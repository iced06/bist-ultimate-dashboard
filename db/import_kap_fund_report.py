"""
KAP "Fon Portfoy Dagilim Raporu" PDF -> Postgres (bist semasi) import script.

Kullanim:
    python db/import_kap_fund_report.py <PDF_URL_veya_yerel_yol> [<...> ...] [--dsn "postgresql://..."]

--dsn verilmezse DATABASE_URL environment variable'i kullanilir.

Her kaynak icin:
  1. (URL ise) indirilir; KAP'in bazi endpoint'leri PDF'i bir Java serialization
     zarfina sariyor - bu aynen sirket_raporlari.py._download_pdf_bytes'taki
     ve migrate_excel_to_postgres.py'daki gibi '%PDF' imzasina kadar atilarak
     temizlenir (pilotta kesfedildi, 4 fonda da dogrulandi).
  2. kap_portfolio_parser ile parse edilir (hisse senedi holdings + katilma
     payi giris/cikis - bkz. o modulun basindaki notlar).
  3. RECONCILIATION KONTROLU: parser'in hesapladigi toplam agirlik, PDF'in
     kendi yazdigi GRUP TOPLAMI ile karsilastirilir. Uyusmuyorsa GUVENLIK
     ICIN HICBIR SEY YAZILMAZ - sadece etl_runs'a 'UYUMSUZLUK' olarak
     loglanir (sessiz veri bozulmasindansa gorunur bir uyari tercih edilir -
     bkz. Faz 3'teki "sessiz hata yutma" bulgusu).
  4. securities/funds tablolarina gerekirse yeni kayit eklenir (upsert).
  5. fund_aum_monthly ve fund_holdings'e upsert yapilir - ayni (fon, yil, ay)
     tekrar import edilirse idempotent guncellenir (KAP duzeltme raporu
     yayinlayabiliyor).
  6. Her calisma etl_runs'a loglanir (OK / UYUMSUZLUK / HATA).
"""
import sys
import os
import io
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kap_portfolio_parser import parse_pdf_text, aggregate_by_isin

try:
    import requests
except ImportError:
    requests = None
try:
    import pdfplumber
except ImportError:
    pdfplumber = None
try:
    import psycopg2
except ImportError:
    psycopg2 = None


def _download_pdf_bytes(url):
    """bkz. sirket_raporlari.py._download_pdf_bytes - ayni zarf-temizleme mantigi."""
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    data = resp.content
    if data[:4] == b'%PDF':
        return data
    idx = data.find(b'%PDF')
    if idx == -1:
        raise ValueError("İndirilen dosya bir PDF gibi görünmüyor (%PDF imzası bulunamadı).")
    return data[idx:]


def _load_pdf_text(path_or_url):
    if path_or_url.startswith('http://') or path_or_url.startswith('https://'):
        if requests is None:
            raise RuntimeError("requests paketi kurulu değil - URL indirilemez.")
        data = _download_pdf_bytes(path_or_url)
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return '\n'.join((p.extract_text() or '') for p in pdf.pages)
    with pdfplumber.open(path_or_url) as pdf:
        return '\n'.join((p.extract_text() or '') for p in pdf.pages)


def _infer_uyruk(isin):
    return 'TC' if isin.startswith('TR') else 'FOR'


def _upsert_security(cur, isin, ticker, uyruk):
    """securities'te isin UNIQUE'dir; (ticker, uyruk) ise SADECE isin BOS
    olan (tarihsel Excel kaynakli) kayitlar icin partial-unique'dir (bkz.
    schema.sql - idx_securities_ticker_uyruk_legacy). Bu FARK bilerek boyle:
    yabanci hisselerde ayni ticker'i FARKLI sirketlerin paylasmasi COK
    yaygin (orn. "SAN" hem Sanofi=FR0000120578 hem Santander=ES0113900J37
    olabiliyor; TMG fonu pilotunda gercek veriyle yakalandi) - bu yuzden
    ticker+uyruk'e gore eslestirme SADECE isin'i hala BOS olan eski bir
    Excel kaydini doldurmak icin kullanilir, ISIN'i DOLU baska bir sirketle
    ASLA birlestirilmez (o zaman guvenle yeni bir satir acilir)."""
    cur.execute("SELECT id FROM securities WHERE isin = %s", (isin,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE securities SET ticker = %s WHERE id = %s", (ticker, row[0]))
        return row[0]

    cur.execute("SELECT id FROM securities WHERE ticker = %s AND uyruk = %s AND isin IS NULL",
                (ticker, uyruk))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE securities SET isin = %s WHERE id = %s", (isin, row[0]))
        return row[0]

    cur.execute("""
        INSERT INTO securities (isin, ticker, uyruk, varlik_sinifi)
        VALUES (%s, %s, %s, 'HISSE_SENEDI')
        RETURNING id
    """, (isin, ticker, uyruk))
    return cur.fetchone()[0]


def _log_etl(conn, fon_kodu, yil, ay, durum, detay):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO etl_runs (kaynak, fon_kodu, donem_yil, donem_ay, durum, detay)
            VALUES ('KAP_PDF', %s, %s, %s, %s, %s)
        """, (fon_kodu or None, yil or None, ay or None, durum, detay))


def import_one(conn, path_or_url):
    """Tek bir KAP fon portfoy raporu PDF'ini parse edip DB'ye yazar.
    Donus: (basarili_mi: bool, detay_mesaji: str)."""
    text = _load_pdf_text(path_or_url)
    result = parse_pdf_text(text)
    holdings = aggregate_by_isin(result, 'HISSE_SENEDI')
    total_weight = sum(h['agirlik_ftd_pct'] for h in holdings)
    printed_total = result.printed_group_totals.get('HISSE_SENEDI')
    recon_ok = printed_total is not None and abs(printed_total - total_weight) < 0.05

    fon_kodu, yil, ay = result.fon_kodu, result.donem_yil, result.donem_ay
    if not fon_kodu or not yil or not ay:
        detay = f"Fon kodu/donem parse edilemedi (fon_kodu={fon_kodu!r}, yil={yil}, ay={ay})"
        _log_etl(conn, fon_kodu, yil, ay, 'HATA', detay)
        return False, detay

    if not recon_ok:
        detay = (f"Reconciliation basarisiz: hesaplanan agirlik {total_weight:.2f}% != "
                 f"PDF GRUP TOPLAMI {printed_total}% - GUVENLIK ICIN YAZILMADI. "
                 f"unmatched_prefix_tokens={result.unmatched_prefix_tokens}, "
                 f"unknown_sections={len(result.unknown_sections)} satir")
        _log_etl(conn, fon_kodu, yil, ay, 'UYUMSUZLUK', detay)
        return False, detay

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO funds (fon_kodu, fon_adi)
            VALUES (%s, %s)
            ON CONFLICT (fon_kodu) DO UPDATE SET fon_adi = EXCLUDED.fon_adi
        """, (fon_kodu, result.fon_adi))

        cur.execute("""
            INSERT INTO fund_aum_monthly (fon_kodu, yil, ay, katilma_payi_giris_tl, katilma_payi_cikis_tl, kaynak)
            VALUES (%s, %s, %s, %s, %s, 'KAP_PDF')
            ON CONFLICT (fon_kodu, yil, ay) DO UPDATE SET
                katilma_payi_giris_tl = EXCLUDED.katilma_payi_giris_tl,
                katilma_payi_cikis_tl = EXCLUDED.katilma_payi_cikis_tl,
                kaynak = 'KAP_PDF'
        """, (fon_kodu, yil, ay, result.katilma_payi_giris_tl, result.katilma_payi_cikis_tl))

        n_written = 0
        for h in holdings:
            isin = h['isin']
            uyruk = _infer_uyruk(isin)
            security_id = _upsert_security(cur, isin, h['ticker'], uyruk)

            cur.execute("""
                INSERT INTO fund_holdings
                    (fon_kodu, yil, ay, security_id, nominal_deger, toplam_tutar_tl,
                     agirlik_pct, lot_sayisi, kaynak)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'KAP_PDF')
                ON CONFLICT (fon_kodu, yil, ay, security_id) DO UPDATE SET
                    nominal_deger = EXCLUDED.nominal_deger,
                    toplam_tutar_tl = EXCLUDED.toplam_tutar_tl,
                    agirlik_pct = EXCLUDED.agirlik_pct,
                    lot_sayisi = EXCLUDED.lot_sayisi,
                    kaynak = EXCLUDED.kaynak
            """, (fon_kodu, yil, ay, security_id, h['nominal_deger'], h['toplam_tutar_tl'],
                  h['agirlik_ftd_pct'], h['lot_sayisi']))
            n_written += 1

    detay = (f"{n_written} hisse yazildi, agirlik {total_weight:.2f}% (PDF: {printed_total}%), "
             f"katilma payi giris/cikis yontemi: {result.katilma_payi_extract_method}")
    if result.unmatched_prefix_tokens:
        detay += f" | UYARI unmatched_prefix_tokens={result.unmatched_prefix_tokens}"
    if result.katilma_payi_extract_method == 'UNRESOLVED':
        detay += " | UYARI katilma payi giris/cikis bulunamadi (NULL birakildi)"
    _log_etl(conn, fon_kodu, yil, ay, 'OK', detay)
    return True, detay


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sources', nargs='+', help='KAP PDF URL veya yerel dosya yolu (birden fazla verilebilir)')
    ap.add_argument('--dsn', default=os.getenv('DATABASE_URL'),
                     help="Postgres connection string (verilmezse DATABASE_URL environment variable'i kullanilir)")
    args = ap.parse_args()

    if psycopg2 is None:
        print("HATA: psycopg2 kurulu değil.", file=sys.stderr)
        sys.exit(1)
    if pdfplumber is None:
        print("HATA: pdfplumber kurulu değil.", file=sys.stderr)
        sys.exit(1)
    if not args.dsn:
        print("HATA: --dsn verilmedi ve DATABASE_URL environment variable'i da yok.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(args.dsn)
    conn.autocommit = True  # her upsert kendi basina idempotent - kismi hata durumunda
                             # onceki basarili satirlar geri alinmaz (rerun ile tamamlanir)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO bist, public;")

    exit_code = 0
    for src in args.sources:
        print(f"\n=== {src} ===")
        try:
            ok, detay = import_one(conn, src)
            print(("OK: " if ok else "ATLANDI: ") + detay)
            if not ok:
                exit_code = 1
        except Exception as e:
            print(f"HATA: {e}")
            try:
                _log_etl(conn, None, None, None, 'HATA', f"{src}: {e}")
            except Exception:
                pass
            exit_code = 1

    conn.close()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
