---
name: unittest-regression-workflow
description: Run this repo's unittest suite correctly (PYTHONPATH, bypass_ui, output redirection), diff results against stored baselines to isolate real regressions from the many pre-existing failures, and read per-turn test output.
allowed-tools:
  - read
  - grep
  - glob
  - exec
triggers:
  - user
  - model
---

# unittest & regression workflow

How to run tests and tell real regressions from this repo's substantial pre-existing failure set.

## Running tests

- Interpreter: `python3.14` (or `.venv\Scripts\python3.14.exe`) — never `python`.
- Run from repo root `C:\src\generals-bot`; tests importing `TestBase` need
  `PYTHONPATH="C:\src\generals-bot\Tests;C:\src\generals-bot"`.
- `bypass_ui=True` env var for any test containing
  `debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True` — do NOT edit the flag.
- Long output: `cmd /c "... > C:\cascade-debug-output\generals-bot\<name>.txt 2>&1"` —
  OS-level redirect, not PowerShell pipes (they hang). Never write to `D:\`.
- Bash env-var prefix works in this shell: `PYTHONPATH="..." bypass_ui=True python3.14 -m unittest <target>`.

```powershell
# single test
PYTHONPATH="C:\src\generals-bot\Tests;C:\src\generals-bot" bypass_ui=True python3.14 -m unittest Tests.test_AllIn.AllInTests.test_should_xyz

# module(s)
PYTHONPATH="C:\src\generals-bot\Tests;C:\src\generals-bot" bypass_ui=True python3.14 -m unittest Tests.test_AllIn UnitTests.test_StealthAllInResume
```

## Baseline diffing — the only honest regression check

This repo has many pre-existing failures (moved tests, known flakes, test-file bugs).
A raw FAIL/ERROR count is meaningless — always diff per-test status against a stored
baseline taken BEFORE your change:

```powershell
.\.venv\Scripts\python.exe RunUnittestBaseline.py --target Tests.test_AllIn --name allin_before_fix
# ... make change ...
.\.venv\Scripts\python.exe RunUnittestBaseline.py --target Tests.test_AllIn --name allin_after_fix
```

- Writes `<name>_raw.txt` (full output) + `<name>_summary.txt` (stable PASS/FAIL/ERROR lines)
  under `C:\cascade-debug-output\generals-bot`. Sets PYTHONPATH + bypass_ui itself.
- Diff the summaries by test NAME — subtests repeat names; dedupe.
- For quick ad-hoc diffs of a raw unittest log:

```python
import re
def fails(p):
    return {m.group(2) for line in open(p, errors='replace')
            if (m := re.match(r'^(FAIL|ERROR): (test_\w+)', line))}
new = fails('after.txt') - fails('before.txt')
```

- Gotcha: a baseline predating a test MOVE won't contain the moved tests under their new
  suite — check the scoped per-suite baselines (`*_scoped_on/off_summary.txt`) before
  calling something a new failure. A FAIL->ERROR mode change is still a pre-existing failure
  if the signature matches.
- Currently-known pre-existing signatures (all in stored baselines): `GatherDebug` NameError
  in `Tests/test_WatchmanRouteUtils.py` (missing import in the test file itself),
  `ValueError: list.remove(x): x not in list` in `switch_to_all_in` tests,
  `no_flags_450` flake, and most moved `BotBehavior` all-in tests fail flag-on.

## Reading test output

- Bot logs mark turns two ways: `~~~ Turn N ~~~` banners and per-scope
  `Beginning tN: <SCOPE> (x in)` / `Complete tN: (dur) <SCOPE>` pairs wrapped in
  `vvv/^^^/-----` separators. The actual move is `Beginning tN: Sending move a,b -> c,d`.
- Grep the dump for the mechanism's structured tag — bot code logs decisions as
  `KEY=value` lines (e.g. `STEALTH_ALLIN_COMMIT turn=292 routeLen=25 headArmy=114`,
  `STEALTH_ALLIN_ROUTE_MOVE`, `STEALTH_ALLIN_ABORT reason=army_wall`,
  `STEALTH_ALLIN_DIVE_REBASE`, `STEALTH_ALLIN_WAIT reason=cannot_kill`,
  `STEALTH_ALLIN_ARMY_WALL`).
- `EH: Tile discovered handler! Tile (x,y b57 54d|54u)` = fog reveal — `(x,y <char><army>
  <down>diffs|<up>diffs)`. `EH: Tile captured! Tile (x,y a34 -91d|-91u)`.
- `update_tile_islands changedTiles` dumps `x,y pl=P(was Q) army=A(was B) disc=D` — the
  authoritative per-turn view of what the bot's map believes vs last turn.
- Extract one turn's full block:
  `sed -n '/Beginning t300:/,/Beginning t301:/p' file.txt`
  or use `GetLogsForScopeByTurn.ps1` / `LiveGameAnalysis/GameLogTool.py scope` for scoped slices.
- For sim-vs-belief questions, dump tile state from a loaded map directly:

```python
from TestBase import TestBase
tb = TestBase('runTest')
rawMap, gen = tb.load_map_and_general('GameContinuationEntries/<f>.txtmap',
                                      respect_undiscovered=True, turn=<t>)
t = rawMap.GetTile(x, y)   # t.player, t.army, t.discovered, t.isCity, t.isMountain
```

- txtmap grids: each cell is 4-5 chars wide (`a2`, `b57`, `bC79` = enemy city 79,
  `aG12`/`bG40` = generals, `M` mountain, `C`/`bC` city, `D` marks discovered).
  Row N of the map = file line N+1; col index = cell index. Width differs between
  bot maps (4-char cells) and truemaps (5-char) — count cells, don't eyeball columns.

## Per .windsurfrules

- If a change doesn't fix the issue after testing, revert before trying the next thing.
- Add `logbook.info/warn` at decision points — never `print`, never guess when a log can tell.
- `py_compile` every touched file immediately; run a relevant test right after each change —
  live games run off this tree, so a half-wired save can throw in a real game.
