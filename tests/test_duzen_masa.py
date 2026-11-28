"""The desk tools' layout (27.11.2026, the desk's "Hepsini yap" to the layout proposals; docs/desk-decisions.md,
"Düzen: masa araçları, FX, menü, Ayarlar"): the pure parts of the pages read under Node - the menu's groups in the
server's order, Araçlar last and folded (menu.js; the reorganization of 28.11.2026), Bugün's columns and the empty columns it drops (bugun.js), Günlük İşlemler's CPT × VADE
with the counterparties that hold a DV01 (blotter.js, also on the service's own table), Gün Sonu Matrisi's bond names and
the one heat scale (history.js), the panels folded until opened (fx.js, history.js).  Each module is copied as an .mjs
with its imports stubbed (none of these functions uses them).  What the pages do on screen is the browser test's
(tests/e2e/e2e.js, the duzenMasa checks).  Skipped without Node.js."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "tto", "static", "js")
MODULES = {"menu": "menu.js", "bugun": "pages/bugun.js", "blotter": "pages/blotter.js", "history": "pages/history.js",
           "fx": "pages/fx.js"}

STUB = ("const __stub = new Proxy({}, { get: (t, k) => (k === 'then' ? undefined : function stub() { return {}; }) });\n")

RUNNER = r"""
import * as menu from './menu.mjs';
import * as bugun from './bugun.mjs';
import * as blotter from './blotter.mjs';
import * as history from './history.mjs';
import * as fx from './fx.mjs';
const mods = { menu, bugun, blotter, history, fx };
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const calls = JSON.parse(raw);
  const plain = (x) => (x instanceof Set ? [...x] : x);
  const out = calls.map(([mod, name, args]) => {
    const x = mods[mod][name];
    return plain(typeof x === 'function' ? x(...(args || [])) : x);
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def _stubbed(src):
    """A module with each ``import { a, b as c } from '…';`` turned into names of a stub (none is called on loading)."""
    def repl(m):
        names = []
        for x in m.group(1).split(","):
            x = x.strip()
            if not x:
                continue
            a, _, b = x.partition(" as ")
            names.append(a.strip() + (": " + b.strip() if b else ""))
        return "const { " + ", ".join(names) + " } = __stub;"
    out = re.sub(r"^import\s*\{([^}]*)\}\s*from\s*'[^']+';", repl, src, flags=re.M)
    assert not re.search(r"^import\b", out, flags=re.M), "an import this harness does not read"
    return STUB + out


@pytest.fixture(scope="module")
def node_run(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to read the pages' modules")
    d = tmp_path_factory.mktemp("duzen-masa")
    for name, rel in MODULES.items():
        with open(os.path.join(JS, rel), encoding="utf-8") as fh:
            (d / (name + ".mjs")).write_text(_stubbed(fh.read()), encoding="utf-8")
    (d / "run.mjs").write_text(RUNNER, encoding="utf-8")

    def run(*calls):
        res = subprocess.run([node, str(d / "run.mjs")], input=json.dumps(calls), capture_output=True, text=True, encoding="utf-8",
                             timeout=60)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout)

    return run


def _source(rel):
    with open(os.path.join(JS, rel), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------ the menu
def test_the_menu_keeps_the_servers_groups_araclar_last_and_nothing_leaves_it(node_run, service):
    """The groups in the server's order (tto/navmenu.py, the desk's reorganization of 28.11.2026 - before it one-entry
    groups joined their neighbour here: DV01 Risk is TRY Faiz's, USD · FOMC FX · USD's now on the server), Araçlar last
    with the administrators' pages and folded until opened; every page of the nav is in the menu once - a page of an entry
    with tabs as one of its tabs."""
    pages = service.nav()
    model, tools_folded, masa_folded = node_run(["menu", "menuModel", [pages, True]], ["menu", "groupFolded", ["Araçlar"]],
                                                ["menu", "groupFolded", ["Masa"]])
    groups = [g["group"] for g in model]
    assert groups == [None, "Masa", "TRY Faiz", "Tahvil", "FX · USD", "Quant", "Araçlar"]
    by = {g["group"]: [e["id"] for e in g["entries"]] for g in model}
    assert by["TRY Faiz"][-1] == "dv01" and by["FX · USD"] == ["fx.spot", "usd"]
    assert by["Araçlar"] == ["calc", "motor", "settings", "explorer", "users", "backup"]
    listed = [x for g in model for e in g["entries"] for x in ([t["id"] for t in e["tabs"]] if e.get("tabs") else [e["id"]])]
    navs = [p["id"] for p in pages]
    assert sorted(listed) == sorted(navs + ["launchpad", "explorer", "users", "backup"]) and len(listed) == len(set(listed))
    assert all(e.get("hint") for g in model for e in g["entries"])                       # (B8: every entry says what it is)
    assert tools_folded is True and masa_folded is False
    # (a group a page of another version names keeps its place, before Araçlar)
    (model2,) = node_run(["menu", "menuModel", [pages + [{"id": "yeni", "title": "Yeni", "group": "Yeni grup"}], False]])
    assert [g["group"] for g in model2][-2:] == ["Yeni grup", "Araçlar"]


# ------------------------------------------------------------------ Bugün
def test_bugun_columns_put_the_things_to_do_first(node_run):
    count = node_run(*[["bugun", "columnCount", [w]] for w in (2600, 1678, 1358, 1124, 980, 960, 782, 300)])
    assert count == [3, 3, 2, 2, 2, 1, 1, 1]                                   # (a column never under 480 px)
    order, p1, p2, p3 = node_run(["bugun", "ORDER"], ["bugun", "columnPlan", [1]], ["bugun", "columnPlan", [2]], ["bugun", "columnPlan", [3]])
    assert order == ["ret", "chat", "agenda", "trades", "quant", "dibs"]
    assert p3 == [["ret", "chat", "agenda"], ["trades", "quant"], ["dibs"]] and p2 == [["ret", "chat", "agenda"], ["trades", "quant", "dibs"]]
    for plan in (p1, p2, p3):
        assert [k for col in plan for k in col] == order                      # every block once, read in the same order


def test_bugun_drops_a_column_empty_in_every_row(node_run):
    head = {"head": True, "cells": ["Kâğıt", "OIS ASW", "FX swap ASW", "Sıfır kupon", ""]}
    rows = [head, {"cells": ["15.03.28", "UCUZ (+143,4 bp)", "UCUZ (+36,3 bp)", "—", ""]},
            {"cells": ["13.09.28", "UCUZ (+95,8 bp)", "PAHALI (−33,2 bp)", "—", ""]}]
    turned = rows + [{"cells": ["12.09.29", "UCUZ", "—", "—", "döndü"]}]
    with_sum = [head, {"cells": ["a", "1", "", "—", "x"]}, {"sum": True, "cells": ["Toplam", "1", "9", "9", "9"]}]
    assert node_run(["bugun", "emptyColumns", [rows]], ["bugun", "emptyColumns", [turned]], ["bugun", "emptyColumns", [with_sum]],
                    ["bugun", "emptyColumns", [[head]]]) == [[3, 4], [3], [2, 3], []]


# ------------------------------------------------------------------ Günlük İşlemler: CPT × VADE
def _cpt_table():
    cell = lambda t, v=None, **kw: dict({"t": t, "k": "n" if v is not None else "s"}, **({"v": v} if v is not None else {}), **kw)  # noqa: E731
    head = [cell(x, f="hd", b=1) for x in ("CPT", "Vade", "Pay DV01", "Pay Ort. Faiz", "Receive DV01", "Receive Ort. Faiz", "Net DV01")]
    rows, r = [head], [88]
    tenors = ["ON", "1W", "1Y", "2Y"]

    def block(name, filled):
        for t in tenors:
            dv = filled.get(t)
            rows.append([cell(name, f="note"), cell(t, b=1), cell("-" if not dv else str(dv), dv if dv else 0.0), cell(""),
                         cell("-", 0.0), cell(""), cell("-" if not dv else str(dv), dv if dv else 0.0)])
            r.append(r[-1] + 1)
        total = sum(filled.values())
        rows.append([cell(name, f="sub"), cell("TOPLAM", f="sub"), cell(str(total), float(total), f="sub"), cell(""), cell("-", 0.0), cell(""),
                     cell(str(total), float(total), f="sub")])
        r.append(r[-1] + 1)

    def empty_block():
        for t in tenors + ["TOPLAM"]:
            rows.append([cell("", f="note"), cell(t, b=1)] + [cell("") for _ in range(5)])
            r.append(r[-1] + 1)

    block("AAA", {"1Y": 996})
    empty_block()
    block("BBB", {})                    # a counterparty whose trades netted to nothing: no DV01, left out
    block("(CPT YOK)", {"ON": 12, "2Y": 300})
    rows.append([cell("GENEL", f="in"), cell("TOPLAM", f="in"), cell("1308", 1308.0), cell(""), cell("-", 0.0), cell(""), cell("1308", 1308.0)])
    r.append(r[-1] + 1)
    return {"sheet": "Günlük İşlemler", "rows": rows, "r": r, "c": list("PQRSTUV")}


def test_cpt_x_vade_shows_the_counterparties_with_a_dv01(node_run):
    data = _cpt_table()
    (out,) = node_run(["blotter", "cptRows", [data]])
    shown = [(row[0]["t"], row[1]["t"]) for row in out["rows"]]
    assert shown == [("CPT", "Vade"), ("AAA", "1Y"), ("AAA", "TOPLAM"), ("(CPT YOK)", "ON"), ("(CPT YOK)", "2Y"), ("(CPT YOK)", "TOPLAM"),
                     ("GENEL", "TOPLAM")]
    # every row keeps its sheet row and its cells as they came (nothing computed); the columns are the table's
    keep = [0, 3, 5, 16, 19, 20, 21]                  # caption · AAA 1Y, TOPLAM · (CPT YOK) ON, 2Y, TOPLAM · GENEL
    assert out["r"] == [data["r"][i] for i in keep] and out["c"] == data["c"]
    assert out["rows"] == [data["rows"][i] for i in keep]
    # nothing with a DV01: the caption and GENEL TOPLAM; a table without a DV01 column comes back as it is
    bare = _cpt_table()
    bare["rows"] = [bare["rows"][0]] + bare["rows"][6:11] + [bare["rows"][-1]]
    bare["r"] = [bare["r"][0]] + bare["r"][6:11] + [bare["r"][-1]]
    plain = {"rows": [[{"t": "A", "f": "hd"}], [{"t": "x"}]], "r": [1, 2]}
    nothing, same = node_run(["blotter", "cptRows", [bare]], ["blotter", "cptRows", [plain]])
    assert [(row[0]["t"], row[1]["t"]) for row in nothing["rows"]] == [("CPT", "Vade"), ("GENEL", "TOPLAM")] and same == plain


def test_cpt_x_vade_of_the_service_keeps_every_dv01(node_run, service):
    """On the workbook's own table (P87:V349): its caption is read, no row with a DV01 is dropped, each kept
    counterparty keeps its TOPLAM, and what is dropped holds no DV01."""
    u = service.login("Düzen Masa CPT")["user"]
    table = next(p for p in service.blotter(u)["sheet"] if p["id"] == "cpt")["data"]
    (out,) = node_run(["blotter", "cptRows", [table]])
    rows = table["rows"]
    assert [c["t"] for c in rows[0]] == ["CPT", "Vade", "Pay DV01", "Pay Ort. Faiz", "Receive DV01", "Receive Ort. Faiz", "Net DV01"]
    has = lambda row: any(isinstance(row[j].get("v"), (int, float)) and abs(row[j]["v"]) > 1e-9 for j in (2, 4, 6))  # noqa: E731
    kept = set(out["r"])
    for r, row in zip(table["r"], rows):
        if has(row) or row[0].get("t") == "GENEL" or r == table["r"][0]:
            assert r in kept, (r, row[:2])
        elif r in kept:
            assert row[1].get("t") == "TOPLAM", (r, row[:2])
    assert len(out["rows"]) < len(rows) and out["rows"][-1][0]["t"] == "GENEL"


# ------------------------------------------------------------------ Gün Sonu Matrisi, the heat scale, the folds
def test_bond_names_only_when_they_tell_more_than_the_kind(node_run):
    gov, bill = "TURKIYE GOVERNMENT BOND", "TURKIYE T-BILL"
    same = [{"type": "S", "name": gov}, {"type": "B", "name": bill}, {"type": "T", "name": gov}, {"type": "S", "name": gov}, {"type": "S", "name": ""}]
    other = same + [{"type": "S", "name": "TURKIYE GOVT CPI LINKED"}]
    assert node_run(["history", "namesTellMore", [same]], ["history", "namesTellMore", [other]], ["history", "namesTellMore", [[]]]) == [False, True, False]


def test_one_heat_scale_a_rise_in_the_heat_maps_colour(node_run):
    up, down = [230, 103, 103], [57, 135, 229]                                  # app.css --heat-up / --heat-down (dark)
    a, b, c, z = node_run(["history", "heat", [12, 10, up]], ["history", "heat", [-12, 10, down]], ["history", "heat", [1, 10, up]],
                          ["history", "heat", [0, 10, up]])
    rgb = lambda x: [int(x[i:i + 2], 16) for i in (0, 2, 4)]  # noqa: E731
    assert rgb(a)[0] > rgb(a)[1] == rgb(a)[2] and rgb(b)[2] > rgb(b)[1] > rgb(b)[0] and z is None
    assert abs(rgb(c)[0] - 128) < abs(rgb(a)[0] - 128)                         # stronger the larger the move
    src = _source("pages/history.js")
    assert "[224, 106, 58]" not in src and "--heat-up" in src                  # (the matrix's own orange is gone)


def test_folded_until_opened_and_the_jump_bar_names_every_settings_panel(node_run):
    folded, jumps = node_run(["fx", "FOLDED_FIRST"], ["history", "SETTINGS_JUMPS"])
    assert sorted(folded) == ["fx-board", "fx-method", "fx-tenor"]
    fx = _source("pages/fx.js")
    for pid in folded:
        assert "panel('%s'" % pid in fx
    hist = _source("pages/history.js")
    built = re.findall(r"(?:gridPanel|panel)\('[^']*', \{[^}]*?id: '([a-z-]+)'", hist)
    assert [j[0] for j in jumps] == [x for x in built if x in {j[0] for j in jumps}] and len(jumps) == 9
    assert "fold: true, folded: true" in hist                                  # Kullanılan kaynak, Tarihçe serileri
    fxvol = _source("pages/fxvol.js")
    assert "fxvol-method'" not in fxvol and "#/fx?p=fx-method" in fxvol and "height: '26px'" not in fxvol
