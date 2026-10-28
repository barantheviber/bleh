# TraderBot

Windows için kullanıcı arayüzlü, otomatik al-sat botu. Canlı grafikler, açılır
TradingView penceresi, geçmiş veriyle test edilip seçilmiş bir strateji ve
[trader-skill](https://github.com/Jakeschincariol/trader-skill) paketinin
algoritmaları (13F kopyalama, bütçe, risk, dengeleme, haber, Kongre bildirimleri)
tek uygulamada.

> **Yatırım tavsiyesi değildir.** Bot kendi kendine alım satım yapar; geçmiş test
> sonuçları geleceği garanti etmez ve para kaybedebilirsiniz. Varsayılan hesap
> **simülasyondur** (gerçek para yok).

## İndirme ve kurulum

1. GitHub'da bu deponun **Actions** sekmesini açın, `build-windows` iş akışının en
   son başarılı (yeşil) çalıştırmasına tıklayın.
2. Sayfanın altındaki **Artifacts** bölümünden `TraderBot-Windows-1.0.0` dosyasını
   indirin ve zip'i açın. İçinde iki seçenek var:
   - `TraderBot-Setup-1.0.0.exe`: kurulum programı (yönetici izni istemez).
   - `TraderBot-portable-1.0.0.zip`: kurulumsuz sürüm. Açın ve `TraderBot\TraderBot.exe`'yi çalıştırın.
3. Windows "Bilgisayarınız korundu" (SmartScreen) derse: **Ek bilgi → Yine de çalıştır**.
   Uygulama imzasız olduğu için bu uyarı çıkar.

Her derlemede exe, CI'da kendi kendini test eder (`--selftest`). Kurulum programı da
sessizce kurulup kurulu kopya tekrar test edilir.

## Neler yapar

| Sekme | Ne işe yarar |
|---|---|
| **Grafik** | Canlı mum grafiği (1dk–haftalık): hacim, EMA 20/50, SMA 200, Bollinger, RSI, MACD, artı imleci ve OHLC, botun alım-satım işaretleri, ortalama maliyet çizgisi. Solda izleme listesi. **Platform penceresi** düğmesi sembolü TradingView, Yahoo Finance veya Finviz'de açılır pencerede gösterir. BIST (`THYAO.IS`) ve kripto (`BTC-USD`) grafikleri de çalışır. |
| **Bot** | Başlat/Durdur, Şimdi çalıştır, Kuru çalıştırma (emir göndermeden plan), Acil durdur, Tümünü kapat. Hesap, pozisyonlar, hedefler, emir geçmişi, varlık eğrisi ve karar günlüğü. |
| **Backtest** | 8 stratejiyi istediğiniz parametre ve tarihle Yahoo verisi üzerinde S&P 500 (SPY) al-tut ile karşılaştırır. **Araştırma raporu** düğmesi stratejinin nasıl seçildiğini gösterir. |
| **13F Kopya** | trader-copycat: bir yatırımcının (Berkshire, Pershing Square, Scion…) son 13F portföyü, çeyrek değişimi, ilk N pozisyonun kopya ağırlıkları. Bu ağırlıklar bota hedef olarak verilebilir. |
| **Haberler** | trader-news: Yahoo başlıkları ve SEC 8-K dosyalamaları, önemli maddeler işaretli. |
| **Kongre** | trader-pelosi: ABD Meclis üyelerinin STOCK Act işlem bildirimleri (PTR). |
| **Ayarlar** | Aracı kurum (simülasyon / Alpaca), tam otomatik ya da onaylı mod, karar saati, risk kuralları ve acil durdurma sınırları, SEC kimliği, Windows ile başlatma. |

### Bot nasıl karar verir

Her işlem gününde, New York saatiyle 10:00'dan sonra (Türkiye'de genelde 17:00)
bir kez:

1. Dünkü kapanışa kadarki günlük veriyle stratejinin hedef ağırlıkları hesaplanır.
2. **trader-rebalance** `plan()`: hedeften 5 puandan fazla sapan pozisyonlar için
   emirler çıkar. Önce satışlar yapılır, alımlar dolar tutarıyla verilir.
3. **trader-risk** `check()`: her emir kurallara göre geçer ya da engellenir.
   Kurallar: nakit tamponu, pozisyon üst sınırı, en büyük/en küçük emir, günlük emir
   sınırı, engelli semboller. Açığa satış, kaldıraç ve opsiyon kapalıdır.
4. Geçen emirler aracıya gönderilir. Onaylı modda her biri sizin onayınızı bekler.

Bot sürekli olarak hesabı da izler. Günün kaybı %5'i ya da zirveden düşüş %25'i
aşarsa **acil durur** ve siz devam deyinceye kadar yeni emir vermez. Bot, uygulama
açıkken çalışır. Pencereyi kapatınca tepside çalışmaya devam eder.

## Strateji nasıl seçildi

Seçim kuralları, sonuçlara bakılmadan önce yazıldı (`research/study.py`).

**Veri ve maliyet:**
- 31 ETF ve hissenin 2005-2026 günlük, temettü düzeltilmiş Yahoo verisi kullanıldı.
- Emirler ertesi günün açılışında doluyor, her işlemde 5 baz puan maliyet var.

**Denenen stratejiler (7 aile, 42 parametre seti):**
- Trend filtresi
- Altın kesişim
- RSI(2)
- Çift momentum
- Sektör rotasyonu
- Varlık rotasyonu
- Volatilite hedefli trend

**Seçim adımları:**
1. Her ailenin parametresi 2005-2015 verisinde seçildi.
2. Aile, 2016-2022 doğrulama döneminde seçildi. Şartlar: SPY'dan derin düşmemek,
   en az 10 işlem yapmak, tek bir şanslı parametreye dayanmamak.
3. 2023-bugün test dönemi seçimde hiç kullanılmadı.

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

## Lisans ve teşekkür

- `traderbot/skills/` klasöründeki betikler, Jake Schincariol'un
  [trader-skill](https://github.com/Jakeschincariol/trader-skill) paketinden
  değiştirilmeden alındı (MIT, lisansı klasörde).
- Testlerde kullanılan kayıtlı veriler de aynı paketten (`tests/fixtures/skills`).
- TradingView grafiği, TradingView'ın ücretsiz gömülebilir widget'ıdır.
