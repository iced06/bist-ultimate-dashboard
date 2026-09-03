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

_MARGIN_FIELDS = [
    ("gross_margin", "gross_margin_prev", "brüt kâr marjı"),
    ("ebitda_margin", "ebitda_margin_prev", "FAVÖK marjı"),
    ("net_margin", "net_margin_prev", "net kâr marjı"),
]

# NOT: Marj Puanı/Marj Gelişim Puanı sadece FAVÖK+net kâr marjına dayanır
# (bkz. compute_margin_scores_for_ticker). Brüt kâr marjı raporun METNİNDE
# mutlaka anlatılır (bkz. SUMMARY_PROMPT_TEMPLATE) ama SAYISAL skora dahil
# EDİLMEZ - üç farklı ölçekteki oranı (brüt kâr genelde %20-30, net kâr
# genelde tek haneli) tek bir "kompozit" yüzdede eritip ortalamak (eski
# _composite_margin/Marj Current) "toplam değerin bir anlamı yok" - FAVÖK
# ve net kâr AYRI AYRI puanlanıp sadece o 1-5 SKORLARIN ortalaması alınıyor.


def _margin_level_score(ticker, sektor_tickers, financial_margins, field_key, label):
    """Tek bir marj oranının (örn. sadece FAVÖK) AYNI SEKTÖRDEKİ diğer
    şirketlere göre z-score bazlı 1-5 seviye skoru + yorum üretir.
    compute_margin_scores_for_ticker'ın FAVÖK Puanı/Net Kâr Puanı
    hesaplarını paylaştığı ortak mantık.
    En az 1 DİĞER şirkette bu oran için veri varsa hesaplar; tek başınaysa
    (None, None) döner."""
    financial_margins = financial_margins or {}
    fm = financial_margins.get(ticker)
    my_val = fm.get(field_key) if fm else None
    if my_val is None:
        return None, None
    all_vals = {}
    for t in sektor_tickers:
        v = (financial_margins.get(t) or {}).get(field_key)
        if v is not None:
            all_vals[t] = v
    all_vals[ticker] = my_val
    others = [v for t, v in all_vals.items() if t != ticker]
    if len(others) < 1:
        return None, None
    mean = sum(others) / len(others)
    variance = sum((v - mean) ** 2 for v in others) / len(others)
    std = variance ** 0.5
    if std == 0:
        score = 5.0 if my_val > mean else (1.0 if my_val < mean else 3.0)
    else:
        z = max(-1.5, min(1.5, (my_val - mean) / std))
        score = 3.0 + z * (2.0 / 1.5)
    score = max(1.0, min(5.0, score))
    ranked = sorted(all_vals.items(), key=lambda kv: -kv[1])
    rank = next((i + 1 for i, (t, _) in enumerate(ranked) if t == ticker), None)
    yorumu = (f"{label} %{my_val:.1f}, sektördeki diğer şirketlerin ortalaması %{mean:.1f}"
              + (f" — {rank}. sırada / {len(all_vals)} şirket arasında" if rank else "") + ".")
    return round(score, 1), yorumu


def _margin_development_score(fm, field_key, label, compare_suffix="_prev",
                                period_latest_key="period_latest", period_compare_key="period_prev"):
    """Tek bir marj oranının (örn. sadece Net Kâr) belirtilen döneme göre
    (varsayılan: bir önceki raporlanan dönem; compare_suffix='_yoy' ile
    bir önceki YILDAKİ aynı çeyrek de kullanılabilir - bkz. Marj Gelişim
    Puanı (Yıllık)) 0-5 gelişim skoru + yorum üretir."""
    if not fm:
        return None, None
    compare_key = f"{field_key}{compare_suffix}"
    if fm.get(field_key) is None or fm.get(compare_key) is None:
        return None, None
    d = fm[field_key] - fm[compare_key]
    score = max(0.0, min(5.0, 2.5 + d * 0.5))
    period_note = (f" ({fm[period_compare_key]} → {fm[period_latest_key]})"
                    if fm.get(period_latest_key) and fm.get(period_compare_key) else "")
    yorumu = (f"{label} %{fm[compare_key]:.1f} → %{fm[field_key]:.1f} "
              f"({'+' if d >= 0 else ''}{d:.1f} puan){period_note}.")
    return round(score, 1), yorumu


def compute_margin_scores_for_ticker(ticker, sektor_tickers, financial_margins):
    """Kullanıcı tanımlı TAM marj skorlama hiyerarşisini tek çağrıda hesaplar:

      FAVÖK Puanı, Net Kâr Puanı        (sektör peer z-score, 1-5)
        -> Marj Puanı = ikisinin ortalaması
      FAVÖK Gelişim Puanı, Net Kâr Gelişim Puanı  (bir önceki döneme göre, 0-5)
        -> Marj Gelişim Puanı = ikisinin ortalaması
      Marj Toplam Puanı = (Marj Puanı + Marj Gelişim Puanı) / 2
      (Overall Puan = (Marj Toplam Puanı + Görünüm Puanı) / 2 - gorunum_
       puani'yi bilen ÇAĞIRAN tarafından hesaplanır, bkz. _finalize_scores)

    Ayrıca BONUS bir "Marj Gelişim Puanı (Yıllık)" hesaplar: aynı iki oranın
    (FAVÖK+Net) bir önceki YILDAKİ aynı çeyreğe göre (YoY-YTD, mevsimsellikten
    arındırılmış) gelişimi - Marj Toplam Puanı'na dahil DEĞİL, ayrı bilgi
    amaçlı bir skor.

    NOT: Brüt kâr marjı bilerek SAYISAL skora dahil edilmez (kullanıcı
    talebi - üç farklı ölçekli oranı tek "kompozit" yüzdede eritmenin
    anlamı yoktu); rapor METNİNDE ayrıca mutlaka anlatılır.

    sektor_tickers boş/None verilirse (henüz sektör atanmamışsa) seviye
    skorları (FAVÖK/Net Kâr Puanı, dolayısıyla Marj Puanı) None kalır -
    peer karşılaştırması için sektör grubu şart; gelişim skorları yine de
    hesaplanır.

    Donus: dict - herhangi bir alan hesaplanamazsa None kalır (anahtarlar:
      favok_puani, favok_puani_yorumu, net_kar_puani, net_kar_puani_yorumu,
      marj_puani, marj_yorumu,
      favok_gelisim_puani, favok_gelisim_yorumu,
      net_kar_gelisim_puani, net_kar_gelisim_yorumu,
      marj_gelisim_puani, marj_gelisim_yorumu,
      marj_gelisim_yillik_puani, marj_gelisim_yillik_yorumu,
      marj_toplam_puani)."""
    fm = (financial_margins or {}).get(ticker)
    out = {k: None for k in (
        "favok_puani", "favok_puani_yorumu", "net_kar_puani", "net_kar_puani_yorumu",
        "marj_puani", "marj_yorumu",
        "favok_gelisim_puani", "favok_gelisim_yorumu",
        "net_kar_gelisim_puani", "net_kar_gelisim_yorumu",
        "marj_gelisim_puani", "marj_gelisim_yorumu",
        "marj_gelisim_yillik_puani", "marj_gelisim_yillik_yorumu",
        "marj_toplam_puani",
    )}

    if sektor_tickers:
        out["favok_puani"], out["favok_puani_yorumu"] = _margin_level_score(
            ticker, sektor_tickers, financial_margins, "ebitda_margin", "FAVÖK marjı")
        out["net_kar_puani"], out["net_kar_puani_yorumu"] = _margin_level_score(
            ticker, sektor_tickers, financial_margins, "net_margin", "Net kâr marjı")
        level_scores = [s for s in (out["favok_puani"], out["net_kar_puani"]) if s is not None]
        if level_scores:
            out["marj_puani"] = round(sum(level_scores) / len(level_scores), 1)
            out["marj_yorumu"] = " ".join(
                p for p in (out["favok_puani_yorumu"], out["net_kar_puani_yorumu"]) if p)

    out["favok_gelisim_puani"], out["favok_gelisim_yorumu"] = _margin_development_score(
        fm, "ebitda_margin", "FAVÖK marjı")
    out["net_kar_gelisim_puani"], out["net_kar_gelisim_yorumu"] = _margin_development_score(
        fm, "net_margin", "Net kâr marjı")
    dev_scores = [s for s in (out["favok_gelisim_puani"], out["net_kar_gelisim_puani"]) if s is not None]
    if dev_scores:
        out["marj_gelisim_puani"] = round(sum(dev_scores) / len(dev_scores), 1)
        out["marj_gelisim_yorumu"] = " ".join(
            p for p in (out["favok_gelisim_yorumu"], out["net_kar_gelisim_yorumu"]) if p)

    favok_yillik, favok_yillik_y = _margin_development_score(
        fm, "ebitda_margin", "FAVÖK marjı", compare_suffix="_yoy", period_compare_key="period_yoy")
    net_yillik, net_yillik_y = _margin_development_score(
        fm, "net_margin", "Net kâr marjı", compare_suffix="_yoy", period_compare_key="period_yoy")
    yillik_scores = [s for s in (favok_yillik, net_yillik) if s is not None]
    if yillik_scores:
        out["marj_gelisim_yillik_puani"] = round(sum(yillik_scores) / len(yillik_scores), 1)
        out["marj_gelisim_yillik_yorumu"] = " ".join(p for p in (favok_yillik_y, net_yillik_y) if p)

    toplam_parts = [s for s in (out["marj_puani"], out["marj_gelisim_puani"]) if s is not None]
    if toplam_parts:
        out["marj_toplam_puani"] = round(sum(toplam_parts) / len(toplam_parts), 1)

    return out


def _fmt_tl_compact(x):
    """Buyume Puani yorumlarinda kullanilan kisa TL bicimi (Mr/Mn/duz)."""
    if x is None:
        return "—"
    a = abs(x)
    sign = "-" if x < 0 else ""
    if a >= 1e9:
        return f"{sign}{a/1e9:,.2f} Mr TL"
    if a >= 1e6:
        return f"{sign}{a/1e6:,.1f} Mn TL"
    return f"{sign}{a:,.0f} TL"


def _growth_score(fm, field_key, label, compare_suffix="_prev",
                    period_latest_key="period_latest", period_compare_key="period_prev"):
    """Tek bir MUTLAK (nominal TL) büyüklüğün (örn. sadece FAVÖK TL - MARJ
    DEĞİL) belirtilen döneme göre % büyüme oranına dayalı 0-5 skor + yorum
    üretir. Marj skorlarından (oran bazlı) BAĞIMSIZ bir boyut - kullanıcı
    notu: "satışlar/FAVÖK nominal olarak düşmüş olabilir ama marjlar
    yükselmiş olabilir - iyi bir şey ama satışlarını/FAVÖK'ünü AYNI ANDA
    marjlarını da artıran bir şirket kadar iyi değil". Önceki değer 0 ise
    (bölme tanımsız) veya biri eksikse (None, None) döner."""
    if not fm:
        return None, None
    compare_key = f"{field_key}{compare_suffix}"
    cur_val, prev_val = fm.get(field_key), fm.get(compare_key)
    if cur_val is None or prev_val is None or prev_val == 0:
        return None, None
    growth_pct = (cur_val - prev_val) / abs(prev_val) * 100
    # +-%50 buyume skorun uclarina tasir (2.5 +- 2.5). Marj gelisim
    # skorlarindaki katsayidan (puan bazinda 0.5) BILEREK farkli/daha
    # kucuk bir katsayi (1/20) kullaniliyor - Turkiye'deki yuksek enflasyon
    # ortaminda nominal buyume oranlari marj puan degisimlerinden (tipik
    # +-birkac puan) cok daha genis olabiliyor.
    score = max(0.0, min(5.0, 2.5 + growth_pct / 20))
    period_note = (f" ({fm[period_compare_key]} → {fm[period_latest_key]})"
                    if fm.get(period_latest_key) and fm.get(period_compare_key) else "")
    yorumu = (f"{label} {_fmt_tl_compact(prev_val)} → {_fmt_tl_compact(cur_val)} "
              f"({'+' if growth_pct >= 0 else ''}{growth_pct:.1f}%){period_note}.")
    return round(score, 1), yorumu


def compute_growth_scores_for_ticker(financial_margins, ticker):
    """Satış (gelir), FAVÖK ve net kârın MUTLAK (nominal TL) büyümesine
    dayalı skor hiyerarşisi - Marj Puanı/Marj Gelişim Puanı'nın
    TAMAMLAYICISI: bir şirket marjlarını iyileştirse bile satış/FAVÖK/net
    kârı KÜÇÜLÜYORSA bu, marj skorlarına hiç yansımayan AYRI bir sinyaldir
    (kullanıcı talebi - bkz. _growth_score docstring'i).

      Satış Büyüme Puanı, FAVÖK Büyüme Puanı, Net Kâr Büyüme Puanı (0-5)
        -> Büyüme Puanı = üçünün ortalaması

    ÖNEMLİ - karşılaştırma YILLIK BAZDA (YTD YoY, period_yoy) yapılır, bir
    önceki RAPORLANAN döneme göre (period_prev) DEĞİL: Türkiye'deki
    KÜMÜLATİF çeyreklik raporlama yüzünden (Ç1=3 ay, Ç2=6 ay YTD, Ç3=9 ay
    YTD, YS=12 ay YTD) bir önceki raporlanan dönem HER ZAMAN daha KISA bir
    süreyi kapsar (örn. Ç2 vs Ç1 = 6 ay vs 3 ay) - bu yüzden MUTLAK (TL)
    büyüklükler için "önceki döneme göre" kıyaslaması sahte/yanıltıcı bir
    "büyüme" gösterir (sadece daha fazla ay toplanmış olmasından kaynaklanır,
    gerçek performansla ilgisi yoktur). Marj (oran) skorlarında bu sorun
    YOKTUR çünkü pay ve payda aynı oranda şişer - ama MUTLAK TL rakamlarında
    ölçüm SADECE aynı uzunluktaki dönemleri (aynı çeyrek etiketinin bir
    önceki YILDAKİ karşılığı) kıyaslayarak güvenilir olur. Bu yüzden bu
    fonksiyon skorlarını (marj tarafındaki "_prev" birincil / "_yoy" bonus
    yapısının TERSİNE) YoY'a dayandırır; period_yoy verisi yoksa (örn. sadece
    1 yıllık geçmiş import edilmişse) skor hesaplanmaz (None) - yanıltıcı bir
    period-over-period rakamına DÜŞÜLMEZ.

    Donus: dict - herhangi bir alan hesaplanamazsa None kalır (anahtarlar:
      satis_buyume_puani, satis_buyume_yorumu,
      favok_buyume_puani, favok_buyume_yorumu,
      net_kar_buyume_puani, net_kar_buyume_yorumu,
      buyume_puani, buyume_yorumu,
      buyume_puani_yillik, buyume_yillik_yorumu - bu ikisi artık ANA skorla
      AYNI (YoY) yöntemle hesaplanıyor; geriye dönük uyumluluk için DB
      şemasında ayrı sütun olarak duruyor, ama artık kopya değer taşıyorlar)."""
    fm = (financial_margins or {}).get(ticker)
    out = {k: None for k in (
        "satis_buyume_puani", "satis_buyume_yorumu",
        "favok_buyume_puani", "favok_buyume_yorumu",
        "net_kar_buyume_puani", "net_kar_buyume_yorumu",
        "buyume_puani", "buyume_yorumu",
        "buyume_puani_yillik", "buyume_yillik_yorumu",
    )}

    out["satis_buyume_puani"], out["satis_buyume_yorumu"] = _growth_score(
        fm, "revenue", "Satışlar", compare_suffix="_yoy", period_compare_key="period_yoy")
    out["favok_buyume_puani"], out["favok_buyume_yorumu"] = _growth_score(
        fm, "ebitda_tl", "FAVÖK", compare_suffix="_yoy", period_compare_key="period_yoy")
    out["net_kar_buyume_puani"], out["net_kar_buyume_yorumu"] = _growth_score(
        fm, "net_profit", "Net Kâr", compare_suffix="_yoy", period_compare_key="period_yoy")
    scores = [s for s in (out["satis_buyume_puani"], out["favok_buyume_puani"],
                          out["net_kar_buyume_puani"]) if s is not None]
    if scores:
        out["buyume_puani"] = round(sum(scores) / len(scores), 1)
        out["buyume_yorumu"] = " ".join(
            p for p in (out["satis_buyume_yorumu"], out["favok_buyume_yorumu"],
                        out["net_kar_buyume_yorumu"]) if p)

    # buyume_puani_yillik/buyume_yillik_yorumu ana skorla AYNI (YoY) yöntemi
    # kullanıyor - DB şemasında (ve UI'da) ayrı sütun olarak duruyor ama artık
    # yeni bir bilgi TAŞIMIYOR (geriye dönük uyumluluk amaçlı kopya).
    out["buyume_puani_yillik"] = out["buyume_puani"]
    out["buyume_yillik_yorumu"] = out["buyume_yorumu"]

    return out


def compute_overall_puani(marj_toplam_puani, gorunum_puani, buyume_puani=None):
    """Overall Puan = Marj Toplam Puanı, Büyüme Puanı (varsa - satış/FAVÖK/
    net kârın MUTLAK büyümesi, bkz. compute_growth_scores_for_ticker) ve
    Görünüm Puanı'nın (faaliyet raporu/yatırımcı sunumu metninden LLM'in
    çıkardığı gelecek beklentisi tonu) ortalaması. Böylece hem marjlarını
    HEM DE nominal büyüklüklerini (satış/FAVÖK/net kâr) artıran bir şirket,
    sadece marjını iyileştiren (küçülen bir işi daha "verimli" hale
    getiren) bir şirketten daha yüksek Overall Puan alır - kullanıcı
    talebi. buyume_puani verilmezse (None) eski 2'li ortalamaya (Marj
    Toplam + Görünüm) geri düşer - geriye dönük uyumlu. Hiçbiri yoksa None."""
    parts = [p for p in (marj_toplam_puani, buyume_puani, gorunum_puani) if p is not None]
    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)


SUMMARY_PROMPT_TEMPLATE = """Sen kıdemli bir yatırım fonu analistisin. Aşağıda bir şirketin PDF'ten
çıkarılmış yatırımcı sunumu/faaliyet raporu metni var. Bu metin PDF'ten otomatik çıkarıldığı
için grafik/infografik etiketleri, sayılar ve başlıklar karışık sırada gelmiş olabilir -
anlamı çıkarmaya çalış, birebir sıralı okuma bekleme.

Şirket: {ticker}
Rapor dönemi: {donem_label} {yil}

{prior_context}

{financial_context}

GÖREV: Aşağıdaki alanları SADECE geçerli JSON olarak döndür. Başka hiçbir metin, açıklama
veya kod bloğu işareti (```) ekleme - yanıtın ilk karakteri {{ olmalı.

{{
  "sektor": "<şirketin ait olduğu sektör - AŞAĞIDAKİ LİSTEDEN TAM OLARAK BİRİNİ seç, başka bir
kelime kullanma: {sektor_listesi}>",
  "marj_development_puani": <0-5 arası (yarım puan olabilir) - "Marj Gelişim Puanı": SADECE
FAVÖK marjı ve net kâr marjının (brüt kâr marjı DAHİL DEĞİL - o sadece metinde anlatılır)
YÖNÜNÜ/GELİŞİMİNİ ölçen bir skor - şirketin KENDİ geçmiş dönemine (BİR ÖNCEKİ RAPORLANAN DÖNEME,
YTD YoY DEĞİL) göre karşılaştır, başka şirketle kıyaslama (bu ayrı/deterministik bir adımda
yapılıyor, gerçek finansal veri varsa senin bu alana yazdığın TAHMİN zaten EZİLİP gerçek
rakamla değiştirilecek). Raporda önceki döneme/yıla göre karşılaştırma varsa ona dayan.
0=FAVÖK ve net kâr marjları belirgin şekilde DÜŞMÜŞ, 2.5=yatay/karışık sinyal, 5=belirgin
şekilde YÜKSELMİŞ. Sadece yön/değişim büyüklüğünü yansıtır, mevcut marj seviyesinin GÜCÜNÜ değil>,
  "marj_development_yorumu": "<skoru gerekçelendiren 1-2 cümle, somut rakamlarla (örn. 'FAVÖK
marjı %8,1'den %8,6'ya yükseldi')>",
  "marj_ytd_puani": <0-5 arası (yarım puan olabilir) - marj_development_puani'nin YILLIK BAZDA
(YTD YoY) versiyonu (yine SADECE FAVÖK+net kâr marjı): AYNI çeyreğin bir önceki YILDAKİ
karşılığına göre karşılaştır (örn. bu 2. çeyrekse geçen yılın 2. çeyreğiyle), bir önceki
RAPORLANAN dönemle değil. Aşağıda "YILLIK BAZDA (YTD YoY)" bloğu verilmişse SADECE onu kullan
(hesaplama zaten yapılmış); verilmemişse VE rapor metninde geçen yılın aynı dönemine dair rakam
varsa ondan çıkar, yoksa null bırak. 0=yıllık bazda belirgin DÜŞÜŞ, 2.5=yatay, 5=yıllık bazda
belirgin YÜKSELİŞ>,
  "marj_ytd_yorumu": "<skoru gerekçelendiren 1-2 cümle, somut rakamlarla; YILLIK BAZDA veri yoksa
null>",
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
(Gelir, kâr, FAVÖK - önceki dönem/yıl karşılaştırmalı, rakamları yorumla: büyüme kaliteli mi,
marj daralması/genişlemesi neden kaynaklanıyor, birkaç paragraf. ZORUNLU - iki AYRI boyutu
BİRBİRİNE KARIŞTIRMADAN, AÇIKÇA ayırt ederek anlat:
(A) NOMİNAL/MUTLAK BÜYÜME: Satışlar, FAVÖK ve Net Kâr'ın TL bazında büyümüş mü küçülmüş mü
olduğunu üçü için de ayrı ayrı belirt - büyüme YÖNÜ değerlendirmesini YILLIK BAZDA (YTD YoY,
aynı çeyreğin bir önceki yıldaki karşılığı) rakamına dayandır (GERÇEK FİNANSAL VERİLER
bölümünde "GÜVENİLİR" diye işaretlenmiş satır). "Önceki döneme göre" rakamını YÖN çıkarmak için
KULLANMA - Türkiye'deki kümülatif çeyreklik raporlama yüzünden (örn. 6 aylık rakam 3 aylık
rakamla kıyaslanıyor) bu her zaman "büyümüş" görünür, gerçek performansla ilgisi olmayabilir.
Bu, marjlardan TAMAMEN BAĞIMSIZ bir boyuttur: bir şirket marjlarını yükseltirken aynı anda
satış/FAVÖK/net kârını (yıllık bazda) nominal olarak KÜÇÜLTMÜŞ olabilir (veya tam tersi) - böyle
bir ayrışma varsa MUTLAKA açıkça vurgula ve bunun ne anlama geldiğini yorumla (örn. 'satışlar
yıllık bazda nominal %5 daraldı ama FAVÖK marjı 2 puan yükseldi - bu maliyet disiplini/portföy
küçülmesinden mi kaynaklanıyor, kaliteli bir büyüme değil').
(B) MARJ GELİŞİMİ: brüt kâr marjı, FAVÖK marjı ve net kâr marjının ÜÇÜNÜ DE yüzde değerleriyle ve
İKİ AYRI KIYASLAMAYLA AÇIKÇA belirt: (1) bir önceki raporlanan döneme göre gelişim yönü
(yükseldi/düştü/sabit, kaç puan), (2) YILLIK BAZDA - aynı çeyreğin bir önceki yıldaki karşılığına
göre gelişim yönü (YTD YoY, kaç puan).
GERÇEK FİNANSAL VERİLER bölümü aşağıda verilmişse (hem "önceki döneme göre" hem "YILLIK BAZDA
(YTD YoY)" alt-blokları varsa) o rakamları BİREBİR kullan, verilmemişse rapor metninden çıkar
(YILLIK BAZDA için veri/rakam yoksa bu kıyaslamayı atlayabilirsin, uydurma))
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
ZORUNLU: bu paragrafta da (A) satış/FAVÖK/net kârın NOMİNAL büyüme yönünü (büyüyor/küçülüyor)
VE (B) brüt kâr marjı, FAVÖK marjı ve net kâr marjının üçünün genel gelişim yönünü
(iyileşiyor/kötüleşiyor/karışık) - hem önceki döneme göre HEM DE (varsa) yıllık bazda (YTD YoY)
- kısaca yeniden vurgula; bu iki boyut BİRBİRİNDEN FARKLI sonuca işaret ediyorsa (örn. marjlar
iyileşirken şirket nominal olarak küçülüyorsa) bunu AÇIKÇA söyle ve genel değerlendirmeyi buna
göre nüanslandır - final değerlendirmenin hem büyüme hem marj tablosuyla tutarlı olduğu net olsun.
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
- ZORUNLU: metin_ozeti içinde brüt kâr marjı, FAVÖK marjı VE net kâr marjının ÜÇÜ DE en az iki
  kez geçmeli (Finansal Performans + Değerlendirme ve Görünüm bölümlerinde) - yüzde değerleriyle
  ve gelişim yönleriyle birlikte. Bu üç oranı atlarsan/tek tek saymadan genel geçer bir cümleyle
  ("marjlar iyileşti" gibi) geçiştirirsen rapor eksik sayılır.
- ZORUNLU: metin_ozeti içinde satışların, FAVÖK'ün VE net kârın NOMİNAL/MUTLAK (TL bazında,
  yüzde değişim olarak) büyüyüp büyümediği de en az iki kez geçmeli (aynı iki bölümde) - bu,
  marj yüzdelerinden AYRI bir bilgidir ve marj değerlendirmesiyle karıştırılıp atlanmamalı.
  Marjların iyileşmesi TEK BAŞINA yeterli değildir - şirket aynı zamanda satış/FAVÖK/net kârını
  nominal olarak büyütüyor mu, buna ayrıca değinilmeli; büyütmüyorsa (marjlar iyi olsa bile) bu
  açıkça "iyi ama tam iyi değil" şeklinde nitelendirilmeli.

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

            -- Marj puani ikiye ayrildi: "development" (marjin KENDI gecmisine
            -- gore yonu/gucu - tek rapordan cikarilabilir) ve "current" (marjin
            -- SEKTOR ORTALAMASINA gore su anki konumu - sadece sektorun TUM
            -- sirketlerini bir arada goren sektor rollup cagrisi hesaplayabilir).
            -- Eski marj_puani/marj_yorumu artik "development" anlamina geliyor;
            -- gecmis kayitlar bir kerelik asagida development'a kopyalaniyor.
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_development_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_development_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_current_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_current_yorumu TEXT;

            -- Development, "bir onceki DOSYA SIRASINDAKI donem" ile kiyaslar
            -- (Turkiye'deki kumulatif ceyreklik raporlama yuzunden bu genelde
            -- ayni yil icinde daha kisa bir YTD'ye karsi kiyaslama olur, yil
            -- sinirinda ise 3 aylik veriyi 12 aylikla kiyaslar - mevsimsel
            -- gurultu icerebilir). YTD, AYNI ceyrek etiketinin bir onceki
            -- YILDAKI karsiligiyla (orn. 2026/6 vs 2025/6) kiyaslayip bu
            -- gurultuyu gideren AYRI/EK bir "gelisim" skorudur.
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_ytd_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_ytd_yorumu TEXT;
            UPDATE company_report_summaries
                SET marj_development_puani = marj_puani, marj_development_yorumu = marj_yorumu
                WHERE marj_development_puani IS NULL AND marj_puani IS NOT NULL;

            -- Marj skorlama hiyerarsisi YENIDEN TASARLANDI (kullanici talebi -
            -- brut+FAVOK+net'i tek "kompozit" yuzdede eritmenin anlami yoktu):
            -- FAVOK Puani + Net Kar Puani (sektor peer, 1-5) -> ortalamalari
            -- artik marj_current_puani/marj_current_yorumu kolonlarinda
            -- "Marj Puani" olarak tutuluyor (isim degismedi, ANLAMI degisti).
            -- FAVOK Gelisim Puani + Net Kar Gelisim Puani (0-5) -> ortalamalari
            -- artik marj_development_puani/marj_development_yorumu kolonlarinda
            -- "Marj Gelisim Puani" olarak tutuluyor (ayni sekilde ANLAMI
            -- degisti, kolon adi degismedi). marj_ytd_puani/marj_ytd_yorumu
            -- da ayni mantikla "Marj Gelisim Puani (Yillik)" oldu - ucu de
            -- artik SADECE FAVOK+Net'in ortalamasi, brut kar dahil degil.
            -- Alt-skorlar (FAVOK/Net Kar Puani ve Gelisim Puanlari) ile
            -- Marj Toplam Puani/Overall Puan icin YENI kolonlar:
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_puani_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_puani_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_gelisim_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_gelisim_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_gelisim_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_gelisim_yorumu TEXT;
            -- Marj Puani (marj_current_puani) ile Marj Gelisim Puani
            -- (marj_development_puani) ortalamasi:
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS marj_toplam_puani NUMERIC(3,1);

            -- Buyume Puani: satis/FAVOK/net karin MUTLAK (nominal TL, marj
            -- DEGIL) buyumesi - kullanici notu: "satislar ve FAVOK nominal
            -- olarak dusmus olabilir ama marjlar yukselmis olabilir - iyi
            -- bir sey ama satislarini/FAVOK'unu AYNI ZAMANDA marjlarini da
            -- artiran bir sirket kadar iyi degil". Marj skorlarindan
            -- BAGIMSIZ bir boyut - bkz. compute_growth_scores_for_ticker.
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS satis_buyume_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS satis_buyume_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_buyume_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS favok_buyume_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_buyume_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS net_kar_buyume_yorumu TEXT;
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS buyume_puani NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS buyume_yorumu TEXT;
            -- Yillik (YoY-YTD) versiyonu - Marj Gelisim Puani (Yillik) ile simetrik:
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS buyume_puani_yillik NUMERIC(3,1);
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS buyume_yillik_yorumu TEXT;

            -- Overall Puan artik Marj Toplam Puani + Buyume Puani (varsa) +
            -- Gorunum Puani (faaliyet raporu metninden LLM'in cikardigi
            -- genel ton) ortalamasi - nihai skor:
            ALTER TABLE company_report_summaries ADD COLUMN IF NOT EXISTS overall_puani NUMERIC(3,1);
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


def _format_financial_context(fm):
    """Import edilmis GERCEK finansallardan (varsa) brut kar/FAVOK/net kar
    marjlarini, hem bir onceki donemle HEM DE bir yil onceki AYNI donemle
    (YoY-YTD) karsilastirmali, LLM promptuna eklenecek bir metin blogu olarak
    hazirlar - boylece metin_ozeti'nin "Finansal Performans" ve
    "Degerlendirme" bolumleri TAHMIN degil GERCEK rakamlarla yazilir."""
    if not fm:
        return ("GERÇEK FİNANSAL VERİLER: Bu ticker için import edilmiş finansal veri yok - "
                "brüt kâr/FAVÖK/net kâr marjlarını rapor metninden çıkarman gerekiyor.")
    lines = ["GERÇEK FİNANSAL VERİLER (import edilmiş, KESIN doğru - rapor metnindeki "
             "olası farklı rakamlar yerine BUNLARI kullan):"]
    lines.append("")
    lines.append("NOMİNAL/MUTLAK BÜYÜKLÜKLER (TL, marjlardan BAĞIMSIZ - satış/FAVÖK/net kâr "
                 "büyüyor mu küçülüyor mu, bunu marj değerlendirmesiyle KARIŞTIRMA). ÖNEMLİ: "
                 "büyüme/küçülme değerlendirmesi için SADECE 'yıllık bazda (YTD YoY)' satırını "
                 "kullan - 'önceki döneme göre' satırı KÜMÜLATİF çeyreklik raporlama yüzünden "
                 "(örn. 6 aylık rakam 3 aylık rakamla kıyaslanıyor) yanıltıcıdır, sadece daha "
                 "fazla ay biriktiği için büyümüş GÖRÜNÜR - bunu gerçek büyüme olarak yorumlama, "
                 "sadece ham rakam bilgisi olarak metinde geçebilirsin ama YÖN değerlendirmesini "
                 "YTD YoY satırına dayandır:")
    _abs_fields = [
        ("revenue", "revenue_prev", "revenue_yoy", "Satışlar"),
        ("ebitda_tl", "ebitda_tl_prev", "ebitda_tl_yoy", "FAVÖK"),
        ("net_profit", "net_profit_prev", "net_profit_yoy", "Net Kâr"),
    ]
    any_abs = False
    for key, prev_key, yoy_key, label in _abs_fields:
        v, vp, vy = fm.get(key), fm.get(prev_key), fm.get(yoy_key)
        if v is not None and vp is not None:
            any_abs = True
            lines.append(f"- {label} (önceki döneme göre, FARKLI UZUNLUKTA dönemler - büyüme "
                         f"yönü çıkarma!): {_fmt_tl_compact(vp)} → {_fmt_tl_compact(v)}")
        if v is not None and vy is not None:
            any_abs = True
            pct_y = (v - vy) / abs(vy) * 100 if vy else None
            yon_y = "büyüdü" if (pct_y or 0) > 0 else ("küçüldü" if (pct_y or 0) < 0 else "sabit kaldı")
            pct_y_str = f", {'+' if pct_y >= 0 else ''}{pct_y:.1f}%" if pct_y is not None else ""
            lines.append(f"- {label} (yıllık bazda, YTD YoY - GÜVENİLİR kıyaslama): "
                         f"{_fmt_tl_compact(vy)} → {_fmt_tl_compact(v)} (nominal {yon_y}{pct_y_str})")
    if not any_abs:
        lines.append("- (nominal büyüklük karşılaştırması için yeterli veri yok)")
    lines.append("")
    lines.append("MARJ ORANLARI (yukarıdaki nominal büyüklüklerden AYRI bir boyut):")
    for key, prev_key, label in _MARGIN_FIELDS:
        v, vp = fm.get(key), fm.get(prev_key)
        if v is not None and vp is not None:
            d = v - vp
            yon = "yükseldi" if d > 0 else ("düştü" if d < 0 else "sabit kaldı")
            lines.append(f"- {label} (önceki döneme göre): %{vp:.1f} → %{v:.1f} ({yon}, "
                         f"{'+' if d >= 0 else ''}{d:.1f} puan)")
        elif v is not None:
            lines.append(f"- {label}: %{v:.1f} (önceki dönem verisi yok)")
    if fm.get('period_latest') and fm.get('period_prev'):
        lines.append(f"(Dönemler: {fm['period_prev']} → {fm['period_latest']})")
    # YoY-YTD: ayni ceyrek etiketinin bir onceki yildaki karsiligi - Turkiye'deki
    # kumulatif ceyreklik raporlamada mevsimsellikten arindirilmis, daha
    # anlamli bir "yillik bazda gelisim" karsilastirmasi (bkz.
    # _margin_development_score'un compare_suffix="_yoy" kullanimi).
    if fm.get('period_yoy'):
        lines.append("")
        lines.append(f"YILLIK BAZDA (YTD YoY, {fm['period_yoy']} → {fm['period_latest']}) "
                      "- AYNI çeyrek etiketinin bir önceki yıldaki karşılığıyla kıyaslama, "
                      "mevsimsellikten arındırılmış:")
        for key, _prev_key, label in _MARGIN_FIELDS:
            v, vy = fm.get(key), fm.get(f"{key}_yoy")
            if v is not None and vy is not None:
                d = v - vy
                yon = "yükseldi" if d > 0 else ("düştü" if d < 0 else "sabit kaldı")
                lines.append(f"- {label} (yıllık bazda): %{vy:.1f} → %{v:.1f} ({yon}, "
                             f"{'+' if d >= 0 else ''}{d:.1f} puan)")
    return "\n".join(lines)


def _summarize_with_gemini(report_text, ticker, donem_label, yil, prior_kpis, financial_margins=None):
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

    fm = (financial_margins or {}).get(ticker) if ticker else None
    financial_context = _format_financial_context(fm)

    client = genai.Client(api_key=api_key)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        ticker=ticker or "(belirtilmedi)",
        donem_label=donem_label or "",
        yil=yil or "",
        prior_context=prior_context,
        financial_context=financial_context,
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
            "sektor": None, "marj_development_puani": None, "marj_development_yorumu": None,
            "marj_ytd_puani": None, "marj_ytd_yorumu": None,
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

    # Marj Gelisim Puani (FAVOK+net kar, brut kar DAHIL DEGIL) icin import
    # edilmis GERCEK finansal veri varsa, LLM'in metinden yaptigi TAHMINI
    # onunla EZ - deterministik ve daha dogru, Gemini kotasi da harcamiyor.
    # Yoksa LLM'in tahmini fallback olarak kalir. Sektor bu asamada HENUZ
    # atanmadigi icin (parsed['sektor'] - ayni cagrinin cikisi) peer/seviye
    # skorlari (FAVOK/Net Kar Puani, Marj Puani, Marj Toplam Puani, Overall)
    # burada HESAPLANAMAZ - bkz. compute_sector_rollup/refresh_all_margin_
    # scores (o sekilde TUM sektordeki sirketler bir arada gorulebiliyor).
    margin_scores = compute_margin_scores_for_ticker(ticker, None, financial_margins) if ticker else {}
    if margin_scores.get("marj_gelisim_puani") is not None:
        parsed["marj_development_puani"] = margin_scores["marj_gelisim_puani"]
        parsed["marj_development_yorumu"] = (
            margin_scores["marj_gelisim_yorumu"] + " (kaynak: import edilmiş finansallar)")
    if margin_scores.get("marj_gelisim_yillik_puani") is not None:
        parsed["marj_ytd_puani"] = margin_scores["marj_gelisim_yillik_puani"]
        parsed["marj_ytd_yorumu"] = (
            margin_scores["marj_gelisim_yillik_yorumu"] + " (kaynak: import edilmiş finansallar, YTD YoY)")
    # FAVOK/Net Kar Gelisim alt-skorlari her zaman parsed'e ekleniyor (varsa) -
    # save_report_summary bunlari da kalici olarak DB'ye yazar.
    for k in ("favok_gelisim_puani", "favok_gelisim_yorumu",
              "net_kar_gelisim_puani", "net_kar_gelisim_yorumu"):
        parsed[k] = margin_scores.get(k)

    # Buyume Puani (satis/FAVOK/net karin MUTLAK buyumesi) - peer/sektor
    # GEREKTIRMEDIGI icin (marj_current_puani'nin aksine) bu asamada da
    # hesaplanabiliyor.
    growth_scores = compute_growth_scores_for_ticker(financial_margins, ticker) if ticker else {}
    for k in ("satis_buyume_puani", "satis_buyume_yorumu",
              "favok_buyume_puani", "favok_buyume_yorumu",
              "net_kar_buyume_puani", "net_kar_buyume_yorumu",
              "buyume_puani", "buyume_yorumu",
              "buyume_puani_yillik", "buyume_yillik_yorumu"):
        parsed[k] = growth_scores.get(k)

    # Peer-bagimli alanlar bu asamada hep None - sektor rollup/refresh
    # calistiginda doldurulacak. (marj_current_puani/yorumu = "Marj Puani",
    # bkz. _apply_margin_scores'daki kolon esleme notu.)
    for k in ("favok_puani", "favok_puani_yorumu", "net_kar_puani", "net_kar_puani_yorumu",
              "marj_current_puani", "marj_current_yorumu", "marj_toplam_puani"):
        parsed.setdefault(k, None)

    # Overall Puan burada da hesaplanabilir (Buyume Puani ve Gorunum Puani
    # ikisi de peer GEREKTIRMEZ - sadece Marj Puani/marj_current_puani
    # eksik kalir, compute_overall_puani onsuz da ortalama alir).
    parsed["overall_puani"] = compute_overall_puani(
        parsed.get("marj_toplam_puani"), parsed.get("gorunum_puani"), growth_scores.get("buyume_puani"))

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
        sektor, kpis.get('marj_development_puani'), kpis.get('marj_development_yorumu'),
        kpis.get('marj_ytd_puani'), kpis.get('marj_ytd_yorumu'),
        kpis.get('favok_gelisim_puani'), kpis.get('favok_gelisim_yorumu'),
        kpis.get('net_kar_gelisim_puani'), kpis.get('net_kar_gelisim_yorumu'),
        kpis.get('satis_buyume_puani'), kpis.get('satis_buyume_yorumu'),
        kpis.get('favok_buyume_puani'), kpis.get('favok_buyume_yorumu'),
        kpis.get('net_kar_buyume_puani'), kpis.get('net_kar_buyume_yorumu'),
        kpis.get('buyume_puani'), kpis.get('buyume_yorumu'),
        kpis.get('buyume_puani_yillik'), kpis.get('buyume_yillik_yorumu'),
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
                    (ticker, kaynak_url, yil, donem, sektor, marj_development_puani, marj_development_yorumu,
                     marj_ytd_puani, marj_ytd_yorumu,
                     favok_gelisim_puani, favok_gelisim_yorumu,
                     net_kar_gelisim_puani, net_kar_gelisim_yorumu,
                     satis_buyume_puani, satis_buyume_yorumu,
                     favok_buyume_puani, favok_buyume_yorumu,
                     net_kar_buyume_puani, net_kar_buyume_yorumu,
                     buyume_puani, buyume_yorumu,
                     buyume_puani_yillik, buyume_yillik_yorumu,
                     gorunum_puani, gorunum_yorumu, satis_hedefi, satis_yonu,
                     favok_hedefi, favok_yonu, net_kar_hedefi, net_kar_yonu,
                     ozet, ham_metin_uzunluk)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (ticker, yil, donem) WHERE ticker IS NOT NULL
                    AND yil IS NOT NULL AND donem IS NOT NULL
                DO UPDATE SET
                    kaynak_url = EXCLUDED.kaynak_url,
                    sektor = EXCLUDED.sektor,
                    marj_development_puani = EXCLUDED.marj_development_puani,
                    marj_development_yorumu = EXCLUDED.marj_development_yorumu,
                    marj_ytd_puani = EXCLUDED.marj_ytd_puani,
                    marj_ytd_yorumu = EXCLUDED.marj_ytd_yorumu,
                    favok_gelisim_puani = EXCLUDED.favok_gelisim_puani,
                    favok_gelisim_yorumu = EXCLUDED.favok_gelisim_yorumu,
                    net_kar_gelisim_puani = EXCLUDED.net_kar_gelisim_puani,
                    net_kar_gelisim_yorumu = EXCLUDED.net_kar_gelisim_yorumu,
                    satis_buyume_puani = EXCLUDED.satis_buyume_puani,
                    satis_buyume_yorumu = EXCLUDED.satis_buyume_yorumu,
                    favok_buyume_puani = EXCLUDED.favok_buyume_puani,
                    favok_buyume_yorumu = EXCLUDED.favok_buyume_yorumu,
                    net_kar_buyume_puani = EXCLUDED.net_kar_buyume_puani,
                    net_kar_buyume_yorumu = EXCLUDED.net_kar_buyume_yorumu,
                    buyume_puani = EXCLUDED.buyume_puani,
                    buyume_yorumu = EXCLUDED.buyume_yorumu,
                    buyume_puani_yillik = EXCLUDED.buyume_puani_yillik,
                    buyume_yillik_yorumu = EXCLUDED.buyume_yillik_yorumu,
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
            # favok_puani/net_kar_puani/marj_puani/marj_toplam_puani/overall_puani
            # (marj_current_puani vb.) kasten bu UPDATE'e dahil edilmedi - sadece
            # sektor rollup/refresh_all_margin_scores hesaplayabilir (peer
            # karsilastirmasi gerekir), rutin metin ozeti yenilemesi onlari
            # SIFIRLAMAMALI. Buyume Puani ailesi buraya DAHIL EDILDI - marj
            # skorlarinin aksine peer/sektor GEREKTIRMEZ, tek basina bu
            # ticker'in kendi finansallarindan hesaplanir, rutin yenilemede
            # bayatlamaz.
        else:
            cur.execute("""
                INSERT INTO company_report_summaries
                    (ticker, kaynak_url, yil, donem, sektor, marj_development_puani, marj_development_yorumu,
                     marj_ytd_puani, marj_ytd_yorumu,
                     favok_gelisim_puani, favok_gelisim_yorumu,
                     net_kar_gelisim_puani, net_kar_gelisim_yorumu,
                     satis_buyume_puani, satis_buyume_yorumu,
                     favok_buyume_puani, favok_buyume_yorumu,
                     net_kar_buyume_puani, net_kar_buyume_yorumu,
                     buyume_puani, buyume_yorumu,
                     buyume_puani_yillik, buyume_yillik_yorumu,
                     gorunum_puani, gorunum_yorumu, satis_hedefi, satis_yonu,
                     favok_hedefi, favok_yonu, net_kar_hedefi, net_kar_yonu,
                     ozet, ham_metin_uzunluk)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (kaynak_url) DO UPDATE SET
                    ozet = EXCLUDED.ozet, ham_metin_uzunluk = EXCLUDED.ham_metin_uzunluk,
                    sektor = EXCLUDED.sektor, marj_development_puani = EXCLUDED.marj_development_puani,
                    marj_development_yorumu = EXCLUDED.marj_development_yorumu,
                    satis_buyume_puani = EXCLUDED.satis_buyume_puani,
                    satis_buyume_yorumu = EXCLUDED.satis_buyume_yorumu,
                    favok_buyume_puani = EXCLUDED.favok_buyume_puani,
                    favok_buyume_yorumu = EXCLUDED.favok_buyume_yorumu,
                    net_kar_buyume_puani = EXCLUDED.net_kar_buyume_puani,
                    net_kar_buyume_yorumu = EXCLUDED.net_kar_buyume_yorumu,
                    buyume_puani = EXCLUDED.buyume_puani,
                    buyume_yorumu = EXCLUDED.buyume_yorumu,
                    buyume_puani_yillik = EXCLUDED.buyume_puani_yillik,
                    buyume_yillik_yorumu = EXCLUDED.buyume_yillik_yorumu,
                    marj_ytd_puani = EXCLUDED.marj_ytd_puani,
                    marj_ytd_yorumu = EXCLUDED.marj_ytd_yorumu,
                    favok_gelisim_puani = EXCLUDED.favok_gelisim_puani,
                    favok_gelisim_yorumu = EXCLUDED.favok_gelisim_yorumu,
                    net_kar_gelisim_puani = EXCLUDED.net_kar_gelisim_puani,
                    net_kar_gelisim_yorumu = EXCLUDED.net_kar_gelisim_yorumu,
                    gorunum_puani = EXCLUDED.gorunum_puani,
                    gorunum_yorumu = EXCLUDED.gorunum_yorumu
            """, vals)
    return True


@st.cache_data(ttl=60, show_spinner=False)
def get_existing_summary(url):
    conn = _get_live_connection()
    if conn is None:
        return None
    df = pd.read_sql("""
        SELECT ticker, yil, donem, sektor,
               marj_development_puani, marj_development_yorumu,
               marj_current_puani, marj_current_yorumu,
               marj_ytd_puani, marj_ytd_yorumu,
               favok_puani, favok_puani_yorumu, net_kar_puani, net_kar_puani_yorumu,
               favok_gelisim_puani, favok_gelisim_yorumu,
               net_kar_gelisim_puani, net_kar_gelisim_yorumu,
               satis_buyume_puani, satis_buyume_yorumu, favok_buyume_puani, favok_buyume_yorumu,
               net_kar_buyume_puani, net_kar_buyume_yorumu, buyume_puani, buyume_yorumu,
               buyume_puani_yillik, buyume_yillik_yorumu,
               marj_toplam_puani, overall_puani,
               gorunum_puani, gorunum_yorumu,
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
               marj_development_puani, marj_development_yorumu,
               marj_current_puani, marj_current_yorumu,
               marj_ytd_puani, marj_ytd_yorumu,
               favok_puani, favok_puani_yorumu, net_kar_puani, net_kar_puani_yorumu,
               favok_gelisim_puani, favok_gelisim_yorumu,
               net_kar_gelisim_puani, net_kar_gelisim_yorumu,
               satis_buyume_puani, satis_buyume_yorumu, favok_buyume_puani, favok_buyume_yorumu,
               net_kar_buyume_puani, net_kar_buyume_yorumu, buyume_puani, buyume_yorumu,
               buyume_puani_yillik, buyume_yillik_yorumu,
               marj_toplam_puani, overall_puani,
               gorunum_puani, gorunum_yorumu,
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
        SELECT ticker, yil, donem, sektor,
               marj_development_puani, marj_development_yorumu,
               marj_current_puani, marj_current_yorumu,
               marj_ytd_puani, marj_ytd_yorumu,
               favok_puani, favok_puani_yorumu, net_kar_puani, net_kar_puani_yorumu,
               favok_gelisim_puani, favok_gelisim_yorumu,
               net_kar_gelisim_puani, net_kar_gelisim_yorumu,
               satis_buyume_puani, satis_buyume_yorumu, favok_buyume_puani, favok_buyume_yorumu,
               net_kar_buyume_puani, net_kar_buyume_yorumu, buyume_puani, buyume_yorumu,
               buyume_puani_yillik, buyume_yillik_yorumu,
               marj_toplam_puani, overall_puani,
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
şirketlerinin {donem_label} {yil} dönemine ait faaliyet raporu/yatırımcı sunumu özetleri var
(bazılarında ayrıca şirketin gerçek finansallarından hesaplanmış bir "marj gelişimi" notu da
bulunuyor - bu sadece bağlam için verildi, sen bu puanı DEĞİL, aşağıdaki görevleri üreteceksin).
Şirketler henüz sektörlere ayrılmamış olabilir - bu senin görevinin bir parçası.

Görevlerin:
1) HER şirketi, SADECE aşağıdaki listeden TEK bir sektöre ata (listedeki isimleri birebir kullan):
   {sektor_listesi}
2) HER şirket için, ÖZETİNDEKİ bilgilere dayanarak 1-5 arası (yarım puan olabilir, örn 3.5):
   - gorunum_puani: Raporda yer alan pozitif/negatif beklentilerin genel değerlemesi
     (5=çok olumlu görünüm, 1=çok olumsuz görünüm)
   - gorunum_yorumu: "<1 kısa cümlelik gerekçe>"
3) HER sektör için, o sektördeki şirketlerin verilerine dayanarak bir MAKRO SEKTÖR ANALİZİ yaz ve
   sektörleri BİRBİRİYLE KIYASLAYARAK 1-5 arası bir sektör skoru ver (5=en güçlü/olumlu
   görünümlü sektör, 1=en zayıf/olumsuz). Skorlar mutlaka birbirinden farklılaşsın - bütün
   sektörlere aynı skoru verme, gerçek bir sıralama/kıyaslama yap.

Not: Şirketlerin sektör ortalamasına göre marj konumu (Marj Puanı) BURADA senin isin degil -
gercek finansal verilerden ayrica ve deterministik olarak hesaplanacak.

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
        {{"ticker": "<TICKER>", "gorunum_puani": <1-5>, "gorunum_yorumu": "<kısa gerekçe>"}}
      ]
    }}
  ]
}}
"""


def _apply_margin_scores(cur, ticker, yil, donem, sektor_tickers, financial_margins, gorunum_puani_for_overall):
    """Bir (ticker, yıl, dönem) satırının TÜM marj alt-skorlarını
    (compute_margin_scores_for_ticker: FAVÖK/Net Kâr Puanı, Marj Puanı,
    FAVÖK/Net Kâr Gelişim Puanı, Marj Gelişim Puanı (+Yıllık), Marj Toplam
    Puanı) hesaplayıp DB'de günceller; Overall Puan için
    gorunum_puani_for_overall kullanılır (çağıran taze bir değer biliyorsa
    onu - örn. Gemini'nin az önce döndürdüğü -, bilmiyorsa satırın mevcut
    DB değerini vermeli). Sadece GERÇEKTEN hesaplanabilen alanlar
    güncellenir - eksik veri yüzünden hesaplanamayan bir alan, önceki bir
    hesaplamadan kalma değeri SIFIRLAMAZ.
    compute_sector_rollup ve refresh_all_margin_scores tarafından paylaşılır.
    Donus: DB'ye yazılan set_values dict'i (boş dict = hiçbir alan
    hesaplanamadı, hiçbir şey güncellenmedi)."""
    scores = compute_margin_scores_for_ticker(ticker, sektor_tickers, financial_margins)
    growth = compute_growth_scores_for_ticker(financial_margins, ticker)
    set_values = {}
    for k in ("favok_puani", "favok_puani_yorumu", "net_kar_puani", "net_kar_puani_yorumu"):
        if scores.get(k) is not None:
            set_values[k] = scores[k]
    if scores.get("marj_puani") is not None:
        set_values["marj_current_puani"] = scores["marj_puani"]
        set_values["marj_current_yorumu"] = scores["marj_yorumu"]
    if scores.get("marj_gelisim_puani") is not None:
        set_values["marj_development_puani"] = scores["marj_gelisim_puani"]
        set_values["marj_development_yorumu"] = scores["marj_gelisim_yorumu"] + " (kaynak: import edilmiş finansallar)"
    if scores.get("marj_gelisim_yillik_puani") is not None:
        set_values["marj_ytd_puani"] = scores["marj_gelisim_yillik_puani"]
        set_values["marj_ytd_yorumu"] = (
            scores["marj_gelisim_yillik_yorumu"] + " (kaynak: import edilmiş finansallar, YTD YoY)")
    if scores.get("favok_gelisim_puani") is not None:
        set_values["favok_gelisim_puani"] = scores["favok_gelisim_puani"]
        set_values["favok_gelisim_yorumu"] = scores["favok_gelisim_yorumu"]
    if scores.get("net_kar_gelisim_puani") is not None:
        set_values["net_kar_gelisim_puani"] = scores["net_kar_gelisim_puani"]
        set_values["net_kar_gelisim_yorumu"] = scores["net_kar_gelisim_yorumu"]
    if scores.get("marj_toplam_puani") is not None:
        set_values["marj_toplam_puani"] = scores["marj_toplam_puani"]

    # Büyüme Puanı (satış/FAVÖK/net kârın MUTLAK büyümesi) - marj
    # skorlarından BAĞIMSIZ bir boyut, bkz. compute_growth_scores_for_ticker.
    for k in ("satis_buyume_puani", "satis_buyume_yorumu",
              "favok_buyume_puani", "favok_buyume_yorumu",
              "net_kar_buyume_puani", "net_kar_buyume_yorumu"):
        if growth.get(k) is not None:
            set_values[k] = growth[k]
    if growth.get("buyume_puani") is not None:
        set_values["buyume_puani"] = growth["buyume_puani"]
        set_values["buyume_yorumu"] = growth["buyume_yorumu"]
    if growth.get("buyume_puani_yillik") is not None:
        set_values["buyume_puani_yillik"] = growth["buyume_puani_yillik"]
        set_values["buyume_yillik_yorumu"] = growth["buyume_yillik_yorumu"]

    overall = compute_overall_puani(
        scores.get("marj_toplam_puani"), gorunum_puani_for_overall, growth.get("buyume_puani"))
    if overall is not None:
        set_values["overall_puani"] = overall

    if not set_values:
        return set_values
    set_sql = ", ".join(f"{col} = %s" for col in set_values)
    cur.execute(f"""
        UPDATE company_report_summaries
        SET {set_sql}
        WHERE ticker = %s AND yil = %s AND donem = %s
    """, list(set_values.values()) + [ticker, int(yil), donem])
    return set_values


def compute_sector_rollup(yil, donem, financial_margins=None):
    """Secilen (yil, donem) icin kayitli TUM rapor ozetlerini TEK bir Gemini
    cagrisinda sektorlere siniflandirir + sektor/gorunum analizini uretir
    (ayri ayri cagirsaydik model diger sektorleri/sirketleri gormeden
    "kiyaslamali" skor veremezdi). Sektor atamasi onceden yapilmis olmasi
    sart degil - bu fonksiyon o donemdeki TUM raporlari (sektoru bos olanlar
    dahil) tarar ve siniflandirir.

    Marj Puani (FAVOK+Net Kar seviye skorlarinin ortalamasi), Gemini'nin
    DEGIL, bu fonksiyonun Python tarafinin isi: Gemini'nin DONDURDUGU sektor
    gruplarina gore, her sirketin (varsa) import edilmis GERCEK
    finansallardan hesaplanan FAVOK ve Net Kar marjlarini AYRI AYRI AYNI
    SEKTORDEKI diger sirketlerle kiyaslar (bkz. _apply_margin_scores /
    compute_margin_scores_for_ticker). Ayrica Marj Gelisim Puani, Marj
    Gelisim Puani (Yillik), Marj Toplam Puani ve Overall Puan da (varsa)
    finansallardan tazelenir - ilk analiz sirasinda financial_store'da
    olmayip sonradan import edilmis olabilir.

    Sonuclari sector_rollup_analysis tablosuna (yil, donem, sektor) anahtariyla
    kaydeder (upsert); ayrica company_report_summaries uzerindeki sektor/marj/
    gorunum alanlarini da gunceller."""
    if genai is None:
        raise RuntimeError("google-genai paketi kurulu değil.")
    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY secrets/environment değişkeni eksik.")

    reports = get_reports_for_period(yil, donem)
    if reports.empty:
        raise RuntimeError(f"{DONEM_LABELS.get(donem, donem)} {yil} için hiç kayıtlı rapor yok.")

    financial_margins = financial_margins or {}
    valid_tickers = set(reports['ticker'])
    lines = []
    for _, r in reports.iterrows():
        ozet_kisa = (r['ozet'] or '')[:600]
        dev_note = ""
        if pd.notna(r.get('marj_development_puani')):
            dev_note = (f"\n(Bağlam - marj gelişimi notu: {r['marj_development_puani']}/5, "
                        f"{r.get('marj_development_yorumu') or ''})")
        if pd.notna(r.get('marj_ytd_puani')):
            dev_note += (f"\n(Bağlam - yıllık bazda (YTD YoY) marj notu: {r['marj_ytd_puani']}/5, "
                         f"{r.get('marj_ytd_yorumu') or ''})")
        lines.append(f"\n## {r['ticker']}\nÖzet: {ozet_kisa}...{dev_note}")
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
            sektor_tickers = [c['ticker'] for c in sirketler]
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
                ticker = c['ticker']
                gorunum_puani = c.get('gorunum_puani')
                cur.execute("""
                    UPDATE company_report_summaries
                    SET sektor = %s, gorunum_puani = %s, gorunum_yorumu = %s
                    WHERE ticker = %s AND yil = %s AND donem = %s
                """, (sektor, gorunum_puani, c.get('gorunum_yorumu'), ticker, int(yil), donem))
                # FAVÖK/Net Kâr Puanı, Marj Puanı, gelişim skorları, Marj
                # Toplam Puanı, Overall Puan - bkz. _apply_margin_scores.
                _apply_margin_scores(cur, ticker, yil, donem, sektor_tickers,
                                      financial_margins, gorunum_puani)
                sirket_toplam += 1
    conn.commit()
    get_sector_rollup.clear()
    get_reports_for_period.clear()
    get_available_periods_for_rollup.clear()
    return len(parsed.get('sektorler', [])), sirket_toplam


def refresh_all_margin_scores(financial_margins):
    """Company Reports'ta ŞİMDİYE KADAR kayıtlı TÜM (ticker, yıl, dönem)
    raporlarının TÜM marj skorlarını (FAVÖK/Net Kâr Puanı, Marj Puanı,
    FAVÖK/Net Kâr Gelişim Puanı, Marj Gelişim Puanı (+Yıllık), Marj Toplam
    Puanı, Overall Puan) YENİ import edilmiş financial_margins'e göre
    YENİDEN hesaplar ve DB'de günceller - compute_sector_rollup'ın aksine
    Gemini'YE HİÇ SORMAZ (sektör ataması ve Görünüm Puanı zaten var, sadece
    marj rakamları gerçek finansal veriyle tazeleniyor). "Financial Data"
    toplu import edildikten SONRA geçmiş raporları güncel finansallarla
    senkronlamak için kullanılır (bkz. Company Reports > 🔄 Marjları
    Finansallardan Tazele butonu).

    Seviye skorları (FAVÖK/Net Kâr Puanı, dolayısıyla Marj Puanı) için peer
    grubu, o (yıl, dönem) içinde HALİHAZIRDA aynı sektöre atanmış diğer
    ticker'lardan kurulur (yeniden sınıflandırma YAPILMAZ) - sektörü boş
    olan raporlar için sadece gelişim skorları hesaplanır.

    Donus: dict(rapor_sayisi, marj_puani_hesaplanan, marj_gelisim_hesaplanan,
                 marj_gelisim_yillik_hesaplanan, marj_toplam_hesaplanan,
                 buyume_puani_hesaplanan)."""
    conn = _get_live_connection()
    stats = {"rapor_sayisi": 0, "marj_puani_hesaplanan": 0,
              "marj_gelisim_hesaplanan": 0, "marj_gelisim_yillik_hesaplanan": 0,
              "marj_toplam_hesaplanan": 0, "buyume_puani_hesaplanan": 0}
    if conn is None:
        return stats
    financial_margins = financial_margins or {}

    df = pd.read_sql("""
        SELECT ticker, yil, donem, sektor, gorunum_puani
        FROM company_report_summaries
        WHERE ticker IS NOT NULL AND yil IS NOT NULL AND donem IS NOT NULL
    """, conn)
    if df.empty:
        return stats
    stats["rapor_sayisi"] = len(df)

    with conn.cursor() as cur:
        for (yil, donem), grp in df.groupby(['yil', 'donem']):
            for sektor, sgrp in grp.groupby('sektor', dropna=False):
                sektor_tickers = list(sgrp['ticker']) if pd.notna(sektor) else None
                for _, row in sgrp.iterrows():
                    ticker = row['ticker']
                    gorunum_puani = row['gorunum_puani'] if pd.notna(row['gorunum_puani']) else None
                    set_values = _apply_margin_scores(
                        cur, ticker, yil, donem, sektor_tickers, financial_margins, gorunum_puani)
                    if "marj_current_puani" in set_values:
                        stats["marj_puani_hesaplanan"] += 1
                    if "marj_development_puani" in set_values:
                        stats["marj_gelisim_hesaplanan"] += 1
                    if "marj_ytd_puani" in set_values:
                        stats["marj_gelisim_yillik_hesaplanan"] += 1
                    if "marj_toplam_puani" in set_values:
                        stats["marj_toplam_hesaplanan"] += 1
                    if "buyume_puani" in set_values:
                        stats["buyume_puani_hesaplanan"] += 1
    conn.commit()
    get_sector_rollup.clear()
    get_reports_for_period.clear()
    get_available_periods_for_rollup.clear()
    get_all_summaries.clear()
    get_existing_summary.clear()
    get_ticker_history.clear()
    return stats


def _kpi_card(label, value, yon):
    st.markdown(f"**{label}**")
    st.markdown(value or "—")
    st.caption(YON_BADGE.get(yon, "❓ Belirsiz"))


def _render_margin_score_block(r):
    """Marj VE büyüme skorlama hiyerarşisini gösterir - "Hedef Özeti" (yeni
    analiz) kartı ve geçmiş rapor listesi kartı arasında paylaşılan ortak
    görsel blok:
      FAVÖK Puanı, Net Kâr Puanı -> Marj Puanı
      FAVÖK Gelişim P., Net Kâr Gelişim P. -> Marj Gelişim Puanı
      (+ bilgi amaçlı: Marj Gelişim Puanı (Yıllık))
      Marj Toplam Puanı
      Satış/FAVÖK/Net Kâr Büyüme Puanı -> Büyüme Puanı (MUTLAK/nominal TL
      büyüme - marjlardan BAĞIMSIZ: bir şirket marjlarını iyileştirse bile
      satış/FAVÖK/net kârı küçülüyorsa bu ayrı yakalanır)
      Marj Toplam Puanı, Büyüme Puanı, Görünüm Puanı -> Overall Puan
    r: dict veya dict-benzeri (pd.Series.to_dict() de olabilir) - eksik
    anahtarlar .get() ile None kabul edilir.
    Donus: hiç skor yoksa False (hiçbir şey çizilmedi), varsa True."""
    has_any = any(pd.notna(r.get(k)) for k in (
        'favok_puani', 'net_kar_puani', 'marj_current_puani',
        'favok_gelisim_puani', 'net_kar_gelisim_puani', 'marj_development_puani',
        'satis_buyume_puani', 'favok_buyume_puani', 'net_kar_buyume_puani', 'buyume_puani',
        'marj_toplam_puani', 'overall_puani', 'gorunum_puani'))
    if not has_any:
        return False

    def _v(key):
        v = r.get(key)
        return f"{v}/5" if pd.notna(v) else "—"

    st.caption("**Marj Puanı** — FAVÖK ve net kâr marjının sektör ortalamasına göre seviyesi "
               "(brüt kâr marjı bu skora dahil değil, sadece metinde anlatılır)")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("FAVÖK Puanı", _v('favok_puani'))
        if r.get('favok_puani_yorumu'):
            st.caption(r['favok_puani_yorumu'])
    with c2:
        st.metric("Net Kâr Puanı", _v('net_kar_puani'))
        if r.get('net_kar_puani_yorumu'):
            st.caption(r['net_kar_puani_yorumu'])
    with c3:
        st.metric("→ Marj Puanı", _v('marj_current_puani'))
    if pd.isna(r.get('marj_current_puani')):
        st.caption("ℹ️ Sadece \"Sektör Analizi\" bölümünde \"Hesapla/Yenile\" ya da "
                   "\"🔄 Marjları Finansallardan Tazele\" çalıştırıldıktan sonra hesaplanır "
                   "(sektördeki diğer şirketlerle kıyaslama gerekir).")

    st.caption("**Marj Gelişim Puanı** — bir önceki döneme göre FAVÖK ve net kâr marjı gelişimi")
    c4, c5, c6 = st.columns(3)
    with c4:
        st.metric("FAVÖK Gelişim P.", _v('favok_gelisim_puani'))
        if r.get('favok_gelisim_yorumu'):
            st.caption(r['favok_gelisim_yorumu'])
    with c5:
        st.metric("Net Kâr Gelişim P.", _v('net_kar_gelisim_puani'))
        if r.get('net_kar_gelisim_yorumu'):
            st.caption(r['net_kar_gelisim_yorumu'])
    with c6:
        st.metric("→ Marj Gelişim Puanı", _v('marj_development_puani'))
    if pd.notna(r.get('marj_ytd_puani')):
        st.caption(f"📅 Yıllık bazda (YTD YoY) Marj Gelişim Puanı: **{r['marj_ytd_puani']}/5**"
                   + (f" — {r['marj_ytd_yorumu']}" if r.get('marj_ytd_yorumu') else ""))

    st.caption("**Büyüme Puanı** — satış, FAVÖK ve net kârın MUTLAK (nominal TL) büyümesi, "
               "marjlardan bağımsız (marjı iyileşse bile satış/FAVÖK/net kârı küçülen bir "
               "şirket burada düşük puan alır). YILLIK BAZDA (YTD YoY, aynı çeyreğin bir "
               "önceki yıldaki karşılığı) kıyaslanır — kümülatif çeyreklik raporlama yüzünden "
               "bir önceki RAPORLANAN döneme göre kıyaslama (örn. 6 aylık vs 3 aylık) yanıltıcı "
               "olurdu (sadece daha fazla ay eklendiği için büyümüş görünür).")
    c7, c8, c9 = st.columns(3)
    with c7:
        st.metric("Satış Büyüme P.", _v('satis_buyume_puani'))
        if r.get('satis_buyume_yorumu'):
            st.caption(r['satis_buyume_yorumu'])
    with c8:
        st.metric("FAVÖK Büyüme P.", _v('favok_buyume_puani'))
        if r.get('favok_buyume_yorumu'):
            st.caption(r['favok_buyume_yorumu'])
    with c9:
        st.metric("Net Kâr Büyüme P.", _v('net_kar_buyume_puani'))
        if r.get('net_kar_buyume_yorumu'):
            st.caption(r['net_kar_buyume_yorumu'])
    st.metric("→ Büyüme Puanı", _v('buyume_puani'))

    st.markdown("---")
    c10, c11, c12, c13 = st.columns(4)
    with c10:
        st.metric("Marj Toplam Puanı", _v('marj_toplam_puani'))
        st.caption("(Marj Puanı + Marj Gelişim Puanı) / 2")
    with c11:
        st.metric("Büyüme Puanı", _v('buyume_puani'))
    with c12:
        st.metric("🔮 Görünüm Puanı", _v('gorunum_puani'))
        if r.get('gorunum_yorumu'):
            st.caption(r['gorunum_yorumu'])
    with c13:
        st.metric("⭐ Overall Puan", _v('overall_puani'))
        st.caption("(Marj Toplam + Büyüme + Görünüm) / 3")
    return True


def display_company_reports(financial_margins=None):
    """financial_margins: streamlit_app.get_financial_margin_snapshot()'un
    ciktisi - {ticker: {net_margin, net_margin_prev, gross_margin, ...}}.
    Verilmezse ({} / None) Marj Gelişim Puanı LLM tahminine, Marj Puanı ise
    hesaplanamadigi icin bos ('—') kalir - modul streamlit_app olmadan da
    (izole testlerde) calismaya devam eder."""
    financial_margins = financial_margins or {}
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
                        kpis = _summarize_with_gemini(text, ticker, DONEM_LABELS[donem], int(yil), prior,
                                                       financial_margins=financial_margins)

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
        _render_margin_score_block(r)
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
                        if _render_margin_score_block(row.to_dict()):
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
    if not financial_margins:
        st.caption("ℹ️ Marj Puanı/Gelişim Puanı/Gelişim Puanı (Yıllık), sidebar'dan **Import "
                   "Financials** çalıştırılmış hisseler için gerçek finansal verilerden "
                   "hesaplanır (daha doğru, Gemini kotası harcamaz). Henüz hiç finansal import "
                   "edilmemiş — Marj Puanı (sadece gerçek veriyle hesaplanır, LLM tahmini yok) "
                   "hiç hesaplanamıyor; Marj Gelişim Puanı ve Gelişim Puanı (Yıllık) ise "
                   "şimdilik faaliyet raporu metninden LLM tahminine dayanıyor (raporda geçen "
                   "yılın aynı döneminden bahsedilmiyorsa Yıllık versiyonu genelde boş kalır).")
    else:
        if st.button("🔄 Marjları Finansallardan Tazele (TÜM dönemler, Gemini'siz)",
                      use_container_width=True,
                      help="Şimdiye kadar kayıtlı TÜM raporların FAVÖK/Net Kâr Puanı, Marj "
                           "Puanı, FAVÖK/Net Kâr Gelişim Puanı, Marj Gelişim Puanı (+Yıllık), "
                           "Marj Toplam Puanı ve Overall Puan'ını import edilmiş finansallardan "
                           "yeniden hesaplar - sektör ataması, Görünüm Puanı ve metin özeti "
                           "DEĞİŞMEZ, Gemini'ye sorulmaz. Yeni bir toplu 'Import Financials' "
                           "sonrası çalıştır."):
            with st.spinner("Tüm raporların marj skorları finansallardan tazeleniyor..."):
                stats = refresh_all_margin_scores(financial_margins)
            st.success(
                f"✅ {stats['rapor_sayisi']} rapor tarandı — "
                f"Marj Puanı: {stats['marj_puani_hesaplanan']}, "
                f"Marj Gelişim Puanı: {stats['marj_gelisim_hesaplanan']}, "
                f"Marj Gelişim Puanı (Yıllık): {stats['marj_gelisim_yillik_hesaplanan']}, "
                f"Marj Toplam Puanı: {stats['marj_toplam_hesaplanan']}, "
                f"Büyüme Puanı: {stats['buyume_puani_hesaplanan']} rapor için gerçek "
                f"finansal veriyle güncellendi."
            )

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
                        n_sektor, n_sirket = compute_sector_rollup(sel_yil, sel_donem,
                                                                    financial_margins=financial_margins)
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
                        # Marj Toplam Puanı = (Marj Puanı + Marj Gelişim Puanı) / 2, Overall Puan
                        # = (Marj Toplam Puanı + Görünüm Puanı) / 2 - ikisi de _apply_margin_scores
                        # tarafından zaten hesaplanıp DB'ye yazılmış durumda (burada tekrar
                        # hesaplanmıyor). Sıralama Overall Puan'a göre.
                        companies = companies.sort_values('overall_puani', ascending=False, na_position='last')
                        show = companies.copy()
                        show['Dönem'] = show.apply(
                            lambda x: f"{DONEM_LABELS.get(x['donem'], x['donem'])} {int(x['yil'])}"
                            if pd.notna(x['yil']) else '—', axis=1)
                        show['Marj Puanı'] = show['marj_current_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Marj Gelişim Puanı'] = show['marj_development_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Marj Gel. P. (Yıllık)'] = show['marj_ytd_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Marj Toplam Puanı'] = show['marj_toplam_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Büyüme Puanı'] = show['buyume_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Görünüm Puanı'] = show['gorunum_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Overall Puan'] = show['overall_puani'].apply(lambda v: f"{v}/5" if pd.notna(v) else "—")
                        show['Özet Değerleme'] = (
                            show['marj_current_yorumu'].fillna('') + " " +
                            show['marj_development_yorumu'].fillna('') + " " +
                            show['marj_ytd_yorumu'].fillna('') + " " +
                            show['buyume_yorumu'].fillna('') + " " +
                            show['gorunum_yorumu'].fillna('')
                        ).str.strip()
                        st.dataframe(
                            show[['ticker', 'Dönem', 'Marj Puanı', 'Marj Gelişim Puanı',
                                  'Marj Gel. P. (Yıllık)', 'Marj Toplam Puanı', 'Büyüme Puanı',
                                  'Görünüm Puanı', 'Overall Puan', 'Özet Değerleme']]
                                .rename(columns={'ticker': 'Hisse'}),
                            use_container_width=True, hide_index=True,
                        )
