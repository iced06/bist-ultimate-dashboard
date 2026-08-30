"""
KAP "Fon Portföy Dağılım Raporu" PDF parser - pilot v2.

Girdi: KAP'tan indirilmiş, Java-serialization zarfindan temizlenmis PDF.
Cikti: fon icindeki her menkul kiymet lotu icin normalize edilmis satirlar +
       ISIN (veya ISIN yoksa ticker) bazinda aggregate edilmis (fon, donem,
       hisse) tablosu.

IKI FARKLI RAPOR SABLONU ("dialect") gozlemlendi - ilk 4 fonluk pilotta
(Tera/HSBC/İş Portföy/Neo) hepsi AYNI sablonu (Format A) kullaniyordu, bu
yuzden "SPK'nin tek bir zorunlu formati var" varsayimi yapilmisti. 5. fonda
(Ata Portföy) FARKLI bir sablon (Format B) cikti - bu yuzden iki ayri
ayristirici var, ilk satirdaki basliga gore otomatik secilir:
  - Format A ("{KOD}-{FON ADI}" basligi): satirlarda ISIN var, Turkce sayi
    formati (1.234.567,89), bolumler "HİSSE SENETLERİ" duz satir, toplam
    "GRUP TOPLAMI ... %" satirinda.
  - Format B ("{KOD} FON {AY} {YIL} PORTFÖY DAĞILIM RAPORU" basligi):
    hisse senedi satirlarinda ISIN YOK (sadece BIST ticker), Ingilizce sayi
    formati (1,234,567.89), bolumler "A) HİSSE SENETLERİ" harfli, toplam
    "TOPLAM: <nominal> <rayic>" satirinda (yuzde YOK - reconciliation TL
    toplamina gore yapiliyor, % degil).

Bilinen sinirlamalar (readme_findings.md'de detayli):
- "Tem.Ver." gibi az sayida bilinen on-ek disinda yeni bir on-ek turu
  cikarsa ticker yanlis yakalanabilir -> unmatched_prefix_tokens listesine
  loglanir, sessizce yutulmaz.
- Bolum basliklari (HISSE SENETLERI / BORCLANMA SENETLERI / DIGER / ...)
  KAP sablonunda gozlemlenen isimlerle esleseiyor; yeni bir fon turunde
  farkli bir baslik cikarsa o blok "UNKNOWN" bolumune duser ve rapor edilir.
- Iki dialect disinda UCUNCU bir sablon cikarsa (baslik hicbirine
  uymazsa), Format A varsayilan olarak denenir - muhtemelen 0 satir
  yakalar ve reconciliation basarisiz olup GUVENLI sekilde reddedilir
  (yanlis veri yazmaz), ama parse_pdf_text'e yeni bir dialect eklemek
  gerekecektir.
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


def _tr_lower(s):
    """Python'un varsayilan str.lower()'i Turkce buyuk 'İ' harfini 'i' +
    BIRLESIK NOKTA (U+0307) olarak kucultur, duz ASCII 'i' DEGIL - bu yuzden
    "HAZİRAN".lower() 'haziran' ile EŞLEŞMEZ (klasik "Turkish-I" hatasi).
    Gercek veriyle yakalandi: AYA fonunun Haziran raporunda ay=0 cikti,
    Temmuz raporunda İ olmadigi icin sansla calismisti. Once 'İ'/'I' harflerini
    ACIKCA degistirip sonra kucultuyoruz."""
    return s.replace('İ', 'i').replace('I', 'ı').lower()

# ── Format B (Ata Portföy'de gozlemlendi) ──
# Ingilizce sayi formati (virgul=binlik, nokta=ondalik) - Format A'nin
# Turkce formatindan (nokta=binlik, virgul=ondalik) TAM TERSI.
FORMAT_B_TITLE_RE = re.compile(
    r'^([A-ZÇĞİÖŞÜ0-9]+)\s+FON\s+([A-ZÇĞİÖŞÜ]+)\s+(\d{4})\s+PORTF[ÖO]Y\s+DA[ĞG]ILIM\s+RAPORU',
    re.IGNORECASE,
)
FORMAT_B_FON_ADI_RE = re.compile(r'^A\.\s*FONUN ADI\s*:\s*(.+)$', re.IGNORECASE)
FORMAT_B_SECTION_RE = re.compile(r'^([A-ZÇĞİÖŞÜ])\)\s*(.+)$')
FORMAT_B_ROW_RE = re.compile(
    r'^([A-ZÇĞİÖŞÜ0-9]{2,8})\s+.+?\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d.]+)%\s*$'
)
FORMAT_B_TOPLAM_RE = re.compile(r'^TOPLAM:\s*([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$')
FORMAT_B_GIRIS_RE = re.compile(
    r'KATILMA PAYI İHRA[ÇC]LARINDAN KAYNAKLANAN NAK[İI]T G[İI]R[İI][ŞS]LER[İI]\s*:\s*([\d,]+\.\d+)',
    re.IGNORECASE,
)
FORMAT_B_CIKIS_RE = re.compile(
    r'KATILMA PAYI İADELER[İI]NDEN KAYNAKLANAN NAK[İI]T [ÇC]IK[İI][ŞS]LAR[İI]\s*:\s*([\d,]+\.\d+)',
    re.IGNORECASE,
)
FORMAT_B_SECTION_MAP = {
    'HİSSE SENETLERİ': 'HISSE_SENEDI',
    'YABANCI HİSSE SENETLERİ': 'HISSE_SENEDI',
}


def _to_float_en(s):
    """Ingilizce sayi formati: 1,234,567.89 -> 1234567.89"""
    return float(s.replace(',', ''))

# Bolum basligi -> normalize edilmis kategori adi
SECTION_HEADERS = {
    'HİSSE SENETLERİ': 'HISSE_SENEDI',
    'BORÇLANMA SENETLERİ': 'BORCLANMA_SENEDI',
    'DİĞER': 'DIGER',
    'MEVDUAT': 'MEVDUAT',
    'REPO': 'REPO',
    'T.REPO': 'REPO',
    'TPP': 'TPP',
    'TÜREV': 'TUREV',  # VIOP/futures - BV Portfoy sablonunda gozlemlendi (bkz.
                        # readme_findings.md); HISSE_SENEDI'ye SIZMAMASI icin
                        # ayri bolum olarak isaretleniyor (import script'i
                        # sadece HISSE_SENEDI'yi DB'ye yaziyor).
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
    isin: str  # Format B'nin hisse senedi satirlarinda ISIN yok -> None
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
    dialect: str = 'A'  # 'A' | 'B' - hangi rapor sablonu tespit edildi
    reconciliation_metric: str = 'agirlik_pct'  # 'agirlik_pct' | 'toplam_tl' - printed_group_totals
                                                  # neyle kiyaslanmali (dialect'e gore degisir)


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
        if not m:
            # BV Portfoy gibi bazi fonlarda kod ile fon adi arasinda tire
            # YOK, sadece bosluk var: "BV1 BV PORTFÖY ... FON". Kisa (<=6
            # karakter) buyuk harf/rakam ilk token'i kod olarak kabul et.
            m = re.match(r'^([A-ZÇĞİÖŞÜ0-9]{2,6})\s+(.+)$', first_lines[0])
        if m:
            fon_kodu, fon_adi = m.group(1), m.group(2)
        else:
            fon_adi = first_lines[0]
    if len(first_lines) > 1:
        m = re.match(r'([A-Za-zçğıöşüÇĞİÖŞÜ]+)-(\d{4})', first_lines[1])
        if m:
            ay = TURKISH_MONTHS.get(_tr_lower(m.group(1)), 0)
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
    """Dispatcher: ilk satirdaki basliga gore Format A/B'yi secer (bkz. dosya
    basindaki not). Ne A ne B'ye uyarsa Format A denenir - reconciliation
    basarisiz olup GUVENLI sekilde reddedilecektir (yeni bir 3. dialect
    eklemek gerekecek anlamina gelir)."""
    first_line = next((l for l in all_text.split('\n') if l.strip()), '')
    if FORMAT_B_TITLE_RE.search(first_line):
        return _parse_pdf_text_format_b(all_text)
    return _parse_pdf_text_format_a(all_text)


def _is_data_line(line):
    """Ticker+nominal/toplam/yuzde iceren bir satir mi (ISIN bu satirda
    olmasi SART degil - bkz. _find_isin_in_window)."""
    return len(NUM_RE.findall(line)) >= 4 and DATE_RE.search(line) is not None


def _find_isin_in_window(lines, start_idx, max_lookahead=10):
    """BV Portfoy sablonunda gozlemlendi: sirket adi uzun oldugunda ISIN,
    ticker+sayisal-veri satiriyla AYNI satirda degil, adin sardigi
    satirlardan BIRINDE cikabiliyor (orn. 'ASTOR TL 15.000,00 ...' veri
    satirindan SONRA gelen 'ENERJİ TREASTR00013' satirinda). Bir sonraki
    veri satirina / bolum basligina / stop-line'a kadar ileri arar."""
    for j in range(start_idx + 1, min(len(lines), start_idx + 1 + max_lookahead)):
        nxt = lines[j]
        if not nxt:
            continue
        if nxt in SECTION_HEADERS or STOP_LINE_RE.match(nxt) or _is_data_line(nxt):
            break
        m = ISIN_RE.search(nxt)
        if m:
            return m.group(0)
    return None


def _parse_pdf_text_format_a(all_text: str) -> ParseResult:
    result = ParseResult()
    result.dialect = 'A'
    result.fon_kodu, result.fon_adi, result.donem_yil, result.donem_ay = _parse_header(all_text)
    (result.katilma_payi_giris_tl, result.katilma_payi_cikis_tl,
     result.katilma_payi_extract_method) = _extract_katilma_payi(all_text)

    current_section = 'UNKNOWN'
    lines = [l.strip() for l in all_text.split('\n')]

    for i, line in enumerate(lines):
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

        if not _is_data_line(line):
            # ISIN tasimayan/sayisal alanlari eksik satir (baslik tekrari,
            # sirket adi devam satiri, vb.) - atla.
            continue

        isin_match = ISIN_RE.search(line)
        if isin_match:
            isin = isin_match.group(0)
            prefix = line[:isin_match.start()].split()
        else:
            # ISIN bu satirda yok - komsu satirlarda ara (bkz. yukaridaki not).
            isin = _find_isin_in_window(lines, i)
            split_pos = min(m.start() for m in (NUM_RE.search(line), DATE_RE.search(line)) if m)
            prefix = line[:split_pos].split()

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


def _parse_pdf_text_format_b(all_text: str) -> ParseResult:
    """Ata Portföy'de gozlemlenen ikinci sablon - bkz. dosya basindaki not.
    Hisse senedi satirlarinda ISIN YOK (sadece BIST ticker), Ingilizce sayi
    formati, harfli bolum basliklari ("A) HİSSE SENETLERİ"), toplam satiri
    yuzde degil TL bazli ("TOPLAM: <nominal> <rayic>") - bu yuzden
    reconciliation_metric='toplam_tl' olarak isaretleniyor (Format A'nin
    yuzde bazli reconciliation'inin aksine)."""
    result = ParseResult(dialect='B', reconciliation_metric='toplam_tl')

    lines = [l.strip() for l in all_text.split('\n')]
    first_line = next((l for l in lines if l), '')
    m = FORMAT_B_TITLE_RE.search(first_line)
    if m:
        result.fon_kodu = m.group(1)
        result.donem_ay = TURKISH_MONTHS.get(_tr_lower(m.group(2)), 0)
        result.donem_yil = int(m.group(3))
    for line in lines:
        m = FORMAT_B_FON_ADI_RE.match(line)
        if m:
            result.fon_adi = m.group(1).strip()
            break

    m = FORMAT_B_GIRIS_RE.search(all_text)
    if m:
        result.katilma_payi_giris_tl = _to_float_en(m.group(1))
    m = FORMAT_B_CIKIS_RE.search(all_text)
    if m:
        result.katilma_payi_cikis_tl = _to_float_en(m.group(1))
    if result.katilma_payi_giris_tl is not None and result.katilma_payi_cikis_tl is not None:
        result.katilma_payi_extract_method = 'same-line'
    else:
        result.katilma_payi_extract_method = 'UNRESOLVED'

    current_section = 'UNKNOWN'
    for line in lines:
        if not line:
            continue

        sm = FORMAT_B_SECTION_RE.match(line)
        if sm:
            current_section = FORMAT_B_SECTION_MAP.get(sm.group(2).strip().upper(), 'DIGER')
            continue

        tm = FORMAT_B_TOPLAM_RE.match(line)
        if tm:
            if current_section not in result.printed_group_totals:
                # 2. sayi = rayic deger toplami - toplam_tutar_tl ile ayni
                # birim, dogrudan kiyaslanabilir (bkz. asagida __main__).
                result.printed_group_totals[current_section] = _to_float_en(tm.group(2))
            continue

        if current_section != 'HISSE_SENEDI':
            continue

        rm = FORMAT_B_ROW_RE.match(line)
        if not rm:
            # HISSE_SENEDI bolumunde ama satir kalibi tutmuyor - genelde
            # bir sirket adinin devam satiri (orn. "A.Ş" tek basina) -
            # sessizce atla, bu Format A'daki "ISIN yok -> atla" ile ayni
            # mantik.
            continue

        ticker, nominal_s, rayic_s, pct_s = rm.groups()
        result.lots.append(Lot(
            section=current_section,
            ticker=ticker,
            isin=None,
            nominal_deger=_to_float_en(nominal_s),
            tarih='',
            toplam_tutar_tl=_to_float_en(rayic_s),
            agirlik_grup_pct=float(pct_s),
            agirlik_fpd_pct=float(pct_s),
            agirlik_ftd_pct=float(pct_s),
            raw_line=line,
        ))

    return result


def aggregate_by_isin(result: ParseResult, section='HISSE_SENEDI'):
    """Isim aksine ragmen ISIN'i olmayan (Format B) satirlar icin ticker'a
    gore de aggregate edebilir - anahtar ISIN varsa ISIN, yoksa ticker'dir."""
    agg = {}
    for lot in result.lots:
        if lot.section != section:
            continue
        key = lot.isin or lot.ticker
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


def check_reconciliation(result: ParseResult, holdings: list):
    """result.reconciliation_metric'e gore (dialect'e bagli) dogru olcuyu
    secip PDF'in kendi yazdigi toplamla kiyaslar. Donus:
    (hesaplanan, yazili_toplam, ok, olcu_etiketi)."""
    printed_total = result.printed_group_totals.get('HISSE_SENEDI')
    if result.reconciliation_metric == 'toplam_tl':
        calculated = sum(h['toplam_tutar_tl'] for h in holdings)
        tol = max(1.0, abs(printed_total or 0) * 0.001)
        label = 'TL'
    else:
        calculated = sum(h['agirlik_ftd_pct'] for h in holdings)
        tol = 0.05
        label = '%'
    ok = printed_total is not None and abs(printed_total - calculated) < tol
    return calculated, printed_total, ok, label


if __name__ == '__main__':
    import pdfplumber

    for path in sys.argv[1:]:
        with pdfplumber.open(path) as pdf:
            text = '\n'.join((p.extract_text() or '') for p in pdf.pages)
        result = parse_pdf_text(text)
        holdings = aggregate_by_isin(result, 'HISSE_SENEDI')
        calculated, printed_total, ok, unit = check_reconciliation(result, holdings)

        print(f"\n=== {path} ===")
        print(f"Fon: {result.fon_kodu} - {result.fon_adi} | Donem: {result.donem_ay}/{result.donem_yil} "
              f"| Dialect: {result.dialect}")
        print(f"Hisse senedi kalemi (aggregate sonrasi): {len(holdings)}")
        print(f"Hesaplanan toplam ({unit}): {calculated:,.2f}")
        print(f"PDF'de yazan toplam ({unit}): {printed_total}")
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
