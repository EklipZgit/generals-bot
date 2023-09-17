from BoardAnalyzer import BoardAnalyzer
from base.client.map import MapBase
from MapMatrix import MapMatrix


class IterativeExpander(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map

    def build_expansion_plan(self, intergeneralAnalysis: BoardAnalyzer, bannedTiles: MapMatrix):
        """
        Build 'gather' tree INTO enemy territory (and/or cleaning up enemy tiles), so we have a plan on what to DO with gathered army.
        Put a cap on the amount of army we want to send down those routes so we don't gather all our army to random places.
        Have the main attack path(s) (@gen, @enemy cities) be an 'infinite' army sink to allow infinite army amounts towards it.
        THEN tweak existing gather to gather towards those target points.
        Have both expansion-plan and gather-plan be pruned simultaneously until we find the 'best' balance of time spent gathering vs expected tiles captured. Somehow factor in time for defending enemy pushes (may need to recalculate this every turn...? Yikes)
        @return:
        """