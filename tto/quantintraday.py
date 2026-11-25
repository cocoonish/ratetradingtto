"""Intraday quant signals, from the live values the dashboard already reads - no Bloomberg request of their own.

**Bars.**  Each minute the quant worker reads the values now (the OIS / offshore quotes of the source page, the FX spots
and USDTRY's 1M points it streams); live, on a week day between 09:30 and 18:00, they are written down as one-minute
closes in a small SQLite file next to the store (``quant_bars.sqlite3``), the last ``KEEP_DAYS`` trading days kept.
Five-minute bars are built from them.  Replay mode reads no live prices: no bars, and the page says so.

**Families** (each a "gün içi" signal with its own horizon in minutes and its own stops):

    izscore  each series' distance from its 60-minute mean (within the day) against the last 20 days' distribution of
             that distance: fade it (Ornstein-Uhlenbeck half-life in bars)
    iorb     the opening range (the first 30 minutes): a break out of it by a quarter of its width follows, while the
             past 20 days' breakouts carried on to the close on average (target: the range's width further; stop: its
             middle)
    irv      offshore − OIS (3M, 1Y) and the curve's 1s2s / 2s5s on 5-minute bars against their 20-day distribution: fade
    ipath    USDTRY against the path its carry implies from the day's open (the forward premium a minute at a time): a
             spot ahead of it by more than the bars' noise is sold back to it, one behind bought (the gap's
             Ornstein-Uhlenbeck half-life on the past days' bars, read inside each day)

Mean-reversion entries are held back in the PPK announcement window of a meeting day (13:45 – 15:30) and no new
intraday entry is taken after 17:00.  Their half-life is in bars and is held to a horizon in bars (``Monitor.horizon``):
the family's own holding when it has one (ipath: an hour), else the bars left in the session.
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import sqlite3
import threading
from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple

from . import quantfam as qf
from . import quantmath as qm

KEYS = ("OIS:3M", "OIS:6M", "OIS:1Y", "OIS:2Y", "OIS:5Y", "OFF:3M", "OFF:1Y", "FX:USDTRY", "FX:EURTRY", "FX:EURUSD", "FXP:USDTRY:1M")
ZKEYS = ("OIS:3M", "OIS:1Y", "OIS:2Y", "OIS:5Y", "OFF:3M", "FX:USDTRY", "FX:EURTRY", "FX:EURUSD")
SPREADS = (("OFF:3M", "OIS:3M", "Offshore 3M − OIS 3M"), ("OFF:1Y", "OIS:1Y", "Offshore 1Y − OIS 1Y"), ("OIS:2Y", "OIS:1Y", "1s2s"),
           ("OIS:5Y", "OIS:2Y", "2s5s"))
KEEP_DAYS = 20
LEAD_KEEP_DAYS = 5                        # the keys only the lead-lag analysis reads (5-minute bars): their last days
BAR = 5                                   # minutes a bar
SESSION = (9 * 60 + 30, 18 * 60)          # the minutes of the day the bars are kept for
OR_BARS = 6                               # the opening range: the first 30 minutes
MA_BARS = 12                              # the 60-minute mean
NO_NEW_AFTER = 17 * 60
PPK_WINDOW = (13 * 60 + 45, 15 * 60 + 30)
ORB_ENTRY = 1.5                           # a break out of the range by a quarter of its width
MIN_BREAKS = 5
PATH_BARS = 12                            # ipath: half the gap to the path closes within an hour - its holding, and its
                                          # half-life when the bars cannot measure one


def _kind(key: str) -> str:
    return "fx" if key.startswith("FX:") else ("pts" if key.startswith("FXP:") else "rate")


def _diff(kind: str, a: float, b: float) -> float:
    """A move in P&L units: bp for a rate, % (log) for a spot."""
    if kind == "fx":
        return math.log(b / a) * 100.0 if a > 0 and b > 0 else 0.0
    return (b - a) * 100.0


# ---------------------------------------------------------------------------------------------- the bars
class Bars(object):
    """One-minute closes of the keys above in SQLite: ``(key, minute, value)``, the minute a local ``YYYY-MM-DD HH:MM``."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS bars (key TEXT NOT NULL, t TEXT NOT NULL, v REAL NOT NULL, PRIMARY KEY (key, t)) WITHOUT ROWID")
        self._db.execute("CREATE INDEX IF NOT EXISTS bars_t ON bars (t)")
        self._db.commit()
        self._pruned = ""

    def record(self, when: _dt.datetime, values: Dict[str, float], also: Collection[str] = ()) -> int:
        """The minute's closes of the keys above - and of ``also`` (the lead-lag analysis' own, kept fewer days)."""
        t = when.strftime("%Y-%m-%d %H:%M")
        rows = [(k, t, float(v)) for k, v in values.items() if (k in KEYS or k in also) and v is not None and math.isfinite(v)]
        if not rows:
            return 0
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO bars (key, t, v) VALUES (?, ?, ?)", rows)
            self._db.commit()
        if self._pruned != t[:10]:
            self.prune()
            self._pruned = t[:10]
        return len(rows)

    def days(self) -> List[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT DISTINCT substr(t, 1, 10) FROM bars ORDER BY 1")]

    def prune(self, keep: int = KEEP_DAYS, keep_other: int = LEAD_KEEP_DAYS) -> int:
        """Drop the minutes of all but the last ``keep`` trading days - ``keep_other`` for the keys not above."""
        days = self.days()
        n = 0
        with self._lock:
            if len(days) > keep:
                n += self._db.execute("DELETE FROM bars WHERE t < ?", (days[-keep],)).rowcount
            if len(days) > keep_other:
                n += self._db.execute("DELETE FROM bars WHERE t < ? AND key NOT IN (%s)" % ",".join("?" * len(KEYS)),
                                      (days[-keep_other],) + tuple(KEYS)).rowcount
            self._db.commit()
        return n

    def load(self, keys: Sequence[str], since: str = "") -> Dict[str, List[Tuple[str, float]]]:
        """The keys' minutes since ``since``, each in time order (read by key: the table's own order)."""
        out: Dict[str, List[Tuple[str, float]]] = {k: [] for k in keys}
        if not out:
            return out
        sql = "SELECT key, t, v FROM bars WHERE key IN (%s) AND t >= ? ORDER BY key, t" % ",".join("?" * len(out))
        with self._lock:
            for k, t, v in self._db.execute(sql, tuple(out) + (since,)):
                out[k].append((t, v))
        return out

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            n, last = self._db.execute("SELECT COUNT(*), MAX(t) FROM bars").fetchone()
        return {"rows": n, "last": last, "days": len(self.days())}

    def close(self) -> None:
        with self._lock:
            self._db.close()


def five(points: Sequence[Tuple[str, float]]) -> Dict[str, List[Tuple[int, float]]]:
    """Five-minute closes per day from one-minute ones: ``{day: [(minute of the day of the bar's end, close)]}``."""
    out: Dict[str, Dict[int, float]] = {}
    for t, v in points:
        day, hm = t[:10], t[11:16]
        mins = int(hm[:2]) * 60 + int(hm[3:5])
        if not SESSION[0] <= mins <= SESSION[1]:
            continue
        b = int(math.ceil(mins / float(BAR))) * BAR
        out.setdefault(day, {})[b] = v                       # the last minute of the bar wins: its close
    return {d: sorted(bs.items()) for d, bs in sorted(out.items())}


# ---------------------------------------------------------------------------------------------- the families
def _ma_dev(kind: str, closes: List[float]) -> List[Optional[float]]:
    """Each bar's distance from the mean of the day's last ``MA_BARS`` closes (itself included); none before."""
    out: List[Optional[float]] = []
    for k in range(len(closes)):
        if k < MA_BARS - 1:
            out.append(None)
            continue
        w = closes[k - MA_BARS + 1:k + 1]
        out.append(_diff(kind, sum(w) / len(w), closes[k]))
    return out


def _window_gate(now: _dt.datetime, meeting_day: bool, mr: bool):
    mins = now.hour * 60 + now.minute

    def gate(_s: int) -> Tuple[float, str]:
        if mins >= NO_NEW_AFTER:
            return 0.0, "seans sonuna az kaldı: 17:00'den sonra yeni gün içi işlem yok"
        if mr and meeting_day and PPK_WINDOW[0] <= mins <= PPK_WINDOW[1]:
            return 0.0, "PPK açıklama penceresi (13:45 – 15:30): ortalamaya dönüş beklenmez"
        return 1.0, "seans içinde"
    return gate


def intraday_monitors(ctx: qf.Ctx, bars: Dict[str, Dict[str, List[Tuple[int, float]]]], now: _dt.datetime,
                      meeting_day: bool = False) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """The four families on five-minute bars (``bars``: key -> day -> [(minute, close)], today's included)."""
    today = now.strftime("%Y-%m-%d")
    mins_now = now.hour * 60 + now.minute
    cfg = ctx.cfg
    mons: List[qf.Monitor] = []
    table: Dict[str, Any] = {"z": [], "rv": [], "path": None, "today": today, "meeting_day": meeting_day}
    left = max(1, int((SESSION[1] - mins_now) / BAR))       # bars left in the session

    # ---- z against the 60-minute mean, and the opening range
    for key in ZKEYS:
        days = bars.get(key) or {}
        if today not in days or len(days) < 3:
            continue
        kind = _kind(key)
        hist_d: List[float] = []
        hist_lbl: List[str] = []
        breaks: List[float] = []
        for d, rows in days.items():
            if d >= today:
                continue
            closes = [v for _, v in rows]
            for (m_, _), dv in zip(rows, _ma_dev(kind, closes)):
                if dv is not None:
                    hist_d.append(dv)
                    hist_lbl.append("%s %02d:%02d" % (d, m_ // 60, m_ % 60))
            if len(closes) > OR_BARS + 1:                    # that day's breakout and what followed it to the close
                hi, lo = max(closes[:OR_BARS]), min(closes[:OR_BARS])
                if hi > lo:
                    mid, half = (hi + lo) / 2.0, (hi - lo) / 2.0
                    for c in closes[OR_BARS:]:
                        sc = (c - mid) / half
                        if abs(sc) >= ORB_ENTRY:
                            breaks.append(qf.sign(sc) * _diff(kind, c, closes[-1]))
                            break
        rows_t = days[today]
        closes_t = [v for _, v in rows_t]
        if len(hist_d) < 120 or len(closes_t) < 2:
            continue
        mean, sd = qf.window_stats(hist_d)
        if not sd:
            continue
        ou = qf.ou_of(hist_d[-2000:])
        tail = closes_t[-(MA_BARS - 1):]

        def calc(live, key=key, kind=kind, tail=tail):
            x = live.get(key)
            if x is None:
                x = tail[-1]
            w = tail + [x]
            return _diff(kind, sum(w) / len(w), x)

        dv_today = [x for x in _ma_dev(kind, closes_t) if x is not None]
        name = ctx.label(key)
        unit = "%" if kind == "fx" else "bp"
        fx = key[3:] if key.startswith("FX:") else None

        def quote(live, tail=tail, name=name):
            # a rate as the desk trades it: the tenor's rate now; the distance is from the 60-minute mean with the rate
            # in it, d = (x − (S + x) / n) · 100 for the n − 1 bars before (sum S) - so x = S / (n − 1) + d / 100 · n / (n − 1)
            # exactly, those bars held (an FX line is told in its prices already)
            n = len(tail) + 1
            if n < 2:
                return None
            base = sum(tail) / (n - 1)
            return {"inst": name, "unit": "%", "digits": qf.RATE_DIGITS, "base": base, "scale": 0.01 * n / (n - 1),
                    "gap": {"name": "60 dk farkı", "of": "60 dakikalık ortalamanın", "at": "60 dakikalık ortalamada"},
                    "model": "son %d barın ortalaması (%s)" % (n - 1, qf.rate_text(base)), "note": "hedef / stop son 60 dakikanın barlarıyla",
                    "held": "Hedef ve stop son 60 dakikanın barlarıyla (ortalama %s): yeni bar gelince onlar da değişir." % qf.rate_text(base)}
        mon = qf.Monitor("izscore:" + key, "izscore", "FX" if fx else ("Offshore" if key.startswith("OFF:") else "TRY OIS"),
                         "%s · 60 dk ortalamasına uzaklık" % name, unit, 2, hist_lbl[-400:], hist_d[-400:],
                         [{"key": key, "name": name, "weight": 1.0}], calc, mean=mean, sd=sd, half_life=ou["half_life"] if ou else None,
                         regime=qf.regime_of(hist_d[-1000:], "bp", cfg), pkg="fx" if fx else "rate", intraday=True, horizon_unit="bar",
                         horizon=float(left),
                         dsd=qm.stdev([b - a for a, b in zip(hist_d, hist_d[1:])]), pnl=(unit, 1.0), fx=fx,
                         quote=None if fx else quote, gate=_window_gate(now, meeting_day, True), gate_name="Seans",
                         info={"window": "%d gün, 5 dk bar" % len([d for d in days if d < today]), "bars_left": left},
                         note="Seviyenin günün son 60 dakikasının ortalamasına uzaklığı (%s), son %d günün 5 dakikalık bar dağılımına göre z: + ise "
                              "ortalamanın üstünde (geri dönüş beklenir). Yarı ömür ve tutma bar (5 dk) cinsinden, yarı ömür seansın kalan "
                              "barlarıyla karşılaştırılır; seansın sonunda kapanır." % (
                                  unit, len([d for d in days if d < today])))
        mons.append(mon)
        row = {"key": key, "label": name, "last": closes_t[-1], "dev": dv_today[-1] if dv_today else None, "mean": mean, "sd": sd,
               "z": ((dv_today[-1] - mean) / sd) if dv_today else None, "half_life": ou["half_life"] if ou else None, "unit": unit,
               "sid": mon.sid}
        # the opening range
        if len(closes_t) > OR_BARS and mins_now >= SESSION[0] + OR_BARS * BAR:
            hi, lo = max(closes_t[:OR_BARS]), min(closes_t[:OR_BARS])
            row.update({"or_high": hi, "or_low": lo})
            if hi > lo:
                mid, half = (hi + lo) / 2.0, (hi - lo) / 2.0
                cont = sum(breaks) / len(breaks) if breaks else None
                row.update({"or_score": (closes_t[-1] - mid) / half, "breaks": len(breaks), "cont": cont})

                def ocalc(live, key=key, last=closes_t[-1]):
                    x = live.get(key)
                    return x if x is not None else last

                def ozfn(level, live, mid=mid, half=half):
                    return (level - mid) / half if level is not None else None

                def ofcast(level, z, cont=cont, kind=kind):
                    # the past breakouts' average follow-through to the close, in level units
                    if cont is None or level is None:
                        return None
                    move = qf.sign(z) * cont
                    return move / 100.0 if kind == "rate" else level * move / 100.0

                sample = {"ok": len(breaks) >= MIN_BREAKS, "text": "son %d günde %d kırılım, kapanışa kadar ortalama %s %s" % (
                    len([d for d in days if d < today]), len(breaks), qf._sg(cont, 2), unit)}
                omon = qf.Monitor("iorb:" + key, "iorb", "FX" if fx else ("Offshore" if key.startswith("OFF:") else "TRY OIS"),
                                  "%s · açılış aralığı" % name, "%" if kind == "rate" else "", 4 if kind == "fx" else 3,
                                  [lbl for lbl in hist_lbl[-60:]], [0.0] * len(hist_lbl[-60:]), [{"key": key, "name": name, "weight": 1.0}], ocalc,
                                  zfn=ozfn, entry=ORB_ENTRY, follows=True, mode="drift", reward=hi - lo, risk=max(abs(closes_t[-1] - mid), (hi - lo) * 0.25),
                                  hold=float(left), regime={"tag": None}, pkg="fx" if fx else "rate", intraday=True, horizon_unit="bar",
                                  dsd=qm.stdev([b - a for a, b in zip(closes_t, closes_t[1:])]) or (hi - lo) / 4.0,
                                  pnl=qf.pnl_scale("fx" if kind == "fx" else "rate", closes_t[-1]), fx=fx, fcast=ofcast, sample=sample,
                                  price="level" if fx else None, inst="%s spot" % fx if fx else None,      # (the level is the spot)
                                  gate=_window_gate(now, meeting_day, False), gate_name="Seans", score_name="aralık",
                                  info={"or_high": hi, "or_low": lo, "breaks": len(breaks), "cont": cont},
                                  note="Açılış aralığı (ilk 30 dk) %s – %s; skor = (seviye − orta) ÷ yarı genişlik: ±1,5'in ötesi kırılım, yönünde "
                                       "girilir. Hedef: aralığın genişliği kadar öte; stop: aralığın ortası. Beklenen: son günlerin kırılımlarının "
                                       "kapanışa kadar ortalama devamı." % (qf._g(lo, 4), qf._g(hi, 4)))
                omon.zvalues = [None] * len(omon.values)
                mons.append(omon)
                row["orb_sid"] = omon.sid
        table["z"].append(row)

    # ---- the spreads on bars
    for a, b, name in SPREADS:
        da, db = bars.get(a) or {}, bars.get(b) or {}
        if today not in da or today not in db:
            continue
        hist: List[float] = []
        lbls: List[str] = []
        for d in sorted(set(da) & set(db)):
            ma, mb = dict(da[d]), dict(db[d])
            for m_ in sorted(set(ma) & set(mb)):
                if d < today:
                    hist.append((ma[m_] - mb[m_]) * 100.0)
                    lbls.append("%s %02d:%02d" % (d, m_ // 60, m_ % 60))
        if len(hist) < 120:
            continue
        mean, sd = qf.window_stats(hist)
        if not sd:
            continue
        ou = qf.ou_of(hist[-2000:])
        la, lb = dict(da[today]), dict(db[today])
        common = sorted(set(la) & set(lb))
        last = (la[common[-1]] - lb[common[-1]]) * 100.0 if common else None

        def scalc(live, a=a, b=b, last=last, la=la, lb=lb, common=common):
            x, y = live.get(a), live.get(b)
            if x is None or y is None:
                return last
            return (x - y) * 100.0

        mon = qf.Monitor("irv:%s|%s" % (a, b), "irv", "Offshore" if a.startswith("OFF:") else "TRY OIS", name + " (gün içi)", "bp", 1,
                         lbls[-400:], hist[-400:], [{"key": a, "name": ctx.label(a), "weight": 1.0}, {"key": b, "name": ctx.label(b), "weight": -1.0}],
                         scalc, mean=mean, sd=sd, half_life=ou["half_life"] if ou else None, regime=qf.regime_of(hist[-1000:], "bp", cfg),
                         pkg="rate", intraday=True, horizon_unit="bar", horizon=float(left), dsd=qm.stdev([y - x for x, y in zip(hist, hist[1:])]), pnl=("bp", 1.0),
                         gate=_window_gate(now, meeting_day, True), gate_name="Seans",
                         note="%s (bp) 5 dakikalık barlarda, son 20 günün dağılımına göre z: + ise spread geniş (ilk bacak receive / ikinci pay ile "
                              "daralma), − dar." % name)
        mons.append(mon)
        table["rv"].append({"name": name, "a": a, "b": b, "now": last, "mean": mean, "sd": sd, "z": (last - mean) / sd if last is not None else None,
                            "half_life": ou["half_life"] if ou else None, "sid": mon.sid})

    # ---- USDTRY against the path its carry implies from the open
    days = bars.get("FX:USDTRY") or {}
    carry = ctx.fx_carry("USDTRY")
    if today in days and carry is not None and len(days) >= 3:
        rate = -carry / 100.0 / 365.0 / 1440.0               # the forward's depreciation, a minute
        rets = []
        zs_hist: List[float] = []
        for d, rows in days.items():
            if d >= today:
                continue
            rets.extend(math.log(b_ / a_) * 100.0 for (_, a_), (_, b_) in zip(rows, rows[1:]) if a_ > 0 and b_ > 0)
        sig = qm.stdev(rets) if len(rets) > 50 else None
        rows_t = days[today]
        if sig and rows_t:
            m0, open_ = rows_t[0]
            gx: List[float] = []                             # the past days' gap at a bar, and a bar later
            gy: List[float] = []
            for d, rows in days.items():                     # the past days' z by the same rule (the distribution shown)
                if d >= today or not rows:
                    continue
                mo, o = rows[0]
                gap = [0.0]                                  # (at its open a day is on its path)
                for k, (m_, v) in enumerate(rows[1:], 1):
                    dev = math.log(v / (o * math.exp(rate * (m_ - mo)))) * 100.0
                    zs_hist.append(dev / (sig * math.sqrt(k)))
                    gap.append(dev)
                gx.extend(gap[:-1])
                gy.extend(gap[1:])
            # the gap's half-life in bars, an Ornstein-Uhlenbeck fit on the bars as the other families have theirs - on
            # the steps inside each day: every day's gap starts again at 0 at its open, and a step across two days would
            # read that restart as a return to the path.  Measured as not returning: None (the half-life gate keeps the
            # signal out); not measurable: the family's own hour
            ou = qm.ou_fit(gx[-2000:], gy[-2000:])
            hl = ou["half_life"] if ou else float(PATH_BARS)

            def dev_now(live, m0=m0, open_=open_):
                x = live.get("FX:USDTRY")
                if x is None:
                    x = rows_t[-1][1]
                k_ = max(1.0, (mins_now - m0) / float(BAR))
                return math.log(x / (open_ * math.exp(rate * (mins_now - m0)))) * 100.0, k_

            def pcalc(live):
                return dev_now(live)[0]

            def pzfn(level, live):
                d_, k_ = dev_now(live)
                return d_ / (sig * math.sqrt(k_))

            k_now = max(1.0, (mins_now - m0) / float(BAR))
            hold = float(min(left, PATH_BARS))               # (the half-life is held to it: half the gap within the hour)
            mon = qf.Monitor("ipath:USDTRY", "ipath", "FX", "USDTRY · carry patikasına göre", "%", 3, [], [], [{"key": "FX:USDTRY", "name": "USDTRY", "weight": 1.0}],
                             pcalc, zfn=pzfn, mean=0.0, sd=sig * math.sqrt(k_now), half_life=hl, regime={"tag": None}, pkg="fx", intraday=True,
                             horizon_unit="bar", horizon=hold, hold=hold, dsd=sig, pnl=("%", 1.0), fx="USDTRY",
                             fcast=lambda level, z: -level * 0.5 if level is not None else None,
                             gate=_window_gate(now, meeting_day, True), gate_name="Seans",
                             info={"open": open_, "carry": carry, "sigma_bar": sig},
                             note="Günün açılışından carry'nin ima ettiği patika (forward primi dakika dakika: yıllık %s) ile spot arasındaki fark "
                                  "(%%, log), bar gürültüsü × √bar ile z: + ise USDTRY patikanın önünde (sat, patikaya dönüş beklenir), − ise "
                                  "gerisinde (al). Beklenen: farkın yarısı bir saatte. Yarı ömür bar (5 dk) cinsinden: geçmiş günlerin barlarında "
                                  "farkın gün içi adımlarından (OU; ölçülemezse bir saat, %d bar), bir saatlik tutmayla karşılaştırılır." % (
                                      qf._g(-carry, 1), PATH_BARS))
            mon.zvalues = None
            mons.append(mon)
            d_now, _ = dev_now(ctx.live)
            table["path"] = {"open": open_, "spot": rows_t[-1][1], "path": open_ * math.exp(rate * (mins_now - m0)), "dev": d_now,
                             "z": d_now / (sig * math.sqrt(k_now)), "carry": carry, "sigma_bar": sig, "sid": mon.sid,
                             "z_hist_sd": qm.stdev(zs_hist) if len(zs_hist) > 20 else None}
    return mons, table


# ---------------------------------------------------------------------------------------------- the service part
class Intraday(object):
    """What the quant worker keeps of the day: the bars (live only) and the intraday monitors built from them."""

    def __init__(self, quant: Any):
        self.quant = quant
        self.svc = quant.svc
        self._bars: Optional[Bars] = None
        self._last = ""
        self._feed: Dict[str, str] = {}

    def want(self, feed: Dict[str, str]) -> None:
        """The keys the lead-lag analysis reads intraday beyond the ones above, ``{bar key: live key}`` (a bond's
        yield is kept under its own key, from the sheet's simple or compound one): written down with them from the
        next minute on, kept ``LEAD_KEEP_DAYS`` days."""
        self._feed = {bar: live for bar, live in feed.items() if bar not in KEYS}

    def bars(self) -> Optional[Bars]:
        if self._bars is None:
            folder = getattr(getattr(self.svc, "settings", None), "data_dir", None)
            if not folder:
                return None
            self._bars = Bars(os.path.join(folder, "quant_bars.sqlite3"))
        return self._bars

    def live(self) -> bool:
        return self.svc.mode == "live" and bool(self.quant.use_live)

    def series(self, key: str, minutes: int = 1) -> Optional[Tuple[List[str], List[float]]]:
        """One key's bars for the lead-lag analysis (``quantlead``): its 1- or 5-minute closes over the days kept, as
        ``(times, values)`` (``"YYYY-MM-DD HH:MM"``, the bar's end); ``None`` when there are none (replay, a key the
        bars do not keep)."""
        if (key not in KEYS and key not in self._feed) or minutes not in (1, BAR) or not self.live():
            return None
        b = self.bars()
        if b is None:
            return None
        since = (_dt.date.today() - _dt.timedelta(days=KEEP_DAYS + 10)).strftime("%Y-%m-%d")
        pts = b.load([key], since).get(key) or []
        if not pts:
            return None
        if minutes == 1:
            return [t for t, _ in pts], [v for _, v in pts]
        times: List[str] = []
        values: List[float] = []
        for day, bars in five(pts).items():
            for m, v in bars:
                times.append("%s %02d:%02d" % (day, m // 60, m % 60))
                values.append(v)
        return times, values

    def sample(self, raw_live: Dict[str, float], now: _dt.datetime) -> int:
        """The minute's values as closes (live, a week day, in the session; once a minute)."""
        if not self.live() or now.weekday() >= 5:
            return 0
        mins = now.hour * 60 + now.minute
        stamp = now.strftime("%Y-%m-%d %H:%M")
        if not SESSION[0] <= mins <= SESSION[1] or stamp == self._last:
            return 0
        b = self.bars()
        if b is None:
            return 0
        self._last = stamp
        values = {k: raw_live[k] for k in KEYS if k in raw_live}
        feed = self._feed
        for bar, live in feed.items():
            if raw_live.get(live) is not None:
                values[bar] = raw_live[live]
        return b.record(now, values, also=feed)

    def monitors(self, ctx: qf.Ctx, now: _dt.datetime) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
        if not self.live():
            return [], {"ok": False, "why": "Kayıtlı veri modunda gün içi bar yok: bu sayfa canlı modda, piyasa açıkken dolar.", "z": [], "rv": []}
        b = self.bars()
        if b is None:
            return [], {"ok": False, "why": "bar dosyası yok", "z": [], "rv": []}
        since = (now - _dt.timedelta(days=45)).strftime("%Y-%m-%d")
        raw = b.load(KEYS, since)
        bars = {k: five(v) for k, v in raw.items()}
        meeting = any(d == now.date() for d, _ in ((ctx.path or {}).get("steps") or []))
        mons, table = intraday_monitors(ctx, bars, now, meeting)
        table.update({"ok": True, "stats": b.stats()})
        if not table["z"] and not table["rv"]:
            table["why"] = "gün içi bar az: en az 3 gün ve bugünün barları gerekli (kayıt: %d gün)" % table["stats"]["days"]
        return mons, table
