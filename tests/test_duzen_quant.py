"""Düzen (27.11.2026, the desk: "Hepsini yap"): the 20 quant pages' layout - proposals 3, 5, 8, 9, 10 and 19 for them.
What a Python test can see of it: the signal lists' columns (``quantbase.js`` SIGNAL_HEAD: the trade first), their one
column choice and what it hides until a user chooses (``Service.DEFAULT_HIDDEN_COLUMNS``), the pages' frames (the
coverage and status tables Sinyaller's alone, no page of its own 46vh, the same order on every page, the secondary panels
of a long page folded), the quant levels' three decimals, the Trend table's reward / risk.  Nothing of a value or a
signal changes.  (On screen - the widths, the folding, the card brought into view: the browser test.)"""
import io
import json
import os
import re

from tto import quanttrend as qtr
from tto.service import Service

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "tto", "static", "js", "pages")

#: every list you can trade from starts with these (the desk's taste: explicit AL / SAT lines with tradeable levels first)
TRADE = ["İşlem", "Giriş", "Hedef", "Stop", "Beklenen K/Z", "Ödül / risk", "İsabet"]
#: the signal lists' 21 columns before the layout work (dc96cf3): the same 21 after it, in the new order
BEFORE = ["Aile", "Varlık", "İşlem", "Trades", "z", "Güç", "Giriş", "Hedef", "Stop", "Birim", "Beklenen K/Z", "Ödül / risk", "İsabet",
          "Yarı ömür (g)", "Tutma", "Carry / hf", "Carry % / yıl", "Rejim", "Uyum", "Kapılar", "Geri test"]


def _read(name, where=PAGES):
    with io.open(os.path.join(where, name), encoding="utf-8") as f:
        return f.read()


def _quant_files():
    return {fn: _read(fn) for fn in sorted(os.listdir(PAGES)) if fn.startswith("quant") and fn.endswith(".js")}


def _folded(text, first):
    """Whether the panel whose id is ``first`` (a regex of the call's first argument) is folded until opened."""
    return re.search(r"panel\(%s, [^\n]*folded: true" % first, text) is not None


def _signal_head():
    m = re.search(r"// <SIGNAL_HEAD>\n[^=]*=\s*(.*?);\n// </SIGNAL_HEAD>", _read("quantbase.js"), re.S)
    assert m, "quantbase.js: SIGNAL_HEAD between its markers"
    return json.loads(m.group(1))


def test_every_signal_list_starts_with_the_trade_and_keeps_every_column():
    head = _signal_head()
    assert head[:7] == TRADE
    assert sorted(head) == sorted(BEFORE)                          # (nothing dropped, nothing added: only the order)
    # the button that books the line follows the trade and its unit; the model and the secondary statistics last
    assert head.index("Trades") == 8 and head.index("Birim") == 7 and head.index("Aile") > head.index("Geri test")


def test_the_19_signal_lists_share_one_column_choice():
    files = _quant_files()
    base = files["quantbase.js"]
    assert "export const SIGNALS_TABLE = 'quant/signals';" in base
    for fn, text in files.items():
        # (no list keeps a choice of its own any more: "quant/<page>/signals")
        assert not re.search(r"'quant/[a-z]+/signals'|'quant/' \+ this\.what \+ '/signals'", text), fn
    lists = {fn: len(re.findall(r"new GridBox\(\w+, SIGNALS_TABLE,", text)) for fn, text in files.items()}
    # Sinyaller's list; one frame for quantviews.js's eight pages, quantfit.js's two; every other page its own
    assert lists["quant.js"] == 1 and lists["quantviews.js"] == 1 and lists["quantfit.js"] == 1
    assert {fn for fn, n in lists.items() if n} == {"quant.js", "quantviews.js", "quantfit.js", "quantpath.js", "quantlead.js", "quantviop.js",
                                                     "quantsira.js", "quantml.js", "quantoptspot.js", "quantdibssw.js"}
    assert len(re.findall(r"super\(host, ctx, '([a-z]+)'\)", files["quantviews.js"])) == 8
    assert len(re.findall(r"super\(host, ctx, '([a-z]+)'\)", files["quantfit.js"])) == 2
    # ... and Sinyaller's box (a launchpad, the side drawer, a window of its own) the same choice
    assert "SIGNALS_TABLE" in _read("pageboxes.js", os.path.join(ROOT, "tto", "static", "js"))


def test_the_signal_lists_hide_only_secondary_statistics_by_default():
    hidden = Service.DEFAULT_HIDDEN_COLUMNS["quant/signals"]
    head = _signal_head()
    assert hidden == ("Varlık", "Yarı ömür (g)", "Rejim", "Uyum", "Kapılar")
    assert set(hidden) <= set(head) and head[-len(hidden):] == list(hidden)        # (they are the list's tail)
    # never the trade, its levels, its P&L, its record, its carry, the button, the score, the model
    assert not set(hidden) & set(TRADE + ["Birim", "Trades", "z", "Güç", "Tutma", "Carry / hf", "Carry % / yıl", "Geri test", "Aile"])


def test_a_users_own_column_choice_wins_over_the_default(service):
    u = service.login("Düzen Quant Ayşe")["user"]
    other = service.login("Düzen Quant Mehmet")["user"]
    assert service.columns(u)["defaults"]["quant/signals"] == list(Service.DEFAULT_HIDDEN_COLUMNS["quant/signals"])
    service.set_columns(u, "quant/signals", [])                     # "Tümü": every column shown - kept as such
    out = service.columns(u)
    assert out["tables"]["quant/signals"] == [] and "quant/signals" not in out.get("defaults", {})
    service.set_columns(u, "quant/signals", ["Saat"])               # one of their own: theirs on all 19 lists
    assert service.columns(u)["tables"]["quant/signals"] == ["Saat"]
    assert "quant/signals" in service.columns(other)["defaults"]    # nobody else's view changes


def test_the_coverage_and_status_tables_are_on_sinyaller_alone_and_no_page_has_a_cap_of_its_own():
    files = _quant_files()
    calls = {fn: len(re.findall(r"this\.addStatus\(", text)) for fn, text in files.items()}
    assert {fn for fn, n in calls.items() if n} == {"quant.js"}     # Sinyaller; every other page a line above (coverageLine)
    assert "coverageLine(" in files["quantbase.js"] and "id: 'quant-coverage-line'" in files["quantbase.js"]
    # folded at Sinyaller's foot, with its settings and the alarm subscription
    assert _folded(files["quantbase.js"], r"this\.what \+ '-coverage'") and _folded(files["quantbase.js"], r"this\.what \+ '-status'")
    assert _folded(files["quant.js"], "'quant-subscribe'") and _folded(files["quant.js"], "'quant-settings'")
    # no quant page is a .volpage (its tables capped at 46vh): the app's one table height; no panel is wide unless asked
    for fn, text in files.items():
        assert "volpage" not in text, fn
    assert "'panel ' + (opts.wide ? 'wide' : 'fit')" in files["quantbase.js"]


def test_the_same_order_on_every_page_trade_tables_first():
    files = _quant_files()
    frame = lambda fn, title: re.search(r"this\.frame\('%s', \[([^\]]*)\]" % re.escape(title), files[fn]).group(1)  # noqa: E731
    # PCA / RV: what trades (rich / cheap, flies and spreads, FRA against the path) before the components; Eğri: the best
    # bond, the quote and the switch before the two fits; Korelasyon: the pairs before the matrix; İma Patikası: its kinks
    assert frame("quantviews.js", "PCA / RV").split(", ")[:3] == ["this.resid", "this.rv", "this.fra"]
    assert frame("quantfit.js", "Eğri Adil Değeri").split(", ") == ["this.best", "this.quotes.quote", "this.quotes.sw", "this.ois", "this.bonds"]
    assert frame("quantviews.js", "Korelasyon").split(", ")[:2] == ["this.pairs", "this.heat"]
    assert frame("quantpath.js", "İma Patikası").split(", ")[0] == "this.kinks"
    assert frame("quantviews.js", "Gün İçi").split(", ")[-1] == "this.st"            # (the bars' record last)
    # a long page's secondary panels folded until opened (VİOP's seven, PCA's three, Opsiyon's smile …)
    for pid in ("calendar", "expiry", "intraday", "intraday-days", "calibration", "ranges", "data"):
        assert _folded(files["quantviop.js"], "'quant-viop-%s'" % pid), pid
    for pid in ("periods", "stability", "loadw"):
        assert _folded(files["quantviews.js"], "'quant-pca-%s'" % pid), pid
    assert _folded(files["quantfit.js"], "'quant-opt-smile'")


def test_quant_levels_in_three_decimals_on_viop_and_dibs_switch():
    files = _quant_files()
    assert re.search(r"export const RATE_DIGITS = 3;", files["quantbase.js"])
    viop = files["quantviop.js"]
    # the contracts' implied rates, OIS, fair, offshore; the levels' title and the order levels; the days' lows and highs
    for x in ("ask", "bid", "mid", "ois", "fair", "off"):
        assert "N(r.%s, R)" % x in viop and "N(r.%s, 2)" % x not in viop, x
    assert "fmt(r.ask, RATE_DIGITS)" in viop and "fmt(b.level, RATE_DIGITS)" in viop and "fmt(s.level, RATE_DIGITS)" in viop
    assert "N(r.low, RATE_DIGITS)" in viop and "N(r.high, RATE_DIGITS)" in viop
    sw = files["quantdibssw.js"]
    assert "N(b.y, RATE_DIGITS), N(b.f, RATE_DIGITS)" in sw


def test_the_trend_table_has_its_lines_reward_to_risk():
    """Trend's table starts with the trade too: its row carries the line's reward / risk (the Sinyaller list's number)."""
    sg = {"id": "trend:OIS:2Y", "family": "trend", "page": "quant-trend", "line": "receive 2Y OIS", "hold": 21, "entry": 38.5, "target": None,
          "stop": 39.1, "px": None, "unit": "%", "digits": 3, "rr": 1.7, "trend": {"money": {"total": 125000.0, "ccy": "TL"}, "bucket": "1–1,5"}}
    v = {"tables": {"trend": {"rows": [{"sid": "trend:OIS:2Y", "label": "2Y OIS", "group": "TRY OIS"}, {"label": "1Y OIS", "why": "geçmiş kısa"}],
                              "_keys": ["OIS:2Y"]}, "errors": {}}, "signals": [sg], "gated": []}
    fit = {"mons": {}, "cfg": {"entry_z": 2.0}, "coverage": [{"key": "OIS:2Y", "label": "2Y OIS", "n": 40}]}
    out = qtr.view(None, "trend", {}, v, fit)
    rows = out["trend"]["rows"]
    assert rows[0]["rr"] == 1.7 and rows[0]["entry"] == 38.5 and rows[0]["stop"] == 39.1 and rows[0]["exp"] == 125000.0
    assert "rr" not in rows[1]                                      # (a row without a line: no levels)
    assert out["signals"] == [sg] and out["coverage"] == fit["coverage"]
