# TTO desk dashboard

A web dashboard for a TRY rates desk: OIS, offshore / XCCY, FX forwards, DİBS bonds, VİOP, RET, trades and quant
signals.

**How it works:**
- `tto/` is a Python server (Starlette + uvicorn).
- It loads the desk's Excel workbooks, imported as `models/*.json.gz`, into its own formula engine (`tto/xl`).
- It adds sheets of its own (`tto/extras.py`, `EK_*`) and calculates each user's view on top of the shared one.
- It serves pages from `tto/views/*.json` and `tto/static`.
- Live data comes from Bloomberg. Tests, agents and checks use **replay** mode: the values saved in the workbook.
  **Start anything yourself with `--mode replay`.** The default `auto` goes live whenever Bloomberg answers, and the
  computer the sessions run on has Bloomberg too.

`README.md` is the user manual, in Turkish.

## Read before you change

| You will touch… | Read |
|---|---|
| any curve, rate, ASW / ASW FX, FRA, PPK, MTM, Fiyatlama, fair value, spot date | `docs/curves.md` |
| behaviour the desk decided (conventions, products, process) | `docs/desk-decisions.md` |
| Bloomberg requests, history, pricing sources, replay | `docs/market-data.md` |
| where things live, the engine, pages, store, row keys | `docs/architecture.md` |
| tests, README counts, the installer, merging, pushing | `docs/testing-and-release.md` |

**When something changes:**
- When you change how something works or what it depends on, update the note in the same commit.
- A new desk decision goes into `docs/desk-decisions.md`, with their words and the date.

## Never

- **Ports 5000 and 5001**: never use them.
- **The user's running system**: never touch these:
  - the user's dashboard (`0.0.0.0:1057`), `127.0.0.1:1058`, the preview at `127.0.0.1:1079`;
  - the install folder (`../ratetradingtto`, beside the clones) and its `data/`. Read its database only through a SQLite
    backup copy (`docs/market-data.md#desk-database`). Never start the app there: it opens the live `data/tto.db`;
  - `D:\tto-test`, `D:\tto-yedek`, `../ratetradingtto-git`;
  - other sessions' worktrees.
- **Backup copies**: a copy of the install you start (no `.git`, its own `data/`) sends its backups' second copy to
  `D:\tto-yedek` by default (`config.backup_copy_default`), and after 17:30 it takes the day's backup at once. Start such
  a copy only with `--mode replay --backup-copy-dir "" --data-dir <scratch>`. Tests set `TTO_BACKUP_COPY_DIR=""`
  (`tests/conftest.py`).
- **Passwords**: never write the opening password of `BBG_Borsa_Swap.xlsx` anywhere - not in code, tests, docs, logs
  or messages. Never write or repeat any password.
- **Bloomberg data, screenshots of it and logs**: never put them in the repository or send them to an external service.
- **The Bloomberg daily limit**: no new ticker, field, history series or request loop without stating its daily cost
  and getting the user's OK. Don't restart a live server over and over. Ask before a heavy BDH.
- **Packages**: don't install any without asking.
- **Git**: no force-push. Merging and pushing are the main session's job (`docs/testing-and-release.md`).

## Curves: what must never be mixed up

The desk has two TRY discount curves. **They are not interchangeable** ("OIS ile ayrı bunlar, OIS farklı").

- **Offshore TRY** is FX swap implied `TRYI…` (1W–9M, one period simple ACT/360) plus XCCY `TRYSAQ1…10` (1Y–10Y,
  annual ACT/360 par).
  - 1Y is always `TRYSAQ1`. 6Y–10Y are `TRYSAQ6…10`.
  - It lives at `Forward!AJ123:AN143` (`OFF_GUN` / `OFF_LNDF`). Its node days are Bloomberg's `DAYS_TO_MTY` of each
    ticker (`Forward!G8:G21`; only 6Y–10Y, `K130:K134`, fall back to counting from `Forward!I2`), read as days from the
    USDTRY spot `Forward!I2`.
  - **Never take an offshore rate from OIS.** The only places they meet are listed in `docs/curves.md`; do not add one.
- **18M offshore is computed, never a quote.** It comes off the XCCY curve on the viewer's interpolation setting, with
  coupons of 6M then 12M counted back from maturity.
- **TRY OIS** is `TYSO…` quotes (GFOF, then the plain ticker), TLREF, ACT/365.
  - One payment up to 3M, then quarterly, counted back from maturity: on a broken date the **short period comes first**
    (Trades, Fiyatlama and `MASA!BL193` alike).
  - Motor's bootstrap (`BOOT_GUN` / `BOOT_LNDF`), counted from `OIS_MAIN!B2` (T+1 on the TRY list).
- **The ASW sheet has its own OIS curve** (`ASW!C65:R65`): up to 3M simple ACT/365, then quarterly ACT/365 par.
  - **ASW FX** is that sheet rebuilt from EK_FX's offshore rates.
  - Each rate is converted to the par quote, in the sheet's convention, that gives the same DF (`aswfx.to_sheet`).
- **Convert before you reuse.** When one curve's quotes feed another sheet's bootstrap, convert each quote to that
  sheet's convention first.
- **Compare curves on DF or zero rates** - never on raw quotes of mixed conventions.
- **Bootstrap is Murex's MTM: its numbers must not move.**
  - PPK basamak is a per-user second view (Ayarlar → Eğri interpolasyonu, default Bootstrap). It also drives that
    user's Trades MTM.
  - Alarms, quant, history and other shared calculations stay on Bootstrap.
- **There are two FX ASW numbers.** DİBS RV `BF:BJ` (offshore ICAP, hidden by default) is not ASW FX (EK_FX), which the
  DİBS fair values, Genel and the card use.
- **Buckets split linearly by months**: 15M = ½ 1Y + ½ 18M (`blotter.bucket_split`).
- **Spot dates:**
  - USDTRY is T+1 on TRY+USD (`Forward!I2`); EURTRY is T+2 on TRY+EUR (`Forward!K2`);
  - TRY dates use the TRY list only;
  - Bloomberg's `SETTLE_DT` is shown beside them ("Bloomberg valörü"). Three dates still use it: `VIOP!K3` (VİOP's
    implied-rate days), `ASW!C4` (→ `ASW!T65`, the ASW sheet's spot) and the gold spot date `EK_XAU!B9` when none is
    typed (`docs/curves.md`, spot dates).

## Stating facts

- **Read the cell's formula or the code** before saying where a value or a date comes from - not a test's output.
  `extras._need_formula` checks record what the workbook holds.
- **Replay is not the desk.** The replay data is the desk's Excel as saved on **03.11.2026**, and some of its cells were
  `#N/A` at that moment (e.g. `TRYSAQ6–10`). A gap in replay is not a gap on the desk.
  - To know what the desk has, read a backup copy of the install's database (`docs/market-data.md#desk-database`).
  - Say which source a statement comes from.
- **Name the curve** - OIS, offshore, or the ASW sheet's - in code, comments and messages.

## Rows move

A PPK or FOMC calendar change, a VİOP roll or a bond-list change moves users' data between rows. Anything stored by
cell, row or position must follow its row (`tto/meetings.py`, `tto/rowkeys.py`) and have a test for the move.

## Working here

- **Where sessions start.** Sessions usually start in the install folder, which is not this repository
  (`../CLAUDE.md`, outside every repository, points here). Work in your clone, and run every command below from the
  clone's root: the install folder has `tto/` and `tools/` too, so a relative command run there acts on the live install.
- **Roles.** The main session merges, runs the full suite and pushes `entegrasyon:main`, once all side sessions are
  done. Side sessions work on their own branch in their own folder beside the clones, and report the branch tip.
- **The installer.** Everything must install from GitHub's single `kurulum/tto_kur.txt` (`tools/make_bundle.py`). The
  integrator rebuilds it after any change to `tto/`, `models/`, `vendor/`, `tools/`, `README.md`, `requirements.txt` or
  `run.*`. `docs/`, `tests/` and this file are not in it.
- **One push for the day's requests.** One push carries all of the day's new requests: each new installer means an
  install and a restart at the office. A push that leaves `kurulum/` unchanged needs no install.
- **Python.** The code must start on Python 3.8 (the installer and `tto/__main__.py` refuse older; `vendor/` has a
  py38 set). The tests run on 3.9.5, so they don't catch syntax newer than 3.8.
- **Tests.** Use the clean venv, from the clone's root:

  ```
  env -u PYTHONPATH PYTHONIOENCODING=utf-8 /d/tto-genis-test/venv/Scripts/python -m pytest <files> -q -rfEs -p no:cacheprovider --no-header -o faulthandler_timeout=900 --basetemp=<scratch>/bt-<name>
  ```

  Run only the files your change touches; the integrator runs everything. The browser test and its pitfalls are in
  `docs/testing-and-release.md`.
- **Style.**
  - UI text in Turkish; code comments in English, in the codebase's style.
  - Keep existing DOM ids.
  - README (Turkish): describe your change in its section and in the test table. Its global counts are the
    integrator's.
- **The user.** The user is a TRY rates trader; their words are the spec. Quote them, and ask when a desk convention is
  unclear rather than assuming a generic market one.
