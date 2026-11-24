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

**Cache first** (the desk, 24.11.2026). That day at 14:27 Bloomberg answered `responseError = { category = "LIMIT"
message = "Daily capacity reached." subcategory = "DAILY_CAPACITY_REACHED" }` with 195 148 hits counted by the dashboard;
the desk: "Bloomberg limiti doldu. Bunu nasıl halledebiliriz bir daha yaşanmaması için" and "Zaten çektiklerini cache
atıp daha fazla çekmemesi gerekliydi" ([desk-decisions.md](desk-decisions.md#bloomberg-and-data)). Now:

- **Every answer is kept for the day**, in memory and in the database (`bbg_answers`, every 30 s), and **a key answered
  today is not asked again today** - whatever its field -, unless the table below gives the reason.
- **Only what is used is asked again.** A key is "used" on a day when the engine reads it (a page's cell is worked out).
  At the day's change the service has every Bloomberg cell read again (`Service._reread_market`): what a page still
  reads is asked once on the new day; yesterday's dated keys (a range up to yesterday, an override of yesterday's date)
  and a bond gone from a list are never asked again. (Before, every key ever asked was refreshed for as long as the
  dashboard ran - each day added another set of dated keys.)
- **Why a key is asked again** is its policy (`policy_of`), counted under a kind on the status page:

| Request | Cost and when it is asked again |
|---|---|
| Quote fields (BID, ASK, MID, PX_LAST …, no overrides) | One reference request for the first value, then a subscription. Streaming is free. A field the stream does not deliver - a failed subscription (the office had 48 of 822), a field the subscription refuses, nothing 30 s after it started (`SILENT_AFTER`) - is polled: **with a value at most every 15 minutes** (`--price-poll`, `POLL_EVERY`) whatever its answer does (it was every 120 s while the answer kept changing), at twice the interval while it stays the same, up to 3 hours (`POLL_MAX`: an idle quote that answers its old price all day costs as little as an empty one); **without any value every 3 hours** (`POLL_EMPTY`); one that streamed and whose subscription failed since, hourly (`POLL_STOPPED`). The size of an order (`BID_SIZE` / `ASK_SIZE`) of a flowing stream never (a new order arrives as a tick). With `--no-stream` every quote field is polled so. A quote field with overrides is an ordinary BDP. |
| `CHG_NET_<n>` (DİBS RV's CK / CL) | Once a day, then **answer + (last price now − last price at the answer)**: Bloomberg's change is the last price less the close n days ago, and that close does not move in the day. Checked on the replay values: for every bond of DİBS RV `CH − CK` and `CH − CL` (`LAST_PRICE` less the change) is a clean three-decimal close - the change is measured from the price the stream carries; on the fake terminal the value worked out equals a fresh answer after every trade (`tests/test_bloomberg_cache.py`). Hourly when nothing streams the bond's last price. These and `LAST_TRADE_DATE` were asked every 60 s (~216 000 hits a day for 50 bonds). |
| `LAST_TRADE_DATE` (DİBS RV's CG, DİBS Trading's AH / AN / AT, Tüm Kâğıtlar' Y) | Once a day, then **today as soon as the stream shows a trade** - the last price changes or the day's volume grows, not the first value seen (the rule of `Service._note_trades`). Hourly when nothing streams. |
| `INTERVAL_LOW` / `INTERVAL_HIGH` up to today (DİBS RV's CM:CP) | Once a day, then the lower / higher of the answer and **the day's streamed low / high** (the field `MARKET_DATA_OVERRIDE` names: `PX_LOW` → `LOW`, `PX_HIGH` → `HIGH`, `PX_LAST` → `LAST_PRICE`). Bloomberg gives some in single precision (100.0999984741211 for 100.1): its own answer stands while the day's is within that. A range that ended is fixed (once a day). Hourly when nothing streams. |
| BDH ending today (a range up to `TODAY()`; the workbooks' own all end yesterday or earlier) | Once a day; **its today's point from the security's live quote** (when the answer has a point for today: the block keeps its shape, so the blocks beside it stay aligned). Otherwise hourly in the desk's hours. It was every 15 minutes. |
| BDH ending before today (EK_VIOP, VIOP, MASA, ASW, DV01_RISK blocks: up to `TODAY()-1` / `WORKDAY(TODAY(),-1)`) | Once a day (was every 6 hours, and each day's range a new key beside yesterday's). One hit per security, whatever the date span. |
| What moves in the day and nothing streams: `LAST_UPDATE`, other `CHG_` fields, `YAS_` fields without the price / yield they start from, BFXFORWARD's forward curve (`--bfx approx`) | At most hourly in the desk's hours (`HOURLY_EVERY`). |
| Every other BDP / BDS: static fields, `DAYS_TO_MTY`, `SETTLE_DT`, `INT_ACC`, `YAS_` with its price as an override … | **Once a day** (were 30 minutes and 6 hours). |
| Unknown security / field | Once a day (a maturity that did not exist yesterday may exist today). |
| Intraday bars | 1 per request; none past 70 % of the budget. |
| Batching | BDP 100 securities per request, BDS / BDH 50, at most 12 requests in flight. |

**The desk's hours (quiet hours).** Refreshes, polls and repairs only on the desk's days - week days that are not on the
TRY holiday list (Motor!A361:A523, `Watch.holidays`) - between `bbg_open` and `bbg_close` (08:00 - 19:00 by default; the
administrators change them in İzleme · Alarmlar → Masa alarmları → Ayarlar, `ops.settings`), in the computer's local time
(Istanbul on the desk's). Outside them **nothing is asked again** - a dashboard left on overnight or over a weekend
costs nothing then; subscriptions keep streaming; a key a page has never had is still asked (a first answer goes in any
hour). The service tells the provider (`set_desk_hours`) at the start, every 10 minutes and when the settings change; a
holiday added to the list counts from the next day. The history's syncs follow the same hours.

**Restarts.** Every answer of the day - quotes, what follows the stream and what Bloomberg did not know included - is
preloaded from `bbg_answers`: a restart the same day asks nothing it has (a quote's subscription brings it up to date for
free). A new helper process is given every answer the dashboard holds (`IsolatedBloombergProvider._spawn`); it used to
ask for everything again. The day's hits by kind (kv `bbg.hits` `kinds`), by key (table `bbg_usage`) and Bloomberg's
own limit (`limit`) are carried too.

**The day's budget and the caps:**
- **`--daily-budget`** (100 000 a day; env `TTO_BBG_BUDGET`; 0: none). Past **70 %** (`BUDGET_WARN`) only the first answers
  of keys a page needs and a user's one-off request (Hesapla) go out - no refresh, no poll, no repair, no history sync, no
  bars. At **100 %** nothing new: a first answer waits in the queue (`_send_queued` holds it) until the next day.
- **`--max-hits`** (400 000) stays the absolute stop: reaching it is as 100 % of the budget. (Before, it was the only cap,
  above Bloomberg's real limit, and `_send_queued` sent new keys past it.)
- **Bloomberg's own daily limit**: an answer of category `LIMIT` (or `DAILY_CAPACITY…`) on any request - a response, a
  security's or a field's error, a request failure, a bar request - stops every request until the next day. The values
  keep what they showed (no "#N/A"), a first answer waits, subscriptions keep streaming, the status says "Bloomberg günlük
  limiti doldu – yarın yeniden". One probe (one security × one field) an hour after the day changed, then hourly while
  Bloomberg still says so; kept for a restart. (Before, only a bar request understood it; every other request went on.)
- The day's count is kept in kv `bbg.hits` (`day`, `hits`, `kinds`, `limit`) and the count by key in `bbg_usage`, written
  every 30 s.

**Where the hits go** (the status window - the badge of the top bar -, `/api/market/usage`): today's hits in % of the
budget (warned at 70 %; administrators get a toast once a day), by kind - first answer, poll, static, daily, hourly,
history, Hesapla / user, resync, bars, probe -, the top 10 sheets (which workbook sheet asks for the key, from its cells;
the history's series, Hesapla and bars by name) and the top 10 fields; the quotes polled (with a value / empty / stopped)
and the keys the stream keeps current.

**Measured** (24.11.2026, a fake-terminal day of the four workbooks' keys as the engine forms them - the replay day -,
a simulated clock, the old code of beadeea against the new; the terminal like the office's: 448 of the 800 BIST swap
tenors unknown and the rest without a quote, 6 % of the other securities' subscriptions failing and 10 % of the other
quote fields silent, both with answers that move on every request, two event-queue overflows, ~730 subscriptions):

| Day | Before | After |
|---|---|---|
| Office: 08:00 - 19:00, started at 08:00 | 163 787 (first answers 5 194, the 60-second class 101 486, quote polls 48 794, 30-minute class 4 830, resyncs 3 160, static 210, BDH 113) | 15 292 (first answers 5 194, quote polls 9 120, resyncs 978) |
| ... with a restart at 13:00 | 174 751 | 15 246 |
| Left on round the clock (a whole day, 00:00 - 24:00) | 338 223 (~14 000 every hour, night included) | 14 494 (nothing from 19:00 to 08:00; at 08:00 the day's once: 2 261) |
| + the history's syncs (the fake terminal's ~217 series with closes; `tests/test_quant.py`'s live day) | + ~9 500 (08:00 - 19:00) / ~20 800 (round the clock) | + ~2 400 |

After, the hours of a working day: 08:00 ~5 400 (the first answers), then ~250 an hour (the moving quotes that do not
stream, every 15 minutes) and ~2 100 at 11:00, 14:00 and 17:00 (the quotes without a value: the largest share left -
`POLL_EMPTY` sets it), ~500 at an overflow. The office's own lists are longer than the replay's (DİBS RV 50 bonds
against 19, Tüm Kâğıtlar ~160 against ~96): their 60-second class alone was ~2.5 times the measured one, which is why
the desk saw ~195 000 by 14:27 - and their first answers will be a few thousand more than here. The whole day stays
under 20 000 (`tests/test_bloomberg_cache.py` keeps it so); every workbook BDH range ends yesterday or earlier
(`TODAY()-1`, `WORKDAY(TODAY(),-1)`, `WORKDAY(SPOTDATE,-2)`): they were refreshed every 6 hours (each day's new set
beside the older ones), now once a day.

**The event queue's repair** (`_resync_lost`): after an overflow, the values of the subscriptions Bloomberg named
(DataLoss) or, when it named none, of those that ticked in the 10 minutes before the queue filled and not since it cleared
(a quiet subscription lost nothing; one that ticked since is current) - at most 2 000 values a day (`RESYNC_BUDGET`, was
20 000; it re-asked every quote, ~4 500, at each overflow); not outside the desk's hours, not past 70 % of the budget.

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
  ISIN;
- **Kâğıt Fiyat Yükleme's BBG mode** (`tto/fiyatyukleme.py`, approved by the desk on 20.11.2026): on **Hesapla** only, one
  reference request of `LAST_PRICE` and `LAST_TRADE_DATE` for the bonds of the user's list that are **not** on DİBS RV's
  trading list - **2 hits a bond a Hesapla**, the answer kept **5 minutes** (`CACHE_SECONDS`: clicking again does not
  spend again). Never polled, streamed or refreshed: it goes through `Provider.reference` (below), not `get_bdp` (which
  would subscribe to `LAST_PRICE` and refresh `LAST_TRADE_DATE` every minute). The trading list's bonds read DİBS RV's
  own `LAST_PRICE` / `LAST_TRADE_DATE` cells (already asked for: no new cost). Replay asks nothing.
- **Kâğıt Fiyat Yükleme's Eurobonds** (the desk, 20.11.2026; priced from Bloomberg in either mode):
  - **once a new ISIN**, its facts: `NAME`, `SECURITY_DES`, `CRNCY`, `CPN`, `CPN_TYP`, `CPN_FREQ`, `DAY_CNT_DES`, `MATURITY`,
    `FIRST_CPN_DT`, `PENULTIMATE_CPN_DT`, `INT_ACC_DT`, `DAYS_TO_SETTLE` - 12 hits once, then kept desk-wide
    (kv `fiyatyukleme.eurobonds`), never asked again;
  - **on each Hesapla**, every Eurobond of the list: `PX_MID` and `YLD_YTM_MID` - **2 hits a Eurobond a Hesapla** (the
    cost the desk approved for BBG requests) - plus `PX_BID` / `PX_ASK` (2 more) only for a bond whose `PX_MID` is empty
    or that is set to Bid/Ask (below; one request for both);
    kept 5 minutes like the other BBG requests. Never polled, streamed or refreshed (`Provider.reference`, counted by
    `--max-hits`). The security is named by DİBS RV!N2's style (`"<ISIN> ISIN"` → `/isin/<ISIN>`), at its default pricing
    source. Replay asks nothing (a Eurobond cannot be added or priced there).
- **Kâğıt Fiyat Yükleme's Bid/Ask choice** (`tto/fiyatyukleme.py`, `SIDE_FIELDS`; **approved by the desk on 23.11.2026**): a
  bond of the user's list set to **Bid/Ask** starts its two sides from Bloomberg's bid and ask; the default, **Mid, asks
  nothing new**.
  - **On Hesapla** only, `PX_BID` and `PX_ASK` of the bonds set to Bid/Ask that are **not** on DİBS RV's trading list: one
    reference request for the off-list DİBS (BBG mode; named as for their last trade, whose request is apart) and one for
    the Eurobonds (either mode; the same request as an empty mid's sides). **2 hits a bond a Hesapla**, the answer kept
    **5 minutes** (`CACHE_SECONDS`). Never polled, streamed or refreshed (`Provider.reference`, counted by `--max-hits`).
  - No size fields are asked (`BID_SIZE` / `ASK_SIZE`): a DİBS whose bid equals its ask is read as no order standing
    (Bloomberg gives the last trade on both sides) and is priced from the mid.
  - The trading list's bonds read DİBS RV's own bid / ask (`K` / `L`, from `PX_BID` / `PX_ASK` and the sizes `XR` / `XS`
    the sheet already asks for): **no new cost**.
  - What the desk was told: "PX_BID and PX_ASK, 2 hits per bond per Hesapla, only for an off-list DİBS or a Eurobond set to
    Bid/Ask; DİBS RV bonds use what the dashboard already receives; answers reused for 5 minutes; e.g. 10 such bonds and 10
    Hesapla a day comes to at most 200 hits a day". Their answer, 23.11.2026: "Ok".
  - Replay asks nothing (the off-list bonds' sides fall back to the mid and say why).

**One-off reference requests** (`Provider.reference(securities, fields, timeout)`; `BloombergProvider.reference`, through the
helper process as `("ref", …)`): one `ReferenceDataRequest` per 100 securities, securities × fields hits counted like every
request (`--max-hits`: none is sent once the day's count is at the cap), on keys of their own (`("REF", security, FIELD,
call)`) that no workbook cell shares; nothing is kept, subscribed to, refreshed or asked again after a time-out. Like
`intraday_bars` it blocks: never call it on the engine thread.

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

**The sync loop runs every 900 s live** (the desk, 15.11: "Böyle kalsın") - but since 24.11.2026 (cache first) a series'
new days are asked **once a day** (yesterday's final close), then its **today's point comes from its live quote** when a page
has one (`Provider.quote`: the value the subscription keeps, no request), else its new days are asked **at most hourly**
(`TAIL_EVERY`; the time is kept with the series' record in `hist.fetch` - `tail`, `tail_at` -, so a restart within the
hour asks nothing). **Outside Bloomberg's hours** (`Service.bbg_open_now`: the desk's hours on the desk's days) a sync
asks nothing (`state["quiet"]`); "Şimdi güncelle" asks at any hour.

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

**The cost of tails:** the new days of every series that has closes (except `SOFRRATE Index`: once a day after 16:30, and
expired VİOP contracts: never) once a day, then at most hourly for those without a live quote - in Bloomberg's hours
(08:00 - 19:00) at most 11 times a day: (series without a live quote) × 11 BDH hits. It was (series with closes) × 96 a
day (every 15 minutes, round the clock): on the fake terminal's history (~217 series with closes) ~20 800 hits a day
left on, ~9 500 for 08:00 - 19:00; now ~2 400 (`tests/test_quant.py`'s live day).

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
