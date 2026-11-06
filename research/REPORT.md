# Strateji araştırması

Bu rapor `python -m research.study` ile üretildi. Veri: Yahoo Finance günlük fiyatları (bölünme ve temettü düzeltilmiş), son bar 2026-10-28. Her işlemde 5 baz puan maliyet, emirler ertesi günün açılışında dolar. Getiriler geçmişe aittir; gelecekte aynısının olacağını göstermez.

## Kural (sonuçlara bakmadan önce yazıldı)

1. Her ailenin parametresi **eğitim** döneminde (2005–2015) en iyi Sharpe'a göre seçilir.
2. Kazanan aile, **doğrulama** döneminde (2016–2022) en iyi Sharpe'a sahip olandır; ancak SPY al-tut'tan daha derin düşüş yapmamalı, en az 10 işlem yapmalı ve tek bir şanslı parametreye dayanmamalı (ailenin medyan eğitim Sharpe'ı seçilenin en az %75'i).
3. **Test** dönemi (2023–bugün) seçimde hiç kullanılmadı; sadece sonda raporlandı.
4. Hiçbir aile geçemezse bot SPY al-tut ile başlar.
5. **2. tur (29.10.2026):** literatürden beş aile eklendi (Faber GTAA, zaman serisi momentumu, risk paritesi, ay dönümü etkisi, strateji karması). Izgaraları sonuçlara bakmadan yazıldı; 1-4. kurallar değişmedi. İlk yedi ailenin test dönemine 1. turda bir kez bakılmıştı.

## Sonuç: Volatilite Hedefli Trend

Seçilen parametreler: `vol_target(n=200, off=BIL, symbol=SPY, target=0.15, vol_n=20)`

### Test dönemi (seçimde kullanılmadı): 2023-01-03 – 2026-10-28

| Strateji | Yıllık getiri | Oynaklık | Sharpe | En büyük düşüş | Calmar | İşlem |
|---|---|---|---|---|---|---|
| **Volatilite Hedefli Trend** | +14.1% | +11.5% | 0.82 | -10.2% | 1.38 | 107 |
| SPY al-tut | +21.6% | +14.8% | 1.10 | -18.8% | 1.15 | 1 |
| 60/40 (SPY/AGG) | +14.7% | +9.7% | 1.01 | -10.7% | 1.37 | 12 |

### Doğrulama dönemi: 2016-01-04 – 2022-12-30

| Strateji | Yıllık getiri | Oynaklık | Sharpe | En büyük düşüş | Calmar | İşlem |
|---|---|---|---|---|---|---|
| **Volatilite Hedefli Trend** | +8.2% | +10.4% | 0.72 | -14.7% | 0.56 | 223 |
| SPY al-tut | +11.6% | +19.0% | 0.63 | -33.7% | 0.34 | 1 |
| 60/40 (SPY/AGG) | +7.6% | +12.0% | 0.60 | -21.5% | 0.35 | 12 |

### Eğitim dönemi: 2005-01-03 – 2015-12-31

| Strateji | Yıllık getiri | Oynaklık | Sharpe | En büyük düşüş | Calmar | İşlem |
|---|---|---|---|---|---|---|
| **Volatilite Hedefli Trend** | +4.7% | +10.4% | 0.40 | -18.1% | 0.26 | 375 |
| SPY al-tut | +7.0% | +20.0% | 0.39 | -55.2% | 0.13 | 1 |
| 60/40 (SPY/AGG) | +6.3% | +12.0% | 0.48 | -34.9% | 0.18 | 16 |

## Tüm aileler (seçilen parametreyle)

| Aile | Parametre | Eğitim Sharpe | Doğrulama Sharpe | Doğrulama düşüş | Doğrulama işlem | Kurallar |
|---|---|---|---|---|---|---|
| Volatilite Hedefli Trend | `n=200, off=BIL, symbol=SPY, target=0.15, vol_n=20` | 0.40 | 0.72 | -14.7% | 223 | geçti |
| Trend Filtresi (SMA) | `monthly=True, n=150, off=BIL, symbol=SPY` | 0.69 | 0.69 | -22.9% | 21 | kaldı: robust |
| Varlık Rotasyonu | `filter=sma, k=3, off=BIL, universe=[10]` | 0.76 | 0.68 | -16.0% | 231 | geçti |
| Strateji Karması | `parts={vol_target:0.5,tsmom:0.5}` | 0.60 | 0.66 | -12.2% | 645 | geçti |
| Çoklu Varlık Trendi (TSMOM) | `lookback=126, min_assets=3, off=BIL, universe=[7], vol_n=63` | 0.78 | 0.66 | -12.9% | 478 | geçti |
| Faber GTAA (10 aylık ortalama) | `months=12, off=BIL, universe=[5]` | 0.54 | 0.58 | -8.0% | 215 | geçti |
| Altın Kesişim | `fast=50, off=BIL, slow=150, symbol=SPY` | 0.65 | 0.51 | -33.7% | 19 | geçti |
| Risk Paritesi (ters oynaklık) | `min_assets=3, universe=[7], vol_n=63` | 0.53 | 0.47 | -18.8% | 595 | geçti |
| Ay Dönümü Etkisi | `after=4, before=2, off=BIL, symbol=SPY` | 0.06 | 0.47 | -9.9% | 337 | kaldı: robust |
| Sektör Rotasyonu | `k=4, lookback=252, off=BIL, sectors=[9], trend_n=200, trend_symbol=SPY` | 0.75 | 0.43 | -23.4% | 249 | geçti |
| Çift Momentum (GEM) | `cash=BIL, lookback=126, risk=[SPY,EFA], safe=AGG` | 0.58 | 0.21 | -33.7% | 37 | geçti |
| RSI(2) Geri Dönüş | `entry=10, exit_n=10, off=BIL, symbol=SPY, trend_n=200` | 0.62 | -0.16 | -34.4% | 177 | kaldı: drawdown, robust |

SPY al-tut doğrulama düşüşü: -33.7%.

## Yıllık getiriler: Volatilite Hedefli Trend ve SPY

| Yıl | Volatilite Hedefli Trend | SPY |
|---|---|---|
| 2005 | -2.7% | +5.1% |
| 2006 | +10.8% | +15.8% |
| 2007 | -3.2% | +5.1% |
| 2008 | -2.6% | -36.8% |
| 2009 | +14.8% | +26.4% |
| 2010 | -0.2% | +15.1% |
| 2011 | -4.2% | +1.9% |
| 2012 | +11.8% | +16.0% |
| 2013 | +31.1% | +32.3% |
| 2014 | +9.9% | +13.5% |
| 2015 | -7.3% | +1.2% |
| 2016 | +9.4% | +13.3% |
| 2017 | +21.7% | +21.7% |
| 2018 | -3.5% | -4.6% |
| 2019 | +12.5% | +31.2% |
| 2020 | +6.3% | +18.3% |
| 2021 | +26.5% | +28.7% |
| 2022 | -10.9% | -18.2% |
| 2023 | +11.5% | +25.9% |
| 2024 | +22.0% | +24.9% |
| 2025 | +10.7% | +17.7% |
| 2026 | +9.8% | +14.1% |

## Test dönemi, tüm aileler (yalnızca bilgi için)

Seçim bu tabloya bakılmadan yapıldı. Buradan strateji seçmek, test dönemini seçimde kullanmak olur ve geçmişe fazla uyum riskini geri getirir.

| Strateji | Yıllık getiri | Oynaklık | Sharpe | En büyük düşüş | Calmar | İşlem |
|---|---|---|---|---|---|---|
| Strateji Karması | +12.3% | +8.1% | 0.92 | -7.6% | 1.61 | 319 |
| Altın Kesişim | +16.3% | +13.1% | 0.88 | -17.5% | 0.93 | 15 |
| Risk Paritesi (ters oynaklık) | +11.8% | +8.5% | 0.84 | -7.7% | 1.54 | 322 |
| Volatilite Hedefli Trend | +14.1% | +11.5% | 0.82 | -10.2% | 1.38 | 107 |
| Varlık Rotasyonu | +14.8% | +14.4% | 0.73 | -13.2% | 1.12 | 131 |
| Trend Filtresi (SMA) | +13.0% | +12.0% | 0.72 | -10.0% | 1.30 | 15 |
| Faber GTAA (10 aylık ortalama) | +9.3% | +7.0% | 0.68 | -8.4% | 1.11 | 128 |
| Sektör Rotasyonu | +12.4% | +12.0% | 0.67 | -10.5% | 1.18 | 153 |
| Çift Momentum (GEM) | +11.4% | +12.6% | 0.57 | -11.4% | 1.00 | 23 |
| Çoklu Varlık Trendi (TSMOM) | +7.4% | +6.0% | 0.49 | -5.2% | 1.43 | 287 |
| RSI(2) Geri Dönüş | +7.9% | +7.1% | 0.48 | -8.5% | 0.93 | 153 |
| Ay Dönümü Etkisi | +2.7% | +8.4% | -0.17 | -20.8% | 0.13 | 183 |
| SPY al-tut | +21.6% | +14.8% | 1.10 | -18.8% | 1.15 | 1 |

## Güvenilirlik: kısa geçmiş ve seçim yanlılığı

Bir backtest'in Sharpe oranı iki nedenle gerçeğinden iyi görünür: geçmiş kısadır ve en iyisi çok sayıda denemenin arasından seçilmiştir. **Olasılıksal Sharpe (PSR)**, gerçek Sharpe'ın sıfırdan büyük olma olasılığıdır; getirilerin çarpıklığını ve basıklığını hesaba katar. **Deflated Sharpe (DSR)**, aynı olasılığı, denenen tüm ayarların en şanslısının şans eseri alacağı Sharpe'a karşı ölçer (Bailey ve López de Prado, 2012 ve 2014). Bu çalışmada **65 ayar** denendi; araştırmacının gayriresmî denemeleri sayılmadığı için DSR iyimser tarafta kalır. Son sütun, Sharpe'ın sıfırdan büyük olduğuna %95 güvenle karar vermek için gereken getiri geçmişidir.

| Strateji | Dönem | Sharpe (BIL üstü) | PSR (>0) | DSR | %95 güven için gereken süre |
|---|---|---|---|---|---|
| **Volatilite Hedefli Trend** | Eğitim | 0.40 | 91% | — | 17 yıl |
| **Volatilite Hedefli Trend** | Doğrulama | 0.72 | 97% | 69% (eşik Sharpe 0.53) | 5.5 yıl |
| **Volatilite Hedefli Trend** | Test | 0.82 | 94% | — | 4.1 yıl |
| SPY al-tut | Eğitim | 0.39 | 90% | — | 18 yıl |
| SPY al-tut | Doğrulama | 0.63 | 95% | 60% (eşik Sharpe 0.53) | 7.1 yıl |
| SPY al-tut | Test | 1.10 | 99% | — | 2.2 yıl |

## İleri yürüyüş: her yıl parametreyi yeniden seçmek

Her yılın başında ailenin parametresi önceki 5 yılın en iyi Sharpe'ına göre seçildi ve sonraki 1 yıl bu parametreyle işlem yapıldı; yıllar uç uca eklendi (2010-01-04 – 2026-10-28). Bu eğri geri görüş içermez: her karar, verildiği gün bilinen veriyle verildi. **Verim** = örnek dışı Sharpe / eğitim Sharpe'ı; 0.5'in altı, geçmişte iyi görünen parametrelerin geleceğe pek taşınmadığını gösterir.

| Aile | Yıllık getiri | Oynaklık | Sharpe | En büyük düşüş | Eğitim Sharpe | Verim |
|---|---|---|---|---|---|---|
| Trend Filtresi (SMA) | +9.5% | +12.4% | 0.68 | -26.1% | 0.84 | 0.81 |
| Varlık Rotasyonu | +9.9% | +13.6% | 0.67 | -18.3% | 0.79 | 0.85 |
| Strateji Karması | +6.1% | +8.3% | 0.59 | -16.4% | 0.72 | 0.83 |
| Volatilite Hedefli Trend | +7.1% | +10.5% | 0.58 | -21.3% | 0.66 | 0.88 |
| Altın Kesişim | +9.1% | +14.6% | 0.58 | -33.7% | 0.72 | 0.80 |
| Risk Paritesi (ters oynaklık) | +5.6% | +9.0% | 0.50 | -19.4% | 0.52 | 0.96 |
| Çoklu Varlık Trendi (TSMOM) | +4.2% | +6.2% | 0.47 | -12.9% | 0.74 | 0.64 |
| Sektör Rotasyonu | +7.2% | +14.1% | 0.47 | -23.4% | 0.74 | 0.64 |
| Çift Momentum (GEM) | +7.3% | +15.1% | 0.45 | -33.7% | 0.54 | 0.83 |
| Faber GTAA (10 aylık ortalama) | +3.8% | +7.7% | 0.35 | -12.4% | 0.61 | 0.57 |
| Ay Dönümü Etkisi | +2.3% | +8.2% | 0.16 | -18.8% | 0.25 | 0.63 |
| RSI(2) Geri Dönüş | +2.3% | +9.4% | 0.15 | -32.9% | 0.58 | 0.25 |
| SPY al-tut (aynı dönem) | +14.1% | +17.0% | 0.78 | -33.7% | — | — |

## Monte Carlo: önümüzdeki 5 yıl için olası aralık

2005'ten bugüne günlük getiriler, ortalama 21 günlük bloklar halinde rastgele yeniden dizildi (durağan blok bootstrap, Politis ve Romano 1994); 5000 yol. Bu, geçmişin aynen tekrarlanacağını değil, geçmişteki iniş çıkışlar başka bir sırayla gelseydi neler olabileceğini gösterir. Geçmişte görülmemiş bir kriz bu aralığın dışına çıkabilir.

| Strateji | Yıllık getiri: kötü (%5) | orta | iyi (%95) | En büyük düşüş: orta | kötü (%5) | Zararla bitirme olasılığı | %20'den derin düşüş olasılığı |
|---|---|---|---|---|---|---|---|
| **Volatilite Hedefli Trend** | -0.4% | +7.5% | +15.3% | -15.7% | -27.8% | 6% | 23% |
| SPY al-tut | -1.7% | +11.1% | +23.7% | -26.3% | -45.9% | 8% | 75% |

## Piyasa rejimleri: sonraki 1 ayda ne oldu? (SPY)

Her gösterge için, göstergenin o durumda olduğu günlerden sonraki 21 işlem gününde SPY'ın getirisi ve oynaklığı. Uygulamadaki **Piyasa** sekmesi aynı göstergeleri bugünün verisiyle gösterir. Pencereler çakıştığı için gün sayısı bağımsız gözlem sayısını abartır; farkların bir kısmı tesadüf olabilir.

Tüm günler: ortalama aylık getiri +0.98%, yükselen ay oranı 67%, kötü ay (%5) -6.7%, sonraki oynaklık +15.6%.

### Trend (SPY / 200 günlük ortalama) (veri 2005-01-03'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Ortalamanın altında | 20% | +1.11% | 62% | -10.7% | +27.2% |
| Ortalamanın üstünde | 80% | +0.95% | 69% | -5.5% | +12.7% |

### 12 aylık momentum (SPY − hazine bonosu) (veri 2005-01-03'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Negatif | 16% | +1.06% | 63% | -10.7% | +26.1% |
| Pozitif | 84% | +0.97% | 68% | -5.8% | +13.5% |

### Gerçekleşen oynaklık (SPY, 20 gün, yıllık) (veri 2005-01-03'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Düşük (<%12) | 46% | +0.73% | 66% | -4.5% | +11.4% |
| Normal (%12-20) | 34% | +1.11% | 71% | -8.0% | +14.7% |
| Yüksek (>%20) | 20% | +1.36% | 65% | -10.2% | +26.7% |

### VIX (beklenen oynaklık) (veri 2005-01-03'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Sakin (<15) | 37% | +0.71% | 67% | -4.3% | +10.4% |
| Normal (15-25) | 47% | +0.77% | 67% | -7.5% | +15.1% |
| Gergin (>25) | 16% | +2.22% | 70% | -11.1% | +28.7% |

### VIX vade yapısı (VIX / VIX3M) (veri 2006-07-17'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Normal eğim (<1) | 89% | +0.93% | 68% | -6.5% | +14.2% |
| Ters eğim (≥1) | 11% | +1.76% | 68% | -15.5% | +30.5% |

### Getiri eğrisi (10 yıl − 3 ay) (veri 2005-01-03'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Ters (≤0) | 15% | +1.67% | 75% | -4.1% | +12.8% |
| Normal (>0) | 85% | +0.86% | 66% | -7.1% | +16.1% |

### Kredi iştahı (HYG / IEF, 200 günlük ortalamaya göre) (veri 2008-01-24'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Kaçış (altında) | 34% | +1.18% | 66% | -9.1% | +21.5% |
| İştah var (üstünde) | 66% | +0.98% | 68% | -5.8% | +13.4% |

### Piyasa genişliği (200 gün ortalama üstündeki sektör payı) (veri 2005-01-03'den)

| Durum | Günlerin payı | Ort. 1 ay getiri | Yükselen ay oranı | Kötü ay (%5) | Sonraki oynaklık |
|---|---|---|---|---|---|
| Dar (<%30) | 11% | +2.06% | 69% | -14.8% | +31.5% |
| Karışık (%30-70) | 22% | +0.89% | 64% | -8.0% | +17.5% |
| Geniş (≥%70) | 68% | +0.84% | 68% | -5.2% | +12.4% |

## Bilinen sınırlar

- Geçmiş performans geleceği garanti etmez. Bu stratejiler yayınlandıktan sonra da çalıştı mı diye bakmak için test dönemi ayrıldı, ama 3-4 yıl kısa bir süre.
- Vergiler ve döviz kuru (TL/USD) hesaba katılmadı. Temettüler düzeltilmiş fiyatlarla dahil; gerçekte temettülerden stopaj kesilir.
- 2007 öncesinde BIL yoktu; o dönemde nakit kolu SHY'nin getirisiyle dolduruldu.
- Bazı ETF'ler (GLD, DBC, VNQ) 2004-2006'da başladı; varlık rotasyonu o yıllarda daha az varlıktan seçti.
- VIX3M 2006'dan, HYG 2007'den başlar; o rejim göstergeleri daha kısa dönemi kapsar.
- 2. turda eklenen aileler için test dönemi ilk kez açıldı; ilk yedi aile için ise test dönemine 1. turda bir kez bakılmıştı.

