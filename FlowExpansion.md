# Flow Expansion V2 Plan

## Goal
Implement a new `ArmyFlowExpanderV2` that eventually replaces `ArmyFlowExpander`, while preserving the public interface expected by `UnitTests/test_FlowExpansion.py` and related callers.

The V2 design should:

- Reuse only the specific existing pieces that are trustworthy.
- Not assume `IterativeExpansion.py` is bug free.
- Treat `flowplan prompt half.txt` as the primary design source, not `IterativeExpansion.py` behavior.
- Separate preprocessing from optimization so each stage can be unit tested independently.
- Preserve current output shape: `FlowExpansionPlanOptionCollection` containing `GatherCapturePlan` instances.

## Current Architecture Summary

### Existing stable-ish pieces worth reusing

- `NetworkXFlowDirectionFinder.build_graph_data(...)`
  - Builds the min-cost flow precursor graph and `NxFlowGraphData`.
- `NetworkXFlowDirectionFinder.compute_flow_dict(...)`
  - Produces the raw NetworkX flow dict.
- `NetworkXFlowDirectionFinder.build_flow_graph(...)`
  - Converts NetworkX output into `IslandMaxFlowGraph`, including:
    - root flow nodes
    - island lookup tables
    - neutral / no-neutral variants
- `FlowGraphModels`
  - `IslandFlowNode`
  - `IslandFlowEdge`
  - `IslandMaxFlowGraph`
  - `FlowGraphMethod`

### What "trustworthy" means here
For V2, "trustworthy" should be read narrowly.

Trusted for reuse:
- the existing max-flow node / graph building pipeline
- the existing conversion of NetworkX flow results into `IslandFlowNode` / `IslandMaxFlowGraph`
- the partial-island gather/capture accounting idea used to track what remains unconsumed as additional gather or target nodes are included

Not trusted as design authority:
- V1 border enumeration behavior
- V1 flow-plan search / queue heuristics
- V1 option enumeration semantics
- V1 complex-case output behavior

### Existing risky / mixed-responsibility area
`IterativeExpansion.find_flow_plans(...)` currently mixes:

- flow graph consumption
- heuristic search
- partial island walking
- visited-set dedupe
- economic scoring
- conversion into `GatherCapturePlan`

That makes it hard to reason about correctness and hard to test small parts in isolation.

For V2, the old implementation should be treated mostly as a source of:

- interface expectations
- some reusable flow-graph plumbing
- the partial-island gather / capture inclusion idea

It should not be treated as the target behavior for complex cases.

## Recommended V2 Shape

Create a new file:

- `BehaviorAlgorithms/FlowExpansion.py`

Primary class:

- `ArmyFlowExpanderV2`

Suggested internal responsibilities:

- **Graph acquisition**
  - Build / cache `IslandMaxFlowGraph` using the existing flow finder.
- **Step 1 preprocessing**
  - Convert each valid border stream into gather/capture lookup tables.
- **Step 2 pair enrichment**
  - Match capture entries to the minimum gather entry that can pay for them.
- **Step 3 plan selection**
  - Solve either:
    - simple grouped knapsack only, or
    - grouped knapsack + local post-optimization.
- **Plan materialization**
  - Convert chosen lookup entries into `GatherCapturePlan` objects.

## Core Design Clarifications

### 1. Border pair should be the unit of decomposition
A "stream" should be keyed by a concrete friendly-target border crossing, not just a target island.

Suggested key:
- `FlowBorderPairKey(friendly_island_id, target_island_id)`

Reason:
- This aligns with the prompt.
- It matches how current search is seeded.
- It gives clean grouping for multiple-choice knapsack.

Important exception:
- friendly islands marked as `target crossable` are not valid border-pair friendly endpoints.
- they may still appear inside target-side traversals as turn-cost-only crossing nodes.

### 2. Lookup tables should be indexed by turns, not army

The prompt should be read as turn-indexed only.

For implementation and testability, use **turn-indexed entries** as the authoritative representation.

Why:
- final optimization is turn-budget constrained
- tests assert `length`, not just total army
- partial-island walking naturally generates best entry for each reachable turn count
- required army should be monotone nondecreasing as turns increase, so a separate army-indexed lookup table provides no practical value

Each entry should still store army requirements as payload, but V2 should not build a separate by-army lookup table.

### 3. Gather and capture sides need explicit uniqueness semantics
Each individual max-flow output should produce unique streams with no ambiguity.

At the moment, planning is expected to operate on two separate flow graph outputs:
- one flow graph that includes neutral tiles
- one flow graph that is enemy-only

V2 should build a separate border-pair lookup-table set for each of those flow graph outputs.

Expected overlap behavior in the current plan:
- no overlap within a single flow graph’s stream decomposition
- the only expected duplication is between the neutral-inclusive and enemy-only flow graph outputs

Likely end state:
- we will probably consolidate primarily onto the neutral-inclusive flow graph path once validated

### 4. Step 1 should not depend on `IterativeExpansion` search correctness

We should only reuse the **partial tile walking ideas**, not the old queue/visited heuristics.

Meaning:

- Reuse the concept of incrementally consuming:
  - source-side gather tiles in best order
  - target-side capture tiles in cheapest / highest-value order
- Do not reuse the old search state machine as the authoritative algorithm.

### 5. Stream uniqueness across the current plan

Within a single max-flow output, streams are expected to be unique and non-overlapping.

Therefore:
- preprocessing for a given flow graph should not expect ambiguous stream ownership
- lookup tables for a given flow graph can assume unique stream decomposition
- any comparison or deduplication concern is primarily between:
  - the neutral-inclusive flow graph output
  - the enemy-only flow graph output

If later implementation disproves this assumption for a single flow graph output, the plan should be amended with a concrete counterexample.

### 6. Some friendly islands must be modeled as target-side crossing nodes
Friendly nodes are not always purely gather-side nodes.

Some friendly islands should be marked `target crossable`, meaning:
- they can be traversed on the capture side
- they provide no direct capture reward
- crossing them reduces required enemy-army burn because they are friendly-held
- but they still cost turns

These nodes should be treated as target-side routing / bridge nodes to reach more valuable downstream capture nodes.

#### `target crossable` detection rule

A friendly island should be marked `target crossable` when all of the following hold:

- it is a friendly island
- it is bordered by more enemy island tile counts than friendly island tile counts
- its parent island (`island.full_island`) contains less than `1/5` of the friendly team’s total tile count
- the max-flow graph/path results show pathing into the friendly island **from enemy islands**
  - regardless of whether that flow ultimately originates from enemy-general sink pressure or from friendly source tiles routed through the graph

#### Consequences of `target crossable`
- it must **not** be used as the friendly endpoint when seeding border-pair enumeration
- it may be included during target-side expansion / lookup generation as a zero-reward, turn-cost crossing node
- it should still remain visible to overlap accounting and provenance tracking
- it should not be credited as a captured target node or as direct econ gain

This behavior should be shared by both algorithms that iterate border pairs / borders so we do not naively seed bad border decompositions.

## Proposed Data Structures

### `FlowStreamIslandContribution`

Represents one stream contribution record used during preprocessing / ordering / reconstruction.

This is **not** intended to be the full A* node/state object.
It is lightweight metadata about one flow node's contribution to a stream.

Clarifications:

- `sort_score`
  - the heuristic ordering score used when ranking candidate next stream contributions during preprocessing
  - not necessarily persisted into final tight-loop table walking if a cheaper derived ordering can replace it
- `marginal_flow`
  - the incremental amount of useful flow capacity / throughput this contribution adds to the stream ordering calculation
  - intended as a stream-ordering feature, not as a separate semantic game value

Fields:

- `island_id: int`
- `is_friendly: bool`
- `flow_node: IslandFlowNode`
- `tile_count: int`
- `army_amount: int`
- `marginal_flow: int`
- `sort_score: float`
- `is_crossing: bool`
  - `True` when a friendly island is being used as a target-side crossing/bridge node rather than as a gather contribution

### `FlowTurnsEntry`

One lookup-table entry for exactly `n` turns.

This structure should stay small and cheap because it will be touched in tight loops.
It should store only what is needed directly for lookup, pairing, and partial-island reconstruction.

Fields:
- `turns: int`
- `required_army: int`
- `econ_value: float`
- `army_remaining: int`
- `gathered_army: int`
- `included_friendly_flow_nodes: tuple[IslandFlowNode, ...]`
- `included_target_flow_nodes: tuple[IslandFlowNode, ...]`
- `incomplete_friendly_island_id: int | None`
- `incomplete_friendly_tile_count: float | int`
  - amount of the incomplete friendly island still unused at this exact turn entry
- `incomplete_target_island_id: int | None`
- `incomplete_target_tile_count: float | int`
  - amount of the incomplete target island still unused at this exact turn entry
- `gather_index: int | None`
  - populated in Step 2
- `combined_value_density: float | None`
  - populated in Step 2

Notes:

- `combined_turn_cost` does not need to be stored as a field if the entry is still being accessed through its table index and `gather_index`
- island references should generally be recovered from the included flow nodes rather than redundantly stored
- no `capture_tiles` / `gather_tiles` tuple payload should be stored here; that was underspecified and unnecessary for the lookup-table structure

### `FlowArmyTurnsLookupTable`
Per border pair.

Fields:
- `border_pair: FlowBorderPairKey`
- `capture_entries_by_turn: list[FlowTurnsEntry | None]`
- `gather_entries_by_turn: list[FlowTurnsEntry | None]`
- `best_capture_entries_prefix: list[FlowTurnsEntry | None]`
- `best_gather_entries_prefix: list[FlowTurnsEntry | None]`
- `metadata`
  - `max_flow_across_border`
  - `friendly_stream_tile_count`
  - `target_stream_tile_count`
  - `contains_neutral_capture`
  - `overlap_candidates_with_border_pairs`
  - `source_flow_variant`
    - neutral-inclusive or enemy-only

### `FlowExpansionV2DebugSnapshot`
Optional, but recommended for tests/debug.

Fields:
- graph stats
- number of border pairs
- number of entries generated per border pair
- overlap warnings
- pruned vs kept choices

## Phase Plan

## Phase -1: Split algorithm-specific test harnesses first ✅
Before implementing V2 algorithms, create separate test files for each planned algorithm / planning mode.

Goal:
- make it easy to iterate independently on each algorithm's expected behavior
- keep scenario coverage aligned across algorithms
- allow expectations to diverge cleanly where algorithm design intentionally differs

Suggested test layout:

- `UnitTests/test_FlowExpansion_<Algorithm>.py`

Examples:

- `UnitTests/test_FlowExpansion_BorderStreamPreprocess.py` ✅
- `UnitTests/test_FlowExpansion_LookupGeneration.py` ✅
- `UnitTests/test_FlowExpansion_GroupedKnapsack.py` ✅
- `UnitTests/test_FlowExpansion_PostOptimization.py` ✅
- or, if you prefer the files to map directly to concrete runtime planners instead of phases, use names matching the actual algorithm classes/modes

Initial content plan:

- copy the tests from `UnitTests/test_FlowExpansion.py` that use explicit inline map data ✅
- use those copied tests as the seed scenarios in each algorithm-specific file ✅
- keep the scenarios duplicated across files on purpose initially so each algorithm is exercised against the same tiny deterministic map situations ✅
- do not spend time normalizing all assertions up front; the copied expectations can be tuned later while implementation proceeds ✅

Important scope note:

- prioritize the tests with hardcoded inline maps first ✅
- these are the scenarios where we can most confidently assert hard truths about behavior
- file-based larger / fuzzier / performance cases can stay in later phases until the algorithm foundations exist

Recommended first execution steps:

1. Identify all `test_FlowExpansion.py` tests that build maps from inline string literals. ✅
2. Copy those scenarios into each algorithm-specific test file. ✅
3. Keep the copied assertions close to the original for now, even if some will later change. ✅
4. Use those duplicated scenario sets as the collaborative surface for expectation tuning during implementation. ✅

## Phase 0: Lock down invariants and compatibility ✅
Deliverables:
- Define exact V2 class surface. ✅
- Decide which existing methods are delegated vs reimplemented. ✅
- Define turn accounting rules in one place. ✅
- Confirm implementation file/module. ✅

Compatibility target:
- `get_expansion_options(...)` must still return `FlowExpansionPlanOptionCollection` with `GatherCapturePlan` outputs. ✅
- For simple cases with a clear optimum, V2 should still produce the same best solution.
- For complex cases, V2 is allowed to differ from V1 and from some current tests.
- We should not assume the current V1 test suite is a complete or correct spec for V2.

Implementation location:
- `BehaviorAlgorithms/FlowExpansion.py` ✅
- primary class: `ArmyFlowExpanderV2` ✅

Unit tests to add first:
- **Interface parity smoke test**
  - instantiate old and new expander on a trivial map
  - assert both return `FlowExpansionPlanOptionCollection`
- **Turn accounting smoke test**
  - border crossing with one friendly and one enemy island
  - verify first crossing counts the same way as current tests expect

Test harness prerequisite:
- complete Phase -1 first so new assertions land in algorithm-specific files, not by continuing to grow one monolithic `test_FlowExpansion.py` ✅

## Phase 1: Build explicit border stream extraction

Implement a preprocessing stage that identifies valid border-pair streams from `IslandMaxFlowGraph`.

Responsibilities:
- Enumerate friendly-target border pairs.
- Verify there is actual flow support across the pair or along reachable stream nodes.
- Build directional stream traversals:
  - upstream gather traversal from the friendly border node
  - downstream capture traversal from the target border node

Important rule:
- Traversal should be based on flow-node edges, not raw map adjacency alone.
- Raw adjacency is only used when converting island-level decisions into concrete tile-level capture/gather ordering.
- Border-pair lookup tables should be generated separately for each flow variant (`include neutral`, `enemy only`).

Suggested functions:
- `enumerate_border_pairs(flow_graph, islands, my_team, target_team) -> list[FlowBorderPairKey]` ✅
- `build_border_pair_stream_data(...) -> FlowBorderPairStreamData` 🏗️
- `preprocess_flow_stream_tilecounts(...)` 🏗️
- `detect_target_crossable_friendly_islands(...) -> set[int]` ✅

Unit tests:
- **Enumerates border pairs correctly**
  - simple 1-border map
  - multiple border map
- **Target-crossable friendly island is excluded from border-pair seeds**
- **Friendly stream extraction respects flow direction**
  - upstream friendly islands included, unrelated friendlies excluded
- **Target stream extraction respects target side**
  - enemy and allowed neutral nodes included in correct preference order
- **Target stream extraction may traverse target-crossable friendly bridge nodes**
- **No duplicate island inclusion inside one stream**
  - cyclic / converging flow graph case

## Phase 1.5: Compute stream ordering metadata ✅
This is the prompt’s `preprocess_flow_stream_tilecounts(...)` idea and should be made concrete.

For each border pair stream, compute:
- upstream total tile count
- upstream total gatherable army
- per-node marginal army / tile ratio
- downstream capture tile ordering
- downstream capture army costs
- node ancestry / predecessor info for reconstruction
- target-crossable node metadata for target-side traversal
- downstream aggregate stream statistics needed to choose low-cost, high-value continuation paths

Clarified heuristic:
- **Friendly ordering**
  - sort by descending effective `gatherable_army / committed_tiles`
  - use flow magnitude as tie-breaker
  - allow upstream continuation through locally bad nodes if they unlock stronger aggregate gather throughput early
- **Target ordering**
  - use a heuristic score, not a hard enemy-first rule
  - prefer lower army-per-tile and stronger downstream continuation potential
  - include target type as one feature in scoring, not a strict gate
  - allow neutral-first expansion when it clearly improves achievable econ-value-per-turn
  - allow traversal through `target crossable` friendly islands with turn cost and no direct econ reward
  - aggregate downstream stream statistics similarly to gather-side ordering, but using capture-focused metrics
  - prefer continuation streams with better effective `(army-per-tile average) / (econValue-per-tile average)` style payoff

Important caveat:
The prompt’s “highest value stream first” is not globally optimal. Treat it as preprocessing order only, not proof of optimality.

Unit tests:

- **Friendly ranking prefers better army-per-tile**
- **Target ranking prefers enemy over neutral at equal cost when continuation value is otherwise similar**
- **Target ranking prefers lower army tiles first**
- **Neutral branch can outrank enemy branch when downstream econ/turn is better**
- **Target-crossable friendly bridge can be traversed to reach better downstream captures**
- **Converging friendly streams compute upstream counts correctly**
- **Locally bad capture step can be preferred when it unlocks better downstream aggregate capture payoff**

## Phase 2: Build per-border gather/capture lookup tables ✅

Implement:

- `process_flow_into_flow_army_turns(...) -> list[FlowArmyTurnsLookupTable]` ✅

This is the main Step 1 from the prompt, clarified.

### Capture lookup generation

For each border pair:
- Walk target-side stream in preferred order.
- Incrementally add islands.
- Between island boundaries, fill intermediate turn entries using partial tile walking.
- For each reachable turn count `t`, store the best capture entry for exactly `t` turns.

Clarification:
- if the walk reaches a `target crossable` friendly island, include only its turn cost / routing effect
- do not add capture econ for it
- do account for any army-burn reduction implied by traversing a friendly-held island instead of hostile tiles

Turn accounting rule:

- a border crossing plan that starts with a friendly island of size `1` and a target island of size `1` has total cost `1`
- each additional island added on either side costs its consumed tile count
- therefore, if `gatherLookup[0]` represents the zero-cost starting border tile state, then:
  - `combined_cost = gather_index + capture_index`
- `captureLookup[0]` is treated as an unused index in this convention
- partial island usage costs exactly the number of tiles consumed
  - using `2` tiles from a size-`4` island costs `2`
  - using `1.5` tiles should be treated according to the implementation’s partial-tile accounting, but the effective turn cost at that point is the amount consumed

### Gather lookup generation

Similarly:
- Walk gather-side stream in preferred order.
- Incrementally add friendly islands.
- Fill intermediate turn entries using partial tile walking.
- For each reachable turn count `t`, store the best gather entry for exactly `t` turns.

Partial-island bookkeeping rule:
- when an entry only partially consumes a friendly or target island, store:
  - which island is incomplete
  - how many tiles remain unused for that entry
- exact per-tile army ordering does not need to be stored in the lookup entry itself; worst-case tile selection can be inferred later during materialization/reconstruction if needed

### Critical clarification
Capture and gather lookup generation should be independent first.
Do **not** try to pair them during generation.
That keeps the stage deterministic and unit testable.

### Partial island walking reuse from old implementation
This is the one area where V2 should borrow concepts from `IterativeExpansion.find_flow_plans(...)`:
- when a newly added island contributes more tiles than needed for the next few turn counts,
- fill each intermediate turn entry by partially consuming tiles from the island in the same tile order the current algorithm effectively models.

But this should be implemented as standalone helpers, e.g.:
- `build_partial_capture_entries(...)`
- `build_partial_gather_entries(...)`

Unit tests:
- **Single border exact capture**
  - should generate entries for 1, 3, 5 turns when applicable
- **Intermediate turn entries exist between island jumps**
- **Excess gather army reflected in `army_remaining`**
- **Insufficient extra gather island not selected if it adds no capture value**
  - mirrors existing tests like "not enough army to fully cap"
- **Neutral-inclusive capture table values neutral appropriately**

## Phase 3: Enrich capture entries with minimum gather support ✅
Implement prompt Step 2 as:
- `postprocess_flow_stream_gather_capture_lookup_pairs(...)` ✅

For each border pair and each capture entry:
- find the minimum-turn gather entry whose `gathered_army >= capture.required_army`
- record:
  - `gather_index`
  - `combined_turn_cost = capture.turns + gather.turns`
  - `combined_value_density = capture.econ_value / combined_turn_cost`

Clarification:
The optimization objective here should use **combined turn cost**, not just capture turns.

Also clarify tie-breaking:
- prefer lower `combined_turn_cost`
- then higher `econ_value`
- then lower overlap risk / fewer committed islands

Unit tests:

- **Capture entry maps to minimum sufficient gather entry**
- **No gather match leaves entry unusable**
- **Combined density computed correctly**
- **Tie-breaking prefers shorter supporting gather**

## Phase 4: Simple solution path via grouped knapsack ✅
Implement the prompt’s `.use_simple_flow_stream_maximization: bool`.

When enabled:

- each border pair is a multiple-choice group
- each usable capture entry contributes one candidate item with:
  - value = `econ_value`
  - weight = `combined_turn_cost`
- solve grouped knapsack for `turns`
- convert chosen entries into `GatherCapturePlan`s

This should be the first fully working V2 path.

Reason:
- Easy to validate
- Deterministic
- Matches prompt intent
- Does not block later step 3.b local-improvement work

Design constraint for 3.a:
- the grouped-knapsack output must preserve enough provenance to support 3.b later:
  - exact chosen border pair
  - chosen gather/capture entries
  - committed friendly / target island IDs
  - remaining turn budget
  - rejected near-miss candidates if useful for local replacement

Unit tests:
- **Single border pair chooses best capture depth within turn limit**
- **Two border pairs compete for same turn budget**
- **Grouped constraint enforces one choice per border pair**
- **Zero-valid-choice group is ignored safely**
- **Selection result retains reconstruction/provenance metadata needed for 3.b**

## Phase 5: Convert chosen lookup entries into `GatherCapturePlan`
Implement a single plan materialization layer.

Responsibilities:
- reconstruct chosen gather/capture island sets
- derive concrete tile paths / moves
- populate plan metrics consistently with old tests

Important compatibility fields:
- `length`
- `econValue`
- `gathered_army`
- `armyRemaining`
- `approximate_capture_tiles`
- `tileSet`

Important clarification:
The lookup-table stage should store enough reconstruction metadata so this stage does not need to redo optimization.

Unit tests:
- **Materialized plan length matches chosen lookup**
- **`gathered_army` matches source-side table entry**
- **`armyRemaining` matches gather minus capture requirement**
- **Concrete plan tiles are subset of recorded stream tiles**

## Phase 6: Optional post-optimization path
When `.use_simple_flow_stream_maximization` is `False`:
- run grouped knapsack first to produce a baseline
- then run localized improvement search

Suggested first implementation:
- keep the best ~50% of chosen turn-spend by value density
- free the rest of the turn budget
- mark kept gather/capture islands visited
- explore only unvisited adjacent extensions
- add improvements only if they dominate the removed options

This phase should be explicitly designed up front, even if implemented after 3.a is validated.

Clarification to the prompt:
This should be framed as a **local-improvement heuristic**, not as a guaranteed optimizer.

Unit tests:
- **Post-optimizer never returns worse total value than baseline MKCP**
- **Visited set prevents overlapping re-use of kept islands**
- **Post-optimizer can improve a crafted local-extension case**

## Recommended Implementation Order
1. Create `ArmyFlowExpanderV2` skeleton with same public method.
2. Reuse existing graph building and flow dict generation.
3. Implement border pair enumeration and stream extraction.
4. Implement Phase 1.5 metadata preprocessing.
5. Implement exact turn-indexed gather/capture lookup generation.
6. Implement Step 2 enrichment.
7. Implement grouped knapsack path.
8. Implement plan materialization.
9. Run current `UnitTests/test_FlowExpansion.py` against V2 adapter.
10. Only then consider post-optimization.

## Testing Strategy by Layer

### Layer A: Graph / stream preprocessing tests
Use tiny hand-authored maps like current unit tests.

Focus on:
- border identification
- stream inclusion
- ordering
- overlap prevention
- target-crossable detection and exclusion from border seeding

### Layer B: Lookup-table generation tests
These should not require full plan conversion.

Assert directly on lookup entries:
- reachable turn indices
- required army
- econ value
- included island IDs
- gather/capture tile counts

This is the biggest missing test surface in the current suite and should be added.

### Layer C: Knapsack / selection tests
Mock or construct lookup tables directly.

Reason:
- lets you test the optimizer independently from graph generation.
- faster and more deterministic.

### Layer D: End-to-end compatibility tests
Reuse and adapt existing `UnitTests/test_FlowExpansion.py` patterns.

Initial V2 acceptance bar:

- pass the simple straight-line cases first
- then cumulative gather cases
- then mixed neutral/enemy cases
- then multi-branch and performance cases

Important note:

- some existing tests that expect all intermediate options rather than only the final optimal combination may need to be rewritten or split.
- V2 should be judged by correctness of the produced best plan set, not by reproducing V1’s full option enumeration behavior.
- the inline-map scenario tests copied into `test_FlowExpansion_<Algorithm>.py` files should be the primary iteration surface while algorithms are being implemented.
- both flow variants should be testable independently through their own lookup-table generation paths.

## Additional Tests To Add Beyond Current Coverage

- **Lookup generation with converging upstream friendly streams**
- **Lookup generation with two border pairs sharing upstream source candidates**
- **Capture ordering where neutral is cheaper but enemy should still be preferred first**
- **Validation mode allows overlap; production mode prunes overlap**
- **Flow graph cache invalidation if enemy general / target team changes**
- **Performance regression benchmark for lookup generation alone**
- **Target-crossable friendly bridge case with downstream enemy payoff**

## Test Migration Notes

When splitting `UnitTests/test_FlowExpansion.py` into algorithm-specific files:

- start by copying, not refactoring
- only copy tests that use explicit inline map strings in the first pass
- preserve scenario names closely so cross-file comparison stays easy
- allow expected assertions to temporarily remain imperfect until each algorithm is implemented enough to tune them collaboratively
- leave larger file-driven, benchmark, or broad integration tests for a later pass

## Finalized Decisions

### 1. Stream uniqueness

Within a single flow graph output, streams are assumed unique.
Separate lookup-table families should be produced for:

- neutral-inclusive flow data
- enemy-only flow data

The only currently expected duplication is between those two flow variants.

### 2. Lookup tables are turn-indexed only
No separate army-indexed lookup table should be built.
Army requirement should remain payload on each turn entry.

### 3. Turn accounting rule

- starting border pair cost for `size-1 friendly -> size-1 target` is `1`
- each additional island costs the number of consumed tiles from that island
- combined partial-solution cost follows `gather_index + capture_index`
- `gatherLookup[0]` represents the zero-cost border starting state
- `captureLookup[0]` is unused in that convention

### 4. Initial path materialization requirement
V2 does not need exact move-list fidelity in general complex cases.
For the first implementation, it is acceptable to reuse the current `IterativeExpansion`/`GatherCapturePlan` materialization steps as a downstream renderer of the chosen flow/tile sets.
For tiny deterministic maps with a clearly best plan, we should still expect the existing converter to trivially emit the correct move list when V2 chooses the correct plan / flow sets.

### 5. Neutral handling in target ordering
This should be heuristic-driven, not a hard enemy-first rule.
Some maps will prefer neutral-first extension if it unlocks better downstream econ-value-per-turn.

### 6. Target/capture stream ordering should use aggregate downstream stats
Just as gather-side ordering may choose a locally worse step to access stronger upstream throughput earlier, target-side ordering should be able to choose a locally worse capture extension when it unlocks a better downstream capture stream.

### 7. Implementation file
`ArmyFlowExpanderV2` should live in `BehaviorAlgorithms/FlowExpansion.py`.

## Recommended First Acceptance Scope
For the first mergeable V2 milestone, I recommend:
- graph reuse
- border stream extraction
- turn-indexed gather/capture tables
- capture/gather pairing
- grouped knapsack selection
- enough plan materialization to satisfy current tests
- no post-optimization yet

That gives a smaller, testable vertical slice and avoids repeating the complexity collapse currently present in `IterativeExpansion.py`.
