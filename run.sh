#!/bin/sh
# TTO Masa dashboard.  Port 1057 (1055 and 1056 are never used).
cd "$(dirname "$0")" && exec python3 -m tto "$@"
