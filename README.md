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
* **Ortak veriler:** RET faizleri, Günlük İşlemler ve Broker Chat bir kişi kaydedince herkeste anında görünür ve
  sunucu yeniden başlasa da kalır.
* **Excel ⇄ dashboard kopyala / yapıştır:** tablolar Excel'e, Excel'deki bloklar girdi hücrelerine doğrudan.
* **Hiçbir formül eksik değil:** dört kitabın her sayfasındaki her formül ve değer, sayfasının bir tablosundadır
  (görünen tablo ya da "Yardımcı tablolar"); bunu bir test denetler.
* **Excel'de olmayan ekler** de Excel formülü olarak yazıldı: bid / ask için ayrı OIS spread'li forward kotasyon
  matrisi, altın forward'ının altın swap faizinden (XAUSR) hesabı, O/N karşılıkları
  ([aşağıda](#dashboardun-kendi-ekledikleri)).
* **Geçmiş:** TRY OIS, offshore ve DİBS için **gün sonu matrisi** (1 gün / 1 hafta / 1 ay değişim), her PPK
  toplantısının **fiyatlama geçmişi** (zaman serisi, bir yıl geriye; yapılan toplantılar da saklanır), offshore − OIS
  ve VİOP − OIS **spread geçmişi** (z-skoru) ve **Ayarlar**'da toplantı takvimi ve carry'nin TLREF patikası
  ([aşağıda](#gün-sonu-matrisi-ppk-fiyatlama-geçmişi-ve-toplantı-takvimi)).
* **Kotadan işleme:** tablolardaki kotalar tek tıkla chat mesajı olur; bir kota ya da chat'teki bir işlem satırı
  Günlük İşlemler'i dolu açar.
* **FX opsiyon piyasası:** **Spot / FX** (bir paritenin vol yüzeyi – ATM, 25D / 10D risk reversal ve butterfly –,
  forward'ları – USDTRY offshore eğrisinden –, smile'ı, ima edilen yolu ve olasılık bulutu, vade × seviye olasılık
  matrisi) ve **FX Vol İzleme** (USDTRY, G10, çaprazlar ve masanın eklediği her şeyin vol'leri, skew'ü – RR / ATM –,
  değişimleri, tarihsel yeri, ısı haritası, vade yapısı ve skew grafikleri) ([aşağıda](#fx-spot--fx-ve-vol-izleme-sayfaları)).
  Bir satıra ya da hücreye tıklayınca geçmişi z-skoruyla çizilir – FX sayfalarında, Gün Sonu Matrisi'nde, İzleme ·
  Alarmlar'da ve Eğri Hareketi'nde ([aşağıda](#tıkla--grafik-bir-satırın-geçmişi)).

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

Bir paritenin FX vol ve forward puanı ticker'larını sınamak için (~70 kalem, tek istek):

```bash
python -m tto check-fx USDTRY
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

### Giriş ve kullanıcılar

Dashboard **isim ve şifreyle** açılır; giriş yapılmadan hiçbir sayfa ve veri gelmez (yalnızca giriş ekranı).
Senaryolar, kişisel girdiler ve kayıtlar bu hesapla saklanır.

* **İlk yönetici.** Hiç yönetici yokken dashboard'u **çalıştığı bilgisayarda** (`http://localhost:1057`) açınca giriş
  ekranı "İlk yönetici hesabı"nı sorar: yönetici adını ve şifresini orada bir kez siz belirlersiniz. Ağdaki başka bir
  bilgisayardan bu adım yapılamaz; şifre hiçbir dosyada, kodda ya da kurulum paketinde durmaz. Komut satırından da
  olur – unutulan bir yönetici şifresi de böyle yenilenir (dashboard açıkken bile; şifre ekrana yazılmadan sorulur):

  ```bash
  python -m tto yonetici "Ad Soyad"
  ```

  Veri klasörü farklıysa `--data-dir` ile verilir (dashboard'unkiyle aynı olmalı).
* **Hesap isteği.** Hesabı olmayan kişi giriş ekranında **Hesap isteyin**'e tıklar, ismini, bir şifre (en az 8
  karakter) ve isterse bir not yazar. İstek bir yöneticinin onayını bekler; onaylanınca o isim ve şifreyle girer.
  Önceki sürümde **yalnızca isimle** giren biri aynı ismi yazar: istek o hesabın şifresini belirler, onaylanınca
  kişisel girdileri ve senaryoları yerinde durur (reddedilirse hesap eski hâline, şifresiz döner).
* **Kullanıcılar sayfası** (*Araçlar → Kullanıcılar*, yalnızca yöneticiler görür; bekleyen istek sayısı menüde
  rozetle görünür): istekleri onaylama / reddetme, kullanıcı oluşturma (isim, ilk şifre, istenirse yönetici), yönetici
  yetkisi verme / alma, şifre belirleme, hesabı kapatma / açma. Son yöneticinin yetkisi alınamaz, hesabı kapatılamaz;
  kimse kendi hesabını kapatamaz. Şifresi değiştirilen ya da hesabı kapatılan kullanıcının açık oturumları sona erer.
  **Şifresi olmayan hesap yönetici yapılamaz** (o ismi isteyen biri yetkiyi kendi şifresiyle alırdı): önce şifre
  belirlenir; istekle sahiplenilen eski hesap da kullanıcı olarak açılır. Onay bekleyen istek en fazla 30 olur.
* **Sayfa gezgini** (herhangi bir sayfanın herhangi bir aralığı, formülleriyle) de **yalnızca yöneticilere** açıktır:
  menüde, Günlük İşlemler'in "Sayfanın tamamı" düğmesinde ve hücre bilgisinin "sayfası olmayan hücre" bağlantısında
  yalnız onlar görür, `/api/sheets` ve `/api/grid` başkasına 403 verir. Sayfaların kendi tabloları ve durum çubuğundaki
  hücre bilgisi (`/api/cell`) herkese açıktır; uzun yardımcı tablonun "tamamı gezginde" notu yalnız yöneticide çıkar.
* **Oturum** 7 gün geçerlidir (sağ üstteki menüden *Çıkış* ile daha önce biter); *Şifremi değiştir* aynı menüdedir
  ve hesabın **diğer bütün oturumlarını kapatır** (şifreyi öğrenen biri artık giremez; değiştirdiğiniz sayfa açık
  kalır). Aynı isimle art arda 5 yanlış şifre o ismi 1 dakika kilitler - aynı anda gönderilen denemeler de tek tek
  sayılır; eski şifrenin yanlış yazılması da sayılır.
* **Güvenlik.** Şifreler veritabanında yalnızca tuzlanmış PBKDF2-SHA256 özetiyle (600.000 tur) durur; oturum
  anahtarı tarayıcıda JavaScript'in okuyamadığı (HttpOnly, SameSite=Strict) bir çerezdedir, veritabanında yalnızca
  özeti tutulur. Betikler aynı anahtarı `Authorization: Bearer …` başlığıyla gönderebilir. Önceki sürümün `X-TTO-User`
  başlığı ya da `?user=` artık kimseyi içeri almaz. Tarayıcının **başka bir sayfadan** (başka site ya da bu
  bilgisayarın başka bir portu) gönderdiği değişiklik isteği reddedilir. İsimde görünmeyen karakter olamaz; tam
  genişlikte ya da ayrık yazılmış harf harfin kendisidir. Aynı anda en fazla 2 şifre denetlenir (yoğun deneme sunucuyu
  kilitlemez). Dashboard düz HTTP ile çalışır: şifre yerel ağda şifrelenmeden gider (HTTPS ayrı bir iş).

**Sayfalar.** Masa, OIS · PPK, Forward, VİOP, Borsa Swap, Carry & Roll, TM OIS, DİBS RV, DİBS ASW, Manuel Tahvil,
Bulk Bond, DV01 Risk, USD · FOMC, Hesaplayıcılar, Motor. Ek olarak **İzleme · Alarmlar** (her kullanıcının
izleme listesi: VİOP spread'i, kâğıt ASW'i, OIS, offshore, ifadeler, hücreler; z-skoru; seviye, hareket ve z-skoru
alarmları; günün masa notları), **Eğri Hareketi** (OIS, offshore, VİOP ve DİBS'in önceki kapanıştan / açılıştan /
referanstan değişimi, ısı haritası), **Tüm Kâğıtlar** (masanın bütün
TRY DİBS'leri; ★ ile trading listesine), **DİBS Trading** (trading listesinin özeti, T0 / T1 / T2 fiyatları, son
işlemler, ima repo, günün işlemleri), **Hazine İhalesi** (üç kâğıt için ihaleye gönderilecek kirli fiyat ve ihale
sonucu), **Günlük İşlemler**,
**Broker Chat** (broker'ların chat'te yazdığı kotalar), **Realized Vol · Carry** (yazılan enstrümanın gerçekleşen
oynaklığı ve fly'ların carry / vol grafiği), **Spread Geçmişi** (offshore − OIS vade bazında, VİOP − OIS kontrat
bazında; z-skoru, aralık, grafik), **Spot / FX** ve **FX Vol İzleme** (FX opsiyon piyasası; [aşağıda](#fx-spot--fx-ve-vol-izleme-sayfaları)) ve
herhangi bir sayfanın herhangi bir aralığını (formülüyle birlikte) gösteren **Sayfa gezgini**. Excel'deki "MOBIL MK",
"Ivır Zıvır", "YP DIBS" ve "USDTRY IYIX" sayfaları masa kullanmadığı için **kaldırıldı**: kitap yüklenirken modelden
çıkarılır, hesaplanmaz, Bloomberg'e sorulmaz (YP DIBS'in 18, Ivır Zıvır'ın 21, USDTRY IYIX'in 6 `BDP` çağrısı; IYIX'in
Refinitiv `RtGet` çağrıları da) ve Sayfa gezgini'nde yoktur. Başka
hiçbir sayfa bunlara başvurmaz; Excel dosyası ve model dosyası onları yine tutar (kitap yeniden içe aktarılsa da
dashboard'a gelmezler). Dosyanın ileride değişen bir sürümünde bunlardan birine başka bir formül başvurursa o sayfa
kaldırılmaz, başlangıçta günlüğe uyarı yazılır (`tto/books.py`, `REMOVED_SHEETS`). Ivır Zıvır'daki ihale hesabı
**Hazine İhalesi** sayfasına taşındı. Masa sayfasının üstündeki **Kısayollar** Excel'deki köprülerin aynısıdır: tıklayınca
ilgili sayfa açılır ve köprünün gösterdiği tablo ekrana gelir.

**Sekmeler.** Excel'de bir sayfada onlarca tablo yan yana ve alt alta durur; aradığını bulmak için sağa sola
kaydırmak gerekir. Dashboard'da çok tablolu sayfalar **sekmelere** ayrılmıştır ve bir seferde bir grup tablo
görünür:

| Sayfa | Sekmeler |
|---|---|
| Forward | **Hesaplayıcılar** (Interest 2 SP, SP 2 Interest, all-in, O/N karşılığı, basit ↔ bileşik, forward faiz, tarih yardımcısı …) · Forward fiyatları (USDTRY, EURTRY, serbest forward, vadelere göre TRY faizleri) · RET · Toplu fiyatlama · Eğriler · Offshore · Ticker'lar |
| VİOP | Kontratlar · **Hesaplayıcılar** (USDTRY kontratları, VİOP XAUTRY) · Altın · Takvim spread matrisleri · Geçmiş · baz (ima faiz ve OIS farkının tarihsel grafikleri) · Eğriler |
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
* Değişen değerin kısa süre yanıp sönmesi üst şeritteki **⚡** düğmesiyle kapatılıp açılır (tercih tarayıcıda
  hatırlanır). Üst şeritteki veri rozetine (**KAYITLI VERİ** / **CANLI**) tıklayınca *Veri kaynağı* penceresi açılır:
  bağlantı, abonelik ve istek sayıları ve **Bloomberg'in tanımadığı ticker'lar** – kalıplara gruplanmış (`TYB#D BFX#
  Curncy` gibi), sayıları, açıklamasıyla (ör. Borsa Swap'ın tanımsız vadeleri, ISIN'i boş tahvil satırı, listedeki bir
  kaynağın yayınlamadığı vade) ve onları soran hücrelerle ("Hücreye git"); liste kopyalanır ya da .xlsx indirilir.
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
* **Excel'de gizli sütunlar** varsayılan olarak gösterilmez ve kopyalanmaz (ör. VİOP'taki eğri tablolarının ticker sütunu): tablo
  Excel'de gördüğünüz haliyle kopyalanır. Tablo başlığındaki "+N gizli sütun" ya da "Yardımcı tablolar" düğmesi
  onları (ve ara hesap tablolarını) açar; açıkken kopyalanan blok Excel'deki sütun düzeniyle aynıdır.
* Alt durum çubuğu seçili hücrenin Excel formülünü, çoklu seçimde toplam / ortalama / adedi gösterir.

**RET faizleri.** Üstteki "RET faizleri" düğmesi (Forward sayfasının RET sekmesindeki "RET faizlerini düzenle /
kopyala" da aynı pencereyi açar):

* **Yükle** — Excel'deki RET tablosunu (yalnızca bid–ask sütunları ya da vade etiketiyle birlikte) kopyalayıp
  pencereye `Ctrl+V` ile yapıştırın.
* **Değiştir** — kutulara tek tek yazın ya da **kaydırın**: "Tümünü kaydır"a baz puanı yazın (`25`, `-50`). Her
  vadenin yanındaki **Kaydır (bp)** kutusu ne kadar kayacağını, **Yeni bid / ask** sütunu neye döneceğini gösterir;
  henüz hiçbir şey değişmez. **Sabit kalacak vadelerin** kutusunu silin (ya da 0 yazın: "sabit" görünür), bir vadeye
  farklı bir miktar da yazabilirsiniz; kendi satırında yazdığınız / sildiğiniz vadeye "Tümünü kaydır" artık dokunmaz
  (miktarı değiştirseniz de sabit kalır). *Bid + Ask / Bid / Ask* hangi tarafın kayacağını seçer. **Uygula** yeni
  değerleri kutulara yazar, "Temizle" kaydırmayı siler. Önizlemede kalmış bir kaydırma varken "Kaydet" çalışmaz.
  **Spread (bp)** sütunu her vadenin bid–ask farkını gösterir; bir tarafı değiştirdiğinizde (ya da tek tarafı
  kaydırdığınızda) kayıtlı eğrinin spread'i ve şimdiki yan yana yazılır: `20 → 30`.
* **Kopyala** — "Kopyala (tablo)" vade · gün · bid · ask sütunlarını Excel'e ya da e-postaya yapıştırılacak biçimde,
  "Kopyala (mesaj)" sohbet penceresine atılacak hizalı metin olarak (`1M    34,25 / 34,45`) panoya koyar. Kutularda
  ne görünüyorsa o kopyalanır; henüz kaydedilmemiş bir değişiklik varsa uyarır.
* **Kaydet** — eğri herkes için geçerli olur, veritabanında saklanır ve her yükleme (kim, ne zaman, hangi değerler)
  geçmişe yazılır; geçmişteki bir kayıt tek tıkla geri getirilebilir.

Aynı şey Forward sayfasındaki TRY RET tablosuna doğrudan yazarak / yapıştırarak da yapılır.

**Senaryolar.** "Senaryolar" düğmesi: o andaki kişisel girdilerinizin tamamını bir isimle kaydeder, yükler, siler.
Senaryolar kullanıcıya özeldir.

**Günlük İşlemler.** Soldaki formdan:

* **FX Forward** — parite (*USDTRY / EURTRY / Diğer*), yön, tutar (`10m`, `2,5 mio`, `10.000.000`), valör tarihi;
  fiyatlama: *RET bid / RET mid / RET ask / TRY faizi / Forward kur / Swap puanı*. Tarihi yazar yazmaz forward kuru
  ve **TL tutarı** hesaplanır (Forward sayfasının kendi hücreleriyle: valör `Forward!D2`'ye yazılmış gibi).
  * **USDTRY**: USDTRY tablosunun RET satırı (`Forward!D33:F33`); TRY faizi verilirse toplu fiyatlama satırının
    formülü, forward kur verilirse ima edilen TRY faizi.
  * **EURTRY**: sayfanın EURTRY tablosu (`Forward!D45:F45`; spot `G2`, gün sayısı EURTRY valöründen, EUR OIS eğrisi).
    TRY faizi verilirse sayfadaki çapraz forward bloğunun formülü (`spot·(1+r·g/360)/(1+r_EUR·g/360)`).
  * **Swap puanı** (her paritede): `forward = spot + puan / 10.000` – sayfanın "Swap Point" satırlarındaki birim.
    Puan Türkçe biçimde `17.400`, İngilizce biçimde `17,400` yazılabilir.
  * **Diğer** (minor para): kutuya döviz (`GBP`) ya da parite (`CHFTRY`, `EURUSD`) yazılır. Çalışma kitabında bu
    paraların eğrisi olmadığından fiyat elle girilir: forward kur, ya da spot + swap puanı (TRY'ye karşı paritelerde
    Bloomberg spotu varsa spot kutusu boş bırakılabilir). İma TRY faizi hesaplanmaz; TRY faizi DV01'i valöre kadarki
    TRY iskonto faktörüyle verilir. TRY'ye karşı olmayan paritenin (EURUSD) TRY riski yoktur.
* **OIS** — *Outright / Spread / Fly / FRA / MPC*; büyüklük DV01 ($/bp) ya da nominal (TL). Bacaklar OIS_MAIN'in
  kuralıyla boyutlanır (`ROUND(w·DV01·USDTRY/(Annuity·0,0001)/lot)·lot`, fly kanatları ½). Piyasa mid seviyesi ve
  **maliyet** (mid'e göre bp, $ ve TL) otomatik hesaplanır.
  * **MPC** (toplantı tarihli OIS): başlangıç *Spot* ya da bir toplantının etkin günü (karardan sonraki gün), bitiş
    daha sonraki bir toplantının etkin günü – OIS sayfasındaki "MPC OIS" tablosunun tarihleri. Piyasa seviyesi o
    tablonun "Piyasa (bootstrap)" sütunu (iki toplantı arası tek dönemde aynı sayı; daha uzun aralıkta sayfadaki
    "İki tarih arası simple rate" hesaplayıcısının bootstrap satırı, iki tarih yazılmış gibi). Nominal sayfanın
    "Nominal" sütunundaki kuralla: `DV01·USDTRY / (gün/365 · DF · 0,0001)`. İşlem listelerde iki tarihiyle
    anılır (`MPC 11.12.26–22.01.27`): toplantı geçince numarası değişir, tarihi değişmez.
* **Tahvil** — enstrüman (ISIN), yön, tutar, fiyat. Kâğıt DİBS RV tablosundaysa adı, vadesi, tablodaki temiz fiyatı,
  süresi ve DV01'i gösterilir.

**DV01.** Her işlemin DV01'i hem girerken (fiyat kutusunda) hem girdikten sonra (listelerde) görünür:

* Forward: Forward sayfasındaki "Forward DV01" bloğunun (`Forward!N31:P49`) formülü, işlemin kendi valörü, forward
  kuru ve tutarıyla: `DV01 (TL) = ± tutar · forward · T · DF_TRY / 10.000`, `DV01 ($) = DV01 (TL) / spot`; ayrıca USD
  faizi DV01'i. Tutar yazılmadan önce 1 mn USD içindir.
* OIS: bacak bazında DV01 ($, işaretli) ve işlemin **net** / brüt DV01'i.
* Tahvil: DİBS RV tablosundaki "DV01 TL / 1mn" sütunundan; tabloda olmayan bir kâğıdın DV01'i boş kalır ve özet
  satırında "DV01'i bilinmeyen işlem" olarak sayılır.

İşaret her yerde aynıdır: **payer +**. TRY faizi 1 bp artınca kazanan pozisyon artıdır (PAY, vadeli döviz alışı),
kaybeden eksidir (RECEIVE, vadeli döviz satışı, tahvil alışı). OIS bacakları da listede, fiyat kutusunda ve indirilen
dosyada bu işaretle yazılır (PAY bacağı +, RECEIVE bacağı −). EURTRY ve minor para forward'larında TRY faizi DV01'i
TL olarak aynı formülle hesaplanır ve USDTRY spotuyla dolara çevrilir. Listelerin üstündeki şerit görüntülenen
işlemlerin toplamını verir: Toplam · Forward · OIS (net) · Tahvil ($).

Kaydedilen işlem tüm kullanıcılarda anında görünür (kim, saat kaçta girdi bilgisiyle). Sağda işlem listeleri ve
**pozisyonun maliyeti** (valör / vade / enstrüman bazında net pozisyon, başabaş seviyesi `(A₁R₁−A₂R₂)/(A₁−A₂)` ve
gerçekleşen K/Z — Hesaplayıcılar sayfasındaki "Weighted Average" tablosunun aynısı), altta Excel'deki
Günlük İşlemler sayfasının kendi özet tabloları. "Fiyatı kopyala" ekrandaki fiyatı tek satır metin olarak panoya koyar.
Excel sayfasının tabloları her işlemi alır: **EURTRY / minor para forward'ları** forward listesine işlem anındaki
kurlarla **USD karşılığı** tutarla ve kendi TRY faiziyle (**TL maliyeti**) girer (TRY ayağı olmayan EURUSD gibi bir
parite girmez); **forward vade kovaları** tablosunun sağında her kovanın **DV01'i ($)** – alış, satış, net – sayfanın
tutarı kovalara bölüşü gibi bölünerek yazılır. **MPC tarihli OIS'ler** *OIS · vade özeti*nde **ana vadelere
dağıtılır**: S'den E'ye swap = E'ye kadar spot swap + ters yönde S'ye kadar spot swap (iki bacağın DV01'i toplamda
işlemin DV01'ine eşit, aynı nominal); her bacak tarihinin iki yanındaki ana vadeye gün oranında bölünür (S'nin
faizi eğrinin, E'ninki ikisini birlikte işlem faizi yapan faiz). Spot'tan başlayan MPC swap'ı tek bacaktır.

**Geçmiş günler ve tarih aralığı.** "İşlem günü" seçicisi geçmiş bir günü, yanındaki **Aralık** iki tarih arasındaki
bütün günleri gösterir (iki tarihi seçip "Göster"; hazır aralıklar: *Bu hafta*, *Bu ay*, *Son 30 gün*). Aralıkta her
satırın başında işlem günü yazar; maliyet ve DV01 özetleri aralıktaki işlemlerin toplamıdır. **Bugünü içeren bir
aralıkta** (*Bu hafta*, *Bu ay*, *Son 30 gün*) işlem formu açık kalır: girilen işlem bugüne yazılır ve listeye eklenir,
bugünün işlemleri silinebilir. Geçmişte biten bir aralık ya da geçmiş bir gün salt okunurdur ("Bugün" düğmesi geri
döndürür).

**Gün sonu arşivi.** Excel'deki `GunSonuArsivle` makrosunun (sayfayı değer olarak `Blotter_yyyy.aa.gg.xlsx`
dosyasına kaydedip listeleri temizleyen düğme) karşılığı: "Gün sonu arşivi (.xlsx)" seçili günü aynı adla indirir.
Dosyanın ilk sayfası Günlük İşlemler sayfasının Excel'deki yerleşimiyle, yalnızca değerlerden oluşan kopyasıdır
(makronun kaydettiği dosyayla aynı hücre adresleri); ikinci sayfada kimin, ne zaman, hangi işlemi girdiği ve
pozisyon maliyetleri vardır. Listeleri temizlemek gerekmez: her günün defteri ayrıdır, yeni gün boş başlar ve
geçmiş günler istenildiği zaman yeniden indirilebilir. Bir **aralık** görüntülenirken aynı düğme o aralığın işlem
listesini (her satırda günüyle), DV01 ve maliyet özetleriyle tek dosya olarak indirir
(`Blotter_yyyy.aa.gg-yyyy.aa.gg.xlsx`); Excel yerleşimindeki sayfa tek bir güne ait olduğundan o dosyada yoktur.

**İzleme · Alarmlar.** Piyasada ne izlenmek istenirse - bir seviye, bir spread, bir kâğıt, bunlardan kurulan bir
ifade - izleme listesine eklenir ve üzerine alarm kurulur:

* **Ne izlenebilir** ("Ekle · alarm kur…" penceresi; seçerken şimdiki değeri görünür):
  * **VİOP**: bir kontratın **OIS − VİOP** spread'i (bp: kontrat vadesindeki OIS ile VİOP ima TRY faizinin bid/ask
    ortası farkı), ima TRY faizi (bid / ask / orta), O/N repo, vadedeki OIS, fiyat. Kontrat **ticker'ıyla** (A1Z6)
    seçilirse o kontrat izlenir - kontratlar dönünce tablodaki yeri değişse de; **sırasıyla** ("1. kontrat")
    seçilirse vade dolunca bir sonrakine geçer. Vadesi geçen kontrat için "kontrat yok" yazar.
  * **Kâğıt** (ISIN'iyle; listedeki yeri değişse de o kâğıt): **ASW**, ASW eğrisi, **pahalı / ucuz**, Z-spread,
    getiri, getiri − OIS, ASW FX, pahalı / ucuz FX, C+R, temiz fiyat, BBG bid / ask, son işlem, T0 / T1 / T2 bid ve
    ask, T0→T1 repo ve repo − TLREF. DİBS RV'den gelenler için kâğıt trading listesinde (★) olmalı (değilse
    söylenir); bid / ask / son işlem listede olmayan kâğıt için Tüm Kâğıtlar'dan okunur.
  * **OIS** (TLREF, 1W, 2W, 1M–10Y), **Offshore** (Forward sayfasındaki FX swap ima TRY faizi; bid / orta / ask),
    **Masa** özeti (USDTRY, TLREF, ima 1Y sonu TLREF, ima 12A, ima / PPK).
  * **İfade**: bunlardan kurulan herhangi bir şey - köşeli parantezde adlar, hücre adresleri, sayılar, + − * / ve
    parantez: `[OIS 2Y] - [OIS 1Y]`, `2*[OIS 5Y] - [OIS 2Y] - [OIS 10Y]`,
    `[VİOP 1. kontrat OIS − VİOP] - [VİOP 2. kontrat OIS − VİOP]`, `[15.03.28 ASW] - [13.09.28 ASW]`,
    `[15.03.28 getiri] - [OIS 2Y]`, `'DİBS RV'!Z8 - 'DİBS RV'!Z9`. Adlar pencerede seçilip **"İfadeye ekle"** ile de
    yazılır (büyük / küçük harf, Türkçe harf farkı önemsizdir; kâğıt kısa adıyla ya da ISIN'iyle). Birimi kendisi
    bulunur: faizlerin farkı (spread, fly) **bp**, ortalaması faiz (%); bp'lerin farkı bp; iki kotanın oranı ya da
    farklı birimlerin karışımı düz sayı.
  * **Hücre**: herhangi bir tabloda hücreye **sağ tık → "İzlemeye ekle" / "Alarm kur…"**. DİBS RV, DİBS Trading, Tüm
    Kâğıtlar, VİOP, OIS ve Forward'daki hücreler **gösterdikleri şey** olarak alınır (ör. DİBS RV'de bir ASW hücresi
    → o kâğıdın ASW'i; VİOP'ta "OIS - VIOP" satırı → o kontratın spread'i); diğerleri hücre olarak (adı satırından
    ve sütun başlığından gelir; birimi ⋯ ile seçilir).
  * **Hazır gruplar** tek tıkla: Masa, TRY OIS eğrisi, Offshore, VİOP OIS − VİOP (ilk 4 kontrat).
* **İzleme listesi** (her kullanıcının kendisi): her kalemde şimdiki seviye, günün **açılışı** (dashboard'un o gün
  gördüğü ilk değer), **gün içi değişim** (faiz ve spread'lerde bp, kurda / fiyatta kendi biriminde), günün **düşüğü /
  yükseği**, **gün içi çizgisi** (açılış kesikli çizgi), son hareketin saati ve **referanstan değişim**: "Referansı
  şimdi al" (hepsi ya da tek kalem, ⟲) o anki seviyeyi saklar - ör. sabah toplantısında; değişim ayrıca o andan beri
  gösterilir. Sıra (▲ ▼) ve ad (çift tık) değiştirilebilir; değeri olmayan kalemin nedeni adının altında yazar.
  Açılış, varsa günün piyasa açılışıdır (dashboard'un o gün ilk turda gördüğü değer); kalem gün içinde sonradan
  eklense de.
* **z-skoru ve tarihsel bant** (listede "z" ve "Bant" sütunları; başlıktaki **20g / 60g / 250g** ile pencere seçilir):
  z = (şimdi − ortalama) ÷ standart sapma, son 20 / 60 / 250 günlük kapanışa göre; bant o pencerenin en düşüğü – en
  yükseği, çizgi ortalama, nokta şimdiki seviye (|z| ≥ 2 sarı). Üzerine gelince ortalama, std, en düşük / en yüksek,
  yüzdelik ve kaç kapanış olduğu yazar. Kapanışlar: OIS, TLREF ve offshore için tarihçe deposu; bir ifadenin geçmişi
  parçalarının geçmişinden aynı hesapla (ör. `[OIS 2Y] - [OIS 1Y]` ilk günden z alır); diğer her şey (VİOP spread'i,
  ASW, kâğıt getirisi, hücreler…) için **dashboard'un kendi kaydı**: izlenen, alarm kurulan ve ısı haritasındaki her
  noktanın günün son değeri her gün saklanır (en az 15 / 20 kapanış birikince z çıkar; tarihçe ayarlarındaki seri
  sayılarına karışmaz).
* **Alarmlar**: "Ekle · alarm kur…", listedeki 🔔, ısı haritasında bir noktaya tıklayıp ya da sağ tık → "Alarm kur…".
  Üç tür:
  * **Seviye**: **≥** (seviyeye ulaşınca), **≤** (inince) ya da **kesişir** (hangi yönde olursa olsun geçince).
    Seviye **gösterildiği gibi** yazılır: faizde 35,50 (= %35,50), spread'de bp (OIS − VİOP için 250, ASW için -70),
    fiyatta fiyat.
  * **Hareket**: belli bir hareket yapınca - **açılıştan**, **şimdiki seviyeden** (alarmın kurulduğu an; yeniden
    kurulunca o an), **izleme referansından** (⟲) ya da **son N dakika içinde** (o sürenin en düşüğünden ya da en
    yükseğinden bu yana; 1–60 dk); **↑ yukarı**, **↓ aşağı** ya da **± iki yön**; büyüklük faiz ve spread'lerde bp,
    fiyatta / kurda kendi biriminde. Ör. "2Y açılıştan ± 15 bp", "VİOP A1Z6 OIS − VİOP 10 dk içinde ↑ 5 bp".
  * **z-skoru**: seçilen pencerede (20 / 60 / 250 gün) z **≥**, **≤** ya da **kesişir** (ör. "1Y2Y z(60g) ≥ 2").
    Pencerede şimdiki z ve kaç kapanış olduğu görünür.

  Bir not eklenebilir; pencerede "izleme listesine de ekle" seçiliyse kalem listeye de girer. Alarm listesinde koşul,
  şimdiki değer, hareket ya da z ve koşula kalan uzaklık yazar. Alarm çalınca **hangi sayfa açıksa** sarı bir uyarı
  çıkar (değer, hareket ve koşul), kısa bir ses çalar ve izin verildiyse tarayıcı bildirimi gelir; alarm bir kez
  çalar, "Yeniden kur" ile tekrar kurulur. Koşul kurulurken zaten sağlanıyorsa söylenir. Alarmlar her değişimden
  sonra (canlıda her tick'te, en geç birkaç saniyede bir) kişinin kendi hesabıyla (kişisel senaryosu dahil)
  denetlenir; tarayıcı kapalıyken çalan alarm, sayfa açılınca "Bugün çalan alarmlar"da görünür. Önceki sürümde
  kurulan hücre alarmları ve listeler aynen çalışır.
* **Masa notları**: günün notu (izlenecek seviyeler, sabah toplantısı, ihale, veri takvimi) - herkes görür, kimin ne
  zaman kaydettiği yazar; her gün yeni sayfa.

Gün içi çizgi ve açılış dashboard açıkken toplanır (yeniden başlatılınca açılış korunur, çizgi o andan devam eder).

**Eğri Hareketi (ısı haritası).** Masa grubunda: piyasanın bir bakışta nereye gittiği.

* **TRY OIS · offshore · fark**: vade vade (O/N–10Y) OIS (O/N'de TLREF), offshore (FX swap ima TRY; 1Y sütununda
  12M) ve **offshore − OIS** farkı.
* **VİOP**: her kontratın **OIS − VİOP** spread'i ve ima TRY faizi.
* **DİBS**: trading listesindeki kâğıtlar vadeye göre; getiri, ASW, pahalı / ucuz.
* Her hücrede değişim (bp, büyük) ve seviye (küçük); **kırmızı yükseldi, mavi düştü**, renk koyulaştıkça hareket
  büyür (ölçek, günün en büyük hareketine göre ±5 / 10 / 15 / 20 / 25 / 50… bp; açıklama üstte). Değişim neye göre:
  **Önceki kapanış** (OIS, TLREF, offshore için tarihçe; diğerleri için dashboard'un kendi kaydı - ilk gün boş
  kalır), **Açılış** (dashboard'un bugün gördüğü ilk değer) ya da **Referans** ("Referansı şimdi al" ile alınan
  seviyeler; ör. sabah toplantısı - kişiye özel, her gün yeni).
* Bir hücreye tıklayınca: **İzlemeye ekle**, **Alarm kur…**, **Hareket alarmı…**; üzerine gelince şimdiki seviye,
  karşılaştırılan seviye (kapanışın günü) ve değişim yazar.
* Isı haritası piyasanın (ortak hesabın) değerlerini gösterir: kişisel senaryo burada etkisizdir.

**Broker Chat.** Broker'ların chat'te yazdığı kotalar buraya yapıştırılır ya da yazılır; her satır okunur, saatiyle
ve gönderenle birlikte saklanır ve herkeste anında görünür. Soldaki kutuya chat yapıştırılınca altında **nasıl
okunduğu** hemen görünür (hiçbir şey kaydedilmeden); "Kaydet" (Ctrl+Enter) saklar. Okunan yazım biçimleri:

| Yazılan | Okunan |
|---|---|
| `12:15:38 18m ois 35.03/35.23` | 18M outright, bid 35,03 / ask 35,23, saat 12:15:38 |
| `18m ois /35.23 offer` · `2y3y4y ois 12/ bid` | tek taraf: eğik çizginin boş yanı "o tarafta kota yok" demektir, tahtada o taraf boşalır |
| `18m ois 35.23 offer` · `18m bid at 35.03` · `pay 18m at 35.03` | tek taraf, kelimeyle (öbür taraf olduğu gibi kalır) |
| `18m ois 35.03 bid 35.23 offer` · `… 35.03 bid, 35.23 offer` · `35.03-35.23` · `35,03/35,23` · `35.14 choice` | iki taraf ("choice": bid ve ask aynı seviye) |
| `6m OIS 90 bid` · `18m ois 10/14` · `6m 90/10` · `1y 35.60/80` · `18m 3503/3523` | büyük rakamı yazılmamış seviye tamamlanır: 35,90 · 35,10 / 35,14 · 35,90 / 36,10 (rakamı aşan kota) · 35,60 / 35,80 · 35,03 / 35,23 |
| `1y5y ois -64/-60` · `1v5y` · `1y vs 5y` · `1y/5y` · `1s5s` | **spread** (uzun − kısa, bp). "v" yazılmasa da iki vade spread'dir, FRA değil |
| `2y3y4y ois 12/14` · `2y/3y/4y` · `2s3s4s` | **fly** (2 × gövde − kanatlar, bp) |
| `9x12 33.80/34.10` · `9x12m ois fra` · `9m12m fra` | **FRA**: "AxB" yazımı ya da "fra" kelimesi |
| `1y1y 34.50/34.80` | forward (aynı vade iki kez spread olamaz) |
| `1y 35.00/35.20 18m 35.03/35.23 2y 35.26/35.46` | bir satırda birkaç kota (virgülle ayrılmış da olabilir) |
| `18m ois taken at 14` · `paid` · `mine` · `given at 03` · `hit` · `trades 35.14` | **işlem**: taken / paid / mine offer'ın alındığını, given / hit bid'e verildiğini söyler. Fiyat yazılmamışsa ("18m taken") o an duran kota alınır |
| `ref 18m ois offer` · `18m ois off` | kota geri çekildi (taraf söylenmişse yalnızca o taraf) |
| `care offer 6m1y OIS` | fiyatsız ilgi |
| `2yr ois 35.46 , oco with 18m 35.14 offer` | iki kota, aynı OCO grubu (taraf bir kez söylenmiş) |
| `1yr x 38.60/80` · `1v5y x 55 offer` | cross-currency (`x`, `xccy`, `ccs`); ürün yazılmamışsa OIS |
| `t/n 380/385` · `t/n 375/90` · `o/n 1175 bid` · `s/n 375 paid` · `t/n gvn` | **FX swap** (USDTRY swap puanı): o/n, t/n, s/n her zaman FX swap'tır; kısa yazılan offer bid'in son hanelerinin yerine geçer (375/90 = 375 / 390). Faiz gibi yazılmış seviye (`o/n 35.10 bid`) puan sayılmaz |
| `fx 2m 25 500/` · `fx 1m 12.750/13.000` · `2m pts 25500/600` | **FX swap**, vadeyle: `fx`, `pts`, `points`, `puan` kelimesi; binler boşlukla ya da noktayla |
| `15/3/28 550/575` · `16/4/31 100/200` · `mar28 .400/475` · `apr31 94.125 bid` · `April 31 100/125` · `Sep 34 625/700 for 50 mio` | **DİBS** (aşağıda): vade tarihi ya da ay-yıl kâğıdı bulur; kısa fiyat kâğıdın fiyatıyla tamamlanır (100,550 / 100,575) |
| `11/9/30 tlref 675/800 tdy` · `Jan30 tlref 98.650/750 nl` · `02/05/2029 cpi.t1 92.050` · `10/02/2027zc.t1 31.400` | TLREF / TÜFE / sıfır kuponlu (`zc`, `bono`, `kuponsuz`) kâğıt; `tdy`, `today` = T+0, `tom`, `.t1` = T+1 valör |
| `feb27 zc 31.45/40` · `feb27zc 45/40` · `jan27 zc 31.45 bid, 40 offer` | **zc = sıfır kuponlu** (bono ya da kuponsuz tahvil), **getiriyle**: bid getirisi ask'ten yüksektir, kısa yazılan ask bid'in altında tamamlanır (31,45 / 31,40; `05/95` = 35,05 / 34,95) |
| `15/3/28 550 traded` · `16/4/31 100 given` · `Dec28 tlref 100.050 trading` · `mar28 given` · `15/3/28 550 bidim refledi` · `16/4/31 aldi` · `15/3/28 any int?` | kâğıtta işlem, ref ve ilgi; Türkçe yazımlar da (bidim, offerim, aldı, verdi, refledi, ilginiz, bakarız) |
| `mar28 vs jul30 switch -45/-40` · `jul30 v mar28 -45 bid` · `mar28/jul30 sw -45/-40` · `15/3/28-10/7/30 trd -42` | **switch** (iki kâğıt): uzun vadelinin getirisi − kısanınki (bp); yazılış sırası ve bağlaç (`vs`, `v`, `into`, `/`, `-`) fark etmez; tür kelimesi yanındaki kâğıdındır (`jan30 tlref vs jul30`: TLREF'e karşı sabit kuponlu) |
| `mar28 200 vs jul30 750 switch trading` · `Sw int 9/1/30 775 offer vs 3/7/30 775 bid` | **bacak bacak switch**: her kâğıdın fiyatı kendi kotası gibi tamamlanır; switch seviyesi iki fiyatın DİBS RV ekranında getiriye çevrilmesiyle (bp) – TLREF / TÜFE kâğıtlarında iki fiyatın farkı |

Büyüklük ("in 50m", "100x100") ve kotaya ait olmayan kelimeler ("bal", "bid nl") satırın **Not**'unda kalır. Hiçbir
enstrüman içermeyen satır ("selam") metin olarak saklanır; "Metin satırlarını da sakla" kapatılırsa atlanır.

* **Saat ve gönderen.** Saat satırın başında, sonunda ya da telefondaki gibi mesajın altındaki satırda olabilir
  (`12:15`, `12:15:38`, `[12:15:38]`, `1:15:38 PM`). `İSİM: mesaj`, `İSİM (KURUM) says: mesaj`, `İSİM 12:15:38 mesaj`
  ya da tek başına bir isim satırı göndereni belirler; `13 Nov 2026`, `13.11.2026` gibi bir tarih satırı (ya da
  saatin önündeki tarih) altındaki mesajların gününü. Saati olmayan mesaja **girildiği an** yazılır (listede soluk). "Kaynak" kutusuna yazılan ad (örn.
  broker'ın kurumu) her satırla saklanır.
  Bloomberg IB'nin gün başlığı da (`Friday, November 13, 2026`; `13 Kasım 2026 Cuma` gibi haftanın günüyle
  yazılanlar da) günü belirler, yani dünün chat'i bugün yapıştırılsa da kendi gününe kaydedilir ("Tarih" kutusu
  yalnızca chat'te gün yazmıyorsa kullanılır). Haftanın günü tarihe uymuyorsa ya da tarih yarından sonraysa satır gün
  sayılmaz: tek başına yazılmış `15/03/2028` bir kâğıttır. IB'de bir yanıtın üstünde yanıtlanan mesaj tarihi, saati
  ve yazanıyla alıntılanır (`11/13/2026 15:34:22 İSİM: mesaj`). İsimlerin kendi satırında, mesajların saatle
  başladığı böyle bir chat'te (ya da hemen altında saatle başlayan yanıt satırı varken) bu satır yeni mesaj sayılmaz:
  yeniden kaydedilmez, altındaki satırların gününü ve yanıtın kimden geldiğini değiştirmez. Her satırı tarih, saat
  ve yazanıyla gelen bir dışa aktarım ise (üstünde bir isim satırı olsa da) satır satır okunur.
* **İsimler → kaynak ve taraf.** "İsimler · kaynaklar" listesi her gönderen adını bir kaynağa (ICAP, Tullett …) ve
  tarafa bağlar: **Broker** ya da **Biz** (masanın kendisi). Liste herkes için ortaktır ve saklanır; yapıştırılan
  chat'teki yeni isimler kutunun altında hemen atanabilir. Böylece yapıştırılan satırın bizim fiyatımız mı broker
  fiyatı mı olduğu bellidir: **bizim kotamız tahtanın bid / ask'ini değiştirmez**, ayrı "Bizim kota" sütununda durur;
  işlem kimden gelirse gelsin son işlemdir ("· biz" ile). Kayıtta *Taraf* sütunu ve Tümü / Broker / Biz süzgeci var.
  `trading`, `trding`, `trd`, `dealt`, `done` gibi yazımlar da işlem sayılır.
* **Büyük rakamın tamamlanması** sırayla şunlara bakar: aynı kotanın tam yazılmış öbür tarafı (`35.60/80`,
  `90/36.10`: ask bid'in altında olamaz) → aynı chat'te o enstrüman için daha önce söylenen seviye → o gün o saate
  kadar kaydedilmiş son seviye → dashboard'un kendi eğrisi → eğrinin veremediği enstrümanda (cross-currency)
  tarihçedeki son kapanış. **İki tarafı da kısa yazılmış kota birlikte tamamlanır** (`90/10`, `95/05`, `10/14`):
  ask, bid'in üstündeki ilk seviyedir (90'dan sonra 10, bir sonraki büyük rakamdadır; getiriyle kotede altındaki) ve kotanın ortası referansa
  en yakın düşen büyük rakam seçilir – 6M 35,88'deyken `90/10` = 35,90 / 36,10. Tamamlanan sayıların altı
  önizlemede noktalı çizilidir. İki türlü okunabilen ("36": 35,36 mı 36,00 mı?; referans iki rakamın tam ortasında),
  hiçbir referansı olmayan (yazıldığı gibi bırakılır), eğik çizgiyle kelimesi çelişen ("12/ offer") ya da bid'i
  ask'inden yüksek çıkan satırlar etiketlenir; yanlışsa seviyeyi tam yazmak yeter.
* **Tahta** her enstrümanın son durumunu gösterir: bid ve ask (ne zaman söylendiği üzerine gelince), son işlem
  (yeşil: offer alındı, kırmızı: bid'e verildi), **model** – dashboard'un kendi TRY OIS eğrisinin o enstrüman için
  verdiği seviye (outright: par; spread ve fly: par farkları, bp; FRA / forward: eğrinin forward'ı; kişisel
  senaryonuzla) – ve bid − model, ask − model farkları (bp). Bid modelin üstünde ya da ask modelin altındaysa fark
  vurgulanır. Satır sonundaki ≡ o enstrüman için söylenen her şeyi aşağıda listeler. **FX swap** satırlarında puanın
  **ima ettiği TRY faizi** (ACT/360) ayrı sütundadır: Forward sayfasının spotu, vadenin gün sayısı (offshore
  tablosundaki Bloomberg `DAYS_TO_MTY`; o/n bir Cuma'da 3 gün) ve o kadar günün USD faiziyle – bid tarafı USD ask'iyle,
  ask tarafı USD bid'iyle, Forward sayfasının forward'ı fiyatladığı gibi.
* **Tahtayı sıfırla** tahtadaki bütün kotaları kaldırır (kayıttaki satırlar silinmez): o ana kadar kaydedilenler -
  chat'teki saatleri ne olursa olsun - ve sonradan yapıştırılıp sıfırlamadan önce söylenmiş olanlar tahtaya gelmez;
  sonra söylenenler tahtaya yeniden gelir. Satırdaki ⟲ yalnızca o enstrümanı sıfırlar. Bugün olmayan bir günde o günün
  tamamı sıfırlanır. Son sıfırlama "geri al" ile geri alınır; sıfırlamalar herkes için geçerlidir.
* **Kayıt** chat'i söylendiği sırayla tutar (en yeni satır en altta ve görünür): saat, kimden, taraf (biz / kaynak),
  mesaj (yazıldığı gibi), enstrüman, tür, bid, ask, işlem / seviye, olay, satır girildiği andaki model seviyesi, not,
  FX swap'ta ima TRY faizi. **Sütun başlığına tıklayınca** o sütuna göre sıralanır (ikinci tık ters; tercih
  hatırlanır). Arama kutusu ve "Yalnızca kotalar" süzer; ✕ satırı siler; satır başındaki **kutular işaretlenip
  "Seçilenleri sil"** ile birkaç satır birlikte silinir (başlıktaki kutu görünen bütün satırları seçer).
* **Aynı chat ikinci kez yapıştırılırsa** günü, saati, göndereni ve metni aynı olan satırlar eklenmez; yalnızca
  yeni satırlar saklanır (önizlemede eskiler soluk görünür).
* Gün seçici ve **Aralık** Günlük İşlemler'deki gibidir; "Excel (.xlsx)" görüntülenen günün / aralığın tahtasını
  ve bütün satırlarını `BrokerChat_yyyy.aa.gg.xlsx` olarak indirir.

* **DİBS kotaları.** Satırdaki tarih (`15/3/28`, `06/01/2027.t1`, `10/02/2027zc`) ya da ay-yıl (`mar28`,
  `Jan30`, `April 31`, `Sep 34`) masanın TRY DİBS listesinden (aşağıda: *DİBS kataloğu*) kâğıdı bulur; `tlref`,
  `cpi`, `zc` kelimesi türünü söyler. **Ay-yıl tek başına önce sabit kuponlu kâğıt demektir** (`mar28`, `feb27`); o ayda
  sabit kuponlu yoksa ayın öbür kâğıdı anlaşılır (`jan30` → TLREF): önce TLREF, sonra TÜFE, sonra bono / kuponsuz; birden
  çoksa ekran fiyatı söylenen seviyeye en yakın olan ("kâğıt?" ve "sabit kuponlu değil" etiketleriyle). Tür yazılmışsa
  (`jan30 tlref`, `jun29 cpi`, `feb27 zc` ya da bitişik `feb27zc`) yalnız o tür aranır; o ayda o türden kâğıt yoksa satır
  "kâğıt yok" etiketiyle kalır (`dec29 tlref`), ayda hiç kâğıt yoksa ay-yıl da öyle. **`zc` sıfır kuponlu kâğıttır**
  (bono ya da kuponsuz tahvil; `bono`, `kuponsuz` da aynı) ve **getiriyle** kote edilir: kâğıt listede olmasa da seviye
  getiri sayılır, kuponlu bir kâğıda geçilmez. Getiride bid ask'ten yüksektir (`31.45/40` = 31,45 / 31,40); ters yazılan
  "bid > ask" etiketi alır. Tarih yazılınca o gün vadesi dolan kâğıt alınır (aynı gün birden çok türde kâğıt varsa tür
  kelimesi seçer: `10/02/2027` sabit kuponlu, `10/02/2027zc` bono). Kâğıdın ISIN'i satırla saklanır (tahtada ve kayıtta
  adın üzerine gelince). Virgülden sonra yazılan öbür taraf (`15/3/28 550 bid, 575 offer`) aynı kâğıdındır.
  Bono ve kuponsuzlar **getiriyle**, diğerleri **fiyatla** kote edilir. Kısa fiyatın büyük rakamı (`550` →
  100,550; `.60` → 100,600) şu sırayla bulunur: kotanın öbür tarafı → aynı chat'te o kâğıt için söylenen fiyat
  (ihale listesi dahil) → o gün kaydedilmiş son fiyat → **DİBS RV tablosundaki ekran fiyatı** → kâğıdın ekranı da
  kotası da yoksa vadesi en yakın **aynı tür kâğıdın** fiyatı (TLREF'ten TLREF, bonodan bono; 18 ay içinde;
  "yakın kâğıttan" etiketiyle: `jan28 tlref .725` yanındaki `13/10/27 tlref 100.650/.800`'den 100,725) → TLREF /
  TÜFE kâğıdında 100 ("100'e göre" etiketiyle). Sabit kuponlu bir kâğıt başkasının fiyatından tamamlanmaz (kuponları
  farklı); referansı yoksa yazıldığı gibi kalır ve etiketlenir. Bir ayda birden çok kâğıt varsa (`mar28`: 08.03.28
  %12,4 ve 15.03.28 %36,8) fiyatı ekrandakine en yakın olan, ekran yoksa kuponu en yüksek olan (gösterge) alınır;
  seviye bir kâğıdın ekranına yakın, öbürü olamayacak kadar uzaksa (ekranı uzak ya da kuponu çok farklı) etiket
  kalkar, iki TLREF gibi ayırt edilemeyenler "kâğıt?" etiketiyle kalır. Fiyat kotasının **ima ettiği getiri**
  (DİBS RV ekranından: ekran getirisi − (fiyat − ekran fiyatı) / (ekran fiyatı · mod. süre)) ayrı sütundadır.
* **Başlıklı liste.** `09:14:59 Auction prices:` gibi iki noktayla biten bir satırın altındaki saatsiz satırlar o
  mesajın satırlarıdır: saatini ve göndereni alır, Not'unda başlığı taşır ("Auction prices"). Boş bir satır ya da
  başka bir gönderen mesajı bitirir.
* **Switch.** İki kâğıtlı satır tahtada tek enstrümandır (`15.03.28 / 10.07.30`, tür "Switch (bp)"): bid / ask ve
  işlem uzun kâğıdın getirisi − kısanınki, bp. **Model** DİBS RV ekranındaki switch'tir (iki kâğıdın BIST bileşik
  getirisi farkı); son sütun kotanın **eğriye göre** yeridir: DİBS RV'nin "Pahalı/ucuz" sütununda (uydurulmuş ASW
  eğrisine göre, + ucuz) uzun kâğıdın kısaya göre farkı + söylenen seviyenin ekrandaki switch'ten farkı (seviye:
  işlem, yoksa bid / ask ortası). **+ ise uzun kâğıt ucuz** (uzunu al, kısayı sat); eğri değeri olmayan kâğıtlarda
  (bono, TLREF) ekrana göre fark yazılır. Bacak bacak yazılmış switch'in (`mar28 200 vs jul30 750`) seviyesi her
  bacağın fiyatından ekranla bulunan getirilerden hesaplanır (fiyat → getiri: ekran getirisi − (fiyat − ekran fiyatı)
  / (ekran fiyatı · mod. süre)). Üç kâğıtlı satırlar metin olarak kalır.
* **İşlem gir (⇢).** İşlem satırlarının ve bizim kotalarımızın (taraf *Biz*) sonundaki ⇢ Günlük İşlemler'i o satırla
  dolu açar: OIS (outright, spread, fly, FRA / forward), FX swap (USDTRY; vade valör olarak, `2M`) ve DİBS. Açılan
  pencerede seviye (işlem / bid / ask) ve **bizim yönümüz** seçilir. Yön satırdan önerilir: bizim kotamızda bid'imize
  satıldıysa biz alıcıyız (PAY · steepener · gövde PAY · USD al · kâğıt al), offer'ımız alındıysa satıcı; broker
  kotasında tersi (bid'e verdik: satıcı, offer'ı aldık: alıcı); işlem satırında offer alındıysa alıcı, bid'e
  verildiyse satıcı. Not alanına chat satırı, karşı taraf alanına broker'ın kaynağı yazılır; tutarı yazıp kaydetmek
  yeter. Listede olmayan bir vade ya da söylenmemiş yön uyarıyla bildirilir.

Anlaşılmayanlar: vade yerine toplantı adıyla yazılan kotalar ("dec mpc 3650/3700") ve tek kelimelik yanıtlar metin
olarak kalır.

**DİBS kataloğu ve ISIN ile ekleme.** Masanın Bloomberg listesindeki 77 TRY devlet iç borçlanma senedi (bono,
kuponsuz, sabit kuponlu, TÜFE'ye endeksli, TLREF'e endeksli; ISIN, vade, kupon) dashboard'la gelir
(`tto/data/try_bonds.json`). DİBS RV, DİBS ASW ve Bulk Bond tablolarının başlığındaki **"+ ISIN ekle"** bir
pencere açar: ISIN yazılır ya da yapıştırılır (birkaç tane: boşluk, virgül ya da satırla), DİBS RV ve ASW'de
katalog da listelenir (türe göre süzgeç, arama; listede olanlar işaretli). Kâğıtlar listenin son kâğıdının
**altına** eklenir (sonda yer kalmazsa aradaki boş satırlara); listede olanlar atlanır, kontrol hanesi tutmayan ISIN reddedilir. DİBS RV ve ASW listeleri
masanındır (herkes görür), Bulk Bond listesi her kullanıcının kendisinin. Türk DİBS ISIN'i vadesini taşır
(`TRT150328T24` → 15.03.2028).

**DİBS RV'de broker chat.** DİBS RV tablosunun sağında her kâğıt için o günün Broker Chat tahtası: bid, ask, son
işlem (yoksa tarafı söylenmemiş son seviye, örn. ihale fiyatı, soluk), son sözün saati, broker orta fiyatının ima
ettiği getiri ve **broker − ekran** farkı (bp; + ise brokerlar kâğıdı ekrandan ucuz görüyor). Tahta sıfırlanınca
bu sütunlar da boşalır; Excel'e aktarmada bu sütunlar yoktur (sayfanın hücresi değiller).

**Kâğıtların düzeni: Tüm Kâğıtlar → ★ → DİBS Trading.** Bütün kâğıtlar bir yerde, üzerinde çalışılanlar ayrı:

* **Tüm Kâğıtlar** masanın Bloomberg listesindeki 77 TRY DİBS'i türüne göre (bono, kuponsuz, sabit kuponlu, TLREF'e
  endeksli, TÜFE'ye endeksli), her türde vade sırasıyla gösterir: kupon, vade, kalan gün / yıl, Borsa İstanbul
  fiyatı (bid, ask, son işlem ve günü, hacim; bono ve kuponsuz kendi valöründe - `ISL0` -, diğerleri ertesi gün -
  `ISL1`; kaynaklar sarı hücrelerde), trading listesindekiler için DİBS RV'nin getirisi, ASW / DM'i, sinyali ve
  DV01'i, sağda bugünün Broker Chat tahtası ve ▸ kart. Üstte **kendi eklediklerimiz**: listede olmayan bir kâğıt (yeni
  ihraç) ISIN'iyle eklenir; Türk DİBS ISIN'inden vadesi okunur.
* **☆ / ★** kâğıdı **trading listesine** (DİBS RV - ve onunla DİBS Trading) koyar ya da çıkarır; herkes için. Eklenen
  kâğıt listenin son kâğıdının altına girer (masanın gruplar arasında bıraktığı boş satırlar boş kalır; sonda yer
  kalmayınca onlar kullanılır). Çıkarılan kâğıdın satırı boşalır, satırla birlikte kâğıda ait ne varsa silinir: kaynak
  kodu ve herkesin o satıra yazdığı manuel fiyat, kupon, repo (aynı satıra sonra giren kâğıda geçmesin diye).
* **DİBS Trading** sayfasının başındaki **özet**, trading listesini türüne ve vadesine göre gruplu tek bakışta verir:
  kâğıdın fiyatlandığı valör ve kaynağı, bid / ask, son işlem ve ne zaman olduğu (canlıda görüldüğü saat), DİBS
  RV'den getiri, ASW / DM, pahalı / ucuz, sinyal, mod. süre, DV01 / 1mn, C+R, T0→T1 ima repo, bugünün Broker Chat
  tahtası, ★ (listeden çıkar) ve ▸ (kart). Ayrıntı altta (valörler, günün işlemleri) ve DİBS RV'de.

**DİBS Trading · valörler.** Trading listesindeki her kâğıt (DİBS RV listesi; başlıktaki "+ ISIN ekle" aynı listeye
ekler) üç valörde yan yana: **T0** (aynı gün), **T1** (ertesi iş günü), **T2** - her valör bir Bloomberg fiyat kaynağıdır
(`ISL0`, `ISL1`, `ISLN`; sarı hücreye başka kod yazılabilir, boşaltılırsa varsayılan kullanılır). Her valörde bid, ask,
**son işlem fiyatı**, **son işlemin ne zaman olduğu** ve günün hacmi; ayrıca seçilen bir **ek kaynağın** bid / ask'i
(`BGN` ile başlar; bir broker'ın kodu yazılabilir) ve sağda o günün **Broker Chat** tahtası (bid, ask, son işlem,
saat). Son işlemin zamanı: canlıda dashboard o valörün son fiyatının değiştiğini ya da hacminin arttığını gördüğü an
"bugün 10:41:07" olarak yazar (aynı fiyattan işlem de hacmi artırır; ipucunda fiyat ve Bloomberg'in son işlem günü),
görmediyse Bloomberg'in `LAST_TRADE_DATE`'i. **İma O/N repo**: iki valörün kirli fiyatlarından (temiz orta + o
valördeki işlemiş faiz, Bloomberg `INT_ACC`), `(kirli₂ / kirli₁ − 1) · 365 / gün`, T0→T1 ve T1→T2; T0→T1'in TLREF'ten
farkı (bp). Repo yalnız **iki valörün fiyatı aynı güne aitse** (son işlemleri aynı gündeyse) hesaplanır: iki hafta
önceki bir T0 fiyatıyla bugünün T1 fiyatı bir repo söylemez; o zaman özet tabloda "–" görünür, üzerine gelince ve
kâğıt kartında nedeni (iki valörün son işlem günü) yazar. TÜFE'ye endeksli kâğıtta hesaplanmaz (TL fiyatı her valörün
endeks oranıyla değişir). Bir fiyat adımı
(0,005) bir günde yaklaşık 1,8 puan repo eder: sayı yönü ve büyüklüğü söyler. Kayıtlı veri modunda kâğıdın DİBS RV'de
fiyatlandığı valör (dosyanın değeri) görünür, diğer valörler canlıda dolar.

* **Bugünün DİBS işlemleri**: Broker Chat'te söylenen bütün DİBS işlemleri (saat, kâğıt, fiyat, ima getiri, alınan
  taraf, valör, kim söyledi) ve canlıda Bloomberg'de görülenler (hangi valörde, hangi kaynakta), en yenisi üstte.
* **Kâğıt kartı** (Tüm Kâğıtlar, DİBS Trading, günün işlemleri ve DİBS RV'deki ▸): kâğıdın bütün bilgisi tek pencerede - ne olduğu
  (tür, kupon, vade, kalan gün), valörlerdeki fiyatlar ve son işlemler, ima repo, Broker Chat tahtası ve o günkü bütün
  chat satırları, günün işlemleri, DİBS RV satırı (getiri, ASW, sinyal, süre, DV01, carry, gün içi aralık). Listede
  olmayan kâğıtta katalog bilgisi ve "DİBS RV listesine ekle" düğmesi.

**Hazine İhalesi** (Tahvil grubunda; `EK_IHALE`). Ivır Zıvır sayfasındaki ihale hesabının yerini alır: ihaleye
gönderilecek **kirli fiyat** ve ihale bitince **sonuç**, üç kâğıt için.

* **Valör ve kâğıt.** Üstte ortak **ihale valörü**; her kâğıda ISIN ve isterse kendi valörü yazılır. Kâğıdın adı, türü
  (sabit kuponlu / TLREF / TÜFE / bono), kuponu ve vadesi ile **o valördeki** birikmiş faiz, önceki ve sonraki kupon
  tarihi ve işlemiş gün sayısı Bloomberg'den gelir (`INT_ACC`, `PREV_CPN_DT`, `NXT_CPN_DT`, `DAYS_ACC`; `SETTLE_DT` =
  valör). Birikmiş faiz **burada hesaplanmaz**: valör kupon gününe denk gelirse Bloomberg birikmişi 0 verir ve sonraki
  kupona geçer, TLREF'in o dönemki kuponunu yalnız Bloomberg bilir. Bloomberg yanıt vermezse kirli fiyat çıkmaz
  (satırın üstünde nedeni yazar). Valörsüz kirli fiyat yoktur. (Excel'deki blokta ikinci kâğıdın ihale sonucundan
  başka bir kâğıdın birikmiş faizi düşülüyordu; burada her kâğıt yalnız kendi birikmişini kullanır.)
* **Teklifler** (kâğıt başına 5 satır). Nominal ve şu üçünden biri yazılır: **temiz fiyat**, **basit** ya da **bileşik
  getiri** (birden çoğu yazılırsa önce temiz, sonra basit; satır hangisini kullandığını yazar). Satır öteki ikisini,
  birikmişi ve **gönderilecek kirli fiyatı** (temiz + birikmiş, 3 haneye yuvarlanmış) ve TL tutarını (nominal × kirli /
  100) verir; altında toplam nominal, nominal ağırlıklı ortalama kirli / temiz fiyat, bunun getirileri ve toplam tutar.
* **Getiriler** DİBS RV'nin "BIST" tanımıyla, iki sayfa aynı getiriyi göstersin diye: sabit kuponluda basit getiri,
  kuponları dönem başına `(1 + y/f)` ile iskonto eden getiridir (dönemin kalan kesri Bloomberg'in önceki / sonraki
  kupon tarihinden; Newton yöntemi kupondan başlar), bileşik `= (1 + basit/f)^f − 1`; bono ve kuponsuzda basit
  `= (100/P − 1)·365/gün`, bileşik `= (100/P)^(365/gün) − 1`. Getiriden fiyat aynı formüllerin tersidir. **TLREF**'te
  getiri yoktur (kirli fiyat ve ihaledeki yer çıkar). **TÜFE**'ye endeksli kâğıt reel fiyat ve reel getiriyle; tutar
  Bloomberg'in valördeki endeks oranıyla (`IDX_RATIO`) TL'ye çevrilir.
* **İhale sonrası.** Açıklanan **asgari, ortalama ve azami** fiyat kirli olarak yazılır (teklif kirliyle verilir): üçünün
  temiz karşılığı ve getirileri; her teklif için **Gerçekleşti / Asgari fiyatta · kısmi olabilir / Gerçekleşmedi**
  (çok fiyatlı ihale: asgari fiyatın üstündeki teklif kendi fiyatından gerçekleşir), ortalamaya fark (fiyat ve basit
  getiride bp), min–maks aralığındaki yeri; asgari fiyattan kısmen karşılanan teklifin **gerçekleşen nominali**
  yazılabilir. Gerçekleşen tekliflerden **ortalama kirli ve temiz fiyatınız**, bunun basit ve bileşik getirisi, ihale
  ortalamasına farkı ve tutar; altında tek cümlelik özet.

Girdiler masa için ortaktır. Bloomberg yükü kâğıt başına bir avuç `BDP` (valör değişince yeniden); `BDH` yok. Kayıtlı
veri modunda Bloomberg yanıtı olmadığından sayfa boş kalır.

**Satır eklenen tablolar.** Bulk Bond tablosu 4 yerine 50 kâğıt alır (alttaki satırlar 6. satırın formülleridir,
ISIN'i boşken hiçbir şey istemez); Forward'daki toplu forward fiyatlama 20 yerine **100 valör** alır (EK_BULK:
sayfanın kendi formülleri, eğri ve faizler Forward sayfasından; ilk 20 satırın valörü ve manuel TRY faizi Forward
sayfasınınkidir, üzerine yazılabilir). Sayfa dolu satırları ve bir boş satırı gösterir; **"+ Satır"** bir boş satır
daha açar (tercih hatırlanır), **"Tümü"** hepsini gösterir.

**Realized Vol · Carry.** İki bölümü vardır; ikisi de dashboard'un günlük kapanış tarihçesini (Gün Sonu Matrisi'nin
kullandığı depo) kullanır.

* **Realized vol · yazdığınız enstrüman.** Kutuya, broker'ın yazdığı gibi enstrüman yazılır (virgülle ayrılmış
  birkaç tane olabilir): vade (`18m`), spread (`1y5y` – uzun − kısa), fly (`2y3y4y` – 2 × gövde − kanatlar),
  FRA / forward (`9x12`, `1y1y`), cross-currency için `x` (`5y x`), DİBS RV tablosundaki bir tahvil için ISIN'i
  (`TRT150328T24`: getirisi; TLREF'e endeksli kâğıtta fiyatı). Tablo her biri için seviyeyi, son günün
  hareketini (bp ve kendi vol'ü cinsinden: `+2,1 σ`) ve **realized vol**'ü verir: günlük değişimlerin (bp) standart
  sapması (Excel'in `STDEV`'i), son 10 / 20 / 60 / 120 / 250 değişim için; "yıllık bp" seçilirse `× √252`.
  Değişim, enstrümanın **bütün bacaklarının kapanışı olan** iki gün arasında alınır (tatil, "hareketsiz gün"
  sayılmaz); pencere dolmadıysa eldeki gün sayısıyla hesaplanır ve soluk gösterilir. Satırdaki 📈 düğmesi o
  enstrümanın seviye geçmişini ve kayan realized vol'ünü çizer. Forward / FRA seviyesi her günün par eğrisinden
  çeyreklik bootstrap'le hesaplanır (blotter'daki FRA formülü; Excel'in bugünkü forward'ından en çok ~2 bp sapar –
  hareketin büyüklüğü için yeterli, fiyat için değil).
* **Carry / vol · fly'lar.** Carry & Roll sayfasının "fly (gövde receive)" tablosundaki her fly için sayfanın kendi
  carry + roll-down değeri (ufuk A ve B; başlangıçta 1 ay ve 3 ay, Ayarlar'dan değişir; bp) ile fly seviyesinin realized vol'ü yan yana:
  `ufuk σ'sı = günlük σ × √(ufuktaki iş günü)`, **oran = C+R ÷ ufuk σ'sı**. Grafik her fly'ı bir nokta olarak çizer
  (yatay: ufuk σ'sı, dikey: C+R; + ise gövdeyi receive eden, − ise pay eden kazanır); tablo orana göre sıralıdır.
  "Spread" seçilirse aynı şey sayfanın spread (flattener) tablosu için yapılır. **z 3a / z 6a / z 1y**: bugünkü
  seviyenin son 60 / 120 / 250 kapanışın ortalamasından kaç standart sapma uzakta olduğu (piyasa seviyesi; yoksa son
  kapanış; |z| ≥ 2 vurgulu). İki tablodaki **bir satıra tıklayınca** o enstrümanın seviye ve vol grafiği çizilir.
  **Listem** seçilirse yukarıdaki kutuya yazılan enstrümanların (OIS vadesi – receiver, spread – flattener, fly –
  gövde receive; 1M – 10Y) carry + roll'u aynı vade motoruyla, yazıldığı sırayla hesaplanır (FRA ve XCCY için carry yok).
* **Carry'nin TLREF patikası** (*Ayarlar → Carry*). Carry = sabit bacağın ufka kadar tahakkuku − TLREF'in ufka kadar
  bileşiği; ufuktan önce ödenen kupon da aynı patikayla taşınır. Bileşik seçilen patikayla hesaplanır: **Bootstrap**
  (varsayılan: piyasa OIS eğrisinin iskonto faktörlerinden, Motor'un eğri düğümleri arasında log-doğrusal), **MPC
  ima** (kotaların ima ettiği PPK patikası), **S1 / S2 / S3** (OIS sayfasındaki senaryolar – Excel'in kendisi S1'i
  kullanıyordu) ya da **Sabit TLREF** (bugünkü TLREF ileriye sabit). Roll eğriyi bugünkü haliyle tutar. Seçim ve
  ufuklar (A / B, ay; OIS sayfasının "Ufuk A / B" girdileri) kullanıcıya özeldir; Carry & Roll sayfası, Realized
  Vol · Carry ve Listem hep bu ayarla hesaplanır, Carry & Roll'un başlığı hangi patikanın kullanıldığını yazar.

Tarihçe Bloomberg bağlıyken arka planda yaklaşık bir yıla tamamlanır; kayıtlı veride yalnızca dosyadaki son ay ve
1M–1Y vadeleri vardır (sayfa bunu söyler, geçmişi olmayan vadeleri içeren satırlar boş kalır).

### FX: Spot / FX ve vol izleme sayfaları

Menünün **FX** grubunda iki sayfa: bir paritenin opsiyon piyasası derinlemesine (Spot / FX) ve bütün pariteler bir
bakışta (FX Vol İzleme). Hesaplar `tto/fxvol.py` (smile ve dağılım, saf Python) ve `tto/fx.py`'dedir (veriler);
Excel formülü değildir – smile kalibrasyonu ve yoğunluk hücre formülüyle yazılamaz –, Realized Vol · Carry gibi.

**Kotalar.** Her vade için Bloomberg'in beş vol kotası, vol puanı: `USDTRYV1M BGN Curncy` (ATM), `USDTRY25R3M BGN
Curncy` / `10R` (risk reversal), `USDTRY25B1Y BGN Curncy` / `10B` (butterfly). Vadeler 1W 2W 1M 2M 3M 6M 9M 1Y 18M
2Y (vol ticker'ında yıl `1Y`, forward puanında `12M`). Fiyat kaynağı (`BGN`) masanın ortak ayarıdır (FX Vol İzleme →
Kendi ticker'larım → *Kaynağı değiştir*). Pariteler: USDTRY, EURTRY; G10: EURUSD, USDJPY, GBPUSD, USDCHF, AUDUSD,
USDCAD, NZDUSD, USDNOK, USDSEK; çaprazlar: EURJPY, EURGBP, EURCHF, AUDJPY, GBPJPY; ve masanın eklediği pariteler.
Ticker adları masanın terminalinde denendi (14.11.2026); `python -m tto check-fx USDTRY` bir paritenin bütün
ticker'larını tek istekte sorar (~70 kalem) ve hangilerinin var olduğunu tablo olarak yazar.

**Forward'lar.**

* **USDTRY**: Forward sayfasının **offshore eğrisinden** – ICAP ima TRY faizi ve USD OIS, "Serbest forward"
  listesinin formülüyle: `F = spot·(1 + TRY·g/360)/(1 + USD·g/360)`. Vadelerin tarihi ve TRY faizi `EK_FWD`'nin
  "TRY faizleri vadelere göre" tablosundan (USDTRY spot valörü + vade, masanın tatil takvimiyle), spot Forward
  fiyatları tablosunun spotu (üzerine yazılan spot o kişinin forward'ını değiştirir). Aynı tarihte Serbest forward
  listesindeki "Offshore" forward'ıyla birebir aynıdır (testle doğrulanır).
* **EURTRY** (TRY çaprazları): USD bacaklarının çarpımı, `F = F(EURUSD)·F(USDTRY)` – TRY tarafı yine offshore eğrisi.
* **Diğerleri**: Bloomberg spotu + forward puanı / 10^`FWD_SCALE` (`EUR1M Curncy`, `JPY1M Curncy`, çaprazlarda
  `EURJPY1M Curncy`); teslim tarihi spot valörü (iki iş günü) + vade, hafta sonu atlanarak.
* Vade süresi `T = gün / 365` (spot valöründen teslime; bugünden vade sonuna, iki uçtaki iki günlük kayma dışında
  aynı).

**Kotaların anlamı (piyasa kuralları).**

| Pariteler | Delta | Delta tipi | ATM |
|---|---|---|---|
| EURUSD, GBPUSD, AUDUSD, NZDUSD | primsiz (`N(d1)`) | 1Y'ye kadar spot, sonrası forward | DNS |
| USDJPY, USDCHF, USDCAD, USDNOK, USDSEK, G10 çaprazları | primli (`(K/F)·N(d2)`) | 1Y'ye kadar spot, sonrası forward | DNS |
| USDTRY, EURTRY (ve eklenen EM pariteleri) | primli | her vadede forward | DNS |

Spot delta = forward delta × baz dövizin iskonto faktörü (USD için TRY kitabının USD OIS'i; EUR, GBP, AUD, NZD için
kendi USD paritesinin `F/S`'i × USD). ATM delta-neutral straddle'dır (primli deltada `K = F·e^(−σ²T/2)`).
**Risk reversal** smile'ın kendi 25-delta call ve put strike'larındaki vol farkıdır; **butterfly market (broker)
strangle'dır**: ATM + BF tek vol'le, o vol'deki 25-delta strike'larda fiyatlanan strangle – smile aynı strangle'ı aynı
fiyatlamalıdır (smile'ın kendi 25D kanatlarının vol'ü "ATM + BF ± RR/2" değildir; USDTRY gibi çarpık bir paritede fark
büyüktür).

**Smile.** Varsayılan **SVI** (Gatheral; toplam varyans, log-moneyness): beş kotaya en küçük kareler (ATM ağırlığı en
yüksek, 10D kanatlar en düşük), Gatheral'ın kelebek arbitrajı koşulu `g(k) ≥ 0` ve Lee'nin kanat sınırı ceza olarak –
smile hiçbir yerde negatif yoğunluk vermez. G10 smile'larını kotaya oturtur; USDTRY'nin orta kotaları kendi aralarında
arbitrajsız olmayabilir, o zaman en yakın arbitrajsız smile alınır. Masanın terminalindeki USDTRY 1M kotalarıyla:
ATM, 25D RR ve BF ile 10D RR'de sapma < 0,1 vol, 10D BF'de ~0,3 vol (BGN alış–satış farkı 25D BF'de ~1 vol).
Karşılaştırma için **SABR** (β = 1; ATM tam, ρ ve ν en küçük kareler) ve **Vanna-Volga** (25D pillar'lar) seçilebilir;
USDTRY'de SABR 25D RR'yi ~0,6 vol kaçırır ve yoğunluğu negatife düşebilir, VV'nin 10D kanadı ~4 vol uzaklaşır – bu
yüzden varsayılan SVI'dır. Seçilen model bir vadede arbitrajlıysa sayfa söyler. Kalibrasyon kotalar değişince yapılır;
spot oynadığında (forward değişince) aynı smile moneyness'te taşınır – bütün koşullar strike'a yalnız `K/F` üzerinden
bağlı olduğu için bu yaklaşık değil, kesindir.

**Dağılım.** Fiyatlar iskontosuz (forward ölçüsü) olduğundan vade sonundaki spotun **risk-nötr** dağılımıdır:
`P(S_T > K) = N(d2) − F·n(d1)·√T·σ'(K)` (Breeden–Litzenberger, birinci türevden). Ortalaması forward'dır: USDTRY'de
bulutun merkezi faiz farkı kadar yukarıdadır – gerçek dünya olasılığı değil, opsiyon piyasasının fiyatladığıdır. Her
vadede toplam olasılık, ortalamanın forward'a uzaklığı ve yoğunluğun hiçbir yerde negatif olmadığı denetlenir
("Yoğunluk" sütunu).

**Spot / FX sayfası.**

* **Pariteler · spot ve vol**: her paritenin spotu, son kapanışa göre değişimi, ATM 1W / 1M / 3M / 1Y, 25D RR 1M / 3M,
  25D BF 1M, 10D RR 1M, **1M ↑1σ / ↓1σ** (skew dahil, aşağıda; yalnız ATM ile ±1σ = spot × ATM 1M × √(30/365)
  hücrenin ipucunda) ve günlük başabaş hareket (spot × ATM 1M / √252). Satıra tıklayınca parite açılır (USDTRY
  varsayılan; seçim hatırlanır); bir vol hücresine tıklamak o vadeyi "Vade geçmişi"nde de açar.
* **Vol yüzeyi**: vade, teslim tarihi, gün, forward, beş kota, smile'ın kendi 10P / 25P / 25C / 10C vol'leri (üzerine
  gelince strike), **↑1σ / ↓1σ**, dağılımın %5 / medyan / %95'i, **Uyum** (modelin kotalardan en büyük sapması, vol
  puanı; ayrıntısı üzerine gelince) ve **Yoğunluk** denetimi. Satıra tıklayınca o vade "Vade geçmişi"nde çizilir (smile
  ve yoğunluk da o vadeye geçer). Bir kotaya ya da forward'a **çift tıklayınca** kendi değerinizi
  yazarsınız ("ya şöyle olsa" ya da Bloomberg'den gelmeyen kota): yalnız sizin görünümünüzü değiştirir, hücre mor olur,
  boş bırakınca Bloomberg'e döner; "N kota sizin · Bloomberg'e dön" hepsini siler. Kayıtlı veri modunda (Bloomberg
  yokken) kotalar böyle elle yazılarak da hesap yapılır.
* **Vade geçmişi**: seçilen vadenin son bir yılı – ATM; 25D ve 10D RR ve BF; **skew (25D RR / ATM)** seviyesi, seçili
  pencerenin (3A / 6A / 1Y) ortalaması ve ±2σ bandı ve günlük z-skoru. İlk açılışta o vadenin beş kotasının
  kapanışları istenir (bir yıl geriye; sonra son günler).
* **İma edilen yol ve olasılık bulutu**: spotun son kapanışları, bugünden itibaren forward patikası (kesikli), medyan
  ve vade sonu dağılımının yüzdelik bantları (%1–99, %5–95, %10–90, %25–75; açılıp kapanır), bantlar vadeler arasında
  doğrusal. Ufuk 3A / 6A / 1Y / 2Y; matrisin seviyeleri grafikte noktalı çizgi. Üzerine gelince o tarihteki forward,
  medyan ve bantlar.
* **Olasılık matrisi**: satır vade, sütun fiyat seviyesi; **Üstünde** (vade sonunda seviyenin üstünde olma
  olasılığı), **Altında** ya da **Aralıkta** (iki seviye arası; uçlarda "<" ve "≥"). Seviyeler yazılır (`50 52,5 55`;
  paritesi için hatırlanır) ya da otomatik gelir (1Y dağılımının %5–%95 aralığında yuvarlak adımlar). Kopyalanır.
* **Smile ve yoğunluk**: seçilen vadenin smile'ı (vol – strike, pillar'larıyla) ve vade sonundaki spotun yoğunluğu
  (forward ve spot çizgileriyle).

**↑1σ / ↓1σ (skew dahil).** Vade sonundaki spotun dağılımının **%84 yüzdeliği − forward** ve **forward − %16
yüzdeliği**: normal dağılımda bir standart sapmaya denk gelen olasılıklar, smile'ın çarpıklığıyla birlikte. Smile yoksa
lognormal yasanın bir sigması çıkar (testle doğrulanır); yalnız ATM vol'le hesaplanan ±1σ simetriktir ve karşılaştırma
için ipucunda yazar. Dağılımın ortalaması forward'dır: **USDTRY**'de uzun bir sağ kuyruk (büyük yukarı sıçrama
olasılığı) ortalamayı gövdenin üstüne çeker; ↑1σ küçülür – eksi bile olabilir, yani %84 yüzdelik forward'ın altındadır
– ve ↓1σ büyür (USDTRY'nin kısa vadelerinde ↑1σ sıfıra yakın çıkabilir; ikisinin toplamı da yalnız ATM'nin
±1σ'sından belirgin dar). Kuyruğun kendisi %95 / %99 yüzdeliklerinde görünür. EURUSD gibi bir G10 paritesinde ikisi ATM'nin sigmasına yakındır.

**FX Vol İzleme sayfası.** Üstteki düğmelerle her bölüm gösterilir ya da gizlenir (tercih tarayıcıda hatırlanır);
**Pencere** (3A / 6A / 1Y = 63 / 126 / 250 kapanış) z-skoru, yüzdelik ve aralığın penceresidir.

* **Özet**: her parite bir satır: ATM 1M / 3M / 1Y, 25D RR 1M / 3M, 25D BF 1M, 10D RR 1M, **25D RR / ATM 1M** (skew)
  (seviye ya da Δ1G / Δ1H / Δ1A; renk penceredeki z-skoru, kırmızı yüksek / mavi düşük), skew'ün penceredeki z'si, ATM
  1M'nin z 3A'sı ve yüzdeliği, **ima − gerçekleşen** (ATM 1M − spotun 21 günlük gerçekleşen vol'ü), **eğim** (ATM 1Y −
  ATM 1M) ve ATM 1M'nin bir yıllık çizgisi. Bir kotaya (spot dahil) tıklayınca geçmişi "Seçili seri"de çizilir, parite
  adına tıklayınca parite ayrıntıda açılır.
* **Isı haritası**: parite × (ATM 1W 1M 3M 6M 1Y · 25D RR ve BF 1M 3M 1Y · 10D RR ve BF 1M · **25D RR / ATM 1M 3M 1Y ·
  10D RR / ATM 1M**); hücrede seçilen ölçü (seviye, Δ1G, Δ1H, Δ1A, z, yüzdelik) ve seviye. Değişimlerde renk sütunun en
  büyük hareketine göre, z ve yüzdelikte tarihine göre. Hücreye tıklayınca o serinin geçmişi "Seçili seri"de çizilir
  (hücre çerçevelenir; parite ayrıntısı da o pariteye geçer).
* **Seçili seri**: tıklanan kotanın ya da skew'ün son bir yılı – seviye, seçili pencerenin ortalaması ve ±2σ bandı – ve
  her günün z-skoru; üstündeki satırda şimdiki değer, z, yüzdelik, ortalama, σ, aralık (tablolardaki sayıların aynısı).
  Pencere üstteki seçimdir. Varsayılan USDTRY 25D RR / ATM 1M; seçim hatırlanır.
* **Hareketler**: günün en büyük değişimleri (vol puanı) ve tarihsel uçta olanlar (|z| ≥ 1,5 ya da yüzdelik ≤ %5 /
  ≥ %95; skew'ler dahil). Satıra tıklayınca geçmişi çizilir.
* **Parite ayrıntısı** (pariteyi seçin; özet ya da ısı haritasında tıklamak da seçer): ATM vade yapısı, 25D / 10D RR
  ve BF vade yapısı, **skew'ün (25D RR / ATM) vade yapısı** ve seçilen vadenin smile'ı (10P … 10C) – bugün, 1 hafta ve
  1 ay önce (o günlerin kapanışlarından aynı yöntemle; RR / BF kapanışı olmayan gün çizilmez) –, ATM 1M / 3M / 1Y, RR,
  skew (1M / 3M / 1Y) ve BF'nin bir yıllık serileri, ima ve gerçekleşen vol.
* **Kendi ticker'larım** (masa için ortak): kutuya **parite** yazılırsa (`USDZAR`) o paritenin vol seti bütün
  tablolara girer (EM paritesi forward delta ile); **herhangi bir ticker** yazılırsa (sonunda sarı tuşuyla: `VIX
  Index`, `USDTRYV1M CMPN Curncy`) seviyesi, değişimleri, z'si, yüzdeliği ve aralığı izlenir. Ad verilebilir; ✕ çıkarır.
  Satıra tıklayınca geçmişi çizilir.

**Skew** = risk reversal ÷ aynı vadenin ATM vol'ü (**25D RR / ATM** 1M 3M 1Y, **10D RR / ATM** 1M; oran): call'ların
put'lara göre primi, vol seviyesinden arındırılmış – vol'ler genel olarak yükselip RR onlarla birlikte büyüdüğünde skew
değişmez. Kapanışları iki serinin aynı günkü kapanışlarının oranıdır (yeni Bloomberg isteği yok: ikisi de izlenen
setin içinde); değişim, z ve yüzdelik vol'lerle aynı tanımla.

**İstatistikler** Masa → Makro bloğunun ("MAKRO · risk göstergeleri") tanımıyla, her vol için: hafta içi günler (boş
gün önceki kapanışla, `Days=W, Fill=P`), pencere bugün − 366 … dün; **Δ1G / Δ1H / Δ1A** canlı değerin 1 / 5 / 21 iş
günü önceki kapanışa farkı; **z 3A** son 63 kapanışa göre `(son − ort)/std` (örneklem std'si, `STDEV`); **z**,
**yüzdelik** (penceredeki ≤ son kapanış payı) ve **aralık** seçili pencerede; |z| ≥ 1,5 vurgulu.

**Tarihçe.** Her vol'ün ve spotun günlük kapanışı (`PX_LAST`) dashboard'un tarihçe tablosunda `<ticker>|PX_LAST` adıyla
saklanır: bir seri ilk istendiğinde bir yıl geriye, sonra son on gün, en çok günde bir kez. FX Vol İzleme canlıda
açılınca izlenen set (parite başına 13 vol ve spot: 16 paritede ~220 seri; ilk gün bir kez), bir paritenin ayrıntısı
açılınca o paritenin bütün vadeleri (50 vol) istenir. `--no-history` ile çalışırken bu otomatik istek yapılmaz;
"Tarihçeyi güncelle" düğmesi her zaman çalışır.

### Tıkla → grafik: bir satırın geçmişi

Realized Vol · Carry'deki gibi, zaman serisi olan her tabloda bir satıra ya da hücreye tıklayınca o serinin geçmişi
çizilir (`tto/static/js/serieschart.js`): solda seviye, seçili pencerenin ortalaması ve ±2σ bandı; sağda her günün
**kendinden önceki pencereye göre z-skoru** (ilk 20 kapanıştan sonra), son nokta şimdiki değer; üstte şimdiki değer,
z, yüzdelik, ortalama, σ, aralık ve tarih aralığı. Seçilen satır işaretlenir; aynı satıra yeniden tıklamak ya da ✕
kapatır.

| Sayfa | Neye tıklanır | Ne çizilir | Pencere |
|---|---|---|---|
| FX Vol İzleme | ısı haritası hücresi, özetteki kota / spot, hareketler, kendi ticker'larım | vol, skew (RR / ATM), spot, ticker | sayfanın 3A / 6A / 1Y'si |
| Spot / FX | vol yüzeyinin satırı (ya da tablodaki bir vol) | o vadenin ATM, RR, BF ve skew'ü | 3A / 6A / 1Y |
| Gün Sonu Matrisi | OIS / offshore hücresi (tıklanan taraf), PPK satırı (tıklanan sütun: adım, seviye, kümülatif), DİBS satırı | tarihçe serisi (yedek kaynakla doldurulmuş, matrisin okuduğu gibi) | 3A / 6A / 1Y |
| İzleme · Alarmlar | listedeki kalem (ya da 📈), alarm | kalemin kapanışları (OIS, TLREF, offshore: tarihçe; diğerleri: dashboard'un kendi kaydı; ifade: parçalarından) | listenin "z / bant"ı (20 / 60 / 250) |
| Eğri Hareketi | nokta → "Geçmişini çiz" | noktanın kapanışları (İzleme'deki gibi) | 1A / 3A / 1Y |

İstatistikler yanındaki tablonun tanımıyla hesaplanır, sayılar birebir tutar (testle; tarayıcının modülü Node ile
çalıştırılarak): FX ve Gün Sonu'nda Makro bloğunun tanımı (hafta içi günler, boş gün önceki kapanışla; yüzdelik ≤
payı), İzleme'de listenin z'si (kapanışlar olduğu gibi, son N kapanış; yüzdelik altında kalanların payı; 1 aylık
pencerede en az 15, daha uzunda 20 kapanış). Yeni Bloomberg isteği yalnız Spot / FX'te bir vade ilk açıldığında
olur (o vadenin beş kotası; FX Vol İzleme'nin parite ayrıntısı zaten bütün vadeleri ister).

### Dashboard'un kendi ekledikleri

Bunlar Excel dosyalarında yok; ama dashboard'a "kod" olarak değil **Excel formülü** olarak eklendi
(`tto/extras.py`, kitap yüklenirken modele sayfalar: `EK_FWD`, `EK_XAU`, `EK_VIOP`, `EK_KAYNAK`, `EK_BULK`,
`EK_DIBS`, `EK_EVREN`, `EK_CARRY`, `EK_IHALE`; ASW kitabına `EK_FX`; Bulk Bond sayfasına 7–52. satırlar; Motor ve Carry & Roll'da carry patikası ve gün sayısı formülleri).
Aynı motor hesaplar, girdilere ve canlı veriye aynı şekilde bağlıdır, durum çubuğunda formülü görünür, Excel'e
kopyalanabilir.

**Forward fiyatları** (Forward sayfası, "Forward fiyatları" sekmesi; `EK_FWD` 44–96. satırlar). Dört tablo:

- **USDTRY** ve altında **EURTRY**, valör faizleriyle: her eğrinin (offshore = ICAP ima eğrisi, OIS, VİOP, RET) o
  valördeki **TRY bid / mid / ask** faizi, **forward bid / mid / ask**, **swap puanı** ve **günlük puan** (P/gün) bid /
  mid / ask; üstte valör, gün, spot ve USD (EUR) bid / mid / ask faizi. Faiz, spot ve döviz faizi üzerine yazılabilen
  hücrelerdir: değiştirince forward ve puanlar sayfanın kendi formülüyle (bid tarafı döviz ask'iyle, ask tarafı döviz
  bid'iyle) hemen yeniden hesaplanır; silince eğriye döner. Değiştirilmeden bırakılınca Forward sayfasının USDTRY /
  EURTRY tablolarıyla (USDTRY günlük puanları dahil) birebir aynıdır; sayfanın kendi tabloları yardımcı tablolardadır.
  EURTRY tablosunun TRY faizleri USDTRY tablosundakilerdir (orada yazılan faiz EURTRY'de de geçerli), yalnız EURTRY
  için ayrıca yazılabilir.
- **Elle** satırı: *Elle ayarı*nda bir eğri seçilir (offshore / OIS / VİOP / RET), sonra ya **mid %** ya da mid'e
  **spread (bp)** yazılır, istenirse bid / ask **genişliği (bp)**; boş bırakılan eğriden gelir (eğrinin mid'i, spread 0,
  eğrinin kendi bid / ask aralığı). Mid yazılınca spread'e bakılmaz. Elle satırının bid / ask'i de ayrıca yazılabilir.
- **Serbest forward** listesi: parite (USDTRY / EURTRY), başlangıç ve bitiş tarihi. Bitiş yazmak yeter: başlangıç
  paritenin spot valörü, **spot** (başlangıçtaki kur; başlangıç ileri bir tarihse spot, seçilen TRY eğrisi ve major OIS
  ile o tarihe taşınır), **major %** (USD / EUR OIS) ve **minor %** (listenin üstünde seçilen TRY eğrisi) başlangıç →
  bitiş arası basit ACT/360 faiz olarak eğrilerden gelir; üçünün de üzerine yazılabilir. Forward = spot·(1 + minor·gün/
  360)/(1 + major·gün/360), swap = (forward − spot)·10000. Yanında dört TRY eğrisinin **bitiş tarihindeki simple zero
  faizi** (offshore, OIS, VİOP, RET). Dolu satırlar ve üç boş satır görünür ("+ Satır" bir tane daha açar).
- **TRY faizleri vadelere göre**: valör, 1W–2Y ve kendi yazdığınız tarihlerde offshore, OIS, VİOP ve RET'in **simple
  zero** (ACT/360) mid faizi yan yana ve OIS'e farkları (bp). Gün ve vadeler USDTRY spot valöründen; faizler Forward
  sayfasının kendi düğümlerinden doğrusal. Bir eğri son düğümünden bir aydan uzak tarihte faiz vermez (düz uzatmak
  yerine boş kalır: VİOP ~1 yıl, RET 2 yıl), serbest forward listesinde de.

Excel'in eski "serbest forward listesi" (Forward!A24:H27) ve USDTRY / EURTRY tabloları yardımcı tablolarda durur.
Önceki sürümün vade faizi tablosunda (`EK_FWD` 33–42. satırlar) yazılmış değerler yeni düzende yanlış hücreye
düşmesin diye yüklenirken silinir.

**Veri kaynakları — Bloomberg fiyat kaynağı sırası** (`EK_KAYNAK`, *Ayarlar → Veri kaynakları*). Her eğri için en çok
dört fiyat kaynağı (pricing source) sırayla denenir, fiyatı olan ilk kaynak kullanılır, en sonda her zaman Excel'deki
ticker: **TRY OIS** `GFOF` → Excel'deki `kök Curncy` (BGN), **offshore FX swap ima** ve **XCCY** `ICPL` (ICAP) →
Forward sayfasındaki `… BGN Curncy`. OIS'te önce `MID`, yoksa `PX_LAST`; offshore'da bid **ve** ask'i olan kaynak
alınır (bir satır iki kaynağı karıştırmaz). Sıra herkes için ortaktır; kaynak eklenebilir (`BGN`, `CMPN`, `TRPU` …),
çıkarılabilir, sırası değiştirilebilir. Aynı sıra tarihçede de kullanılır. Ayarlar'daki *Şu an kullanılan kaynak*
tablosu her vadenin hangi kaynaktan, hangi ticker'la geldiğini gösterir. Kayıtlı veri modunda sayfalar dosyanın
değerlerini gösterir (OIS sayfası ve Forward tabloları Excel'in kaydettiği değerde kalır).

**Forward kotasyon matrisi — OIS + spread, bid ve ask ayrı** (Masa sayfası, "Forward fiyatlama"nın altında).
Vadeler 1M / 2M / 3M / 6M / 9M / 12M (valör formülle gelir, üzerine yazılabilir) ve dört serbest tarih.
"Tümü" satırına bid ve ask için **ayrı** OIS spread'i (bp) yazılır; bir vadenin kendi spread'i o satıra yazılır
(silince genele döner). Her satırda: valör, gün, spot bid / ask, **puan bid / ask**, forward bid / ask, OIS %,
TRY bid / ask %, USD %, günlük puan, RET bid / ask % ve aynı valörde RET'le çıkan puana fark.
OIS eğrisi listeden seçilir (MPC ima, S1–S3, Ağırlıklı, Bootstrap, TLREF sabit; seçilen S1–S3'ün hangi senaryo
olduğu – Baz / Hawkish / Dovish ve olasılığı – yanında ve tablonun altında yazar) ve Masa'daki "Tarih arası faiz"
bloğunun iskonto faktörleriyle aynıdır: aynı tarih ve spread'de iki blok aynı TRY faizini verir.
`Fwd bid = spot bid·(1+TRY bid·g/360)/(1+USD·g/360)`, ask tarafı spot ask ve TRY ask ile.
Altındaki **Puan → OIS spread** tablosu tersini yapar: elle verdiğiniz bid / ask puanının ima ettiği TRY faizini ve
OIS'e göre kaç bp olduğunu gösterir.

**Piyasa spread'i.** "Tümü" satırındaki seçim **Elle spread** (yazdığınız spread'ler) ya da **Piyasa spread**: her
vadenin bid / ask spread'i offshore ima eğrisinin (Forward sayfasının ICAP eğrisi) o valördeki bid / ask faizi − OIS
(bp). Son iki sütun (*Piyasa bid / ask*) her vadenin piyasa spread'ini seçimden bağımsız gösterir; eğrinin bittiği
yerden ötede boştur. EURTRY matrisi seçimi USDTRY'ninkinden alır (ayrıca değiştirilebilir).

**EURTRY** için aynı matris USDTRY'ninkinin hemen altındadır (`EK_FWD` 100–115; puan → OIS spread'i 117–129): aynı
OIS eğrileri (aynı tarihte USDTRY matrisiyle aynı TRY OIS faizi), spot olarak Bloomberg EURTRY bid / ask (yazılabilir),
gün EURTRY spot valöründen (vadeler de oradan: 1M … 12M ve dört serbest tarih), döviz faizi EUR OIS eğrisinden – Masa'nın
kendi forward tablosunun EURTRY için kullandığı faiz ve gün. Eğri ve "Tümü" spread'leri başlangıçta USDTRY matrisinden
gelir (orada değişince EURTRY de değişir); EURTRY için ayrıca seçilip yazılabilir, silince yeniden USDTRY'ninkine döner.
`Fwd bid = spot bid·(1+TRY bid·g/360)/(1+EUR·g/360)`.

**Kota mesajı ve İşlem gir.** Forward fiyatları (USDTRY / EURTRY), Masa'daki iki forward kotasyon matrisi, OIS
sayfasının kotalar tablosu ve DİBS RV tablosunun başlığında **Kota mesajı** düğmesi vardır: seçilen satırlar ve bir
sütun takımı (puan, outright, TRY %, P/gün; OIS'te par – istenirse bp genişlikle mid ± yarım genişlik; DİBS'te
BBG fiyatı, basit getiri, ASW / DM) chat'e yapıştırılacak bir mesaj olarak hazırlanır (`USDTRY · puan · 05.11.2026`
başlığı, sonra her satır `1M   15.115 / 16.357`) ve tek tıkla kopyalanır; seçim tablo başına hatırlanır, sayılar
tabloda göründüğü gibidir (değiştirdikleriniz dahil). Forward tablolarındaki **İşlem gir** bir satır ve yön seçtirir
(kotayı veren masa olarak: *USD al · bid puan* / *USD sat · ask puan*) ve Günlük İşlemler'i parite, yön, valör ve
swap puanı dolu açar; tutarı yazıp kaydetmek yeter.

**OIS Kontrol'ün gün sayıları masa takvimiyle.** Motor'un eğri düğümlerinin gün sayısı (89–130. satırlar)
Bloomberg'in `DAYS_TO_MTY` alanı yerine düğümün kendi tarihinden (WORKDAY(EDATE(…)), masanın tatil takvimi) sayılır.
Hafta içi ikisi aynı günü verir; hafta sonu ve tatilde Bloomberg'in kaydırdığı gün sayısı yüzünden OIS Kontrol'de
görülen hayalet "HATA" artık çıkmaz.

**DV01 Risk: pozisyon sıfırdan başlar.** Dosya, kaydedildiği günün masa pozisyonlarını taşır (kova DV01'leri
`DV01_RISK!C6:C25` ve yanındaki Onshore / TLREF yapıştırma alanı `X33:Y52`); bugün kimsenin pozisyonu olmayan bu
değerler yerine sayfa **sıfır** pozisyonla açılır. Her kullanıcı kendi pozisyonunu yazar ya da yapıştırır (kişisel
girdi, önceden yazılmış olanlar korunur); "girdilerimi sıfırla" yine sıfıra döndürür.

**Boş başlayan girdiler: PPK ima adımları ve VİOP Target.** Dosyanın kaydedildiği günün seçimleri bugün kimsenin
seçimi değil: OIS · PPK → *PPK ima* sekmesindeki toplantı başına senaryo adımları (S1 / S2 / S3, `OIS_MAIN!U10:W89`)
ve VİOP'taki **Target** tablosu (Yakın, Uzak, Yön, Hedef tipi, Hedef değer; `VIOP!L331:P338`, Masa sayfasında da
görünür) her kullanıcıya **boş** gelir. Boş adımda sayfanın kendi kuralı geçerlidir: senaryo tabanı (`B3`: ima yol ya
da sıfır) ve kaydırma (`D3`). Kullanıcının yazdığı değerler kendisinin kalır. Takvim değişikliklerinin eskiden ortak
girdi olarak taşıdığı dosya adımları bu sürümün ilk açılışında bir kez temizlenir.

**VİOP matrisinin DV01'leri kendi para biriminde** (VİOP → Takvim spread matrisleri → *Matris sürücü satırları*).
Her kontrat için 1 mn USD başına: **DV01 TRY (TL)** – TRY faizindeki 1 bp'nin kontrat fiyatına etkisi, TL (Excel'in
kendi satırı); **DV01 TRY (USD)** – aynısı USD; **DV01 USD (USD)** – USD faizindeki 1 bp'nin etkisi, USD
(`−100·(gün/360)/(1 + USD OIS·gün/360)`; Excel bunu TL olarak gösteriyordu). Değerler vadedeki tutarlardır; TL'den
USD'ye kontratın kendi fiyatıyla (o vadenin forward kuru) çevrilir. Bu satırları başka hiçbir formül okumaz.

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

**VİOP ima faizinin ve OIS farkının tarihsel grafikleri** (VİOP sayfası, **Geçmiş · baz** sekmesi). Excel'deki VİOP
sayfası bir geçmiş tutar (spot, on iki kontrat ve OIS vadeleri, `BDH`) ve her kontratın her günkü bazını hesaplar –
ama bununla yalnızca son 20 günün ortalamasını ve z-skorunu çıkarır ("BAZ GEÇMİŞİ" tablosu); grafiği yoktur. İki
grafik eklendi:

* **VİOP ima TRY faizi · geçmiş (%)** — `((fiyat / spot)·(1 + USD·g/360) − 1)·360/g`, g = vade − (gün + 1 iş günü);
  USD faizi o günün USD OIS vadelerinden.
* **VİOP − OIS · geçmiş (bp)** — sayfanın "Baz" formülünün (`VIOP!AJ380`) kendisi, hücre hücre aktarılarak: ima faiz −
  aynı gün sayısındaki OIS (360 bazında). Aynı günde sayfanın kendi Baz değeriyle birebir aynıdır (testle doğrulanır).

Grafiklerin üstündeki tablodan:

* **Hangi kontratlar** — altı çizgi için kontrat sırası (1 = en yakın vade; ilk dördü 1–4 gelir, boş bırakılan
  çizilmez). Grafikteki adı vade ve ticker'dır (`30.11.26 · A1X6`).
* **Geçmiş (iş günü)** — kaç iş günü geriye gidileceği: 120 gelir, en çok 240. Grafikler **kendi** geçmişini okur;
  BAZ GEÇMİŞİ tablosunun istatistik penceresi (z-skor, ortalama: 20 gün) bundan etkilenmez, o da grafiği etkilemez.

Seçimler kişiseldir. Çizgilerin son noktası bugünün canlı son fiyatıdır; kontratın fiyatı olmayan gün çizilmez (çizgi
üzerinden geçer). Kayıtlı veri modunda VİOP geçmişi kaydı olmadığından yalnızca canlı nokta görünür; canlıda
Bloomberg'den dolar (17 seri × gün sayısı kadar veri noktası). Serilerin tamamı "Yardımcı tablolar"dadır.

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
  iskonto edilmiş bugünkü değer, ASW (bp), uydurulan eğriye göre ucuz / pahalı ve üç kâğıdın ASW geçmişi. Tablonun
  sağında **FX swap eğrisine göre ASW** ve FX − OIS farkı: kâğıt, sayfanın kendi iskonto ve annuity formülleriyle,
  OIS kotaları yerine *FX swap ima TRY eğrisi* (`EK_FX`: 18 aya kadar `TRYI…` FX swap ima, sonra `TRYSAQ…` XCCY;
  önce ICPL, yoksa BGN; MID yoksa bid–ask ortası; ticker kökleri ve kaynaklar ortak girdi) ile kurulan eğriyle de
  fiyatlanır. Fiyatı olmayan vadede OIS kotası kalır.
* Bu iki dosya Bloomberg bağlantısı olmadan kaydedildiği için içlerinde **kayıtlı piyasa verisi yok**. Kayıtlı
  veri modunda: ASW sayfası kâğıt bilgilerini ve fiyatları TTO dosyasının aynı günkü kayıtlarından alır (ASW
  değerleri TTO'daki DİBS RV tablosuyla 0,05 bp içinde aynıdır; geçmiş kısmı yalnızca canlıda dolar); Borsa Swap
  sayfasındaki kotalar TTO'daki RET eğrisinden türetilmiş **örnek veridir** (sayfanın üstünde yazar).
  Canlı modda ikisi de doğrudan Bloomberg'den beslenir.

### Gün Sonu Matrisi, PPK Fiyatlama Geçmişi ve toplantı takvimi

Bu üç sayfa Excel dosyasında yok; dashboard'un kendi **günlük tarihçesine** dayanır (`data/tto.db` içinde: her seri
için gün gün kapanış, her gün için her toplantının fiyatlaması). Hangi serilerin tutulacağı dosyadan okunur: OIS
ticker kökleri (`OIS_MAIN!J9:J26`), TLREF, offshore ticker'ları (`Forward!AO6:AO26`: `TRYI…` FX swap ima faizleri ve
`TRYSAQ…` XCCY), DİBS RV listesindeki kâğıtlar. Bu hücreler değişince tarihçe de onları izler. **Kaynak sırası**
canlı sayfalarınkiyle aynıdır (*Ayarlar → Veri kaynakları*): OIS'te **GFOF ana kaynak**, yedek `MASA!S171`'deki kaynak
(`Curncy`, BGN); offshore ve XCCY'de **ICPL ana kaynak**, yedek Forward sayfasındaki BGN ticker'ı. Yedek yalnızca ana
kaynağın kapanışı olmayan günleri doldurur ve kendi seviyesiyle değil, **o günkü hareketiyle** girer (ana kaynağın en
yakın ortak günündeki kapanışı + yedeğin o günden bu yana hareketi): iki kaynak arasındaki baz farkı sahte bir
günlük hareket, vol ya da z-score olarak görünmez. Ana kaynağın hiç geçmişi yoksa seri yedekten olduğu gibi okunur.
Matriste yedekten gelen kapanış soluk yazılır.

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

**Spread Geçmişi** (TRY Faiz grubu). TRY'nin OIS'e karşı iki spread'i, gün gün ve şu an:

* **Offshore − OIS, vade bazında** (1M … 5Y): tarihçenin kapanışlarından (Gün Sonu Matrisi'nin serileri; offshore
  9 aya kadar FX swap ima getirisi, 1 yıldan itibaren XCCY), iki eğrinin de kapanışı olan günler. Bugünkü seviye
  canlı kotadan (Ayarlar'daki kaynak sırasının kullandığı fiyat: offshore bid / ask ortası, OIS), yoksa son kapanış
  (soluk).
* **VİOP − OIS, kontrat bazında**: VİOP sayfasının geçmiş tablosundaki kontratlar ve geçmiş uzunluğu (Çizgi 1–6,
  "Geçmiş" iş günü), sayfanın kendi baz formülüyle; son nokta bugünün canlı son fiyatı.

Her satırda spread (bp), Δ1G / Δ1H / Δ1A (1 / 5 / 21 kapanış önceye göre), seçilen pencerede (20 / 60 / 250
kapanış) ortalama, σ, **z-skoru**, min / maks ve yüzdelik (kapanışların ne kadarı bugünkünün altında), kapanış
sayısı. 📈 spread'i çizer: kesikli çizgiler pencerenin ortalaması ve ±2σ. Kayıtlı veri modunda yalnızca dosyanın son
ayı vardır (XCCY 1Y ve 1Y'ye kadar OIS); Bloomberg bağlıyken offshore ve OIS bir yıl geriye doldurulur.
Vadeye / kontrata tıklamak da o spread'i çizer: grafik görünür alana gelir, çizilen satır tabloda işaretlenir.

**Ayarlar · Toplantı takvimi** (Araçlar grubu). Tek liste: yapılan toplantılar (arşiv) ve OIS sayfasındaki 80
toplantı (`OIS_MAIN!P10:P89`; aynı hücreler, herkes için ortak). Gerçek tarih belli olunca satırdaki tarih
düzeltilir (gg.aa.yyyy), yeni toplantı eklenir, silinir ya da Excel'den bir tarih sütunu toplu yapıştırılır →
**Kaydet**. **Kopyala** tablodaki tarihleri Excel'e yapıştırılacak bir sütun olarak kopyalar.

* **Toplu yapıştır…** üç şekilde çalışır; yapıştırılanın ne yapacağını sunucu hesaplar (`POST /api/calendar/preview`,
  hiçbir şey kaydedilmez), tablo gösterir, **Kaydet** ile kaydedilir:
  * **Açıklanan tarihlerle düzelt (diğerleri kalır)** — TCMB yılın tarihlerini açıklayınca: yapıştırılan her tarih,
    bugünden (OIS spot valöründen) sonraki toplantılardan en çok 45 gün uzaktaki en yakınının tarihini düzeltir
    (sıra korunur, tarihler olabildiğince az kayar — kaydetmenin adımları taşırken kullandığı eşleştirme); satırda
    "önce 21.01.2027" görünür. Yakınında toplantı olmayan tarih yeni toplantı olarak eklenir. Açıklanmamış
    toplantılar (ör. sonraki yıllar), geçen toplantılar ve arşiv olduğu gibi kalır; bugünden önceki yapıştırılmış
    tarih yok sayılır ve söylenir. Liste 80 satırı aşacaksa kaydetmeden önce hangi tarihin eklendiği ve en
    uzaktaki hangi toplantıların çıkarılması gerektiği yazılır.
  * **Listeye ekle** — listede olmayan tarihler eklenir, eskiler de kalır.
  * **Gelecek toplantıların yerine koy** — bugünden sonraki bütün toplantılar silinip yerine yapıştırılanlar gelir;
    önce kaç toplantının (ve senaryo adımlarının) gideceği sorulur.

  Takvim değişince PPK fiyatlama geçmişinin her günü yeni takvimle yeniden hesaplanır (canlıda gün başına
  birkaç saniye); düzeltmeleri tek kayıtta yapın — kaydetmeden önce sayfa bunu yaklaşık gün sayısıyla hatırlatır.

* Bir toplantıya yazılmış her şey **toplantısıyla birlikte taşınır**: her kullanıcının senaryo adımları (`U:W`),
  kayıtlı senaryoları ve dosyanın kendi adımları. Araya toplantı eklenince sonrakiler bir satır aşağı, çıkarılınca
  yukarı kayar; tarihi düzeltilen toplantı aynı toplantı sayılır. **OIS sayfasında** bir toplantı tarihinin üstüne
  yazmak (ya da yapıştırmak, silmek) da aynı yoldan gider: adımlar toplantısıyla taşınır. Tarihlerin dosyadaki değere
  döndürülmesi reddedilir (dosyanın kaydedildiği günün tarihleridir; adımlar toplantılarından kopardı).
* **Toplantı geçince liste kendiliğinden kayar: MPC1 her zaman sıradaki toplantıdır.** Bir toplantının tarihi OIS
  spot valöründen önce kalınca (dosyanın kendi "geçti" ölçütü) dashboard açılışta, gün dönünce ve gün içinde 10
  dakikada bir (Bloomberg'in valörü gece yarısından bir süre sonra değişir) geçen toplantıyı
  listeden arşive alır, liste sıradaki toplantıdan (MPC1) başlar; dosyanın adımları, her kullanıcının senaryo
  adımları ve kayıtlı senaryoları toplantılarıyla birlikte bir satır kayar. Kaydırmadan önce ve sonra her toplantının
  fiyatlaması ve her kullanıcının senaryo patikaları toplantı bazında aynıdır (testle doğrulanır); kaydı yapan
  "otomatik" görünür, Ayarlar'da son otomatik kaydırma yazar. **Geçen toplantıları arşivle** aynı işi elle yapar.
  Fiyatlama geçmişi toplantının tarihine bağlı olduğu için kaydırmadan etkilenmez.
* Takvim değişince fiyatlama geçmişi yeni takvimle arka planda yeniden hesaplanır (yalnızca etkilenen günler).
* *Tarihçe* bölümü: durum, DİBS getiri alanı, geriye bakış süresi, "Şimdi güncelle", "PPK geçmişini yeniden
  hesapla". *Tarihçe serileri* tablosu her ticker için ilk / son gün ve gün sayısını gösterir — matriste boş kalan
  bir satırın nedeni (Bloomberg o ticker ya da alan için geçmiş vermiyor) buradan görülür.

### Excel'deki diğer özelliklerin karşılığı

| Excel'de | Dashboard'da |
|---|---|
| Masa sayfasındaki 30 köprü | "Kısayollar" çubuğu: sayfa + tablo (YP DIBS'e giden köprü o sayfayla birlikte kalktı: 29) |
| Gizli sütunlar (VİOP C/I/J, Borsa Swap, DİBS RV yardımcı sütunları) | Gösterilmez; "+N gizli sütun" / "Yardımcı tablolar" ile açılır |
| Daraltılmış satır grupları (OIS'te tüm spread/fly/FRA listeleri, VİOP matrisleri) | Kapalı başlayan paneller (▸ ile açılır, tercih hatırlanır) |
| Dondurulmuş bölmeler | Başlık satırları ve dondurulmuş sütunlar (DİBS RV A:C, USD A) kaydırırken yerinde kalır |
| Hücre yorumları (OIS parametreleri, VİOP) | Hücrenin köşesinde kırmızı işaret, üzerine gelince metin |
| Açılır listeler (veri doğrulama; sabit ya da bir aralıktan okunan) | Hücrede seçenek menüsü |
| Koşullu biçimler: kural, renk skalası, veri çubuğu | Aynı kurallarla hücre rengi / ısı haritası / çubuk |
| Sayfadaki resimler | Okunur ve `/api/image` ile sunulur; resimli bir sayfa gösterilseydi sonunda resim paneli olurdu (dosyadaki tek resim Ivır Zıvır'daydı, o sayfa kaldırıldı) |
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
| `BDP` anlık alanlar (BID, ASK, MID, PX_LAST, LAST_PRICE, PX_BID/ASK/MID, HIGH, LOW, BID_SIZE, ASK_SIZE, VOLUME) | İlk değer `ReferenceDataRequest`, sonrası `//blp/mktdata` aboneliğiyle akar (günlük veri limitini tüketmez) |
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

**FX vol'leri** de aynı yoldan gelir: bir kota ilk istendiğinde referans isteği, sonra abonelik (vol ve forward puanı
ticker'larında `LAST_PRICE`, `BID`, `ASK`, `MID` akar). Yalnız açılan sayfanın istediği ister: Spot / FX'te açılan
parite için ~60 ticker (10 vade × 5 kota, forward puanları ve `FWD_SCALE`, spot), FX Vol İzleme'de parite başına 13 vol
ve spot (16 paritede ~220 abonelik). Tarihçeleri yukarıda ([FX tarihçesi](#fx-spot--fx-ve-vol-izleme-sayfaları)): ilk gün bir
yıllık BDH (~220 seri), sonra günde bir son 10 gün. Bu yeni ticker'lar Bloomberg'in aylık tekil menkul sınırına da
sayılır.

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

* **İlk yönetici:** bu sürüme geçince ilk iş, dashboard'un çalıştığı bilgisayarda sayfayı açıp yönetici hesabını
  oluşturmaktır (ya da `python -m tto yonetici <isim>`); sonra masadakiler aynı isimleriyle hesap ister, yönetici
  *Araçlar → Kullanıcılar*'dan onaylar (bkz. [Giriş ve kullanıcılar](#giriş-ve-kullanıcılar)).
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
  "geçmiş yok" yazan bir OIS vadesi varsa *Veri kaynakları*'nda o eğrinin kaynak sırasını değiştirin (yedek her zaman
  Excel'deki ticker'dır); üst şeritteki **CANLI** rozetine tıklayınca açılan pencere Bloomberg'in tanımadığı
  ticker'ları ne olduklarıyla ve hangi hücrenin sorduğuyla listeler (indirilebilir);
  DİBS satırları boşsa getiri alanını (`YLD_YTM_MID`) Bloomberg'de o kâğıtlar için geçmişi olan bir alanla
  değiştirin (ör. `YLD_CNV_MID`). Toplantı takvimindeki geçmiş toplantılar (2025–2026) TCMB takviminden gelir;
  eksik ya da fazla varsa Ayarlar'dan düzeltin.
* `python -m tto check-bloomberg` ile bağlantıyı sınayın, ardından birkaç hücreyi Excel'le karşılaştırın.
* **FX ticker'ları:** `python -m tto check-fx USDTRY` (ve izlediğiniz başka bir parite) bir paritenin bütün vol,
  forward puanı ve spot ticker'larını tek istekte sorar ve hangilerinin geldiğini yazar. FX Vol İzleme'yi ilk açışta
  vol'lerin bir yıllık tarihçesi istenir (~220 seri, bir kez); günlük veri limitine yakın bir günde açmayın ya da
  `--no-history` ile çalışıp "Tarihçeyi güncelle"yi uygun bir anda kullanın.
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
* **Tarihçe** kapanış fiyatlarıyla hesaplanır (OIS sayfası canlı `MID` kullanır); kaynak sırası ikisinde aynıdır,
  ama yedekten doldurulan günlerde ve kapanış ile canlı kota arasında fiyatlama geçmişinin bugünkü noktası OIS
  sayfasından birkaç bp ayrışabilir. FX swap ima TRY faizi (Broker Chat) ve ASW'nin FX eğrisi canlıda sınanmadı;
  `ICPL` XCCY ticker'ı yoksa BGN kullanılır ve ticker *Bloomberg'in tanımadıkları* listesinde açıklamasıyla görünür. Geçmiş günler dosyanın **bugünkü** çözücü ayarları ve tatil
  listesiyle (geçmiş tatiller TLREF fixingi olmayan iş günlerinden çıkarılır) hesaplanır; kullanıcıların kişisel
  çözücü ayarları tarihçeye girmez.
* **DİBS değişimleri** Bloomberg'in getiri alanındandır (kendi getiri kuralıyla); DİBS RV sayfasındaki BIST bileşik
  getirinin geçmişi dosyada yoktur, bu yüzden o sütun yalnızca bugünkü seviyeyi gösterir. Bloomberg'in bu alanlar
  için geçmiş verip vermediği canlıda sınanmadı.
* **DİBS Trading ve Tüm Kâğıtlar** canlıda sınanmadı. `ISL0` (aynı gün) ve `ISL1` (ertesi gün) çalışma kitabının kendi
  kaynaklarıdır, `ISLN` (T2) masanın Bloomberg'indeki kaynaktır (bir kaynak kodu yanlışsa o sütunlar boş kalır, ticker
  *Bloomberg'in tanımadıkları* listesinde görünür; sarı hücreden düzeltilir). `VOLUME` alanının DİBS'te akıp akmadığı
  ve son işlem saatini veren bir Bloomberg alanı denenmedi: saat, dashboard'un işlemi gördüğü andır (açık değilken
  olan işlemin yalnızca günü görünür). Ek kaynak (`BGN`) her kâğıt için fiyat vermeyebilir.
* **"Gerçekleşen"** (yapılan toplantılarda) TLREF fixingindeki değişimdir, politika faizi kararı değil; TLREF
  politika faizinden ayrıştığı dönemlerde (ör. fonlamanın üst banda kaydığı günler) ikisi farklıdır.
* **FX olasılıkları risk-nötrdür** (forward ölçüsü): opsiyon piyasasının fiyatladığı dağılımdır, gerçek dünya tahmini
  değildir; USDTRY'de forward'ın faiz farkı merkezi yukarı taşır. Delta / ATM / prim kuralları tablodaki piyasa
  alışkanlıklarıdır (Bloomberg OVDV ayarlarıyla karşılaştırılmadı); BGN'nin orta kotaları kendi aralarında arbitrajsız
  olmayabilir (SVI en yakın arbitrajsız smile'ı alır, sapma "Uyum" sütununda). G10 teslim tarihleri yalnız hafta sonunu
  atlar (ülke tatilleri yok); vade süresi `gün/365`. Kayıtlı veri modunda FX kotası ve tarihçesi yoktur (kotalar elle
  yazılabilir). Gerçekleşen vol kapanışlardan, işlem günleriyle hesaplanır.
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

Bloomberg ve ağ gerekmez (~8–11 dk; masa bilgisayarında ~35 dk). 978 test (gerçek `blpapi` kuruluysa 7 tane daha):

| Dosya | Kapsam |
|---|---|
| `test_xl_functions.py`, `test_xl_engine.py`, `test_numfmt.py` | Excel semantiği (operatörler, yuvarlama, tarih - bayram, 1 Ocak ve hafta sonu tatilli `WORKDAY` / `NETWORKDAYS`, ay sonu ve 29 Şubat'ta `EDATE` / `EOMONTH`, `YEARFRAC` -, metin, arama, koşullu toplamlar, matris, `LET`, `FILTER` ve taşma / `#SPILL!`, `AGGREGATE`, sıfıra yapıştırma), bağımlılık takibi, kullanıcı katmanları (aynı gruptaki girdilerden birini değiştiren kullanıcının diğerlerini dosyadaki değeriyle görmesi dahil), sayı biçimleri |
| `test_parity.py` | Excel'in kayıtlı değerleriyle parite (sayfa bazında eşikler) |
| `test_reference.py` | LibreOffice'in baştan hesapladığı değerlerle karşılaştırma (`tests/data/lo_*.json.gz`) |
| `test_forward.py` | Forward: bağımsız kapalı formül, Excel'in kayıtlı değerleri, işlem girişindeki fiyatlamanın sayfayla aynılığı |
| `test_blotter.py` | Outright / spread / fly / FRA bacakları, maliyet, ortak işlem defteri, forward'ların O/N karşılığı, Excel özet tabloları, **DV01** (forward: sayfadaki "Forward DV01" bloğuyla aynı sayılar, iki yön, tutarsız fiyat; OIS net / brüt; tahvil: DİBS RV tablosundan, tabloda olmayan kâğıt), işlemle saklanması ve risk özeti, DV01'siz eski kayıt, **tarih aralığı** (günler, toplam maliyet / risk, uçların sırası) ve aralığın tek dosya olarak indirilmesi |
| `test_brokerchat.py` | Broker chat: masanın gönderdiği örnek satırlar ve telefon ekranındaki chat satır satır (saat, gönderen, enstrüman, bid / ask, işlem, ref, OCO, cross-currency), enstrüman türleri ("v"siz spread, fly, FRA yazımları, forward), iki tarafın ve tek tarafın her yazımı, büyük rakamın tamamlanması (öbür taraf, önceki seviye, eğri, belirsizlik), bir satırda birkaç kota, kota olmayan satırlar, mesaj düzenleri (saat başta / sonda / alt satırda, isim, tarih), tahta, eğriyle karşılaştırma; saklama (önizleme, ikinci kez yapıştırma, saatsiz satır, o saate kadarki referans, fiyatsız "taken"), tahtanın model seviyeleri (outright / spread / fly / FRA, kişisel senaryo), **switch'in ekranla değerlemesi** (modeli ekrandaki switch, ASW eğrisine göre yeri, bacak bacak yazılmış switch'in seviyesinin bacakların ekranda getiriye çevrilen fiyatlarından, TLREF switch'inde fiyat farkı, tahtadaki satırı, DİBS sayfalarına girmemesi), günler / aralık / silme, .xlsx, yeniden başlatma, HTTP uçları |
| `test_blotter_fx_mpc.py` | Blotter'ın yeni girişleri: parite okuma, **EURTRY** (sayfanın EURTRY tablosu ve swap puanı satırıyla aynı sayılar, TRY faizinden fiyat = çapraz forward bloğunun hücresi), **swap puanı** (forward = spot + puan / 10.000, ima faiz, Türkçe / İngilizce yazım, eksi puan), **minor para** (elle outright / spot + puan, eğrisiz paritede reddedilen fiyatlama tipleri, TRY'ye karşı olmayan parite), forward DV01'i (payer +, iki yön, USD'ye USDTRY spotuyla çevrim), işlemlerin paritesiyle saklanması, parite + valöre göre maliyet, Excel sayfasına yalnızca USDTRY ve vadeli OIS'in aktarılması, **MPC tarihli OIS** (tarihler ve piyasa seviyesi "MPC OIS" tablosuyla, nominal sayfanın "Nominal" sütunuyla aynı; iki tarih arası hesaplayıcıyla aynı seviye, nominal verilince DV01, dönemlerin çarpımı, hatalı tarihler), listede / maliyette / riskte yeri, indirilen dosyada parite, puan ve işaretli DV01, HTTP uçları |
| `test_watch.py` | **Ne izlenebilir**: OIS, offshore, masa, VİOP kontratı (ticker'ıyla ya da sırasıyla; OIS − VİOP bp, ima faiz), kâğıt (ISIN'iyle; ASW, getiri, pahalı/ucuz, liste dışı kâğıt), hücrenin gösterdiği şey olarak alınması, reddedilenler; **ifadeler** (okunuşu, hataları, birimi: spread / fly bp, ortalama %, oran düz sayı, hücre adresi); **izleme listesi** (hazır gruplar, açılış / düşük / yüksek / gün içi çizgi, referanstan değişim, sıra / ad / hücrenin birimi, kişiye özel liste, açılışın saklanması, yeni gün); **alarmlar** (seviyenin gösterildiği gibi okunması, ≥ / ≤ / kesişir, bir kez çalması, başka kullanıcıya söylenmemesi, yeniden kurma ve silme, izleme döngüsünün kendiliğinden çalması; **VİOP spread'i, kâğıt ASW'i ve ifade üzerine alarmlar**); kâğıt listede yer değiştirince ve **kontratlar dönünce** takip; önceki sürümün listeleri; HTTP uçları (katalog, önizleme) ve **masa notları**; **hareket alarmları** (açılıştan, kurulduğu andan, referanstan, son 10 dakikada - saat testte verilir -, yön, hatalı koşulların reddi, yeniden kurunca yeni başlangıç); **z-skoru ve bant** (tarihçeden, ifadenin parçalarından, dashboard'un kendi kapanışlarından; 20 / 60 / 250 gün; günün kapanışının kaydı; z alarmı); **ısı haritası** (tablolar, sütunlar, hücrelerin konuları, piyasanın hareketi, önceki kapanış: tarihçe ve kendi kayıt, referans - kişiye özel -, HTTP) |
| `test_bonds.py` | **Tüm Kâğıtlar** (77 kâğıt türlerine ve vadesine göre, ★, trading listesindekilerin fiyatı ve DİBS RV özeti, listede olmayanlar, kendi eklenen kâğıt ve ISIN'inden vadesi, sayfadaki ☆ / ★), **★ ile trading listesi** (listenin sonuna ekleme, herkes için, özetteki tür grupları ve vade sırası, çıkarınca satırın kaynağının ve herkesin kişisel değerlerinin silinmesi, HTTP), **DİBS Trading** (her valörün menkulü ve tarihi, DİBS RV'nin valörünün o sayfadan okunması, diğerlerinin hata değil boş kalması, kaynağın değiştirilip boşaltılınca varsayılana dönmesi, kirli fiyatlardan **ima repo** ve TLREF farkı - yalnız aynı güne ait fiyatlardan, değilse kartta ve özette nedeni -, TÜFE'de repo olmaması), canlıda **işlemin görüldüğü an** (ilk yanıt işlem sayılmaz, aynı fiyattan işlem hacimden anlaşılır, azalan hacim, yeni gün), sayfada saat ve günün işlemleri, **kâğıt kartı** (katalog, DİBS RV satırı, valörler, tahta, chat satırları, işlemler, listede olmayan kâğıt, HTTP); **TRY DİBS kataloğu** (77 kâğıt, ISIN kontrol hanesi, ISIN'deki vade, türler, bir ayın / günün adayları); broker chat'te **DİBS kotaları** (tarih ve ay-yıl yazımları, TLREF / TÜFE / bono, valör, kısa fiyatın tamamlanması, Türkçe işlem / ref / ilgi kelimeleri, switch'in metin kalması), fiyatı bilinmeyen kâğıdın **en yakın aynı tür kâğıttan** ya da 100'den tamamlanması, **başlıklı liste** (ihale fiyatları), servisin örnek chat'i ekranla okuması (ima getiri, bir ayın iki kâğıdının ekranla ayrılması), **DİBS RV'deki broker sütunları**, **ISIN ile listeye ekleme** (listenin sonuna, atlanan / reddedilen, ortak ve kişisel liste, HTTP), **100 satırlık toplu forward**'ın Forward tablosuyla birebirliği ve **Bulk Bond**'un yeni satırları; **switch** kotaları (iki kâğıt: getiri farkı bp, yazılış sırası ve bağlaçlar, "bid … offer" ayrı yazılışı, tahtada tek satır; bacak bacak yazılmış switch: her bacağın fiyatı kendi ekranıyla tamamlanır, olay satırın kelimelerinden; üç kâğıt metin kalır); **ay-yıl tek başına önce sabit kuponlu** (o ayda yoksa ayın TLREF'i, sonra TÜFE'si; tür yazılınca yalnız o tür; switch bacağının kendi türü); **zc = sıfır kuponlu ve getiriyle** (bono / kuponsuz, bitişik `feb27zc`, kuponluya geçmeme, getiride bid > ask ve kısa ask'in altta tamamlanması); virgülden sonraki öbür tarafın aynı kâğıt olması |
| `test_sources_and_desk.py` | **Fiyat kaynağı sırası**: canlı hücrelerin sıradaki ilk fiyatlı kaynağı alması (offshore'da iki taraflı kaynak, tek taraflı alınmaz), kayıtlı veride sayfaların dosyanın değerinde kalması, sıranın herkes için değişmesi, saklanması, tarihçe tanımlarının izlemesi, hatalı kod, HTTP; **yedek kaynağın yalnızca boş günleri hareketiyle doldurması**; tanımsız ticker açıklamaları; **ASW'nin FX swap eğrisiyle** fiyatlanması; **Forward fiyatları**: USDTRY / EURTRY tablolarının Forward sayfasıyla birebirliği (günlük puanlar dahil), yazılan faizin iki pariteyi yalnız yazana yeniden fiyatlaması, **Elle** satırı (eğri + mid ya da spread, genişlik), **serbest forward** (spot, major, minor eğrilerden; ileri başlangıç; EURTRY; eğrinin bittiği yerde boş; üzerine yazma), **vadelere göre simple zero** tablosu, eski düzende yazılmış değerin silinmesi; altın serbest sütunu; **z-score**; **tahta sıfırlama / geri alma, işaretlenen satırların silinmesi**; bugünü içeren aralıkta işlem girişi; **FX swap puanlarının okunuşu ve ima TRY faizi**; **OIS Kontrol gün sayıları masa takvimiyle** (düğüm tarihinden sayılan gün, hafta içi Bloomberg'le aynı) |
| `test_fxvol.py` | FX smile'ları: normal dağılım ve tersi, Black, piyasanın deltaları (forward / spot, primli) ve strike'ları – primli call deltasının azalan kolu –, delta-neutral straddle, market strangle; **SVI'nin, kotaları üreten smile'ı geri bulması**, G10 smile'ını arbitrajsız ve kotasına oturtması, USDTRY benzeri smile'da arbitrajsız kalması (ATM ve 25D kotalarda < 0,1 vol), **SABR'ın USDTRY skew'unu tutamaması** (neden SVI), Vanna-Volga'nın pillar'larından geçmesi, eksik kotalar; dağılım: düz smile'da lognormal yasa, kuantil ↔ CDF, ortalama = forward, yoğunluğun call'un ikinci türeviyle aynılığı |
| `test_fx.py` | Spot / FX ve FX Vol İzleme: ticker adları (Bloomberg'deki gibi), paritelerin kuralları, **USDTRY forward'ının Forward sayfasının "Serbest forward" listesindeki offshore forward'ıyla birebirliği** (her vade), yazılan spotun yalnız sahibini etkilemesi, puandan forward ve TRY çaprazının USD bacaklarından, teslim tarihleri; yüzey (her vadede arbitrajsız, ortalama = forward, artan kuantiller, skew), otomatik seviyeler, SABR / geçersiz model, EURUSD'de spot delta ve iskonto, **kendi kotası** (yalnız sahibine, boşla Bloomberg'e dönüş, hatalı girdiler), pariteler tablosu, **Makro bloğunun istatistikleri** (Δ1G / 1H / 1A, z 3A, pencere z'si, yüzdelik, aralık, boş günün doldurulması), gerçekleşen vol, yuvarlak seviyeler, izleme (tarihçeyle, eklenen parite ve ticker, ortak fiyat kaynağı), parite ayrıntısı (bugün / 1H / 1A önce; RR / BF'siz gün smile'sız), tarihçenin bir yıl geriye sonra son on gün istenmesi, **spot oynayınca smile'ın yeniden kalibre edilmeden taşınması**, `check-fx`, HTTP uçları |
| `test_series_charts.py` | **Tıkla → grafik**: Gün Sonu Matrisi'nin satırının, izleme kaleminin ve ısı haritası noktasının arkasındaki kapanışlar (`/api/history/closes`, `/api/watch/history`) ve tarayıcının onları çizdiği istatistikler (`seriesstats.js`, Node.js ile) - yanındaki tablonun sayılarıyla birebir (FX izleme: `tto.fx.stats`, izleme listesi: `Watch.zinfo`); Node.js yoksa atlanır |
| `test_volcarry.py` | Realized vol: yazılanın okunuşu, enstrüman seviyesinin günlere göre kuruluşu (yalnızca bütün bacakların kapandığı günler), **vol = günlük değişimlerin standart sapması** (elle hesapla aynı; pencereler, dolmayan pencere, en az beş değişim, kayan vol), forward'ın par eğrisinden bootstrap'i (düz eğri, sınırlar, Excel'in forward'ına 5 bp içinde yakınlık), sayfa satırı; tarihçeye yazılmış kapanışlarla servis (outright / spread / fly / FRA / cross-currency, eksik günü olan vade, geçmişi olmayan vade, pencere seçimi), **carry / vol** (C & R sayfasının 34 fly'ı ve 120 spread'i, sayfanın kendi C+R değerleri, ufukların iş günü sayısı, oran = C+R ÷ (σ·√gün)), **carry patikası** (S1'in Excel'in kaydettiği C & R değerlerini birebir vermesi, Bootstrap'ta ufku vadeye eşit OIS'in carry'sinin ~0 olması, patikadan bağımsız roll, kullanıcıya özel seçim ve ufuklar, hatalı değerler), **Listem** (yazılan OIS vadesi / spread / fly'ın carry'si, FRA ve listede olmayan vade için açıklama), **Spread Geçmişi** (offshore − OIS: iki eğrinin ortak günlerinden seri, canlı kotayla bugünkü seviye, 1G / 1H / 1A değişim, 20 / 60 / 250 kapanışta ortalama, σ, z, aralık, yüzdelik; canlı kota yokken son kapanış; VİOP − OIS kontratları), HTTP uçları |
| `test_charts.py` | Grafik tanımlarının Excel'den alınışı (renk, çizgi, işaretçi, eksen sınırları, tarih ekseni, bid–ask kutuları), değerlerin Excel kuralıyla çizime verilişi (boşluk, `#N/A`, metin) ve XY grafikleri (nokta etiketleri, sayı / tarih ekseni) |
| `test_auction.py` | **Hazine İhalesi** (canlı-benzeri bir Bloomberg'le): temiz fiyattan, basit ve bileşik getiriden kirli fiyat (bağımsız bir BIST getiri hesabıyla aynı; 3 haneye yuvarlama, tutar, iki girdide temizin önceliği), nominal ağırlıklı ortalama ve getirisi; açıklanan asgari / ortalama / azami fiyatla gerçekleşen / asgari fiyatta / gerçekleşmeyen teklifler, ortalamaya fark, aralıktaki yer, elle yazılan gerçekleşen nominal, gerçekleşen ortalama ve getirisi; bono, TLREF (getiri yok) ve TÜFE (reel getiri, endeks oranıyla tutar); **uzun ilk kuponlu** yeni ihraçta kalan kuponların takvim dönemiyle (364 / frekans gün) sayılması; **birikmiş faizin yalnız Bloomberg'den, valörle** istenmesi (kâğıdın kendi valörü, kupon gününe denk gelen valör, Bloomberg'in yanıt vermediği valörde fiyat çıkmaması, tanınmayan ISIN); sayfa tanımı ve kayıtlı veri modu |
| `test_extras.py` | Dashboard'un ekledikleri: forward kotasyon matrisi (yedi eğri Masa bloğuyla aynı, bid / ask ayrı spread, puan → spread tersi; **piyasa spread'i**: her vadede offshore ima − OIS, seçilince spread'in yerine geçmesi, EURTRY'nin seçimi izlemesi; **EURTRY matrisi**: aynı tarihte USDTRY ile aynı OIS faizi, EUR faizi ve gününün Masa'nın EURTRY hücreleriyle aynılığı, eğri ve spread'lerin USDTRY'yi izlemesi ve ayrılması, kendi spot'u, puandan spread), altın (`spot·(1+swap·g/360)` kapalı formülü, USD faizinin hesaba girmediği, faiz interpolasyonu, kaynak seçimi, `XAUSR…` ticker'ları ve ticker eki, canlıda `BFXFORWARD`'sız çalışma, VİOP / Forward hücrelerinin beslenmesi, "belli faizle fiyat"; **VİOP XAUTRY hesaplayıcısında her girdinin elle yazılması**: fiyattan ima TRY ve ima altın swap faizi, ima faizle fiyatın geri gelmesi, başka tarih, serbest sütun, silince piyasaya dönüş; **VİOP geçmiş serileri**: canlı-benzeri bir sağlayıcının geçmişiyle ima faiz / baz / OIS'in elle hesapla ve aynı günlerde sayfanın kendi "Baz" değeriyle aynılığı, fiyatı olmayan günün çizilmemesi, grafik verisi, kontrat seçimi, kendi geçmiş penceresi – sayfanın 20 günlük istatistik penceresi değişmeden), bir ekin dosyaya uymadığında dışarıda bırakılması, Borsa O/N karşılıkları ve örnek kotaların RET'e eşitliği, **Borsa'da yalnızca miktarı olan kotanın listelenmesi** (miktarı 0 / eski fiyatlı vadeler, tek taraflı kota, hata hücresi kalmaması), ASW ↔ DİBS RV |
| `test_workbook_features.py` | Gizli sütunlar, dondurulmuş bölmeler, yorumlar, veri çubukları, kısayollar, resim, aralıktan okunan açılır listeler, Excel yerleşimiyle yapıştırma, gün sonu arşivi (.xlsx yazıcı dahil), hücreden okunan başlık / notlar, şifreli dosyanın içe aktarılması |
| `test_defaults.py` | PPK ima adımlarının ve VİOP Target tablosunun herkese boş gelmesi (boş adımla üç senaryonun ima yola eşitlenmesi, kullanıcının kendi değeri), eski sürümün ortak girdi olarak taşıdığı dosya adımlarının ilk açılışta bir kez silinmesi (başka ortak girdiye dokunmadan; boş başlatma eki dosyaya uymadıysa silinmemesi) |
| `test_dv01.py` | DV01 Risk'in sıfır pozisyonla açılması (kova DV01'leri ve yapıştırma alanı; kullanıcının kendi pozisyonu kişisel), VİOP matrisinin DV01 satırları kendi para biriminde (TRY: TL ve USD, USD: USD; kontrat fiyatıyla çevrim, sayfada yeni satır) |
| `test_dates.py` | **Özel günler**: vadeden valörün (`2W`, `18W`, `1M` …) masanın tatil listesini (Motor!A361:A523) izlemesi - Ramazan Bayramı'na (10.03.2027), 19 Mayıs'a ve 1 Ocak'a düşen valörün ilk iş gününe kayması, ay vadelerinin çalışma kitabının kendi `WORKDAY(EDATE(…))` tarihleriyle aynı olması; dashboard'un **ay sonunda** (30.11.2026), **yıl sonunda** (31.12.2026: spot 1 Ocak ve hafta sonundan sonra) ve **bayramın ortasında** (10.03.2027) açılması: spot ve tahvil T+1 valörü, geçen PPK'nın listeden bir kez çıkması (MPC1 bir sonraki toplantı), bütün sayfaların Python hatası vermeden hesaplanması |
| `test_auth.py` | **Giriş ve hesaplar**: şifrenin tuzlu özetle saklanması (tur sayısı özetin içinde), önceki sürümün veritabanındaki kullanıcıların şifresiz etkin hesap olarak kalması, **ilk yöneticinin yalnızca bu bilgisayardan** ve yalnızca yönetici yokken oluşturulması (önceki sürümden bir kullanıcı da olabilir, girdileri kalır), yanlış şifre / bilinmeyen isim için aynı yanıt, **5 hatada 1 dakika kilit**, oturumun 7 gün sürmesi ve veritabanında yalnızca özetinin durması, çıkış; **hesap isteği** (bekleyen istekle girilmemesi, önceki sürümün kullanıcısının aynı isimle isteyip onaylanınca girdilerine kavuşması, reddedilen yeni isteğin silinmesi / eski hesabın şifresiz geri dönmesi); **yönetici işleri** (oluşturma, rol verme / alma, son yöneticinin korunması, şifre belirleyince ve hesap kapatınca açık oturumların bitmesi, kendi hesabını kapatamama); kendi şifresini değiştirme (diğer oturumların kapanması, eski şifre hatalarının kilide sayılması); **aynı anda gönderilen 20 tahminin 5'inin denenip gerisinin kilide takılması**, şifresiz hesabın yönetici yapılamaması ve istekle sahiplenilenin kullanıcı olması, kendi yetkisini bırakma, benzer görünen isimlerin tek isim / görünmeyen karakterin reddi, bekleyen istek sınırı; HTTP'de **oturumsuz her `/api` isteğinin 401** alması, **başka sayfadan (Origin / Sec-Fetch-Site) gelen değişiklik isteğinin 403** alması, sunucunun X-Forwarded-For'a inanmaması, çerezin HttpOnly / SameSite=Strict / 7 gün olması, `Authorization: Bearer`, yönetici uçlarının yöneticiye açık olması, kapatılan hesabın tarayıcısının bir sonraki istekte dışarıda kalması; `python -m tto yonetici` komutu |
| `test_service.py`, `test_server.py`, `test_store.py`, `test_inputs.py`, `test_config_cli.py` | Kişisel/ortak girdiler, senaryolar, RET, kalıcılık, HTTP API, yapıştırma/ayrıştırma, port kuralı, manuel spot (VİOP ve Masa'nın ilk tablosu, üst şeritten giriş, temizleyince Bloomberg spotu), **elle değer** (formülün üzerine yazma: yalnızca sahibinin, yalnızca ona girdi görünür, silince / "formüle dön"le formül geri gelir, yeniden başlatmada kalır), hesaplayıcıların otomatik dolan girdileri (Forward ve VİOP: tarih, spot, döviz faizi), sekmeli sayfa çıktısı ve arama kutusunun verisi, işlem defterinin aralık / DV01 / tahvil fiyatı uçları |
| `test_views.py` | Sayfa tanımları: her panel ve girdi gerçek hücrelere bakıyor, **her formül bir tabloda** (dört kitap + ekler, sıfır istisna), her girdi hücresine sayfasından ulaşılıyor, Forward'daki elle hesaplama araçları (USDTRY ve EURTRY) görünür tablolarda; **sekmeler**: 12'den çok tablosu olan her sayfa sekmeli, her görünen tablo bir sekmede ya da sekmelerin üstünde, sekmeler var olan görünür tabloları gösteriyor, Forward hesaplayıcılarla başlıyor, Hesaplayıcılar sayfasında aynı adlı iki tablo yok; **kaldırılan dört sayfa** (MOBIL MK, YP DIBS, Ivır Zıvır, USDTRY IYIX: yüklenen kitapta ve Sayfa gezgini'nde yok, 45 `BDP` çağrısı gitti, kalan sayfaların sırası ve numaraları, model dosyasının onları tutması, başka bir formülün başvurduğu sayfanın kalması) |
| `test_bundled.py` | Kurulumsuz çalıştırma: her Python kuşağının paket seti, wheel özetleri ve lisansları, kurulu paketlerin önceliği, `vendor/local`, ve hiçbir paketi olmayan bir Python'la (`python -S`) sunucunun açılıp sayfa, statik dosya, giriş ve canlı akış vermesi |
| `test_history.py` | **Toplantı takvimi**: açıklanan tarihlerle toplu düzeltme (en yakın toplantının düzeltilmesi, 45 günden uzak tarihin eklenmesi, açıklanmamış yılların ve geçmişin kalması, 80 sınırının nedeniyle reddi, listeye ekleme, gelecektekilerin yerine koyma, kaydedince adımların toplantısıyla gitmesi, önizleme ucu) ve **geçen toplantının listeden kendiliğinden çıkması** (açılışta ve gün içinde spot değişince: MPC1 sıradaki toplantı, adım toplantısıyla, "otomatik" kaydı), **OIS sayfasında yazılan toplantı tarihinin takvimden geçmesi** (adımın toplantısıyla kalması, çıkarılan toplantının adımıyla gitmesi, dosya tarihlerine dönüşün reddi); günlük tarihçe: kapanış deposu, kayıtlı `BDH` bloklarının tarihlenmesi, serilerin dosyadan okunuşu, **tarihçenin bugünkü satırı = OIS sayfası** (80 toplantı, hücre hücre), toplantı bazında fiyatlama (yapılan toplantının serisi, gerçekleşen TLREF değişimi, toplantı günü ölçümü, kotaların eriştiği ufuk), gün sonu matrisi (1 / 5 / 21 iş günü kuralı, tatil, geçmiş gün), takvim (tarih düzeltme / ekleme / çıkarma: adımların ve kayıtlı senaryoların toplantıyla taşınması; **toplantı geçince ve liste kaydırılınca** sayfalar ve her toplantının değerleri), sahte Bloomberg'le canlı tarihçe (istek gruplama, yalnızca son günlerin yenilenmesi, yedek ticker, zaman aşımı), HTTP uçları; **bir günün kotaları** (kapanışı olmayan vadenin komşularının hareketiyle taşınması, komşularından ayrılıp geri dönen kapanışın ayıklanması, piyasa hareketinin korunması), günlerin Excel'in kendi durumuna göre sınıflanması, çözücünün tutturamadığı günün seriden / min-maks'tan / değişimlerden çıkması, hatalı bir kapanışın kayıtlı ayda çözücüye ulaşmaması, eski sürümün veritabanının korunması |
| `test_bundle.py` | Tek dosyalık kurulum (`kurulum/tto_kur.py`): içine ne girdiği, aynı içeriğin aynı dosyayı vermesi, boş klasöre açma, güncelleme (değişen yenilenir, kalkan silinir, `data` / `vendor/local` / kullanıcının kendi dosyaları kalır), ZIP'ten gelmiş klasör, yarım inmiş / bozulmuş / satır sonları değişmiş dosya, klasör dışına çıkan adların reddi, seçenekler; **repodaki dosyanın kodla aynı olduğu** ve hiçbir paketi olmayan bir Python'la açılıp sunucunun ondan çalıştığı |
| `test_bloomberg.py` | `blpapi` katmanı (sahte sunucuyla): gruplama, abonelik (kota büyüklükleri dahil), sessiz kalan kotaların giderek seyrek sorulması, hata metinleri, BDH/BDS, limit koruması, canlı–doğrudan eşdeğerlik (dört kitap); **Bloomberg'in tanımadığı ticker'lara abone olunmaması**, ertesi gün yeniden sorulması, seyreltme seçeneği ve reddedilince seçeneksiz deneme, uzun olay kuyruğu, **kuyruk taşınca sayım ve düşen değerlerin yeniden istenmesi** (günlük üst sınırıyla); **Excel eklentisi için yazılmış kimliklerin API biçimine çevrilmesi** (`… @ISL1 ISIN` → `/isin/…@ISL1`: istek, geçmiş, abonelik), geri çekilen emrin miktarının boşalması |
| `test_bloomberg_process.py` | Oturumun yardımcı süreçte çalışması: değerlerin, tick'lerin, `BDH`'nin ve tarihçe çağrısının süreç sınırını geçmesi; `blpapi` yok / yüklenemiyor / terminal yok / yardımcı yanıt vermiyor; **yardımcı ölünce yeniden başlayıp her şeyi yeniden istemesi** (istek sayacı sürer), sürekli ölen yardımcının bir noktada bırakılması; dashboard durunca ya da öldürülünce yardımcının kapanması; **ölçüm: hesap yapan bir sürecin içindeki okuyucu saniyede 2.000 tick'in dörtte birine yetişemezken yardımcı hepsini okur**; dashboard'un yardımcıyı kullanması ve başlatamazsa aynı süreçte devam etmesi; ve ilk canlı çalıştırmanın sahnelenmesi: `python -m tto --mode live`, dört kitap, saniyede 1.500 tick, 10.000'lik kuyruk — hiç olay düşmez, var olmayan ~790 vadeye abone olunmaz |
| `test_blpapi_real.py` | Gerçek `blpapi` kuruluysa (yoksa atlanır; terminal gerekmez): kütüphanenin kendi test olaylarıyla tick okuma, değeri boşaltılmış miktarın "mesajda yok"tan ayırt edilmesi, `SlowConsumerWarning` / `DataLoss` / abonelik durum mesajları, oturum seçenekleri ve abonelik metni (`…?fields=ASK,BID&interval=1`), hesap yapan bir iş parçacığının yanında okumanın kaç kat yavaşladığı, terminal yokken hata (aynı süreçte ve yardımcıyla). `blpapi` yükseltildikten sonra masada bir kez çalıştırmaya değer. |
| `test_e2e.py` | Gerçek tarayıcıda (Playwright/Chromium) 306 kontrol: **şifreyle giriş** (oturumsuz API'nin 401'i, yanlış şifre, yöneticide "Kullanıcılar" sayfası, kullanıcıda yok), **sekmeler** (Forward hesaplayıcılarla açılır, sabit valör şeridi, sekme değiştirme ve hatırlanması, her sekmede arama, "Tümü", başka sekmedeki hücreye gidiş), **elle değer** (mod kapalıyken formül yazılamaz; açıkken yazılan değerin işareti, sayaç, silince ve "formüle dön"le geri dönüş), hesaplayıcıya elle spot, düzenleme, Excel kopyala/yapıştır, RET, senaryo, işlem girişi, iki kullanıcı arası canlı paylaşım, grafiklerin çizimi (renk, eksen, tarih ekseni, ipucu, XY grafiği), kısayollar, gizli / dondurulmuş sütunlar, arşiv indirme, forward kotasyon matrisi (USDTRY ve EURTRY; EURTRY'nin USDTRY'nin eğri ve spread'lerini izlemesi, kendi spread'i, puandan spread), altın swap faizi girişi ve VİOP tablosunun değişmesi, Borsa Swap, DİBS ASW, gün sonu matrisi (değerler, geçmiş gün, kopyalama), PPK fiyatlama geçmişi (çizgiler, toplantı ekleme / çıkarma, ölçü değiştirme, ipucu, günlerin durumu), manuel spot penceresi (üst şeritten açma, bid > ask reddi, Bloomberg'e dönme), RET kaydırma önizlemesi (her vadede kaç bp ve yeni bid / ask, sabit tutulan ve elle miktar verilen vade, yalnız bid, önizlemedeyken kaydetmeme, "Uygula") ve tablo / mesaj olarak kopyalama, VİOP geçmiş sekmesi (kontrat tablosu, iki grafik, yeni çizgi ekleme), işlem girerken ve listede DV01, tarih aralığı görünümü ve indirilmesi, **Broker Chat** (yapıştırılan chat'in yazılırken okunması, kısaltılmış seviye / işlem / ref, kaydetme, tahta ve model farkı, ikinci kez yapıştırma, tek enstrüman / arama / ürün süzgeci, başka kullanıcının eklediği satırın canlı gelmesi, silme, saatsiz satır, indirme, aralık), blotter'da **EURTRY / swap puanı / minor para / MPC tarihli OIS** girişi ve bacak bazında payer (+) işaretli DV01, **Realized Vol · Carry** (yazılan enstrümanların vol'ü, geçmişi olmayan / okunamayan satır, yıllık birim, seviye ve kayan vol grafiği, fly ve spread'lerin C+R ÷ σ sıralaması ve noktalı grafiği), altın hesaplayıcısının serbest sütunu, Ctrl+K ile tablo bulma, Ayarlar'da toplantı tarihinin düzeltilip OIS sayfasına yansıması, **Ayarlar'da fiyat kaynağı sırası** (ekleme, kaydetme, varsayılana dönme, her vadenin kullandığı kaynak), Broker Chat'te **taraf** sütunu, sütuna göre **sıralama**, **işaretleyerek silme**, **tahtayı sıfırlama / geri alma**, RET penceresinde **spread (önceki → şimdi)**, carry tablosunda **z-score**, bugünü içeren aralıkta **işlem girişi**, Broker Chat'te **DİBS kotaları** (ISIN'li ad, valör, ihale listesi, yakın kâğıttan tamamlama), **DİBS RV'nin broker sütunları**, **"+ ISIN ekle"** (77 kâğıtlık katalog, hatalı ISIN'in reddi, listeye ekleme), **Bulk Bond ve toplu forward'da satır açma**, **DİBS Trading** (valörler, ek kaynak, chat sütunları, günün işlemleri), **kâğıt kartı** (DİBS Trading'den ve DİBS RV'den), **Tüm Kâğıtlar** (77 kâğıt, türler, ★) ve **☆ / ★ ile trading listesine ekleme / çıkarma** (DİBS Trading özetinde görünmesi), **İzleme · Alarmlar** (hazır grup, sağ tıkla hücre ekleme - kâğıdın getirisi kâğıt olarak -, alarmın çalıp açık sayfada uyarması, "Ekle · alarm kur…" ile **VİOP OIS − VİOP spread alarmı**, **kâğıt ASW alarmı** ve **"İfadeye ekle" ile ifade**, hatalı ifadenin söylenmesi, **z-skoru sütunu ve pencere seçimi**, **z alarmı**, masa notları), **Eğri Hareketi** (tablolar, seviye, açılış ve referans karşılaştırması, ölçek, bir noktadan **hareket alarmı**), **Forward fiyatları** sekmesi (USDTRY / EURTRY alt alta, günlük puanlar, Elle'de eğri seçip spread, serbest forward'da eğrilerden gelen spot / faizler ve yazılan minor faizle fiyat, vadelere göre faizler), **Kota mesajı** (forward tablosunun puanları, satır çıkarma; OIS par'ı ± genişlik), **İşlem gir** (forward tablosundan ve Broker Chat'teki işlem satırından Günlük İşlemler'in dolu açılması: parite, yön, valör, puan; OIS vadesi, seviye, PAY, not, karşı taraf), Broker Chat'te **switch** (tahtada tek satır, ekrandaki switch modeli, eğriye göre yeri), carry'de **Listem**, **Spread Geçmişi** (offshore − OIS ve VİOP − OIS tabloları, pencere seçimi, grafik), Ayarlar'da **carry patikası ve ufku**, tüm sayfalar. Node.js + Playwright yoksa atlanır. |

Masadaki makinede (Windows 10 Türkçe, Python 3.9) de tamamı geçer ve ~35–40 dk sürer. Bloomberg yardımcı
sürecinin testleri orada da sahte `blpapi` ile çalışır; hiçbir test gerçek terminale bağlanmaz.

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
`NO_PAGE` listesine eklemek yeterlidir (hücreleri hesaplanmaya ve Sayfa gezgini'nde görünmeye devam eder). Sayfa
tamamen kalksın (hesaplanmasın, Sayfa gezgini'nde de olmasın) isteniyorsa adı `tto/books.py` içindeki
`REMOVED_SHEETS` listesine yazılır; başka bir sayfanın formülü ona başvuruyorsa kaldırılmaz, günlüğe uyarı düşer.

Dashboard'un kendi ekleri (`tto/extras.py`) dosyadaki belirli hücrelere dayanır (Masa'daki iskonto faktörleri,
VİOP'taki `BFXFORWARD` hücreleri, Borsa tablosunun başlıkları). Dosyanın düzeni değişip bir ek artık uymuyorsa
sunucu yine açılır; yalnızca o ek dışarıda bırakılır, nedeni başlangıçta günlüğe ve `/api/status` yanıtındaki
`left_out` alanına yazılır.

## Proje yapısı

```
tto/xl/            Excel formül motoru (tokenizer, parser, derleyici, fonksiyonlar, sayı biçimleri, içe aktarıcı)
tto/marketdata/    Bloomberg (blpapi) ve kayıtlı veri sağlayıcıları; bbg_process.py: Bloomberg oturumunu ayrı bir
                   yardımcı süreçte çalıştırır
tto/extras.py      dashboard'un kendi eklediği hesaplar (Excel formülü olarak: EK_FWD, EK_XAU, EK_VIOP, EK_KAYNAK,
                   EK_BULK, EK_FX, EK_IHALE, Borsa O/N, Bulk Bond'un yeni satırları)
tto/service.py     uygulama servisi (sayfalar, girdiler, senaryolar, RET, işlem defteri)
tto/history.py     günlük tarihçe: kapanışlar, PPK fiyatlama geçmişi (çözücüyü geçmiş günle besleyen ikinci motor),
                   gün sonu matrisi, toplantı takvimi (düzeltme, kaydırma, adımların toplantıyla taşınması)
tto/blotter.py     forward fiyatlama (USDTRY, EURTRY, elle girilen pariteler; swap puanı), OIS strateji bacakları ve MPC
                   tarihli OIS, pozisyon maliyeti, DV01 (forward / OIS / tahvil; payer +) ve risk özeti
tto/brokerchat.py  broker chat ayrıştırıcısı: mesajlar (saat, gönderen, gün), kotalar (outright / spread / fly / FRA,
                   FX swap puanı, DİBS; kısaltılmış seviyeler, işlem / ref / ilgi), tahta ve eğriyle karşılaştırma
tto/watch.py       izlenenler (VİOP, kâğıt, OIS, offshore, masa, ifade, hücre), izleme listeleri, alarmlar (seviye, hareket, z-skoru), z-skoru, kendi kapanış kaydı, ısı haritası
tto/bonds.py       TRY DİBS kataloğu (tto/data/try_bonds.json): ISIN kontrolü, ISIN'deki vade, chat'teki kâğıdın adayları
tto/volcarry.py    realized vol (yazılan enstrümanın günlük tarihçeden seviyesi, değişimlerin standart sapması,
                   forward için par eğrisinden bootstrap) ve carry'nin vol'e oranı
tto/fxvol.py       FX smile'ları (saf Python): Black, piyasanın delta / ATM kuralları, market strangle, SVI (varsayılan),
                   SABR, Vanna-Volga; smile'dan spotun risk-nötr dağılımı, kuantiller, yoğunluk denetimi
tto/fx.py          Spot / FX ve FX Vol İzleme: pariteler, ticker'lar, forward'lar (USDTRY offshore eğrisinden), yüzey,
                   olasılık matrisi, izleme istatistikleri (Makro bloğunun tanımı), FX tarihçesi, check-fx
tto/xlsx.py        gün sonu arşivi için küçük .xlsx yazıcı (yalnızca değerler ve biçimler)
tto/server.py      HTTP API + canlı güncelleme (server-sent events); oturum kapısı: girişsiz /api isteği 401
tto/auth.py        şifre özeti (PBKDF2-SHA256), oturum anahtarı, kilit ve süre ayarları
tto/store.py       SQLite (kullanıcılar ve oturumlar, girdiler, senaryolar, RET geçmişi, işlemler, broker chat, günlük
                   tarihçe)  →  data/tto.db
tto/bundled.py     kurulu değilse web paketlerini vendor/ altındaki wheel'lerden içe aktarır
tto/views/         sayfa tanımları: tablolar, girdiler, sekmeler ("sections") ve sekmelerin üstünde sabit duranlar ("pinned")
tto/data/          kayıtlı veri modunda kullanılan ek kotalar ve TLREF geçmişi (replay_*.json), DİBS kataloğu
tto/static/        arayüz (derleme gerektirmeyen ES modülleri, kendi SVG grafikleri; fan.js: olasılık bulutu)
models/            içe aktarılmış çalışma kitapları        workbooks/   kaynak Excel dosyaları
vendor/            gömülü web paketleri (değiştirilmemiş PyPI wheel'leri; Python 3.8 / 3.9 / 3.10+ setleri)
tools/             parite, LibreOffice referansı, içe aktarma, kayıtlı veri kotaları, tek dosyalık kurulumun üretimi
kurulum/           tto_kur.py: dashboard'un tamamı tek düz metin dosyasında (ZIP inmeyen / taşınamayan yerler için)
tests/             test paketi
```

Yedekleme için `data/tto.db` dosyasını kopyalamak yeterlidir.
