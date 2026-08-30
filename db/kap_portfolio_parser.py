"""
KAP "Fon Portföy Dağılım Raporu" PDF parser - pilot v2.

Girdi: KAP'tan indirilmiş, Java-serialization zarfindan temizlenmis PDF.
Cikti: fon icindeki her menkul kiymet lotu icin normalize edilmis satirlar +
       ISIN bazinda aggregate edilmis (fon, donem, hisse) tablosu.

Bilinen sinirlamalar (readme_findings.md'de detayli):
- "Tem.Ver." gibi az sayida bilinen on-ek disinda yeni bir on-ek turu
  cikarsa ticker yanlis yakalanabilir -> unmatched_prefix_tokens listesine
  loglanir, sessizce yutulmaz.
- Bolum basliklari (HISSE SENETLERI / BORCLANMA SENETLERI / DIGER / ...)
  KAP sablonunda gozlemlenen isimlerle esleseiyor; yeni bir fon turunde
  farkli bir baslik cikarsa o blok "UNKNOWN" bolumune duser ve rapor edilir.
"""
import re
import sys
import json
from dataclasses import dataclass, field, asdict

ISIN_RE = re.compile(r'\b[A-Z]{2}[A-Z0-9]{9}\d\b')
NUM_RE = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d+')
DATE_RE = re.compile(r'\b\d{2}/\d{2}/\d{2}\b')
BORSA_KODU_RE = re.compile(r'\b\d{8}\b')

# II. Bolum - fon toplam nakit giris/cikisi (katilma payi ihrac/iade).
# PDF'te iki farkli duzen gozlemlendi (4 fonun 4'unde de dogrulandi):
#   - Cogunlukla (HVS/NHY/TMG): "<etiket> (TL) : <sayi>" tek satirda.
#   - DOH'ta: etiketler blok halinde, degerler baska bir blokta AYNI SIRAYLA
#     geliyor (pdfplumber'in bu PDF'teki cok-sutunlu duzeni linearize etme
#     bicimi farkli) - bu yuzden "ayni satir" basarisiz olursa yakin satirlarda
#     yalniz duran (sadece ":" + sayi) satirlari sirayla eslestiren bir
#     fallback var.
GIRIS_LABEL_RE = re.compile(r'Katılma Payı İhraçlarından Kaynaklanan Nakit Girişleri \(TL\)')
CIKIS_LABEL_RE = re.compile(r'Katılma Payı İadelerinden Kaynaklanan Nakit Çıkışları \(TL\)')
ORPHAN_NUM_LINE_RE = re.compile(r'^\s*:?\s*(-?\d{1,3}(?:\.\d{3})*,\d+)\s*$')

TURKISH_MONTHS = {
    'ocak': 1, 'şubat': 2, 'subat': 2, 'mart': 3, 'nisan': 4, 'mayıs': 5, 'mayis': 5,
    'haziran': 6, 'temmuz': 7, 'ağustos': 8, 'agustos': 8, 'eylül': 9, 'eylul': 9,
    'ekim': 10, 'kasım': 11, 'kasim': 11, 'aralık': 12, 'aralik': 12,
}

# Bolum basligi -> normalize edilmis kategori adi
SECTION_HEADERS = {
    'HİSSE SENETLERİ': 'HISSE_SENEDI',
    'BORÇLANMA SENETLERİ': 'BORCLANMA_SENEDI',
    'DİĞER': 'DIGER',
    'MEVDUAT': 'MEVDUAT',
    'REPO': 'REPO',
    'T.REPO': 'REPO',
    'TPP': 'TPP',
}
# Bu satirlar bolum degistirmez, sadece alt-etiket (Hisse Turk / Hisse Yabanci vb.)
SUB_LABEL_LINES = {
    'Hisse Türk', 'Hisse Yabancı', 'Devlet Tahvili', 'Eurobond Yabancı',
    'Özel Sektör', 'Borsa Y.Fonu Türk', 'Borsa Y.Fonu Yabancı', 'Y.Fonu Türk', 'Döviz',
}
KNOWN_NOISE_PREFIXES = {'Tem.Ver.', 'Tem.Alac.'}

STOP_LINE_RE = re.compile(r'^(GRUP TOPLAMI|FON PORTFÖY DEĞERİ|IV-FON|V-AY|VI-)')


@dataclass
class Lot:
    section: str
    ticker: str
    isin: str
    nominal_deger: float
    tarih: str
    toplam_tutar_tl: float
    agirlik_grup_pct: float
    agirlik_fpd_pct: float
    agirlik_ftd_pct: float
    raw_line: str


@dataclass
class ParseResult:
    fon_kodu: str = ''
    fon_adi: str = ''
    donem_yil: int = 0
    donem_ay: int = 0
    lots: list = field(default_factory=list)
    unmatched_prefix_tokens: list = field(default_factory=list)
    unknown_sections: list = field(default_factory=list)
    pledge_disclosures: list = field(default_factory=list)
    printed_group_totals: dict = field(default_factory=dict)
    katilma_payi_giris_tl: float = None
    katilma_payi_cikis_tl: float = None
    katilma_payi_extract_method: str = ''  # 'same-line' | 'block-fallback' | 'UNRESOLVED'


def _to_float(s):
    return float(s.replace('.', '').replace(',', '.'))


def _extract_katilma_payi(all_text):
    """II. bolumdeki fon nakit giris/cikisini (katilma payi ihrac/iade) cikarir.
    4 gercek fonun 4'unde de dogrulandi (bkz. dosya basindaki not).
    Donus: (giris_tl, cikis_tl, yontem) - hicbiri bulunamazsa (None, None, 'UNRESOLVED')."""
    lines = all_text.split('\n')
    giris_idx = cikis_idx = None
    for i, line in enumerate(lines):
        if giris_idx is None and GIRIS_LABEL_RE.search(line):
            giris_idx = i
        if cikis_idx is None and CIKIS_LABEL_RE.search(line):
            cikis_idx = i
    if giris_idx is None or cikis_idx is None:
        return None, None, 'UNRESOLVED'

    # Once en yaygin durum: deger etiketle ayni satirda ("... (TL) : 123,45").
    giris_val = cikis_val = None
    m = NUM_RE.search(lines[giris_idx])
    if m:
        giris_val = _to_float(m.group(0))
    m = NUM_RE.search(lines[cikis_idx])
    if m:
        cikis_val = _to_float(m.group(0))
    if giris_val is not None and cikis_val is not None:
        return giris_val, cikis_val, 'same-line'

    # Fallback: bazi PDF'lerde (orn. DOH) deger etiketle ayni satirda degil,
    # yalniz duran (":" + sayi) bir satirda - ve bu satir etiketten ONCE de
    # SONRA da gelebiliyor (pdfplumber'in bu PDF'teki cok-sutunlu duzeni
    # linearize etme sirasina gore degisiyor). Her iki etiketin ETRAFINDAKI
    # dar bir pencerede yalniz sayi satirlarini toplayip, HER etikete EN
    # YAKIN kullanilmamis adayi atar.
    lo = max(0, min(giris_idx, cikis_idx) - 3)
    hi = min(len(lines), max(giris_idx, cikis_idx) + 8)
    candidates = []
    for i in range(lo, hi):
        if i in (giris_idx, cikis_idx):
            continue
        m = ORPHAN_NUM_LINE_RE.match(lines[i])
        if m:
            candidates.append((i, _to_float(m.group(1))))

    used = set()
    if giris_val is None:
        remaining = sorted((c for c in candidates if c[0] not in used), key=lambda c: abs(c[0] - giris_idx))
        if remaining:
            giris_val = remaining[0][1]
            used.add(remaining[0][0])
    if cikis_val is None:
        remaining = sorted((c for c in candidates if c[0] not in used), key=lambda c: abs(c[0] - cikis_idx))
        if remaining:
            cikis_val = remaining[0][1]
            used.add(remaining[0][0])

    if giris_val is not None and cikis_val is not None:
        return giris_val, cikis_val, 'nearby-orphan-fallback'
    return giris_val, cikis_val, 'UNRESOLVED'


def _parse_header(all_text):
    first_lines = [l.strip() for l in all_text.split('\n')[:2] if l.strip()]
    fon_kodu, fon_adi, yil, ay = '', '', 0, 0
    if first_lines:
        m = re.match(r'^([A-ZÇĞİÖŞÜ0-9]+)\s*-\s*(.+)$', first_lines[0])
        if m:
            fon_kodu, fon_adi = m.group(1), m.group(2)
        else:
            fon_adi = first_lines[0]
    if len(first_lines) > 1:
        m = re.match(r'([A-Za-zçğıöşüÇĞİÖŞÜ]+)-(\d{4})', first_lines[1])
        if m:
            ay = TURKISH_MONTHS.get(m.group(1).lower(), 0)
            yil = int(m.group(2))
    return fon_kodu, fon_adi, yil, ay


def _extract_ticker(prefix_tokens, unmatched_log, raw_line):
    if not prefix_tokens:
        return '', False
    if prefix_tokens[0] in KNOWN_NOISE_PREFIXES:
        return (prefix_tokens[1] if len(prefix_tokens) > 1 else ''), True
    # Bilinmeyen bir on-ek turu olabilir mi? (ilk token harf+nokta iceriyorsa supheli)
    if re.match(r'^[A-Za-zÇĞİÖŞÜçğıöşü]+\.$', prefix_tokens[0]) and prefix_tokens[0] not in KNOWN_NOISE_PREFIXES:
        unmatched_log.append({'token': prefix_tokens[0], 'raw_line': raw_line})
        return (prefix_tokens[1] if len(prefix_tokens) > 1 else ''), True
    return prefix_tokens[0], False


def parse_pdf_text(all_text: str) -> ParseResult:
    result = ParseResult()
    result.fon_kodu, result.fon_adi, result.donem_yil, result.donem_ay = _parse_header(all_text)
    (result.katilma_payi_giris_tl, result.katilma_payi_cikis_tl,
     result.katilma_payi_extract_method) = _extract_katilma_payi(all_text)

    current_section = 'UNKNOWN'
    lines = [l.strip() for l in all_text.split('\n')]

    for line in lines:
        if not line:
            continue
        if line in SUB_LABEL_LINES:
            continue
        if line in SECTION_HEADERS:
            current_section = SECTION_HEADERS[line]
            continue
        if STOP_LINE_RE.match(line):
            if line.startswith('GRUP TOPLAMI') and current_section not in result.printed_group_totals:
                nums = NUM_RE.findall(line)
                if len(nums) >= 3:
                    result.printed_group_totals[current_section] = _to_float(nums[-1])
            continue

        isin_match = ISIN_RE.search(line)
        if not isin_match:
            continue
        isin = isin_match.group(0)

        prefix = line[:isin_match.start()].split()
        ticker, flagged = _extract_ticker(prefix, result.unmatched_prefix_tokens, line)
        if not ticker:
            continue
        if prefix and prefix[0] in KNOWN_NOISE_PREFIXES:
            # "Tem.Ver." (teminata verilen) satirlari zaten baska bir satirda
            # sayilan pozisyonun alt-aciklamasidir - ayri bir lot DEGILDIR.
            # Aggregate'e katarsak ayni hisseyi cift saymis oluruz.
            result.pledge_disclosures.append(line)
            continue

        nums = NUM_RE.findall(line)
        dates = DATE_RE.findall(line)
        if len(nums) < 4 or not dates:
            # ISIN tasiyan ama beklenen sayisal alanlara sahip olmayan satir
            # (ör. baslik tekrari) - atla.
            continue

        nominal = _to_float(nums[0])
        toplam_tutar = _to_float(nums[-4]) if len(nums) >= 4 else 0.0
        pct_grup, pct_fpd, pct_ftd = (
            _to_float(nums[-3]), _to_float(nums[-2]), _to_float(nums[-1])
        )

        if current_section == 'UNKNOWN':
            result.unknown_sections.append(line)
            continue

        result.lots.append(Lot(
            section=current_section,
            ticker=ticker,
            isin=isin,
            nominal_deger=nominal,
            tarih=dates[0],
            toplam_tutar_tl=toplam_tutar,
            agirlik_grup_pct=pct_grup,
            agirlik_fpd_pct=pct_fpd,
            agirlik_ftd_pct=pct_ftd,
            raw_line=line,
        ))

    return result


def aggregate_by_isin(result: ParseResult, section='HISSE_SENEDI'):
    agg = {}
    for lot in result.lots:
        if lot.section != section:
            continue
        key = lot.isin
        if key not in agg:
            agg[key] = {
                'ticker': lot.ticker, 'isin': lot.isin,
                'nominal_deger': 0.0, 'toplam_tutar_tl': 0.0,
                'agirlik_ftd_pct': 0.0, 'lot_sayisi': 0,
            }
        agg[key]['nominal_deger'] += lot.nominal_deger
        agg[key]['toplam_tutar_tl'] += lot.toplam_tutar_tl
        agg[key]['agirlik_ftd_pct'] += lot.agirlik_ftd_pct
        agg[key]['lot_sayisi'] += 1
    return list(agg.values())


if __name__ == '__main__':
    import pdfplumber

    for path in sys.argv[1:]:
        with pdfplumber.open(path) as pdf:
            text = '\n'.join((p.extract_text() or '') for p in pdf.pages)
        result = parse_pdf_text(text)
        holdings = aggregate_by_isin(result, 'HISSE_SENEDI')
        total_weight = sum(h['agirlik_ftd_pct'] for h in holdings)

        printed_total = result.printed_group_totals.get('HISSE_SENEDI')
        ok = printed_total is not None and abs(printed_total - total_weight) < 0.05

        print(f"\n=== {path} ===")
        print(f"Fon: {result.fon_kodu} - {result.fon_adi} | Donem: {result.donem_ay}/{result.donem_yil}")
        print(f"Hisse senedi kalemi (aggregate sonrasi): {len(holdings)}")
        print(f"Hesaplanan toplam agirlik (FTD bazli): {total_weight:.2f}%")
        print(f"PDF'de yazan GRUP TOPLAMI (FTD bazli): {printed_total}")
        print(f"Reconciliation: {'OK - eslesti' if ok else 'UYUSMUYOR - incele!'}")
        if result.katilma_payi_extract_method == 'UNRESOLVED':
            print("UYARI - katilma payi girisi/cikisi bulunamadi (nakit akisi verisi eksik kalacak)")
        else:
            print(f"Katilma Payi Girisi (TL): {result.katilma_payi_giris_tl:,.2f} "
                  f"| Cikisi (TL): {result.katilma_payi_cikis_tl:,.2f} "
                  f"(yontem: {result.katilma_payi_extract_method})")
        if result.pledge_disclosures:
            print(f"Bilgi - {len(result.pledge_disclosures)} teminata verilmis alt-aciklama satiri aggregate disi birakildi")
        if result.unmatched_prefix_tokens:
            print(f"UYARI - bilinmeyen on-ek: {result.unmatched_prefix_tokens}")
        if result.unknown_sections:
            print(f"UYARI - bolumu belirlenemeyen {len(result.unknown_sections)} satir")

        out_path = path.replace('.pdf', '_v2_holdings.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump({
                'fon_kodu': result.fon_kodu, 'fon_adi': result.fon_adi,
                'donem_yil': result.donem_yil, 'donem_ay': result.donem_ay,
                'katilma_payi_giris_tl': result.katilma_payi_giris_tl,
                'katilma_payi_cikis_tl': result.katilma_payi_cikis_tl,
                'holdings': holdings,
            }, f, ensure_ascii=False, indent=1)
