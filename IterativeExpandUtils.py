import typing

from BoardAnalyzer import BoardAnalyzer
from DataModels import GatherTreeNode, Move
from base.client.map import MapBase, Tile
from MapMatrix import MapMatrix


class IterativeExpander(object):
    def __init__(self, map: MapBase, player: int):
        self.map: MapBase = map
        self.player: int = player

    def build_expansion_plan(self, boardAnalysis: BoardAnalyzer, bannedTiles: MapMatrix):
        """
        Build 'gather' tree INTO enemy territory (and/or cleaning up enemy tiles), so we have a plan on what to DO with gathered army.
        Put a cap on the amount of army we want to send down those routes so we don't gather all our army to random places.
        Have the main attack path(s) (@gen, @enemy cities) be an 'infinite' army sink to allow infinite army amounts towards it.
        THEN tweak existing gather to gather towards those target points.
        Have both expansion-plan and gather-plan be pruned simultaneously until we find the 'best' balance of time spent gathering vs expected tiles captured. Somehow factor in time for defending enemy pushes (may need to recalculate this every turn...? Yikes)
        @return:
        """

        # we maintain two lists of things:
        # 1. The expansion leaves that can be branched from by gathering more army to them.
        # 2. The gather tree nodes we've gathered thus far, and link them to their corresponding expansion nodes.
        # 3. A map from expansion leaves to speculative expansion extensions (think, expansion nodes that 'gathered negative' if you will). May be part of the expansion tree nodes?

        turns: int = 0
        gatheredValue: int = 0
        # TODO get this shit from the expansion yellow/pink zones.
        flankCutoff =
        # start with a list of tiles that are boundaries towards enemy flank position. For right now, lets just include all leaf moves that don't have a friendly tile on one of the edges on the shortest path between two players.
        initialGatherTreeNodes: typing.List[GatherTreeNode] = []
        for tile in self.map.get_all_tiles():
            if tile.player == self.player:
                # TODO expand to include speculative shortish distance flank routes that do move away from shortest path but only briefly.
                hasFriendlyAdj = False
                pathway = boardAnalysis.intergeneral_analysis.pathWayLookupMatrix[tile]
                tileDistGen = boardAnalysis.intergeneral_analysis.aMap[tile]
                tileDistEn = boardAnalysis.intergeneral_analysis.bMap[tile]
                bestDestination: Tile | None = None
                foundDirectPathway: bool = False
                for adj in tile.movable:
                    adjDistGen = boardAnalysis.intergeneral_analysis.aMap[adj]
                    if adjDistGen < tileDistGen:
                        # never ever consider anything that moves backwards towards our general.
                        continue

                    adjPathway = boardAnalysis.intergeneral_analysis.pathWayLookupMatrix[adj]
                    adjDistEn = boardAnalysis.intergeneral_analysis.bMap[adj]
                    if adjPathway == pathway:
                        # then moving along shortest path towards enemy because we already eliminated anything moving towards our gen.
                        if adj.player == self.player:
                            # TODO then this is not a tendril expansion border, but might be utilized for tile recapture within our territory...?
                            # skip for now but we'll need to revisit these later.
                            hasFriendlyAdj = True
                            break
                        else:
                            bestDestination = adj
                            foundDirectPathway = True
                    elif not foundDirectPathway and adjPathway.distance > pathway.distance:
                        # then this is moving outwards, possibly towards a flank?
                        if adj.player == self.player:
                            continue

                        if adjDistEn < flankCutoff:
                            bestDestination = adj

                if hasFriendlyAdj:
                    continue

                if len(validDestinations) == 0:
                    continue

                # beep boop add it to the expansion borders
                newNode = GatherTreeNode(tile, fromTile=None, turn=0)
                initialGatherTreeNodes.append(newNode)
                for dest in validDestinations:
                    newChild = GatherTreeNode(dest, fromTile=None, turn=1)
                    newChild.children.append(newNode)
                    newNode.


        # initialBorderMoves: typing.List[GatherTreeNode] = []

        while True:
