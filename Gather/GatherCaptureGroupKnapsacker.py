from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

import KnapsackUtils
import logbook
from Algorithms.FastDisjointSet import FastDisjointSet
from PerformanceTimer import PerformanceTimer


@dataclass(slots=True)
class GroupedKnapsackIterationSummary:
    iteration: int
    max_value: int
    chosen_indices: list[int]
    chosen_weight: int
    conflicts: list[tuple[int, int]]


@dataclass(slots=True)
class GroupedKnapsackInput:
    turn_budget: int
    groups: list[int]
    weights: list[int]
    values: list[int]
    econ_values: list[float]
    friendly_island_sets: list[list[int]]
    target_island_sets: list[list[int]]
    item_tile_sets: list[list[int]]
    is_external_item: dict[int, bool]
    item_descriptions: list[str]
    max_iterations: int = 32


@dataclass(slots=True)
class GroupedKnapsackPreGroupItem:
    border_pair: tuple[int, int] | None
    external_group_id: int | None
    is_external: bool
    weight: int
    value: int
    econ_value: float
    friendly_island_set: list[int]
    target_island_set: list[int]
    item_tile_set: list[int]
    description: str


@dataclass(slots=True)
class GroupedKnapsackPreGroupInput:
    turn_budget: int
    items: list[GroupedKnapsackPreGroupItem]
    max_iterations: int = 32


@dataclass(slots=True)
class GroupedKnapsackResult:
    max_value: int
    chosen_indices: list[int]
    chosen_weight: int
    chosen_descriptions: list[str]
    blacklist: list[int]
    iteration_summaries: list[GroupedKnapsackIterationSummary]
    groups: list[int] | None = None


@dataclass(slots=True)
class GroupedKnapsackPrunedGrouping:
    active_indices: list[int]
    groups_by_index: dict[int, int]
    maybe_options: list[GroupedKnapsackMaybeOption]


@dataclass(slots=True)
class GroupedKnapsackMaybeOption:
    option_index: int
    would_merge_groups: tuple[int, ...]


@dataclass(slots=True)
class GroupedKnapsackGroupState:
    root_id: int
    option_indices: list[int]
    tile_ids: set[int]
    frontier: list[tuple[int, float, int]]
    frontier_by_input_group: dict[int, list[tuple[int, float, int]]]
    max_econ_value: float
    max_turns: int


def _get_option_value_per_turn(input_data: GroupedKnapsackInput, index: int) -> float:
    return input_data.econ_values[index] / max(input_data.weights[index], 1)


def _is_dominated_by_frontier(input_data: GroupedKnapsackInput, frontier: list[tuple[int, float, int]], index: int) -> bool:
    turns = input_data.weights[index]
    econ_value = input_data.econ_values[index]
    for existing_turns, existing_value, _ in reversed(frontier):
        if existing_turns <= turns:
            return existing_value >= econ_value
    return False


def _add_to_frontier(input_data: GroupedKnapsackInput, frontier: list[tuple[int, float, int]], index: int):
    turns = input_data.weights[index]
    econ_value = input_data.econ_values[index]
    insert_at = 0
    while insert_at < len(frontier) and frontier[insert_at][0] < turns:
        insert_at += 1
    while insert_at < len(frontier) and frontier[insert_at][0] == turns:
        if frontier[insert_at][1] <= econ_value:
            frontier.pop(insert_at)
        else:
            insert_at += 1
    frontier.insert(insert_at, (turns, econ_value, index))

    prune_at = insert_at + 1
    while prune_at < len(frontier):
        if frontier[prune_at][1] <= econ_value:
            frontier.pop(prune_at)
        else:
            prune_at += 1


def _describe_grouped_knapsack_option(input_data: GroupedKnapsackInput, index: int) -> str:
    return (
        f'idx={index} weight={input_data.weights[index]} value={input_data.values[index]} '
        f'econ={input_data.econ_values[index]:.2f} vpt={_get_option_value_per_turn(input_data, index):.3f} '
        f'tiles={sorted(input_data.item_tile_sets[index])} desc={input_data.item_descriptions[index]}')


def _describe_grouped_knapsack_external_flag(input_data: GroupedKnapsackInput, index: int) -> str:
    if input_data.is_external_item.get(index, False):
        return 'external'
    return 'flow'


def prune_and_get_groups_for_knapsack(input_data: GroupedKnapsackInput, noLog: bool = True) -> GroupedKnapsackPrunedGrouping:
    sorted_indices = sorted(
        range(len(input_data.weights)),
        key=lambda idx: (
            -_get_option_value_per_turn(input_data, idx),
            -input_data.econ_values[idx],
            input_data.weights[idx],
            idx))

    disjoint_set = FastDisjointSet()
    group_state_by_root: dict[int, GroupedKnapsackGroupState] = {}
    active_indices: list[int] = []
    groups_by_index: dict[int, int] = {}
    maybe_options: list[GroupedKnapsackMaybeOption] = []

    for index in sorted_indices:
        tile_set = set(input_data.item_tile_sets[index])
        overlapping_roots: set[int] = set()
        for tile_id in tile_set:
            if tile_id in disjoint_set:
                overlapping_roots.add(disjoint_set[tile_id])

        if not noLog and input_data.is_external_item.get(index, False):
            overlap_options = [
                option_idx
                for root in sorted(overlapping_roots)
                if root in group_state_by_root
                for option_idx in group_state_by_root[root].option_indices
                if bool(tile_set & set(input_data.item_tile_sets[option_idx]))
            ]
            logbook.info(
                f'Grouped knapsack external inspect: {_describe_grouped_knapsack_option(input_data, index)} '
                f'overlapping_roots={sorted(overlapping_roots)} '
                f'overlap_options={overlap_options} '
                f'overlap_descriptions={[ _describe_grouped_knapsack_option(input_data, option_idx) for option_idx in overlap_options ]}')

        if len(overlapping_roots) > 1:
            maybe_options.append(GroupedKnapsackMaybeOption(
                option_index=index,
                would_merge_groups=tuple(sorted(overlapping_roots))))
            if not noLog:
                conflicted_options = [
                    group_state_by_root[root].option_indices
                    for root in sorted(overlapping_roots)
                    if root in group_state_by_root
                ]
                logbook.info(
                    f'Grouped knapsack prune: deferring maybe type={_describe_grouped_knapsack_external_flag(input_data, index)} '
                    f'{_describe_grouped_knapsack_option(input_data, index)} '
                    f'would_merge_roots={sorted(overlapping_roots)} conflicted_options={conflicted_options}')
            continue

        if len(overlapping_roots) == 1:
            root = next(iter(overlapping_roots))
        else:
            root = next(iter(tile_set))

        disjoint_set.add(root)
        for tile_id in tile_set:
            disjoint_set.add(tile_id)
            disjoint_set.merge(root, tile_id)

        root = disjoint_set[root]
        if root not in group_state_by_root:
            group = GroupedKnapsackGroupState(
                root_id=root,
                option_indices=[],
                tile_ids=set(),
                frontier=[],
                frontier_by_input_group={},
                max_econ_value=0.0,
                max_turns=0)
            group_state_by_root[root] = group
            if not noLog:
                logbook.info(
                    f'Grouped knapsack prune: new group root={root} '
                    f'type={_describe_grouped_knapsack_external_flag(input_data, index)} '
                    f'option={_describe_grouped_knapsack_option(input_data, index)}')
        else:
            group = group_state_by_root[root]
            input_group = input_data.groups[index]
            input_group_frontier = group.frontier_by_input_group.get(input_group, [])
            if _is_dominated_by_frontier(input_data, input_group_frontier, index):
                if not noLog:
                    logbook.info(
                        f'Grouped knapsack prune: dominated option skipped root={root} '
                        f'type={_describe_grouped_knapsack_external_flag(input_data, index)} '
                        f'input_group={input_group} frontier={input_group_frontier} '
                        f'option={_describe_grouped_knapsack_option(input_data, index)}')
                continue
            if not noLog:
                logbook.info(
                    f'Grouped knapsack prune: adding to group root={root} '
                    f'type={_describe_grouped_knapsack_external_flag(input_data, index)} '
                    f'option={_describe_grouped_knapsack_option(input_data, index)}')

        group.option_indices.append(index)
        group.tile_ids.update(tile_set)
        group.max_econ_value = max(group.max_econ_value, input_data.econ_values[index])
        group.max_turns = max(group.max_turns, input_data.weights[index])
        _add_to_frontier(input_data, group.frontier, index)
        input_group = input_data.groups[index]
        if input_group not in group.frontier_by_input_group:
            group.frontier_by_input_group[input_group] = []
        _add_to_frontier(input_data, group.frontier_by_input_group[input_group], index)
        active_indices.append(index)

    compact_group_by_root = {
        root: group_id
        for group_id, root in enumerate(sorted(group_state_by_root.keys()))
    }
    for root, group in group_state_by_root.items():
        group_id = compact_group_by_root[root]
        for index in group.option_indices:
            groups_by_index[index] = group_id

    maybe_options = [
        GroupedKnapsackMaybeOption(
            option_index=maybe.option_index,
            would_merge_groups=tuple(sorted(
                compact_group_by_root[root]
                for root in maybe.would_merge_groups
                if root in compact_group_by_root)))
        for maybe in maybe_options
    ]
    maybe_options.sort(key=lambda maybe: (-input_data.econ_values[maybe.option_index], input_data.weights[maybe.option_index], maybe.option_index))

    if not noLog:
        logbook.info(
            f'Grouped knapsack prune complete: active={len(active_indices)} groups={len(compact_group_by_root)} '
            f'maybes={len(maybe_options)} pruned={len(input_data.weights) - len(active_indices) - len(maybe_options)}')
        external_active = [
            index
            for index in active_indices
            if input_data.is_external_item.get(index, False)
        ]
        external_maybes = [
            maybe.option_index
            for maybe in maybe_options
            if input_data.is_external_item.get(maybe.option_index, False)
        ]
        logbook.info(
            f'Grouped knapsack external prune summary: active={external_active} maybes={external_maybes} '
            f'active_descriptions={[ _describe_grouped_knapsack_option(input_data, index) for index in external_active ]} '
            f'maybe_descriptions={[ _describe_grouped_knapsack_option(input_data, index) for index in external_maybes ]}')

    return GroupedKnapsackPrunedGrouping(
        active_indices=active_indices,
        groups_by_index=groups_by_index,
        maybe_options=maybe_options)


def solve_grouped_knapsack_input(
        input_data: GroupedKnapsackInput,
        noLog: bool = True,
        perfTimer: PerformanceTimer | None = None
) -> GroupedKnapsackResult:
    turn_budget = input_data.turn_budget
    weights = input_data.weights
    values = input_data.values
    item_descriptions = input_data.item_descriptions
    grouping = prune_and_get_groups_for_knapsack(input_data, noLog=noLog)

    active_idx = sorted(grouping.active_indices, key=lambda i: (grouping.groups_by_index[i], i))
    a_groups = [grouping.groups_by_index[i] for i in active_idx]
    a_weights = [weights[i] for i in active_idx]
    a_values = [values[i] for i in active_idx]
    max_value, chosen_orig_idx = KnapsackUtils.solve_multiple_choice_knapsack(
        active_idx, turn_budget, a_weights, a_values, a_groups, noLog=noLog, longRuntimeThreshold=10.0)

    chosen_by_group = {
        grouping.groups_by_index[index]: index
        for index in chosen_orig_idx
    }
    chosen_set = set(chosen_orig_idx)
    chosen_weight = sum(weights[i] for i in chosen_set)
    chosen_value = sum(values[i] for i in chosen_set)

    if chosen_weight < turn_budget - 3:
        for maybe in grouping.maybe_options:
            maybe_idx = maybe.option_index
            replaced_indices = sorted({
                chosen_by_group[group_id]
                for group_id in maybe.would_merge_groups
                if group_id in chosen_by_group
            })
            replaced_weight = sum(weights[i] for i in replaced_indices)
            replaced_value = sum(values[i] for i in replaced_indices)
            candidate_weight = chosen_weight - replaced_weight + weights[maybe_idx]
            candidate_value = chosen_value - replaced_value + values[maybe_idx]

            if candidate_weight > turn_budget:
                if not noLog:
                    logbook.info(
                        f'Grouped knapsack maybe rejected overweight: maybe={_describe_grouped_knapsack_option(input_data, maybe_idx)} '
                        f'would_merge_groups={maybe.would_merge_groups} replaced={replaced_indices} '
                        f'candidate_weight={candidate_weight} turn_budget={turn_budget}')
                continue
            if candidate_value <= chosen_value:
                if not noLog:
                    logbook.info(
                        f'Grouped knapsack maybe rejected no improvement: maybe={_describe_grouped_knapsack_option(input_data, maybe_idx)} '
                        f'would_merge_groups={maybe.would_merge_groups} replaced={replaced_indices} '
                        f'candidate_value={candidate_value} chosen_value={chosen_value}')
                continue

            for replaced_idx in replaced_indices:
                chosen_set.remove(replaced_idx)
                replaced_group = grouping.groups_by_index.get(replaced_idx, None)
                if replaced_group is not None and replaced_group in chosen_by_group:
                    del chosen_by_group[replaced_group]
            chosen_set.add(maybe_idx)
            for group_id in maybe.would_merge_groups:
                chosen_by_group[group_id] = maybe_idx
            chosen_weight = candidate_weight
            chosen_value = candidate_value
            if not noLog:
                logbook.info(
                    f'Grouped knapsack maybe substitution: maybe={_describe_grouped_knapsack_option(input_data, maybe_idx)} '
                    f'would_merge_groups={maybe.would_merge_groups} replaced={replaced_indices} '
                    f'chosen_weight={chosen_weight}, chosen_value={chosen_value}')

    repair_timing_context = perfTimer.begin_move_event('Grouped knapsack post-solve repair scan') if perfTimer is not None else nullcontext()
    with repair_timing_context:
        chosen_tile_owner_by_tile_id: dict[int, int] = {}
        chosen_by_input_group: dict[int, int] = {}
        for chosen_idx in chosen_set:
            chosen_by_input_group[input_data.groups[chosen_idx]] = chosen_idx
            for tile_id in input_data.item_tile_sets[chosen_idx]:
                chosen_tile_owner_by_tile_id[tile_id] = chosen_idx

        conflict_free_indices: list[int] = []
        for option_idx in range(len(weights)):
            if option_idx in chosen_set:
                continue

            conflicting_chosen_indices = {
                chosen_tile_owner_by_tile_id[tile_id]
                for tile_id in input_data.item_tile_sets[option_idx]
                if tile_id in chosen_tile_owner_by_tile_id
            }
            option_input_group = input_data.groups[option_idx]
            same_group_chosen_idx = chosen_by_input_group.get(option_input_group, None)
            if len(conflicting_chosen_indices) == 0:
                conflict_free_indices.append(option_idx)
                continue
            if len(conflicting_chosen_indices) > 1:
                continue
            replaced_idx = next(iter(conflicting_chosen_indices))
            if same_group_chosen_idx is not None and same_group_chosen_idx != replaced_idx:
                continue

            candidate_weight = chosen_weight - weights[replaced_idx] + weights[option_idx]
            candidate_value = chosen_value - values[replaced_idx] + values[option_idx]
            if candidate_weight > turn_budget or candidate_value <= chosen_value:
                continue

            chosen_set.remove(replaced_idx)
            chosen_set.add(option_idx)
            chosen_weight = candidate_weight
            chosen_value = candidate_value
            if input_data.groups[replaced_idx] in chosen_by_input_group:
                del chosen_by_input_group[input_data.groups[replaced_idx]]
            chosen_by_input_group[option_input_group] = option_idx
            for tile_id in input_data.item_tile_sets[replaced_idx]:
                if chosen_tile_owner_by_tile_id.get(tile_id, None) == replaced_idx:
                    del chosen_tile_owner_by_tile_id[tile_id]
            for tile_id in input_data.item_tile_sets[option_idx]:
                chosen_tile_owner_by_tile_id[tile_id] = option_idx
            if not noLog:
                logbook.info(
                    f'Grouped knapsack post-solve single-conflict substitution: '
                    f'option={_describe_grouped_knapsack_option(input_data, option_idx)} '
                    f'replaced={_describe_grouped_knapsack_option(input_data, replaced_idx)} '
                    f'chosen_weight={chosen_weight}, chosen_value={chosen_value}')

        considered_chosen_indices = sorted(
            chosen_set,
            key=lambda idx: (_get_option_value_per_turn(input_data, idx), values[idx], -weights[idx], idx))[:max(1, min(len(chosen_set), 8))]
        repair_capacity = sum(weights[idx] for idx in considered_chosen_indices)
        repair_existing_value = sum(values[idx] for idx in considered_chosen_indices)
        considered_chosen_set = set(considered_chosen_indices)
        considered_chosen_tile_set = {
            tile_id
            for chosen_idx in considered_chosen_indices
            for tile_id in input_data.item_tile_sets[chosen_idx]
        }
        kept_chosen_indices = chosen_set - considered_chosen_set
        kept_chosen_tile_set = {
            tile_id
            for chosen_idx in kept_chosen_indices
            for tile_id in input_data.item_tile_sets[chosen_idx]
        }
        direct_replacement_indices = [
            option_idx
            for option_idx in range(len(weights))
            if option_idx not in chosen_set
            and weights[option_idx] <= repair_capacity
            and not any(tile_id in kept_chosen_tile_set for tile_id in input_data.item_tile_sets[option_idx])
            and any(tile_id in considered_chosen_tile_set for tile_id in input_data.item_tile_sets[option_idx])
        ]
        direct_replacement_indices.sort(
            key=lambda idx: (-_get_option_value_per_turn(input_data, idx), -values[idx], weights[idx], idx))
        conflict_free_indices.sort(
            key=lambda idx: (-_get_option_value_per_turn(input_data, idx), -values[idx], weights[idx], idx))
        repair_candidate_indices = (
            considered_chosen_indices +
            direct_replacement_indices[:max(8, len(considered_chosen_indices) * 4)] +
            [
                option_idx
                for option_idx in conflict_free_indices[:max(8, len(considered_chosen_indices) * 4)]
                if weights[option_idx] <= repair_capacity
                and not any(tile_id in kept_chosen_tile_set for tile_id in input_data.item_tile_sets[option_idx])
            ])
        repair_candidate_indices = list(dict.fromkeys(repair_candidate_indices))

    if len(repair_candidate_indices) > len(considered_chosen_indices):
        repair_solve_timing_context = perfTimer.begin_move_event(f'Grouped knapsack post-solve repair solve candidates={len(repair_candidate_indices)}') if perfTimer is not None else nullcontext()
        with repair_solve_timing_context:
            repair_input = GroupedKnapsackInput(
                turn_budget=repair_capacity,
                groups=[input_data.groups[idx] for idx in repair_candidate_indices],
                weights=[weights[idx] for idx in repair_candidate_indices],
                values=[values[idx] for idx in repair_candidate_indices],
                econ_values=[input_data.econ_values[idx] for idx in repair_candidate_indices],
                friendly_island_sets=[input_data.friendly_island_sets[idx] for idx in repair_candidate_indices],
                target_island_sets=[input_data.target_island_sets[idx] for idx in repair_candidate_indices],
                item_tile_sets=[input_data.item_tile_sets[idx] for idx in repair_candidate_indices],
                is_external_item={
                    local_idx: input_data.is_external_item[original_idx]
                    for local_idx, original_idx in enumerate(repair_candidate_indices)
                    if input_data.is_external_item.get(original_idx, False)
                },
                item_descriptions=[input_data.item_descriptions[idx] for idx in repair_candidate_indices],
                max_iterations=input_data.max_iterations)
            repair_grouping = prune_and_get_groups_for_knapsack(repair_input, noLog=noLog)
            repair_active_idx = sorted(repair_grouping.active_indices, key=lambda i: (repair_grouping.groups_by_index[i], i))
            repair_groups = [repair_grouping.groups_by_index[i] for i in repair_active_idx]
            repair_weights = [repair_input.weights[i] for i in repair_active_idx]
            repair_values = [repair_input.values[i] for i in repair_active_idx]
            repair_max_value, repair_chosen_local_indices = KnapsackUtils.solve_multiple_choice_knapsack(
                repair_active_idx, repair_capacity, repair_weights, repair_values, repair_groups, noLog=noLog, longRuntimeThreshold=10.0)
        repair_chosen_original_indices = {
            repair_candidate_indices[local_idx]
            for local_idx in repair_chosen_local_indices
        }
        repair_chosen_tile_set: set[int] = set()
        repair_has_duplicate_tiles = False
        for repair_idx in repair_chosen_original_indices:
            for tile_id in input_data.item_tile_sets[repair_idx]:
                if tile_id in repair_chosen_tile_set:
                    repair_has_duplicate_tiles = True
                repair_chosen_tile_set.add(tile_id)
        repair_chosen_input_groups = [input_data.groups[idx] for idx in repair_chosen_original_indices]
        repair_has_duplicate_groups = len(repair_chosen_input_groups) != len(set(repair_chosen_input_groups))
        remaining_chosen_indices = chosen_set - considered_chosen_set
        remaining_chosen_tile_set = {
            tile_id
            for chosen_idx in remaining_chosen_indices
            for tile_id in input_data.item_tile_sets[chosen_idx]
        }
        remaining_chosen_input_groups = {
            input_data.groups[chosen_idx]
            for chosen_idx in remaining_chosen_indices
        }
        if (
                not repair_has_duplicate_tiles
                and not repair_has_duplicate_groups
                and not bool(repair_chosen_tile_set & remaining_chosen_tile_set)
                and not bool(set(repair_chosen_input_groups) & remaining_chosen_input_groups)
                and repair_max_value > repair_existing_value):
            chosen_set.difference_update(considered_chosen_set)
            chosen_set.update(repair_chosen_original_indices)
            chosen_weight = chosen_weight - repair_capacity + sum(weights[idx] for idx in repair_chosen_original_indices)
            chosen_value = chosen_value - repair_existing_value + repair_max_value
            if not noLog:
                logbook.info(
                    f'Grouped knapsack post-solve repair knapsack substitution: '
                    f'removed={[ _describe_grouped_knapsack_option(input_data, removed_idx) for removed_idx in considered_chosen_indices ]} '
                    f'added={[ _describe_grouped_knapsack_option(input_data, added_idx) for added_idx in sorted(repair_chosen_original_indices, reverse=True) ]} '
                    f'chosen_weight={chosen_weight}, chosen_value={chosen_value}')

    chosen_orig_idx = sorted(chosen_set, reverse=True)
    max_value = chosen_value
    iteration_summaries = [
        GroupedKnapsackIterationSummary(
            iteration=0,
            max_value=max_value,
            chosen_indices=chosen_orig_idx,
            chosen_weight=chosen_weight,
            conflicts=[])]

    if not noLog:
        logbook.info(
            f'Grouped knapsack pruned solve: active={len(active_idx)}, maybes={len(grouping.maybe_options)}, '
            f'chosen_weight={chosen_weight}, chosen_value={chosen_value}, chosen_indices={chosen_orig_idx}')
        external_chosen = [
            index
            for index in chosen_orig_idx
            if input_data.is_external_item.get(index, False)
        ]
        external_not_chosen = [
            index
            for index in range(len(weights))
            if input_data.is_external_item.get(index, False) and index not in chosen_set
        ]
        logbook.info(
            f'Grouped knapsack external final: chosen={external_chosen} not_chosen={external_not_chosen} '
            f'chosen_descriptions={[ _describe_grouped_knapsack_option(input_data, index) for index in external_chosen ]} '
            f'not_chosen_descriptions={[ _describe_grouped_knapsack_option(input_data, index) for index in external_not_chosen ]}')

    return GroupedKnapsackResult(
        max_value=max_value,
        chosen_indices=chosen_orig_idx,
        chosen_weight=chosen_weight,
        chosen_descriptions=[item_descriptions[i] for i in chosen_orig_idx],
        blacklist=[],
        iteration_summaries=iteration_summaries,
        groups=[grouping.groups_by_index.get(i, -1) for i in range(len(weights))]
    )


# Old repair-loop implementation reference:
# def solve_grouped_knapsack_input(
#         input_data: GroupedKnapsackInput,
#         noLog: bool = True
# ) -> GroupedKnapsackResult:
#     Repeatedly solved MKCP, detected chosen-item concrete tile conflicts, blacklisted
#     one loser, and solved again until no conflicts remained or max_iterations was hit.


def solve_grouped_knapsack_pre_group_input(
        input_data: GroupedKnapsackPreGroupInput,
        noLog: bool = True
) -> GroupedKnapsackResult:
    group_lookup: dict[tuple[int, int], int] = {}
    groups: list[int] = []
    next_group = 0

    for item in input_data.items:
        border_pair = item.border_pair
        if border_pair is None:
            group_id = item.external_group_id
        else:
            key = tuple(border_pair)
            if key not in group_lookup:
                group_lookup[key] = next_group
                next_group += 1
            group_id = group_lookup[key]
        groups.append(group_id)

    grouped_input = GroupedKnapsackInput(
        turn_budget=input_data.turn_budget,
        groups=groups,
        weights=[item.weight for item in input_data.items],
        values=[item.value for item in input_data.items],
        econ_values=[item.econ_value for item in input_data.items],
        friendly_island_sets=[item.friendly_island_set for item in input_data.items],
        target_island_sets=[item.target_island_set for item in input_data.items],
        item_tile_sets=[item.item_tile_set for item in input_data.items],
        is_external_item={
            idx: True
            for idx, item in enumerate(input_data.items)
            if item.is_external
        },
        item_descriptions=[item.description for item in input_data.items],
        max_iterations=input_data.max_iterations,
    )
    result = solve_grouped_knapsack_input(grouped_input, noLog=noLog)
    result.groups = groups
    return result


def format_pre_group_input_for_test(input_data: GroupedKnapsackPreGroupInput) -> str:
    lines = [
        'GroupedKnapsackPreGroupInput(',
        f'    turn_budget={input_data.turn_budget},',
        '    items=[',
    ]
    for item in input_data.items:
        lines.extend(_format_pre_group_item_for_test(item, 8))
    lines.extend([
        '    ],',
        f'    max_iterations={input_data.max_iterations})',
    ])
    return '\n'.join(lines)


def _format_pre_group_item_for_test(item: GroupedKnapsackPreGroupItem, indent: int) -> list[str]:
    prefix = ' ' * indent
    return [
        f'{prefix}GroupedKnapsackPreGroupItem(',
        f'{prefix}    border_pair={item.border_pair!r},',
        f'{prefix}    external_group_id={item.external_group_id!r},',
        f'{prefix}    is_external={item.is_external!r},',
        f'{prefix}    weight={item.weight!r},',
        f'{prefix}    value={item.value!r},',
        f'{prefix}    econ_value={item.econ_value!r},',
        f'{prefix}    friendly_island_set={item.friendly_island_set!r},',
        f'{prefix}    target_island_set={item.target_island_set!r},',
        f'{prefix}    item_tile_set={item.item_tile_set!r},',
        f'{prefix}    description={item.description!r}),',
    ]
