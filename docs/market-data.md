# Market data and Bloomberg

**The desk's Bloomberg terminal has a daily data limit, and it is a hard rule.** Going over it stops reference and
history data for the whole desk.

Before adding any ticker, field, history series or request loop:
1. State its daily cost: hits = securities × fields per request, plus the data points and how often it runs.
2. Get the user's OK.

Never restart a live dashboard over and over, and ask before a heavy BDH. Bloomberg data, screenshots of it and logs
never go into the repository or to an external service.

Line numbers are as of commit a5e7ea7.

---

## Modes

| Mode | Where values come from |
|---|---|
| **live** | blpapi on `localhost:8194`, services `//blp/refdata` and `//blp/mktdata`. It runs in a helper process (`marketdata/bbg_process.py`) unless `--bbg-inprocess` is given. |
| **replay** | The values saved in the workbook (`marketdata/replay.py`, `snapshot_from_model`). See [Replay](#replay). |
| **auto** (default) | Live if Bloomberg connects, otherwise replay. The fallback is silent apart from `mode_note`. |
| tests | Replay (`tests/conftest.py`: `Settings(mode="replay")`), plus fake terminals: `tests/fake_blpapi.py`, handed in-process (`BloombergProvider(blpapi_module=fake_blpapi.module(server))`); `fake_blpapi_live.py`, imported by name through env `TTO_BLPAPI_MODULE` and set up by env `TTO_FAKE_BBG`; `fake_blpapi_broken.py`, a `blpapi` that fails to import (`blpapi_name`) |

**This computer has Bloomberg too.** The home computer the sessions run on has a terminal, as the desk's office
computer does. `--mode auto` (the default, env `TTO_MODE`) goes live whenever Bloomberg connects, so a session starts
anything itself with `--mode replay`. Agents work in replay and on the fake terminals only.

## Replay

**Where replay values come from.**
- **Pinned cells.** In books `tto` and `sofr` (`books.BOOKS`: the files that recorded their Bloomberg values), every
  formula cell that calls an add-in anywhere in its formula and has a value Excel saved is pinned to that value, with
  the cells its array spilled into (`xl/engine.py:1240-1286`, `formula_has_addin` / `cached_pins`). This covers the
  cells the dashboard patched too: `OIS_MAIN!B9`'s source chain shows the saved value whatever EK_KAYNAK says.
- **Provider answers.** Each `tto` cell that is exactly one add-in call with a saved value also becomes an answer of the
  replay provider (`snapshot_from_model`, `Service._setup`). The other books read these: EK_FX's `TRYI` / `TRYSAQ`
  prices (the BGN bid and ask the Forward sheet saved) and `ASW!C4`'s `SETTLE_DT` come from them.
- `asw` and `borsa` recorded nothing themselves. They are calculated on those answers plus `tto/data/replay_asw.json`
  and `replay_borsa.json`. `replay_usd.json` adds USD OIS mids for the USD · FOMC page.
- Past closes: the `BDH` blocks the `tto` file saved, then `tto/data/replay_history.json` for the days they lack
  (`ReplayProvider.history`: the file's own wins).
- A key without a recorded answer is `#N/A` (`ReplayProvider.missing` counts them).

**The replay day is 03.11.2026.**
- It is the saved value of the plain `=TODAY()` cell in `models/tto.json.gz` (`books.snapshot_today`).
- If that cell were missing, replay would silently use the machine's clock.
- The file is the desk's Excel **as it was saved that day**. Cells that were `#N/A` at that moment stay `#N/A` in every
  replay. For example, `Forward!D130:F134` (`TRYSAQ6–10` BGN) are `#N/A`, so the file's offshore curve stops at 5Y and
  EK_FX falls back to OIS at 6Y–10Y.
- **This is not the desk.** The desk's history has those tickers on every day. Never report a replay gap as a desk
  fact. Check the desk database (below) and say which source a statement comes from.

## What costs hits (`tto/marketdata/bloomberg.py`)

| Request | Cost and refresh |
|---|---|
| Quote fields (BID, ASK, MID, PX_LAST …) | One reference request for the first value, then a subscription. Streaming is free. A field the stream does not deliver (a failed subscription, or nothing 30 s after it started: `SILENT_AFTER`) is polled by request instead: after `--price-poll` (120 s), then at twice the interval while the answer stays the same, up to 30 min (60 min for an empty field). With `--no-stream` every quote field is polled so. A quote field with overrides is an ordinary BDP (next row). |
| Other BDP | securities × fields. Refreshed every 6 h (static fields), 60 s (derived) or 30 min (the rest). |
| BDH | One hit per security, whatever the date span. Refreshed every 15 min if it ends today, else every 6 h. |
| Intraday bars | 1 per request |
| Batching | BDP 100 securities per request, BDS / BDH 50, at most 12 requests in flight |
| Unknown security | Asked once, then once on each new day |

**Restarts:**
- After a restart every quote key is asked once more, one reference request each.
- Today's slow answers are preloaded from the `bbg_answers` table. These are the non-quote answers with a refresh of
  15 minutes or more.
- A new helper process asks for everything again.
- This is why restarts are rationed and why the desk wants **one update a day**.

**The hit cap:**
- `--max-hits` defaults to 400 000 a day, far above normal use. It is a runaway guard, not the desk's limit.
- When it is reached, refreshes and resyncs stop. **New keys are still sent** (`_send_queued` does not check
  `limit_reached`); only intraday bars refuse.
- The day's count is kept in kv `bbg.hits`, written every 30 s.

**Guards:**
- Users' formulas (personal calc sheets, input formulas) cannot call Bloomberg (`calc.py`, `inputformula.py`).
- Temporary table copies never open requests (`copies.py`).

**Commands that contact Bloomberg:** `python -m tto check-bloomberg` (about 9 probes) and `check-fx` (about 70).

**Where new requests come from** - review every one of these for cost:
- workbook formulas (BDP / BDH / BDS / BFXFORWARD / RTGET), through `marketdata/base.py`;
- history series definitions (`history.py`);
- FX series (`fx.py`);
- the quant FX pair setting;
- a new source code in EK_KAYNAK. That is a new ticker for each tenor row of that curve's list: OIS 18 rows, offshore
  11, XCCY 10. The new history series also come in their first window in one sync (see Rationing below);
- EK_FX roots and sources;
- a ticker point in Ayarlar → Eğri noktaları. Its cost is confirmed before saving;
- intraday bars (`quantviop.fetch_bars`, live only): a whole past day of one security per request, each asked once, at
  most `BAR_PER_REFRESH = 4` requests a refresh;
- a bond added to the desk's list (`Service.bond_list_add` → `_bond_facts`): the `bonds.FACTS` fields of each new
  ISIN.

## Pricing sources

**`EK_KAYNAK`** (book `tto`; `extras._tto_sources`, `SRC_LISTS`) holds the desk-wide source order: up to four codes per
curve in `B4:E6`, tried left to right. The workbook's own ticker (BGN) always comes last.

| Curve | Default | Rule | Cells patched to read the chosen ticker |
|---|---|---|---|
| OIS | GFOF | MID, else PX_LAST | `OIS_MAIN!B9:B26` (not rows 15 and 17), `AU13:AU14` |
| Offshore FX swap implied | ICPL | bid and ask from one source | `Forward!I6:I16` / `K6:K16` |
| XCCY | ICPL | bid and ask from one source | `Forward!D125:D134` / `F125:F134`, and `I17` / `K17` (the "12M" row is `TRYSAQ1`) |

- When nothing is live (replay), the choice falls to the workbook's ticker, and its saved value shows.
- The history uses the same lists: `history.source_lists` reads `EK_KAYNAK!B4:E6` (`history.SOURCE_DEFAULTS` only
  when the workbook has no EK_KAYNAK). After the list come the workbook's own tickers: for OIS the root plus
  `MASA!S171` ("Curncy" when empty), for offshore and XCCY `Forward!AO6:AO26`. A backup source fills only the days the
  main source lacks, laid onto the main source's level.
- Changing a list kicks the history (`set_sources` → `hist.kick()`).
- **EK_FX** (book `asw`) has its own two source cells, `B3` = ICPL and `C3` = BGN. It takes MID, else the middle of bid
  and ask.
- **EK_KAYNAK does not reach book `asw`.** The ASW sheet's OIS quotes (`ASW!C65:R65`, roots `C63:R63`) keep the
  workbook's own chain: GFOF MID, else GFOF PX_LAST, else the plain ticker's PX_LAST.

## History (`tto/history.py`)

**Series and groups.**
- A series id is `"<ticker>|<FIELD>"`, for example `"TRYSAQ6 ICPL Curncy|PX_LAST"`. One series per ticker and source.
- The groups are `ref | ois | off | xccy | dibs`, plus `sofr` and the quant groups.

**The sync loop runs every 900 s live.** The desk decided it stays at 15 minutes ("Böyle kalsın").

**Pacing** (kv `hist.fetch`):
- **Full range:** each series at most once a day.
- **After that:** only new days, from its last close − 3.
- **Series with no history:** asked once a day.
- **A timed-out full-range request:** still counts as asked for that day.

**Rationing (live only; replay asks everything at once):**
- `BACKFILL_PER_SYNC = 40` a sync covers only the series marked `backfill`: the quant package's series and
  `SOFRRATE Index` (the user approved: "Önerini yap"). The older part of the history's own series (below) waits in the
  same turn;
- VİOP contracts (`backfill: "viop"`) fill `VIOP_PER_SYNC = 15` a sync, beside those 40;
- an expired VİOP contract is asked once in full and never for new days. One that came back empty is asked again only
  after 7 days (`FINAL_RETRY_DAYS`);
- every other new series - the history's own groups `ref | ois | off | xccy | dibs`, marked "extend" by
  `quant.extend_for_quant` - gets its first window (`lookback_days`, the history setting) in full in one sync. The older
  part, up to two years (`quant.HISTORY_DAYS`), then comes in the 40-a-sync turn.

**The cost of tails:** every sync asks the new days of every series that has closes, except `SOFRRATE Index` (once a
day) and expired VİOP contracts (never). That is about (series with closes) × 96 BDH hits a day.

**`SOFRRATE Index`:** its new days are asked once a day, after 16:30 (`SOFR_AFTER`): a start before 16:30 does not ask,
and a restart the same day does not ask again ("1 kalsın"). A manual update (`History.request_sync`) asks again, still
only after 16:30. Its first two years come once, last in the 40-a-sync turn.

**`tto/fx.py` keeps its own older rule.**
- It runs live only.
- Each series is asked at most once in 20 h, recorded in kv `fx.hist.asked`.
- Empty series are retried after 6 h.
- "Tarihçeyi güncelle" forces it.
- It writes the same `hist_values` table, but keeps separate records.

**The store keeps the closes in memory too** (`hist_values`, `watch_closes`, `mpc_days`, `mpc_values`): write them only
through its methods (`hist_upsert`, `hist_delete`, `close_upsert`, `rename_closes`, `mpc_save`, `mpc_delete`), never with
SQL of your own (see [architecture.md](architecture.md#store-ttostorepy)).

## Desk database

To know what the desk really has - which series have closes, which inputs or overrides exist - read a **copy** of the
install's database. Never open the live one for writing. Never touch the running dashboard
(`0.0.0.0:1057`).

```python
import sqlite3
src = sqlite3.connect("file:<install>/data/tto.db?mode=ro", uri=True)   # read-only
dst = sqlite3.connect("<your scratch folder>/tto-copy.db")
src.backup(dst)                                                          # SQLite's online backup
```

- `<install>` is the folder beside the clones. On the user's machine it is `../ratetradingtto` from a clone.
- Useful tables:
  - `hist_values` (`series`, `day`, `value`);
  - `shared_inputs` and `user_inputs` (overrides by book and cell);
  - `kv` (`bbg.hits`, `hist.fetch`, …).
- The copy holds Bloomberg data and password hashes. Keep it in your scratch folder and never commit or send it.
- The install's `data/` may lag the office: the dashboard normally runs on the office computer.
