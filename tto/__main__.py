"""Command line: ``python -m tto`` starts the dashboard.

    python -m tto                       # http://<this machine>:1057, Bloomberg if reachable else replay
    python -m tto --port 1060           # any port except 5000 / 5001
    python -m tto --mode replay         # never touch Bloomberg (works anywhere, uses the workbook snapshot)
    python -m tto --mode live           # fail instead of falling back when Bloomberg is not reachable
    python -m tto import-workbook workbooks/TTO_v8_5.xlsm --id tto
    python -m tto import-workbook workbooks/BBG_Borsa_Swap.xlsx --id borsa --password ...   # a file with a password to open
    python -m tto check-bloomberg       # connection / entitlement check for the fields the workbook uses
    python -m tto yonetici "Ad Soyad"   # an administrator with a password typed here (the first one, or a forgotten one)
    python -m tto check-fx USDTRY       # which vol / forward point tickers of a pair the terminal knows (~70 items)

Nothing has to be installed: when Starlette / uvicorn are missing they are taken from the wheels in ``vendor/``
(see ``tto/bundled.py``).
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .config import DEFAULT_PORT, FORBIDDEN_PORTS, ROOT, Settings


def _add_server_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default=os.environ.get("TTO_HOST", "0.0.0.0"), help="arayüz adresi (varsayılan 0.0.0.0)")
    p.add_argument("--port", type=int, default=int(os.environ.get("TTO_PORT", DEFAULT_PORT)),
                   help="port (varsayılan %d; %s kullanılamaz)" % (DEFAULT_PORT, ", ".join(str(x) for x in FORBIDDEN_PORTS)))
    p.add_argument("--mode", choices=("auto", "live", "replay"), default=os.environ.get("TTO_MODE", "auto"),
                   help="auto: Bloomberg varsa canlı, yoksa kayıtlı veri · live: yalnızca Bloomberg · replay: yalnızca kayıtlı veri")
    p.add_argument("--data-dir", default=None, help="veritabanı klasörü (varsayılan ./data)")
    p.add_argument("--bbg-host", default=os.environ.get("TTO_BBG_HOST", "localhost"))
    p.add_argument("--bbg-port", type=int, default=int(os.environ.get("TTO_BBG_PORT", 8194)))
    p.add_argument("--tick", type=float, default=2.0, help="canlı veride ekran yenileme aralığı (sn)")
    p.add_argument("--locale", choices=("tr", "en"), default="tr", help="varsayılan sayı biçimi")
    p.add_argument("--no-stream", action="store_true", help="fiyat alanlarını abonelik yerine sorguyla güncelle")
    p.add_argument("--price-poll", type=float, default=120.0,
                   help="abonelikle gelmeyen fiyat alanlarının sorgu aralığı (sn); küçültmek günlük veri limitini tüketir")
    p.add_argument("--bfx", choices=("off", "approx"), default="off",
                   help="BFXFORWARD: off = #N/A (API karşılığı yok), approx = FWD_CURVE'den yaklaşık hesap")
    p.add_argument("--max-hits", type=int, default=400000, help="günlük referans/geçmiş veri isteği üst sınırı (0 = sınırsız)")
    p.add_argument("--bbg-inprocess", action="store_true",
                   help="Bloomberg oturumunu ayrı bir yardımcı süreçte değil, dashboard'un kendi sürecinde çalıştır")
    p.add_argument("--bbg-interval", type=float, default=None,
                   help="bir aboneliğin iki güncellemesi arasındaki en kısa süre (sn; 0 = her tick). "
                        "Varsayılan: yardımcı süreçte 0, aynı süreçte 1")
    p.add_argument("--bbg-queue", type=int, default=100000,
                   help="Bloomberg oturumunun bekletebileceği olay sayısı (blpapi varsayılanı 10000)")
    p.add_argument("--no-history", action="store_true",
                   help="günlük tarihçeyi (gün sonu matrisi, PPK fiyatlama geçmişi) arka planda güncelleme")
    p.add_argument("--history-refresh", type=float, default=900.0,
                   help="canlı veride tarihçenin güncellenme aralığı (sn; 0 = yalnızca açılışta)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tto", description="TTO masa dashboard")
    _add_server_args(parser)
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="dashboard sunucusunu başlat (varsayılan komut)")
    _add_server_args(run)
    imp = sub.add_parser("import-workbook", help="bir Excel dosyasını model olarak içe aktar")
    imp.add_argument("path")
    imp.add_argument("--id", required=True, choices=("tto", "sofr", "borsa", "asw"), help="hangi çalışma kitabı")
    imp.add_argument("--password", default=os.environ.get("TTO_WORKBOOK_PASSWORD"),
                     help="dosyanın açma şifresi (şifreli kaydedildiyse; 'pip install msoffcrypto-tool' ister)")
    chk = sub.add_parser("check-bloomberg", help="Bloomberg bağlantısını ve alanları sına")
    chk.add_argument("--bbg-host", default=os.environ.get("TTO_BBG_HOST", "localhost"))
    chk.add_argument("--bbg-port", type=int, default=int(os.environ.get("TTO_BBG_PORT", 8194)))
    adm = sub.add_parser("yonetici", help="bir kullanıcıyı şifresiyle yönetici yap (ilk yönetici ya da unutulan şifre)")
    adm.add_argument("name", help="kullanıcı adı")
    adm.add_argument("--data-dir", default=None, help="dashboard'un veri klasörü (varsayılan ./data)")
    cfx = sub.add_parser("check-fx", help="bir paritenin vol / forward puanı ticker'larını Bloomberg'de sına (~70 kalem)")
    cfx.add_argument("pair", nargs="?", default="USDTRY")
    cfx.add_argument("--source", default="BGN", help="vol ticker'larının fiyat kaynağı (varsayılan BGN; boş: kaynaksız)")
    cfx.add_argument("--bbg-host", default=os.environ.get("TTO_BBG_HOST", "localhost"))
    cfx.add_argument("--bbg-port", type=int, default=int(os.environ.get("TTO_BBG_PORT", 8194)))
    return parser


def settings_from(args) -> Settings:
    return Settings(host=args.host, port=args.port, data_dir=args.data_dir, mode=args.mode, bbg_host=args.bbg_host,
                    bbg_port=args.bbg_port, tick_seconds=args.tick, locale=args.locale, bbg_stream=not args.no_stream,
                    bbg_bfx=args.bfx, bbg_max_hits=args.max_hits, bbg_price_poll=args.price_poll,
                    history=not args.no_history, history_refresh=args.history_refresh,
                    bbg_isolate=not args.bbg_inprocess, bbg_interval=args.bbg_interval, bbg_queue=args.bbg_queue)


def cmd_run(args) -> int:
    try:
        settings = settings_from(args)
    except ValueError as exc:
        print("HATA: %s" % exc, file=sys.stderr)
        return 2
    from . import bundled
    try:
        packages = bundled.enable()                # the web packages: installed, or the copies in vendor/
    except bundled.BundleError as exc:
        print("HATA: %s" % exc, file=sys.stderr)
        return 2
    import uvicorn

    from .server import create_app
    app = create_app(settings=settings)
    shown = "localhost" if settings.host in ("0.0.0.0", "::") else settings.host
    how = ", web paketleri: gömülü kopya (vendor/%s)" % packages["bundled"] if packages["bundled"] else ""
    print("TTO Masa  ->  http://%s:%d   (mod: %s, veri: %s%s)" % (shown, settings.port, settings.mode, settings.data_dir, how))
    # no proxy in front of the dashboard: the address a request came from is the connection's own (an
    # X-Forwarded-For header could otherwise make a request from the network look like one from this computer)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", proxy_headers=False)
    return 0


def cmd_import(args) -> int:
    from .xl.importer import WorkbookLocked, import_workbook
    try:
        model = import_workbook(args.path, password=args.password)
    except WorkbookLocked as exc:
        print("HATA: %s" % exc, file=sys.stderr)
        return 2
    out = os.path.join(ROOT, "models", "%s.json.gz" % args.id)
    model.save(out)
    print("%s -> %s  (%d sayfa, %d formül)" % (args.path, out, len(model.sheets), model.formula_count()))
    return 0


def cmd_check(args) -> int:
    from . import bundled
    bundled.add_local()                            # a blpapi dropped into vendor/local
    try:
        from .marketdata.bloomberg import check_connection
    except ImportError as exc:
        print("blpapi yüklü değil: %s" % exc, file=sys.stderr)
        return 1
    return check_connection(args.bbg_host, args.bbg_port)


def cmd_admin(args) -> int:
    """Make a user an administrator with a password typed here (never on the command line, never echoed): the
    first administrator of a dashboard, or one whose password was forgotten.  The dashboard may keep running."""
    import getpass

    from . import auth
    from .store import Store, now_iso, user_key
    try:
        display = auth.clean_name(args.name)
    except ValueError as exc:
        print("HATA: %s" % exc, file=sys.stderr)
        return 2
    if not display or len(display) > 40:
        print("HATA: kullanıcı adı 1-40 karakter olmalı", file=sys.stderr)
        return 2
    password = getpass.getpass("%s için yeni şifre: " % display)
    problem = auth.password_problem(password)
    if problem:
        print("HATA: %s" % problem, file=sys.stderr)
        return 2
    if getpass.getpass("Şifre (tekrar): ") != password:
        print("HATA: iki şifre aynı değil", file=sys.stderr)
        return 2
    path = Settings(data_dir=args.data_dir).db_path
    store = Store(path)
    try:
        key = user_key(display)
        pw_hash = auth.hash_password(password)
        if store.account(key) is None:
            store.create_account(display, pw_hash, role="admin", status="active", by=key)
        else:
            store.update_account(key, pw_hash=pw_hash, role="admin", status="active", failed=0, locked_until=None,
                                 decided_by=key, decided_at=now_iso())
            store.drop_sessions(key)                     # signed in somewhere with the old password: out
    finally:
        store.close()
    print("%s artık yönetici; bu isim ve şifreyle girebilir (veri: %s)" % (display, path))
    return 0


def cmd_check_fx(args) -> int:
    from . import bundled
    bundled.add_local()
    from .fx import check_fx
    return check_fx(args.pair, args.source.strip().upper(), args.bbg_host, args.bbg_port)


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:                                       # a console that cannot show a Turkish letter must not stop the start
            stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001
            pass
    if sys.version_info < (3, 8):
        print("HATA: Python %d.%d cok eski; en az Python 3.8 gerekir." % sys.version_info[:2], file=sys.stderr)
        return 2
    args = build_parser().parse_args(argv)
    if args.command == "import-workbook":
        return cmd_import(args)
    if args.command == "check-bloomberg":
        return cmd_check(args)
    if args.command == "yonetici":
        return cmd_admin(args)
    if args.command == "check-fx":
        return cmd_check_fx(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
