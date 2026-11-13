# TTO Masa — TRY ve USD faiz masası dashboard'u

`TTO_v8_5.xlsm` (TRY faiz masası: OIS/PPK, forward, VİOP, DİBS RV, DV01 …), `USD_SOFR_FOMC.xlsx`
(USD OIS / FOMC patikası), `BBG_Borsa_Swap.xlsx` (Borsa İstanbul swap kotaları → ima TRY faizi) ve `DIBS_ASW.xlsx`
(DİBS asset swap spread'leri, TLREF OIS eğrisine göre) çalışma kitaplarının tek bir web dashboard'unda
birleştirilmiş hâli. Piyasa verisi Bloomberg'den `blpapi` ile canlı gelir; Bloomberg yoksa Excel dosyasında
kayıtlı son veriyle çalışır.

* **Port:** varsayılan `1057`. Masadaki makinede dolu olan `5000` ve `5001` portları **hiçbir koşulda
  kullanılmaz** (program reddeder).
* **Excel ile birebir:** formüller yeniden yazılmadı; çalışma kitaplarının kendi formülleri bir Excel formül
  motoruyla aynen çalıştırılıyor. Doğrulama sonuçları [aşağıda](#excel-ile-birebirlik-nasıl-doğrulandı).
* **İsimle giriş:** her kullanıcı ismini yazıp girer; kişisel girdileri ve senaryoları o isimle saklanır.
* **Ortak veriler:** RET faizleri ve Günlük İşlemler bir kişi kaydedince herkeste anında görünür ve sunucu
  yeniden başlasa da kalır.
* **Excel ⇄ dashboard kopyala / yapıştır:** tablolar Excel'e, Excel'deki bloklar girdi hücrelerine doğrudan.
* **Hiçbir formül eksik değil:** dört kitabın her sayfasındaki her formül ve değer, sayfasının bir tablosundadır
  (görünen tablo ya da "Yardımcı tablolar"); bunu bir test denetler.
* **Excel'de olmayan ekler** de Excel formülü olarak yazıldı: bid / ask için ayrı OIS spread'li forward kotasyon
  matrisi, altın forward'ının altın swap faizinden (XAUSR) hesabı, O/N karşılıkları
  ([aşağıda](#dashboardun-kendi-ekledikleri)).
* **Geçmiş:** TRY OIS, offshore ve DİBS için **gün sonu matrisi** (1 gün / 1 hafta / 1 ay değişim), her PPK
  toplantısının **fiyatlama geçmişi** (zaman serisi, bir yıl geriye; yapılan toplantılar da saklanır) ve
  **Ayarlar**'da toplantı takvimi ([aşağıda](#gün-sonu-matrisi-ppk-fiyatlama-geçmişi-ve-toplantı-takvimi)).

---

## Hızlı başlangıç

### Hiçbir şey kurmadan

Bilgisayarda **Python 3.8 ya da üstü** olması yeterlidir; `pip install` da Git de gerekmez.

1. GitHub'da (giriş yapmış olarak) repo sayfası → yeşil **Code** düğmesi → **Download ZIP**; zip'i bir klasöre açın.
   Repo private kalabilir. ZIP inmiyorsa ya da ZIP'i taşıyamıyorsanız
   [tek dosyalık kurulum](#zip-inmiyorsa-tek-dosya) aynı klasörü üretir.
2. Klasördeki `run.bat`'a çift tıklayın — ya da o klasörde bir komut penceresinde:

```bash
python -m tto
```

3. Tarayıcıdan `http://localhost:1057` (başka bilgisayardan `http://<makine-adı>:1057`).

Web sunucusunun ihtiyaç duyduğu paketler (Starlette, uvicorn ve bağımlılıkları) `vendor/` klasöründe gömülü gelir
ve kurulmadan, doğrudan oradan kullanılır; açılış satırında `web paketleri: gömülü kopya (vendor/py310)` yazar
(ayrıntı: [vendor/README.md](vendor/README.md)). Bu yol Python 3.8, 3.9, 3.10, 3.11, 3.12 ve 3.13'te, hiçbir paket
kurulu olmayan bir Python'la denendi.

* **Python var mı?** Komut penceresinde `python --version` (ya da `py --version`). Hiç yoksa python.org'daki
  *Windows embeddable package (64-bit)* zip'i de kurulum istemez: içindekileri proje klasörüne açıp
  `python.exe -m tto` çalıştırılır. Bu yol bu ortamda denenemedi.
* **Güncelleme:** yeni ZIP'i indirip eskisinin üzerine açın; `data` klasörüne dokunmayın (kullanıcılar, senaryolar,
  RET geçmişi ve işlem defteri orada).
* **Güvenlik duvarı sorusu** çıkarsa ve yalnızca kendi bilgisayarınızdan kullanacaksanız `python -m tto --host 127.0.0.1`
  ile açın; soru çıkmaz.
* **Canlı Bloomberg verisi** için o Python'da `blpapi` paketi bulunmalıdır (`python -c "import blpapi"` hata
  vermiyorsa vardır). Yoksa dashboard kayıtlı veriyle açılır. Kurulamıyorsa, kurulum gerektirmeyen yol
  [vendor/README.md](vendor/README.md) içinde (`vendor/local`).

### ZIP inmiyorsa: tek dosya

Bazı ağlarda GitHub'ın "Download ZIP"i engellenir, e-posta servisleri de içinde `.bat` / `.js` bulunan arşivleri
kabul etmez (Gmail: *"yürütülebilir dosyalara ve arşivlere yönelik politika"*). Dosyalar tek tek inebiliyorsa
[`kurulum/tto_kur.py`](kurulum/tto_kur.py) yeter: dashboard'un çalışması için gereken her şeyi (program, içe aktarılmış
çalışma kitapları, web paketleri) taşıyan **tek bir düz metin dosyası** (~4,7 MB).

1. Repoda `kurulum/tto_kur.py` → **Download raw file**.
2. İndirdiğiniz yerde:

```bash
python tto_kur.py
```

Yanına `ratetradingtto` klasörünü açar (ZIP'ten çıkanla aynı program; testler ve kaynak Excel dosyaları hariç) ve
dashboard'u başlatmayı sorar. Sonraki açılışlarda o klasördeki `run.bat`. İnternetten bir şey indirmez, bir şey kurmaz.

* **Güncelleme:** yeni `tto_kur.py`'yi indirip aynı yerde yeniden çalıştırın; değişen dosyalar yenilenir, artık
  olmayanlar silinir, `data` klasörüne ve `vendor/local`'a dokunulmaz.
* **E-postayla:** dosyanın adını `tto_kur.txt` yapıp ekleyin; içerik düz metindir ve `python tto_kur.txt` aynı şekilde
  çalışır.
* Yarım inmiş ya da yolda bozulmuş dosya açılmaz, ne olduğunu söyler (içeriğin özeti dosyanın içindedir).
* Dosya `python tools/make_bundle.py` ile üretilir; repodaki kopyanın kodla aynı olduğunu bir test denetler
  (`python tools/make_bundle.py --check` de söyler). Ayrıntı: [kurulum/README.md](kurulum/README.md).

### Kurulum yapılabilen bir makinede

```bash
pip install -r requirements.txt
```

```bash
python -m tto
```

Kurulu paketler varsa gömülü kopyalar yerine onlar kullanılır. Test paketi Python 3.13 ve 3.8'de koşturuldu.

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

Diğer seçenekler: `--port 1060` (5000/5001 hariç), `--host 127.0.0.1`, `--data-dir D:\tto-data` (veritabanı klasörü),
`--bbg-host`, `--bbg-port 8194`, `--tick 2` (ekran yenileme, sn), `--no-stream`, `--price-poll 120`, `--max-hits 400000`,
`--bfx approx`, `--history-refresh 900` (tarihçenin canlıda güncellenme aralığı, sn), `--no-history` (tarihçeyi arka
planda güncelleme), `--bbg-inprocess`, `--bbg-interval`, `--bbg-queue` (üçü için aşağıda
[Bloomberg oturumu ayrı bir süreçte](#bloomberg-oturumu-ayrı-bir-süreçte)). Aynı ayarlar `TTO_PORT`, `TTO_HOST`,
`TTO_MODE`, `TTO_DATA_DIR`, `TTO_BBG_HOST`, `TTO_BBG_PORT` ortam değişkenleriyle de verilebilir.

---

## Kullanım

**Sayfalar.** Masa, OIS · PPK, Forward, VİOP, Borsa Swap, Carry & Roll, TM OIS, DİBS RV, DİBS ASW, Manuel Tahvil,
Bulk Bond, YP DİBS, DV01 Risk, USD · FOMC, Hesaplayıcılar, USDTRY IYIX, Motor. Ek olarak **Günlük İşlemler** ve
herhangi bir sayfanın herhangi bir aralığını (formülüyle birlikte) gösteren **Sayfa gezgini**. Excel'deki "MOBIL MK"
ve "Ivır Zıvır" sayfalarının dashboard'da sayfası yoktur (masa kullanmıyor); hücreleri hesaplanmaya devam eder ve
Sayfa gezgini'nden bakılabilir. Masa sayfasının üstündeki **Kısayollar** Excel'deki köprülerin aynısıdır: tıklayınca
ilgili sayfa açılır ve köprünün gösterdiği tablo ekrana gelir.

**Sekmeler.** Excel'de bir sayfada onlarca tablo yan yana ve alt alta durur; aradığını bulmak için sağa sola
kaydırmak gerekir. Dashboard'da çok tablolu sayfalar **sekmelere** ayrılmıştır ve bir seferde bir grup tablo
görünür:

| Sayfa | Sekmeler |
|---|---|
| Forward | **Hesaplayıcılar** (Interest 2 SP, SP 2 Interest, all-in, O/N karşılığı, basit ↔ bileşik, forward faiz, tarih yardımcısı …) · Forward fiyatları · RET · Toplu fiyatlama · Eğriler · Offshore · Ticker'lar |
| VİOP | Kontratlar · **Hesaplayıcılar** (USDTRY kontratları, VİOP XAUTRY) · Altın · Takvim spread matrisleri · Baz · Eğriler |
| Masa | Genel bakış · Forward fiyatlama · Faiz · PPK · VİOP · Sinyaller · Makro |
| OIS · PPK | Kotalar · Hesaplayıcılar · PPK ima · En iyi işlemler · Tüm listeler |
| Hesaplayıcılar | Swap puanı ↔ faiz · Faiz çevirici · Maliyet · DV01 · Tahvil · diğer |
| DV01 Risk, USD · FOMC, Carry & Roll, Motor | konularına göre 3–4 sekme |

Forward sayfası **hesaplayıcılarla açılır**; hepsinin okuduğu valör tarihi (ve spot) sekmelerin üstünde sabit durur.
Son açtığınız sekme hatırlanır. "Tümü" sekmesi sayfanın bütün tablolarını bölüm başlıklarıyla alt alta gösterir;
sayfadaki arama kutusu **bütün sekmelerde** arar. Bir kısayol ya da arama sonucu başka sekmedeki bir tabloyu
gösteriyorsa o sekme kendiliğinden açılır. Üst çubuktaki **"Tablo / hesaplayıcı bul" (Ctrl+K)** kutusu bütün
sayfalardaki tabloları adıyla arar ("interest", "ret", "xautry", "dv01" …); `Enter` ile tabloya gidilir.
Hesaplayıcılar sayfasındaki aynı adlı kopyalar ("Interest 2 SP" × 5) neyin hesaplayıcısı olduklarıyla adlandırıldı
(USDTRY – tarih ve spot üst banttan, EURTRY, serbest parite 1–4 …).

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
* İnce alt çizgili hücreler **otomatik dolan** girdilerdir: değeri piyasadan ya da başka bir hücreden gelir (bir
  hesaplayıcının tarihleri, spotu, USD / EUR faizi; Forward sayfasının üstündeki spot ve spot valörü; VİOP altın
  hesaplayıcısındaki spotlar, XAUUSD forward'ı ve VİOP fiyatı). Üzerine kendi değerinizi yazabilirsiniz; hücre mor
  olur ve `Delete` ile piyasadaki değere döner. Bloomberg'den gelmeyen bir veri olduğunda hesap böyle sürdürülür.
* **Elle değer.** Excel'de her hücrenin üzerine yazılabilir; dashboard'da bu, yanlışlıkla bir formülü silmemek için
  bir **mod**dur. Sayfanın üstündeki "Elle değer" düğmesi açıkken o sayfadaki *her* hücreye – formül olanlara da –
  kendi değerinizi yazabilirsiniz (gelmeyen bir kota, denemek istediğiniz bir seviye). Değer yalnızca sizin
  görünümünüzü değiştirir, hücre mor işaretlenir, sayfanın üstünde "N formül yerine elle değer · formüle dön"
  düğmesi çıkar; hücreyi silmek (ya da o düğme) formülü geri getirir. Mod tarayıcı sekmesi açık kaldıkça bütün
  sayfalarda geçerlidir; yeni oturum kapalı başlar. Senaryolar bu değerleri de saklar.
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

**RET faizleri.** Üstteki "RET faizleri" düğmesi (Forward sayfasının RET sekmesindeki "RET faizlerini düzenle /
kopyala" da aynı pencereyi açar):

* **Yükle** — Excel'deki RET tablosunu (yalnızca bid–ask sütunları ya da vade etiketiyle birlikte) kopyalayıp
  pencereye `Ctrl+V` ile yapıştırın.
* **Değiştir** — kutulara tek tek yazın ya da "Tümünü kaydır": baz puanı yazıp (`25`, `-50`) *Bid + Ask*, *Bid* ya da
  *Ask* düğmesine basın; bütün vadeler o kadar kayar.
* **Kopyala** — "Kopyala (tablo)" vade · gün · bid · ask sütunlarını Excel'e ya da e-postaya yapıştırılacak biçimde,
  "Kopyala (mesaj)" sohbet penceresine atılacak hizalı metin olarak (`1M    34,25 / 34,45`) panoya koyar. Kutularda
  ne görünüyorsa o kopyalanır; henüz kaydedilmemiş bir değişiklik varsa uyarır.
* **Kaydet** — eğri herkes için geçerli olur, veritabanında saklanır ve her yükleme (kim, ne zaman, hangi değerler)
  geçmişe yazılır; geçmişteki bir kayıt tek tıkla geri getirilebilir.

Aynı şey Forward sayfasındaki TRY RET tablosuna doğrudan yazarak / yapıştırarak da yapılır.

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
* **Tahvil** — enstrüman (ISIN), yön, tutar, fiyat. Kâğıt DİBS RV tablosundaysa adı, vadesi, tablodaki temiz fiyatı,
  süresi ve DV01'i gösterilir.

**DV01.** Her işlemin DV01'i hem girerken (fiyat kutusunda) hem girdikten sonra (listelerde) görünür:

* Forward: Forward sayfasındaki "Forward DV01" bloğunun (`Forward!N31:P49`) formülü, işlemin kendi valörü, forward
  kuru ve tutarıyla: `DV01 (TL) = ± tutar · forward · T · DF_TRY / 10.000`, `DV01 ($) = DV01 (TL) / spot`; ayrıca USD
  faizi DV01'i. Tutar yazılmadan önce 1 mn USD içindir.
* OIS: bacak bazında DV01 ($) (eskiden olduğu gibi) ve işlemin **net** / brüt DV01'i.
* Tahvil: DİBS RV tablosundaki "DV01 TL / 1mn" sütunundan; tabloda olmayan bir kâğıdın DV01'i boş kalır ve özet
  satırında "DV01'i bilinmeyen işlem" olarak sayılır.

İşaret Excel'deki bloğun işaretidir: **+ = TRY faizi 1 bp artınca kazanır** (vadeli USD alışı, PAY), **−** = kaybeder
(vadeli USD satışı, RECEIVE, tahvil alışı). Listelerin üstündeki şerit görüntülenen işlemlerin toplamını verir:
Toplam · Forward · OIS (net) · Tahvil ($).

Kaydedilen işlem tüm kullanıcılarda anında görünür (kim, saat kaçta girdi bilgisiyle). Sağda işlem listeleri ve
**pozisyonun maliyeti** (valör / vade / enstrüman bazında net pozisyon, başabaş seviyesi `(A₁R₁−A₂R₂)/(A₁−A₂)` ve
gerçekleşen K/Z — Hesaplayıcılar sayfasındaki "Weighted Average" tablosunun aynısı), altta Excel'deki
Günlük İşlemler sayfasının kendi özet tabloları. "Fiyatı kopyala" ekrandaki fiyatı tek satır metin olarak panoya koyar.

**Geçmiş günler ve tarih aralığı.** "İşlem günü" seçicisi geçmiş bir günü, yanındaki **Aralık** iki tarih arasındaki
bütün günleri gösterir (iki tarihi seçip "Göster"; hazır aralıklar: *Bu hafta*, *Bu ay*, *Son 30 gün*). Aralıkta her
satırın başında işlem günü yazar; maliyet ve DV01 özetleri aralıktaki işlemlerin toplamıdır. Geçmiş gün ve aralık
salt okunurdur: işlem girişi ve silme yalnızca bugünün sayfasındadır ("Bugün" düğmesi geri döndürür).

**Gün sonu arşivi.** Excel'deki `GunSonuArsivle` makrosunun (sayfayı değer olarak `Blotter_yyyy.aa.gg.xlsx`
dosyasına kaydedip listeleri temizleyen düğme) karşılığı: "Gün sonu arşivi (.xlsx)" seçili günü aynı adla indirir.
Dosyanın ilk sayfası Günlük İşlemler sayfasının Excel'deki yerleşimiyle, yalnızca değerlerden oluşan kopyasıdır
(makronun kaydettiği dosyayla aynı hücre adresleri); ikinci sayfada kimin, ne zaman, hangi işlemi girdiği ve
pozisyon maliyetleri vardır. Listeleri temizlemek gerekmez: her günün defteri ayrıdır, yeni gün boş başlar ve
geçmiş günler istenildiği zaman yeniden indirilebilir. Bir **aralık** görüntülenirken aynı düğme o aralığın işlem
listesini (her satırda günüyle), DV01 ve maliyet özetleriyle tek dosya olarak indirir
(`Blotter_yyyy.aa.gg-yyyy.aa.gg.xlsx`); Excel yerleşimindeki sayfa tek bir güne ait olduğundan o dosyada yoktur.

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

**Altın — forward'ı altın swap faizinden** (VİOP sayfası, altın tablolarının altında). Excel altın forward'ını
`BFXFORWARD("XAUUSD"; tarih; …)` ile alıyor; bu fonksiyonun API karşılığı olmadığı için canlıda bu hücreler boş
kalıyordu. Artık forward, spot'un Bloomberg'deki altın swap faiziyle (`XAUSR1W`, `XAUSR1M` …) taşınmasıyla
hesaplanır; altın faizi **doğrudan** uygulanır, USD faizi hesaba girmez:
`XAUUSD fwd = spot·(1 + swap·g/360)` (g = valör − altın spot valörü; faiz eğriden gün bazında doğrusal, uçlarda
sabit).

* *Spot ve kaynak:* spot ticker'ı (`XAU Curncy`), manuel spot (boşsa Bloomberg), spot valörü, okunacak Bloomberg
  alanı (`PX_LAST`), ticker eki (`Curncy`) ve kaynak seçimi: **Otomatik** (spot ve swap faizi varsa swap faizinden,
  yoksa `BFXFORWARD`), **Swap faizi**, **BFXFORWARD**.
* *Swap faizi eğrisi:* 1W … 12M için **ticker kökü** (`XAUSR1W`, `XAUSR1M`, `XAUSR2M`, `XAUSR3M`, `XAUSR6M`,
  `XAUSR9M`, `XAUSR12M`; sonuna ticker eki eklenir, hücreye boşluklu tam ticker yazılırsa aynen kullanılır) ve
  **Manuel %** (doluysa Bloomberg değerinin önüne geçer). Faizi olmayan ya da Bloomberg'de bulunmayan vade atlanır.
  Yanında yalnızca bilgi için USD OIS faizi ve ikisinin ima ettiği lease (≈ USD − swap) gösterilir.
* *XAUUSD forward:* üç VİOP XAUTRY kontratı, üç VİOP XAUUSD kontratı, `Forward!D2` tarihi ve iki serbest tarih için
  swap faizinden forward, `BFXFORWARD`, kullanılan değer ve `BFXFORWARD`'ın ima ettiği swap faizi. **VİOP XAUTRY
  BID / ASK** tabloları, VİOP XAUUSD tablosu ve Forward sayfasındaki altın şeridi (`VIOP!M58:O58`, `S58:U58`,
  `M68:O68`, `Forward!I29:J29`) buradaki "kullanılan" değeri okur.
* *VİOP XAUTRY hesaplayıcısı* ("Interest 2 SP" ve "SP 2 Interest"in altın karşılığı; VİOP sayfasında hem
  **Hesaplayıcılar** hem **Altın** sekmesinde). Üç XAUTRY kontratı için birer sütun ve bir **Serbest** sütun.
  - *Faizden fiyat:* TRY %, USD % (USDTRY bacağı için) ve isteğe bağlı altın swap % → USDTRY forward, swap puanı,
    **teorik XAUTRY (TL/gr) = XAUUSD fwd · USDTRY fwd / 31,1035** ve VİOP bid / ask'a fark. TRY % varsayılanı aynı
    vadeli USDTRY VİOP kontratının ima faizidir.
  - *Fiyattan faiz:* "VIOP bid / ask" satırındaki fiyat için **ima TRY %** `((fiyat·31,1035/XAUUSD fwd)/spot ·
    (1+USD·VKGS/360) − 1)·360/VKGS` ve, TRY % satırındaki faizle aynı fiyatı veren, **ima altın swap %**. Fiyat
    piyasadan gelir; üzerine kendi fiyatınızı yazınca o fiyatın ima ettiği faizi görürsünüz.
  - **Her girdi elle yazılabilir:** 1. ve 2. tarih, USDTRY spot, XAUUSD spot, USD %, TRY %, altın swap %, XAUUSD
    forward ve VİOP bid / ask. Boş bırakılan piyasadan dolar; yazılan değer `Delete` ile piyasaya döner. 2. tarih
    değiştirilirse gün sayısı, USD faizi ve (swap faizi eğrisinden) XAUUSD forward o tarihe göre hesaplanır.
    *Serbest* sütunda 2. tarihi ve TRY faizini siz yazarsınız; Bloomberg'den altın verisi gelmese bile XAUUSD
    forward'ı (ya da spot + altın swap faizini) elle yazarak hesap yapılır.
  - VİOP XAUTRY BID / ASK tabloları bid için ask, ask için bid outright'ı kullanır; hesaplayıcı tek forward (orta ya
    da yazdığınız) kullandığından ima faiz tablodakinden birkaç baz puan farklı olabilir.

Kayıtlı veri modunda altın spotu ve swap faizi kaydı olmadığından forward Excel'in kaydettiği `BFXFORWARD`
değerlerinden okunur (sayfalar Excel'le aynı kalır); spot ve faizi elle yazınca hesap devreye girer.

**O/N karşılıkları.** Borsa Swap tablolarında BID / ASK ima faizinin yanında O/N karşılığı
(`360·((1+r·gün/360)^(1/gün) − 1)`) ve günlük puan sütunları; Günlük İşlemler'deki forward listesinde her işlemin
TRY faizinin O/N karşılığı (sayfanın kendi F sütunu) ve gün sonu arşivinde aynı sütun.

### Borsa Swap ve DİBS ASW

* **Borsa Swap** (`BBG_Borsa_Swap.xlsx`): BIST swap pazarının T+0 ve T+1 kotaları (1–400 gün; alış / satış puanı ve
  miktarları) → USD OIS ile ima edilen TRY basit faizi. Yalnızca kotası olan vadeler listelenir (Excel'deki `FILTER`
  formülleri). Ham kota tabloları yardımcı tablolardadır.
  **Yalnızca arkasında emir olan kota gösterilir:** bir taraf (alış ya da satış) ancak miktarı sıfırdan büyükse
  görünür, iki tarafı da boş olan vade listelenmez. Excel dosyası "miktar bir sayı mı" diye süzer; Bloomberg API'si
  ise kotası olmayan bir vade için miktarı 0, fiyatı da eski bir değer (iki tarafta aynı) olarak döndürür — Excel'in
  canlı bağlantısında bunlar `#N/A N/A` görünür. Dosyanın kuralıyla sayfa gerçekte olmayan kotalarla doluyordu; bu
  yüzden dashboard süzgeci `Sheet2`'de değiştirir (dosyanın kendi formülüne dokunan tek ek budur). Canlı akışta bir
  emrin miktarı boşaltılırsa (emir geri çekildi) miktar `#N/A N/A` olur ve kota listeden düşer.
* **DİBS ASW** (`DIBS_ASW.xlsx`): 50 kâğıtlık izleme listesi (ISIN, kaynak, manuel fiyat), TLREF OIS eğrisiyle
  iskonto edilmiş bugünkü değer, ASW (bp), uydurulan eğriye göre ucuz / pahalı ve üç kâğıdın ASW geçmişi.
* Bu iki dosya Bloomberg bağlantısı olmadan kaydedildiği için içlerinde **kayıtlı piyasa verisi yok**. Kayıtlı
  veri modunda: ASW sayfası kâğıt bilgilerini ve fiyatları TTO dosyasının aynı günkü kayıtlarından alır (ASW
  değerleri TTO'daki DİBS RV tablosuyla 0,05 bp içinde aynıdır; geçmiş kısmı yalnızca canlıda dolar); Borsa Swap
  sayfasındaki kotalar TTO'daki RET eğrisinden türetilmiş **örnek veridir** (sayfanın üstünde yazar).
  Canlı modda ikisi de doğrudan Bloomberg'den beslenir.

### Gün Sonu Matrisi, PPK Fiyatlama Geçmişi ve toplantı takvimi

Bu üç sayfa Excel dosyasında yok; dashboard'un kendi **günlük tarihçesine** dayanır (`data/tto.db` içinde: her seri
için gün gün kapanış, her gün için her toplantının fiyatlaması). Hangi serilerin tutulacağı dosyadan okunur: OIS
ticker kökleri (`OIS_MAIN!J9:J26`) + geçmiş kaynağı (`MASA!S171`, ör. `Curncy`), TLREF, offshore ticker'ları
(`Forward!AO6:AO26`: `TRYI…` FX swap ima faizleri ve `TRYSAQ…` XCCY), DİBS RV listesindeki kâğıtlar. Bu hücreler
değişince tarihçe de onları izler.

* **Canlı modda** kapanışlar Bloomberg'den (`HistoricalDataRequest`, yalnızca işlem günleri) bir yıl geriye çekilir
  ve 15 dakikada bir son günler yenilenir (`--history-refresh`); bugünün satırı gün içinde günün son fiyatıdır.
  İlk açılışta ~100 ticker için bir kez bir yıllık geçmiş istenir, sonraki turlar yalnızca son 10 günü ister.
* **Kayıtlı veri modunda** tarihçe, Excel dosyasının kendi sakladığı `BDH` bloklarıdır (05.10–03.11.2026: OIS
  1M–1Y, XCCY 1Y) ve dashboard'la gelen TLREF fixingleri (`tto/data/replay_history.json`, kaynak TCMB EVDS
  `TP.BISTTLREF.ORAN`). Sayfalar hangi verinin eksik olduğunu üstlerinde söyler.

**Gün Sonu Matrisi** (Masa grubu). Seçilen günün kapanışı ve **Δ1G / Δ1H / Δ1A** — Excel'deki MAKRO ve OIS eğri RV
tablolarının kuralıyla: 1 / 5 / 21 iş günü önceki kapanışa göre, tatil günü bir önceki kapanışı alır. Üç tablo:

* *TRY OIS · Offshore:* vadeye göre yan yana — OIS par faizi (TLREF satırıyla birlikte, 1W–10Y) ve offshore (9 aya
  kadar FX swap ima faizi, 1Y–10Y XCCY); seviye % ve değişimler bp.
* *PPK fiyatlaması:* sıradaki toplantıların her biri için fiyatlanan adım (bp), toplantı sonrası ima TLREF (%) ve
  kümülatif (bp), her birinin değişimi.
* *DİBS:* DİBS RV listesindeki kâğıtlar vadeye göre; Bloomberg getirisi (alan Ayarlar'dan seçilir, varsayılan
  `YLD_YTM_MID`; TLREF'e endeksli kâğıtlarda fiyat) ve değişimi, yanında Excel'in kendi hesabı olan BIST bileşik
  getiri (DİBS RV sayfası, şu anki değer). Bloomberg'in sayfadaki kaynaklı ticker'ı (`… @ISL1 ISIN`) geçmiş
  vermezse kaynaksız ticker denenir.

Değişimler büyüklüğüne göre renklenir (yukarı sıcak, aşağı soğuk); hücrenin üzerinde durunca önceki kapanış
görünür; üstteki listeden geçmiş bir gün seçilebilir; her tablo Excel'e kopyalanabilir.

**PPK Fiyatlama Geçmişi** (TRY Faiz grubu). Her geçmiş gün için, o günün OIS kapanışları, TLREF'i ve o gün geçerli
toplantı takvimiyle **Excel'in kendi çözücüsü** (Motor · GLOBAL İMA PPK) yeniden çalıştırılır; formüller yeniden
yazılmadı, ikinci bir motor örneği o günün verisiyle beslenir. Sonuç gün ve **toplantı tarihi** bazında saklanır.

* Grafik: seçilen toplantıların zaman serisi — *Adım (bp)* (OIS sayfasındaki "Implied bps"), *Kümülatif (bp)* ya da
  *Seviye (%)*; dönem 1A / 3A / 6A / 1Y. Toplantılar düğmelerinden eklenip çıkarılır (en çok 6 çizgi).
* *Toplantılar* tablosu: son fiyatlama, Δ1G / Δ1H / Δ1A, bir yıllık min / max, seviye, kümülatif, çözücünün ± bp'si.
  **Yapılan toplantılar** ayrı blokta kalır: serileri toplantıdan önceki son iş gününde biter; yanında TLREF'in
  toplantı ertesindeki değişimi ("gerçekleşen") ve sürpriz (gerçekleşen − toplantı öncesi fiyatlanan) yazar.
* *Günlük geçmiş*: gün × toplantı matrisi (kopyalanabilir), o günün TLREF'i, çözücüye giren kota sayısı ve
  **Durum**: Excel'in kendi durum hücresi (`OIS_MAIN!AU12`) o gün için ne dedi.
* **Bir günün değeri ne kadar güvenilir?** Çözücü bütün vadeleri birlikte uydurur ve o güne ait olmayan tek bir
  kotadan çok etkilenir: 3M kapanışı 40 bp sapınca en yakın toplantıların adımı yüz baz puandan fazla oynar,
  üstelik çözücünün kendi kontrolü ("model − kota" farkı, tolerans 5 bp) bunu çoğu zaman görmez. Bu yüzden:
  * o gün kapanışı **olmayan** bir vade son kapanışından (en çok 3 işlem günü) *komşu vadelerinin o günden beri
    yaptığı hareket kadar* kaydırılarak devam ettirilir — seviyeyi olduğu gibi taşımak, hareket etmiş bir eğrinin
    içinde bayat bir nokta bırakır ve gün aşırı kapanan bir vadede zikzak çizer;
  * **iki komşusundan da ayrılıp ertesi gün geri dönen** bir kapanış (her iki yanındaki vadeye göre ≥ 25 bp gidiş
    ve dönüş: güncellenmemiş ya da hatalı kota) kullanılmaz, yerine yukarıdaki gibi doldurulur. Komşusunun da
    paylaştığı bir hareket — eğrinin bir parçası ya da tamamı — piyasadır ve kalır. 2 aydan kısa vadeler ve son gün
    (dönecek ertesi günü henüz yok) bu süzgece girmez. Hangi günde hangi vadenin ayıklandığı sayfanın üstünde yazar;
  * çözücünün **tutturamadığı** günler (Excel'de "Kota/takvim tutarsız – kontrolü incele") veritabanında ve
    günlük tabloda ⚠ ile kalır ama grafiğe, min / maks'a ve değişimlere girmez.
  1Y ile 18M arasındaki toplantılarda görülen pozitif adımlar bir hata değildir: dosyanın 03.11.2026'da Excel'de
  kayıtlı kendi çözümünde de aynıdır (09.12.2027: +70, 20.01.2028: +71 bp), 18M ve 2Y kotalarının 1Y'ye göre
  seviyesinden gelir.
* Bir günün çözümü 2–3 saniye sürer. Canlıda ilk doldurma (bir yıl ≈ 260 gün) arka planda 10–15 dakika alır, en
  yeni günlerden başlar ve sayfalar bu sırada dolan kadarını gösterir; sonrası yalnızca yeni / değişen günlerdir.
* **Toplantı günü:** o günün kapanışı kararı fiyatlar ama TLREF fixingi kararı ertesi gün yansıtır. O gün sıradaki
  toplantının adımı, çözücünün karar sonrası için ima ettiği seviyeden ölçülür (yoksa bugünkü karar da adımın
  içinde görünürdü); bu günler tabloda "PPK" ile işaretlidir.
* Kayıtlı veride yalnızca 1Y'ye kadar altı OIS vadesi olduğundan değerler OIS sayfasındaki tam çözümden birkaç bp
  farklı olabilir ve 1Y'nin ötesindeki toplantılar hesaplanmaz. Bugünün kotaları verildiğinde tarihçe satırının
  OIS sayfasıyla hücre hücre aynı olduğu testle doğrulanır.

**Ayarlar · Toplantı takvimi** (Araçlar grubu). Tek liste: yapılan toplantılar (arşiv) ve OIS sayfasındaki 80
toplantı (`OIS_MAIN!P10:P89`; aynı hücreler, herkes için ortak). Gerçek tarih belli olunca satırdaki tarih
düzeltilir (gg.aa.yyyy), yeni toplantı eklenir, silinir ya da Excel'den bir tarih sütunu toplu yapıştırılır →
**Kaydet**.

* Bir toplantıya yazılmış her şey **toplantısıyla birlikte taşınır**: her kullanıcının senaryo adımları (`U:W`),
  kayıtlı senaryoları ve dosyanın kendi adımları. Araya toplantı eklenince sonrakiler bir satır aşağı, çıkarılınca
  yukarı kayar; tarihi düzeltilen toplantı aynı toplantı sayılır.
* **Toplantı geçince:** dosyanın kendi mantığı çalışır — satır "geçti" olur, sıradaki toplantı ilk toplantı olur,
  hiçbir şeyi kaydırmak gerekmez. İstenirse **Geçen toplantıları arşivle** geçenleri listeden arşive alır ve liste
  sıradaki toplantıdan (MPC1) başlar; kaydırmadan önce ve sonra her toplantının fiyatlaması ve her kullanıcının
  senaryo patikaları toplantı bazında aynıdır (testle doğrulanır). Fiyatlama geçmişi toplantının tarihine bağlı
  olduğu için kaydırmadan etkilenmez.
* Takvim değişince fiyatlama geçmişi yeni takvimle arka planda yeniden hesaplanır (yalnızca etkilenen günler).
* *Tarihçe* bölümü: durum, DİBS getiri alanı, geriye bakış süresi, "Şimdi güncelle", "PPK geçmişini yeniden
  hesapla". *Tarihçe serileri* tablosu her ticker için ilk / son gün ve gün sayısını gösterir — matriste boş kalan
  bir satırın nedeni (Bloomberg o ticker ya da alan için geçmiş vermiyor) buradan görülür.

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
| Ivır Zıvır sayfasındaki resim | Sayfanın dashboard'da sayfası yok; resim okunur ve `/api/image` ile sunulur (resimli bir sayfa gösterilseydi sonunda resim paneli olurdu) |
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
| PPK fiyatlama geçmişi: tarihçenin çözücüsü bugünün OIS sayfası kotalarıyla beslendi, OIS sayfasıyla karşılaştırıldı | 80 toplantının adımı, seviyesi, kümülatifi ve ± bp'si hücre hücre aynı (1e-9); durum `OK` |
| Toplantı geçişi: spot ilk toplantının ötesine alındı, sonra liste kaydırıldı | Geçişte OIS / DV01 / Carry / Motor sayfalarında yeni hata hücresi yok (sayfaya önceden yazılmış ve artık spotun gerisinde kalan bir tarih, Excel'deki gibi, yenisi yazılana kadar `#N/A` verir); kaydırma öncesi ve sonrası 79 toplantının fiyatlaması, üç senaryo patikası ve adımları üç ayrı kullanıcı için **bit bit aynı**; kaydırmadan önce kaydedilmiş senaryo aynı toplantıları gösteriyor |
| Dashboard'un ekledikleri bağımsız kapalı formüllerle sınandı | Forward matrisi: yedi eğrinin her biri Masa'daki bloğun TRY faiziyle 1e-12 aynı; puan → spread tersi 1e-7 bp. Altın: `spot·(1+swap·g/360)` ve faiz interpolasyonu 1e-13; USD eğrisi oynatıldığında hiçbir altın forward'ı değişmiyor. |

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
| `BFXFORWARD` | **API karşılığı yok** → `#N/A BFXFORWARD` (aşağıya bakın); altın forward'ı bunun yerine altın swap faizinden (`XAUSR…`) hesaplanır |
| `RtGet` (Refinitiv) | Bloomberg fonksiyonu değil → `#N/A RTGET` |

Bağlantı **Desktop API** içindir (terminalin açık olduğu makinede `localhost:8194`); B-PIPE / SAPI gibi sunucu
ürünlerinin yetkilendirme adımı yazılmadı. Abonelikle hiç değer gelmeyen fiyat alanları (ör. işlem görmeyen bir
kağıt) `--price-poll` (120 sn) sonra sorguyla istenir; yanıt değişmedikçe aralık ikiye katlanarak 30 dakikaya
(hiç değeri olmayan alanlarda 1 saate) kadar uzar, değer değişince yeniden 120 sn'ye iner. Bloomberg'in tanımadığı
bir ticker (`#N/A Invalid Security`) o gün bir daha sorulmaz, aboneliği de açılmaz; gün değişince bir kez yeniden
sorulur (dün olmayan bir vade bugün var olabilir). Böylece Borsa Swap sayfasının kotası olmayan yüzlerce vadesi ne
günlük veri limitini tüketir ne de terminali boş aboneliklerle uğraştırır.

Henüz gelmemiş bir değer Excel'deki gibi `#N/A Requesting Data...` görünür, yanıt gelince bağlı hücreler yeniden
hesaplanır. Sunucu açılırken kitapların kullandığı tüm kalemler önceden istenir (dört kitapla ~4.300 kalem).
Abonelik yalnızca Bloomberg'in tanıdığı ticker'lara açılır: Borsa Swap sayfası 1–400 günlük her vadeyi iki kaynakta
(`TYB…D BFX0 / BFX1`, 800 ticker) sorar, bunların yalnızca o gün var olanlarına abone olunur (kayıtlı dosyadaki
durumla toplam ~240 abonelik); var olmayanlar bir kez sorgulanır ve Excel'deki gibi `#N/A Invalid Security` görünür.
**Tahvil kimlikleri.** DİBS RV sayfası bir kâğıdı Excel eklentisinin kabul ettiği biçimde yazar: kimlik türü sonda
(`TRT150328T24 ISIN`, kaynakla `TRT150328T24 @ISL1 ISIN`). API bu yazımı tanımaz (`#N/A Invalid Security`); kimlik
türünü önde ister. Dashboard isteği, geçmişi ve aboneliği gönderirken çevirir (`/isin/TRT150328T24@ISL1`; `CUSIP`,
`SEDOL`, `BUID`, `FIGI` … için de), hücrelerde dosyanın kendi yazımı kalır. `ISIN + Corp / Govt` gibi sarı tuşlu
yazımlara dokunulmaz.
BDP tarihleri masadaki Excel'de olduğu gibi `4.11.2026` biçiminde metin olarak döner. Günlük referans/geçmiş veri
isteği sayısı sayılır; `--max-hits` (varsayılan 400.000) aşılırsa yalnızca akan veriler güncellenmeye devam eder ve
rozet uyarır. Bağlantı koparsa otomatik yeniden bağlanılır.

**Tarihçe** (gün sonu matrisi, PPK fiyatlama geçmişi) için ayrıca `HistoricalDataRequest` gönderilir: ilk
açılışta ~100 ticker için bir yıllık günlük kapanış (alan başına 50 ticker'lık isteklerle), sonra 15 dakikada bir son
10 gün. Bunlar da günlük istek sayacına yazılır (tur başına ~100). Geçmişi hiç olmayan bir ticker 6 saat boyunca
yeniden sorulmaz; "Şimdi güncelle" hemen yeniden dener.

### Bloomberg oturumu ayrı bir süreçte

Bloomberg, olayları uygulamaya sınırlı uzunlukta bir kuyruktan verir; yeterince hızlı okumayan uygulamayı önce
uyarır (`Marking Session as slow … pending events = 7500`), sonra olayları atar (`Slow consumer: event queue is
full, events are being dropped`). Masadaki ilk canlı çalıştırmada (13.11.2026) tam olarak bu oldu. Nedeni:
olayları okuyan kod ile hesap motoru aynı Python sürecindeydi. Python aynı anda tek iş parçacığı çalıştırır;
`blpapi`'ye yapılan her çağrı yorumlayıcıyı bırakır ve motor o sırada hesap yapıyorsa okuyucu sırasını bekler.
Gerçek `blpapi` ile ölçüldü: tek başına 0,06 ms süren bir tick okuması, yanında hesap yapan bir iş parçacığı varken
6 ms sürüyor (3.26'da ~100 kat, 3.24'te ~60 kat). İlk açılıştaki tarihçe hesabı dakikalarca sürdüğü için kuyruk
dolup taşıyordu; üstüne Borsa Swap sayfasının var olmayan ~780 vadesine açılan abonelikler (`Resolution failed`
satırları) geliyordu.

Şimdi:

* **Oturum, abonelikler ve istekler ayrı bir yardımcı süreçte** çalışır (`tto/marketdata/bbg_process.py`); orada
  başka hiçbir şey hesap yapmaz. Dashboard yardımcıdan saniyede ~10 kez "değişen kalemlerin son değeri"ni alır.
  Görev Yöneticisi'nde bu yüzden iki `python.exe` görünür; dashboard kapanınca (ya da öldürülünce) yardımcı da
  kapanır, yardımcı ölürse yeniden başlatılır ve her şey yeniden istenir (günlük istek sayacı kaldığı yerden
  sürer). Art arda 5 kez kısa sürede ölürse yeniden başlatılmaz ve rozet bunu söyler: her yeni yardımcı Bloomberg'den
  her şeyi baştan ister, sürekli ölen bir süreç terminalin günlük veri limitini böyle tüketmemelidir. Açılışta
  konsolda `Veri: Bloomberg canlı · oturum ayrı bir yardımcı süreçte` yazar; rozetin ipucunda da görünür.
* Yardımcı süreç başlatılamazsa (ya da `--bbg-inprocess` verilirse) oturum eskisi gibi dashboard'un sürecinde açılır;
  bu durumda okuyucuya öncelik verilir (yorumlayıcının iş parçacığı değiştirme aralığı 5 ms → 1 ms), abonelikler
  saniyede bir güncellemeye seyreltilir (`interval=1`) ve tarihçe hesabı her günün ardından bir o kadar dinlenir.
* Olay kuyruğu 10.000'den 100.000'e çıkarıldı (`--bbg-queue`); bir tick mümkün olan en az `blpapi` çağrısıyla okunur.
* Bloomberg kuyruk hakkında ne derse sayılır ve gösterilir: kuyruk dolarken rozet sarıya döner ("CANLI · Bloomberg
  kuyruğu doluyor"); olay düşerse ipucunda `KUYRUK TAŞTI: … olay düştü` yazar ve etkilenen değerler sorguyla
  yeniden istenir (düşen bir tick ekranda eski fiyat bırakmasın diye; günde en çok 20.000 değer, veri limitini
  korumak için).

`--bbg-interval N`: bir aboneliğin iki güncellemesi arasındaki en kısa süre (sn). Varsayılan: yardımcı süreçte 0
(her tick), aynı süreçte 1. Abonelik bu seçenekle reddedilirse seçeneksiz yeniden denenir.

Aynı sahne eski ve yeni kodla çalıştırıldı (dört kitap, `blpapi` gibi davranan sahte terminal: çağrılarda
yorumlayıcıyı bırakır, kuyruğu 10.000 olaydır; saniyede 1.500 tick, tarihçe hesabı açık): eski kod **53.817 olay
düşürdü**, yenisi hem yardımcı süreçle hem aynı süreçte **hiç** düşürmedi (kuyrukta en çok 8, aynı süreçte ~1.800
olay bekledi).

> **Dürüst not:** canlı katman ilk kez 13.11.2026'da masada gerçek terminale karşı çalıştı ve yukarıdaki sorun o
> zaman ortaya çıktı. Düzeltme bu ortamda gerçek terminale karşı **çalıştırılamadı** (terminal yok, Windows yok):
> `blpapi` arayüzünü taklit eden modülle (`tests/fake_blpapi.py`), gerçek `blpapi` kütüphanesinin kendi test
> olaylarıyla (`tests/test_blpapi_real.py`, 3.24 ve 3.26) ve Linux'ta Windows'un kullandığı süreç başlatma
> yöntemiyle (`spawn`) sınandı. Canlıda rozetin ipucuna bakın: "oturum ayrı süreçte" yazmalı, "KUYRUK TAŞTI"
> yazmamalı. `python -m tto check-bloomberg` bağlantıyı ve alanları sınar.
> Aynı günkü ikinci canlı çalıştırma üç şey daha gösterdi; üçü de bu ortamdaki sahte terminalin gerçeğinden
> gevşek olmasından gözden kaçmıştı ve sahte terminal artık gerçeği gibi davranıyor: DİBS kimliklerinin Excel
> yazımını API tanımıyor (`#N/A Invalid Security`), kotası olmayan BIST swap vadeleri miktar 0 ve eski fiyatla
> dönüyor, tek tek vadelerin günlük kapanışları PPK geçmişinde sıçrama yapabiliyor.

---

## Canlıya geçmeden önce

* **Manuel spot:** kaydedilmiş dosyada VİOP sayfasındaki "Manuel SP" hücreleri dolu (üst şeritte *Spot kaynağı:
  MANUEL* yazar). Bloomberg spotunu kullanmak için üst şeritteki **Spot kaynağı ✎** kutusuna tıklayıp "Bloomberg'e
  dön" deyin (ya da iki hücreyi silin); hücreler ortak girdidir, bir kişinin yapması yeter. Manuel spot aynı
  pencereden her sayfadan girilir; hücrelerin kendisi VİOP sayfasının ve Masa sayfasının en üstündeki "Manuel spot"
  tablosundadır.
* **RET faizleri:** dosyadaki RET eğrisi 03.11.2026 tarihlidir. Her gün "RET faizleri" penceresinden güncel eğriyi
  yapıştırın; bugün yüklenmediyse düğmenin yanında sarı nokta durur.
* **Altın swap faizi ticker'ları:** VİOP sayfasındaki "Altın · swap faizi eğrisi" tablosu `XAUSR1W` … `XAUSR12M`
  kökleri ve `Curncy` ekiyle gelir. `XAUSR1W` ve `XAUSR1M` masadan alınan adlardır; diğer vadeler aynı kalıba göre
  yazıldı, ek (sarı tuş) ise varsayımdır. İlk açılışta "Bloomberg %" sütununda değer gelmeyen satır varsa kökü ya
  da eki düzeltin (ek tek hücredir) ya da faizi "Manuel %" sütununa girin. Hiç faiz gelmezse altın forward'ı
  `BFXFORWARD`'a düşer; o da canlıda yoktur, yani VİOP XAUTRY tabloları `#N/A` kalır. Bu durumda da hesap yapılabilir:
  VİOP → Hesaplayıcılar → "VİOP XAUTRY · faizden fiyat, fiyattan faiz" tablosunda XAUUSD forward'ı (ya da XAUUSD spot
  ve altın swap faizini) ve gerekiyorsa VİOP fiyatını elle yazın; tabloların kendisine değer yazmak için "Elle değer"
  modunu açın.
* **Tarihçe serileri:** ilk canlı açılıştan birkaç dakika sonra *Ayarlar → Tarihçe serileri* tablosuna bakın.
  "geçmiş yok" yazan bir OIS vadesi varsa geçmiş kaynağını (`MASA!S171`: `Curncy` ↔ `GFOF Curncy`) değiştirin;
  DİBS satırları boşsa getiri alanını (`YLD_YTM_MID`) Bloomberg'de o kâğıtlar için geçmişi olan bir alanla
  değiştirin (ör. `YLD_CNV_MID`). Toplantı takvimindeki geçmiş toplantılar (2025–2026) TCMB takviminden gelir;
  eksik ya da fazla varsa Ayarlar'dan düzeltin.
* `python -m tto check-bloomberg` ile bağlantıyı sınayın, ardından birkaç hücreyi Excel'le karşılaştırın.
* **Bloomberg kuyruğu:** açılıştan sonra konsolda `Slow consumer` / `Marking Session as slow` satırı çıkmamalı,
  rozetin ipucunda "oturum ayrı süreçte" yazmalı. Çıkarsa ipucundaki sayıları (abonelik, düşen olay) not edin.

## Bilinen sınırlamalar

* **`BFXFORWARD`** (Forward sayfasında çapraz forward, Masa'da USD/EUR dışı döviz): Bloomberg'in Excel'e özel bir
  fonksiyonu, API'de yok. Canlı modda bu hücreler `#N/A` olur; USDTRY / EURTRY forward tabloları bundan
  etkilenmez. `--bfx approx` ile Bloomberg'in `FWD_CURVE` verisinden gün bazında doğrusal interpolasyonla
  **yaklaşık** bir değer üretilir (Excel'le birebir olma garantisi yoktur, doğrulanmadı). Altın forward'ı artık
  buna bağlı değildir (altın swap faizinden hesaplanır). `XAUSR…` ticker'larının sarı tuşu (`Curncy`) ve 2M–12M
  vadelerinin yazımı canlıda doğrulanmadı; yanlışsa o vade atlanır, hücreden düzeltilir.
* **Borsa Swap ve DİBS ASW** dosyalarında kayıtlı piyasa verisi yok: kayıtlı veri modunda Borsa kotaları örnek
  veridir, ASW geçmişi boştur. İkisi de gerçek değerlerini ancak canlı modda gösterir ve canlıda henüz sınanmadı.
* **Tarihçe** kapanış fiyatlarıyla ve geçmiş kaynağıyla (`MASA!S171`, varsayılan bileşik `Curncy`) hesaplanır;
  OIS sayfası ise canlı `GFOF` kotasını kullanır. Bu yüzden fiyatlama geçmişinin bugünkü noktası OIS sayfasından
  kaynak farkı kadar (tipik olarak 1–3 bp) ayrışabilir. Geçmiş günler dosyanın **bugünkü** çözücü ayarları ve tatil
  listesiyle (geçmiş tatiller TLREF fixingi olmayan iş günlerinden çıkarılır) hesaplanır; kullanıcıların kişisel
  çözücü ayarları tarihçeye girmez.
* **DİBS değişimleri** Bloomberg'in getiri alanındandır (kendi getiri kuralıyla); DİBS RV sayfasındaki BIST bileşik
  getirinin geçmişi dosyada yoktur, bu yüzden o sütun yalnızca bugünkü seviyeyi gösterir. Bloomberg'in bu alanlar
  için geçmiş verip vermediği canlıda sınanmadı.
* **"Gerçekleşen"** (yapılan toplantılarda) TLREF fixingindeki değişimdir, politika faizi kararı değil; TLREF
  politika faizinden ayrıştığı dönemlerde (ör. fonlamanın üst banda kaydığı günler) ikisi farklıdır.
* **USDTRY IYIX** sayfası Refinitiv `RtGet` kullanıyor; canlı modda `#N/A`.
* **Kayıtlı veri modu** piyasa verisini ve "bugün"ü dosyanın son hesaplandığı güne (03.11.2026) sabitler;
  Günlük İşlemler ise gerçek takvim gününe yazılır. Spot hücreleri de (`VIOP!L99:L100`, içlerinde Bloomberg çağrısı
  var) dosyadaki değerde kalır: manuel spot bu modda kaynak yazısını değiştirir ama kullanılan spotu değiştirmez
  (canlıda değiştirir).
* **Giriş şifresizdir** (istenen: yalnızca isim). Porta ağdan erişebilen herkes kullanabilir; masanın güvenilen
  ağı dışına açmayın.
* Hesaplar tek süreçte, tek bir motor iş parçacığında sıraya girer (Bloomberg oturumu ayrı bir yardımcı süreçtedir).
  Canlı bir tick'ten sonra en ağır sayfaların yenilenmesi ~0,3–0,5 sn sürer; ilk açılışta tarihçe hesaplanırken
  (bir yıl için 20–30 dk, yalnızca ilk gün) sayfalar biraz daha yavaş yenilenir.

---

## Testler

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest tests
```

Bloomberg ve ağ gerekmez (~8–11 dk). 675 test (gerçek `blpapi` kuruluysa 7 tane daha):

| Dosya | Kapsam |
|---|---|
| `test_xl_functions.py`, `test_xl_engine.py`, `test_numfmt.py` | Excel semantiği (operatörler, yuvarlama, tarih, metin, arama, koşullu toplamlar, matris, `LET`, `FILTER` ve taşma / `#SPILL!`, `AGGREGATE`, sıfıra yapıştırma), bağımlılık takibi, kullanıcı katmanları (aynı gruptaki girdilerden birini değiştiren kullanıcının diğerlerini dosyadaki değeriyle görmesi dahil), sayı biçimleri |
| `test_parity.py` | Excel'in kayıtlı değerleriyle parite (sayfa bazında eşikler) |
| `test_reference.py` | LibreOffice'in baştan hesapladığı değerlerle karşılaştırma (`tests/data/lo_*.json.gz`) |
| `test_forward.py` | Forward: bağımsız kapalı formül, Excel'in kayıtlı değerleri, işlem girişindeki fiyatlamanın sayfayla aynılığı |
| `test_blotter.py` | Outright / spread / fly / FRA bacakları, maliyet, ortak işlem defteri, forward'ların O/N karşılığı, Excel özet tabloları, **DV01** (forward: sayfadaki "Forward DV01" bloğuyla aynı sayılar, iki yön, tutarsız fiyat; OIS net / brüt; tahvil: DİBS RV tablosundan, tabloda olmayan kâğıt), işlemle saklanması ve risk özeti, DV01'siz eski kayıt, **tarih aralığı** (günler, toplam maliyet / risk, uçların sırası) ve aralığın tek dosya olarak indirilmesi |
| `test_charts.py` | Grafik tanımlarının Excel'den alınışı (renk, çizgi, işaretçi, eksen sınırları, tarih ekseni, bid–ask kutuları), değerlerin Excel kuralıyla çizime verilişi (boşluk, `#N/A`, metin) ve XY grafikleri (nokta etiketleri, sayı / tarih ekseni) |
| `test_extras.py` | Dashboard'un ekledikleri: forward kotasyon matrisi (yedi eğri Masa bloğuyla aynı, bid / ask ayrı spread, puan → spread tersi), altın (`spot·(1+swap·g/360)` kapalı formülü, USD faizinin hesaba girmediği, faiz interpolasyonu, kaynak seçimi, `XAUSR…` ticker'ları ve ticker eki, canlıda `BFXFORWARD`'sız çalışma, VİOP / Forward hücrelerinin beslenmesi, "belli faizle fiyat"; **VİOP XAUTRY hesaplayıcısında her girdinin elle yazılması**: fiyattan ima TRY ve ima altın swap faizi, ima faizle fiyatın geri gelmesi, başka tarih, serbest sütun, silince piyasaya dönüş), bir ekin dosyaya uymadığında dışarıda bırakılması, Borsa O/N karşılıkları ve örnek kotaların RET'e eşitliği, **Borsa'da yalnızca miktarı olan kotanın listelenmesi** (miktarı 0 / eski fiyatlı vadeler, tek taraflı kota, hata hücresi kalmaması), ASW ↔ DİBS RV |
| `test_workbook_features.py` | Gizli sütunlar, dondurulmuş bölmeler, yorumlar, veri çubukları, kısayollar, resim, aralıktan okunan açılır listeler, Excel yerleşimiyle yapıştırma, gün sonu arşivi (.xlsx yazıcı dahil), hücreden okunan başlık / notlar, şifreli dosyanın içe aktarılması |
| `test_service.py`, `test_server.py`, `test_store.py`, `test_inputs.py`, `test_config_cli.py` | Kişisel/ortak girdiler, senaryolar, RET, kalıcılık, HTTP API, yapıştırma/ayrıştırma, port kuralı, manuel spot (VİOP ve Masa'nın ilk tablosu, üst şeritten giriş, temizleyince Bloomberg spotu), **elle değer** (formülün üzerine yazma: yalnızca sahibinin, yalnızca ona girdi görünür, silince / "formüle dön"le formül geri gelir, yeniden başlatmada kalır), hesaplayıcıların otomatik dolan girdileri (Forward ve VİOP: tarih, spot, döviz faizi), sekmeli sayfa çıktısı ve arama kutusunun verisi, işlem defterinin aralık / DV01 / tahvil fiyatı uçları |
| `test_views.py` | Sayfa tanımları: her panel ve girdi gerçek hücrelere bakıyor, **her formül bir tabloda** (dört kitap + ekler, sıfır istisna), her girdi hücresine sayfasından ulaşılıyor, Forward'daki elle hesaplama araçları (USDTRY ve EURTRY) görünür tablolarda; **sekmeler**: 12'den çok tablosu olan her sayfa sekmeli, her görünen tablo bir sekmede ya da sekmelerin üstünde, sekmeler var olan görünür tabloları gösteriyor, Forward hesaplayıcılarla başlıyor, Hesaplayıcılar sayfasında aynı adlı iki tablo yok; sayfası kaldırılan iki sayfa (formülleri sayılır, Sayfa gezgini'nde durur) |
| `test_bundled.py` | Kurulumsuz çalıştırma: her Python kuşağının paket seti, wheel özetleri ve lisansları, kurulu paketlerin önceliği, `vendor/local`, ve hiçbir paketi olmayan bir Python'la (`python -S`) sunucunun açılıp sayfa, statik dosya, giriş ve canlı akış vermesi |
| `test_history.py` | Günlük tarihçe: kapanış deposu, kayıtlı `BDH` bloklarının tarihlenmesi, serilerin dosyadan okunuşu, **tarihçenin bugünkü satırı = OIS sayfası** (80 toplantı, hücre hücre), toplantı bazında fiyatlama (yapılan toplantının serisi, gerçekleşen TLREF değişimi, toplantı günü ölçümü, kotaların eriştiği ufuk), gün sonu matrisi (1 / 5 / 21 iş günü kuralı, tatil, geçmiş gün), takvim (tarih düzeltme / ekleme / çıkarma: adımların ve kayıtlı senaryoların toplantıyla taşınması; **toplantı geçince ve liste kaydırılınca** sayfalar ve her toplantının değerleri), sahte Bloomberg'le canlı tarihçe (istek gruplama, yalnızca son günlerin yenilenmesi, yedek ticker, zaman aşımı), HTTP uçları; **bir günün kotaları** (kapanışı olmayan vadenin komşularının hareketiyle taşınması, komşularından ayrılıp geri dönen kapanışın ayıklanması, piyasa hareketinin korunması), günlerin Excel'in kendi durumuna göre sınıflanması, çözücünün tutturamadığı günün seriden / min-maks'tan / değişimlerden çıkması, hatalı bir kapanışın kayıtlı ayda çözücüye ulaşmaması, eski sürümün veritabanının korunması |
| `test_bundle.py` | Tek dosyalık kurulum (`kurulum/tto_kur.py`): içine ne girdiği, aynı içeriğin aynı dosyayı vermesi, boş klasöre açma, güncelleme (değişen yenilenir, kalkan silinir, `data` / `vendor/local` / kullanıcının kendi dosyaları kalır), ZIP'ten gelmiş klasör, yarım inmiş / bozulmuş / satır sonları değişmiş dosya, klasör dışına çıkan adların reddi, seçenekler; **repodaki dosyanın kodla aynı olduğu** ve hiçbir paketi olmayan bir Python'la açılıp sunucunun ondan çalıştığı |
| `test_bloomberg.py` | `blpapi` katmanı (sahte sunucuyla): gruplama, abonelik (kota büyüklükleri dahil), sessiz kalan kotaların giderek seyrek sorulması, hata metinleri, BDH/BDS, limit koruması, canlı–doğrudan eşdeğerlik (dört kitap); **Bloomberg'in tanımadığı ticker'lara abone olunmaması**, ertesi gün yeniden sorulması, seyreltme seçeneği ve reddedilince seçeneksiz deneme, uzun olay kuyruğu, **kuyruk taşınca sayım ve düşen değerlerin yeniden istenmesi** (günlük üst sınırıyla); **Excel eklentisi için yazılmış kimliklerin API biçimine çevrilmesi** (`… @ISL1 ISIN` → `/isin/…@ISL1`: istek, geçmiş, abonelik), geri çekilen emrin miktarının boşalması |
| `test_bloomberg_process.py` | Oturumun yardımcı süreçte çalışması: değerlerin, tick'lerin, `BDH`'nin ve tarihçe çağrısının süreç sınırını geçmesi; `blpapi` yok / yüklenemiyor / terminal yok / yardımcı yanıt vermiyor; **yardımcı ölünce yeniden başlayıp her şeyi yeniden istemesi** (istek sayacı sürer), sürekli ölen yardımcının bir noktada bırakılması; dashboard durunca ya da öldürülünce yardımcının kapanması; **ölçüm: hesap yapan bir sürecin içindeki okuyucu saniyede 2.000 tick'in dörtte birine yetişemezken yardımcı hepsini okur**; dashboard'un yardımcıyı kullanması ve başlatamazsa aynı süreçte devam etmesi; ve ilk canlı çalıştırmanın sahnelenmesi: `python -m tto --mode live`, dört kitap, saniyede 1.500 tick, 10.000'lik kuyruk — hiç olay düşmez, var olmayan ~790 vadeye abone olunmaz |
| `test_blpapi_real.py` | Gerçek `blpapi` kuruluysa (yoksa atlanır; terminal gerekmez): kütüphanenin kendi test olaylarıyla tick okuma, değeri boşaltılmış miktarın "mesajda yok"tan ayırt edilmesi, `SlowConsumerWarning` / `DataLoss` / abonelik durum mesajları, oturum seçenekleri ve abonelik metni (`…?fields=ASK,BID&interval=1`), hesap yapan bir iş parçacığının yanında okumanın kaç kat yavaşladığı, terminal yokken hata (aynı süreçte ve yardımcıyla). `blpapi` yükseltildikten sonra masada bir kez çalıştırmaya değer. |
| `test_e2e.py` | Gerçek tarayıcıda (Playwright/Chromium) 186 kontrol: giriş, **sekmeler** (Forward hesaplayıcılarla açılır, sabit valör şeridi, sekme değiştirme ve hatırlanması, her sekmede arama, "Tümü", başka sekmedeki hücreye gidiş), **elle değer** (mod kapalıyken formül yazılamaz; açıkken yazılan değerin işareti, sayaç, silince ve "formüle dön"le geri dönüş), hesaplayıcıya elle spot, düzenleme, Excel kopyala/yapıştır, RET, senaryo, işlem girişi, iki kullanıcı arası canlı paylaşım, grafiklerin çizimi (renk, eksen, tarih ekseni, ipucu, XY grafiği), kısayollar, gizli / dondurulmuş sütunlar, arşiv indirme, forward kotasyon matrisi, altın swap faizi girişi ve VİOP tablosunun değişmesi, Borsa Swap, DİBS ASW, gün sonu matrisi (değerler, geçmiş gün, kopyalama), PPK fiyatlama geçmişi (çizgiler, toplantı ekleme / çıkarma, ölçü değiştirme, ipucu, günlerin durumu), manuel spot penceresi (üst şeritten açma, bid > ask reddi, Bloomberg'e dönme), RET'i baz puanla kaydırma ve tablo / mesaj olarak kopyalama, işlem girerken ve listede DV01, tarih aralığı görünümü ve indirilmesi, altın hesaplayıcısının serbest sütunu, Ctrl+K ile tablo bulma, Ayarlar'da toplantı tarihinin düzeltilip OIS sayfasına yansıması, tüm sayfalar. Node.js + Playwright yoksa atlanır. |

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

Model ya da kod değişince tek dosyalık kurulumu da yenileyin (bir test, repodaki kopyanın güncel olduğunu denetler):

```bash
python tools/make_bundle.py
```

Sayfa düzeni (hangi aralık hangi panelde, hangi hücreler girdi, kişisel mi ortak mı, hangi tablo hangi sekmede)
`tto/views/*.json` dosyalarındadır; satır/sütun eklenip çıkarıldıysa ilgili aralıkları güncelleyin
(`python -m pytest tests/test_views.py` tutarlılığı denetler). Yeni bir Excel fonksiyonu kullanılırsa
`test_parity.py` adını söyler. Bir sayfanın sekmeleri dosyasındaki `sections` listesidir (`{"id", "title", "note",
"panels": [...]}`; tablo sırası listedeki sıradır, bir tablo iki sekmede olabilir), `pinned` sekmelerin üstünde sabit
duran tabloları sayar; yeni eklenen görünür bir tablo bir sekmeye yazılmadıysa test adını söyler. `"header"` Excel'in
adsız bıraktığı sütunlara başlık satırı ekler, `"action": "ret"` tablonun başlığına RET penceresinin düğmesini koyar.
Bir sayfanın dashboard'da sayfası olmasın isteniyorsa görünüm dosyasını silip `tests/test_views.py` içindeki
`NO_PAGE` listesine eklemek yeterlidir (hücreleri hesaplanmaya ve Sayfa gezgini'nde görünmeye devam eder).

Dashboard'un kendi ekleri (`tto/extras.py`) dosyadaki belirli hücrelere dayanır (Masa'daki iskonto faktörleri,
VİOP'taki `BFXFORWARD` hücreleri, Borsa tablosunun başlıkları). Dosyanın düzeni değişip bir ek artık uymuyorsa
sunucu yine açılır; yalnızca o ek dışarıda bırakılır, nedeni başlangıçta günlüğe ve `/api/status` yanıtındaki
`left_out` alanına yazılır.

## Proje yapısı

```
tto/xl/            Excel formül motoru (tokenizer, parser, derleyici, fonksiyonlar, sayı biçimleri, içe aktarıcı)
tto/marketdata/    Bloomberg (blpapi) ve kayıtlı veri sağlayıcıları; bbg_process.py: Bloomberg oturumunu ayrı bir
                   yardımcı süreçte çalıştırır
tto/extras.py      dashboard'un kendi eklediği hesaplar (Excel formülü olarak: EK_FWD, EK_XAU, Borsa O/N)
tto/service.py     uygulama servisi (sayfalar, girdiler, senaryolar, RET, işlem defteri)
tto/history.py     günlük tarihçe: kapanışlar, PPK fiyatlama geçmişi (çözücüyü geçmiş günle besleyen ikinci motor),
                   gün sonu matrisi, toplantı takvimi (düzeltme, kaydırma, adımların toplantıyla taşınması)
tto/blotter.py     forward fiyatlama, OIS strateji bacakları, pozisyon maliyeti, DV01 (forward / OIS / tahvil) ve risk özeti
tto/xlsx.py        gün sonu arşivi için küçük .xlsx yazıcı (yalnızca değerler ve biçimler)
tto/server.py      HTTP API + canlı güncelleme (server-sent events)
tto/store.py       SQLite (kullanıcılar, girdiler, senaryolar, RET geçmişi, işlemler, günlük tarihçe)  →  data/tto.db
tto/bundled.py     kurulu değilse web paketlerini vendor/ altındaki wheel'lerden içe aktarır
tto/views/         sayfa tanımları: tablolar, girdiler, sekmeler ("sections") ve sekmelerin üstünde sabit duranlar ("pinned")
tto/data/          kayıtlı veri modunda kullanılan ek kotalar ve TLREF geçmişi (replay_*.json)
tto/static/        arayüz (derleme gerektirmeyen ES modülleri, kendi SVG grafikleri)
models/            içe aktarılmış çalışma kitapları        workbooks/   kaynak Excel dosyaları
vendor/            gömülü web paketleri (değiştirilmemiş PyPI wheel'leri; Python 3.8 / 3.9 / 3.10+ setleri)
tools/             parite, LibreOffice referansı, içe aktarma, kayıtlı veri kotaları, tek dosyalık kurulumun üretimi
kurulum/           tto_kur.py: dashboard'un tamamı tek düz metin dosyasında (ZIP inmeyen / taşınamayan yerler için)
tests/             test paketi
```

Yedekleme için `data/tto.db` dosyasını kopyalamak yeterlidir.
