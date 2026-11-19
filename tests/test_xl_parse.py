"""A formula template is parsed once per process (``tto/xl/parser.py``: ``parse_template`` keeps its AST): the same AST
for the same template, an error raised as before, a bounded number kept, the same values computed, and no caller
changing an AST it was given (one AST serves every cell of its template, in every book and thread)."""
import os
import threading

import pytest

from tto.xl import parser
from tto.xl.engine import Clock, Engine, cached_pins, run_with_big_stack
from tto.xl.model import COLS, Model
from tto.xl.parser import parse_template
from tto.xl.tokenizer import FormulaSyntaxError, to_template

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_a_template_is_parsed_once_and_its_ast_shared():
    tpl = to_template('IF(A1>0,SUM(B1:B9)*2,"yok")', 5, 3)
    kept = parse_template(tpl)
    assert kept == ("func", "IF", [("bin", ">", ("cell", None, False, -4, False, -2), ("num", 0.0)),
                                   ("bin", "*", ("func", "SUM", [("range", None, False, -4, False, -1, False, 4, False, -1)],
                                                 False), ("num", 2.0)),
                                   ("str", "yok")], False)
    assert kept == parse_template.__wrapped__(tpl)             # what a parse afresh gives
    assert parse_template(tpl[:3] + tpl[3:]) is kept           # the same text, another string: the same AST
    # leaves are one tuple across templates: A1 seen from C5 in another formula
    other = parse_template(to_template("A1*3", 5, 3))
    assert other == ("bin", "*", ("cell", None, False, -4, False, -2), ("num", 3.0))
    assert other[2] is kept[2][0][2]


@pytest.mark.parametrize("bad", ["1+", "SUM(1,", "`R1C1", "{1,A}", ")", "IF(1,2"])
def test_a_template_that_does_not_parse_raises_each_time(bad):
    with pytest.raises(FormulaSyntaxError) as first:
        parse_template(bad)
    with pytest.raises(FormulaSyntaxError) as again:           # (an error is not kept as if it were an AST)
        parse_template(bad)
    assert str(again.value) == str(first.value)


def test_the_kept_asts_are_bounded(monkeypatch):
    """At most PARSED_KEPT ASTs - every workbook template (~21 000) with room for users' formulas -, the least recently
    used one going first; the shared leaves are bounded too."""
    assert parse_template.cache_info().maxsize == parser.PARSED_KEPT >= 25000
    oldest = parse_template("0+0.125")
    try:
        for i in range(1, parser.PARSED_KEPT + 1):
            parse_template("%d+0.125" % i)
        assert parse_template.cache_info().currsize <= parser.PARSED_KEPT
        newest = "%d+0.125" % parser.PARSED_KEPT
        assert parse_template(newest) is parse_template(newest)
        again = parse_template("0+0.125")                      # pushed out by the others: parsed afresh
        assert again is not oldest and again == oldest
        monkeypatch.setattr(parser, "LEAVES_KEPT", 16)
        trees = [parse_template("SUM(%d,`R[%d]C1`)" % (i, -i)) for i in range(40)]
        assert len(parser._LEAVES) <= 16
        assert trees[39] == ("func", "SUM", [("num", 39.0), ("cell", None, False, -39, True, 1)], False)
    finally:
        parse_template.cache_clear()                           # (none of these is a formula of anybody's)
        parser._LEAVES.clear()


def test_threads_parsing_at_once_get_whole_asts():
    """The engine thread, the reference index's and request threads parse at once: each gets a whole AST - the kept one
    or an equal one parsed beside it -, never part of one."""
    tpls = ["IF(`R[%d]C1`>%d,SUM(`R1C1:R%dC2`),{1,2;3,%d})" % (-i, i, i + 1, i) for i in range(1, 1500)]
    got = [[] for _ in range(4)]
    errors = []

    def run(k):
        try:
            for t in (tpls if k % 2 else tpls[::-1]):
                got[k].append((t, parse_template(t)))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(len(g) == len(tpls) for g in got)
    assert [t for g in got for t, ast in g if ast != parse_template.__wrapped__(t)] == []


def _values(name: str):
    """Every formula cell of a workbook computed, on a model loaded afresh (the clock of the file's day, the add-in
    cells at their saved values)."""
    def run():
        model = Model.load(os.path.join(ROOT, "models", name))
        eng = Engine(model, clock=Clock(46329.0))
        eng.set_pins(cached_pins(model))
        calc = eng.shared
        return {(s.name, rc): calc.get(s.index, *divmod(rc, COLS)) for s in model.sheets for rc in sorted(s.fml)}
    return run_with_big_stack(run)


def _same(a, b) -> bool:
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return a == b or (a != a and b != b)
    return a is b or repr(a) == repr(b)


def test_a_workbook_computed_twice_gives_the_same_values():
    """First from ASTs parsed afresh, then from the ASTs the first calculation kept (its compiler and the add-in scan
    read them): the same values - nothing of the first changed an AST the second compiles."""
    parse_template.cache_clear()
    first = _values("sofr.json.gz")
    second = _values("sofr.json.gz")
    assert len(first) > 4000 and first.keys() == second.keys()
    assert [k for k in first if not _same(first[k], second[k])] == []
    model = Model.load(os.path.join(ROOT, "models", "sofr.json.gz"))
    assert [t for t in set(model.templates) if parse_template(t) != parse_template.__wrapped__(t)] == []


def test_no_caller_changes_a_kept_ast(module_service):
    """Everything that reads templates has run on the kept ASTs - a service built (the books, the dashboard's own sheets,
    date cells, replay's snapshot), pages computed, a formula typed into an input, the reverse reference indexes -:
    every template's kept AST is still what a parse afresh gives."""
    svc = module_service
    user = svc.login("Ayrıştırma Kontrolü")["user"]
    try:
        for vid in ("masa", "ois", "forward", "viop", "borsa", "asw", "usd"):
            svc.view(None, vid)
        res = svc.set_inputs(user, "tto", [{"ref": "MASA!C171", "value": "=C60+7"}])
        assert res["errors"] == []
        svc.view(user, "masa")
        for book in svc.books.values():
            book.engine.ref_index()
        changed = []
        for bid, book in svc.books.items():
            for t in set(book.model.templates) | set(book.model.names.values()):
                try:
                    kept = parse_template(t)
                except FormulaSyntaxError:
                    continue
                if kept != parse_template.__wrapped__(t):
                    changed.append((bid, t))
        assert changed == []
    finally:
        svc.reset_inputs(user, "tto")
