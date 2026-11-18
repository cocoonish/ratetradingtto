# Market data and Bloomberg

**The desk's Bloomberg terminal has a daily data limit, and it is a hard rule.** Going over it stops reference and
history data for the whole desk.

Before adding any ticker, field, history series or request loop:
1. State its daily cost: hits = securities × fields per request, plus the data points and how often it runs.
2. Get the user's OK.

Never restart a live dashboard over and over, and ask before a heavy BDH. Bloomberg data, screenshots of it and logs
never go into the repository or to an external service.

Line numbers are as of commit 7a53dfe.

---

## Modes

| Mode | Where values come from |
|---|---|
| **live** | blpapi on `localhost:8194`, services `//blp/refdata` and `//blp/mktdata`. It runs in a helper process (`marketdata/bbg_process.py`) unless `--bbg-inprocess` is given. |
| **replay** | The values saved in the workbook (`marketdata/replay.py`, `snapshot_from_model`). See [Replay](#replay). |
| **auto** (default) | Live if Bloomberg connects, otherwise replay. The fallback is silent apart from `mode_note`. |
| tests | Replay, plus fake terminals: `tests/fake_blpapi.py` (via env `TTO_BLPAPI_MODULE`), `fake_blpapi_live.py` (env `TTO_FAKE_BBG`), `fake_blpapi_broken.py` |

There is no Bloomberg on development machines other than the desk's. Agents work in replay and on the fake terminal
only.

## Replay

**Where replay values come from.**
- Every cell that is a single add-in call and has a value Excel saved is pinned to that value. This applies to books
  `tto` and `sofr` (`books.py`, `xl/engine.py:1272-1286`).
- `asw` and `borsa` read `tto/data/replay_asw.json` and `replay_borsa.json`.
- Past closes come from `tto/data/replay_history.json`.
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
| Quote fields (BID, ASK, MID, PX_LAST …) | One reference request for the first value, then a subscription. Streaming is free. |
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
  11, XCCY 10. The new history series also come in their first full range in one sync;
- EK_FX roots and sources;
- a ticker point in Ayarlar → Eğri noktaları. Its cost is confirmed before saving.

## Pricing sources

**`EK_KAYNAK`** (book `tto`; `extras._tto_sources`, `SRC_LISTS`) holds the desk-wide source order: up to four codes per
curve in `B4:E6`, tried left to right. The workbook's own ticker (BGN) always comes last.

| Curve | Default | Rule | Cells patched to read the chosen ticker |
|---|---|---|---|
| OIS | GFOF | MID, else PX_LAST | `OIS_MAIN!B9:B26` (not rows 15 and 17), `AU13:AU14` |
| Offshore FX swap implied | ICPL | bid and ask from one source | `Forward!I6:I16` / `K6:K16` |
| XCCY | ICPL | bid and ask from one source | `Forward!D125:D134` / `F125:F134`, and `I17` / `K17` (the "12M" row is `TRYSAQ1`) |

- When nothing is live (replay), the choice falls to the workbook's ticker, and its saved value shows.
- The history uses the same lists (`history.SOURCE_DEFAULTS`). A backup source fills only the days the main source
  lacks, laid onto the main source's level.
- Changing a list kicks the history (`set_sources` → `hist.kick()`).
- **EK_FX** (book `asw`) has its own two source cells, `B3` = ICPL and `C3` = BGN. It takes MID, else the middle of bid
  and ask.

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

**Rationing (live only):**
- new series fill `BACKFILL_PER_SYNC = 40` per sync (the user approved: "Önerini yap");
- VİOP contracts fill `VIOP_PER_SYNC = 15` per sync;
- expired VİOP contracts are asked once in full and retried after 7 days;
- a new series in an "extend" group that has no closes yet is **not** rationed: its first full range comes at once.

**The cost of tails:** every sync asks the new days of every series that has closes. That is about (series with
closes) × 96 BDH hits a day.

**`SOFRRATE Index`:** asked once a day after 16:30, never at startup ("1 kalsın").

**`tto/fx.py` keeps its own older rule.**
- It runs live only.
- Each series is asked at most once in 20 h, recorded in kv `fx.hist.asked`.
- Empty series are retried after 6 h.
- "Tarihçeyi güncelle" forces it.
- It writes the same `hist_values` table, but keeps separate records.

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
