# from .GatherDebug import *
from .GatherPrune import *
from .NetworkXHelpers import *
from .GatherCapturePlan import *
from .GatherSteiner import *
from .GatherDepthIterative import *
from .GatherMaxIterative import *
from .GatherMaxIterativeSet import *
from .ChatGptDpGather import *
from .GatherUtils import *
from .GathSetPruneReconnect import *
# from .GatherPrizeSteiner import *
# from .KruskalsSpanningGather import *

def cutesy_chatgpt_gather_plan(
        map: MapBase,
        targetTurns: int,
        rootTiles: typing.Set[Tile],
        searchingPlayer: int,
        valueMatrix: MapMatrixInterface[float],
        tilesToInclude: typing.Set[Tile] | None = None,
        negativeTiles: TileSet | None = None,
        viewInfo: ViewInfo | None = None,
) -> GatherCapturePlan:
    val, gathSet = cutesy_chatgpt_gather(
        map,
        targetTurns=targetTurns,
        rootTiles=rootTiles,
        searchingPlayer=searchingPlayer,
        negativeTiles=negativeTiles,
        valueMatrix=valueMatrix,
        tilesToInclude=tilesToInclude,
        viewInfo=viewInfo,
    )

    plan = convert_contiguous_tile_tree_to_gather_capture_plan(
        map,
        rootTiles=rootTiles,
        tiles=gathSet,
        searchingPlayer=searchingPlayer,
        priorityMatrix=valueMatrix,
        negativeTiles=negativeTiles,
        # useTrueValueGathered=useTrueValueGathered,
        # includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        # includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        # pruneToTurns=targetTurns,
        # captures={t for t in gathSet if not map.is_tile_on_team_with(t, general.player)},
        viewInfo=None
    )
    return plan

def cutesy_chatgpt_capture_gather_plan(
        map: MapBase,
        targetTurns: int,
        rootTiles: typing.Set[Tile],
        searchingPlayer: int,
        valueMatrix: MapMatrixInterface[float],
        tilesToInclude: typing.Set[Tile] | None = None,
        negativeTiles: TileSet | None = None,
        viewInfo: ViewInfo | None = None,
) -> GatherCapturePlan:
    val, gathSet = cutesy_chatgpt_gather(
        map,
        targetTurns=targetTurns,
        rootTiles=rootTiles,
        searchingPlayer=searchingPlayer,
        negativeTiles=negativeTiles,
        valueMatrix=valueMatrix,
        tilesToInclude=tilesToInclude,
        viewInfo=viewInfo,
    )

    # nonCaps =

    plan = convert_contiguous_capture_tiles_to_gather_capture_plan(
        map,
        rootTiles=rootTiles,
        tiles=gathSet,
        searchingPlayer=searchingPlayer,
        priorityMatrix=valueMatrix,
        negativeTiles=negativeTiles,
        # useTrueValueGathered=useTrueValueGathered,
        # includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
        # includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
        # pruneToTurns=targetTurns,
        # skipTiles=skipTiles,
        captures={t for t in gathSet if not map.is_tile_on_team_with(t, searchingPlayer)},
        viewInfo=None
    )

    return plan