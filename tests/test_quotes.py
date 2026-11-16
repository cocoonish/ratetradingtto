"""Kotasyon kopyala: a pricing table's prices as a quote to send a client, in Turkish or English (tto/quotes.py).

Every table that opts in ("client_quote" in its page definition) is quoted from planted values in both languages: the
pair, the value date and the maturity with the days, the spot, the swap points, the outright, the TRY and the foreign
rate, the amount and the side where the table has them - each number as its cell's format writes it, in the quote's
language (34,38 / 34.38; 12.663 / 12,663; 04.12.2026 / 04 Dec 2026).  On the workbook the numbers are the table's own."""
from __future__ import annotations

import datetime as dt
import re

import pytest

from conftest import cell
from tto import quotes as qt
from tto.views import load_views
from tto.xl.values import date_to_serial

D = dt.date
TODAY = D(2026, 11, 17)
VIEWS = load_views()
#: every table that gives a client quote: (page, table)
QUOTED = [(v["id"], p["id"]) for v in VIEWS for p in v["panels"] if p.get("client_quote")]


def serial(d):
    return float(date_to_serial(d))


#: what each field's cells hold (bid, ask): a value and its number format
PLANTED = {
    "start": [(serial(D(2026, 11, 4)), "dd.mm.yyyy")],
    "end": [(serial(D(2026, 12, 4)), "dd.mm.yyyy")],
    "days": [(30.0, "0")],
    "spot": [(49.997, "#,##0.0000"), (49.9975, "#,##0.0000")],
    "near": [(50.1234, "0.0000")],
    "points": [(12663.0, "#,##0"), (12664.0, "#,##0")],
    "outright": [(51.2633, "_-* #,##0.0000_-;\\-* #,##0.0000_-;_-* \"-\"??_-;_-@_-"), (51.2639, "#,##0.0000")],
    "try": [(0.3438, "0.00%"), (0.344, "0.00%")],
    "ccy": [(3.8912, "0.00")],
    "on": [(0.31265, "0.000%")],
    "amount": [(5e6, "_-[$$-409]* #,##0_ ;_-[$$-409]* \\-#,##0\\ ;_-[$$-409]* \"-\"??_ ;_-@_ ")],
    "side": [("B", "General")],
}
#: the same in the quote, Turkish and English
WRITTEN = {
    "start": ("04.11.2026", "04 Nov 2026"), "end": ("04.12.2026", "04 Dec 2026"), "spot": ("49,9970", "49.9970"),
    "spot2": ("49,9970 / 49,9975", "49.9970 / 49.9975"), "near": ("50,1234", "50.1234"), "points": ("12.663", "12,663"),
    "points2": ("12.663 / 12.664", "12,663 / 12,664"), "outright": ("51,2633", "51.2633"),
    "outright2": ("51,2633 / 51,2639", "51.2633 / 51.2639"), "try": ("34,38", "34.38"), "try2": ("34,38 / 34,40", "34.38 / 34.40"),
    "ccy": ("3,89", "3.89"), "on": ("31,265", "31.265"), "amount": ("5.000.000", "5,000,000"),
}


def plant(spec, sheet, filled=2):
    """A reader of planted values for a spec: every cell it reads holds its field's value (a table of quotes: its first
    ``filled`` rows; the others are empty, as a free row is)."""
    cells = {}
    rows = qt.table_rows(spec)
    at = [rows[0] + k for k in range(filled)] if rows else [None]
    for p in qt.parts(spec):
        for key in qt.KEYS:
            f = qt.field(p, key)
            if not f:
                continue
            srcs = f["src"] if isinstance(f["src"], list) else [f["src"]]
            for k, s in enumerate(srcs):
                for n, r in enumerate(at):
                    ref = qt.ref_of(s, sheet, r)
                    if ref and (qt.is_column(s) or n == 0):
                        cells[ref] = PLANTED[key][min(k, len(PLANTED[key]) - 1)]
        for n, r in enumerate(at):
            if p.get("label"):
                cells[qt.ref_of(p["label"], sheet, r)] = ("%dM" % (n + 1), "General")
            if isinstance(p.get("pair"), dict):
                cells[qt.ref_of(p["pair"]["src"], sheet, r)] = ("USDTRY", "General")
    return lambda ref: cells.get(ref, (None, "General"))


def panel_of(view_id, panel_id):
    v = next(x for x in VIEWS if x["id"] == view_id)
    p = next(x for x in v["panels"] if x["id"] == panel_id)
    return v, p


def test_the_calculators_named_give_a_quote():
    """Masa's forward tables, KIRIK VADE & KARŞILIK, TARİH ARASI FORWARD, the Forward page's calculators and its
    forward tables, and the VİOP Target (on its page and in Masa's summary)."""
    assert set(QUOTED) == {("masa", "EKS"), ("masa", "EKSE"), ("masa", "B10"), ("masa", "B22"), ("masa", "B17"),
                           ("forward", "B7"), ("forward", "B8"), ("forward", "B9"), ("forward", "B10"), ("forward", "B21"),
                           ("forward", "B18"), ("forward", "FR1"), ("forward", "FR2"), ("forward", "FR3"),
                           ("forward", "EKF1"), ("forward", "EKF5"), ("viop", "B33")}


@pytest.mark.parametrize("view_id, panel_id", QUOTED, ids=["%s/%s" % x for x in QUOTED])
@pytest.mark.parametrize("lang", ["tr", "en"])
def test_every_table_quotes_its_planted_values_in_both_languages(view_id, panel_id, lang):
    v, p = panel_of(view_id, panel_id)
    spec, sheet = p["client_quote"], p.get("sheet", v["sheet"])
    k = 1 if lang == "en" else 0
    text = qt.quote_text(spec, plant(spec, sheet), sheet, lang, TODAY)
    lines = text.split("\n")
    assert ("17 Nov 2026" if lang == "en" else "17.11.2026") in lines[0], lines[0]
    assert not any(line != line.rstrip() for line in lines)                      # (no trailing spaces)
    for part in qt.parts(spec):
        pair = part.get("pair")
        if isinstance(pair, str):
            assert any(line.startswith(pair) for line in lines), (pair, lines)
        for key in ("start", "end", "near", "on", "amount"):
            if qt.field(part, key):
                assert WRITTEN[key][k] in text, (key, text)
        for key in ("spot", "points", "outright", "try"):
            f = qt.field(part, key)
            if f:
                want = WRITTEN[key + "2"][k] if isinstance(f["src"], list) else WRITTEN[key][k]
                assert re.search(re.escape(want).replace(r"\ /\ ", r"\s*/\s*"), text), (key, want, text)
        if qt.field(part, "ccy"):
            assert WRITTEN["ccy"][k] in text
        if qt.field(part, "side"):
            assert ("Buy USD" if lang == "en" else "USD alış") in text
        if qt.field(part, "days") and qt.field(part, "end") and not qt.table_rows(spec):
            assert ("(30 days)" if lang == "en" else "(30 gün)") in text
    # the other language's numbers are nowhere
    other = WRITTEN["outright"][1 - k]
    assert other not in text
    rows = qt.table_rows(spec)
    if rows:
        # a table of quotes: a line for each of the two rows that hold a price, under a caption line; one row alone
        data = [line for line in lines[lines.index("") + 2:]] if "" in lines else []
        assert len(data) == 2, text
        one = qt.quote_text(spec, plant(spec, sheet), sheet, lang, TODAY, row=rows[0])
        assert WRITTEN["outright"][k] in one and one.count("\n") >= 3
        if spec.get("label"):
            assert "1M" in one.split("\n")[0]
        with pytest.raises(qt.QuoteError):
            qt.quote_text(spec, plant(spec, sheet), sheet, lang, TODAY, row=rows[0] + 2)       # an empty row
        with pytest.raises(qt.QuoteError):
            qt.quote_text(spec, plant(spec, sheet), sheet, lang, TODAY, row=rows[1] + 1)       # not a row of it


def test_the_desks_forward_matrix_word_for_word():
    v, p = panel_of("masa", "EKS")
    spec = p["client_quote"]
    read = plant(spec, "EK_FWD")
    assert qt.quote_text(spec, read, "EK_FWD", "tr", TODAY) == "\n".join([
        "USDTRY forward · 17.11.2026 · bid / ask",
        "Başlangıç  04.11.2026",
        "Spot       49,9970 / 49,9975",
        "",
        "Vade  Vade tarihi  Gün       Swap puanı           Outright    TRY faizi %  USD faizi %",
        "1M    04.12.2026    30  12.663 / 12.664  51,2633 / 51,2639  34,38 / 34,40         3,89",
        "2M    04.12.2026    30  12.663 / 12.664  51,2633 / 51,2639  34,38 / 34,40         3,89",
    ])
    assert qt.quote_text(spec, read, "EK_FWD", "en", TODAY, row=5) == "\n".join([
        "USDTRY forward 1M · 17 Nov 2026 · bid / ask",
        "Value date   04 Nov 2026",
        "Maturity     04 Dec 2026 (30 days)",
        "Spot         49.9970 / 49.9975",
        "Swap points  12,663 / 12,664",
        "Outright     51.2633 / 51.2639",
        "TRY rate %   34.38 / 34.40",
        "USD rate %   3.89",
    ])


def test_a_calculator_of_two_pairs_and_one_with_an_amount_and_a_side_word_for_word():
    v, p = panel_of("forward", "B7")
    spec = p["client_quote"]
    read = plant(spec, "Forward")
    both = qt.quote_text(spec, read, "Forward", "tr", TODAY)
    usd, eur = both.split("\n\n")
    assert usd == "\n".join([
        "USDTRY forward · 17.11.2026",
        "Başlangıç    04.11.2026",
        "Vade tarihi  04.12.2026 (30 gün)",
        "Spot         49,9970",
        "Swap puanı   12.663",
        "Outright     51,2633",
        "TRY faizi %  34,38",
        "USD faizi %  3,89",
    ])
    assert eur.split("\n")[0] == "EURTRY forward · 17.11.2026" and eur.split("\n")[-1] == "EUR faizi %  3,89"
    assert qt.quote_text(spec, read, "Forward", "en", TODAY, part=1).split("\n")[-1] == "EUR rate %   3.89"
    assert qt.part_name(spec, 0) == "USDTRY" and qt.part_name(spec, 1) == "EURTRY"
    v, p = panel_of("forward", "B18")
    spec = p["client_quote"]
    assert qt.quote_text(spec, plant(spec, "Forward"), "Forward", "en", TODAY) == "\n".join([
        "USDTRY forward · 17 Nov 2026",
        "Side             Buy USD",
        "Value date       04 Nov 2026",
        "Maturity         04 Dec 2026 (30 days)",
        "Spot             49.9970",
        "Outright         51.2633",
        "TRY OIS rate %   34.38",
        "USD SOFR rate %  3.89",
        "Amount           5,000,000 USD",
    ])


def test_the_viop_target_row_its_side_and_a_contract_kept_as_text():
    v, p = panel_of("viop", "B33")
    spec = p["client_quote"]
    cells = {"VIOP!L331": ("Spot", "General"), "VIOP!M331": ("31.12.2026", "General"), "VIOP!N331": ("LONG", "General"),
             "VIOP!Y331": (57.0, "0"), "VIOP!R331": (49.997, "#,##0.0000"), "VIOP!T331": (2.4061, "#,##0.0000"),
             "VIOP!S331": (52.4031, "#,##0.0000"), "VIOP!Q331": (0.3455, "0.00%")}
    read = lambda ref: cells.get(ref, (None, "General"))                       # noqa: E731
    assert qt.quote_text(spec, read, "VIOP", "tr", TODAY, row=331) == "\n".join([
        "VİOP USDTRY spread · 17.11.2026",
        "Yön (uzak USD)      LONG",
        "Yakın               Spot",
        "Uzak                31.12.2026 (57 gün)",
        "Yakın fiyat         49,9970",
        "Spread fiyatı       2,4061",
        "Uzak limit fiyatı   52,4031",
        "Hedef faiz % (360)  34,55",
    ])
    en = qt.quote_text(spec, read, "VIOP", "en", TODAY)
    assert en.split("\n")[-1] == "LONG            Spot  31 Dec 2026    57     49.9970        2.4061          52.4031                34.55"
    with pytest.raises(qt.QuoteError):
        qt.quote_text(spec, lambda ref: (None, "General"), "VIOP", "tr", TODAY)          # no target typed: nothing to quote


def test_numbers_are_the_cells_format_in_the_quotes_language():
    assert qt.number_text(12663.0, "#,##0", "tr") == "12.663" and qt.number_text(12663.0, "#,##0", "en") == "12,663"
    assert qt.number_text(0.042, "0.00%", "tr") == "4,20" and qt.number_text(36.1079, "0.0000", "en") == "36.1079"
    assert qt.number_text(-37072.0, "#,##0;\\-#,##0;0", "tr") == "-37.072"
    assert qt.number_text(0.0, "_-* #,##0_-;\\-* #,##0_-;_-* \"-\"??_-;_-@_-", "tr") == "0"      # ("-" for a zero)
    assert qt.number_text(49.99773, "General", "tr") == "49,99773"
    assert qt.number_text(None, "0.00", "tr") == "" and qt.number_text("x", "0.00", "tr") == ""
    assert qt.date_value_text(serial(D(2026, 12, 4)), "en") == "04 Dec 2026" and qt.date_value_text("Spot", "en") == "Spot"
    assert qt.date_value_text("30.11.2026", "en") == "30 Nov 2026" and qt.day_text(D(2027, 5, 4), "tr") == "04.05.2027"


def test_the_specs_name_real_cells():
    """Every cell a quote reads is a cell of its workbook (a column at its first row); only the known words."""
    from tto.books import load_books
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    books = load_books(os.path.join(root, "models"))
    for view_id, panel_id in QUOTED:
        v, p = panel_of(view_id, panel_id)
        spec, sheet = p["client_quote"], p.get("sheet", v["sheet"])
        assert set(spec) <= qt.SPEC_KEYS, (view_id, panel_id, set(spec) - qt.SPEC_KEYS)
        for part in qt.parts(spec):
            assert set(part) <= qt.SPEC_KEYS
            for key in qt.KEYS:
                f = qt.field(part, key)
                if f:
                    assert set(f) <= qt.FIELD_KEYS and (not isinstance(f["src"], list) or len(f["src"]) == 2), (panel_id, key)
        book = books[v["book"]]
        refs = qt.sources(spec, sheet)
        assert refs, (view_id, panel_id)
        for ref in refs:
            si, rc = book.cell(ref)
            assert si >= 0, ref


def test_the_inputs_say_how_a_tenor_counts():
    """A ``tenor`` is on date inputs only, with known words: a pair the desk keeps calendars of, a column, a start."""
    from tto import extras as ex
    seen = 0
    for v in VIEWS:
        for inp in v["inputs"]:
            t = inp.get("tenor")
            if t is None:
                continue
            seen += 1
            assert inp.get("kind") == "date" and set(t) <= {"pair", "pair_col", "from"}, (v["id"], inp["range"])
            assert t.get("pair", "TRY") == "TRY" or ex.pair_calendar(t["pair"]), (v["id"], inp["range"])
            assert re.match(r"^([A-Z]{1,3}|\d+|([^!]+!)?[A-Z]{1,3}\d+)$", t.get("from", "A")), (v["id"], inp["range"])
    kinds = {(v["id"], i["range"]): i.get("tenor") for v in VIEWS for i in v["inputs"]}
    assert kinds[("forward", "D2")] == {"pair": "USDTRY"} and kinds[("forward", "EK_FWD!B104:B113")] == {"pair": "EURTRY"}
    assert kinds[("masa", "E60")] == {"pair": "USDTRY", "from": "C60"} and kinds[("forward", "EK_FWD!B68:C77")]["pair_col"] == "A"
    assert seen >= 40


# ---------------------------------------------------------------------------------------------- on the workbook
def test_on_the_workbook_the_numbers_are_the_tables_own(service):
    """The desk's USDTRY summary quoted on the recorded market: each row's points, outright and rates are what the table
    shows - in the user's number format and in the other one alike; a calculator of two pairs gives both or one; the
    page says which tables offer a quote (and their rows / parts)."""
    u = service.login("Kotasyon Masa")["user"]
    try:
        page = service.view(u, "masa", locale="tr")
        eks = next(p for p in page["panels"] if p["id"] == "EKS")
        assert eks["client_quote"] == {"rows": "5:14"}
        shown = {c: t for c, t in zip(eks["data"]["c"], [x.get("t") for x in eks["data"]["rows"][eks["data"]["r"].index(5)]])}
        tr = service.client_quote(u, "masa", "EKS", language="tr")["text"]
        line = next(x for x in tr.split("\n") if x.startswith("1M "))
        for col in ("B", "C", "H", "I", "J", "K", "M", "N"):
            assert shown[col] in line, (col, shown[col], line)
        en_page = service.view(u, "masa", locale="en")
        en_eks = next(p for p in en_page["panels"] if p["id"] == "EKS")
        en_shown = {c: t for c, t in zip(en_eks["data"]["c"], [x.get("t") for x in en_eks["data"]["rows"][en_eks["data"]["r"].index(5)]])}
        en = service.client_quote(u, "masa", "EKS", language="en")["text"]
        en_line = next(x for x in en.split("\n") if x.startswith("1M "))
        for col in ("H", "I", "J", "K"):
            assert en_shown[col] in en_line, (col, en_shown[col], en_line)
        assert en.split("\n")[0].startswith("USDTRY forward · 03 Nov 2026 · bid / ask")
        one = service.client_quote(u, "masa", "EKS", row=5, language="tr")["text"].split("\n")
        assert one[0] == "USDTRY forward 1M · 03.11.2026 · bid / ask" and one[2] == "Vade tarihi  04.12.2026 (30 gün)"
        fwd = next(p for p in service.view(u, "forward")["panels"] if p["id"] == "B7")
        assert fwd["client_quote"] == {"parts": ["USDTRY", "EURTRY"]}
        both = service.client_quote(u, "forward", "B7")["text"]
        assert both.count("\n\n") == 1 and service.client_quote(u, "forward", "B7", part=1)["text"].startswith("EURTRY forward")
        # the user's own inputs count: a TRY rate typed into the calculator is in the quote
        service.set_inputs(u, "tto", [{"ref": "Forward!AH10", "value": "40"}])
        assert "TRY faizi %  40,00" in service.client_quote(u, "forward", "B7", part=0)["text"]
        assert cell(service, "Forward!AH10", u) == pytest.approx(0.4)
    finally:
        service.reset_inputs(u, "tto")


def test_the_quote_over_http(service):
    from starlette.testclient import TestClient
    from conftest import auth
    from tto.server import create_app
    hdr = auth(service, "Kotasyon HTTP")
    client = TestClient(create_app(service=service))                          # (no "with": the shared service stays up)
    r = client.get("/api/quote", params={"view": "forward", "panel": "FR1", "language": "en", "lang": "tr"}, headers=hdr)
    assert r.status_code == 200 and r.json()["language"] == "en"
    assert r.json()["text"].startswith("USDTRY forward · 03 Nov 2026 · bid / ask") and "Curve" in r.json()["text"]
    r = client.get("/api/quote", params={"view": "forward", "panel": "FR1", "row": "48"}, headers=hdr)
    assert r.status_code == 200 and r.json()["text"].startswith("USDTRY forward OIS · 03.11.2026")
    assert client.get("/api/quote", params={"view": "forward", "panel": "FR1", "row": "60"}, headers=hdr).status_code == 400
    assert client.get("/api/quote", params={"view": "forward", "panel": "B11"}, headers=hdr).status_code == 404
    assert client.get("/api/quote", params={"view": "yok", "panel": "B7"}, headers=hdr).status_code == 404
    assert client.get("/api/quote", params={"view": "forward", "panel": "B7"}, headers={"Authorization": ""}).status_code == 401
