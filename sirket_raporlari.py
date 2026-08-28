"""
Şirket yatırımcı raporu analiz modülü.

Kullanıcı bir PDF linki (KAP bildirimi VEYA şirketin kendi IR sitesindeki
doğrudan PDF linki - ikisi de aynı boru hattından geçer) + hisse kodu +
dönem (yıl/çeyrek) girer. PDF indirilir, metni çıkarılır, Google Gemini API
(ücretsiz katman) ile Türkçe özetlenir VE yıl sonu satış/FAVÖK/net kâr
hedefleri yapısal olarak çıkarılır. Bir önceki çeyreğin hedefleriyle
karşılaştırılıp YUKARI/AŞAĞI/AYNI yönü belirlenir - bu sayede zaman içinde
hedeflerin nasıl revize edildiği izlenebilir.

Her şey "bist.company_report_summaries" tablosunda KALICI olarak saklanır -
aynı link tekrar analiz edilirse Gemini'ye tekrar sorulmadan cache'den
döner; aynı (ticker, yıl, dönem) tekrar girilirse üzerine yazılır (yeni bir
düzeltilmiş link gelmiş olabilir).

Not: KAP bildirim/rapor sunumlarının hepsi KAP'a PDF olarak eklenmiyor -
bazı şirketler sadece "kendi web sitemize yükledik" diyor. Bu durumda
kullanıcı doğrudan şirketin IR sayfasındaki PDF linkini yapıştırabilir -
indirme/özetleme mantığı kaynaktan bağımsızdır.
"""
import json
import os
import re
import time

import pandas as pd
import requests
import streamlit as st

try:
    import psycopg2
except ImportError:
    psycopg2 = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

MAX_SUMMARY_INPUT_CHARS = 100_000  # Gemini'ye gonderilecek ham metnin ust siniri (token/kota kontrolu)
GEMINI_MODEL = "gemini-3.6-flash"  # ucretsiz katmanda mevcut (2.5-flash yeni kullanicilara kapatildi)

DONEM_OPTIONS = ["Q1", "Q2", "Q3", "Q4", "FY"]
DONEM_LABELS = {"Q1": "1. Çeyrek", "Q2": "2. Çeyrek", "Q3": "3. Çeyrek", "Q4": "4. Çeyrek", "FY": "Yıl Sonu"}
DONEM_SIRA = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}

YON_BADGE = {
    "YUKARI": "🟢 ⬆️ Yukarı Revize",
    "ASAGI": "🔴 ⬇️ Aşağı Revize",
    "AYNI": "⚪ ➡️ Değişmedi",
    "ILK_KEZ": "🆕 İlk Kayıt",
    "BELIRSIZ": "❓ Belirsiz",
}

# Sektor kumelemesinin tutarli olmasi icin Gemini'ye SABIT bir listeden secim
# yaptiriyoruz - serbest metin birakirsak "Enerji" / "Enerji Sektoru" gibi
# varyasyonlar kumelemeyi bozar.
SEKTOR_LISTESI = [
    "Bankacılık", "Sigorta ve Emeklilik", "Holding", "Enerji", "Perakende",
    "Gıda ve İçecek", "Otomotiv", "Sanayi ve Üretim", "İnşaat ve GYO",
    "Teknoloji", "Telekomünikasyon", "Turizm", "Sağlık",
    "Kimya ve Petrokimya", "Madencilik", "Tekstil", "Ulaştırma ve Lojistik",
    "Finans (Banka Dışı)", "Diğer",
]

SUMMARY_PROMPT_TEMPLATE = """Sen kıdemli bir yatırım fonu analistisin. Aşağıda bir şirketin PDF'ten
çıkarılmış yatırımcı sunumu/faaliyet raporu metni var. Bu metin PDF'ten otomatik çıkarıldığı
için grafik/infografik etiketleri, sayılar ve başlıklar karışık sırada gelmiş olabilir -
anlamı çıkarmaya çalış, birebir sıralı okuma bekleme.

Şirket: {ticker}
Rapor dönemi: {donem_label} {yil}

{prior_context}

GÖREV: Aşağıdaki alanları SADECE geçerli JSON olarak döndür. Başka hiçbir metin, açıklama
veya kod bloğu işareti (```) ekleme - yanıtın ilk karakteri {{ olmalı.

{{
  "sektor": "<şirketin ait olduğu sektör - AŞAĞIDAKİ LİSTEDEN TAM OLARAK BİRİNİ seç, başka bir
kelime kullanma: {sektor_listesi}>",
  "marj_puani": <1-5 arası TAM SAYI - kârlılık marjlarının (brüt/FAVÖK/net) hem GÜCÜNÜ hem
YÖNÜNÜ (iyileşiyor mu kötüleşiyor mu) yansıtan tek bir skor. 1=çok zayıf/hızla kötüleşen
marjlar, 3=vasat/durağan, 5=güçlü ve iyileşen marjlar>,
  "marj_yorumu": "<marj skorunu gerekçelendiren 1-2 cümle, somut rakamlarla>",
  "gorunum_puani": <1-5 arası TAM SAYI - raporda şirketin kendi ifade ettiği (veya senin
rakamlardan çıkardığın) gelecek beklentilerinin genel tonu. 1=çok negatif/karamsar,
3=nötr/karışık, 5=çok pozitif/iyimser>,
  "gorunum_yorumu": "<görünüm skorunu gerekçelendiren 1-2 cümle>",
  "satis_hedefi": "<yıl sonu satış/ciro hedefi varsa kısa metin (örn. '18-19 Mr TL'), yoksa null>",
  "satis_yonu": "<önceki döneme göre: YUKARI | ASAGI | AYNI | ILK_KEZ | BELIRSIZ>",
  "favok_hedefi": "<yıl sonu FAVÖK hedefi varsa kısa metin, yoksa null>",
  "favok_yonu": "<YUKARI | ASAGI | AYNI | ILK_KEZ | BELIRSIZ>",
  "net_kar_hedefi": "<yıl sonu net kâr hedefi varsa kısa metin, yoksa null>",
  "net_kar_yonu": "<YUKARI | ASAGI | AYNI | ILK_KEZ | BELIRSIZ>",
  "metin_ozeti": "<UZUN, DETAYLI, profesyonel bir yatırım fonu analist raporu - yaklaşık 1 A4
sayfası uzunluğunda (600-900 kelime). Yüzeysel maddeler değil, akıcı analiz paragrafları yaz.
TAM OLARAK şu başlıklarla:
## 📊 Finansal Performans
(Gelir, kâr, FAVÖK, marjlar - önceki dönem/yıl karşılaştırmalı, rakamları yorumla: büyüme
kaliteli mi, marj daralması/genişlemesi neden kaynaklanıyor, birkaç paragraf)
## 🎯 Operasyonel ve Stratejik Gelişmeler
(Kapasite, yeni yatırımlar, pazar payı, yönetim açıklamaları - bunların gelecekteki
finansallara olası etkisini yorumla)
## 🏭 Sektörel Konum ve Rekabet
(Metinde sektöre/rakiplere dair bilgi varsa değerlendir; yoksa bu başlığı kısa geç)
## ⚠️ Risk ve Dikkat Noktaları
(Raporda geçen riskler + rakamlardan senin çıkardığın örtük riskler - örn. marj baskısı,
borçluluk, kur riski, tek müşteri/sektör bağımlılığı)
## 📌 Değerlendirme ve Görünüm
(SON PARAGRAF - en az 4-5 cümle: genel tabloyu özetle ve hangi yöne işaret ettiğini net
söyle - örn. 'sonuçlar olumlu/karışık/zayıf, X ve Y nedeniyle temkinli/iyimser bir görünüm
öne çıkıyor, izlenmesi gereken en kritik nokta Z'. Somut ve net ol, muğlak ifadelerden kaçın.
Bu paragrafın sonuna şunu ekle: '*Not: Bu bir yatırım tavsiyesi değildir, raporun analistçe
yorumlanmış bir değerlendirmesidir.*')>"
}}

Kurallar:
- Önceki dönem hedefi verilmişse (yukarıda) ve bu raporda hedef değişmemişse "AYNI" yaz.
- Önceki dönem hedefi verilmemişse (ilk kayıt) yön alanlarına "ILK_KEZ" yaz.
- Bu raporda o hedefe dair net bir rakam/aralık yoksa hedef alanını null, yönü "BELIRSIZ" yap.
- Emin olmadığın rakamları uydurma - ama verilen rakamlar üzerinden yorum/analiz yapmaktan
  çekinme, senden istenen tam da bu.
- Yüzeysel/jenerik ifadelerden kaçın ("şirket iyi performans gösterdi" gibi) - somut rakam ve
  nedensellik ver ("FAVÖK marjı %38,8 artışla X'e yükseldi, bunun nedeni Y" gibi).

--- RAPOR METNİ ---
{report_text}
"""


def _get_database_url():
    try:
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    return os.getenv("DATABASE_URL")


def _get_gemini_api_key():
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY")


def _make_connection():
    if psycopg2 is None:
        return None
    dsn = _get_database_url()
    if not dsn:
        return None
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET search_path TO bist, public;")
        # Bu modul kendi tablosunu kendi olusturur/gunceller - db/schema.sql'i
        # yeniden calistirmaya gerek kalmadan mevcut kurulumlara eklenir.
        # ALTER ... ADD COLUMN IF NOT EXISTS: tablo daha onceki (KPI'siz)
        # versiyondan zaten varsa veri kaybetmeden yeni kolonlari ekler.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS company_report_summaries (
                id                  BIGSERIAL PRIMARY KEY,
                ticker              VARCHAR(24),
                sirket_adi          TEXT,
                kaynak_url          TEXT NOT NULL UNIQUE,
                rapor_basligi       TEXT,
                ozet                TEXT NOT NULL,
                ham_metin_uzunluk   INTEGER,
                olusturma_zamani    TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS yil SMALLINT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS donem VARCHAR(4);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS satis_hedefi TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS satis_yonu VARCHAR(12);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_hedefi TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_yonu VARCHAR(12);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_hedefi TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_yonu VARCHAR(12);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS sektor VARCHAR(50);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS gorunum_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS gorunum_yorumu TEXT;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_company_report_period
                ON company_report_summaries(ticker, yil, donem)
                WHERE ticker IS NOT NULL AND yil IS NOT NULL AND donem IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_company_report_ticker
                ON company_report_summaries(ticker, olusturma_zamani DESC);

            -- Sektor bazinda derlenmis makro analiz (compute_sector_rollup() ile
            -- tek bir Gemini cagrisinda TUM sektorler birlikte, birbirine
            -- kiyaslanarak uretilir - ayri ayri cagirsaydik "kiyaslama" anlamsiz
            -- olurdu, model diger sektorleri gormeden skor veremezdi).
            CREATE TABLE IF NOT EXISTS sector_rollup_analysis (
                id               BIGSERIAL PRIMARY KEY,
                sektor           VARCHAR(50) NOT NULL,
                makro_analiz     TEXT,
                sektor_skoru     NUMERIC(3,1),
                sirket_sayisi    INTEGER,
                olusturma_zamani TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            -- Sektor tablosu artik yil/donem bazinda tutuluyor (once tek
            -- sektor basina tek satirdi - eski kurulumlar icin ekleniyor).
            ALTER TABLE sector_rollup_analysis ADD COLUMN IF NOT EXISTS yil SMALLINT;
            ALTER TABLE sector_rollup_analysis ADD COLUMN IF NOT EXISTS donem VARCHAR(4);

            -- Eski tekil UNIQUE(sektor) kisitini kaldirip yerine
            -- (yil, donem, sektor) kisitini koy (isim bilinmeyebilir,
            -- bu yuzden information_schema uzerinden bulup dusuruyoruz).
            DO $$
            DECLARE
                _con_name TEXT;
            BEGIN
                SELECT tc.constraint_name INTO _con_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'bist'
                  AND tc.table_name = 'sector_rollup_analysis'
                  AND tc.constraint_type = 'UNIQUE'
                GROUP BY tc.constraint_name
                HAVING COUNT(*) = 1 AND bool_and(kcu.column_name = 'sektor');

                IF _con_name IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE sector_rollup_analysis DROP CONSTRAINT %I', _con_name);
                END IF;
            END $$;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_sector_rollup_period
                ON sector_rollup_analysis(yil, donem, sektor);
        """)
    return conn


@st.cache_resource(show_spinner=False)
def _get_connection():
    return _make_connection()


def _get_live_connection():
    """Neon serverless bosta kalinca baglantiyi kapatabiliyor (bkz. fon_analiz.py
    - ayni sorun burada da gecerli). Kullanmadan once canliligini kontrol edip
    gerekirse yeniden baglaniyoruz."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        if conn.closed:
            raise psycopg2.OperationalError("connection closed")
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        _get_connection.clear()
        conn = _get_connection()
    return conn


def _download_pdf_bytes(url):
    """PDF'i indirir. KAP'ın bazi endpoint'leri (api/file/download/...) PDF'i
    bir Java serialization zarfina sarip gonderiyor (pilotta kesfedildi -
    bkz. db/migrate_excel_to_postgres.py'daki ayni sorun); bu durumda ilk
    '%PDF' imzasina kadar olan onsozu atiyoruz. Sirket kendi sitesinden
    gelen duz PDF'lerde bu sarmalayici yok, dokunmadan geciyoruz."""
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    data = resp.content
    if data[:4] == b'%PDF':
        return data
    idx = data.find(b'%PDF')
    if idx == -1:
        raise ValueError("İndirilen dosya bir PDF gibi görünmüyor (imza bulunamadı).")
    return data[idx:]


def _extract_pdf_text(pdf_bytes):
    if pdfplumber is None:
        raise RuntimeError("pdfplumber kurulu değil.")
    import io
    texts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n_pages = len(pdf.pages)
        for p in pdf.pages:
            texts.append(p.extract_text() or "")
    full_text = "\n".join(texts)
    return full_text, n_pages


def _parse_llm_json(raw_text):
    """Gemini response_mime_type='application/json' ile genelde duz JSON
    donuyor, ama bazen yine de ```json ... ``` bloguna sarabiliyor - once
    duz parse dener, olmazsa kod bloklarini temizleyip tekrar dener."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw_text.strip())
        return json.loads(cleaned)


def _call_gemini_with_retry(client, prompt, max_attempts=3, max_output_tokens=8000):
    """Gemini API bazen gecici olarak asiri yuklu oluyor (503 UNAVAILABLE,
    canli hatada gozlemlendi) veya rate-limit'e takiliyor (429). Ikisi de
    gecici - kisa bir bekleme ile tekrar denemek genelde yeterli. Diger
    hatalar (400 gecersiz istek, 404 model bulunamadi vb.) tekrar denemeden
    direkt yukari firlatilir - onlar tekrar denense de duzelmez."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            return client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=max_output_tokens,
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
        except genai.errors.APIError as e:
            last_error = e
            if e.code in (503, 429) and attempt < max_attempts - 1:
                time.sleep(3 * (attempt + 1))  # 3s, 6s
                continue
            raise
    raise last_error


def _summarize_with_gemini(report_text, ticker, donem_label, yil, prior_kpis):
    if genai is None:
        raise RuntimeError("google-genai paketi kurulu değil (requirements.txt'e eklenmeli).")
    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY secrets/environment değişkeni eksik.")

    truncated = report_text[:MAX_SUMMARY_INPUT_CHARS]
    was_truncated = len(report_text) > MAX_SUMMARY_INPUT_CHARS

    if prior_kpis:
        prior_context = (
            f"Bir önceki dönemde ({prior_kpis.get('donem')} {prior_kpis.get('yil')}) açıklanan hedefler:\n"
            f"- Satış hedefi: {prior_kpis.get('satis_hedefi') or 'belirtilmemiş'}\n"
            f"- FAVÖK hedefi: {prior_kpis.get('favok_hedefi') or 'belirtilmemiş'}\n"
            f"- Net kâr hedefi: {prior_kpis.get('net_kar_hedefi') or 'belirtilmemiş'}\n"
            "Bu bilgiyi kullanarak yeni raporda hedeflerin YUKARI mı revize edildiğini, "
            "AŞAĞI mı çekildiğini, yoksa AYNI mı kaldığını belirle."
        )
    else:
        prior_context = "Bu ticker için kayıtlı önceki dönem hedefi yok - bu ilk kayıt olacak."

    client = genai.Client(api_key=api_key)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        ticker=ticker or "(belirtilmedi)",
        donem_label=donem_label or "",
        yil=yil or "",
        prior_context=prior_context,
        sektor_listesi=", ".join(SEKTOR_LISTESI),
        report_text=truncated,
    )
    response = _call_gemini_with_retry(client, prompt)
    raw = response.text

    try:
        parsed = _parse_llm_json(raw)
    except json.JSONDecodeError:
        # Yapisal cikarma basarisiz oldu - en azindan ham yaniti metin ozeti
        # olarak goster, KPI alanlarini bos birak. Sessizce veri uydurmaktan
        # iyidir.
        parsed = {
            "sektor": None, "marj_puani": None, "marj_yorumu": None,
            "gorunum_puani": None, "gorunum_yorumu": None,
            "satis_hedefi": None, "satis_yonu": "BELIRSIZ",
            "favok_hedefi": None, "favok_yonu": "BELIRSIZ",
            "net_kar_hedefi": None, "net_kar_yonu": "BELIRSIZ",
            "metin_ozeti": "⚠️ *Yapısal KPI çıkarımı başarısız oldu, ham yanıt gösteriliyor:*\n\n" + (raw or ""),
            "_parse_failed": True,  # caller bunu goruyorsa DB'ye KAYDETMEMELI (bozuk veri kalici olmasin)
        }

    if was_truncated:
        parsed["metin_ozeti"] = parsed.get("metin_ozeti", "") + (
            f"\n\n---\n*Not: Rapor metni çok uzun olduğu için ilk "
            f"{MAX_SUMMARY_INPUT_CHARS:,} karakteri analiz edildi.*"
        )
    return parsed


def get_previous_period_kpis(ticker, yil, donem):
    """Verilen (yil, donem)'den kronolojik olarak hemen ONCEKI kayitli
    donemin KPI'larini getirir - Gemini'ye "onceki hedef neydi" baglamini
    vermek icin. Kayit yoksa None doner (ilk kayit demektir)."""
    conn = _get_live_connection()
    if conn is None or not (ticker and yil and donem):
        return None
    sira = DONEM_SIRA.get(donem, 99)
    df = pd.read_sql("""
        SELECT yil, donem, satis_hedefi, favok_hedefi, net_kar_hedefi
        FROM company_report_summaries
        WHERE ticker = %(ticker)s AND yil IS NOT NULL AND donem IS NOT NULL
          AND (yil < %(yil)s OR (yil = %(yil)s AND donem != %(donem)s))
        ORDER BY yil DESC
        LIMIT 20
    """, conn, params={"ticker": ticker, "yil": yil, "donem": donem})
    if df.empty:
        return None
    # Donem sirasina gore en yakin onceki kaydi python tarafinda bul
    # (CASE WHEN ile SQL'de siralamak yerine - kucuk veri seti, basit tutuluyor)
    df['_sira'] = df['donem'].map(DONEM_SIRA).fillna(99)
    df['_key'] = df['yil'] * 10 + df['_sira']
    target_key = yil * 10 + sira
    candidates = df[df['_key'] < target_key].sort_values('_key', ascending=False)
    if candidates.empty:
        return None
    row = candidates.iloc[0]
    return {
        'yil': int(row['yil']), 'donem': row['donem'],
        'satis_hedefi': row['satis_hedefi'], 'favok_hedefi': row['favok_hedefi'],
        'net_kar_hedefi': row['net_kar_hedefi'],
    }


def save_report_summary(url, ticker, yil, donem, kpis, ham_metin_uzunluk):
    conn = _get_live_connection()
    if conn is None:
        return False
    ozet = kpis.get('metin_ozeti', '')
    sektor = kpis.get('sektor') if kpis.get('sektor') in SEKTOR_LISTESI else None
    vals = (
        ticker, url, yil, donem,
        sektor, kpis.get('marj_puani'), kpis.get('marj_yorumu'),
        kpis.get('gorunum_puani'), kpis.get('gorunum_yorumu'),
        kpis.get('satis_hedefi'), kpis.get('satis_yonu'),
        kpis.get('favok_hedefi'), kpis.get('favok_yonu'),
        kpis.get('net_kar_hedefi'), kpis.get('net_kar_yonu'),
        ozet, ham_metin_uzunluk,
    )
    with conn.cursor() as cur:
        if ticker and yil and donem:
            cur.execute("""
                INSERT INTO company_report_summaries
                    (ticker, kaynak_url, yil, donem, sektor, marj_puani, marj_yorumu,
                     gorunum_puani, gorunum_yorumu, satis_hedefi, satis_yonu,
                     favok_hedefi, favok_yonu, net_kar_hedefi, net_kar_yonu,
                     ozet, ham_metin_uzunluk)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (ticker, yil, donem) WHERE ticker IS NOT NULL
                    AND yil IS NOT NULL AND donem IS NOT NULL
                DO UPDATE SET
                    kaynak_url = EXCLUDED.kaynak_url,
                    sektor = EXCLUDED.sektor,
                    marj_puani = EXCLUDED.marj_puani,
                    marj_yorumu = EXCLUDED.marj_yorumu,
                    gorunum_puani = EXCLUDED.gorunum_puani,
                    gorunum_yorumu = EXCLUDED.gorunum_yorumu,
                    satis_hedefi = EXCLUDED.satis_hedefi,
                    satis_yonu = EXCLUDED.satis_yonu,
                    favok_hedefi = EXCLUDED.favok_hedefi,
                    favok_yonu = EXCLUDED.favok_yonu,
                    net_kar_hedefi = EXCLUDED.net_kar_hedefi,
                    net_kar_yonu = EXCLUDED.net_kar_yonu,
                    ozet = EXCLUDED.ozet,
                    ham_metin_uzunluk = EXCLUDED.ham_metin_uzunluk,
                    olusturma_zamani = now()
            """, vals)
        else:
            cur.execute("""
                INSERT INTO company_report_summaries
                    (ticker, kaynak_url, yil, donem, sektor, marj_puani, marj_yorumu,
                     gorunum_puani, gorunum_yorumu, satis_hedefi, satis_yonu,
                     favok_hedefi, favok_yonu, net_kar_hedefi, net_kar_yonu,
                     ozet, ham_metin_uzunluk)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (kaynak_url) DO UPDATE SET
                    ozet = EXCLUDED.ozet, ham_metin_uzunluk = EXCLUDED.ham_metin_uzunluk,
                    sektor = EXCLUDED.sektor, marj_puani = EXCLUDED.marj_puani,
                    marj_yorumu = EXCLUDED.marj_yorumu, gorunum_puani = EXCLUDED.gorunum_puani,
                    gorunum_yorumu = EXCLUDED.gorunum_yorumu
            """, vals)
    return True


@st.cache_data(ttl=60, show_spinner=False)
def get_existing_summary(url):
    conn = _get_live_connection()
    if conn is None:
        return None
    df = pd.read_sql("""
        SELECT ticker, yil, donem, sektor, marj_puani, marj_yorumu, gorunum_puani, gorunum_yorumu,
               satis_hedefi, satis_yonu, favok_hedefi, favok_yonu,
               net_kar_hedefi, net_kar_yonu, ozet, ham_metin_uzunluk, olusturma_zamani
        FROM company_report_summaries WHERE kaynak_url = %(url)s
    """, conn, params={"url": url})
    if df.empty:
        return None
    return df.iloc[0].to_dict()


@st.cache_data(ttl=60, show_spinner=False)
def get_all_summaries():
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql("""
        SELECT id, ticker, yil, donem, kaynak_url, sektor,
               marj_puani, marj_yorumu, gorunum_puani, gorunum_yorumu,
               satis_yonu, favok_yonu, net_kar_yonu, ozet, olusturma_zamani
        FROM company_report_summaries
        ORDER BY yil DESC NULLS LAST,
                 CASE donem WHEN 'FY' THEN 5 WHEN 'Q4' THEN 4 WHEN 'Q3' THEN 3
                            WHEN 'Q2' THEN 2 WHEN 'Q1' THEN 1 ELSE 0 END DESC,
                 olusturma_zamani DESC
    """, conn)


@st.cache_data(ttl=60, show_spinner=False)
def get_ticker_history(ticker):
    conn = _get_live_connection()
    if conn is None or not ticker:
        return pd.DataFrame()
    df = pd.read_sql("""
        SELECT yil, donem, satis_hedefi, satis_yonu, favok_hedefi, favok_yonu,
               net_kar_hedefi, net_kar_yonu, olusturma_zamani
        FROM company_report_summaries
        WHERE ticker = %(ticker)s AND yil IS NOT NULL AND donem IS NOT NULL
    """, conn, params={"ticker": ticker})
    if df.empty:
        return df
    df['_sira'] = df['donem'].map(DONEM_SIRA).fillna(99)
    return df.sort_values(['yil', '_sira']).drop(columns=['_sira'])


@st.cache_data(ttl=60, show_spinner=False)
def get_available_periods_for_rollup():
    """Ticker+yil+donem bilgisiyle kayitli TUM raporlarin bulundugu (yil, donem)
    kombinasyonlarini en yeniden en eskiye siralar - donem secici bunu kullanir.
    Sektor atanmis olmasi sart degil: sektor kumeleme adiminin kendisi bu
    atamayi yapacak (bkz. compute_sector_rollup)."""
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    df = pd.read_sql("""
        SELECT DISTINCT yil, donem
        FROM company_report_summaries
        WHERE yil IS NOT NULL AND donem IS NOT NULL AND ticker IS NOT NULL
    """, conn)
    if df.empty:
        return df
    df['_sira'] = df['donem'].map(DONEM_SIRA).fillna(0)
    return df.sort_values(['yil', '_sira'], ascending=[False, False]).drop(columns=['_sira'])


@st.cache_data(ttl=60, show_spinner=False)
def get_reports_for_period(yil, donem):
    """Belirtilen (yil, donem) icin kayitli TUM raporlari getirir - sektoru
    henuz atanmamis olanlar dahil ('en guncel rapor' degil, o donem icin
    gercekten girilmis raporlar; yeni eklenen raporlar da bir sonraki
    hesaplamada otomatik dahil olsun diye)."""
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql("""
        SELECT ticker, yil, donem, sektor, marj_puani, marj_yorumu,
               gorunum_puani, gorunum_yorumu, ozet
        FROM company_report_summaries
        WHERE yil = %(yil)s AND donem = %(donem)s
          AND ticker IS NOT NULL
        ORDER BY ticker
    """, conn, params={"yil": int(yil), "donem": donem})


@st.cache_data(ttl=300, show_spinner=False)
def get_sector_rollup(yil, donem):
    conn = _get_live_connection()
    if conn is None:
        return pd.DataFrame()
    return pd.read_sql("""
        SELECT sektor, makro_analiz, sektor_skoru, sirket_sayisi, olusturma_zamani
        FROM sector_rollup_analysis
        WHERE yil = %(yil)s AND donem = %(donem)s
        ORDER BY sektor_skoru DESC NULLS LAST
    """, conn, params={"yil": int(yil), "donem": donem})


SECTOR_ROLLUP_PROMPT_TEMPLATE = """Sen kıdemli bir portföy stratejistisin. Aşağıda BIST
şirketlerinin {donem_label} {yil} dönemine ait faaliyet raporu/yatırımcı sunumu özetleri var.
Şirketler henüz sektörlere ayrılmamış olabilir - bu senin görevinin bir parçası.

Görevlerin:
1) HER şirketi, SADECE aşağıdaki listeden TEK bir sektöre ata (listedeki isimleri birebir kullan):
   {sektor_listesi}
2) HER şirket için, özetindeki bilgilere dayanarak 1-5 arası (yarım puan olabilir, örn 3.5) İKİ
   PUAN ver ve her biri için 1 kısa cümlelik gerekçe yaz:
   - marj_puani: Marjlar (brüt/net/FAVÖK) ne kadar güçlü ve iyiye mi kötüye mi gidiyor?
     (5=çok güçlü ve iyileşiyor, 1=çok zayıf ve kötüleşiyor)
   - gorunum_puani: Raporda yer alan pozitif/negatif beklentilerin genel değerlemesi
     (5=çok olumlu görünüm, 1=çok olumsuz görünüm)
3) HER sektör için, o sektördeki şirketlerin verilerine dayanarak bir MAKRO SEKTÖR ANALİZİ yaz ve
   sektörleri BİRBİRİYLE KIYASLAYARAK 1-5 arası bir sektör skoru ver (5=en güçlü/olumlu
   görünümlü sektör, 1=en zayıf/olumsuz). Skorlar mutlaka birbirinden farklılaşsın - bütün
   sektörlere aynı skoru verme, gerçek bir sıralama/kıyaslama yap.

--- ŞİRKET ÖZETLERİ ---
{sirket_verileri}

GÖREV: SADECE geçerli JSON döndür, başka hiçbir metin ekleme. Format:

{{
  "sektorler": [
    {{
      "sektor": "<sektör adı, yukarıdaki listeden birebir>",
      "makro_analiz": "<3-5 cümlelik, o sektördeki şirketlerin ortak eğilimlerini özetleyen
analiz - marjlar genel olarak iyiye mi kötüye mi gidiyor, hangi ortak temalar/riskler öne
çıkıyor>",
      "sektor_skoru": <1-5 arası, diğer sektörlerle kıyaslanmış tam sayı veya yarım puan (örn 3.5)>,
      "sirketler": [
        {{"ticker": "<TICKER>", "marj_puani": <1-5>, "marj_yorumu": "<kısa gerekçe>",
          "gorunum_puani": <1-5>, "gorunum_yorumu": "<kısa gerekçe>"}}
      ]
    }}
  ]
}}
"""


def compute_sector_rollup(yil, donem):
    """Secilen (yil, donem) icin kayitli TUM rapor ozetlerini TEK bir Gemini
    cagrisinda hem sektorlere siniflandirir hem de sirket/sektor bazinda
    puanlar (ayri ayri cagirsaydik model diger sektorleri/sirketleri gormeden
    "kiyaslamali" skor veremezdi). Sektor atamasi onceden yapilmis olmasi
    sart degil - bu fonksiyon o donemdeki TUM raporlari (sektoru bos olanlar
    dahil) tarar ve siniflandirir.
    Sonuclari sector_rollup_analysis tablosuna (yil, donem, sektor) anahtariyla
    kaydeder (upsert); ayrica company_report_summaries uzerindeki sektor/marj/
    gorunum alanlarini da bu siniflandirmayla gunceller."""
    if genai is None:
        raise RuntimeError("google-genai paketi kurulu değil.")
    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY secrets/environment değişkeni eksik.")

    reports = get_reports_for_period(yil, donem)
    if reports.empty:
        raise RuntimeError(f"{DONEM_LABELS.get(donem, donem)} {yil} için hiç kayıtlı rapor yok.")

    valid_tickers = set(reports['ticker'])
    lines = []
    for _, r in reports.iterrows():
        ozet_kisa = (r['ozet'] or '')[:600]
        lines.append(f"\n## {r['ticker']}\nÖzet: {ozet_kisa}...")
    sirket_verileri = "\n".join(lines)

    client = genai.Client(api_key=api_key)
    prompt = SECTOR_ROLLUP_PROMPT_TEMPLATE.format(
        donem_label=DONEM_LABELS.get(donem, donem), yil=yil,
        sektor_listesi=", ".join(SEKTOR_LISTESI), sirket_verileri=sirket_verileri,
    )
    response = _call_gemini_with_retry(client, prompt, max_output_tokens=12000)
    parsed = _parse_llm_json(response.text)

    conn = _get_live_connection()
    if conn is None:
        raise RuntimeError("Veritabanı bağlantısı yok - sonuçlar kaydedilemedi.")
    sirket_toplam = 0
    with conn.cursor() as cur:
        for s in parsed.get('sektorler', []):
            sektor = s.get('sektor')
            if sektor not in SEKTOR_LISTESI:
                continue  # model listeden sapmis olabilir - guvenlik icin atla
            sirketler = [c for c in s.get('sirketler', []) if c.get('ticker') in valid_tickers]
            cur.execute("""
                INSERT INTO sector_rollup_analysis (yil, donem, sektor, makro_analiz, sektor_skoru, sirket_sayisi)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (yil, donem, sektor) DO UPDATE SET
                    makro_analiz = EXCLUDED.makro_analiz,
                    sektor_skoru = EXCLUDED.sektor_skoru,
                    sirket_sayisi = EXCLUDED.sirket_sayisi,
                    olusturma_zamani = now()
            """, (int(yil), donem, sektor, s.get('makro_analiz'), s.get('sektor_skoru'),
                  len(sirketler)))
            for c in sirketler:
                cur.execute("""
                    UPDATE company_report_summaries
                    SET sektor = %s, marj_puani = %s, marj_yorumu = %s,
                        gorunum_puani = %s, gorunum_yorumu = %s
                    WHERE ticker = %s AND yil = %s AND donem = %s
                """, (sektor, c.get('marj_puani'), c.get('marj_yorumu'),
                      c.get('gorunum_puani'), c.get('gorunum_yorumu'),
                      c['ticker'], int(yil), donem))
                sirket_toplam += 1
    conn.commit()
    get_sector_rollup.clear()
    get_reports_for_period.clear()
    get_available_periods_for_rollup.clear()
    return len(parsed.get('sektorler', [])), sirket_toplam


def _kpi_card(label, value, yon):
    st.markdown(f"**{label}**")
    st.markdown(value or "—")
    st.caption(YON_BADGE.get(yon, "❓ Belirsiz"))


def display_company_reports():
    st.markdown("### 📄 Şirket Yatırımcı Raporu Analizi")
    st.caption("Bir KAP bildirim linki veya şirketin kendi yatırımcı ilişkileri "
               "sayfasındaki doğrudan PDF linkini yapıştırın — AI ile özetlenir ve "
               "yıl sonu hedefleri (satış/FAVÖK/net kâr) çeyrek çeyrek izlenir. "
               "Yatırım tavsiyesi değildir.")

    conn = _get_live_connection()
    if conn is None:
        st.error("Veritabanı bağlantısı kurulamadı — DATABASE_URL secrets/environment "
                  "değişkeni eksik olabilir.")
        return
    if genai is None or not _get_gemini_api_key():
        st.warning("⚠️ GEMINI_API_KEY secrets/environment değişkeni eksik — "
                   "yeni özet çıkarma çalışmaz, ama daha önce kaydedilmiş özetler "
                   "aşağıda görüntülenebilir. (Ücretsiz key: aistudio.google.com)")

    with st.form("report_url_form"):
        url = st.text_input("Rapor PDF linki (KAP veya şirket sitesi)",
                            placeholder="https://kap.org.tr/tr/api/file/download/... "
                                        "veya https://sirket.com/.../sunum.pdf")
        c1, c2, c3 = st.columns(3)
        with c1:
            ticker = st.text_input("Hisse kodu", placeholder="THYAO")
        with c2:
            yil = st.number_input("Yıl", min_value=2015, max_value=2035, value=2025, step=1)
        with c3:
            donem = st.selectbox("Dönem", DONEM_OPTIONS, format_func=lambda d: DONEM_LABELS[d])
        st.caption("Hisse kodu + yıl + dönem, hedef takibi (KPI karşılaştırması) için gerekli. "
                   "Boş bırakılırsa sadece metin özeti kaydedilir, dönem takibi yapılamaz.")
        submitted = st.form_submit_button("🔍 Analiz Et", use_container_width=True, type="primary")

    if submitted and url:
        ticker = (ticker or "").strip().upper() or None
        existing = get_existing_summary(url)
        # sektor/marj_puani ozelligi eklenmeden ONCE kaydedilmis raporlarda bu
        # alanlar bos - byle bir kayitla karsilasirsak "zaten analiz edildi"
        # deyip sonsuza kadar eksik birakmak yerine otomatik yeniden analiz
        # ediyoruz (tek seferlik, sessiz bir "backfill").
        if existing is not None and existing.get('sektor') is not None:
            st.info("✅ Bu link daha önce analiz edilmiş — kayıtlı özet gösteriliyor "
                    "(Gemini'ye tekrar sorulmadı).")
            st.session_state['_last_report'] = existing
        else:
            if existing is not None:
                st.caption("ℹ️ Bu link daha önce analiz edilmiş ama sektör/skor bilgisi "
                           "eksik (eski bir kayıt) — otomatik olarak yeniden analiz ediliyor.")
            try:
                prior = get_previous_period_kpis(ticker, int(yil), donem) if ticker else None
                with st.spinner("PDF indiriliyor..."):
                    pdf_bytes = _download_pdf_bytes(url)
                with st.spinner("Metin çıkarılıyor..."):
                    text, n_pages = _extract_pdf_text(pdf_bytes)
                if not text.strip():
                    st.error("PDF'ten metin çıkarılamadı (taranmış/görüntü tabanlı bir PDF olabilir).")
                else:
                    with st.spinner(f"Gemini ile analiz ediliyor ({n_pages} sayfa, {len(text):,} karakter)..."):
                        kpis = _summarize_with_gemini(text, ticker, DONEM_LABELS[donem], int(yil), prior)

                    if kpis.get('_parse_failed'):
                        # Bozuk/yarim sonucu KALICI olarak kaydetmiyoruz - aksi halde
                        # ayni link tekrar denendiginde "zaten analiz edildi" diyip
                        # bu bozuk sonucu sonsuza kadar cache'den gosterirdik.
                        st.error("⚠️ Gemini'nin yanıtı yapısal olarak işlenemedi (muhtemelen "
                                 "yanıt yarıda kesildi). Kaydedilmedi — lütfen 'Analiz Et'e "
                                 "tekrar basmayı dene.")
                        with st.expander("Ham yanıtı gör"):
                            st.text(kpis.get('metin_ozeti', ''))
                    else:
                        saved = save_report_summary(url, ticker, int(yil) if ticker else None,
                                                     donem if ticker else None, kpis, len(text))
                        if saved:
                            get_existing_summary.clear()
                            get_all_summaries.clear()
                            get_ticker_history.clear()
                            st.success("✅ Analiz tamamlandı ve kalıcı olarak kaydedildi.")
                        else:
                            st.warning("⚠️ Analiz tamamlandı ama veritabanına kaydedilemedi — "
                                       "sayfa yenilenirse kaybolabilir.")
                        st.session_state['_last_report'] = {
                            'ticker': ticker, 'yil': int(yil), 'donem': donem, **kpis,
                            'ham_metin_uzunluk': len(text),
                        }
            except Exception as e:
                st.error(f"Hata: {e}")

    r = st.session_state.get('_last_report')
    if r:
        st.markdown("---")
        sektor_str = f" | 🏭 {r['sektor']}" if r.get('sektor') else ""
        st.markdown(f"#### 🎯 Hedef Özeti — {r.get('ticker') or ''} {DONEM_LABELS.get(r.get('donem'), '')} {r.get('yil') or ''}{sektor_str}")
        if r.get('marj_puani') is not None or r.get('gorunum_puani') is not None:
            m1, m2 = st.columns(2)
            with m1:
                st.metric("📊 Marj Puanı", f"{r.get('marj_puani') or '—'} / 5")
                st.caption(r.get('marj_yorumu') or '')
            with m2:
                st.metric("🔮 Görünüm Puanı", f"{r.get('gorunum_puani') or '—'} / 5")
                st.caption(r.get('gorunum_yorumu') or '')
        k1, k2, k3 = st.columns(3)
        with k1:
            _kpi_card("💰 Satış/Ciro Hedefi", r.get('satis_hedefi'), r.get('satis_yonu'))
        with k2:
            _kpi_card("📈 FAVÖK Hedefi", r.get('favok_hedefi'), r.get('favok_yonu'))
        with k3:
            _kpi_card("💵 Net Kâr Hedefi", r.get('net_kar_hedefi'), r.get('net_kar_yonu'))
        st.markdown("---")
        st.markdown(r.get('ozet', ''))

        if r.get('ticker'):
            hist = get_ticker_history(r['ticker'])
            if len(hist) > 1:
                st.markdown("---")
                st.markdown(f"#### 📈 {r['ticker']} — Hedef Geçmişi (Çeyrek Çeyrek)")
                show = hist.copy()
                show['Dönem'] = show.apply(lambda x: f"{DONEM_LABELS.get(x['donem'], x['donem'])} {int(x['yil'])}", axis=1)
                show['Satış Hedefi'] = show.apply(lambda x: f"{x['satis_hedefi'] or '—'} ({YON_BADGE.get(x['satis_yonu'], '')})", axis=1)
                show['FAVÖK Hedefi'] = show.apply(lambda x: f"{x['favok_hedefi'] or '—'} ({YON_BADGE.get(x['favok_yonu'], '')})", axis=1)
                show['Net Kâr Hedefi'] = show.apply(lambda x: f"{x['net_kar_hedefi'] or '—'} ({YON_BADGE.get(x['net_kar_yonu'], '')})", axis=1)
                st.dataframe(show[['Dönem', 'Satış Hedefi', 'FAVÖK Hedefi', 'Net Kâr Hedefi']],
                             use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### 📚 Tüm Kayıtlı Özetler — Yıl / Dönem Bazında")
    df = get_all_summaries()
    if df.empty:
        st.info("Henüz kayıtlı özet yok.")
    else:
        # Yil -> Donem -> satirlar seklinde grupla (get_all_summaries zaten bu
        # sirada donuyor ama burada acikca gruplu basliklar olusturuyoruz -
        # kullanicinin talebi: "quarter ve yil bazinda classified olsun,
        # yoksa ilerde cok karisir").
        no_period = df[df['yil'].isna()]
        with_period = df[df['yil'].notna()]

        for yil, yil_grp in with_period.groupby('yil', sort=False):
            st.markdown(f"##### 📅 {int(yil)}")
            for donem, donem_grp in yil_grp.groupby('donem', sort=False):
                st.markdown(f"**{DONEM_LABELS.get(donem, donem)}**")
                for _, row in donem_grp.iterrows():
                    sektor_badge = f" · 🏭 {row['sektor']}" if pd.notna(row.get('sektor')) else ""
                    title = f"{row['ticker'] or row['kaynak_url'][:60]}{sektor_badge}"
                    with st.expander(f"{title} — {row['olusturma_zamani']:%d.%m.%Y %H:%M}"):
                        st.caption(row['kaynak_url'])
                        if pd.notna(row.get('marj_puani')) or pd.notna(row.get('gorunum_puani')):
                            m1, m2 = st.columns(2)
                            with m1:
                                st.markdown(f"**📊 Marj Puanı: {row.get('marj_puani', '—')}/5**")
                                if pd.notna(row.get('marj_yorumu')):
                                    st.caption(row['marj_yorumu'])
                            with m2:
                                st.markdown(f"**🔮 Görünüm Puanı: {row.get('gorunum_puani', '—')}/5**")
                                if pd.notna(row.get('gorunum_yorumu')):
                                    st.caption(row['gorunum_yorumu'])
                            st.markdown("---")
                        st.markdown(row['ozet'])

        if not no_period.empty:
            st.markdown("##### ❓ Dönem Belirtilmemiş")
            for _, row in no_period.iterrows():
                title = row['ticker'] or row['kaynak_url'][:60]
                with st.expander(f"{title} — {row['olusturma_zamani']:%d.%m.%Y %H:%M}"):
                    st.caption(row['kaynak_url'])
                    st.markdown(row['ozet'])

    # ── Sektor Analizi ──
    st.markdown("---")
    st.markdown("#### 🏭 Sektör Analizi")
    st.caption("Seçilen yıl/dönem içindeki raporları sektörlere göre kümeleyip, sektörleri "
               "birbirleriyle kıyaslayarak analiz eder. **Hesapla/Yenile** o dönem için yeni "
               "bir Gemini çağrısı yapar (yeni eklenen raporlar da dahil edilir); **Göster** "
               "ise hiçbir çağrı yapmadan en son hesaplanmış tabloyu getirir.")

    periods = get_available_periods_for_rollup()
    if periods.empty:
        st.info("Henüz yıl/dönem bilgisiyle kayıtlı bir rapor yok — önce yukarıdan bir analiz yap.")
    else:
        period_options = list(periods.itertuples(index=False, name=None))  # [(yil, donem), ...]

        def _period_fmt(p):
            y, d = p
            return f"{DONEM_LABELS.get(d, d)} {int(y)}"

        sel_yil, sel_donem = st.selectbox(
            "Yıl / Dönem", period_options, format_func=_period_fmt, key="sektor_rollup_period",
        )

        col_hesapla, col_goster = st.columns(2)
        with col_hesapla:
            hesapla_clicked = st.button(
                "🔄 Hesapla / Yenile", use_container_width=True,
                help="Bu dönem için raporları yeniden tarar ve YENİ bir Gemini çağrısı yapar.",
            )
        with col_goster:
            goster_clicked = st.button(
                "👁️ Göster", use_container_width=True,
                help="Gemini çağrısı yapmadan, bu dönem için en son hesaplanmış tabloyu gösterir.",
            )

        if hesapla_clicked:
            donem_raporlari = get_reports_for_period(sel_yil, sel_donem)
            if donem_raporlari.empty:
                st.warning(f"{_period_fmt((sel_yil, sel_donem))} için kayıtlı rapor yok.")
            else:
                try:
                    with st.spinner(f"{len(donem_raporlari)} şirket sektörlere göre "
                                     f"sınıflandırılıp analiz ediliyor..."):
                        n_sektor, n_sirket = compute_sector_rollup(sel_yil, sel_donem)
                    st.success(f"✅ {n_sirket} şirket, {n_sektor} sektöre ayrılarak "
                               f"{_period_fmt((sel_yil, sel_donem))} analizi güncellendi.")
                    st.session_state['_sektor_rollup_shown_period'] = (sel_yil, sel_donem)
                except Exception as e:
                    st.error(f"Hata: {e}")

        if goster_clicked:
            st.session_state['_sektor_rollup_shown_period'] = (sel_yil, sel_donem)

        shown_period = st.session_state.get('_sektor_rollup_shown_period')
        if shown_period:
            rollup = get_sector_rollup(*shown_period)
            donem_raporlari = get_reports_for_period(*shown_period)
            if rollup.empty:
                st.info(f"{_period_fmt(shown_period)} için sektör analizi henüz "
                        f"hesaplanmadı — \"Hesapla / Yenile\" butonuna bas.")
            else:
                for _, srow in rollup.iterrows():
                    skor = srow['sektor_skoru']
                    skor_str = f"{skor:.1f}/5" if pd.notna(skor) else "—"
                    with st.expander(f"🏭 {srow['sektor']} — Sektör Skoru: {skor_str} "
                                      f"({int(srow['sirket_sayisi'] or 0)} şirket)"):
                        st.markdown(srow['makro_analiz'] or '_Analiz yok._')
                        st.markdown("---")
                        companies = donem_raporlari[donem_raporlari['sektor'] == srow['sektor']].copy()
                        companies['_skor'] = companies[['marj_puani', 'gorunum_puani']].mean(axis=1, skipna=True)
                        companies = companies.sort_values('_skor', ascending=False, na_position='last')
                        show = companies.copy()
                        show['Dönem'] = show.apply(
                            lambda x: f"{DONEM_LABELS.get(x['donem'], x['donem'])} {int(x['yil'])}"
                            if pd.notna(x['yil']) else '—', axis=1)
                        show['Marj Puanı'] = show['marj_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Görünüm Puanı'] = show['gorunum_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Özet Değerleme'] = show['marj_yorumu'].fillna('') + " " + show['gorunum_yorumu'].fillna('')
                        st.dataframe(
                            show[['ticker', 'Dönem', 'Marj Puanı', 'Görünüm Puanı', 'Özet Değerleme']]
                                .rename(columns={'ticker': 'Hisse'}),
                            use_container_width=True, hide_index=True,
                        )
