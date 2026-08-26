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
            CREATE UNIQUE INDEX IF NOT EXISTS idx_company_report_period
                ON company_report_summaries(ticker, yil, donem)
                WHERE ticker IS NOT NULL AND yil IS NOT NULL AND donem IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_company_report_ticker
                ON company_report_summaries(ticker, olusturma_zamani DESC);
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
        report_text=truncated,
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            max_output_tokens=8000,  # ~900 kelimelik detayli analiz + JSON overhead icin (2500 yetersizdi - JSON yarida kesiliyordu)
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    raw = response.text

    try:
        parsed = _parse_llm_json(raw)
    except json.JSONDecodeError:
        # Yapisal cikarma basarisiz oldu - en azindan ham yaniti metin ozeti
        # olarak goster, KPI alanlarini bos birak. Sessizce veri uydurmaktan
        # iyidir.
        parsed = {
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
    vals = (
        ticker, url, yil, donem,
        kpis.get('satis_hedefi'), kpis.get('satis_yonu'),
        kpis.get('favok_hedefi'), kpis.get('favok_yonu'),
        kpis.get('net_kar_hedefi'), kpis.get('net_kar_yonu'),
        ozet, ham_metin_uzunluk,
    )
    with conn.cursor() as cur:
        if ticker and yil and donem:
            cur.execute("""
                INSERT INTO company_report_summaries
                    (ticker, kaynak_url, yil, donem, satis_hedefi, satis_yonu,
                     favok_hedefi, favok_yonu, net_kar_hedefi, net_kar_yonu,
                     ozet, ham_metin_uzunluk)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (ticker, yil, donem) WHERE ticker IS NOT NULL
                    AND yil IS NOT NULL AND donem IS NOT NULL
                DO UPDATE SET
                    kaynak_url = EXCLUDED.kaynak_url,
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
                    (ticker, kaynak_url, yil, donem, satis_hedefi, satis_yonu,
                     favok_hedefi, favok_yonu, net_kar_hedefi, net_kar_yonu,
                     ozet, ham_metin_uzunluk)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (kaynak_url) DO UPDATE SET
                    ozet = EXCLUDED.ozet, ham_metin_uzunluk = EXCLUDED.ham_metin_uzunluk
            """, vals)
    return True


@st.cache_data(ttl=60, show_spinner=False)
def get_existing_summary(url):
    conn = _get_live_connection()
    if conn is None:
        return None
    df = pd.read_sql("""
        SELECT ticker, yil, donem, satis_hedefi, satis_yonu, favok_hedefi, favok_yonu,
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
        SELECT id, ticker, yil, donem, kaynak_url, satis_yonu, favok_yonu, net_kar_yonu,
               ozet, olusturma_zamani
        FROM company_report_summaries
        ORDER BY olusturma_zamani DESC
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
        if existing is not None:
            st.info("✅ Bu link daha önce analiz edilmiş — kayıtlı özet gösteriliyor "
                    "(Gemini'ye tekrar sorulmadı).")
            st.session_state['_last_report'] = existing
        else:
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
        st.markdown(f"#### 🎯 Hedef Özeti — {r.get('ticker') or ''} {DONEM_LABELS.get(r.get('donem'), '')} {r.get('yil') or ''}")
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
    st.markdown("#### 📚 Tüm Kayıtlı Özetler")
    df = get_all_summaries()
    if df.empty:
        st.info("Henüz kayıtlı özet yok.")
        return

    for _, row in df.iterrows():
        donem_str = f" — {DONEM_LABELS.get(row['donem'], '')} {int(row['yil'])}" if pd.notna(row['yil']) else ""
        title = f"{row['ticker'] or row['kaynak_url'][:60]}{donem_str}"
        with st.expander(f"{title} — {row['olusturma_zamani']:%d.%m.%Y %H:%M}"):
            st.caption(row['kaynak_url'])
            st.markdown(row['ozet'])
