from __future__ import annotations

import typing

from base.client.tile import Tile

# All of this pulled from https://arxiv.org/abs/2405.03792
def pcst_gw(root: Tile, penalties: typing.Dict[Tile, float]) -> typing.Tuple[typing.Set[Tile], typing.Set[Tile]]:
    def initialize():
        forest = set()
        active_sets = {frozenset([v]) for v in penalties}
        y_s = {s: 0 for s in active_sets}
        return forest, active_sets, y_s

    def find_min_delta(active_sets, forest):
        delta_1 = min(
            (sum(penalties[v] for v in s) - sum(y_s[t] for t in active_sets if t.issubset(s)), s)
            for s in active_sets
        )[0]
        delta_2 = min(
            (1 - sum(y_s[t] for t in active_sets if t.issubset(set([u, v]))), (u, v))
            for (u, v) in edges if (u in active_sets) != (v in active_sets)
        )[0]
        return min(delta_1, delta_2)

    def color_edges_and_update(forest, active_sets, y_s):
        while len(active_sets) > 1:
            delta = find_min_delta(active_sets, forest)
            for s in list(active_sets):
                y_s[s] += delta
                if sum(penalties[v] for v in s) - sum(y_s[t] for t in active_sets if t.issubset(s)) <= 0:
                    active_sets.remove(s)
                    dead_sets.add(s)
            for (u, v) in edges:
                if sum(y_s[t] for t in active_sets if t.issubset({u, v})) >= 1:
                    forest.add((u, v))
                    active_sets = merge_active_sets(active_sets, (u, v))
        return forest

    def prune_tree(forest, dead_sets):
        final_tree = forest.copy()
        for s in dead_sets:
            if len([e for e in final_tree if e.intersection(s)]) == 1:
                final_tree -= s
        return final_tree

    subsets = [frozenset(subset) for subset in powerset(penalties.keys())]
    edges = [(u, v) for u in penalties for v in u.movable if u != v]

    forest, active_sets, y_s = initialize()
    dead_sets = set()
    forest = color_edges_and_update(forest, active_sets, y_s)
    final_tree = prune_tree(forest, dead_sets)

    return final_tree, dead_sets


def merge_active_sets(active_sets, edge):
    u, v = edge
    merged_set = None
    for s in list(active_sets):
        if u in s or v in s:
            if merged_set is None:
                merged_set = s
                active_sets.remove(s)
            else:
                merged_set = merged_set.union(s)
                active_sets.remove(s)
    active_sets.add(merged_set)
    return active_sets


def powerset(iterable):
    from itertools import chain, combinations
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(len(s) + 1))


def iterative_pcst(root: Tile, penalties: typing.Dict[Tile, float], beta: float) -> typing.Set[Tile]:
    def steiner_tree(nodes: typing.Set[Tile]) -> typing.Set[Tile]:
        # Placeholder for a Steiner Tree algorithm
        # For simplicity, we'll use a minimal spanning tree (MST) approximation here.
        return minimum_spanning_tree(nodes)

    def adjust_penalties(dead_nodes):
        for node in dead_nodes:
            penalties[node] = 0

    def recursive_call(nodes: typing.Set[Tile]) -> typing.Set[Tile]:
        if all(penalties[node] == 0 for node in nodes):
            return steiner_tree(nodes)
        else:
            final_tree, dead_nodes = pcst_gw(root, penalties)
            adjust_penalties(dead_nodes)
            return iterative_pcst(root, penalties, beta)

    penalties_beta = {node: penalty / beta for node, penalty in penalties.items()}
    tree_gw, dead_nodes = pcst_gw(root, penalties_beta)
    cost_gw = len(tree_gw) + sum(penalties[v] for v in penalties if v not in tree_gw)

    live_nodes = {v for v in penalties if v not in dead_nodes}
    tree_st = steiner_tree(live_nodes)
    cost_st = len(tree_st) + sum(penalties[v] for v in penalties if v not in tree_st)

    if all(penalties[node] == 0 for node in dead_nodes):
        return min([tree_gw, tree_st], key=lambda t: calculate_cost(t, penalties))
    else:
        adjust_penalties(dead_nodes)
        tree_it = recursive_call(set(penalties.keys()))
        cost_it = len(tree_it) + sum(penalties[v] for v in penalties if v not in tree_it)

        return min([tree_gw, tree_st, tree_it], key=lambda t: calculate_cost(t, penalties))


def calculate_cost(tree: typing.Set[Tile], penalties: typing.Dict[Tile, float]) -> float:
    return len(tree) + sum(penalties[node] for node in penalties if node not in tree)


def minimum_spanning_tree(nodes: typing.Set[Tile]) -> typing.Set[Tile]:
    # A simple placeholder for the MST approximation.
    return nodes  # In reality, use an MST algorithm like Kruskal's or Prim's.