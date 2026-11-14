"""DV01: the risk sheet opens without a position; the VİOP matrix shows each DV01 in its own currency."""
from __future__ import annotations

import pytest

from conftest import cell
from tto import extras as ex
from tto.xl.model import COLS, a1, parse_range


def test_the_dv01_risk_sheet_opens_without_a_position(service):
    """The file keeps the desk's positions of the day it was saved: the sheet opens at zero instead, and what a
    user types or pastes is theirs."""
    for rng in ex.DV01_POSITIONS:                          # the bucket DV01s and the Onshore / TLREF paste area
        r1, c1, r2, c2 = parse_range(rng)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                assert cell(service, "DV01_RISK!%s" % a1(r * COLS + c)) == 0.0, (rng, r, c)
    u = service.login("DV01 Pozisyon")["user"]
    try:
        service.set_inputs(u, "tto", [{"ref": "DV01_RISK!C11", "value": "176474"}])
        assert cell(service, "DV01_RISK!C11", u) == 176474.0 and cell(service, "DV01_RISK!C11") == 0.0
    finally:
        service.reset_inputs(u, "tto")
    assert cell(service, "DV01_RISK!C11", u) == 0.0


def test_the_viop_matrix_shows_each_dv01_in_its_own_currency(service):
    """Per 1 mn USD: the TRY rate's bp in TL and in USD (at the contract's price, the forward of its maturity),
    the USD rate's bp in USD - the workbook showed it in TL."""
    assert [cell(service, "VIOP!K%d" % r) for r in (107, 108, 109)] == ["DV01 TRY (TL)", "DV01 TRY (USD)", "DV01 USD (USD)"]
    for col in ex.VIOP_DV01_COLS:
        days, bid, ask, usd = (cell(service, "VIOP!%s%d" % (col, r)) for r in (98, 99, 100, 101))
        mid = (bid + ask) / 2
        try_tl, try_usd, usd_usd = (cell(service, "VIOP!%s%d" % (col, r)) for r in (107, 108, 109))
        assert try_tl > 0 > usd_usd and try_usd == pytest.approx(try_tl / mid), col
        assert usd_usd == pytest.approx(-100 * (days / 360) / (1 + usd * days / 360)), col
        # the USD bp as the workbook had it (in TL, at the contract's price) is the same figure at that price
        assert usd_usd * mid == pytest.approx(-100 * mid * (days / 360) / (1 + usd * days / 360)), col
    panel = next(p for p in service.view(None, "viop", True)["panels"] if p["id"] == "B14")
    assert panel["range"] == "K97:X109" and panel["data"]["r"][-1] == 109
