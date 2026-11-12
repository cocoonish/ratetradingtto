"""Excel error values."""
from __future__ import annotations


class XlError(object):
    """An Excel error value (``#N/A``, ``#DIV/0!`` ...).  Instances are singletons per code."""

    __slots__ = ("code",)
    _pool = {}

    def __new__(cls, code):
        inst = cls._pool.get(code)
        if inst is None:
            inst = object.__new__(cls)
            inst.code = code
            cls._pool[code] = inst
        return inst

    def __repr__(self):
        return self.code

    __str__ = __repr__

    def __reduce__(self):
        return (XlError, (self.code,))

    def __bool__(self):  # errors must never be used as conditions silently
        raise TypeError("XlError used in boolean context: %s" % self.code)


E_NULL = XlError("#NULL!")
E_DIV0 = XlError("#DIV/0!")
E_VALUE = XlError("#VALUE!")
E_REF = XlError("#REF!")
E_NAME = XlError("#NAME?")
E_NUM = XlError("#NUM!")
E_NA = XlError("#N/A")
E_SPILL = XlError("#SPILL!")
E_CALC = XlError("#CALC!")
E_GETTING = XlError("#GETTING_DATA")

ERROR_CODES = ("#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#SPILL!", "#CALC!", "#GETTING_DATA")


def is_error(v):
    return type(v) is XlError
