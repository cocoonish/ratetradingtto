# Developer notes

These notes are for the people and Claude sessions who change the code. The user manual is the Turkish `README.md` at
the root. `CLAUDE.md` at the root is the short version; a Claude session whose folder is in this repository loads it.
Sessions usually start in the install folder, which is no repository: there the `CLAUDE.md` one level up (in the
folder that holds the install and the clones, outside every repository) points here.

| File | Read it before you touch… |
|---|---|
| [curves.md](curves.md) | anything that reads or builds a rate curve: OIS, offshore (FX swap / XCCY), the ASW sheet, ASW FX, PPK basamak / Bootstrap, curve points, buckets, Fiyatlama, Trades MTM, fair values, spot dates |
| [desk-decisions.md](desk-decisions.md) | any behaviour the desk has decided, in their own words with dates. Check here before "improving" something. |
| [market-data.md](market-data.md) | Bloomberg requests and their cost, replay (the 03.11.2026 file), pricing sources, history pacing, reading the desk's database |
| [architecture.md](architecture.md) | where things live: startup, request path, books and the formula engine, `extras.py`'s sheets, modules, store tables, pages, row keys |
| [testing-and-release.md](testing-and-release.md) | tests, the browser test, README counts, the single-file installer, merging and pushing |

**Keeping these files current:**
- When you change how something works or what it depends on, change the note in the same commit.
- When the desk decides something, add it to `desk-decisions.md`, with their words and the date.
- Write no Bloomberg values and no passwords here.
