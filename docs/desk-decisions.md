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
