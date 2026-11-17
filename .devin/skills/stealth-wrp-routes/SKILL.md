---
name: stealth-wrp-routes
description: Architecture and invariants of the stealth all-in / Watchman Route Planning subsystem — StealthAllInState, worker-process WRP jobs, committed-route execution, safe-front truncation, army-wall aborts, and txtmap serialization. Use when touching BotStealthAllIn, WatchmanRouteUtils, or WRP-related tests.
allowed-tools:
  - read
  - grep
  - glob
triggers:
  - user
  - model
---

# Stealth all-in & Watchman Route Planning

Map of the losing-all-in stealth subsystem: `BotModules/BotStealthAllIn.py`,
`Algorithms/WatchmanRouteUtils.py`, `BotModules/WrpWorkerProcess.py`, `bot_ek0x45.py` call sites.

## The two modes (shared machinery, different gates)

- **Losing all-in** (`is_stealth_all_in_active`, requires `is_all_in_losing`): plan a hidden
  flank → gather army to a launch tile → WRP-sweep general candidates. Relaxed kill criteria
  apply (predicted general stack, not full fog defense) — we're betting on a misplay.
- **Opportunistic hunt** (`is_undefendable_hunt`): strict safety only; a single WRP commit
  when projected reveal army beats fog defense. Abort excludes launch+head from future hunts.
  A route whose only unsafe reveals sit at the tail commits a **truncated safe front**
  (`STEALTH_ALLIN_SAFE_FRONT`), same as the losing path — but only when the front still
  covers a majority of the candidate reveals AND its deepest safe reveal retains
  `remaining_army > approximate_fog_army_available_total` (a front that ends too weak to
  kill the general it might find is a mostly-failed search, not a hunt).

## Pipeline (losing all-in)

1. `get_stealth_all_in_move` (called from `bot_ek0x45` move loop when `committed_route` is None):
   - **Dive-check first**: `_get_forward_dive_stack` finds a non-general stack already able to
     kill under the relaxed criterion (`army > approximate_fog_army_available_total` AND the
     relaxed single-candidate eval passes). `STEALTH_ALLIN_DIVE_REBASE` re-roots
     launch/entry/flank onto that stack — the gather then converges reserves ONTO the diver
     instead of dragging it back to a stale launch tile. **This was the t291 fix**: a 115-army
     stack 6 tiles past `launch=9,3` was being walked home for 6 turns because
     `gather_approximate_turns_to_tiles(rootTiles=[launch_tile])` counts it as gatherable.
   - Otherwise `find_stealth_flank_path` → gather phase → `launch_turn` gate → `start_wrp_job`.
   - `head_ready_now` early-commit when the real head army already passes route safety;
     a head that can't survive the committed segment is never committed
     (`reason=head_too_weak`, does NOT tick the desperation counter — only projected-eval
     `cannot_kill` failures drive desperation).
   - `consecutiveFails >= desperation threshold` → `is_desperation_dive` commit anyway.
2. `start_wrp_job` → `WrpWorkerProcess` — **WRP must run in a separate process**
   (`background_process=True`, ~1-3s timeLimit) so route search can't eat live move-selection
   time. Never move it back onto the move thread. Payloads pickle the map — worker code must
   stay robust; once live, any crash in normal games is a real failure.
3. Commit (`STEALTH_ALLIN_COMMIT`): `state.committed_route = route` +
   `committed_route_army_snapshot` baseline + `committed_turn`. `_evaluate_route_safety`
   truncates to a safe front before the first unsafe candidate reveal (`is_truncated_front`,
   `STEALTH_ALLIN_SAFE_FRONT`); completion triggers `STEALTH_ALLIN_FRONT_REBASE` which replans
   from the frontier head — this is how route-chaining works.
4. Execute (`get_committed_route_move`, called from `bot_ek0x45:1203` & `:1683` every turn
   while a route is committed): pops one `Path` step per turn via `get_first_move()` +
   `remove_start()`. Terminal conditions only: `general_known` (with a same-dest capturable
   handoff to direct attack), `route_complete`, `broken_head`, `broken_next_move`,
   `army_wall`, plus the lethal-defense interrupt (Kill threat on our general, possibly
   `last_stealth_route_defense_interrupt`).

## Key invariants & failure modes

- **Committed replay is blind** — it does NOT re-evaluate safety mid-route. The `army_wall`
  check exists because vision reveals enemy stacks 1-2 tiles ahead that weren't priced at
  commit (QvmmDx_Q2 t300: `(20,12)` revealed `b57` one step before the route stepped on it).
  Wall check: discovered, non-team, `army >= max(12, head//4)`, and `army - baseline >= 8`
  where baseline = `committed_route_army_snapshot` at commit. The snapshot is what makes it
  loop-safe: a replanned route that still prices through the wall re-baselines it, so a wall
  forces at most one replan.
- **Walls get a vantage-preserving detour, not an abort**: when a wall is found, the route is
  spliced in place — `head + un-walked prefix + BFS detour + route tail` — so the committed
  direction keeps executing instead of releasing the stack to arbitrary pipeline fallbacks
  (a released stack once got dragged the opposite way by `Delayed defense kingKillPath` for
  6 turns — the down→up flip-flop). `_find_wall_detour` first tries to flank to a tile
  orthogonally adjacent to the wall (preferring the one that can still see the most of the
  wall's undiscovered `tile.adjacents`) because the wall step usually exists FOR its reveal
  vantage (the `20,12` peek sighted `21,13`); then rejoins the route. Rejoin targets equal
  to the detour start are skipped (tours revisit tiles after peeks). Only if no short detour
  exists does it `army_wall`-abort for a full replan.
- **`bot._map.teammates` excludes self** — use `bot._map.is_tile_on_team_with(tile,
  bot.general.player)` for "is this ours" checks or your own stacks get flagged as enemies.
- **Delayed-defense `kingKillPath` must not seize the dive stack** — the `DELAYED_DEF_KK_GATE`
  in `bot_ek0x45` (~line 1608) suppresses that fallback ONLY when `kingKillPath.start.tile`
  is the tile stealth owns: committed route head, gather `launch_tile`, or pre-state when it
  passes `_get_forward_dive_stack`'s eligibility filter (`army > predicted_general_army`,
  non-general) while an episode is in scope (`flag + target + unknown-gen + not-ffa-nondom +
  (losing OR not advantage)`). The tile check matters: during timed all-ins the same fallback
  is the legitimate race move on OTHER stacks (keep_timed_all_in regressed when suppressed
  unconditionally). The `(losing or not advantage)` scope covers `determine_should_winning_all_in`'s
  hysteresis flicker — advantage=True for one turn released the stack to the QK tour at t291,
  then stealth dive-rebased and committed an up-first route = down->up->down.
- **WRP objective** (`PivotIterativeWRP.solve`): weighted A* (`w` 3.0→1.0) over tiles where
  `cost_so_far` = turn count (drives `lenThreshs` prune schedule and stays the index) and
  `combat_cost` = enemy/neutral `tile.army` walked, folded into `total_estimated_cost` and
  best-path selection (`bestCost = turns + combat`). The turn-based heuristic stays
  admissible (mixed cost >= turns). Nodes dedup on `(tile_index, tuple(unseen))`.
- **Vision vs `tile.adjacents`**: real game vision is 3x3 — capturing `(20,12)` reveals
  diagonal `(21,13)` — but WRP reveal bookkeeping uses `neighbor.adjacents`; a route may only
  need an adjacent tile to clear a candidate, which is why approach detours can be cheap.
- **Predicted cities are WRP walls**: `_is_uncertain_city_wall` = `isCity and not discovered`
  (covers opponent-tracker predicted cities that lack `isTempFogPrediction`), except
  walled/low-cost city games.
- **`_abort_committed_route` nukes the whole state** (`bot.stealth_all_in = None`, resets
  `cannot_kill_counter`, hunt-abort excludes tiles). Aborting is cheap for losing all-ins —
  the dive-check re-fires next turn and recommits, often same-turn when WRP runs sync.
- **Route cost model for PLAN choice** (stealth vs direct): `cost = route_len + 3 *
  warning_turns` — each enemy-visible "surprise" turn is worth ~3 turns of longer route
  (user's rule).

## Serialization contract

`StealthAllInState` is dataclass(slots) — committed routes persist into txtmaps via
`BotRendering.py`'s `bot_stealth_*` block and restore in
`load_committed_route_from_resume_data`. **Any new field needed across a mid-route resume
must be written AND parsed** (`resume_data.get(key, fallback)` for old fixtures) or resume
tests silently lose it — `committed_route_army_snapshot` is the example
(`idx:army,idx:army`).

## Useful Path API

`Path.tiles` (remaining queue incl. head), `Path.tileList`, `get_first_move()` (Move
source=head→next), `remove_start()` (pops head each executed step), `length`, `start.tile`,
`str(path)` = remaining-route string used for serialization.

## Log tags for debugging

`STEALTH_ALLIN_{VISION,PLAN,GATHER,WAIT,DESPERATE,WRP_START,WRP_DONE,SAFE_FRONT,COMMIT,
ROUTE_MOVE,ABORT,ARMY_WALL,WALL_DETOUR,DIVE_REBASE,FRONT_REBASE,DEFENSE_INTERRUPT,GENERAL_KNOWN_HANDOFF,
RESUME}` — all `KEY=value` formatted; grep test output for them (see
`unittest-regression-workflow`).
