# Desk decisions

What the desk (the user, a TRY rates trader) decided, in their own words, and where the code carries it out. These
are requirements, not suggestions:
- Do not "improve" one away, and do not reopen one, without the user's OK.
- When a new decision overrides an old one, change the entry and date it.
- Quotes are verbatim (Turkish), with the date they were said.
- Bloomberg values never go in this file (see [market-data.md](market-data.md)).

Related: [curves.md](curves.md) explains the curves these decisions are about.

---

## Curves

### Offshore TRY is a curve of its own - never OIS (18.11.2026, 19.11.2026)

> "Offshore için hep TRYSAQ1 kullanılacak 1Y'de, OIS ile ayrı bunlar, OIS farklı."
>
> "6-10 arası zaten offshore curve'ünü de çekip FRA vs hesaplamıyor muyuz? TRYSAQ5-6-7-8-9 gibi kullanıyor olmamız lazım"

- **What the offshore curve is made of.** The offshore TRY curve is built from two instruments:
  - FX swap implied yields (`TRYI…`) up to 9M;
  - cross-currency swaps (`TRYSAQ1` … `TRYSAQ10`) from 1Y.

  It never takes an OIS quote or OIS's conventions.
- **1Y is `TRYSAQ1`** (XCCY, one coupon). `TRYI12M` is not used.
- **Where the tickers are set:**
  - `extras.FXC_ROOTS` (EK_FX);
  - `aswfx.FX_SWAP_MAX = 9` and `aswfx.HIST_GROUP` (each tenor's history series comes from its own kind's group only);
  - the Forward sheet's tickers `Forward!AO6:AO26`, read through EK_KAYNAK's source order.
- **Where OIS still meets offshore:** only the places listed in
  [curves.md](curves.md#where-ois-and-offshore-meet); do not add one. Its OIS-quote fallbacks are one rule,
  `aswfx.RULES[OIS]` ("fiyat yok: OIS kotası"): a tenor with no price keeps its OIS quote. That covers an EK_FX tenor
  with no price on either source, 18M without `TRYSAQ1` / `TRYSAQ2`, and a past day without that tenor's offshore
  close.
  - On the desk this does not happen at 6Y–10Y: the history has `TRYSAQ6–10` closes every day.
  - The replay file has those five tenors as `#N/A` (`Forward!D130:F134`), so tests and replay comparisons do see the
    fallback there (see [market-data.md](market-data.md#replay)).

### 18M is computed, never a quote (18.11.2026)

> "18m hesaplanacak gercek kotasyon girilmeyecek"
>
> "TRYI18M gerçek bir kotasyon değil. Orada annual payment olduğu için 1Y'den sonra XCCY trade ediyor. Zero'yu oradan
> bulmamız gerekli. Bunun da interpolasyonu PPK'yı seçersem PPK'ya gelmeli"
>
> "18 ayda 6 ay + 12 ay kupon, sondan başlayıp"

- **EK_FX's 18M** is the offshore XCCY curve's discount factor at 18M, on the viewer's interpolation setting.
  - Code: `aswfx.point_18m`, `Service._asw_fx_18m`.
  - Its rate is the 18M XCCY par, with coupons of 6M then 12M counted back from maturity (`aswfx.xccy_months`).
  - On a past day it comes from that day's `TRYSAQ1` and `TRYSAQ2` closes (`aswfx.history_point`).
- **XCCY schedules in general** run in 12-month coupons counted back from maturity, with the short period first. For
  example, 2Y3M = 3M + 12M + 12M.
  - Code: `pricing.coupons`.
  - In the workbook: MASA's broken-date helper `BU192:BY203`.
- **Ayarlar → Eğri noktaları** has "18M · XCCY · hesaplanan" on the default offshore list (`curvepoints.py`).

### Convert every quote to the convention of the sheet it feeds (18.11.2026)

The desk caught the ASW FX curve fed with the wrong convention ("kuponlu rate çizilmiş"). The conventions:

| Instrument | Convention |
|---|---|
| `TRYI` (FX swap implied) | one period, simple ACT/360 |
| `TRYSAQ` (XCCY) | annual ACT/360 par, bootstrapped |
| The ASW sheet's own OIS | one period, simple ACT/365 up to 3M; then quarterly ACT/365 par |

When one curve's instruments feed another sheet's bootstrap, give that sheet the par quote, in its own convention,
that gives the same discount factor (`aswfx.to_sheet`). Compare curve points on DF or zero rates, never on raw quotes
of mixed conventions.

### Bootstrap (Murex) stays as it is; PPK basamak is a second view (18.11.2026)

> "Murex şu anda yaptığımız gibi MTM ettiği için bunu da görebilmem gerekli"
>
> "PPK tarihli basamak da ekleyelim, iki türlü de bakabileyim"
>
> "Ayarlardan PPK basamakla tüm interpolasyonları değiştirebilmeliyim"
>
> "Trades MTM de anahtara bağlansın"

- **Bootstrap is what Murex marks.** It is Motor's bootstrap: the quoted pars linear in months on its quarterly grid,
  then ln DF linear in days between the nodes (`BOOT_GUN` / `BOOT_LNDF`). The desk reconciles P&L against Murex, so
  Bootstrap numbers must not move.
- **Ayarlar → Eğri interpolasyonu** is per user, default Bootstrap. On PPK basamak it switches that user's
  interpolation:
  - Motor's node pars, via `EK_INTERP`;
  - the offshore nodes;
  - the ASW sheet's row 65 (the plain ASW column);
  - Trades MTM (`tradebook.FOLLOW_CURVE`).

  Not ASW FX's sheet curve: it stays the sheet's own for everyone, and only its 18M point follows the setting (a known
  difference, [curves.md](curves.md#known-differences---read-before-changing)).
- **Shared and automatic calculations stay on Bootstrap:** Günlük İşlemler records, alarms, quant, history, the ASW
  history rows and `retfair`. Desk MTM snapshots are stored for both curves, and each viewer sees the one for their own
  setting.
- **Two-way views read the real Bootstrap**, even for a PPK user. These are the FRA lists' PPK columns, MASA's broken
  date, the blotter's PPK figures, the interpolation chart and Fiyatlama.
- **Code:** `tto/interp.py`, `tto/ppkcurve.py`, `extras.INTERP_SHEET`, `tto/interpchart.py`, `tto/tradebook.py`.

### FRA / DV01 buckets split linearly by months (18.11.2026)

> (a 12x15 FRA) "15M bucket'ı arıyor" … "yarısını 1Y, yarısını 18M bucket'ına atması gerekmiyor muydu"

The buckets are `blotter.BUCKET_MONTHS`. `blotter.bucket_split(m)` splits a tenor between its two neighbouring buckets,
linear in months:

| Tenor | Split |
|---|---|
| 15M | ½ 1Y + ½ 18M |
| 27M | ¾ 2Y + ¼ 3Y |
| 63M | ¾ 5Y + ¼ 6Y |

### Eğri noktaları - the desk's list of curve points (18.11.2026)

> "Bu enterpolasyon noktalarına Ayarlar'dan ekle / çıkar yapabilmeliyim, yanlarına da ne olduklarını not
> alabilmeliyim. Ama PPK'lar her zaman olmalı. PPK tarihleri güncellenince o da güncellenmeli." - then: "Evet, böyle"

- **One list per curve** (OIS, Offshore), shared by the whole desk:
  - only administrators change it, and every change is logged;
  - PPK meetings are always in it and follow the calendar.
- **A Bloomberg-ticker point is a new live subscription.** Its cost is stated and confirmed before it is saved.
- **The default list is today's points**, so no number moves until the list changes.
- **DİBS ASW keeps its own quotes.**
- **Code:** `tto/curvepoints.py`.

### Which FX swap curve the DİBS fair values use (17.11.2026)

> FX swap = "(a) FX swap ima eğrisi"

- **Who reads EK_FX's curve (ASW FX):**
  - DİBS RV · Genel;
  - DİBS Trading's "FX swap'a göre" group;
  - the bond card;
  - the FX side of `rvfair`.
- **DİBS RV's own `BF:BJ` is a different number.** It is the TRY workbook's "offshore ICAP" discount. It stays in the
  sheet under that name, hidden by default, because the TRY book cannot build EK_FX's curve and showing it would put a
  third FX number on screen.

### DİBS zero-coupon curve (17–18.11.2026)

- Always Nelson–Siegel (3 β, 1 τ).
- Bills are out of the fit ("Çıksın", 18.11): `quantcurve.FIT_KINDS = ("fixed",)`.

### Spot and value dates (15.11.2026)

> "usdtry spot t+1 normalde" · "eurtry t+2" · "TRY, USD ve EUR için ayrı tatil listeleri ekleyip FX valörlerinde iki
> para biriminin tatillerini de kullanalım" · (US holidays for EURTRY) "Buna gerek yok" · (OIS spot) "Evet, TR'ye göre"

- **Spot dates** (`extras.FX_SPOTS`):
  - USDTRY spot = T+1 on TRY+USD: `Forward!I2 = WORKDAY(TODAY(),1,<TRY+USD>)`;
  - EURTRY spot = T+2 on TRY+EUR, with no USD rule: `Forward!K2`.
- **Bloomberg's own date stays beside each, for comparison.** Bloomberg's `SETTLE_DT` is shown as "Bloomberg valörü"
  in `Forward!J2` / `L2`.
- **FX value dates** skip both currencies' holidays for USDTRY, EURTRY and EURUSD (`extras.pair_calendar`).
- **TRY-only dates:** TRY money market, bonds, VİOP and OIS dates use the TRY list alone. That includes OIS_MAIN!B2
  `= WORKDAY(TODAY(),1,TRY)`, which also shows Bloomberg's date beside it.
- **Holiday lists:**
  - TRY is Motor's list (`Motor!A361:A523`).
  - USD (Fed, New York FX settlement) and EUR (TARGET2) are on `EK_TATIL`. Their defaults are generated by rule;
    everyone can edit them.
  - SIFMA is not the USD FX list; it stays for SOFR.
- **Date shortcuts.** Typing "18m" or "3m" into a date cell counts from the cell's own start: the row's spot or value
  date that the page names, else the date the workbook counts the cell's days from, else the pair's spot
  (`tto/shortcuts.py`, `tto/datecells.py`).
- **Read the formula first.** These cells used to be Bloomberg's `SETTLE_DT`. Read the cell's formula before saying
  where a date comes from.

### Broken-date TRY OIS: the short period comes first (19.11.2026)

> "İlk olan kısa olan"

The desk was asked where a broken-date TRY OIS puts its short coupon period; Murex puts it first. Coupons are counted
back from maturity every 3 months, so the first period is the short one. All three places now agree:

| Where | Code |
|---|---|
| Trades | `tradevalue.CONVS["ois"]`, anchor `"end"` (it was `"start"`, short period last, until 19.11.2026) |
| Fiyatlama | `pricing.coupons` |
| MASA's broken-date block | `MASA!BL193`: `WORKDAY(EDATE(end, −3k) − 1, 1, TRY)` |
| Günlük İşlemler (a leg to a date of its own: "Ters işlem" of a past day's OIS, 23.11.2026) | `blotter.OisMarket.broken` → `pricing.swap_deal` (Fiyatlama's, on the true Bootstrap) |

A trade entered as a tenor is dated on its own grid from the start (`EDATE(start, m − 3k)`):
- whole quarters give Motor's own dates (`Motor!B88`), unchanged;
- 13M gets a 1M first period.

Tests: `tests/test_tradevalue.py` - `test_schedules_of_a_tenor_and_of_a_broken_date`,
`test_trades_and_fiyatlama_date_a_broken_try_ois_alike`.

### Coupon conventions, taken from the workbooks (17–19.11.2026)

- **TRY OIS:**
  - ACT/365, fixed against TLREF compounded;
  - one payment up to 3M, then quarterly coupons counted back from maturity, the short period first (above);
  - paid at period end.
- **SOFR OIS:**
  - ACT/360;
  - one payment up to 1Y, then annual coupons counted back from the end, short period first;
  - modified following on SIFMA, paid two SIFMA business days later (`tradevalue.py`).

---

## Bloomberg and data

- **The daily data limit is a hard rule.** Say the daily cost of any new request (tickers × fields, how often) before
  adding it. Details: [market-data.md](market-data.md).
- **History pacing:**
  - each series' full range once a day, then only the new days;
  - the quant package's new series and SOFR fill 40 per live sync (`History.BACKFILL_PER_SYNC`), as the user
    approved: "Önerini yap"; VİOP contracts 15 (`VIOP_PER_SYNC`). Which series are rationed:
    [market-data.md](market-data.md);
  - the "new days" query stays every 15 minutes ("Böyle kalsın", 15.11);
  - `SOFRRATE Index` is asked once a day after 16:30: not at a start before then, and not again after a restart the
    same day ("1 kalsın", 18.11).
- **Where Bloomberg data may not go:** the repository, an external service, GitHub, or a cloud-synced folder. This
  covers Bloomberg data, screenshots of it and logs, and backups of the database (which also holds password hashes).

## Product rules

- **Keep the original number beside a refined one** (15.11). Example: ATM ±1σ stays beside the skew-aware ↑1σ / ↓1σ.
  Remove, rename or hide a number the desk already sees only after asking.
- **Quant prints trades.** Systematic AL / SAT lines with levels worth trading: R/R ≥ 1, target and stop calibrated on
  past trades - except the families whose design fixes their own levels (`quantlevels.KEEP`; their line says why).
  - A line whose calibrated levels lost money in the backtest is "düşük güven": no alarm, no log ("2a", 17.11).
  - Do not add generic evidence gates that filter signals out.
- **Alarms** (15.11):
  - muting is personal;
  - there is no RET alarm;
  - the TLREF alarm is due at 14:00 (`ops.py` default `tlref_due`).
- **Broker Chat board** (15.11):
  - the "işlem görüldü" rule stays: a trade seen in the chat takes the quotes it hit off the board (`brokerchat`);
  - a quote is stale after 10 minutes, a desk-wide setting (`Service.BROKER_STALE_MINUTES`, 1–1440);
  - staleness also shows on DİBS RV, DİBS Trading and the bond card: the best fresh quote, a stale one greyed.
- **Bond list** (15.11):
  - everyone edits it;
  - a matured bond drops the next day;
  - an FRN has no DM, only a price;
  - foreign-currency bonds are not taken.
- **RET fair value** (`tto/retfair.py`; the desk's design, 16–17.11):
  - each tenor has its own row;
  - the base is OIS, VİOP or offshore mid, or a blend;
  - the spread on the base is the trader's;
  - the bid–ask width is a multiple of 5 bp, changed only by administrators;
  - "Tabana göre" is Bid, Mid or Ask, default Mid;
  - a 2 bp hysteresis applies;
  - each user picks their own scenario view.
- **Backups** (15.11):
  - taken at 17:30;
  - an administrator picks the folder and a second-copy folder;
  - cloud-synced folders are refused;
  - if the folder can't be written, the backup goes to `data/backups` with an alarm.
- **Presence** (18.11): online / away / offline for everyone. The IP shows only in the administrators' user list.
- **Günlük İşlemler** (18.11):
  - "Mid'e göre" is + in the trader's favour;
  - editing a trade re-prices only what changed.

### Trades: spot and DİBS K/Z include their carry (19.11.2026)

> "Trades kısmında carry de hesaplıyoruz değil mi? Veya OIS SOFR trade'lerinin biriken kuponunu" -
> "Spot trade'lerindeki carry'den de bahsediyorum"

Until then an FX spot trade's K/Z was only the spot move, and a bond's had no funding: their carry (the roll at the two
currencies' O/N rates; the dirty price funded at TLREF) showed only as the "c" of the K/Z, and "f" cancelled it. Asked
whether spot and DİBS K/Z should include the carry, the desk chose "1": yes, both.

- **The rule.** K/Z = the price move + the carry since the value date: the funding the value does not hold
  (`funding_1d`: an FX spot's whole carry; a bond's TLREF funding of its dirty price) is added day by day from the
  closes, as the carry is counted. `c` is the carry, `f` the price move alone. A closed trade keeps its carry up to its
  close.
- **The list.** "Fonlama" is the funding since inception (MTM + Kupon + Fonlama = total K/Z); "Biriken" a swap's period
  under way so far (inside the MTM); "Carry (1g)" the next business day's carry, its parts in the tip.
- **Before 19.11.2026.** A close kept before funding was: an FX spot's carry is all funding; a bond's days take the
  first funding known after them, and a bond closed before then keeps its K/Z. A realised K/Z kept under the old rule
  is worked out again (`tradebook.REALIZED_RULE`).
- Code: `tradevalue` (`funding_1d`, `running`, `carry_parts`), `tradebook` (`funding_between`, `FUNDED`). Tests:
  `tests/test_trades.py` - `test_spot_and_dibs_k_z_count_their_funding_beside_the_value`,
  `test_a_realised_p_and_l_kept_before_funding_counted_is_worked_out_again`.

### Trades: a DV01 table like Günlük İşlemler's (19.11.2026)

> "Trades kısmına da günlük işlemler kısmındaki gibi dv01 tablosu eklemek istiyorum"

- **What it copies.** Günlük İşlemler's "OIS · vade özeti" (`Günlük İşlemler!O22:W39`): Net DV01 (`S − V`, payer +),
  the tenor, Pay and Receive nominal / rate (nominal-weighted) / DV01 ($), and the net rate `(R·S − U·V)/(S − V)` when
  both sides are there; the total row has no rates. Plus a bar like the blotter's ("DV01 · TRY faizi +1 bp ($) ·
  payer +"): TRY OIS net, bonds, their total, and SOFR apart.
- **Whose trades.** The tab's open trades (desk or personal) at the last "MTM yenile"; SOFR in its own table (USD
  rates); bonds only in the bar (DİBS RV's DV01 at maturity, a bond bought −); FX not in it.
- **Tenors.** ON, 1W, 2W, 1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y, 3Y, 4Y, 5Y as the sheet, then 6Y–10Y (the desk's buckets).
  - A spot swap entered as a tenor sits on its tenor; 15M splits ½ 1Y + ½ 18M (the 18.11 bucket rule).
  - A dated or started swap sits at its end date, split between the two tenors around it by days. The tenor ends are
    rolled to business days as the swaps' are.
  - A forward-starting swap (FRA, PPK period, forward leg) is split as Günlük İşlemler splits a meeting-dated swap
    (`blotter.mpc_summary_rows`): the spot swap to its end its way, the spot swap to its start the other way, on one
    nominal whose two DV01s add up to its own.
- Code: `tradevalue.risk_split` / `risk_months` / `_risk_legs` (`risk` of a valuation), `tradebook.dv01_table`.
  Tests: `test_dv01_on_the_tenors_as_gunluk_islemler_takes_a_trade` (test_tradevalue),
  `test_the_dv01_table_adds_up_the_tab_s_open_swaps_and_bonds` (test_trades).

### Trades: the K/Z's c · f split stays as it is (19.11.2026)

> "Trades'teki OIS DİBS spot trade'lerini de carry ve rate hareketi diye ayıralım P&L'i" - shown that every K/Z
> already reads "c … · f …": "Bunu görmemişim kalsın güzelmiş şu an"
>
> "12x15 FRA pay etmiştim, bu carry'den zarar yazdı gösteriyor. Ancak forward rate'te daha TLREF belli olmadığı için
> carry'den zarar yazamaması gerekiyor" - the roll-down explained: "Böyle kalsın anladım güzel böyle"

- **The split stays.** Every K/Z cell (Günlük, Haftalık, Toplam) shows `c` (carry) and `f` (the rest: the rate or
  price move) under its number (`trades.js` `pnlCell`). No separate Carry / Rate columns.
- **`c` = the day's accrual + the one-day roll-down**, for a forward start too.
  - The accrual is the fixed rate against TLREF on the period's compounded notional, nothing before the start.
  - The roll-down is the trade tomorrow on the curve rolled a day against the trade tomorrow when today's forwards
    come true: what the curve keeping its shape earns (nothing on a flat curve).
  - So a swap that has not started (an FRA, a forward leg) has a `c` of roll-down alone, and it can be negative. A paid
    12x15 showed a negative `c` because the bootstrap's forward just before its window (9–12M) was below the one inside
    it (12–15M): about −2.8 thousand TL a day on 100 mn on the replay curve.
- Don't move the roll-down out of `c`, or redesign the split, without asking. A surprising `c` is explained by its
  parts: Carry (1g)'s tip shows them (tahakkuk / roll-down).
- Code: `tradevalue` (`carry_1d` = `carry_accrual` + `roll_1d`, `carry_parts`), `tradebook` (the P&L's `carry` /
  `price`).

### Swaption page (19.11.2026)

> "Önce bir swaption sekmesi yapmanı istiyorum. Try ois için hesaplayacağız. Vadeyi seçtiğimde günlük, yıllık bps vol ve
> % black vol çıkacak. Ben buraya vol girdiğimde bana delta gamma vega hesaplayacak, veya rate opsiyonlarında ne
> greek'i varsa, bu vole göre implied rate vade sonunda ne olacak onu gösterecek, breakeven rate'i hesaplayacak. Bu
> sadece görmek için olacak henüz buradan herhangi bir işlem yapılmayacak"

- **View only.** No booking, no trade buttons, nothing stored on the server; the page keeps its last inputs in the
  browser (localStorage). Nothing is keyed by cell or row, so the PPK calendar's row moves do not reach it.
- **The desk's two answers:**
  - *The vol shown on picking expiry × tenor* is **realized, from our own closes**: the forward swap rate's daily bp
    changes over 20 / 60 / 120 / 250 changes, as the Realized Vol · Carry page (sample standard deviation; annual =
    daily × √252). No new Bloomberg request.
  - *Dating* is **like Fiyatlama**: the underlying OIS starts <expiry> after today's OIS spot (`OIS_MAIN!B2`, T+1 on
    the TRY list), the forward-start OIS Fiyatlama prices for that start and maturity, with its coupons
    (`pricing.coupons`); the option expires on the TRY business day before the start.
- **The integrator's defaults** (said on the page's notes and in README; the desk may change any of them):
  1. Model: normal (Bachelier) on the forward swap rate F with the annuity A; payer = call on F, receiver = put,
     straddle both. % Black = the lognormal vol giving the same payer premium (solved); a typed % Black vol becomes σN
     the same way.
  2. Vol time: T = TRY business days from the market day to the expiry / 252, so bp/year = bp/day × √252 exactly and
     the daily bp vol is the daily breakeven move; the discounting stays in the annuity (the curve's ACT/365).
  3. Default vol: realized over 60 changes; a vol typed in any unit (bp/day, bp/year, % Black) overrides it, and the
     page shows all three units of the vol used.
  4. Curve: the viewer's interpolation setting first, the other curve's forward beside it, as Fiyatlama; the realized
     vol's history on Bootstrap, as every shared history calculation.
  5. Strike ATM (K = F) unless one is typed (%); notional 100 mn TL unless typed (`100m`, `2,5mn`).
  6. Outputs for payer, receiver and straddle, the buyer's view: premium (bp upfront A·p, bp running p, TL N·A·p),
     delta (TL per bp, %), gamma (the delta's change for 1 bp), vega (1 bp of normal vol, 1 % of Black vol), theta (TL
     a business day, same F, σN, A), the underlying's DV01 (N·A·1e-4).
  7. The rate at expiry: F, F ± σN√T, F ± 2σN√T (normal). Breakevens at expiry: payer K + p, receiver K − p, straddle
     K ± (p_payer + p_receiver), p the running premium.
- **Conventions settled while building it** (the spec did not say; ask before changing):
  - "Matures <tenor> after that start" is dated as Fiyatlama dates a forward start: both ends are tenors from the OIS
    spot, so 1Y × 2Y is Fiyatlama's "TRY OIS 1Y × 3Y" on Motor's quarterly calendar - not `EDATE(start, tenor)`, which
    can be a day off when the start rolls.
  - Expiry and tenor are typed in months / years only (no weeks, no dates); expiry + tenor ≤ 10Y.
  - A past day counts when every OIS tenor its forward needs closed that day (up to the quote at or beyond the Motor
    node its maturity reads); past TRY holidays are the history's (Motor's list and week days without a TLREF fixing).
  - The realized table's % Black is at today's F and the strike in use.
- Code: `tto/swaption.py`, `Service.swaption` (`_swaption_market`, `_swaption_closes`, `_swaption_history`),
  `GET /api/swaption`, `tto/static/js/pages/swaption.js`. Tests: `tests/test_swaption.py`, the browser test's
  Swaption checks.

### Prop panel (19.11.2026)

> "Bir de prop trade calculation kısmı açalım, bunu üstteki panele koyabiliriz. Pariteyi, stopumu, ve potansiyel loss'umu
> koyduktan sonra 1M'e yuvarlanmış şekilde bana gerçek potansiyel lossumu ve size'i söylesin."

- **Their answers.**
  - The size is rounded **down** to 1M, so the real loss never goes above the loss typed.
  - The loss is typed in **TRY or USD, chosen each time**.
  - They also chose the **prop risk** in the same panel: the loss if every stop is hit, today's K/Z, a daily loss
    limit and the room left.
- **The calculator.** A pair of the desk's FX lists that has a price, the stop, the loss, the entry (the live mid unless
  typed). Stop below the entry: long; above: short; equal: refused. The loss goes into the pair's quote currency at
  today's rates; `size = loss / |entry − stop|`, rounded down to 1M of the base currency. Shown: the direction, the
  distance (price, %, pips; kuruş for a TL pair), the size, the real loss at it (the loss's currency and TL, with the
  other one beside), the loss of 1M and, with a limit, the share of today's room the trade uses. Worked example:
  USDTRY 44,35 → stop 44,55, 500k TL: short, 2,5M raw, **2M USD, 400.000 TL**, 200.000 TL a million.
- **The risk.** Room = limit − max(0, −today's K/Z) − loss at the stops: a gain gives no room. "Limit · Bugün K/Z ·
  Stoplar · Kalan", in the panel's currency.
- **Conventions settled while building it** (the spec did not say; ask before changing):
  - **Prices** are the valuation's market snapshot (`tradevalue.market`): the Forward sheet's USDTRY and EURTRY, the
    quant package's FX series (its last live refresh, else the last close), crosses through USD - and the cross of two
    TL prices (EURUSD = EURTRY / USDTRY) when there is no other. No Bloomberg request. The pairs offered are the quant
    setting's list and the Spot / FX board's; one without a price is refused ("canlı fiyat yok").
  - **Rounding down** forgives float noise of 1e-9 (44,55 − 44,35 is 0,19999999999999574: 400k is 2M, not 1M).
  - **Under 1M** the size is 0 and the panel says what 1M would lose.
  - **One currency switch.** The loss's TRY / USD switch is the panel's: the risk is shown in it too. It starts on TRY
    each time the panel is built; the Kişisel / Masa switch is remembered (localStorage).
  - **Stop levels from the market now, on Bootstrap** (Murex), as the stop alarms read them, each in the trade's own
    level unit (`tradebook.level_spec`), with its valuation's sensitivity:
    - FX spot: base amount × the rate's distance (exact);
    - TRY OIS / SOFR outright, PPK period, FRA: DV01 (notional × annuity × 1 bp, the sensitivity to its own par rate) ×
      the bp;
    - spread / fly: the level's DV01 = half the sum of the legs' DV01s (the long leg's / the body's when DV01-weighted
      as the desk sizes them) × the level's bp;
    - DİBS by yield: DİBS RV's DV01 (TL a bp of 1 mn, of the simple yield) × the bp; by price: nominal × the price
      distance / 100 (exact);
    - **FX option: not "delta × spot distance".** Trades keeps an option's stop as a **premium amount** (what it would
      fetch now: `level_spec`), not a spot level, so the loss at its stop is that premium's own distance (exact). The
      delta only translates the stop into the spot where the premium would reach it, labelled "yaklaşık (delta)".
  - **A stop already passed** adds nothing to Stoplar: what lies beyond it is already lost - it is in the MTM and so in
    the K/Z - and is shown beside the trade ("geçildi · ötesi …").
  - **No stop**: listed apart ("stopsuz") with the DV01, the size (signed) or the delta (approximate); not in Stoplar.
    A trade that cannot be valued is listed with the reason and counted as unknown (left out of the sum, said).
  - **Today's K/Z** is the tab's "Günlük" of its last "MTM yenile", on the viewer's curve - exactly the Trades page's
    total. Nothing is valued automatically for it (Trades' design: values on "MTM yenile"); with no "MTM yenile" today
    there is no K/Z and no room, and the panel offers the same "MTM yenile" button.
  - **The limit** is the user's own (`prop.limit:<user>`), any amount above 0, in TRY or USD; empty removes it, and
    then the line has no Limit and no Kalan (only Bugün K/Z · Stoplar). Its other currency, the K/Z's and the stops'
    are converted at today's USDTRY.
  - The risk is read when the panel opens, on its buttons, and every minute while it is open.
- Code: `tto/prop.py`, `Service.prop_state` / `prop_size` / `prop_risk` / `prop_limit` / `prop_set_limit`,
  `GET /api/prop`, `GET /api/prop/size`, `GET /api/prop/risk`, `GET` / `POST /api/prop/limit`,
  `tto/static/js/prop.js`. Tests: `tests/test_prop.py`, the browser test's Prop checks.

### Kâğıt fiyatlama (19.11.2026)

> "Özellikle kâğıt tarafı zayıf geldi" - "Hangi seviyelerin iyi olduğunu ve fiyatlamayı nasıl yapacağımı net söylemiyor"
>
> (asked what a bond's price should start from) "Bunu sen bul. En çok neyi takip ediyor"

- **What the bonds follow** (measured on the desk's own history: a copy of its database of 17.11.2026, 16 DİBS - 14
  fixed coupon, 2 bills -, 10.11.2025–16.11.2026; daily yield changes, R², OIS / offshore / the Nelson-Siegel curve fitted
  to the other bonds, leave one out):

  | Maturity | OIS | Offshore | Neighbours' curve |
  |---|---|---|---|
  | ≤ 1Y | .21 | .21 | .14 |
  | 1–3Y | .50 | .39 | .73 |
  | 3–5Y | .54 | .40 | .82 |
  | 5Y+ | .47 | .27 | .81 |

  Next-day pricing error of fair = base + the bond's spread to it at the previous close (sd): neighbours 23 bp at 1–3Y,
  16 at 3–5Y, 16 at 5Y+; OIS 37 bp at ≤ 1Y. 20- or 60-day median spreads were 35–140 % worse (the spreads drift).
  Offshore was never the best base (the bonds move about half as much, β ≈ 0.45), so it is no base here.
- **The method** (`tto/kagitfiyat.py`, page "Kâğıt Fiyatlama", the first entry of the Tahvil menu, and the same block on
  the bond card):
  - fair yield = each base now + the bond's spread to it at the last close before today, weighted by the bond's years to
    maturity; a base that cannot be had gives its share to the other (said under the bond);
  - the bases: the neighbours' curve (quantcurve's live Nelson-Siegel fit, DİBS RV · Genel's, refitted without the bond;
    its τ searched on the last close and held) and the TRY OIS Bootstrap zero rate at the bond's maturity (a past day's
    on Motor's bootstrap of its closes);
  - one basis: BIST compound yields against zero rates compounded once a year; shown as compound and simple yields and as
    the clean price at DİBS RV's value date;
  - the quote: fair ± half the bucket's width; the good levels: Al at a yield ≥ fair + 2σ, Sat ≤ fair − 2σ, ±1σ noise;
    σ the bond's own next-day error over its last 60 closes, floored at its bucket's; the backtest: of the closes beyond
    ±2σ, how many had the gap to fair narrowed by the 5th close after (the gap measured with the signal's own spreads,
    against its bases), and the average bp;
  - the market: the Broker Chat board's best fresh bid / offer and DİBS RV's live Bloomberg bid / ask, in σ from fair, AL
    on an offer ≥ fair + 2σ, SAT on a bid ≤ fair − 2σ; the context: the spread to the neighbours' curve now against its
    20-day median;
  - TLREF floaters, FRNs and CPI linkers are not priced (their reason shown).
- **The defaults the desk may change** (named constants in `tto/kagitfiyat.py`):
  - weights `WEIGHTS`: ≤ 1Y 75 % OIS + 25 % neighbours; 1–5Y 100 % neighbours; over 5Y 75 % neighbours + 25 % OIS;
  - buckets `BUCKETS`: ≤ 1Y, 1–3Y, 3–5Y, 5Y+ (a bucket's upper bound inclusive);
  - σ floors `SIGMA_FLOOR`: 37 / 23 / 16 / 16 bp; `SIGMA_WINDOW` 60 closes, `SIGMA_MIN` 20 errors before σ is measured;
  - the good levels `BAND` 2σ, noise `NOISE` 1σ; the backtest's horizon `REVERT` 5 closes; the context's median
    `MEDIAN_DAYS` 20;
  - the quote's width `WIDTH_DEFAULT`: 10 bp in total in every bucket. **Administrators** change it on the page (kv
    `kagitfiyat.widths`, logged in `kagitfiyat.log`), as RET's width.
- **Conventions settled while building it** (the spec did not say; ask before changing):
  - the width is in bp of the compound yield, bid to ask (bid = fair + width / 2), any value 0–200 bp to one decimal (not
    RET's multiple of 5);
  - "the last close" is the last day before today's market day with the bond's close; today's own close (the history
    keeps today's running value) never counts;
  - a past day's OIS base needs every quoted OIS tenor's close that day (as the analysis); without it that day has the
    neighbours alone;
  - a bond with no price on DİBS RV still gets a fair: its neighbours' curve now (the curve of all the others) plus its
    last close's spread; its price then comes from the bond's own cash flows (quantcurve's BIST rules) at DİBS RV's value
    date;
  - the history's yields are read in the convention of the sheet's yield they are nearest (quantcurve's
    `detect_convention`, as the quant fit reads them);
  - the backtest counts every close beyond ±2σ (overlapping signals of one episode count each), σ as known that day.
- **What the record says so far** (the desk copy of 17.11, one year, small samples): the backtest's hit rate was about
  40–50 % (e.g. 50 % of 16 at 1–3Y, 40 % of 5 at 5Y+). So the ±2σ levels mark "unusual against fair now", not a
  proven reversion signal - say so when asked, and don't tune the band on this sample. The fair level itself held
  with a next-day error of about 16–23 bp over 1Y.
- **Öngörülen and the two ASW curves** (asked the same evening, after seeing the page):

  > "Bu adil fiyat bir süre sonra ulaşmasını tahmin ettiğimiz fiyat gibi de olmalı. Bir adil fiyat, bir de öngörülen fiyat
  > olacak yani, OIS ve FX swap curve'üne göre fiyatları da ayrıca gösterilsin"

  - **Adil** stays as it is (where the bond should trade now). **Öngörülen**: the yield and price we expect it to reach
    after a while. **OIS'e göre / FX swap'a göre**: shown apart, exactly DİBS Trading's columns of those names
    (`rvfair.fair` and the trading summary's own cells, `Service._fair_cells`: the same values, tips and reasons).
  - **Measured first, on the desk's history** (a backup copy of its database of 19.11.2026: the same 16 DİBS, bases and
    basis as above; 256 closes, 10.11.2025–16.11.2026). Horizons H = 5, 10, 20 closes. Models, each on the bond's
    spread to the neighbours' curve `s = y − nbr` (`kagitfiyat.project`): M0 no change; M1 `nbr + μ + (s − μ)·φ^H` (AR(1),
    μ and φ from a rolling 60 or 120 closes, φ held within [0, 1]); M2 the roll-down only, `roll + s` (`roll`: the bond's
    yield on the same curve at the horizon's value date); M3 M1 with the roll-down; M4 M3 `+ β × (OIS forward zero from the
    horizon to maturity − today's OIS zero for the same remaining life)`, β the bond's daily yield changes on its OIS
    zero's, rolling. Every forecast out of sample (its parameters from the closes up to the forecast day); one sample for
    all models (from a bond's 120th close on: 181–362 forecasts per cell). RMSE in bp of the compound yield:

    | | 1 hafta (H 5) | 2 hafta (H 10) | 1 ay (H 20) |
    |---|---|---|---|
    | ≤ 1Y | M2 84 vs M0 86 (+1,9 %) | M2 120 vs 124 (+2,8 %) | **M4/120 166 vs 179 (+7,4 %), hit 71 % (177)** |
    | 1–3Y | M4/60 86 vs 87 (+0,4 %) | M4/60 118 vs 120 (+1,4 %) | **M4/60 149 vs 164 (+9,0 %), hit 64 % (259)** |
    | 3–5Y | M4/60 78 vs 78 (0,0 %) | M2 101 vs 101 (0,0 %) | M2 133 vs 132 (−0,9 %) |
    | 5Y+ | M2 71 vs 71 (+0,1 %) | M2 95 vs 95 (+0,3 %) | M2 122 vs 122 (+0,3 %) |

    (each cell: the best model but M0, its RMSE against M0's, the gain; hit: of its calls of a move ≥ 5 bp, the share
    the yield went that way). The spread's own reversion (M1, M3) was worse than no change almost everywhere (−1 to
    −18 %); the OIS forward's drift (M4) is what helped, at 1 ay and short maturities.
  - **The rule, fixed before measuring** (`kagitfiyat.choose`): per bucket and horizon the lowest out-of-sample RMSE if it
    beats M0 by 5 % or more; else M2 shown as "eğri ve fark değişmezse", saying plainly that no model beat no change
    there. **Chosen** (`PROJECTION`): ≤ 1Y and 1–3Y at 1 ay M4 (windows 120 and 60); everywhere else M2, said. **The
    page opens on 1 ay** (`DEFAULT_H`): the best gain over M0 pooled over the buckets (+4,6 %; 1 hafta +0,4 %, 2 hafta
    +0,7 %). All three horizons stay on the switch.
  - **The honest record**: a week's error is 70–90 bp, a month's 120–180 bp, and only short bonds at a month beat no
    change - by 7–9 % on half a year of overlapping forecasts (about six independent months), when the PPK path the OIS
    curve priced largely came true (in the last quarter the gain was larger, +12–18 %). The τ of the neighbours' curve
    was searched on the last close and held (as the page does): a slight look-ahead in the curve's shape. So Öngörülen is
    "the likeliest level on this evidence", not a call; say so when asked, and don't tune it on this sample.
  - **The page** (`KagitFiyat._projection`): from the yield now (DİBS RV!T; without one, the neighbours' curve now plus
    the last close's spread), the neighbours' curve now and its roll-down to each horizon's value date (`neighbours`'
    `ahead`), the window's AR(1) and β of the bond's closes (`fit_window`, kept per history revision) and today's OIS
    Bootstrap (`ois_move`); the projected yield in compound and simple, its clean price at the horizon's value date (the
    bond's own cash flows then, BIST's rules - at today's value date the same price as DİBS RV's), the change in bp and
    the K/Z of 1 mn nominal (the two yields' prices on that date; no carry, no funding), the model and its record
    ("geri test: RMSE x bp, değişmezse'ye göre %y daha iyi, yön isabeti %z (n)"; `record_text`).
  - **Conventions settled while building it** (ask before changing): the horizon's day is today + H TRY business days
    (the history's holidays), its value date by the bond's source (ISL0 the same day, else the next week day); a window
    shorter than its length (a newer bond) uses the closes there are, from 21 consecutive ones on, and the line says how
    many; a bond whose closes cannot give the model's AR(1) or β, or with no OIS curve now, shows M2 in its place with
    the reason and M2's own record; the switch's choice is kept per browser, the card follows the page's.
- Code: `tto/kagitfiyat.py`, `Service.kagit_fiyat` / `kagit_fiyat_widths`, `GET /api/kagit-fiyat` (`?isin=`: one bond, the
  card's), `POST /api/kagit-fiyat/genislik`, `tto/static/js/pages/kagitfiyat.js`, `tto/static/js/kagitblock.js`. Tests:
  `tests/test_kagitfiyat.py`, the browser test's Kâğıt Fiyatlama checks.

### Kâğıt fiyat yükleme (20.11.2026)

> "Bir de kağıt fiyat yükleme sekmesi açmamız gerekli. Bu sekmede BBG/İhale olarak iki seçim olacak. Her sabah ihale
> fiyatları yükleyeceğim, buna göre belirttiğim yield spreadine göre fiyatları alıp t0 yieldına spreadleri koyarak
> fiyatları belirleyecek. Tüm kağıtlar olmayacak, buraya tek tek veya liste halinde kağıtları ekleyebilmeliyim.
> Kağıtların descriptionı, vadesi de bana gösterilmeli. Fiyatı veya yieldı manuel olarak editleyebilmeliyim. Fiyatlar
> belirlendikten sonra sistem bunları ISIN,fiyatbid,fiyatask,yieldbid,yieldask olarak düzenleyecek ve her birini bir
> satıra yazacak. Bunu da bir txt dosyası olarak kaydedebileceğim. Zero coupon kağıtlar yield ile, diğerleri fiyat ile
> yazılacak, ve hangisi yazıldıysa diğerleri 0 yazılacak. Örneğin ISIN,100.200,100.400,0,0 olarak. İhaleden kağıt
> tanınamadıysa kağıdı tanıtabiliriz, bir kez tanıttıktan sonra da onu hep tanıyacak. Liste de ben çıkarana kadar
> eklenenler hep kalacak. Eğer bbg olarak seçim yaparsam, bbg last trade'i mid alacak. Eğer son trade bugün değilse, son
> ihale fiyatından itibaren curve'deki genel harekete göre fiyat basacak. Önce hesapla demeliyiz, daha sonra fiyatları
> ve yieldları göndermeden kontrol edip öyle kaydedeceğiz."

The four answers the same night:
- spreads: "İki tarafa da ayrı ayrı koyacağım, hepsine aynı spread başta ayarlanabilir, daha sonra tek tek
  değiştirebilmeliyim listeden";
- TLREF / TÜFE: a price spread;
- bill yields (the auction list and the txt): simple (basit);
- BBG mode: ask Bloomberg for the bonds off DİBS RV's trading list (`LAST_PRICE` + `LAST_TRADE_DATE`, 2 hits a bond a
  Hesapla) - approved.

The auction text pasted every morning: lines `<dd/mm/yy(yy)>[zc| TLREF| cpi].t1|.t2  <value>`, other lines ignored ("Auction
prices:", "** Min 50 mio, Increment 1 mio", "Auction starts in a minute..."). A bill's / zero coupon's value is its simple
yield (31.500 = 31.5 %), the others' a clean price; .t1 values T+1, .t2 T+2 from the paste day.

- **What it does** (`tto/fiyatyukleme.py`, page "Kâğıt Fiyat Yükleme", the Tahvil menu's entry right after Kâğıt Fiyatlama):
  - each user's own list (kv `fiyatyukleme.list:<user>`), a bond until its owner takes it off; a bond off the desk's catalog
    comes in by `Service.bond_list_add` (Bloomberg's facts once a new ISIN, it joins Tüm Kâğıtlar) - not in replay;
  - spreads: yield-quoted (fixed coupon, bill, zero) bid yield = t0 + bid bp, ask yield = t0 − ask bp; price-quoted (TLREF,
    FRN, TÜFE) bid price = t0 − bid, ask price = t0 + ask; one default each, a row's own on either side;
  - İhale: each line matched by maturity and tag (no tag: the fixed coupon bond, else the bill / zero of that day); an
    unrecognised one named once - desk-wide, for good (kv `fiyatyukleme.labels`); .t1 used, .t2 only without one; the
    day's values kept per ISIN (kv `fiyatyukleme.auctions`: day, label, value, .t1 / .t2);
  - BBG: the trading list's own `LAST_PRICE` / `LAST_TRADE_DATE` (DİBS RV!AS / I); others one reference request on
    Hesapla; a trade of today is the mid; else the newer of the last trade and the last auction kept (an auction on
    the trade's day or later wins) moved with the bond curve since its day, TRY OIS without it. Changed on
    20.11.2026 after the first morning at the desk: "dün işlem olmasına rağmen son işlem dün diyor ve göstermiyor" -
    before, a trade not of today with no auction kept gave no price;
  - Kaydet: the desk's line format, the saves of the day kept per user (kv `fiyatyukleme.saved:<user>`).
- **Conventions settled while building it** (the spec did not say; ask before changing):
  - **t0** is today's own value date: today, or the next TRY business day when today is not one (Motor's holiday list,
    as DİBS RV's value dates). T+1 / T+2: `WORKDAY(today, 1 | 2, TRY)`.
  - **Yields** are BIST's simple yields (the auction sheet's, DİBS RV!S): bill / zero `(100/P − 1)·365/days`; fixed coupon
    the rate that discounts its coupons at (1 + y/f) a period - quantcurve's `Bond` (coupons every round(364/f) days back
    from the maturity, semi-annual for every fixed coupon DİBS) and `quantcurve.accrued` (c/f × the share of the period
    gone). A yield-quoted bond's t0 is the same simple yield as at the line's value date; a price-quoted bond's t0 is the
    auction's (or the trade's) clean price as it is.
  - **Default spreads** until a user sets theirs: 5 bp / 5 bp (yield-quoted), 0,05 / 0,05 (price-quoted); a spread within
    ±500 bp / ±10 price points.
  - **The desk's labels** are keyed by the label's date and tag ("10/02/2027 zc": dd/mm/yy and dd/mm/yyyy alike) and are
    the desk's: anyone may name or forget one (as the bond list: "everyone edits it"); who and when are kept.
  - **The stored auction values**: all recognised lines (the first line per bond and value date); the same day pasted
    again replaces that day's; 30 kept per bond. "The last auction price" is the latest day's .t1, its .t2 without one.
  - **BBG's request**: securities named as Tüm Kâğıtlar names them (`EK_EVREN!U`: bills / zeros on `C2`, default ISL0,
    the rest on `E2`, default ISL1; DİBS RV!N2's identifier style); a trade's value date ISL0 the trade day, else the next
    TRY business day (DİBS RV!DC's rule). One request a Hesapla for all such bonds, the answers kept 5 minutes; no answer
    (the limit, a time-out, replay): said on the page, the rows fall back to the stale path.
  - **A bill's last trade** is read as a price (Bloomberg quotes TRY bills in price on ISL0: DİBS RV!AS 92,147 for a
    99-day bill); as a yield only when the price reading gives a yield outside −5 % … 100 % and the figure is a sane yield,
    or - both sane - when the yield reading is nearer the bill's own (DİBS RV!S, else its last auction). Said on the row.
  - **"Curve'deki genel hareket"**: the bond's model yield at t0 on the Nelson-Siegel fit now (DİBS RV · Genel's, on the
    trading list's yields) minus the same bond, the same cash flows from t0, on the same model with its τ held refitted to
    the auction day's closes (the history's; the last day before it with enough coupon bonds when that day has none) - the
    curve's move, not the bond's roll-down; an auction of today: no move. On the made-up closes of the tests, a 50 bp
    parallel move of the coupon bonds' yields moves a coupon bond ~50 bp and a bill or zero (the short end, which the
    coupon bonds do not reach) less, ~35–40 bp. Without that fit: the TRY OIS Bootstrap zero rate's change at the bond's
    maturity (Motor's bootstrap of that day's closes against the workbook's now, over the same days), added to the bond's
    compound yield and read back as the change of its simple yield - said on the row. Neither: the auction yield as it is,
    with a warning on the row.
  - **The file**: rows without the figures they are written with are left out and named; a crossed quote (bid better than
    ask) is written and named. The name carries the calculation's day (replay: 03.11.2026).
- **Eurobonds** (the same night):

  > "Eklenecek listede eurobondlar da olacak. Bunlar direkt bbgden fiyatlanacak. Bunlarda last trade yok direkt midden ve
  > spreadden gideceğiz"

  Asked whether their spreads are in price or yield, the desk first said price points, then corrected it: "Eurobondlar
  da yield spreadi". So:
  - a Eurobond (a USD / EUR Turkish sovereign: `US900123…`, `XS…`) comes onto the list by its ISIN; its facts are asked of
    Bloomberg **once an ISIN** and kept desk-wide (kv `fiyatyukleme.eurobonds`: description, currency, coupon, `CPN_FREQ`,
    `DAY_CNT_DES`, maturity, first / penultimate coupon dates, accrual start, `DAYS_TO_SETTLE`). It never goes into the
    DİBS catalog ("foreign-currency bonds are not taken"). A TR ISIN Bloomberg says is in a foreign currency comes in the
    same way. Without Bloomberg (replay) it cannot come in: the reason is shown;
  - **always Bloomberg, whatever the İhale / BBG switch**: mid = `PX_MID` (else (`PX_BID` + `PX_ASK`)/2, said) and
    Bloomberg's mid yield `YLD_YTM_MID` - never an auction or a last trade;
  - bid yield = mid yield + bid spread, ask yield = mid yield − ask spread, in bp, negatives allowed; **its own default
    pair** (2 bp / 2 bp until the user sets theirs: much tighter than DİBS), per bond in the list, remembered;
  - each side's clean price by the street convention (`fiyatyukleme.Street`: Excel's PRICE / YIELD - 30/360 US or ISMA's
    30E/360 or ACT/ACT by `DAY_CNT_DES`, `CPN_FREQ` coupons a year back from the maturity, simple interest in the last
    period), **anchored to Bloomberg**: price(y) = convention(y) + (PX_MID − convention(mid yield)). The mid is then
    Bloomberg's to the digit, and a convention that differs moves the sides by its curvature only. The anchor is in the
    row's tooltip and flagged beyond 0,05 price points. An edited yield or price of a Eurobond goes through the same
    anchored conversion at the same settlement;
  - in the txt: clean prices, yields 0 (`ISIN,99.875,100.125,0,0`).
  - **Conventions settled** (ask before changing): the settlement Bloomberg's mid is for is today + the bond's
    `DAYS_TO_SETTLE` business days (asked once with its facts; without it T+2, said) on its currency's calendar - USD the
    Fed's, EUR TARGET2 (the desk's lists, EK_TATIL); `DAY_CNT_DES` not given: a USD bond 30/360, any other ACT/ACT, said; a
    short first coupon accrues from the accrual start; an irregular last period is not modelled (the anchor absorbs it);
    `YLD_YTM_MID` empty: the mid yield from the price by the convention (anchor 0, said); no price but a yield: the price
    from the yield (anchor 0, said); floaters, perpetuals and TL bonds are refused with their reason.
- **Sabit fiyat** (20.11.2026, at the desk in the morning):

  > "Bir de sabit fiyat kısmı açmalıyız, bazı kağıtları direkt bu şekilde yüklenecek diye girip bırakabilmeliyim"

  - a "Sabit fiyat" section: a bond (any ISIN - no catalog or Bloomberg needed, below) with its fixed bid and ask, typed in the
    unit the txt writes it in - a bill's / zero coupon's simple yields (%), any other's clean prices (fixed coupon,
    TLREF, TÜFE, FRN, Eurobond) -, the page's number reading (a Turkish comma too). Kept with the user's list
    (`fiyatyukleme.list:<user>`, `fixed`) until changed or taken off;
  - on Hesapla, in either mode, each fixed bond is a row as it is, marked "sabit fiyat": never computed, never asked of
    Bloomberg (a fixed bond off the trading list costs nothing in BBG mode). In the list too: the fixed figures win, said
    on the row. Its other unit is shown for information only - a bill's price at t0 from the fixed yield, a fixed coupon
    bond's yield at t0 from the fixed price, a Eurobond's yield by the street convention at its settlement (not anchored:
    Bloomberg is not asked); a TLREF / TÜFE / FRN bond has none;
  - its cells stay editable, but an edit is that Hesapla's (and that file's) alone: the stored figures stay (said in the
    tooltip). "Sabitle" on a computed row stores its bid / ask as they are (edited or not) as that bond's fixed figures;
  - Kaydet writes a fixed bond's figures as they are, in the same line format, the other unit 0.
  - **Conventions settled** (ask before changing): a yield between −50 % and 500 %, a price between 0 and 1000; a crossed
    pair (bid better than ask) typed or edited in the table is kept and said; the fixed bonds join the list's order (kind,
    then maturity); İhale mode needs no auction text when only fixed bonds or Eurobonds are to be priced.
  - **Pasted from Excel** (the same day, with a photo of their sheet: FX-denominated domestic DİBS such as `TRT191127F19`,
    grouped USD / EUR):

    > "Sabitlemeyi de tablo olarak atacağım excelden kopyalayıp, bu da ayrıca tablo olarak gözükmeli ve ben de rahat
    > görebilmeliyim. Burada bid ve offer'ı ve ISIN'i kopyalayacağım"

    - a box for Excel's rows and **Ekle / Güncelle** (`fiyatyukleme.parse_fixed`): one bond a line, the cells split by tabs
      (else runs of spaces); the ISIN the first cell like one, the bid the first number after it, the offer the next
      number within ±10 % of the bid - so the sheet's lower block (ISIN | Bid | | Offer) and its upper one (ISIN | Bid |
      Bid Yield | Offer | T1 Yield | Stok) read alike; a dot or a Turkish comma as the decimal mark, the last one when a
      cell has both; a line with neither an ISIN nor a number (a header, "USD") ignored; one that cannot be read shown with
      why (no offer, an offer on the wrong side of the bid, a bad check digit) and not kept; a bond fixed already updated;
    - **no catalog and no Bloomberg** for a fixed row: only the ISIN and the two figures. The description is the catalog's
      name, else a Eurobond's facts if held, else "döviz DİBS" for `TRT…F…`, else blank; the maturity the catalog's, else
      read from a Turkish ISIN (TR, the type letter, DDMMYY: `TRT191127F19` → 19.11.2027); the unit a bill's / zero's
      yields (the catalog's kind, or a `TRB…` ISIN), everything else clean prices - shown on the row;
    - their own table, "Sabit fiyatlar": ISIN, description, maturity, unit, bid, offer (three decimals, edited in place),
      the file line each gives, × - apart from the computed list.
- Code: `tto/fiyatyukleme.py`, `Service.fiyat_yukleme`, `GET /api/fiyat-yukleme`, `POST /api/fiyat-yukleme/{ekle, cikar,
  sabit, sabit-sil, sabit-yapistir, ayar, tanit, hesapla, cevir, kaydet}`, `GET /api/fiyat-yukleme/dosya`, `Provider.reference` (`tto/marketdata`),
  `tto/static/js/pages/fiyatyukleme.js`. Tests: `tests/test_fiyatyukleme.py`, the browser test's Kâğıt Fiyat Yükleme
  checks.

### Kâğıt fiyatlama: eğri fiyatı - a price for the bonds that have none (20.11.2026)

> "Kağıt fiyatlama kısmını çok anlayamadım, curve'e göre fiyatı olmayanların da fiyatını bulmak içindi asıl"

Its main job is a **curve price for bonds that have no price of their own**. The desk's two answers:

- **(a) the whole catalog:** every fixed coupon bond, bill and zero coupon bond of the desk's bond list, not only DİBS RV's
  trading list;
- **(b) Kâğıt Fiyat Yükleme** uses that curve price, labelled **"eğri fiyatı"**, when a bond would otherwise get no price.

**The rules** (`tto/kagitfiyat.py`: `_universe`, `_curve_row`, `base_of`, `_answer`, `curve_quotes`):

- **The main table** of Kâğıt Fiyatlama, one row a bond, kind by kind, by maturity: **Kâğıt / ISIN / Vade · Piyasa ·
  Eğri · Fiyat · Fark · ▸**.
  - The bonds: the desk's list (Tüm Kâğıtlar: the catalog less the bonds taken off and the matured ones) - its fixed
    coupon bonds, bills and zero coupon bonds - and the trading list's.
  - **Piyasa**: today's market price, its compound yield (DİBS RV's own price ↔ yield on the trading list; the bond's
    cash flows by BIST's rules otherwise) and source. The middle of a two-sided quote (a side where no order stands is
    "–"), else today's last trade, else "—". The trading list's from DİBS RV (bid `K`, ask `L`, last `AS` / `I`); the
    others from Tüm Kâğıtlar (`EK_EVREN` `I`, `J`, `K`, `L`): cells the pages already ask for, no new Bloomberg request.
  - **The curve**: the Nelson-Siegel fitted now to the bonds with prices (Kâğıt Fiyatlama's live fit, the same as before)
    at the bond's own cash flows from its value date; a bond in the fit is read on the fit without it (leave one out), a
    bill / zero and a bond off the fit on the curve of all of them. **The bucket base**, with the fair model's weights
    (`WEIGHTS`, `base_of`): ≤ 1Y 75 % the TRY OIS zero rate (the Bootstrap, at the bond's maturity) + 25 % the curve;
    1–5Y the curve; 5Y+ 75 % the curve + 25 % OIS (a base that cannot be had gives its share to the other).
  - **Eğri** (the column): a fixed coupon bond's curve; a bill's or zero coupon bond's bucket base.
  - **Fiyat**, with its label: the market price ("**piyasa**"); else the base + the bond's own last spread to that base,
    whatever its kind ("**eğri + son fark <dd.mm>**": the desk's history showed the last spread the best predictor; for a
    bond of the trading list this is its adil in the details); else - no history of its own - **by its kind**:
    - a fixed coupon bond: the curve alone ("**eğri**");
    - a bill or zero coupon bond: the base + the median spread to their bases of today's market-priced bills and zero
      coupon bonds of its bucket, the bond itself left out ("**eğri + akran farkı**"; the how line names the peers' number
      and the median, e.g. "OIS %75 + eğri %25 … + akran farkı −613 bp (2 bono / kuponsuz …)"); none priced: the base
      alone ("**eğri**", with the warning that no peer was priced).

    As compound and simple yield and a clean price at the bond's value date.
  - **Tipik hata** on every curve-priced row (`validate`, `error_bands`, `error_text`): "tipik hata ±X bp", X the median
    absolute error of the row's rule on today's market-priced bonds of its bucket and kind group, each priced without its
    own quote (the curve on the fit without it; a bill off the other bills; "son fark": today's base + its spread at the
    last close). Measured live on every page answer (arithmetic on the rows: no extra fit); on fewer than 2 bonds
    "tipik hata ölçülemedi". In the how line, so in the Fiyat cell's tooltip, the card's line and the upload's row.
  - **Fark**: market − Eğri (bp), when there is a market price.
  - **▸ details**: everything the page showed before (adil, kota, iyi seviyeler, σ, isabet, öngörülen, OIS'e / FX swap'a
    göre, the "nasıl fiyatlandı" lines), the same cells and numbers, closed by default; a bond off the trading list has
    none (said).
  - **TLREF floaters, TÜFE linkers, FRNs**: left out of the table, counted in one line under it with the reason ("kuponları
    değişken ya da reel: nominal eğriye göre fiyatlanmaz"; they are on Tüm Kâğıtlar).
  - On top, a short line: "Fiyatı olmayan kâğıtlara eğriden fiyat: …".
- **The bond card's block** has the curve price line first ("Eğri fiyatı: …"); the rest as before. A bond of the desk's list
  off the trading list: that line alone.
- **Kâğıt Fiyat Yükleme's fallback** (`FiyatYukleme._curve_fallback`), in İhale and BBG mode: a yield-quoted row (fixed
  coupon, bill, zero coupon) that would get no price - no trade and no auction kept, or missing from today's auction
  text - gets the curve price: the "Fiyat" column's answer without the market (the base + the bond's own last spread;
  else a fixed coupon bond's curve, a bill's base + its peers' median spread, or the base). Its simple yield at its value
  date is taken as t0's, as an auction line's is; its spreads then apply as for any yield-quoted bond. The row says
  which - "**eğri fiyatı (son fark)**", "**eğri fiyatı (akran farkı)**", or "**eğri fiyatı**" (a fixed coupon bond's
  curve, a bill's base alone) - with the how line and its typical error, so the desk sees it before saving. Price-quoted
  bonds and Eurobonds are unchanged; fixed prices still win.

**Conventions settled while building it** (ask before changing):

- (Since the next section: the last known spread is the most recent point of every source - a trade, an auction, a close.)
  "The last known spread" of a trading list bond is Kâğıt Fiyatlama's spread to each base at its last close before today
  (the neighbours' curve, OIS), blended by the bucket's weights. A bond off the list has one only when the history kept
  its series - a bond once on the list, named as DİBS RV named it ("<ISIN> @<source> ISIN", "<ISIN> ISIN") - measured at
  its last close on that day's curve of the trading list's closes (not in that fit) and that day's OIS zero rate at its
  maturity (Motor's bootstrap of that day's closes), its convention the trading list's bonds' of its kind. The desk copy
  has no such series: there, a bond off the list is priced by its kind.
- The peers are today's market-priced bills and zero coupon bonds only (the main table's Piyasa), their spreads to their
  own bases now; their history is not used. Fixed coupon bonds have no peers.
- A bond with a market price still has the upload's curve price (the base + its last spread, else its kind's rule): the
  upload never takes the market from here.
- A bond off the trading list is dated as Tüm Kâğıtlar dates it: bills and zero coupon bonds on its source `C2` (ISL0: the
  same day), the others on `E2` (ISL1: the next week day).
- A fixed coupon bond of the catalog without a coupon gets a row with no price and why ("kuponu bilinmiyor").

**How the rule by kind was decided** (the coordinator, 20.11.2026). The first build read every bond with no price and no
history on the coupon bonds' curve alone: bills and zero coupon bonds came out 136–255 bp too high in yield (the curve's
short end), a price the upload would have published. A bucket base + peer spread rule was then built for every kind and
validated; it fixed the bills and made every fixed coupon bucket worse. The validation decided it: **bills and zero coupon
bonds take the bucket base + their peers' spread, fixed coupon bonds the pure leave-one-out curve**; "eğri + son fark"
stays for any bond with history. No other tuning.

**Validation** on the desk copy (replay day 03.11.2026; `KagitFiyat.validation`, the same check the page runs live for the
typical errors): every market-priced bond priced as if it had no price and no history - itself out of the Nelson-Siegel
fit and out of its peers. Absolute error against its market yield (compound), bp, median / max:

| Bucket, kind | Bonds | Rule in use | Before: the curve alone | Final |
|---|---|---|---|---|
| ≤ 1Y, bills / zero coupon | 2 | base + peers' median | 196 / 256 | 43 / 43 |
| ≤ 1Y, fixed coupon | 4 | the curve | 76 / 104 | 76 / 104 |
| 1–3Y, fixed coupon | 3 | the curve | 23 / 39 | 23 / 39 |
| 3–5Y, fixed coupon | 3 | the curve | 96 / 139 | 96 / 139 |
| 5Y+, fixed coupon | 3 | the curve | 56 / 165 | 56 / 165 |

- **Bills:** 196 / 256 → 43 / 43 bp (each bill's one peer is the other bill: TRB100227T13 +136 → −43, TRB170327T15 +255
  → +43). The bills trade about 600 bp under their OIS-heavy base (−592, −635 bp), so the median carries it.
- **Fixed coupon bonds:** the peer rule tried on them was worse in every bucket - ≤ 1Y 206 / 242, 1–3Y 27 / 51, 3–5Y
  126 / 195, 5Y+ 131 / 177 (each peer's curve also fitted without the bond and the peer). Their peers were 2–3 bonds whose
  spreads to the base were far apart (≤ 1Y −153, −168, −366, −407 bp; 3–5Y −96 … +139; 5Y+ −125 … +118). They keep the
  curve alone; its error stands as above (≤ 1Y and 3–5Y near 100 bp: the typical error says so on each row).
- **"Son fark"** (a bond with its own history: today's base + its spread at the last close, against today's market), the
  same day: ≤ 1Y bills 35 / 50 (2), ≤ 1Y fixed coupon 18 / 112 (4), 1–3Y 5 / 11 (3), 3–5Y 21 / 25 (3), 5Y+ 14 / 16 (3).
- On the desk copy the main table's answers: piyasa 15, eğri + son fark 1, eğri + akran farkı 2, eğri 11. E.g.
  TRT060127T10 (zero coupon, no history): OIS %75 + eğri %25 40,80 + akran farkı −613 bp (2) = 34,66 · tipik hata ±43 bp;
  TRT240227T17 (fixed, off the list): eğri 36,32 · tipik hata ±76 bp; TRT081128T15 (trading list, no price): eğri 39,90 +
  son fark −49 bp = 39,41 · tipik hata ±5 bp.

Code: `tto/kagitfiyat.py` (`market_of`, `base_of`, `peer_spread`, `validate`, `error_bands`, `error_text`, `validation_table`, `_universe`,
`_curve_rows`, `_curve_row`, `_answer`, `validation`, `_off_closes`, `_off_spreads`, `curve_quotes`),
`tto/fiyatyukleme.py` (`_curve_fallback`), `tto/static/js/pages/kagitfiyat.js`, `tto/static/js/kagitblock.js`
(`curveLine`), `tto/static/js/pages/fiyatyukleme.js`. Tests: `tests/test_kagitfiyat.py`, `tests/test_fiyatyukleme.py`, the
browser test's Kâğıt Fiyatlama and Kâğıt Fiyat Yükleme checks.

### Kâğıt fiyatlama: son fark from every source (20.11.2026)

> "Fiyatı olmayanı eğriden fiyatlarken eğriye göre önceden ne kadar pahalı ucuz olduğuna da bakmamız gerekli. Buna da
> bakıyor muyuz" - and then: "Aynı şey fiyatlama kısmı için de geçerli"

They mean Kâğıt Fiyatlama and the upload's pricing. Before this, "eğri + son fark" used only the history's stored closes
(DİBS RV's trading list plus series it kept): on the desk copy only 1 of 14 unpriced bonds had one.

**The rule** (`tto/kagitfiyat.py`: `_points`, `pick_point`, `_own`; one function for every use):

- **A bond's points**, none of them a new Bloomberg request - each its yield at its value date and its spread to each
  base (the bucket base's parts: the Nelson-Siegel curve and the OIS zero rate) on that point's day:
  1. **close** - the history's last close (as before);
  2. **auction** - the last auction value Kâğıt Fiyat Yükleme keeps per ISIN (`fiyatyukleme.KEY_AUCTIONS`): a bill's or
     zero coupon bond's value is its simple yield at the line's value date, a fixed coupon bond's a clean price there
     (`auction_yield`);
  3. **trade** - Bloomberg's last trade: DİBS RV's `LAST_PRICE` / `LAST_TRADE_DATE` for the trading list, Tüm Kâğıtlar's
     for the rest (the cells the pages already read), and the answers Kâğıt Fiyat Yükleme gets in BBG mode, now kept per
     ISIN (`fiyatyukleme.KEY_TRADES`, `FiyatYukleme.keep_trades`: a later trade replaces an earlier one) beyond the
     5-minute cache; the price read at the trade's value date (ISL0 the same day, else the next week day) as the upload
     reads it (`trade_yield`: a bill's figure that can only be a yield is one);
  4. **close kept** - from now on, the daily close of every fixed coupon bond, bill and zero coupon bond of the desk's
     list (`KagitFiyat.record_closes`, kv `kagitfiyat.closes`, the last 120 days per ISIN): the Piyasa column's price -
     the middle of a two-sided quote, else the day's last trade; DİBS RV for the trading list, Tüm Kâğıtlar for the rest
     -, its compound yield and value date. Taken once a day after 17:35 on a business day, or when the workbook's day has
     turned with the day before not kept (its prices then are still that day's last), by the warm thread - live mode only;
     no Bloomberg request. The history's own daily-close machinery asks Bloomberg (BDH), so it does not fit: kv instead.
- **The spread**: the point's yield − the base on its day - that day's close curve (the history's Nelson-Siegel fit of
  the trading list's closes, kept with the day; a bond of the trading list on the fit without it, as its closes are
  measured) and that day's OIS zero rate at its maturity. A point of **today** (today's auction, today's trade) is
  measured on the curve now, said - its price is then its own yield. A day without a close curve: the point is not
  measured, said.
- **The most recent point wins**; the same day a trade, then an auction, then a close (the history's, then the one kept) -
  the how line says which was taken and what else that day had.
- **The price** = the bucket's base now + that spread (blended by the bucket's weights, as the fair model blends them).
  Label: "eğri + son fark (ihale 20.11, bugün)", "(son işlem 14.11, 4 iş günü önce)", "(kapanış 19.11, 1 iş günü önce)" -
  the source, the day, its age in TRY business days; the typical error as before (that rule's, measured on today's
  market-priced bonds from their points before today).
- **Everywhere**: the Fiyat column, the bond card's line, Kâğıt Fiyat Yükleme's fallback ("eğri fiyatı (son fark, ihale
  20.11)"), the fair (Adil) of the details and Öngörülen's start without a yield now - all through `_points`.
  - **The fair takes the most recent point before today.** A trade or auction of today would make the fair that trade's
    own yield (on the curve now the base cancels); the fair stays the forecast its σ and backtest measure ("today's base
    + the last spread before today"). One argument (`pick_point(points, before)`) changes it if the desk wants today's.
  - The BBG and İhale paths that already move a trade or an auction with the curve stay as they are (the same idea).

**On the desk copy** (replay day 03.11.2026): of the 14 bonds with no price, 1 has a son fark - TRT081128T15, now from DİBS
RV's last trade of 02.11 (the same day as its last close: the trade taken). No more come from the new sources there: the
auction store is empty in that copy, Tüm Kâğıtlar's last-trade cells of the bonds off the trading list are empty in that
file, and no Bloomberg answer or daily close was kept yet - those fill from now on. DİBS RV's last trades: 15 of today, 3
of 02.11, 1 of 26.10 (older than that bond's last close: the close taken). The fair moves on 3 bonds (their 02.11 trade
taken over the 02.11 close): TRT050527T33, TRT131027T36, TRT081128T15.

**Validation** (the same leave-one-out check, `KagitFiyat.validation`): the market-priced bonds whose son fark now comes
from a trade point before today - TRT050527T33 and TRT131027T36, both 02.11 - priced at today's base + that spread,
against today's market: +0,2 and +11,2 bp (median 5,7, max 11,2); the same two from their 02.11 close: −0,4 and +10,9
(median 5,6, max 10,9). Too few to tell the sources apart: the trade and the close of the same day sit within half a bp.
The 13 others (son fark from the close): median 16,2, max 111,9 bp. The auction source is tested on seeded data
(`tests/test_kagitfiyat.py`).

Code: `tto/kagitfiyat.py` (`business_days`, `pick_point`, `point_label`, `auction_yield`, `trade_yield`, `_sources`,
`_points`, `_own`, `_curve_rows`, `_row`, `_projection`, `record_closes`, `warm`), `tto/fiyatyukleme.py` (`KEY_TRADES`,
`keep_trades`). Tests: `tests/test_kagitfiyat.py` (the order and ties, the yields at value dates, every source on the
made-up history, today's auction on the curve now, the daily close recorder), `tests/test_fiyatyukleme.py` (the kept
Bloomberg trades and the fallback's label).

### Günlük İşlemler: "Benzerini gir" and "Ters işlem" (23.11.2026)

Proposed to the desk and approved (as relayed): "A trade row has only Düzenle and ✕. Proposal: one click fills the entry
form from that trade, either as a new trade or with the side reversed, for repeats and unwinds."

- **Where.** Two row actions on every trade, today's and past days', wherever the form is open (today, a period up to
  today). Both fill the form as a new trade (never an edit); nothing is saved until "İşlemi kaydet". A line over the form
  says what it was filled from.
- **No price comes along.** The form prices the copy on today's market as any new trade (the OIS mid offered, RET
  priced by itself, a typed price typed again).
- **Benzerini gir**: the trade's terms - product, structure, side, size as typed, counterparty, note - and its instrument
  as entered; a past day's: the same tenor from today's spot (a forward's tenor read back from its own spot: whole months
  or weeks, else the same days).
- **Ters işlem**: the other side, the same size (a forward's first-currency amount, so the position closes exactly; an
  OIS's nominal, a spread / fly sized by DV01 that DV01), the same end. A start that has passed is today's spot: a past
  day's TRY OIS is a **broken date to its own maturity** (Fiyatlama's broken-date pricing: quarterly back from maturity,
  short period first - the table above), each leg of a package; a FRA not started keeps its two dates, one started runs
  from today's spot to its end. A trade that has run off has no offset: its button is left out, the cell's tip says why.
- Code: `blotter.copy_specs` (the listing's `copy`, `Service._blotter_copies`), `blotter.js` `copyFrom`. Tests:
  `tests/test_blotter_copy.py`, the browser test's block.

### Günlük İşlemler: a period's summary tables (23.11.2026)

> "Bir de günlük işlemlerde daha fazla tarihe bakarken bugündeki alttaki tablo gelmiyor, onu da düzelt."

- **What was missing.** In a period (Aralık) the workbook's own summary tables under the lists (forward buckets, OIS
  summary, Bonds, CPT × tenor) were left out - the sheet holds today's trades only. The cost tables were there.
- **Now.** A period - and a day gone by without its end-of-day archive - shows the same tables, the sheet's own
  formulas with its lists filled with the trades shown, in an engine layer of its own over the shared calculation (the
  sheet stays today's; the last four periods kept, a refresh evaluates only what changed). Said over them: what they
  cover, buckets and days counted from today, each trade with its own amounts, rates and DV01; trades the lists have no
  row for are counted. A day gone by with its archive shows its archive, as before.
- Code: `Service._blotter` / `_blotter_panels` / `_blotter_layer` / `_blotter_scope`, `blotter.sheet_values(left_out)`.
  Tests: `test_a_period_shows_the_sheets_tables_over_its_trades` (test_blotter), the browser test.

## Process

- **The single-file install is a requirement.** Everything must install from GitHub's single `kurulum/tto_kur.txt`
  ("Her şeyin daha sonra GitHub'dan indirilip tek txt'ten yüklenebilmesi olayını da unutmayalım. Bu bir şart").
- **One push carries every new request of the day** ("Tüm yeni istekleri tekte gönder", "Tüm anlattıklarım tek
  push'ta olsun"). Each update means restarting the live dashboard.
- **The main session merges and runs the last test after every session is done, then pushes** ("tüm sessionlar
  bittikten sonra birleştirme ve son test bu oturumda yapacak. github'a da ondan sonra pushlanacak").
  - It pushes without waiting for approval ("Daha sonra push için onayımı beklemene gerek yok").
  - It first makes sure nothing broke ("Her şey bittikten sonra hiç bir şeyi bozmadığımızdan da emin ol").
- **Where the dashboard runs:**
  - Normally on the office computer.
  - The home computer, the one these sessions run on, also has Bloomberg.
  - The office machine may have no `D:` drive.
  - The office machine has no command window, only Anaconda Prompt ("Normal cmd'ye erişim olmadığı için anaconda
    prompt ile runlıyorum, bat'ı da bunun gibi değiştirelim", 19.11.2026). So `run.bat` opens Anaconda first
    (`TTO_CONDA`, else the usual folders), and install or run commands for the user are given for Anaconda Prompt.
- **Rows move.** A change to the PPK calendar, a VİOP roll or a change to the bond lists moves users' data between
  rows. Every feature that stores anything by cell, row or position must handle that move and test it (see
  [architecture.md](architecture.md#row-keys)).
