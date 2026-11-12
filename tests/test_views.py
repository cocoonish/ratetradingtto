"""Page definitions are consistent with the workbooks they show."""
import pytest

from tto.views import load_views
from tto.xl.model import Model, parse_range
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWS = load_views()


@pytest.fixture(scope="module")
def models():
    return {"tto": Model.load(os.path.join(ROOT, "models", "tto.json.gz")),
            "sofr": Model.load(os.path.join(ROOT, "models", "sofr.json.gz"))}


def test_every_sheet_of_both_workbooks_has_a_page(models):
    covered = {(v["book"], v["sheet"]) for v in VIEWS}
    for book, model in models.items():
        for sh in model.sheets:
            if sh.name == "Günlük İşlemler":
                continue                        # has its own page (the blotter)
            assert (book, sh.name) in covered, sh.name


def test_ids_are_unique():
    ids = [v["id"] for v in VIEWS]
    assert len(ids) == len(set(ids))
    for v in VIEWS:
        pids = [p["id"] for p in v["panels"]]
        assert len(pids) == len(set(pids)), v["id"]


@pytest.mark.parametrize("view", VIEWS, ids=[v["id"] for v in VIEWS])
def test_panels_and_inputs_point_at_real_cells(models, view):
    model = models[view["book"]]
    assert view["sheet"] in model.sheet_index
    sheet = model.sheet(view["sheet"])
    assert view["title"] and view["group"]
    for p in view["panels"]:
        assert p["type"] in ("table", "notes", "chart")
        if p["type"] == "chart":
            if "spec" in p:
                for s in p["spec"]["series"]:
                    for ref in (s["val"], s.get("cat"), s.get("name_ref")):
                        if ref:
                            model.range_ref(ref.replace("$", ""))
            else:
                assert 0 <= p["chart"] < len(sheet.charts), (view["id"], p)
            continue
        r1, c1, r2, c2 = parse_range(p["range"])
        assert 1 <= r1 <= sheet.max_row and 1 <= c1 <= sheet.max_col, (view["id"], p["id"], p["range"])
        assert p.get("title"), (view["id"], p["id"])
    for inp in view["inputs"]:
        assert inp.get("scope", "user") in ("user", "shared")
        ref = inp["range"]
        if "!" in ref:
            model.range_ref(ref)
        else:
            parse_range(ref)


def test_ret_curve_is_a_shared_desk_input():
    fwd = next(v for v in VIEWS if v["id"] == "forward")
    ret = [i for i in fwd["inputs"] if i.get("group") == "ret"]
    assert sorted(i["range"] for i in ret) == ["W33:W47", "X33:X47"]
    assert all(i["scope"] == "shared" and i["kind"] == "pct" for i in ret)
    assert any(i["range"] == "D2" and i.get("scope", "user") == "user" for i in fwd["inputs"])


def test_workbook_charts_are_all_shown(models):
    for v in VIEWS:
        sheet = models[v["book"]].sheet(v["sheet"])
        shown = {p["chart"] for p in v["panels"] if p["type"] == "chart" and "chart" in p}
        assert shown == set(range(len(sheet.charts))), v["id"]
