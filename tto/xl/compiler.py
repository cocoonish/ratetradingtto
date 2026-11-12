"""Formula template -> Python function.

Each template is compiled once into ``f(X, S, r, c)`` where ``X`` is the calculation context, ``S`` the
host sheet index and ``(r, c)`` the host cell.  Two evaluation bases exist, mirroring Excel:

* base ``S`` (ordinary formulas): operands are scalars; a multi-cell reference in a scalar position is
  reduced by *implicit intersection* with the host cell.
* base ``A`` (array / dynamic-array formulas and the arguments of array-forcing functions such as
  SUMPRODUCT): operators broadcast element-wise and scalar functions are lifted over arrays.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from . import functions as _fn
from . import values as _v
from .errors import (E_CALC, E_DIV0, E_NA, E_NAME, E_NULL, E_NUM, E_REF, E_SPILL, E_VALUE, E_GETTING, XlError)
from .functions import FUNCS
from .parser import parse_template
from .tokenizer import FormulaSyntaxError
from .values import XlArray

_OPS = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "^": "POW", "&": "CAT",
        "=": "EQ", "<>": "NE", "<": "LT", ">": "GT", "<=": "LE", ">=": "GE"}

_ERR_NAMES = {"#NULL!": "E_NULL", "#DIV/0!": "E_DIV0", "#VALUE!": "E_VALUE", "#REF!": "E_REF", "#NAME?": "E_NAME",
              "#NUM!": "E_NUM", "#N/A": "E_NA", "#SPILL!": "E_SPILL", "#CALC!": "E_CALC",
              "#GETTING_DATA": "E_GETTING"}

ADDINS = ("BDP", "BDH", "BDS", "BFXFORWARD", "BINTERPOL", "RTGET", "BQL", "BCURVE")
_ADDIN_MULTI = ("BDH", "BDS", "BQL")


def base_namespace() -> Dict[str, Any]:
    ns: Dict[str, Any] = {}
    for name in ("ADD", "SUB", "MUL", "DIV", "POW", "CAT", "EQ", "NE", "LT", "GT", "LE", "GE", "NEG", "PCT",
                 "ADDT", "SUBT", "range_union", "deref", "first", "XlArray"):
        ns[name] = getattr(_v, name)
    ns["IX"] = lambda X, r, c, v: _v.intersect(v, r, c)
    ns["IXV"] = _v.intersect
    ns["DR"] = _v.deref
    for name in dir(_fn):
        if name.startswith("F_") or name in ("IF3", "IFA", "IFE", "IFEA", "IFNA", "CHOOSE", "LIFT", "INDEX_S"):
            ns[name] = getattr(_fn, name)
    for code, pyname in _ERR_NAMES.items():
        ns[pyname] = XlError(code)
    ns["__builtins__"] = {"float": float, "True": True, "False": False, "None": None}
    return ns


class Compiler(object):
    def __init__(self, model):
        self.model = model
        self.ns = base_namespace()
        self._cache: Dict[Tuple[int, bool], Any] = {}
        self._name_ast: Dict[str, Any] = {}
        self._nconst = 0
        self.unknown_functions: Set[str] = set()
        self.errors: List[str] = []

    # ------------------------------------------------------------------ public
    def function(self, tid: int, is_array: bool):
        key = (tid, is_array)
        fn = self._cache.get(key)
        if fn is None:
            fn = self._compile(self.model.templates[tid], is_array)
            self._cache[key] = fn
        return fn

    def source(self, template: str, is_array: bool = False) -> str:
        ast = parse_template(template)
        self._scope: List[Dict[str, str]] = []
        self._nlocal = 0
        if is_array:
            body = self.ref(ast, "A")
        elif ast[0] == "bin" and ast[1] in ("+", "-"):
            # the final + / - of a formula snaps negligible results to zero (Excel behaviour)
            body = "%s(%s, %s)" % ("ADDT" if ast[1] == "+" else "SUBT",
                                   self.value(ast[2], "S"), self.value(ast[3], "S"))
        else:
            body = self.value(ast, "S")
        return "def f(X, S, r, c):\n    cv = X.cv\n    rg = X.rg\n    return " + body + "\n"

    def compile_node(self, node, base: str = "S"):
        """Compile one AST node (e.g. an argument of a call) into ``f(X, S, r, c)``; references are kept."""
        self._scope = []
        self._nlocal = 0
        src = "def f(X, S, r, c):\n    cv = X.cv\n    rg = X.rg\n    return " + self.ref(node, base) + "\n"
        loc: Dict[str, Any] = {}
        exec(compile(src, "<formula-arg>", "exec"), self.ns, loc)
        return loc["f"]

    def compile_expression(self, template: str, is_array: bool = False):
        """Compile an ad-hoc formula template (used for defined names / tests)."""
        return self._compile(template, is_array)

    # ------------------------------------------------------------------ internals
    def _compile(self, template: str, is_array: bool):
        try:
            src = self.source(template, is_array)
            loc: Dict[str, Any] = {}
            exec(compile(src, "<formula>", "exec"), self.ns, loc)
            return loc["f"]
        except (FormulaSyntaxError, SyntaxError, RecursionError, MemoryError, KeyError, IndexError) as exc:
            self.errors.append("%s: %s" % (template[:120], exc))
            return _bad_formula

    def _sheet(self, sheet: Optional[str]) -> Optional[str]:
        if sheet is None:
            return "S"
        idx = self.model.sheet_index.get(sheet)
        return None if idx is None else str(idx)

    @staticmethod
    def _rc(abs_: bool, val: int, base: str) -> str:
        if abs_:
            return str(val)
        if val == 0:
            return base
        return "%s%+d" % (base, val)

    def _range_code(self, nd) -> str:
        kind = nd[0]
        s = self._sheet(nd[1])
        if s is None:
            return "E_REF"
        if kind == "cell":
            r = self._rc(nd[2], nd[3], "r")
            c = self._rc(nd[4], nd[5], "c")
            return "rg(%s, %s, %s, %s, %s)" % (s, r, c, r, c)
        if kind == "range":
            return "rg(%s, %s, %s, %s, %s)" % (s, self._rc(nd[2], nd[3], "r"), self._rc(nd[4], nd[5], "c"),
                                              self._rc(nd[6], nd[7], "r"), self._rc(nd[8], nd[9], "c"))
        if kind == "cols":
            return "X.cols(%s, %s, %s)" % (s, self._rc(nd[2], nd[3], "c"), self._rc(nd[4], nd[5], "c"))
        if kind == "rows":
            return "X.rows(%s, %s, %s)" % (s, self._rc(nd[2], nd[3], "r"), self._rc(nd[4], nd[5], "r"))
        raise FormulaSyntaxError("not a reference node: %r" % (nd,))

    def _lookup_name(self, name: str):
        """-> ("local", pyvar) | ("ast", node) | None"""
        for scope in reversed(self._scope):
            if name in scope:
                return ("local", scope[name])
        ast = self._name_ast.get(name)
        if ast is None:
            tpl = self.model.names.get(name)
            if tpl is None:
                return None
            ast = parse_template(tpl)
            self._name_ast[name] = ast
        return ("ast", ast)

    def _const(self, value) -> str:
        self._nconst += 1
        name = "_K%d" % self._nconst
        self.ns[name] = value
        return name

    # ------------------------------------------------------------------ value / reference compilation
    def value(self, nd, base: str) -> str:
        """Code producing a value: a scalar in base S, a scalar / array in base A."""
        kind = nd[0]
        if kind == "num":
            return repr(nd[1])
        if kind == "str":
            return repr(nd[1])
        if kind == "cell":
            s = self._sheet(nd[1])
            if s is None:
                return "E_REF"
            return "cv(%s, %s, %s)" % (s, self._rc(nd[2], nd[3], "r"), self._rc(nd[4], nd[5], "c"))
        if kind == "bin":
            op = nd[1]
            if op == ":":
                code = "range_union(%s, %s)" % (self.ref(nd[2], base), self.ref(nd[3], base))
                return "IXV(%s, r, c)" % code if base == "S" else code
            return "%s(%s, %s)" % (_OPS[op], self.value(nd[2], base), self.value(nd[3], base))
        if kind == "func":
            return self.func(nd, base, False)
        if kind == "paren":
            return "(" + self.value(nd[1], base) + ")"
        if kind in ("range", "cols", "rows"):
            code = self._range_code(nd)
            return "IXV(%s, r, c)" % code if base == "S" else code
        if kind == "name":
            hit = self._lookup_name(nd[1])
            if hit is None:
                return "E_NAME"
            if hit[0] == "local":
                return "IXV(%s, r, c)" % hit[1] if base == "S" else "DR(%s)" % hit[1]
            return self.value(hit[1], base)
        if kind == "neg":
            return "NEG(%s)" % self.value(nd[1], base)
        if kind == "pos":
            return self.value(nd[1], base)
        if kind == "pct":
            return "PCT(%s)" % self.value(nd[1], base)
        if kind == "bool":
            return "True" if nd[1] else "False"
        if kind == "err":
            return _ERR_NAMES.get(nd[1], "E_VALUE")
        if kind == "missing":
            return "None"
        if kind == "single":
            return "IXV(%s, r, c)" % self.ref(nd[1], base)
        if kind == "array":
            rows = [[self._literal(x) for x in row] for row in nd[1]]
            if base == "S":
                return repr(rows[0][0])
            return self._const(XlArray(rows))
        raise FormulaSyntaxError("cannot compile node %r" % (kind,))

    @staticmethod
    def _literal(nd):
        if nd[0] == "err":
            return XlError(nd[1])
        return nd[1]

    def ref(self, nd, base: str) -> str:
        """Code that keeps references as references (for range-taking parameters)."""
        kind = nd[0]
        if kind in ("cell", "range", "cols", "rows"):
            return self._range_code(nd)
        if kind == "name":
            hit = self._lookup_name(nd[1])
            if hit is None:
                return "E_NAME"
            if hit[0] == "local":
                return hit[1]
            return self.ref(hit[1], base)
        if kind == "paren":
            return self.ref(nd[1], base)
        if kind == "bin" and nd[1] == ":":
            return "range_union(%s, %s)" % (self.ref(nd[2], base), self.ref(nd[3], base))
        if kind == "func":
            return self.func(nd, base, True)
        if kind == "array":
            return self._const(XlArray([[self._literal(x) for x in row] for row in nd[1]]))
        return self.value(nd, base)

    # ------------------------------------------------------------------ functions
    def func(self, nd, base: str, want_ref: bool) -> str:
        name, args, addin = nd[1], nd[2], nd[3]
        special = getattr(self, "_f_" + name.replace(".", "_"), None)
        if special is not None:
            return special(args, base, want_ref)
        if addin or name in ADDINS:
            # add-in arguments keep references (BINTERPOL takes ranges); the provider scalarises the rest
            codes = ", ".join("None" if a[0] == "missing" else self.ref(a, base) for a in args)
            code = "X.addin(%r, S, r, c, (%s%s))" % (name, codes, "," if len(args) == 1 else "")
            if want_ref:
                return code
            if base == "S":
                return "IXV(%s, r, c)" % code
            return code
        spec = FUNCS.get(name)
        if spec is None:
            self.unknown_functions.add(name)
            return "E_NAME"
        codes: List[str] = []
        vpos: List[int] = []
        for i, a in enumerate(args):
            k = spec.kind(i)
            if a[0] == "missing":
                codes.append("None")
            elif k == "v":
                codes.append(self.value(a, base))
                vpos.append(i)
            elif k == "r":
                codes.append(self.ref(a, base))
            else:
                codes.append(self.ref(a, "A"))
        if base == "A" and vpos:
            call = "LIFT(%s, (%s,), [%s])" % (spec.pyname, ", ".join(str(i) for i in vpos), ", ".join(codes))
        else:
            call = "%s(%s)" % (spec.pyname, ", ".join(codes))
        if spec.multi and not want_ref:
            return "IXV(%s, r, c)" % call if base == "S" else "DR(%s)" % call
        return call

    def _branch(self, nd, base: str, want_ref: bool) -> str:
        if nd[0] == "missing":
            return "0.0"
        return self.ref(nd, base) if want_ref else self.value(nd, base)

    def _f_IF(self, args, base, want_ref):
        if not args:
            return "E_VALUE"
        cond = self.value(args[0], base)
        a = self._branch(args[1], base, want_ref) if len(args) > 1 else "True"
        b = self._branch(args[2], base, want_ref) if len(args) > 2 else "False"
        return "%s(%s, lambda: %s, lambda: %s)" % ("IF3" if base == "S" else "IFA", cond, a, b)

    def _f_IFERROR(self, args, base, want_ref):
        if not args:
            return "E_VALUE"
        v = self._branch(args[0], base, want_ref)
        alt = self._branch(args[1], base, want_ref) if len(args) > 1 else "0.0"
        return "%s(%s, lambda: %s)" % ("IFE" if base == "S" else "IFEA", v, alt)

    def _f_IFNA(self, args, base, want_ref):
        v = self._branch(args[0], base, want_ref)
        alt = self._branch(args[1], base, want_ref) if len(args) > 1 else "0.0"
        return "IFNA(%s, lambda: %s)" % (v, alt)

    def _f_CHOOSE(self, args, base, want_ref):
        idx = self.value(args[0], "S") if base == "S" else "first(%s)" % self.value(args[0], base)
        thunks = ", ".join("lambda: " + self._branch(a, base, want_ref) for a in args[1:])
        return "CHOOSE(%s, (%s,))" % (idx, thunks)

    def _f_LET(self, args, base, want_ref):
        if len(args) < 3 or len(args) % 2 == 0:
            return "E_VALUE"
        scope: Dict[str, str] = {}
        self._scope.append(scope)
        try:
            bindings: List[Tuple[str, str]] = []
            for i in range(0, len(args) - 1, 2):
                nm = args[i]
                if nm[0] != "name":
                    return "E_VALUE"
                code = self.ref(args[i + 1], base)
                self._nlocal += 1
                var = "_L%d" % self._nlocal
                bindings.append((var, code))
                scope[nm[1]] = var
            body = self.ref(args[-1], base) if want_ref else self.value(args[-1], base)
        finally:
            self._scope.pop()
        for var, code in reversed(bindings):
            body = "(lambda %s: %s)(%s)" % (var, body, code)
        return body

    def _f_SINGLE(self, args, base, want_ref):
        return "IXV(%s, r, c)" % self.ref(args[0], base)

    def _f_ROW(self, args, base, want_ref):
        if not args:
            return "float(r)"
        code = "F_ROW(%s)" % self.ref(args[0], base)
        if want_ref or base == "A":
            return code
        return "IXV(%s, r, c)" % code

    def _f_COLUMN(self, args, base, want_ref):
        if not args:
            return "float(c)"
        code = "F_COLUMN(%s)" % self.ref(args[0], base)
        if want_ref or base == "A":
            return code
        return "IXV(%s, r, c)" % code

    def _f_TODAY(self, args, base, want_ref):
        return "X.today()"

    def _f_NOW(self, args, base, want_ref):
        return "X.now()"

    def _f_NA(self, args, base, want_ref):
        return "E_NA"

    def _f_TRUE(self, args, base, want_ref):
        return "True"

    def _f_FALSE(self, args, base, want_ref):
        return "False"

    def _f_INDEX(self, args, base, want_ref):
        if base == "S" and not want_ref and 1 <= len(args) <= 4:
            codes = [self.ref(args[0], "A")]
            for a in args[1:]:
                codes.append("None" if a[0] == "missing" else self.value(a, "S"))
            return "INDEX_S(X, r, c, %s)" % ", ".join(codes)
        nd = ("func", "INDEX\0", args, False)
        # generic path (registered spec) without re-entering this special form
        spec = FUNCS["INDEX"]
        codes: List[str] = []
        vpos: List[int] = []
        for i, a in enumerate(args):
            if a[0] == "missing":
                codes.append("None")
            elif i == 0:
                codes.append(self.ref(a, "A"))
            else:
                codes.append(self.value(a, base))
                vpos.append(i)
        if base == "A" and vpos:
            call = "LIFT(F_INDEX, (%s,), [%s])" % (", ".join(str(i) for i in vpos), ", ".join(codes))
        else:
            call = "F_INDEX(%s)" % ", ".join(codes)
        if want_ref:
            return call
        return "IXV(%s, r, c)" % call if base == "S" else "DR(%s)" % call


def _bad_formula(X, S, r, c):
    return E_NAME
