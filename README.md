# TTO Masa — TRY ve USD faiz masası dashboard'u

`TTO_v8_5.xlsm` (TRY faiz masası: OIS/PPK, forward, VİOP, DİBS RV, DV01 …), `USD_SOFR_FOMC.xlsx`
(USD OIS / FOMC patikası), `BBG_Borsa_Swap.xlsx` (Borsa İstanbul swap kotaları → ima TRY faizi) ve `DIBS_ASW.xlsx`
(DİBS asset swap spread'leri, TLREF OIS eğrisine göre) çalışma kitaplarının tek bir web dashboard'unda
birleştirilmiş hâli. Piyasa verisi Bloomberg'den `blpapi` ile canlı gelir; Bloomberg yoksa Excel dosyasında
kayıtlı son veriyle çalışır.

* **Port:** varsayılan `1057`. `1055` ve `1056` portları **hiçbir koşulda kullanılmaz** (program reddeder).
* **Excel ile birebir:** formüller yeniden yazılmadı; çalışma kitaplarının kendi formülleri bir Excel formül
  motoruyla aynen çalıştırılıyor. Doğrulama sonuçları [aşağıda](#excel-ile-birebirlik-nasıl-doğrulandı).
* **İsimle giriş:** her kullanıcı ismini yazıp girer; kişisel girdileri ve senaryoları o isimle saklanır.
* **Ortak veriler:** RET faizleri ve Günlük İşlemler bir kişi kaydedince herkeste anında görünür ve sunucu
  yeniden başlasa da kalır.
* **Excel ⇄ dashboard kopyala / yapıştır:** tablolar Excel'e, Excel'deki bloklar girdi hücrelerine doğrudan.
* **Hiçbir formül eksik değil:** dört kitabın her sayfasındaki her formül ve değer, sayfasının bir tablosundadır
  (görünen tablo ya da "Yardımcı tablolar"); bunu bir test denetler.
* **Excel'de olmayan ekler** de Excel formülü olarak yazıldı: bid / ask için ayrı OIS spread'li forward kotasyon
  matrisi, altın forward'ının lease faizinden hesabı, O/N karşılıkları ([aşağıda](#dashboardun-kendi-ekledikleri)).

---

## Hızlı başlangıç

```bash
pip install -r requirements.txt
```

```bash
python -m tto
```

Tarayıcıdan `http://<makine-adı>:1057` adresine girin. Windows'ta `run.bat`'a çift tıklamak da aynı işi yapar.
Python 3.11, 3.12 ve 3.13 ile sınandı (kod 3.9 sözdizimiyle uyumlu yazıldı).

Bloomberg terminalinin olduğu makinede bir kez:

```bash
pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi
```

Bağlantıyı ve alanları sınamak için (birkaç örnek kotasyon ister, sonucu yazar):

```bash
python -m tto check-bloomberg
```

### Çalışma modları

| Komut | Davranış |
|---|---|
| `python -m tto` | `auto`: Bloomberg'e bağlanabilirse **canlı**, bağlanamazsa **kayıtlı veri** (üstte sarı rozet + uyarı) |
| `python -m tto --mode live` | Yalnızca canlı; Bloomberg yoksa başlamaz |
| `python -m tto --mode replay` | Bloomberg'e hiç dokunmaz; Excel dosyasındaki son kayıtlı piyasa verisi (değerleme tarihi 03.11.2026) |

Diğer seçenekler: `--port 1060` (1055/1056 hariç), `--host 127.0.0.1`, `--data-dir D:\tto-data` (veritabanı klasörü),
`--bbg-host`, `--bbg-port 8194`, `--tick 2` (ekran yenileme, sn), `--no-stream`, `--price-poll 120`, `--max-hits 400000`,
`--bfx approx`. Aynı ayarlar `TTO_PORT`, `TTO_HOST`, `TTO_MODE`, `TTO_DATA_DIR`, `TTO_BBG_HOST`, `TTO_BBG_PORT`
ortam değişkenleriyle de verilebilir.

---

## Kullanım

**Sayfalar.** Excel'deki her sayfanın bir karşılığı var: Masa, OIS · PPK, Forward, VİOP, Borsa Swap, Carry & Roll,
TM OIS, DİBS RV, DİBS ASW, Manuel Tahvil, Bulk Bond, YP DİBS, DV01 Risk, USD · FOMC, Hesaplayıcılar, USDTRY IYIX,
Mobil MK, Ivır Zıvır, Motor. Ek olarak **Günlük İşlemler** ve herhangi bir sayfanın herhangi bir aralığını
(formülüyle birlikte) gösteren **Sayfa gezgini**. Masa sayfasının üstündeki **Kısayollar** Excel'deki 30 köprünün
aynısıdır: tıklayınca ilgili sayfa açılır ve köprünün gösterdiği tablo ekrana gelir.

**Tablolar ve yardımcı tablolar.** Bir sayfadaki her formül ve değer o sayfanın bir tablosundadır. Masanın baktığı
tablolar doğrudan görünür; ara hesaplar, grafik verileri ve Excel'de kenara yazılmış serbest hücreler "Yardımcı
tablolar" düğmesiyle açılır (çok uzun olanların ilk satırları gösterilir, tamamı Sayfa gezgini'ndedir). Tabloların
altındaki açıklama satırları ve grafiklerin üstündeki blok başlıkları Excel'deki hücrelerden okunur.

**Grafikler.** Excel'deki 16 grafik kendi tanımlarıyla çizilir: seri renkleri (RET kırmızı/mor kesik çizgi, ICAP
turuncu, OIS mavi, VİOP yeşil …), işaretçiler, yumuşatılmış çizgiler, sabit eksen alt/üst sınırı ve adımı, eksen
sayı biçimi, tarih ekseni (TLREF patikası ay ay), her 4 etiketten biri (FRA eğrisi), RET bid–ask kutuları, bant
(alan) grafikleri, yığılmış / yan yana sütunlar ve grafiğin Excel'deki en-boy oranı. Değerler Excel'in kuralıyla
çizilir: boş hücre çizgide boşluk bırakır, `#N/A` noktası atlanıp çizgi devam eder (Forward sayfasındaki iki
grafikte Excel'deki ayar gereği boşluk kalır), metin sıfır sayılır; sabit sınırı olmayan eksen Excel'in otomatik
kuralını izler. Renkler Excel'deki renk ailesini korur, tonları iki temada da renk körlüğü ayrımı için sınanmıştır.
Fareyle üzerine gelince o noktadaki tüm değerler, "Tablo" düğmesiyle grafiğin verisi (kopyalanabilir) görünür.
DİBS ASW'deki iki grafik XY (dağılım) grafiğidir: her kâğıt kalan vadesine göre bir nokta, yanında Excel'deki
etiketi (Mar28, Eyl35 …), üstünde kesik çizgiyle uydurulan eğri; geçmiş grafiği tarih ekseninde.

**Girdi hücreleri.**

* Sarı alt çizgili hücreler **kişisel** girdidir (valör tarihi, PPK senaryo adımları, hesaplayıcı
  girdileri …). Değiştirdiğiniz hücre yalnızca sizin ekranınızı etkiler, sağ üstünde mavi nokta çıkar.
* Yeşil alt çizgili hücreler **ortak** girdidir (RET faizleri, PPK toplantı tarihleri, ticker listeleri, tatiller …):
  değiştirince herkes görür.
* Düzenleme: çift tık ya da `Enter` / `F2`, doğrudan yazmaya başlamak da olur. `Delete` hücreyi boşaltır
  (formül varsayılanı olan hücre formülüne döner). Sağ tık → "varsayılana dön".
* Yüzde hücrelerine `35,5`, `35,5%` ya da `0,355` yazılabilir (Excel'in otomatik yüzde girişi gibi).
* Sayılar seçili **sayı biçimine** göre okunur (sağ üstteki `1.234,56` düğmesi): Türkçe biçimde `12.345` on iki bin
  üç yüz kırk beştir (Türkçe Excel gibi), İngilizce biçimde `12,345`.

**Kopyala / yapıştır.**

* Fareyle sürükleyip (ya da `Shift` + ok / `Ctrl+A`) seçin, `Ctrl+C` → Excel'e yapıştırın. Her tablonun
  başlığında "Kopyala" düğmesi de var. `Ctrl+Shift+C` sayıları tam hassasiyetle (15 basamak) kopyalar.
* Excel'den kopyaladığınız bloğu bir girdi hücresine tıklayıp `Ctrl+V` ile yapıştırın; girdi olmayan hücreler
  atlanır (kaç hücrenin yazıldığı / atlandığı bildirilir). Blok Excel'deki yerleşimiyle oturur: tablonun
  göstermediği (Excel'de gizli ya da boş olduğu için atlanan) satır ve sütunlar da sayılır, tablonun kendi aralığı
  dışına hiçbir şey yazılmaz. Dashboard'dan kopyalanıp dashboard'a yapıştırılan blok ise ekrandaki hücrelere oturur.
* **Excel'de gizli sütunlar** varsayılan olarak gösterilmez ve kopyalanmaz (ör. YP DİBS'te Bid sütunları): tablo
  Excel'de gördüğünüz haliyle kopyalanır. Tablo başlığındaki "+N gizli sütun" ya da "Yardımcı tablolar" düğmesi
  onları (ve ara hesap tablolarını) açar; açıkken kopyalanan blok Excel'deki sütun düzeniyle aynıdır.
* Alt durum çubuğu seçili hücrenin Excel formülünü, çoklu seçimde toplam / ortalama / adedi gösterir.

**RET faizleri.** Üstteki "RET faizleri" düğmesi: Excel'deki RET tablosunu (yalnızca bid–ask sütunları ya da
vade etiketiyle birlikte) kopyalayıp pencereye `Ctrl+V` ile yapıştırın, "Kaydet". Aynı şey Forward sayfasındaki
TRY RET tablosuna doğrudan yapıştırarak da yapılır. Eğri herkes için geçerlidir, veritabanında saklanır ve her
yükleme (kim, ne zaman, hangi değerler) geçmişe yazılır; geçmişteki bir kayıt tek tıkla geri getirilebilir.

**Senaryolar.** "Senaryolar" düğmesi: o andaki kişisel girdilerinizin tamamını bir isimle kaydeder, yükler, siler.
Senaryolar kullanıcıya özeldir.

**Günlük İşlemler.** Soldaki formdan:

* **USDTRY Forward** — yön, tutar (`10m`, `2,5 mio`, `10.000.000`), valör tarihi; fiyatlama: *RET bid / RET mid /
  RET ask / TRY faizi / Forward kur*. Tarihi yazar yazmaz forward kuru ve **TL tutarı** hesaplanır
  (Forward sayfasının kendi hücreleriyle: valör `Forward!D2`'ye yazılmış gibi). TRY faizi verilirse toplu
  fiyatlama satırının formülü, forward kur verilirse ima edilen TRY faizi kullanılır.
* **OIS** — *Outright / Spread / Fly / FRA*; büyüklük DV01 ($/bp) ya da nominal (TL). Bacaklar OIS_MAIN'in
  kuralıyla boyutlanır (`ROUND(w·DV01·USDTRY/(Annuity·0,0001)/lot)·lot`, fly kanatları ½). Piyasa mid seviyesi ve
  **maliyet** (mid'e göre bp, $ ve TL) otomatik hesaplanır.
* **Tahvil** — enstrüman, yön, tutar, fiyat.

Kaydedilen işlem tüm kullanıcılarda anında görünür (kim, saat kaçta girdi bilgisiyle). Sağda işlem listeleri ve
**pozisyonun maliyeti** (valör / vade / enstrüman bazında net pozisyon, başabaş seviyesi `(A₁R₁−A₂R₂)/(A₁−A₂)` ve
gerçekleşen K/Z — Hesaplayıcılar sayfasındaki "Weighted Average" tablosunun aynısı), altta Excel'deki
Günlük İşlemler sayfasının kendi özet tabloları. Geçmiş günler tarih seçicisinden salt okunur açılır.

**Gün sonu arşivi.** Excel'deki `GunSonuArsivle` makrosunun (sayfayı değer olarak `Blotter_yyyy.aa.gg.xlsx`
dosyasına kaydedip listeleri temizleyen düğme) karşılığı: "Gün sonu arşivi (.xlsx)" seçili günü aynı adla indirir.
Dosyanın ilk sayfası Günlük İşlemler sayfasının Excel'deki yerleşimiyle, yalnızca değerlerden oluşan kopyasıdır
(makronun kaydettiği dosyayla aynı hücre adresleri); ikinci sayfada kimin, ne zaman, hangi işlemi girdiği ve
pozisyon maliyetleri vardır. Listeleri temizlemek gerekmez: her günün defteri ayrıdır, yeni gün boş başlar ve
geçmiş günler istenildiği zaman yeniden indirilebilir.

### Dashboard'un kendi ekledikleri

Bunlar Excel dosyalarında yok; ama dashboard'a "kod" olarak değil **Excel formülü** olarak eklendi
(`tto/extras.py`, kitap yüklenirken modele iki sayfa: `EK_FWD`, `EK_XAU`). Aynı motor hesaplar, girdilere ve canlı
veriye aynı şekilde bağlıdır, durum çubuğunda formülü görünür, Excel'e kopyalanabilir.

**Forward kotasyon matrisi — OIS + spread, bid ve ask ayrı** (Masa sayfası, "Forward fiyatlama"nın altında).
Vadeler 1M / 2M / 3M / 6M / 9M / 12M (valör formülle gelir, üzerine yazılabilir) ve dört serbest tarih.
"Tümü" satırına bid ve ask için **ayrı** OIS spread'i (bp) yazılır; bir vadenin kendi spread'i o satıra yazılır
(silince genele döner). Her satırda: valör, gün, spot bid / ask, **puan bid / ask**, forward bid / ask, OIS %,
TRY bid / ask %, USD %, günlük puan, RET bid / ask % ve aynı valörde RET'le çıkan puana fark.
OIS eğrisi listeden seçilir (MPC ima, S1–S3, Ağırlıklı, Bootstrap, TLREF sabit) ve Masa'daki "Tarih arası faiz"
bloğunun iskonto faktörleriyle aynıdır: aynı tarih ve spread'de iki blok aynı TRY faizini verir.
`Fwd bid = spot bid·(1+TRY bid·g/360)/(1+USD·g/360)`, ask tarafı spot ask ve TRY ask ile.
Altındaki **Puan → OIS spread** tablosu tersini yapar: elle verdiğiniz bid / ask puanının ima ettiği TRY faizini ve
OIS'e göre kaç bp olduğunu gösterir.

**Altın — forward'ı lease faizinden** (VİOP sayfası, altın tablolarının altında). Excel altın forward'ını
`BFXFORWARD("XAUUSD"; tarih; …)` ile alıyor; bu fonksiyonun API karşılığı olmadığı için canlıda bu hücreler boş
kalıyordu. Artık forward taşıma maliyetinden hesaplanır:
`XAUUSD fwd = spot·(1+USD·g/360)/(1+lease·g/360)` (USD = VİOP sayfasındaki USD OIS eğrisi, lease = eğriden gün
bazında doğrusal, uçlarda sabit).

* *Spot ve kaynak:* spot ticker'ı (`XAU Curncy`), manuel spot (boşsa Bloomberg), spot valörü ve kaynak seçimi:
  **Otomatik** (spot ve lease varsa lease, yoksa `BFXFORWARD`), **Lease**, **BFXFORWARD**.
* *Lease eğrisi:* 1W … 12M için **ticker hücresi** (Bloomberg'den okunur; alan adı da hücrede, varsayılan
  `PX_LAST`) ve **Manuel %** (doluysa ticker'ın önüne geçer). Faizi olmayan vade atlanır.
  Lease ticker'ları boş gelir: Bloomberg'deki altın lease faizi ticker adları doğrulanamadı, bir kez yazmanız
  yeterli (ortak girdidir, saklanır).
* *XAUUSD forward:* üç VİOP XAUTRY kontratı, üç VİOP XAUUSD kontratı, `Forward!D2` tarihi ve iki serbest tarih için
  lease forward'ı, `BFXFORWARD`, kullanılan değer ve `BFXFORWARD`'ın ima ettiği lease. **VİOP XAUTRY BID / ASK**
  tabloları, VİOP XAUUSD tablosu ve Forward sayfasındaki altın şeridi (`VIOP!M58:O58`, `S58:U58`, `M68:O68`,
  `Forward!I29:J29`) buradaki "kullanılan" değeri okur.
* *Belli faizle fiyat* ("Interest 2 SP"nin altın karşılığı): her XAUTRY kontratı için TRY %, USD % ve isteğe
  bağlı lease % yazılır → USDTRY forward, swap puanı, **teorik XAUTRY (TL/gr) = XAUUSD fwd · USDTRY fwd / 31,1035**
  ve VİOP bid / ask'a fark. TRY % varsayılanı aynı vadeli USDTRY VİOP kontratının ima faizidir.

Kayıtlı veri modunda altın spotu ve lease kaydı olmadığından forward Excel'in kaydettiği `BFXFORWARD` değerlerinden
okunur (sayfalar Excel'le aynı kalır); spot ve lease'i elle yazınca lease hesabı devreye girer.

**O/N karşılıkları.** Borsa Swap tablolarında BID / ASK ima faizinin yanında O/N karşılığı
(`360·((1+r·gün/360)^(1/gün) − 1)`) ve günlük puan sütunları; Günlük İşlemler'deki forward listesinde her işlemin
TRY faizinin O/N karşılığı (sayfanın kendi F sütunu) ve gün sonu arşivinde aynı sütun.

### Borsa Swap ve DİBS ASW

* **Borsa Swap** (`BBG_Borsa_Swap.xlsx`): BIST swap pazarının T+0 ve T+1 kotaları (1–400 gün; alış / satış puanı ve
  miktarları) → USD OIS ile ima edilen TRY basit faizi. Yalnızca kotası olan vadeler listelenir (Excel'deki `FILTER`
  formülleri). Ham kota tabloları yardımcı tablolardadır.
* **DİBS ASW** (`DIBS_ASW.xlsx`): 50 kâğıtlık izleme listesi (ISIN, kaynak, manuel fiyat), TLREF OIS eğrisiyle
  iskonto edilmiş bugünkü değer, ASW (bp), uydurulan eğriye göre ucuz / pahalı ve üç kâğıdın ASW geçmişi.
* Bu iki dosya Bloomberg bağlantısı olmadan kaydedildiği için içlerinde **kayıtlı piyasa verisi yok**. Kayıtlı
  veri modunda: ASW sayfası kâğıt bilgilerini ve fiyatları TTO dosyasının aynı günkü kayıtlarından alır (ASW
  değerleri TTO'daki DİBS RV tablosuyla 0,05 bp içinde aynıdır; geçmiş kısmı yalnızca canlıda dolar); Borsa Swap
  sayfasındaki kotalar TTO'daki RET eğrisinden türetilmiş **örnek veridir** (sayfanın üstünde yazar).
  Canlı modda ikisi de doğrudan Bloomberg'den beslenir.

### Excel'deki diğer özelliklerin karşılığı

| Excel'de | Dashboard'da |
|---|---|
| Masa sayfasındaki 30 köprü | "Kısayollar" çubuğu: sayfa + tablo |
| Gizli sütunlar (YP DİBS D:E, VİOP C/I/J, DİBS RV yardımcı sütunları) | Gösterilmez; "+N gizli sütun" / "Yardımcı tablolar" ile açılır |
| Daraltılmış satır grupları (OIS'te tüm spread/fly/FRA listeleri, VİOP matrisleri) | Kapalı başlayan paneller (▸ ile açılır, tercih hatırlanır) |
| Dondurulmuş bölmeler | Başlık satırları ve dondurulmuş sütunlar (DİBS RV A:C, USD A) kaydırırken yerinde kalır |
| Hücre yorumları (OIS parametreleri, VİOP) | Hücrenin köşesinde kırmızı işaret, üzerine gelince metin |
| Açılır listeler (veri doğrulama; sabit ya da bir aralıktan okunan) | Hücrede seçenek menüsü |
| Koşullu biçimler: kural, renk skalası, veri çubuğu | Aynı kurallarla hücre rengi / ısı haritası / çubuk |
| Ivır Zıvır sayfasındaki resim | Sayfanın sonunda resim paneli |
| `GunSonuArsivle` makrosu | "Gün sonu arşivi (.xlsx)" |

---

## Excel ile birebirlik nasıl doğrulandı

**Yaklaşım.** Çalışma kitapları içe aktarılır (`models/*.json.gz`: formüller, sabitler, biçimler, koşullu
biçimler, grafik tanımları, gizli satır/sütunlar, dondurulmuş bölmeler, yorumlar, köprüler, resimler) ve formüller `tto/xl` altındaki motorla çalıştırılır: Excel'in işlem önceliği, örtük kesişim,
dizi formülleri, `LET`, Türkçe yerel ayar (metin tarihler, `TEXT`), 15 basamak karşılaştırma, yarım-yukarı
yuvarlama, soldan sağa toplama, son `+`/`−` işlemindeki sıfıra yapıştırma gibi davranışlarıyla. Bir hücre
değişince yalnızca ona bağlı hücreler yeniden hesaplanır; her kullanıcının girdileri kendi katmanında tutulur.

**Sonuçlar** (hepsi `pytest` ile tekrar üretilebilir):

| Kontrol | Sonuç |
|---|---|
| Her formül, Excel'in kaydettiği öncül değerlerle hesaplanıp Excel'in kaydettiği sonuçla karşılaştırıldı | 164.002 formülün 156.476'sı aynı (%95,41). Kalanlar dosyanın kendi içinde tutarsız olan **bayat kayıtlar**: dosya son hesaplamadan sonra düzenlenmiş (ör. `Forward!H126` formülü Excel'de hiç hesaplanmamış, ona bağlı `J18`'in eski değeri duruyor). |
| Bağımsız hesaplayıcı: LibreOffice aynı dosyayı baştan hesapladı, motorun tam yeniden hesabıyla karşılaştırıldı | TRY: 186.585 hücrenin 186.283'ü 1e-7 göreli toleransla aynı; **13 sayfa birebir** (Forward 1.556 / 1.556, VİOP, DİBS RV, C&R, Günlük İşlemler, Hesaplayıcılar …). Farklı 302 hücrenin tamamı Motor'daki eğri çözücüsünün (koşul sayısı ~3·10⁶ olan matris tersi) devamında ve en az 4 anlamlı basamak aynı. USD: 4.277 / 4.277 (1e-9). |
| Forward hesabı ayrıca elle yazılmış bağımsız bir formülle (faiz paritesi, basit ACT/360, gün bazında doğrusal interpolasyon) 11 valör için sınandı | 1e-13 göreli hassasiyetle aynı; dosyanın kendi valöründe Excel'in kayıtlı outright ve swap puanlarıyla 1e-13 aynı. |
| Canlı veri hattı: sahte bir Bloomberg sunucusuyla *istek → yanıt → geçersiz kılma → yeniden hesap* zinciri, aynı veriyle doğrudan hesapla karşılaştırıldı | Dört kitaptaki 220.337 formül hücresinin **tamamı** aynı (tick öncesi ve sonrası). |
| DİBS ASW kitabı, TRY kitabındaki DİBS RV tablosuyla (aynı kâğıtlar, aynı gün, iki ayrı dosya) karşılaştırıldı | Sabit kuponlu ve iskontolu 15 kâğıdın ASW'si 0,05 bp içinde aynı (RV tablosu değeri 0,1 bp'ye yuvarlıyor). |
| Dashboard'un ekledikleri bağımsız kapalı formüllerle sınandı | Forward matrisi: yedi eğrinin her biri Masa'daki bloğun TRY faiziyle 1e-12 aynı; puan → spread tersi 1e-7 bp. Altın: taşıma maliyeti formülü ve lease interpolasyonu 1e-13. |

Motor'daki çözücü farkı ekranda görünen basamakların çok altındadır; ancak "son basamağına kadar aynı" iddiası
yalnızca çözücüye bağlı olmayan sayfalar için geçerlidir (Excel'in kendisi de bu matriste tam çözümden ~1e-9
uzaktadır).

---

## Bloomberg

| Excel'deki çağrı | Dashboard'da |
|---|---|
| `BDP` anlık alanlar (BID, ASK, MID, PX_LAST, LAST_PRICE, PX_BID/ASK/MID, HIGH, LOW, BID_SIZE, ASK_SIZE) | İlk değer `ReferenceDataRequest`, sonrası `//blp/mktdata` aboneliğiyle akar (günlük veri limitini tüketmez) |
| Diğer `BDP` alanları ve override'lı `BDP` | `ReferenceDataRequest`; alan türüne göre 1 dk – 6 saat arayla yenilenir |
| `BDH` | `HistoricalDataRequest` (`Days`, `Fill`, `Per`, `Dates`, `Sort` seçenekleri) |
| `BDS` | toplu alan için `ReferenceDataRequest` |
| `BInterpol` | doğrusal interpolasyon (Excel'deki değerlerle doğrulandı) |
| `BFXFORWARD` | **API karşılığı yok** → `#N/A BFXFORWARD` (aşağıya bakın); altın forward'ı bunun yerine lease faizinden hesaplanır |
| `RtGet` (Refinitiv) | Bloomberg fonksiyonu değil → `#N/A RTGET` |

Bağlantı **Desktop API** içindir (terminalin açık olduğu makinede `localhost:8194`); B-PIPE / SAPI gibi sunucu
ürünlerinin yetkilendirme adımı yazılmadı. Abonelikle hiç değer gelmeyen fiyat alanları (ör. işlem görmeyen bir
kağıt) `--price-poll` (120 sn) sonra sorguyla istenir; yanıt değişmedikçe aralık ikiye katlanarak 30 dakikaya
(hiç değeri olmayan alanlarda 1 saate) kadar uzar, değer değişince yeniden 120 sn'ye iner, geçersiz ticker bir
daha sorulmaz. Böylece Borsa Swap sayfasının kotası olmayan yüzlerce vadesi günlük veri limitini tüketmez.

Henüz gelmemiş bir değer Excel'deki gibi `#N/A Requesting Data...` görünür, yanıt gelince bağlı hücreler yeniden
hesaplanır. Sunucu açılırken kitapların kullandığı tüm kalemler önceden istenir (dört kitapla ~4.300 kalem ve
~1.000 abonelik; aboneliklerin 800'ü Borsa Swap sayfasının izlediği `TYB…D BFX0 / BFX1` ticker'larıdır — Excel'de
de aynı sayıda kota izlenir).
BDP tarihleri masadaki Excel'de olduğu gibi `4.11.2026` biçiminde metin olarak döner. Günlük referans/geçmiş veri
isteği sayısı sayılır; `--max-hits` (varsayılan 400.000) aşılırsa yalnızca akan veriler güncellenmeye devam eder ve
rozet uyarır. Bağlantı koparsa otomatik yeniden bağlanılır.

> **Dürüst not:** bu ortamda Bloomberg terminali olmadığı için canlı katman gerçek terminale karşı
> **çalıştırılamadı**; `blpapi` arayüzünü taklit eden bir sahte modülle (`tests/fake_blpapi.py`) sınandı. İlk
> canlı kullanımdan önce `python -m tto check-bloomberg` çalıştırın ve birkaç hücreyi Excel'le karşılaştırın.

---

## Canlıya geçmeden önce

* **Manuel spot:** kaydedilmiş dosyada VİOP sayfasındaki "Manuel SP" hücreleri dolu (üst şeritte *Spot kaynağı:
  MANUEL* yazar). Bloomberg spotunu kullanmak için VİOP sayfasında bu iki hücreyi (`AA9`, `AA10`) silin; hücreler
  ortak girdidir, bir kişinin silmesi yeter.
* **RET faizleri:** dosyadaki RET eğrisi 03.11.2026 tarihlidir. Her gün "RET faizleri" penceresinden güncel eğriyi
  yapıştırın; bugün yüklenmediyse düğmenin yanında sarı nokta durur.
* **Altın lease ticker'ları:** VİOP sayfasındaki "Altın · lease eğrisi" tablosuna Bloomberg'deki lease faizi
  ticker'larını bir kez yazın (ya da faizleri "Manuel %" sütununa girin). Boşken altın forward'ı `BFXFORWARD`'a
  düşer; o da canlıda yoktur, yani VİOP XAUTRY tabloları lease gelene kadar `#N/A` kalır.
* `python -m tto check-bloomberg` ile bağlantıyı sınayın, ardından birkaç hücreyi Excel'le karşılaştırın.

## Bilinen sınırlamalar

* **`BFXFORWARD`** (Forward sayfasında çapraz forward, Masa'da USD/EUR dışı döviz): Bloomberg'in Excel'e özel bir
  fonksiyonu, API'de yok. Canlı modda bu hücreler `#N/A` olur; USDTRY / EURTRY forward tabloları bundan
  etkilenmez. `--bfx approx` ile Bloomberg'in `FWD_CURVE` verisinden gün bazında doğrusal interpolasyonla
  **yaklaşık** bir değer üretilir (Excel'le birebir olma garantisi yoktur, doğrulanmadı). Altın forward'ı artık
  buna bağlı değildir (lease faizinden hesaplanır) — ancak lease ticker'ları kullanıcıdan beklenir: Bloomberg'deki
  ticker adları doğrulanamadığı için hücreler varsayılan olarak boştur.
* **Borsa Swap ve DİBS ASW** dosyalarında kayıtlı piyasa verisi yok: kayıtlı veri modunda Borsa kotaları örnek
  veridir, ASW geçmişi boştur. İkisi de gerçek değerlerini ancak canlı modda gösterir ve canlıda henüz sınanmadı.
* **USDTRY IYIX** sayfası Refinitiv `RtGet` kullanıyor; canlı modda `#N/A`.
* **Kayıtlı veri modu** piyasa verisini ve "bugün"ü dosyanın son hesaplandığı güne (03.11.2026) sabitler;
  Günlük İşlemler ise gerçek takvim gününe yazılır.
* **Giriş şifresizdir** (istenen: yalnızca isim). Porta ağdan erişebilen herkes kullanabilir; masanın güvenilen
  ağı dışına açmayın.
* Tek süreçtir; hesaplar tek bir motor iş parçacığında sıraya girer. Canlı bir tick'ten sonra en ağır sayfaların
  yenilenmesi ~0,3–0,5 sn sürer.

---

## Testler

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest tests
```

Bloomberg ve ağ gerekmez (~4 dk). 556 test:

| Dosya | Kapsam |
|---|---|
| `test_xl_functions.py`, `test_xl_engine.py`, `test_numfmt.py` | Excel semantiği (operatörler, yuvarlama, tarih, metin, arama, koşullu toplamlar, matris, `LET`, `FILTER` ve taşma / `#SPILL!`, `AGGREGATE`, sıfıra yapıştırma), bağımlılık takibi, kullanıcı katmanları, sayı biçimleri |
| `test_parity.py` | Excel'in kayıtlı değerleriyle parite (sayfa bazında eşikler) |
| `test_reference.py` | LibreOffice'in baştan hesapladığı değerlerle karşılaştırma (`tests/data/lo_*.json.gz`) |
| `test_forward.py` | Forward: bağımsız kapalı formül, Excel'in kayıtlı değerleri, işlem girişindeki fiyatlamanın sayfayla aynılığı |
| `test_blotter.py` | Outright / spread / fly / FRA bacakları, maliyet, ortak işlem defteri, forward'ların O/N karşılığı, Excel özet tabloları |
| `test_charts.py` | Grafik tanımlarının Excel'den alınışı (renk, çizgi, işaretçi, eksen sınırları, tarih ekseni, bid–ask kutuları), değerlerin Excel kuralıyla çizime verilişi (boşluk, `#N/A`, metin) ve XY grafikleri (nokta etiketleri, sayı / tarih ekseni) |
| `test_extras.py` | Dashboard'un ekledikleri: forward kotasyon matrisi (yedi eğri Masa bloğuyla aynı, bid / ask ayrı spread, puan → spread tersi), altın (taşıma maliyeti kapalı formülü, lease interpolasyonu, kaynak seçimi, Bloomberg ticker'ları, canlıda `BFXFORWARD`'sız çalışma, VİOP / Forward hücrelerinin beslenmesi, "belli faizle fiyat"), Borsa O/N karşılıkları ve örnek kotaların RET'e eşitliği, ASW ↔ DİBS RV |
| `test_workbook_features.py` | Gizli sütunlar, dondurulmuş bölmeler, yorumlar, veri çubukları, kısayollar, resim, aralıktan okunan açılır listeler, Excel yerleşimiyle yapıştırma, gün sonu arşivi (.xlsx yazıcı dahil), hücreden okunan başlık / notlar, şifreli dosyanın içe aktarılması |
| `test_service.py`, `test_server.py`, `test_store.py`, `test_inputs.py`, `test_config_cli.py` | Kişisel/ortak girdiler, senaryolar, RET, kalıcılık, HTTP API, yapıştırma/ayrıştırma, port kuralı |
| `test_views.py` | Sayfa tanımları: her panel ve girdi gerçek hücrelere bakıyor, **her formül bir tabloda** (dört kitap + ekler, sıfır istisna), her girdi hücresine sayfasından ulaşılıyor, Forward'daki elle hesaplama araçları (USDTRY ve EURTRY) görünür tablolarda |
| `test_bloomberg.py` | `blpapi` katmanı (sahte sunucuyla): gruplama, abonelik (kota büyüklükleri dahil), sessiz kalan kotaların giderek seyrek sorulması, hata metinleri, BDH/BDS, limit koruması, canlı–doğrudan eşdeğerlik (dört kitap) |
| `test_e2e.py` | Gerçek tarayıcıda (Playwright/Chromium) 116 kontrol: giriş, düzenleme, Excel kopyala/yapıştır, RET, senaryo, işlem girişi, iki kullanıcı arası canlı paylaşım, grafiklerin çizimi (renk, eksen, tarih ekseni, ipucu, XY grafiği), kısayollar, gizli / dondurulmuş sütunlar, arşiv indirme, forward kotasyon matrisi, altın lease girişi ve VİOP tablosunun değişmesi, Borsa Swap, DİBS ASW, tüm sayfalar. Node.js + Playwright yoksa atlanır. |

LibreOffice referansını yeniden üretmek (LibreOffice kuruluysa):

```bash
python tools/lo_reference.py models/tto.json.gz --work /tmp/lo_tto --tol 1e-7 --golden tests/data/lo_tto.json.gz
```

---

## Excel dosyası değişince

Yeni dosyayı `workbooks/` altına koyup modeli yeniden üretin, sunucuyu yeniden başlatın:

```bash
python -m tto import-workbook workbooks/TTO_v8_5.xlsm --id tto
```

```bash
python -m tto import-workbook workbooks/USD_SOFR_FOMC.xlsx --id sofr
```

```bash
python -m tto import-workbook workbooks/DIBS_ASW.xlsx --id asw
```

`BBG_Borsa_Swap.xlsx` açma şifresiyle kayıtlı; şifre komuta (ya da `TTO_WORKBOOK_PASSWORD` ortam değişkenine)
verilir, dosya yalnızca bellekte çözülür. Bunun için bir kez `pip install msoffcrypto-tool` gerekir:

```bash
python -m tto import-workbook workbooks/BBG_Borsa_Swap.xlsx --id borsa --password <açma şifresi>
```

TTO dosyası değiştiyse, kayıtlı veri modunda Borsa ve ASW sayfalarını besleyen dosyaları da yenileyin
(`tto/data/replay_borsa.json`, `replay_asw.json`):

```bash
python tools/make_replay_quotes.py
```

Sayfa düzeni (hangi aralık hangi panelde, hangi hücreler girdi, kişisel mi ortak mı) `tto/views/*.json`
dosyalarındadır; satır/sütun eklenip çıkarıldıysa ilgili aralıkları güncelleyin (`python -m pytest tests/test_views.py`
tutarlılığı denetler). Yeni bir Excel fonksiyonu kullanılırsa `test_parity.py` adını söyler.

Dashboard'un kendi ekleri (`tto/extras.py`) dosyadaki belirli hücrelere dayanır (Masa'daki iskonto faktörleri,
VİOP'taki `BFXFORWARD` hücreleri, Borsa tablosunun başlıkları). Dosyanın düzeni değişip bir ek artık uymuyorsa
sunucu yine açılır; yalnızca o ek dışarıda bırakılır, nedeni başlangıçta günlüğe ve `/api/status` yanıtındaki
`left_out` alanına yazılır.

## Proje yapısı

```
tto/xl/            Excel formül motoru (tokenizer, parser, derleyici, fonksiyonlar, sayı biçimleri, içe aktarıcı)
tto/marketdata/    Bloomberg (blpapi) ve kayıtlı veri sağlayıcıları
tto/extras.py      dashboard'un kendi eklediği hesaplar (Excel formülü olarak: EK_FWD, EK_XAU, Borsa O/N)
tto/service.py     uygulama servisi (sayfalar, girdiler, senaryolar, RET, işlem defteri)
tto/blotter.py     forward fiyatlama, OIS strateji bacakları, pozisyon maliyeti
tto/xlsx.py        gün sonu arşivi için küçük .xlsx yazıcı (yalnızca değerler ve biçimler)
tto/server.py      HTTP API + canlı güncelleme (server-sent events)
tto/store.py       SQLite (kullanıcılar, girdiler, senaryolar, RET geçmişi, işlemler)  →  data/tto.db
tto/views/         sayfa tanımları
tto/data/          kayıtlı veri modunda kullanılan ek kotalar (replay_*.json)
tto/static/        arayüz (derleme gerektirmeyen ES modülleri, kendi SVG grafikleri)
models/            içe aktarılmış çalışma kitapları        workbooks/   kaynak Excel dosyaları
tools/             parite, LibreOffice referansı, içe aktarma, kayıtlı veri kotaları
tests/             test paketi
```

Yedekleme için `data/tto.db` dosyasını kopyalamak yeterlidir.
