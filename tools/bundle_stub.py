# -*- coding: utf-8 -*-
r"""TTO Masa - tek dosyalık kurulum.

Bu dosya dashboard'un çalışması için gereken her şeyi kendi içinde taşır: program dosyaları, içe aktarılmış
çalışma kitapları ve web paketleri, kodun altındaki "#" ile başlayan satırlarda base64 ile yazılmış bir zip
arşividir.  Betik internetten hiçbir şey indirmez, hiçbir şey kurmaz; yalnızca kendi içindekini bir klasöre
açar.  Python 3.8 ya da üstü yeterlidir.

    python tto_kur.py                 bu dosyanın yanına "ratetradingtto" klasörünü açar (ya da günceller)
    python tto_kur.py D:\tto           başka bir klasöre
    python tto_kur.py --no-run        açtıktan sonra dashboard'u başlatmayı sorma
    python tto_kur.py --run           sormadan başlat
    python tto_kur.py --list          içindeki dosyaları listele, hiçbir şey yazma

Güncelleme: yeni tto_kur.py'yi aynı yere indirip yeniden çalıştırın.  Değişen dosyalar yenilenir, artık
olmayanlar silinir; "data" klasörüne (kullanıcılar, senaryolar, RET geçmişi, işlem defteri, tarihçe) ve
"vendor/local" klasörüne dokunulmaz.  Dosyanın uzantısı önemli değildir: "python tto_kur.txt" de çalışır.

Bu dosya elle yazılmadı: tools/make_bundle.py üretir.
"""
from __future__ import print_function

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile

VERSION = "@VERSION@"                      # içeriğin özeti: aynı içerik aynı sürümdür
SHA256 = "@SHA256@"                        # gömülü arşivin özeti (eksik ya da bozuk inmiş dosyayı yakalar)
COUNT = int("@COUNT@") if "@COUNT@".isdigit() else 0
NAME = "ratetradingtto"
MANIFEST = ".tto_kur.json"                 # hedef klasörde: bu betiğin oraya yazdığı dosyaların listesi
KEEP = ("data", "vendor/local")            # bunlara ne yazılır ne de bunlardan bir şey silinir
MIN_PYTHON = (3, 8)
BEGIN = "# ---- " + "ARSIV (base64 zip) ----"   # arşiv bu satırla başlar, satırlarının başında "#" vardır
END = "# ---- " + "SON ----"                    # ... ve bu satırla biter (yoksa dosya yarım inmiştir)


def say(text=""):
    try:
        try:
            print(text)
        except UnicodeEncodeError:         # Türkçe harfi gösteremeyen bir konsol kurulumu durdurmasın
            print(text.encode("ascii", "replace").decode("ascii"))
        sys.stdout.flush()
    except (IOError, OSError):             # çıktıyı okuyan kalmadı (ör. "| more" kapatıldı)
        pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def kept(name):
    return any(name == k or name.startswith(k + "/") for k in KEEP)


def safe(name):
    """Arşivdeki bir ad hedef klasörün dışına çıkamaz."""
    if not name or name.startswith("/") or "\\" in name or ":" in name:
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def archive(path=None):
    """Gömülü arşiv: bu dosyanın kodun altındaki satırları (bozuksa ne olduğunu söyleyen bir ValueError)."""
    path = path or os.path.abspath(__file__)
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = [line.rstrip("\r\n") for line in fh]
    if BEGIN not in lines:
        raise ValueError("dosyada gömülü arşiv yok")
    start = lines.index(BEGIN)
    if END not in lines[start:]:
        raise ValueError("dosyanın sonu yok: yarım inmiş")
    stop = lines.index(END, start)
    try:
        raw = base64.b64decode("".join(line[1:].strip() for line in lines[start + 1:stop]))
    except Exception:  # noqa: BLE001
        raise ValueError("gömülü arşiv okunamadı")
    if digest(raw) != SHA256:
        raise ValueError("gömülü arşivin özeti tutmuyor")
    return zipfile.ZipFile(io.BytesIO(raw))


def read_manifest(target):
    try:
        with open(os.path.join(target, MANIFEST), "r") as fh:
            data = json.load(fh)
        return data if isinstance(data.get("files"), dict) else None
    except (IOError, OSError, ValueError, AttributeError):
        return None


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def unpack(zf, target):
    """Arşivi hedef klasöre açar; ne yaptığını anlatan bir sözlük döner."""
    names = sorted(n for n in zf.namelist() if not n.endswith("/"))
    bad = [n for n in names if not safe(n) or kept(n)]
    if bad:
        raise ValueError("arşivde beklenmeyen bir ad var: %s" % bad[0])
    old = read_manifest(target)
    files = {}
    wrote, same, failed = 0, 0, []
    for name in names:
        data = zf.read(name)
        files[name] = digest(data)
        dest = os.path.join(target, *name.split("/"))
        try:
            if os.path.isfile(dest) and file_digest(dest) == files[name]:
                same += 1
                continue
            folder = os.path.dirname(dest)
            if not os.path.isdir(folder):
                os.makedirs(folder)
            tmp = dest + ".tto_yeni"
            with open(tmp, "wb") as fh:
                fh.write(data)
            if os.name != "nt" and (zf.getinfo(name).external_attr >> 16) & 0o111:
                os.chmod(tmp, 0o755)
            os.replace(tmp, dest)
            wrote += 1
        except (IOError, OSError) as exc:
            failed.append("%s (%s)" % (name, exc))
            try:
                os.remove(dest + ".tto_yeni")              # yarım kalan kopya ortada kalmasın
            except (IOError, OSError):
                pass
    removed = 0
    if old is not None and not failed:
        # dosyalar bu betiğin önceki bir sürümüyle gelmiş ve artık yok: silinir (başka hiçbir şey silinmez)
        for name in sorted(old["files"]):
            if name in files or not safe(name) or kept(name):
                continue
            dest = os.path.join(target, *name.split("/"))
            try:
                os.remove(dest)
                removed += 1
            except (IOError, OSError):
                continue
            folder = os.path.dirname(dest)
            while folder and os.path.abspath(folder) != os.path.abspath(target):
                try:
                    os.rmdir(folder)                       # yalnızca boş kaldıysa
                except (IOError, OSError):
                    break
                folder = os.path.dirname(folder)
    if not failed:
        with open(os.path.join(target, MANIFEST), "w") as fh:
            json.dump({"version": VERSION, "files": files}, fh, indent=0, sort_keys=True)
    return {"wrote": wrote, "same": same, "removed": removed, "failed": failed, "fresh": old is None,
            "before": (old or {}).get("version"), "total": len(names)}


def usage():
    say(__doc__.strip())


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass
    extra = []
    if "--" in argv:                                   # sonrası dashboard'a verilir:  -- --port 1060
        cut = argv.index("--")
        argv, extra = argv[:cut], argv[cut + 1:]
    if "-h" in argv or "--help" in argv or "--yardim" in argv:
        usage()
        return 0
    run = None
    if "--no-run" in argv:
        run = False
    if "--run" in argv:
        run = True
    listing = "--list" in argv
    unknown = [a for a in argv if a.startswith("-") and a not in ("--no-run", "--run", "--list")]
    places = [a for a in argv if not a.startswith("-")]
    if unknown or len(places) > 1:
        say("Anlaşılmayan seçenek: %s\n" % " ".join(unknown or places[1:]))
        usage()
        return 2
    say("TTO Masa · tek dosyalık kurulum · sürüm %s · %d dosya" % (VERSION, COUNT))
    if sys.version_info[:2] < MIN_PYTHON:
        say("HATA: Python %d.%d çok eski; en az Python %d.%d gerekir." % (sys.version_info[:2] + MIN_PYTHON))
        return 2
    try:
        zf = archive()
    except ValueError as exc:
        say("HATA: %s.  Dosya eksik ya da bozuk inmiş olabilir - yeniden indirin." % exc)
        return 2
    if listing:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            say("%9d  %s" % (info.file_size, info.filename))
        return 0
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.abspath(places[0]) if places else os.path.join(here, NAME)
    if os.path.exists(target) and not os.path.isdir(target):
        say("HATA: %s bir klasör değil." % target)
        return 2
    say("Hedef klasör: %s" % target)
    try:
        if not os.path.isdir(target):
            os.makedirs(target)
        res = unpack(zf, target)
    except (IOError, OSError, ValueError) as exc:
        say("HATA: %s" % exc)
        return 2
    if res["failed"]:
        say("HATA: %d dosya yazılamadı (dashboard açıksa kapatıp yeniden deneyin):" % len(res["failed"]))
        for line in res["failed"][:8]:
            say("    " + line)
        return 2
    parts = ["%d dosya yazıldı" % res["wrote"]]
    if res["same"]:
        parts.append("%d dosya zaten aynıydı" % res["same"])
    if res["removed"]:
        parts.append("%d eski dosya silindi" % res["removed"])
    say("  " + ", ".join(parts) + ".")
    if res["before"] and res["before"] != VERSION:
        say("  Önceki sürüm: %s." % res["before"])
    if os.path.isdir(os.path.join(target, "data")):
        say("  data klasörüne (kullanıcılar, senaryolar, işlem defteri, tarihçe) dokunulmadı.")
    if res["fresh"] and res["same"]:
        say("  Not: bu klasör daha önce başka bir yolla (ZIP) açılmış; eski sürümden kalmış fazla dosya varsa silinmedi.")
    if (res["wrote"] or res["removed"]) and (res["before"] or res["same"]):
        say("  Dashboard açıksa yeni sürüm için kapatıp yeniden başlatın.")
    say("")
    say("Başlatmak için:  %s klasöründe run.bat'a çift tıklayın" % target)
    say("       ya da:    cd \"%s\"   ve   python -m tto" % target)
    say("Tarayıcıdan:     http://localhost:1057")
    if run is None:
        try:
            interactive = sys.stdin is not None and sys.stdin.isatty() and sys.stdout.isatty()
        except Exception:  # noqa: BLE001
            interactive = False
        if not interactive:
            return 0
        say("")
        try:
            answer = input("Dashboard şimdi başlatılsın mı? [E/h] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0
        run = answer in ("", "e", "evet", "y", "yes")
    if not run:
        return 0
    say("")
    try:
        return subprocess.call([sys.executable, "-m", "tto"] + extra, cwd=target)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())

# Buradan sonrası koda dahil değildir: gömülü arşivin satırları.
# ---- ARSIV (base64 zip) ----
@PAYLOAD@
# ---- SON ----
