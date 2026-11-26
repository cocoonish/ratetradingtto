# Curves

The dashboard has **two TRY discount curves** and they are not interchangeable:

- **TRY OIS** - onshore, TLREF.
- **Offshore TRY** - FX swap implied up to 9M, cross-currency swaps (XCCY) from 1Y.

The desk: "OIS ile ayrı bunlar, OIS farklı". A third object, **the ASW sheet's own curve**, is an OIS curve that the
ASW FX feature rebuilds from offshore rates. Always say which of the three you mean.

Line numbers below are as of commit a5e7ea7. Search for the name if a line has moved. The desk's decisions behind
this are in [desk-decisions.md](desk-decisions.md).

---

## The three curves

| | TRY OIS | Offshore TRY | ASW sheet's own curve (book `asw`) |
|---|---|---|---|
| **Instruments** | OIS 1M…10Y quotes. 15M and 21M are interpolated, not quoted. 1W / 2W are apart (`OIS_MAIN!AU13:AU14`). | `TRYI…` FX swap implied, 1W…9M. `TRYSAQ1…10` XCCY, 1Y…10Y. 1Y is `TRYSAQ1`. | 16 OIS tenors, `aswfx.TENORS`: 1M 2M 3M 6M 9M 1Y 18M 2Y…10Y. |
| **Tickers** | Roots in `OIS_MAIN!J9:J26` (`TYSO…`). Source order from `EK_KAYNAK` row 4: GFOF, then the plain ticker. MID, else PX_LAST. | Roots in `Forward!AO6:AO16` (`TRYI`) and `AO17:AO26` (`TRYSAQ1…10`). Source order from `EK_KAYNAK` rows 5–6: ICPL, then the workbook's BGN ticker. A row never mixes sources: it needs both bid and ask. | Roots in `ASW!C63:R63` (a shared input). Quotes in `C65:R65`, the workbook's own chain: GFOF MID, else GFOF PX_LAST, else the plain ticker's PX_LAST. EK_KAYNAK does not reach them. |
| **Convention** | Up to 3M: one period, simple ACT/365. Then quarterly ACT/365 par. | `TRYI`: one period, simple ACT/360, `DF = 1/(1 + r·d/360)`. `TRYSAQ`: annual ACT/360 par, bootstrapped as `DF_n = (1 − r·Σ τ·DF)/(1 + r·τ_n)`. The 1Y has one coupon, so it reads like the FX swap. | Up to 3M: one period, simple ACT/365. Then quarterly ACT/365 par. A quarter between two quoted tenors takes the quote linear in months. |
| **Built in** | `Motor!C88:I130`, 43 nodes: spot, 1M, 2M, 3M, then quarterly to 120M. Names `BOOT_GUN` (days, Motor C) and `BOOT_LNDF` (ln DF, Motor I). Quote copy at `Motor!A306:B321`. | `Forward!AJ123:AN143`: AJ label, AK days, AL rate, AM ln DF, AN slope. AK is Bloomberg's `DAYS_TO_MTY` of each ticker (`Forward!G8:G21`, through `K125:K134` for XCCY); only `K130:K134` (6Y–10Y) fall back, when Bloomberg has none, to `WORKDAY(EDATE(I2, m) − 1, 1, TRY+USD) − I2`. A node at every quote. Names `OFF_GUN` / `OFF_LNDF` / `OFF_SL` (`Forward!AK124:AN143`). Quotes: `TRYI` rows 8–16, XCCY rows 125–134 (C label, D bid, E mid, F ask, K days). | Days `AB65:BR65` ("D0…D120"), ln DF `BS65:DI65` ("L0…L120"), annuities `DJ65:EW65`. Same 43-node grid. |
| **Between nodes** | Par rates linear in months on Motor's grid, then ln DF linear in days. | ln DF linear in days. Past the last node, the last slope continues. | ln DF linear between nodes. |
| **Spot** | `OIS_MAIN!B2 = WORKDAY(TODAY(),1,TRY)`. TRY list only. | `Forward!I2 = WORKDAY(TODAY(),1,TRY+USD)`, the USDTRY spot. | `ASW!T65` = `ASW!C4`: Bloomberg's `SETTLE_DT` of `TRY Curncy` (USDTRY), else `WORKDAY(TODAY(),1,TATIL)`. Not `OIS_MAIN!B2`. |
| **O/N** | TLREF, `OIS_MAIN!J2` (ACT/365). `Forward!AD123` restates it on ACT/360 ("TLREF, 365 → 360"). | Offshore O/N mid, ICAP (`Forward!AC123`). | - |

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
    DİBS RV / Tüm Kâğıtlar (and DİBS RV's ways back: a typed ASW / DM, a switch level -> the clean price; its two-way rows:
    a yield − OIS, ASW / DM or Z-spread typed in the table -> the clean price), Manuel Tahvil (its two-way results too);
  - the OIS mid of Borsa Swap;
  - Trades' OIS MTM;
  - Fiyatlama's OIS and FRA;
  - Swaption: Fiyatlama's forward-start OIS on the viewer's setting, the other curve's forward beside it; its realized
    vol from the history's closes, each past day on its own Motor bootstrap (Bootstrap);
  - RET's "OIS" base;
  - Kâğıt Fiyatlama's "OIS" base (below).
- **Offshore TRY:**
  - MASA's broken-date block (FX forward, XCCY and O/N rows);
  - DİBS RV's own FX swap ASW (`BF:BJ`, "offshore ICAP");
  - the offshore mid of Borsa Swap;
  - Trades' USDTRY forwards, FX carry and FX options;
  - Fiyatlama's XCCY and FX forward;
  - RET's "offshore" base;
  - ASW FX's 18M point;
  - the interpolation chart's "Offshore" view.
- **ASW sheet's own curve:** DİBS ASW's "ASW" column, its fitted curve and history, and its "ASW → temiz fiyat" (a typed
  ASW's clean price: on this curve, never on ASW FX's) - as the ASW typed in the table itself (two-way). With EK_FX's
  quotes in it, it is also the "ASW FX" column (next section).

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
5. A row whose ASW (or dirty price) the user typed in the table (two-way) keeps, in that calculation, the clean price
   the typed value gives on the sheet's own OIS curve - its ASW FX is worked out at that price, never held at the typed
   OIS ASW (`Service._twoway_pins`; the offshore history's live row likewise).

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
- `Service` labels which curve each FX column is on (about `service.py:6601`).

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
- Motor's node pars (`F89:F130`), so everything that reads `BOOT_*` follows: OIS pages, Masa (its date-to-date block's
  Bootstrap row, and EK_TARIH's, which reuses the block's formulas - with the spreads of a quote typed there: the
  block's box over `MASA!D62:D68`, a row's Kote % over the row's rates), VİOP, DİBS RV.
- The offshore names `OFF_GUN` / `OFF_LNDF` / `OFF_SL`, which then read `EK_INTERP!I:K`.
- ASW row 65's ln DF.
- Trades' MTM, carry, coupons and P&L (`tradebook.FOLLOW_CURVE = True`). Desk close snapshots are kept on both curves.

**What stays Bootstrap:**
- Günlük İşlemler records;
- alarms, quant, history and any calculation without a user;
- ASW history rows;
- `retfair` (the desk calculation);
- `kagitfiyat` (Kâğıt Fiyatlama's OIS base, now and on past days);
- ASW FX's sheet curve (only its 18M follows);
- the Bootstrap side of every two-way view (`Service._try_curves` reads the real Bootstrap).

**Two-way views** show both curves, the user's first:
- the FRA lists' PPK columns (`_fra_ppk_columns`);
- MASA's broken date (`_broken_ppk_columns`);
- the blotter's PPK figures;
- Fiyatlama;
- Swaption (`tto/swaption.py`: the forward and annuity both ways, the option on the viewer's curve);
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
- `blotter.bucket_split(m)` splits an OIS leg **entered as a tenor** between its two neighbouring buckets, linear in
  months:
  - 15M → ½ 1Y + ½ 18M;
  - 21M → ½ 18M + ½ 2Y;
  - 27M → ¾ 2Y + ¼ 3Y;
  - 63M → ¾ 5Y + ¼ 6Y.
- `blotter.split_weights` splits by days between the two nodes around a date:
  - FX forwards (kind `fwd`) on the Forward sheet's own buckets (`Günlük İşlemler!O6:O19`: the RET tenors' days,
    `Forward!U33:U47` without TN);
  - a meeting-dated OIS swap, first turned into two spot swaps, on the summary's tenors (`blotter.mpc_summary_rows`).
- Trades' DV01 table (`tradevalue.RISK_TENORS`, `tradebook.dv01_table`) uses both rules:
  - a spot swap entered as a tenor goes through `bucket_split`;
  - a dated, started or forward-starting swap, and a bond, goes through `split_weights` at its date, by days, against
    tenor ends rolled as the swaps' are (`tradevalue.risk_split`). A forward-starting swap is first turned into two spot
    swaps as Günlük İşlemler does a meeting-dated one (`blotter.mpc_summary_rows`).

## A spread over a TRY OIS curve, and the way back

- **The desk's spread is added to the ACT/360 simple rate** of the chosen TRY OIS curve: MASA's date-to-date block
  (`MASA!F62:F68 = D + I60/10000`, its note `B69`), EK_TARIH's "+ spread (360)", the forward quote matrices (`EK_FWD`,
  spot → value date).
- **The ways back read a quote in the same convention:** the block's box (`EK_TARIH!C110`) and the Forward page's
  FAİZ → SPREAD take an ACT/360 simple rate, so the spread found, typed back, gives the quote.
- **The forward quote matrices are two-way** (24.11.2026, `tto/twoway.py`): a TRY % typed into one is read as that
  ACT/360 simple rate too (spread = TRY − OIS of the chosen curve); a puan or fwd typed gives the TRY rate the outright
  implies on the matrix's own spot, USD / EUR rate and days (`extras.fwd_rate`, the exact inverse of
  `extras.fwd_outright`) - no curve is read for it.
- **EK_TARIH's Kote % is read in the basis the table shows** (ACT/360, ACT/365 or O/N (360)); its difference to a curve is
  in that basis too. Only with ACT/360 is it the row's spread (desk decision 24.11.2026).
- **Two-way** (24.11.2026, [desk-decisions.md](desk-decisions.md#tarih-arası-ve-ois-tabloları-iki-yönlü-24112026)): a
  value typed in MASA's block (a curve's rate + spread, TRY % of a leg, a forward, points, forward-forward points …) gives
  the block's one spread `I60` - each formula is linear in the spread, so its exact inverse is closed form (a forward
  through its leg's TRY rate: ((F/spot)·(1 + USD·g/360) − 1)·360/g; the start leg at the OIS spot does not depend on the
  spread and gives none) - and every reader of `I60` follows. An EK_TARIH row's "+ spread (360)" typed gives its spread over
  the chosen curve's ACT/360 rate, whatever basis the table shows. The TRY side stays the block's TRY OIS curves + spread
  (never offshore); the forwards' USD side the Forward sheet's USD OIS, as before.

## Fiyatlama (`tto/pricing.py`)

One instrument at any start and maturity, on both curves (the user's setting first), with DV01 per bucket by pillar
bump and NPV at a typed price.

| Instrument | Counted from | Convention | Coupon dates |
|---|---|---|---|
| OIS and FRA | OIS spot | quarterly ACT/365 | counted back from maturity, short period first (MASA's broken-date helper). A tenor quoted from spot lands on Motor's own quarters. |
| XCCY | FX spot `Forward!I2`, TRY holidays | annual ACT/360 | counted back from maturity: 18M = 6M + 12M, 2Y3M = 3M + 12M + 12M |
| FX forward | - | - | `F = S · DF_TRY(spot) / DF_TRY(value) / (1 + r·d/360)`, on the **offshore** curve and the **USD / EUR** OIS (`Forward!U:X`, `AA:AD`) - not TRY OIS |

**Each DV01 bucket shows its quote** (24.11.2026, [desk-decisions.md](desk-decisions.md#fiyatlama-kovaların-kotası-24112026)):
the market quote the bucket's +1 bp moves, the rate its hedge trades at (`Curves.pillars`; the bucket row's `quote`).
- **TRY OIS and FRA:** the OIS quote Motor's bootstrap reads, `Motor!A306:B321` (= `OIS_MAIN!B9:B26` without 15M and
  21M; 1Y is `OIS_MAIN!B14`). On a desk's list that differs from the default: the list's points. ON / 1W / 2W have none.
- **XCCY and FX forward:** the offshore quote (`ppkcurve.offshore_quotes`): `TRYI` mid `Forward!J8:J16` (one period,
  simple ACT/360), `TRYSAQ` mid `Forward!E125:E134` (annual ACT/360 par). Never an OIS quote.
- **One column for both curves.** Bootstrap gives every quote back at its own maturity by construction, PPK basamak by its
  calibration (1e-12). On the replay day the worst miss over the 16 OIS and 14 offshore quotes is 3·10⁻¹⁰ bp.

**The ways back** (24.11.2026, [desk-decisions.md](desk-decisions.md#fiyatlamanın-tersi-ve-fx-opsiyonun-prim-volü-24112026)):
- **An NPV or an upfront typed gives the level** that prices to it - `pricing.level_for`, `value`'s exact inverse: a
  swap K = ((DF(start) − DF(end)) − NPV / (side · N)) / Σ τ·DF, an FX forward K = F − NPV / (side · A · DF(value date)).
  It is solved **on the viewer's own curve** (Bootstrap or PPK basamak, the setting's), the other curve's level for the
  same NPV beside it. The NPV, the DV01 buckets and price − mid are then at that level, on both curves, as with that
  level typed. NPV $ is TL at `OIS_MAIN!D2`; an upfront is NPV / nominal in bp, + in the trader's favour.
- **Toplu fiyatlama** reads every line off the page's own curves (`Curves`): no bootstrap, no bump and no calibration
  for a line. Each instrument stays on its own curve - TRY OIS and FRA lines on OIS, XCCY and FX forward lines on
  offshore - and a line's DV01 is its size's (annuity rule), not the buckets'.

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
- Discounted on the offshore curve. Trades has no FX forward product (`tradevalue.PRODUCTS`): its USDTRY forwards are
  an option's forward and the spot roll's fallback (`Market.forward`), the offshore curve with the USD OIS.
- Without the offshore curve (or the USD OIS), a USDTRY forward has no value ("forward yok"). Trades keeps no USDTRY
  forward points (`tradevalue.market` skips them), and the OIS step needs both currencies' OIS (`Market.rates`: USD and
  EUR only). TRY OIS is never substituted. Forward points, then USD / EUR OIS or a cross through USD, are other pairs'
  fallbacks.

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
| `kagitfiyat` | Kâğıt Fiyatlama: two bases, each plus the bond's spread to it at the last close, weighted by maturity - the **neighbours' curve** (`quantcurve`'s Nelson-Siegel of the trading list's other fixed coupon bonds, leave one out) and **TRY OIS**: the Bootstrap's zero rate at the bond's maturity from the OIS spot, compounded once a year. Now: the workbook's Bootstrap (`Service._try_curves`' `boot`, the true one whatever the viewer's setting); a past day: Motor's bootstrap of that day's closes (`swaption.day_curve`). Desk calculation: Bootstrap only, no PPK. |

**Kâğıt Fiyatlama has no offshore base.** On the desk's history the bonds moved about half as much as the offshore curve
(β ≈ 0.45) and offshore was never the best base at any maturity (desk-decisions, "Kâğıt fiyatlama"). This is about that
page's fair only: the ASW FX fair values (`rvfair`'s FX side, DİBS Trading's "FX swap'a göre", Genel, the card) stay as
they are, and the page shows them beside its fair ("OIS'e göre" / "FX swap'a göre": `rvfair`'s, not recomputed).

**Öngörülen's OIS move** (M4, `kagitfiyat.ois_move`): on the TRY OIS Bootstrap (now: the workbook's; in the measurement:
each day's Motor bootstrap of its closes), the forward zero rate from the horizon (today + H TRY business days, counted
from the OIS spot in calendar days) to the bond's maturity less today's zero rate for the same remaining life, both
compounded once a year (ACT/365) - the base's move beyond the roll-down the other models already have. OIS only; no
offshore, no PPK.

## Meeting steps from a rate

The ways back of 24.11.2026 ([desk-decisions.md](desk-decisions.md#ways-back-rate--ppk--fomc-step-an-fras-other-leg-24112026)).

**TRY OIS - a meeting window's rate → the PPK step** (`EK_PPK`, Broker Chat's `Service._mpc_implied`):
- A window of 'MPC OIS' runs from a meeting's effective day to the next one's (`OIS_MAIN!B84:C99`, Motor's `C5:C21` from
  the OIS spot: the business day after the decision, `Motor!G`). Its market rate is simple ACT/365 off the table's ln DFs
  (`D` = (DF start / DF end − 1)·365 / days, `BK` / `BL` read on `BOOT_*`): **the viewer's curve** - Bootstrap, or a PPK
  basamak user's.
- **O/N equivalent: TLREF's, as the MPC ima model compounds it** (the desk, 25.11.2026: "B";
  [desk-decisions.md](desk-decisions.md#ppk-adımı-tlref-iş-günlerinde-bileşik-25112026)). Only business days of the TRY
  list (`Motor!A361:A523`, Ayarlar → Tatiller) accrue, each for the calendar days to the next business day (1; 3 over a
  weekend - Friday's rate for three days in one step -; more over a holiday), ACT/365. Over a window of d days whose
  business days are g apart that is Π (1 + x·g), x = O/N / 365; the model (`Motor!L`, `OIS_MAIN!BJ`, `ppkcurve.StepCurve`)
  takes its log to the second order, and so does the step:
  - ln(1 + r·d/365) = d·ln(1 + x) − W·x², **W = Σ g(g − 1)/2** - the window's weekend / holiday term, the model's own:
    Motor's Pcum (its daily calendar `Motor!F528:F4228`, days from the OIS spot; `Motor!J` at a meeting's effective day,
    `J4` = 0 at the spot) at the window's end − at its start (`extras.ppk_term`, `OisMarket.mpc_term`);
  - rate → O/N: that equation solved (`ppkcurve.window_overnight`, eight fixed-point steps from the calendar day's answer;
    `extras.overnight_bd` writes the same steps as the cells' formula, so the page and the chat agree to the last digit);
    O/N → rate: (exp(d·ln(1 + x) − W·x²) − 1)·365/d, `OIS_MAIN!BJ`'s formula (`ppkcurve.window_rate`,
    `extras.overnight_bd_back`). With no weekend or holiday in the window (W = 0) it is every day compounded alone.
  - **Consistency:** the model's own window rate (`OIS_MAIN!BJ`, "İma oran (model)") typed gives the model's TLREF
    (`Motor!K`) back as its O/N (1e-12), so the O/Ns of consecutive windows step by the model's steps; the market's own
    window rate gives the market's own step (`M`). On the replay windows the terms Motor reads are the TRY list's, counted
    by hand (the first window holds New Year's Day, the second the 2027 Ramazan Bayramı).
  - The second order against the exact product Π (1 + x·g): a few thousandths of a bp of O/N over a weekend, a few
    hundredths over a bayram week, at TRY's rates (`test_ppkcurve`); on the replay windows (03.11.2026, the model's own
    window rates) at most 0.008 bp of O/N and 0.004 bp of a step.
- Step = the rate's O/N − the O/N of the market's rate for the period before (the window before, with its own term; for
  the first window the bootstrap's stub from the OIS spot, ln DF 0 there, term `Motor!J5 − J4`). An MPC spread typed: the
  later window's rate = the earlier window's market + the spread, on the same base.
- **Until 25.11.2026 every calendar day compounded alone**, 365·((1 + r·d/365)^(1/d) − 1), in both the page and the chat;
  for the same rate that O/N is 1.3–2.5 bp below TLREF's on the replay windows (the model's window rates read 1.3–2.5 bp
  under the model's TLREF). The market's step moved by −0.87 … +0.95 bp (replay, 03.11.2026; a step typed stays the step,
  a rate typed stays the rate - only what is worked out from them moves).
- **Not the Forward page's O/N.** Its FX-implied TRY rates take the calculators' calendar-day ACT/360 O/N equivalent,
  360·((1 + r·g/360)^(1/g) − 1) (`Forward!AH14`'s "ON Karşılık", `extras.on_equivalent` / `on_simple`): the
  calculators, VİOP's gold calculator and TOPLU FORWARD's ON karşılık % (`EK_BULK!M`, g = the row's Gün; 26.11.2026).
  TLREF's business-day one above is TRY OIS's (EK_PPK, Broker Chat); the two are never mixed.

**USD (SOFR / FF OIS) - a FOMC window's rate → the step** (`SOFR_FOMC!AA:AE`): the window from a meeting's effective day
to the next active meeting's (`F:H`); its rate simple **ACT/360** (İşlem 1's `E` = (exp(ln DF start − ln DF end) − 1)·36000 /
days); O/N compounded daily, ((1 + r·d/36000)^(1/d) − 1)·36000 - the page's own `K` on the rate's DF ratio; step = O/N −
`L` (the previous active meeting's `K`, the first's the stub O/N `B7 + B16/100`), in bp and in steps of `B9` (as `N`).
**Not part of the 25.11.2026 decision:** SOFR is the USD page's own convention (its `K` compounds every calendar day), so
USD · FOMC keeps it - the business-day change is TRY OIS's (TLREF) alone.

**FRA from two spot swaps** (`OIS_MAIN!S336:S438`, TRY OIS): FRA = (R·P − Q·O) / (P − O), O / P the annuities to the start
/ end month on Motor's quarterly calendar (ACT/365), a blank fill the market's par (`I` / `J`). Its inverse (`U:W`): end
leg = (F·(P − O) + Q·O) / P, start leg = (R·P − F·(P − O)) / O.

**Two-way** (24.11.2026): the PPK tables and the FOMC table invert their own conversions in place - a step typed: O/N =
the period before's O/N + the step, then the window's simple rate from that O/N - TRY OIS on business days
(`extras.overnight_bd_back`, the model's window rate, the exact inverse of `overnight_bd`), USD every day in % on ACT/360
(`extras.overnight_back`, ((1 + O/N/36000)^days − 1)·36000/days); a pair's later rate or its O/N or step gives the spread
(later − the earlier window's market rate). Same curves and bases as above. The FRA list too (the desk's "Ok",
24.11.2026): an FRA typed into Gerçekleşen FRA holds the start leg (its fill, else its market par) and gives the end leg's
fill, (F·(P − O) + Q′·O) / P - the "Gereken bitiş bacağı" formula (`extras.fra_end_leg`, one implementation for both).

## Spot and value dates

| Pair / use | Spot | Holidays |
|---|---|---|
| USDTRY | T+1, `Forward!I2` | TRY+USD |
| EURTRY | T+2, `Forward!K2` | TRY+EUR, no USD rule |
| EURUSD value dates | - | USD+EUR |
| TRY OIS / money market / bonds; VİOP's OIS FRAs; MASA's date-to-date block and EK_TARIH's rows | `OIS_MAIN!B2` (T+1) | TRY only |
| VİOP's implied TRY rates | `VIOP!K3`: Bloomberg's `SETTLE_DT` of `USDTRY Curncy` (`VIOP!M8`; days `M10 = M9 − M8`) | Bloomberg's dates |
| The ASW sheet's curve | `ASW!C4` → `T65`: Bloomberg's `SETTLE_DT` of `TRY Curncy`, else `WORKDAY(TODAY(),1,TATIL)` | the ASW book's `TATIL` |

- The rules live in `extras.FX_SPOTS`, `pair_calendar` and `_tto_ois_spot`.
- Beside `Forward!I2`, `K2` and `OIS_MAIN!B2`, Bloomberg's `SETTLE_DT` is only shown, as "Bloomberg valörü"
  (`Forward!J2`, `L2`, `OIS_MAIN!L2`). Three dates still use it, and no addition patches them: `VIOP!K3` (VİOP's
  implied rates), `ASW!C4` → `T65` (the ASW sheet's curve and the shift of ASW FX's 18M) and the gold spot date
  (`EK_XAU!B9`, when none is typed).
- The cells counted from the USDTRY spot: `MASA!P94:P99`, `MASA!C171`, `Forward!B200:B205`, `Forward!K130:K134`.
- The Forward page's two-way tables (24.11.2026) solve a typed outright's TRY rate (`extras.implied_try`, simple
  ACT/360) over the days each table counts: USDTRY from `Forward!I2`, EURTRY from `Forward!K2` (TOPLU FORWARD's and
  ÇAPRAZ's EURTRY, the EURTRY value-date table, FSS's EURTRY period `MAX(0, G168 − F168)`), the free list from its row's
  start. No curve is read for it: offshore and OIS are untouched.
- `fx_shift` (`ppkcurve.read`) = FX spot − OIS spot, in days. It puts the OIS side's MPC path on the offshore curve's
  days (`StepCurve.rebased`: the offshore PPK curve, and its bumps in Fiyatlama) and the offshore curve on Motor's
  quarterly calendar in the interpolation chart. ASW FX's 18M uses a shift of its own, `ASW!T65 − Forward!I2`
  (`Service._asw_fx_18m`).

---

## Where OIS and offshore meet

This is the complete list as of 19.11.2026. **Do not add to it.** If a feature seems to need an OIS number on the
offshore side, ask the desk first.

| # | Where | What happens |
|---|---|---|
| A | `aswfx.to_sheet` (`aswfx.py` about 231–239) | EK_FX tenor with no FX price on either source keeps the ASW sheet's OIS quote. The rule text is `aswfx.RULES[OIS]`, "fiyat yok: OIS kotası". On the desk, 6Y–10Y always have `TRYSAQ` prices. In the replay file they don't (see [market-data.md](market-data.md#replay)). |
| B | `Service._asw_fx_18m` | 18M without `TRYSAQ1` / `TRYSAQ2`, or without a curve, keeps its OIS quote. |
| C | `aswfx.history_series` / service history rows | On a past day, a tenor with no offshore close keeps that day's OIS quote. |
| D | Curve names (`rvfair.FX_CURVE_TEXT`, `views/61_asw.json`) | The label says "…; fiyatı yoksa OIS", so the mix is visible. Wording only. |
| E | `rvfair` FX side | The dirty price at spot is carried with TLREF. This is the ASW sheet's own formula. |
| F | `ppkcurve` offshore PPK | The offshore PPK curve takes the OIS-implied MPC path's **shape**. Its level comes from the offshore quotes (a flat basis between them). |
| G | `retfair` scenarios | The offshore and VİOP bases move by the OIS scenario's change, `market + (scenario − reference)`. |
| H | EK_FWD, "FORWARD KOTASYON" (`extras._tto_forward`) | USDTRY forward quotes priced as OIS + spread: the chosen OIS curve's rate (MASA's own discount factors, default "MPC ima") plus a typed spread or the market's (offshore ICAP implied − OIS). The desk's pricing design, not a fallback. Two-way since 24.11.2026: a TRY %, puan or fwd typed instead gives the spread (that rate − OIS); offshore still enters only as the "Piyasa spread" default. |
| I | `retfair` "karma" base | A blend of the OIS, VİOP and offshore mids: a tenor's own weights, else the administrators' default, 50 / 25 / 25 to start with (`retfair.DEFAULTS["blend"]`). A desk design, not a fallback. |

**Not fallbacks** (each curve keeps its own):
- The O/N: `borsaspread` (and `retfair` through it) uses offshore ICAP `Forward!AC123` and TLREF `Forward!AD123`
  (365 → 360); `tradevalue` uses offshore `AC123` and TLREF `OIS_MAIN!J2` (ACT/365).
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
