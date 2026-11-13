#!/bin/sh
# TTO Masa dashboard.  Port 1057 (5000 and 5001 are never used).
cd "$(dirname "$0")" && exec python3 -m tto "$@"
