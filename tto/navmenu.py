"""The menu: its groups, their entries and each entry's tabs - one table for the whole menu (the desk, 28.11.2026:
"Bir de genel sayfalari da daha duzenli yapabiliriz ... Digerlerini de onayliyorum" - the reorganization R of
``oneriler-28-11.md``; docs/desk-decisions.md, *Menü ve kabuk*).

Forty-odd pages are some twenty entries: several pages of one subject are one entry, its pages the tabs of a strip over
the page (the nav's ``menu`` / ``menu_title`` / ``tab``, as quant's entries and DİBS RV were before - ``menu.js``
``pageTabs``).  **A page keeps its own id and address** (``#/blotter``, ``#/mpc`` …): favourites, launchpads, the side
drawer, alarms, Ctrl+K, links and bookmarks find it as before; ``#/mpc`` opens OIS · PPK on its "PPK geçmişi" tab.

Every entry has a one-line hint (the menu's tooltip; a tab's own in the strip).  The groups come in the table's order,
Araçlar last; :func:`arrange` puts the nav's pages in that order and names their entry.  A page the table does not name
(one added later) stays at the end of its group - a group the table does not know, before Araçlar.  The quant entries
are ``quant.MENU``'s (their tabs and order); DİBS RV's is ``dibsgenel``'s (``MENU_ID``, ``MENU_TITLE``, ``TABS``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import dibsgenel as dg

#: an entry: (id, title, hint, ((page id, tab title, tab hint), ...)) - one page: the entry is the page itself (its own
#: title in the menu); two or more: one entry, the pages its tabs
Entry = Tuple[str, str, str, Tuple[Tuple[str, str, str], ...]]

QUANT = "Quant"
#: the group a page of an old group name belongs to now (a page added by another version keeps its place)
OLD_GROUPS = {"Risk": "TRY Faiz", "USD Faiz": "FX · USD", "FX": "FX · USD"}
LAST = "Araçlar"


def _one(pid: str, hint: str) -> Entry:
    return (pid, "", hint, ((pid, "", ""),))


_DIBS_RV_HINTS = {"dibs-genel": "Genel — kâğıtlar yan yana: OIS ASW, FX swap ASW, sıfır kupon eğrisi ve grafikler",
                  "dibs": "RV hesap tablosu — DİBS RV sayfası (Excel'in hesabı)",
                  "asw": "ASW hesap tablosu — DİBS ASW sayfası (Excel'in hesabı)"}

#: the menu, group by group (the desk's reorganization of 28.11.2026)
MENU: Tuple[Tuple[str, Any], ...] = (
    ("Masa", (
        _one("bugun", "Bugün — sabah ekranı: RET, girilmemiş işlemler, Ajanda, Trades, Quant ve DİBS'te bakılacaklar tek sayfada"),
        _one("masa", "Masa — masanın genel bakışı: kontrol, oranlar, forward fiyatlama, tarih arası, faiz · PPK, VİOP, sinyaller"),
        ("masa.islemler", "İşlemler", "İşlemler — Günlük İşlemler (masanın blotter'ı), Trades (izlenen işlemler, pozisyona girmez), "
                                      "Broker Chat", (
            ("blotter", "Günlük İşlemler", "Günlük İşlemler — masanın blotter'ı: günün işlemleri, DV01'i, gün sonu arşivi"),
            ("trades", "Trades", "Trades — izlenen işlemler (masanın ve sizin), MTM ve K/Z: pozisyona girmez"),
            ("broker", "Broker Chat", "Broker Chat — broker kotaları ve chat'teki işlemler, en iyi bid / ask tahtası"))),
        ("masa.piyasa", "Piyasa hareketi", "Piyasa hareketi — eğrinin gün içi hareketi, gün sonu matrisi, izleme listesi ve "
                                           "alarmlar", (
            ("heat", "Eğri Hareketi (gün içi)", "Eğri Hareketi — referansa göre gün içi hareket: OIS, offshore, DİBS"),
            ("eod", "Gün Sonu Matrisi", "Gün Sonu Matrisi — kapanışlar ve günlük / haftalık / aylık değişim"),
            ("watch", "İzleme · Alarmlar", "İzleme · Alarmlar — izlediğiniz hücreler, alarmlar, bugün çalanlar"))),
        ("masa.iletisim", "Masa iletişim", "Masa iletişim — masanın kendi sohbeti (Sosyal) ve ajandası", (
            ("social", "Sosyal", "Sosyal — masanın kendi sohbeti"),
            ("agenda", "Ajanda", "Ajanda — masanın yapılacakları, hatırlatmaları ve gecikenleri"))),
    )),
    ("TRY Faiz", (
        ("faiz.ois", "OIS · PPK", "OIS · PPK — TRY OIS kotaları, PPK ima patikası, MPC işlemleri, en iyi işlemler; PPK "
                                  "fiyatlamasının geçmişi", (
            ("ois", "OIS · PPK", "OIS · PPK — kotalar, MPC ima, MPC işlem, en iyi işlemler, tüm listeler"),
            ("mpc", "PPK geçmişi", "PPK geçmişi — PPK fiyatlamasının gün gün geçmişi"))),
        ("faiz.fiyatlama", "Fiyatlama", "Fiyatlama — bir enstrüman her başlangıç ve vadede; swaption; OIS'in nakit akışı", (
            ("fiyatlama", "Fiyatlama", "Fiyatlama — OIS, FRA, XCCY, forward: her başlangıç ve vadede, iki yönlü"),
            ("swaption", "Swaption", "Swaption — TRY OIS swaption, Fiyatlama'nın forward başlangıçlı OIS'i üzerine"),
            ("tmois", "Nakit akışı", "Nakit akışı — OIS'in dönem dönem nakit akışı ve piyasa bacağı"))),
        _one("forward", "Forward — USDTRY / EURTRY forward fiyatları, kotasyon, RET, toplu fiyatlama, eğriler, offshore"),
        _one("viop", "VİOP — kontratlar, altın, takvim spread matrisleri, baz geçmişi, eğriler"),
        _one("borsa", "Borsa Swap — BIST swap kotaları ve OIS'e, offshore'a farkları"),
        ("faiz.carry", "Carry & Roll", "Carry & Roll — carry ve roll-down; gerçekleşen vol ve carry; spread geçmişi", (
            ("carry", "Carry & Roll", "Carry & Roll — outright, spread · fly, kapanış simülatörü"),
            ("vol", "Realized vol", "Realized vol — gerçekleşen vol ve carry / vol"),
            ("spreads", "Spread geçmişi", "Spread geçmişi — offshore, OIS ve VİOP spread'lerinin geçmişi"))),
        _one("dv01", "DV01 Risk — pozisyon, risk · senaryo, VaR, hedge, günlük P&L"),
    )),
    ("Tahvil", (
        ("tahvil.piyasa", "DİBS Piyasa", "DİBS Piyasa — trading listesinin canlı tahtası, bütün kâğıtlar (evren), Eurobond "
                                         "kotaları", (
            ("dibslive", "Trading", "Trading — ★ listenin canlı tahtası: T0 / T1 / T2, broker, bugünkü işlemler"),
            ("kagitlar", "Evren", "Evren — bütün kâğıtlar: ★ yönetimi, + ISIN"),
            ("bulk", "Eurobond", "Eurobond — Eurobond kotaları: dealer bid / ask"))),
        ("tahvil.fiyatlama", "DİBS Fiyatlama", "DİBS Fiyatlama — adil fiyat ve AL / SAT, tek kâğıt, sabah fiyat dosyası, "
                                               "ihale", (
            ("kagit-fiyat", "Adil fiyat · AL/SAT", "Adil fiyat · AL/SAT — her kâğıda adil fiyat, kotasyon ve iyi seviyeler"),
            ("manuel", "Tek kâğıt", "Tek kâğıt — ISIN'den koşullar, fiyat ↔ getiri, DV01"),
            ("fiyat-yukleme", "Sabah fiyat dosyası", "Sabah fiyat dosyası — kâğıt fiyat yükleme: ihale ya da Bloomberg"),
            ("ihale", "İhale", "İhale — Hazine ihalesinin teklif fiyatlaması"))),
        (dg.MENU_ID, dg.MENU_TITLE, "DİBS RV — trading listesinin ASW / pahalı-ucuz özeti; RV ve ASW hesap tabloları",
         tuple((pid, tab, _DIBS_RV_HINTS.get(pid, "")) for pid, tab in dg.TABS)),
    )),
    ("FX · USD", (
        ("fx.spot", "Spot / FX", "Spot / FX — bir paritenin spotu ve vol yüzeyi; bütün paritelerin vol izlemesi", (
            ("fx", "Spot / FX", "Spot / FX — bir paritenin spotu, vol yüzeyi, vade geçmişi"),
            ("fxvol", "FX Vol", "FX Vol — bütün paritelerin vol'ü bir bakışta"))),
        _one("usd", "USD · FOMC — SOFR OIS, FOMC ima patikası, eğri, işlemler"),
    )),
    (QUANT, QUANT),
    (LAST, (
        _one("calc", "Hesaplayıcılar — faiz, FX · vol ve tahvil hesaplayıcıları"),
        _one("motor", "Motor — çalışma kitabının motoru (yöneticiler)"),
        _one("settings", "Ayarlar — toplantı takvimi, eğri noktaları, interpolasyon, tatiller, tarihçe"),
    )),
)

#: a page's title where two pages had one (the top bar and Ctrl+K say it; its tab keeps the short name): quant's VİOP
#: page beside the VİOP sheet's
TITLES = {"quant-viop": "Quant · VİOP"}

#: the quant entries' hints (their tabs and order: quant.MENU)
QUANT_HINTS = {
    "quant.sinyal": "Sinyaller — bütün quant AL / SAT satırları; gün içi, model, trend, carry + momentum, makine öğrenmesi, VİOP",
    "quant.faiz": "Faiz analizleri — PCA / RV, çiftler, korelasyon, rejim, eğri adil değeri, DİBS switch, ima patikası, WIRP, "
                  "öncü-takipçi",
    "quant.fx": "FX analizleri — FX vol primi ve carry, makro beta, opsiyon, opsiyon → spot",
}

_KEYS = ("menu", "menu_title", "tab", "menu_hint", "hint")


def group_of(page: Dict[str, Any]) -> str:
    """The group a page belongs to now (an old group's name: its group of today)."""
    g = page.get("group") or "Diğer"
    return OLD_GROUPS.get(g, g)


def entries_of(group: str) -> Sequence[Entry]:
    for name, entries in MENU:
        if name == group:
            return entries if entries is not QUANT else ()
    return ()


def _place(page: Dict[str, Any], group: str, entry: Entry, tab: Tuple[str, str, str], several: bool) -> Dict[str, Any]:
    eid, title, hint, _ = entry
    out = {k: v for k, v in page.items() if k not in _KEYS}
    out["group"] = group
    if several:
        out.update(menu=eid, menu_title=title, tab=tab[1], menu_hint=hint, hint=tab[2] or hint)
    else:
        out["hint"] = hint if len(entry[3]) == 1 else (tab[2] or hint)
    return out


def arrange(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The nav's pages in the menu's order, each naming its group and - in an entry of several pages - its entry
    (``menu``, ``menu_title``, ``menu_hint``) and its tab (``tab``); every page its one-line ``hint``.  Only the pages
    given (an administrators' page is not there for anybody else; a dashboard without the TRY workbook has few): an entry
    left with one of its pages is that page alone."""
    by_id = {p["id"]: p for p in pages}
    used = set()
    out: List[Dict[str, Any]] = []
    known = {name for name, _ in MENU}

    def rest(group: str) -> None:
        # the pages of the group the menu does not name (added later): at the group's end, in their order
        for p in pages:
            if p["id"] not in used and group_of(p) == group:
                out.append(dict(p, group=group))
                used.add(p["id"])

    def unknown_groups() -> None:
        for p in pages:
            if p["id"] not in used and group_of(p) not in known:
                g = group_of(p)
                for q in pages:
                    if q["id"] not in used and group_of(q) == g:
                        out.append(dict(q, group=g))
                        used.add(q["id"])

    for group, entries in MENU:
        if group == LAST:
            unknown_groups()                   # (Araçlar stays last)
        if entries is QUANT:
            # quant.MENU's entries and tabs as quant.pages() names them; the entries' hints here
            for p in pages:
                if p["id"] in used or group_of(p) != QUANT:
                    continue
                q = dict(p, group=QUANT)
                if q.get("menu"):
                    q["menu_hint"] = QUANT_HINTS.get(q["menu"], q.get("menu_title") or "")
                    q["hint"] = q["menu_hint"]
                out.append(q)
                used.add(p["id"])
            continue
        for entry in entries:
            present = [t for t in entry[3] if t[0] in by_id and t[0] not in used]
            for tab in present:
                out.append(_place(by_id[tab[0]], group, entry, tab, len(present) > 1))
                used.add(tab[0])
        rest(group)
    unknown_groups()
    for p in out:
        if p["id"] in TITLES:
            p["title"] = TITLES[p["id"]]
    return out


def entry_ids() -> List[str]:
    """Every entry's id, the menu's order (quant's left out: ``quant.MENU``)."""
    return [e[0] for _, entries in MENU if entries is not QUANT for e in entries]


def page_entry(page_id: str) -> Optional[str]:
    """The id of the entry a page is a tab of (``None``: an entry of its own, or no page of the menu)."""
    for _, entries in MENU:
        if entries is QUANT:
            continue
        for eid, _, _, tabs in entries:
            if len(tabs) > 1 and any(t[0] == page_id for t in tabs):
                return eid
    return None
