"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

import logbook
import math
import typing
import time
from collections import deque
from queue import PriorityQueue
from DataModels import PathNode
from Path import Path
from test.test_float import INF
from base.client.map import Tile, MapBase, new_value_grid
from MapMatrix import MapMatrix

BYPASS_TIMEOUTS_FOR_DEBUGGING = False


class Counter(object):
    def __init__(self, value):
        self.value = value

    def add(self, value):
        self.value = self.value + value


def where(enumerable, filter_func):
    results = [item for item in enumerable if filter_func(item)]
    return results


def any_where(enumerable, filter_func) -> bool:
    for item in enumerable:
        if filter_func(item):
            return True
    return False


def count(enumerable, filter_func) -> int:
    countMatch = 0
    for item in enumerable:
        if filter_func(item):
            countMatch += 1
    return countMatch


def dest_breadth_first_target(
        map,
        goalList,
        targetArmy=1,
        maxTime=0.1,
        maxDepth=20,
        negativeTiles=None,
        searchingPlayer=-2,
        dontEvacCities=False,
        dupeThreshold=3,
        noNeutralCities=True,
        skipTiles=None,
        ignoreGoalArmy=False,
        noLog=True,
        additionalIncrement: float = 0.0,
        preferCapture: bool = False
) -> typing.Union[None, Path]:
    """
    Gets a path that results in {targetArmy} army on one of the goalList tiles.
    GoalList can be a dict that maps from start tile to (startDist, goalTargetArmy)

    additionalIncrement can be set if for example capturing one of two nearby cities and you want to kill with enough to kill both.
    Positive means gather EXTRA, negative means gather LESS.
    """
    if searchingPlayer == -2:
        searchingPlayer = map.player_index
    frontier = PriorityQueue()
    visited = [[None for _ in range(map.rows)] for _ in range(map.cols)]
    if isinstance(goalList, dict):
        for goal in goalList.keys():
            (startDist, goalTargetArmy, goalIncModifier) = goalList[goal]
            if goal.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue

            goalInc = goalIncModifier + additionalIncrement
            startArmy = goalIncModifier

            # THE goalIncs below might be wrong, unit test.
            if searchingPlayer != goal.player:
                startArmy = 0 + goalTargetArmy  # + goalInc
            else:
                startArmy = 0 - goalTargetArmy  # - goalInc

            if ignoreGoalArmy:
                # then we have to inversely increment so we dont have to figure that out in the loop every time
                if searchingPlayer != goal.player:
                    if negativeTiles is None or goal not in negativeTiles:
                        startArmy -= goal.army
                else:
                    if negativeTiles is None or goal not in negativeTiles:
                        startArmy += goal.army

            startVal = (startDist, 0, 0 - startArmy)
            frontier.put((startVal, goal, startDist, startArmy, goalInc, None))
    else:
        for goalRaw in goalList:
            goal: Tile = goalRaw
            if goal.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue

            goalInc = additionalIncrement

            # fixes the off-by-one error because we immediately decrement army, but the target shouldn't decrement
            startArmy = 1
            if ignoreGoalArmy and (negativeTiles is None or goal not in negativeTiles):
                # then we have to inversely increment so we dont have to figure that out in the loop every time
                if searchingPlayer != goal.player:
                    startArmy -= goal.army
                else:
                    startArmy += goal.army

            startVal = (0, 0, 0 - startArmy)
            frontier.put((startVal, goal, 0, startArmy, goalInc, None))
    start = time.perf_counter()
    iter = 0
    foundGoal = False
    foundArmy = -1000
    foundDist = -1
    endNode = None
    depthEvaluated = 0
    while not frontier.empty():
        iter += 1

        (prioVals, current, dist, army, goalInc, fromTile) = frontier.get()
        if visited[current.x][current.y] is not None:
            continue
        if skipTiles is not None and current in skipTiles:
            if not noLog and iter < 100: logbook.info(
                f"PopSkipped skipTile current {current.toString()}, army {army}, goalInc {goalInc}, targetArmy {targetArmy}")
            continue
        if current.isMountain or (
                current.isCity and noNeutralCities and current.player == -1 and current not in goalList) or (
                not current.discovered and current.isNotPathable):
            if not noLog and iter < 100: logbook.info(
                f"PopSkipped Mountain, neutCity or Obstacle current {current.toString()}")
            continue

        _, negCaptures, prioArmy = prioVals

        nextArmy = army - 1 - goalInc

        if preferCapture and not map.is_player_on_team_with(searchingPlayer, current.player):
            negCaptures -= 1

        # nextArmy is effectively "you must bring this much army to the tile next to me for this to kill"
        if (current.isCity and current.player != -1) or current.isGeneral:
            if current.player == searchingPlayer:
                goalInc -= 0.5
                nextArmy -= goalInc
            else:
                goalInc += 0.5
                nextArmy += goalInc

        if negativeTiles is None or current not in negativeTiles:
            if searchingPlayer == current.player:
                if current.isCity and dontEvacCities:
                    nextArmy += (current.army // 2)
                else:
                    nextArmy += current.army
            else:
                nextArmy -= current.army
        newDist = dist + 1

        visited[current.x][current.y] = (nextArmy, fromTile)

        if nextArmy >= targetArmy and nextArmy > foundArmy:
            foundGoal = True
            foundDist = newDist
            foundArmy = nextArmy
            endNode = current
            if not noLog and iter < 100:
                logbook.info(
                    f"GOAL popped {current.toString()}, army {nextArmy}, goalInc {goalInc}, targetArmy {targetArmy}, processing")
            break
        if newDist > depthEvaluated:
            depthEvaluated = newDist
        # targetArmy += goalInc

        if not noLog and iter < 100:
            logbook.info(
                f"Popped current {current.toString()}, army {nextArmy}, goalInc {goalInc}, targetArmy {targetArmy}, processing")
        if newDist <= maxDepth and not foundGoal:
            for next in current.movable:  # new spots to try
                frontier.put(((newDist, negCaptures, 0 - nextArmy), next, newDist, nextArmy, goalInc, current))
    if not noLog:
        logbook.info(
            f"BFS DEST SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}, FOUNDDIST: {foundDist}")
    if foundDist < 0:
        return None

    node = endNode
    dist = foundDist
    nodes = []
    army = foundArmy
    # logbook.info(json.dumps(visited))
    # logbook.info("PPRINT FULL")
    # logbook.info(pformat(visited))

    while node is not None:
        # logbook.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
        nodes.append((army, node))

        # logbook.info(pformat(visited[node.x][node.y]))
        (army, node) = visited[node.x][node.y]
        dist -= 1
    nodes.reverse()

    (startArmy, startNode) = nodes[0]

    # round against our favor so we always error on the side of too much defense
    # or too much offense instead of not enough
    if searchingPlayer == map.player_index:
        foundArmy = math.floor(foundArmy)
    else:
        foundArmy = math.ceil(foundArmy)

    pathObject = Path(foundArmy)
    pathObject.add_next(startNode)

    pathStart = PathNode(startNode, None, foundArmy, foundDist, -1, None)
    path = pathStart
    dist = foundDist
    for i, armyNode in enumerate(nodes[1:]):
        (curArmy, curNode) = armyNode
        if curNode is not None:
            # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
            path = PathNode(curNode, path, curArmy, dist, -1, None)
            pathObject.add_start(curNode)
            dist -= 1
    while path is not None and path.tile.army <= 1:
        logbook.info(
            "IS THIS THE INC BUG? OMG I THINK I FOUND IT!!!!!! Finds path where waiting 1 move for city increment is superior, but then we skip the 'waiting' move and just move the 2 army off the city instead of 3 army?")
        logbook.info(f"stripping path node {str(path)}")
        path = path.parent
        pathObject.made_move()

    if pathObject.length <= 0:
        logbook.info("abandoned path")
        return None
    # while (node != None):
    #     army, node = visited[node.x][node.y][dist]
    #     if (node != None):
    #         dist -= 1
    #         path = PathNode(node, path, army, dist, -1, None)

    logbook.info(
        f"DEST BFS FOUND KILLPATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    return pathObject


def _shortestPathHeur(goals, cur) -> int:
    minFound = 100000
    for goal in goals:
        minFound = min(minFound, abs(goal.x - cur.x) + abs(goal.y - cur.y))
    return minFound


def a_star_kill(
        map,
        startTiles,
        goalSet,
        maxTime=0.1,
        maxDepth=20,
        restrictionEvalFuncs=None,
        ignoreStartTile=False,
        requireExtraArmy=0,
        negativeTiles=None):
    frontier = PriorityQueue()
    came_from = {}
    cost_so_far = {}
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            logbook.info(f"a* enqueued start tile {start.toString()} with extraArmy {requireExtraArmy}")
            startArmy = start.army
            if ignoreStartTile:
                startArmy = 0
            startArmy -= requireExtraArmy
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = (startDist, 0 - startArmy)
            frontier.put((cost_so_far[start], start))
            came_from[start] = None
    else:
        for start in startTiles:
            logbook.info(f"a* enqueued start tile {start.toString()} with extraArmy {requireExtraArmy}")
            startArmy = start.army
            if ignoreStartTile:
                startArmy = 0
            startArmy -= requireExtraArmy
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = (0, 0 - startArmy)
            frontier.put((cost_so_far[start], start))
            came_from[start] = None
    start = time.perf_counter()
    iter = 0
    foundDist = -1
    foundArmy = -1
    goal = False
    depthEvaluated = 0

    while not frontier.empty():
        iter += 1
        if iter & 64 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING:
            logbook.info("breaking A* early")
            break
        prio, current = frontier.get()
        x = current.x
        y = current.y
        curCost = cost_so_far[current]
        dist = curCost[0]
        army = 0 - curCost[1]

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current in goalSet:
            if army > 1 and army > foundArmy:
                foundDist = dist
                foundArmy = army
                goal = True
                break
            else:  # skip paths that go through target, that wouldn't make sense
                # logbook.info("a* path went through target")
                continue
        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next == came_from[current]:
                    continue
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if restrictionEvalFuncs is not None:
                    if current in restrictionEvalFuncs:
                        if not restrictionEvalFuncs[current](next):
                            logbook.info(f"dangerous, vetod: {current.x},{current.y}")
                            continue
                        else:
                            logbook.info(f"safe: {current.x},{current.y}")

                inc = 0 if not ((next.isCity and next.player != -1) or next.isGeneral) else (dist + 1) / 2

                # new_cost = cost_so_far[current] + graph.cost(current, next)
                nextArmy = army - 1
                if negativeTiles is None or next not in negativeTiles:
                    if startTiles[0].player == next.player:
                        nextArmy += next.army + inc
                    else:
                        nextArmy -= (next.army + inc)
                    if next.isCity and next.player == -1:
                        nextArmy -= next.army * 2
                if nextArmy <= 0 and army > 0:  # prune out paths that go negative after initially going positive
                    # logbook.info("a* next army <= 0: {}".format(nextArmy))
                    continue
                new_cost = (dist + 1, (0 - nextArmy))
                if next not in cost_so_far or new_cost < cost_so_far[next]:
                    cost_so_far[next] = new_cost
                    priority = (dist + 1 + _shortestPathHeur(goalSet, next), 0 - nextArmy)
                    frontier.put((priority, next))
                    # logbook.info("a* enqueued next")
                    came_from[next] = current
    logbook.info(
        f"A* KILL SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")
    goal = None
    for possibleGoal in goalSet:
        if possibleGoal in came_from:
            goal = possibleGoal
    if goal is None:
        return None

    pathObject = Path(foundArmy)
    pathObject.add_next(goal)
    node = goal
    dist = foundDist
    while came_from[node] is not None:
        # logbook.info("Node {},{}".format(node.x, node.y))
        node = came_from[node]
        dist -= 1
        pathObject.add_start(node)
    logbook.info(f"A* FOUND KILLPATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    pathObject.calculate_value(startTiles[0].player, teams=map._teams)
    if pathObject.value < requireExtraArmy:
        logbook.info(f"A* path {pathObject.toString()} wasn't good enough, returning none")
        return None
    return pathObject


def breadth_first_dynamic(
        map,
        startTiles,
        goalFunc,
        maxTime=0.2,
        maxDepth=100,
        noNeutralCities=True,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        allowDoubleBacks=False):
    """
    startTiles dict is (startPriorityObject, distance) = startTiles[tile]
    goalFunc is (currentTile, priorityObject) -> True or False
    priorityFunc is (nextTile, currentPriorityObject) -> nextPriorityObject

    # make sure to initialize the initial base values and account for first priorityObject being None.
    def default_priority_func(nextTile, currentPriorityObject):
        dist = -1
        negCityCount = negEnemyTileCount = negArmySum = x = y = 0
        if currentPriorityObject != None:
            (dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and nextTile.player != -1:
            negEnemyTileCount -= 1
        if nextTile.player == searchingPlayer:
            negArmySum -= nextTile.army - 1
        else:
            negArmySum += nextTile.army + 1
        return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
    """
    if negativeTiles is None:
        negativeTiles = set()

    # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
    def default_priority_func(nextTile, currentPriorityObject):
        (dist, negCityCount, negEnemyTileCount, negArmySum, x, y, goalIncrement) = currentPriorityObject
        dist += 1
        if not map.is_player_on_team_with(nextTile.player, searchingPlayer):
            # if negativeTiles is None or next not in negativeTiles:
            negArmySum += nextTile.army
        else:
            negArmySum -= nextTile.army

        # always leaving 1 army behind. + because this is negative.
        negArmySum += 1
        # -= because we passed it in positive for our general and negative for enemy gen / cities
        negArmySum -= goalIncrement
        return dist, 0, 0, negArmySum, nextTile.x, nextTile.y, goalIncrement

    if searchingPlayer == -2:
        searchingPlayer = map.player_index
    if priorityFunc is None:
        priorityFunc = default_priority_func
    frontier = PriorityQueue()
    visited = [[{} for x in range(map.rows)] for y in range(map.cols)]
    globalVisitedSet = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            frontier.put((startVal, distance, tile, None))
    else:
        for tile in startTiles:
            if priorityFunc != default_priority_func:
                raise AssertionError(
                    "yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
            if tile.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            dist = 0
            negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0

            if not ignoreStartTile and tile.isCity:
                negCityCount = -1
            if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
                negEnemyTileCount = -1
            if not ignoreStartTile and tile.player == searchingPlayer:
                negArmySum = 1 - tile.army
            else:
                negArmySum = tile.army + 1
            if not ignoreStartTile:
                if tile.player != -1 and tile.isCity or tile.isGeneral:
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            frontier.put((startVal, dist, tile, None))
    start = time.perf_counter()
    iter = 0
    foundGoal = False
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    foundVal = None
    while not frontier.empty():
        iter += 1
        if iter % 1000 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING:
            logbook.info("BFS-DYNAMIC BREAKING")
            break

        (prioVals, dist, current, parent) = frontier.get()
        if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
            visited[current.x][current.y][dist] = (prioVals, parent)
        # TODO no globalVisitedSet
        if current in globalVisitedSet or (skipTiles is not None and current in skipTiles):
            continue
        globalVisitedSet.add(current)
        if goalFunc(current, prioVals) and (foundVal is None or prioVals < foundVal):
            foundGoal = True
            foundDist = dist
            foundVal = prioVals
            endNode = current
        if dist > depthEvaluated:
            depthEvaluated = dist
            if foundGoal:
                break
        if dist <= maxDepth and not foundGoal:
            for next in current.movable:  # new spots to try
                if next == parent and not allowDoubleBacks:
                    continue
                if (next.isMountain
                        or (noNeutralCities and next.player == -1 and next.isCity)
                        or (not next.discovered and next.isNotPathable)):
                    continue
                newDist = dist + 1
                nextVal = priorityFunc(next, prioVals)
                if skipFunc is not None and skipFunc(next, nextVal):
                    continue
                frontier.put((nextVal, newDist, next, current))

    logbook.info(
        f"BFS-DYNAMIC ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return None

    tile = endNode
    dist = foundDist
    tileList = []
    # logbook.info(json.dumps(visited))
    # logbook.info("PPRINT FULL")
    # logbook.info(pformat(visited))

    while tile is not None:
        # logbook.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
        tileList.append(tile)

        # logbook.info(pformat(visited[node.x][node.y]))
        (prioVal, tile) = visited[tile.x][tile.y][dist]
        dist -= 1
    pathObject = Path()
    for tile in reversed(tileList):
        if tile is not None:
            # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
            pathObject.add_next(tile)

    # while (node != None):
    #     army, node = visited[node.x][node.y][dist]
    #     if (node != None):
    #         dist -= 1
    #         path = PathNode(node, path, army, dist, -1, None)
    pathObject.calculate_value(
        searchingPlayer,
        teams=map._teams,
        incrementBackwards=incrementBackward)
    logbook.info(
        f"DYNAMIC BFS FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject.toString()}")
    return pathObject


def breadth_first_dynamic_max(
        map,
        startTiles: typing.Union[typing.List[Tile], typing.Dict[Tile, typing.Tuple[object, int]]],
        valueFunc=None,  # higher is better
        maxTime=0.2,
        maxTurns=100,
        maxDepth=100,
        noNeutralCities=False,
        noNeutralUndiscoveredObstacles=True,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,  # lower is better
        skipFunc=None,  # evaluation to true will refuse to even path through the tile
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        useGlobalVisitedSet=True,  # never path through a tile again once one prio func has pathed through it once
        logResultValues=False,
        noLog=False,
        includePathValue=False,
        fullOnly=False,
        fullOnlyArmyDistFunc=None,
        boundFunc=None,
        maxIterations: int = INF,
        allowDoubleBacks=False,
        priorityMatrix: MapMatrix[float] | None = None,
        includePath=False,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True
):
    """
    @param map:
    @param startTiles: startTiles dict is (startPriorityObject, distance) = startTiles[tile]
    @param valueFunc:
    @param maxTime:
    @param maxDepth:
    @param noNeutralCities:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc: priorityFunc is (nextTile, currentPriorityObject) -> nextPriorityObject
    @param skipFunc:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param useGlobalVisitedSet: prevent a tile from ever being popped more than once in a search. Use this when your priority function guarantees that the best path that uses a tile is also guaranteed to be reached first in the search.
    @param logResultValues:
    @param noLog:
    @param includePathValue: if True, the paths value (from the value func output) will be returned in a tuple with the actual path.
    @param fullOnly:
    @param fullOnlyArmyDistFunc:
    @param boundFunc: boundFunc is (currentTile, currentPiorityObject, maxPriorityObject) -> True (prune) False (continue)
    @param maxIterations:
    @param allowDoubleBacks:
    @param includePath:  if True, all the functions take a path object param as third tuple entry
    @param ignoreNonPlayerArmy: if True, the paths returned will be calculated on the basis of just the searching players army and ignore enemy (or neutral city!) army they pass through.
    @param ignoreIncrement: if True, do not have paths returned include the city increment in their path calculation for any cities or generals in the path.
    @return:

    # make sure to initialize the initial base values and account for first priorityObject being None.
    def default_priority_func(nextTile, currentPriorityObject):
        dist = -1
        negCityCount = negEnemyTileCount = negArmySum = x = y = 0
        if currentPriorityObject != None:
            (dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and nextTile.player != -1:
            negEnemyTileCount -= 1
        if nextTile.player == searchingPlayer:
            negArmySum -= nextTile.army - 1
        else:
            negArmySum += nextTile.army + 1
        return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
    """
    if negativeTiles is None:
        negativeTiles = set()

    if valueFunc is None:
        # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
        def default_value_func(curTile, currentPriorityObject):
            (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject

            if dist == 0:
                return None

            return 0 - negArmySum / dist, 0 - negEnemyTileCount

        valueFunc = default_value_func

    if fullOnly:
        oldValFunc = valueFunc

        def newValFunc(current, prioVals):
            army, dist, tileSet = fullOnlyArmyDistFunc(current, prioVals)

            validMoveCount = 0
            # if not noLog:
            #    logbook.info("{}  EVAL".format(current.toString()))

            for adj in current.movable:
                skipMt = adj.isMountain or (adj.isCity and adj.player == -1)
                skipSearching = adj.player == searchingPlayer
                # 2 is very important unless army amounts get fixed to not include tile val
                skipArmy = army - adj.army < 2
                skipVisited = adj in tileSet or adj in negativeTiles
                skipIt = skipMt or skipSearching or skipArmy or skipVisited
                # if not noLog:
                #    logbook.info("    {}   {}  mt {}, player {}, army {} ({} - {} < 1), visitedNeg {}".format(adj.toString(), skipIt, skipMt, skipSearching, skipArmy, army, adj.army, skipVisited))
                if not skipIt:
                    validMoveCount += 1

            # validMoveCount = count(current.movable, lambda adj: not  and not adj.player == searchingPlayer and (not army - adj.army < 1) and not )
            if validMoveCount > 0 and dist < maxDepth:
                # if not noLog:
                #    logbook.info("{} SKIPPED VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
                return None
            # if not noLog:
            #    logbook.info("{} VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
            return oldValFunc(current, prioVals)

        valueFunc = newValFunc

    if searchingPlayer == -2:
        searchingPlayer = map.player_index

    if priorityFunc is None:
        # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
        def default_priority_func(nextTile, currentPriorityObject):
            (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
            dist += 1
            if nextTile.isCity:
                negCityCount -= 1
            if nextTile.player != searchingPlayer and (
                    nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
                negEnemyTileCount -= 1

            if negativeTiles is None or next not in negativeTiles:
                if nextTile.player == searchingPlayer:
                    negArmySum -= nextTile.army
                else:
                    negArmySum += nextTile.army
            # always leaving 1 army behind. + because this is negative.
            negArmySum += 1
            # -= because we passed it in positive for our general and negative for enemy gen / cities
            negArmySum -= goalIncrement
            return dist, negCityCount, negEnemyTileCount, negArmySum, sumX + nextTile.x, sumY + nextTile.y, goalIncrement

        priorityFunc = default_priority_func
    frontier = PriorityQueue()

    globalVisitedSet = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            startList = list()
            startList.append((tile, startVal))
            frontier.put((startVal, distance, tile, None, startList))
    else:
        for tile in startTiles:
            if priorityFunc != default_priority_func:
                raise AssertionError(
                    "yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
            if tile.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            dist = 0
            negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0

            if not ignoreStartTile and tile.isCity:
                negCityCount = -1
            if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
                negEnemyTileCount = -1
            if not ignoreStartTile and tile.player == searchingPlayer:
                negArmySum = 1 - tile.army
            else:
                negArmySum = tile.army + 1
            if not ignoreStartTile:
                if tile.player != -1 and tile.isCity or tile.isGeneral:
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            startList = list()
            startList.append((tile, startVal))
            frontier.put((startVal, dist, tile, None, startList))

    start = time.perf_counter()
    iter = 0
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    maxValue = None
    maxPrio = None
    maxList = None

    current: Tile = None
    next: Tile = None

    while not frontier.empty():
        iter += 1
        if (iter & 128 == 0
            and time.perf_counter() - start > maxTime
                # and not BYPASS_TIMEOUTS_FOR_DEBUGGING
        ) or iter > maxIterations:
            logbook.info(f"BFS-DYNAMIC-MAX BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
            break

        (prioVals, dist, current, parent, nodeList) = frontier.get()
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
        if useGlobalVisitedSet:
            if current in globalVisitedSet:
                continue
            globalVisitedSet.add(current)
        if skipTiles is not None and current in skipTiles:
            continue

        newValue = valueFunc(current, prioVals) if not includePath else valueFunc(current, prioVals, nodeList)
        # if logResultValues:
        #    logbook.info("Tile {} value?: [{}]".format(current.toString(), '], ['.join(str(x) for x in newValue)))
        #    if parent != None:
        #        parentString = parent.toString()
        #    else:
        #        parentString = "None"
        if newValue is not None and (maxValue is None or newValue > maxValue):
            foundDist = dist
            if logResultValues:
                if parent is not None:
                    parentString = parent.toString()
                else:
                    parentString = "None"
                logbook.info(
                    f"+Tile {current.toString()} from {parentString} is new max value: [{'], ['.join('{:.3f}'.format(x) for x in newValue)}]  (dist {dist})")
            maxValue = newValue
            maxPrio = prioVals
            endNode = current
            maxList = nodeList
        # elif logResultValues:
        #        logbook.info("   Tile {} from {} was not max value: [{}]".format(current.toString(), parentString, '], ['.join(str(x) for x in newValue)))
        if dist > depthEvaluated:
            depthEvaluated = dist
            # stop when we either reach the max depth (this is dynamic from start tiles) or use up the remaining turns (as indicated by len(nodeList))
        if dist >= maxDepth or len(nodeList) > maxTurns:
            continue
        dist += 1
        for next in current.movable:  # new spots to try
            if next == parent and not allowDoubleBacks:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.player == -1 and next.isCity)
                    or (next.isUndiscoveredObstacle and noNeutralUndiscoveredObstacles)):
                continue
            nextVal = priorityFunc(next, prioVals) if not includePath else priorityFunc(next, prioVals, nodeList)
            if nextVal is not None:
                if boundFunc is not None:
                    bounded = boundFunc(next, nextVal, maxPrio) if not includePath else boundFunc(next, nextVal,
                                                                                                  maxPrio, nodeList)
                    if bounded:
                        if not noLog:
                            logbook.info(f"Bounded off {next.toString()}")
                        continue
                if skipFunc is not None:
                    skip = skipFunc(next, nextVal) if not includePath else skipFunc(next, nextVal, nodeList)
                    if skip:
                        continue
                newNodeList = list(nodeList)
                newNodeList.append((next, nextVal))
                frontier.put((nextVal, dist, next, current, newNodeList))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        if includePathValue:
            return None, None
        return None

    tile = endNode
    dist = foundDist
    pathObject = Path()
    for tileTuple in maxList:
        tile, prioVal = tileTuple
        if tile is not None:
            if not noLog:
                if prioVal is not None:
                    prioStr = '] ['.join(str(x) for x in prioVal)
                    logbook.info(f"  PATH TILE {str(tile)}: Prio [{prioStr}]")
                else:
                    logbook.info(f"  PATH TILE {str(tile)}: Prio [None]")
            # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
            pathObject.add_next(tile)

    # while (node != None):
    #     army, node = visited[node.x][node.y][dist]
    #     if (node != None):
    #         dist -= 1
    #         path = PathNode(node, path, army, dist, -1, None)
    pathNegs = negativeTiles
    if ignoreStartTile:
        pathNegs = negativeTiles.union(startTiles)
    pathObject.calculate_value(
        searchingPlayer,
        teams=map._teams,
        negativeTiles=pathNegs,
        ignoreNonPlayerArmy=ignoreNonPlayerArmy,
        incrementBackwards=incrementBackward,
        ignoreIncrement=ignoreIncrement)

    if priorityMatrix:
        for tile in pathObject.tileList:
            pathObject.value += priorityMatrix[tile]

    if pathObject.length == 0:
        if not noLog:
            logbook.info(
                f"BFS-DYNAMIC-MAX FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}, returning NONE!\n   {pathObject.toString()}")
        if includePathValue:
            return None, None
        return None
    else:
        if not noLog:
            logbook.info(
                f"BFS-DYNAMIC-MAX FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject.toString()}")
    if includePathValue:
        return pathObject, maxValue
    return pathObject


def breadth_first_dynamic_max_per_tile(
        map,
        startTiles: typing.Union[typing.List[Tile], typing.Dict[Tile, typing.Tuple[object, int]]],
        valueFunc,  # higher is better
        maxTime=0.2,
        maxTurns=100,
        maxDepth=100,
        noNeutralCities=False,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,  # lower is better
        skipFunc=None,  # evaluation to true will refuse to even path through the tile
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        logResultValues=False,
        noLog=True,
        fullOnly=False,
        fullOnlyArmyDistFunc=None,
        boundFunc=None,
        maxIterations: int = INF,
        allowDoubleBacks=False,
        includePath=False,
        priorityMatrix: MapMatrix[float] | None = None,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        useGlobalVisitedSet: bool = True
) -> typing.Dict[Tile, Path]:
    """
    Keeps the max path from each of the start tiles as output. Since we force use a global visited set, the paths returned will never overlap each other.

    @param map:
    @param startTiles: startTiles dict is (startPriorityObject, distance) = startTiles[tile]
    @param valueFunc:
    @param maxTime:
    @param maxDepth:
    @param noNeutralCities:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc: priorityFunc is (nextTile, currentPriorityObject) -> nextPriorityObject
    @param skipFunc:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param logResultValues:
    @param noLog:
    @param fullOnly:
    @param fullOnlyArmyDistFunc:
    @param boundFunc: boundFunc is (currentTile, currentPiorityObject, maxPriorityObject) -> True (prune) False (continue)
    @param maxIterations:
    @param allowDoubleBacks:
    @param includePath:  if True, all the functions take a path object param as third tuple entry
    @param ignoreNonPlayerArmy: if True, the paths returned will be calculated on the basis of just the searching players army and ignore enemy (or neutral city!) army they pass through.
    @param ignoreIncrement: if True, do not have paths returned include the city increment in their path calculation for any cities or generals in the path.
    @param useGlobalVisitedSet: prevent a tile from ever being popped more than once in a search. Use this when your priority function guarantees that the best path that uses a tile is also guaranteed to be reached first in the search.
    @return:

    # make sure to initialize the initial base values and account for first priorityObject being None.
    def default_priority_func(nextTile, currentPriorityObject):
        dist = -1
        negCityCount = negEnemyTileCount = negArmySum = x = y = 0
        if currentPriorityObject != None:
            (dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and nextTile.player != -1:
            negEnemyTileCount -= 1
        if nextTile.player == searchingPlayer:
            negArmySum -= nextTile.army - 1
        else:
            negArmySum += nextTile.army + 1
        return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
    """
    if negativeTiles is None:
        negativeTiles = set()

    # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
    def default_priority_func(nextTile, currentPriorityObject):
        (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and (
                nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
            negEnemyTileCount -= 1

        if negativeTiles is None or next not in negativeTiles:
            if nextTile.player == searchingPlayer:
                negArmySum -= nextTile.army
            else:
                negArmySum += nextTile.army
        # always leaving 1 army behind. + because this is negative.
        negArmySum += 1
        # -= because we passed it in positive for our general and negative for enemy gen / cities
        negArmySum -= goalIncrement
        return dist, negCityCount, negEnemyTileCount, negArmySum, sumX + nextTile.x, sumY + nextTile.y, goalIncrement

    if fullOnly:
        oldValFunc = valueFunc

        def newValFunc(current, prioVals):
            army, dist, tileSet = fullOnlyArmyDistFunc(current, prioVals)

            validMoveCount = 0
            # if not noLog:
            #    logbook.info("{}  EVAL".format(current.toString()))

            for adj in current.movable:
                skipMt = adj.isMountain or (adj.isCity and adj.player == -1)
                skipSearching = adj.player == searchingPlayer
                # 2 is very important unless army amounts get fixed to not include tile val
                skipArmy = army - adj.army < 2
                skipVisited = adj in tileSet or adj in negativeTiles
                skipIt = skipMt or skipSearching or skipArmy or skipVisited
                # if not noLog:
                #    logbook.info("    {}   {}  mt {}, player {}, army {} ({} - {} < 1), visitedNeg {}".format(adj.toString(), skipIt, skipMt, skipSearching, skipArmy, army, adj.army, skipVisited))
                if not skipIt:
                    validMoveCount += 1

            # validMoveCount = count(current.movable, lambda adj: not  and not adj.player == searchingPlayer and (not army - adj.army < 1) and not )
            if validMoveCount > 0 and dist < maxDepth:
                # if not noLog:
                #    logbook.info("{} SKIPPED VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
                return None
            # if not noLog:
            #    logbook.info("{} VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
            return oldValFunc(current, prioVals)

        valueFunc = newValFunc

    if searchingPlayer == -2:
        searchingPlayer = map.player_index
    if priorityFunc is None:
        priorityFunc = default_priority_func
    frontier = PriorityQueue()

    globalVisitedSet = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            startList = list()
            startList.append((tile, startVal))
            frontier.put((startVal, distance, tile, None, startList, tile))
    else:
        for tile in startTiles:
            if priorityFunc != default_priority_func:
                raise AssertionError(
                    "yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
            if tile.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            dist = 0
            negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0

            if not ignoreStartTile and tile.isCity:
                negCityCount = -1
            if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
                negEnemyTileCount = -1
            if not ignoreStartTile and tile.player == searchingPlayer:
                negArmySum = 1 - tile.army
            else:
                negArmySum = tile.army + 1
            if not ignoreStartTile:
                if tile.player != -1 and tile.isCity or tile.isGeneral:
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            startList = list()
            startList.append((tile, startVal))
            frontier.put((startVal, dist, tile, None, startList, tile))

    start = time.perf_counter()
    iter = 0
    foundDist = 1000
    depthEvaluated = 0
    maxValues: typing.Dict[Tile, typing.Any] = {}
    maxPrios: typing.Dict[Tile, typing.Any] = {}
    maxLists: typing.Dict[Tile, typing.List[typing.Tuple[Tile, typing.Any]]] = {}
    endNodes: typing.Dict[Tile, Tile] = {}

    while not frontier.empty():
        iter += 1
        if iter & 64 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
            logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
            break

        (prioVals, dist, current, parent, nodeList, startTile) = frontier.get()
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
        if useGlobalVisitedSet:
            if current in globalVisitedSet:
                continue
            globalVisitedSet.add(current)
        if skipTiles is not None and current in skipTiles:
            continue

        newValue = valueFunc(current, prioVals) if not includePath else valueFunc(current, prioVals, nodeList)
        # if logResultValues:
        #    logbook.info("Tile {} value?: [{}]".format(current.toString(), '], ['.join(str(x) for x in newValue)))
        #    if parent != None:
        #        parentString = parent.toString()
        #    else:
        #        parentString = "None"

        if newValue is not None and (startTile not in maxValues or newValue > maxValues[startTile]):
            foundDist = dist
            if logResultValues:
                if parent is not None:
                    parentString = parent.toString()
                else:
                    parentString = "None"
                valStr = '], ['.join('{:.3f}'.format(x) for x in newValue)
                logbook.info(
                    f"+Tile {current.toString()} from {parentString} is new max value: [{valStr}]  (dist {dist})")
            maxValues[startTile] = newValue
            maxPrios[startTile] = prioVals
            endNodes[startTile] = current
            maxLists[startTile] = nodeList
        # elif logResultValues:
        #        logbook.info("   Tile {} from {} was not max value: [{}]".format(current.toString(), parentString, '], ['.join(str(x) for x in newValue)))
        if dist > depthEvaluated:
            depthEvaluated = dist
        if dist >= maxDepth or len(nodeList) > maxTurns:
            continue
        dist += 1
        for next in current.movable:  # new spots to try
            if next == parent and not allowDoubleBacks:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.player == -1 and next.isCity)
                    or (not next.discovered and next.isNotPathable)):
                continue
            nextPrio = priorityFunc(next, prioVals) if not includePath else priorityFunc(next, prioVals, nodeList)
            if nextPrio is not None:
                # TODO we're bounding per tile, not globally, seems questionable.

                if boundFunc is not None:
                    boundPrio = maxPrios.get(startTile, None)
                    if boundPrio is not None:
                        if not includePath:
                            bounded = boundFunc(next, nextPrio, boundPrio)
                        else:
                            bounded = boundFunc(next, nextPrio, boundPrio, nodeList)
                        if bounded:
                            if not noLog:
                                logbook.info(f"Bounded off {next.toString()}")
                            continue
                if skipFunc is not None:
                    skip = skipFunc(next, nextPrio) if not includePath else skipFunc(next, nextPrio, nodeList)
                    if skip:
                        continue
                newNodeList = list(nodeList)
                newNodeList.append((next, nextPrio))
                frontier.put((nextPrio, dist, next, current, newNodeList, startTile))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return {}


    pathNegs = negativeTiles
    negWithStart = negativeTiles.union(startTiles)

    if ignoreStartTile:
        pathNegs = negWithStart

    maxPaths: typing.Dict[Tile, Path] = {}
    for startTile in maxValues.keys():
        tile = endNodes[startTile]
        pathObject = Path()
        maxList = maxLists[startTile]
        for tileTuple in maxList:
            tile, prioVal = tileTuple
            if tile is not None:
                if not noLog:
                    if prioVal is not None:
                        prioStr = ']\t['.join(str(x) for x in prioVal)
                        logbook.info(f"  PATH TILE {str(tile)}: Prio [{prioStr}]")
                    else:
                        logbook.info(f"  PATH TILE {str(tile)}: Prio [None]")
                # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
                pathObject.add_next(tile)
        maxPaths[startTile] = pathObject

        pathObject.calculate_value(
            searchingPlayer,
            teams=map._teams,
            negativeTiles=pathNegs,
            ignoreNonPlayerArmy=ignoreNonPlayerArmy,
            incrementBackwards=incrementBackward,
            ignoreIncrement=ignoreIncrement)

        if priorityMatrix:
            for tile in pathObject.tileList:
                pathObject.value += priorityMatrix[tile]

        if pathObject.length == 0:
            if not noLog:
                logbook.info(
                    f"BFS-DYNAMIC-MAX-PER-TILE FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}, returning NONE!\n   {pathObject.toString()}")
            continue
        else:
            if not noLog:
                logbook.info(
                    f"BFS-DYNAMIC-MAX-PER-TILE FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject.toString()}")

    return maxPaths


def breadth_first_dynamic_max_per_tile_per_distance(
        map,
        startTiles: typing.Union[typing.List[Tile], typing.Dict[Tile, typing.Tuple[object, int]]],
        valueFunc,  # higher is better
        maxTime=0.2,
        maxTurns=100,
        maxDepth=100,
        noNeutralCities=False,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,  # lower is better
        skipFunc=None,  # evaluation to true will refuse to even path through the tile
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        logResultValues=False,
        noLog=True,
        fullOnly=False,
        fullOnlyArmyDistFunc=None,
        boundFunc=None,
        maxIterations: int = INF,
        allowDoubleBacks=False,
        includePath=False,
        priorityMatrix: MapMatrix[float] | None = None,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        useGlobalVisitedSet: bool = True
) -> typing.Dict[Tile, typing.List[Path]]:
    """
    Keeps the max path from each of the start tiles as output. Since we force use a global visited set, the paths returned will never overlap each other.
    For each start tile, returns a dict from found distances to the max value found at that distance.
    Does not return paths for a tile that are a longer distance but the same value as a shorter one, so no need to prune them yourself.

    @param map:
    @param startTiles: startTiles dict is (startPriorityObject, distance) = startTiles[tile]
    @param valueFunc:
    @param maxTime:
    @param maxDepth:
    @param noNeutralCities:
    @param negativeTiles:
    @param skipTiles:
    @param searchingPlayer:
    @param priorityFunc: priorityFunc is (nextTile, currentPriorityObject) -> nextPriorityObject
    @param skipFunc:
    @param ignoreStartTile:
    @param incrementBackward:
    @param preferNeutral:
    @param logResultValues:
    @param noLog:
    @param fullOnly:
    @param fullOnlyArmyDistFunc:
    @param boundFunc: boundFunc is (currentTile, currentPiorityObject, maxPriorityObject) -> True (prune) False (continue)
    @param maxIterations:
    @param allowDoubleBacks:
    @param includePath:  if True, all the functions take a path object param as third tuple entry
    @param ignoreNonPlayerArmy: if True, the paths returned will be calculated on the basis of just the searching players army and ignore enemy (or neutral city!) army they pass through.
    @param ignoreIncrement: if True, do not have paths returned include the city increment in their path calculation for any cities or generals in the path.
    @param useGlobalVisitedSet: prevent a tile from ever being popped more than once in a search. Use this when your priority function guarantees that the best path that uses a tile is also guaranteed to be reached first in the search.
    @return:

    # make sure to initialize the initial base values and account for first priorityObject being None.
    def default_priority_func(nextTile, currentPriorityObject):
        dist = -1
        negCityCount = negEnemyTileCount = negArmySum = x = y = 0
        if currentPriorityObject != None:
            (dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and nextTile.player != -1:
            negEnemyTileCount -= 1
        if nextTile.player == searchingPlayer:
            negArmySum -= nextTile.army - 1
        else:
            negArmySum += nextTile.army + 1
        return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
    """
    if negativeTiles is None:
        negativeTiles = set()

    # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
    def default_priority_func(nextTile, currentPriorityObject):
        (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and (
                nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
            negEnemyTileCount -= 1

        if negativeTiles is None or next not in negativeTiles:
            if nextTile.player == searchingPlayer:
                negArmySum -= nextTile.army
            else:
                negArmySum += nextTile.army
        # always leaving 1 army behind. + because this is negative.
        negArmySum += 1
        # -= because we passed it in positive for our general and negative for enemy gen / cities
        negArmySum -= goalIncrement
        return dist, negCityCount, negEnemyTileCount, negArmySum, sumX + nextTile.x, sumY + nextTile.y, goalIncrement

    if fullOnly:
        oldValFunc = valueFunc

        def newValFunc(current, prioVals):
            army, dist, tileSet = fullOnlyArmyDistFunc(current, prioVals)

            validMoveCount = 0
            # if not noLog:
            #    logbook.info("{}  EVAL".format(current.toString()))

            for adj in current.movable:
                skipMt = adj.isMountain or (adj.isCity and adj.player == -1)
                skipSearching = adj.player == searchingPlayer
                # 2 is very important unless army amounts get fixed to not include tile val
                skipArmy = army - adj.army < 2
                skipVisited = adj in tileSet or adj in negativeTiles
                skipIt = skipMt or skipSearching or skipArmy or skipVisited
                # if not noLog:
                #    logbook.info("    {}   {}  mt {}, player {}, army {} ({} - {} < 1), visitedNeg {}".format(adj.toString(), skipIt, skipMt, skipSearching, skipArmy, army, adj.army, skipVisited))
                if not skipIt:
                    validMoveCount += 1

            # validMoveCount = count(current.movable, lambda adj: not  and not adj.player == searchingPlayer and (not army - adj.army < 1) and not )
            if validMoveCount > 0 and dist < maxDepth:
                # if not noLog:
                #    logbook.info("{} SKIPPED VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
                return None
            # if not noLog:
            #    logbook.info("{} VALUE, moveCt {}, dist {}, maxDepth {}".format(current.toString(), validMoveCount, dist, maxDepth))
            return oldValFunc(current, prioVals)

        valueFunc = newValFunc

    if searchingPlayer == -2:
        searchingPlayer = map.player_index
    if priorityFunc is None:
        priorityFunc = default_priority_func
    frontier = PriorityQueue()

    globalVisitedSet = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            startList = list()
            startList.append((tile, startVal))
            frontier.put((startVal, distance, tile, None, startList, tile))
    else:
        for tile in startTiles:
            if priorityFunc != default_priority_func:
                raise AssertionError(
                    "yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
            if tile.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            dist = 0
            negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0

            if not ignoreStartTile and tile.isCity:
                negCityCount = -1
            if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
                negEnemyTileCount = -1
            if not ignoreStartTile and tile.player == searchingPlayer:
                negArmySum = 1 - tile.army
            else:
                negArmySum = tile.army + 1
            if not ignoreStartTile:
                if tile.player != -1 and tile.isCity or tile.isGeneral:
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            startList = list()
            startList.append((tile, startVal))
            frontier.put((startVal, dist, tile, None, startList, tile))

    start = time.perf_counter()
    iter = 0
    foundDist = 1000
    depthEvaluated = 0
    maxValuesTMP: typing.Dict[Tile, typing.Dict[int, typing.Any]] = {}
    maxPriosTMP: typing.Dict[Tile, typing.Dict[int, typing.Any]] = {}
    maxListsTMP: typing.Dict[Tile, typing.Dict[int, typing.List[typing.Tuple[Tile, typing.Any]]]] = {}
    endNodesTMP: typing.Dict[Tile, typing.Dict[int, Tile]] = {}

    while not frontier.empty():
        iter += 1
        if iter & 64 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
            logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE-PER-DIST BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
            break

        (prioVals, dist, current, parent, nodeList, startTile) = frontier.get()
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
        if useGlobalVisitedSet:
            if current in globalVisitedSet:
                continue
            globalVisitedSet.add(current)
            if skipTiles is not None and current in skipTiles:
                continue

        newValue = valueFunc(current, prioVals) if not includePath else valueFunc(current, prioVals, nodeList)
        # if logResultValues:
        #    logbook.info("Tile {} value?: [{}]".format(current.toString(), '], ['.join(str(x) for x in newValue)))
        #    if parent != None:
        #        parentString = parent.toString()
        #    else:
        #        parentString = "None"

        if newValue is not None:
            if startTile not in maxValuesTMP:
                maxValuesTMP[startTile] = {}
                maxPriosTMP[startTile] = {}
                endNodesTMP[startTile] = {}
                maxListsTMP[startTile] = {}
            maxMinusOne = maxValuesTMP[startTile].get(dist-1, None)
            if (dist not in maxValuesTMP[startTile] or newValue > maxValuesTMP[startTile][dist]) and (maxMinusOne is None or maxMinusOne < newValue):
                foundDist = min(foundDist, dist)
                if logResultValues:
                    if parent is not None:
                        parentString = parent.toString()
                    else:
                        parentString = "None"
                    logbook.info(
                        f"+Tile {current.toString()} from {parentString} for startTile {str(startTile)} at dist {dist} is new max value: [{'], ['.join('{:.3f}'.format(x) for x in newValue)}]")
                maxValuesTMP[startTile][dist] = newValue
                maxPriosTMP[startTile][dist] = prioVals
                endNodesTMP[startTile][dist] = current
                maxListsTMP[startTile][dist] = nodeList

        if dist > depthEvaluated:
            depthEvaluated = dist
        if dist >= maxDepth or len(nodeList) > maxTurns:
            continue
        dist += 1
        for next in current.movable:  # new spots to try
            if next == parent and not allowDoubleBacks:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.player == -1 and next.isCity)
                    or (not next.discovered and next.isNotPathable)):
                continue
            if next in globalVisitedSet:
                continue
            nextPrio = priorityFunc(next, prioVals) if not includePath else priorityFunc(next, prioVals, nodeList)
            if nextPrio is not None:
                if boundFunc is not None:
                    maxPrioDict = maxPriosTMP.get(startTile, None)
                    if maxPrioDict is not None:
                        maxPrioDist = maxPrioDict.get(dist - 1, None)
                        if maxPrioDist is not None:
                            if not includePath:
                                bounded = boundFunc(next, nextPrio, maxPrioDist)
                            else:
                                bounded = boundFunc(next, nextPrio, maxPrioDist, nodeList)

                            if bounded:
                                if not noLog:
                                    logbook.info(f"Bounded off {next.toString()}")
                                continue
                if skipFunc is not None:
                    skip = skipFunc(next, nextPrio) if not includePath else skipFunc(next, nextPrio, nodeList)
                    if skip:
                        continue
                newNodeList = list(nodeList)
                newNodeList.append((next, nextPrio))
                frontier.put((nextPrio, dist, next, current, newNodeList, startTile))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return {}

    maxPaths: typing.Dict[Tile, typing.List[Path]] = {}
    negWithStart = negativeTiles.union(startTiles)

    pathNegs = negativeTiles
    if ignoreStartTile:
        pathNegs = negWithStart

    for startTile in maxValuesTMP.keys():
        pathListForTile = []
        for dist in maxValuesTMP[startTile].keys():
            pathObject = Path()
            # # prune any paths that are not higher value than the shorter path.
            # # THIS WOULD PRUNE LOWER VALUE PER TURN PATHS THAT ARE LONGER, WHICH IS ONLY OK IF WE ALWAYS DO PARTIAL LAYERS OF THE FULL GATHER...
            # if dist - 1 in maxValuesTMP[startTile]:
            #     shorterVal = maxValuesTMP[startTile][dist - 1]
            #     if maxValuesTMP[startTile][dist] <= shorterVal:
            #         logbook.info(f"  PRUNED PATH TO {str(startTile)} at dist {dist} because its value {shorterVal} was same or less than shorter dists value")
            #         continue

            maxList = maxListsTMP[startTile][dist]
            for tileTuple in maxList:
                tile, prioVal = tileTuple
                if tile is not None:
                    if not noLog:
                        if prioVal is not None:
                            prioStr = ']\t['.join(str(x) for x in prioVal)
                            logbook.info(f"  PATH TILE {str(tile)}: Prio [{prioStr}]")
                        else:
                            logbook.info(f"  PATH TILE {str(tile)}: Prio [None]")
                    # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
                    pathObject.add_next(tile)

            pathObject.calculate_value(
                searchingPlayer,
                teams=map._teams,
                negativeTiles=pathNegs,
                ignoreNonPlayerArmy=ignoreNonPlayerArmy,
                incrementBackwards=incrementBackward,
                ignoreIncrement=ignoreIncrement)

            if priorityMatrix:
                for tile in pathObject.tileList:
                    pathObject.value += priorityMatrix[tile]

            if pathObject.length == 0:
                if not noLog:
                    logbook.info(
                        f"BFS-DYNAMIC-MAX-PER-TILE FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}, returning NONE!\n   {pathObject.toString()}")
                continue
            else:
                if not noLog:
                    logbook.info(
                        f"BFS-DYNAMIC-MAX-PER-TILE FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject.toString()}")
            pathListForTile.append(pathObject)
        maxPaths[startTile] = pathListForTile
    return maxPaths

def bidirectional_breadth_first_dynamic(
        map,
        startTiles,
        goalFunc,
        maxTime=0.2,
        maxDepth=100,
        noNeutralCities=False,
        negativeTiles=None,
        skipTiles=None,
        searchingPlayer=-2,
        priorityFunc=None,
        skipFunc=None,
        ignoreStartTile=False,
        incrementBackward=False,
        preferNeutral=False,
        allowDoubleBacks=False):
    """
    THIS isn't implemented yet...?

    startTiles dict is (startPriorityObject, distance) = startTiles[tile]
    goalFunc is (currentTile, priorityObject) -> True or False
    priorityFunc is (nextTile, currentPriorityObject) -> nextPriorityObject

    # make sure to initialize the initial base values and account for first priorityObject being None.
    def default_priority_func(nextTile, currentPriorityObject):
        dist = -1
        negCityCount = negEnemyTileCount = negArmySum = x = y = 0
        if currentPriorityObject != None:
            (dist, negCityCount, negEnemyTileCount, negArmySum, x, y) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and nextTile.player != -1:
            negEnemyTileCount -= 1
        if nextTile.player == searchingPlayer:
            negArmySum -= nextTile.army - 1
        else:
            negArmySum += nextTile.army + 1
        return (dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y)
    """
    if negativeTiles is None:
        negativeTiles = set()

    # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
    def default_priority_func(nextTile, currentPriorityObject):
        (dist, negCityCount, negEnemyTileCount, negArmySum, x, y, goalIncrement) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and (
                nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
            negEnemyTileCount -= 1

        if negativeTiles is None or next not in negativeTiles:
            if nextTile.player == searchingPlayer:
                negArmySum -= nextTile.army
            else:
                negArmySum += nextTile.army
        # always leaving 1 army behind. + because this is negative.
        negArmySum += 1
        # -= because we passed it in positive for our general and negative for enemy gen / cities
        negArmySum -= goalIncrement
        return dist, negCityCount, negEnemyTileCount, negArmySum, nextTile.x, nextTile.y, goalIncrement

    if searchingPlayer == -2:
        searchingPlayer = map.player_index
    if priorityFunc is None:
        priorityFunc = default_priority_func
    frontier = PriorityQueue()
    visited = [[{} for x in range(map.rows)] for y in range(map.cols)]
    globalVisitedSet = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            frontier.put((startVal, distance, tile, None))
    else:
        for tile in startTiles:
            if priorityFunc != default_priority_func:
                raise AssertionError(
                    "yo you need to do the dictionary start if you're gonna pass a nonstandard priority func.")
            if tile.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            dist = 0
            negCityCount = negEnemyTileCount = negArmySum = x = y = goalIncrement = 0

            if not ignoreStartTile and tile.isCity:
                negCityCount = -1
            if not ignoreStartTile and tile.player != searchingPlayer and tile.player != -1:
                negEnemyTileCount = -1
            if not ignoreStartTile and tile.player == searchingPlayer:
                negArmySum = 1 - tile.army
            else:
                negArmySum = tile.army + 1
            if not ignoreStartTile:
                if tile.player != -1 and tile.isCity or tile.isGeneral:
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            frontier.put((startVal, dist, tile, None))
    start = time.perf_counter()
    iter = 0
    foundGoal = False
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    foundVal = None
    while not frontier.empty():
        iter += 1
        if iter % 1000 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING:
            logbook.info("BI-DIR BREAKING")
            break

        (prioVals, dist, current, parent) = frontier.get()
        if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
            visited[current.x][current.y][dist] = (prioVals, parent)
        # TODO no globalVisitedSet
        if current in globalVisitedSet or (skipTiles is not None and current in skipTiles):
            continue
        globalVisitedSet.add(current)
        if goalFunc(current, prioVals) and (foundVal is None or prioVals < foundVal):
            foundGoal = True
            foundDist = dist
            foundVal = prioVals
            endNode = current
        if dist > depthEvaluated:
            depthEvaluated = dist
            if foundGoal:
                break
        if dist <= maxDepth and not foundGoal:
            for next in current.movable:  # new spots to try
                if next == parent and not allowDoubleBacks:
                    continue
                if (next.isMountain
                        or (noNeutralCities and next.player == -1 and next.isCity)
                        or (not next.discovered and next.isNotPathable)):
                    continue
                newDist = dist + 1
                nextVal = priorityFunc(next, prioVals)
                if skipFunc is not None and skipFunc(next, nextVal):
                    continue
                frontier.put((nextVal, newDist, next, current))

    logbook.info(
        f"BI-DIR BFS-FIND ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return None

    tile = endNode
    dist = foundDist
    tileList = []
    # logbook.info(json.dumps(visited))
    # logbook.info("PPRINT FULL")
    # logbook.info(pformat(visited))

    while tile is not None:
        # logbook.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
        tileList.append(tile)

        # logbook.info(pformat(visited[node.x][node.y]))
        (prioVal, tile) = visited[tile.x][tile.y][dist]
        dist -= 1
    pathObject = Path()
    for tile in reversed(tileList):
        if tile is not None:
            # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
            pathObject.add_next(tile)

    # while (node != None):
    #     army, node = visited[node.x][node.y][dist]
    #     if (node != None):
    #         dist -= 1
    #         path = PathNode(node, path, army, dist, -1, None)
    pathObject.calculate_value(searchingPlayer, teams=map._teams, incrementBackwards=incrementBackward)
    logbook.info(
        f"BI-DIR DYNAMIC BFS FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject.toString()}")
    return pathObject


def breadth_first_find_queue(
        map,
        startTiles,
        goalFunc: typing.Callable[[Tile, int, int], int],
        maxTime=0.1,
        maxDepth=20,
        noNeutralCities=False,
        negativeTiles=None,
        skipTiles=None,
        bypassDefaultSkipLogic: bool = False,
        searchingPlayer=-2,
        ignoreStartTile=False,
        prioFunc: typing.Callable[[Tile], typing.Any] | None = None,
        noLog: bool = False,
) -> Path | None:
    """
    goalFunc is goalFunc(current, army, dist)
    prioFunc is prioFunc(tile) - bigger is better, tuples supported, True comes before False etc.
    bypassDefaultSkipLogic allows you to search through undiscovered mountains etc.
    """

    if searchingPlayer == -2:
        searchingPlayer = map.player_index

    frontier = deque()
    nodeValues = [[None for x in range(map.rows)] for y in range(map.cols)]
    visited: typing.Set[Tile] = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startDist, startArmy) = startTiles[tile]
            if tile.isMountain and not bypassDefaultSkipLogic:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            goalInc = 0
            if (tile.isCity or tile.isGeneral) and tile.player != -1:
                goalInc = -0.5
            startArmy = tile.army - 1
            if tile.player != searchingPlayer:
                startArmy = 0 - tile.army - 1
                goalInc = -1 * goalInc
            if ignoreStartTile:
                startArmy = 0
            nodeValues[tile.x][tile.y] = (startArmy, None)
            frontier.appendleft((tile, startDist, startArmy, goalInc))
    else:
        for tile in startTiles:
            if tile.isMountain and not bypassDefaultSkipLogic:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            goalInc = 0
            startArmy = tile.army - 1
            if tile.player != searchingPlayer:
                startArmy = 0 - tile.army - 1
            nodeValues[tile.x][tile.y] = (startArmy, None)
            if (tile.isCity or tile.isGeneral) and tile.player != -1:
                goalInc = 0.5
            if ignoreStartTile:
                startArmy = 0
            frontier.appendleft((tile, 0, startArmy, goalInc))
    iter = 0
    start = time.perf_counter()
    foundGoal = False
    foundArmy = -100000
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    while len(frontier) > 0:
        iter += 1
        (current, dist, army, goalInc) = frontier.pop()
        if current in visited or (skipTiles is not None and current in skipTiles):
            continue
        visited.add(current)
        if goalFunc(current, army, dist) and (dist < foundDist or (dist == foundDist and army > foundArmy)):
            foundGoal = True
            foundDist = dist
            foundArmy = army
            endNode = current
        if dist > depthEvaluated:
            depthEvaluated = dist
            if foundGoal:
                break
        if dist <= maxDepth and not foundGoal:
            nextSearch = current.movable
            if prioFunc is not None:
                nextSearch = sorted(current.movable, key=prioFunc, reverse=True)
            for next in nextSearch:  # new spots to try
                if (
                    (
                        not bypassDefaultSkipLogic
                        and (
                            next.isMountain
                            or (noNeutralCities and next.isCity and next.player == -1)
                            or (not next.discovered and next.isNotPathable)
                        )
                    )
                    or next in visited
                ):
                    continue

                inc = 0 if not ((next.isCity and next.player != -1) or next.isGeneral) else dist / 2
                # new_cost = cost_so_far[current] + graph.cost(current, next)
                nextArmy = army - 1
                if negativeTiles is None or next not in negativeTiles:
                    if searchingPlayer == next.player:
                        nextArmy += next.army + inc
                    else:
                        nextArmy -= (next.army + inc)
                newDist = dist + 1
                if nodeValues[next.x][next.y] is None or nodeValues[next.x][next.y][0] < nextArmy:
                    nodeValues[next.x][next.y] = (nextArmy, current)
                frontier.appendleft((next, newDist, nextArmy, goalInc))

    if not noLog:
        logbook.info(
            f"BFS-FIND-QUEUE ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.3f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return None

    node = endNode
    dist = foundDist
    nodes = []
    army = foundArmy
    # logbook.info(json.dumps(visited))
    # logbook.info("PPRINT FULL")
    # logbook.info(pformat(visited))

    while node is not None:
        # logbook.info("ARMY {} NODE {},{}  DIST {}".format(army, node.x, node.y, dist))
        nodes.append((army, node))

        # logbook.info(pformat(visited[node.x][node.y]))
        (army, node) = nodeValues[node.x][node.y]
        dist -= 1
    nodes.reverse()
    (startArmy, startNode) = nodes[0]
    pathObject = Path(foundArmy)
    pathObject.add_next(startNode)
    dist = foundDist
    for i, armyNode in enumerate(nodes[1:]):
        (curArmy, curNode) = armyNode
        if curNode is not None:
            # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
            pathObject.add_next(curNode)
            dist -= 1

    # while (node != None):
    #     army, node = visited[node.x][node.y]
    #     if (node != None):
    #         dist -= 1
    #         path = PathNode(node, path, army, dist, -1, None)

    if not noLog:
        logbook.info(
            f"BFS-FIND-QUEUE found path OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    return pathObject


def breadth_first_foreach(map: MapBase, startTiles, maxDepth, foreachFunc, negativeFunc=None, skipFunc=None,
                          skipTiles=None, noLog=False, bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Skip func runs AFTER the foreach func is evaluated.
    Same as breath_first_foreach_dist, except the foreach function does not get the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc:
    @param negativeFunc:
    @param skipFunc: Evaluated BEFORE the foreach runs on a tile
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = deque()
    globalVisited = new_value_grid(map, False)
    if skipTiles is not None:
        for tile in skipTiles:
            if not noLog:
                logbook.info(f"    skipTiles contained {tile.toString()}")
            globalVisited[tile.x][tile.y] = True

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    if negativeFunc is not None:
        oldForeachFunc = foreachFunc

        def newFunc(tile):
            if not negativeFunc(tile):
                oldForeachFunc(tile)

        foreachFunc = newFunc

    start = time.perf_counter()
    iter = 0
    depthEvaluated = 0
    dist = 0
    while len(frontier) > 0:
        iter += 1

        (current, dist) = frontier.pop()
        if globalVisited[current.x][current.y]:
            continue
        if dist > maxDepth:
            break
        globalVisited[current.x][current.y] = True
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)) and dist > 0:
            continue
        foreachFunc(current)
        # intentionally placed after the foreach func, skipped tiles are still foreached, they just aren't traversed
        if skipFunc is not None and skipFunc(current):
            continue
        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach. startTiles[0] {startTiles[0].x},{startTiles[0].y}: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def breadth_first_foreach_dist(
        map: MapBase,
        startTiles: typing.List[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], None],
        negativeFunc: typing.Callable[[Tile], bool] | None = None,
        skipFunc: typing.Callable[[Tile], bool] | None = None,
        skipTiles: typing.Set[Tile] = None,
        noLog=False,
        bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Skip func runs AFTER the foreach func is evaluated.
    Same as breath_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc:
    @param negativeFunc:
    @param skipFunc: Evaluated AFTER the foreach runs on a tile
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = deque()
    globalVisited = new_value_grid(map, False)
    if skipTiles is not None:
        for tile in skipTiles:
            globalVisited[tile.x][tile.y] = True

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    if negativeFunc is not None:
        oldForeachFunc = foreachFunc

        def newFunc(tile, dist):
            if not negativeFunc(tile):
                oldForeachFunc(tile, dist)

        foreachFunc = newFunc

    start = time.perf_counter()
    iter = 0
    dist = 0
    while len(frontier) > 0:
        iter += 1

        (current, dist) = frontier.pop()
        if dist > maxDepth:
            break
        if globalVisited[current.x][current.y]:
            continue
        globalVisited[current.x][current.y] = True
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)):
            continue
        foreachFunc(current, dist)
        # intentionally placed after the foreach func, skipped tiles are still foreached, they just aren't traversed
        if skipFunc is not None and skipFunc(current):
            continue
        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach_dist. startTiles[0] {startTiles[0].x},{startTiles[0].y}: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")



def breadth_first_foreach_dist_revisit_callback(
        map: MapBase,
        startTiles: typing.List[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], None],
        revisitFunc: typing.Callable[[Tile, int], None],
        negativeFunc: typing.Callable[[Tile], bool] | None = None,
        skipFunc: typing.Callable[[Tile], bool] | None = None,
        skipTiles: typing.Set[Tile] = None,
        noLog=False,
        bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Skip func runs AFTER the foreach func is evaluated.
    Same as breath_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc:
    @param revisitFunc: Called when a node is popped from the queue at a different dist than its original
    @param negativeFunc:
    @param skipFunc: Evaluated AFTER the foreach runs on a tile
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = deque()
    globalVisited = new_value_grid(map, False)
    if skipTiles is not None:
        for tile in skipTiles:
            globalVisited[tile.x][tile.y] = True

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    if negativeFunc is not None:
        oldForeachFunc = foreachFunc

        def newFunc(tile, dist):
            if not negativeFunc(tile):
                oldForeachFunc(tile, dist)

        foreachFunc = newFunc

    start = time.perf_counter()
    iter = 0
    dist = 0
    while len(frontier) > 0:
        iter += 1

        (current, dist) = frontier.pop()
        if globalVisited[current.x][current.y]:
            continue
        if dist > maxDepth:
            break
        globalVisited[current.x][current.y] = True
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)):
            continue
        foreachFunc(current, dist)
        # intentionally placed after the foreach func, skipped tiles are still foreached, they just aren't traversed
        if skipFunc is not None and skipFunc(current):
            continue
        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach_dist. startTiles[0] {startTiles[0].x},{startTiles[0].y}: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def build_distance_map_incl_mountains(map, startTiles, skipTiles=None) -> typing.List[typing.List[int]]:
    distanceMap = new_value_grid(map, 1000)

    if skipTiles is None:
        skipTiles = None
    elif not isinstance(skipTiles, set):
        newSkipTiles = set()
        for tile in skipTiles:
            newSkipTiles.add(tile)
        skipTiles = newSkipTiles

    def bfs_dist_mapper(tile, dist):
        if dist < distanceMap[tile.x][tile.y]:
            distanceMap[tile.x][tile.y] = dist

    breadth_first_foreach_dist(map, startTiles, 1000, bfs_dist_mapper, skipTiles=skipTiles,
                               skipFunc=lambda tile: tile.isObstacle, bypassDefaultSkip=True)
    return distanceMap


def build_distance_map(map, startTiles, skipTiles=None) -> typing.List[typing.List[int]]:
    distanceMap = new_value_grid(map, 1000)

    if skipTiles is None:
        skipTiles = None
    elif not isinstance(skipTiles, set):
        newSkipTiles = set()
        for tile in skipTiles:
            newSkipTiles.add(tile)
        skipTiles = newSkipTiles

    def bfs_dist_mapper(tile, dist):
        if dist < distanceMap[tile.x][tile.y]:
            distanceMap[tile.x][tile.y] = dist

    breadth_first_foreach_dist(
        map,
        startTiles,
        1000,
        bfs_dist_mapper,
        skipTiles=skipTiles,
        skipFunc=lambda tile: tile.isNeutral and tile.isCity)
    return distanceMap


def build_distance_map_matrix(map, startTiles, skipTiles=None) -> MapMatrix[int]:
    distanceMap = MapMatrix(map, 1000)

    if skipTiles is None:
        skipTiles = None
    elif not isinstance(skipTiles, set):
        newSkipTiles = set()
        for tile in skipTiles:
            newSkipTiles.add(tile)
        skipTiles = newSkipTiles

    def bfs_dist_mapper(tile, dist):
        if dist < distanceMap[tile]:
            distanceMap[tile] = dist

    breadth_first_foreach_dist(
        map,
        startTiles,
        1000,
        bfs_dist_mapper,
        skipTiles=skipTiles,
        skipFunc=lambda tile: tile.isNeutral and tile.isCity)
    return distanceMap
