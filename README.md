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
  ve VİOP − OIS **spread geçmişi** (z-skoru) ve **Ayarlar**'da toplantı takvimi, carry'nin TLREF patikası, kişisel
  **eğri interpolasyonu** (Bootstrap (Murex) ya da PPK basamak: kotalı vadeler arasında bütün TRY eğrileri) ve masanın
  **eğri noktaları** listesi (OIS ve offshore eğrinin hangi noktalardan kurulduğu: ekle / kapat / not)
  ([aşağıda](#gün-sonu-matrisi-ppk-fiyatlama-geçmişi-ve-toplantı-takvimi)).
* **Kotadan işleme:** tablolardaki kotalar tek tıkla chat mesajı olur; bir kota, chat'teki bir işlem satırı ya da
  sayfalardaki bir fiyat (sağ tık → **İşlem gir**) Günlük İşlemler'i dolu açar; Forward'ın toplu forward tablosu
  tutarı yazılı satırlarını tek seferde işleme alır (**İşleme al**) ([aşağıda](#kullanım), *Fiyattan işlem*,
  *Tablodan işlem*).
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
  **eğri adil değeri** (OIS'e Nelson-Siegel-Svensson, DİBS'e Nelson-Siegel: zengin / ucuz, carry + roll, receive / pay için en iyi
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
* **Bugün (sabah ekranı):** dikkat isteyen her şey tek sayfada - RET bugün yüklendi mi, adil değerde güncellenen vadeler;
  açık Trades'in K/Z'si (son MTM'e göre) ve hedefine / stopuna yaklaşanlar; quant'ın önceki kapanıştan beri yeni AL / SAT
  satırları ve DİBS'te sinyali dönen kâğıtlar; girilmemiş işlemler, Ajanda'nın bugünü, PPK / FOMC. **Ctrl+K komut da alır:**
  `ret yayınla`, `işlem gir usdtry 1m 10mn`, `trade ois 1y 5mn`, `kâğıt ekle TRT…`, `senaryo S2` - hiçbiri kendiliğinden
  kaydetmez ([aşağıda](#bugün-sabah-ekranı)).

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

* **Anaconda:** `run.bat` önce Anaconda'yı (ya da Miniconda'yı) açar - Anaconda Prompt'un yaptığı gibi
  `Scripts\activate.bat` ile -, sonra o Python'la başlatır; komut penceresi açılamayan makinede de `run.bat`'a çift
  tıklamak yeter (masa, 19.11.2026: "Normal cmd'ye erişim olmadığı için anaconda prompt ile runlıyorum"). Bilinen
  yerlere bakar: `%USERPROFILE%\Anaconda3`, `Miniconda3`, `miniforge3`, `%LOCALAPPDATA%\anaconda3`,
  `%LOCALAPPDATA%\Continuum\anaconda3`, `%ProgramData%\Anaconda3` …; başka bir klasördeyse `TTO_CONDA` ortam
  değişkenine o klasörü yazın. Anaconda yoksa eskisi gibi `python`, sonra `py -3`.
* **Python var mı?** Komut penceresinde `python --version` (ya da `py --version`). Hiç yoksa python.org'daki
  *Windows embeddable package (64-bit)* zip'i de kurulum istemez: içindekileri proje klasörüne açıp
  `python.exe -m tto` çalıştırılır. Bu yol bu ortamda denenemedi.
* **Güncelleme:** yeni ZIP'i indirip eskisinin üzerine açın; `data` klasörüne dokunmayın (kullanıcılar, senaryolar,
  RET geçmişi ve işlem defteri orada).
* **Bilgisayarın kendi diskine kurun** (C:, D:), ağdaki bir paylaşıma değil; bir `data` klasörünü aynı anda tek
  dashboard açar (bkz. [Veritabanı](#veritabanı-tutarlı-yazma-açılış-denetimi-günlük-yedek)).
* **Güvenlik duvarı sorusu** çıkarsa ve yalnızca kendi bilgisayarınızdan kullanacaksanız `python -m tto --host 127.0.0.1`
  ile açın; soru çıkmaz.
* **Canlı Bloomberg verisi** için o Python'da `blpapi` paketi bulunmalıdır (`python -c "import blpapi"` hata
  vermiyorsa vardır). Yoksa dashboard kayıtlı veriyle açılır. Kurulamıyorsa, kurulum gerektirmeyen yol
  [vendor/README.md](vendor/README.md) içinde (`vendor/local`).

### ZIP inmiyorsa: tek dosya

Bazı ağlarda GitHub'ın "Download ZIP"i engellenir, e-posta servisleri de içinde `.bat` / `.js` bulunan arşivleri
kabul etmez (Gmail: *"yürütülebilir dosyalara ve arşivlere yönelik politika"*). Dosyalar tek tek inebiliyorsa
[`kurulum/tto_kur.py`](kurulum/tto_kur.py) yeter: dashboard'un çalışması için gereken her şeyi (program, içe aktarılmış
çalışma kitapları, web paketleri) taşıyan **tek bir düz metin dosyası** (~6,5 MB). Aynı dosya
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
`--bbg-host`, `--bbg-port 8194`, `--tick 2` (ekran yenileme, sn), `--no-stream`, `--price-poll 900`,
`--daily-budget 100000` (günlük Bloomberg bütçesi; [Önce önbellek](#önce-önbellek-bloombergin-günlük-limiti-24112026)),
`--max-hits 400000`,
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
* **Kim çevrimiçi.** Üst çubukta, kullanıcı düğmesinin solunda **"● 3 çevrimiçi"** durur (pencere 1700 pikselden darsa
  yalnız "● 3"; uzakta olanların sayısı üzerine gelince yazar). Tıklayınca masanın kullanıcıları listelenir: **●
  çevrimiçi**, **◐ uzakta** (ne kadardır) ya da **○ çevrimdışı**, **son görülme** ("şimdi", "12 dk önce", "dün 18:40",
  "14.11 09:12") ve **son giriş**. Liste herkese aynıdır ve canlı akışla güncellenir - biri gelince, uzaklaşınca ya da
  çıkınca açık liste kendiliğinden yenilenir; hiçbir şey durmadan sorulmaz (sayı canlı akışla gelir, liste yalnızca
  açıkken ve birinin durumu değişince istenir; "12 dk önce" yazıları 30 saniyede bir yeniden yazılır).
  **Çevrimiçi**: dashboard bir tarayıcıda açık - tarayıcı canlı akışı tutuyor (bir tarayıcının sekmeleri tek akışı
  paylaşır) ya da son **2 dakikada** sunucudan bir şey istemiş - ve sekmelerinden birinde (ayrı penceresi dahil) son
  **15 dakikada** klavye, tıklama, kaydırma ya da fare hareketi olmuş; sayfa bunu sunucuya **dakikada en fazla bir kez**
  söyler, 15 dakikalık aradan sonraki ilk hareket hemen duyulur. **Uzakta**: açık ama 15 dakikadır kullanılmıyor
  (sayfaların kendiliğinden yenilenmesi kullanım sayılmaz). **Çevrimdışı**: ikisi de değil. **Çıkış** yapan anında
  çevrimdışı olur (başka bir tarayıcıda açık değilse); tarayıcısını kapatan, son isteğinden en geç 2 dakika sonra.
  **Son görülme** kullanıcının en son bağlı olduğu andır (akış açıkken "şimdi"); veritabanına kullanıcı başına
  **dakikada en fazla bir kez**, çıkışta ve dashboard kapanırken hemen yazılır - yeniden başlatmada kaybolmaz. **Son
  giriş** şifreyle en son giriştir (önceki sürümün veritabanında, o zamanki "son görülme" girişte yazıldığı için oradan
  alınır). Listede yalnızca **etkin ve şifresi olan** hesaplar vardır: onay bekleyen istekler, kapatılmış hesaplar ve
  önceki sürümün şifresiz kullanıcıları ne listelenir ne sayılır. Girişin geldiği **adres (IP) hiçbir kullanıcıya
  gösterilmez**; yalnız yöneticilerin *Kullanıcılar* sayfasında, son girişin yanında durur. O sayfada da **Son görülme**
  (şu an bağlıysa çevrimiçi / uzakta) ve **Son giriş** sütunları vardır, canlı güncellenir. Kimin hangi sayfada olduğu
  gösterilmez (bir tarayıcıda birkaç sekme açık olabilir: güvenilir bir bilgi değil). Durumları sunucu kendi iş
  parçacığında 5 saniyede bir ve bir değişiklikten hemen sonra hesaplar (`tto/presence.py`): `GET /api/presence`
  listeyi verir, `POST /api/presence` sayfanın "biri kullanıyor" haberidir, canlı akış sayıları taşır.
* **Güvenlik.** Şifreler veritabanında yalnızca tuzlanmış PBKDF2-SHA256 özetiyle (600.000 tur) durur; oturum
  anahtarı tarayıcıda JavaScript'in okuyamadığı (HttpOnly, SameSite=Strict) bir çerezdedir, veritabanında yalnızca
  özeti tutulur. Betikler aynı anahtarı `Authorization: Bearer …` başlığıyla gönderebilir. Önceki sürümün `X-TTO-User`
  başlığı ya da `?user=` artık kimseyi içeri almaz. Tarayıcının **başka bir sayfadan** (başka site ya da bu
  bilgisayarın başka bir portu) gönderdiği değişiklik isteği reddedilir. İsimde görünmeyen karakter olamaz; tam
  genişlikte ya da ayrık yazılmış harf harfin kendisidir. Aynı anda en fazla 2 şifre denetlenir (yoğun deneme sunucuyu
  kilitlemez). Dashboard düz HTTP ile çalışır: şifre yerel ağda şifrelenmeden gider (HTTPS ayrı bir iş).

**Sayfalar.** Masa, OIS · PPK, Forward, VİOP, Borsa Swap, Carry & Roll, OIS · Nakit Akışı (Excel'de "TM OIS"), DİBS
RV (menüde tek giriş, üç sekme: **Genel**, RV hesap tablosu ve ASW hesap tablosu - DİBS RV ve DİBS ASW sayfaları;
aşağıda, *DİBS RV (genel sayfa)*), Manuel Tahvil, Eurobond Kotaları (Excel'de "Bulk Bond": masanın XS ISIN'li Türk banka / şirket
Eurobond'ları, dealer fiyat kaynaklarıyla), DV01 Risk, USD · FOMC, Hesaplayıcılar ve - yalnızca **yöneticilere** -
Motor (çalışma kitabının motoru: bootstrap, çözücü, tatiller; menüde, aramada ve kısayollarda başkasına görünmez,
`/api/view/motor` başkasına 403 verir; tatiller Ayarlar'dan düzenlenir). Ek olarak **İzleme · Alarmlar** (her kullanıcının
izleme listesi: VİOP spread'i, kâğıt ASW'i, OIS, offshore, ifadeler, hücreler; z-skoru; seviye, hareket ve z-skoru
alarmları; günün masa notları), **Eğri Hareketi** (OIS, offshore, VİOP ve DİBS'in önceki kapanıştan / açılıştan /
referanstan değişimi, ısı haritası), **Tüm Kâğıtlar** (masanın bütün
TRY DİBS'leri, türüne ve vadesine göre - TLREF ve FRN ayrı; ISIN ile eklenir, ✕ ile çıkar; ★ ile trading listesine), **DİBS Trading** (trading listesinin özeti, T0 / T1 / T2 fiyatları, son
işlemler, ima repo, günün işlemleri), **Hazine İhalesi** (üç kâğıt için ihaleye gönderilecek kirli fiyat ve ihale
sonucu), **Günlük İşlemler**, **Fiyatlama** (TRY OIS, FRA, XCCY ve FX forward'ın kırık vadede mid'i, DV01 kovaları ve
NPV'si, iki eğride; aşağıda, *Dashboard'un kendi ekledikleri*), **Swaption** (TRY OIS swaption'ı, yalnız görüntüleme:
forward, gerçekleşen vol, payer / receiver / straddle primi ve greek'leri, başabaşlar; aynı bölümde),
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
| Forward | **Hesaplayıcılar** (Interest 2 SP, SP 2 Interest, all-in, O/N karşılığı, basit ↔ bileşik, tarih yardımcısı, tahvil carry: repodan başabaş ve fiyattan repo …) · Forward fiyatları (USDTRY, EURTRY, serbest forward, vadelere göre TRY faizleri, Forward DV01) · **Kotasyon** (OIS + spread'ten USDTRY / EURTRY forward kotasyon matrisleri, puandan ve faizden spread) · RET · Toplu fiyatlama · Eğriler · Offshore · Ticker'lar |
| VİOP | Kontratlar · **Hesaplayıcılar** (VİOP XAUTRY) · Altın · Takvim spread matrisleri · Geçmiş · baz (ima faiz ve OIS farkının tarihsel grafikleri) · Eğriler |
| Masa | Genel bakış · Forward fiyatlama (USDTRY ve EURTRY kotasyon matrislerinin özeti, tarih arası forward ve tarihleri, kırık vade) · Faiz · PPK (tarih arası faiz, kotadan spread'i, **toplu tarih arası faiz**) · VİOP · Sinyaller · Makro |
| OIS · PPK | Kotalar · Hesaplayıcılar (stub) · PPK ima (MPC OIS / MPC SPREAD ve **faizden / spread'den PPK adımı**) · En iyi işlemler · Tüm listeler (TÜM FORWARD / FRA'da **hedef FRA → gereken bacak**) (Parametreler hepsinin üstünde sabit) |
| Hesaplayıcılar | Faiz çevirici (üst bant, basit ↔ bileşik, DF, exponential / simple, implied move ve tersi: hareketten vol) · Maliyet · Tahvil · diğer |
| DV01 Risk, USD · FOMC, Carry & Roll, Motor | konularına göre 3–4 sekme |
| DİBS RV (menüde tek giriş) | **Genel** (trading listesi tek tabloda: OIS ASW, FX swap ASW, sıfır kupon eğrisi; getiri eğrisi ve iki ASW grafiği) · **RV hesap tablosu** (DİBS RV sayfası, `#/dibs`) · **ASW hesap tablosu** (DİBS ASW sayfası, `#/asw`) |

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
etiketi (Mar28, Eyl35 …), üstünde kesik çizgiyle uydurulan eğri; geçmiş grafiği tarih ekseninde. ASW grafiği aynı sayfada
bir kez daha, **FX swap eğrisine göre** çizilir (aşağıda, *Borsa Swap ve DİBS ASW*). Panonun kendi XY grafikleri
**basamak çizgisi** de çizer (bir değer bir sonraki noktaya kadar sürer): böyle bir grafikte fare bir güne gelince her
çizginin o günkü değeri, grafiğin söylediği farklar (bp) ve o günün işaretleri görünür; eksendeki işaretler (kotalı vade:
grafiğin üstünde açık kesik çizgi ve adı; toplantı: eksende kısa çentik) yanına gelen fareyi kendi gününe çeker - OIS ·
PPK'nın interpolasyon grafiği (aşağıda, *TRY faizleri iki yoldan*).

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
* **Hesap** (üst şerit; `tto/progress.py`): arka planda uzun bir hesap sürerken - quant tam hesabı, Makine öğrenmesi
  modelleri, yürüyen geri test, tarihçe güncellemesi - üst şeritte nerede olduğu yazar, yalnızca o sürece:
  `Hesap · Quant 14/26 · ML 240/480 · geri test 12/25 · ~3 dk`. **Quant** tam hesabın adımları (ailelerin süresini
  yazdığı her adım; 26 adım), **ML** bu hesapta eğitilecek modeller (önbellekte olanlar sayılmaz: aynı kapanışlarla
  ikinci hesapta hiç yok, güncellemeden sonraki ilk hesapta hepsi - ~500), **geri test** yeniden kurmalar (25), **tarihçe**
  Bloomberg'den istenen seriler, ardından **PPK geçmişi** hesaplanan günler. Tıklayınca her hesap ayrı satırda: şu anki
  adımı (ör. "Trend", geri testte "Mart 2026 · 14.03.2026 kapanışıyla"), yapılan / toplam, ne zamandan beri, geçen süre,
  **kalan süre** (tahmini, "~"). Kalan süre ölçüye dayanır, tahmin uydurulmaz: aynı türden birimlerde (model, yeniden
  kurma, seri, gün) üç birim bittikten sonra bu çalışmanın hızı, öncesinde son çalışmanınki (bir modelin süresi yalnız
  eğitimi: önbellekteki satırlar sayılmaz); tam hesapta son tam hesabın adım süreleri - güncellemeden / açılıştan sonraki
  **ilk** tam hesap (önbellekler boş: dakikalar) ile sonrakiler (saniyeler) ayrı ölçülür -, ML adımı çalışırken kendi
  modelleriyle; sürmekte olan adım geçen süresini aşarsa sıfırın altına inmez, geri test bütçesini (900 sn) aşmaz, iki
  saatin üstü yazılmaz, ölçüsü olmayan işte boş kalır; aynı anda birkaç hesap varsa en uzunu. Süreler veritabanında
  (`progress.runs`) saklanır: güncellemeden sonraki ilk hesap da tahminini bilir (bu sürümün ilk hesabı hariç: ölçüsü
  henüz yok). Şerit sayfaların zaten 15 sn'de bir sorduğu durumla gelir; bir hesap sürerken birkaç saniyede bir
  `/api/progress` sorulur (sayaçlar okunur, hiçbir şey hesaplanmaz), boştayken hiç. Sayaçlar hesabı yavaşlatmaz
  (ölçüm: [Quant sinyaller](#quant-sinyaller)).
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
* **İki yönlü tablolar** (masa, 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar bu
  şekilde olmalı karışıklık olmaması için"). Böyle bir tabloda bir satırın değerlerinin **hepsi** yazılabilir (ilki
  Forward'ın FORWARD KOTASYON'u: spread, TRY %, puan ve fwd, bid ve ask ayrı): **hangisini yazarsanız o kalır**, aynı
  satırın (ve aynı tarafın) diğerleri ondan hesaplanır. Yazılan hücre kalın ve köşesinde **✎** ile işaretlidir; üzerine
  gelince "Yazdığınız değer: satırın … değerleri bundan hesaplanır" der, öbürleri "Hesaplanan: bu satırda yazılan …"
  der. **Son yazılan geçerlidir:** başka bir sütuna yazınca önceki yazdığınız gider, yenisi kalır; yazılan değer piyasa
  değişse de aynen durur, diğerleri piyasayla değişir. `Delete` (ya da sağ tık → "Kendi girdimi sil", "formüle dön")
  satırın **herhangi** bir hücresinde satırı varsayılanına döndürür. Excel'den yapıştırılan blokta bir satırın her
  tarafının (bid / ask) en sağdaki dolu değeri o tarafın yazılanıdır (aynı taraftaki boş hücre onu silmez); yalnız
  boşlardan oluşan taraf varsayılana döner. Formül (`=`) de yazılabilir; satırın (aynı tarafın) kendi başka bir değerini
  ya da ondan hesaplanan bir hücreyi okuyan formül döngüdür, **yazarken** reddedilir - okuduğu değer o an elle yazılmış
  olsa da (yazınca o silinir, sonra o da bu formülden hesaplanırdı); nedeni de, durmuş bir formülün nedeni de sayfadaki
  hücreleri söyler. Senaryolar, "Girdilerimi sıfırla" ve geçici kopyalar yazılan değerleri olduğu gibi tutar (kopyada
  tablonun kendisine yazılmış bir değerin satırına kopyada başka bir sütun yazılamaz: nedeni söylenir; satırın yalnız bir
  değerini gösteren tablonun kopyası da satırın tamamını tutar - kopyada yazdığınız, tabloda öbür bir değere yazılmış olanı
  kopyada geçersiz kılar). **Tablo iki yönlü
  olmadan önce** bu hücrelere yazılmış değerler - "Elle değer" ya da o zamanki girdinin değeri, **formülüyle** - satırlarının
  yazılanı olur, formül canlı kalır; masanın ortak değerleri ve o tablonun daha önce açılmış geçici kopyalarındaki
  değerler de öyle (günlük dosyasına yazılır).
  İki yönlü tablolar: Forward'ın FORWARD KOTASYON'u; Hesaplayıcılar sayfasının hesaplayıcıları ve DV01 Risk'in
  Senaryo P&L'i (*Hesaplayıcılar iki yönlü*, aşağıda); VİOP'un Target tablosu (*VİOP Target — iki yönlü*); sayfası
  tablo olmayanlarda aynı kural kendi kutularında: Prop panelinde kayıp ya da büyüklük, Swaption'da vol ya da bir
  prim / başabaş.
* **Girdiye formül (Excel'deki gibi `=`).** Sarı ya da yeşil bir girdi hücresine `=` yazıp başka bir hücreye tıklayın:
  adresi formüle girer - aynı tablonun, sayfanın başka bir tablosunun, **başka bir sekmenin** (sekmeye tıklayınca formül
  pencerenin üstündeki kendi çubuğunda sürer), yan panelin ya da bir launchpad kutusunun hücresi. Aynı sayfanın hücresi
  yalın adresiyle (`=C60+7`), başka sayfanınki adıyla (`=Forward!D2`), başka kitabınki köşeli parantezle
  (`=[sofr]SOFR_FOMC!B9`) girer; sürükleyince aralık (`P94:P99`). Düz tık başvurunun girebileceği yerde çalışır
  (`=`, bir işlem, parantez ya da ayırıcıdan sonra; az önce eklenenin yerine), **Ctrl+tık** formülün her yerinde; başka
  bir yere tık yazmayı bitirir. `Enter` kaydeder, `Esc` vazgeçer. İşlevler, `;` ve ondalık virgül kişisel hesap
  tablosundaki gibidir (aynı derleyici ve hesap). Sütunları kendi sıranızda ya da bir launchpad kutusunda bir kısmı
  gösterilen tabloda sürüklenen blok, çalışma kitabında tek bir aralıksa girer (sıranız V, U ise `U10:V10`); ekranda yan
  yana olup arada gösterilmeyen satır / sütun bırakıyorsa (MPC1 → MPC3, arada MPC2) **girmez** - başvuru işaretlenmeyen
  hücreleri de kapsardı -, uyarı çıkar, önceki başvuru kalır (Excel'de gizli ya da boş olduğu için tabloda olmayan satır /
  sütun Excel'deki gibi aralığa dahildir). Dashboard'un kendi tablosunun (DİBS işlem akışı) ve bir tabloya eklediği
  sütunun (Broker bid, Kart …) hücresi bir çalışma kitabı hücresi değildir: "Bu tablonun hücreleri bir çalışma kitabı
  sayfasında değil" uyarısı çıkar, formüle bir şey girmez. Başvurusu eklenen hücrelerin işareti, tablosu yeniden çizilse de
  (bir satır eklenmesi, sıra değişmesi) kalır.
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
  formül. Listeli hücreler (B/S …), "Elle değer" hücreleri, **toplantısıyla taşınan hücreler** (bir toplantının tarihi,
  toplantı başına yazılanlar ve masanın etiketi: TCMB'de `OIS_MAIN!P`, `U:W`, `O` - satır 10–89 - ve Motor'un
  `D4311:D4390` / `A4481:A4560`'ı; Fed'de `SOFR_FOMC!B`, `C`, `P`, `R:T` - satır 74–83; takvim değişince değerleri
  toplantısıyla taşınır), **tatil listelerinin hücreleri** (TRY: `Motor!A361:B523` ve DİBS ASW'deki kopyası
  `ASW!LR2:LR200`; USD ve EUR: `EK_TATIL`'in tarih ve ad sütunları - Ayarlar → Tatiller'de kayıt bütün listeyi tarih
  sırasıyla yeniden yazar, formül kalmaz ya da başka günün satırına düşerdi) ve **listelerin anahtar hücreleri** (DİBS
  RV, DİBS ASW ve Eurobond Kotaları listelerinin ISIN'leri - `DİBS RV!A5:A54`, `ASW!B7:B56`, `Bulk Bond!A3:A52` -, VİOP
  kontrat kodları - `VIOP!L1:W1`, `M45:O45`, `M60:O60`: satırın değerleri kâğıda, alarmlar kontrata bunlarla bağlıdır,
  kendiliğinden değişen bir anahtar onları koparırdı; ISIN'i / kodu yazın) formül almaz. Bu toplantı hücrelerine
  **başvuran** formül ise takvimle birlikte toplantısının peşinden gider, Excel'de satır taşınınca olduğu gibi:
  `=OIS_MAIN!P12+1` araya toplantı girince `=OIS_MAIN!P13+1` olur; listeden çıkan toplantıya başvuru `#REF!` olur.
  **Hesaplanan** toplantı hücrelerine (ima adım `R`, ima PPK `S`, patikalar `X:Z`, MPC OIS …) başvuru yerinde kalır:
  `=OIS_MAIN!R10` her zaman sıradaki toplantının (MPC1) ima adımıdır (aşağıda, toplantı takvimi). Değeri bir **Bloomberg
  isteğine giren** hücreye (Forward'ın valörü, ticker'lar …) canlı fiyat ya da `NOW()` okuyan formül yazılmaz - her
  tikte yeni bir istek doğururdu; `=TODAY()+30` gibi günde bir değişen olur; değeri hata olan formül de yazılmaz (istek
  boş bir değerle giderdi; hata nedeniyle söylenir). Sonradan hata olursa (ör. başvurduğu toplantı listeden çıktı:
  `#REF!`) hücre son iyi değerini korur, hatayı neden olarak yazar; değer yeniden gelince yine yazılır. Reddedilen
  formül `Enter`'la yazıldıysa hücre aynı metinle yeniden açılır; başka bir yere tıklandıysa yalnızca uyarı çıkar
  (formülüyle), seçim tıklanan yerde kalır.
  **Duramayacak formül kalmaz.** Önceki bir sürümün aldığı ya da bir senaryonun geri getirdiği formül artık duramayacağı
  yerdeyse - toplantısıyla taşınan ya da tatil listesinin hücresi, listenin anahtar hücresi (ISIN, kontrat kodu), artık
  girdi olmayan ya da kapsamı değişen hücre (kişisel girdi ortak oldu), bu sürümün kabul etmediği metin (Bloomberg
  işlevi) - açılışta, senaryo yüklenince hemen kalkar: değeri değer olarak kalır, günlük dosyasına nedeniyle yazılır.
  Böylece "Girdilerim" artık hiçbir şeyi izlemeyen formülü ƒ ile listelemez, kaydedilen senaryo onu yeniden saklamaz.
  **Durmayan döngü, takılan formül olmaz.** Sonradan oluşan bir döngü (okuduğu girdinin kendi formülüne dönmesi gibi)
  dönüp durmaz: formül birkaç turdan sonra durur, değeri `#CALC!`, nedeni hücrede. Hesap süresi sınırını aşan formül
  (yeniden başlatma sonrası soğuk hesap) değerini korur, biraz sonra yeniden denenir, ancak üst üste birkaç kez aşarsa
  durur. Duran formül, sahibi bir girdi yazınca bir kez hemen, yine durursa artan aralıklarla yeniden denenir;
  yeniden yazınca hemen. Değeri bir Bloomberg isteğine giren hücrede duran formül `#CALC!` yerine **son iyi değerini**
  korur (orada hata değeri boş bağımsız değişkenli yeni bir istek olurdu), nedeni hücrede. Durmadan hataya düşen formül
  de (okuduğu bir değer bozuldu: `#DIV/0!`, `#N/A` …) orada son iyi değerini korur, hata nedeni hücrede yazar ("Formülün
  değeri hata (#DIV/0! - Sıfıra bölme) · … son iyi değeri kaldı"); formül izlemeyi sürdürür, yeniden değer verince değer
  yazılır, neden kalkar. Bloomberg'e girmeyen hücrede hata Excel'deki gibi hücrenin değeridir. Piyasayı izleyen formülün
  değişmesi masa değişikliği sayılmaz (kendi girdisi olanların sayfaları piyasa hareketindeki gibi yenilenir); formülü
  yazmak ya da değiştirmek sayılır.
* Yüzde hücrelerine `35,5`, `35,5%` ya da `0,355` yazılabilir (Excel'in otomatik yüzde girişi gibi).
* **Nominal / tutar** hücrelerine masanın kısaltmasıyla da yazılır: `5m` / `5mn` / `5mln` = 5.000.000, `250k` /
  `250 bin` = 250.000, `1,5mn` (İngilizce biçimde `1.5mn`; ikisi de iki biçimde okunur) = 1.500.000, `2b` / `2mr` /
  `2mlr` / `2 milyar` = 2.000.000.000, `1,5 milyon`, `2,5 mio` (Hazine İhalesi'nin teklif ve gerçekleşen nominali; OIS'in "DV01/bacak $"ı, "Yuvarlama TL" ve
  "Nominal C+R"'si, USD · FOMC'un "Hedef DV01 ($/bp)"si, DV01 Risk'in "Murex P&L" ve "Yeni işlem / day-1 P&L"si,
  OIS · Nakit Akışı'nın "Nominal (TL)"'si, Forward ve Hesaplayıcılar'ın "Tutar"ı). Bu hücrelerde anlaşılmayan bir tutar hata
  verir, metin olarak kalmaz (kalsaydı tutarlar ve toplamlar sessizce boş görünürdü). DİBS RV'nin "Sat nominal
  (mn)"'si zaten milyon cinsindendir, kısaltma almaz. **Hangi hücre tutar:** sayfa tanımında `"kind": "amount"` diye
  işaretlenen girdi - sayı biçimi ayırt edemez (tutar da swap puanı da `#,##0`); faiz, fiyat, puan hücrelerinde `5m`
  eskisi gibi yazıldığı metin olarak kalır, hiçbir şeyle çarpılmaz. Hesaplayıcılar'daki ağırlıklı ortalama tablosunun
  "Amount" sütunları (`Z39:Z52`, `AC39:AC52`) faiz sütunlarıyla tek girdi olarak tanımlı olduğundan kısaltma almaz.
* **Tarih tutan her hücre tarih görünür.** Çalışma kitabında tarih tutup biçimi tarih olmayan hücreler (General, sayı ya
  da muhasebe biçimi) `gg.aa.yyyy` görünür: Forward DV01'in **Start**'ı (`Forward!O33 = +I2`, Excel'de de 46.344,0000
  görünüyordu) ve RET tablosunun spot valörü (`V75`), Forward'ın Bloomberg valörleri (`F8:F21`), DİBS RV'nin vade / kupon
  / valör sütunları, DİBS Canlı ve Tüm Kâğıtlar'ın son işlem günleri, VİOP'un kontrat vadeleri (bütün blokları), Hazine
  İhalesi'nin valör / vade / kupon tarihleri, DİBS ASW'nin vadeleri - 1 263 hücre (TRY kitabında 1 213, DİBS ASW'de 50;
  çoğu yardımcı tablolarda). Değeri, formülü, kalınlığı, rengi, hizası aynı kalır, yalnız sayı biçimi değişir;
  Bloomberg'in metin olarak gönderdiği tarih ("30.11.2026") zaten öyle görünüyordu, değişmez. **Hangi hücrenin tarih
  tuttuğunu formüller söyler** (`tto/datecells.py`): tarih biçimli hücre, `TODAY` / `DATE` / `EDATE` / `EOMONTH` /
  `WORKDAY`, Bloomberg'in tarih alanı (`SETTLE_DT`, `MATURITY`, `LAST_TRADE_DATE` …), tarihe başvuru (`=+I2`,
  `=SPOTDATE`), tarih ± gün; dalları hep tarih (ya da boş / metin) olan `IF` / `IFERROR` / `CHOOSE` / `MIN` / `MAX` /
  `INDEX` / `VLOOKUP` … tarihtir. **Sayı sayı kalır:** iki tarihin farkı (gün sayısı: `O35 = O34-O33`), yıl kesri,
  `*` / `/`, tarihle sayıyı karıştıran formül, biçimi sayı olan sabit (elle yazılmış 46000) tarih sayılmaz. Bütün kitabı
  okumak birkaç saniye sürdüğünden kural her açılışta değil testte koşar: bulduğu hücreler `tto/datecells.py`'deki
  `SHOWN` listesidir, açılışta her biri kurala tek tek bir kez daha sorulup gösterilir; kitap yeniden içe aktarılınca
  `tests/test_datecells.py` neyin değiştiğini söyler, `python -m tto.datecells` yeni listeyi yazar. Sayfa tanımında tarih
  diye tanımlı ama biçimi tarih olmayan girdi de tarih görünür (tatil listelerinin sondaki boş satırları: DİBS ASW'nin
  TRY listesi `ASW!LR154:LR200`, USD SOFR'un ABD listesi `SOFR_FOMC!BO63:BO70`; VİOP Target'ın kontrat listesi metin
  tuttuğundan hariç).
* **Tarih kısayolları.** Tarih hücrelerine (tarih biçimli, yukarıdaki kuralla tarih görünen ya da sayfa tanımında tarih
  diye işaretlenmiş girdi; "Elle değer" ile üzerine yazılan tarih formülü de) ve Günlük İşlemler'in valörüne vade de
  yazılır; saklanan, karşılığı olan tarihtir, yazılan kısayol hücrenin ipucunda kalır ("Kısayol: 3m → 04.02.2027";
  Günlük İşlemler'de kutunun altında). Büyük / küçük harf önemsizdir: `3m` = `3M` = `3A`, `18m`, `1y`, `2w`, `on` …;
  tarih hücresinde `3m` üç aydır, tutar hücresinde (`"kind": "amount"`) 3.000.000:

  | Yazılan | Tarih |
  |---|---|
  | `1A` / `1M`, `3A`, `6A`, `18M` | o kadar ay sonrası (`EDATE`), tatil ya da hafta sonuysa sonraki iş günü - çalışma kitabının vadeleri saydığı kural |
  | `1Y`, `2Y` | yıl (12 ay) |
  | `2H` / `2W` | hafta (7 gün), aynı kuralla |
  | `ON` · `TN` · `SN` (`O/N` …) | bugünden 1 iş günü · bugünden 2 iş günü · başlangıçtan 1 iş günü |
  | `ay sonu` (`aysonu`, `EOM`) | başlangıcın ayının son iş günü (başlangıç o gün ya da sonrasıysa sonraki ayın) |
  | `IMM` | başlangıçtan sonraki ilk IMM tarihi (Mart / Haziran / Eylül / Aralık'ın üçüncü çarşambası; tatilse sonraki iş günü) |
  | `+5` | başlangıçtan 5 iş günü sonrası |

  **Başlangıç** hücrenin doğal başlangıcıdır: satırın spot / valör tarihi (serbest forward listesinde ve kırık vade /
  tarih arası bloklarında bitiş tarihinin başlangıcı, hesaplayıcılarda 1. tarih), yoksa paritenin bugünkü spot valörü.
  **Takvim** paritenin iki para biriminin tatil listesi ve spot kuralıdır: USDTRY T+1 (TRY + USD; Forward, Masa'nın forward
  blokları, VİOP spotu), EURTRY T+2 (TRY + EUR; EURTRY matrisi ve hesaplayıcıların EURTRY sütunu), serbest forward
  listesinde satırın paritesi; hiçbir pariteye bağlanmayan tarih hücresi TRY para piyasasınındır (çalışma kitabının
  SPOTDATE'i, TRY listesiyle T+1: OIS, tahvil, VİOP Target'ın uzak kontratı …). **Her hücre nasıl karar verir:**
  1. Sayfa tanımındaki `"tenor"` (`tto/views/__init__.py`) söyledikleri için geçerlidir: `"pair"` / `"pair_col"` (satırın
     paritesi), `"from"` (başlangıç); `"from"` yazmayan tanım spot'tan sayar.
  2. Söylemediğini formüller söyler (`tto/datecells.py`). **Parite**, hücrenin yapıldığı tarihlerin paritesidir: formülü
     USDTRY'nin spot valöründen (`Forward!I2`) geliyorsa USDTRY, EURTRY'ninkinden (`Forward!K2`) geliyorsa EURTRY, OIS spot
     valöründen (`OIS_MAIN!B2`, `SPOTDATE`) geliyorsa TRY para piyasası; sayfa tanımında paritesi yazılı bir girdiden
     geliyorsa onunki (Forward'ın valör tarihi `D2`: USDTRY; VİOP'un `K3`'ü: USDTRY). İkisinden birini satırına göre seçen
     formül (serbest listenin spot sütunu `EK_FWD!O68`) ve hiçbirinden gelmeyen (sabit, `TODAY()`, kontrat vadesi)
     başlangıcının paritesini alır, o da yoksa TRY para piyasasınındır. Örnek: VİOP'un `M32:M33`'ü USDTRY spotundan gelir
     (USDTRY), `S32:S33` kontrat vadelerinden (TRY).
  3. Sayfa tanımı hiç olmayan hücrenin (yeni girdiler, "Elle değer") **başlangıcı**, çalışma kitabının o tarihin gün
     sayısını saydığı tarihtir: `O35 = O34-O33` → End'in başlangıcı Start (`DAYS`, `YEARFRAC`, `NETWORKDAYS` de); spot
     valörü başlangıç sayılmaz (zaten varsayılan: Masa'nın `E60`'ı hem `C60`'tan hem OIS spotundan sayılır → `C60`),
     birden çok aday kalırsa spot.

  **Forward DV01** tablosunun Start'ı ve End'i (`Forward!O33:O34`, varsayılanları `=+I2` / `=+D2`) artık girdidir: Start'a
  `3m` → USDTRY spot + 3 ay, USDTRY takvimiyle (03.11.2026'da 04.02.2027; o gün bir ABD tatili olsa 05.02.2027); End'e `18m`
  → Start + 18 ay (05.08.2028 cumartesi → 07.08.2028); N (`O35`) gün sayısı olarak kalır; silince formüle döner.
  Aynı tablonun **Spot**'u (`O32 = +F2`: sayfanın USDTRY spotu - Bloomberg ortası ya da `F2`'ye yazılan) ve **Rate**'i
  (`O46 = +E33`: USDTRY tablosunun valör tarihindeki (`D2`) RET ortası forward kuru) da artık doğrudan girdidir ("Elle
  değer" gerekmez): yazılmadıkça formülün değeri (bir şey değişmez), yazılınca DV01'ler (`O48`, `O49`) onunla, yalnız
  sizin için; silince formüle döner.
  Örnek (03.11.2026, USDTRY spot 04.11): `1A` → 04.12.2026, `IMM` → 16.12.2026, `ay sonu` → 30.11.2026, `+5` → 12.11.2026
  (11.11 Veterans Day: USD tatili; TRY para piyasasında 11.11). PPK / Fed toplantı tarihleri kendi kuralındadır (takvim
  değişir; `3m` orada eskisi gibi reddedilir).
  `=` ile başlayan her şey formüldür, kısayol sayılmaz; kısayol olmayan yazı (tarih, sayı) eskisi gibi okunur; listeli
  tarih hücresinde (VİOP kontratları) listenin kendi sözü (`Spot`) kısayol değildir, `ay sonu`nun düştüğü gün listedeki
  kontratsa o kontrat saklanır. Yapıştırılan blokta her hücre ayrı okunur, aynı blokta yapıştırılan başlangıç sayılır.
  Kişisel hesap tablosu kendi okumasını sürdürür (kısayol almaz: hücrelerinin tutar / tarih türü yoktur).
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
  Tablo Excel'deki düzeninde gösterilmiyorsa - sütunlar **kendi sıranızda**, ya da bir launchpad / yan panel kutusu
  tablonun **bir kısmını** gösteriyor - blok **göründüğü yere** oturur, o yönde ekrandaki satır / sütunlara: IMPLIED
  RATES'ın yalnız MPC1, MPC3, MPC5'ini gösteren kutuda MPC1'in adımına yapıştırılan üç değer MPC1, MPC3, MPC5'e gider
  (MPC2'ye değil); sütun sıranız V, U, W ise V'den başlayan üç değer V, U, W'ye (W, X'e değil).
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
* Bir tablo, kullanıcı seçim yapana kadar bazı sütunları **varsayılan olarak gizler**: DİBS RV'nin kendi FX swap sütunları
  (`BF:BJ`, offshore ICAP eğrisinde; tablonun notu söyler) - masa FX swap tarafını DİBS ASW'nin FX swap ima eğrisinde okur
  (DİBS RV · Genel'in "FX swap ASW"si, DİBS Trading, kâğıt kartı). "Sütunlar" ya da "Tümünü göster" onları da getirir ve
  bu seçim saklanır (varsayılan geri gelmez). Hücreler ve değerleri aynıdır.
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

**Ondalık basamak (sağ tık).** Masanın isteği (25.11.2026): "İstediğim şeyleri seçip sağ tıklayıp decimal formatını
yapabilmeliyim". Herkes sayıları kendi istediği ondalıkla görür; yalnız sizin görünümünüz değişir.

* Sayıları seçin (tek hücre, bir blok ya da `Ctrl+A` ile bütün tablo) ve sağ tıklayın: **Ondalık 0 1 2 3 4 5 6**
  satırındaki sayıya basınca seçimdeki her sayı o kadar ondalıkla görünür (seçimin hepsi aynı ondalıktaysa o sayı
  işaretlidir). **Ondalık artır** / **Ondalık azalt** (Excel'deki düğmeler gibi) her hücreyi kendi gösterdiğinden bir
  basamak öteye götürür. **Ondalığı varsayılana döndür** dosyadaki biçime geri getirir.
* Yalnız ondalık değişir: yüzde yüzde kalır (`35,55%` → `35,550%`); binlik ayırıcı, milyon gösterimi (`6.265M` →
  `6.265,43M`), eksi / parantez, önek ve sonek (`bp`) yerinde kalır; muhasebe biçimindeki sıfırın `-`'si değişmez.
  Tarih, saat ve metin hücrelerine dokunulmaz (seçimde olsalar da atlanır). Seçimdeki boş ya da hata gösteren formül /
  girdi hücreleri de ayarı alır: sayı geldiğinde seçtiğiniz ondalıkla görünür.
* Seçim hesabınızla sunucuda saklanır: sayfayı yeniden açınca, başka bilgisayardan girince, ertesi gün aynı; aynı
  tarayıcıdaki başka sekme ve pencereler hemen izler. Başkalarının görünümü değişmez. Ayarlanan hücrenin üzerine gelince
  "Ondalık: 3 – sizin görünümünüz" yazar.
* Yalnız görünüş: değerler, hesaplar, yazdığınız girdiler, alarmlar ve **Tam hassasiyetle kopyala** (`Ctrl+Shift+C`)
  aynıdır. **Kopyala** (`Ctrl+C`) ekranda göreneni alır; sağ tık → **İşlem gir** fiyatı eskisi gibi ekranda gördüğünüz
  haliyle alır. "Kotasyon kopyala" ve "Kota mesajı" kendi biçimleriyle kalır.
* Ayar **hücrenin yerine** bağlıdır: PPK / FOMC takvimi değişince, VİOP kontratları dönünce ya da kâğıt listesi değişince
  satırlardaki değerler yer değiştirir, ondalık ayarı aynı hücrede kalır (ondalık bir sütunun görünüşüdür: oran sütunu,
  fiyat sütunu - listede ne olursa).
* **Geçici kopyada** ayarlanan ondalık yalnız o kopyanındır (tablo değişmez); kopya, kendisinde ayar olmayan hücrelerde
  tablodaki ayarınızı gösterir. Kopyada sağ tık → **Ondalığı tablonunkine döndür**; kopyayı kapatınca kopyanın ayarları da
  gider.
* Kapsam: çalışma kitabı sayfalarının tabloları - sayfada, launchpad'de, yan panelde, ayrı pencerede ve geçici
  kopyalarda (DİBS RV · Genel'deki hesap tablosu yansımaları da aynı ayarla görünür). Dashboard'un bir tabloya eklediği
  sütunlar (PPK basamak, Broker bid …) ve dashboard'un kendi sayfalarının tabloları (Günlük İşlemler, Trades …) dışarıda.

**RET faizleri.** Üstteki "RET faizleri" düğmesi (Forward sayfasının RET sekmesindeki "RET faizlerini düzenle /
kopyala" da aynı pencereyi açar):

* **Yükle** — Excel'deki RET tablosunu (yalnızca bid–ask sütunları ya da vade etiketiyle birlikte) kopyalayıp
  pencereye `Ctrl+V` ile yapıştırın.
* **Ne kadar, nerede değişti** — yapıştırınca (ya da kutulara yazınca) her vadenin yanında **Δ bid** ve **Δ ask**
  sütunu kayıtlı eğriye (pencere açıldığındaki ya da son kaydedilen hali) göre farkı baz puan olarak gösterir: yukarı
  yeşil, aşağı kırmızı, değişen satır renkli, değişmeyen `0`. Tablonun üstündeki satır özetler:
  `Değişen 3 vade: 1M −45 / −45 · 3M +10 / +10 · 1Y +80 / +90 · 12 vade aynı`; hiçbir şeyi değiştirmeyen bir
  yapıştırma "Kayıtlı eğriyle aynı: değişen vade yok" der (bildirimde de). Kısmi yapıştırmada yapıştırılmayan vadeler
  `0` kalır; boş kutu fark sayılmaz (kaydedince o vade değişmez).
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
  geçmişe yazılır; geçmişteki bir kayıt tek tıkla geri getirilebilir. Geçmiş her yüklemenin **önceki eğriye göre neyi
  değiştirdiğini** de vade vade saklar ve listede kaydın altında yazar (`1M −45 / −45 · 3M +10 / +10`, "değişen vade
  yok"); Adil değer'den yayınlanan kayıt nereden geldiğini de söyler ("Adil değer · Kopyala ve yayınla · S2 · Hawkish
  senaryosundan"). Pencereden "Kaydet", sayfadaki RET tablosuna yazma / yapıştırma ve "Kopyala ve yayınla" aynı
  biçimde yazılır; eski kayıtlar olduğu gibi kalır (yeni sütun kendiliğinden eklenir).

Aynı şey Forward sayfasındaki TRY RET tablosuna doğrudan yazarak / yapıştırarak da yapılır. Yukarıdakiler pencerenin
**Elle giriş** sekmesidir; ikinci sekme kural tabanlı RET'tir (aşağıda). Pencere son kullanılan sekmede açılır.

**RET faizleri · Adil değer (kural tabanlı RET).** Pencerenin "Adil değer (kural tabanlı)" sekmesi
(`tto/retfair.py`, `tto/static/js/retfair.js`): masanın RET'i yayınladığı, kurala bağlı bir eğri - yayınlanan RET'in
yanında hesaplanır. Elle giriş aynen çalışır: masa bir gün kendi eğrisini yapıştırırsa yapıştırılan, yayınlanan RET
olur; adil değer yanında hesaplanmaya devam eder.

* **Her vade bir satır** (ON … 2Y). Ayarlar vadenin **etiketiyle** saklanır, RET tablosunun satırıyla değil (RET'in
  satırları da Forward!V sütunundaki etiketlerinden bulunur):
  * **Taban:** OIS mid, VİOP mid, offshore mid ya da bunların **karması** (ağırlıklar tabanla birlikte seçilir: ⚖;
    toplamları 100 olmak zorunda değil, 0 o tabanı dışarıda bırakır; varsayılanı Ekstra ayarlar'dan).
  * **Tabana spread (bp):** satırına yazılır (Enter), ya da çok vadeye birden: seçili vadelere (seçim yoksa hepsine)
    **Spread yaz** / **Kaydır**. **Yayınlanandan al** spread'i Şimdiki = Yayınlanan olacak şekilde ayarlar
    (kuralın tarafı: yayınlanan mid, bid ya da ask − taban − akış, tam bp) - ilk gün tek tıkla başlamak için. Spread
    masanın olduğundan her zaman piyasa tabanıyla alınır (senaryo görünümünde de).
  * **Akış ayarı (bp):** kabul edilen bir akış önerisi. Spread'den ayrı görünür (`OIS mid − 60 + 5 (akış)`), spread'e
    ve genişliğe dokunmaz, × ile kaldırılana kadar kalır (her vade tek tık).
  * **Genişlik:** vadenin sabit bid–ask genişliği (bp, 5'in katı); yalnızca Ekstra ayarlar'da değişir. İlk açılışta
    yayınlanan RET'in genişliklerinden alınır; 5'in katı olmayan yuvarlanır ve hem geçmişte hem Ekstra ayarlar'da
    söylenir (dosyadaki genişliklerin hepsi 5'in katı: ON – 1M 20, 2M – 3M 50, 4M – 5M 60, 6M 70, 9M – 2Y 110 bp).
  * **Tabana göre** (**Bid** / **Mid** / **Ask**): taban + spread + akış hangi kotayı belirler. Satırındaki üç düğmeyle
    tek tıkla, ya da çok vadeye birden (üstteki çubukta; seçili vadeler, seçim yoksa hepsi) - spread ve taban gibi masanın,
    vade etiketiyle saklanır, değişiklik geçmişine yazılır (`1M: tabana göre Bid (Bid = taban + spread + akış)`).
    **Varsayılan Mid**: güncellemeden sonra yayınlanan sayılar ve Şimdiki değişmez. Seçim değişince spread aynı kalır
    (Mid'den Bid'e geçen 20 bp genişlikli vade 10 bp yukarı çıkar: aynı spread artık bid'i belirler).
* **RET**, kuralın tarafına göre (bid her zaman 5 bp'lik ızgarada, yarım adım yukarı):
  * **Mid:** mid = taban + spread + akış; bid = mid − genişlik / 2 ızgaraya, ask = bid + genişlik (eskisi gibi);
  * **Bid:** bid = taban + spread + akış ızgaraya, ask = bid + genişlik (`Bid = OIS mid − 60 + 5 (akış)`);
  * **Ask:** ask = taban + spread + akış ızgaraya, bid = ask − genişlik (`Ask = OIS mid − 60`).
  Örnek: OIS mid 35,87, spread −60: Bid'de 35,25 / 35,45 (20 bp), Ask'ta 34,75 / 35,25 (50 bp), Mid'de 35,15 / 35,35.
  Formül sütunu tarafı yazar (Mid'de eskisi gibi yazmaz).
* **Gün sayımı RET'in kendisi:** USDTRY spot valöründen (Forward!I2) RET tablosunun gün sayısı kadar (Forward!U33:U47),
  basit ACT/360 - Forward sayfası RET'ten böyle fiyatlar (D33: spot·(1 + RET·g/360)/(1 + USD·g/360)). ON spot'tan önceki
  gün(ler)dir, diğer vadeler spot'tan başlar. Her taban aynı iki tarih arasındaki faizdir:
  * **OIS mid / offshore mid:** Borsa Swap spread'lerinin makinesi (`tto/borsaspread.py`): TLREF OIS ve offshore TRY mid
    eğrilerinin iki tarih arası zero faizi, basit ACT/360; spot öncesi günler eğrinin O/N'uyla (TLREF 365 → 360,
    offshore O/N mid). Düğümlerde Masa ORANLAR'ın "OIS zero" ve "ICAP" sütunlarıyla aynıdır.
  * **VİOP mid:** VİOP sayfasının kontrat başına ima TRY faizi - ((fiyat / spot)(1 + USD·g/360) − 1)·360/g, bid'de ve
    ask'ta (sayfanın 13. ve 25. satırları, g = vade − USDTRY spot; VİOP quant sayfasının okuduğu gibi,
    `quantviop.read_engine`) - ikisinin ortası, vadenin bitiş tarihine, vadeleri onun iki yanında olan iki kontrat
    arasında tarihle doğrusal. İlk kontratın vadesinden kısa (çoğunlukla ON – 3W) ya da sonuncununkinden uzun vadede
    VİOP tabanı yoktur (dışarı uzatılmaz; satır nedenini söyler).
* **Şimdiki ve Yayınlanan.** Şimdiki sürekli hesaplanır (pencere açıkken 5 sn'de, üst şeritteki etiket için 10–15
  sn'de bir), ama bir vadenin gösterilen değeri, kuralın tarafının ham değeri (Mid ve Bid'de bid - Mid'de eskisi gibi
  mid − genişlik / 2 -, Ask'ta ask) bir 5 bp adımını
  **2 bp'den fazla** geçmedikçe değişmez (histerezis: gösterilen değerden 2,5 + 2 bp uzaklaşınca). Taban 3 bp oynayıp
  adımı geçerse değer değişir, 1 bp oynarsa değişmez, adımın iki yanında gidip gelmesi değeri oynatmaz. Bir kişinin
  değişikliği (spread, taban, tabana göre, akış, genişlik) hemen yansır. Yayınlanandan farklı vadeler renklidir (yukarı yeşil,
  aşağı kırmızı) ve fark bp olarak yazılır; üstte **"RET güncellemesi var: 1M, 2M"**. Aynı vadeler üst şeritteki
  "RET faizleri" düğmesinde turuncu bir etikette de görünür (`↻ 1M, 2M`; tıklayınca bu sekme açılır).
* **Kopyala ve yayınla.** Şimdiki eğriyi (Şimdiki'si olmayan vade yayınlanan değerinde kalır) pencerenin **tablo** ya
  da **mesaj** biçiminde panoya koyar ve masanın RET'i olarak yazar: RET'i okuyan her tablo (Masa ORANLAR, forward
  tabloları, Günlük İşlemler'in RET fiyatlaması …) izler, RET geçmişine kim / ne zaman / ne yazılır, "bugün
  yüklenmedi" sarı noktası kalkar. Panoya giden ve yazılan aynı sayılardır. Bildirim yayın anında yayınlanan RET'e
  göre hangi vadelerin ne kadar kaydığını söyler (`RET yayınlandı ve kopyalandı: 1M +10 / +10 · 2M +25 / +25 (15
  vade)`, "değişen vade yok"); aynısı değişiklik geçmişinde ve RET geçmişinde vade vade durur.
* **Neredeyim.** Her vadede kuralın belirlediği yayınlanan tarafın (Bid ve Mid vadesinde bid - eskisi gibi -, Ask
  vadesinde ask) tabanlara uzaklığı (`1M bid 34,45: OIS mid'e −142 bp · VİOP mid'e +70 bp · offshore mid'e +144 bp`) ve
  bugünkü spread ve akışla, vadenin kuralıyla her tabanın (ve karmanın) vereceği RET: taban değişikliğinin sonucu
  yapılmadan görülür.
* **Senaryo** (sekmenin üstündeki liste; **kişisel**: her kullanıcının kendi seçimi, hatırlanır). **Piyasa
  (bootstrap)** varsayılandır - masanın Şimdiki'si, bugünkü sayılar. Ya da OIS · PPK'daki üç senaryodan biri, adı
  SENARYOLAR tablosundan (`OIS_MAIN!P3:P5`; `S2 · Hawkish`, ad değişince listede de değişir, seçim koduyla S1 / S2 / S3
  saklanır). Senaryo **o kullanıcının kendi hesabında** değerlendirilir: kendi adımları (*PPK ima*, `OIS_MAIN!U10:W89`),
  kendi adları; yüklenen kayıtlı bir "Senaryo" seti de izlenir; spread, taban seçimi, tabana göre, genişlik ve akış
  masanınki kalır. Sekme hangi senaryoda olduğunu yazar (`Senaryo: S2 · Hawkish`, altında ne değiştiğini anlatan satır).
  * **OIS tabanı** senaryonun eğrisinin vadenin iki tarihi arası faizidir (RET'in kendi tarihleri, basit ACT/360): Masa'nın
    "Tarih arası faiz" bloğunun (`MASA!I63:I65`, Motor'un PPK patikası) iskonto faktörleri - aynı iki tarihle bloğun
    verdiği faizin kendisi. ON vadesinde OIS spot'undan önceki gün piyasanınki gibi O/N ile (orada toplantı yok).
  * **VİOP ve offshore tabanı** OIS'e bazını korur: piyasa tabanı + (senaryo − **referans**) vadede. Referans, hiç adımı
    olmayan senaryodur (sayfanın kuralı: senaryo tabanı *ima yol*, kaydırma 0 - TLREF ilk toplantıya kadar, sonra
    piyasanın ima patikası). Adımsız senaryo bootstrap'lanmış piyasa eğrisini birebir veremiyor (ilk dönemi TLREF,
    patikası toplantı günlerinde bileşiyor: vadeye göre birkaç bp fark), bu yüzden referans ima yol eğrisidir: adımsız
    bir senaryoda VİOP ve offshore tabanı piyasanınkiyle aynıdır, OIS tabanı ima yolunkidir (bootstrap değil). Karma
    tabanda her parça kendi senaryo değeriyle girer. VİOP kontratları dönünce senaryonun OIS kısmı değişmez (yardımcı
    tablo VİOP'tan hiçbir şey okumaz), yalnız VİOP'un piyasa tabanı.
  * Senaryo görünümünde **histerezis yoktur**: kuralın ham değeri her okumada 5 bp ızgarasına yuvarlanır (aynı girdiler
    aynı sayıyı verir; PPK takvimi değişip geri gelince sayılar da geri gelir). Masanın piyasa Şimdiki'si ve histerezisi
    olduğu gibi kalır; üst şeritteki "RET güncellemesi var" etiketi piyasanındır.
  * **Senaryolara göre adil değer** tablosu her vadede yayınlananı, Piyasa'yı (masanın Şimdiki'si) ve üç senaryonun adil
    bid / ask'ını yan yana gösterir; senaryonun bid'inin piyasadan farkı yanında (bp). Seçili senaryo vurgulanır.
  * **Kopyala ve yayınla** kullanıcının gördüğünü yazar; değişiklik geçmişi ve RET geçmişi hangi senaryodan olduğunu
    söyler (`Kopyala ve yayınla (S2 · Hawkish senaryosundan): …`). Akış önerileri ve maliyet karşılaştırması masanın
    piyasa sayılarıyla kalır.
  * PPK takvimi değişince adımlar toplantılarıyla taşınır, senaryo adil değeri yeni haliyle hesaplanır; takvim geri
    gelince aynı sayılar. Yardımcı tablo `EK_RET` (vadelerin tarihleri, S1–S3 ve referansın iskonto faktörleri ve faizi,
    referansın adımsız patikası) Forward sayfasının "Yardımcı tablolar"ındadır. Yeni Bloomberg isteği yoktur.
* **Akış önerileri** (yalnızca öneri: hiçbir şey kendiliğinden uygulanmaz). Kaynak yalnızca **Günlük İşlemler**'deki
  TRY'ye karşı forward'lardır (Broker Chat ve BIST swap kotaları değil; OIS ve tahvil TRY satmaz / almaz). Vadeli
  **USD alışı = TRY sattık** (RET bid'inde işlenir), vadeli **USD satışı = TRY aldık** (RET ask'ında); tutar USD
  karşılığı. Bir işlem vadesinin iki yanındaki RET vadesine gün oranında bölünür (sayfanın forward kovaları gibi, TN
  hariç). Her vadede bugünün ve son N iş gününün net akışı, **normal** (önceki N iş gününde günlük net akışın
  ortalama büyüklüğü) ve katı, **maliyet** (net tarafın tutarla ağırlıklı ortalama TRY faizi) ve maliyetin RET'e ve
  tabanlara uzaklığı görünür.
  * Bugünkü net akış normalinin üstündeyse fazlasının her (5 / hassasiyet) × 100 mn USD'si için 5 bp önerilir:
    TRY sattıkta yukarı ("ask +5"), TRY aldıkta aşağı ("bid −5"); genişlik sabit olduğundan vadenin iki tarafı birlikte
    kayar. Yanındaki vade de (yukarıda bir sonraki, aşağıda bir önceki) yarısıyla, 5 bp'ye yukarı yuvarlanarak kayar -
    eğri kırılmasın. Örnek: `1M'de bugün net 240 mn USD TRY sattık (normalin 2 katı), ortalama 34,10 ile; RET bid 34,25
    maliyetin 15 bp üstünde → öneri 1M / 2M ask +5 bp`.
  * **Maliyete saygı:** bir öneri hiçbir vadenin ask'ını o vadedeki akışın maliyeti + asgari marjın altına indirmez;
    inebileceği kadarla sınırlanır ya da "öneri yok" der.
  * **Kabul et** öneriyi vadelerine akış ayarı olarak ekler; aynı gün aynı öneri yeniden önerilmez (akış büyürse yalnız
    eklenen kısmı).
* **Ekstra ayarlar** (yalnızca yöneticiler değiştirir; diğerleri görür): genişlikler, histerezis (2 bp), akış
  hassasiyeti (100 mn USD başına 5 bp), geriye bakış (10 iş günü), asgari marj (5 bp), karmanın varsayılan ağırlıkları
  (OIS 50 · VİOP 25 · offshore 25).
* Spread, taban, tabana göre, akış ayarları ve yayınlanan RET masanındır (ortak, herkes görür); her değişiklik
  "Değişiklik geçmişi"ne kim, ne zaman, ne ile yazılır. Yalnız senaryo seçimi kişiseldir. Yeni Bloomberg isteği yoktur:
  piyasa görünümü çalışma kitabının masa hesabından (kimsenin kişisel girdisi olmadan), senaryo görünümü kullanıcının
  kendi hesabından okunur. Eski veritabanı RET'i ve geçmişiyle açılır; yeni tablo kendiliğinden eklenir.

**Pozisyon ve maliyet** (Günlük İşlemler sayfasında; RET penceresinden "Pozisyon ve maliyet →"). Akış önerileriyle
aynı toplama (`tto/retflow.py`, tek uygulama): RET vadelerine göre bugünün TRY satışı / alışı ve neti (mn USD),
**maliyeti** (net tarafın ağırlıklı ortalama faizi), bu pozisyonun **yayınlanan RET mid'ine** ve **OIS mid'ine** göre
**K/Z**'si (TL; her işlem: DV01'i (TL, payer +) × (eğrinin işlemin gün sayısındaki değeri − işlemin faizi); + masanın
lehine) ve aynıları son N iş günü + bugün için. Kaynak yine yalnızca Günlük İşlemler.

**Senaryolar.** "Senaryolar" düğmesi: o andaki kişisel girdilerinizin tamamını bir isimle kaydeder, yükler, siler.
Senaryolar kullanıcıya özeldir. **Yükle** (ve Ctrl+K'nin `senaryo` komutu) son yazılan değerden sonra gelir: açık bir
hücre düzenlemesi önce kaydedilir, yolda olan her yazma (hücre, yapıştırma, sıfırlama, manuel spot) cevaplanınca yükleme
gönderilir; sunucu da yüklemeyi yazma kuyruğunda kendinden önce gelenlerin arkasına koyar - senaryonun değeri kalır,
hemen önce yazılan değer üstüne binmez. Formüllü girdiler formülleriyle saklanır; yüklenince formül o anki değerlerle yeniden
hesaplanır. Geçici kopyaların değerleri senaryoya girmez
([Geçici kopyalar](#geçici-kopyalar)): senaryo tablonun kendisini, yani kişisel girdilerinizi saklar.

**Günlük İşlemler.** Soldaki formdan:

* **FX Forward** — parite (*USDTRY / EURTRY / Diğer*), yön, tutar (`10m`, `2,5 mio`, `2mr`, `10.000.000`), valör tarihi
  (tarih ya da kısayol: `3M`, `1A`, `2H`, `TN`, `ay sonu`, `IMM`, `+5` - paritenin spot valöründen, iki para biriminin
  tatilleriyle; kutunun altında karşılığı yazar: "1A → 04.12.2026"; [yukarıda](#kullanım), *Tarih kısayolları*);
  fiyatlama: *RET bid / RET mid / RET ask / TRY faizi / Forward kur / Swap puanı*. Tarihi yazar yazmaz forward kuru
  ve **TL tutarı** hesaplanır (Forward sayfasının kendi hücreleriyle: valör `Forward!D2`'ye yazılmış gibi).
  * **USDTRY**: USDTRY tablosunun RET satırı (`Forward!D33:F33`); TRY faizi verilirse toplu fiyatlama satırının
    formülü, forward kur verilirse ima edilen TRY faizi.
  * **EURTRY**: sayfanın EURTRY tablosu (`Forward!D45:F45`; spot `G2`, gün sayısı EURTRY valöründen, EUR OIS eğrisi).
    TRY faizi verilirse sayfadaki çapraz forward bloğunun formülü (`spot·(1+r·g/360)/(1+r_EUR·g/360)`; `r_EUR` eğrinin
    valördeki bid / ask ortası, `Forward!AD27` - toplu fiyatlama tablosu Bloomberg'in MID'ini kullanır: oradan işleme
    alınan EURTRY satırı bu yüzden tablonun forward kuruyla girilir).
  * **Swap puanı** (her paritede): `forward = spot + puan / 10.000` – sayfanın "Swap Point" satırlarındaki birim.
    Puan Türkçe biçimde `17.400`, İngilizce biçimde `17,400` yazılabilir.
  * **Diğer** (minor para): kutuya döviz (`GBP`) ya da parite (`CHFTRY`, `EURUSD`) yazılır. Çalışma kitabında bu
    paraların eğrisi olmadığından fiyat elle girilir: forward kur, ya da spot + swap puanı (TRY'ye karşı paritelerde
    Bloomberg spotu varsa spot kutusu boş bırakılabilir). İma TRY faizi hesaplanmaz; TRY faizi DV01'i valöre kadarki
    TRY iskonto faktörüyle verilir. TRY'ye karşı olmayan paritenin (EURUSD) TRY riski yoktur.
  * **Tutar karşı parada**: tutar paritenin iki dövizinde de yazılabilir; "Tutar (USD)" ile "Tutar (TRY)" yan yana
    durur (EURTRY'de EUR / TRY, EURUSD'de EUR / USD). Hangisi yazılırsa o sabit kalır ve **✎ yazılan** diye işaretlenir;
    öbürü işlemin kendi forward kuruyla (fiyatlama ne ise: RET, TRY faizi, forward kur, swap puanı) hesaplanır, fiyat ya
    da valör değişince yeniden hesaplanır. İşlem her yerde yine ilk dövizin işlemidir: pozisyon, DV01, maliyet ve K/Z,
    Excel sayfası, gün sonu dosyası ve chat eşleştirmesi döviz tutarını okur. Hesaplanan döviz tutarı kuruşuna (yende
    bütün yen) yuvarlanarak saklanır ve sayfadaki bütün tutarlar gibi tam birimle gösterilir (kuruşlusu ipucunda);
    yazılan karşı tutar olduğu gibi kalır (TL tutarı = yazılan tutar). Kayıtta hangi tarafın yazıldığı ve tutarı da
    durur: listede yazılan tutar ✎ ile işaretlidir, gün sonu dosyasının forward tablosunun sonunda **Girilen tutar** ve
    **Girilen döviz** sütunları vardır (önceki kayıtlar dövizle yazılmış sayılır).
* **OIS** — *Outright / Spread / Fly / FRA / MPC*; büyüklük DV01 ($/bp) ya da nominal (TL). Bacaklar OIS_MAIN'in
  kuralıyla boyutlanır (`ROUND(w·DV01·USDTRY/(Annuity·0,0001)/lot)·lot`, fly kanatları ½). Piyasa mid seviyesi ve
  işlemin **mid'e göre** değeri otomatik hesaplanır: **Mid'e göre (bp)**, **($)** ve **(TL)** - **+ mid'den iyi
  (lehine, yeşil), − mid'den kötü (aleyhine, kırmızı)**. Mid %35,12 iken %34,45'ten PAY edilen FRA **+67,00 bp**'dir
  (piyasadan ucuza alınmış). Fiyat kutusu, OIS listesinin "Mid'e göre (bp)" / "Mid'e göre ($)" sütunları ve gün sonu
  arşivinin OIS tablosu aynı işaretle yazar. Kayıtta saklanan maliyet (`cost_bp`, `cost_usd`: + mid'den kötü, ödenen)
  eskisi gibi durur, ekranda ve dosyada işareti çevrilerek gösterilir: önceki günlerin işlemleri de doğru okunur.
  * **MPC** (toplantı tarihli OIS): başlangıç *Spot* ya da bir toplantının etkin günü (karardan sonraki gün), bitiş
    daha sonraki bir toplantının etkin günü – OIS sayfasındaki "MPC OIS" tablosunun tarihleri. Piyasa seviyesi o
    tablonun "Piyasa (bootstrap)" sütunu (iki toplantı arası tek dönemde aynı sayı; daha uzun aralıkta sayfadaki
    "İki tarih arası simple rate" hesaplayıcısının bootstrap satırı, iki tarih yazılmış gibi). Nominal sayfanın
    "Nominal" sütunundaki kuralla: `DV01·USDTRY / (gün/365 · DF · 0,0001)`. İşlem listelerde iki tarihiyle
    anılır (`MPC 11.12.26–22.01.27`): toplantı geçince numarası değişir, tarihi değişmez.
* **Tahvil** — enstrüman (ISIN), yön, tutar, fiyat. Kâğıt DİBS RV tablosundaysa adı, vadesi, tablodaki temiz fiyatı,
  süresi ve DV01'i gösterilir.

**Şablonlar.** Sık girilen kurulumlar adıyla saklanır: formun üstündeki şeritte **+ Şablon olarak kaydet**, açık
sekmenin formunu alır ve hangi alanların şablonda kalacağını sorar (karşı taraf, parite, yön, tutar, valör ya da vade,
fiyatlama, strateji, vadeler, büyüklük … herhangi bir alt kümesi; not, OIS seviyesi ve tahvil fiyatı varsayılan olarak
dışarıda). Şeritteki şablona **bir tık formu doldurur** (gerekirse sekmesini açar); işlem kaydedilmez, "İşlemi
kaydet" yine sizdedir. Tutar yazıldığı dövizle saklanır (TRY yazılmışsa döviz tutarı her seferinde günün forward'ından); valöre vade
(`3M`) yazılmışsa günün spotundan hesaplanır; MPC şablonu toplantıları sırasıyla tutar (MPC1→MPC2, toplantı geçince
bir sonrakine kayar). Şablondaki tutarlar ve swap puanı iki sayı biçiminde de aynı okunacak gibi saklanır (`17.400` puan `17400` olarak):
Türkçe ve İngilizce biçimle çalışan kullanıcılar bir masa şablonunu aynı okur. Şablonlar kişiseldir: başkası görmez. Yönetici kaydederken **Masa (herkes görür)** seçerek masa
şablonu yayımlar: herkes kullanır, yalnızca yöneticiler değiştirir ya da siler (şeritte kesik çerçeveyle). **Yönet…**:
doldurma, yeniden adlandırma, **formdakiyle güncelleme** (önce formu şablonla doldurup düzenleyin) ve silme. Şablonlar
veritabanında ayrı bir tabloda (`trade_templates`) durur; önceki sürümün veritabanı açılınca bu tablo eklenir,
başka hiçbir şey değişmez.

**Excel'den yapıştır.** Excel'den kopyalanan işlem satırları (sekmeyle ayrılmış; hücresinde sekme ya da satır sonu
olanlar tırnaklı, Excel'in kopyaladığı gibi) "Excel'den yapıştır" penceresine yapıştırılır; ürün seçilir: FX Forward,
OIS ya da Tahvil.

* **Sütunlar**: başlık satırı tanınır - Günlük İşlemler sayfasının kendi başlıkları (Yön · Tutar · Faiz · Valör;
  Nominal · DV01 USD · Yön · Faiz · Valör · CPT; Enstrüman · Tutar · Fiyat), bu sayfanın sütun adları ve İngilizceleri
  (Side, Amount, Value Date, Fwd Rate, Counterparty …). Başlık yoksa sütunlar sayfanın listelerinin sırasıyla okunur.
  Her sütunun ne olduğu önizlemenin üstündeki seçimle değiştirilir (ya da "— yok say"); **Otomatik eşle** başa döner.
* **Okunuş**: sayılar ve tarihler formdaki gibi kullanıcının biçiminde okunur (Türkçe `1.000.000,50`, İngilizce
  `1,000,000.50`; tarih `gg.aa.yyyy` ya da vade `3M`). Forward'da tutar başlığı bir döviz söylüyorsa (`USD tutarı`,
  `Tutar (TL)`, `TRY`) satırın paritesine göre döviz ya da karşı tutardır (TRY yazılan USDTRY satırının USD'si forward
  kurundan); paritede olmayan döviz hatadır. Fiyat: TRY faizi, forward kur ya da swap puanı sütunlarından biri; birden
  çoksa **Fiyatlama** sütunu (RET bid / mid / ask, TRY faizi, Forward kur, Swap puanı) hangisi olduğunu söyler. OIS
  satırı vadeyle (`1Y`) ya da Başlangıç / Bitiş tarihleriyle (MPC) girilir, yön PAY / RECEIVE ya da sayfadaki gibi
  B / S; nominal yazılmışsa DV01 ondan hesaplanır. Tahvilde tutar + alış / − satış ya da Yön sütunu.
* **Önizleme**: her satır formun kendi denetimleri ve fiyatlamasıyla kontrol edilir; geçerli satırda kaydedilecek
  işlem (parite, yön, tutar, valör, forward, TRY faizi, DV01), hatalı satırda nedeni yazar.
* **Kaydet** ("N satırı kaydet"): geçerli satırların **hepsi tek işlemde (transaction)** kaydedilir - hepsi ya da hiçbiri.
  Önizlemede geçerli görünen bir satır kayıt anında geçersizse (piyasa değişti) hiçbir satır kaydedilmez, yeni önizleme
  gösterilir. **Hatalı satır asla kaydedilmez**: başlığıyla birlikte kutuda kalır, düzeltilip yeniden kaydedilir. Bir
  yapıştırmada en fazla 200 satır.
* **TOPLU FORWARD'dan** (Forward → Toplu fiyatlama, **İşleme al**): pencere tablonun Tutar'ı yazılı satırlarıyla dolu
  açılır, ürün FX Forward'da sabit; önizleme ve kayıt aynıdır. Kaydedilen satırların Tutar'ı tabloda silinir (Forward
  sayfası, *Tablodan işlem*).

**Fiyattan işlem (sağ tık → İşlem gir).** Sayfalardaki bir fiyat hücresine sağ tıklayınca menünün başında **İşlem gir**
çıkar; Günlük İşlemler'i o fiyatla dolu açar (sayfada, yan panelde, launchpad'de; ayrı pencerede ana pencerenin formunu).
Hiçbir şey kaydedilmez: ürün, parite / enstrüman, tarihler, fiyat ve yön doldurulur, **tutar ve karşı taraf yazılmaz**
(tutar kutusu boş gelir, forward'da yazılan taraf paritenin ilk dövizidir; yazılmış karşı taraf kalır), her alan
değiştirilebilir, "İşlemi kaydet"e basılınca kaydedilir. Not alanına fiyatın yeri yazılır
(`Fiyat: 3M · Puan ask (Masa · FORWARD KOTASYON)`).

* **Hangi hücreler:**
  * Masa ve Forward'daki forward kotasyon matrisleri (USDTRY / EURTRY): puan → *Swap puanı*, Fwd → *Forward kur*,
    TRY % → *TRY faizi*; Forward'dakilerde RET bid / ask % → *RET bid / ask*.
  * Forward'ın USDTRY / EURTRY tabloları: her eğri satırında TRY %, outright ve puan (bid / mid / ask); RET satırı RET
    eğrisinin kendi fiyatlamasıyla (*RET bid / mid / ask*).
  * Forward'ın TOPLU FORWARD FİYATLAMA tablosu: USDTRY / EURTRY fwd → *Forward kur*, puanları → *Swap puanı*, elle
    yazılan forward → *Forward kur*, İma TRY % → *TRY faizi*; her fiyat kendi sütununun paritesiyle, valör satırın kendi
    valörü, yön seçili gelmez (tablonun **İşleme al**'ı da var: *Excel'den yapıştır*).
  * RET: Forward'daki TRY RET tablosu (1W–2Y), Masa'daki ORANLAR ve RET BANDINA GÖRE PİYASA'nın RET bid / ask'ı.
  * Hesaplayıcılar: TARİH ARASI FORWARD'ın bitiş tarihine forward, puanı ve TRY %'si (bitiş üstteki satırda yazılan);
    KIRIK VADE & KARŞILIK'ın forward, puan ve basit % satırları (piyasa ve işlem karşılığı; valör tablonun kendi
    valörü).
  * OIS: OIS · PPK'daki OUTRIGHT'ın piyasa par'ı ve Masa'daki ORANLAR'ın OIS kotası → *Outright*, o vade; MPC OIS'in
    piyasa (bootstrap) seviyesi → *MPC*, satırın kendi iki günüyle.
  * Tahvil: DİBS RV (BBG alış / satış / orta, kullanılan temiz; alış / satış getirisi o tarafın fiyatıyla, getiri
    notta), DİBS Trading (T0 / T1 / T2 / ek bid / ask, son işlemler), Tüm Kâğıtlar (bid / ask / son işlem), DİBS ASW
    (temiz fiyat).
  * VİOP kontratlarının fiyatında **İşlem gir** soluk durur ve nedenini söyler (Günlük İşlemler'de VİOP yok). Fiyat
    olmayan hücrede (vade, gün, spread, başlık) çıkmaz.
* **Satırın kendisinden:** enstrüman ve tarihler tıklanan satırın kendi hücrelerinden okunur (satırın valörü, vadesi -
  spot'tan formun saydığı gibi tarihlenir -, toplantının iki günü, ISIN), satırın yerinden değil: PPK takvimi, VİOP
  devri ve kâğıt listeleri satırları kaydırsa da işlem satırın o anki enstrümanıdır. Fiyat ekranda görüldüğü gibidir.
* **Yön sütundan, kotayı veren masa olarak:** bid'de masa alır (USD / EUR al, kâğıt al; bir OIS kotasında PAY – Broker
  Chat'teki "bizim kotamız" kuralı), ask'ta satar. Mid bir fiyatta (eğrilerin orta değeri, OIS par'ı, hesaplayıcılar,
  kullanılan temiz fiyat) **yön seçili gelmez**: seçilmeden kaydedilmez. Ekrandaki bir piyasa fiyatına (DİBS ekranı,
  offshore eğri) vuran taraf olunduğunda yön tersidir: formda değiştirin.
* TRY % hücresi formun *TRY faizi* fiyatlamasıyla gelir: faiz tıklanan faizdir, forward'ı formun kuralıyla (USD orta
  faizi) hesaplanır ve tablonun o taraftaki outright'ından birkaç puan ayrışabilir; tablonun outright'ı istenirse
  outright ya da puan hücresine tıklayın.
* Bir tablo sayfa tanımındaki `"trade"` ipucuyla katılır (`tto/views/__init__.py`): hangi hücrelerin fiyat olduğu, neyin
  fiyatı ve hangi tarafı, satırın enstrümanının hangi sütunda olduğu; iki pariteli tabloda bir fiyatın kendi paritesi
  (`"pairs"`).

Formu dışarıdan dolduran her şey - kotadan ya da fiyattan "İşlem gir", şablon, listedeki **Düzenle** - aynı girişi kullanır: `blotter.js`'teki
`fillForm` (alanları orada yazılı); şablonun ve yapıştırılan satırın sunucudaki karşılığı `tto/entry.py`, fiyatınki
`tto/tradehint.py`.

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
Masanın OIS kovaları ON, 1W, 2W, 1M, 2M, 3M, 6M, 9M, 1Y, **18M**, 2Y, 3Y … 10Y'dir (karşı taraf × vade tablosu;
*OIS · vade özeti* 5Y'de biter); **15M, 21M, 27M** gibi aradaki vadeler yoktur - OIS_MAIN onları iki kota arasından okur,
orada işlem olmaz. Böyle bir vadedeki bacak - 12x15 FRA'nın 15M bacağı, 15M outright, 24x27 FRA'nın 27M bacağı - **iki
yanındaki kovaya aylara göre doğrusal bölünür**: nominali ve DV01'i, kendi oranıyla (15M: yarısı 1Y, yarısı 18M; 21M:
yarısı 18M, yarısı 2Y; 27M: ¾ 2Y, ¼ 3Y; 30M yarı yarıya; 33M: ¼ 2Y, ¾ 3Y …; sayfada iki satır, pozisyon maliyeti
tablosunda iki kova).
İşlemin kendisi, etiketi ve gün sonu arşivi kendi vadesini (15M) tutar. OIS · PPK'nın FRA listeleri (*EN İYİ 15 FRA*,
*TÜM FORWARD / FRA*) aynı kuralla her FRA'nın bacaklarının hangi kovaya kaçtan ne DV01 getireceğini yazar: iki sütun,
"Başlangıç bacağı → kova" ve "Bitiş bacağı → kova" - kova(lar), satırın YÖN'ündeki yönle, Nominal'iyle DV01 (+ pay,
− receive: Günlük İşlemler'in işareti; bölünen bacakta her kovanın payı) ve bacağın oranı ("1Y −5.922 $ + 18M −5.922 $ ·
%35,47"; ipucunda bacağın kendi vadesi ve payları).
FRA kotasyonu piyasa mid'inin (Bootstrap, Murex'in MTM'i) yanında **PPK basamak** mid'ini ve işlemin ona göre yerini de
yazar (aşağıda: *TRY faizleri iki yoldan*); kaydedilen maliyet Bootstrap'ladır.

**Düzenle.** Bugünün her işleminin satır sonunda (✕'in yanında; paketin - spread, fly, FRA - ilk satırında, paketin
tamamı için) **Düzenle** vardır: girildikten sonra yanlış yazılan seviye, büyüklük, tutar, karşı taraf, not, valör …
düzeltilir. Silme gibi herkes düzenleyebilir (başkasının girdiği işlemi de). Düzenle, işlemin sekmesindeki formu
işlemin değerleriyle doldurur: strateji, yön, vadeler / aylar / MPC günleri, seviye, büyüklük, karşı taraf, not; forward'da
parite, valör, fiyatlama ve fiyatı, tutar yazıldığı dövizde (TRY yazılmışsa TRY); tahvilde enstrüman, tutar, fiyat. OIS'te
büyüklük bacakların **nominalidir** (DV01 ile boyutlanmış spread / fly'da girilen DV01), paketin bacak oranları da (kısa
bacak, kanatlar, FRA'nın başlangıç bacağı) kendi kutularına yazılır. Formun başlığı **İşlemi düzenle**dir, üstünde hangi
işlemin düzenlendiği yazar; düğme **Değişikliği kaydet**, yanında **Vazgeç** (form düzenlemeden önceki haline döner, işlem
olduğu gibi kalır). Ürün (forward / OIS / tahvil), OIS'in **stratejisi** ve **bacak sayısı** değişmez (formda öbür
sekmeler ve stratejiler kapalıdır; spot başlangıçlı FRA tek bacaktır): sunucu "strateji değişiyorsa silip yeniden girin"
diye reddeder. **Düzenleme, değiştirilmeyeni oynatmaz:**

* **Yalnızca karşı taraf / not** değiştiyse yalnızca onlar değişir: hiçbir şey fiyatlanmaz, kayıttaki bütün sayılar
  (kur, faiz, mid'e göre değer, DV01 …) aynı kalır. Bu düzenleme **geçmiş günün işleminde de** yapılır: geçmiş bir
  günün (ya da aralığın) listesinde Düzenle **Karşı taraf ve not** penceresini açar.
* **Tutar, yön, seviye, büyüklük ya da bacak oranı** değiştiyse işlem **kendi fiyatlarıyla** yeniden hesaplanır: forward'ın
  kuru, TRY faizi, spot'u ve iskonto faktörleri aynı kalır, tutarlar ve DV01 bunlarla hesaplanır; OIS'te enstrüman aynıysa
  her bacağın kayıtlı **işlem anındaki mid'i** korunur ve **Mid'e göre** değer o mid'e göre hesaplanır, bacaklar işlemin
  kendi eğrisiyle (bacağın kayıtlı DV01 / nominal oranı: işlem anının annuity'si ve USDTRY'si) kurulur - nominal yazılan
  büyüklük tam aynı kalır, DV01 yazılanın nominali de işlemin kendi eğrisinden gelir, bugünkünden değil; tahvilde nominal
  başına DV01 aynı kalır.
* **Enstrüman** değiştiyse - OIS'te yön, vade, FRA ayları, MPC tarihleri; forward'da parite, valör, fiyatlama ya da
  yazılan fiyat (TRY faizi, forward kur, swap puanı; başka paritede spot); tahvilde ISIN - işlem yeni işlem gibi
  **bugünkü piyasayla** fiyatlanır.

Form kaydetmeden önce bunu söyler: düzenlemede fiyat kutusu kaydedilecek işlemi gösterir (sunucunun önizlemesi:
`POST /api/blotter/trade/<id>/preview`), üstündeki tek satır nasıl fiyatlanacağını yazar - bugünkü piyasayla fiyatlanacaksa
turuncu, neyin değiştiğiyle ("Valör değişti: bugünkü piyasayla yeniden fiyatlanır", "Yön değişti: …"); öbür durumlarda
"İşlem anının mid'i ve eğrisiyle …", "İşlemin kuru, TRY faizi ve spot'u aynı kalır …", "Yalnızca karşı taraf / not
değişir …" ya da "Değişiklik yok"; OIS'te mid kutusu o zaman **Mid (işlem anı)** adını alır. Fiyatı, tutarı ya da
enstrümanı değişen düzenleme yalnızca **bugünün** işleminde yapılır (sunucu da reddeder: "geçmiş günün işleminde yalnızca
karşı taraf ve not değişir"). Kaydedilen düzenlemede **aynı kayıt değişir**: kimlikleri (id), günü, kimin ve saat kaçta
girdiği aynı kalır; değiştiren ve saati kayda yazılır. Her bacak düzenlemeyi **kendisiyle saklar** (`edits`: saat, kim,
nasıl fiyatlandığı - `none` yalnızca karşı taraf / not, `trade` işlemin kendi fiyatlarıyla, `today` bugünkü piyasayla ve
neyin değiştiği -, değişen alanların önceki değerleri; son 20 düzenleme). Listede düzenlenmiş işlemin saatinin yanında
turuncu **✎** vardır; üzerine gelince kimin, saat kaçta (kaçıncı kez) düzenlediği, nasıl fiyatlandığı, kimin ne zaman
girdiği ve önceki değerleri (seviye, nominal, tutar, kur, karşı taraf …) görünür. Hiçbir şey değişmediyse kayıt yazılmaz
("Değişiklik yok"). Düzenlemeden sonra Excel sayfasının listeleri, maliyet tabloları, DV01 özeti, pozisyon ve maliyet
paneli ve blotter'ı okuyan her şey eklemede / silmede olduğu gibi kendini yeniler. Kimlikler değişmediği için
**Chat ↔ Günlük İşlemler** eşleşmeleri düzenlemeden sonra da durur: elle eşleştirilen kayıt (paketin hangi bacağıyla
eşleştirilmiş olursa olsun) eşleşmiş kalır, "İşlem gir"le girilen kayıt notu (form notu korur) ile, otomatik eşleşen
kayıt girildiği saatle ve seviyesiyle eşleşmeye devam eder - seviyesi chat'tekinden başka bir seviyeye düzeltilen
kayıt artık o chat satırının işlemi sayılmaz (satır "girilmedi"ye döner).

**Benzerini gir · Ters işlem** (masa, 23.11.2026: tekrar eden işlemler ve kapatmalar için). İşlem formunun açık olduğu her
listede - bugün ve bugünü içeren bir aralık - her işlemin satırında (bugünün ve geçmiş günlerin) iki düğme daha vardır.
İkisi de formu **yeni işlem** olarak doldurur (düzenleme değil; süren bir düzenleme bırakılır) ve hiçbir şey kaydetmez:
"İşlemi kaydet" yine sizdedir, eski işlem olduğu gibi kalır. Formun üstündeki satır neyden dolduğunu ("Benzeri: …" /
"Ters işlem: …", geçmiş günün işleminde günüyle) ve nasıl dolduğunu söyler; işlem kaydedilince kalkar. İşlemin fiyatı,
faizi ya da seviyesi gelmez: form **bugünkü piyasayla** fiyatlar - OIS'te piyasa mid'i ("kullan"), forward'da RET
fiyatlaması kendiliğinden, elle fiyatlamada (TRY faizi, forward kur, swap puanı) ve tahvilde fiyat yazılır.

* **Benzerini gir** – işlemin koşulları: ürün, yapı, yön, büyüklük (forward'da yazıldığı dövizde; OIS'te nominal, DV01'le
  boyutlanmış spread / fly'da yazılan DV01), karşı taraf, not; enstrüman girildiği gibi - vade bugünkü spot'tan, tarih
  tarihiyle. Başlangıcı geçmiş işlemde (geçmiş günün) **aynı vade bugünkü spot'tan**: forward'ın valörü kendi spot'undan
  tam ay ya da hafta ise o vade (`3M`, `2W`), değilse aynı gün sayısı; OIS'te aynı vadeler / FRA ayları; MPC'de
  başlangıcı geçtiyse Spot'tan aynı bitişe.
* **Ters işlem** – işlemi kapatan işlem: **ters yön, aynı büyüklük, aynı bitiş** (vade, valör, ISIN, toplantı);
  başlangıcı geçmişse başlangıç **bugünkü spot**'tur. Ürün ürün:
  * **FX forward**: ters yön, aynı valör, aynı fiyatlama; tutar ilk dövizde (karşı parada girilmiş olsa da döviz tutarı:
    pozisyon tam kapanır).
  * **TRY OIS outright** – bugünün işlemi aynı vadeyle; geçmiş günün işlemi bugünkü OIS spot'undan **işlemin kendi
    vadesine kırık vade** (vade, girildiği günün OIS spot'undan Motor'un takvimiyle: `WORKDAY(EDATE(spot, ay) − 1, 1,
    TRY)`). Kırık vade **Fiyatlama'nın hesabıyla** fiyatlanır: 3 aya kadar tek ödeme, daha uzunda çeyreklik kuponlar
    vadeden geriye sayılır, **kısa dönem başta** (Masa'nın kırık vade bloğu, BL193), ACT/365, Bootstrap eğrisi (Murex);
    nominal OIS_MAIN'in kuralıyla o vadenin annuity'sinden. Aynı nominal.
  * **Spread / fly**: paket bütün bacaklarıyla, yön ters (STEEPENER ↔ FLATTENER, REC GÖVDE ↔ PAY GÖVDE); geçmiş günün
    paketinde her bacak kendi vadesine kırık vade. Büyüklük nominalse aynı nominal, DV01'le girildiyse aynı DV01.
  * **FRA**: başlamamışsa kendi iki tarihi arasında (iki kırık vadeli spot swap, ileri annuity'den tek nominal - formun
    FRA'sı gibi), başlamışsa bugünkü spot'tan bitişine; aynı nominal.
  * **MPC**: aynı toplantı tarihleri; başlangıcı geçtiyse Spot'tan aynı bitişe.
  * **Tahvil**: aynı ISIN ve nominal, ters yön.
* **Çıkmayan düğme**: vadesi ya da valörü gelmiş işlemin "Ters işlem"i (kapatılacak bir şey kalmadı) ve dönemi bitmiş MPC
  işleminin ikisi de çıkmaz; nedeni düğmelerin hücresinin ipucunda yazar.
* **Kırık vade formda**: OIS formunun vade listesinde ve FRA aylarında tarihiyle durur (`04.11.2027 · kırık vade`) ve
  öyle kaydedilir (listede bacağın vadesi o tarih, düzenlenebilir). Excel sayfasında ve özet tablolarında vadesinin iki
  yanındaki ana vadeye gün oranında bölünür (spot'tan başlayan MPC işlemi gibi); maliyet tablosunda kendi satırındadır.

**Geçmiş günler ve tarih aralığı.** "İşlem günü" seçicisi geçmiş bir günü, yanındaki **Aralık** iki tarih arasındaki
bütün günleri gösterir (iki tarihi seçip "Göster"; hazır aralıklar: *Bu hafta*, *Bu ay*, *Son 30 gün*). Aralıkta her
satırın başında işlem günü yazar; maliyet ve DV01 özetleri aralıktaki işlemlerin toplamıdır. **Bugünü içeren bir
aralıkta** (*Bu hafta*, *Bu ay*, *Son 30 gün*) işlem formu açık kalır: girilen işlem bugüne yazılır ve listeye eklenir,
bugünün işlemleri silinebilir ve düzenlenebilir. Geçmişte biten bir aralık ya da geçmiş bir gün salt okunurdur - işlemlerin
yalnızca karşı tarafı ve notu düzenlenir ("Karşı taraf ve not" penceresi) - ("Bugün" düğmesi geri döndürür).
Listelerin altındaki **Excel sayfasının özet tabloları** (forward vade kovaları, OIS vade özeti, Bonds, CPT × vade; masa,
23.11.2026: "daha fazla tarihe bakarken bugündeki alttaki tablo gelmiyor") aralıkta da gelir: Excel sayfası yalnızca
bugünün işlemlerini tuttuğundan, aynı tablolar sayfanın kendi formülleriyle, listeleri **gösterilen işlemlerle**
doldurulmuş ayrı bir hesapta kurulur (sayfanın kendisi bugünün kalır). Üstlerinde neyi kapsadıkları yazar ("Aralık
… – …: N işlemin hepsi birlikte …"): aralığın bütün işlemleri tek tabloda, vade kovaları ve gün sayıları bugüne göre,
her işlem kendi tutarı, faizi ve DV01'iyle. Sayfanın listelerine sığmayan işlem olursa (en fazla 198 forward, 248 OIS
bacağı, 248 tahvil) sayısı da yazar; maliyet tabloları (parite ve valöre, vadeye, enstrümana göre) her zaman bütün
işlemleri sayar. Geçmiş tek bir gün, o günün gün sonu özetiyle gelir (gün açıkken saklanan tablolar); özeti olmayan
geçmiş gün (o gün dashboard açılmamışsa) aralık gibi kendi işlemleriyle hesaplanır ve bunu söyler. Bu tablolar
yenilemede yalnızca değişenle yeniden hesaplanır (son dört aralık saklanır).

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
    ve sütun başlığından gelir; birimi ⋯ ile seçilir). Adı olan bir ölçü olmasa da **bir kâğıdın satırındaki her
    hücre** (DİBS RV - ör. DV01 -, DİBS Trading, Tüm Kâğıtlar'ın bid / ask / son işlemi, DİBS ASW) o kâğıdın, **bir
    VİOP kontratının sütunundaki her hücre** (kontratlar, BID / ASK - swap puanı, günlük SP, VKGS … -, OIS, ICAP,
    matrisin kontrat satırları, altın-TRY bid / ask ve altın-USD tabloları) o kontratın hücresi olarak izlenir: liste
    değişse, kâğıt satır değiştirse, kontratlar dönse de aynı kâğıt / kontrat; hücre gibi okunur (birimi ⋯ ile seçilir).
    Kâğıtsız bir satırın hücresi, hesaplayıcıların sütunları ("1. kontrat": yerdir, kontrat değil) ve iki kontratı
    eşleyen matrisler hücre olarak kalır. Önceki sürümün hücre olarak sakladığı kalemler ve alarmlar (masa alarmları
    dahil) bu sürümün ilk açılışında bir kereye mahsus o an gösterdikleri kâğıda / kontrata bağlanır: birimi, alarm
    seviyesi ve dashboard'un kaydettiği kapanışlarıyla (`kv` · `migrated.watch_anchor`).
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
  **Ses için sekmeye bir kez tıklayın:** Chrome / Edge, hiç tıklanmamış (ya da klavyeye dokunulmamış) bir sekmede ses
  çaldırmaz. Böyle bir sekmede alarm çalınca uyarı ve bildirim gelir, sesin yerine bir kez "🔇 Bu sekmede alarm sesi
  kapalı … ses için sayfaya bir kez tıklayın" yazar; sayfaya bir kez tıklandıktan sonra alarmlar (masa alarmları, güçlü
  sinyaller ve ajanda da) sesle çalar.
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
  "Brokerlar" kutusuyla gizlenir). "Bid · kimde" / "Ask · kimde" sütunlarını gizleyen kullanıcıda tek broker'ın da kendi
  satırı gelir (broker'ın adı tahtada başka hiçbir yerde kalmaz); sütunlar yeniden gösterilince o satırlar kalkar.
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
  toplantıdan sonrakine) satırın son sütununda **ima PPK adımı** vardır: seviyenin ON karşılığı − toplantıdan önceki dönemin
  bootstrap seviyesinin ON karşılığı (bp; ilk toplantıda spot'tan toplantıya, sonrakilerde önceki toplantıdan); yanında
  bootstrap'ın kendi adımı ("adım −62 / −52 bp · model −68"). **ON karşılığı TLREF'in işlediği gibidir** (masa,
  25.11.2026: "B"): yalnız iş günlerinde bileşik (masanın TRY tatil listesi) - Cuma'nın faizi hafta sonu boyunca üç gün,
  tatilde aradaki günler kadar tek adımda işler -, ACT/365; MPC ima modelinin bileşiği, OIS · PPK'daki *MPC OIS → PPK
  ADIMI*'yla aynı hesap, aynı sayı (aşağıda). PPK Fiyatlama Geçmişi'ndeki adım MPC çözücüsünündür, burada piyasa
  bootstrap'ı kullanılır. İki dönemi birbirine karşı koyan kota (adım: `dec vs jan mpc -25/-20`, `… spread`,
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
  kayıt silinirse satır yeniden aranır; düzenlenen kayıt eşleşmesini korur (kimliği aynı kalır). Gün sonu arşivi indirilmeden önce girilmemiş işlem varsa uyarılır.

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
(`TRT150328T24` → 15.03.2028). DİBS RV ve DİBS Trading'in "+ ISIN ekle"si trading listesine ekler: kâğıt **DİBS ASW
listesine** ve - orada yoksa - **Tüm Kâğıtlar**'a da gider (aşağıda); DİBS ASW'ninki yalnız kendi listesine ekler.

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
  `ISL1`; kaynaklar sarı hücrelerde), trading listesindekiler için DİBS RV'nin getirisi, getirinin **ON karşılığı**
  (aşağıda: *Getirinin ON karşılığı*), ASW / DM'i, sinyali ve DV01'i, sağda bugünün Broker Chat tahtası, ▸ kart ve ✕. Liste **masanındır** (herkes görür, herkes değiştirir): başta
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
  **Her kâğıt sayfanın arkasındaki satırını korur** (`EK_EVREN`, her kâğıt bir satır): yeniden başlatmada liste baştan
  dizilmez (satırlar `kv` · `bonds.rows`'ta), yeni kâğıt hiç kullanılmamış bir satıra girer, ötekiler yerinde kalır;
  vadesi geçen ya da ✕ ile çıkan kâğıdın satırı boşalır, o satıra yazılmış "Elle değer" kâğıtla gider ve satır ancak
  hiç kullanılmamış satır kalmayınca (en eski boşalan önce) yeniden kullanılır. Böylece bir kâğıdın fiyatına kurulan
  alarm, "Elle değer" ve satırına başvuran formül o kâğıdın kalır (alarm zaten kâğıdı ISIN'iyle izler).
* **☆ / ★** kâğıdı **trading listesine** (DİBS RV - ve onunla DİBS Trading) koyar ya da çıkarır; herkes için. Eklenen
  kâğıt listenin son kâğıdının altına girer (masanın gruplar arasında bıraktığı boş satırlar boş kalır; sonda yer
  kalmayınca onlar kullanılır). Çıkarılan kâğıdın satırı boşalır, satırdaki her şey kâğıtla gider (aşağıda: *Kâğıdın
  satırındaki değerler kâğıdındır*): kaynak kodu, herkesin o satıra yazdığı manuel fiyat, kupon, repo, "Elle değer" -
  kaydedilmiş senaryolarda da.
* **DİBS ASW**'nin ISIN listesi (`ASW!B7:B56`, ASW eğrisi ve grafikleri) trading listesini **her yoldan** izler. Trading
  listesine giren kâğıt - ★, DİBS Trading ya da DİBS RV'deki "+ ISIN ekle", kâğıt kartındaki "DİBS RV listesine ekle",
  DİBS RV'nin ISIN hücresine yazmak ya da birkaç ISIN'i birden yapıştırmak - ASW listesine de girer (listede yoksa, son
  kâğıdın altına; ASW listesinde yer kalmadıysa yalnız trading listesine girer ve uyarı "DİBS ASW listesinde yer yok"
  der) ve **Tüm Kâğıtlar**'da yoksa oraya da eklenir (türü, vadesi ve kuponu Bloomberg'den, Tüm Kâğıtlar'ın "+ ISIN
  ekle"si gibi; döviz cinsi kâğıt oraya alınmaz, uyarı nedenini söyler). Trading listesinden çıkan kâğıt - ☆, ✕, ISIN
  hücresini silmek ya da üzerine başka ISIN yazmak, masanın listesinin dosyadakine sıfırlanması - ASW listesinden de
  çıkar, satırının kaynağı, herkesin manuel fiyatı / eğri işareti ve "Elle değer"iyle (*Kâğıdın satırındaki değerler
  kâğıdındır*); Tüm Kâğıtlar'da kalır. Aynı yazmada liste içinde yer değiştiren kâğıt iki listede de yerinde kalır.
  ISIN olmayan bir metin hiçbir yere gitmez. ASW sayfasının kendi "+ ISIN ekle"si yalnız ASW listesine ekler; trading
  listesinde olmayan böyle bir kâğıda trading listesinin değişiklikleri (✕ dahil) dokunmaz. ASW listesinden elle
  çıkarılan bir trading kâğıdını ★ geri koyar. Uyarı (toast) ASW listesine ve Tüm Kâğıtlar'a ne olduğunu ve satırların
  nesinin taşındığını ya da silindiğini söyler. Bu sürümün **ilk açılışında, bir kereye mahsus**, trading listesinde olup
  ASW listesinde olmayan kâğıtlar ASW listesine eklenir (günlükte yazar; masanın verisinde iki listede de aynı 19 kâğıt
  vardı, bir şey değişmez).
* **DİBS Trading** sayfasının başındaki **özet**, trading listesini türüne ve vadesine göre gruplu tek bakışta verir;
  sütunları başlıklı gruplardadır: kâğıt (★ - listeden çıkar -, ad, ISIN, vade, kalan yıl) · **Fiyat** (kâğıdın
  fiyatlandığı valör ve kaynağı, bid / ask, son işlem ve ne zaman olduğu - canlıda görüldüğü saat) · **OIS'e göre**
  (DİBS RV'den getiri, getirinin **ON karşılığı** - *Getirinin ON karşılığı* -, ASW / DM, **adil getiri**, **adil fiyat**,
  pahalı / ucuz, sinyal) · **FX swap'a göre** (ASW FX,
  adil getiri, adil fiyat, pahalı / ucuz FX, sinyal FX - hepsi DİBS ASW'nin FX swap ima eğrisi (TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden; fiyatı yoksa OIS)'ndeki hesabı) · **Risk** (mod. süre, DV01 / 1mn, 1.000$ DV01 nominal) ·
  **Carry** (C+R, T0→T1 ima repo) · **Broker** (bugünün Broker Chat tahtası) · ▸ (kart). Sütun başlıklarının üzerine
  gelince neyin nasıl hesaplandığı yazar. Eski sütunlar harflerini korur: birinin gizlediği ya da sıraladığı sütun, bir
  launchpad kutusunun seçtiği sütun yine odur; yeni sütunlar onların ardından sayılır. Satırlar da eskisi gibi
  numaralanır (gruplar satırı başlıktır): kâğıtlarını satır numarasıyla tutan eski bir launchpad kutusu aynı kâğıtları
  gösterir; yeni seçilen satır kâğıdıyla (ISIN'i ya da TLREF'te adı) tutulur, liste değişse de o kâğıttır. Ayrıntı
  altta (valörler, günün işlemleri) ve DİBS RV'de.
  **Adil getiri / adil fiyat** (`tto/rvfair.py`): kâğıdın ASW'si uydurulan ASW eğrisinde (`a + b·t + c·t²`) dursaydı
  getirisi ve valördeki temiz fiyatı - OIS'te DİBS RV'nin eğrisi (`CA3:CC3`, sabit kuponlulara uydurulur, `t` OIS
  spot'tan vadeye yıl), FX swap'ta DİBS ASW'nin **FX swap ima eğrisi (TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden; fiyatı yoksa OIS)** üzerindeki eğrisi (`ASW!AW3:AY3`, sayfanın Eğri /
  grafik kuralıyla; DİBS ASW'nin "ASW FX" sütununun ve FX swap grafiğinin hesabı). Eğrinin ASW'sinde kirli fiyat @spot =
  kâğıdın o eğrideki bugünkü değeri − eğri ASW × annuity / 100 (OIS'te DİBS RV'nin `EG`, `EE`; FX'te DİBS ASW'nin `P`, `Q`
  - ASW'nin kendi formülünün tersi), valöre fonlama çarpanıyla (OIS'te `DD`; FX'te DİBS ASW'nin `O / (L + N)`'si) döner,
  temizi − işlemiş faiz (`CW`; DİBS ASW'de `N`, aynısı); getiri ekrandaki gibi BIST bileşik (sabit
  kuponluda kâğıdın nakit akışlarını - `ID:JA`, `LV:MS` dönem - kirli fiyata iskonto eden basit faizin bileşiği,
  bonoda `(100 / kirli)^(365 / gün) − 1`). Kâğıdın kendi ASW'sinde adil fiyat ekrandaki fiyattır; eğriye göre ucuz kâğıdın
  adil fiyatı ekrandakinden yüksek, adil getirisi düşüktür. **Bono** eğriye girmez (eğri sabit kuponluların): eğrinin
  bono vadesindeki değeri kullanılır, ipucu söyler; eğriye giren kâğıtların vadelerinden çeyrek yıldan fazla dışarıdaysa
  (ASW grafiğinin eğriyi çizdiği kadar) eğri uzatılmış demektir, soluk gösterilir. **TLREF'e endeksli** kâğıtta adil
  fiyat yoktur (eğriler sabit kuponluların ASW'sine; DM için uydurulmuş eğri yok - kâğıdın DM'i ASW / DM sütununda),
  FRN ve TÜFE'de de yok; DİBS RV'nin hesaplamadığı (fiyatı olmayan) kâğıt, eğrisi uydurulamayan taraf (en az 2 sabit
  kuponlu gerekir) ve DİBS ASW listesinde olmayan ya da DİBS ASW'nin hesaplamadığı kâğıdın FX tarafı için de yok - hücrede
  soluk "–", üzerine gelince nedeni. Her sayının ipucunda hesabı (eğri, eğrinin ASW'si, bugünkü değer, annuity, kirli,
  temiz, ekrandaki getiri; FX getirisi DİBS RV'nin nakit akışlarıyla, aynı valörde). Pahalı / ucuz ve sinyal OIS'te DİBS
  RV'nin kendi sütunlarıdır (`AB`, `AC`); FX'te DİBS ASW'nin o eğrideki ucuz / pahalısı (`T` = ASW − eğri) ve DİBS RV'nin
  eşiğiyle (`P2`, "Eşik (bp)") UCUZ / PAHALI. **FX swap tarafı her yerde aynı eğri:** masa FX swap ima eğrisi (TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden; fiyatı yoksa OIS)'ni seçti - DİBS
  Trading'in FX grubu, kâğıt kartı ve DİBS RV · Genel aynı sayıları gösterir (testle); DİBS RV'nin kendi FX sütunları
  (`BF:BJ`, FX swap - offshore ICAP eğrisi) çalışma kitabının formülleri olarak yalnız RV hesap tablosunda kalır ve
  orada **varsayılan olarak gizlidir** (aşağıda, DİBS RV · Genel).
  Ekranın fiyatından çıkan değerler canlı kota yokken soluk, adil değerler kâğıdın kendi fiyatına dayanmadığı için
  değil. Aynı değerler kâğıt kartındadır. Yeni Bloomberg isteği yoktur.
  **1.000$ DV01 nominal** sütunu, DV01'i 1.000 USD olan TL nominali verir: 1.000 × USDTRY ÷ DV01 / 1mn, en yakın
  5 mn'a yuvarlı (`500m`; TLREF'te spread DV01'i). USDTRY masanın kullandığı kurdur: VİOP!L99 / L100'ün ortası
  (manuel spot, boşsa Bloomberg). Üzerine gelince hesap görünür.

**Kâğıdın satırındaki değerler kâğıdındır, satırın değil.** DİBS RV (ve onunla DİBS Trading), DİBS ASW ve her
kullanıcının kendi Eurobond Kotaları listesinde bir kâğıdın satırına yazılanlar - masanın kâğıt bazındaki fiyat
kaynağı, herkesin manuel temiz fiyatı, bilinen kuponu, reposu, eğri işareti, satırın herhangi bir hücresine yazılmış
"Elle değer" - kâğıdın **ISIN'ine bağlı** tutulur. Liste nasıl değişirse değişsin (ISIN'in üzerine başka ISIN yazmak ya
da yapıştırmak, listeyi yeniden sıralayıp yapıştırmak, ☆ / ★, "+ ISIN ekle", ISIN'i silmek, ortak sıfırlama, satırları
değişmiş bir Excel dosyası) bir satırın değerleri kâğıdıyla birlikte **kâğıdın yeni satırına taşınır**; kâğıt listeden
çıktıysa **onunla birlikte silinir** - herkes için, masanın değerleri ve **kaydedilmiş senaryolar dahil** (eski bir
senaryo yüklenince değer başka bir kâğıdın satırına düşmez). Kâğıtsız bir satıra yazılmış değer oraya bir kâğıt girince
silinir. Çalışma kitabının kâğıt bazındaki kendi kaynakları (`DİBS RV!B5:B15`, `ASW!C7:C16`: bonolarda `ISL0`) da o
satırdaki kâğıdındır: kâğıtla taşınır, kâğıdın bıraktığı satır boş kaynakla (genel kaynak) kalır. Listeyle aynı yazmada
yazılan değerler yazıldığı satıra gider (ISIN'iyle birlikte yapıştırılan kaynak gibi). Formül taşınmaz, değeri taşınır
(başvuruları taşınmazdı). Hepsi tek işlemde olur ve listeyi değiştirene bir uyarıyla söylenir: "DİBS RV · … TRT150328T24
satır 8 → 29 (3 değer taşındı); TRT081128T15 listeden çıktı: satır 10, 2 değer silindi · 1 senaryo da". Değerler
veritabanında yine hücre adresiyle durur; her listenin satırlarının hangi kâğıda ait olduğu ayrıca saklanır (`kv` ·
`rowkeys.dibs`, `rowkeys.asw`, kişisel liste için `rowkeys.bulk:<kullanıcı>`) ve her değişiklik (açılışta bulunan
dahil) buna göre yapılır. Bu sürümün ilk açılışı satırları olduğu gibi alır: her satırın değerleri o an orada duran kâğıdındır,
hiçbir şey taşınmaz ya da silinmez. Bir formülün ya da hesap tablosunun `DİBS RV!N8` gibi başvurusu ise satıra bağlıdır:
satırda hangi kâğıt varsa onu okur.

**Satırın kendisine ait olanlar** (formun parçası, kâğıtla gitmez): Eurobond Kotaları'nda kullanıcının **kendi bid /
ask**'i (`Bulk Bond!C3:D52`: o satıra yazdığı kendi kotası - satıra başka kâğıt yazınca kotayı da yeniden yazın; aynı
satırdaki "Elle değer" ise kâğıtla gider); **Hazine İhalesi**'nin üç kâğıt bloğu (`EK_IHALE`: bloğun valörü, teklifleri -
nominal, temiz fiyat, getiri -, gerçekleşen nominali ve açıklanan fiyatlar bloğundur: bloğa başka ISIN yazmak o blokta yeni
bir ihale demektir, eski teklifleri silin); **Manuel Tahvil**'in dönem bazındaki elle girdileri (`B24:H63`: dönem
tarihleri, tip, sabit kupon / ek getiri / anapara, bilinen kupon - kâğıdın vadesi ya da kuponu değişince dönemler yeni
kâğıdındır, eski dönemlerin elle değerleri kalır).

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
ekler, kâğıt DİBS ASW'ye de gider) - yalnız kâğıt tutan satırlar: DİBS RV'deki grup araları ve kullanılmayan satırlar
gösterilmez (yalnız görünüş: hücreler yerinde, DİBS RV aynı) - üç valörde yan yana: **T0** (aynı gün), **T1** (ertesi
iş günü), **T2** - her valör bir Bloomberg fiyat kaynağıdır (`ISL0`, `ISL1`, `ISLN`; sarı hücreye başka kod yazılabilir, boşaltılırsa varsayılan kullanılır). Her valörde bid, ask,
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
  günün işlemleri, DİBS RV satırı (getiri, ASW, sinyal, süre, DV01, carry, gün içi aralık; OIS eğrisine göre adil getiri ve
  adil fiyat; FX swap ima eğrisi (TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden; fiyatı yoksa OIS)'nde ASW FX ima, pahalı / ucuz, sinyal, adil getiri ve adil fiyat - DİBS Trading'in özetindeki
  sayılar -, hesabı ipucunda). Listede olmayan kâğıtta katalog bilgisi ve "DİBS RV listesine ekle"
  düğmesi (kâğıt DİBS ASW'ye de gider).

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
gösterir. Tersi de toplu (masa, 23.11.2026: "forward rate'lerden faizi de toplu olarak bulabilmeliyim"): **USDTRY fwd
(elle)** / **EURTRY fwd (elle)** sütunlarına forward yazılır ya da Excel'den bir sütun yapıştırılır, yanlarındaki **İma
TRY %** onun ima ettiği TRY faizidir - USDTRY / EURTRY fwd sütunlarının tam tersi (aynı spot, USD / EUR faizi ve gün).

**TOPLU FORWARD iki yönlü** (masa, 24.11.2026: "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız
için"; genel kural: Kullanım'daki *İki yönlü tablolar*). Bir satırın **Manuel TRY %**'si, **Spread (bp)**'si, **ON
karşılık %**'si (aşağıda), **USDTRY fwd**'si, **puan**'ı ve **P/gün**'ü, **EURTRY fwd**'si, **puan**'ı ve **P/gün**'ü
yazılabilir: **hangisini yazarsanız o kalır, diğerleri ondan hesaplanır** (tablonun altında da yazar; yazılan ✎ ile
işaretli). Satırın iki paritesi **tek TRY
faiziyle** fiyatlanır: USDTRY forward'ını (ya da puanını) yazınca Manuel TRY % onun ima ettiği faiz olur ve satırın EURTRY
forward'ı da o faizle değişir; EURTRY'yi yazınca tersi. Puan yazılınca fwd = spot + puan/10000; forward'dan faiz USDTRY /
EURTRY fwd sütununun tam tersidir (aynı spot, USD / EUR faizi ve gün; EURTRY'nin günü EURTRY spot valöründen). Son
yazılan geçerlidir; `Delete` satırın bu dokuz hücresinden herhangi birinde satırı RET mid'e (genel spread yazılıysa RET
mid + genel spread'e) döndürür; Excel'den yapıştırılan bir sütun (ör. USDTRY fwd'ler) her satırın yazılanı olur. Önceden
yazılan Manuel TRY %'ler aynen durur; fwd / puan'ın yazılanları satırın gizli sütunlarında (`Z:AC`, ON karşılık'ınki
`AE`, spread ve P/gün'lerinki `AF:AH`; verdikleri TRY faizi `AD`) saklanır, yardımcı tabloda görünür. **USDTRY fwd (elle)** / **EURTRY fwd (elle)** sütunları ayrıca durur: yazılan forward'ın ima
ettiği faizi gösterir, satırı değiştirmez.

**ON karşılık %** (masa, 26.11.2026: "Toplu forward fiyatlama kısımlarında ON karşılıklarını da görmek istiyorum").
Manuel TRY % ile USDTRY fwd arasındaki sütun, **satırı fiyatlayan TRY faizinin** - Manuel TRY % (yazılan ya da yazılan bir
forward / puandan hesaplanan), boşsa RET mid %; USDTRY / EURTRY fwd'nin kullandığı faiz - **günlük bileşik karşılığıdır**:
Forward'daki hesaplayıcıların *ON Karşılık*'ının aynısı, 360·((1 + faiz·Gün/360)^(1/Gün) − 1), Gün satırın Gün'ü (valör −
USDTRY spot). Takvim günleri ve 360 gün bazı - FX'ten çıkan bir faizin ON'u; TLREF'in iş günlerinde bileşiği (OIS · PPK,
Broker Chat) değil. Örnek: 120 gün, %35,30 → %33,3884; %35,0135 → %33,1317. Valör yoksa ya da valör spot günüyse (Gün 0)
boş; iki ondalıkla görünür (değeri bütün ondalıklarıyla). **İki yönlü**: ON da yazılabilir - satırın TRY faizi ondan
tersiyle bulunur, ((1 + ON/360)^Gün − 1)·360/Gün; Manuel TRY % onu gösterir, USDTRY ve EURTRY fwd / puan o faizle
hesaplanır (EURTRY kendi günüyle). Excel'den bir ON sütunu da yapıştırılabilir. **İşleme al**'da ON bir fiyat değildir:
ON'u yazılmış satır USDTRY'de satırın gösterdiği TRY faiziyle (Manuel TRY %), EURTRY'de EURTRY fwd'siyle girilir (not:
`· ON karşılık %`); ON hücresinin sağ tık menüsünde İşlem gir yoktur (ON bir forward fiyatı değil).

**Spread, genel spread, P/gün, dönem ve faizlerin ON'u** (masa, 26.11.2026: "Bunların da hepsini yap"):

* **Genel spread (bp)** (tablonun başında, etiketinin yanındaki kutu; her kullanıcının kendisinin): satırına bir şey
  yazılmamış satırlar **RET mid + genel spread**'le fiyatlanır - forward'lar, puanlar, ON ve satırın faizinden çıkan her
  sütun. Boşsa RET mid, eskisi gibi (her değer aynen). Satırında bir değer yazılı olan satır kendi faiziyle kalır; Manuel
  TRY % boş kalır, Spread sütunu genel spread'i gösterir.
* **Spread (bp)** (RET ask %'nin sağında): satırın TRY faizi − RET mid, bp, bir ondalık. İki yönlü: spread yazılınca TRY
  faizi = RET mid + spread/100, forward'lar izler.
* **USDTRY P/gün / EURTRY P/gün**: puan / gün - EURTRY kendi günüyle (valör − EURTRY spot) -, valör tablolarındaki P/gün
  gibi. İki yönlü: P/gün yazılınca puan = P/gün · gün, forward = spot + puan/10000 ve satırın TRY faizi onun ima ettiği;
  iki parite birlikte izler (tek TRY faizi).
* **ON − RET ON (bp)**: satırın ON karşılığı − bugünün RET ON mid'i (RET tablosunun ON bid / ask ortası), bp, bir ondalık.
* **Dönem TRY % / Dönem ON %**: üstteki en yakın dolu satırın valöründen bu satırınkine forward-forward faiz,
  ((1 + r2·g2/360) / (1 + r1·g1/360) − 1)·360/(g2 − g1) - r her satırı fiyatlayan TRY faizi, g Gün'ü - ve onun bu
  dönemdeki ON'u. İlk dolu satır spottan: kendi faizi. Aradaki boş satır atlanır; tarihler artmıyorsa boş.
* **ON · Offshore mid % / OIS mid % / RET bid % / RET mid % / RET ask %**: her faizin aynı 360 formülüyle ON'u. OIS de 360
  bazında - tablo bu faizleri yan yana % olarak gösterir, Masa'nın "O/N EŞLENİKLERİ · 360 bazında" tablosu da OIS'i ve
  offshore'u 360'la karşılaştırır; TLREF'in iş günlerinde bileşiği OIS · PPK'nın ve Broker Chat'indir.
* Valör spot günüyse (Gün 0) ya da spottan önceyse ON ve dönem sütunları boş - Forward'ın öbür tablolarındaki ON'lar
  gibi; P/gün de Gün 0'da boş.
* **İşleme al**: USDTRY P/gün yazılmışsa USDTRY puanı yazılmış gibi (*Forward kur* = satırın USDTRY fwd'si), EURTRY P/gün
  EURTRY puanı gibi; spread yazılmışsa satırın TRY faizi; genel spread'le fiyatlanan satır USDTRY'de RET mid + genel
  spread faiziyle, EURTRY'de EURTRY fwd'siyle girilir. Not: `· USDTRY P/gün`, `· EURTRY P/gün`, `· Spread (bp)`,
  `· RET mid % + genel spread`. Spread ve P/gün fiyat değildir: sağ tıkta İşlem gir yoktur.
* **Yerleşim**: yeni sütunlar, satırların gizli yardımcı sütunlarının (yazılanlar, satırı fiyatlayan TRY %, dönem için son
  dolu satır - Excel'de gizli sütun gibi; *Yardımcı tablolar*'la görünür) sağında, bu sırayla: ON − RET ON, Dönem
  TRY %, Dönem ON %, USDTRY P/gün, EURTRY P/gün, ON · Offshore mid %, ON · OIS mid %, ON · RET bid %, ON · RET mid %, ON ·
  RET ask %. **Valör ve Gün** sağa kaydırırken sabit kalır.

**Tablodan işlem** (masa, 24.11.2026: "3 ekle"). Toplu forward tablosundan doğrudan işlem girilir:

* **Sağ tık → İşlem gir**: USDTRY fwd / puan, EURTRY fwd / puan, elle yazılan forward'lar ve İma TRY %'leri Günlük
  İşlemler'i satırın valörü ve tıklanan fiyatla açar; her fiyat **kendi sütununun paritesiyle** (USDTRY ve EURTRY yan
  yana). Fiyatlar mid ya da elle yazılmış olduğundan yön seçili gelmez.
* **Parite / Yön / Tutar / Karşı taraf**: her satırın sonunda dört girdi (kişisel, boş başlar). Parite USDTRY ya da
  EURTRY (boş = USDTRY), Yön AL / SAT (B / S, Alış / Satış da yazılır), Tutar paritenin ilk dövizinde (`10m`, `2,5mn`).
* **İşleme al** (tablonun başlığında): Tutar'ı yazılı her satır Günlük İşlemler'in **Excel'den yapıştır** penceresinde
  FX Forward olarak açılır - aynı önizleme, aynı "N satırı kaydet" (hepsi ya da hiçbiri, bugünün işlemleri). Tutar'ı boş
  satırlar alınmaz, pencere kaç tane olduğunu söyler; Tutar'ı olup Yön'ü ya da valörü olmayan satır hatalı satır olarak
  görünür ve kaydedilmez. Penceredeki *Satır* sütunu satırın tablodaki sırasıdır (işleme girmez).
* **Fiyat satırın gösterdiğidir**, son hanesine kadar: satırın paritesinin elle forward'ı yazılıysa *Forward kur* = o;
  satırın USDTRY fwd'si, puanı ya da P/gün'ü yazılmışsa (iki yönlü) USDTRY'de *Forward kur* = satırın USDTRY fwd'si
  (yazılan, ya da spot + puan/10000); değilse USDTRY'de *TRY faizi* = Manuel TRY % (yazılan, ya da yazılan EURTRY fwd /
  puan / P/gün'ünden, ON karşılık'tan ya da spread'den hesaplanan; boşsa RET mid %, genel spread yazılıysa RET mid % +
  genel spread) - Günlük İşlemler'in TRY faiziyle fiyatlaması toplu satırın kendi formülüdür, forward tablonun USDTRY
  fwd'sinin aynısı -; EURTRY'de *Forward kur* = tablonun EURTRY fwd'si
  (Günlük İşlemler'in EURTRY'yi TRY faiziyle fiyatlaması EUR faizini eğrinin bid / ask ortasından alır, tablo
  Bloomberg'in MID'inden: ikisi ancak MID tam orta olduğunda aynıdır, bu yüzden tablonun outright'ı girilir). Not neyden
  geldiğini söyler: `TOPLU FORWARD · RET mid %`, `· Manuel TRY %`, `· elle forward`; satırın faizi yazılan bir forward /
  puandan geliyorsa `· USDTRY fwd`, `· USDTRY puan`, `· EURTRY fwd`, `· EURTRY puan`; yazılan ON'dan, spread'den ya da
  P/gün'den geliyorsa `· ON karşılık %`, `· Spread (bp)`, `· USDTRY P/gün`, `· EURTRY P/gün`; satırda bir şey yazılı
  değil de genel spread yazılıysa `· RET mid % + genel spread`.
* **Kaydedilen satırların Tutar'ı tabloda silinir** ("N işlem kaydedildi; tutarları temizlendi"): ikinci basış onları
  yeniden girmez. Valör, faizler, Parite, Yön ve Karşı taraf kalır; kaydedilmeyen (hatalı) satırın Tutar'ı da kalır.

**Puandan faize** (öneri 2, masa onayladı: "1-2-3-4 yap"; aynı sekmede). **Forward starting swap**'ta *Elle puan → faiz*
satırları: bir broker'ın ya da müşterinin verdiği FS swap puanını yazın (USDTRY `I181`, EURTRY `O182`). Yanında ima
ettiği **TRY fwd-fwd %** - Manuel satırının formülünün tersi: aynı near / far valör, near outright RET mid'den, aynı USD
/ EUR fwd-fwd % (`C170` / `C171` ya da eğri) - ve OIS mid, offshore mid, RET mid'e göre bp. **Çapraz forward**'da
*XXXTRY fwd (elle)* sütunu: yazılan forward'ın ima ettiği TRY faizi, döviz bacağı sabit (manuel forward'ın tersi: USD /
EUR'da o dövizin OIS faizi ve günü, başka dövizde Bloomberg'in USDXXX forward'ının ortası); yanında RET mid'e göre bp.

**Forward starting swap ve Çapraz forward iki yönlü** (masa, 24.11.2026: "tüm tablolar bu şekilde olmalı").
**FORWARD STARTING SWAP**'ın **Manuel** satırında **TRY fwd-fwd %** (`C169`), **TRY far %**, USDTRY **far outright**, **FS
puan** ve **günlük puan**, **EURTRY far** ve **EURTRY puan** yazılabilir: hangisini yazarsanız o kalır, diğerleri satırın
formüllerinin tam tersiyle ondan hesaplanır (near bacak RET mid, USD / EUR fwd-fwd % `C170` / `C171` ya da eğri;
EURTRY'nin dönemi EURTRY spot valörlerinden). Tek TRY fwd-fwd % iki paritenin far bacağını fiyatlar: USDTRY değeri yazınca
EURTRY'ninkiler de değişir, tersi de. Satır, near / far valörü geçerliyken (Durum OK) dolar; değilse yalnız yazdığınız
değer görünür. EURTRY'nin dönemi yoksa (far valörü EURTRY spot valöründen önce) EURTRY değerinden faiz çıkmaz. `Delete`
satırın herhangi bir değerinde satırı boşaltır. Geçici kopyada da iki yönlüdür (tablonun kendisinde `C169` yazılıysa
kopyada satırın başka bir değeri yazılamaz: nedeni söylenir). *Elle puan → faiz* satırları ayrıca durur.
**ON karşılık** (masa, 26.11.2026: "Toplu forward fiyatlama kısımlarında ON karşılıklarını da görmek istiyorum" -
"Bunların da hepsini yap"): her satırda (eğriler, Manuel, Elle puan → faiz) **TRY far %**'nin yanında **ON far %**
(spot → far günüyle) ve **TRY fwd-fwd %**'nin yanında **ON fwd-fwd %** (near → far günüyle: dönemin forward ON'u) -
Forward hesaplayıcılarının *ON Karşılık*'ı: `360·((1 + TRY·g/360)^(1/g) − 1)`. Manuel satırda ikisi de yazılabilir: ON
fwd-fwd yazılınca TRY fwd-fwd % = `((1 + ON/360)^g − 1)·360/g`; ON far yazılınca far TRY % öyle, TRY fwd-fwd % ondan (far
TRY % yazılmış gibi); satırın kalanı izler.
**ÇAPRAZ FORWARD**'da her satırın **Manuel TRY %**'si ve **manuel forward**'ı (*XXXTRY fwd (manuel)*) yazılabilir:
hangisini yazarsanız o kalır, diğeri ondan hesaplanır (döviz bacağı sabit; *XXXTRY fwd (elle)*'nin aynı tersi). Yazılan
forward **yazıldığı dövizindir**: `C197`'deki döviz değişince (yazınca, silince ya da dosyadakine dönünce) yazılan
forward'lar silinir, satır yazılan TRY %'ye (yoksa boşa) döner; yazılan TRY % kalır - TRY faizi her dövizde aynıdır. 1M–12M
satırlarının valörü her gün spot'la kayar: yazılan forward satırında kalır, faizi o günün valörüyle hesaplanır.
**ON karşılık** (26.11.2026): **Manuel TRY %**'nin yanında **Manuel ON %**, **İma TRY %**'nin yanında **İma ON %** -
o faizin, forward'ın onu uyguladığı günle (USD ve başka dövizde USDTRY spot valöründen, EUR'da EURTRY spot valöründen)
ON karşılığı. Manuel ON % de yazılabilir (Manuel TRY % ondan, manuel forward izler); bir TRY faizi olduğundan döviz
değişince **kalır** (Manuel TRY %'si yeni dövizin günüyle yeniden hesaplanır), yazılan forward'lar gider.

**Tahvil carry: fiyattan repo** (masa, 24.11.2026, 8. madde: buy / sell-back fiyatından ima repo; Forward →
Hesaplayıcılar → *Tahvil carry / başabaş*). Hesaplayıcı repodan başabaşa gider: `B/E = Temiz Fiyat − Kupon + Dirty Price ·
Carry / 365 · N` (temiz fiyat; Kupon = Coupon · N / 364 · 100, N = End Date − Settlement). Altındaki **Fwd temiz fiyat
(elle)**'ye bir geri satım (forward) temiz fiyatı yazılır, **İma repo** onun ima ettiği repodur - aynı formülün tersi:
`(fiyat − Temiz Fiyat + Kupon) · 365 / (Dirty Price · N)`. Bulunan repo Carry'ye yazılınca B/E yazılan fiyat olur.
Dirty Price ve kupon hesaplayıcının kendi hücreleridir: yeni bir Bloomberg isteği yok (yazılan fiyatın getirisi -
`YAS_BOND_YLD` o fiyatla - yeni bir istek olurdu, eklenmedi). Girdi kişiseldir, boş başlar. Kâğıdın **ISIN** satırı
tablonun ilk satırıdır: hesaplayıcının girdileri boş başladığından beri ISIN boşken o satır tablo başlığı sanılıp
gizleniyordu; artık hep tablodadır.

**Hesaplayıcılar iki yönlü** (masa, 24.11.2026: "Genel olarak tablolar bu şekilde olmalı karışıklık olmaması için", "Bu
söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız için"; genel kural: Kullanım'daki *İki yönlü tablolar*).
Forward sayfasının hesaplayıcılarında bir bloğun aynı şeyi söyleyen değerlerinin **hepsi** yazılabilir: **hangisini
yazarsanız o kalır, diğerleri ondan hesaplanır** (her tablonun altında da yazar). Yazılan değer kalın ve ✎ ile işaretlidir,
piyasa (spot, döviz faizi, tarih) değişse de aynen durur; **son yazılan geçerlidir**; `Delete` bloğun herhangi bir hücresinde
bloğu varsayılanına döndürür. Hesap bloğun kendi formülleri ve tam tersleridir:

* **Interest 2 SP, SP 2 Interest, all-in ve O/N** (Hesaplayıcılar; USDTRY ve EURTRY ayrı): TRY, SP, All In S -> E (SP 2
  Interest'lerde E -> S de), ON karşılık ve günlük SP. `SP = spot·((1 + TRY·g/b)/(1 + USD·g/b) − 1)·10000` (b 360;
  Interest 2 SP'nin USDTRY'sinde Gün Bazı), SP yazılınca `TRY = ((1 + SP/10000/spot)·(1 + USD·g/b) − 1)·b/g`; All In =
  spot ± SP/10000; `ON = 360·((1 + TRY·g/360)^(1/g) − 1)`, ON yazılınca `TRY = ((1 + ON/360)^g − 1)·360/g`; günlük SP =
  SP/g. Hiçbir şey yazılmamışsa her blok eskisi gibidir (dosyanın değerleriyle: Interest 2 SP'nin TRY'si, SP 2 Interest'in
  SP'si, all-in'in kuru, O/N'nin faizi). Tarih, spot ve döviz faizi bloğun girdileri olarak kalır.
* **Basit ↔ bileşik · Repo**: her çeviricinin iki faizi (günlük bileşik faiz ↔ dönemin basit faizi, çeviricinin Gün Basis
  ve Gün'üyle).
* **Forward DV01** (Forward fiyatları): Tutar, DV01_USD, DV01_TRY, TRY_USD_DV01. Yazılan DV01'in **mutlak değeri** tutarı
  verir, işareti B/S'den gelir (S: USD DV01 artı, TRY DV01 eksi; B tersi). Tutar'a `5m` yazılır.
* **Tahvil carry**: Carry (repo), B/E, Px Drop ve günlük Px Drop. B/E (ya da Px Drop) yazılınca Carry, İma repo'nun
  formülüyle bulunan repodur. B/E Yield ve Yield Drop yazılmaz: yazılan getiriden fiyat her seferinde yeni bir Bloomberg
  isteği olurdu. Fwd temiz fiyat (elle) → İma repo olduğu gibi kalır. Carry boş başlar.
* **TRY OIS w/Spread** (Eğriler): Spread ya da bir vadenin spread'li faizi - bir vadeyi yazınca Spread = o faiz − OIS,
  öbür vadeler Spread'den; valörün OIS mid'i + spread'i (`P27`) yazılınca spread'i (`O27`). Silince ikisi de Masa'daki
  spread'e (`MASA!I60`) döner.

Geçici kopyalarda (Interest 2 SP … Repo, Forward DV01) her değer kopyanın kendisinde de yazılabilir - tabloda başka bir değer
yazılmış olsa bile. Bu özellikten önce TRY, SP, all-in, O/N, çeviricilerin sol faizi ve Tutar'a yazdıklarınız aynen durur ve
bloklarının yazılanıdır (gizli bir sütuna bir kez taşınır: `AL` / `AM` / `Q`, yardımcı tablolarda görünür); o hücrelere
formül yazılmışsa formülüyle birlikte taşınır ve canlı kalır; bu sürümden önce açılmış bir geçici kopyada o hücrelere
yazılan değer de kopyanın yazılanı olur. Tahvil carry'nin Carry'si ve iki spread yazıldıkları
yerde kalır. Yeni bir Bloomberg isteği yok.

**Implied Move: hareketten vol** (masa, 24.11.2026, 12. madde: bir straddle başabaşını vole çevirmek; Hesaplayıcılar →
Faiz çevirici → *Implied Move*). Blok volden harekete gider: `Implied Move = √(Gün / Gün Basis) · Volatilite`, sınırlar
`(1 ± hareket) · Spot`, pip `Spot · hareket · 10000`. Altındaki üç girdinin her biri ima ettiği vol'ü verir, bloğun
formülünün tersiyle: **Hareket % (elle)** → `vol = hareket / √(Gün / Gün Basis)`; **Başabaş seviyesi (elle)** - straddle'ın
üst ya da alt başabaşı; spot'un üstündeyse üst, altındaysa alt sınır: hareket `|seviye / Spot − 1|` -; **Hareket pip
(elle)** → hareket `pip / (Spot · 10000)`. Bulunan vol Volatilite'ye yazılınca blok aynı hareketi, sınırı ve pip'i verir.
Boş, sıfır ya da eksi değerde vol çıkmaz. Girdiler kişiseldir, boş başlar.

**Hesaplayıcılar iki yönlü** (masa, 24.11.2026: "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız
için"). Hesaplayıcılar sayfasının her hesaplayıcısında bloğun **her değeri** yazılabilir: **hangisini yazarsanız o kalır**,
diğerleri ondan bloğun kendi formülleri ve tam tersleriyle hesaplanır (yazılan kalın ve ✎ ile; son yazılan geçerli;
`Delete` - yazılanda ya da hesaplananda - hesaplayıcıyı varsayılanına döndürür). Hesaplanan bir değer kendi türüyle geri
yazılınca aynı sayılar çıkar.

* **Ana girdiler (üst bant):** Forward, fark (Forward − Spot) ya da puan: Forward = Spot + fark = Spot + puan / 10000.
  Forward eskisi gibi girdidir (yazdığınız değer yerinde kalır); hiçbiri yazılmamışsa piyasanın forward'ı.
* **Basit → Bileşik** ve **Bileşik → Basit:** basit ya da bileşik; bileşik = (1 + basit · gün / esas)^(esas / gün) − 1,
  basit = ((1 + bileşik)^(gün / esas) − 1) · esas / gün.
* **DF to Rate:** DF, Simple ya da Continous; DF = 1 / (1 + simple · t) = e^(−continous · t), t = (End − Start) / Gün Basis.
* **Exponential** ve **Simple** (her biri iki hesaplayıcı: faizden fiyat, fiyattan faiz): Interest ya da Forward;
  exponential Forward = Spot · e^(faiz · gün / 360), simple Forward = Spot · (1 + faiz · gün / 360).
* **Implied Move:** Volatilite, Implied Move, Upper / Lower Bound ya da Move By Pips; vol = hareket / √(Gün / Gün Basis),
  üst sınırdan hareket = sınır / Spot − 1, alt sınırdan 1 − sınır / Spot, pipten pip / (Spot · 10000) (sınır spot'un
  ters tarafındaysa vol eksi çıkar: bloğun formülünün tersi). Altındaki "… (elle)" kutuları (hareketten vol) yerinde kalır.
* **TLREF Spread:** Fiyat ya da Spread; fiyat = 100 − spread · gün / 36500.
* **Forward Volatility:** End Vol ya da Fwd Vol, Start Vol yerinde kalır; End Vol = √((Fwd Vol² · (End − Start) +
  Start Vol² · Start) / End).
* **Yıllık getiriden forward fiyat** (360): Ann. Yield ya da Forward; **İki fiyat arası yıllık getiri** (365): Last Price
  ya da Ann. Yield, First Price yerinde kalır.
* **DV01 Risk → Risk · senaryo → Senaryo P&L:** her satırda şok (Girdi 2, bp) ya da P&L (TL); şok = P&L / 1 bp'nin P&L'i
  (tek toplantı sürprizinde seçilen MPC'den sonraki risklerin toplamı, TLREF şokunda TLREF döneminin riski, paralel şokta
  toplam DV01). Şok eskisi gibi girdidir. Pozisyon yokken P&L'den şok çıkmaz (`#DIV/0!`).

Hiçbir şey yazılmamışken her hesaplayıcı eskisi gibidir (dosyanın değerleri). Yazılan değer hesaplayıcının kendi sütununda
saklanır (Calculators `AH:AT`, her biri üyesinin satırında; DV01_RISK `G69:G71`; Yardımcı tablolarda görünür).
**Önceden yazdığınız** girdiler (Volatilite, Basit, DF, Interest …) o hesaplayıcının yazılanı olur ve aynen okunur; böyle
bir girdiye **formül** yazılmışsa formülüyle birlikte taşınır ve canlı kalır (günlüğe yazılır).
**Geçici kopyada** her hesaplayıcı tam iki yönlüdür: tabloda yazılan bir değer kopyada başka bir değerin yazılmasını
engellemez. Bu sürümden önce açılmış bir kopyada hesaplayıcının eski girdisine (Volatilite, Basit …) yazılmış değer de kopyanın
yazılanı olur (kopya okunurken bir kez taşınır).

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
  panele sabitleme, ayrı pencere, tablonun sayfasına gitme ve kaldırma; ▾ kutuyu daraltır. **Satır adı günden güne
  değişmez:** adın `" · "`dan sonrası her gün ya da piyasayla değişen ayrıntıdır ve sayılmaz - MPC OIS'in satırı
  "MPC1→2 · 1.2–2.6A" (toplantılara kalan ay her gün azalır) "MPC1→2" diye, Spread · YÖN'ünki yönü dönse de "MPC1 / MPC2"
  diye hatırlanır; ad yerine yazı olarak duran tarih (Bloomberg'in valörü: ICAP eğrisinde satır vadesiyle, `1W`; VİOP
  matrislerinde vade tarihi) atlanır, başka adı olmayan satır numarasıyla tutulur. **Sıralama tabloları** (OIS'in EN İYİ 15
  SPREAD / FLY / FRA'sı, USD · FOMC'un en iyi işlemleri, Masa'nın sinyal listeleri; sayfa tanımında `"ranked": true`)
  satır numarasıyla tutulur: seçilen "ilk 5" yarın da ilk 5'tir, o günün işlemi değil. Satırların nasıl tutulacağını
  sunucu söyler (seçim penceresi tabloyu anahtarlarıyla ister); önceki sürümün tam metinle kaydettiği seçim yine bulunur
  (metin aynıysa aynen, `" · "` sonrası değiştiyse öncesiyle - tek satıra uyuyorsa). Kutular **canlıdır ve
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
* **Ctrl+K komutları** (`commands.js` okur, `commandrun.js` yapar). Kutu tablo bulmanın yanında komut da alır: yazarken önce
  komut gelir - ilk kelimesini yazarken kalıbı (Enter kutuya yazar), ne yapacağı ya da ne beklediği -, **Enter** çalıştırır,
  **Esc** vazgeçer. Türkçe ve ASCII yazım aynıdır (ı/i, ş/s, ğ/g …), büyük / küçük harf fark etmez. **Hiçbir komut kendiliğinden
  kaydetmez ya da yayınlamaz:**
  - `ret` · `ret yayınla` · `ret elle` - RET penceresi (yayınla / adil: adil değer sekmesi - yayınlamak sizin düğmeniz);
  - `işlem gir <parite> <vade> <tutar> [al | sat]` (`işlem gir usdtry 1m 10mn`, `işlem gir eurtry 3a 5m`) - Günlük İşlemler'in
    forward formu dolu açılır: parite, vade kısayolu (valör formun okuduğu gibi paritenin kendi spot kuralıyla: "1M →
    04.12.2026"), tutar kısayoluyla (`10mn`, `5m`, `500k`), fiyatlama RET mid; önce vade gelir (`5m` paritenin ardından beş ay,
    `10mn` tutar);
  - `trade <ürün> …` (`trade ois 1y 5mn`, `trade ois 2y 10m rec`, `trade sofr 5y dv01 25k pay`, `trade dibs TRT150328T24 10m al`,
    `trade spot usdtry 5m sat`, `trade opsiyon usdtry 1a 10m call`) - Trades'in "Yeni işlem" formu, kutuları sizin yazacağınız
    gibi doldurulmuş (formun kendi varsayılanları gelince);
  - `kâğıt ekle <ISIN …>` - trading listesinin "+ ISIN ekle"si ISIN'lerle (bir ya da birkaç) açılır; "Ekle" sizin;
  - `senaryo <ad>` - kayıtlı senaryonuz, adı söylenerek sorulduktan sonra yüklenir; `senaryo S2` (S1 / S2 / S3, `piyasa`) RET
    adil değerin sizin senaryo görünümünü o PPK senaryosu yapar ve pencereyi açar;
  - `sayfa <ad>` bir sayfa, `launchpad <ad>` launchpad'lerinizden biri (sayfanın adını yazmak da eskisi gibi bulur).

  Okunamayan komut ne beklediğini söyler (`"1x" vade olarak okunamadı: 1m, 3a, 1y …`); Enter onu çalıştırmaz.
* **Açılış sayfası** (sağ üstteki adınız → *Açılış sayfası…*, ya da launchpad'de / Bugün'de *Açılış sayfası yap*): dashboard'u
  adres yazmadan açtığınızda gelen sayfa - bir sayfa (listenin başında **Bugün · sabah ekranı**) ya da launchpad'lerinizden
  biri; boşsa Masa.
* **Sütun sırası.** Bir tablonun sütunlarını kendi sıranıza dizebilirsiniz: "Sütunlar" → **Sütun sırası…** (sürükleyin ya
  da ↑ ↓), ya da başlığa sağ tık → *Sütunu sola / sağa taşı*; **Excel sırasına dön** eski hâline getirir. Gizlediğiniz
  sütunlarla birlikte çalışır; sıra tablo nerede çizilirse (sayfa, launchpad, yan panel, ayrı pencere) orada geçerlidir.
  Hücreler kendi adresini korur: yazma, kopyala / yapıştır, alarm ve izleme değişmez; birleşik bir başlığın sütunları
  ayrılırsa başlık ilk sütununda kalır. Excel'den yapıştırılan blok ekrandaki sıraya oturur (sıranız V, U, W ise V'den
  başlayan üç değer V, U, W'ye); formül yazarken sürüklenen blok çalışma kitabında tek aralıksa girer (V..U → `U10:V10`),
  arada gösterilmeyen bir sütun bırakıyorsa (U → W, arada V) girmez, nedeni söylenir. Dashboard'un kendi tablolarında (Günlük İşlemler, Broker Chat, FX …) yalnız
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
* **Quant menüsü.** Yirmi quant sayfası menüde **dört giriştir**, her biri sekmeli bir sayfa: **Sinyaller** (Sinyaller,
  Gün içi, Model, Trend, Carry + momentum, Makine öğrenmesi), **Faiz** (PCA / RV, Çiftler, Korelasyon, Rejim, Eğri Adil Değeri, DİBS switch, İma Patikası,
  TCMB WIRP, Öncü-Takipçi), **FX** (FX, Makro, Opsiyon, Opsiyon → spot) ve **VİOP**. Her sayfanın adresi aynı kalır (`#/quant-pca` Faiz'i "PCA / RV"
  sekmesinde açar; sinyallerin sayfa bağlantıları, Ctrl+K, favoriler ve yer imleri eskisi gibi çalışır); sekmeye tıklamak
  o sayfanın adresine gider (geri / ileri onu bulur). Bir girişe tıklayınca **son açtığınız sekme** açılır (bu tarayıcıda
  hatırlanır).
* **Kendi menünüz** (sağ üstteki adınız → **Menüyü düzenle…**): kullanmadığınız sayfaların işaretini kaldırın, menünüzden
  çıkar - bir quant girişi bütün sekmeleriyle. **Ctrl+K ve bağlantılar onları yine açar**; *Hepsini göster* hepsini geri
  getirir. Hesabınızla saklanır (`hidden_pages`): girdiğiniz her bilgisayarda aynı menü, başka bir pencerede değiştirince
  bu pencerede de. Yalnızca yöneticilere açık sayfalar (Sayfa gezgini, Kullanıcılar, Yedekleme) yine yalnız yöneticilerin
  menüsünde ve listesindedir; menüden çıkarmak hiçbir yetkiyi değiştirmez.
* **Sıkışık görünüm** (sağ üstteki adınız → **Sıkışık görünüm** kutusu): satırlar daha alçak, hücrelerin ve panel
  başlıklarının boşlukları daha dar, tabloların yazısı bir boy küçük - bir ekrana daha çok tablo sığar. Çalışma kitabı
  tablolarında, quant sayfalarının tablolarında, launchpad kutularında, yan panelde ve ayrı pencerelerde geçerlidir.
  Yalnızca yoğunluk değişir: hiçbir satır, sütun ya da rakam gizlenmez, kesilmez; sütunlar yazıyla birlikte daralır,
  daralan tablolar yan yana sığabilir. Grafiklerin yazısı küçülmez; yanına bir tablo sığan grafik kutusunun yeni
  genişliğinde çizilir. Hesabınızla saklanır (`compact`): girdiğiniz her bilgisayarda aynı, bu tarayıcının açık
  bütün pencerelerinde (ayrı pencereler dahil) anında. İki temada da aynıdır (`<html>`'deki tek `compact` sınıfı ve
  `app.css`'in başındaki yoğunluk değişkenleri: satır yüksekliği, hücre boşluğu, yazı adımı, panel başlığı).

API: `POST /api/panels {items: [{view, panel, key?, rows?, cols?, all?, since?, as?}]}` (cevap `view/panel` anahtarlı:
tablonun kendisi, `unchanged` ya da `missing` + `status`), `GET` / `POST /api/layout` (`launchpads`, `drawer`, `favs`,
`landing`, `hidden_pages`, `compact` - gönderilen bölüm değişir, diğerleri kalır), `GET /api/layout/export?name=…`,
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
* **Toplantı hücreleri.** Bir toplantının kendi hücresine başvuru (tarihi `OIS_MAIN!P12`, adımları `U12:W12`, etiketi
  `O12`, Motor'daki satırı; FOMC'de `[sofr]SOFR_FOMC!B76`, `C76`, `P76`, `R76:T76`) toplantı takvimi değişince
  toplantısıyla taşınır; listeden çıkan toplantıya başvuru `#REF!` olur. Hesaplanan toplantı hücrelerine (`R`, `S`, `X:Z`,
  MPC OIS, MPC SPREAD …) ve birkaç toplantının satırını kapsayan aralığa (`=SUM(OIS_MAIN!U10:U20)`) başvuru yerinde
  kalır: "MPC3" üçüncü sıradaki toplantıdır, liste kayınca bir sonrakini okur (toplantı takvimi bölümü, "Bilerek böyle").
* **Bloomberg'e soran formül yok.** BDP, BDH, BDS, BFXFORWARD, BINTERPOL, RTGET ya da başka bir eklenti işlevi (`_xll.`)
  içeren formül yazılırken reddedilir ve nedeni söylenir (günlük veri limiti): değeri dashboard'daki hücresinden alın
  (`=MASA!I60`). Formüllerin okuduğu çalışma kitabı hücreleri sayfaların zaten hesapladığı hücrelerdir.
* **Yöneticilerin sayfası.** Yalnızca bir yönetici sayfasının gösterdiği sayfanın (Motor) hücreleri hesap tablosunda da
  yalnızca yöneticilere açıktır (diğerlerinde `#REF!` · "Motor sayfası yalnızca yöneticilere açık").

API: `POST /api/calc/eval {items: [{key, sheet, since?, rev?}]}` (cevap `key` anahtarlı: hesaplanmış tablo ya da
`unchanged`), `POST /api/calc/save {sheet, cells?, copy?, fmt?, widths?, rows?, cols?}` (değişikliğin hepsi ya da hiçbiri;
cevap tablonun hesaplanmış hâli). Launchpad / yan panel öğesi `{type: "calc", sheet: "<kimlik>"}` (`tto/calc.py`,
`tto/static/js/calc.js`).

#### Geçici kopyalar

Bir hesaplayıcıyla iki üç işlemi yan yana fiyatlamak için: girdileri kişisel olan bir hesaplayıcı tablonun başlığındaki
**+ Launchpad** menüsünde **Geçici kopya aç** vardır. Kopya tablonun hemen altında, aynı sekmede açılır: "… · kopya 2",
"… · kopya 3" (mor kenarlı). Her kopyanın **kendi girdileri** vardır: kopyaya yazdığınız değer yalnızca o kopyanın
sonuçlarını değiştirir - tablonun kendisini, diğer kopyalarınızı, başka sayfaları ve başka kullanıcıları değil.

* **Hangi tablolar.** Masa: KIRIK VADE & KARŞILIK, TARİH ARASI FAİZ, TARİH ARASI FORWARD (kopyası, tarihlerin ve spread'in
  durduğu üst satırla birlikte açılır: o satır kopyanın girdisidir) ve VİOP TARGET (hedef şeridiyle); Forward →
  Hesaplayıcılar: Interest 2 SP, iki SP 2 Interest, Interest 2 SP · O/N, Basit ↔ bileşik çevirici, Tarih yardımcısı,
  XARTRY müşteri altın forward hesaplayıcısı; Forward DV01 ve FORWARD STARTING SWAP; VİOP: Target ve VİOP XAUTRY altın
  hesaplayıcısı; Hesaplayıcılar sayfası: Exponential, Simple, Basit → Bileşik, Bileşik → Basit, Implied Move, DF to Rate,
  Ağırlıklı ortalama, TLREF Spread, Forward Volatility, Yıllık getiriden forward fiyat, İki fiyat arası yıllık getiri,
  TÜFE'ye endeksli. Sayfa tanımında `"copyable": true` ile işaretlidir (`tto/views/__init__.py`). **Ortak girdisi olan
  tablo kopyalanamaz** (masanın ayarının kopyası onu değiştiriyormuş gibi gösterirdi): öyle işaretlenmişse açılışta
  reddedilir ve günlüğe yazılır.
* **Nasıl hesaplanır.** Kopya, hesap motorunda sizin hesabınızın üstünde ince bir katmandır: yalnızca kendi girdilerinin
  değiştirdiği hücreleri tutar ve yalnızca onları hesaplar (KIRIK VADE'de valör değişince birkaç yüz hücre); geri kalan her
  şeyi - piyasayı, masanın girdilerini, sizin girdilerinizi - tablonun okuduğu yerden okur. Canlı veri kopyaya da tabloya
  geldiği gibi gelir; kopyanın hesabı tablonuza, başka kullanıcıya ya da herkesin hesabına sızmaz.
* **Başlangıç ve sonrası.** Kopya açılırken tablonuzda yazılı kişisel değerler kopyaya da yazılır; sonra ikisi ayrıdır.
  İkisinde de yazılmamış hücre (formülle ya da piyasadan dolan) tablonun değerini izler; tablonun bir girdisine yazdığınız
  formül (`=C60+7`) de kopya o hücreye kendi değerini yazmadıkça kopyada izlenir (hücrede ƒ görünür), formülün yerine elle
  yazdığınız değer ("Elle değer") kopyada da geçerlidir. Kopyada, formülü olan
  hücreye `Delete` tablonun değerine döndürür, olmayana boş değer yazar. Başlıktaki **Sıfırla** kopyanın kendi değerlerini
  siler (kopya yine tablonun değerlerini gösterir); sağ tık → "Kopyadaki değeri sil → tablonun değerine dön" tek hücreyi.
* **Kopyada olmayanlar.** Kopyaya **formül yazılamaz**: kopyanın girdileri değerdir, formül tablonun kendisinde kalır
  (yazılırsa nedeni söylenir). "Elle değer" kopyada çalışmaz; kopyanın hücresi bir formüle tıklanarak eklenemez, izlemeye
  ya da alarma eklenemez; kopyada **Kotasyon kopyala**, sağ tıkta **İşlem gir** ve "Bu satırın kotasyonu" da yoktur -
  bunlar tablonun kendisini okur.
* **Bloomberg isteği yok.** Kopya hiçbir zaman Bloomberg'e sormaz: Bloomberg'e soran hücreler kopyada tablonunkidir (sizin
  girdinizle, bir kez sorulur). Değeri bir Bloomberg isteğine giren girdi (valör, ticker) kopyada **salt okunurdur**: gri
  görünür, üzerine gelince nedeni yazar (kopya kendi isteğini açmaz - günlük veri limiti). Yukarıdaki tabloların hiçbirinde
  böyle bir girdi yoktur; Forward'daki "Tahvil carry / başabaş" bu yüzden kopyalanmaz (ISIN'i, fiyatı ve tarihleri istek
  açar). Toplantı takvimiyle kayan satırın ve tatil listesinin hücresi de kopyada salt okunur olurdu.
* **Ömrü.** Kopya kapatılana (başlığındaki **×**) kadar durur: sayfa değiştirmek, sayfayı yenilemek, dashboard'un yeniden
  başlaması onu silmez; hesabınızla sunucuda saklanır (`copies.<kullanıcı>`) ve yalnızca sizindir. Her tablo gibi kendi
  **+ Launchpad** menüsünden launchpad'e, yan panele ya da ayrı pencereye konur. Kapatmak kopyanın değerlerini siler
  (yazılmış değeri varsa önce sorulur) ve onu launchpad'lerinizden ve yan panelden kaldırır; dışa aktarılan launchpad'de
  kopyanın yerine tablonun kendisi gider.
* **Sınırlar.** Kullanıcı başına bir tablonun en fazla **5**, toplamda en fazla **20** geçici kopyası açık olabilir.
* **Tablonun kendisi.** Sayfanın "Girdilerimi sıfırla" düğmesi tablonuzu sıfırlar, kopyaların değerleri kalır.
  **Senaryolar kopyaları saklamaz**: senaryo yalnızca kişisel girdilerinizi (tablonun kendisini) kaydeder ve yükler.
  Kişisel hesap tabloları, girdi formülleri, izleme ve alarmlar da tablonun kendisini okur, kopyayı değil.
* **Hücre adresi.** Kopyanın değerleri, tablonun kendi girdileri gibi hücre adresiyle saklanır. Kopyalanan tabloların hiçbir
  girdisi toplantı takvimiyle, tahvil listesiyle ya da tatil kaydıyla kayan bir satırda değildir (testle doğrulanır);
  VİOP altın hesaplayıcısının kopyasında yazılan değerler hücresinde kalır: kontrat dönüşünde kopyanın sütunu bir
  sonraki kontratın olur (tablonun kendisinde yazılan fiyat ve forward kontratıyla gider; aşağıda, VİOP).

API: `GET /api/copies` (kopyalarınız), `POST /api/copies/open {view, panel}`, `/api/copies/inputs {copy, items,
lenient?}` (`/api/inputs` gibi), `/api/copies/reset {copy, refs?}`, `/api/copies/close {copy}`; `/api/cell?copy=<kimlik>`
hücreyi kopyadaki hâliyle söyler. Kopyanın sayfadaki ve launchpad öğesindeki adı `<tablo>.<kimlik>` (`B22.k1a2b3c4d`)
(`tto/copies.py`; motorda `LayerCalc`).

### Bugün: sabah ekranı

Menünün Masa grubunda, Masa'nın hemen altında (`#/bugun`; `tto/bugun.py`, sayfa `pages/bugun.js`): sabah bakılacak her şey
tek ekranda. Her blok işin yapıldığı yere götürür (başlığındaki düğme) ve yoksa bunu düz bir cümleyle söyler; bakılması
gereken bloğun başlığının yanındaki sayı yanar. **Açılış sayfası yapmak için:** sayfadaki *Açılış sayfası yap* düğmesi, ya
da sağ üstteki adınız → *Açılış sayfası…* → listenin başındaki **Bugün · sabah ekranı** (hesabınızla saklanır; dashboard'u
adres yazmadan açtığınızda gelir).

* **RET** - bugün yüklendi mi (üst şeritteki sarı noktanın kuralı: son yükleme bugünün tarihli değilse yüklenmemiştir), kim
  ve ne zaman; adil değerin "RET güncellemesi var: 1M, 2M" vadeleri. Düğmesi RET penceresini açar: güncelleme varsa adil
  değer sekmesinde, RET bugün yüklenmediyse elle girişte. Yayınlamak her zaman sizin "Kopyala ve yayınla"nızdır.
* **Trades · açık işlemler** - gördüğünüz açık işlemler: Kişisel (yalnız sizinkiler) ve Masa; başka bir trader'ın kişisel
  işlemi hiçbir zaman. Günlük ve toplam K/Z (TL) **son "MTM yenile"ye göre**: sayfa açılınca değerleme yapılmaz (MTM
  istenince); MTM'den sonra girilen işlem ve sekmede sonradan olan değişiklik söylenir. İşlemler hedef / stop seviyelerini
  taşıyorsa (`/api/trades`'te açık işlemin `levels`'ı: `target`, `stop`, `unit`, `to_target`, `to_stop`, `near`) hedefine ya
  da stopuna yaklaşanlar ayrıca listelenir (önce stop); taşımıyorsa bu konuda hiçbir şey söylenmez.
* **Quant · yeni AL / SAT** - quant gününden önceki iş gününün masa kapanışından (Trades'in kapanış saati, 17:30) beri giriş
  eşiğini geçen satırlar (sinyal kaydının o zamandan beri açılan, hâlâ açık girişleri) ve yönü kapanıştan beri dönen günlük
  satırlar ("YENİ", Trend'inki gibi): işlem masanın diliyle, yön (AL / SAT; faizde RECEIVE / PAY), büyüklük, giriş / hedef /
  stop (FX'te işlenen enstrümanın fiyatıyla; seviyesi modelin farkı olan satırda işlenen enstrümanın seviyesiyle - FRA / PPK
  patikası'nda FRA'nın faizi, yanında "patika farkı +6,9 / +0,1 / +7,9 bp"), ödül / risk ve beklenen K/Z. Beklenen kâra göre (satırın kendi büyüklüğünde
  TL) ilk 8, kalanı "ve N satır daha"; satıra tıklamak sinyalin sayfasını açar. Listeden çıkmış (|z| geri dönmüş) ama
  kayıtta açık satır soluk görünür.
* **DİBS · sinyali dönen kâğıtlar** - trading listesinin kâğıtlarında DİBS RV'nin **Sinyal**'i (OIS ASW) ve **Sinyal FX**'i,
  ve **sıfır kupon eğrisi**nin pahalı / ucuzu (quant'ın DİBS NS uyumu, DİBS RV'nin eşiğiyle - P2): önceki kapanışa göre
  dönenler ("PAHALI → UCUZ (+12,4 bp)"). DİBS RV sinyallerinin geçmişini tutmaz: masanın kapanışında, her iş günü bir kez,
  dashboard kaydeder (`bugun.dibs`, son 15 gün; masanın hesabıyla). İlk kayıttan önce **"dünle kıyas yok"** yazar ve bugün
  sinyal veren kâğıtları listeler. Sıfır kupon eğrisi quant'ın kendi kapanış geçmişiyle karşılaştırılır.
* **Girilmemiş işlemler** - masanın (Biz) bugün chat'te yaptığı, Günlük İşlemler'de olmayan işlemler (Chat ↔ Günlük
  İşlemler listesinin "Girilmedi"leri); düğmesi o listeyi açar.
* **Ajanda · takvim** - bugünün işleri (masanın ve kendinizinkiler), geciken deadline'lar, bugün ya da sıradaki PPK ve FOMC
  (toplantı takvimleri), bugün ve sonraki iş günü TRY / ABD tatili. Veri günleri Ajanda'daki işlerdir (dashboard'un kendi
  veri takvimi yoktur).

Sayfa piyasa değiştikçe en çok 20 saniyede bir, Ajanda ya da Trades değişince ve *Yenile* ile yeniden okunur. Tek istekle
(`GET /api/bugun`) servisin elindekinden toplanır: Bloomberg'e soru yok, değerleme, uydurma ya da yeniden hesap yok (hesap
iş parçacığına tek uğrayış: DİBS RV'nin birkaç hücresi, toplantı takvimleri, tatiller). Okunamayan blok nedenini yazar,
diğerleri durur.

### Trades: masanın ve kişinin kendi işlemleri

Menünün Masa grubunda, Günlük İşlemler ve Broker Chat'in altında (`tto/tradebook.py`, sayfa `pages/trades.js`). Masanın ya da
bir trader'ın **ayrıca izlemek istediği** işlemler: MTM'leri ve günlük / haftalık / toplam K/Z'ları burada hesaplanır.
Bu işlemler **masanın genel pozisyonuna karışmaz**: Günlük İşlemler'e, blotter'ın pozisyonlarına, DV01 riskine, RET
akış önerilerine ya da masanın başka hiçbir hesabına girmez - kendi tablolarındadırlar ve o hesaplar onları okumaz.

* **İki sekme.** **Masa**: masanın işlemleri - herkes görür ve herkes girebilir; değiştirmek, kapatmak ve silmek
  **girenin ya da bir yöneticinin** işidir. **Kişisel**: yalnızca **sahibi** görür ve değiştirir. Başka hiçbir kullanıcı -
  **yöneticiler de** - kişisel bir işleme hiçbir yoldan ulaşamaz: listede, işlem geçmişinde, değişiklik kaydında,
  "MTM yenile"de yoktur; doğrudan adresine yapılan her istek (görme, değiştirme, kapatma, silme) var olmayan bir işlemin
  cevabını (404) alır. Bunu sunucu uygular; kişisel işlemler hiçbir dışa aktarmaya ve launchpad'e girmez. Bir işlemin
  listesi (Masa / Kişisel) ve ürünü sonradan değişmez (silip yeniden girilir).
* **Ürünler ve alanlar.** İşlem tarihi, **valör (settle)** ve işlem fiyatı her işlemde zorunludur; işlem tarihi bugünden
  ileri, valör işlem tarihinden geri olamaz.
  * **TRY OIS** (TLREF) ve **SOFR** (USD): **Yapı** - *Outright* (RECEIVE / PAY, başlangıç, vade ya da bitiş tarihi, sabit
    oran %), *PPK / FOMC* (toplantı **tarihiyle** seçilir - takvimin satırıyla değil: takvim değişse, araya toplantı girse
    de işlem kendi toplantısına bağlı kalır), *Spread* (2 bacak) ve *Fly* (3 bacak; her bacağın kendi vadesi, yönü,
    nominali ya da DV01'i ve oranı - bunlar işlemin fiyatlarıdır; paketin seviyesi bacaklardan bp olarak hesaplanır,
    değerlemenin kuralıyla: uzun − kısa, fly'da 50/50 gövde − ½ her kanat (OIS sayfasının 2 × gövde − kanatlar'ının
    yarısı); **paket yönü** STEEPENER / FLATTENER, REC GÖVDE / PAY GÖVDE bacakların yönlerini doldurur, paketin kendi
    yönü uzun bacağın / gövdenin yönüdür), *FRA* (`3x6` valörden 3 ve 6 ay - ya da başlangıç / bitiş tarihi - ve FRA
    oranı). OIS'te valör varsayılan olarak başlangıç tarihidir. Vade bir tenor olarak yazılırsa (`2Y`) bitiş tarihini
    değerleme ürünün kuralıyla bulur (TRY: sonraki iş günü; SOFR: modified following, SIFMA). Yön RECEIVE / PAY
    yazılır; değerleme onu Günlük İşlemler'in koduyla saklar (`S` receive, `B` pay) - sayfa ikisini de okur. PPK
    işleminin toplantısı `mpc_date` olarak saklanır.
  * **DİBS**: ISIN (DİBS RV / Tüm Kâğıtlar listesinden; masanın listesinde olmayan ISIN yalnızca elle fiyatla alınır),
    ALIŞ / SATIŞ, nominal, **temiz fiyat ya da getiri**, valör.
  * **FX spot**: parite, ALIŞ / SATIŞ (ilk döviz), tutar **iki dövizden birinde** (Günlük İşlemler'deki gibi: ikinci
    dövizde yazılırsa ilk dövizdeki tutar kurdan çıkar), kur, valör.
  * **FX opsiyon**: parite, CALL / PUT, ALIŞ / SATIŞ, strike, vade (expiry; `1A` gibi bir tenor yazılırsa vade ve
    teslim FX sayfalarının kuralıyla: spot + tenor) ve teslim (boşsa vadenin spot'u), nominal (ilk dövizde), prim tutarı
    ve dövizi (işlemin fiyatı), prim valörü (= işlemin valörü).
  * Her işlemde isteğe bağlı: not, **elle fiyat** (dashboard enstrümanı fiyatlayamazsa kullanılır), karşı taraf / defter.
  * Dashboard'un kısayolları çalışır: tutarda `5m`, `250k`; tarihte `2Y`, `1A`, `ay sonu`, `+1` (ürünün tatil
    takvimiyle; vade başlangıçtan, başlangıç valörden, valör işlem tarihinden sayılır) - kutunun altında "2Y → 20.11.2028".
* **Varsayılanlar.** Form açılınca ve ürün, parite, işlem tarihi ya da vade (expiry) değişince varsayılanı olan alanlar
  dolar: işlem tarihi bugün; valör ve başlangıç ürünün spot'u (masanın kuralları ve tatil listeleri); opsiyonun teslimi
  vadenin spot'u (paritenin spot gecikmesi); dövizler; prim dövizi ikinci döviz; PPK / FOMC toplantıları; bacak
  ağırlıkları. Varsayılanlar değerleme modülünden gelir (`tradevalue.defaults`: kurallar tek yerde, `GET
  /api/trades/defaults`). **Elle yazılan alanın üstüne hiçbir varsayılan yazılmaz**; boşaltılan alan yeniden dolar.
* **DV01 ile büyüklük.** OIS / SOFR yapılarında (her bacakta) ve DİBS'te nominalin yanında DV01 kutusu vardır (varsayılan
  **$ / bp**, TL seçilebilir). DV01 yazınca nominal değerleme modülünden hesaplanır ve **masanın lotuna - en yakın 5
  milyona - yuvarlanır** (en az bir lot); yanında o nominalin gerçekte verdiği DV01 yazar ("DV01 ≈ 1.014 $"). Sonra **nominal elle
  yazılırsa nominal kalır**: DV01 kutusu yalnızca bilgi olarak o nominalin DV01'ini gösterir, başka bir alanın değişmesi
  elle yazılan nominali değiştirmez. Spread / fly'da paket DV01'i bacaklara ağırlıklarıyla dağılır (spread 1:1, fly
  50/50). Kayıtta yazılan DV01, nominal ve hangisinin yazıldığı (`sized_by`) durur.
* **Formun önizlemesi** (`POST /api/trades/check`): sunucu formu kaydederken okuyacağı gibi okur - işlem masanın diliyle
  ("RECEIVE 2Y TRY OIS 100m @ %38,50", "2s5s steepener TRY OIS -35,0 bp", "ALIŞ USDTRY 10m USD @ 42,1500") ya da her
  alanın altında eksik / hatalı olanın nedeni; hiçbir şey kaydedilmez.
* **FX opsiyonda primin vol'ü** (masa, 24.11.2026: tek yönlü fiyatlama araçları listesine cevabı "1-2-3-4-5-6-7-8-11-11-13";
  11. madde: Trades'te bir bayinin primini ekrandaki smile'la karşılaştırmak için primden vol). Prim tutarı yazılınca
  önizlemenin altında: **"Primin vol'ü 21,35 · smile (SVI, strike'ta) 20,10 · fark +1,25 vol · smile'la prim 142.350 TRY"**.
  Primin vol'ü, opsiyonu bugünkü piyasada tam primine eşitleyen Garman-Kohlhagen vol'üdür - değerlemenin kendi girdileriyle
  (spot, teslimin forward'ı, iskontolar, vadeye gün / 365; prim kendi dövizinde bugünkü kurla), yani MTM'in 0 olduğu vol;
  Brent ile çözülür (Swaption sayfasının Black vol'ü gibi). Yanında değerlemenin kullandığı vol: strike'taki smile vol'ü
  (USDTRY / EURUSD SVI, G10 Vanna-Volga) ya da elle vol yazıldıysa o; ve o vol'ün verdiği prim, prim dövizinde. Piyasa
  formun piyasasıdır (Bootstrap, en çok 30 sn eski). **Hiçbir vol prime ulaşmıyorsa** nedeni yazar: prim, içsel değerin
  bugünkü karşılığının altında ya da ona eşit (vol 0'da bile opsiyon daha değerli), opsiyonun alabileceği en yüksek değerin
  (call'da spot · DF_baz, put'ta strike · DF_kote) üstünde ya da ona eşit, prim sıfır, vadesi geçmiş; smile yoksa ("vol kotası
  yok") primin vol'ü yine yazar. İşlem gününde bayinin primindeki vol'dür; sonra spot ve zaman değiştikçe değişir.
* **Kapatma.** "Kapat": kapanış tarihi (varsayılan bugün) ve kapanış fiyatı. İşlem **Kapanan işlemler** listesine gider,
  gerçekleşen K/Z'ıyla (o fiyattan değeri; carry + fiyat etkisi). "Geri aç" kapanışı geri alır.
* **Hedef ve stop.** Her işleme (masa ya da kişisel, her ürün) isteğe bağlı bir **hedef** ve bir **stop** yazılır -
  işlemin kendi kotasıyla, formdaki fiyat kutusu neyse o: OIS / SOFR outright, PPK, FRA'da **oran (%)**; spread / fly'da
  **paketin seviyesi (bp)**; DİBS'te işlem **getiriyle** girildiyse **getiri (%)** (işlemin kendi getiri kuralıyla:
  bileşik ya da basit), **temiz fiyatla** girildiyse **temiz fiyat**; FX spot'ta **kur**; FX opsiyonda **prim tutarı**
  (prim dövizinde: opsiyonun şimdi getireceği prim - kapanış fiyatı da prim tutarıdır, hedefte / stopta kapanışla aynı
  birim). Hedef işlemin kazandığı tarafta olmalı (receive: hedef < stop; alınan FX / opsiyon, fiyatla alınan tahvil:
  hedef > stop; getiriyle alınan tahvil: hedef < stop) - değilse kutunun altında söyler. Sonradan değiştirilir; kutu
  boşaltılınca kalkar; formu göndermeyen bir istek (betik) var olanı korur. Hedef / stop işlemin değerinin parçası
  değildir: kapanış kayıtları geçerli kalır.
  * **İzleme alarmı kendiliğinden.** Kaydedince her seviye bir İzleme alarmı olur: **"hedefe geldi"** / **"stopa
    geldi"** - MTM'in o işlem için okuduğu değerin (oran, paket seviyesi, getiri / fiyat, kur, prim) seviyeye gelmesi.
    O değer sunucuda izleme turunda **10 saniyede bir** piyasanın o anki görüntüsüyle değerlenir (dashboard'un değerleri
    canlıysa canlı; değilse "MTM yenile"de ve gün sonu kaydında güncellenir). Kişisel işlemin alarmları yalnız
    **sahibinin** (kendi listesi, kendi uyarısı); masa işlemininki **masanın**: Masa alarmları'nda herkese görünür ve
    herkese çalar ("Gördüm, ben bakıyorum"lu), kuranı işlemi giren, masa alarm kaydında kuruldu / kaldırıldı satırıyla.
    Seviye değişince alarm yeni seviyeyle yeniden kurulur, boşaltılınca kalkar; işlem kapanınca ya da silinince
    alarmları kalkar, geri açılınca geri gelir. Açılışta sunucu bütün işlemlerin alarmlarını bir kez eşler: yeniden
    başlatmadan sonra **hiçbir alarm iki kez olmaz**, silinmiş işlemin alarmı kalmaz. Bu alarmlar İzleme'den silinmez
    (✕ yerine **Trades** düğmesi): işlemindir, seviyesi Trades'te değişir.
  * **Satırda uzaklık.** Açık işlemler listesinde **Hedef / stop** sütunu: her seviye ve ona **kalan** - faizde
    (oran, paket seviyesi, getiri) **bp**, FX spot'ta **pip** (yen ve altında 0,01, diğerlerinde 0,0001), opsiyonda primin
    **%**'si, fiyatla girilmiş tahvilde **puan**; gelince "geldi". Seviyeden **hedef–stop aralığının dörtte biri** kadar
    yakınsa (tek seviye varsa: işlem fiyatından o seviyeye uzaklığın dörtte biri) ya da gelmişse satır işaretlenir
    (hedef yeşil, stop kırmızı). Uzaklık sayfa açıkken en çok 10 saniyede bir yenilenir (MTM değerleri yine yalnız "MTM
    yenile"yle). Kapanan işlemde kapanış fiyatının yanında **hedefte / stopta / diğer**.
  * **Sözleşme** (sabah sayfası okur): `GET /api/trades` ve "MTM yenile"nin cevabı her açık işlem için `levels: {target,
    stop, unit, to_target, to_stop, near}` verir (`now`, `at` da): `to_*` satırın gösterdiği birimde (`bp`, `pip`, `%`,
    `puan`), pozitif = daha gidecek yol (≤ 0: geldi); `near` "target" / "stop" ya da null. Seviyesi olmayan işlemde yok.
* **Sinyalden işleme ("İşleme al").** Quant listesindeki (Sinyaller, ailelerin sayfaları, satırın kartı) her AL / SAT
  satırında, Trades'in girebildiği bir enstrümansa **İşleme al** düğmesi: Trades formu satırdan **dolu açılır** - ürün,
  yapı ve bacaklar, yön (OIS'te receive / pay), büyüklük (faizde satırın DV01'i, formun DV01'i nominale çevirdiği gibi
  5 mn lotuna; FX'te satırın büyüklüğü kadar 1 mn baz döviz), işlem fiyatı = satırın **şimdiki girişi** (spread / fly'da
  bacaklar eğrinin şimdiki oranlarıyla, uzun bacak / gövde paket tam girişte olacak şekilde), hedef ve stop = satırın
  (FX'te kurla). Liste **Kişisel**dir, formdan Masa seçilebilir; **kaydedene kadar hiçbir şey kaydolmaz**. İşlem nereden
  geldiğini saklar (`source: {kind: "quant", family, line_id, at, entry, target, stop}`; düzenleme değiştirmez) ve
  satırında "Quant · aile · enstrüman" yazar. Hangi satırlar: TRY OIS outright, 1:1 spread, 50/50 fly, FRA (evrenin FRA'ları
  ve **FRA / PPK patikası** satırı: FRA'nın faiziyle - fiyatı FRA'nın şimdiki faizi, hedef / stop bugünkü patikayla FRA
  faizleri, fark değil; 24.11.2026), PPK dönemi,
  tek başına DİBS (getiriyle), FX spot (G10 ve Opsiyon → spot'un spot satırları - USDTRY / EURTRY dahil). Düğmesiz
  ("—", nedeni ipucunda; kartta düğme soluk): vol işlemleri, VİOP, Offshore (forward, swap puanı, offshore eğrisi:
  offshore limiti), FX forward, korelasyon, PCA / hedge ağırlıklı paketler, DİBS switch ya da OIS hedge'li kâğıt.
* **Quant'tan.** Sayfanın **Quant'tan** düğmesi listeleri sinyalden alınmış işlemlere süzer ve üstte aile aile bir tablo
  açar: masanın işlemleri ve kullanıcının kişisel işlemleri birlikte - işlem sayısı (masa / kişisel), açık, kapanan,
  **toplam ve ortalama K/Z (TL)** (açığın şimdiki değerle işlem tarihinden bu yana, kapananın gerçekleşeni), kapananların
  **hedefte / stopta / diğer** kapanması (kapanış fiyatı seviyede, ötesinde ya da aralığın %5'i kadar yakınında) ve
  isabet (hedefte kapanan payı): hangi modelin masaya para kazandırdığı.
* **MTM sürekli canlı değildir.** **MTM yenile** sekmedeki işlemleri o an değerler (değerleme modülünün piyasası bir kez,
  hesaplama iş parçacığında - motorun zaten bildiğini okur, Bloomberg'e hiçbir istek gitmez) ve "son yenileme: 14:05
  (kim)" yazar. Sayfayı açmak, işlem girmek ya da listeyi yenilemek hiçbir şey değerlemez (bir swap'ın **Kuponlar**
  penceresi yalnız o işlemi, açılınca değerler). Masa sekmesinin son yenilemesi
  herkesindir; kişisel sekmeninki sahibinin. Yenilemeden sonra işlem değişirse "MTM yenile" diye uyarır. Değerlenemeyen
  işlemde değer yerine **nedeni** yazar.
* **Kapanış kaydı.** Her iş günü masanın kapanışında (**İzleme · Alarmlar → Masa ayarları → Trades kapanış kaydı**,
  varsayılan **17:30**, yedekleme saatiyle aynı; ayarı yöneticiler değiştirir) sunucu bütün açık işlemlerin - masanın ve
  her trader'ın kendi işlemleri - değerini saklar: işlemin dövizinde, TL ve USD MTM; 1 günlük carry ve FX spot / DİBS'te
  onun fonlama kısmı (`funding_1d`); gerçekleşen nakit
  (`accrued`: swap'ın biten dönemlerinin kuponu); bacakların değerleri ve her bacağın kendi gerçekleşen kuponu. Dashboard o
  saatte kapalıysa kayıt **bir sonraki açılışta** (piyasa verisi için 3
  dakika sonra) **o günün tarihiyle** alınır. Bir gün asla iki kez kaydedilmez. Hafta sonu ve TRY tatillerinde kayıt yok.
* **K/Z dönemleri, her biri carry + fiyat etkisi.** Bir andaki değer = MTM + o ana kadar gerçekleşen nakit (swap'ta
  **gerçekleşen kuponlar + kalan swap'ın değeri**; bacakta da öyle). Ödeme gününde dönemin kuponu MTM'den gerçekleşene
  geçer: **toplam, günlük ve haftalık K/Z sıçramaz** (o günün farkı yalnızca bir günlük faiz). Bacaklarının kuponunu henüz
  taşımayan eski bir kapanış kaydı, bacağın o güne kadar biten dönemlerinin kuponuyla okunur (taşıma yok).
  * **Günlük K/Z**: şimdi − son kapanış (kapanıştan sonra kapanan işlem gerçekleşen değeriyle girer).
  * **Haftalık**: önceki haftanın son kapanışına göre.
  * **Toplam**: işlem tarihinden bu yana. Her işlemin ilk değeri 0'dır: değerlemenin MTM'i işlemin değerinin maliyetine
    karşı farkıdır (doğrusal işlem işlem fiyatından yapılmıştır; opsiyonun MTM'inden ödenen / alınan prim düşülmüştür).
  * **Carry**: dönemdeki her kapanışın carry'si - değerlemenin 1 günlük carry'si bir sonraki iş gününe kadardır
    (`carry_days`: cumadan pazartese 3 gün; TLREF cumanın fixingini hafta sonu boyunca biriktirir) - gün başına yayılıp bir
    sonraki kapanışa kadar sayılır; son kapanıştan bu yana oransal kısım eklenir. **Fiyat etkisi** = toplam − carry.
  * **FX spot ve DİBS'te K/Z = fiyat hareketi + carry** (masa, 19.11.2026: "Spot tradelerindeki carryden de
    bahsediyorum" - spot ve DİBS K/Z'ına carry'nin girmesi seçildi). Carry'nin değerde olmayan kısmı - FX spot'ta
    pozisyonu her gün bir sonraki spot valörüne iki paranın O/N faiziyle taşımak (carry'nin tamamı), DİBS'te kirli fiyatın
    TLREF ile fonlanması - **fonlama**dır: nakit olarak ödenir / alınır, MTM'de yoktur. Her dönemin K/Z'ına carry gibi
    kapanışlardan sayılarak eklenir: K/Z = değer değişimi + fonlama, `c` carry, `f` **yalnız fiyat hareketi** (DİBS'te
    kâğıdın kendi tahakkuku kirli fiyattadır: getiri yerindeyse `f` sıfır). İşlem tarihinden bu yana toplamı listenin
    **Fonlama** sütunudur: MTM + Kupon + Fonlama = toplam K/Z. Fonlamadan önceki kapanış kayıtlarında FX spot'un carry'si
    olduğu gibi fonlamadır; DİBS'in o günleri kendisinden sonraki ilk bilinen fonlamayla sayılır (hiç yoksa - 19.11.2026'dan
    önce kapanmış DİBS - fonlamasız, eskisi gibi). Kapanmış işlemin saklı gerçekleşen K/Z'ı hangi kuralla hesaplandığını
    taşır (`realized.rule`: 2); eski kuralla saklanmış FX spot / DİBS'inki liste açılınca yeniden hesaplanır, ilk **MTM
    yenile** onu yeni kuralla saklar.
  * İşlem son kapanıştan sonra girildiyse dönem işlemin ilk değerinden başlar. Kapanıştan sonra değiştirilen ya da
    kapanış kaydı olmayan (geriye tarihli girilen) işlemin o dönemi "—" olur ve nedeni hücrenin ipucundadır.
* **Liste.** Ürün, işlem (masanın diliyle), işlem tarihi ve fiyatı, güncel fiyat / oran, hedef / stop ve kalan, MTM,
  **Biriken**, **Kupon**, **Fonlama**, **Carry (1g)**, günlük / haftalık / toplam
  K/Z (her biri altında `c` carry · `f` fiyat etkisi), opsiyonda greekler. FX opsiyonun **Güncel** hücresinde vol'ün
  (smile ya da elle) altında **"prim vol"**: "MTM yenile"nin piyasasında primin vol'ü (MTM'in 0 olduğu vol) ve kullanılan
  vol'e farkı ("prim vol 21,35 (+1,25)"; ipucunda açıklaması; ulaşılamıyorsa "prim vol yok" ve nedeni) - günlük
  kapanışlar saklamaz. **Gösterim**: işlemin dövizi, TL ya da USD.
  Swap'ta **MTM kalan dönemlerin değeridir**, **Kupon** biten dönemlerin net kuponu (alınan +, ödenen −; DİBS'te
  valörden beri alınan kuponlar): MTM + Kupon = toplam K/Z. İpucunda kaç dönemin bittiği, sonuncusu (ödendi / ödenecek)
  ve sıradaki ödeme günü.
  * **Biriken** (TRY OIS / SOFR varken): işleyen kupon döneminin bugüne kadarki neti - sabit faizin bugüne kadarki tutarı
    − fixinglerin bileşiği (alınan +, ödenen −). MTM'in içindedir (Kuponlar penceresinin "işliyor" satırı); dönem bitince
    Kupon'a geçer.
  * **Fonlama** (FX spot / DİBS varken): işlem tarihinden bu yana fonlama (yukarıda): MTM + Kupon + Fonlama = toplam K/Z.
  * **Carry (1g)** (her zaman): piyasa aynı kalırsa bir sonraki iş gününün carry'si (cuma 3 takvim günü). İpucunda
    parçaları işlemin dövizinde - swap'ta tahakkuk ve roll-down, DİBS'te kâğıt ve fonlama (TLREF), FX spot'ta fonlama
    (iki paranın O/N faizi), opsiyonda theta.
  Spread, fly ve FRA tek satırdır (paket seviyesiyle); ▸ ile **bacaklar** açılır: her bacağın MTM'i, birikeni, kuponu, carry'si ve K/Z'ı.
  FRA tek enstrüman olarak değerlenir, bacakları "hangi bacaktan ne kadar geldiği"dir; bacakların açıklamadığı kısım
  "kalan" satırındadır. **Bacaklar ayrı satır** seçilince bacaklar kendi satırlarında listelenir (vadelere göre outright
  pozisyon). Altta ürün başına ve toplam **TL ve USD** (MTM, günlük, haftalık, toplam, gerçekleşen); değerlenemeyen
  işlem toplama girmez ve sayısı söylenir.
* **DV01 · vade** (masa, 19.11.2026: "Trades kısmına da Günlük İşlemler kısmındaki gibi DV01 tablosu eklemek
  istiyorum"): sekmenin açık işlemleri, son **MTM yenile**'den, Günlük İşlemler'in **"OIS · vade özeti"** (O22:W39)
  gibi - Net DV01 ($, payer +: ödenen − alınan), vade, **Pay** ve **Receive** için tutar, faiz (tutarla ağırlıklı) ve
  DV01 ($, TRY faizi +1 bp), **Net faiz** ((R·S − U·V) / (S − V), iki taraf da varken - sayfanın W sütunu); en altta
  toplam (faizsiz). Vadeler ON, 1W, 2W, 1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y, 3Y, 4Y, 5Y (hep) ve 6Y–10Y (dolu olanlar).
  * Swap bitişinde: bugün spot'tan vadeyle girilen kendi vadesinde (15M: ½ 1Y + ½ 18M, masanın kovaları); tarihle
    girilen ya da başlamış olan, bitiş tarihinin iki yanındaki vadeye gün oranında (vadelerin bitişi swap'ın kuralıyla
    iş gününe kaydırılır).
  * İleri başlangıçlı (FRA, PPK dönemi, ileri başlayan bacak): Günlük İşlemler'in PPK işlemi gibi - spot'tan bitişine
    swap işlemin yönünde, başlangıcına swap ters yönde, DV01'leri toplamı işlemin DV01'i olan tek nominalle; başlangıca
    olanın faizi eğrinin, bitişe olanınki ikisini birlikte işlemin faizi yapan. Spread / fly bacak bacak.
  * **SOFR** ayrı tablo (USD faizi, tutar $); **tahvil** yalnız üstteki çubukta: DİBS RV'nin DV01'i vadesinde, aldığınız
    kâğıt − (receiver gibi). Çubuk: **Toplam** (TRY OIS net + tahvil), **OIS (net)**, **Tahvil**, **SOFR** (TRY
    toplamına girmez); değeri olmayan swap / tahvil sayılır, toplama girmez. FX işlemleri DV01 tablosunda yok.
* **Kuponlar** (TRY OIS ve SOFR; açık işlemde Kupon hücresine - değerlenmeden önce "takvim"e - tıklayınca, kapanmış
  işlemde satırın **Kuponlar** düğmesi). Pencere sunucunun o an yaptığı değerlemedir (değerleme modülünün piyasası, Bloomberg
  isteği yok; kapanmış işlem kapanış gününe göre), **bacak bacak** bir tablo: işlemin nakit akışı olan her swap -
  outright, PPK dönemi ve FRA'da işlemin kendisi (FRA tek ileri başlangıçlı swap'tır), spread / fly'da her bacak. Başlıkta
  bacak, nominal, sabit oran, değişken endeks ve kural (TRY: ACT/365, 3 aya kadar tek ödeme, sonra vadeden geriye 3 ayda
  bir - ilk dönem kısa -, ödeme dönem sonunda; SOFR: ACT/360, 1 yıla kadar tek ödeme, sonra yıllık - bitişten geriye, ilk dönem kısa -,
  ödeme dönem sonundan 2 SIFMA iş günü sonra). Her dönem: başlangıç – bitiş, gün, **ödeme günü**, **sabit ödeme**,
  **değişken ödeme** (dönemin fixinglerinin bileşiği, tarihçeden) ve bileşik oranı, **net** ve durumu: **ödendi**,
  **ödenecek** (dönem bitti, ödeme günü gelmedi), **işliyor** (bugüne kadar), **bekliyor** (yalnız sabit tutar; kapanmış
  swap'ın kapanıştan sonraki dönemleri yalnız sabit faiz farkı, tutarı belli). Tahmini fixing'li dönemin değişkeninde `*`,
  ipucunda günler; altta **gerçekleşen** (ödenen + ödenecek) ve hangi günlerin tahmini olduğu. Kişisel işlemin
  kuponlarına yalnız sahibi ulaşır (diğer her istek 404).
* **Kayıt.** Her değişiklik (girme, değiştirme - alan alan eskisi → yenisi -, kapatma, geri açma, silme) kim ve ne
  zamanla saklanır: satırdaki **Geçmiş** ve sekmenin **Değişiklik kaydı**. Silinen işlemin kaydı kalır.
* **Canlı.** Bir işlem girilince / değişince açık Trades sayfaları listeyi kendiliğinden yeniden ister (canlı akışın
  sayacı; yeni bir hesaplama turu başlatmaz). Akış yalnızca masanın ve kullanıcının kendi işlemlerinin sayacını taşır.
* **Değerleme** `tto/tradevalue.py`'dedir (`check`, `market`, `value`, `defaults`, `notional_for_dv01`); bu dalda yerinde
  bir taslak durur ve her işlem için "değerleme henüz yok" der - gerçek modül ayrı daldan gelir.
* **Saklama.** Kendi tablolarında: `tradebook` (işlem: ürün alanları JSON, kapsam / sahip / durum sütunları),
  `tradebook_close_days` ve `tradebook_closes` (kapanış kayıtları: gün başına bir satır ve işlem başına değerler),
  `tradebook_log` (değişiklik kaydı). Var olan bir veritabanı açılışta bu tabloları kendisi ekler; eski kayıtlara
  dokunulmaz. API: `GET /api/trades?scope=desk|personal`, `POST /api/trades`, `POST` / `DELETE /api/trades/<id>`,
  `POST /api/trades/<id>/close` (`{close_date, close_price}`), `…/reopen`, `GET /api/trades/<id>/log`,
  `GET /api/trades/<id>/coupons` (swap'ın kuponları: `legs[].periods[]` - `start`, `end`, `pay`, `days`, `fixed`,
  `float`, `float_rate`, `net`, `state`: paid / due / running / future, `estimated` -, `realised`, `notes`),
  `GET /api/trades/log?scope=`, `POST /api/trades/mtm` (`{scope}`), `POST /api/trades/check`,
  `GET /api/trades/defaults?product=&pair=&trade_date=&expiry=`, `GET` / `POST /api/trades/dv01`,
  `GET /api/trades/from-quant?id=&scope=` (bir quant satırının dolu formu, hiçbir şey kaydedilmez), `GET /api/trades/quant`
  (Quant'tan tablosu). Hedef / stop ve kaynak işlemin JSON'undadır (yeni sütun yok); alarmlar İzleme'nin listesinde
  (`watch.alarms`), işlemin kimliğiyle (`tb<id>-target` / `tb<id>-stop`).

#### Trades · değerleme ve carry

`tto/tradevalue.py`: Trades sayfasındaki her işlemin **şimdiki değeri** (MTM), **bir günde ne kazandırdığı** (carry),
başladığından beri **ödediği / aldığı nakit** (accrued), **fiyatı masanın okuduğu gibi**, opsiyonun greek'leri ve
swap'ın **kuponları**. Yalnız istenince hesaplanır: "MTM yenile", gün sonu kapanışı ve bir swap'ın Kuponlar penceresi.
Sayfa yalnız şunları çağırır: `PRODUCTS` (`ois`, `sofr`, `dibs`, `fxspot`, `fxopt`), `check()`, `defaults()`, `market()`,
`value()`, `coupons()`, `notional_for_dv01()`.

* **Piyasa** (`market(svc)`): her yenilemede bir kez, motor iş parçacığında, **masanın ortak hesabından** (kimsenin
  kişisel girdisi değil) ve tarihçeden okunur; **hiçbir Bloomberg isteği yapmaz** (hücreler kitapların zaten istediği,
  gerisi tarihçenin ve quant paketinin son değerleri - sahte terminalle test edilir). İçinde: TRY OIS eğrisi
  (`BOOT_GUN` / `BOOT_LNDF`, Motor'un bootstrap'ı; spot `OIS_MAIN!B2`, TLREF `J2`), OIS kotaları (`OIS_MAIN!A9:B26`),
  SOFR eğrisi (`SOFR_FOMC!K48:M68`, kitabın "Zero lineer" ara değeri, T+2 spot `B5`, SOFR `B6`, SIFMA tatilleri
  `BO4:BO70`), TLREF fixing'leri (tarihçenin `BISTTREF Index` serisi; kayıtlı veri modunda dosyayla gelen kapanışlar)
  ve SOFR fixing'leri (tarihçenin `SOFRRATE Index` serisi - bkz. Gün Sonu Matrisi bölümü; kayıtlı veri modunda yok),
  TRY / USD / EUR tatil listeleri, PPK ve FOMC takvimleri, Forward sayfasının USDTRY /
  EURTRY spot'u (`F2` / `G2`), USD ve EUR OIS'i (`U:X`, `AA:AD`), offshore TRY eğrisi (`OFF_GUN` / `OFF_LNDF`) ve O/N
  faizleri (ICAP O/N, SOFR, €STR), quant paketinin G10 spot'ları, forward puanları ve vol kotaları (canlı, yoksa son
  kapanış), DİBS RV ve Tüm Kâğıtlar fiyatları.
* **Enstrüman adıyla tanınır**, satırıyla değil: swap tarihleriyle, PPK dönemi toplantının tarihiyle, tahvil ISIN'iyle,
  FX paritesiyle - takvim düzenlemesi, satır kayması, listeye yeni kâğıt bir şeyi kaydırmaz.
* **Yön** blotter'ın kodlarıyla yazılır: OIS / SOFR'da "S" sabit faizi alır (receive), "B" öder (pay); tahvilde ve FX'te
  "B" alış, "S" satış. `check()` sözü de ("receive" / "pay", "al" / "sat" …) alıp koda çevirir; `defaults()` kodları
  sözleriyle verir, `value()`'nun sonucu ve bacakları yönü sözle de yazar (`side_text`).
* **MTM + accrued (+ fonlama) = toplam değer değişimi.** MTM, kalan nakit akışlarının bugünkü değeri ile maliyetin farkı (tahvilde
  ve FX'te fiyat farkı); accrued, işlemin başından beri ödenmiş / alınmış ve MTM'de artık olmayan nakit (swap'ın
  biten dönemleri - **gerçekleşen kuponlar** -, tahvilin kuponları); `accrued_try` / `accrued_usd` TL ve USD'si. Bir
  dönemin K/Z'si ikisinin birlikte değişimidir (FX spot ve DİBS'te üstüne o dönemin fonlaması): ödeme gününde kupon MTM'den accrued'a geçer, değer sıçramaz. Paketin her
  bacağı da kendi `accrued`'unu ve biten kuponlarını (`coupon_flows`: [bitiş, net]) taşır.
* **Carry** (`carry_1d`): piyasa yerinde kalırken bir günün kazandırdığı - ertesi iş gününe kadar (`inputs.carry_days`
  takvim günü: cuma → pazartesi 3, TLREF'in cuma fixing'i gibi). Her sonuç işlemin parasında, TL'de ve USD'de
  (bugünkü kurlarla); `inputs` hesaba giren her şeyi yazar. `carry_parts` parçaları (`[ad, tutar]`, işlemin dövizinde:
  swap'ta tahakkuk / roll-down, DİBS'te kâğıt / fonlama, FX spot'ta fonlama, opsiyonda theta), `carry_note` giren
  faizler (FX'te O/N faizleri, DİBS'te TLREF).
* **Fonlama** (`funding_1d`, `_try`, `_usd`): carry'nin işlemin değerinde olmayan kısmı - pozisyonu bir gün daha tutmanın
  yanında ödenen / alınan nakit: FX spot'ta carry'nin tamamı (bir sonraki spot valörüne iki paranın O/N faiziyle
  taşıma), DİBS'te kirli fiyatın TLREF ile fonlanması. Swap'ta ve opsiyonda 0 (değerleri carry'nin hepsini taşır),
  kapanmış işlemde `None` (taşınacak bir şey yok). Trades'in K/Z'ı FX spot ve DİBS'te bunu gün gün ekler (masa,
  19.11.2026).
* **Biriken** (`running`, `_try`, `_usd`; swap'ta): işleyen dönemin bugüne kadarki neti - sabit faizin bugüne kadarki
  tutarı − değişkenin bugüne kadarki bileşiği, işaretli (alınan +); dönem bitene kadar MTM'in içindedir, bitince
  `accrued`'a geçer. Paket bacaklarının toplamı; her bacak kendisininkini taşır.
* **Risk** (`risk`; swap'ta ve tahvilde): DV01'i Trades'in DV01 tablosunun vadelerinde (`RISK_TENORS`) -
  `[{kind, tenor, dir, nominal, rate, dv01, dv01_try, dv01_usd, curve}]`: bugün spot'tan vadeyle girilen swap kendi
  vadesinde (`risk_months`, `blotter.bucket_split`), tarihle girilen ya da başlamış olan bitişinde iki yana gün
  oranında (`risk_split`, `blotter.split_weights`; vadelerin bitişi `tenor_end` ile kaydırılır), ileri başlangıçlı spot'tan
  bitişine + ters yönde başlangıcına (tek nominal, `blotter.mpc_summary_rows` gibi), tahvil vadesinde (alış "S").
  Kapanmış işlemde ve FX'te yok. Sayfanın tablosunu `tradebook.dv01_table` toplar (MTM yenile'de, sekme başına).

Ürün ürün:

* **OIS / SOFR** - `structure`: *outright*, *mpc* (toplantı tarihli dönem), *spread*, *fly*, *fra*. **Kural
  çalışma kitaplarınınki** (kitabın kotasındaki swap her vadede ~1e-8 TL ile sıfır değer alır, test edilir): TRY
  ACT/365, 3A'ya kadar tek ödeme, sonra **vadeden geriye** üç ayda bir kupon, ilk dönem kısa (masa, 19.11.2026: "İlk olan kısa olan";
  tarihle girilende MASA'nın kırık vade bloğu gibi `WORKDAY(EDATE(bitiş, −3k) − 1, 1, TRY)`, BL193; vadeyle girilende
  başlangıçtan vadenin ızgarası `EDATE(başlangıç, m − 3k)` - tam çeyreklerde Motor!B88'in tarihleri, 13A'da ilk dönem 1A); USD ACT/360, 1Y'ye kadar tek ödeme, sonra yıllık kupon, ilk dönem kısa (vadeyle girilende kitabın
  `EDATE(spot, m − 12k)`'si, `SOFR_FOMC!AV64`; tarihle girilende bitişten geriye), SIFMA listesiyle modified
  following. **Ödeme günü**: TRY'de dönem sonu (kitapların kuralı: Motor'un bootstrap'ı kuponu dönem sonunda
  iskontolar, MASA'nın kırık vade bloğunun "Ödeme"si dönem sonudur; hiçbir kitapta ödeme gecikmesi yok); USD'de dönem
  sonundan **2 SIFMA iş günü** sonra (SOFR OIS piyasasının gecikmesi; `SOFR_FOMC`'un bootstrap'ı dönem sonunda
  iskontolar, değerleme de öyle - gecikme ödemenin tarihidir, değeri kaydırmaz). *MTM* = sabit bacak − değişken bacak
  (receive; pay eksi), kalan akışlar eğriden bugüne iskontolu; değişken bacağın fixlenmiş günleri **tarihçenin
  fixing'leriyle** (TLREF `BISTTREF Index`, SOFR `SOFRRATE Index`), kalanı eğriden. Her fixing endeksin bir sonraki iş
  gününe kadar işler: tarihçenin içinde fixing'i olmayan hafta içi gün endeksin tatilidir (kitapların listeleri yalnız
  gelecek tatilleri tutar - SIFMA listesi 2026'dan başlar), bir önceki günün fixing'i onu da kapsar (gün sayısıyla); o
  günlerin %8'inden fazlası boşsa eksik veri sayılır. Tarihçede olmayan geçmiş günler **tahminidir ve adlarıyla
  söylenir** (`inputs.notes`): tarihçenin ilk fixing'inden önceki günler bugünkü fixing'le ("… fixingleri tarihçede
  yok: gerçekleşen N gün bugünkü … ile - 02.12.25–27.02.26"), içindeki eksik gün bir öncekiyle, son fixing'inden sonraki
  gün son fixing'le - SOFR bir günün fixing'ini **ertesi iş günü New York 08:00'de** (İstanbul 16:00 / yazın 15:00)
  yayımlar: o saate kadar dünün SOFR'u yoktur ("SOFR 17.11.26 fixing'i henüz yayımlanmadı …: son fixing (16.11.26 %3,95)
  ile"). *Accrued* = biten dönemlerin net ödemesi (gerçekleşen: ödendi ya da ödeme günü bekleniyor). **Kuponlar**
  (`inputs.coupons`, `coupons()`): işlemin nakit akışı olan her swap için (işlemin kendisi; spread / fly'da her bacak)
  kural ve her dönem - başlangıç, bitiş, ödeme günü, gün, sabit ve değişken ödeme (+ alınan, − ödenen), değişkenin
  bileşik oranı, net, durum (`paid` / `due` / `running` - bugüne kadar - / `future`), tahmini günleri -, gerçekleşen
  (= accrued), ödenen ve ödenecek toplamları. *Carry* = **günün net tahakkuku** (sabit faiz − bugünkü O/N, dönemin bileşik
  nominali üzerinde: işaret × N × (K − I × r_ON) × gün / baz; başlamamış işlemde yok) **+ bir günlük roll-down**:
  işlem yarın, aynı şekli koruyan (spot'undan aynı gün için aynı zero faiz) eğride, bugünün forward'larının
  gerçekleştiği hâline göre - düz eğride sıfır; iki parça `inputs.carry_accrual` ve `inputs.roll_1d`. *Biriken*
  (`running`) = işleyen dönemin bugüne kadarki neti (kuponların `running` satırı). *Fonlama* 0.
  * *Spread* (iki bacak, DV01 1:1) ve *fly* (üç bacak, 50/50 DV01): toplam bacakların toplamı; seviye uzun − kısa (bp),
    fly'da gövde − ½ her kanat ve yanında OIS sayfasının 2·gövde − kanatlar kotası ("1s2s5s −12,5 bp (OIS sayfasında
    −25,0)"); `legs` her bacağın MTM'i, carry'si, gerçekleşen kuponu ve fiyatı.
  * *FRA* (`fra: "3x6"` ya da tarihleri) **tek enstrüman** olarak, ileri başlangıçlı swap; `legs` onu yeniden üreten iki
    swap (işlemin kendi valöründen, aynı nominal ve faizle: sonuna kadar FRA'nın yönünde, başlangıcına kadar ters):
    MTM'in ve carry'nin hangi bacaktan ne kadar geldiği; üretemedikleri `inputs.residual` (ızgaradaki FRA'da ~0).
  * *MPC* dönemi: toplantının etkin gününden (kararın ertesi iş günü, Motor!C5) bir sonrakinin etkin gününe; tarihler
    işlem girilirken toplantının tarihiyle sabitlenir, takvim sonradan değişse de işlem yerinde kalır.
  * Kapanmış işlem (`status` "closed", `close_price`): kapanışa kadar swap'ın kendi tahakkuku, kapanıştan sonra yalnız
    sabit faiz farkı (değişkenler birbirini götürür), carry yok. (Her üründe kapanış fiyatı kilitlenen K/Z'dir: FX
    spot ve tahvil kapanış fiyatıyla, opsiyon kapanış primiyle.)
* **DİBS** - *MTM* = (şimdiki kirli fiyat − ödenen kirli fiyat) × nominal / 100: şimdiki temiz fiyat DİBS RV'nin
  "Kullanılan temiz"i (listede olmayan kâğıtta Tüm Kâğıtlar'ın bid / ask ortası ya da son işlemi; ikisi de yoksa
  `manual_price`, o da yoksa `ok` false ve nedeni) ve valöründeki işlemiş faiz; işlemin temiz fiyatı (ya da getirisi:
  varsayılan BIST bileşik, `yield_conv: "basit"` basit) ve valöründeki işlemiş faiz karşısında. Hesap DİBS RV'nin BIST
  kuralı (`quantcurve.Bond`: kupon c/f, vadeden geriye round(364/f) günde bir; getiri yılda f kez bileşik, ilk dönem
  kesirli, bonoda basit; işlemiş faiz c/f × geçen gün / dönem günü) - sayfanın işlemiş faizini ve kirli fiyatını
  birebir verir. *Accrued* = valörden beri ödenen kuponlar (ve itfa). *Carry* = getiri sabitken bir sonraki valörün
  kirli fiyatı + aradaki kupon − bugünkü kirli fiyatın TLREF ile fonlanması. *Fonlama* = yalnız o fonlama,
  −işaret × N / 100 × kirli fiyat × TLREF × gün / 365 (carry'nin geri kalanı kâğıdın kendisinin, kirli fiyat - MTM - onu
  kazanır). TLREF'e endeksli ve FRN fiyatla izlenir
  (işlemiş faiz bugünkü kuponla, yaklaşık); TÜFE'ye endeksli kâğıt değerlenmez (endeks oranı panoda yok).
* **FX spot** - *MTM* = (spot − işlem kuru) × baz tutar, kote parada; spot USDTRY / EURTRY için Forward sayfasınınki,
  G10 için quant evreninin (yoksa çaprazı); *carry* = pozisyonu bir sonraki spot valörüne taşımanın puanı, iki paranın
  O/N faiziyle (TRY offshore O/N, SOFR, €STR; yoksa paritenin forward eğrisi). *Fonlama* = carry'nin tamamı (spot MTM'i
  taşımanın hiçbir kısmını tutmaz). Spot yoksa `manual_price`.
* **FX opsiyon** - Garman-Kohlhagen: teslim gününün forward'ı (USDTRY offshore eğri + USD OIS, puanı olan parite
  puanlarından, çapraz USD bacaklarından), kote paranın iskontosu (TRY offshore eğri, USD / EUR OIS, diğerleri
  USD paritesinden); vol zamanı vadeye kalan gün / 365. **Strike'taki vol** panonun smile'ından: USDTRY / EURUSD
  Opsiyon sayfasının SVI uyumu (paritenin delta kuralıyla), G10 quant evreninin ATM / 25D RR / 25D BF'si
  **Vanna-Volga** ile (`fxvol`); kotalar vadeye ara değerle (ATM toplam varyansta, RR / BF vol puanında doğrusal,
  kotalı vadelerin dışında sabit). `manual_price` elle vol'dür (vol puanı). *MTM* = opsiyon değeri − prim (alış +,
  satış −; prim kendi parasında, bugünkü kurla). *Carry* = theta. Greek'ler: delta (baz para tutarı, spot delta),
  gamma (spot %1 artınca deltanın değişimi), vega (vol puanı başına, kote para), theta (bir takvim günü: spot, vol ve
  faizler sabit). **Primin vol'ü** (`implied_vol`, `premium_vol`; değerlemede `vols` ve `inputs.premium_vol`): aynı
  spot, forward, iskonto ve vol zamanıyla opsiyonu primine eşitleyen vol - `gk`'nın vol'de tersi, Brent ile (`fxvol.brent`);
  prim içsel değerin bugünkü karşılığının altında / ona eşitse ya da call'da S · DF_baz'ın (put'ta K · DF_kote) üstünde /
  ona eşitse vol yok, nedeni yazar.
* **Fiyat** (`price_text`): "2Y OIS 35,85%", "MPC 11.12.26–22.01.27 37,25%", "2s5s −35,0 bp", "3x6 FRA 37,10%",
  "TRT150328T24 98,450", "USDTRY 41,8020", "USDTRY 3A 42 call vol 18,5".

**`defaults(product, pair, trade_date, mkt_or_svc, …)`** yeni işlemin masa varsayılanları: işlem tarihi bugün; valör
TRY OIS'te OIS spot'u (`OIS_MAIN!B2` = `WORKDAY(TODAY(),1,TRY)`), SOFR'da SIFMA listesiyle T+2, DİBS'te DİBS RV'nin
valör kuralı (ISL0 kâğıt aynı gün, diğerleri ertesi TRY iş günü), FX'te paritenin spot'u (USDTRY T+1, EURTRY / EURUSD
T+2, iki paranın tatilleriyle); opsiyonda teslim = vade + paritenin spot gecikmesi, prim parası kote para, prim valörü
valör; nominal parası; PPK / FOMC dönemleri (toplantı tarihiyle), FRA'nın tarihleri (`fra="3x6"`), paketlerin
ağırlıkları. **`check()`** alanları düzenler (tarih ISO, vade → bitiş tarihi, Türkçe sayı ve tutar, yön) ve denetler:
zorunlu alanlar, tarih sırası, ürünün takviminde iş günü (kayıtlı işlem değerlenirken değil), bilinen ISIN / fiyatlanan
parite (ya da `manual_price`), pozitif tutarlar; nedeni Türkçe `ValueError`. **`notional_for_dv01()`** yazılan DV01'in
(USD - masanın "1.000 $ DV01"i - ya da TL, bugünkü kurla) nominali: tam değeri, masanın 5 mn'lik lotuna yuvarlanmışı
(`OIS_MAIN!H2`; SOFR'da 5 mn USD; en az bir lot) ve yuvarlanmış nominalin verdiği DV01; spread / fly'da önce ağırlıklar,
sonra her bacak ayrı yuvarlanır.

**Açık kararlar:** carry'nin roll-down'u forward'ların gerçekleşmesine göre (düz eğride sıfır) ve TLREF'in bileşik
nominali üzerinde; tahvil getirisinin varsayılanı BIST bileşik; DİBS carry'sinde fonlama TLREF (repo değil); MTM
bugüne iskontolu (TRY swap), FX opsiyonu spot valörüne; opsiyonun primi bugünkü kurla; G10 forward'ı 3A puanından sabit
carry ile; floater'ın işlemiş faizi bugünkü kuponla; SOFR'ın 2 günlük ödeme gecikmesi yalnız ödeme gününü belirler
(iskonto dönem sonunda, kitabın bootstrap'ı gibi); ödeme günü gelmemiş (biten) kupon gerçekleşene yüzüyle girer;
`SOFR_FOMC!B11` "FF OIS" olursa değişken Fed funds'tır (`FEDL01 Index`) ve tarihçede yoktur (bugünkü fixing'le,
söylenerek) - tarihçe yalnız SOFR'ı tutar.

### Prop: pozisyon büyüklüğü ve prop risk

Üst şeritte, her sayfada **Prop** düğmesi (`tto/prop.py`, `prop.js`): altında küçük bir panel açar. **Yalnız görmek
içindir:** hiçbir işlem kaydedilmez, hiçbir yere gönderilmez; saklanan tek şey kendi günlük kayıp limitinizdir. Esc ya
da panelin dışına tıklamak kapatır; yazdıklarınız sekme açık kaldıkça durur.

**Hesaplayıcı.** Pariteyi (büyük / küçük harf fark etmez; masanın FX listesinden - quant pariteleri ve Spot / FX
sayfasınınkiler - fiyatı olan biri), stopu, göze aldığınız kaybı (`500k`, `1mn`, `2,5mn`; **TRY ya da USD**, her
seferinde seçilir) ve isterseniz girişi yazın (boşsa panodaki canlı orta kur, kutunun yanında yazar):

* **Yön** stoptan okunur: stop girişin altındaysa long, üstündeyse short; girişe eşitse hesap yapılmaz (sebebi yazılır).
* Kayıp paritenin **kote dövizine** bugünkü kurlarla çevrilir: USDTRY'de TL kayıp olduğu gibi; EURUSD'de TL kayıp
  USDTRY'den USD'ye; USDJPY'de USD kayıp USDJPY'yle yene.
* **Büyüklük** = kayıp / |giriş − stop| (baz dövizde), **1M'e aşağı yuvarlanır**: gerçek kayıp yazdığınızı hiçbir zaman
  geçmez. 1M'in altında kalırsa büyüklük 0'dır ve 1M'in ne kaybettireceği yazılır.
* Gösterilen: yön, mesafe (fiyat, %, pip; TL paritede kuruş), büyüklük (ham değeriyle), **gerçek kayıp** (seçtiğiniz
  dövizde, yanında öteki), 1M başına kayıp ve - limit girdiyseniz - bu kaybın bugün kalan alandaki payı.
* **İki yönlü** (masa, 24.11.2026: "tüm tablolar bu şekilde olmalı"): kaybın yerine **Büyüklük** de yazılabilir (`2m`,
  `2,5m`; baz dövizde). Stop verili, kayıp ve büyüklükten **son yazdığınız kalır** (kalın, ✎), öbürü ondan hesaplanır ve
  kutusunda soluk görünür: büyüklük yazılınca stoptaki kayıp = büyüklük · |giriş − stop| (seçtiğiniz dövizde; yazılan
  büyüklük yuvarlanmaz), kayıp yazılınca büyüklük eskisi gibi 1M'e aşağı. Yazılanı silince ikisi de boşalır.
* Örnek: USDTRY giriş 44,35, stop 44,55, kayıp 500k TL → SHORT; mesafe 0,20; ham 2,5M; **2M USD**; gerçek kayıp
  **400.000 TL**; 1M başına 200.000 TL.

**Prop risk** (aynı panelde; **Kişisel / Masa**: Trades'in iki sekmesi, seçim bu tarayıcıda hatırlanır):

* **Stoplar** - sekmenin açık işlemleri stoplarına giderse ne kaybeder: şimdiki piyasadan, işlemin kendi seviyesinde
  (Trades'teki hedef / stop birimi), değerlemesinin duyarlılığıyla:
  - FX spot: tutar × kur farkı;
  - TRY OIS / SOFR (outright, PPK, FRA): DV01 × bp;
  - spread / fly: seviyenin DV01'i (bacakların DV01 toplamının yarısı: DV01 ağırlıklı pakette uzun bacağın / gövdenin
    DV01'i) × seviyenin bp'si;
  - DİBS getiriyle: DİBS RV'nin DV01'i × bp; fiyatla: nominal × fiyat farkı / 100;
  - **FX opsiyon:** Trades'te opsiyonun stopu **prim tutarıdır** (spot seviyesi değil), kayıp prim farkıdır; delta
    yalnızca stopun karşılık geldiği spotu söyler ("yaklaşık (delta)").

  Seviyeler stop alarmları gibi Bootstrap (Murex) eğrisiyle okunur. **Geçilmiş stop** Stoplar'a eklenmez: ötesindeki
  kayıp zaten MTM'de, dolayısıyla K/Z'dedir; satırında "geçildi · ötesi …" yazar. **Stopsuz** işlemler ayrıca
  listelenir (DV01, tutar ya da delta - yaklaşık) ve Stoplar'a girmez; değerlenemeyen işlem sebebiyle yazılır,
  toplama girmez (yanında `*`).
* **Bugün K/Z** - Trades sayfasının o sekmedeki **"Günlük"** toplamı: son "MTM yenile"nin değeri, sizin eğri
  ayarınızla. Bugün MTM yenilenmediyse bugünkü K/Z (ve kalan alan) bilinmez; paneldeki **MTM yenile** Trades'tekinin
  aynısıdır.
* **Günlük kayıp limitim** - TRY ya da USD; yalnız siz görür ve değiştirirsiniz (sunucuda, hesabınızla); boş bırakıp
  kaydedince kalkar.
* **Kalan** = limit − bugünkü zarar (kâr alan açmaz) − Stoplar. Üst satır **Limit · Bugün K/Z · Stoplar · Kalan**,
  panelin dövizinde (kaybın TRY / USD seçimi); öteki döviz bugünkü USDTRY'den. Limit yoksa satırda limit ve kalan
  yoktur (yalnız Bugün K/Z · Stoplar).

Fiyatlar panodaki değerleme görüntüsünden gelir (Forward sayfasının USDTRY ve EURTRY'si, quant'ın FX serileri, USD
üzerinden çaprazlar; hiçbiri yoksa iki TL fiyatının çaprazı: EURUSD = EURTRY / USDTRY) - **Bloomberg'e yeni istek
yok**. Fiyatı olmayan parite için "canlı fiyat yok" yazar. Risk panel açılınca, düğmeleriyle ve açıkken dakikada bir
yeniden okunur.

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
`EK_DIBS`, `EK_EVREN`, `EK_CARRY`, `EK_IHALE`, `EK_TATIL`, `EK_TARIH`, `EK_VFRA`, `EK_RET`; ASW kitabına `EK_FX`; Bulk Bond sayfasına 7–52. satırlar; Motor ve Carry & Roll'da carry patikası ve gün sayısı formülleri; Forward ve Masa'da FX valörleri; VİOP Target'a FRA eğrisi ve **Fiyat** hedef tipi; RET adil değerine senaryo eğrileri).
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
- **İki yönlü** (masa, 24.11.2026: "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız için"; genel
  kural: Kullanım'daki *İki yönlü tablolar*). USDTRY ve EURTRY tablolarında her eğri satırının (Elle dahil) bid'inde ve
  ask'inde **TRY %**, **forward**, **puan** ve **P/gün**, serbest forward listesinde **minor %**, **swap** ve **forward**
  yazılabilir: **hangisini yazarsanız o kalır, diğerleri ondan hesaplanır** (tablonun altında da yazar; yazılan ✎ ile
  işaretli). Hesap tablonun kendi formülleri ve tam tersleridir: forward ya da puan yazılınca TRY = ((fwd/spot)·(1 +
  döviz·g/360) − 1)·360/g (bid tarafı döviz ask'iyle, ask tarafı bid'iyle; serbest listede satırın spot'u, major %'si ve
  günü), puan = (fwd − spot)·10000, P/gün = puan / gün; P/gün yazılınca puan = P/gün · gün. Orta sütunlar (TRY mid, mid
  forward, puan ve P/gün mid) iki taraftan hesaplanır, yazılmaz. Son yazılan geçerlidir; `Delete` satırın o tarafını
  eğriye döndürür. EURTRY tablosunun TRY faizleri USDTRY tablosundakilerdir: USDTRY'de yazılan forward / puan EURTRY'nin
  faizini de (ve forward'ını) değiştirir, EURTRY'de kendi değeri yazılmadıkça. **Valör tarihi değişince yazılan değer
  kalır** (yazılan bir TRY faizi gibi): aynı forward / puan yeni valörün değeri sayılır, diğerleri yeni günle hesaplanır.
  Önceden yazılan TRY faizleri aynen durur; forward / puan / P/gün'ün yazılanları satırın gizli sütunlarında (`N:U`;
  serbest listede `Z:AB`) saklanır, yardımcı tabloda görünür.
- **ON karşılık** (masa, 26.11.2026: "Toplu forward fiyatlama kısımlarında ON karşılıklarını da görmek istiyorum" -
  "Bunların da hepsini yap"): USDTRY ve EURTRY tablolarında TRY bid / mid / ask %'nin hemen yanında **ON bid / mid /
  ask %**, serbest forward'da minor %'nin yanında **Minor ON %**. Forward hesaplayıcılarının *ON Karşılık*'ı:
  `ON = 360·((1 + TRY·g/360)^(1/g) − 1)` - her gün 360 bazında bileşik, g tablonun forward'ının o faizi uyguladığı gün
  (USDTRY tablosunda valör − USDTRY spot valörü, EURTRY'de valör − EURTRY spot valörü, serbest listede başlangıç → bitiş).
  İki yönlüdür: ON bid / ask ya da Minor ON yazılınca TRY faizi onun tam tersi, `TRY = ((1 + ON/360)^g − 1)·360/g`,
  forward, puan ve P/gün ondan; ON mid (TRY mid'in ON'u) yazılmaz. USDTRY'de yazılan ON USDTRY'nin TRY faizini verir,
  EURTRY o faizi alır (ON'u EURTRY'nin günüyle - bir gün farkla); valör tarihi değişince yazılan ON kalır, faizi yeni
  günle hesaplanır. İki ondalıklı görünür (değer bütün ondalıklarıyla); yazılanlar gizli sütunlarda (`Y:Z`, `AC`).
- **TRY faizleri vadelere göre**: valör, 1W–2Y ve kendi yazdığınız tarihlerde offshore, OIS, VİOP ve RET'in **simple
  zero** (ACT/360) mid faizi yan yana ve OIS'e farkları (bp). Gün ve vadeler USDTRY spot valöründen; faizler Forward
  sayfasının kendi düğümlerinden doğrusal. Bir eğri son düğümünden bir aydan uzak tarihte faiz vermez (düz uzatmak
  yerine boş kalır: VİOP ~1 yıl, RET 2 yıl), serbest forward listesinde de.
- **TRY faizleri iki ondalıkla** (masa, 25.11.2026: "Forward fiyatlama kısımlarında try faizleri 4 decimal'i çok yoruyor
  gözü. Bunları 2 decimala alalım"): USDTRY / EURTRY tablolarının TRY bid / mid / ask %'si ve Elle ayarının mid %'si,
  serbest forward'ın minor %'si, TOPLU FORWARD'ın offshore / OIS / RET faizleri, Manuel TRY %'si, İma TRY %'leri (ve
  26.11'den beri ON karşılık %'si, Dönem TRY % / ON %'si ve faizlerin ON'ları; spread'ler bp, bir ondalık), ÇAPRAZ
  FORWARD'ın İma TRY %'si (Kotasyon matrisleri, puandan / faizden spread, vadelere göre TRY faizleri, Forward
  starting swap ve hesaplayıcılar zaten iki ondalıklıydı). **Yalnız görünüş:** değer, hesap ve yazılan bütün
  ondalıklarıyla kalır (36,123456 yazılırsa 36,12 görünür, forward 36,123456 ile hesaplanır); **Tam hassasiyetle
  kopyala** (Ctrl+Shift+C) bütün ondalıkları kopyalar. Ctrl+C, *Kota mesajı*, *Kotasyon kopyala* ve *İşlem gir*
  gördüğünüzü alır (TRY faizi iki ondalıkla). USD / EUR faizleri eskisi gibi: valör satırının USD (EUR) bid / mid / ask'i
  ve serbest forward'ın major %'si dört, TOPLU FORWARD'ın USD % / EUR %'si üç ondalık; gizli yardımcı sütunlar (yazılanın
  verdiği faiz) de.

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
fiyatlama" sekmesinde USDTRY ve EURTRY özeti: her spread'in **yanında verdiği TRY faizi ve onun ON karşılığı** - Spread bid ·
TRY bid % · ON bid % · Spread ask · TRY ask % · ON ask % -, sonra spot, puan ve forward; spread'ler oradan da yazılır). Vadeler 1M / 2M / 3M / 6M / 9M / 12M (valör formülle gelir, üzerine yazılabilir)
ve dört serbest tarih. "Tümü" satırına bid ve ask için **ayrı** OIS spread'i (bp) yazılır; bir vadenin kendi spread'i
o satıra yazılır (silince genele döner). Her satırda: valör, gün, spot bid / ask, **puan bid / ask**, forward bid / ask,
OIS %, TRY bid / ask % ve hemen yanında **ON bid / ask %** (TRY faizinin valörün günüyle ON karşılığı, `360·((1 +
TRY·g/360)^(1/g) − 1)`: Forward hesaplayıcılarının *ON Karşılık*'ı), USD %, günlük puan, RET bid / ask % ve aynı valörde
RET'le çıkan puana fark.
OIS eğrisi listeden seçilir (MPC ima, S1–S3, Ağırlıklı, Bootstrap, TLREF sabit; seçilen S1–S3'ün hangi senaryo
olduğu – Baz / Hawkish / Dovish ve olasılığı – yanında ve tablonun altında yazar) ve Masa'daki "Tarih arası faiz"
bloğunun iskonto faktörleriyle aynıdır: aynı tarih ve spread'de iki blok aynı TRY faizini verir.
`Fwd bid = spot bid·(1+TRY bid·g/360)/(1+USD·g/360)`, ask tarafı spot ask ve TRY ask ile.

**Matris iki yönlüdür** (masa, 24.11.2026: "ben hazırda olan forward kotasyon kısmında hem spread hem faizler girdi
olabilsin, hangisine ben girdiysem diğerini hesaplasın"; genel kural: Kullanım'daki *İki yönlü tablolar*). Bir vadenin
**spread**'i, **TRY %**'si, **puan**'ı ve **fwd**'si - bid ve ask ayrı ayrı - dördü de yazılabilir: **spread, TRY %, puan
ya da fwd - hangisini yazarsanız o kalır, diğerleri ondan hesaplanır** (tablonun altında da yazar). Yazılan değer piyasa
değişse de aynen durur (TRY % yazdıysanız spread OIS'le, puan ve forward spot ve USD faiziyle değişir, TRY % kalır), kalın ve ✎ ile
işaretlidir; üzerine gelince ne yazdığınızı, öbürlerinin üzerine gelince neden hesaplandığını söyler. Hesap matrisin
kendi formülleri ve tam tersleridir: spread = TRY − OIS; fwd = spot·(1+TRY·g/360)/(1+USD·g/360); puan = (fwd − spot)·10000;
puan yazılınca fwd = spot + puan/10000; fwd (ya da puan) yazılınca TRY = ((fwd/spot)·(1+USD·g/360) − 1)·360/g. Hesaplanan
bir değeri kendi sütununa geri yazmak aynı satırı verir. **Son yazılan geçerlidir:** aynı vadenin aynı tarafında başka
bir sütuna yazınca önceki yazdığınız gider. `Delete` (ya da sağ tık → "Kendi girdimi sil") satırın o tarafının dört
hücresinden **herhangi** birinde satırı varsayılanına döndürür: "Tümü" satırının spread'i, **Piyasa spread** seçiliyken
o vadenin piyasa spread'i. Piyasa spread seçiliyken de yazdığınız (spread ya da TRY % / puan / fwd) kalır - seçim yalnız
hiçbir şey yazılmamış vadelerin varsayılanıdır. Excel'den bir sütun yapıştırmak her satırı o sütunun yazılanı yapar;
bir blok yapıştırılınca bir satırın her tarafında en sağdaki dolu değer kalır. Formül de yazılabilir (ör. TRY bid %'ye
`=EK_FWD!N5-0.25`: ask'tan 25 bp aşağı); satırın aynı tarafının başka bir değerini okuyan formül döngüdür, reddedilir.
Bu özellikten önce yazdığınız spread'ler aynen durur ve satırlarının yazılanıdır (hiçbir değer taşınmadı); TRY % / puan /
fwd'nin yazılan değerleri satırın gizli sütunlarında (`AN:AS`) saklanır, yardımcı tabloda görünür. Masa'daki özette de
aynıdır (oradaki TRY %, puan ve fwd de yazılabilir). EURTRY matrisi de iki yönlüdür (kendi spot'u, EUR faizi ve EURTRY
günüyle). **ON karşılık** da (26.11.2026) bir vadenin bid'inde / ask'inde yazılabilir - Masa'daki özette de: TRY % onun
tam tersi, `((1 + ON/360)^g − 1)·360/g` (g valörün günü), spread, puan ve fwd ondan; yazılan ON gizli `AX:AY`'de.

Altındaki **Puan → OIS spread** tablosu tersini yapar: elle verdiğiniz bid / ask puanının ima ettiği TRY faizini ve
OIS'e göre kaç bp olduğunu gösterir. Onun hemen arkasındaki **Faiz → spread** tablosu (masa, 23.11.2026: "faizi girdiğimde
de spreadi ve rate'leri vermesi lazım") aynı vadeler için **TRY bid / ask %** yazdırır ve OIS'e göre **spread'i** (bp),
puanı, forward'ı, P/gün'ü ve RET'e farkı verir - matrisin aynı formülleriyle, OIS + spread yerine yazılan faizle. Bulunan
spread'i matrise yazınca aynı puan ve forward çıkar. İki tablo da kalır (masa: "Yeni açtığımız tablolar kalsın"); aynı
şey artık matrisin kendisinde de yapılır.

**Tek OIS spread'i.** Masanın OIS spread varsayımı bir kez yazılır: Masa'daki tarih arası faizin spread'i
(`MASA!I60`, −150 bp). Matrisin genel spread'i, Forward'daki "TRY OIS w/Spread" spread'i (`P58`, % puan: −1,5), OIS
ortasının valör kaydırması (`O27`, −%1,5) ve OIS sayfasındaki tarih arası faizin spread'i (`OIS_MAIN!F122`, −%1,5) ondan
çevrilir (eskiden dört ayrı yere yazılıyordu). Her biri ayrıca kendi değeriyle üzerine yazılabilir; silince yine
`I60`'tan gelir.

**Piyasa spread'i.** "Tümü" satırındaki seçim **Elle spread** (yazdığınız spread'ler) ya da **Piyasa spread**: her
vadenin bid / ask spread'i offshore ima eğrisinin (Forward sayfasının ICAP eğrisi) o valördeki bid / ask faizi − OIS
(bp). Son iki sütun (*Piyasa bid / ask*) her vadenin piyasa spread'ini seçimden bağımsız gösterir; eğrinin bittiği
yerden ötede boştur. EURTRY matrisi seçimi USDTRY'ninkinden alır (ayrıca değiştirilebilir).

**EURTRY** için aynı matris USDTRY'ninkinin hemen altındadır (`EK_FWD` 100–115; puan → OIS spread'i 117–129; faiz →
spread'i 145–157, USDTRY'ninki 131–143 - hiç girdi olmamış satırlar): aynı
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
swap puanı dolu açar; tutarı yazıp kaydetmek yeter. Tek bir fiyat için sağ tık → **İşlem gir** de olur (puan, outright,
TRY %, RET, OIS, tahvil fiyatı; Günlük İşlemler'de *Fiyattan işlem*).

**Kotasyon kopyala (müşteriye kotasyon).** Fiyatlama tablolarının başlığındaki **Kotasyon kopyala** tek tıkla müşteriye
gönderilecek kotasyonu panoya koyar: parite / enstrüman, başlangıç (valör) ve vade tarihi gün sayısıyla, spot, swap puanı,
outright, TRY ve döviz (USD / EUR) faizi, tablonun tutarı varsa tutar, yönü biliyorsa yön; iki taraflı tablolarda bid / ask.
Yanındaki **▾** dili seçer (**Türkçe** / **English**; seçince o dilde kopyalar, seçim tarayıcıda hatırlanır); sayılar dile
göre yazılır (`34,25` / `34.25`, `12.663` / `12,663`, `04.12.2026` / `04 Dec 2026`), her sayı tablodaki biçimiyle (hane
sayısı tablodakidir). Biçim RET penceresinin "Kopyala (mesaj)"ı gibi hizalı metindir:

```
USDTRY forward 1M · 03.11.2026 · bid / ask
Başlangıç    04.11.2026
Vade tarihi  04.12.2026 (30 gün)
Spot         49,9970 / 49,9975
Swap puanı   12.663 / 12.664
Outright     51,2633 / 51,2639
TRY faizi %  34,38 / 34,38
USD faizi %  3,89
```

Birden çok satırlı tabloda düğme fiyatı olan her satırı bir satır olarak kopyalar (başlık satırı `Vade  Vade tarihi  Gün
Swap puanı …`, bütün satırlar için aynı olan başlangıç ve spot üstte; boş serbest satır, doldurulmamış Target satırı
girmez); tek satırın kotasyonu **satıra sağ tık → "Bu satırın kotasyonu"**. İki pariteyi yan yana veren hesaplayıcılar
(USDTRY | EURTRY) ikisini birden kopyalar, ▾'den "Yalnız USDTRY" / "Yalnız EURTRY". Kotasyon veren tablolar: Masa'nın
USDTRY ve EURTRY forward özeti, **TARİH ARASI FORWARD** (eğri başına forward-forward), **KIRIK VADE & KARŞILIK** (girilen
kotanın outright, puan, basit ve O/N karşılığı) ve VİOP TARGET özeti; Forward'ın hesaplayıcıları (Interest 2 SP, SP 2
Interest, all-in, O/N; XARTRY müşteri altın forward'ı), Forward fiyatları (USDTRY, EURTRY, serbest forward), Forward DV01
(yön ve tutarla) ve Kotasyon sekmesindeki iki matris; VİOP'un Target tablosu. Sayılar kullanıcının kendi hesabındandır
(girdileri ve elle değerleri dahil: sayfasında gördüğü). Bir tablonun hangi hücrelerden kotasyon verdiği sayfa tanımındaki
`"client_quote"`dur (`tto/views/__init__.py`); yeni bir tablo kod yazmadan katılır. Uç: `GET /api/quote?view=…&panel=…`
(`row`: tek satır, `part`: yan yana kotasyonlardan biri, `language`: `tr` / `en`) → `{"text"}`. Pano bir sebeple metni
almazsa (tıklamadan uzun süre sonra) metin bir pencerede seçili açılır, "Kopyala" ile alınır.

**Toplu tarih arası faiz** (Masa → Faiz · PPK, TARİH ARASI FAİZ'in hemen altında; `EK_TARIH`). TARİH ARASI FAİZ bloğu
(`MASA!B59:N70`) bir başlangıç / bitiş çifti alır; bu tablo 100 çifte kadar aynı hesabı yapar: bloğun kendi formülleri
satır satır (her eğrinin OIS spot'tan başlangıç ve bitişe iskonto faktörü `MASA!H62:I68`, dönem faizi, Ağırlıklı = S1–S3
OIS · PPK olasılıklarıyla). Aynı başlangıç, bitiş ve spread'le satır bloğun sayılarını verir.

* **Girdiler (satır başına):** **Başlangıç** (boşsa OIS spot valörü - bloğun kendi varsayılanı; bitiş yazılınca görünür),
  **Bitiş**, **Spread (bp)** (boşsa üstteki **genel spread**; o da başta Masa'nın tek OIS spread'idir, `MASA!I60`, üzerine
  yazılabilir, silince yine `I60`'tan gelir). Excel'den başlangıç | bitiş | spread sütunları birlikte yapıştırılabilir (boş
  spread hücresi genel spread'i alır), Toplu forward'daki gibi. Kısayollar TRY takviminde: bitişe `3A` yazınca satırın
  başlangıcından sayılır.
* **Çıktılar:** **Gün**, yedi eğrinin (MPC ima, S1–S3 senaryo adlarıyla, Ağırlıklı, Bootstrap, TLREF sabit) dönem faizi ve
  seçilen eğrinin **ACT/360 basit faizi + spread**'i (bloğun "Dönem + spread (360)"ı). Üstteki **Eğri (+ spread)** son
  sütunun eğrisini seçer (varsayılan MPC ima), **Gün esası** eğri sütunlarını ACT/360 (varsayılan, masanın kotası),
  ACT/365 ya da O/N (360) gösterir (bloğun D, C, E sütunları); son sütun her durumda ACT/360'tır.
* **Kote %** (masa, 24.11.2026, 1. madde: bir kırık tarih için verilen faizi yazıp her eğriye spread'ini görmek): bir
  satırın kotası yazılır ya da Excel'den bir sütun yapıştırılır; tablonun **gün esasında** okunur (üstteki seçim; başlık
  söyler: "Kote % (ACT/360)"). Yanında **Kote − seçilen eğri** ve **Kote − Bootstrap** (bp, aynı gün esasında): eğrinin o
  satırdaki faizi + bu fark = kote. ACT/360'ta seçilen eğrinin farkı satırın spread'ine yazılınca "+ spread (360)" kote
  olur. Yedi eğrinin hepsine birden yer yok (tablo zaten ekrandan geniş): seçilen eğri ve Bootstrap (Murex'in eğrisi);
  başka bir eğriye göre bakmak için üstteki eğri seçilir, yedisi birden tek tarih için aşağıdaki kutuda.
* Satırlar boş başlar; tablo dolu satırları ve bir boş satırı gösterir ("+ Satır", "Tümü"). Yazılanlar kişiseldir.
  Eğriler kullanıcının **Eğri interpolasyonu** ayarını blok gibi izler (Bootstrap satırı PPK basamak seçende onun eğrisi).
  Yardımcı sütunlar (gün, iskonto faktörleri, ACT/360 ve + spread) "Yardımcı tablolar"dadır.

**Tarih arası faizden spread** (Masa → Faiz · PPK, TARİH ARASI FAİZ'in hemen altında: *TARİH ARASI FAİZ → SPREAD*; masa,
24.11.2026, 1. madde: Forward sayfasındaki FAİZ → SPREAD'in tarih arası hali). Bloğun tarihleri için verilen faizi
**Kote % (ACT/360)**'a yazın (yanında bloğun başlangıcı, bitişi ve günü): her eğrinin altında **Kote − eğri (bp)** = kote −
o eğrinin dönem ACT/360 faizi (bloğun D sütunu). ACT/360 basit, çünkü blok spread'i ACT/360 basit faize ekler; bulunan
spread bloğun **Spread (bp)**'sine yazılınca o eğrinin "Dönem + spread (360)"ı kote olur. Eğriler bloğun TRY OIS
eğrileri (MPC ima, S1–S3, Ağırlıklı, Bootstrap, TLREF sabit; kullanıcının eğri ayarını blok gibi izler). Girdi kişiseldir,
boş başlar.

**Masa: offshore 2Y sonrası zero ve O/N** (Masa → Genel bakış; masa, 26.11.2026: "Masa sayfasında offshore'un da 2y
sonrasını zero ve on karşılıkta göstermemişiz"). ORANLAR'ın 3Y / 5Y / 7Y / 10Y satırlarında **ICAP** ve **OIS zero** artık
dolu, aralarındaki **ICAP − OIS (bp)** de - 2Y satırı gibi her biri kendi eğrisinin zero faizi, 360 basit, kendi spot'undan:
**ICAP** XCCY (TRYSAQ) bootstrap'ının zero'su (`Forward!H127 / H129 / H131 / H134`, (1/DF − 1)·360/gün; gün kotanın
Bloomberg vadesi, USDTRY spot'undan - 6Y–10Y'de Bloomberg'in günü yoksa spot'tan TRY + USD takvimiyle sayılır), **OIS zero**
OIS bootstrap'ının, Motor'un 36 / 60 / 84 / 120. ay düğümünde (`Motor!M102 / M110 / M118 / M130`; gün OIS spot'undan;
2Y'ye kadarki satırlar gibi kullanıcının *Eğri interpolasyonu* ayarını izler, ICAP izlemez). RET ve VİOP orada boştur (kota
yok). XCCY fiyatı olmayan vade - kendisinin ya da öncekilerden birinin fiyatı yoksa - **boş kalır, OIS'ten doldurulmaz**.
**O/N EŞLENİKLERİ**'nin Offshore O/N'u 3Y–10Y'de aynı iskonto faktörlerinden, aynı günlerle zaten okunuyordu
(`Forward!E112 / E114 / E116 / E119`); bir satırın zero'su ile O/N'u her eğride aynı DF'tir. Kayıtlı dosyada (replay)
TRYSAQ6–10 `#N/A` olduğundan orada 7Y / 10Y offshore boştur; masanın geçmişinde bu kotalar her gün vardır, masada dolar.
Masa ve Forward sayfalarında başka hiçbir hücre değişmez.

**Faizden PPK / FOMC adımı ve FRA'nın öbür bacağı** (masa, 24.11.2026: "1-2-3-4-5-6-7-8-11-11-13" - 2, 3 ve 13). Üç
hesap tersinden; her biri sayfanın kendi formülünün tam tersidir (bulunan değer ileri yöne yazılınca yazdığınızı verir):

* **MPC OIS → PPK ADIMI** (OIS · PPK → *PPK ima*, MPC OIS'in hemen altında; `EK_PPK!A1:M18`). MPC OIS'in her dönemi (bir
  toplantının etkin gününden sonrakininkine) için **MPC OIS (elle)**'ye bir toplantı swap'ının faizini yazın: **İma PPK
  adımı (bp)** = faizin O/N eşdeğeri − önceki dönemin piyasa faizinin O/N eşdeğeri. Önceki dönem MPC OIS'in bir önceki
  satırının *Piyasa (bootstrap)*'ıdır; ilk dönemde OIS spot'tan ilk toplantıya bootstrap stub'ı. Yanında **Piyasanın
  adımı**: dönemin kendi piyasa faiziyle aynı hesap. Bu, **Broker Chat**'in toplantı swap'ı satırlarına yazdığı ima adımın
  kendisidir (aynı önceki dönem, aynı dönüşüm): chat'teki "dec mpc 36.50/37.00" ile tabloya yazılan %36,50 aynı bp'yi
  verir. Piyasa Bootstrap'tır (Murex'in MTM'i); Ayarlar'da PPK basamak seçen kullanıcıda kendi eğrisi - MPC OIS tablosu
  ve chat gibi.

  **O/N eşdeğeri TLREF'in iş günleriyle** (masa, 25.11.2026: "B" - önceden her takvim günü ayrı bileşikti, hafta sonu
  hafta içi gibi işliyordu). TLREF yalnız iş günlerinde işler: her iş gününün faizi bir sonraki iş gününe kadarki takvim
  günleri boyunca tek adımda (1 gün; hafta sonu Cuma'nın faizi 3 gün; tatilde aradaki günler kadar), ACT/365 - OIS ·
  PPK'daki MPC ima modelinin (`Motor`) TLREF'i bileştirdiği gibi. Dönemin gün sayısı d, iş günleri arasındaki boşluklar
  g ise: ln(1 + faiz·d/365) = d·ln(1 + x) − W·x², x = O/N / 365, **W = Σ g(g − 1)/2** (dönemin hafta sonu / tatil terimi;
  modelin kendi günlük takviminden - `Motor!F528:F4228`, toplantının etkin günündeki değeri `Motor!J` -, masanın TRY tatil
  listesiyle, Ayarlar → Tatiller). Bu, Π (1 + x·g)'nin modelin kullandığı ikinci derece açılımıdır (tam çarpımdan farkı
  hafta sonunda binde birkaç, bayramda yüzde birkaç bp). Dönemin tarihleri de modelinkiler: kararın ertesi iş gününden
  sonraki toplantınınkine, ilk dönemin öncesi OIS spot'tan. Modelin kendi dönem faizi (*İma oran (model)*, `OIS_MAIN!BJ`)
  yazılınca O/N eşdeğeri modelin TLREF'idir (`Motor!K`), adımlar da modelin adımları. Tekrar günü (03.11.2026) piyasanın
  adımları bu yüzden −0,87 … +0,95 bp değişti; yazdığınız faiz faiz, adım adım olarak kalır, yalnız ondan hesaplanan değişir.
* **MPC SPREAD → PPK ADIMI** (MPC SPREAD'in hemen altında; `EK_PPK!P1:W17`). **Elle spread (bp)**'e bir MPC spread'i
  yazın (sonraki dönem − önceki dönem, MPC SPREAD'deki gibi): sonraki dönemin faizi = önceki dönemin piyasa faizi +
  spread ve bu faizin sonraki dönemin toplantısında fiyatladığı **PPK adımı** - üstteki tabloyla aynı hesap, aynı taban.
  Broker Chat spread satırlarını okumaz; spread'in adımı burada.
* **TÜM FORWARD / FRA → Hedef FRA** (OIS · PPK → *Tüm listeler*; `OIS_MAIN!U336:W438`). **Hedef FRA**'yı yazın:
  **Gereken bitiş bacağı** - başlangıç bacağının dolumuyla (*Başl. bacağı dolum*; boşsa piyasa par'ı) bu FRA'yı veren
  bitiş bacağı oranı, (F·(P − O) + Q·O) / P; **Gereken başl. bacağı** - bitiş bacağının dolumuyla (*Bitiş bacağı dolum*;
  boşsa piyasa) gereken başlangıç bacağı oranı, (R·P − F·(P − O)) / O. *Gerçekleşen FRA*'nın (R·P − Q·O) / (P − O)
  formülünün tersi: bulunan oran dolum sütununa yazılınca Gerçekleşen FRA hedefe eşit olur. Spot başlangıçlı satırda
  bitiş bacağı FRA'nın kendisidir; başlangıç bacağı yoktur. OIS eğrisi.
* **Pencere OIS → FOMC adımı** (USD · FOMC → *FOMC*, FOMC ima patikası tablosunun sağında; `SOFR_FOMC!AA72:AE83`). Bir
  toplantının penceresinin (İşlem 1'deki pencere: etkin gününden sonraki toplantıya) OIS faizini **Pencere OIS (elle) %**'ye
  yazın (%, ACT/360): **Elle O/N %** - *İma O/N %*'nin formülü faizin kendi iskonto oranıyla, ((1 + r·gün/36000)^(1/gün)
  − 1)·36000 - ve fiyatladığı adım *Önceki ima %*'ye göre: **Elle adım (bp)** ve *Toplantı adımı %* gibi Adım (bp)
  cinsinden **Elle toplantı adımı %**. Yanında piyasanın pencere faizi (İşlem 1'in *Piyasa fwd %*'si): onu yazınca İma
  O/N ve Toplantı adımı aynen çıkar. USD OIS eğrisi (Girdiler'deki Eğri kaynağı). Burada O/N her takvim günü bileşiktir
  (SOFR; sayfanın kendi *İma O/N*'si gibi): TRY'deki iş günü kuralı (25.11.2026) TLREF'in, FOMC tablosu değişmedi.

Yazılanlar kişiseldir ve boş başlar. **Dönem faizi, spread ve pencere faizi toplantısıyla gider** (`tto/meetings.py`):
takvim değişince, araya toplantı girince ya da toplantı geçince bir satıra yazılan faiz / spread satırın (ilk) döneminin
başladığı toplantıyla kayar, toplantısı listeden çıkanınki kenara alınır; FOMC'deki pencere faizi de toplantısıyla gider.
Yeni Bloomberg isteği yok; Bootstrap sayıları değişmez.

**İki yönlü: tarih arası ve OIS tabloları** (masa, 24.11.2026: "Genel olarak tablolar bu şekilde olmalı karışıklık
olmaması için", "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız için"). Bu tablolarda birbirine
bağlı değerlerden **hangisini yazarsanız o kalır, diğerleri ondan hesaplanır** (*Kullanım → İki yönlü tablolar*: ✎ yazılan
değer, son yazılan geçerli, `Delete` varsayılana döner). Yukarıdaki ayrı kutular (TARİH ARASI FAİZ → SPREAD, Kote %, Hedef
FRA) olduğu gibi kalır.

* **TARİH ARASI FAİZ / TARİH ARASI FORWARD** (Masa): bloğun **tek spread'i** (Spread (bp), `MASA!I60`) ya da onu taşıyan
  77 değerden herhangi biri - her eğride Dönem + spread (360), Spot→bitiş + spread, TRY % başl. / bitiş, Fwd başlangıç /
  bitiş, puanları, Fwd-fwd puan, Dönem TRY %, Bitiş fwd − RET mid fwd. Spread yedi eğrinin hepsine tek olduğundan blokta
  **tek değer** yazılı olur: yazdığınız kalır, spread ondan, diğer eğrilerin bütün değerleri o spread'den hesaplanır
  (örnek: Bootstrap satırının fwd-fwd puanını yazın; spread ve MPC ima / senaryoların forward'ları ondan). Blokta yazmak
  `I60`'a yazılmış spread'in yerini alır. **Spread başka tabloların varsayılanıdır**: FORWARD KOTASYON'un genel spread'i,
  TOPLU TARİH ARASI FAİZ'in genel spread'i, Forward'daki "TRY OIS w/Spread" ve OIS mid kaydırması, OIS sayfasının iki
  tarih arası faizi - blokta bir faiz ya da forward yazılıysa onlar da o spread'i izler; eğri değiştikçe yazılan durur,
  spread ve onlar değişir. Başlangıç OIS spot iken (varsayılan) başlangıç bacağı spread'e bağlı değildir (forward'ı spot):
  oraya (TRY % başl., Fwd başl., Puan başl.) yazılan değer spread vermez - blok boş görünür; silince ya da ileri bir
  başlangıç yazınca döner. Geçici kopyada da çalışır; tabloda spread'i elle yazdıysanız kopyada bloğun başka bir değeri
  yazılamaz (nedeni söylenir), spread'in kendisi yazılabilir. Yazılanlar gizli yardımcı tabloda (*Yardımcı · TARİH ARASI
  FAİZ / FORWARD*) verdikleri spread'le görünür.
* **TOPLU TARİH ARASI FAİZ**: satırın **Spread (bp)**'i ya da **+ spread (360)**'ı - "+ spread" yazılınca satırın spread'i
  = yazılan − seçilen eğrinin ACT/360 faizi (tablo hangi gün esasını gösterirse göstersin; Ağırlıklı'da S1–S3 ortalaması).
  Kote % ayrı bir okumadır: satırın spread'ini değiştirmez (ACT/360'ta "Kote − seçilen eğri", aynı faiz "+ spread"e
  yazılınca satırın alacağı spread'dir).
* **MPC OIS → PPK ADIMI**: **MPC OIS (elle)**, **O/N eşdeğeri** ya da **İma PPK adımı** - adım yazılınca O/N = önceki
  dönemin O/N'si + adım, faiz o O/N'nin dönemdeki karşılığı (aynı dönüşümün - iş günlerinde bileşik TLREF - tam tersi,
  Broker Chat'le aynı). **MPC SPREAD → PPK ADIMI**: **Elle spread**, sonraki dönemin faizi, O/N'si ya da adımı.
  Hangisini yazdıysanız toplantısıyla gider.
* **OIS · Nakit Akışı**: **İşlem oranı** ya da beş PV'den biri (piyasa, S1–S3, beklenen) - PV yazılınca oran onu veren
  orandır (PV'nin kendi eğrisinde; beklenen PV senaryo olasılıklarıyla), diğer PV'ler o orandan. Yazılan PV aynen kalır,
  hesaplananlar sayfadaki gibi 1 TL'ye yuvarlıdır; kendi sabit oranı yazılı dönemler aynen kalır. Silince oran yine par.
* **USD · FOMC**: **Pencere OIS (elle) %**, **Elle O/N %**, **Elle adım (bp)** ya da **Elle toplantı adımı %** (yüzde
  hücresi, *Toplantı adımı %* gibi: −100 bir adım indirim); **WIRP (manuel)** ya da **Fark WIRP (bp)** (fark yazılınca
  WIRP = İma O/N − fark/100). Toplantısıyla gider.
* **TÜM FORWARD / FRA** (OIS · PPK → *Tüm listeler*; masa, 24.11.2026: **"Ok"** - "FRA'yı yazınca başlangıç bacağı kalır
  (dolumunuz, boşsa piyasa par'ı), bitiş bacağı hesaplanır"): satırın **Bitiş bacağı dolum**'u ya da **Gerçekleşen
  FRA**'sı. FRA yazılınca başlangıç bacağı tutulur - **Başl. bacağı dolum**'unuz, boşsa başlangıç bacağının piyasa par'ı
  (Gerçekleşen FRA boş dolumu hep böyle okur) - ve bitiş bacağı dolumu o FRA'yı veren oran olur, (FRA·(P − O) +
  başlangıç·O) / P (*Gereken bitiş bacağı*'nın formülü; spot başlangıçta FRA'nın kendisi). Başlangıç dolumu ayrı bir
  girdidir: FRA yazılıyken değiştirirseniz bitiş bacağı yeniden hesaplanır. Bitiş dolumu yazılınca (ya da hiçbir şey
  yazılı değilken) Gerçekleşen FRA eskisi gibi hesaplanır. Hedef FRA sütunları (U:W) olduğu gibi kalır.

Yeni Bloomberg isteği yok; hiçbir şey yazılı değilken bütün sayılar eskisi gibidir.

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
(Near limit yakın bacağın fiyatıdır, değişmez). **FXswap+bp**, **Faiz %** ve **Fiyat** satırlarında seçim etkisizdir (OIS FRA
Bootstrap kalır, seçimin ipucu bunu söyler). OIS FRA sütununun başlığı eğriyi yazar (`OIS FRA · S2 · Hawkish`; satırlar farklı
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
valöründen sonra bitmiyorsa da satırın sayıları - OIS FRA, Hedef faiz, limitler, spread fiyatı, hedef − piyasa; hedef tipi
ne olursa olsun - boş kalır (sayfanın kendi FRA'sı orada 0, hedef faiz −%1,5 çıkıyordu) ve aynı uyarı çıkar; VİOP
sayfasında, Masa'nın özetinde ve launchpad'de aynı. Yardımcı tablo (`EK_VFRA`: liste, her
satırın tarihleri, S1–S3 iskonto faktörleri, dört eğrinin FRA'sı ve durumu) "Yardımcı tablolar"dadır.

**VİOP Target — Fiyat hedefi** (VİOP → Kontratlar → Target ve Masa'nın VİOP sekmesi; `VIOP!O331:Q338`). Target tablosu
hedef faizden uzak limit fiyatına gider: uzak limit = near limit · (1 + hedef faiz · gün / 360) / USD taşıma (near limit SHORT
satırda yakın kontratın ask'ı, LONG'da bid'i; gün iki kontratın günleri arası; USD taşıma = (1 + USD uzak · gün uzak / 360) /
(1 + USD yakın · gün yakın / 360)). **Hedef tipi** listesinde artık **Fiyat** da var: **Hedef değer**'e uzak kontratın fiyatı
yazılır (`51,10`), **Hedef faiz (360)** o fiyatın ima ettiği TRY faizidir: ((fiyat / near limit) · USD taşıma − 1) · 360 /
gün, sayfanın kendi uzak limit formülünün tam tersi (bir satırın kendi uzak limit fiyatı Fiyat tipiyle geri yazılınca aynı
hedef faizi verir). Satırın gerisi diğer tiplerdeki gibi bundan gelir: uzak limit (yazılan fiyat), spread fiyatı, hedef −
piyasa (bp), DV01; OIS FRA Faiz % satırındaki gibi Bootstrap'tır (FRA eğrisi seçimi bu satırda etkisiz). Sıfır ya da eksi
fiyat faiz vermez. Hedef faizin ipucu fiyatı, near limiti ve günü yazar; Masa özetinde hedef `Fiyat 51,1000` diye görünür.
Hedef değer fiyatı uzak limitin dört ondalığıyla gösterir (bp değerleri bir ondalıkla; aşağıda *Hedef değer tipinde okunur*).

**VİOP Target — iki yönlü** (masa, 24.11.2026: "tüm tablolar bu şekilde olmalı"; VİOP → Kontratlar → Target). Her satırda
**Hedef değer**, **Hedef faiz (360)**, **Uzak limit fiyatı**, **Spread fiyatı** ya da **Hedef − piyasa (bp)** yazılabilir:
hangisini yazarsanız o kalır, satırın diğerleri ondan hesaplanır (✎; son yazılan geçerli; `Delete` satırı boşaltır).
Uzak limit yazılınca hedef faiz o fiyatın ima ettiği faizdir (Fiyat tipinin tersi: near limit satırın yönüyle - SHORT'ta
yakın kontratın ask'ı, LONG'da bid'i); spread fiyatı yazılınca uzak limit = near limit + spread; hedef − piyasa yazılınca
hedef faiz = piyasa ima ff (yön) + fark. **Hedef değer satırın kendi Hedef tipindedir**, ne yazılırsa yazılsın: FRA+bp'de
OIS FRA'ya göre bp, FXswap+bp'de FX swap imaya göre bp, Faiz %'de faiz, Fiyat'ta uzak limit fiyatı. Tip sizin seçiminizdir:
bir fiyat yazmak tipi değiştirmez (değiştirseydi sonra yazılan Hedef değer başka bir şey demek olurdu); tipi değiştirirseniz
yazılan değer kalır, Hedef değer yeni tipte gösterilir. Hedef faizin ipucu faizin nereden geldiğini yazar. Kontrat adıyla
bulunur: vadesi geçen kontrat satırı yine "geçersiz" yapar, yazılan değer kendi hücresinde kalır; kontrat yeniden seçilince
satır ondan hesaplanır. Masa'nın VİOP sekmesindeki hedef şeridinden Hedef değer yazılabilir, diğerleri VİOP sayfasında
yazılır; Masa özeti bp hedef değerini (yazılan ya da hesaplanan) bir ondalıkla gösterir. Daha önce yazdığınız Hedef değerler aynen okunur
(saklandıkları yer değişir: `VIOP!AE331:AE338`; diğerlerinin yazılanları `AF:AI`, Yardımcı tablolarda). Geçici kopyada
satırın beşi de yazılabilir. Masa'nın TARGET şeridinin kopyasında yalnız Hedef değer yazılır; VİOP sayfasında satıra
başka bir değer (hedef faiz, uzak limit, spread fiyatı, hedef − piyasa) yazılmışsa o değer kopyada da durur ve satır
onunla karışık görünür: o satırı denemek için VİOP sayfasındaki Target'ın kopyasını kullanın (ya da oradaki değeri silin).

**VİOP Target — Hedef değer tipinde okunur** (masa, 25.11.2026: "VİOP target kısmında da faiz seçtiğim durumda decimalsiz
yazıyor"). Hedef değerin biçimini satırın **Hedef tipi** seçer: **Faiz %**'de faiz **iki ondalıkla** (`45` → `45,00`,
Hedef faiz'ten hesaplanan da), **Fiyat**'ta fiyat uzak limit fiyatının **dört ondalığıyla** (`51,05` → `51,0500`),
**FRA+bp** / **FXswap+bp**'de bp **bir ondalıkla**, yazılan da başka sütundan hesaplanan da (`-75` → `-75,0`, `40,5`;
uzak limit yazılınca hesaplanan `-1636,148629` → `-1636,1`). Tipi değiştirince aynı değer yeni tipin biçimiyle görünür.
Yalnız görünüş: değer, yazılan ve Ctrl+Shift+C bütün ondalıklarıyla kalır. VİOP sayfasında ve Masa'nın VİOP TARGET
şeridinde aynı; Masa özeti (*VİOP · TARGET*) hedefi aynı biçimle, virgülle yazar (`Faiz % 45,00`, `Fiyat
51,0500`, `FRA+bp -75,0`). Satırın diğerleri zaten okunaklı: hedef faiz ve piyasa ima `%` iki ondalık, near / uzak limit
ve spread fiyatı dört ondalık, hedef − piyasa tam bp.

**TRY faizleri iki yoldan: Bootstrap (Murex) ve PPK basamak** (`tto/ppkcurve.py`). Bir karşı taraf FRA fiyatlarının
"interpolasyon seçimine göre" değişebileceğini söyledi; masa TRY faizlerini iki yoldan yan yana görür:

* **Bootstrap (Murex)** — bugünkü eğri, Murex'in de MTM'i: OIS kotalarının par faizleri aylara göre doğrusal, çeyreklik
  bootstrap, ln DF günlere göre doğrusal (`Motor!C88:I130`, `BOOT_GUN` / `BOOT_LNDF`); offshore'da FX swap ima (≤9M, tek
  dönem basit ACT/360) ve XCCY (1Y–10Y, yıllık ACT/360 par) eğrisi (`Forward!AJ123:AN143`). Olduğu gibi okunur; listelerin
  ve blokların "Piyasa"sı, Trades'in MTM'i ve mevcut hiçbir sayı değişmez (Ayarlar'daki **Eğri interpolasyonu** Bootstrap'ta
  - varsayılan - iken; PPK basamak seçen kullanıcıda bunlar da PPK basamak olur, aşağıda).
* **PPK basamak** — toplantı tarihli basamak yöntemi: TLREF iki PPK toplantısı arasında sabit, toplantıda sıçrar. Biçimi PPK
  çözücüsünün ima patikasıdır ("MPC ima": `Motor!C4:L84`, hafta sonu / tatil terimi `Motor!F528:F4228` dahil - Masa'nın
  Tarih arası faiz bloğundaki MPC ima satırı onu böyle okur). **Kalibrasyon:** bootstrap'ın kurulduğu kotaların her biri
  (`Motor!A306:B321`, 1M … 10Y; OIS_MAIN'in 15M ve 21M'si kota değil, eğrinin kendi değeri - dışarıda) kendi
  konvansiyonuyla - 3 aya kadar tek dönem basit ACT/365, 6M'den çeyreklik ACT/365 par, bootstrap'ın kendi düğüm günlerinde -
  aynen yeniden fiyatlansın diye iki ardışık kotalı vade arasına sabit bir O/N kaydırma eklenir. Vade vade sırayla çözülür
  (bir kota yalnız kendi aralığına ve öncekilere bağlı; sekant, |par − kota| ≤ 1e-12). TLREF her aralığın içinde
  toplantılar arasında yine sabittir, kotalı vadede adımlanır. **Offshore PPK eğrisi:** aynı MPC ima biçimi (FX spot'undan
  görülen), offshore kotalar arasında sabit bir bazla aynı yolla kalibre edilir: TRYI tek dönem basit ACT/360, TRYSAQ n
  yıllık ACT/360 par (kuponları TRYSAQ 1 … n'in günlerinde; ilk eksik XCCY kotasında durur, sayfanın bootstrap'ı gibi).

İki eğri her kotalı vadede aynıdır; yalnız iki kota arasındaki aralığı nasıl böldüklerinde ayrılırlar - iki kotanın
arasındaki bir FRA'nın (12x15, 15x18 …) ya da kırık vadenin gördüğü fark budur; kotalı vadeleri birleştiren FRA (3x6, 12x18,
1Y1Y …) iki yolda da (neredeyse) aynıdır. Her aralığın kaydırması (bp) ve MPC ima'nın kotalardan kendi farkı sütun
başlıklarının ipucunda yazar. Nerede görünür (Bootstrap olduğu gibi, yanında PPK basamak):

* **OIS · PPK'nın FRA listeleri** (*EN İYİ 15 FRA*, *TÜM FORWARD / FRA*): **PPK basamak** (FRA'nın PPK basamak eğrisindeki
  değeri) ve **PPK − piyasa (bp)** sütunları; her satırın kendi ayları, listenin piyasasıyla aynı çeyreklik takvim ve gün
  sayımı (`OIS_MAIN!B336`'nın formülü: `(DF(M) − DF(N)) / Σ τ·DF`, Motor'un çeyreklik takvimi `D139:F178`) - fark yalnız
  eğriden. "Piyasa" başlığının ipucu "Bootstrap (Murex)" der; kova sütunları en sağda kalır.
* **Günlük İşlemler'in FRA girişi:** kotasyonda piyasa mid'inin (Bootstrap) yanında "PPK basamak mid" ve kutuların sonunda
  **Piyasa mid · PPK basamak** ile **Mid'e göre · PPK (bp)** (+ mid'den iyi, − kötü). Kaydedilen işlemin maliyeti ve MTM'i
  Bootstrap'la kalır.
* **Masa → Forward fiyatlama → KIRIK VADE & KARŞILIK:** **PPK basamak** ve **PPK − piyasa** sütunları - forward outright /
  puan, basit (ACT/360, ACT/365), O/N ve XCCY satırları PPK biçimli offshore eğriden, OIS satırı PPK basamak eğrisinden;
  bloğun kendi valörü, kupon takvimleri (valörden geriye 3M / 12M) ve gün sayımıyla (yardımcı `BK170:CC234`). Fark forward
  satırlarında puan, oranlarda bp. Geçici kopya kendi valörüyle hesaplar. Kotalı vadede (XCCY 1Y'nin, 2Y'nin günü) iki yol
  aynı, kotalar arasında (spot + 2Y3M gibi) ayrı; bloğun piyasası olmayan satır (eğrinin bittiği vade) PPK'da da boştur.
* **OIS · PPK → En iyi işlemler → İnterpolasyon · Bootstrap (Murex) ve PPK basamak** (`tto/interpchart.py`; *EN İYİ 15
  FRA*'nın hemen altında, sayfa genişliğinde grafik): iki yolun iki kotalı vade arasını nasıl böldüğü, çizgiyle.
  **Düz çizgiler O/N forward** - spot'tan gün gün bir günlük basit faiz, (DF(t) / DF(t + 1) − 1) · 365 (offshore'da 360),
  basamak çizgisi: Bootstrap'ta Motor'un düğümleri (0, 1, 2, 3, 6 … 120 ay) arasında sabit (eğrinin kendi ln DF eğimi), her
  düğümde basamaklı; PPK basamak'ta TLREF kaydırmasıyla toplantılar arasında sabit, toplantının ertesi iş günü ve kotalı
  vadede basamaklı. **Kesik çizgiler 3 aylık FRA şeridi** (0x3, 3x6 …, her FRA kendi çeyreğinde): FRA listelerinin Piyasa'sı
  ve PPK basamak sütunu, aynı çeyreklik takvim ve gün sayımıyla. Kotalı vadeler (1M … 10Y; 15M, 21M kota değil) üstte
  adlarıyla açık kesik çizgi, toplantılar eksende turuncu çentik; Bootstrap mavi, PPK basamak turuncu. Altında şerit
  tablosu - her FRA bir sütun: iki yol (%) ve **PPK − Bootstrap (bp)**, listenin "PPK fark"ıyla aynı - ve tek satırda en çok
  ayrıldıkları FRA'lar. Başlıkta **1Y / 3Y / 10Y** (açılışta 3Y: farklar orada) ve **OIS / Offshore** (Forward'daki offshore
  eğri - FX swap ≤9M + XCCY - ile PPK biçimli offshore eğri, ACT/360; son offshore kotadan sonrası iki eğride de uzatmadır,
  satırı söyler): sunucu her yolu birden gönderir, tık beklemeden çizilir; seçim her kullanıcının kendi tarayıcısında kalır.
  Fare bir güne gelince o günün iki O/N'i, iki FRA'sı (adıyla: 12x15 …) ve farkları (bp); bir kotanın ya da toplantının
  yanında onun gününe oturur ve adını söyler. **Nasıl okunur:** çizgiler yalnız kotalı vadeler arasında ayrılır; kotalı
  vadede (dikey çizgi) iki eğrinin iskonto faktörü aynıdır, bu yüzden bir aralıkta PPK basamak bootstrap'ın altında kalırsa
  aynı aralığın öbür yanında üstüne çıkar ve iki ucu kotalı vade olan FRA (0x3 … 9x12, 12x18) iki yolda aynıdır. Kayıtlı
  günde (03.11.2026) 3Y'de en büyük farklar 15x18 +78,8 bp, 12x15 −70,7 bp (12x18 aynı) ve 21x24 −62,5 bp; 10Y'de
  84x87 −106,7 bp. Launchpad'e ve yan panele 3Y OIS olarak gider.
  **DF** (başlıktaki üçüncü seçim, *Faiz / DF*; masa, 18.11.2026: "Bu enterpolasyondaki DF farkları da bir grafikte bana
  gösterilmeli"): aynı ufuk ve eğride iki yolun **iskonto faktörü farkı, gün gün** - **PPK basamak / Bootstrap − 1 (bp)**,
  turuncu; Bootstrap'ın kendi çizgisi 0'da, mavi. Göreli fark seçildi, mutlak fark (`DF_PPK − DF_Bootstrap`, 10⁻⁴
  biriminde) değil: o güne düşen bir nakit akışının PPK basamak'ta bugünkü değeri ne kadar fazla (+) ya da az (−) -
  değerinin bp'si; her vadede aynı ölçek (mutlak fark DF küçüldükçe küçülür, 10Y'de DF ~0,07: aynı fark 1M'dekinin
  ~14'te biri görünürdü) ve yaklaşık −(sıfır kupon faizi farkı × yıl). Kotalı vadeler dikey çizgi (ipucunda iki DF ve fark), toplantılar çentik; altındaki
  tabloda kotalı vadelerde iki DF ve farkı. **Kotalı vadede**: nakit akışlarının hepsi kotalı vadeye düşen kotada fark 0'dır
  - sıfır kuponlu kota (OIS 1M–3M, TRYI, XCCY 1Y) ve kuponları kotalı vadelere düşen kota (OIS 6M–1Y, XCCY 2Y–5Y) -; arada
  kotasız kupon tarihi olan kuponlu kotada küçüktür (OIS 18M'den: 15M, 21M … kota değil; iki eğri par faizi aynen fiyatlar,
  kuponları başka böler). Son kotadan sonrası çizilmez (iki eğride de uzatma; offshore'da kayıtlı günde XCCY 5Y'den
  sonrası), satırı söyler. Kayıtlı günde 3Y OIS'te PPK basamak'ın DF'i Bootstrap'ınkinden en çok +17,49 bp yukarıda
  (21.01.2028), −14,97 bp aşağıda (04.08.2028); kotalı vadede 1M … 1Y 0, 18M −1,47, 2Y −0,27, 3Y +2,40 bp; 10Y OIS'te en
  büyük +32,39 bp (06.02.2034). Fare bir güne gelince o günün farkı (bp). Seçim tarayıcıda kalır (önceki "3Y|OIS" seçimi
  Faiz'le açılır). Günlük farklar bir kez hesaplanır (1Y ve 3Y, 10Y'ninkilerin ilk günleri); her güne bir nokta olduğundan
  grafiğin sayfaya giden verisi kayıtlı günde ~90 KB'tan ~250 KB'a çıkar.

Eğriler kullanıcının (ve geçici kopyanın) kendi hesabından kurulur: hesabın bir durumu için bir kez (~30 ms) ve tutulur;
kurarken okunanlar değişince tablo (ve grafik) yeniden yapılır.

**Eğri interpolasyonu: her kullanıcının kendi ayarı** (Ayarlar → *Eğri interpolasyonu · kotalı vadeler arası*; "Ayarlardan da
PPK basamak kısmını, tüm interpolasyonları değiştirebiliyor olmam lazım"). TRY eğrileri kotalı vadeler arasında iki yoldan
biriyle okunur: **Bootstrap (Murex)** - bugünkü eğri, varsayılan - ya da **PPK basamak**. Seçim kişisel bir girdidir
(`EK_INTERP!B2`; "Girdilerimi sıfırla" Bootstrap'a döndürür): masanın ortak hesabı ve başkalarının ekranları Bootstrap'ta
kalır. PPK basamak seçen kullanıcının her sayfasında üst şeritte **"Eğri: PPK basamak"** rozeti durur (ipucunda ne olduğu ve
neyin Bootstrap'ta kaldığı; tıklayınca Ayarlar) - meslektaşların farklı sayıları karıştırılmasın. Değişiklik kaynakta,
çalışma kitabının kendi formüllerindedir:

* **Motor'un 42 düğümü:** her düğümün par faizi (`Motor!F89:F130`, kotalardan aylara göre doğrusal) PPK'da PPK basamak
  eğrisinin o düğümdeki par faizi olur - `EK_INTERP!C11:C52`'deki PPK iskonto faktörlerinden Motor'un kendi takvimi ve gün
  sayımıyla (1–3 ay tek dönem ACT/365, sonra 3 ay düğümünden çeyreklik par). Motor'un bootstrap'ı bu iskonto faktörlerini
  aynen verir (~1e-15): annuity'ler, ln DF'ler, çeyreklik kopya (`O139:O178`: OIS_MAIN, Masa), `BOOT_GUN` / `BOOT_LNDF` /
  `BOOT_PAR` okuyan her sayfa (OIS · PPK, Masa, Forward, DV01, Carry & Roll, VİOP, DİBS RV / Tüm Kâğıtlar, Manuel Tahvil,
  Borsa Swap'ın OIS mid'i) onu izler; kotalı her vadenin par'ı kotasıdır (1e-10). 1Y'ye kadar her düğüm kota (ya da kuponu)
  olduğundan iki yol orada aynıdır; 15M, 21M, 27M … ve onları kupon olarak okuyan sonraki düğümler ayrılır. Kotaya göre kova
  DV01'i (`Motor!T:…` +1 bp "çadır") PPK'da PPK eğrisinin par faizlerine aynı çadırla uygulanır - eğri her kova için yeniden
  kalibre edilmez.
* **Düğümler arası:** her okuyucu bugünkü gibi ln DF'yi günlere göre doğrusal okur. Motor'un düğümleri 1–3 ay aylık, sonra
  çeyreklik olduğundan çeyrek içindeki kırık bir tarih PPK eğrisini çeyreğin iki düğümünde görür, aradaki her toplantı
  basamağını değil; günlük tam PPK değerleri PPK sütunlarında kalır (OIS · PPK'nın FRA listeleri, Masa'nın kırık vade bloğu,
  Günlük İşlemler'in FRA kotasyonu). Çeyreklik takvimdeki FRA'lar (12x15 …) tamdır: PPK'da listenin piyasası PPK basamak
  eğrisinin FRA'sıdır.
* **İki yolu yan yana gösterenler PPK'da:** FRA listeleri ve Masa'nın kırık vade bloğu PPK kullanıcısında piyasa sütununu
  (artık PPK basamak) gerçek **Bootstrap (Murex)** sütunuyla yan yana gösterir, fark yine **PPK − Bootstrap** (Bootstrap
  kullanıcısının gördüğü fark); "Piyasa" başlığının ipucu PPK der. Bu görünümlerin (ve eğri grafiğinin) eğrileri her zaman
  gerçek bootstrap'ı okur: PPK kullanıcısının hesabında da eğri Bootstrap'a alınarak (`Service._try_curves`).
* **Offshore eğri** (`OFF_GUN` / `OFF_LNDF` / `OFF_SL`: Masa'nın kırık vade bloğu, DİBS RV'nin FX swap ASW'si, Borsa Swap'ın
  offshore mid'i, Trades'in USDTRY forward'ları): düğümlerinin hepsi kota ve XCCY kuponları düğümlerde - PPK onlarda
  Bootstrap'la aynı; PPK'da adlar `EK_INTERP!I:K`'yı okur: PPK biçimli offshore eğri (MPC ima + kotalar arasında sabit baz)
  her toplantı basamağında ve her kotada düğümle (son düğümden sonra son eğimle). Bootstrap'ta adlar Forward'ın kendi
  aralıklarıdır.
* **DİBS ASW kitabının bugünkü eğrisi** (`ASW!BT65:DI65`): kullanıcının seçimi o kitaba da yansır (`EK_INTERP!B2`, dashboard
  yazar); PPK'da ln DF düğümleri TRY kitabının MPC ima patikasının ASW kitabının kendi kotalarına (`C65:R65`) ve düğüm
  günlerine kalibrasyonudur. Geçmiş satırları ve FX swap ASW sütunu (kendi eğrisi) Bootstrap'ta kalır - FX swap ASW'de yalnız 18A noktası
  (EK_FX) kullanıcının ayarını izler.
* **Trades** (masanın kararı, "Trades MTM de anahtara bağlansın"): MTM, carry, "Kupon", **Kuponlar** penceresi ve günlük /
  haftalık / toplam K/Z bakan kullanıcının eğrisiyle (araç çubuğunda "Eğri: …"). Masanın paylaşılan kayıtları iki eğride de
  alınır: **MTM yenile** ve günlük **kapanış kaydı** her işlemi Bootstrap ve PPK basamak ile değerler, herkes kendi ayarınınkini
  görür; iki eğri alınmadan önceki bir kayıt (yalnız Bootstrap) Bootstrap gösterilir ve PPK kullanıcısına söylenir (MTM
  yenile'ye kadar; eski kapanışlardan sayılan K/Z'ye eğri farkı karışır). Kodda tek anahtar: `tradebook.FOLLOW_CURVE`
  (False: herkesin Trades'i Bootstrap'ta).
* **Bootstrap'ta kalanlar:** Günlük İşlemler (masanın kaydı: kotasyon, mid, "Mid'e göre", DV01 - FRA'da PPK mid yanında, eskisi
  gibi), kullanıcısız çalışan her şey - Trades'in hedef / stop alarmları, masa alarmları, quant paketi ve İşleme al, tarihçe ve
  PPK fiyatlama geçmişi, ısınma, Bugün -, masanın ortak hesabı ve başkalarının ekranları. Kişisel İzleme kalemleri ve
  alarmları kişisel girdisi olan herkeste olduğu gibi kullanıcının hesabıyla okunur: bağlıyken onun eğrisi, yokken masanınki
  (Bootstrap). Forward sayfasının kota faizlerini doğrusal okuyan tabloları (offshore `I22:K22`, VİOP, RET) eğri okumaz;
  "OIS" eğrisi Motor'un düğümlerindeki zero faizleri okur (izler).
* **PPK hücreleri:** `EK_INTERP`'teki PPK hücrelerini dashboard ortak hesaptan (Bootstrap'taki hesap: PPK kendini okumaz)
  ppkcurve ile doldurur: bir PPK kullanıcısının hesabı istendiğinde ve yalnız okuduklarından biri (kotalar, MPC ima, takvim,
  spotlar) değiştiyse yeniden (~50 ms; kimse PPK'da değilse hiç). Bootstrap'taki formüller iç içe IF'le bu hücreleri hiç
  okumaz: doldurulmaları Bootstrap kullanıcısında hiçbir şeyi yeniden hesaplatmaz (ortak hesapta 0 değerlendirme). Kendi
  kotasını ("Elle değer") ya da TLREF'ini yazan PPK kullanıcısının PPK hücreleri kendi hesabından kendine kurulur (girdisi
  sayılmaz, listelenmez). PPK eğrisi kurulamazsa (kota, MPC ima yok) kullanıcı Bootstrap'ta kalır, Ayarlar ve rozet söyler.

**Eğri noktaları: masanın listesi** (Ayarlar → *Eğri noktaları · OIS ve offshore*, `tto/curvepoints.py`; "Bu enterpolasyon
noktalarına Ayarlar'dan ekle / çıkar yapabilmeliyim, yanlarına da ne olduklarını not alabilmeliyim. Ama PPK'lar her zaman
olmalı. PPK tarihleri güncellenince o da güncellenmeli"). Her TRY eğrisi - **OIS** ve **Offshore** - bir nokta listesinden
kurulur; liste masanındır: herkes görür, yalnız yöneticiler değiştirir (herkesin eğrisi değişir), her değişiklik kayda
geçer (kim, ne zaman, ne: tablonun altında son 12'si). Bir nokta:

* **vade ya da tarih** (1W, 1M, 18M, 2Y3M … ya da gg.aa.yyyy); **tür ve kuralı**: **OIS** (3 aya kadar tek dönem basit
  ACT/365, sonra çeyreklik ACT/365 par - Motor'un ızgarasındaki bir vadede Motor'un çeyreklik günleri, ızgara dışında
  kuponlar vadeden geriye, Masa'nın kırık vade bloğu gibi), **FX swap ima** (tek dönem basit ACT/360), **XCCY** (yıllık
  ACT/360 par, kuponlar vadeden geriye sayılır, kısa dönem başta: "18 ayda 6 ay + 12 ay, sondan başlayıp"). Tarihler
  Fiyatlama'nın kuralıyla: vade `WORKDAY(EDATE(spot, ay) − 1, 1, tatiller)`, kuponların k'ıncısı geriye (ay − k·adım)'ın
  vade günü (bir tarihte `EDATE(tarih, −k·adım)` iş gününe); OIS ve XCCY TRY tatilleriyle (Motor; Masa'nın kırık vade
  bloğu da böyle), FX swap valörü TRY + USD tatilleriyle (`EK_TATIL!B:C`); gün spot'tan (OIS: `OIS_MAIN!B2`, offshore:
  `Forward!I2`);
* **kaynak**: **Çalışma kitabı** (varsayılan noktalar: kitabın kendi kota hücresi), **Elle** (masanın girdiği oran, yüzde;
  sonradan değiştirilebilir), **Bloomberg** (bir ticker: yeni bir canlı abonelik - aşağıda) ya da **Hesaplanan** (eğriden
  okunur: o vadede noktanın kuralıyla par, sıfır kupon faizi (yıllık bileşik ACT/365, EK_FX'inki) ve iskonto faktörü,
  bakanın interpolasyon ayarıyla - Bootstrap'ta adların verdiği eğri, PPK basamak'ta ppkcurve'ün PPK eğrisi: Fiyatlama'nın ve
  EK_FX'in okuduğu eğriler; eğriye bilgi eklemez - eğrinin uydurulduğu bir nokta değildir);
* **not** (ne olduğu), **ekleyen · tarih** (ipucunda son değiştiren), **açık / kapalı**: kapatmak yumuşak silmedir - satır
  notuyla listede kalır, eğri onun üzerinden interpolasyon yapar.

**Varsayılan liste bugünkü noktalardır** ve onunla her sayı eskisi gibidir: OIS'te OIS_MAIN'in kotalı vadeleri 1M … 10Y
(Motor'un kota kopyası `A306:B321`; 15M ve 21M kota değil), offshore'da Forward'ın TRYI 1W … 9M ve TRYSAQ 1 … 10 satırları
(`AJ123:AN143` ve `C123:K134` onları böyle okur) ve **18M · XCCY · hesaplanan** (not: "1Y–2Y XCCY'den, 6M + 12M kupon,
sondan"; masa: "18M hesaplanacak, gerçek kotasyon girilmeyecek"): değeri `aswfx.point_18m`'in kendisidir - EK_FX'in
18M'ini veren fonksiyon -, par'ı Fiyatlama'nın XCCY 18M mid'i (kayıtlı günde %39,5879 Bootstrap / %39,3752 PPK basamak),
Bootstrap'ta iskonto faktörü Masa'nın kırık vade bloğunun o tarihte okuduğu. Varsayılan
listede hiçbir okuyucu listenin hücrelerine bakmaz (iç içe IF): Motor ve offshore adlar kendi formülleri - karşılaştırma
betiğiyle 0 açıklanmamış fark. **PPK toplantıları her zaman listededir**: Motor'un toplantı tablosundan (PPK toplantı
takvimi) salt okunur gri satırlar, iki tabloda da günlerine göre noktaların arasında ("PPK toplantısı · takvimden"); PPK
basamak listede ne olursa olsun orada basamaklanır, takvim değişince satırlar kendiliğinden değişir; kapatılamaz,
notlanamaz.

**Liste farklıyken iki yöntem de listeden kurulur** (`ppkcurve.list_curves`): **Bootstrap** masanın kendi yöntemiyle -
OIS'te Motor'unki (açık noktaların par faizi aylara göre doğrusal, Motor'un 42 düğümünde, uçlarda düz; Motor'un kendi
bootstrap'ı; ızgara dışı bir nokta - bir tarih, 2Y1M - dashboard'un eğrisinde ayrıca düğüm, Motor'da çeyreklik
düğümlerinde okunur), offshore'da her nokta bir düğüm (ln DF günlere göre doğrusal, Forward'ın eğrisi gibi; kuponu bir
düğümde değilse eğriden okunur, nokta aynen fiyatlanır); **PPK basamak** MPC ima patikası, listedeki her noktaya aynen
oturur. Çalışma kitabına aynı yoldan girer (`EK_INTERP`, dashboard yazar): `N3` / `N4` OIS / offshore listesi farklı,
`N11:N52` Motor'un düğüm par'ları (Motor!F: `IF(PPK, …, IF(liste, N, kendi formülü))`), `Q:S` offshore düğüm tablosu
(`OFF_GUN` / `OFF_LNDF` / `OFF_SL` PPK tablosundan sonra onu okur); PPK hücreleri listeden kurulur (offshore PPK tablosunda
her noktanın kupon günleri de düğüm). Masanın hücreleri ortak hesaptan (onları okuyan; kurmak yalnız noktaların kotalarını,
Motor'un düğüm günlerini, spotları ve takvimleri okur) piyasa her değiştiğinde ve bir hesap istendiğinde güncellenir;
noktalardan birinin kotasını kendisi yazan ("Elle değer") kullanıcının liste hücreleri kendi hesabından kendine kurulur.
OIS listesi farklıyken Motor, `BOOT_PAR`, FRA listeleri, Masa, Forward, DV01, Trades … listeyi izler; offshore listesi
farklıyken offshore adları okuyan her şey (Masa'nın kırık vade bloğu, DİBS RV FX swap ASW'si, Borsa Swap'ın offshore mid'i,
Trades'in USDTRY forward'ları, EK_FX'in 18M'i). Grafikteki kotalı vade işaretleri listeden gelir. **Fiyatlama** listenin
eğrileriyle fiyatlar; DV01 kovaları listenin bilgi taşıyan açık noktalarıdır (çalışma kitabı kotası, ticker, elle) - her biri
+1 bp, eğri listenin yöntemiyle yeniden (OIS: `ppkcurve.list_ois_curve`, offshore: `ppkcurve.bootstrap`; PPK'da kalibrasyon
yeniden); hesaplanan ve PPK satırları kova değildir (elle bir 15M OIS noktası: 15M swap'ının DV01'i 1Y ile 18M arasında
bölünmek yerine kendi kovasında). Varsayılan listede Fiyatlama'nın her sayısı eskisi gibidir. Ayarlar'daki
*Eğri interpolasyonu* durumu liste farklıyken "eğri noktaları masanın listesinden" der.
**DİBS ASW listeyi izlemez:** kendi kotaları (`ASW!C65:R65`, kendi ticker'ları) ve günlük geçmiş satırları (her günün
kapanışından eğrisi) var; liste TRY kitabının kaynaklarını (OIS_MAIN, elle girilen, ticker) gösterir, geçmişi yoktur -
bugünkü eğri listeyi izleseydi geçmişle bugün ayrı eğrilerden olurdu. PPK basamak seçimi ASW'de eskisi gibidir (MPC ima,
ASW'nin kendi kotalarına kalibre). Tarihçe ve PPK fiyatlama geçmişi de listeyi izlemez (her günün kendi kapanışları,
çalışma kitabının kendi formülleriyle).

**Bloomberg ticker'lı nokta:** Bloomberg'e yeni bir istektir; kaydetmeden önce maliyeti söylenir ve onay istenir
(onaysız hiçbir şey kaydedilmez, Bloomberg'e hiçbir şey sorulmaz). Söylenen: 1 canlı ticker, MID / BID / ASK - ilk değer bir
referans isteğiyle, **3 veri noktası** (dashboard her açıldığında yeniden 3); sonra canlı akış, Bloomberg'in günlük sınırına
sayılmaz; abonelik akmazsa alan başına en sık 2 dakikada bir yeniden sorulur (en kötü günde ~2.160 veri noktası); canlıda
bugüne kadar kullanılan ve dashboard'un günlük koruması (400.000). Onaylanınca ticker `EK_INTERP!U10:U29`'daki bir yuvaya
yazılır (en çok 20), değeri MID, yoksa BID / ASK ortası (yüzde); kapatılınca yuva boşalır, yeniden açmak yine onay ister.
Tarihçeye girmez (yeni geçmiş isteği yok).

**Fiyatlama: kırık vade, DV01 kovaları, NPV** (TRY Faiz → *Fiyatlama*, menüde OIS · PPK'nın hemen altında; `tto/pricing.py`;
masa: "Kırık vade fiyatlamayı da açalım. Bir fiyatlama sekmesi olsun, buradan asseti ve vadeyi seçtiğimde fiyat, DV01'lar
bucket bucket olarak, fiyat girdiğimde de NPV'yi vermeli"). Bir enstrüman, istenen başlangıç ve vadede, TRY eğrileriyle iki
yoldan fiyatlanır - kullanıcının kendi **Eğri interpolasyonu** ayarı önde, öbürü yanında. Girdiler: enstrüman, başlangıç /
vade (`1Y`, `18M`, `2Y3M`, `3A`, `12` (ay), `2W` ya da tarih), yön (PAY / RECEIVE; FX'te AL / SAT), büyüklük (nominal TL -
FX'te döviz tutarı - ya da DV01 $) ve isteğe bağlı fiyat, **Fiyat tipi**yle: **Faiz** (`35,10` = %35,10), **NPV TL**, **NPV $**
ya da **Peşin bp**; FX'te **Outright**, **Puan**, **NPV TL** ya da **NPV $**.

* **Enstrümanlar** (konvansiyonları sayfanın altında da yazar):
  * **TRY OIS** (spot ya da ileri başlangıçlı): sabit ↔ TLREF, ACT/365; 3 aya kadar tek ödeme, daha uzunda çeyreklik -
    kuponlar vadeden geriye sayılır, kısa dönem başta (Masa'nın kırık vade bloğunun takvimi). Başlangıç ve vade OIS
    spot'undan (`OIS_MAIN!B2`), TRY tatilleriyle; spot'tan kotalı vade Motor'un çeyreklik takvimidir, her kota kendi
    vadesinde kendini verir.
  * **FRA** (OIS forward'ı): başlangıç × bitiş, ikisi de spot'tan (`12` ve `15`, `1Y` ve `18M` ya da tarih; tek kutuya
    `12x15` yazılabilir). Çeyreklik takvimde OIS · PPK'nın FRA listesiyle aynı sayı: Bootstrap'ta listenin piyasası, PPK'da
    PPK basamak sütunu.
  * **XCCY**: TRY sabit, yıllık ACT/360 ↔ USD değişken (par'da: offshore TRY eğrisi çapraz kur eğrisidir). Kuponlar vadeden
    geriye 12'şer ay, **kısa dönem başta** ("18 ayda 6 ay + 12 ay olarak kupon ödemesi yapılıyor, sondan başlayıp"): 18M =
    6A + 12A, 2Y3M = 3A + 12A + 12A. Offshore eğride (FX swap ≤9A + XCCY 1Y–10Y), günler FX spot'undan (`Forward!I2`);
    sayfa ödeme takvimini (dönem başı, ödeme, gün, τ, iki eğrinin DF'i, annuity) gösterir.
  * **FX forward** (USDTRY, EURTRY): F = S · DF_TRY(spot) / DF_TRY(valör) / (1 + r · gün/360) - offshore TRY eğrisi, USD
    (EUR) OIS faizi valöre günlere göre doğrusal; outright ve puan. USDTRY'de Masa'nın spotu (`MASA!H2`): kırık vade
    bloğunun forward satırı. Valör paritenin ortak takviminde (TRY + USD / EUR).

  Vade tarihle yazılırsa kuponlar o tarihten geriye sayılır (bloğun yardımcısının kuralı: `WORKDAY(EDATE(T, −3k) − 1, 1)`);
  tenörle yazılırsa spot'tan ay olarak (her tarih iş gününe).
* **Çıktılar:** iki eğride **mid** (FX'te outright ve puan) ve farkı (bp / puan); **büyüklük**: DV01 yazılınca nominal
  OIS_MAIN'in kuralıyla (`DV01 · USDTRY / (annuity · 0,0001)`, 5 mn TL'ye yuvarlı; FX'te forward'ın 1 bp'lik değişiminin
  bugünkü değeriyle, 1.000'e yuvarlı); **DV01 kova kova** ($/bp): OIS ve FRA'da masanın kovaları (ON, 1W, 2W - eğrinin
  orada kotası yok, riskleri 1A kovasında - ve 1M … 10Y), XCCY ve FX forward'da offshore eğrinin kotaları (TRYI 1W … 9M,
  XCCY 1Y …); iki eğri yan yana, toplam = kovaların toplamı. **Fiyat yazılınca NPV** (TL ve $) ve fiyat − mid (bp; FX'te
  puan).
* **Kovaların kotası** (masa, 24.11.2026: "Bu fiyatlama kısmına bunları ayırdığımızda denk gelen faizleri de yazalım"):
  kova tablosunda "Kova"nın hemen yanında her kovanın **kotası** - kovanın +1 bp'sinin kaydırdığı piyasa kotası, hedge'in
  yapılacağı faiz. OIS ve FRA'da **OIS kotası**: OIS_MAIN'in kotası, Motor'un bootstrap'ının okuduğu (`Motor!A306:B321`;
  1Y `OIS_MAIN!B14`) - Eğri noktaları listesi varsayılandan farklıysa listenin noktası. XCCY ve FX forward'da **Offshore
  kotası**: Forward'ın TRYI mid'i (FX swap ima, tek dönem basit ACT/360) ya da TRYSAQ mid'i (yıllık ACT/360 par). İki eğri
  karışmaz: offshore kovada hiç OIS kotası yoktur. ON / 1W / 2W'de kota yok: "–". **Tek sütun**: iki eğri de her kotayı
  kendi vadesinde aynen verir (Bootstrap kuruluşu gereği, PPK basamak kalibrasyonuyla; kayıtlı günde 16 OIS ve 14 offshore
  kotada en büyük fark 3·10⁻¹⁰ bp), kota iki DV01 sütununun ikisi için de aynıdır. Toplu fiyatlamada kova yok (DV01 annuity
  kuralıyla), kota da yok. Yeni Bloomberg isteği yok: kotalar eğrilerin zaten kurulduğu kotalar.
* **DV01 nasıl:** her kotanın +1 bp'sinde pozisyonun bugünkü değerinin değişimi; + = faizler yükselince kazanır (pay,
  döviz alış: Günlük İşlemler'in ve DV01 Risk'in işareti). Eğri aynı yöntemle yeniden kurulur: **Bootstrap**'ta Motor'un
  kendi kova kaydırması (`Motor!T86`, "her kota +1bp bootstrap": kota +1 bp, düğümlerin par'ı aylara göre doğrusal yeniden,
  bootstrap yeniden - Motor'un ΔlnDF sütunlarıyla birebir); **PPK basamak**'ta kalibrasyon yeniden (MPC ima aynı; o kotanın
  ve sonraki aralıkların O/N kaydırması yeniden çözülür, öncekiler aynı kalır); offshore'da FX swap / XCCY bootstrap'ı (PPK'da
  offshore kalibrasyonu) yeniden. Fiyat yazılıysa o fiyattaki, yoksa mid'deki pozisyonun riski. Vadeden sonraki kovalar 0;
  bir FRA'nın riski iki ucunun kovalarında (12x15 PAY: 1Y −, 18M +). Kırık vadede kovaların toplamı DV01'den biraz
  ayrılabilir: kotalar 1 bp kayınca o enstrümanın fiyatı tam 1 bp oynamaz (XCCY 2Y3M'de ~%5: kısa uç FX swap, uzun uç XCCY).
* **NPV:** pozisyonun yazılan fiyattaki bugünkü değeri (eğrinin spot'una iskontolu), **+ = lehine** (Günlük İşlemler'in
  "Mid'e göre"si gibi: mid'in altında PAY, üstünde RECEIVE; FX'te mid'in altında AL, üstünde SAT). Swap'larda yanında
  **Peşin (bp)** = NPV / nominal · 10.000.
* **NPV'den faiz** (masa, 24.11.2026: listedeki 14 tek yönlü hesaptan "1-2-3-4-5-6-7-8-11-11-13" - 4. madde: NPV (TL ya da $)
  ya da bp peşin yazınca sabit faiz, ve vade listesini tek seferde fiyatlayan bir kutu). Fiyat tipi NPV TL, NPV $ ya da
  Peşin bp iken yazılan sayı faiz değil NPV'dir (+ = lehine, NPV gibi; `1.000.000`, `-250k`, `2,5m`; peşinde `25` bp ya da
  nominalin yüzdesi `%0,5` = 50 bp) ve **o NPV'yi veren sabit faiz eğrinizde çözülür** - NPV'nin tam tersi: K = ((DF(başlangıç)
  − DF(vade)) − NPV / (yön · N)) / Σ τ·DF (yön PAY +1, RECEIVE −1); FX forward'da K = F − NPV / (yön · tutar · DF(valör)).
  Sayfa çözülen faizi büyük karoda gösterir ("Faiz ← NPV TL · Bootstrap (Murex)"; öbür eğrinin aynı NPV için faizi ipucunda);
  NPV, NPV $, Peşin, DV01 kovaları ve Fiyat − mid **o faizdedir** (faizi elle yazmışsınız gibi). NPV $, `OIS_MAIN!D2`'deki
  USDTRY ile TL'dir. Peşin, swap'ın size değeridir: + peşin karşılığında bu tutarı siz ödersiniz.
* **Toplu fiyatlama** (sayfanın altındaki kutu): her satıra bir enstrüman - vade (`2Y3M`, `18M`, `15`, tarih), başlangıç ×
  bitiş (`12x15`, `1Yx18M`) ya da iki tarih (`04.05.2027 04.05.2028`; arada sekme, `;` ya da ` - ` de olur); FX forward'da
  valör - ve satırın sonunda isteğe bağlı fiyat, yukarıdaki Fiyat tipiyle (`2Y 38,50`; NPV TL seçiliyse `2Y -1m`). Önce bütün
  satır enstrüman olarak okunur (`2Y 3M` = 2Y3M; `1Y 18M` de tek vadedir, 2Y6M: ileri başlangıç `x` ile yazılır); fiyat tek
  kelimedir, vadeden sonraki çıplak sayı fiyattır (ay değil). "Fiyatla" (ya da Ctrl+Enter, kutudan çıkmak) her satırı yukarıdaki
  enstrümanın yönü ve büyüklüğüyle fiyatlar: iki eğride mid (FX'te outright), farkı, annuity (FX'te puan), nominal (DV01
  yazılıysa her satırın nominali o DV01'den), **büyüklüğün DV01'i** (N · annuity · 0,0001 / USDTRY, OIS_MAIN'in kuralı; + =
  faizler yükselince kazanır) ve fiyat yazılan satırda NPV TL / $, Peşin, Fiyat − mid - NPV / peşin yazılansa çözülen faiz.
  Satırlar **sayfanın eğrileriyle** fiyatlanır, satır için eğri yeniden kurulmaz (kova kova DV01 için satırı yukarıda
  fiyatlayın); TRY OIS ve FRA satırları OIS eğrisinde, XCCY ve FX forward satırları **offshore** eğride. Okunamayan satır kendi
  satırında nedenini söyler, öbürleri fiyatlanır; en çok 100 satır. Kutu kullanıcının, enstrüman başına saklanır; yukarıdaki
  enstrümanın hatası satırları durdurmaz.
* Fiyatlar canlı piyasayı izler (sayfa her güncellemede yeniden ister); girdiler kullanıcının kendi - hesabıyla saklanır,
  enstrüman başına (başka enstrümana geçip dönünce yazdığı yerinde; 24.11.2026'dan önce saklanan fiyat faiz olarak okunur,
  FX'te saklandığı tipte). Eğriler kullanıcının hesabından kurulur ("Elle
  değer"iyle); kova kaydırmaları kurulduklarından biri (kotalar, Motor'un düğümleri, MPC ima, FX spot'u) değişince yeniden
  yapılır (PPK'da ~0,15 sn, Bootstrap'ta ~2 ms), başka bir fiyat değişince değil.
* Kayıtlı günde (03.11.2026, spot 04.11.2026): 12x15 FRA Bootstrap %35,6684, PPK basamak %34,9610 (−70,7 bp); XCCY 2Y3M
  %40,6174 / %40,6292; USDTRY 18M forward 79,0537 (290.564,6 puan) - Masa'nın kırık vade bloğuyla aynı. XCCY 2Y'de offshore
  eğrinin 2Y düğümü Bloomberg'ün günüdür (04.11.2028, cumartesi), sayfanın vadesi iş günü (06.11.2028): mid kotadan ~1,3 bp
  ayrılır, sayfa bunu yazar.

**Swaption: TRY OIS swaption'ı, yalnız görüntüleme** (TRY Faiz → *Swaption*, menüde Fiyatlama'nın hemen altında;
`tto/swaption.py`, `/api/swaption`; masa: "Önce bir swaption sekmesi yapmanı istiyorum. Try ois için hesaplayacağız.
Vadeyi seçtiğimde günlük, yıllık bps vol ve % black vol çıkacak. Ben buraya vol girdiğimde bana delta gamma vega
hesaplayacak, veya rate opsiyonlarında ne greek'i varsa, bu vole göre implied rate vade sonunda ne olacak onu gösterecek,
breakeven rate'i hesaplayacak. Bu sadece görmek için olacak henüz buradan herhangi bir işlem yapılmayacak"). Avrupa tipi
bir swaption: opsiyon vadesi × swap vadesi seçilir (hazır düğmeler 1M 3M 6M 9M 1Y 2Y 3Y 5Y ve 1Y 2Y 3Y 4Y 5Y 7Y 10Y, ya da
yazılır: `18M`, `2Y3M`, `15`). Opsiyon vadesi + swap vadesi en çok 10 yıldır: TRY OIS eğrisi 10Y'de biter; aşanı sayfa
Türkçe sebebiyle reddeder, seçili vadeye göre fazla uzun swap düğmeleri soluk görünür. Buradan işlem yapılmaz, sunucuda
hiçbir şey saklanmaz: girdiler istekle gider, son girdiler yalnızca o tarayıcıda kalır. Aşağıdaki model, vol zamanı ve
varsayılanlar entegrasyonun seçimidir; masa değiştirebilir (`docs/desk-decisions.md`).

* **Dayanak** (masanın cevabı: "Fiyatlama gibi"): Fiyatlama'nın ileri başlangıçlı TRY OIS'i. Başlangıç OIS spot'undan
  (`OIS_MAIN!B2`, TRY listesiyle T+1) opsiyon vadesi kadar sonra, vade spot'tan opsiyon vadesi + swap vadesi kadar sonra:
  1Y × 2Y, Fiyatlama'da *TRY OIS 1Y × 3Y*'dir - forward'ı, annuity'si ve kuponları birebir aynı. Sabit ↔ TLREF, ACT/365,
  3 aya kadar tek ödeme, sonra çeyreklik; kuponlar vadeden geriye, kısa dönem başta. **Opsiyon, başlangıçtan önceki TRY
  iş günü sona erer.** F = swap'ın par'ı, A = annuity (Σ τ·DF), kullanıcının **Eğri interpolasyonu** ayarındaki eğride
  (Bootstrap (Murex) / PPK basamak); öbür eğrinin F'i ve A'sı yanında.
* **Model:** normal (Bachelier), F üzerinde, annuity A ile. Payer = F üzerine call, receiver = put:
  d = (F − K)/(σN·√T), payer = A·[(F − K)·Φ(d) + σN·√T·φ(d)], receiver = A·[(K − F)·Φ(−d) + σN·√T·φ(d)]; straddle
  ikisi. **% Black:** aynı payer primini veren lognormal vol (çözülür); yazılan % Black vol da aynı yolla normal vol'e
  çevrilir.
* **Vol zamanı:** T = piyasa gününden (kayıtlı günde 03.11.2026) opsiyon vadesine TRY iş günü / 252. Böylece
  bp/yıl = bp/gün · √252 tam olarak, günlük bp vol de günlük başabaş hareketidir. İskonto annuity'nin içindedir (eğrinin
  kendi ACT/365'i).
* **Vadeyi seçince çıkan vol** (masanın cevabı): **gerçekleşen vol**, dashboard'un kendi günlük kapanışlarından - aynı
  opsiyon vadesi × swap vadesi forward'ının günlük bp değişimlerinin örneklem standart sapması, son 20 / 60 / 120 / 250
  değişim (*Realized Vol · Carry* gibi; yıllık = günlük · √252). Her pencerede bp/gün, bp/yıl, % Black (bugünkü F ve
  strike'ta), kullanılan değişim sayısı (dolmayan pencere `*`), ilk ve son gün; 5'ten az değişimli pencere boş.
  * Geçmiş bir günün forward'ı **o günün kendi OIS spot'undan** tarihlenir ve o günün kapanışlarından Motor'un yöntemiyle
    kurulan Bootstrap eğrisinden okunur: sabit vadeli forward. Geçmiş günlerin tatilleri: listedeki tatiller ve TLREF'in
    fixlenmediği hafta içi günler (tarihçenin kuralı; liste yalnız ilerideki tatilleri tutar).
  * Bir gün, forward'ın ihtiyaç duyduğu bütün OIS vadeleri (vadesini okuyan Motor düğümünün kotasına kadar) o gün
    kapandıysa sayılır; sayfa hangi vadelerin gerektiğini ve hangilerinin kapanışı olmadığını yazar.
  * Geçmiş her zaman Bootstrap'tadır. Yeni Bloomberg isteği yoktur: kapanışlar tarihçenin. Her günün eğrisi bir kez
    kurulur, başka vadeler ve sayfa yenilemeleri onu yeniden kullanır.
* **Kullanılan vol:** varsayılan, 60 değişimlik gerçekleşen vol. Üç kutudan birine (bp/gün, bp/yıl, % Black) yazılan vol
  onun yerine geçer; öbür iki kutu onun karşılığını gösterir, **Gerçekleşen vol** düğmesi yazılanı siler. Gerçekleşen vol
  yoksa (geçmiş kısa ya da gereken vadelerin kapanışı yok) sayfa nedenini söyler; prim için vol yazılır.
* **İki yönlü** (masa, 24.11.2026: "tüm tablolar bu şekilde olmalı"): vol yerine tablodaki bir **prim** (payer, receiver
  ya da straddle'ın bp running, bp peşin ya da TL primi) ya da **başabaş** (payer, receiver; straddle'ın alt ve üst
  başabaşı) da kendi hücresine yazılabilir (hücreye tıklayıp yazın, Enter): o primi veren normal vol bulunur - ATM'de
  kapalı formül (bacak başına σN·√T/√(2π)), değilse tek boyutlu Brent - ve sayfanın gerisi o vol'den hesaplanır. Vol
  kutularından ve bu hücrelerden **son yazdığınız kalır** (kalın, ✎): piyasa değişince o prim aynen durur, vol ona göre
  değişir; öbür hücreler ve vol kutuları onun karşılığını gösterir. Hücreyi silmek (ya da **Gerçekleşen vol**) gerçekleşen
  vol'e döndürür. İçsel değerin altındaki (ya da ona eşit) bir prim için vol yoktur: sayfa içsel değeri söyleyerek
  reddeder. Eski istekler ve tarayıcıda kalan girdiler eskisi gibi okunur.
* **Strike:** boşsa ATM (K = F, sizin eğrinizde); `35,10` = %35,10. **Nominal:** varsayılan 100 mn TL (`100m`, `2,5mn`,
  `50.000.000`).
* **Çıktılar** (payer, receiver, straddle yan yana; **alıcının gözünden**: prim ödenir, delta payer'da +, receiver'da −,
  gamma ve vega +, teta −):
  * prim: bp peşin (A·p, nominalin bp'si), bp running (p, forward prim) ve TL (N·A·p);
  * delta: TL/bp (N·A·Φ(d)·0,0001; receiver −N·A·Φ(−d)·0,0001) ve % (Φ(d));
  * gamma: o deltanın 1 bp'lik değişimi (N·A·φ(d)/(σN·√T)·10⁻⁸);
  * vega: TL / 1 bp normal vol (N·A·√T·φ(d)·0,0001) ve TL / %1 Black vol;
  * teta: TL / iş günü - aynı F, σN ve A ile bir iş günü sonraki prim − bugünkü;
  * dayanak swap'ın DV01'i (N·A·0,0001, payer +);
  * **vadede faiz:** F (beklenen), F ± σN·√T (±1σ) ve F ± 2σN·√T (±2σ);
  * **başabaş (vadede):** payer K + p, receiver K − p, straddle K ± (p_payer + p_receiver); p running prim;
  * dayanak swap'ın ödeme takvimi (iki eğrinin DF'i, annuity).
* Kayıtlı günde (03.11.2026, Bootstrap): 1Y × 2Y'nin forward'ı %35,7502 (PPK basamak da %35,7502), A = 0,98771; opsiyon
  vadesi 03.11.2027, 250 iş günü (T = 0,9921). Kayıtlı veride OIS kapanışları 1Y'ye kadardır (22 gün): 1Y × 2Y'nin
  gerçekleşen vol'ü yoktur (18M, 2Y, 3Y kapanışı yok), 3M × 9M'inki vardır (20 değişim: 10,34 bp/gün). 1Y × 2Y'ye 5 bp/gün
  yazınca: 79,37 bp/yıl, %2,22 Black; ATM payer 31,54 bp running, 31,15 bp peşin, 311.516 TL; delta ±4.939 TL/bp, gamma
  49,84, vega 3.925 TL (%1 Black'te 140.302 TL), teta −624 TL / iş günü; başabaş payer %36,0656, receiver %35,4348.

**VİOP kontratları masanın ortak girdisi ve kendiliğinden döner:** VİOP sayfasındaki vadeli ticker'ları, yani USDTRY
1–12 (`VIOP!L1:W1`, `A1X6 Curncy` …), altın-TRY (`M45:O45`, `XLZ6 Comdty` …, çift aylar) ve altın-USD (`M60:O60`,
`XLTZ6 Comdty` …) bugünün tarihinden kurulur (ay harfleri `FGHJKMNQUVXZ`, yılın son hanesi): bir kontrat vade gününe
kadar (o gün dahil) işlem görür, ertesi gün sıradaki en yakın kontrattır. Vade günü ayın son iş günüdür (`Motor`'un
tatil listesiyle); o gün yarım günse (29 Ekim'in ya da bir bayramın arifesi) bir önceki iş günüdür - çalışma kitabının
kontrat tarihleri böyledir: 30.11.2026, 31.12.2026, … ve 27.10.2027 (28.10.2027 arifedir). Masanın elle yazdığı ticker
yine geçerlidir ve herkeste değişir; hücreyi silmek (`Delete`) kendiliğinden dönen koda geri getirir. Daha önce saklanmış,
dosyadakiyle aynı ticker'lar bu sürümün ilk açılışında bir kez silinir (yoksa dönmeyi durdururlardı); farklı bir değer
kalır. Bunlar kişiselken birinin kaydettiği değer, o kişide ortak değeri gizlememesi için ilk açılışta atılır. Kontrat
kodu hücresine formül yazılmaz (kodu yazın ya da silin).

**VİOP'un sütunları kontratın yeridir ("1. kontrat", "2. kontrat" …), kontratın kendisi değil.** Kontratlar dönünce bir
sütuna bağlı olan her şey sıradaki kontratın olur: kişisel girdiler - Interest 2 SP hesaplayıcılarının tarih, spot ve
faizleri (`VIOP!M32:M37`, `P32:P37`, `S32:S37`), altın hesaplayıcısının sütunlarına yazılan tarih, spot ve faizler
(`EK_XAU!B40:E48`, yazılan TRY % ve ON karşılık; fiyatlar aşağıda), geçmiş grafiklerinde çizilen kontratlar
(`EK_VIOP!B3:G3`) -, launchpad'deki sütun seçimleri, gizlenen ve sıralanan sütunlar,
kontrat sütunlarına başvuran girdi formülleri ve hesap tablosu hücreleri, "Elle değer"ler, hücre adresi içeren izleme
ifadeleri (her hesapta adresten yeniden okunur). "İlk 4 kontrat" hazır grubu da sırayladır: dönüşte seviye ve
"kurulduğundan" alarmları sıçrar, kapanışları iki kontratı karıştırır. Bir hücreye kurulan izleme ve alarm ise
kontratı **koduyla** izler (yukarıda, *İzleme · Alarmlar*). **Kendi yazdığınız fiyat** bir kontratın fiyatıdır,
sonrakine anlamsızdır: altın hesaplayıcısında bir kontrata yazdığınız kendi VİOP bid / ask'i (`EK_XAU!B54:D55`) ve
iki yönlü satırlarına yazılan **fiyat ya da forward** (USDTRY fwd, SP, günlük SP, XAUTRY teorik) kontrat dönünce
**kontratıyla birlikte onun yeni sütununa gider** (vade dolunca bir sola); kontrat tablodan çıktıysa - vadesi dolunca ya
da masa başka kod yazınca - silinir. Yazılan **faiz** (TRY %, ON karşılık) ve sütunun öteki girdileri **sütununda
kalır** (masa, 25.11.2026: "Evet"). Herkesin değerinde ve kaydedilmiş senaryolarda böyledir (görülen kodlar `kv` ·
`rowkeys.xau`). Bir sütunda tek yazılan değer olur: gelen fiyat, gittiği sütunda orada kalan yazılmış bir değer (o
sütunun faizi) bulursa silinir, sütunun kendi değeri kalır; gelen VİOP bid / ask da orada yazılmış olanın yerine geçmez.
(25.11.2026'ya kadar kendi VİOP bid / ask'iniz, sütuna başka kontrat gelince kontratı tablodan çıkmasa da silinirdi.)

**VİOP matrisinin DV01'leri kendi para biriminde** (VİOP → Takvim spread matrisleri → *Matris sürücü satırları*).
Her kontrat için 1 mn USD başına: **DV01 TRY (TL)** – TRY faizindeki 1 bp'nin kontrat fiyatına etkisi, TL (Excel'in
kendi satırı); **DV01 TRY (USD)** – aynısı USD; **DV01 USD (USD)** – USD faizindeki 1 bp'nin etkisi, USD
(`−100·(gün/360)/(1 + USD OIS·gün/360)`; Excel bunu TL olarak gösteriyordu). Değerler vadedeki tutarlardır; TL'den
USD'ye kontratın kendi fiyatıyla (o vadenin forward kuru) çevrilir. Bu satırları başka hiçbir formül okumaz.

**VİOP kontratlarının ON karşılığı** (masa, 26.11.2026: "Bunların da hepsini yap" - toplu forward fiyatlamadaki ON
karşılıklarıyla birlikte önerilenlerden: her VİOP USDTRY kontratının ima TRY faizinin ON karşılığı). VİOP sayfasının
**VIOP BID** ve **VIOP ASK** tablolarındaki **ON karşılık** satırı (Excel'deki adı TRY Repo) zaten budur: TRY satırındaki ima faizin (BID'de bid,
ASK'ta ask fiyatından; 360 basit, VKGS gün = vade − spot valörü `VIOP!K3`) aynı günlerde günlük bileşik karşılığı,
`360·((1 + TRY·VKGS/360)^(1/VKGS) − 1)` - Forward hesaplayıcılarındaki ve altın hesaplayıcısındaki ON karşılığın
formülü. Satır eklenmedi; sayfada adı **ON karşılık** oldu (masa, 26.11.2026: "Evet"; Excel dosyası değişmez), iki tablonun altındaki not da bunu söyler. **Masa → VİOP** sekmesindeki
*VİOP · kontratlar, ima TRY ve baz* özetinde her kontratın **ON bid (360)**'ı İma bid'in, **ON ask (360)**'ı İma ask'ın
yanındadır: VİOP sayfasındaki ON karşılık satırının kendisi, iki ondalıkla (`MASA!A109:A121`, `O109:O121`). Kayıtlı veride
30.11.2026 vadeli kontrat (26 gün): ima bid %33,58 → ON %33,20, ima ask %33,83 → ON %33,44. Yalnız gösterim: bu
tablolarda kontrat başına yazılan bir değer yoktur; kontratlar dönünce her ON kendi kontratının faiziyle birlikte kayar.
Bu, kontratın fiyatından gelen faizin kendi günleri ve 360 bazıyla ON karşılığıdır - OIS · PPK'daki TLREF'in iş günü
O/N'u değildir.

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
  - **İki yönlü** (masa, 25.11.2026): her sütunda **TRY %**, **All In S -> E (USDTRY fwd)**, **SP**, **Günlük SP**,
    **XAUTRY teorik** ve **ON karşılık** yazılabilir - **hangisini yazarsanız o kalır** (piyasa değişse de), diğerleri
    ondan hesaplanır, hesaplayıcının kendi formülleri ve tersleriyle: fwd'dan TRY = ((fwd/spot)·(1+USD·VKGS/360) −
    1)·360/VKGS (VİOP fiyatının ima TRY %'siyle aynı ters), SP'den fwd = spot + SP/10000, günlük SP'den SP = günlük ·
    VKGS, teorikten fwd = teorik · 31,1035 / XAUUSD fwd, ON'dan TRY = ((1 + ON/360)^VKGS − 1)·360/VKGS. Yazılan değer
    kalın ve ✎ ile işaretlidir, diğerlerinin ipucu neyden hesaplandığını söyler; herhangi birinde `Delete` sütunu
    varsayılana döndürür. Tarih, spot, USD %, swap %, XAUUSD fwd ve VİOP bid / ask hesaplayıcının girdisi olarak kalır:
    değişince yazılan değer kalır, diğerleri izler. Daha önce TRY %'ye yazdığınız değer sütunun yazılan değeridir (aynı
    sayılar). Serbest sütunda TRY % ya da başka bir üye yazılmadan fwd, SP ve ON boş kalır (eskiden yalnızca tarih
    yazılınca faizi 0 sayıp hesaplıyordu). Yazılanlar gizli yardımcı tabloda (`EK_XAU!B67:E72`) durur.
  - **Kontrat dönünce** yazılan USDTRY fwd, SP, günlük SP ya da teorik - ve kendi VİOP bid / ask'iniz - kontratıyla
    birlikte onun yeni sütununa gider, yazılan TRY % ya da ON sütununda kalır (yukarıda, *VİOP'un sütunları kontratın
    yeridir*).
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
  saklanmaz): **OIS mid zero %** ve **Offshore mid zero %** – satırın başlangıcından (T+0'da bugün, T+1'de TRY
  tatillerini atlayan ertesi iş günü: Valör − VKGS) Valör'üne eğrinin iskonto faktörlerinden zero faiz, basit ACT/360
  (BID % / ASK % ile aynı gün sayımı) – ve **BID − OIS mid**, **ASK − OIS mid**, **BID − Off mid**, **ASK − Off mid**
  (bp: swap'ın kendi bid / ask'ı eğrinin mid'iyle, + ise swap mid'in üstünde; tek taraflı kotada yalnız o tarafın
  spread'i). OIS = bootstrap TLREF OIS mid eğrisi (`BOOT_GUN` / `BOOT_LNDF`, OIS_MAIN'in par kotalarından: her vadenin
  ilk fiyat veren kaynağındaki MID, MID yoksa PX_LAST), Masa'nın 'Tarih arası faiz' Bootstrap satırıyla ve OIS_MAIN'in
  'İki tarih arası' bloğuyla aynı hesap (ln DF günle doğrusal); düğümlerde ORANLAR'ın "OIS zero"suyla aynı (1A, 2A, 3A
  …). Eğrinin spot'tan sonraki ilk düğümü 1A'dır; yalnız bu spread'lerde ondan önce **1W ve 2W OIS kotaları** düğüm
  olarak girer (Forward'ın "TRY OIS Simple Zero Rates"ı: ORANLAR'ın 1W / 2W "OIS zero"su), 1W'den kısa satırlar spot →
  1W arasından okunur – eğrinin kendisi ve Masa'nın Bootstrap satırları değişmez. Offshore = Forward'daki offshore TRY
  iskonto eğrisi (`OFF_GUN` / `OFF_LNDF`: 9A'ya kadar FX swap ima faizlerinin bid–ask ortası – 1W, 2W ve 1A noktaları
  `TRYI1W` / `TRYI2W` / `TRYI1M` zaten eğride –, 1Y'den XCCY ortalarının bootstrap'ı; günler USDTRY spot'undan) –
  Masa'nın kırık vade bloğu ve DİBS RV'nin FX swap ASW'siyle aynı eğri. Eğrinin spot'undan
  önceki günler (T+0: bir gün, hafta sonunda üç) eğrinin kendi O/N'uyla basit taşınır – ORANLAR'ın ON satırı: OIS'te
  TLREF (365 → 360), offshore'da offshore O/N mid; hücrenin ipucunda tarihler ve bu taşıma yazar. Eğriler sayfayı
  açanın TTO hesabındandır: kendi girdisi (ör. elle yazdığı bir OIS kotası) yalnız onun sayfasına yansır. Yeni
  Bloomberg isteği yoktur.
  **T+1 valörü TRY tatillerini atlar.** Dosya T+1 tablosunun valörünü `WORKDAY(TODAY(),1)` ile, yalnız hafta sonunu
  atlayarak sayıyordu (tatil listesi yok): bayram arifesinde vadeler bir gün erken görünüyordu. Dashboard'un eki Borsa
  kitabına TRY tatil listesinin bir kopyasını (`EK_TATIL!A5:A204`; yukarıda, Ayarlar → Tatiller) ve onunla T+1 günü
  (`EK_TATIL!B2` = `WORKDAY(TODAY(),1,liste)`, TRY OIS spot'u `OIS_MAIN!B2` ile aynı gün) ekler; T+1 tablosunun bütün
  "Valör"leri (`bu!Q9:Q54`; dosyada formülü olmayan son satır dahil) bu günden sayılır. T+1 tarihini Borsa kitabında
  başka okuyan yoktur (ima faizler gün sayısıyla hesaplanır). Aynı ek T+0 tablosunun son satırındaki dosya hatasını da
  düzeltir (`bu!D54` vadenin gününü eklemeden bugünü gösteriyordu). Kopya ve T+1 günü yardımcı tablolardadır.
* **DİBS ASW** (`DIBS_ASW.xlsx`): 50 kâğıtlık izleme listesi (ISIN, kaynak, manuel fiyat), TLREF OIS eğrisiyle
  iskonto edilmiş bugünkü değer, ASW (bp), uydurulan eğriye göre ucuz / pahalı ve üç kâğıdın ASW geçmişi. Tablonun
  sağında **FX swap ima eğrisine göre ASW** (ASW FX ima) ve FX ima − OIS farkı: kâğıt, sayfanın kendi iskonto ve annuity formülleriyle,
  OIS kotaları yerine *FX swap ima TRY eğrisi* (`EK_FX`: 9 aya kadar `TRYI…` FX swap ima, 1Y'den `TRYSAQ…` XCCY -
  1Y `TRYSAQ1` -, 18M XCCY eğrisinden hesaplanan;
  önce ICPL, yoksa BGN; MID yoksa bid–ask ortası; ticker kökleri ve kaynaklar ortak girdi) ile kurulan eğriyle de
  fiyatlanır. Fiyatı olmayan vadede OIS kotası kalır.
  **Her FX faizi kendi kuralıyla okunur** (`tto/aswfx.py`) - masanın kendi dosyası bu ticker'ları böyle okur (Forward'daki
  offshore TRY iskonto eğrisi, DİBS RV'nin FX swap ASW'sinin arkasındaki: `Forward!AJ123:AN143`, `C123:K134`): 9 aya
  kadar `TRYI…` FX swap ima, **tek dönem, basit ACT/360** (FX swap'ın kuponu yok: `DF = 1 / (1 + r·gün/360)`); 1 yıldan
  `TRYSAQ…` XCCY (1Y `TRYSAQ1`, tek kupon), **yıllık ACT/360 par** (`DF_n = (1 − r·Σ τ·DF) / (1 + r·τ_n)`, önceki yılların iskonto faktörleri
  eğrinin o vadeye kadar kurulan düğümlerinden). Tür vadeye göredir; gün, sayfanın eğrisinde spot'tan vadeye gündür.
  Sayfanın formülleri değişmez: her FX faizi, sayfanın kendi kuralında (3 aya kadar tek dönem basit ACT/365, sonra
  çeyreklik ACT/365 par; iki vade arasındaki çeyrekte kotaların aylara göre doğrusal ortası) vadesinde **aynı iskonto
  faktörünü veren par faize** çevrilip `ASW!C65:R65`'teki OIS kotasının yerine girer - 3 aya kadar kapalı formülle
  (`r·365/360`), sonrası sayfanın formüllerinin bir kopyasıyla (motorun düğümleriyle son basamağına kadar aynı) ikiye
  bölerek. Okunamayan faizde (gün ya da kota eksik, hiçbir par faizin ulaşamadığı iskonto faktörü) eğri orada durur
  (#N/A), sayfanın eksik kotada durduğu gibi. Önceden FX faizleri OIS kotası gibi çeyreklik par okunuyordu: kayıtlı
  veride 2–5 yıllık kâğıtların ASW FX'i +392…+485 bp değişti (FX − OIS −452…−546 bp'den −60…−67 bp'ye; 13.09.28:
  −532,3 → −140,1). `EK_FX` tablosu her vadede FX faizinin nasıl okunduğunu, günü ve OIS eğrisinin sıfır kupon faizini
  (sayfanın hücreleri), yanında ASW FX hesabından FX eğrisinin sıfır kupon faizini ve sayfaya giden par faizi gösterir.
  **18M hesaplanır, kota değildir** (masa, 18.11.2026: "TRYI18M gerçek bir kotasyon değil. Orada annual payment olduğu için
  1Y'den sonra XCCY trade ediyor. Zero'yu oradan bulmamız gerekli. Bunun da interpolasyonu PPK'yı seçersem PPK'ya
  gelmeli"; "18M hesaplanacak, gerçek kotasyon girilmeyecek"). EK_FX'in 18M satırında ticker yoktur (`hesaplanan`; ticker
  kökleri girdisi `EK_FX!B6:B11` ve `B13:B21`). 18M'in iskonto faktörü **offshore eğrinin XCCY 1Y (`TRYSAQ1`) ile 2Y
  (`TRYSAQ2`) düğümleri arasında**, ASW sayfasının 18M düğüm gününde okunur - kullanıcının kendi **Eğri interpolasyonu**
  ayarıyla: **Bootstrap**'ta Forward'daki offshore eğri (`OFF_GUN` / `OFF_LNDF`: düğümler arasında ln DF günlere göre
  doğrusal), **PPK basamak**'ta offshore PPK eğrisi (MPC ima, offshore kotalara sabit bazla). Eğri FX spot'undan sayar; ASW
  sayfasının spot'u başka günse 18M oradan okunur (`ASW!T65`, `Forward!I2`). **Faizi** aynı eğride **18M XCCY par**:
  yıllık ACT/360, kuponlar vadeden geriye - önce 6 aylık kısa dönem, sonra 12 ay (masa: "18 ayda 6 ay + 12 ay olarak kupon
  ödemesi yapılıyor, sondan başlayıp"); bu par aynı takvimle geri bootstrap edilince 18M'deki iskonto faktörünü aynen
  verir. Hepsi tek fonksiyondadır: `aswfx.point_18m(eğri, 6A günü, 18A günü, kaydırma)` (iskonto faktörü, par, sıfır kupon);
  hangi eğri olduğunu `Service._asw_fx_18m` seçer. Sayfaya diğer vadeler gibi, vadesinde aynı iskonto faktörünü veren kendi
  kuralındaki par faiz olarak girer. EK_FX tablosunda 18M satırı **"hesaplanan (XCCY 1Y–2Y, Bootstrap)"** ya da **"…, PPK
  basamak)"** yazar, D'de 18M XCCY par'ı, F'de OIS'e farkını, FX sıfır kupon sütununda sıfır kupon faizini gösterir;
  altındaki grafiğin FX kota çizgisinde de 18M bu par'dır. Çalışma kitabının kendisinde 18M'in faizi yoktur (`EK_FX!D12`
  #N/A): değer her kullanıcının kendi hesabından gelir. `TRYSAQ1` ya da `TRYSAQ2`'nin fiyatı yoksa 18M hesaplanmaz, OIS
  kotası kalır (satır "yok" der). Kayıtlı günde (03.11.2026) `TRYI18M`'in fiyatı yoktu, 18M OIS kotasıyla (%35,59)
  duruyordu; şimdi Bootstrap'ta iskonto faktörü 0,592809, 18M XCCY par %39,588 (sıfır kupon %41,752), PPK basamak'ta
  0,594371, %39,375 (%41,503). Bir ile üç yıl arası kâğıtların ASW FX'i değişti (Bootstrap; PPK basamak'ta parantez içinde):
  `TRT150328T24` −63,7 → −115,7 bp (−103,2), `TRT130928T38` −140,1 → −163,9 (−158,2), `TRT120929T12` −148,0 → −154,0
  (−152,5); bir yıldan kısalar aynı. **1Y `TRYSAQ1`** (masa, 18.11.2026: "Offshore için hep TRYSAQ1 kullanılacak 1Y'de, OIS ile
  ayrı bunlar, OIS farklı"): EK_FX'in 1Y satırı `TRYI12M` yerine 1 yıllık XCCY `TRYSAQ1`'i okur - masanın Forward sayfası offshore eğrisinin 1Y noktası olarak bunu kullanır, ASW geçmişi de;
  `TRYI12M`'in iki kaynakta da fiyatı yoktu, 1Y OIS kotasıyla (%35,55) duruyordu. Türü XCCY'dir (yıllık ACT/360 par); tek
  kuponla iskonto faktörü FX swap'ın okunuşuyla aynıdır (`1 / (1 + r · gün/360)`), 2Y XCCY'nin zinciri de Forward'daki
  gibi bu 1Y'nin iskonto faktörüyle kurulur. Kayıtlı günde 1Y %39,400 (`TRYSAQ1 BGN`). FX eğrisinin sıfır kupon faizi
  (EK_FX'in FX sıfır kupon sütunu): 9A %39,700, 1Y %40,703 → %39,947, 18A %41,752 (aynı), 2Y %42,484 → %42,649; 9A–1Y
  forward'ı (basit ACT/360, Bootstrap) %37,5 → %35,2, 1Y–18A %39,3 → %40,6 - Forward'daki offshore eğrinin `TRYI9M` → `TRYSAQ1`
  adımı. ASW FX (Bootstrap; PPK basamak'ta parantez içinde): `TRT131027T36` (0,94 yıl) −142,5 → −96,8 bp (aynı),
  `TRT150328T24` −115,7 → −99,1 (−103,2 → −86,5), iki ile dört buçuk yıl arası 3–4,5 bp aşağı (`TRT120929T12` −154,0 →
  −158,5), yedi–dokuz yıllıklar en çok 0,4 bp; dokuz aydan kısaların ASW FX'i ve OIS tarafı aynı.
  FX tarafının adil değerleri (DİBS Trading'in "FX swap'a göre" sütunları, DİBS RV · Genel, kart: ASW FX'lere
  uydurulan a + b·t + c·t²) eğri yeniden uydurulduğu için bütün kâğıtlarda oynar - kayıtlı günde DİBS Trading'de dokuz
  aydan kısaların adil getirisi +11…+16 bp, pahalı / ucuz −9,5…−11,7 bp; `TRT131027T36` −44,8 bp / +37,4;
  `TRT150328T24` −12,5 / +10,3; yedi yıldan uzunlar 4 bp'den az. Bloomberg: `TRYI12M`'in boş dönen iki ticker'ı yerine `TRYSAQ1 ICPL` / `TRYSAQ1 BGN Curncy` (MID, yoksa bid–ask ortası); geçmiş için yeni istek yok
  (`TRYSAQ1`'in günlük kapanışı zaten alınıyor).
  **İki FX swap eğrisi, iki ad.** İki sayfa iki ayrı FX swap eğrisi kullanır ve aynı kâğıda farklı FX ASW'si verir
  (kayıtlı veride 13.09.28: −172 ve −164): DİBS RV'ninki **FX swap (offshore ICAP eğrisi)** - Forward'daki offshore TRY
  iskonto eğrisi; `BF:BJ` sütunları ondandır, başlıklarının ipucu ve "ASW eğrisi · FX swap (offshore ICAP eğrisi)"
  tablosu bunu söyler -, bu sayfanınki **FX swap ima eğrisi (TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden; fiyatı yoksa OIS)** - OIS
  kotalarının yerine kendi kuralıyla okunan FX faizleri; ASW FX ima sütunları, tablonun, grafiğin ve EK_FX tablosunun
  başlığı bunu söyler. Hücreler ve değerleri aynıdır, yalnız başlıklar ve ipuçları.
  **FX swap ima eğrisine göre ASW grafiği**: OIS grafiğinin hemen altında aynı XY grafiği, aynı hesap FX swap ima eğrisiyle -
  her kâğıt kalan vadesinde tablonun ASW FX sütunundaki değeriyle (etiketi OIS grafiğindeki gibi: Mar28, Eyl35 …),
  kesik çizgiyle bu ASW'lere aynı kuralla uydurulan `a + b·t + c·t²` eğrisi (Eğri / grafik sütunu: boş, 1, 0 ya da
  x - OIS grafiğinde hariç tutulan kâğıt burada da hariç); görünüşü, üzerine gelince değerleri ve "Tablo" düğmesi
  OIS grafiğinin. Grafik çalışma kitabının kendi grafiğidir: sayfanın formülleri OIS kotaları yerine FX faizlerinin
  sayfaya giden par karşılıklarıyla hesaplanır (tablonun ASW FX sütunuyla aynı hesap, aynı anda bir kez). FX swap ima
  faizi hiç yoksa grafik boş kalır, nedeni yazar. `EK_FX` tablosunun altında **FX swap ima TRY eğrisi ve OIS** çizgi
  grafiği: düz çizgiler iki eğrinin vadedeki **sıfır kupon faizi** (yıllık bileşik, ACT/365: `DF^(−365/gün) − 1`,
  `EK_FX!K`) - OIS sayfanın kendi iskonto faktörlerinden, FX aynı düğümlerin ASW FX hesabındaki değerinden (kâğıtların
  iskonto edildiği eğrinin kendisi; fiyatlı vadede FX faizinin kendi kuralıyla verdiği iskonto faktörü, fiyatı olmayan
  vadede eğri o vadenin OIS kotasıyla sürer) -; kesik çizgiler kotaların kendisi: FX ima faizi (fiyatı olmayan vade
  atlanır, çizgi üzerinden geçer) ve aynı vadenin OIS kotası. Grafiğin bir serisi `"curve": "fx"` ile FX hesabından
  okunur (aynı hücreler). Yeni Bloomberg isteği yok.
  **Tablonun düzeni** (yalnız görünüş): kâğıtlar trading listesindeki gibi türüne (bono, kuponsuz, sabit kuponlu, TLREF,
  FRN, TÜFE; her türün başlığı "Bono · 2 kâğıt") ve vadesine göre sıralıdır, kâğıtsız satırlar gösterilmez. Hücreler
  yerindedir: `ASW!B9` yine `ASW!B9`'dur; grafikler, geçmişi izlenen kâğıtlar, "+ ISIN ekle" ve satırların değerleri
  (*Kâğıdın satırındaki değerler kâğıdındır*) bundan etkilenmez. Tablonun bir launchpad kutusu kâğıtlarını yine ISIN'iyle
  ya da satır numarasıyla bulur ve tablonun başlık satırını eskisi gibi gösterir; türlerin başlıkları yalnız sayfadadır,
  kutuya girmez (seçilen bir satırın yerini almaz).
  **ASW → temiz fiyat** (masa, 24.11.2026; tek yönlü araçların tersi). Kâğıt tablosunun hemen altında kendi tablosu (aynı
  kâğıtlar, aynı sıra): **Hedef ASW (bp)** sütununa kâğıdın ASW'sini yazın (`-50`, `25`): **Temiz (hedef ASW'den)**
  kâğıdın o ASW'de olacağı temiz fiyattır - sayfanın kendi formülü tersinden (`ASW!V:Y`): ASW = (PV @OIS − kirli @spot) /
  annuity · 100, kirli @spot = (temiz + işlemiş) · (1 + TLREF · (spot − valör) / 365), yani temiz = (PV − ASW · annuity /
  100) / (1 + TLREF · …) − işlemiş. PV, annuity, işlemiş ve taşıma fiyata bağlı değildir: bulunan fiyat Manuel temiz'e
  yazılınca ASW tam yazılan değer çıkar. **Eğri bu sayfanın kendi OIS eğrisidir** (`ASW!C65:R65` kotaları, Ayarlar'daki
  eğri interpolasyonunuzla) - **ASW FX ima'ya göre değildir** (o, aynı sayfanın FX swap ima faizleriyle hesabıdır) ve DİBS
  RV'nin ASW'sinden de ayrıdır (başka bir OIS eğrisi: aynı kâğıda iki ayrı ASW, ikisinin de tersi kendi sayfasında).
  **Fark** = bu temiz − tablodaki temiz. TLREF'li kâğıtta ASW yoktur, Not "DM → temiz fiyat DİBS RV'de" der; fiyatı olmayan
  kâğıdın satırı hesaplanmaz - Manuel temiz'e herhangi bir fiyat yazınca hesaplanır (sonuç ona bağlı değildir). Girdi
  kişiseldir, başta boştur; kâğıt listede yer değiştirince değer kâğıdıyla gider (*Kâğıdın satırındaki değerler
  kâğıdındır*). Yeni Bloomberg isteği yok.
  **Kâğıt tablosu iki yönlüdür** (masa, 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar
  bu şekilde olmalı"; genel kural: Kullanım'daki *İki yönlü tablolar*). Bir kâğıdın satırında **Manuel temiz**, **ASW** ve
  **Kirli @spot** üçü de yazılabilir: **hangisini yazarsanız o kalır, diğerleri ondan hesaplanır** (tablonun altında da
  yazar; yazılan ✎ ile işaretli). ASW yazılınca temiz = (PV − ASW · annuity / 100) / (1 + TLREF · (spot − valör) / 365) −
  işlemiş (yukarıdaki "ASW → temiz fiyat"ın aynı formülü), kirli @spot yazılınca temiz = kirli / (1 + TLREF · …) −
  işlemiş; öbürleri o temizden sayfanın kendi formülleriyle. Hesaplanan bir değeri kendi sütununa geri yazmak aynı satırı
  verir; son yazılan geçerlidir; `Delete` satırın herhangi bir hücresinde satırı piyasaya döndürür. **Yazılan ASW kâğıda
  varsayımsal bir temiz fiyat verir**: eğri oynadıkça o fiyat da oynar, ASW aynen kalır - Pahalı / ucuz, eğri uyumu ve
  grafik bu fiyatla. **ASW FX ima sütunu** (ve geçmişin canlı noktası) o satırı **aynı temiz fiyatla** FX swap ima
  eğrisinde fiyatlar (yazılan OIS ASW'si FX eğrisinde başka bir ASW'dir). Sabit kuponlu ve bonoda; fiyatı olmayan kâğıtta
  da çalışır (ters hesap fiyata bakmaz). TLREF / TÜFE satırında yazılan ASW fiyat vermez (satır piyasada kalır). Önceden
  Manuel temiz'e yazdığınız fiyatlar aynen durur; ASW'nin üzerine "Elle değer" yazdıysanız o satırın yazılanı olur.
  Yazılan ASW / kirli fiyat satırın gizli sütunlarında (`ASW!Z:AA`, yardımcı tabloda) saklanır ve kâğıtla taşınır.
  Pahalı / ucuz (T) yazılamaz: eğri kâğıdın kendi ASW'sinden uydurulur (döngü).
  **ASW geçmişi offshore eğrisine göre de** (masanın isteği, 18.11.2026: "ASW geçmişini offshore'a göre de çizebilmem
  gerekli"). Sayfanın geçmişi (`ASW!B66:Z325`: seçili üç kâğıdın her geçmiş gündeki ASW'si, o günün OIS kotalarıyla -
  `C66:R325` Bloomberg geçmiş blokları - kurulan eğriyle) aynı hesapla offshore eğrisine göre de çıkar: her geçmiş günün
  OIS kotalarının yerine **o günün offshore faizleri**, bugünkü ASW FX ima'daki kuralla - her faiz kendi kuralıyla okunur
  ve sayfaya, vadesinde aynı iskonto faktörünü veren kendi kuralındaki par faiz olarak girer (`aswfx.to_sheet`);
  sayfanın formülleri değişmez. Faizler **panonun kendi günlük geçmişinden** gelir (Gün Sonu Matrisi'nin tarihçesi,
  `tto/history.py`; bunun için Bloomberg'e yeni istek yok). Vade → seri (`aswfx.history_series`, ay sayısıyla
  eşlenir): **1M, 2M, 3M, 6M, 9M** → Forward'daki offshore satırlarının FX swap ima faizleri `TRYI1M … TRYI9M` (tarihçede
  "off" grubu); **1Y … 10Y** → `TRYSAQ1 … TRYSAQ10` (EK_FX'tekilerle aynı - her vade yalnız kendi türünün grubunda:
  tarihçede bir `TRYI12M` serisi olsa da 1Y `TRYSAQ1`'dir); her biri önce ICPL'den, o gün ICPL'nin
  kapanışı yoksa BGN'nin hareketi ICPL'nin seviyesine eklenerek (tarihçenin kendi birleştirmesi). **18M** o günün
  `TRYSAQ1` ve `TRYSAQ2` kapanışlarından hesaplanır (`aswfx.history_point`: ikisinden Forward'daki zincirle kurulan XCCY
  eğrisi, ln DF doğrusal - Bootstrap; geçmiş günün PPK eğrisi yoktur: PPK basamak ayarında da geçmiş günler Bootstrap'la,
  yalnız bugünkü satır kullanıcının ayarıyla). **Boşluk kuralı**, canlıdaki gibi: o gün kapanışı olmayan vade (18M'de iki
  kapanıştan biri) o günün OIS kotasıyla kalır; o gün **hiç offshore kapanış yoksa** o günün offshore ASW'si yoktur - grafikte
  offshore çizgisinde (İkisi'nde de) boşluk, tabloda offshore ASW hücreleri boş, Offshore vade `0 / 16` (ipucu: "o gün
  offshore kapanışı yok"); bugün EK_FX'te hiç FX faizi yoksa bugünkü offshore noktası da yoktur (ASW FX ima sütunu da
  boştur). Son satır (bugün) tablonun ASW FX ima değeridir (EK_FX'in canlı faizleri; aynı kotalar). Geçmiş tablosunun sağında dört sütun: **ASW 1–3
  offshore** ve **Offshore vade** - o gün eğrinin 16 vadesinden kaçının offshore faizden geldiği (`16 / 16`; üzerine
  gelince hangileri offshore, hangileri OIS; bugün: EK_FX'te fiyatlı vade sayısı). **Geçmiş grafiği** OIS'e (varsayılan,
  çalışma kitabının grafiği - değişmedi), offshore eğrisine ya da ikisine göre çizilir: grafiğin üstündeki küçük
  seçici (OIS / Offshore / İkisi) ya da Parametreler'deki **Geçmiş grafiği** hücresi (`ASW!N3`, kişisel girdi: herkes
  kendi seçimini görür, "Girdilerimi sıfırla" OIS'e döndürür). Offshore'da her kâğıdın serisi "· offshore" adıyla,
  İkisi'nde OIS serilerinin yanında kesik çizgiyle; grafiğin notu kaç geçmiş günün offshore faizli olduğunu yazar. DİBS RV
  · Genel'deki ASW geçmişi grafiği de kullanıcının seçimine göre çizilir. Hesap bir kez yapılır ve tutulur: geçmiş
  blokları bütün olarak (Bloomberg geçmiş formüllerine dizi verilerek) kullanıcının hesabının üstünde bir katmanda
  değişir; yalnız onlara bağlı hücreler orada yeniden hesaplanır, piyasa oynadıkça yalnız bugünkü satır. Kayıtlı veri
  modunda geçmiş blokları boş olduğundan yalnız bugünkü nokta vardır.
* Bu iki dosya Bloomberg bağlantısı olmadan kaydedildiği için içlerinde **kayıtlı piyasa verisi yok**. Kayıtlı
  veri modunda: ASW sayfası kâğıt bilgilerini ve fiyatları TTO dosyasının aynı günkü kayıtlarından alır (ASW
  değerleri TTO'daki DİBS RV tablosuyla 0,05 bp içinde aynıdır; geçmiş kısmı yalnızca canlıda dolar); Borsa Swap
  sayfasındaki kotalar TTO'daki RET eğrisinden türetilmiş **örnek veridir** (sayfanın üstünde yazar).
  Canlı modda ikisi de doğrudan Bloomberg'den beslenir.

### Manuel Tahvil: ISIN'den koşullar

Girdiler tablosunun son satırı **ISIN** (`Manuel Tahvil!B17`; masa, 24.11.2026). Kâğıdın ISIN'i yazılınca koşulları
girdilere **varsayılan** olarak gelir: **vade** ve **sabit kupon** katalogdan (Tüm Kâğıtlar: kâğıdın ISIN'iyle tutulur),
**kupon frekansı** DİBS RV'den (Bloomberg'in `CPN_FREQ`'i; listede değilse 6 ayda bir), **tip** (S / D), TLREF'lide
**ek getiri** (Bloomberg'in marjı, dönemsel %) ve **TLREF gecikmesi** (DİBS RV'nin `V2`'si), **cari dönemin bilinen
kuponu** (DİBS RV'de yazılan bilinen kupon ya da sabit ilk kupon, dönem tablosunun o dönemine) ya da **gerçekleşen endeks**
(işlemiş faizin endeks kısmı), **temiz fiyat** ve **valör**: kâğıt trading listesindeyse DİBS RV'nin kullanılan temizi ve
valörü (oraya yazdığınız manuel fiyat dahil), değilse Tüm Kâğıtlar'ın bid / ask ortası, tek taraflıysa bugünkü son işlemi
(başka bir şey sorulmaz). Böylece **Hedef → temiz fiyat** tablosu yazılan BIST getirisinin, ASW'nin, Z'nin ya da DM'nin
fiyatını hemen verir (o tablo temiz fiyata bağlı değildir: fiyatı olmayan kâğıtta da çalışır). **Yazdığınız değer önce
gelir**: ISIN'in getirdiği bir girdinin üzerine yazdığınız değer kalır, C17 hangilerini elle yazdığınızı söyler ("elle
yazılan (önce gelir): kupon"); silince (`Delete`) kâğıdınki döner. ISIN boşken her girdi çalışma kitabının kendi
varsayılanıdır (eskisi gibi). **Fiyatlanan kâğıtlar:** sabit kuponlu her kâğıt; TLREF'li yalnız trading listesindeyse
(marjı ve bilinen kuponu oradan); **reddedilenler**, C17'de nedeniyle: bono ve kuponsuz (Manuel Tahvil'in getirisi kupon
kuralıyla - bononun basit getirisi değil; DİBS ASW / DİBS RV'nin "ASW → temiz fiyat" tablolarına), FRN (TLREF dışı
endeks), TÜFE'ye endeksli (reel kupon), kuponu bilinmeyen, vadesi geçmiş ve listede olmayan ISIN. Kâğıt listede yer
değiştirse de koşulları ISIN'iyle bulunur. Girdi kişiseldir, başta boştur. Yeni Bloomberg isteği yok.

**Manuel Tahvil iki yönlüdür** (masa, 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın"). **Temiz fiyat** (B14)
ve Sonuç / Ek sonuçlar'daki **kirli fiyat** (valör ve OIS spot), **BIST basit** ve **bileşik getiri**, **ASW par-par**,
**Z-spread**, **DM** ve **getiri − OIS** yazılabilir: **hangisini yazarsanız o kalır**, temiz fiyat ondan, öbür sonuçlar
temiz fiyattan hesaplanır (✎ yazılan; tablonun altında da yazar). Ters hesaplar sağdaki Hedef → temiz fiyat tablosunun
aynı formülleridir (getiri: Σ CF / (1 + s/f)^w − işlemiş; ASW: (P_OIS − ASW · annuity / 100) / fonlama − işlemiş; Z:
Σ CF · DF · e^(−z·t); DM: nakit akışları ileri faiz + DM ile dönem dönem - DM'in kendi sütunu `AG`, hedef DM'in `AF`'si
ayrı); bileşik getiri ve getiri − OIS (bileşik getiri − vadedeki OIS par) basit getiriye kupon frekansıyla çevrilir. Yazılan
sonuç **ISIN'in getirdiği fiyatın önüne geçer** (C17 "fiyat (yazılan sonuçtan)" der); silince (`Delete`, satırın herhangi bir
hücresinde) ISIN'in fiyatı - ISIN yoksa dosyanınki - döner. Yazılan getiri ya da spread varsayımsal bir fiyattır: eğri
oynadıkça fiyat oynar, yazılan aynen kalır. Hesaplanan bir sonucu geri yazmak aynı fiyatı verir. Önceden B14'e yazdığınız
fiyat aynen durur. Yazılan sonuçlar gizli `AO17:AP25`'te (yardımcı tablo) saklanır.

### Kâğıt Fiyatlama

Menünün Tahvil grubunun **ilk girişi** (`#/kagit-fiyat`; `tto/kagitfiyat.py`, `pages/kagitfiyat.js`). Trading listesinin
her sabit kuponlusu ve bonosu için **tek bir adil seviye**, etrafında **kota**, **iyi alış / satış seviyeleri** ve fiyatın
**nasıl kurulduğu**. Masanın 19.11.2026 isteği: "Hangi seviyelerin iyi olduğunu ve fiyatlamayı nasıl yapacağımı net
söylemiyor". TLREF'e endeksli, FRN ve TÜFE'ye endeksli kâğıtlar fiyatlanmaz; satırları nedenini söyler. Yeni Bloomberg
isteği yoktur.

**Ana tablo: eğri fiyatı** (masa, 20.11.2026: "Kağıt fiyatlama kısmını çok anlayamadım, curve'e göre fiyatı olmayanların da
fiyatını bulmak içindi asıl"). Sayfanın üstündeki tablo masanın listesindeki (Tüm Kâğıtlar) **her sabit kuponlu, bono ve
kuponsuz kâğıdı** gösterir, trading listesinde olmasa da; türüne ve vadesine göre:

* **Kâğıt / ISIN / Vade.**
* **Piyasa**: bugünkü piyasa fiyatı - iki taraflı kotanın ortası, yoksa bugünkü son işlem - getirisi (bileşik), temiz
  fiyatı ve kaynağı. Trading listesindekiler için DİBS RV'nin bid / ask / son işlemi, diğerleri için Tüm Kâğıtlar'ın
  (sayfaların zaten istediği hücreler: yeni Bloomberg isteği yok). Yoksa "—".
* **Eğri**: sabit kuponluda **Nelson-Siegel eğrisi** - fiyatı olan kâğıtlara şimdi uydurulur, kâğıdın kendi nakit
  akışlarında okunur; uydurmadaki kâğıt için kendisi dışarıda bırakılarak uydurulan eğri. Bono ve kuponsuzda vade
  kovasının **tabanı**, adil getirinin ağırlıklarıyla: 1 yıla kadar %75 TRY OIS sıfır faizi (Bootstrap, kâğıdın
  vadesinde) + %25 Nelson-Siegel; 1–5 yıl Nelson-Siegel; 5 yıl üstü %75 Nelson-Siegel + %25 OIS.
* **Fiyat** (cevap) ve **nereden**: piyasa fiyatı varsa o (**piyasa**); yoksa kovanın tabanı + kâğıdın **son bilinen
  noktasında** o tabana farkı (**eğri + son fark (kaynak gg.aa, yaş)**, her türde - masanın geçmişinde en iyi tahmin buydu;
  ör. "eğri + son fark (ihale 20.11, bugün)", "(son işlem 14.11, 4 iş günü önce)", "(kapanış 19.11, 1 iş günü önce)"; aşağıda
  *Son fark*). Hiçbir noktası yoksa türüne göre:
  * sabit kuponlu: **eğri** - yalnız Nelson-Siegel;
  * bono ve kuponsuz: taban + **akran farkı** (**eğri + akran farkı**) - aynı vade kovasında bugün piyasa fiyatı olan bono
    ve kuponsuzların kendi tabanlarına farklarının medyanı, kâğıdın kendisi hariç; nasıl satırı akran sayısını ve medyanı
    söyler (ör. "OIS %75 + eğri %25 … + akran farkı −613 bp (2 bono / kuponsuz …)"). Akranı yoksa yalnız taban (**eğri**),
    "akran yok" uyarısıyla.

  Getiri ve kâğıdın valöründeki temiz fiyat; üzerine gelince nasıl kurulduğu ve tipik hatası.
* **Tipik hata** (her eğri fiyatında: nasıl satırında, Fiyat hücresinin ipucunda, Kâğıt Fiyat Yükleme'nin satırında):
  "tipik hata ±X bp". X, o kuralın bugün piyasa fiyatı olan aynı kova ve türdeki kâğıtlara uygulanınca piyasadan
  sapmasının medyanıdır; her kâğıt kendi kotası kullanılmadan fiyatlanır (eğride kendisi dışarıda, akranlarında yok, son
  farkta dünkü fark). Sayfa her açılışta yeniden ölçer; 2'den az kâğıtta "tipik hata ölçülemedi".
* **Son fark** (masa, 20.11.2026: "Fiyatı olmayanı eğriden fiyatlarken eğriye göre önceden ne kadar pahalı ucuz olduğuna
  da bakmamız gerekli"; "Aynı şey fiyatlama kısmı için de geçerli"): kâğıdın son bilinen farkı **tek bir yerden** gelir ve
  her yerde aynıdır - Fiyat sütunu, kart, ayrıntıdaki adil ve Kâğıt Fiyat Yükleme'nin "eğri fiyatı (son fark …)" satırı.
  Noktalar (hiçbiri yeni Bloomberg isteği değil):
  * **kapanış** - tarihçenin son kapanışı (trading listesi; listeden çıkmış kâğıdın tarihçede kalan serisi);
  * **ihale** - Kâğıt Fiyat Yükleme'nin her sabah sakladığı ihale değeri (bono / kuponsuz: basit getiri, sabit kuponlu:
    temiz fiyat; o satırın valöründe getiriye çevrilir);
  * **son işlem** - LAST_PRICE / LAST_TRADE_DATE: trading listesinde DİBS RV'nin, diğerlerinde Tüm Kâğıtlar'ın
    hücreleri; ya da Kâğıt Fiyat Yükleme'nin BBG modunda Bloomberg'den aldığı yanıt - artık kâğıt başına saklanır, 5
    dakikalık önbellekten sonra da kalır. Fiyat, işlemin valöründe getiriye çevrilir (bono fiyatı, getiri gibi duran
    rakam getiri sayılır: yüklemenin kuralı);
  * **kapanış (kayıtlı)** - bundan sonra her gün, piyasa kapandıktan sonra (17:35) bir kez, ya da çalışma kitabının günü
    döndüğünde önceki gün kaydedilmemişse: masanın listesindeki her sabit kuponlu / bono / kuponsuz kâğıdın Piyasa
    sütunundaki fiyatı (iki taraflı kotanın ortası ya da günün son işlemi; trading listesinde DİBS RV, diğerlerinde Tüm
    Kâğıtlar), getirisi ve valörü saklanır (kâğıt başına son 120 gün; yalnız canlı modda; Bloomberg'e istek yok).

  En **yeni** nokta seçilir; aynı gün birden çoksa önce son işlem, sonra ihale, sonra kapanış (nasıl satırı hangisinin
  seçildiğini ve aynı gün başka ne olduğunu söyler). Fark, noktanın gününün kapanış eğrisine (o günün Nelson-Siegel'i ve
  OIS'i) göre ölçülür; **bugünkü** nokta (bugünkü ihale ya da işlem) şimdiki eğriye göre ölçülür ve öyle yazılır - fiyat o
  zaman noktanın kendi getirisidir. Kapanış eğrisi olmayan bir günün noktası ölçülemez, söylenir. Ayrıntıdaki **adil**
  aynı noktayı alır, ama bugünden önceki en yeni noktayı: bugünkü bir işlem adili o işlemin kendisi yapardı; adilin σ'sı
  ve geri testi "bugünkü taban + dünkü fark"ın hatasıyla ölçülür.
* **Fark**: piyasa − Eğri sütunu (bp), piyasa fiyatı varsa.
* **Öngörülen · OIS'e göre · FX swap'a göre** (masa, 20.11.2026, öngörülen fiyatlar yeniden sütun olsun mu diye sorulunca:
  "Göster"): Fark'tan sonra, iki satırlı hücreler - üstte getiri, altta temiz fiyat.
  * **Öngörülen**: "Öngörülen ufku"nda seçilen ufukta (1 hafta / 2 hafta / 1 ay; değiştirince sütun hemen yeniden çizilir)
    öngörülen getiri ve ufkun valöründeki temiz fiyat, yanında kısa model ("M4/60", "eğri+fark sabit"). Üzerine gelince
    basit getiri, Δ bp, K/Z / 1 mn, hesap ve geri test.
  * **OIS'e göre / FX swap'a göre**: DİBS Trading'in aynı adlı sütunlarının getirisi ve fiyatı (aşağıda).
  * Değerler ayrıntıdakilerin aynısıdır; yalnız trading listesindeki kâğıtlar için. Diğerlerinde "—", üzerine gelince
    nedeni: günlük kapanışları ve DİBS RV satırı (OIS / FX swap ASW'si) yok.
* **▸**: kâğıdın ayrıntıları (aşağıdaki adil, kota, iyi seviyeler, σ, geri test, piyasa ve nasıl fiyatlandı - öngörülenin
  satırıyla) - kapalı gelir; trading listesinde olmayan kâğıdın ayrıntısı yoktur. Öngörülen ve OIS'e / FX swap'a göre
  ayrıntıdan çıktı (tablonun sütunları oldu).
* TLREF'e endeksli, TÜFE'ye endeksli ve FRN kâğıtlar tabloya girmez (nominal eğriye göre fiyatlanmaz): tablonun altında
  sayıları ve nedeni tek satırda.
* Kuponu katalogda olmayan sabit kuponlu kâğıt satırda durur, fiyatı yoktur ("kuponu bilinmiyor").

**Doğrulama** (20.11.2026; masanın veritabanı kopyası, kayıtlı gün 03.11.2026): piyasa fiyatı olan her kâğıt, fiyatı ve
geçmişi yokmuş gibi fiyatlandı - kendisi Nelson-Siegel uydurmasının da akranlarının da dışında. Piyasa getirisinden
mutlak hata, bp, medyan / en büyük:

| Kova, tür | Kâğıt | Kullanılan kural | Önce: yalnız Nelson-Siegel | Şimdi |
|---|---|---|---|---|
| 1 yıla kadar, bono / kuponsuz | 2 | taban + akran farkı | 196 / 256 | 43 / 43 |
| 1 yıla kadar, sabit kuponlu | 4 | eğri (Nelson-Siegel) | 76 / 104 | 76 / 104 |
| 1–3Y, sabit kuponlu | 3 | eğri | 23 / 39 | 23 / 39 |
| 3–5Y, sabit kuponlu | 3 | eğri | 96 / 139 | 96 / 139 |
| 5Y+, sabit kuponlu | 3 | eğri | 56 / 165 | 56 / 165 |

Bonolarda akran farkı hatayı 196 / 256 bp'den 43 / 43 bp'ye indirdi (her bononun tek akranı var: diğer bono). Sabit
kuponlularda da denendi ve her kovada kötüleştirdi (1 yıla kadar 206 / 242, 1–3Y 27 / 51, 3–5Y 126 / 195, 5Y+ 131 / 177):
orada yalnız eğri kalır. Kurala başka ayar yapılmadı. Aynı gün, kendi geçmişi olan kâğıtta "son fark"ın hatası (bugünkü
taban + dünkü fark, bugünkü piyasaya karşı): 1 yıla kadar bono 35 / 50, 1 yıla kadar sabit kuponlu 18 / 112, 1–3Y 5 / 11,
3–5Y 21 / 25, 5Y+ 14 / 16 bp (`KagitFiyat.validation`; ayrıntı `docs/desk-decisions.md`).

Son fark'ın kaynakları aynı kopyada (20.11.2026): fiyatı olmayan 14 kâğıttan yalnız 1'inin (TRT081128T15) son farkı var -
şimdi DİBS RV'nin 02.11 son işleminden (aynı gün kapanışı da var, son işlem seçildi). Kopyada saklı ihale yok, liste dışı
kâğıtların Tüm Kâğıtlar son işlem hücreleri boş, Bloomberg yanıtı ve kayıtlı kapanış henüz yok: bu kaynaklar bundan sonra
dolar. Son işlemden gelen son fark, piyasa fiyatı olan ve son noktası bugünden önceki bir işlem olan 2 kâğıtta (TRT050527T33,
TRT131027T36; ikisi de 02.11) +0,2 / +11,2 bp - medyan 5,7, en büyük 11,2 bp; aynı kâğıtlar kapanışlarından 5,6 / 10,9.

Kâğıt Fiyat Yükleme, kendi fiyatı olmayan kâğıda bu tablonun eğri fiyatını verir (aşağıda).

**Fiyat neden başlar?** ("Bunu sen bul. En çok neyi takip ediyor"): masanın kendi geçmişinde (17.11 veritabanı kopyası; 16
DİBS, 10.11.2025–16.11.2026) bir kâğıdın günlük getiri değişimi en çok **diğer kâğıtlara uydurulan eğriyi** izliyor (R²
1–3Y .73, 3–5Y .82, 5Y+ .81; OIS .50 / .54 / .47, offshore .39 / .40 / .27). 1 yıla kadar hiçbiri güçlü değil (.21 / .21 /
.14). Ertesi günün adilini "taban + dünkü fark" ile kurunca hata (sapma): komşu eğriyle 23 bp (1–3Y), 16 (3–5Y), 16 (5Y+);
1 yıla kadar OIS'le 37 bp. 20 / 60 günlük medyan fark %35–140 daha kötü (farklar kayıyor); offshore hiçbir vadede en iyi
değil.

* **Adil getiri** = her taban şimdi + kâğıdın o tabana **son kapanıştaki** (bugünden önceki son kapanış) farkı, vadeye göre
  ağırlıklı:
  * **Komşu eğri**: DİBS RV · Genel'in canlı Nelson-Siegel eğrisi, **kâğıt dışarıda** bırakılarak (diğer kâğıtların şimdiki
    getirilerine yeniden uydurulur); bono eğriye girmez, sabit kuponluların eğrisinde okunur;
  * **OIS**: TRY OIS Bootstrap'ın kâğıdın vadesindeki sıfır faizi (OIS spot'tan, yıllık bileşik);
  * ağırlıklar: **1 yıla kadar %75 OIS + %25 komşu**, **1–5Y %100 komşu**, **5Y üstü %75 komşu + %25 OIS**. Bir taban
    kurulamazsa payı diğerine geçer (satırın altında yazar).
  * Hepsi BIST bileşik getiride karşılaştırılır (sıfır faizler yıllık bileşiğe çevrilir). Adil, listedeki gibi **bileşik ve
    basit** getiri ve DİBS RV'nin valöründe (DİBS Trading'inki) **temiz fiyat** olarak gösterilir.
* **Kotan**: adilin iki yanında bid / ask getirisi ve fiyatı. Genişlik vade kovasına göre (≤1Y, 1–3Y, 3–5Y, 5Y+), başta
  hepsi **10 bp**. Yalnız **yöneticiler** sayfanın altındaki "Kotasyon genişliği"nden değiştirir; her değişiklik kaydedilir.
* **İyi seviyeler**: **Al ≥ adil + 2σ** (getiri yüksekse ucuz), **Sat ≤ adil − 2σ**; ±1σ gürültü bandı. σ, kâğıdın kendi
  son 60 kapanıştaki sonraki-gün hatası; kovanın tabanının altına inmez (37 / 23 / 16 / 16 bp). Geçmiş kısaysa (20 hatadan
  az) taban kullanılır ve σ'nın yanında `*` görünür.
* **Geri test** ("isabet %X (n)"): geçmişte kapanış adilin ±2σ ötesindeyken, 5 kapanış sonra adile olan fark kapanmış mı
  (fark, sinyalden önceki günün farklarıyla, kâğıt tabanlarına karşı ölçülür) ve ortalama kaç bp; ipucunda ucuz / pahalı
  ayrı. Masanın 17.11 kopyasında (bir yıl, az örnek) bu isabet %40–50 civarıydı: ±2σ seviyeleri "şu an adile göre
  olağandışı" demektir, geçmişte güvenilir biçimde geri dönmüş bir sinyal değil; adil seviye ve fiyatlama satırı ise
  ölçümde günden güne ~16–23 bp hatayla tuttu.
* **Piyasa şimdi**: Broker Chat tahtasının en iyi **taze** bid / offer'ı ve DİBS RV'nin canlı Bloomberg bid / ask'ı,
  adilden σ cinsinden. Offer adil + 2σ ya da üstündeyse **AL**, bid adil − 2σ ya da altındaysa **SAT**.
* **Bağlam**: komşu eğriye fark şimdi, son 20 kapanıştaki medyanının yanında.
* **Nasıl fiyatlandı**: her kâğıdın altında tek satır, ör. "Komşu eğri 37,62 + dünkü fark +8 bp = 37,70 · OIS 38,10 − 42 bp
  = 37,68 · %75 / %25 → adil 37,69 · fiyat 98,452 (valör 20.11)".

**Öngörülen** (masanın 19.11.2026 isteği: "Bu adil fiyat bir süre sonra ulaşmasını tahmin ettiğimiz fiyat gibi de olmalı.
Bir adil fiyat, bir de öngörülen fiyat olacak"): adilin yanında, kâğıdın **seçilen ufukta** ulaşması beklenen getiri ve
fiyat. Ufuk sayfanın üstündeki düğmelerle seçilir: **1 hafta / 2 hafta / 1 ay** (5 / 10 / 20 iş günü); seçim tarayıcıda
kalır, kâğıt kartı da onu gösterir (kartta da aynı düğmeler var). Sayfa **1 ay** ile açılır (geçmişte en iyi sonucu veren
ufuk).

* Ana tablonun **Öngörülen** sütunu: öngörülen **bileşik getiri** ve ufkun valöründeki **temiz fiyat**, yanında **model**.
  Üzerine gelince **basit getiri**, şimdiki getiriden **değişim (bp)**, **K/Z / 1 mn** (1 mn nominal alışın bu getiri
  değişiminden kârı / zararı, ufkun valöründe iki getirinin fiyat farkı; taşıma ve fonlama dahil değil), modelin hesabı
  ve **geri testi** ("geri test: RMSE 149 bp, değişmezse'ye göre %9,0 daha iyi, yön isabeti %64 (259)"); hesap satırı
  ayrıntıda (▸) da durur.
* **Modeller** (hepsi kâğıdın komşu eğriye farkı üzerinde): M0 değişmez; M1 fark son kapanışlardaki ortalamasına döner
  (AR(1)); **M2 eğri ve fark değişmezse** (yalnız vade kısalır: eğri aynı, kâğıt ufuk kadar kısa); M3 M1 + vade kısalması;
  **M4** M3 + OIS'in ima ettiği hareket (β × OIS forward'ı − bugünkü sıfır faiz, aynı kalan vade için).
* **Hangi model?** Masanın geçmişinde (19.11 veritabanı kopyası; 16 DİBS, 10.11.2025–16.11.2026; her tahmin yalnız o güne
  kadarki kapanışlarla, örnek dışı) ölçüldü. Önceden konan kural: kova ve ufuk başına en düşük RMSE'li model, "değişmez"i en
  az **%5** yeniyorsa kullanılır; yenen yoksa **eğri ve fark değişmezse** gösterilir ve bunu açıkça söyler. Sonuç:
  * **1 ay**: ≤ 1Y **M4** (120 kapanış; RMSE 166 bp, değişmez 179 bp: %7,4 daha iyi, yön isabeti %71) · 1–3Y **M4** (60
    kapanış; 149 / 164 bp: %9,0, yön isabeti %64) · 3–5Y ve 5Y+ hiçbir model yenemedi (eğri ve fark değişmezse);
  * **1 hafta, 2 hafta**: hiçbir kovada hiçbir model "değişmez"i %5 yenemedi (en iyisi %3'ün altında): eğri ve fark
    değişmezse.
  * Dürüst kayıt: haftalık hata 70–90 bp, aylık 120–180 bp; "değişmez"e göre kazanç yalnız 1 ayda kısa vadede var ve
    örnek küçük (yarım yıl, iç içe tahminler). Öngörülen bir yön tahmini değil, "bu kanıtla en olası seviye"dir.
* Kâğıdın geçmişi modele yetmezse (ör. 20'den az ardışık kapanış) yerine eğri ve fark değişmezse gösterilir, nedeni yazar.
  Ekranda getirisi olmayan kâğıtta başlangıç komşu eğri + son kapanıştaki farktır.

**OIS'e göre / FX swap'a göre**: her kâğıdın **DİBS Trading'deki aynı adlı sütunlarının** adil getirisi ve adil fiyatı
(kâğıdın ASW'si DİBS RV'nin OIS ASW eğrisinde / DİBS ASW'nin FX swap ima eğrisindeki ASW eğrisinde dursaydı); değerler,
ipuçları ve "yok" nedenleri DİBS Trading'inkiyle aynıdır.

Ana tablonun sırası: **Kâğıt · Piyasa · Eğri · Fiyat · Fark · Öngörülen · OIS'e göre · FX swap'a göre · Kart**. Ayrıntıların
(▸) sırası: **Kâğıt · Adil getiri · Kotan · İyi seviyeler · Piyasa şimdi · Bağlam**, altında nasıl fiyatlandı ve öngörülenin
satırı.

**Kâğıt kartı** aynı bloğu gösterir (en üstte eğri fiyatı satırı; trading listesinde olmayan kâğıtta yalnız o; adil, öngörülen ve ufuk düğmeleri, OIS'e / FX swap'a göre, kota, seviyeler, σ, geri
test, piyasa, nasıl fiyatlandı ve öngörülen). Geçmişin hesabı
(bir yılın günlük eğrileri) tarihçenin her değişiminde bir kez yapılır ve saklanır; dashboard açıldıktan bir dakika sonra
arka planda hazırlanır. Replay'de (kayıtlı dosya) kâğıt geçmişi yoktur: sayfa adil kurulamadığını ve nedenini söyler.

### Kâğıt Fiyat Yükleme

Menünün Tahvil grubunda, Kâğıt Fiyatlama'nın hemen altında (`#/fiyat-yukleme`; `tto/fiyatyukleme.py`,
`pages/fiyatyukleme.js`). Masanın günlük fiyat yüklemesi: seçtiğiniz kâğıtlara t0 için bid / ask getiri ve fiyat yapar,
kontrol ettikten sonra başka bir sisteme yüklenecek **txt dosyası** olarak kaydeder. Masanın 20.11.2026 isteği: "Bir de
kağıt fiyat yükleme sekmesi açmamız gerekli. Bu sekmede BBG/İhale olarak iki seçim olacak." Hiçbir şey bir yere
gönderilmez; dosya tarayıcıya iner.

* **Liste masanındır** (masa, 25.11.2026: "Kağıt fiyat yüklemedeki isin listesi tüm masa için olmalı"): herkes aynı
  listeyi görür ve biri çıkarana kadar kalır. Kâğıtlar, her kâğıdın spread'leri ve Mid / Bid/Ask'ı, varsayılan
  spread'ler ve Sabit fiyatlar herkes için birdir: oturum açan herkes değiştirebilir, değişiklik bütün masanındır (kim
  yükleme yaparsa aynı listeden aynı dosyayı çıkarır). Kişinin kendisinin olanlar: mod (BBG / İhale), yapıştırılan ihale
  metni, Hesapla ve tablosundaki düzenlemeler, kaydedilen dosyalar. Tablonun üstünde son değişikliği kimin ne zaman
  yaptığı yazar.
  * Başka biri listeyi değiştirince açık sayfanız da sayfayı yenilemeden güncellenir (sayfa yerinde kalır). O an bir
    spread kutusuna yazıyorsanız tablo siz kutudan çıkana kadar bekler; Ekle ve yapıştırma kutularına, kaydetmediğiniz
    varsayılan spread'e yazdıklarınız silinmez. Hesapla yapılmışsa "Masanın listesi değişti: yeniden Hesapla" yazar.
  * Güncellemeden önce herkesin kendi listesi vardı: güncellemeden sonraki ilk açılışta hepsi masanın listesinde
    birleşir. Herkesin bütün kâğıtları ve sabit fiyatları girer; iki kişide farklı ayarlı aynı kâğıt ve varsayılan
    spread'ler en son kaydeden kullanıcınınkidir (kâğıt ekleme, sabit fiyat girme, dosya kaydetme zamanlarının en
    yenisine göre), iki kişide farklı sabit fiyatı olan kâğıtta en son girilen fiyat geçerlidir. Eski listeler veritabanında
    olduğu gibi durur.
* Kutuya bir ISIN ya da ISIN listesi (satır satır ya da virgülle) yazıp **Ekle**; **×** çıkarır. Uzun liste kendi
  kutusunda kayar: bir satırın Mid / Bid/Ask'ı ya da spread'i kaydedilince liste de sayfa da yerinde kalır, imleç
  kullandığınız kutuda kalır (Tab oradan devam eder; Sabit fiyatlar ve Hesapla tablosunda da). Her satırda ISIN, kâğıdın
  adı, açıklaması (Bloomberg'in), vadesi ve türü. Kâğıt kataloğunda olmayan ISIN masanın listesine (Tüm Kâğıtlar) türü
  Bloomberg'den sorularak girer (yeni ISIN başına bir kez, Tüm Kâğıtlar'daki "+ ISIN ekle" gibi); Bloomberg yokken
  (kayıtlı veri) eklenemez, nedeni yazar.
* **Spread** ("İki tarafa da ayrı ayrı"):
  * getiriyle kote edilenler (sabit kuponlu, bono, kuponsuz): bid getiri = t0 + bid spread, ask getiri = t0 − ask spread
    (bp);
  * fiyatla kote edilenler (TLREF, FRN, TÜFE): bid fiyat = t0 − bid spread, ask fiyat = t0 + ask spread (fiyat puanı);
  * **Varsayılan spread** (getiri bid / ask, fiyat bid / ask; başta 5 bp / 5 bp ve 0,05 / 0,05) kendi spread'i olmayan
    her kâğıda uygulanır; Kaydet yalnız değiştirdiğiniz kutuları kaydeder (o arada başkasının değiştirdiği diğerleri
    kalır). Listede bir kâğıdın kutusuna yazılan spread o kâğıdın olur, boşaltınca varsayılana döner. Eksi değer olur
    (skew).
* **t0** bugünün valörüdür (bugün iş günü değilse sonraki TRY iş günü). Getiriler BIST **basit** getiri: bono / kuponsuz
  (100/P − 1)·365/gün; sabit kuponlu kuponları dönem başına (1 + y/f) ile iskonto eden oran (DİBS RV ve Hazine İhalesi
  sayfasının kuralı; kuponlar vadeden geriye 182 günde bir, birikmiş faiz c/f × geçen dönem payı).
* **İhale**: her sabah ihale fiyatlarını kutuya yapıştırın. Satır: `gg/aa/yyyy[etiket].t1|.t2  değer` (yıl iki haneli de
  olur: 13/01/27). "Auction prices:", "** Min 50 mio, Increment 1 mio" gibi diğer satırlar yok sayılır.
  * Değer: bono / kuponsuzda **basit getiri** (31.500 = %31,5), diğerlerinde **temiz fiyat**. `.t1` T+1, `.t2` T+2 valör
    (yapıştırılan günden, TRY iş günü).
  * Etiket: `zc` aynı vadede kuponlu varken kuponsuz, `TLREF` TLREF'e endeksli, `cpi` TÜFE'ye endeksli. Etiketsiz satır o
    vadenin sabit kuponlusu, sabit kuponlu yoksa bonosu / kuponsuzu.
  * Bir kâğıdın `.t1` satırı kullanılır, `.t2` yalnız `.t1` yoksa.
  * t0: getiriyle kote edilen kâğıtta satırın valöründeki getiri t0'da aynen kullanılır, fiyatı t0'da o getiriden.
    Fiyatla kote edilende ihalenin temiz fiyatı t0 fiyatıdır.
  * **Tanınamayan satır** (o vadede o türde kâğıt yok ya da birden çok var): "Tanınamadı" ve nedeni, yanında o tarihe yakın
    vadeli kâğıtlar ve bir ISIN kutusu. **Tanıt** ile bir kez tanıtılan etiket (`.t1` / `.t2`'siz) **masa için hep** o
    kâğıt olarak tanınır. Tanıtılan etiketler sayfanın altındadır; kâğıt listesi gibi masanındır, herkes silebilir.
  * Her yapıştırmada tanınan satırların değeri kâğıt başına saklanır (gün, etiket, değer, .t1 / .t2): BBG'nin "son ihale
    fiyatı" budur.
* **BBG**: mid = Bloomberg'in son işlemi.
  * Trading listesindeki kâğıtlar (DİBS RV): DİBS RV'nin kendi `LAST_PRICE` / `LAST_TRADE_DATE` hücreleri. Zaten isteniyor,
    yeni maliyet yok.
  * Diğerleri: **Hesapla'ya basınca** tek seferlik Bloomberg isteği (`LAST_PRICE`, `LAST_TRADE_DATE`: **kâğıt başına 2
    hit**), cevap 5 dakika saklanır (üst üste basmak yeniden harcamaz); abonelik ya da yenileme yok. Kâğıt Tüm Kâğıtlar'daki
    adıyla sorulur (bono / kuponsuz ISL0, diğerleri ISL1). Gelen son işlem (gün, fiyat) ayrıca kâğıt başına saklanır
    (daha yeni bir işlem gelince değişir): Kâğıt Fiyatlama'nın son farkı onu da kullanır.
  * Son işlem **bugünse**: sabit kuponluda temiz fiyat (valöründeki getirisi t0'da aynen), bonoda fiyat → basit getiri,
    fiyatla kote edilende fiyat. Bloomberg bononun son işlemini getiri olarak verirse (fiyat sayılınca getirisi akla
    yatmıyorsa, ya da kâğıdın kendi getirisine o okuma daha yakınsa) getiri olarak okunur ve satır söyler.
  * Son işlem **bugün değilse**, referans son işlem ile kayıtlı son ihaleden **daha yeni olanıdır**: işlem tarihinde ya da
    sonra kaydedilmiş bir ihale varsa ihale; işlem bütün ihalelerden yeniyse (ya da hiç ihale yoksa) o işlem, kendi
    valöründe okunur (masa, 20.11.2026: "dün işlem olmasına rağmen son işlem dün diyor ve göstermiyor" - sabah piyasa
    açılmadan dünkü son işlem + gecenin hareketi). Fiyatla kote edilende o referansın fiyatı olduğu gibi. Getiriyle:
  * referansın getirisi + o günün kapanışından bu yana **tahvil eğrisinin hareketi**
    (trading listesinin getirilerine uydurulan Nelson-Siegel eğrisi, DİBS RV · Genel'inki: şimdiki eğri ile o günün
    kapanışlarına aynı τ'yla uydurulan eğri arasındaki fark, kâğıdın t0'dan nakit akışlarıyla). Eğri kurulamazsa TRY OIS
    Bootstrap sıfır faizinin kâğıdın vadesindeki değişimi; satır söyler. İhale bugünse hareket yoktur. Ne işlem ne
    kayıtlı ihale varsa fiyat yoktur, satır nedenini söyler.
  * Kayıtlı veride (replay) Bloomberg yoktur: trading listesindekiler DİBS RV'nin kayıtlı son işleminden, diğerleri son
    ihale + eğri hareketinden (satır söyler).
* **Eurobond** (masanın aynı geceki eki: "Eklenecek listede eurobondlar da olacak. Bunlar direkt bbgden fiyatlanacak.
  Bunlarda last trade yok direkt midden ve spreadden gideceğiz" · "Eurobondlar da yield spreadi"):
  * USD / EUR Türkiye Eurobond'u ISIN'iyle (`US900123…`, `XS…`) listeye eklenir, tek tek ya da liste olarak. Bilgileri
    (açıklama, para birimi, kupon, yılda kupon sayısı, gün sayımı, vade, kupon tarihleri, valör gecikmesi) **ISIN başına
    bir kez** Bloomberg'den sorulur ve masa için saklanır; DİBS kataloğuna girmez. Satırda tür "Eurobond" ve para birimi.
    Bloomberg yokken (kayıtlı veri) eklenemez, nedeni yazar.
  * **Mod ne olursa olsun** Bloomberg'in mid'inden fiyatlanır (ihale ya da son işlem değil): mid fiyat `PX_MID` (boşsa
    `PX_BID` / `PX_ASK`'ın ortası, söylenir), mid getiri `YLD_YTM_MID`. **Kâğıt başına 2 hit** her Hesapla'da (mid boşsa ya
    da Bid/Ask seçiliyse 2 daha), 5 dakika saklanır.
  * Bid getiri = mid + bid spread, ask getiri = mid − ask spread (**bp**; Eurobond'un kendi varsayılanı, başta 2 / 2 bp;
    listede kâğıt başına değişir).
  * Fiyatlar kâğıdın kendi kuralıyla (sokak kuralı: 30/360 ya da ACT/ACT, yılda 1 ya da 2 kupon) ve **Bloomberg'e
    çapalı**: fiyat(y) = kural(y) + (PX_MID − kural(mid getiri)). Mid Bloomberg'inkiyle birebir aynıdır; çapa farkı
    ipucunda görünür, 0,05 fiyat puanını aşarsa satır uyarır. Valör Bloomberg'in `DAYS_TO_SETTLE`'ı kadar iş günü sonra
    (USD için Fed, EUR için TARGET2 tatilleri; yoksa T+2, söylenir). Düzenlenen getiri / fiyat aynı çapalı kuralla.
  * Dosyada temiz fiyatla, getiriler 0: `ISIN,99.875,100.125,0,0`.
* **Mid / Bid/Ask** (masa, 23.11.2026: "Kağıt fiyat yükleme listesinde bloomberg'te kağıt kağıt bid'i ve ask'i mid'den mi,
  bid/asktan mı almasını istediğimi de seçebilmeliyim. Default mid"): listede her kâğıdın **BBG'den** kutusu.
  * **Mid** (varsayılan; önceki gibi): iki taraf da mid'den, spread'ler iki yanına.
  * **Bid/Ask**: bid tarafı Bloomberg'in bid'inden, ask tarafı ask'inden başlar; spread'ler her biri kendi tarafına
    (getiriyle kote edilende getiri spread'i, fiyatla kote edilende fiyat spread'i). Spread 0 ise ekrandaki fiyat. Her taraf
    son işlem gibi okunur: valöründeki fiyattan basit getiri, t0'da aynı getiri (bonoda fiyat → basit getiri); fiyatla kote
    edilende fiyat olduğu gibi. t0 / mid sütunu iki tarafın ortası.
  * Başlıktaki **Tümü** listedeki bütün kâğıtları birden Mid ya da Bid/Ask yapar. Seçim masanın listesiyle, ISIN'iyle
    saklanır: listeye kâğıt girip çıkınca, satırlar kayınca da kâğıdın kalır.
  * DİBS RV'deki kâğıt: DİBS RV'nin bid / ask'ı (`K` / `L`; zaten isteniyor, **yeni maliyet yok**). Emir büyüklüğü (`XR` /
    `XS`) canlı emir yok diyorsa ("–") satır mid'den fiyatlanır ve söyler.
  * Diğer DİBS (BBG modunda) ve Eurobond (her modda): **Hesapla'ya basınca** Bloomberg'e `PX_BID` / `PX_ASK` sorulur -
    **yalnız Bid/Ask seçilen kâğıda, kâğıt başına 2 hit**, cevap 5 dakika saklanır (masanın onayı, 23.11.2026). Mid seçilene
    yeni istek yok. Hesapla'nın özeti bu hit'leri de sayar ve kaç kâğıdın bid / ask'tan, kaçının mid'den fiyatlandığını söyler.
  * DİBS'te **bid ask'e eşitse** emir yoktur (Bloomberg iki tarafa da son işlemi verir): satır mid'den fiyatlanır, nedenini
    söyler. Taraflardan biri yoksa da öyle.
  * Eurobond: tarafların getirisi sokak kuralıyla, mid gibi Bloomberg'e çapalı (fiyattan çapa farkı çıkarılarak); t0 / mid
    sütunu Bloomberg'in mid'idir.
  * İhale modunda DİBS ihale fiyatından gelir: seçim yalnız BBG modunda (Eurobond'da her modda) kullanılır.
* **Hesapla**, sonra tablo: kâğıt, açıklama, vade, t0 getiri ve fiyatı, bid / ask getiri ve fiyatı, dosyaya ne yazılacağı
  ve nasıl hesaplandığı. **Her hücre düzenlenebilir**: getiri değişince fiyatı, fiyat değişince getirisi aynı kurallarla
  (sunucuda) yeniden hesaplanır ve kaydetmeden önce görünür.
* **Kaydet (txt)**: `dibs_fiyat_YYYYMMDD.txt` iner. Her kâğıt bir satır, `ISIN,fiyatbid,fiyatask,yieldbid,yieldask`:
  * bono ve kuponsuz **getiriyle** (basit, %), fiyatlar 0: `TRB100227T13,0,0,31.750,31.650`;
  * diğerleri **temiz fiyatla**, getiriler 0: `TRT130127T11,100.450,100.550,0,0` ("hangisi yazıldıysa diğerleri 0");
  * üç ondalık, nokta, CRLF, ASCII, başlıksız. Fiyatı olmayan kâğıt yazılmaz (söylenir); bid'i ask'ten iyi olan uyarılır.
    Sayfa yazılacak satırları önceden gösterir. Günün dosyaları saklanır: **Bugünkü dosya** sonuncuyu yeniden indirir.
* **Sabit fiyat** (masanın 20.11.2026 sabahki isteği: "Bir de sabit fiyat kısmı açmalıyız, bazı kağıtları direkt bu
  şekilde yüklenecek diye girip bırakabilmeliyim"):
  * **Excel'den yapıştırma** ("Sabitlemeyi de tablo olarak atacağım excelden kopyalayıp, bu da ayrıca tablo olarak
    gözükmeli ve ben de rahat görebilmeliyim. Burada bid ve offer'ı ve ISIN'i kopyalayacağım"): satırları kutuya
    yapıştırıp **Ekle / Güncelle**. Her satır bir kâğıt; hücreler Excel'in kopyaladığı gibi sekmeyle (yoksa birkaç
    boşlukla) ayrılır. ISIN ilk ISIN'e benzeyen hücre, **bid** ondan sonraki ilk sayı, **offer** bid'in ±%10'u içindeki
    sonraki sayı: aradaki boş sütun, getiri (4.74, %4,49) ve stok (42,000) sütunları atlanır. Nokta da virgül de ondalık
    olur (ikisi birden varsa sonuncusu). Başlık ve "USD" / "EUR" gibi satırlar yok sayılır; okunamayan satır nedeniyle
    gösterilir (offer yok, offer bid'den küçük, ISIN'in kontrol hanesi…). Aynı ISIN yeniden yapıştırılınca güncellenir.
  * **Katalog gerekmez**: yalnız ISIN, bid ve offer. Açıklama katalogdan, yoksa saklanan Eurobond bilgisinden, yoksa
    `TRT…F…` için "döviz DİBS"; vade katalogdan, yoksa ISIN'den (`TRT191127F19` → 19.11.2027). Birim: bono ve kuponsuz
    (katalogdaki türü ya da `TRB…`) **getiri** (%, basit), diğerleri (sabit kuponlu, TLREF, TÜFE, FRN, Eurobond, döviz
    DİBS) **temiz fiyat**.
  * **Sabit fiyatlar tablosu**: ISIN, açıklama, vade, birim, bid, offer (3 ondalık, kutudan değiştirilir) ve verdiği
    dosya satırı (`TRT191127F19,99.483,99.726,0,0`); **×** çıkarır. Değerler liste gibi masanındır, biri değiştirene ya
    da çıkarana kadar kalır.
  * **Hesapla**'da (İhale de BBG de) her sabit kâğıt tabloda **olduğu gibi** durur, "sabit fiyat" yazar; diğer birimi
    yalnız bilgi içindir (bononun t0 fiyatı sabit getiriden, kuponlunun getirisi sabit fiyattan, Eurobond'unki sokak
    kuralıyla). Hesaplanmaz, Bloomberg'e sorulmaz: trading listesinde olmayan sabit kâğıt BBG modunda hit harcamaz.
    Listede de olan kâğıtta sabit fiyat geçerlidir, satır söyler.
  * Hücreleri düzenlenebilir ama değişiklik **yalnız o Hesapla** içindir; kayıtlı sabit değer değişmez (ipucu söyler).
  * Hesaplanan bir satırdaki **Sabitle** düğmesi o satırın şimdiki bid / ask'ini (düzenlendiyse düzenlenmiş hâlini)
    sabit fiyat olarak kaydeder.
  * Kaydet'te sabit kâğıtlar aynı satır biçiminde, girildiği gibi yazılır (diğer birim 0).
  * Listede yalnız sabit kâğıtlar (ya da Eurobond'lar) varsa İhale modunda metin gerekmez.
* **Eğri fiyatı** (masa, 20.11.2026): İhale de BBG de, getiriyle kote edilen (sabit kuponlu, bono, kuponsuz) ve başka
  fiyatı olmayan kâğıt - bugünkü ihale metninde yok, ya da bugün işlemi ve kayıtlı ihalesi yok - Kâğıt Fiyatlama'nın
  eğri fiyatını alır (kovanın tabanı + kâğıdın son bilinen noktasındaki farkı - kapanış, ihale ya da son işlem, en
  yenisi; hiç noktası yoksa sabit kuponluda eğri, bono / kuponsuzda taban + akranlarının farkı): o valördeki basit getirisi
  t0 getirisi olur, spreadler her getirili kâğıttaki gibi uygulanır. Satır hangisi olduğunu yazar - **eğri fiyatı (son
  fark, ihale 20.11)** / **(son fark, son işlem 14.11)** / **(son fark, kapanış 19.11)**, **eğri fiyatı (akran farkı)** ya
  da **eğri fiyatı** (sabit kuponluda eğri, akransız bonoda taban) -, nasıl kurulduğu ve **tipik hatası** yanında:
  kaydetmeden önce görülür. Fiyatla kote edilenler ve Eurobond'lar değişmez; sabit fiyat yine önce gelir. İhale ve BBG'nin
  bir işlemi ya da ihaleyi eğriyle taşıyan yolları olduğu gibi kalır (aynı fikir).

### DİBS RV (genel sayfa)

Menünün Tahvil grubunda **DİBS RV** tek giriştir, üç sekmesiyle: **Genel** (`#/dibs-genel`; dashboard'un kendi sayfası,
`tto/dibsgenel.py`, `pages/dibsgenel.js`), **RV hesap tablosu** (DİBS RV sayfası, `#/dibs`) ve **ASW hesap tablosu**
(DİBS ASW sayfası, `#/asw`). İki sayfa adreslerini, başlıklarını ve tablolarını korur: launchpad kutuları, alarmlar,
izlenen hücreler, Ctrl+K ve kâğıt kartının bağlantıları eskisi gibi çalışır; menüde ayrı girişleri yoktur. Girişe
tıklamak son açılan sekmeye gider (ilk seferde Genel). Yeni Bloomberg isteği yoktur.

**Genel**: trading listesinin kâğıtları türüne ve vadesine göre (DİBS Trading özeti gibi) tek tabloda, sütunlar gruplu:

* **Kâğıt** (ad, ISIN, vade, kalan yıl) · **Fiyat** (valörün kaynağı, bid / ask - emir yokken "–", DİBS RV'deki gibi -,
  son işlem ve günü, kullanılan temiz) · **Getiri** (BIST bileşik ve basit: DİBS RV!T / S; ve getirinin **ON karşılığı**,
  DİBS RV!BO - aşağıda: *Getirinin ON karşılığı*);
* **OIS ASW**: DİBS RV'nin ASW / DM'i, uydurulan eğrinin kâğıdın vadesindeki ASW'si, pahalı / ucuz, sinyal, adil getiri
  ve adil fiyat;
* **FX swap ASW · FX swap ima eğrisi (TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden; fiyatı yoksa OIS)**: aynı altı sütun, DİBS ASW'nin bu eğrideki
  hesabından (ASW FX, eğri, ucuz / pahalı; sinyal DİBS RV'nin eşiğiyle) - DİBS Trading'in özeti ve kâğıt kartıyla aynı
  sayılar. DİBS RV'nin kendi FX sütunları (FX swap - offshore ICAP eğrisi) yalnız RV hesap tablosundadır;
* **Sıfır kupon eğrisi (NS)**: model getiri, pahalı / ucuz (bp, + ucuz) ve adil fiyat - aşağıda;
* **Risk** (mod. süre, DV01 / 1mn, OIS hedge oranı) · **Carry** (C+R) · **Broker** (bugünün Broker Chat tahtası, DİBS
  Trading'deki gibi) · ▸ kâğıt kartı · ★ trading listesinden çıkarır.

Her sayı kaynağınındır (DİBS RV'nin hücresi, `rvfair`'in adil değeri, DİBS ASW'nin FX hesabı, canlı uyum); üzerine gelince
hesabı. Satırlar kâğıda (ISIN) bağlıdır: liste değişince, ortadaki boş satıra kâğıt eklenince ya da çıkınca her kâğıt kendi
sayılarıyla, kendi grubunda, vadesine göre durur. TLREF / FRN / TÜFE kâğıtları ASW eğrilerine ve sıfır kupon eğrisine
karşı ölçülmez; hücrede soluk "–", nedeni üzerinde (fiyatı olmayan kâğıtta da).

**Sıfır kupon eğrisi.** Trading listesinin **sabit kuponlularına** (en az 6 kâğıt) **şimdi** uydurulan **Nelson-Siegel**
eğrisi (üç β, bir τ: tek tümsek). **Bonolar uydurmaya girmez** (masanın kararı, 18.11.2026 - aşağıda): listede kalır,
BIST kuralıyla (basit getiri, sayfanın fiyatladığı gibi) eğride fiyatlanır; model getirisi, pahalı / ucuzu ve adil fiyatı
her kâğıdınki gibi gösterilir, ipucu "uydurmaya girmez, eğriye karşı ölçülür" der. Bononun getirisi eğriyi oynatmaz,
pahalı / ucuzu kupon tahvillerinin eğrisinin kısa ucuna göredir. Hesap quant'ın "DİBS adil değeri"nin aynısıdır
(`quantcurve.dibs_search`, tek uygulama): kâğıtlar DİBS RV'den aynı okumayla (kullanıcının kendi hesabıyla: elle fiyatı,
fiyat tipi yansır) basit getirileriyle (`S`), BIST kuralıyla fiyatlanır; τ sabit kuponluların şimdiki getirileriyle
aranır, β'lar onunla uydurulur (Huber ile sağlam) - aynı girdilerle `quantcurve.fam_dibs`'in sonuçlarını verir (testle).
**Pahalı / ucuz** = getiri − model getiri (bp, basit getiri kuralıyla; + ucuz: al, − pahalı: sat), **model getiri** =
getiri − pahalı / ucuz (quant sayfasındaki "Model"), **adil fiyat** = nakit akışlarının eğrideki değeri (Σ CF·DF) − işlemiş
faiz (quant'ın adil eğriden kotasıyla aynı). Aynı girdilerle uyum saklanır; getiriler değişince yalnız β'lar yeniden
uydurulur (τ kâğıtlar ya da gün değişince yeniden aranır), quant'ın canlı uyumu gibi. Sayfanın üstündeki satır uyumun
kalitesini ve parametrelerini söyler: model (NS), RMSE ve **LOO RMSE** (bp; uydurulan her kâğıt, eğri o olmadan yeniden
uydurulunca - τ aynı - eğriden ne kadar uzak: eğrinin görmediği kâğıdı ne kadar tutturduğu), uydurulan sabit kuponlu
sayısı ve eğriye göre ölçülen bono sayısı, ağırlığı düşürülen kâğıt (Huber), β0…β2 (%), τ1 (yıl) ve eğrinin 1Y / 2Y / 5Y /
10Y zero faizleri.

*Neden Nelson-Siegel (18.11.2026).* Önceki eğri Svensson'du (dört β, iki τ), yalnız sabit kuponlulara: kayıtlı veride
(03.11.2026, 13 kâğıt) RMSE 51 bp ama β = 391,8 / −361,8 / 43,3 / −910,4 %, τ2 sınırda (8,84 yıl = en uzun vade) - eğri
gürültüye uyuyordu, bonolar 140–220 bp pahalı görünüyordu. Kanıt (kayıtlı gün ve quant ailesinin yaptığı gibi günlük
uydurulan geçmişler):

| | Önce: NSS, sabit kuponlu | NS, sabit kuponlu + bono (18.11 sabahı) | **Şimdi: NS, sabit kuponlu** (masanın kararı) |
|---|---|---|---|
| RMSE (uydurulan kâğıtlar) | 51,4 bp (13) | 70,6 bp (15) | 53,2 bp (13) |
| LOO RMSE, 15 kâğıt, τ yeniden aranarak | 104,7 bp | 95,6 bp | 95,1 bp |
| LOO RMSE, τ sabit (sayfadaki) | 74,0 bp (13 kupon) | 89,2 bp (15) | 66,8 bp (13 kupon) |
| en büyük \|fark\| (hepsi) | 223,1 bp | 149,6 bp | 221,3 bp |
| eşiği (P2, 5 bp) / 50 bp'yi aşan | 13 / 7 kâğıt | 13 / 7 kâğıt | 15 / 7 kâğıt |
| bonolar (10.02.27 / 17.03.27) | −141,5 / −223,1 bp | −45,3 / −149,6 bp | −134,4 / −221,3 bp |
| β (%) · τ (yıl) | 391,8 / −361,8 / 43,3 / −910,4 · 3,60 / 8,84 | 23,3 / 4,9 / 27,5 · 1,28 | 22,0 / 7,7 / 26,0 · 1,56 |
| β'nın günlük değişimi (σ, puan) | 16,6 / 16,7 / 1,0 / 39,6 | 0,2 / 0,2 / 0,5 | ölçülmedi |
| eğrinin piyasa dışı günlük oynaması, 0,5 / 2 / 5 yıl | 6,1 / 2,9 / 4,0 bp | 7,4 / 2,4 / 2,1 bp | ölçülmedi |

Günlük satırlar kayıtlı güne bağlanmış 260 günlük bir geçmişten (kâğıtların kayıtlı günkü farkları sabit, piyasa seviye /
eğim / eğrilik hareketi ve kâğıt başına AR(1) sapma; gerçek DİBS geçmişi depoda yok); son sütunun satırları kayıtlı günün
aynı girdileriyle (Huber'li uyumda hiçbir kâğıdın ağırlığı düşmüyor). Svensson'un iki fazla parametresi kayıtlı günde
dışarıda bırakılan kâğıdı daha iyi tahmin etmedi (bonolar olmadan da: 85 / 73 bp); 8 – 40 kâğıtlık sentetik listelerde
(Svensson eğrisinden ve NS eğrisinden fiyatlanmış, σ 5 / 25 / 50 bp, 36 durum) NS'in LOO'su 34'ünde düşük ya da eşit kaldı -
iki istisna aynı rastgele çekiliş (24 kâğıt, σ 50 bp), biri NS'ten fiyatlanmış listede: gürültü. **Kural:** DİBS eğrisi
kâğıt sayısından bağımsız olarak NS - listenin tutabileceği hiçbir kâğıt sayısında Svensson kazanmıyor (OIS eğrisi 16
vadede 1–3 bp ile Svensson kalır). **Bonolar ve kısa uç:** kayıtlı veride bono ile aynı gün vadeli kupon tahvili
(TRB100227T13 ve TRT100227T13, 10.02.27) ~140 bp ayrı - hiçbir eğri ikisinden birden geçemez; bonolar uydurmaya girince
fark ikisine bölünür: bono −45 bp pahalı, kupon tahvili +106 bp ucuz (önce +1,5). Bu fark eğrinin değil piyasanındır.

**Masanın kararı (18.11.2026): bonolar uydurmaya girmez.** Eğri yalnız sabit kuponlulara uydurulur, model NS kalır
(bonolar olmadan da dışarıda bırakılan kâğıdı Svensson'dan iyi tahmin ediyor: LOO 73 / 85 bp). Bonolar listede kalır,
eğride fiyatlanır, model getirisi ve pahalı / ucuzu her kâğıdınki gibi gösterilir - ama artık kupon tahvillerinin
eğrisinin kısa ucuna göre: kayıtlı günde 10.02.27 / 17.03.27 bonoları **−134 / −221 bp pahalı** (uydurmadayken −45 / −150),
aynı gün vadeli kupon tahvili TRT100227T13 +9 bp (uydurmadayken +106). Masanın ekranda gördüğü budur ve bu masanın
seçimidir: eğri bonoya bükülmez, bononun kupon eğrisine göre pahalılığı olduğu gibi okunur. Listenin 15 kâğıdında
dışarıda bırakılan kâğıdın hatası aynı kalır (LOO, τ yeniden aranarak: 95,1 bp; bonolar uydurmadayken 95,6): hata
bonolara taşınır, kupon tahvillerinde küçülür (13 kâğıtta RMSE 53,2 bp, LOO 66,8 bp). Quant'ın "DİBS adil değeri"
ailesi de aynı uyumu kullanır.

**Grafikler.** **Getiri eğrisi**: her kâğıt kalan vadesinde bileşik getirisiyle (etiketli), uydurulan eğrinin **par
getirisi** (eğride temiz fiyatı 100 olan kâğıdın getirisi; kupon 182 günde bir, BIST) ve **zero faizi** (ikisi de yıllık
bileşik), karşılaştırma için DİBS RV'nin kâğıdın vadesindeki OIS par faizi (`X`). **ASW · OIS** ve **ASW · FX swap**: DİBS
ASW'nin kendi iki grafiği, sayfasının çizdiği gibi (aynı veri).

**Hesap tablosundan, salt okunur.** DİBS RV'nin **SWITCH / PAIR** tablosu ve DİBS ASW'nin **ASW geçmişi** (seçili
kâğıtlar ve grafiği) sayfalarının çizdiği gibi; Genel'deki sayıların okuduğu ayarlar (sinyal eşiği, C+R ufku, fiyat tipi,
varsayılan repo, genel kaynak) sayfanın üstünde. Girdiler hesap tablosu sekmelerinde yazılır: Genel'de bir ayara ya da
tablonun girdi hücresine tıklayınca o sekme açılır, hücre seçili gelir (hemen yazılabilir).

**RV hesap tablosu: seviyeden temiz fiyat** (masa, 24.11.2026; DİBS RV sayfası, `#/dibs`). İki ters hesap, ikisi de **DİBS
RV'nin TRY OIS eğrisine göre** (Motor'un bootstrap'ı, Ayarlar'daki eğri interpolasyonunuzla) - DİBS ASW sayfasının kendi
eğrisi ve FX swap ASW'leri değil:

* **ASW / DM → temiz fiyat** (kâğıt tablosunun hemen altında kendi tablosu, `DİBS RV!BK:BN`): **Hedef ASW / DM (bp)**
  sütununa sabit kuponlu ve bonoda ASW'yi, TLREF'li kâğıtta DM'i yazın: **Temiz (hedeften)** kâğıdın o ASW / DM'deki temiz
  fiyatıdır. ASW sayfanın kendi formülü tersinden (`EH` = (PV − kirli @OIS spot) / annuity · 100: kirli = PV − ASW ·
  annuity / 100, valöre fonlama çarpanıyla, işlemiş düşülür); DM'de kâğıdın nakit akışları (öngörülen kuponlar) dönem
  dönem ileri TLREF + DM ile iskonto edilir - sayfanın DM çözücüsünün (`EL:EN`) fiyatı, Manuel Tahvil'in DM hedefi gibi.
  Bulunan fiyat Manuel temiz'e yazılınca ASW / DM tam yazılan değer çıkar (ASW / DM sütunu 0,1 bp'ye yuvarlı gösterir).
  **Fark** = bu temiz − kullanılan temiz; **Not** neyden hesaplandığını (ASW'den / DM'den) ya da neden hesaplanmadığını
  söyler: FRN'nin DM'i yoktur (yalnız fiyatla izlenir), TÜFE'nin ASW'si yoktur; fiyatı olmayan kâğıtta önce Manuel temiz'e
  herhangi bir fiyat yazın (sonuç ona bağlı değildir).
* **SWITCH / PAIR: seviyeden Al fiyatı** (tablonun sağında, `U:Z`; altında notu): **Getiri seviyesi (bp)** = Al − Sat BIST
  basit getirisi (tablonun "Getiri farkı"), **ASW/DM seviyesi (bp)** = Al − Sat ASW / DM (tablonun "ASW/DM farkı": sabit
  kuponlu ve bono ASW, TLREF DM; karışık çiftte ASW'ye karşı DM). **Sat bacağı piyasada kalır** (kullanılan temiz fiyatının
  getirisi / ASW-DM'i, G ve I sütunlarındaki), **Al bacağı seviyeden çözülür**: Al temiz, Al bacağının nakit akışlarından
  (getiri; bonoda `100 / (1 + getiri · gün / 365)`) ya da ASW / DM'inden; yanında Al'ın şimdiki temizi ve **Seviye notu**
  (TLREF / FRN bacağında getiri, FRN / TÜFE'de ASW-DM yok). Bulunan fiyat Al bacağının Manuel temiz'ine yazılınca "Getiri
  farkı" / "ASW/DM farkı" tam seviyeyi gösterir. Çift ISIN'leriyle yazıldığından kâğıtlar listede yer değiştirse de seviye
  çiftindir. DİBS RV · Genel'deki switch tablosu bu sütunları da salt okunur gösterir.

Girdiler kişiseldir, başta boştur; kâğıt tablosundaki hedef kâğıtla taşınır. Yeni Bloomberg isteği yok.

**RV hesap tablosu iki yönlüdür** (masa, 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar
bu şekilde olmalı karışıklık olmaması için"; genel kural: Kullanım'daki *İki yönlü tablolar*). Yukarıdaki iki tablo kalır;
aynı şey artık tabloların kendisinde de yapılır:

* **Kâğıt satırı**: **Manuel temiz**, **BIST basit getiri**, **BIST bileşik getiri**, **Getiri − OIS**, **ASW / DM**,
  **Z-spread** ve **ON karşılık %** (26.11.2026, aşağıda: *Getirinin ON karşılığı*) - hangisini yazarsanız o kalır (✎), Manuel temiz onun verdiği temiz fiyat olur, öbürleri o fiyattan tablonun
  kendi formülleriyle. Ters hesaplar: basit getiri → bonoda 100 / (1 + getiri · gün / 365), kuponluda Σ CF / (1 + getiri /
  f)^x; bileşik getiri → bonoda 100 / (1 + getiri)^(gün / 365), kuponluda önce basit getiriye (f · ((1 + bileşik)^(1/f) −
  1)); getiri − OIS → bileşik getiri = vadedeki OIS par (bileşik) + fark; ASW / DM → "ASW / DM → temiz fiyat"ın aynı
  formülleri (sabit kuponlu ve bonoda ASW, TLREF'lide DM); Z-spread → Σ CF · DF(OIS) · e^(−z·t) / fonlama − işlemiş.
  **"Fiyat durumu"** neyden fiyatlandığını söyler ("ASW'den (yazılan)"); kâğıdın olmayan bir değeri (TLREF'lide getiri,
  TÜFE'lide ASW, FRN'de spread) yazılırsa yazılan kalır ama fiyat vermez: satır piyasada kalır, "Fiyat durumu" "Yazılan
  basit getiri bu kâğıtta yok: fiyat piyasadan" der. **Fiyatı olmayan kâğıtta da çalışır** (ters hesap fiyata bakmaz;
  satırın "fiyat yok" bekçisi yazılan bir değerle açılır). Elle fiyatlanan satırda (Manuel temiz yazılı ya da bir değer
  yazılı) getiri − OIS, ASW / DM ve Z-spread 0,1 bp'ye yuvarlanmaz, getiri ve Z-spread çözücüleri iki adım daha atar:
  hesaplanan bir değeri kendi sütununa geri yazmak aynı satırı verir (1e-9). Hiçbir şey yazılmamış satırlar eskisi gibi.
* **Yazılan değer kâğıda varsayımsal bir temiz fiyat verir**: eğri oynadıkça o fiyat da oynar, yazılan değer aynen kalır.
  Bu fiyat **sizin hesabınızda kâğıdın fiyatını okuyan her yerde** kullanılır: eğri uyumu ve bütün kâğıtların pahalı /
  ucuz'u ve sinyalleri, Masa'daki sinyaller, switch bacakları, DİBS Trading, Tüm Kâğıtlar'daki getiri / ASW, Manuel
  Tahvil'in ISIN fiyatı, Kâğıt Fiyatlama ve DİBS RV · Genel - Manuel temiz yazdığınızda olduğu gibi. Masanın ortak hesabı
  (alarmlar, quant, Trades) değişmez.
* **Repo ↔ carry**: **Repo (%)** ya da **Carry (bp)** - hangisini yazarsanız o kalır; carry yazılınca gereken repo carry'nin
  kendi formülleri tersinden (TLREF'lide kendi formülüyle); silince OIS fonlaması / varsayılan repo döner.
* **SWITCH / PAIR**: **Getiri farkı** ya da **ASW/DM farkı** yazılabilir - yazılan kalır (✎); Al bacağının o farktaki temiz
  fiyatı tablonun sağındaki **Al temiz (yazılan farktan)** sütununda (Sat bacağı tablodaki fiyatında), öbür fark o
  fiyattan: getiri farkından ASW'si (kapalı formül), ASW/DM farkından getirisi (DİBS RV'nin kendi getiri adımlarıyla -
  Al'ın satırına o fiyat elle yazılsa gösterilecek getiri). **Al kâğıdının kendi satırı ve Manuel temiz'i değişmez** (o
  fiyat başka çiftlerin ve satırın kendisinin); satırın öbür sütunları kâğıtların tablodaki fiyatlarıyla kalır. Getirisi
  olmayan bacakta (TLREF / FRN) getiri farkı fiyat vermez, ASW / DM'i olmayanda (FRN / TÜFE) ASW/DM farkı: Al temiz
  sütunu nedenini yazar. Çiftin farkları satırındaki ISIN'leriyle yazılan çiftindir.

Yazılanlar kişiseldir; kâğıt satırınınkiler gizli `YF:YL` sütunlarında (yardımcı tablo "iki yönlü") saklanır ve kâğıt
listede yer değiştirince kâğıtla gider. Önceden yazdığınız Manuel temiz ve repo aynen durur; bir getiri / ASW hücresinin
üzerine "Elle değer" yazdıysanız o satırın yazılanı olur. Yeni Bloomberg isteği yok.

**Getirinin ON karşılığı** (masa, 26.11.2026: "Bunların da hepsini yap" - "Toplu forward fiyatlama kısımlarında ON
karşılıklarını da görmek istiyorum. Bu ve bunun gibi başka önerin olur mu" sorusuna gelen önerilerden biri: her DİBS
getirisinin TLREF'in kuralıyla ON karşılığı, TLREF ve repoyla doğrudan karşılaştırılsın diye). Getirinin yanında gecelik
faiz karşılığı, iki ondalık:

* **Nerede**: RV hesap tablosunda **ON karşılık %** bileşik getirinin hemen sağında (kullanılan temiz fiyatın getirisinin),
  **Alış ON %** alış getirisinin, **Satış ON %** satış getirisinin sağında (`DİBS RV!BO:BQ`); **Genel** sekmesinde "Getiri"
  grubunda bileşik ve basit getiriden sonra; DİBS Trading özetinde "OIS'e göre"de **Getiri %**'nin sağında; Tüm Kâğıtlar'da
  **Getiri % (RV)**'nin sağında **ON karşılık % (RV)** (trading listesindeki kâğıtlar); kâğıt kartında bileşik getiriden sonra.
* **Nasıl**: önce getiri **kendi kuralıyla** pencerenin - kâğıdın valöründen (DİBS RV'nin Valör'ü: `ISL0`'da bugün,
  ötekilerde TRY listesine göre ertesi iş günü) vadesine - büyümesine çevrilir: bono ve kuponsuzda basit ACT/365, G = 1 +
  getiri · gün / 365 (= 100 / kirli); sabit kuponluda BIST getirisi yılda kupon sayısı (f) kadar bileşik, G = (1 + getiri /
  f)^n, n vadeye kalan dönem - getirinin kendi toplamındaki gibi: içinde bulunulan dönemin kalan kesri (sonraki kupon −
  valör, dönemin gününe bölünür), sonra tam dönemler. Bileşik getiri aynı büyümeyi verir: bir fiyatın tek ON'u vardır.
  Sonra **TLREF'in kuralıyla** ON'a (masanın 25.11.2026 "B"si, *Faizden PPK adımı*): iş günlerinde bileşik, ACT/365 - hafta
  sonu ya da tatilde son iş gününün faizi aradaki günler için tek adımda: gün · ln(1 + ON/365) − W · (ON/365)² = ln G, W =
  Σ g(g − 1)/2 pencerenin iş günleri arasındaki boşluklardan (MPC ima modelinin ve PPK adımının ikinci dereceden yazımı).
  **W** OIS spot'tan sonrası için Motor'un günlük takviminden (TRY tatil listesi: Ayarlar → Tatiller); `ISL0`'da bugünden
  spot'a olan günler eklenir; vadesi Motor'un takviminin sonundan (OIS spot + 3700 gün, şimdi 2036 sonu) uzun kâğıtta
  ötesi doğrudan TRY tatil listesinden sayılır (gizli `EK_ISGUNU` sayfası: cumartesi 1, pazar 2, hafta içi tatil son iş
  gününden günü kadar, cuma tatili hafta sonuna bir daha).
* **Örnek** (kayıtlı gün, 03.11.2026): TRB100227T13 (bono, `ISL0`): 03.11.2026 → 10.02.2027, 99 gün, temiz 92,220, basit
  %31,10, bileşik %34,80 → W = 45 (14 hafta sonu × 3, Yılbaşı 2027 cuma: perşembeden pazartesiye 4 gün, 3 yerine 6) → **ON
  %29,88**; her gün ayrı bileşik (takvim günü, ACT/365) olsaydı %29,87. TRT150328T24 (%36,8 kupon, yılda iki): 04.11.2026 →
  15.03.2028, 497 gün, 2,73 dönem, basit %36,39, bileşik %39,70 → W = 247 → **ON %33,56** (takvim günüyle %33,54). TLREF'in
  kuralıyla ON, takvim gününden ~1–1,6 bp yüksektir (hafta sonu cuma'nın faizi üç gün tek adımda işler).
* **Hangi kâğıtlar**: sabit kuponlu, bono ve kuponsuz. TLREF'li, FRN ve TÜFE'lide boş (reel getirinin nominal ON'u yok).
* **İki yönlü** (RV hesap tablosunun kâğıt satırında, yukarıdaki iki yönlü tablonun bir üyesi): **ON karşılık %**
  yazılabilir - yazılan kalır (✎), Manuel temiz o ON'un verdiği fiyat olur (büyümesi kendi kuralıyla getiriye, getiri
  fiyata), öbürleri o fiyattan; "Fiyat durumu" "ON karşılığından (yazılan)" der; son yazılan geçerlidir, Delete satırı
  piyasaya döndürür; TLREF / TÜFE satırında yazılan ON fiyat vermez (nedeni Fiyat durumu'nda); fiyatı olmayan kâğıdı
  fiyatlar. Yazılan ON gizli `YQ` sütununda (yardımcı tablo "ON karşılık") kişisel olarak saklanır ve kâğıtla taşınır.
  **Alış / Satış ON** yalnız gösterilir (getirileri piyasanın). Genel, DİBS Trading, Tüm Kâğıtlar ve kart gösterir, yazılmaz.
* Fiyatın arkasında canlı iki taraflı kota yoksa getiriler gibi soluk; eğri interpolasyonu ayarından bağımsız (eğri
  okunmaz). **Kâğıt Fiyat Yükleme**'de yok: oradaki getiriler yükleme dosyasının kotalarıdır (kendi t0 valörü ve kupon
  takvimiyle), her hücresi düzenlenebilir - masa isterse ayrıca eklenir. Yeni Bloomberg isteği yok; hiçbir şey
  yazılmamışken mevcut her sayı aynı.

### Gün Sonu Matrisi, PPK Fiyatlama Geçmişi ve toplantı takvimi

Bu üç sayfa Excel dosyasında yok; dashboard'un kendi **günlük tarihçesine** dayanır (`data/tto.db` içinde: her seri
için gün gün kapanış, her gün için her toplantının fiyatlaması). Hangi serilerin tutulacağı dosyadan okunur: OIS
ticker kökleri (`OIS_MAIN!J9:J26`), TLREF, offshore ticker'ları (`Forward!AO6:AO26`: `TRYI…` FX swap ima faizleri ve
`TRYSAQ…` XCCY), DİBS RV listesindeki kâğıtlar. Bu hücreler değişince tarihçe de onları izler. Dosyadan gelmeyen bir seri
daha: Trades'in SOFR swap'larının değişken bacağı için **SOFR fixing'i** (`SOFRRATE Index`, `PX_LAST`; *Tarihçe
serileri* tablosunda "SOFR fixing (Trades)"). **Kaynak sırası**
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
  * **SOFR fixing'i** (`SOFRRATE Index`) günde **bir değerdir** ve 15 dakikalık turla değil, **günde bir kez** istenir:
    New York bir günün SOFR'unu **ertesi iş günü 08:00'de** (İstanbul 16:00, yazın 15:00) yayımlar; tarihçe yeni
    günlerini **günde tek istekle, 16:30'dan sonra** sorar (masanın kararı, 18.11.2026): o saatten önceki bir açılışta
    istek yapılmaz, aynı akşam yeniden başlatılınca da sorulmaz (günün isteği serinin kaydında tutulur; "Şimdi güncelle"
    yeniden sorar). Dashboard'un 16:30'dan sonra açık olmadığı bir günün fixing'i ertesi günün isteğiyle gelir (istek
    son fixing'ten bugüne). 16:30'a kadar dünün fixing'i yoktur, Trades onu son fixing'le tahmin eder ve söyler. İlk
    doldurma **bir kez, iki yıl** (740 gün, ~510 değer), quant serileriyle aynı sırada (turda en çok 40 seri: masada
    quant serileri çoktan dolu olduğundan ilk turda). **Bloomberg maliyeti:** 1 seri; ilk gün bir kez ~510 değer; sonra
    **günde 1 istek**, son kapanıştan (diğer serilerdeki gibi 3 gün geriden) bugüne, yani günde ~3–4 değer. Sayfa
    yenilemesi, "MTM yenile" ya da Kuponlar penceresi hiçbir istek yapmaz: tarihçeyi okur.
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

* **TRY** üç kitapta tutulur: TRY kitabında `Motor!A361:B523` (tarih ve adı; bütün WORKDAY hesapları - para piyasası,
  tahvil, VİOP, OIS, kontrat vadeleri - bunu okur), DİBS ASW kitabında `ASW!LR2:LR200` (yalnız tarihler) ve Borsa Swap
  kitabında dashboard'un eklediği `EK_TATIL!A5:A204` (yalnız tarihler; BIST swap'ın T+1 valörü bunu okur - dosyanın
  kendi listesi yok: dashboard açılırken TRY kitabının listesinden satır satır doldurulur, o listenin günleri tek tek
  yazılınca ya da geri alınınca - Motor sayfası, sıfırlama - onu hemen izler). Sekme listeleri tek liste
  olarak gösterir (birleşimi, adlar TRY kitabından), Kaydet üçüne birden yazar; en çok 163 gün.
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
    önce kaç toplantının listeden çıkacağı (ve senaryo adımlarının kenara alınacağı) sorulur.

  Takvim değişince PPK fiyatlama geçmişinin her günü yeni takvimle yeniden hesaplanır (canlıda gün başına
  birkaç saniye); düzeltmeleri tek kayıtta yapın — kaydetmeden önce sayfa bunu yaklaşık gün sayısıyla hatırlatır.

* Bir toplantıya yazılmış her şey **toplantısıyla birlikte taşınır**. Neyin bir toplantının satırına ait olduğu tek bir
  kayıtta tutulur (`tto/meetings.py`) ve takvimi değiştiren her yol onu kullanır:
  * **TCMB** (`OIS_MAIN`, satır 10–89): tarih `P`; toplantı başına yazılanlar - senaryo adımları `U:W`, Motor'un o
    toplantının sırasındaki öncel ortalaması `Motor!D4311:D4390` ve çözücünün başlangıç adımı `A4481:A4560`; masanın
    etiketi `O`; IMPLIED RATES tablosunun hesaplanan hücreleri `N`, `Q:T`, `X:Z` ve `BM:BO` (üzerlerine yazılmış "Elle
    değer" toplantısıyla taşınır). Aynı satırlardaki başka tablolar (O/N eşlenikleri, stub, çözücü ayarları, sıralama
    sütunları) toplantıya ait değildir, kaymaz. *PPK ima*'daki PPK adımı tablolarına (`EK_PPK`, satır 3'ten: k'ıncı
    satır k'ıncı toplantının) yazılan dönem faizi `G` ve MPC spread'i `S` satırın (ilk) döneminin başladığı toplantının,
    hesaplanan sütunları da ("Elle değer" toplantısıyla taşınır).
  * **Fed** (`SOFR_FOMC`, satır 74–83, USD · FOMC sayfası): tarih `B`; "Karar (1/0)" `C`, "WIRP (manuel)" `P`, senaryo
    adımları `R:T`, "Pencere OIS (elle) %" `AB`; hesaplanan `D:O`, `Q`, `U:Z`, `AA`, `AC:AE` ("Elle değer" toplantısıyla
    taşınır).

  Taşınanlar: her kullanıcının kendi değerleri ve "Elle değer"leri, masanın değerleri (dosyanın kendi adımları,
  masanın yazdığı etiket - dosyanın "MPC1 … MPC80" adları satırındır, yerinde kalır), **kayıtlı senaryolar**, bu
  hücrelere **başvuran formüller** (girdi formülleri, senaryolardaki formüller, kişisel hesap tabloları, izleme
  ifadeleri: `=OIS_MAIN!U12+25` → `U13`; listeden çıkan toplantıya başvuru `#REF!`), toplantı satırındaki hücreye kurulu
  **alarmlar ve izleme kalemleri** (hücreye değil toplantıya bağlanır: tarihi düzeltilince alarmı, kalemi, günün açılışı
  ve saklanan kapanışları yeni tarihe geçer; önceki sürümün hücre olarak sakladığı kalemler açılışta bir kez, o gün
  satırın tuttuğu toplantıya bağlanır). Araya toplantı eklenince sonrakiler bir satır aşağı, çıkarılınca yukarı kayar;
  tarihi düzeltilen toplantı (en çok 45 gün, sırası değişmeden) aynı toplantı sayılır. Hepsi **tek işlemde** yazılır:
  yarıda kalan bir değişiklik (disk, kapanan süreç) hiçbir şeyi yarım taşımaz.
* **Listeden çıkan toplantının değerleri silinmez, kenara alınır.** ✕ ile çıkarılan, "Gelecek toplantıların yerine
  koy" ile giden, tarihi 45 günden fazla değiştirilen (yanlış yazılmış bir yıl: başka bir toplantı sayılır) ya da
  geçip arşive giden toplantıya herkesin yazdığı her şey - kendi değerleri, "Elle değer"leri, masanın etiketi, kayıtlı
  senaryolardaki değerleri - toplantının tarihiyle saklanır (`calendar.parked`) ve satırlardan çıkar. **Tarih listeye
  geri gelince** hepsi kendi satırına geri konur (yanlış yılı düzeltmek yeter). Takvimi değiştiren her cevap ne
  olduğunu söyler: "1 toplantı listeden çıktı (18.03.2027): 5 değer (2 kullanıcı) ve kayıtlı senaryolarda 3 değer
  kenara alındı - tarih geri eklenirse geri gelir", "18.03.2027 listeye geri geldi …"; takvim sayfası kenardaki
  toplantıları yazar ve ✕ ile çıkarılan toplantıyı kaydetmeden önce sorar. Kenardaki değerler toplantının gününden 30 gün
  sonra silinir.
* **OIS sayfasında** bir toplantı tarihinin üstüne yazmak ya da yapıştırmak da aynı yoldan gider. **Delete ile tarih
  silinmez:** seçimde toplantı tarihleri (`P`) varsa onlar reddedilir, nedeniyle ("bir toplantıyı listeden çıkarmak için
  Ayarlar → Toplantı takvimi'nde ✕ kullanın"), seçimin geri kalanı (adımlar) temizlenir; boş tarihli yapıştırma da
  böyle. Listede zaten olan bir tarih reddedilir (iki satır, bir toplantı). Tarihle **aynı yazmada** yazılan adımlar o
  tarihin toplantısına gider: araya giren olağanüstü toplantı tarihiyle ve adımlarıyla birlikte yapıştırılınca adımlar
  toplantının listedeki yerine (ör. 15. satır) yazılır, o satırdaki toplantı kendi adımlarıyla bir satır aşağı kayar.
  Tarihlerin dosyadaki değere döndürülmesi reddedilir (dosyanın kaydedildiği günün tarihleridir).
* **FOMC listesi** (`SOFR_FOMC!B74:B83`) USD · FOMC sayfasında düzenlenir ve aynı kuralla değişir: tarih yazılınca ya
  da yapıştırılınca liste tarih sırasına dizilir (boş satır kalmaz), yapılan toplantıları atıp yenilerini sona eklemek
  her kullanıcının kararını, WIRP'ini ve adımlarını toplantısıyla taşır. Orada tarih silinebilir (listeyi düzenlemenin
  tek yeri): toplantıya yazılanlar kenara alınır ve söylenir, tarih yeniden yazılınca geri gelir. Aynı tarih iki kez
  yazılamaz; tarihlere ve toplantı başına girdilere formül yazılmaz; tarihler dosyadakine döndürülmez.
* **Kaydetme sürümle.** Takvim sayfası listeyi okuduğu andaki sürümüyle kaydeder; o arada takvim değiştiyse (başka biri
  kaydetti, OIS sayfasında tarih yazıldı, liste kaydı) kayıt reddedilir, kimin ne zaman değiştirdiği yazar ve sayfa
  takvimin şimdiki halini gösterir - eski liste yenisinin üstüne yazılıp başkasının düzeltmesini geri almaz.
  `POST /api/calendar` `{"dates", "roll", "version"}` (sürümsüz çağrı eskisi gibi kaydeder; cevapta `note`, `parked`,
  `restored`, `formulas`).
* **Toplantı geçince liste kendiliğinden kayar: MPC1 her zaman sıradaki toplantıdır.** Bir toplantının tarihi OIS
  spot valöründen önce kalınca (dosyanın kendi "geçti" ölçütü) dashboard açılışta, gün dönünce ve gün içinde 10
  dakikada bir (TRY tatil listesi gün içinde değişirse spot da kayar) geçen toplantıyı
  listeden arşive alır, liste sıradaki toplantıdan (MPC1) başlar; toplantı satırındaki her şey (yukarıda: adımlar,
  etiketler, elle değerler, Motor'un girdileri, kayıtlı senaryolar, başvurular, alarmlar) toplantılarıyla birlikte bir
  satır kayar. Kaydırmadan önce ve sonra her toplantının
  fiyatlaması ve her kullanıcının senaryo patikaları toplantı bazında aynıdır (testle doğrulanır); kaydı yapan
  "otomatik" görünür, Ayarlar'da son otomatik kaydırma yazar. **Geçen toplantıları arşivle** aynı işi elle yapar.
  Fiyatlama geçmişi toplantının tarihine bağlı olduğu için kaydırmadan etkilenmez.
* **Bilerek böyle** (Excel'in anlamı):
  * **"MPCk" bir sıradır.** Hesaplanan toplantı ve dönem hücreleri (`OIS_MAIN!Q:T`, `X:Z`, `N`, satır 10–89; MPC OIS;
    MPC SPREAD) "k'ıncı sıradaki toplantı"nındır: onlara **başvuru** (girdi formülü, hesap tablosu, izleme ifadesi),
    launchpad'deki "MPC3" seçimi ve DV01 Risk'in "Tek toplantı sürprizi – MPC no"su liste kayınca bir sonraki
    toplantıyı okur. Toplantının kendisini izlemek için hücreye alarm / izleme kalemi kurun (toplantıya bağlanır) ya da
    toplantının kendi hücresine (tarih, adım) başvurun - o toplantıyla taşınır. Dönem tablolarındaki (MPC OIS, MPC
    SPREAD) "Elle değer" de dönemindir, yerinde kalır; PPK adımı tablolarına yazılan faiz ve spread ise toplantısıyla
    gider (yukarıda). Masa'nın anketinde `MASA!Q157`'ye `=OIS_MAIN!P10` yazmak artık
    o günkü toplantının tarihini tutar: toplantı geçince başvuru `#REF!` olur ve anketin eskidiği görülür.
  * **Senaryo yüklemek değerleri adresleriyle geri koyar.** Kayıtlı senaryonun toplantı hücreleri (TCMB ve Fed: adımlar,
    elle değerler, Motor'un toplantı girdileri) takvim her değiştiğinde toplantısıyla güncellendiği için yüklenince doğru
    satıra gelir; listeden çıkan toplantınınkiler kenarda bekler, tarih dönünce senaryoya da geri konur. Başka satırlara
    bağlı değerler (bir kâğıdın satırı, bir VİOP kontrat sütunu, tatil listesi) kaydedildikleri adrese döner.
  * **Broker Chat'in MPC kotaları yapıştırıldıkları günün tarihlerini taşır.** Sonradan düzeltilen bir toplantı tarihi
    eski kotaya geçmez: o kota MPC OIS tablosunun dönemleriyle eşleşmez, ima adımı olmaz ve tahtada ayrı bir enstrüman
    olarak görünür.
  * **Toplantı kendi karar gününde geçmiş sayılır.** Tarihi OIS spot valöründen (T+1) önce kaldığı için o günün ilk
    kaydırmasında listeden çıkar - dosyanın kendi "geçti"si gibi; ona yazılmış adımlar o andan itibaren kenardadır
    (30 gün), kararın açıklanmasını beklemez.
* Takvim değişince fiyatlama geçmişi yeni takvimle arka planda yeniden hesaplanır (yalnızca etkilenen günler).
* Geriye bakış penceresinde artık hesaplanamayan bir gün (kotası ya da TLREF'i kalmayan, tatil sayılan) geçmişten çıkar;
  pencereden eski günler ve **bugünden sonraki günler kalır**: masanın verisinin bir kopyası kayıtlı veri modunda
  açılınca (bugün = dosyanın kaydedildiği gün) sonradan canlıda fiyatlanan günler silinmez.
* *Tarihçe* bölümü: durum, DİBS getiri alanı, geriye bakış süresi, "Şimdi güncelle", "PPK geçmişini yeniden
  hesapla". *Tarihçe serileri* tablosu her ticker için ilk / son gün ve gün sayısını gösterir — matriste boş kalan
  bir satırın nedeni (Bloomberg o ticker ya da alan için geçmiş vermiyor) buradan görülür.

### Quant sinyaller

**Quant** grubundaki yirmi sayfa, masanın istatistik analizlerini **işlem sinyaline** çevirir: her analiz aynı biçimde
sinyal üretir, **Sinyaller** sayfası hepsini tek listede - en üstte **Konsensüs** (üç ya da daha çok ailenin aynı
enstrümanda aynı yönde olduğu yerler: [aşağıda](#konsensüs)), sonra gruplara göre (G10 spot, G10 opsiyon, TRY OIS, DİBS,
VİOP, Offshore) - ve grubun içinde beklenen K/Z'ye göre sıralar - hedef ve stop ailenin **geçmiş işlemlerinden ayarlı**
(aşağıda: *Seviyeler*), ödül / risk en az 1, yanında isabeti ve işlem sayısı -, bir sinyal giriş eşiğini
geçtiği an kaydedilir, izlenir ve abone olan kullanıcıya bildirilir. Analiz sayfaları: **Korelasyon**, **PCA / RV**,
**Çiftler**, **Rejim & Momentum**, **FX Vol Primi & Carry**, **Makro Beta**, **Tahmin Modeli**, **Makine öğrenmesi**
([aşağıda](#makine-öğrenmesi)), **Gün İçi**,
**Eğri Adil Değeri**, **Opsiyon** ([aşağıda](#eğri-adil-değeri-ve-opsiyon)), **İma Patikası**, **Öncü-Takipçi**,
**VİOP** (aşağıda: *VİOP*), **Trend** (aşağıda: *Trend*), **Carry + momentum** (aşağıda: *Carry + momentum*), **Makine öğrenmesi** (aşağıda: *Makine öğrenmesi*),
**Opsiyon → spot** ([aşağıda](#opsiyon--spot)), **DİBS switch** (aşağıda: *DİBS switch*); her
biri kendi sinyallerini üstte listeler, satıra tıklayınca serisi çizilir. **TCMB WIRP** sinyal üretmez: piyasanın
toplantı başına fiyatladığı karar olasılıkları (aşağıda: *İma Patikası ve TCMB WIRP*).

Menüde bu sayfalar **dört giriştir**, her biri sekmeli bir sayfa: **Sinyaller** (Sinyaller, Gün içi, Model, Trend, Carry + momentum, Makine öğrenmesi), **Faiz**
(PCA / RV, Çiftler, Korelasyon, Rejim, Eğri Adil Değeri, DİBS switch, İma Patikası, TCMB WIRP, Öncü-Takipçi), **FX** (FX, Makro,
Opsiyon, Opsiyon → spot) ve **VİOP**; her sayfanın adresi aynıdır, girişe tıklayınca son açılan sekmesi gelir. Canlı sinyal listesi, VİOP
emir seviyeleri ve kontratları, WIRP tablosu ve parite özeti launchpad'e, yan panele ve ayrı pencereye de konur
([Launchpad ve gezinme](#launchpad-ve-gezinme)).

**İşleme al.** Her sinyal satırının **Trades** sütununda (Sinyaller, ailelerin sayfaları, kutular) ve kartında,
Trades'in girebildiği satırlarda **İşleme al** düğmesi: Trades formu satırın şimdiki seviyeleriyle dolu açılır (ürün,
bacaklar, yön, DV01'den nominal, giriş, hedef, stop), kaydedince işlem Trades'te sinyalin kaynağıyla durur, hedefi ve
stopu İzleme alarmı olur; Trades'in **Quant'tan** tablosu aile aile bu işlemlerin gerçek K/Z'ını gösterir. Girilemeyen
satırda "—" ve nedeni ([Trades](#trades-masanın-ve-kişinin-kendi-işlemleri): hangi satırlar). Sunucu her satıra bunu
`book: {ok, why, kind}` olarak yazar (`tto/tradequant.py`).

**Tablolar masanın diliyle.** Her quant tablosunun başlığının hemen altında bir-iki cümle: tablo neyi söyler, hangi sayı
ne zaman ve hangi yönde işlem demektir (ör. PCA / RV'nin zengin / ucuz tablosu: "Her OIS vadesi iki komşusuna göre ucuz
mu pahalı mı? *Kalıntı (bp)* artıysa vade ucuz → receive, eksiyse pahalı → pay …"). Tablonun nasıl hesaplandığı
altındaki notta **Yöntem** olarak kalır (değişmedi); okunuşu ya da canlı bilgiyi veren notlar (sinyal listelerininki,
kotasyonun valörü ve işlemiş faizi, switch'in nominali) etiketsizdir. Cümleler tek dosyada, tablonun kimliğiyle
(`tto/static/js/pages/quantread.js`): sayfaların ortak sinyal listesi ve grafiği tek cümleyle; veri kapsamı, hesap
durumu, ayar ve abonelik formları cümlesiz. `test_quantread.py` her tablonun bir cümlesi olduğunu, kalkan tabloya cümle
kalmadığını, cümlelerin kısa (en çok 320 karakter) ve yöntem terimsiz (ADF, Kalman, GARCH, SVI, EWMA …) olduğunu denetler.

**Düzen (27.11.2026; masa: "Hepsini yap").** Yirmi quant sayfası aynı düzende:

- **Sıra her sayfada aynı:** sinyaller → seçili satırın kartı → işlem yapılan tablolar → analiz → ikincil tablolar
  (ör. PCA / RV'de zengin / ucuz, fly / spread ve FRA önce, bileşenler sonra; Eğri Adil Değeri'nde en iyi kâğıt,
  kotasyon ve switch önce, iki uyum sonra; Korelasyon'da çiftler matristen önce; İma Patikası'nda kinkler önce).
- **Genişlik tablonunki:** dar tablolar kendi genişliğinde ve yan yana; sinyal listesi, kart ve grafikli paneller satırın
  tamamı. Tabloların yüksekliği uygulamanın ortak kuralı (quant'ın kendi %46'lık sınırı kalktı), kartın sınırı yok.
- **Veri kapsamı ve Hesap durumu yalnız Sinyaller'de**, sayfanın sonunda kapalı; her sayfanın üstünde tek satır:
  "Veri kapsamı: 12 seri · 2 kısa · son kapanış …" (ipucunda kısa / geçmişi dolan seriler, tıklayınca Sinyaller'deki
  tablo) ve yanında "Hesap …" satırı.
- **Uzun sayfalarda ikincil paneller kapalı** (başlıkta ▸; başlığa ya da ▾ / ▸'e tıklayınca açılır, seçim tarayıcıda
  kalır) ve üstte sayfanın tablolarına **bağlantılar**: Sinyaller (ayarlar, abonelik, kapsam, durum), Carry + momentum,
  PCA / RV (dönemler, kararlılık, pencere yükleri), Eğri Adil Değeri, İma Patikası (toplantı toplantı kalibrasyon,
  ayarlar), TCMB WIRP (ayarlar), Opsiyon (smile uyumu), VİOP (yedi ikincil panel). Öncü-Takipçi'nin çapraz
  korelasyonları ve DİBS switch'in evren dışı kâğıtları da kapalı gelir.
- **Boş panel = başlık + neden:** sinyali olmayan liste ve boş kart yalnız başlığını ve nedenini gösterir.
- **İlk satırın kartı kendiliğinden açılır** (her sayfada); bir satıra tıklayınca kart ekranda değilse **kart görünür**
  (aşağıdaki bir tabloya - Eğri'nin DİBS'i, PCA - tıklayınca kart ekran dışında güncellenmez).
- **İşlem yapılan her tablo işlemle başlar:** **İşlem** (AL / receive yeşil, SAT / pay kırmızı) · Giriş · Hedef · Stop ·
  Beklenen K/Z · Ödül / risk · İsabet (n); sonra Birim, Trades ("İşleme al"), z, Güç, Tutma, Carry / hf, Carry % / yıl,
  Geri test, Aile (Sinyaller'de Grup), en sonda ikincil istatistikler (Varlık, Yarı ömür, Rejim, Uyum, Kapılar), Bileşik /
  neden, Saat. Trend tablosu ve DİBS switch'in switch tablosu da işlemle başlar; sıralamalarda AL / SAT renkli (Carry +
  momentum'un "Sepette"si, DİBS switch'in "Switch'te"si, Eğri'nin en iyi kâğıdı, ML ve Opsiyon → spot'un "Olasılık"ı).
- **19 sinyal listesinin tek sütun seçimi** (Sinyaller, kutusu ve her analiz sayfasınınki): "Sütunlar"da bir kez seçilir,
  hepsinde geçerli. Seçim yapmamış kullanıcıda **varsayılan gizli**: Varlık, Yarı ömür (g), Rejim, Uyum, Kapılar
  (kartta hepsi yazar; "Sütunlar" ile tek tıkla geri gelir). İşlem, seviyeler, K/Z, kayıt, carry hiç gizlenmez;
  kullanıcının kendi seçimi varsayılanı geçer.
- **Kimlik sütunu donuk:** yana kayan tablolarda (1366 px) ilk sütun yerinde kalır - sinyal listeleri (Sinyaller'de # ve
  İşlem), Eğri'nin DİBS'i, Öncü-Takipçi taraması (grup ve çift), İma Patikası'nın ardışık toplantıları ("Okuma" artık
  kesilmez, satıra sarar), Opsiyon → spot pariteleri, VİOP kontratları, Opsiyon tabloları (parite ve vade) …
- **Quant seviyeleri üç ondalık** (masa, 25.11.2026): VİOP'un ima faizleri (kontratlar, emir seviyeleri ve başlıkları,
  gün içi en düşük / en yüksek) ve DİBS switch'in getiri ve fonlama faizi.
- **Bir bilgi bir kez:** DİBS switch'te sıralama yoksa neden yalnız "Bu haftanın switch'leri"nin başında (önce beş kez);
  Carry + momentum'da sepeti olmayanın nedeni yalnız kartında; sepet kartının bacak tablosu kapalı ("Bacaklar (N)" - her
  bacak üstteki listede zaten satır); Tahmin Modeli'nin sütunları ML'inkilerle aynı adla ("Basılıyor", "Olasılık
  (yukarı)"). VİOP'ta kontrat seçici seçtiği **Emir seviyeleri** panelinde, seviyelerin hemen üstünde.

Değer ya da sinyal değişmez; yalnız yer ve görünüş. Kod: `tto/static/js/pages/quantbase.js` (`panel`, `GridBox`,
`signalRows` / `signalHead`, `SIGNALS_TABLE`, `coverageLine`, `firstPick`, `revealCard`, `jumpBar`), sayfa modülleri,
`app.css`'in sonundaki "Quant düzen" bloğu, `Service.DEFAULT_HIDDEN_COLUMNS["quant/signals"]`.

**Motoru bloklamaz.** Bütün hesaplar `tto-quant` iş parçacığında, tarihçenin kapanışlarının bir kopyası üzerinde
yapılır (saf Python; numpy yok: `tto/quantmath.py`). Yeni bir kapanış gelince (tarihçe deposu her 5 dakikada bir
yoklanır), gün dönünce ya da ayar değişince **tam hesap**; arada **dakikada en çok bir kez** yalnızca son nokta canlı
değerlerle yenilenir (her enstrüman, seviyesini canlı değerden okuyan küçük bir fonksiyon tutar), sonuç önbellekte
durur, sayfalar yalnızca onu okur. Motor iş parçacığında geçen tek şey kısa bir okumadır: kaynak sayfasındaki canlı
OIS / offshore kotaları, VİOP geçmişi ve canlı satırı, Carry & Roll'un vade motoru (ilk okuma ~0,3 sn, sonrakiler
milisaniyeler). PPK patikası OIS_MAIN'den okunmaz (çözücüyü motor iş parçacığında çalıştırırdı); tarihçenin kendi
motorunda hesapladığı son gün kullanılır. Masa bilgisayarında iki yıllık sentetik tarihçeyle tam hesap ~3,1 – 3,4 sn
(en ağırları model ~0,8 sn, DİBS NSS ~0,7 sn, OIS NSS ~0,55 sn, GARCH ~0,35 sn), canlı yenileme ~25 ms (canlı smile
ve NSS'le ~0,1 sn); motor iş parçacığındaki okuma (DİBS RV dahil) ~15 ms. Süreler Sinyaller'in sonundaki (kapalı) *Hesap durumu*
tablosunda yazar. Arka plan işi tarihçe güncellemesiyle birlikte çalışır (`--no-history` ile ikisi de durur;
"Şimdi hesapla" yine çalışır). Hesap sürerken nerede olduğu yazar (üst şeritteki **Hesap**, yukarıda): ilk sonuç gelmeden
sayfanın bandı "Analizler hesaplanıyor (ayrı iş parçacığında): Quant 14/26 · ML 240/480 · ~3 dk – şu an Makine
öğrenmesi; …", *Hesap durumu*'nun Durum satırı da öyle; geri test panelinde "Geri test çalışıyor: 12 / 25 yeniden kurma ·
Mart 2026 · 14.03.2026 kapanışıyla · ~4 dk". Sayaçlar hesabın kendi döngülerinde birer atama (adım: ailelerin süresini
yazdığı sözlük, model: eğitimden sonra bir çağrı, yeniden kurma: başında bir çağrı); ML'in yürüyen testi önce planlanır
(her ayın eğitim satırları ve özetleri - modelin önbellekteki anahtarı -, zaten hesaplananlar), sonra eğitilir: aynı
modeller, aynı sonuç. Ölçüm, önce / sonra sırayla (masa bilgisayarı): ML ailesi tek başına (sentetik evren, 42 satır, 512
model, soğuk önbellek, üçer kez) 36,5 – 37,8 / 36,1 – 37,2 sn, önbellekten ikinci hesabı 1,90 – 1,94 / 1,77 – 1,98 sn;
servisin tam hesabı (sentetik tarihçe, ikişer kez) açılıştan sonraki ilk hesap 24,5 – 25,3 / 22,8 – 24,2 sn, sonraki
5,46 – 5,56 / 5,45 – 5,68 sn - fark gürültünün içinde; 160 sinyal ve ML tablosu birebir aynı. Bir sayaç adımı ~0,6 µs
(512 model: ~0,3 ms), tam hesabın 26 adımı ~75 µs, `/api/progress` ~20 µs.

**Bir sinyal** şunları taşır:

| Alan | Anlamı |
|---|---|
| Düz anlatım | Kartın başında, sinyalin kendi sayılarından tek paragraf: ne yapılır, hangi enstrümanda, hangi fiyattan; tutma süresince ne beklenir ve hedefte / stopta ne olur. FX: "Bugün 3 aylık USDTRY forward'ını satıp ~63 iş günü tutarsan (giriş 44,1250) ve kur o sürede beklenen seviyeye gelirse (43,6000), 1 mn USD başına ~525 bin TRY kazanırsın: forward priminden (carry) +2.325 bin TRY, kur hareketinden -1.800 bin TRY (spot 41,8000 → 43,6000). Hedefte (43,6000) ~525 bin TRY kâr, stopta (44,6000) ~475 bin TRY zarar." Faiz: "Sabit faiz alınan (receive): 2Y OIS (değişken bacak TLREF). 2Y OIS (PC1–PC2 hedge'li) şimdi +3,0 bp; hedef seviyesine (0,0 bp) gelirse 3,0 bp ≈ 120 bin TL kazanırsın, stop seviyesine (+3,5 bp) gelirse 0,5 bp ≈ 20 bin TL kaybedersin. Beklenen: ~13 iş günü içinde +5,1 bp ≈ +203 bin TL (+2,6 bp'si carry + roll). Ana bacak 1.000 $ DV01 = 40.000 TL / bp." Altında İşlem, Giriş / hedef / stop, Beklenen K/Z ve Hedefte / stopta satırları aynı sayılarla |
| Tez | Tek cümle: ne, ne kadar yerinden oynamış, hangi pencereyle, işlem ve beklenen kâr ("2Y OIS, iki komşusuyla … 8,4 bp ucuz (250 günlük pencere, z +2,6); yarı ömür 6 gün → Receive 2Y OIS; beklenen +5,1 bp ≈ +203 bin TL (carry + roll dahil)"; FX'te "USDTRY forward'ların fiyatladığından geride kalıyor: kur, forward priminin gerisinde - forward'la satan kazanıyor (…) → Sell USDTRY forward; beklenen ~+353 bin TRY / 1 mn USD (forward primi dahil)") |
| Aile, varlık | Hangi analizden geldiği; TRY OIS, Offshore, VİOP, DİBS, FX, FX vol, EM carry, Küresel (süzgeçler bunlara göre) |
| İşlem | İfade ve bacaklar, ağırlıklarıyla: "Receive 2s5s10s PCA-nötr fly", "Pay 1s2s PC1-nötr spread", "Sell USDTRY 3M ATM vol", "Steepener 2s10s", "Sell USDTRY forward"; hedge'li bir paket (Eğri ve DİBS adil değeri, PCA kalıntısı) **bacak bacak**: "Buy 09.06.30 · Sell 26.09.29 · Sell 28.03.31", "Receive 2Y OIS · Pay 18M OIS · Pay 3Y OIS". Sinyalin *Yön* satırı da her bacağı nominali ve DV01'iyle ($ / TL) yazar; bacak tablosu her paket için: işlem (Buy / Sell, Pay / Receive), enstrüman, **nominal (mn TL)**, **DV01 ($ ve TL / bp)**, DV01 ağırlığı - ana bacak paket DV01'i (ayar, **1.000 $ / bp**; TL'si OIS_MAIN!D2'deki USDTRY ile), OIS bacağının nominali DV01 ÷ (annuity × 1e-4), annuity Motor'unki (Günlük İşlemler'in OIS girişi gibi), kâğıdınki DV01 ÷ kâğıdın 1 mn'lik DV01'i (DİBS RV!AI); nominaller yuvarlanmaz (masa 5 mn TL'ye yuvarlar, OIS_MAIN!H2) |
| Yön, skor, güç | z (ailenin skoru); güç |z| ÷ giriş eşiğine göre: Zayıf < 1,25 ≤ Orta < 1,5 ≤ Güçlü; bir kapıya takılan sinyalin gücü yazılmaz: **düşük güven** |
| Grup | Listedeki yeri: G10 spot, G10 opsiyon, TRY OIS (≤ 2Y / uzun), DİBS, VİOP, Offshore (**offshore limiti**), Diğer (aşağıda: *Evren, gruplar ve listenin sırası*) |
| İşlem (masanın diliyle) | FX: enstrüman ve yön - "USDTRY 1A forward sat" (tutma süresinin forward'ı: valörü ufkun sonu; 20 iş günü = 28 gün ≈ "1A"), forward primi ailesinde "USDTRY 3A forward sat", gün içinde "USDTRY spot sat"; büyüklük 1 mn baz döviz. Faiz ve diğerleri: bacaklar ne yapıldığına göre gruplanır - "sabit faiz alınan (receive): 2Y OIS · sabit faiz ödenen (pay): 1Y OIS ×0,45, 5Y OIS ×0,30 (değişken bacak TLREF)", "alınan: VİOP Kas26 (12 kontrat) · satılan: USDTRY spot", "alınan: 09.06.30 · satılan: …"; yanında ana bacağın DV01'i ($ ve TL / bp) |
| Giriş / hedef / stop | Giriş = şimdiki seviye. **Hedef ve stop ailenin geçmiş işlemlerinden ayarlıdır** (aşağıda: *Seviyeler*): tutmanın σ'sının katları - stop k σ, hedef m σ, σ enstrümanın bugünkü günlük σ'sı × √tutma -, ödül / risk = m ÷ k ≥ 1; ortalamaya dönüş ailelerinde hedef adil değer (pencerenin ortalaması) de seçilebilir, stop o zaman en çok hedef kadar uzakta; **Trend'de hedef yok, iz süren stop**; Carry + momentum'da sepetin katları bacağın kendi σ'sıyla. Kalibrasyonu olmayan satır (geri test henüz yok, ailenin 30'dan az işlemi var) ve seviyesi kendi tasarımı olan aileler (VİOP emir seviyeleri, İma kalibrasyonu, gün içi aileleri, korelasyon, ima patikası, DİBS adil değeri) ailenin kuralıyla - ortalamaya dönüşte hedef ortalamada (hedef z, varsayılan 0), stop seviyenin |z| = 3,5 olduğu yerde; momentum / model / döngü / carry sinyallerinde hedef ve stop ufuk boyunca beklenen hareketten -, kartta ve listede nedeni yazar. **FX'te işlem yapılan forward'ın kuru**: giriş bugünkü forward (ör. 44,1250; spot yanında), hedef ve stop analiz serisinin hedef / stop seviyesine karşılık gelen forward kuru (forward pozisyonunun getirisi forward'ın log değişimidir: F × e^(Δ / 100); forward priminde tampon oraya gelince 3A forward, spot bugünkü yerindeyken); paritenin kendi ondalığıyla (USDTRY 4, EURUSD 5, USDJPY 3). Listede de bu kurlar, *Birim* sütununda "USDTRY 1A fwd"; analiz serisinin değerleri ipucunda ve kartın *Analiz serisi* satırında. Faizde seviye kendi biriminde (%38,500 - faiz üç ondalıkla -, +3,0 bp). **Seviyesi modelin kendi farkı olan satırlarda** (bir patikaya / uyuma göre fark, bir kalıntı) giriş / hedef / stop **işlem yapılan enstrümanın kendi seviyesinde**, modelin farkı yanında (aşağıda: *Seviyeler enstrümanın kendi biriminde*): FRA / PPK patikası'nda "%38,720 / %38,652 / %38,730 · 6x9 FRA (patika farkı +6,9 / +0,1 / +7,9 bp; hedef / stop bugünkü PPK patikasıyla)" - listede de FRA faizleri, *Birim* "6x9 FRA %", fark ipucunda; farkın kendisi kartın *Model farkı* satırında |
| Beklenen K/Z | **Ayarlı seviyelerle: o seviyelerin geçmiş işlemlerdeki işlem başına ortalaması** (tutmanın σ'sı cinsinden, örneklem dışı; 10'dan az örneklem dışı işlemde bugünkü seviyelerin örneklem içi kaydı) × bugünkü σ; FX'te ve evrenin swap puanlarında carry kaydın içindedir, faizde tarihçede carry olmadığından Carry & Roll'un carry + roll'unun o seviyelerle ortalama tutmaya düşen payı eklenir; grubun sırası bu tutara (TL, satırın kendi büyüklüğüyle) göre. Ayarlı seviyesi olmayan satırda ailenin kendi tahmini, **carry + roll dahil**: ortalamaya dönüşte OU'nun o sürede kapattığı pay (aradaki fark × (1 − 2^(−tutma / yarı ömür))), momentumda son 63 günün ortalama değişimi (kesinliğiyle küçültülmüş) × ufuk, modelde (2p − 1) × haftalık hareketin ortalama büyüklüğü, makroda kalıntının ertesi hafta geri dönen payı (geçmişten), döngüde fazın ortalama değişimi, forward priminde tamponun ufka düşen payı. **Para olarak**: FX'te 1 mn baz döviz başına kote para biriminde (USDTRY / EURTRY / GBPTRY: TRY, EURUSD: USD, diğerleri kendi kote parası; yanında TRY ve USD karşılığı) = 1 mn × forward'ın beklenen fiyat hareketi (giriş → beklenen), ikiye ayrılır: **forward primi (carry)** = 1 mn × (forward − spot), tutma boyunca kazanılan / ödenen prim (forward priminde 3A puanlarının tutma süresine düşen payı), ve **kur hareketi** = 1 mn × spotun beklenen hareketi (toplamdan kalan; ikisinin toplamı beklenen K/Z); listede "+525 bin TRY / 1 mn USD", % ipucunda. Faizde bp ve TL (bp × ana bacağın TL DV01'i), carry + roll ile hareket ayrı; vol'de vol puanı; ufkun σ'sı ipucunda |
| Hedefte / stopta, ödül / risk, isabet | Hedefe ve stoba uzaklık: FX'te 1 mn baz döviz başına para (hedef / stop kuru − giriş), faizde bp ve TL; oranları (ayarlı seviyede ≥ 1; Trend'de kazanan işlemlerin ortalaması ÷ iz süren stop) ve beklenen ÷ risk. **İsabet** (listede ayrı sütun): o seviyelerle geçmiş işlemlerin hedefe ya da süre sonunda kârda kapanan payı, örneklem dışı (her ayın işlemleri o ay başlamadan seçilen seviyelerle; kapanışlarla ölçüldüğü için gün içi dokunmaya göre düzeltilmiş), parantezde işlem sayısı; kartın *Seviyeler* satırı katları, oranı, isabeti ve işlem başına beklentiyi, ayarlı değilse nedenini yazar |
| Yarı ömür, tutma | Seviyenin AR(1) regresyonundan Ornstein-Uhlenbeck yarı ömrü (iş günü; gün içi sinyallerde bar); beklenen tutma = yarı ömür × log₂(|z| ÷ 0,5) - beklenen z'nin 0,5'e inme süresi |
| Carry / hafta, carry % / yıl | Faizde Carry & Roll sayfasının vade motorundan (ufuk A, haftalığa çevrilmiş), işlemin yönünde, bp; FX'te forward'ların ima ettiği forward primi, işlemin yönünde, haftalık ve yıllık % (sürekli bileşik, en kısa forward'tan); kartta tutma süresine düşen payı para olarak |
| Rejim | Ortalamaya dönüş / Trend / Nötr (varyans oranı testi), Hurst üsteli, vol yüzdeliği |
| Uyum | Aynı bacağı aynı yönde isteyen **başka aile** sayısı (ve ters yöndekiler) |
| Kapılar | Her kapı geçti (✓) / takıldı (✗) ve nedeni: eşik, stop bölgesi, rejim, yarı ömür, ailenin kendi onayı (ortalamalar, USDTRY trendi), örneklem (döngü), tolerans (FRA), carry (FX: forward primi aleyhine işlemin beklenen kazancı tamponu geçmezse "carry'yi karşılamıyor"; tutarlar 1 mn baz döviz başına para: "forward primi lehte: ufukta +1.184 bin TRY / 1 mn USD"), beklenen kâr (carry dahil sıfırın altındaysa; faizde bp ve TL) |
| Saat, geçmiş | Hesap saati (● canlı değerle); tıklayınca serisi, ±giriş / ±stop bantları ve giriş / hedef / stop çizgileri, tez, kapılar |

**Seviyeler: geçmiş işlemlerden ayarlı hedef ve stop** (`tto/quantlevels.py`). Ailelerin eski kuralları (pencerenin
ortalaması, haftanın 2σ'sı, bir güç diliminin ortalama kazancı, (2p − 1) × ortalama hareket …) birkaç pip hedefe yüzlerce
pip stop koyabiliyordu: "Ödül / risk" 0,02. Şimdi hedef ve stop, ailenin **geçmiş işlemlerinin gerçekte ne yaptığına**
göre seçilir:

* **Yol.** Yürüyen geri testin (`tto/quantbt.py`; Trend, Carry + momentum ve Makine öğrenmesi kendi yürüyen testleriyle)
  her işleminin tutma süresi boyunca her kapanıştaki K/Z'si - kendi hedefi ya da stopu ne yaptıysa yapsın - **tutmanın
  σ'sı** cinsinden (girişte bilinen günlük σ × √tutma; sepette sepetin önceden bilinen haftalık σ'sı): en kötü noktası
  (MAE), en iyi noktası (MFE), bittiği yer. Ölçek yalnız girişte bilinenden; yol sonradan gelendir.
* **Kalibrasyon**, aile × liste grubu başına (G10 spot, G10 opsiyon, TRY OIS, DİBS, VİOP, Offshore, Diğer): stop katı k
  ve hedef katı m, **ay başlamadan biten işlemlerle** (yürüyen: her ay yeniden). Adaylar: kazanan işlemlerin %70 / %80 /
  %90'ının hiç gitmediği yer (MAE yüzdelikleri) stop; bütün işlemlerin MFE dağılımının %30 … %70 yüzdelikleri ve stopun
  1 / 1,5 / 2 katı hedef; ortalamaya dönüş ailelerinde bir de **hedef adil değer** (pencerenin ortalaması), stop en çok
  hedef kadar. Amaç: işlem başına beklenen K/Z en yüksek (carry'si içinde, kayıt nerede tutuyorsa), şartlar **ödül / risk =
  m ÷ k ≥ 1** ve **en az 30 işlem** (grubun azsa ailenin bütün grupları birlikte; aile de azsa ayarlı seviye yok, kendi
  kuralı ve nedeni). Stop 0,5 – 3 σ, hedef en çok 4 σ (daha yakını bir iki günün gürültüsü, ötesi seviye değil). Hedef
  kendi seviyesinde (limit emri), stop kendi seviyesinde ya da onu geçen kapanışta (boşluk işlemindir), yoksa süre
  sonundaki kapanış. **Stoplar kapanışlarla ölçüldüğü için gün içi dokunma ihtimaline göre düzeltildi**
  (Broadie-Glasserman-Kou): tarihçede yalnız kapanışlar var, gün boyu duran bir emre gün içinde de gelinir; stop, bir
  kapanış ona 0,58 × kapanış başına σ kadar yaklaşınca (5 günlük tutmada tutmanın σ'sının 0,26'sı) çalışmış, hedef ancak
  bir kapanış onu o kadar geçince ulaşılmış sayılır (dokunmak dolmak değildir). k ve m'nin seçimi, isabet ve beklenen
  K/Z bu kuralla; listede ve kartta gösterilen (emrin verildiği) hedef ve stop düzeltilmemiş k σ ve m σ'dır.
* **Trend**: hedef yok, **iz süren stop** - en iyi seviyeden k × aylık σ (günlük σ × √21) geri (aynı düzeltmeyle: en iyi
  kapanıştan k − 0,13σ geri gelen kapanış yeter); ödül / risk kazanan işlemlerin ortalaması ÷ k (≥ 1); satır "iz süren
  stop" der; kayıt ve geri test stopu en iyi seviyenin arkasından taşır.
* **Carry + momentum**: kalibrasyon **sepet** üstünde (sepetin kendi, çeşitlendirilmiş haftalık σ'sı: hafta içindeki her
  kapanışta sepetin K/Z'si); her bacağa sepetin k ve m'si bacağın kendi haftalık σ'sıyla; kart sepetin ödül / riskini
  gösterir.
* **Satır.** Giriş şimdiki seviye; hedef ve stop katlar × enstrümanın bugünkü σ'sı. Yanında **ödül / risk**,
  **isabet** (o seviyelerle örneklem dışı kayıt: her ayın işlemleri o ay başlamadan seçilen seviyelerle; 10'dan azsa
  bugünkü seviyelerin örneklem içi kaydı, yazılır), **beklenen K/Z** (işlem başına ortalama × bugünkü σ, ailenin para
  çevrimiyle) ve **işlem sayısı**. Grup beklenen K/Z'ye göre sıralanır. En iyi seviyelerle bile geçmişte zarar ettiren
  kurulumun satırı listede kalır: **düşük güven**, nedeni "bu kurulum bu seviyelerle geçmişte zarar ettirdi" (kayda ve
  alarma düşmez; kapısı olmayan aileler - Trend, Carry + momentum - de).
* **Ailelerin seviye kuralı.** Yürüyen geri testteki her aile (PCA kalıntısı, PCA-nötr fly / spread, FRA / PPK patikası,
  makro artık, eşbütünleşik ve Kalman çift, VİOP takvim, momentum, PPK döngüsü, vol primi ve tahmini, EM carry, forward
  primi, tahmin modeli; ve artık geri teste giren **Eğri adil değeri**, **Opsiyon smile**, **Öncü-takipçi**) yukarıdaki
  sabit kuralla (ortalamaya dönüşte adil değer adayıyla); Trend iz süren stopla; Carry + momentum sepetten; Makine
  öğrenmesi kendi örneklem dışı tahminlerinin işlemlerinden (sabit kural, 5 günlük σ). **Kendi seviyesini tutanlar**:
  VİOP adil değer (sayfanın emir seviyeleri ve doluş olasılıkları), İma kalibrasyonu (toplantının iki sonucu), gün içi
  aileleri (5 dakikalık barlar, seans sonu; günlük geri testi yok), korelasyon kırılması (K/Z σ'sı yok); günlük geri teste
  giremeyen İma patikası ayrıklığı (patika her gün yeniden kurulur) ve DİBS adil değeri (çalışma kitabının kâğıt
  listesi) de kendi kuralıyla - satırları nedenini yazar.
* **Geri test paneli** her aileyi ayarlı seviyeleriyle raporlar (örneklem dışı kayıt, grup başına satır) ve bugün seçilen
  k ve m'yi *Seviyeler* sütununda gösterir; kendi seviyesindeki aile kendi işlemleriyle, nedeniyle.
* **Maliyet.** Bir ayın seçimi (aile, grup, ay, işlemlerin özeti) anahtarıyla saklanır: aynı veriyle ikinci tam hesap,
  canlı yenileme ve geri testin yeniden kurmaları hiçbir şeyi yeniden seçmez; düzeltilen bir kapanış yalnız onu gören ayları.
  Masa bilgisayarında sentetik iki yıllık tarihçede tam hesaba eklenen: soğuk başlangıçta ~0,5 sn (Trend ~0,3 sn, ML
  ~0,15 sn, Carry + momentum ~0,02 sn), sonraki tam hesaplarda ~0,2 sn; geri test (ayrı iş parçacığı) yolları kaydedip
  üç aileyi daha yeniden kurduğu için ~50 sn'den ~80 sn'ye, kalibrasyonu ~0,05 sn. Bloomberg'e yeni istek yok.
* **Yeni bir aile** hiçbir ek kod istemez: yürüyen geri testin yeniden kurmalarında koşuyorsa yollarını geri test
  kaydeder; kendi yürüyen testi olan aile (ör. **Opsiyon → spot**) işlemlerini tablosunun `backtest`'inde geri testin
  işlem biçiminde ve yollarıyla verir (`path_sigma`: her kapanışta işlemin lehine hareket, tutmanın σ'sı cinsinden, çıkışı
  ne olursa olsun bütün ufuk; `sigma`, toplam `carry`, `horizon`; isteğe bağlı `mae_sigma` / `mfe_sigma`, `end_day`,
  `group`) - her tam hesapta ayarlanır ve satırlarına uygulanır. Sözleşme `tto/quantlevels.py`'nin başında.

**Sıralama (bileşik puan)** = |z| × rejim uyumu × yarı ömür uyumu × carry yönü, ve her çarpan açıklanır (kartta ve
*Bileşik* sütununda; listenin grup içi sırası artık beklenen K/Z'ye göre, bileşik eşitliği bozar):

* |z| masanın ölçeğinde (kendi eşiği olan aile – momentum, döngü – eşiğine göre ölçeklenir), en çok stop eşiği kadar sayılır;
* rejim: ortalamaya dönüş sinyali ortalamaya dönen rejimde 1, nötrde 0,5, trendde 0 (elenir); momentum tersi;
* yarı ömür: ufuk (20 iş günü; gün içi sinyallerde bar cinsinden - ailenin tutması ya da seansın kalanı) içindeyse 1, ufkun iki katına kadar ufuk ÷ yarı ömür, ötesi 0 (elenir);
* carry işlemin aleyhineyse 0,5 (faiz); FX'te carry seviyenin içindedir, aleyhine olan carry kapısından geçmeli.

Eşiği geçip bir kapının (rejim, yarı ömür, stop bölgesi, hareketli ortalama, trend, carry, beklenen kâr, örneklem,
tolerans, seviyelerin zarar ettiren kaydı) tuttuğu sinyaller listeden düşmez: **düşük güven** etiketiyle, nedeni son sütunda (*Bileşik / neden*), gri,
grubunun güvenli sinyallerinden sonra durur; kayda ve alarma düşmez (yalnızca kapılardan geçen sinyaller kaydedilir ve
bildirilir). Önceki ayrı "Elenen sinyaller" paneli kalktı: hepsi tek listede. Analiz sayfalarının kendi listeleri de
aynı etiketi kullanır.

**Evren, gruplar ve listenin sırası** (`tto/quantuniv.py`). Sinyaller listesi gruplara göre sıralanır, üstünde her
grubun düğmesi (sinyal sayısıyla) ve **Tümü**: en üstte **Konsensüs** (birden çok ailenin aynı enstrümanda aynı yönde
olduğu satırlar, [aşağıda](#konsensüs); abonelikte grup değildir: kendi alarmı yok), **G10 spot** (EURUSD, USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF, NZDUSD),
**G10 opsiyon**, **TRY OIS** (önce **≤ 2Y** satırları, sonra uzun uç), **DİBS**, **VİOP** (borsa: TRY grubunda, offshore
değil), **Offshore** (USDTRY / EURTRY forward'ları, swap puanları, offshore eğrisi, USDTRY opsiyonları; her satırda
**offshore limiti** etiketi: masanın offshore işlem limiti dar) ve evrenin dışında kalan eski sinyaller için **Diğer**
(EM pariteleri, küresel sürücüler, USD faizleri). Grubun içinde güvenli sinyaller **beklenen K/Z'ye göre** (ayarlı
seviyelerle, TL, satırın kendi büyüklüğüyle; eşitlikte bileşik), sonra düşük güvenliler de aynı sırayla. Mevcut ailelerin sinyalinin grubu ana bacağından (varlığı TRY OIS / DİBS / VİOP / Offshore ise
o; USDTRY ve TRY çaprazları Offshore; G10 paritesi spot ya da opsiyon; TRY OIS'te paketin ana bacağı - hedge'li paket - ya
da en uzun bacağı - spread / fly / FRA - 2Y'ye kadarsa ≤ 2Y). Seçilen grup hatırlanır; launchpad kutusu ve abonelik de
grup seçer. Satır ve kart grubu yazar ("TRY OIS · ≤ 2Y", "Offshore · offshore limiti").

Evren, sistematik ailelerin (**Trend**, **Carry + momentum**, **Makine öğrenmesi**, **Opsiyon → spot**, **DİBS switch**) gezeceği enstrüman listesidir;
her enstrüman: anahtar, grup, öncelik, masanın diliyle adı, birimi ve büyüklüğü, seviye hareketinin paraya çevrimi,
yön sözcükleri, günlük kapanışları ve canlı değeri, günlük σ'sı (son 60 değişim), carry + roll'u ve paketse DV01
ağırlıklı bacakları:

| Grup | Enstrümanlar | Büyüklük, para | Yön | Carry + roll |
|---|---|---|---|---|
| G10 spot | 7 paritenin spotu | 1 mn baz döviz, K/Z USD | AL / SAT | 3A forward puanından (paritenin carry'si) |
| G10 opsiyon | 7 parite × ATM 1A / 3A, 25D RR 1A / 3A, 25D BF 3A (35) | 10.000 $ vega / vol puanı | vol al / sat, RR al / sat, BF al / sat | - |
| TRY OIS ≤ 2Y | outright 1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y; spread 1M/3M … 6M/2Y (10, uzun − kısa, DV01 1:1); fly 1M/2M/3M … 1Y/18M/2Y (8, OIS sayfasının "TÜM FLY'LAR"ı, 50/50 DV01); FRA 3×6, 6×9, 9×12, 12×15, 15×18, 18×24 (her günün eğrisinden); sıradaki 1., 2., 3. PPK dönemi | 1.000 $ DV01, K/Z TL | pay / receive, steepener / flattener, gövde pay / kanatlar receive | Carry & Roll motorundan (PPK dönemi 0) |
| TRY OIS uzun | outright 3Y, 5Y, 10Y; spread 2Y/3Y, 2Y/5Y, 3Y/5Y, 5Y/10Y; fly 1Y/2Y/3Y, 2Y/3Y/5Y, 2Y/5Y/10Y | aynı | aynı | aynı |
| DİBS | DİBS RV listesinin sabit kuponluları (vadesine 30 günden az kalan hariç) | 1.000 $ DV01 için nominal (DV01 DİBS RV!AI gibi), K/Z TL | SAT / AL (getiri yükselince SAT kazanır) | DİBS eğri uyumunun carry + roll'u |
| VİOP | işlemdeki kontratlar: ima TRY faizi spot'a karşı (VİOP ailesinin paketi) | 1.000 $ DV01 (kontrat sayısıyla), K/Z TL | AL / SAT (vadeliyi al, spot sat) | - |
| Offshore | USDTRY 1A / 3A / 6A / 1Y ve EURTRY 3A forward; aynı vadelerin swap puanları; offshore eğrisinin vadeleri | forward ve puan 1 mn baz döviz (K/Z TRY; bir puan 10⁻⁴ TRY), faiz 1.000 $ DV01 (K/Z TL) | AL / SAT, pay / receive | forward ve puan: puanların spota yuvarlanması |

15M ve 21M (ara değerlenen vadeler), 4Y, 6Y – 9Y, 1W, 2W ve UST 2Y / 10Y, DXY, Brent, CDS, EM FX, TLREF, USD OIS 3M, USDTRY
spot **yalnızca girdidir**: modeller okur, hiçbir zaman işlem satırı olmaz. Ayrıntılar: fly'ın seviyesi 50/50 paketinki
(gövde − kanatların yarısı, bp; OIS sayfasının 2·gövde − kanatlar kotasının yarısı: bir bp'si paketin DV01'inin bir
bp'si, PCA / RV sayfasının klasik fly'ları gibi); evrenin yazdığı her yerde - işlem satırı, kartın cümlesi ve giriş /
hedef / stop'u, listenin ipucu, gerekçenin stop'u, `/api/quant/universe` - yanında masanın okuduğu OIS sayfası kotası
durur: "giriş -12,5 bp (OIS sayfasında -25,0)". FRA'lar her günün kotalarından masanın konvansiyonuyla (≤ 3A tek
ödeme, uzunlar üç ayda bir kupon, spot ertesi iş günü) - her çeyreğin kotası (15M ve 21M dahil) varken bootstrap tek
geçişte tam, eksik çeyrekte FRA / PPK ailesinin `curve_dfs`'i; bacakları uzak vade pay / yakın vade receive, annuity
ağırlıklı (ileri başlangıçlı swap'ın DV01'i 1.000 $). PPK dönemleri **PPK Fiyatlama Geçmişi**'nden (tarihçenin her gün
çözdüğü toplantı tarihli patika, İma Patikası sayfasının kaynağı): k. dönemin seviyesi o günün spot'undan sonraki k.
toplantının ardından TLREF seviyesi; seri toplantı günü bir sonraki döneme geçer (o gün değişim sayılmaz), bacağı o
dönemin toplantı tarihli OIS'i. G10 forward primi seviyenin içinde değildir (seviye fiyattır): aile beklentisine tutma
süresinin carry'sini ekler. **Satırı kayan hiçbir şeye bağlı değil**: her satır kendi adıyla tutulur - OIS vadesi
etiketiyle, PPK dönemi toplantının tarihiyle (OIS_MAIN'in satırıyla değil: o günün patikasında tarih sırasıyla k.
toplantı), VİOP kontratı ticker'ıyla (VİOP sayfasının sütunuyla değil), DİBS ISIN'iyle (DİBS RV'nin satırıyla değil).
Takvim düzeltilince (toplantı eklenir, çıkar ya da tarihi değişir) tarihçenin henüz yeniden çözmediği eski günler eski
listeyle kalır: k. toplantının değiştiği gün dönem serisinde bir geçiştir, sıçraması piyasa hareketi sayılmaz
(`changes()` o günü almaz, `adjusted()` sıçramayı çıkarır); başka bir toplantının geçmişi bu döneme eklenmez. Kontrat
dönünce ya da yeni kâğıt eklenince hiçbir satır başkasının geçmişini, canlı değerini ya da büyüklüğünü almaz. Saklanan
abonelik grupları, seçilen grup (tarayıcıda) ve launchpad kutusunun grubu grubun adıdır.

**Yeni ailelerin takıldığı yer.** Bir aile kendi modülünde (`tto/quanttrend.py`, `tto/quantsira.py`, `tto/quantml.py`,
`tto/quantoptspot.py`, `tto/quantdibssw.py`)
`@quantuniv.family("trend")` ile kaydettiği `fn(ctx, reg, cfg) -> (monitors, table)` işlevidir; modül varsa her tam
hesapta diğer ailelerden sonra ve geri testin her yeniden kurulmasında çalışır, başka dosya değişmez. `inst.monitor(…)`
bacakları, büyüklüğü, K/Z birimini, FX paritesini ve parayı kurulmuş monitörü verir; kart, düz cümle, liste, kayıt,
alarm ve geri test (türü grubu) mevcut makineden gelir. Opsiyon ve swap puanı satırlarının parası da kartta yazar
(vol puanı × 10.000 $, puan × 100 TRY / 1 mn USD). Üç ailenin adı abonelikte ve aile süzgecinde şimdiden var
(sinyal üretmeden). Evren `/api/quant/universe`'te: her satırın grubu, seviyesi, σ'sı, carry'si, büyüklüğü ve bir
birim hareketin parası.

**Trend** (`tto/quanttrend.py`; Sinyaller'in **Trend** sekmesi): volatiliteyle ölçeklenmiş zaman serisi momentumu,
evrenin her satırında.

* **Skor.** Her enstrümanın 1A, 3A ve 1Y (21, 63, 252 iş günü) getirisi kendi K/Z biriminde - FX'te carry dahil (spotta
  forward'larından uzun tutmanın kazandığı / ödediği, forward'da ve swap puanında spota doğru kayış), faizde, DİBS
  getirisinde, spread'de ve fly'da seviyenin bp'si, vol'de vol puanı -, her biri enstrümanın günlük σ'sı (son 60 K/Z
  hareketi) × √gün'e bölünür; skor üçünün ortalaması, ±2 ile sınırlı. Bir yıldan kısa geçmişte uzun ufuk eldeki gün
  kadardır; 63 kapanıştan kısa geçmişte satır yoktur (tabloda nedeniyle). Sayılar seviyenin yükselen tarafınındır
  (evrenin yön sözcükleri): skor artıysa yükselişe (AL, pay, vol al, steepener; DİBS getirisinde SAT), eksiyse düşüşe
  oynanır - faizde receive tarafından bakmak aynı kararı verir, skor artı = pay olsun diye seviyenin yönünde yazılır.
* **Kapı yok.** Her gün her enstrümana bir satır: zayıf skor zayıf satırdır (|skor| 0,5'ten küçükse Zayıf, 1'den
  küçükse Orta, 1 ve üstü Güçlü), listeden düşmez, grubunda beklenen K/Z'sine göre sıralanır (bileşik = |skor| × giriş
  eşiği, en çok stop eşiği, eşitliği bozar). Yönü dünkü kapanıştan beri dönen satır **YENİ** yazar (artık grubun başına
  atlamaz: sıra beklenen K/Z'nin). Tek tutan şey seviyelerin kaydı: grubunun iz süren stopu geçmişte zarar ettirdiyse
  satır **düşük güven** (listede kalır, kayda ve alarma düşmez).
* **Büyüklük.** Masanın birimi aynı günlük riske ölçeklenir: *Trend · hedef günlük risk* (masa ayarı, USD, varsayılan
  **5.000 $**) ÷ bir birimin günlük σ'sı (USD; TL / TRY satırlar USDTRY'yle), iki anlamlı basamak, 0,1 – 10 birim:
  "EURUSD 710 bin EUR", "2Y OIS 610 $ DV01", "EURUSD ATM 1A vol 33.000 $ vega". 5.000 $ tipik satırı ~1 birim yapar: G10
  spotunda (günde ~%0,5) bir birim ~5 bin $, TRY OIS satırlarında ~3 – 15 bin $, vol satırlarında ~1 – 4 bin $ oynar.
* **Hedef yok, iz süren stop** (*Seviyeler*, `tto/quantlevels.py`). Yürüyen testin her pozisyonu (ilk günün ya da bir
  dönüşün satırından sonraki dönüşe kadar) yoluyla, **aylık σ** cinsinden (girişte bilinen günlük σ × √21) - o anda
  süren pozisyonlar ayın başındaki kârlarıyla: k, 0,5 – 3 arasından işlem başına beklenen K/Z'si en yüksek olan,
  kazanan işlemlerin ortalaması en az k olmak şartıyla (ödül / risk = ortalama kazanç ÷ k ≥ 1); her ay o ay başlamadan
  bilinenle, grubun (30'dan az işlemde ailenin). Stop: en iyi seviyeden k × bugünkü aylık σ geri (satırda bugünkü
  girişten). Beklenen K/Z: o stopla işlem başına ortalama (örneklem dışı) × bugünkü aylık σ (FX'te ve swap puanında carry
  içinde; faizde üstüne Carry & Roll'un carry + roll'unun o stopla ortalama tutmaya düşen payı); tutma o stopla ortalama
  tutma. Pozisyon yön dönene ya da iz süren stopa kadar tutulur. Kalibrasyon yoksa eski kural: aynı güç dilimindeki
  (|skor| 0 – 0,5, 0,5 – 1, 1 – 1,5, 1,5 – 2) geçmiş günlük satırların ortalama kazancı hedef, tutmanın 2σ'sı stop.
* **Satır**, Sinyaller listesinin *İşlem* sütununda planın biçiminde: `YENİ · SAT USDTRY 1A forward · 1 mn USD · offshore
  limiti · giriş 44,3500 · iz süren stop 44,5500 · beklenen +300 bin TRY · isabet %41 (148) · model: Trend`. İsabet ve
  işlem sayısı iz süren stopun örneklem dışı kaydından (kârda kapananların payı). Kartın cümlesi: ne yapılır, neden
  (hangi ufuklar aynı yönde, skor, kaç gündür bu yönde), ne beklenir (tutma ve para - satırın büyüklüğünde, G10'da USD),
  iz süren stopun σ'sı ve bugünkü yeri parayla, ödül / risk (ortalama kazanç ÷ stop), geri testin isabeti.
* **Yürüyen test.** Her geçmiş günün satırı o gün çizildiği gibi: skoru o güne kadarki kapanışlardan, stop'u o güne
  kadar kapanan ve hâlâ açık (o günkü kârıyla) satırların tutmasından; yön dönene ya da stopa kadar izlenir. Açık satırlar
  dışarıda kalsaydı süren her trend eksik kalır, yalnız dönenler sayılırdı (kazanç eksiye kayardı): son kapanışta açık
  olanlar o günkü kârıyla sayılır. İşlem: ilk günün ve her yön dönüşünün satırı, bir sonraki dönüşe ya da stopa kadar
  (stoptan sonra yeni dönüşe kadar pozisyon yok); Sharpe aynı riskle tutulan pozisyonların günlük K/Z'sinden, yıllık.
  Hiçbir gün kendinden sonraki veriyle karar vermez.
* **Geri test paneli, kayıt, alarm.** Sinyaller'in geri test paneli Trend'i kendi yürüyen testinin iz süren stoplu
  örneklem dışı kaydıyla gösterir (k grup başına). Yeniden kurmalarda Trend yine günlük pozisyonla koşar (düşük
  güvendeki satır - grubunun o güne kadarki iz süren stopu zarar ettirmişse - kayıttaki gibi açılmaz): satır yönünün
  ilk günü açılır, hedef ve süre sınırı olmadan yön dönünce ("dönüş", yeni yön aynı gün açılır) ya da iz süren stopta
  kapanır; evrenin FX satırlarının K/Z'sine carry eklenir. Sinyal kaydı ve abonelik alarmı bir Trend satırı YENİ olunca,
  günde bir kez: eski yönün kaydı "dönüş"le kapanır, yeni kaydın hedefi ve süresi yoktur (stop en iyi seviyenin
  arkasından gelir; stopta ya da dönüşte kapanır).
* **Sayfa** (`quant-trend`): her enstrüman bir satır - grup, skor, 1A / 3A / 1Y katkıları (toplamları sınırlanmamış
  skor), yön ve YENİ, pozisyondaki gün, büyüklük, beklenen K/Z, tutma, isabet, Sharpe; grup düğmeleri (hatırlanır);
  satıra tıklayınca kartı ve serisi (skorun gün gün geçmişiyle); altında güç dilimleri (hedeflerin kaynağı) ve grupların
  geri testi.
* **Süre.** İki yıllık sentetik veride ~100 satır × 504 gün: tam hesaba eklenen ~0,65 – 1,0 sn (evrenin serileri ~0,3 sn
  dahil - diğer evren aileleriyle ortak; skorlar ~0,15 sn, yürüyen test ~0,4 sn); iz süren stopun ayarı ilk hesapta
  ~0,3 – 0,4 sn (~3.900 pozisyon × 13 ay), aylar saklandığından sonraki hesaplarda ~0,15 sn; canlı yenileme yalnızca
  satırları canlı değerle yeniden puanlar (~20 ms); geri testin her yeniden kurulmasında aile yeniden koşar (ayları saklıdır).
* **Ortak makineye eklenenler** (diğer aileler de kullanabilir): monitörün `finish` kancası (make_signal'in sonunda
  ailenin son sözü), günlük satır (`daily`: kayıt / alarm ve geri test kuralı yukarıdaki gibi), listede YENİ'nin önce
  gelmesi, kartın İşlem satırında evren satırının kendi büyüklüğü.

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
gürültüsü × √bar ile z; öndeyse sat, gerideyse al; beklenen farkın yarısının bir saatte kapanması, tutma en çok bir
saat). PPK günü 13:45 – 15:30 arası ortalamaya dönüş sinyali elenir (PPK
açıklama penceresi); 17:00'den sonra yeni gün içi işlem yok; kayıtta gün içi giriş ufkunda ya da seans sonunda kapanır,
geceye taşınmaz. Kayıtlı veri modunda bar yoktur, sayfa bunu söyler.
Ortalamaya dönüş ailelerinin yarı ömrü bar cinsindendir ve yarı ömür kapısı onu bar cinsinden bir ufukla karşılaştırır
(masanın 20 iş günüyle değil): ailenin kendi tutması varsa o (carry patikası: bir saat, 12 bar), yoksa seansın kalan
barları (gün içi z, gün içi RV). Carry patikasının yarı ömrü farkın kendisinden ölçülür: geçmiş günlerin barlarında
farkın Ornstein-Uhlenbeck yarı ömrü, yalnızca gün içi adımlarla (fark her gün açılışta sıfırdan başlar; günden güne
geçen bir adım bu yeniden başlamayı patikaya dönüş sanardı). Ölçülemezse ailenin bir saati (12 bar) alınır; farkın
patikaya dönmediği ölçülürse (AR(1) katsayısı 1 ya da üstü) sinyal "ortalamaya dönmüyor" diye elenir, yarı ömrü bir
saati aşarsa ağırlığı düşer, ufkun ayardaki katını (varsayılan 2: iki saat) aşarsa elenir. Önceden bu ailenin yarı
ömrü hiç verilmiyordu: sinyali hep "ortalamaya dönmüyor" diye eleniyordu; gün içi z ve RV'nin bar cinsinden yarı ömrü
de 20 "gün"le karşılaştırılıyordu.

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
25 yeniden kurma ~40 sn (yolların kaydı ve Eğri adil değeri, Opsiyon, Öncü-takipçi yeniden kurmalara girdiğinden ~90 sn);
sonuç saklanır (`quant.backtest`), Sinyaller sayfasında "Geri test" tablosu. Her işlemin **yolu** tutma süresinin
sonuna kadar (kendi hedefi ya da stopu önce gelse de) kaydedilir ve ailelerin **seviyeleri** bu yollarla ayarlanır
(*Seviyeler*); tablo her aileyi ayarlı seviyeleriyle (örneklem dışı, grup başına) ve bugün seçilen k / m ile gösterir,
satırın "Geri test" sütunu ve kapısı da o kaydı okur ("bu aile seviyeleriyle son 1 yılda …").

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

**Seviyeler enstrümanın kendi biriminde** (masa, 24.11.2026: "Burada da 6x9 net bir seviye değil mi, bps olarak
yazdıklarını anlayamadım bunun da net olması lazım"). FRA / PPK patikası satırının seviyesi FRA'nın patikaya farkıdır
(bp); işlem ise FRA'nın kendisidir. Satır artık **FRA'nın faiziyle** konuşur: **giriş** FRA'nın şimdiki faizi (eğrinin o
dönem forward'ı, masanın konvansiyonuyla - ailenin zaten okuduğu, Trades'in FRA'sının tarihleri ve kuralıyla), **hedef
ve stop** farkın hedefte / stopta olduğu FRA faizi, bugünkü patika sabitken: bugünkü patikanın aynı dönem forward'ı +
hedefin / stopun farkı; bacakların şimdiki par faizleri ağırlıklarıyla ("sabit faiz alınan (receive): 9M OIS (%39,500)
×3,27 · sabit faiz ödenen (pay): 6M OIS (%40,100) ×2,27"). bp farkı kalkmaz, ikinci sırada yanında durur ("+6,9 bp
patikanın üstünde"). Kartın düz cümlesi: "6x9 FRA şimdi %38,720 (+6,9 bp patikanın üstünde); hedef seviyesine (%38,652;
+0,1 bp patikanın üstünde) gelirse 6,8 bp ≈ 343 bin TL kazanırsın, stop seviyesine (%38,730; +7,9 bp patikanın üstünde)
gelirse 1,0 bp ≈ 51 bin TL kaybedersin. Hedef ve stop bugünkü PPK patikasıyla (patikanın 6x9 forward'ı %38,651): patika
değişirse onlar da değişir." *Giriş / hedef / stop* satırı "%38,720 / %38,652 / %38,730 · 6x9 FRA (patika farkı +6,9 /
+0,1 / +7,9 bp; hedef / stop bugünkü PPK patikasıyla)", *Hedefte / stopta* "hedefte (%38,652) 6,8 bp ≈ +343 bin TL ·
stopta (%38,730) 1,0 bp ≈ -51 bin TL", *Model farkı* farkın kendisi ve FRA = patikanın forward'ı + fark, *Gerekçe*'nin
stop'u "Stop: 6x9 FRA %38,730 (giriş %38,720; +7,9 bp patikanın üstünde)". Aynı faizler listenin
satırında (*Birim* "6x9 FRA %", farkı ipucunda), Bugün'ün *Quant · yeni AL / SAT* satırlarında ("… 6x9 FRA % · patika
farkı +6,9 / +0,1 / +7,9 bp"), **alarmlarda** (masa alarmı ve abone bildirimi: "z +3,05 (Güçlü) · giriş %38,720 · hedef
%38,652 · stop %38,730 (6x9 FRA; patika farkı +6,9 / +0,1 / +7,9 bp)"; her satırın alarmı artık seviyelerini yazar -
FX'te forward'ın kuru, diğerlerinde kendi seviyesi) ve **İşleme al**'da: satır Trades'e **6x9 FRA** olarak girer (receive /
pay), fiyatı FRA faizi, hedefi ve stopu FRA faizleri, DV01'i paketin (1.000 $). Faizler **seviye gibi canlı hesaplanır**:
her canlı yenilemede FRA'nın faizi kotalarla oynar, hedef ve stop da satırın kendi farklarıyla (ailenin kuralı ya da ayarlı
seviyeler, eskisi gibi) yeniden faize çevrilir - hepsi bugünkü patikanın forward'ı üstüne; tarihçe patikayı yeniden
çözünce (15 dakikada bir) o forward da, onunla birlikte faizler de yenilenir. Bugünün patikası henüz yoksa satırın seviyesi son kapanışınkidir, faizleri
de: "hedef / stop 03.11.26 kapanışının PPK patikasıyla". Sinyal kaydı ailenin kendi seviyesini (farkı) izler; girişteki FRA
faizleri kaydın ipucunda ve alarmda. Bloomberg'e yeni istek yok.

**Faizler üç ondalıkla** (masa, 25.11.2026: "3 decimal"): quant satırlarının % ile yazılan her faizi - işlem yapılan
seviye, bacakların faizleri, seviyesi % olan aileler (outright OIS …) - kartta, listede, Bugün'de, alarmda, konsensüste ve
İşleme al'da üç ondalıkla: "%38,720 → %38,652" yanındaki farkın 6,8 bp'i okunur (iki ondalıkta %38,72 → %38,65 7 bp
okunuyordu); bp, fiyat, vol, FX ve z olduğu gibi.

**Aynı kural diğer ailelerde.** Seviyesi bir modele göre fark ya da kalıntı olan her aile, bugünkü model değeri tam bir
çevrim veriyorsa (enstrüman = model değeri + fark, model değeri sabitken) aynı biçimde konuşur - giriş / hedef / stop
enstrümanın kendi seviyesinde, fark yanında, canlı:

| Aile | Enstrümanın seviyesi | Sabit tutulan (model değeri) |
|---|---|---|
| FRA / PPK patikası | FRA'nın faizi (%) | bugünkü PPK patikasının aynı dönem forward'ı |
| Eğri adil değeri | vadenin faizi (%), hedge bacaklarının faizleri yanında | bugünkü NSS uyumunun o vadedeki par faizi |
| DİBS adil değeri | kâğıdın getirisi (%, kendi kuralıyla: basit / bileşik), komşu kâğıtların getirileri yanında | bugünkü NS uyumunun model getirisi (fark getiri farkıdır - birinci mertebe; ikinci mertebesi bp'nin yüzde biri) |
| PCA kalıntısı | ana vadenin faizi (%) | hedge bacaklarının bugünkü faizleri (ana bacağın ağırlığı 1: farkın bir bp'si faizin bir bp'si) |
| Eşbütünleşik / Kalman çift (DİBS, TLREF FRN, VİOP) | y bacağının seviyesi: DİBS getirisi (%), FRN'in fiyatı (fiyat = 100 − marj × yıl / 100), VİOP ima faizi (%) | OIS bacağının bugünkü seviyesi (denge α + β × OIS) |
| VİOP takvim | iki vade arasındaki ima TRY forward faizi (%, ACT/360) | OIS'ten faiz paritesiyle adil forward |
| VİOP adil değer | kontratın ima faizi (%, ACT/360); yanında kontratın fiyatı (bugünkü spot ve USD faiziyle) | vadesinin OIS'i (ACT/360) |
| Vol primi / Vol tahmini | ATM 3A ima vol (vol puanı) | son 63 günün gerçekleşen vol'ü / GARCH'ın 63 günlük tahmini |
| İma kalibrasyonu | dönemin seviyesi (%): patikanın o dönem için fiyatladığı faiz - Trades'e PPK dönemi olarak girer | patikanın tabanı (TLREF / SOFR) |
| Gün içi z (faiz) | vadenin faizi (%) | son 60 dakikanın barları (ortalama) |

Kendi seviyesinde kalanlar (işlem yapılan şey zaten o seviyedir ya da çevrim yoktur): **Korelasyon kırılması** (ρ: bir
enstrümanın seviyesi değil), **PCA-nötr fly / spread** (paketin seviyesi bacaklarının faizlerinden bp), **Makro artık**
(seviyesi vadenin faizi ya da FX'te forward'ın kuru; kalıntı yalnız z'de), **Momentum**, **Tahmin modeli**,
**Öncü-takipçi**, **Gün içi kırılım** (seviye enstrümanın kendisi), **PPK döngüsü** ve **Gün içi RV** (faizlerin farkı,
bp), **İma patikası ayrıklığı** (toplantı tarihli dönemlerin bp fly'ı), **Opsiyon smile** (kotalar vol puanında),
**DİBS switch** (getiri farkı, bp), **EM carry**, **Forward primi**, **USDTRY carry patikası** (FX: forward / spot kuru zaten),
**Trend**, **Carry + momentum**, **Makine öğrenmesi**, **Opsiyon → spot** (evrenin enstrümanları kendi seviyelerinde),
**Konsensüs** (en iyi ailenin satırının seviyeleri - onunki çevrilmişse çevrilmiş haliyle). **Offshore − OIS ve USDTRY puan
çiftleri** de kendi seviyesinde kalır: y'leri offshore'dur ve OIS'ten offshore seviye çıkarılmaz (`docs/curves.md`).

**Aileler:**

| Aile | Ne hesaplar | Sinyal |
|---|---|---|
| Korelasyon kırılması | OIS 3M–10Y, offshore 3M / 1Y, VİOP ön vade ima, USDTRY spot ve 3M swap puanı, CDS, UST 2Y / 10Y, DXY, EM FX, Brent: günlük değişimlerin 20 / 60 / 120 günlük korelasyonu (ısı haritası) | 20 günlük korelasyonun Fisher dönüşümüyle kendi uzun dönem dağılımına göre z'si (uzun dönem \|ρ\| ≥ 0,3 olan çiftlerde); işlem: son 20 günde ayrışan çiftin β ile yakınsaması |
| PCA kalıntısı | TRY OIS eğrisinin (≥ %80 kapanışı olan vadeler) **60 / 120 / 250 günlük pencerelerde** değişimlerinin kovaryansı (risk bileşenleri: PC1 seviye / PC2 eğim / PC3 eğrilik; açıklanan varyans, bugünkü skorlar ve z) ve seviyelerinin PCA'sı; pencereler arasında yüklerin kararlılığı (\|kosinüs\|, en büyük yük değişimi) | Her vade, iki komşusuyla **seviye-PCA'sının** PC1–PC2'sine nötr pakette (bp, pencerenin ortalamasına göre): + ucuz → receive, − pahalı → pay; en az gözlem kadar kapanışı olan en uzun pencere (sinyal yazar: "250 günlük pencere"), diğer pencerelerin z'si yanında; beklenen kâr carry + roll dahil; giriş / hedef / stop **ana vadenin faizinde** (hedge bacakları bugünkü faizlerindeyken), fark yanında |
| Fly / spread (klasik ve PCA ağırlıklı) | Masa ayarındaki listedeki her spread ve fly **iki sürümde yan yana**: klasik (masanın usulü, DV01'de spread 1:1, fly 50/50: paralel kaymaya nötr) ve PCA ağırlıklı (spread PC1'e, fly PC1 + PC2'ye nötr); her biri için seri, z, yarı ömür, rejim, carry + roll, bacaklar (DV01, nominal), **net DV01** ve kalan maruziyet - PC1 / PC2 / PC3'ün 1σ'luk hareketinde paketin hareketi Σ w × e × √λ (klasik fly'ın gizli seviye / eğim maruziyeti, PCA fly'ın sıfır olmayan net DV01'i) ve farkı söyleyen tek satır | Her sürümün kendi z'si, ayrı sinyal ("klasik 50/50" / "1:1" ve "PCA ağırlıklı"; aynı aile, birbirini uyum saymaz) |
| FRA / PPK patikası | 1x3, 3x6, 6x9, 9x12 forward'ı: OIS kotalarından (masanın konvansiyonuyla çözülen iskonto, log-doğrusal) ve aynı günün toplantı tarihli PPK patikasından; vade başına kota − patika par faizi (≈ 0: patika kotaları yeniden üretir); sıradaki toplantı dönemlerinin seviyesi ve fiyatlanan adım | Farkın z'si, fark ≥ 5 bp ise (altı çözücünün toleransı: elenir): + ise uzak bacak ucuz → FRA receive (uzak receive / yakın pay); giriş / hedef / stop **FRA'nın faizinde** (bugünkü patikanın forward'ı + fark), fark yanında; Trades'e FRA olarak girer |
| Makro artık | TRY OIS 3M–10Y ve USDTRY'nin forward pozisyonu getirisi (kur değişimi − forward primi), günlük değişimleri ~ UST 2Y / 10Y, DXY, EM FX endeksi, Brent, CDS (EKK, betalar ve t'leri); bugünkü hareket = küresel + TRY'ye özgü; kalıntının ertesi hafta geri dönen payı (sonraki 5 günün hareketinin kalıntıya regresyonu) | TRY'ye özgü kalıntının z'si: açıklanmayan yükseliş → receive / USDTRY forward sat; geçmişte geri dönmüyorsa beklenen kâr yok, elenir |
| Eşbütünleşik çift | Offshore − OIS (vade vade), VİOP ima − OIS (kontrat kontrat), DİBS getirisi − vadesindeki OIS, TLREF FRN iskonto marjı − OIS, USDTRY 3M puan farkı − (OIS 3M − USD OIS 3M): Engle-Granger (EKK + kalıntıya ADF, MacKinnon 2010 kritik değerleri) | Yalnızca geçen çiftlerde (ADF %5 ve \|t(β)\| ≥ 2) spread'in z'si; DİBS / FRN / VİOP çiftinde giriş / hedef / stop **y bacağının seviyesinde** (getiri, FRN fiyatı, ima faiz; OIS bacağı sabitken), fark yanında - offshore ve puan çiftleri kendi seviyesinde |
| Kalman çift | Aynı çiftler, hedge oranı rastgele yürüyüş (skaler Kalman filtresi) | Bir gün önceki β ile kalıntının z'si (ADF geçerse), statik olanla yan yana; seviyeleri eşbütünleşik çiftteki gibi y bacağının seviyesinde |
| VİOP takvim | Her VİOP vade çifti: fiyatlardan ima TRY forward faizi − aynı tarihler için OIS forward'ı (USD faiziyle faiz paritesi) | Farkın z'si: + ise uzak vade pahalı → uzak sat / yakın al; giriş / hedef / stop **iki vade arasındaki ima forward faizinde** (adil forward sabitken), fark yanında |
| Momentum | OIS vadeleri, offshore, UST, DXY, Brent, CDS ve her FX paritesi (forward pozisyonunun getirisi: kur değişimi − forward primi): 1H / 1A / 3A değişim ÷ (vol × √gün), gruplar içinde sıra, 20 / 60 günlük ortalama kesişimi | \|skor\| ≥ 1,5, ortalamalar aynı yönde, rejim trend (nötrde yarım ağırlık); FX'te forward primi aleyhine ise onu karşılamalı |
| PPK döngüsü | Her günün fazı (TLREF'in 63 iş günlük değişimi ≤ −100 bp indirim, ≥ +100 bp artırım, arası sabit); 2s10s, 1s2s, 2s5s'in sonraki ufuk boyunca değişimi faz başına, Newey-West t; çakışan gözlemlerin bağımsız dönem sayısı (n ÷ ufuk) ve o örneklemin kritik değeri | Bugünkü fazda en az 2 bağımsız dönem ve \|t\| ≥ max(2, örneklemin %5 kritik değeri): steepener / flattener |
| Vol primi | USDTRY, EURUSD, ZAR, MXN, BRL, INR, IDR, HUF, PLN, COP: ATM 3M ima − gerçekleşen (21 / 63 / 126 gün), 25D RR'nin spota duyarlılığı | İma − 63 günlük gerçekleşenin z'si: pahalı → vol sat, ucuz → al; giriş / hedef / stop **ATM 3A ima vol'de** (gerçekleşen sabitken), prim yanında |
| Vol tahmini | Aynı pariteler: EWMA (λ 0,94) ve GARCH(1,1) (ızgarada en çok olabilirlik, uzun dönem varyans hedefli) ile önümüzdeki 63 iş gününün ortalama vol'ü | İma − GARCH tahmininin z'si; vol primiyle aynı yöndeyse ikisi birbirini "uyum" olarak sayar; giriş / hedef / stop ATM 3A ima vol'de (tahmin sabitken) |
| EM carry | Her para birimi: 3M forward'ın ima ettiği yıllık getiri farkı ÷ ATM 3M vol, sıralama, kendi z'si | TRY'nin carry / vol'ü − EM sepeti ortalamasının z'si: cazip → USDTRY 3M forward sat (EM sepetine karşı) |
| Forward primi | USDTRY 1M / 3M / 6M / 1Y, EURTRY 3M: forward'ın ima ettiği yıllık değer kaybı − beklenen kayma (getirilerin EWMA'sı, λ 0,97, kesinliğiyle küçültülmüş); gerçekleşen kayma yanında | Tamponun z'si: + forward kaybı fazla fiyatlıyor → carry (forward sat), − tersi; beklenen kâr = tamponun ufka düşen payı (forward al ancak tampon eksiyse ve carry'yi karşılıyorsa); USDTRY'nin forward pozisyonu getirisi trendde ise bekletilir |
| Gün içi z / kırılım / RV, USDTRY carry patikası | 5 dakikalık barlar (yukarıda) | Gün içi: kendi ufku (bar) ve stop'u; PPK penceresi ve seans sonu kapıları |
| Tahmin modeli | OIS 1Y / 2Y / 5Y / 10Y, USDTRY (forward pozisyonunun getirisi), CDS, UST 10Y: gelecek haftanın yönü için L2 lojistik regresyon (özellikler: 60 günlük z, 1H / 1A momentum, carry, rejim, vol; katsayılar gösterilir); **zorunlu kayan pencereli doğrulama** - her hafta bir test noktası, model yalnızca etiketi o güne kadar bilinen örneklerle kurulur | Yalnızca doğrulanmış isabet ≥ %55 ve ≥ 40 test noktası olan enstrümanlarda; z = (p − 0,5) ÷ 0,05; isabet, log-loss ve test sayısı sinyalin yanında |
| Makine öğrenmesi | Evrenin 42 satırı (G10 spot / ATM 3A vol, TRY OIS ≤ 2Y ve 5Y / 10Y, spread / fly / FRA / PPK, DİBS 2 / 5 / 10 yıl, VİOP ön vade, offshore): önümüzdeki 5 iş gününün yönü için saf Python gradyan artırmalı ağaçlar, 41 özellik (TRY satırlarında USDTRY'nin opsiyonları), TRY OIS düz vadeleri tek ortak modelde; **aylık yeniden eğitim**, her ayın modeli yalnız sonraki ayda test (yukarıda: *Makine öğrenmesi*) | Örneklem dışı isabet ≥ %55, ≥ 40 test ve olasılık ≥ %60: "AL AUDUSD spot · 1 mn AUD · olasılık %65 · isabet %69 (64)"; hedef (2p − 1) × ortalama 5 günlük K/Z, stop 1,5σ; kartta en etkili üç özellik |
| Opsiyon → spot | 7 G10 paritesi ve USDTRY (Offshore): 25D RR 1A / 3A'nın haftalık değişimi, RR 3A'nın son bir yıla göre seviyesi, RR – spot ayrışması, ATM vol artışı × RR yönü (her biri kendi geçmişine göre z); bütün paritelerde birlikte kısmi havuzlu ridge (ortak katsayı + paritenin sapması), **aylık yeniden eğitim**, her ayın modeli yalnız sonraki ayda test; olasılık paritenin örneklem dışı ayarıyla (aşağıda: *Opsiyon → spot*) | Örneklem dışı isabet ≥ %55, ≥ 40 test ve olasılık ≥ %60: "25D RR 1A 1 haftada +1,2 vol (z +2,1; USD call'ları pahalandı), spot henüz gelmedi → AL USDJPY spot · 1,1 mn USD · giriş 150,250 · hedef 152,630 · stop 148,350 · beklenen +3,4 bin USD · isabet %57 (64)"; hedef 1,25σ, stop 1σ (σ: ATM 1A × √(5/252) × BF çarpanı), 5 gün - geçmiş işlemlerden kalibre edilen seviyeler gelince onların katları, isabeti ve beklentisi |
| Eğri adil değeri | TRY OIS 1M – 10Y: her gün Nelson-Siegel-Svensson uyumu, Excel'in OIS kuralıyla (3A'ya kadar tek ödeme, sonra üç ayda bir kupon); her vadenin kotası − NSS par'ı (bp), sıfır ve forward eğrisi | Farkın z'si: + ucuz → receive, − pahalı → pay; paket vade + uyumun seviye ve eğim faktörlerine nötr iki komşu vade; giriş / hedef / stop **vadenin faizinde** (NSS uyumu sabitken), fark yanında |
| DİBS adil değeri | DİBS RV'nin sabit kuponluları ve bonoları: sabit kuponlulara Nelson-Siegel uyumu (BIST kuralı; bonolar uydurmaya girmez, eğride fiyatlanır - masanın kararı, 18.11.2026), getiri − model getiri (bp), OIS uyumuna göre fark, 1H / 1A carry + roll, receive / pay için en iyi kâğıt | Farkın z'si: + ucuz → al, − pahalı → sat; paket kâğıt + seviye / eğim nötr iki komşu kâğıt, carry'si kâğıtların carry + roll'u; giriş / hedef / stop **kâğıdın getirisinde** (NS uyumu sabitken), fark yanında |
| Opsiyon smile | USDTRY ve EURUSD: ATM vade yapısı (1W – 1Y), 25D / 10D RR ve BF (1M, 3M), smile'ın forward'a göre ima ettiği ±X% olasılıkları ve gerçekleşen sıklık | z (vol puanı): 25D RR 1M / 3M (skew), 25D BF 1M / 3M ve 10D BF 1M (kanatlar), ATM eğimi 1Y − 1M - pahalı → sat, ucuz → al |
| İma patikası ayrıklığı | Her toplantının ima adımı (TCMB: tarihçenin PPK hesabı; Fed: USD kitabının FOMC tablosu) ızgaranın (50 / 25 bp) iki katının karışımı; bir dönemin seviyesinin komşularının ortalamasına göre kinki (ikinci farkın yarısı), kendi geçmişine göre z | Dönem komşularına göre ucuz → fly receive (+1 dönem, −½ komşular, toplantı tarihli OIS), pahalı → pay; en az 40 günlük geçmişle; senaryo K/Z, taşıma (0) ve tez notta |
| İma kalibrasyonu | Toplantı sıradakiyken (en çok 20 iş günü önce) büyük adıma verilen olasılık ile verilen karar (TLREF fixinginden; Fed: üst bandın günlük görüntülerinden) | En az 8 toplantıda kalibrasyon z'si girişin üstündeyse: sıradaki toplantının dönemi, piyasanın düşük fiyatladığı sonuca doğru; giriş / hedef / stop **dönemin faizinde** (taban + fiyatlanan hareket), Trades'e PPK dönemi olarak girer |
| Öncü-takipçi | Offshore ↔ OIS (aynı vadeler), USDTRY swap puanı ↔ OIS, VİOP ön vade ↔ OIS ve offshore, her VİOP kontratı ↔ kendi vadesinin OIS'i, USDTRY / EURTRY ↔ OIS ön ucu, OIS 1Y ↔ 2Y / 5Y, DİBS RV listesinin her sabit kuponlu kâğıdı / bonosu ↔ vadesine en yakın OIS: günlük değişimlerin −5 … +5 gecikmeli çapraz korelasyonu ve asimetrisi (kim önde), iki yönde Granger F-testi, gecikme, β (ℓ gün içindeki toplam tepki), R², 60 / 120 / 250 günde kararlılık | Lider son ℓ + 1 günde ≥ k σ oynadı, takipçi yetişmedi: beklenen yetişme = β × lider hareketi − takipçinin hareketi, z = yetişme ÷ σ; giriş / hedef / stop takipçinin biriminde; her pencerede tutmayan öncülük elenir |

**Sinyal kaydı.** Bir sinyal giriş eşiğini geçtiği an (önceki bakışta altındaydı) saat, seviye, z, hedef ve stop ile
yazılır (`quant.log`), sonra izlenir: **hedef**, **stop** ya da 20 iş günü sonra (**süre**) kapanır; kâr / zarar
seviye birimi ve sinyalin σ'sı cinsinden. Sinyaller sayfasında aile başına isabet tablosu (isabet = hedef + kârda
kapanan süre dolmuşlar ÷ kapananlar). Bu bir **backtest değildir**: yalnızca dashboard çalışırken görülen geçişler.

**Alarmlar.** *Sinyal alarmı aboneliği* (Sinyaller sayfası): açık / kapalı, aileler, gruplar (G10 spot … Offshore;
hiçbiri seçili değilse hepsi), en az güç; yalnızca kapılardan geçen sinyaller bildirilir. Bir geçiş olunca canlı
akış (`/api/events`) `quant.alerts` sayacını artırır; açık sayfa `/api/quant/alerts?since=` ile abone olduğu yeni
sinyalleri alır ve köşede gösterir (tıklayınca sinyal açılır). Bildirim ve masa alarmı satırın seviyelerini de yazar,
işlenen enstrümanın kendi seviyesinde ("z +3,05 (Güçlü) · giriş %38,720 · hedef %38,652 · stop %38,730 (6x9 FRA;
patika farkı +6,9 / +0,1 / +7,9 bp)"; FX'te forward'ın kuru). **Masa alarmları:** *Masa ayarları*ndaki "masa
alarmına düşen en az güç" (varsayılan **Güçlü**; Zayıf / Orta / kapalı) ve üstündeki her geçiş ayrıca masanın
alarmı olur (`tto/deskalarms.py`: herkese çalar, "Gördüm" ile cevaplanır, günün kaydına girer): her sinyal kendi
alarmıdır (`quant:<sinyal>`), kaydı hedef / stop / süreyle kapanınca alarm da kapanır; susturma masa alarmlarında
olduğu gibi kişiseldir (bir trader onu kendisi için susturur, alarm herkese yine çalar). Masa alarmları olmayan bir
sürümde bu adım atlanır. Başka dinleyiciler için
`service.quant.add_alert_hook(fn)` her yeni sinyal alarmını (`{seq, sid, family, family_label, asset, group, expression,
z, level, unit, strength, day, time}`) verir.

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
spotlar, forward puanları (spotla birlikte her paritenin carry'si), ATM vol'ler, risk reversal'lar, Opsiyon
sayfasının vol'leri ve VİOP sayfasının beş serisi, en son G10 evreninin kendi serileri - 143 seri 4 turda (ilki
açılışta, ~45 dakika; her seri yine bir kez, toplam istek turda 5 serideki kadar); VİOP'un kontrat serileri yanlarında
kendi sıralarıyla turda 15 (aşağıda: *VİOP*). Bu sırada quant sayfaları eldekiyle çalışır; kapsam tablosu
dolmamış serilere **"geçmiş doluyor"** der, sayfanın üstündeki not kaç seri kaldığını söyler. Sonra her tur, tarihçenin
diğer serilerinde olduğu gibi yalnızca yeni günleri ister (masa 15 dakikalık güncellemeyi bütün seriler için tutar -
Trades'in SOFR fixing'i hariç: günde bir değer, günde bir kez).
**Tarihçenin kendi serileri** (OIS, offshore, XCCY, TLREF, DİBS) de quant için iki yıl tutulur: ilk doldurmada
kendi penceresi (*Geriye bakış*, 370 gün) bir kerede, ertesi günden itibaren önceki yıl - yalnızca eksik kısım, elindeki
ilk kapanışın bir hafta içine kadar (boş bir cevap cevap sayılmaz) - turda 40 seri, quant serilerinden sonra.
Hepsi **terminalde doğrulanacak**; FX vol ticker'ları FX sayfalarının fiyat kaynağıyla (varsayılan BGN) kurulur.
Pariteler masa ayarındaki listedir (*FX pariteleri*; USDTRY hep başta); liste değişince tarihçe yeni paritenin
serilerini aynı kuralla doldurur. **G10 evreni** (`tto/quantuniv.py`: yeni sistematik ailelerin) bu listeden
bağımsızdır: yedi paritenin spotu, 3M forward puanı ve vol'leri (ATM 1M / 3M, 25D RR 1M / 3M, 25D BF 3M) her zaman
tutulur - listenin ve Opsiyon sayfasının zaten tuttuğu seri ikinci kez istenmez (varsayılan listeyle 22 yeni seri:
NZDUSD'nin spotu, puanı, ATM 3M ve 25D RR 3M'i, altı paritenin ATM 1M, 25D RR 1M ve 25D BF 3M'i; listede G10 paritesi
yoksa en çok 45). Listede olmayan bir G10 paritesi FX analizlerine (momentum, vol primi, parite özeti) girmez, onlar
masanın listesinde kalır:

| Seri | Ticker'lar (terminalde doğrulanacak) |
|---|---|
| Spot | `USDTRY Curncy`, `EURTRY Curncy`, `GBPTRY Curncy`, `EURUSD Curncy`, `GBPUSD Curncy`, `USDJPY Curncy`, `USDCHF Curncy`, `AUDUSD Curncy`, `USDCAD Curncy`, `USDCNH Curncy`, `USDZAR Curncy`, `USDMXN Curncy`, `USDBRL Curncy`, `USDINR Curncy`, `USDIDR Curncy`, `USDHUF Curncy`, `USDPLN Curncy`, `USDCOP Curncy`, `USDCZK Curncy`, `USDKRW Curncy`, `USDCLP Curncy`, `USDILS Curncy` |
| ATM 3M vol | `<PARİTE>V3M BGN Curncy` - TRY çaprazları (EURTRY, GBPTRY) dışında her parite: `USDTRYV3M`, `EURUSDV3M`, `GBPUSDV3M`, `USDJPYV3M`, `USDCHFV3M`, `AUDUSDV3M`, `USDCADV3M`, `USDCNHV3M`, `USDZARV3M`, `USDMXNV3M`, `USDBRLV3M`, `USDINRV3M`, `USDIDRV3M`, `USDHUFV3M`, `USDPLNV3M`, `USDCOPV3M`, `USDCZKV3M`, `USDKRWV3M`, `USDCLPV3M`, `USDILSV3M` |
| 25D RR 3M | `<PARİTE>25R3M BGN Curncy`, aynı pariteler |
| Forward puanı | `TRY1M Curncy`, `TRY3M Curncy`, `TRY6M Curncy`, `TRY12M Curncy`, `EURTRY3M Curncy`, `GBPTRY3M Curncy`, `EUR3M Curncy`, `GBP3M Curncy`, `JPY3M Curncy`, `CHF3M Curncy`, `AUD3M Curncy`, `CAD3M Curncy`, `CNH3M Curncy`, `ZAR3M Curncy`, `MXN3M Curncy`, `BRL3M Curncy`, `INR3M Curncy`, `IDR3M Curncy`, `HUF3M Curncy`, `PLN3M Curncy`, `COP3M Curncy`, `CZK3M Curncy`, `KRW3M Curncy`, `CLP3M Curncy`, `ILS3M Curncy` (BRL, INR, IDR, COP, KRW, CLP NDF'tir: puan yoksa NDF ticker'ı, ör. `BCN3M`, `IRN3M`, `IHN3M`, `KWN3M`, `CHN3M`, gerekebilir) |
| Küresel | `USGG2YR Index`, `USGG10YR Index`, `DXY Curncy`, `CO1 Comdty` (Brent), `TURKEY CDS USD SR 5Y D14 Corp`, `USSOC Curncy` (USD OIS 3M) |
| G10 evreni (listeden bağımsız; listede olan ikinci kez istenmez) | spot `EURUSD`, `USDJPY`, `GBPUSD`, `AUDUSD`, `USDCAD`, `USDCHF`, `NZDUSD Curncy`; 3M puan `EUR3M`, `JPY3M`, `GBP3M`, `AUD3M`, `CAD3M`, `CHF3M`, `NZD3M Curncy`; vol `<PARİTE>V1M`, `<PARİTE>V3M`, `<PARİTE>25R1M`, `<PARİTE>25R3M`, `<PARİTE>25B3M` (`… BGN Curncy`, ör. `NZDUSDV1M BGN Curncy`, `USDJPY25R1M BGN Curncy`, `GBPUSD25B3M BGN Curncy`) - 49 seri, varsayılan listeyle 22'si yeni |
| Opsiyon (USDTRY ve EURUSD, 11'er) | ATM `USDTRYV1W`, `USDTRYV1M`, `USDTRYV6M`, `USDTRYV1Y`; `USDTRY25R1M`; `USDTRY25B1M`, `USDTRY25B3M`; `USDTRY10R1M`, `USDTRY10R3M`; `USDTRY10B1M`, `USDTRY10B3M` (hepsi `… BGN Curncy`); EURUSD'nin aynı on biri (`EURUSDV1W BGN Curncy` …); EURUSD forward puanı `EUR1M Curncy`, `EUR3M Curncy` - toplam 24 (ATM 3M ve 25D RR 3M yukarıda) |

Gruplar: TRY (USDTRY ve TRY çaprazları), G10 (iki para birimi de G10), EM (gerisi: EM FX sepeti ve EM carry bunlardan).
**Bloomberg maliyeti** (sahte terminalle ölçülen bir canlı gün, `tests/test_quant.py`; hit = istek başına menkul ×
alan): 143 quant serisi (22 parite, küresel sürücüler, Opsiyon sayfasının vol'leri, VİOP sayfasının USD OIS 1M / 6M /
1Y'si ve USDTRY'nin gün içi en yüksek / en düşüğü, G10 evreninin 22 yeni serisi) ilk gün iki yıllık doldurmada seri
başına bir kez (turda 40 seriyle 4 tur, ~45 dakika), VİOP'un 90 kontrat serisi yanlarında kendi sırasıyla turda 15
(aşağıda: *VİOP*), sonra - tarihçenin diğer serileri gibi - yalnızca yeni günleri: **günde bir kez, sonra en çok
saatte bir** (önce önbellek, 24.11.2026; önceden her 15 dakikalık turda; tur yine 15 dakikada bir; vadesi geçmiş
kontratın yeni günü hiç sorulmaz). Ölçülen masanın günü (08:00–18:45, 44 tur): 2.787 hit, 115.259 veri noktası
(423 seri soruldu, 289'unun geçmişi var; 143 quant serisi, 167'si VİOP'un), bunun 419 hit'i VİOP'un, 242'si G10
evreninin; önceki kuralla 97 turluk gün 21.065 hit'ti. **G10 evreni** (22 yeni seri): iki yıllık doldurma bir
kerelik 22 hit, 11.638 veri noktası (4. turda, quant serilerinin sonuncusu), sonra saatte 22 hit, 44 nokta - günde
~242 hit (önceden 96 turda 2.112; plandaki tahmin ~2.000 hit; ayrıca her yeni
ticker'ın canlı değeri için bir kez referans isteği, sonra akış - akış günlük limiti kullanmaz -, `NZD3M`'nin
`FWD_SCALE`'i altı saatte bir). Tarihçenin kendi serilerinin iki yıla uzatılması (C): ertesi gün seri başına bir kez,
yalnızca eksik yılı (gerçekte ~117 ticker, ~117 hit ve ~29.000 veri noktası bir kerelik; sahte terminalle ölçülen ertesi
gün: 08:00–09:00'da 5 turda 514 hit, yeni günler günün ilk turunda ve bir saat sonra 177'şer; önceden turda 217).
Hepsi günlük bütçenin (100.000) içinde.
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

#### Makine öğrenmesi

`tto/quantml.py`, Sinyaller'in **Makine öğrenmesi** sekmesi (`#/quant-ml`). Evrenin **42 satırında** önümüzdeki **5 iş
gününün yönü**: 7 G10 spot ve 7 ATM 3A vol; TRY OIS 1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y, 5Y, 10Y, 3M/1Y, 6M/2Y, 1Y/2Y, 2Y/5Y
spread'leri, 3M/6M/1Y ve 6M/1Y/2Y fly'ları, FRA 3×6, 6×9 ve 12×15 (evrenin ızgarasında 12×18 yok), sıradaki PPK dönemi;
vadesi 2, 5 ve 10 yıla en yakın sabit kuponlu DİBS'ler (ISIN'le), VİOP ön vade (vadesine en az 7 gün), offshore'da
USDTRY 1A / 3A forward, 3A swap puanı ve offshore 1Y (**offshore limiti**). Hepsi evrenin anahtarlarıyla; evrende olmayan
satır tabloda nedeniyle.

* **Hedef**: yukarı tarafın (AL, pay, steepener, vol al; faizde receive aşağı taraftır) önümüzdeki 5 kapanıştaki K/Z'sinin
  işareti, kendi biriminde: seviyenin hareketi (rulo günlerinin sıçraması çıkarılmış) ve FX'te (spot, offshore forward)
  tutmanın carry'si de. Faiz paketinin carry + roll'u geçmişte yok (vade motoru yalnız bugünün): beklenen K/Z'ye her
  ailede olduğu gibi `make_signal` ekler.
* **41 özellik**, her biri günün kapanışında bilinenle (sonrası hiç): kendi z'si (20 / 60 / 250 kapanış), momentumu (5 / 21
  / 63 kapanış, σ√n'e bölünmüş), carry'si (FX: forward'lardan yıllık %; faiz: TLREF'in üstü, bp; ATM vol: ima −
  gerçekleşen), 20 günlük oynaklığı ve 20 / 60 oranı; TRY OIS eğrisinin seviyesi, eğimi ve eğriliği (2Y, 2s10s,
  2s5s10s) ve 5 günlük değişimleri - aynı gün; UST 2Y / 10Y, DXY, EM FX, Brent ve CDS'in 1 ve 5 günlük değişimi, TLREF'in 3
  aylık değişimi, PPK patikasının sıradaki toplantıya fiyatladığı adım, VİOP − OIS farkı (30 gün), **opsiyonlar**: G10
  satırında kendi paritesinin 25D RR 3A'sı; diğer bütün satırlarda (TRY OIS, FRA, PPK, DİBS, VİOP, offshore) **USDTRY'nin
  25D RR 3A'sı ve ATM vol 1A'sı** (Opsiyon sayfasının tarihçede zaten tutulan kotaları; yeni Bloomberg serisi ya da
  alanı yok) ve yedi G10 paritesinin RR ortalaması (**küresel risk**), her birinin 5 günlük değişimi - bunlar **bir gün
  öncesinden** (kapanışları TRY'ninkinden sonra gelir); ufukta ay sonu var mı, haftanın günü; ortak modeldeki satırın
  vadesi (yıl). Olmayan özellik (kısa seri, eksik girdi, G10 satırında USDTRY opsiyonları) ağaçların kendi yolu olan
  ayrı bir değerdir.
* **OIS ortak modeli (1A–10Y)**: TRY OIS düz vadeleri (1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y, 5Y, 10Y) her ay **tek bir
  modelde**: on vadenin satırlarıyla kurulur (her satır kendi vadesinin günü, **vade bir özellik**), her vadeyi kendi
  satırından tahmin eder. Ayın modeli yalnız **o ay başlamadan etiketi bilinen** satırları görür - her satırın kendi beşinci
  kapanışı aydan önce, bütün vadelerde aynı kural: bir vadenin sonraki kapanışı ortak model üzerinden başka vadenin önceki
  ayına ulaşmaz. İlk ayı etiketi bilinen 100 **günün** olduğu ay (tek satırın başlangıcı; on vadenin birkaç günlük
  satırı değil); yaprak ve L2 vade sayısıyla çarpılır (bir günün on satırı birlikte hareket eder: on satır tek satırın on
  katı kanıt değildir - sentetik gürültüde çarpansız log-loss 0,747, √10'la 0,735, ×10'la 0,708; vadeler tek başına
  0,714). Her vadenin kaydı (isabet, log-loss, test) kendi günlerinden. **Spread, fly ve FRA'lar kendi modelleriyle**
  kalır - etiketleri başka türden hareket: sentetik evrende FRA'lar ortak modelde kötüleşti (isabet 0,521 → 0,508,
  log-loss 0,704 → 0,708); spread + fly'ın kendi ortak modelinde spread'ler iyileşirken fly'lar kötüleşti (3M/6M/1Y
  0,758 → 0,711) ve toplam log-loss arttı (0,613 → 0,615); hepsi tek modelde basılan spread / fly 6'dan 4'e indi. Diğer
  satırlar (G10, vol, DİBS, VİOP, offshore) satır başına.
* **Model**: saf Python **gradyan artırmalı ağaçlar** (lojistik kayıp; 50 ağaç, derinlik 2, öğrenme 0,1; her ağaç
  satırların %70'i ve özelliklerin %50'siyle - bölünebilen özelliklerin: satırın hiçbir satırında olmayan ya da sabit
  özellik, G10 satırında USDTRY opsiyonları gibi, yer tutmaz -, yaprakta en az 30 satır, yaprak değerinde L2 30;
  ortak modelde ikisi vade sayısı katı). Her özellik eğitim
  satırlarının 10 kantiline bölünür; bölünmeler düğümün histogramından aranır (büyük çocuğunki çıkarmayla). Satır ve ay
  başına tohumlu: aynı veri aynı model. Sentetik gürültüde derinlik 3, L2 1 ve 20'lik yaprak gürültüyü öğreniyordu
  (örneklem dışı log-loss 0,82, olasılıklar %50'den ±17 puan); bu ayar dikili sürücüyü (%71 isabet) korur, gürültüde
  0,72'ye (±8 puan) iner ve üçte iki sürede biter.
* **Aylık yeniden eğitim**: her takvim ayının modeli yalnızca **o ay başlamadan etiketi bilinen** satırların hepsiyle
  kurulur (beşinci kapanışı aydan önce) ve yalnızca o ayın günlerini tahmin eder; bugünü bu ayın modeli tahmin eder.
  Etiketi bilinen en az 100 satırın olduğu ilk aydan bugüne: iki yıllık geçmişte ~15 ay örneklem dışı. **İsabet** ve
  **log-loss** etiketi bilinen bütün örneklem dışı günlerden; **test** = gün ÷ 5 (5 günlük ufuklar örtüşür).
* **Satır** yalnızca örneklem dışı isabet ≥ masanın model eşiği (%55) ve ≥ 40 test olan (Tahmin modelinin kuralı ve
  ayarları) ve bugünkü olasılığı girişi geçen (z(p) = (p − 0,5) ÷ 0,05 ≥ giriş: %60) enstrümanda:
  "AL AUDUSD spot · 1 mn AUD · olasılık %65 · isabet %69 (64)". **Hedef ve stop ayarlı** (*Seviyeler*): ailenin örneklem
  dışı tahminlerinin işlemleri (olasılığı girişi geçen her gün, satırda bir işlem açıkken yenisi yok, 5 kapanış) yollarıyla,
  5 günlük σ cinsinden (o günden önceki 60 hareketin σ'sı × √5; FX'te carry yanında), grup başına aylık yürüyen: stop k,
  hedef m × bugünkü 5 günlük σ, ödül / risk ≥ 1, isabet ve beklenen K/Z o seviyelerin kaydından; kalibrasyon yoksa eski
  kural (hedef (2p − 1) × son 250 satırın ortalama |5 günlük K/Z|'sı, stop 5 günlük σ'nın 1,5 katı). Geri testin yeniden
  kurmaları günün ayının seviyeleriyle oynar. Tutma 5 iş günü; büyüklük masanın birimi, K/Z para olarak (evrenin `inst.monitor`'ü:
  kart, para, liste, kayıt, alarm). Kartın düz cümlesi ne yapılacağını ve **nedenini** söyler - bugünkü tahmini en çok
  oynatan üç özellik (ağaçların bu satırdaki yol katkıları), masanın diliyle: "… yükseliş olasılığı %65 (örneklem dışı
  isabet %69, 64 test, log-loss 0,575). Neden: en çok Brent son 5 günde +%12,5 (lehte), CDS son 5 günde -10,8 bp
  (aleyhte) ve Brent dün +%2,5 (lehte) etkiledi." Kapılarında *Örneklem* (kayıt, log-loss); FX'te carry aleyhine işlem
  her ailedeki gibi tamponu geçmeli.
* **Hesap**: ağır kısım tam hesapta, quant iş parçacığında. Her ayın modeli satırın anahtarı, ay ve eğitim satırlarının
  özetiyle saklanır (ortak modelin anahtarı modelin kimliği; ayarlar, özellikler ve ortak modellerin tanımı özette:
  başka ayarın modeli başka modeldir): aynı kapanışlarla ikinci tam hesap, canlı yenileme ve geri test **hiç model
  kurmaz**; yeni kapanış yalnız ayın ilk iş gününde kendi modeli olan satır başına bir, ortak model başına bir model
  kurar, geçmiş düzeltilince ya da dolunca yalnız satırları değişen aylar. Gün içinde yalnız canlı özellikler (seviye, eğri, carry) yeniden puanlanır. Ölçüm (geliştirme makinesi, başka
  testler çalışırken; sentetik 42 satır × 460 gün): yeniden başlatmadan sonraki ilk tam hesap **480 model ~36–41 sn**
  (USDTRY opsiyonları ve ortak modelden önce 615 model ~39 sn: yedi yeni özelliğe karşın - bir satırın hiçbir
  satırında bölünemeyen özellik ağacın özellik payında yer tutmaz - ve on vadeye ayda tek model); aynı kapanışlarla
  ~2 sn; ayın ilk günü 32 model ~5 sn (önce 41); ayın sonraki kapanışı model kurmadan ~2 sn. Masada ilk hesap ~45 sn
  ölçülmüştü: değişiklik onu artırmaz. Geçmiş uzadıkça ilk hesap uzar (750 günde ~100 sn, önce de ~95 sn): 90 sn'yi
  geçerse eğitim penceresine üst sınır (son N gün) konabilir. Kimlik hep evrenden: takvim düzeltmesi, VİOP rulosu, yeni ya da vadesi gelen kâğıt
  hiçbir satırın modelini, özelliklerini ya da tahminini başka satıra taşımaz.
* **Geri test**: yeniden kurmada aile bir şey eğitmez - o günün **örneklem dışı tahminini** canlı kurallarla oynar
  (olasılık girişi geçince; %55 kapısı yok, o kapı geri testin kendisidir), seviye satırın kendi kapanışı (rulo K/Z
  sayılmaz). Sinyaller'in geri test tablosunda aile satırı ve altında **satır başına** tür; sinyalin yanında kendi
  satırının kaydı (yeterli işlemi varsa).
* **Sayfa**: ailenin sinyalleri ve seçilenin grafiği (altında örneklem dışı olasılık gün gün, z(p) olarak); her satırın
  kapanış sayısı, testi, isabeti, taban oranı, log-loss'u, basılıp basılmadığı ya da nedeni ("geçmiş kısa (… kapanış; en
  az 126)", "örneklem dışı isabet %51,3 < %55", "olasılık %57,3 < eşik %60"; kuralı ve girişi geçip listede bir kapıya - FX carry tamponu, beklenen kâr - takılan satır "düşük güven: …"), bugünkü olasılığı ve en etkili üç verisi
  (↑ yükselişe, ↓ düşüşe), geri testi (olasılığın girişi geçtiği günlerin 5 günlük K/Z'si: isabet, Sharpe) ve aylık model
  sayısı (ortak modeldeki vadede "· ortak", ipucunda modelin adı); altında verilerin ağaç kazancındaki payı grup başına -
  her model bir kez, ortak model kendi sütununda (TRY OIS'in önünde). Kayıtlı veri modunda geçmiş kısa: hiçbir satır
  basılmaz, her biri nedenini söyler. Ortak modeldeki vadenin kartı modelin adını söyler ("… log-loss 0,668; OIS ortak
  modeli 1A–10Y). Neden: en çok USDTRY 25D RR 5 günde +1,50 (lehte), …"); USDTRY'nin opsiyonları adıyla geçer.
* **USDTRY opsiyonları ve OIS ortak modeli: kayıt, önce / sonra** (sentetik evren, `tests/quant_synth_ml.py`; gerçek
  veri bu makinede yok). Örneklem dışı isabet / log-loss / kuralı geçen satır (≥ %55, ≥ 40 test), gün ağırlıklı:

  | Satırlar | 460 gün (testlerin evreni) önce | sonra | 750 gün, gürültü önce | sonra | 750 gün, eğri USDTRY RR'ına bağlı (β 0,10) önce | sonra |
  |---|---|---|---|---|---|---|
  | OIS düz (10, ortak model) | 0,514 / 0,714 / 1 | 0,496 / 0,713 / 0 | 0,502 / 0,715 / 0 | 0,533 / 0,710 / 0 | 0,493 / 0,724 / 0 | **0,562 / 0,687 / 9** |
  | spread / fly (6) | 0,670 / 0,610 / 6 | 0,678 / 0,610 / 5 | 0,636 / 0,633 / 5 | 0,635 / 0,632 / 5 | 0,636 / 0,632 / 5 | 0,636 / 0,633 / 5 |
  | FRA (3) | 0,533 / 0,704 / 0 | 0,510 / 0,708 / 0 | 0,508 / 0,713 / 0 | 0,504 / 0,717 / 0 | 0,503 / 0,714 / 0 | 0,554 / 0,688 / 1 |
  | G10 spot + vol (14) | 0,531 / 0,699 / 4 | 0,530 / 0,698 / 4 | 0,527 / 0,703 / 5 | 0,529 / 0,702 / 5 | 0,524 / 0,702 / 5 | 0,529 / 0,702 / 5 |
  | DİBS / VİOP | 0,543 / 0,705 / 2 | 0,539 / 0,709 / 1 | 0,512 / 0,712 / 0 | 0,497 / 0,714 / 0 | 0,489 / 0,723 / 0 | 0,526 / 0,705 / 1 |
  | Offshore (4) | 0,693 / 0,547 / 3 | 0,702 / 0,546 / 4 | 0,702 / 0,538 / 3 | 0,699 / 0,537 / 3 | 0,691 / 0,542 / 3 | 0,705 / 0,532 / 3 |
  | **Hepsi** (41; basılan) | 0,564 / 0,676 / 16; 11 | 0,560 / 0,676 / 14; 11 | 0,551 / 0,681 / 13; 6 | 0,557 / 0,680 / 13; 6 | 0,544 / 0,685 / 13; 7 | **0,571 / 0,671 / 24**; 6 |

  Gürültüde kayıt aynı kalır (satır başına ±%3 oynama 64 testin gürültüsü; gürültüde şansla kuralı geçen OIS 1M ortak
  modelde geçmez); USDTRY'nin RR'ı eğriyi sürdüğünde eski özellikler göremez, yenileri bulur - yalnız yeni özelliklerle
  (ortak model olmadan) OIS düz 0,560 / 0,691, ortak modelle 0,562 / 0,687. Ortak modelin olasılıkları ölçülüdür
  (yaprağı tek satırınki kadar gün tutar): bağlı eğride bile bugünkü olasılık ~%57–61 - %60 girişini yalnız güçlü
  günlerde geçer (750 günlük bağlı evrende 9 vade kuralı geçti, o gün hiçbiri basılmadı). Ağaç kazancı (ortak model, bütün aylar):
  gürültüde opsiyonlar %9 (her biri %0,4–2,3: bilgisiz bir verinin payı), G10 RR ortalaması %1,8, vade %0; bağlı
  eğride opsiyonlar %44 (USDTRY RR'ının 5 günlük değişimi tek başına %33), G10 ortalaması yine %3,6. **G10 RR
  ortalaması** (küresel risk) sentetik veride hiçbir şeye bağlı değil; kazancı orada bilgisiz bir verininki kadar -
  karar gerçek veride: sayfanın "Verilerin payı" tablosu masada da bilgisiz düzeyde gösterirse çıkarılabilir.

#### Opsiyon → spot

`tto/quantoptspot.py`, FX girişinin **Opsiyon → spot** sekmesi (`#/quant-optspot`, Opsiyon'un yanında). Masa spot
işlem yapar: opsiyon piyasasının sinyalleri - 25D risk reversal'ın haftalık hareketi ve seviyesi, spotla ayrışması,
ATM vol'le birlikte yükselişi - **spot AL / SAT** satırına döner; yalnızca spotu örneklem dışında öncülediği kanıtlanan
paritede. Butterfly yön vermez: seviyeleri ölçekler.

* **Pariteler**: 7 G10 paritesi (evrenin spot satırları, G10 spot) ve opsiyonu tutulan **USDTRY** (spot satırı
  **Offshore** grubunda, "offshore limiti"; evren USDTRY spotunu yalnız girdi olarak tutar). EURTRY'nin opsiyon kotası
  tutulmuyor: satırı "opsiyon serisi yok" der. Kotalar evrenin anahtarlarıyla - ATM 1A / 3A, 25D RR 1A / 3A, 25D BF 3A
  (USDTRY'ninkiler Opsiyon sayfasının) -: **yeni Bloomberg isteği yok**. Her şey paritenin koduyla ve serinin
  anahtarıyla tutulur, hiçbir şey satırla değil.
* **Zamanlama**: opsiyon ve spot kapanışları aynı günün kapanışı; bir kapanışın sinyalleri o kapanışa kadarki
  kotalardan (en çok bir hafta eski), hedefi sonraki 5 kapanıştan. Her z o kapanıştan **önceki** 250 kapanışa göre (en
  az 60); bugününki canlı kotalarla (yoksa son kapanışla) aynı kuralla.
* **Beş sinyal**, her biri kendi geçmişine göre z: **25D RR 1A** ve **25D RR 3A**'nın 5 kapanışlık değişimi (÷ kendi 5
  günlük değişimlerinin σ'sı); **RR seviyesi** (25D RR 3A'nın son bir yıla göre z'si: aşırı skew); **RR – spot ayrışması**
  (RR'ın 5 günlük değişimi − β × spotun 5 günlük değişimi, β günlük hareketlerden: opsiyon oynadı, spot gelmedi);
  **vol × RR** (ATM 1A vol'ün 5 günlük artışının z'si - yalnız artış - × RR değişiminin z'si: vol ve skew birlikte,
  gerilimli yön). **25D BF 3A**'nın z'si yön vermez (aşağıda: seviyeler).
* **Hedef**: önümüzdeki 5 kapanışta uzun pozisyonun carry'li getirisi (spotun hareketi + forward'lardan carry) ÷
  opsiyonların ima ettiği 1 haftalık σ (ATM 1A × √(5/252)), ±4'te kırpılmış.
* **Model**: bütün paritelerde birlikte **ridge** regresyonu, kısmi havuz: paritenin katsayısı = ortak katsayı + kendi
  sapması (sapma 10 kat cezalı) - her yerde tutan bütün paritelerden, tek paritede tutan o paritenin satırlarından
  öğrenilir. Parite sabitleri (carry trade'in ortalama getirisi) tahmine girmez: tahmin μ (haftanın σ'sı) yalnız opsiyon
  sinyallerinin payıdır. Katsayının işareti verinin seçtiği yön: + **momentum** (call'lar pahalanınca spot yükselir), −
  **ters** (hareket geri döner). Olasılık Φ(c·μ ÷ s): s uyumun kalıntı σ'sı, **c paritenin ayarı** - örneklem dışı
  tahminlerin gerçekleşen payı (gerçekleşenin tahmine eğimi, 0 – 1; paritenin 100 örneklem dışı satırı olana kadar bütün
  paritelerinki). Tahmini hiç tutmamış parite, opsiyonu ne kadar oynarsa oynasın yazı-tura olasılığında kalır: 55 % / 40
  kuralını şansla geçen bir gürültü paritesi bu yüzden basılmaz.
* **Aylık yeniden eğitim** (ML ailesi gibi): her ayın modeli yalnızca o ay başlamadan etiketi bilinen satırlarla (bütün
  paritelerde en az 300) kurulur ve yalnız o ayı tahmin eder; bugünü bu ayın modeli tahmin eder. Normal denklemler ay ay
  büyür: bir ayın modeli küçük bir doğrusal çözüm. **İsabet**: μ'nün işaretinin carry'li getirinin işaretini tutturma
  payı, etiketi bilinen örneklem dışı günlerden; **test** = gün ÷ 5 (ufuklar örtüşür).
* **Sinyallerin kaydı** (havuzda ve parite parite): her sinyal, eğitim satırlarının seçtiği yönde (paritenin kendi
  içindeki eğimin işareti; havuz için toplamı) yalnız sonraki ayda oynanır - bir şey söylediği her gün (isabet, ortalama
  hareket; aynı 55 % / 40 kuralıyla "öncü"), |z| ≥ 1 günleri ve bilgi katsayısı (IC). Hangi opsiyon sinyalinin spotu hangi
  yönde öncülediği bu tablodadır; havuzun tersi yönü seçen pariteler ayrıca yazılır (modelde kendi sapmalarıyla).
* **Satır** yalnızca paritenin örneklem dışı isabeti ≥ masanın model eşiği (%55) ve ≥ 40 test (model ailelerinin
  kuralı) ve bugünkü olasılığı girişi geçince (z(p) = (p − 0,5) ÷ 0,05 ≥ giriş: %60): `25D RR 1A 1 haftada +1,2 vol (z
  +2,1; USD call'ları pahalandı), spot henüz gelmedi → AL USDJPY spot · 1,1 mn USD · giriş 150,250 · hedef 152,630 · stop
  148,350 · beklenen +3,4 bin USD · isabet %57 (64)` - işlemi açan sinyal (bugünkü tahmine işlem yönündeki en büyük katkı)
  masanın diliyle önde, sonra planın satırı: kurla giriş / hedef / stop, satırın büyüklüğünde beklenen K/Z (USD),
  isabet ve sayısı; veri ters yönü seçtiyse "geçmişte bu hareket tersine döndü". Kartın cümlesi: opsiyon piyasası ne
  yaptı, olasılık ve yöndeki kaydı, ayar, tahmini en çok oynatan üç sinyal (lehte / aleyhte), kurla giriş / hedef / stop
  ve para, seviyelerin nereden geldiği.
* **Seviyeler** opsiyonların ima ettiği 1 haftalık hareketten: σ = ATM 1A × √(5/252) × BF çarpanı (spotun %'si); giriş
  bugünkü spot, **hedef 1,25σ, stop 1σ** (ödül / risk 1,25), 5 iş günü; beklenen c·μ × σ. **BF çarpanı** da kanıttan:
  kanatlar pahalıyken haftalar ne kadar büyüktü (eğitim satırlarında y²'nin BF z'sine eğimi; örtüşme sayılarak iki
  standart hata içindeyse yok) → √(1 + b·z), 0,85 – 1,5 arası (kanıt yoksa 1); çarpan 1'in üstündeyse satır listede de
  geriler (bileşik ÷ çarpan). **Büyüklük**: masa ayarı *Opsiyon → spot · haftalık 1σ risk* (varsayılan **10.000 $**) ÷ bir
  birimin (1 mn baz döviz) 1σ haftası (USD), iki anlamlı basamak, 0,1 – 10 birim. Carry aleyhine işlem her ailedeki gibi
  tamponu geçmeli (USDTRY AL çoğunlukla "düşük güven"). **Geçmiş işlem yollarından kalibre edilen seviyeler** sinyalle
  gelince (`sg["levels"]`: hedef ve stop aynı σ'nın onun seçtiği katları, beklenen K/Z onun işlem başına beklentisi)
  satır ve kart onun katlarını, isabetini, işlem sayısını ve beklentisini yazar; ailenin kendi 1,25σ / 1σ'sı ve kaydı
  yalnızca kalibrasyon yokken (işlem az, başka bir kural) - kart seviyeler satırıyla hiç çelişmez.
* **Geri test** (ailenin kendi yürüyen testi): olasılığın girişi geçtiği (bir gün önce geçmemiş, açık işlem yok) her
  örneklem dışı gün o kapanışta işlem; hedef / stop kapanışlarda, yoksa 5. kapanış; K/Z carry'li. İşlemler geri testin
  biçiminde (`quantbt`) ve **yollarıyla**: girişten sonraki 5 kapanışın her birinde spotun işlem yönündeki hareketi
  haftanın σ'sı cinsinden (`path_sigma`, çıkıştan bağımsız bütün ufuk), yolun son kapanışı (`end_day`: kalibrasyonun ay
  sınırı onu tam kullanır), **MAE / MFE** (`mae_sigma`, `mfe_sigma`), sinyali, TRY K/Z giriş gününün kurlarıyla.
  Sinyaller'in geri test tablosunda aile ve parite parite tür; sinyalin yanında kendi paritesinin kaydı.
* **Süre**: tam hesaba eklenen ~0,3 – 0,5 sn (sentetik 8 parite × 500 gün: 3.480 satır, 18 aylık model; servis içinde
  ~0,4 sn). Canlı yenileme yalnız bugünkü satırı canlı kotalarla yeniden puanlar (model aynı).
* **Sayfa**: ailenin sinyalleri ve seçilenin grafiği (altında örneklem dışı olasılık gün gün, z(p)); **Pariteler** -
  bugünkü spot, ATM / 25D RR 1A / 25D RR 3A'nın 1 haftalık hareketi ve z'leri, RR seviye z'si, ayrışma, vol × RR, BF z'si
  ve çarpanı, olasılık, basılıp basılmadığı ya da nedeni ("geçmiş kısa (… kapanış; en az 265)", "opsiyon geçmişi kısa
  (25D RR …, ATM … kapanış; en az 265)" - vol'lerin iki yılı henüz dolmadıysa -, "örneklem dışı isabet %52,7 < %55",
  "olasılık %57,3 < eşik %60", "opsiyon serisi yok", bir kapıya takılan "düşük güven: …"), işlemi açan
  sinyal, test, isabet, c, geri test, büyüklük; **Opsiyon sinyalleri spotu öncülüyor mu?** - her sinyalin havuzdaki yönü
  (kaç ayın modelinde aynı), isabeti ve testi, güçlüyken isabeti ve hareketi, IC, öncü mü, kaydı tutan pariteler kendi
  yönleriyle, havuzun tersi yönlü pariteler. Kayıtlı veri modunda vol geçmişi yok: hiçbir satır basılmaz, her parite
  nedenini, kayıt tablosu kaydı olmadığını söyler.

### Eğri Adil Değeri ve Opsiyon

İki sayfa, üç aile (`tto/quantcurve.py`, `tto/quantopt.py`; sayfalar `tto/static/js/pages/quantfit.js`): diğer quant
aileleriyle aynı iş parçacığında, aynı sinyal biçimiyle, Sinyaller listesinde.

**Eğri Adil Değeri.** TRY OIS eğrisine her gün **Nelson-Siegel-Svensson** (NSS), DİBS'e **Nelson-Siegel** (NS: β3 = 0,
tek τ) eğrisi uydurulur; her vade ve kâğıt için eğriye göre farkı (bp), bunun z'si, yarı ömrü ve rejimi - aileler **Eğri
adil değeri** (OIS) ve **DİBS adil değeri**.

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
* *DİBS:* model Nelson-Siegel (β3 = 0, τ1 her iki ızgarada aranır; `quantcurve.DIBS_MODEL`), **yalnız sabit
  kuponlulara** (BIST kuralıyla) uydurulur (`quantcurve.FIT_KINDS`); bonolar eğride fiyatlanır, uydurmaya girmez - masanın
  kararı, 18.11.2026 (tabloda türün yanında "·", ipucunda "uyum dışı") - neden NS, bonolar ve kayıtlı günde önce / sonra:
  DİBS RV · Genel'in "Sıfır kupon eğrisi" bölümünde. Tablonun notunda RMSE'nin yanında **LOO RMSE** (uydurulan her kâğıt,
  eğri o olmadan yeniden uydurulunca - τ aynı - eğriden uzaklığı) ve uyum dışı bono sayısı; seri "05.10.33 · NS farkı",
  Paket 1 "NS seviye β0 ve eğim β1'e nötr", kotasyonda "Adil (NS)".
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
  basit). Eğri **sabit kuponlulara** uydurulur (masanın kararı, 18.11.2026; sayfanın kendi ASW uyumu da yalnızca "S"
  satırlarını alır): bonolar kuponluların eğrisinden çok pahalı işlem görür (kayıtlı günde 134 – 221 bp) ve uyumda ön ucu
  bükerdi; eğride fiyatlanır, ölçülür, izlenir ama eğriyi biçimlendirmez - pahalı / ucuzları kuponluların eğrisinin kısa
  ucuna göre. Yanında aynı nakit akışlarının **OIS uyumuyla** getirisi ve farkı (bp; ASW benzeri, sayfanın
  kendi ASW'si ve kendi pahalı / ucuzu - ASW'nin karesel uyumuna göre - yanında), kesit z (fark ÷ bugün uydurulan sabit
  kuponluların farklarının standart sapması - bonolar da ona göre ölçülür; z'nin geçmişi yokken de bir ölçü).
* *Carry + roll*, 1 hafta ve 1 ay (7 / 30 gün), bp (÷ DV01: sayfanın AM / AN birimi): **carry** = getiri sabitken ufuktaki
  fiyat + aradaki kupon − fonlanan kirli fiyat; fonlama satırın reposu, yoksa OIS uyumunun ufka kadarki faizi (sayfanın
  varsayılan "Bootstrap" patikası gibi), yoksa günlük bileşik TLREF. **Roll** = eğri yerinde kalırken (nakit akışları
  yeni vadelerinin eğri faiziyle, kâğıdın eğriye göre farkı sabit) fiyat − getiri sabitken fiyat. Ufuktan önce ödenen
  kupon yeniden yatırılmaz. Sinyalin carry'si paketin 1 haftalık carry + roll'u.
* *Paketler* (DİBS adil değeri sinyali; seri kâğıdın kendi farkı, "05.10.33 · NS farkı" - hedge paketlerindir), her bacak
  işlemi, nominali (mn TL) ve DV01'iyle ($ ve TL / bp), ana bacak 1.000 $ DV01:
  **Paket 1 · DİBS komşularıyla hedge'li** - kâğıt ve vadede iki komşusu, DİBS uyumunun seviye (β0) ve eğim (β1) faktörlerine nötr
  DV01 ağırlıklarıyla ("Sell 05.10.33 · Buy … · Buy …"): eğri kayar ya da dikleşirse paket yerinde kalır, kazanç kâğıdın
  eğriye dönmesinden. Kâğıdın DV01'i masanınki gibi (DİBS RV!AI: mod. süre × kirli fiyat, basit getiriden; geçmişi bileşik
  okunan kâğıtta ağırlıklar ona çevrilir). **Paket 2 · kâğıt + OIS, OIS'le hedge'li** - kâğıdın asset swap'ı, DİBS RV'nin kendi OIS hedge'i
  gibi (AJ: kâğıdın vadesine kadar bir OIS, aynı DV01) ama kote vadelerle: vadesini çevreleyen iki OIS vadesi, OIS DV01'i
  aralarında vadeye göre doğrusal, toplamı kâğıdınki (1:1); kâğıdı satan OIS receive, alan pay eder. Bu paket kâğıdın OIS'e
  göre farkıyla gider: NS farkının yanında bütün eğrinin DİBS − OIS farkını da taşır (Paket 1 taşımaz); sinyalin z'si ve
  beklenen hareketi NS farkınındır, carry + roll'u kendi bacaklarının (OIS'inki Carry & Roll'un vade motorundan).
* *Receive / pay için en iyi kâğıt:* puan = z × (1 aylık carry + roll) ÷ σ, σ kâğıdın 1 aylık getiri oynaklığı (son 60
  kapanışın günlük değişimleri × √21). z ile carry aynı yönü gösterdiğinde artı: **receive (al)** tarafında ucuz ve
  carry'si artı, **pay (sat)** tarafında pahalı ve carry'si eksi (açığa satış onu kazanır); carry'si z'sine ters olan
  kâğıt kendi tarafında eksi puanla sonda. z için kâğıdın tarihçede en az 120 günü gerekir.
* *Adil eğriden kotasyon:* sabit kuponlu herhangi bir DİBS (listeden ya da ISIN yazarak; listede olmayan kâğıt
  kataloğun kuponu ve vadesiyle) için valörüne göre NS **adil getirisi** (eğrinin nakit akışlarına verdiği kirli fiyatın
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
tur başına bir hit ve 2 – 3 kapanış: günde ~2.330 hit, ~4.700 – 7.000 nokta - **önce önbellekten beri** (24.11.2026)
yeni günler günde bir kez, sonra en çok saatte bir: **günde ~24 × 11 ≈ 260 hit**.
Canlıda ayrıca her ticker için bir referans isteği ve abonelik (24), `EUR1M` / `EUR3M`'in `FWD_SCALE`'i günde bir kez.
EURUSD bunun 13 serisidir (`quantopt.PAIRS`'ten çıkarılırsa 11 seri, günde ~1.070 hit). Eğri Adil Değeri yeni seri
istemez (OIS ve DİBS tarihçenin kendi serileri; DİBS RV motor iş parçacığında okunur).

**Açık kararlar:** OIS kuralı Excel'inki (3A'ya kadar tek ödeme, sonra üç ayda bir kupon) - quant paketinin FRA ailesi
(`quantfam._annuity`, `curve_df`) 1Y'ye kadar tek ödeme, sonra yıllık kupon varsayar; ikisi `quantcurve.SINGLE_MONTHS` /
`COUPON_MONTHS` ile tek yerde değiştirilebilir. τ'ların her tam hesapta son kapanışta aranıp pencereye sabit
tutulması, sınırları (τ1 ≥ en kısa vadenin yarısı, τ2 ≤ en uzun vade); DİBS eğrisinin yalnızca sabit kuponlulara
uydurulması (bonolar eğride ölçülür - masa 18.11.2026'da böyle karar verdi); Huber eşiği 2 sağlam σ, üç geçiş; `YLD_YTM_MID`'in kuralının sayfaya bakılarak seçilmesi (150 bp sınırı);
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
18 serisi ve 5 sabit seri, turda 23 hit (~46 nokta) - **önce önbellekten beri** (24.11.2026) yeni günleri günde bir
kez, sonra en çok saatte bir: günde ~23 × 11 ≈ 250 hit (önceden ~2.200). Sahte terminalde vadesi
geçmiş kontrat yalnız iki haneli yılla bilinir (en pahalı durum: tek haneli biçim boş döner, her seri iki istek);
terminal tek haneli biçimi tanırsa 72 hit eksik. 5 dakikalık barlar: ilk gün **80 istek = 80 hit** (iki kontratın
işlemleri, USDTRY'nin bid ve ask'i × 20 iş günü; dakikada 4, 20 dakikada), 8.160 bar; sonra **günde 4 istek** (biten
gün). VİOP'un hepsi ilk gün ~2.340 hit (bir kerelik doldurma), sonra günde ~255 (önceden ~2.210).

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

#### Carry + momentum (haftalık sıralama sepetleri)

Evrenin (yukarıda: *Quant evreni*) enstrümanları küme küme birbirine göre sıralanır; her kümenin **sepeti her hafta
yenilenir**: "en iyi üçünü AL, en kötü üçünü SAT". Her sepet **Sinyaller** girişinin **Carry + momentum** sekmesinde bir
kart, her bacağı Sinyaller listesinde kendi grubunda bir satırdır (aile sütununda sepetin adı), ör. `SAT USDJPY spot ·
1,2 mn USD · giriş 150,250 · hedef 149,900 · stop 151,800 · beklenen +2,1 bin USD · isabet %58 (87) · model: Carry +
momentum · G10 spot sepeti` (`tto/quantsira.py`).

| Sepet | Enstrümanlar | Sıralama (yalnız dengeleme kapanışına kadarki verilerle) | İşlem | Büyüklük |
|---|---|---|---|---|
| G10 spot | 7 paritenin para birimi, USD'ye karşı | z(carry: 3A forward'ın yıllık faiz farkı) + z(son 3 ayın getirisi, forward'la tutulan pozisyonun: carry dahil); z o kapanışta pariteler arasında | en iyi 3 long, en kötü 3 short - paritenin kendi yönüyle (JPY almak USDJPY SAT) | bacak başına eşit risk (USD tutarı ∝ 1 ÷ günlük σ, ortanca parite 1 mn USD), iki tarafın doları eşit: dolar-nötr |
| G10 vol | 7 paritenin 3A ATM straddle'ı | z(prim: 3A ATM ima − spotun son 63 günlük gerçekleşen vol'ü) + z(vol satanın momentumu: −ima'nın 3 aylık değişimi) | en pahalı 3'ünde vol sat, en ucuz 3'ünde vol al | 10.000 $ vega: vega-nötr |
| TRY OIS | 1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y | z(carry + roll ÷ oynaklık) + z(−getirinin 3 aylık değişimi: düşen faiz receive lehine) | en iyi 2 receive, en kötü 2 pay | 1.000 $ DV01: DV01-nötr |
| TRY OIS spread | evrenin spread'leri (DV01 1:1; listede ≤ 2Y önce) | paketin carry + roll ÷ oynaklığı + son 3 ayın hareketi, her biri kümedeki karesel ortalamasına bölünür (merkezlenmez: işaret paketin kendi yönü) | en güçlü 3, kendi yönünde (+ steepener, − flattener) | 1.000 $ DV01 |
| TRY OIS fly | evrenin fly'ları (50/50) | aynı | en güçlü 3, kendi yönünde (+ gövde pay / kanatlar receive) | 1.000 $ DV01 |
| DİBS | DİBS RV listesinin sabit kuponluları | z(carry + roll ÷ oynaklık) + z(ucuzluk: DİBS eğri uyumunun kalıntısının z'si) + z(−getirinin 3 aylık değişimi) | en iyi 3 AL, en kötü 3 SAT | 1.000 $ DV01: DV01-nötr |

**Ne zaman.** Her haftanın ilk kapanışında (pazartesi; pazartesi tatilse haftanın ilk iş günü - masanın tatil
takvimiyle) her küme o kapanışa kadarki kapanışlarla sıralanır, sepet bir sonraki dengelemenin kapanışına kadar
tutulur. Arada satırlar kurulduğu gibi kalır (sıra, büyüklük); kart sepetin **şimdiye kadarki K/Z'sini** (canlı) ve
**sonraki dengeleme tarihini** yazar. Pazartesi gün içinde geçen haftanın sepeti durur, "sonraki dengeleme: bugün
kapanışı". **Kapı yok:** sepetin bacakları her zaman satırdır - carry'si aleyhte ya da beklenen kârı tamponu
karşılamayan bacak "düşük güven" olmaz (kapılar kartta ✓ / ✗ yazar). Bir enstrüman dengelemede sepete girince yeni
satırdır: kayda ve alarma düşer. Satırın skoru **sıra**dır: 2 bir tarafın en güçlüsü, 1 en zayıfı; 1'in altı sepette
değil (giriş eşiği 1). Bileşik puan ve güç bu sıradan.

**Beklenen K/Z, hedef, stop** (*Seviyeler*: sepet düzeyinde ayarlı). Sepetin riski: haftanın önceden bilinen σ'sı
(sepetin ağırlıklarıyla kuruluş kapanışına kadarki 60 günlük K/Z'si × √5, çeşitlendirilmiş). Yürüyen testin her haftası
bir işlemdir: hafta içindeki her kapanışta sepetin K/Z'si (carry + roll günlere düşen payıyla) o riskin katı olarak;
liste grubu başına (TRY OIS'in üç sepeti birlikte) her ay o ay başlamadan biten haftalarla **stop k** ve **hedef m**
seçilir (beklenen K/Z en yüksek, m ÷ k ≥ 1, en az 30 hafta). Sepetin hedefi m × riski, stopu k × riski; **her bacağa
aynı katlar kendi haftalık σ'sıyla**, beklenen K/Z sepetinkinin (kaydın haftalık ortalaması × sepetin riski) bacağın σ'sı
oranında payı; kart ve her bacak sepetin ödül / riskini (m ÷ k), isabetini ve hafta sayısını gösterir. En iyi
seviyelerle bile zarar ettiren sepetin bütün bacakları "düşük güven". Kalibrasyon yoksa eski kural: hedef geri testin
ortalama haftası, stop **2σ** aleyhte. Satırda giriş / hedef / stop enstrümanın kendi fiyatıyla (FX'te paritenin kuru),
beklenen para (FX kartında 1 mn baz döviz başına, satırın cümlesinde bacağın kendi büyüklüğüyle); tutma bir hafta.

**Carry + roll geçmiş kapanışlarda.** Carry & Roll motorunun ve DİBS uyumunun carry'si yalnız bugünündür; sepet ise
geçmiş bir kapanışta kurulur (geri testte ve hafta boyunca: çarşamba hesabı pazartesinin sepetini yeniden kurar). Bu
yüzden sıralama her kapanışın kendi eğrisini okur: TRY OIS vadesinde (faiz − haftanın TLREF'i) × 7/365 ÷ annuity
(çalışma kitabının takvimi) + eğride bir hafta yuvarlanma (aylara göre doğrusal, TLREF 0'da) - alıcının, vadenin DV01'i
cinsinden bp; DİBS'te (getiri − haftanın TLREF'i) × 7/365 ÷ değiştirilmiş süre + o kapanışın uydurulmuş eğrisinde
yuvarlanma (kâğıtların getirisi − kalıntısı, vadeye göre doğrusal). Haftanın TLREF'i o kapanışın toplantı patikasından
(PPK Fiyatlama Geçmişi): hafta içinde bir karar varsa ertesi günden fiyatlanan adım kadar kayar - motorun değişken
bacağı da patikayla bileşiklenir. Satır kartının "carry + roll"u motorunkidir (DİBS'te uyumunki), yoksa bu.

**Geri test** (yürüyen pencere, ileriye bakış yok). Tarihçenin her dengelemesinde sepet yalnız o kapanışa kadarki
verilerle kurulur ve bir sonraki dengelemeye kadar tutulur: iki yıllık tarihçe, momentumun gerektirdiği ilk üç ay
dışında (~90 hafta; DİBS eğri uyumunun kalıntı penceresinde, ~45 hafta). K/Z parayla: bacakların hareketi; faiz
bacağında dengelemenin carry + roll'u tutulan iş günleri kadar; FX'te forward primi dahil (paritenin forward
pozisyonunun getirisi); straddle'da teta ve gama, her gün delta hedge'li (vega ÷ (2σ τ) × (r² − σ² ÷ 252), τ 3 ay).
Riski haftanın önceden bilinen σ'sı. Sepet başına ve ailede: hafta, isabet, Sharpe (risk birimli haftalık K/Z'nin
ortalaması ÷ σ × √52), en büyük düşüş. **Sinyaller'in geri test tablosu** aileyi bu haftalık geri testle verir, türleri
sepetler (diğer aileler 10 iş gününde bir yeniden kurulur; bu ailenin takvimi haftalık, yeniden kurmalarda çalışmaz:
`quantuniv.own_backtests`); satırın "Geri test" sütunu ve "isabet %58 (87)"si sepetinkidir.

**Sayfa.** Sinyaller girişinin dördüncü sekmesi: ailenin satırları (satıra tıklayınca kart ve seri), her sepetin
**kartı** (bacaklar, büyüklükleri, kuruluştaki giriş ve şimdiki seviye, şimdiye kadarki K/Z, haftalık beklenen ve stop,
geri test, sonraki dengeleme, net dolar / vega / DV01) ve **sıralama tablosu** (enstrüman, carry, carry ÷ vol,
momentum, DİBS'te ucuzluk z'si, bileşik, sıra, sepette mi, büyüklük, sıra skoru), sepet başına **geri test** tablosu;
her tablonun başlığının altında masanın diliyle cümlesi. **Bloomberg:** yeni istek yok (G10 serileri evrenin, gerisi
tarihçenin). **Tam hesaba eklediği süre** (ölçüldü, masanın makinesinde, kayıtlı veri modunda iki yıllık sentetik
tarihçeyle: paketin serileri, 7 G10 paritesi, OIS eğrisi, DİBS RV listesinin kâğıtları - altı sepet de kurulu, ~80
hafta): tam hesap ~6,3 sn'den ~6,6 sn'ye; ailenin kendi süresi ~0,4 sn (*Hesap durumu* tablosunda "sira").

**Sınırlar.** DİBS'in ucuzluğu eğri uyumunun kalıntı geçmişinden: uyumun τ'ları bugünün kapanışında aranır, her günün
β'ları o günün getirileriyle (kalıntının geçmişe dönük şekli bu kadar bugüne bağlı); DİBS evreni bugünün listesidir
(geri testte vadesi dolmuş kâğıt yok). Sinyal kaydı her ailede olduğu gibi satırı hedef / stop / 20 iş gününe kadar
izler; sepetin kendi sonucu haftalık geri testidir.

#### DİBS switch

`tto/quantdibssw.py`, Faiz girişinin **DİBS switch** sekmesi (`#/quant-dibssw`, Eğri Adil Değeri'nin yanında: DİBS adil
değeri'nin satırları oradadır). Carry + momentum'un DİBS'e uyarlanmışı, sepet yerine **switch**: haftada bir trading
listesinin kâğıtları aylık carry + roll'larına ve son bir ayın getiri hareketine göre sıralanır, iyisi süresi benzer
kötüsüne karşı **DV01 dengeli** alınır. Her switch Sinyaller listesinde **DİBS** grubunda bir satırdır:
`AL TRT150328T24 / SAT TRT130928T38 · switch · 210 mn / 205 mn · C+R +18,0 bp/ay · 1A momentum lehte · hedef +12,0 bp ·
stop -8,0 bp · beklenen +504 bin TL · isabet %56 (142)`.

* **Evren**: trading listesinin (DİBS RV!A5:A54; tarihçenin `dibs` serileri, Bloomberg `YLD_YTM_MID`, ~bir yıllık
  kapanış - **yeni Bloomberg isteği yok**) **sabit kuponluları ("S") ve bonoları ("B")**. Dışarıda, her biri nedeniyle
  sayfanın "Evrenin dışında kalan kâğıtlar" tablosunda: **TLREF'e endeksliler ("T") ve FRN'ler ("F")** - kuponu TLREF'le
  değişir, tarihçe fiyatını tutar: sabit kuponluya karşı getiri farkı switch seviyesi olmaz -, **TÜFE'ye endeksliler
  ("E")** - reel getiri, nominal getiriyle karşılaştırılmaz -, vadesine 37 günden az kalanlar, kuponu / vadesi
  bilinmeyenler. Kâğıt ISIN'iyle tutulur: DİBS RV'de satırı kayınca hiçbir şey kaymaz.
* **Getiri** kâğıdın **BIST basit getirisi** (DİBS RV!S; sayfanın SWITCH / PAIR tablosunun "Getiri farkı (basit)"
  gibi): tarihçe bileşik okunuyorsa (`quantcurve.detect_convention`) basite çevrilir (bonoda fiyatından). Şimdi:
  DİBS RV'nin canlı basit getirisi, yoksa bileşiği çevrilir, yoksa son kapanış.
* **Ne zaman**: Carry + momentum gibi her pazartesi kapanışında (pazartesi tatilse haftanın ilk iş günü) yalnız o
  kapanışa kadarki verilerle; switch'ler bir sonraki dengelemenin kapanışına kadar tutulur, arada satırlar kurulduğu
  gibi kalır, kart sonraki dengelemeyi yazar.
* **Skor** (her parça o kapanıştaki kâğıtlar arasında z): **carry + roll, bir ay** (kâğıdın DV01'i cinsinden bp,
  tutan için): carry = (getiri − fonlama) × 30/365 ÷ modifiye süre, fonlama o kapanışın 1 aylık OIS'i (TLREF 0'da;
  quantcurve'ün repo'suz satırdaki yolu); roll = o kapanışın sabit kuponlulara uydurulan eğrisinde (Nelson-Siegel, τ 1
  / 2 / 4 yılın en iyisi, en kısa ve en uzun kâğıdın ötesinde düz; bonolar uydurmaya girmez, eğride okunur) bir ay
  kısalmanın getiri düşüşü. Bugünün satırı **DİBS RV'nin kendi C+R'ını** yazar (AO, J2 ufkuna göre aylık; yoksa
  tarihçeninkini). **Momentum, bir ay**: −(getiri − 21 kapanış önceki), bp - düşen getiri tutanın lehine. Bileşik = z(C+R)
  + z(momentum).
* **Switch'ler**: modifiye süreleri **en çok 1,5 kat** farklı (uzununki kısanınkinin en çok 1,5 katı: göreli değer
  işlemi, eğri işlemi değil) ve bileşikleri **en az 1** ayrışan her çift; en geniş fark önce, **bir kâğıt bir kez**,
  haftada **en çok üç** switch. AL bileşiği yüksek, SAT düşük olan.
* **Büyüklük**: AL bacağı masanın DV01 ayarı (**1.000 $**, OIS_MAIN!F2; OIS_MAIN!D2'nin USDTRY'siyle TL), nominali
  masanın kâğıt yuvarlamasıyla (DİBS RV!AK gibi: OIS_MAIN!H2 "Yuvarlama TL", 5 mn TL); SAT bacağı aynı DV01'in nominali
  (DİBS RV!AI'nin DV01'i, basit getiriden), aynı yuvarlamayla - yuvarlamanın bıraktığı DV01 farkı kartta (bu
  nominallerde %1-2).
* **Seviye**: switch'in getiri farkı **AL − SAT** (bp; DİBS RV'nin switch tablosundaki "Getiri farkı"): switch fark
  daralınca kazanır. Hedef ve stop bu farkın **işlem yönündeki hareketi** olarak yazılır ("hedef +12,0 bp": 12 bp
  lehte). Çiftin izleyicisi tek yönlüdür - kısa vadeli kâğıt önce, serisi getiri(kısa) − getiri(uzun) - satırın yönü
  haftanın sıralamasının seçtiği taraf; listedeki giriş / hedef / stop o serinin seviyeleridir.
* **Geri test** (yürüyen, ileriye bakış yok): tarihçenin her dengelemesinde switch'ler o kapanışa kadarki verilerle
  kurulur, bir sonraki dengelemenin kapanışına kadar tutulur; her kapanışta K/Z = getiri farkının düşüşü + C+R'ın günlük
  payı (aylık ÷ 21), AL bacağının DV01'iyle bp ve TL, ve **switch'in haftalık σ'sı** cinsinden (girişten önceki 60
  günün farkın günlük değişimleri × √5). Her switch bir işlem (`quantbt` biçimi ve **yolu**: `quantlevels`'ın
  sözleşmesi); kayıt: switch, isabet, ortalama σ / bp / TL, Sharpe, en büyük düşüş. Sinyaller'in geri test tablosunda
  aile kendi haftalık testiyle (`quantuniv.own_backtests`).
* **Seviyeler** (`tto/quantlevels.py`): bu işlemler üzerinde ay ay ayarlanır (en az 30 işlem): switch'in haftalık
  σ'sında stop k ve hedef m, ödül / risk ≥ 1, carry içinde; aile kitabını tablosuna koyar, `tto.quant` satırlara uygular
  (`make_signal`): satır ve kart katları, isabeti ve beklentiyi yazar. Bu seviyelerle bile **zarar ettiren kayıt satırı
  "düşük güven" yapar**. Kalibrasyon yokken: hedef 1,5σ, stop 1σ, beklenen haftanın C+R'ı (kartta söylenir).
* **İzleyiciler**: haftanın sıralamasında süre bandındaki **her çiftin** bir izleyicisi var - haftanın switch'ine giren
  çift yeni satırdır (kayda ve alarma düşer), çıkan düşer. Skor **sıra**: 2 haftanın en geniş farkı … 1 en darı, 1'in
  altı alınmayan çift. **Kapı yok** (Carry + momentum'un bacakları gibi): yalnız seviyelerin kaydı satırı "düşük güven"
  yapar.
* **Sayfa**: ailenin satırları ve seçilenin grafiği (serisi çiftin getiri farkı, altında sıra gün gün); **bu haftanın
  switch'leri** (nominaller, DV01'ler, süreler, skor farkı, C+R - DİBS RV'ninki ve tarihçeninki -, momentum, getiri
  farkı kuruluşta ve şimdi, o zamandan beri hareket, haftalık σ, hedef / stop bp, beklenen TL, ödül / risk, isabet);
  **sıralama** (her kâğıdın getirisi, fonlaması, carry, roll, C+R, DİBS RV'nin C+R'ı, momentum, z'ler, bileşik,
  switch'teki yeri); **evrenin dışında kalanlar** ve nedeni; **geri test** (kayıt ve son 26 hafta). Kayıtlı veri modunda
  DİBS geçmişi bir ay: sıralama kurulmaz, sayfa nedenini yazar.
* **Süre**: tam hesaba eklenen ~0,1 sn (sentetik 9 kâğıt × 300 kapanış: 61 dengeleme, ~150 switch).

#### Konsensüs

`tto/quantcons.py`. Aynı enstrümanda **üç ya da daha çok ailenin güvenli satırı aynı yöndeyse** Sinyaller listesinin en
üstünde (**Konsensüs** grubu, diğerlerinden önce) tek satır: `AL USDJPY spot · 3 aile (Makine öğrenmesi, Opsiyon → spot,
Trend) · birleşik 1,2 mn USD · hedef 152,630 · stop 148,350 (seviyeler: Makine öğrenmesi, en iyi örneklem dışı kayıt) ·
aile isabetleri %58 / %57 / %55`.

* **Satırların bir görünüşüdür**: listenin canlı satırlarından (bir kapının tuttuğu "düşük güven" satırı sayılmaz) liste
  her yapıldığında kurulur; onlar gelince gelir, gidince gider. **Kendi kaydı ve alarmı yok** (aileler kendi satırlarıyla
  bildirir), geri testte aile değildir; abonelikte grup olarak çıkmaz.
* **Aynı enstrüman**: satırlar işledikleri şeyle karşılaştırılır - sinyalin `instrument` ve `asset`'i ve bacakları
  (anahtarları, birbirlerine göre yönleri): FX satırı aynı paritenin aynı enstrümanıyla (spot forward'la buluşmaz), faiz
  satırı aynı paketle (2Y outright 1Y/2Y spread'le buluşmaz); enstrümanlar arası hiç. Yön enstrümanın (anahtara göre)
  ilk bacağının tarafı. En az üç **farklı** aile bir tarafta ve **öbür tarafta hiçbiri**: ters yönde bir aile (ya da iki
  yönde de satırı olan bir aile) varsa konsensüs yok.
* **Aileler** en iyi kayıttan başlayarak adlanır; **seviyeler** aralarında en iyi **örneklem dışı** kayda sahip ailenin
  ayarlı seviyeleri (`quantlevels`: örneklem dışı önce, sonra işlem başına beklenti, sonra isabet) - giriş, hedef, stop o
  ailenin satırındaki gibi, satır kimin olduğunu yazar; **büyüklük** ailelerin büyüklüklerinin **medyanı** (her biri
  enstrümanın masa biriminde: 1 mn baz döviz, 1.000 $ DV01 …) - ailelerden birinin kendi alacağı bir büyüklük; toplamları
  aynı enstrümanda üç satırın riskini üst üste koyardı, her ailenin kendi satırı listede duruyor. Satır her ailenin
  isabetini (seviyelerinin kaydı) aynı sırayla yazar. Karta tıklayınca seviyeleri kullanılan ailenin kartı açılır, üstünde
  konsensüsün cümlesi; büyüklüğe göre bacakların DV01 / nominali ve faizde TL'si ölçeklenir (FX'te para 1 mn baz döviz
  başına kalır).
* Ailenin süzgeci (Sinyaller'in *Aile* seçimi, kutu) içinde olduğu konsensüsü de gösterir; grubun düğmesi
  `#quant-group-konsensus`.

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
| Diğer `BDP` alanları ve override'lı `BDP` | `ReferenceDataRequest`; **günde bir kez** (aşağıda **Önce önbellek**) |
| `BDH` | `HistoricalDataRequest` (`Days`, `Fill`, `Per`, `Dates`, `Sort` seçenekleri) |
| `BDS` | toplu alan için `ReferenceDataRequest` |
| `BInterpol` | doğrusal interpolasyon (Excel'deki değerlerle doğrulandı) |
| `BFXFORWARD` | **API karşılığı yok** → `#N/A BFXFORWARD` (aşağıya bakın); altın forward'ı bunun yerine altın swap faizinden (`XAUSR…`) hesaplanır |
| `RtGet` (Refinitiv) | Bloomberg fonksiyonu değil → `#N/A RTGET` |
| — (formül dışı) gün içi barlar | `IntradayBarRequest`: istek başına tek menkul, **1 hit** (aşağıda **Gün içi barlar**) |

Bağlantı **Desktop API** içindir (terminalin açık olduğu makinede `localhost:8194`); B-PIPE / SAPI gibi sunucu
ürünlerinin yetkilendirme adımı yazılmadı. Abonelikle gelmeyen fiyat alanları (aboneliği başarısız olan, alanı
reddeden ya da sessiz kalan) sorguyla istenir: değeri olan **en çok 15 dakikada bir** (`--price-poll`, 900 sn; yanıt
değişse de), yanıt aynı kaldıkça aralık ikiye katlanarak 60 dakikaya kadar uzar; **hiç değeri olmayan alan 3 saatte
bir**; yalnızca Bloomberg sorgu saatlerinde (aşağıda **Önce önbellek**). Bloomberg'in tanımadığı bir ticker
(`#N/A Invalid Security`) o gün bir daha sorulmaz, aboneliği de açılmaz; ertesi gün bir kez yeniden sorulur (dün
olmayan bir vade bugün var olabilir). Böylece Borsa Swap sayfasının kotası olmayan yüzlerce vadesi ne
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
isteği sayısı sayılır; günlük bütçe, `--max-hits` ve Bloomberg'in kendi limiti aşağıda (**Önce önbellek**). Bağlantı
koparsa otomatik yeniden bağlanılır.

### Önce önbellek: Bloomberg'in günlük limiti (24.11.2026)

24.11.2026'da 14:27'de ofisteki terminal `category = "LIMIT" message = "Daily capacity reached."` cevabını verdi;
dashboard o güne kadar 195.148 istek saymıştı. Masa: "Bloomberg limiti doldu. Bunu nasıl halledebiliriz bir daha
yaşanmaması için" - "Zaten çektiklerini cache atıp daha fazla çekmemesi gerekliydi". Nedeni (çalışma kitaplarının
formülleri ve sahte terminalde ölçülen bir günle doğrulandı): DİBS RV'nin gizli `CG` / `CK` / `CL` sütunları
(`LAST_TRADE_DATE`, `CHG_NET_5D`, `CHG_NET_1M`) ve DİBS Trading / Tüm Kâğıtlar'ın `LAST_TRADE_DATE`'leri **dakikada
bir** yeniden soruluyordu; akmayan ve cevabı değişen kotalar 2 dakikada bir; 30 dakikalık sınıf, 6 saatlik BDH'ler
(her günün aralığı dününkünün yanında yeni bir anahtar), tarihçenin 15 dakikalık turları, kuyruk taşınca bütün kotaların yeniden istenmesi, yeniden başlatmada her şeyin yeniden istenmesi,
dünkü tarihli anahtarların (aralık sonu, valör override'ı) yenilenmeye devam etmesi; `--max-hits` (400.000)
Bloomberg'in gerçek limitinin üstündeydi, Bloomberg'in kendi LIMIT cevabını ise yalnızca gün içi bar isteği
anlıyordu. Şimdi:

* **Bugün cevabı gelen bir değer bugün bir daha istenmez** - alanı ne olursa olsun. Her cevap (kotalar da) bellekte
  ve veritabanında (`bbg_answers`, 30 sn'de bir) saklanır; **aynı gün yeniden başlatma hiçbir şeyi yeniden istemez**
  (kotaları aboneliği ücretsiz günceller); yardımcı süreç yeniden başlarsa elindeki bütün cevaplar ona verilir.
  Yalnızca bir sayfanın hâlâ okuduğu değer ertesi gün bir kez yeniden istenir (dünkü aralıklar, listeden çıkan bir
  kâğıt hiç).
* **Gün içinde değişen akıştan gelir:** DİBS RV'nin 5 gün / 1 ay değişimi (`CK` / `CL`) = sabahki cevap + (akan son
  fiyat − cevap anındaki son fiyat) - Bloomberg'in değişimi son fiyat eksi N gün önceki kapanıştır, o kapanış gün
  içinde değişmez (kayıtlı dosyada her kâğıt için `CH − CK` üç ondalıklı temiz bir fiyat: değişim akan son fiyattan
  ölçülüyor); son işlem tarihi (`CG`) akışta bir işlem görülünce bugün (son fiyat değişir ya da günün hacmi artar);
  aralık en düşük / en yüksek (`CM:CP`) günün akan en düşük / en yükseğiyle; bugünü içeren BDH'nin bugünkü noktası
  menkulün akan fiyatından. Akış yoksa saatte bir.
* **Akmayan kota en çok 15 dakikada bir**, değeri olmayan 3 saatte bir sorulur (yanıtı değişse de; önceden 2
  dakikada bir). Diğer bütün alanlar (`DAYS_TO_MTY`, `SETTLE_DT`, `INT_ACC`, sabit alanlar …) günde bir kez.
* **Bloomberg sorgu saatleri:** masanın günlerinde (hafta içi, Motor'daki TRY tatil listesinde olmayan günler)
  **08:00–19:00** (yöneticiler İzleme · Alarmlar → Masa alarmları → Ayarlar'dan değiştirir: "Bloomberg sorgu
  başlangıcı / bitişi"). Dışında, hafta sonu ve tatilde **hiçbir şey yeniden sorulmaz**: gece açık unutulan dashboard
  bir şey harcamaz; abonelikler akmaya devam eder, sayfanın hiç almadığı ilk değer yine istenir. Tarihçe de bu
  saatlerde güncellenir ("Şimdi güncelle" her saatte).
* **Günlük bütçe** (`--daily-budget`, varsayılan 100.000; `TTO_BBG_BUDGET`): **%70'ten sonra** yalnızca sayfaların
  hiç almadığı ilk değerler ve kullanıcının Hesapla isteği gider (yenileme, kota sorgusu, tarihçe, bar yok); **%100'de
  hiçbir yeni istek gitmez**, ilk değer de ertesi güne bekler. `--max-hits` (400.000) mutlak sınır olarak kalır.
* **Bloomberg'in kendi limiti:** herhangi bir isteğe `LIMIT` / `DAILY_CAPACITY_REACHED` cevabı gelince o gün **hiçbir
  istek gönderilmez**; sayfalardaki son değerler kalır (`#N/A` olmaz), abonelikler akar; durum penceresi ve rozet
  "**Bloomberg günlük limiti doldu – yarın yeniden**" der. Gün değiştikten bir saat sonra tek bir deneme isteği (bir
  menkul, bir alan) gider; Bloomberg hâlâ limit derse saatte bir yeniden denenir. Yeniden başlatmada da hatırlanır.
* **Nereye gittiği görünür:** rozete tıklayınca açılan pencere bugünkü isteği bütçenin yüzdesiyle gösterir (%70'te
  uyarır; yöneticilere günde bir kez bildirim), türe göre dağılımını (ilk cevap, akmayan kota, sabit / günlük alanlar,
  saatlik, tarihçe, Hesapla, kuyruk onarımı, gün içi bar, limit denemesi), en çok isteyen 10 sayfayı ve 10 alanı
  (`/api/market/usage`), akmayan kotaların ve akıştan güncellenen alanların sayısını.
* **Kuyruk taşınca** yalnızca taşmadan önceki 10 dakikada tick'i gelip sonra gelmeyen aboneliklerin değerleri yeniden
  istenir (önceden bütün kotalar), günde en çok 2.000.

**Tarihçe** (gün sonu matrisi, PPK fiyatlama geçmişi, quant serileri) için ayrıca `HistoricalDataRequest`
gönderilir: ilk açılışta ~120 ticker için bir yıllık günlük kapanış (alan başına 50 ticker'lık isteklerle; quant
paketinin serileri iki yıl, turda 40'ar). Tur 15 dakikada birdir ama her serinin son kapanışından sonrası **günde bir
kez** istenir (dünkü kesin kapanış için), sonra serinin bugünkü noktası bir sayfanın aldığı canlı fiyatından gelir
(istek yok), canlı fiyatı yoksa **en çok saatte bir** yeniden sorulur (önceden her turda; saat, serinin kaydıyla
saklanır: bir saat içinde yeniden başlatma sormaz). Bir serinin tüm aralığı günde en çok bir kez istenir;
Bloomberg'in geçmişi kısaysa verdiği en eski gün saklanır (`hist.fetch`) ve o aralık bir daha istenmez. Bunlar da
günlük istek sayacına yazılır: seri başına günde en çok 11 (08:00–19:00); sahte terminalle ölçülen bir gün
`tests/test_quant.py`'de. Geçmişi hiç olmayan bir ticker günde bir kez sorulur; "Şimdi güncelle" hemen yeniden dener.
(FX vol sayfalarının tarihçesi `tto/fx.py`'nin kendi kuralıyla gelir: aşağıda.)

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
  kapanır, yardımcı ölürse yeniden başlatılır ve dashboard'un elindeki bütün cevaplar ona verilir: yalnızca cevabı
  henüz gelmemiş olanlar istenir (günlük istek sayacı kaldığı yerden sürer; önceden her şey yeniden istenirdi). Art
  arda 5 kez kısa sürede ölürse yeniden başlatılmaz ve rozet bunu söyler. Açılışta
  konsolda `Veri: Bloomberg canlı · oturum ayrı bir yardımcı süreçte` yazar; rozetin ipucunda da görünür.
* Yardımcı süreç başlatılamazsa (ya da `--bbg-inprocess` verilirse) oturum eskisi gibi dashboard'un sürecinde açılır;
  bu durumda okuyucuya öncelik verilir (yorumlayıcının iş parçacığı değiştirme aralığı 5 ms → 1 ms), abonelikler
  saniyede bir güncellemeye seyreltilir (`interval=1`) ve tarihçe hesabı her günün ardından bir o kadar dinlenir.
* Olay kuyruğu 10.000'den 100.000'e çıkarıldı (`--bbg-queue`); bir tick mümkün olan en az `blpapi` çağrısıyla okunur.
* Bloomberg kuyruk hakkında ne derse sayılır ve gösterilir: kuyruk dolarken rozet sarıya döner ("CANLI · Bloomberg
  kuyruğu doluyor"); olay düşerse ipucunda `KUYRUK TAŞTI: … olay düştü` yazar ve etkilenen değerler sorguyla
  yeniden istenir (düşen bir tick ekranda eski fiyat bırakmasın diye; Bloomberg'in adını verdiği abonelikler, adını
  vermediyse taşmadan önceki 10 dakikada tick'i gelip sonra gelmeyenler; günde en çok 2.000 değer, Bloomberg sorgu
  saatlerinde, veri limitini korumak için).

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
  120, 240 sn). Her yeni sürece dashboard'un elindeki cevaplar verilir (yalnızca cevabı gelmemiş olanları ister); bu
  sınırlar yine de bir döngüyü önler. Sınır dolunca (ya da piyasa saati dışında) yeniden başlatılmaz: rozet bayat kalır,
  pencere nedenini ve "dashboard'u yeniden başlatın"ı yazar. Kapanan (ölen) sürecin ayrı sınırı aynen geçerlidir:
  art arda 5 kısa ömürlü süreçten sonra durur.
* Piyasa saatlerini ve "kaç saniye tick gelmezse bayat"ı yöneticiler İzleme · Alarmlar → Masa alarmları → Ayarlar'dan
  değiştirir; veri piyasa saatinde 3 dakika bayat kalırsa herkese masa alarmı çalar (İzleme · Alarmlar → Masa alarmları).

### Veritabanı: tutarlı yazma, açılış denetimi, günlük yedek

Her şey tek dosyada: `data/tto.db` (SQLite, WAL; ağ sürücüsünde DELETE - aşağıda).

* **Bilgisayarın kendi diskinde çalıştırın.** Dashboard'u ve `data` klasörünü bilgisayarın kendi diskine (C:, D:)
  kurun; ağdaki bir paylaşıma (eşlenmiş sürücü ya da `\\sunucu\paylaşım\…`) değil. SQLite'ın WAL günlüğü veritabanını
  açan bütün süreçlerin aynı bilgisayarda olmasını ister (yanındaki `-shm` dosyası ortak bellektir): ağ sürücüsünde
  çalışmaz; iki bilgisayar aynı dosyayı açarsa dosya bozulabilir. 24.11.2026'da olan buydu (masa: "Kendi limitim
  bitince arkadaştan açtım"): dashboard aynı ağ klasöründen bir arkadaşın bilgisayarında da açıldı, durum penceresi
  `tarihçe · DatabaseError: database disk image is malformed` dedi. Veri klasörü bir ağ sürücüsündeyse dashboard yine
  açılır, ama:
  * veritabanı o açılışta WAL yerine **DELETE** günlük kipiyle çalışır (WAL orada çalışamaz); klasör yerel diske
    taşınınca yine WAL;
  * konsolda ünlemlerle çevrili bir **UYARI** satırı ve günlükte bir satır çıkar; rozetin penceresinde kırmızı satır:
    "Veri klasörü bir ağ sürücüsünde: veritabanı bozulabilir - dashboard'u bilgisayarın kendi diskine kurun; yedeğin
    ikinci kopyası ağda durabilir".

  Ağdaki paylaşım **yedeğin ikinci kopyası** için uygundur (*Araçlar → Yedekleme*, ikinci kopya klasörü). Ağ sürücüsü
  Windows'ta tanınır: `\\sunucu\paylaşım` yolu ya da Windows'un "ağ sürücüsü" dediği bir harf.
* **Bir veri klasörünü tek dashboard kullanır** (`data\tto.lock`). Dashboard açılırken - veritabanını açmadan önce -
  veri klasörüne bir kilit dosyası yazar: hangi bilgisayar, kullanıcı, süreç, port, ne zamandan beri; her 15 sn'de bir
  "buradayım" işaretini yeniler. Dosya "yalnızca yoksa yarat" diye açılır: ağdaki paylaşımda da çalışır.
  * Aynı klasörü başka bir dashboard kullanırken - bu bilgisayarda ya da başka bir bilgisayarda - ikinci dashboard
    **başlamaz**: konsolda hangi bilgisayarda, kimin, ne zamandan beri açık olduğunu yazar (bu bilgisayardaysa açık
    olanın adresini: `http://localhost:1057`) ve kapanır (çıkış kodu 3; `run.bat`'ın penceresi mesajla bekler).
  * Dashboard penceresinde Ctrl+C ile kapanınca kilit kalkar. Pencere kapatılarak, çökerek ya da bilgisayar kapanarak
    kalan eski kilidi bir sonraki açılış kendisi devralır (konsolda ve günlükte "eski kilidi devralındı" satırı): aynı
    bilgisayarda hemen (o süreç artık yok), başka bir bilgisayardan açılınca kilidin 35 sn boyunca işaret vermediğini
    gördükten sonra - iki bilgisayarın saati farklı olabilir: saate değil işaretin kıpırdamasına bakılır.
  * Kilidin işareti bir dakika yazılamazsa (ağ klasörüne ulaşılamadı, bilgisayar uykuya daldı) başka bir dashboard
    kilidi devralabilir; eski dashboard bunu bir sonraki işarette görür ve **kendini kapatır** (iki dashboard aynı
    dosyaya yazmasın diye; konsolda ve günlükte nedeni).
  * `yedekten-don` ve `kurtar` da dashboard açıkken çalışmaz (aynı bilgiyle durur); çalışırken kilidi onlar tutar.
  * Rozetin penceresi kilidi gösterir: "Tek dashboard kilidi: bu dashboard tutuyor · bilgisayar · açılışı …" (yazılamıyor
    ya da başkasına geçtiyse kırmızı).
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
`tto.db.onceki-YYYYAAGG-SSDDss` adıyla (WAL ya da günlük dosyalarıyla birlikte) taşınır. Dashboard açıkken komut
çalışmaz: veri klasörünün kilidini görür, nerede açık olduğunu söyler ve hiçbir şeyi değiştirmeden durur. Yedeğin
alındığı andan sonraki girişler (işlemler, chat, RET …) geri dönülen veritabanında yoktur - bozuk dosyada okunabilenler
`kurtar` ile geri gelir (hemen aşağıda).

#### Veritabanı bozulursa

Belirtisi: rozetin penceresinde "Veritabanı denetimi: BAŞARISIZ", açılışta konsolda `UYARI: VERİTABANI DENETİMİ
BAŞARISIZ`, ya da bir tabloda `database disk image is malformed`. Yapılacak: en son yedeğe dönün, sonra bozuk dosyada
okunabilen ne varsa geri alın. Anaconda Prompt'ta, dashboard'un klasöründe:

1. **Dashboard'u her yerde kapatın** - her bilgisayarda penceresinde Ctrl+C. Bir yerde açıksa aşağıdaki komutlar
   çalışmaz, nerede açık olduğunu söyler.
2. `python -m tto yedekten-don` - yedekleri listeler (en yenisi önce).
3. `python -m tto yedekten-don tto-YYYY-AA-GG.db` - en son yedeğe döner. Bozuk dosya silinmez: yanında
   `data\tto.db.onceki-YYYYAAGG-SSDDss` adıyla durur (komut adını ve sonraki adımı yazar).
4. `python -m tto kurtar data\tto.db.onceki-YYYYAAGG-SSDDss --dene` - bozuk dosyadan neyin geri geleceğini söyler,
   hiçbir şey yazmaz (`python -m tto kurtar` tek başına saklanan bozuk dosyaları listeler; yalnızca adı da yeter).
5. `python -m tto kurtar data\tto.db.onceki-YYYYAAGG-SSDDss` - geri getirir.
6. Dashboard'u açın (`run.bat`).

```bash
python -m tto yedekten-don                                      # yedekler, en yenisi önce
python -m tto yedekten-don tto-2026-11-23.db                    # en son yedeğe dön (bozuk dosya yanında kalır)
python -m tto kurtar                                            # yedekten dönülürken saklanan bozuk dosyalar
python -m tto kurtar data\tto.db.onceki-20261124-101500 --dene  # neyin geri geleceği - hiçbir şey yazmaz
python -m tto kurtar data\tto.db.onceki-20261124-101500         # geri getir
```

`kurtar` ne yapar:

* **Okur.** Bozuk dosyanın her tablosunu SQLite'ın okuyabildiği kadar okur: bozuk bir sayfaya gelince satır satır o
  noktaya kadar, sonra onu atlayıp ötesini. Okunamayan satırları tabloların dizinlerinden sayar ve şimdiki
  veritabanında (yedekte) olup olmadıklarını söyler. Değerleri bozuk bir satırı (boş olamayacak alan boş, sayının
  yerinde yazı, okunamayan JSON, tarih olmayan tarih) almaz. Bozuk dosyaya dokunmaz: bir kopyasını okur (yanındaki
  `-wal` / `-journal` dosyasıyla; onunla okunamıyorsa onsuz).
* **Ekler, üzerine yazmaz.** Şimdiki veritabanında (yedekten dönüldüyse yedek) **olmayan** satırları ekler - her
  tablonun kendi anahtarıyla (işlem numarası, kullanıcı + hücre, ayarın adı …). Var olan satırın üzerine yazmaz;
  yalnızca satırın kendi zamanını taşıyan tablolarda bozuk dosyadaki hali daha yeniyse onu alır: kişisel ve ortak
  girdiler, senaryolar, Günlük İşlemler'in ve Trades'in işlemleri (gün içinde düzeltilen ya da silinen), işlem
  şablonları, Günlük İşlemler'in gün görüntüleri, ajandanın yapılan maddeleri ve tekrarlayan işleri, geri
  bildirimlerin yapılanları, Bloomberg'in günün cevapları; Broker Chat'te gün içinde silinen satır silinmiş kalır.
  Hesaplar ve ayarlar (`kv`) kendi zamanını taşımaz: var olanlar korunur (bugün değişen bir şifre, bir ayar yeniden
  yapılır; özet hangilerinin farklı olduğunu söyler). Ayarlardan yalnızca Bloomberg'e bugün sorulanları sayanlar kayıt
  kayıt birleştirilir - günün veri sayacı (`bbg.hits`), tarihçenin ve Spot / FX'in istek kayıtları (`hist.fetch`,
  `fx.hist.asked`), Eurobond bilgileri (`fiyatyukleme.eurobonds`): **bugün sorulanlar yeniden sorulmaz** (günlük limit).
* **Silmez.** Yedekte olup gün içinde silinen bir kayıt (silinen kişisel girdi, chat mesajı, ajanda maddesi …)
  geri dönülen veritabanında durur; kurtarma onu silmez (Günlük İşlemler'in ve Trades'in silinen işlemleri ile Broker
  Chat'in silinen satırları silinmiş olarak gelir: silmeleri satırın kendisinde yazılıdır).
* **Numaralar.** Yedeğin üzerinde dashboard açılıp yeni kayıt girildiyse (bozuk dosyadaki bir işlemin numarasını
  başka bir işlem aldıysa) o kayıt yeni bir numarayla eklenir; Trades'in günlüğü ve kapanışı, ajandanın günleri onu
  izler. İkinci kez çalıştırmak bir şey eklemez.
* **Ya hep ya hiç.** Hepsi tek işlemde yazılır. Önce şimdiki veritabanının bir kopyası alınır,
  `data\tto.db.kurtarma-oncesi-YYYYAAGG-SSDDss` (bir şey eklenmediyse silinir): geri almak için `yedekten-don` ile ona
  dönülür.
* **Özet.** Sonunda masanın bildiği adlarla yazar - "Günlük İşlemler: 12 işlem (24.11)", "kişisel girdiler: 34 girdi
  (3 kullanıcı)", "chat: 5 mesaj (24.11)" -, okunamayanları ("Günlük İşlemler: 8 işlem okunamadı (24.11) –
  şimdiki veritabanında olan: 5, kayıp: 3"), şimdiki hali korunanları ve tablo tablo sayıları. Özet dashboard'un günlük
  dosyasına da yazılır (`--dene`'ninki yazılmaz).
* **Tarihçe** (günlük kapanışlar, izlemenin kapanışları, PPK fiyatlama geçmişi) okunamadığı yerde atlanır: dashboard
  eksik günleri kendisi çeker (yalnızca yeni günler).
* SQLite bozuk dosyanın tablo listesini (ilk sayfasını) hiç okuyamıyorsa geri getirilecek bir şey yoktur: komut bunu
  söyler, şimdiki veritabanına dokunmaz; geriye en son yedek kalır.

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
  ister. Sayfalara yeni nesil saniyede en çok bir kez bildirilir. Bir yazma (girdi, Delete, yapıştırma, senaryo,
  piyasa) hesaplama iş parçacığında uygulandığı anda yeni nesil başlar: tam o anda istenen sayfa (bir önceki yazmanın
  cevabının başlattığı yenileme) yazılanı getirir. Eskiden nesil ancak yazmadan sonra ilerlediği için arada yapılan
  sayfa yazılanı eski nesille veriyordu; tarayıcı onu "değişmedi" sanıp hiç almıyordu (24.11.2026: DİBS RV'de ISIN'i
  silinen kâğıdın fiyatı yeni satırına geçtiği halde sayfada eski satırında kalıyordu).
* **Bir tarayıcıya bir canlı akış.** Sekmeler akışı paylaşır (BroadcastChannel + localStorage); 7. sekme artık
  bağlantı beklemez. `/api/status` açık akış sayısını gösterir.
* **Kendi girdisi olan kullanıcı.** Şeridi, sayfaları ve izleme listesi piyasaya en çok 5 s'de bir yeniden hesaplanır
  (`--private-refresh`; kendi değişikliği ve ortak bir girdi hemen görünür). Bağlı olmayan kullanıcının izleme listesi
  herkesin hesabından okunur (kendi girdisine bağlı kalem o sırada okunmaz). 30 dakikadır görünmeyen kullanıcının
  hesabı bırakılır, dönünce yeniden kurulur (`--idle-minutes`).
* **Her formül şablonu bir kez ayrıştırılır.** Bir formülle doldurulmuş hücreler tek bir şablonu paylaşır (dört
  kitapta, dashboard'un kendi sayfalarıyla ~21 000 şablon). Açılışta kitaplar, Bloomberg taraması, derleyici, tarih
  hücreleri ve başvuru dizini aynı şablonu her biri yeniden ayrıştırıyordu (başvuru dizini kurulana kadar ~104 000
  kez); artık her şablonun ağacı bir kez kurulup saklanır (en son kullanılan 32 768 şablon; kitapların hepsi ~36 MB)
  ve hepsi onu okur. Masanın 17.11 veritabanının kopyasıyla, kayıtlı veri modunda, başka oturumlar bilgisayarı
  yüklerken (üçer açılışın ortancası): hizmetin kurulması 15,8 → 11,9 s, ilk sayfa (kuruluşun başından) 19,6 → 15,1 s,
  ısınmanın bitişi 40,2 → 26,0 s, başvuru dizininin kurulması 17,8 → 10,3 s. Hesaplanan değerler aynıdır.
* **Isınma.** Açılışta, gün dönünce ve toplantı takvimi değişince şerit ve bütün sayfalar en düşük öncelikle, sayfa
  sayfa önceden hesaplanır: sabahın ilk kullanıcısı beklemez.
* **Bloomberg veri limiti yeniden başlatmada harcanmaz.** Günün veri isteği sayacı ve günün referans cevapları
  (kotalar değil) veritabanında tutulur; aynı gün yeniden başlayan dashboard bunları yeniden sormaz, vadesi
  gelince sorar. FX tarihçesinin "bugün çekildi" bilgisi de saklanır.
* **Dizi hesapları hızlı yoldan (hız paketi, 19.11).** Dizi formüllerinin eleman eleman işlemleri (`(A>=x)*(A<y)*B`
  gibi; `SUMPRODUCT`'ın argümanları), `SUMPRODUCT`, `COUNTIF` ve `MMULT` sık görülen durumda (sayı, boş hücre, mantıksal
  değer; uyan şekiller) hızlı yoldan hesaplanır; metin, hata, uymayan şekil ve diğer her şey eski yoldan. Sonuçlar bit
  bit aynıdır, toplamaların sırası korunur (Bootstrap kıpırdamaz): masa veritabanının 17.11 kopyasıyla bütün sayfalar
  soğuk açıldıktan sonra ortak hesaptaki 234 311 değerin hepsi eskisiyle aynı. Soğuk açılış (replay, aynı kopya, dörder
  ölçümün ortancası, makine başka oturumlarla yüklüyken): DV01 2,11 → 0,87 s, Günlük İşlemler 1,46 → 0,52 s, üst şerit
  1,98 → 1,43 s (şeridin kalan süresinin çoğu formüllerin derlenmesi).
* **Büyük JSON cevapları sıkıştırılır.** gzip kabul eden istemciye (tarayıcılar kabul eder) 1 KB'tan büyük JSON
  cevapları gzip'le gider (`Vary: Accept-Encoding`): OIS 775 KB → 115 KB, Sinyaller 1,08 MB → 139 KB, Trend 787 KB →
  107 KB. 128 KB'tan büyük cevap ayrı bir iş parçacığında sıkıştırılır (sunucu o sırada başka cevapları verir). Canlı
  akış (`/api/events`), statik dosyalar ve indirilen dosyalar olduğu gibi gider.
* **Arka planda uzun bir hesap sürerken sayfalar donmaz.** Tarihçenin tabloları (günlük kapanışlar, izlemenin kendi
  kapanışları, PPK fiyatlama geçmişi) veritabanı açılırken bir kez belleğe okunur (masanın ~175 000 kapanışı ~0,5 s,
  ~14 MB) ve her yazmayla birlikte güncellenir; sayfalar onları artık SQLite'tan satır satır okumaz. Python'un
  sqlite3'ü her satırda yorumlayıcıyı bırakır: quant'ın fit'i, walk-forward backtest ya da tarihçe senkronu sürerken
  her satır ~5 ms bekliyordu ve **Eğri Hareketi** hesaplama iş parçacığını yarım dakikadan uzun tutuyordu; alarm
  kontrolleri, quant'ın canlı okuması ve öteki sayfalar onun arkasında bekliyordu. Masa veritabanının 17.11 kopyasıyla,
  kayıtlı veriyle, backtest sürerken ve Eğri Hareketi de açıkken (yan yana 3 ölçümün ortancası, makine başka
  oturumlarla da yüklüyken): Eğri Hareketi ~45 s → ~0,3 s, Gün Sonu Matrisi ~33 s → ~0,13 s, PPK Fiyatlama Geçmişi
  ~12 s → ~0,3 s, Vol · Carry ~16 s → ~0,3 s, FX Vol İzleme ~18 s → ~1,2 s; alarm kontrolünün en uzun bekleyişi
  39–68 s → 1 s'nin altı (açılıştan ~1,5 dk sonra bir kez çalışan kopya hazırlığı dışında). Arka planda iş yokken
  süreler aynı ya da daha kısa; sayfaların içeriği birebir aynı. Bugün'ün (~1,2 s) ve Günlük İşlemler'in (~0,5 s)
  kalan yavaşlığı tarihçeden değil: yorumlayıcıyı arka plandaki hesapla paylaşmaktan (Bugün'ün ~30 küçük sorgusunun her
  biri sırasını bekler). Bozuk bir dosya yine açılır (denetim söyler); tarihçesi o zaman eskisi gibi dosyadan okunur.

## Testler

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest tests
```

Bloomberg ve ağ gerekmez (19.11.2026'da oturumların çalıştığı bilgisayarda iki grup yan yana ~50 dk, tarayıcı testi
~6 dk). 2907 test (gerçek `blpapi` kuruluysa 7 tane daha):

| Dosya | Kapsam |
|---|---|
| `test_xl_functions.py`, `test_xl_engine.py`, `test_numfmt.py` | Excel semantiği (operatörler, yuvarlama, tarih - bayram, 1 Ocak ve hafta sonu tatilli `WORKDAY` / `NETWORKDAYS`, iki listenin yan yana sütunlarından **ortak takvim** (boş hücre, 0, aynı gün iki kez, sırasız liste, metin tarih; ad ya da boş metin `#VALUE!`), ay sonu ve 29 Şubat'ta `EDATE` / `EOMONTH`, `YEARFRAC` -, metin, arama, koşullu toplamlar, matris, `LET`, `FILTER` ve taşma / `#SPILL!`, `AGGREGATE`, sıfıra yapıştırma), bağımlılık takibi, kullanıcı katmanları (aynı gruptaki girdilerden birini değiştiren kullanıcının diğerlerini dosyadaki değeriyle görmesi dahil), **sonradan elle değer yazılan formülün hiçbir hesaplanmış değeri silmemesi** (yalnız bağımlıları, yalnız yazan kullanıcı için; yukarıda kendi değeri olan kullanıcının değerleri dahil), **sonradan yazılan sabitin formül başvurularıyla izlenmesi** (hücre, aralık, tanımlı isim, `A1:INDEX(..)` kutusu; dizi formülünün alanında eski yol), **bir hücre grubunun okuduğu girdiler** (`RefIndex.upstream`: hücre, aralık, tanımlı isim, `A1:INDEX(..)` kutusu, taşma alanı; zincirin girdide bitmesi, 3 000 hücrelik zincirin özyinelemesiz izlenmesi), hiçbir şey hesaplanmadan tanımlanan girdinin sıfırlama yapmaması, taşmanın `#NUM!` olması, büyük yığınlı iş parçacığında uzun zincirin bölünmeden hesaplanması (değerler ve maskeler aynı), **rastgele geçersizleştirme testi** (her adımda her kullanıcının her hücresi sıfırdan hesapla aynı), **dizi verilen dizi formülü** (girdi yapılmış bir dizi formülüne bir kullanıcının ya da katmanın verdiği dizinin alanına formülün kendi sonucu gibi yazılması - kısa dizide alanın kalanı boş -, okuyanların yalnız orada yeniden hesaplanması, başka girdiler değişince elemanların yeniden yazılmaması, dizi kalkınca formülün sonucuna dönüş), sayı biçimleri; **kullanıcının ondalığı** (`with_decimals`: yalnız ondalık değişir - yüzde, binlik ayırıcı, milyon ölçeği, renkli / parantezli eksi, sonek, üs yerinde; muhasebe sıfırının `-`'si, tarih, saat, metin aynen; General `0.00` olur) |
| `test_xl_parse.py` | **Şablonun bir kez ayrıştırılması** (`tto/xl/parser.py`): aynı şablona aynı ağacın (AST) verilmesi ve baştan ayrıştırılanla aynı olması, yaprakların (başvuru, sayı) şablonlar arasında paylaşılması; ayrıştırılamayan şablonun her seferinde eskisi gibi hata vermesi; saklananların sınırı (en son kullanılan 32 768; paylaşılan yapraklar da sınırlı); aynı anda ayrıştıran iş parçacıklarının her birinin bütün bir ağaç alması; bir çalışma kitabının iki kez hesaplanması (önce baştan ayrıştırılmış, sonra saklanan ağaçlarla: değerler aynı); **hiçbir çağıranın ağacı değiştirmemesi** (hizmet kurulup sayfalar, girdiye formül ve başvuru dizinleri çalıştıktan sonra her şablonun saklanan ağacı baştan ayrıştırılanla aynı) |
| `test_parity.py` | Excel'in kayıtlı değerleriyle parite (sayfa bazında eşikler) |
| `test_xl_fastpaths.py` | **Dizi hesaplarının hızlı yolu eski yoluyla bit bit aynı**: dizi formüllerinin eleman eleman işlemleri (`+ - * / ^ &`, karşılaştırmalar; aynı şekil, sütun / satır / tek değer karşısında dizi, uymayan şekilde `#N/A` dolgusu, boş ve düzensiz dizi, aralık), `SUMPRODUCT` (tek dizi, sütunlar, satırlar, işaretli sıfır, sonsuz, metinden sonra sonsuz, hata, şekil uyuşmazlığı, soldan sağa toplama), `COUNTIF` (sayı, boş, metin, joker, karşılaştırmalı, mantıksal, hata ölçütü; sayıya okunan metin, boş metin), `MMULT` (hata, metin, boş hücre, mantıksal, şekil uyuşmazlığı, işaretli sıfır); uç değerlerin her çifti, rastgele diziler, 15 hanede eşit sayılar ve bütün formüller hızlı yollar kapalıyken de aynı |
| `test_reference.py` | LibreOffice'in baştan hesapladığı değerlerle karşılaştırma (`tests/data/lo_*.json.gz`) |
| `test_forward.py` | Forward: bağımsız kapalı formül, Excel'in kayıtlı değerleri, işlem girişindeki fiyatlamanın sayfayla aynılığı |
| `test_progress.py` | **Hesap** (`tto/progress.py`): kalan sürenin kuralı test saatiyle (ölçü yokken boş, üç birimden sonra bu çalışmanın hızı, öncesinde son çalışmanınki - yeni açılışta veritabanından -, sürmekte olan birimin geçen süresi düşülür ama sıfırın altına inmez, geri test bütçesini aşmaz, iki saatin üstü yazılmaz, başarısız çalışma ölçü bırakmaz; ML modelinin süresi eğitimin kendi süresi; tam hesapta son tam hesabın adım süreleri, ML adımı kendi modelleriyle, son adımdan sonra kalan kuyruk, ilk / sonraki hesap ayrı, kayıtsız türde yalnız sıra); yazımı ("az kaldı", "~40 sn", "~3 dk", "~1 sa 5 dk", "Mart 2026 · 14.03.2026 kapanışıyla"); **sentetik tarihçede gerçek tam hesap**: adımların kodun sırasıyla sayılması (Trend sırası geldiğinde "Quant 20/26 · şu an Trend", quant durumunda da), ML'in eğitilecek her modeli tek tek (yapılan / toplam), bitince hiçbir şeyin kalmaması ve sürelerin saklanması, aynı veriyle ikinci hesapta ML işi olmaması, açılış gibi yeniden ilk hesapta kalan sürenin baştan bilinmesi; **geri test** her yeniden kurmanın başında yapılan / toplam, ayı ve kapanışı, ilk geri testte süre yok, ikincide son geri testin hızıyla; **tarihçe** her isteğin serileri, sonra PPK günleri tek tek, hatayla kesilen turun iz bırakmaması; `/api/progress` ve `/api/status` (oturumsuz 401, boşta `busy: false`) |
| `test_blotter.py` | Outright / spread / fly / FRA bacakları, maliyet, ortak işlem defteri, forward'ların O/N karşılığı, Excel özet tabloları, **15M / 21M bacağın iki yanındaki kovaya bölünmesi** (12x15 FRA'nın 15M bacağı yarı 1Y, yarı 18M; 21M yarı 18M, yarı 2Y - sayfanın satırları, özeti, karşı taraf × vade tablosu ve maliyet tablosu; işlem kendi vadesini tutar), **DV01** (forward: sayfadaki "Forward DV01" bloğuyla aynı sayılar, iki yön, tutarsız fiyat; OIS net / brüt; tahvil: DİBS RV tablosundan, tabloda olmayan kâğıt), işlemle saklanması ve risk özeti, DV01'siz eski kayıt, **tarih aralığı** (günler, toplam maliyet / risk, uçların sırası; **aralığın özet tabloları**: Excel sayfasının kendi tabloları aralığın işlemleriyle ayrı bir hesapta - OIS vade özetinde iki geçmiş günün ve bugünün 1Y'si birlikte, Bonds ve CPT tablosunda aralığın kâğıdı ve karşı tarafları -, üstündeki kapsam yazısı, sayfanın kendisinin bugünün kalması, maliyet tabloları; özeti olmayan geçmiş günün kendi işlemleriyle hesaplanıp bunu söylemesi, özeti olan günün özetiyle gelmesi; sayfaya sığmayan işlemlerin sayılması) ve aralığın tek dosya olarak indirilmesi; **Chat ↔ Günlük İşlemler** (masanın chat işlemleri: ±15 dk içinde aynı enstrüman / seviye "girildi", "İşlem gir" notuyla saatinden bağımsız eşleşme, başka seviye "girilmedi", broker satırının ve cross currency'nin sayılmaması, durumdaki ve sayfadaki sayı, elle eşleştirme / yok sayma / yanlış eşleşme / geri alma, silinen kaydın satırı geri getirmesi, hatalı istekler) |
| `test_brokerchat.py` | Broker chat: masanın gönderdiği örnek satırlar ve telefon ekranındaki chat satır satır (saat, gönderen, enstrüman, bid / ask, işlem, ref, OCO, cross-currency), enstrüman türleri ("v"siz spread, fly, FRA yazımları, forward), iki tarafın ve tek tarafın her yazımı, büyük rakamın tamamlanması (öbür taraf, önceki seviye, eğri, belirsizlik), bir satırda birkaç kota, kota olmayan satırlar, mesaj düzenleri (saat başta / sonda / alt satırda, isim, tarih), tahta, eğriyle karşılaştırma; saklama (önizleme, ikinci kez yapıştırma, saatsiz satır, o saate kadarki referans, fiyatsız "taken"), tahtanın model seviyeleri (outright / spread / fly / FRA, kişisel senaryo), **switch'in ekranla değerlemesi** (modeli ekrandaki switch, ASW eğrisine göre yeri, bacak bacak yazılmış switch'in seviyesinin bacakların ekranda getiriye çevrilen fiyatlarından, TLREF switch'inde fiyat farkı, tahtadaki satırı, DİBS sayfalarına girmemesi), **MPC tarihli OIS** (30 yazılış: ay adı İngilizce / Türkçe, yıllı, `mpc1` / `1st` / `next`, `dec/jan`, `dec jan`, `mpc1/2`, iki yanı ayrı yazılmış; hangi toplantı - ayın ilk toplantısı, karardan sonra süren dönem, karar günü MPC1 -, birkaç dönem, spot'tan, işlem / ref / ilgi, kısa seviye, bir satırda iki MPC kotası, boyutun vade sayılmaması, adım kotasının / tarihin / toplantısız satırın metin kalması, takvimde olmayan toplantı, tahtada tek satır; servisle: modelin "MPC OIS" tablosunun D sütunu ve MPC formunun piyasa seviyesiyle aynılığı, kısa seviyenin modelden tamamlanması, ima PPK adımı ve bootstrap'ın adımı (TLREF iş günlerinde bileşik, dönemlerin modelin hafta sonu / tatil terimiyle), tahta sırası ve son işlemin adımı), **chat ↔ Günlük İşlemler eşleştirmesi** (kayıtların paket paket enstrüman / seviyesi; aynı enstrüman ve seviye ±15 dk, iki satıra tek kayıt - saati yakın olan, "İşlem gir" notuyla iki saat sonra, başka seviye, formu olmayan ürün, MPC / FX swap / DİBS, elle eşleştirme, yok sayma, yanlış eşleşme, silinmiş kaydın yeniden aranması), **en iyi fiyat broker broker** (sonra söylenen kötü kotanın iyisini örtmemesi, broker adı ve saati, geri çekilen yalnız o broker'ın, işlemle o seviyede ve daha iyi olanların ve oco mesajının öbür kotasının inmesi, seviyesiz işlem, bizim kotamızın ayrı kalması, bayat sınırı - yaş, en iyi sayılmama, daha taze kötü kotanın en iyi olması, ileri yazılmış saatin taze saymaması -, getiride ters yön; servisle: bugünün tahtası saatle, masanın 1 - 1440 dakikalık sınırı, işlemin bid'leri indirmesi, tek enstrüman sıfırlaması ve sonrası, geri alma, geçmiş günün sonundaki hâli; .xlsx'te en iyi fiyat, kimde, yaş ve "Brokerlar" sayfası), günler / aralık / silme, .xlsx, yeniden başlatma, HTTP uçları |
| `test_blotter_fx_mpc.py` | Blotter'ın yeni girişleri: parite okuma, **EURTRY** (sayfanın EURTRY tablosu ve swap puanı satırıyla aynı sayılar, TRY faizinden fiyat = çapraz forward bloğunun hücresi), **swap puanı** (forward = spot + puan / 10.000, ima faiz, Türkçe / İngilizce yazım, eksi puan), **minor para** (elle outright / spot + puan, eğrisiz paritede reddedilen fiyatlama tipleri, TRY'ye karşı olmayan parite), forward DV01'i (payer +, iki yön, USD'ye USDTRY spotuyla çevrim), işlemlerin paritesiyle saklanması, parite + valöre göre maliyet, Excel sayfasına yalnızca USDTRY ve vadeli OIS'in aktarılması, **MPC tarihli OIS** (tarihler ve piyasa seviyesi "MPC OIS" tablosuyla, nominal sayfanın "Nominal" sütunuyla aynı; iki tarih arası hesaplayıcıyla aynı seviye, nominal verilince DV01, dönemlerin çarpımı, hatalı tarihler; **tablonun kendi iskonto faktörleriyle** spot / toplantı günleri arasındaki her swap'ın hesaplayıcıyla aynı seviyesi, tablo dışı gün), listede / maliyette / riskte yeri, indirilen dosyada parite, puan ve işaretli DV01, HTTP uçları |
| `test_tradehint.py` | **Fiyattan işlem** (`tto/tradehint.py`, `/api/trade/prefill`): her sayfa tanımının `"trade"` ipucunun denetimi (19 tablo: hücreleri tablonun gösterdiği sütunlarda, okuduğu sütunlar ve tarih hücresi var), tarayıcıya tabloyla giden fiyat hücreleri (launchpad'in sütun parçasında da) ve başlıktaki "İşlem gir" düğmesinin yalnız swap puanlı forward tablolarında kalması; tablo türü türü dolan işlem: **forward kotasyon matrisi** (satırın kendi valörü, puan / outright / TRY % fiyatlaması, bid'de alış, ask'ta satış; EURTRY; Forward'daki matrisin RET ask'ı), **tek valörlü forward tablosu** (tablonun valörü, eğrinin mid'inde yön yok, RET satırının RET bid / mid / ask'ı, EURTRY), **RET** (TRY RET, ORANLAR, RET bandı: vadenin spot'tan tarihi, ON'un fiyat sayılmaması), **hesaplayıcılar** (tarih arası forward'ın başka tablodaki bitiş tarihi, forward-forward puanının fiyat sayılmaması; kırık vadenin valörü, ACT/365 satırının fiyat sayılmaması), **OIS** (par'ın outright'ı, 15M; ORANLAR'ın OIS kotası; MPC OIS satırının kendi iki günü - formun sunduğu günlerden -; bid / ask'lı bir kotada PAY / RECEIVE), **tahvil** (satırın ISIN'i, alış / satış, getiride o tarafın fiyatı ve not, kullanılan temiz fiyatta yön yok, DİBS Trading, Tüm Kâğıtlar, ASW, boş liste satırı), **TOPLU FORWARD** (USDTRY ve EURTRY yan yana: her fiyatın kendi sütununun paritesi - `"pairs"` -, fwd / puan / elle forward / İma TRY %'nin fiyatlaması, satırın valörü, yön yok; valörsüz satırın, RET mid %'nin, ON karşılık %'nin, Spread (bp)'nin, P/gün'lerin ve başlık satırının reddi; `"pairs"`'in denetimi: forward fiyatı olmayan anahtar, parite olmayan değer), **VİOP** (nedeniyle reddi), fiyat olmayan hücre, fiyat satırları dışı, ipucusuz tablo ve sayfa, okunamayan fiyat, hatalı istek; kullanıcının satıra yazdığı valörün (serbest satırda da) işlemin valörü olması, başka kullanıcının dosyanınkini görmesi; HTTP ucu (kullanıcının sayı biçimi, 400, 404, 401) |
| `test_tradevalue.py` | **Trades · değerleme ve carry** (`tto/tradevalue.py`), elle hesaplanan durumlarla: kitapların kotasındaki OIS ve SOFR swap'ının her vadede sıfır değeri (TRY ve USD kuralının Motor / SOFR_FOMC bootstrap'ıyla aynılığı), Motor'un formülüyle elle kurulan eğride par swap'ın sıfırı ve kotalar 1 bp kayınca MTM değişiminin DV01'e eşitliği, kendi seviyelerindeki spread'in sıfırı ve DV01-nötr spread'in kaymadan etkilenmemesi, fly seviyesinin iki kuralı (50/50 ve OIS sayfasının 2·gövde − kanatlar'ı), FRA'nın tek başına değerinin kendini üreten bacaklarla toplamı ve artığı (ızgaradaki FRA'da sıfır; "3x6"nın formdaki varsayılan valörün üstüne tarihleri), ödeme takvimleri (USD vadeyle kitabın kuralı, kırık tarihte bitişten geriye; TRY tek ödeme ve üç aylık kupon - kırık tarihte vadeden geriye, ilk dönem kısa, vadeyle girilende başlangıçtan ızgara, 13A'da ilk dönem 1A -; TRY kırık tarihte Trades'in dönem sonlarının Fiyatlama'nın ödeme günleriyle, tatiller dahil, aynılığı), dönem içinde kapanan swap (kapanışa kadar kendi tahakkuku, sonra sabit faiz farkı) ve kapanmış FX / tahvil / opsiyon, yönün sözle ("receive" / "pay") ya da blotter'ın koduyla ("S" / "B") aynı değeri vermesi ve bacakların yönü sözle de yazması, MPC işleminin takvim kayınca toplantının tarihiyle yerinde kalması, başlamış OIS'in TLREF fixing'leriyle elle hesabı (ödenmiş dönemin net ödemesi accrued'da), SOFR'ın kendi fixing'leriyle ve fixing yokken söylemesi, **kuponlar**: başlamış SOFR swap'ının ekilen fixing'lerle elle bileşiği (2025 ABD tatilleri - SIFMA listesinde yok - fixing'siz günden okunur, önceki fixing tatili kapsar; yayımlanmamış pazartesi son fixing'le ve notta adıyla; ödenen yılın 2 SIFMA günü sonraki ödeme günü, işleyen dönemin bugüne kadarı), `market()`'in SOFR'ı tarihçenin `SOFRRATE Index`'inden okuması ("tarihçede yok" notu gider), TRY OIS ve SOFR'ın birçok vadede dönemleri ve ödeme günleri (TRY 1M–2Y dönem sonunda, SOFR 6M–3Y ve tatil arifesinde biten dönem iki iş günü sonra), ödeme gününde kuponun MTM'den accrued'a geçip değerin sıçramaması (o günün farkı bir günlük faiz) ve spread'in iki bacağının kendi kuponları, tarihçeden eski işlemin kuponlarının kendi tarihlerinden ve tahmini günlerin adıyla, kapanmış swap'ın kapanış sonrası dönemlerinin sabit faiz farkı; tahvilin kendi fiyatında sıfır MTM'i ve kupon dönemini aşan alışta kirli fiyat farkı ve kuponun accrued'u (BIST kuralıyla elle), getiriyle girilen bono ve kuponlu tahvil (basit ve bileşik), FX spot K/Z'si ve TL / USD çevrimi (yen dahil), Garman-Kohlhagen'in kapalı biçimi ve put-call paritesi, smile'ın ATM'deki vol'ünün ATM kotası (SVI ve Vanna-Volga), greek'lerin sonlu farkla doğrulanması, ürün başına carry'nin elle değeri (OIS tahakkuku, düz eğride sıfır roll, eğimli eğride roll-down, bono ve kuponlu tahvil, FX O/N puanı, opsiyon theta'sı), hafta sonu ve tatil üzerinden carry günleri, sonuçların düz JSON olması, `manual_price` yedekleri (fiyatsız kâğıt, spot'suz parite, vol'süz opsiyon), `check()`'in Türkçe hataları ve düzenlemeleri (kayıtlı işlemin sonradan tatil olan valörüyle de değerlenmesi), dikilmiş tatiller üzerinden ürün ürün varsayılan valörler ve vadeden teslim, DV01'den nominal (5 mn'e yuvarlama, kontrol DV01'i, en az bir lot, USD / TL), `market()`'in sahte terminalde **hiçbir Bloomberg isteği ve aboneliği** yapmaması; **fonlama** (`funding_1d`: FX spot'ta carry'nin tamamı ve kısada işaretinin dönmesi, DİBS'te kirli fiyatın TLREF'le fonlanması - carry'nin kâğıt ve fonlama parçaları -, swap'ta ve opsiyonda 0, kapanmışta yok), **biriken** (`running`: başlamış OIS'te işleyen dönemin bugüne kadarki neti elle - fixinglerin bileşiğiyle -, Kuponlar'ın "işliyor" satırıyla aynılığı, paketin bacaklarının toplamı) ve carry'nin parçaları (`carry_parts`, `carry_note`); **DV01'in vadelere dağılması** (`risk`: spot'tan vadeyle girilen kendi vadesinde, 15M ½ 1Y + ½ 18M; kırık tarih iki yanındaki vadeye gün oranında; FRA spot'tan bitişine ve ters yönde başlangıcına, DV01'leri toplamı FRA'nınki, başlangıcın faizi eğrinin; spread bacak bacak; SOFR kendi eğrisinde; tahvil vadesinde alışta "S"; kapanmışta ve FX'te yok); **opsiyon priminin vol'ü** (24.11.2026, masanın 11. maddesi): `implied_vol` `gk`'nın vol'de tersi - primin vol'üyle değerlenen opsiyon primine eşit (MTM 0, primin 1e-9'u), bir vol'le fiyatlanan prim o vol'ü geri verir (prim vol'le oynadığı her yerde; call / put, içeride / dışarıda, iki hafta - bir yıl, prim iki dövizde), içsel değerin altındaki prime vol yok; strike'taki smile vol'ünün ve verdiği primin yanında olması, USD prim bugünkü kurla, üst sınırlar (call S · DF_baz, put K · DF_kote), içsel değerin altı / hemen üstü, sıfır prim, vadesi geçmiş, smile'ı olmayan parite (EURTRY: primin vol'ü yine), opsiyon olmayan ve piyasasız istek (söylenir, hata atılmaz); değerlemenin `vols`'u |
| `test_watch.py` | **Uzaktaki kullanıcı** (kendi girdisi olup bağlı olmayan kullanıcının listesi herkesin hesabından, kendi girdisine bağlı kalem okunmadan; bağlıyken en çok `private_refresh`'te bir); **Ne izlenebilir**: OIS, offshore, masa, VİOP kontratı (ticker'ıyla ya da sırasıyla; OIS − VİOP bp, ima faiz), kâğıt (ISIN'iyle; ASW, getiri, pahalı/ucuz, liste dışı kâğıt), hücrenin gösterdiği şey olarak alınması, reddedilenler; **ifadeler** (okunuşu, hataları, birimi: spread / fly bp, ortalama %, oran düz sayı, hücre adresi); **izleme listesi** (hazır gruplar, açılış / düşük / yüksek / gün içi çizgi, referanstan değişim, sıra / ad / hücrenin birimi, kişiye özel liste, açılışın saklanması, yeni gün); **alarmlar** (seviyenin gösterildiği gibi okunması, ≥ / ≤ / kesişir, bir kez çalması, başka kullanıcıya söylenmemesi, yeniden kurma ve silme, izleme döngüsünün kendiliğinden çalması; **VİOP spread'i, kâğıt ASW'i ve ifade üzerine alarmlar**); kâğıt listede yer değiştirince ve **kontratlar dönünce** takip; **bir kâğıdın satırındaki ve bir VİOP kontratının sütunundaki her hücrenin** o kâğıt / kontrat olarak izlenmesi (swap puanı, altın-TRY ask tablosu, DV01, Tüm Kâğıtlar bid'i, DİBS ASW; adı ve vadesi, kontratlar dönünce ve kâğıt satır değiştirince izlemesi, birim seçimi, kâğıtsız satırın ve hesaplayıcı sütununun hücre kalması, hatalı konuların reddi); **hücre olarak saklanmış kalemlerin ve alarmların bir kereye mahsus kâğıda / kontrata bağlanması** (önceki sürümün kalemi ve birimi, alarm seviyesi, kapanışların yeni adına taşınması, diğer hücrenin hücre kalması, bir kez); önceki sürümün listeleri; HTTP uçları (katalog, önizleme) ve **masa notları**; **hareket alarmları** (açılıştan, kurulduğu andan, referanstan, son 10 dakikada - saat testte verilir -, yön, hatalı koşulların reddi, yeniden kurunca yeni başlangıç); **z-skoru ve bant** (tarihçeden, ifadenin parçalarından, dashboard'un kendi kapanışlarından; 20 / 60 / 250 gün; günün kapanışının kaydı; z alarmı); **ısı haritası** (tablolar, sütunlar, hücrelerin konuları, piyasanın hareketi, önceki kapanış: tarihçe ve kendi kayıt, referans - kişiye özel -, HTTP, VİOP sütunlarında vade ayı); **piyasanın kapalı olduğu gün** (hafta sonu ve masanın tatilleri; cumartesi kapanış kaydedilmemesi, önceden kaydedilmiş hafta sonu değerinin kapanış sayılmaması, pazartesinin önceki kapanışının cuma olması, hafta sonu seviyenin cuma kapanışı ve değişimin 0 olması, tatilin hafta sonu sayılmaması); **masa alarmları** (yalnızca yöneticinin kurması, kimsenin kişisel listesinde olmaması, piyasanın değeriyle - bir kişinin senaryosuyla değil - denetlenmesi, herkese bir kez çalması, **"Gördüm – X bakıyor"** cevabında ilkinin geçerli olması ve alarmın açık olmaktan çıkması, **susturmanın kişisel olması** (susturana sessiz, başkalarına çalması, sayacına girmemesi, kaldırılınca yine ona gelmesi), yeniden kurma / silme, günün kaydında kimin ne yaptığı; HTTP uçları ve yetkiler) ve **sistem alarmları** (kayıtlı veride yalnızca veritabanı; veri akışının piyasa saatinde N dakika bayat kalması ve düzelmesi, piyasa saati dışında tick beklenmemesi, TLREF fixinginin saatine kadar gelmemesi ve gelince kapanması, kendisi için susturanın dışında herkese çalan veritabanı alarmı, ayardan kapatılan alarmın kapanması, RET alarmının olmaması ve önceki sürümden açık kalan RET alarmının kapanması); **ısı haritasının kapanışları bellekten** (hesaplama iş parçacığında - hiçbir yerde - tarihçe için SQLite okuması yok; izleme listesinin z-skoru ve alarm kontrolü de; yeni kapanış bir sonraki açılışta görünür; harita dosyadan okunarak yapılanla birebir aynı) |
| `test_bonds.py` | **Tüm Kâğıtlar** (masanın listesi: 77 kâğıt altı türde - TLREF ve FRN ayrı -, her türde vade sırası, ★, trading listesindekilerin fiyatı ve DİBS RV özeti, listede olmayanlar, sayfadaki ☆ / ★, ▸ ve ✕; **+ ISIN ekle** canlı-benzeri bir Bloomberg'le: tür, vade, kupon Bloomberg'den, kendi grubuna, döviz cinsi ve tanınmayan ISIN'in reddi, yanıt gelmeyenin türünü bekleyip sonra yerine geçmesi, saklanması, ISIN seçicide görünmesi, HTTP; **✕** herkes için ve trading listesinden de, geri ekleme; vadesi geçenin ertesi gün düşmesi; eski "kendi eklediklerimiz" satırlarının listeye taşınması; **satırların korunması**: yeniden başlatmada aynı satırlar, yeni kâğıdın hiç kullanılmamış satıra girmesi, vadesi geçenin satırının boşalıp üzerindeki "Elle değer"in gitmesi ve o satırın sonra kullanılması, fiyattaki alarmın kâğıdı izlemesi), **DİBS RV'de FRN** (Tüm Kâğıtlar'dan ya da Bloomberg'den: "F", "FRN", TLREF'e karşı hesapların boş kalması, canlı fiyat sayfasındaki adı, özetteki grubu), **★ ile trading listesi** (listenin sonuna ekleme, herkes için, DİBS ASW'nin ISIN listesinin de izlemesi, özetteki tür grupları ve vade sırası, çıkarınca satırın kaynağının ve herkesin kişisel değerlerinin silinmesi, HTTP), **DİBS ASW ve Tüm Kâğıtlar trading listesini her yoldan izler** ("+ ISIN ekle", yazılan, birkaç tane yapıştırılan ISIN, ★: ASW listesinin son kâğıdının altına, Tüm Kâğıtlar'da olmayan yeni kâğıdın türü Bloomberg'den, döviz cinsinin Tüm Kâğıtlar'a alınmaması, ISIN olmayan metnin hiçbir yere gitmemesi; silinen, üzerine yazılan, ☆ / ✕ ile çıkan, ortak sıfırlamayla dosyadakine dönen listeden çıkanın ASW satırının kaynağı, herkesin manuel fiyatı ve eğri işaretiyle gitmesi; liste içinde yer değiştirenin iki listede de kalması; ASW'nin kendi eklediği kâğıda ✕'in dokunmaması; ASW'den elle çıkarılanı ★'ın geri koyması; dolu ASW listesinde kâğıdın yalnız trading listesine girmesi ve uyarının söylemesi; uyarı metinleri; HTTP), **bir kereye mahsus eşleme** (ilk açılışta trading listesinin ASW'de olmayan kâğıdının son kâğıdın altına eklenmesi, o boş satıra yazılmış değerin gitmesi, günlük satırı, bir kez), **DİBS Trading** (her valörün menkulü ve tarihi, DİBS RV'nin valörünün o sayfadan okunması, diğerlerinin hata değil boş kalması, kaynağın değiştirilip boşaltılınca varsayılana dönmesi, kirli fiyatlardan **ima repo** ve TLREF farkı - yalnız aynı güne ait fiyatlardan, değilse kartta ve özette nedeni -, TÜFE'de repo olmaması), canlıda **işlemin görüldüğü an** (ilk yanıt işlem sayılmaz, aynı fiyattan işlem hacimden anlaşılır, azalan hacim, yeni gün), sayfada saat ve günün işlemleri, **kâğıt kartı** (katalog, DİBS RV satırı, valörler, tahta, chat satırları ve durumları, işlemler, listede olmayan kâğıt, HTTP); **TRY DİBS kataloğu** (77 kâğıt, ISIN kontrol hanesi, ISIN'deki vade, türler - 14 TLREF, 9 FRN -, bir ayın / günün adayları; eklenen kâğıdın türünün Bloomberg alanlarından bulunması: bono / kuponsuz, TLREF / FRN, TÜFE, tarih yazımları, döviz cinsi, tanınmayan ISIN, desteklenmeyen kupon tipi, yanıtsız); broker chat'te **DİBS kotaları** (tarih ve ay-yıl yazımları, TLREF / FRN / TÜFE / bono - `tlref` FRN'e gitmez -, valör, kısa fiyatın tamamlanması, Türkçe işlem / ref / ilgi kelimeleri, switch'in metin kalması), fiyatı bilinmeyen kâğıdın **en yakın aynı tür kâğıttan** (TLREF'ten TLREF, FRN'den FRN) ya da 100'den tamamlanması, **başlıklı liste** (ihale fiyatları), servisin örnek chat'i ekranla okuması (ima getiri, bir ayın iki kâğıdının ekranla ayrılması), **DİBS RV'deki broker sütunları**, **kâğıt sayfalarında tahtanın kuralları** (DİBS RV, DİBS Trading özeti ve valörleri, Tüm Kâğıtlar, kart: en iyi taze bid / ask ve broker'ı, bayat kotanın soluk ve "bayat · BGC · 30 dk" olarak durup en iyi sayılmaması, getiri ve broker − ekran farkının yalnız taze kotadan olması, işlemle giden, geri çekilen ve sıfırlamadan önceki kotanın kalkması, kartta her chat satırının geçerli / bayat / geçmiş durumu), **ISIN ile listeye ekleme** (listenin sonuna, atlanan / reddedilen, ortak ve kişisel liste, HTTP), **100 satırlık toplu forward**'ın Forward tablosuyla birebirliği (Manuel TRY % iki yönlü: varsayılanı boş) ve **Bulk Bond**'un yeni satırları; **switch** kotaları (iki kâğıt: getiri farkı bp, yazılış sırası ve bağlaçlar, "bid … offer" ayrı yazılışı, tahtada tek satır; bacak bacak yazılmış switch: her bacağın fiyatı kendi ekranıyla tamamlanır, olay satırın kelimelerinden; üç kâğıt metin kalır); **ay-yıl tek başına önce sabit kuponlu** (o ayda yoksa ayın TLREF'i, sonra TÜFE'si; tür yazılınca yalnız o tür; switch bacağının kendi türü); **zc = sıfır kuponlu ve getiriyle** (bono / kuponsuz, bitişik `feb27zc`, kuponluya geçmeme, getiride bid > ask ve kısa ask'in altta tamamlanması); virgülden sonraki öbür tarafın aynı kâğıt olması; **canlı kota mı** (`BID_SIZE` / `ASK_SIZE`: emir yoksa soluk "–" ve ipucunda Bloomberg'in tekrar ettiği fiyat, kotasız tarafla alış / satış getirisi, alış−satış ve ASW'nin hesaplanmaması, kullanılan fiyattan çıkan getiri / ASW / sinyal ve broker − ekran farkının soluk gösterilmesi, Fiyat durumu, tek taraflı kota, büyüklüğü olmayan BGN, ALIŞ fiyat tipi, canlı kotalarla bugünün repo'su; kapalı piyasada hiçbir sayfada kota görünmemesi) |
| `test_aswfx.py` | **DİBS ASW'nin FX swap ima eğrisi** (`tto/aswfx.py`): her FX faizinin kendi kuralıyla okunması (TRYI tek dönem basit ACT/360; TRYSAQ yıllık ACT/360 par - masanın dosyasındaki zincirle elle, önceki yılın iskonto faktörü fiyatı olmayan vadede eğrinin o ana kadar kurulan düğümünden -, tür vadeye göre, fiyatı olmayan vadede OIS kotası olduğu gibi); sayfaya giden par faizin sayfanın bootstrap'ında vadesinde aynı iskonto faktörünü vermesi (gidiş-dönüş; 3 aya kadar `r·365/360`), yüksek FX faizinin düşük iskonto faktörü ve yüksek par vermesi; sayfanın formüllerinin kopyasının formüllerin kendisi olması (`BT65`, `BW65`, ara çeyrekler) ve motorun düğümleriyle son basamağına kadar aynılığı (OIS ve FX tarafında); okunamayan faizin (eksik gün / kota, ulaşılamayan iskonto faktörü) boş kalıp eğrinin orada durması; motorda FX hesabının sayfaya bu kotaları vermesi, fiyatlı vadede iskonto faktörünün kendi kuralınınki olması, OIS tarafının (kotalar, eğri, ASW'ler) değişmemesi; **ASW geçmişi offshore eğrisine göre**: vade → tarihçe serisi eşlemesi (1–9A TRYI, 1–10Y TRYSAQ, 18A serisi yok - TRYSAQ1 ve TRYSAQ2'den hesaplanır; TRYI12M tutulsa da 1Y TRYSAQ1), her geçmiş günün kotalarının o günün offshore kapanışlarından (ICPL yoksa BGN'nin hareketiyle) `to_sheet` par faizleri olması, eğrinin sayfanın formülleri (kopyası son basamağına kadar), fiyatlı vadede iskonto faktörünün kendi kuralınınki, kâğıtların ASW'sinin ikinci bir motorda satırın kotaları sabitlenerek (pin) bulunanla aynı ve OIS'tekinden farklı olması, OIS tarafının değişmemesi; bugünkü satırın ASW tablosunun ASW FX ima'sı olması (hesapta ve sayfada); hiç offshore kapanışı olmayan günün offshore ASW'sinin boş kalıp `0 / 16` (ipucu "o gün offshore kapanışı yok") yazması ve grafiğin offshore çizgisinde (İkisi'nde de) boşluk olması - OIS serisi o günü çizer -, bugün EK_FX'te FX faizi yoksa bugünkü offshore noktasının da boş olması, 9A'sı olmayan günün `15 / 16`, TRYSAQ2'si olmayan günün `14 / 16` (18A ve 2Y OIS; ipucunda hangi vadeler) yazması; grafiğin üç seçimi (OIS: çalışma kitabının grafiği aynen; Offshore: aynı grafik offshore hesabında, "· offshore" adlarıyla; İkisi: OIS serileri ve kesik offshore serileri), seçimin kişisel olması, listede olmayan değerin reddi, sıfırlamanın OIS'e döndürmesi, yalnız seçimi olan kullanıcının herkesin offshore hesabını okuması; geçmiş tablosunun kendi sütunlarının eskisi gibi, dört yeni sütunun sonda olması; **18A hesaplanır** (masa, 18.11.2026): XCCY kuponlarının vadeden geriye sayılması (18M: 6M + 12M; 2Y3M: 3M, 15M, 27M) ve par ↔ iskonto faktörünün gidiş-dönüşü; `point_18m`'in offshore eğrinin 18M iskonto faktörü olması (Bootstrap'ta 1Y–2Y XCCY düğümleri arasında ln DF doğrusal, PPK basamak'ta adım eğrisinin kendisi; ASW spot'undan; eğrinin kendi 18M düğümü varsa o) ve 18M XCCY par'ının (6M + 12M) aynı takvimle geri bootstrap edilince aynı iskonto faktörünü vermesi; `to_sheet`'in noktayı alması (sayfanın 18M düğümünde aynı iskonto faktörü; öncekiler ve 2Y'nin iskonto faktörü aynı, 2Y'nin sayfa par'ı başka; noktasız 18M OIS, EK_FX'te faiz olsa da); geçmiş gününün 18M'inin o günün TRYSAQ1 / TRYSAQ2 kapanışlarından (Forward'daki zincir, ln DF doğrusal; biri yoksa OIS); motorda Bootstrap kullanıcısının 18M'inin Forward eğrisinin 1Y–2Y düğümleri arasında, PPK basamak kullanıcısınınkinin kendi offshore PPK eğrisinden olması, sayfanın 18M düğümünde aynı iskonto faktörü, 1–3 yıllık kâğıtların ASW FX'inin iki ayarda farklı, bir yıldan kısaların aynı olması, kayıtlı günde 18M XCCY par %39,59 (Bootstrap) / %39,38 (PPK basamak; önceden OIS kotası %35,59); EK_FX'in 18M satırı (ticker yok, "hesaplanan (XCCY 1Y–2Y, Bootstrap)" / "… PPK basamak)", par, OIS'e fark, nasıl okunduğu, FX sıfır kupon; grafiğin FX kota çizgisinde 18M) ve TRYSAQ2'si silinmiş kullanıcıda 18M'in OIS kalıp satırın "yok" demesi; geçmişte 18M'in iki kapanıştan (ln DF doğrusal) gelmesi, PPK basamak kullanıcısının geçmiş günlerinin Bootstrap'takiyle aynı, bugünkü satırının kendi ayarında olması; **1Y `TRYSAQ1`** (masa, 18.11.2026): EK_FX'in 1Y kökü `TRYSAQ1`, türü XCCY, tek kuponla iskonto faktörünün FX swap'ın okunuşu olması (sayfanın 1Y düğümünde), kayıtlı günde %39,400 (`TRYSAQ1 BGN`) |
| `test_rvfair.py` | **Her sayfanın FX swap eğrisini adıyla söylemesi** (DİBS RV'nin offshore ICAP eğrisi: `BF:BJ` başlıklarının ipucu ve tablo başlığı - hücreler aynı -; DİBS ASW'nin FX swap ima eğrisi: ASW FX ima sütunları, tablo, grafik ve EK_FX tablosu başlıkları); **DİBS Trading'in adil değerleri** (`tto/rvfair.py`): OIS'te DİBS RV'nin, FX swap'ta DİBS ASW'nin (FX swap ima eğrisi: PV, annuity, uydurulan eğri, fonlama, işlemiş faiz) ASW eğrilerine göre adil getiri ve adil fiyatın sayfaların kendi sütunlarından elle hesapla birebirliği (sabit kuponlu: eğrinin ASW'si sayfanın uydurulmuş ASW'si, getiri nakit akışlarıyla ikiye bölmeyle; bono: eğrinin vadesindeki değeri, `(100 / kirli)^(365 / gün) − 1`), kâğıdın kendi ASW'sinde fiyatın ve getirinin ekranınki olması, ucuz kâğıdın adil fiyatının yüksek olması; her trading kâğıdında değer ya da nedeniyle "–" (TLREF, fiyatı olmayan - DİBS ASW'de de -, uydurulamayan eğri); FX swap ima eğrisinin DİBS RV'nin offshore ICAP eğrisinin uzanmadığı vadeye de uzanması; özetin sütun grupları, başlıklar ve eski sütunların harfleri; FX tarafının DİBS ASW'nin FX swap ima eğrisindeki ASW'si, ucuz / pahalısı ve DİBS RV'nin eşiğiyle sinyali (DİBS RV'nin `BF` / `BH`'si değil); kâğıt kartında aynı değerler; **kâğıt listelerinin düzeni** (valörlerde ve DİBS ASW tablosunda kâğıtsız satırların gösterilmemesi, ASW tablosunun tür ve vade sırası ve başlıkları, her satırın kendi hücresi, DİBS RV'nin değişmemesi, grafiğin sayfanın sırasıyla kalması); **launchpad kutularının aynı satırları bulması** (önceki sürümün kaydettiği kutular: satır numarasıyla - başlık satırı dahil - ve ilk metniyle; ASW tablosunda başlık satırının eskisi gibi kalması ve metinleri, kutuya tür başlığı girmemesi, gizlenen boş satırın düşmesi; valörlerde aynı satırlar; özette eski satır numarası, eski başlık satırı ve üstünde sütun grupları, yeni seçilen satırın kâğıdın ISIN'iyle tutulması) |
| `test_dibsgenel.py` | **DİBS RV · Genel** (`tto/dibsgenel.py`): menüde tek giriş, üç sekme (Genel, RV / ASW hesap tablosu; sıra, adlar, sayfaların kendi başlığı, adresi, tabloları; eski sayfaların, launchpad kutularının açılması; TRY kitabı yokken giriş olmaması); **tablonun her sayısının kaynağı**: grupları, trading listesinin her kâğıdı türüne ve vadesine göre, DİBS RV'nin hücreleri (getiri, ASW, ucuz / pahalı, sinyal, süre, DV01, hedge, C+R, temiz, kalan) birebir, OIS / FX adil değerlerinin DİBS Trading'inkiyle aynılığı, OIS eğrisinin `AA`'sı, TLREF ve fiyatı olmayan kâğıdın nedenli "–"leri, ayarlar; **FX sayılarının DİBS Trading'de, kartta ve Genel'de aynı** olması ve DİBS ASW'nin FX swap ima eğrisindeki `R` / `T`'si olması (DİBS RV'nin `BF`'si değil; 13.09.28'de −140,1); düz eğride par getirinin ve zero faizin formülü; **sıfır kupon uyumunun aynı girdilerle `quantcurve.fam_dibs`'inki** olması (model NS, yalnız sabit kuponlular uydurmada - 13 kâğıt -, 2 bono eğride: uyum dışı, ağırlıksız, farkı ve model getirisiyle; RMSE, LOO RMSE, β, τ, her kâğıdın farkı ve model getirisi; adil fiyatın `quote_bond`'unki, model getirinin `S` − fark olması, ipucunda uydurulan sabit kuponlu ve ölçülen bono sayısı, bononun "uydurmaya girmez, eğriye karşı ölçülür"ü), uyumun saklanması ve getiri değişince τ'ların tutulup β'ların yeniden uydurulması; **trading listesinin eğrisi** (sayfanın şimdiki hâliyle, sabit sayı yok): NS yalnız sabit kuponlulara, β onlarca yüzde (eski Svensson'un yüzlercesi değil), τ1 vadelerin içinde, bonoların fiyatlanıp uydurulmaması (bononun getirisi 10 bp oynayınca β ve adil fiyat aynı, farkı 10 bp), bonoların uydurmadayken olduğundan eğriye uzak olması (masanın kararı), her getiriye birkaç bp'lik gürültüde τ sabitken β'nın bir puandan az oynaması; az kâğıtta uyum olmaması ve nedeni (bonolar sayılmaz: 5 sabit kuponlu + 3 bono yetmez); **ortadaki boş satıra eklenen kâğıdın ISIN'iyle izlenmesi** (diğer kâğıtların sayıları aynı, yeni kâğıt kendi türünde vadesine göre, çıkınca gitmesi); getiri eğrisinin seri ve nokta sayıları (kâğıtlar `F` / `T`'leriyle, OIS `X`, çizgilerin ızgarası), hesap tablosundan gösterilen panellerin sayfalarındakiyle aynı olması; HTTP (`/api/dibs/genel`, 401, nav'da giriş, sayfa modülü, `/api/panels`) |
| `test_kagitfiyat.py` | **Kâğıt Fiyatlama** (`tto/kagitfiyat.py`, `/api/kagit-fiyat`): kovaya göre ağırlıklar (≤1Y %75 OIS, 1–5Y %100 komşu eğri, 5Y+ %75 komşu; eksik tabanın payı diğerine), **komşu eğride kâğıdın kendi kotasının eğriyi oynatmaması** (birini dışarıda bırak; bono kimsenin eğrisini oynatmaz), adilin bir önceki kapanışın farkıyla kurulması ve sonraki-gün hatası, σ ve tabanı, iyi seviyelerin işaretleri (getiri yüksek = ucuz = al), broker / Bloomberg kotalarının adile göre AL / SAT'ı, bilinen cevaplı küçük bir geçmişte geri test, "nasıl fiyatlandı" satırı; replay gününde yapay geçmişle: farkın bugünden önceki son kapanıştan alınması (bugünün kapanışı sayılmaz), adil = taban + fark, tabanların şimdiki değerleri (komşu eğri, OIS Bootstrap), DİBS RV'nin kendi fiyat ↔ getiri hesabı, geçmiş hesabının tarihçe revizyonu başına saklanması, TLREF / TÜFE'nin nedeniyle reddi, kart için tek kâğıt, genişliği yalnız yöneticinin değiştirmesi, menüde Tahvil'in ilk girişi; **Öngörülen**: her modelin (M0–M4) bilinen cevaplı küçük örnekte hesabı, AR(1) / β ve penceresi (yalnız o güne kadarki kapanışlar), OIS forward hareketi, vade kısalması (aynı eğride ufkun valöründe), karar kuralı (%5 yenmeyen yerde M2 ve açık kayıt), ölçülen tablo; replay gününde üç kâğıdın üç ufukta öngörüleni parçalarından yeniden kurulur, ufuk düğmesi (her ufuk kendi valörü ve değeri, varsayılan 1 ay), ufkun valöründeki temiz fiyat ve 1 mn K/Z, modeli kurulamayan kâğıtta M2 ve nedeni; **OIS'e / FX swap'a göre** değerlerin DİBS Trading'in hücreleriyle ve rvfair'le aynılığı; HTTP (401, 400 nedeniyle, 403); **eğri fiyatı** (20.11.2026): masanın listesindeki her sabit kuponlu / bono / kuponsuz kâğıdın satırı (trading listesinde olmayan da), dört etiket (piyasa: DİBS RV'nin bid / ask ortası; eğri + son fark: trading listesinin fiyatsız kâğıdı ve geçmişi olan liste dışı kâğıt, o günün eğrisinde ve OIS'inde ölçülen, kovanın ağırlıklarıyla - trading listesindekinde ayrıntıdaki adil; geçmişi olmayanda **türe göre**: sabit kuponlu eğri, bono / kuponsuz taban + aynı kovada piyasa fiyatlı bono / kuponsuzların medyanı - eğri + akran farkı, kendisi hariç, akran sayısı nasıl satırında -, akran yoksa taban, uyarıyla), **kovanın tabanı** (≤1Y %75 OIS + %25 eğri, 1–5Y eğri, 5Y+ %75 eğri + %25 OIS; OIS yoksa eğri), Eğri sütunu (sabit kuponluda eğri, bonoda taban), fiyatı olan kâğıtta birini dışarıda bırakan eğri, TLREF / TÜFE / FRN'nin sayılıp dışarıda kalması, kartta tek kâğıdın eğri satırı (ana tablodakiyle aynı akranlarla), yüklemenin eğri fiyatları ve kısa adları; **tipik hata**: her eğri fiyatında o kuralın bugünkü piyasa fiyatlı aynı kova ve türdeki kâğıtlarda medyan sapması ("tipik hata ±X bp", 2'den az kâğıtta "ölçülemedi"; iki bonoda \|s1 − s2\|), **doğrulama yardımcısı**: kâğıdın kendi kotası kendi tahminini oynatmaz, akranlarınınkini oynatır; kural, kova ve türe göre hatalar; **son fark** (20.11.2026): en yeni nokta (kapanış, ihale, son işlem, kayıtlı kapanış; aynı gün son işlem > ihale > kapanış, söylenir), noktanın valöründe getirisi (ihale: bonoda basit getiri, sabit kuponluda temiz fiyat; son işlem: bono fiyatı ya da getiri gibi duran rakam), bugünkü ihale şimdiki eğriye, önceki günün noktası o günün eğrisine göre, adil aynı noktadan (bugünden önceki), etiket ve yaş, yüklemenin "eğri fiyatı (son fark, …)" satırı; **günlük kapanış kaydı**: 17:35'ten sonra günde bir kez, gün dönünce önceki gün, hafta sonu yok, Bloomberg'e istek yok; **ana tablonun Öngörülen / OIS'e / FX swap'a göre sütunları** (masa: "Göster"): trading listesindeki kâğıdın aynı cevaptaki ayrıntı değerleri (her ufukta öngörülen, rvfair'in iki ASW eğrisindeki değerleri - DİBS Trading'inkiler), liste dışı kâğıtta "—" ve nedeni |
| `test_fiyatyukleme.py` | **Kâğıt Fiyat Yükleme** (`tto/fiyatyukleme.py`, `/api/fiyat-yukleme*`): ihale metninin okunması (her satır türü, yok sayılan satırlar, gg/aa/yy, okunamayan tarih / valör), vade + etiketle eşleşme (etiketsiz: sabit kuponlu, yoksa bono / kuponsuz; zc, TLREF, cpi), birden çok ya da hiç kâğıt bulunan satırın tanınmaması ve yakın vadeli kâğıtlar, bir kez tanıtılanın sonra hep (masa için, gg/aa/yy ile de) tanınması ve silinmesi, `.t1`'in `.t2`'ye üstünlüğü; bononun basit getirisinden t0 fiyatına ve geri, sabit kuponlunun T+1 fiyatından getirisine ve t0 fiyatına (rvfair'in Newton'u ve quantcurve'ün birikmiş faiziyle); spread'ler (varsayılan, kâğıdın kendi, skew, TLREF / TÜFE fiyat spread'i); bononun son işleminin fiyat ya da getiri okunuşu; txt satırları karakteri karakterine (getiri / fiyat ve 0'lar, üç ondalık, CRLF, ASCII); replay gününde: **masanın listesi** (25.11.2026: kalıcı, iki kullanıcıda aynı - birinin eklediği, çıkardığı, spread'i, varsayılanı, sabit fiyatı ötekinin de -, mod kişinin kendisinin, değişiklikte yeni nesil ve yeni sürüm, sürümüyle sorana "değişmedi", ayarda bir hata olunca hiçbirinin kaydedilmemesi; kullanıcıların eski listelerinden bir kez kurulması: herkesin kâğıtları ve sabit fiyatları, farklı ayarlı kâğıtta ve varsayılanlarda en yeni kullanıcınınki, farklı sabit fiyatta en son girilen, mod ve metnin kişide kalması, eski kayıtların değişmemesi, sonradan çıkarılanın geri gelmemesi; katalogda olmayanın Bloomberg'siz eklenmemesi, Bloomberg'le masanın yolundan girmesi), İhale'nin Hesapla'sı ve değerlerin masa için saklanması (aynı gün yeniden yapıştırınca değişmesi), dosya, ikinci indirme ve günün kaydı (kişi başına: aynı listeden ötekinin aynı dosyası, kendi kaydı), düzenlenen hücrenin diğer yarısı; **BBG**: trading listesinin DİBS RV'den istek yapılmadan okunması, listede olmayanın Tüm Kâğıtlar'daki adıyla bir kez sorulması (2 alan, kâğıt başına 2 hit) ve 5 dakika yeniden sorulmaması, cevap gelmeyince nedeni; bugün olmayan son işlemde son ihale + tahvil eğrisinin hareketi (yapay kapanışlarla; hareket, eğrilerin kendisiyle de doğrudan) ya da eğri yoksa TRY OIS'in sıfır faiz değişimi, fiyatla kote edilende son ihale fiyatı, kayıtlı ihale yoksa nedeni; **Eurobond**: sokak kuralının fiyat ↔ getirisi (Excel'in PRICE / YIELD örnekleri, elle hesaplanmış 30/360 yarıyıllık ve ACT/ACT yıllık örnek, son dönemde basit faiz, 31'inde gün sayımları), Bloomberg'in mid'ine çapa (mid'in birebir aynı çıkması, getiri spread'inden fiyatlar), Bloomberg bilgilerinden kaydın kurulması (eksik gün sayımı / valör gecikmesi, TL, değişken kuponlu, tanınmayan kâğıt), bilgilerin ISIN başına bir kez sorulması ve DİBS kataloğuna girmemesi, Bloomberg'siz eklenmemesi; iki modda da PX_MID ve YLD_YTM_MID'den fiyatlanması (kâğıt başına 2 hit, 5 dakika önbellek), PX_MID boşken PX_BID / PX_ASK'ın ortası, valörün USD / EUR takvimiyle, çapa farkının 0,05'i aşınca uyarısı, kâğıdın kendi getiri spread'i, düzenlenen hücrenin çapalı çevrimi, txt satırı (temiz fiyat, getiriler 0); sağlayıcının tek seferlik isteğinin sayılması, günlük sınırı ve hiçbir yerde tutulmaması (süreç içinde ve yardımcı süreçte); **Sabit fiyat**: masanın sabit bid / ask'inin eklenmesi, değişmesi, çıkarılması ve kalması (ötekinde de aynı, ötekinin değiştirmesi), birimin türe göre (bono / kuponsuz getiri, diğerleri temiz fiyat; virgüllü okunuş), iki modda da hesaplananın yerine olduğu gibi durması (listede de olanın notu, diğer birimin bilgi için çevrimi), BBG'de trading listesi dışındaki sabit kâğıda ve Eurobond'a Bloomberg isteği yapılmaması, düzenlemenin kayıtlı değeri değiştirmemesi, Sabitle, txt satırları, yalnız sabit kâğıtla metinsiz İhale; **Excel'den yapıştırma**: masanın sayfasının alt bloğu birebir, üst bloğun C:F ve C:H satırları (getiri ve stok atlanır), virgüllü ondalık, iki işaretli hücre, okunamayan satırın nedeni, başlıkların yok sayılması, katalogsuz döviz DİBS ("döviz DİBS", vadesi ISIN'den), `TRB…`'nin getiriyle, yeniden yapıştırınca güncellenme, `TRT191127F19` / `TRT030327F17` satırları; HTTP (401, Türkçe nedenli 400, 404, dosyanın adı ve baytları; sabit fiyatın 401 / 400'ü; `?rev=` ile "değişmedi" ve değişince yeni sürüm); **eğri fiyatı**: fiyatı olmayan getirili kâğıt (ihale metninde yok / işlemi ve ihalesi yok) iki modda da Kâğıt Fiyatlama'nın eğri fiyatıyla, kendi spreadleriyle, "eğri fiyatı" (sabit kuponlu) / "eğri fiyatı (akran farkı)" (kuponsuz) yazarak ("(son fark)" kendi farkında), tipik hatasıyla; fiyatla kote edilen değişmez, sabit fiyat önce gelir; dosyada; BBG'de Bloomberg'in **son işlem yanıtları kâğıt başına saklanır** (daha eski bir yanıt değiştirmez) ve ihale metninde olmayan kâğıdın eğri fiyatı onunla "eğri fiyatı (son fark, son işlem gg.aa)" olur; **Mid / Bid/Ask** (23.11.2026): seçimin listeyle (masanın) saklanması, ISIN'iyle liste değişince (satır kayınca) de kalması, Tümü, Mid'e dönünce kaydın eskisi gibi olması; Mid'in önceki gibi fiyatlaması ve yeni istek yapmaması; DİBS RV'deki kâğıdın taraflarının DİBS RV'nin bid / ask'ından (istek yok; spread 0 ise ekrandaki), listede olmayan DİBS'in ve Eurobond'un `PX_BID` / `PX_ASK`'tan (yalnız onlara, kâğıt başına 2 hit, özetin hit'lerinde, 5 dakika saklanır; Eurobond'da çapalı sokak kuralıyla); bid = ask olanın ve DİBS RV'de "–" olanın mid'den, nedenini söyleyerek |
| `test_rowkeys.py` | **Kâğıdın satırındaki değerler kâğıdındır** (`tto/rowkeys.py`): değerlerin nereye gittiği (yer değiştiren, üzerine yazılan, çıkan, iki kez listelenen, kâğıtsız satıra giren kâğıt); masanın listesi yeniden sıralanıp yapıştırılınca herkesin manuel fiyatı, kuponu, reposu, "Elle değer"i, masanın kaynağı ve senaryoların kâğıtla taşınması, formülün değer olarak taşınması, aynı yapıştırmada yazılanın yazıldığı satıra gitmesi, boşalan satırda dosyanın kaynağının da kalmaması, uyarının metni ve listenin kaydı; ISIN'in üzerine başka ISIN yazılınca eski kâğıdın her şeyinin - senaryolarda da, DİBS ASW listesindeki satırıyla - gitmesi, yeni kâğıdın boş kaynakla başlaması, kâğıtsız satıra yazılanın ★ ile giren kâğıtla silinmesi; ☆ ile DİBS RV ve ASW'den çıkanın değerleri, ortak sıfırlamayla çıkan kâğıt; liste değiştikten sonra yüklenen senaryonun değeri kâğıdın yeni satırına koyması; **Eurobond Kotaları** (kişisel liste: "Elle değer" kâğıtla, kendi bid'i satırla; başkasının listesi; senaryonun kendi listesiyle gelmesi); **önceki sürümün veritabanı** (her şeyin yerinde kalması, satırların bir kez olduğu gibi alınması, sonra taşınması; kapalıyken değişen listenin açılışta taşınması); **VİOP altın kontratı tablodan çıkınca** kendi VİOP fiyatının herkesten ve senaryolardan silinmesi, sütunun öteki girdilerinin kalması (başka sütuna geçen kontratın fiyatı onunla gider: `test_xau_twoway.py`) |
| `test_blotter_entry.py` | **Günlük İşlemler girişi**: tutarın **karşı parada** yazılması (USDTRY / EURTRY'de TRY, EURUSD'de USD: döviz tutarı işlemin kendi forward'ından kuruşuna - yende bütün yen -, yazılan taraf ve tutarı kayıtta; fiyat yeniden yazılınca yalnızca öbür taraf değişir; işlem her yerde döviz işlemi: liste, maliyet, risk, Excel sayfası; iki tutar birden, sıfır, okunmayan ya da çevrilemeyecek kadar küçük tutar; gün sonu dosyasında girilen tutar ve döviz), **şablonlar** (kişisel: başkası görmez, değiştiremez, silemez; yeniden adlandırma ve içerik değiştirme; masa şablonunu yalnız yönetici yayımlar, herkes görür, kişisel şablonla aynı ad olabilir, kullanıcının masa şablonunu değiştirememesi; ad büyük / küçük harften ve Türkçe i'den bağımsız tek; şablonun yalnızca formun aldığını tutması - ürün, yön, parite, fiyatlama, tutar, strateji / yön, vadeler, FRA ayları, MPC toplantıları, büyüklük -; blotter'la gelmesi ve alanlarının formun fiyatladığı işlem olması), **Excel'den yapıştırma** (sayfanın kendi başlıkları, İngilizce ve dövizli başlıklar, başlıksız sayfa sırası, sütun eşlemesi, tırnaklı hücre, satır numaraları, iki sütunda aynı alan, eksik sütun; satırın formun denetimi ve fiyatıyla okunması - Türkçe / İngilizce sayı, yön ve fiyatlama sözcükleri, satır satır hata -; OIS - vadeli, MPC, nominal - ve tahvil satırları; geçerli satırların tek işlemde kaydı, yazarken bir hata olunca hiçbiri, önizlemeden sonra geçersizleşen satırda 409 ve hiçbiri), **önceki sürümün veritabanı** (işlemleri, maliyeti, riski ve gün sonu dosyası aynen; yeni tablo; eski kayıtların değişmemesi), HTTP uçları |
| `test_blotter_edit.py` | **Düzenle**: değiştirilmeyen oynamaz - **yalnızca karşı taraf / not** (RET eğrisi işlemden sonra kaymışken forward'ın kuru, faizi, tutarları, DV01'i aynı; pencereden gelen `fields` de; geçmiş günün işleminde izinli, seviye / nominal / yön / vade değişikliği reddedilir, geçmiş valörlü forward'ın notu fiyatlanmadan değişir), **forward tutarı / yönü** (kur, TRY faizi, spot, iskonto faktörleri aynı; tutarlar ve DV01 ölçeklenir, yönle işaret döner), **valör / fiyatlama / yazılan fiyat** (önizlemede kaydetmeden önce "bugünkü piyasa" ve nedeni; yeni işlemin fiyatı, denetim kaydında `today` ve neden), **OIS seviyesi** (eğri 20 bp kaymışken mid'e göre değer işlem anının kayıtlı mid'ine göre, nominal ve DV01 aynı; DV01 yazılan büyüklüğün nominali işlemin kendi eğrisinden; yön değişince bugünkü piyasa), outright (seviye, nominal, karşı taraf), **FRA paketi** (seviye ve nominal: iki bacak, aynı id'ler, başlangıç bacağının geri gelen oranının değişmemesi, bitiş oranının işlem anının annuity'leriyle, sayfanın iki satırı, vade bazında maliyet), DV01 ile boyutlanmış spread'in bacaklarının kalması, tahvil (nominal başına DV01); kimin / ne zaman girdiğinin ve gününün kalması, **önceki değerlerin** (`edits`: nasıl fiyatlandığıyla) bacak bacak saklanması ve son N'in tutulması, aynı işlem yeniden gönderilince hiçbir şeyin yazılmaması; ürün / strateji / bacak sayısı değişikliğinin, olmayan ya da silinmiş işlemin, oturumsuz isteğin reddi; paketin **tek işlemde** değişmesi; düzenlemenin kurallarının `ois_legs`'inkiyle aynı olması (mid'e göre maliyet, DV01'i, aynı seviyede yeniden kurulan bacaklar - sekiz strateji / yön); **Chat ↔ Günlük İşlemler** eşleşmelerinin düzenlemeden sonra durması; gün sonu arşivinin OIS tablosunda **Mid'e göre (bp / $)**; HTTP (`POST /api/blotter/trade/<id>`, `…/preview`) |
| `test_blotter_copy.py` | **Benzerini gir / Ters işlem**: kırık vadeli TRY OIS'in Fiyatlama'nın hesabıyla fiyatlanması (mid ve annuity Fiyatlama'nın aynısı, nominal OIS_MAIN'in kuralıyla, kuponlar vadeden geriye - kısa dönem başta -, tatile düşen tarihin iş gününe kayması, spot'tan önceki tarihin reddi), kırık vadeli spread ve iki tarih arası FRA (iki spot swap, tek nominal, Fiyatlama'nın FRA'sıyla aynı mid; Spot'tan tek bacak); bugünün işlemleri (forward: karşı parada girilen tutarın benzerinde aynı, tersinde döviz tutarı; fly, DV01'le boyutlanmış spread, FRA, tahvil; paketin düğmesi ilk bacağında); geçmiş günün işlemleri (1Y outright'ın tersi o günün spot'undan vadesine kırık vade, kaydı - Excel sayfasında iki ana vadeye gün oranında, maliyet tablosunda kendi satırı - ve eski işlemin değişmemesi; spread'in iki bacağı; başlamamış FRA kendi tarihleriyle, başlamış FRA spot'tan bitişine, vadesi gelmiş FRA'nın tersi yok; forward'ın vadesi `6M` olarak, valörü gelmişse tersi yok ve benzerinde aynı gün sayısı; MPC'nin başlangıcı geçince Spot'tan, dönemi bitince ikisi de yok); form kapalıyken (geçmiş tek gün) düğme yok ve hiçbir kaydın değişmemesi; forward'ın vadesinin okunuşu |
| `test_sources_and_desk.py` | **Fiyat kaynağı sırası**: canlı hücrelerin sıradaki ilk fiyatlı kaynağı alması (offshore'da iki taraflı kaynak, tek taraflı alınmaz), kayıtlı veride sayfaların dosyanın değerinde kalması, sıranın herkes için değişmesi, saklanması, tarihçe tanımlarının izlemesi, hatalı kod, HTTP; **yedek kaynağın yalnızca boş günleri hareketiyle doldurması**; tanımsız ticker açıklamaları; **ASW'nin FX swap eğrisiyle** fiyatlanması ve **FX swap eğrisine göre ASW grafiği** (noktalar tablonun ASW FX sütunu, etiketler ve x'ler OIS grafiğininki, kesik çizgi FX hesabının `a + b·t + c·t²`'si) ile FX swap ima eğrisi – OIS çizgi grafiği: düz çizgilerde iki eğrinin **sıfır kupon faizi** (OIS sayfanın kendi düğümlerinden; FX, ASW FX hesabının aynı düğümlerinden ve fiyatlı vadede FX faizinin kendi kuralıyla verdiği iskonto faktöründen - 18M'de XCCY eğrisinden hesaplanan noktanınkinden), kesik çizgilerde kotalar; `EK_FX` tablosunun yeni sütunları (okunuş, gün, OIS sıfır kupon; FX hesabından FX sıfır kupon ve sayfaya giden par), FX fiyatı hiç yokken FX tarafının - sıfır kupon ve kota çizgileri - boş kalması; **Forward fiyatları**: USDTRY / EURTRY tablolarının Forward sayfasıyla birebirliği (günlük puanlar dahil), yazılan faizin iki pariteyi yalnız yazana yeniden fiyatlaması, **Elle** satırı (eğri + mid ya da spread, genişlik), **serbest forward** (spot, major, minor eğrilerden; ileri başlangıç; EURTRY; eğrinin bittiği yerde boş; üzerine yazma), **vadelere göre simple zero** tablosu, eski düzende yazılmış değerin silinmesi; altın serbest sütunu; **z-score**; **tahta sıfırlama / geri alma, işaretlenen satırların silinmesi**; bugünü içeren aralıkta işlem girişi; **FX swap puanlarının okunuşu ve ima TRY faizi**; **OIS Kontrol gün sayıları masa takvimiyle** (düğüm tarihinden sayılan gün, hafta içi Bloomberg'le aynı) |
| `test_fxvol.py` | FX smile'ları: normal dağılım ve tersi, Black, piyasanın deltaları (forward / spot, primli) ve strike'ları – primli call deltasının azalan kolu –, delta-neutral straddle, market strangle; **SVI'nin, kotaları üreten smile'ı geri bulması**, G10 smile'ını arbitrajsız ve kotasına oturtması, USDTRY benzeri smile'da arbitrajsız kalması (ATM ve 25D kotalarda < 0,1 vol), **SABR'ın USDTRY skew'unu tutamaması** (neden SVI), Vanna-Volga'nın pillar'larından geçmesi, eksik kotalar; dağılım: düz smile'da lognormal yasa, kuantil ↔ CDF, ortalama = forward, yoğunluğun call'un ikinci türeviyle aynılığı; **en olası**: lognormal yasada tepenin kapalı formülle aynılığı, en dar aralıkların kütlesi, iki ucundaki eşit yoğunluk ve yüzdelik aralıktan darlığı, USDTRY benzeri skew'de forward'ın altına, G10 put skew'ünde üstüne kayması |
| `test_fx.py` | Spot / FX ve FX Vol İzleme: ticker adları (Bloomberg'deki gibi), paritelerin kuralları, **USDTRY forward'ının Forward sayfasının "Serbest forward" listesindeki offshore forward'ıyla birebirliği** (her vade), yazılan spotun yalnız sahibini etkilemesi, puandan forward ve TRY çaprazının USD bacaklarından, teslim tarihleri; yüzey (her vadede arbitrajsız, ortalama = forward, artan kuantiller, skew), otomatik seviyeler, SABR / geçersiz model, EURUSD'de spot delta ve iskonto, **kendi kotası** (yalnız sahibine, boşla Bloomberg'e dönüş, hatalı girdiler), pariteler tablosu, **Makro bloğunun istatistikleri** (Δ1G / 1H / 1A, z 3A, pencere z'si, yüzdelik, aralık, boş günün doldurulması), gerçekleşen vol, yuvarlak seviyeler, izleme (tarihçeyle, eklenen parite ve ticker, ortak fiyat kaynağı), parite ayrıntısı (bugün / 1H / 1A önce; RR / BF'siz gün smile'sız; bekleyen kotaların sayılıp adlandırılması, forward'sız da aynı smile), tarihçenin bir yıl geriye sonra son on gün istenmesi, **spot oynayınca smile'ın yeniden kalibre edilmeden taşınması**, her vadenin en olası seviyesi ve en dar aralıkları (spot oynayınca yalnız ölçeklenir), `check-fx`, HTTP uçları |
| `test_series_charts.py` | **Tıkla → grafik**: Gün Sonu Matrisi'nin satırının, izleme kaleminin ve ısı haritası noktasının arkasındaki kapanışlar (`/api/history/closes`, `/api/watch/history`) ve tarayıcının onları çizdiği istatistikler (`seriesstats.js`, Node.js ile) - yanındaki tablonun sayılarıyla birebir (FX izleme: `tto.fx.stats`, izleme listesi: `Watch.zinfo`); Node.js yoksa atlanır |
| `test_volcarry.py` | Realized vol: yazılanın okunuşu, enstrüman seviyesinin günlere göre kuruluşu (yalnızca bütün bacakların kapandığı günler), **vol = günlük değişimlerin standart sapması** (elle hesapla aynı; pencereler, dolmayan pencere, en az beş değişim, kayan vol), forward'ın par eğrisinden bootstrap'i (düz eğri, sınırlar, Excel'in forward'ına 5 bp içinde yakınlık), sayfa satırı; tarihçeye yazılmış kapanışlarla servis (outright / spread / fly / FRA / cross-currency, eksik günü olan vade, geçmişi olmayan vade, pencere seçimi), **carry / vol** (C & R sayfasının 34 fly'ı ve 120 spread'i, sayfanın kendi C+R değerleri, ufukların iş günü sayısı, oran = C+R ÷ (σ·√gün)), **carry patikası** (S1'in Excel'in kaydettiği C & R değerlerini birebir vermesi, Bootstrap'ta ufku vadeye eşit OIS'in carry'sinin ~0 olması, patikadan bağımsız roll, kullanıcıya özel seçim ve ufuklar, hatalı değerler), **Listem** (yazılan OIS vadesi / spread / fly'ın carry'si, FRA ve listede olmayan vade için açıklama), **Spread Geçmişi** (offshore − OIS: iki eğrinin ortak günlerinden seri, canlı kotayla bugünkü seviye, 1G / 1H / 1A değişim, 20 / 60 / 250 kapanışta ortalama, σ, z, aralık, yüzdelik; canlı kota yokken son kapanış; VİOP − OIS kontratları), HTTP uçları |
| `test_charts.py` | Grafik tanımlarının Excel'den alınışı (renk, çizgi, işaretçi, eksen sınırları, tarih ekseni, bid–ask kutuları), değerlerin Excel kuralıyla çizime verilişi (boşluk, `#N/A`, metin) ve XY grafikleri (nokta etiketleri, sayı / tarih ekseni) |
| `test_auction.py` | **Hazine İhalesi** (canlı-benzeri bir Bloomberg'le): temiz fiyattan, basit ve bileşik getiriden kirli fiyat (bağımsız bir BIST getiri hesabıyla aynı; 3 haneye yuvarlama, tutar, iki girdide temizin önceliği), nominal ağırlıklı ortalama ve getirisi; açıklanan asgari / ortalama / azami fiyatla gerçekleşen / asgari fiyatta / gerçekleşmeyen teklifler, ortalamaya fark, aralıktaki yer, elle yazılan gerçekleşen nominal, gerçekleşen ortalama ve getirisi; **kısaltmayla yazılan nominal** (`35m`, `2,5 mn`, `500k`; yazarak ve yapıştırarak; anlaşılmayan tutar reddedilir, toplamı boşaltmaz); bono, TLREF ve FRN (getiri yok; FRN kendi adıyla) ve TÜFE (reel getiri, endeks oranıyla tutar); **uzun ilk kuponlu** yeni ihraçta kalan kuponların takvim dönemiyle (364 / frekans gün) sayılması; **birikmiş faizin yalnız Bloomberg'den, valörle** istenmesi (kâğıdın kendi valörü, kupon gününe denk gelen valör, Bloomberg'in yanıt vermediği valörde fiyat çıkmaması, tanınmayan ISIN); sayfa tanımı ve kayıtlı veri modu |
| `test_extras.py` | Dashboard'un ekledikleri: forward kotasyon matrisi (yedi eğri Masa bloğuyla aynı, bid / ask ayrı spread, puan → spread tersi, iki yönlü hücrelerle girdi sayısı ve J5'in formülü - iki yönlüsü `test_fwd_twoway.py`'de; **piyasa spread'i**: her vadede offshore ima − OIS, seçilince spread'in yerine geçmesi, EURTRY'nin seçimi izlemesi; **EURTRY matrisi**: aynı tarihte USDTRY ile aynı OIS faizi, EUR faizi ve gününün Masa'nın EURTRY hücreleriyle aynılığı, eğri ve spread'lerin USDTRY'yi izlemesi ve ayrılması, kendi spot'u, puandan spread; **faiz → spread** (USDTRY ve EURTRY'nin kendi gün sayısıyla: yazılan TRY faizinin OIS'e göre spread'i, matrisin formülleriyle puan, forward, P/gün ve RET farkı; bulunan spread matrise yazılınca aynı puan ve forward, 1e-9), **toplu forward'ın tersi** (satırın kendi USDTRY / EURTRY fwd'si yapıştırılınca ima TRY % = manuel faiz ya da RET mid), eklemelerin listesi (tahvil carry'nin fiyattan reposu ve implied move'un hareketten vol'ü dahil: başka bir kitapta dışarıda kalmaları), yeni girdilerin hiç girdi olmamış hücrelerde olması (emekli girdiler dahil); **puandan faize**: FS'in Manuel satırının kendi puanı geri yazılınca aynı TRY fwd-fwd % - USDTRY ve EURTRY, USD faizi eğriden ve yazılı - ve OIS / offshore / RET mid'e bp, çapraz forward'ın kendi forward'ı geri yazılınca manuel TRY % - USD ve EUR kendi günüyle, başka döviz Bloomberg'siz boş), altın (`spot·(1+swap·g/360)` kapalı formülü, USD faizinin hesaba girmediği, faiz interpolasyonu, kaynak seçimi, `XAUSR…` ticker'ları ve ticker eki, canlıda `BFXFORWARD`'sız çalışma, VİOP / Forward hücrelerinin beslenmesi, "belli faizle fiyat"; **VİOP XAUTRY hesaplayıcısında her girdinin elle yazılması**: fiyattan ima TRY ve ima altın swap faizi, ima faizle fiyatın geri gelmesi, başka tarih, serbest sütun, silince piyasaya dönüş; **VİOP geçmiş serileri**: canlı-benzeri bir sağlayıcının geçmişiyle ima faiz / baz / OIS'in elle hesapla ve aynı günlerde sayfanın kendi "Baz" değeriyle aynılığı, fiyatı olmayan günün çizilmemesi, grafik verisi, kontrat seçimi, kendi geçmiş penceresi – sayfanın 20 günlük istatistik penceresi değişmeden), bir ekin dosyaya uymadığında dışarıda bırakılması (DİBS RV'nin bid'i başka yazılınca canlı kota ekinin; ASW sayfasının eğri düzeni değişince `EK_FX`'in), `EK_FX`'in formülleri (gün, sıfır kupon, FX faizinin okunuşu; 18M'in ticker'sız, hesaplanan satırı - B girdi değil, D / G / H `=NA()`), Borsa O/N karşılıkları ve örnek kotaların RET'e eşitliği, **Borsa'da yalnızca miktarı olan kotanın listelenmesi** (miktarı 0 / eski fiyatlı vadeler, tek taraflı kota, hata hücresi kalmaması), ASW ↔ DİBS RV |
| `test_borsa_spread.py` | **Borsa Swap'ın OIS ve offshore mid spread'leri** (`tto/borsaspread.py`): elle kurulan bir eğride iki tarih arası zero faizin elle hesapla aynılığı (düğümde, düğümler arasında ln DF doğrusal, son düğümden sonra son eğimle; sayısı olmayan düğümün yalnız kendi aralıklarını boşaltması); **T+0'ın spot öncesi günleri** (bir gün, hafta sonu üç gün, ikisi de spot öncesi tarih, spot'a kadar O/N'un kendisi; O/N yoksa spot öncesine faiz yok); **1A'dan kısa satırlar**: 1W ve 2W noktalarının eğrinin 1A düğümünden önce girmesi (kendi günlerinde tam, arada ln DF doğrusal, 1A'dan sonrası değişmeden; sayısı olmayan, 1A'dan sonra ya da aynı güne düşen nokta girmez) ve sayfada T+1 7 / 14 günün ORANLAR'ın 1W / 2W "OIS zero"su olması - Bootstrap eğrisi ve Masa'nın satırı aynı kalırken -, offshore'da 2W düğümünün ICAP 2W'si; sayfada iki tabloda altı sütun ve her satırda iki mid, **spread = BID % / ASK % − mid zero** (bp; mid'in üstü +, altı −, işaretin rengiyle), tek taraflı kotada yalnız o tarafın spread'i; **ORANLAR'la aynılık** (T+1 30 gün = 1A "OIS zero" ve ICAP; T+0 1 gün = ON satırı: TLREF 365 → 360 ve offshore O/N mid); 1A'dan sonra herhangi iki tarih arasında Masa'nın 'Tarih arası faiz' Bootstrap satırı ve kırık vade bloğunun offshore basit faiziyle aynılık; kullanıcının kendi OIS kotasının yalnız kendi sayfasını değiştirmesi; kotasız satırın boş kalması, başka tablonun ve başlığı kaymış tablonun dokunulmaması, okunamayan eğrinin nedenini söylemesi; **T+1 valörü**: dosyanın formülü yerine Borsa kitabındaki TRY tatil kopyasından sayılması (`bu!Q9:Q54`, formülü olmayan son satır dahil; T+0'ın son satırı da), T+1 formülü farklı dosyada ekin dışarıda kalması, kopyanın açılışta TRY kitabının listesi olması, **eklenen bir TRY tatilinde** (04.11.2026) OIS spot'u ile T+1 gününün birlikte kayması, gösterilen valörün de, T+1 satırlarının spot öncesi taşımasız, T+0'ın iki günlük O/N'la başlaması; kopyanın kendi saklananları silinse de yeniden başlatmada aynı gün; TRY listesi sıfırlanınca ya da Motor'a tek gün yazılınca kopyanın ve T+1 gününün hemen izlemesi |
| `test_retfair.py` | **Adil değer RET** (`tto/retfair.py`) ve **masanın vade başına akışı** (`tto/retflow.py`): her tabanın vade başına mid'i kendi makinesine karşı (OIS / offshore: Borsa Swap spread'lerinin eğrileriyle RET'in kendi tarihleri arası, ON spot'tan önceki gün; düğümlerde ORANLAR'ın "OIS zero" / "ICAP"ıyla aynılık; VİOP: VİOP sayfasının kontrat ima faizlerinin bid–ask ortası, tarihle doğrusal, ilk ve son kontratın dışında yok); **karma** (ağırlıklar, 100 etmeyen ağırlık, 0 ağırlık, eksik taban, varsayılan karma); **spread ve genişlik**, **5 bp ızgara** (yarım adım yukarı); **2 bp histerezis** (taban 3 bp oynayıp adımı geçince değişir, 1 bp oynayınca değişmez, gidip gelmede oynamaz, 2 bp'nin ötesinde geri döner); "Yayınlanandan al" ile Şimdiki = Yayınlanan, taban ve spread değişince "RET güncellemesi var: 1M, 2M" (sayfada ve durumda); toplu spread / kaydırma, hatalı vade / taban / sayı; **Kopyala ve yayınla** (RET hücreleri, Masa ORANLAR'ın RET bid / ask'ı, RET geçmişi, sarı noktanın kalkması, ask'ı bid'in altındaki eğrinin reddi); **Neredeyim** sayıları ve taban değişirse RET; dikilmiş işlemlerden **akış önerileri**: hacim, normal ve katı, maliyet, **masanın örneği kelimesi kelimesine**, öneri büyüklüğü ve komşu vade (yukarıda bir sonraki, aşağıda bir önceki), **maliyet + marjın altına inmeme** (kısılan ve düşen öneri, komşunun kendi maliyeti), aynı gün kabul edilenin yeniden önerilmemesi; **Broker Chat, OIS ve tahvilden hiçbir şey**; **akış ayarı** (spread'den ayrı, spread'e ve genişliğe dokunmaz, kaldırılana kadar kalır, tek tıkla kalkar); **Ekstra ayarlar yalnızca yöneticide** (403; değerlerin sınırları, 5'in katı olmayan genişliğin reddi); **eski veritabanı** (yeni tablo yokken RET'i ve geçmişiyle açılır, 5'in katı olmayan genişlik söylenir, yeniden başlatmada ayarlar kalır); vadelerin RET tablosunda etiketle bulunması; **Pozisyon ve maliyet** (bugün ve son günler: TRY satış / alış, net, maliyet, RET mid'ine ve OIS mid'ine göre K/Z, bölünen işlem, geriye bakışın dışındaki işlem); **Tabana göre** (elle hesaplanmış Bid / Ask / Mid örnekleri: ızgara, yarım adım, adımı olmayan yarım genişlik, formül, 'Neredeyim'in yayınlanan tarafı, her tabanla RET; **histerezisin kuralın tarafında** - Bid'de bid, Ask'ta ask -; **varsayılan Mid'in eski kuralla sayı sayı aynılığı** (300 rastgele eğri, spread, akış, genişlik, histerezis, gösterilen değer: Şimdiki, ham değerler, formül, Neredeyim, tabanla RET); satırdan ve çoktan seçim, günlükte kim / ne, her kuralla **Yayınlanandan al** (Şimdiki = Yayınlanan), kaydırmanın kuralın tarafını kaydırması, Mid'e dönüşte saklanan bir şey kalmaması, yayınlanan RET'in değişmemesi); **RET geçmişinin vade başına değişikliği** (Kaydet, aynı eğri: 'değişen vade yok', sayfaya yapıştırılan blok, Kopyala ve yayınla'nın kaynağı ve senaryosu; yayın yanıtında kayan vadeler ve bp; bir float'ın son hanesinin değişiklik sayılmaması); **Senaryo**: OIS tabanının Masa'nın 'Tarih arası faiz' bloğuyla aynı tarihlerde birebir aynılığı (S1 / S2 / S3, 3M / 6M / 1Y), karşılaştırma tablosu, ilk toplantıdan önce bitenin senaryodan bağımsızlığı, histerezissiz ızgara; **adımsız senaryo = referans** (VİOP ve offshore tabanı piyasanınkiyle birebir, OIS tabanı ima yol eğrisi - bootstrap değil, ON piyasanınki gibi O/N ile; S1 = S2 = S3 = referans; bir toplantıya adım yazılınca ayrılmaları); **bir kullanıcının adımları yalnız kendi görünümünü değiştirir** (diğerinin üç senaryosu tek eğri, masanın piyasa görünümü ve üst şerit aynı); seçimin kişisel ve kodla saklanması, **adın SENARYOLAR'dan değişince izlemesi** (sayılar aynı, başkasının adı kendi); **kayıtlı Senaryo seti** (sıfırlayınca referans, yükleyince aynı sayılar); **PPK takvimi değişince** adımların toplantısıyla taşınması, senaryonun yeni Masa oranına eşitliği, takvim geri gelince aynı sayılar; **VİOP kontratı dönünce senaryonun OIS kısmının değişmemesi** (taban farkı aynı, yalnız VİOP'un piyasa tabanı), karma tabanda her parçanın senaryo değeri, senaryo değeri olmayan vade; yeni HTTP uçları (görünüm, tabana göre) |
| `test_masa_offshore.py` | **Masa: offshore 2Y sonrası zero ve O/N** (masa, 26.11.2026): ORANLAR'ın 3Y–10Y ICAP'ı XCCY bootstrap'ının, OIS zero'su Motor'un düğümünün zero'su - iskonto faktörü ve günle elle hesapla ve eğrilerin düğüm tablolarıyla (offshore `Forward!AK:AM`, OIS'in O/N bloğundaki ln DF'i) aynılık, iki tarafın kendi günü (USDTRY spot'undan kotanın vadesine / OIS spot'undan düğüme), ICAP − OIS, RET ve VİOP'un boş kalması; **O/N EŞLENİKLERİ**'nin aynı iskonto faktörlerinden olması (her eğride 1 + zero·g/360 = (1 + O/N/360)^g); **masanın durumu**: TRYSAQ6–10 fiyatlıyken 7Y / 10Y'nin zero'su, bp'si ve O/N'unun dolması, O/N grafiğinde de, OIS'in değişmemesi; **fiyatı olmayan XCCY vadesi** (TRYSAQ3 silinince 3Y–10Y) boş kalır, OIS'ten doldurulmaz, 2Y ve OIS sütunları aynı kalır; **PPK basamak**: OIS zero'nun 2Y gibi kullanıcının eğrisini izlemesi, ICAP'ın değişmemesi, Bootstrap'ın kıpırdamaması; dosya orada değişmişse (7Y ICAP'ı kendi formülü) ekin dışarıda kalıp dosyanınkini bırakması; **başka hiçbir şeyin değişmemesi** (ek dışında her sayfanın her formülü, sabiti, biçimi ve grafiği aynı - Oranlar grafiği 2Y'de kalır; Masa ve Forward'ın değerleri yalnız bu hücrelerde ve onları okuyanlarda - ICAP − OIS, grafik verisi - farklı). Tarayıcı testinde: 3Y ve 7Y satırının metinleri |
| `test_workbook_features.py` | Gizli sütunlar, dondurulmuş bölmeler, yorumlar, veri çubukları, kısayollar, resim, aralıktan okunan açılır listeler, Excel yerleşimiyle yapıştırma, gün sonu arşivi (.xlsx yazıcı dahil), hücreden okunan başlık / notlar, şifreli dosyanın içe aktarılması |
| `test_defaults.py` | PPK ima adımlarının, VİOP Target tablosunun, manuel USDTRY spotunun ve hesaplayıcıların kayıt günü değerlerinin (TM OIS işlemi, gün sayacı, altın forward tarihleri, tahvil carry - Carry iki yönlü formülüyle boş -, iki tarih arası, VİOP TRY faizleri, switch, Eurobond ask'ları, FOMC senaryo adımları) herkese boş gelmesi (boş adımla üç senaryonun ima yola eşitlenmesi, kullanıcının kendi değeri, boş spotla kaynağın BBG olması); Hesaplayıcılar üst bandının ve altın forward'ının spot / tarih / faizlerinin piyasadan başlaması (üzerine yazma, silince piyasaya dönme); eski sürümün ortak girdi olarak taşıdığı dosya adımlarının ilk açılışta bir kez silinmesi (başka ortak girdiye dokunmadan; boş başlatma eki dosyaya uymadıysa silinmemesi), saklı manuel spotun yalnızca dosyanın değeriyse bir kez silinmesi (masanın yazdığı farklı değerin ve sonradan yazılanın kalması); masanın referans verisinin (ticker'lar, tatil adları, kaynak kodları, kova tanımları) ortak, DİBS RV ufkunun kişisel olması ve eski kişisel değerlerin silinmesi; **VİOP kontratlarının kendiliğinden dönmesi** (dosyanın kontrat tarihlerinde vade günü / ertesi gün, arife kuralı - 27.10.2027 -, çift aylı altın, masanın yazdığının geçerli olması, silince dönüşe geri gelme, dosyanın ticker'ının saklı kopyasının silinmesi); **tek OIS spread'i** (`P58` / `O27` / `F122`'nin `MASA!I60`'ı izlemesi, üzerine yazma, silince geri gelme) |
| `test_viopfra.py` | **VİOP Target · FRA eğrisi**: "Hedef tipi"nin yanındaki liste (`EK_VFRA`'dan okunan açılır liste, SENARYOLAR adlarıyla), satırın diğer girdileri gibi kişisel; bugünkü OIS FRA'nın bootstrap eğrisi olması ve varsayılanda dosyanın altı Target satırının her sütunda Excel'in değerini vermesi; her eğrinin (Bootstrap, S1, S2, S3) aynı tarihlerde Masa "Tarih arası faiz" bloğunun faizini vermesi, hedef faiz = FRA + bp ve uzak limit / spread fiyatı / hedef − piyasa'nın izlemesi (near limit değişmez); başlık (`OIS FRA · S2 · Hawkish`, `eğri satıra göre`) ve ipuçları; senaryo adı değişince listenin, başlığın, ipuçlarının ve Masa özetinin izlemesi (seçim aynı senaryo, hücre eski adıyla ve bunu söyleyerek); FXswap+bp ve Faiz % satırlarının hiçbir sayısının değişmemesi, boş tipin FRA+bp sayılması; kişisellik, saklanma, `Delete` ve "Girdilerimi sıfırla", formül ve liste dışı değerin reddi; kayıtlı senaryoyla gidip gelmesi; Masa şeritleri ve launchpad (bütün tablo ve sütun seçimi); **PPK takvimi değişince** adımların toplantısıyla taşınıp satırın senaryonun yeni eğrisiyle fiyatlanması, takvim geri gelince aynı sayılar; **VİOP kontrat dönüşü** (canlı-benzeri Bloomberg, saat ilerletilerek: vade gününde dönemi OIS spot'tan sonra bitmeyen satırın - FRA+bp ve Faiz % - ve dönüşten sonra vadesi geçen kontratın satırının "geçersiz" demesi ve sayı vermemesi: OIS FRA, hedef faiz, limitler, spread fiyatı, hedef − piyasa boş, VİOP sayfasında, Masa şeridinde ve özetinde, launchpad kutusunda; listede kalan kontratın aynı tarihler ve aynı eğriyle kalması); **Fiyat hedef tipi**: her türden satırın (FRA+bp SHORT, S2'den FRA+bp LONG, Faiz %, FXswap+bp) kendi uzak limit fiyatı Fiyat tipiyle geri yazılınca aynı hedef faizi vermesi (1e-9'dan sıkı) ve satırın gerisinin (near / uzak limit, spread fiyatı, piyasa, hedef − piyasa, DV01, gün) aynı kalması, OIS FRA'nın Bootstrap olup FRA eğrisinin etkisiz kalması ve ipuçları, Masa özeti; listede Fiyat, `51,10` virgülle yazılıp uzak limitin dört ondalığıyla - `51,1000` - görünmesi (bp değeri bir ondalıkla: `-150,0`), faizin elle hesaplanan tersle aynılığı, sıfır / eksi fiyatın faiz vermemesi; uzak limit formülü ya da tip listesi başka yazılmış bir çalışma kitabında tipin dışarıda kalması (FRA eğrisi kalır) |
| `test_toplufaiz.py` | **Toplu tarih arası faiz** (`EK_TARIH`, Masa → Faiz · PPK): altı çiftin (bir günden beş yıla; 60., 63., 65. satırlar dahil) her satırının aynı başlangıç, bitiş ve spread'le Masa'nın TARİH ARASI FAİZ bloğunun gününü, yedi eğrinin üç gün esasındaki (ACT/360, ACT/365, O/N) faizini ve her eğrinin + spread'ini vermesi (1e-12); sütun başlıklarının bloğun eğri adları olması (senaryo adı değişince izlemesi), listeler; boş başlangıcın OIS spot, boş spread'in genel spread (`MASA!I60`'tan, yazılınca kişinin, silince geri) olması; boş ve yarım satırların hiçbir şey göstermemesi; Excel'den yapıştırılan satırlar ve TRY takvimli `3A` kısayolu; PPK basamak kullanıcısında blok gibi izlemesi; **kotadan spread** (24.11.2026): satırın Kote %'si tablonun üç gün esasında ve yedi eğri seçiminde seçilen eğriye ve Bootstrap'a göre `kote − eğri` (eğri + fark = kote, 1e-9), ACT/360'ta bulunan spread satıra yazılınca "+ spread (360)"ın kote olması, yapıştırılan kota sütunu, tarihsiz satırın boş kalması; bloğun kutusu (TARİH ARASI FAİZ → SPREAD): üç aylık ve beş yıllık dönemde yedi eğrinin her birine `kote − dönem ACT/360` ve bulunan spread bloğun spread'ine yazılınca o eğrinin "Dönem + spread (360)"ının kote olması (1e-9), kutunun bloğun tarihlerini göstermesi, PPK basamakta kendi eğrisi; sayfadaki yeri (TARİH ARASI FAİZ, kutusu, toplu tablo), girdiler, grow, başlıklar; blok başka yazılmışsa tablonun (ve bloğun iki yönlü hücrelerinin) dışarıda kalması |
| `test_toplu_islem.py` | **TOPLU FORWARD → işlem** (Forward → Toplu fiyatlama, "İşleme al"; masa, 24.11.2026: "3 ekle"): yeni girdilerin (Parite, Yön, Tutar, Karşı taraf) hiç girdi olmamış hücrelerde olması - başka girdi, emekli girdi, dosyada değer yok -, başlıkları, türleri (liste, tutar: `2,5mn`; `eur`, `Satış`, `b` sözcükleri, listede olmayanın ve okunmayan tutarın reddi), tablonun Y'nin ötesine (26.11'in sütunlarına, AU'ya) genişlemesi ve başlıktaki düğme; **satırlardan yapıştırma metni** (`entry.bulk_forward_paste`: Tutar'ı yazılı her satır, Satır / Parite - boşsa USDTRY - / Yön / Tutar / Valör / fiyat / Karşı taraf / Not sütunları, Türkçe ve İngilizce sayı; fiyat kuralı: elle forward satırın kendi paritesininse Forward kur, USDTRY'de Manuel TRY % ya da RET mid % TRY faizi son hanesine kadar, EURTRY'de EURTRY fwd; Tutar'ı boş satırın sayılıp alınmaması, valörsüz ve yönsüz satırın hatalı satır olması, boş tablo; pencerenin metni başlığıyla aynen okuması); **satırın gösterdiği fiyatla işlem** (USDTRY RET mid / manuel / elle, EURTRY RET mid / manuel / elle: önizlemenin forward'ı tablonun N / P / R / T'sine 1e-9'la, USDTRY'nin TRY faizi yolu son bitlerine kadar - aynı formül -, TRY faizi satırınki, not, karşı taraf, öbür paritenin elle forward'ının fiyat sayılmaması); **kayıt ve tutarların silinmesi** (geçerli altı satır tek işlemde bugünün defterine, hatalılar hiç; kaydedilenlerin Satır'ından Tutar hücreleri, silinince valör / faiz / Parite / Yön / Karşı taraf'ın kalması, ikinci basışta yalnız düzeltilecek satırlar); **ON karşılık % yazılmış satır** (masa 26.11.2026: ON fiyat değil - USDTRY satırın gösterdiği TRY faiziyle, blotter'ın forward'ı satırınkiyle son bitlerine kadar ve o faizin ON'u yazılan ON; EURTRY EURTRY fwd'siyle; not `· ON karşılık %`); **P/gün, spread ve genel spread** (USDTRY P/gün yazılmış USDTRY satırının Forward kur'la, EURTRY P/gün'ün EURTRY satırını EURTRY fwd'yle ve USDTRY satırını verdiği faizle, spread'in RET mid + spread/100 faiziyle, genel spread'le fiyatlanan satırların USDTRY'de RET mid + spread, EURTRY'de EURTRY fwd'yle girilmesi ve notları; `entry.bulk_forward_price`'ın bu kaynakları); HTTP ucu (kullanıcının sayı biçimi, başka kullanıcının tablosu, 401) |
| `test_fwd_iki_yon.py` | **Forward sayfasının tabloları iki yönlü** (masa 24.11.2026: "tüm tablolar bu şekilde olmalı"; `tto/twoway.py`): sekiz grubun kullanılabilmesi (yerinde üye eski girdisi, depolar kişisel sayı girdisi, hiç girdi olmamış hücrelerde ve sayfanın gizli yardımcı tablosunda; sayfa tanımında "twoway" anahtarının bir kez olması), **hiçbir şey yazılmamışken her değerin eskisi gibi olması**; **TOPLU FORWARD**: Manuel TRY % / ON karşılık % / USDTRY fwd, puan / EURTRY fwd, puan'ın her biri yazılınca öbürlerinin bağımsız hesapla aynı olması (tek TRY faizi iki pariteyi fiyatlar), gidiş-dönüşler (1e-9, tek yazılan; ON'dan geçen puan 1e-11 göreli), son yazılanın geçmesi, `Delete`, yapıştırılan sütun, elle sütunlarının ayrı durması; **ON karşılık %** (masa 26.11.2026): satırı fiyatlayan faizin (Manuel, boşsa RET mid) satırın Gün'ü üzerinden Forward hesaplayıcısının ON Karşılık'ı olması (`Forward!AH14` aynı faiz ve günle, 1e-12), kontrol değerleri (120 gün %35,30 → %33,3884, %35,0135 → %33,1317), valörsüz satırda boş, iki ondalık; Manuel TRY % ve fwd yazılmışken ON'un, ON yazılmışken onların son yazılan olması, ON'da ve verdiği faizde `Delete`, yapıştırılan ON sütunu, işaretler ve yardımcı tablodaki `AE` deposu; **"Bunların da hepsini yap"** (masa 26.11.2026): Spread (bp) ve iki paritenin P/gün'ü yazılınca öbürlerinin bağımsız hesapla aynı olması (spread: RET mid + spread/100; P/gün: puan = P/gün · gün), gidiş-dönüşleri, son yazılanın geçmesi ve `Delete`; Gün 0'da ON / dönem / P/gün sütunlarının boş kalması (ON yazılırsa durur, faiz vermez); **genel spread**'in hiçbir şey yazılmamış satırları RET mid + spread'le fiyatlaması (değer yazılı satır kendi faiziyle; boşsa her değer bit bit eskisi gibi); **Dönem TRY % / ON %**'nin üstteki en yakın dolu satırdan forward-forward'ı (ilk satır kendi faizi, boş satırın atlanması, tarihler artmıyorsa boş, Gün 0'dan sonraki satır); **ON · sütunları** (offshore / OIS / RET'in 360 ON'u, OIS de 360 bazında) ve **ON − RET ON (bp)**; gizli blok (`Z:AK`) tablodan çıkıp yardımcı tabloda görünmesi, yeni sütunların sırası, Valör ve Gün'ün sabit (fz 2), genel spread kutusunun başlıkta olması; **İşleme al**: USDTRY fwd / puan yazılmış satırın USDTRY'yi Forward kur'la, EURTRY fwd / puan yazılmışın USDTRY'yi satırın TRY faiziyle (blotter'ın forward'ı satırınkiyle son bitlerine kadar), EURTRY'yi EURTRY fwd'yle girmesi - her forward satırın gösterdiği (1e-9) - ve notlar; önceden yazılan Manuel TRY % ve N'nin üstüne yazılmış "Elle değer"in satırın yazılanı olması; **valör tabloları**: her satırın bid / ask'inde TRY % / forward / puan / P/gün, ortalar, gidiş-dönüşler, EURTRY'nin USDTRY'nin faizini izlemesi (kendi yazılanı yoksa), **valör tarihi değişince yazılanın kalması**, işaretler (✎, kimden hesaplandığı), önceden yazılanlar; **serbest forward**: minor % / swap / forward; **FORWARD STARTING SWAP**: Manuel satırın yedi değerinin her biri, gidiş-dönüşler, Durum OK değilken yalnız yazılanın görünmesi, EURTRY dönemi yokken faiz çıkmaması, `Delete`, Elle puan → faiz satırlarının ayrı durması, **geçici kopya** (kopyada yazılan, tablodaki `C169` varken reddin nedeni); **ÇAPRAZ FORWARD**: USD ve EUR'da Manuel TRY % / manuel forward ve gidiş-dönüşler, **döviz değişince yazılan forward'ların silinmesi** (aynı döviz başka yazılışla: değişmez; dövizle aynı yazımda yazılan kalır; Delete / dosyadakine dönüş), kayan valörde yazılanın kalması; senaryo ve tablo notları |
| `test_fwd_on.py` | **Forward tablolarında ON karşılık** (masa 26.11.2026: "Toplu forward fiyatlama kısımlarında ON karşılıklarını da görmek istiyorum" - "Bunların da hepsini yap"): her tablonun ON'unun grubunun son üyesi olması (öncekiler aynı, deposu hiç girdi olmamış hücrede kişisel sayı girdisi, gizli yardımcı tabloda), sayfada TRY faizinin hemen yanında görünmesi ("cols"; depolar ve yardımcılar görünmez), Forward sayfasındaki yeni hücrelerin dosyada boş olması (dolu dosyada ekin dışarıda kalması); **hiçbir şey yazılmamışken** her ON'un tablonun kendi faizinin, forward formülünün o faizi uyguladığı günle hesaplayıcının *ON Karşılık*'ı olması (1e-12) - ve Forward'ın kendi hesaplayıcısına aynı iki tarih ve faiz yazılınca aynısını vermesi: FORWARD KOTASYON (valör − paritenin spot valörü), valör tabloları (bid / mid / ask), serbest forward (USDTRY ve EURTRY), FSS'nin her satırı (far: spot → far, fwd-fwd: near → far), ÇAPRAZ (Manuel ve İma; USD, EUR, başka döviz); iki ondalık; **FORWARD KOTASYON**: ON yazılınca TRY %'nin tam tersi olması ve satırın izlemesi, gidiş-dönüşler (1e-9, tek yazılan), öbür tarafın ayrı kalması, `Delete`, işaretler (✎, kimden hesaplandığı), not, yapıştırılan sütun, kendi satırını okuyan formülün reddi, senaryo, **Masa'daki özette** Spread · TRY % · ON % sırası ve oraya yazılan ON; **valör tabloları**: ON bid / ask yazılınca satır, ON mid'in yeni mid'in ON'u olması ve yazılamaması, EURTRY'nin USDTRY'de yazılan ON'un faizini alması (ON'u kendi günüyle), valör tarihi değişince yazılan ON'un kalması; **serbest forward**: Minor ON, bitiş tarihi yokken yalnız yazılanın görünmesi; **FSS**: ON fwd-fwd ve ON far (far TRY % yazılmış gibi), gidiş-dönüşler, Durum OK değilken, `Delete`, işaretler ve not, **geçici kopya**; **ÇAPRAZ**: Manuel ON, gidiş-dönüşler, **döviz değişince yazılan ON'un kalması** (forward gider; TRY % yeni dövizin günüyle), işaretler, "Yöntem" satırının birleşik hücrelerinin kalması; `_pick_columns`'un birleşik hücreleri |
| `test_hesap_ters.py` | **Hesaplayıcıların tersleri** (masa, 24.11.2026; 8. ve 12. maddeler): **tahvil carry'de fiyattan repo** - hesaplayıcının kendi B/E'si Fwd temiz fiyat (elle) olarak yazılınca Carry geri gelir, her fiyatın İma reposu Carry'ye yazılınca B/E o fiyat olur (1e-9; bono ve kupon yazılmış kâğıt), yüksek fiyat yüksek repo, gün yoksa ya da fiyat boşsa repo yok; **Implied Move'da hareketten vol** - bloğun kendi hareketi (%), üst ve alt sınırı ve pip'i geri yazılınca Volatilite, her değerin İma vol'ü Volatilite'ye yazılınca aynı hareket / sınır / pip (1e-9; dosyanın ve başka bir spot, gün, gün esasıyla), masanın yazdığı biçimler, boş / sıfır / eksi değerde vol yok; yeni girdilerin kişisel, boş başlaması ve tablolarında yerleri (tahvil carry'nin ISIN satırı tabloda kalır); blok başka yazılmışsa ya da aldığı hücre doluysa yalnız o tersin dışarıda kalması |
| `test_kagitters.py` | **Kâğıtlar tersinden** (masa, 24.11.2026: "1-2-3-4-5-6-7-8-11-11-13"; `extras._asw_back`, `_rv_back`, `_rv_switch_back`, `_manuel_isin`): **DİBS ASW** - bir bononun, kısa ve uzun iki sabit kuponlunun kendi ASW'sinin kendi temiz fiyatını, başka seviyelerin sayfanın formülünün elle çözümünü vermesi (1e-12), bulunan fiyat Manuel temiz'e yazılınca ASW'nin yazılan değer çıkması (1e-9) ve cevabın fiyattan bağımsızlığı, TLREF'linin nedeni, kişisellik, sayfadaki yeri (kâğıt tablosunun hemen altı, sütunlar, girdi), ASW listesinde iki kâğıt yer değiştirince hedefin kâğıdıyla gitmesi; **DİBS RV** - bono, iki sabit kuponlu ve üç TLREF'lide (ikisi ilk kuponu sabit) ASW / DM'den fiyatın elle hesapla aynı olması (DM: nakit akışları ileri faiz + DM ile dönem dönem), Manuel temiz'e yazılınca ASW / DM'in yazılan değer çıkması (1e-9; sütun 0,1 bp), FRN ve TÜFE'nin nedeni, fiyatsız kâğıdın nedeni ve herhangi bir fiyatla hesaplanıp ona bağlı olmaması, sayfadaki yeri; trading listesinde iki kâğıt yer değiştirince hedeflerin kâğıtlarıyla gidip yeni satırlarında hesaplanması; **SWITCH / PAIR** - getiri seviyesinin (sabit / sabit, Al bono) ve ASW / DM seviyesinin (sabit / sabit ASW, TLREF / TLREF DM, sabit / TLREF) Al temizinin elle hesapla aynı olması, Al'ın Manuel temiz'ine yazılınca "Getiri farkı" / "ASW/DM farkı"nın seviyeyi göstermesi (1e-9), TLREF bacağında getiri olmamasının nedeni, sütunlar (sonunda iki yönlü tablonun Al temiz'i) ve not; çiftin kâğıtları listede yer değiştirince seviyelerin çiftte kalıp kâğıtlarını ISIN'iyle okuması; **Manuel Tahvil** - ISIN yokken çalışma kitabının varsayılanları; trading listesindeki sabit kuponluda vade, kupon, frekans, tip, kullanılan temiz ve valörün gelmesi ve durum satırı, getiri / ASW / Z hedeflerinin fiyatının fiyat olarak yazılınca hedefi geri vermesi (1e-9), elle yazılan kuponun önce gelip söylenmesi ve silinince dönmesi, DİBS RV'deki manuel fiyatın gelmesi; TLREF'lide D tipi, ek getiri, gecikme, gerçekleşen endeks, cari dönemin bilinen kuponu ve DM hedefi; listede olmayan sabit kuponluda katalogun vadesi ve kuponu, fiyatsızlığın söylenmesi, Tüm Kâğıtlar'ın bid / ask ortası ve bugünkü son işlemi; bono, kuponsuz, TÜFE, FRN, listede olmayan TLREF, kuponu bilinmeyen kâğıt ve bilinmeyen ISIN'in nedeniyle reddi; kâğıt trading listesinde yer değiştirince koşulların ve fiyatın kâğıdından gelmesi; yeni girdilerin hiç girdi durmamış hücrelerde ve kişisel olması; formüllerin metinleri ve eklerin kitaplara uyması; ters çevrilen formül farklı yazılmış kitapta yolların - ve aynı formülü ters çeviren iki yönlü tabloların - dışarıda kalması |
| `test_ppkters.py` | **Faizden PPK / FOMC adımı ve FRA'nın öbür bacağı** (masa 24.11.2026; `EK_PPK`, `OIS_MAIN!U:W`, `SOFR_FOMC!AA:AE`): MPC OIS → PPK ADIMI'nın her satırının MPC OIS'in dönemi (tarihler, gün, piyasa, önceki dönem - ilk dönemde OIS spot'tan stub'ı -, O/N eşdeğerleri) olması; **O/N eşdeğerinin TLREF'in iş günleriyle** olması (masa 25.11.2026: "B"): her dönemin iş günleri ve hafta sonu / tatil terimi masanın TRY tatil listesinden elle sayılınca modelinkiyle (Motor'un Pcum'u) aynı - Yılbaşı ve 2027 Ramazan Bayramı -, yazılan faizin O/N'si modelin denkleminin elle (bisection) çözümü; **modelin kendi dönem faizinin** (`OIS_MAIN!BJ`) iki tabloda da modelin TLREF'ini (`Motor!K`, 1e-12) ve adımlarını (1e-8 bp) vermesi, her gün bileşiğin 365·W·x²/d kadar altında kalması (tekrar gününde 1,3–2,5 bp), piyasanın faizinin piyasanın adımını vermesi; üç dönemde yazılan faizin adımının **Broker Chat**'in aynı satırdaki ima adımına eşit olması (bp'nin son hanesine kadar; piyasanın adımı = chat'in modeli), adımın önceki dönemin O/N'sine eklenip faizi geri vermesi (1e-12), her dönemde piyasa faizinin piyasanın adımını vermesi; MPC SPREAD → PPK ADIMI'nda piyasanın spread'inin sonraki dönemin piyasasını ve adımını vermesi, bir spread'in adımının o faizin sonraki döneme yazılmasıyla ve chat'in o seviyedeki satırıyla aynı olması; PPK basamak kullanıcısında piyasanın onun eğrisi olup chat'le yine aynı çıkması, Bootstrap kullanıcısının sayılarının masanınki kalması; TÜM FORWARD / FRA'da hedef FRA'nın gereken bitiş / başlangıç bacağının dolum olarak yazılınca Gerçekleşen FRA'yı hedefe eşitlemesi (dolumlu, boş - piyasa par'ı -, spot başlangıçlı, kişinin kendi 1Y1Y satırı); FOMC'de piyasanın pencere faizinin İma O/N ve Toplantı adımını vermesi, bir faizin adımının geri faizi vermesi (1e-9), Adım değişince, kararsız toplantıda boş kalması; hücrelerin toplantı satırına ait olması (yazılan / hesaplanan) ve **taşınma**: araya toplantı girince, toplantı geçince (kenara alma) ve FOMC listesi yapıştırılınca faiz / spread / pencere faizi / yazılan adım (iki yönlü) toplantısıyla gider, formül alınmaz, yeni dönemin adımı yeni dönemin iş günleriyle (yazılan adım adım kalır, faizi yeni dönemden); sayfadaki yerleri, notları, girdilerin hiç girdi olmamış hücrelerde olması; formül başka yazılmışsa (modelin Pcum hücresi `Motor!J` dahil) ya da hücre doluysa eklemenin dışarıda kalması |
| `test_kagit_on.py` | **Getirinin ON karşılığı** (masa 26.11.2026: "Bunların da hepsini yap"; `extras._rv_on`, `try_term`, `EK_ISGUNU`): iki bononun (`ISL0`: bugünden) ve kısa / uzun iki sabit kuponlunun (`ISL1`) kullanılan, alış ve satış getirisinin ON'unun elle hesapla aynı olması (getirinin kendi kuralıyla büyüme - bonoda basit ACT/365, kuponluda (1 + y/f)^n, dönem sayısı sonraki / önceki kupon tarihlerinden -, TLREF'in iş günü denklemi Newton'la, 1e-13), bileşik getirinin aynı büyümeyi vermesi, takvim günü bileşiğinin 0,5–3 bp üstünde ve kesin çarpımdan 0,01 bp içinde olması; her fiyatlı sabit kuponlu / bononun hafta sonu / tatil teriminin TRY listesinden gün gün sayılanla (ve Motor'un Pcum'u + `ISL0`'ın spot'a kadarki günleriyle) aynı olması, TLREF'li ve fiyatsız kâğıtta boş kalması; **Motor'un takviminin ötesi** (OIS spot + 3700 gün): takvimin sonundan 200 gün ötesine her vade ve üç uzak vade, bugünden ve spot'tan, listeye eklenen tatillerle (perşembe + cuma, pazartesi, çarşamba-perşembe, cumartesi, iki kez yazılan) gün gün sayılanla aynı; **iki yönlü**: yazılan ON'un temiz fiyatının elle hesapla aynı olması, öbür üyelerin o fiyat elle yazılınca ile aynı olması, geri yazmalar (1e-9), son yazılan, Delete, TLREF'lide fiyat vermemesi ve nedeni, fiyatsız kâğıdı fiyatlaması, PPK basamak kullanıcısında aynı olması; **satırlar kayar** (yazılan ON kâğıtla yeni satırına gider ve orada fiyatlar, geri gelir); **sayfalar**: DİBS RV'de sütunların getirilerin yanında olması, başlıklar, iki ondalık, girdi işareti, sabit sütunların (ISIN, kaynak, ad) korunması, yardımcı tablo ve grubun notu; DİBS Trading özetinde "Getiri %"nin sağında, Genel'de "Getiri" grubunda, Tüm Kâğıtlar'da "Getiri % (RV)"nin sağında (sabit iki sütun korunur), kartta bileşik getiriden sonra; canlı kotası olmayan fiyatta soluk; sütun sırasının sabit sütunları koruma kuralı |
| `test_kagit_twoway.py` | **Kâğıt tabloları iki yönlü** (masa 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar bu şekilde olmalı"; `extras._rv_tw`, `_sw_tw`, `_asw_tw`, `_man_tw`, `tto/twoway.py`): beş grubun kullanılabilmesi (DİBS RV kâğıt satırı, repo ↔ carry, SWITCH / PAIR, DİBS ASW, Manuel Tahvil), depoların kişisel sayı girdisi ve hiç girdi olmamış hücrelerde olması, yerinde üyelerin eski girdiler (N, AL, D, B14) olması; **DİBS RV** - bono, iki sabit kuponlu (biri uzun) ve TLREF'lide her üye yazılınca Manuel temiz'in elle hesapla aynı olması (basit / bileşik getiri, getiri − OIS, ASW, DM, Z-spread) ve öbürlerinin o fiyat elle yazılınca sayfanın verdiğiyle aynı olması, her hesaplanan değerin kendi türüyle geri yazılınca aynı satır (1e-9; elle fiyatlanan satırda tam değer, hiçbir şey yazılmamışta 0,1 bp), son yazılanın geçerli olması, Delete (yazılanda / hesaplananda) ve sıfırlama, fiyatsız kâğıdın yazılan değerle fiyatlanması, TLREF'lide getirinin fiyat vermemesi ve nedeni; **repo ↔ carry** (bono, sabit kuponlu, TLREF'li: carry'den repo, elle hesap, geri yazma, Delete); **SWITCH / PAIR** - getiri farkından Al temizi ve ASW/DM farkı, ASW/DM farkından Al temizi ve getiri farkı (Al'ın satırına o fiyat elle yazılınca gösterilenle aynı), geri yazma, Al kâğıdının satırının değişmemesi, iki TLREF'lide DM, getirisi olmayan bacağın nedeni, çiftin kâğıtları listede yer değiştirince farkın çiftte kalması; **DİBS ASW** - ASW ve kirli @spot'tan temiz (elle hesap), geri yazma, son yazılan, Delete; **ASW FX** sütununun yazılan ASW'li satırı aynı temiz fiyatla fiyatlaması (o fiyat elle yazılınca ile aynı); fiyatsız kâğıdın yazılan ASW'yle fiyatlanması; **Manuel Tahvil** - ISIN'li kâğıtta her sonuçtan temiz fiyat (elle hesap) ve ISIN'in fiyatının önüne geçmesi, C17, geri yazma, Delete ile ISIN'in fiyatı, ISIN'siz dosyanınki; **önceden yazılanlar** (Manuel temiz, repo, ASW'nin Manuel temiz'i, B14 aynen; ASW hücrelerine "Elle değer" satırın yazılanı); **satırlar kayar** (trading listesinde ve ASW listesinde iki kâğıt yer değiştirince yazılan getiri, ASW, carry, ASW ve kirli fiyatın kâğıtla gidip yeni satırında hesaplanması, geri gelmesi); **yapıştırma ve senaryo**; **fiyatı okuyanlar** (Manuel Tahvil'in ISIN fiyatı, Tüm Kâğıtlar'ın getiri / ASW'si, switch'in ASW/DM farkı varsayımsal fiyatı okur, masanın hesabı değişmez); **sayfalar** (üyeler girdi, ✎ ve `an` / `ao`, tabloların altındaki notlar, "Fiyat durumu", switch tablosunun yeni sütunu, depoların sayfanın gizli yardımcı tablolarında ve ISIN'le kayan sütunlarda olması) |
| `test_viop_twoway.py` | **VİOP Target iki yönlü** (masa 24.11.2026): satır başına beş üyenin (Hedef değer, Hedef faiz, Uzak limit, Spread fiyatı, Hedef − piyasa) hiç girdi olmamış hücrelerde kişisel depoları, Hedef değerin artık kendi başına girdi olmaması, boş satırın boş kalması; **her tipte ve yönde** (Faiz % LONG, FRA+bp SHORT, FXswap+bp LONG, Fiyat SHORT) her üye yazılınca öbürlerinin kontrat satırlarından (gün, bid / ask, USD, FX swap) bağımsız bir hesaba eşitliği - near limit yönle, Hedef değer satırın tipinde -, her değerin kendi türüyle geri yazılınca aynı satır (1e-9) ve yalnız sonuncunun saklanması; **tipin kullanıcının kalması** (FRA+bp satırına yazılan fiyatın Hedef değerde bp görünmesi, tip değişince yazılanın kalıp Hedef değerin yeni tipte olması), hedef faizin her yazılana göre ipucu, Delete ve sıfırlama; **önceden yazılan Hedef değer** (deposuna taşınıp dosyanın satırıyla aynı sayılar, Masa özeti); vadesi geçen kontratta satırın geçersiz olup yazılanın kalması, kontrat yeniden seçilince hesaplanması; sütun yapıştırma, senaryo, Masa özeti ve şeridinden yazma; geçici kopyada uzak limit (tablonunki kalır, Delete tabloya döner); sayfa işaretleri, not, yardımcı tablo; hedef faiz başka yazılmış bir çalışma kitabında dışarıda kalması; Masa özetinin bp'yi virgülle bir ondalıkla yazması |
| `test_viop_on.py` | **VİOP kontratlarının ON karşılığı** (masa 26.11.2026): VİOP sayfasının BID / ASK tablolarındaki ON karşılık satırının (Excel'de TRY Repo; sayfadaki adı) her kontratta TRY satırının aynı günlerde (vade − `VIOP!K3`) 360 bazında günlük bileşik karşılığı olması (kendi hesabına ve `extras.on_equivalent`'in formülüne 1e-13'ten sıkı), tabloların notları ve iki ondalık; Masa'nın VİOP özetinde ON bid / ON ask'in İma bid / İma ask'in yanında, VİOP sayfasının sayısı ve yazısıyla aynı (30.11.2026 vadeli kontrat: %33,58 → %33,20, %33,83 → %33,44); kişinin kendi spot valörü (K3) bir gün sonra yazılınca her kontratın gününün, ima faizinin ve ON'unun izlemesi (yalnız onda); **kontrat dönüşü** (canlı-benzeri Bloomberg, saat ilerletilerek: ertesi gün ilk satır Aralık kontratı, kendi faizi, günü ve ON'uyla); eklemenin yalnız kendi hücrelerini yazması (öbür bütün hücreler, formüller ve biçimler aynı) ve hiçbir formülün onları okumaması; başka yazılmış bir çalışma kitabında (TRY Repo'nun günleri, özetin faiz sütunu, başlık, dolu hücre, ima faizin formülü) eklemenin dışarıda kalması |
| `test_ondalik.py` | **Okunan ondalıklar** (masa 25.11.2026: "try faizleri 4 decimal'i çok yoruyor gözü. Bunları 2 decimala alalım. VİOP target kısmında da faiz seçtiğim durumda decimalsiz yazıyor"): bir hücrenin biçimini başka bir hücrenin seçmesi (`SheetBuilder.number_format_if`: koşulu tutan ilk kural, tutmayan kendi biçimi, metin / boş ve değer dokunulmadan); Forward'ın USDTRY / EURTRY tablolarında her eğrinin TRY bid / mid / ask %'sinin iki ondalıkla görünmesi, değerinin (`v`, Ctrl+Shift+C) bütün ondalıklarıyla kalması, outright'ların ve USD / EUR faizlerinin dört ondalık kalması; altı ondalıkla yazılan TRY faizinin iki ondalıkla görünüp forward'ın ve Elle ayarı mid'inin bütün ondalıklarla hesaplanması; serbest forward'ın minor %'si (major % dört), TOPLU FORWARD'ın offshore / OIS / RET faizleri, Manuel TRY %, ON karşılık % (hesaplanan ve altı ondalıkla yazılan), dönem faizleri ve faizlerin ON'ları, Spread / ON − RET ON / P/gün'lerin bir ondalığı ve İma TRY %'si (USD % / EUR % üç), ÇAPRAZ FORWARD'ın İma TRY %'si; **VİOP Target'ın Hedef değeri tipinde**: Faiz % iki ondalık (yazılan ve Hedef faiz'ten hesaplanan), Fiyat uzak limitin dört ondalığı, FRA+bp / FXswap+bp bir ondalık (yazılan ve başka sütundan hesaplanan) - VİOP sayfasında, Masa'nın VİOP TARGET şeridinde ve Masa özetinde aynı -, satırın diğer üyelerinin okunaklı kalması, tip değişince aynı değerin yeni tipte görünmesi; hedef tablosu beklenenden farklı bir çalışma kitabında biçimlerin iki yönlüyle birlikte dışarıda kalması |
| `test_xau_twoway.py` | **VİOP altın hesaplayıcısı iki yönlü** (masa 25.11.2026: "Evet"): sütun başına altı üyenin (TRY %, USDTRY fwd, SP, günlük SP, XAUTRY teorik, ON karşılık) hiç girdi olmamış hücrelerde kişisel depoları (gizli yardımcı tablo, başlığında kontratlar; kopyalanabilir hesaplayıcı: hiçbiri yerinde değil), TRY %'nin artık kendi başına girdi olmaması, USD % ve swap %'nin girdi kalması; **hiçbir şey yazılmadan** her üyenin eskisi gibi (TRY % aynı vadeli USDTRY kontratının ima faizi, gerisi formülleri), serbest sütunun tarih ve faiz yazılmadan boş kalması; **iki kontrat sütununda ve serbest sütunda** her üye yazılınca öbürlerinin sütunun spot, USD, gün ve XAUUSD fwd'ından bağımsız bir hesaba eşitliği, her değerin kendi türüyle geri yazılınca aynı sütun (1e-9) ve yalnız sonuncunun saklanması; son yazılanın kalması (öbür sütunlar kendi değerinde), USD % değişince yazılanın kalıp gerisinin izlemesi, Delete (hesaplanan ve yazılan hücrede), "Kendi girdimi sil" ve "Girdilerimi sıfırla"; dört sütuna yapıştırılan teorik satırı ve senaryo; **önceden yazılanlar** (TRY % deposuna taşınıp aynı sayılar, formülüyle canlı, "Elle değer" yazılmış teorik, eski senaryo); geçici kopyada teorik (tablonun TRY %'si kalır, Delete tabloya döner); sayfa işaretleri, girdi sayısı, not ve yardımcı tablo; **kontrat dönüşü** (masa sonraki üç kodu yazınca): yazılan fwd / SP / günlük SP / teorik ve kendi VİOP bid / ask kontratıyla yeni sütununa, tablodan çıkan kontratınki silinir, TRY % ve ON sütununda kalır, serbest sütun yerinde, kaydedilmiş senaryolarda da; gelen fiyatın sütunda kalan yazılmış faize denk gelince silinmesi; kontrat tablodan çıkıp geri gelince bir şey getirmemesi; aynı kontrat iki sütundayken geri alınca değerin kontratın kaldığı sütuna gitmesi (orada yazılmış değer varsa o kalır) |
| `test_hesap_twoway.py` | **Hesaplayıcılar iki yönlü** (masa 24.11.2026: "tüm tablolar bu şekilde olmalı"; `extras.TW_HUBS`): her hesaplayıcının (üst bant, basit ↔ bileşik iki tablo, DF to Rate, Exponential ve Simple'ın dört hesaplayıcısı, Implied Move, TLREF Spread, Forward Volatility, iki getiri hesaplayıcısı) ve DV01 senaryo P&L'inin iki yönlü grup olması, depoların hiç girdi olmamış hücrelerde kişisel sayı girdisi olması, yerinde kalanlar (üst bandın Forward'ı, DV01 şokları); hiçbir şey yazılmamışken dosyanın değerleri; **her değer yazılınca öbürlerinin** bloğun formülleriyle ve tersleriyle bağımsız bir hesaba eşitliği, hesaplanan her değerin kendi türüyle geri yazılınca aynı hesaplayıcı (1e-9) ve yalnız onun saklanması; Implied Move'da başabaştan vol, masanın yazdığı biçimler ve 24.11 kutularıyla aynılığı, spot / gün değişince yazılanın kalması; **son yazılan geçerli**, Delete (yazılanda ve hesaplananda), "Kendi girdimi sil" ve "Girdilerimi sıfırla"; yapıştırılan sütunun son değeri, senaryo; **önceden yazılanlar** (eski girdiler deposuna taşınır, "Elle değer" de, formülün değeri kalır); sayfa işaretleri, notlar, yardımcı tablo, Girdilerim; **geçici kopyada** başabaş (tablonunki kalır, Delete tabloya döner); DV01'de şoktan P&L ve P&L'den şok, sütun yapıştırma; çalışma kitabı değişmiş bir hesaplayıcının tek başına dışarıda kalması |
| `test_columns.py` | **Sütun gizle / göster**: her kullanıcının gizlediği sütunların hesabıyla sunucuda saklanması (tablo ve sütun adıyla; boş liste tabloyu unutur), başkasının görünümünün değişmemesi, geçersiz ya da oturumsuz isteğin ve başka sayfadan gelen değişikliğin reddi, tablo sınırı; **sütun sırası** (kullanıcı başına, gizlenenlerden ayrı saklanması, boş listeyle Excel sırasına dönüş, geçersiz istek, sınırlar, HTTP'de gizlemeyle birlikte gönderilmesi); **varsayılan gizli sütunlar** (DİBS RV'nin `BF:BJ`'si - varsayılanlar sunucudan okunur, düzen dalları kendi tablolarınınkini ekler -: seçim yapmamış kullanıcıya `defaults`, üstüne gizlenen sütunla birlikte saklanması, "hepsini göster"in boş liste olarak saklanıp varsayılanın geri gelmemesi, başkasının görünümü, tablonun Genel'i gösteren notu, HTTP); sayfadaki davranış (DİBS RV'nin varsayılan gizli FX sütunları ve notu, sağ tık, "Sütunlar", kopyalama, ok tuşları, yeniden açılış, İzleme listesi, sütun sırası) `test_e2e.py`'de |
| `test_decimals.py` | **Ondalık basamak (sağ tık)** (`tto/decimals.py`): her kullanıcının ayarının hesabıyla saklanması ve yalnız onun cevabına konması - herkesin paylaştığı sayfa değişmeden, aynı sayfa başka kullanıcıya dosyanın biçimiyle gider -; yalnız ondalığın değişmesi (yüzde yüzde, muhasebe biçiminin eksisi, milyonların "M"si yerinde; değer ve hücrenin öteki işaretleri aynı; metin dokunulmadan, tarih atlanarak); yeniden ayar ve varsayılana dönüş; cevabın `as` işaretiyle eski ayarlı tabloları tutan tarayıcıya (sayfa, launchpad kutusu) tabloların bütün gitmesi; **geçici kopyanın kendi ayarı** (`dpc`; kopya, kendi ayarı olmayan hücrede tablonunkini gösterir; şerit girdisi; kopyadaki ayar geri alınınca tablonunki; kopya kapanınca silinmesi; başkasının kopyasına yazılamaması); **satırlar kayınca** (olağanüstü PPK toplantısı) ayarın hücresinde kalması - yazılan adım toplantısıyla gider -; yeniden başlatmada okunması; geçersiz istek (kitap, hücre, ondalık 0–10 tam sayı, sözlük / liste, bir seferde 5000), oturumsuz istek, kullanıcı başına sınır, başka siteden gelen istek, HTTP; menü ve sayfadaki davranış `test_e2e.py`'de |
| `test_launchpad.py` | **Launchpad ve düzen**: birden çok sayfanın tablolarının tek istekte `view/panel` anahtarıyla gelmesi (aynı panel id'si başka sayfada başka tablo), sayfasındakiyle aynı olması, sayfa ve sekme adı; `since` / `as` (değişmeyenin "unchanged" demesi, ortak girdinin yalnız onu okuyan tabloyu, kullanıcının kendi girdisinin bütün tabloyu getirmesi); tablonun bir kısmının sunucuda kesilmesi (satır adı ya da numarası, sütun harfi, tablonun kendi sırası, başlık satırları, birleşik hücrenin kalan kısmı - ilk hücresi gidince salt okunur -, dondurulmuş sütun, sayfanın tablosunun değişmemesi, seçimden bir şey kalmayınca bütün tablo, kısmın bütün tablonun satır / sütunlarını `ar` / `ac` ile söylemesi); **satırın günden güne değişmeyen adı** (`" · "` öncesi; yazı olarak duran tarihin atlanması, tekrar eden adın satır numarası, sıralama tablosunun satır numarasıyla tutulması; önceki sürümün tam metinle seçiminin aynen ya da `" · "` öncesiyle bulunması, iki satıra uyanın hiçbirine uymaması), seçim penceresinin anahtarları istemesi (MPC OIS'te "MPC1→2" …, ICAP eğrisinde vadeler, EN İYİ 15 SPREAD'de satır numaraları); **gün dönümü** (saat testlerdeki gibi on gün ileri alınınca MPC OIS'in adı değişir, "MPC1→2" ile ve eski tam metinle seçilen satırlar yine gelir); yöneticiye özel sayfa (403 "erişim yok"), kaldırılmış sayfa ya da tablo (404 "artık yok") ve diğerlerinin yine gelmesi; geçersiz istekler; düzenin kullanıcı başına saklanması, gönderilmeyen bölümlerin kalması, normalleştirme, geçersiz düzen, sınırlar (launchpad, tablo, yan panel, bayt), yeni öğe türünün kendi denetimiyle eklenmesi, açılış sayfası, **sıkışık görünüm** (`compact`: kullanıcı başına, başka bölüm değişince kalması, yalnız true / false - `1`, `"true"`, `null` reddedilir -, başka sürümün yazdığı true olmayan değerin kapalı okunması), dışa / içe aktarma (aynı adın "(2)" alması), oturum; **servis yeniden başlayınca** düzenin (sıkışık görünüm dahil) ve sütun sırasının kalması; HTTP (`compact`'ın kaydı ve reddi, 401, başka sayfadan gelen değişikliğin reddi) |
| `test_calc.py` | **Kişisel hesap tablosu** (`tto/calc.py`): yazılanın okunuşu (Türkçe / İngilizce sayı, yüzde ve tarih biçimiyle, DOĞRU / YANLIŞ, `'` ile metin, formül), Türkçe Excel'in `;`'ü ve ondalık virgülü, `[kitap]Sayfa!` yazımı, kopyalanan formülün göreli başvurularının kayması (`$` kalır, sayfadan taşan `#REF!`); kendi hücreleri ve aralıkları (SUM, AVERAGE, TEXT, IF, LET, INDEX), ana kitabın hücreleri sayfa adıyla (büyük / küçük harf, tırnaklı ad, aralık, adlar: SPOTDATE) ve diğer kitapların (`[sofr]`, `[asw]`, `[borsa]`) - sayfanın gösterdiği değerle aynı -, başvurunun sayı biçimini alma (tarih, yüzde), TODAY / WORKDAY tarih; **kullanıcının kendi girdisinin ve "Elle değer"inin yalnız onun sonucunu değiştirmesi** (diğerinin "unchanged" demesi), ortak girdinin yalnız onu okuyan tabloyu getirmesi; **Bloomberg işlevlerinin reddi** (BDP, BDH, BDS, BFXFORWARD, BINTERPOL, RTGET, `_xll.`, iç içe ve küçük harfle; nedeniyle, değişikliğin hiçbir kısmı kalmadan) ve başka sürümün sakladığı böyle bir formülün sağlayıcıya hiç ulaşmaması; hücre hücre hatalar ve anlamları (`#DIV/0!`, bilinmeyen işlev / ad / sayfa / kitap, döngüsel başvuru, `#NUM!`, `#VALUE!`, okunamayan formülün reddi); Motor sayfasının yalnız yöneticiye açık olması; **sınırlar** (formül uzunluğu, hücre adresi, satır / sütun, dolu hücreyi kesmeme, genişlik, sayı biçimi, yapıştırılan alan, okunan hücre, aralık, süre, tablo boyutu, istek); hiçbir öğenin göstermediği tablonun 7 gün sonra ve üst sınırda gitmesi; kopyalama ve doldurmada formüllerin kayması; sayı biçimleri; düzende `calc` öğesi; dışa aktarılan launchpad'in hücreleri taşıması, içe aktaranın kendi kopyası, Bloomberg'li dosyanın reddi; **servis yeniden başlayınca** kalması; HTTP (`/api/calc/eval`, `/api/calc/save`, 400 / 401 / 403 / 404, kullanıcının sayı biçimi) |
| `test_inputformula.py` | **Girdiye formül** (`tto/inputformula.py`): Masa'nın kırık vade valörüne `=C60+7` - değerin başlangıç tarihi + 7 olması, başlangıç her yazılınca kendiliğinden izlemesi, sayfada `ƒ` / formül (`ff`), `/api/cell` ve "girdilerim" listesinde formül ve şimdiki değer; Türkçe `;` ve ondalık virgül, başka sayfa adıyla ve onun değişince izlemesi; **aynı formülü yazan iki kullanıcı** (tek şablon, bir kez ayrıştırılır: her birinin kendi C60'ıyla değeri, C60 yeniden yazılınca izlemesi); **sayfasız başvurunun girdinin kendi sayfası olması** (Forward'da `=AB2*2` - aynı gruptaki iki girdinin bağımlılık bitini paylaşmasına rağmen döngü sayılmaması); **ortak girdinin formülü herkesin** (başka kullanıcının değeri ve formülü görmesi, başkasının yazdığı ortak girdiyi izlemesi), **kişiselinki yalnız sahibinin**; **ret ve nedeni** (BDP, `_xll.BDH`, doğrudan döngü, çalışma kitabının formülü üzerinden döngü - E60'ın formülü C60'ı okur -, başka formüllü girdi üzerinden döngü ve aynı yazmadaki iki formülün birbirini okuması, okunamayan formül, bilinmeyen işlev, olmayan sayfa, listeli hücre, toplantı tarihi, **toplantı başına adım** (U12, W89), Motor'u okuyan ortak formül, "Elle değer" hücresi ve yapıştırmada girdi olmayanın atlanması, **listelerin anahtar hücreleri** (DİBS RV, DİBS ASW ve Eurobond listelerinin ISIN'i, VİOP kontrat kodları; değerin kabulü, switch seçiminin anahtar olmaması, önceki sürümün aldığı formülün açılışta kalkıp değerinin kalması ve günlük dosyasına yazılması), **Bloomberg isteğine giren hücreye canlı formül** - Forward valörüne `=NOW()+30` reddi, `=TODAY()+30` kabulü); **sonradan oluşan döngünün dönmemesi** (E60 boşaltılınca birkaç turda durması, `#CALC!` ve nedeni, piyasa / nesil tetiklemesinde yeniden denenmemesi, üzerine yazılan değerle bitmesi); **toplantı takvimi kayınca** (araya toplantı girince kayan hücrelerde - tarih, adım, etiket - formül kalmaması, 12. satırdaki toplantının tarihine başvuran formülün toplantısıyla bir satır aşağı gitmesi - `=OIS_MAIN!P13+1` - ve değerinin aynı toplantıdan gelmesi, yazılan adımın toplantısıyla taşınması, reddin sürmesi; önceki sürümün kayan hücreye aldığı formülün açılışta kalkıp değerinin kalması ve günlük dosyasına yazılması); **piyasayı izleyen formülün masa değişikliği saymaması** (her tikte değerin izlemesi, sayacın kıpırdamaması); **süre sınırı** (sınır aşılınca değerin kalması, "yeniden denenecek", aradaki nesillerde denenmemesi, ara bitince izlemesi, üst üste üç kez aşınca durması); **Bloomberg isteğine giren hücrede duran formülün son iyi değerini koruması** (Forward valörü, `#CALC!` değil); orada **hataya düşen formülün** de (durmadan: `#DIV/0!`) son iyi değerinin kalması, nedeninin hücrede ve `/api/cell`'de yazması, değer verince yeniden yazılması ve nedenin kalkması; değeri hata olan formülün orada yazılırken reddi, başka hücrede hatanın değer olması; **tatil listelerinin** (EK_TATIL'in USD / EUR tarih ve adları, Motor'un TRY listesi, DİBS ASW'deki kopyası) formül almaması; **duramayacak formülün kalkması** (artık girdi olmayan, ortak olmuş, bu sürümün kabul etmediği - Bloomberg -, tatil listesindeki formülün açılışta ve senaryo yüklenince kalkması, değerinin kalması, "Girdilerim"in ve kaydedilen senaryonun onu artık içermemesi, günlüğe nedeniyle yazılması); **yetki** (Motor'u okuyan ortak formülün yöneticiye de reddi, kişiselin sahibinin o anki rolüyle okuması - yetki alınınca durup nedeni, geri verilince yeniden okuması); **duran formülün yeniden denenmesi** (sahibinin ilk yazmasında hemen, yine durunca aradaki yazmalarda denenmemesi, ara bitince yeniden); **kuyruğa alınamayan turun bir şey bırakmaması**; **silme ve sıfırlamalar** (Delete, hücrenin kendi sıfırlaması, "Girdilerimi sıfırla", ortak sıfırlama, üzerine yazılan değer, yapıştırılan formül); senaryonun formülleri saklaması; **formül yokken hiç iş yapılmaması** (yeni nesilde iş kuyruğa bile girmez); **yeniden başlatmada kalması** (ortak formülün açılışta, kişiselin kullanıcının hesabı kurulunca hesaplanması, sonra yine izlemesi); HTTP (`/api/inputs`, `/api/cell`, `/api/view`, `/api/my-inputs`, `/api/reset`); `test_store.py`'de formülün değerin yanında saklanması (eski veritabanına sütunun eklenmesi, üzerine yazılan değerin formülü silmesi, senaryonun dördüncü öğesi, toplantıyla taşınan hücrenin değerinin formülsüz taşınması, formülün kaldırılınca değerin kalması, her yazmanın bildirilmesi); `test_store.py`'de **kâğıt satırlarının değerlerinin taşınması** (herkesin, masanın ve senaryoların değerleri, dolu hücrenin üzerine yazılmaması, formülün taşınmaması, anahtar hücreler ve listenin kaydıyla tek işlem; yarıda kalan yazmanın hiçbir şey bırakmaması) |
| `test_copies.py` | **Geçici kopyalar** (`tto/copies.py`, motorda `LayerCalc`). Motorun katmanları küçük kitaplarda: kopyanın girdisinin yalnızca kendi sonuçlarını değiştirmesi (kullanıcının, herkesin, başka kullanıcının, başka kopyanın değişmemesi), alttan gelenin - kullanıcının girdisi, ortak girdi, saat - kopyaya ulaşıp kopyanın yazdığı hücreyi geçmemesi, aynı gruptaki girdilerden birini yazan kopyanın diğerlerini kullanıcınınki gibi görmesi, **maliyet** (kopyanın yalnız kendi girdisine bağlı hücreleri hesaplaması, gerisini kullanıcıya / herkese bırakması ve bir daha hesaplatmaması), **Bloomberg'e hiç sormaması** (BDP / BDH hücresinin altta, kullanıcının argümanıyla bir kez sorulması, kopyaya yazılan ticker'ın isteğe girmemesi, BDH dizisinin hücrelerinin ortak hesapta boş kalmaması, BINTERPOL'ün kopyanın değeriyle hesaplanması), kullanıcı bırakılınca katmanlarının gitmesi, **rastgele karşılaştırma** (her adımda her kopyanın her hücresi kullanıcının girdileri ve kopyanınkilerle sıfırdan hesapla aynı; kullanıcıların ve herkesin değerleri katmansız hesapla aynı). Gerçek kitapta: kopyalanabilir tabloların listesi, girdilerinin kişisel olması, hiçbirinin Bloomberg isteğine girmemesi, toplantı satırında ya da tatil listesinde olmaması, ortak girdili / gizli / girdisiz tablonun reddi; KIRIK VADE'nin kopyasında başka bir valörün yalnız kopyanın günlerini ve forward'ını değiştirmesi (tablonun, ikinci kopyanın, başka kullanıcının değişmemesi), kopyanın tablonun hemen altında, aynı sekmede "… · kopya 2 / 3" olması, tabloda yazılı değerle başlayıp sonra ayrılması, yazılmamış hücrenin tabloyu izlemesi, `Delete` ve sıfırlamalar; TARİH ARASI FORWARD'ın kopyasının tarih şeridiyle gelmesi; ret ve nedeni (formül, girdi olmayan hücre, ortak girdili tablo, bilinmeyen kopya, kopyanın kopyası; yapıştırmada atlananın sayılması); **sınırlar** (tablo başına 5, toplam 20, boşalan numaranın yeniden alınması); **canlı veri** (altın spotunun piyasa kotası, masanın elle altın spotu, kullanıcının tabloya yazdığı girdi kopyaya ulaşır, kopyanın kendi değeri kalır); **Bloomberg isteği yok** (kopyanın hesabından hiçbir istek çıkmaması; isteğe giren girdinin - Forward valörü, spot valörleri - kopyada salt okunur, gri ve nedenli olması, yazılınca reddi); **maliyet** (kopyaya yazınca yalnız kopyanın panelinin yeniden yapılması, ortak hesapta hiçbir şeyin yeniden hesaplanmaması, kopyanın tuttuğu her hücrenin kendi girdisinin aşağısında olması - birkaç yüz); kişisel hesap tablosunun, girdi formülünün, senaryonun ve "Girdilerimi sıfırla"nın tabloya ait olması; **saklanma** (yeniden başlatmada değeriyle durması, launchpad ve yan panel öğesi olması, dışa aktarılan launchpad'de tablonun gitmesi, kapatınca değerlerinin, launchpad / yan panel öğesinin ve motor katmanının gitmesi, okunamayan kaydın atlanması); HTTP (`/api/copies`, `/api/cell?copy=`) |
| `test_twoway.py` | **İki yönlü tablolar** (`tto/twoway.py`; masa 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar bu şekilde olmalı"), testin kendi küçük tablosunda (`EK_TWT`: x yerinde girdi, y = 2x + taban, z = y + 100, bid / ask; bir de masanın ortak tek hücreli grubu): sayfaların bütün gruplarının kullanılabilmesi, deponun grubun kapsamında girdi olması, yerinde üyenin kendi girdisini tutması; **kullanılamayan tanımın** nedeniyle dışarıda kalması (biçim farkı, boş olmayan depo, girdi olmayan / iki yerinde üye, formül olmayan üye hücresi, iki kez ya da iki grupta kullanılan hücre, tek üye, kapsam farkı) ve hiçbir şeyin tanımlanmaması; **her üye yazılınca öbürlerinin ondan hesaplanması**, yazılanın aynen durması, öbür taraf / satırın kendi değeri, hesaplanan her değerin kendi türüyle geri yazılınca aynı satır (1e-9); **son yazılan geçerli** (öbür depoların - yerinde üyenin değeri dahil - boşalması, reddedilen değerin satırı bozmaması, `applied`'ın yalnız yazılanı sayması); **Delete** (yazılanda ya da hesaplanan bir üyede), hücrenin / deponun sıfırlanması ve "Girdilerimi sıfırla"nın satırı varsayılana döndürmesi; **yapıştırma** (satırın son dolu değerinin yazılan olması, yanındaki boşun silmemesi, yalnız boşlu satırın varsayılana dönmesi, sütun yapıştırılınca her satırın kendi yazılanı); **formül** (depoda saklanması, üyede `ƒ` ve metni, okuduğunu izlemesi, kendi satırını okuyan formülün döngü diye reddi ve nedeninde deponun değil üyenin hücresi, öbür tarafı okuyanın kabulü, `/api/cell`'in `twoway`'i, üzerine değer yazılınca formülün gitmesi); **kendi satırını okuyan formülün yazarken reddi** (yerinde üye o an elle yazılmışken onu okuyan - yazınca silinip formülden hesaplanırdı -, satırdan hesaplanan hücreyi, üyeyi ya da depoyu okuyan; nedenin üyelerin hücrelerini söylemesi, satırın olduğu gibi kalması, öbür tarafı ve satırı okuyanın kabulü); **saklanmış böyle bir formülün** (eski senaryo) `#CALC!` ile durması ve nedeninde deponun değil üyelerin; **üye olmadan önce yazılmış girdi formülünün** atılmayıp değeriyle üyenin deposuna taşınması, günlüğe yazılması ve canlı kalması (okuduğu değişince satırın izlemesi, `ƒ`); **iki yönlü olmadan önce açılmış geçici kopyanın** üye hücresindeki değerinin okununca kopyanın deposuna taşınması (satırın öbür depoları kopyanın boşu, yerinde değeri tablonunki, kopyanın zaten tuttuğu deponun kalması), kaydedilmesi, günlüğe yazılması ve kopyada görünmesi; **masanın önceden yazılmış ortak değerinin** formülüyle depoya taşınması; **satırın yalnız bir üyesini gösteren tablonun kopyası** (satırın bütün depolarının kopyanın girdisi olması, tabloda öbür üyeye yazılmış değerle başlaması, kopyada yazılan üyenin onu kopyada temizlemesi - içinden görünmemesi -, Delete'le tabloyu izlemeye dönmesi); **sayfa işaretleri** (her üye girdi, yazılan `an` - ✎ - ve `m`, öbürleri `ao`, hiçbir şey yazılmamış satırda işaret olmaması, tablonun altındaki not, "Girdilerim"in üyenin hücresiyle listelemesi, yardımcı tablodaki depo); **senaryo** (kaydedilip yüklenince yazılanların ve değerlerin aynen gelmesi); **eski "Elle değer"** (bir üyenin hücresine önceden yazılmış değerin satırın yazılanı olması, aynı satırda ikisi varsa sonra tanımlananın, hiçbirinin "Elle değer" girdisi sayılmaması); **geçici kopya** (kopyada yazılan üyenin kopyanın deposu olması, öbürlerinin kopyanın boş değeri, tablonun değişmemesi, kopyadaki işaretler, Delete'le tabloyu izlemeye dönmesi, tabloda yazılmış yerinde üyenin satırına kopyada başka sütun yazılınca nedeniyle reddi, yerinde üyenin kendisinin kabulü); **ortak grup** (herkesin görmesi, son yazanın herkes için geçerli olması, ortak sıfırlama); HTTP (`/api/inputs`, `/api/cell`, `/api/paste`, `/api/reset`) |
| `test_fwd_twoway.py` | **FORWARD KOTASYON iki yönlü** (masa 24.11.2026: "hem spread hem faizler girdi olabilsin, hangisine ben girdiysem diğerini hesaplasın"; `EK_FWD`, `tto/twoway.py`): iki matrisin beş üyeli grup olması (spread yerinde - eski girdisi D:E -, TRY % / puan / fwd aynı satırın `AN:AS`'inde, 26.11'in ON karşılığı `AX:AY`'de: `test_fwd_on.py`), depoların kişisel sayı girdisi ve hiç girdi olmamış hücrelerde olması (emekli girdiler dahil); **USDTRY ve EURTRY'de** (kendi spot'u, EUR faizi, EURTRY günü) 1M, 3M ve 12M'nin iki tarafında **TRY % / puan / fwd / spread yazılınca öbür üçünün** matrisin kurallarıyla elle hesaba eşit olması (1e-9), yazılanın aynen durması (puanda fwd = spot + puan/10000 tam), yazılmayan satır ve tarafın genel spread'de kalması; **gidiş dönüş** (her türün başlangıç olarak yazılıp hesaplanan dört değerin kendi türüyle geri yazılması: aynı satır, 1e-9, her seferinde yalnız o deponun dolu olması); **son yazılan geçerli** ve **Delete** (hesaplanan spread'de ya da yazılan değerde: genel spread'e dönüş; sağ tık sıfırlaması); **önceki sürümün yazdığı spread'in aynen okunması** (D6 / E104: TRY = OIS + spread tam, puan ve forward, sayfada yazılan diye işaretli); **Piyasa spread** (varsayılanın piyasa spread'i olması, yazılan spread'in ve TRY %'nin kalması - spread'i TRY'den -, silince piyasa spread'ine dönüş); **yapıştırma ve senaryo** (Excel'den TRY % sütunu - her satırın yazılanı, spread'ler OIS'e göre -, üzerine spread sütunu, her türle kaydedilen senaryonun sıfırlamadan sonra aynen yüklenmesi); **formül** (TRY bid %'ye `=EK_FWD!N5-0.25`: ask değişince izlemesi, `ƒ`; satırın kendi spread'ini okuyan fwd formülünün döngü diye reddi, nedeninde matrisin hücreleri); **sayfa** (iki matrisin altındaki not, 114 / 116 girdi, Masa'daki özetin de iki yönlü olması - oraya yazılan TRY % ile spread'in izlemesi, işaretler -, yazılan TRY %'de İşlem gir'in o faizle açılması, başka kimsenin matrisinin değişmemesi) |
| `test_ois_twoway.py` | **İki yönlü tarih arası ve OIS tabloları** (masa 24.11.2026; `MASA`, `EK_TARIH`, `EK_PPK`, `OIS_MAIN` FRA listesi, `TM_OIS`, `SOFR_FOMC`): grupların kullanılabilmesi, depoların kişisel girdi olması, eski girdilerin yerinde kalması, toplantı satırındaki depoların toplantıyla gitmesi; **TARİH ARASI FAİZ / FORWARD**: hiçbir şey yazılı değilken bloğun çalışma kitabının formülleri olması (spot ve ileri başlangıçta; Dönem TRY %'nin bit bit aynı), 77 değerin her biri yazılınca spread'in (1e-9) ve bütün bloğun bağımsız hesapla aynı çıkması, hesaplanan her değerin geri yazılınca aynı bloğu vermesi, son yazılanın geçerli olması (`I60`'a yazılmışın gitmesi), Delete ve "Kendi girdimi sil", sütun yapıştırma, spread'i okuyanların (FORWARD KOTASYON'un ve toplu tablonun genel spread'i, Forward P58 / O27, OIS F122) izlemesi ve eğri değişince yazılanın durması, spot başlangıçta başlangıç bacağının spread vermemesi, önceden yazılmış spread'in ve "Elle değer"in anlamı, senaryo, sayfadaki işaretler ve not, geçici kopya (kopyanın kendi spread'i; tabloda spread yazılıyken reddi); **TOPLU TARİH ARASI FAİZ**: "+ spread"ten spread (seçilen eğri ve gün esası), geri yazma, sütun yapıştırma, Kote %'nin ayrı kalması, Delete; **PPK ADIMI**: her dönemde adım / O/N'den faiz (iş günlerinde bileşik TLREF, elle çözümle) ve geri yazma, chat'in o faizdeki adımı, her çiftte sonraki dönemin faizinden / O/N'sinden / adımından spread, son yazılan; takvim değişince ve toplantı geçince yazılanların (eski "Elle değer" dahil) toplantısıyla gitmesi; **TÜM FORWARD / FRA**: hiçbir şey yazılı değilken FRA'nın eskisi gibi olması, yazılan FRA'dan bitiş bacağı (başlangıç dolumu ya da boşsa piyasa par'ı tutularak; spot başlangıçta FRA'nın kendisi), FRA yazılıyken başlangıç dolumu değişince bitiş bacağının kayması, geri yazma (1e-9), son yazılan, Delete, yapıştırılan FRA sütunu, Hedef FRA'nın aynı kalması, önceden yazılmış bitiş dolumu ve FRA'ya yazılmış "Elle değer", sayfadaki işaretler ve not; **Nakit Akışı**: oran → PV'ler, her PV → oran (kendi eğrisinde, beklenen olasılıklarla), geri yazınca TL'sine kadar aynı PV, kendi oranı olan dönem, Delete'le par; **FOMC**: O/N / adım / adım sayısından pencere faizi ve geri yazma, kararsız toplantı, WIRP ve farkı, FOMC listesi yapıştırılınca toplantısıyla gitmesi; HTTP |
| `test_fwdcalc_twoway.py` | **Forward hesaplayıcıları iki yönlü** (masa 24.11.2026: "Genel olarak tablolar bu şekilde olmalı", "tüm tablolar bu şekilde olmalı"; `extras._tto_fwd_calc_tw`, `_tto_bond_back`): on beş grubun (Interest 2 SP, SP 2 Interest, all-in, O/N - USDTRY ve EURTRY ayrı -, üç çevirici, Forward DV01, tahvil carry, TRY OIS w/Spread, valörün OIS mid'i + spread'i) kullanılabilmesi, kopyalanabilir blokların her üyesinin depolu olması, depoların kişisel girdi ve sayfanın yardımcı tablolarında olması, eski sürücü girdilerinin girdi olmaması, Carry'nin ve iki spread'in yerinde kalması; **hiçbir şey yazılmadan** her bloğun dosyanın değeri ve formülleriyle aynı olması (Forward sayfasının bütün değerleri bir önceki commit'le hücre hücre aynı); **her üye yazılınca** öbürlerinin bağımsız hesapla aynı olması (her blok, iki yarı, öbür yarının değişmemesi), **geri yazma** (hesaplanan her değer kendi türüyle yazılınca aynı blok, 1e-9); **son yazılan geçerli**, `Delete` (yazılanda ve hesaplananda) ve sıfırlama; **yapıştırma** (bir bloğun sütunu tek değer - son dolu -, iki yarıya bir satır) ve **senaryo**; **önceden yazılanlar** (sürücü girdilerine yazılmış değerlerin, eski senaryonun ve formülün değerinin bloğun yazılanı olması); **sayfa** (her üye girdi, ✎ ve `ao`, tablonun notu; başka grubu okuyan formülün kabulü, kendi bloğunu okuyanın - blokta başka bir değer yazılıyken de - döngü diye reddi); **geçici kopya** (tabloda TRY yazılıyken kopyada SP yazılması, tablonun değişmemesi, Delete'le tabloyu izlemesi); **çeviriciler**; **Forward DV01** (B ve S'de DV01'den tutar, işaretin B/S'den gelmesi, mutlak değer, `3m`); **tahvil carry** (Carry, B/E, Px Drop, günlük düşüş; B/E'nin reposu İma repo'yla aynı, boş Carry); **TRY OIS w/Spread** (bir vadeden Spread ve öbür vadeler, grafik verisinin izlemesi, Spread'in kendisi, Delete; valörün kaydırılmış OIS mid'inden spread) |
| `test_pageboxes.py` | **Sayfaların kutuları ve kendi menünüz**: yedi kutu türünün seçenekleriyle saklanması (VİOP seviyelerinde ön vade, tahtanın enstrüman listesinin tekrarsız, broker satırlarının yalnız açıkken; tablo alanlarının alınmaması), geri okunması, başka bir bölüm değişince kalması, dışa / içe aktarma; geçersiz seçeneklerin (aile, varlık, tıklama, kontrat, ürün, enstrüman, liste, banka, genişlik, yükseklik) reddi ve düzenin değişmemesi; başka sürümün kutusunun yalnız kendisinin dışarıda kalması; **menüden çıkarılan sayfaların** (`hidden_pages`) kullanıcı başına saklanması, tekrarın atılması, diğer bölümlerin kalması, sayfaya erişimin değişmemesi, sınır ve geçersiz listeler, başka sürümün yazdığının toleranslı okunması; **quant menüsü**: 19 sayfanın dört giriş ve sekmeleri (FX'te Opsiyon → spot dahil) (sıra, sekme adları, sayfanın kendi adı ve adresi, VİOP'un tek sayfalık girişi), menünün adlandırmadığı sayfanın kendi girişi; **kutuların okuduğu kısımlar**: ilk hesaptan önce quant kutusu, bilinmeyen kutu (400), tahtanın sayfanınkiyle aynı olması (satırlar, günler ve girilmeyen işlemler gelmeden), **Broker Chat'in değişiklik sayacı** (yazılan satır, bayat sınırı, sıfırlama, silme sayılır; piyasanın nesli sayılmaz; tahta okunduğu sayacı söyler), İzleme sayfasının tek listesi (izleme, alarmlar, çalanlar - masa alarmları ve notlar gelmeden), bilinmeyen kısım (400); HTTP (yeni modüller, kısımlar, 401, düzende kutu ve `hidden_pages`, nav'da menü) |
| `test_dv01.py` | DV01 Risk'in sıfır pozisyonla açılması (kova DV01'leri ve yapıştırma alanı; kullanıcının kendi pozisyonu kişisel), VİOP matrisinin DV01 satırları kendi para biriminde (TRY: TL ve USD, USD: USD; kontrat fiyatıyla çevrim, sayfada yeni satır) |
| `test_dates.py` | **Özel günler**: vadeden valörün (`2W`, `18W`, `1M` …) masanın tatil listesini (Motor!A361:A523; USDTRY'de USD tatilleriyle birlikte) izlemesi - Ramazan Bayramı'na (10.03.2027), 19 Mayıs'a ve 1 Ocak'a düşen valörün ilk iş gününe kayması, ay vadelerinin çalışma kitabının kendi `WORKDAY(EDATE(…))` tarihleriyle aynı olması; dashboard'un **ay sonunda** (30.11.2026), **yıl sonunda** (31.12.2026: spot 1 Ocak ve hafta sonundan sonra) ve **bayramın ortasında** (10.03.2027) açılması: spot ve tahvil T+1 valörü, geçen PPK'nın listeden bir kez çıkması (MPC1 bir sonraki toplantı), bütün sayfaların Python hatası vermeden hesaplanması |
| `test_holidays.py` | **TRY, USD ve EUR tatil listeleri ve iki takvimli FX valörleri**: USD listesinin Fed tatilleri (2026 günleri, Thanksgiving, Good Friday'in olmaması, cumartesiye düşen 4 Temmuz'da cumanın açık, pazara düşende pazartesinin kapalı olması, Juneteenth 2022'den), EUR listesinin TARGET2 günleri (Paskalya), hangi paritenin ortak takvimi olduğu; `EK_TATIL` (listeler, TRY kopyası, eklerin hepsinin dosyaya uyması), spot valörlerinin dashboard'un olup Bloomberg'inkinin yanında durması (Forward şeridi); **USDTRY spot T+1, TRY ve USD** (24.11 → 25.11, 25.11 → 27.11 Thanksgiving, 28.10 → 30.10 Cumhuriyet, Good Friday'de takas, 03.07.2026, Veterans Day, yıl sonu), **EURTRY spot T+2, TRY ve EUR** (01.04 → 07.04, Thanksgiving'in etkisizliği, 29 Ekim, Noel); tahvil T+1'in ve OIS spotunun TRY'de kalması; **vadeler** (spot 26.10 → 1M Thanksgiving'den 27.11: Masa, `EK_FWD`, çapraz blok, vadeler tablosu, Günlük İşlemler'in vadesi, forward kotası, Spot / FX; başka paritenin TRY listesiyle kalması; EURTRY 1M'in Good Friday / Easter Monday'den 07.04'e, USDTRY'nin Good Friday'de takas olması; EURUSD), **EURUSD'nin kendi spot valörü** (27.10.2026 → 29.10, Cumhuriyet Bayramı'nda; EURTRY 30.10: Günlük İşlemler'in vadesi ve gün sayısı, Spot / FX), **TLREF OIS spotunun TRY listesiyle** (25.11 → 26.11 Thanksgiving'de, 28.10 → 30.10, 31.12 → 04.01.2027; ondan sayılan OIS günleri, Masa'nın spotu, kırık vadede FX − OIS spotu; OIS sayfasında yanında Bloomberg valörü), Spot / FX'te EURUSD'nin iki takvimle, USDJPY'nin yalnız hafta içiyle sayılması; **düzenleme** (USD'ye eklenen günün yalnız USDTRY'yi, EUR'ya eklenenin yalnız EURTRY'yi kaydırması, tahvil valörünün yerinde kalması, yazmanın hesap motorunda öncelikli olması, saklanan sayfanın herkes için yenilenmesi, hatalı para birimi / tarih / fazla gün reddi, yeniden başlatmada kalması; HTTP: her kullanıcının düzenleyebilmesi, `ccy`'siz eski çağrının TRY olması, dosya listesine dönünce hiçbir şeyin saklanmaması) |
| `test_auth.py` | **Giriş ve hesaplar**: şifrenin tuzlu özetle saklanması (tur sayısı özetin içinde), önceki sürümün veritabanındaki kullanıcıların şifresiz etkin hesap olarak kalması, **ilk yöneticinin yalnızca bu bilgisayardan** ve yalnızca yönetici yokken oluşturulması (önceki sürümden bir kullanıcı da olabilir, girdileri kalır), yanlış şifre / bilinmeyen isim için aynı yanıt, **5 hatada 1 dakika kilit**, oturumun 7 gün sürmesi ve veritabanında yalnızca özetinin durması, çıkış; **hesap isteği** (bekleyen istekle girilmemesi, önceki sürümün kullanıcısının aynı isimle isteyip onaylanınca girdilerine kavuşması, reddedilen yeni isteğin silinmesi / eski hesabın şifresiz geri dönmesi); **yönetici işleri** (oluşturma, rol verme / alma, son yöneticinin korunması, şifre belirleyince ve hesap kapatınca açık oturumların bitmesi, kendi hesabını kapatamama); kendi şifresini değiştirme (diğer oturumların kapanması, eski şifre hatalarının kilide sayılması); **aynı anda gönderilen 20 tahminin 5'inin denenip gerisinin kilide takılması**, şifresiz hesabın yönetici yapılamaması ve istekle sahiplenilenin kullanıcı olması, kendi yetkisini bırakma, benzer görünen isimlerin tek isim / görünmeyen karakterin reddi, bekleyen istek sınırı; HTTP'de **oturumsuz her `/api` isteğinin 401** alması, **başka sayfadan (Origin / Sec-Fetch-Site) gelen değişiklik isteğinin 403** alması, sunucunun X-Forwarded-For'a inanmaması, çerezin HttpOnly / SameSite=Strict / 7 gün olması, `Authorization: Bearer`, yönetici uçlarının yöneticiye açık olması, kapatılan hesabın tarayıcısının bir sonraki istekte dışarıda kalması; `python -m tto yonetici` komutu |
| `test_presence.py` | **Kim çevrimiçi** (`tto/presence.py`): canlı akış ya da son 2 dakikada bir istek varken çevrimiçi, 15 dakika klavye / fare kullanılmayınca uzakta, sonra çevrimdışı (iki tarayıcıdan birinin kullanılması yeter; eski bir "boşta" haberi yenisini geri almaz); **çıkışta anında** çevrimdışı (biten oturumun geç kapanan akışı, geç gelen isteği geri getirmez; yeni şifre ve kapatılan hesap diğer oturumları da düşürür, isteyen sayfa kalır); listede yalnız etkin ve şifreli hesaplar (onay bekleyen, kapalı, şifresiz hesap ne listelenir ne sayılır); **son görülmenin kullanıcı başına dakikada en fazla bir kez yazılması**, çıkışta ve kapanırken hemen yazılması, geri gitmemesi, yeniden başlatmadan sonra listede kalması, hiç girmemiş hesapta "—"; önceki sürümün veritabanında son girişin `last_seen`'den bir kez alınması; **girişte son giriş ve adresi** (yanlış şifre giriş sayılmaz), değişikliğin açık sayfalara haber verilmesi; HTTP'de kullanıcıya ve yöneticiye **aynı liste, hiçbir adres yok**, yöneticinin hesap listesinde durum, son görülme, son giriş ve adresi (kullanıcıya 403), oturumsuz 401, sayfanın "biri kullanıyor" haberi, kendiliğinden yenilenmenin kullanım sayılmaması, HTTP ile çıkış. Tarayıcıda (`test_e2e.py`): iki kullanıcı üst çubuktaki listede birbirini çevrimiçi görür; biri çıkınca diğeri onu anında çevrimdışı ve "son görülme"siyle görür |
| `test_desk.py` | **Hata / Öneri, Sosyal, Ajanda** (`tto/desk.py`): bildirimin yalnızca yöneticiye gitmesi (kullanıcıda rozet sayısı yok; liste ve "İlgilenildi" 403), İlgilenildi / yeniden aç ve geçmiş; sohbetin herkese açık ve kalıcı olması (yeniden başlatmada), okunmamış sayısı, sayfalama (son 200, öncekiler, okunanı yeniden okuma), yalnızca kendi mesajını silme; ajandada masa / kişisel görünürlüğü (başkasının kişisel işi 404), gün ve saat sırası, gecikmiş deadline'ın yaşı ne olursa olsun kalması, uyarı listesi (bugün, yarın, gecikmiş), tamamlama ve silme yetkileri; metin temizliği (görünmez yön karakterleri), uzunluk ve hız sınırları (429; silmek sınırı açmaz), ajanda sayfasının sınırı; **tekrarlayan işler**: her türün günleri (Her iş günü'nün hafta sonunu ve TRY tatilini - Cumhuriyet Bayramı - atlaması, Seçili günlerin tatilde de sayılması, Ayın son iş günü: son günü hafta sonu olan ay ve Kurban Bayramı'nın ardından hafta sonuyla biten ay), başlangıç / bitiş, bugünün tekrarının günün işleri arasında ve rozette olması, sonraki zamanı, her günün ayrı tamamlanması (kim, ne zaman, geri alma; tarihi olmayan / gelecekteki / eklenmeden önceki günün reddi), uyarı listesi (15 dakika önce, saatinde, geç açılınca gecikmiş, ertelemenin kişiye özel olması ve bitince yeniden uyarı, saatinden önce ertelenen deadline, gece yarısından sonraki saatin önceki akşam uyarısı, tamamlanınca ve sonraki günlerde susması, deadline'ın rozette gecikmiş kalması), masa / kişisel görünürlüğü ve yetkiler (değiştirme, duraklatma, silme: ekleyen ya da yönetici; başkasının kişiseli 404), yeni saatin geçmiş günleri gecikmiş saymaması, duraklatma ve devam, silmenin kayıtlarıyla gitmesi, denetimler ve sınırlar (100, hız), yeniden başlatmada kalması (kurallar, tamamlanan günler, erteleme), **önceki sürümün veritabanının** yeni tabloları alıp her tablosunun satırlarını koruması, dashboard'un tatil listesini okuması ve değişince hemen izlemesi (yeni günde arka planda yeniden okunur: masanın durumu meşgul hesap iş parçacığını beklemez); bir değişikliğin yeni nesil açmadan sayfalara haber vermesi, canlı akışta bildirim sayacının yalnızca yöneticiye gitmesi; HTTP'de oturum ve başka siteden gelen isteğin reddi (tekrarlayan işlerin uçları da) |
| `test_trades_levels.py` | **Trades · hedef / stop ve İşleme al** (`tto/tradebook.py`, `tto/tradequant.py`): ürün ürün seviyelerin kendi kotasıyla okunması (oran %, paket bp, getiri / temiz fiyat, kur, prim tutarı) ve birimleri, hedefin kâr tarafında olması, değişmesi / boşaltılınca kalkması / göndermeyen düzenlemede kalması, değerin parmak izine girmemesi; ekilen değerlerle **kalan** (bp, pip - yende 0,01 -, primin %'si, puan) ve `near` (aralığın dörtte biri, tek seviyede işlem fiyatından uzaklığın dörtte biri, geçince ≤ 0), listenin ve "MTM yenile"nin `levels` sözleşmesi, seviyesizde olmaması; kapanışın hedefte / stopta / diğer sayılması (%5 tolerans); replay serviste **alarmların ömrü** - masa işleminde herkesin masa alarmı (yön: receive'de hedef ≤, stop ≥), seviyeye gelince "hedefe geldi"nin masa kaydında çalması, seviye değişince yeniden kurulması, İzleme'den (yöneticiden de) silinememesi, boşaltma / kapatma / geri açma / silmeyle izlemesi; kişisel işlemde yalnız sahibinin alarmı ve uyarısı; yeniden başlatmada tek alarm, kopyanın ve silinmiş işleminkinin düşmesi -; **İşleme al**: hangi satırların girilebildiği (outright, spread, fly, FRA, PPK, DİBS, FX spot; vol, PCA, forward, offshore, korelasyon değil) ve listenin her satırına yazılması, OIS outright'ın formu (receive 2Y, DV01'in formun verdiği 5 mn'lik nominali, giriş / hedef / stop, kaynak, kaydedilince alarmları, düzenlemenin kaynağı değiştirmemesi), OIS spread'in iki bacağı eğrinin oranlarıyla ve paketin girişte olması, DİBS'in getiriyle ve kuralıyla, FX spot'un kurlarla ve büyüklüğüyle, **FRA / PPK patikası satırının Trades'in FRA'sı olarak** (3x6, receive) FRA faiziyle - fiyat, hedef ve stop satırın FRA faizleri, bp farkı değil; DV01 paketin 1.000 $'ı -, ailenin FRA faizinin Trades'in aynı FRA'yı değerlediği par faiz olması (1×3 … 9×12, kayıtlı dosyada 1e-6 içinde) ve FRA faizi olmayanının girilmemesi, girilemeyen satırın ve olmayan satırın reddi; **Quant'tan** tablosu (aile başına sayılar, açık / kapanan, hedefte / stopta, K/Z; başkasının kişisel işleminin girmemesi); HTTP yolları |
| `test_trades.py` | **Trades** (`tto/tradebook.py`): her ürünün ve OIS yapısının (outright, PPK, spread, fly, FRA `3x6`; DİBS fiyat ya da getiriyle; FX spot iki dövizden biriyle; FX opsiyon) girilmesi, saklanması ve masanın diliyle söylenmesi, değiştirilmesi, kapatılması, geri açılması, silinmesi; zorunlu alanlar (işlem tarihi ve fiyatı her üründe, ileri tarihli işlem, valör, vade, bacaklar, ISIN, parite); **DV01'den nominal** (5 mn'a yuvarlama - yarım yukarı -, en az 5 mn, o nominalin gerçek DV01'i, elle yazılan nominalin kalması, hangisinin yazıldığının saklanması, bacakların formdaki sırası); **kişisel işlemin yalnız sahibinin olması** (başka kullanıcıya ve yöneticiye her yoldan 404) ve masa işlemini yalnız girenin ya da yöneticinin değiştirmesi; **kayıt** (kim, ne zaman, alan alan ne); **kapanış kaydı** (günde bir kez, saatinde; kapalıyken kaçırılan gün açılışta o günün tarihiyle; hafta sonu ve tatilde yok; aynı anda dört istekte tek kayıt; kapanan ve sonradan girilen işlemin girmemesi); **dönem K/Z'ı** ekilen değerlerle (günlük, hafta sonunu aşan haftalık, toplam - carry + fiyat etkisi; gerçekleşen nakit; kapanan işlemin gerçekleşeni ve haftaya girip güne girmemesi; bugün girilen, geriye tarihli ve kapanıştan sonra değişen işlem; spread ve FRA bacakları ve kalan; opsiyonun MTM'inin primi düşülmüş olması; cuma kapanışının üç günlük carry'sinin hafta sonuna yayılması - `carry_days` -); **kupon ödemesi iki kapanış arasında** (gerçek değerleme, değişmeyen piyasa: günlük K/Z bir günlük faiz, MTM kupon kadar düşer, kapanışlar gerçekleşeni ve bacaklarınkini saklar; bacaklarının kuponunu taşımayan eski bir kapanış bacağın o güne kadar biten kuponlarıyla okunur, kalan sıfır), **Kuponlar** (masa işlemi herkese, kişisel yalnız sahibine - diğerlerine ve yöneticiye 404 -, FX'te yok, kapanmış swap kapanış gününe göre; HTTP'de replay serviste SOFR 2Y'nin iki yıllık dönemi ve 2 SIFMA günlük ödeme gecikmesi, TRY OIS 1Y'nin dönem sonunda ödenen dört çeyreği); değerlemenin yön kodları (`S` / `B`: masanın dili, paket yönü, düzenleme) ve reddettiği işlemin nedeni, kendi lotu; "MTM yenile" istenmeden hiçbir değerleme olmaması; canlı sayaç; varsayılanların değerleme modülünden gelmesi (opsiyonun teslimi, FRA tarihleri, `mpc_periods` toplantı tarihiyle, ağırlıklar; değerleme vermezse vadenin spot'u ve bugünün tarihi); eski veritabanı; HTTP'de her yolun oturum istemesi, sayfanın menüdeki yeri, işlemlerin masanın hesaplarına girmemesi ve **PPK işleminin takvim kayınca toplantı tarihiyle kalması**; **FX spot ve DİBS K/Z'ına fonlamanın girmesi** (masa, 19.11.2026: dönem dönem değer değişimi + kapanışlardan sayılan fonlama, `c` carry, `f` yalnız fiyat hareketi - getirisi yerindeki DİBS'te sıfır -, işlem tarihinden bu yana "Fonlama"; fonlamasız eski kapanışta FX spot'un carry'si, DİBS'in sonraki ilk bilinen fonlaması; kapanmış FX spot'un gerçekleşeni fonlamasıyla), eski kuralla saklanmış gerçekleşen K/Z'ın listede yeniden hesaplanıp MTM yenile'de kuralıyla saklanması (fonlaması bilinmeyen DİBS ve OIS olduğu gibi); **DV01 · vade** tablosu (Günlük İşlemler'in "OIS · vade özeti" gibi: vade başına ödenen / alınan tutar, tutarla ağırlıklı faiz, DV01, net - payer + - ve net faiz (R·S − U·V) / (S − V), faizsiz toplam; TRY OIS ve SOFR ayrı; çubukta tahvil - alış − - ve SOFR ayrı; değeri olmayan swap bilinmeyen sayılır, FX yok; MTM yenile'yle saklanıp listede değerlemesiz okunması, kapanış kayıtlarının onu tutmaması); **FX opsiyon formunda primin vol'ü** (24.11.2026, gerçek değerleme, testin piyasası): önizlemenin `vol`'ü - formun piyasasında primin vol'ü, strike'taki smile vol'ü ve verdiği prim (`premium_vol`'ün aynısı; tenörle yazılan vadenin tarihleri), o vol'de opsiyonun yazılan primi etmesi, hiçbir vol'ün ulaşmadığı primin nedeni, başka üründe ve okunmayan formda olmaması; MTM yenile'nin satırında `vols` (kullanılan ve primin vol'ü), günlük kapanışın saklamaması |
| `test_prop.py` | **Prop** (`tto/prop.py`, `/api/prop*`): masanın örneği (USDTRY 44,35 → 44,55, 500k TL: SHORT, ham 2,5M, **2M USD**, gerçek kayıp **400.000 TL**, 1M başına 200.000 TL); **iki yönlü: kaybın yerine büyüklük** (2,5M → 500.000 TL, her çevrim yolunda büyüklükten kayıp ve o kaybın geri verdiği ham büyüklük, 1M'in altındaki büyüklük de, panelin isteğinde `size`, ikisi birden gelirse kayıp, okunuş ve retler, HTTP'de eski isteğin aynen okunması); **1M'e aşağı yuvarlama** (2M'in kaybından bir lira eksik → 1M; tam 2M'in kaybı → 2M, mesafenin kayan nokta gürültüsüne rağmen; 1M'in altı → 0 ve 1M'in kaybı; bir tarama boyunca gerçek kayıp yazılanı hiç geçmez, bir 1M'den fazla da altında kalmaz); stop girişin altında long, üstünde short, eşitse ret; giriş boşsa canlı orta kur; **her çevrim yolu** (USDTRY TL / USD kayıp, EURUSD TL kaybı USDTRY'den / USD kaybı olduğu gibi, USDJPY USD kaybı USDJPY'yle / TL kaybı, EURTRY USD kaybı; fiyatı olmayan EURUSD'nin TL çaprazı EURTRY / USDTRY, USD üzerinden EURJPY); yazılanın okunuşu (`500k`, `1mn`, `2,5mn`, `250 bin`, İngilizce sayı biçimi) ve Türkçe retler (masanın listesinde olmayan, fiyatı olmayan parite, eksik / anlaşılmayan girdi, TRY / USD dışı döviz); açılışta fiyatı olan pariteler masanın sırasıyla. **Trades'in kendi defterinde gerçek değerlemeyle ürün ürün stoptaki kayıp**: TRY OIS / SOFR / FRA DV01 × bp (ve eğri 25 bp kayınca MTM kaybıyla %2 içinde aynılığı), spread / fly seviyenin DV01'i (bacakların yarı toplamı) × bp, DİBS fiyatla nominal × fiyat farkı / 100 (61.250 TL) ve getiriyle DİBS RV DV01'i × bp, FX spot USDTRY (2M TL) ve EURUSD (50.000 USD), FX opsiyonun prim farkı ve deltanın verdiği spotun yeniden fiyatlamayla tutması; **geçilmiş stop** (Stoplar'a 0, ötesi ayrıca), stopsuzların DV01 / tutar / delta'sı, değerlenemeyen kâğıt (bilinmeyen olarak sayılır), toplamın sırası; **Bugün K/Z = Trades listesinin "Günlük"ü** (Kişisel ve Masa; MTM yenile yokken ve başka günün MTM'sinde K/Z yok); **limitin kişiye özel olması** (kv `prop.limit:<kullanıcı>`, reddedilen değişiklik eskisini bırakır, boş limit kaldırır); **kalan alanın aritmetiği** (kâr alan açmaz, zarar alır; USD limit TL'ye bugünkü kurla; piyasa stopa gelince zarar stoptakini alır, kalan aynı kalır); Kişisel / Masa / başkasının kişiseli hiç; HTTP'de oturumsuz 401, hatalı girdi 400 ve Türkçe sebebi, örneğin kayıtlı veriyle aynısı |
| `test_bugun.py` | **Bugün** (`tto/bugun.py`, `GET /api/bugun`): menüde Masa'nın hemen altında; her bloğun "yok" hâli; RET'in bugün yüklenip yüklenmediği (başka günün yüklemesi bugünün değil), kim, adil değerin güncellemeleri ve pencerenin sekmesi; açık işlemler son MTM'in günlük / toplam K/Z'siyle (MTM'den önce K/Z yok, sonra girilen işlem söylenir), **başkasının kişisel işlemi hiçbir zaman**, `levels` sözleşmesi yokken hiçbir şey, varken hedefe / stopa yakınlar (önce stop; okunamayan seviye yok sayılır); quant'ın önceki kapanıştan beri açılan ve "YENİ" satırları beklenen kâra göre (kapanıştan önceki ve kapanmış girişler değil; FX satırında enstrümanın fiyatları ve ödül / risk; listeden çıkmış girişin kayıttaki hâli; ilk 8 ve kalanı); DİBS kapanış kaydının iş günü kapanışta bir kez alınması (önce değil, hafta sonu değil), kayda göre sinyali dönen kâğıt ve sıfır kupon eğrisinin eşiği geçmesi (quant geçmişine göre), dönen yoksa "yok"; chat'te girilmemiş işlem (girilince düşer); **modelin kendi seviyesindeki quant satırı** (FRA / PPK) giriş / hedef / stop'u FRA faizinde, birimi "6x9 FRA %", patika farkı notta - listeden çıkmışı kaydın tuttuğu faizlerle; Ajanda'nın bugünü (başkasının kendi işi değil), geciken deadline, bugün PPK; çöken bloğun nedeni ve diğerlerinin durması; HTTP (oturumsuz 401) |
| `test_commands.py` | **Ctrl+K komutları** (`tto/static/js/commands.js`, Node ile): `ret` / `ret yayınla` / `ret elle`, `işlem gir` (parite, vade kısayolları - `1m`, `3a`, `1yıl`, `2h`, ay sonu, tarih -, iki sayı biçiminde tutar, al / sat; önce vade: `5m` beş ay, tek başına `10mn` tutar), `trade` (OIS / SOFR / DİBS / spot / opsiyon; rec / pay, DV01, call / put), `kâğıt ekle` (bir ya da birkaç ISIN), `senaryo` (kayıtlı, S1–S3, piyasa; hiç yokken önce S1–S3), `sayfa`, `launchpad`; Türkçe ve ASCII yazım, büyük / küçük harf; okunamayanın ne beklediği; ilk kelime yazılırken kalıp; tablo aramalarının (`interest`, `Opsiyon` …) komut sayılmaması. Node.js yoksa atlanır |
| `test_service.py`, `test_server.py`, `test_store.py`, `test_inputs.py`, `test_config_cli.py` | Kişisel/ortak girdiler, senaryolar, RET, kalıcılık, HTTP API, yapıştırma/ayrıştırma (nominal, DV01 hedefi ve P&L hücrelerinde `100m` / `2,5mn` / `500k` / `5k`; anlaşılmayanın reddi, başka hücrede `3m`'nin metin kalması; tarih sanılan spot / faiz / fiyat / ISIN hücrelerine yazılabilmesi; B/S listesinde `Al` / `Sat`'ın karşılığı, başka metnin reddi), port kuralı, manuel spot (VİOP ve Masa'nın ilk tablosu, üst şeritten giriş, temizleyince Bloomberg spotu), **elle değer** (formülün üzerine yazma: yalnızca sahibinin, yalnızca ona girdi görünür, silince / "formüle dön"le formül geri gelir, yeniden başlatmada kalır), hesaplayıcıların otomatik dolan girdileri (Forward ve VİOP: tarih, spot, döviz faizi), sekmeli sayfa çıktısı ve arama kutusunun verisi, işlem defterinin aralık / DV01 / tahvil fiyatı uçları; **operasyon**: piyasa ve izleme döngülerinin hatalarının günlük dosyasına bir kez ayrıntısıyla yazılması (tekrarı sayılır) ve durumda son hata / hesap motoru kuyruğu, beklenmeyen sunucu hatasının tarayıcıya kısa, günlüğe tam gitmesi, piyasa saatleri (hafta sonu, masanın tatili, ayarlar); **veritabanı**: yarıda kalan yazmanın geri alınması (paket bacakları ve silinmesi, chat yapıştırma, hesap silme - ikinci adımı reddeden tetikleyiciyle), her kaydın diske yazılması (`synchronous=FULL`), **yedek ve geri dönüş** (yedeğin tek dosya ve tutarlı olması, sonraki yazmaları içermemesi, açık veritabanının yerinden alınamaması, önceki halin saklanması, bozuk / başka bir dosyanın reddi, komut satırı), gece yedeğinin zamanı (saati, kaçırılanın açılışta alınması, başarısızın beklemesi) ve en yeni 30'un kalması, **ikinci kopya** (D:\tto-yedek'in yalnızca kurulu dashboard'un varsayılanı olması; başka klasöre aynı adla kopya, orada da 30; sürücü / klasör yazılamazken yedeğin yine alınması, hatanın bir kez günlüğe yazılması, tek gecede alarm olmaması, iki gece üst üste alarm, düzelince kapanması; yedek klasörünün kendisinin reddi), **geri dönüşün iki klasörden de** (yol ya da yalnızca adla), **bozuk dosyanın açılışta söylenmesi** ve hiç açılamayanın en son yedeği göstermesi, **chat ↔ blotter** ucu (durumdaki "girilmedi" sayısı, liste, yok sayma ve geri alma, oturumsuz karar, hatalı istek), Broker Chat tahtasının **bayat sınırı** ucu; **tatillerin tek yerden düzenlenmesi** (üç kitabın - TRY, DİBS ASW, Borsa Swap'ın kopyası - birleşik listesi, ABD / FOMC tarihleri, üçüne birden yazma, Borsa'nın T+1 gününün kayması, WORKDAY'in izlemesi, hatalı / fazla tarihin reddi, yeniden başlatmada kalması, HTTP); **Motor yalnız yöneticilere** (menü, arama, Masa kısayolu, 403; servisin kendisi için açık), Eurobond Kotaları ve OIS · Nakit Akışı adları; **hız / dayanıklılık**: hesaplama iş parçacığının önceliği ve aynı sayfanın bir kez hesaplanması, meşgul hesaplamada sunucu iş parçacığı tutulmaması (statik dosya ve giriş cevap verir), oturumun bir dakika tutulup çıkışta hemen unutulması, tarihçe durumunun taramasız sorulması, sayfaların hesap başına saklanıp yalnız değişen panelin yeniden yapılması (`since`, `panels`; sıfırdan yapılanla aynı), nesil bildiriminin saniyede bir olması, sabitin üzerine yazılınca kimsenin değerinin silinmemesi (sıfırdan hesapla aynı), kayıtlı elle değerlerin ve senaryoların açılışta tanımlanması, kendi girdisi olanın piyasayı birkaç saniyede bir izlemesi ve uzun süre yokken hesabının bırakılması, ısınma, Bloomberg sayacı ve cevaplarının saklanması (kotalar da; türe ve anahtara göre sayaç, Bloomberg'in kendi limiti), JSON'a yazılamayan sayının `null` gitmesi; **Forward DV01'in Spot / Rate'i** (`O32 = +F2`, `O46 = +E33`): formül varsayılanlı kişisel girdi, yazılmadıkça formülün değeri (sayfanın spotu ve RET ortası forward'ı - başka kullanıcının da), yazılınca DV01'lerin onunla (DV01_TRY = ±tutar × kur × T × DF_TRY / 10.000, TRY_USD_DV01 = DV01_TRY / spot), yalnız yazanın; silince formül ve yine okuduğuna bağlı (`F2` yazılınca Spot da); **tarihçe bellekte** (kapanışlar, izlemenin kapanışları, PPK geçmişi: okumalar dosyaya gitmez, dosyadakiyle birebir - -0,0, tam sayı, NaN, sıra -; her yazma hemen görünür, işlem içindeki yazma commit'te, geri alınan işlem bellekten de geri alınır, zincirleme ad değişikliği, yeniden açılış; bozuk dosya yine açılır, tarihçesi dosyadan okunur) |
| `test_page_after_write.py` | **Yazılan, tam o anda istenen sayfaya da gelir** (`Service._wrote`): DİBS RV'de kâğıdın fiyatı, ISIN'i sonraki boş satıra yazılıp eski satırdaki silinince - yazma hesaplama iş parçacığında uygulanıp sayfalara haber verilmeden önce istenen sayfanın taşınan fiyatı getirmesi (eski satır boş, fiyat yeni satırda), sonra "değişmedi" demesi, baştan açılan sayfayla aynı olması; **kâğıdın hızla gidip gelmesi** (hesap meşgulken art arda gönderilen üç yazma - eski satırın ISIN'i silinir, geri yazılır, yeni satırınki silinir - ve arada istenen sayfa: gönderildiği sırayla uygulanması, her birinin cevabı söyler; fiyatın kâğıdın satırına dönmesi, sunucuda ve sayfada) |
| `test_server.py` (sıkıştırma) | **Büyük JSON cevaplarının gzip'li gitmesi**: gzip kabul eden istemciye 1 KB'tan büyük cevap gzip'li (`Content-Length` sıkıştırılmışın boyu, `Vary: Accept-Encoding`, açılınca aynı JSON - aynı cevapta aynı baytlar), küçük cevap, gzip istemeyen ya da `q=0` diyen istemci ve hata cevabı düz; `Accept-Encoding`'in q değerleriyle okunması; canlı akışın (`/api/events`) gzip kabul eden istemciye de hiç sıkıştırılmaması; JSON olmayan cevaplara (akış, düz metin, indirilen dosya) dokunulmaması |
| `test_backup.py` | **Günlük yedek**: varsayılan saatin 17:30 olması (ayarlar, komut satırı, yedeğin zamanı, alarm sayfasının eşiği); **öncelik**: yöneticinin seçimi > komut satırı / ortam değişkeni > varsayılan (ayar ayar, nereden geldiği, boş ikinci kopyanın "yok" olması, yeniden başlatmada kalması, *Varsayılanlara dön*); **yeniden başlatmadan** geçerli olması (yeni saat bir sonraki bakışta, yeni klasöre hemen ilk yedek, eskilerin taşınmaması ve her klasörün kendi 30'u, başarısız klasörün yerine seçilenin hemen denenmesi); **klasör denetimi** (göreli yolun, sürücüsüz kökün, hatalı saatin reddi; OneDrive'ın ortam değişkeniyle ve OneDrive / Dropbox / Google Drive / iCloud Drive / Box klasör adlarıyla **bulut eşitleme klasörünün** - orada hiçbir şey açılmadan - Bloomberg / şifre gerekçesiyle reddi, açılamayan ve yazılamayan klasörün reddi, ikinci kopyanın yedek klasörünün kendisi olamaması, hatanın alan alan söylenmesi ve hiçbir şeyin kaydedilmemesi, uygun klasörün açılıp deneme dosyasının silinmesi); **D:\tto-yedek'in yalnızca D: sürücüsü olan bilgisayarda varsayılan olması** (sürücü denetimi taklit edilerek), ikinci kopya yokken alarm olmaması, seçilen ikinci klasörün iki gün üst üste alınamamasında alarmın klasör adı içermemesi; **yedekten dönüşün seçilen klasörlere de bakması** (önce onlar, yalnızca adla); **Şimdi yedek al**ın seçilen klasörlere yazması (dosya, boyut, ikinci kopya, listeler); **seçilen klasöre yazılamazsa** (paylaşım kapalı): günün yedeğinin `data\backups`'a alınması, ikinci kopyanın ondan yine alınması, klasör adı içermeyen veritabanı alarmı, günün yedeklenmiş sayılması (döngü ne kadar bakarsa baksın ve yeniden başlatmada ikinci tam yedek yok), seçilen klasörün yarım saatte bir denenmesi, açılınca dosyanın oraya bütün kopyalanması ve alarmın kapanması, birkaç günün sayılıp ilk doğrudan yedekle birlikte gitmesi, seçilen klasöre sonradan kendi yedeği alınan günün üzerine yazılmaması, ikinci kopya `data\backups`'ın kendisiyken dosyanın kendisi; seçilen klasör `data\backups`'ın kendisiyken geri çekilme olmaması, ikisi de yazılamazken iki nedenin söylenmesi; HTTP: oturumsuz 401, kullanıcıya 403 (okuma, kaydetme, sıfırlama, şimdi yedek), alan alan 400, kullanıcının durumunda ve masa alarmında hiçbir klasörün geçmemesi |
| `test_datadir.py` | **Bir veri klasörüne tek dashboard** (`data\tto.lock`): kilit dosyasının içeriği (program, bilgisayar, kullanıcı, süreç, port, açılış, işaret); aynı bilgisayardan ikinci dashboard'un reddi (kim, nerede, ne zamandan beri, açık olanın adresi), `yedekten-don` ve `kurtar`ın (`--dene` de) reddi; temiz çıkışta kilidin kalkması; **eski kilidin devralınması** (süreci olmayan bu bilgisayarın kilidi hemen, işareti bir dakikadan eski olan da; günlük satırı); **başka bilgisayarın kilidi**: saati bizimkinden geri olsa da işareti kıpırdadıkça ret (bilgisayarın adıyla), saati ileri olsa da kıpırdamayınca izlenip devralınması, okunamayan kilit dosyasının da; **kalp atışı** (sırasının artması, elle silinen kilidin yeniden yazılması, başkasının devraldığı kilidin üzerine yazılmaması, haber verilmesi, çıkışta silinmemesi; iş parçacığının kilidi taze tutması); **gerçek süreçlerle**: kilit tutulurken `python -m tto`'nun veritabanını açmadan 3 ile durması, `yedekten-don` / `kurtar` / `kurtar --dene`'nin reddi, tutan süreç öldürülünce eski kilidin hemen devralınması, temiz çıkışta silinmesi; `python -m tto`'nun kilidi sunucu boyunca tutup sonra bırakması, eski kilidi konsolda ve günlükte söylemesi, kilidi başka dashboard'a geçince Ctrl+C gibi kapanması (başkasının kilidine dokunmadan); **ağ sürücüsü**: `\\sunucu\paylaşım` yolları ve Windows'un "uzak" dediği harf (taklit edilerek), yerel disk, uzun biçimli yerel yol, Windows dışı; ağ sürücüsünde **DELETE günlük kipi** (`-wal` / `-shm` yok, `synchronous=FULL`, denetim, yedek, yedekten dönüşte kalan `-journal`'ın dosyayla taşınması), yerel diske dönünce WAL, WAL'lı veritabanının ağ sürücüsünde DELETE'e geçmesi; açılışta konsolda **UYARI** ve günlük satırı, durumda kırmızı satırın metni (kullanıcıya klasör adı olmadan), rozetin penceresindeki kilit; yerel diskte uyarı olmaması |
| `test_kurtar.py` | **`python -m tto kurtar`**: bozuk bir kopyadan (Günlük İşlemler'in ortadaki bir yaprağı ve tarihçenin - rowid'siz tablo - bir yaprağı üzerine yazılmış) en son yedeğe dönülmüş veritabanına geri gelenler: günün işlemleri kendi numaralarıyla, gün içinde düzeltilen / silinen işlem (satırın kendi zamanı), yeni ve yeniden yazılan kişisel girdi, ortak girdi, yeni hesap, chat, Broker Chat (gün içinde silinen satır silinmiş kalır), Trades (günlüğü, kapanışı), ajanda, tarihçenin günü; **üzerine yazılmayanlar** (şimdiki daha yeni girdi, kendi zamanı olmayan ayar - özetteki adıyla); günün Bloomberg sayacı ve tarihçenin istek kaydının kayıt kayıt birleşmesi; okunamayan işlemlerin dizinden sayılması ve yedekte olduklarının söylenmesi, tarihçenin atlanan bölümü; bozuk dosyaya dokunulmaması, öncesinin kopyası, ikinci çalıştırmanın bir şey eklememesi (kopya da bırakmaması), özetin günlük dosyasında olması; **`--dene`** (veri klasöründe hiçbir dosya değişmez, söylediğini gerçeği yapar); **kilit** (dashboard açıkken kurtarma, denemesi, yedekten dönüş 3 ile durur, hiçbir şey değişmez); **başka kayda verilmiş numara** (yedek üzerinde girilen işlem ve Trades kaydı: bozuk dosyadakilerin yeni numarayla gelmesi, günlüğün ve kapanışın izlemesi, tekrarda çoğalmaması); değerleri bozuk satırın (okunamayan JSON, tarih olmayan tarih) alınmaması; bozuk dosyanın **`-wal`**'ındaki satırın da gelmesi (dosyanın kendisi açılmadan); tablo listesi okunamayan dosyada şimdiki veritabanına dokunulmaması; veritabanının kendisi, olmayan dosya, bozuk şimdiki veritabanı, liste; **yedeği hiç olmayan** (yeni veritabanına: tarihçenin bozuk yaprağın ötesi de - günü ilerleterek); store'un her tablosunun bir kuralı olması |
| `test_frabuckets.py` | **OIS · PPK'nın FRA listelerinde kovalar**: *TÜM FORWARD / FRA*'nın her satırında başlangıç ve bitiş bacağının kovası (aradaki vade iki yanındaki kovaya aylara göre bölünür: 12x15'in bitişi "1Y … + 18M …" yarı yarıya, 15x18'in başlangıcı da, 24x27'nin bitişi ¾ 2Y ¼ 3Y), YÖN'deki yönle işaretli DV01'i (+ pay; satırın K / L'si) ve oranı (I / J), spot'tan başlayanda tek bacak; *EN İYİ 15 FRA*'nın her satırı tam listedeki FRA'sıyla aynı; listeden Günlük İşlemler'e girilen 12x15 FRA'nın bacakları o kovalarda, o DV01'lerle (15M bacağı iki yarım satır) |
| `test_ppkcurve.py` | **TRY faizleri iki yoldan** (`tto/ppkcurve.py`): basamak eğrisinin TLREF'i Motor'un formülüyle bileştirmesi (hafta sonu terimi, takvimin sonu, iki kez yazılan toplantı, başka spot'tan görülen patika), **bir dönemin faizi ↔ içindeki O/N** (masa 25.11.2026: "B"; elle sayılmış iki hafta - hafta sonlu ve 2027 Ramazan Bayramlı -: modelin denkleminin bisection çözümüyle aynılık, tam geri dönüş, Π (1 + x·g)'ye yakınlık, her gün bileşiğe göre 1,43 / 4,31 bp; basamak eğrisinin aynı fonksiyonla bileştirmesi), ln DF doğrusal eğri, par / forward / FRA, kotaların kendi konvansiyonlarıyla swap'ları (OIS: tek dönem ACT/365, çeyreklik par; offshore: TRYI ACT/360, TRYSAQ yıllık par, ilk eksikte durma); **kalibrasyon** (bilinen kaydırmalarla kurulmuş "piyasa"nın kaydırmalarının ve eğrisinin geri bulunması, her kotanın 1e-12 içinde yeniden fiyatlanması, TLREF'in yalnız toplantıda ya da kotalı vadede adımlanıp aradaki her iş gününde iskonto faktörlerinden okunan O/N'in adımın faizi olması, sırasız kotalar, aynı vadede iki kota); **çalışma kitabıyla**: Bootstrap'ın sayfanın kendisi olması (Motor'un DF'leri, *TÜM FORWARD / FRA*'nın her satırının piyasası, Masa'nın Bootstrap satırı), MPC ima'nın Motor'un "DF ima"sı ve Masa'nın MPC ima satırı olması, PPK basamak ve offshore PPK eğrisinin her kotayı yeniden fiyatlaması (sayfanın offshore eğrisi de); **FRA listelerinde** PPK basamak ve PPK − piyasa sütunları (her satır, başlık ipuçları, kotalı vadeleri birleştiren FRA'larda ~0, 15 en iyinin tam listedeki FRA'sıyla aynılığı); **Günlük İşlemler'in FRA kotasyonu** (piyasa ve maliyet eskisi gibi, yanında PPK mid ve maliyeti, iki yön); **kırık vade bloğu** (bloğun kendi eğrileriyle bloğun piyasası - fark yalnız eğriden -, satır satır PPK ve fark, XCCY 1Y'nin gününde iki yolun aynılığı, kotalar arasında ayrılığı, geçici kopyanın kendi valörüyle); **tekrar günü** (03.11.2026: 12x15 MPC ima'da −70,0 bp, kalibrasyondan sonra −70,7; 15x18 ~+79; 12x18 aynı; kaydırmalar ±11 bp içinde; spot + 2Y3M XCCY'de iki yol ayrı, 2Y'nin gününde aynı) |
| `test_interpchart.py` | **OIS · PPK'nın interpolasyon grafiği** (`tto/interpchart.py`): Bootstrap'ın O/N forward'ının düğümler arasında eğrinin kendi ln DF eğimi olması (sentetik eğride; sayfada Motor'un ve Forward'daki offshore eğrinin her düğümünde, son düğümden sonra son aralığın sürmesiyle), PPK basamak'ın O/N'inin yalnız toplantıda ya da kotalı vadede basamaklanıp arada sabit olması (önündeki her toplantı bir basamak; offshore'da ACT/360), basamak çizgisinin kapanış noktası ve boşluğu; sayfadaki yeri (*EN İYİ 15 FRA*'nın hemen ardı, sayfa genişliği) ve sayfanın geri kalanının değişmemesi; her ufuk ve eğri (1Y / 3Y / 10Y × OIS / Offshore: spot'tan ufkun çeyreklik takvim gününe dört basamak çizgisi, şerit tablosu, kotalı vadeler - 15M / 21M değil - ve toplantılar etkin günlerinde); **FRA şeritlerinin FRA listesiyle aynılığı** (40 çeyreğin her biri: Bootstrap listenin piyasası, PPK basamak listenin PPK basamak sütunu, farkı "PPK fark"ı - metni ve rengiyle -; 1Y / 3Y şeritleri onun ilk çeyrekleri; offshore'da iki offshore eğrinin aynı çeyreklerde ACT/360 3A forward'ı); **tekrar günü** (03.11.2026: 3Y'de en büyük fark 15x18 +78,8 bp, 12x15 −70,7 bp, 9x12'ye kadar aynı; offshore'da XCCY 5Y'den sonrası uzatma) ve **kullanıcının kendi hesabı** (üzerine yazdığı 1Y kotası yalnız onun grafiğini değiştirir, başkasınınki aynı kalır; okuduğu bir şey değişmeden grafik yeniden yapılmaz); **DF görünümü** (üçüncü seçim, Faiz / DF; yollar "ufuk\|eğri\|görünüm", 12 yol, açılış 3Y OIS Faiz): gün gün PPK basamak / Bootstrap − 1 (0,01 bp), Bootstrap'ın 0 çizgisi, son kotada durması (sonrası uzatma: çizilmez, satır söyler), kotalı vadelerin işaretleri ve ipuçları (iki DF), toplantı çentikleri, tablo (kotalı vadelerde iki DF ve fark; arada kotasız kuponu olan kota söylenir), kısa ufukların uzun ufkun ilk günleri olması; sayfada her yolun eğrilerin kendi DF'leriyle aynılığı, nakit akışlarının hepsi kotalı vadede olan kotada farkın 0 olması (OIS 1M … 1Y, offshore her kota), OIS'in 18M'den sonraki kuponlu kotalarında olmaması; tekrar gününde 3Y OIS'te en yüksek +17,49 bp, en düşük −14,97 bp, 18M / 2Y / 3Y −1,47 / −0,27 / +2,40 bp, offshore 10Y'nin XCCY 5Y'de durması; PPK basamak kullanıcısının 12 yolun hepsinde Bootstrap kullanıcısınınkini görmesi |
| `test_pricing.py` | **Fiyatlama** (`tto/pricing.py`, `/api/pricing`): takvim (iş günü, EDATE, tenörün tarihi), yazılanın okunuşu (`2Y3M`, `3A`, `1 yıl 6 ay`, `12`, `2W`, tarih; tek kutuda `12x15`; girdilerin enstrüman başına saklanması), **kuponların vadeden geriye sayılması, kısa dönem başta** (XCCY 18M = 6A + 12A, 2Y3M = 3A + 12A + 12A; OIS 4M = 1A + 3A, 3M tek ödeme; tarihle yazılan vadede bloğun kuralı; ileri başlangıçta yalnız sonrası); Motor'un bootstrap'ının ve offshore eğrinin kotalardan yeniden kurulması (her düğümün / kotanın geri gelmesi; kayıtlı günde sayfanın `BOOT_LNDF`'i ve offshore eğrisiyle birebir), **Motor'un kendi kova kaydırması** (`Motor!T86`'nın 1M … 3Y ΔlnDF'leriyle her düğümde birebir), PPK'da bir kotanın kaydırılması (kaydırılmış kotaların kalibrasyonuyla aynı, öncesindeki aralıklar aynen); değer, DV01 ve NPV işaretleri (PAY / RECEIVE, AL / SAT); **Masa'nın kırık vade bloğunun kendi tarihinde ve kırık bir tarihte**: forward, puan, OIS ve XCCY'nin iki eğride bloğun sayıları (Bootstrap: F173 / F174 / F178 / F179; PPK: bloğun PPK basamak sütunu) ve XCCY takviminin bloğun yardımcısıyla (BU:BX) aynılığı; OIS · PPK'nın bütün FRA listesi (Bootstrap'ta piyasası, PPK'da PPK basamak sütunu), her OIS kotasının kendi vadesinde geri gelmesi; **kotalı vadede sıfır kuponlu enstrümanda PPK = Bootstrap** (OIS ≤3M, XCCY 1Y, TRYI günlerinde forward), kotalar arasında ayrılık; **kovaların toplamı = toplam ≈ paralel kaydırma** (iki eğride %0,5 içinde), vadeden uzak kovaların 0 olması, RECEIVE'ın PAY'in tersi, DV01'den nominal (OIS_MAIN'in kuralı), kova kaydırmalarının yeniden yapılmaması; **NPV mid'de 0, mid'in 10 bp altında PAY +N·A·10 bp**, PPK'da PPK mid'ine göre, FX'te puanla fiyat; girdilerin kullanıcıya ve enstrümana özel olması, okunamayan girdinin hatası (girdi saklı), PPK kullanıcısında kendi eğrisinin önde olması; kayıtlı günün sayıları (12x15 −70,7 bp, XCCY 2Y3M, 18M forward, XCCY 2Y'nin notu); **ters hesaplar (24.11.2026)**: NPV TL / NPV $ / peşin bp'den faiz (FX'te outright) - `level_for`'un `value`'nun tam tersi olması (swap'lar, ileri başlangıç, tarih, FX; iki yön, küçük ve büyük nominal: NPV'ye 1e-9 ile geri dönüş, faizden faize 1e-12), fiyat kutusunun okunuşu (`1.000.000`, `-250k`, `2,5m`, `%0,5` = 50 bp), türlerin enstrümana göre olması ve **eski kayıtlı girdilerin eskisi gibi okunması** (türü olmayan fiyat faiz, FX'te kayıtlı türü; Toplu kutusu boş); sayfada çözülen faizin kullanıcının eğrisinde olması (PPK kullanıcısında PPK), öbür eğrinin faizinin yanında, NPV / NPV $ / Peşin'in yazılanı geri vermesi, DV01 kovalarının ve Fiyat − mid'in o faizle faiz yazılmış gibi aynı olması, FX forward'da satılan forward'ın outright'ı; **Toplu fiyatlama**: satırın okunuşu (vade, `12x15`, iki tarih, sonda tek kelime fiyat), sayfanın kendi enstrümanı olan satırın birebir aynı sayıları, OIS'te ileri başlangıcın FRA'yla aynılığı, satır fiyatının NPV'si, satır satır hatalar, XCCY ve FX satırlarının offshore eğride olması, en çok 100 satır, PPK kullanıcısının eğrisi, **satır için eğri kurulmaması** (bootstrap, kova kaydırması, PPK kalibrasyonu çağrılmaz); **kovaların kotası** (24.11.2026): her kovanın kotası kaydırdığı kota - FRA 12x24 ve OIS 2Y3M'de `Motor!B306:B321` (OIS_MAIN'in; 1Y `OIS_MAIN!B14`, 2Y `B18`), XCCY ve iki FX forward'da Forward'ın TRYI / XCCY mid'i, hiç OIS değil -, iki eğrinin her kotayı kendi vadesinde vermesi ve kovanın kaydırılmış eğrisinin kota + 1 bp'yi vermesi, ON / 1W / 2W'de kota olmaması, PPK kullanıcısında aynı kotalar, kova satırlarının eskisi gibi + kota, Toplu satırlarında kota olmaması; HTTP'de peşin ve Toplu |
| `test_swaption.py` | **Swaption** (`tto/swaption.py`, `/api/swaption`): **iki yönlü: primden / başabaştan vol** (payer, receiver, straddle; ATM, ITM ve OTM; bp running, bp peşin, TL ve başabaşlar - kapalı formül ATM'de, Brent dışında, 1e-12; içsel değerin altında vol yok; okunuş ve Türkçe retler; kayıtlı günde tablonun her primi ve başabaşı geri yazılınca aynı vol ve aynı sayılar, 1e-9; içsel değerin altındaki prim 400 ve sebebi); Bachelier primleri (**ATM = A·σN·√T/√(2π)**, **payer − receiver = A·(F − K)**), **greek'ler sonlu farklarla** (delta, gamma, normal ve %1 Black vega, teta - bir iş günü sonraki prim − bugünkü, −∂/∂T / 252'ye yakın; ATM straddle'ın günlük başabaşı √(−2Θ/Γ) = bp/gün), **normal ↔ Black iki yönde** (derin ITM'de OTM tarafından çözüm, F ya da K ≤ 0'da yok), başabaşlar (payer K + p, receiver K − p, straddle K ± toplam), yazılanın okunuşu (vadeler, `ATM` / `%35,1` strike, `2,5mn` nominal, üç vol birimi; okunamayan ve **10 yılı aşan** Türkçe hatayla), gereken OIS vadeleri; kayıtlı günde **dayanak Fiyatlama'nın ileri başlangıçlı TRY OIS'i** (altı vade çiftinde iki eğride forward, annuity, spot, başlangıç / vade ve kuponlar birebir; 1Y × 2Y %35,7502, A 0,98771), **opsiyon vadesi başlangıçtan önceki TRY iş günü** (cumartesiye düşen başlangıçta cuma), **T = iş günü / 252** (bağımsız sayımla), her birimde yazılan vol'ün aynı fiyatı vermesi, vadede ±1σ / ±2σ, yazılan strike ve nominal, **PPK basamak kullanıcısında PPK forward'ı önde** (Fiyatlama'nınkiyle aynı), 400 / 401, hiçbir şeyin saklanmaması (kv, kişisel ve ortak girdiler aynı), menüde Fiyatlama'nın hemen altında; **uydurma geçmişte gerçekleşen vol = forward'ın günlük değişimlerinin örneklem standart sapması** (her gün kendi spot'undan, o günün kapanışlarının Motor bootstrap'ıyla, elle yeniden kurulanla aynı; son günün forward'ı sayfanın Bootstrap forward'ı; gereken vadesi eksik gün sayılmaz, gerekmeyeni eksik gün sayılır; TLREF'in fixlenmediği hafta içi gün tatil; 20 / 60 dolu, 120 / 250 olan kadar; % Black bugünkü F ve strike'ta; 60'lık vol'ün fiyatlaması, yazılanın onu geçmesi), **her günün eğrisinin bir kez kurulması** (başka vade çiftinde yeniden kurulmaması, yeni kapanışta yalnız o günün); HTTP ucu (okuma, 10 yılı aşan 400, okunamayan strike, oturumsuz 401, saklanmayan girdiler) |
| `test_interp.py` | **Eğri interpolasyonu** (`tto/interp.py`, `EK_INTERP`): motorun dayanağı (tembel IF'in öteki dalı değerin maskesine girmiyor, sayılmayan ortak yazım, kullanıcıya hesaplanan girdilerin yazdıklarının üstünde kalması); iki kitapta da ek (Motor'un 42 par formülü ve offshore adları seçimi izliyor, ASW'nin bugünkü ln DF'leri, seçim kişisel girdi, varsayılan Bootstrap); **Bootstrap'ta hiçbir şey kıpırdamıyor** (Motor'un par'ları kendi formüllerinin değerine bit bit eşit, adlar Forward'ın kendi aralıkları, düğümlerin maskesinde PPK hücrelerinin biti yok; PPK hücreleri yeniden yazılınca ortak hesapta 0 değerlendirme, girdi sayacı aynı, Bootstrap kullanıcısının sayfası "değişmedi", PPK kullanıcısınınki izliyor); **PPK'da** Motor'un düğümleri PPK iskonto faktörleri (1e-13), her kotanın par'ı kotası (1e-10), 1Y'ye kadar Bootstrap'la aynı, 12x15 FRA'nın piyasası PPK eğrisinin FRA'sı; **iki yolu gösterenler gerçek bootstrap'ı okuyor** (PPK kullanıcısının önbellekteki eğrileri Bootstrap kullanıcısınınkiyle aynı; FRA listesinde Bootstrap tarafı Bootstrap kullanıcısının piyasası, PPK tarafı kendi piyasası, fark aynı; kırık vade bloğunda da), Forward'ın vadelere göre TRY faizinde 1Y–18M arası serbest tarihin kıpırdaması / 1Y'nin aynı kalması, kırık vadede offshore kotalar arası kıpırdama / 1M kotasının gününde aynılık, ASW'nin 15M düğümünün PPK'da 3M'sinin aynı, geçmiş satırının aynı kalması; **iki kullanıcı** (biri PPK biri Bootstrap; masanın hesabı ve Bootstrap kullanıcısı aynı; rozet yalnız PPK'da, başlık Bootstrap'ta değişmedi; Ayarlar); **kendi kotası** ("Elle değer" 2Y: kendi PPK hücreleri, kendi kotasına oturuyor; öteki PPK kullanıcısı masanın kotasında; "Girdilerimi sıfırla" iki kitapta da Bootstrap'a döndürür); **Günlük İşlemler** PPK kullanıcısında da Bootstrap (OIS piyasası, MPC tarihleri, 12x15 FRA kotasyonunun mid'i; PPK mid yanında); **Trades** (15M receive: PPK kullanıcısının MTM yenile'si iki eğride, her bakan kendininkini görür - kim yenilerse yenilesin; PPK'sız eski kayıt Bootstrap ve not; Kuponlar bakanın eğrisiyle; `FOLLOW_CURVE` kapalıyken herkes Bootstrap); **kapanış kaydı** iki eğride (PPK ikizi işlemin parmak iziyle), hedef / stop alarmının seviyesi Bootstrap'tan; **HTTP**: `/api/interp` okuma / yazma / geçersiz seçim, başlıkta rozet |
| `test_curvepoints.py` | **Eğri noktaları** (`tto/curvepoints.py`, Ayarlar): vade / tarih / oran / ticker'ın masanın yazdığı gibi okunması, vadeden geriye sayılan kupon takvimi (18M = 6M + 12M), düğüm bootstrap'ı (bilinen kuponlarda kapalı, aradakinde çözülen) ve Motor'un yöntemi; **varsayılan liste bugünkü noktalar** (OIS 1M … 10Y Motor'un kota kopyası ve okuduğu OIS_MAIN hücresi, offshore TRYI 1W … 9M ve TRYSAQ 1 … 10 Forward'ın satırları, hesaplanan 18M XCCY; PPK toplantıları iki tabloda gri, takvimden) ve **her sayı eskisi gibi** (Motor'un par'ları kendi formüllerine bit bit eşit, adlar Forward'ın aralıkları, listeli / listesiz `read` aynı, hiçbir okuyucunun maskesinde listenin biti yok); **hesaplanan 18M** (6M + 12M; Bootstrap ve PPK kullanıcısında `aswfx.point_18m`'in kendisi - EK_FX'in 18M'i - ve Fiyatlama'nın XCCY 18M mid'i, kayıtlı günde %39,5879 / %39,3752; Bootstrap'ta DF'si Masa'nın kırık vade bloğunun o tarihte okuduğu; kapatılıp açılınca eğriler aynı); **Fiyatlama'nın DV01 kovaları listeden** (varsayılanda çalışma kitabının 16 kotası; elle 15M OIS: 15M swap'ının DV01'i 1Y–18M arasında bölünmek yerine kendi kovasında, kovalar toplama ve paralel kaydırmaya eşit, iki yolda, kovanın kotası yazılan faiz; kapatınca her sayı eskisi; offshore XCCY 2Y kapalıyken 2Y kovası yok, 18M hiç kova değil); **elle 2Y3M XCCY** (offshore eğride düğüm, 3M + 12M + 12M kuponla iki yolda %42,10'a aynen oturuyor, öteki kotalar da; OIS kendi formülleri) ve **elle 15M OIS** (Motor'un 15M düğümü, PPK'da Motor'un ızgarasında aynen; Motor listenin eğrisine 1e-13); **kapatılan nokta** (OIS 2Y: 21M / 24M / 27M par'ı 18M–3Y arası doğrusal, PPK artık 2Y'ye oturmuyor, PPK kullanıcısının Motor'u listedeki PPK eğrisi; offshore XCCY 2Y: 3Y'nin 2Y kuponu eğriden; açılınca bit bit eskisi); **kendi kotası** (liste farklıyken 1Y'sini yazanın Motor'u onun kotası, masanınki masanın); **PPK satırları** kapatılmıyor, takvim değişince değişiyor; **Bloomberg ticker'ı** (onaysız: maliyet söyleniyor, hiçbir şey kaydedilmiyor, Bloomberg'e hiçbir şey sorulmuyor; onayla yuva, MID soruluyor, değeri eğride; kapatınca yuva boş, yeniden açmak onay istiyor); **yalnız yönetici** (403), geçersiz eklemeler, **kayıt** (kim, ne zaman, ne; varsayılana dönüş), saklanan listenin yeniden okunması; **HTTP**: okuma, 403, ekle / kapat, ticker onayı |
| `test_views.py` | Sayfa tanımları: Masa'nın USDTRY ve EURTRY forward özetinde her spread'in yanında TRY faizi ve ON karşılığı (sütun sırası, girdiler kendi hücrelerinde - iki yönlü: TRY %, puan ve fwd de -, +25 bp yazınca TRY faizinin OIS + 0,25, EURTRY'de −40 bp yazınca OIS − 0,40 olması), tarih arası forward'ın üstündeki tarih / spread satırı (başlangıç, bitiş ve spread girdileri; 01.12.2026 → 01.03.2027 = 90 gün, bitiş forward'ının yükselmesi), her panel ve girdi gerçek hücrelere bakıyor (tablonun ipucu sütunları dahil), **her formül bir tabloda** (dört kitap + ekler, sıfır istisna), her girdi hücresine sayfasından ulaşılıyor, Forward'daki elle hesaplama araçları (USDTRY ve EURTRY) görünür tablolarda; **sekmeler**: 12'den çok tablosu olan her sayfa sekmeli, her görünen tablo bir sekmede ya da sekmelerin üstünde, sekmeler var olan görünür tabloları gösteriyor, Forward hesaplayıcılarla başlıyor, Hesaplayıcılar sayfasında aynı adlı iki tablo yok; **kaldırılan dört sayfa** (MOBIL MK, YP DIBS, Ivır Zıvır, USDTRY IYIX: yüklenen kitapta ve Sayfa gezgini'nde yok, 45 `BDP` çağrısı gitti, kalan sayfaların sırası ve numaraları, model dosyasının onları tutması, başka bir formülün başvurduğu sayfanın kalması); **her hesaplayıcının tek yeri** (kopyaların yardımcı tablo olması, Kotasyon sekmesi, Masa'daki özet, emekli tablo, limit tablosunun girdisiz kalması); **tarih sanılan girdi kalmaması** (tarih girdisi olarak tanımlı her hücrede tarih ya da boşluk); **her tablonun girdileri kendi sekmesinde** (her görünür tablonun formülleri girdilere kadar izlenir; okunan her girdi aynı sekmede - tabloda, üstündeki girdi satırında, sabit panelde - ya da masanın ortak / kurulum verisi, ya da notla anılan büyük bir girdi tablosu - Manuel Tahvil'in Girdiler'i ISIN'in okuduğu DİBS RV ve Tüm Kâğıtlar girdilerini notunda anar; DİBS RV'nin kâğıt satırlarında iki yönlü yazılanlar - `YF:YL` - Manuel temiz'le birlikte -; iki yönlü bir tablonun gösterilen üyesi deposu yazılmış sayılır, üyeleri ve depoları sayfalarının bir tablosunda; tarih arası forward'ın tarih satırı ya da forward özetinin eğri satırı kalkınca, pozisyonu anan not silinince, RET ortak veri sayılmayınca testin bunları bulması), **yeni girdi satırlarına yazılanın tabloya ulaşması** (Masa'da DEALS'e vade sınırı 1: tek kontrat; VİOP hedefinin TARGET'ta görünmesi, girdi şeridinde FRA eğrisinin "Hedef tipi"nin yanında olması; OIS'te DV01/bacak 2.000 → en iyi spread'in nominali iki katı; Carry & Roll'un OIS satırında C+R nominali ve yönü; USD'nin Girdiler'i her sekmede) |
| `test_bundled.py` | Kurulumsuz çalıştırma: her Python kuşağının paket seti, wheel özetleri ve lisansları, kurulu paketlerin önceliği, `vendor/local`, ve hiçbir paketi olmayan bir Python'la (`python -S`) sunucunun açılıp sayfa, statik dosya, giriş ve canlı akış vermesi |
| `test_quant.py` (`quant_synth.py`: sentetik tarihçe) | **Quant sinyaller**, cevabı bilinen sentetik serilerle: kayan korelasyon ve dikilmiş bir kırılma, PCA'nın dikilmiş seviye / eğimi bulması ve dikilmiş ucuz vadeyi (receive, hedge'in seviye-PCA'sının PC1 / PC2'sine nötrlüğü) ve zengin / ucuz tablosundaki z'nin sinyalin kendi canlı z'si olması, **dinamik PCA** (60 / 120 / 250 günlük pencereler, son 60 günde şekli değişen ikinci bileşenin kararlılık tablosunda görünmesi, sinyalin penceresini yazması; bir indirim döngüsünde değişim-PCA kalıntılarının zamanla korelasyonu 1 iken seviye-PCA paketlerinin ~0 ve hiçbirinin sinyal vermemesi), klasik ve PCA ağırlıklı fly / spread'in maruziyetleri (bilinen yüklerle Σ w e √λ, net DV01, fark satırı), **gün içi** (barların küçük tutulması - 20 gün, bilinen anahtarlar - ve 5 dakikaya çevrilmesi; dikilmiş barlarda 60 dakikalık ortalamadan sapmanın receive'i, açılış aralığı kırılımının yönünde pay'i ve devam beklentisi, offshore − OIS daralmasının z'si, carry patikasının önündeki USDTRY'nin sat'ı ve gerisindekinin al'ı, patikaya dönen farkta elenmeden - yarı ömrü farkın gün içi adımlarından, bar cinsinden, bir saatlik (12 bar) ufukla karşılaştırılır; patikaya dönmeyen farkın (patika etrafında rastgele yürüyüş) yarı ömür kapısında kalması ("ortalamaya dönmüyor" ya da "yarı ömür N bar: ufkun (12 bar) 2 katından uzun"), ölçülemeyen yarı ömrün ailenin bir saati (12 bar) sayılması, gün içi z'nin yarı ömür kapısının bar yazması; PPK penceresinde ortalamaya dönüşün elenmesi (carry patikası dahil), carry patikasında stop bölgesi, 17:00 sonrası hiç; kayıtlı veri modunda bar olmaması; gün içi kaydın geceye kalmaması), **geri test** (ortalamaya dönen seri yüksek isabet ve artı ortalama, rastgele yürüyüş yarı ömür kapısında kalır; gelecek değiştirilince o güne kadarki işlemler aynı; istatistikler - isabet, Sharpe, düşüş, TL -; masanın eşiğiyle susturma; servisin bütün aileleri sınayıp her sinyalin yanına kaydını koyması, API), **gerekçe** (3σ'daki ortalamaya dönen bir serinin benzer günleri yüksekte duran ve sonra dönen günler, en az bir hafta arayla; stop, rejim ve ufuktaki PPK toplantısı geçersiz kılanlarda; API'de), PCA-nötr fly / spread ağırlıkları ve DV01'leri, β'sı ve yarı ömrü bilinen eşbütünleşik çift (offshore − OIS), iki rastgele yürüyüşün çift olmaması, OU yarı ömrü, ADF'nin MacKinnon değerleri ve boyutu (rastgele yürüyüşlerin ~%5'i), Kalman'ın kayan β'yı izlemesi, rejim değişiminin bulunması (varyans oranı, Hurst), trendde momentum sinyali (pay, hareketli ortalamalar), makro betalar ve TRY'ye özgü hareket (receive), vol primi ve GARCH tahmini (sat; iki ailenin uyumu), EM carry sıralaması, VİOP takviminin faiz paritesine göre sapması (uzak sat / yakın al), **FRA / PPK konvansiyonu** (patika kendi kotalarını ≤ 3A tek ödeme / uzunlar üç ayda bir kuponla 0,01 bp içinde yeniden üretir; kaydedilmiş çalışma kitabının kendi patikası Motor!K325:K330'u 0,05 bp içinde verir; 6M kotası bozulunca 3x6 / 6x9; 5 bp altı fark tolerans), **FRA / PPK satırı FRA'nın faiziyle** (giriş eğrinin bugünkü forward'ı, hedef / stop − patikanın forward'ı = hedefin / stopun farkı, fark = seviye; bacakların şimdiki par faizleri ağırlıklarıyla; düz cümlede önce faiz, yanında "patikanın üstünde"; canlıda 6M oynayınca seviye ve faizler birlikte, patika sabit; bugünün patikası yokken son kapanışınki), **diğer ailelerin enstrüman seviyesi** (PCA kalıntısında ana vadenin faizi - hedge bacağı oynayınca hedef değişir, ana vadenin faizi değil -, DİBS ve TLREF FRN çiftinde getiri / fiyat ve OIS sabitken denge - Kalman'da da -, offshore − OIS çiftinde hiç - OIS'ten offshore seviye çıkmaz -, VİOP takvimde ima forward ve adil forward, vol priminde / tahmininde ima vol ve gerçekleşen / GARCH, gün içi z'de vadenin faizi ve 60 dakikanın ortalaması), **alarmın ve kaydın seviyeleri** (masa alarmının ve abone bildiriminin "giriş %38,719 · hedef … (6x9 FRA; patika farkı …)", kayıtta girişteki FRA faizleri, kaydın kendisi farkı izler), **faizler üç ondalıkla** (FRA'nın giriş / hedef / stop faizi alarmda ve kartta "%38,720" biçiminde, listenin okuduğu ondalık 3; % olarak giriş − hedef farkın bp farkını 0,1 bp içinde verir - masanın fotoğrafındaki %38,720 → %38,652 = 6,8 bp), PPK fazına göre eğim sinyali (steepener) ve **küçük örneklem** (kritik değerler, 1,96'nın rastgele yürüyüşte üçte bir yanılması; kısa fazda sinyal yok, uzunda var), **pariteler** (varsayılan 22 parite ve ticker'ları - GBP3M, JPY3M, GBPTRY3M, EUR3M, CNH vol'ü -, grupları, listenin denetimi, masanın listeyi değiştirince tarihçenin yeni paritenin serilerini istemesi), **FX carry** (USDTRY yılda %20 kayış, forward %30: forward pozisyonunun getirisi −%10, "Sell USDTRY forward" carry lehte, "TRY long"; forward'ı olmayan pariteye sinyal yok; carry aleyhine işlemin tampon kapısı, "elendi"), **FX'in masa dili ve parası** (işlem ufkun sonu valörlü forward'la - "USDTRY 1A forward sat" -, giriş bugünkü forward'ın kuru, hedef / stop analiz serisinin hedef / stop'unun forward kuru; 1 mn USD başına TRY = 1 mn × fiyat hareketi, forward primi = 1 mn × (forward − spot), kur hareketi = 1 mn × spotun beklenen hareketi, ikisinin toplamı beklenen K/Z; eski % × spot karşılığından farkı F / S; EURUSD'de 1 mn EUR başına USD ve TRY karşılığı, USDZAR'da ZAR ve USD / TRY karşılığı, paritenin ondalığı; forward primi ailesinde 3A forward, kâr spotun yüzdesi, prim 3A puanlarının tutma süresine düşen payı, kur hareketi beklenen kayma - carry'nin sinyalin kendi tutma süresiyle okunması -; kartın düz cümlesinin bu sayılardan kurulması; gerekçede benzer günlerin sonucunun ve stopun parayla / forward kuruyla yazılması; para ve vade yazımı - "+2.325 bin TRY", "1A", "45 gün"), momentum ailesinin kendi tezinin yazılması, parite özeti (carry, küçültülmüş kayma, tampon, karar), **her sinyalin kararı** (OU'dan beklenen kâr, carry dahil, TRY karşılığı, ödül / risk, kapıların sırası; carry'nin yediği sinyal "beklenen kâr yok"; faizde TL: beklenen = bp × ana bacağın TL DV01'i, carry + roll ve hareket ayrı, hedefte / stopta bp ve TL, "sabit faiz alınan (receive): 2Y OIS (değişken bacak TLREF)" ve düz cümle; API'de her sinyalin masa diliyle işlemi ve cümlesi, gerekçenin TL'si), forward primi ve trend kapısı, modelin kayan pencereli doğrulaması (OU geçer, rastgele yürüyüş geçmez) ve **ileriye bakmaması** (gelecek değiştirilince geçmiş tahminlerin aynı kalması); sinyal biçimi, bileşik puan ve kapılar (rejim, yarı ömür, stop bölgesi), uyum sayısı; kaydın hedef / stop / süre sonuçları ve aile başına isabet; abonelere göre süzülen alarmlar; **masa alarmları** (güç eşiği, susturma, hedefte kapanma; z'nin yanında satırın giriş / hedef / stop'u); ayarların denetimi; yeni ticker'ların tarihçeye iki yıl geriye eklenmesi; **Bloomberg'in günlük limiti**: sahte terminalle masanın bir günü (08:00–18:45, 15 dakikada bir 44 tur; 19:30'da hiç istek yok) - her serinin tüm aralığı günde en çok bir kez, kısa geçmişin ilk gününün saklanması, quant serilerinin turda 40'ar, **VİOP kontratlarının yanlarında turda 15'er** dolması (vadesi geçmiş kontrat bir kez, iki haneli yılı ancak tek haneli biçimi boş dönünce, yeni günü hiç), sonra yalnızca yeni günler - her seri günde bir kez, sonra saatte bir (önceden her turda) -, ertesi gün yalnızca geçmişi olmayanların yeniden sorulması (vadesi geçmiş kontratın değil), gelmeyen cevabın aralığı o gün değil ertesi gün yeniden sorması; günün hit / veri noktası toplamı sınırlı (ölçülen: 2.787 hit, 115.259 nokta - önceki kurallarla 97 turda 21.065 hit -; VİOP'un 419 hit; **G10 evreninin** 22 yeni serisi bir kez - quant serilerinin son turunda - sonra saatte 22 hit: ilk gün 242 hit; ertesi gün yeni günler günün ilk turunda ve bir saat sonra); hesabın motor iş parçacığı dışında çalışıp dikilmiş sinyalleri bulması; **paket büyüklüğü dolar**: ana bacak 1.000 $ DV01 (ayar), TL'si masanın USDTRY'siyle, OIS bacağının nominali annuity'den (Motor'unki, yoksa kendi par'ından), TRY ile ölçen eski sürümün kaydının dolar sayılmaması, sinyalde bacağın işlemi ve büyüklüğü, TL K/Z'nin ana bacaktan; API (her sayfa, süzgeçler, hatalı istekler, nav - menünün sırasıyla, dört giriş); **kutuların hafif kısmı** (`/api/quant/box`): sinyal listesinin sayfanınkiyle aynı olması (süzgeçler dahil, elenenler / kapsam / ayarlar gelmeden), VİOP'un canlı kontratları ve seviyeleri, WIRP'in her bankasının tablosu (matris, dağılım ve geçmiş olmadan), parite özeti; cevabın sürümü ve canlı yenilemeyle artması |
| `test_quantcurve.py` (`quant_synth_extra.py`) | **Eğri Adil Değeri**: **sinyalin enstrümanın seviyesinde olması** (vadenin faizi = NSS par'ı + fark, hedef / stop − NSS par = hedefin / stopun farkı, bacakların faizleri; kâğıdın getirisi = model getirisi + fark, kendi getiri kuralıyla, canlı getiri oynayınca ilişki aynı); NSS'in uçları ve forward'ı; OIS par'ların Excel'in kuralıyla (3A'ya kadar tek ödeme, sonra üç ayda bir kupon) hesaplanması; parametreleri bilinen bir eğrinin par'larından **parametrelerin geri bulunması** (β 1e-6, τ 1e-5 içinde); dikilmiş ucuz bir vadenin farkta kalması ve **komşularını bükmemesi** (Huber; düz EKK'dan farkı); DİBS fiyatının sayfanın BIST kuralıyla (TRT150328T24'ün kirli fiyatı ve bir bononun fiyatı DİBS RV'deki değerleriyle birebir); **bilinen bir eğriden fiyatlanan kâğıtların ne zengin ne ucuz** olması (Svensson'la; 12 sabit kuponlu uydurmada, 2 bono eğride; basit ve bileşik getiriyle, < 0,01 bp) ve 25 bp ucuz bir kâğıdın farkının kendisinde kalması; **DİBS eğrisinin Nelson-Siegel** olması (dikilmiş NS eğrisinin üç β'sı ve τ1'inin sabit kuponlulardan geri bulunması, bonoların da eğride olması, parametrelerin NS söylemesi - β3 / τ2 yok -, τ sabitken β'nın her başlangıçtan aynı bulunması); **bononun eğride fiyatlanıp uydurulmaması** (masanın kararı, 18.11.2026: bononun getirisi eğriyi oynatmaz, farkı hareketin tamamını alır, model getirisi eğrininki; bonolar da uydurulsaydı kısa uç bonoya çekilirdi); **bonoların uyumun sayısına girmemesi** (listede 5 sabit kuponlu + 2 bono, ya da 6 sabit kuponlunun 5'inin getirisi: uyum yok, nedeniyle; 6 sabit kuponluyla uyum, 2 bono uyum dışı); **model kuralı** (8 ve 40 kâğıtta da NS; OIS'te NSS); **birini dışarıda bırak (LOO)** (dikilmiş eğride hepsi sıfır; 30 bp ucuz kâğıdın LOO'su 30 bp ve kendi farkından büyük, komşularınınki küçük; LOO RMSE); carry ve roll'un düz eğride ve eğriyle aynı fonlamayla sıfır, 1 puan ucuz fonlamada beklenen kadar, yükselen eğride artı / düşende eksi roll; tarihçe getiri kuralının sayfaya göre seçilmesi; sentetik iki yıllık tarihçede dikilmiş 2Y'nin receive sinyali (paket seviye / eğim nötr), dikilmiş kâğıdın al sinyali (NS uyumuyla - sentetik eğri Svensson'un -, yalnız sabit kuponlular uydurmada, bonolar eğride, uyum dışı ve eğriye yakın; LOO RMSE; z, hedge'li paket, carry + roll, OIS farkı, en iyi kâğıt sıralaması), **kesit z**'nin uydurulan sabit kuponluların bugünkü farklarının standart sapmasına göre olması (bonolar dahil her satır; bonolar 150 bp pahalılaşınca kuponluların kesit z'si değişmez - bonoların farkları katılsaydı dağılım üç kattan geniş olurdu), canlı getirinin farkı ve z'yi oynatması, bileşik tarihçenin bileşik okunması; **işlemin bacak bacak yazılması**: seri "NS farkı", ifade her bacağın işlemi, Paket 1'in (kâğıt ve iki komşusu) DİBS uyumunun seviye ve eğimine nötr olması (bacakların nominalleriyle model fiyatları), ana bacağın 1.000 $ DV01'i ve masanın DV01'iyle nominali, Paket 2'nin (kâğıt + OIS) vadesini çevreleyen iki vadede vadeye göre doğrusal, 1:1 DV01'i ve annuity'den nominalleri, vadenin uçta tek OIS'e düşmesi, carry bilinmeyince uydurulmaması; **adil eğriden kotasyon**: bilinen bir eğriden fiyatlanan kâğıdın adil ± yarım spread'i birebir (getiri, temiz / kirli fiyat, işlemiş faiz DİBS RV'deki gibi, DV01), yarım spread kovaları ve ayarın denetimi, **switch'in DV01 nötr oranı**, eğriye göre kazancı, carry farkı ve z'si (ters yönde işaretler); DİBS RV'nin okunması (sabit kuponlu ve bonolar, floater'lar dışarıda; her satırın DV01'imizin sayfanın AI'sına eşitliği, masanın USDTRY'si ve Motor annuity'lerinin Günlük İşlemler'inkine eşitliği); servis ve **API**: iki sayfa (sinyaller, iki paketin masanın büyüklüğüyle, tablolar, kapsam, canlı yenileme), kotasyon / switch / yarım spread uçları, nav'da on altı Quant sayfası |
| `test_quantopt.py` | **Opsiyon**: 24 yeni ticker'ın adları, paketin listesinde iki kez olmaması, tarihçeye iki yıl ve doldurma sırasının sonunda girmesi; düz smile'ın **lognormal olasılıkları** birebir, **bilinen bir SVI smile'ının beş kotasından kendi olasılıklarının** bulunması (2e-4 içinde); hareketlerin **forward'dan** ölçülmesi (aynı forward'da spot fark etmez); gerçekleşen sıklıkların, bağımsız gözlem sayısının ve standart hatanın kurulmuş bir yoldan birebir; dikilmiş 25D RR'nin sat sinyali, eğim paketi, yüzey / vade yapısı / olasılık tablosu (EURUSD spot delta, USDTRY forward delta, forward'daki carry); kota yokken sayfanın nedenini söylemesi |
| `test_quantpath.py` | **İma Patikası ve TCMB WIRP**: **kalibrasyon sinyalinin dönemin faiziyle** (patika tabanı + fiyatlanan hareket; tabanı olmayanda yok; Trades'e PPK dönemi olarak girmesi); bir adımın iki ızgara sonucuna bölünmesi (−40 = %80 −50 + %20 0, ızgaradaki adım, Fed'in 25 bp'si, iki indirim arası), masanın örneği (−40 / −60: (−50, −50) %0–80, (0, −100) %20–60, (−100, 0) %0–40; TLREF − 40'tan +10 / −40 / +60, ikinci dönem 0; okumalar), olasılık aralıklarının kaba kuvvet aramasıyla aynılığı (ızgarada olmayan toplam), dönüş fiyatlanınca toplantı başına sonuçlara düşülmesi, eşit adımın %50 / %50 önden / geç karışımı da olabilmesi, kinkler ve zikzaklar (ızgaranın beşte birinin altında zikzak yok; kinkin toplantısıyla kalması), kararların fixingden ızgaraya okunması (ızgara dışı değişim karar sayılmaz; Fed'de toplantı günü görüntüsü), dikilmiş bir sapmada kalibrasyon (kovalar, toplantı sayısıyla aralık, z) ve az toplantıda sinyal olmaması, kalibrasyon sinyalinin hedef / stop'u, WIRP evrişimi (−40 / −60 → −150 %16, −100 %68, −50 %16; rastgele patikalarda matrisin beklenen değerinin ima patikayı vermesi), politika faizi çevirimi (elle / Masa!Q155 / yok) ve kovalar, geçmişin bugünkü kovalarda okunması, USD günlük görüntülerinin tutulması (değişmeyen yazılmaz, 10 dakika, yeni gün hemen, 800 gün); sentetik bir yıllık PPK fiyatlamasıyla servis (dikilmiş kinkte receive fly ve bacakları, komşuların sinyal vermemesi, kalibrasyon sinyali, Sinyaller'de sıralanmaları, USD kitabından on FOMC toplantısı ve bugünün görüntüsü), motor okumasının en düşük öncelikte tek kısa çağrı olması, kayıtlı ayın çalışma kitabının kendi çözücüsünden geçmesi (adımlar depodakiyle aynı, 22 Ekim kararı −100), HTTP API (ızgara ve politika faizi ayarı, sayfalar) |
| `test_quantlead.py` | **Öncü-Takipçi**: F dağılımının kuyruğu (kritik değerler, tamamlanmamış betanın kapalı biçimi ve simetrisi), dikilmiş 2 günlük gecikmenin β'sı, Granger p'si ve 3/3 kararlılığıyla bulunması, ters yönde de; kuralın geçmişi (isabet, gelen / beklenen); yalnızca son 70 günde olan öncülüğün 250 günde tutmaması; bağımsız serilerde (20 tohumda en çok 2) ve aynı gün birlikte hareket edende öncü bulunmaması; kendi gürültüsü olan aynı kotalarda ve ortalamaya dönen spread'de Granger'in tek başına "lider" demesi, asimetrinin demediği; lider oynamadan sinyal olmaması, yetişmemiş takipçide sinyal (Pay 2Y OIS, hedef = yetişme, stop = σ, tez), kararsız öncülükte sinyalin elenmesi, yetişmiş takipçide olmaması; **VİOP ve DİBS çiftleri** (ön vade ↔ OIS ve offshore, kontrat ↔ kendi vadesinin OIS'i, kâğıt ↔ en yakın OIS vadesi, en kısa önce, adı vadesinden; TLREF / FRN / TÜFE ve 3 aydan kısa kâğıdın dışarıda kalması; barların nerede olduğu: ön vade kendi kontratından, bono basit, kuponlu bileşik getiriden); **OIS'i izlemeyen kâğıt** (Sell / Buy, DİBS varlığı, şimdiki getirinin tarihçenin kuralındaki getiriden okunması, yetişmişte sinyal olmaması); **barların lead-lag anahtarları** (canlı değerden kendi anahtarıyla yazılması, istenmeyenin yazılmaması, hafta sonu yok, 20'ye karşı 5 gün tutulması, anahtar anahtar okunması); dakikalık barlarda 3 bar gecikmenin bulunması, bar kaynağının sezilmesi, bar yoksa "gün içi barlar yok"; iki yıllık sentetik tarihçede 5Y'nin 1Y'yi 2 gün geriden izlediğinin bulunması, her aday grubun listelenmesi, sinyal ailesi; HTTP API (ayarlar, sayfa) |
| `test_quantml.py` (`quant_synth_ml.py`: sentetik evren) | **Makine öğrenmesi**: evrenin 42 satırı evrenin anahtarlarıyla (7 G10 spot, 7 ATM 3A vol, TRY OIS outright / spread / fly, FRA 3×6, 6×9, 12×15, PPK, 2 / 5 / 10 yıla en yakın DİBS, VİOP ön vade, dört offshore satırı "offshore limiti"yle, listenin sırasıyla; evrende olmayan satırın nedeni); **dikili sürücü** (AUDUSD'nin günlük hareketi Brent'in bir hafta önceki hareketlerine bağlı): örneklem dışı isabet ≥ %62 ve ≥ 40 test, ağaç kazancında ilk Brent'in 5 günlük değişimi (her ayın modelinde Brent), satır planın biçiminde ("AL AUDUSD spot · 1 mn AUD · olasılık %65 · isabet %69 (64)"), hedef ve stop ayarlı seviyelerden (örneklem dışı tahminlerin işlemleri - satırda bir işlem, 5 kapanış, o günün 5 günlük σ'sıyla - grup başına; dikili satırın grubunun kaydı kârlı, ödül / risk ≥ 1, yeniden kurmada günün ayının seviyeleri), 5 gün, 1 mn AUD başına USD, kartın nedeni Brent'le başlar, *Örneklem* kapısı ve log-loss; **saf gürültü** (diğer G10 spotları, OIS outright'ları, sürücüsüz AUDUSD) %55 / 40 kuralını geçmez, basılmaz, log-loss > 0,69; **ileriye bakış yok** (bir günden sonrası değiştirilince o güne kadarki her tahmin bitine kadar aynı); **aylık sınırlar** (ardışık takvim ayları, 13+ ay örneklem dışı; her ayın modeli ay başından önce etiketi bilinen satırların hepsiyle, ilk ay en az 100 satırla, ondan önceki ay az; her tahmin kendi ayının modelinin; etiket 5 kapanışlık K/Z, FX'te carry'li); **süre** (küçük boyut 14 satır × 300 gün ~5 sn, model başına ~50 ms; aynı veri yeniden hiç model kurmaz; gerçek boyut 42 × 460, 512 model ~40 sn, sınır 5 dk); modellerin **canlı yenilemede** (canlı seviye ve eğri olasılığı değiştirir, ağaçlar aynı) ve aynı kapanışlarla ikinci hesapta (bütün modeller önbellekten, aynı nesneler, aynı tahminler) kalması; DİBS RV listesinin başına yeni kâğıt, VİOP sayfasının sütunlarının kayması ve takvime toplantı eklenmesiyle **hiçbir satırın durumunun taşınmaması** (aynı model nesneleri ve tahminler; yeni kâğıt 5 yılın benchmark'ı, kendi modelleriyle; PPK dönemi eklenen toplantının ardından); **geri testin walk-forward'un kendi tahminlerini oynaması** (yeniden kurmada model kurulmaz; günün z'si o günün örneklem dışı tahmini, seviyesi satırın kapanışı; satır başına tür, dikili satırın isabeti > %50); servisten sayfa (satırlar, nedenler, gruplar), Sinyaller listesinde satırın biçimi ve grubu, canlı yenileme ve ikinci hesapta model kurulmaması, geri test tablosu, HTTP (`/api/quant/ml`, Sinyaller'in bir sekmesi, sayfa dosyası); **USDTRY'nin opsiyonları** (G10 dışındaki her satırda USDTRY'nin 25D RR 3A'sı ve ATM vol 1A'sı ve 5 günlük değişimleri, G10 paritelerinin RR ortalaması - hepsi bir gün öncesinden -; G10 satırında yalnız kendi paritesinin RR'ı; kotalar yokken eksik değer, aile yine kurulur ve ağaçlar onlarda bölmez; kartta adlarıyla); **OIS ortak modeli** (on düz vadeye ayda tek model - aynı nesne -, her ayın modeli bütün vadelerin ay başından önce etiketi bilinen satırlarının hepsiyle, ilk ayı 100 günle - tek satırınkiyle aynı -, her vadenin tahmini kendi satırından, vade özelliği; spread / fly / FRA ve diğerleri kendi modelleriyle; sayfada kendi sütunu, satırında "ortak"); **ortak modelde sızıntı yok** (9M'nin bir ay başından sonraki 500 bp sıçraması öbür vadelerin o ayın sonuna kadarki tahminlerini bitine kadar değiştirmez, sonraki ayınkileri değiştirir; ileriye bakış testi ortak modelle de); **USDTRY RR'ına bağlı dikili eğri** (ortak model örneklem dışında bulur - on vadenin en az altısı kuralı geçer -, kazançta ilk USDTRY RR'ının 5 günlük değişimi; bugün pay satırı, kartta "USDTRY 25D RR 5 günde +1,50 (lehte)" ve "OIS ortak modeli 1A–10Y"); **önbellek** (aynı kapanışlar hiç, ayın ilk günü ortak model başına bir ve kendi modeli olan satır başına bir, ayın sonraki kapanışı hiç model kurmaz) |
| `test_quantoptspot.py` (`quant_synth_optspot.py`: sentetik pariteler) | **Opsiyon → spot**: pariteler anahtarlarıyla (7 G10 paritesi G10 spot'ta; USDTRY Offshore'da "offshore limiti"yle; EURTRY "opsiyon serisi yok"; tutulmayan spot "seri yok"; kısa geçmişte kapanışı ve en azı, opsiyonları henüz dolan paritede "opsiyon geçmişi kısa"), kotaların evrenin anahtarları; **dikili öncü** (USDJPY'nin spotu RR'ının hareketlerini bir hafta içinde izler): örneklem dışı isabet ≥ %58 ve ≥ 40 test, satırın AL ve masanın diliyle olması ("25D RR … USD call'ları pahalandı …, spot henüz gelmedi → AL USDJPY spot · … · giriş … · hedef … · stop … · beklenen … USD · isabet %… (…)": kurla giriş / hedef / stop, satırın büyüklüğünde USD), seviyelerin ATM 1A × √(5/252) × BF'den (hedef 1,25σ, stop 1σ, ödül / risk 1,25, 5 gün), beklenen c·μσ, olasılık Φ(c·μ ÷ s), büyüklüğün haftalık 1σ riskten, para, kartın cümlesi ve *Örneklem* kapısı, grubu, sinyal kaydında USDJPY'nin momentum öncülüğü, grafiğin örneklem dışı z(p)'si; USDTRY'nin Offshore'da SAT olması (carry lehte, kapı tutmaz); **yön seçimi** (EURUSD ters: call'lar pahalanınca SAT, "geçmişte bu hareket tersine döndü", katsayısı eksi; kayıtta EURUSD ters, USDJPY ve USDTRY momentum, havuz momentum ve her ay aynı; bütün pariteler ters → havuz "ters" ve öncü, hepsi momentum → "momentum"); **saf gürültünün basılmaması** (üç tohum; 55 % / 40 kuralını şansla geçen parite bile: olasılıklar %50 ± 10, hiçbir sinyal öncü değil); **ileriye bakış yok** (bir günden sonrası değişince o güne kadarki sinyaller, tahminler, olasılıklar ve yolu içeride kalan işlemler bitine kadar aynı); **BF'nin seviyeyi ölçeklemesi, yönü değil** (kanatlar pahalıyken büyüyen haftalarda çarpanın kanıtı, hedef ve stop'un çarpan oranında genişlemesi, z ve yönün aynı kalması, bileşiğin çarpana bölünmesi; BF serileri başka bir geçmişinkiyle değişince her tahmin ve olasılığın aynı kalması); **canlı kotayla bugün** (RR'ın haftalık artışı ekranda geri alınınca z'nin düşmesi, modelin aynı kalması); **kalibre edilen seviyeler** (sinyal `sg["levels"]` taşıyınca - katman, birleşince, hedefi ve stop'u katlarına koyar - satırın hedefi, stop'u, isabeti, işlem sayısı ve beklentisi onunkiler, kart onun katlarını, isabetini ve işlem başına beklentisini yazar, kendi 1,25σ / 1σ'sını hiç; kalibrasyon yokken ya da başka kuralda ailenin kendisi); **geri testin yollu işlemleri** (quantbt'nin alanları, 5 kapanışlık yol ve son kapanışı (`end_day`), MAE / MFE'nin yoldan, çıkış kuralı - hedef / stop / süre -, K/Z = hareket + carry, parite başına tek açık işlem, açılışın girişi geçen ilk gün olması, dikili paritelerin isabetinin > %55 olması, `add_own` ile parite parite tür); **süre** (8 parite × 500 gün ~0,3 – 0,5 sn, yazdırılır); servisten sayfa (satırlar, nedenler, sinyal kayıtları), Sinyaller listesinde satırın biçimi ve grubu (USDTRY Offshore), canlı yenileme, geri test tablosunda aile ve parite türü, işlemlerin yolu ve sinyalin geri testi, HTTP (`/api/quant/optspot`, FX'in dördüncü sekmesi, sayfa dosyası, ayar) |
| `test_duzen_quant.py` | **Quant sayfalarının düzeni** (27.11.2026): sinyal listelerinin işlemle başlaması (İşlem · Giriş · Hedef · Stop · Beklenen K/Z · Ödül / risk · İsabet; 21 sütunun hiçbiri düşmeden), 19 listenin (Sinyaller, kutusu, her analiz sayfası) tek sütun seçimi (`quant/signals`), varsayılan gizli ikincil istatistikler (Varlık, Yarı ömür, Rejim, Uyum, Kapılar - işlem, seviye, K/Z, kayıt, carry asla) ve kullanıcının kendi seçiminin varsayılanı geçmesi; veri kapsamı ve hesap durumu tablolarının yalnız Sinyaller'de (kapalı) olması, hiçbir sayfanın kendi %46 sınırı olmaması; sayfaların sırası (PCA / RV, Eğri, Korelasyon, İma Patikası, Gün İçi) ve uzun sayfaların kapalı ikincil panelleri; VİOP ve DİBS switch seviyelerinin üç ondalığı; Trend satırının ödül / riski; ekrandaki genişlik, kapalı paneller, kartın görünmesi `test_e2e.py`'de |
| `test_quantread.py` | **Quant tablolarının cümleleri** (`quantread.js`): sayfaların kurduğu her tablonun - kimliğiyle ya da sayfa adından kurulan deseniyle (`quant-*-signals`, `*-coverage`) - bir cümlesi olması, artık olmayan tabloya cümle kalmaması, cümlelerin en çok 320 karakter, tam cümle ve yöntem terimsiz (ADF, Kalman, GARCH, SVI, EWMA, OU, regresyon …) olması; desen eşleşmesinin sayfadakiyle aynı olması (kendi kimliği desenden önce) |
| `test_quanttrend.py` | **Trend** (`tto/quanttrend.py`), cevabı bilinen iki yıllık sentetik evrenle (~100 satır): dikilmiş yukarı trend AL / pay, tersi SAT / receive, sabit çevresinde beyaz gürültü zayıf satır (kapı yok: yine satır); skorun elle hesabı (1A / 3A / 1Y ÷ σ × √gün, ±2; kısa geçmişte uzun ufuk eldeki gün kadar, 63 günden kısada satır yok ve nedeni; okunamayan bir enstrümanın yalnız kendi satırında nedeniyle kalması); FX getirisinde carry; **her satırın aynı günlük riske** boyutlanması (iki anlamlı basamak, 0,1 – 10 birim; risk iki katına çıkınca boyut da) ve masanın sözcükleri; **hedef yok, iz süren stop** (yürüyen testin pozisyonlarıyla grup başına ay ay ayarlanan k - aylık σ -, satırda bugünkü σ'yla stop, ödül / risk = ortalama kazanç ÷ k ≥ 1, tutma ve beklenen K/Z kaydından - faizde + carry + roll -, zarar ettiren grubun satırı "düşük güven" ama listede; dikili trendin pozisyonu en uzun koşu); **ileriye bakış yok** (gelecek yeniden yazılınca o güne kadarki skorlar, satırlar, stop'lar ve kapanmış sonuçlar aynı - ailenin kendi testinde ve geri test makinesinde); geri testte **günlük pozisyon** (ilk günde açılır, dönüşte ya da stopta kapanır, hedef ve süre yok, dönüşte ters yön aynı gün); yön dönünce **YENİ**; grupların sırası, grubun içinde beklenen K/Z'ye göre (düşük güvenliler sonra); Offshore satırlarında "offshore limiti"; satırın **planın biçiminde** olması ve kartın cümlesi; isabetin enstrümanın, az işlemde grubunun olması; servis: tam hesapta Trend satırları, Trend sayfasının görünümü, dönüşte kayıt ve alarm (günde bir kez; eski yön "dönüş"le kapanır; düşük güvendeki satır yazılmaz - sentetik tarihçede bütün grupların iz süren stopu zarar ettirmiş olabilir, bir satırın kaydı kârlı yapılır); HTTP'de sayfa, ayar ve menüdeki sekme; ~100 satır × 2 yılda tam hesaba eklenen süre (yazdırılır) |
| `test_quantviop.py` | **VİOP**: **sinyalin kontratın ima faiziyle** (OIS + fark, hedef / stop'un da; her birinin yanında bugünkü spot ve USD faiziyle kontrat fiyatı - VİOP sayfasının formülünün tersi); kontrat ticker'ları ve vadeleri (tek haneli yılın en yakın yıla okunması; ayın son iş günü, 29 Ekim'den ve Bayram'dan önce bir gün erken, 1 Ocak / 1 Mayıs'tan önce değil), işlemdeki ilk altı ve önceki 24 ay (vadesi geçmişin iki haneli yıllı ticker'ı), tarihçe serileri (kapanış / en yüksek / en düşük); **ima faizin VİOP sayfasının formülü** ve tersi (fiyat), EK_VIOP'un USD çizgisi (30 güne düz, 1M / 3M / 6M / 1Y arası doğrusal, eksik vadenin komşulardan); sabit vadeli serilerin dış değerleme yapmadan doğrusal olması; ay sonuna kalan iş günü ve **dikilmiş bir ay sonu etkisinin bulunması** (ortalama, t; sürüklenmeye yalnız belirgin günler); **yansıma ilkesi simülasyona karşı** (iki yönde sürüklenmeyle), tersi (seviyenin olasılığı 1e-6 içinde) ve merdiven; **kalibrasyonun bilinen bir OU sürecinde c ≈ 1 bulması** (isabetler olasılıklara 0,12 içinde), kısa geçmişte boş; gün içi profil ve ufukların varyansı (bugünün kalanı, hafta, seans bittikten sonra, cumartesi); **5 dakikalık barlar**: depo (boş gün de hatırlanır), plan (en yeni gün önce), budama, canlıda yenileme başına 4 istek, yanıt gelmeyince durma, kayıtlı veri modunda hiç istek; **sahte terminalde barlar ve maliyeti** (iki kontratın işlemleri ve USDTRY bid / ask × 20 iş günü: 80 istek = 80 hit, 8.160 bar, 20 yenilemede; ertesi gün 4 istek, en eski gün düşer; barların ima faizi, yarım saatlik profil 09:30 … 17:30, gün içi kalibrasyon); barın ima faizinin USDTRY bid / ask ortasıyla hesaplanması; **sentetik iki yıllık tarihçede aile**: dikilmiş spread'in geri bulunması, 60 bp ucuz ön kontratta *Buy VİOP Kas26 (… kontrat) · Sell USDTRY spot* (1.000 $ DV01), bugünün ve haftanın seviyeleri (sıraları, fiyatları, adile çekilme, haftanın varyansı); **ince kotada seviyeler** (tek taraflı kotada iki merdivenin o taraftan, kotasız kontratta son işlemin ima faizinden, ikisi de yokken nedeni; kendi geçmişi olmayan uzak vadenin en yakın kontratın σ'sını adıyla alması; pencereden kısa geçmişin σ'sının kendi günlük değişimlerinden - sıfır değil -; seans bitince bugünün nedeni, haftanın seviyeleri); **takvim sürüklenmesi**: bugünün etkisi seansın kalan payı kadar - haftada da -, önündeki günler tam, seans bitince bugünden yok; servis: kayıtlı veri modunda **VİOP sayfasının on iki kontratı** canlı bid / ask ima faiziyle (Bloomberg geçmişi yok: adil değer ve seviye yok), HTTP API, sayfa dosyası, nav; Bloomberg geçmişi gelmeden EK_VIOP'un kendi günleriyle adil değer ve seviyeler |
| `test_history.py` | **Toplantı takvimi**: açıklanan tarihlerle toplu düzeltme (en yakın toplantının düzeltilmesi, 45 günden uzak tarihin eklenmesi, açıklanmamış yılların ve geçmişin kalması, 80 sınırının nedeniyle reddi, listeye ekleme, gelecektekilerin yerine koyma, kaydedince adımların toplantısıyla gitmesi, önizleme ucu) ve **geçen toplantının listeden kendiliğinden çıkması** (açılışta ve gün içinde spot değişince: MPC1 sıradaki toplantı, adım toplantısıyla, "otomatik" kaydı), **OIS sayfasında yazılan toplantı tarihinin takvimden geçmesi** (adımın toplantısıyla kalması, Delete ya da boş tarihle toplantı çıkarmanın ve listede olan tarihin nedeniyle reddi - yazmanın geri kalanı yazılır -, dosya tarihlerine dönüşün reddi); günlük tarihçe: kapanış deposu, kayıtlı `BDH` bloklarının tarihlenmesi, serilerin dosyadan okunuşu, **tarihçenin bugünkü satırı = OIS sayfası** (80 toplantı, hücre hücre), toplantı bazında fiyatlama (yapılan toplantının serisi, gerçekleşen TLREF değişimi, toplantı günü ölçümü, kotaların eriştiği ufuk), gün sonu matrisi (1 / 5 / 21 iş günü kuralı, tatil, geçmiş gün), takvim (tarih düzeltme / ekleme / çıkarma: adımların ve kayıtlı senaryoların toplantıyla taşınması; **toplantı geçince ve liste kaydırılınca** sayfalar ve her toplantının değerleri), sahte Bloomberg'le canlı tarihçe (istek gruplama, yalnızca son günlerin yenilenmesi - **günde bir kez, sonra serinin canlı fiyatından ya da en çok saatte bir; Bloomberg sorgu saatleri dışında hiç, elle her saatte; bir saat içinde yeniden başlatmada sorulmaması** -, yedek ticker, zaman aşımı; **SOFR fixing'i**: iki yıl bir kez, quant serilerinden sonra turda 40'lık sırasında, o gün bir daha sorulmaması, ertesi gün 16:30'dan önce hiç (açılışta da), sonra tek istek - pazartesinin fixing'i salı yayımlanır -, aynı akşam yeniden başlatılınca yeniden sorulmaması, 16:30'dan sonraki bir açılışta tek istek, dashboard'un akşam kapalı kaldığı günün ertesi günün isteğiyle gelmesi, ABD tatillerinde fixing yok; günün hit'leri: her referans çifti bir kez + tarihçe kuralların verdiği kadar - dört turda 430, VİOP'un turda 15'i dahil), **VİOP kontratlarının tarihçesi** (kendi sırasında turda 15, quant serilerinin 5'i yanında; vadesi geçmiş kontratın bir kez istenip yeni gününün hiç sorulmaması, iki haneli yılın ancak tek haneli biçim boş dönünce sonraki turda sorulması, ikisi de boşsa ertesi günler ve "şimdi güncelle"de değil ancak bir hafta sonra yeniden - bu arada gelen bir daha sorulmaz -, kapsam tablosunda durumları), HTTP uçları; **bir günün kotaları** (kapanışı olmayan vadenin komşularının hareketiyle taşınması, komşularından ayrılıp geri dönen kapanışın ayıklanması, piyasa hareketinin korunması), günlerin Excel'in kendi durumuna göre sınıflanması, çözücünün tutturamadığı günün seriden / min-maks'tan / değişimlerden çıkması, hatalı bir kapanışın kayıtlı ayda çözücüye ulaşmaması, eski sürümün veritabanının korunması, masanın verisi kayıtlı veri modunda açılınca **sonradan fiyatlanan günlerin silinmemesi** (pencerede hesaplanamayan gün gider, pencereden eskisi kalır); **tarihçe sayfaları bellekten** (Gün Sonu Matrisi, PPK Fiyatlama Geçmişi, satırın kapanışları, durum, Vol · Carry: tarihçe tablolarına SQLite okuması yok, dosyadan okunarak yapılanla birebir aynı) |
| `test_meetings.py` | **Toplantı satırına ait olan** (`tto/meetings.py`): kayıt - TCMB'nin tarih / etiket / adım / hesaplanan sütunları ve Motor'un iki bloğu, Fed'in sütunları, aynı satırlardaki başka tabloların ait olmaması; **başvuruların taşınması** (toplantının kendi hücresi, `$`'lı ve sayfasız başvuru, bir satırdaki aralık, çıkan toplantıya `#REF!`, hesaplanan hücrenin ve birkaç toplantılık aralığın yerinde kalması, metin içi, Türkçe `;`, `[sofr]`, izleme ifadesi); **araya toplantı girince** her kullanıcının adımları, "Elle değer"i, masanın etiketi (dosyanın MPCk adları yerinde), Motor'un öncel ortalaması ve başlangıç adımı, kayıtlı senaryo, girdi / masa / senaryo formülleri, hesap tablosu, izleme ifadesi, alarm ve izleme kalemi toplantısıyla - yeniden başlatmada da; **çıkan toplantının kenara alınması** (✕: herkesin değerleri, etiket, senaryodaki değerler, sayılarıyla söylenmesi, başvurunun `#REF!`, alarmın susması; tarih dönünce hepsinin ve alarmın geri gelmesi; OIS sayfasında yanlış yazılan yılın kenara alıp düzeltilince geri getirmesi; boş tarihli yapıştırmanın reddi); **tarih ve adımların aynı yazmada** (olağanüstü toplantı adımlarıyla son satıra yapıştırılınca adımların toplantının yerine gitmesi, sonraki toplantının kendi adımlarıyla kayması; satırında başka tarihe çevrilen toplantının kenara alınması, yeni tarihle yazılan adımın ona gitmesi); **sürüm** (eski takvimin üstüne kaydın 409 ve kimin değiştirdiğiyle reddi, HTTP) ve **tek işlem** (ortasında hata veren değişikliğin tarihleri, adımları, senaryoları, kenardakileri ve motoru değiştirmemesi); **kaydırma** (geçen toplantının değerlerinin kenara alınması, elle değer / etiket / Motor'un toplantıyla kayması, 30 gün sonra silinmesi); **FOMC listesi** (yapılan toplantıları atıp yenilerini eklemekle karar / WIRP / adımlar / elle değer / senaryo / formül / alarmın toplantıyla gitmesi, dosyanın sabit değerlerinin satırda kalması, tarihin silinince kenara alınıp yazılınca geri gelmesi, aynı tarihin, tarihe ve adıma formülün, dosya tarihlerine dönüşün reddi); **izleme** (düzeltilen tarihle alarmın, adının ve kapanışlarının yeni tarihe geçmesi; önceki sürümün hücre olarak sakladığı kalemlerin açılışta bir kez toplantıya bağlanması) |
| `test_bundle.py` | Tek dosyalık kurulum (`kurulum/tto_kur.py`): içine ne girdiği, aynı içeriğin aynı dosyayı vermesi, boş klasöre açma, güncelleme (değişen yenilenir, kalkan silinir, `data` / `vendor/local` / kullanıcının kendi dosyaları kalır), ZIP'ten gelmiş klasör, yarım inmiş / bozulmuş / satır sonları değişmiş dosya, klasör dışına çıkan adların reddi, seçenekler; **repodaki dosyanın kodla aynı olduğu** ve hiçbir paketi olmayan bir Python'la açılıp sunucunun ondan çalıştığı; **`run.bat`'ın Anaconda'yı önce açması** (masa, 19.11.2026: Python'suz bir PATH'te `TTO_CONDA`'daki ya da `%USERPROFILE%\Anaconda3`'teki sahte Anaconda'nın `activate.bat`'ı klasörüyle çağrılıp `python -m tto` onunla başlıyor, hiçbiri yoksa "Python bulunamadi"; dosya ASCII, CRLF, içinde kullanıcı klasörü yazmıyor) |
| `test_bloomberg.py` | `blpapi` katmanı (sahte sunucuyla): gruplama, abonelik (kota büyüklükleri dahil), sessiz kalan kotaların giderek seyrek sorulması (değeri olmayan 3 saatte bir, değeri olan en çok 15 dakikada bir, yanıtı aynı kaldıkça seyrekleşerek), hata metinleri, BDH/BDS, limit koruması (sınıra gelince yeni anahtarın da beklemesi), canlı–doğrudan eşdeğerlik (dört kitap); **Bloomberg'in tanımadığı ticker'lara abone olunmaması**, ertesi gün - bir sayfa hâlâ okuyorsa - yeniden sorulması, seyreltme seçeneği ve reddedilince seçeneksiz deneme, uzun olay kuyruğu, **kuyruk taşınca sayım ve düşen değerlerin yeniden istenmesi** (günlük üst sınırıyla); **Excel eklentisi için yazılmış kimliklerin API biçimine çevrilmesi** (`… @ISL1 ISIN` → `/isin/…@ISL1`: istek, geçmiş, abonelik), geri çekilen emrin miktarının boşalması, **aboneliği akan menkulde kota büyüklüğünün yeniden sorulmaması** (akmayanda eskisi gibi), canlı–doğrudan eşdeğerlikte büyüklüğün tick'le gelip DİBS RV'de kotayı açması, **aynı gün yeniden başlatma** (günün bütün cevaplarının - kotalar da - ve veri sayacının devralınması: hiçbir şey yeniden sorulmaz, kota aboneliğiyle güncellenir; ertesi gün bir kez sorulur) |
| `test_bloomberg_bars.py` | **Gün içi barlar** (`IntradayBarRequest`, sahte terminalin hafta içi 09:30–18:00 barlarıyla): isteğin öğeleri (tek menkul, olay türü, bar uzunluğu, İstanbul saatinin UTC'ye çevrilmesi - yerel gece yarısı bir önceki gün 21:00 -, ISIN'in API yazımı), barların İstanbul saatiyle ve eskiden yeniye dönmesi, **bitişin hariç olması** (terminal o barı da gönderse), hafta sonunun boş kalması, **uzun aralığın parça parça gelip birleştirilmesi** (20 iş günü, 2.040 bar, 5 parça), **istek başına 1 hit ve günlük sınırda isteğin hiç gönderilmemesi** (ertesi gün yeniden), tanınmayan menkulün boş liste ve hata metni, Bloomberg'in limit / zaman aşımı yanıtının `None` olması (günlük limitinden sonra hiçbir isteğin gitmemesi), yanıt gelmeyince `None` ve geç gelen yanıtın hiçbir yerde kalmaması, zaman aşımına uğrayan isteğin yeniden gönderilmesi, aynı anda dört çağrı, Bloomberg'in reddedeceği argümanlar (`ValueError`) ve boş aralık (istek yok), imzanın her sağlayıcıda aynı olması, kayıtlı veride `None` |
| `test_bloomberg_process.py` | Oturumun yardımcı süreçte çalışması: değerlerin, tick'lerin, `BDH`'nin ve tarihçe çağrısının süreç sınırını geçmesi; `blpapi` yok / yüklenemiyor / terminal yok / yardımcı yanıt vermiyor; **yardımcı ölünce yeniden başlayıp dashboard'un elindeki bütün cevapları alması** (yalnız cevabı olmayanı sorar; istek sayacı sürer), aynı gün yeniden başlatmada kotaların da, türe ve anahtara göre sayacın da devralınması, sürekli ölen yardımcının bir noktada bırakılması; **sessiz kalan (takılan) yardımcının fark edilmesi** (son sesin saati, verinin "bayat" olması), piyasa saati dışında yeniden başlatılmaması, piyasa saatinde yenisinin başlatılıp her şeyi yeniden istemesi, **sürekli takılanın günlük sınırdan sonra bırakılması**; verinin durumu (canlı / bayat: tick yaşı, piyasa saati, sessiz yardımcı / bağlantı yok / kayıtlı veri) ve "itibarıyla" saati; dashboard durunca ya da öldürülünce yardımcının kapanması; **ölçüm: hesap yapan bir sürecin içindeki okuyucu saniyede 2.000 tick'in dörtte birine yetişemezken yardımcı hepsini okur**; dashboard'un yardımcıyı kullanması ve başlatamazsa aynı süreçte devam etmesi; ve ilk canlı çalıştırmanın sahnelenmesi: `python -m tto --mode live`, dört kitap, saniyede 1.500 tick, 10.000'lik kuyruk — hiç olay düşmez, var olmayan ~790 vadeye abone olunmaz; **gün içi barların yardımcıdan geçmesi** (aynı barlar, tanınmayan menkulün boş listesi, hit sayımı ve günlük sınırın yardımcıda tutulması), yanıt gelmeyince ve yardımcı ölünce `None` (zaman aşımını beklemeden), yeni yardımcının yanıtlaması |
| `test_bloomberg_cache.py` | **Önce önbellek** (24.11.2026, Bloomberg'in "Daily capacity reached" cevabından sonra; sahte terminal, sağlayıcı benzetilmiş saatle tur tur sürülür): **bugün cevabı gelen değerin bugün bir daha sorulmaması** (sabit, günlük, 5G / 1A değişim, son işlem tarihi - eski dakikalık sınıf -; ertesi gün 08:00'de bir kez, sayfanın artık okumadığı dünkü anahtar hiç); **sessiz saatler** (19:00 sonrası, hafta sonu, tatil: hiçbir şey yeniden sorulmaz, abonelik akar, yeni anahtar yine sorulur); **DİBS RV'nin CK / CL'si akan son fiyattan** (cevap + son fiyatın hareketi: her işlemden sonra Bloomberg'in yeni cevabına eşit, sayfanın GC'si - 5 gün önceki kapanış - sabit; kayıtlı dosyada her kâğıt için CH − CK üç ondalıklı temiz bir fiyat); **CG'nin akışta işlem görülünce bugün olması** (ilk resim işlem sayılmaz; hacim artışı, son fiyatı olmayan kâğıdın ilk fiyatı); **aralık en düşük / en yükseğin** günün akan en düşük / en yükseğiyle; **bugünü içeren BDH'nin bugünkü noktasının akıştan**, canlı fiyatı olmayanın saatte bir; **akmayan kota en çok 15 dakikada bir** (yanıtı her seferinde değişse de; değeri olmayan 3 saatte bir, tanınmayan günde bir); **günlük bütçe** (%70'te yalnız ilk cevaplar, %100'de hiçbir yeni istek: bekler, ertesi gün gider); **Bloomberg'in LIMIT cevabı** (hiçbir istek gitmez, son değerler kalır, durum der; gün değiştikten bir saat sonra tek deneme, limit sürüyorsa saatte bir; cevaplanınca normale döner); **türe ve anahtara göre sayım** ve durum penceresinin dağılımı (`/api/market/usage`: türler, ilk 10 sayfa - DİBS RV -, ilk 10 alan); **çalışma kitaplarının bütün anahtarlarıyla ofis benzeri bir gün** (448 tanınmayan BIST vadesi, %6 başarısız abonelik, %10 sessiz alan): 20.000 hit'in altında, aynı gün yeniden sorulan yok |
| `test_blpapi_real.py` | Gerçek `blpapi` kuruluysa (yoksa atlanır; terminal gerekmez): kütüphanenin kendi test olaylarıyla tick okuma, değeri boşaltılmış miktarın "mesajda yok"tan ayırt edilmesi, `SlowConsumerWarning` / `DataLoss` / abonelik durum mesajları, oturum seçenekleri ve abonelik metni (`…?fields=ASK,BID&interval=1`), hesap yapan bir iş parçacığının yanında okumanın kaç kat yavaşladığı, terminal yokken hata (aynı süreçte ve yardımcıyla). `blpapi` yükseltildikten sonra masada bir kez çalıştırmaya değer. |
| `test_quantuniv.py` | **Quant evreni ve Sinyaller listesi** (`tto/quantuniv.py`): planlanan her enstrümanın kayıtta olması - 7 G10 spot, 35 G10 opsiyon (ATM 1A / 3A, 25D RR 1A / 3A, 25D BF 3A), TRY OIS'te 35 adet ≤ 2Y (outright, spread, fly, FRA 3×6 … 18×24, üç PPK dönemi) ve 10 uzun uç satırı sırasıyla, DİBS, VİOP, 13 Offshore satırı -, grubu, önceliği (G10 spot … Offshore; TRY OIS'te ≤ 2Y uzun uçtan önce), birimi, büyüklüğü ("1 mn EUR", "10.000 $ vega", "1.000 $ DV01", DİBS'in nominali, VİOP'un kontratı), yön sözcükleri ve "offshore limiti"; girdilerin (UST, DXY, Brent, CDS, TLREF, 15M / 21M / 4Y / 9Y OIS) işlem satırı olmaması; **dikilmiş seviyelerle** spread (uzun − kısa), fly (gövde − kanatların yarısı) ve işaretleri (uzun vade 10 bp yükselince spread +10, fly −5; steepener uzun vadeyi pay eder), fly'ın her yazılışında yanında OIS sayfasının 2·gövde − kanatlar kotası ("-12,5 bp (OIS sayfasında -25,0)": satır, kartın cümlesi, gerekçenin stop'u, evren tablosu; spread'de ve outright'ta yok), **FRA**'lar (düz eğride 3×6 … 15×18 eğrinin faizi, 18×24 iki çeyreğin bileşiği; her gün FRA / PPK ailesinin `curve_dfs`'iyle 1e-9 içinde aynı, çeyrek eksikken de; uzak vade yükselince yalnız ona biten FRA; bacakları uzak pay / yakın receive, net DV01 1); **PPK dönemi serisinin toplantıda bir sonraki döneme geçmesi** (toplantı günü, iki dönemde de; geçiş günü değişim sayılmaz; bugünkü patikadan seviye, bacağı dönemin toplantı tarihli OIS'i, carry 0); **kayan satırlar**: takvim düzeltilince (araya toplantı, bir tarihin bir gün kayması; eski günler eski listeyle, bir günün satırları karışık sırada) her günün k. dönemi kendi k. toplantısı tarihiyle, değiştiği gün geçiş - +50 / +100 bp'lik sıçrama hareket sayılmaz, her hareket piyasanın 1 bp'i -, bugünün dönemleri ve bacakları yeni takvimden; VİOP sayfasının sütunları kayınca ve yeni kontrat gelince her kontratın geçmişi, canlı değeri ve bacağı ticker'ıyla aynı, DİBS RV'ye üste yeni kâğıt eklenince (satırlar kayar) kâğıdın adı, geçmişi, getirisi ve nominali ISIN'iyle aynı, vadesine 30 günden az kalan kâğıdın satırı olmaması; **büyüklük ve para** (1 mn EUR'nun %1'i USD, USDJPY'de yen USD'ye, 1,4 mn / 700 bin EUR, vol puanı 10.000 $, bp × 1.000 $ × USDTRY, DİBS nominali DİBS RV!AI gibi, USDTRY forward'ı TRY ve puan düşüşü, 100 puan = 10.000 TRY, VİOP %40 ima faiz; opsiyon satırının kartında parası - "≈ +6,0 bin USD (10.000 $ vega)", hedefte / stopta -, G10 spot'un "EURUSD spot al"ı); **listenin sırası** (gruplar, TRY OIS'te ≤ 2Y önce - güçlü bir 2s10s bile sonra -, grubun içinde güvenliler beklenen K/Z'ye göre sonra düşük güvenliler, hedge'li 2Y'nin ana bacağıyla ≤ 2Y'de olması, USDTRY forward'ının Offshore, EURUSD'nin G10 spot / opsiyon, USDZAR ve UST'nin Diğer olması, grup sayıları); **G10 serileri tarihçede**: hiçbir serinin iki kez istenmemesi, varsayılan listeyle 22 yeni seri ve doldurma sırası (en sonda: spotlar, puanlar, sonra vol'ler vade vade; iki yıl bir kez, her tur yeni günler), G10'suz bir listede bile 45'inin tutulması, yalnız evrenin tuttuğu paritenin FX analizlerine girmemesi; **takılan bir aile** (servis: "trend" kaydıyla dört satır - G10 spot, TRY OIS ≤ 2Y ve uzun, Offshore - gruplarında, düşük güvenli satırın listede ve elenenlerde kalıp kayda ve alarma düşmemesi, grup düğmesi ve kutunun aynı listesi, abonelikte üç yeni aile ve grupla süzülen alarmlar; geri testin yeniden kurulmasında evrenin ailelerini grubuyla çalıştırması), ailelerin modüllerinin sırası (Trend, Carry + momentum, ML, Opsiyon → spot), modülü olmayan ailenin atlanması ve bozuk modülün kendi hatası; HTTP API (`/api/quant/universe`, grup süzgeci, gruplu abonelik - saklanan grubun adı) |
| `test_quantsira.py` | **Carry + momentum** (`tto/quantsira.py`), cevabı dikilmiş sentetik piyasalarla: **dikilmiş carry sırasının doğru sepeti vermesi** - G10'da carry'si en yüksek üç para birimi long, en düşük üçü short (JPY satmak USDJPY AL, EUR satmak EURUSD SAT; CAD dışarıda), carry ve momentum sütunları; vol'de primi en büyük üçünde vol sat, en küçük üçünde al; TRY OIS'te carry + roll ÷ oynaklığı en iyi iki vade receive, en kötü iki pay; DİBS'te eğriye göre her zamankinden ucuz üç kâğıt al, pahalı üçü sat -; **nötrlük ve eşit risk** (G10'da bir tarafın bacaklarının haftalık σ'sı eşit, iki tarafın doları eşit; vol'de vega, faizde ve DİBS'te satırların DV01 toplamı 0); bir vadenin haftalık carry + roll'unun elle hesabı (TLREF'e göre carry ÷ annuity, eğride yuvarlanma); **haftalık dengeleme** (pazartesi kapanışı, pazartesi tatilse salı; sonraki dengeleme: bu hafta kurulduysa gelecek pazartesi - tatilse salı -, pazartesi kapanıştan önce bugün, cumartesi pazartesi; çarşamba sepetin pazartesinki, pazartesi geçen haftanınki olması); **ileriye bakış yok** (bir günden sonraki bütün kapanışlar değişince o güne kadar biten haftaların sepeti ve K/Z'si aynı; o güne kadarki tarihçeyle kurulan son sepet tam tarihçenin o dengelemedeki sepeti); **satırlar** planın biçiminde ("AL AUDUSD spot · … · giriş … · hedef … · stop … · beklenen … USD · isabet %… (…) · model: Carry + momentum · G10 spot sepeti", faiz satırında TL), **sepetin seviyeleri** (haftaların yolu sepetin riski cinsinden, son kapanışı haftanın K/Z'si; grup başına - TRY OIS'in üç sepeti birlikte - ayarlı k ve m; sepetin hedefi m × riski, stopu k × riski, ödül / risk m ÷ k ≥ 1; her bacakta aynı katlar kendi σ'sıyla, kartın parasıyla; beklenen K/Z kaydın ortalaması × sepetin riski, bacağın payı riskiyle; zarar ettiren sepetin bacakları "düşük güven"), sıra 1 … 2, sepet dışı 1'in altında; **kapı yok** (carry'si aleyhte, beklentisi tamponu karşılamayan bacak "düşük güven" olmaz, kapı kartta ✗; başka bir ailenin satırı olsa tutulurdu); **listede ≤ 2Y önce** (en güçlü 5Y/10Y steepener'a rağmen), Offshore'a satır düşmemesi; **geri test** (her hafta pazartesiden pazartesiye, isabet ve ortalama; sonucun ailenin kendi süresiyle, sepetler tür olarak geri test tablosuna girmesi, yeniden kurmalarda ailenin çalışmaması); servis ve **API** (tam hesapta aile, sayfanın kümeleri ve canlı K/Z'si, Sinyaller'deki satırlar, geri test tablosunda ailenin ayarlı seviyeleriyle kaydı ve TRY OIS grubunun satırı, satırların kaydı, nav'da Sinyaller'in sekmesi) |
| `test_quantdibssw.py` | **DİBS switch** (`tto/quantdibssw.py`), cevabı dikilmiş sentetik piyasayla (iki süre kümesi: her kümede getirisi en yüksek ve düşen kâğıt en iyi, en düşük ve yükselen en kötü): **dikilmiş carry + momentum sırasının doğru switch'leri vermesi** (her kümede iyisi AL, kötüsü SAT; en geniş fark önce, bir kâğıt bir kez, en çok üç; carry, momentum, z'ler ve bileşik tanımıyla), **süre bandı** (switch ve izleyici yalnız 1,5 kat içindeki çiftlerde, kümeler arası yok; bant genişleyince bütün çiftler), **DV01 dengesi** (AL bacağı masanın 1.000 $ DV01'i, nominaller 5 mn TL'nin katı, SAT bacağı yarım birim içinde aynı DV01; bacaklar Buy / Sell; masanın yuvarlaması OIS_MAIN!H2'den), **haftalık takvim** (pazartesi kapanışı, pazartesi gün içinde geçen haftanınki, tatil pazartesisinde salı), **ileriye bakış yok**, **evren** (bono içeride; TLREF'e endeksli ve vadesi yaklaşan dışarıda, nedeniyle), **seviyeler quantlevels'tan** (≥ 30 işlem, yol = farkın düşüşü + C+R payı, satırın hedef / stopu katlar × haftalık σ, beklenti), **DİBS RV'nin C+R'ı** bugünün satırında, **zarar ettiren kayıt** her satırı "düşük güven" yapar, satırın planın biçiminde olması, servis: tam hesapta aile, sayfa, Faiz menüsünde Eğri Adil Değeri'nin yanında |
| `test_quantcons.py` | **Konsensüs** (`tto/quantcons.py`): **üç aile aynı yönde → tek satır** (aileler en iyi kayıttan, en iyi örneklem dışı ailenin seviyeleri satırda adıyla, büyüklük medyan, aile isabetleri; satırların kendisi değişmez; seviyesi modelin farkı olan satırlarda hedef / stop enstrümanın kendi seviyesinde - FRA faizi -, fark yanında), **iki aile → yok**, **düşük güven satırı sayılmaz**, **ters yön → yok** (bir aile ters ya da iki yönde), **enstrümanlar arası yok** (spot / forward, outright / spread, başka varlık), faizde medyan büyüklükte bacak DV01'i ve TL; servis: Konsensüs grubu listenin ve düğmelerin başında, ailenin süzgecinde, kutuda, kartı en iyi ailenin satırı, kaydı ve alarmı yok |
| `test_quantlevels.py` | **Seviyeler** (`tto/quantlevels.py`): **dikili yollarla bilinen en iyi k ve m** (kazananlar 0,3 … 1,1σ düşüp +2σ'ya gider, kaybedenler ikinci kapanışta −1,3σ'yı geçer: stop kazananların MAE'sinin %90'ı + 0,26σ, hedef kazananların hiç ulaşmadığı bir yer - son kapanışa kadar tutulurlar -, beklenti elle hesapla aynı; düzeltmesiz eski cevap %90 ve +2σ; stopa 0,26σ'dan yakın kapanış stopta, stopun kendi seviyesinde; hedefte kapanış dolmaz, 0,26σ ötesi doldurur); **kapanışlar yalnız**: ince adımlarla (kapanış başına 50) çizilip kapanışlarda bakılan yollarda düzeltmeyle stop daha sık ve gün içi dokunmaya yakın sayıda çalışır, hedef daha seyrek; kapanışları stopa yakın kazananlarda ve ince adımlı karışık trendlerde **stop tabandan (0,5σ) ayrılır**, düzeltmeyle seçilen seviyeler gün içi duran emirlerle daha çok kazandırır, gösterilen kayıt gün içinin altında kalır; ortalamaya dönüşte **adil değer hedefi** (stop en çok hedef kadar, her işlemde ödül / risk ≥ 1, sabit hedefi yener; ortalamayı yalnız kapanışta gören yol hedefe ulaşmış sayılmaz); rastgele yollarla **ödül / risk hep ≥ 1** ve sınırlar (stop 0,5 – 3σ, hedef en çok 4σ); **az işlemli grup ailenin havuzuyla**, aile de azsa seviye yok ve nedeni; **saklama** (aynı işlemlerle ikinci kalibrasyon hiç seçmez, düzeltilen bir yol yalnız onu gören ayları, başka aile kendi); **ileriye bakış yok** (bir aydan sonra biten yollar değişince o aya kadarki seçimler aynı, her ayın seçimi o ay başlamadan biten işlemlerle; geri testte her işlemin yolu tutma sonuna kadar - kendi hedefi / stopu önce gelse de -, girişte bilinen σ'yla, adil değer uzaklığıyla; gelecek yeniden yazılınca biten yollar ve o aya kadarki seviyeler aynı); **kendi yürüyen testini veren aile** (quantbt biçiminde `path_sigma`, `sigma`, toplam `carry`, `horizon` - grup satırın anahtarından, yolun sonu gerçekten erken değil - kodsuz ayarlanır: Opsiyon → spot'un sözleşmesi); **iz süren stop** geri testte ve sinyal kaydında en iyi seviyenin arkasından gelir; satırda **hedef / stop = katlar × tutmanın σ'sı**, ödül / risk, isabet, işlem sayısı, beklenen K/Z (faizde + carry + roll), kartın cümlesi ve *Seviyeler* kapısı; adil değer ve iz süren stop satırı; **zarar ettiren seviyelerin satırı "düşük güven"** ("bu kurulum bu seviyelerle geçmişte zarar ettirdi"), listede kalır, kapısı olmayan ailede de; grubun **beklenen K/Z'ye göre sırası**; kendi seviyesini tutan aileler (VİOP, İma kalibrasyonu, gün içi, korelasyon) ve nedenleri, geri test yokken / ailenin işlemi yokken nedeni, saklanan geri testin JSON'dan okunması |
| `test_e2e.py` | Gerçek tarayıcıda (Playwright/Chromium) 793 kontrol: **bir tarayıcıya bir canlı akış** (8 sekme: hepsi sayfasını açar, akış sayısı artmaz, değişiklik her sekmeye ulaşır, yenileme yalnız açık sekmenin panellerini `since` ile ister), **şifreyle giriş** (oturumsuz API'nin 401'i, yanlış şifre, yöneticide "Kullanıcılar" sayfası, kullanıcıda yok), **sekmeler** (Forward hesaplayıcılarla açılır, sabit valör şeridi, sekme değiştirme ve hatırlanması, her sekmede arama, "Tümü", başka sekmedeki hücreye gidiş), **elle değer** (mod kapalıyken formül yazılamaz; açıkken yazılan değerin işareti, sayaç, silince ve "formüle dön"le geri dönüş), hesaplayıcıya elle spot, düzenleme, Excel kopyala/yapıştır, RET, senaryo, işlem girişi, iki kullanıcı arası canlı paylaşım, grafiklerin çizimi (renk, eksen, tarih ekseni, ipucu, XY grafiği), kısayollar, gizli / dondurulmuş sütunlar, **ondalık basamak** (OIS · PPK'nın OUTRIGHT'ında sağ tık → "Ondalık 2": yüzde yüzde, milyonların "M"si yerinde, metin aynı, seçim yerinde; "Ondalık artır"; Kopyala ekrandakini, tam hassasiyet değeri alır; sayfa yeniden açılınca kalması; başka hesabın dosyanın biçimini görmesi; "Ondalığı varsayılana döndür"), arşiv indirme, forward kotasyon matrisi (USDTRY ve EURTRY; EURTRY'nin USDTRY'nin eğri ve spread'lerini izlemesi, kendi spread'i, puandan spread), altın swap faizi girişi ve VİOP tablosunun değişmesi, Borsa Swap (**OIS ve offshore mid spread sütunları**: iki tabloda başlıklar, spread = BID % / ASK % − mid zero, tek taraflı kotada yalnız o taraf, T+0'ın OIS spot'una TLREF'le taşındığını söyleyen ipucu, tablonun notu), DİBS ASW (geçmiş grafiğinin OIS / Offshore / İkisi seçicisi: Offshore'a geçip OIS'e dönüş, seçimin `ASW!N3`'e yazılması), **kâğıtlar tersinden** (DİBS ASW'nin "ASW → temiz fiyat"ı kâğıt tablosunun altında: bir kâğıdın kendi ASW'si kendi temiz fiyatını verir; DİBS RV'nin "ASW / DM → temiz fiyat"ı: TLREF'linin kendi DM'i kendi fiyatını; SWITCH / PAIR'de çiftin getiri farkı seviye olarak Al'ın fiyatını; Manuel Tahvil'de ISIN vadeyi, kuponu ve fiyatı doldurur, kendi ASW'si hedef olarak fiyatı geri verir), gün sonu matrisi (değerler, geçmiş gün, kopyalama), PPK fiyatlama geçmişi (çizgiler, toplantı ekleme / çıkarma, ölçü değiştirme, ipucu, günlerin durumu), manuel spot penceresi (üst şeritten açma - dosyanın spotu gelmez, kaynak BBG -, bid > ask reddi, Bloomberg'e dönme), **VİOP Target'ın FRA eğrisi** ("Hedef tipi"nin yanında, varsayılan Bootstrap (piyasa); S2 seçilince OIS FRA ve hedef faizin S2'nin değeri olması, başlığın ve ipuçlarının "S2 · Hawkish" demesi, sayfa yeniden yüklenince seçimin durması, Bootstrap'a dönünce eski değerler), **toplu tarih arası faiz** (TARİH ARASI FAİZ'in ve kutusunun - TARİH ARASI FAİZ → SPREAD - hemen altında; Excel'den yapıştırılan iki çiftin iki satırı doldurması ve her satırın Masa bloğunun aynı tarih ve spread'deki faizlerini - değer ve görünen metin - vermesi), **VİOP Target'ın Fiyat hedefi** (satırın kendi uzak limit fiyatı Fiyat tipiyle yazılınca aynı hedef faiz, uzak limitin o fiyat olması, fiyatın dört ondalıkla görünmesi, ipucu; **Faiz %** satırında Hedef değerin iki ondalıkla - `45` → `45,00` -; **iki yönlü**: aynı fiyat FRA+bp satırında Uzak limit sütununa yazılınca aynı hedef faiz, Hedef değer OIS FRA'ya göre bp, uzak limit ✎), **24.11'in tersleri**: TARİH ARASI FAİZ → SPREAD (bloğun MPC ima + spread'i kote yazılınca MPC ima'ya −150 bp, her eğriye `kote − dönem faizi`, bulunan spread bloğa yazılınca kote, 1e-9), toplu tablonun Kote %'si (iki satırın + spread'i sütun olarak yapıştırılınca seçilen eğriye −100 ve −150 bp, Bootstrap'a farkı, başlıklar), tahvil carry'nin ISIN satırı ve kendi B/E'si Fwd temiz fiyat olarak yazılınca İma repo %36, Implied Move'un kendi hareketi, üst sınırı ve pip'i geri yazılınca İma vol %19, **Implied Move iki yönlü** (üst sınır yazılınca vol izler, yazılan ✎ ve ipuçları, hesaplananda Delete'le %19), RET kaydırma önizlemesi (her vadede kaç bp ve yeni bid / ask, sabit tutulan ve elle miktar verilen vade, yalnız bid, önizlemedeyken kaydetmeme, "Uygula") ve tablo / mesaj olarak kopyalama, **RET yapıştırınca ne kadar ve nerede değiştiği** (açılışta her Δ 0 ve 'değişen vade yok'; yapıştırılan vadelerin Δ bid / Δ ask'ı bp, renkleri, renkli satırlar, yapıştırılmayanın 0'ı; üstteki 'Değişen N vade: … · M vade aynı' satırı; kaydedince geçmişin aynı değişikliği yazması; aynı eğri yeniden yapıştırılınca satırın ve bildirimin 'değişen vade yok' demesi), VİOP geçmiş sekmesi (kontrat tablosu, iki grafik, yeni çizgi ekleme), işlem girerken ve listede DV01, tarih aralığı görünümü ve indirilmesi, **Broker Chat** (yapıştırılan chat'in yazılırken okunması, kısaltılmış seviye / işlem / ref, kaydetme, tahta ve model farkı, ikinci kez yapıştırma, tek enstrüman / arama / ürün süzgeci, başka kullanıcının eklediği satırın canlı gelmesi, silme, saatsiz satır, indirme, aralık), blotter'da **EURTRY / swap puanı / minor para / MPC tarihli OIS** girişi ve bacak bazında payer (+) işaretli DV01, blotter'da **Benzerini gir / Ters işlem** (bugünün forward'ında formun yeni işlem olarak - düzenleme değil - aynı parite, yön, tutar, valör, fiyatlama ve karşı tarafla dolması, üstündeki "Benzeri: …" satırı, kaydedince aynı koşullarla yeni işlem ve satırın kalkması; ters işlemde ters yön, aynı tutar ve valör; spread'in ters işleminde STEEPENER, aynı vadeler, seviyesiz - bugünkü mid önerilir -; 45 gün önceki 1Y PAY'in bugünü içeren aralıkta "Benzerini gir"i aynı vade bugünkü spot'tan, "Ters işlem"i o günün spot'undan 1Y'lik vadesine kırık vadeli RECEIVE, aynı nominal, bugünkü mid'le kaydı - eski işlem değişmeden), **aralığın özet tabloları** (aralıkta listelerin altında Excel sayfasının dört tablosu ve kapsam yazısı, OIS vade özetinin 1Y'sinde geçmiş günün 3.500 $'ının bugünkülerin yanında; özeti olmayan geçmiş günün kendi tablosu ve "gün sonu arşivi yok"; bugünde yazısız), blotter'da **Düzenle** (forward'ın formunun işlemle dolup "Vazgeç"le eski haline dönmesi, işlemin değişmemesi; fiyat kutusunun üstündeki satırın kaydetmeden önce "Değişiklik yok", karşı taraf yazılınca "Yalnızca karşı taraf / not", valör değişince turuncu "Valör değişti: bugünkü piyasayla yeniden fiyatlanır" demesi; spread'in seviyesinin sayfadan değiştirilmesi: işlem anının mid'iyle ("Mid (işlem anı)"), aynı bacaklar ve giriş saati, listede ✎ ve ipucunda kim / ne zaman / önceki seviye, **Mid'e göre** fiyat kutusunda ve listede - + mid'den iyi, yeşil -, maliyet tablosunun yeni orana geçmesi; "Karşı taraf ve not" penceresinde karşı taraf değişince forward'ın kuru, tutarları ve DV01'inin aynı kalması), blotter'da **tutarın TRY yazılması** (USDTRY'de 520m TRY: USD'nin forward'dan gelmesi, yazılan tarafın ✎ işareti - kutuda, TL tutarında, listede -, USD yazılınca işaretin geçmesi), **şablon** (formdan kaydetme ve seçili alanlar, bir tıkla doldurma - EURTRY, satış, 300m TRY, 3M, karşı taraf - ve hiçbir şey kaydetmemesi; kullanıcının masa şablonunu görüp başkasının kişiselini görmemesi, masaya yayımlayamaması), **Excel'den yapıştırma** (üç satırdan biri hatalı: başlığın tanınması, hatalı satırın nedeniyle görünmesi, "2 satırı kaydet", iki geçerli satırın birlikte kaydı, hatalı satırın başlığıyla kutuda kalması), **Realized Vol · Carry** (yazılan enstrümanların vol'ü, geçmişi olmayan / okunamayan satır, yıllık birim, seviye ve kayan vol grafiği, fly ve spread'lerin C+R ÷ σ sıralaması ve noktalı grafiği), altın hesaplayıcısının serbest sütunu, **altın hesaplayıcısı iki yönlü** (bir kontrat sütununa yazılan teorik fiyatın kalıp TRY %'nin onun ima ettiği faiz olması - 1e-9 -, USDTRY fwd'ın izlemesi, ✎ işareti ve ipucu, notun kontrat dönüşünü söylemesi; hesaplanan SP'de Delete ile sütunun piyasa faizine dönmesi), Ctrl+K ile tablo bulma, Ayarlar'da toplantı tarihinin düzeltilip OIS sayfasına yansıması, **toplantıyla taşınma** (araya toplantı girince adımın, "Elle değer"in ve alarmın yeni satırda görünmesi, eski takvimin üstüne kaydın 409'la reddi, tarihleri içeren seçimde Delete'in tarihleri nedeniyle reddedip adımları temizlemesi), **Ayarlar'da fiyat kaynağı sırası** (ekleme, kaydetme, varsayılana dönme, her vadenin kullandığı kaynak), Broker Chat'te **taraf** sütunu, sütuna göre **sıralama**, **işaretleyerek silme**, **tahtayı sıfırlama / geri alma**, RET penceresinde **spread (önceki → şimdi)**, carry tablosunda **z-score**, bugünü içeren aralıkta **işlem girişi**, Broker Chat'te **DİBS kotaları** (ISIN'li ad, valör, ihale listesi, yakın kâğıttan tamamlama), **DİBS RV'nin broker sütunları** (en iyi taze bid / ask, kimde · yaş; bayat sınırı 10 dakikayken yarım saatlik kotanın soluk, "bayat · BGC · 30 dk" olarak, getirisiz ve ekran farksız durması), **"+ ISIN ekle"** (77 kâğıtlık katalog, hatalı ISIN'in reddi, listeye ekleme), **manuel temiz fiyatın kâğıdıyla taşınması** (ISIN başka satıra yazılıp eski satırı silinince fiyatın kâğıdın yeni satırında görünmesi, uyarının satırları söylemesi, kâğıt geri dönünce fiyatın da dönmesi), **Bulk Bond ve toplu forward'da satır açma** (toplu forward'a iki valör ve iki forward yapıştırıp ima TRY %'nin RET mid'i vermesi - TRY faizleri iki, outright'lar dört, USD % üç ondalık -; **TOPLU FORWARD → işlem**: satırın EURTRY fwd'sinde sağ tık → İşlem gir'in Günlük İşlemler'i EURTRY, satırın valörü ve o outright'la, yönsüz ve tutarsız açması, Parite / Yön (listeden seçilerek ve yazılarak) / Tutar / Karşı taraf yazılıp "İşleme al": Tutar'ı yazılı üç satırın FX Forward önizlemesi - USDTRY satırın forward'ıyla, EURTRY EURTRY fwd'siyle, valörsüz satır "valör yok", Tutar'ı boş satırın söylenmesi, ürünün sabit olması -, "2 satırı kaydet", notları ve tabloda Tutar'ların silinmesi (valör, parite, yön, karşı taraf, fiyat kalır; hatalı satır kutuda), ikisinin Günlük İşlemler listesinde olması, ikinci basışta yalnız düzeltilecek satırın gelmesi; **ON karşılık %**: satırın RET mid'inin hesaplayıcı ON'u olması, yazılan ON'un kalması (✎), Manuel TRY %'nin onun tersiyle bulunan faiz olup USDTRY fwd'nin değişmesi, Delete'le satırın geri dönmesi; yeni sütunlar (Spread, ON − RET ON, Dönem TRY % / ON %, P/gün'ler, faizlerin ON'ları: başlıkları, ilk satırın dönemi kendi faizi, ikincininki forward-forward, ON · RET mid %'nin ON karşılık'a eşitliği), Valör ve Gün'ün sabit, gizli yardımcı sütunların sayfada olmaması; spread yazılınca (40 bp) Manuel TRY %'nin RET mid + 0,40, USDTRY P/gün yazılınca (150) puanın 150 · Gün olması, genel spread'in (25 bp) hiçbir şey yazılmamış satırları RET mid + 25 bp'yle fiyatlaması ve her Delete'in geri dönmesi; Kotasyon'da faiz → spread'e matrisin faizini yazıp spread'in ve puanın aynı çıkması; forward starting swap'ın puanını ve çapraz forward'ın forward'ını geri yazıp faizin aynı çıkması), **OIS · PPK ve USD · FOMC'un ters hesapları** (MPC OIS → PPK ADIMI'na dönemin piyasa faizini yazınca adımın piyasanınkiyle aynı çıkması, −30 bp spread'in sonraki dönemin faizini önceki dönemin piyasası − %0,30 vermesi, ilk döneme yazılan %36,50'nin adımının Broker Chat'teki "mpc1 36.50/37.00"nınkiyle aynı olması ve tablonun notunun O/N'nin iş günlerinde bileşik olduğunu söylemesi; TÜM FORWARD / FRA'da hedef FRA'nın gereken bitiş bacağını dolum olarak yazınca Gerçekleşen FRA'nın hedef olması; FOMC'de pencerenin piyasa OIS'ini yazınca İma O/N ve Toplantı adımının geri gelmesi), **DİBS Trading** (valörler, ek kaynak, chat sütunları, günün işlemleri), **kâğıt kartı** (DİBS Trading'den ve DİBS RV'den), **Tüm Kâğıtlar** (77 kâğıt, türler, ★) ve **☆ / ★ ile trading listesine ekleme / çıkarma** (DİBS Trading özetinde görünmesi, ★ ile DİBS ASW listesinden de çıkması; DİBS Trading'de "+ ISIN ekle" ile eklenen kâğıdın DİBS ASW tablosunda görünmesi ve uyarının söylemesi), **DİBS Trading özetinin sütun grupları** ve adil getiri / fiyatın hesabını söyleyen ipucu, valörlerde yalnız kâğıt satırları, **DİBS RV · Genel** (menüde tek giriş ve üç sekmesi, ayrı DİBS RV / DİBS ASW girişi olmaması, sekmenin ve girişin yanması, tablonun grupları - FX swap ima eğrisinin adıyla - ve trading listesinin her kâğıdı, uyum satırı - NS, RMSE ve LOO RMSE -, getiri eğrisinin ve iki ASW grafiğinin sunucudaki nokta sayısı kadar işareti; Genel'deki bir ayarın ve switch / pair tablosunun girdi hücresinin tıklayınca RV hesap tablosunda seçili açılması, `#/dibs` ve `#/asw`'nin girişin sekmeleri olarak açılması), **DİBS ASW'de FX swap grafiği** (işaret sayısı sunucudaki grafiğin nokta sayısı ve OIS grafiğininki kadar, etiketler aynı, kesik eğri, üzerine gelince kâğıt, "Tablo"), FX swap ima eğrisi çizgi grafiği, ASW tablosunun boş satırsız ve tür başlıklı olması, **İzleme · Alarmlar** (hazır grup, sağ tıkla hücre ekleme - kâğıdın getirisi kâğıt olarak -, alarmın çalıp açık sayfada uyarması, "Ekle · alarm kur…" ile **VİOP OIS − VİOP spread alarmı**, **kâğıt ASW alarmı** ve **"İfadeye ekle" ile ifade**, hatalı ifadenin söylenmesi, **z-skoru sütunu ve pencere seçimi**, **z alarmı**, **masa alarmı** (yöneticinin herkese kurması, açık sayfada "Gördüm, ben bakıyorum"lu uyarı ve üst şeritteki sayaç, tek cevabın herkese görünmesi, kişisel susturma: yeniden çalınca susturana sessiz, başkasına açık), **alarm sesi** (hiç tıklanmamış yeni sekmede masa alarmı uyarısıyla bir kez "🔇 … sayfaya bir kez tıklayın", ses bağlamı kurulmaz; tıklandıktan sonraki alarmda tek bağlam, çalışır durumda), masa notları), **Eğri Hareketi** (tablolar, seviye, açılış ve referans karşılaştırması, ölçek, bir noktadan **hareket alarmı**), **Forward fiyatları** sekmesi (USDTRY / EURTRY alt alta, günlük puanlar, **TRY faizlerinin iki ondalıkla** - outright ve USD faizleri dört -, Elle'de eğri seçip spread, serbest forward'da eğrilerden gelen spot / faizler ve yazılan minor faizle fiyat, vadelere göre faizler; iki ondalıklı bir TRY faizinin hücre menüsündeki *Tam hassasiyetle kopyala*'yla bütün ondalıklarıyla kopyalanması), **Kota mesajı** (forward tablosunun puanları, satır çıkarma; OIS par'ı ± genişlik), **İşlem gir** (forward tablosundan ve Broker Chat'teki işlem satırından Günlük İşlemler'in dolu açılması: parite, yön, valör, puan; OIS vadesi, seviye, PAY, not, karşı taraf), **fiyattan işlem** (Masa'daki forward kotasının 3M ask puanına sağ tık: menünün başında "İşlem gir", izleme / alarm / kopyalama ardında; Günlük İşlemler'in USDTRY satış, satırın kendi valörü ve tıklanan puanla, tutar ve karşı taraf boş dolması ve puanla fiyatlanması; OIS sayfasındaki 1Y par'ının 1Y outright'ı par'la, yön seçili gelmeden doldurması ve yönsüz kaydedilmemesi; MPC OIS satırının MPC formunu satırın kendi iki günüyle açması; fiyat olmayan hücrede "İşlem gir" olmaması, VİOP kontratının fiyatında soluk ve nedeniyle), Broker Chat'te **switch** (tahtada tek satır, ekrandaki switch modeli, eğriye göre yeri), Broker Chat'te **MPC tarihli OIS** (`mpc1`: tahtada kendi satırı, MPC OIS modeli ve ima PPK adımı; işlem satırından Günlük İşlemler'in MPC formunun toplantı günleriyle dolu açılması), **girilmemiş işlem** (menüde "1 işlem girilmedi" rozeti, tıklayınca liste, "Yok say" ve "Geri al", gün sonu arşivinden önce uyarı, listeden "⇢ Gir" ile girilince rozetin kalkması ve arşivin uyarısız inmesi), **en iyi fiyat** (en iyi bid'in broker'ı ve yaşı; bayat sınırı 10 dakikayken yarım saatlik daha iyi kotanın en iyi sayılmayıp kendi broker satırında soluk ve yaşıyla durması), carry'de **Listem**, **Spread Geçmişi** (offshore − OIS ve VİOP − OIS tabloları, pencere seçimi, grafik), Ayarlar'da **carry patikası ve ufku**, **Hazine İhalesi**'nde kısaltmayla yazılan nominal (`35m`) ve toplamı, tablo başlığının yazılan kâğıtla sayfa yenilenmeden değişmesi, **Ayarlar'da tatiller** (TRY · USD · EUR sekmeleri; TRY listesinin yazıldığı üç kitap - TRY (Motor), DİBS ASW, Borsa Swap -, birleşik TRY listesi, Fed tatilleriyle USD - Thanksgiving var, Good Friday ve cumartesiye düşen 4 Temmuz yok -, TARGET2 ile EUR, SIFMA / FOMC tarihleri; EUR'ya gün ekleyince EURTRY spot valörünün kayması - USDTRY ve Bloomberg valörleri yerinde -, kaydedilmemiş TRY yazısının sekme değişince kalması, gün ekleme, dosyaların listesine dönme), Forward'ın valör şeridinde **Bloomberg valörü** sütunları, Forward'ın **Kotasyon** sekmesi ve Masa'daki USDTRY ve EURTRY özetleri (her spread'in yanında TRY faizi, OIS + spread), Masa'da tarih arası forward'ın tarihlerinin Forward fiyatlama sekmesinden yazılması (sekme değişmeden, 90 gün, silince eski hâline dönmesi), **girdiye formül** (kırık vade valörüne `=`, başka tablodaki başlangıç tarihine düz tık - `=C60` -, `+7`, Enter: başlangıç + 7'nin `ƒ` ve "Formül: =C60+7" ipucuyla görünmesi; başlangıç yazılınca kendiliğinden izlemesi; F2'nin formülü göstermesi ve ortasına Ctrl+tıkla başvuru - `=C60+G60`; tamamlanmış başvurudan sonra düz tıkın yazmayı bitirmesi; Bloomberg işlevinin nedeniyle reddi, hücrenin yeniden açılması, formülün kalması; reddedilen formülden başka hücreye tıklayınca uyarının formülüyle çıkıp seçimin tıklanan hücrede kalması; **başka sekmenin hücresi**: sekme açılınca formülün kendi çubuğunda sürmesi, Faiz · PPK'daki anket ayına tıklama - `=S155+1`; Delete'in formülü de silmesi), Masa'nın VİOP sekmesinde DEALS'in vade sınırının ve hedeflerin tablolarının üstünde durması ve vade sınırı 1 yazınca DEALS'te her listede tek çift kalması, **OIS'in Parametreler'inin her sekmenin üstünde durması** ve En iyi işlemler sekmesinde DV01/bacak yazınca nominallerin iki katına çıkması, **Motor sayfasının yalnız yöneticinin menüsünde** olması, **Yedekleme** (yalnız yöneticinin menüsünde; varsayılan 17:30 ve veri klasörü, ikinci kopya seçilmemişken ipucu; göreli ve OneDrive klasörünün alanın yanında, gerekçesiyle reddi; seçilen saat ve klasörlerin kaydedilip "yönetici seçimi" olarak görünmesi; **Şimdi yedek al**: dosya, boyut, ikinci kopya ve iki klasörün listesi; seçilen klasör yazılamazken yedeğin dashboard'un kendi klasörüne gitmesi - sayfada ve durumda -, klasör geri gelince ulaşması; kullanıcıya 403 ve durumunda klasör olmaması; *Varsayılanlara dön*), tüm sayfalar, **Hata / Öneri · Sosyal · Ajanda** (bildirimin yöneticide canlı "!" olması ve İlgilenildi ile kalkması, kullanıcının listeyi görememesi; iki kullanıcı arasında canlı sohbet, düz metin, okunmamış sayısı, silinen mesajın her ekrandan gitmesi; ajandaya Bugün + saat + deadline, 15 dakika önce uyarı, gecikmiş deadline'ın önde olması, kişisel işin başkasına görünmemesi, başkasının tamamlaması; **tekrarlayan iş**: birkaç dakika sonrasına "Her iş günü" deadline'ı - iş günü değilse o günle "Seçili günler" -, uyarısının başka kullanıcının başka sayfasında "Ertele 10 dk" ve "Bugün tamam"la çıkması, aynı tarayıcının iki penceresinden yalnızca birinde çıkması, Ertele'nin yalnızca erteleyende susması, Bugün tamam'ın yalnızca o günü tamamlayıp her ekranda görünmesi, Tekrarlayan işler'de duraklatma ve silme), **İma Patikası ve TCMB WIRP** (her TCMB toplantısının iki 50 bp sonucuna bölünmesi, ardışık çiftlerin ayrık patikaları, kinkler, kalibrasyon, kayıtlı veri notu; Fed'in FOMC tablosundan on toplantısı 25 bp ızgarada; WIRP'te indirim / sabit / artırımın toplamı, matrisin beklenen patikasının ima patika olması, Masa!Q155'ten politika faizi ve TLREF farkı, tıklanan toplantının kova grafiği, Fed'in hedef aralıkları), **Öncü-Takipçi** (her aday çiftin listelenmesi - kayıtlı ay kısa: her biri nedenini söyler -, gün içi barların olmadığının yazması, DİBS RV listesinin kâğıtlarının vadesiyle adlanması, grup süzgecinin satırları daraltması, hatırlanması ve "Tümü"ye dönmesi), **VİOP** (VİOP sayfasının on iki kontratının canlı ask / bid ima faiziyle listelenmesi; kayıtlı veride Bloomberg geçmişi olmadığından adil değer ve emir seviyesi olmaması, sayfanın ve seviye panelinin bunu söylemesi; kontrat seçiminin seviye panelini o kontrata çevirmesi ve hatırlanması), **sinyal kartının düz anlatımı** (kayıtlı ayda sinyal çıkmadığından sunucunun biçimindeki bir FX ve bir faiz sinyaliyle, satıra tıklamanın yaptığı gibi: kartın başında cümle; "USDTRY 3A forward sat · 1 mn USD", forward kurlarıyla giriş / hedef / stop ve spot, 1 mn USD başına beklenen K/Z - forward primi ve kur hareketi ayrı -, hedefte / stopta para; faizde alınan / ödenen, bp ve TL; listede beklenen K/Z birimiyle - "+525 bin TRY / 1 mn USD", "+5,08 bp" -, FX'in girişi kur ve birimi "USDTRY 3A fwd"; sunucunun verdiği her sinyalin masa diliyle işlemi ve cümlesi), **Launchpad ve gezinme** (sayfadaki tablodan "+ Launchpad" ile yeni launchpad, Ctrl+K sonucundan ekleme, sürükle-bırak sıranın ve genişliğin yeniden yüklemede kalması, launchpad'de yazılan değerin kaynak sayfada görünmesi, tablonun seçilen sütunları, kendi sütun sırası - sayfada, yeniden yüklemede, launchpad'de; Excel sırasına dönüş -, ★ favori, açılış sayfası, **sıkışık görünüm** (kullanıcı menüsünden açılınca sayfadaki sınıf, tablo satırının alçalması ve yazının küçülmesi, hesapla saklanması, aynı tarayıcıda açık ayrı pencerenin anında izlemesi, yeniden yüklemede kalması ve menüde işaretli olması, kapatınca satırların eski yüksekliğine dönmesi), yan panelin sayfalar arasında kalması ve Alt+Y, Alt+← / Alt+→ ile sayfanın sekmesi ve kaydırmasıyla dönmesi, ayrı pencerenin menüsüz ve canlı olması - toplu istekle, alarm denetimi olmadan -, launchpad'in ayrı penceresi, kaybolan ya da yetkisiz tablonun kutusunda söylenmesi), **kişisel hesap tablosu** (launchpad'e "+ Hesap tablosu", `=MASA!I60+25`'in -125 göstermesi ve formül çubuğu, kendi hücreleri üzerine formüller, Excel'den 2 × 2 blok yapıştırma, Bloomberg işlevinin nedeniyle reddi - hiçbir şey saklanmadan, hücre yeniden açılarak -, yan panele sabitlenen aynı tablonun Masa'da yazılan spread'le anında değişmesi, formül yazarken sayfanın hücresine Ctrl+tıkla ve `=` / işlemden sonra düz tıkla başvuru ekleme, tamamlanmış formülde düz tıklamanın yazmayı bitirmesi, yeniden yüklemede launchpad'de ve yan panelde kalması), **sayfaların kutuları** (yedi kutunun bir launchpad'de sayfalarının hafif kısmından çizilmesi - VİOP'un 12 kontratı ve ön vadenin seviyeleri, tahtanın enstrümanları, izleme listesi, TCMB'nin toplantıları -; yeni hesapla quant kutularının - VİOP'un ikisi tek istekle -, chat satırıyla tahtanın - akışın taşıdığı Broker Chat sayacıyla -, eklenen kalemle izleme listesinin yenilenmesi; kutudaki sinyale tıklayınca kartın kutunun üstünde, sayfanın element id'leri olmadan açılması ve "Sinyaller sayfasında aç"; kutunun kendi seçeneğinin - VİOP kontratı - öğeyle saklanması; sayfadaki panelin "+ Launchpad"i ile yan panele sabitleme ve orada canlı kalması, aynı id'nin iki kez olmaması; ⧉ ile ayrı pencere - menüsüz, sürümle yenilenen, yalnız kendi kısmını isteyen), **Sinyaller'in grupları** (listenin üstündeki düğmeler sırasıyla - Tümü, G10 spot, G10 opsiyon, TRY OIS, DİBS, VİOP, Offshore, Diğer -, ayrı elenenler paneli olmaması, bir grubun tek başına istenmesi ve boş listenin söylemesi, Tümü'ye dönüş, sunucunun sırası - gruplar, grubun içinde güvenliler önce -, seçilen grubun adıyla hatırlanması, evrenin fly'ının kartta giriş / hedef / stop'unun yanında OIS sayfası kotası, **FRA / PPK satırının FRA faiziyle** (kartın giriş / hedef / stop'u "%38,720 / %38,652 / %38,730 · 6x9 FRA (patika farkı …; hedef / stop bugünkü PPK patikasıyla)" - faizler üç ondalıkla -, hedefte / stopta faizleriyle, bacakların par faizleri, İşleme al, Model farkı satırı; listede FRA faizleri ("38,720"), Birim "6x9 FRA %", fark ipucunda; Bugün'ün quant bloğunda faizler ve patika farkı), satırın grubu "TRY OIS · ≤ 2Y", Offshore'un "offshore limiti"si, düşük güvenli satırın etiketi ve nedeni, kartın grup satırı, abonelikte gruplar ve üç yeni aile), **Trend** (Sinyaller'in dördüncü sekmesi; evrenin her enstrümanının satırı - kayıtlı ay kısa: her biri nedenini söyler -, tabloların başlık altı cümleleri, grup düğmelerinin tabloyu daraltması ve hatırlanması; Sinyaller listesinde Trend satırının planın biçiminde - "YENİ · SAT USDTRY 1A forward · 1 mn USD · … · isabet %61 (148) · model: Trend" -, kartında cümle, satırın kendi büyüklüğü ve giriş eşiksiz skor), **Carry + momentum** (Sinyaller'in dördüncü sekmesi; her sepetin kartı ve sıralama tablosu başlığının altındaki cümlesiyle, sepet başına geri test; kayıtlı ay kısa: her sepet nedenini söyler; sunucunun biçimindeki bir sepet bacağının listede planın biçimiyle görünmesi - "SAT USDJPY spot · 1,2 mn USD", kurla giriş / hedef / stop, beklenen K/Z, isabet ve hafta, aile sütununda "Carry + momentum · G10 spot sepeti"), **quant tablolarının cümleleri** (PCA / RV'de her tablonun başlığının hemen altında masanın diliyle cümlesi, yöntem notunun altta "Yöntem:" etiketiyle), **Makine öğrenmesi** (Sinyaller'in bir sekmesi: ailenin her satırı tablosunda, üç tablonun cümlesi başlığının altında ve yöntem notu; kayıtlı ayda hiçbir satırın basılmaması, her satırın nedeni - "geçmiş kısa (… kapanış; en az …)" -, listenin bunu söylemesi; listede bir ML satırının ailesi, grubu ve "AL AUDUSD spot · 1 mn AUD · olasılık %65 · isabet %69 (64)" işlemi), **Opsiyon → spot** (FX'in dördüncü sekmesi: her parite tablosunda - USDTRY ve EURTRY Offshore'da -, üç tablonun cümlesi başlığının altında ve yöntem notu; kayıtlı veride vol geçmişi olmadığından hiçbir satırın basılmaması, her paritenin nedeni - EURTRY "opsiyon serisi yok" -, sinyal kaydı tablosunun kaydı olmadığını söylemesi; listede bir Opsiyon → spot satırının ailesi, grubu ve işlemi açan opsiyon sinyaliyle başlayıp planın satırıyla - kurla giriş / hedef / stop, beklenen, isabet - biten işlemi), **quant menüsü** (dört giriş ve sekme sayıları; eski adresin Faiz'i doğru sekmede açması ve menüde Faiz'in yanması; sekmenin kendi adresi ve son sekmenin yeniden yüklemede de hatırlanması; Ctrl+K'nın sayfayı kendi sekmesinde açması), **kendi menünüz** ("Menüyü düzenle…" ile bir sayfanın ve bir quant girişinin menüden çıkması ve hesapla saklanması; Ctrl+K'nın gizli sayfayı yine açması, yeniden yüklemede menünün kalması; başka kullanıcının menüsünün kendisinin olması, yönetici sayfalarının listede olmaması; "Hepsini göster"), **kısmı ve kendi sırası olan tablolar** (başka bir kullanıcının kendi launchpad'inde: MPC OIS'ten "MPC1→2" ve "MPC3→4" seçilip kendi "Elle değer" spot valörüyle bir hafta ileri gidilince aynı iki satırın kalması; IMPLIED RATES'ın MPC1, MPC3, MPC5'ini gösteren kutuya Excel'den yapıştırılan üç adımın o satırlara, V, U, W sırasına yapıştırılan üç değerin o sütunlara gitmesi; formül yazarken V..U bloğunun `U10:V10` girmesi, MPC1 → MPC3 ve U → W bloklarının nedeniyle reddi; işaretli hücrelerin tablo yeniden çizilince işaretli kalması; DİBS işlem akışının ve Broker bid sütununun hücresine tıklamanın "çalışma kitabı sayfasında değil" demesi), **girdi kısayolları ve Kotasyon kopyala** (Forward DV01'in tutarına `5m` yazınca 5.000.000 ve tablonun kotasyonunda yön, valör, outright ve "Tutar 5.000.000 USD"; Masa'daki USDTRY forward özetinin serbest satırının valörüne `1A` yazınca 1M satırının tarihi, ipucunda "Kısayol: 1A → …"; aynı tabloda **Kotasyon kopyala** → panoda Türkçe kotasyon - başlık, başlangıç, spot, başlık satırı ve fiyatı olan her vade, yazılan serbest satır dahil -, ▾ → English (tarih `04 Dec 2026`, sayı `51.2633`), 2M satırına sağ tık → "Bu satırın kotasyonu"), **geçici kopyalar** (Masa'nın KIRIK VADE & KARŞILIK'ında "+ Launchpad" → "Geçici kopya aç": kopyanın tablonun hemen altında "… · kopya 2" olarak açılması, kopyaya yazılan başka bir valörün kopyanın günlerini ve forward'ını değiştirip tablonunkileri değiştirmemesi, kopyanın fiyatına sağ tıkta "İşlem gir" olmaması (tablonunkinde menünün başında), sayfa yenilenince kopyanın değeriyle durması, yan panele sabitlenmesi, × ile kapanıp yan panelden ve hesaptan da kalkması). **adil değer RET** (pencerenin sekmesi; "Yayınlanandan al"; **Tabana göre**: her satırda Bid / Mid / Ask, varsayılan Mid, satırdan Bid'e geçince "Bid = OIS mid − N" ve Şimdiki'nin yarım genişlik yukarı çıkması, çubuktan hepsinin Mid'e dönmesi; **Senaryo**: varsayılan Piyasa, listede senaryoların adları, S2 seçilince sekmenin 'Senaryo: S2 · Hawkish' demesi, satırların karşılaştırma tablosunun S2 sütunu olması, Piyasa'ya dönüş; taban ve spread değişince Şimdiki, "RET güncellemesi var: 1M, 2M" ve RET düğmesindeki etiket; "Kopyala ve yayınla" ile pano, bildirimin kayan vadeleri ve bp'leri, RET geçmişi, Forward'ın RET'i ve Masa ORANLAR; büyük bir forward'dan akış önerisi, kabulü ve tek tıkla kaldırılması; yönetici olmayanın Ekstra ayarları değiştirememesi) ve Günlük İşlemler'de **Pozisyon ve maliyet**; **Trades** (formun değerlemenin varsayılan işlem tarihiyle açılması; DV01 1.012 $'ın 5 mn lotunda bir nominal ve o nominalin "DV01 ≈ …"sini vermesi, sonra elle yazılan nominalin kalıp DV01'in bilgi olarak görünmesi; spread / fly bacakları ve PPK toplantılarının tarihle seçilmesi; masa OIS'inin kaydı; kişisel FX spot'ta parite iki kez değişince elle yazılan işlem tarihinin kalması, boşaltılınca varsayılanın gelmesi; ikinci kullanıcının masa işlemini görüp değiştirememesi, kişisel işlemi sayfada, API'de ve kayıtta görmemesi; başkasının girdiği masa işleminin açık sayfaya kendiliğinden gelmesi; "MTM yenile"nin saati ve her işlemin değeri ya da nedeni, TL / USD toplamlar; MTM'in yanında **Kupon** sütunu ve SOFR swap'ının Kupon hücresinden açılan **Kuponlar** (5Y'nin beş yıllık dönemi, 2 SIFMA günlük ödeme gecikmesi); kapatılan işlemin kapanan listesine gitmesi ve geçmişi; **hedef / stop**: kutuların "Hedef (%)" / "Stop (%)" etiketi, kâr tarafında olmayan hedefin kutunun altında söylenmesi, satırda hedefe ve stopa kalan bp, listenin `levels` alanları, İzleme'de masanın "hedefe geldi" / "stopa geldi" alarmları ve işlem kapanınca kalkmaları; **İşleme al**: listenin "Trades" sütununda düğme ya da "—" ve nedeni, kartta düğme - girilemeyende soluk -, sunucunun her satıra yazması, dolu formun kişisel, RECEIVE 2Y, DV01 ve nominali, giriş, hedef ve stopla açılması, kaydedilince satırda "Quant · Trend" ve seviyeleri; **Quant'tan**: süzülen liste ve aile tablosu; **FX opsiyonda primin vol'ü** (24.11.2026): formda prim yazılınca "Primin vol'ü", strike'taki smile vol'ü ve farkı (ya da "smile yok"), opsiyonun tavanının üstündeki prime "hiçbir vol" ve nedeni; elle vol'le girilen opsiyonda MTM yenile'den sonra satırda "prim vol" ve kullanılan vol'e farkı, ipucu - işlem sonra silinir), **Bugün** (menüde Masa'nın altında; altı blok içerikleriyle ya da "yok"larıyla, RET satırının üst şeritteki noktayla aynı söylemesi, girilmemiş işlemlerin listedeki "Girilmedi"ler olması, RET düğmesinin doğru sekmeyi açması, "Açılış sayfası yap" sonrası adressiz açılışın Bugün'e gelmesi) ve **Ctrl+K komutları** (`işlem gir usdtry 1m 10mn` önce komut olarak çıkar ve Günlük İşlemler'i doldurur - 1M paritenin spot'undan -, `ret yayınla` adil değer sekmesi, `trade ois 1y 5mn` Trades formu, `kâğıt ekle` "+ ISIN ekle"; hiçbiri kaydetmez ya da yayınlamaz; okunamayan komut ne beklediğini söyler, Enter bir şey yapmaz). **Hesap** (açılışta tarihçe / quant hesabı sürerken üst şeritte hangisi ve nerede; sunucunun verdiği bir görünüm - tam hesap, ML modelleri, geri test birlikte - şeritte "Quant 14/26 · ML 240/480 · geri test 12/25 · ~3 dk" ve ipucunda her biri, tıklayınca her hesabın adımı, yapılan / toplam, başlangıcı, geçen ve kalan süresi; sunucu boş deyince kaybolması; quant sayfasının bandı ve Durum satırı "hesaplanıyor: Quant 14/26 · ML 240/480 · ~3 dk – şu an Makine öğrenmesi"), **senaryo son yazılandan sonra** (tarih yazılıp hemen senaryo yüklenir, yazının isteği yolda 2 sn tutulur: yükleme yazının cevabından sonra gider, sayfada ve kayıtta senaryonun tarihi kalır), **OIS · PPK'nın interpolasyon grafiği** (*EN İYİ 15 FRA*'nın hemen ardında, sayfa genişliğinde; iki yolun O/N forward'ı ve 3A FRA şeridi basamak çizgisi - Bootstrap mavi, PPK basamak turuncu, şeritler kesik -, kotalı vadeler adlarıyla - 15M / 21M yok - ve toplantı çentikleri; şerit tablosunda 12x15 / 15x18 farkının FRA listesinin "PPK fark"ıyla aynılığı, 9x12'ye kadar 0,0; 1Y, 10Y ve Offshore seçiminin anında çizilmesi - 1Y'de dört FRA'nın hepsi aynı, offshore'da ACT/360 3A forward -, seçimin tarayıcıda kalması; üstüne gelince o günün iki O/N'i, adıyla iki FRA'sı ve iki farkı), **Fiyatlama** (menüde OIS · PPK'nın hemen altında; TRY OIS 1Y ile açılması ve masanın kovaları ON … 10Y - ON / 1W / 2W "–" -; XCCY 2Y3M RECEIVE'ın üç kuponu vadeden geriye, kısa dönem başta - 04.11.2026 → 04.02.2027 → 04.02.2028 → 05.02.2029, 92 / 365 / 367 gün -, iki eğrinin mid'i ve offshore kovaları - alıcıda −, uzak kovalar 0; her kovanın yanında kotası (24.11.2026) - TRY OIS 1Y'de 1Y'nin OIS kotası (`OIS_MAIN!B14`) "OIS kotası" başlığıyla, ON / 1W / 2W "–"; XCCY'de "XCCY 2Y"nin offshore kotası (`Forward!E126`) "Offshore kotası" başlığıyla; tek kutuya yazılan 12x15 FRA'nın 12 / 15'e ayrılması, Bootstrap mid'inin OIS · PPK'nın FRA listesindeki 1Y3M'le aynılığı, PPK'da ~70 bp altında, ödeyenin riskinin 1Y − / 18M +; fiyat yazılınca NPV - TL ve $, mid'in altında PAY + - ve fiyat − mid; sayfaya dönünce ve enstrüman değişince girdilerin yerinde, başka kullanıcının kendi varsayılanları; 18M USDTRY forward'ın outright'ı ve puanı; **ters hesaplar** (24.11.2026): Fiyat tipi düğmeleri - Faiz / NPV TL / NPV $ / Peşin bp -, PAY 1Y'de 25 bp peşinden eğrideki sabit faiz - mid'in altında, büyük karoda, peşinin geri okunması -, -1.000.000 TL NPV'den faiz - mid'in üstünde, NPV karosunda geri, PPK'nın faizi yanında -, **Toplu fiyatlama**'nın altı satırı - 1Y sayfanın kendi mid'i, 12x15 FRA'nınki, iki tarih, "2Y -500k"nın faizi, okunamayan satırın kendi satırında nedeni), **Swaption** (menüde Fiyatlama'nın hemen altında; **iki yönlü**: payer'ın kendi running primi hücresine yazılınca vol 5,00 bp/gün geri gelir, hücre ✎, vol kutuları karşılığını gösterir; 1Y × 2Y'nin dayanağı Fiyatlama'nın TRY OIS 1Y × 3Y'si, iki eğrinin forward'ı, opsiyon vadesi 03.11.2027 ve 250 iş günü; kayıtlı kapanışlar 1Y'de bittiği için gerçekleşen vol'ün olmaması ve eksik vadelerin - 18M, 2Y, 3Y - yazılması; 5 bp/gün yazınca bp/yıl = 5 · √252 ve % Black, payer / receiver / straddle'ın bütün greek'leri, payer başabaşı = K + running prim; 3M × 9M'in kayıtlı aydan gerçekleşen vol'leri - 20 değişim dolu, 60 / 120 / 250 olan 21 - ve 60'lığın kullanılması; 5Y × 7Y'nin Türkçe reddi, 7Y / 10Y düğmelerinin soluk olması), **Prop** (üst şeritte Masa'da ve OIS · PPK'da; **iki yönlü**: büyüklük 2,5M yazılınca stoptaki kayıp 500.000 TRY, büyüklük ✎, kayıp kutusu karşılığını gösterir, kayıp yeniden yazılınca 2M; USDTRY 44,35 → 44,55, 500k TL: SHORT, 2M USD, gerçek kayıp 400.000 TRY, 1M başına 200.000 TRY, girişin yanında canlı orta kur; stop girişe eşitken sebebi; bugün girilen stoplu bir USDTRY short'la "MTM yenile": limit yokken yalnız "Bugün K/Z · Stoplar", 50mn TRY limitle "Limit · Bugün K/Z · Stoplar · Kalan" - Bugün K/Z Trades'in "Günlük"ü (bilinmeyenler `*` ile), kalan = limit − bugünkü zarar − stoplar, 2Y OIS'in 37,85 ve short'un 50,60 stopu listede -, kalan alandaki payı; Esc ile kapanması, yeniden açılınca Masa sekmesinin ve yazılanın durması, başka kullanıcının limitinin olmaması), **Kâğıt Fiyatlama** (Tahvil'in ilk girişi; testin veritabanına konan üç günlük kâğıt kapanışıyla bir sabit kuponlunun adil getirisi, kotası, iyi seviyeleri, tabandaki σ'sı ve nasıl fiyatlandığı, TLREF'in nedeni; Öngörülen (1 ay varsayılan, M4 yerine kısa geçmişte M2 ve nedeni) ve OIS'e / FX swap'a göre sütunları, ufuk düğmesiyle öngörülenin değişmesi; kâğıt kartında aynı blok, öngörülen ve kendi ufuk düğmesi; yöneticinin 1–3Y genişliği ve kaydı), **Kâğıt Fiyat Yükleme** (Kâğıt Fiyatlama'nın altında; iki kâğıdın liste olarak eklenip açıklaması ve vadesiyle görünmesi, kısa bir ihale metninin okunması ve tanınamayan satıra yakın vadeli kâğıtların sunulması, Hesapla, bir hücrenin düzenlenmesi ve fiyatının sunucudan gelmesi, Kaydet'in indirdiği dosyanın adı ve satırları, CRLF; Eurobond'un kendi varsayılan getiri spread'i ve kayıtlı veride eklenemeyişinin nedeni; Sabit fiyatlar: Excel'den yapıştırılan iki satırın kendi tablosu - açıklama ("döviz DİBS"), ISIN'den vade, birim, 3 ondalık, verdiği dosya satırı -, Hesapla'da "sabit fiyat" olarak durmaları, hesaplanan satırların Sabitle düğmesi ve dosyadaki satırları; Mid / Bid/Ask: DİBS RV'deki kâğıdın Bid/Ask'ta taraflarının DİBS RV'nin bid / ask'ından başlaması, bid'i ask'ine eşit bononun mid'den fiyatlanıp nedenini söylemesi, özetteki sayım, seçimin listeyle saklanması, Tümü; yerinde kalma: kendi kutusunda kayan uzun listede, kutu yarıya kadar kaymışken bir satırın Mid → Bid/Ask'ı ve bid spread'i + Tab - kutu ve sayfa kaymaz (± 2 px), satır yeni değeri gösterir, imleç kullanılan kutuda kalır ve sonraki Tab satırın Mid / Bid/Ask'ına gider; masanın listesi: başka bir hesabın (Mehmet) eklediği kâğıt açık sayfaya yenilemeden gelir - "son değişiklik: Mehmet" -, kullanıcı spread kutusuna yazarken tablo bekler, kutudan çıkınca çizilir ve yazdığı kaydedilir; iki hesapta liste aynı, mod kişinin); **rozetin penceresinde veri klasörü** (bilgisayarın kendi diskinde, WAL) ve tek dashboard kilidini bu dashboard'un tuttuğu. Node.js + Playwright yoksa atlanır. |
| `test_shortcuts.py` | **Girdi kısayolları**: tutar hücresinde `5m` / `5mn` / `5mln`, `250k`, `1,5mn` / `1.5mn` (iki sayı biçiminde), `2b` / `2mr` / `2mlr`; düz tutarların eskisi gibi okunması (gruplu binler, ondalık, `1e6`, parantezli eksi), anlaşılmayanın reddi; faiz, fiyat, puan ve metin hücrelerinde `5m` / `1A`'nın eskisi gibi metin kalması; **tarih kısayollarının ne olduğu** (`1A` / `1M`, `18M`, `1Y`, `1 yıl`, `2H` / `2W`, `ON` / `O/N`, `TN`, `SN`, `ay sonu` / `aysonu` / `EOM`, `IMM` / `İMM`, `+5`) ve olmayanlar (her tarih yazımı, seri numarası, sayı, `+45000`, `=1A`, `T+1` …); **dikilmiş bir takvimle** her kısayol (tatile düşen 1M, iki hafta, EDATE'in 28 Şubat'ı ve sonraki iş günü, iş günü sayımı, ay sonu - tatilde önceki iş günü, zaten ay sonuysa sonraki ayınki -, IMM - tatilse ertesi gün -, ON / TN bugünden, SN başlangıçtan); **hücrelerde**: Forward valörünün USDTRY'nin (T+1, TRY + USD: Veterans Day sayılmaz), EURTRY matrisinin EURTRY'nin (T+2, TRY + EUR), OIS tarih arası faizinin TRY para piyasasının takvimiyle sayması, cevabın yazılanı ipucu için söylemesi, bitiş tarihinin satırının / hesaplayıcının başlangıcından sayılması; Thanksgiving, Good Friday / Easter Monday ve **Ayarlar → Tatiller'e eklenen günün** kısayolları kaydırması; **yapıştırılan blokta** hücre hücre ve aynı blokta yapıştırılan başlangıçtan (sunucunun yapıştırması dahil), satırın paritesinin (EURTRY) takvimi; VİOP Target'ın kontrat listesinde `ay sonu`nun kontratı, `Spot`'un listenin sözü olması; `=` ile başlayanın formül kalması; tarih, tutar, faiz, fiyat ve metin hücrelerine yazılan düz değerlerin girdi okuyucusunun eskiden verdiği değerle aynı saklanması; Günlük İşlemler valörünün aynı kısayolları |
| `test_datecells.py` | **Tarih tutan her hücre tarih görünür**: kuralın küçük kitaplarda ne dediği (tarih + gün tarih, iki tarihin farkı gün sayısı, `*` / `/` sayı, `IF(A1="","",A1+7)` tarih, tarihle sayıyı karıştıran `IF` / `MAX` bilinmez, `INDEX` / `VLOOKUP`'ta sütun, `LET`, Bloomberg'in tarih alanı tarih / fiyatı bilinmez, biçimi sayı olan 46000 sayı, döngü bilinmez, 3 000 hücrelik zincir, birkaç sütunlu dizi bilinmez); **dört kitapta kuralın bulduğu hücrelerin listeyle (`datecells.SHOWN`: 1 213 + 50 hücre) birebir aynı olması** (kitap yeniden içe aktarılınca neyin değiştiğini söyler); gösterirken yalnız sayı biçiminin değişmesi (değerler, formüller, diziler, kayıtlı değerler, başka hücrelerin görünüşü aynı; kalınlık, renk, dolgu, hiza aynı); listedeki her hücrenin tarih (ya da Bloomberg'in metin tarihi) tutup tarih çizilmesi; tatil listelerinin boş satırlarının tarih, VİOP Target'ın listesinin metin kalması; **Forward DV01'in Start'ı** 04.11.2026 görünür, girdi: `3m` USDTRY spotundan, dikilen ABD tatiliyle 05.02.2027, End'e `18m` Start'tan 07.08.2028, N 549, silince formüle dönüş; Thanksgiving'de Start'ın 27.11'e, TRY para piyasasının 26.11'e düşmesi; **EURTRY spotundan yapılan hücreye** ("Elle değer") `6m` - dikilen TARGET2 tatiliyle 06.05.2027; formüllerin söylediği parite ve başlangıç (Start USDTRY, End'in başlangıcı Start, Masa E60'ın C60'ı, `SPOTDATE` TRY, satırına göre seçen spot sütunu paritesiz); büyük / küçük harf (`3m`/`3M`, `18m`, `1y`, `2w`, `on` …) aynı; tutar hücresinde `3m` = 3.000.000, gün sayısında ve faizde metin; PPK tarihinde `3m`'in eskisi gibi reddi, hiçbir yeni tarih hücresinin toplantısıyla taşınan hücre olmaması; yapıştırılan blok ve senaryonun kısayolu değil tarihi saklaması |
| `test_quotes.py` | **Kotasyon kopyala** (`tto/quotes.py`): kotasyon veren 17 tablonun (Masa'nın forward özetleri, TARİH ARASI FORWARD, KIRIK VADE, VİOP TARGET; Forward'ın hesaplayıcıları, forward fiyatları, Forward DV01, kotasyon matrisleri; VİOP Target) **dikilmiş değerlerden Türkçe ve İngilizce** kotasyonu - parite, tarih, valör ve vade, gün, spot, puan, outright, faizler, tutar, yön; her sayının hücrenin biçimiyle, dilin ayırıcılarıyla yazılması, öteki dilin sayısının hiç geçmemesi, sonda boşluk olmaması; satırlı tablolarda fiyatı olan satırlar (boş satır girmez), tek satırın kotasyonu, boş / tablo dışı satırın reddi; masanın forward özetinin, iki pariteli hesaplayıcının ve yön + tutarlı Forward DV01'in kelimesi kelimesine metni; VİOP Target satırı (metin olarak duran kontrat, LONG); sayının biçimden okunuşu (yüzde, muhasebe biçiminde sıfır, General); tanımların gerçek hücrelere işaret etmesi, `tenor` tanımlarının yalnız tarih girdilerinde ve bilinen sözlerle olması; **çalışma kitabında**: masanın USDTRY özetinin kotasyonundaki sayıların tablonun gösterdiğiyle (Türkçe ve İngilizce biçimde) aynı olması, sayfanın kotasyonlu tabloları ve satırlarını / parçalarını söylemesi, kullanıcının kendi girdisinin kotasyona girmesi; HTTP ucu (dil, satır, tablo dışı satır 400, kotasyonsuz tablo 404, oturumsuz 401) |

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
adsız bıraktığı sütunlara başlık satırı ekler, `"action": "ret"` tablonun başlığına RET penceresinin düğmesini koyar,
`"ranked": true` tablonun bir sıralama olduğunu söyler (EN İYİ 15 …: launchpad seçimi satırları numarasıyla tutar).
Bir sayfanın dashboard'da sayfası olmasın isteniyorsa görünüm dosyasını silip `tests/test_views.py` içindeki
`NO_PAGE` listesine eklemek yeterlidir (hücreleri hesaplanmaya ve Sayfa gezgini'nde görünmeye devam eder). Sayfa
tamamen kalksın (hesaplanmasın, Sayfa gezgini'nde de olmasın) isteniyorsa adı `tto/books.py` içindeki
`REMOVED_SHEETS` listesine yazılır; başka bir sayfanın formülü ona başvuruyorsa kaldırılmaz, günlüğe uyarı düşer.

Dashboard'un kendi ekleri (`tto/extras.py`) dosyadaki belirli hücrelere dayanır (Masa'daki iskonto faktörleri,
VİOP'taki `BFXFORWARD` hücreleri, Borsa tablosunun başlıkları). Dosyanın düzeni değişip bir ek artık uymuyorsa
sunucu yine açılır; yalnızca o ek dışarıda bırakılır, nedeni başlangıçta günlüğe ve `/api/status` yanıtındaki
`left_out` alanına yazılır.

**Satır ya da sütun eklenen / silinen dosya: kayıtlı durum eski adreste kalır.** Dashboard'un sakladığı her şey hücre
adresiyle tutulur ve bir kurulum güncellemesi ya da yeniden içe aktarma bunları taşımaz. Yeni dosyada bir satır / sütun
eklenmiş ya da silinmişse (aralıklar kaymışsa) aşağıdakilerin hepsi **eski adreste** kalır ve artık orada duran başka
bir hücreye uygulanır, hiçbir uyarı olmadan:

* kişisel ve ortak girdiler, girdilere yazılmış formüller ve formüllerin içindeki başvurular, "Elle değer"ler;
* kayıtlı senaryolar, kişisel hesap tablolarının hücreleri ve içlerindeki başvurular (`=OIS_MAIN!U12+25`);
* izleme kalemleri ve alarmların hücreleri ve ifadeleri (kâğıda, kontrata, vadeye bağlananlar da: bağlantıyı kodun
  sabitleri çözer);
* launchpad / yan panel / ayrı pencere kutularının satır numaraları ve sütun harfleri; gizlenen sütunlar ve kişisel
  sütun sıraları;
* kodun içindeki sabit adresler (`MEETING_ROWS`, `STEP_COLS`, `OIS_ROWS`, `VIOP_METRICS`, `BOND_METRICS`, `POLICY_CELL`,
  `TRADING_LIST`, sayfa tanımlarındaki aralıklar).

Bugün yalnızca `extras.RETIRED_INPUTS` vardır ve taşımaz, siler: oradaki eski girdinin değeri bırakılır. Girdi olmaktan
çıkan bir hücrede saklı kişisel değer ise o hücredeki yeni formülün üzerine yazılmış bir "Elle değer" olur. Bu yüzden
düzeni değiştiren bir güncelleme **bir taşıma adımı** ister: eski adresten yeni adrese bir eşleme yazılıp yukarıdaki
listenin hepsine (veritabanındaki girdiler, formüller, senaryolar, hesap tabloları, izleme ve alarmlar, düzenler ve sütun
seçimleri; koddaki sabitler ve `tto/views/*.json`) güncellemeden önce uygulanmalıdır. Taşıma adımı olmadan, düzeni
değiştiren dosya kurulmamalıdır; yalnızca değerleri ya da formülleri değişen (satır / sütun kaydırmayan) dosya
güvenlidir.

## Proje yapısı

```
tto/xl/            Excel formül motoru (tokenizer, parser, derleyici, fonksiyonlar, sayı biçimleri, içe aktarıcı, başvuru dizini)
tto/marketdata/    Bloomberg (blpapi) ve kayıtlı veri sağlayıcıları; bbg_process.py: Bloomberg oturumunu ayrı bir
                   yardımcı süreçte çalıştırır
tto/extras.py      dashboard'un kendi eklediği hesaplar (Excel formülü olarak: EK_FWD, EK_XAU, EK_VIOP, EK_KAYNAK,
                   EK_BULK, EK_FX, EK_IHALE, EK_TATIL - USD / EUR tatilleri ve FX valörleri -, Borsa O/N, Borsa'nın
                   TRY tatil kopyası ve T+1 valörü, Bulk Bond'un yeni satırları)
tto/service.py     uygulama servisi (sayfalar, girdiler, senaryolar, RET, işlem defteri)
tto/inputs.py      yazılanın okunuşu (sayı, yüzde, tarih, liste; tutar kısaltmaları 5m / 250k / 2mr)
tto/shortcuts.py   tarih kısayolları (1A, 3M, 2H, ON / TN / SN, ay sonu, IMM, +5): ne oldukları ve paritenin takvimiyle
                   karşılıkları - hücrenin başlangıcı ve takvimi servisten (sayfa tanımının "tenor"u)
tto/quotes.py      Kotasyon kopyala: tablonun "client_quote"unda adı geçen hücrelerden müşteri kotasyonu metni (Türkçe /
                   İngilizce, tek kotasyon, satır başına tablo, yan yana kotasyonlar); arayüzde kotasyon.js
tto/history.py     günlük tarihçe: kapanışlar, PPK fiyatlama geçmişi (çözücüyü geçmiş günle besleyen ikinci motor),
                   gün sonu matrisi, toplantı takvimi (düzeltme, kaydırma, adımların toplantıyla taşınması)
tto/blotter.py     forward fiyatlama (USDTRY, EURTRY, elle girilen pariteler; swap puanı), OIS strateji bacakları ve MPC
                   tarihli OIS, pozisyon maliyeti, DV01 (forward / OIS / tahvil; payer +) ve risk özeti
tto/pricing.py     Fiyatlama: TRY OIS / FRA / XCCY / FX forward'ın her vadede mid'i iki eğride, takvimi (vadeden geriye, kısa
                   dönem başta), DV01 kovaları (kota +1 bp, eğri aynı yöntemle yeniden: Motor'un bootstrap'ı, PPK kalibrasyonu,
                   offshore bootstrap'ı; her kovanın yanında kotası) ve NPV'si; NPV / peşin'den faiz (value'nun tam tersi),
                   Toplu fiyatlama (satırlar aynı eğrilerden) - saf Python; arayüzde pages/pricing.js
tto/tradehint.py   fiyattan işlem: sayfa tanımlarının "trade" ipucu (denetimi, tarayıcıya giden fiyat hücreleri) ve sağ
                   tıklanan fiyatın Günlük İşlemler formuna dolacak işlemi (satırın kendi hücrelerinden; /api/trade/prefill)
tto/tradevalue.py  Trades'in değerlemesi: OIS / SOFR (outright, MPC, spread, fly, FRA), DİBS, FX spot ve opsiyonun MTM'i,
                   carry'si, accrued'u, fiyatı ve greek'leri; masanın ortak hesabından tek okumalık piyasa (Bloomberg'e
                   sormaz), varsayılan alanlar, alan denetimi, DV01'den nominal, opsiyon priminin vol'ü (premium_vol)
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
tto/rowkeys.py     kâğıt listelerinin satır değerleri kâğıdın (ISIN'in): liste değişince herkesin değerleri, masanınkiler,
                   "Elle değer" ve senaryolar kâğıtla taşınır ya da silinir (tek işlem), açılışta bulunan değişiklik;
                   anahtar hücrelere formül yazılmaması; VİOP altın kontratı değişince kendi VİOP fiyatlarının silinmesi
tto/aswfx.py       DİBS ASW'nin FX swap ima eğrisi: EK_FX'in faizleri kendi kuralıyla okunur (TRYI tek dönem basit ACT/360,
                   TRYSAQ yıllık ACT/360 par; 18M hesaplanır - point_18m: offshore eğrinin XCCY 1Y–2Y arasındaki iskonto
                   faktörü, 18M XCCY par'ı 6M + 12M) ve sayfaya vadesinde aynı iskonto faktörünü veren kendi kuralındaki par
                   faiz olarak girer (sayfanın formüllerinin kopyası: motorla son basamağına kadar aynı)
tto/rvfair.py      adil getiri / fiyat (DİBS Trading, kart, DİBS RV · Genel): DİBS RV'nin OIS ASW eğrisinde ve DİBS ASW'nin
                   FX swap ima eğrisindeki ASW eğrisinde kâğıdın getirisi ve temiz fiyatı (sayfaların kendi bugünkü değer,
                   annuity ve uydurulan eğri sütunlarından); FX tarafının ASW'si, ucuz / pahalısı ve sinyali
tto/dibsgenel.py   DİBS RV · Genel: menü girişi ve sekmeleri, trading listesinin tablosu (DİBS RV, DİBS ASW, rvfair), canlı NS
                   sıfır kupon uyumu (quantcurve'ün DİBS adil değeri hesabı: sabit kuponlulara, bonolar eğride ölçülür),
                   getiri eğrisi grafiği
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
tto/bugun.py       Bugün (sabah ekranı): RET, açık işlemler (son MTM), quant'ın yeni satırları, DİBS'te dönen sinyaller (ve
                   masanın kapanıştaki kaydı), girilmemiş işlemler, Ajanda ve toplantılar - servisin elindekinden; arayüzde
                   pages/bugun.js; Ctrl+K komutları commands.js (okur) ve commandrun.js (yapar)
tto/tradebook.py   Trades: masanın ve kişinin kendi işlemleri (görünürlük ve yetki, formun okunuşu, DV01'den nominal,
                   değişiklik kaydı, günlük kapanış kaydı ve zamanı, carry + fiyat etkisiyle K/Z dönemleri, bacaklar);
                   arayüzde pages/trades.js
tto/tradevalue.py  Trades'in değerlemesi (check, market, value, defaults, notional_for_dv01) - bu dalda taslak
tto/tradequant.py  Trades · quant satırları: hangi satır girilebilir (book), "İşleme al"ın dolu formu, Quant'tan tablosu
tto/quantmath.py   quant istatistikleri, saf Python: EKK, Jacobi PCA, ADF (MacKinnon), Engle-Granger, OU, Kalman,
                   varyans oranı, Hurst, EWMA / GARCH, L2 lojistik regresyon, Newey-West
tto/quantfam.py    quant sinyal aileleri (25), ortak sinyal biçimi, bileşik puan ve uyum
tto/quantcurve.py  Eğri Adil Değeri: OIS'e Nelson-Siegel-Svensson, DİBS'e Nelson-Siegel (Excel'in OIS, BIST'in tahvil kuralıyla), zengin /
                   ucuz, carry + roll, receive / pay için en iyi kâğıt (iki aile)
tto/quantopt.py    Opsiyon: USDTRY / EURUSD vol yüzeyi, smile'ın forward'a göre olasılıkları ve gerçekleşen sıklık (bir aile)
tto/quantpath.py   ima PPK / FOMC patikası ayrık kararların karışımı olarak (İma Patikası) ve TCMB / Fed WIRP'ü:
                   ızgara, tutarlı patikalar (doğrusal kısıtlar), kinkler, kalibrasyon, evrişim matrisi, USD görüntüleri
tto/quantlead.py   öncü-takipçi: çapraz korelasyon ve asimetrisi, Granger F, dağıtılmış gecikme β'sı, kararlılık, yetişme
                   sinyali; hizalı her seride (gün ya da dakika barı), gün içi bar kaynağı için adaptör
tto/quantviop.py   VİOP: kontratlar (ticker, vade), ima TRY faiz, sabit vadeli seriler, adil değer ve sinyal, bugün / bu hafta
                   emir seviyeleri (yansıma ilkesi, gün içi profil, kalibrasyon), takvim etkileri, 5 dakikalık barlar
tto/quantuniv.py   quant evreni: G10 spot / opsiyon, TRY OIS (spread, fly, FRA, PPK dönemleri), DİBS, VİOP, Offshore -
                   seri, σ, carry, büyüklük, para, yön, bacaklar; Sinyaller'in grupları ve sırası; yeni ailelerin kaydı
tto/quantml.py     Makine öğrenmesi ailesi: evrenin 42 satırında 5 günlük yön; saf Python gradyan artırmalı ağaçlar
                   (histogramla), aylık walk-forward, OIS düz vadelerinin ortak modeli, model önbelleği, tahmini
                   oynatan özellikler; arayüzde pages/quantml.js
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
