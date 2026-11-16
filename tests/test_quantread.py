"""The quant tables' read lines (``tto/static/js/pages/quantread.js``): every table the quant pages build has one - a
sentence or two in the desk's words above it, its method note below it as "Yöntem" - within its length and without the
method's jargon, and no line is left for a table that is gone. (On screen, above the table: the browser test.)"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "tto", "static", "js", "pages")

LONGEST = 320                                                           # characters: one or two sentences
# the method's words: they stay in the note below the table ("Yöntem"), not in the line above it
JARGON = ["ADF", "Kalman", "GARCH", "SVI", "EWMA", "OU", "Engle-Granger", "Jacobi", "MacKinnon", "Lo-MacKinlay",
          "lojistik", "varyans oranı", "Nelson-Siegel", "NSS", "eşbütünleşme", "özvektör", "kovaryans", "regresyon"]


def _literal(text, name):
    """The JSON literal between the module's ``// <NAME>`` markers."""
    m = re.search(r"// <%s>\n[^=]*=\s*(.*?);\n// </%s>" % (name, name), text, re.S)
    assert m, name
    return json.loads(m.group(1))


def _lines():
    with open(os.path.join(PAGES, "quantread.js"), encoding="utf-8") as f:
        text = f.read()
    return _literal(text, "READ"), _literal(text, "INFO")


def _fits(key, pid):
    """quantread.js's matching: a panel id, or a pattern whose * stands for the page's name."""
    if key == pid:
        return True
    return "*" in key and re.fullmatch("[a-z0-9-]+".join(re.escape(p) for p in key.split("*")), pid) is not None


def _key(keys, pid):
    return pid if pid in keys else next((k for k in keys if _fits(k, pid)), None)


def _panels():
    """Every panel id the quant pages build: the literal ones, and the ones built from a page's name with each name the
    file's pages have (quantbase.js's - the status and coverage tables - with every page's)."""
    first_arg = re.compile(r"(?<!function )\bpanel\(\s*([^,()]+?)\s*,")
    files, names = {}, {}
    for fn in sorted(os.listdir(PAGES)):
        if fn.startswith("quant") and fn.endswith(".js") and fn != "quantread.js":
            with open(os.path.join(PAGES, fn), encoding="utf-8") as f:
                files[fn] = f.read()
            names[fn] = re.findall(r"super\(host, ctx, '([a-z]+)'\)", files[fn])
    every = sorted({n for ns in names.values() for n in ns})
    ids = set()
    for fn, text in files.items():
        for arg in first_arg.findall(text):
            parts = [p.strip() for p in arg.split("+")]
            if all(p.startswith("'") and p.endswith("'") for p in parts):
                ids.add("".join(p[1:-1] for p in parts))
                continue
            assert all(p.startswith("'") or p in ("this.what", "what") for p in parts), (fn, arg)
            for n in (every if fn == "quantbase.js" else names[fn]):
                ids.add("".join(p[1:-1] if p.startswith("'") else n for p in parts))
    return ids


def test_every_quant_table_has_its_read_line_and_no_line_is_left_over():
    read, info = _lines()
    ids = _panels()
    assert len(ids) > 60                                                # (the parse found the pages' panels)
    missing = sorted(i for i in ids if _key(list(read), i) is None)
    assert not missing, "quantread.js READ'de satırı olmayan tablolar: %s" % missing
    unused = sorted(k for k in read if not any(_fits(k, i) for i in ids))
    assert not unused, "artık olmayan tablolara satır: %s" % unused
    assert set(info) <= {k for k in read if read[k]}, info             # (INFO names lines whose note is not a method)
    assert sum(1 for k in read if read[k]) >= 0.8 * len(read)           # ("": only forms, settings and logs)


def test_read_lines_are_short_and_in_the_desks_words():
    read, _info = _lines()
    jargon = re.compile(r"(?<!\w)(%s)(?!\w)" % "|".join(re.escape(w) for w in JARGON), re.I)
    for key, line in read.items():
        assert line == line.strip() and "  " not in line, key
        assert len(line) <= LONGEST, (key, len(line))
        assert not jargon.search(line), (key, jargon.search(line).group(0))
        assert not line or line[-1] in ".?)", (key, line[-12:])          # (whole sentences)


def test_the_pattern_matching_reads_like_the_page_does():
    assert _fits("quant-*-signals", "quant-pca-signals") and not _fits("quant-*-signals", "quant-signals")
    assert _fits("*-coverage", "pca-coverage") and not _fits("quant-*-chart", "quant-chart")
    assert _key(["quant-*-signals", "quant-lead-signals"], "quant-lead-signals") == "quant-lead-signals"
