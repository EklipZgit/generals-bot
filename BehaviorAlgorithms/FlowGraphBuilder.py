"""
Flow graph builder for NetworkX min-cost flow graphs from island data.
"""
from __future__ import annotations

import typing
import time
import logbook
import networkx as nx

from Algorithms import TileIslandBuilder, TileIsland


class FlowGraphBuilder(object):
    """Builds NetworkX min-cost flow graphs from island data."""
    
    def __init__(self, log_debug: bool = False):
        self.log_debug = log_debug
    
    def build_nx_flow_graph_data(
        self,
        islands: TileIslandBuilder,
        my_team: int,
        target_team: int,
        include_neutral_demand: bool = True
    ) -> 'NxFlowGraphData':
        """
        Build a NetworkX DiGraph for min-cost flow from island data.
        
        @param islands: TileIslandBuilder containing all island data
        @param my_team: Our team ID
        @param target_team: Target (enemy) team ID
        @param include_neutral_demand: Whether to include neutral islands as demand nodes
        @return: NxFlowGraphData containing the graph and metadata
        """
        from BehaviorAlgorithms.IterativeExpansion import NxFlowGraphData
        
        g = nx.DiGraph()
        demands: typing.Dict[int, int] = {}
        neutral_sinks: typing.Set[int] = set()
        fake_nodes: typing.Set[int] = set()
        
        # First pass: create nodes for all islands
        for island in islands.all_tile_islands:
            island_id = island.unique_id
            
            # Calculate demand based on team
            if island.team == my_team:
                # Friendly island: supply (negative demand)
                demand = -(island.sum_army - island.tile_count)
            elif island.team == target_team or (include_neutral_demand and island.team == -1):
                # Enemy or neutral island: demand (positive)
                demand = island.sum_army + island.tile_count
                if island.team == -1:
                    neutral_sinks.add(island_id)
            else:
                # Other teams - no demand/supply
                demand = 0
            
            demands[island_id] = demand
            
            # Add throughput node (negative ID) - input side
            throughput_id = -island_id
            g.add_node(throughput_id, demand=0)
            
            # Add output node (positive ID)
            g.add_node(island_id, demand=demand)
            
            # Add throughput edge: input -> output with large capacity
            throughput_capacity = max(island.sum_army, abs(demand)) + island.tile_count * 10
            g.add_edge(throughput_id, island_id, capacity=throughput_capacity, weight=0)
        
        # Second pass: create edges between bordering islands
        for island in islands.all_tile_islands:
            island_id = island.unique_id
            
            for border_island in island.border_islands:
                border_id = border_island.unique_id
                border_throughput_id = -border_id
                
                # Edge from this island's output to border island's input
                edge_capacity = max(1, island.sum_army - island.tile_count)
                
                # Weight based on target type
                if border_island.team == target_team:
                    weight = 1
                elif border_island.team == -1:
                    weight = 2 if include_neutral_demand else 1000
                else:
                    weight = 1
                
                g.add_edge(island_id, border_throughput_id, capacity=edge_capacity, weight=weight)
        
        # Add fake source/sink nodes to balance the graph if needed
        cumulative_demand = sum(demands.values())
        
        if cumulative_demand < 0:
            # More supply than demand - add fake sink
            fake_sink_id = 999999
            fake_nodes.add(fake_sink_id)
            g.add_node(fake_sink_id, demand=-cumulative_demand)
            for island in islands.all_tile_islands:
                if demands.get(island.unique_id, 0) < 0:
                    g.add_edge(-island.unique_id, fake_sink_id,
                              capacity=abs(demands[island.unique_id]), weight=0)
        elif cumulative_demand > 0:
            # More demand than supply - add fake source
            fake_source_id = -999999
            fake_nodes.add(fake_source_id)
            g.add_node(fake_source_id, demand=-cumulative_demand)
            for island in islands.all_tile_islands:
                if demands.get(island.unique_id, 0) > 0:
                    g.add_edge(fake_source_id, -island.unique_id,
                              capacity=demands[island.unique_id], weight=0)
        
        return NxFlowGraphData(
            graph=g,
            neutSinks=neutral_sinks,
            demands=demands,
            cumulativeDemand=cumulative_demand,
            fakeNodes=fake_nodes
        )
