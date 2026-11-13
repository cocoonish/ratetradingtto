"""A ``blpapi`` that is installed but cannot be loaded (on Windows: the C++ library next to it is missing)."""
raise ImportError("DLL load failed while importing blpapi: the specified module could not be found")
