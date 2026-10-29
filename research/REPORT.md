# Strateji araştırması

Bu rapor `python -m research.study` ile üretildi. Veri: Yahoo Finance günlük fiyatları (bölünme ve temettü düzeltilmiş), son bar 2026-10-28. Her işlemde 5 baz puan maliyet, emirler ertesi günün açılışında dolar. Getiriler geçmişe aittir; gelecekte aynısının olacağını göstermez.

## Kural (sonuçlara bakmadan önce yazıldı)

1. Her ailenin parametresi **eğitim** döneminde (2005–2015) en iyi Sharpe'a göre seçilir.
2. Kazanan aile, **doğrulama** döneminde (2016–2022) en iyi Sharpe'a sahip olandır; ancak SPY al-tut'tan daha derin düşüş yapmamalı, en az 10 işlem yapmalı ve tek bir şanslı parametreye dayanmamalı (ailenin medyan eğitim Sharpe'ı seçilenin en az %75'i).
3. **Test** dönemi (2023–bugün) seçimde hiç kullanılmadı; sadece sonda raporlandı.
4. Hiçbir aile geçemezse bot SPY al-tut ile başlar.

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
| Altın Kesişim | `fast=50, off=BIL, slow=150, symbol=SPY` | 0.65 | 0.51 | -33.7% | 19 | geçti |
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
| Altın Kesişim | +16.3% | +13.1% | 0.88 | -17.5% | 0.93 | 15 |
| Volatilite Hedefli Trend | +14.1% | +11.5% | 0.82 | -10.2% | 1.38 | 107 |
| Varlık Rotasyonu | +14.8% | +14.4% | 0.73 | -13.2% | 1.12 | 131 |
| Trend Filtresi (SMA) | +13.0% | +12.0% | 0.72 | -10.0% | 1.30 | 15 |
| Sektör Rotasyonu | +12.4% | +12.0% | 0.67 | -10.5% | 1.18 | 153 |
| Çift Momentum (GEM) | +11.4% | +12.6% | 0.57 | -11.4% | 1.00 | 23 |
| RSI(2) Geri Dönüş | +7.9% | +7.1% | 0.48 | -8.5% | 0.93 | 153 |
| SPY al-tut | +21.6% | +14.8% | 1.10 | -18.8% | 1.15 | 1 |

## Bilinen sınırlar

- Geçmiş performans geleceği garanti etmez. Bu stratejiler yayınlandıktan sonra da çalıştı mı diye bakmak için test dönemi ayrıldı, ama 3-4 yıl kısa bir süre.
- Vergiler ve döviz kuru (TL/USD) hesaba katılmadı. Temettüler düzeltilmiş fiyatlarla dahil; gerçekte temettülerden stopaj kesilir.
- 2007 öncesinde BIL yoktu; o dönemde nakit kolu SHY'nin getirisiyle dolduruldu.
- Bazı ETF'ler (GLD, DBC, VNQ) 2004-2006'da başladı; varlık rotasyonu o yıllarda daha az varlıktan seçti.

