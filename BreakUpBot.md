---
description: Plan for safely breaking bot_ek0x45.py into multiple files without moving bot state off EklipZBot
---

# BreakUpBot Plan

## Goals

- Preserve behavior and performance.
- Preserve the existing outer bot object as the single owner of all god-fields.
- Avoid breaking tests, renderer integrations, debug tooling, and any code that directly reads bot properties.
- Move logic only, not data containers.
- Make the migration incremental and reversible until final swap.

## Non-Negotiable Constraints

- `EklipZBot` remains the canonical state container.
- All existing bot fields stay on the outer bot object.
- New extracted classes are thin logic containers that receive `bot: EklipZBot` and operate on `bot.<field>`.
- Do not change algorithm order, timing boundaries, caching behavior, or log ordering unless required by import wiring.
- Prefer moving groups of related methods together to avoid cross-file churn.
- Avoid introducing wrapper layers in hot paths unless they are one-hop pass-throughs.

## Migration Steps

### Step 1

Decide the target file/module layout and write down the architecture for how extracted logic will still use the outer bot state safely.

### Step 2

Annotate every function in `bot_ek0x45.py` with a comment above it describing:

- the destination file/module
- whether it stays on `EklipZBot` or moves into a helper/controller class
- the migration strategy for that function

During this step:

- keep the original file intact
- do not delete moved logic yet
- this file becomes the migration map for Step 3

### Step 3

Create the new files and a new `EklipZBotV2.py`.

Rules for Step 3:

- implement the new helper/controller classes first
- wire `EklipZBotV2` to instantiate them lazily or in `__init__`
- copy/move functions according to the Step 2 comments
- each time a function has been migrated, mark the comment in `bot_ek0x45.py` as completed by prefixing it with `--`
- preserve method names where practical so searchability remains high
- keep any compatibility pass-throughs on `EklipZBotV2` only where needed for call-site stability

### Step 4

Swap the original bot implementation to the new one after the migration is complete and validated.

Swap requirements:

- preserve import expectations for existing callers
- preserve public surface area relied on by tests and runtime integration
- keep the original file available for bug-reference until the swap is complete

## Step 1 Architecture

## Core approach

Use a **stateful shell + extracted logic controllers** design.

### State owner

- `EklipZBot` / later `EklipZBotV2`
- owns all current fields
- remains the object tests and other systems interact with
- still exposes the high-level entrypoints

### Extracted logic units

Each extracted file defines a small class with the shape:

```python
class SomeBotModule:
    def __init__(self, bot: "EklipZBot"):
        self.bot = bot
```

These classes:

- never own durable game state that should live independently of the bot
- read/write state only through `self.bot.<field>`
- may hold tiny immutable helpers or cached callables, but not authoritative state
- are organizational boundaries, not new sources of truth

### Call pattern

`EklipZBotV2` will delegate:

```python
return self.city_ops.capture_cities(...)
```

inside extracted classes, all previous `self.foo` references become `self.bot.foo` unless the function remains on the bot.

This preserves:

- property access patterns
- renderer/test expectations
- caches/history/timers
- object identity of stateful collaborators already stored on the bot

## Proposed target files

This is the recommended first-pass breakup. It is organized by cohesion and call density, while minimizing risky cycles.

### `EklipZBotV2.py`

Primary shell / orchestration file.

Keep here:

- `EklipZBotV2.__init__`
- top-level move entrypoints like `find_move`, `select_move`, `init_turn`
- helper/module construction
- extremely small compatibility methods and object lifecycle wiring
- high-level coordination that intentionally spans multiple domains

Why:

- this remains the stable public bot surface
- it minimizes external breakage
- it keeps the god-object fields where tests already expect them

### `BotModules/BotEventHandlers.py`

Event-driven map update handlers.

Move here:

- `handle_city_found`
- `handle_tile_captures`
- `handle_player_captures`
- `handle_tile_deltas`
- `handle_tile_discovered`
- `handle_tile_vision_change`
- `handle_army_moved`
- any event-only update helpers tightly coupled to these

Why:

- these are cohesive side-effect handlers
- they mostly mutate bot-owned trackers/classifiers and are naturally grouped

### `BotModules/BotTimings.py`

Timing and cycle policy.

Move here:

- `is_player_aggressive`
- `get_timings_old`
- `get_timings`
- cycle/timing calculators
- small helpers used only for timing selection

Why:

- timing logic is cohesive and mostly policy-oriented
- this is a good isolated area for early extraction

### `BotModules/BotGatherOps.py`

Generic gather planning and gather execution helpers.

Move here:

- `timing_gather`
- `get_gather_to_target_tile`
- `get_defensive_gather_to_target_tiles`
- `get_gather_to_target_tiles`
- `get_gather_to_target_tiles_greedy`
- gather tree conversion / selection helpers
- MST/gather plan construction helpers
- prune-and-select helpers used primarily by gather routines

Why:

- this is one of the largest cohesive algorithm clusters
- it has strong internal reuse
- it is hot-path code, so it should remain as direct method calls on one helper object

### `BotModules/BotExpansionOps.py`

Expansion planning and early-game growth logic.

Move here:

- `make_first_25_move`
- optimal city/general plan selection for early turns
- exploration/expansion path search helpers
- quick expand / greedy expand / iterative expansion glue
- city expansion plan helpers

Why:

- expansion logic is a clear domain
- it is already conceptually distinct from combat and city-capture logic

### `BotModules/BotCityOps.py`

Neutral/enemy city capture, city prioritization, and city-specific attack planning.

Move here:

- `should_proactively_take_cities`
- `capture_cities`
- `find_neutral_city_path`
- `find_enemy_city_path`
- `should_allow_neutral_city_capture`
- `plan_city_capture`
- rapid-city capture helpers
- fog neutral city hunt helpers
- city contestation helpers

Why:

- these methods heavily share city-specific state and reasoning
- they represent a clear sub-engine inside the bot

### `BotModules/BotCombatOps.py`

Combat decisions, kill attempts, tactical races, and attack/defense tactical logic.

Move here:

- `should_kill`
- `should_kill_path_move_half`
- `kill_threat`
- `check_for_king_kills_and_races`
- tactical kill path evaluators
- combat interception glue not already encapsulated by other analyzers
- launch/attack selection helpers

Why:

- combat logic is broad but cohesive
- this reduces noise in the main bot shell substantially

### `BotModules/BotTargeting.py`

Enemy targeting, general approximation, and pursuit pathing.

Move here:

- target-player selection helpers
- enemy general approximation helpers
- undiscovered search / spawn approximation helpers
- `find_hacky_path_to_find_target_player_spawn_approx`
- target gather path selection helpers

Why:

- this logic has its own data flow and usually feeds other modules
- it is conceptually separate from city ops and general combat execution

### `BotModules/BotDefense.py`

Threat response, defensive posture, and out-of-play evaluation.

Move here:

- `check_army_out_of_play_ratio`
- defense spanning-tree helpers
- general defense move selection helpers
- economy-defense gating helpers
- threat-path defensive response helpers

Why:

- defense logic is a major behavior domain with shared heuristics and state flags

### `BotModules/BotPathingUtils.py`

Bot-specific path scoring / path cleanup / path utility methods.

Move here:

- `clean_up_path_before_evaluating`
- `get_undiscovered_count_on_path`
- `get_enemy_count_on_path`
- `is_path_moving_mostly_away`
- path conversion helpers like gather-to-move-list conversion
- path utility routines that are bot-specific rather than generic library utilities

Why:

- these are support methods used across modules
- extracting them prevents duplication in city/combat/expansion modules

### `BotModules/BotRepetition.py`

Move repetition and dropped-move handling.

Move here:

- `detect_repetition_at_all`
- `detect_repetition`
- `detect_repetition_tile`
- `move_half_on_repetition`
- `droppedMove`

Why:

- small but cleanly isolated concern
- low-risk first extraction candidate

### `BotModules/BotRendering.py`

ViewInfo/debug rendering helpers.

Move here:

- render/prep helpers
- debug overlays
- city score render helpers
- targeted tile/path coloring helpers that are presentation-only

Why:

- this is noisy and mostly orthogonal to decision logic
- isolating it helps the shell stay readable without affecting gameplay behavior

### `BotModules/BotComms.py`

Teammate/all-chat/ping logic.

Move here:

- outbound/inbound communication helpers
- teammate ping handling
- communication cooldown helpers
- bot-team coordination methods

Why:

- communication is its own concern and should be easy to reason about in isolation

### `BotModules/BotEngineInterop.py`

Army engine / MCTS integration.

Move here:

- scrim helpers
- engine move generation helpers
- MCTS orchestration helpers
- cached scrim management helpers

Why:

- engine code is domain-specific and optional/config-driven
- isolating it avoids infecting the main bot shell with simulation detail

### `BotModules/BotStateQueries.py`

Small cross-domain boolean/int/path query helpers.

Move here only if needed later:

- `is_all_in`
- lightweight getters / derived-state checks
- tiny convenience methods used everywhere

Why:

- do this late, not early
- these tiny helpers are sometimes better left on the shell until the bigger migrations stabilize

## Recommended extraction order

To minimize risk, move files in this order:

1. `BotRepetition.py`
2. `BotEventHandlers.py`
3. `BotPathingUtils.py`
4. `BotTimings.py`
5. `BotComms.py`
6. `BotRendering.py`
7. `BotCityOps.py`
8. `BotDefense.py`
9. `BotTargeting.py`
10. `BotCombatOps.py`
11. `BotExpansionOps.py`
12. `BotGatherOps.py`
13. `BotEngineInterop.py`
14. final cleanup into `EklipZBotV2.py`

Rationale:

- start with low-risk, highly cohesive modules
- delay `Gather` / `Expansion` / `Combat` because they have the heaviest call density and the greatest chance of subtle behavior drift

## Wiring pattern for `EklipZBotV2`

Suggested instance fields:

```python
self.repetition = BotRepetition(self)
self.events = BotEventHandlers(self)
self.pathing = BotPathingUtils(self)
self.timings_logic = BotTimings(self)
self.comms = BotComms(self)
self.rendering = BotRendering(self)
self.city_ops = BotCityOps(self)
self.defense = BotDefense(self)
self.targeting = BotTargeting(self)
self.combat = BotCombatOps(self)
self.expansion = BotExpansionOps(self)
self.gather_ops = BotGatherOps(self)
self.engine_interop = BotEngineInterop(self)
```

High-level bot methods remain thin delegators where needed.

## Safety rules for the actual split

- Do not move field initialization off the bot.
- Do not rename fields.
- Do not collapse or refactor unrelated helper methods during migration.
- Keep hot-path helper calls shallow: `self.gather_ops.method(...)` is fine; avoid multi-hop delegation chains.
- Keep logs and perf timer scopes in the same logical places.
- Keep existing analyzers/trackers (`dangerAnalyzer`, `cityAnalyzer`, `gatherAnalyzer`, `win_condition_analyzer`, etc.) on the bot.
- If a moved method is called heavily from many bot methods, prefer leaving a thin method on the bot during the migration window.

## Architecture snippet

```python
class EklipZBotV2:
    def __init__(self):
        # all existing bot fields remain here
        ...
        self.city_ops = BotCityOps(self)
        self.gather_ops = BotGatherOps(self)
        self.combat = BotCombatOps(self)

    def capture_cities(self, negativeTiles, forceNeutralCapture=False):
        return self.city_ops.capture_cities(negativeTiles, forceNeutralCapture)


class BotCityOps:
    def __init__(self, bot: "EklipZBotV2"):
        self.bot = bot

    def capture_cities(self, negativeTiles, forceNeutralCapture=False):
        bot = self.bot
        # existing logic copied with self.bot.<field> access
        ...
```

## Step 1 done

This file defines the target architecture and the migration order. The next step is to annotate every function in `bot_ek0x45.py` with its destination and migration strategy.
