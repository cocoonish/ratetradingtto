# vendor — kurulum gerektirmeyen web paketleri

Dashboard'un web sunucusu iki Python paketine ihtiyaç duyar: **Starlette** ve **uvicorn** (ve bu ikisinin
kullandığı birkaç küçük paket). Hiçbir şey kurulamayan bir bilgisayarda `python -m tto` bunları bu klasördeki
wheel dosyalarından doğrudan içe aktarır — wheel bir zip arşividir, Python saf-Python paketleri zip'in içinden
okuyabilir. Hiçbir dosya açılmaz, hiçbir yere bir şey kopyalanmaz, yönetici yetkisi gerekmez.

* Paketler bilgisayarda **kuruluysa onlar kullanılır**; bu klasöre yalnızca Starlette ya da uvicorn bulunamazsa
  bakılır. Kurulu olanlar yerine buradakileri zorlamak için `TTO_BUNDLED=1` ortam değişkeni.
* Hangi setin kullanıldığı sunucu açılırken yazılır: `web paketleri: gömülü kopya (vendor/py310)`.

| Klasör | Python | Starlette | uvicorn | anyio | diğerleri |
|---|---|---|---|---|---|
| `py310` | 3.10 ve üstü | 1.7.0 | 0.54.0 | 4.15.1 | h11 0.16.0, click 8.5.0, idna 3.20, typing_extensions 4.16.0, exceptiongroup 1.3.1, colorama 0.4.6 |
| `py39` | 3.9 | 0.49.3 | 0.39.0 | 4.12.1 | h11 0.16.0, click 8.1.8, idna 3.20, typing_extensions 4.16.0, exceptiongroup 1.3.1, colorama 0.4.6 |
| `py38` | 3.8 | 0.44.0 | 0.33.0 | 4.5.2 | h11 0.16.0, click 8.1.8, idna 3.15, sniffio 1.3.1, typing_extensions 4.13.2, exceptiongroup 1.3.1, colorama 0.4.6 |

`py310` Python 3.10 ve üstü içindir; bu bilgisayardaki testler Python 3.9.5 ile koştuğundan `py39` setini sınar,
`py310` setini sınamaz. `py39` ve `py38`, o Python sürümlerini destekleyen son sürümlerdir
(Python 3.8 ve 3.9 artık güncelleme almıyor; mümkünse 3.10 ya da üstünü kullanın).

**Kaynak ve doğrulama.** Dosyalar PyPI'dan indirilmiş, değiştirilmemiş wheel'lerdir; `SHA256SUMS` her birinin
özetini tutar (PyPI'daki özetlerle karşılaştırılabilir). Yeniden indirmek / sürüm yükseltmek için
(`tools/make_vendor.py` içindeki sürüm listesi):

```bash
python tools/make_vendor.py
```

**Lisanslar.** Her wheel kendi lisans metnini içinde taşır (`*.dist-info/`): Starlette, uvicorn, click, idna,
colorama — BSD-3-Clause; anyio, h11, exceptiongroup — MIT; sniffio — MIT / Apache-2.0; typing_extensions — PSF-2.0.

## vendor/local — kendi paketleriniz (ör. blpapi)

Bu klasör repoda yoktur; oluşturursanız içindeki klasörler ve wheel dosyaları da içe aktarılabilir olur
(kurulu paketlerden **sonra** aranır). Kurulum yapılamayan bir bilgisayarda Bloomberg paketi için kullanılabilir:
Bloomberg'in sayfasından Python sürümünüze uyan `blpapi-…-win_amd64.whl` dosyasını indirin, uzantısını `.zip`
yapıp içindekileri `vendor/local/` altına açın (`vendor/local/blpapi/…` oluşmalı). `blpapi` derlenmiş dosyalar
içerdiği için zip'in içinden okunamaz, açılmış olması gerekir.
