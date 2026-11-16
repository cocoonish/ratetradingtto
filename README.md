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
* **Girdiye formül:** sarı / yeşil bir hücreye `=` yazıp başka bir hücreye tıklamak Excel'deki gibi formül kurar
  (`=C60+7`); değer canlıdır, okuduğu hücre değişince kendiliğinden güncellenir ([aşağıda](#kullanım), *Girdi hücreleri*).
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
* **Quant sinyaller:** korelasyon kırılması, OIS eğrisinin PCA'sı (zengin / ucuz, PCA-nötr fly ve spread'ler),
  eşbütünleşik çiftler (Kalman hedge oranıyla), VİOP takvim ve FRA / PPK patikası tutarsızlıkları, ima PPK / FOMC
  patikasının ayrık kararların karışımı olarak okunması (**İma Patikası**: tutarlı patikalar, kinkler, kalibrasyon),
  **TCMB WIRP** (Bloomberg WIRP / CME FedWatch gibi, Fed'i yanında), **Öncü-Takipçi** (kim önce hareket ediyor),
  **VİOP** (vadelinin spota göre ima TRY faizi: adil değeri, al / sat sinyali, bugün ve bu hafta hangi faizden alınıp
  satılabileceği olasılıklarıyla, ay sonu etkileri), makro
  betalar, rejim, momentum, PPK döngüsü, FX vol primi ve GARCH, EM carry, forward primi, doğrulanmış bir tahmin modeli,
  **eğri adil değeri** (OIS ve DİBS'e Nelson-Siegel-Svensson: zengin / ucuz, carry + roll, receive / pay için en iyi
  kâğıt, adil eğriden kâğıt kotası ve switch) ve **FX opsiyon smile'ı** (USDTRY / EURUSD skew, kanatlar, vade yapısı;
  smile'ın forward'a göre ima ettiği olasılıklar ve gerçekleşen sıklık) - hepsi aynı biçimde sinyal (tez, işlem, z,
  giriş / hedef / stop, carry dahil beklenen kâr, risk / ödül, yarı ömür, rejim, uyum, geçtiği ve takıldığı her kapı),
  tek listede sıralı, kayıtlı ve abonelere bildirilen; her sinyal **masanın diliyle** de yazılır: işlem ("USDTRY 3A
  forward sat", "sabit faiz alınan (receive): 2Y OIS"), giriş / hedef / stop enstrümanın kendi fiyatıyla (FX'te
  forward'ın kuru ve spot), beklenen kâr **para olarak** (FX'te 1 mn baz döviz başına kote para biriminde, forward
  primi ve kur hareketi ayrı; faizde bp ve paket DV01'iyle TL) ve bunları anlatan düz bir cümle; FX sinyalleri forward
  pozisyonunun getirisi (kur değişimi − forward primi) üzerinde hesaplanır, forward primi aleyhine olan onu
  karşılamadıkça elenir; hesaplar motoru bekletmeden ayrı iş parçacığında ([aşağıda](#quant-sinyaller)).
* **Masanın kendi köşesi:** sağ üstte **Hata / Öneri** (yöneticilere gider; açık bildirim yalnız yöneticide "!" olarak
  görünür), **Sosyal** (masanın canlı sohbeti) ve **Ajanda** (gün, saat, deadline; her gün / her iş günü / seçili
  günler / ayın son iş günü **tekrarlayan işler**; yaklaşınca ve gelince her sayfada uyarı, "Ertele 10 dk" ve "Bugün
  tamam") ([aşağıda](#masanın-kendi-köşesi-hata--öneri-sosyal-ajanda)).

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
çalışma kitapları, web paketleri) taşıyan **tek bir düz metin dosyası** (~5,6 MB). Aynı dosya
[`kurulum/tto_kur.txt`](kurulum/tto_kur.txt) olarak da yanında durur: ağ `.py` indirmeye izin vermiyorsa onu indirin
(içerik birebir aynıdır).

1. Repoda `kurulum/tto_kur.py` (ya da `kurulum/tto_kur.txt`) → **Download raw file**.
2. İndirdiğiniz yerde:

```bash
python tto_kur.py
```

(`.txt`'yi indirdiyseniz `python tto_kur.txt` - aynı şekilde çalışır.)

Yanına `ratetradingtto` klasörünü açar (ZIP'ten çıkanla aynı program; testler ve kaynak Excel dosyaları hariç) ve
dashboard'u başlatmayı sorar. Sonraki açılışlarda o klasördeki `run.bat`. İnternetten bir şey indirmez, bir şey kurmaz.

* **Güncelleme:** yeni `tto_kur.py`'yi indirip aynı yerde yeniden çalıştırın; değişen dosyalar yenilenir, artık
  olmayanlar silinir, `data` klasörüne ve `vendor/local`'a dokunulmaz.
* **E-postayla:** `tto_kur.txt`'yi ekleyin; içerik düz metindir ve `python tto_kur.txt` aynı şekilde çalışır.
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
* **Yedekleme sayfası** (*Araçlar → Yedekleme*, yalnızca yöneticiler): veritabanının günlük yedeğinin saati, yedek
  klasörü ve ikinci kopya klasörü, **Şimdi yedek al** ve her klasörün son yedekleri; `/api/admin/backup` başkasına 403
  verir (bkz. [Veritabanı](#veritabanı-tutarlı-yazma-açılış-denetimi-günlük-yedek)).
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

**Sayfalar.** Masa, OIS · PPK, Forward, VİOP, Borsa Swap, Carry & Roll, OIS · Nakit Akışı (Excel'de "TM OIS"), DİBS
RV, DİBS ASW, Manuel Tahvil, Eurobond Kotaları (Excel'de "Bulk Bond": masanın XS ISIN'li Türk banka / şirket
Eurobond'ları, dealer fiyat kaynaklarıyla), DV01 Risk, USD · FOMC, Hesaplayıcılar ve - yalnızca **yöneticilere** -
Motor (çalışma kitabının motoru: bootstrap, çözücü, tatiller; menüde, aramada ve kısayollarda başkasına görünmez,
`/api/view/motor` başkasına 403 verir; tatiller Ayarlar'dan düzenlenir). Ek olarak **İzleme · Alarmlar** (her kullanıcının
izleme listesi: VİOP spread'i, kâğıt ASW'i, OIS, offshore, ifadeler, hücreler; z-skoru; seviye, hareket ve z-skoru
alarmları; günün masa notları), **Eğri Hareketi** (OIS, offshore, VİOP ve DİBS'in önceki kapanıştan / açılıştan /
referanstan değişimi, ısı haritası), **Tüm Kâğıtlar** (masanın bütün
TRY DİBS'leri, türüne ve vadesine göre - TLREF ve FRN ayrı; ISIN ile eklenir, ✕ ile çıkar; ★ ile trading listesine), **DİBS Trading** (trading listesinin özeti, T0 / T1 / T2 fiyatları, son
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
| Forward | **Hesaplayıcılar** (Interest 2 SP, SP 2 Interest, all-in, O/N karşılığı, basit ↔ bileşik, tarih yardımcısı …) · Forward fiyatları (USDTRY, EURTRY, serbest forward, vadelere göre TRY faizleri, Forward DV01) · **Kotasyon** (OIS + spread'ten USDTRY / EURTRY forward kotasyon matrisleri ve puandan spread) · RET · Toplu fiyatlama · Eğriler · Offshore · Ticker'lar |
| VİOP | Kontratlar · **Hesaplayıcılar** (VİOP XAUTRY) · Altın · Takvim spread matrisleri · Geçmiş · baz (ima faiz ve OIS farkının tarihsel grafikleri) · Eğriler |
| Masa | Genel bakış · Forward fiyatlama (USDTRY ve EURTRY kotasyon matrislerinin özeti, tarih arası forward ve tarihleri, kırık vade) · Faiz · PPK (tarih arası faiz) · VİOP · Sinyaller · Makro |
| OIS · PPK | Kotalar · Hesaplayıcılar (stub) · PPK ima · En iyi işlemler · Tüm listeler (Parametreler hepsinin üstünde sabit) |
| Hesaplayıcılar | Faiz çevirici (üst bant, basit ↔ bileşik, DF, exponential / simple, implied move) · Maliyet · Tahvil · diğer |
| DV01 Risk, USD · FOMC, Carry & Roll, Motor | konularına göre 3–4 sekme |

Forward sayfası **hesaplayıcılarla açılır**; hepsinin okuduğu valör tarihi (ve spot) sekmelerin üstünde sabit durur.
Son açtığınız sekme hatırlanır. "Tümü" sekmesi sayfanın bütün tablolarını bölüm başlıklarıyla alt alta gösterir;
sayfadaki arama kutusu **bütün sekmelerde** arar. Bir kısayol ya da arama sonucu başka sekmedeki bir tabloyu
gösteriyorsa o sekme kendiliğinden açılır. Üst çubuktaki **"Tablo / hesaplayıcı bul" (Ctrl+K)** kutusu bütün
sayfalardaki tabloları adıyla arar ("interest", "ret", "xautry", "dv01" …); `Enter` ile tabloya gidilir.
**Her hesaplayıcının tek bir yeri var.** Çalışma kitabında aynı hesaplayıcı birkaç sayfada tekrar ediyordu; her biri
bir yerde gösterilir, kopyaları "Yardımcı tablolar"dadır (hücreleri hesaplanmaya devam eder, başlıkları tek yerini
söyler): *Interest 2 SP / SP 2 Interest* ve repo çevirici → Forward → Hesaplayıcılar (Hesaplayıcılar sayfasının B1–B4 ve
B12–B22'si, VİOP'un B8'i kopya); *Forward DV01* → Forward → Forward fiyatları (Hesaplayıcılar B10 kopya); *tarih arası
faiz* → Masa → Faiz · PPK → TARİH ARASI FAİZ (OIS'in "İki tarih arası simple rate"i ve Forward'ın "Forward faiz
hesaplayıcı"sı kopya; Masa'nın "Forward fiyatlama" sekmesindeki TARİH ARASI FORWARD aynı başlangıç, bitiş ve spread'i
kullanır, bunlar orada tablonun hemen üstündeki satırdan da yazılır); Hesaplayıcılar sayfasındaki birebir kopyalar (B21, B22, B29, B30, B34). Masa'nın **forward
kotasyon matrisleri** (USDTRY, EURTRY ve puandan spread) Forward sayfasının **Kotasyon** sekmesine taşındı; Masa'nın
"Forward fiyatlama" sekmesinde USDTRY ve EURTRY matrislerinin özeti durur (aynı girdiler). Masa'nın "FORWARD FİYATLAMA · USDTRY"
tablosu (Forward'daki ÇAPRAZ FORWARD'ın neredeyse aynısı) emekli: yardımcı tablolarda. Hesaplayıcılar sayfasındaki
kullanılmayan limit tablosunun (B35) hücreleri artık girdi değildir.

**Her tablonun girdileri kendi sekmesinde.** Bir tablonun formüllerinin okuduğu girdiler (formüller çalışma kitabında
girdilere kadar izlenir) o tablonun sekmesinde görünür: tablonun içinde, hemen üstündeki bir girdi satırında (başka
sayfanın hücreleriyse "ödünç": aynı girdi, hangisine yazılırsa yazılsın) ya da sekmelerin üstünde sabit duran bir
panelde. Masa'da forward kotasyon özetlerinin **eğri seçimi** özetin ilk satırında; VİOP sekmesinde DEALS'in **vade
sınırı** ve TARGET'ın **hedefleri** (VİOP sayfasının hücreleri, **FRA eğrisi** dahil) tablolarının üstünde; Sinyaller sekmesinde **OIS
parametreleri** (DV01/bacak, yuvarlama, vade limiti, C+R ufku ve PV / FV), **DİBS RV ayarları** (ufuk, sinyal eşiği,
fiyat tipi, varsayılan repo) ve **C+R patikası** okuyan tablonun üstünde. OIS · PPK'nın ve DV01 Risk'in **Parametreler**'i
sekmelerin üstünde sabit; USD · FOMC'nin **Girdiler**'i onu okuyan her sekmede; Carry & Roll'un üstteki OIS satırı C+R
nominali ve yönünü, DV01/bacak ve yuvarlamayı da gösterir. TM OIS, Manuel Tahvil ve DİBS RV'de hedge nominalini
boyutlayan DV01/bacak ve yuvarlama, DV01 Risk'in Hedge sekmesinde yuvarlama, VİOP → Altın'da "Forward tarihi" satırının
tarihi (Forward sayfasının valörü), Tüm Kâğıtlar'da RV sütunlarının sinyal eşiği ve fiyat tipi tablonun üstündedir.
Masanın ortak ve kurulum verisi kendi yerinde kalır: tatil listeleri, fiyat kaynağı sırası, ticker'lar, toplantı
tarihleri, RET eğrisi, gün sayımı kuralları, spot valörleri, elle yazılan piyasa verisi (TLREF, manuel spot, altın),
OIS çözücüsünün ayarları ve senaryolar, Motor'un kurulumu. Büyük bir girdi tablosu başka sekmede ya da sayfadaysa
tablonun ya da sekmenin notu nerede yazıldığını söyler (DV01 Risk'in yapıştırılan pozisyonu ve hedge enstrümanları,
DİBS RV'nin kâğıt bazındaki girdileri, Motor'da C & R'nin ufukları). Bunu `tests/test_views.py` her görünür tablo
için denetler; ortak veri ve notla anılan girdiler oradaki listelerde, gerekçeleriyle durur.

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
  değiştirince herkes görür. Masanın referans verisi hep ortaktır: VİOP'taki USD / TRY OIS ve ICAP ticker'ları
  (`C16:D35`, `C43:C52`, `C58:C69`), spot ticker'ı (`S340`) ve swap gün bazı (`R353`); Motor'un ticker kökleri (`O89`,
  `O130`), "Kotalı" bayrakları (`C327:C342`) ve tatil adları (`B361:B523`, tarihler zaten ortaktı); Masa'nın OIS geçmişi
  kaynağı (`S171`); Eurobond Kotaları'nın fiyat kaynakları ve alanları (`K1:V2`); DİBS RV'nin TLREF gecikmesi (`V2`);
  DV01 Risk'in kova tanımları (`H6:I25`) ve OIS çözücüsünün kovaları (`B442:G457`). Bir kullanıcının bunlar kişiselken
  sakladığı değer bir sonraki açılışta silinir (masanınkini gizlerdi). Tersine, DİBS RV'nin carry / roll **ufku**
  (`J2`, "Ufuk (ay)") artık kişiseldir: herkes kendi ufkunu seçer (masanın daha önce yazdığı ufuk, kimse kendi değerini
  yazmadıkça herkesin başlangıç değeri olarak kalır).
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
  sayfalarda geçerlidir; yeni oturum kapalı başlar. Senaryolar bu değerleri de saklar. Bir formülün üzerine ilk kez
  yazmak kimsenin hesabını silmez; yalnız o hücreyi okuyanlar, yalnız yazan kişi için yeniden hesaplanır. Eskiden
  bütün çalışma kitabı herkes için baştan hesaplanıyordu ve masa bilgisayarında herkes ~20 sn bekliyordu.
* **Girdiye formül (Excel'deki gibi `=`).** Sarı ya da yeşil bir girdi hücresine `=` yazıp başka bir hücreye tıklayın:
  adresi formüle girer - aynı tablonun, sayfanın başka bir tablosunun, **başka bir sekmenin** (sekmeye tıklayınca formül
  pencerenin üstündeki kendi çubuğunda sürer), yan panelin ya da bir launchpad kutusunun hücresi. Aynı sayfanın hücresi
  yalın adresiyle (`=C60+7`), başka sayfanınki adıyla (`=Forward!D2`), başka kitabınki köşeli parantezle
  (`=[sofr]SOFR_FOMC!B9`) girer; sürükleyince aralık (`P94:P99`). Düz tık başvurunun girebileceği yerde çalışır
  (`=`, bir işlem, parantez ya da ayırıcıdan sonra; az önce eklenenin yerine), **Ctrl+tık** formülün her yerinde; başka
  bir yere tık yazmayı bitirir. `Enter` kaydeder, `Esc` vazgeçer. İşlevler, `;` ve ondalık virgül kişisel hesap
  tablosundaki gibidir (aynı derleyici ve hesap).
  Formülün sonucu hücrenin **değeridir** - elle yazılmış gibi her yere gider (sayfalar, launchpad'ler, Excel'e kopya) ve
  hücrenin kendi biçimiyle görünür (valörde tarih). **Canlıdır:** okuduğu bir hücre değişince - başka bir girdi, piyasa,
  saat - kendiliğinden yeniden hesaplanır; okuduğu hiçbir şey değişmeyen formül hesaplanmaz. Hücrenin sol üstünde küçük bir
  **ƒ** durur; üzerine gelince formül görünür, `F2` / çift tık formülü düzenletir, durum çubuğu da onu gösterir;
  Senaryolarım'daki girdi listesi formülü ve şimdiki değeri yazar. **Kişisel** (sarı) girdinin formülü yalnız sizindir
  ve sizin görünümünüzü okur (girdileriniz, elle değerleriniz), o anki rolünüzle (yöneticilikten çıkan birinin Motor'u
  okuyan formülü durur, geri verilince yeniden okur); **ortak** (yeşil) girdinin formülü herkesindir, herkesin gördüğünü
  okur - kimsenin yetkisiyle değil: yönetici yazsa da Motor'u okuyamaz - ve ortak girdiyi yazabilen herkes yazabilir.
  `Delete`, "Girdilerimi sıfırla" ve her sıfırlama formülü de siler; formülün üzerine yazılan değer onun yerini alır.
  Formül değeriyle birlikte sunucuda saklanır, yeniden başlatmada kalır; senaryolar formülleri de saklar.
  **Reddedilenler** (nedeniyle): Bloomberg işlevleri (BDP, BDH, BDS, BFXFORWARD, `_xll.` … - günlük veri limiti); yazıldığı
  hücreyi okuyan formül (doğrudan, çalışma kitabının formülleri ya da başka formüllü girdiler üzerinden: **döngüsel
  başvuru**, yolu yazılır: `MASA!C60 → MASA!C171 → MASA!C60`); okunamayan ya da olmayan bir işlev / ad / sayfa yazan
  formül. Listeli hücreler (B/S …), "Elle değer" hücreleri ve **toplantı takvimiyle kayan hücreler** (OIS'in toplantı
  tarihleri ve toplantı başına adımları, `OIS_MAIN!P10:P89` ve `U10:W89`: takvim kayınca değerleri toplantısıyla
  taşınır, bir formülün başvuruları taşınmazdı) formül almaz - önceki bir sürümün oraya aldığı formül açılışta kalkar,
  değeri kalır, günlük dosyasına yazılır. Değeri bir **Bloomberg isteğine giren** hücreye (Forward'ın valörü, ticker'lar …)
  canlı fiyat ya da `NOW()` okuyan formül yazılmaz - her tikte yeni bir istek doğururdu; `=TODAY()+30` gibi günde bir
  değişen olur. Reddedilen formül `Enter`'la yazıldıysa hücre aynı metinle yeniden açılır; başka bir yere tıklandıysa
  yalnızca uyarı çıkar (formülüyle), seçim tıklanan yerde kalır.
  **Durmayan döngü, takılan formül olmaz.** Sonradan oluşan bir döngü (okuduğu girdinin kendi formülüne dönmesi gibi)
  dönüp durmaz: formül birkaç turdan sonra durur, değeri `#CALC!`, nedeni hücrede. Hesap süresi sınırını aşan formül
  (yeniden başlatma sonrası soğuk hesap) değerini korur, biraz sonra yeniden denenir, ancak üst üste birkaç kez aşarsa
  durur. Duran formül, sahibi bir girdi yazınca bir kez hemen, yine durursa artan aralıklarla yeniden denenir;
  yeniden yazınca hemen. Değeri bir Bloomberg isteğine giren hücrede duran formül `#CALC!` yerine **son iyi değerini**
  korur (orada hata değeri boş bağımsız değişkenli yeni bir istek olurdu), nedeni hücrede. Piyasayı izleyen formülün
  değişmesi masa değişikliği sayılmaz (kendi girdisi olanların sayfaları piyasa hareketindeki gibi yenilenir); formülü
  yazmak ya da değiştirmek sayılır.
* Yüzde hücrelerine `35,5`, `35,5%` ya da `0,355` yazılabilir (Excel'in otomatik yüzde girişi gibi).
* **Nominal / tutar** hücrelerine masanın kısaltmasıyla da yazılır: `100m`, `2,5mn`, `1,5 milyon`, `500k`, `500 bin`,
  `1,5b`, `2 milyar` (Hazine İhalesi'nin teklif ve gerçekleşen nominali; OIS'in "DV01/bacak $"ı, "Yuvarlama TL" ve
  "Nominal C+R"'si, USD · FOMC'un "Hedef DV01 ($/bp)"si, DV01 Risk'in "Murex P&L" ve "Yeni işlem / day-1 P&L"si,
  OIS · Nakit Akışı'nın "Nominal (TL)"'si, Forward ve Hesaplayıcılar'ın "Tutar"ı). Bu hücrelerde anlaşılmayan bir tutar hata
  verir, metin olarak kalmaz (kalsaydı tutarlar ve toplamlar sessizce boş görünürdü). DİBS RV'nin "Sat nominal
  (mn)"'si zaten milyon cinsindendir, kısaltma almaz.
* **Listeli hücreler** (çift tıkta seçenekler açılır) yazılarak da doldurulur; büyük / küçük harf ve Türkçe İ / ı
  farkı önemsizdir. Forward DV01 bloklarının **B/S** hücresi (`Forward!O44`, `Calculators!X29`) yalnızca `B` / `S`
  alır; `Al` / `Sat` (`Alış`, `Satış`, `Buy`, `Sell`) karşılığına çevrilir, başka bir metin reddedilir: formüller
  yalnız "S"yi aradığından "Sat" yazılan satış eskiden sessizce alış diye fiyatlanıyordu.
* Sayılar seçili **sayı biçimine** göre okunur (sağ üstteki `1.234,56` düğmesi): Türkçe biçimde `12.345` on iki bin
  üç yüz kırk beştir (Türkçe Excel gibi), İngilizce biçimde `12,345`.

**Kopyala / yapıştır.**

* Fareyle sürükleyip (ya da `Shift` + ok / `Ctrl+A`) seçin, `Ctrl+C` → Excel'e yapıştırın. Her tablonun
  başlığında "Kopyala" düğmesi de var. `Ctrl+Shift+C` sayıları tam hassasiyetle (15 basamak) kopyalar.
* Excel'den kopyaladığınız bloğu bir girdi hücresine tıklayıp `Ctrl+V` ile yapıştırın; girdi olmayan hücreler
  atlanır (kaç hücrenin yazıldığı / atlandığı bildirilir). `=` ile başlayan yapıştırılmış metin formüldür (yazılmış
  formülün denetimleriyle). Blok Excel'deki yerleşimiyle oturur: tablonun
  göstermediği (Excel'de gizli ya da boş olduğu için atlanan) satır ve sütunlar da sayılır, tablonun kendi aralığı
  dışına hiçbir şey yazılmaz. Dashboard'dan kopyalanıp dashboard'a yapıştırılan blok ise ekrandaki hücrelere oturur.
* **Excel'de gizli sütunlar** varsayılan olarak gösterilmez ve kopyalanmaz (ör. VİOP'taki eğri tablolarının ticker sütunu): tablo
  Excel'de gördüğünüz haliyle kopyalanır. Tablo başlığındaki "+N gizli sütun" ya da "Yardımcı tablolar" düğmesi
  onları (ve ara hesap tablolarını) açar; açıkken kopyalanan blok Excel'deki sütun düzeniyle aynıdır.
* Alt durum çubuğu seçili hücrenin Excel formülünü (formüllü girdide girdinin formülünü), çoklu seçimde toplam /
  ortalama / adedi gösterir.

**Sütunları gizleme / gösterme.** Herkes tablolara kendi gözüyle bakar: bir tablonun istemediğiniz sütunlarını
gizleyin; yalnız sizin görünümünüz değişir.

* Sütunun başlığına (ya da bir hücresine) sağ tıklayın → **"Sütunu gizle: …"**. Birkaç sütun seçiliyse "Bu N sütunu
  gizle"; iki satırlı başlığın üstündeki birleşik başlık altındaki sütunların hepsini gizler.
* Tablo başlığındaki **"Sütunlar"** düğmesi ("Kopyala"nın yanında) bütün sütunları işaret kutularıyla listeler: işareti
  kaldırılan gizlenir, konan geri gelir; liste açık kalır. Çalışma kitabı tablolarında sütunun Excel'deki harfi de
  yazar. **"Tümünü göster"** hepsini geri getirir.
* Gizli sütunu olan tablonun başlığında **"Gizlediğiniz N sütun"** etiketi durur (üzerine gelince hangileri, tıklayınca
  liste); gizli sütunların yerini başlıktaki mavi çizgi gösterir. En az bir sütun her zaman görünür kalır.
* Seçim hesabınızla sunucuda saklanır: sayfayı yeniden açınca, başka bir bilgisayardan ya da tarayıcıdan girince aynı
  sütunlar gizli gelir; başkalarının görünümü değişmez. Çalışma kitabı tablosunda sütun Excel'deki harfiyle, dashboard'un
  kendi tablolarında başlığıyla tanınır (sıralama oku ya da seçilen ölçüyle değişen başlık yine aynı sütundur).
* Gizli sütun **kopyalanmaz** ("Kopyala" ve `Ctrl+C` ekranda göreneni alır) ve ona **yazılmaz**: yapıştırma, `Delete`,
  "Kendi girdimi sil" gizli sütundaki girdilere dokunmaz; Excel'den gelen bloğun gizli sütuna düşen değerleri bırakılır
  ("N hücre gizlediğiniz sütunda olduğu için yazılmadı"). Ok tuşları gizli sütunu atlar, durum çubuğundaki toplam /
  ortalama yalnız görünen hücreleri sayar; dondurulmuş sütunlar (ISIN gibi) yerinde kalır, canlı yenileme seçimi bozmaz.
* Kapsam: çalışma kitabı sayfalarının tabloları ve dashboard'un kendi tabloları (Gün Sonu, PPK, Spread, Ayarlar
  listeleri, Günlük İşlemler, Broker Chat, Spot / FX, FX Vol İzleme, Realized Vol · Carry, İzleme · Alarmlar, Eğri
  Hareketi); İzleme listelerinde ve ısı haritalarında sağ tık sütun başlığında çalışır. Sayfa gezgini, pencerelerdeki küçük
  tablolar ve ayar formları dışarıda. "+N gizli sütun" (Excel'in herkes için gizlediği sütunlar) bundan ayrıdır.

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
Senaryolar kullanıcıya özeldir. Formüllü girdiler formülleriyle saklanır; yüklenince formül o anki değerlerle yeniden
hesaplanır.

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
İndirmeden önce Broker Chat'te masanın **girilmemiş işlemi** varsa (aşağıda: *Chat ↔ Günlük İşlemler*) uyarır: liste
gösterilir, "Listeyi aç" ya da "Yine de indir".

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
* **Masa alarmları (herkese)** - sayfadaki "Masa alarmları · herkese" bölümü (`tto/deskalarms.py`):
  * **Yöneticiler kurar**, herkes için: bölümdeki **Masa alarmı kur…** ya da alarm penceresinde **"Masa alarmı: herkese
    çalar"** (yalnızca yöneticide görünür). Koşullar kişisel alarmlarınkiyle aynıdır (seviye, hareket, z-skoru; her
    konu), ama masa alarmı **piyasanın değerleriyle** denetlenir - kimsenin kişisel senaryosuyla değil. Silmek ve
    yeniden kurmak da yöneticilerin işidir; listede kimin kurduğu yazar.
  * Çalınca **açık her sayfada** kırmızı kenarlı uyarı çıkar (kısa ses, izin verildiyse tarayıcı bildirimi) ve üst
    şeritte **"🔔 N masa alarmı"** belirir: kimsenin cevaplamadığı alarm sayısı (tıklayınca bu bölüm açılır).
  * **"Gördüm, ben bakıyorum"** (uyarıda ya da listede): herkesin ekranında **"✓ Gördüm – Ayşe bakıyor"** olur, alarm
    sayaçtan düşer. İlk cevap geçerlidir; sonraki cevaplar onu değiştirmez.
  * **Sustur** (🔔 düğmesi) **kişiseldir**: alarmı yalnızca susturan kişi için 15 / 30 / 60 / 120 dakika ya da gün sonuna
    kadar susturur. Alarm yine çalar ve herkese gelir; susturana o sürede uyarı, ses ve bildirim gelmez, üst şeritteki
    sayacına da girmez (listede "🔕 sizin için susturuldu · bitiş 14:47" yazar). Susturma kaldırılınca ya da süre
    bitince yine ona da gelir. Kimin kendisi için susturduğu günün kaydına geçer. "Gördüm" cevabı herkes için geçerli
    kalır.
  * **Sistem alarmları** (kendiliğinden; veritabanınınki dışında yalnızca canlı veride):
    * **Bloomberg veri akışı:** piyasa saatinde veri **3 dk** boyunca bayat (bkz. [Operasyon](#operasyon) → Veri tazeliği:
      yardımcı süreç sessiz ya da tick gelmiyor, ya da bağlantı yok).
    * **TLREF fixingi:** masanın iş gününde **14:00**'e kadar bugünün TLREF fixingi gelmediyse. Fixing, tarihçenin
      `BISTTREF Index` kapanışlarından görülür (canlıda 15 dakikada bir güncellenir); tarihçe kapalıysa (`--no-history`)
      bu alarm denetlenmez.
    * **Veritabanı:** açılıştaki denetim başarısızsa, günlük yedek alınamadıysa, seçilen klasöre yazılamadığı için
      dashboard'un kendi klasörüne alındıysa (seçilen klasöre ulaşana kadar) ya da yedeğin ikinci kopyası (başka sürücü
      ya da paylaşım) **iki gün üst üste** alınamadıysa ([Operasyon](#operasyon); tek günlük kopya hatası yalnızca durum
      penceresinde görünür; ikinci kopya seçilmemişse onun için alarm yoktur). Metin klasör adı içermez.
    Koşul başlayınca bir kez çalar, bitince kendiliğinden kapanır ("düzeldi"); gün içinde yeniden başlarsa yeniden çalar.
    RET eğrisi için sistem alarmı yoktur: eğri günün her saatinde değişebilir, belli bir yükleme saati yoktur.
  * **Bugünün kaydı:** ne çaldı, kim gördü, kim neyi kendisi için ne kadar susturdu, ne kuruldu / silindi / yeniden
    kuruldu, ayarlarda ne değişti - saatiyle. Her gün yeni kayıt.
  * **Ayarlar** (yöneticiler değiştirir, herkes görür; bölümün altında): piyasa saatleri (09:00–18:00), kaç saniye tick
    gelmezse veri bayat sayılır (120), her sistem alarmının açık / kapalı oluşu ve eşiği (3 dk, 14:00).
  * E-posta, Teams ya da webhook gönderilmez (henüz karar verilmedi): uyarıyı dashboard'u açık tutan ekranlar görür.

Gün içi çizgi ve açılış dashboard açıkken toplanır (yeniden başlatılınca açılış korunur, çizgi o andan devam eder).

**Eğri Hareketi (ısı haritası).** Masa grubunda: piyasanın bir bakışta nereye gittiği.

* **TRY OIS · offshore · fark**: vade vade (O/N–10Y) OIS (O/N'de TLREF), offshore (FX swap ima TRY; 1Y sütununda
  12M) ve **offshore − OIS** farkı.
* **VİOP**: her kontratın **OIS − VİOP** spread'i ve ima TRY faizi.
  Sütun başlığı kontratın vade ayıdır (`Kas26`, `Ara26`, `Oca27` …); ticker ve son işlem günü üzerine gelince görünür.
* **DİBS**: trading listesindeki kâğıtlar vadeye göre; getiri, ASW, pahalı / ucuz.
* Her hücrede değişim (bp, büyük) ve seviye (küçük); **kırmızı yükseldi, mavi düştü**, renk koyulaştıkça hareket
  büyür (ölçek, günün en büyük hareketine göre ±5 / 10 / 15 / 20 / 25 / 50… bp; açıklama üstte). Değişim neye göre:
  **Önceki kapanış** (OIS, TLREF, offshore için tarihçe; diğerleri için dashboard'un kendi kaydı - ilk gün boş
  kalır), **Açılış** (dashboard'un bugün gördüğü ilk değer) ya da **Referans** ("Referansı şimdi al" ile alınan
  seviyeler; ör. sabah toplantısı - kişiye özel, her gün yeni).
* **Önceki kapanış, bir önceki iş gününün kapanışıdır.** Dashboard kendi kapanışını yalnız piyasanın açık olduğu
  günlerde kaydeder (hafta içi, masanın tatil listesi - `Motor!A361:A523` - dışında); hafta sonu ya da tatilde
  kaydedilmiş bir değer kapanış sayılmaz. Cumartesi ve pazar piyasa kapalıdır: son iş gününün kapanışı geçerli
  kalır, o günün kapanışı olan her noktada seviye o kapanıştır ve değişim **0**'dır (valörü kayan bir kâğıdın
  getirisi de oynamaz); bilgi satırı "Hafta sonu, piyasa kapalı" yazar. TR tatillerinde offshore Londra'da işlem
  gördüğü için değişim olağan şekilde, son kapanışa göre hesaplanır.
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
| `6x9m vs 9x12m -65/-35` · `6x9 fra v 9x12 fra` · `1y1y vs 2y1y` · `5y vs. 2y` · `2y ois versus 5y ois` | **"vs" ile iki enstrüman** (`vs`, `v`, `vs.`, `versus`): spread (bp), geç olan − erken olan (9x12 − 6x9, 5Y − 2Y), yazılış sırası fark etmez. İki FRA ya da forward tahtada **kendi satırında** durur (6x9 FRA'nın kotası sayılmaz); modeli iki FRA'nın eğrideki farkı. Günlük İşlemler'de formu olmadığından "İşlem gir" çıkmaz |
| `dec mpc 3650/3700` · `Dec MPC 36.50/37.00` · `mpc dec` · `aralık ppk` · `dec meeting` · `dec26 mpc` · `mpc1` · `mpc 2` · `1st mpc` · `next mpc` | **MPC tarihli OIS** (toplantıdan toplantıya): ay adı (İngilizce / Türkçe, yılla ya da yılsız) ya da sıra numarası `mpc` / `ppk` / `meeting` / `toplantı` kelimesinin yanında. Ay, o ayın önümüzdeki ilk toplantısıdır (bir ay öncesine kadar geçmiş olan da: dönemi sürüyorsa); numara toplantıları satırın gününden sayar (karar günü o toplantı hâlâ MPC1'dir). Toplantının etkin gününden (karardan sonraki iş günü, OIS sayfasındaki "MPC OIS" tablosu) sonraki toplantının etkin gününe |
| `dec/jan mpc` · `dec-jan mpc` · `dec jan mpc` · `mpc1/2` · `dec/mar mpc` · `spot/dec mpc` | iki toplantı arası (Aralık → Ocak; `dec mpc` ile aynı enstrüman) ya da birkaç dönem (Aralık → Mart); `spot/dec`: OIS spot'tan Aralık toplantısına |
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
* **Tahta** her enstrümanın son durumunu gösterir: **en iyi bid ve ask** (aşağıda), son işlem (yeşil: offer alındı,
  kırmızı: bid'e verildi; üzerine gelince kimde), **model** – dashboard'un kendi TRY OIS eğrisinin o enstrüman için
  verdiği seviye (outright: par; spread ve fly: par farkları, bp; FRA / forward: eğrinin forward'ı; kişisel
  senaryonuzla) – ve en iyi bid − model, en iyi ask − model farkları (bp). Bid modelin üstünde ya da ask modelin
  altındaysa fark vurgulanır. Satır sonundaki ≡ o enstrüman için söylenen her şeyi aşağıda listeler.
* **En iyi fiyat, broker broker.** Bid ve ask sütunları brokerların **taze** kotalarının en iyisidir (en yüksek bid, en
  düşük offer; getiriyle kote edilen bonoda tersi); yanında **hangi broker'da olduğu ve kaç dakika önce söylendiği**
  ("Tullett · 2 dk"; aynı seviyede iki broker'dan son söyleyen). Sonra söylenen daha kötü bir kota başka bir broker'ın
  daha iyi kotasını artık örtmez. Broker, satırın kaynağıdır (kurum; yoksa gönderen). Bir enstrümanın iki ya da daha çok
  broker'ı ya da bayat kotası varsa altında her broker'ın kendi satırı vardır (`↳ ICAP`: bid, ask, yaşları; başlıktaki
  "Brokerlar" kutusuyla gizlenir).
  * **Bayat kota en iyi sayılmaz.** Bayat sınırından (varsayılan **10 dakika**; tahtanın başlığındaki "Bayat … dk",
    masa için ortak, 1 – 1440) eski kota broker satırında soluk ve yaşıyla ("bayat · 42 dk") durur, en iyi fiyat olmaz;
    o tarafın yalnız bayat kotası varsa en iyi hücre boş, yanında "bayat" yazar (üzerine gelince kimin, hangi seviye, ne
    kadar eski). Kotanın yaşı söylendiği saatten sayılır – kaydedildiği an daha erkense ondan: saati ileri yazılmış bir
    satır taze sayılmaz. Sayfa açıkken bugünün tahtası 20 saniyede bir kendiliğinden tazelenir (bayatlayan kota kimse bir
    şey yazmadan en iyi fiyattan iner). Geçmiş bir gün ya da bugünle bitmeyen bir aralık, sonundaki hâliyle ve yaş yerine
    saatle gösterilir.
  * **Tahtadan inen kota.** Broker'ın geri çektiği taraf (`ref`: yalnız o broker'ınki), tahtanın sıfırlanmasından önce
    söylenen her şey (sıfırlama kuralları aynen) ve **işlemle giden** kota en iyi fiyat olamaz: offer bir seviyeden
    alındığında (taken, paid) o seviyedeki ve altındaki bütün offer'lar, bid verildiğinde (given, hit) o seviyedeki ve
    üstündeki bütün bid'ler, tarafı söylenmeyen işlemde ikisi de iner (daha iyisi ya önce alınmıştır ya da gerçek değildir);
    seviyesiz işlemde işlemi söyleyen broker'ın o tarafı. Bir "oco" mesajının kotası işlem görünce mesajın öbür kotaları
    da iner. Broker'ın sonradan söylediği kota (`sell a bal at 14`) yeniden gelir.
  * **Bizim kotamız** ayrı sütundadır ve en iyi fiyata girmez; bayatsa soluk.
  * Excel'deki "Tahta" sayfası en iyi bid / ask'i, kimde olduğunu ve yaşını yazar; "Brokerlar" sayfası her broker'ın
    kotalarını, bayat olanları işaretli.
  * **Sayfanın dışında da aynı kurallar:** DİBS RV'nin, DİBS Trading'in (özet ve valörler), Tüm Kâğıtlar'ın broker
    sütunları ve kâğıt kartı (aşağıda) da bu tahtayı gösterir - en iyi taze bid / ask, bayatı soluk, broker'ı ve yaşıyla.
* **FX swap** satırlarında puanın
  **ima ettiği TRY faizi** (ACT/360) ayrı sütundadır: Forward sayfasının spotu, vadenin gün sayısı (offshore
  tablosundaki Bloomberg `DAYS_TO_MTY`; o/n bir Cuma'da 3 gün) ve o kadar günün USD faiziyle – bid tarafı USD ask'iyle,
  ask tarafı USD bid'iyle, Forward sayfasının forward'ı fiyatladığı gibi.
* **MPC tarihli OIS.** `dec mpc`, `mpc1`, `dec/jan mpc` aynı iki günün swap'ıysa (Aralık kararının ertesi → Ocak kararının
  ertesi) tahtada **tek satırdır** (`MPC Ara26`; birkaç dönem `MPC Ara26–Mar27`, spot'tan `MPC Spot–Ara26`); outright'ların
  hemen altında, tarih sırasıyla durur. Tarihler toplantı takviminden gelir (geçmiş toplantılar ve OIS sayfasındaki liste);
  takvimde olmayan bir toplantı ("dec35 mpc") okunur ama tarihlenemez ("toplantı?" etiketi, modeli yok). **Model**, OIS
  sayfasındaki "MPC OIS" tablosunun bootstrap seviyesidir (tablonun kendi iskonto faktörlerinden: Günlük İşlemler'in MPC
  formundaki "Piyasa mid"in aynısı); kısa yazılan seviyenin büyük rakamı da ondan tamamlanır. Tek dönemlik (bir
  toplantıdan sonrakine) satırın son sütununda **ima PPK adımı** vardır: seviyenin günlük bileşik ON karşılığı − toplantıdan
  önceki dönemin bootstrap seviyesinin ON karşılığı (bp; ilk toplantıda spot'tan toplantıya, sonrakilerde önceki toplantıdan);
  yanında bootstrap'ın kendi adımı ("adım −62 / −52 bp · model −68"). PPK Fiyatlama Geçmişi'ndeki adım MPC çözücüsünündür,
  burada piyasa bootstrap'ı kullanılır. İki dönemi birbirine karşı koyan kota (adım: `dec vs jan mpc -25/-20`, `… spread`,
  eksi seviye) okunmaz, metin kalır.
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
  `Jan30`, `April 31`, `Sep 34`) masanın TRY DİBS listesinden (aşağıda: *DİBS kataloğu*) kâğıdı bulur; `tlref`, `frn`,
  `cpi`, `zc` kelimesi türünü söyler: **`tlref` yalnız TLREF'e endeksli kâğıda, `frn` yalnız FRN'e gider** (`float`,
  `floater`: ikisinden biri). **Ay-yıl tek başına önce sabit kuponlu kâğıt demektir** (`mar28`, `feb27`); o ayda
  sabit kuponlu yoksa ayın öbür kâğıdı anlaşılır (`jan30` → 02.01.30 FRN ya da 09.01.30 TLREF): önce floater'lar (TLREF,
  FRN), sonra TÜFE, sonra bono / kuponsuz; birden
  çoksa ekran fiyatı söylenen seviyeye en yakın olan ("kâğıt?" ve "sabit kuponlu değil" etiketleriyle). Tür yazılmışsa
  (`jan30 tlref`, `jan30 frn`, `jun29 cpi`, `feb27 zc` ya da bitişik `feb27zc`) yalnız o tür aranır; o ayda o türden kâğıt yoksa satır
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
  dolu açar: OIS (outright, spread, fly, FRA / forward, **MPC**: formun MPC stratejisi, başlangıç ve bitiş toplantının
  günleriyle seçili), FX swap (USDTRY; vade valör olarak, `2M`) ve DİBS. Açılan
  pencerede seviye (işlem / bid / ask) ve **bizim yönümüz** seçilir. Yön satırdan önerilir: bizim kotamızda bid'imize
  satıldıysa biz alıcıyız (PAY · steepener · gövde PAY · USD al · kâğıt al), offer'ımız alındıysa satıcı; broker
  kotasında tersi (bid'e verdik: satıcı, offer'ı aldık: alıcı); işlem satırında offer alındıysa alıcı, bid'e
  verildiyse satıcı. Not alanına chat satırı, karşı taraf alanına broker'ın kaynağı yazılır; tutarı yazıp kaydetmek
  yeter. Listede olmayan bir vade ya da söylenmemiş yön uyarıyla bildirilir.
* **Chat ↔ Günlük İşlemler.** Masanın chat'te söylediği işlemler (taraf *Biz* olan işlem satırları: "İsimler · kaynaklar"daki
  taraf ya da yapıştırırken seçilen "Biz") Günlük İşlemler'deki kayıtlarla eşleştirilir: **aynı enstrüman, aynı seviye,
  chat'teki saatin ±15 dakikası** içinde girilmiş kayıt (bir kayıt bir satırla; iki aday varsa saati yakın olan); "İşlem gir"
  ile açılıp kaydedilen kayıt ise notundaki chat satırıyla, saatine bakılmadan eşleşir. OIS (outright, spread, fly, FRA /
  forward, MPC), FX swap (USDTRY, vadenin günü ± birkaç gün, puan) ve DİBS (ISIN ve fiyat; getiriyle kote edilen bonoda
  yalnız kâğıt ve saat) karşılaştırılır; formu olmayanlar (cross currency, IRS, switch, O/N – T/N) sayılmaz. Bugün
  girilmemiş olanların sayısı menüde Broker Chat'in yanında **"N işlem girilmedi"** rozetidir (dar menüde yalnız sayı);
  rozete ya da sayfadaki "Chat ↔ blotter" düğmesine tıklayınca liste açılır: satır, işlemi, durumu (girildi / girilmedi /
  elle eşleştirildi / yok sayıldı / formu yok) ve Günlük İşlemler'deki kaydı (girilme saati, chat'e göre farkı). Girilmemiş
  satırda **⇢ Gir** (Günlük İşlemler'i dolu açar), günün bir kaydıyla **Eşleştir** ve **Yok say**; otomatik eşleşmede
  **Yanlış eşleşme** (o kayıt bu satırın değil), elle yapılanda **Geri al**. Kararlar herkes için geçerlidir; eşleştirilen
  kayıt silinirse satır yeniden aranır. Gün sonu arşivi indirilmeden önce girilmemiş işlem varsa uyarılır.

Anlaşılmayanlar: iki toplantı dönemini birbirine karşı koyan kotalar (`dec vs jan mpc -25/-20`, `dec/jan mpc spread`)
ve tek kelimelik yanıtlar metin olarak kalır.

**DİBS kataloğu ve ISIN ile ekleme.** Masanın Bloomberg listesindeki 77 TRY devlet iç borçlanma senedi (bono,
kuponsuz, sabit kuponlu, TÜFE'ye endeksli, TLREF'e endeksli, FRN; ISIN, vade, kupon) dashboard'la gelir
(`tto/data/try_bonds.json`); masanın Tüm Kâğıtlar'da eklediği kâğıtlar da bu katalogdadır (aşağıda). DİBS RV, DİBS ASW
ve Eurobond Kotaları tablolarının başlığındaki **"+ ISIN ekle"** bir
pencere açar: ISIN yazılır ya da yapıştırılır (birkaç tane: boşluk, virgül ya da satırla), DİBS RV ve ASW'de
masanın listesi (Tüm Kâğıtlar) da listelenir (türe göre süzgeç, arama; listede olanlar işaretli). Kâğıtlar listenin son kâğıdının
**altına** eklenir (sonda yer kalmazsa aradaki boş satırlara); listede olanlar atlanır, kontrol hanesi tutmayan ISIN reddedilir. DİBS RV ve ASW listeleri
masanındır (herkes görür), Eurobond Kotaları listesi her kullanıcının kendisinin. Türk DİBS ISIN'i vadesini taşır
(`TRT150328T24` → 15.03.2028).

**DİBS RV'de broker chat.** DİBS RV tablosunun sağında her kâğıt için o günün Broker Chat tahtası, tahtanın
kurallarıyla (yukarıda: *En iyi fiyat, broker broker*): brokerların **en iyi taze** bid'i ve ask'i (geri çekilen,
işlemle giden ya da tahta sıfırlanmadan önce söylenen kota yok), son işlem (yoksa tarafı söylenmemiş son seviye, örn.
ihale fiyatı, soluk), **Kimde · yaş** (bid / ask'in hangi broker'da olduğu ve kaç dakika önce söylendiği; duran kota
yoksa son sözün saati), broker orta fiyatının ima ettiği getiri ve **broker − ekran** farkı (bp; + ise brokerlar
kâğıdı ekrandan ucuz görüyor). **Bayat kota güncel görünmez:** bir tarafın yalnız bayat kotası varsa en yenisi soluk
durur, yanında "bayat · ICAP · 42 dk"; getiri ve broker − ekran farkı **yalnız taze kotadan** (taze kota yoksa taze son
işlemden) hesaplanır, hiç taze bir şey yoksa getiri hücresinde soluk "bayat" yazar. Aynı sütunlar DİBS Trading'in
özetinde ve valörler tablosunda, Tüm Kâğıtlar'da da aynıdır. Tahta sıfırlanınca bu sütunlar da boşalır; Excel'e
aktarmada bu sütunlar yoktur (sayfanın hücresi değiller).

**Kâğıtların düzeni: Tüm Kâğıtlar → ★ → DİBS Trading.** Bütün kâğıtlar bir yerde, üzerinde çalışılanlar ayrı:

* **Tüm Kâğıtlar** masanın kâğıt listesidir: türüne göre (bono, kuponsuz, sabit kuponlu, TLREF'e endeksli, FRN,
  TÜFE'ye endeksli), her türde **vade sırasıyla** (eklenme sırası önemsiz): kupon, vade, kalan gün / yıl, Borsa İstanbul
  fiyatı (bid, ask, son işlem ve günü, hacim; bono ve kuponsuz kendi valöründe - `ISL0` -, diğerleri ertesi gün -
  `ISL1`; kaynaklar sarı hücrelerde), trading listesindekiler için DİBS RV'nin getirisi, ASW / DM'i, sinyali ve
  DV01'i, sağda bugünün Broker Chat tahtası, ▸ kart ve ✕. Liste **masanındır** (herkes görür, herkes değiştirir): başta
  katalogdaki 77 kâğıt; **"+ ISIN ekle"** ile kâğıt eklenir - türü, vadesi, kuponu ve adı Bloomberg'den
  (`CPN_TYP`, `INFLATION_LINKED_INDICATOR`, `FLOATER_FORMULA`, `CRNCY`, `MATURITY`, `CPN`) bulunur ve kâğıt kendi
  grubuna girer; **döviz cinsi** kâğıt (`CRNCY` TRY değil) ve Bloomberg'in tanımadığı ISIN reddedilir, Bloomberg henüz
  yanıt vermediyse kâğıt "Türü bekleniyor" grubunda durur ve yanıt gelince (birkaç saniyede bir yeniden sorulur) yerine
  geçer. **✕** kâğıdı listeden çıkarır (onayla; trading listesindeyse oradan da); "+ ISIN ekle" geri getirir. **Vadesi
  geçen kâğıt** ertesi gün kendiliğinden düşer. Kimin ne zaman eklediği ve çıkardığı saklanır (eklenen kâğıdın ISIN'inin
  üzerinde yazar). Liste ISIN'e göre sunucunun veritabanında durur (`kv` · `bonds.desk`); güncellemeler katalogu
  yenilese de masanın eklediği ve çıkardığı korunur. Dashboard listedeki her kâğıdı tanır: Broker Chat eşleştirmesi,
  İzleme, kâğıt kartı, DİBS RV ve ASW'nin ISIN seçicisi. Önceki sürümün **kendi eklediklerimiz** satırlarındaki
  kâğıtlar bir kereye mahsus listeye taşınır (döviz cinsi olan alınmaz, tablonun altında nedeniyle yazar).
* **☆ / ★** kâğıdı **trading listesine** (DİBS RV - ve onunla DİBS Trading) koyar ya da çıkarır; herkes için. Eklenen
  kâğıt listenin son kâğıdının altına girer (masanın gruplar arasında bıraktığı boş satırlar boş kalır; sonda yer
  kalmayınca onlar kullanılır). Çıkarılan kâğıdın satırı boşalır, satırla birlikte kâğıda ait ne varsa silinir: kaynak
  kodu ve herkesin o satıra yazdığı manuel fiyat, kupon, repo (aynı satıra sonra giren kâğıda geçmesin diye). **DİBS
  ASW**'nin ISIN listesi (`ASW!B7:B56`, ASW eğrisi ve grafikleri) trading listesini izler: ★ kâğıdı oraya da ekler
  (listede yoksa, son kâğıdın altına; listede yer kalmadıysa yalnız trading listesine girer), ☆ oradan da çıkarır
  (satırın kaynağı ve herkesin manuel fiyatı / eğri işaretiyle). ASW sayfasının kendi "+ ISIN ekle"si ayrıca çalışır.
* **DİBS Trading** sayfasının başındaki **özet**, trading listesini türüne ve vadesine göre gruplu tek bakışta verir:
  kâğıdın fiyatlandığı valör ve kaynağı, bid / ask, son işlem ve ne zaman olduğu (canlıda görüldüğü saat), DİBS
  RV'den getiri, ASW / DM, pahalı / ucuz, sinyal, mod. süre, DV01 / 1mn, C+R, T0→T1 ima repo, bugünün Broker Chat
  tahtası, ★ (listeden çıkar) ve ▸ (kart). Ayrıntı altta (valörler, günün işlemleri) ve DİBS RV'de.
  **1.000$ DV01 nominal** sütunu, DV01'i 1.000 USD olan TL nominali verir: 1.000 × USDTRY ÷ DV01 / 1mn, en yakın
  5 mn'a yuvarlı (`500m`; TLREF'te spread DV01'i). USDTRY masanın kullandığı kurdur: VİOP!L99 / L100'ün ortası
  (manuel spot, boşsa Bloomberg). Üzerine gelince hesap görünür.

**TLREF ve FRN.** Floater'lar iki türdür: kuponu TLREF'e bağlı olanlar (Bloomberg'in `FLOATER_FORMULA` alanı
"91 D TLREF FLAT" ya da "182 D TLREF FLAT", `RESET_IDX` BISTREFI) ve **FRN**'ler (alan boş, endeks TLREF değil;
katalogda 9 kâğıt: 05.05.27, 17.11.27, 13.09.28, 03.10.29, 02.01.30, 05.06.30, 16.04.31, 10.03.32, 11.08.32). FRN her
yerde kendi adıyla görünür ("02.01.30 FRN"): Tüm Kâğıtlar'da ve DİBS Trading özetinde ayrı grup, kâğıt kartı, İzleme
adları, Hazine İhalesi. **DİBS RV'de FRN yalnız fiyatla izlenir**: tür sütununda "F", kupon sütununda "FRN"
("TLREF+x bp" değil); TLREF'e karşı hesaplanan her şey boştur (DM, alış / satış DM ve farkı, OIS par getirisi,
Z-spread, spread DV01 ve ona bağlı nominal, carry, roll, günlük carry); fiyatlar, işlemiş faiz, kirli fiyat, son işlem
ve repo kalır. DİBS RV ve İhale bir floater'ın FRN olup olmadığını Tüm Kâğıtlar'dan okur; listede olmayan kâğıt için
Bloomberg'e sorar (`FLOATER_FORMULA`'da TLREF yoksa ve `RESET_IDX` TLREF'inki değilse FRN; Bloomberg yanıt vermezse
TLREF sayılır).

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

**Canlı kota mı?** Borsa İstanbul kaynakları (`ISL0` / `ISL1` / `ISLN`) bir tarafta emir yokken de bid / ask verir: son
işlemi (bonoda son işlemin getirisinin yeni valördeki fiyatını) iki tarafa birden yazar - piyasa kapalıyken bütün
kâğıtlarda bid = ask görünmesi bundandır. Emrin büyüklüğü (Bloomberg `BID_SIZE` / `ASK_SIZE`) ikisini ayırır:
büyüklük > 0 ise canlı kota, boşsa (`#N/A N/A`) o tarafta emir yok. Kotasız taraf her sayfada (DİBS RV, DİBS Trading
özeti ve valörleri, Tüm Kâğıtlar, kâğıt kartı) soluk **"–"** görünür; üzerine gelince nedeni ve Bloomberg'in tekrar
ettiği fiyat yazar. Canlı kotanın büyüklüğü ipucunda, kâğıt kartında ayrı sütunlarda (Bid boyutu / Ask boyutu).
Kotasız tarafla hesap yapılmaz: alış / satış getirisi, alış−satış, alış / satış ASW boş kalır; ALIŞ / SATIŞ fiyat
tipi o tarafta canlı kota yokken ortayı kullanır. Kullanılan temiz fiyat (Bloomberg'in orta fiyatı; kota yokken son
işlem ya da yeni valörün fiyatı) ve ondan çıkanlar - getiri, ASW / DM, pahalı / ucuz, sinyal ve broker − ekran
farkı - hesaplanmaya devam eder, ama iki taraflı canlı kota yokken **soluk** gösterilir (ipucunda fiyat durumu).
**Fiyat durumu**: "Canlı kota", "Canlı: yalnız bid / ask", "Kota yok · işlem bugün", "Kota yok · son fiyat (gün)".
İma repo'da iki taraflı canlı kota bugünün fiyatıdır (ortasından), kotasız valörde son işlem kullanılır (aynı gün
şartıyla). Büyüklüğü olmayan kaynaklarda (BGN gibi kompozit kota: `#N/A Field Not Applicable`) ve kayıtlı veri
modunda büyüklük bilinmez: fiyatlar eskisi gibi gösterilir ve kullanılır.

* **Bugünün DİBS işlemleri**: Broker Chat'te söylenen bütün DİBS işlemleri (saat, kâğıt, fiyat, ima getiri, alınan
  taraf, valör, kim söyledi) ve canlıda Bloomberg'de görülenler (hangi valörde, hangi kaynakta), en yenisi üstte.
* **Kâğıt kartı** (Tüm Kâğıtlar, DİBS Trading, günün işlemleri ve DİBS RV'deki ▸): kâğıdın bütün bilgisi tek pencerede - ne olduğu
  (tür, kupon, vade, kalan gün), valörlerdeki fiyatlar (bid / ask boyutlarıyla) ve son işlemler, ima repo, Broker Chat tahtası
  (en iyi taze bid / ask, bayatı soluk, kimde ve yaşı; ima getiri yalnız taze kotadan) ve o günkü bütün chat satırları -
  her kota satırının **durumu**: tahtada duruyorsa "geçerli · 3 dk", duruyor ama bayatsa "bayat · 42 dk", artık durmuyorsa
  (sonra yeni kota geldi, geri çekildi, işlem gördü ya da tahta sıfırlandı) "geçmiş"; bayat ve geçmiş satırlar soluk -,
  günün işlemleri, DİBS RV satırı (getiri, ASW, sinyal, süre, DV01, carry, gün içi aralık). Listede
  olmayan kâğıtta katalog bilgisi ve "DİBS RV listesine ekle" düğmesi.

**Hazine İhalesi** (Tahvil grubunda; `EK_IHALE`). Ivır Zıvır sayfasındaki ihale hesabının yerini alır: ihaleye
gönderilecek **kirli fiyat** ve ihale bitince **sonuç**, üç kâğıt için.

* **Valör ve kâğıt.** Üstte ortak **ihale valörü**; her kâğıda ISIN ve isterse kendi valörü yazılır. Kâğıdın adı, türü
  (sabit kuponlu / TLREF / FRN / TÜFE / bono), kuponu ve vadesi ile **o valördeki** birikmiş faiz, önceki ve sonraki kupon
  tarihi ve işlemiş gün sayısı Bloomberg'den gelir (`INT_ACC`, `PREV_CPN_DT`, `NXT_CPN_DT`, `DAYS_ACC`; `SETTLE_DT` =
  valör). Birikmiş faiz **burada hesaplanmaz**: valör kupon gününe denk gelirse Bloomberg birikmişi 0 verir ve sonraki
  kupona geçer, TLREF'in o dönemki kuponunu yalnız Bloomberg bilir. Bloomberg yanıt vermezse kirli fiyat çıkmaz
  (satırın üstünde nedeni yazar). Valörsüz kirli fiyat yoktur. (Excel'deki blokta ikinci kâğıdın ihale sonucundan
  başka bir kâğıdın birikmiş faizi düşülüyordu; burada her kâğıt yalnız kendi birikmişini kullanır.)
* **Teklifler** (kâğıt başına 5 satır). Nominal (`100m`, `2,5mn`, `500k` gibi de) ve şu üçünden biri yazılır: **temiz fiyat**, **basit** ya da **bileşik
  getiri** (birden çoğu yazılırsa önce temiz, sonra basit; satır hangisini kullandığını yazar). Satır öteki ikisini,
  birikmişi ve **gönderilecek kirli fiyatı** (temiz + birikmiş, 3 haneye yuvarlanmış) ve TL tutarını (nominal × kirli /
  100) verir; altında toplam nominal, nominal ağırlıklı ortalama kirli / temiz fiyat, bunun getirileri ve toplam tutar.
* **Getiriler** DİBS RV'nin "BIST" tanımıyla, iki sayfa aynı getiriyi göstersin diye: sabit kuponluda basit getiri,
  kuponları dönem başına `(1 + y/f)` ile iskonto eden getiridir (dönemin kalan kesri Bloomberg'in önceki / sonraki
  kupon tarihinden; Newton yöntemi kupondan başlar), bileşik `= (1 + basit/f)^f − 1`; bono ve kuponsuzda basit
  `= (100/P − 1)·365/gün`, bileşik `= (100/P)^(365/gün) − 1`. Getiriden fiyat aynı formüllerin tersidir. **TLREF**'te
  ve **FRN**'de getiri yoktur (kirli fiyat ve ihaledeki yer çıkar). **TÜFE**'ye endeksli kâğıt reel fiyat ve reel getiriyle; tutar
  Bloomberg'in valördeki endeks oranıyla (`IDX_RATIO`) TL'ye çevrilir.
* **İhale sonrası.** Açıklanan **asgari, ortalama ve azami** fiyat kirli olarak yazılır (teklif kirliyle verilir): üçünün
  temiz karşılığı ve getirileri; her teklif için **Gerçekleşti / Asgari fiyatta · kısmi olabilir / Gerçekleşmedi**
  (çok fiyatlı ihale: asgari fiyatın üstündeki teklif kendi fiyatından gerçekleşir), ortalamaya fark (fiyat ve basit
  getiride bp), min–maks aralığındaki yeri; asgari fiyattan kısmen karşılanan teklifin **gerçekleşen nominali**
  yazılabilir. Gerçekleşen tekliflerden **ortalama kirli ve temiz fiyatınız**, bunun basit ve bileşik getirisi, ihale
  ortalamasına farkı ve tutar; altında tek cümlelik özet.

Girdiler masa için ortaktır. Bloomberg yükü kâğıt başına bir avuç `BDP` (valör değişince yeniden); `BDH` yok. Kayıtlı
veri modunda Bloomberg yanıtı olmadığından sayfa boş kalır.

**Satır eklenen tablolar.** Eurobond Kotaları (`Bulk Bond` sayfası) tablosu 4 yerine 50 kâğıt alır (alttaki satırlar 6. satırın formülleridir,
ISIN'i boşken hiçbir şey istemez); Forward'daki toplu forward fiyatlama 20 yerine **100 valör** alır (EK_BULK:
sayfanın kendi formülleri, eğri ve faizler Forward sayfasından). Valör ve manuel TRY faizi **boş başlar**: dosyanın
kaydedildiği günün tarihleri bugün kimsenin seçimi değil. Yazılanlar kullanıcının kendisinin kalır. Sayfa dolu
satırları ve bir boş satırı gösterir; **"+ Satır"** bir boş satır daha açar (tercih hatırlanır), **"Tümü"** hepsini
gösterir.

**Realized Vol · Carry.** İki bölümü vardır; ikisi de dashboard'un günlük kapanış tarihçesini (Gün Sonu Matrisi'nin
kullandığı depo) kullanır.

* **Realized vol · yazdığınız enstrüman.** Kutuya, broker'ın yazdığı gibi enstrüman yazılır (virgülle ayrılmış
  birkaç tane olabilir): vade (`18m`), spread (`1y5y` – uzun − kısa), fly (`2y3y4y` – 2 × gövde − kanatlar),
  FRA / forward (`9x12`, `1y1y`), cross-currency için `x` (`5y x`), DİBS RV tablosundaki bir tahvil için ISIN'i
  (`TRT150328T24`: getirisi; floater'da - TLREF ya da FRN - fiyatı). Tablo her biri için seviyeyi, son günün
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

### Launchpad ve gezinme

Sayfalar arasında gidip gelmeyi azaltmak için: kendi tablo sayfalarınız (**launchpad**), her sayfada sağda duran **yan
panel**, **ayrı pencereler**, son açılan sayfalara **hızlı dönüş**, **favoriler**, kendi **açılış sayfanız** ve tabloların
**kendi sütun sıranız**; dashboard'un kendi sayfalarının parçaları da (**sayfaların kutuları**), quant'ın **dört girişlik
menüsü** ve **kendi menünüz**. Hepsi **hesabınızla sunucuda** saklanır (`layout.<kullanıcı>`, sütun sırası
`colorder.<kullanıcı>`): girdiğiniz her bilgisayarda aynıdır, güncellemede korunur.

* **Launchpad** (menünün ilk satırı, `#/launchpad`): istediğiniz kadar adlı launchpad, her biri bir sekme. Bir sayfadaki
  tablonun başlığında (fareyle üstüne gelince) **+ Launchpad** → hangi launchpad'e ya da *+ Yeni launchpad…*; **Ctrl+K**
  sonucunda da "Launchpad'e ekle" vardır (Ctrl+Enter). Sekmeler sürükleyerek ya da sağ tık / ⋯ menüsünden sıralanır, yeniden
  adlandırılır, silinir. **Dışa aktar** launchpad'i bir JSON dosyası olarak indirir; **İçe aktar…** böyle bir dosyayı (bir
  arkadaşınızınkini de) ekler - aynı adda bir launchpad'iniz varsa adına "(2)" eklenir. Launchpad'in kendi adresi vardır
  (`#/launchpad/<ad>`): geri / ileri ve yer imi onu bulur.
* **Kutular.** Her tablo bir kutudur: başlığındaki ⠿ ile sürükleyip bırakınca yeri değişir; **⋯** menüsünde genişlik (¼ ⅓
  ½ ⅔ tam - 12 sütunluk ızgarada), yükseklik (otomatik ya da sabit piksel: tablo kutunun içinde kaydırılır), **Satırlar ve
  sütunlar…** (tablonun bir kısmı: satır adıyla - satırın soldan ilk metni; ad tabloda tekrar ediyorsa satır numarasıyla -,
  sütun harfiyle; başlık satırları hep görünür; seçim sunucuda uygulanır), yeniden adlandırma, sola / sağa taşıma, yan
  panele sabitleme, ayrı pencere, tablonun sayfasına gitme ve kaldırma; ▾ kutuyu daraltır. Kutular **canlıdır ve
  düzenlenebilir**: aynı hücreler, aynı kitap, aynı kişisel / ortak kapsam - launchpad'de yazdığınız değer kaynak sayfanın
  değeridir. "Elle değer" launchpad'de de çalışır. Ekrandaki bütün kutular (launchpad, yan panel) hangi sayfalardan
  gelirse gelsin **tek istekle** güncellenir (`POST /api/panels`); her sayfa kendi sayfasının yolundan, yalnız istenen
  tablolarıyla ve yalnız değişenleriyle hesaplanır.
* **Kaybolan tablo.** Kutunun tablosu artık yoksa (güncellemeyle kaldırılmış bir sayfa ya da tablo) ya da sayfası yalnızca
  yöneticilere açıksa kutuda "**Bu tablo artık yok**" / "**Erişim yok**" yazar ve *Kaldır* düğmesi çıkar; launchpad'in geri
  kalanı çalışır.
* **Yan panel** (üst şeritteki ◨ ya da **Alt+Y**): sabitlediğiniz tablolar hangi sayfaya geçerseniz geçin sağda durur
  (tablonun "+ Launchpad" menüsünde *Yan panele sabitle*). Launchpad'inkiyle aynı canlı kutular; ⇔ paneli genişletir.
  Kapalıyken kutuları sorulmaz.
* **Ayrı pencere.** Tablonun başlığındaki **⧉**, ya da launchpad'in *Ayrı pencerede aç*ı, tabloyu / launchpad'i menüsüz bir
  pencerede açar (ikinci ekran için: `#/pop/<sayfa>/<tablo>`, `#/pop/launchpad/<ad>`). Pencere canlıdır ama **alarm
  denetlemez, masaüstü bildirimi göstermez** (bunlar ana pencerenin işi), canlı akışı diğer sekmelerle paylaşır ve her
  yenilemede tek istek yapar (tarayıcı bir sunucuya en fazla 6 bağlantı açar). Alarm bildirimleri artık etiketlidir: iki
  sekme açıkken aynı alarm tek bildirim olur.
* **Hızlı geçiş.** Son açılan **4 sayfa** (çalışma kitabı sayfaları ve launchpad) kapatılmaz, bekletilir: geri döndüğünüzde
  **sekmesi, araması ve kaydırması yerindedir**, sayılar o an güncellenir (güncellenene kadar soluk görünür). **Alt+←** /
  **Alt+→** önceki / sonraki sayfa. Sayfa başlığının yanındaki **☆** sayfayı üst şeritteki **favorilerinize** ekler (★ ile
  çıkar). **Ctrl+K** kutusu boşken son açılan sayfaları listeler; bir tablo sonucunda "Launchpad'e ekle" (Ctrl+Enter) ve "Yan
  panele sabitle" (Shift+Enter) vardır. Dashboard'un kendi sayfaları (Günlük İşlemler, Broker Chat, Quant …) eskisi gibi her
  açılışta yeniden kurulur.
* **Açılış sayfası** (sağ üstteki adınız → *Açılış sayfası…*, ya da launchpad'de *Açılış sayfası yap*): dashboard'u adres
  yazmadan açtığınızda gelen sayfa - bir sayfa ya da launchpad'lerinizden biri; boşsa Masa.
* **Sütun sırası.** Bir tablonun sütunlarını kendi sıranıza dizebilirsiniz: "Sütunlar" → **Sütun sırası…** (sürükleyin ya
  da ↑ ↓), ya da başlığa sağ tık → *Sütunu sola / sağa taşı*; **Excel sırasına dön** eski hâline getirir. Gizlediğiniz
  sütunlarla birlikte çalışır; sıra tablo nerede çizilirse (sayfa, launchpad, yan panel, ayrı pencere) orada geçerlidir.
  Hücreler kendi adresini korur: yazma, kopyala / yapıştır, alarm ve izleme değişmez; birleşik bir başlığın sütunları
  ayrılırsa başlık ilk sütununda kalır. Dashboard'un kendi tablolarında (Günlük İşlemler, Broker Chat, FX …) yalnız
  gizleme vardır (tıklamaları sütunun yerine bakar).
* **Sayfaların kendi kutuları.** Dashboard'un kendi sayfalarının bazı parçaları da launchpad'e, yan panele ve ayrı
  pencereye konur: o parçanın panel başlığında (fareyle üstüne gelince) tablolardaki gibi **+ Launchpad** (*Yan panele
  sabitle* onun menüsünde) ve **⧉** vardır. Yedi kutu, her biri ⋯ menüsünde sayfasının seçenekleriyle:
  - **Canlı sinyaller** (Quant › Sinyaller): aile ve varlık süzgeci (eklerken sayfadaki süzgeç gelir). Sinyale tıklayınca
    kartı **kutunun üstünde** açılır - Sinyaller sayfasındaki kartın aynısı: düz anlatım, seri ve bantlar, giriş / hedef /
    stop - ya da (seçenek) doğrudan **Sinyaller sayfasında**; kartın *Sinyaller sayfasında aç*ı da oraya götürür.
  - **VİOP emir seviyeleri** (Quant › VİOP): bir kontratın ya da **ön vadenin** (vadesi dolunca sonraki kontrata geçer;
    sayfada ön vade seçiliyken eklenirse o) bugünkü ve haftalık seviyeleri.
  - **VİOP kontratları** (Quant › VİOP): canlı ima faizlerle kontrat tablosu; satıra tıklayınca kontratın kartı.
  - **Broker Chat tahtası**: en iyi bid / ask, enstrüman başına; ürün (Tümü / OIS / XCCY / FX swap / DİBS), enstrümanlar
    (bugünkü tahtadan seçilir; hepsi seçiliyken sonradan gelenler de görünür) ve her broker'ın kendi kotası.
  - **İzleme listesi**: İzleme sayfasının bir listesi - izleme listesi, alarmlar ya da bugün çalanlar.
  - **TCMB WIRP** (Quant › TCMB WIRP): toplantı başına tablo, TCMB ya da Fed.
  - **Parite özeti** (Quant › FX): carry, beklenen kayma, tampon, karar.

  Her kutu sayfasının **hafif bir kısmını kendi isteğiyle** okur ve sayfasının satırlarını aynı fonksiyonlarla çizer (sütun
  gizleme sayfasıyla ortaktır). Kendi kendine güncellenir: quant kutuları **quant sonucunun sürümü değişince** (canlı
  akışın quant sayacı; ayrı pencerede de) - VİOP'un canlı kısmı da dakikalık canlı yenilemeyle yeni sürümle gelir, iki
  VİOP kutusu tek istek yapar -; tahta **Broker Chat değişince** (akış Broker Chat'in kendi değişiklik sayacını taşır:
  yazılan ya da silinen satır, sıfırlama, bayat sınırı, isim listesi - piyasanın her neslinde değil), ayrıca kotaların
  yaşı ve model için 20 saniyede bir, sayfası gibi; izleme listesi **her nesilde**. Kutular sayfanın element id'lerini
  kullanmaz: sayfası yanındayken de (yan panel) çakışma olmaz. Bu sürümün tanımadığı bir kutu (başka bir sürümün
  kaydettiği) yalnız kendini gösteremez, düzenin kalanı çalışır.
* **Quant menüsü.** On beş quant sayfası menüde **dört giriştir**, her biri sekmeli bir sayfa: **Sinyaller** (Sinyaller,
  Gün içi, Model), **Faiz** (PCA / RV, Çiftler, Korelasyon, Rejim, Eğri Adil Değeri, İma Patikası, TCMB WIRP,
  Öncü-Takipçi), **FX** (FX, Makro, Opsiyon) ve **VİOP**. Her sayfanın adresi aynı kalır (`#/quant-pca` Faiz'i "PCA / RV"
  sekmesinde açar; sinyallerin sayfa bağlantıları, Ctrl+K, favoriler ve yer imleri eskisi gibi çalışır); sekmeye tıklamak
  o sayfanın adresine gider (geri / ileri onu bulur). Bir girişe tıklayınca **son açtığınız sekme** açılır (bu tarayıcıda
  hatırlanır).
* **Kendi menünüz** (sağ üstteki adınız → **Menüyü düzenle…**): kullanmadığınız sayfaların işaretini kaldırın, menünüzden
  çıkar - bir quant girişi bütün sekmeleriyle. **Ctrl+K ve bağlantılar onları yine açar**; *Hepsini göster* hepsini geri
  getirir. Hesabınızla saklanır (`hidden_pages`): girdiğiniz her bilgisayarda aynı menü, başka bir pencerede değiştirince
  bu pencerede de. Yalnızca yöneticilere açık sayfalar (Sayfa gezgini, Kullanıcılar, Yedekleme) yine yalnız yöneticilerin
  menüsünde ve listesindedir; menüden çıkarmak hiçbir yetkiyi değiştirmez.

API: `POST /api/panels {items: [{view, panel, key?, rows?, cols?, all?, since?, as?}]}` (cevap `view/panel` anahtarlı:
tablonun kendisi, `unchanged` ya da `missing` + `status`), `GET` / `POST /api/layout` (`launchpads`, `drawer`, `favs`,
`landing`, `hidden_pages` - gönderilen bölüm değişir, diğerleri kalır), `GET /api/layout/export?name=…`,
`POST /api/layout/import`, `/api/columns`'ta `order`. Düzen doğrulanır ve sınırlıdır (24 launchpad, launchpad başına 60,
yan panelde 24 tablo, menüden 120 giriş, 256 KB); bir launchpad öğesi türünü söyler (`type: "table"`; sayfaların
kutuları `quant-signals` {family?, asset?, open?: card / page}, `viop-levels` {contract: front ya da ticker},
`viop-contracts`, `broker-board` {product?, keys?, brokers?}, `watch-list` {list?: items / alarms / fired}, `wirp`
{bank?: try / usd}, `fx-summary`), yeni öğe türleri `tto/layout.py`'deki `ITEM_TYPES`'a kendi denetimleriyle eklenir
(tarayıcıda `boxes.js`'teki `BOX_TYPES`'a kutusuyla; sayfaların kutuları `pagebox.js` / `pageboxes.js`). Kutuların
okuduğu kısımlar: `GET /api/quant/box?of=signals|viop|wirp|fxsum` (sinyaller `family` / `asset` ile; cevap sonucun
`version`'ını söyler), `GET /api/broker?part=board` (yalnız tahta; okunduğu andaki `changes` sayacıyla - canlı akış
`/api/events` aynı sayacı `broker` olarak taşır), `GET /api/watch?part=items|alarms|fired` (tek liste). Ayrı
penceredeki kutunun adresi `#/pop/box/<tür>?o={seçenekleri}`. `/api/nav` bir sayfanın menü girişini
söyler: `menu` (girişin id'si, `quant.faiz`), `menu_title`, `tab`.

#### Kişisel hesap tablosu

Launchpad'de **+ Hesap tablosu** kendi küçük Excel sayfanızı ekler: hücrelerine sayı, metin ya da dashboard'un canlı
hücrelerine bağlı formül yazarsınız (`=MASA!I60+25`) ve formül canlı kalır - Masa'daki spread değişince sonuç da değişir.
Hesap tablosu da bir kutudur (genişlik, yükseklik, ad, sürükleyerek yer, daraltma); **⋯** menüsünde *Yan panele sabitle*
(aynı tablo yan panelde de durur: birinde yazdığınız ötekinde görünür), *Ayrı pencerede aç* (`#/pop/calc/<kimlik>`), yan
panelden *Launchpad'e ekle…*. Hesabınızla sunucuda saklanır (`calc.<kullanıcı>`): girdiğiniz her bilgisayarda aynıdır,
yeniden başlatmada ve güncellemede kalır. Launchpad **dışa aktarılınca** hesap tablolarının hücreleri de dosyaya girer;
**içe aktaran** kişiye kendi kopyaları olur.

* **Excel alışkanlıkları.** Tıklayarak seçin (Shift+tık, sürükleme ya da Shift+ok: blok; satır / sütun başlığı: bütünü),
  **Enter**, **F2** ya da yazmaya başlamak düzenler; yazarken **Enter** aşağı, **Tab** sağa geçer, **Esc** vazgeçer; oklar
  gezinir, Ctrl+ok kenara gider. **Formül çubuğu** (fx) seçili hücrenin formülünü gösterir, oradan da yazılır. **Delete**
  temizler (sayı biçimi kalır). **Ctrl+C / Ctrl+V** Excel'le blok alışverişi (Ctrl+Shift+C tam hassasiyet); hesap
  tablosundan kopyalanan blok yapıştırılınca formüller Excel'deki gibi kayar (`=A1*2` bir alt satırda `=A2*2`, `$` olanlar
  kalır), **Ctrl+D / Ctrl+R** aşağı / sağa doldurur. Araç çubuğu: **Biçim** (genel, tam sayı, ondalık, binlik ayraçlı,
  yüzde, tarih), **%**, **000** (binlik ayracı), **+,0 / −,0** (ondalık artır / azalt), **+ Satır / + Sütun**; sütun
  başlığının kenarını sürükleyerek genişlik (çift tık: varsayılan). Başta 8 satır × 6 sütun, en fazla 50 × 12 (yapıştırınca
  ya da son satırda Enter'la büyür; ⋯ → *Boş son satır ve sütunları kaldır*).
* **Değerler.** Sayılar kullandığınız sayı biçimiyle yazılır ve gösterilir (`1.234,5` / `1,234.5`); `25%` yüzde, `15.12.2026`
  tarih olarak görünür; `'` ile başlayan metin olarak kalır; DOĞRU / YANLIŞ (TRUE / FALSE). Yazılan sayılar mavi,
  hesaplananlar düz renk (modellerdeki gibi); değişen sayılar tablolardaki gibi yanıp söner.
* **Formüller** dashboard'un kendi motorunun formülleridir: işlev adları İngilizce (SUM, IF, IFERROR, ROUND, VLOOKUP, INDEX
  / MATCH, SUMIFS, WORKDAY, EDATE, YEARFRAC, TEXT …), bağımsız değişkenler virgülle - Türkçe Excel alışkanlığıyla noktalı
  virgülle de (`=ROUND(1,25;1)`: o zaman ondalık ayırıcı virgüldür; TEXT'in biçim metni yine İngilizce yazılır: `"0.00"`).
  Motorun bilmediği işlev (XLOOKUP, OFFSET, INDIRECT …) `#NAME?` olur. Başvurular: tablonun kendi hücreleri (`A1`, `$B$2`,
  `A1:A5`); ana çalışma kitabının hücreleri sayfa adıyla (`=MASA!I60`, `='C & R'!B5`; büyük / küçük harf fark etmez) ve
  adlarıyla (`=SPOTDATE`); diğer kitaplar köşeli parantezle (`=[sofr]SOFR_FOMC!B9`, `=[asw]ASW!J3`, `='[borsa]bu'!B5`).
  Formül yazarken, başvurunun gelebileceği yerde (`=`, bir işlem, parantez ya da ayırıcıdan sonra) bir hücreye **tıklamak**
  adresini ekler, Excel'deki gibi: tablonun kendi hücresi (ok tuşları da) ya da bir sayfanın, yan panelin tablosundaki
  hücre - çalışma kitabındaki adresiyle (`MASA!I60`); hemen ardından başka hücreye tıklamak eklenen adresi değiştirir,
  **Ctrl+tık** formülün her yerinde ekler, başka yere tıklamak yazmayı bitirir. Sonuç, başvurduğu hücrenin sayı
  biçimini alır (`=Forward!D2` tarih, `=MASA!I60+25` spread gibi görünür); TODAY / DATE / EDATE / EOMONTH / WORKDAY tarih
  olarak görünür. Dizi sonucu taşmaz (ilk değeri görünür); bir hesap tablosu başka bir hesap tablosuna başvurmaz.
* **Hesap.** Sunucuda, hesap iş parçacığında, sizin hesabınızla: kendi girdileriniz ve "Elle değer"leriniz geçerlidir -
  sayfalarınızın gösterdiği değerler (başka kullanıcının girdisi sizinkini değiştirmez). Ekrandaki bütün hesap tabloları
  (launchpad, yan panel, ayrı pencere) her yenilemede **tek istekle** güncellenir; okuduğu hücrelerden hiçbiri değişmediyse
  yeniden hesaplanmaz (motorun bağımlılık maskeleri). Sınırlar: bir hesap en fazla 2 sn sürer ve 200.000 çalışma kitabı
  hücresi okur (bir aralık en fazla 100.000 hücre); bir isteğin tabloları en fazla 4 sn (hesap iş parçacığı herkesin:
  kalanlar bir sonraki istekte); formül en fazla 1.000 karakter ve 64 iç içe parantez; kullanıcı başına 30 hesap tablosu -
  hiçbir launchpad / yan panel öğesinin göstermediği tablo son değişikliğinden 7 gün sonra silinir.
* **Hatalar** hücre hücre, dashboard'un başka yerde gösterdiği Excel kodlarıyla: `#DIV/0!`, `#VALUE!`, `#N/A`, `#NAME?`
  (bilinmeyen işlev ya da ad - "Bilinmeyen işlev: XLOOKUP"), `#REF!` (böyle bir sayfa / kitap yok), `#CALC!` (döngüsel
  başvuru, süre ya da hücre sınırı) …; ne demek olduğu hücrenin ipucunda ve formül çubuğunun altında yazar. Okunamayan
  formül (eksik parantez …) yazılırken reddedilir, hücre aynı metinle yeniden açılır.
* **Bloomberg'e soran formül yok.** BDP, BDH, BDS, BFXFORWARD, BINTERPOL, RTGET ya da başka bir eklenti işlevi (`_xll.`)
  içeren formül yazılırken reddedilir ve nedeni söylenir (günlük veri limiti): değeri dashboard'daki hücresinden alın
  (`=MASA!I60`). Formüllerin okuduğu çalışma kitabı hücreleri sayfaların zaten hesapladığı hücrelerdir.
* **Yöneticilerin sayfası.** Yalnızca bir yönetici sayfasının gösterdiği sayfanın (Motor) hücreleri hesap tablosunda da
  yalnızca yöneticilere açıktır (diğerlerinde `#REF!` · "Motor sayfası yalnızca yöneticilere açık").

API: `POST /api/calc/eval {items: [{key, sheet, since?, rev?}]}` (cevap `key` anahtarlı: hesaplanmış tablo ya da
`unchanged`), `POST /api/calc/save {sheet, cells?, copy?, fmt?, widths?, rows?, cols?}` (değişikliğin hepsi ya da hiçbiri;
cevap tablonun hesaplanmış hâli). Launchpad / yan panel öğesi `{type: "calc", sheet: "<kimlik>"}` (`tto/calc.py`,
`tto/static/js/calc.js`).

### Masanın kendi köşesi: Hata / Öneri, Sosyal, Ajanda

Piyasadan bağımsız üç parça (`tto/desk.py`). Kayıtları veritabanındadır (`data/tto.db`): sunucu yeniden başlasa da kalır.
Bir mesaj, bildirim ya da ajanda değişikliği canlı akışla herkesin ekranına anında gider, ama tabloları yeniden
hesaplatmaz: akış bu üç parçanın kendi sayaçlarını taşır, sayfa yalnızca değişen parçayı yeniden ister. Kullanıcının
yazdığı her şey ekrana **düz metin** olarak gelir (içindeki HTML / betik çalışmaz); her istek giriş ister, başka bir
sayfadan gelen değişiklik isteği reddedilir.

**Hata / Öneri.** Sağ üstteki **Hata / Öneri** düğmesi herkese açıktır: tür (**Hata** / **Öneri**) ve metin (en fazla
2000 karakter); hangi sayfadan gönderildiği kendiliğinden eklenir.

* Açık bildirim varsa **yalnızca yöneticilerde** düğmenin köşesinde kırmızı **!** görünür; kullanıcı (bildirimi
  gönderen dahil) rozeti hiç görmez. Yönetici düğmeye basınca listeyi açar: tür, yazan, zaman, sayfa (tıklayınca o
  sayfa açılır) ve metin.
* **İlgilenildi** kaydı rozetten düşürür; kayıt altta **İlgilenilenler** geçmişine gider (kim, ne zaman; son 100).
  Yanlışlıkla kapatılan **Yeniden aç** ile döner. Yönetici listeden kendisi de "Yeni bildirim yaz"abilir.
* Listeyi görmek ve İlgilenildi işaretlemek sunucuda yöneticiye özeldir (`/api/feedback` başkasına 403 verir).
  Bir kullanıcı 10 dakikada en fazla 10 bildirim gönderebilir. Canlı akışta bildirimlerin sayacı da yalnızca
  yöneticiye gider: kullanıcı bir bildirimin geldiğini ya da kapatıldığını hiçbir yoldan öğrenmez.

**Sosyal.** Menünün Masa grubunda: masanın sohbeti. Giriş yapmış herkes yazar ve görür; mesajlar isim ve saatle, gün
ayraçlarıyla (Bugün / Dün / tarih) durur, aynı kişinin 5 dakika içindeki mesajları tek isim altında toplanır.

* **Enter** gönderir, **Shift+Enter** alt satıra geçer (en fazla 1000 karakter, 30 satır). Başkasının yazdığı anında
  gelir; sohbetin yukarısındayken "Yeni mesaj ↓" çıkar.
* Sosyal açık değilken menüde **okunmamış mesaj sayısı** görünür (başkalarının, o tarayıcıda okunandan sonraki
  mesajları).
* Mesajlar **süresiz saklanır**: sayfa son 200 mesajla açılır, öncekiler "Daha eski mesajlar" ile gelir. Herkes
  **kendi mesajını** silebilir (herkesin ekranından gider), başkasınınkini silemez. Dakikada en fazla 20 mesaj (silinen
  mesaj sayıdan düşmez).

**Ajanda.** Menünün Masa grubunda: unutulmaması gereken işler.

* **Gün** (ya da **Bugün** düğmesi; geriye en fazla 30 gün), isteğe bağlı **saat**, **iş** (en fazla 300 karakter), **Deadline** işareti ve
  kimin için olduğu: **Masa** (herkes görür ve tamamlayabilir; silmek ekleyenin ya da bir yöneticinin işidir) ya da
  **Kişisel** (yalnızca siz görürsünüz; başkası ona ulaşamaz).
* Liste: önce **gecikmiş deadline'lar** (kırmızı: günü ya da bugünkü saati geçmiş, tamamlanmamış - ne kadar eski
  olursa olsun; bugünkü saati geçmiş tekrarlayan işler de), sonra **bugün**, sonra ileriki günler (Yarın …); geçmiş
  günler (son 30 gün) katlı durur. Saati olmayan iş gününün başındadır. Tamamlanan iş üstü çizili kalır, kimin ne
  zaman tamamladığı yazar; geri alınabilir.
* **Uyarılar** - hangi sayfada olursanız olun ekranın sağ altında, her tarayıcıda bir kez (tıklayınca Ajanda açılır):
  saatli deadline'da **15 dakika önce** ve **saatinde**, saatsiz deadline'da **bir gün önce** ve **o gün**; saatli
  her işte saatinde hatırlatma. Menüde Ajanda'nın yanında bugünkü işlerin (tekrarlayanların bugünkü günü dahil) ve
  gecikenlerin sayısı; gecikmiş varsa rozet kırmızıdır. 10 dakikada en fazla 60 iş eklenebilir; sayfa en yakın 1000 işi
  ve en yeni 200 gecikmiş deadline'ı gösterir.
* **Tekrarlayan işler** - formdaki **Tekrar**: *Bir kez* (varsayılan: tek günlük iş, yukarıdaki gibi), *Her gün*, *Her iş
  günü* (hafta sonunu ve **Ayarlar → Tatiller**'deki TRY tatillerini atlar: dashboard'un kendi takvimi, çalışma
  kitabının WORKDAY'inin okuduğu liste; liste değişince günler hemen yeniden hesaplanır), *Seçili günler* (Pzt … Paz
  kutuları; seçilen gün tatil olsa da sayılır) ya da *Ayın son iş günü* (ayın son günü hafta sonu ya da tatilse ondan
  önceki ilk iş günü). Tekrarlayan işin **saati zorunludur** (o saatte uyarır); gün alanı **başlangıç günüdür** (bugün
  ya da önceyse bugünden başlar; Tekrar'ın yanında yazar), isteğe bağlı bir **bitiş** günü verilebilir. Masa / Kişisel
  ve Deadline tek seferlik işteki gibidir.
* **Her gün kendi başınadır:** bugünün tekrarı günün işleri arasında "↻ Her iş günü" gibi bir etiketle görünür ve
  yalnızca o gün için tamamlanır (kim, ne zaman; geri alınabilir; ertesi gün yeniden gelir). Saati geçen ve
  tamamlanmayan gün gecikmiş sayılır: deadline'sa tamamlanana kadar (geriye 30 güne kadar), değilse o gün boyunca. İş
  eklendiğinde - saati, tekrarı ya da deadline'ı değiştiğinde, duraklatıldıktan sonra devam ettiğinde - o andan
  sonrası sayılır: öncesi "kaçırılmış" olmaz.
* **Tekrarlayan işler** bölümü bunları listeler: nasıl tekrarladığı, saati, başlangıç / bitişi, **sonraki** zamanı,
  ekleyen. **Düzenle** (tekrar, günler, saat, iş, deadline, başlangıç / bitiş; kimin için olduğu sonradan değişmez -
  değiştirmek için silip yeniden ekleyin), **Duraklat / Devam et** (duraklatılan işin günü olmaz, uyarmaz) ve **Sil**
  (tamamlanma kayıtlarıyla birlikte) masa işinde ekleyenin ya da bir yöneticinin, kişisel işte sahibinin işidir; masa
  işinin gününü herkes tamamlayabilir.
* **Alarmlar** - ajanda açık olmasa da, hangi sayfada olursanız olun: deadline'da **15 dakika önce**, her işte
  **saatinde**; dashboard kapalıyken saati geçen gün, o gün açılınca **gecikmiş** olarak uyarır (deadline'sa
  tamamlanana kadar listede gecikmiş kalır). Uyarıda **Ertele 10 dk** (yalnızca sizin için: 10 dakika sonra yeniden;
  başkalarına uyarı sürer) ve **Bugün tamam** (yalnızca o günün tekrarı) vardır; uyarı yanıtlanana, gün başka yerde
  tamamlanana ya da ertelenene kadar ekranda kalır, kısa bir ses ve tarayıcı bildirimi de çıkar. Her uyarı **her
  tarayıcıda bir kez** gösterilir: aynı tarayıcının iki penceresinden yalnızca biri gösterir. Neyin ne zaman söyleneceğine
  sunucu karar verir (`/api/desk`'te `alarms` ve bir sonraki değişime kalan saniye `next`); sayfa o anda yeniden sorar.
* Sınırlar: kullanıcı başına en fazla 100 tekrarlayan iş, 300 karakter; ekleme ve düzenleme ajandanın hız sınırına
  (10 dakikada 60) sayılır. Kayıtlar kendi tablolarındadır (`agenda_rules`, `agenda_rule_days`: günlerin tamamlanması,
  `agenda_snoozes`: ertelemeler); var olan bir veritabanı açılışta bu tabloları kendisi ekler, eski kayıtlara dokunulmaz.
  API: `POST /api/agenda/rules`, `POST` / `DELETE /api/agenda/rules/<id>`, `POST /api/agenda/rules/<id>/done`
  (`{day, done}`), `…/snooze` (`{day}`), `…/pause` (`{paused}`); kurallar `GET /api/agenda`'nın `rules`'ındadır.

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
  "TRY faizleri vadelere göre" tablosundan (USDTRY spot valörü + vade, TRY ve USD tatilleriyle), spot Forward
  fiyatları tablosunun spotu (üzerine yazılan spot o kişinin forward'ını değiştirir). Aynı tarihte Serbest forward
  listesindeki "Offshore" forward'ıyla birebir aynıdır (testle doğrulanır).
* **EURTRY** (TRY çaprazları): USD bacaklarının çarpımı, `F = F(EURUSD)·F(USDTRY)` – TRY tarafı yine offshore eğrisi.
  EURTRY'nin tarihleri kendi spot valöründen (TRY ve EUR'nun ortak iki iş günü) TRY ve EUR tatilleriyle; diğer TRY
  çaprazları USDTRY'nin tarihlerini alır.
* **Diğerleri**: Bloomberg spotu + forward puanı / 10^`FWD_SCALE` (`EUR1M Curncy`, `JPY1M Curncy`, çaprazlarda
  `EURJPY1M Curncy`); teslim tarihi spot valörü (iki iş günü) + vade, hafta sonu atlanarak - EURUSD'de USD ve EUR
  tatilleri de atlanır (aşağıda, Ayarlar · Tatiller).
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
  25D BF 1M, 10D RR 1M, **1M ATM ±1σ** (yalnız ATM vol'le, simetrik), **1M ↑1σ / ↓1σ** (skew dahil; ikisi de
  aşağıda) ve günlük başabaş hareket (spot × ATM 1M / √252). Satıra tıklayınca parite açılır (USDTRY
  varsayılan; seçim hatırlanır); bir vol hücresine tıklamak o vadeyi "Vade geçmişi"nde de açar.
* **Vol yüzeyi**: vade, teslim tarihi, gün, forward, beş kota, smile'ın kendi 10P / 25P / 25C / 10C vol'leri (üzerine
  gelince strike), **ATM ±1σ**, **↑1σ / ↓1σ**, dağılımın %5 / medyan / %95'i ve **en olası** seviyesi (aşağıda; en dar
  %50 / %80 aralık üzerine gelince), **Uyum** (modelin kotalardan en büyük sapması, vol
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
  doğrusal. **Yüzdelik / En olası**: "En olası"da bantlar aynı kütlenin en dar aralıklarıdır (%98 / %90 / %80 / %50),
  orta çizgi medyan yerine tepedir (aşağıda). Ufuk 3A / 6A / 1Y / 2Y. Dikey eksen çizilene oturur (geçmiş, forward,
  orta çizgi ve açık bantlar); matrisin bu aralığa düşen seviyeleri noktalı çizgi ("Seviyeler" ile açılıp kapanır).
  Üzerine gelince o tarihteki forward, orta çizgi ve bantlar.
* **Olasılık matrisi**: satır vade, sütun fiyat seviyesi; **Üstünde** (vade sonunda seviyenin üstünde olma
  olasılığı), **Altında** ya da **Aralıkta** (iki seviye arası; uçlarda "<" ve "≥"; her vadenin en olası aralığı – iki
  seviye arasındakiler içinde – kalın). Seviyeler yazılır (`50 52,5 55`; paritesi için hatırlanır) ya da otomatik gelir
  (1Y dağılımının %5–%95 aralığında yuvarlak adımlar). Kopyalanır.
* **Smile ve yoğunluk**: seçilen vadenin smile'ı (vol – strike, pillar'larıyla) ve vade sonundaki spotun yoğunluğu
  (forward, spot ve tepe çizgileriyle; başlıkta en olası seviye ve en dar %50 aralık).

**En olası (tepe ve en dar aralıklar).** Piyasanın fiyatladığı (risk-nötr) dağılımda spotun vade sonunda en olası
olduğu yerler. **Tepe**, yoğunluğun zirvesidir: tek en olası seviye. **En dar %50 aralık**, olasılığın yarısını taşıyan
en dar aralıktır; iki ucunda yoğunluk aynıdır ve içindeki her seviye dışındakilerden daha olasıdır (%80, %90, %98
aynı biçimde). Yüzdelik bantlar iki kuyruğa eşit pay bıraktığından medyanın çevresine oturur; bunlar tepeye doğru kayar.
Dağılımın ortalaması arbitraj gereği forward'dır: **USDTRY**'de uzun sağ kuyruk ortalamayı yukarı çektiğinden tepe ve
en olası aralıklar forward'ın **altında** kalır; put skew'lü bir G10 paritesinde (EURUSD) tepe lognormal yasanınkinin
üstündedir (kısa vadelerde forward'ın da). Hesap, CDF'nin ln K'da 800 noktalık ızgarasından yapılır: tepe, yoğunluğun en
yüksek dilimi ile komşularından geçen parabolün tepe noktası; aralıklar, yoğunluğun seviye kümeleri (seviyeye göre ikiye
bölme). Lognormal yasada kapalı formülle aynıdır (F·e^(−3σ²T/2); testle doğrulanır). Smile'ın kotaları değişmedikçe
yeniden hesaplanmaz: şekil K/F'te aynı kaldığından spot oynayınca yalnız ölçeklenir.

**↑1σ / ↓1σ (skew dahil) ve ATM ±1σ.** ↑1σ / ↓1σ, vade sonundaki spotun dağılımının **%84 yüzdeliği − forward**
ve **forward − %16 yüzdeliği**: normal dağılımda bir standart sapmaya denk gelen olasılıklar, smile'ın çarpıklığıyla
birlikte. Smile yoksa lognormal yasanın bir sigması çıkar (testle doğrulanır). **ATM ±1σ** yalnız ATM vol'le hesaplanan
simetrik harekettir: **forward × ATM × √T**, ↑1σ / ↓1σ ile aynı forward ve aynı gün sayısıyla, böylece yan yana
karşılaştırılır (smile kurulamasa da yazar). Dağılımın ortalaması forward'dır: **USDTRY**'de uzun bir sağ kuyruk (büyük
yukarı sıçrama olasılığı) ortalamayı gövdenin üstüne çeker; ↑1σ küçülür – eksi bile olabilir, yani %84 yüzdelik
forward'ın altındadır – ve ↓1σ büyür (USDTRY'nin kısa vadelerinde ↑1σ sıfıra yakın çıkabilir; ikisinin toplamı da ATM
±1σ'nın iki katından belirgin dar). Kuyruğun kendisi %95 / %99 yüzdeliklerinde görünür. EURUSD gibi bir G10 paritesinde
ikisi de ATM ±1σ'ya yakındır.

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
  skew (1M / 3M / 1Y) ve BF'nin bir yıllık serileri, ima ve gerçekleşen vol. Vade yapısında kotası olmayan vade atlanır,
  çizgi komşu vadeleri birleştirir. Parite ilk açıldığında bütün yüzeyin kotaları (izleme setinin dışındakiler de)
  istenir; gelene kadar sayfa birkaç saniyede bir yenilenir ("Kota bekleniyor"). Smile'ın kendi delta strike'larındaki
  vol'ler forward'a bağlı değildir (smile'ın bütün koşulları K/F'te): forward gelmeden de çizilir; çizilemiyorsa hangi
  kotanın beklendiği ya da olmadığı yazar.
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
`EK_DIBS`, `EK_EVREN`, `EK_CARRY`, `EK_IHALE`, `EK_TATIL`, `EK_VFRA`; ASW kitabına `EK_FX`; Bulk Bond sayfasına 7–52. satırlar; Motor ve Carry & Roll'da carry patikası ve gün sayısı formülleri; Forward ve Masa'da FX valörleri; VİOP Target'a FRA eğrisi).
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

**Forward kotasyon matrisi — OIS + spread, bid ve ask ayrı** (Forward sayfası → **Kotasyon**; Masa'nın "Forward
fiyatlama" sekmesinde USDTRY ve EURTRY özeti: her spread'in **yanında verdiği TRY faizi** - Spread bid · TRY bid % · Spread ask ·
TRY ask % -, sonra spot, puan ve forward; spread'ler oradan da yazılır). Vadeler 1M / 2M / 3M / 6M / 9M / 12M (valör formülle gelir, üzerine yazılabilir)
ve dört serbest tarih. "Tümü" satırına bid ve ask için **ayrı** OIS spread'i (bp) yazılır; bir vadenin kendi spread'i
o satıra yazılır (silince genele döner). Her satırda: valör, gün, spot bid / ask, **puan bid / ask**, forward bid / ask,
OIS %, TRY bid / ask %, USD %, günlük puan, RET bid / ask % ve aynı valörde RET'le çıkan puana fark.
OIS eğrisi listeden seçilir (MPC ima, S1–S3, Ağırlıklı, Bootstrap, TLREF sabit; seçilen S1–S3'ün hangi senaryo
olduğu – Baz / Hawkish / Dovish ve olasılığı – yanında ve tablonun altında yazar) ve Masa'daki "Tarih arası faiz"
bloğunun iskonto faktörleriyle aynıdır: aynı tarih ve spread'de iki blok aynı TRY faizini verir.
`Fwd bid = spot bid·(1+TRY bid·g/360)/(1+USD·g/360)`, ask tarafı spot ask ve TRY ask ile.
Altındaki **Puan → OIS spread** tablosu tersini yapar: elle verdiğiniz bid / ask puanının ima ettiği TRY faizini ve
OIS'e göre kaç bp olduğunu gösterir.

**Tek OIS spread'i.** Masanın OIS spread varsayımı bir kez yazılır: Masa'daki tarih arası faizin spread'i
(`MASA!I60`, −150 bp). Matrisin genel spread'i, Forward'daki "TRY OIS w/Spread" spread'i (`P58`, % puan: −1,5), OIS
ortasının valör kaydırması (`O27`, −%1,5) ve OIS sayfasındaki tarih arası faizin spread'i (`OIS_MAIN!F122`, −%1,5) ondan
çevrilir (eskiden dört ayrı yere yazılıyordu). Her biri ayrıca kendi değeriyle üzerine yazılabilir; silince yine
`I60`'tan gelir.

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

**Boş başlayan girdiler: PPK ima adımları, VİOP Target ve manuel spot.** Dosyanın kaydedildiği günün seçimleri bugün
kimsenin seçimi değil: OIS · PPK → *PPK ima* sekmesindeki toplantı başına senaryo adımları (S1 / S2 / S3, `OIS_MAIN!U10:W89`)
ve VİOP'taki **Target** tablosu (Yakın, Uzak, Yön, Hedef tipi, Hedef değer; `VIOP!L331:P338`, Masa sayfasında da
görünür) her kullanıcıya **boş** gelir. Boş adımda sayfanın kendi kuralı geçerlidir: senaryo tabanı (`B3`: ima yol ya
da sıfır) ve kaydırma (`D3`). Kullanıcının yazdığı değerler kendisinin kalır. Takvim değişikliklerinin eskiden ortak
girdi olarak taşıdığı dosya adımları bu sürümün ilk açılışında bir kez temizlenir.

**Hesaplayıcıların kayıt günü değerleri de boş gelir:** OIS · Nakit Akışı'ndaki kayıtlı işlem (`TM_OIS!A10:C12`), Forward'daki gün
sayacı (`E20`, `E22`), müşteri altın forward'ının tarihleri ve swap'ı (`C59`, `C60`, `C63`, `E61`, `E67`), tahvil carry
hesaplayıcısı (`V56:V62`), OIS · PPK'daki iki tarih arası faizin tarihleri (`OIS_MAIN!B122:B123`), VİOP'taki üç Interest
2 SP hesaplayıcısının TRY faizi (`M37`, `P37`, `S37`), DİBS RV'deki kayıtlı switch (`A64:C64`), Eurobond Kotaları'ndaki
kendi ask'larımız (`Bulk Bond!D3:D5`) ve USD · FOMC'taki toplantı başına senaryo adımları (`SOFR_FOMC!R74:T83`; boş adım
patikayı oynatmaz). **Piyasadan başlayanlar:** Hesaplayıcılar sayfasının üst bandı (`Calculators!AA3:AA10`: ilk dört
hesaplayıcının okuduğu başlangıç / bitiş tarihi ve spot, yanındaki swap puanının okuduğu forward) artık 03.11.2026'nın
değerlerini değil piyasayı gösterir - başlangıç USDTRY spot valörü, bitiş Forward sayfasının valör tarihi (`D2`), spot
`Forward!F2`, forward bitiş tarihine offshore (ICAP) TRY ve USD OIS eğrisiyle; Forward'daki müşteri altın forward'ının
spotları (XAUUSD: EK_XAU'nun kullandığı spot, USDTRY: `F2`) ve müşteri forward tarihinin USD / TRY faizleri (tarih
yazılınca) de öyle. Forward sayfasının kendi hesaplayıcıları gibi: üzerine yazılan kişinindir, `Delete` piyasaya döndürür.

**Manuel USDTRY spotu** (`VIOP!AA9:AA10`, "Manuel SP", masanın ortak girdisi) da boş gelir: dosya 49,997 / 49,9975 ile
kaydedilmişti ve bu değerler her sayfada herkes için Bloomberg spotunun yerine geçiyordu (`VIOP!L99` =
`IF(N(AA9)>0,AA9,BDP(…))`). Boşken spot Bloomberg'dendir (üst şeritte *Spot kaynağı: BBG*). Masanın daha önce sakladığı
bir manuel spot, **yalnızca dosyanın değeriyse** (bir kopya) bu sürümün ilk açılışında bir kez silinir; masanın yazdığı
farklı bir değer yerinde kalır. Sonradan boş başlatılan her hücre için aynı kural geçerlidir (hangi hücrelerin
temizlendiği `migrated.file_copies` kaydında tutulur, her hücre bir kez).

Target'ın **Yakın** ve **Uzak** kontratı, kontrat satırındaki listeden (`VIOP!L97:X97`: `Spot`, `30.11.2026`, …)
seçilir ve formüller o metni arar. Uzak kontrat başka biçimde yazılsa da (`30.11.26`, `30/11/2026`) listedeki aynı günün
maddesi olarak saklanır. Eskiden tarih sayısı (`46356`) olarak saklanıyor, hiçbir şeyle eşleşmiyor ve satır boş
kalıyordu. Aralıktan okunan her açılır liste kayıtta da aynı biçimde okunur.

**VİOP Target — FRA eğrisi** (VİOP → Kontratlar → Target; `VIOP!Z331:Z338`, yardımcı sayfa `EK_VFRA`). FRA+bp hedefinin OIS
FRA'sı tek eğriden geliyordu: sayfanın 104. satırı, yani piyasa OIS eğrisinin bootstrap'ı (`Motor`'un `BOOT_LNDF`'i, günde
doğrusal). Artık her satır FRA'nın eğrisini **Hedef tipi**'nin hemen yanındaki **FRA eğrisi** listesinden seçer:

* **Bootstrap (piyasa)** — varsayılan, bugünkü hesap (satırın iki kontratı yazılıp hedef tipi FRA olunca hücrede görünür;
  `Delete` buna döndürür). Dosyanın Target satırları ve kullanıcıların yazdıkları bu seçimle önceki sayılarını birebir verir.
* **S1 · Baz**, **S2 · Hawkish**, **S3 · Dovish** — OIS · PPK'daki üç senaryo; adları SENARYOLAR tablosundan
  (`OIS_MAIN!P3:P5`, kullanıcının kendi adları) gelir, orada değişince listede de değişir. Senaryonun eğrisi Masa'nın "Tarih
  arası faiz" bloğunun iskonto faktörüdür (`MASA!I63:I65`: Motor'un PPK patikası, toplantı başına adımlar *PPK ima*
  sekmesinde), satırın yakın ve uzak kontrat tarihinde: FRA = (DF yakın / DF uzak − 1) · 360 / gün. Aynı tarihlerle Masa
  bloğu aynı faizi verir.

Seçim **FRA+bp** satırında geçerlidir (çalışma kitabının formülü hedef tipi boş satırı da FRA+bp sayar): OIS FRA seçilen
eğriden, **Hedef faiz** = OIS FRA + hedef değer (bp), ondan da **Uzak limit fiyatı**, **Spread fiyatı** ve **Hedef − piyasa**
(Near limit yakın bacağın fiyatıdır, değişmez). **FXswap+bp** ve **Faiz %** satırlarında seçim etkisizdir (OIS FRA Bootstrap
kalır, seçimin ipucu bunu söyler). OIS FRA sütununun başlığı eğriyi yazar (`OIS FRA · S2 · Hawkish`; satırlar farklı
eğrideyse `OIS FRA · eğri satıra göre`); OIS FRA, Hedef faiz ve FRA eğrisi hücrelerinin üzerine gelince ipucu satırın eğrisini
(senaryo seçilmişse yanında Bootstrap'ın değerini) söyler. Masa'daki TARGET özeti senaryodan fiyatlanan satırın hedefinin
yanına eğrinin adını yazar (`FRA+bp -150 · S2 · Hawkish`), üstündeki girdi şeridinde FRA eğrisi de vardır; launchpad'deki
Target kutuları aynı tablodur.

Seçim satırın diğer girdileri gibi **kişiseldir**: girdilerle saklanır (sayfa yeniden açılınca durur, kayıtlı senaryoyla
gidip gelir), "Girdilerimi sıfırla" Bootstrap'a döndürür; liste dışı bir değer ve formül yazılamaz. Seçim senaryonun koduyla
(S1 / S2 / S3) okunur: senaryonun adı sonradan değişse de seçim aynı senaryodur (hücre, Excel listesi gibi, seçildiği adı
gösterir; ipucu yeni adı söyler). PPK takvimi değişince adımlar toplantılarıyla taşınır, satır o senaryonun yeni haliyle
fiyatlanır. VİOP kontratları dönünce satır kontratlarını tarihleriyle tutar: listede kalan kontrat aynı kontrattır; vadesi
geçen kontratın satırı hesaplanmaz, ipuçları ve Masa özeti "geçersiz" der. Uzak kontratın vade gününde dönem OIS spot
valöründen sonra bitmiyorsa (sayfanın kendi FRA'sı orada 0'dır) aynı uyarı çıkar. Yardımcı tablo (`EK_VFRA`: liste, her
satırın tarihleri, S1–S3 iskonto faktörleri, dört eğrinin FRA'sı ve durumu) "Yardımcı tablolar"dadır.

**VİOP kontratları masanın ortak girdisi ve kendiliğinden döner:** VİOP sayfasındaki vadeli ticker'ları, yani USDTRY
1–12 (`VIOP!L1:W1`, `A1X6 Curncy` …), altın-TRY (`M45:O45`, `XLZ6 Comdty` …, çift aylar) ve altın-USD (`M60:O60`,
`XLTZ6 Comdty` …) bugünün tarihinden kurulur (ay harfleri `FGHJKMNQUVXZ`, yılın son hanesi): bir kontrat vade gününe
kadar (o gün dahil) işlem görür, ertesi gün sıradaki en yakın kontrattır. Vade günü ayın son iş günüdür (`Motor`'un
tatil listesiyle); o gün yarım günse (29 Ekim'in ya da bir bayramın arifesi) bir önceki iş günüdür - çalışma kitabının
kontrat tarihleri böyledir: 30.11.2026, 31.12.2026, … ve 27.10.2027 (28.10.2027 arifedir). Masanın elle yazdığı ticker
yine geçerlidir ve herkeste değişir; hücreyi silmek (`Delete`) kendiliğinden dönen koda geri getirir. Daha önce saklanmış,
dosyadakiyle aynı ticker'lar bu sürümün ilk açılışında bir kez silinir (yoksa dönmeyi durdururlardı); farklı bir değer
kalır. Bunlar kişiselken birinin kaydettiği değer, o kişide ortak değeri gizlememesi için ilk açılışta atılır.

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
  **OIS ve offshore mid'e göre spread'ler.** İki tablonun sağında altı sütun (dashboard'un kendi sütunları,
  `tto/borsaspread.py`; TTO kitabının eğrilerinden, tablo her yapıldığında yeniden – satır başına hiçbir şey
  saklanmaz): **OIS mid zero %** ve **Offshore mid zero %** – satırın başlangıcından (T+0'da bugün, T+1'de ertesi iş
  günü: Valör − VKGS) Valör'üne eğrinin iskonto faktörlerinden zero faiz, basit ACT/360 (BID % / ASK % ile aynı gün
  sayımı) – ve **BID − OIS mid**, **ASK − OIS mid**, **BID − Off mid**, **ASK − Off mid** (bp: swap'ın kendi bid /
  ask'ı eğrinin mid'iyle, + ise swap mid'in üstünde; tek taraflı kotada yalnız o tarafın spread'i). OIS = bootstrap
  TLREF OIS mid eğrisi (`BOOT_GUN` / `BOOT_LNDF`, OIS_MAIN'in par kotalarından: her vadenin ilk fiyat veren
  kaynağındaki MID, MID yoksa PX_LAST), Masa'nın 'Tarih arası faiz' Bootstrap satırıyla ve OIS_MAIN'in 'İki tarih
  arası' bloğuyla aynı hesap (ln DF günle doğrusal); düğümlerde ORANLAR'ın "OIS zero"suyla aynı (1A, 2A, 3A …).
  Eğrinin spot'tan sonraki ilk düğümü 1A'dır: daha kısa satırlar spot → 1A arasından okunur (ORANLAR'ın 1W / 2W "OIS
  zero"su 1W / 2W kotalarının kendisidir, eğride yoktur). Offshore = Forward'daki offshore TRY iskonto eğrisi
  (`OFF_GUN` / `OFF_LNDF`: 9A'ya kadar FX swap ima faizlerinin bid–ask ortası, 1Y'den XCCY ortalarının bootstrap'ı;
  günler USDTRY spot'undan) – Masa'nın kırık vade bloğu ve DİBS RV'nin FX swap ASW'siyle aynı eğri. Eğrinin spot'undan
  önceki günler (T+0: bir gün, hafta sonunda üç) eğrinin kendi O/N'uyla basit taşınır – ORANLAR'ın ON satırı: OIS'te
  TLREF (365 → 360), offshore'da offshore O/N mid; hücrenin ipucunda tarihler ve bu taşıma yazar. Eğriler sayfayı
  açanın TTO hesabındandır: kendi girdisi (ör. elle yazdığı bir OIS kotası) yalnız onun sayfasına yansır. Yeni
  Bloomberg isteği yoktur.
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
  Bloomberg'in günlük veri limiti için: bir serinin **tüm aralığı günde en çok bir kez** istenir; Bloomberg'in geçmişi
  pencereden kısaysa (yeni bir kâğıt, kısa geçmişli bir ticker) verdiği en eski gün saklanır ve o aralık bir daha
  istenmez (yalnızca pencere büyürse). Sonraki turlar her serinin **yalnızca son kapanışından sonrasını** ister (o
  kapanışı ve bir önceki günü de yeniden: gün içinde saklanan değer kesinleşsin, düzeltme gelsin); dashboard kapalı
  kalmışsa da aynı, son kapanıştan. Hiç geçmişi olmayan bir seri günde bir kez sorulur ("Şimdi güncelle" yeniden
  sorar).
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
  `YLD_YTM_MID`; floater'larda - TLREF ve FRN - fiyat) ve değişimi, yanında Excel'in kendi hesabı olan BIST bileşik
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

**Ayarlar · Tatiller: TRY, USD ve EUR.** Üç ayrı liste, her biri kendi sekmesinde (TRY · USD · EUR), aynı şekilde
düzenlenir: her satıra bir gün, `gg.aa.yyyy` ve isterseniz adı (Excel'den iki sütun yapıştırılabilir); **Kaydet** açık
sekmenin listesini yazar - herkes için (her kullanıcı düzenleyebilir), tarih sırasıyla. Kaydedilmemiş yazı başka sekmeye
geçince kaybolmaz (sekmesinde • işareti); **Vazgeç** yalnız açık listeyi geri alır. Dosyanın (ya da varsayılanın) kendi
değerine dönen satırda saklanan değer silinir.

* **TRY** iki kitapta tutulur: TRY kitabında `Motor!A361:B523` (tarih ve adı; bütün WORKDAY hesapları - para piyasası,
  tahvil, VİOP, OIS, kontrat vadeleri - bunu okur) ve DİBS ASW kitabında `ASW!LR2:LR200` (yalnız tarihler). Sekme ikisini
  tek liste olarak gösterir (birleşimi, adlar TRY kitabından), Kaydet ikisine birden yazar; en çok 163 gün.
* **USD**: New York'ta FX takası olmayan günler - Fed tatilleri (Yılbaşı, Martin Luther King Day, Presidents' Day,
  Memorial Day, Juneteenth, Independence Day, Labor Day, Columbus Day, Veterans Day, Thanksgiving, Noel). Pazara denk
  gelen tatilde pazartesi kapalıdır, cumartesiye denk gelende cuma açıktır (04.07.2026 cumartesi: 03.07 iş günü); Good
  Friday USD için iş günüdür. ABD tahvil piyasasının SIFMA listesi değildir.
* **EUR**: TARGET2'nin kapalı olduğu günler - 1 Ocak, Good Friday, Easter Monday, 1 Mayıs, 25 ve 26 Aralık.

USD ve EUR dashboard'un kendi `EK_TATIL` sayfasındadır (TRY kitabı; kendi sayfası yok, sayfa gezgininde görünür):
kurallarından **2020–2040** için üretilmiş günlerle başlar (hafta sonuna düşenler yok; aralık sabittir, satırlar bugünle
kaymaz), en çok 260 gün. SIFMA tatilleri (`SOFR_FOMC!BO4:BO70`; SOFR / USD OIS sayfaları onu kullanmaya devam eder) ve FOMC
toplantıları (`B74:B83`) yanında, salt okunur (USD · FOMC sayfasında düzenlenir). Uç: `GET / POST /api/holidays` -
`{"ccy": "USD", "items": [{"date", "name"}]}`; `ccy` yoksa TRY (eski çağrılar aynı çalışır). Cevapta her liste
`lists.TRY` / `USD` / `EUR` altında, TRY eskisi gibi `tr` olarak da.

**FX valörleri iki para biriminin tatilleriyle.** Bir paritenin valörü, iki para biriminden birinin tatiline düşemez:

* **USDTRY spot** (`Forward!I2`): bugünden sonra hem TRY hem USD iş günü olan ilk gün, `WORKDAY(TODAY(),1,TRY+USD)`.
  24.11.2026'da işlem → 25.11; 25.11'de → 26.11 Thanksgiving (TRY iş günü, USD takası yok) → **27.11**; 28.10'da →
  29.10 Cumhuriyet Bayramı → 30.10; 02.04.2026'da → 03.04 (Good Friday: USDTRY takas olur).
* **EURTRY spot** (`Forward!K2`): TRY ve EUR'nun ikisinin de iş günü olduğu iki gün sonrası, `WORKDAY(TODAY(),2,TRY+EUR)`.
  01.04.2026'da işlem → Good Friday ve Easter Monday → **07.04**; ABD tatilleri EURTRY'yi etkilemez (24.11.2026 → 26.11).
* **EURUSD spot**'u kendisinindir: USD ve EUR'nun ikisinin de iş günü olduğu iki gün sonrası (`WORKDAY(TODAY(),2,USD+EUR)`);
  TRY tatili onu kaydırmaz: 27.10.2026'da işlem → 29.10 (Cumhuriyet Bayramı, yalnız TRY) EURUSD'nin valörüdür, EURTRY'ninki
  30.10. Günlük İşlemler'de EURUSD'nin vadeleri ve gün sayısı, Spot / FX'teki tarihleri bundan sayılır.
* Spot gecikmeleri çalışma kitabınınkiyle aynıdır (USDTRY T+1, EURTRY T+2); değişen yalnız tatil takvimidir. İki hücre
  önceden Bloomberg'in `SETTLE_DT`'siydi (kayıtlı veri modunda dosyanın kaydedildiği günün tarihi); artık masanın
  listelerinden hesaplanır, kayıtlı veride de doğrudur. Bloomberg'in tarihi yanlarında durur (`Forward!J2`, `L2`:
  "Bloomberg valörü"), karşılaştırmak için. Spot valörü hâlâ kişisel olarak yazılabilir (silince formüle döner).
* **Vadeler** çalışma kitabının kendi kuralıyla (`WORKDAY(EDATE(spot, n) − 1, 1, …)`, haftalar spot + 7·n), paritenin
  ortak takvimiyle: Masa'nın forward fiyatlama tarihleri (`MASA!P94:P99`) ve kırık vadesi (`C171`), Forward sayfasının
  çapraz forward valörleri (`B200:B205`, USDTRY bacağı) ve XCCY düğümlerinin yedek gün sayısı (`K130:K134`), `EK_FWD`'nin
  USDTRY / EURTRY kotasyon matrisleri ve "TRY faizleri vadelere göre" tablosu, Günlük İşlemler'de vadeyle yazılan valör
  (`3M`, `2W`: USDTRY → TRY + USD, EURTRY → TRY + EUR, EURUSD → USD + EUR; başka parite eskisi gibi TRY listesiyle) ve Spot
  / FX sayfası (USDTRY, EURTRY, EURUSD iki takvimle; diğer pariteler eskisi gibi yalnız hafta sonunu atlar). Örnek: spot
  26.10.2026 → 1M = 26.11 Thanksgiving → 27.11; EURTRY spot 04.03.2026 → 1M = 04.04 cumartesi, 06.04 Easter Monday → 07.04.
* **TLREF / OIS spotu** (`OIS_MAIN!B2`, çalışma kitabının `SPOTDATE`'i) TRY listesinin bir sonraki iş günüdür,
  `WORKDAY(TODAY(),1,Motor!A361:A523)` - ABD tatilleri sayılmaz: 25.11.2026'da → 26.11 (TLREF Thanksgiving'de çalışır;
  USDTRY 27.11), 28.10 → 30.10, 31.12 → 04.01.2027. Önceden Bloomberg'in USDTRY `SETTLE_DT`'siydi (`OIS_MAIN!W2`, bir FX
  tarihi); o şimdi OIS sayfasının Parametreler tablosunda yanında durur (`K2:L2`, "Bloomberg valörü").
* TRY para piyasası, tahvil, VİOP, OIS, TLREF ve toplantı takvimi tarihleri (`B2`'den sayılanlar dahil: OIS günleri,
  Masa'nın spotu, O/N tablosu, kırık vadenin OIS tarafı) ve masanın piyasa günleri yalnız TRY listesini kullanır; FX
  valörleri `Forward!I2`'den sayılır. (`VIOP!K3`, VİOP'un spotu, Bloomberg'in USDTRY valörü olarak kaldı.)
* Ortak takvim `EK_TATIL`'de yan yana iki sütundur: `B:C` = USD + TRY, `C:D` = TRY + EUR (C sütunu TRY listesinin kopyası,
  `=N(Motor!A361)` …). WORKDAY boş hücreyi, aynı günün iki kez geçmesini ve sırasız listeyi sorun etmez; tarih olmayan bir
  metin (bir ad, boş metin) Excel'deki gibi `#VALUE!` verir, kopya bu yüzden sayıdır (boş satır 0).

Bir liste kaydedilince bütün sayfalar herkes için yeniden hesaplanır (toplantı takvimi değişince olduğu gibi: ortak
sayfalar ilk istekten önce arka planda hazırlanır); yazma, hesap motorunun kuyruğunda öne geçer. TRY listesi değişince
masanın piyasa günleri (izleme, operasyon) de aynı gün yenilenir.

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
  dakikada bir (TRY tatil listesi gün içinde değişirse spot da kayar) geçen toplantıyı
  listeden arşive alır, liste sıradaki toplantıdan (MPC1) başlar; dosyanın adımları, her kullanıcının senaryo
  adımları ve kayıtlı senaryoları toplantılarıyla birlikte bir satır kayar. Kaydırmadan önce ve sonra her toplantının
  fiyatlaması ve her kullanıcının senaryo patikaları toplantı bazında aynıdır (testle doğrulanır); kaydı yapan
  "otomatik" görünür, Ayarlar'da son otomatik kaydırma yazar. **Geçen toplantıları arşivle** aynı işi elle yapar.
  Fiyatlama geçmişi toplantının tarihine bağlı olduğu için kaydırmadan etkilenmez.
* Takvim değişince fiyatlama geçmişi yeni takvimle arka planda yeniden hesaplanır (yalnızca etkilenen günler).
* Geriye bakış penceresinde artık hesaplanamayan bir gün (kotası ya da TLREF'i kalmayan, tatil sayılan) geçmişten çıkar;
  pencereden eski günler ve **bugünden sonraki günler kalır**: masanın verisinin bir kopyası kayıtlı veri modunda
  açılınca (bugün = dosyanın kaydedildiği gün) sonradan canlıda fiyatlanan günler silinmez.
* *Tarihçe* bölümü: durum, DİBS getiri alanı, geriye bakış süresi, "Şimdi güncelle", "PPK geçmişini yeniden
  hesapla". *Tarihçe serileri* tablosu her ticker için ilk / son gün ve gün sayısını gösterir — matriste boş kalan
  bir satırın nedeni (Bloomberg o ticker ya da alan için geçmiş vermiyor) buradan görülür.

### Quant sinyaller

**Quant** grubundaki on beş sayfa, masanın istatistik analizlerini **işlem sinyaline** çevirir: her analiz aynı biçimde
sinyal üretir, **Sinyaller** sayfası hepsini tek listede açıklanabilir bir puanla sıralar, bir sinyal giriş eşiğini
geçtiği an kaydedilir, izlenir ve abone olan kullanıcıya bildirilir. Analiz sayfaları: **Korelasyon**, **PCA / RV**,
**Çiftler**, **Rejim & Momentum**, **FX Vol Primi & Carry**, **Makro Beta**, **Tahmin Modeli**, **Gün İçi**,
**Eğri Adil Değeri**, **Opsiyon** ([aşağıda](#eğri-adil-değeri-ve-opsiyon)), **İma Patikası**, **Öncü-Takipçi**,
**VİOP** (aşağıda: *VİOP*); her
biri kendi sinyallerini üstte listeler, satıra tıklayınca serisi çizilir. **TCMB WIRP** sinyal üretmez: piyasanın
toplantı başına fiyatladığı karar olasılıkları (aşağıda: *İma Patikası ve TCMB WIRP*).

Menüde bu sayfalar **dört giriştir**, her biri sekmeli bir sayfa: **Sinyaller** (Sinyaller, Gün içi, Model), **Faiz**
(PCA / RV, Çiftler, Korelasyon, Rejim, Eğri Adil Değeri, İma Patikası, TCMB WIRP, Öncü-Takipçi), **FX** (FX, Makro,
Opsiyon) ve **VİOP**; her sayfanın adresi aynıdır, girişe tıklayınca son açılan sekmesi gelir. Canlı sinyal listesi, VİOP
emir seviyeleri ve kontratları, WIRP tablosu ve parite özeti launchpad'e, yan panele ve ayrı pencereye de konur
([Launchpad ve gezinme](#launchpad-ve-gezinme)).

**Tablolar masanın diliyle.** Her quant tablosunun başlığının hemen altında bir-iki cümle: tablo neyi söyler, hangi sayı
ne zaman ve hangi yönde işlem demektir (ör. PCA / RV'nin zengin / ucuz tablosu: "Her OIS vadesi iki komşusuna göre ucuz
mu pahalı mı? *Kalıntı (bp)* artıysa vade ucuz → receive, eksiyse pahalı → pay …"). Tablonun nasıl hesaplandığı
altındaki notta **Yöntem** olarak kalır (değişmedi); okunuşu ya da canlı bilgiyi veren notlar (sinyal listelerininki,
kotasyonun valörü ve işlemiş faizi, switch'in nominali) etiketsizdir. Cümleler tek dosyada, tablonun kimliğiyle
(`tto/static/js/pages/quantread.js`): sayfaların ortak sinyal listesi ve grafiği tek cümleyle; veri kapsamı, hesap
durumu, ayar ve abonelik formları cümlesiz. `test_quantread.py` her tablonun bir cümlesi olduğunu, kalkan tabloya cümle
kalmadığını, cümlelerin kısa (en çok 320 karakter) ve yöntem terimsiz (ADF, Kalman, GARCH, SVI, EWMA …) olduğunu denetler.

**Motoru bloklamaz.** Bütün hesaplar `tto-quant` iş parçacığında, tarihçenin kapanışlarının bir kopyası üzerinde
yapılır (saf Python; numpy yok: `tto/quantmath.py`). Yeni bir kapanış gelince (tarihçe deposu her 5 dakikada bir
yoklanır), gün dönünce ya da ayar değişince **tam hesap**; arada **dakikada en çok bir kez** yalnızca son nokta canlı
değerlerle yenilenir (her enstrüman, seviyesini canlı değerden okuyan küçük bir fonksiyon tutar), sonuç önbellekte
durur, sayfalar yalnızca onu okur. Motor iş parçacığında geçen tek şey kısa bir okumadır: kaynak sayfasındaki canlı
OIS / offshore kotaları, VİOP geçmişi ve canlı satırı, Carry & Roll'un vade motoru (ilk okuma ~0,3 sn, sonrakiler
milisaniyeler). PPK patikası OIS_MAIN'den okunmaz (çözücüyü motor iş parçacığında çalıştırırdı); tarihçenin kendi
motorunda hesapladığı son gün kullanılır. Masa bilgisayarında iki yıllık sentetik tarihçeyle tam hesap ~3,1 – 3,4 sn
(en ağırları model ~0,8 sn, DİBS NSS ~0,7 sn, OIS NSS ~0,55 sn, GARCH ~0,35 sn), canlı yenileme ~25 ms (canlı smile
ve NSS'le ~0,1 sn); motor iş parçacığındaki okuma (DİBS RV dahil) ~15 ms. Süreler her sayfanın altındaki *Hesap durumu*
tablosunda yazar. Arka plan işi tarihçe güncellemesiyle birlikte çalışır (`--no-history` ile ikisi de durur;
"Şimdi hesapla" yine çalışır).

**Bir sinyal** şunları taşır:

| Alan | Anlamı |
|---|---|
| Düz anlatım | Kartın başında, sinyalin kendi sayılarından tek paragraf: ne yapılır, hangi enstrümanda, hangi fiyattan; tutma süresince ne beklenir ve hedefte / stopta ne olur. FX: "Bugün 3 aylık USDTRY forward'ını satıp ~63 iş günü tutarsan (giriş 44,1250) ve kur o sürede beklenen seviyeye gelirse (43,6000), 1 mn USD başına ~525 bin TRY kazanırsın: forward priminden (carry) +2.325 bin TRY, kur hareketinden -1.800 bin TRY (spot 41,8000 → 43,6000). Hedefte (43,6000) ~525 bin TRY kâr, stopta (44,6000) ~475 bin TRY zarar." Faiz: "Sabit faiz alınan (receive): 2Y OIS (değişken bacak TLREF). 2Y OIS (PC1–PC2 hedge'li) şimdi +3,0 bp; hedef seviyesine (0,0 bp) gelirse 3,0 bp ≈ 120 bin TL kazanırsın, stop seviyesine (+3,5 bp) gelirse 0,5 bp ≈ 20 bin TL kaybedersin. Beklenen: ~13 iş günü içinde +5,1 bp ≈ +203 bin TL (+2,6 bp'si carry + roll). Ana bacak 1.000 $ DV01 = 40.000 TL / bp." Altında İşlem, Giriş / hedef / stop, Beklenen K/Z ve Hedefte / stopta satırları aynı sayılarla |
| Tez | Tek cümle: ne, ne kadar yerinden oynamış, hangi pencereyle, işlem ve beklenen kâr ("2Y OIS, iki komşusuyla … 8,4 bp ucuz (250 günlük pencere, z +2,6); yarı ömür 6 gün → Receive 2Y OIS; beklenen +5,1 bp ≈ +203 bin TL (carry + roll dahil)"; FX'te "USDTRY forward'ların fiyatladığından geride kalıyor: kur, forward priminin gerisinde - forward'la satan kazanıyor (…) → Sell USDTRY forward; beklenen ~+353 bin TRY / 1 mn USD (forward primi dahil)") |
| Aile, varlık | Hangi analizden geldiği; TRY OIS, Offshore, VİOP, DİBS, FX, FX vol, EM carry, Küresel (süzgeçler bunlara göre) |
| İşlem | İfade ve bacaklar, ağırlıklarıyla: "Receive 2s5s10s PCA-nötr fly", "Pay 1s2s PC1-nötr spread", "Sell USDTRY 3M ATM vol", "Steepener 2s10s", "Sell USDTRY forward"; hedge'li bir paket (Eğri ve DİBS adil değeri, PCA kalıntısı) **bacak bacak**: "Buy 09.06.30 · Sell 26.09.29 · Sell 28.03.31", "Receive 2Y OIS · Pay 18M OIS · Pay 3Y OIS". Sinyalin *Yön* satırı da her bacağı nominali ve DV01'iyle ($ / TL) yazar; bacak tablosu her paket için: işlem (Buy / Sell, Pay / Receive), enstrüman, **nominal (mn TL)**, **DV01 ($ ve TL / bp)**, DV01 ağırlığı - ana bacak paket DV01'i (ayar, **1.000 $ / bp**; TL'si OIS_MAIN!D2'deki USDTRY ile), OIS bacağının nominali DV01 ÷ (annuity × 1e-4), annuity Motor'unki (Günlük İşlemler'in OIS girişi gibi), kâğıdınki DV01 ÷ kâğıdın 1 mn'lik DV01'i (DİBS RV!AI); nominaller yuvarlanmaz (masa 5 mn TL'ye yuvarlar, OIS_MAIN!H2) |
| Yön, skor, güç | z (ailenin skoru); güç |z| ÷ giriş eşiğine göre: Zayıf < 1,25 ≤ Orta < 1,5 ≤ Güçlü; bir kapıya takılan sinyalin gücü yazılmaz: **elendi** |
| İşlem (masanın diliyle) | FX: enstrüman ve yön - "USDTRY 1A forward sat" (tutma süresinin forward'ı: valörü ufkun sonu; 20 iş günü = 28 gün ≈ "1A"), forward primi ailesinde "USDTRY 3A forward sat", gün içinde "USDTRY spot sat"; büyüklük 1 mn baz döviz. Faiz ve diğerleri: bacaklar ne yapıldığına göre gruplanır - "sabit faiz alınan (receive): 2Y OIS · sabit faiz ödenen (pay): 1Y OIS ×0,45, 5Y OIS ×0,30 (değişken bacak TLREF)", "alınan: VİOP Kas26 (12 kontrat) · satılan: USDTRY spot", "alınan: 09.06.30 · satılan: …"; yanında ana bacağın DV01'i ($ ve TL / bp) |
| Giriş / hedef / stop | Giriş = şimdiki seviye. Ortalamaya dönüş ailelerinde hedef ortalamada (hedef z, varsayılan 0), stop seviyenin |z| = 3,5 olduğu yerde; momentum / model / döngü / carry sinyallerinde hedef ve stop ufuk boyunca beklenen hareketten (her ailenin notunda yazar). **FX'te işlem yapılan forward'ın kuru**: giriş bugünkü forward (ör. 44,1250; spot yanında), hedef ve stop analiz serisinin hedef / stop seviyesine karşılık gelen forward kuru (forward pozisyonunun getirisi forward'ın log değişimidir: F × e^(Δ / 100); forward priminde tampon oraya gelince 3A forward, spot bugünkü yerindeyken); paritenin kendi ondalığıyla (USDTRY 4, EURUSD 5, USDJPY 3). Listede de bu kurlar, *Birim* sütununda "USDTRY 1A fwd"; analiz serisinin değerleri ipucunda ve kartın *Analiz serisi* satırında. Faizde seviye kendi biriminde (%38,50, +3,0 bp) |
| Beklenen K/Z | Tutma boyunca beklenen kâr, **carry + roll dahil**: ortalamaya dönüşte OU'nun o sürede kapattığı pay (aradaki fark × (1 − 2^(−tutma / yarı ömür))), momentumda son 63 günün ortalama değişimi (kesinliğiyle küçültülmüş) × ufuk, modelde (2p − 1) × haftalık hareketin ortalama büyüklüğü, makroda kalıntının ertesi hafta geri dönen payı (geçmişten), döngüde fazın ortalama değişimi, forward priminde tamponun ufka düşen payı. **Para olarak**: FX'te 1 mn baz döviz başına kote para biriminde (USDTRY / EURTRY / GBPTRY: TRY, EURUSD: USD, diğerleri kendi kote parası; yanında TRY ve USD karşılığı) = 1 mn × forward'ın beklenen fiyat hareketi (giriş → beklenen), ikiye ayrılır: **forward primi (carry)** = 1 mn × (forward − spot), tutma boyunca kazanılan / ödenen prim (forward priminde 3A puanlarının tutma süresine düşen payı), ve **kur hareketi** = 1 mn × spotun beklenen hareketi (toplamdan kalan; ikisinin toplamı beklenen K/Z); listede "+525 bin TRY / 1 mn USD", % ipucunda. Faizde bp ve TL (bp × ana bacağın TL DV01'i), carry + roll ile hareket ayrı; vol'de vol puanı; ufkun σ'sı ipucunda |
| Hedefte / stopta, ödül / risk | Hedefe ve stoba uzaklık: FX'te 1 mn baz döviz başına para (hedef / stop kuru − giriş), faizde bp ve TL; oranları ve beklenen ÷ risk |
| Yarı ömür, tutma | Seviyenin AR(1) regresyonundan Ornstein-Uhlenbeck yarı ömrü (iş günü); beklenen tutma = yarı ömür × log₂(|z| ÷ 0,5) - beklenen z'nin 0,5'e inme süresi |
| Carry / hafta, carry % / yıl | Faizde Carry & Roll sayfasının vade motorundan (ufuk A, haftalığa çevrilmiş), işlemin yönünde, bp; FX'te forward'ların ima ettiği forward primi, işlemin yönünde, haftalık ve yıllık % (sürekli bileşik, en kısa forward'tan); kartta tutma süresine düşen payı para olarak |
| Rejim | Ortalamaya dönüş / Trend / Nötr (varyans oranı testi), Hurst üsteli, vol yüzdeliği |
| Uyum | Aynı bacağı aynı yönde isteyen **başka aile** sayısı (ve ters yöndekiler) |
| Kapılar | Her kapı geçti (✓) / takıldı (✗) ve nedeni: eşik, stop bölgesi, rejim, yarı ömür, ailenin kendi onayı (ortalamalar, USDTRY trendi), örneklem (döngü), tolerans (FRA), carry (FX: forward primi aleyhine işlemin beklenen kazancı tamponu geçmezse "carry'yi karşılamıyor"; tutarlar 1 mn baz döviz başına para: "forward primi lehte: ufukta +1.184 bin TRY / 1 mn USD"), beklenen kâr (carry dahil sıfırın altındaysa; faizde bp ve TL) |
| Saat, geçmiş | Hesap saati (● canlı değerle); tıklayınca serisi, ±giriş / ±stop bantları ve giriş / hedef / stop çizgileri, tez, kapılar |

**Sıralama (bileşik puan)** = |z| × rejim uyumu × yarı ömür uyumu × carry yönü, ve her çarpan açıklanır:

* |z| masanın ölçeğinde (kendi eşiği olan aile – momentum, döngü – eşiğine göre ölçeklenir), en çok stop eşiği kadar sayılır;
* rejim: ortalamaya dönüş sinyali ortalamaya dönen rejimde 1, nötrde 0,5, trendde 0 (elenir); momentum tersi;
* yarı ömür: ufuk (20 iş günü) içindeyse 1, ufkun iki katına kadar ufuk ÷ yarı ömür, ötesi 0 (elenir);
* carry işlemin aleyhineyse 0,5 (faiz); FX'te carry seviyenin içindedir, aleyhine olan carry kapısından geçmeli.

Eşiği geçip bir kapının (rejim, yarı ömür, stop bölgesi, hareketli ortalama, trend, carry, beklenen kâr, örneklem,
tolerans) tuttuğu sinyaller ayrı listede, **elendi** olarak nedeniyle görünür.

**FX: hesap forward pozisyonunun getirisinde, anlatım kurla ve parayla.** Yönlü FX sinyalleri (momentum, rejim, model,
makro kalıntı) spotun değil, **forward pozisyonunun** getirisinin üzerinde çalışır: günlük `ln(S_t / S_{t−1}) − carry`
(carry = bazı uzun tutmanın yıllık getirisi `(ln S − ln F) × 365 / gün`, o günün en kısa forward'ından; USDTRY'de 1A /
3A / 6A / 1Y swap puanları, diğerlerinde 3A). Forward'ı olmayan bir pariteye carry uydurulmaz: momentum tablosunda
"forward yok", sinyal yok. Hedef, stop ve beklenen kâr bu getiri üzerinde hesaplanır (forward primi içinde); kart ve
liste ise bunu masanın okuduğu gibi verir: **ufkun sonu valörlü forward'ı** bugünkü kurundan al / sat, hedef ve stop o
forward'ın kuru (getirinin Δ'sı forward'ın log değişimi: F × e^(Δ / 100)), beklenen K/Z 1 mn baz döviz başına =
1 mn × (giriş kuru − beklenen kur), forward primi (1 mn × (forward − spot), tutma süresinin) ve kur hareketi (1 mn ×
spotun beklenen hareketi) ayrı. Forward primi ailesi 3A forward'ı satar / alır; beklenen kâr tamponun tutma süresine
düşen payı, spotun yüzdesi olarak (ima artış basit faizle yıllıklandırıldığı için), forward primi 3A puanlarının o
süreye düşen payı, kalan beklenen kur artışıdır. EM carry 3A forward'ın kendi kuruyla; gün içi FX sinyalleri spotla.
Tutma süresi her FX sinyalinde sinyalin kendisininkidir (ortalamaya dönüşte yarı ömürden: forward primi ve gün içi z;
önceden carry varsayılan 20 günlük ufukla okunuyordu - kararları değiştirmez, gösterilen carry'yi düzeltir). Forward
primi aleyhine bir işlem (ör. USDTRY long) ancak beklenen kazancı tutma süresinin σ'sının yarısını (*carry aleyhine
işlemde tampon*) geçerse kalır, yoksa "carry'yi karşılamıyor" diye elenir. Kontrollü bir kayışta (USDTRY yılda ~%20,
forward ~%30) spotun yükselişi "USDTRY al" değildir: kur forward priminin gerisinde kalır, forward'la satan kazanır,
işaret TRY long'dur. Grafikte analiz serisi (forward pozisyonunun birikimli getirisi, %) çizilir, başlığı bunu söyler;
kartın *Analiz serisi* satırı onun giriş / hedef / stop'unu yazar. FX Vol Primi &
Carry sayfasının başında **parite özeti**: carry % / yıl (USDTRY'de vade yapısıyla), beklenen kayma (günlük getirilerin
EWMA'sı, λ 0,97, kendi kesinliğiyle küçültülmüş: üç standart hatanın içindeki kayma sıfır sayılır), long'un beklenen
getirisi (kayma + carry), carry tarafının tamponu ve **karar** (beklenen getiri ÷ vol ≥ 0,3 ise ilgili para birimi
long / short, değilse nötr).

**Gün içi sinyaller** (`tto/quantintraday.py`, **Gün İçi** sayfası). Bloomberg'e ayrı istek yoktur: quant iş
parçacığının dakikada bir zaten okuduğu canlı değerler (kaynak sayfasındaki OIS / offshore kotaları, FX spotları,
USDTRY 1A puanı) canlı modda, iş günü 09:30 – 18:00 arasında dakikalık kapanış olarak küçük bir SQLite dosyasına
yazılır (`quant_bars.sqlite3`, veri klasöründe; son 20 işlem günü tutulur - Öncü-Takipçi'nin kendi anahtarları,
VİOP ve DİBS getirileri gibi, son 5 gün), 5 dakikalık barlar bunlardan kurulur.
Dört aile, her biri "gün içi" etiketli, kendi ufku (bar = 5 dk) ve stop'larıyla, dakikada bir yenilenir ve diğerleri
gibi kaydedilir / bildirilir: **gün içi z** (seviyenin günün son 60 dakikalık ortalamasına uzaklığı, son 20 günün bar
dağılımına göre: geri dönüş), **gün içi kırılım** (açılış aralığı = ilk 30 dakika; aralığın dörtte biri ötesine
kırılım yönünde, hedef bir aralık daha, stop aralığın ortası; beklenen = son günlerin kırılımlarının kapanışa kadar
ortalama devamı, en az 5 kırılım), **gün içi RV** (offshore − OIS 3A / 1Y, 1s2s, 2s5s 5 dakikalık barlarda: geri
dönüş), **USDTRY carry patikası** (günün açılışından forward priminin dakika dakika ima ettiği patikaya göre spot: bar
gürültüsü × √bar ile z; öndeyse sat, gerideyse al). PPK günü 13:45 – 15:30 arası ortalamaya dönüş sinyali elenir (PPK
açıklama penceresi); 17:00'den sonra yeni gün içi işlem yok; kayıtta gün içi giriş ufkunda ya da seans sonunda kapanır,
geceye taşınmaz. Kayıtlı veri modunda bar yoktur, sayfa bunu söyler.

**Geri test.** Bütün aileler, canlıdakiyle **aynı kurallarla** tarihçe üzerinde yürüyen pencereyle sınanır
(`tto/quantbt.py`): son bir yılın (250 iş günü) her 10. iş gününde her aile yalnızca o güne kadarki kapanışlarla
yeniden kurulur, aradaki günler o günün kapanışı "canlı değer" sayılarak puanlanır ve sinyali `make_signal` verir -
eşikler ve kapılar aynı. Bir gün sinyal olan (önceki gün olmayan) enstrüman o günün kapanışından girilir; işlem
açıldığı modeli tutar, hedef, stop ya da tutma süresi (sinyalin kendisi, en çok kayıt süresi) dolunca sonraki
kapanışlarla kapanır - bir günün kararına sonraki hiçbir şey karışmaz (test: geleceği değiştirmek geçmiş işlemleri
değiştirmez). Aile ve tür (fly / spread'in klasik ya da PCA sürümü, FX ya da faiz) başına: işlem, isabet, ortalama K/Z
σ (canlı kayıttaki gibi sinyalin σ'sıyla) ve birimiyle (bp, %, vol; FX'te forward primi dahil, faiz paketinde tarihçede carry
motoru olmadığından fiyat hareketi), TL (paket DV01'iyle / 1 mn baz döviz başına: canlı sinyal gibi forward'ın fiyat hareketi), Sharpe (işlem K/Z σ'larının ortalaması
÷ σ × √yılda işlem) ve birikimli K/Z'nin en büyük düşüşü. Her canlı sinyalin yanında ailesinin (yeterli işlemi varsa
türünün) kaydı: "bu aile son 1 yılda 41 işlem, %58 isabet, ort. +0,4σ"; kapılarında "Geri test". Masa ayarı **geri
testi zayıf aileyi sustur** (varsayılan kapalı: yalnız gösterilir): açıkken en az 10 işlemi olup isabeti %50'nin ya da
Sharpe'ı 0'ın altında kalan ailenin sinyalleri "geri testte zayıf" diye elenir. Geri test günde bir kez (ve ayar
değişince), günün ilk tam hesabından sonra ayrı bir iş parçacığında (`tto-quant-bt`) çalışır, aileler arasında motora
yol vererek; masa bilgisayarında iki yıllık sentetik tarihçede 120 gün / 6 yeniden kurma ~10 sn, varsayılan 250 gün /
25 yeniden kurma ~40 sn; sonuç saklanır (`quant.backtest`), Sinyaller sayfasında "Geri test" tablosu.

**Gerekçe paneli.** Bir sinyale tıklayınca grafiğin altında *Gerekçe*: bugüne en çok benzeyen 10 geçmiş gün - her gün
o güne kadarki kapanışlardan z (sinyalin kendi skoru; yoksa seviyenin 60 günlük z'si), eğim (haftalık hareket ÷ günlük σ
× √5), rejim (son 60 günlük hareketin birinci gecikme otokorelasyonu), vol (20 / 60 günlük σ oranının logu) ve FX'te
carry ile tarif edilir; standartlaştırılır, z iki kat sayılır, en az bir hafta arayla seçilir - ve her birinden sonra
tutma süresi boyunca işlemin yönünde ne olduğu: dağılımı (ortalama, medyan, çeyrekler) ve kârda bitenlerin payı (FX'te
forward pozisyonunun getirisi - kur hareketi + forward primi -, faizde fiyat hareketi; carry ayrıca); sonuçlar para
olarak da (FX'te 1 mn baz döviz başına, faizde TL). Altında **geçersiz kılanlar**: stop seviyesi (FX'te forward'ın
kuru: "Stop: USDTRY 1A forward 52,2480 (giriş 52,0342)"), rejimin dönmesi (varyans oranı z'si ±1,645), yarı ömrün
ufkun iki katını aşması, forward priminin tersine dönmesi, eşbütünleşmenin
bozulması, model isabetinin düşmesi ve ufkun içindeki olaylar (PPK toplantıları - bugünün patikasından -, tatiller).

**Dinamik PCA ve kalıntının ölçüsü.** Eğrinin PCA'sı 60, 120 ve 250 günlük pencerelerde ayrı ayrı kurulur; PCA / RV
sayfasında pencereler, açıklanan paylar, PC1–PC3 yüklerinin pencere pencere değerleri ve kararlılığı (iki pencerenin
yük vektörlerinin |kosinüsü|, bir vadenin yükünün en büyük değişimi) yan yana. Kalıntı **seviyelerin PCA'sına** göre
ölçülür: tenor, iki komşusuyla seviye-PCA'sının ilk iki bileşenine nötr bir pakette, pencerenin ortalamasına göre.
Neden bu: bir indirim / artırım döngüsü eğriyi seviyelerin gerçekten kaydığı yönlerde (kısa uç daha çok) taşır; o
yönler seviye-PCA'sının ilk bileşenleridir, çıkarılınca kalan kalıntı döngüyle trend yapmaz. Değişimlerin PCA'sına göre
kalıntı (önceki ölçü) döngünün yönüyle günlük risk bileşenleri aynı olmadığı için trendin bir kısmını taşır - sentetik
bir indirim döngüsünde kalıntıların zamanla korelasyonu 1, seviye-PCA'sında ~0 (testte); kayan ortalamaya göre kalıntı
ise trende gecikir ve kalıcı bir sapmayı da "ortalama" sayar. Fly / spread ağırlıkları (risk nötrlüğü) değişimlerin
PCA'sından kalır. Her PCA sinyali penceresini yazar.

**FRA / PPK konvansiyonu.** Patika, tarihçenin aynı gün aynı kotalarla çözdüğü toplantı tarihli seviyelerdir;
çözücünün kendi taban seviyesinden (Motor!K4) başlar, her toplantının ertesi iş günü yeni seviyeye geçer, iş günü
bileşik (tatil ve hafta sonu basit). Par faiz masanın çalışma kitabındaki gibi (Motor!G325:K342): **≤ 3 ay vade
sonunda tek ödeme** (ACT/365, basit), **daha uzunlar üç ayda bir kupon** (par = (1 − DF) ÷ Σ gün / 365 × DF), vade sonu
`WORKDAY(EDATE(spot, ay) − 1, 1)`. Önceki sürüm 6A / 9A / 1Y kotalarını tek ödemeli okuyordu: kota − patika par farkı
vadeyle büyüyordu (1Y'de ~−480 bp). Şimdi patika kendi kotalarını yeniden üretir (PCA / RV sayfasında vade vade kota −
patika par; kaydedilmiş dosyada 1A −2,1 bp - çözücünün kendisi -, diğerleri < 0,1 bp) ve FRA farkı ancak 5 bp'yi
(çözücünün toleransı) aşınca sinyal olur; toplantı dönemleri tablosu patikanın seviyesini ve fiyatlanan adımı gösterir.
Bugünün patikası yoksa bugünün kotaları önceki günün patikasıyla karşılaştırılmaz (fark piyasanın hareketi olurdu).

**Aileler:**

| Aile | Ne hesaplar | Sinyal |
|---|---|---|
| Korelasyon kırılması | OIS 3M–10Y, offshore 3M / 1Y, VİOP ön vade ima, USDTRY spot ve 3M swap puanı, CDS, UST 2Y / 10Y, DXY, EM FX, Brent: günlük değişimlerin 20 / 60 / 120 günlük korelasyonu (ısı haritası) | 20 günlük korelasyonun Fisher dönüşümüyle kendi uzun dönem dağılımına göre z'si (uzun dönem \|ρ\| ≥ 0,3 olan çiftlerde); işlem: son 20 günde ayrışan çiftin β ile yakınsaması |
| PCA kalıntısı | TRY OIS eğrisinin (≥ %80 kapanışı olan vadeler) **60 / 120 / 250 günlük pencerelerde** değişimlerinin kovaryansı (risk bileşenleri: PC1 seviye / PC2 eğim / PC3 eğrilik; açıklanan varyans, bugünkü skorlar ve z) ve seviyelerinin PCA'sı; pencereler arasında yüklerin kararlılığı (\|kosinüs\|, en büyük yük değişimi) | Her vade, iki komşusuyla **seviye-PCA'sının** PC1–PC2'sine nötr pakette (bp, pencerenin ortalamasına göre): + ucuz → receive, − pahalı → pay; en az gözlem kadar kapanışı olan en uzun pencere (sinyal yazar: "250 günlük pencere"), diğer pencerelerin z'si yanında; beklenen kâr carry + roll dahil |
| Fly / spread (klasik ve PCA ağırlıklı) | Masa ayarındaki listedeki her spread ve fly **iki sürümde yan yana**: klasik (masanın usulü, DV01'de spread 1:1, fly 50/50: paralel kaymaya nötr) ve PCA ağırlıklı (spread PC1'e, fly PC1 + PC2'ye nötr); her biri için seri, z, yarı ömür, rejim, carry + roll, bacaklar (DV01, nominal), **net DV01** ve kalan maruziyet - PC1 / PC2 / PC3'ün 1σ'luk hareketinde paketin hareketi Σ w × e × √λ (klasik fly'ın gizli seviye / eğim maruziyeti, PCA fly'ın sıfır olmayan net DV01'i) ve farkı söyleyen tek satır | Her sürümün kendi z'si, ayrı sinyal ("klasik 50/50" / "1:1" ve "PCA ağırlıklı"; aynı aile, birbirini uyum saymaz) |
| FRA / PPK patikası | 1x3, 3x6, 6x9, 9x12 forward'ı: OIS kotalarından (masanın konvansiyonuyla çözülen iskonto, log-doğrusal) ve aynı günün toplantı tarihli PPK patikasından; vade başına kota − patika par faizi (≈ 0: patika kotaları yeniden üretir); sıradaki toplantı dönemlerinin seviyesi ve fiyatlanan adım | Farkın z'si, fark ≥ 5 bp ise (altı çözücünün toleransı: elenir): + ise uzak bacak ucuz → FRA receive (uzak receive / yakın pay) |
| Makro artık | TRY OIS 3M–10Y ve USDTRY'nin forward pozisyonu getirisi (kur değişimi − forward primi), günlük değişimleri ~ UST 2Y / 10Y, DXY, EM FX endeksi, Brent, CDS (EKK, betalar ve t'leri); bugünkü hareket = küresel + TRY'ye özgü; kalıntının ertesi hafta geri dönen payı (sonraki 5 günün hareketinin kalıntıya regresyonu) | TRY'ye özgü kalıntının z'si: açıklanmayan yükseliş → receive / USDTRY forward sat; geçmişte geri dönmüyorsa beklenen kâr yok, elenir |
| Eşbütünleşik çift | Offshore − OIS (vade vade), VİOP ima − OIS (kontrat kontrat), DİBS getirisi − vadesindeki OIS, TLREF FRN iskonto marjı − OIS, USDTRY 3M puan farkı − (OIS 3M − USD OIS 3M): Engle-Granger (EKK + kalıntıya ADF, MacKinnon 2010 kritik değerleri) | Yalnızca geçen çiftlerde (ADF %5 ve \|t(β)\| ≥ 2) spread'in z'si |
| Kalman çift | Aynı çiftler, hedge oranı rastgele yürüyüş (skaler Kalman filtresi) | Bir gün önceki β ile kalıntının z'si (ADF geçerse), statik olanla yan yana |
| VİOP takvim | Her VİOP vade çifti: fiyatlardan ima TRY forward faizi − aynı tarihler için OIS forward'ı (USD faiziyle faiz paritesi) | Farkın z'si: + ise uzak vade pahalı → uzak sat / yakın al |
| Momentum | OIS vadeleri, offshore, UST, DXY, Brent, CDS ve her FX paritesi (forward pozisyonunun getirisi: kur değişimi − forward primi): 1H / 1A / 3A değişim ÷ (vol × √gün), gruplar içinde sıra, 20 / 60 günlük ortalama kesişimi | \|skor\| ≥ 1,5, ortalamalar aynı yönde, rejim trend (nötrde yarım ağırlık); FX'te forward primi aleyhine ise onu karşılamalı |
| PPK döngüsü | Her günün fazı (TLREF'in 63 iş günlük değişimi ≤ −100 bp indirim, ≥ +100 bp artırım, arası sabit); 2s10s, 1s2s, 2s5s'in sonraki ufuk boyunca değişimi faz başına, Newey-West t; çakışan gözlemlerin bağımsız dönem sayısı (n ÷ ufuk) ve o örneklemin kritik değeri | Bugünkü fazda en az 2 bağımsız dönem ve \|t\| ≥ max(2, örneklemin %5 kritik değeri): steepener / flattener |
| Vol primi | USDTRY, EURUSD, ZAR, MXN, BRL, INR, IDR, HUF, PLN, COP: ATM 3M ima − gerçekleşen (21 / 63 / 126 gün), 25D RR'nin spota duyarlılığı | İma − 63 günlük gerçekleşenin z'si: pahalı → vol sat, ucuz → al |
| Vol tahmini | Aynı pariteler: EWMA (λ 0,94) ve GARCH(1,1) (ızgarada en çok olabilirlik, uzun dönem varyans hedefli) ile önümüzdeki 63 iş gününün ortalama vol'ü | İma − GARCH tahmininin z'si; vol primiyle aynı yöndeyse ikisi birbirini "uyum" olarak sayar |
| EM carry | Her para birimi: 3M forward'ın ima ettiği yıllık getiri farkı ÷ ATM 3M vol, sıralama, kendi z'si | TRY'nin carry / vol'ü − EM sepeti ortalamasının z'si: cazip → USDTRY 3M forward sat (EM sepetine karşı) |
| Forward primi | USDTRY 1M / 3M / 6M / 1Y, EURTRY 3M: forward'ın ima ettiği yıllık değer kaybı − beklenen kayma (getirilerin EWMA'sı, λ 0,97, kesinliğiyle küçültülmüş); gerçekleşen kayma yanında | Tamponun z'si: + forward kaybı fazla fiyatlıyor → carry (forward sat), − tersi; beklenen kâr = tamponun ufka düşen payı (forward al ancak tampon eksiyse ve carry'yi karşılıyorsa); USDTRY'nin forward pozisyonu getirisi trendde ise bekletilir |
| Gün içi z / kırılım / RV, USDTRY carry patikası | 5 dakikalık barlar (yukarıda) | Gün içi: kendi ufku (bar) ve stop'u; PPK penceresi ve seans sonu kapıları |
| Tahmin modeli | OIS 1Y / 2Y / 5Y / 10Y, USDTRY (forward pozisyonunun getirisi), CDS, UST 10Y: gelecek haftanın yönü için L2 lojistik regresyon (özellikler: 60 günlük z, 1H / 1A momentum, carry, rejim, vol; katsayılar gösterilir); **zorunlu kayan pencereli doğrulama** - her hafta bir test noktası, model yalnızca etiketi o güne kadar bilinen örneklerle kurulur | Yalnızca doğrulanmış isabet ≥ %55 ve ≥ 40 test noktası olan enstrümanlarda; z = (p − 0,5) ÷ 0,05; isabet, log-loss ve test sayısı sinyalin yanında |
| Eğri adil değeri | TRY OIS 1M – 10Y: her gün Nelson-Siegel-Svensson uyumu, Excel'in OIS kuralıyla (3A'ya kadar tek ödeme, sonra üç ayda bir kupon); her vadenin kotası − NSS par'ı (bp), sıfır ve forward eğrisi | Farkın z'si: + ucuz → receive, − pahalı → pay; paket vade + uyumun seviye ve eğim faktörlerine nötr iki komşu vade |
| DİBS adil değeri | DİBS RV'nin sabit kuponluları ve bonoları: NSS uyumu (BIST kuralı), getiri − model getiri (bp), OIS uyumuna göre fark, 1H / 1A carry + roll, receive / pay için en iyi kâğıt | Farkın z'si: + ucuz → al, − pahalı → sat; paket kâğıt + seviye / eğim nötr iki komşu kâğıt, carry'si kâğıtların carry + roll'u |
| Opsiyon smile | USDTRY ve EURUSD: ATM vade yapısı (1W – 1Y), 25D / 10D RR ve BF (1M, 3M), smile'ın forward'a göre ima ettiği ±X% olasılıkları ve gerçekleşen sıklık | z (vol puanı): 25D RR 1M / 3M (skew), 25D BF 1M / 3M ve 10D BF 1M (kanatlar), ATM eğimi 1Y − 1M - pahalı → sat, ucuz → al |
| İma patikası ayrıklığı | Her toplantının ima adımı (TCMB: tarihçenin PPK hesabı; Fed: USD kitabının FOMC tablosu) ızgaranın (50 / 25 bp) iki katının karışımı; bir dönemin seviyesinin komşularının ortalamasına göre kinki (ikinci farkın yarısı), kendi geçmişine göre z | Dönem komşularına göre ucuz → fly receive (+1 dönem, −½ komşular, toplantı tarihli OIS), pahalı → pay; en az 40 günlük geçmişle; senaryo K/Z, taşıma (0) ve tez notta |
| İma kalibrasyonu | Toplantı sıradakiyken (en çok 20 iş günü önce) büyük adıma verilen olasılık ile verilen karar (TLREF fixinginden; Fed: üst bandın günlük görüntülerinden) | En az 8 toplantıda kalibrasyon z'si girişin üstündeyse: sıradaki toplantının dönemi, piyasanın düşük fiyatladığı sonuca doğru |
| Öncü-takipçi | Offshore ↔ OIS (aynı vadeler), USDTRY swap puanı ↔ OIS, VİOP ön vade ↔ OIS ve offshore, her VİOP kontratı ↔ kendi vadesinin OIS'i, USDTRY / EURTRY ↔ OIS ön ucu, OIS 1Y ↔ 2Y / 5Y, DİBS RV listesinin her sabit kuponlu kâğıdı / bonosu ↔ vadesine en yakın OIS: günlük değişimlerin −5 … +5 gecikmeli çapraz korelasyonu ve asimetrisi (kim önde), iki yönde Granger F-testi, gecikme, β (ℓ gün içindeki toplam tepki), R², 60 / 120 / 250 günde kararlılık | Lider son ℓ + 1 günde ≥ k σ oynadı, takipçi yetişmedi: beklenen yetişme = β × lider hareketi − takipçinin hareketi, z = yetişme ÷ σ; giriş / hedef / stop takipçinin biriminde; her pencerede tutmayan öncülük elenir |

**Sinyal kaydı.** Bir sinyal giriş eşiğini geçtiği an (önceki bakışta altındaydı) saat, seviye, z, hedef ve stop ile
yazılır (`quant.log`), sonra izlenir: **hedef**, **stop** ya da 20 iş günü sonra (**süre**) kapanır; kâr / zarar
seviye birimi ve sinyalin σ'sı cinsinden. Sinyaller sayfasında aile başına isabet tablosu (isabet = hedef + kârda
kapanan süre dolmuşlar ÷ kapananlar). Bu bir **backtest değildir**: yalnızca dashboard çalışırken görülen geçişler.

**Alarmlar.** *Sinyal alarmı aboneliği* (Sinyaller sayfası): açık / kapalı, aileler, en az güç. Bir geçiş olunca canlı
akış (`/api/events`) `quant.alerts` sayacını artırır; açık sayfa `/api/quant/alerts?since=` ile abone olduğu yeni
sinyalleri alır ve köşede gösterir (tıklayınca sinyal açılır). **Masa alarmları:** *Masa ayarları*ndaki "masa
alarmına düşen en az güç" (varsayılan **Güçlü**; Zayıf / Orta / kapalı) ve üstündeki her geçiş ayrıca masanın
alarmı olur (`tto/deskalarms.py`: herkese çalar, "Gördüm" ile cevaplanır, günün kaydına girer): her sinyal kendi
alarmıdır (`quant:<sinyal>`), kaydı hedef / stop / süreyle kapanınca alarm da kapanır; susturma masa alarmlarında
olduğu gibi kişiseldir (bir trader onu kendisi için susturur, alarm herkese yine çalar). Masa alarmları olmayan bir
sürümde bu adım atlanır. Başka dinleyiciler için
`service.quant.add_alert_hook(fn)` her yeni sinyal alarmını (`{seq, sid, family, family_label, asset, expression, z,
level, unit, strength, day, time}`) verir.

**Ayarlar** (*Masa ayarları*, herkes için ortak; kim değiştirdiği yazar): giriş |z| 2, hedef z 0, stop |z| 3,5,
ufuk 20 iş günü, yarı ömür sınırı ufkun 2 katı, en az 120 gözlem, tahmin penceresi 250 gün, korelasyon pencereleri
20 / 60 / 120, kırılma için uzun dönem |ρ| ≥ 0,3, momentum eşiği 1,5, ortalamalar 20 / 60, varyans oranı q = 10,
rejim penceresi 250, kayıt süresi 20 iş günü, Kalman q = 0,01, model isabet eşiği %55, en az 40 test, L2 = 5, PPK
fazı eşiği 100 bp ve |t| ≥ 2 (küçük örneklemde o örneklemin kritik değeri), paket DV01'i 1.000 $ / bp (ana bacak; masanın OIS_MAIN!F2 "DV01/bacak $"ı gibi - TRY ile ölçen eski sürümün kaydı dolar sayılmaz), PCA-nötr liste
`1y2y, 2y5y, 5y10y, 2y10y, 1y5y, 6m1y2y, 1y2y3y, 1y2y5y, 2y3y5y, 2y5y10y, 3y5y10y`, carry aleyhine işlemde tampon
ufkun σ'sının 0,5'i, parite kararı için beklenen getiri ÷ vol ≥ 0,3, FX pariteleri (aşağıda), geri testi zayıf aileyi
sustur kapalı (açıkken: en az 10 işlem, isabet ≥ %50, Sharpe ≥ 0).

**Yeni tarihçe serileri.** Dosyanın tutmadığı seriler tarihçenin listesine eklendi (*Ayarlar → Tarihçe serileri*'nde
"Quant" grubu): canlı dashboard normal tarihçe güncellemesiyle bunları **iki yıl** geriye çeker. İlk doldurma
Bloomberg'in günlük limiti için **yayılır**: her tarihçe turunda (15 dk) en çok 40 seri, önce küresel sürücüler, sonra
spotlar, forward puanları (spotla birlikte her paritenin carry'si), ATM vol'ler, risk reversal'lar, en son Opsiyon
sayfasının vol'leri ve VİOP sayfasının beş serisi - 121 seri 4 turda (ilki açılışta, ~45 dakika; her seri yine bir kez,
toplam istek turda 5 serideki kadar); VİOP'un kontrat serileri yanlarında
kendi sıralarıyla turda 15 (aşağıda: *VİOP*). Bu sırada quant sayfaları eldekiyle çalışır; kapsam tablosu
dolmamış serilere **"geçmiş doluyor"** der, sayfanın üstündeki not kaç seri kaldığını söyler. Sonra her tur, tarihçenin
diğer serilerinde olduğu gibi yalnızca yeni günleri ister (masa 15 dakikalık güncellemeyi bütün seriler için tutar).
**Tarihçenin kendi serileri** (OIS, offshore, XCCY, TLREF, DİBS) de quant için iki yıl tutulur: ilk doldurmada
kendi penceresi (*Geriye bakış*, 370 gün) bir kerede, ertesi günden itibaren önceki yıl - yalnızca eksik kısım, elindeki
ilk kapanışın bir hafta içine kadar (boş bir cevap cevap sayılmaz) - turda 40 seri, quant serilerinden sonra.
Hepsi **terminalde doğrulanacak**; FX vol ticker'ları FX sayfalarının fiyat kaynağıyla (varsayılan BGN) kurulur.
Pariteler masa ayarındaki listedir (*FX pariteleri*; USDTRY hep başta); liste değişince tarihçe yeni paritenin
serilerini aynı kuralla doldurur:

| Seri | Ticker'lar (terminalde doğrulanacak) |
|---|---|
| Spot | `USDTRY Curncy`, `EURTRY Curncy`, `GBPTRY Curncy`, `EURUSD Curncy`, `GBPUSD Curncy`, `USDJPY Curncy`, `USDCHF Curncy`, `AUDUSD Curncy`, `USDCAD Curncy`, `USDCNH Curncy`, `USDZAR Curncy`, `USDMXN Curncy`, `USDBRL Curncy`, `USDINR Curncy`, `USDIDR Curncy`, `USDHUF Curncy`, `USDPLN Curncy`, `USDCOP Curncy`, `USDCZK Curncy`, `USDKRW Curncy`, `USDCLP Curncy`, `USDILS Curncy` |
| ATM 3M vol | `<PARİTE>V3M BGN Curncy` - TRY çaprazları (EURTRY, GBPTRY) dışında her parite: `USDTRYV3M`, `EURUSDV3M`, `GBPUSDV3M`, `USDJPYV3M`, `USDCHFV3M`, `AUDUSDV3M`, `USDCADV3M`, `USDCNHV3M`, `USDZARV3M`, `USDMXNV3M`, `USDBRLV3M`, `USDINRV3M`, `USDIDRV3M`, `USDHUFV3M`, `USDPLNV3M`, `USDCOPV3M`, `USDCZKV3M`, `USDKRWV3M`, `USDCLPV3M`, `USDILSV3M` |
| 25D RR 3M | `<PARİTE>25R3M BGN Curncy`, aynı pariteler |
| Forward puanı | `TRY1M Curncy`, `TRY3M Curncy`, `TRY6M Curncy`, `TRY12M Curncy`, `EURTRY3M Curncy`, `GBPTRY3M Curncy`, `EUR3M Curncy`, `GBP3M Curncy`, `JPY3M Curncy`, `CHF3M Curncy`, `AUD3M Curncy`, `CAD3M Curncy`, `CNH3M Curncy`, `ZAR3M Curncy`, `MXN3M Curncy`, `BRL3M Curncy`, `INR3M Curncy`, `IDR3M Curncy`, `HUF3M Curncy`, `PLN3M Curncy`, `COP3M Curncy`, `CZK3M Curncy`, `KRW3M Curncy`, `CLP3M Curncy`, `ILS3M Curncy` (BRL, INR, IDR, COP, KRW, CLP NDF'tir: puan yoksa NDF ticker'ı, ör. `BCN3M`, `IRN3M`, `IHN3M`, `KWN3M`, `CHN3M`, gerekebilir) |
| Küresel | `USGG2YR Index`, `USGG10YR Index`, `DXY Curncy`, `CO1 Comdty` (Brent), `TURKEY CDS USD SR 5Y D14 Corp`, `USSOC Curncy` (USD OIS 3M) |
| Opsiyon (USDTRY ve EURUSD, 11'er) | ATM `USDTRYV1W`, `USDTRYV1M`, `USDTRYV6M`, `USDTRYV1Y`; `USDTRY25R1M`; `USDTRY25B1M`, `USDTRY25B3M`; `USDTRY10R1M`, `USDTRY10R3M`; `USDTRY10B1M`, `USDTRY10B3M` (hepsi `… BGN Curncy`); EURUSD'nin aynı on biri (`EURUSDV1W BGN Curncy` …); EURUSD forward puanı `EUR1M Curncy`, `EUR3M Curncy` - toplam 24 (ATM 3M ve 25D RR 3M yukarıda) |

Gruplar: TRY (USDTRY ve TRY çaprazları), G10 (iki para birimi de G10), EM (gerisi: EM FX sepeti ve EM carry bunlardan).
**Bloomberg maliyeti** (sahte terminalle ölçülen bir canlı gün, `tests/test_quant.py`; hit = istek başına menkul ×
alan): 121 quant serisi (22 parite, küresel sürücüler, Opsiyon sayfasının vol'leri, VİOP sayfasının USD OIS 1M / 6M /
1Y'si ve USDTRY'nin gün içi en yüksek / en düşüğü) ilk gün iki yıllık doldurmada seri başına bir kez (turda 40 seriyle 4
tur, ~45 dakika), VİOP'un 90 kontrat serisi yanlarında kendi sırasıyla turda 15 (aşağıda: *VİOP*), sonra - tarihçenin
diğer serileri gibi - **her turda** yalnızca yeni günleri (masa 15 dakikalık güncellemeyi bütün seriler için tutar;
vadesi geçmiş kontratın yeni günü hiç sorulmaz). Ölçülen ilk canlı gün: 97 tur, 807 istek, 18.996 hit, 136.085 veri
noktası (400 seri soruldu, 267'sinin geçmişi var; 121 quant serisi, 167'si VİOP'un), bunun 2.361 hit ve 29.278 noktası
VİOP'un. Tarihçenin kendi serilerinin iki yıla uzatılması (C): ertesi gün seri başına bir kez, yalnızca eksik yılı
(gerçekte ~117 ticker, ~117 hit ve ~29.000 veri noktası bir kerelik; sahte terminalle ölçülen ertesi gün: 4 turda 841
hit, sonra turda 195, 23'ü VİOP'un). Hepsi `--max-hits` (400.000 / gün) içinde: bir gün ~%4,7. Turda 5 seriyle
ölçülen ilk gün 17.730 hit'ti: seriler erken dolunca gün içinde yeni günleri daha çok turda istenir (+1.266 hit).
Bunlardan dokuzu (`USDTRY Curncy`, `TRY1M` / `TRY3M` / `TRY6M` / `TRY12M Curncy`, `USSOA` / `USSOC` / `USSOF` /
`USSO1 Curncy`) çalışma kitabının kendi `BDH` bloklarında da var; kayıtlı veri modunda tarihçeye dosyanın kaydettiği son
bir ay girer.
Forward puanı okunurken: spota yakın (spotun 0,8 – 1,25 katı) bir kota outright forward sayılır (NDF ticker'ları),
değilse puan × 10^−ölçek; ölçek canlıda Bloomberg'in `FWD_SCALE` alanından günde bir kez okunur, yoksa 4 (yen 2).

**Sınırlar.**

* **Geri test bir modeldir.** Kapanıştan girip kapanıştan çıkar (gün içi yol, kayma, maliyet yok); faiz paketlerinde
  carry'siz; VİOP ve FRA aileleri yalnız yeniden kurma günlerinde girer (ara günlerde canlı satırları yok); sinyal kaydı
  ise yalnızca dashboard çalışırken görülen canlı geçişleri izler.
* **Tarihçe uzunluğu.** Analizlerin okuduğu bütün seriler iki yıl tutulur (yukarıda; ilk günler doldurulurken
  "geçmiş doluyor"). En az 120 gözlemi olmayan analiz sinyal üretmez (sayfasında nedeni yazar); PPK döngüsü fazın
  bağımsız dönem sayısıyla sınanır (en az 2, eşik o örneklemin kritik değeri), VİOP aileleri 100, FRA 60 günle yetinir.
* **VİOP** geçmişi VİOP Geçmişi sayfasının "Geçmiş" günü kadardır (varsayılan 120, en çok 240 iş günü); VİOP aileleri
  100 gözlemle yetinir. Kayıtlı veri modunda VİOP geçmişi yoktur.
* **DİBS** çiftleri canlı getiri okumaz (son kapanış); FRA / PPK ailesi PPK patikasını tarihçenin son hesabından alır
  (canlıda 15 dakikada bir).
* Kapanış saatleri farklı piyasaların (TRY, ABD, Brent) günlük değişimleri aynı güne yazılır: betalar ve
  korelasyonlar biraz küçük çıkar.
* PPK fazı politika faizi yerine **TLREF**'ten okunur; GARCH parametreleri penceredeki veriyle bir kez kestirilir
  (tahmin serisinin geçmişi bu parametrelerle); forward primindeki beklenen kayma gürültülüdür (yıllık birkaç puan).
* Kayıtlı veri modunda tarihçe dosyanın son ayıdır: sayfalar açılır, çoğu analiz "geçmiş kısa" der.

**Açık kararlar** (sorulmadan seçilen, ayarlardan değiştirilebilir ya da kodda tek yerde duran varsayılanlar):
yukarıdaki ayar değerleri; bileşik puandaki çarpanlar (nötr rejim 0,5, carry aleyhte 0,5, |z| stop'ta kırpılır);
rejimin varyans oranı z'si ±1,645 ile ayrılması; yarı ömür ≤ 0 olan (bir günde dönen) serinin "0 gün" sayılması;
çiftlerde ADF'nin yanında |t(β)| ≥ 2 şartı; EM sepeti (listedeki EM grubu: ZAR, MXN, BRL, INR, IDR, HUF, PLN, COP, CZK,
KRW, CLP, ILS, CNH) ve 3M vade; varsayılan 22 parite (G10'dan NZD, NOK, SEK, DKK listede yok; TRY çaprazlarından yalnız
EURTRY, GBPTRY; çaprazlara vol serisi istenmez); carry =
forward'ın ima ettiği fark (USD faizi gerekmez); EM FX endeksi = sepetin eşit ağırlıklı log getirisi; politika fazı
için TLREF ve 63 gün; model için haftalık etiket, dört haftada bir yeniden kurma, z = (p − 0,5) ÷ 0,05; alarmlar
varsayılan kapalı (abonelikle açılır), masa alarmına yalnızca **Güçlü** sinyaller; arka plan hesabının tarihçe
ayarına bağlı olması. Tarihçe isteklerinde: ilk doldurma turda 40 seri (`History.BACKFILL_PER_SYNC`) ve küresel →
spot → puan → vol → RR sırası; yeni günler son kapanışın 3 takvim günü öncesinden (eski kural her turda son 10 günü
yeniden okurdu: 3 günden eski bir düzeltme artık gelmez); geçmişi olmayan seri günde bir kez (eskiden 6 saatte bir);
quant serilerinin yeni günleri günde bir kez, 07:00'den sonra; tarihçenin kendi serilerinin önceki yılı ertesi gün.
FX'te: carry o günün en kısa forward'ından, ufkun carry'si vadeler arasında doğrusal (en uzunun ötesi düz); beklenen
kayma EWMA λ 0,97, üç standart hata içinde sıfır; momentumun beklenen kârında iki standart hata; carry aleyhine
tampon 0,5 σ; parite kararı 0,3. FRA toleransı 5 bp. Kapılar: beklenen kâr (carry dahil) sıfırın altındaysa her
ailede eleme; faizde carry aleyhine ağırlık 0,5 (önceki gibi).

### Eğri Adil Değeri ve Opsiyon

İki sayfa, üç aile (`tto/quantcurve.py`, `tto/quantopt.py`; sayfalar `tto/static/js/pages/quantfit.js`): diğer quant
aileleriyle aynı iş parçacığında, aynı sinyal biçimiyle, Sinyaller listesinde.

**Eğri Adil Değeri.** TRY OIS eğrisine ve DİBS'e her gün **Nelson-Siegel-Svensson** (NSS) eğrisi uydurulur; her vade
ve kâğıt için eğriye göre farkı (bp), bunun z'si, yarı ömrü ve rejimi - aileler **Eğri adil değeri** (OIS) ve **DİBS
adil değeri**.

* *Model:* sıfır faiz z(t) = β0 + β1·g(t/τ1) + β2·(g(t/τ1) − e^(−t/τ1)) + β3·(g(t/τ2) − e^(−t/τ2)), g(x) = (1 − e^(−x)) / x
  (sürekli bileşik, ACT/365); anlık forward aynı parametrelerle. τ'lar sabitken β doğrusal: uyum β'da Gauss-Newton;
  (τ1, τ2) için ızgara (τ2 ≥ 2·τ1: iki tümsek ayrı kalsın) ve en iyi beş noktadan altı parametrede Levenberg-Marquardt
  (NSS yüzeyinin birden çok sığ vadisi var). τ'lar her tam hesapta son kapanışta bir kez aranır (OIS ve DİBS için
  ~0,15 – 0,3 sn); pencerenin her günü ve dakikalık canlı nokta aynı τ ile, yalnızca β uydurularak - bir vadenin farkı
  pencere boyunca tek modelle ölçülür, z'si her gün aynı şeyi söyler. **Huber ağırlıkları** (2 sağlam σ'nın ötesi
  ağırlık kaybeder, en çok üç kez yeniden ağırlıklandırma): eğriden çok uzak tek bir kâğıt eğriyi komşularının üstüne
  bükmez (onları ters yönde zengin / ucuz gösterirdi). τ1 en kısa vadenin yarısından kısa, τ2 en uzun vadeden uzun
  olamaz: verinin dışındaki bir tümsek veriden okunamaz, orada β'lar kaçar (önde 1/t gibi bir uç, sonda neredeyse
  polinom yükler). Az ve gürültülü noktada β'lar yine büyük ve zıt işaretli çıkabilir (eğri verinin içinde aynı kalır):
  sayfa eğrinin 1Y / 2Y / 5Y / 10Y sıfır faizlerini önde, β'ları parantezde gösterir.
* *OIS:* par faizler **Excel'in kendi kuralıyla** uydurulur - Motor!B88:K130 (bootstrap) ve Motor!A325:K340 (her
  vadenin par'ı ve annuity'si; OIS_MAIN'in DV01'i ve blotter da bunu kullanır): **3A'ya kadar vadede tek ödeme, 6A'dan
  itibaren üç ayda bir sabit kupon**, ACT/365, tarihler OIS spot'undan (ertesi iş günü) ay ay. Fark = kota − NSS par
  (bp): + vade ucuz (receive), − pahalı (pay); seri bu fark ("2Y OIS · NSS farkı"), hedge paketindir. Sinyalin paketi vade
  + uyumun seviye (β0) ve eğim (β1) faktörlerine nötr iki komşu vade, DV01 ağırlıklı (PCA ailesinin PC1 / PC2 hedge'i gibi),
  bacak bacak ve nominalleriyle; carry + roll Carry & Roll'un vade motorundan.
  Tabloda her vadenin NSS par'ı, sıfır ve forward faizi; grafikte kotalar, NSS par, sıfır ve forward eğrileri.
* *DİBS:* DİBS RV listesinin sabit kuponlu kâğıtları ve bonoları / kuponsuzları (TLREF, FRN ve TÜFE'ye endeksliler
  dışarıda), sayfanın BIST kuralıyla: kupon c/f, vadeden geriye round(364/f) günde bir; getiri yılda f kez bileşik,
  kalan ilk dönem kesirli; bono basit (100/P − 1)·365/gün; kirli fiyat valörde (ertesi iş günü; sayfada "ISL0"
  fiyatlanan kâğıt kendi gününde) - sayfanın kirli fiyatını ve bono fiyatını birebir verir. Eğri getirilere uydurulur:
  her kâğıdın model fiyatı Σ CF·DF(t) ile piyasa fiyatının farkı, fiyatın getiriye duyarlılığına bölünerek (getiri
  hatası). Fark = getiri − model fiyatın getirisi (bp, kâğıdın kendi getiri kuralıyla): + ucuz (al), − pahalı (sat).
  Bugünkü değer DİBS RV'nin canlı getirisi; geçmiş günler tarihçenin kapanışları (`YLD_YTM_MID`). Bloomberg'in bu
  alanının kuralı bu kâğıtlar için belgesiz olduğundan her kâğıdın geçmişi, sayfanın **bugünkü basit ve bileşik**
  getirisinden hangisine yakınsa öyle okunur (bu seviyelerde ikisi 300 – 400 bp ayrı; ikisinden de 150 bp'ten uzaksa
  basit). Eğri **sabit kuponlulara** uydurulur (sayfanın kendi ASW uyumu da yalnızca "S" satırlarını alır): bonolar
  aynı vadedeki kuponlulardan 150 – 300 bp pahalı işlem görür ve ön ucu bükerdi; eğriye göre ölçülür, izlenir ama
  eğriyi biçimlendirmez. Yanında aynı nakit akışlarının **OIS uyumuyla** getirisi ve farkı (bp; ASW benzeri, sayfanın
  kendi ASW'si ve kendi pahalı / ucuzu - ASW'nin karesel uyumuna göre - yanında), kesit z (bugünkü farkların
  dağılımına göre; z'nin geçmişi yokken de bir ölçü).
* *Carry + roll*, 1 hafta ve 1 ay (7 / 30 gün), bp (÷ DV01: sayfanın AM / AN birimi): **carry** = getiri sabitken ufuktaki
  fiyat + aradaki kupon − fonlanan kirli fiyat; fonlama satırın reposu, yoksa OIS uyumunun ufka kadarki faizi (sayfanın
  varsayılan "Bootstrap" patikası gibi), yoksa günlük bileşik TLREF. **Roll** = eğri yerinde kalırken (nakit akışları
  yeni vadelerinin eğri faiziyle, kâğıdın eğriye göre farkı sabit) fiyat − getiri sabitken fiyat. Ufuktan önce ödenen
  kupon yeniden yatırılmaz. Sinyalin carry'si paketin 1 haftalık carry + roll'u.
* *Paketler* (DİBS adil değeri sinyali; seri kâğıdın kendi farkı, "05.10.33 · NSS farkı" - hedge paketlerindir), her bacak
  işlemi, nominali (mn TL) ve DV01'iyle ($ ve TL / bp), ana bacak 1.000 $ DV01:
  **Paket 1 · DİBS komşularıyla hedge'li** - kâğıt ve vadede iki komşusu, DİBS uyumunun seviye (β0) ve eğim (β1) faktörlerine nötr
  DV01 ağırlıklarıyla ("Sell 05.10.33 · Buy … · Buy …"): eğri kayar ya da dikleşirse paket yerinde kalır, kazanç kâğıdın
  eğriye dönmesinden. Kâğıdın DV01'i masanınki gibi (DİBS RV!AI: mod. süre × kirli fiyat, basit getiriden; geçmişi bileşik
  okunan kâğıtta ağırlıklar ona çevrilir). **Paket 2 · kâğıt + OIS, OIS'le hedge'li** - kâğıdın asset swap'ı, DİBS RV'nin kendi OIS hedge'i
  gibi (AJ: kâğıdın vadesine kadar bir OIS, aynı DV01) ama kote vadelerle: vadesini çevreleyen iki OIS vadesi, OIS DV01'i
  aralarında vadeye göre doğrusal, toplamı kâğıdınki (1:1); kâğıdı satan OIS receive, alan pay eder. Bu paket kâğıdın OIS'e
  göre farkıyla gider: NSS farkının yanında bütün eğrinin DİBS − OIS farkını da taşır (Paket 1 taşımaz); sinyalin z'si ve
  beklenen hareketi NSS farkınındır, carry + roll'u kendi bacaklarının (OIS'inki Carry & Roll'un vade motorundan).
* *Receive / pay için en iyi kâğıt:* puan = z × (1 aylık carry + roll) ÷ σ, σ kâğıdın 1 aylık getiri oynaklığı (son 60
  kapanışın günlük değişimleri × √21). z ile carry aynı yönü gösterdiğinde artı: **receive (al)** tarafında ucuz ve
  carry'si artı, **pay (sat)** tarafında pahalı ve carry'si eksi (açığa satış onu kazanır); carry'si z'sine ters olan
  kâğıt kendi tarafında eksi puanla sonda. z için kâğıdın tarihçede en az 120 günü gerekir.
* *Adil eğriden kotasyon:* sabit kuponlu herhangi bir DİBS (listeden ya da ISIN yazarak; listede olmayan kâğıt
  kataloğun kuponu ve vadesiyle) için valörüne göre NSS **adil getirisi** (eğrinin nakit akışlarına verdiği kirli fiyatın
  getirisi) ve adil **temiz / kirli fiyatı** - işlemiş faiz sayfanın kuralıyla (c/f × geçen gün / dönem günü) -, masanın
  **yarım spread**'iyle iki yönlü kotasyon: alış getirisi = adil + yarım, satış = adil − yarım (bp, basit getiri; BIST
  kuralıyla bileşik getiri ve fiyatlar yanında). Yarım spread vadeye göre üç kovada (kısa ≤ 2 yıl 10 bp, orta 15 bp,
  uzun ≥ 5 yıl 20 bp varsayılan; sınırlar ve bp'ler sayfadan, masanın ortak ayarı, kim değiştirdiği yazar). Yanında
  piyasa getirisi, adilden farkı (bp) ve z'si, carry + roll; **Kopyala** kotasyonu tek satır mesaj olarak kopyalar
  ("DİBS 15.03.28 (TRT150328T24) · getiri alış / satış · temiz alış / satış · adil · valör").
* *Switch A → B* (A sat / B al): **DV01 nötr** nominal oranı (1mn A'ya karşı B), getiri kazancı adil eğriye göre (B'nin
  farkı − A'nınki: + ise B daha ucuz), carry + roll farkı (1 hafta / 1 ay, bp), piyasa getiri farkı ve eğriye göre farkın
  geçmişine göre z'si ve yarı ömrü (iki kâğıdın ortak günlerinden), tek satır Türkçe okuma - Kopyala ile mesaj olarak.

**Opsiyon.** USDTRY ve EURUSD: ATM vol vade yapısı (1W, 1M, 3M, 6M, 1Y), 25D ve 10D risk reversal ve butterfly (1M,
3M), her birinin canlı değeri, z'si, RR / ATM ve BF / ATM. Aile **Opsiyon smile** (vol puanı olarak, kotalandığı gibi):
25D RR 1M / 3M (skew pahalı → RR sat), 25D BF 1M / 3M ve 10D BF 1M (kanatlar pahalı → BF sat), ATM eğimi 1Y − 1M
(pahalı → 1Y sat / 1M al). Tablodaki RR / ATM ve BF / ATM, seviyenin yalnızca ATM vol'ün kendi hareketi olan kısmını
gösterir.

* *Dağılım:* bir vadenin beş kotası tek bir **arbitrajsız smile** yapar (`tto/fxvol.py`, Spot / FX sayfasının kendisi:
  Gatheral'ın SVI'ı, beş kotaya beş parametre, paritenin delta kuralıyla - USDTRY primli forward delta, EURUSD EUR iskonto
  faktörüyle spot delta (forward'ından ve USD OIS'ten) -, butterfly'lar piyasa strangle'ı olarak; kelebek ve kanat
  koşulları ceza olarak: yoğunluk hiç eksiye düşmez, kotalar kendi aralarında tutarsızsa en yakın arbitrajsız smile
  alınır, artıkları sayfada). **Breeden-Litzenberger**: P(S > K) = −∂C/∂K, iskontosuz fiyatlarla (forward ölçüsü:
  ortalama forward'dır). T = vadenin takvim günü ÷ 365 (1M 30,4, 3M 91,25). Butterfly'lar yoksa smile ATM'de düz
  (lognormal) ve sayfa bunu söyler. Smile, kotaları değişmedikçe yeniden uydurulmaz.
* *Carry'li:* hareketler **forward'dan** ölçülür - USDTRY'nin 3M forward'ı spotun yüzde birkaç üstündedir; "spottan
  +%5" neredeyse kesindir ve opsiyonlar hakkında bir şey söylemez. İma: P(S > F·(1+X)) ve P(S < F·(1−X)); X: USDTRY 1M
  %2 / 3 / 5, 3M %3 / 5 / 10; EURUSD 1M %1 / 2 / 3, 3M %2 / 3 / 5. **Gerçekleşen**: tarihçenin her günü, o günün vade
  forward'ı ve vade sonraki spot (teslim gününde ya da sonraki ilk kapanış, en çok bir hafta sonra): S / F − 1'in X'i
  aştığı günlerin payı. Pencereler çakışır: n gün ≈ n ÷ vadedeki iş günü (21 / 63) bağımsız gözlem; standart hata ondan
  (iki yılda 3M için ~7 bağımsız gözlem: gürültülü). Fark + ise opsiyonlar o kuyruğu geçmişe göre pahalı fiyatlıyor.
  Yanında S / F − 1'in ortalaması (forward'ın sapması, carry getirisi) ve smile'ın %5 – %95 yüzdelikleri (forward'a
  göre %).

**Bloomberg maliyeti (24 yeni seri, hepsi `PX_LAST`).** Sahte terminalle ölçülen bir canlı gün (ilk tur + 96 tur):
10.131 → 12.173 hit (+2.042), 59.017 → 75.749 veri noktası (+16.732). Bunun ~24 hit / ~12.700 noktası **bir kerelik
doldurma** (seri başına iki yıllık tek aralık, ~528 kapanış; turda 40'ar, quant'ın son turunda); sonrası her gün seri başına
tur başına bir hit ve 2 – 3 kapanış: **günde ~2.330 hit, ~4.700 – 7.000 nokta** (`--max-hits` 400.000'in ~%0,6'sı).
Canlıda ayrıca her ticker için bir referans isteği ve abonelik (24), `EUR1M` / `EUR3M`'in `FWD_SCALE`'i günde bir kez.
EURUSD bunun 13 serisidir (`quantopt.PAIRS`'ten çıkarılırsa 11 seri, günde ~1.070 hit). Eğri Adil Değeri yeni seri
istemez (OIS ve DİBS tarihçenin kendi serileri; DİBS RV motor iş parçacığında okunur).

**Açık kararlar:** OIS kuralı Excel'inki (3A'ya kadar tek ödeme, sonra üç ayda bir kupon) - quant paketinin FRA ailesi
(`quantfam._annuity`, `curve_df`) 1Y'ye kadar tek ödeme, sonra yıllık kupon varsayar; ikisi `quantcurve.SINGLE_MONTHS` /
`COUPON_MONTHS` ile tek yerde değiştirilebilir. τ'ların her tam hesapta son kapanışta aranıp pencereye sabit
tutulması, sınırları (τ1 ≥ en kısa vadenin yarısı, τ2 ≤ en uzun vade); DİBS eğrisinin yalnızca sabit kuponlulara
uydurulması (bonolar ölçülür); Huber eşiği 2 sağlam σ, üç geçiş; `YLD_YTM_MID`'in kuralının sayfaya bakılarak seçilmesi (150 bp sınırı);
vadesine 30 günden az kalan kâğıdın uyum dışı kalması; carry ufukları 7 / 30 gün, kupon yeniden yatırılmaz; en iyi
kâğıt puanı z × carry / σ; RR ve BF sinyallerinin vol puanında (RR / ATM değil) olması, 10D RR'nin yalnızca tabloda;
eğim 1Y − 1M; hareket eşikleri (yukarıda); EURUSD'nin de dahil olması.

#### İma Patikası ve TCMB WIRP

Masanın sorusu: *"Hem USD hem TRY için, ima eğrisindeki yamukluklardan bir şey bulabilir miyiz? Örneğin −40 −60 ise
ima eğrisi, gerçek ya 0 −100, ya −100 0, ya da −50 −50 olacağı için bir düzeltme olması gerekli."* Bir toplantının ima
adımı ayrık kararların beklenen değeridir: TCMB 50 bp'nin katlarıyla (250 / 300 / 350 dahil), Fed 25 bp'nin katlarıyla
oynar (ızgaralar masa ayarı). Hesap `tto/quantpath.py`'de, quant iş parçacığında; iki sayfa da TCMB / Fed arasında geçer.

**Girdiler.** TCMB: tarihçenin her gün çalışma kitabının kendi çözücüsüyle hesapladığı toplantı patikası (`mpc_days` /
`mpc_values`: her toplantıdan sonraki TLREF seviyesi ve patikanın başladığı seviye; karar gününde o kararın sonrası);
son hesaplanan gün bugünün patikasıdır (canlıda tarihçe 15 dakikada bir yeniden hesaplar; çözücü motor iş parçacığında
çalışmaz, OIS_MAIN'den okunmaz). Verilen kararlar TLREF fixinginden: toplantı günü → ertesi fixing, ızgaraya
yuvarlanmış; ızgaradan üçte bir adımdan fazla sapan değişim karar sayılmaz (TLREF politika faizinden ayrışmış: ör.
fonlamanın üst banda kaydığı günler). Fed: USD kitabının FOMC tablosu (`SOFR_FOMC!B74:K83`: toplantı ve sonrasındaki
ima O/N; başlangıç stub O/N `B7 + B16/100`; üst bant `B8`), motor iş parçacığında en düşük öncelikle tek kısa okuma
(milisaniyeler). USD'de patikanın geçmişi yoktu: günlük görüntüsü bundan sonra depoda tutulur (`quant.path.usd`; günde
bir kayıt, gün içinde değişince en çok 10 dakikada bir yeniden yazılır; 800 gün; yeni Bloomberg isteği yok) - Fed
kinklerinin z'si, kararları (üst bandın toplantı öncesi / sonrası görüntüsü) ve kalibrasyonu bunlar biriktikçe gelir.

**Toplantı başına.** Adım Δ (ilk toplantıda başlangıç seviyesinden) iki yanındaki ızgara katına bölünür:
Δ = p·alt + (1 − p)·üst (−40 = %80 −50 + %20 0); kümülatif hareket ve fiyatlanan adım sayısı (kümülatif ÷ ızgara).

**Ardışık toplantılar.** İki ima adımıyla tutarlı ayrık patikalar: ızgarada, iki toplantıda yön değiştirmeyen
(monoton), toplamı ima toplamın iki yanındaki ızgara katı olan karar çiftleri (−40 / −60: (−50, −50), (0, −100),
(−100, 0)); böyle bir karışım iki adımı veremiyorsa (piyasa bir dönüş fiyatlıyor) her toplantının kendi iki sonucu.
Her patikanın olasılığı, iki ima adımını veren bütün karışımlar içinde **en az / en çok**: doğrusal kısıtların
çokyüzlüsünün köşeleri (temel olurlu çözümler) tek tek sayılır, tamdır (−40 / −60'ta (−50, −50) %0–80, (0, −100)
%20–60, (−100, 0) %0–40). Her senaryoda toplantı tarihli OIS dönemlerinin receive K/Z'si (bp / DV01): iki toplantı
arası dönem Δ₁ − a₁ (TLREF − 40'tan: +10 / −40 / +60), ikinci toplantıdan sonrası (Δ₁ + Δ₂) − (a₁ + a₂) (üçünde de
TLREF − 100: 0); ilk çiftten sonra bir önceki döneme karşı (önceki toplantıların sonucu dışarıda kalır). Okuma:
"eşit adım (−50/−50) görüşü: 1. dönem 10 bp ucuz → receive".

**Kinkler.** Dönemin seviyesi komşularının ortalamasına göre: kink = C_k − (C_k−1 + C_k+1) ÷ 2 = −(ikinci fark) ÷ 2 (+
ise dönem eşit adımlı patikaya göre ucuz); zikzak: ikinci fark ardışık toplantılarda (en az ızgaranın beşte biri) yön
değiştiriyor. z aynı toplantının önceki günlerdeki kinkine göre (20 günden gösterilir); en az 40 günle sinyal: fly +1
dönem, −½ komşular (ilk toplantıda öncesi stub'tır, neredeyse sabit: dışarıda); taşıma 0 (dönemler ileri başlangıçlı,
tarihleri sabit); senaryo K/Z ve tek cümlelik tez sinyalin notunda.

**Kalibrasyon.** Toplantı sıradakiyken (en çok 20 iş günü önce) büyük adıma (iki ızgara sonucundan sıfırdan uzak
olanı) verilen olasılık ile verilen karar: olasılık kovaları (gün ve toplantı sayısı, ortalama fiyat, gerçekleşen
sıklık, **toplantı sayısıyla** %90 Wilson aralığı - bir toplantının günleri tek sonuçtur) ve toplantı toplantı liste.
Sapma z'si = Σ (sıklık − fiyat) ÷ √Σ p(1 − p), her toplantı bir terim; en az 8 toplantıda girişin üstündeyse sinyal
(sıradaki toplantının dönemi, düşük fiyatlanan sonuca doğru; hedef beklenen fazla, stop öbür sonuçtaki kayıp). Örneklem
küçükken sayfa bunu yazar (kayıtlı veri modunda 1 toplantı).

**TCMB WIRP** (Bloomberg'in WIRP'ü, CME FedWatch gibi; Fed'i yanında). Her toplantının adımı yukarıdaki gibi iki sonuca
bölünür ve adımlar beklenen patika verildiğinde **bağımsız** sayılır: bir toplantı sonrasının dağılımı öncekinin bu
toplantının iki noktalı adımıyla evrişimi (FedWatch'ın ağacı). Toplantı başına: ima faiz, bugüne ve önceki toplantıya
göre değişim (bp), fiyatlanan adım, bu toplantıdaki iki sonuç, indirim / sabit / artırım (toplantı sonrası faizin
bugünküne göre); tıklanan toplantının faiz kovaları (grafik); koşullu olasılık matrisi (toplantı × faiz kovası) ve
**kontrol**: matrisin beklenen değeri ima patikayı verir (fark sütunda; ~1e-13 bp). Patika TLREF (SOFR) cinsindendir;
politika faizine bugünkü fark (politika − TLREF) sabit tutularak çevrilir ve fark gösterilir. Politika faizi: masa
ayarı "Politika faizi, elle" (0 değilse), yoksa masanın Masa sayfasında yazdığı "Politika faizi %" (`MASA!Q155`;
çalışma kitabının "PPK · piyasa ima vs anket" tablosu aynı çevirimi yapar); Fed'de üst bant (`FDTR Index`, USD kitabı
zaten istiyor; kovalar hedef aralık: "375–400"). **Geçmiş:** sıradaki üç toplantının olasılıkları bugün, 1 gün, 1, 2
ve 4 hafta önce, bugünkü faiz kovalarında (aradaki kararlar TLREF / üst bandın ızgaraya yuvarlanmış değişiminden) ve
bu toplantıların ima adımının son 40 iş günlük grafiği. İkili toplantı analiziyle aynı patika ve aynı ayrışım
kullanılır; WIRP'ün bağımsızlık varsayımı toplamı serbest bırakır (−40 / −60'ta −150 %16, −100 %68, −50 %16), ardışık
toplantı analizi toplamı ima toplamın iki yanına sabitler: ikisi farklı soruların cevabıdır.

**Ayarlar** (*Masa ayarları*, herkes için; iki sayfanın altında da): PPK ızgarası 50 bp, FOMC ızgarası 25 bp,
politika faizi (elle) 0 = Masa!Q155. **Bloomberg:** yeni istek yok. Politika faizini canlı almak için önerilen tek
seri TCMB'nin bir hafta vadeli repo faizidir (günde tek değer: maliyeti ihmal edilir); ticker'ı terminalde
doğrulanmadan bağlanmadı.

**Sınırlar ve açık kararlar.** TCMB patikası tarihçenin son hesaplanan günüdür (canlıda en çok 15 dakika eski); TLREF
zaman zaman politika faizinden ayrışır (ızgara dışı değişimler karar sayılmaz, WIRP'ün sabit fark çevirimi de bundan
etkilenir); kayıtlı veri modunda tarihçe dosyanın son ayıdır (kalibrasyon 1 toplantı, kinklerin z'si 20 günle, sinyal
yok) ve USD'nin yalnızca bugünkü görüntüsü vardır. Sorulmadan seçilenler: tutarlı patikalar için monotonluk ve iki
toplam; kinkte komşuların eşit ağırlığı (takvim değil toplantı sırası); kink sinyali için 40 gün, z için 20; kalibrasyon
için 20 iş günü, 8 toplantı ve %90 aralık; WIRP'te 12 toplantı ve %0,05'ten küçük kovaların gizlenmesi (bugünkü kova
hep görünür); fark tabanı patikanın başladığı seviye (karar gününde kararın sonrası); Fed kararında toplantıdan önceki
günün görüntüsü (üst bant o gün değişebilir).

#### Öncü-Takipçi (lead-lag)

Masanın sorusu: *kim önce hareket ediyor?* Aday çiftler: offshore (ICAP) ↔ onshore TLREF OIS (aynı vadeler), USDTRY
swap puanı ↔ OIS (1M / 3M / 6M / 1Y), **VİOP** ön vade ima faizi ↔ OIS 1M / 3M ve offshore 1M / 3M, VİOP geçmişindeki
her kontratın ima faizi ↔ kendi vadesinin OIS'i (VİOP geçmiş sekmesinin "OIS" sütunu), USDTRY / EURTRY spot ↔ OIS ön
ucu (1M / 3M), OIS 1Y ↔ 2Y / 5Y, **DİBS**: DİBS RV listesindeki her sabit kuponlu kâğıt ve bono (TLREF / FRN ve TÜFE'ye
endeksliler dışında, vadesine en az 3 ay kalan) ↔ vadesine en yakın OIS vadesi (getirisi tarihçenin günlük kapanışı;
sayfada masanın adıyla, vadesinden: "05.10.33", "03.02.27 Bono"). VİOP'un günlük çiftleri VİOP geçmiş sayfasının
kapanışlarını ister: canlı modda Bloomberg'den dolar, kayıtlı veri modunda yoktur (VİOP satırı çıkmaz).
Hesap `tto/quantlead.py`'de, quant iş parçacığında; sayfa **Öncü-Takipçi** (üstte grup süzgeci: Tümü / Offshore /
Swap puanı / VİOP / Kur / Eğri / DİBS - üç tabloya da uygulanır, seçim tarayıcıda hatırlanır).

**Günlük.** İki serinin de kapanışı olan günlerin değişimleri (faizlerde bp, kurlarda % log, swap puanında puan; son
250 gün): x_t ile y_t+k'nin çapraz korelasyonu (k = −5 … +5; k > 0 x önde) ve her iki yönde Granger testi (takipçi
kendi gecikmeleriyle, ötekinin gecikmeleri eklenince EKK ve F-testi; gecikme sayısı tek örneklemde AIC ile, en çok
ayardaki kadar). **Kimin önde olduğu çapraz korelasyonların asimetrisinden okunur:** her gecikmede x'in önde olduğu
r(+l) ile y'nin önde olduğu r(−l); yalnızca ortak bir bileşeni paylaşan iki seride (üstünde kendi gürültüsü olan aynı
kotalar, ortalamaya dönen bir spread, kendi kendine ilişkili ortak hareket) r(+l) ≈ r(−l) olur ve Granger testi tek
başına birini "lider" sayar (her biri ötekinin gürültüsünü yeniden kurar); gerçek öncülük bir tarafı güçlendirir.
z = (r(+l) − r(−l)) ÷ √(2 ÷ n), en büyük |z|'nin gecikmesinde, bakılan gecikmeler üzerinden %5 düzeyinde (Bonferroni:
beş gecikmede 2,58); lider |r|'si büyük taraf, ℓ o gecikme; liderin Granger testi de anlamlı olmalı (p < %5). β:
takipçinin liderin bir hareketine ℓ gün içindeki toplam tepkisi (dağıtılmış gecikmede Σ b₀ … b_ℓ, tek katsayı olarak
kestirilir: standart hatası regresyonun kendisinden), R². **Kararlılık:** ℓ'deki asimetri son 60 / 120 / 250 günde aynı
işaretli ve |z| ≥ 2 mi ("3/3"). Tablo: çift, lider → takipçi, gecikme, β ± se, t, Granger F (p), R², kararlılık; aynı
gün birlikte hareket eden ya da öncüsü olmayan çiftler nedenini yazar.

**Sinyal** (aile "Öncü-takipçi"). Lider son ℓ + 1 günde en az k σ oynadıysa (k masa ayarı, varsayılan 2) ve takipçi
yetişmediyse: **beklenen yetişme = β × liderin hareketi − takipçinin aynı günlerdeki hareketi**; σ'sı β'nın standart
hatasından ve takipçinin pencere boyunca kendi gürültüsünden, z = yetişme ÷ σ. Giriş takipçinin şimdiki seviyesi, hedef
seviye + yetişme, stop bir σ öte (takipçinin biriminde: OIS %, kur, puan); taşıma sayılmaz. Takipçi bir DİBS ise
işlem kâğıdın kendisidir (getirisi yükselecekse *Sell*, düşecekse *Buy*); şimdiki getirisi DİBS RV sayfasının basit ya da
bileşik getirisinden, tarihçenin son kapanışına yakın olanı (Bloomberg'in getirisinin kuralı belirsiz; ikisi bu
seviyelerde 300 - 400 bp ayrı, Eğri Adil Değeri sayfası da böyle okur). Öncülük her kararlılık
penceresinde tutmuyorsa sinyal elenir (nedeniyle görünür). Tez tek cümle: kim ne kadar oynadı, takipçiden ne
bekleniyor, z, geçmişte nasıl gitti. **Geçmiş:** aynı kural tarihçede (liderin her k σ hareketi, örneklem içi β):
takipçinin sonra beklenen yöne gitme oranı ve beklenenin ne kadarının geldiği - her çiftin yanında.

**Gün içi.** Analiz hizalı herhangi bir seri çifti üzerinde çalışır (gün ya da bar): quant iş parçacığının canlı
akıştan tuttuğu dakikalık barlarda (`quant_bars.sqlite3`, Gün İçi sayfasınınkiler) aynı tablo bar gecikmeleriyle
yapılır, **15 dakikada bir** yenilenir. Çiftlerin barlarda olmayan anahtarları (VİOP kontratları, DİBS getirileri, OIS /
offshore'un öbür vadeleri) aynı dakikalarda onlarla birlikte yazılır ve **5 gün** tutulur: bir kâğıdınki DİBS RV
sayfasının getirisinden (bonoda basit, kuponluda bileşik), ön vade VİOP kendi kontratının barlarından (vade dönüşünde
sıçrama yok). Bu çiftler (VİOP ↔ offshore, VİOP ↔ aynı vadenin OIS'i, DİBS ↔ OIS ve öbür vadeler) yalnız **5 dakikalık**
barlarla, ilk çiftler (20 günlük barları olanlar) 1 ve 5 dakikalık barlarla taranır. Kayıtlı veri modunda bar
tutulmaz: sayfa "gün içi barlar yok" der. Seyrek kotalanan bir kâğıdın barı dakikalarca aynı kalır: öyle bir kâğıtta
"OIS önde" görünmesi kotanın geç güncellenmesinden de gelebilir.

**Ayarlar:** öncü hareket eşiği k = 2 σ, en çok gecikme 5 gün (*Masa ayarları*). **Bloomberg:** yeni istek yok - günlük
kapanışlar tarihçenin (DİBS RV listesinin getirileri, VİOP geçmiş sayfasının kontratları), barlar dashboard'un zaten
okuduğu canlı değerler. Hesap yükü: günlükte bir çift ~0,04 sn (50 kâğıtla ~2 sn), gün içinde 5 dakikalık barda bir çift
~0,3 sn.
**Sınırlar ve açık kararlar:** Granger ve asimetri tahmin gücüdür, nedensellik değil; kapanış saatleri farklı
piyasalarda (USDTRY, offshore, OIS) bir günlük "öncülük" saat farkından gelebilir; olay geçmişi örneklem içidir (β aynı
veriden), iyimserdir; kayıtlı veri modunda tarihçe bir aydır (çiftler "geçmiş kısa" der). Sentetik iki yıllık
eğrilerde 12 tohum × 14 çiftte 4 yanlış öncü çıktı (hepsi tek tohumda, kur ↔ OIS, kararlılık 2/3: sinyal olmazdı).
Sorulmadan seçilenler: %5 düzeyi ve Bonferroni, kararlılık için |z| ≥ 2 ve her pencerede tutma şartı, en az 120
gözlem (masanın "en az gözlem"i), yetişme σ'sı.

#### VİOP

Masanın sorusu: *VİOP'tan USDTRY vadeli almak (ya da satmak) için doğru zaman mı, bugün ve bu hafta hangi faizden
alınır, kaça gelirse satılır?* Hesap `tto/quantviop.py`'de, quant iş parçacığında; sayfa **VİOP**.

**İma faiz.** VİOP sayfasının formülü: ima TRY % = ((fiyat / spot) · (1 + USD · g/360) − 1) · 360/g, g valörden (T+1,
TRY tatilleri) kontrat vadesine takvim günü; USD geçmişte EK_VIOP'un USSOA / USSOC / USSOF / USSO1 çizgisi, canlıda
VİOP sayfasının kendi BID / ASK satırları (13 ve 25: **alış = ask fiyatının**, **satış = bid fiyatının** ima faizi). Karşısında
aynı vadenin TRY OIS'i (gün cinsinden doğrusal, 365'ten 360'a: VİOP sayfasının satır 77'si gibi) ve offshore (ICAP, olduğu
gibi). **Al** = vadeli almak: ima faiz ne kadar düşükse o kadar iyi (ucuz forward / ucuz TL borçlanma); **Sat** tersi.
Sinyalin paketi vadeli ile spot (yalnız faiz): *Buy VİOP Kas26 (… kontrat) · Sell USDTRY spot*, ana bacak 1.000 $ DV01
(ima faizin 1 bp'si 1.000 $; kontrat 1.000 $).

**Veri (Bloomberg, tarihçenin normal turu).** İşlemdeki ilk 6 kontrat (VİOP sayfasının L1:W1'i) ve onlardan önceki 24
aylık kontrat: kapanış, gün içi en yüksek, en düşük (PX_LAST / PX_HIGH / PX_LOW). **Vadesi geçmiş kontrat bir kez
istenir** (geçmişi tamdır), yeni günleri hiç sorulmaz; önce VİOP sayfasının ticker biçimiyle ("A1X5 Curncy"), o boş
dönerse iki haneli yılla ("A1X25 Curncy"); ikisi de boşsa en erken bir hafta sonra yeniden. VİOP serilerinin ilk
doldurması kendi sırasında, turda 15 seri. USDTRY'nin en yüksek / en düşüğü, USD OIS 1M / 6M / 1Y (3M quant paketinin).
Canlıda ön iki kontratın (işlem) ve USDTRY'nin (bid, ask) son 20 iş gününün **5 dakikalık barları**: her gün bir kez,
gün bittikten sonra (dakikada en çok 4 istek). Bloomberg geçmişi gelene kadar (ilk canlı gün) VİOP geçmiş sayfasının
(EK_VIOP) kendi günleri kullanılır.

**Bloomberg maliyeti** (sahte terminalde ölçüldü: tarihçe `tests/test_quant.py`'nin canlı gününde, barlar
`tests/test_quantviop.py`'de; hit dashboard'un sayacıyla). Tarihçe: VİOP'un 167 serisi (90 kontrat serisi, vadesi geçmiş
24 kontratın iki haneli yıllı 72 ticker'ı, 5 sabit seri) ilk canlı gün **2.361 hit, 29.278 veri noktası**; bunun 167
hit'i ve 24.890 noktası bir kerelik tam aralıklar (kontratlarınki 11 turda), gerisi yeni günler: işlemdeki 6 kontratın
18 serisi ve 5 sabit seri, **turda 23 hit** (~46 nokta), ertesi gün de öyle - günde ~2.200 hit. Sahte terminalde vadesi
geçmiş kontrat yalnız iki haneli yılla bilinir (en pahalı durum: tek haneli biçim boş döner, her seri iki istek);
terminal tek haneli biçimi tanırsa 72 hit eksik. 5 dakikalık barlar: ilk gün **80 istek = 80 hit** (iki kontratın
işlemleri, USDTRY'nin bid ve ask'i × 20 iş günü; dakikada 4, 20 dakikada), 8.160 bar; sonra **günde 4 istek** (biten
gün). VİOP'un hepsi ilk gün ~2.340 hit, sonra günde ~2.210: `--max-hits` 400.000'in ~%0,6'sı.

**Hesaplananlar.**
* **Kontrat tablosu:** VİOP sayfasının on iki kontratının alış / satış / orta ima faizi, aynı vadenin OIS'i, VİOP − OIS
  ve VİOP − offshore farkı (bp), normal fark, adil ima faiz (OIS + farkın penceredeki ortalaması), z, yarı ömür, 1.000 $
  DV01 için kontrat sayısı.
* **Sabit vadeli seriler** (30 / 61 / 91 / 182 gün): her gün bütün kontratlardan (vadesi geçmişler dahil) doğrusal -
  hangi kontrat önde olursa olsun iki yıllık geçmiş. Bir kontratın farkı o vadedeki seriyle izlenir (sabit vadeli seri o
  vadede kısaysa kontratın kendi günleriyle).
* **Sinyal** (aile "VİOP adil değer"): farkın penceredeki ortalamasına uzaklığı (z, OU yarı ömrü, rejim - paketin bütün
  ortalamaya dönüş aileleri gibi): − ise ima faiz ucuz (Buy VİOP / Sell spot), + ise pahalı.
* **Emir seviyeleri, bugün (kalan seans 09:30–18:15) ve bu hafta (Cuma kapanışına):** alış emrinin (ask ima faizin en
  düşüğü) ve satış emrinin (bid ima faizin en yükseği) %90 / 70 / 50 / 30 / 10 olasılıkla görüleceği seviyeler, ima faiz
  ve şimdiki spot ile vadeli fiyatı olarak. Model: sürüklenmeli Brown hareketi, yansıma ilkesiyle (simülasyonla
  doğrulandı); sürüklenme = adil değere çekilme (OU) + vadeye doğru kayma (canlı kontratların ima eğrisinin eğimi) +
  geçmişte belirgin (|t| ≥ 2) ay sonu etkisi (bugünün etkisi seansın kalan payı kadar - haftanın ufkunda da -,
  önündeki günlerinki tam); varyans gün içi barların yarım saatlik profili (geçmişin günlük oynaklığına ölçekli; bar
  yoksa seansa eşit dağıtılır). Günlük oynaklık serinin son 120 günlük değişiminden (geçmişi daha kısa olan seride
  bütün değişimlerinden). Kota inceyken de seviye verilir: tek taraf kotalıysa iki merdiven o taraftan, hiç kota yoksa
  son işlem fiyatının ima faizinden başlar; kendi geçmişi olmayan uzak vade, vadeye kalan günde en yakın kontratın
  oynaklığını kullanır. Seviyelerin altında başlangıcın ve oynaklığın nereden geldiği, seviye yoksa nedeni yazar
  (oynaklık için geçmiş yok, canlı kota ve son işlem yok, seans kapalı).
* **Kalibrasyon:** geçmişin her kapanışında sonraki 5 kapanış için verilen seviyeler, gelenlere karşı (1 ve 3 aylık
  sabit vade; kapanışların en düşüğü için Broadie-Glasserman düzeltmesi): isabet oranları ve onları olasılıklara en çok
  yaklaştıran σ çarpanı c - canlı seviyeler c ile verilir. Gün içi: barlı günlerde 11:00'de verilen seviyeler, günün
  kalanına karşı.
* **Takvim:** 1 aylık sabit vadenin VİOP − OIS farkının günlük değişimi ay sonuna kalan iş gününe göre (−5 … +3, bütün
  aylar ve çeyrek sonları) ve haftanın gününe göre (ortalama, t, n); vadeye kalan güne göre ima faizin günlük oynaklığı.
* **Gün içi profil** (barlar): yarım saatlik dilimde barın oynaklığı ve ima faizin günün ortalamasından uzaklığı (−: o
  saatlerde genelde düşük - alış için); son günlerin en düşük / en yüksek ima faizi ve saati kendi tablosunda.
* **Günlük aralık:** kontratların ve USDTRY'nin en yüksek − en düşük fiyatı (20 gün).

**Ayarlar:** adil spread ve oynaklık penceresi 120 gün (*Masa ayarları*). **Sınırlar:** model Brown hareketidir; şişman
kuyruklar kalibrasyonla (c) kısmen karşılanır. Gün içi profil 5 dakikalık işlem barlarındandır: kontrat seyrek işlem
görürse bar boş kalır. Vadeye birkaç gün kala küçük bir fiyat hareketi ima faizi çok oynatır (tabloda); seviyeler o
günlerde geniştir. Kayıtlı veri modunda VİOP geçmişi ve bar yoktur: kontratlar canlı kotalarıyla görünür, seviyeler
canlıda gelir. Vadesi geçmiş kontratların Bloomberg ticker'ı terminalde doğrulanmalı (ilk canlı günde sayfanın *Veri*
tablosu hangi kontratın geldiğini gösterir).

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
| — (formül dışı) gün içi barlar | `IntradayBarRequest`: istek başına tek menkul, **1 hit** (aşağıda **Gün içi barlar**) |

Bağlantı **Desktop API** içindir (terminalin açık olduğu makinede `localhost:8194`); B-PIPE / SAPI gibi sunucu
ürünlerinin yetkilendirme adımı yazılmadı. Abonelikle hiç değer gelmeyen fiyat alanları (ör. işlem görmeyen bir
kağıt) `--price-poll` (120 sn) sonra sorguyla istenir; yanıt değişmedikçe aralık ikiye katlanarak 30 dakikaya
(hiç değeri olmayan alanlarda 1 saate) kadar uzar, değer değişince yeniden 120 sn'ye iner. Bloomberg'in tanımadığı
bir ticker (`#N/A Invalid Security`) o gün bir daha sorulmaz, aboneliği de açılmaz; gün değişince bir kez yeniden
sorulur (dün olmayan bir vade bugün var olabilir). Böylece Borsa Swap sayfasının kotası olmayan yüzlerce vadesi ne
günlük veri limitini tüketir ne de terminali boş aboneliklerle uğraştırır. Kota büyüklükleri (`BID_SIZE` /
`ASK_SIZE`) aboneliği akan bir menkulde hiç yeniden sorulmaz: akışta büyüklük yoksa emir yoktur, yeni emir tick olarak
gelir (sorulsaydı piyasa kapalıyken her kâğıt saatte bir istek ederdi).

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

**Tarihçe** (gün sonu matrisi, PPK fiyatlama geçmişi, quant serileri) için ayrıca `HistoricalDataRequest`
gönderilir: ilk açılışta ~120 ticker için bir yıllık günlük kapanış (alan başına 50 ticker'lık isteklerle; quant
paketinin serileri iki yıl, turda 40'ar), sonra 15 dakikada bir her serinin yalnızca son kapanışından sonrası. Bir
serinin tüm aralığı günde en çok bir kez istenir; Bloomberg'in geçmişi kısaysa verdiği en eski gün saklanır
(`hist.fetch`) ve o aralık bir daha istenmez. Bunlar da günlük istek sayacına yazılır: tur başına seri sayısı kadar
(security × alan), 15 dakikalık turlarla günde en çok ~194 × 97 ≈ 18.800 (`--max-hits` 400.000'in ~%5'i); sahte
terminalle ölçülen bir gün `tests/test_quant.py`'de. Geçmişi hiç olmayan bir ticker günde bir kez sorulur; "Şimdi
güncelle" hemen yeniden dener. (FX vol sayfalarının tarihçesi `tto/fx.py`'nin kendi kuralıyla gelir: aşağıda.)

**Gün içi barlar** (formül dışı; quant sayfaları için, ör. VİOP USDTRY kontratlarının ve `USDTRY Curncy`'nin
5 dakikalık barları) `IntradayBarRequest` ile istenir: `provider.intraday_bars(menkul, başlangıç, bitiş, interval=5,
event="TRADE")`. Bloomberg bu istekte tek menkul alır; bu yüzden **menkul başına bir istek, sayaçta 1 hit**, kaç bar
dönerse dönsün (20 iş gününün 5 dakikalık barları ~2.000 bar, yine 1 hit). Saatler İstanbul saatiyle verilir ve
döner (`YYYY-MM-DD SS:DD`, bitiş hariç), Bloomberg'e UTC olarak gider: Türkiye 2016'dan beri yıl boyu UTC+3, fark
sabittir. Uzun bir aralığın yanıtı parça parça gelir (`PARTIAL_RESPONSE`) ve birleştirilir; hiçbir şey saklanmaz,
her çağrı yeniden sorar. Bloomberg'in tanımadığı menkul boş liste döner ve rozetin hatasında görünür. Günlük sayaç
`--max-hits`'e ulaşmışsa istek hiç gönderilmez; yanıt zamanında gelmezse ya da Bloomberg limit / zaman aşımı derse
sonuç `None`dır ("şimdi sorulamadı"; boş liste o günlerde bar yokmuş gibi okunurdu). Kayıtlı veriyle (replay) bar
yoktur (`None`). Oturum yardımcı süreçteyse çağrı oraya iletilir, sayım ve limit orada tutulur. Günlük maliyeti
çağıranın sıklığı belirler: üç serinin 20 günlük ilk çekimi 3 hit, sonrası yalnızca eksik günler (her çağrı 1
hit). Bloomberg'in kendi günlük limitinde gün içi bar isteklerini nasıl saydığı (istek mi, bar mı) burada
doğrulanamadı; dashboard'un sayacı istek başına 1 sayar.

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

## Operasyon

Dashboard'un kendisinin nasıl olduğunu söyleyen parçalar (`tto/ops.py`): günlük dosyası, ekrandaki verinin tazeliği.

### Günlük dosyası ve son hata

`python -m tto` olanları **`data/logs/tto.log`** dosyasına yazar; dosya 5 MB olunca yenisine geçilir, eski beş dosya
(`tto.log.1` … `tto.log.5`) saklanır. Klasör `--log-dir` (ya da `TTO_LOG_DIR`) ile değişir; varsayılan, kurulumun veri
klasörüdür: tek dosyalık kurulum `data/`'yı korur, git deposu ise `data/`'yı hiç almaz. Açılışta konsol dosyanın
yerini yazar (`Günlük: …`).

Yazılanlar: piyasa, izleme / alarm ve tarihçe döngülerinin atlatıp sürdüğü hatalar (önceden piyasa ve izleme
döngüleri bunları hiçbir yere yazmadan yutuyordu), beklenmeyen sunucu hataları (tarayıcıya kısa "sunucu hatası"
gider, ayrıntısı günlüğe), Bloomberg yardımcı sürecinin kapanması, sessiz kalması, yeniden başlatılması. Aynı hata
ilk seferinde ayrıntısıyla (traceback) yazılır, sonra dakikada en çok bir kez "son kayıttan beri N kez daha" diye:
saniyede bir tekrarlayan bir hata diski doldurmaz.

Rozete tıklayınca açılan pencere (ve `/api/status` → `ops`) ayrıca **hesap motoru kuyruğunu** (bekleyen iş, şu anki
işin kaç saniyedir sürdüğü), **son hatayı** (nerede, ne, ne zaman, toplam kaç kez) ve günlük dosyasının yerini gösterir.

### Veri tazeliği: "BAYAT VERİ"

Önceden rozet yalnızca Bloomberg yardımcı süreci kapanınca değişirdi; süreç takılıp kalsa ya da oturum açık durup
tick gelmese ekrandaki son fiyatlar "CANLI" görünmeye devam ederdi. Şimdi:

* Yardımcı süreç saniyede en az bir kez haber verir (değişen yoksa boş paketle). **10 sn** ses gelmezse veri bayattır.
* **Piyasa saatinde** - masanın iş günleri (hafta içi, Motor sayfasındaki tatil listesinde olmayan günler),
  varsayılan 09:00–18:00 - hiçbir abonelikten **120 sn** tick gelmezse de veri bayattır (açılıştan beri hiç tick
  gelmediyse de).
* Rozet kırmızıya döner ve ışığı yanıp söner: **BAYAT VERİ · 14:32:05 itibarıyla** (son tick'in, o yoksa sürecin
  son sesinin saati); ipucunda ve pencerede nedeni yazar.
* Sessiz kalan yardımcı süreç **60 sn** sonra (`--bbg-silent-restart N`, 0 = hiç) sonlandırılıp yenisi başlatılır -
  yalnızca piyasa saatinde, günde en çok **3 kez** ve her seferinde bir öncekinin iki katı sessizlik beklenerek (60,
  120, 240 sn). Her yeni süreç Bloomberg'den her şeyi yeniden ister; bu sınırlar terminalin günlük veri limitinin bir
  döngüyle tükenmesini önler. Sınır dolunca (ya da piyasa saati dışında) yeniden başlatılmaz: rozet bayat kalır,
  pencere nedenini ve "dashboard'u yeniden başlatın"ı yazar. Kapanan (ölen) sürecin ayrı sınırı aynen geçerlidir:
  art arda 5 kısa ömürlü süreçten sonra durur.
* Piyasa saatlerini ve "kaç saniye tick gelmezse bayat"ı yöneticiler İzleme · Alarmlar → Masa alarmları → Ayarlar'dan
  değiştirir; veri piyasa saatinde 3 dakika bayat kalırsa herkese masa alarmı çalar (İzleme · Alarmlar → Masa alarmları).

### Veritabanı: tutarlı yazma, açılış denetimi, günlük yedek

Her şey tek dosyada: `data/tto.db` (SQLite, WAL).

* **Ya hep ya hiç.** Birden çok adımlı yazmalar tek işlemdir: bir paketin (spread, fly, FRA) bacaklarının girilmesi
  ve silinmesi, Broker Chat'e yapıştırılan bütün satırlar, bir hesabın oturumlarıyla birlikte silinmesi. Ortada bir
  adım yazılamazsa (disk dolu, G/Ç hatası) hiçbiri kalmaz: yarım silinmiş paket ya da yarısı kaydedilmiş chat olmaz.
* **Her kayıt diske yazılmadan dönmez** (`synchronous=FULL`). Önceden (`NORMAL`) son kayıtlar bir sonraki birleştirmeye
  kadar yalnızca işletim sisteminin önbelleğindeydi: elektrik kesilirse ekranda "girildi" görünen bir işlem
  kaybolabilirdi. Masa bilgisayarında dashboard'unkine benzer kayıtlarla ölçüldü: kayıt başına ~0,6–1,1 ms (en kötü
  %1'de ~4 ms), önceden ~0,03 ms. Dashboard saniyede en fazla birkaç kayıt yaptığından bütün tablolar için açıldı.
* **Açılışta denetim.** Her açılışta `PRAGMA quick_check` çalışır (masa bilgisayarında 48 MB'lık bir dosyada 0,2 sn).
  Dosya sağlam değilse konsolda `UYARI: VERİTABANI DENETİMİ BAŞARISIZ …` (en son yedeğin yeriyle) yazar, günlüğe
  geçer, her kullanıcının ekranına bir kez kırmızı uyarı çıkar ve rozetin penceresi "Veritabanı denetimi: BAŞARISIZ"
  der; dashboard okuyabildiğiyle çalışmaya devam eder. Dosya hiç açılamıyorsa dashboard başlamaz ve en son yedeği söyler.
* **Günlük yedek.** Her gün **17:30**'da (masanın günü bitince, ofis bilgisayarı henüz açıkken; `--backup-time`)
  veritabanının çevrimiçi kopyası (SQLite'ın yedekleme arayüzü: dashboard yazmaya devam ederken tutarlı bir an; 48 MB'lık
  dosyada ~0,5 sn) **`data/backups/tto-YYYY-AA-GG.db`** olarak alınır (`--backup-dir` ya da `TTO_BACKUP_DIR`). Kopya,
  adını almadan önce denetlenir; tek dosyadır (yanında `-wal` yoktur). En yeni **30** yedek kalır, eskisi silinir;
  klasördeki başka dosyalara dokunulmaz. O saatte dashboard çalışmıyorduysa, açıldıktan 5 dakika sonra kaçırdığı yedeği
  alır (bir günden eski yedek varsa). Alınamayan yedek günlüğe yazılır, rozetin penceresinde kırmızı görünür ve 30
  dakika sonra yeniden denenir. Son yedeğin saati, boyutu, sayısı ve klasörü rozetin penceresindedir (yöneticilere).
* **İkinci kopya.** Her günün yedeği aynı adla ikinci bir klasöre de kopyalanır - başka bir sürücü ya da ofis ağındaki
  bir paylaşım (`--backup-copy-dir` ya da `TTO_BACKUP_COPY_DIR`; `""` verilirse ikinci kopya alınmaz); orada da en yeni
  **30** kalır, klasördeki başka dosyalara dokunulmaz. Klasör yoksa açılır. Sürücü / paylaşım yoksa ya da klasöre
  yazılamıyorsa yedeğin kendisi yine alınır: hata günlüğe **bir kez** yazılır (kopya yeniden alınana kadar
  tekrarlanmaz) ve rozetin penceresinde "İkinci kopya: ALINAMADI" görünür; **iki gün üst üste** alınamazsa veritabanı
  sistem alarmı çalar (sayı yeniden başlatmada da korunur). Kopya yeniden alınınca alarm kendiliğinden kapanır.
  Varsayılanı **`D:\tto-yedek`**'tir - yalnızca **kurulu dashboard**'da (git deposu olmayan, kendi `data` klasörüyle
  çalışan) ve **bilgisayarda D: sürücüsü varsa**. D: sürücüsü olmayan bir ofis bilgisayarında ikinci kopya alınmaz, bunun
  için alarm da çalmaz; Yedekleme sayfası "İkinci kopya seçilmedi" der ve bir klasör seçmeyi önerir. Bir git klonu
  (geliştirici, testler) ya da başka bir veri klasörüyle açılan dashboard, istenmedikçe ikinci kopya almaz - masanın
  kopyalarının üzerine yazmasın diye.
* **Saati ve klasörleri yöneticiler seçer** (*Araçlar → Yedekleme*, yalnızca yöneticiler): yedeğin saati, yedek klasörü
  ve ikinci kopya klasörü (boş = ikinci kopya yok). Seçim veritabanında saklanır ve **komut satırının / ortam
  değişkenlerinin, onlar da varsayılanların önündedir**; sayfa her ayarın şu an nereden geldiğini (yönetici seçimi /
  komut satırı / varsayılan) ve seçim olmasa ne geçerli olacağını gösterir, *Varsayılanlara dön* seçimi siler. Yeniden
  başlatma gerekmez: yedek döngüsü seçimi her bakışta (15 sn) yeniden okur. Klasör değişince eski yedekler taşınmaz,
  eski klasörde kalır; her klasör kendi en yeni 30'unu tutar; yeni yedek klasöründe henüz yedek yoksa ilk yedek hemen
  alınır. Klasör kaydedilmeden önce denetlenir: **tam yol** olmalı (yerel sürücü, eşlenmiş sürücü ya da ofis ağındaki
  `\\sunucu\paylaşım\…`); yoksa açılır, içine küçük bir deneme dosyası yazılıp silinir - açılamayan ya da yazılamayan
  klasör reddedilir. **Bulut eşitleme klasörleri reddedilir** - OneDrive (`OneDrive`, `OneDriveCommercial`,
  `OneDriveConsumer` ortam değişkenlerinin gösterdiği yer de), Dropbox, Google Drive, iCloud Drive, Box: veritabanında
  Bloomberg verisi ve şifre özetleri var, masanın kuralı gereği bunlar hiçbir dış hizmete gitmez. Hatalar Türkçe,
  alanın yanında söylenir. **Şimdi yedek al** o anki ayarlarla bir yedek alır ve sonucunu gösterir (dosya, boyutu,
  ikinci kopyanın yazılıp yazılmadığı); sayfa her klasörün en yeni yedeklerini listeler. Kullanıcılar bu ayarlara
  ulaşamaz (403) ve klasörlerin yerini görmez: rozetin penceresi onlara klasör göstermez, veritabanı alarmının metni
  klasör adı içermez.
* **Seçilen klasöre yazılamazsa** (ağ paylaşımı kapalı, sürücü yok) gün yedeksiz kalmaz: yedek dashboard'un kendi
  klasörüne (`data\backups`) alınır, gün yedeklenmiş sayılır (yarım saatte bir yeniden tam yedek alınmaz), ikinci kopya
  - seçilmişse ve yazılabiliyorsa - bu dosyadan yine alınır ve veritabanı alarmı çalar ("seçilen yedek klasörüne
  yazılamadı – bugünkü yedek dashboard'un kendi klasörüne (data\backups) alındı"; birkaç gün sürerse gün sayısıyla).
  Seçilen klasör yarım saatte bir yeniden denenir; yazılabilir olunca bekleyen günlerin dosyaları oraya kopyalanır ve
  alarm kapanır - seçilen klasöre sonradan doğrudan yedek alınırsa (ör. *Şimdi yedek al*) bekleyenler de hemen gider.
  O gün sonradan seçilen klasöre kendi yedeği alınmışsa bir şey kopyalanmaz (yenisinin üzerine eskisi yazılmaz).
  Seçilen klasör `data\backups`'ın kendisiyse geri çekilecek yer yoktur: yedek alınamadı alarmı çalar ve yarım saatte bir
  yeniden denenir. Yedekleme sayfası ve rozetin penceresi (yöneticilere) bugünkü yedeğin kendi klasöre alındığını ve
  seçilen klasöre ulaşıp ulaşmadığını söyler; klasör değiştirilirse eski klasörü bekleyen günler unutulur (dosyaları
  `data\backups`'ta kalır).
* **Bilgisayarın dışına kopya alınmaz** (masanın kararı): veritabanında Bloomberg geçmişi, şifre özetleri ve işlemler
  var; yedekler GitHub'a, bir bulut hizmetine ya da başka bir dış yere gitmez. Kopyalar masa bilgisayarının kendi
  disklerinde ya da ofis ağındaki bir paylaşımdadır.

**Yedekten dönme.** Dashboard'u kapatın, sonra:

```bash
python -m tto yedekten-don                                   # yedekleri ve ikinci kopyaları listeler (en yenisi önce)
python -m tto yedekten-don data\backups\tto-2026-11-14.db    # o yedeğe döner
python -m tto yedekten-don D:\tto-yedek\tto-2026-11-14.db     # ... ya da ikinci kopyasına
python -m tto yedekten-don tto-2026-11-14.db                 # yalnızca adı: önce yedek klasöründe, sonra ikinci kopyalarda aranır
```

Komut, yöneticilerin Yedekleme sayfasında seçtiği klasörleri veritabanından okur: önce onlara, sonra komut satırının /
varsayılanın klasörlerine ve dashboard'un kendi klasörüne (`data\backups`) bakar (klasör değişmeden önce alınan
yedekler eski klasörde, seçilen klasöre yazılamayan günler `data\backups`'ta durur).

Yedek önce denetlenir (sağlam bir SQLite dosyası ve bu dashboard'un tabloları) - hangi klasörden gelirse gelsin; şimdiki veritabanı silinmez, yanına
`tto.db.onceki-YYYYAAGG-SSDDss` adıyla (WAL dosyalarıyla birlikte) taşınır. Dashboard açıkken komut veritabanını yerinden
alamaz ve hiçbir şeyi değiştirmeden durur (Windows). Yedeğin alındığı andan sonraki girişler (işlemler, chat, RET …)
geri dönülen veritabanında yoktur.

---

## Canlıya geçmeden önce

* **İlk yönetici:** bu sürüme geçince ilk iş, dashboard'un çalıştığı bilgisayarda sayfayı açıp yönetici hesabını
  oluşturmaktır (ya da `python -m tto yonetici <isim>`); sonra masadakiler aynı isimleriyle hesap ister, yönetici
  *Araçlar → Kullanıcılar*'dan onaylar (bkz. [Giriş ve kullanıcılar](#giriş-ve-kullanıcılar)).
* **Manuel spot:** kaydedilmiş dosyadaki "Manuel SP" değerleri (49,997 / 49,9975) artık gelmez: spot Bloomberg'dendir
  (üst şeritte *Spot kaynağı: BBG*). Bloomberg'den gelmeyen bir spot için üst şeritteki **Spot kaynağı ✎** kutusuna
  tıklayıp bid / ask yazın ("Bloomberg'e dön" ya da iki hücreyi silmek geri döndürür); hücreler ortak girdidir, bir
  kişinin yapması yeter. Hücrelerin kendisi VİOP sayfasının ve Masa sayfasının en üstündeki "Manuel spot" tablosundadır.
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
* **Girdiye formül**: veritabanında formül ve girildiği andaki değeri durur; canlı izlenen değer her değişimde yeniden
  yazılmaz (açılışta ve kullanıcının hesabı kurulunca yeniden hesaplanır - önceki sürüm saklanan değeri okur). Bir
  seçime tek formül yapıştırılınca her hücreye aynı metin gider (Excel'in doldururken yaptığı gibi göreli başvurular
  kaydırılmaz). Ok tuşlarıyla işaretleme yok (fareyle tık ve sürükleme var). Bloomberg isteğine giren hücrelerde "canlı"
  formül piyasa verisi ve `NOW()` okuyandır; `TODAY()` günde bir kez yeni istek doğurabilir. Yönetici yetkisi
  Kullanıcılar sayfasından değişince kişisel formüller hemen yeni rolle hesaplanır; komut satırından (`python -m tto
  yonetici`) değişince formülün okuduğu bir şey değiştiğinde.
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
  olan işlemin yalnızca günü görünür). Ek kaynak (`BGN`) her kâğıt için fiyat vermeyebilir. `BID_SIZE` / `ASK_SIZE`
  15.11.2026'da (pazar) sınandı: ISL kaynaklarında alan var ama değeri yok, abonelikte bid / ask hiç gelmiyor; BGN'de
  alan uygulanamaz. Piyasa açıkken büyüklüklerin akışı ve kapanışta ne zaman boşaldıkları henüz görülmedi (kapanışta
  boşalmazsa son kotalar ertesi güne kadar canlı görünebilir).
* **"Gerçekleşen"** (yapılan toplantılarda) TLREF fixingindeki değişimdir, politika faizi kararı değil; TLREF
  politika faizinden ayrıştığı dönemlerde (ör. fonlamanın üst banda kaydığı günler) ikisi farklıdır.
* **FX olasılıkları risk-nötrdür** (forward ölçüsü): opsiyon piyasasının fiyatladığı dağılımdır, gerçek dünya tahmini
  değildir; USDTRY'de forward'ın faiz farkı merkezi yukarı taşır. Delta / ATM / prim kuralları tablodaki piyasa
  alışkanlıklarıdır (Bloomberg OVDV ayarlarıyla karşılaştırılmadı); BGN'nin orta kotaları kendi aralarında arbitrajsız
  olmayabilir (SVI en yakın arbitrajsız smile'ı alır, sapma "Uyum" sütununda). G10 teslim tarihleri yalnız hafta sonunu
  atlar (ülke tatilleri yok; masanın listesi olan TRY / USD / EUR'dan oluşan USDTRY, EURTRY ve EURUSD dışında); vade
  süresi `gün/365`. Kayıtlı veri modunda FX kotası ve tarihçesi yoktur (kotalar elle yazılabilir). Gerçekleşen vol kapanışlardan, işlem günleriyle hesaplanır.
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

## Hız ve dayanıklılık

Masada 5–10 kişi aynı anda, tek bir hesaplama iş parçacığıyla çalışır. Bunun için yapılanlar (ölçümler kayıtlı
veriyle, masa bilgisayarında):

* **Uzun zincirler tek seferde.** Hesaplama iş parçacığı 255 MiB yığınla çalışır (Windows 256 MiB'ı reddeder: eski
  sürüm farkında olmadan varsayılan ~2 MB yığınla çalışıyordu) ve 1000 hücre derinliğe kadar zinciri bölmeden
  hesaplar; başka iş parçacıkları 90'da kalır. Üst şerit soğuk başlangıçta 9,8 s → 1,4 s; bütün sayfalar (yardımcı
  tablolar dahil) 32 s → 13 s. `tools/depth_check.py` başlığı ve 18 sayfanın hepsini iki derinlikte de hesaplayıp
  karşılaştırır: birebir aynı.
* **Taşma `#NUM!`.** `1E308*10` gibi bir taşma Excel'deki gibi `#NUM!` olur; JSON'a yazılamayan bir sayı (sonsuz,
  NaN) sayfayı 500 hatasıyla düşürmez, `null` gider.
* **Tik başına geçersizleştirme maske başına.** Saklanan ~127 000 değer ~4 900 farklı bağımlılık maskesini paylaşır;
  bir tik her değeri değil her maskeyi bir kez sınar: hesap başına 21,7 ms → 1,9 ms.
* **Girdi tanımlamak kimsenin değerini silmez.** Kaydedilmiş elle değerler ve senaryo hücreleri açılışta, hiçbir şey
  hesaplanmadan, tek seferde tanımlanır (açılıştaki sıfırlama 666 → 9). Çalışırken bir sabitin üzerine yazılınca
  (Elle değer) formüllerin statik başvurularından (`tto/xl/refs.py`) o hücreden etkilenen değerler bulunur ve
  işaretlenir; artık herkesin bütün değerleri silinip yeniden hesaplanmaz. OFFSET / INDIRECT olan bir dosyada ya da
  bir dizi formülünün yazdığı bir hücrede eski yol (her şey yeniden) geçerlidir. Başvuru dizini açılıştan 45 s sonra
  arka planda kurulur (~10 s, dört kitap için ~45 MB).
* **Sunucu tek bir uzun hesapta donmaz.** Sayfa ve şerit istekleri hesaplama iş parçacığını bir iş parçacığı tutmadan
  bekler; hesap bekleyen diğer istekler en çok 12 iş parçacığı alır (statik dosyalar ve giriş hep cevap verir). Aynı
  sayfa aynı anda iki kez istenirse bir kez hesaplanır. Sıra önceliklidir: yazılan girdi ve piyasa tiki → şerit →
  sayfa → arka plan (izleme listesi, ısınma). Oturum bilgisi 60 s bellekte tutulur (çıkışta, şifre değişince ve her
  yönetici işleminde hemen unutulur); `/api/history/status` artık her sorguda bütün kapanışları taramaz.
* **Sayfalar hesap başına saklanır, yalnızca değişen panel yeniden yapılır.** Kendi girdisi olmayan herkes aynı
  sayfayı paylaşır; bir panel okuduğu hücrelerin maskelerini hatırlar, yeni bir nesilde yalnızca okuduğu bir şey
  değiştiyse yeniden yapılır. Tarayıcı yalnızca açık sekmenin panellerini, `since` ile ister ("değişmedi" cevabı
  boş gelir); başka bir sekme açılınca paneller güncellenene kadar soluk görünür (eski bir sayı okunmasın), yazılan
  bir hücrenin tablosu yazarken yeniden kurulmaz. Arka plandaki tarayıcı sekmesi hiç istemez, öne gelince bir kez
  ister. Sayfalara yeni nesil saniyede en çok bir kez bildirilir.
* **Bir tarayıcıya bir canlı akış.** Sekmeler akışı paylaşır (BroadcastChannel + localStorage); 7. sekme artık
  bağlantı beklemez. `/api/status` açık akış sayısını gösterir.
* **Kendi girdisi olan kullanıcı.** Şeridi, sayfaları ve izleme listesi piyasaya en çok 5 s'de bir yeniden hesaplanır
  (`--private-refresh`; kendi değişikliği ve ortak bir girdi hemen görünür). Bağlı olmayan kullanıcının izleme listesi
  herkesin hesabından okunur (kendi girdisine bağlı kalem o sırada okunmaz). 30 dakikadır görünmeyen kullanıcının
  hesabı bırakılır, dönünce yeniden kurulur (`--idle-minutes`).
* **Isınma.** Açılışta, gün dönünce ve toplantı takvimi değişince şerit ve bütün sayfalar en düşük öncelikle, sayfa
  sayfa önceden hesaplanır: sabahın ilk kullanıcısı beklemez.
* **Bloomberg veri limiti yeniden başlatmada harcanmaz.** Günün veri isteği sayacı ve günün referans cevapları
  (kotalar değil) veritabanında tutulur; aynı gün yeniden başlayan dashboard bunları yeniden sormaz, vadesi
  gelince sorar. FX tarihçesinin "bugün çekildi" bilgisi de saklanır.

## Testler

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest tests
```

Bloomberg ve ağ gerekmez (~8–11 dk; masa bilgisayarında ~35 dk). 1467 test (gerçek `blpapi` kuruluysa 7 tane daha):

| Dosya | Kapsam |
|---|---|
| `test_xl_functions.py`, `test_xl_engine.py`, `test_numfmt.py` | Excel semantiği (operatörler, yuvarlama, tarih - bayram, 1 Ocak ve hafta sonu tatilli `WORKDAY` / `NETWORKDAYS`, iki listenin yan yana sütunlarından **ortak takvim** (boş hücre, 0, aynı gün iki kez, sırasız liste, metin tarih; ad ya da boş metin `#VALUE!`), ay sonu ve 29 Şubat'ta `EDATE` / `EOMONTH`, `YEARFRAC` -, metin, arama, koşullu toplamlar, matris, `LET`, `FILTER` ve taşma / `#SPILL!`, `AGGREGATE`, sıfıra yapıştırma), bağımlılık takibi, kullanıcı katmanları (aynı gruptaki girdilerden birini değiştiren kullanıcının diğerlerini dosyadaki değeriyle görmesi dahil), **sonradan elle değer yazılan formülün hiçbir hesaplanmış değeri silmemesi** (yalnız bağımlıları, yalnız yazan kullanıcı için; yukarıda kendi değeri olan kullanıcının değerleri dahil), **sonradan yazılan sabitin formül başvurularıyla izlenmesi** (hücre, aralık, tanımlı isim, `A1:INDEX(..)` kutusu; dizi formülünün alanında eski yol), **bir hücre grubunun okuduğu girdiler** (`RefIndex.upstream`: hücre, aralık, tanımlı isim, `A1:INDEX(..)` kutusu, taşma alanı; zincirin girdide bitmesi, 3 000 hücrelik zincirin özyinelemesiz izlenmesi), hiçbir şey hesaplanmadan tanımlanan girdinin sıfırlama yapmaması, taşmanın `#NUM!` olması, büyük yığınlı iş parçacığında uzun zincirin bölünmeden hesaplanması (değerler ve maskeler aynı), **rastgele geçersizleştirme testi** (her adımda her kullanıcının her hücresi sıfırdan hesapla aynı), sayı biçimleri |
| `test_parity.py` | Excel'in kayıtlı değerleriyle parite (sayfa bazında eşikler) |
| `test_reference.py` | LibreOffice'in baştan hesapladığı değerlerle karşılaştırma (`tests/data/lo_*.json.gz`) |
| `test_forward.py` | Forward: bağımsız kapalı formül, Excel'in kayıtlı değerleri, işlem girişindeki fiyatlamanın sayfayla aynılığı |
| `test_blotter.py` | Outright / spread / fly / FRA bacakları, maliyet, ortak işlem defteri, forward'ların O/N karşılığı, Excel özet tabloları, **DV01** (forward: sayfadaki "Forward DV01" bloğuyla aynı sayılar, iki yön, tutarsız fiyat; OIS net / brüt; tahvil: DİBS RV tablosundan, tabloda olmayan kâğıt), işlemle saklanması ve risk özeti, DV01'siz eski kayıt, **tarih aralığı** (günler, toplam maliyet / risk, uçların sırası) ve aralığın tek dosya olarak indirilmesi; **Chat ↔ Günlük İşlemler** (masanın chat işlemleri: ±15 dk içinde aynı enstrüman / seviye "girildi", "İşlem gir" notuyla saatinden bağımsız eşleşme, başka seviye "girilmedi", broker satırının ve cross currency'nin sayılmaması, durumdaki ve sayfadaki sayı, elle eşleştirme / yok sayma / yanlış eşleşme / geri alma, silinen kaydın satırı geri getirmesi, hatalı istekler) |
| `test_brokerchat.py` | Broker chat: masanın gönderdiği örnek satırlar ve telefon ekranındaki chat satır satır (saat, gönderen, enstrüman, bid / ask, işlem, ref, OCO, cross-currency), enstrüman türleri ("v"siz spread, fly, FRA yazımları, forward), iki tarafın ve tek tarafın her yazımı, büyük rakamın tamamlanması (öbür taraf, önceki seviye, eğri, belirsizlik), bir satırda birkaç kota, kota olmayan satırlar, mesaj düzenleri (saat başta / sonda / alt satırda, isim, tarih), tahta, eğriyle karşılaştırma; saklama (önizleme, ikinci kez yapıştırma, saatsiz satır, o saate kadarki referans, fiyatsız "taken"), tahtanın model seviyeleri (outright / spread / fly / FRA, kişisel senaryo), **switch'in ekranla değerlemesi** (modeli ekrandaki switch, ASW eğrisine göre yeri, bacak bacak yazılmış switch'in seviyesinin bacakların ekranda getiriye çevrilen fiyatlarından, TLREF switch'inde fiyat farkı, tahtadaki satırı, DİBS sayfalarına girmemesi), **MPC tarihli OIS** (30 yazılış: ay adı İngilizce / Türkçe, yıllı, `mpc1` / `1st` / `next`, `dec/jan`, `dec jan`, `mpc1/2`, iki yanı ayrı yazılmış; hangi toplantı - ayın ilk toplantısı, karardan sonra süren dönem, karar günü MPC1 -, birkaç dönem, spot'tan, işlem / ref / ilgi, kısa seviye, bir satırda iki MPC kotası, boyutun vade sayılmaması, adım kotasının / tarihin / toplantısız satırın metin kalması, takvimde olmayan toplantı, tahtada tek satır; servisle: modelin "MPC OIS" tablosunun D sütunu ve MPC formunun piyasa seviyesiyle aynılığı, kısa seviyenin modelden tamamlanması, ima PPK adımı ve bootstrap'ın adımı, tahta sırası ve son işlemin adımı), **chat ↔ Günlük İşlemler eşleştirmesi** (kayıtların paket paket enstrüman / seviyesi; aynı enstrüman ve seviye ±15 dk, iki satıra tek kayıt - saati yakın olan, "İşlem gir" notuyla iki saat sonra, başka seviye, formu olmayan ürün, MPC / FX swap / DİBS, elle eşleştirme, yok sayma, yanlış eşleşme, silinmiş kaydın yeniden aranması), **en iyi fiyat broker broker** (sonra söylenen kötü kotanın iyisini örtmemesi, broker adı ve saati, geri çekilen yalnız o broker'ın, işlemle o seviyede ve daha iyi olanların ve oco mesajının öbür kotasının inmesi, seviyesiz işlem, bizim kotamızın ayrı kalması, bayat sınırı - yaş, en iyi sayılmama, daha taze kötü kotanın en iyi olması, ileri yazılmış saatin taze saymaması -, getiride ters yön; servisle: bugünün tahtası saatle, masanın 1 - 1440 dakikalık sınırı, işlemin bid'leri indirmesi, tek enstrüman sıfırlaması ve sonrası, geri alma, geçmiş günün sonundaki hâli; .xlsx'te en iyi fiyat, kimde, yaş ve "Brokerlar" sayfası), günler / aralık / silme, .xlsx, yeniden başlatma, HTTP uçları |
| `test_blotter_fx_mpc.py` | Blotter'ın yeni girişleri: parite okuma, **EURTRY** (sayfanın EURTRY tablosu ve swap puanı satırıyla aynı sayılar, TRY faizinden fiyat = çapraz forward bloğunun hücresi), **swap puanı** (forward = spot + puan / 10.000, ima faiz, Türkçe / İngilizce yazım, eksi puan), **minor para** (elle outright / spot + puan, eğrisiz paritede reddedilen fiyatlama tipleri, TRY'ye karşı olmayan parite), forward DV01'i (payer +, iki yön, USD'ye USDTRY spotuyla çevrim), işlemlerin paritesiyle saklanması, parite + valöre göre maliyet, Excel sayfasına yalnızca USDTRY ve vadeli OIS'in aktarılması, **MPC tarihli OIS** (tarihler ve piyasa seviyesi "MPC OIS" tablosuyla, nominal sayfanın "Nominal" sütunuyla aynı; iki tarih arası hesaplayıcıyla aynı seviye, nominal verilince DV01, dönemlerin çarpımı, hatalı tarihler; **tablonun kendi iskonto faktörleriyle** spot / toplantı günleri arasındaki her swap'ın hesaplayıcıyla aynı seviyesi, tablo dışı gün), listede / maliyette / riskte yeri, indirilen dosyada parite, puan ve işaretli DV01, HTTP uçları |
| `test_watch.py` | **Uzaktaki kullanıcı** (kendi girdisi olup bağlı olmayan kullanıcının listesi herkesin hesabından, kendi girdisine bağlı kalem okunmadan; bağlıyken en çok `private_refresh`'te bir); **Ne izlenebilir**: OIS, offshore, masa, VİOP kontratı (ticker'ıyla ya da sırasıyla; OIS − VİOP bp, ima faiz), kâğıt (ISIN'iyle; ASW, getiri, pahalı/ucuz, liste dışı kâğıt), hücrenin gösterdiği şey olarak alınması, reddedilenler; **ifadeler** (okunuşu, hataları, birimi: spread / fly bp, ortalama %, oran düz sayı, hücre adresi); **izleme listesi** (hazır gruplar, açılış / düşük / yüksek / gün içi çizgi, referanstan değişim, sıra / ad / hücrenin birimi, kişiye özel liste, açılışın saklanması, yeni gün); **alarmlar** (seviyenin gösterildiği gibi okunması, ≥ / ≤ / kesişir, bir kez çalması, başka kullanıcıya söylenmemesi, yeniden kurma ve silme, izleme döngüsünün kendiliğinden çalması; **VİOP spread'i, kâğıt ASW'i ve ifade üzerine alarmlar**); kâğıt listede yer değiştirince ve **kontratlar dönünce** takip; önceki sürümün listeleri; HTTP uçları (katalog, önizleme) ve **masa notları**; **hareket alarmları** (açılıştan, kurulduğu andan, referanstan, son 10 dakikada - saat testte verilir -, yön, hatalı koşulların reddi, yeniden kurunca yeni başlangıç); **z-skoru ve bant** (tarihçeden, ifadenin parçalarından, dashboard'un kendi kapanışlarından; 20 / 60 / 250 gün; günün kapanışının kaydı; z alarmı); **ısı haritası** (tablolar, sütunlar, hücrelerin konuları, piyasanın hareketi, önceki kapanış: tarihçe ve kendi kayıt, referans - kişiye özel -, HTTP, VİOP sütunlarında vade ayı); **piyasanın kapalı olduğu gün** (hafta sonu ve masanın tatilleri; cumartesi kapanış kaydedilmemesi, önceden kaydedilmiş hafta sonu değerinin kapanış sayılmaması, pazartesinin önceki kapanışının cuma olması, hafta sonu seviyenin cuma kapanışı ve değişimin 0 olması, tatilin hafta sonu sayılmaması); **masa alarmları** (yalnızca yöneticinin kurması, kimsenin kişisel listesinde olmaması, piyasanın değeriyle - bir kişinin senaryosuyla değil - denetlenmesi, herkese bir kez çalması, **"Gördüm – X bakıyor"** cevabında ilkinin geçerli olması ve alarmın açık olmaktan çıkması, **susturmanın kişisel olması** (susturana sessiz, başkalarına çalması, sayacına girmemesi, kaldırılınca yine ona gelmesi), yeniden kurma / silme, günün kaydında kimin ne yaptığı; HTTP uçları ve yetkiler) ve **sistem alarmları** (kayıtlı veride yalnızca veritabanı; veri akışının piyasa saatinde N dakika bayat kalması ve düzelmesi, piyasa saati dışında tick beklenmemesi, TLREF fixinginin saatine kadar gelmemesi ve gelince kapanması, kendisi için susturanın dışında herkese çalan veritabanı alarmı, ayardan kapatılan alarmın kapanması, RET alarmının olmaması ve önceki sürümden açık kalan RET alarmının kapanması) |
| `test_bonds.py` | **Tüm Kâğıtlar** (masanın listesi: 77 kâğıt altı türde - TLREF ve FRN ayrı -, her türde vade sırası, ★, trading listesindekilerin fiyatı ve DİBS RV özeti, listede olmayanlar, sayfadaki ☆ / ★, ▸ ve ✕; **+ ISIN ekle** canlı-benzeri bir Bloomberg'le: tür, vade, kupon Bloomberg'den, kendi grubuna, döviz cinsi ve tanınmayan ISIN'in reddi, yanıt gelmeyenin türünü bekleyip sonra yerine geçmesi, saklanması, ISIN seçicide görünmesi, HTTP; **✕** herkes için ve trading listesinden de, geri ekleme; vadesi geçenin ertesi gün düşmesi; eski "kendi eklediklerimiz" satırlarının listeye taşınması), **DİBS RV'de FRN** (Tüm Kâğıtlar'dan ya da Bloomberg'den: "F", "FRN", TLREF'e karşı hesapların boş kalması, canlı fiyat sayfasındaki adı, özetteki grubu), **★ ile trading listesi** (listenin sonuna ekleme, herkes için, DİBS ASW'nin ISIN listesinin de izlemesi, özetteki tür grupları ve vade sırası, çıkarınca satırın kaynağının ve herkesin kişisel değerlerinin silinmesi, HTTP), **DİBS Trading** (her valörün menkulü ve tarihi, DİBS RV'nin valörünün o sayfadan okunması, diğerlerinin hata değil boş kalması, kaynağın değiştirilip boşaltılınca varsayılana dönmesi, kirli fiyatlardan **ima repo** ve TLREF farkı - yalnız aynı güne ait fiyatlardan, değilse kartta ve özette nedeni -, TÜFE'de repo olmaması), canlıda **işlemin görüldüğü an** (ilk yanıt işlem sayılmaz, aynı fiyattan işlem hacimden anlaşılır, azalan hacim, yeni gün), sayfada saat ve günün işlemleri, **kâğıt kartı** (katalog, DİBS RV satırı, valörler, tahta, chat satırları ve durumları, işlemler, listede olmayan kâğıt, HTTP); **TRY DİBS kataloğu** (77 kâğıt, ISIN kontrol hanesi, ISIN'deki vade, türler - 14 TLREF, 9 FRN -, bir ayın / günün adayları; eklenen kâğıdın türünün Bloomberg alanlarından bulunması: bono / kuponsuz, TLREF / FRN, TÜFE, tarih yazımları, döviz cinsi, tanınmayan ISIN, desteklenmeyen kupon tipi, yanıtsız); broker chat'te **DİBS kotaları** (tarih ve ay-yıl yazımları, TLREF / FRN / TÜFE / bono - `tlref` FRN'e gitmez -, valör, kısa fiyatın tamamlanması, Türkçe işlem / ref / ilgi kelimeleri, switch'in metin kalması), fiyatı bilinmeyen kâğıdın **en yakın aynı tür kâğıttan** (TLREF'ten TLREF, FRN'den FRN) ya da 100'den tamamlanması, **başlıklı liste** (ihale fiyatları), servisin örnek chat'i ekranla okuması (ima getiri, bir ayın iki kâğıdının ekranla ayrılması), **DİBS RV'deki broker sütunları**, **kâğıt sayfalarında tahtanın kuralları** (DİBS RV, DİBS Trading özeti ve valörleri, Tüm Kâğıtlar, kart: en iyi taze bid / ask ve broker'ı, bayat kotanın soluk ve "bayat · BGC · 30 dk" olarak durup en iyi sayılmaması, getiri ve broker − ekran farkının yalnız taze kotadan olması, işlemle giden, geri çekilen ve sıfırlamadan önceki kotanın kalkması, kartta her chat satırının geçerli / bayat / geçmiş durumu), **ISIN ile listeye ekleme** (listenin sonuna, atlanan / reddedilen, ortak ve kişisel liste, HTTP), **100 satırlık toplu forward**'ın Forward tablosuyla birebirliği ve **Bulk Bond**'un yeni satırları; **switch** kotaları (iki kâğıt: getiri farkı bp, yazılış sırası ve bağlaçlar, "bid … offer" ayrı yazılışı, tahtada tek satır; bacak bacak yazılmış switch: her bacağın fiyatı kendi ekranıyla tamamlanır, olay satırın kelimelerinden; üç kâğıt metin kalır); **ay-yıl tek başına önce sabit kuponlu** (o ayda yoksa ayın TLREF'i, sonra TÜFE'si; tür yazılınca yalnız o tür; switch bacağının kendi türü); **zc = sıfır kuponlu ve getiriyle** (bono / kuponsuz, bitişik `feb27zc`, kuponluya geçmeme, getiride bid > ask ve kısa ask'in altta tamamlanması); virgülden sonraki öbür tarafın aynı kâğıt olması; **canlı kota mı** (`BID_SIZE` / `ASK_SIZE`: emir yoksa soluk "–" ve ipucunda Bloomberg'in tekrar ettiği fiyat, kotasız tarafla alış / satış getirisi, alış−satış ve ASW'nin hesaplanmaması, kullanılan fiyattan çıkan getiri / ASW / sinyal ve broker − ekran farkının soluk gösterilmesi, Fiyat durumu, tek taraflı kota, büyüklüğü olmayan BGN, ALIŞ fiyat tipi, canlı kotalarla bugünün repo'su; kapalı piyasada hiçbir sayfada kota görünmemesi) |
| `test_sources_and_desk.py` | **Fiyat kaynağı sırası**: canlı hücrelerin sıradaki ilk fiyatlı kaynağı alması (offshore'da iki taraflı kaynak, tek taraflı alınmaz), kayıtlı veride sayfaların dosyanın değerinde kalması, sıranın herkes için değişmesi, saklanması, tarihçe tanımlarının izlemesi, hatalı kod, HTTP; **yedek kaynağın yalnızca boş günleri hareketiyle doldurması**; tanımsız ticker açıklamaları; **ASW'nin FX swap eğrisiyle** fiyatlanması; **Forward fiyatları**: USDTRY / EURTRY tablolarının Forward sayfasıyla birebirliği (günlük puanlar dahil), yazılan faizin iki pariteyi yalnız yazana yeniden fiyatlaması, **Elle** satırı (eğri + mid ya da spread, genişlik), **serbest forward** (spot, major, minor eğrilerden; ileri başlangıç; EURTRY; eğrinin bittiği yerde boş; üzerine yazma), **vadelere göre simple zero** tablosu, eski düzende yazılmış değerin silinmesi; altın serbest sütunu; **z-score**; **tahta sıfırlama / geri alma, işaretlenen satırların silinmesi**; bugünü içeren aralıkta işlem girişi; **FX swap puanlarının okunuşu ve ima TRY faizi**; **OIS Kontrol gün sayıları masa takvimiyle** (düğüm tarihinden sayılan gün, hafta içi Bloomberg'le aynı) |
| `test_fxvol.py` | FX smile'ları: normal dağılım ve tersi, Black, piyasanın deltaları (forward / spot, primli) ve strike'ları – primli call deltasının azalan kolu –, delta-neutral straddle, market strangle; **SVI'nin, kotaları üreten smile'ı geri bulması**, G10 smile'ını arbitrajsız ve kotasına oturtması, USDTRY benzeri smile'da arbitrajsız kalması (ATM ve 25D kotalarda < 0,1 vol), **SABR'ın USDTRY skew'unu tutamaması** (neden SVI), Vanna-Volga'nın pillar'larından geçmesi, eksik kotalar; dağılım: düz smile'da lognormal yasa, kuantil ↔ CDF, ortalama = forward, yoğunluğun call'un ikinci türeviyle aynılığı; **en olası**: lognormal yasada tepenin kapalı formülle aynılığı, en dar aralıkların kütlesi, iki ucundaki eşit yoğunluk ve yüzdelik aralıktan darlığı, USDTRY benzeri skew'de forward'ın altına, G10 put skew'ünde üstüne kayması |
| `test_fx.py` | Spot / FX ve FX Vol İzleme: ticker adları (Bloomberg'deki gibi), paritelerin kuralları, **USDTRY forward'ının Forward sayfasının "Serbest forward" listesindeki offshore forward'ıyla birebirliği** (her vade), yazılan spotun yalnız sahibini etkilemesi, puandan forward ve TRY çaprazının USD bacaklarından, teslim tarihleri; yüzey (her vadede arbitrajsız, ortalama = forward, artan kuantiller, skew), otomatik seviyeler, SABR / geçersiz model, EURUSD'de spot delta ve iskonto, **kendi kotası** (yalnız sahibine, boşla Bloomberg'e dönüş, hatalı girdiler), pariteler tablosu, **Makro bloğunun istatistikleri** (Δ1G / 1H / 1A, z 3A, pencere z'si, yüzdelik, aralık, boş günün doldurulması), gerçekleşen vol, yuvarlak seviyeler, izleme (tarihçeyle, eklenen parite ve ticker, ortak fiyat kaynağı), parite ayrıntısı (bugün / 1H / 1A önce; RR / BF'siz gün smile'sız; bekleyen kotaların sayılıp adlandırılması, forward'sız da aynı smile), tarihçenin bir yıl geriye sonra son on gün istenmesi, **spot oynayınca smile'ın yeniden kalibre edilmeden taşınması**, her vadenin en olası seviyesi ve en dar aralıkları (spot oynayınca yalnız ölçeklenir), `check-fx`, HTTP uçları |
| `test_series_charts.py` | **Tıkla → grafik**: Gün Sonu Matrisi'nin satırının, izleme kaleminin ve ısı haritası noktasının arkasındaki kapanışlar (`/api/history/closes`, `/api/watch/history`) ve tarayıcının onları çizdiği istatistikler (`seriesstats.js`, Node.js ile) - yanındaki tablonun sayılarıyla birebir (FX izleme: `tto.fx.stats`, izleme listesi: `Watch.zinfo`); Node.js yoksa atlanır |
| `test_volcarry.py` | Realized vol: yazılanın okunuşu, enstrüman seviyesinin günlere göre kuruluşu (yalnızca bütün bacakların kapandığı günler), **vol = günlük değişimlerin standart sapması** (elle hesapla aynı; pencereler, dolmayan pencere, en az beş değişim, kayan vol), forward'ın par eğrisinden bootstrap'i (düz eğri, sınırlar, Excel'in forward'ına 5 bp içinde yakınlık), sayfa satırı; tarihçeye yazılmış kapanışlarla servis (outright / spread / fly / FRA / cross-currency, eksik günü olan vade, geçmişi olmayan vade, pencere seçimi), **carry / vol** (C & R sayfasının 34 fly'ı ve 120 spread'i, sayfanın kendi C+R değerleri, ufukların iş günü sayısı, oran = C+R ÷ (σ·√gün)), **carry patikası** (S1'in Excel'in kaydettiği C & R değerlerini birebir vermesi, Bootstrap'ta ufku vadeye eşit OIS'in carry'sinin ~0 olması, patikadan bağımsız roll, kullanıcıya özel seçim ve ufuklar, hatalı değerler), **Listem** (yazılan OIS vadesi / spread / fly'ın carry'si, FRA ve listede olmayan vade için açıklama), **Spread Geçmişi** (offshore − OIS: iki eğrinin ortak günlerinden seri, canlı kotayla bugünkü seviye, 1G / 1H / 1A değişim, 20 / 60 / 250 kapanışta ortalama, σ, z, aralık, yüzdelik; canlı kota yokken son kapanış; VİOP − OIS kontratları), HTTP uçları |
| `test_charts.py` | Grafik tanımlarının Excel'den alınışı (renk, çizgi, işaretçi, eksen sınırları, tarih ekseni, bid–ask kutuları), değerlerin Excel kuralıyla çizime verilişi (boşluk, `#N/A`, metin) ve XY grafikleri (nokta etiketleri, sayı / tarih ekseni) |
| `test_auction.py` | **Hazine İhalesi** (canlı-benzeri bir Bloomberg'le): temiz fiyattan, basit ve bileşik getiriden kirli fiyat (bağımsız bir BIST getiri hesabıyla aynı; 3 haneye yuvarlama, tutar, iki girdide temizin önceliği), nominal ağırlıklı ortalama ve getirisi; açıklanan asgari / ortalama / azami fiyatla gerçekleşen / asgari fiyatta / gerçekleşmeyen teklifler, ortalamaya fark, aralıktaki yer, elle yazılan gerçekleşen nominal, gerçekleşen ortalama ve getirisi; **kısaltmayla yazılan nominal** (`35m`, `2,5 mn`, `500k`; yazarak ve yapıştırarak; anlaşılmayan tutar reddedilir, toplamı boşaltmaz); bono, TLREF ve FRN (getiri yok; FRN kendi adıyla) ve TÜFE (reel getiri, endeks oranıyla tutar); **uzun ilk kuponlu** yeni ihraçta kalan kuponların takvim dönemiyle (364 / frekans gün) sayılması; **birikmiş faizin yalnız Bloomberg'den, valörle** istenmesi (kâğıdın kendi valörü, kupon gününe denk gelen valör, Bloomberg'in yanıt vermediği valörde fiyat çıkmaması, tanınmayan ISIN); sayfa tanımı ve kayıtlı veri modu |
| `test_extras.py` | Dashboard'un ekledikleri: forward kotasyon matrisi (yedi eğri Masa bloğuyla aynı, bid / ask ayrı spread, puan → spread tersi; **piyasa spread'i**: her vadede offshore ima − OIS, seçilince spread'in yerine geçmesi, EURTRY'nin seçimi izlemesi; **EURTRY matrisi**: aynı tarihte USDTRY ile aynı OIS faizi, EUR faizi ve gününün Masa'nın EURTRY hücreleriyle aynılığı, eğri ve spread'lerin USDTRY'yi izlemesi ve ayrılması, kendi spot'u, puandan spread), altın (`spot·(1+swap·g/360)` kapalı formülü, USD faizinin hesaba girmediği, faiz interpolasyonu, kaynak seçimi, `XAUSR…` ticker'ları ve ticker eki, canlıda `BFXFORWARD`'sız çalışma, VİOP / Forward hücrelerinin beslenmesi, "belli faizle fiyat"; **VİOP XAUTRY hesaplayıcısında her girdinin elle yazılması**: fiyattan ima TRY ve ima altın swap faizi, ima faizle fiyatın geri gelmesi, başka tarih, serbest sütun, silince piyasaya dönüş; **VİOP geçmiş serileri**: canlı-benzeri bir sağlayıcının geçmişiyle ima faiz / baz / OIS'in elle hesapla ve aynı günlerde sayfanın kendi "Baz" değeriyle aynılığı, fiyatı olmayan günün çizilmemesi, grafik verisi, kontrat seçimi, kendi geçmiş penceresi – sayfanın 20 günlük istatistik penceresi değişmeden), bir ekin dosyaya uymadığında dışarıda bırakılması (DİBS RV'nin bid'i başka yazılınca canlı kota ekinin), Borsa O/N karşılıkları ve örnek kotaların RET'e eşitliği, **Borsa'da yalnızca miktarı olan kotanın listelenmesi** (miktarı 0 / eski fiyatlı vadeler, tek taraflı kota, hata hücresi kalmaması), ASW ↔ DİBS RV |
| `test_borsa_spread.py` | **Borsa Swap'ın OIS ve offshore mid spread'leri** (`tto/borsaspread.py`): elle kurulan bir eğride iki tarih arası zero faizin elle hesapla aynılığı (düğümde, düğümler arasında ln DF doğrusal, son düğümden sonra son eğimle; sayısı olmayan düğümün yalnız kendi aralıklarını boşaltması); **T+0'ın spot öncesi günleri** (bir gün, hafta sonu üç gün, ikisi de spot öncesi tarih, spot'a kadar O/N'un kendisi; O/N yoksa spot öncesine faiz yok); sayfada iki tabloda altı sütun ve her satırda iki mid, **spread = BID % / ASK % − mid zero** (bp; mid'in üstü +, altı −, işaretin rengiyle), tek taraflı kotada yalnız o tarafın spread'i; **ORANLAR'la aynılık** (T+1 30 gün = 1A "OIS zero" ve ICAP; T+0 1 gün = ON satırı: TLREF 365 → 360 ve offshore O/N mid); düğüm dışında Masa'nın 'Tarih arası faiz' Bootstrap satırı ve kırık vade bloğunun offshore basit faiziyle aynılık; kullanıcının kendi OIS kotasının yalnız kendi sayfasını değiştirmesi; kotasız satırın boş kalması, başka tablonun ve başlığı kaymış tablonun dokunulmaması, okunamayan eğrinin nedenini söylemesi |
| `test_workbook_features.py` | Gizli sütunlar, dondurulmuş bölmeler, yorumlar, veri çubukları, kısayollar, resim, aralıktan okunan açılır listeler, Excel yerleşimiyle yapıştırma, gün sonu arşivi (.xlsx yazıcı dahil), hücreden okunan başlık / notlar, şifreli dosyanın içe aktarılması |
| `test_defaults.py` | PPK ima adımlarının, VİOP Target tablosunun, manuel USDTRY spotunun ve hesaplayıcıların kayıt günü değerlerinin (TM OIS işlemi, gün sayacı, altın forward tarihleri, tahvil carry, iki tarih arası, VİOP TRY faizleri, switch, Eurobond ask'ları, FOMC senaryo adımları) herkese boş gelmesi (boş adımla üç senaryonun ima yola eşitlenmesi, kullanıcının kendi değeri, boş spotla kaynağın BBG olması); Hesaplayıcılar üst bandının ve altın forward'ının spot / tarih / faizlerinin piyasadan başlaması (üzerine yazma, silince piyasaya dönme); eski sürümün ortak girdi olarak taşıdığı dosya adımlarının ilk açılışta bir kez silinmesi (başka ortak girdiye dokunmadan; boş başlatma eki dosyaya uymadıysa silinmemesi), saklı manuel spotun yalnızca dosyanın değeriyse bir kez silinmesi (masanın yazdığı farklı değerin ve sonradan yazılanın kalması); masanın referans verisinin (ticker'lar, tatil adları, kaynak kodları, kova tanımları) ortak, DİBS RV ufkunun kişisel olması ve eski kişisel değerlerin silinmesi; **VİOP kontratlarının kendiliğinden dönmesi** (dosyanın kontrat tarihlerinde vade günü / ertesi gün, arife kuralı - 27.10.2027 -, çift aylı altın, masanın yazdığının geçerli olması, silince dönüşe geri gelme, dosyanın ticker'ının saklı kopyasının silinmesi); **tek OIS spread'i** (`P58` / `O27` / `F122`'nin `MASA!I60`'ı izlemesi, üzerine yazma, silince geri gelme) |
| `test_viopfra.py` | **VİOP Target · FRA eğrisi**: "Hedef tipi"nin yanındaki liste (`EK_VFRA`'dan okunan açılır liste, SENARYOLAR adlarıyla), satırın diğer girdileri gibi kişisel; bugünkü OIS FRA'nın bootstrap eğrisi olması ve varsayılanda dosyanın altı Target satırının her sütunda Excel'in değerini vermesi; her eğrinin (Bootstrap, S1, S2, S3) aynı tarihlerde Masa "Tarih arası faiz" bloğunun faizini vermesi, hedef faiz = FRA + bp ve uzak limit / spread fiyatı / hedef − piyasa'nın izlemesi (near limit değişmez); başlık (`OIS FRA · S2 · Hawkish`, `eğri satıra göre`) ve ipuçları; senaryo adı değişince listenin, başlığın, ipuçlarının ve Masa özetinin izlemesi (seçim aynı senaryo, hücre eski adıyla ve bunu söyleyerek); FXswap+bp ve Faiz % satırlarının hiçbir sayısının değişmemesi, boş tipin FRA+bp sayılması; kişisellik, saklanma, `Delete` ve "Girdilerimi sıfırla", formül ve liste dışı değerin reddi; kayıtlı senaryoyla gidip gelmesi; Masa şeritleri ve launchpad (bütün tablo ve sütun seçimi); **PPK takvimi değişince** adımların toplantısıyla taşınıp satırın senaryonun yeni eğrisiyle fiyatlanması, takvim geri gelince aynı sayılar; **VİOP kontrat dönüşü** (canlı-benzeri Bloomberg, saat ilerletilerek: vade gününde dönemi OIS spot'tan sonra bitmeyen satırın, dönüşten sonra vadesi geçen kontratın satırının "geçersiz" demesi ve sayı vermemesi; listede kalan kontratın aynı tarihler ve aynı eğriyle kalması) |
| `test_columns.py` | **Sütun gizle / göster**: her kullanıcının gizlediği sütunların hesabıyla sunucuda saklanması (tablo ve sütun adıyla; boş liste tabloyu unutur), başkasının görünümünün değişmemesi, geçersiz ya da oturumsuz isteğin ve başka sayfadan gelen değişikliğin reddi, tablo sınırı; **sütun sırası** (kullanıcı başına, gizlenenlerden ayrı saklanması, boş listeyle Excel sırasına dönüş, geçersiz istek, sınırlar, HTTP'de gizlemeyle birlikte gönderilmesi); sayfadaki davranış (sağ tık, "Sütunlar", kopyalama, ok tuşları, yeniden açılış, İzleme listesi, sütun sırası) `test_e2e.py`'de |
| `test_launchpad.py` | **Launchpad ve düzen**: birden çok sayfanın tablolarının tek istekte `view/panel` anahtarıyla gelmesi (aynı panel id'si başka sayfada başka tablo), sayfasındakiyle aynı olması, sayfa ve sekme adı; `since` / `as` (değişmeyenin "unchanged" demesi, ortak girdinin yalnız onu okuyan tabloyu, kullanıcının kendi girdisinin bütün tabloyu getirmesi); tablonun bir kısmının sunucuda kesilmesi (satır adı ya da numarası, sütun harfi, tablonun kendi sırası, başlık satırları, birleşik hücrenin kalan kısmı - ilk hücresi gidince salt okunur -, dondurulmuş sütun, sayfanın tablosunun değişmemesi, seçimden bir şey kalmayınca bütün tablo); yöneticiye özel sayfa (403 "erişim yok"), kaldırılmış sayfa ya da tablo (404 "artık yok") ve diğerlerinin yine gelmesi; geçersiz istekler; düzenin kullanıcı başına saklanması, gönderilmeyen bölümlerin kalması, normalleştirme, geçersiz düzen, sınırlar (launchpad, tablo, yan panel, bayt), yeni öğe türünün kendi denetimiyle eklenmesi, açılış sayfası, dışa / içe aktarma (aynı adın "(2)" alması), oturum; **servis yeniden başlayınca** düzenin ve sütun sırasının kalması; HTTP (401, başka sayfadan gelen değişikliğin reddi) |
| `test_calc.py` | **Kişisel hesap tablosu** (`tto/calc.py`): yazılanın okunuşu (Türkçe / İngilizce sayı, yüzde ve tarih biçimiyle, DOĞRU / YANLIŞ, `'` ile metin, formül), Türkçe Excel'in `;`'ü ve ondalık virgülü, `[kitap]Sayfa!` yazımı, kopyalanan formülün göreli başvurularının kayması (`$` kalır, sayfadan taşan `#REF!`); kendi hücreleri ve aralıkları (SUM, AVERAGE, TEXT, IF, LET, INDEX), ana kitabın hücreleri sayfa adıyla (büyük / küçük harf, tırnaklı ad, aralık, adlar: SPOTDATE) ve diğer kitapların (`[sofr]`, `[asw]`, `[borsa]`) - sayfanın gösterdiği değerle aynı -, başvurunun sayı biçimini alma (tarih, yüzde), TODAY / WORKDAY tarih; **kullanıcının kendi girdisinin ve "Elle değer"inin yalnız onun sonucunu değiştirmesi** (diğerinin "unchanged" demesi), ortak girdinin yalnız onu okuyan tabloyu getirmesi; **Bloomberg işlevlerinin reddi** (BDP, BDH, BDS, BFXFORWARD, BINTERPOL, RTGET, `_xll.`, iç içe ve küçük harfle; nedeniyle, değişikliğin hiçbir kısmı kalmadan) ve başka sürümün sakladığı böyle bir formülün sağlayıcıya hiç ulaşmaması; hücre hücre hatalar ve anlamları (`#DIV/0!`, bilinmeyen işlev / ad / sayfa / kitap, döngüsel başvuru, `#NUM!`, `#VALUE!`, okunamayan formülün reddi); Motor sayfasının yalnız yöneticiye açık olması; **sınırlar** (formül uzunluğu, hücre adresi, satır / sütun, dolu hücreyi kesmeme, genişlik, sayı biçimi, yapıştırılan alan, okunan hücre, aralık, süre, tablo boyutu, istek); hiçbir öğenin göstermediği tablonun 7 gün sonra ve üst sınırda gitmesi; kopyalama ve doldurmada formüllerin kayması; sayı biçimleri; düzende `calc` öğesi; dışa aktarılan launchpad'in hücreleri taşıması, içe aktaranın kendi kopyası, Bloomberg'li dosyanın reddi; **servis yeniden başlayınca** kalması; HTTP (`/api/calc/eval`, `/api/calc/save`, 400 / 401 / 403 / 404, kullanıcının sayı biçimi) |
| `test_inputformula.py` | **Girdiye formül** (`tto/inputformula.py`): Masa'nın kırık vade valörüne `=C60+7` - değerin başlangıç tarihi + 7 olması, başlangıç her yazılınca kendiliğinden izlemesi, sayfada `ƒ` / formül (`ff`), `/api/cell` ve "girdilerim" listesinde formül ve şimdiki değer; Türkçe `;` ve ondalık virgül, başka sayfa adıyla ve onun değişince izlemesi; **sayfasız başvurunun girdinin kendi sayfası olması** (Forward'da `=AB2*2` - aynı gruptaki iki girdinin bağımlılık bitini paylaşmasına rağmen döngü sayılmaması); **ortak girdinin formülü herkesin** (başka kullanıcının değeri ve formülü görmesi, başkasının yazdığı ortak girdiyi izlemesi), **kişiselinki yalnız sahibinin**; **ret ve nedeni** (BDP, `_xll.BDH`, doğrudan döngü, çalışma kitabının formülü üzerinden döngü - E60'ın formülü C60'ı okur -, başka formüllü girdi üzerinden döngü ve aynı yazmadaki iki formülün birbirini okuması, okunamayan formül, bilinmeyen işlev, olmayan sayfa, listeli hücre, toplantı tarihi, **toplantı başına adım** (U12, W89), Motor'u okuyan ortak formül, "Elle değer" hücresi ve yapıştırmada girdi olmayanın atlanması, **Bloomberg isteğine giren hücreye canlı formül** - Forward valörüne `=NOW()+30` reddi, `=TODAY()+30` kabulü); **sonradan oluşan döngünün dönmemesi** (E60 boşaltılınca birkaç turda durması, `#CALC!` ve nedeni, piyasa / nesil tetiklemesinde yeniden denenmemesi, üzerine yazılan değerle bitmesi); **toplantı takvimi kayınca** (araya toplantı girince kayan hücrelerde formül kalmaması, satır 12'nin yeni toplantısını okuyan formülün izlemesi, yazılan adımın toplantısıyla taşınması, reddin sürmesi; önceki sürümün kayan hücreye aldığı formülün açılışta kalkıp değerinin kalması ve günlük dosyasına yazılması); **piyasayı izleyen formülün masa değişikliği saymaması** (her tikte değerin izlemesi, sayacın kıpırdamaması); **süre sınırı** (sınır aşılınca değerin kalması, "yeniden denenecek", aradaki nesillerde denenmemesi, ara bitince izlemesi, üst üste üç kez aşınca durması); **Bloomberg isteğine giren hücrede duran formülün son iyi değerini koruması** (Forward valörü, `#CALC!` değil); **yetki** (Motor'u okuyan ortak formülün yöneticiye de reddi, kişiselin sahibinin o anki rolüyle okuması - yetki alınınca durup nedeni, geri verilince yeniden okuması); **duran formülün yeniden denenmesi** (sahibinin ilk yazmasında hemen, yine durunca aradaki yazmalarda denenmemesi, ara bitince yeniden); **kuyruğa alınamayan turun bir şey bırakmaması**; **silme ve sıfırlamalar** (Delete, hücrenin kendi sıfırlaması, "Girdilerimi sıfırla", ortak sıfırlama, üzerine yazılan değer, yapıştırılan formül); senaryonun formülleri saklaması; **formül yokken hiç iş yapılmaması** (yeni nesilde iş kuyruğa bile girmez); **yeniden başlatmada kalması** (ortak formülün açılışta, kişiselin kullanıcının hesabı kurulunca hesaplanması, sonra yine izlemesi); HTTP (`/api/inputs`, `/api/cell`, `/api/view`, `/api/my-inputs`, `/api/reset`); `test_store.py`'de formülün değerin yanında saklanması (eski veritabanına sütunun eklenmesi, üzerine yazılan değerin formülü silmesi, senaryonun dördüncü öğesi, toplantıyla taşınan hücrenin değerinin formülsüz taşınması, formülün kaldırılınca değerin kalması, her yazmanın bildirilmesi) |
| `test_pageboxes.py` | **Sayfaların kutuları ve kendi menünüz**: yedi kutu türünün seçenekleriyle saklanması (VİOP seviyelerinde ön vade, tahtanın enstrüman listesinin tekrarsız, broker satırlarının yalnız açıkken; tablo alanlarının alınmaması), geri okunması, başka bir bölüm değişince kalması, dışa / içe aktarma; geçersiz seçeneklerin (aile, varlık, tıklama, kontrat, ürün, enstrüman, liste, banka, genişlik, yükseklik) reddi ve düzenin değişmemesi; başka sürümün kutusunun yalnız kendisinin dışarıda kalması; **menüden çıkarılan sayfaların** (`hidden_pages`) kullanıcı başına saklanması, tekrarın atılması, diğer bölümlerin kalması, sayfaya erişimin değişmemesi, sınır ve geçersiz listeler, başka sürümün yazdığının toleranslı okunması; **quant menüsü**: 15 sayfanın dört giriş ve sekmeleri (sıra, sekme adları, sayfanın kendi adı ve adresi, VİOP'un tek sayfalık girişi), menünün adlandırmadığı sayfanın kendi girişi; **kutuların okuduğu kısımlar**: ilk hesaptan önce quant kutusu, bilinmeyen kutu (400), tahtanın sayfanınkiyle aynı olması (satırlar, günler ve girilmeyen işlemler gelmeden), **Broker Chat'in değişiklik sayacı** (yazılan satır, bayat sınırı, sıfırlama, silme sayılır; piyasanın nesli sayılmaz; tahta okunduğu sayacı söyler), İzleme sayfasının tek listesi (izleme, alarmlar, çalanlar - masa alarmları ve notlar gelmeden), bilinmeyen kısım (400); HTTP (yeni modüller, kısımlar, 401, düzende kutu ve `hidden_pages`, nav'da menü) |
| `test_dv01.py` | DV01 Risk'in sıfır pozisyonla açılması (kova DV01'leri ve yapıştırma alanı; kullanıcının kendi pozisyonu kişisel), VİOP matrisinin DV01 satırları kendi para biriminde (TRY: TL ve USD, USD: USD; kontrat fiyatıyla çevrim, sayfada yeni satır) |
| `test_dates.py` | **Özel günler**: vadeden valörün (`2W`, `18W`, `1M` …) masanın tatil listesini (Motor!A361:A523; USDTRY'de USD tatilleriyle birlikte) izlemesi - Ramazan Bayramı'na (10.03.2027), 19 Mayıs'a ve 1 Ocak'a düşen valörün ilk iş gününe kayması, ay vadelerinin çalışma kitabının kendi `WORKDAY(EDATE(…))` tarihleriyle aynı olması; dashboard'un **ay sonunda** (30.11.2026), **yıl sonunda** (31.12.2026: spot 1 Ocak ve hafta sonundan sonra) ve **bayramın ortasında** (10.03.2027) açılması: spot ve tahvil T+1 valörü, geçen PPK'nın listeden bir kez çıkması (MPC1 bir sonraki toplantı), bütün sayfaların Python hatası vermeden hesaplanması |
| `test_holidays.py` | **TRY, USD ve EUR tatil listeleri ve iki takvimli FX valörleri**: USD listesinin Fed tatilleri (2026 günleri, Thanksgiving, Good Friday'in olmaması, cumartesiye düşen 4 Temmuz'da cumanın açık, pazara düşende pazartesinin kapalı olması, Juneteenth 2022'den), EUR listesinin TARGET2 günleri (Paskalya), hangi paritenin ortak takvimi olduğu; `EK_TATIL` (listeler, TRY kopyası, eklerin hepsinin dosyaya uyması), spot valörlerinin dashboard'un olup Bloomberg'inkinin yanında durması (Forward şeridi); **USDTRY spot T+1, TRY ve USD** (24.11 → 25.11, 25.11 → 27.11 Thanksgiving, 28.10 → 30.10 Cumhuriyet, Good Friday'de takas, 03.07.2026, Veterans Day, yıl sonu), **EURTRY spot T+2, TRY ve EUR** (01.04 → 07.04, Thanksgiving'in etkisizliği, 29 Ekim, Noel); tahvil T+1'in ve OIS spotunun TRY'de kalması; **vadeler** (spot 26.10 → 1M Thanksgiving'den 27.11: Masa, `EK_FWD`, çapraz blok, vadeler tablosu, Günlük İşlemler'in vadesi, forward kotası, Spot / FX; başka paritenin TRY listesiyle kalması; EURTRY 1M'in Good Friday / Easter Monday'den 07.04'e, USDTRY'nin Good Friday'de takas olması; EURUSD), **EURUSD'nin kendi spot valörü** (27.10.2026 → 29.10, Cumhuriyet Bayramı'nda; EURTRY 30.10: Günlük İşlemler'in vadesi ve gün sayısı, Spot / FX), **TLREF OIS spotunun TRY listesiyle** (25.11 → 26.11 Thanksgiving'de, 28.10 → 30.10, 31.12 → 04.01.2027; ondan sayılan OIS günleri, Masa'nın spotu, kırık vadede FX − OIS spotu; OIS sayfasında yanında Bloomberg valörü), Spot / FX'te EURUSD'nin iki takvimle, USDJPY'nin yalnız hafta içiyle sayılması; **düzenleme** (USD'ye eklenen günün yalnız USDTRY'yi, EUR'ya eklenenin yalnız EURTRY'yi kaydırması, tahvil valörünün yerinde kalması, yazmanın hesap motorunda öncelikli olması, saklanan sayfanın herkes için yenilenmesi, hatalı para birimi / tarih / fazla gün reddi, yeniden başlatmada kalması; HTTP: her kullanıcının düzenleyebilmesi, `ccy`'siz eski çağrının TRY olması, dosya listesine dönünce hiçbir şeyin saklanmaması) |
| `test_auth.py` | **Giriş ve hesaplar**: şifrenin tuzlu özetle saklanması (tur sayısı özetin içinde), önceki sürümün veritabanındaki kullanıcıların şifresiz etkin hesap olarak kalması, **ilk yöneticinin yalnızca bu bilgisayardan** ve yalnızca yönetici yokken oluşturulması (önceki sürümden bir kullanıcı da olabilir, girdileri kalır), yanlış şifre / bilinmeyen isim için aynı yanıt, **5 hatada 1 dakika kilit**, oturumun 7 gün sürmesi ve veritabanında yalnızca özetinin durması, çıkış; **hesap isteği** (bekleyen istekle girilmemesi, önceki sürümün kullanıcısının aynı isimle isteyip onaylanınca girdilerine kavuşması, reddedilen yeni isteğin silinmesi / eski hesabın şifresiz geri dönmesi); **yönetici işleri** (oluşturma, rol verme / alma, son yöneticinin korunması, şifre belirleyince ve hesap kapatınca açık oturumların bitmesi, kendi hesabını kapatamama); kendi şifresini değiştirme (diğer oturumların kapanması, eski şifre hatalarının kilide sayılması); **aynı anda gönderilen 20 tahminin 5'inin denenip gerisinin kilide takılması**, şifresiz hesabın yönetici yapılamaması ve istekle sahiplenilenin kullanıcı olması, kendi yetkisini bırakma, benzer görünen isimlerin tek isim / görünmeyen karakterin reddi, bekleyen istek sınırı; HTTP'de **oturumsuz her `/api` isteğinin 401** alması, **başka sayfadan (Origin / Sec-Fetch-Site) gelen değişiklik isteğinin 403** alması, sunucunun X-Forwarded-For'a inanmaması, çerezin HttpOnly / SameSite=Strict / 7 gün olması, `Authorization: Bearer`, yönetici uçlarının yöneticiye açık olması, kapatılan hesabın tarayıcısının bir sonraki istekte dışarıda kalması; `python -m tto yonetici` komutu |
| `test_desk.py` | **Hata / Öneri, Sosyal, Ajanda** (`tto/desk.py`): bildirimin yalnızca yöneticiye gitmesi (kullanıcıda rozet sayısı yok; liste ve "İlgilenildi" 403), İlgilenildi / yeniden aç ve geçmiş; sohbetin herkese açık ve kalıcı olması (yeniden başlatmada), okunmamış sayısı, sayfalama (son 200, öncekiler, okunanı yeniden okuma), yalnızca kendi mesajını silme; ajandada masa / kişisel görünürlüğü (başkasının kişisel işi 404), gün ve saat sırası, gecikmiş deadline'ın yaşı ne olursa olsun kalması, uyarı listesi (bugün, yarın, gecikmiş), tamamlama ve silme yetkileri; metin temizliği (görünmez yön karakterleri), uzunluk ve hız sınırları (429; silmek sınırı açmaz), ajanda sayfasının sınırı; **tekrarlayan işler**: her türün günleri (Her iş günü'nün hafta sonunu ve TRY tatilini - Cumhuriyet Bayramı - atlaması, Seçili günlerin tatilde de sayılması, Ayın son iş günü: son günü hafta sonu olan ay ve Kurban Bayramı'nın ardından hafta sonuyla biten ay), başlangıç / bitiş, bugünün tekrarının günün işleri arasında ve rozette olması, sonraki zamanı, her günün ayrı tamamlanması (kim, ne zaman, geri alma; tarihi olmayan / gelecekteki / eklenmeden önceki günün reddi), uyarı listesi (15 dakika önce, saatinde, geç açılınca gecikmiş, ertelemenin kişiye özel olması ve bitince yeniden uyarı, saatinden önce ertelenen deadline, gece yarısından sonraki saatin önceki akşam uyarısı, tamamlanınca ve sonraki günlerde susması, deadline'ın rozette gecikmiş kalması), masa / kişisel görünürlüğü ve yetkiler (değiştirme, duraklatma, silme: ekleyen ya da yönetici; başkasının kişiseli 404), yeni saatin geçmiş günleri gecikmiş saymaması, duraklatma ve devam, silmenin kayıtlarıyla gitmesi, denetimler ve sınırlar (100, hız), yeniden başlatmada kalması (kurallar, tamamlanan günler, erteleme), **önceki sürümün veritabanının** yeni tabloları alıp her tablosunun satırlarını koruması, dashboard'un tatil listesini okuması ve değişince hemen izlemesi (yeni günde arka planda yeniden okunur: masanın durumu meşgul hesap iş parçacığını beklemez); bir değişikliğin yeni nesil açmadan sayfalara haber vermesi, canlı akışta bildirim sayacının yalnızca yöneticiye gitmesi; HTTP'de oturum ve başka siteden gelen isteğin reddi (tekrarlayan işlerin uçları da) |
| `test_service.py`, `test_server.py`, `test_store.py`, `test_inputs.py`, `test_config_cli.py` | Kişisel/ortak girdiler, senaryolar, RET, kalıcılık, HTTP API, yapıştırma/ayrıştırma (nominal, DV01 hedefi ve P&L hücrelerinde `100m` / `2,5mn` / `500k` / `5k`; anlaşılmayanın reddi, başka hücrede `3m`'nin metin kalması; tarih sanılan spot / faiz / fiyat / ISIN hücrelerine yazılabilmesi; B/S listesinde `Al` / `Sat`'ın karşılığı, başka metnin reddi), port kuralı, manuel spot (VİOP ve Masa'nın ilk tablosu, üst şeritten giriş, temizleyince Bloomberg spotu), **elle değer** (formülün üzerine yazma: yalnızca sahibinin, yalnızca ona girdi görünür, silince / "formüle dön"le formül geri gelir, yeniden başlatmada kalır), hesaplayıcıların otomatik dolan girdileri (Forward ve VİOP: tarih, spot, döviz faizi), sekmeli sayfa çıktısı ve arama kutusunun verisi, işlem defterinin aralık / DV01 / tahvil fiyatı uçları; **operasyon**: piyasa ve izleme döngülerinin hatalarının günlük dosyasına bir kez ayrıntısıyla yazılması (tekrarı sayılır) ve durumda son hata / hesap motoru kuyruğu, beklenmeyen sunucu hatasının tarayıcıya kısa, günlüğe tam gitmesi, piyasa saatleri (hafta sonu, masanın tatili, ayarlar); **veritabanı**: yarıda kalan yazmanın geri alınması (paket bacakları ve silinmesi, chat yapıştırma, hesap silme - ikinci adımı reddeden tetikleyiciyle), her kaydın diske yazılması (`synchronous=FULL`), **yedek ve geri dönüş** (yedeğin tek dosya ve tutarlı olması, sonraki yazmaları içermemesi, açık veritabanının yerinden alınamaması, önceki halin saklanması, bozuk / başka bir dosyanın reddi, komut satırı), gece yedeğinin zamanı (saati, kaçırılanın açılışta alınması, başarısızın beklemesi) ve en yeni 30'un kalması, **ikinci kopya** (D:\tto-yedek'in yalnızca kurulu dashboard'un varsayılanı olması; başka klasöre aynı adla kopya, orada da 30; sürücü / klasör yazılamazken yedeğin yine alınması, hatanın bir kez günlüğe yazılması, tek gecede alarm olmaması, iki gece üst üste alarm, düzelince kapanması; yedek klasörünün kendisinin reddi), **geri dönüşün iki klasörden de** (yol ya da yalnızca adla), **bozuk dosyanın açılışta söylenmesi** ve hiç açılamayanın en son yedeği göstermesi, **chat ↔ blotter** ucu (durumdaki "girilmedi" sayısı, liste, yok sayma ve geri alma, oturumsuz karar, hatalı istek), Broker Chat tahtasının **bayat sınırı** ucu; **tatillerin tek yerden düzenlenmesi** (iki kitabın birleşik listesi, ABD / FOMC tarihleri, ikisine birden yazma, WORKDAY'in izlemesi, hatalı / fazla tarihin reddi, yeniden başlatmada kalması, HTTP); **Motor yalnız yöneticilere** (menü, arama, Masa kısayolu, 403; servisin kendisi için açık), Eurobond Kotaları ve OIS · Nakit Akışı adları; **hız / dayanıklılık**: hesaplama iş parçacığının önceliği ve aynı sayfanın bir kez hesaplanması, meşgul hesaplamada sunucu iş parçacığı tutulmaması (statik dosya ve giriş cevap verir), oturumun bir dakika tutulup çıkışta hemen unutulması, tarihçe durumunun taramasız sorulması, sayfaların hesap başına saklanıp yalnız değişen panelin yeniden yapılması (`since`, `panels`; sıfırdan yapılanla aynı), nesil bildiriminin saniyede bir olması, sabitin üzerine yazılınca kimsenin değerinin silinmemesi (sıfırdan hesapla aynı), kayıtlı elle değerlerin ve senaryoların açılışta tanımlanması, kendi girdisi olanın piyasayı birkaç saniyede bir izlemesi ve uzun süre yokken hesabının bırakılması, ısınma, Bloomberg sayacı ve cevaplarının saklanması, JSON'a yazılamayan sayının `null` gitmesi |
| `test_backup.py` | **Günlük yedek**: varsayılan saatin 17:30 olması (ayarlar, komut satırı, yedeğin zamanı, alarm sayfasının eşiği); **öncelik**: yöneticinin seçimi > komut satırı / ortam değişkeni > varsayılan (ayar ayar, nereden geldiği, boş ikinci kopyanın "yok" olması, yeniden başlatmada kalması, *Varsayılanlara dön*); **yeniden başlatmadan** geçerli olması (yeni saat bir sonraki bakışta, yeni klasöre hemen ilk yedek, eskilerin taşınmaması ve her klasörün kendi 30'u, başarısız klasörün yerine seçilenin hemen denenmesi); **klasör denetimi** (göreli yolun, sürücüsüz kökün, hatalı saatin reddi; OneDrive'ın ortam değişkeniyle ve OneDrive / Dropbox / Google Drive / iCloud Drive / Box klasör adlarıyla **bulut eşitleme klasörünün** - orada hiçbir şey açılmadan - Bloomberg / şifre gerekçesiyle reddi, açılamayan ve yazılamayan klasörün reddi, ikinci kopyanın yedek klasörünün kendisi olamaması, hatanın alan alan söylenmesi ve hiçbir şeyin kaydedilmemesi, uygun klasörün açılıp deneme dosyasının silinmesi); **D:	to-yedek'in yalnızca D: sürücüsü olan bilgisayarda varsayılan olması** (sürücü denetimi taklit edilerek), ikinci kopya yokken alarm olmaması, seçilen ikinci klasörün iki gün üst üste alınamamasında alarmın klasör adı içermemesi; **yedekten dönüşün seçilen klasörlere de bakması** (önce onlar, yalnızca adla); **Şimdi yedek al**ın seçilen klasörlere yazması (dosya, boyut, ikinci kopya, listeler); **seçilen klasöre yazılamazsa** (paylaşım kapalı): günün yedeğinin `dataackups`'a alınması, ikinci kopyanın ondan yine alınması, klasör adı içermeyen veritabanı alarmı, günün yedeklenmiş sayılması (döngü ne kadar bakarsa baksın ve yeniden başlatmada ikinci tam yedek yok), seçilen klasörün yarım saatte bir denenmesi, açılınca dosyanın oraya bütün kopyalanması ve alarmın kapanması, birkaç günün sayılıp ilk doğrudan yedekle birlikte gitmesi, seçilen klasöre sonradan kendi yedeği alınan günün üzerine yazılmaması, ikinci kopya `dataackups`'ın kendisiyken dosyanın kendisi; seçilen klasör `dataackups`'ın kendisiyken geri çekilme olmaması, ikisi de yazılamazken iki nedenin söylenmesi; HTTP: oturumsuz 401, kullanıcıya 403 (okuma, kaydetme, sıfırlama, şimdi yedek), alan alan 400, kullanıcının durumunda ve masa alarmında hiçbir klasörün geçmemesi |
| `test_views.py` | Sayfa tanımları: Masa'nın USDTRY ve EURTRY forward özetinde her spread'in yanında TRY faizi (sütun sırası, girdiler kendi hücrelerinde, +25 bp yazınca TRY faizinin OIS + 0,25, EURTRY'de −40 bp yazınca OIS − 0,40 olması), tarih arası forward'ın üstündeki tarih / spread satırı (başlangıç, bitiş ve spread girdileri; 01.12.2026 → 01.03.2027 = 90 gün, bitiş forward'ının yükselmesi), her panel ve girdi gerçek hücrelere bakıyor (tablonun ipucu sütunları dahil), **her formül bir tabloda** (dört kitap + ekler, sıfır istisna), her girdi hücresine sayfasından ulaşılıyor, Forward'daki elle hesaplama araçları (USDTRY ve EURTRY) görünür tablolarda; **sekmeler**: 12'den çok tablosu olan her sayfa sekmeli, her görünen tablo bir sekmede ya da sekmelerin üstünde, sekmeler var olan görünür tabloları gösteriyor, Forward hesaplayıcılarla başlıyor, Hesaplayıcılar sayfasında aynı adlı iki tablo yok; **kaldırılan dört sayfa** (MOBIL MK, YP DIBS, Ivır Zıvır, USDTRY IYIX: yüklenen kitapta ve Sayfa gezgini'nde yok, 45 `BDP` çağrısı gitti, kalan sayfaların sırası ve numaraları, model dosyasının onları tutması, başka bir formülün başvurduğu sayfanın kalması); **her hesaplayıcının tek yeri** (kopyaların yardımcı tablo olması, Kotasyon sekmesi, Masa'daki özet, emekli tablo, limit tablosunun girdisiz kalması); **tarih sanılan girdi kalmaması** (tarih girdisi olarak tanımlı her hücrede tarih ya da boşluk); **her tablonun girdileri kendi sekmesinde** (her görünür tablonun formülleri girdilere kadar izlenir; okunan her girdi aynı sekmede - tabloda, üstündeki girdi satırında, sabit panelde - ya da masanın ortak / kurulum verisi, ya da notla anılan büyük bir girdi tablosu; tarih arası forward'ın tarih satırı ya da forward özetinin eğri satırı kalkınca, pozisyonu anan not silinince, RET ortak veri sayılmayınca testin bunları bulması), **yeni girdi satırlarına yazılanın tabloya ulaşması** (Masa'da DEALS'e vade sınırı 1: tek kontrat; VİOP hedefinin TARGET'ta görünmesi, girdi şeridinde FRA eğrisinin "Hedef tipi"nin yanında olması; OIS'te DV01/bacak 2.000 → en iyi spread'in nominali iki katı; Carry & Roll'un OIS satırında C+R nominali ve yönü; USD'nin Girdiler'i her sekmede) |
| `test_bundled.py` | Kurulumsuz çalıştırma: her Python kuşağının paket seti, wheel özetleri ve lisansları, kurulu paketlerin önceliği, `vendor/local`, ve hiçbir paketi olmayan bir Python'la (`python -S`) sunucunun açılıp sayfa, statik dosya, giriş ve canlı akış vermesi |
| `test_quant.py` (`quant_synth.py`: sentetik tarihçe) | **Quant sinyaller**, cevabı bilinen sentetik serilerle: kayan korelasyon ve dikilmiş bir kırılma, PCA'nın dikilmiş seviye / eğimi bulması ve dikilmiş ucuz vadeyi (receive, hedge'in seviye-PCA'sının PC1 / PC2'sine nötrlüğü) ve zengin / ucuz tablosundaki z'nin sinyalin kendi canlı z'si olması, **dinamik PCA** (60 / 120 / 250 günlük pencereler, son 60 günde şekli değişen ikinci bileşenin kararlılık tablosunda görünmesi, sinyalin penceresini yazması; bir indirim döngüsünde değişim-PCA kalıntılarının zamanla korelasyonu 1 iken seviye-PCA paketlerinin ~0 ve hiçbirinin sinyal vermemesi), klasik ve PCA ağırlıklı fly / spread'in maruziyetleri (bilinen yüklerle Σ w e √λ, net DV01, fark satırı), **gün içi** (barların küçük tutulması - 20 gün, bilinen anahtarlar - ve 5 dakikaya çevrilmesi; dikilmiş barlarda 60 dakikalık ortalamadan sapmanın receive'i, açılış aralığı kırılımının yönünde pay'i ve devam beklentisi, offshore − OIS daralmasının z'si, carry patikasının önündeki USDTRY'nin sat'ı; PPK penceresinde ortalamaya dönüşün elenmesi, 17:00 sonrası hiç; kayıtlı veri modunda bar olmaması; gün içi kaydın geceye kalmaması), **geri test** (ortalamaya dönen seri yüksek isabet ve artı ortalama, rastgele yürüyüş yarı ömür kapısında kalır; gelecek değiştirilince o güne kadarki işlemler aynı; istatistikler - isabet, Sharpe, düşüş, TL -; masanın eşiğiyle susturma; servisin bütün aileleri sınayıp her sinyalin yanına kaydını koyması, API), **gerekçe** (3σ'daki ortalamaya dönen bir serinin benzer günleri yüksekte duran ve sonra dönen günler, en az bir hafta arayla; stop, rejim ve ufuktaki PPK toplantısı geçersiz kılanlarda; API'de), PCA-nötr fly / spread ağırlıkları ve DV01'leri, β'sı ve yarı ömrü bilinen eşbütünleşik çift (offshore − OIS), iki rastgele yürüyüşün çift olmaması, OU yarı ömrü, ADF'nin MacKinnon değerleri ve boyutu (rastgele yürüyüşlerin ~%5'i), Kalman'ın kayan β'yı izlemesi, rejim değişiminin bulunması (varyans oranı, Hurst), trendde momentum sinyali (pay, hareketli ortalamalar), makro betalar ve TRY'ye özgü hareket (receive), vol primi ve GARCH tahmini (sat; iki ailenin uyumu), EM carry sıralaması, VİOP takviminin faiz paritesine göre sapması (uzak sat / yakın al), **FRA / PPK konvansiyonu** (patika kendi kotalarını ≤ 3A tek ödeme / uzunlar üç ayda bir kuponla 0,01 bp içinde yeniden üretir; kaydedilmiş çalışma kitabının kendi patikası Motor!K325:K330'u 0,05 bp içinde verir; 6M kotası bozulunca 3x6 / 6x9; 5 bp altı fark tolerans), PPK fazına göre eğim sinyali (steepener) ve **küçük örneklem** (kritik değerler, 1,96'nın rastgele yürüyüşte üçte bir yanılması; kısa fazda sinyal yok, uzunda var), **pariteler** (varsayılan 22 parite ve ticker'ları - GBP3M, JPY3M, GBPTRY3M, EUR3M, CNH vol'ü -, grupları, listenin denetimi, masanın listeyi değiştirince tarihçenin yeni paritenin serilerini istemesi), **FX carry** (USDTRY yılda %20 kayış, forward %30: forward pozisyonunun getirisi −%10, "Sell USDTRY forward" carry lehte, "TRY long"; forward'ı olmayan pariteye sinyal yok; carry aleyhine işlemin tampon kapısı, "elendi"), **FX'in masa dili ve parası** (işlem ufkun sonu valörlü forward'la - "USDTRY 1A forward sat" -, giriş bugünkü forward'ın kuru, hedef / stop analiz serisinin hedef / stop'unun forward kuru; 1 mn USD başına TRY = 1 mn × fiyat hareketi, forward primi = 1 mn × (forward − spot), kur hareketi = 1 mn × spotun beklenen hareketi, ikisinin toplamı beklenen K/Z; eski % × spot karşılığından farkı F / S; EURUSD'de 1 mn EUR başına USD ve TRY karşılığı, USDZAR'da ZAR ve USD / TRY karşılığı, paritenin ondalığı; forward primi ailesinde 3A forward, kâr spotun yüzdesi, prim 3A puanlarının tutma süresine düşen payı, kur hareketi beklenen kayma - carry'nin sinyalin kendi tutma süresiyle okunması -; kartın düz cümlesinin bu sayılardan kurulması; gerekçede benzer günlerin sonucunun ve stopun parayla / forward kuruyla yazılması; para ve vade yazımı - "+2.325 bin TRY", "1A", "45 gün"), momentum ailesinin kendi tezinin yazılması, parite özeti (carry, küçültülmüş kayma, tampon, karar), **her sinyalin kararı** (OU'dan beklenen kâr, carry dahil, TRY karşılığı, ödül / risk, kapıların sırası; carry'nin yediği sinyal "beklenen kâr yok"; faizde TL: beklenen = bp × ana bacağın TL DV01'i, carry + roll ve hareket ayrı, hedefte / stopta bp ve TL, "sabit faiz alınan (receive): 2Y OIS (değişken bacak TLREF)" ve düz cümle; API'de her sinyalin masa diliyle işlemi ve cümlesi, gerekçenin TL'si), forward primi ve trend kapısı, modelin kayan pencereli doğrulaması (OU geçer, rastgele yürüyüş geçmez) ve **ileriye bakmaması** (gelecek değiştirilince geçmiş tahminlerin aynı kalması); sinyal biçimi, bileşik puan ve kapılar (rejim, yarı ömür, stop bölgesi), uyum sayısı; kaydın hedef / stop / süre sonuçları ve aile başına isabet; abonelere göre süzülen alarmlar; **masa alarmları** (güç eşiği, susturma, hedefte kapanma); ayarların denetimi; yeni ticker'ların tarihçeye iki yıl geriye eklenmesi; **Bloomberg'in günlük limiti**: sahte terminalle bir canlı gün (ilk tur + 96 tur 15 dakikada bir) - her serinin tüm aralığı günde en çok bir kez, kısa geçmişin ilk gününün saklanması, quant serilerinin turda 40'ar, **VİOP kontratlarının yanlarında turda 15'er** dolması (vadesi geçmiş kontrat bir kez, iki haneli yılı ancak tek haneli biçimi boş dönünce, yeni günü hiç), sonra yalnızca yeni günler, ertesi gün yalnızca geçmişi olmayanların yeniden sorulması (vadesi geçmiş kontratın değil), gelmeyen cevabın aralığı o gün değil ertesi gün yeniden sorması; günün hit / veri noktası toplamı sınırlı (ölçülen: 18.996 hit, 136.085 nokta; VİOP'un 2.361 hit, 29.278 nokta); hesabın motor iş parçacığı dışında çalışıp dikilmiş sinyalleri bulması; **paket büyüklüğü dolar**: ana bacak 1.000 $ DV01 (ayar), TL'si masanın USDTRY'siyle, OIS bacağının nominali annuity'den (Motor'unki, yoksa kendi par'ından), TRY ile ölçen eski sürümün kaydının dolar sayılmaması, sinyalde bacağın işlemi ve büyüklüğü, TL K/Z'nin ana bacaktan; API (her sayfa, süzgeçler, hatalı istekler, nav - menünün sırasıyla, dört giriş); **kutuların hafif kısmı** (`/api/quant/box`): sinyal listesinin sayfanınkiyle aynı olması (süzgeçler dahil, elenenler / kapsam / ayarlar gelmeden), VİOP'un canlı kontratları ve seviyeleri, WIRP'in her bankasının tablosu (matris, dağılım ve geçmiş olmadan), parite özeti; cevabın sürümü ve canlı yenilemeyle artması |
| `test_quantcurve.py` (`quant_synth_extra.py`) | **Eğri Adil Değeri**: NSS'in uçları ve forward'ı; OIS par'ların Excel'in kuralıyla (3A'ya kadar tek ödeme, sonra üç ayda bir kupon) hesaplanması; parametreleri bilinen bir eğrinin par'larından **parametrelerin geri bulunması** (β 1e-6, τ 1e-5 içinde); dikilmiş ucuz bir vadenin farkta kalması ve **komşularını bükmemesi** (Huber; düz EKK'dan farkı); DİBS fiyatının sayfanın BIST kuralıyla (TRT150328T24'ün kirli fiyatı ve bir bononun fiyatı DİBS RV'deki değerleriyle birebir); **bilinen bir eğriden fiyatlanan kâğıtların ne zengin ne ucuz** olması (basit ve bileşik getiriyle, < 0,01 bp) ve 25 bp ucuz bir kâğıdın farkının kendisinde kalması; carry ve roll'un düz eğride ve eğriyle aynı fonlamayla sıfır, 1 puan ucuz fonlamada beklenen kadar, yükselen eğride artı / düşende eksi roll; tarihçe getiri kuralının sayfaya göre seçilmesi; sentetik iki yıllık tarihçede dikilmiş 2Y'nin receive sinyali (paket seviye / eğim nötr), dikilmiş kâğıdın al sinyali (z, hedge'li paket, carry + roll, OIS farkı, en iyi kâğıt sıralaması), canlı getirinin farkı ve z'yi oynatması, bileşik tarihçenin bileşik okunması; **işlemin bacak bacak yazılması**: seri "NSS farkı", ifade her bacağın işlemi, Paket 1'in (kâğıt ve iki komşusu) DİBS uyumunun seviye ve eğimine nötr olması (bacakların nominalleriyle model fiyatları), ana bacağın 1.000 $ DV01'i ve masanın DV01'iyle nominali, Paket 2'nin (kâğıt + OIS) vadesini çevreleyen iki vadede vadeye göre doğrusal, 1:1 DV01'i ve annuity'den nominalleri, vadenin uçta tek OIS'e düşmesi, carry bilinmeyince uydurulmaması; **adil eğriden kotasyon**: bilinen bir eğriden fiyatlanan kâğıdın adil ± yarım spread'i birebir (getiri, temiz / kirli fiyat, işlemiş faiz DİBS RV'deki gibi, DV01), yarım spread kovaları ve ayarın denetimi, **switch'in DV01 nötr oranı**, eğriye göre kazancı, carry farkı ve z'si (ters yönde işaretler); DİBS RV'nin okunması (sabit kuponlu ve bonolar, floater'lar dışarıda; her satırın DV01'imizin sayfanın AI'sına eşitliği, masanın USDTRY'si ve Motor annuity'lerinin Günlük İşlemler'inkine eşitliği); servis ve **API**: iki sayfa (sinyaller, iki paketin masanın büyüklüğüyle, tablolar, kapsam, canlı yenileme), kotasyon / switch / yarım spread uçları, nav'da on beş Quant sayfası |
| `test_quantopt.py` | **Opsiyon**: 24 yeni ticker'ın adları, paketin listesinde iki kez olmaması, tarihçeye iki yıl ve doldurma sırasının sonunda girmesi; düz smile'ın **lognormal olasılıkları** birebir, **bilinen bir SVI smile'ının beş kotasından kendi olasılıklarının** bulunması (2e-4 içinde); hareketlerin **forward'dan** ölçülmesi (aynı forward'da spot fark etmez); gerçekleşen sıklıkların, bağımsız gözlem sayısının ve standart hatanın kurulmuş bir yoldan birebir; dikilmiş 25D RR'nin sat sinyali, eğim paketi, yüzey / vade yapısı / olasılık tablosu (EURUSD spot delta, USDTRY forward delta, forward'daki carry); kota yokken sayfanın nedenini söylemesi |
| `test_quantpath.py` | **İma Patikası ve TCMB WIRP**: bir adımın iki ızgara sonucuna bölünmesi (−40 = %80 −50 + %20 0, ızgaradaki adım, Fed'in 25 bp'si, iki indirim arası), masanın örneği (−40 / −60: (−50, −50) %0–80, (0, −100) %20–60, (−100, 0) %0–40; TLREF − 40'tan +10 / −40 / +60, ikinci dönem 0; okumalar), olasılık aralıklarının kaba kuvvet aramasıyla aynılığı (ızgarada olmayan toplam), dönüş fiyatlanınca toplantı başına sonuçlara düşülmesi, eşit adımın %50 / %50 önden / geç karışımı da olabilmesi, kinkler ve zikzaklar (ızgaranın beşte birinin altında zikzak yok; kinkin toplantısıyla kalması), kararların fixingden ızgaraya okunması (ızgara dışı değişim karar sayılmaz; Fed'de toplantı günü görüntüsü), dikilmiş bir sapmada kalibrasyon (kovalar, toplantı sayısıyla aralık, z) ve az toplantıda sinyal olmaması, kalibrasyon sinyalinin hedef / stop'u, WIRP evrişimi (−40 / −60 → −150 %16, −100 %68, −50 %16; rastgele patikalarda matrisin beklenen değerinin ima patikayı vermesi), politika faizi çevirimi (elle / Masa!Q155 / yok) ve kovalar, geçmişin bugünkü kovalarda okunması, USD günlük görüntülerinin tutulması (değişmeyen yazılmaz, 10 dakika, yeni gün hemen, 800 gün); sentetik bir yıllık PPK fiyatlamasıyla servis (dikilmiş kinkte receive fly ve bacakları, komşuların sinyal vermemesi, kalibrasyon sinyali, Sinyaller'de sıralanmaları, USD kitabından on FOMC toplantısı ve bugünün görüntüsü), motor okumasının en düşük öncelikte tek kısa çağrı olması, kayıtlı ayın çalışma kitabının kendi çözücüsünden geçmesi (adımlar depodakiyle aynı, 22 Ekim kararı −100), HTTP API (ızgara ve politika faizi ayarı, sayfalar) |
| `test_quantlead.py` | **Öncü-Takipçi**: F dağılımının kuyruğu (kritik değerler, tamamlanmamış betanın kapalı biçimi ve simetrisi), dikilmiş 2 günlük gecikmenin β'sı, Granger p'si ve 3/3 kararlılığıyla bulunması, ters yönde de; kuralın geçmişi (isabet, gelen / beklenen); yalnızca son 70 günde olan öncülüğün 250 günde tutmaması; bağımsız serilerde (20 tohumda en çok 2) ve aynı gün birlikte hareket edende öncü bulunmaması; kendi gürültüsü olan aynı kotalarda ve ortalamaya dönen spread'de Granger'in tek başına "lider" demesi, asimetrinin demediği; lider oynamadan sinyal olmaması, yetişmemiş takipçide sinyal (Pay 2Y OIS, hedef = yetişme, stop = σ, tez), kararsız öncülükte sinyalin elenmesi, yetişmiş takipçide olmaması; **VİOP ve DİBS çiftleri** (ön vade ↔ OIS ve offshore, kontrat ↔ kendi vadesinin OIS'i, kâğıt ↔ en yakın OIS vadesi, en kısa önce, adı vadesinden; TLREF / FRN / TÜFE ve 3 aydan kısa kâğıdın dışarıda kalması; barların nerede olduğu: ön vade kendi kontratından, bono basit, kuponlu bileşik getiriden); **OIS'i izlemeyen kâğıt** (Sell / Buy, DİBS varlığı, şimdiki getirinin tarihçenin kuralındaki getiriden okunması, yetişmişte sinyal olmaması); **barların lead-lag anahtarları** (canlı değerden kendi anahtarıyla yazılması, istenmeyenin yazılmaması, hafta sonu yok, 20'ye karşı 5 gün tutulması, anahtar anahtar okunması); dakikalık barlarda 3 bar gecikmenin bulunması, bar kaynağının sezilmesi, bar yoksa "gün içi barlar yok"; iki yıllık sentetik tarihçede 5Y'nin 1Y'yi 2 gün geriden izlediğinin bulunması, her aday grubun listelenmesi, sinyal ailesi; HTTP API (ayarlar, sayfa) |
| `test_quantread.py` | **Quant tablolarının cümleleri** (`quantread.js`): sayfaların kurduğu her tablonun - kimliğiyle ya da sayfa adından kurulan deseniyle (`quant-*-signals`, `*-coverage`) - bir cümlesi olması, artık olmayan tabloya cümle kalmaması, cümlelerin en çok 320 karakter, tam cümle ve yöntem terimsiz (ADF, Kalman, GARCH, SVI, EWMA, OU, regresyon …) olması; desen eşleşmesinin sayfadakiyle aynı olması (kendi kimliği desenden önce) |
| `test_quantviop.py` | **VİOP**: kontrat ticker'ları ve vadeleri (tek haneli yılın en yakın yıla okunması; ayın son iş günü, 29 Ekim'den ve Bayram'dan önce bir gün erken, 1 Ocak / 1 Mayıs'tan önce değil), işlemdeki ilk altı ve önceki 24 ay (vadesi geçmişin iki haneli yıllı ticker'ı), tarihçe serileri (kapanış / en yüksek / en düşük); **ima faizin VİOP sayfasının formülü** ve tersi (fiyat), EK_VIOP'un USD çizgisi (30 güne düz, 1M / 3M / 6M / 1Y arası doğrusal, eksik vadenin komşulardan); sabit vadeli serilerin dış değerleme yapmadan doğrusal olması; ay sonuna kalan iş günü ve **dikilmiş bir ay sonu etkisinin bulunması** (ortalama, t; sürüklenmeye yalnız belirgin günler); **yansıma ilkesi simülasyona karşı** (iki yönde sürüklenmeyle), tersi (seviyenin olasılığı 1e-6 içinde) ve merdiven; **kalibrasyonun bilinen bir OU sürecinde c ≈ 1 bulması** (isabetler olasılıklara 0,12 içinde), kısa geçmişte boş; gün içi profil ve ufukların varyansı (bugünün kalanı, hafta, seans bittikten sonra, cumartesi); **5 dakikalık barlar**: depo (boş gün de hatırlanır), plan (en yeni gün önce), budama, canlıda yenileme başına 4 istek, yanıt gelmeyince durma, kayıtlı veri modunda hiç istek; **sahte terminalde barlar ve maliyeti** (iki kontratın işlemleri ve USDTRY bid / ask × 20 iş günü: 80 istek = 80 hit, 8.160 bar, 20 yenilemede; ertesi gün 4 istek, en eski gün düşer; barların ima faizi, yarım saatlik profil 09:30 … 17:30, gün içi kalibrasyon); barın ima faizinin USDTRY bid / ask ortasıyla hesaplanması; **sentetik iki yıllık tarihçede aile**: dikilmiş spread'in geri bulunması, 60 bp ucuz ön kontratta *Buy VİOP Kas26 (… kontrat) · Sell USDTRY spot* (1.000 $ DV01), bugünün ve haftanın seviyeleri (sıraları, fiyatları, adile çekilme, haftanın varyansı); **ince kotada seviyeler** (tek taraflı kotada iki merdivenin o taraftan, kotasız kontratta son işlemin ima faizinden, ikisi de yokken nedeni; kendi geçmişi olmayan uzak vadenin en yakın kontratın σ'sını adıyla alması; pencereden kısa geçmişin σ'sının kendi günlük değişimlerinden - sıfır değil -; seans bitince bugünün nedeni, haftanın seviyeleri); **takvim sürüklenmesi**: bugünün etkisi seansın kalan payı kadar - haftada da -, önündeki günler tam, seans bitince bugünden yok; servis: kayıtlı veri modunda **VİOP sayfasının on iki kontratı** canlı bid / ask ima faiziyle (Bloomberg geçmişi yok: adil değer ve seviye yok), HTTP API, sayfa dosyası, nav; Bloomberg geçmişi gelmeden EK_VIOP'un kendi günleriyle adil değer ve seviyeler |
| `test_history.py` | **Toplantı takvimi**: açıklanan tarihlerle toplu düzeltme (en yakın toplantının düzeltilmesi, 45 günden uzak tarihin eklenmesi, açıklanmamış yılların ve geçmişin kalması, 80 sınırının nedeniyle reddi, listeye ekleme, gelecektekilerin yerine koyma, kaydedince adımların toplantısıyla gitmesi, önizleme ucu) ve **geçen toplantının listeden kendiliğinden çıkması** (açılışta ve gün içinde spot değişince: MPC1 sıradaki toplantı, adım toplantısıyla, "otomatik" kaydı), **OIS sayfasında yazılan toplantı tarihinin takvimden geçmesi** (adımın toplantısıyla kalması, çıkarılan toplantının adımıyla gitmesi, dosya tarihlerine dönüşün reddi); günlük tarihçe: kapanış deposu, kayıtlı `BDH` bloklarının tarihlenmesi, serilerin dosyadan okunuşu, **tarihçenin bugünkü satırı = OIS sayfası** (80 toplantı, hücre hücre), toplantı bazında fiyatlama (yapılan toplantının serisi, gerçekleşen TLREF değişimi, toplantı günü ölçümü, kotaların eriştiği ufuk), gün sonu matrisi (1 / 5 / 21 iş günü kuralı, tatil, geçmiş gün), takvim (tarih düzeltme / ekleme / çıkarma: adımların ve kayıtlı senaryoların toplantıyla taşınması; **toplantı geçince ve liste kaydırılınca** sayfalar ve her toplantının değerleri), sahte Bloomberg'le canlı tarihçe (istek gruplama, yalnızca son günlerin yenilenmesi, yedek ticker, zaman aşımı; günün hit'leri: her referans çifti bir kez + tarihçe kuralların verdiği kadar - dört turda 430, VİOP'un turda 15'i dahil), **VİOP kontratlarının tarihçesi** (kendi sırasında turda 15, quant serilerinin 5'i yanında; vadesi geçmiş kontratın bir kez istenip yeni gününün hiç sorulmaması, iki haneli yılın ancak tek haneli biçim boş dönünce sonraki turda sorulması, ikisi de boşsa ertesi günler ve "şimdi güncelle"de değil ancak bir hafta sonra yeniden - bu arada gelen bir daha sorulmaz -, kapsam tablosunda durumları), HTTP uçları; **bir günün kotaları** (kapanışı olmayan vadenin komşularının hareketiyle taşınması, komşularından ayrılıp geri dönen kapanışın ayıklanması, piyasa hareketinin korunması), günlerin Excel'in kendi durumuna göre sınıflanması, çözücünün tutturamadığı günün seriden / min-maks'tan / değişimlerden çıkması, hatalı bir kapanışın kayıtlı ayda çözücüye ulaşmaması, eski sürümün veritabanının korunması, masanın verisi kayıtlı veri modunda açılınca **sonradan fiyatlanan günlerin silinmemesi** (pencerede hesaplanamayan gün gider, pencereden eskisi kalır) |
| `test_bundle.py` | Tek dosyalık kurulum (`kurulum/tto_kur.py`): içine ne girdiği, aynı içeriğin aynı dosyayı vermesi, boş klasöre açma, güncelleme (değişen yenilenir, kalkan silinir, `data` / `vendor/local` / kullanıcının kendi dosyaları kalır), ZIP'ten gelmiş klasör, yarım inmiş / bozulmuş / satır sonları değişmiş dosya, klasör dışına çıkan adların reddi, seçenekler; **repodaki dosyanın kodla aynı olduğu** ve hiçbir paketi olmayan bir Python'la açılıp sunucunun ondan çalıştığı |
| `test_bloomberg.py` | `blpapi` katmanı (sahte sunucuyla): gruplama, abonelik (kota büyüklükleri dahil), sessiz kalan kotaların giderek seyrek sorulması, hata metinleri, BDH/BDS, limit koruması, canlı–doğrudan eşdeğerlik (dört kitap); **Bloomberg'in tanımadığı ticker'lara abone olunmaması**, ertesi gün yeniden sorulması, seyreltme seçeneği ve reddedilince seçeneksiz deneme, uzun olay kuyruğu, **kuyruk taşınca sayım ve düşen değerlerin yeniden istenmesi** (günlük üst sınırıyla); **Excel eklentisi için yazılmış kimliklerin API biçimine çevrilmesi** (`… @ISL1 ISIN` → `/isin/…@ISL1`: istek, geçmiş, abonelik), geri çekilen emrin miktarının boşalması, **aboneliği akan menkulde kota büyüklüğünün yeniden sorulmaması** (akmayanda eskisi gibi), canlı–doğrudan eşdeğerlikte büyüklüğün tick'le gelip DİBS RV'de kotayı açması, **aynı gün yeniden başlatma** (günün referans cevaplarının ve veri sayacının devralınması: yeniden sorulmaz, vadesi gelince sorulur) |
| `test_bloomberg_bars.py` | **Gün içi barlar** (`IntradayBarRequest`, sahte terminalin hafta içi 09:30–18:00 barlarıyla): isteğin öğeleri (tek menkul, olay türü, bar uzunluğu, İstanbul saatinin UTC'ye çevrilmesi - yerel gece yarısı bir önceki gün 21:00 -, ISIN'in API yazımı), barların İstanbul saatiyle ve eskiden yeniye dönmesi, **bitişin hariç olması** (terminal o barı da gönderse), hafta sonunun boş kalması, **uzun aralığın parça parça gelip birleştirilmesi** (20 iş günü, 2.040 bar, 5 parça), **istek başına 1 hit ve günlük sınırda isteğin hiç gönderilmemesi** (ertesi gün yeniden), tanınmayan menkulün boş liste ve hata metni, Bloomberg'in limit / zaman aşımı yanıtının `None` olması, yanıt gelmeyince `None` ve geç gelen yanıtın hiçbir yerde kalmaması, zaman aşımına uğrayan isteğin yeniden gönderilmesi, aynı anda dört çağrı, Bloomberg'in reddedeceği argümanlar (`ValueError`) ve boş aralık (istek yok), imzanın her sağlayıcıda aynı olması, kayıtlı veride `None` |
| `test_bloomberg_process.py` | Oturumun yardımcı süreçte çalışması: değerlerin, tick'lerin, `BDH`'nin ve tarihçe çağrısının süreç sınırını geçmesi; `blpapi` yok / yüklenemiyor / terminal yok / yardımcı yanıt vermiyor; **yardımcı ölünce yeniden başlayıp her şeyi yeniden istemesi** (istek sayacı sürer), sürekli ölen yardımcının bir noktada bırakılması; **sessiz kalan (takılan) yardımcının fark edilmesi** (son sesin saati, verinin "bayat" olması), piyasa saati dışında yeniden başlatılmaması, piyasa saatinde yenisinin başlatılıp her şeyi yeniden istemesi, **sürekli takılanın günlük sınırdan sonra bırakılması**; verinin durumu (canlı / bayat: tick yaşı, piyasa saati, sessiz yardımcı / bağlantı yok / kayıtlı veri) ve "itibarıyla" saati; dashboard durunca ya da öldürülünce yardımcının kapanması; **ölçüm: hesap yapan bir sürecin içindeki okuyucu saniyede 2.000 tick'in dörtte birine yetişemezken yardımcı hepsini okur**; dashboard'un yardımcıyı kullanması ve başlatamazsa aynı süreçte devam etmesi; ve ilk canlı çalıştırmanın sahnelenmesi: `python -m tto --mode live`, dört kitap, saniyede 1.500 tick, 10.000'lik kuyruk — hiç olay düşmez, var olmayan ~790 vadeye abone olunmaz; **gün içi barların yardımcıdan geçmesi** (aynı barlar, tanınmayan menkulün boş listesi, hit sayımı ve günlük sınırın yardımcıda tutulması), yanıt gelmeyince ve yardımcı ölünce `None` (zaman aşımını beklemeden), yeni yardımcının yanıtlaması |
| `test_blpapi_real.py` | Gerçek `blpapi` kuruluysa (yoksa atlanır; terminal gerekmez): kütüphanenin kendi test olaylarıyla tick okuma, değeri boşaltılmış miktarın "mesajda yok"tan ayırt edilmesi, `SlowConsumerWarning` / `DataLoss` / abonelik durum mesajları, oturum seçenekleri ve abonelik metni (`…?fields=ASK,BID&interval=1`), hesap yapan bir iş parçacığının yanında okumanın kaç kat yavaşladığı, terminal yokken hata (aynı süreçte ve yardımcıyla). `blpapi` yükseltildikten sonra masada bir kez çalıştırmaya değer. |
| `test_e2e.py` | Gerçek tarayıcıda (Playwright/Chromium) 471 kontrol: **bir tarayıcıya bir canlı akış** (8 sekme: hepsi sayfasını açar, akış sayısı artmaz, değişiklik her sekmeye ulaşır, yenileme yalnız açık sekmenin panellerini `since` ile ister), **şifreyle giriş** (oturumsuz API'nin 401'i, yanlış şifre, yöneticide "Kullanıcılar" sayfası, kullanıcıda yok), **sekmeler** (Forward hesaplayıcılarla açılır, sabit valör şeridi, sekme değiştirme ve hatırlanması, her sekmede arama, "Tümü", başka sekmedeki hücreye gidiş), **elle değer** (mod kapalıyken formül yazılamaz; açıkken yazılan değerin işareti, sayaç, silince ve "formüle dön"le geri dönüş), hesaplayıcıya elle spot, düzenleme, Excel kopyala/yapıştır, RET, senaryo, işlem girişi, iki kullanıcı arası canlı paylaşım, grafiklerin çizimi (renk, eksen, tarih ekseni, ipucu, XY grafiği), kısayollar, gizli / dondurulmuş sütunlar, arşiv indirme, forward kotasyon matrisi (USDTRY ve EURTRY; EURTRY'nin USDTRY'nin eğri ve spread'lerini izlemesi, kendi spread'i, puandan spread), altın swap faizi girişi ve VİOP tablosunun değişmesi, Borsa Swap (**OIS ve offshore mid spread sütunları**: iki tabloda başlıklar, spread = BID % / ASK % − mid zero, tek taraflı kotada yalnız o taraf, T+0'ın OIS spot'una TLREF'le taşındığını söyleyen ipucu, tablonun notu), DİBS ASW, gün sonu matrisi (değerler, geçmiş gün, kopyalama), PPK fiyatlama geçmişi (çizgiler, toplantı ekleme / çıkarma, ölçü değiştirme, ipucu, günlerin durumu), manuel spot penceresi (üst şeritten açma - dosyanın spotu gelmez, kaynak BBG -, bid > ask reddi, Bloomberg'e dönme), **VİOP Target'ın FRA eğrisi** ("Hedef tipi"nin yanında, varsayılan Bootstrap (piyasa); S2 seçilince OIS FRA ve hedef faizin S2'nin değeri olması, başlığın ve ipuçlarının "S2 · Hawkish" demesi, sayfa yeniden yüklenince seçimin durması, Bootstrap'a dönünce eski değerler), RET kaydırma önizlemesi (her vadede kaç bp ve yeni bid / ask, sabit tutulan ve elle miktar verilen vade, yalnız bid, önizlemedeyken kaydetmeme, "Uygula") ve tablo / mesaj olarak kopyalama, VİOP geçmiş sekmesi (kontrat tablosu, iki grafik, yeni çizgi ekleme), işlem girerken ve listede DV01, tarih aralığı görünümü ve indirilmesi, **Broker Chat** (yapıştırılan chat'in yazılırken okunması, kısaltılmış seviye / işlem / ref, kaydetme, tahta ve model farkı, ikinci kez yapıştırma, tek enstrüman / arama / ürün süzgeci, başka kullanıcının eklediği satırın canlı gelmesi, silme, saatsiz satır, indirme, aralık), blotter'da **EURTRY / swap puanı / minor para / MPC tarihli OIS** girişi ve bacak bazında payer (+) işaretli DV01, **Realized Vol · Carry** (yazılan enstrümanların vol'ü, geçmişi olmayan / okunamayan satır, yıllık birim, seviye ve kayan vol grafiği, fly ve spread'lerin C+R ÷ σ sıralaması ve noktalı grafiği), altın hesaplayıcısının serbest sütunu, Ctrl+K ile tablo bulma, Ayarlar'da toplantı tarihinin düzeltilip OIS sayfasına yansıması, **Ayarlar'da fiyat kaynağı sırası** (ekleme, kaydetme, varsayılana dönme, her vadenin kullandığı kaynak), Broker Chat'te **taraf** sütunu, sütuna göre **sıralama**, **işaretleyerek silme**, **tahtayı sıfırlama / geri alma**, RET penceresinde **spread (önceki → şimdi)**, carry tablosunda **z-score**, bugünü içeren aralıkta **işlem girişi**, Broker Chat'te **DİBS kotaları** (ISIN'li ad, valör, ihale listesi, yakın kâğıttan tamamlama), **DİBS RV'nin broker sütunları** (en iyi taze bid / ask, kimde · yaş; bayat sınırı 10 dakikayken yarım saatlik kotanın soluk, "bayat · BGC · 30 dk" olarak, getirisiz ve ekran farksız durması), **"+ ISIN ekle"** (77 kâğıtlık katalog, hatalı ISIN'in reddi, listeye ekleme), **Bulk Bond ve toplu forward'da satır açma**, **DİBS Trading** (valörler, ek kaynak, chat sütunları, günün işlemleri), **kâğıt kartı** (DİBS Trading'den ve DİBS RV'den), **Tüm Kâğıtlar** (77 kâğıt, türler, ★) ve **☆ / ★ ile trading listesine ekleme / çıkarma** (DİBS Trading özetinde görünmesi), **İzleme · Alarmlar** (hazır grup, sağ tıkla hücre ekleme - kâğıdın getirisi kâğıt olarak -, alarmın çalıp açık sayfada uyarması, "Ekle · alarm kur…" ile **VİOP OIS − VİOP spread alarmı**, **kâğıt ASW alarmı** ve **"İfadeye ekle" ile ifade**, hatalı ifadenin söylenmesi, **z-skoru sütunu ve pencere seçimi**, **z alarmı**, **masa alarmı** (yöneticinin herkese kurması, açık sayfada "Gördüm, ben bakıyorum"lu uyarı ve üst şeritteki sayaç, tek cevabın herkese görünmesi, kişisel susturma: yeniden çalınca susturana sessiz, başkasına açık), masa notları), **Eğri Hareketi** (tablolar, seviye, açılış ve referans karşılaştırması, ölçek, bir noktadan **hareket alarmı**), **Forward fiyatları** sekmesi (USDTRY / EURTRY alt alta, günlük puanlar, Elle'de eğri seçip spread, serbest forward'da eğrilerden gelen spot / faizler ve yazılan minor faizle fiyat, vadelere göre faizler), **Kota mesajı** (forward tablosunun puanları, satır çıkarma; OIS par'ı ± genişlik), **İşlem gir** (forward tablosundan ve Broker Chat'teki işlem satırından Günlük İşlemler'in dolu açılması: parite, yön, valör, puan; OIS vadesi, seviye, PAY, not, karşı taraf), Broker Chat'te **switch** (tahtada tek satır, ekrandaki switch modeli, eğriye göre yeri), Broker Chat'te **MPC tarihli OIS** (`mpc1`: tahtada kendi satırı, MPC OIS modeli ve ima PPK adımı; işlem satırından Günlük İşlemler'in MPC formunun toplantı günleriyle dolu açılması), **girilmemiş işlem** (menüde "1 işlem girilmedi" rozeti, tıklayınca liste, "Yok say" ve "Geri al", gün sonu arşivinden önce uyarı, listeden "⇢ Gir" ile girilince rozetin kalkması ve arşivin uyarısız inmesi), **en iyi fiyat** (en iyi bid'in broker'ı ve yaşı; bayat sınırı 10 dakikayken yarım saatlik daha iyi kotanın en iyi sayılmayıp kendi broker satırında soluk ve yaşıyla durması), carry'de **Listem**, **Spread Geçmişi** (offshore − OIS ve VİOP − OIS tabloları, pencere seçimi, grafik), Ayarlar'da **carry patikası ve ufku**, **Hazine İhalesi**'nde kısaltmayla yazılan nominal (`35m`) ve toplamı, tablo başlığının yazılan kâğıtla sayfa yenilenmeden değişmesi, **Ayarlar'da tatiller** (TRY · USD · EUR sekmeleri; iki kitabın birleşik TRY listesi, Fed tatilleriyle USD - Thanksgiving var, Good Friday ve cumartesiye düşen 4 Temmuz yok -, TARGET2 ile EUR, SIFMA / FOMC tarihleri; EUR'ya gün ekleyince EURTRY spot valörünün kayması - USDTRY ve Bloomberg valörleri yerinde -, kaydedilmemiş TRY yazısının sekme değişince kalması, gün ekleme, dosyaların listesine dönme), Forward'ın valör şeridinde **Bloomberg valörü** sütunları, Forward'ın **Kotasyon** sekmesi ve Masa'daki USDTRY ve EURTRY özetleri (her spread'in yanında TRY faizi, OIS + spread), Masa'da tarih arası forward'ın tarihlerinin Forward fiyatlama sekmesinden yazılması (sekme değişmeden, 90 gün, silince eski hâline dönmesi), **girdiye formül** (kırık vade valörüne `=`, başka tablodaki başlangıç tarihine düz tık - `=C60` -, `+7`, Enter: başlangıç + 7'nin `ƒ` ve "Formül: =C60+7" ipucuyla görünmesi; başlangıç yazılınca kendiliğinden izlemesi; F2'nin formülü göstermesi ve ortasına Ctrl+tıkla başvuru - `=C60+G60`; tamamlanmış başvurudan sonra düz tıkın yazmayı bitirmesi; Bloomberg işlevinin nedeniyle reddi, hücrenin yeniden açılması, formülün kalması; reddedilen formülden başka hücreye tıklayınca uyarının formülüyle çıkıp seçimin tıklanan hücrede kalması; **başka sekmenin hücresi**: sekme açılınca formülün kendi çubuğunda sürmesi, Faiz · PPK'daki anket ayına tıklama - `=S155+1`; Delete'in formülü de silmesi), Masa'nın VİOP sekmesinde DEALS'in vade sınırının ve hedeflerin tablolarının üstünde durması ve vade sınırı 1 yazınca DEALS'te her listede tek çift kalması, **OIS'in Parametreler'inin her sekmenin üstünde durması** ve En iyi işlemler sekmesinde DV01/bacak yazınca nominallerin iki katına çıkması, **Motor sayfasının yalnız yöneticinin menüsünde** olması, **Yedekleme** (yalnız yöneticinin menüsünde; varsayılan 17:30 ve veri klasörü, ikinci kopya seçilmemişken ipucu; göreli ve OneDrive klasörünün alanın yanında, gerekçesiyle reddi; seçilen saat ve klasörlerin kaydedilip "yönetici seçimi" olarak görünmesi; **Şimdi yedek al**: dosya, boyut, ikinci kopya ve iki klasörün listesi; seçilen klasör yazılamazken yedeğin dashboard'un kendi klasörüne gitmesi - sayfada ve durumda -, klasör geri gelince ulaşması; kullanıcıya 403 ve durumunda klasör olmaması; *Varsayılanlara dön*), tüm sayfalar, **Hata / Öneri · Sosyal · Ajanda** (bildirimin yöneticide canlı "!" olması ve İlgilenildi ile kalkması, kullanıcının listeyi görememesi; iki kullanıcı arasında canlı sohbet, düz metin, okunmamış sayısı, silinen mesajın her ekrandan gitmesi; ajandaya Bugün + saat + deadline, 15 dakika önce uyarı, gecikmiş deadline'ın önde olması, kişisel işin başkasına görünmemesi, başkasının tamamlaması; **tekrarlayan iş**: birkaç dakika sonrasına "Her iş günü" deadline'ı - iş günü değilse o günle "Seçili günler" -, uyarısının başka kullanıcının başka sayfasında "Ertele 10 dk" ve "Bugün tamam"la çıkması, aynı tarayıcının iki penceresinden yalnızca birinde çıkması, Ertele'nin yalnızca erteleyende susması, Bugün tamam'ın yalnızca o günü tamamlayıp her ekranda görünmesi, Tekrarlayan işler'de duraklatma ve silme), **İma Patikası ve TCMB WIRP** (her TCMB toplantısının iki 50 bp sonucuna bölünmesi, ardışık çiftlerin ayrık patikaları, kinkler, kalibrasyon, kayıtlı veri notu; Fed'in FOMC tablosundan on toplantısı 25 bp ızgarada; WIRP'te indirim / sabit / artırımın toplamı, matrisin beklenen patikasının ima patika olması, Masa!Q155'ten politika faizi ve TLREF farkı, tıklanan toplantının kova grafiği, Fed'in hedef aralıkları), **Öncü-Takipçi** (her aday çiftin listelenmesi - kayıtlı ay kısa: her biri nedenini söyler -, gün içi barların olmadığının yazması, DİBS RV listesinin kâğıtlarının vadesiyle adlanması, grup süzgecinin satırları daraltması, hatırlanması ve "Tümü"ye dönmesi), **VİOP** (VİOP sayfasının on iki kontratının canlı ask / bid ima faiziyle listelenmesi; kayıtlı veride Bloomberg geçmişi olmadığından adil değer ve emir seviyesi olmaması, sayfanın ve seviye panelinin bunu söylemesi; kontrat seçiminin seviye panelini o kontrata çevirmesi ve hatırlanması), **sinyal kartının düz anlatımı** (kayıtlı ayda sinyal çıkmadığından sunucunun biçimindeki bir FX ve bir faiz sinyaliyle, satıra tıklamanın yaptığı gibi: kartın başında cümle; "USDTRY 3A forward sat · 1 mn USD", forward kurlarıyla giriş / hedef / stop ve spot, 1 mn USD başına beklenen K/Z - forward primi ve kur hareketi ayrı -, hedefte / stopta para; faizde alınan / ödenen, bp ve TL; listede beklenen K/Z birimiyle - "+525 bin TRY / 1 mn USD", "+5,08 bp" -, FX'in girişi kur ve birimi "USDTRY 3A fwd"; sunucunun verdiği her sinyalin masa diliyle işlemi ve cümlesi), **Launchpad ve gezinme** (sayfadaki tablodan "+ Launchpad" ile yeni launchpad, Ctrl+K sonucundan ekleme, sürükle-bırak sıranın ve genişliğin yeniden yüklemede kalması, launchpad'de yazılan değerin kaynak sayfada görünmesi, tablonun seçilen sütunları, kendi sütun sırası - sayfada, yeniden yüklemede, launchpad'de; Excel sırasına dönüş -, ★ favori, açılış sayfası, yan panelin sayfalar arasında kalması ve Alt+Y, Alt+← / Alt+→ ile sayfanın sekmesi ve kaydırmasıyla dönmesi, ayrı pencerenin menüsüz ve canlı olması - toplu istekle, alarm denetimi olmadan -, launchpad'in ayrı penceresi, kaybolan ya da yetkisiz tablonun kutusunda söylenmesi), **kişisel hesap tablosu** (launchpad'e "+ Hesap tablosu", `=MASA!I60+25`'in -125 göstermesi ve formül çubuğu, kendi hücreleri üzerine formüller, Excel'den 2 × 2 blok yapıştırma, Bloomberg işlevinin nedeniyle reddi - hiçbir şey saklanmadan, hücre yeniden açılarak -, yan panele sabitlenen aynı tablonun Masa'da yazılan spread'le anında değişmesi, formül yazarken sayfanın hücresine Ctrl+tıkla ve `=` / işlemden sonra düz tıkla başvuru ekleme, tamamlanmış formülde düz tıklamanın yazmayı bitirmesi, yeniden yüklemede launchpad'de ve yan panelde kalması), **sayfaların kutuları** (yedi kutunun bir launchpad'de sayfalarının hafif kısmından çizilmesi - VİOP'un 12 kontratı ve ön vadenin seviyeleri, tahtanın enstrümanları, izleme listesi, TCMB'nin toplantıları -; yeni hesapla quant kutularının - VİOP'un ikisi tek istekle -, chat satırıyla tahtanın - akışın taşıdığı Broker Chat sayacıyla -, eklenen kalemle izleme listesinin yenilenmesi; kutudaki sinyale tıklayınca kartın kutunun üstünde, sayfanın element id'leri olmadan açılması ve "Sinyaller sayfasında aç"; kutunun kendi seçeneğinin - VİOP kontratı - öğeyle saklanması; sayfadaki panelin "+ Launchpad"i ile yan panele sabitleme ve orada canlı kalması, aynı id'nin iki kez olmaması; ⧉ ile ayrı pencere - menüsüz, sürümle yenilenen, yalnız kendi kısmını isteyen), **quant tablolarının cümleleri** (PCA / RV'de her tablonun başlığının hemen altında masanın diliyle cümlesi, yöntem notunun altta "Yöntem:" etiketiyle), **quant menüsü** (dört giriş ve sekme sayıları; eski adresin Faiz'i doğru sekmede açması ve menüde Faiz'in yanması; sekmenin kendi adresi ve son sekmenin yeniden yüklemede de hatırlanması; Ctrl+K'nın sayfayı kendi sekmesinde açması), **kendi menünüz** ("Menüyü düzenle…" ile bir sayfanın ve bir quant girişinin menüden çıkması ve hesapla saklanması; Ctrl+K'nın gizli sayfayı yine açması, yeniden yüklemede menünün kalması; başka kullanıcının menüsünün kendisinin olması, yönetici sayfalarının listede olmaması; "Hepsini göster"). Node.js + Playwright yoksa atlanır. |

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
duran tabloları sayar; yeni eklenen görünür bir tablo bir sekmeye yazılmadıysa test adını söyler. Bir tablonun okuduğu
bir girdi tablonun sekmesinde görünmüyorsa (`RefIndex.upstream`, `tto/xl/refs.py`: formüller girdilere kadar izlenir)
test tabloyu ve girdiyi söyler: girdiyi tablonun yanına koyun (üstüne bir girdi satırı - başka sayfanın hücreleri
`"sheet"` ve `"borrowed": true` ile -, aralığı genişletmek ya da `pinned`) ya da masanın ortak verisiyse gerekçesiyle
`REFERENCE` listesine yazın. `"header"` Excel'in
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
tto/xl/            Excel formül motoru (tokenizer, parser, derleyici, fonksiyonlar, sayı biçimleri, içe aktarıcı, başvuru dizini)
tto/marketdata/    Bloomberg (blpapi) ve kayıtlı veri sağlayıcıları; bbg_process.py: Bloomberg oturumunu ayrı bir
                   yardımcı süreçte çalıştırır
tto/extras.py      dashboard'un kendi eklediği hesaplar (Excel formülü olarak: EK_FWD, EK_XAU, EK_VIOP, EK_KAYNAK,
                   EK_BULK, EK_FX, EK_IHALE, EK_TATIL - USD / EUR tatilleri ve FX valörleri -, Borsa O/N, Bulk Bond'un
                   yeni satırları)
tto/service.py     uygulama servisi (sayfalar, girdiler, senaryolar, RET, işlem defteri)
tto/history.py     günlük tarihçe: kapanışlar, PPK fiyatlama geçmişi (çözücüyü geçmiş günle besleyen ikinci motor),
                   gün sonu matrisi, toplantı takvimi (düzeltme, kaydırma, adımların toplantıyla taşınması)
tto/blotter.py     forward fiyatlama (USDTRY, EURTRY, elle girilen pariteler; swap puanı), OIS strateji bacakları ve MPC
                   tarihli OIS, pozisyon maliyeti, DV01 (forward / OIS / tahvil; payer +) ve risk özeti
tto/brokerchat.py  broker chat ayrıştırıcısı: mesajlar (saat, gönderen, gün), kotalar (outright / spread / fly / FRA,
                   MPC tarihli OIS ve toplantı takvimiyle tarihlenmesi, FX swap puanı, DİBS; kısaltılmış seviyeler,
                   işlem / ref / ilgi), tahta ve eğriyle karşılaştırma
tto/watch.py       izlenenler (VİOP, kâğıt, OIS, offshore, masa, ifade, hücre), izleme listeleri, alarmlar (seviye, hareket, z-skoru), z-skoru, kendi kapanış kaydı, ısı haritası
tto/ops.py         operasyon: günlük dosyası (data/logs), döngülerin hataları, verinin tazeliği (bayat / sessiz yardımcı),
                   piyasa saatleri, veritabanının açılış denetimi ve günlük yedeği (17:30, data/backups, 30 adet; ikinci
                   kopyası D:\tto-yedek'te - D: varsa -, 30 adet; saati ve klasörleri yöneticinin seçimi: öncelik,
                   klasör denetimi, bulut klasörünün reddi; seçilen klasöre yazılamazsa data/backups'a alınması ve
                   klasör açılınca oraya kopyalanması), sistem alarmlarının koşulları (veri akışı, TLREF, veritabanı)
tto/deskalarms.py  masa alarmları: herkese çalan alarmlar ve sistem alarmları, "Gördüm" cevabı, kişisel susturma, günün kaydı
tto/bonds.py       TRY DİBS kataloğu (tto/data/try_bonds.json): ISIN kontrolü, ISIN'deki vade, chat'teki kâğıdın adayları
tto/volcarry.py    realized vol (yazılan enstrümanın günlük tarihçeden seviyesi, değişimlerin standart sapması,
                   forward için par eğrisinden bootstrap) ve carry'nin vol'e oranı
tto/fxvol.py       FX smile'ları (saf Python): Black, piyasanın delta / ATM kuralları, market strangle, SVI (varsayılan),
                   SABR, Vanna-Volga; smile'dan spotun risk-nötr dağılımı, kuantiller, yoğunluk denetimi
tto/fx.py          Spot / FX ve FX Vol İzleme: pariteler, ticker'lar, forward'lar (USDTRY offshore eğrisinden), yüzey,
                   olasılık matrisi, izleme istatistikleri (Makro bloğunun tanımı), FX tarihçesi, check-fx
tto/borsaspread.py Borsa Swap'ın OIS ve offshore mid spread'leri: TTO kitabının iki iskonto eğrisi (BOOT, offshore)
                   çalışma kitabının kuralıyla, iki tarih arası zero faiz; spot öncesi günler eğrinin O/N'uyla
tto/desk.py        masanın kendi köşesi: Hata / Öneri (yöneticilere), Sosyal (sohbet), Ajanda (tekrarlayan işler:
                   günleri, tamamlanmaları, uyarıları); yetki, uzunluk ve hız sınırları, canlı akışın bu üç parçaya
                   ait sayaçları; arayüzde desk.js, agendaalarms.js (tekrarlayan işlerin uyarıları), pages/agenda.js
tto/quantmath.py   quant istatistikleri, saf Python: EKK, Jacobi PCA, ADF (MacKinnon), Engle-Granger, OU, Kalman,
                   varyans oranı, Hurst, EWMA / GARCH, L2 lojistik regresyon, Newey-West
tto/quantfam.py    quant sinyal aileleri (25), ortak sinyal biçimi, bileşik puan ve uyum
tto/quantcurve.py  Eğri Adil Değeri: OIS ve DİBS'e Nelson-Siegel-Svensson (Excel'in OIS, BIST'in tahvil kuralıyla), zengin /
                   ucuz, carry + roll, receive / pay için en iyi kâğıt (iki aile)
tto/quantopt.py    Opsiyon: USDTRY / EURUSD vol yüzeyi, smile'ın forward'a göre olasılıkları ve gerçekleşen sıklık (bir aile)
tto/quantpath.py   ima PPK / FOMC patikası ayrık kararların karışımı olarak (İma Patikası) ve TCMB / Fed WIRP'ü:
                   ızgara, tutarlı patikalar (doğrusal kısıtlar), kinkler, kalibrasyon, evrişim matrisi, USD görüntüleri
tto/quantlead.py   öncü-takipçi: çapraz korelasyon ve asimetrisi, Granger F, dağıtılmış gecikme β'sı, kararlılık, yetişme
                   sinyali; hizalı her seride (gün ya da dakika barı), gün içi bar kaynağı için adaptör
tto/quantviop.py   VİOP: kontratlar (ticker, vade), ima TRY faiz, sabit vadeli seriler, adil değer ve sinyal, bugün / bu hafta
                   emir seviyeleri (yansıma ilkesi, gün içi profil, kalibrasyon), takvim etkileri, 5 dakikalık barlar
tto/quant.py       quant servisi: ayrı iş parçacığı, tarihçeye eklenen seriler, ayarlar, sinyal kaydı, alarmlar, API
tto/xlsx.py        gün sonu arşivi için küçük .xlsx yazıcı (yalnızca değerler ve biçimler)
tto/layout.py      kullanıcının düzeni: launchpad'ler, yan panel, favoriler, açılış sayfası, menüden çıkarılanlar - doğrulama,
                   sınırlar, öğe türleri (ITEM_TYPES: tablo, sayfaların yedi kutusu, hesap tablosu); arayüzde layout.js, boxes.js (kutu
                   ve toplu yenileme), pagebox.js / pageboxes.js (sayfaların kutuları), drawer.js, pages/launchpad.js,
                   menu.js (menü: quant'ın sekmeli girişleri, kendi menünüz)
tto/calc.py        kişisel hesap tablosu: hücreler, formüllerin denetimi (Bloomberg işlevlerinin reddi), motorla kullanıcının
                   kendi hesabı üzerinden değerlendirme, sınırlar, saklama, dışa / içe aktarma; arayüzde calc.js
tto/inputformula.py girdiye yazılan formüller (=C60+7): denetim (Bloomberg, döngü - motorun maskeleri ve formüllerin
                   başvuruları -, formül almayan ve takvimle kayan hücreler, Bloomberg isteğine giren hücreye canlı formül,
                   ortak formülün yetkisizliği), hesap tablosunun derleyicisiyle kişisel / ortak görünümde hesap, okuduğu
                   değişince yeniden hesap (nesil başına, piyasa hareketi olarak; formül yoksa iş yok), sonradan oluşan
                   döngünün ve süre aşımının durdurulması / ara verilerek yeniden denenmesi; arayüzde grid.js (işaretleme, ƒ, F2) ve
                   pointing.js (hesap tablosuyla ortak: başvurunun yazılışı, işaretlenebilecek yer)
tto/server.py      HTTP API + canlı güncelleme (server-sent events); oturum kapısı: girişsiz /api isteği 401
tto/auth.py        şifre özeti (PBKDF2-SHA256), oturum anahtarı, kilit ve süre ayarları
tto/store.py       SQLite (kullanıcılar ve oturumlar, girdiler, senaryolar, RET geçmişi, işlemler, broker chat, günlük
                   tarihçe, bildirimler, sohbet, ajanda ve tekrarlayan işleri)  →  data/tto.db
tto/bundled.py     kurulu değilse web paketlerini vendor/ altındaki wheel'lerden içe aktarır
tto/views/         sayfa tanımları: tablolar, girdiler, sekmeler ("sections") ve sekmelerin üstünde sabit duranlar ("pinned")
tto/data/          kayıtlı veri modunda kullanılan ek kotalar ve TLREF geçmişi (replay_*.json), DİBS kataloğu
tto/static/        arayüz (derleme gerektirmeyen ES modülleri, kendi SVG grafikleri; fan.js: olasılık bulutu)
models/            içe aktarılmış çalışma kitapları        workbooks/   kaynak Excel dosyaları
vendor/            gömülü web paketleri (değiştirilmemiş PyPI wheel'leri; Python 3.8 / 3.9 / 3.10+ setleri)
tools/             parite, LibreOffice referansı, içe aktarma, kayıtlı veri kotaları, tek dosyalık kurulumun üretimi, derinlik kontrolü
kurulum/           tto_kur.py: dashboard'un tamamı tek düz metin dosyasında (ZIP inmeyen / taşınamayan yerler için)
tests/             test paketi
```

Yedekleme için `data/tto.db` dosyasını kopyalamak yeterlidir.
