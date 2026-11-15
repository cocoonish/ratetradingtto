"""Broker chat: every way a broker writes a TRY rates quote is read, kept with its time, and shown as a board."""
from __future__ import annotations

import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import auth
from tto import blotter as bl
from tto import brokerchat as bc
from tto.server import create_app
from tto.service import ServiceError

TODAY = dt.date(2026, 11, 13)

# where the instruments stand in the tests that complete a shortened level
LEVELS = {"OIS:outright:18M": 35.10, "OIS:outright:1Y": 35.10, "OIS:outright:2Y": 35.40, "OIS:outright:6M": 35.88,
          "OIS:outright:3M": 36.60}


def ref(q):
    return LEVELS.get(q["key"])


def one(text, where=ref):
    quotes = bc.parse_message(text, where)
    assert len(quotes) == 1, (text, quotes)
    return quotes[0]


def sides(text, where=ref):
    q = one(text, where)
    return q["bid"], q["ask"]


# what the desk sent as the way brokers quote (the message that asked for this page)
DESK_SAMPLE = """10:23:58 3y5y ois /-75 offer
10:29:57 1y5y ois -64/-60

12:10:07 18m ois /35.23 offer
12:11:25 3m ois /36.65 offer
12:11:55 9x12m ois fra 33.80/34.10
12:15:29 1y ois 35.00/35.20
12:15:38 18m ois 35.03/35.23
12:18:04 2y3y4y ois 12/ bid
12:19:25 4y6y8y ois -2/3
12:26:52 2y3y ois /-20 offer
12:30:45 5y7y10y ois 23/28
12:31:42 1y ois 35.00/35.20
12:31:48 18m ois 35.03/35.23

6m OIS 90 bid
"""


def test_the_desks_sample_is_read_line_by_line():
    rows = bc.parse_chat(DESK_SAMPLE, ref, TODAY)
    assert all(q["ok"] and q["event"] == "quote" and q["product"] == "OIS" for q in rows)
    got = [(q["time"], q["kind"], q["label"], q["unit"], q["bid"], q["ask"], q["clear"]) for q in rows]
    assert got == [
        ("10:23:58", "spread", "3Y–5Y", "bp", None, -75.0, ["bid"]),            # "/-75": nothing bid
        ("10:29:57", "spread", "1Y–5Y", "bp", -64.0, -60.0, []),               # two tenors without a "v": a spread, not a FRA
        ("12:10:07", "outright", "18M", "pct", None, 35.23, ["bid"]),
        ("12:11:25", "outright", "3M", "pct", None, 36.65, ["bid"]),
        ("12:11:55", "fra", "9x12", "pct", 33.80, 34.10, []),
        ("12:15:29", "outright", "1Y", "pct", 35.00, 35.20, []),
        ("12:15:38", "outright", "18M", "pct", 35.03, 35.23, []),
        ("12:18:04", "fly", "2Y–3Y–4Y", "bp", 12.0, None, ["ask"]),            # "12/": bid only
        ("12:19:25", "fly", "4Y–6Y–8Y", "bp", -2.0, 3.0, []),
        ("12:26:52", "spread", "2Y–3Y", "bp", None, -20.0, ["bid"]),
        ("12:30:45", "fly", "5Y–7Y–10Y", "bp", 23.0, 28.0, []),
        ("12:31:42", "outright", "1Y", "pct", 35.00, 35.20, []),
        ("12:31:48", "outright", "18M", "pct", 35.03, 35.23, []),
        (None, "outright", "6M", "pct", 35.90, None, []),                       # no time in the message; "90" is 35.90
    ]
    assert rows[-1]["flags"] == ["abbr"] and rows[-1]["raw"] == "6m OIS 90 bid" and rows[0]["raw"] == "3y5y ois /-75 offer"
    assert [q["months"] for q in rows[:2]] == [[36.0, 60.0], [12.0, 60.0]] and rows[4]["months"] == [9.0, 12.0]
    assert rows[0]["key"] == "OIS:spread:3Y/5Y" and rows[4]["key"] == "OIS:fra:9M/1Y" and rows[8]["key"] == "OIS:fly:4Y/6Y/8Y"
    assert all(q["sender"] == "" and q["date"] is None for q in rows)


# the two screenshots of the chat on the phone: a name, the message, its time below it
PHONE = """13 Nov 2026
EVREN DIKME
1v2 x 190 offer
care offer 6m1y OIS
13:01:10
MIKE REES
18m ois  35.14 offer
13:30:20
18m ois 10/14
13:33:59
MIKE REES
18m ois taken  at 14
13:41:09
18m ois sell a bal at 14
13:44:56
MIKE REES
2yr ois  35.46 , oco with 18m 35.14 offer
13:51:22
2yr ois 45 offer oco with 18m 14 offer
13:55:21
ref 18m ois offer
13:55:37
2yr  ois 45 offer
13:55:51
MIKE REES
2y ois 44 offer
14:46:00
EVREN DIKME
6m OIS 35.88 bid
15:04:20
MIKE REES
1v5y x 55 offer
16:12:03
MIKE REES
2yr x 40.75 offer
16:30:48
EVREN DIKME
6m OIS 35.88 bid
16:40:10
EVREN DIKME
18m OIS 15 offer
16:46:59
6m OIS 90 bid
16:48:21
MIKE REES
1yr x 38.60/80 , bid nl
17:00:01
"""


def test_the_chat_on_the_phone():
    rows = bc.parse_chat(PHONE, None, TODAY)
    assert all(q["date"] == "2026-11-13" and q["ok"] for q in rows)
    seen = [(q["time"], q["sender"], q["product"], q["label"], q["event"], q["bid"], q["ask"], q["price"], q["side"]) for q in rows]
    assert seen == [
        ("13:01:10", "EVREN DIKME", "XCCY", "1Y–2Y", "quote", None, 190.0, None, "ask"),        # "x": cross-currency; "1v2": a spread
        ("13:01:10", "EVREN DIKME", "OIS", "6M–1Y", "interest", None, None, None, "ask"),       # both lines of one bubble have its time
        ("13:30:20", "MIKE REES", "OIS", "18M", "quote", None, 35.14, None, "ask"),
        ("13:33:59", "MIKE REES", "OIS", "18M", "quote", 35.10, 35.14, None, None),             # "10/14" after 35.14
        ("13:41:09", "MIKE REES", "OIS", "18M", "trade", None, None, 35.14, "ask"),             # taken: the offer was lifted
        ("13:44:56", "MIKE REES", "OIS", "18M", "quote", None, 35.14, None, "ask"),             # "sell a bal at 14"
        ("13:51:22", "MIKE REES", "OIS", "2Y", "quote", None, 35.46, None, "ask"),              # the side is said once, after "oco"
        ("13:51:22", "MIKE REES", "OIS", "18M", "quote", None, 35.14, None, "ask"),
        ("13:55:21", "MIKE REES", "OIS", "2Y", "quote", None, 35.45, None, "ask"),
        ("13:55:21", "MIKE REES", "OIS", "18M", "quote", None, 35.14, None, "ask"),
        ("13:55:37", "MIKE REES", "OIS", "18M", "ref", None, None, None, "ask"),
        ("13:55:51", "MIKE REES", "OIS", "2Y", "quote", None, 35.45, None, "ask"),
        ("14:46:00", "MIKE REES", "OIS", "2Y", "quote", None, 35.44, None, "ask"),
        ("15:04:20", "EVREN DIKME", "OIS", "6M", "quote", 35.88, None, None, "bid"),
        ("16:12:03", "MIKE REES", "XCCY", "1Y–5Y", "quote", None, 55.0, None, "ask"),
        ("16:30:48", "MIKE REES", "XCCY", "2Y", "quote", None, 40.75, None, "ask"),
        ("16:40:10", "EVREN DIKME", "OIS", "6M", "quote", 35.88, None, None, "bid"),
        ("16:46:59", "EVREN DIKME", "OIS", "18M", "quote", None, 35.15, None, "ask"),
        ("16:48:21", "EVREN DIKME", "OIS", "6M", "quote", 35.90, None, None, "bid"),
        ("17:00:01", "MIKE REES", "XCCY", "1Y", "quote", 38.60, 38.80, None, None),
    ]
    by_time = {(q["time"], q["label"]): q for q in rows}
    assert by_time[("13:44:56", "18M")]["note"] == "bal" and by_time[("17:00:01", "1Y")]["note"] == "bid nl"
    assert by_time[("13:51:22", "2Y")]["oco"] == by_time[("13:51:22", "18M")]["oco"] == 1          # one cancels the other
    assert by_time[("13:55:21", "2Y")]["oco"] == by_time[("13:55:21", "18M")]["oco"] == 2
    assert "oco" not in by_time[("13:55:51", "2Y")]
    assert by_time[("13:51:22", "18M")]["raw"] == "2yr ois  35.46 , oco with 18m 35.14 offer"
    assert by_time[("16:12:03", "1Y–5Y")]["unit"] == "bp" and by_time[("16:30:48", "2Y")]["unit"] == "pct"
    # where everything stands at the end of the day
    board = {r["key"]: r for r in bc.board(rows)}
    r18 = board["OIS:outright:18M"]
    assert (r18["bid"], r18["bid_time"]) == (35.10, "2026-11-13 13:33:59")
    assert (r18["ask"], r18["ask_time"]) == (35.15, "2026-11-13 16:46:59")
    assert (r18["last"], r18["last_side"], r18["last_time"]) == (35.14, "ask", "2026-11-13 13:41:09")
    assert board["OIS:outright:6M"]["bid"] == 35.90 and board["OIS:outright:6M"]["ask"] is None
    assert board["OIS:outright:2Y"]["ask"] == 35.44 and board["XCCY:outright:1Y"]["ask"] == 38.80
    assert board["OIS:spread:6M/1Y"]["said"] == "care offer 6m1y OIS" and board["OIS:spread:6M/1Y"]["bid"] is None
    assert [r["label"] for r in bc.board(rows)] == ["6M", "18M", "2Y", "6M–1Y", "1Y", "2Y", "1Y–2Y", "1Y–5Y"]     # OIS first, by kind and tenor
    assert [r["product"] for r in bc.board(rows)] == ["OIS"] * 4 + ["XCCY"] * 4


@pytest.mark.parametrize("text, kind, label", [
    ("3y5y ois -75/-70", "spread", "3Y–5Y"),                  # no "v": still a spread
    ("1v5y ois -64/-60", "spread", "1Y–5Y"),
    ("1v5 ois -64/-60", "spread", "1Y–5Y"),
    ("1y v 5y -64/-60", "spread", "1Y–5Y"),
    ("1y vs 5y -64/-60", "spread", "1Y–5Y"),
    ("1y - 5y ois -64/-60", "spread", "1Y–5Y"),
    ("1y/5y -64/-60", "spread", "1Y–5Y"),
    ("1s5s -64/-60", "spread", "1Y–5Y"),
    ("6m1y ois -80/-75", "spread", "6M–1Y"),
    ("18m2y 5/8", "spread", "18M–2Y"),
    ("2y3y spread -20/-18", "spread", "2Y–3Y"),
    ("2y3y4y ois 12/14", "fly", "2Y–3Y–4Y"),
    ("2y/3y/4y fly 12/14", "fly", "2Y–3Y–4Y"),
    ("2s3s4s 12/14", "fly", "2Y–3Y–4Y"),
    ("2v3v4 12/14", "fly", "2Y–3Y–4Y"),
    ("9x12 33.80/34.10", "fra", "9x12"),                      # "AxB" is a FRA ...
    ("9x12m ois fra 33.80/34.10", "fra", "9x12"),
    ("9 x 12 fra 33.80/34.10", "fra", "9x12"),
    ("3x6 36.10/36.30", "fra", "3x6"),
    ("9m12m fra 33.80/34.10", "fra", "9x12"),                 # ... and so is anything called one
    ("1y1y 34.50/34.80", "fwd", "1Y1Y"),                      # the same tenor twice cannot be a spread
    ("5y vs 2y -10/-5", "spread", "2Y–5Y"),                   # one against another: a spread, whichever comes first
    ("2y vs. 5y -10/-5", "spread", "2Y–5Y"),
    ("2y ois versus 5y ois -10/-5", "spread", "2Y–5Y"),
    ("6x9m vs 9x12m -65/-35", "spread", "6x9–9x12"),          # two FRAs: the later one − the earlier
    ("9x12m vs 6x9m -65/-35", "spread", "6x9–9x12"),
    ("6x9 v 9x12 -60/-40", "spread", "6x9–9x12"),
    ("6x9 fra vs 9x12 fra -60/-40", "spread", "6x9–9x12"),
    ("1y1y vs 2y1y 10/12", "spread", "1Y1Y–2Y1Y"),
    ("18m ois 35.03/35.23", "outright", "18M"),
    ("1.5y ois 35.03/35.23", "outright", "18M"),
    ("24m ois 35.26/35.46", "outright", "2Y"),
    ("2yr ois 35.26/35.46", "outright", "2Y"),
    ("2yrs 35.26/35.46", "outright", "2Y"),
    ("1w ois 37.00/37.50", "outright", "1W"),
])
def test_what_kind_of_instrument(text, kind, label):
    q = one(text)
    assert (q["kind"], q["label"]) == (kind, label)
    assert q["unit"] == ("bp" if kind in ("spread", "fly") else "pct")
    assert q["bid"] is not None and q["ask"] is not None and q["event"] == "quote"


@pytest.mark.parametrize("text", [
    "18m ois 35.03/35.23", "18m ois 35.03 / 35.23", "18m 35.03-35.23", "18m ois 35,03/35,23", "18m ois 3503/3523", "18m 03/23",
    "18m ois 35.03/23", "18m ois 35.03 bid 35.23 offer", "18m ois bid 35.03 offer 35.23", "18m ois 35.03 bid, 35.23 offer",
    "18m ois 35.03 bid / 35.23 offer", "18m ois offer 35.23 / bid 35.03", "tlref 18m 35.03/35.23", "TRY OIS 18M 35.03/35.23",
    "18m ois 35.03/35.23 100x100", "18m ois 35.03/35.23 in 50m", "100m 18m ois 35.03/35.23", "18m ois pays 35.03 offered 35.23",
    "18m ois 35.03%/35.23%", "18m ois 35.03 % / 35.23 %", "50x50 18m ois 35.03/35.23", "25x25 18m 35.03/35.23",
])
def test_two_sides_however_they_are_written(text):
    assert sides(text) == (35.03, 35.23)


@pytest.mark.parametrize("text, bid, ask", [
    ("18m ois 35.03 bid", 35.03, None), ("18m ois bid 35.03", 35.03, None), ("18m ois bid at 35.03", 35.03, None),
    ("18m ois @ 35.03 bid", 35.03, None), ("pay 18m ois at 35.03", 35.03, None), ("18m ois 35.03/ bid", 35.03, None),
    ("18m ois 35.03/", 35.03, None), ("18m ois 03 bid", 35.03, None), ("18m ois .03 bid", 35.03, None),
    ("18m ois 35.23 offer", None, 35.23), ("18m ois /35.23 offer", None, 35.23), ("18m ois /35.23", None, 35.23),
    ("18m ois offered 35.23", None, 35.23), ("rec 18m at 35.23", None, 35.23), ("18m ois 23 offer", None, 35.23),
    ("18m ois 35.23 ofr", None, 35.23), ("18m ois seller at 23", None, 35.23), ("18m ois satıcı 35.23", None, 35.23),
])
def test_one_side(text, bid, ask):
    assert sides(text) == (bid, ask)
    assert one(text)["side"] == ("bid" if ask is None else "ask")


def test_a_level_without_its_big_figure():
    complete = bc._complete
    assert complete("90", 35.88) == (35.90, "abbr")                           # the desk's "6m OIS 90 bid"
    assert complete("14", 35.10) == (35.14, "abbr") and complete("03", 35.10) == (35.03, "abbr")
    assert complete("95", 36.02) == (35.95, "abbr") and complete("05", 35.97) == (36.05, "abbr")       # across the figure
    assert complete(".90", 35.88) == (35.90, "abbr") and complete("0.90", 35.88) == (35.90, "abbr")
    assert complete("35.90", 30.0) == (35.90, "") and complete("-64", 35.0) == (-64.0, "") and complete("190", 35.0) == (190.0, "")
    assert complete("3590", None) == (35.90, "")                              # written without the decimal point
    assert complete("90", None) == (90.0, "no-ref")                           # nothing to complete it with: as typed, and said so
    assert complete("36", 35.55)[1] == "ambiguous"                            # 35.36 or 36.00?
    # the other side of the same quote: the ask is not below the bid
    assert complete("80", 35.0, 35.60) == (35.80, "abbr") and complete("05", 35.0, 35.95) == (36.05, "abbr")
    assert sides("1y ois 35.95/05") == (35.95, 36.05) and sides("18m 10/14") == (35.10, 35.14)
    assert sides("1yr x 38.60/80", None) == (38.60, 38.80)                    # no reference needed for the second half
    assert sides("18m ois 35.14 choice") == (35.14, 35.14) and sides("18m ois 14 choice") == (35.14, 35.14)
    assert sides("2y3y ois -20bp/-18bp") == (-20.0, -18.0) and sides("2y3y ois -20 bps offer") == (None, -20.0)
    # spreads and flies are basis points: nothing to complete
    assert sides("2y3y ois -20/-18") == (-20.0, -18.0) and sides("2y3y4y 12/14") == (12.0, 14.0) and one("2y3y 5/8")["flags"] == []
    q = one("2yr x 40 offer", None)
    assert q["ask"] == 40.0 and q["flags"] == ["no-ref"]
    # a level said earlier in the same chat is the reference, before the caller's
    rows = bc.parse_chat("12:00:00 6m ois 36.40/36.60\n12:05:00 6m ois 45 bid", lambda q: 35.88)
    assert rows[1]["bid"] == 36.45 and rows[1]["flags"] == ["abbr"]
    assert bc.parse_chat("6m ois 45 bid", lambda q: 35.88)[0]["bid"] == 35.45


def test_both_sides_short_find_their_big_figure_together():
    pair = bc._complete_pair
    assert pair("90", "10", 35.88) == (35.90, 36.10, "abbr")                  # the desk's "6m 90/10": across the figure
    assert pair("90", "10", 36.02) == (35.90, 36.10, "abbr") and pair("10", "14", 35.14) == (35.10, 35.14, "abbr")
    assert pair("95", "05", 36.0) == (35.95, 36.05, "abbr") and pair("98", "02", 35.99) == (35.98, 36.02, "abbr")
    assert pair(".90", ".10", 36.0) == (35.90, 36.10, "abbr") and pair("50", "50", 36.6) == (36.50, 36.50, "abbr")
    # the reference half a figure away: the nearer figure still, and said to be uncertain
    assert pair("90", "10", 36.44) == (35.90, 36.10, "ambiguous") and pair("90", "10", 36.60)[:2] == (36.90, 37.10)
    assert pair("35", "36", 35.5) == (35.0, 36.0, "ambiguous")                # whole numbers may be meant as typed
    assert bc._is_short("90") and bc._is_short(".5") and bc._is_short("0,90") and not bc._is_short("35.90")
    assert not bc._is_short("3590") and not bc._is_short("-5") and not bc._is_short("190")
    # in a quote, however it is written
    for text in ("6m 90/10", "6m ois 90 / 10", "6m ois 90 bid 10 offer", "6m ois 90 bid, 10 offer", "6m 90/36.10", "6m 35.90/10",
                 "6m ois .90/.10", "6m ois bid 90 offer 10"):
        assert sides(text) == (35.90, 36.10), text
    assert one("6m 90/10")["flags"] == ["abbr"] and one("6m 35.90/10")["flags"] == ["abbr"] and one("6m 90/36.10")["flags"] == ["abbr"]
    assert sides("3m ois 55/75") == (36.55, 36.75) and sides("3m ois 95/15") == (36.95, 37.15) and sides("2y 30/50") == (35.30, 35.50)
    assert sides("3m ois 40/80") == (36.40, 36.80) and sides("3m ois 85/05") == (36.85, 37.05)    # 3M stands at 36.60: the middle nearest to it
    # what the chat said just before is the reference, whatever the caller's
    rows = bc.parse_chat("12:00:00 6m ois 37.95 bid\n12:05:00 6m 90/10", ref)
    assert (rows[1]["bid"], rows[1]["ask"], rows[1]["flags"]) == (37.90, 38.10, ["abbr"])
    # nothing to find the figure with: as typed, and said so
    q = one("1y x 60/80", None)
    assert (q["bid"], q["ask"], q["flags"]) == (60.0, 80.0, ["no-ref"])
    assert one("6m 90/10", None)["flags"] == ["no-ref", "crossed"]
    # basis points are never completed
    assert sides("2y3y 90/10") == (90.0, 10.0) and sides("1v5y x 55/60", None) == (55.0, 60.0)


def test_trades_refs_and_interest():
    q = one("18m ois taken at 14")
    assert (q["event"], q["price"], q["side"], q["bid"], q["ask"]) == ("trade", 35.14, "ask", None, None)
    assert [(one(t)["event"], one(t)["side"], one(t)["price"]) for t in (
        "18m ois lifted at 35.14", "paid 35.14 18m ois", "mine 18m at 14", "18m given at 03", "18m ois hit 35.03",
        "18m ois trades 35.14", "18m ois 35.14 traded", "18m dealt at 14")] == [
        ("trade", "ask", 35.14), ("trade", "ask", 35.14), ("trade", "ask", 35.14), ("trade", "bid", 35.03), ("trade", "bid", 35.03),
        ("trade", None, 35.14), ("trade", None, 35.14), ("trade", None, 35.14)]
    assert [(one(t)["event"], one(t)["side"]) for t in ("ref 18m ois offer", "18m ois ref bid", "18m ois ref", "18m ois off",
                                                         "cxl 18m ois")] == [("ref", "ask"), ("ref", "bid"), ("ref", None), ("ref", None), ("ref", None)]
    assert [(one(t)["event"], one(t)["side"]) for t in ("care offer 6m1y OIS", "18m ois bid", "looking for 2y offer")] == [
        ("interest", "ask"), ("interest", "bid"), ("interest", "ask")]
    q = one("18m ois 35.14")                                                  # a number and no side: a level
    assert (q["event"], q["price"], q["bid"], q["ask"]) == ("level", 35.14, None, None)
    # "taken" without a price: at the offer that stands - in the chat itself, or before it
    rows = bc.parse_chat("12:00:00 18m ois 35.03/35.23\n12:01:00 18m ois taken\n12:02:00 18m ois given\n12:03:00 2y ois mine")
    assert [(q["event"], q["price"], q["flags"]) for q in rows[1:]] == [("trade", 35.23, ["standing"]), ("trade", 35.03, ["standing"]),
                                                                         ("trade", None, [])]
    rows = bc.parse_chat("2y ois mine", None, None, lambda q: {"bid": 35.26, "ask": 35.46})
    assert rows[0]["price"] == 35.46 and rows[0]["flags"] == ["standing"]
    rows = bc.parse_chat("12:00:00 18m ois 35.03/35.23\n12:01:00 ref 18m ois offer\n12:02:00 18m ois taken")
    assert rows[2]["price"] is None                                           # the offer was pulled: nothing to take


def test_several_quotes_in_one_message():
    run = bc.parse_message("1y 35.00/35.20 18m 35.03/35.23 2y 35.26/35.46", ref)
    assert [(q["label"], q["bid"], q["ask"]) for q in run] == [("1Y", 35.00, 35.20), ("18M", 35.03, 35.23), ("2Y", 35.26, 35.46)]
    lst = bc.parse_message("1y ois 35.00/35.20, 18m 35.03/35.23; 2y3y -20/-18", ref)
    assert [(q["label"], q["bid"], q["ask"]) for q in lst] == [("1Y", 35.00, 35.20), ("18M", 35.03, 35.23), ("2Y–3Y", -20.0, -18.0)]
    fras = bc.parse_message("3x6 36.10/36.30 6x9 35.20/35.40", ref)
    assert [(q["kind"], q["label"]) for q in fras] == [("fra", "3x6"), ("fra", "6x9")]
    both = bc.parse_message("18m ois 14 offer 2y 46 offer", ref)
    assert [(q["label"], q["ask"]) for q in both] == [("18M", 35.14), ("2Y", 35.46)]
    # the product is said once
    xs = bc.parse_message("1yr x 38.60/80, 2yr 40.55/75", None)
    assert [(q["product"], q["label"], q["bid"], q["ask"]) for q in xs] == [("XCCY", "1Y", 38.60, 38.80), ("XCCY", "2Y", 40.55, 40.75)]
    oco = bc.parse_message("2yr ois 35.46 , oco with 18m 35.14 offer", ref)
    assert [(q["label"], q["ask"], q["oco"]) for q in oco] == [("2Y", 35.46, True), ("18M", 35.14, True)]
    # a size or a word after a comma is not another instrument
    q = one("18m ois 35.14 offer, 50m")
    assert (q["label"], q["ask"], q["note"]) == ("18M", 35.14, "50m")
    assert one("1yr x 38.60/80 , bid nl", None)["note"] == "bid nl"
    assert one("18m ois 35.03/35.23 in 25m")["note"] == "25m" and one("2y3y4y fly 12/14")["note"] == ""


def test_what_is_not_a_quote_stays_text():
    rows = bc.parse_chat("hello mate, anything in 2y?\nwhat is 18m\n12:00:01 thanks\nTRY OIS\n35.03/35.23\n500m", ref)
    assert [(q["ok"], q["event"], q["raw"]) for q in rows] == [(False, "text", t) for t in (
        "hello mate, anything in 2y?", "what is 18m", "thanks", "TRY OIS", "35.03/35.23", "500m")]
    assert rows[2]["time"] == "12:00:01" and bc.board(rows) == []
    assert bc.parse_quote("thanks") is None and bc.parse_message("35.03/35.23") == []
    assert one("18m ois 35.03/35.23 thanks mate")["note"] == "thanks mate"     # what else was said stays with the quote


def test_what_may_be_wrong_is_flagged():
    assert one("18m ois 35.23/35.03")["flags"] == ["crossed"]
    assert "side?" in one("2y3y4y ois 12/ offer")["flags"] and one("2y3y4y ois 12/ offer")["bid"] == 12.0      # the slash wins
    assert one("18m ois 35.03/35.23")["flags"] == [] and one("2y3y4y ois 12/ bid")["flags"] == []


def test_messages_in_every_layout():
    split = bc.split_messages
    assert split("12:15:38 18m ois 35.03/35.23") == [{"date": None, "time": "12:15:38", "sender": "", "text": "18m ois 35.03/35.23"}]
    assert split("18m ois 35.03/35.23 12:15:38")[0]["time"] == "12:15:38"
    assert split("9:05 1y ois 35/35.2")[0] == {"date": None, "time": "09:05:00", "sender": "", "text": "1y ois 35/35.2"}
    assert split("  • 12:15:38 - 18m ois 35.03/35.23\r\n")[0]["text"] == "18m ois 35.03/35.23"
    assert split("[12:15:38] 18m ois 35.03/35.23")[0] == {"date": None, "time": "12:15:38", "sender": "", "text": "18m ois 35.03/35.23"}
    assert [split(t)[0]["time"] for t in ("1:15:38 PM 18m ois 35.03/35.23", "12:15 am 1y ois 35/35.2", "12:15:38 PM x", "x 9:05 a.m.")] == [
        "13:15:38", "00:15:00", "12:15:38", "09:05:00"]
    assert split("1:15:38 PM 18m ois 35.03/35.23")[0]["text"] == "18m ois 35.03/35.23"
    # who said it
    assert split("MIKE REES 12:15:38 18m ois 35.03/35.23\nMike Rees, Tullett 12:16:00: 2y ois 35.26/35.46") == [
        {"date": None, "time": "12:15:38", "sender": "MIKE REES", "text": "18m ois 35.03/35.23"},
        {"date": None, "time": "12:16:00", "sender": "Mike Rees, Tullett", "text": "2y ois 35.26/35.46"}]
    assert split("18m ois valid till 15:30 only")[0] == {"date": None, "time": None, "sender": "", "text": "18m ois valid till 15:30 only"}
    m = split("12:15:38 MIKE REES: 18m ois 35.03/35.23\n12:16:00 2y ois 35.26/35.46\nEVREN DIKME: 6m ois 35.88 bid")
    assert [(x["time"], x["sender"], x["text"]) for x in m] == [("12:15:38", "MIKE REES", "18m ois 35.03/35.23"),
                                                                 ("12:16:00", "MIKE REES", "2y ois 35.26/35.46"),
                                                                 (None, "EVREN DIKME", "6m ois 35.88 bid")]
    m = split("11/13/2026 12:15:38 MIKE REES (TULLETT PREBON) says: 18m ois 35.03/35.23")
    assert m == [{"date": "2026-11-13", "time": "12:15:38", "sender": "MIKE REES (TULLETT PREBON)", "text": "18m ois 35.03/35.23"}]
    assert split("1y ois: 35.00/35.20")[0]["sender"] == "" and split("OIS: 18m 35.03/35.23")[0]["sender"] == ""      # a label is no name
    assert split("Try Ois: 18m 35.03/35.23")[0] == {"date": None, "time": None, "sender": "", "text": "Try Ois: 18m 35.03/35.23"}
    # the day
    days = split("13 Nov 2026\n12:00:00 a\n14.11.2026\n12:00:00 b\n2026-11-16\n12:00:00 c\n17 Kasım 2026\n12:00:00 d")
    assert [(x["date"], x["text"]) for x in days] == [("2026-11-13", "a"), ("2026-11-14", "b"), ("2026-11-16", "c"), ("2026-11-17", "d")]
    assert split("11/13/2026\n12:00:00 a")[0]["date"] == "2026-11-13"
    assert split("03/11/2026\n12:00:00 a", dt.date(2026, 11, 13))[0]["date"] == "2026-11-03"        # day first where both are possible
    assert split("12/11/2026\n12:00:00 a", dt.date(2026, 11, 13))[0]["date"] == "2026-11-12"
    assert split("12/11/2026\n12:00:00 a", dt.date(2026, 11, 11))[0]["date"] == "2026-11-12"        # ... also a day ahead: day first
    # the day as chat programs head it, with its day of the week (Bloomberg IB: "Friday, November 13, 2026")
    for head in ("Friday, November 13, 2026", "Fri, Nov 13, 2026", "November 13, 2026", "Nov. 13th 2026", "Friday 13 November 2026",
                 "13 Kasım 2026 Cuma", "Cuma, 13 Kasım 2026", "13 KASIM 2026, CUMA", "— Friday, November 13, 2026 —"):
        assert split(head + "\n12:00:00 a", TODAY) == [{"date": "2026-11-13", "time": "12:00:00", "sender": "", "text": "a"}], head
    assert split("ÇARŞAMBA 1 NİSAN 2026\n12:00:00 a")[0]["date"] == "2026-04-01"              # the dotted İ of the capitals
    assert split("CUMARTESİ, 14 KASIM 2026\n12:00:00 a")[0]["date"] == "2026-11-14"
    # ... a day of the week that is not the date's makes it no day, nor does a date after tomorrow: a chat is not
    # written ahead of time - a bond's maturity on a line of its own is a message, and the day stays as it was
    for line in ("Friday, November 14, 2026", "15/03/2028", "Mar 15, 2028", "15 Mart 2028"):
        assert [(x["date"], x["text"]) for x in split(line + "\n12:00:00 a", TODAY)] == [(None, line), (None, "a")], line
    assert [x["date"] for x in split("13 Nov 2026\n12:00:00 a\n15/03/2028\n12:00:05 b", TODAY)] == ["2026-11-13"] * 3
    # the phone: the time under the message, for every line of the bubble; a name starts a new bubble
    m = split("MIKE REES\nfirst\nsecond\n13:01:10\nthird\nEVREN DIKME\nfourth\n13:05:00")
    assert [(x["time"], x["sender"], x["text"]) for x in m] == [("13:01:10", "MIKE REES", "first"), ("13:01:10", "MIKE REES", "second"),
                                                                 (None, "MIKE REES", "third"), ("13:05:00", "EVREN DIKME", "fourth")]
    assert split("6M OIS 35.88 BID")[0]["sender"] == ""                       # capitals alone do not make a name
    # ... nor does a message in capitals: it has its time next to it, or right below it
    assert split("12:00:00 THANKS MATE\n12:00:05 18m ois 35.03/35.23") == [
        {"date": None, "time": "12:00:00", "sender": "", "text": "THANKS MATE"},
        {"date": None, "time": "12:00:05", "sender": "", "text": "18m ois 35.03/35.23"}]
    m = split("MIKE REES\n18m ois 35.03/35.23\n13:01:10\nALL OFF\n13:02:00\n2y ois 35.26/35.46\n13:03:00")
    assert [(x["time"], x["sender"], x["text"]) for x in m] == [("13:01:10", "MIKE REES", "18m ois 35.03/35.23"), ("13:02:00", "MIKE REES", "ALL OFF"),
                                                                 ("13:03:00", "MIKE REES", "2y ois 35.26/35.46")]
    assert split("\n\n  \n") == []


def test_a_bloomberg_ib_chat_and_its_replies():
    # IB: the day above its messages, each sender's name on a line of its own above them; a reply carries the message it
    # answers - with its date, time and author - right above it: that quote is no message, and it moves neither the
    # day (a quote of the day before) nor whose the reply is
    chat = "\n".join(["Friday, November 13, 2026", "MIKE REES", "16:32:04 18m ois 35.03/35.23", "16:32:10 any int?",
                      "EVREN DIKME", "11/13/2026 16:32:04 MIKE REES: 18m ois 35.03/35.23", "16:32:59 05/20",
                      "11/12/2026 17:01:00 MIKE REES: 1y ois 35.00/35.20", "16:33:10 1y ois 35.05 bid",
                      "MIKE REES", "16:33:35 18m ois 35.05/35.20"])
    m = bc.split_messages(chat, TODAY)
    assert [(x["date"], x["time"], x["sender"], x["text"]) for x in m] == [
        ("2026-11-13", "16:32:04", "MIKE REES", "18m ois 35.03/35.23"), ("2026-11-13", "16:32:10", "MIKE REES", "any int?"),
        ("2026-11-13", "16:32:59", "EVREN DIKME", "05/20"), ("2026-11-13", "16:33:10", "EVREN DIKME", "1y ois 35.05 bid"),
        ("2026-11-13", "16:33:35", "MIKE REES", "18m ois 35.05/35.20")]
    rows = bc.parse_chat(chat, ref, TODAY)
    assert [(q["time"], q["label"]) for q in rows if q["ok"]] == [("16:32:04", "18M"), ("16:33:10", "1Y"), ("16:33:35", "18M")]
    assert [(r["label"], r["bid"], r["ask"]) for r in bc.board(rows)] == [("1Y", 35.05, None), ("18M", 35.05, 35.20)]
    # a paste that starts at a reply: the line under the quote, starting with its time, tells the quote
    m = bc.split_messages("EVREN DIKME\n11/12/2026 17:01:00 MIKE REES: 1y ois 35.00/35.20\n16:33:10 1y ois 35.05 bid", TODAY)
    assert [(x["date"], x["time"], x["sender"], x["text"]) for x in m] == [(None, "16:33:10", "EVREN DIKME", "1y ois 35.05 bid")]
    # an export of the chat - every line with its date, time and author - is read line by line, a name above it or not
    export = "11/13/2026 12:15:38 MIKE REES: 18m ois 35.03/35.23\n11/12/2026 12:16:00 EVREN DIKME: 2y ois 35.26/35.46"
    for text in (export, "MIKE REES\n" + export):
        m = bc.split_messages(text, TODAY)
        assert [(x["date"], x["time"], x["sender"]) for x in m] == [("2026-11-13", "12:15:38", "MIKE REES"),
                                                                    ("2026-11-12", "12:16:00", "EVREN DIKME")], text


def test_the_board_follows_the_chat():
    rows = bc.parse_chat("""10:00:00 18m ois 35.03/35.23
10:05:00 18m ois /35.20 offer
10:06:00 2y3y ois -20/-18
10:10:00 18m ois 35.05 bid
10:20:00 ref 18m ois offer
10:30:00 18m ois given at 05
10:40:00 18m ois 35.12
10:50:00 1y ois ref
selam""", ref, TODAY)
    board = bc.board(rows)
    assert [r["label"] for r in board] == ["18M", "2Y–3Y"]                    # "1y ois ref": nothing was there to take off
    r = board[0]
    assert (r["bid"], r["bid_time"]) == (35.05, "10:10:00")                   # "/35.20" took the bid off, 35.05 came after it
    assert (r["ask"], r["ask_time"]) == (None, "10:20:00")                    # the offer was pulled
    assert (r["last"], r["last_side"], r["last_time"]) == (35.05, "bid", "10:30:00")
    assert (r["level"], r["level_time"]) == (35.12, "10:40:00") and r["said"] == "18m ois 35.12" and r["time"] == "10:40:00"
    assert (board[1]["bid"], board[1]["ask"], board[1]["unit"]) == (-20.0, -18.0, "bp")
    # one side keeps standing while the other is spoken of
    rows = bc.parse_chat("10:00:00 18m ois 35.03/35.23\n10:05:00 18m ois 35.20 offer", ref)
    r = bc.board(rows)[0]
    assert (r["bid"], r["bid_time"], r["ask"], r["ask_time"]) == (35.03, "10:00:00", 35.20, "10:05:00")
    assert bc.board([]) == []


def test_one_instrument_against_another():
    # "A vs B": the spread of the two, the later one − the earlier (as "1y5y" is 5Y − 1Y); two FRAs are its parts -
    # its own instrument, not a quote of the 6x9 FRA with "9x12m" left beside it as a note
    q = one("6x9m vs 9x12m -65/-35")
    assert (q["product"], q["kind"], q["key"], q["unit"], q["bid"], q["ask"], q["note"]) == \
        ("OIS", "spread", "OIS:spread:6x9/9x12", "bp", -65.0, -35.0, "")
    assert q["parts"] == [{"kind": "fra", "tenors": ["6M", "9M"], "months": [6.0, 9.0]},
                          {"kind": "fra", "tenors": ["9M", "1Y"], "months": [9.0, 12.0]}]
    assert one("9x12m vs 6x9m -65/-35")["key"] == q["key"]
    # two tenors: the spread the desk also writes without the "vs" - the same instrument, without parts
    assert one("2y vs 5y -10/-5")["key"] == one("2y5y -10/-5")["key"] == one("5y v. 2y -10/-5")["key"] == "OIS:spread:2Y/5Y"
    assert "parts" not in one("2y vs 5y -10/-5")
    # where the curve has it: 9x12 − 6x9 (bp); a part the curve cannot answer leaves the spread without one
    fra = lambda a, b: {(6, 9): 0.3428, (9, 12): 0.3396}.get((a, b))      # noqa: E731
    assert bc.model_level(q, lambda t: None, fra) == pytest.approx(-32.0)
    assert bc.model_level(one("6x9 vs 12x15 -40/-30"), lambda t: None, fra) is None
    # on the board: a row of its own, next to the 6x9 FRA's - which keeps its own quote
    board = bc.board(bc.parse_chat("10:00:00 6x9 ois 34.10/34.30\n10:01:00 6x9m vs 9x12m -65/-35", ref, TODAY))
    assert [(r["label"], r["bid"], r["ask"]) for r in board] == [("6x9–9x12", -65.0, -35.0), ("6x9", 34.10, 34.30)]
    assert board[0]["parts"] == q["parts"]
    # two bonds are still a switch, the same tenor twice still a forward
    assert one("mar28 vs jul30 switch -45/-40")["kind"] == "switch" and one("1y1y 34.50/34.80")["kind"] == "fwd"


#: the meetings as the dashboard gives them to the parser: (decision, effective day), the OIS spot, the day of the chat
D = dt.date
CALENDAR = {"spot": D(2026, 11, 4), "on": TODAY,
            "meetings": [(D(2026, 10, 22), D(2026, 10, 23)), (D(2026, 12, 10), D(2026, 12, 11)), (D(2027, 1, 21), D(2027, 1, 22)),
                         (D(2027, 3, 18), D(2027, 3, 19)), (D(2027, 4, 22), D(2027, 4, 23)), (D(2027, 12, 9), D(2027, 12, 10)),
                         (D(2028, 1, 20), D(2028, 1, 21))]}
DEC = "OIS:mpc:2026-12-11/2027-01-22"


def mpc(text, where=None, on=TODAY, calendar=CALENDAR):
    # the chat's day on a line of its own (a day after "today" would not be taken for one)
    rows = [q for q in bc.parse_chat("%s\n10:00:00 %s" % (on.strftime("%d.%m.%Y"), text), where, max(on, TODAY), calendar=calendar) if q.get("ok")]
    assert all(q["date"] == on.isoformat() for q in rows)
    assert len(rows) == 1, (text, rows)
    return rows[0]


@pytest.mark.parametrize("text", [
    "dec mpc 3650/3700", "Dec MPC 36.50/37.00", "DEC MPC OIS 36.50/37.00", "december mpc 36.50/37.00", "mpc dec 36.50/37.00",
    "aralık ppk 36.50/37.00", "ARALIK PPK 36.50/37.00", "Aralık toplantısı 36.50/37.00", "dec meeting 36.50/37.00", "dec26 mpc 36.50/37.00",
    "dec'26 mpc 36.50/37.00", "dec 26 mpc 36.50/37.00", "mpc1 36.50/37.00", "MPC1 36.50/37.00", "mpc 1 36.50/37.00", "ppk1 36.50/37.00",
    "1st mpc 36.50/37.00", "next mpc 36.50/37.00", "first mpc 36.50/37.00", "1. ppk 36.50/37.00", "dec/jan mpc 36.50/37.00",
    "Dec/Jan MPC 36.50/37.00", "dec-jan mpc 36.50/37.00", "dec jan mpc 36.50/37.00", "dec / jan mpc 36.50/37.00", "mpc dec/jan 36.50/37.00",
    "mpc1/2 36.50/37.00", "mpc1→2 36.50/37.00", "dec mpc 36.50 bid 37.00 offer", "dec mpc 36.50 bid, 37.00 offer"])
def test_a_meeting_dated_quote_however_it_is_written(text):
    # the December meeting (decision 10.12, effective 11.12) to the next one (effective 22.01): one instrument
    q = mpc(text)
    assert (q["product"], q["kind"], q["key"], q["label"], q["unit"], q["bid"], q["ask"], q["event"]) == \
        ("OIS", "mpc", DEC, "MPC Ara26", "pct", 36.50, 37.00, "quote"), text
    assert (q["mpc"]["start"], q["mpc"]["end"], q["mpc"]["meeting"], q["mpc"]["until"], q["mpc"]["periods"]) == \
        ("2026-12-11", "2027-01-22", "2026-12-10", "2027-01-21", 1)
    assert q["note"] == "" and q["flags"] == []


def test_meeting_dated_quotes():
    # which meeting: a month is its first meeting ahead, a number counts them from the day of the chat
    assert mpc("jan mpc 35.90/36.10")["key"] == mpc("mpc2 35.90/36.10")["key"] == mpc("ocak ppk 35.90/36.10")["key"] == "OIS:mpc:2027-01-22/2027-03-19"
    assert mpc("dec27 mpc 30/31")["key"] == mpc("dec 2027 mpc 30/31")["key"] == "OIS:mpc:2027-12-10/2028-01-21"
    q = mpc("dec/mar mpc 36.20/36.40")                                       # two periods: one swap, December to March
    assert (q["key"], q["label"], q["mpc"]["periods"], q["tenors"]) == ("OIS:mpc:2026-12-11/2027-03-19", "MPC Ara26–Mar27", 2, ["Ara26", "Mar27"])
    q = mpc("spot/dec mpc 36.40/36.60")                                      # from the OIS spot to the December meeting
    assert (q["key"], q["label"], q["mpc"]["meeting"], q["mpc"]["periods"]) == ("OIS:mpc:2026-11-04/2026-12-11", "MPC Spot–Ara26", None, None)
    # after the December decision its period is running: "dec" is still that one, MPC1 is January
    late = D(2026, 12, 20)
    assert mpc("dec mpc 36.50/37.00", on=late)["key"] == DEC and mpc("mpc1 36.50/37.00", on=late)["key"] == "OIS:mpc:2027-01-22/2027-03-19"
    assert mpc("mpc1 36.50/37.00", on=D(2026, 12, 10))["key"] == DEC              # the day of the decision: still the first ahead
    # trades, refs, interest and the big figure completed from where the meeting swap stands
    near = lambda q: 35.76 if q["key"] == DEC else None                       # noqa: E731
    t = mpc("dec mpc paid 3675", near)
    assert (t["event"], t["side"], t["price"], t["key"]) == ("trade", "ask", 36.75, DEC)
    assert (mpc("dec mpc 70/80", near)["bid"], mpc("dec mpc 70/80", near)["ask"], mpc("dec mpc 70/80", near)["flags"]) == (35.70, 35.80, ["abbr"])
    assert mpc("ref dec mpc offer")["event"] == "ref" and mpc("care dec mpc offer")["event"] == "interest"
    # several in a line, and next to other quotes
    rows = [q for q in bc.parse_chat("10:00:00 dec mpc 3650/3700 jan mpc 3600/3650", None, TODAY, calendar=CALENDAR) if q["ok"]]
    assert [(q["key"], q["bid"], q["ask"]) for q in rows] == [(DEC, 36.50, 37.00), ("OIS:mpc:2027-01-22/2027-03-19", 36.00, 36.50)]
    rows = [q for q in bc.parse_chat("10:00:00 1y x 38.60/38.80, dec mpc 36.50/37.00", None, TODAY, calendar=CALENDAR) if q["ok"]]
    assert [(q["product"], q["kind"]) for q in rows] == [("XCCY", "outright"), ("OIS", "mpc")]
    q = mpc("dec mpc ois 36.50/37.00 in 5m")                                 # a size after it is a size, not a 5M tenor
    assert (q["key"], q["note"]) == (DEC, "5m")
    # what is not one meeting's rate stays text: two periods against each other (a step), a date, no meeting named
    for text in ("dec vs jan mpc -25/-20", "dec/jan mpc -25/-20", "dec/jan mpc spread -25/-20", "next mpc on 10 dec", "mpc 36.50/37.00",
                 "after the meeting 36.50"):
        assert not any(q.get("ok") for q in bc.parse_chat("10:00:00 " + text, None, TODAY, calendar=CALENDAR)), text
    # a tenor said first is the instrument; a meeting the calendar does not have is read, flagged and left undated
    assert one("18m ois 35.03/35.23 ahead of the dec meeting")["key"] == "OIS:outright:18M"
    q = mpc("dec35 mpc 30.00/31.00")
    assert (q["key"], q["label"], q["flags"], q["bid"]) == ("OIS:mpc:Ara35", "MPC Ara35", ["mpc?"], 30.0) and "start" not in q["mpc"]
    # without a calendar (the parser alone): read as said, not dated
    q = one("mpc1 36.50/37.00", None)
    assert (q["kind"], q["key"], q["label"], q["mpc"]["from"]) == ("mpc", "OIS:mpc:1", "MPC1", {"n": 1})
    assert one("dec/jan mpc 36.50/37.00", None)["label"] == "MPC Ara–Oca"
    # on the board: a row of its own after the outrights, whichever way it was said
    board = bc.board(bc.parse_chat("10:00:00 1y ois 35.00/35.20\n10:01:00 dec mpc 36.50/37.00\n10:02:00 mpc1 36.60 bid\n"
                                   "10:03:00 dec/jan mpc paid 37.00\n10:04:00 2y5y ois -20/-15", None, TODAY, calendar=CALENDAR))
    assert [(r["kind"], r["label"]) for r in board] == [("outright", "1Y"), ("mpc", "MPC Ara26"), ("spread", "2Y–5Y")]
    assert (board[1]["bid"], board[1]["ask"], board[1]["last"], board[1]["mpc"]["start"]) == (36.60, 37.00, 37.00, "2026-12-11")
    # where a curve has it: the rate between its two days
    rates = {("2026-12-11", "2027-01-22"): 0.3576}
    assert bc.model_level(mpc("dec mpc 36.50/37.00"), lambda t: None, None, lambda a, b: rates.get((a, b))) == pytest.approx(35.76)
    assert bc.model_level(mpc("dec mpc 36.50/37.00"), lambda t: None) is None
    assert bc.model_level(mpc("dec35 mpc 30.00/31.00"), lambda t: None, None, lambda a, b: 0.3) is None


def test_against_a_curve():
    par = {"6M": 0.3644, "1Y": 0.3555, "18M": 0.3559, "2Y": 0.3585, "3Y": 0.3566, "4Y": 0.3527, "5Y": 0.3471}.get
    fra = lambda a, b: {(9, 12): 0.3411, (12, 24): 0.3627}.get((a, b))      # noqa: E731
    level = lambda text: bc.model_level(one(text), par, fra)                 # noqa: E731
    assert level("18m ois 35.03/35.23") == pytest.approx(35.59)
    assert level("1y5y ois -64/-60") == pytest.approx(-84.0)                  # long − short, in bp
    assert level("2y3y4y ois 12/ bid") == pytest.approx((2 * 0.3566 - 0.3585 - 0.3527) * 1e4)
    assert level("9x12m ois fra 33.80/34.10") == pytest.approx(34.11) and level("1y1y 34.5/34.8") == pytest.approx(36.27)
    assert level("7y ois 33.5/33.7") is None and level("5y7y ois -10/-8") is None and level("3x6 36.1/36.3") is None
    assert bc.model_level(one("9x12 33.80/34.10"), par) is None               # no forwards without a curve for them
    row = bc.board(bc.parse_chat("10:00:00 18m ois 35.03/35.23\n10:01:00 18m ois taken at 23\n10:02:00 1y5y ois -64/-60"))
    out = bc.against(row[0], 35.59)
    assert out["mid"] == 35.59 and out["bid_diff"] == pytest.approx(-56.0) and out["ask_diff"] == pytest.approx(-36.0)
    assert out["last_diff"] == pytest.approx(-36.0)
    out = bc.against(row[1], -84.0)
    assert out["bid_diff"] == pytest.approx(20.0) and out["ask_diff"] == pytest.approx(24.0) and out["last_diff"] is None
    assert bc.against(row[0], None) == {"mid": None, "bid_diff": None, "ask_diff": None, "last_diff": None}


# ---------------------------------------------------------------------------------------------- kept by the dashboard
@pytest.fixture(scope="module")
def desk(module_service):
    return module_service, module_service.login("Broker A")["user"]


def curve(svc, user=None):
    book = svc.books["tto"]
    return svc.et.call(lambda: bl.OisMarket(book, svc._calc(user, book)))


def test_forwards_of_the_curve(desk):
    svc, _ = desk
    mkt = curve(svc)

    def run():
        for tenor in ("3M", "6M", "1Y", "2Y", "5Y", "10Y"):
            assert mkt.fra_months(0, bl.TENOR_MONTHS[tenor]) == pytest.approx(mkt.par(tenor), abs=1e-9)     # from spot: the par rate
        a9, a12 = mkt.annuity_months(9), mkt.annuity_months(12)
        assert mkt.fra_months(9, 12) == pytest.approx((mkt.par("1Y") * a12 - mkt.par("9M") * a9) / (a12 - a9), abs=1e-12)
        assert mkt.fra_months(12, 9) is None and mkt.fra_months(9, 10) is None and mkt.fra_months(0, 123) is None
        return mkt.fra_months(9, 12), mkt.par("9M"), mkt.par("1Y")

    fra, p9, p12 = svc.et.call(run)
    assert fra < p12 < p9                                                     # an inverted curve: the forward is below both


def test_a_chat_is_previewed_kept_and_not_kept_twice(desk):
    svc, u = desk
    today = svc.today_iso()
    seen = svc.broker_parse(u, DESK_SAMPLE)
    assert (seen["date"], seen["quotes"], seen["texts"], seen["known"]) == (today, 14, 0, 0)
    assert svc.broker(u)["rows"] == []                                        # a preview keeps nothing
    assert all(q["date"] == today and q["dup"] is False and q["mark"] for q in seen["rows"])
    assert [q["timed"] for q in seen["rows"]] == [True] * 13 + [False]
    res = svc.broker_add(u, DESK_SAMPLE, None, "Tullett")
    assert (res["saved"], res["skipped"], res["quotes"], res["dates"]) == (14, 0, 14, [today]) and len(res["ids"]) == 14
    data = svc.broker(u)
    assert (data["date"], data["to"], data["ranged"], data["is_today"], data["today"]) == (today, today, False, True, today)
    rows = data["rows"]
    # in the order said (the line without a time: when it was entered - now, wherever that falls in the day)
    assert [q["time"] for q in rows] == sorted(q["time"] for q in rows) and [q for q in rows if q["timed"]][0]["time"] == "10:23:58"
    assert all(q["source"] == "Tullett" and q["created_by"] == u and q["id"] and q["created_at"] for q in rows)
    q = next(x for x in rows if x["raw"] == "18m ois 35.03/35.23")
    assert (q["time"], q["label"], q["bid"], q["ask"], q["timed"], q["event"]) == ("12:15:38", "18M", 35.03, 35.23, True, "quote")
    assert data["dates"] == [{"date": today, "count": 14}]
    # the same stretch again: only the line without a time is new (it is written when it is entered)
    again = svc.broker_parse(u, DESK_SAMPLE)
    assert again["known"] >= 13 and [q["dup"] for q in again["rows"][:13]] == [True] * 13
    more = "12:31:48 18m ois 35.03/35.23\n12:40:00 2y ois 35.26/35.46"
    res = svc.broker_add(u, more)
    assert (res["saved"], res["skipped"]) == (1, 1)
    # the same words at another time, or from someone else, are another message
    assert svc.broker_add(u, "12:41:00 2y ois 35.26/35.46\nMIKE REES\n2y ois 35.26/35.46\n12:40:00")["saved"] == 2
    assert svc.broker_add(u, "12:41:00 2y ois 35.26/35.46")["saved"] == 0
    # a repeated line of one message and the two halves of an "oco" are each kept once
    res = svc.broker_add(u, "13:51:22 2yr ois 35.46 , oco with 18m 35.14 offer")
    assert res["saved"] == 2 and svc.broker_add(u, "13:51:22 2yr ois 35.46 , oco with 18m 35.14 offer")["saved"] == 0


def test_shortened_levels_use_what_was_said_then_the_curve(desk):
    svc, u = desk
    mkt = curve(svc, u)
    # nothing said about the 9M yet: completed from the dashboard's own curve
    par9 = svc.et.call(lambda: mkt.par("9M")) * 100
    q = svc.broker_parse(u, "9m ois 50 bid")["rows"][0]
    assert q["flags"] in (["abbr"], ["ambiguous"]) and abs(q["bid"] - par9) <= 0.5 and round(q["bid"] * 100) % 100 == 50
    assert q["model"] == pytest.approx(par9)
    # ... and kept that way, with where the curve was when it was entered
    svc.broker_add(u, "21m ois 50 bid")
    par21 = svc.et.call(lambda: mkt.par("21M")) * 100
    kept = next(x for x in svc.broker(u)["rows"] if x["raw"] == "21m ois 50 bid")
    assert abs(kept["bid"] - par21) <= 0.5 and round(kept["bid"] * 100) % 100 == 50 and kept["model"] == pytest.approx(par21)
    assert kept["timed"] is False and len(kept["time"]) == 8
    # once a level is kept, it is the reference - however far the curve is - for what is said after it
    par4 = svc.et.call(lambda: mkt.par("4Y")) * 100
    svc.broker_add(u, "15:04:20 4y OIS 31.88 bid")
    q = svc.broker_parse(u, "16:48:21 4y OIS 90 bid")["rows"][0]
    assert (q["bid"], q["flags"]) == (31.90, ["abbr"])
    if dt.datetime.now().strftime("%H:%M:%S") > "15:04:20":                  # no time: said now - after it, in the afternoon
        assert svc.broker_parse(u, "4y OIS 90 bid")["rows"][0]["bid"] == 31.90
    early = svc.broker_parse(u, "15:00:00 4y OIS 90 bid")["rows"][0]          # said before it: the curve again
    assert abs(early["bid"] - par4) <= 0.5 and early["bid"] != 31.90
    # "taken" without a price: the offer that stood on the board then
    svc.broker_add(u, "15:10:00 3y ois 35.50/35.70\n15:20:00 3y ois 35.52/35.68")
    q = svc.broker_parse(u, "15:11:00 3y ois taken")["rows"][0]
    assert (q["event"], q["price"], q["side"], q["flags"]) == ("trade", 35.70, "ask", ["standing"])
    assert svc.broker_parse(u, "15:21:00 3y ois given")["rows"][0]["price"] == 35.52
    assert svc.broker_parse(u, "15:09:00 3y ois taken")["rows"][0]["price"] is None       # nothing stood yet
    # the desk's "6m 90/10": both sides find their figure, from the curve when nothing was said
    par6 = svc.et.call(lambda: mkt.par("6M")) * 100
    q = svc.broker_parse(u, "00:00:00 6m 90/10")["rows"][0]                  # (before the sample's "6m" without a time)
    assert q["ask"] - q["bid"] == pytest.approx(0.20) and round(q["bid"] * 100) % 100 == 90 and abs((q["bid"] + q["ask"]) / 2 - par6) <= 0.5
    svc.broker_add(u, "09:01:00 6m ois 35.88 bid")
    q = svc.broker_parse(u, "09:02:00 6m 90/10")["rows"][0]
    assert (q["bid"], q["ask"], q["flags"]) == (35.90, 36.10, ["abbr"])
    # cross-currency: no curve to ask - the last close of the history finds the figure, when there is one
    q = svc.broker_parse(u, "2yr x 40 offer")["rows"][0]
    assert q["ask"] == 40.0 and q["flags"] == ["no-ref"] and q["model"] is None
    assert svc.broker_parse(u, "2yr x 90/10")["rows"][0]["flags"] == ["no-ref", "crossed"]
    swap = next(d for d in svc.history.snapshot()["defs"] if d.group == "xccy" and d.label == "2Y")
    svc.store.hist_upsert(swap.id, [("2026-11-02", 40.60), ("2026-11-03", 40.75)])
    svc.history.rev += 1                                                     # as the history does when it stores closes
    q = svc.broker_parse(u, "2yr x 90/10")["rows"][0]
    assert (q["product"], q["bid"], q["ask"], q["flags"], q["model"]) == ("XCCY", 40.90, 41.10, ["abbr"], None)
    assert svc.broker_parse(u, "2yr x 80 offer")["rows"][0]["ask"] == 40.80


def test_the_board_next_to_the_curve(desk):
    svc, u = desk
    svc.broker_add(u, "16:00:00 1y ois 35.00/35.20\n16:00:01 1y5y ois -64/-60\n16:00:02 2y3y4y ois 12/ bid\n16:00:03 9x12m ois fra 33.80/34.10\n"
                      "16:00:04 1yr x 38.60/80\n16:00:05 1y ois taken at 20\n16:00:06 7y9y ois -5/-2\n16:00:07 1y1y 36.10/36.40")
    mkt = curve(svc, u)
    par = {t: svc.et.call(lambda t=t: mkt.par(t)) for t in ("1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "9Y")}
    board = {r["key"]: r for r in svc.broker(u)["board"]}
    r = board["OIS:outright:1Y"]
    assert r["mid"] == pytest.approx(par["1Y"] * 100)
    assert r["bid_diff"] == pytest.approx((35.00 - par["1Y"] * 100) * 100) and r["ask_diff"] == pytest.approx((35.20 - par["1Y"] * 100) * 100)
    assert (r["last"], r["last_side"]) == (35.20, "ask") and r["last_diff"] == pytest.approx(r["ask_diff"])
    r = board["OIS:spread:1Y/5Y"]
    assert r["mid"] == pytest.approx((par["5Y"] - par["1Y"]) * 1e4) and r["bid_diff"] == pytest.approx(-64 - r["mid"])
    r = board["OIS:fly:2Y/3Y/4Y"]
    assert r["mid"] == pytest.approx((2 * par["3Y"] - par["2Y"] - par["4Y"]) * 1e4) and r["ask"] is None and r["ask_diff"] is None
    assert board["OIS:spread:7Y/9Y"]["mid"] == pytest.approx((par["9Y"] - par["7Y"]) * 1e4)
    fra = svc.et.call(lambda: (mkt.fra_months(9, 12), mkt.fra_months(12, 24)))
    assert board["OIS:fra:9M/1Y"]["mid"] == pytest.approx(fra[0] * 100) and board["OIS:fwd:1Y/1Y"]["mid"] == pytest.approx(fra[1] * 100)
    x = board["XCCY:outright:1Y"]
    assert (x["bid"], x["ask"], x["mid"], x["bid_diff"]) == (38.60, 38.80, None, None)
    # OIS first, outrights by tenor, then spreads, flies, forwards
    kinds = [r["kind"] for r in svc.broker(u)["board"] if r["product"] == "OIS"]
    assert kinds == sorted(kinds, key=bc.KINDS.index)
    # a spread of two FRAs ("6x9m vs 9x12m"): the curve's 9x12 − its 6x9, in bp (read without keeping it)
    f = svc.et.call(lambda: (mkt.fra_months(6, 9), mkt.fra_months(9, 12)))
    row = svc.broker_parse(u, "16:00:08 6x9m vs 9x12m -65/-35")["rows"][0]
    assert (row["key"], row["bid"], row["ask"]) == ("OIS:spread:6x9/9x12", -65.0, -35.0)
    assert row["model"] == pytest.approx((f[1] - f[0]) * 1e4)
    # the curve of the user's own scenario
    other = svc.login("Broker B")["user"]
    svc.set_inputs(other, "tto", [{"ref": "OIS_MAIN!B14", "value": "40"}], allow_adhoc=True)
    try:
        mine = {r["key"]: r for r in svc.broker(other)["board"]}["OIS:outright:1Y"]
        assert mine["mid"] == pytest.approx(40.0) and mine["bid"] == 35.00
        assert {r["key"]: r for r in svc.broker(u)["board"]}["OIS:outright:1Y"]["mid"] == pytest.approx(par["1Y"] * 100)
    finally:
        svc.reset_inputs(other, "tto", ["OIS_MAIN!B14"])


def test_switches_next_to_the_screen(desk):
    """A switch next to the DİBS RV screen: the screen's switch (the longer bond's yield − the shorter one's) as its
    model, and where the level said stands against it and against the fitted ASW curve; one written leg by leg gets
    its level from the legs' prices made yields on the screen."""
    from tto.service import Service
    svc, u = desk
    day = (dt.date.today() - dt.timedelta(days=50)).isoformat()
    svc.broker_add(u, "10:01:02 mar28 vs jul30 switch -45/-40\n10:02:00 mar28 100.200 vs jul30 93.900 switch trading\n"
                      "10:03:00 Sw int 9/1/30 775 offer vs 3/7/30 775 bid", day)
    mkt = curve(svc, u)
    a, b, f1, f2 = (svc.et.call(lambda i=i: Service._bond_screen(mkt, i)) for i in ("TRT150328T24", "TRT100730T13", "TRT090130T12", "TRT030730T12"))
    screen = (b["yield"] - a["yield"]) * 100
    seen = svc.broker(u, day)
    rows = [q for q in seen["rows"] if q.get("ok")]
    quote, trade, floater = rows
    assert quote["model"] == pytest.approx(screen) and quote["implied"]["screen"] == pytest.approx(screen)
    m = quote["implied"]
    assert m["rv"] == pytest.approx(b["rv"] - a["rv"]) and m["at"] == -42.5 and m["vs_screen"] == pytest.approx(-42.5 - screen)
    assert m["vs_curve"] == pytest.approx(m["rv"] + m["vs_screen"])
    ys = [s["yield"] - (p - s["clean"]) / (s["clean"] * s["mod_dur"]) * 100 for s, p in ((a, 100.2), (b, 93.9))]
    assert trade["event"] == "trade" and trade["price"] == pytest.approx((ys[1] - ys[0]) * 100)
    assert [leg["yield"] for leg in trade["legs"]] == pytest.approx(ys) and trade["implied"]["at"] == pytest.approx(trade["price"])
    # floaters: the difference of the two prices, each completed from its own screen price
    assert floater["unit"] == "px" and floater["event"] == "interest"
    levels = [leg["level"] for leg in floater["legs"]]
    assert all(abs(lv - s["clean"]) < 0.5 for lv, s in zip(levels, (f1, f2))) and floater["price"] == pytest.approx(levels[1] - levels[0])
    assert floater["model"] == pytest.approx(f2["clean"] - f1["clean"])
    board = {r["key"]: r for r in seen["board"]}
    r = board["DIBS:switch:TRT150328T24/TRT100730T13"]
    assert (r["bid"], r["ask"], r["last"]) == (-45.0, -40.0, pytest.approx(trade["price"])) and r["mid"] == pytest.approx(screen)
    assert r["bid_diff"] == pytest.approx(-45.0 - screen) and r["implied"]["kind"] == "switch"
    # not a bond's own trade: the DİBS pages leave a switch out
    assert all(t.get("kind") != "switch" for t in svc.broker(u, day)["rows"] if t.get("isin"))


def overnight(rate, days):
    return 365.0 * ((1.0 + rate * days / 365.0) ** (1.0 / days) - 1.0)


def test_meeting_dated_quotes_next_to_the_mpc_bootstrap(desk):
    """ "dec mpc", "jan27 mpc", "dec/mar mpc", "spot/dec mpc" dated with the workbook's meetings; the model is the 'MPC OIS'
    bootstrap - the trade form's market level for the same two days -, with the step at the meeting each level stands for."""
    from conftest import cell
    from tto.xl.values import date_to_serial
    svc, u = desk
    day = "2026-01-15"                                         # a day no other test keeps lines on
    m = svc.ois_market(u)["mpc"]
    e1, e2, e3, spot = m["dates"][0]["date"], m["dates"][1]["date"], m["dates"][2]["date"], m["spot"]
    serial = lambda iso: float(date_to_serial(dt.date.fromisoformat(iso)))        # noqa: E731
    market = lambda a, b: svc.quote_ois(u, {"strategy": "mpc", "side": "PAY", "start": a, "end": b, "level": "36"})["info"]["market"] * 100   # noqa: E731
    text = ("10:00:00 dec mpc 3650/3700\n10:01:00 jan27 mpc 50/60\n10:02:00 dec/mar mpc 36.20/36.40\n10:03:00 spot/dec mpc 36.40/36.60\n"
            "10:04:00 dec mpc paid 36.75\n10:05:00 dec40 mpc 30.00/31.00")
    rows = {q["raw"].split(" mpc")[0]: q for q in svc.broker_parse(u, text, day)["rows"] if q["event"] != "trade"}
    dec = rows["dec"]
    assert (dec["key"], dec["label"], dec["bid"], dec["ask"]) == ("OIS:mpc:2026-12-11/2027-01-22", "MPC Ara26", 36.50, 37.00)
    assert serial(dec["mpc"]["start"]) == e1 and serial(dec["mpc"]["end"]) == e2
    assert dec["model"] == pytest.approx(cell(svc, "OIS_MAIN!D84", u) * 100, rel=1e-12) == pytest.approx(market(e1, e2), rel=1e-12)
    jan = rows["jan27"]
    assert jan["model"] == pytest.approx(cell(svc, "OIS_MAIN!D85", u) * 100, rel=1e-12)
    assert jan["flags"] == ["abbr"] and (jan["bid"], jan["ask"]) == (int(jan["model"]) + 0.50, int(jan["model"]) + 0.60)   # the figure from the model
    assert rows["dec/mar"]["model"] == pytest.approx(market(e1, e3), rel=1e-12) and rows["dec/mar"]["label"] == "MPC Ara26–Mar27"
    assert rows["spot/dec"]["model"] == pytest.approx(market(spot, e1), rel=1e-12) and rows["spot/dec"]["label"] == "MPC Spot–Ara26"
    far = rows["dec40"]
    assert far["flags"] == ["mpc?"] and far["model"] is None and far["key"] == "OIS:mpc:Ara40"
    # the step at the December meeting: overnight equivalent of the level − that of the bootstrap's period before it
    stub = market(spot, e1) / 100
    base = overnight(stub, e1 - spot)
    step = dec["implied"]
    assert step["kind"] == "mpc" and step["meeting"] == "2026-12-10" and step["days"] == e2 - e1
    assert step["bid"] == pytest.approx((overnight(0.365, e2 - e1) - base) * 1e4) and step["ask"] == pytest.approx((overnight(0.37, e2 - e1) - base) * 1e4)
    assert step["model"] == pytest.approx((overnight(dec["model"] / 100, e2 - e1) - base) * 1e4) and step["prev"] == pytest.approx(stub * 100)
    assert -300 < step["model"] < 300 and step["bid"] < step["ask"]
    assert "implied" not in rows["dec/mar"] and "implied" not in rows["spot/dec"]       # a step belongs to one meeting's period
    # kept: one board row per meeting swap, after the outrights, with the bootstrap as its model and the trade on it
    svc.broker_add(u, text + "\n10:06:00 1y ois 35.00/35.20", day, "Tullett")
    board = svc.broker(u, day)["board"]
    assert [r["label"] for r in board] == ["1Y", "MPC Spot–Ara26", "MPC Ara26", "MPC Ara26–Mar27", "MPC Oca27", "MPC Ara40"]
    r = next(x for x in board if x["label"] == "MPC Ara26")
    assert (r["kind"], r["bid"], r["ask"], r["last"]) == ("mpc", 36.50, 37.00, 36.75) and r["mid"] == pytest.approx(dec["model"])
    assert r["bid_diff"] == pytest.approx((36.50 - dec["model"]) * 100) and r["implied"]["last"] == pytest.approx((overnight(0.3675, e2 - e1) - base) * 1e4)
    # the trade form books it between the same two days, at the same market level
    q = svc.quote_ois(u, {"strategy": "mpc", "side": "PAY", "start": serial(r["mpc"]["start"]), "end": serial(r["mpc"]["end"]), "level": "36,75"})
    assert q["info"]["market"] * 100 == pytest.approx(r["mid"], rel=1e-12) and q["legs"][0]["tenor"] == "MPC 11.12.26–22.01.27"


def test_days_periods_and_what_is_left_out(desk):
    svc, u = desk
    today = dt.date.today()
    before = (today - dt.timedelta(days=3)).isoformat()
    # a day typed in the box, and a day the chat names itself
    # (an empty line between: "selam" is a message of its own, without a time - not a line of the 09:00 message)
    res = svc.broker_add(u, "09:00:00 2y ois 35.30/35.50\n\nselam\n", before, "ICAP")
    assert (res["saved"], res["quotes"], res["dates"]) == (2, 1, [before])
    named = (today - dt.timedelta(days=2))
    res = svc.broker_add(u, "%s\n09:00:00 2y ois 35.32/35.52\n" % named.strftime("%d.%m.%Y"), before)
    assert res["dates"] == [named.isoformat()]
    day = svc.broker(u, before)
    assert (day["is_today"], day["ranged"], len(day["rows"])) == (False, False, 2)
    assert sorted((q["ok"], q["event"], q["raw"], q["source"]) for q in day["rows"]) == [(False, "text", "selam", "ICAP"),
                                                                                      (True, "quote", "2y ois 35.30/35.50", "ICAP")]
    hello = next(q for q in day["rows"] if q["raw"] == "selam")                # (when it was entered: now)
    assert hello["timed"] is False and len(hello["time"]) == 8
    assert [r["label"] for r in day["board"]] == ["2Y"] and day["board"][0]["bid"] == 35.30
    span = svc.broker(u, named.isoformat(), before)                           # the two ends in any order
    assert (span["date"], span["to"], span["ranged"], span["is_today"]) == (before, named.isoformat(), True, False)
    assert [q["date"] for q in span["rows"]] == [before, before, named.isoformat()]
    assert span["board"][0]["bid"] == 35.32 and span["board"][0]["bid_time"] == named.isoformat() + " 09:00:00"      # the later day stands
    assert {d["date"]: d["count"] for d in svc.broker(u)["dates"]}.items() >= {before: 2, named.isoformat(): 1}.items()
    # text lines are left out when asked; a chat with nothing in it is refused
    old = (today - dt.timedelta(days=9)).isoformat()
    res = svc.broker_add(u, "09:00:00 günaydın\n09:01:00 2y ois 35.30/35.50", old, "", False)
    assert res["saved"] == 1 and [q["raw"] for q in svc.broker(u, old)["rows"]] == ["2y ois 35.30/35.50"]
    for text, date in (("", None), ("   \n", None), ("09:00:00 günaydın", old)):
        with pytest.raises(ServiceError):
            svc.broker_add(u, text, date, "", False)
    with pytest.raises(ServiceError):
        svc.broker(u, "dün")
    with pytest.raises(ServiceError):
        svc.broker_add(u, "2y ois 35.30/35.50", "13.11.2026")
    with pytest.raises(ServiceError) as err:
        svc.broker_add(None, "2y ois 35.30/35.50")
    assert err.value.status == 401
    # deleting takes the line off the list and off the board
    row = svc.broker(u, old)["rows"][0]
    gen = svc.gen
    assert svc.broker_delete(u, row["id"]) == {"deleted": row["id"]} and svc.gen > gen
    assert svc.broker(u, old)["rows"] == [] and svc.broker(u, old)["board"] == []
    with pytest.raises(ServiceError) as err:
        svc.broker_delete(u, row["id"])
    assert err.value.status == 404
    assert svc.broker_add(u, "09:01:00 2y ois 35.30/35.50", old)["saved"] == 1         # and it can be entered again


def test_the_chat_as_a_workbook(desk):
    from helpers import read_xlsx
    from tto.xl.values import date_to_serial
    svc, u = desk
    day = dt.date.today() - dt.timedelta(days=20)
    svc.broker_add(u, "MIKE REES\n18m ois 35.03/35.23\n10:00:00\n1y5y ois -64/-60\n10:01:00\n18m ois taken at 23\n10:02:00\nteşekkürler\n10:03:00",
                   day.isoformat(), "Tullett")
    raw, name = svc.broker_export(u, day.isoformat())
    assert name == "BrokerChat_%s.xlsx" % day.strftime("%Y.%m.%d")
    book = read_xlsx(raw)
    assert list(book) == ["Tahta", "Kayıt"]
    board, log = book["Tahta"], book["Kayıt"]
    assert [board[c + "1"] for c in "ABCDEFGHIJKLM"] == ["Ürün", "Tür", "Enstrüman", "Birim", "Bid", "Bid saati", "Ask", "Ask saati", "Son işlem",
                                                         "İşlem saati", "Model mid", "Bid − mid (bp)", "Ask − mid (bp)"]
    assert [board[c + "2"] for c in "ABCDEGI"] == ["OIS", "Outright", "18M", "%", 35.03, 35.23, 35.23]
    assert board["F2"] == day.isoformat() + " 10:00:00" and board["J2"] == day.isoformat() + " 10:02:00"
    assert board["K2"] == pytest.approx(svc.broker(u, day.isoformat())["board"][0]["mid"]) and board["L2"] == pytest.approx((35.03 - board["K2"]) * 100)
    assert [board[c + "3"] for c in "ABCDEG"] == ["OIS", "Spread", "1Y–5Y", "bp", -64, -60]
    assert log["A1"] == "Tarih" and log["B1"] == "Saat" and log["E1"] == "Mesaj" and "yyyy" in log["!formats"]["A2"]
    assert [log[c + "2"] for c in "ABCDEFGHIJK"] == [date_to_serial(day), "10:00:00", "MIKE REES", "Tullett", "18m ois 35.03/35.23", "OIS", "Outright",
                                                     "18M", "Kota", 35.03, 35.23]
    assert (log["I4"], log["L4"], log["O4"]) == ("İşlem", 35.23, "Broker A")
    assert (log["E5"], log["I5"]) == ("teşekkürler", "Metin") and "J5" not in log
    # a period
    raw, name = svc.broker_export(u, day.isoformat(), dt.date.today().isoformat())
    assert name == "BrokerChat_%s-%s.xlsx" % (day.strftime("%Y.%m.%d"), dt.date.today().strftime("%Y.%m.%d"))
    assert len([k for k in read_xlsx(raw)["Kayıt"] if k.startswith("A")]) > 6


def test_kept_across_a_restart(tmp_path):
    from conftest import make_service
    svc = make_service(tmp_path)
    try:
        u = svc.login("Kalıcı")["user"]
        svc.broker_add(u, "12:15:38 18m ois 35.03/35.23", None, "Tullett")
    finally:
        svc.stop()
    svc = make_service(tmp_path)
    try:
        rows = svc.broker(None)["rows"]
        assert [(q["time"], q["raw"], q["bid"], q["ask"], q["source"], q["created_by"]) for q in rows] == [
            ("12:15:38", "18m ois 35.03/35.23", 35.03, 35.23, "Tullett", u)]
    finally:
        svc.stop()


# ---------------------------------------------------------------------------------------------- over HTTP
@pytest.fixture(scope="module")
def client(module_service):
    with TestClient(create_app(module_service)) as c:
        yield c


def test_broker_chat_over_http(client, module_service):
    user = module_service.login("Broker Web")["user"]
    hdr = auth(module_service, user)
    day = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    text = "12:15:38 18m ois 35.03/35.23\n12:18:04 2y3y4y ois 12/ bid\nselam"
    res = client.post("/api/broker/parse", json={"text": text, "date": day}, headers=hdr)
    assert res.status_code == 200
    seen = res.json()
    assert (seen["date"], seen["quotes"], seen["texts"], seen["known"]) == (day, 2, 1, 0)
    assert [(q["label"], q["bid"], q["ask"]) for q in seen["rows"][:2]] == [("18M", 35.03, 35.23), ("2Y–3Y–4Y", 12.0, None)]
    assert client.get("/api/broker", params={"date": day}, headers=hdr).json()["rows"] == []
    assert client.post("/api/broker", json={"text": text, "date": day}).status_code == 401          # saving needs a name
    res = client.post("/api/broker", json={"text": text, "date": day, "source": "Tullett", "texts": False}, headers=hdr)
    assert res.status_code == 200 and (res.json()["saved"], res.json()["skipped"], res.json()["dates"]) == (2, 0, [day])
    assert client.post("/api/broker", json={"text": text, "date": day, "texts": False}, headers=hdr).json()["saved"] == 0
    data = client.get("/api/broker", params={"date": day}, headers=hdr).json()
    assert [q["raw"] for q in data["rows"]] == ["18m ois 35.03/35.23", "2y3y4y ois 12/ bid"] and len(data["board"]) == 2
    assert data["board"][0]["mid"] is not None and data["rows"][0]["source"] == "Tullett"
    span = client.get("/api/broker", params={"date": day, "to": dt.date.today().isoformat()}, headers=hdr).json()
    assert span["ranged"] is True and len(span["rows"]) >= 2
    assert client.get("/api/broker", params={"date": "dün"}, headers=hdr).status_code == 400
    assert client.post("/api/broker", json={"text": "", "date": day}, headers=hdr).status_code == 400
    res = client.get("/api/broker/export", params={"date": day}, headers=hdr)
    assert res.status_code == 200 and res.content[:2] == b"PK"
    assert res.headers["content-disposition"] == 'attachment; filename="BrokerChat_%s.xlsx"' % day.replace("-", ".")
    row = data["rows"][0]["id"]
    assert client.delete("/api/broker/%d" % row).status_code == 401
    assert client.delete("/api/broker/%d" % row, headers=hdr).json() == {"deleted": row}
    assert client.delete("/api/broker/%d" % row, headers=hdr).status_code == 404
    assert [q["raw"] for q in client.get("/api/broker", params={"date": day}, headers=hdr).json()["rows"]] == ["2y3y4y ois 12/ bid"]
    nav = client.get("/api/nav", headers=hdr).json()["pages"]
    assert [p["title"] for p in nav if p["id"] == "broker"] == ["Broker Chat"]
    assert client.get("/static/js/pages/broker.js").status_code == 200
