---
name: debug-live-game-logs
description: Analyze a live generals.io game log folder (txtmap snapshots + ~40MB bot log) to find where/why the bot started losing, what it did wrong, and which turns to import as regression tests.
argument-hint: "<game log folder> [question]"
allowed-tools:
  - read
  - grep
  - glob
triggers:
  - user
  - model
---

# Debugging live game logs

Use this for prompts like "figure out where the bot started losing this game and why", "why did it lose city X",
"was it looping / failing to intercept", or "which turns should we import as tests" given a folder like
`C:\GeneralsLogs\GroupedLogs\<BotName>-1v1-<date>---<replayId>` or `C:\KeptGeneralsLogs\...`.

Follow `.windsurfrules` (PowerShell, `.\.venv\Scripts\python.exe`, run from repo root `C:\src\generals-bot`,
outputs under `C:\cascade-debug-output\generals-bot`, never D:\).

## Folder contents

- `_<name>.txt` — the main bot log (~40MB / ~1.5M lines for a ~600 turn game). NEVER read it directly. Use the tools.
- `<turn>.txtmap` — one bot-perspective snapshot per turn (map grid + `key=value` bot/player state). `turn` is the
  server tick: a round is 50 ticks, cities/general give +1 every 2 ticks, tiles give +1 at ticks divisible by 50.
  So per-round income ("econ") = `tiles + 25 * cities`.
- Bot player = `player_index` (0->`a`, 1->`b`). `{c}Score`/`{c}Tiles` are true scoreboard values for every player;
  enemy `{c}CityCount` and enemy grid cells are the bot's estimates (fog). The bot folder name is the bot's username;
  the opponent may be a human.
- Useful txtmap keys: `bot_is_all_in_losing`, `bot_all_in_losing_counter`, `bot_is_all_in_army_advantage`,
  `bot_defend_economy`, `targetPlayerExpectedGeneralLocation`, `{c}General` (present only once a general is known),
  `{c}KnowsKingLocation`, `{c}CityGainedTurn`/`{c}CityLostTurn`, `ot_city_X_Y=owner:turn:army`, `bot_cur_path`.

## Log structure (what the tools rely on)

- A bot turn N ends at a `MOVE Complete: N (secs in, ...)` line. Turn N's block = lines after the previous
  `MOVE Complete` through this one (the server `game_update` WS line with true scores is at the top of the block).
- Scopes: `Beginning tN: <NAME> (x in)` / `Complete tN: (dur) <NAME>` (nested, wrapped in vvv/^^^/---- separators).
- The move: `Beginning tN: Sending move a,b -> c,d to server`. The last top-level scope before it is the
  *decision scope*; the last timestamped log line before it is the *decision hint* (usually the bot's own `info()` text,
  e.g. `CurPath cont ...`, `EXP 24.43/14t ...`, `Send: All in here, hit in 28 moves`). The hint is often more accurate
  than the scope: e.g. `CurPath cont` moves are executing a path chosen on an earlier turn, attributed to whatever
  top-level scope ran last.
- After the move: `MOVE N TIMINGS:` (~130 lines of perf timings) — pure noise for behavior analysis.
- Post-game: `bot gave up :(`, `IN TERMINATE <id>  (won? False)`.

## Tools (all in `LiveGameAnalysis/`, all write files and log the output path)

Default output dir: `C:\cascade-debug-output\generals-bot\game_analysis\<folderName>\`. Each run takes ~1.5-4s.

1. **Stats CSVs (start here)**
   `.\.venv\Scripts\python.exe LiveGameAnalysis\GameStatsGenerator.py <folder>`
   - `<folder>_rounds.csv`: one row per round end (every 50 ticks + final turn). Per player: tiles, score, cities,
     econ, round deltas, `army_spent_or_lost_round` (expected generation minus actual score delta = army lost in
     fights + spent capturing neutrals), cities gained/lost, `last_new_city_turn`, `contested_cities_round`
     (cities that changed hands between players), `contesting`; plus `bot_econ_diff/score_diff/tiles_diff/cities_diff`
     vs the strongest enemy. Read this first to find the round where `bot_econ_diff` starts trending negative.
   - `<folder>_turns.csv`: one row per turn with the same per-player raw numbers, bot flags (all-in state etc.), and
     the log-derived `bot_move, decision_scope, decision_hint, turn_duration, problems`. Use `Import-Csv` + filters in
     PowerShell to slice a turn range rather than reading the whole file.
2. **Log tool**: `.\.venv\Scripts\python.exe LiveGameAnalysis\GameLogTool.py <cmd> <folder> [--from A --to B] [--out F]`
   - `decisions` — per round, counts of normalized decision labels (what was the bot *doing* each round).
   - `overview` — per turn: scores, move, decision scope | hint, plus capped key-event lines (WCA, danger, LKP, city
     captures, intercepts, kills, errors). `--patterns p1 p2 ...` overrides the patterns (e.g. a tile `6,1`).
   - `moves` — CSV move timeline + `moves_loops_*.txt` (oscillations A->B->A, repeated moves, no-move turns).
   - `grep --pattern REGEX [--context K] [--max-per-turn M] [--ignore-case]` — turn-prefixed matches.
   - `scope --scope "A|B"` — every occurrence of matching scopes, compact rendered (replacement for
     `GetLogsForScopeByTurn.ps1`, which also works on live logs now but is much slower).
   - `turn --compact` — one turn (or small range) with timings/separators/WS noise removed (~50% smaller). Only read
     full turns once you know the exact turn that matters.
   - `scopes` — per-scope counts/durations over a range (perf, and what code paths ran).
   - `noise [--top N]` — biggest log line templates by bytes; use it to find logs to comment out.
   Tip: for unique-value timelines, combine grep output with PowerShell, e.g. print only when a value changes:
   `Get-Content out.txt | ? { $_ -match '^t(\d+): \S+ (WinConns:.*)$' } | % { ... if changed ... }`.

## Workflow: "where/why did the bot start losing?"

1. Run GameStatsGenerator; read `_rounds.csv`. Identify: the first round the econ diff goes and stays negative, city
   count divergence (`last_new_city_turn` for each player — a bot that stops taking cities is the most common way to
   lose), big `army_spent_or_lost_round` spikes (fights) and who lost more, and contested/lost cities.
2. Check bot mode flips in `_turns.csv` (`bot_is_all_in_losing`, `bot_all_in_losing_counter`, `bot_defend_economy`...)
   and whether `{enemy}General` ever appears in the txtmaps (unknown enemy general + all-in = gamble).
3. `decisions` for the whole game to see what the bot spent each round doing.
4. Zoom into the suspicious window with `overview --from --to` (keep ranges <= ~50 turns) and targeted `grep`s
   (e.g. `WinConns:` timeline, `No neutral city found|NEUT_CITY_REJECT|Skipped neut`, `CITY_ROUND_OPPORTUNITY_COST`,
   `get_danger_paths`, `EH: Tile captured!`, `CITY_COUNT`). Then `scope` the relevant decision scope on a couple of
   representative turns, then read the code that emitted the deciding log line.
5. Correlate with txtmap grid rows for the exact tiles (e.g. army on a city across turns:
   `(Get-Content "<folder>\<t>.txtmap")[y+1]`).
6. Distinguish confirmed mechanisms (log line proves the code path ran) from hypotheses (missing logging) — when
   logging is missing, say so and add a targeted `logbook.info` at the decision point for future games.

## Picking turns to import as tests

- Choose the earliest turn where the bad decision is already determined by the state and a correct alternative
  exists (e.g. the turn a gather plan is built that drains a frontline city, not the turn the city falls).
- Prefer short, assertable scenarios: "city X still owned after N turns", "bot captures a neutral city within N
  turns", "bot is not all-in at turn T", "bot defends threat on tile X".
- Bot state in txtmap (`bot_all_in_losing_counter`, etc.) is resumed by `BotSerialization`, so counter-based decisions
  reproduce when loading that turn.
- Create tests with `game-result-analysis-utils.ps1`:
  `. .\game-result-analysis-utils.ps1; "<folder>\<turn>.txtmap" | Create-TestContinuingGameFrom -TestCategory BotBehavior -TestName should_xyz`
  (needs `..\run_config.txt`; copies the txtmap into `Tests/GameContinuationEntries` and appends a skeleton test to
  `Tests/test_<Category>.py` that you then fill in with real asserts).

## Keep log noise down

Logs are only useful if the important lines are findable. Run `noise` occasionally; comment out (don't delete) lines
that are high-volume and low-value, with a comment saying why and to uncomment when debugging that feature
(see `BotExpansionOps.prioritize_expansion_leaves` leafMove log, `BotHost` TURN_START_IDENTITY None generals).
Don't touch diagnostics someone is actively using (e.g. `FE_PHASE*_DIAG`, `FLOW_DEMAND_SATURATION*` WARN lines)
without asking. Prefer one structured summary line per decision (`KEY=value ...`) over many per-candidate lines,
unless the candidate count is small and the decision is otherwise opaque (e.g. `NEUT_CITY_REJECT`).
