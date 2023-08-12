import logging
import time
import typing
from collections import deque

from DataModels import Move
from Path import Path
from SearchUtils import breadth_first_foreach, count, solve_knapsack, build_distance_map, where, \
    breadth_first_dynamic_max
from ViewInfo import PathColorer, ViewInfo
from base.client.map import Tile, MapBase, MapMatrix


# attempt to get this to a* able?
def get_optimal_expansion(
        map: MapBase,
        searchingPlayer: int,
        targetPlayer: int,
        turns: int,
        enemyDistMap: typing.List[typing.List[int]],
        generalDistMap: typing.List[typing.List[int]],
        territoryMap: typing.List[typing.List[int]],
        innerChokes: typing.List[typing.List[bool]],
        pathChokes: typing.Set[Tile],
        negativeTiles: typing.Set[Tile] = None,
        leafMoves: typing.Union[None, typing.List[Move]] = None,
        viewInfo: ViewInfo = None,
        valueFunc = None,
        priorityFunc = None,
        initFunc = None,
        skipFunc = None,
        boundFunc = None,
        allowLeafMoves = True,
        calculateTrimmable = True) -> typing.Union[None, Path]:

    '''
    f(n) = node priority in queue
    g(n) = cost so far
    h(n) = estimated cost after choosing next node
    priority (f(n)) = g(n) + h(n)
    what is our cost?
    goal is no remaining moves with this army
        h(n) estimated cost to reach goal: amount of army remaining on tile
            - targets high army enemy tiles first?
        g(n) moves used so far
    add value function which simply evaluates the paths for best path


    what about estimated cost is distance to
    '''
    # allow exploration again
    fullLog = map.turn < 150

    general = map.generals[searchingPlayer]

    distanceBetweenGenerals = enemyDistMap[general.x][general.y]
    withinGenPathThreshold = int((distanceBetweenGenerals + 1) * 1.3)
    tilesOnMainPathDist = int((distanceBetweenGenerals + 1) * 1.15)

    withinGenPathMatrix = MapMatrix(map, initVal=False)
    withinTakeEverythingMatrix = MapMatrix(map, initVal=False)

    for tile in map.pathableTiles:
        tileDistSum = enemyDistMap[tile.x][tile.y] + generalDistMap[tile.x][tile.y]
        if tileDistSum < withinGenPathThreshold:
            withinGenPathMatrix[tile] = True
        if tileDistSum < tilesOnMainPathDist:
            withinTakeEverythingMatrix[tile] = True

    if viewInfo:
        viewInfo.add_map_division(withinGenPathMatrix, (255, 200, 0))
        viewInfo.add_map_division(withinTakeEverythingMatrix, (200, 0, 200))

    ## The more turns remaining, the more we prioritize longer paths. Towards the end of expansion, we prioritize sheer captured tiles.
    ## This hopefully leads to finding more ideal expansion plans earlier on while being greedier later
    # lengthWeight = 0.3 * ((turns ** 0.5) - 3)
    # lengthWeight = max(0.25, lengthWeight)

    lengthWeight = 0.3
    logging.info("\n\nAttempting Optimal Expansion (tm) for turns {} (lengthWeight {}):\n".format(turns, lengthWeight))
    startTime = time.perf_counter()
    generalPlayer = map.players[searchingPlayer]
    searchingPlayer = searchingPlayer
    if negativeTiles is None:
        negativeTiles = set()
    else:
        negativeTiles = negativeTiles.copy()

    for tile in negativeTiles:
        logging.info("negativeTile: {}".format(tile.toString()))

    iter = [0]

    # skipFunc(next, nextVal). Not sure why this is 0 instead of 1, but 1 breaks it. I guess the 1 is already subtracted
    if not skipFunc:
        def skip_after_out_of_army(nextTile, nextVal):
            wastedMoves, prioWeighted, distSoFar, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = nextVal
            # skip if out of army, or if we've wasted a bunch of moves already and have nothing to show
            if negArmyRemaining >= 0 or (wastedMoves > 4 and tileCapturePoints > -5):
                return True
            return False
        skipFunc = skip_after_out_of_army

    if not valueFunc:
        # def value_priority_army_dist(currentTile, priorityObject):
        #    wastedMoves, prioWeighted, distSoFar, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = priorityObject
        #    # negative these back to positive
        #    #return (posPathPrio, 0-armyRemaining, distSoFar)
        #    value = -1000
        #    dist = 1
        #    #if currentTile in negativeTiles:
        #    #    return None
        #    if negArmyRemaining < 0 and distSoFar > 0 and tileCapturePoints < 0:
        #        dist = distSoFar + lengthWeight
        #        # negative points for wasted moves until the end of expansion
        #        value = 0-tileCapturePoints - len(enemyExpansionTileSet) - 3 * wastedMoves * lengthWeight
        #    return (value / (dist + wastedMoves),
        #                0-negArmyRemaining,
        #                    0-enemyTiles / dist,
        #                        value,
        #                            0-len(enemyExpansionTileSet),
        #                                0-distSoFar)
        # valueFunc = value_priority_army_dist

        def value_priority_army_dist_basic(currentTile, priorityObject):
            wastedMoves, prioWeighted, distSoFar, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = priorityObject
            # negative these back to positive
            value = -1000
            dist = 1
            if viewInfo:
                viewInfo.evaluatedGrid[currentTile.x][currentTile.y] += 1
            if currentTile in negativeTiles or negArmyRemaining >= 0 or distSoFar == 0:
                return None
            if distSoFar > 0 and tileCapturePoints < 0:
                dist = distSoFar + lengthWeight
                # negative points for wasted moves until the end of expansion
                value = 0- tileCapturePoints - 2 * wastedMoves * lengthWeight
            return (value / (dist + wastedMoves),
                    0 - negArmyRemaining,
                    0 - enemyTiles / dist,
                    value,
                    0,
                    0 - distSoFar)

        valueFunc = value_priority_army_dist_basic

    # def a_starey_value_priority_army_dist(currentTile, priorityObject):
    #    wastedMoves, pathPriorityDivided, armyRemaining, enemyTiles, neutralTiles, pathPriority, distSoFar, tileSetSoFar, adjacentSetSoFar = priorityObject
    #    # negative these back to positive
    #    posPathPrio = 0-pathPriorityDivided
    #    #return (posPathPrio, 0-armyRemaining, distSoFar)
    #    return (0-(enemyTiles*2 + neutralTiles) / (max(1, distSoFar)), 0-enemyTiles / (max(1, distSoFar)), posPathPrio, distSoFar)
    ENEMY_EXPANSION_TILE_PENALTY = 0.7

    if not priorityFunc:
        def default_priority_func(nextTile, currentPriorityObject):
            wastedMoves, prioWeighted, distSoFar, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = currentPriorityObject
            if nextTile in tileSetSoFar:
                # logging.info("Prio None for visited {}".format(nextTile.toString()))
                return None
            armyRemaining = 0 - negArmyRemaining
            armyRemaining -= 1

            nextTileSet = tileSetSoFar.copy()
            distSoFar += 1
            # weight tiles closer to the target player higher
            addedPriority = -13 - max(2, enemyDistMap[nextTile.x][nextTile.y] // 3)
            if nextTile in enemyExpansionTileSet:
                enemyExpansionTileSet.remove(nextTile)
                # Then give the penalties back, as we have now captured their expansion tile
                enemyExpansionValue -= (nextTile.army - 1) // 2
                tileCapturePoints -= ENEMY_EXPANSION_TILE_PENALTY
                addedPriority += 2

            releventAdjacents = where(nextTile.adjacents,
                                      lambda adjTile: adjTile not in adjacentSetSoFar and adjTile not in tileSetSoFar)
            if negativeTiles is None or (nextTile not in negativeTiles):
                if searchingPlayer == nextTile.player:
                    armyRemaining += nextTile.army
                else:
                    armyRemaining -= nextTile.army

            if armyRemaining <= 0:
                return None

            nextTileSet.add(nextTile)
            if armyRemaining >= 0:
                # Tiles penalized that are further than 7 tiles from enemy general
                tileModifierPreScale = max(8, enemyDistMap[nextTile.x][nextTile.y]) - 8
                tileModScaled = tileModifierPreScale / 300
                tileCapturePoints += tileModScaled
                usefulMove = True
                # enemytiles or enemyterritory undiscovered tiles
                if targetPlayer != -1 and (nextTile.player == targetPlayer or (
                        not nextTile.visible and territoryMap[nextTile.x][
                    nextTile.y] == targetPlayer)):
                    if nextTile.player == -1:
                        # these are usually 1 or more army since usually after army bonus
                        armyRemaining -= 1
                    addedPriority += 8
                    tileCapturePoints -= 2.3
                    enemyTiles -= 1

                    ## points for locking all nearby enemy tiles down
                    # numEnemyNear = count(nextTile.adjacents, lambda adjTile: adjTile.player == targetPlayer)
                    # numEnemyLocked = count(releventAdjacents, lambda adjTile: adjTile.player == targetPlayer)
                    ##    for every other nearby enemy tile on the path that we've already included in the path, add some priority
                    # addedPriority += (numEnemyNear - numEnemyLocked) * 12
                elif nextTile.player == -1:
                    # if nextTile.isCity: #TODO and is reasonably placed?
                    #    neutralTiles -= 12
                    # we'd prefer to be killing enemy tiles, yeah?
                    wastedMoves += 0.2
                    neutralTiles -= 1
                    tileCapturePoints -= 1
                    # points for capping tiles in general
                    addedPriority += 2
                    # points for taking neutrals next to enemy tiles
                    numEnemyNear = count(nextTile.movable, lambda
                        adjTile: adjTile not in adjacentSetSoFar and adjTile.player == targetPlayer)
                    if numEnemyNear > 0:
                        addedPriority += 2
                else:  # our tiles and non-target enemy tiles get negatively weighted
                    addedPriority -= 1
                    # 0.7
                    usefulMove = False
                    wastedMoves += 0.5

                if usefulMove:
                    # choke points
                    if innerChokes[nextTile.x][nextTile.y]:
                        # bonus points for retaking iChokes
                        addedPriority += 0.5
                        tileCapturePoints -= 0.02
                    if nextTile in pathChokes:
                        # bonus points for retaking iChokes
                        addedPriority += 1
                        tileCapturePoints -= 0.05
                    # if not self.board_analysis.outerChokes[nextTile.x][nextTile.y]:
                    #    # bonus points for not taking oChokes ????
                    #    addedPriority += 0.02
                    #    tileCapturePoints -= 0.01
                    # points for discovering new tiles
                    # addedPriority += count(releventAdjacents, lambda adjTile: not adjTile.discovered) / 2
                    ## points for revealing tiles in the fog
                    # addedPriority += count(releventAdjacents, lambda adjTile: not adjTile.visible) / 3
            else:
                logging.info("Army remaining on {} < 0".format(nextTile.toString()))
                wastedMoves += 1
            iter[0] += 1
            nextAdjacentSet = adjacentSetSoFar.copy()
            for adj in nextTile.adjacents:
                nextAdjacentSet.add(adj)
            nextEnemyExpansionSet = enemyExpansionTileSet.copy()
            # deprioritize paths that allow counterplay
            for adj in nextTile.movable:
                if adj.army >= 3 and adj.player != searchingPlayer and adj.player != -1 and adj not in negativeTiles and adj not in tileSetSoFar and adj not in nextEnemyExpansionSet:
                    nextEnemyExpansionSet.add(adj)
                    enemyExpansionValue += (adj.army - 1) // 2
                    tileCapturePoints += ENEMY_EXPANSION_TILE_PENALTY
            newPathPriority = pathPriority - addedPriority
            if iter[0] < 100 and fullLog:
                logging.info(
                    " - nextTile {}, waste [{:.2f}], prio/dist [{:.2f}], capPts [{:.2f}], negArmRem [{}]\n    eTiles {}, nTiles {}, npPrio {:.2f}, dsf {}, nextTileSet {}\n    nextAdjSet {}, enemyExpVal {}, nextEnExpSet {}".format(
                        nextTile.toString(), wastedMoves, newPathPriority / distSoFar, tileCapturePoints,
                        0 - armyRemaining, enemyTiles, neutralTiles, newPathPriority, distSoFar, len(nextTileSet),
                        len(nextAdjacentSet), enemyExpansionValue, len(nextEnemyExpansionSet)))
            # prioPerTurn = newPathPriority/distSoFar
            prioPerTurn = tileCapturePoints / distSoFar - addedPriority / 4
            return wastedMoves, prioPerTurn, distSoFar, tileCapturePoints, 0 - armyRemaining, enemyTiles, neutralTiles, newPathPriority, nextTileSet, nextAdjacentSet, enemyExpansionValue, nextEnemyExpansionSet

        priorityFunc = default_priority_func

        def default_priority_func_basic(nextTile, currentPriorityObject):
            wastedMoves, prioWeighted, distSoFar, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = currentPriorityObject
            if nextTile in tileSetSoFar:
                # logging.info("Prio None for visited {}".format(nextTile.toString()))
                return None
            armyRemaining = 0 - negArmyRemaining
            distSoFar += 1
            # weight tiles closer to the target player higher

            armyRemaining -= 1

            nextTileSet = tileSetSoFar.copy()
            nextTileSet.add(nextTile)
            addedPriority = -13 - max(2.0, enemyDistMap[nextTile.x][nextTile.y] / 3)
            # releventAdjacents = where(nextTile.adjacents, lambda adjTile: adjTile not in adjacentSetSoFar and adjTile not in tileSetSoFar)
            if negativeTiles is None or (nextTile not in negativeTiles):
                if searchingPlayer == nextTile.player:
                    armyRemaining += nextTile.army
                else:
                    armyRemaining -= nextTile.army
            if armyRemaining <= 0:
                return None
            # Tiles penalized that are further than 7 tiles from enemy general
            tileModifierPreScale = max(8, enemyDistMap[nextTile.x][nextTile.y]) - 8
            tileModScaled = tileModifierPreScale / 200
            tileCapturePoints += tileModScaled
            usefulMove = True
            # enemytiles or enemyterritory undiscovered tiles
            if targetPlayer != -1 and (nextTile.player == targetPlayer or (
                    not nextTile.visible and territoryMap[nextTile.x][
                nextTile.y] == targetPlayer)):
                if nextTile.player == -1:
                    # these are usually 1 or more army since usually after army bonus
                    armyRemaining -= 1
                addedPriority += 8
                tileCapturePoints -= 2.3
                enemyTiles -= 1

                ## points for locking all nearby enemy tiles down
                # numEnemyNear = count(nextTile.adjacents, lambda adjTile: adjTile.player == targetPlayer)
                # numEnemyLocked = count(releventAdjacents, lambda adjTile: adjTile.player == targetPlayer)
                ##    for every other nearby enemy tile on the path that we've already included in the path, add some priority
                # addedPriority += (numEnemyNear - numEnemyLocked) * 12
            elif nextTile.player == -1:
                # if nextTile.isCity: #TODO and is reasonably placed?
                #    neutralTiles -= 12
                # we'd prefer to be killing enemy tiles, yeah?
                # wastedMoves += 0.2
                neutralTiles -= 1
                tileCapturePoints -= 1
                # points for capping tiles in general
                addedPriority += 2
                # points for taking neutrals next to enemy tiles
                # numEnemyNear = count(nextTile.movable, lambda adjTile: adjTile not in adjacentSetSoFar and adjTile.player == targetPlayer)
                # if numEnemyNear > 0:
                #    addedPriority += 2
            else:  # our tiles and non-target enemy tiles get negatively weighted
                addedPriority -= 1
                # 0.7
                usefulMove = False
                wastedMoves += 0.5

            if usefulMove:
                # choke points
                if innerChokes[nextTile.x][nextTile.y]:
                    # bonus points for retaking iChokes
                    addedPriority += 0.5
                    tileCapturePoints -= 0.02
                if nextTile in pathChokes:
                    # bonus points for retaking iChokes
                    addedPriority += 1
                    tileCapturePoints -= 0.05
                # if not self.board_analysis.outerChokes[nextTile.x][nextTile.y]:
                #    # bonus points for not taking oChokes ????
                #    addedPriority += 0.02
                #    tileCapturePoints -= 0.01
                # points for discovering new tiles
                # addedPriority += count(releventAdjacents, lambda adjTile: not adjTile.discovered) / 2
                ## points for revealing tiles in the fog
                # addedPriority += count(releventAdjacents, lambda adjTile: not adjTile.visible) / 3

            iter[0] += 1
            nextAdjacentSet = None
            # nextAdjacentSet = adjacentSetSoFar.copy()
            # for adj in nextTile.adjacents:
            #    nextAdjacentSet.add(adj)
            # nextEnemyExpansionSet = enemyExpansionTileSet.copy()
            nextEnemyExpansionSet = None
            # deprioritize paths that allow counterplay
            # for adj in nextTile.movable:
            #    if adj.army >= 3 and adj.player != searchingPlayer and adj.player != -1 and adj not in negativeTiles and adj not in tileSetSoFar and adj not in nextEnemyExpansionSet:
            #        nextEnemyExpansionSet.add(adj)
            #        enemyExpansionValue += (adj.army - 1) // 2
            #        tileCapturePoints += ENEMY_EXPANSION_TILE_PENALTY
            newPathPriority = pathPriority - addedPriority
            # prioPerTurn = newPathPriority/distSoFar
            prioPerTurn = tileCapturePoints / (distSoFar + lengthWeight) - addedPriority / 4
            if iter[0] < 50 and fullLog:
                logging.info(
                    " - nextTile {}, waste [{:.2f}], prioPerTurn [{:.2f}], dsf {}, capPts [{:.2f}], negArmRem [{}]\n    eTiles {}, nTiles {}, npPrio {:.2f}, nextTileSet {}\n    nextAdjSet {}, enemyExpVal {}, nextEnExpSet {}".format(
                        nextTile.toString(), wastedMoves, prioPerTurn, distSoFar, tileCapturePoints, 0 - armyRemaining,
                        enemyTiles, neutralTiles, newPathPriority, len(nextTileSet), None, enemyExpansionValue, None))

            return wastedMoves, prioPerTurn, distSoFar, tileCapturePoints, 0 - armyRemaining, enemyTiles, neutralTiles, newPathPriority, nextTileSet, nextAdjacentSet, enemyExpansionValue, nextEnemyExpansionSet

        priorityFunc = default_priority_func_basic

    if not boundFunc:
        def default_bound_func(currentTile, currentPriorityObject, maxPriorityObject):
            if maxPriorityObject is None:
                return False
            wastedMoves, prioWeighted, distSoFar, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = currentPriorityObject
            wastedMovesMax, prioWeightedMax, distSoFarMax, tileCapturePointsMax, negArmyRemainingMax, enemyTilesMax, neutralTilesMax, pathPriorityMax, tileSetSoFarMax, adjacentSetSoFarMax, enemyExpansionValueMax, enemyExpansionTileSetMax = maxPriorityObject
            if distSoFarMax <= 4 or distSoFar <= 4:
                return False
            if wastedMoves > wastedMovesMax * 1.2 + 0.4:
                logging.info(
                    "Pruned {} via wastedMoves {:.2f}  >  wastedMovesMax {:.2f} * 1.2 + 0.4 {:.3f}".format(currentTile,
                                                                                                           wastedMoves,
                                                                                                           wastedMovesMax,
                                                                                                           wastedMovesMax * 1.2 + 0.4))
                return True
            thisCapPoints = tileCapturePoints / distSoFar
            maxCapPoints = tileCapturePointsMax / distSoFarMax
            weightedMax = 1.2 * maxCapPoints + 0.5
            if enemyTilesMax + neutralTilesMax > 2 and thisCapPoints > weightedMax:
                logging.info(
                    "Pruned {} via tileCap thisCapPoints {:.3f}  >  weightedMax {:.3f} (maxCapPoints {:.3f})".format(
                        currentTile, thisCapPoints, weightedMax, maxCapPoints))
                return True

            return False

        boundFunc = default_bound_func

    if not initFunc:
        def initial_value_func_default(tile):
            startingSet = set()
            startingSet.add(tile)
            startingAdjSet = set()
            for adj in tile.adjacents:
                startingAdjSet.add(adj)
            startingEnemyExpansionTiles = set()
            enemyExpansionValue = 0
            tileCapturePoints = 0
            for adj in tile.movable:
                if adj.army > 3 and adj.player != searchingPlayer and adj.player != -1 and adj not in negativeTiles:
                    startingEnemyExpansionTiles.add(adj)
                    enemyExpansionValue += (adj.army - 1) // 2
                    tileCapturePoints += ENEMY_EXPANSION_TILE_PENALTY
            return 0, -10000, 0, tileCapturePoints, 0 - tile.army, 0, 0, 0, startingSet, startingAdjSet, enemyExpansionValue, startingEnemyExpansionTiles

        initFunc = initial_value_func_default

    # BACKPACK THIS EXPANSION! Don't stop at remainingTurns 0... just keep finding paths until out of time, then knapsack them

    # Switch this up to use more tiles at the start, just removing the first tile in each path at a time. Maybe this will let us find more 'maximal' paths?
    def postPathEvalFunction(path, negativeTiles):
        value = 0
        last = path.start.tile
        nextNode = path.start.next
        while nextNode is not None:
            tile = nextNode.tile
            if tile in negativeTiles:
                value -= 0.1
                # or do nothing?
            else:
                if tile.player == targetPlayer:
                    value += 2.4
                elif not tile.discovered and territoryMap[tile.x][tile.y] == targetPlayer:
                    value += 2.0
                elif not tile.visible and territoryMap[tile.x][tile.y] == targetPlayer:
                    value += 2.10
                elif tile.player == -1:
                    value += 1.0
            sourceDist = enemyDistMap[last.x][last.y]
            destDist = enemyDistMap[tile.x][tile.y]
            sourceGenDist = generalDistMap[last.x][last.y]
            destGenDist = generalDistMap[tile.x][tile.y]

            sourceDistSum = sourceDist + sourceGenDist
            destDistSum = destDist + destGenDist

            if destDistSum < sourceDistSum:
                logging.info(f"move {last.toString()}->{tile.toString()} was TOWARDS shortest path")
                value += 0.04
            elif destDistSum == sourceDistSum:
                logging.info(f"move {last.toString()}->{tile.toString()} was flanking parallel to shortest path")
                value += 0.01

            if abs(destDist - destGenDist) <= abs(sourceDist - sourceGenDist):
                valueAdd = abs(destDist - destGenDist) / 30
                logging.info(
                    f"move {last.toString()}->{tile.toString()} was moving towards the center, valuing it {valueAdd} higher")
                value += valueAdd

            last = tile
            nextNode = nextNode.next
        return value

    # Tells the FullOnly parameter how to get the values it needs to determine if a path is full or not
    def fullOnly_func(current, currentPriorityObject):
        wastedMoves, prioWeighted, distSoFar, tileCapturePoints, negArmyRemaining, enemyTiles, neutralTiles, pathPriority, tileSetSoFar, adjacentSetSoFar, enemyExpansionValue, enemyExpansionTileSet = currentPriorityObject
        return int(0 - negArmyRemaining), distSoFar, tileSetSoFar

    if turns <= 0:
        logging.info(f"turns {turns} <= 0 in optimal_expansion... Setting to 25")
        turns = 25

    if turns > 25:
        logging.info(f"turns {turns} < 25 in optimal_expansion... Setting to 25")
        turns = 25

    remainingTurns = turns
    sortedTiles = sorted(list(where(generalPlayer.tiles, lambda tile: tile.army > 2 and tile not in negativeTiles)), key=lambda tile: 0 - tile.army)
    if len(sortedTiles) == 0:
        sortedTiles = sorted(list(where(generalPlayer.tiles, lambda tile: tile.army > 1 and tile not in negativeTiles)), key=lambda tile: 0 - tile.army)

    paths = []
    # fullCutoff
    fullCutoff = 10
    cutoffFactor = 1

    # if len(sortedTiles) < 5:
    #    logging.info("Only had {} tiles to play with, switching cutoffFactor to full...".format(len(sortedTiles)))
    #    cutoffFactor = fullCutoff
    player = map.players[searchingPlayer]
    logStuff = True
    if player.tileCount > 70 or turns > 25:
        logging.info("Not doing algorithm logging for expansion due to player tilecount > 70 or turn count > 25")
        logStuff = False
    expandIntoNeutralCities = False
    if player.standingArmy / player.tileCount > 2.6:
        logging.info("Allowing expansion into neutral cities")
        expandIntoNeutralCities = True

    while True:
        if remainingTurns <= 0:
            logging.info("breaking due to remainingTurns <= 0")
            break
        if cutoffFactor > fullCutoff:
            logging.info("breaking due to cutoffFactor > fullCutoff")
            break
        if len(sortedTiles) == 0:
            logging.info("breaking due to no tiles left in sortedTiles")
            break
        timeUsed = time.perf_counter() - startTime
        # Stages:
        # first 0.1s, use large tiles and shift smaller. (do nothing)
        # second 0.1s, use all tiles (to make sure our small tiles are included)
        # third 0.1s - knapsack optimal stuff outside this loop i guess?
        stage1 = 0.10
        stage2 = 0.15
        breakStage = 0.22
        if timeUsed > stage1:
            logging.info("timeUsed > {} ({})... Breaking loop and knapsacking...".format(stage1, timeUsed))
        if timeUsed > stage2:
            logging.info(
                "timeUsed > {} ({})... Switching to using all tiles, cutoffFactor = fullCutoff...".format(stage2,
                                                                                                          timeUsed))
            cutoffFactor = fullCutoff
        if timeUsed > breakStage:
            logging.info("timeUsed > {} ({})... breaking...".format(breakStage, timeUsed))
            break

        # startIdx = max(0, ((cutoffFactor - 1) * len(sortedTiles))//fullCutoff)
        startIdx = 0
        endIdx = min(len(sortedTiles), (cutoffFactor * len(sortedTiles)) // fullCutoff + 1)
        logging.info("startIdx {} endIdx {}".format(startIdx, endIdx))
        tilePercentile = sortedTiles[startIdx:endIdx]
        # filter out the bottom value of tiles (will filter out 1's in the early game, or the remaining 2's, etc)
        tilesLargerThanAverage = where(
            tilePercentile,
            lambda tile: (negativeTiles is None or tile not in negativeTiles) and tile.army > tilePercentile[-1].army)

        tilesLargerThanAverage = tilePercentile
        logging.info('cutoffFactor {}/{}, largestTile {}: {} army, smallestTile {}: {} army'
                     .format(cutoffFactor,
                             fullCutoff,
                             tilePercentile[0].toString(),
                             tilePercentile[0].army,
                             tilePercentile[-1].toString(),
                             tilePercentile[-1].army))

        # hack,  see what happens TODO
        # tilesLargerThanAverage = where(generalPlayer.tiles, lambda tile: tile.army > 1)
        # logging.info("Filtered for tilesLargerThanAverage with army > {}, found {} of them".format(tilePercentile[-1].army, len(tilesLargerThanAverage)))
        startDict = {}
        for i, tile in enumerate(tilesLargerThanAverage):
            # skip tiles we've already used or intentionally ignored
            if tile in negativeTiles:
                continue
            # self.mark_tile(tile, 10)

            initVal = initFunc(tile)
            # wastedMoves, pathPriorityDivided, armyRemaining, pathPriority, distSoFar, tileSetSoFar
            # 10 because it puts the tile above any other first move tile, so it gets explored at least 1 deep...
            startDict[tile] = (initVal, 0)

        path = breadth_first_dynamic_max(
            map,
            startDict,
            valueFunc,
            0.03,
            remainingTurns,
            noNeutralCities=(not expandIntoNeutralCities),
            negativeTiles=negativeTiles,
            searchingPlayer=searchingPlayer,
            priorityFunc=priorityFunc,
            useGlobalVisitedSet=False,
            skipFunc=skipFunc,
            logResultValues=logStuff,
            fullOnly=False,
            fullOnlyArmyDistFunc=fullOnly_func,
            boundFunc=boundFunc)

        if path is not None and path:
            logging.info(
                "Path found for maximizing army usage? Duration {:.3f} path {}".format(time.perf_counter() - startTime,
                                                                                       path.toString()))

            # BYPASSED THIS BECAUSE KNAPSACK...
            # remainingTurns -= path.length
            value = postPathEvalFunction(path, negativeTiles)
            if value >= 1 and value / path.length >= 0.2:
                visited = set()
                friendlyCityCount = 0
                node = path.start
                # only add the first tile in the path
                # negativeTiles.add(node.tile)
                while node is not None:
                    if node.tile not in negativeTiles and node.tile not in visited:
                        visited.add(node.tile)

                    if node.tile.player == searchingPlayer and (node.tile.isCity or node.tile.isGeneral):
                        friendlyCityCount += 1
                    # this tile is now worth nothing because we already intend to use it ?
                    negativeTiles.add(node.tile)
                    node = node.next
                sortedTiles.remove(path.start.tile)
                paths.append((friendlyCityCount, value, path))
            else:
                logging.info(
                    "Trimming value {:.2f} Path {} and incrementing cutoffFactor because low value".format(value,
                                                                                                           path.toString()))
                cutoffFactor += 3
        else:
            cutoffFactor += 3
            logging.info(
                "Didn't find a super duper cool optimized expansion pathy thing for remainingTurns {}, cutoffFactor {}. Incrementing cutoffFactor :(".format(
                    remainingTurns, cutoffFactor))

    # expansionGather = greedy_backpack_gather(map, tilesLargerThanAverage, turns, None, valueFunc, baseCaseFunc, negativeTiles, None, searchingPlayer, priorityFunc, skipFunc = None)
    if allowLeafMoves and leafMoves is not None:
        logging.info("Allowing leafMoves as part of optimal expansion....")
        for leafMove in leafMoves:
            if (leafMove.source not in negativeTiles
                    and leafMove.dest not in negativeTiles
                    and (leafMove.dest.player == -1 or leafMove.dest.player == targetPlayer)):
                if leafMove.source.army < 30:
                    if leafMove.source.army - 1 <= leafMove.dest.army:
                        continue
                    logging.info("adding leafMove {} to knapsack input".format(leafMove.toString()))
                    path = Path(leafMove.source.army - leafMove.dest.army - 1)
                    path.add_next(leafMove.source)
                    path.add_next(leafMove.dest)
                    value = postPathEvalFunction(path, negativeTiles)
                    cityCount = 0
                    if leafMove.source.isGeneral or leafMove.source.isCity:
                        cityCount += 1
                    paths.append((cityCount, value, path))
                    negativeTiles.add(leafMove.source)
                    negativeTiles.add(leafMove.dest)
                else:
                    logging.info(
                        "Did NOT add leafMove {} to knapsack input because its value was high. Why wasn't it already input if it is a good move?".format(
                            leafMove.toString()))

    alpha = 75
    minAlpha = 50
    alphaDec = 2
    trimmable = {}
    if calculateTrimmable:
        for friendlyCityCount, tilesCaptured, path in paths:
            tailNode = path.tail
            trimCount = 0
            while tailNode.tile.player == -1 and territoryMap[tailNode.tile.x][
                tailNode.tile.y] != targetPlayer and tailNode.tile.discovered:
                trimCount += 1
                tailNode = tailNode.prev
            if trimCount > 0:
                trimmable[path.start.tile] = (path, trimCount)

            if viewInfo:
                viewInfo.bottomRightGridText[path.start.tile.x][path.start.tile.y] = tilesCaptured
                viewInfo.paths.appendleft(PathColorer(path, 180, 51, 254, alpha, alphaDec, minAlpha))

    intFactor = 100
    # build knapsack weights and values
    weights = [path.length for friendlyCityCount, tilesCaptured, path in paths]
    values = [int(intFactor * tilesCaptured) for friendlyCityCount, tilesCaptured, path in paths]
    logging.info("Feeding the following paths into knapsackSolver at turns {}...".format(turns))
    for i, pathTuple in enumerate(paths):
        friendlyCityCount, tilesCaptured, curPath = pathTuple
        logging.info("{}:  cap {:.2f} length {} path {}".format(i, tilesCaptured, curPath.length, curPath.toString()))

    totalValue, maxKnapsackedPaths = solve_knapsack(paths, turns, weights, values)
    logging.info("maxKnapsackedPaths value {} length {},".format(totalValue, len(maxKnapsackedPaths)))

    path: typing.Union[None, Path] = None
    if len(maxKnapsackedPaths) > 0:
        maxVal = (-10000, -1)
        totalTrimmable = 0
        for friendlyCityCount, tilesCaptured, curPath in maxKnapsackedPaths:
            if curPath.start.tile in trimmable:
                logging.info("trimmable in current knapsack, {} (friendlyCityCount {}, tilesCaptured {})".format(
                    curPath.toString(), friendlyCityCount, tilesCaptured))
                trimmablePath, possibleTrim = trimmable[curPath.start.tile]
                totalTrimmable += possibleTrim
        logging.info("totalTrimmable! {}".format(totalTrimmable))

        if totalTrimmable > 0:
            trimmableStart = time.perf_counter()
            trimRange = min(10, 1 + totalTrimmable)
            # see if there are better knapsacks if we trim the ends off some of these
            maxKnapsackVal = totalValue
            for i in range(trimRange):
                otherValue, otherKnapsackedPaths = solve_knapsack(paths, turns + i, weights, values)
                # offset by i to compensate for the skipped moves
                otherValueWeightedByTrim = otherValue - i * intFactor
                logging.info("i {} - otherKnapsackedPaths value {} weightedValue {} length {}".format(i, otherValue,
                                                                                                      otherValueWeightedByTrim,
                                                                                                      len(otherKnapsackedPaths)))
                if otherValueWeightedByTrim > maxKnapsackVal:
                    maxKnapsackVal = otherValueWeightedByTrim
                    maxKnapsackedPaths = otherKnapsackedPaths
                    logging.info("NEW MAX {}".format(maxKnapsackVal))
            logging.info("(Time spent on {} trimmable iterations: {:.3f})".format(trimRange,
                                                                                  time.perf_counter() - trimmableStart))
        # Select which of the knapsack paths to move first
        logging.info("Selecting which of the above paths to move first")
        for friendlyCityCount, tilesCaptured, curPath in maxKnapsackedPaths:
            trimmableVal = 0
            if curPath.start.tile in trimmable:
                trimmablePath, possibleTrim = trimmable[curPath.start.tile]
                trimmableVal = possibleTrim
            # Paths ending with the largest armies go first to allow for more path selection options later
            thisVal = (0 - friendlyCityCount,
                       curPath.value,
                       0 - trimmableVal,
                       0 - enemyDistMap[curPath.start.tile.x][curPath.start.tile.y],
                       tilesCaptured / curPath.length)
            if thisVal > maxVal:
                maxVal = thisVal
                path = curPath
                logging.info(
                    "new max val, eval [{}], path {}".format('], ['.join(str(x) for x in maxVal), path.toString()))
            else:
                logging.info(
                    "NOT max val, eval [{}], path {}".format('], ['.join(str(x) for x in thisVal), curPath.toString()))

            if viewInfo:
                # draw other paths darker
                alpha = 150
                minAlpha = 150
                alphaDec = 0
                viewInfo.paths.appendleft(PathColorer(curPath, 200, 51, 204, alpha, alphaDec, minAlpha))
        logging.info("EXPANSION PLANNED HOLY SHIT? iterations {}, Duration {:.3f}, path {}".format(iter[0],
                                                                                                   time.perf_counter() - startTime,
                                                                                                   path.toString()))
        # draw maximal path darker
        alpha = 255
        minAlpha = 200
        alphaDec = 0
        if viewInfo:
            viewInfo.paths = deque(where(viewInfo.paths, lambda pathCol: pathCol.path != path))
            viewInfo.paths.appendleft(PathColorer(path, 255, 100, 200, alpha, alphaDec, minAlpha))
    else:
        logging.info(
            "No expansion plan.... :( iterations {}, Duration {:.3f}".format(iter[0], time.perf_counter() - startTime))

    tilesInKnapsackOtherThanCurrent = set()

    for friendlyCityCount, tilesCaptured, curPath in maxKnapsackedPaths:
        if curPath != path:
            for tile in curPath.tileList:
                tilesInKnapsackOtherThanCurrent.add(tile)

    if path is None:
        return path

    shouldConsiderMoveHalf = should_consider_path_move_half(
        map,
        general,
        path,
        negativeTiles=tilesInKnapsackOtherThanCurrent,
        player=searchingPlayer,
        enemyDistMap=enemyDistMap,
        playerDistMap=generalDistMap,
        withinGenPathThreshold=withinGenPathThreshold,
        tilesOnMainPathDist=tilesOnMainPathDist)

    if not shouldConsiderMoveHalf:
        return path

    path.start.move_half = True
    val = path.calculate_value(searchingPlayer)
    if viewInfo:
        viewInfo.addAdditionalInfoLine(f'path move_half value was {val} (path {str(path)})')
    if val <= 0:
        path.start.move_half = False

    return path



def should_consider_path_move_half(
        map: MapBase,
        general: Tile,
        path: Path,
        negativeTiles: typing.Set[Tile],
        player: int,
        playerDistMap: typing.List[typing.List[int]],
        enemyDistMap: typing.List[typing.List[int]],
        withinGenPathThreshold: int,
        tilesOnMainPathDist: int):

    pathTile: Tile = path.start.tile
    pathTileDistSum = enemyDistMap[pathTile.x][pathTile.y] + playerDistMap[pathTile.x][pathTile.y]

    def filter_alternate_movables(tile: Tile):
        if tile.isMountain:
            return False
        if tile.isCity and tile.player != player:
            return False
        if tile in negativeTiles:
            return False
        if tile in path.tileSet:
            return False
        if tile.player == player:
            return False

        tileDistSum = enemyDistMap[tile.x][tile.y] + playerDistMap[tile.x][tile.y]
        tileNotTooFarToFlank = tileDistSum < withinGenPathThreshold
        tileShouldTakeEverything = tileDistSum < tilesOnMainPathDist

        altMovableMovingAwayFromPath = pathTileDistSum < tileDistSum
        if altMovableMovingAwayFromPath and not tileNotTooFarToFlank:
            return False

        # a 4 move-half leaves 2 behind, a 5 move_half leaves 3 behind
        capArmy = (path.value + 1) // 2

        altCappable = set()
        def filter_alternate_path(altTile: Tile):
            if altTile.isMountain:
                return
            if altTile in negativeTiles:
                return
            if altTile in path.tileSet:
                return
            if altTile.isCity and altTile.player != player:
                return
            if altTile.player == player:
                return
            if altTile == tile:
                return

            altTileDistSum = enemyDistMap[altTile.x][altTile.y] + playerDistMap[altTile.x][altTile.y]
            movingTowardPath = altTileDistSum < tileDistSum
            movingParallelToPath = altTileDistSum == tileDistSum
            if movingTowardPath or tileShouldTakeEverything or (tileNotTooFarToFlank and movingParallelToPath):
                altCappable.add(altTile)

        breadth_first_foreach(
            map,
            [tile],
            maxDepth = 4,
            foreachFunc=filter_alternate_path)

        canCapTile = capArmy - 1 > tile.army
        isEnemyTileThatCanRecapture = tile.player >= 0 and tile.army > 2
        canProbablyCaptureNearbyTiles = len(altCappable) > capArmy // 2
        if (canCapTile and canProbablyCaptureNearbyTiles) or isEnemyTileThatCanRecapture:
            return True

        return False

    if count(pathTile.movable, filter_alternate_movables) > 0:
        # TODO take into account whether the alt path would expand away from both generals
        return True

    return False
