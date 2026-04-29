from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from Algorithms import TileIsland


class TileIslandFlowRole:
    """
    Precomputed per-island classification used by both NetworkX and PyMaxflow graph builders
    to decide each island's role in the flow graph (neutral sink, edges, etc.).

    Produced by FlowDirectionFinderABC.classify_islands_for_flow; consumed by any concrete
    build_graph_data implementation so that the distance / topology decisions are not
    duplicated.
    """
    __slots__ = (
        'island',
        'is_neutral_sink_with_neut',
        'is_neutral_sink_no_neut',
        'borders_friendly',
        'borders_enemy',
        'are_all_borders_neutral',
    )

    def __init__(
        self,
        island: 'TileIsland',
        is_neutral_sink_with_neut: bool,
        is_neutral_sink_no_neut: bool,
        borders_friendly: bool,
        borders_enemy: bool,
        are_all_borders_neutral: bool,
    ):
        self.island: 'TileIsland' = island
        self.is_neutral_sink_with_neut: bool = is_neutral_sink_with_neut
        """True when use_neutral_flow=True and this island should be routed to the fake sink."""
        self.is_neutral_sink_no_neut: bool = is_neutral_sink_no_neut
        """True when use_neutral_flow=False and this island should be routed to the fake sink."""
        self.borders_friendly: bool = borders_friendly
        self.borders_enemy: bool = borders_enemy
        self.are_all_borders_neutral: bool = are_all_borders_neutral

    @property
    def is_neutral_sink(self, use_neutral_flow: bool) -> bool:
        """Convenience accessor — prefer the explicit fields for performance."""
        return self.is_neutral_sink_with_neut if use_neutral_flow else self.is_neutral_sink_no_neut
