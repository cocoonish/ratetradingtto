"""Ctrl+K commands (``tto/static/js/commands.js``): the parser read under Node - each command, Turkish and ASCII spellings,
any case, what it expected when it cannot read the text, the templates while a command's first word is typed, and the
searches it leaves to the table finder.  The module imports ``format.js`` alone: both are copied as ``.mjs`` files and
run as they are.  (What each command does on screen - the dialog it opens, the form it fills, nothing saved - is the
browser test's, tests/e2e/e2e.js.)  Skipped without Node.js."""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "tto", "static", "js")

HARNESS = r"""
import { parseCommand, fold, tenorOf } from './commands.mjs';
import { setLang } from './format.mjs';
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const { cases, env, lang, folds, tenors } = JSON.parse(raw);
  setLang(lang);
  process.stdout.write(JSON.stringify({ parsed: cases.map((t) => parseCommand(t, env)), folded: (folds || []).map(fold),
    tenors: (tenors || []).map(tenorOf) }));
});
"""

ENV = {"scenarios": ["PPK -250", "Şahin"], "launchpads": ["Sabah", "Öğle"],
       "pages": [{"id": "ois", "title": "OIS", "group": "TRY Faiz"}, {"id": "blotter", "title": "Günlük İşlemler", "group": "Masa"},
                 {"id": "bugun", "title": "Bugün", "group": "Masa"}, {"id": "trades", "title": "Trades", "group": "Masa"}]}


@pytest.fixture(scope="module")
def node_run(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to read the command parser")
    d = tmp_path_factory.mktemp("commands")
    for name in ("commands", "format"):
        with open(os.path.join(JS, name + ".js"), encoding="utf-8") as fh:
            src = fh.read().replace("'./format.js'", "'./format.mjs'")
        (d / (name + ".mjs")).write_text(src, encoding="utf-8")
    (d / "run.mjs").write_text(HARNESS, encoding="utf-8")

    def run(cases=(), env=None, lang="tr", folds=(), tenors=()):
        payload = json.dumps({"cases": list(cases), "env": ENV if env is None else env, "lang": lang, "folds": list(folds),
                              "tenors": list(tenors)})
        res = subprocess.run([node, str(d / "run.mjs")], input=payload, capture_output=True, text=True, encoding="utf-8",
                             timeout=60)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout)

    return run


def parse(node_run, *cases, **kw):
    return node_run(cases, **kw)["parsed"]


def one(node_run, text, **kw):
    got = parse(node_run, text, **kw)[0]
    assert got is not None and len(got) >= 1, (text, got)
    return got[0]


def test_ret_opens_the_dialog_on_the_tab_asked_and_never_publishes(node_run):
    assert one(node_run, "ret") == {"cmd": "ret", "tab": None, "label": "RET penceresini aç", "note": "RET faizleri"}
    for text in ("ret yayınla", "RET YAYINLA", "ret yayinla", "Ret Adil"):
        got = one(node_run, text)
        assert (got["cmd"], got["tab"]) == ("ret", "fair"), text
        assert "Kopyala ve yayınla" in got["note"]                          # (the user publishes: the command opens)
    assert one(node_run, "ret elle")["tab"] == "manual" and one(node_run, "ret gir")["tab"] == "manual"
    bad = one(node_run, "ret xyz")
    assert "cmd" not in bad and bad["error"] == '"ret", "ret yayınla" ya da "ret elle" bekleniyor'


def test_islem_gir_fills_the_forward_form_with_pair_tenor_and_amount(node_run):
    got = one(node_run, "işlem gir usdtry 1m 10mn")
    assert got["cmd"] == "blotter" and got["spec"] == {"kind": "fwd", "pair": "USDTRY", "basis": "RET_MID", "date": "1M", "amount": "10mn"}
    assert got["label"] == "Günlük İşlemler: USDTRY · valör 1M · 10mn USD" and "USDTRY spot'undan" in got["note"]
    assert one(node_run, "işlem gir eurtry 3a 5m")["spec"] == {"kind": "fwd", "pair": "EURTRY", "basis": "RET_MID", "date": "3A",
                                                               "amount": "5m"}
    # Turkish and ASCII, any case; a side word anywhere; a currency alone is against TRY; the month end in two words
    assert one(node_run, "İŞLEM GİR USD 1Y 2,5m sat")["spec"] == {"kind": "fwd", "pair": "USDTRY", "basis": "RET_MID", "date": "1Y",
                                                                  "amount": "2,5m", "dir": "S"}
    assert one(node_run, "islem gir al gbp 2h 500k")["spec"] == {"kind": "fwd", "pair": "GBPTRY", "basis": "RET_MID", "date": "2H",
                                                                 "amount": "500k", "dir": "B"}
    assert one(node_run, "işlem gir usdtry ay sonu 5m")["spec"]["date"] == "ay sonu"
    assert one(node_run, "işlem gir usdtry 15.12.2026 1m")["spec"]["date"] == "15.12.2026"
    assert one(node_run, "işlem gir usdtry 3ay 1m")["spec"]["date"] == "3A" and one(node_run, "işlem gir usdtry 1yıl 1m")["spec"]["date"] == "1Y"
    # the tenor comes first: a lone "10mn" is the amount (no tenor reads so), "5m" after the pair is five months
    assert one(node_run, "işlem gir usdtry 10mn")["spec"] == {"kind": "fwd", "pair": "USDTRY", "basis": "RET_MID", "amount": "10mn"}
    assert one(node_run, "işlem gir usdtry 5m")["spec"]["date"] == "5M"
    # in the English number format the amount is read so
    assert one(node_run, "işlem gir usdtry 1m 2.5m", lang="en")["spec"]["amount"] == "2.5m"
    # bare: the page
    assert one(node_run, "işlem")["cmd"] == "page" and one(node_run, "işlem gir")["id"] == "blotter"


def test_islem_gir_says_what_it_expected(node_run):
    assert one(node_run, "işlem gir usdtry 1x 10mn")["error"].startswith('"1x" vade olarak okunamadı: 1m, 3a, 1y')
    assert one(node_run, "işlem gir 1m usdtry")["error"].startswith('"1m" parite değil: işlem gir <parite> <vade> <tutar>')
    assert one(node_run, "işlem gir usdtry 1m abc")["error"].startswith('"abc" tutar olarak okunamadı: 10mn, 5m, 500k')
    assert '"fazla"' in one(node_run, "işlem gir usdtry 1m 10mn fazla")["error"]
    assert all("cmd" not in one(node_run, t) for t in ("işlem gir usdtry 1x 10mn", "işlem gir 1m usdtry"))


def test_islem_gir_an_ois_fra_meeting_swap_and_bond_in_the_book(node_run):
    """The desk, 28.11.2026 (A4): "işlem gir" fills Günlük İşlemler's OIS and bond forms too - the strategy from what is
    typed (a tenor, two or three, a FRA "9x12" / "1y1y", a meeting by its month), the side in the strategy's words, a
    size (DV01 under a million, a nominal from it), a level "@" - and every suggestion names the book (the position)."""
    def spec(text):
        got = one(node_run, text)
        assert got.get("cmd") == "blotter", (text, got)
        return got["spec"]

    got = one(node_run, "işlem gir ois 2y rec 10k")
    assert got == {"cmd": "blotter", "spec": {"kind": "ois", "strategy": "outright", "side": "RECEIVE", "tenors": ["2Y"], "size": "10k",
                                              "sizeMode": "dv01"},
                   "label": "Günlük İşlemler: TRY OIS · 2Y · RECEIVE · DV01 10k $/bp", "note": "pozisyona girer · form dolar, kaydetmek sizin"}
    assert spec("işlem gir 1y2y steepener") == {"kind": "ois", "strategy": "spread", "side": "STEEPENER", "tenors": ["1Y", "2Y"]}
    assert spec("işlem gir 1y/2y flattener -125bp") == {"kind": "ois", "strategy": "spread", "side": "FLATTENER", "tenors": ["1Y", "2Y"],
                                                         "level": "-125"}
    assert spec("işlem gir 1y/2y/3y rec gövde") == {"kind": "ois", "strategy": "fly", "side": "REC GÖVDE", "tenors": ["1Y", "2Y", "3Y"]}
    assert spec("işlem gir 9x12 pay") == {"kind": "ois", "strategy": "fra", "side": "PAY", "months": [9, 12]}
    assert spec("işlem gir 1y1y rec") == {"kind": "ois", "strategy": "fra", "side": "RECEIVE", "months": [12, 24]}
    assert spec("işlem gir fra 18m6m pay dv01 3k")["months"] == [18, 24]
    assert spec("işlem gir dec mpc pay") == {"kind": "ois", "strategy": "mpc", "side": "PAY", "mpc_month": 12}
    assert spec("İŞLEM GİR MPC ARALIK REC") == {"kind": "ois", "strategy": "mpc", "side": "RECEIVE", "mpc_month": 12}
    assert spec("işlem gir mpc spread ocak pay") == {"kind": "ois", "strategy": "mpcspread", "side": "PAY K+1 / REC K", "mpc_month": 1}
    assert spec("işlem gir ois 2y pay @35,50 500m") == {"kind": "ois", "strategy": "outright", "side": "PAY", "tenors": ["2Y"], "level": "35,50",
                                                         "size": "500m", "sizeMode": "nominal"}
    assert spec("işlem gir ois 3a pay 5000")["tenors"] == ["3M"] and spec("işlem gir ois 12m pay")["tenors"] == ["1Y"]
    assert spec("işlem gir ois 2y nom 50k pay")["sizeMode"] == "nominal"
    assert spec("işlem gir ois 1y 2y") == {"kind": "ois", "strategy": "spread", "tenors": ["1Y", "2Y"]}             # (no side: the user's)
    assert "yönü seçin" in one(node_run, "işlem gir ois 1y 2y")["note"]
    # a bond: an ISIN or the desk's name of it (the server finds the ISIN)
    got = one(node_run, "işlem gir dibs mar28 50m al")
    assert got["spec"] == {"kind": "bond", "instrument": "mar28", "amount": "50m", "dir": "B"}
    assert got["label"] == "Günlük İşlemler: DİBS mar28 · alış · 50m nominal" and "ISIN'i sunucu bulur" in got["note"]
    assert spec("işlem gir TRT150328T24 10m sat @98,75") == {"kind": "bond", "instrument": "TRT150328T24", "amount": "10m", "dir": "S",
                                                              "price": "98,75"}
    assert spec("işlem gir 15.03.28 5m al")["instrument"] == "15.03.28" and spec("işlem gir tahvil eyl29 1m sat")["instrument"] == "eyl29"
    # what it cannot read: said
    for text, said in (("işlem gir 2y rec 4m", "4M OIS formunun vadelerinden değil"), ("işlem gir 1y2y/3y pay", "okunamadı"),
                       ("işlem gir 1y/2y rec", "steepener ya da flattener"), ("işlem gir mpc pay", "toplantının ayı bekleniyor"),
                       ("işlem gir 2x5 pay", "3'ün katı"), ("işlem gir ois 2y gövde", "gövdenin yönü"),
                       ("işlem gir dibs 50m al", "kâğıt bekleniyor"), ("işlem gir dibs mar28 foo", "tutar (50m), al / sat ya da @fiyat")):
        got = one(node_run, text)
        assert "cmd" not in got and said in got["error"], (text, got)
    # the forwards stay as they were - a date written with "/" too
    assert spec("işlem gir usdtry 15/12/2026 1m") == {"kind": "fwd", "pair": "USDTRY", "basis": "RET_MID", "date": "15/12/2026", "amount": "1m"}


def test_fiyatla_opens_fiyatlama_filled_through_its_address(node_run):
    """"fiyatla …": the page's address with /api/pricing's fields - asset, pair, start, end, side, size_kind, size, price,
    price_kind - as typed (the page reads them, nothing is kept until then); a swap without a start starts at spot, a
    price is the one said or none."""
    got = one(node_run, "fiyatla ois 2y3m rec 10k")
    assert got == {"cmd": "page", "id": "fiyatlama?asset=ois&start=&end=2Y3M&side=RECEIVE&size_kind=dv01&size=10k&price=",
                   "label": "Fiyatlama: TRY OIS · 2Y3M · RECEIVE · DV01 10k", "note": "Fiyatlama dolu açılır · hiçbir şey kaydedilmez"}
    assert one(node_run, "fiyatla fra 12x15")["id"] == "fiyatlama?asset=fra&start=12&end=15&price="
    assert one(node_run, "fiyatla 9x12 pay")["id"] == "fiyatlama?asset=fra&start=9&end=12&side=PAY&price="
    assert one(node_run, "fiyatla usdtry 3m al 10m")["id"] == "fiyatlama?asset=fx&pair=USDTRY&end=3M&side=AL&size_kind=amount&size=10m&price="
    assert one(node_run, "fiyatla eur 1y sat 5m @58,25")["id"] == (
        "fiyatlama?asset=fx&pair=EURTRY&end=1Y&side=SAT&size_kind=amount&size=5m&price=58%2C25&price_kind=outright")
    assert one(node_run, "fiyatla ois 1y 2y pay 500m 38%")["id"] == (
        "fiyatlama?asset=ois&start=1Y&end=2Y&side=PAY&size_kind=nominal&size=500m&price=38%25&price_kind=rate")
    assert one(node_run, "fiyatla xccy 5y pay dv01 20k")["id"] == "fiyatlama?asset=xccy&start=&end=5Y&side=PAY&size_kind=dv01&size=20k&price="
    assert one(node_run, "fiyatla") == {"cmd": "page", "id": "fiyatlama", "label": "Fiyatlama'yı aç",
                                       "note": "fiyatla <ois | fra | xccy | parite> … formu doldurur"}
    assert one(node_run, "fiyatla ois 1y al")["error"].startswith("yön rec ya da pay bekleniyor")
    assert one(node_run, "fiyatla usdtry 1m pay")["error"] == "forward'ın yönü al ya da sat"
    assert '"xyz" okunamadı' in one(node_run, "fiyatla ois xyz")["error"]
    assert one(node_run, "fiy") == {"complete": "fiyatla ", "label": "fiyatla <ois | fra | xccy | parite> …",
                                   "note": "Fiyatlama dolu açılır, örn. fiyatla ois 2y3m rec 10k"}


def test_trade_fills_the_trades_form_by_product(node_run):
    assert one(node_run, "trade ois 1y 5mn") == {"cmd": "trades", "spec": {"product": "ois", "tenor": "1Y", "notional": "5mn"},
                                                 "label": "Trades formu: TRY OIS · 1Y · 5mn",
                                                 "note": "izleme, pozisyona girmez · form dolar, kaydetmek sizin"}
    assert one(node_run, "TRADE OİS 2y 10m rec")["spec"] == {"product": "ois", "tenor": "2Y", "notional": "10m", "side": "receive"}
    assert one(node_run, "trade sofr 5y dv01 25k pay")["spec"] == {"product": "sofr", "tenor": "5Y", "dv01": "25k", "side": "pay"}
    assert one(node_run, "trade dibs trt150328t24 10m al")["spec"] == {"product": "dibs", "isin": "TRT150328T24", "notional": "10m", "side": "B"}
    assert one(node_run, "trade spot usdtry 5m sat")["spec"] == {"product": "fxspot", "pair": "USDTRY", "notional": "5m", "side": "S"}
    assert one(node_run, "trade opsiyon usdtry 1a 10m call al")["spec"] == {"product": "fxopt", "pair": "USDTRY", "tenor": "1A",
                                                                           "notional": "10m", "call_put": "call", "side": "B"}
    assert one(node_run, "trade") == {"cmd": "trades", "spec": {}, "label": "Trades: yeni işlem formu", "note": "trade <ürün> … ile doldurulur"}
    assert one(node_run, "trade xyz")["error"].startswith('"xyz" ürün değil: ois, sofr, dibs, spot ya da opsiyon')
    assert one(node_run, "trade ois foo")["error"] == '"foo" okunamadı: trade ois için vade (1y), tutar (5mn), rec / pay bekleniyor'
    assert "ISIN" in one(node_run, "trade dibs TRT15 10m")["error"]


def test_kagit_ekle_takes_one_or_many_isins(node_run):
    assert one(node_run, "kâğıt ekle TRT150328T24")["isins"] == ["TRT150328T24"]
    got = one(node_run, "KAGIT EKLE trt150328t24, TRT130928T38 TRT150328T24")
    assert got["cmd"] == "isin" and got["isins"] == ["TRT150328T24", "TRT130928T38"] and '"Ekle" sizin' in got["note"]
    assert one(node_run, "kağıt ekle")["isins"] == []                       # (the dialog empty)
    assert one(node_run, "kâğıt ekle TRT15")["error"] == '"TRT15" ISIN değil: 12 karakter bekleniyor (örn. TRT150328T24)'


def test_senaryo_loads_a_saved_one_or_sets_the_ret_fair_values_ppk_view(node_run):
    got = parse(node_run, "senaryo S2", "senaryo s2", "senaryo piyasa")
    assert [g[0]["cmd"] for g in got] == ["retview"] * 3 and [g[0]["code"] for g in got] == ["S2", "S2", "piyasa"]
    assert got[0][0]["label"] == "RET adil değer: PPK senaryosu S2" and "sizin görünümünüz" in got[0][0]["note"]
    assert one(node_run, "senaryo ppk -250") == {"cmd": "scenario", "name": "PPK -250", "label": "Senaryoyu yükle: PPK -250",
                                                 "note": "sorulur; kişisel girdileriniz onunkilerle değişir"}
    assert one(node_run, "senaryo sahin")["name"] == "Şahin" and one(node_run, "Senaryo ŞAHİN")["name"] == "Şahin"
    bad = one(node_run, "senaryo yok")
    assert bad["error"].startswith('"yok" adlı senaryonuz yok (senaryolarınız: PPK -250, Şahin)')
    listed = parse(node_run, "senaryo")[0]
    assert [x.get("name") or x.get("code") for x in listed] == ["PPK -250", "Şahin", "S1", "S2", "S3"]
    # none saved: the PPK views first (Enter runs the first), said after them that there is none
    bare = parse(node_run, "senaryo", env=dict(ENV, scenarios=[]))[0]
    assert [x.get("code") for x in bare[:3]] == ["S1", "S2", "S3"] and bare[3]["error"] == "Kayıtlı senaryonuz yok: Senaryolar'dan kaydedin"
    # before the user's scenarios are read: said so (the box reads the text again when they come)
    assert one(node_run, "senaryo foo", env=dict(ENV, scenarios=None))["error"].startswith("senaryolarınız okunuyor")
    assert one(node_run, "senaryo S3", env=dict(ENV, scenarios=None))["code"] == "S3"


def test_sayfa_and_launchpad_open_by_name(node_run):
    assert one(node_run, "sayfa günlük")["id"] == "blotter" and one(node_run, "sayfa gunluk islemler")["id"] == "blotter"
    assert one(node_run, "SAYFA BUGUN") == {"cmd": "page", "id": "bugun", "label": "Sayfayı aç: Bugün", "note": "Masa"}
    assert one(node_run, "sayfa xyz")["error"] == '"xyz" adlı bir sayfa yok'
    assert one(node_run, "sayfa") == {"complete": "sayfa ", "label": "sayfa <ad>", "note": "bir sayfayı aç, örn. sayfa ois"}
    assert one(node_run, "launchpad sabah")["name"] == "Sabah" and one(node_run, "launchpad ogle")["name"] == "Öğle"
    assert [x.get("name") or x["id"] for x in parse(node_run, "launchpad")[0]] == ["launchpad", "Sabah", "Öğle"]
    assert one(node_run, "launchpad yok")["error"] == '"yok" adlı launchpad\'iniz yok (launchpad\'leriniz: Sabah, Öğle)'


def test_a_commands_first_word_typed_offers_its_template_and_table_searches_stay_table_searches(node_run):
    got = parse(node_run, "re", "işl", "isl", "tr", "kâ", "kağıt", "sen", "sa", "la")
    assert [g[0]["complete"] for g in got] == ["ret ", "işlem gir ", "işlem gir ", "trade ", "kâğıt ekle ", "kâğıt ekle ", "senaryo ",
                                               "sayfa ", "launchpad "]
    assert all(len(g) == 1 for g in got)
    # what the table finder had before stays its own (the browser test's searches among them)
    assert parse(node_run, "interest", "faizden fiyat", "Opsiyon", "Eğri Hareketi", "trades", "kâğıtlar", "r", "", "   ", "retail x") == [None] * 10


def test_spellings_fold_to_one(node_run):
    got = node_run(folds=["İşlem Gİr", "ŞÇĞÜÖ ıI", "kâğıt"], tenors=["1m", "3AY", "1Yıl", "2h", "O/N", "aysonu", "IMM", "+5", "15.12.26", "1x", "10mn"])
    assert got["folded"] == ["islem gir", "scguo ii", "kagit"]
    assert got["tenors"] == ["1M", "3A", "1Y", "2H", "O/N", "ay sonu", "IMM", "+5", "15.12.26", None, None]
