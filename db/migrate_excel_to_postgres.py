"""
"fonlar (version 3).xlsx" -> Neon Postgres tek seferlik migration.

Kullanim:
    set DATABASE_URL=postgresql://user:pass@ep-xxxx.neon.tech/dbname   (PowerShell: $env:DATABASE_URL=...)
    python migrate_excel_to_postgres.py --excel "fonlar (version 3).xlsx" --create-schema

Notlar / bilinçli tasarım kararları:
- securities.isin tarihsel Excel'de hiç yok (sadece "Hisseler" sayfasinda
  ticker+uyruk var). Bu yuzden securities surrogate id ile tutuluyor, isin
  NULLABLE. Ileride KAP parser'indan gelen veri ayni (ticker,uyruk) icin
  isin'i otomatik dolduracak (bkz. upsert_securities - ON CONFLICT ... DO
  UPDATE SET isin = COALESCE(securities.isin, EXCLUDED.isin)).
- "Fon-Hisse Dağılımı" sayfasi HER SATIRDA iki ay birden tasiyor: (n-1) ve
  (n). Ayni ay, bir SONRAKI satirda tekrar (n-1) olarak goruniyor - yani
  dogal olarak cakisiyor. Bu yuzden iki tarafi da ayri "snapshot" olarak
  cikarip (fon_kodu, yil, ay, ticker, uyruk) uzerinde dedup ediyoruz.
- Yil rollover: (n-1) Ay > (n) Ay ise (n-1) bir onceki yila aittir
  (ornegin (n-1) Ay=12, (n) Ay=1 -> (n-1) yil = Yil-1).
- Model Portföy sayfasinda MENŞEİ kolonu yok; oradaki hisseler BIST
  (yerli) analist tavsiyeleri oldugu icin uyruk='TC' varsayildi. Bu bir
  VARSAYIM - yanlissa asagidaki MODEL_PORTFOY_UYRUK sabitini degistirin.
- Agirlik: Excel'de kesir olarak tutuluyor (0.0895). Veritabaninda KAP
  PDF'inden gelecek veriyle ayni birimde olmasi icin YUZDE'ye ceviriyoruz
  (0.0895 -> 8.95).
"""
import argparse
import os
import sys
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

MODEL_PORTFOY_UYRUK = 'TC'


def normalize_cols(df):
    df.columns = [str(c).strip().rstrip(',').strip() for c in df.columns]
    return df


def read_sheets(excel_path):
    xls = pd.ExcelFile(excel_path)
    sheets = {}
    for name in ['Hisseler', 'Fonlar', 'Fon-Hisse Dağılımı', 'Model Portföy']:
        df = pd.read_excel(xls, sheet_name=name)
        sheets[name] = normalize_cols(df)
    return sheets


def build_security_keys(sheets):
    """Excel'in tum sayfalarindan gecen (ticker, uyruk) ciftlerinin tam kumesi."""
    keys = set()

    hs = sheets['Hisseler']
    for _, r in hs.iterrows():
        ticker = str(r['Hisse Kod']).strip()
        uyruk = str(r['Uyruk']).strip() if pd.notna(r['Uyruk']) else 'TC'
        if ticker and ticker != 'nan':
            keys.add((ticker, uyruk))

    fh = sheets['Fon-Hisse Dağılımı']
    for _, r in fh.iterrows():
        ticker = str(r['Hisse']).strip()
        uyruk = str(r['MENŞEİ']).strip() if pd.notna(r['MENŞEİ']) else 'TC'
        if ticker and ticker != 'nan':
            keys.add((ticker, uyruk))

    mp = sheets['Model Portföy']
    for _, r in mp.iterrows():
        ticker = str(r['Hisse']).strip()
        if ticker and ticker != 'nan':
            keys.add((ticker, MODEL_PORTFOY_UYRUK))

    return keys


def upsert_securities(cur, keys, names_by_key):
    rows = [(t, u, names_by_key.get((t, u))) for (t, u) in keys]
    execute_values(cur, """
        INSERT INTO securities (ticker, uyruk, ad)
        VALUES %s
        ON CONFLICT (ticker, uyruk) DO UPDATE
            SET ad = COALESCE(securities.ad, EXCLUDED.ad)
    """, rows)

    cur.execute("SELECT id, ticker, uyruk FROM securities")
    return {(ticker, uyruk): sid for sid, ticker, uyruk in cur.fetchall()}


def upsert_funds(cur, fonlar_df):
    # Her fon_kodu icin en son (Yil,Ay) gorulen Kurum/Pazar/Sub Category'yi tut
    latest = (fonlar_df.sort_values(['Yıl', 'Ay'])
                        .groupby('Kodu').tail(1))
    rows = []
    for _, r in latest.iterrows():
        rows.append((
            str(r['Kodu']).strip(),
            str(r['Fon Adı']) if pd.notna(r['Fon Adı']) else str(r['Kodu']),
            str(r['Kurum']) if pd.notna(r['Kurum']) else None,
            str(r['Pazar']) if pd.notna(r['Pazar']) else None,
            str(r['Sub Category']) if pd.notna(r['Sub Category']) else None,
        ))
    execute_values(cur, """
        INSERT INTO funds (fon_kodu, fon_adi, kurucu_kurum, pazar, sub_category)
        VALUES %s
        ON CONFLICT (fon_kodu) DO UPDATE SET
            fon_adi = EXCLUDED.fon_adi,
            kurucu_kurum = EXCLUDED.kurucu_kurum,
            pazar = EXCLUDED.pazar,
            sub_category = EXCLUDED.sub_category
    """, rows)
    return len(rows)


def upsert_fund_aum(cur, fonlar_df):
    rows = []
    for _, r in fonlar_df.iterrows():
        if pd.isna(r['Kodu']) or pd.isna(r['Yıl']) or pd.isna(r['Ay']):
            continue
        rows.append((
            str(r['Kodu']).strip(), int(r['Yıl']), int(r['Ay']),
            float(r['Hacim']) if pd.notna(r['Hacim']) else None,
            'EXCEL_MANUEL',
        ))
    execute_values(cur, """
        INSERT INTO fund_aum_monthly (fon_kodu, yil, ay, fon_toplam_degeri, kaynak)
        VALUES %s
        ON CONFLICT (fon_kodu, yil, ay) DO UPDATE SET
            fon_toplam_degeri = EXCLUDED.fon_toplam_degeri
    """, rows)
    return len(rows)


def _shift_year(yil, ay_n, ay_other):
    """(n-1) Ay, (n) Ay'dan buyukse (n-1) bir onceki yila aittir (Aralik->Ocak gecisi)."""
    if ay_other > ay_n:
        return yil - 1
    return yil


def extract_holding_snapshots(fh_df):
    """Her satirdan (n-1) ve (n) snapshot'larini cikarir, dedup icin dict kullanir."""
    snapshots = {}
    skipped = 0
    for _, r in fh_df.iterrows():
        fon_kodu = str(r['Kodu']).strip() if pd.notna(r['Kodu']) else None
        ticker = str(r['Hisse']).strip() if pd.notna(r['Hisse']) else None
        uyruk = str(r['MENŞEİ']).strip() if pd.notna(r['MENŞEİ']) else 'TC'
        yil = r['Yıl']
        if not fon_kodu or not ticker or pd.isna(yil):
            skipped += 1
            continue
        yil = int(yil)
        ay_n = r['(n) Ay']
        ay_n1 = r['(n-1) Ay']

        if pd.notna(ay_n) and pd.notna(r['(n) TL']):
            key = (fon_kodu, yil, int(ay_n), ticker, uyruk)
            snapshots[key] = (float(r['(n) TL']), float(r['(n) Ağırlık']) * 100 if pd.notna(r['(n) Ağırlık']) else None)

        if pd.notna(ay_n1) and pd.notna(r['(n-1) TL']):
            yil_n1 = _shift_year(yil, int(ay_n), int(ay_n1)) if pd.notna(ay_n) else yil
            key = (fon_kodu, yil_n1, int(ay_n1), ticker, uyruk)
            # (n) tarafi zaten varsa onu koru (daha guvenilir taraf, cunku
            # (n-1) bir onceki satirin (n)'i ile ayni olmali - cakisirsa sorun yok)
            snapshots.setdefault(key, (float(r['(n-1) TL']), float(r['(n-1) Ağırlık']) * 100 if pd.notna(r['(n-1) Ağırlık']) else None))

    return snapshots, skipped


def upsert_fund_holdings(cur, snapshots, sec_cache):
    rows = []
    unresolved = set()
    for (fon_kodu, yil, ay, ticker, uyruk), (tl, agirlik) in snapshots.items():
        sid = sec_cache.get((ticker, uyruk))
        if sid is None:
            unresolved.add((ticker, uyruk))
            continue
        if agirlik is None:
            continue
        rows.append((fon_kodu, yil, ay, sid, tl, agirlik, 'EXCEL_MANUEL'))

    execute_values(cur, """
        INSERT INTO fund_holdings (fon_kodu, yil, ay, security_id, toplam_tutar_tl, agirlik_pct, kaynak)
        VALUES %s
        ON CONFLICT (fon_kodu, yil, ay, security_id) DO UPDATE SET
            toplam_tutar_tl = EXCLUDED.toplam_tutar_tl,
            agirlik_pct = EXCLUDED.agirlik_pct
    """, rows)
    return len(rows), unresolved


def upsert_model_portfolio(cur, mp_df, sec_cache):
    rows = []
    for _, r in mp_df.iterrows():
        if pd.isna(r['Kurum']) or pd.isna(r['Yıl']) or pd.isna(r['Ay']) or pd.isna(r['Hisse']):
            continue
        ticker = str(r['Hisse']).strip()
        sid = sec_cache.get((ticker, MODEL_PORTFOY_UYRUK))
        rows.append((
            str(r['Kurum']).strip(), int(r['Yıl']), int(r['Ay']), ticker, sid,
            str(r['Tavsiye']) if pd.notna(r['Tavsiye']) else None,
            float(r['Güncel Fiyat']) if pd.notna(r['Güncel Fiyat']) else None,
            float(r['Hedef Fiyat']) if pd.notna(r['Hedef Fiyat']) else None,
            float(r['Potansiyel']) * 100 if pd.notna(r['Potansiyel']) else None,
        ))
    execute_values(cur, """
        INSERT INTO model_portfolio_recommendations
            (kurum, yil, ay, ticker, security_id, tavsiye, guncel_fiyat, hedef_fiyat, potansiyel_pct)
        VALUES %s
        ON CONFLICT (kurum, yil, ay, ticker) DO UPDATE SET
            guncel_fiyat = EXCLUDED.guncel_fiyat,
            hedef_fiyat = EXCLUDED.hedef_fiyat,
            potansiyel_pct = EXCLUDED.potansiyel_pct
    """, rows)
    return len(rows)


def log_etl_run(cur, kaynak, durum, detay):
    cur.execute("""
        INSERT INTO etl_runs (kaynak, durum, detay) VALUES (%s, %s, %s)
    """, (kaynak, durum, detay))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--excel', required=True, help='fonlar (version 3).xlsx dosya yolu')
    ap.add_argument('--create-schema', action='store_true', help='faz1_schema.sql dosyasini once calistir')
    ap.add_argument('--schema-file', default='faz1_schema.sql')
    ap.add_argument('--dsn', default=os.environ.get('DATABASE_URL'), help='Postgres connection string (yoksa DATABASE_URL env)')
    args = ap.parse_args()

    if not args.dsn:
        sys.exit("HATA: --dsn verilmedi ve DATABASE_URL environment variable'i da yok.")

    print(f"[{datetime.now()}] Excel okunuyor: {args.excel}")
    sheets = read_sheets(args.excel)

    conn = psycopg2.connect(args.dsn)
    try:
        with conn:
            with conn.cursor() as cur:
                if args.create_schema:
                    print("Sema olusturuluyor...")
                    with open(args.schema_file, encoding='utf-8') as f:
                        cur.execute(f.read())

                print("Menkul kiymetler (securities) upsert ediliyor...")
                keys = build_security_keys(sheets)
                names_by_key = {}
                for _, r in sheets['Hisseler'].iterrows():
                    if pd.notna(r['Hisse Kod']):
                        uyruk = str(r['Uyruk']).strip() if pd.notna(r['Uyruk']) else 'TC'
                        ad = str(r['Tam Ad']) if pd.notna(r['Tam Ad']) else None
                        if ad:
                            names_by_key[(str(r['Hisse Kod']).strip(), uyruk)] = ad
                sec_cache = upsert_securities(cur, keys, names_by_key)
                print(f"  -> {len(sec_cache)} menkul kiymet")

                print("Fonlar (master data) upsert ediliyor...")
                n_funds = upsert_funds(cur, sheets['Fonlar'])
                print(f"  -> {n_funds} fon")

                print("Fon AUM (aylik buyukluk) upsert ediliyor...")
                n_aum = upsert_fund_aum(cur, sheets['Fonlar'])
                print(f"  -> {n_aum} fon-ay AUM satiri")

                print("Fon-hisse dagilimi cikariliyor (n-1/n unpivot + dedup)...")
                snapshots, skipped = extract_holding_snapshots(sheets['Fon-Hisse Dağılımı'])
                print(f"  -> {len(snapshots)} tekil (fon, yil, ay, hisse) snapshot, {skipped} satir atlandi (eksik alan)")

                n_holdings, unresolved = upsert_fund_holdings(cur, snapshots, sec_cache)
                print(f"  -> {n_holdings} fund_holdings satiri yazildi")
                if unresolved:
                    print(f"  UYARI: {len(unresolved)} (ticker, uyruk) cifti securities'te bulunamadi: {list(unresolved)[:10]}...")
                    log_etl_run(cur, 'EXCEL_MANUEL', 'UYUMSUZLUK', f"{len(unresolved)} unresolved ticker/uyruk: {sorted(unresolved)[:50]}")

                print("Model portfoy tavsiyeleri upsert ediliyor...")
                n_model = upsert_model_portfolio(cur, sheets['Model Portföy'], sec_cache)
                print(f"  -> {n_model} tavsiye satiri")

                log_etl_run(cur, 'EXCEL_MANUEL', 'OK',
                            f"securities={len(sec_cache)} funds={n_funds} aum={n_aum} "
                            f"holdings={n_holdings} model={n_model} skipped={skipped}")

        print("Migration tamamlandi ve commit edildi.")
    except Exception as e:
        conn.rollback()
        print(f"HATA - rollback yapildi: {e}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
