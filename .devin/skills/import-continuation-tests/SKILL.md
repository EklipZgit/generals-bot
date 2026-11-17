---
name: import-continuation-tests
description: Import a live generals.io game turn as a continuation regression test — true-map ground truth, bot vision map, resume-state serialization, and assert patterns. Use when asked to turn a specific turn into a test.
argument-hint: "<game log folder> <turn> [behavior to pin]"
allowed-tools:
  - read
  - grep
  - glob
  - exec
  - edit
  - write
triggers:
  - user
  - model
---

# Importing a live-game turn as a continuation test

Converts one turn from `C:\GeneralsLogs\GroupedLogs\<folder>` into a `Tests/test_<Category>.py`
regression test that resumes mid-game and asserts correct behavior.

## The importer — always use it, never hand-copy

From `C:\src\generals-bot` (requires `..\run_config.txt`):

```powershell
. .\game-result-analysis-utils.ps1
"C:\GeneralsLogs\GroupedLogs\<folder>\<turn>.txtmap" | Create-TestContinuingGameFrom -TestCategory AllIn -TestName should_xyz
# -MovesTurns N (default 25) controls how many post-turn moves get captured;
#  0 disables capture entirely.
```

What it does:
- Copies the bot-perspective `<turn>.txtmap` into `Tests/GameContinuationEntries/<TestName>___<replayId>---<playerIndex>--<turn>.txtmap`.
- Dumps the replay TRUE map as a sibling `...truemap.txtmap` via `Invoke-ReplayTrueMapDump`.
- Records every move each player actually executed over the next `MovesTurns`
  turns (default 25) from the replay, and emits them as `queue_player_moves_str`
  lines in the generated test — opponents' lines active, the bot's own real line
  commented out.
- Appends a test skeleton to `Tests/test_<Category>.py` that loads both.

**Never copy/rename a txtmap by hand** — that bypasses the truemap dump and produces fixtures
with no ground truth (`---a--` naming is a pre-importer convention, not what the tool makes;
`player_index=0` produces `---0--`). If you find a fixture without a `.truemap.txtmap` sibling
that shares replay+turn with one that does, the truemap is byte-identical — copy it under the
expected name and repoint the test instead of re-dumping.

## Test structure

```python
mapFile = 'GameContinuationEntries/<name>___<replay>---0--<turn>.txtmap'
trueMapFile = 'GameContinuationEntries/<name>___<replay>---0--<turn>.truemap.txtmap'
map, general, enemyGeneral = self.load_map_and_generals(trueMapFile, <turn>, fill_out_tiles=True)
rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=<turn>)
self.enable_search_time_limits_and_disable_debug_asserts()
simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
# replay moves for the 25 turns after turn <turn>
simHost.queue_player_moves_str(0, 'x,y->x,y  none  ...')  # replay moves: <enemy username>
# simHost.queue_player_moves_str(general.player, 'x,y->x,y  ...')  # replay line for <bot username>
bot = self.get_debug_render_bot(simHost, general.player)
playerMap = simHost.get_player_map(general.player)
self.begin_capturing_logging()
winner = simHost.run_sim(run_real_time=debugMode and not self.GLOBAL_BYPASS_RENDERING, turn_time=0.25, turns=N)
```

Ground rules:
- **truemap = simulator ground truth** (`load_map_and_generals`, `fill_out_tiles=True`).
  **bot txtmap = bot vision/resume state** (`load_map_and_general`, `respect_undiscovered=True`).
  Never feed the fog map to the simulator.
- `allAfkExceptMapPlayer=True` + `queue_player_moves_str(enemy, 'None')` makes the enemy static —
  the sim is deterministic; a kill either happens or it doesn't.
- Keep `enable_search_time_limits_and_disable_debug_asserts()` — removing it lets unrelated
  asserts crash first.
- Bot state resumes from txtmap keys (`bot_all_in_losing_counter`, `bot_is_all_in_losing`,
  `targetPlayerExpectedGeneralLocation`, `bot_stealth_*`) — counter-dependent decisions
  reproduce faithfully from the imported turn.

## `# proof` lines — REQUIRED before writing asserts

Before trusting a test, prove the desired behavior actually passes it by scripting the correct
moves yourself. `simHost.queue_player_moves_str(player, moves_str)` injects moves for a player
directly (bypassing bot logic): queue the moves the bot *should* make, run the sim, and confirm
the asserts pass. This does two things:

1. **Validates the test is achievable** — if your scripted correct line can't pass, the
   fixture/state/assert is wrong, not the bot. Never ship a test whose correct behavior you
   haven't seen pass.
2. **Measures the turn budget** — the proof line shows exactly how many turns correct behavior
   takes, which is what sets the tight `turns=N` above (correct turns + small margin).

Then **comment it out but LEAVE it in the file** — it documents the intended line for the next
person debugging this test and lets them re-verify. Examples (format: `x,y->x',y'->...` paths,
double-space separated, `z` suffix = move_half, `none` = no-op turn):

```python
        # proof
        # simHost.queue_player_moves_str(general.player, '14,19->14,18->16,18->16,10->18,10  17,19->16,19->16,18  17,12->16,12  14,20->14,18->16,18->16,10->19,10->19,9')
```

```python
        # proof
        # simHost.queue_player_moves_str(general.player, '9,10->9,11->11,11->11,13')
        # simHost.queue_player_moves_str(general.player, '2,5->2,8')  # proof
        # simHost.queue_player_moves_str(general.player, '15,9->14,9z->13,9')  # proof this works
```

Enemy-player scripting (`queue_player_moves_str(enemyGeneral.player, '...')`) is NOT a proof
line — it's part of the repro (drives the opponent). The proof line is always the one driving
`general.player` (the bot's own moves).

## Asserts

- **Keep `run_sim(turns=N)` as tight as the repro allows — not longer.** First measure how many
  turns the CORRECT behavior needs (grep the log for the deciding event), then budget that plus
  a small margin — not a round 32/50 "to be safe". Oversized windows are a double failure:
  (a) they waste compute multiplying a slow suite, and (b) worse, they let much-slower-than-
  correct behavior eventually stumble into the right outcome and PASS — e.g. a route that
  wastes 15 turns gather-looping still reaches the tile inside a 50-turn window, so the test
  certifies the exact stall it was written to prevent. The turn budget IS part of the spec:
  "kills in 11 turns" and "kills in 40 turns" are different behaviors; pin the fast one.
  If the window must grow to pass, that's the test telling you the fix is still too slow —
  investigate the timing, don't inflate the budget.
- Kill: `self.assertOwned(general.player, enemyGeneral)` — capturing the enemy general transfers
  ownership; prefer this over proximity asserts when the behavior should actually kill.
- `self.assertNoFriendliesKilled(map, general)` always.
- **Never call `run_sim` twice in one test** — the first call's final `make_move` (run_sim's
  end-of-run state-refresh, `GameSimulator.py:884`) leaves a move queued in `sim.moves` that is
  never consumed, so the second call's first `set_next_move` raises
  `player N already has a move queued this turn`. For mid-run asserts, register a
  `simHost.run_between_turns(fn)` hook: it fires after every turn inside one `run_sim`; gate on
  `simHost.sim.turn == <targetTurn>` and record `simHost.get_player_map(p)` state into a list,
  then assert on the recorded values after the run.
- `debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True` — run with `bypass_ui=True`
  instead of editing it.
- If the intended behavior can't deterministically kill (e.g. lone dive vs a 56-army general),
  pin the *trajectory* instead: largest non-general stack within N tiles of a candidate region —
  but prefer the kill assert once a fix makes the kill reliable, and say why in the comment.

## Resume-state serialization contract

- **Island rebuild vs fog-guess obstacles**: live-pathable fog tiles that were *guessed* as
  enemy cities reload as `TILE_OBSTACLE` (`reset_wrong_undiscovered_fog_guess` on import) even
  though the serialized `island_ids` still carry their island ids from live play.
  `rebuild_islands_from_ids` cannot flood-claim obstacle tiles → `full_island=None` crashes
  inside `GameSimulatorHost` construction. `Algorithms/TileIslandBuilder.py` skips
  `tile.isObstacle` during the id rebuild exactly like mountains —
  `debug_verify_all_islands` already ignores obstacle tiles in the lookup scan, so skipping
  is the consistent semantic (do NOT create singleton islands for them: border computation
  skips obstacles too and produces asymmetric `border_islands` verify failures).
- **Spawn-fairness recompute vs serialized `bValidGeneralPos`**: fixtures predating
  `{char}SpawnFairness` weights serialization fall into the `island_ids` recompute path in
  `BotSerialization.load_spawn_fairness_weights`, which runs
  `initialize_spawn_fairness_weights` on the *resume-turn* map — but `score_spawn_fairness_tile`
  reads live tile state (`isObstacle`/`isMountain`/`isCity` are walls), so discovered
  cities/mountains and fog-guessed `TILE_OBSTACLE`s shrink the BFS counts vs live's
  spawn-time computation and `eliminate_negative_spawn_fairness_positions` can strip
  candidate positions the live game still considered valid (including the true general
  tile). The serialized `bValidGeneralPos` is authoritative: when it is present,
  `initialize_spawn_fairness_weights(apply_eliminations=False)` keeps the recomputed
  weights for scoring while trusting the restored candidacy set.

If the behavior you're importing involves a committed plan/route/state that must survive a
txtmap dump mid-execution (e.g. `bot_stealth_committed_route`), that state is serialized in
`BotModules/BotRendering.py` and restored by a `load_*_from_resume_data` method (see
`BotStealthAllIn.load_committed_route_from_resume_data`). **When you add a new field to such
state, add both sides** — write it in BotRendering's `bot_*` block and parse it (with a
`resume_data.get(key, default)` fallback for old fixtures) in the loader — or mid-route resume
tests silently drop it.

## Verifying the import

1. The skeleton should reproduce the bug — run it and confirm the bad behavior appears in logs
   (see `unittest-regression-workflow` for how to read test output).
2. Write the real asserts, watch them fail for the right reason, then fix.
3. Per `.windsurfrules` #13: comment referencing `Tests/test_X.py::ClassName.test_name` above
   every code path added to fix the test, explaining the mechanism.
