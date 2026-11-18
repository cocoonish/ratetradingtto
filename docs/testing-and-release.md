# Testing and release

## Who does what

**The main session (the integrator)** keeps the integration clone `ratetradingtto-entegrasyon` on branch `entegrasyon`,
with the other clones wired in as local remotes. When every side session has finished, it:
1. merges their branches;
2. runs the full suite;
3. updates README's counts;
4. rebuilds the installer;
5. compares old with new;
6. checks the install;
7. pushes `entegrasyon:main`.

**Side sessions and agents** work in their own worktree (`../ratetradingtto-<branch>`) on their own branch.
- **Git:** commit only there. Never merge, push, rebase or switch branches.
- **Shared files** (README, `main.js`, `server.py`, `service.py`, `tests/e2e/e2e.js`): touch only your own section.
- **Leave alone:** README's global counts and `kurulum/`.
- **Report at the end:** the branch tip, what changed, the tests run with their counts, anything open, and the
  decisions the user should know about.

**Commits:**
- Command: `git -c user.name=Claude -c user.email=noreply@anthropic.com commit …`.
- End the message with the `Co-Authored-By:` trailer the session was given.
- **Never force-push.**

## Test environment (the desk machine)

Use the clean venv `D:\tto-genis-test\venv`. It was made from `requirements-dev.txt`, with no system packages; installing
anything needs the user's OK. Run from a clone, never from the install folder:

```bash
env -u PYTHONPATH PYTHONIOENCODING=utf-8 /d/tto-genis-test/venv/Scripts/python -m pytest <files> -q -rfEs -p no:cacheprovider --no-header -o faulthandler_timeout=900 --basetemp=<scratch>/agents/<branch>/bt-<branch>-<n>
```

- **Run only what your change touches.** Run the files your change touches; the integrator runs everything. Other
  sessions share the machine.
- **Expected skips:**
  - `test_blpapi_real` (no blpapi in the venv; not collected);
  - the encrypted-workbook test (msoffcrypto-tool is not installed).
- **The full suite** (integrator) takes about 45 min. It runs as two weight-balanced groups side by side, each with its
  own `--basetemp`, with the browser test apart. Heavy files: `test_service` (about 14 min alone), `test_bloomberg`
  and `test_history` (about 5), `test_bonds` and `test_dates` (about 4).
- **Fixtures** (`tests/conftest.py`):
  - `service` is **session-scoped**: every file in a run shares it, and earlier files change its sources, lists and
    inputs. Don't pin a literal that such a change moves. Compare with what the sheet says now, or build your own with
    `make_service(tmp_path)`.
  - `module_service` is module-scoped.
  - `hist` (in `test_aswfx.py`) is module-scoped.
- **Hangs:**
  - Leaving `with TestClient(create_app(s))` stops the service, and a later `s.et.call(...)` in the same test waits
    forever. Put a test's HTTP part last.
  - `-o faulthandler_timeout=900` dumps the stacks.
- **Stopping a run:** stopping the background task leaves `env.exe`, the venv launcher and python alive. Find them by
  your own full `--basetemp` path and `taskkill /PID <id> /T /F`. Never kill by name or a short pattern: other
  sessions' runs and the user's dashboard are python too.
- **`-x` and the bundle test:** never `pytest -x` a run that includes `test_bundle.py`'s freshness test before
  `kurulum/` is rebuilt.

## Browser test

```bash
NODE_PATH="$(npm root -g)" env -u PYTHONPATH PYTHONIOENCODING=utf-8 /d/tto-genis-test/venv/Scripts/python -m pytest tests/test_e2e.py -q -rfEs -s -p no:cacheprovider --basetemp=<scratch>/bt-e2e
```

**What the test does:**
1. `tests/test_e2e.py` picks a free port (never 5000 / 5001).
2. It starts `python -m tto --mode replay` with a fresh data folder and three test accounts.
3. It runs `node tests/e2e/e2e.js` (Playwright + Chromium, installed globally with npm).
4. It prints each check and then "N passed, M failed", and asserts 0 failed.

**It skips quietly** if Node or Playwright is missing: read the output, because a skip looks green.

**Pitfalls:**
- **Load:** a check waits 20 s. Under other sessions' load, run a failed check once more before calling it broken.
- **After a merge**, run `node --check tests/e2e/e2e.js`. Two branches once declared the same `const` in one scope.
- **ES modules** (`tto/static/js/**`): `node --check` can pass a module with a syntax error. Copy it to a `.mjs` file
  and check that.
- **Git Bash** rewrites `"#/x"` arguments; prefix the command with `MSYS_NO_PATHCONV=1`.
- **UI text is Turkish.** Keep existing DOM ids (the browser test uses them) and add new ones for new elements.

## README.md

- It is the Turkish user manual: each feature's section, and the test table with one row per test file.
- Its global counts are:
  - "NNNN test": `pytest tests --collect-only -q`. The browser test counts as 1, and `test_blpapi_real`'s 7 are not
    collected without blpapi.
  - "NNN kontrol": the browser test's checks.
- Only the integrator changes the counts, after merging and measuring. No test reads them.
- **README is inside the installer**, so a README change means a rebuild.

## The installer: one text file

The desk installs everything from GitHub's single `kurulum/tto_kur.txt`, because some networks refuse a ZIP or a `.py`.
This is a requirement.

- **Build:**
  - `python tools/make_bundle.py` writes `kurulum/tto_kur.py` and an identical `kurulum/tto_kur.txt`;
  - `python tools/make_bundle.py --check` tells whether both still match the tree.
- **Contents:** `tto/`, `models/`, `vendor/` (not `vendor/local`), `tools/`, `README.md`, `requirements.txt`, `run.bat`,
  `run.sh`.
- **Left out:** tests, `workbooks/`, `docs/` and `CLAUDE.md`. A change to those does not change the installer.
- **Version:** 10 hex digits of a digest of the contents.
- **Freshness:** `test_bundle`'s freshness test fails whenever a bundled file changed after the build. Rebuild in the
  last commit (the integrator's job).
- **Updating an install:** run the file in or next to the install folder.
  - The manifest `.tto_kur.json` holds the version and the file hashes.
  - Changed files are replaced atomically.
  - A file that was in the old manifest but is not in the new bundle is deleted.
  - `data/` and `vendor/local/` are never touched.
  - A running dashboard is not stopped: restart it afterwards.
  - If a write fails, the script exits 2; run it again to finish.
- **No manifest means a fresh install.** A folder unpacked from an old ZIP counts as fresh, and its stale files stay.

## Release checklist (integrator)

1. Wait until every side session has finished. Merge their branches into `entegrasyon`. In README conflicts, keep both
   sides' rows.
2. Run `node --check tests/e2e/e2e.js`, then the tests of the merged areas.
3. Run the full suite in two groups, and the browser test on a quiet machine. The result must be 0 failed, with only
   the expected skips.
4. Update README's counts.
5. Rebuild the installer. Run `--check` and `test_bundle`.
6. **Compare old and new.** Run the old and new checkouts in replay, each on its own port (1095 / 1096) with an empty
   data folder, and read every page twice. Every difference must be intended. Seed the synthetic history for quant.
7. **Install check, on a copy of the desk's install.**
   - Copy the database through SQLite's backup.
   - The update over the copy must keep every table and account.
   - A fresh install from the `.txt` must start, and its pages must open.
   - Use a free port such as 1083 - never 1057, 1058, 1079, 5000 or 5001.
8. **Push and confirm.**
   - Push: `git push origin entegrasyon:main`, fast-forward only.
   - Confirm: `git ls-remote origin main`, then check that `git rev-parse origin/main:kurulum/tto_kur.txt` equals
     `git hash-object kurulum/tto_kur.txt` of the tested file.
9. Remove merged worktrees and branches. Note the push in the shared notes.
10. **One push carries all the day's requests.** Tell the user whether it needs an install at the office. A push that
    leaves `kurulum/` unchanged does not.

### Helper scripts

The integrator's helpers live in its scratch folder, not in this repository, and a reboot can clear them:

| Script | What it does |
|---|---|
| `split_suite.py` | splits the suite into the two groups |
| `readme_counts3.py` | writes the measured counts into README |
| `merge_rows2.py` | merges README's test-table rows during a merge |
| `compare_r4.py` | the old-vs-new comparison |
| `install_check.py` | the install check |
| `e2e_slow.py` | the browser test with long waits |

If they are gone, rebuild them from the steps above.
