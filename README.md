# TraderBot

Windows için kullanıcı arayüzlü, otomatik al-sat botu. Tek uygulamada şunları
birleştirir:

- canlı grafikler ve açılır TradingView penceresi
- geçmiş veriyle test edilip seçilmiş bir strateji
- trading araştırmalarından çıkan araçlar: piyasa rejimi, tarayıcı, alarmlar, pozisyon
  hesaplayıcı ve backtest güvenilirlik analizleri
- [trader-skill](https://github.com/Jakeschincariol/trader-skill) paketinin algoritmaları:
  13F kopyalama, bütçe, risk, dengeleme, haber, Kongre bildirimleri

Özelliklerin hangi araştırmaya dayandığı [research/ARASTIRMA.md](research/ARASTIRMA.md)
rehberinde anlatılıyor; aynı rehber uygulamanın **Rehber** sekmesinde de var.

> **Yatırım tavsiyesi değildir.** Bot kendi kendine alım satım yapar; geçmiş test
> sonuçları geleceği garanti etmez ve para kaybedebilirsiniz. Varsayılan hesap
> **simülasyondur** (gerçek para yok).

## İndirme ve kurulum

1. GitHub'da bu deponun **Actions** sekmesini açın, `build-windows` iş akışının en
   son başarılı (yeşil) çalıştırmasına tıklayın.
2. Sayfanın altındaki **Artifacts** bölümünden `TraderBot-Windows-1.1.0` dosyasını
   indirin ve zip'i açın. İçinde iki seçenek var:
   - `TraderBot-Setup-1.1.0.exe`: kurulum programı (yönetici izni istemez). Eski sürümün
     üzerine kurulur; ayarlarınız ve simülasyon hesabınız korunur.
   - `TraderBot-portable-1.1.0.zip`: kurulumsuz sürüm. Açın ve `TraderBot\TraderBot.exe`'yi çalıştırın.
3. Windows "Bilgisayarınız korundu" (SmartScreen) derse: **Ek bilgi → Yine de çalıştır**.
   Uygulama imzasız olduğu için bu uyarı çıkar.

Her derlemede exe, CI'da kendi kendini test eder (`--selftest`). Kurulum programı da
sessizce kurulup kurulu kopya tekrar test edilir.

## Neler yapar

| Sekme | Ne işe yarar |
|---|---|
| **Grafik** | Canlı mum grafiği (1dk–haftalık): hacim, EMA 20/50, SMA 200, Bollinger, RSI, MACD, artı imleci ve OHLC, botun alım-satım işaretleri, ortalama maliyet çizgisi. Solda izleme listesi. **Platform penceresi** düğmesi sembolü TradingView, Yahoo Finance veya Finviz'de açılır pencerede gösterir. **Pozisyon hesapla** ve **Alarm kur** düğmeleri de burada. BIST (`THYAO.IS`) ve kripto (`BTC-USD`) grafikleri de çalışır. |
| **Piyasa** | Sekiz göstergeyle bugünkü piyasa rejimi: trend, 12 aylık momentum, oynaklık, VIX, VIX vade yapısı, getiri eğrisi (NY Fed modeliyle resesyon olasılığı), kredi iştahı, sektör genişliği. Her birinin 5 yıllık geçmişi, geçmişte o durumdan sonraki ayda ne olduğu, yaklaşan FOMC kararları, NYSE tatilleri ve ay dönümü pencereleri. |
| **Tarayıcı** | Sektör, varlık sınıfı, ülke ETF'leri, ABD büyük şirketleri, BIST büyükleri ya da kendi listenizi 12-1 ay momentumu ve 52 haftalık zirveye yakınlığa göre sıralar; trend, oynaklık ve RSI(2) de gösterilir. Çift tıklama grafiği açar. |
| **Bot** | Başlat/Durdur, Şimdi çalıştır, Kuru çalıştırma (emir göndermeden plan), Acil durdur, Tümünü kapat. Hesap (TL karşılığıyla), pozisyonlar, hedefler, emir geçmişi, işlem istatistikleri, varlık eğrisi ve karar günlüğü. Emirler ve acil durum Windows bildirimi olarak da gelir. |
| **Backtest** | 14 stratejiyi (al-tut ve sabit ağırlık dahil) istediğiniz parametre ve tarihle S&P 500 (SPY) al-tut ile karşılaştırır. Ölçüler, yıllık ve aylık getiriler; **Risk** (VaR, beklenen kayıp, en kötü dönemler, beta); **Güvenilirlik** (olasılıksal ve deflated Sharpe, oturumda denenen ayar sayısıyla); **Monte Carlo** (5000 yola kadar olası aralık); **İleri yürüyüş** (parametreyi her yıl yeniden seçme testi). |
| **Alarmlar** | Fiyat, günlük değişim, hareketli ortalama, RSI ve 52 haftalık zirve/dip alarmları. Her dakika kontrol edilir, koşul gerçekleşince Windows bildirimi gelir. |
| **13F Kopya** | trader-copycat: bir yatırımcının (Berkshire, Pershing Square, Scion…) son 13F portföyü, çeyrek değişimi, ilk N pozisyonun kopya ağırlıkları. Bu ağırlıklar bota hedef olarak verilebilir. |
| **Haberler** | trader-news: Yahoo başlıkları ve SEC 8-K dosyalamaları, önemli maddeler işaretli. |
| **Kongre** | trader-pelosi: ABD Meclis üyelerinin STOCK Act işlem bildirimleri (PTR). |
| **Rehber** | Özelliklerin dayandığı araştırmaların Türkçe özeti ve strateji testinin bütün sayıları. |
| **Ayarlar** | Aracı kurum (simülasyon / Alpaca), tam otomatik ya da onaylı mod, karar saati, risk kuralları ve acil durum sınırları, bildirimler, SEC kimliği, Windows ile başlatma. |

### Bot nasıl karar verir

Bot her işlem gününde bir kez, New York saatiyle 10:00'dan sonra çalışır. Bu saat
Türkiye'de 17:00'dir, ABD kış saatinde (Kasım başı - Mart ortası) 18:00 olur. Her
çalışmada:

1. Dünkü kapanışa kadarki günlük veriyle stratejinin hedef ağırlıkları hesaplanır.
2. **trader-rebalance** `plan()`: hedeften 5 puandan fazla sapan pozisyonlar için
   emirler çıkar. Önce satışlar yapılır, alımlar dolar tutarıyla verilir.
3. **trader-risk** `check()`: her emir kurallara göre geçer ya da engellenir.
   Kurallar: nakit tamponu, pozisyon üst sınırı, en büyük/en küçük emir, günlük emir
   sınırı, engelli semboller. Açığa satış, kaldıraç ve opsiyon kapalıdır.
4. Geçen emirler aracıya gönderilir. Onaylı modda her biri sizin onayınızı bekler.

Bot hesabı 30 saniyede bir değerler. Günün kaybı %5'i ya da zirveden düşüş %25'i
aşarsa **acil duruma** geçer. Siz Bot sekmesinde **Devam et** diyene kadar alım
yapmaz, yalnızca riski azaltan satışları yapar. **Acil durdur** düğmesi ise siz devam
diyene kadar her emri durdurur.

Bot, uygulama açıkken çalışır. Pencereyi kapatınca tepside çalışmaya devam eder.

## Strateji nasıl seçildi

Seçim kuralları, sonuçlara bakılmadan önce yazıldı (`research/study.py`).

**Veri ve maliyet:**
- 36 ETF, hisse ve endeksin (VIX, ABD faizleri dahil) 2005-2026 günlük, temettü
  düzeltilmiş Yahoo verisi kullanıldı.
- Emirler ertesi günün açılışında doluyor, her işlemde 5 baz puan maliyet var.

**Denenen stratejiler (12 aile, 65 parametre seti):**
- 1. tur: trend filtresi, altın kesişim, RSI(2), çift momentum, sektör rotasyonu, varlık
  rotasyonu, volatilite hedefli trend
- 2. tur, literatürden: Faber GTAA, çoklu varlık trendi (TSMOM), risk paritesi, ay dönümü
  etkisi, strateji karması

**Seçim adımları:**
1. Her ailenin parametresi 2005-2015 verisinde seçildi.
2. Aile, 2016-2022 doğrulama döneminde seçildi. Şartlar: SPY'dan derin düşmemek,
   en az 10 işlem yapmak, tek bir şanslı parametreye dayanmamak.
3. 2023-bugün test dönemi seçimde hiç kullanılmadı. 2. turda kurallar değişmedi; ilk
   yedi ailenin test dönemine 1. turda bir kez bakılmıştı.

**Kazanan: Volatilite Hedefli Trend.** SPY 200 günlük ortalamanın üstündeyken
oynaklığı yıllık %15'te tutacak oranda SPY tutar, kalan para hazine bonosu ETF'inde
(BIL) bekler.

| Test dönemi (2023-01 → 2026-10) | Yıllık getiri | Sharpe | En büyük düşüş |
|---|---|---|---|
| Volatilite Hedefli Trend | +14.1% | 0.82 | **-10.2%** |
| SPY al-tut | **+21.6%** | **1.10** | -18.8% |
| 60/40 SPY/AGG | +14.7% | 1.01 | -10.7% |

**Dürüst sonuç:** Hiçbir aktif strateji yükselen piyasada SPY'ı getiride geçemedi.
Seçilen strateji çöküşlerde zararı sınırlar: 2008'de -%2.6 (SPY -%36.8) ve 2022'de
-%10.9 (SPY -%18.2). Buna karşılık yükselen yıllarda daha az kazandırır.

**Güvenilirlik kontrolleri** (2. tur):
- Deflated Sharpe, 65 denemenin şans etkisini düzeltir. Doğrulama döneminde %69 çıktı
  (SPY %60).
- İleri yürüyüş (2010-2026): parametre her yıl önceki 5 yıla göre yeniden seçildi. Sonuç
  yıllık %7.1, Sharpe 0.58, en büyük düşüş -%21.3. SPY aynı dönemde %14.1, 0.78 ve -%33.7.
- Monte Carlo (5 yıl): ortanca yıllık getiri %7.5; %20'den derin düşüş olasılığı %23
  (SPY'da %75).
- Ay dönümü etkisi bu veride kaybolmuş: eğitim döneminde negatif Sharpe aldı.
- Strateji karması test döneminde en iyi Sharpe'ı (0.92) aldı ama seçilmedi. Kural gereği
  seçim test dönemine bakılarak yapılmaz.

Tüm tablolar [research/REPORT.md](research/REPORT.md) dosyasında. Başka bir
stratejiyi Backtest sekmesinde deneyip **Bu stratejiyi bota uygula** ile
seçebilirsiniz.

## Alpaca'ya bağlama (isteğe bağlı)

1. [alpaca.markets](https://alpaca.markets) üzerinde ücretsiz hesap açın. **Paper
   Trading** bölümünden API anahtarı (Key ID + Secret) oluşturun.
2. **Ayarlar → Aracı kurum → Alpaca** seçin, anahtarları girin, **Bağlantıyı test et**
   ve **Kaydet**.
3. Önce **kağıt (paper)** hesapla birkaç hafta izleyin. Canlı hesap için ayrıca
   `CANLI` yazarak onay vermeniz gerekir. Canlı modda pencerede kırmızı uyarı görünür.

Anahtarlar bu bilgisayarda Windows hesabınıza şifreli (DPAPI) saklanır ve
yalnızca Alpaca'ya gönderilir. Alpaca'nın Türkiye'den gerçek para hesabı kabul
edip etmediğini kendiniz kontrol edin. Simülasyon her durumda çalışır.

## Kaynaktan çalıştırma ve derleme

```bash
pip install -r requirements.txt
```
```bash
python -m traderbot
```
Testler (Linux'ta `QT_QPA_PLATFORM=offscreen` ile):
```bash
pip install -r requirements-dev.txt
```
```bash
python -m pytest -q
```
Windows exe:
```bash
pyinstaller packaging/traderbot.spec --noconfirm --clean
```
Araştırmayı yeniden üretmek için:
```bash
python -m research.study
```

## Bilinen sınırlar

- Fiyatlar Yahoo Finance'in resmi olmayan ücretsiz uç noktasından gelir ve
  gecikmeli olabilir. Emirler aracının fiyatından dolar.
- Strateji ABD hisse ve ETF'leri içindir. Vergi ve TL/USD kur etkisi hesaba katılmadı.
- NYSE tatilleri kurallardan hesaplanır. Önceden bilinemeyen kapanışları Alpaca'nın
  saati yakalar.
- FOMC tarihleri `traderbot/events.py` içinde elle tutulur. 2027 tarihleri Fed'in geçici
  takvimidir; listeyi her yıl güncellemek gerekir.
- Piyasa ve Tarayıcı sekmeleri durum tespiti yapar, alım-satım sinyali vermez. Bot yalnızca
  seçili stratejiye göre işlem yapar.

## Lisans ve teşekkür

- `traderbot/skills/` klasöründeki betikler, Jake Schincariol'un
  [trader-skill](https://github.com/Jakeschincariol/trader-skill) paketinden
  değiştirilmeden alındı (MIT, lisansı klasörde).
- Testlerde kullanılan kayıtlı veriler de aynı paketten (`tests/fixtures/skills`).
- TradingView grafiği, TradingView'ın ücretsiz gömülebilir widget'ıdır.
