# OffenseAnalyzer: First-Pass Data Aggregation Plan

## Scope

Implement only the data-collection layer that future offensive-option generation will consume. This pass will not choose moves, produce `OffensiveThreatOptionInfo` instances, score threats, or change existing expansion/defense decisions.

The entry point remains `OffenseAnalyzer.get_offense_options(bot, turns_left_in_cycle)`. Before it returns its current empty list, it will rebuild the per-analysis data below for the selected enemy player. The first implementation targets `bot.targetPlayer`; all collected data must be reset at the start of every call so stale fog, city, and army information cannot survive into a later turn.

## Existing Sources and Reuse Targets

- Use `ArmyTracker.emergenceLocationMap[player]` as the authoritative per-player emergence-value matrix.
- Use `OpponentTracker.get_last_attacked_from_locations(player, lastNRounds)` for the current and historical unresolved-emergence locations. This already returns the current largest unresolved emergence followed by prior cycle-end values.
- Use `ArmyTracker.armies.values()` for concrete tracked armies, including armies that are currently fogged.
- Use `BoardAnalyzer.intergeneral_analysis.aMap` for the current distance-to-our-general comparison.
- Use `bot.targetPlayerExpectedGeneralLocation` as the current predicted general pivot for `bot.targetPlayer`.
- Use the cached `map.distance_mapper.get_tile_dist_matrix(tile)` only for simple static distance maps.
- Adapt the spread-selection shape from `BotTargeting._get_furthest_apart_3_enemy_general_locations`, which builds and extends a multi-source distance map.
- Implement the friendly-army routing search with the same movement/army accounting semantics as the existing dynamic max-per-distance searches in `SearchUtils`, but return matrices rather than `Path` objects.

## New Data Types

Add the following slotted dataclasses in `Behavior/OffenseAnalyzer.py`.

### `AnticipatedFogDistanceData`

```text
anticipated_army_value: float
distance_matrix: MapMatrixInterface[int]
```

- The owning dictionary key is the anticipated fog-army source `Tile`.
- `anticipated_army_value` starts from the selected tile's emergence value. It represents the first-pass fog-army potential allocated to that selected source, not a claim that a concrete army is known there.
- `distance_matrix` is the normal obstacle-aware static distance matrix from the source tile.

### `PivotDistanceData`

```text
distance_matrix: MapMatrixInterface[int]
army_needed_to_maintain_threat: MapMatrixInterface[float]
```

- The owning dictionary key is the target pivot `Tile` (an enemy city or predicted enemy general).
- `distance_matrix` is the static obstacle-aware distance from that pivot.
- `army_needed_to_maintain_threat[t]` is the army that must be available at `t` to reach the pivot and still create an effective threat there, as determined by the reverse target-outward dynamic search in B3. It includes the expected army on the pivot tile itself, intervening ownership/army effects, and turn-based city/general production.

### `FriendlyArmyDistData`

```text
distance_matrix: MapMatrixInterface[int]
enemy_capture_count_matrix: MapMatrixInterface[int]
army_remaining_matrix: MapMatrixInterface[int]
```

- The owning dictionary key is the friendly large-army source `Tile`.
- Every matrix has one value per reachable tile, all taken from the same lexicographically best settled search state for that destination.
- `distance_matrix[t]` is the route length from the source to `t`.
- `enemy_capture_count_matrix[t]` is the count of enemy-owned tiles captured on that selected route.
- `army_remaining_matrix[t]` is the moving army remaining after entering `t` and leaving one army behind on every move.

## New `OffenseAnalyzer` Fields

Add these fields to `OffenseAnalyzer.__slots__` and initialize/reset them per analysis:

```text
anticipated_fog_armies: dict[Tile, AnticipatedFogDistanceData]
all_en_armies_distance_matrix: MapMatrixInterface[int]
pivot_distances_by_tile_map: dict[Tile, PivotDistanceData]
all_pivots_distance_matrix: MapMatrixInterface[int]
friendly_army_dist_data: dict[Tile, FriendlyArmyDistData]
```

Use `UNREACHABLE` / `1000` as the initial value for aggregate distance matrices so direct raw-array minimization remains fast and unambiguous.

## A. Anticipated Enemy Fog-Armies

### A1. Build the candidate fog-location set

For `bot.targetPlayer`, inspect the emergence matrix and retain only candidate tiles that satisfy all of the following:

1. The tile is in fog (`not tile.discovered`).
2. The tile is a plausible tile for that player/team using the same player-team predicate currently used by `BotTargeting.get_target_player_possible_general_location_tiles_sorted`.
3. The tile is pathable; do not choose a mountain or another non-traversable tile as a fog-army source.
4. The tile lies in the chosen board play-area matrix. The intended first-pass default is `board_analysis.extended_play_area_matrix`, because it is the existing broad "in play" region; retain this behind a helper/constant so the precise play-area policy can later change without rewriting selection.
5. The tile has a positive emergence value from `army_tracker.emergenceLocationMap[target_player]`.

Feed the candidate scoring with both sources requested for fog-location confidence:

- The raw `emergenceLocationMap` values, which incorporate prior unresolved emergence evidence.
- Current and recent locations from `opponent_tracker.get_last_attacked_from_locations(target_player, lastNRounds=...)`. These are explicit historical emergence points and must remain available as priority/debug inputs even when the map's current top values have moved or decayed.

The implementation should log the selected candidates and their emergence scores when `log_debug` is enabled. It must not use `print`.

### A2. Select up to three close-but-spread fog sources

Choose up to three purple source tiles from the high-emergence eligible candidates.

1. Rank candidate quality primarily by descending emergence score.
2. Use distance to the friendly side (`SearchUtils.build_distance_map_matrix(map, friendly-team tiles)` or the equivalent existing friendly distance source) as the closeness metric.
3. Select the first candidate as the closest-to-us qualifying high-emergence tile.
4. For each subsequent source, require it to be separated from every already selected fog source using the same iterative distance-map expansion idea used for the early-game three-furthest-general helper. Among candidates that remain sufficiently separated, prefer the one closest to us; use emergence score and `tile_index` as deterministic tie-breakers.
5. Do not manufacture a third point if fewer than three eligible, adequately separated candidates exist.

This intentionally differs from `_get_furthest_apart_3_enemy_general_locations`: that helper repeatedly maximizes distance from the friendly side and prior selections, while this selection keeps the same anti-clustering mechanism but minimizes friendly distance after the required separation filter.

For each selected tile:

- Call `bot.viewInfo.add_targeted_tile(tile, TargetStyle.PURPLE, radiusReduction=-8)`.
- Add `anticipated_fog_armies[tile] = AnticipatedFogDistanceData(...)`.
- Initialize `anticipated_army_value` from the source tile's emergence value.
- Build `distance_matrix` with `map.distance_mapper.get_tile_dist_matrix(tile)`.

### A3. Incorporate concrete enemy army sources and reduce duplicated fog potential

Build the concrete enemy-army source set alongside the selected purple locations:

1. Include every visible enemy general location that currently contains a visible enemy army. This covers known general-held armies rather than treating every enemy general as fog.
2. From `army_tracker.armies.values()`, filter to armies owned by the target player/team and sort descending by army value, then stable by `tile_index`.
3. Keep the three largest tracked enemy armies whether currently visible or fogged.
4. Add all retained concrete-army tiles to the aggregate enemy-distance source list.

For each retained tracked army that is currently in fog:

1. Find any selected purple fog source that is "near" the tracked army according to the chosen fog-army association distance.
2. Subtract that tracked army's value from the matching source's `anticipated_army_value`.
3. Clamp the value at zero so concrete tracked fog armies cannot make an anticipated value negative.
4. If multiple selected sources qualify, apply a deterministic nearest-source rule, then `tile_index` tie-break. Do not subtract the same concrete army from multiple anticipated sources.

This subtraction only prevents the purple emergence potential from double-counting an already tracked fog army. It does not remove the concrete army as a source from the global enemy-distance aggregate.

### A4. Aggregate all enemy-army distances

Create `all_en_armies_distance_matrix` as the tile-wise minimum of static distance matrices from the union of:

- Every selected anticipated purple fog source.
- Every included visible enemy-general army location.
- Every retained top-three concrete `ArmyTracker` enemy army location.

For each pathable tile, the aggregate value is the shortest distance to any included anticipated or concrete enemy army source. If no source exists, leave the matrix at `UNREACHABLE`.

## B. Offensive Pivot Distance Maps

### B1. Determine eligible enemy-city pivots

Iterate all cities for the target enemy player, including visible and fog-predicted city locations.

For an actual/visible city, always include the city as a pivot.

For a temporary fog-predicted city (`city.isTempFogPrediction`), include it only if at least one movable adjacent tile has an emergence value strictly above the target player's average emergence value. The comparison uses the same `army_tracker.emergenceLocationMap[target_player]` data used in section A.

Calculate the average once per analysis over the same eligible, non-obstacle fog-domain used for anticipated fog selection. This prevents inaccessible board regions from diluting the threshold. If that domain is empty, do not include a temporary predicted city solely because an average cannot be calculated.

### B2. Include the predicted general pivot

Always add `bot.targetPlayerExpectedGeneralLocation` as the current predicted general pivot when it is non-null and pathable. If it is the same tile as an included city, deduplicate it by dictionary key rather than computing the same matrix twice.

### B3. Build reverse pivot threat data and aggregate pivot distances

For every included pivot tile, create and store:

```text
pivot_distances_by_tile_map[pivot_tile] = PivotDistanceData(
    distance_matrix=...,
    army_needed_to_maintain_threat=...,
)
```

Build `distance_matrix` with `map.distance_mapper.get_tile_dist_matrix(pivot_tile)` and fold its raw values into `all_pivots_distance_matrix` with a tile-wise minimum.

Build `army_needed_to_maintain_threat` with a dedicated **reverse, target-outward priority-queue search** beginning at that city/general pivot. This search must not invent an alternate army model. It must heavily reference and preserve the standard army/turn accounting in the existing `SearchUtils` dynamic breadth-first-per-distance path searches (especially the `breadth_first_dynamic_max_per_tile_per_distance` family and its priority-state conventions); the only product difference is that this helper settles matrix entries instead of reconstructing `Path` objects.

The reverse state must include the current tile, distance from the pivot, and the army required at that current tile to travel back to the pivot while maintaining a real threat. Initialize the requirement with the expected army on the target pivot tile itself. As the search expands outward:

- When crossing a target-player-owned tile, increase required army by that encountered target-player tile army, preserving the normal project leave-one / capture-cost semantics used by the comparable dynamic searches.
- When crossing a tile not owned by the target player's team, reduce the requirement by that tile's available army contribution, again using the existing dynamic-search same-team versus opposing-team formulas rather than a hand-rolled approximation.
- Apply city/general production in the reverse threat requirement: every two moves away from the target increases the needed target army by one additional army. This increment is in addition to the tile-army additions/subtractions above.
- Preserve the existing dynamic-search handling of cities, generals, swamps, fog-predicted obstacles, pathability, teammate ownership, and unaffordable transitions. Do not simplify these rules for this matrix writer.

At each settled tile, write the resulting army requirement to `army_needed_to_maintain_threat[tile]`. The matrix therefore answers: "if we begin at this location, how much army do we need to reach this enemy city/general on time and still maintain an effective threat?"

The result is a static aggregate distance matrix plus per-pivot reverse threat requirements. If no pivot is available, keep `all_pivots_distance_matrix` at `UNREACHABLE` and skip section C safely.

## C. Friendly Large-Armies Near Enemy Pivots

### C1. Select friendly large-army sources

Use the existing `board_analysis.largest_player_tiles` as the first-pass definition of "our large armies" so the new analyzer follows the board analysis's current large-army policy instead of creating a conflicting threshold.

For each candidate source tile, retain it only when:

```text
all_pivots_distance_matrix[source] < board_analysis.intergeneral_analysis.aMap[source]
```

This exact strict comparison implements the requested "closer to threatening an enemy pivot than to our own general" rule. If `intergeneral_analysis` or no pivot matrix is available, produce no friendly routing data rather than substitute a different distance definition.

### C2. Perform one priority-queue route search per retained army

Do not use the simple cached distance matrix for these sources. Add a dedicated private helper that runs a real `heapq` search for one source tile and returns `FriendlyArmyDistData`.

The search state must carry:

```text
current_tile: Tile
distance: int
enemy_tiles_captured: int
army_remaining: int
parent_tile: Tile | None
```

Initialize the moving army from the actual movable amount at the source (the source tile army after preserving one unit). Follow the same capture routing / army accounting used by the existing dynamic max-per-distance functionality:

- Moving through a friendly tile adds its available army while leaving one unit behind.
- Moving into an enemy or neutral target spends the defending army plus the one unit left behind.
- Increment `enemy_tiles_captured` only when entering an enemy-owned tile.
- Do not traverse mountains or other non-pathable tiles.
- Do not continue a route whose moving army can no longer legally make the next move.
- Preserve the existing project treatment of cities, fog-predicted obstacles, and teammate ownership when translating the accounting from the existing max-per-distance routing behavior.

The min-heap priority must be lexicographic:

```text
(distance, -enemy_tiles_captured, -army_remaining, tile_index)
```

This means shorter routes always win. At equal route length, routes capturing more enemy tiles win; at equal captures, routes retaining more army win. `tile_index` makes equal states deterministic.

When the first best state for a destination tile is settled, write its three values to the corresponding matrices. A destination must not be overwritten by a longer route, or by an equal-distance route with fewer captures or less remaining army.

Run this search independently for each friendly source. Do not share a global visited set or parent map between sources, because each source needs a complete independent matrix result.

### C3. Store the routing results

For every retained friendly source tile:

```text
friendly_army_dist_data[source_tile] = FriendlyArmyDistData(
    distance_matrix=...,
    enemy_capture_count_matrix=...,
    army_remaining_matrix=...,
)
```

The data stores only the best routing state per destination in this first pass. It deliberately does not retain paths or construct offensive options yet.

## D. Collective Offensive Space Search

This phase consumes the aggregate data from A-C to build one shared movement-space map. It does not yet select an `OffensiveThreatOptionInfo`; it establishes which side can reach each tile first, what army remains there, what terrain/ownership was traversed, and the relevant army source for later threat generation.

### D1. Search seeds

Run one combined priority-queue search containing all relevant friendly and target-player army seeds at once:

- **Friendly seeds:** the friendly large-army source tiles retained in C1 and represented in `friendly_army_dist_data`.
- **Target-player seeds:** every concrete enemy source retained in A3 plus every selected anticipated fog-army source in `anticipated_fog_armies`.

Deduplicate seeds by tile. If a tile is represented by both a concrete tracked enemy army and an anticipated fog army, retain the concrete army value as the seed's army amount so the same army is not represented twice. A friendly seed always uses its current movable army; a tracked enemy seed uses its tracked `Army.value`; an anticipated fog seed uses `AnticipatedFogDistanceData.anticipated_army_value`.

Each starting state has distance zero and does not count its own seed tile as traversed. Its `original_team_id` is the source-side team id: the team of `map.player_index` for friendly seeds and the team of `targetPlayer` for enemy/anticipated-fog seeds. Derive team ids through the map's established team lookup rather than treating player indexes as teams.

### D2. State and priority

Create a slotted internal state type for the search. It contains at minimum:

```text
current_tile: Tile
original_team_id: int
source_tile: Tile
distance: int
army_remaining: float
neutral_tiles_captured: int
target_player_tiles_traversed: int
friendly_tiles_traversed: int
neutral_tiles_traversed: int
```

The state counters have these fixed meanings regardless of which side owns the source:

- `friendly_tiles_traversed` increments when the entered tile's player is `map.player_index`.
- `target_player_tiles_traversed` increments when the entered tile's player is `targetPlayer`.
- `neutral_tiles_traversed` increments when the entered tile's player is `-1`.
- `neutral_tiles_captured` records neutral captures independently. Under the first-pass normal movement model it increments when the state enters a neutral tile, so it initially tracks alongside neutral traversal; keep it separate because later offense scoring may distinguish a traversed neutral from a neutral that is actually capturable by the remaining army.

The heap is ordered with shortest `distance` first. Add deterministic tie fields after distance (such as source tile index and current tile index) only to make queue processing stable; they must not replace the required distance-first behavior or prevent equal-distance cross-owner handling.

For every neighbor, apply the standard army accounting using the **state's original/searching team**, not the tile's current owner:

- If the entered tile is on the same team as `original_team_id`, add `new_tile.army - 1` to `army_remaining`.
- If the entered tile is not on that team, subtract `new_tile.army + 1` from `army_remaining`.
- Do not enqueue a move that cannot legally be made with the resulting army.
- Do not traverse mountains or any other non-pathable tile.

This combined search must heavily reference and preserve the real army-value logic from the existing `SearchUtils` dynamic breadth-first-per-distance path searches, especially `breadth_first_dynamic_max_per_tile_per_distance` and its global-visited variant. It differs only in retaining settled matrix state instead of emitting reconstructed `Path` objects. The implementation must retain the same project rules for team ownership, leave-one behavior, capture cost, city/general increment behavior where applicable, swamps, fog-predicted obstacles, and unaffordable transitions; it must not introduce a simplified parallel army model.

This allows friendly and enemy states to use the same mechanical search while preserving each side's actual team relationship to every traversed tile.

### D3. Output matrices

Add these `OffenseAnalyzer` fields and reset them before every collective search:

```text
offensive_tile_team_matrix: MapMatrixInterface[int]
offensive_tile_army_source_matrix: MapMatrixInterface[int | None]
offensive_tile_army_value_matrix: MapMatrixInterface[float]
offensive_num_friendly_traversed_matrix: MapMatrixInterface[int]
offensive_num_target_traversed_matrix: MapMatrixInterface[int]
offensive_num_neutral_traversed_matrix: MapMatrixInterface[int]
```

Also maintain `offensive_tile_distance_matrix: MapMatrixInterface[int]` as the internal settled-distance record required by the visited/tie algorithm. It may be retained as an analyzer field for future consumers, but it is not a new requested scoring output.

When a state first settles a tile, write:

- `offensive_tile_team_matrix[tile] = state.original_team_id`.
- `offensive_tile_army_source_matrix[tile] = state.source_tile.tile_index`.
- `offensive_tile_army_value_matrix[tile] = state.army_remaining`.
- Each traversed-count matrix from its corresponding state counter.
- `offensive_tile_distance_matrix[tile] = state.distance`.

The result is a collective team-ownership/reachability map: tiles settled first by a target-team state identify the enemy army context; tiles settled first by a friendly-team state identify the friendly army context. Future offensive logic can use the source matrix to determine the specific enemy army that a candidate friendly movement is microing against.

### D4. Global visited and equal-distance collision rules

Use a global visited/settled set when popping entries from the priority queue, not when enqueueing them.

For a popped state whose tile was already settled:

1. If `state.distance > offensive_tile_distance_matrix[tile]`, discard it and continue. A later arrival cannot replace the earlier settled result.
2. Equal distance is the only other valid case because a smaller distance would have been popped first.
3. If the distance is equal and `state.original_team_id` differs from `offensive_tile_team_matrix[tile]`, the tile is equidistant from friendly-team and target-team movement. Set `offensive_tile_team_matrix[tile] = -1` and set `offensive_tile_army_source_matrix[tile] = None`.
4. Do not overwrite the first-settled army-value or traversal-count matrices during this tie step. They remain the deterministic first-arrival route data, while the team/source matrices explicitly mark that neither side owns first arrival.
5. If the distance is equal and the original team is the same, discard the duplicate state after preserving the previously settled values.

Once a tile has been marked `-1`, later equal-distance states must leave it tied; a third same-distance source must not restore a team owner or army source. The tile remains a no-first-arrival boundary between the two sides.

This behavior is intentionally different from the per-friendly-army independent routing in C: D is one global search so friendly and enemy fronts offset against each other without collision and reveal the boundary of credible offensive movement space.

### D5. Validation additions

Extend the planned `unittest` coverage with:

9. **Collective reach ownership:** a tile closer to a friendly seed stores the friendly team id and that source tile index; a tile closer to a target seed stores the target team id and its source tile index.
10. **Equal-distance boundary:** a tile reached at equal shortest distance from a friendly-team and target-team state has team `-1` and source `None`; later equal-distance states cannot restore ownership.
11. **Longer revisit:** a state popped after a shorter settled arrival leaves every recorded matrix unchanged.
12. **Army accounting:** same-team traversal adds `army - 1`; opposing-team traversal subtracts `army + 1`; unaffordable moves are not enqueued.
13. **Counters:** friendly, target-player, neutral-traversed, and neutral-captured counts are attributed by the entered tile's owner and are independent of the source side.
14. **Seed de-duplication:** a concrete tracked army supersedes a same-tile anticipated fog seed without producing duplicate initial states.

## E. Stage-One Actionable Interception Paths

This phase converts the aggregate matrices into initial offensive options. It produces paths that leave friendly-controlled collective space, maintain a credible threat to an enemy pivot, and terminate at the first plausible interception boundary.

### E1. Run an independent max-path-per-distance search for each friendly army

For each friendly source in `friendly_army_dist_data`, run a dedicated per-distance dynamic path search. Heavily reference the existing `SearchUtils.breadth_first_dynamic_max_per_tile_per_distance` family and its real gather/capture army accounting, parent/from-tile tracking, path reconstruction, city/general increments, swamp behavior, fog-predicted-obstacle behavior, team checks, and affordability pruning. This is a path-producing search, not a new simplified BFS.

The state/priority object must carry at least:

```text
current_tile: Tile
previous_tile: Tile | None
source_tile: Tile
distance_from_start: int
friendly_army_remaining: float
target_player_tiles_traversed: int
neutral_tiles_traversed: int
```

Use the relevant `PivotDistanceData.army_needed_to_maintain_threat` matrix or matrices for threat pruning. If more than one pivot remains viable at a tile, use the lowest requirement among pivots that the current state can still threaten; preserve the associated pivot tile for the eventual option. This min requirement is distinct from `all_pivots_distance_matrix` (the aggregate minimum-pivot-distance matrix), which is used only as the second priority term.

### E2. Priority and continuation rules

The priority tuple is lexicographic, in this exact order:

```text
(
    distance_from_start,
    all_pivots_distance_matrix[current_tile],
    -target_player_tiles_traversed,
    -friendly_army_remaining,
    deterministic_tie_breakers,
)
```

Therefore the search prefers, in order:

1. A shorter path from the friendly army.
2. A tile with a shorter distance to any enemy pivot in the aggregate minimum pivot-distance matrix.
3. A route that traversed more target-player tiles.
4. A route that retains more friendly army.

The priority transition must carry `previous_tile`, following the existing from-tile/to-tile conventions used by gather and capture searches. It must return `None` and refuse to enqueue a child when either condition holds:

1. `previous_tile` is non-null and its owner in `offensive_tile_team_matrix` is not the friendly team. The zero-distance source state is exempt because it has no previous tile. This permits a path to enter its interception endpoint but prevents it from continuing beyond the first collective non-friendly/boundary tile.
2. `friendly_army_remaining` is below the selected threat pivot's `army_needed_to_maintain_threat[current_tile]`. This ensures every produced path can still maintain an active threat on its pivot.

### E3. Value function and interception endpoint selection

The value function must return `None` for a `current_tile` whose owner in `offensive_tile_team_matrix` is the friendly team. Consequently, the search only emits paths at the first collective enemy-controlled or tied interception boundary, while the priority continuation rule prevents it from extending past that boundary.

For an emitted endpoint, select the tile used to measure the enemy army's forced self-damage:

1. If `offensive_tile_team_matrix[current_tile]` is the target team, use `current_tile` directly.
2. If `offensive_tile_team_matrix[current_tile] == -1`, inspect `current_tile.movable` and select the movable tile that:
   - Is owned by the target team in `offensive_tile_team_matrix`.
   - Has the lowest `all_en_armies_distance_matrix` value.
   - Uses `tile_index` as the deterministic tie-breaker.
3. If no target-team movable exists for a tied endpoint, return `None`; no concrete enemy army context exists for a stage-one option.

The selected enemy-context tile identifies the enemy frontier that would be forced to move. Its collective traversal counters quantify the opponent's forced self-damage:

```text
enemy_forced_damage = (
    2 * offensive_num_target_traversed_matrix[enemy_context_tile]
    + offensive_num_neutral_traversed_matrix[enemy_context_tile]
)
```

The friendly route's own pressure is:

```text
friendly_pressure = (
    2 * state.target_player_tiles_traversed
    + state.neutral_tiles_traversed
)
```

Set the emitted path's stage-one economic value to:

```text
stage_one_econ_value = enemy_forced_damage + friendly_pressure
```

Return the dynamic search value as the comparable tuple `(stage_one_econ_value, friendly_army_remaining)`. This makes the existing max-path-per-distance selection retain the higher-economic path at each distance and, when values tie, the path with greater endpoint army. Preserve the chosen target pivot and the selected enemy-context tile as metadata for later forced-army, interception, and threat refinements.

### E4. Initial option output

For every valid emitted per-distance path, construct a stage-one `OffensiveThreatOptionInfo` from the reconstructed path and selected pivot. Set its initial economic value from `stage_one_econ_value`, set `target_pivot_tile` to the viable pivot preserved by the priority state, and initialize the required not-yet-derived constructor fields to safe stage-one defaults: empty `forced_army_info_by_tile_index`, zero `damage_prevented`, `False` kill/city flags, zero `forcing_turns`, no split option, no double-back path, and zero delay. Retain the selected enemy-context tile and endpoint remaining army in dedicated stage-one metadata/data so later phases can calculate forced armies and interception probability without re-searching.

Leave later-stage interception probability, exact forced-army mapping, kill/city classification, split behavior, and double-back routing for subsequent planning phases. Return this set of stage-one options from `OffenseAnalyzer.get_offense_options`. Deduplicate equivalent options by source tile, endpoint tile, selected pivot, and path tile sequence; retain the higher economic value, then higher remaining friendly army, deterministically.

### E5. Validation additions

Extend `unittest` coverage with:

15. **Friendly-space rejection:** the value function emits no path whose endpoint is owned by the friendly team in `offensive_tile_team_matrix`.
16. **Interception stop:** a path may enter an enemy/tied endpoint, but the previous-tile team check prevents traversal beyond that first boundary.
17. **Priority order:** candidates are ordered by source distance, then aggregate pivot distance, then target-player tiles traversed, then friendly army remaining.
18. **Threat viability:** a state whose remaining army is below the applicable `army_needed_to_maintain_threat` value is pruned and cannot produce a path.
19. **Tied-endpoint enemy context:** a tied endpoint selects the target-team movable with lowest `all_en_armies_distance_matrix`; no eligible movable means no option.
20. **Stage-one value:** option value equals twice the forced enemy target-player traversal plus forced enemy neutral traversal, plus twice the friendly path target-player traversal plus friendly neutral traversal; equal values select greater remaining friendly army.

## Diagnostics and Validation Plan

### Diagnostics

- Wrap each major rebuild phase in `PerformanceTimer` events: anticipated fog armies, pivot distances, friendly army route data, the collective offensive space search, and stage-one interception-path generation.
- Under `log_debug`, log selected purple sources, emergence values, associated/subtracted fog armies, pivot inclusion/skips, selected friendly source armies, collective-search seed data, tie-boundary counts, viable interception paths, selected enemy-context tiles, path economic values, and search iteration/time totals.
- The only visual output in this pass is the requested purple `TargetStyle.PURPLE` marker with `radiusReduction=-8` on each selected fog source.

### Unit tests

Add focused `unittest` coverage before adding offensive decision logic:

1. **Fog selection:** only fog, player-plausible, positive-emergence, in-play-area tiles are eligible; no more than three are chosen; selected points respect separation; purple render calls use `TargetStyle.PURPLE` and `-8`.
2. **Fog army accounting:** retained top-three enemy tracked armies are deterministic; a nearby fogged army reduces exactly one anticipated source and never below zero; visible army locations remain global sources without subtraction.
3. **Enemy aggregate:** every cell in `all_en_armies_distance_matrix` equals the minimum distance across selected anticipated and concrete source matrices.
4. **Pivot filtering:** visible cities are retained; temporary fog cities require an adjacent above-average-emergence movable tile; the predicted general is included and deduplicated.
5. **Pivot aggregate:** every cell in `all_pivots_distance_matrix` equals the minimum of the `distance_matrix` values in stored `PivotDistanceData`.
6. **Reverse pivot threat requirement:** `army_needed_to_maintain_threat` includes the target tile's expected army, applies the same dynamic-search army accounting as the existing per-distance path searches, and increases the requirement by one for every two moves from the city/general pivot.
7. **Friendly source gate:** a large friendly tile is routed only when its pivot distance is strictly less than its `intergeneral_analysis.aMap` distance.
8. **Priority routing:** verify shortest-distance priority, then higher enemy capture count, then greater remaining army; verify all three stored matrices describe the same settled state.

Run tests with `unittest` using the repository's configured PowerShell environment and `bypass_ui=True` when required. Do not use `pytest`.

## Decisions Requiring Confirmation Before Runtime Implementation

1. **Play area:** this plan defaults "board analysis's play area" to `extended_play_area_matrix`; confirm whether you instead want `core_play_area_matrix` or another area.
2. **Spread separation:** choose the minimum path-distance required between selected purple fog sources.
3. **Fog association:** choose the maximum path-distance at which a tracked fog army is considered near enough to subtract from a purple source's anticipated value.
4. **Emergence-to-army semantics:** the plan initializes `anticipated_army_value` from the raw emergence score because no conversion formula was specified. Confirm whether it should instead use a different estimate of enemy fog army amount.
5. **Enemy scope:** this plan uses `bot.targetPlayer` consistently. Confirm whether the first pass should aggregate all non-friendly players in free-for-all games instead.
