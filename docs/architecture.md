# Architecture

**What the program is.** A Python web app (Starlette + uvicorn) that does five things:
- loads the desk's Excel workbooks, imported as `models/*.json.gz`, into its own formula engine (`tto/xl`);
- adds sheets of its own (`tto/extras.py`, the `EK_*` sheets);
- calculates every user's own view on top of the shared one;
- serves the result as pages (`tto/views/*.json` plus `tto/static`);
- keeps its own data in SQLite (`data/tto.db`).

Market data comes from Bloomberg live, or from the values saved in the workbook (replay); see
[market-data.md](market-data.md).

Line numbers are as of commit a5e7ea7. Search for the name if a line has moved.

---

## Repository layout

| Path | What | In the installer bundle |
|---|---|---|
| `tto/` | the program | yes |
| `tto/views/*.json` | pages over workbook sheets: panels, inputs, tabs (schema in `tto/views/__init__.py`) | yes |
| `tto/static/` | the browser app (ES modules, `js/main.js` routes page ids) | yes |
| `tto/xl/` | the formula engine: importer, tokenizer, parser, compiler, functions, values, engine | yes |
| `tto/marketdata/` | Bloomberg (live, helper process), replay, the provider base | yes |
| `tto/data/` | replay extras (`replay_usd/asw/borsa/history.json`), catalogs | yes |
| `models/*.json.gz` | the imported workbooks - **what runs** | yes |
| `workbooks/` | the source `.xlsx` / `.xlsm`, read only by the import (`python -m tto import-workbook`, `tools/import_workbook.py`). `BBG_Borsa_Swap.xlsx` is encrypted: never write its password anywhere - the user runs its import (the password on their own command line, or `TTO_WORKBOOK_PASSWORD`). | no |
| `vendor/` | bundled wheels (`tto/bundled.py` falls back to them). `vendor/local` is never bundled. | yes |
| `tools/` | `make_bundle.py`, `bundle_stub.py` | yes |
| `kurulum/` | the single-file installer `tto_kur.py` and the identical `tto_kur.txt` | (it is the bundle) |
| `tests/` | pytest suite, `tests/e2e/e2e.js` (Playwright) | no |
| `README.md` | the user manual, in Turkish | yes |
| `docs/`, `CLAUDE.md` | these notes | no |

## Startup

| Step | What happens | Where |
|---|---|---|
| Launch | `run.bat` (opens Anaconda first when it finds one: `Scripts\activate.bat`, `TTO_CONDA`) / `run.sh` → `python -m tto`. Subcommands: `import-workbook`, `check-bloomberg`, `yonetici`, `check-fx`, `yedekten-don`. | `tto/__main__.py:280-291` |
| Run | `bundled.enable()` → logging → `create_app` → `uvicorn.run` | `__main__.py:130-153` |
| Mode | `--mode auto` (default), `live` or `replay`, or env `TTO_MODE`. Auto falls back to replay when Bloomberg is unreachable and sets only `mode_note`. | `service.py:367-380` |
| Host / port | Default `0.0.0.0:1057` (env `TTO_HOST`, `TTO_PORT`). Ports 5000 and 5001 are refused in code. | `config.py:8-9,108-115` |
| Data | `--data-dir`, else env `TTO_DATA_DIR`, else `<install>/data`. The DB is `tto.db`; logs and backups sit beside it. | `config.py:31,51,57` |
| Bloomberg | A helper process by default (`--bbg-inprocess` turns that off) | `service.py:562-593` |
| Other flags | `--max-hits` (400 000/day), `--no-history`, `--history-refresh` (900 s), `--backup-time` (17:30), `--idle-minutes` … | `__main__.py:38-75` |

## Request path

1. `tto/server.py`:
   - builds a Starlette app with about 150 routes;
   - `_SessionGate` attaches the user;
   - `/api/*` without a session is a 401, except `PUBLIC_API`.
2. A page: `GET /api/view/{id}` → `Service.view_future` → `_render_job` on the **engine thread** at VIEW priority →
   `_render` loops the view JSON's panels → `_panel` → `Renderer.table`.
3. The browser: `main.js` maps page ids to JS page classes. Any other id is a `ViewPage`, which calls
   `/api/view/<id>`.
4. Custom pages (no view JSON) are listed in `Service.nav`:
   - bugun, watch / heat, blotter, broker, trades;
   - eod, mpc, vol, spreads, settings;
   - fiyatlama, swaption, fx, fxvol, social, agenda, dibs-genel, kagit-fiyat, fiyat-yukleme;
   - the quant pages.

**JSON answers are gzip-compressed** for a client that takes gzip:
- **Where:** `handler` (`tto/server.py`) passes every answer through `compress_json`. Only a `JSONResponse` is touched:
  gzip at zlib level 6 from `GZIP_MIN` (1 KB) up, in a worker thread from `GZIP_THREAD_MIN` (128 KB) up, and
  `Vary: Accept-Encoding` on every JSON answer.
- **When:** `Accept-Encoding` names gzip (or x-gzip) without `q=0` (`accepts_gzip`).
- **Never:** the live stream `/api/events` (a `StreamingResponse`, not wrapped by `handler`), static files, downloads
  and images go as they are.
- **Why not Starlette's `GZipMiddleware`:** the three vendored sets differ. 0.44.0 (py38) compresses the event stream
  too (it would hold the live messages back); 0.49.3 excludes only `text/event-stream`; 1.7.0 excludes a list of types
  and compresses in threads. All three use level 9 and read any "gzip" in the header, `q=0` included.
- **Sizes** (desk copy of 17.11, 19.11): OIS 775 KB → 115 KB, Sinyaller 1.08 MB → 139 KB, Trend 787 KB → 107 KB.

**A typed input** goes `POST /api/inputs` → `Service.set_inputs` → `_set_inputs` on the engine thread at WRITE
priority:
- **Parsing:** `inputs.parse_input`; date shortcuts go through `shortcuts.date_shortcut`.
- **Formulas:** a value starting with `=` goes to `InputFormulas.accept`.
- **Storing:** a shared input goes to `engine.set_inputs` plus the `shared_inputs` table. A personal one goes to the
  `user_inputs` table plus `engine.set_user_inputs`.
- **Which cells are inputs** is declared by the view JSON's `inputs[]` (`Service._setup`), so editing a view JSON
  changes which cells can be typed in.

### Two-way tables (`tto/twoway.py`)

The desk, 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar bu şekilde olmalı
karışıklık olmaması için" - every value of a table's row can be typed; the one typed last stands, the others are worked
out from it. Built once, declared per table; FORWARD KOTASYON (USDTRY and EURTRY) is the first table on it
([desk-decisions.md](desk-decisions.md#forward-kotasyon-iki-yönlü-24112026)).

- **Declaration** (the view JSON's `"twoway"`, schema in `tto/views/__init__.py`): a group of same-shaped ranges of one
  sheet, its members. The cells at one place of every member are a **row-side** (a value date's bid).
- **Stores.** What is typed into a member is kept in its store: a blank range of the member's shape (FORWARD
  KOTASYON: hidden columns `AN:AS` of the same rows), declared as an input by `TwoWay` - not in `inputs[]`. The member's
  own cells are formulas: `IF(ISBLANK(<store>), <worked out>, <store>)`. At most one member keeps what is typed in its
  own cells (no store, **in place**): the table's input from before, whose formula default is the value the other stores
  give - so the values users typed there keep their meaning, with no move (FORWARD KOTASYON's spread, `D5:E14`).
- **Writes** (`Service._set_inputs`, through `TwoWay.expand`): a member's item goes to its store; once its value is
  taken (parsed, or a formula accepted) the row-side's other stores are cleared in the same write - **the last typed
  wins**. A value refused clears nothing. In one write (a paste) each row-side takes its last value; a blank beside it
  clears nothing; a row-side that is only blanked goes back to its default (all its stores cleared). `applied` counts
  what the user typed, not the stores the mechanism cleared.
- **Resets** (`/api/reset` with refs: "Kendi girdimi sil", "formüle dön"): a two-way cell stands for its whole row-side
  (`TwoWay.widen`). "Girdilerimi sıfırla", scenarios (save / load) and "Girdilerim" need nothing: the stores are
  ordinary inputs ("Girdilerim" names a store by its member's cell).
- **Formulas** (`inputformula.py`): accepted on the store; a cycle - a formula reading a member of its own row-side - is
  refused, and its reason names the member's cells (`TwoWay.said`), not the stores.
- **The page** (`Renderer.cell`, `twoway.mark`): a member is an input (`i`), modified (`m`) when its store holds a value;
  the anchor gets `an` (the members worked out from it), the others of an anchored row-side `ao` (the anchor's name and
  cell). The browser draws the anchor bold with ✎ (`grid.js` `cellClass` / `tipOf`, `app.css` `td.in.anchor`); the
  group's `note` goes under every table showing its members (`TwoWay.note_for`). `/api/cell` gives `input.twoway`.
- **Temporary copies** (`copies.py`): a member's store is the copy's input; a member typed in a copy writes its store and
  the copy's own empty values for the row-side's other stores (`TwoWay.copy_write`); Delete in a copy takes the
  row-side's values away (it follows the table again). Limit: the engine's copy layer cannot unset a value the table holds,
  so an in-place member typed in the table cannot go back to its formula in a copy - typing another member of that
  row-side there is refused with the reason.
- **Values typed over a member before it was two-way** ("Elle değer" at the member's own cell): its row-side's anchor,
  moved to the store once when the user's values are read (`TwoWay.adopt`, logged); such cells are never declared
  "Elle değer" inputs at the start (`_declare_saved_cells`).
- **Adopting it** (the module's docstring has the full list): the builder writes the stores and the members' formulas
  (the table's inverse formulas: one implementation, as `extras.fwd_outright` / `fwd_rate`); the view declares the group;
  the tests cover each member typed -> the others, exact round trips, the last typed wins, Delete, a paste, a scenario,
  the values typed before - and rows that move (`meetings.py`, `rowkeys.py`) must move the stores too.
- **Calculators of a workbook sheet** (`extras.TW_HUBS`: Hesaplayıcılar, DV01 Risk's scenario P&L): one `_BUILDERS` entry
  per calculator (a block the workbook changed is left out by itself). Each has a hub - the input its block computes
  from -: the other members keep their workbook formula wrapped in their store, the hub is its store, else the value the
  typed member gives (the block's formula solved), else its old default (the file's constant, or its formula default when
  it stays in place). A copyable calculator keeps every member in a store, so a temporary copy is never refused.
- **VİOP Target** (`extras._tto_viop_tw`): five members per row (stores `VIOP!AE:AI`), the target rate the hub. A member
  shown in only part of a table (Masa's TARGET strip shows Hedef değer alone) has a limit in that table's temporary copy:
  the copy cannot empty the row-side's other stores (`Copies.overlay` keeps the copy's own cells only), so a value typed
  there on the VİOP page shows through.

## Books and the formula engine

| Book id | File | Recorded (replay pins add-in cells to saved values) | Main sheets |
|---|---|---|---|
| `tto` | `models/tto.json.gz` | yes | MASA, OIS_MAIN, Forward, VIOP, C & R, TM_OIS, DİBS RV, Manuel Tahvil, Bulk Bond, DV01_RISK, Calculators, Motor |
| `sofr` | `models/sofr.json.gz` | yes | SOFR_FOMC |
| `borsa` | `models/borsa.json.gz` | no (`tto/data/replay_borsa.json`) | bu, Sheet1, Sheet2 |
| `asw` | `models/asw.json.gz` | no (`tto/data/replay_asw.json`) | ASW |

- **Cell address.** A cell is `rc = row * 16384 + col`, both 1-based (`tto/xl/model.py`). `divmod(rc, COLS)` gives
  `(row, col)`.
- **Evaluation is lazy and pull-based.** Every input, market key and the clock owns a dependency bit, and cached values
  carry a mask. A user's `Calc` reuses shared values whose mask does not touch that user's inputs (`xl/engine.py`
  docstring).
- **Templates are parsed once per process.** Cells filled from one formula share a template (`xl/tokenizer.to_template`,
  relative R1C1); the four books with the dashboard's own sheets have ~21 000.
  - `xl/parser.parse_template` keeps each template's AST (`functools.lru_cache`, `PARSED_KEPT` = 32 768, the most
    recently used; ~36 MB for all the books' templates) and gives the same AST to every caller: the books' spill scan,
    `formula_has_addin` / `formula_requests`, the compilers, the reverse reference index (`xl/refs.py`), `datecells`,
    `extras.formula_of`, `borsaspread`, replay's snapshot, users' formulas (`calc`, `inputformula`). Up to the reverse
    reference index, a start used to parse ~104 000 times; now 21 113 parses and 83 167 hits (19.11.2026, a copy of
    the desk database, replay, medians of 3 starts: service build 15.8 → 11.9 s, first page 19.6 → 15.1 s, warm-up's
    end 40.2 → 26.0 s, reverse reference index 17.8 → 10.3 s).
  - **An AST is read only.** Never append to a `func` node's argument list or an `array`'s rows: build a new tree
    (`calc._clip`). `tests/test_xl_parse.py` compares every kept AST with a fresh parse after a service has run.
  - Leaves (references, numbers, texts, names) are one shared tuple across ASTs (`parser._leaf`, `LEAVES_KEPT`).
  - Threads (the engine thread, `tto-refs`, request threads) may parse at once: a duplicate parse is harmless and only
    a whole AST is kept. A template that does not parse raises each time; nothing is kept for it.
  - `extras.SheetBuilder._template` is not cached: its (formula, row, column) calls are all different (the dashboard's
    sheets write each row's formula text, ~32 000 texts for ~2 000 templates). Its cost is `to_template` itself.
- **`Service._calc(user, book)`**:
  - no user → the shared `Calc`;
  - otherwise it loads the user's typed inputs (`_overlay`), catches up input formulas, and syncs the curve choice
    (`interp.sync`);
  - it returns the user's `Calc`.
  - **Derived inputs** (values worked out for a user, such as the PPK mirror) live in `engine.derived` and join only
    through `engine.set_user_inputs`. A `Calc(engine, shared, overlay)` built by hand does not see them (see
    [curves.md](curves.md#asw-fx-the-asw-sheet-repriced-on-offshore-rates)).
- **Array arithmetic has fast paths** (`tto/xl/values.py`, `tto/xl/functions.py`). Each keeps its general path, the
  code it had before, for everything else:

  | What | Fast path | General path |
  |---|---|---|
  | element-wise operators in array mode (`broadcast2`: `(A>=x)*(A<y)*B`, SUMPRODUCT's arguments) | `_broadcast_fast`, when the shapes line up: one kernel per operator (`_KERNELS`) per column or row. Numbers, blanks and logicals are worked inline (C loops when there are no blanks); text, errors and other values go to the scalar operator. | `_broadcast_rows` (any shape, `#N/A` padding) |
  | SUMPRODUCT | `_sumproduct_numbers`: one array, or columns / rows, of numbers only | `_sumproduct_general` |
  | COUNTIF | a number (or blank) criterion, counted inline | `_countif_general` (`make_criteria`) |
  | MMULT | `_number_block`: rectangles of numbers only | `_mmult_general` |

  - **Results are identical to the bit.** Every element gets the same IEEE operation, and sums keep their
    left-to-right order (`functools.reduce` over `operator.add`; never `sum()`, which compensates since Python 3.12).
  - **How this was checked:** after a cold sweep of every page on the desk copy of 17.11, all 234 311 values the
    shared calculations held were equal to f3434d1's, bit for bit (19.11). `tests/test_xl_fastpaths.py` compares each
    fast path with its general path.
  - **What it saved** (cold, replay, desk copy, medians of 4 on a loaded machine, 19.11): DV01 2.11 → 0.87 s, Günlük
    İşlemler 1.46 → 0.52 s, the header strip 1.98 → 1.43 s (most of the rest of the strip is compiling formulas). Per
    call on the workbook's own ranges, the four functions and the operators ran 1.5-4.7x faster.
  - TRANSPOSE has no fast path: its own time was negligible; its cost was its argument's array arithmetic.
- **One engine thread** (`EngineThread`) runs all engine work.
  - It is a priority queue: WRITE 0, HEADER 1, VIEW 2, BACKGROUND 3.
  - `s.et.call(fn)` runs inline if already on it, otherwise it blocks.
  - HTTP handlers never touch an engine directly.
  - A job on it never reads the history from SQLite: the store answers those reads from memory (see Store below). A
    query of many rows on it would hold every page and the alarm checks while a long calculation runs elsewhere.
- **The market loop** applies changed market keys on the engine thread. It then bumps `gen` and notifies listeners at
  most once a second (`service.py:768-798, 900-929`).

## `tto/extras.py`: the dashboard's own sheets

- **Shape of an addition.** Each one is a `(name, check, build)` triple in `_BUILDERS` (about `extras.py:3646`), keyed
  by book.
- **How `apply()` runs it.** `apply()` runs `check` first. If `check` raises, the addition is left out and listed in
  `Book.left_out`, and the rest of the program runs without it. Otherwise `build` runs.
- **Checks guard the workbook.** They state what the desk's workbook is expected to hold, so read them before stating
  what a cell does:
  - `_need_sheets`;
  - `_need_formula(sheet, addr, containing)`;
  - `_need_captions`.
- **The builder's tools.**
  - `SheetBuilder` writes values, formulas and styles.
  - `fill_down(addr, last)` is Excel's fill down: the cell's template (references relative to the row move with it),
    constant and look copied to the rows below - one template, no formula text parsed again (EK_TARIH's 100 rows).
  - `patch(addr, formula)` replaces a workbook cell's formula.
  - `recorded(addr, value)` gives a new Bloomberg cell the file's saved value, for replay.

| Sheet | Book | What |
|---|---|---|
| EK_TATIL | tto, borsa | USD (Fed) / EUR (TARGET2) holiday lists beside the TRY copy; joint FX calendars |
| EK_FWD | tto | forward quotes from OIS + spread, value-date rates, EURTRY (three builders) |
| EK_XAU | tto | gold forwards, VİOP gold calculator |
| EK_VIOP | tto | VİOP contract history for charts |
| EK_KAYNAK | tto | pricing-source order for OIS / offshore / XCCY (see [market-data.md](market-data.md#pricing-sources)) |
| EK_BULK | tto | 100-row bulk forward table; each row's Parite / Yön / Tutar / Karşı taraf (V..Y) for "İşleme al" (below, *Prices and rows as trades*) |
| EK_DIBS | tto | DİBS Trading: live T0/T1/T2 quotes, repo, "FX swap'a göre" fair values |
| EK_EVREN | tto | Tüm Kâğıtlar (the service writes its rows) |
| EK_CARRY | tto | carry along a chosen TLREF path |
| EK_IHALE | tto | Treasury auction bid pricing |
| EK_TARIH | tto | TOPLU TARİH ARASI FAİZ: MASA's date-to-date block (`MASA!B59:N70`) for 100 start / end pairs, the block's formulas carried to each row (`_tarih_formulas`), a row's quote (Kote %, N) → its spread over the chosen curve and Bootstrap (O:P), the helpers from R; under it the block's own box, a quote → its spread over each curve (`_tarih_back`, B109:I114, shown between the block and the table) |
| EK_VFRA | tto | VİOP target FRA. The target type "Fiyat" (a far price → its implied rate, the inverse of `VIOP!S331`) is an addition of its own, "VİOP hedef fiyatı" (`_tto_viop_price`), applied just before: it patches the target rate `VIOP!Q331:Q338` and the type list |
| EK_RET | tto | RET tenors on the OIS scenario curves |
| EK_PPK | tto | OIS · PPK's ways back: a meeting window's rate / an MPC spread typed -> the PPK step it prices (Broker Chat's implied step, cell for cell). Its typed and computed columns are bands of `meetings.TCMB` (row 3 + k: meeting slot k). Formula-only beside it: "FRA ikinci bacak" (`OIS_MAIN!U335:W438`) and, in book `sofr`, "FOMC pencere OIS'ten adım" (`SOFR_FOMC!AA72:AE83`, bands of `meetings.FED`) |
| EK_INTERP | tto, asw | the Bootstrap / PPK switch and the PPK cells (see [curves.md](curves.md#interpolation-bootstrap-murex-and-ppk-basamak)) |
| EK_FX | asw | the offshore rates ASW FX is built on |

Formula-only additions (no sheet) are in `_BUILDERS` too: OIS spot date, FX value dates, DV01, the calculators' ways back
written beside their blocks (the Forward sheet's points → rate, bond carry's price → repo `Forward!U71:V72`, Implied
Move's move → vol `Calculators!N44:O49`), the bonds' ways back (24.11.2026: a typed level -> the clean price, on the
workbook sheets' own free cells: `ASW!V:Y`, `DİBS RV!BK:BN`, SWITCH / PAIR's `DİBS RV!U:Z`, Manuel Tahvil's ISIN `B17`
with its helper block `AL17:AM36` and the inputs' defaults it gives; [desk-decisions.md](desk-decisions.md)) and others.
The module docstring's list of sheets is incomplete; `_BUILDERS` is the full list.

## Module map

| Group | Modules |
|---|---|
| Core | `config`, `__main__`, `server` (HTTP), `service` (about 9 300 lines: the application), `books`, `render`, `views/__init__`, `store` (SQLite), `inputs`, `inputformula`, `twoway` (two-way tables), `shortcuts`, `datecells`, `extras`, `meetings`, `rowkeys`, `calc` (personal calc sheets), `copies` (temporary table copies), `layout`, `auth`, `presence`, `bundled`, `xlsx` |
| Market data | `marketdata/{base,bloomberg,bbg_process,replay}`, `history` (daily closes, MPC history), `fx` (Spot / FX board, its own history rule), `fxvol` |
| Curves and pricing | `ppkcurve`, `interp`, `interpchart`, `curvepoints`, `aswfx`, `rvfair`, `borsaspread`, `pricing` (Fiyatlama), `swaption` (Swaption: TRY OIS swaptions on Fiyatlama's forward-start OIS, realized vol from the history; view only, `GET /api/swaption`), `bonds` (catalog) |
| Pages and features | `blotter` (Günlük İşlemler), `entry`, `brokerchat`, `tradehint`, `quotes`, `retfair`, `retflow`, `dibsgenel`, `kagitfiyat` (Kâğıt Fiyatlama, below), `fiyatyukleme` (Kâğıt Fiyat Yükleme, below), `bugun`, `watch`, `desk`, `deskalarms`, `tradebook` + `tradevalue` + `tradequant` (Trades), `prop` (the top bar's Prop panel, below), `volcarry` |
| Quant | `quant` (the runner) + `quantfam`, `quantmath`, `quantuniv`, `quantsira`, `quanttrend`, `quantml`, `quantbt`, `quantlevels`, `quantcons`, `quantcurve`, `quantopt`, `quantoptspot`, `quantlead`, `quantviop`, `quantintraday`, `quantpath`, `quantdibssw` |
| Ops | `ops` (log, backups, freshness), `progress` |

## Store (`tto/store.py`)

| Table(s) | Owner |
|---|---|
| `users`, `sessions` | auth, presence |
| `user_inputs`, `shared_inputs`, `scenarios` | `Service._set_inputs`, scenarios. `rowkeys.py` moves them (`Store.move_values`); `meetings.change` rewrites them in one `store.transaction()`. |
| `trades`, `blotter_snapshots`, `trade_templates` | **Günlük İşlemler** (the blotter), despite the name |
| `tradebook*` | the **Trades** page |
| `hist_values`, `mpc_days`, `mpc_values` | `history.py`; `fx.py` also writes `hist_values` |
| `bbg_answers` | today's slow Bloomberg answers, kept across a restart (`Service._keep_bloomberg`) |
| `ret_history`, `ret_fair_log` | RET editor, `retfair` |
| `broker_quotes` | `brokerchat` |
| `watch_closes` | `watch` |
| `feedback`, `chat`, `agenda*` | `desk` |
| `kv` | everyone, JSON values (table below) |

A second file, `data/quant_bars.sqlite3`, holds intraday bars (`quantintraday`, `quantviop`).

| `kv` key | Owner |
|---|---|
| `rowkeys.<list>[:<user>]`, `rowkeys.xau` | `rowkeys` |
| `bonds.rows`, `bonds.desk` | service / `bonds` |
| `calendar.parked` | `meetings` |
| `hist.settings`, `hist.fetch`, `mpc.archive`, `mpc.autoroll` | `history` |
| `bbg.hits` | service (the day's Bloomberg hit count) |
| `quant.*` | quant modules |
| `watch.items`, `watch.alarms`, `watch.open:<day>`, `watch.fired:<day>` | `watch` (`meetings` also moves them) |
| `migrated.*` | one-time migrations |
| `layout.<user>`, `calc.<user>`, `copies.<user>`, `pricing.<key>` | per-user state |
| `prop.limit:<user>` | `prop` (a user's daily loss limit: `{amount, ccy, at}`, `null` for none; only its owner reads or sets it) |
| `fx.*`, `ops.*`, `progress.runs`, `curvepoints.*`, `retfair.*`, `desk.*`, `bugun.dibs` | their modules |
| `kagitfiyat.widths`, `kagitfiyat.log` | `kagitfiyat` (the quote's width by maturity bucket, set by administrators; its changes) |
| `fiyatyukleme.list:<user>`, `fiyatyukleme.saved:<user>` | `fiyatyukleme` (a user's bonds by ISIN with their own spreads, the defaults, the mode, the last auction text, the fixed bonds with their bid / ask; the user's saved files of the last days) |
| `fiyatyukleme.labels`, `fiyatyukleme.auctions` | `fiyatyukleme` (desk-wide: an auction label's bond, named once; each bond's auction values by day and .t1 / .t2) |
| `fiyatyukleme.eurobonds` | `fiyatyukleme` (desk-wide: each Eurobond's Bloomberg facts, asked once an ISIN - never in `bonds.desk`) |

**The history's tables are kept in memory too** (`hist_values`, `watch_closes`, `mpc_days`, `mpc_values`):
- **Read once**, when the store opens (the desk's ~175 000 closes: ~0.5 s, ~14 MB), before any other thread uses it.
- **Every write of the store changes the copy** after its commit; inside a `transaction()` at its commit, and a rollback
  drops it. A value is kept as SQLite gives it back (in a REAL column an integer as a float, NaN as NULL, -0.0 as the
  library keeps it: 0.0 in 3.35); anything else is read back from the file.
- **Write these tables only through the store's methods**: a statement of your own would leave the copy behind.
- **Their reads never touch SQLite** (`hist_many`, `hist_series`, `hist_bounds`, `closes`, `mpc_days`, `mpc_values`)
  and take the copy's own lock (`_mem`), not the connection's.
- **Why:** Python's sqlite3 gives up the interpreter on every row it reads. While the quant fit, the backtest or the
  history sync holds it, each row waits ~5 ms: Eğri Hareketi (`Watch.heat`, on the engine thread) took 30–90 s, and the
  alarm checks and the quant's engine read queued behind it.
- **A damaged file** whose history cannot be read at the start still opens (`ops.check_database` says so); its history
  is then read from the file, as before.

## Pages

| View JSON | id | Title | Book / sheet |
|---|---|---|---|
| 10_masa | masa | Masa | tto / MASA |
| 20_ois | ois | OIS · PPK | tto / OIS_MAIN |
| 30_forward | forward | Forward | tto / Forward |
| 40_viop | viop | VİOP | tto / VIOP |
| 46_borsa | borsa | Borsa Swap | borsa / bu |
| 50_carry | carry | Carry & Roll | tto / C & R |
| 55_tmois | tmois | OIS · Nakit Akışı | tto / TM_OIS |
| 58_kagitlar | kagitlar | Tüm Kâğıtlar | tto / EK_EVREN |
| 60_dibs | dibs | DİBS RV | tto / DİBS RV |
| 60_dibslive | dibslive | DİBS Trading | tto / EK_DIBS |
| 61_asw | asw | DİBS ASW | asw / ASW |
| 62_manuel | manuel | Manuel Tahvil | tto / Manuel Tahvil |
| 63_ihale | ihale | Hazine İhalesi | tto / EK_IHALE |
| 64_bulk | bulk | Eurobond Kotaları | tto / Bulk Bond |
| 70_dv01 | dv01 | DV01 Risk | tto / DV01_RISK |
| 80_usd | usd | USD · FOMC | sofr / SOFR_FOMC |
| 90_calc | calc | Hesaplayıcılar | tto / Calculators |
| 98_motor | motor | Motor (administrators only) | tto / Motor |

Two kinds of panel key add the dashboard's own columns:
- the `ppk` key: PPK columns beside Bootstrap (`_fra_ppk_columns`, `_broken_ppk_columns`);
- the `append` keys (aswfx, rvfair, borsaspread, dibs_live, universe …): see `Service._panel`.

### The top bar's own panels

The top bar (`#top` in `tto/static/index.html`) is the same on every page; besides the page's title it carries popovers
that do not belong to a page: "● N çevrimiçi" (`presence.js`), "Hesap" (`hesap.js`), the curve mark (`paintInterp` in
`main.js`) and **Prop**.

- **Prop** (`tto/prop.py`, `tto/static/js/prop.js`; the desk's decision in
  [desk-decisions.md](desk-decisions.md#prop-panel-19112026)): a position-size calculator and the prop risk of a Trades
  tab, to look at only. `#prop-btn` opens `#prop-panel` under it; `stopProp` clears it at sign-out; a window of its own
  has no button.
- **Endpoints** (`Service.prop_*`, each needs a session; a `PropError` is a 400 with the Turkish reason):
  - `GET /api/prop` - the desk's FX pairs that have a price (`quant.fx_pair_list`, then the Spot / FX board's), each with
    its mid, and the user's limit;
  - `GET /api/prop/size?pair=&stop=&loss=&ccy=TRY|USD[&entry=]` - the calculator (`prop.size`);
  - `GET /api/prop/risk?scope=personal|desk` - the loss at every stop, the tab's "Günlük" K/Z, the limit, the room;
  - `GET` / `POST /api/prop/limit` - the user's own daily loss limit (`prop.limit:<user>` in kv).
- **Where its numbers come from.** Prices: `tradevalue.market` (request-free; cached 5 s, `MARKET_SECONDS`). K/Z: the
  tab's last "MTM yenile" as `tradebook.listing` returns it. Stops: `tradevalue.value` of each open trade on that market
  (Bootstrap, as the stop alarms), off the engine thread.

### Prices and rows as trades

Günlük İşlemler's entry is filled from other pages; nothing below saves a trade but the blotter's own endpoints.

- **A price right-clicked** ("İşlem gir", `tto/tradehint.py`): a table opts in with its `"trade"` hint (schema in
  `tto/views/__init__.py`). `client` sends the price cells with the table (`data.trade`); a right click posts
  `/api/trade/prefill` → `prefill` reads the clicked row's own cells on the engine thread → the browser's
  `ctx.openTrade(spec)` fills the form. A table of two pairs names each price's own pair in `"pairs"` (`pair_at`:
  TOPLU FORWARD's USDTRY and EURTRY columns side by side).
- **TOPLU FORWARD's rows** ("İşleme al"; [desk-decisions.md](desk-decisions.md), *TOPLU FORWARD → işlem*):
  the header button (`"action": "toplu-islem"`, `view.js` → `blotterentry.js` `bookBulkForward`) → `GET
  /api/blotter/bulk/toplu-forward` (`Service.bulk_from_forward`: the user's EK_BULK rows read on the engine thread →
  `entry.bulk_forward_paste`: a tab-separated paste, a line per row with a Tutar, its price to the last digit, and a
  "Satır" column the dialog does not read) → `openBulk(page, from)`: "Excel'den yapıştır" with its own preview
  (`/api/blotter/bulk/preview`) and save (`/api/blotter/bulk`, one transaction) → the browser then resets the kept rows'
  Tutar cells (`/api/reset`, found by "Satır").

### Kâğıt Fiyatlama

`tto/kagitfiyat.py` (page `kagit-fiyat`, the first entry of the Tahvil menu; `pages/kagitfiyat.js`; the bond card's block
`kagitblock.js`; the desk's decision and its numbers in
[desk-decisions.md](desk-decisions.md#kâğıt-fiyatlama-19112026), its curves in [curves.md](curves.md#fair-values)).

- **Endpoints** (`Service.kagit_fiyat` / `kagit_fiyat_widths`; a `KagitError` is a 400 with the Turkish reason):
  - `GET /api/kagit-fiyat` - `curve_rows` (the main table since 20.11.2026, Eğri fiyatı: every fixed coupon bond, bill
    and zero coupon bond of the desk's list - `bonds.listed` - and of the trading list: `market` today's price - DİBS RV's
    bid / ask middle or today's last trade, Tüm Kâğıtlar's for the rest -, `base` the bucket's base (`base_of`: the
    Nelson-Siegel now at the bond's cash flows, leave one out for a bond in the fit, and the OIS Bootstrap's zero rate at
    its maturity by the fair model's weights), `curve` the Eğri column - a fixed coupon bond's Nelson-Siegel, a bill's or
    zero coupon bond's base; `ns`, `ois`, `weights`, `base` its make-up -, `price` the answer with its label - "piyasa",
    "eğri + son fark (<source> <day>, <age>)" (any kind with a point: `src`, `day`, `age`), else by kind: a fixed coupon
    bond "eğri" (the curve), a bill / zero
    "eğri + akran farkı" (`peers`, `spread`: the median of today's market-priced bills' and zero coupon bonds' spreads to
    their bases in its bucket, the bond left out) or "eğri" (the base alone) -, each with `err` (`bp`, `n`: its rule's
    typical error) and the "tipik hata" text in `how`; `_curve_rows` first builds every row, then checks the rules on the
    market-priced rows (`validate` → `error_bands`: arithmetic on the rows' leave-one-out curve, no extra fit), then the
    peers, then each answer; `alt` the answer without the market (`tag`: the upload's mark), `diff` market − Eğri;
    `counts`, `others`: the floaters counted; the main table's Öngörülen / OIS'e / FX swap'a göre columns are drawn from
    the bond's details row of the same answer - `proj`, `asw` -, and a row without one carries `cols_why`: "—", said why)
    and `rows`, the trading list's details as before: fair, Öngörülen (`proj`: each horizon - 5 / 10 / 20 closes -
    its yield, price at the horizon's value date, bp, K/Z, model, record, line; `projection`: the horizons, the default,
    the measured table), the two ASW curves' fair values (`asw`: DİBS Trading's "OIS'e göre" / "FX swap'a göre"), quote,
    good levels, σ, backtest, market, context and the "how" line; `?isin=` one bond (the card's block; a bond of the
    desk's list off the trading list: its curve row alone; a floater of the catalog: `why`; an ISIN the desk does not
    have: 400). The horizon switch is the client's (all three come in one answer);
  - `KagitFiyat.curve_quotes(user, isins)` - Kâğıt Fiyat Yükleme's fallback: each bond's `alt` (the base + its own last
    spread; else a fixed coupon bond's curve, a bill's base + its peers' median spread or the base), its simple yield at
    its value date, its typical error;
  - `KagitFiyat.validation(user)` - the rules checked on the quotes now, the same check the typical errors come from
    (`validate`, `validation_table`, `error_bands`): every market-priced bond priced as if it had no price, leave one
    out (its curve the fit without it, out of its peers), errors per rule, bucket and kind group - the curve alone, the
    rule in use without history, its own last spread; no route (a check run on a database copy, numbers in
    desk-decisions);
  - `POST /api/kagit-fiyat/genislik` `{"widths": {"1y": 10, "3y": …}}` - administrators only (403 otherwise).
- **Threads.** `_read` (engine thread, short): DİBS RV's rows, the yields now (`quantcurve.read_engine`), each row's
  price ↔ yield inputs (P, CU, CW, DR, the cash flows), Bloomberg's bid / ask, the Broker Chat board, the TRY OIS
  Bootstrap, and each row's fair values on the two ASW curves (`rvfair.fair` + `Service._fair_cells`, as DİBS Trading).
  Everything else on the request thread:
  - the closes' part (`closes`): the bonds' and OIS tenors' closes from the store's memory (`hist_many`,
    `Service._swaption_closes`), each past day's neighbours' curve (a leave-one-out refit per coupon bond) and OIS curve,
    then each bond's spreads, σ, backtest and Öngörülen's windows (`fit_window`: the spread's AR(1) and β on OIS over the
    last 60 / 120 closes). Kept per history revision (and bonds, OIS calendar); each day's curves kept
    by what they are made of, so a new close builds that day only. The first build of a year of closes takes ~6 s (desk
    copy of 17.11: 246 days); a thread (`KagitFiyat.warm`, the dashboard's own server only - not with `--no-history` or
    in tests) builds it a minute after the start and again whenever the history changed;
  - the quotes now (`now_fit`): one leave-one-out refit per coupon bond on DİBS RV's yields, and each bond's roll-down
    on its curve to each horizon's value date (`neighbours`' `ahead`), kept per yields and horizon days; the curve of all
    of them (`full`), on which a bond off the trading list is read (`_curve_row`); a bond off the list whose series the
    history kept (`_off_closes`: "<ISIN> @<source> ISIN" / "<ISIN> ISIN") has its last spreads measured on its day's
    curve and that day's OIS zero rate (`_off_spreads`; each day's OIS curve kept with the day, `ois_curve`);
  - a bond's last known spread (`_points` → `pick_point` → `_own`; the one function the Fiyat column, the card, the
    upload's fallback, the fair and Öngörülen's start use): its points - the history's last close, the last auction the
    upload kept (`fiyatyukleme.KEY_AUCTIONS`), the last trade (DİBS RV's / Tüm Kâğıtlar's `AS`·`I` / `K`·`L` cells, the
    upload's Bloomberg answers kept in `fiyatyukleme.KEY_TRADES`), the last daily close kept (`kagitfiyat.closes`) - read
    once per answer (`_sources`: three kv reads), each measured against its day's curve kept in `_days` (today's against
    the bases now); the most recent wins, the same day trade > auction > close; the fair takes the most recent before
    today (`view` passes it to `_row` / `_projection`). Arithmetic only: no fit, no Bloomberg request;
  - the daily close recorder (`record_closes`): the warm thread, live mode only, every `WARM_EVERY` - after `CLOSE_AT`
    on a business day once, or at the workbook's day turn for the day before; Piyasa's price, yield and value date of
    every bond with one, kept per ISIN (`CLOSES_KEPT` days) in kv `kagitfiyat.closes`;
  - Öngörülen (`_projection`): the model of the bond's bucket and the horizon (`PROJECTION`, measured on the desk's history
    - desk-decisions), from the above and the OIS Bootstrap's forwards (`ois_move`); arithmetic only.

### Kâğıt Fiyat Yükleme

`tto/fiyatyukleme.py` (page `fiyat-yukleme`, right after Kâğıt Fiyatlama in the Tahvil menu; `pages/fiyatyukleme.js`; the
desk's decision and the conventions in [desk-decisions.md](desk-decisions.md#kâğıt-fiyat-yükleme-20112026), its Bloomberg
cost in [market-data.md](market-data.md#what-costs-hits-ttomarketdatabloombergpy)).

- **Endpoints** (`Service.fiyat_yukleme(user, what, body)`; each needs a session; a `FiyatError` is a 400 with the Turkish
  reason):
  - `GET /api/fiyat-yukleme` - the user's list (each bond's description, maturity, kind, spreads), mode, defaults, last
    auction text, the desk's labels, today's saved files;
  - `POST /api/fiyat-yukleme/ekle` `{"isins": "…"}` / `cikar` `{"isin"}` - the list (a bond off the catalog through
    `Service.bond_list_add`; refused in replay);
  - `POST /api/fiyat-yukleme/sabit` `{"isin", "bid", "ask"}` / `sabit-sil` `{"isin"}` / `sabit-yapistir` `{"text"}` - a
    bond's fixed bid / ask in the txt's unit (set or change / take off / Excel's rows pasted, `parse_fixed`): kept in the
    user's list state (`fixed`); the bond needs no catalog (`fixed_record`: the catalog's, a Eurobond's facts if held, else
    what its ISIN says); on Hesapla a row as it is (`_fixed_row`), never computed or asked of Bloomberg;
  - `POST /api/fiyat-yukleme/ayar` `{"mode"?, "defaults"?, "spreads"?: {isin: {bid, ask}}}`;
  - `POST /api/fiyat-yukleme/tanit` `{"label", "isin"}` - the desk names an auction label's bond (an empty ISIN forgets it);
  - `POST /api/fiyat-yukleme/hesapla` `{"mode": "ihale" | "bbg", "text"}` - every bond at t0 (İhale keeps the day's auction
    values desk-wide); `POST /api/fiyat-yukleme/cevir` `{"isin", "field", "value"}` - an edited cell's other half;
  - `POST /api/fiyat-yukleme/kaydet` `{"rows": [...]}` - the file's lines (kept per user and day); `GET
    /api/fiyat-yukleme/dosya[?gun=]` - the day's last file again (an attachment: ASCII, CRLF).
- **Threads.** Everything on the request thread but two short engine calls in BBG mode: `_read` (DİBS RV's `AS` / `I` / `BS`
  / `S` of the list's bonds on it, quantcurve's `read_engine` rows for the bond curve now, Tüm Kâğıtlar's sources) and,
  only when a bond falls back to OIS, `_read_ois` (Motor's market and the Bootstrap, as Kâğıt Fiyatlama reads them). The
  Bloomberg request (`Provider.reference`) blocks the request thread, never the engine's; each last trade it answers is
  kept per ISIN (`keep_trades` → kv `fiyatyukleme.trades`: day, price, source; a later trade replaces it) for Kâğıt
  Fiyatlama's last known spread. The bond curve now is DİBS RV ·
  Genel's fit (`DibsGenel.fit`, kept there); a past day's is refitted from the history's closes (store memory) with its τ
  held, kept per what it is made of.
- **Eğri fiyatı** (20.11.2026): in either mode, a yield-quoted row (fixed coupon, bill, zero coupon) left with no price
  (`_curve_fallback`) takes Kâğıt Fiyatlama's curve price (`KagitFiyat.curve_quotes`: its engine read, its closes' part and
  fit of the quotes now, all kept there - no curve code here): its simple yield at its value date as t0's, the row's
  spreads on it; `source` "eğri", `curve` its label, `mark` ("eğri fiyatı (son fark)" / "eğri fiyatı (akran farkı)" /
  "eğri fiyatı"), figures and `err`, `how` "<mark>: <why no price> → <how, its typical error in it>"; the answer's
  `curve` counts them. Price-quoted bonds, Eurobonds and fixed rows never reach it.
- **Eurobonds** (kind `euro`): records of their own (`FiyatYukleme.record` → kv `fiyatyukleme.eurobonds`), split off in
  `calculate` and priced by `_euro` in either mode; `Street` is the street-convention price ↔ yield (Excel's PRICE / YIELD),
  `anchored` ties it to Bloomberg's mid. `POST /api/fiyat-yukleme/cevir` takes a Eurobond's `settle` and `anchor` (the row's,
  from Hesapla).

## Row keys

Rows move between users' data when the desk's lists change. Three mechanisms keep values with their row's meaning; a
new feature that stores anything by cell, row or position must use one of them **and test the move**.

1. **`tto/meetings.py`: meeting calendars.**
   - It covers the PPK list (`OIS_MAIN!P10:P89`) and FOMC (`SOFR_FOMC!B74:B83`).
   - A row is a slot. `change()` moves every value of a meeting across users, scenarios, formulas and watch items in
     one transaction.
   - A band may sit on another sheet of the book, its k-th row the k-th slot: Motor's per-meeting inputs, `EK_PPK`'s
     rate / spread typed per window (from row 3). The watch anchors alarms to a meeting only on the list's own sheet.
   - Meetings that leave are parked in `calendar.parked`.
   - Typed meeting dates reach it through `_set_inputs`.
2. **`tto/rowkeys.py`: bond lists and VİOP gold contracts.**
   - It covers DİBS RV / EK_DIBS, ASW, Eurobond Kotaları (per user), Tüm Kâğıtlar, and the VİOP gold contracts.
   - Values follow the ISIN or contract: `rowkeys.<list>` records whose values each row holds.
   - The moves happen in `plan(old, new)` → `store.move_values`, at `before_write`, `start()` and `roll()`.
   - Key cells take no formula.
3. **`watch.py` anchors**: old watch items migrated to anchors at startup.

## Names that mislead

- **"calc" means five things:**
  - `Service._calc` (an engine `Calc`);
  - `tto/calc.py` (personal calc sheets);
  - `xl.engine.Calc`;
  - `/api/calc/{what}` (the calc-sheet API);
  - page `calc` (the Calculators sheet).
- **"Trades" means two things.** Table `trades` is Günlük İşlemler (the blotter); the Trades page is `tradebook*`.
- **The same sheet name is in two books:** `EK_TATIL` (tto, borsa) and `EK_INTERP` (tto, asw). `EK_FWD` has three
  builders.
- **Replay is per book.** `tto` and `sofr` are pinned to the file's saved values. `asw` and `borsa` get theirs from
  `tto/data/replay_*.json`.
- **`--data-dir`'s help says "./data"**, but the default is the install's `data/` folder, and `TTO_DATA_DIR` comes
  first.
