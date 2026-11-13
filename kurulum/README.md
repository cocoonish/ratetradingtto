# kurulum — dashboard'un tamamı tek dosyada

`tto_kur.py` projenin çalışması için gereken her şeyi (program, içe aktarılmış çalışma kitapları, web paketleri)
**tek bir düz metin dosyasında** taşır. Repo ZIP olarak indirilemiyorsa ya da e-posta arşiv eklerini kabul
etmiyorsa bu dosya yeter; internetten bir şey indirmez, bir şey kurmaz, yalnızca kendi içindekini bir klasöre açar.
Gereken tek şey Python 3.8 ya da üstüdür.

1. Bu klasörde `tto_kur.py` → sağ üstte **Download raw file** (⬇). Dosya yaklaşık 4,7 MB'tır; GitHub içeriğini
   göstermeyebilir ama indirme düğmesi çalışır.
2. İndirdiğiniz klasörde bir komut penceresinde:

```bash
python tto_kur.py
```

   Yanına `ratetradingtto` klasörünü açar ve dashboard'u başlatmayı sorar. (Başka bir klasöre: `python tto_kur.py D:\tto`.)
3. Sonraki açılışlarda `ratetradingtto` klasöründeki `run.bat`'a çift tıklayın; tarayıcıdan `http://localhost:1057`.

**Güncelleme:** yeni `tto_kur.py`'yi indirip aynı yerde yeniden çalıştırın. Değişen dosyalar yenilenir, artık olmayanlar
silinir; `data` klasörüne (kullanıcılar, senaryolar, RET geçmişi, işlem defteri, tarihçe) ve `vendor/local`'a dokunulmaz.

**E-postayla taşımak için** dosyanın adını `tto_kur.txt` yapın — içerik düz metindir, uzantı önemli değildir:
`python tto_kur.txt` aynı şekilde çalışır.

Diğer seçenekler: `python tto_kur.py --list` (içindekiler), `--no-run` (başlatmayı sorma), `--run` (sormadan başlat),
`python tto_kur.py --run -- --port 1060` (`--` sonrası dashboard'a verilir).

Dosya elle düzenlenmez; `python tools/make_bundle.py` üretir ve bir test, repodaki dosyanın kodla aynı olduğunu denetler.
İçinde testler ve kaynak Excel dosyaları yoktur (çalışmak için gerekmezler).
