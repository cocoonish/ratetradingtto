"""Konsensüs (``tto/quantcons.py``): three families' live lines agreeing on an instrument make one line at the top of the
Sinyaller list - the families named best record first, the best out-of-sample family's levels (said in the line), the
median of their sizes, each family's hit rate -; two make none, a "düşük güven" line is not counted, a family the other
way makes none, lines on different instruments never meet (a spot is not a forward, an outright not a spread).  In the
service: the group "Konsensüs" before the others, a family's filter keeps the consensus it is in, the box lists it, its
card is the best family's line with the consensus told, no log or alarm of its own.  (The HTTP part last.)"""
from __future__ import annotations

import copy

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from tto import quant  # noqa: F401 - the families on the universe among quantfam's (their labels)
from tto import quantcons as qcons
from tto import quantfam as qf
from tto import quantuniv as qu
from tto.server import create_app


class Inst(object):
    """The universe's instrument as the consensus asks it: its size in the desk's words."""

    def __init__(self, unit):
        self.unit = unit

    def size_text(self, k):
        return "%s %s" % (qf._g(k, 1), self.unit)


class Reg(object):
    def __init__(self, **items):
        self.items = items

    def get(self, key, default=None):
        return self.items.get(key, default)


REG = Reg(**{"FX:USDJPY": Inst("mn USD"), "OIS:2Y": Inst("bin $ DV01")})


def fx(fam, side=1, k=1.0, hit=0.55, n=40, exp=0.10, oos=True, gated="", inst="USDJPY spot", key="FX:USDJPY", target=152.0, stop=148.5,
       ok=True):
    """A live FX line as make_signal writes it (what the consensus reads of it)."""
    return {"id": "%s:%s" % (fam, key), "family": fam, "family_label": qf.FAMILIES[fam][0], "asset": "FX", "instrument": inst,
            "legs": [{"key": key, "name": inst, "side": side, "action": "Buy" if side > 0 else "Sell", "weight": 1.0, "dv01": None,
                      "dv01_usd": None, "notional": None, "text": inst}],
            "direction": side, "z": 2.2 * side, "gated": gated, "strength": "elendi" if gated else "Güçlü", "composite": 0.0 if gated else 2.2,
            "levels": {"ok": ok, "rule": "fixed", "k": 1.0, "m": 1.5, "rr": 1.5, "hit": hit, "n": n, "exp": exp, "oos": oos} if ok else {"ok": False, "why": "yok"},
            "info": {"universe": key, "k": k, "size": "%s mn USD" % qf._g(k, 1), "verbs": ["AL", "SAT"], "model": qf.FAMILIES[fam][0]},
            "px": {"entry": 150.25, "target": target, "stop": stop, "digits": 3, "inst": inst, "label": inst},
            "money": {"ccy": "USD", "base": "USD", "total": 3400.0, "target": 9000.0, "stop": -6000.0}, "exp_try": 3400.0 * 42.0 * k,
            "entry": 0.0, "target": 1.0, "stop": -1.0, "unit": "", "digits": 3, "trade_tr": "USDJPY spot %s" % ("al" if side > 0 else "sat"),
            "line": "%s line" % fam, "expression": "%s line" % fam, "plain": "Ailenin cümlesi.", "live": False, "time": "10:00", "rr": 1.5}


def ois(fam, side=1, k=1.0, hit=0.55, exp=0.1, inst="2Y OIS", legs=(("OIS:2Y", 1.0),), asset="TRY OIS"):
    """A live rates line: its legs DV01-sized at k × 1.000 $, its money in TL a bp of the main leg."""
    sg = {"id": "%s:%s" % (fam, inst), "family": fam, "family_label": qf.FAMILIES[fam][0], "asset": asset, "instrument": inst,
          "legs": [{"key": key, "name": key, "side": side * (1 if w > 0 else -1), "weight": abs(w), "dv01": 42000.0 * k * abs(w),
                    "dv01_usd": 1000.0 * k * abs(w), "notional": 30.0 * k * abs(w)} for key, w in legs],
          "direction": side, "z": 2.0 * side, "gated": "", "levels": {"ok": True, "rule": "fixed", "k": 1.0, "m": 1.5, "rr": 1.5, "hit": hit, "n": 50,
                                                                         "exp": exp, "oos": True, "money": 8820.0 * k},
          "info": {"universe": legs[0][0] if len(legs) == 1 else inst, "k": k, "size": "%s $ DV01" % qf._th(1000 * k, 0), "verbs": ["pay", "receive"]},
          "px": None, "money": {"ccy": "TL", "per_bp": 42000.0 * k, "total": 8820.0 * k, "target": 63000.0 * k, "stop": -42000.0 * k,
                                "bp": {"total": 0.21, "target": 1.5, "stop": -1.0}},
          "pnl_try": 8820.0 * k, "exp_try": 8820.0 * k, "entry": 38.5, "target": 38.2, "stop": 38.7, "unit": "%", "digits": 2,
          "trade_tr": "pay 2Y OIS", "line": "%s line" % fam, "expression": "%s line" % fam, "plain": "", "live": False, "time": "10:00"}
    return sg


# ================================================================================================ the rule
def test_three_families_agreeing_make_one_line_with_the_best_record_s_levels_and_the_median_size():
    live = [fx("trend", k=1.2, hit=0.55, exp=0.10, target=152.10, stop=148.20), fx("optspot", k=1.0, hit=0.57, exp=0.15, target=152.40, stop=148.40),
            fx("ml", k=1.5, hit=0.58, exp=0.21, target=152.63, stop=148.35)]
    out = qcons.lines(live, REG)
    assert len(out) == 1
    c = out[0]
    assert c["line"] == ("AL USDJPY spot · 3 aile (Makine öğrenmesi, Opsiyon → spot, Trend) · birleşik 1,2 mn USD · hedef 152,630 · "
                         "stop 148,350 (seviyeler: Makine öğrenmesi, en iyi örneklem dışı kayıt) · aile isabetleri %58 / %57 / %55")
    assert c["expression"] == c["line"] and c["id"] == "konsensus:FX:USDJPY" and c["family"] == "konsensus" and c["family_label"] == "Konsensüs"
    assert c["group"] == qcons.GROUP == "Konsensüs" and c["priority"] == 0 and c["gated"] == "" and c["families"] == ["ml", "optspot", "trend"]
    cs = c["consensus"]
    assert cs["n"] == 3 and cs["ref"] == "ml:FX:USDJPY" and cs["best"] == "ml" and cs["k"] == pytest.approx(1.2) and cs["side"] == 1
    assert [f["hit"] for f in cs["families"]] == [0.58, 0.57, 0.55] and c["info"]["model"] == "Konsensüs · 3 aile" and c["info"]["k"] == 1.2
    # the best line's levels and record, its expectancy at the combined size (an FX card's money stays per 1 mn of the base)
    assert c["px"]["target"] == 152.63 and c["levels"]["hit"] == 0.58 and c["money"]["total"] == 3400.0
    assert c["exp_try"] == pytest.approx(3400.0 * 42.0 * 1.2) and c["agree"] == 3 and c["plain"].startswith("Konsensüs: 3 aile aynı yönde")
    # the lines themselves are not changed
    assert live[2]["px"]["target"] == 152.63 and live[2]["info"]["k"] == 1.5 and live[2]["id"] == "ml:FX:USDJPY"


def test_two_families_make_none_and_a_gated_line_is_not_counted():
    assert qcons.lines([fx("trend"), fx("ml")], REG) == []
    assert qcons.lines([fx("trend"), fx("ml"), fx("optspot", gated="bu kurulum bu seviyelerle geçmişte zarar ettirdi")], REG) == []
    four = qcons.lines([fx("trend"), fx("ml"), fx("optspot", gated="beklenen kâr yok"), fx("sira")], REG)
    assert len(four) == 1 and four[0]["families"] == ["ml", "sira", "trend"] and four[0]["consensus"]["n"] == 3


def test_opposite_directions_make_none():
    assert qcons.lines([fx("trend"), fx("ml"), fx("optspot"), fx("sira", side=-1)], REG) == []         # (one family the other way)
    assert qcons.lines([fx("trend"), fx("ml"), fx("optspot", side=-1), fx("sira", side=-1)], REG) == []
    # a family with lines both ways is no vote for either
    both = [fx("trend"), fx("ml"), fx("optspot"), dict(fx("optspot", side=-1), id="optspot:other")]
    assert qcons.lines(both, REG) == []
    # three SAT: one line, its verb the down side's
    sat = qcons.lines([fx("trend", side=-1), fx("ml", side=-1), fx("optspot", side=-1)], REG)
    assert len(sat) == 1 and sat[0]["line"].startswith("SAT USDJPY spot · 3 aile") and sat[0]["consensus"]["side"] == -1


def test_lines_meet_only_on_the_same_instrument():
    # the same pair's spot and forward (one leg key, two instruments): no consensus across them
    mixed = [fx("trend"), fx("ml"), fx("optspot", inst="USDJPY 1A forward")]
    assert qcons.lines(mixed, REG) == []
    # an outright and a spread sharing its leg; the same name in another asset
    rates = [ois("trend"), ois("ml"), ois("sira", inst="1Y/2Y spread", legs=(("OIS:2Y", 1.0), ("OIS:1Y", -1.0)))]
    assert qcons.lines(rates, REG) == []
    assert qcons.lines([ois("trend"), ois("ml"), ois("sira", asset="Offshore")], REG) == []


def test_a_rates_consensus_is_sized_at_the_median_its_money_and_legs_with_it():
    live = [ois("trend", k=0.7, exp=0.05), ois("ml", k=1.0, exp=0.30), ois("sira", k=1.4, exp=0.12)]
    out = qcons.lines(live, REG)
    assert len(out) == 1
    c = out[0]
    assert c["families"] == ["ml", "sira", "trend"] and c["consensus"]["k"] == 1.0 and "birleşik 1,0 bin $ DV01" in c["line"]
    assert c["line"].startswith("pay 2Y OIS · 3 aile (Makine öğrenmesi, Carry + momentum, Trend)") and "hedef %38,200" in c["line"]
    # (the best is ml at 1,0: nothing to scale) - a best of another size is scaled to the median
    live2 = [ois("trend", k=0.7, exp=0.05), ois("ml", k=2.0, exp=0.30), ois("sira", k=1.4, exp=0.12)]
    c2 = qcons.lines(live2, REG)[0]
    r = 1.4 / 2.0
    assert c2["consensus"]["k"] == 1.4 and c2["legs"][0]["dv01"] == pytest.approx(42000.0 * 2.0 * r) and c2["legs"][0]["notional"] == pytest.approx(30.0 * 2.0 * r)
    assert c2["money"]["per_bp"] == pytest.approx(42000.0 * 1.4) and c2["money"]["total"] == pytest.approx(8820.0 * 1.4)
    assert c2["exp_try"] == pytest.approx(8820.0 * 1.4) and c2["levels"]["money"] == pytest.approx(8820.0 * 1.4) and c2["money"]["bp"]["total"] == 0.21
    assert live2[1]["money"]["per_bp"] == 84000.0                                          # (its own line as it was)


def test_a_model_level_consensus_says_its_instruments_levels_the_gap_beside_them():
    """Lines whose level is a model's own (a gap to the PPK path) agreeing on their instrument: the consensus line says the
    best family's levels in the traded instrument's (the FRA's rate), the gap beside each (quantfam.inst_quote)."""
    quote = {"inst": "6x9 FRA", "unit": "%", "digits": qf.RATE_DIGITS, "label": "6x9 FRA %", "base": 38.65, "scale": 0.01, "entry": 38.719,
             "target": 38.651, "stop": 38.729, "gap": {"name": "patika farkı", "of": "patikanın", "at": "patikada", "unit": "bp", "digits": 1}}

    def fra(fam, exp):
        return dict(ois(fam, side=-1, exp=exp, inst="6x9 FRA (PPK patikasına göre)", legs=(("OIS:9M", 3.27), ("OIS:6M", -2.27))),
                    unit="bp", digits=1, entry=6.9, target=0.1, stop=7.9, quote=quote)

    out = qcons.lines([fra("trend", 0.05), fra("ml", 0.30), fra("sira", 0.12)], REG)
    assert len(out) == 1
    assert "hedef %38,651 (+0,1 bp patikanın üstünde) · stop %38,729 (+7,9 bp patikanın üstünde)" in out[0]["line"]
    assert out[0]["quote"]["entry"] == 38.719                        # (the best line's quote: its levels are the line's)


def test_most_families_first_and_the_group_s_button():
    three = [fx("trend"), fx("ml"), fx("optspot")]
    four = [ois("trend"), ois("ml"), ois("sira"), ois("optspot")]
    out = qcons.lines(three + four, REG)
    assert [c["consensus"]["n"] for c in out] == [4, 3]
    g = qcons.group_count(out + three)
    assert g == {"id": "Konsensüs", "label": "Konsensüs", "slug": "konsensus", "n": 2, "live": 2, "tag": ""}
    # a line already a consensus is never counted again; a line without legs is no instrument
    assert qcons.lines(out + [dict(fx("sira"), legs=[])], REG) == []


# ================================================================================================ the service
@pytest.fixture(scope="module")
def seeded(module_service):
    svc = module_service
    svc.quant.use_live = False
    quant_synth.seed(svc)
    return svc


def test_the_consensus_group_heads_the_list_a_view_of_the_families_lines(seeded, monkeypatch):
    """Two more families' copies of a live universe line (given to the consensus only): one consensus line at the top of
    the list and of its group, in a family's filter it is in, in the box; its card the best family's; no log, no alarm."""
    svc = seeded
    q = svc.quant
    real = qcons.lines
    made = {}

    def lines(live, reg=None):
        # (a universe line no other live line shares its instrument with; two families that have no line on it)
        # (the copies' record a little worse: the line's own family is the best, its line the card)
        keys = [qcons.ident(s)[0] for s in live]
        alone = [s for s, k in zip(live, keys) if (s.get("info") or {}).get("universe") and k is not None and keys.count(k) == 1]
        base = next((s for s in alone if (s.get("levels") or {}).get("ok")), alone[0] if alone else None)
        extra = []
        if base is not None:
            for f in ("kalman", "cycle"):
                c = copy.deepcopy(base)
                lv = c.get("levels") or {}
                c.update({"id": "%s:%s" % (f, base["info"]["universe"]), "family": f, "family_label": qf.FAMILIES[f][0],
                          "levels": dict(lv, exp=(lv.get("exp") or 0.0) - 1.0) if lv.get("ok") else {"ok": False, "why": "kopya"}})
                extra.append(c)
            made["base"] = base
        return real(list(live) + extra, reg)

    monkeypatch.setattr(qcons, "lines", lines)
    q.compute()
    user = svc.login("konsensüs okuyucu")["user"]
    view = q.view("signals", user, {})
    base = made["base"]
    first = view["signals"][0]
    assert first["group"] == "Konsensüs" and first["id"] == "konsensus:" + base["info"]["universe"] and first["consensus"]["n"] == 3
    assert sorted(first["families"]) == sorted([base["family"], "kalman", "cycle"]) and first["consensus"]["ref"] == base["id"]
    assert view["groups"][0] == {"id": "Konsensüs", "label": "Konsensüs", "slug": "konsensus", "n": 1, "live": 1, "tag": ""}
    assert [g["id"] for g in view["groups"]][1:] == list(qu.GROUPS)
    assert all(s["group"] != "Konsensüs" for s in view["signals"][1:])
    only = q.view("signals", user, {"group": "Konsensüs"})["signals"]
    assert [s["id"] for s in only] == [first["id"]]
    fam = q.view("signals", user, {"family": base["family"]})["signals"]
    assert fam[0]["id"] == first["id"] and all(s["family"] == base["family"] for s in fam[1:])
    assert not any(s["group"] == "Konsensüs" for s in q.view("signals", user, {"family": "corr"})["signals"])
    box = q.box_view({"of": "signals"})
    assert box["signals"][0]["id"] == first["id"] and box["groups"][0] == "Konsensüs"
    # its card: the line whose levels it tells, the consensus as its signal
    card = q.signal_view(first["id"])
    assert card["signal"]["id"] == first["id"] and card["monitor"]["sid"] == first["consensus"]["ref"]
    # a view of the lines: not in the live lines the log and the alarms follow
    assert first["id"] not in {s["id"] for s in q._view["signals"]} and not any(e["sid"] == first["id"] for e in q._log())
    with TestClient(create_app(svc), headers=auth(svc, "Konsensüs HTTP")) as client:
        body = client.get("/api/quant/signals").json()
        assert body["signals"][0]["id"] == first["id"] and body["groups"][0]["slug"] == "konsensus"
        r = client.get("/api/quant/signal", params={"id": first["id"]})
        assert r.status_code == 200 and r.json()["signal"]["line"] == first["line"]
        assert client.get("/api/quant/signal", params={"id": "konsensus:yok"}).status_code == 400
