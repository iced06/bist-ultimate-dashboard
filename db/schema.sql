-- ============================================================
-- BIST Ultimate Dashboard — Faz 1 Şema Tasarımı
-- Hedef: Neon (Postgres 15+) — medconcept-dashboard ile PAYLAŞILAN sunucu
-- Excel kaynağı: "fonlar (version 3).xlsx"
--
-- Bu veritabanı sunucusu medconcept-dashboard ile paylaşılıyor (18 tablo,
-- public şemasında). Karışmasınlar diye BIST tablolarını ayrı bir "bist"
-- şemasında tutuyoruz. search_path'i ayarladıktan sonra asagidaki
-- CREATE TABLE/VIEW ifadeleri otomatik olarak bist şemasına düşer.
-- ============================================================
CREATE SCHEMA IF NOT EXISTS bist;
SET search_path TO bist, public;

-- 1) Menkul kıymetler (hisse/tahvil/fon) — surrogate id ile
--    NEDEN ISIN DEĞİL SURROGATE ID? İlk tasarımda isin'i PK yapmıştım ama
--    migration'ı yazarken fark ettim ki: mevcut Excel'in tarihsel verisinde
--    ("Hisseler", "Fon-Hisse Dağılımı" sayfaları) hiç ISIN yok — sadece
--    ticker + uyruk var. ISIN'i PK/NOT NULL yapmak tarihsel veriyi import
--    edilemez hale getirirdi. Bunun yerine: surrogate id PK, isin NULLABLE
--    + UNIQUE (varsa doldurulur, yoksa boş kalır), ticker+uyruk de UNIQUE
--    (tarihsel veri bunun üzerinden eşleşir). KAP'tan gelen yeni aylık veri
--    ISIN taşıdığı için, ileride ayni tickerin isin'i otomatik zenginleştirilir
--    (bkz. migration script'teki upsert_security fonksiyonu).
CREATE TABLE securities (
    id              BIGSERIAL PRIMARY KEY,
    isin            VARCHAR(12) UNIQUE,                -- KAP verisinde dolu, tarihsel Excel'de NULL
    ticker          VARCHAR(24) NOT NULL,
    ad              TEXT,
    uyruk           VARCHAR(3)  NOT NULL,              -- 'TC' | 'FOR'
    para_birimi     VARCHAR(3),                        -- 'TL' | 'USD' | 'EUR' | 'CHF' | ...
    varlik_sinifi   VARCHAR(20) NOT NULL DEFAULT 'HISSE_SENEDI',
                    -- 'HISSE_SENEDI' | 'BORCLANMA_SENEDI' | 'FON' | 'DIGER'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_securities_ticker ON securities(ticker);
-- (ticker, uyruk) UNIQUE bir SUTUN KISITI DEGIL, sadece ISIN'i BOS olan
-- (tarihsel Excel kaynakli) kayitlara uygulanan bir PARTIAL index - yabanci
-- hisselerde ayni ticker'i FARKLI sirketlerin paylasmasi COK yaygin (orn.
-- "SAN" hem Sanofi=FR0000120578 hem Santander=ES0113900J37 olabiliyor;
-- "BBVA" hem Ispanya hem ABD ADR listesi icin ayri ISIN'lerle gorulebiliyor).
-- KAP fon parser pilotunda (TMG fonu) gercek veriyle yakalandi - blanket
-- UNIQUE(ticker, uyruk) bu durumda IKINCI sirketin/listelemenin INSERT'ini
-- reddedip ilkiyle YANLISLIKLA birlestiriyordu. ISIN dolu oldugunda ISIN
-- zaten tekil kimlik oldugu icin bu kisitin korumaya ihtiyaci kalmiyor.
CREATE UNIQUE INDEX idx_securities_ticker_uyruk_legacy
    ON securities(ticker, uyruk) WHERE isin IS NULL;

-- 2) Fonlar (fon master data) — "Fonlar" / "Hisseler" sayfalarının kalıcı kısmı
CREATE TABLE funds (
    fon_kodu        VARCHAR(10) PRIMARY KEY,
    fon_adi         TEXT NOT NULL,
    kurucu_kurum    TEXT,
    pazar           VARCHAR(50),                       -- 'IMKB' | 'Yabancı Hisse' | 'MULTI' | ...
    sub_category    VARCHAR(50),
    kurulus_tarihi  DATE,
    aktif_mi        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3) Fon büyüklüğü (AUM) — aylık, "Fonlar" sayfası karşılığı
--    katilma_payi_giris/cikis_tl: KAP PDF'in II. bölümünde zaten hazır halde
--    duruyor ("Katılma Payı İhraçlarından Kaynaklanan Nakit Girişleri (TL)" /
--    "...İadelerinden Kaynaklanan Nakit Çıkışları (TL)" — pilotta DOH/HVS/TMG/NHY
--    hepsinde gördük). Bunu fon seviyesinde tutmak, hisse seviyesindeki
--    değişimi yorumlarken "fon zaten küçülüyordu" bağlamını verir — bkz.
--    fund_holdings_change view'ındaki miktar_etkisi_tl notu.
CREATE TABLE fund_aum_monthly (
    fon_kodu              VARCHAR(10) NOT NULL REFERENCES funds(fon_kodu),
    yil                   SMALLINT    NOT NULL,
    ay                    SMALLINT    NOT NULL CHECK (ay BETWEEN 1 AND 12),
    fon_toplam_degeri     NUMERIC(20,2),
    pay_fiyati            NUMERIC(18,6),
    pay_sayisi            NUMERIC(20,2),
    katilma_payi_giris_tl NUMERIC(20,2),        -- yeni katılımcı parası (ihraç)
    katilma_payi_cikis_tl NUMERIC(20,2),        -- çıkan yatırımcı parası (iade)
    kaynak                VARCHAR(20) NOT NULL DEFAULT 'MANUEL',   -- 'MANUEL' | 'TEFAS_API' | 'KAP_PDF'
    PRIMARY KEY (fon_kodu, yil, ay)
);

-- 4) Fon-hisse dağılımı — ASIL DEĞERLİ VERİ, "Fon-Hisse Dağılımı" sayfası karşılığı
--    Doğal anahtar (fon_kodu, yil, ay, isin) => aynı ayın importu tekrar
--    çalıştırılırsa ON CONFLICT DO UPDATE ile idempotent upsert yapılabilir
--    (KAP bazen düzeltme raporu yayınlıyor, bu durumda yeniden import gerekir).
CREATE TABLE fund_holdings (
    fon_kodu            VARCHAR(10) NOT NULL REFERENCES funds(fon_kodu),
    yil                 SMALLINT    NOT NULL,
    ay                  SMALLINT    NOT NULL CHECK (ay BETWEEN 1 AND 12),
    security_id         BIGINT      NOT NULL REFERENCES securities(id),
    nominal_deger       NUMERIC(20,4),                   -- tarihsel Excel'de NULL (Excel'de adet yok, sadece TL/agirlik)
    toplam_tutar_tl     NUMERIC(20,2) NOT NULL,
    agirlik_pct         NUMERIC(7,4)  NOT NULL,          -- FTD bazlı (fon toplam değerine göre)
    lot_sayisi          SMALLINT NOT NULL DEFAULT 1,     -- aggregate edilen lot adedi (izlenebilirlik)
    kaynak              VARCHAR(20) NOT NULL DEFAULT 'KAP_PDF',   -- 'KAP_PDF' | 'EXCEL_MANUEL'
    kaynak_bildirim_id  BIGINT,                          -- KAP bildirim id — hangi PDF'ten geldiğini iz sürmek için
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (fon_kodu, yil, ay, security_id)
);
CREATE INDEX idx_fund_holdings_security   ON fund_holdings(security_id, yil, ay);
CREATE INDEX idx_fund_holdings_fon_donem  ON fund_holdings(fon_kodu, yil, ay);

-- 5) Aylık değişim — TABLO DEĞİL, VIEW.
--    "Fon Değişim Pivot" sayfasının Excel'de elle/formülle tutulan değişim
--    sütunlarına karşılık gelir. Ayrı bir tabloda TUTMUYORUZ çünkü o zaman
--    fund_holdings güncellenince bu tablo da senkron tutulmalı (update anomalisi
--    riski). Postgres'te window function ile anlık hesaplamak, ~1M satırda bile
--    milisaniyeler sürer.
--
--    ÖNEMLİ AYRIM (kullanıcı notu üzerine eklendi): toplam_tutar_tl'deki ay-ay
--    değişim tek başına yanıltıcı — üç farklı şeyi karıştırır:
--      1) hissenin FİYATININ hareketi (fon hiçbir işlem yapmasa bile değişir)
--      2) fona giren/çıkan yatırımcı parasının TÜM portföye orantılı yansıması
--      3) fon yöneticisinin o hisseye özel GERÇEK al-sat kararı
--    (2) ve (3)'ü ayırmak fund_aum_monthly.katilma_payi_giris/cikis_tl'ye bakmayı
--    gerektirir (dashboard tarafında yorumlanır); ama (1) ile (3)'ü BURADA,
--    fiyat/miktar ayrıştırmasıyla (standart "price-volume bridge" tekniği)
--    kesin olarak ayırabiliyoruz — çünkü nominal_deger (adet) fiyattan bağımsız:
--      degisim_nominal   : fonun elindeki ADET değişimi -> gerçek al/sat sinyali
--      fiyat_etkisi_tl   : sadece fiyat hareketinden gelen TL değişimi
--      miktar_etkisi_tl  : sadece adet değişiminden gelen TL değişimi
--    fiyat_etkisi_tl + miktar_etkisi_tl ≈ degisim_tl (küçük bir çapraz terim
--    farkı hariç, bu standart bir yaklaşıklıktır).
CREATE VIEW fund_holdings_change AS
SELECT
    fon_kodu, security_id, yil, ay,
    toplam_tutar_tl,
    agirlik_pct,
    nominal_deger,
    toplam_tutar_tl - LAG(toplam_tutar_tl) OVER w AS degisim_tl,
    agirlik_pct     - LAG(agirlik_pct)     OVER w AS degisim_agirlik_pct,
    nominal_deger   - LAG(nominal_deger)   OVER w AS degisim_nominal,
    -- fiyat_etkisi: onceki ay elde tutulan adet x bu ayki-onceki ay birim fiyat farki
    LAG(nominal_deger) OVER w
        * ( (toplam_tutar_tl / NULLIF(nominal_deger, 0))
          - (LAG(toplam_tutar_tl) OVER w / NULLIF(LAG(nominal_deger) OVER w, 0)) )
        AS fiyat_etkisi_tl,
    -- miktar_etkisi: adet degisimi x bu ayki birim fiyat
    (nominal_deger - LAG(nominal_deger) OVER w)
        * (toplam_tutar_tl / NULLIF(nominal_deger, 0))
        AS miktar_etkisi_tl
FROM fund_holdings
WINDOW w AS (PARTITION BY fon_kodu, security_id ORDER BY yil, ay);

-- 6) Hisse bazında toplam fon ilgisi — "Summed" sayfası karşılığı, yine VIEW.
--    Screener'a "Fon Net Alımı" kolonu eklerken net_gercek_alim_satim_tl
--    kullanılmalı, net_fon_akisi_tl DEĞİL — ikincisi fiyat hareketini de
--    içerdiği için "fiyatı yükselen ama kimse almayan" bir hisseyi yanlışlıkla
--    güçlü alım sinyali gibi gösterebilir.
CREATE VIEW stock_fund_flow_monthly AS
SELECT
    security_id, yil, ay,
    COUNT(DISTINCT fon_kodu) AS fon_sayisi,
    SUM(toplam_tutar_tl)     AS toplam_fon_tutari,
    SUM(toplam_tutar_tl) - LAG(SUM(toplam_tutar_tl)) OVER (PARTITION BY security_id ORDER BY yil, ay)
                              AS net_fon_akisi_tl,          -- HAM değişim (fiyat + miktar karışık)
    SUM(miktar_etkisi_tl)     AS net_gercek_alim_satim_tl   -- SADECE adet değişiminden gelen kısım
FROM fund_holdings_change
GROUP BY security_id, yil, ay;

-- 7) Model portföy / analist tavsiyeleri — "Model Portföy" sayfası karşılığı
CREATE TABLE model_portfolio_recommendations (
    kurum           VARCHAR(50) NOT NULL,
    yil             SMALLINT NOT NULL,
    ay              SMALLINT NOT NULL CHECK (ay BETWEEN 1 AND 12),
    ticker          VARCHAR(24) NOT NULL,                     -- bu sayfada ISIN hiç yok, dogal anahtar ticker
    security_id     BIGINT REFERENCES securities(id),         -- eslesirse doldurulur (join kolayligi icin)
    tavsiye         VARCHAR(20),
    guncel_fiyat    NUMERIC(18,4),
    hedef_fiyat     NUMERIC(18,4),
    potansiyel_pct  NUMERIC(9,4),
    PRIMARY KEY (kurum, yil, ay, ticker)
);

-- 8) ETL / import denetim kaydı — YENİ, Excel'de karşılığı yok.
--    Önceki kod incelemesinde bulunan "sessiz hata yutma" probleminin
--    fon veri hattında TEKRARLANMAMASI için: her import/parse denemesi
--    (başarılı ya da başarısız) buraya loglanır. Reconciliation farkı
--    (parser'ın hesapladığı toplam vs PDF'in yazdığı GRUP TOPLAMI) da
--    burada tutulur — pilotta NHY'de yakaladığımız türden sorunlar
--    artık production'da sessizce geçmez, buradan görünür olur.
CREATE TABLE etl_runs (
    id              BIGSERIAL PRIMARY KEY,
    kaynak          VARCHAR(30) NOT NULL,     -- 'KAP_PDF' | 'TEFAS_API' | 'EXCEL_MANUEL'
    fon_kodu        VARCHAR(10),
    donem_yil       SMALLINT,
    donem_ay        SMALLINT,
    durum           VARCHAR(20) NOT NULL,     -- 'OK' | 'HATA' | 'UYUMSUZLUK'
    detay           TEXT,                     -- hata mesajı / reconciliation farkı / unmatched_prefix_tokens
    calisma_zamani  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_etl_runs_durum ON etl_runs(durum, calisma_zamani);

-- 9) Teknik veri cache iskeleti — Faz 3'te detaylandırılacak, şimdilik yer tutucu.
--    Amaç: calculate_all_indicators'ın her rerun'da yeniden hesaplanması yerine
--    fiyat verisini burada tutup indikatörleri de ayrı bir tabloda cache'lemek.
CREATE TABLE stock_price_daily (
    security_id BIGINT NOT NULL REFERENCES securities(id),
    tarih       DATE NOT NULL,
    acilis      NUMERIC(18,4),
    yuksek      NUMERIC(18,4),
    dusuk       NUMERIC(18,4),
    kapanis     NUMERIC(18,4),
    hacim       NUMERIC(20,2),
    PRIMARY KEY (security_id, tarih)
);

-- 10) Sirket yatirimci raporu ozetleri (LLM ile) — sirket_raporlari.py
--     Bu raporlar CEYREKLIK yayinlanir (faaliyet raporu / yatirimci sunumu) -
--     bu yuzden dogal anahtar kaynak_url degil (ticker, yil, donem) uclusu:
--     ayni ceyrege ait duzeltilmis/farkli bir link gelirse AYNI donem
--     satirinin uzerine yazilir (yeni bir donem satiri OLUSTURULMAZ).
--     kaynak_url ayrica UNIQUE tutuluyor - amac farkli: ayni link ikinci kez
--     yapistirilirsa Claude'a tekrar odeme yapmadan cache'den donmek icin.
--
--     satis/favok/net_kar hedefi + yonu (YUKARI/ASAGI/AYNI/ILK_KEZ/BELIRSIZ):
--     her ceyrekte acikca guncellenen yil sonu hedeflerinin bir onceki
--     ceyreğe gore revize yonunu izlemek icin - kullanicinin asil istegi bu.
CREATE TABLE company_report_summaries (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              VARCHAR(24),
    sirket_adi          TEXT,
    kaynak_url          TEXT NOT NULL UNIQUE,
    rapor_basligi       TEXT,
    yil                 SMALLINT,
    donem               VARCHAR(4),           -- 'Q1'|'Q2'|'Q3'|'Q4'|'FY'
    satis_hedefi        TEXT,
    satis_yonu          VARCHAR(12),          -- YUKARI|ASAGI|AYNI|ILK_KEZ|BELIRSIZ
    favok_hedefi        TEXT,
    favok_yonu          VARCHAR(12),
    net_kar_hedefi      TEXT,
    net_kar_yonu        VARCHAR(12),
    ozet                TEXT NOT NULL,
    ham_metin_uzunluk   INTEGER,
    olusturma_zamani    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_company_report_period
    ON company_report_summaries(ticker, yil, donem)
    WHERE ticker IS NOT NULL AND yil IS NOT NULL AND donem IS NOT NULL;
CREATE INDEX idx_company_report_ticker ON company_report_summaries(ticker, olusturma_zamani DESC);
