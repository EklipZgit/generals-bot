from __future__ import annotations

import typing

import networkx as nx


class NxFlowGraphData(object):
    def __init__(self, graph: nx.DiGraph, neutSinks: typing.Set[int], demands: typing.Dict[int, int], cumulativeDemand: int, fakeNodes: typing.Set[int] | None = None):
        self.graph: nx.DiGraph = graph

        self.neutral_sinks: typing.Set[int] = neutSinks
        """The set of neutral-sink TileIsland unique_ids used in this graph. This is the set of all outskirt neutral tile islands who the enemy generals overflow was allowed to help fill with zero cost."""

        self.demand_lookup: typing.Dict[int, int] = demands
        """Demand amount lookup by island unique_id. Negative demand = want to gather army, positive = want to capture with army"""

        self.cumulative_demand: int = cumulativeDemand
        """The cumulative demand (prior to adjusting the nxGraph by making enemy general / cities as graph balancing sinks). If negative, then we do not have enough standing army to fully flow the entire map (or the part this graph covers) by the negative amount of army."""

        self.fake_nodes: typing.Set[int] = fakeNodes
        if fakeNodes is None:
            self.fake_nodes = frozenset()

        self.friendly_army_supply: int = 0
        """Total gatherable army from friendly islands (positive value: sum_army - tile_count per friendly island)."""

        self.enemy_army_demand: int = 0
        """Total army required to capture all enemy islands (positive value: sum_army + tile_count per enemy island)."""

        self.enemy_general_demand: int = 0
        """The demand placed on the enemy general island specifically (sum_army + tile_count). Positive."""
