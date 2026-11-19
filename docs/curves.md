# Curves

The dashboard has **two TRY discount curves** and they are not interchangeable:

- **TRY OIS** - onshore, TLREF.
- **Offshore TRY** - FX swap implied up to 9M, cross-currency swaps (XCCY) from 1Y.

The desk: "OIS ile ayrı bunlar, OIS farklı". A third object, **the ASW sheet's own curve**, is an OIS curve that the
ASW FX feature rebuilds from offshore rates. Always say which of the three you mean.

Line numbers below are as of commit 7a53dfe. Search for the name if a line has moved. The desk's decisions behind
this are in [desk-decisions.md](desk-decisions.md).

---

## The three curves

| | TRY OIS | Offshore TRY | ASW sheet's own curve (book `asw`) |
|---|---|---|---|
| **Instruments** | OIS 1M…10Y quotes. 15M and 21M are interpolated, not quoted. 1W / 2W are apart (`OIS_MAIN!AU13:AU14`). | `TRYI…` FX swap implied, 1W…9M. `TRYSAQ1…10` XCCY, 1Y…10Y. 1Y is `TRYSAQ1`. | 16 OIS tenors, `aswfx.TENORS`: 1M 2M 3M 6M 9M 1Y 18M 2Y…10Y. |
| **Tickers** | Roots in `OIS_MAIN!J9:J26` (`TYSO…`). Source order from `EK_KAYNAK` row 4: GFOF, then the plain ticker. MID, else PX_LAST. | Roots in `Forward!AO6:AO16` (`TRYI`) and `AO17:AO26` (`TRYSAQ1…10`). Source order from `EK_KAYNAK` rows 5–6: ICPL, then the workbook's BGN ticker. A row never mixes sources: it needs both bid and ask. | Roots in `ASW!C63:R63` (a shared input). Quotes in `C65:R65` = `BDP(root&" GFOF Curncy","MID")`. |
| **Convention** | Up to 3M: one period, simple ACT/365. Then quarterly ACT/365 par. | `TRYI`: one period, simple ACT/360, `DF = 1/(1 + r·d/360)`. `TRYSAQ`: annual ACT/360 par, bootstrapped as `DF_n = (1 − r·Σ τ·DF)/(1 + r·τ_n)`. The 1Y has one coupon, so it reads like the FX swap. | Up to 3M: one period, simple ACT/365. Then quarterly ACT/365 par. A quarter between two quoted tenors takes the quote linear in months. |
| **Built in** | `Motor!C88:I130`, 43 nodes: spot, 1M, 2M, 3M, then quarterly to 120M. Names `BOOT_GUN` (days, Motor C) and `BOOT_LNDF` (ln DF, Motor I). Quote copy at `Motor!A306:B321`. | `Forward!AJ123:AN143`: AJ label, AK days from the FX spot, AL rate, AM ln DF, AN slope. A node at every quote. Names `OFF_GUN` / `OFF_LNDF` / `OFF_SL` (`Forward!AK124:AN143`). Quotes: `TRYI` rows 8–16, XCCY rows 125–134 (C label, D bid, E mid, F ask, K days). | Days `AB65:BR65` ("D0…D120"), ln DF `BS65:DI65` ("L0…L120"), annuities `DJ65:EW65`. Same 43-node grid. |
| **Between nodes** | Par rates linear in months on Motor's grid, then ln DF linear in days. | ln DF linear in days. Past the last node, the last slope continues. | ln DF linear between nodes. |
| **Spot** | `OIS_MAIN!B2 = WORKDAY(TODAY(),1,TRY)`. TRY list only. | `Forward!I2 = WORKDAY(TODAY(),1,TRY+USD)`, the USDTRY spot. | `ASW!T65`. |
| **O/N** | TLREF (`Forward!AD123`, "TLREF, 365 → 360"). | Offshore O/N mid, ICAP (`Forward!AC123`). | - |

Notes on the offshore curve:
- The Forward sheet's "12M" offshore row (`Forward!I17/K17`) is patched to read `TRYSAQ1`'s bid / ask. `TRYI12M` has
  no price on either source.
- 18M is not a node of the offshore curve. EK_FX computes it from the curve, between the 1Y and 2Y nodes (below).

**Code that reads these curves:**
- `ppkcurve.read` / `ppkcurve.offshore_quotes`;
- `borsaspread.CURVES` / `read_curves`;
- `tradevalue` (`BOOT_*`, `bsp.read_curves(...)["off"]`);
- `interpchart.CURVES`.

### Who uses which curve

- **TRY OIS:**
  - pages: OIS · PPK (and its FRA lists - these are OIS only), Masa, Forward, DV01 Risk, Carry & Roll, VİOP,
    DİBS RV / Tüm Kâğıtlar, Manuel Tahvil;
  - the OIS mid of Borsa Swap;
  - Trades' OIS MTM;
  - Fiyatlama's OIS and FRA;
  - RET's "OIS" base.
- **Offshore TRY:**
  - MASA's broken-date block (FX forward, XCCY and O/N rows);
  - DİBS RV's own FX swap ASW (`BF:BJ`, "offshore ICAP");
  - the offshore mid of Borsa Swap;
  - Trades' USDTRY forwards, FX carry and FX options;
  - Fiyatlama's XCCY and FX forward;
  - RET's "offshore" base;
  - ASW FX's 18M point;
  - the interpolation chart's "Offshore" view.
- **ASW sheet's own curve:** DİBS ASW's "ASW" column, its fitted curve and history. With EK_FX's quotes in it, it is
  also the "ASW FX" column (next section).

---

## ASW FX: the ASW sheet repriced on offshore rates

**Code:**
- `tto/aswfx.py`;
- the EK_FX sheet (`extras._asw_fx`, `extras.FXC_ROOTS`);
- `Service._asw_fx_calc`, `_asw_fx_18m` and `_asw_fx_point` (about `service.py:5689-5792`).

**EK_FX** (book `asw`):
- **Layout:** rows 6–21, one per `aswfx.TENORS` entry. Columns: A tenor, B ticker root (an input), C ticker used,
  D FX rate %, E OIS %, F FX − OIS (bp), G / H the two sources' prices, I the rule, J days, K OIS zero.
- **Its own source list:** `B3` = ICPL, `C3` = BGN, kept apart from EK_KAYNAK but with the same defaults. It takes MID,
  else the middle of bid and ask.

**The kind of each tenor** (`aswfx.kind_of`):

| Tenor | Kind | Source |
|---|---|---|
| ≤ 9M | `FX_SWAP` | `FX_SWAP_MAX = 9`; `TRYI1M … TRYI9M` |
| 18M | `CURVE` | computed, never a quote |
| 1Y and ≥ 2Y | `XCCY` | `TRYSAQ1 … TRYSAQ10` |

**How a bond gets its ASW FX** (`aswfx.to_sheet`, then the sheet):
1. Each FX rate gives its discount factor, by its own convention.
2. That DF becomes the par quote, in the ASW sheet's own convention, that gives the same DF at the sheet's node day.
   Up to 3M this is closed form; from 6M it is solved on a replica of the sheet's formulas.
3. That quote replaces the OIS quote in `ASW!C65:R65`, as an overlay on the user's calculation.
4. The sheet's own formulas then price every bond. The result is the "ASW FX" column.

**The 18M point** (`Service._asw_fx_18m` → `aswfx.point_18m`):
- It is the offshore curve's DF at the ASW sheet's 18M node day.
- It is read on the viewer's own setting:
  - **Bootstrap**: `OFF_GUN` / `OFF_LNDF`, log-linear;
  - **PPK basamak**: the offshore PPK curve.
- It is shifted by (ASW spot − FX spot).
- Its par is 18M XCCY with coupons of 6M then 12M counted back from maturity (`aswfx.xccy_months`). The par goes into
  `EK_FX!D12`.
- Without both `TRYSAQ1` and `TRYSAQ2` there is no point, and 18M keeps its OIS quote.

**The rest of the ASW FX curve does not follow the PPK setting.**
- `_asw_fx_calc` builds `Calc(engine, shared, typed inputs + FX quotes)`.
- The per-user PPK mirror is a *derived* input (`engine.derived`), which only `engine.set_user_inputs` merges.
- So the ASW FX curve between nodes is the sheet's own (Bootstrap-like) for everyone. Only its 18M point follows the
  viewer's setting.
- The plain "ASW" (OIS) column does follow it: ASW row 65's ln DF reads `EK_INTERP!C` on PPK.

**What the gaps do:**
- A tenor without an FX price keeps its OIS quote (see [the fallbacks](#where-ois-and-offshore-meet)).
- A rate whose par cannot be solved becomes `#N/A`, and the curve stops there.
- With no FX rate at all there is no ASW FX: the fit says "EK_FX'te hiçbir vadenin fiyatı yok".

**History** (DİBS ASW "geçmiş", offshore):
- `aswfx.history_series` picks each tenor's series by its kind (`HIST_GROUP`):
  - group `off` (`TRYI1M…9M`) at ≤ 9M;
  - group `xccy` (`TRYSAQ1…10`) at 1Y–10Y.
- 18M is rebuilt from that day's `TRYSAQ1` and `TRYSAQ2` closes (`history_point`), Bootstrap only.
- A tenor without a close keeps that day's OIS quote.
- A day without any offshore close has no offshore ASW.

**Who reads ASW FX:**
- DİBS ASW: its ASW FX column, its chart, and EK_FX's FX zero rates.
- `rvfair`'s FX side (fit `a + b·t + c·t²` at `ASW!AW3:AY3`).
- DİBS RV · Genel (`dibsgenel`).
- DİBS Trading's "FX swap'a göre" columns (AA ASW FX, AB fair yield, AC fair price, AD rich / cheap).
- The bond card.

### DİBS RV `BF:BJ` is a different number

DİBS RV's own FX swap ASW columns (`BF:BJ`, book `tto`) discount on the Forward sheet's offshore ICAP curve. They are
not ASW FX:
- the TRY workbook cannot build EK_FX's curve;
- they are hidden by default (`Service.DEFAULT_HIDDEN_COLUMNS`, `"v/dibs/B3"`);
- `Service` labels which curve each FX column is on (about `service.py:6598`).

Two FX ASW numbers for the same bond is expected. Do not "fix" one to equal the other.

---

## Interpolation: Bootstrap (Murex) and PPK basamak

The setting is Ayarlar → "Eğri interpolasyonu", per user:
- it lives in `EK_INTERP!B2` in book `tto`;
- the service mirrors it into book `asw`'s `EK_INTERP!B2`;
- the default is **Bootstrap**, which is what Murex marks. Its numbers must not move.

**How PPK basamak is built** (`tto/ppkcurve.py`):
- TLREF is flat between PPK meetings: Motor's "MPC ima" path (`Motor!C4:L84`), with the meetings at
  `OIS_MAIN!P10:P89`.
- A flat overnight shift on each stretch between quoted maturities makes every quote reprice exactly.
- Offshore uses the same path shape, seen from the FX spot, plus a flat basis between the offshore quotes.
- A PPK curve that cannot be built falls back to Bootstrap, and the sheet and the badge say so.

**What a PPK user's setting changes** (`tto/interp.py`, extras' `INTERP_SHEET` section):
- Motor's node pars (`F89:F130`), so everything that reads `BOOT_*` follows: OIS pages, Masa, VİOP, DİBS RV.
- The offshore names `OFF_GUN` / `OFF_LNDF` / `OFF_SL`, which then read `EK_INTERP!I:K`.
- ASW row 65's ln DF.
- Trades' MTM, carry, coupons and P&L (`tradebook.FOLLOW_CURVE = True`). Desk close snapshots are kept on both curves.

**What stays Bootstrap:**
- Günlük İşlemler records;
- alarms, quant, history and any calculation without a user;
- ASW history rows;
- `retfair` (the desk calculation);
- ASW FX's sheet curve (only its 18M follows);
- the Bootstrap side of every two-way view (`Service._try_curves` reads the real Bootstrap).

**Two-way views** show both curves, the user's first:
- the FRA lists' PPK columns (`_fra_ppk_columns`);
- MASA's broken date (`_broken_ppk_columns`);
- the blotter's PPK figures;
- Fiyatlama;
- the interpolation chart (`tto/interpchart.py`).

**A new curve-dependent feature** must decide which of the three groups above it belongs to, and test both modes.

## Eğri noktaları (`tto/curvepoints.py`)

The desk's list of points each curve is built from, one list for OIS and one for Offshore.
- **The default list is today's points:**
  - OIS: `OIS_MAIN`'s quoted 1M…10Y;
  - offshore: Forward's `TRYI` 1W…9M and `TRYSAQ1…10`, plus "18M · XCCY · hesaplanan";
  - every reader then reads the workbook's own formulas, so no number moves.
- **PPK meetings are always in it** (read-only, from the calendar).
- **Administrators only** change it, and every change is logged.
- **A Bloomberg-ticker point** is a new live subscription: its cost is stated and confirmed before it is saved.
- **A list that differs from the default** is taken into the workbook by `interp.py`: Motor's node pars and the
  offshore names on Bootstrap, the PPK cells on PPK.
- **DİBS ASW does not follow the list.**

## Buckets (DV01 and FRA legs)

- `blotter.BUCKET_MONTHS = (1, 2, 3, 6, 9, 12, 18, 24, 36, …, 120)`.
- `blotter.bucket_split(m)` splits an OIS leg between its two neighbouring buckets, linear in months:
  - 15M → ½ 1Y + ½ 18M;
  - 21M → ½ 18M + ½ 2Y;
  - 27M → ¾ 2Y + ¼ 3Y;
  - 63M → ¾ 5Y + ¼ 6Y.
- Offshore and forward legs use the Forward sheet's own buckets (`blotter.split_weights`).
- Trades' DV01 table (`tradevalue.RISK_TENORS`, `tradebook.dv01_table`) uses both rules:
  - a spot swap entered as a tenor goes through `bucket_split`;
  - a dated, started or forward-starting swap, and a bond, goes through `split_weights` at its date, by days, against
    tenor ends rolled as the swaps' are (`tradevalue.risk_split`). A forward-starting swap is first turned into two spot
    swaps as Günlük İşlemler does a meeting-dated one (`blotter.mpc_summary_rows`).

## Fiyatlama (`tto/pricing.py`)

One instrument at any start and maturity, on both curves (the user's setting first), with DV01 per bucket by pillar
bump and NPV at a typed price.

| Instrument | Counted from | Convention | Coupon dates |
|---|---|---|---|
| OIS and FRA | OIS spot | quarterly ACT/365 | counted back from maturity, short period first (MASA's broken-date helper). A tenor quoted from spot lands on Motor's own quarters. |
| XCCY | FX spot `Forward!I2`, TRY holidays | annual ACT/360 | counted back from maturity: 18M = 6M + 12M, 2Y3M = 3M + 12M + 12M |
| FX forward | - | - | `F = S · DF_TRY(spot) / DF_TRY(value) / (1 + r·d/360)`, on the **offshore** curve and the **USD / EUR** OIS (`Forward!U:X`, `AA:AD`) - not TRY OIS |

## Trades (`tto/tradevalue.py`, `tto/tradebook.py`)

**TRY OIS:**
- Discounted on `BOOT_GUN` / `BOOT_LNDF`, or the user's PPK curve (`FOLLOW_CURVE`).
- ACT/365. One payment up to 3M, then quarterly coupons **counted back from maturity, the short period first**, paid
  at period end. The desk decided this on 19.11.2026, and it matches Fiyatlama and `MASA!BL193`.
- A trade entered as a tenor is dated on its grid from the start (`EDATE(start, m − 3k)`): whole quarters give Motor's
  own dates (`Motor!B88`).
- The float leg compounds TLREF fixings (`BISTTREF Index`).

**SOFR:**
- Discounted on the SOFR book's curve (`SOFR_FOMC!K48:M68`).
- ACT/360. Annual coupons counted back from the end.
- Modified following on SIFMA, paid two SIFMA days later.

**FX:**
- Discounted on the offshore curve.
- Without it, a USDTRY forward falls back to forward points, then to USD / EUR OIS. TRY OIS is never substituted.

**Carry and funding in the P&L** (desk decision 19.11.2026, [desk-decisions.md](desk-decisions.md)):
- An FX spot's carry is the roll to the next spot date at the Forward sheet's O/N rates: TRY **offshore** O/N (ICAP,
  `Forward!AC123`), SOFR, €STR. All of it is funding (`funding_1d`), so spot K/Z includes it. TLREF never stands in.
- A bond's funding is its dirty price at TLREF (the fixing, else the OIS curve's O/N); the rest of its carry is the
  bond's own, already in its dirty price.
- Swaps and options carry no funding: their value holds all of their carry.

## Fair values

| Model | Curve |
|---|---|
| `rvfair` OIS side | DİBS RV's OIS curve. Bond ASW is fitted `a + b·t + c·t²` against years from the OIS spot (`CA3:CC3`). |
| `rvfair` FX side | ASW FX, the ASW sheet on EK_FX's quotes. Fitted the same way at `ASW!AW3:AY3`. The dirty price at spot is carried with TLREF (`(L + N)·(1 + TLREF·days/365)`), as the sheet's formula does. |
| `dibsgenel` | OIS ASW and FX ASW through `rvfair`, plus an independent Nelson–Siegel zero curve of the bonds (`quantcurve`, `FIT_KINDS = ("fixed",)`). |
| `retfair` | Base OIS mid, VİOP mid, offshore mid or a blend; the default is OIS. Desk calculation, so no PPK. In a scenario view, the offshore and VİOP bases move by the OIS scenario's change. |

## Spot and value dates

| Pair / use | Spot | Holidays |
|---|---|---|
| USDTRY | T+1, `Forward!I2` | TRY+USD |
| EURTRY | T+2, `Forward!K2` | TRY+EUR, no USD rule |
| EURUSD value dates | - | USD+EUR |
| TRY OIS / money market / bonds / VİOP | `OIS_MAIN!B2` (T+1) | TRY only |

- The rules live in `extras.FX_SPOTS`, `pair_calendar` and `_tto_ois_spot`.
- Bloomberg's `SETTLE_DT` stays beside each spot as "Bloomberg valörü" (`Forward!J2`, `L2`; on OIS_MAIN too). It is
  shown, not used.
- The cells counted from the USDTRY spot: `MASA!P94:P99`, `MASA!C171`, `Forward!B200:B205`, `Forward!K130:K134`.
- `fx_shift` = FX spot − OIS spot. It moves the offshore curve onto the OIS curve's (or the ASW sheet's) day count
  (`ppkcurve`).

---

## Where OIS and offshore meet

This is the complete list as of 7a53dfe. **Do not add to it.** If a feature seems to need an OIS number on the offshore
side, ask the desk first.

| # | Where | What happens |
|---|---|---|
| A | `aswfx.to_sheet` (`aswfx.py` about 231–239) | EK_FX tenor with no FX price on either source keeps the ASW sheet's OIS quote. The rule text is `aswfx.RULES[OIS]`, "fiyat yok: OIS kotası". On the desk, 6Y–10Y always have `TRYSAQ` prices. In the replay file they don't (see [market-data.md](market-data.md#replay)). |
| B | `Service._asw_fx_18m` | 18M without `TRYSAQ1` / `TRYSAQ2`, or without a curve, keeps its OIS quote. |
| C | `aswfx.history_series` / service history rows | On a past day, a tenor with no offshore close keeps that day's OIS quote. |
| D | Curve names (`rvfair.FX_CURVE_TEXT`, `views/61_asw.json`) | The label says "…; fiyatı yoksa OIS", so the mix is visible. Wording only. |
| E | `rvfair` FX side | The dirty price at spot is carried with TLREF. This is the ASW sheet's own formula. |
| F | `ppkcurve` offshore PPK | The offshore PPK curve takes the OIS-implied MPC path's **shape**. Its level comes from the offshore quotes (a flat basis between them). |
| G | `retfair` scenarios | The offshore and VİOP bases move by the OIS scenario's change, `market + (scenario − reference)`. |

**Not fallbacks** (each curve keeps its own):
- `borsaspread` and `tradevalue` use a separate O/N per curve (offshore ICAP `Forward!AC123`, TLREF `AD123`).
- Trades' USDTRY forward never takes TRY OIS.

## Known differences - read before changing

1. **TRY OIS coupon dates: settled.** Until 19.11.2026 Trades put a broken date's short period last. The desk answered
   "İlk olan kısa olan", so Trades, Fiyatlama and `MASA!BL193` now all count back from maturity with the short period
   first. `test_trades_and_fiyatlama_date_a_broken_try_ois_alike` holds them together.
2. **ASW FX and PPK.** The ASW FX sheet curve stays Bootstrap-like for a PPK user; only its 18M follows the setting
   (see above). The plain ASW column follows the setting.
3. **Fallback A shows in replay only.** The replay file (the desk's Excel saved on 03.11.2026) has `TRYSAQ6–10` as
   `#N/A`. So replay-based tests and page comparisons exercise fallback A at 6Y–10Y, not the XCCY path there. The
   XCCY path is covered by `tests/test_aswfx.py`'s history tests and `test_each_rate_is_read_by_its_own_convention`.

## Before you change or claim anything about a curve

- **Name the curve:** OIS, offshore, or the ASW sheet's.
- **Read the cell's formula and the code**, not a test's output. `extras._need_formula` records what the workbook is
  expected to hold.
- **Compare curves on DF or zero rates.** Quotes of different conventions cannot be compared. An FX swap yield, an
  XCCY par and an OIS par at neighbouring tenors are not on one basis.
- **Convert before you reuse.** When one curve's instruments feed another sheet's bootstrap, convert each quote to that
  sheet's convention first (`aswfx.to_sheet`).
- **Don't confuse replay with the desk.** A gap in replay is a gap in the 03.11 file, not on the desk. Check the desk's
  history ([market-data.md](market-data.md#desk-database)).
- **Bootstrap numbers must not move.** Run a comparison with the setting on Bootstrap to prove it.
- **Rows move.** A feature that stores anything by cell or row must survive a PPK calendar change (see
  [architecture.md](architecture.md#row-keys)).
