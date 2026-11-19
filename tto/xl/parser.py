"""Recursive-descent parser: formula template -> AST.

AST nodes are plain tuples (first item = node kind):

* ``("num", float)``  ``("str", text)``  ``("bool", b)``  ``("err", code)``  ``("missing",)``
* ``("cell", sheet, row_abs, row, col_abs, col)``
* ``("range", sheet, ra1, r1, ca1, c1, ra2, r2, ca2, c2)``
* ``("cols", sheet, ca1, c1, ca2, c2)``  ``("rows", sheet, ra1, r1, ra2, r2)``
* ``("name", NAME, sheet_or_None)``
* ``("func", NAME, [args], addin)``
* ``("bin", op, lhs, rhs)``  with op in ``+ - * / ^ & = <> < > <= >= :``
* ``("neg", x)``  ``("pos", x)``  ``("pct", x)``  ``("single", x)``
* ``("array", [[node, ...], ...])``

Operator precedence follows Excel: reference ``:`` > unary minus > ``%`` > ``^`` (left assoc.) >
``* /`` > ``+ -`` > ``&`` > comparisons.

A template is parsed once per process (:func:`parse_template` keeps its AST) and that one AST goes to every caller,
so an AST is read only: build a new tree rather than change one (``tto.calc._clip`` does).
"""
from __future__ import annotations

import functools
from typing import Any, Dict, List, Tuple

from .tokenizer import FormulaSyntaxError, Token, parse_ref_token, tokenize_template

_CMP = ("=", "<>", "<", ">", "<=", ">=")
_PREFIXES = ("_XLFN.", "_XLWS.", "_XLL.", "_XLUDF.")
#: ASTs kept, the most recently used: the four workbooks with the dashboard's own sheets have ~21 000 templates (all
#: of them kept: ~36 MB), the rest is room for the formulas users type
PARSED_KEPT = 32768
#: leaves kept to be shared (the workbooks have ~8 000 different ones); started again when full
LEAVES_KEPT = 65536
_LEAVES: Dict[tuple, tuple] = {}


def _leaf(node: tuple) -> tuple:
    """The tuple already made for an equal leaf - a reference, a number, a text, a name: most nodes of an AST are
    leaves, and the kept ASTs share them (``R[0]C[-1]``, the cell to the left, is one tuple in all of them).  A leaf
    holds no list, so sharing it changes nothing (equal leaves hold the same values: a number token has no sign, so no
    -0.0 meets a 0.0); two threads making the same leaf at once may each keep their own."""
    got = _LEAVES.get(node)
    if got is None:
        if len(_LEAVES) >= LEAVES_KEPT:
            _LEAVES.clear()
        _LEAVES[node] = got = node
    return got


def normalise_function_name(raw: str) -> Tuple[str, bool]:
    """``_xlfn._xlws.FILTER`` -> ("FILTER", False) ; ``_xll.BDP`` -> ("BDP", True)."""
    name = raw.upper()
    addin = False
    changed = True
    while changed:
        changed = False
        for p in _PREFIXES:
            if name.startswith(p):
                if p == "_XLL.":
                    addin = True
                name = name[len(p):]
                changed = True
    return name, addin


def normalise_name(raw: str) -> str:
    name = raw.upper()
    if name.startswith("_XLPM."):
        name = name[6:]
    return name


class _Parser(object):
    def __init__(self, tokens: List[Token], source: str):
        self.toks = tokens
        self.pos = 0
        self.n = len(tokens)
        self.source = source

    def peek(self):
        if self.pos < self.n:
            return self.toks[self.pos]
        return ("eof", "")

    def take(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def expect(self, text: str):
        tok = self.take()
        if tok[1] != text:
            raise FormulaSyntaxError("expected %r but found %r in %r" % (text, tok[1], self.source))

    def is_op(self, text: str) -> bool:
        tok = self.peek()
        return tok[0] == "op" and tok[1] == text

    # ---- grammar
    def parse(self):
        node = self.expr()
        if self.pos != self.n:
            raise FormulaSyntaxError("unexpected %r in %r" % (self.peek()[1], self.source))
        return node

    def expr(self):
        left = self.concat()
        while True:
            tok = self.peek()
            if tok[0] == "op" and tok[1] in _CMP:
                self.pos += 1
                left = ("bin", tok[1], left, self.concat())
            else:
                return left

    def concat(self):
        left = self.additive()
        while self.is_op("&"):
            self.pos += 1
            left = ("bin", "&", left, self.additive())
        return left

    def additive(self):
        left = self.term()
        while True:
            tok = self.peek()
            if tok[0] == "op" and tok[1] in ("+", "-"):
                self.pos += 1
                left = ("bin", tok[1], left, self.term())
            else:
                return left

    def term(self):
        left = self.power()
        while True:
            tok = self.peek()
            if tok[0] == "op" and tok[1] in ("*", "/"):
                self.pos += 1
                left = ("bin", tok[1], left, self.power())
            else:
                return left

    def power(self):
        left = self.unary()
        while self.is_op("^"):
            self.pos += 1
            left = ("bin", "^", left, self.unary())
        return left

    def unary(self):
        tok = self.peek()
        if tok[0] == "op":
            if tok[1] == "-":
                self.pos += 1
                return ("neg", self.unary())
            if tok[1] == "+":
                self.pos += 1
                return ("pos", self.unary())
            if tok[1] == "@":
                self.pos += 1
                return ("single", self.unary())
        return self.postfix()

    def postfix(self):
        node = self.reference()
        while self.is_op("%"):
            self.pos += 1
            node = ("pct", node)
        return node

    def reference(self):
        node = self.primary()
        while self.is_op(":"):
            self.pos += 1
            node = ("bin", ":", node, self.primary())
        return node

    def primary(self):
        kind, text = self.take()
        if kind == "num":
            return _leaf(("num", float(text)))
        if kind == "str":
            return _leaf(("str", text[1:-1].replace('""', '"')))
        if kind == "err":
            return _leaf(("err", text))
        if kind == "ref":
            sheet, rk, payload = parse_ref_token(text)
            if rk == "cell":
                return _leaf(("cell", sheet) + tuple(payload))
            if rk == "range":
                return _leaf(("range", sheet) + tuple(payload))
            if rk == "cols":
                return _leaf(("cols", sheet) + tuple(payload))
            if rk == "rows":
                return _leaf(("rows", sheet) + tuple(payload))
            return _leaf(("name", normalise_name(payload), sheet))
        if kind == "func":
            name, addin = normalise_function_name(text[:-1])
            args: List[Any] = []
            if self.is_op(")"):
                self.pos += 1
                return ("func", name, args, addin)
            while True:
                tok = self.peek()
                if tok[0] == "op" and tok[1] in (",", ")"):
                    args.append(("missing",))
                else:
                    args.append(self.expr())
                tok = self.take()
                if tok[0] == "op" and tok[1] == ",":
                    if self.is_op(")"):
                        args.append(("missing",))
                        self.pos += 1
                        break
                    continue
                if tok[0] == "op" and tok[1] == ")":
                    break
                raise FormulaSyntaxError("bad argument list near %r in %r" % (tok[1], self.source))
            return ("func", name, args, addin)
        if kind == "name":
            up = text.upper()
            if up == "TRUE":
                return ("bool", True)
            if up == "FALSE":
                return ("bool", False)
            return _leaf(("name", normalise_name(text), None))
        if kind == "op":
            if text == "(":
                node = self.expr()
                self.expect(")")
                return ("paren", node)
            if text == "{":
                rows: List[List[Any]] = [[]]
                while True:
                    tok = self.take()
                    if tok[0] == "op" and tok[1] == "-":
                        nxt = self.take()
                        if nxt[0] != "num":
                            raise FormulaSyntaxError("bad array constant in %r" % self.source)
                        rows[-1].append(("num", -float(nxt[1])))
                    elif tok[0] == "op" and tok[1] == "+":
                        nxt = self.take()
                        rows[-1].append(("num", float(nxt[1])))
                    elif tok[0] == "num":
                        rows[-1].append(("num", float(tok[1])))
                    elif tok[0] == "str":
                        rows[-1].append(("str", tok[1][1:-1].replace('""', '"')))
                    elif tok[0] == "err":
                        rows[-1].append(("err", tok[1]))
                    elif tok[0] == "name" and tok[1].upper() in ("TRUE", "FALSE"):
                        rows[-1].append(("bool", tok[1].upper() == "TRUE"))
                    else:
                        raise FormulaSyntaxError("bad array constant in %r" % self.source)
                    sep = self.take()
                    if sep[0] == "op" and sep[1] == ",":
                        continue
                    if sep[0] == "op" and sep[1] == ";":
                        rows.append([])
                        continue
                    if sep[0] == "op" and sep[1] == "}":
                        break
                    raise FormulaSyntaxError("bad array constant in %r" % self.source)
                return ("array", rows)
        raise FormulaSyntaxError("unexpected token %r in %r" % (text, self.source))


@functools.lru_cache(maxsize=PARSED_KEPT)
def parse_template(template: str):
    """Parse a formula template (see :func:`tto.xl.tokenizer.to_template`) into an AST.

    Once per process: the AST is kept (:data:`PARSED_KEPT`, the most recently used) and the same one is returned to
    every caller - books, the engine's compilers, the reverse reference index, the dashboard's own sheets, date cells,
    users' formulas -, so it must not be changed.  Threads may ask at once (a template two of them parse at the same
    time is parsed twice; only a whole AST is kept).  A template that does not parse raises each time it is asked."""
    return _Parser(tokenize_template(template), template).parse()


def walk(node):
    """Yield every node of an AST (pre-order)."""
    stack = [node]
    while stack:
        nd = stack.pop()
        yield nd
        kind = nd[0]
        if kind == "func":
            stack.extend(nd[2])
        elif kind == "bin":
            stack.append(nd[2])
            stack.append(nd[3])
        elif kind in ("neg", "pos", "pct", "single", "paren"):
            stack.append(nd[1])
