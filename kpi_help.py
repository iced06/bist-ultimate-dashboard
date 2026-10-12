"""Portföy / Stock Analyzer ekranlarındaki göstergelerin (metrik kutuları ve tablo sütunları) üzerine gelince
çıkan açıklamalar: ne ölçtüğü, değerin nasıl okunacağı. `metric_help(label)` ve `df(...)` ile kullanılır."""
from __future__ import annotations

import streamlit as st

HELP: dict[str, str] = {
    # ───────── portföy sağlık ve risk göstergeleri ─────────
    "Sağlık skoru": (
        "Portföyün yapısal kalitesi (0–100). Çeşitlendirme %30, yoğunlaşma %20, risk %25, kalite %25 ağırlıkla "
        "birleşir. ≥75 Sağlam, 60–75 İyi, 45–60 Orta, <45 Zayıf. Dikkat: bu, hisselerin yükseleceği anlamına gelmez; "
        "portföyün dengeli, sakin ve kaliteli kurulduğunu ölçer."),
    "Yıllık volatilite": (
        "Portföy günlük getirilerinin standart sapması, yıllığa çevrilmiş. %20 → bir yıl içinde tipik dalgalanma "
        "yaklaşık ±%20. Düşük = daha sakin. Altındaki XU100 değeri aynı dönemde endeksin volatilitesi; portföyünki "
        "onun altındaysa portföy endeksten daha az dalgalanıyor."),
    "Beta (XU100)": (
        "Endeks (XU100) %1 hareket ettiğinde portföyün ortalama kaç % hareket ettiği. 1 = endeks gibi; <1 savunmacı "
        "(endeksten az oynar); >1 agresif. Örn. 0.86 → endeks %10 düşerse portföy ortalama ≈ %8.6 düşme eğiliminde."),
    "Sharpe": (
        "(Getiri − risksiz faiz) ÷ volatilite: alınan her birim risk başına fazla getiri. >1 iyi, 0 civarı risksiz "
        "faizle aynı, negatif = risksiz faizin altında. TL'de risksiz faiz çok yüksek (~%40) olduğundan çoğu portföyde "
        "negatif çıkması normaldir; sorun portföyde değil faiz seviyesindedir. Sonuç faiz girdisine çok duyarlıdır."),
    "Max drawdown": (
        "Tepeden dibe görülen en büyük kayıp. %12.5 → portföyün zirvesinden en kötü anda %12.5 aşağıdaydı. Düşük = "
        "kötü dönemlerde daha dayanıklı. Altındaki XU100 değeri aynı dönemde endeksin en büyük düşüşü."),
    "Efektif hisse": (
        "1 ÷ Σ(ağırlık²): portföy kaç eşit ağırlıklı hisse kadar çeşitlenmiş. 22 / 23 → neredeyse eşit dağılmış; "
        "3 / 15 gibi küçük bir sayı, birkaç hissede yoğunlaşma demektir."),
    "Çeşitlendirme skoru": (
        "Hisseler birbirini ne kadar dengeliyor? Ortalama ikili korelasyon (0.25 → 100, 0.85 → 0) ile efektif "
        "hisse sayısı / hisse sayısı oranının ortalaması. Yüksek = hisseler farklı hareket ediyor (iyi)."),
    "Yoğunlaşma skoru": (
        "Tek hisseye / tek sektöre bağımlılık. En büyük hisse ağırlığı (%15 → 100, %45 → 0) ile en büyük sektör payının "
        "(%30 → 100, %80 → 0) ortalaması. Yüksek = yoğunlaşma düşük (iyi)."),
    "Risk skoru": (
        "Portföyün sakinliği. Volatilite (%20 → 100, %55 → 0) ile max drawdown'un (%15 → 100, %45 → 0) ortalaması. "
        "Yüksek = daha az dalgalı ve daha sığ düşüşler."),
    "Kalite skoru": (
        "Ağırlıklı ortalama Overall puanı (1 → 0, 5 → 100): sepetteki şirketlerin rapor/marj/büyüme kalitesi. "
        "Yüksek = ağırlık güçlü raporlu şirketlerde."),
    # ───────── kosinüs bölümü ─────────
    "Kosinüs (3B)": (
        "İki hissenin 3B harita vektörleri arasındaki açının kosinüsü. +1 = aynı yön (benzer hareket), 0 = ilişkisiz, "
        "−1 = zıt yön. Yalnızca YÖNÜ ölçer; vektörler kısaysa (3 faktör hisseyi tam açıklamıyorsa) gerçek korelasyondan "
        "YÜKSEK görünür."),
    "Açı": (
        "İki vektör arasındaki açı. 0° = tamamen benzer hareket, 90° = ilişkisiz, 180° = zıt. Küçük açı → "
        "çeşitlendirme faydası az (riskler aynı yönde toplanır); büyük açı → birbirini dengeler."),
    "x·y (≈ korelasyon)": (
        "İki vektörün nokta çarpımı. Boyları da hesaba kattığı için korelasyona kosinüsten daha yakın bir "
        "yaklaşıklıktır (harita yapısı: xᵢ·xⱼ ≈ ρᵢⱼ)."),
    "Gerçek korelasyon": (
        "İki hissenin günlük getirilerinin tüm geçmişten hesaplanan korelasyonu (3B'ye indirgenmeden). +1 = hep aynı "
        "yönde, 0 = ilişkisiz, negatif = zıt hareket (hedge etkisi). Portföyde düşük/negatif değerler riski azaltır."),
    # ───────── hedef fiyat / ucuzluk ─────────
    "Ağırlıklı potansiyel": (
        "Hedefi hesaplanabilen hisselerin potansiyelinin (hedef fiyat ÷ fiyat − 1) portföy ağırlığıyla ortalaması. "
        "+%20 → hedef çarpanlara dönüldüğünde portföyün yaklaşık %20 değer kazanacağı varsayımı. Zaman ufku belirsiz; "
        "tahmin değil değerleme yönteminin sonucudur."),
    "En ucuz": "Güvenilir hedefler arasında potansiyeli en yüksek hisse (kendi geçmişine, sektörüne ve puanlarına göre en ucuz).",
    "En pahalı": "Güvenilir hedefler arasında potansiyeli en düşük (en negatif) hisse: hedef çarpana göre en pahalı.",
    "Ucuz/pahalı": "Potansiyeli ≥ +%10 olan hisse sayısı / ≤ −%10 olan hisse sayısı.",
    "Hedefi hesaplanan": "Değerlemesi (hedef fiyatı) hesaplanabilen hisse sayısı / gösterilen toplam hisse. Finansalı olmayan ya da tahmini uç olanlar dışarıda kalır.",
    # ───────── model portföy / faktör metrikleri ─────────
    "Beklenen getiri": (
        "Model portföyün ağırlıklı beklenen yıllık getirisi (seçili kaynak + hedef fiyat katkısı). Bir tahmin değil, "
        "girdi varsayımlarının sonucudur. Altındaki değer, evrendeki tüm hisselerin eşit ağırlıklı beklentisi."),
    "Risk σ": "Portföyün yıllık standart sapması (Ledoit-Wolf kovaryansıyla). %23 → tipik yıllık dalgalanma ±%23.",
    "Getiri/Risk": (
        "(Beklenen getiri − risksiz faiz) ÷ risk σ. Pozitif = risksiz faizin üstünde kazanç bekleniyor; negatif = "
        "beklenen getiri risksiz faizin altında (TL'de faiz çok yüksek olduğu için sık görülür)."),
    "Ort. ikili korelasyon": (
        "Portföydeki tüm hisse çiftlerinin korelasyon ortalaması. Düşük (≈0.1–0.3) = iyi çeşitlenmiş; yüksek (>0.6) = "
        "hisseler benzer hareket ediyor, çeşitlendirme zayıf."),
    "Yön uyumu": (
        "|Σ wᵢvᵢ| ÷ Σ wᵢ|vᵢ|: hisse vektörlerinin ne kadar aynı yöne baktığı. 1 = hepsi aynı yönde (portföy tek bir "
        "faktör karakteri taşıyor); 0'a yakın = vektörler birbirini götürüyor (çeşitlenmiş / hedge)."),
    "Momentum maruziyeti": (
        "Portföyün ağırlıklı ortalama momentum z-skoru (σ). +0.5σ → hisseler evrenin ortalamasına göre yarım standart "
        "sapma daha güçlü yükselmiş (momentum eğilimi); negatif → geride kalanlara ağırlık (kontrarian). Altındaki açı, "
        "maruziyet vektörünün momentum eksenine açısı: küçük açı = portföy ağırlıklı olarak bu faktörle tanımlanıyor; "
        "90° = bu faktörden bağımsız."),
    "Risk maruziyeti": (
        "Portföyün ağırlıklı ortalama volatilite z-skoru (σ). Pozitif → evrenin ortalamasından daha oynak hisselere "
        "yaslanıyorsun; negatif → daha sakin hisseler. Altındaki açı 90°'ye yakınsa portföy volatilite faktöründen "
        "bağımsız, 0°'ye yakınsa tamamen risk yönünde."),
    "FD/FAVÖK maruziyeti": (
        "Portföyün ağırlıklı ortalama ileri FD/FAVÖK z-skoru (σ). NEGATİF değer = ortalamaya göre UCUZ hisselere "
        "eğilim, pozitif = pahalı hisselere eğilim (düşük FD/FAVÖK ucuzluktur). Altındaki açı bu ekseni portföyün "
        "karakterinde ne kadar belirleyici olduğunu gösterir."),
    # ───────── tablo sütunları: portföy ─────────
    "Hisse": "Hisse kodu; yanındaki işaret Görünüm puanıdır: * = 4 üzeri, + = 3–4 arası, − = 3 altı.",
    "Sektör": "Şirketin Company Reports'taki sektör ataması.",
    "Ağırlık %": "Portföyün yüzde kaçı bu hissede. Toplam 100.",
    "Risk katkısı %": (
        "Portföy riskinin (varyansının) yüzde kaçı bu hisseden geliyor. Ağırlığından çok yüksekse hisse portföyü "
        "olduğundan fazla oynatıyor (korelasyonu/oynaklığı yüksek); düşükse riski dengeliyor."),
    "Beklenen getiri % (Markowitz)": (
        "Tarihsel yıllık ortalama getirinin kesit ortalamasına %50 çekilmiş hali (Markowitz girdisi). Tarihsel "
        "ortalama gürültülüdür; tahmin değil, geçmişe dayalı bir referanstır."),
    "Risk σ % (Markowitz)": "Ledoit-Wolf shrinkage'lı kovaryanstan hissenin yıllık standart sapması (%). Yüksek = daha oynak.",
    "Min-varyans ağırlığı %": "Yalnızca riski en aza indiren (getiriyi hiç hesaba katmayan) portföyde bu hissenin ağırlığı.",
    "Maks-Sharpe ağırlığı %": (
        "Getiri/risk oranını en yüksek yapan portföyde bu hissenin ağırlığı. Birkaç hissede yoğunlaşabilir; hiçbir hisse "
        "risksiz faizi aşmıyorsa Min varyansa düşer."),
    "Beta": "Hisse endeksle ne kadar birlikte hareket ediyor: 1 = endeks gibi, <1 savunmacı, >1 agresif.",
    "Yıllık getiri % (bileşik)": "Pencerede hissenin bileşik (CAGR) yıllık getirisi. Geçmiştir, gelecek değildir.",
    "Max DD %": "Hissenin pencere içindeki en büyük tepeden-dibe kaybı (%).",
    "Overall": "Company Reports toplam puanı (1–5): marj, büyüme ve görünüm puanlarının bileşimi. Yüksek = güçlü rapor.",
    "Görünüm": "Company Reports'taki Görünüm puanı (1–5): şirketin ileriye dönük beklenti/ görünüm değerlendirmesi. 3 nötr.",
    "Görünüm işareti": "* = Görünüm 4 üzeri, + = 3–4 arası, − = 3 altı.",
    "Yüksek getiri · düşük risk": "✅ = riski gösterilen hisselerin medyanının altında VE beklenen getirisi medyanın üstünde olanlar (göreli ayrım).",
    # ───────── Markowitz özeti ─────────
    "Portföy": "Karşılaştırılan portföy türü (mevcut, minimum varyans, maksimum Sharpe, eşit ağırlık).",
    "Beklenen getiri %": "Portföyün (ya da hissenin) yıllık beklenen getirisi (%): seçili kaynağa göre; tahmin değil varsayım sonucudur.",
    "Risk σ %": "Yıllık standart sapma (%): getirinin beklenen dalgalanma genişliği. Düşük = sakin.",
    "Sharpe": "(Beklenen getiri − risksiz faiz) ÷ risk. Yüksek iyi; negatif = risksiz faizin altı.",
    # ───────── hedef fiyat tablosu ─────────
    "Öncelik": "Ucuzluğa göre sıra (1 = en yüksek potansiyel). Güveni 'Düşük' olan hedefler güvenilir olanların ardına dizilir.",
    "Fiyat ₺": "Son kapanış fiyatı.",
    "Hedef fiyat ₺": (
        "Hissenin çarpanlarının (kendi geçmiş + sektör medyanı, Overall/Görünüm ile ayarlı) ortalamaya döneceği "
        "varsayımıyla bulunan değer. Zaman ufku belirsiz; fiyatın 0.5x–2x'i ile sınırlı."),
    "Potansiyel %": "Hedef fiyat ÷ fiyat − 1. + ucuz (hedefin altında işlem görüyor), − pahalı.",
    "Ucuzluk": "Potansiyele göre etiket: ≥+%30 Çok ucuz, +%10 Ucuz, ±%10 Makul, −%10 Pahalı, ≤−%30 Çok pahalı.",
    "Güven": (
        "Hedefin güvenilirliği: Yüksek = iki yöntem (F/K ve FD/FAVÖK) ve hem geçmiş hem sektör referansı var; Orta = biri "
        "eksik; Düşük = tek zayıf referans / uç değer sınırına çarpmış / holding."),
    "Kalite çarpanı": (
        "Hedef çarpana uygulanan Overall/Görünüm düzeltmesi. 1.00 = etkisiz; 1.15 → puanları iyi olduğu için hedef çarpan "
        "%15 yüksek tutuldu; 0.85 → puanları zayıf olduğu için %15 düşük."),
    "Not": "Hesaplamayı etkileyen uyarı (örn. mekanik kâr tahmini uç olduğu için bir çarpan hedefe katılmadı).",
    # ───────── çarpan karşılaştırma tabloları ─────────
    "Güncel (trailing)": "Son 12 ayın gerçekleşen kârına/FAVÖK'üne göre bugünkü çarpan (F/K veya FD/FAVÖK). Düşük = ucuz.",
    "İleri F/K": "Piyasa değeri ÷ tahmini önümüzdeki 4 çeyrek net kâr. Düşük = ucuz. Tahmin uygulamanın mekanik tahminidir.",
    "İleri FD/FAVÖK": "Firma değeri ÷ tahmini önümüzdeki 4 çeyrek FAVÖK. Düşük = ucuz; borcu hesaba katar.",
    "Geçmiş medyan": "Hissenin kendi geçmiş çeyreklerinde (aynı tahmin yöntemiyle yeniden kurulan) çarpanlarının medyanı.",
    "Geçmiş n": "Geçmiş medyan için kullanılan gözlem (çeyrek) sayısı. Az ise medyan güvenilmez.",
    "Geçmişe göre %": "Bugünkü çarpan ÷ kendi geçmiş medyanı − 1. Negatif = hisse kendi geçmişine göre ucuz.",
    "Geçmişte bugünden düşük %": "Geçmiş gözlemlerin yüzde kaçında çarpan bugünkünden düşüktü. Düşükse bugün geçmişin en ucuz bölgesinde.",
    "Sektör medyan": "Aynı sektördeki hisselerin güncel çarpan medyanı (en az 3 hisse yoksa tüm evren).",
    "Sektör n": "Sektör medyanı için kullanılan hisse sayısı.",
    "Sektöre göre %": "Bugünkü çarpan ÷ sektör medyanı − 1. Negatif = sektörüne göre ucuz.",
    "Hedef çarpan": "Geçmiş ve sektör medyanının ağırlıklı ortalaması × kalite çarpanı: hissenin 'olması gereken' çarpanı.",
    # ───────── beklenen getiri yöntemleri ─────────
    "Markowitz (tarihsel, shrunk) %": "Tarihsel yıllık ortalama getirinin kesit ortalamasına %50 çekilmiş hali. Geçen yılın kazananlarını öne çıkarma eğilimi vardır.",
    "PCA faktör modeli %": "Yalnızca ortak faktörlerle (piyasa, sektör eğilimleri) açıklanan beklenen getiri; hissenin kendine özgü şans eseri ortalaması atılır.",
    "Karakteristik regresyon %": "Ucuzluk (sektöre/geçmişe göre), tahmini kâr büyümesi ve momentumun sonraki getiriyi ne kadar açıkladığını öğrenen modelin tahmini + puan primi.",
    "Ortalama %": "Üç yöntemin ortalaması: tek bir yöntemin gürültüsünü azaltır.",
    "Yöntem aralığı (pp)": "Üç yöntemin en yüksek ve en düşük tahmini arasındaki fark (puan). Büyükse tahmin belirsiz.",
    "Katsayı γ (ufuk getirisi / 1σ)": "Özelliği 1 standart sapma yüksek olan hissenin, sonraki ufukta ortalamanın ne kadar üstünde (+) / altında (−) getiri sağladığı.",
    "t-değeri": "Katsayının istatistiksel anlamlılığı: |t| ≥ 2 anlamlı sayılır; altı rastlantı olabilir.",
    "Özellik": "Regresyonun kullandığı açıklayıcı değişken.",
    "Özellik katkısı %": "Özelliklerin (ucuzluk, büyüme, momentum) beklenen getiriye yıllık katkısı (taban dışı).",
    "Puan primi %": "Overall/Görünüm puanlarının ayarlanabilir sabit primle eklenen katkısı.",
    "F/K ucuzluk – sektör (z)": "İleri F/K'nın sektör medyanına göre ucuzluğu (z-skoru). + = sektöründen ucuz.",
    "FD/FAVÖK ucuzluk – sektör (z)": "İleri FD/FAVÖK'ün sektör medyanına göre ucuzluğu (z-skoru). + = ucuz.",
    "F/K ucuzluk – kendi geçmişi (z)": "İleri F/K'nın kendi geçmiş medyanına göre ucuzluğu (z-skoru). + = geçmişine göre ucuz.",
    "Kâr büyümesi (z)": "Tahmini kâr / son 12 ay kârı (log) z-skoru. + = kârının daha hızlı büyümesi bekleniyor.",
    "Momentum (z)": "Momentum (12-1 ay) z-skoru: + = evren ortalamasına göre güçlü yükselmiş.",
    "Baz getiri % (kaynak)": "Seçili kaynağın (Markowitz tarihsel ya da PCA) bu hisse için yıllık beklenen getirisi; hedef fiyat katkısı eklenmeden önceki değer.",
    "Hedef fiyat katkısı %": "Hedef fiyat potansiyelinin (−%50…+%100 ile sınırlı) güven ve 'Hedef fiyat payı' ile çarpılmış yıllık katkısı. 0 = hedef fiyat etkisiz.",
    "Faktör": "PCA faktörü (F1 en güçlü ortak hareket).",
    "Açıkladığı varyans %": "Faktörün evren getiri varyansının yüzde kaçını açıkladığı.",
    "Faktör primi λ (yıllık %)": "Faktör getirisinin yıllık ortalaması: o faktöre maruz kalmanın yıllık getirisi (işaret keyfi, yüklerle birlikte okunur).",
    "PCA R² (faktörlerle açıklanan)": "Hissenin getirisinin ortak faktörlerle açıklanan oranı (0–1). Düşükse PCA tahmini o hisse için zayıf.",
    # ───────── zaman bölümü ─────────
    "Yıllık devir %": "Yeniden dengelemelerde yıllık ortalama el değiştiren portföy oranı (tek yön). Yüksek = çok işlem, yüksek maliyet.",
    "Toplam maliyet %": "Test boyunca ödenen işlem maliyetinin başlangıç sermayesine oranı.",
    "Bitiş (100 →)": "Başlangıçtaki 100 TL'nin test sonundaki değeri (maliyet düşülmüş).",
    "Sortino": "Sharpe gibi, ama yalnızca aşağı yönlü dalgalanmayı risk sayar. Yüksek iyi.",
    "Volatilite %": "Yıllık standart sapma (%).",
    "Büyüme": "Company Reports büyüme puanı (1–5).",
    "Marj": "Company Reports marj toplam puanı (1–5).",
    # ───────── faktör uzayı tablosu ─────────
    "Momentum z": (
        "Hissenin momentumunun (analiz penceresi getirisi, son 1 ay hariç) evren ortalamasından kaç standart sapma "
        "uzakta olduğu. 0 = ortalama, +1 = ortalamanın 1σ üstü (güçlü yükselmiş), −1 = geride. ±3'e kırpılır."),
    "Risk z": "Hissenin volatilitesinin evren ortalamasından kaç σ uzakta olduğu. +1 = ortalamadan 1σ daha oynak; −1 = daha sakin.",
    "FD/FAVÖK z": "log(ileri FD/FAVÖK)'ün evren ortalamasından kaç σ uzakta olduğu. NEGATİF = ucuz (düşük çarpan), pozitif = pahalı.",
    "FD/FAVÖK ~": "'doldurulmuş' = hissenin FD/FAVÖK'ü yok/anlamsız olduğu için sektör ya da evren medyanı kullanıldı (bu eksen nötr sayılır).",
    "Öz vektör": (
        "PCA öz vektörü. 'Portföy u1' = portföyün faktör uzayında en çok yayıldığı yön; 'Evren u1' = rapor evreninin. "
        "u1 en güçlü, u2 ikinci, u3 üçüncü yön; üçü birbirine diktir."),
    "λ": (
        "Özdeğer: o yönde ne kadar yayılma/yoğunlaşma olduğu. Büyük λ → hisseler (ya da portföy) o eksen boyunca "
        "toplanmış. Üç λ'nın toplamı toplam yayılımdır."),
    "Açıkladığı %": "λ ÷ Σλ: bu öz vektörün toplam faktör yayılımındaki payı. u1 = %51 → yayılımın yarısı tek yönde (baskın karakter).",
    "Momentum": "Öz vektörün momentum bileşeni (−1…+1). Büyük |değer| = bu yönü momentum belirliyor; işaret yönü gösterir.",
    "Risk": "Öz vektörün risk (volatilite) bileşeni (−1…+1). Büyük |değer| = bu yön riskle tanımlı.",
    "FD/FAVÖK": "Öz vektörün FD/FAVÖK bileşeni (−1…+1). Büyük |değer| = bu yön değerleme (ucuz/pahalı) ekseniyle tanımlı.",
    "Baskın eksen": "Öz vektörde mutlak değeri en büyük bileşen: bu yönün hangi faktöre yaslandığı (işaret = yönü).",
    "Hisse A": "Çiftin birinci hissesi.",
    "Hisse B": "Çiftin ikinci hissesi.",
    "Açı °": "İki hissenin 3B vektörleri arasındaki açı (derece). Küçük = benzer hareket.",
    "Kosinüs (3B) ": "",
    "x·y": "Vektörlerin nokta çarpımı (≈ korelasyon).",
    "Seç": "Hisseyi sepete ekle/çıkar.",
}
HELP.pop("Kosinüs (3B) ", None)


def metric_help(label: str) -> str | None:
    return HELP.get(label)


def with_help(cfg, cols) -> dict:
    """column_config sözlüğüne, HELP'te karşılığı olan sütunlar için açıklama (hover) ekler."""
    cfg = dict(cfg or {})
    for c in cols:
        text = HELP.get(str(c))
        if not text:
            continue
        cur = cfg.get(c)
        if isinstance(cur, dict):
            cfg[c] = {**cur, "help": text}
        elif cur is None:
            cfg[c] = st.column_config.Column(help=text)
    return cfg


def df(data, **kwargs):
    """st.dataframe: sütun başlıklarına açıklama (hover) ekler."""
    try:
        cols = list(data.columns)
    except AttributeError:
        cols = []
    return st.dataframe(data, column_config=with_help(kwargs.pop("column_config", None), cols), **kwargs)
