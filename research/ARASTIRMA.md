# Trading araştırması: ne işe yarıyor, ne yaramıyor?

Bu rehber, TraderBot'a eklenen özelliklerin dayandığı araştırmaları özetler. Her bölümde
önce akademik bulgu, sonra bu uygulamanın kendi verisiyle yaptığı test, en sonda da
bunun uygulamada neye dönüştüğü var. Sayılar, kaynakların kendi verdiği rakamlardır ya da
`research/REPORT.md` dosyasındaki testlerden gelir (Yahoo Finance günlük verisi,
2005 – Ekim 2026, işlem başına 5 baz puan maliyet).

> **Yatırım tavsiyesi değildir.** Aşağıdaki çalışmaların çoğu geçmişi inceler; geçmişte
> işe yarayan bir kural yayımlandıktan sonra zayıflayabilir. Bunun kendisi de bir
> araştırma bulgusudur (bkz. bölüm 6).

## Kısa özet

1. **Çok işlem yapan bireysel yatırımcı çoğunlukla kaybeder.** Maliyet ve aşırı güven,
   seçim becerisinden daha belirleyicidir.
2. **Trend takibi** yüz yılı aşkın veride işe yaradı ve krizlerde koruma sağladı, ama
   uzun durgun dönemleri var.
3. **Oynaklık kümelenir.** Yüksek oynaklıkta pozisyon küçültmek düşüşleri azaltır; getiriyi
   artırıp artırmadığı tartışmalıdır.
4. **Takvim etkileri** (ay dönümü, "Mayıs'ta sat", FOMC öncesi) belgelendi ama zamanla
   zayıflıyor.
5. **Teknik analiz kuralları**, çok kural denemenin yarattığı şans etkisi düzeltilince
   çoğunlukla anlamını yitirir. Mum formasyonlarının kanıtı zayıftır.
6. **Geriye dönük testler** (backtest) sistematik olarak iyimserdir. Çok sayıda deneme,
   kısa geçmiş ve yayın sonrası zayıflama hesaba katılmalıdır.
7. **Pozisyon büyüklüğü** riski getiriden daha çok belirler. Kelly oranının tamamı fazla
   risklidir.
8. **Kesitsel momentum** ve 52 haftalık zirveye yakınlık uzun süre çalıştı, ama ani
   çöküşleri var.
9. **Makro göstergeler** (getiri eğrisi, kredi primi) resesyonu önceden haber verebilir;
   piyasayı birkaç haftalık vadede zamanlamaya yaramaz.
10. **Çeşitlendirme ve sade kurallar**, karmaşık optimizasyondan daha sağlamdır.

## 1. Bireysel yatırımcı ve işlem sıklığı

- Barber ve Odean (2000), bir aracı kurumdaki yaklaşık 66 bin hanenin 1991-1996 hesaplarını
  inceledi. Ortalama hanenin brüt getirisi piyasaya yakındı: yıllık %17,7, piyasa ise %17,1.
  Masraflardan sonra bu %15,3'e düştü. En çok işlem yapan %20'lik grubun net getirisi ise
  yalnızca %10,0 oldu. Yazarlara göre kötü sonucu hisse seçimi değil, işlem maliyeti ve
  işlem sıklığı açıklıyor.
- Chague, De-Losso ve Giovannetti (2020), Brezilya'da 2013-2015 arasında gün içi işleme
  başlayan 19.646 kişiyi izledi. Bunlardan 300 günden uzun devam eden 1.551 kişinin
  %97'si para kaybetti; yalnızca %1,1'i asgari ücretten fazla kazandı. Zamanla öğrenmeye
  dair de kanıt bulunamadı.
- Odean (1998): yatırımcılar kazandıran hisseyi erken satıp kaybettireni tutmaya eğilimlidir
  (elden çıkarma etkisi). Satılan kazananlar, tutulan kaybedenlerden sonra da iyi gitti.

**Uygulamada:** Bot günde yalnızca bir kez karar verir. Hedeften 5 puandan az sapan
pozisyona dokunmaz (dengeleme bandı). Gün içi otomatik işlem bilerek eklenmedi. Backtest
sekmesi yıllık devir oranını, Bot sekmesi de canlı hesabın kazanma oranını, kâr faktörünü
ve gerçekleşen kâr/zararı gösterir.

## 2. Trend takibi (zaman serisi momentumu)

- Moskowitz, Ooi ve Pedersen (2012), 58 vadeli işlem piyasasında 1-12 aylık getirinin
  sonraki ayda sürme eğiliminde olduğunu gösterdi. Daha uzun vadede bu kısmen tersine
  döner. Çeşitlendirilmiş bir trend portföyü özellikle aşırı piyasalarda iyi sonuç verdi.
- Hurst, Ooi ve Pedersen (2017), aynı kuralı 1880'e kadar geri götürdü: 67 piyasada,
  110 yılda tutarlı biçimde kârlıydı.
- Eleştiriler: Kim, Tse ve Wald'a göre sonuçların büyük kısmı stratejiden değil,
  pozisyonları oynaklığa göre ölçeklemekten geliyor; ölçekleme olmadan trend takibi al-tut ile
  benzer getiri veriyor. Goyal ve Jegadeesh (2017) de farkın büyük kısmını değişen net uzun
  pozisyona bağlıyor.
- Gerçek fonlarda: SG Trend endeksi 2008'de %20,9, 2022'de %27,4 kazandı (dünya hisseleri
  sırasıyla %42 ve %18 kaybederken). Ama Mayıs 2024 – Mayıs 2025 arasında %20,4 ile 2000'den
  beri ikinci büyük düşüşünü yaşadı.

**Bizim testimiz:** Literatürden üç trend ailesi denendi: Faber'in 10 aylık ortalama kuralı
(GTAA), zaman serisi momentumu (TSMOM) ve 200 günlük ortalama filtresi. TSMOM eğitim
döneminde (2005-2015) en yüksek Sharpe'lardan birini aldı (0,78), ama doğrulamada (2016-2022)
0,66'ya, testte (2023-2026) 0,49'a düştü. Bu, literatürdeki "son on yıl zayıf" bulgusuyla
uyumlu.

**Uygulamada:** Backtest'te yeni stratejiler: Çoklu Varlık Trendi (TSMOM), Faber GTAA,
Strateji Karması. Piyasa sekmesinde trend ve 12 aylık momentum göstergeleri.

## 3. Oynaklık hedefleme

- Moreira ve Muir (2017): bir portföyü beklenen oynaklığıyla ters orantılı tutmak, örneklem
  içinde Sharpe oranını artırdı.
- Cederburg ve diğerleri (2020), 103 hisse stratejisinde bunu gerçek zamanlı uygulanabilir
  biçimde yeniden test etti. Örneklem dışı sürümler çoğunlukla orijinal portföylerden daha
  düşük Sharpe verdi. Barroso ve Detzel, işlem maliyetlerinin kazancı tamamen sildiğini
  gösterdi. DeMiguel ve diğerlerinin (2024) çok faktörlü koşullu sürümü ise maliyetlerden
  sonra da örneklem dışında işe yaradı.
- Momentum için: Barroso ve Santa-Clara (2015), momentumun oynaklığının kendi geçmişinden
  tahmin edilebildiğini, ölçeklemenin çöküşleri büyük ölçüde önleyip Sharpe'ı neredeyse ikiye
  katladığını buldu. Daniel ve Moskowitz (2016): momentum çöküşleri, düşüşten sonra oynaklık
  yüksekken, toparlanma anlarında gelir.

**Bizim testimiz:** Botun stratejisi (SPY, 200 günlük ortalamanın üstündeyken yıllık %15
oynaklık hedefiyle; kalan para BIL'de) iki turda da kuralları geçen kazanan oldu. Yükselen
piyasada SPY'dan az kazandırdı, düşüşleri ise belirgin biçimde azalttı:

| | Test dönemi yıllık getiri | En büyük düşüş | 5 yıllık Monte Carlo'da %20'den derin düşüş olasılığı |
|---|---|---|---|
| Volatilite Hedefli Trend | +%14,1 | -%10,2 | %23 |
| SPY al-tut | +%21,6 | -%18,8 | %75 |

**Uygulamada:** Botun kendi kuralı. Pozisyon hesaplayıcının "oynaklık hedefi" bölümü, bu
kuralı herhangi bir sembole uygular.

## 4. Takvim etkileri

- **Ay dönümü:** McConnell ve Xu (2008), 1926-2005 arasında ABD hisse getirisinin ayın son
  ve sonraki ayın ilk üç işlem gününde toplandığını buldu (bu dört günün günlük ortalaması
  %0,15). Etki 38 ülkenin 34'ünde de vardı. 2025'te "The disappearing turn-of-month effect"
  (kaybolan ay dönümü etkisi) başlıklı bir çalışma yayımlandı.
- **"Mayıs'ta sat, git":** Bouman ve Jacobsen (2002), kasım-nisan döneminin mayıs-ekimden
  daha iyi geçtiğini 37 piyasanın 36'sında gösterdi. 1998-2012 örneklem dışı testinde etki
  sürdü. Eleştiri: ABD'de 1987 ekimi ve 1998 ağustosu çıkarılınca kayboluyor.
- **FOMC öncesi:** Lucca ve Moench (2015): 1994'ten beri hisse senedi risk priminin yaklaşık
  %80'i, planlı Fed kararlarından önceki 24 saatte oluştu. 2018 güncellemesine göre etki
  sürüyor ama artık bir gün önceden başlıyor.

**Bizim testimiz:** Ay Dönümü stratejisi (ayın son N ve ilk M gününde SPY, diğer günlerde
BIL) 2005-2015 eğitim döneminde negatif Sharpe aldı ve sağlamlık kuralını geçemedi. Test
döneminde de negatif kaldı (yıllık +%2,7, Sharpe -0,17). Etki bu veride kaybolmuş görünüyor.

**Uygulamada:** Ay Dönümü Etkisi stratejisi Backtest'te denenebilir. Piyasa sekmesindeki
takvim FOMC kararlarını (2027 tarihleri Fed'in geçici takvimidir), NYSE tatillerini, erken
kapanışları ve ay dönümü pencerelerini gösterir.

## 5. Teknik analiz ve formasyonlar

- Sullivan, Timmermann ve White (1999), yüzlerce teknik kuralı White'ın "gerçeklik testi"
  ile sınadı. Bu test, çok sayıda kural denemenin yarattığı şans etkisini düzeltir.
  Düzeltmeden sonra en iyi kuralın örneklem dışı getirisi istatistiksel olarak anlamsızdı.
- Park ve Irwin (2007), 1990'ların başına kadar teknik kuralların kâr ettiğini ama
  çalışmaların çoğunun veri madenciliği, sonradan kural seçimi ve eksik maliyet hesabıyla
  sorunlu olduğunu yazdı.
- Mum formasyonları: Marshall, Young ve Rose (2006) Dow Jones hisselerinde mum
  stratejilerinin değer katmadığını buldu. Farklı bir çıkış kuralıyla bazı üç günlük
  formasyonları kârlı bulan çalışmalar da var; kanıt tartışmalı.
- Kısa vadeli geri dönüş (Connors'ın RSI(2) kuralı): uygulayıcıların testlerine göre
  getirisinin çoğu 1999-2010 arasında geldi. Sonrasına dair hakemli bir çalışma yok.

**Bizim testimiz:** RSI(2) eğitimde 0,62 Sharpe aldı, doğrulamada -0,16'ya düştü ve en büyük
düşüş kuralını geçemedi. İleri yürüyüş testinde (her yıl parametreyi yeniden seçmek) yıllık
yalnızca %2,3 getirdi.

**Uygulamada:** Mum formasyonu, Fibonacci ya da Elliott dalgası sinyali bilerek eklenmedi.
Tarayıcıdaki RSI(2) "geri çekilme" işareti yalnızca bilgi içindir.

## 6. Backtest neden yanıltır?

- **Çoklu deneme:** Harvey, Liu ve Zhu (2016), finans literatüründe yüzlerce "faktör"
  denendiğini, bu yüzden yeni bir bulgu için olağan t > 2 eşiği yerine t > 3 gerektiğini ve
  yayımlanan bulguların çoğunun muhtemelen yanlış olduğunu savundu.
- **Yayın sonrası zayıflama:** McLean ve Pontiff (2016), 97 getiri tahmin edicisinde
  getirinin örneklem dışında %26, yayından sonra %58 düştüğünü buldu.
- **Düzeltme yöntemleri:** Bailey ve López de Prado'nun olasılıksal Sharpe oranı (PSR),
  gerçek Sharpe'ın sıfırdan büyük olma olasılığını hesaplar. Bu hesap getiri geçmişinin
  uzunluğunu, çarpıklığını ve kalın kuyruklarını hesaba katar. Deflated Sharpe (DSR, 2014)
  aynı olasılığı, denenen tüm ayarların en şanslısının şans eseri alacağı Sharpe'a karşı
  ölçer. Bailey ve diğerlerinin (2017) aşırı uyum olasılığı (PBO) da aynı soruyu farklı bir
  yöntemle sorar.
- **İleri yürüyüş testi (Pardo):** parametreyi geçmişte seç, sonraki dönemde uygula, ileri
  kaydır. Ortaya çıkan eğride geri görüş yoktur.

**Bizim testimiz:** Bu çalışmada 12 ailede 65 ayar denendi. Kazananın doğrulama dönemindeki
DSR'si %69 çıktı (aynı ölçüyle SPY %60). İleri yürüyüşte (2010-2026) botun stratejisi yıllık
%7,1 getiri, 0,58 Sharpe ve -%21,3 en büyük düşüş verdi. SPY aynı dönemde %14,1, 0,78 ve
-%33,7 verdi. Örneklem dışı ve içi Sharpe oranı (verim) 0,88 oldu; 0,5'in üstü, seçilen
ayarların geleceğe makul ölçüde taşındığını gösterir.

**Uygulamada:** Backtest sekmesinin Güvenilirlik bölümü, bu oturumda denediğiniz her farklı
ayarı sayar; çok ayar denedikçe DSR düşer ve uyarı verir. İleri yürüyüş ve Monte Carlo
(durağan blok bootstrap, Politis ve Romano 1994) sekmeleri de burada.

## 7. Pozisyon büyüklüğü ve risk

- Kaminski ve Lo (2014): fiyatlar rastgele yürüyorsa stop-loss beklenen getiriyi asla
  artırmaz; momentum ya da rejim değişimi varsa artırabilir. Han, Zhou ve Zhu (2016),
  momentum stratejisinde stop-loss'un kayıpları belirgin biçimde azalttığını buldu.
- Kelly (1956) kriteri uzun vadeli büyümeyi en üst düzeye çıkaran oranı verir. MacLean,
  Thorp ve Ziemba (2010), tam Kelly'nin kısa vadede çok riskli olduğunu, Kelly'nin bir
  kesrinin (yarım, çeyrek) büyüme ile güvenlik arasında daha iyi bir denge kurduğunu gösterdi.
- Risk ölçüsü: Beklenen kayıp (ES), VaR'ın aksine en kötü günlerin ortalamasına bakar.
  Basel bankacılık kuralları %99 VaR'dan %97,5 ES'ye geçti.
- Kaldıraçlı ETF'ler günlük sıfırlandığı için uzun vadede, özellikle yatay ve oynak
  piyasalarda, endeksin katından geride kalır.

**Uygulamada:** Pozisyon hesaplayıcı (Grafik sekmesi → Pozisyon hesapla) şunları gösterir:
işlem başına riskten (%1 gibi) ve ATR, yüzde ya da fiyat stop'undan adet; 1R/2R/3R
hedefleri; art arda 10 zararın hesaba etkisi; yarım ve çeyrek Kelly. Backtest'in Risk
bölümü VaR, ES, ülser endeksi ve en uzun toparlanma süresini verir. Bot kaldıraç, açığa
satış ve opsiyon kullanmaz.

## 8. Kesitsel momentum ve 52 haftalık zirve

- Jegadeesh ve Titman (1993): son 3-12 ayda iyi giden hisseler sonraki aylarda da iyi
  gitmeye devam etti. Son ay genellikle tersine döndüğü için ölçüde atlanır (12-1 ay).
- George ve Hwang (2004): 52 haftalık zirvesine yakın hisseler sonraki dönemde daha iyi
  gitti. Bu ölçü momentum kârının büyük kısmını açıklıyor ve uzun vadede tersine dönmüyor.
  Gelişmekte olan piyasalarda sonuçlar daha zayıf.
- Daniel ve Moskowitz (2016): momentum, sert düşüşlerden sonraki toparlanmalarda çöker.

**Bizim testimiz:** Sektör rotasyonu (en güçlü sektör ETF'leri) eğitimde 0,75 Sharpe aldı,
doğrulamada 0,43'e düştü.

**Uygulamada:** Tarayıcı sekmesi; sektör, varlık sınıfı, ülke, ABD büyük şirketleri, BIST
büyükleri ya da kendi listenizi şu ölçülerle sıralar: 12-1 ay momentumu, 52 haftalık
zirveye uzaklık, trend, oynaklık ve RSI(2). Puan, iki momentum ölçüsünün sıralamasının
ortalamasıdır.

## 9. Makro göstergeler ve piyasa rejimi

- **Getiri eğrisi:** Estrella ve Mishkin'in modeli, 10 yıllık ile 3 aylık faiz farkından
  12 ay içinde resesyon olasılığını hesaplar: P = Φ(-0,5333 - 0,6330 × fark). Bu modeli
  New York Fed kullanır. Eğrinin terslenmesi 1970'ten beri her ABD resesyonundan önce
  görüldü, ama zamanlama 6-24 ay arasında değişir. St. Louis Fed, enflasyon beklentileri
  ayrıştığı için son dönemde bu farkın daha az bilgi verebileceğini not eder.
- **Kredi primi:** Gilchrist ve Zakrajšek (2012), şirket tahvili primlerinin temerrüt riskiyle
  açıklanamayan kısmının ekonomik yavaşlamayı önceden haber verdiğini gösterdi.
- **VIX vade yapısı:** Kısa vadeli VIX'in 3 aylığı geçmesi yakın vadeli stres demektir;
  bunun getiriyi öngördüğünü gösteren hakemli bir çalışma bulunamadı.

**Bizim testimiz (2005-2026, SPY, sonraki 21 işlem günü):**

| Durum | Sonraki ay ort. getiri | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|
| Tüm günler | +%0,98 | -%6,7 | %15,6 |
| 200 günlük ortalamanın altında | +%1,11 | -%10,7 | %27,2 |
| VIX > 25 | +%2,22 | -%11,1 | %28,7 |
| VIX vade yapısı ters | +%1,76 | -%15,5 | %30,5 |
| Getiri eğrisi ters | +%1,67 | -%4,1 | %12,8 |
| Sektörlerin %30'undan azı yükselişte | +%2,06 | -%14,8 | %31,5 |

Sonuç açık: kötü rejimler sonraki ayın **oynaklığını** iki katına çıkarıyor, ama ortalama
**getiriyi** düşürmüyor; hatta toparlanmalar yüzünden artırıyor. Ters getiri eğrisi kısa
vadede bir satış sinyali değil. Bu yüzden bot piyasayı zamanlamaya değil, oynaklığa göre
pozisyon küçültmeye dayanır.

**Uygulamada:** Piyasa sekmesi sekiz göstergenin bugünkü durumunu, resesyon olasılığını,
5 yıllık geçmişini ve bu tabloyu canlı veriyle gösterir.

## 10. Çeşitlendirme ve sade kurallar

- Faber (2007): beş varlık sınıfının her birini 10 aylık ortalamanın üstündeyken tutmak,
  benzer getiriyle çok daha düşük düşüş sağladı. Faber, 2018'de yayımlanan güncellemede kuralı
  yayından sonraki 11 yılla yeniden değerlendirdi. Eleştirmenler, ilk testin dönemin şansından
  yararlandığını düşünüyor.
- Risk paritesi: Asness, Frazzini ve Pedersen (2012), varlıkları risk katkısına göre dengeleyen
  ve kaldıraç kullanan portföyün yüz yılda piyasayı geçtiğini buldu. Eleştirmenlere göre sonucu
  sağlayan kaldıraç.
- Dengeleme: Vanguard'ın çalışmaları, eşik tabanlı dengelemenin takvim tabanlıya göre riski
  daha iyi kontrol ettiğini ve en iyi dengelemenin ne çok sık ne çok seyrek olduğunu buldu.

**Bizim testimiz:** Kaldıraçsız risk paritesi test döneminde 0,84 Sharpe ve -%7,7 en büyük
düşüş verdi. Yarı oynaklık hedefli trend, yarı TSMOM'dan oluşan strateji karması test
döneminde en yüksek Sharpe'ı (0,92) ve en düşük düşüşü (-%7,6) aldı. Ama kurallara göre
seçim doğrulama dönemine göre yapıldığı için seçilmedi: test dönemine bakıp seçmek, testi
anlamsız kılar.

**Uygulamada:** Risk Paritesi ve Strateji Karması stratejileri. Karmanın parçalarını
`vol_target=50, gtaa=50` biçiminde istediğiniz gibi verebilirsiniz. Bot, hedeften 5 puan
sapınca dengeler.

## Bilerek eklemediklerimiz

- **Gün içi otomatik işlem:** Bireysel gün içi işlemcilerin büyük çoğunluğu kaybediyor
  (bölüm 1). Ayrıca maliyet ve veri gecikmesi bu ölçekte belirleyici olur.
- **Mum formasyonu, Fibonacci, Elliott sinyalleri:** Kanıt zayıf (bölüm 5).
- **Kaldıraç, açığa satış, opsiyon:** Kayıpları sınırsızlaştırır; kaldıraçlı ETF'ler uzun
  vadede erir (bölüm 7).
- **Tam Kelly ile otomatik boyutlama:** Kazanma oranı ve kazanç/kayıp tahmini belirsizdir.
  Hesaplayıcı yalnızca yarım ve çeyrek Kelly'yi önerir.
- **Test dönemine bakarak strateji değiştirmek:** Strateji karması test döneminde daha iyi
  göründüğü halde varsayılan yapılmadı (bölüm 10).

## Kaynaklar

- Asness, Frazzini, Pedersen (2012), *Leverage Aversion and Risk Parity*, Financial Analysts
  Journal. https://www.aqr.com/Insights/Research/Journal-Article/Leverage-Aversion-and-Risk-Parity
- Bailey, López de Prado (2012), *The Sharpe Ratio Efficient Frontier*, Journal of Risk.
  https://www.risk.net/journal-risk/2223785/sharpe-ratio-efficient-frontier
- Bailey, López de Prado (2014), *The Deflated Sharpe Ratio*, Journal of Portfolio Management.
  https://papers.ssrn.com/abstract=2460551
- Bailey, Borwein, López de Prado, Zhu (2017), *The Probability of Backtest Overfitting*,
  Journal of Computational Finance. https://papers.ssrn.com/abstract=2326253
- Barber, Odean (2000), *Trading Is Hazardous to Your Wealth*, Journal of Finance.
  https://faculty.haas.berkeley.edu/odean/papers/returns/returns.html
- Barroso, Santa-Clara (2015), *Momentum Has Its Moments*; Daniel, Moskowitz (2016), *Momentum
  Crashes* (özet). https://alphaarchitect.com/risk-of-momentum-crashes/
- Bouman, Jacobsen (2002), *The Halloween Indicator*; örneklem dışı güncellemeler (özet).
  https://alphaarchitect.com/may-sell-go-away/
- Cambridge Associates, trend takibinin 2008, 2022 ve 2024-25 performansı.
  https://www.cambridgeassociates.com/insight/does-trend-followings-recent-struggle-signal-that-the-strategy-is-structurally-broken/
- Cederburg, O'Doherty, Wang, Yan (2020), *On the Performance of Volatility-Managed
  Portfolios*, Journal of Financial Economics. https://www.lehigh.edu/~xuy219/research/COWY.pdf
- Chague, De-Losso, Giovannetti (2020), *Day Trading for a Living?*
  https://econpapers.repec.org/RePEc:fgv:eesptd:525
- DeMiguel, Martin-Utrera, Uppal (2024), *A Multifactor Perspective on Volatility-Managed
  Portfolios*, Journal of Finance. https://lbsresearch.london.edu/id/eprint/3716
- Estrella, Mishkin; New York Fed, *The Yield Curve as a Leading Indicator* (SSS).
  https://www.newyorkfed.org/medialibrary/media/research/capital_markets/ycfaq.pdf
- St. Louis Fed (2023), getiri farkı ve resesyon olasılığı.
  https://www.stlouisfed.org/on-the-economy/2023/sep/what-probability-recession-message-yield-spreads
- Faber (2007), *A Quantitative Approach to Tactical Asset Allocation* (strateji özeti).
  https://quantpedia.com/strategies/asset-class-trend-following
- George, Hwang (2004), *The 52-Week High and Momentum Investing*, Journal of Finance (özet).
  https://alphaarchitect.com/the-secret-to-momentum-is-the-52-week-high/
- Gilchrist, Zakrajšek (2012), *Credit Spreads and Business Cycle Fluctuations*; Fed notu (2016).
  https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/recession-risk-and-the-excess-bond-premium-20160408.html
- Harvey, Liu, Zhu (2016), *…and the Cross-Section of Expected Returns*, Review of Financial
  Studies. https://www.nber.org/papers/w20592
- Hurst, Ooi, Pedersen (2017), *A Century of Evidence on Trend-Following Investing*.
  https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
- Jegadeesh, Titman (1993), *Returns to Buying Winners and Selling Losers*, Journal of Finance.
- Kaminski, Lo (2014), *When Do Stop-Loss Rules Stop Losses?*, Journal of Financial Markets.
  https://dspace.mit.edu/handle/1721.1/114876
- Kim, Tse, Wald; Goyal, Jegadeesh — zaman serisi momentumu eleştirileri (özet).
  https://quantpedia.com/deconstructing-the-time-series-momentum-strategy/
- Kaldıraçlı ETF'lerde bileşik getiri etkisi (2025, ön baskı). https://arxiv.org/abs/2504.20116
- Lucca, Moench (2015), *The Pre-FOMC Announcement Drift*, Journal of Finance; 2018 güncellemesi.
  https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.html ·
  https://libertystreeteconomics.newyorkfed.org/2018/11/the-pre-fomc-announcement-drift-more-recent-evidence.html
- MacLean, Thorp, Ziemba (2010), *Good and Bad Properties of the Kelly Criterion*.
  https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf
- Marshall, Young, Rose (2006), *Candlestick Technical Trading Strategies*, Journal of Banking
  & Finance (özet). https://www.cxoadvisory.com/?p=1236
- McConnell, Xu (2008), *Equity Returns at the Turn of the Month*, Financial Analysts Journal.
  https://rpc.cfainstitute.org/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month
- McLean, Pontiff (2016), *Does Academic Research Destroy Stock Return Predictability?*,
  Journal of Finance. https://ivey.uwo.ca/media/3775549/pontiff.pdf
- Moskowitz, Ooi, Pedersen (2012), *Time Series Momentum*, Journal of Financial Economics.
  https://papers.ssrn.com/abstract=2089463
- Odean (1998), elden çıkarma etkisi (özet). https://en.wikipedia.org/wiki/Disposition_effect
- Pardo (2008), *The Evaluation and Optimization of Trading Strategies*, Wiley.
- Park, Irwin (2007), *What Do We Know About the Profitability of Technical Analysis?*,
  Journal of Economic Surveys. https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html
- Politis, Romano (1994), *The Stationary Bootstrap*, JASA; azami düşüş dağılımı için
  karşılaştırma. https://madoc.bib.uni-mannheim.de/72376/
- Sullivan, Timmermann, White (1999), *Data-Snooping, Technical Trading Rule Performance, and
  the Bootstrap*, Journal of Finance.
- Vanguard (2022), *Rational Rebalancing*.
  https://corporate.vanguard.com/content/dam/corp/research/pdf/rational_rebalancing_analytical_approach_to_multiasset_portfolio_rebalancing.pdf
- Federal Reserve, FOMC toplantı takvimi.
  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
