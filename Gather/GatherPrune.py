import time
import typing
from collections import deque

import logbook

import SearchUtils
from Models import GatherTreeNode, Move
from Gather import GatherDebug
from ViewInfo import ViewInfo
from base.client.tile import Tile


def get_tree_moves(
        gathers: typing.List[GatherTreeNode],
        valueFunc: typing.Callable[[Tile, typing.Tuple | None], typing.Tuple | None],
        limit: int = 10000,
        pop: bool = False
) -> typing.List[Move]:
    if len(gathers) == 0:
        logbook.info("get_tree_moves... len(gathers) == 0?")
        return []

    q = deque()

    if not pop:
        gathers = [g.deep_clone() for g in gathers]

    for gather in gathers:
        basePrio = valueFunc(gather.tile, None)
        q.append((basePrio, gather))

    moveQ = SearchUtils.HeapQueueMax()

    prioLookup = {}
    """Looks up each nodes priority by its tile."""

    while q:
        (curPrio, curGather) = q.popleft()
        prioLookup[curGather.tile] = curPrio

        if not curGather.children:
            moveQ.put((curPrio, curGather))
        else:
            for gather in curGather.children:
                gather.toGather = curGather
                nextPrio = valueFunc(gather.tile, curPrio)
                q.append((nextPrio, gather))

    moves = []
    iter = 0
    while moveQ.queue:
        (curPrio, curGather) = moveQ.get()
        toGather = curGather.toGather
        if toGather is not None:
            moves.append(Move(curGather.tile, curGather.toTile))
            toGather.children.remove(curGather)
            iter += 1
            if iter >= limit:
                break

            if not toGather.children:
                fromPrio = prioLookup.get(toGather.toTile, None)
                curPrio = valueFunc(toGather.tile, fromPrio)
                moveQ.put((curPrio, toGather))

    return moves


def get_tree_move(
        gathers: typing.List[GatherTreeNode],
        valueFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None],
        pop: bool = False
) -> typing.Union[None, Move]:
    moves = get_tree_moves(gathers, valueFunc, pop=pop, limit=1)
    if moves:
        return moves[0]
    return None
    # if len(gathers) == 0:
    #     logbook.info("get_tree_move... len(gathers) == 0?")
    #     return None
    #
    # # TODO this is just an iterate-all-leaves-and-keep-max function, why the hell are we using a priority queue?
    # #  we don't call this often so who cares I guess, but wtf copy paste, normal queue would do fine.
    # q = SearchUtils.HeapQueue()
    #
    # for gather in gathers:
    #     basePrio = priorityFunc(gather.tile, None)
    #     q.put((basePrio, gather))
    #
    # lookup = {}
    #
    # highestValue = None
    # highestValueNode = None
    # while q.queue:
    #     (curPrio, curGather) = q.get()
    #     lookup[curGather.tile] = curGather
    #     if len(curGather.children) == 0:
    #         # WE FOUND OUR FIRST MOVE!
    #         thisValue = valueFunc(curGather.tile, curPrio)
    #         if (thisValue is not None
    #                 and curGather.fromTile is not None
    #                 and (highestValue is None or thisValue > highestValue)
    #         ):
    #             highestValue = thisValue
    #             highestValueNode = curGather
    #             logbook.info(f"new highestValueNode {str(highestValueNode)}!")
    #     for gather in curGather.children:
    #         nextPrio = priorityFunc(gather.tile, curPrio)
    #         q.put((nextPrio, gather))
    #
    # if highestValueNode is None:
    #     return None
    #
    # if pop:
    #     if highestValueNode.fromTile is not None:
    #         parent = lookup[highestValueNode.fromTile]
    #         parent.children.remove(highestValueNode)
    #
    # highestValueMove = Move(highestValueNode.tile, highestValueNode.fromTile)
    # logbook.info(f"highestValueMove in get_tree_move was {highestValueMove.toString()}!")
    # return highestValueMove


def prune_mst_to_turns(
        rootNodes: typing.List[GatherTreeNode],
        turns: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
) -> typing.List[GatherTreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param turns: The number of turns to prune the MST down to.
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.

    @return: The list same list of rootnodes passed in, modified.
    """
    count, totalValue, rootNodes = prune_mst_to_turns_with_values(
        rootNodes=rootNodes,
        turns=turns,
        searchingPlayer=searchingPlayer,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        invalidMoveFunc=invalidMoveFunc,
    )

    return rootNodes


def prune_mst_to_turns_with_values(
        rootNodes: typing.List[GatherTreeNode],
        turns: int,
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
        allowNegative: bool = True,
        logEntries: typing.List[str] | None = None,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
    TODO optimize to reuse existing GatherTreeNode lookup map instead of rebuilding...?
     MAKE A GATHER CLASS THAT STORES THE ROOT NODES, THE NODE LOOKUP, THE VALUE, THE TURNS

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param turns: The number of turns to prune the MST down to.
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    if logEntries is None:
        logEntries = []

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.tile.army <= 1:
                return True
            if node.tile.player != searchingPlayer and len(node.children) == 0:
                return True

        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def pruneFunc(node: GatherTreeNode, curPrioObj: typing.Tuple | None):
        rawValPerTurn = -100
        # trunkValPerTurn = -100
        # trunkBehindNodeValuePerTurn = -100
        if node.gatherTurns > 0:
            rawValPerTurn = node.value / node.gatherTurns
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkBehindNodeValuePerTurn = trunkValPerTurn
            # trunkBehindNodeValue = node.trunkValue - node.value
            # trunkBehindNodeValuePerTurn = trunkBehindNodeValue / node.trunkDistance
        elif node.value > 0:
            if GatherDebug.USE_DEBUG_ASSERTS:
                raise AssertionError(f'divide by zero exception for {str(node)} with value {round(node.value, 6)} turns {node.gatherTurns}')
        if viewInfo is not None:
            viewInfo.midRightGridText[node.tile] = f'v{node.value:.0f}'
            viewInfo.bottomMidRightGridText[node.tile] = f'tv{node.trunkValue:.0f}'
            viewInfo.bottomRightGridText[node.tile] = f'td{node.trunkDistance}'

            # viewInfo.bottomMidLeftGridText[node.tile] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[node.tile] = f'vt{rawValPerTurn:.1f}'

        return rawValPerTurn, node.value, 0 - node.trunkDistance

    return prune_mst_until(
        rootNodes,
        untilFunc=lambda node, _, turnsLeft, curValue: turnsLeft <= turns,
        pruneOrderFunc=pruneFunc,
        invalidMoveFunc=invalidMoveFunc,
        pruneOverrideFunc=lambda node, _, turnsLeft, curValue: turnsLeft - node.gatherTurns < turns,
        viewInfo=viewInfo,
        noLog=noLog,
        pruneBranches=True,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        preferPrune=preferPrune,
        logEntries=logEntries,
        allowNegative=allowNegative,
        parentPruneFunc=parentPruneFunc,
    )


def prune_mst_to_tiles(
        rootNodes: typing.List[GatherTreeNode],
        tiles: typing.Set[Tile],
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
) -> typing.List[GatherTreeNode]:
    """
    Prunes nodes from an MST until a set of specific nodes are encountered. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param tiles: The tiles that should be force-kept within the spanning tree
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.

    @return: The list same list of rootnodes passed in, modified.
    """
    count, totalValue, rootNodes = prune_mst_to_tiles_with_values(
        rootNodes=rootNodes,
        tiles=tiles,
        searchingPlayer=searchingPlayer,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        preferPrune=preferPrune,
        invalidMoveFunc=invalidMoveFunc,
    )

    return rootNodes


def prune_mst_to_tiles_with_values(
        rootNodes: typing.List[GatherTreeNode],
        tiles: typing.Set[Tile],
        searchingPlayer: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes nodes from an MST until a set of specific nodes are encountered. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).
    TODO optimize to reuse existing GatherTreeNode lookup map instead of rebuilding...?
     MAKE A GATHER CLASS THAT STORES THE ROOT NODES, THE NODE LOOKUP, THE VALUE, THE TURNS

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param tiles: The tiles that should be force-kept within the spanning tree
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.tile.army <= 1:
                return True
            if node.tile.player != searchingPlayer and len(node.children) == 0:
                return True

        invalidMoveFunc = invalid_move_func

    # count, nodeMap = calculate_mst_trunk_values_and_build_leaf_queue_and_node_map(rootNodes, searchingPlayer, invalidMoveFunc, viewInfo=viewInfo, noLog=noLog)

    def pruneFunc(node: GatherTreeNode, curPrioObj: typing.Tuple | None):
        rawValPerTurn = -100
        # trunkValPerTurn = -100
        # trunkBehindNodeValuePerTurn = -100
        if node.gatherTurns > 0:
            rawValPerTurn = node.value / node.gatherTurns
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkValPerTurn = node.trunkValue / node.trunkDistance
            # trunkBehindNodeValuePerTurn = trunkValPerTurn
            # trunkBehindNodeValue = node.trunkValue - node.value
            # trunkBehindNodeValuePerTurn = trunkBehindNodeValue / node.trunkDistance
        elif node.value > 0:
            if GatherDebug.USE_DEBUG_ASSERTS:
                raise AssertionError(f'divide by zero exception for {str(node)} with value {round(node.value, 6)} turns {node.gatherTurns}')

        if viewInfo is not None:
            viewInfo.midRightGridText[node.tile] = f'v{node.value:.1f}'
            viewInfo.bottomMidRightGridText[node.tile] = f'tv{node.trunkValue:.1f}'
            viewInfo.bottomRightGridText[node.tile] = f'td{node.trunkDistance}'

            # viewInfo.bottomMidLeftGridText[node.tile] = f'tt{trunkValPerTurn:.1f}'
            viewInfo.bottomLeftGridText[node.tile] = f'vt{rawValPerTurn:.1f}'

        return rawValPerTurn, node.value, 0 - node.trunkDistance

    return prune_mst_until(
        rootNodes,
        untilFunc=lambda node, _, turnsLeft, curValue: node.tile in tiles,
        pruneOrderFunc=pruneFunc,
        invalidMoveFunc=invalidMoveFunc,
        pruneOverrideFunc=lambda node, _, turnsLeft, curValue: node.tile in tiles,
        viewInfo=viewInfo,
        noLog=noLog,
        pruneBranches=False,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        tileDictToPrune=tileDictToPrune,
        preferPrune=preferPrune,
        parentPruneFunc=parentPruneFunc,
    )


def prune_mst_to_army_with_values(
        rootNodes: typing.List[GatherTreeNode],
        army: int,
        searchingPlayer: int,
        teams: typing.List[int],
        turn: int,
        additionalIncrement: int = 0,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
        pruneLargeTilesFirst: bool = False,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param army: The army amount to prune the MST down to
    @param searchingPlayer:
    @param teams: the teams array.
    @param additionalIncrement: if need to gather extra army due to incrementing, include the POSITIVE enemy city increment or NEGATIVE allied increment value here.
    @param turn: the current map turn, used to calculate city increment values.
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param pruneLargeTilesFirst: if True (emptyVal), then largest tiles will be pruned first allowing this prune to be used to maximize leaving tiles for offense if possible.

    @return: gatherTurns, gatherValue, rootNodes
    """
    start = time.perf_counter()

    turnIncFactor = (1 + turn) & 1

    cityCounter = SearchUtils.Counter(0 - additionalIncrement)
    cityGatherDepthCounter = SearchUtils.Counter(0)
    citySkipTiles = set()
    for n in rootNodes:
        if (n.tile.isCity or n.tile.isGeneral) and not n.tile.isNeutral:
            if teams[n.tile.player] == [searchingPlayer]:
                citySkipTiles.add(n.tile)

    def cityCounterFunc(node: GatherTreeNode):
        if (node.tile.isGeneral or node.tile.isCity) and not node.tile.isNeutral and node.tile not in citySkipTiles:
            if teams[node.tile.player] == teams[searchingPlayer]:
                cityCounter.add(1)
                # each time we add one of these we must gather all the other cities in the tree first too so we lose that many increment turns + that
                cityGatherDepthCounter.add(node.trunkDistance)
            else:
                cityCounter.add(-1)

        for child in node.children:
            cityCounterFunc(child)

    for n in rootNodes:
        cityCounterFunc(n)

    def setCountersToPruneCitiesRecurse(node: GatherTreeNode):
        for child in node.children:
            setCountersToPruneCitiesRecurse(child)

        if teams[node.tile.player] == teams[searchingPlayer] and (node.tile.isCity or node.tile.isGeneral):
            cityGatherDepthCounter.add(0 - node.trunkDistance)
            cityCounter.add(-1)

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.tile.army <= 1:
                return True
            if node.tile.player != searchingPlayer:
                return True

        invalidMoveFunc = invalid_move_func

    def getCurrentCityIncAmount(gatherTurnsLeft: int) -> int:
        cityIncrementAmount = (cityCounter.value * (gatherTurnsLeft - turnIncFactor)) // 2  # +1 here definitely causes it to under-gather
        cityIncrementAmount -= cityGatherDepthCounter.value // 2
        return cityIncrementAmount

    def untilFunc(node: GatherTreeNode, _, turnsLeft: int, curValue: int):
        turnsLeftIfPruned = turnsLeft - node.gatherTurns

        # act as though we're pruning the city so we can calculate the gather value without it
        setCountersToPruneCitiesRecurse(node)

        cityIncrementAmount = getCurrentCityIncAmount(turnsLeftIfPruned)
        armyLeftIfPruned = curValue - node.value + cityIncrementAmount

        if armyLeftIfPruned < army:
            # not pruning here, put the city increments back
            cityCounterFunc(node)
            return True

        return False

    def pruneLargeTilesFirstFunc(node: GatherTreeNode, curObj) -> typing.Tuple:
        trunkValuePerTurn = node.trunkValue / node.trunkDistance if node.trunkDistance > 0 else 0
        return 0 - node.value, trunkValuePerTurn, node.trunkDistance

    def pruneWorstValuePerTurnFunc(node: GatherTreeNode, curObj) -> typing.Tuple:
        trunkValuePerTurn = node.trunkValue / node.trunkDistance if node.trunkDistance > 0 else 0
        return node.value / node.gatherTurns, trunkValuePerTurn, node.trunkDistance

    prioFunc = pruneLargeTilesFirstFunc
    if not pruneLargeTilesFirst:
        prioFunc = pruneWorstValuePerTurnFunc

    prunedTurns, noCityCalcGathValue, nodes = prune_mst_until(
        rootNodes,
        untilFunc=untilFunc,
        # if we dont include trunkVal/node.trunkDistance we end up keeping shitty branches just because they have a far, large tile on the end.
        pruneOrderFunc=prioFunc,
        # pruneOrderFunc=lambda node, curObj: (node.value, node.trunkValue / node.trunkDistance, node.trunkDistance),
        # pruneOrderFunc=lambda node, curObj: (node.value / node.gatherTurns, node.trunkValue / node.trunkDistance, node.trunkDistance),
        invalidMoveFunc=invalidMoveFunc,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        pruneBranches=False  # if you turn this to true, test_should_not_miscount_gather_prune_at_neut_city will fail. Need to fix how mid-branch city prunes function apparently.
    )

    finalIncValue = getCurrentCityIncAmount(prunedTurns)
    gathValue = noCityCalcGathValue + finalIncValue

    return prunedTurns, gathValue, nodes


def prune_mst_to_army(
        rootNodes: typing.List[GatherTreeNode],
        army: int,
        searchingPlayer: int,
        teams: typing.List[int],
        turn: int,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
        pruneLargeTilesFirst: bool = False,
) -> typing.List[GatherTreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param army: The army amount to prune the MST down to
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param pruneLargeTilesFirst: if True, will try to prune the largest tiles out first instead of lowest value per turn.
    Useful when pruning a defense to the minimal army set needed for example while leaving large tiles available for other things.

    @return: gatherTurns, gatherValue, rootNodes
    """

    count, totalValue, rootNodes = prune_mst_to_army_with_values(
        rootNodes=rootNodes,
        army=army,
        searchingPlayer=searchingPlayer,
        teams=teams,
        turn=turn,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        invalidMoveFunc=invalidMoveFunc,
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        pruneLargeTilesFirst=pruneLargeTilesFirst,
    )

    return rootNodes


def prune_mst_to_max_army_per_turn_with_values(
        rootNodes: typing.List[GatherTreeNode],
        minArmy: int,
        searchingPlayer: int,
        teams: typing.List[int],
        additionalIncrement: int = 0,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
        allowBranchPrune: bool = True,
        minTurns: int = 0,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param minArmy: The minimum army amount to prune the MST down to.
    @param searchingPlayer:
    @param teams: the teams array to use when calculating whether a gathered tile adds or subtracts army.
    @param additionalIncrement: if need to gather extra army due to incrementing, include the POSITIVE enemy city increment or NEGATIVE allied increment value here.
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param allowBranchPrune: Optionally, pass false to disable pruning whole branches. Allowing branch prunes produces lower value per turn trees but also smaller trees.
    @param minTurns: The minimum number of turns that can be pruned to.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified)
    """

    cityCounter = SearchUtils.Counter(0 - additionalIncrement)
    cityGatherDepthCounter = SearchUtils.Counter(0)
    citySkipTiles = set()
    totalValue = 0
    totalTurns = 0
    for n in rootNodes:
        if (n.tile.isCity or n.tile.isGeneral) and not n.tile.isNeutral:
            if teams[n.tile.player] == teams[searchingPlayer]:
                citySkipTiles.add(n.tile)

        totalTurns += n.gatherTurns
        totalValue += n.value

    if totalTurns == 0:
        return 0, 0, rootNodes

    if totalValue < minArmy:
        return totalTurns, totalValue, rootNodes

    def cityCounterFunc(node: GatherTreeNode):
        if (node.tile.isGeneral or node.tile.isCity) and not node.tile.isNeutral and node.tile not in citySkipTiles:
            if teams[node.tile.player] == teams[searchingPlayer]:
                cityCounter.add(1)
                # each time we add one of these we must gather all the other cities in the tree first too so we lose that many increment turns + that
                cityGatherDepthCounter.add(node.trunkDistance)
            else:
                cityCounter.add(-1)

    GatherTreeNode.foreach_tree_node(rootNodes, cityCounterFunc)

    if invalidMoveFunc is None:
        def invalid_move_func(node: GatherTreeNode):
            if node.tile.army <= 1:
                return True
            if node.tile.player != searchingPlayer:
                return True

        invalidMoveFunc = invalid_move_func

    curValuePerTurn = SearchUtils.Counter(totalValue / totalTurns)

    def untilFunc(node: GatherTreeNode, _, turnsLeft: int, curValue: int):
        turnsLeftIfPruned = turnsLeft - node.gatherTurns
        if turnsLeftIfPruned <= minTurns:
            return True
        cityIncrementAmount = cityCounter.value * ((turnsLeftIfPruned - 1) // 2)
        cityIncrementAmount -= cityGatherDepthCounter.value // 2
        armyLeftIfPruned = curValue - node.value + cityIncrementAmount
        pruneValPerTurn = armyLeftIfPruned / turnsLeftIfPruned
        if pruneValPerTurn < curValuePerTurn.value or armyLeftIfPruned < minArmy:
            return True

        if teams[node.tile.player] == teams[searchingPlayer] and (node.tile.isCity or node.tile.isGeneral):
            cityGatherDepthCounter.add(0 - node.trunkDistance)
            cityCounter.add(-1)

        curValuePerTurn.value = pruneValPerTurn
        return False

    def pruneOrderFunc(node: GatherTreeNode, curObj):
        if node.gatherTurns == 0 or node.trunkDistance == 0:
            if node.toTile is not None:
                msg = f'ERRPRUNE {repr(node)} td {node.trunkDistance} or gathTurns {node.gatherTurns}'
                logbook.info(msg)
                if viewInfo:
                    viewInfo.add_info_line(msg)
                if GatherDebug.USE_DEBUG_ASSERTS:
                    raise AssertionError(msg)
            return -1, -1, -1
        return (node.value / node.gatherTurns), node.trunkValue / node.trunkDistance, node.trunkDistance

    return prune_mst_until(
        rootNodes,
        untilFunc=untilFunc,
        # if we dont include trunkVal/node.trunkDistance we end up keeping shitty branches just because they have a far, large tile on the end.
        pruneOrderFunc=pruneOrderFunc,
        # pruneOrderFunc=lambda node, curObj: (node.value, node.trunkValue / node.trunkDistance, node.trunkDistance),
        # pruneOrderFunc=lambda node, curObj: (node.value / node.gatherTurns, node.trunkValue / node.trunkDistance, node.trunkDistance),
        invalidMoveFunc=invalidMoveFunc,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        pruneBranches=allowBranchPrune
    )


def prune_mst_to_max_army_per_turn(
        rootNodes: typing.List[GatherTreeNode],
        minArmy: int,
        searchingPlayer: int,
        teams: typing.List[int],
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        allowNegative: bool = True,
        allowBranchPrune: bool = True
) -> typing.List[GatherTreeNode]:
    """
    Prunes bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param minArmy: The minimum army amount to prune the MST down to
    @param searchingPlayer:
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param allowBranchPrune: Optionally, pass false to disable pruning whole branches.
    Allowing branch prunes produces lower value per turn trees but also smaller trees.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified).
    """

    count, totalValue, rootNodes = prune_mst_to_max_army_per_turn_with_values(
        rootNodes=rootNodes,
        minArmy=minArmy,
        searchingPlayer=searchingPlayer,
        teams=teams,
        viewInfo=viewInfo,
        noLog=noLog,
        gatherTreeNodeLookupToPrune=gatherTreeNodeLookupToPrune,
        invalidMoveFunc=invalidMoveFunc,
        preferPrune=preferPrune,
        allowNegative=allowNegative,
        allowBranchPrune=allowBranchPrune
    )

    return rootNodes


def _would_prune_cause_negative_root(current: GatherTreeNode, nodeMap: typing.Dict[Tile, GatherTreeNode], logEntries: typing.List[str]):
    parent: GatherTreeNode | None = nodeMap.get(current.toTile, None)
    nextParent = parent

    while nextParent is not None:
        parent = nextParent
        nextParent = nodeMap.get(nextParent.toTile, None)

    if logEntries:
        logEntries.append(f'neg root? parent {parent.tile} <- current {current.tile} | parent.value {parent.value:.2f} - current.value {current.value:.2f} = {parent.value - current.value:.2f}')
    if parent.value - current.value < 0:
        return True

    return False


# TODO can implement prune as multiple choice knapsack, optimizing lowest weight combinations of tree prunes instead of highest weight, maybe?
def prune_mst_until(
        rootNodes: typing.List[GatherTreeNode],
        untilFunc: typing.Callable[[GatherTreeNode, typing.Tuple, int, int], bool],
        pruneOrderFunc: typing.Callable[[GatherTreeNode, typing.Tuple | None], typing.Tuple],
        invalidMoveFunc: typing.Callable[[GatherTreeNode], bool],
        pruneBranches: bool = False,
        pruneOverrideFunc: typing.Callable[[GatherTreeNode, typing.Tuple, int, int], bool] | None = None,
        viewInfo: ViewInfo | None = None,
        noLog: bool = True,
        gatherTreeNodeLookupToPrune: typing.Dict[Tile, typing.Any] | None = None,
        tileDictToPrune: typing.Dict[Tile, typing.Any] | None = None,
        preferPrune: typing.Set[Tile] | None = None,
        parentPruneFunc: typing.Callable[[Tile, GatherTreeNode], None] | None = None,
        allowNegative: bool = True,
        logEntries: typing.List[str] | None = None,
) -> typing.Tuple[int, int, typing.List[GatherTreeNode]]:
    """
    Prunes excess / bad nodes from an MST. Does NOT prune empty 'root' nodes (nodes where fromTile is none).
    O(n*log(n)) (builds lookup dict of whole tree, puts at most whole tree through multiple queues, bubbles up prunes through the height of the tree (where the log(n) comes from).

    @param rootNodes: The MST to prune. These are NOT copied and WILL be modified.
    @param untilFunc: Func[curNode, curPriorityObject, GatherTreeNodeCountRemaining, curValue] -> bool (should return False to continue pruning, True to return the tree).
    @param pruneOrderFunc: Func[curNode, curPriorityObject] - min are pruned first
    @param pruneBranches: If true, runs the prune func to prioritize nodes in the middle of the tree, not just leaves.
    @param pruneOverrideFunc: Func[curNode, curPriorityObject, GatherTreeNodeCountRemaining, curValue] -> bool
    If passed, a node popped from the queue will run through this function and if the function returns true, will NOT be pruned.
    @param viewInfo:
    @param noLog:
    @param gatherTreeNodeLookupToPrune: Optionally, also prune tiles out of this dictionary when pruning the tree nodes, if provided.
    @param tileDictToPrune: Optionally, also prune tiles out of this dictionary
    @param invalidMoveFunc: func(GatherTreeNode) -> bool, return true if you want a leaf GatherTreeNode to always be pruned. By emptyVal, if none is passed, then gather nodes that begin at an enemy tile or that are 1's will always be pruned as invalid.
    @param parentPruneFunc: func(Tile, GatherTreeNode) When a node is pruned this function will be called for each parent tile above the node being pruned and passed the node being pruned.

    @return: (totalCount, totalValue, The list same list of rootnodes passed in, modified).
    """
    start = time.perf_counter()

    nodeMap: typing.Dict[Tile, GatherTreeNode] = {}
    pruneHeap = SearchUtils.HeapQueue()

    logEnd = False
    if logEntries is None:
        logEntries = []
        logEnd = True

    iter = 0

    def nodeInitializer(current: GatherTreeNode):
        nodeMap[current.tile] = current
        if current.toTile is not None and (len(current.children) == 0 or pruneBranches):
            # then we're a leaf. Add to heap
            # value = current.trunkValue / max(1, current.trunkDistance)
            value = current.value
            validMove = True
            if invalidMoveFunc(current) and len(current.children) == 0:
                if not noLog:
                    logEntries.append(
                        f"tile {current.tile.toString()} will be eliminated due to invalid move, army {current.tile.army}")
                validMove = False
            if not noLog:
                logEntries.append(
                    f"  tile {current.tile.toString()} had value {value:.1f}, trunkDistance {current.trunkDistance}")
            pruneHeap.put((validMove, preferPrune is None or current.tile not in preferPrune, pruneOrderFunc(current, None), current))

    GatherTreeNode.foreach_tree_node(rootNodes, nodeInitializer)

    curValue = 0
    for node in rootNodes:
        curValue += node.value

    count = len(nodeMap) - len(rootNodes)
    if not noLog:
        logEntries.append(f'MST prune beginning with {count} nodes ({len(pruneHeap.queue)} nodes)')

    childRecurseQueue: typing.Deque[GatherTreeNode] = deque()

    initialCount = len(nodeMap)

    current: GatherTreeNode
    try:
        # now we have all the leaves, smallest value first
        while pruneHeap.queue:
            validMove, isPreferPrune, prioObj, current = pruneHeap.get()
            iter += 1
            if iter > initialCount * 3:
                logEntries.append("PRUNE WENT INFINITE, BREAKING")
                if viewInfo is not None:
                    viewInfo.add_info_line('ERR PRUNE WENT INFINITE!!!!!!!!!')
                    viewInfo.add_info_line('ERR PRUNE WENT INFINITE!!!!!!!!!')
                    viewInfo.add_info_line('ERR PRUNE WENT INFINITE!!!!!!!!!')
                break

            if current.toTile is None:
                continue

            if current.tile not in nodeMap:
                # already pruned
                continue
            # have to recheck now that we're pruning mid branches
            validMove = not invalidMoveFunc(current)
            if validMove or len(current.children) > 0:
                if untilFunc(current, prioObj, count, curValue):
                    # Then this was a valid move, and we've pruned enough leaves out.
                    # Thus we should break. Otherwise if validMove == 0, we want to keep popping invalid moves off until they're valid again.
                    continue
            elif not noLog:
                logEntries.append(f'Intending to prune extra invalid tree node regardless of untilFunc: {str(current)}')

            if pruneOverrideFunc is not None and pruneOverrideFunc(current, prioObj, count, curValue):
                if not noLog:
                    logEntries.append(f'SKIPPING pruning tree node {str(current)} due to pruneOverrideFunc')
                continue

            if not allowNegative and _would_prune_cause_negative_root(current, nodeMap, logEntries if not noLog else None):
                if not noLog:
                    logEntries.append(f'SKIPPING pruning tree node {str(current)} because would cause negative node')
                continue

            # make sure the value of this prune didn't go down, if it did, shuffle it back into the heap with new priority.
            if validMove:
                doubleCheckPrioObj = pruneOrderFunc(current, prioObj)
                if doubleCheckPrioObj > prioObj:
                    pruneHeap.put((validMove, preferPrune is None or current.tile not in preferPrune, doubleCheckPrioObj, current))
                    if not noLog:
                        logEntries.append(
                            f'requeued {str(current)} (prio went from {str(prioObj)} to {str(doubleCheckPrioObj)})')
                    continue

            if not noLog:
                logEntries.append(f'pruning tree node {str(current)}')

            # now remove this leaf from its parent and bubble the value change all the way up
            curValue -= current.value
            parent: GatherTreeNode | None = nodeMap.get(current.toTile, None)
            realParent: GatherTreeNode | None = parent

            if parent is not None:
                try:
                    parent.children.remove(current)
                except ValueError:
                    logEntries.append(f'child {str(current)} already not present on {str(parent)}')
                    if GatherDebug.USE_DEBUG_ASSERTS:
                        raise AssertionError(f'child {str(current)} already not present on {str(parent)}')
                parent.pruned.append(current)

            while parent is not None:
                parent.value -= current.value
                parent.gatherTurns -= current.gatherTurns
                if parentPruneFunc is not None:
                    parentPruneFunc(parent.tile, current)
                if parent.toTile is None:
                    break
                parent = nodeMap.get(parent.toTile, None)

            childRecurseQueue.append(current)
            childIter = 0
            while childRecurseQueue:
                toDropFromLookup = childRecurseQueue.popleft()
                childIter += 1
                if childIter > initialCount * 3:
                    logEntries.append("PRUNE CHILD WENT INFINITE, BREAKING")
                    if viewInfo is not None:
                        viewInfo.add_info_line('ERR PRUNE CHILD WENT INFINITE!!!!!!!!!')
                    if GatherDebug.USE_DEBUG_ASSERTS:
                        queueStr = '\r\n'.join([str(i) for i in childRecurseQueue])
                        raise AssertionError(f"PRUNE CHILD WENT INFINITE, BREAKING, {str(toDropFromLookup)}. QUEUE:\r\n{queueStr}")
                    break

                if gatherTreeNodeLookupToPrune is not None:
                    gatherTreeNodeLookupToPrune.pop(toDropFromLookup.tile, None)
                if tileDictToPrune is not None:
                    tileDictToPrune.pop(toDropFromLookup.tile, None)
                nodeMap.pop(toDropFromLookup.tile, None)
                count -= 1
                if not noLog:
                    logEntries.append(
                        f"    popped/pruned BRANCH CHILD {toDropFromLookup.tile.toString()} value {toDropFromLookup.value:.1f} count {count}")
                for child in toDropFromLookup.children:
                    childRecurseQueue.append(child)

            if not noLog:
                logEntries.append(f"    popped/pruned {current.tile.toString()} value {current.value:.1f} count {count}")

            if realParent is not None and len(realParent.children) == 0 and realParent.toTile is not None:
                # (value, length) = self.get_prune_point(nodeMap, realParent)
                # value = realParent.trunkValue / max(1, realParent.trunkDistance)
                value = realParent.value
                parentValidMove = True
                if invalidMoveFunc(realParent):
                    if not noLog:
                        logEntries.append(
                            f"parent {str(realParent.tile)} will be eliminated due to invalid move, army {realParent.tile.army}")
                    parentValidMove = False

                if not noLog:
                    logEntries.append(
                        f"  Appending parent {str(realParent.tile)} (valid {parentValidMove}) had value {value:.1f}, trunkDistance {realParent.trunkDistance}")

                nextPrioObj = pruneOrderFunc(realParent, prioObj)
                pruneHeap.put((parentValidMove, preferPrune is None or realParent.tile not in preferPrune, nextPrioObj, realParent))

    except Exception as ex:
        logEntries.append('prune got an error, dumping state:')

        logEntries.append(f'rootNodes: {repr(rootNodes)}')
        # logEntries.append(f'untilFunc: {repr(untilFunc)}')
        # logEntries.append(f'pruneOrderFunc: {repr(pruneOrderFunc)}')
        # logEntries.append(f'invalidMoveFunc: {repr(invalidMoveFunc)}')
        logEntries.append(f'pruneBranches: {repr(pruneBranches)}')
        # logEntries.append(f'pruneOverrideFunc: {repr(pruneOverrideFunc)}')
        # logEntries.append(f'viewInfo: {repr(viewInfo)}')
        # logEntries.append(f'noLog: {repr(noLog)}')
        logEntries.append(f'gatherTreeNodeLookupToPrune: {repr(gatherTreeNodeLookupToPrune)}')
        logEntries.append(f'tileDictToPrune: {repr(tileDictToPrune)}')
        if logEnd:
            _dump_log_entries(logEntries)
        raise

    # while not leaves.empty():
    totalValue = 0
    for node in rootNodes:
        # the root tree nodes need + 1 to their value
        # node.value += 1
        totalValue += node.value
    if not noLog:
        logEntries.append(
            f"  Pruned MST to turns {count} with value {totalValue} in duration {time.perf_counter() - start:.4f}")

        if logEnd:
            _dump_log_entries(logEntries)

    return count, totalValue, rootNodes


def _dump_log_entries(logEntries: typing.List[str]):
    logbook.info('\r\n' + '\r\n'.join(logEntries))