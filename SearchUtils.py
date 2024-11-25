"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""
import heapq
import types
from argparse import ArgumentError
from heapq import heappush, heappop

import logbook
import math
import typing
import time
from collections import deque

from heapq_max import heappush_max, heappop_max

import DebugHelper
# from numba import jit, float32, int64

from Interfaces import MapMatrixInterface, TileSet
from Path import Path
from test.test_float import INF
from base.client.tile import Tile
from base.client.map import MapBase
from MapMatrix import MapMatrix, MapMatrixSet

BYPASS_TIMEOUTS_FOR_DEBUGGING = False


T = typing.TypeVar('T')


class HeapQueue(typing.Generic[T]):
    """Create a Heap Priority Queue object."""

    def __init__(self):
        self.queue: typing.List[T] = []

    def __bool__(self):
        return len(self.queue) > 0

    def put(self, item: T):
        """Put an item into the queue."""
        heappush(self.queue, item)

    def get(self) -> T:
        """Remove and return an item from the queue."""
        return heappop(self.queue)

    # Override these methods to implement other queue organizations
    # (e.g. stack or priority queue).
    # These will only be called with appropriate locks held

    __class_getitem__ = classmethod(types.GenericAlias)


class HeapQueueMax(typing.Generic[T]):
    """
    Create a Heap Priority Queue object.

    Fastest way to empty check is
    while myHeapQMax.queue:
       ...

    Note the Min HeapQueue is much faster than this Max heapqueue.

    With integers only:
    20: HeapQueue 0.646 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueue 0.707 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueue 0.912 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueue 1.034 seconds (2500 runs of 2000 pushes + pops)

    20: HeapQueueMax 1.306 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueueMax 1.707 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueueMax 2.026 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueueMax 2.411 seconds (2500 runs of 2000 pushes + pops)

    With 5 pair tuple objects of bool, float, int, int, int:
    20: HeapQueue 0.727 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueue 0.898 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueue 1.264 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueue 1.551 seconds (2500 runs of 2000 pushes + pops)

    20: HeapQueueMax 1.498 seconds (250000 runs of 20 pushes + pops)
    100: HeapQueueMax 1.975 seconds (50000 runs of 100 pushes + pops)
    500: HeapQueueMax 2.494 seconds (10000 runs of 500 pushes + pops)
    2000: HeapQueueMax 3.026 seconds (2500 runs of 2000 pushes + pops)
    """

    def __init__(self):
        self.queue: typing.List[T] = []

    def __bool__(self):
        return len(self.queue) > 0

    def put(self, item: T):
        """Put an item into the queue."""
        heappush_max(self.queue, item)

    def get(self) -> T:
        """Remove and return an item from the queue."""
        return heappop_max(self.queue)

    # Override these methods to implement other queue organizations
    # (e.g. stack or priority queue).
    # These will only be called with appropriate locks held

    __class_getitem__ = classmethod(types.GenericAlias)


class Counter(object):
    def __init__(self, value):
        self.value = value

    def add(self, value):
        self.value = self.value + value

    def __repr__(self):
        return str(self.value)

    def __str__(self):
        return str(self.value)


def where(enumerable: typing.Iterable[T], filter_func: typing.Callable[[T], bool]):
    results = [item for item in enumerable if filter_func(item)]
    return results


def any_where(enumerable: typing.Iterable[T], filter_func: typing.Callable[[T], bool]) -> bool:
    for item in enumerable:
        if filter_func(item):
            return True
    return False


def count(enumerable: typing.Iterable[T], filter_func: typing.Callable[[T], bool]) -> int:
    countMatch = 0
    for item in enumerable:
        if filter_func(item):
            countMatch += 1
    return countMatch


def dest_breadth_first_target(
        map: MapBase,
        goalList: typing.Dict[Tile, typing.Tuple[int, int, float]] | typing.Iterable[Tile],
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
) -> Path | None:
    """
    Gets a path that results in {targetArmy} army on one of the goalList tiles.
    GoalList can be a dict that maps from start tile to (startDist, goalTargetArmy)

    additionalIncrement can be set if for example capturing one of two nearby cities and you want to kill with enough to kill both.
    Positive means gather EXTRA, negative means gather LESS.
    """
    if searchingPlayer == -2:
        searchingPlayer = map.player_index

    if map.teammates and searchingPlayer == map.player_index:
        if skipTiles:
            skipTiles = set(t for t in skipTiles)
        else:
            skipTiles = set()
        for tId in map.teammates:
            if map.generals[tId] and map.generals[tId].isGeneral and map.generals[tId].player == tId:
                skipTiles.add(map.generals[tId])

    frontier = []
    visited = MapMatrix(map, None)
    if isinstance(goalList, dict):
        for goal in goalList.keys():
            (startDist, goalTargetArmy, goalIncModifier) = goalList[goal]
            if goal.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue

            goalInc = goalIncModifier + additionalIncrement

            # THE goalIncs below might be wrong, unit test.
            if not map.is_player_on_team_with(searchingPlayer, goal.player):
                startArmy = 0 + goalTargetArmy  # + goalInc
            else:
                startArmy = 0 - goalTargetArmy  # - goalInc

            if ignoreGoalArmy:
                # then we have to inversely increment so we dont have to figure that out in the loop every time
                if not map.is_player_on_team_with(searchingPlayer, goal.player):
                    if negativeTiles is None or goal not in negativeTiles:
                        startArmy -= goal.army
                else:
                    if negativeTiles is None or goal not in negativeTiles:
                        startArmy += goal.army

            startVal = (startDist, 0, 0 - startArmy)
            heapq.heappush(frontier, (startVal, goal, startDist, startArmy, int(goalInc * 2), None))
    else:
        goal: Tile
        for goal in goalList:
            if goal.isMountain:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue

            goalInc = additionalIncrement

            # fixes the off-by-one error because we immediately decrement army, but the target shouldn't decrement
            startArmy = 1
            if ignoreGoalArmy and (negativeTiles is None or goal not in negativeTiles):
                # then we have to inversely increment so we dont have to figure that out in the loop every time
                if not map.is_player_on_team_with(searchingPlayer, goal.player):
                    if goal.army > 0:
                        startArmy -= goal.army
                else:
                    startArmy += goal.army

            startVal = (0, 0, 0 - startArmy)
            heapq.heappush(frontier, (startVal, goal, 0, startArmy, int(goalInc * 2), None))
    start = time.perf_counter()
    iter = 0
    foundGoal = False
    foundArmy = -1000
    foundDist = -1
    endNode = None
    depthEvaluated = 0
    baseTurn = map.turn
    noNegs = negativeTiles is None or not negativeTiles
    while frontier:
        iter += 1

        (prioVals, current, dist, army, goalInc, fromTile) = heapq.heappop(frontier)
        if visited.raw[current.tile_index] is not None:
            continue
        if skipTiles and current in skipTiles:
            continue
        if current.isMountain or (
                noNeutralCities and current.isCostlyNeutral and current not in goalList) or (
                not current.discovered and current.isNotPathable
        ):
            continue

        _, negCaptures, prioArmy = prioVals

        nextArmy = army - 1
        isInc = (baseTurn + dist) & 1 == 0 and dist > 0

        isTeam = map.is_player_on_team_with(searchingPlayer, current.player)
        if preferCapture and not isTeam:  # and army > current.army // 3
            negCaptures -= 1

        # nextArmy is effectively "you must bring this much army to the tile next to me for this to kill"
        if (current.isCity and current.player != -1) or current.isGeneral:
            if isTeam:
                goalInc -= 1
                # if isInc:
                #     nextArmy -= int(goalInc * 2)
            else:
                goalInc += 1
                # if isInc:
                #     nextArmy += int(goalInc * 2)

        notNegativeTile = noNegs or current not in negativeTiles

        # we screw up the paths if we let negatives happen, we think a 1 can make it all the way across the map to capture a 1000...?
        if current.army > 0:
            if isTeam:
                if notNegativeTile:
                    nextArmy += current.army
            else:
                if notNegativeTile:
                    nextArmy -= current.army
                else:
                    nextArmy -= 1

        if current.isSwamp:
            nextArmy -= 2

        newDist = dist + 1

        visited.raw[current.tile_index] = (nextArmy, fromTile)

        if nextArmy >= targetArmy and nextArmy > foundArmy and current.player == searchingPlayer and current.army > 1:
            foundDist = newDist
            foundArmy = nextArmy
            endNode = current
            if not noLog and iter < 100:
                logbook.info(
                    f"GOAL popped {current.toString()}, army {nextArmy}, goalInc {goalInc}, targetArmy {targetArmy}, processing")
            break

        if isInc:  #(current.x == 2 and current.y == 7) or (current.x == 2 and current.y == 8) or (current.x == 2 and current.y == 9) or (current.x == 3 and current.y == 9) or (current.x == 4 and current.y == 9) or (current.x == 5 and current.y == 9)
            nextArmy -= goalInc

        if newDist > depthEvaluated:
            depthEvaluated = newDist
        # targetArmy += goalInc

        if not noLog and iter < 100:
            logbook.info(
                f"Popped current {current.toString()}, army {nextArmy}, goalInc {goalInc}, targetArmy {targetArmy}, processing")
        if newDist <= maxDepth and not foundGoal:
            for nextMove in current.movable:  # new spots to try
                heapq.heappush(frontier, ((newDist, negCaptures, 0 - nextArmy), nextMove, newDist, nextArmy, goalInc, current))
    if not noLog:
        logbook.info(
            f"BFS DEST SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}, FOUNDDIST: {foundDist}")
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
        (army, node) = visited.raw[node.tile_index]
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

    # pathStart = PathNode(startNode, None, foundArmy, foundDist, -1, None)
    # path = pathStart
    dist = foundDist
    for i, armyNode in enumerate(nodes[1:]):
        (curArmy, curNode) = armyNode
        if curNode is not None:
            # logbook.info("curArmy {} NODE {},{}".format(curArmy, curNode.x, curNode.y))
            # path = PathNode(curNode, path, curArmy, dist, -1, None)
            pathObject.add_start(curNode)
            dist -= 1

    while pathObject.start is not None and (pathObject.start.tile.army <= 1 or pathObject.start.tile.player != searchingPlayer):
        logbook.info(
            "IS THIS THE INC BUG? OMG I THINK I FOUND IT!!!!!! Finds path where waiting 1 move for city increment is superior, but then we skip the 'waiting' move and just move the 2 army off the city instead of 3 army?")
        logbook.info(f"stripping path node {pathObject.start.tile}")
        pathObject.remove_start()
        pathObject.requiredDelay += 1

    if pathObject.length <= 0:
        logbook.info("abandoned path")
        return None

    logbook.info(
        f"DEST BFS FOUND KILLPATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    return pathObject


def _shortestPathHeur(goals, cur) -> int:
    minFound = 100000
    for goal in goals:
        minFound = min(minFound, abs(goal.x - cur.x) + abs(goal.y - cur.y))
    return minFound


def _shortestPathHeurTile(goal, cur) -> int:
    # MUCH much slower
    # return (abs(goal.x - cur.x)**2 + abs(goal.y - cur.y)**2)**0.5

    # TODO need to replace with torus safe calls to map...
    return abs(goal.x - cur.x) + abs(goal.y - cur.y)


def a_star_kill(
        map,
        startTiles,
        goalSet,
        maxTime=0.1,
        maxDepth=20,
        restrictionEvalFuncsLookup=None,
        ignoreStartTile=False,
        requireExtraArmy=0,
        negativeTiles=None):
    frontier = []
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
            cost_so_far[start.tile_index] = (startDist, 0 - startArmy)
            heapq.heappush(frontier, ((_shortestPathHeur(goalSet, start) + startDist, 0 - startArmy), start))
            came_from[start.tile_index] = None
    else:
        for start in startTiles:
            logbook.info(f"a* enqueued start tile {start.toString()} with extraArmy {requireExtraArmy}")
            startArmy = start.army
            if ignoreStartTile:
                startArmy = 0
            startArmy -= requireExtraArmy
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = (0, 0 - startArmy)
            heapq.heappush(frontier, ((_shortestPathHeur(goalSet, start), 0 - startArmy), start))
            came_from[start.tile_index] = None

    start = time.perf_counter()
    iter = 0
    foundDist = -1
    foundArmy = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, current = heapq.heappop(frontier)
        dist, negArmy = cost_so_far[current.tile_index]
        army = 0 - negArmy

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current in goalSet:
            if army > 1 and army > foundArmy:
                foundDist = dist
                foundArmy = army
                break
            else:  # skip paths that go through target, that wouldn't make sense
                # logbook.info("a* path went through target")
                continue
        if dist >= maxDepth:
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            if next == came_from[current.tile_index]:
                continue
            if next.isMountain or ((not next.discovered) and next.isNotPathable):
                # logbook.info("a* mountain")
                continue
            if restrictionEvalFuncsLookup is not None:
                try:
                    f = restrictionEvalFuncsLookup[current]
                    if f(next):
                        logbook.info(f"dangerous, vetod: {current}")
                        continue
                    else:
                        logbook.info(f"safe: {current}")
                except KeyError:
                    pass

            inc = 0 if not ((next.isCity and next.player != -1) or next.isGeneral) else (dist + 1) / 2

            # new_cost = cost_so_far[current.tile_index] + graph.cost(current, next)
            nextArmy = army - 1
            if negativeTiles is None or next not in negativeTiles:
                if startTiles[0].player == next.player:
                    nextArmy += next.army + inc
                else:
                    nextArmy -= (next.army + inc)
                # if next.isCity and next.player == -1:
                #     nextArmy -= next.army * 2
            if nextArmy <= 0 < army:  # prune out paths that go negative after initially going positive
                # logbook.info("a* next army <= 0: {}".format(nextArmy))
                continue
            new_cost = (newDist, (0 - nextArmy))
            try:
                curCost = cost_so_far[next.tile_index]
            except KeyError:
                curCost = (1000, -10000)
            if new_cost < curCost:
                cost_so_far[next.tile_index] = new_cost
                priority = (newDist + _shortestPathHeur(goalSet, next), 0 - nextArmy)
                heapq.heappush(frontier, (priority, next))
                # logbook.info("a* enqueued next")
                came_from[next.tile_index] = current
    logbook.info(
        f"A* KILL SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    goal = None
    for possibleGoal in goalSet:
        if possibleGoal.tile_index in came_from:
            goal = possibleGoal
    if goal is None:
        return None

    pathObject = Path(foundArmy)
    pathObject.add_next(goal)
    node = goal
    dist = foundDist
    while came_from[node.tile_index] is not None:
        # logbook.info("Node {},{}".format(node.x, node.y))
        node = came_from[node.tile_index]
        dist -= 1
        pathObject.add_start(node)
    logbook.info(f"A* FOUND KILLPATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    pathObject.calculate_value(startTiles[0].player, teams=map.team_ids_by_player_index)
    if pathObject.value < requireExtraArmy:
        logbook.info(f"A* path {pathObject.toString()} wasn't good enough, returning none")
        return None
    return pathObject


def a_star_find(
        startTiles,
        goal: Tile,
        maxDepth: int = 200,
        allowNeutralCities: bool = False,
        noLog: bool = False):
    frontier = []
    came_from = {}
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            heapq.heappush(frontier, (startDist + _shortestPathHeurTile(goal, start), startDist, start))
            came_from[start.tile_index] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            heapq.heappush(frontier, (_shortestPathHeurTile(goal, start), 0, start))
            came_from[start.tile_index] = None
    start = time.perf_counter()
    iter = 0
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, dist, current = heapq.heappop(frontier)

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current is goal:
            break

        new_cost = dist + 1
        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCostlyNeutral and not allowNeutralCities:
                    continue
                if next.tile_index in came_from:
                    continue

                priority = new_cost + _shortestPathHeurTile(goal, next)
                heapq.heappush(frontier, (priority, new_cost, next))
                # logbook.info("a* enqueued next")
                came_from[next.tile_index] = current

    if not noLog:
        logbook.info(
            f"a_star_find SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal.tile_index not in came_from:
        return None

    pathObject = Path()
    pathObject.add_next(goal)
    node = goal
    while came_from[node.tile_index] is not None:
        # logbook.info("Node {},{}".format(node.x, node.y))
        node = came_from[node.tile_index]
        pathObject.add_start(node)

    if not noLog:
        logbook.info(f"a_star_find FOUND PATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject}")
    # pathObject.calculate_value(startTiles[0].player, teams=map._teams)
    return pathObject


def a_star_find_official(
        startTiles,
        goal: Tile,
        maxDepth: int = 200,
        allowNeutralCities: bool = False,
        noLog: bool = False):
    frontier = []
    came_from = {}
    cost_so_far = {}
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = startDist
            heapq.heappush(frontier, (startDist + _shortestPathHeurTile(goal, start), startDist, start))
            came_from[start.tile_index] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = 0
            heapq.heappush(frontier, (_shortestPathHeurTile(goal, start), 0, start))
            came_from[start.tile_index] = None
    start = time.perf_counter()
    iter = 0
    foundDist = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, dist, current = heapq.heappop(frontier)

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current is goal:
            foundDist = dist
            break

        new_cost = dist + 1
        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCostlyNeutral and not allowNeutralCities:
                    continue

                curNextCost = cost_so_far.get(next.tile_index, 1000)
                if new_cost < curNextCost:
                    cost_so_far[next.tile_index] = new_cost
                    priority = new_cost + _shortestPathHeurTile(goal, next)
                    heapq.heappush(frontier, (priority, new_cost, next))
                    # logbook.info("a* enqueued next")
                    came_from[next.tile_index] = current

    if not noLog:
        logbook.info(
            f"a_star_find SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal.tile_index not in came_from:
        return None

    pathObject = Path()
    pathObject.add_next(goal)
    node = goal
    while came_from[node.tile_index] is not None:
        # logbook.info("Node {},{}".format(node.x, node.y))
        node = came_from[node.tile_index]
        pathObject.add_start(node)

    if not noLog:
        logbook.info(f"a_star_find FOUND PATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject}")
    # pathObject.calculate_value(startTiles[0].player, teams=map._teams)
    return pathObject


def a_star_find_raw(
        startTiles,
        goal: Tile,
        maxDepth: int = 200,
        allowNeutralCities: bool = False,
        noLog: bool = False) -> typing.List[Tile] | None:
    """Returns tile list instead of path object"""
    frontier = []
    came_from = {}
    cost_so_far = {}
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = startDist
            heapq.heappush(frontier, (startDist + _shortestPathHeurTile(goal, start), startDist, start))
            came_from[start.tile_index] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = 0
            heapq.heappush(frontier, (_shortestPathHeurTile(goal, start), 0, start))
            came_from[start.tile_index] = None
    start = time.perf_counter()
    iter = 0
    foundDist = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, dist, current = heapq.heappop(frontier)

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current is goal:
            foundDist = dist
            break

        new_cost = dist + 1
        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCostlyNeutral and not allowNeutralCities:
                    continue

                curNextCost = cost_so_far.get(next.tile_index, 1000)
                if new_cost < curNextCost:
                    cost_so_far[next.tile_index] = new_cost
                    priority = new_cost + _shortestPathHeurTile(goal, next)
                    heapq.heappush(frontier, (priority, new_cost, next))
                    # logbook.info("a* enqueued next")
                    came_from[next.tile_index] = current

    if not noLog:
        logbook.info(
            f"a_star_find_raw SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal.tile_index not in came_from:
        return None

    tileList = [goal]
    node = goal
    while came_from[node.tile_index] is not None:
        node = came_from[node.tile_index]
        tileList.append(node)

    if not noLog:
        logbook.info(f"a_star_find_raw FOUND PATH OF LENGTH {len(tileList) - 1}  {tileList}")

    tileList.reverse()
    return tileList


def a_star_find_raw_with_try_avoid(
        startTiles,
        goal: Tile,
        tryAvoid: TileSet,
        maxDepth: int = 200,
        allowNeutralCities: bool = False,
        noLog: bool = False) -> typing.List[Tile] | None:
    frontier = []
    came_from = {}
    cost_so_far = {}
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = startDist
            heapq.heappush(frontier, (startDist + _shortestPathHeurTile(goal, start), startDist, start))
            came_from[start.tile_index] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = 0
            heapq.heappush(frontier, (_shortestPathHeurTile(goal, start), 0, start))
            came_from[start.tile_index] = None
    start = time.perf_counter()
    iter = 0
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, dist, current = heapq.heappop(frontier)

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current is goal:
            break

        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCostlyNeutral and not allowNeutralCities:
                    continue

                new_cost = dist + 1
                if next in tryAvoid:
                    new_cost += 0.05

                curNextCost = cost_so_far.get(next.tile_index, 1000)
                if new_cost < curNextCost:
                    cost_so_far[next.tile_index] = new_cost
                    extraCost = 0
                    if next in tryAvoid:
                        extraCost = 0.3
                    priority = new_cost + _shortestPathHeurTile(goal, next) + extraCost
                    heapq.heappush(frontier, (priority, new_cost, next))
                    # logbook.info("a* enqueued next")
                    came_from[next.tile_index] = current

    if not noLog:
        logbook.info(
            f"a_star_find_raw SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal.tile_index not in came_from:
        return None

    tileList = [goal]
    node = goal
    while came_from[node.tile_index] is not None:
        node = came_from[node.tile_index]
        tileList.append(node)

    if not noLog:
        logbook.info(f"a_star_find_raw FOUND PATH OF LENGTH {len(tileList) - 1}  {tileList}")

    tileList.reverse()
    return tileList


def a_star_find_matrix(
        map: MapBase,
        startTiles,
        goal: Tile,
        maxDepth: int = 200,
        allowNeutralCities: bool = False,
        noLog: bool = False):
    frontier = []
    came_from: MapMatrixInterface[Tile | None] = MapMatrix(map, None)
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            heapq.heappush(frontier, (startDist + _shortestPathHeurTile(goal, start), startDist, start))
            came_from.raw[start.tile_index] = start
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            heapq.heappush(frontier, (_shortestPathHeurTile(goal, start), 0, start))
            came_from.raw[start.tile_index] = start

    start = time.perf_counter()
    iter = 0
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, dist, current = heapq.heappop(frontier)

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current is goal:
            break

        new_cost = dist + 1
        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if came_from.raw[next.tile_index] is not None:
                    continue
                came_from.raw[next.tile_index] = current
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCostlyNeutral and not allowNeutralCities:
                    continue

                priority = new_cost + _shortestPathHeurTile(goal, next)
                heapq.heappush(frontier, (priority, new_cost, next))

    if not noLog:
        logbook.info(
            f"A* FIND SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if not came_from.raw[goal.tile_index]:
        return None

    pathObject = Path()
    pathObject.add_next(goal)
    node = goal
    while came_from.raw[node.tile_index] is not None and came_from.raw[node.tile_index] is not node:
        node = came_from.raw[node.tile_index]
        pathObject.add_start(node)

    if not noLog:
        logbook.info(f"A* FOUND KILLPATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    return pathObject


def a_star_find_dist(
        startTiles,
        goal: Tile,
        maxDepth: int = 200,
        allowNeutralCities: bool = False,
        noLog: bool = False) -> int:
    frontier = []
    cost_so_far = {}
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = startDist
            heapq.heappush(frontier, (_shortestPathHeurTile(goal, start) + startDist, 0, start))
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start.tile_index] = 0
            heapq.heappush(frontier, (_shortestPathHeurTile(goal, start), 0, start))
    start = time.perf_counter()
    iter = 0
    foundDist = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, dist, current = heapq.heappop(frontier)

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current is goal:
            foundDist = dist
            break

        new_cost = dist + 1
        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCostlyNeutral and not allowNeutralCities:
                    continue

                curNextCost = cost_so_far.get(next.tile_index, 1000)
                if new_cost < curNextCost:
                    cost_so_far[next.tile_index] = new_cost
                    priority = new_cost + _shortestPathHeurTile(goal, next)
                    heapq.heappush(frontier, (priority, new_cost, next))
                    # logbook.info("a* enqueued next")

    if not noLog:
        logbook.info(
            f"A* FIND SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    return foundDist


# TODO this is in need of optimization
def breadth_first_dynamic(
        map,
        startTiles,
        goalFunc: typing.Callable[[Tile, typing.Tuple], bool],
        maxDepth=100,
        noNeutralCities: bool = True,
        negativeTiles: TileSet | None = None,
        skipTiles: TileSet | None = None,
        searchingPlayer: int = -2,
        priorityFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None] = None,
        ignoreStartTile: bool = False,
        incrementBackward: bool = False,
        noLog: bool = False,
        noVal: bool = False,
) -> Path:
    """
    Finds a path to a goal, dynamically. Doesn't search past when it found the goal, unlike _max equivalents.
    startTiles dict is (startPriorityObject, distance) = startTiles[tile]
    goalFunc is (currentTile, priorityObject) -> True or False
    priorityFunc is (nextTile, currentPriorityObject) -> nextPriorityObject | None

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
    frontier = []
    visited = {}
    if skipTiles:
        visited = {t.tile_index: None for t in skipTiles}
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            heapq.heappush(frontier, (startVal, distance, tile, None))
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
                if tile.player != -1 and (tile.isCity or tile.isGeneral):
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            heapq.heappush(frontier, (startVal, dist, tile, None))

    start = time.perf_counter()
    iter = 0
    foundGoal = False
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    foundVal = None
    while frontier:
        iter += 1

        (prioVals, dist, current, parent) = heapq.heappop(frontier)
        if current.tile_index in visited:
            continue
        visited[current.tile_index] = parent

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
            for nextTile in current.movable:  # new spots to try
                if (nextTile.isMountain
                        or (noNeutralCities and nextTile.isCostlyNeutral)
                        or (not nextTile.discovered and nextTile.isNotPathable)):
                    continue
                newDist = dist + 1
                nextVal = priorityFunc(nextTile, prioVals)
                if nextVal is not None:
                    heapq.heappush(frontier, (nextVal, newDist, nextTile, current))

    if not noLog:
        logbook.info(
            f"BFS-DYNAMIC ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return None

    tile = endNode
    tileList = []

    while tile is not None:
        tileList.append(tile)
        tile = visited[tile.tile_index]
    pathObject = Path()
    for tile in reversed(tileList):
        if tile is not None:
            pathObject.add_next(tile)

    if not noVal:
        pathObject.calculate_value(
            searchingPlayer,
            teams=map.team_ids_by_player_index,
            incrementBackwards=incrementBackward)
    if not noLog:
        logbook.info(
            f"DYNAMIC BFS FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject}")
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
        priorityMatrix: MapMatrixInterface[float] | None = None,
        priorityMatrixSkipStart: bool = False,
        priorityMatrixSkipEnd: bool = False,
        pathValueFunc: typing.Callable[[Path, typing.Tuple], float] | None = None,
        includePath=False,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        forceOld: bool = False
) -> Path | None:
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
    @param logResultValues:
    @param noLog:
    @param includePathValue: if True, the paths value (from the value func output) will be returned in a tuple with the actual path.
    @param fullOnly:
    @param fullOnlyArmyDistFunc:
    @param boundFunc: boundFunc is (currentTile, currentPiorityObject, maxPriorityObject) -> True (prune) False (continue)
    @param maxIterations:
    @param includePath:  if True, all the functions take a path object param as third tuple entry
    @param ignoreNonPlayerArmy: if True, the paths returned will be calculated on the basis of just the searching players army and ignore enemy (or neutral city!) army they pass through.
    @param ignoreIncrement: if True, do not have paths returned include the city increment in their path calculation for any cities or generals in the path.
    @param useGlobalVisitedSet: prevent a tile from ever being popped more than once in a search. Use this when your priority function guarantees that the best path that uses a tile is also guaranteed to be reached first in the search.
    @param forceOld: force list-copying version even when useGlobalVisitedSet = True. NEVER pass true for this...
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
    if useGlobalVisitedSet and not forceOld:
        return breadth_first_dynamic_max_global_visited(**locals())

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
                skipMt = adj.isMountain or adj.isCostlyNeutral
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

    nonDefaultPrioFunc = True
    if priorityFunc is None:
        nonDefaultPrioFunc = False
        # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
        def default_priority_func(nextTile, currentPriorityObject):
            (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
            dist += 1
            if nextTile.isCity:
                negCityCount -= 1
            if nextTile.player != searchingPlayer and (
                    nextTile.player != -1 or (preferNeutral and not nextTile.isCity)):
                negEnemyTileCount -= 1

            if negativeTiles is None or next not in negativeTiles:
                if map.is_player_on_team_with(nextTile.player, searchingPlayer):
                    negArmySum -= nextTile.army
                else:
                    negArmySum += nextTile.army
            # always leaving 1 army behind. + because this is negative.
            negArmySum += 1
            # -= because we passed it in positive for our general and negative for enemy gen / cities
            negArmySum -= goalIncrement
            return dist, negCityCount, negEnemyTileCount, negArmySum, sumX + nextTile.x, sumY + nextTile.y, goalIncrement

        priorityFunc = default_priority_func

    frontier = HeapQueue()

    globalVisitedSet: typing.Set[Tile] | None = None
    if useGlobalVisitedSet:
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
            if nonDefaultPrioFunc:
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
                if tile.player != -1 and (tile.isCity or tile.isGeneral):
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

    qq = frontier.queue
    while qq:
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
            if current.tile_index in globalVisitedSet:
                continue
            globalVisitedSet.add(current.tile_index)
        if skipTiles and current in skipTiles:
            continue

        newValue = valueFunc(current, prioVals) if not includePath else valueFunc(current, prioVals, nodeList)
        if newValue is not None and (maxValue is None or newValue > maxValue):
            foundDist = dist
            if logResultValues:
                if parent is not None:
                    parentString = parent.toString()
                else:
                    parentString = "None"
                logbook.info(
                    f"+Tile {str(current)} from {parentString} is new max value: [{'], ['.join('{:.3f}'.format(x) for x in newValue)}]  (dist {dist})")
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
            if next == parent:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.isCostlyNeutral)
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
                if skipFunc:
                    shouldSkip = skipFunc(next, nextVal) if not includePath else skipFunc(next, nextVal, nodeList)
                    if shouldSkip:
                        continue
                newNodeList = nodeList.copy()
                newNodeList.append((next, nextVal))
                frontier.put((nextVal, dist, next, current, newNodeList))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
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
            if not noLog and DebugHelper.IS_DEBUGGING:
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

    if pathValueFunc:
        pathObject.value = pathValueFunc(pathObject, maxValue)
    else:
        pathObject.calculate_value(
            searchingPlayer,
            teams=map.team_ids_by_player_index,
            negativeTiles=pathNegs,
            ignoreNonPlayerArmy=ignoreNonPlayerArmy,
            incrementBackwards=incrementBackward,
            ignoreIncrement=ignoreIncrement)

        matrixStart = 0 if not priorityMatrixSkipStart else 1
        matrixEndOffset = -1 if not priorityMatrixSkipEnd else 0

        # TODO this needs to change to .econValue...?
        if priorityMatrix:
            for tile in pathObject.tileList[matrixStart:pathObject.length - matrixEndOffset]:
                pathObject.value += priorityMatrix.raw[tile.tile_index]

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
        includePath=False,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        priorityMatrixSkipStart: bool = False,
        priorityMatrixSkipEnd: bool = False,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        useGlobalVisitedSet: bool = True,
        forceOld: bool = False
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
    @param includePath:  if True, all the functions take a path object param as third tuple entry
    @param ignoreNonPlayerArmy: if True, the paths returned will be calculated on the basis of just the searching players army and ignore enemy (or neutral city!) army they pass through.
    @param ignoreIncrement: if True, do not have paths returned include the city increment in their path calculation for any cities or generals in the path.
    @param useGlobalVisitedSet: prevent a tile from ever being popped more than once in a search. Use this when your priority function guarantees that the best path that uses a tile is also guaranteed to be reached first in the search.
    @param forceOld: force list-copying version even when useGlobalVisitedSet = True. NEVER pass true for this...
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
    if useGlobalVisitedSet and not forceOld:
        return breadth_first_dynamic_max_per_tile_global_visited(**locals())

    if negativeTiles is None:
        negativeTiles = set()

    # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
    def default_priority_func(nextTile, currentPriorityObject):
        (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and (
                nextTile.player != -1 or (preferNeutral and not nextTile.isCity)):
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
                skipMt = adj.isMountain or adj.isCostlyNeutral
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
    frontier = HeapQueue()

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
                if tile.player != -1 and (tile.isCity or tile.isGeneral):
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

    qq = frontier.queue
    while qq:
        iter += 1
        if iter & 64 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
            logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
            break

        (prioVals, dist, current, parent, nodeList, startTile) = frontier.get()
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
        if useGlobalVisitedSet:
            if current.tile_index in globalVisitedSet:
                continue
            globalVisitedSet.add(current.tile_index)
        if skipTiles and current in skipTiles:
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
                    f"+Tile {str(current)} from {parentString} is new max value: [{valStr}]  (dist {dist})")
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
            if next == parent:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.isCostlyNeutral)
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
                if skipFunc:
                    shouldSkip = skipFunc(next, nextPrio) if not includePath else skipFunc(next, nextPrio, nodeList)
                    if shouldSkip:
                        continue
                newNodeList = list(nodeList)
                newNodeList.append((next, nextPrio))
                frontier.put((nextPrio, dist, next, current, newNodeList, startTile))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return {}

    pathNegs = negativeTiles
    negWithStart = negativeTiles.union(startTiles)

    if ignoreStartTile:
        pathNegs = negWithStart

    matrixStart = 0 if not priorityMatrixSkipStart else 1
    matrixEndOffset = -1 if not priorityMatrixSkipEnd else 0

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
            teams=map.team_ids_by_player_index,
            negativeTiles=pathNegs,
            ignoreNonPlayerArmy=ignoreNonPlayerArmy,
            incrementBackwards=incrementBackward,
            ignoreIncrement=ignoreIncrement)

        if priorityMatrix:
            for tile in pathObject.tileList[matrixStart:pathObject.length - matrixEndOffset]:
                pathObject.value += priorityMatrix.raw[tile.tile_index]

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
        includePath=False,
        pathValueFunc: typing.Callable[[Path, typing.Tuple], float] | None = None,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        priorityMatrixSkipStart: bool = False,
        priorityMatrixSkipEnd: bool = False,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        useGlobalVisitedSet: bool = True,
        forceOld: bool = False
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
    @param includePath:  if True, all the functions take a path object param as third tuple entry
    @param ignoreNonPlayerArmy: if True, the paths returned will be calculated on the basis of just the searching players army and ignore enemy (or neutral city!) army they pass through.
    @param ignoreIncrement: if True, do not have paths returned include the city increment in their path calculation for any cities or generals in the path.
    @param useGlobalVisitedSet: prevent a tile from ever being popped more than once in a search. Use this when your priority function guarantees that the best path that uses a tile is also guaranteed to be reached first in the search.
    @param forceOld: force list-copying version even when useGlobalVisitedSet = True. NEVER pass true for this...
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
    if useGlobalVisitedSet and not forceOld:
        return breadth_first_dynamic_max_per_tile_per_distance_global_visited(**locals())

    if negativeTiles is None:
        negativeTiles = set()

    # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
    def default_priority_func(nextTile, currentPriorityObject):
        (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and (
                nextTile.player != -1 or (preferNeutral and not nextTile.isCity)):
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
                skipMt = adj.isMountain or adj.isCostlyNeutral
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
    frontier = HeapQueue()

    globalVisitedSet = set()
    if isinstance(startTiles, dict):
        for tile, (startPriorityObject, distance) in startTiles.items():
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
                if tile.player != -1 and (tile.isCity or tile.isGeneral):
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

    valuePrinter = None
    if logResultValues:
        valuePrinter = lambda val: f"[{'], ['.join('{:.3f}'.format(x) for x in val)}]"
        try:
            valuePrinter(startTiles[0])
        except:
            valuePrinter = lambda val: str(val)

    qq = frontier.queue
    while qq:
        iter += 1
        if iter & 63 == 0:
            elapsed = time.perf_counter() - start
            if elapsed > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
                logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE-PER-DIST BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
                break

        (prioVals, dist, current, parent, nodeList, startTile) = frontier.get()
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
        if useGlobalVisitedSet:
            if current.tile_index in globalVisitedSet:
                continue
            globalVisitedSet.add(current.tile_index)
            if skipTiles and current in skipTiles:
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
            val = maxValuesTMP[startTile].get(dist, None)
            if (val is None or newValue > val) and (maxMinusOne is None or maxMinusOne < newValue):
                foundDist = min(foundDist, dist)
                if logResultValues:
                    if parent is not None:
                        parentString = str(parent)
                    else:
                        parentString = "None"
                    logbook.info(
                        f"+Tile {str(current)} from {parentString} for startTile {str(startTile)} at dist {dist} is new max value: {valuePrinter(newValue)}")
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
            if next == parent:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.isCostlyNeutral)
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
                                    logbook.info(f"Bounded off {str(next)}")
                                continue
                if skipFunc:
                    shouldSkip = skipFunc(next, nextPrio) if not includePath else skipFunc(next, nextPrio, nodeList)
                    if shouldSkip:
                        continue
                newNodeList = list(nodeList)
                newNodeList.append((next, nextPrio))
                frontier.put((nextPrio, dist, next, current, newNodeList, startTile))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return {}

    maxPaths: typing.Dict[Tile, typing.List[Path]] = {}
    negWithStart = negativeTiles.union(startTiles)

    pathNegs = negativeTiles
    if ignoreStartTile:
        pathNegs = negWithStart

    matrixStart = 0 if not priorityMatrixSkipStart else 1
    matrixEndOffset = -1 if not priorityMatrixSkipEnd else 0

    for startTile in maxValuesTMP.keys():
        pathListForTile = []
        for dist, valObj in maxValuesTMP[startTile].items():
            pathObject = Path()
            # # prune any paths that are not higher value than the shorter path.
            # # THIS WOULD PRUNE LOWER VALUE PER TURN PATHS THAT ARE LONGER, WHICH IS ONLY OK IF WE ALWAYS DO PARTIAL LAYERS OF THE FULL GATHER...
            # if dist - 1 in maxValuesTMP[startTile]:
            #     shorterVal = maxValuesTMP[startTile][dist - 1]
            #     if maxValuesTMP[startTile][dist] <= shorterVal:
            #         logbook.info(f"  PRUNED PATH TO {str(startTile)} at dist {dist} because its value {shorterVal} was same or less than shorter _dists value")
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

            if pathValueFunc:
                pathObject.value = pathValueFunc(pathObject, valObj)
            else:
                pathObject.calculate_value(
                    searchingPlayer,
                    teams=map.team_ids_by_player_index,
                    negativeTiles=pathNegs,
                    ignoreNonPlayerArmy=ignoreNonPlayerArmy,
                    incrementBackwards=incrementBackward,
                    ignoreIncrement=ignoreIncrement)

                if priorityMatrix:
                    for tile in pathObject.tileList[matrixStart:pathObject.length - matrixEndOffset]:
                        pathObject.value += priorityMatrix.raw[tile.tile_index]

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


def breadth_first_dynamic_max_global_visited(
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
        logResultValues=False,
        noLog=False,
        fullOnly=False,
        fullOnlyArmyDistFunc=None,
        boundFunc=None,
        maxIterations: int = INF,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        priorityMatrixSkipStart: bool = True,
        priorityMatrixSkipEnd: bool = False,
        pathValueFunc: typing.Callable[[Path, typing.Tuple], float] | None = None,
        includePath=False,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        **kwargs  # swallows the garbage from the non-global-visited parameters
) -> Path | None:
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
    @param logResultValues:
    @param noLog:
    @param fullOnly:
    @param fullOnlyArmyDistFunc:
    @param boundFunc: boundFunc is (currentTile, currentPiorityObject, maxPriorityObject) -> True (prune) False (continue)
    @param maxIterations:
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
                skipMt = adj.isMountain or adj.isCostlyNeutral
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

    nonDefaultPrioFunc = True
    if priorityFunc is None:
        nonDefaultPrioFunc = False
        # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
        def default_priority_func(nextTile, currentPriorityObject):
            (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
            dist += 1
            if nextTile.isCity:
                negCityCount -= 1
            if nextTile.player != searchingPlayer and (
                    nextTile.player != -1 or (preferNeutral and not nextTile.isCity)):
                negEnemyTileCount -= 1

            if negativeTiles is None or next not in negativeTiles:
                if map.is_player_on_team_with(nextTile.player, searchingPlayer):
                    negArmySum -= nextTile.army
                else:
                    negArmySum += nextTile.army
            # always leaving 1 army behind. + because this is negative.
            negArmySum += 1
            # -= because we passed it in positive for our general and negative for enemy gen / cities
            negArmySum -= goalIncrement
            return dist, negCityCount, negEnemyTileCount, negArmySum, sumX + nextTile.x, sumY + nextTile.y, goalIncrement

        priorityFunc = default_priority_func

    frontier: typing.List[typing.Tuple[typing.Any, int, int, Tile, Tile | None]] = []
    """prioObj, distance (incl startDist), curTurns (starting at 0 per search), nextTile, fromTile"""

    fromTileLookup: MapMatrixInterface[typing.Tuple[typing.Any, Tile]] = MapMatrix(map, None)

    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            heapq.heappush(frontier, (startVal, distance, 0, tile, None))
    else:
        for tile in startTiles:
            if nonDefaultPrioFunc:
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
                if tile.player != -1 and (tile.isCity or tile.isGeneral):
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            heapq.heappush(frontier, (startVal, dist, 0, tile, None))

    start = time.perf_counter()
    iter = 0
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    maxValue = None
    maxPrio = None

    current: Tile
    next: Tile

    while frontier:
        iter += 1
        if (iter & 128 == 0
            and time.perf_counter() - start > maxTime
                # and not BYPASS_TIMEOUTS_FOR_DEBUGGING
        ) or iter > maxIterations:
            logbook.info(f"BFS-DYNAMIC-MAX BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
            break

        (prioVals, dist, curTurns, current, parent) = heapq.heappop(frontier)
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):

        fromVal = fromTileLookup.raw[current.tile_index]
        if fromVal:
            continue

        fromTileLookup.raw[current.tile_index] = (prioVals, parent)

        newValue = valueFunc(current, prioVals)
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
                    f"+Tile {str(current)} from {parentString} is new max value: [{'], ['.join('{:.3f}'.format(x) for x in newValue)}]  (dist {dist})")
            maxValue = newValue
            maxPrio = prioVals
            endNode = current
        # elif logResultValues:
        #        logbook.info("   Tile {} from {} was not max value: [{}]".format(current.toString(), parentString, '], ['.join(str(x) for x in newValue)))
        if dist > depthEvaluated:
            depthEvaluated = dist
            # stop when we either reach the max depth (this is dynamic from start tiles) or use up the remaining turns (as indicated by len(nodeList))
        if dist >= maxDepth or curTurns >= maxTurns:
            continue
        dist += 1
        curTurns += 1
        for next in current.movable:  # new spots to try
            if next == parent:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.isCostlyNeutral)
                    or (next.isUndiscoveredObstacle and noNeutralUndiscoveredObstacles)):
                continue
            nextVal = priorityFunc(next, prioVals)
            if nextVal is not None:
                if boundFunc is not None:
                    bounded = boundFunc(next, nextVal, maxPrio)
                    if bounded:
                        if not noLog:
                            logbook.info(f"Bounded off {next.toString()}")
                        continue
                if skipFunc:
                    shouldSkip = skipFunc(next, nextVal)
                    if shouldSkip:
                        continue
                heapq.heappush(frontier, (nextVal, dist, curTurns, next, current))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return None

    tile = endNode
    pathObject = Path()
    while True:
        if tile is None:
            break

        pathObject.add_start(tile)

        fromData = fromTileLookup.raw[tile.tile_index]

        if not fromData:
            break

        prioVal, prevTile = fromData

        if not noLog:
            if prioVal is not None:
                prioStr = '] ['.join(str(x) for x in prioVal)
                logbook.info(f"  PATH TILE {str(tile)}: Prio [{prioStr}]")
            else:
                logbook.info(f"  PATH TILE {str(tile)}: Prio [None]")

        if prevTile == tile:
            raise AssertionError(f'self referential fromTile {prevTile} -> {tile}')

        tile = prevTile

    if pathObject.length == 0:
        return None

    # while (node != None):
    #     army, node = visited[node.x][node.y][dist]
    #     if (node != None):
    #         dist -= 1
    #         path = PathNode(node, path, army, dist, -1, None)

    if pathValueFunc:
        pathObject.value = pathValueFunc(pathObject, maxValue)
    else:
        pathNegs = negativeTiles
        if ignoreStartTile:
            pathNegs = negativeTiles.union(startTiles)
        pathObject.calculate_value(
            searchingPlayer,
            teams=map.team_ids_by_player_index,
            negativeTiles=pathNegs,
            ignoreNonPlayerArmy=ignoreNonPlayerArmy,
            incrementBackwards=incrementBackward,
            ignoreIncrement=ignoreIncrement)

        matrixStart = 0 if not priorityMatrixSkipStart else 1
        matrixEndOffset = -1 if not priorityMatrixSkipEnd else 0

        # TODO this needs to change to .econValue...?
        if priorityMatrix:
            for tile in pathObject.tileList[matrixStart:pathObject.length - matrixEndOffset]:
                pathObject.value += priorityMatrix.raw[tile.tile_index]

    if pathObject.length == 0:
        if not noLog:
            logbook.info(
                f"BFS-DYNAMIC-MAX FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}, returning NONE!\n   {pathObject.toString()}")
        return None
    else:
        if not noLog:
            logbook.info(
                f"BFS-DYNAMIC-MAX FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject.toString()}")
    return pathObject


def breadth_first_dynamic_max_per_tile_global_visited(
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
        priorityMatrix: MapMatrixInterface[float] | None = None,
        priorityMatrixSkipStart: bool = False,
        priorityMatrixSkipEnd: bool = False,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        **kwargs
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

    # make sure to initialize the initial base values and account for first priorityObject being None. Or initialize all your start values in the dict.
    def default_priority_func(nextTile, currentPriorityObject):
        (dist, negCityCount, negEnemyTileCount, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
        dist += 1
        if nextTile.isCity:
            negCityCount -= 1
        if nextTile.player != searchingPlayer and (
                nextTile.player != -1 or (preferNeutral and not nextTile.isCity)):
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
                skipMt = adj.isMountain or adj.isCostlyNeutral
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

    frontier: typing.List[typing.Tuple[typing.Any, int, int, Tile, Tile | None, Tile]] = []
    """prioObj, distance (incl startDist), curTurns (starting at 0 per search), nextTile, fromTile, startTile"""

    fromTileLookup: MapMatrixInterface[typing.Tuple[typing.Any, Tile]] = MapMatrix(map, None)

    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            (startPriorityObject, distance) = startTiles[tile]

            startVal = startPriorityObject
            heapq.heappush(frontier, (startVal, distance, 0, tile, None, tile))
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
                if tile.player != -1 and (tile.isCity or tile.isGeneral):
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            heapq.heappush(frontier, (startVal, dist, 0, tile, None, tile))

    start = time.perf_counter()
    iter = 0
    foundDist = 1000
    depthEvaluated = 0
    maxValues: typing.Dict[Tile, typing.Any] = {}
    maxPrios: typing.Dict[Tile, typing.Any] = {}
    endNodes: typing.Dict[Tile, Tile] = {}

    while frontier:
        iter += 1
        if iter & 64 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
            logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
            break

        (prioVals, dist, curTurns, current, parent, startTile) = heapq.heappop(frontier)
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):

        fromVal = fromTileLookup.raw[current.tile_index]

        if fromVal:
            continue

        if skipTiles and current in skipTiles:
            continue

        fromTileLookup.raw[current.tile_index] = (prioVals, parent)

        newValue = valueFunc(current, prioVals)

        if newValue is not None and (startTile not in maxValues or newValue > maxValues[startTile]):
            foundDist = dist
            if logResultValues:
                if parent is not None:
                    parentString = parent.toString()
                else:
                    parentString = "None"
                valStr = '], ['.join('{:.3f}'.format(x) for x in newValue)
                logbook.info(
                    f"+Tile {str(current)} from {parentString} is new max value: [{valStr}]  (dist {dist})")
            maxValues[startTile] = newValue
            maxPrios[startTile] = prioVals
            endNodes[startTile] = current
        # elif logResultValues:
        #        logbook.info("   Tile {} from {} was not max value: [{}]".format(current.toString(), parentString, '], ['.join(str(x) for x in newValue)))
        if dist > depthEvaluated:
            depthEvaluated = dist
        if dist >= maxDepth or curTurns >= maxTurns:
            continue
        dist += 1
        curTurns += 1
        for next in current.movable:  # new spots to try
            if next == parent:
                continue
            if (next.isMountain
                    or (noNeutralCities and next.isCostlyNeutral)
                    or (not next.discovered and next.isNotPathable)):
                continue
            nextPrio = priorityFunc(next, prioVals)
            if nextPrio is not None:
                # TODO we're bounding per tile, not globally, seems questionable.

                if boundFunc is not None:
                    boundPrio = maxPrios.get(startTile, None)
                    if boundPrio is not None:
                        bounded = boundFunc(next, nextPrio, boundPrio)
                        if bounded:
                            if not noLog:
                                logbook.info(f"Bounded off {next.toString()}")
                            continue
                if skipFunc:
                    shouldSkip = skipFunc(next, nextPrio)
                    if shouldSkip:
                        continue
                heapq.heappush(frontier, (nextPrio, dist, curTurns, next, current, startTile))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return {}

    pathNegs = negativeTiles
    negWithStart = negativeTiles.union(startTiles)

    if ignoreStartTile:
        pathNegs = negWithStart

    matrixStart = 0 if not priorityMatrixSkipStart else 1
    matrixEndOffset = -1 if not priorityMatrixSkipEnd else 0

    maxPaths: typing.Dict[Tile, Path] = {}
    for startTile in maxValues.keys():
        tile = endNodes[startTile]
        pathObject = Path()

        while True:
            if tile is None:
                break

            pathObject.add_start(tile)

            fromData = fromTileLookup.raw[tile.tile_index]

            if not fromData:
                break

            prioVal, prevTile = fromData

            if not noLog:
                if prioVal is not None:
                    prioStr = '] ['.join(str(x) for x in prioVal)
                    logbook.info(f"  PATH TILE {str(tile)}: Prio [{prioStr}]")
                else:
                    logbook.info(f"  PATH TILE {str(tile)}: Prio [None]")

            if prevTile == tile:
                raise AssertionError(f'self referential fromTile {prevTile} -> {tile}')

            tile = prevTile

        if pathObject.length == 0:
            continue

        maxPaths[startTile] = pathObject

        pathObject.calculate_value(
            searchingPlayer,
            teams=map.team_ids_by_player_index,
            negativeTiles=pathNegs,
            ignoreNonPlayerArmy=ignoreNonPlayerArmy,
            incrementBackwards=incrementBackward,
            ignoreIncrement=ignoreIncrement)

        if priorityMatrix:
            for tile in pathObject.tileList[matrixStart:pathObject.length - matrixEndOffset]:
                pathObject.value += priorityMatrix.raw[tile.tile_index]

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


def breadth_first_dynamic_max_per_tile_per_distance_global_visited(
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
        pathValueFunc: typing.Callable[[Path, typing.Tuple], float] | None = None,
        priorityMatrix: MapMatrixInterface[float] | None = None,
        priorityMatrixSkipStart: bool = True,
        priorityMatrixSkipEnd: bool = False,
        ignoreNonPlayerArmy: bool = False,
        ignoreIncrement: bool = True,
        **kwargs
) -> typing.Dict[Tile, typing.List[Path]]:
    """
    Keeps the max path from each of the start tiles as output. Since we force use a global visited set, the paths returned will never overlap each other.
    For each start tile, returns a dict from found distances to the max value found at that distance.
    Does not return paths for a tile that are a longer distance but the same value as a shorter one, so no need to prune them yourself.

    @param map:
    @param startTiles: startTiles dict is (startPriorityObject, distance) = startTiles[tile]
    @param valueFunc:
    @param maxTime:
    @param maxTurns: The max number of moves in this search.
    @param maxDepth: The max depth (based on tiles starting distances) in this search.
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
    @param ignoreNonPlayerArmy: if True, the paths returned will be calculated on the basis of just the searching players army and ignore enemy (or neutral city!) army they pass through.
    @param ignoreIncrement: if True, do not have paths returned include the city increment in their path calculation for any cities or generals in the path.
    @param pathValueFunc: if provided, this will be used instead of standard path.calculate_value. all priorityMatrix* parameters will be ignored when this is passed. (Path, valueTuple) -> float
    @param priorityMatrix: if provided, used to modify the paths value unless pathValueFunc is passed.
    @param priorityMatrixSkipStart: Dont add the path start tile priority to path val
    @param priorityMatrixSkipEnd: Dont add the path end priority val to path val.
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
    # if negativeTiles is None:
    #     negativeTiles = set()

    if fullOnly:
        oldValFunc = valueFunc

        def newValFunc(current, prioVals):
            army, dist, tileSet = fullOnlyArmyDistFunc(current, prioVals)

            validMoveCount = 0
            # if not noLog:
            #    logbook.info("{}  EVAL".format(current.toString()))

            for adj in current.movable:
                skipMt = adj.isMountain or adj.isCostlyNeutral
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
        raise ArgumentError(None, 'priorityFunc cannot be null')

    frontier: typing.List[typing.Tuple[typing.Any, int, int, Tile, Tile | None, dict]] = []
    """prioObj, distance (incl startDist), curTurns (starting at 0 per search), nextTile, fromTile, maxDict"""

    fromTileLookup: MapMatrixInterface[typing.Tuple[typing.Any, Tile]] = MapMatrix(map, None)
    # fromTileLookup: typing.Dict[int, typing.Tuple[typing.Any, Tile]] = {}

    maxValuesDict = {}

    # maxValuesTMP: typing.Dict[Tile, typing.Dict[int, typing.Any]] = {}
    # maxPriosTMP: typing.Dict[Tile, typing.Dict[int, typing.Any]] = {}
    # endNodesTMP: typing.Dict[Tile, typing.Dict[int, Tile]] = {}

    # visited = set()

    if isinstance(startTiles, dict):
        for tile, (startPriorityObject, distance) in startTiles.items():
            # visited.add(tile.tile_index)
            startVal = startPriorityObject
            startDict = {}
            maxValuesDict[tile] = startDict
            heapq.heappush(frontier, (startVal, distance, 0, tile, None, startDict))
    else:
        for tile in startTiles:
            # visited.add(tile.tile_index)
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
                if tile.player != -1 and (tile.isCity or tile.isGeneral):
                    goalIncrement = 0.5
                    if tile.player != searchingPlayer:
                        goalIncrement *= -1

            startDict = {}
            maxValuesDict[tile] = startDict

            startVal = (dist, negCityCount, negEnemyTileCount, negArmySum, tile.x, tile.y, goalIncrement)
            heapq.heappush(frontier, (startVal, dist, 0, tile, None, startDict))

    start = time.perf_counter()
    iter = 0
    foundDist = 1000
    depthEvaluated = 0

    valuePrinter = None
    if logResultValues:
        valuePrinter = lambda val: f"[{'], ['.join('{:.3f}'.format(x) for x in val)}]"
        try:
            valuePrinter(startTiles[0])
        except:
            valuePrinter = lambda val: str(val)

    while frontier:
        iter += 1
        if iter & 63 == 0:
            elapsed = time.perf_counter() - start
            if elapsed > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
                logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE-PER-DIST BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
                break

        (prioVals, dist, curTurns, current, parent, maxDict) = heapq.heappop(frontier)

        # remove if visited set
        fromVal = fromTileLookup.raw[current.tile_index]
        # fromVal = fromTileLookup.get(current.tile_index, None)
        if fromVal is not None:
            oldPrioVals, oldParent = fromVal
            # if prioVals > oldPrioVals:
            continue

        if skipTiles and current in skipTiles:
            continue

        fromTileLookup.raw[current.tile_index] = (prioVals, parent)
        # fromTileLookup[current.tile_index] = (prioVals, parent)

        newValue = valueFunc(current, prioVals)

        if newValue:
            maxMinusOne = None
            maxMinusOneStuff = maxDict.get(dist-1, None)
            if maxMinusOneStuff:
                maxMinusOne, _, __ = maxMinusOneStuff
            if maxMinusOne is None or maxMinusOne < newValue:
                val = None
                valStuff = maxDict.get(dist, None)
                if valStuff:
                    val, _, __ = valStuff

                if val is None or newValue > val:
                    foundDist = dist
                    if logResultValues:
                        if parent is not None:
                            parentString = str(parent)
                        else:
                            parentString = "None"
                        logbook.info(
                            f"+Tile {str(current)} from {parentString} at dist {dist} is new max value: {valuePrinter(newValue)}")
                    maxDict[dist] = newValue, prioVals, current

        if dist > depthEvaluated:
            depthEvaluated = dist
        if dist >= maxDepth or curTurns >= maxTurns:
            continue
        ogDist = dist
        dist += 1
        curTurns += 1
        for next in current.movable:  # new spots to try
            if next == parent:
                continue
            # if next.tile_index in visited:
            #     continue
            if (next.isMountain
                    or (noNeutralCities and next.isCostlyNeutral)
                    or (not next.discovered and next.isNotPathable)):
                continue
            nextPrio = priorityFunc(next, prioVals)
            if nextPrio is not None:
                if boundFunc is not None:
                    maxPrioStuff = maxDict.get(ogDist, None)
                    if maxPrioStuff:
                        _, maxPrio, __ = maxPrioStuff
                        bounded = boundFunc(next, nextPrio, maxPrio)
                        if bounded:
                            if not noLog:
                                logbook.info(f"Bounded off {str(next)}")
                            continue
                if skipFunc:
                    shouldSkip = skipFunc(next, nextPrio)
                    if shouldSkip:
                        continue

                # visited.add(next.tile_index)
                heapq.heappush(frontier, (nextPrio, dist, curTurns, next, current, maxDict))
    if not noLog:
        logbook.info(f"BFS-DYNAMIC-MAX ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return {}

    maxPaths: typing.Dict[Tile, typing.List[Path]] = {}

    matrixStart = 0 if not priorityMatrixSkipStart else 1
    matrixEndOffset = -1 if not priorityMatrixSkipEnd else 0

    for startTile, table in maxValuesDict.items():
        pathListForTile = []
        for dist, valObj in table.items():
            pathObject = Path()
            val, prio, tile = valObj
            # # prune any paths that are not higher value than the shorter path.
            # # THIS WOULD PRUNE LOWER VALUE PER TURN PATHS THAT ARE LONGER, WHICH IS ONLY OK IF WE ALWAYS DO PARTIAL LAYERS OF THE FULL GATHER...
            # if dist - 1 in maxValuesTMP[startTile]:
            #     shorterVal = maxValuesTMP[startTile][dist - 1]
            #     if maxValuesTMP[startTile][dist] <= shorterVal:
            #         logbook.info(f"  PRUNED PATH TO {str(startTile)} at dist {dist} because its value {shorterVal} was same or less than shorter _dists value")
            #         continue

            while True:
                if tile is None:
                    break
                pathObject.add_start(tile)

                fromData = fromTileLookup.raw[tile.tile_index]
                # fromData = fromTileLookup.get(tile.tile_index, None)
                if not fromData:
                    break

                prioVal, prevTile = fromData

                if not noLog:
                    if prioVal is not None:
                        prioStr = '] ['.join(str(x) for x in prioVal)
                        logbook.info(f"  PATH TILE {str(tile)}: Prio [{prioStr}]")
                    else:
                        logbook.info(f"  PATH TILE {str(tile)}: Prio [None]")

                if prevTile == tile:
                    raise AssertionError(f'self referential fromTile {prevTile} -> {tile}')

                tile = prevTile

            if pathValueFunc:
                pathObject.value = pathValueFunc(pathObject, val)
            else:
                pathNegs = negativeTiles
                if ignoreStartTile and not pathValueFunc:
                    negWithStart = negativeTiles.union(startTiles.keys())
                    pathNegs = negWithStart

                pathObject.calculate_value(
                    searchingPlayer,
                    teams=map.team_ids_by_player_index,
                    negativeTiles=pathNegs,
                    ignoreNonPlayerArmy=ignoreNonPlayerArmy,
                    incrementBackwards=incrementBackward,
                    ignoreIncrement=ignoreIncrement)

                if priorityMatrix:
                    for tile in pathObject.tileList[matrixStart:pathObject.length - matrixEndOffset]:
                        pathObject.value += priorityMatrix.raw[tile.tile_index]

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


def breadth_first_find_queue(
        map,
        startTiles,
        goalFunc: typing.Callable[[Tile, int, int], bool],
        maxTime=0.1,
        maxDepth=200,
        noNeutralCities=False,
        negativeTiles=None,
        skipTiles: typing.Iterable[Tile] | None = None,
        bypassDefaultSkipLogic: bool = False,
        searchingPlayer=-2,
        ignoreStartTile=False,
        prioFunc: typing.Callable[[Tile], typing.Any] | None = None,
        noLog: bool = False,
) -> Path | None:
    """
    ALWAYS slower than a-star-find. Do not use except when the goalFunc is actually dynamic...

    goalFunc is goalFunc(current, army, dist)
    prioFunc is prioFunc(tile) - bigger is better, tuples supported, True comes before False etc.
    bypassDefaultSkipLogic allows you to search through undiscovered mountains etc.
    """

    if searchingPlayer == -2:
        searchingPlayer = map.player_index

    frontier = deque()
    nodeValues: MapMatrixInterface[typing.Tuple[int, Tile | None]] = MapMatrix(map)  # (army, fromTile)
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
            nodeValues.raw[tile.tile_index] = (startArmy, None)
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
            nodeValues.raw[tile.tile_index] = (startArmy, None)
            if (tile.isCity or tile.isGeneral) and tile.player != -1:
                goalInc = 0.5
            if ignoreStartTile:
                startArmy = 0
            frontier.appendleft((tile, 0, startArmy, goalInc))

    if skipTiles:
        for t in skipTiles:
            nodeValues.raw[t.tile_index] = (None, None)

    iter = 0
    start = time.perf_counter()
    foundGoal = False
    foundArmy = -100000
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    while frontier and not foundGoal:
        iter += 1
        (current, dist, army, goalInc) = frontier.pop()
        if dist > depthEvaluated:
            depthEvaluated = dist
            if foundGoal:
                break
        if dist <= maxDepth and not foundGoal:
            nextSearch = current.movable
            # if prioFunc is not None:
            #     nextSearch = sorted(current.movable, key=prioFunc, reverse=True)
            newDist = dist + 1
            for nextTile in nextSearch:  # new spots to try
                curTuple = nodeValues.raw[nextTile.tile_index]
                if (curTuple is not None
                        or (
                                not bypassDefaultSkipLogic
                                and (
                                        nextTile.isMountain
                                        or (noNeutralCities and nextTile.isCostlyNeutral)
                                        or (not nextTile.discovered and nextTile.isNotPathable)
                                )
                        )
                ):
                    continue

                inc = 0 if not ((nextTile.isCity and nextTile.player != -1) or nextTile.isGeneral) else dist / 2
                # new_cost = cost_so_far[current] + graph.cost(current, next)
                nextArmy = army - 1
                if negativeTiles is None or nextTile not in negativeTiles:
                    if searchingPlayer == nextTile.player:
                        nextArmy += nextTile.army + inc
                    else:
                        nextArmy -= (nextTile.army + inc)
                nodeValues.raw[nextTile.tile_index] = (nextArmy, current)
                if goalFunc(nextTile, nextArmy, newDist):
                    foundGoal = True
                    foundDist = newDist
                    foundArmy = nextArmy
                    endNode = nextTile
                    break
                frontier.appendleft((nextTile, newDist, nextArmy, goalInc))

    if not noLog:
        logbook.info(
            f"BFS-FIND-QUEUE ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
    if foundDist >= 1000:
        return None

    node = endNode
    nodes = []
    army = foundArmy

    while node is not None:
        nodes.append((army, node))

        (army, node) = nodeValues.raw[node.tile_index]
    pathObject = Path(foundArmy)
    revNodes = nodes[::-1]
    for i, armyNode in enumerate(revNodes):
        (curArmy, curNode) = armyNode
        if curNode is not None:
            pathObject.add_next(curNode)

    if not noLog:
        logbook.info(
            f"BFS-FIND-QUEUE found path OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    return pathObject


def breadth_first_find_dist_queue(
        startTiles,
        goalFunc: typing.Callable[[Tile, int], bool],
        maxDepth=200,
        noNeutralCities=False,
        skipTiles=None,
        bypassDefaultSkipLogic: bool = False,
        noLog: bool = False,
) -> Path | None:
    """
    NEVER USE THIS. Distmapper is better and if we DID need a distance func, aStarDistance is faster. in all cases, even at distance 2.
    goalFunc is goalFunc(current, dist)
    prioFunc is prioFunc(tile) - bigger is better, tuples supported, True comes before False etc.
    bypassDefaultSkipLogic allows you to search through undiscovered mountains etc.
    """

    frontier = deque()
    visited: typing.Set[int] = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            startDist = startTiles[tile]
            if tile.isMountain and not bypassDefaultSkipLogic:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            frontier.appendleft((tile, startDist))
            visited.add(tile.tile_index)
    else:
        for tile in startTiles:
            if tile.isMountain and not bypassDefaultSkipLogic:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            frontier.appendleft((tile, 0))
            visited.add(tile.tile_index)

    if skipTiles:
        for t in skipTiles:
            visited.add(t.tile_index)

    iter = 0
    start = time.perf_counter()
    foundDist = 1000
    while frontier:
        iter += 1
        (current, dist) = frontier.pop()
        if goalFunc(current, dist):
            foundDist = dist
            break
        for nextTile in current.movable:  # new spots to try
            if (
                nextTile.tile_index in visited
                or (
                    not bypassDefaultSkipLogic
                    and (
                        nextTile.isMountain
                        or (noNeutralCities and nextTile.isCostlyNeutral)
                        or (not nextTile.discovered and nextTile.isNotPathable)
                    )
                )
            ):
                continue
            visited.add(nextTile.tile_index)

            newDist = dist + 1
            frontier.appendleft((nextTile, newDist))

    if not noLog:
        logbook.info(
            f"BFS-FIND-QUEUE-DIST ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}")
    return foundDist


def breadth_first_foreach(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile], bool | None],
        skipTiles=None,
        noLog=False,
        bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Return True to skip.
    Same as breadth_first_foreach_dist, except the foreach function does not get the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = deque()
    globalVisited = set()
    if skipTiles:
        for tile in skipTiles:
            if not noLog:
                logbook.info(f"    skipTiles contained {tile}")
            globalVisited.add(tile.tile_index)

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    start = time.perf_counter()
    iter = 0
    depthEvaluated = 0
    dist = 0
    while frontier:
        iter += 1

        (current, dist) = frontier.pop()
        if current.tile_index in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current.tile_index)
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)) and dist > 0:
            continue

        if foreachFunc(current):
            continue

        newDist = dist + 1
        for nextTile in current.movable:  # new spots to try
            frontier.appendleft((nextTile, newDist))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach. startTiles[0] {startTiles[0].x},{startTiles[0].y}: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def breadth_first_foreach_with_state(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile] | typing.Dict[Tile, typing.Any],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, typing.Any | None], typing.Any | None],
        skipTiles=None,
        noLog=False,
        bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    INVERSE of normal return of forceach, return None/False to skip. Return a state object to continue to the next neighbors.
    Same as breadth_first_foreach_dist, except the foreach function does not get the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = deque()
    globalVisited = set()
    if skipTiles:
        for tile in skipTiles:
            if not noLog:
                logbook.info(f"    skipTiles contained {tile}")
            globalVisited.add(tile.tile_index)

    if isinstance(startTiles, dict):
        for tile, startVal in startTiles.items():
            frontier.appendleft((tile, 0, startVal))

    else:
        for tile in startTiles:
            frontier.appendleft((tile, 0, None))

    start = time.perf_counter()
    iter = 0
    dist = 0
    while frontier:
        iter += 1

        (current, dist, state) = frontier.pop()
        if current.tile_index in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current.tile_index)
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)) and dist > 0:
            continue

        nextState = foreachFunc(current, state)
        if not nextState:
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist, nextState))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach_with_state: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def breadth_first_foreach_with_state_and_start_dist(
        map: MapBase,
        startTiles: typing.Dict[Tile, typing.Tuple[int, typing.Any]],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, typing.Any | None], typing.Any | None],
        skipTiles=None,
        noLog=False,
        bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    INVERSE of normal return of forceach, return None/False to skip. Return a state object to continue to the next neighbors.
    Same as breadth_first_foreach_dist, except the foreach function does not get the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = HeapQueue()
    globalVisited = set()
    if skipTiles:
        for tile in skipTiles:
            if not noLog:
                logbook.info(f"    skipTiles contained {tile}")
            globalVisited.add(tile.tile_index)

    if isinstance(startTiles, dict):
        for tile, (startDist, startVal) in startTiles.items():
            frontier.put((startDist, startVal, tile))

    else:
        raise AssertionError('startTiles must be dict here')

    start = time.perf_counter()
    iter = 0
    dist = 0
    while frontier:
        iter += 1

        (dist, state, current) = frontier.get()
        if current.tile_index in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current.tile_index)
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)) and dist > 0:
            continue

        nextState = foreachFunc(current, state)
        if not nextState:
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.put((newDist, nextState, next))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach_with_state_and_start_dist: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def breadth_first_foreach_dist(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], bool | None],
        skipTiles: typing.Set[Tile] = None,
        noLog=False,
        bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Return True to skip.
    Same as breadth_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile, preventing the foreach from ever reaching it.
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles unless you skip them yourself with skipTiles/skipFunc.
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = deque()
    globalVisited = set()
    if skipTiles:
        for tile in skipTiles:
            globalVisited.add(tile.tile_index)

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    if not noLog:
        start = time.perf_counter()
    iter = 0
    dist = 0
    while frontier:
        iter += 1

        (current, dist) = frontier.pop()
        if current.tile_index in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current.tile_index)
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)):
            continue

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for nextTile in current.movable:  # new spots to try
            frontier.appendleft((nextTile, newDist))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach_dist. startTiles[0] {startTiles[0].x},{startTiles[0].y}: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def breadth_first_foreach_dist_fast_incl_neut_cities(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], bool | None]):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Same as breadth_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier: typing.Deque[typing.Tuple[Tile, int]] = deque()

    globalVisited = set()

    for tile in startTiles:
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()
        if current.isNotPathable:
            continue
        if current.tile_index in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current.tile_index)

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for nextTile in current.movable:  # new spots to try
            frontier.appendleft((nextTile, newDist))


def breadth_first_foreach_dist_fast_with_start_dist_incl_neut_cities(
        map: MapBase,
        startTiles: typing.Iterable[typing.Tuple[int, Tile]],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], bool | None]):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Same as breadth_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @return:
    """
    frontier: typing.Deque[typing.Tuple[Tile, int, int]] = deque()

    globalVisited = set()

    for dist, tile in startTiles:
        frontier.appendleft((tile, dist, 0))

    while frontier:
        (current, dist, depth) = frontier.pop()
        if current.isNotPathable:
            continue
        if current.tile_index in globalVisited:
            continue
        if depth > maxDepth:
            break
        globalVisited.add(current.tile_index)

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        newDepth = depth + 1
        for n in current.movable:  # new spots to try
            frontier.appendleft((n, newDist, newDepth))


def breadth_first_foreach_dist_fast_no_neut_cities(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], bool | None]):
    """
    WILL NOT run the foreach function against mountains (use breadth_first_foreach_dist_fast_no_default_skip to allow mountains).
    DOES skip neutral cities by default.
    Same as breadth_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier: typing.Deque[typing.Tuple[Tile, int]] = deque()

    globalVisited = set()

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))
        globalVisited.add(tile.tile_index)

    while frontier:
        (current, dist) = frontier.pop()

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        if newDist > maxDepth:
            continue
        for nextTile in current.movable:  # new spots to try
            if nextTile.tile_index in globalVisited:
                continue
            globalVisited.add(nextTile.tile_index)
            if nextTile.isObstacle:
                continue
            frontier.appendleft((nextTile, newDist))


def breadth_first_foreach_dist_fast_no_default_skip(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], bool | None]):
    """
    WILL run the foreach function against mountains.
    DOES NOT skip neutral cities.
    Same as breadth_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier: typing.Deque[typing.Tuple[Tile, int]] = deque()

    globalVisited = set()

    for tile in startTiles:
        frontier.appendleft((tile, 0))
        globalVisited.add(tile.tile_index)

    while frontier:
        (current, dist) = frontier.pop()

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        if newDist > maxDepth:
            continue
        for nextTile in current.movable:  # new spots to try
            if nextTile.tile_index in globalVisited:
                continue
            globalVisited.add(nextTile.tile_index)
            frontier.appendleft((nextTile, newDist))


def breadth_first_foreach_dist_fast_free_swamp_no_default_skip(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], bool | None]):
    """
    WILL run the foreach function against mountains.
    Swamps do not count for distance.
    DOES NOT skip neutral cities.
    Same as breadth_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier: typing.Deque[typing.Tuple[Tile, int]] = deque()

    globalVisited = set()

    for tile in startTiles:
        frontier.appendleft((tile, 0))
        globalVisited.add(tile.tile_index)

    while frontier:
        (current, dist) = frontier.pop()

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        if newDist > maxDepth:
            continue
        if current.isSwamp:
            newDist -= 1
        for nextTile in current.movable:  # new spots to try
            if nextTile.tile_index in globalVisited:
                continue
            globalVisited.add(nextTile.tile_index)
            frontier.appendleft((nextTile, newDist))


def breadth_first_foreach_fast_no_neut_cities(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile], bool | None],
):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    DOES skip neutral cities.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier: typing.Deque[typing.Tuple[Tile, int]] = deque()

    globalVisited = set()

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        globalVisited.add(tile.tile_index)
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()

        if foreachFunc(current):
            continue

        newDist = dist + 1
        if newDist > maxDepth:
            continue
        for nextTile in current.movable:  # new spots to try
            if nextTile.tile_index in globalVisited:
                continue
            globalVisited.add(nextTile.tile_index)
            if nextTile.isObstacle:
                continue
            frontier.appendleft((nextTile, newDist))


def breadth_first_foreach_dist_revisit_callback(
        map: MapBase,
        startTiles: typing.List[Tile] | typing.Set[Tile],
        maxDepth: int,
        foreachFunc: typing.Callable[[Tile, int], None],
        revisitFunc: typing.Callable[[Tile, int], None],
        skipTiles: typing.Set[Tile] = None,
        noLog=False,
        bypassDefaultSkip: bool = False):
    """
    WILL NOT run the foreach function against mountains unless told to bypass that with bypassDefaultSkip
    (at which point you must explicitly skipFunc mountains / obstacles to prevent traversing through them)
    Does NOT skip neutral cities by default.
    Return True to skip.
    Same as breadth_first_foreach, except the foreach function also gets the distance parameter passed to it.

    @param map:
    @param startTiles:
    @param maxDepth:
    @param foreachFunc: ALSO the skip func. Return true to avoid adding neighbors to queue.
    @param revisitFunc: Called when a node is popped from the queue at a different dist than its original
    @param skipTiles: Evaluated BEFORE the foreach runs on a tile
    @param noLog:
    @param bypassDefaultSkip: If true, does NOT skip mountains / undiscovered obstacles
    @return:
    """
    if len(startTiles) == 0:
        return

    frontier = deque()
    globalVisited = MapMatrix(map, None)
    if skipTiles:
        for tile in skipTiles:
            globalVisited.raw[tile.tile_index] = 1000

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    start = time.perf_counter()
    iter = 0
    dist = 0
    while frontier:
        iter += 1

        (current, dist) = frontier.pop()
        prevDist = globalVisited.raw[current.tile_index]
        if prevDist:
            if prevDist < dist:
                revisitFunc(current, dist)
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current.tile_index)
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)):
            continue
        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for nextTile in current.movable:  # new spots to try
            frontier.appendleft((nextTile, newDist))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach_dist_revisit_callback. startTiles[0] {startTiles[0].x},{startTiles[0].y}: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def build_distance_map_matrix(map: MapBase, startTiles: typing.Iterable[Tile]) -> MapMatrixInterface[int]:
    distanceMap = MapMatrix(map, 1000)

    frontier = deque()
    raw = distanceMap.raw
    for startTile in startTiles:
        raw[startTile.tile_index] = 0
        frontier.append((startTile, 0))

    dist: int
    current: Tile
    while frontier:
        (current, dist) = frontier.popleft()
        newDist = dist + 1
        for n in current.movable:  # new spots to try
            if raw[n.tile_index] != 1000:
                continue

            raw[n.tile_index] = newDist

            if n.isObstacle:
                continue

            frontier.append((n, newDist))

    return distanceMap


def build_distance_map_matrix_with_max_depth(map: MapBase, startTiles: typing.Iterable[Tile], maxDepth: int) -> MapMatrixInterface[int]:
    distanceMap = MapMatrix(map, 1000)

    frontier = deque()
    raw = distanceMap.raw
    for startTile in startTiles:
        raw[startTile.tile_index] = 0
        frontier.append((startTile, 0))

    dist: int
    current: Tile
    while frontier:
        (current, dist) = frontier.popleft()
        newDist = dist + 1
        if newDist > maxDepth:
            break
        for n in current.movable:  # new spots to try
            if raw[n.tile_index] != 1000:
                continue

            raw[n.tile_index] = newDist

            if n.isObstacle:
                continue

            frontier.append((n, newDist))

    return distanceMap


def build_distance_map_matrix_with_skip(map, startTiles, skipTiles=None, maxDepth: int = 1000) -> MapMatrixInterface[int]:
    """
    Builds a distance map to all reachable tiles (including neutral cities). Does not put distances in for mountains / undiscovered obstacles.

    @param map:
    @param startTiles:
    @param skipTiles:
    @param maxDepth:
    @return:
    """
    if not skipTiles:
        return build_distance_map_matrix_with_max_depth(map, startTiles, maxDepth)

    if not isinstance(skipTiles, set) and not isinstance(skipTiles, MapMatrix) and not isinstance(skipTiles, MapMatrixSet):
        skipTiles = {t for t in skipTiles}

    distanceMap = MapMatrix(map, 1000)

    frontier = deque()
    raw = distanceMap.raw
    for startTile in startTiles:
        raw[startTile.tile_index] = 0
        frontier.append((startTile, 0))

    dist: int
    current: Tile
    while frontier:
        (current, dist) = frontier.popleft()
        newDist = dist + 1
        if newDist > maxDepth:
            break
        for n in current.movable:  # new spots to try
            if raw[n.tile_index] != 1000:
                continue

            raw[n.tile_index] = newDist

            if n.isObstacle or n in skipTiles:
                continue

            frontier.append((n, newDist))

    return distanceMap


def extend_distance_map_matrix(map, startTiles, toExtend: MapMatrixInterface[int], skipTiles=None, maxDepth: int = 1000):
    """
    Modifies a distance map matrix in place efficiently with the minimum of multiple distances

    @param map:
    @param startTiles:
    @param toExtend: the mapmatrix to MODIFY with the minimum of existing distances, and distances from the new start points.
    @param skipTiles:
    @param maxDepth:
    @return:
    """

    if not skipTiles:
        skipTiles = None
    elif not isinstance(skipTiles, set) and not isinstance(skipTiles, MapMatrix) and not isinstance(skipTiles, MapMatrixSet):
        skipTiles = {t for t in skipTiles}

    if skipTiles is None:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if toExtend.raw[tile.tile_index] < dist:
                return True

            toExtend.raw[tile.tile_index] = dist

            return tile.isCostlyNeutral
    else:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if toExtend.raw[tile.tile_index] < dist:
                return True

            if tile in skipTiles:
                return True

            toExtend.raw[tile.tile_index] = dist

            return tile.isCostlyNeutral

    breadth_first_foreach_dist_fast_incl_neut_cities(
        map,
        startTiles,
        maxDepth,
        bfs_dist_mapper)


def build_distance_map_matrix_with_start_dist(map, startTiles: typing.Iterable[typing.Tuple[int, Tile]], skipTiles=None, maxDepth: int = 1000) -> MapMatrixInterface[int]:
    """
    Builds a distance map to all reachable tiles (including neutral cities). Does not put distances in for mountains / undiscovered obstacles.

    @param map:
    @param startTiles:
    @param skipTiles:
    @param maxDepth:
    @return:
    """
    distanceMap = MapMatrix(map, 1000)

    if not skipTiles:
        skipTiles = None
    elif not isinstance(skipTiles, set) and not isinstance(skipTiles, MapMatrix) and not isinstance(skipTiles, MapMatrixSet):
        skipTiles = {t for t in skipTiles}

    if skipTiles is None:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            distanceMap.raw[tile.tile_index] = dist

            return tile.isCostlyNeutral
    else:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if tile in skipTiles:
                return True

            distanceMap.raw[tile.tile_index] = dist

            return tile.isCostlyNeutral

    frontier: typing.Deque[typing.Tuple[Tile, int, int]] = deque()

    globalVisited = set()

    for dist, tile in startTiles:
        frontier.appendleft((tile, dist, 0))

    while frontier:
        (current, dist, depth) = frontier.pop()
        if current.isNotPathable:
            continue
        if current.tile_index in globalVisited:
            continue
        if depth > maxDepth:
            break
        globalVisited.add(current.tile_index)

        if bfs_dist_mapper(current, dist):
            continue

        newDist = dist + 1
        newDepth = depth + 1
        for n in current.movable:  # new spots to try
            frontier.appendleft((n, newDist, newDepth))

    return distanceMap

#
# def build_reachability_cost_map_matrix(map, startTiles: typing.Iterable[Tile], maxDepth: int = 1000) -> MapMatrixInterface[int]:
#     """
#     Builds a distance map to all reachable tiles (including neutral cities). Does not put distances in for mountains / undiscovered obstacles.
#
#     @param map:
#     @param startTiles:
#     @param maxDepth:
#     @return:
#     """
#     distanceMap = MapMatrix(map, 1000)
#     costMap = MapMatrix(map, 0)
#
#     frontier: typing.List[typing.Tuple[int, int, int, int, Tile]] = []
#     """weightedDistance, cost, true distance, move cost weight, Tile"""
#
#     globalVisited = set()
#
#     for tile in startTiles:
#         heapq.heappush(frontier, (0, 0, 1, tile))
#         globalVisited.add(tile.tile_index)
#
#     while frontier:
#         (weightedDist, cost, dist, curCostPerMove, current) = heapq.heappop(frontier)
#
#         nextDist = dist + 1
#         for n in current.movable:  # new spots to try
#             if n.tile_index in globalVisited:
#                 continue
#             globalVisited.add(n.tile_index)
#             nextCost = cost
#             nextCostPerMove = curCostPerMove
#
#             distanceMap.raw[n.tile_index] = weightedDist
#             costMap.raw[n.tile_index] = cost
#
#             nextCost = curCost
#             if n.isCostlyNeutral:
#                 # extra cost for bad cities
#                 nextCost *= 2
#                 weightedDist += 2 * curCost
#             elif n.isNotPathable:
#                 continue
#             nextDist = weightedDist
#             if n.isCity and n.isNeutral:
#
#                 curCost *= 2
#                 weightedDist
#             if n.isCity and n.isNeutral:
#                 curCost *= 2
#             if dist > maxDepth:
#                 break
#
#             distanceMap.raw[current.tile_index] = weightedDist
#
#             heapq.heappush(frontier, (nextWeightedDist, nextCost, nextDist, curCost, n))
#
#     return distanceMap


def build_reachability_cost_map_matrix(map, startTiles: typing.Iterable[Tile], maxDepth: int = 1000) -> typing.Tuple[MapMatrixInterface[typing.List[Tile]], MapMatrixInterface[int]]:
    """
    Maps out the costs to reach all tiles. Maps out the tiles that lead to other tiles.

    @param map:
    @param startTiles:
    @param maxDepth:
    @return:
    """
    costMap = MapMatrix(map, 10000)
    throughMap = MapMatrix(map, None)

    frontier: typing.Deque[typing.Tuple[int, Tile, Tile | None]] = deque()
    """true distance, Tile, throughTile"""

    nextFrontier: typing.List[typing.Tuple[int, int, Tile, Tile | None]] = []
    """next cost, true distance, Tile, throughCaptureTile"""

    globalVisited = set()

    for tile in startTiles:
        nextFrontier.append((0, 0, tile, None))
        globalVisited.add(tile.tile_index)
        costMap.raw[tile.tile_index] = 0

    while nextFrontier:
        startCost, startDist, startTile, throughCaptureTile = heapq.heappop(nextFrontier)
        # curCost, curDist, curTile = startCost, startDist, startTile
        # while curCost == startCost:
        #     frontier.append((curDist, curTile))
        #     if not nextFrontier:
        #         break
        #     curCost, curDist, curTile = heapq.heappop(nextFrontier)
        #
        # if curCost > startCost:
        #     heapq.heappush(nextFrontier, (curCost, curDist, curTile))

        frontier.append((startDist, startTile, throughCaptureTile))

        cost = startCost
        while frontier:
            (dist, current, throughTile) = frontier.popleft()

            if dist > maxDepth:
                continue

            nextDist = dist + 1
            for n in current.movable:
                if n.tile_index in globalVisited:
                    continue
                globalVisited.add(n.tile_index)

                costMap.raw[n.tile_index] = cost
                throughMap.raw[n.tile_index] = throughTile

                if not n.isCostlyNeutral and n.isNotPathable:
                    continue

                if n.isSwamp:
                    heapq.heappush(nextFrontier, (cost + 1 + n.army, nextDist, n, throughTile))
                elif n.player == -1 and n.army > 0:
                    heapq.heappush(nextFrontier, (cost + n.army, nextDist, n, n))
                else:
                    frontier.append((nextDist, n, throughTile))

    return throughMap, costMap


def build_distance_map_matrix_with_start_dist_increasing(map, startTiles: typing.Iterable[typing.Tuple[int, Tile]], skipTiles=None, maxDepth: int = 1000) -> MapMatrixInterface[int]:
    """
    Builds a distance map to all reachable tiles (including neutral cities). Does not put distances in for mountains / undiscovered obstacles.
    Tile 0 in the enumerable will have dist 0, etc.

    @param map:
    @param startTiles:
    @param skipTiles:
    @param maxDepth:
    @return:
    """
    distanceMap = MapMatrix(map, 1000)

    if not skipTiles:
        skipTiles = None
    elif not isinstance(skipTiles, set) and not isinstance(skipTiles, MapMatrix) and not isinstance(skipTiles, MapMatrixSet):
        skipTiles = {t for t in skipTiles}

    if skipTiles is None:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            distanceMap.raw[tile.tile_index] = dist

            return tile.isCostlyNeutral
    else:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if tile in skipTiles:
                return True

            distanceMap.raw[tile.tile_index] = dist

            return tile.isCostlyNeutral

    frontier: typing.Deque[typing.Tuple[Tile, int, int]] = deque()

    globalVisited = set()

    for dist, tile in startTiles:
        frontier.appendleft((tile, dist, 0))

    while frontier:
        (current, dist, depth) = frontier.pop()
        if current.isNotPathable:
            continue
        if current.tile_index in globalVisited:
            continue
        if depth > maxDepth:
            break
        globalVisited.add(current.tile_index)

        if bfs_dist_mapper(current, dist):
            continue

        newDist = dist + 1
        newDepth = depth + 1
        for n in current.movable:  # new spots to try
            frontier.appendleft((n, newDist, newDepth))

    return distanceMap


def build_distance_map_matrix_allow_pathing_through_neut_cities(map, startTiles, skipTiles=None) -> MapMatrixInterface[int]:
    """
    Builds a distance map that allows pathing through neutral cities.

    @param map:
    @param startTiles:
    @param skipTiles:
    @return:
    """
    distanceMap = MapMatrix(map, 1000)

    if not skipTiles:
        skipTiles = None
    elif not isinstance(skipTiles, set) and not isinstance(skipTiles, MapMatrix) and not isinstance(skipTiles, MapMatrixSet):
        skipTiles = {t for t in skipTiles}

    if skipTiles is None:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            distanceMap.raw[tile.tile_index] = dist
            return False
    else:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if tile in skipTiles:
                return True

            distanceMap.raw[tile.tile_index] = dist
            return False

    breadth_first_foreach_dist_fast_incl_neut_cities(
        map,
        startTiles,
        1000,
        bfs_dist_mapper)

    return distanceMap


def build_distance_map_matrix_include_set(map, startTiles, containsSet: typing.Container[Tile]) -> MapMatrixInterface[int]:
    """
    Builds a distance matrix but instead of having skipTiles, instead a set of only ALLOWED tiles is provided. All neighbors will be skipped unless they are in containsSet.

    @param map:
    @param startTiles:
    @param containsSet:
    @return:
    """
    distanceMap = MapMatrix(map, 1000)

    maxDepth = 1000

    if len(startTiles) == 0:
        return distanceMap

    frontier = deque()
    globalVisited = set()

    for tile in startTiles:
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()
        if current.tile_index in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current.tile_index)
        if current.isMountain or (not current.discovered and current.isNotPathable):
            continue

        distanceMap.raw[current.tile_index] = dist
        if current.isCostlyNeutral:
            continue

        newDist = dist + 1
        for nextTile in current.movable:  # new spots to try
            if nextTile in containsSet:
                frontier.appendleft((nextTile, newDist))

    return distanceMap


def euclidean_distance(v: Tile, goal: Tile) -> float:
    """Not fast, does square root"""

    return ((v.x - goal.x)**2 + (v.y - goal.y)**2)**0.5


def bidirectional_a_star_pq(start: Tile, goal: Tile, allowNeutralCities: bool = False) -> Path | None:
    """
    Lifted from
    https://stackoverflow.com/a/42046086
    """
    if start == goal:
        raise AssertionError(f'start end end were both {str(start)}')

    # pq_s = []
    # pq_t = []
    pq_s = HeapQueue()
    pq_t = HeapQueue()
    closed_s = dict()
    closed_t = dict()
    g_s = dict()
    g_t = dict()

    g_s[start] = 0
    g_t[goal] = 0

    cameFrom1 = dict()
    cameFrom2 = dict()

    def h1(v: Tile) -> float:  # heuristic for forward search (from start to goal)
        return euclidean_distance(v, goal)

    def h2(v: Tile) -> float:  # heuristic for backward search (from goal to start)
        return euclidean_distance(v, start)

    cameFrom1[start] = False
    cameFrom2[goal] = False

    pq_s.put((h1(start), start))
    pq_t.put((h2(goal), goal))

    done = False
    i = 0

    mu = 10 ** 301  # 10**301 plays the role of infinity
    connection = None
    stopping_distance = None

    while pq_s.queue and pq_t.queue and not done:
        i = i + 1
        if i & 1 == 1:  # alternate between forward and backward A*
            curTile: Tile
            fu, curTile = pq_s.get()
            closed_s[curTile] = True
            for v in curTile.movable:
                if v.isMountain:
                    continue
                if v.isCostlyNeutral and not allowNeutralCities:
                    continue
                # weight = graph[curTile][v]['weight']
                weight = 1
                if v in g_s:
                    if g_s[curTile] + weight < g_s[v]:
                        g_s[v] = g_s[curTile] + weight
                        cameFrom1[v] = curTile
                        if v in closed_s:
                            del closed_s[v]
                        # if v in pq_s:
                        #     pq_s.update((g_s[v]+h1(v), v))
                        # else:
                        #     pq_s.append((g_s[v]+h1(v), v))
                else:
                    g_s[v] = g_s[curTile] + weight
                    cameFrom1[v] = curTile
                    pq_s.put((g_s[v]+h1(v), v))
        else:
            fu, curTile = pq_t.get()
            closed_t[curTile] = True
            for v in curTile.movable:
                if v.isMountain:
                    continue
                if v.isCostlyNeutral and not allowNeutralCities:
                    continue
                # weight = graph[curTile][v]['weight']
                weight = 1

                if v in g_t:
                    if g_t[curTile] + weight < g_t[v]:
                        g_t[v] = g_t[curTile] + weight
                        cameFrom2[v] = curTile
                        if v in closed_t:
                            del closed_t[v]
                        # if v in pq_t:
                        #     pq_t.update((g_t[v]+h2(v), v))
                        # else:
                        #     pq_t.append((g_t[v]+h2(v), v))
                else:
                    g_t[v] = g_t[curTile] + weight
                    cameFrom2[v] = curTile
                    pq_t.put((g_t[v]+h2(v), v))

        if curTile in closed_s and curTile in closed_t:
            curMu = g_s[curTile] + g_t[curTile]
            # logbook.info(f'mu {curTile} g_s {g_s[curTile]} g_t {g_t[curTile]} = {curMu} vs best {mu}')
            if curMu < mu:
                mu = curMu
                connection = curTile
                # done = True
                if len(pq_s.queue) and len(pq_t.queue):
                    startHeur, t = pq_s.queue[0]
                    endHeur, t2 = pq_t.queue[0]
                    stopping_distance = max(startHeur, endHeur)
                    if mu <= stopping_distance:
                        done = True
                        connection = curTile
                        continue

    if connection is None:
        # start and goal are not connected
        return None

    #print cameFrom1
    #print cameFrom2

    pathForwards = []
    current = connection
    #print current
    while current != False:
        #print predecessor
        pathForwards.append(current)
        current = cameFrom1[current]

    path = Path()
    for tile in reversed(pathForwards):
        path.add_next(tile)

    current = connection
    successor = cameFrom2[current]
    while successor != False:
        path.add_next(successor)
        current = successor
        successor = cameFrom2[current]

    return path


def bidirectional_a_star(start: Tile, goal: Tile, allowNeutralCities: bool = False) -> Path | None:
    """
    Lifted from
    https://stackoverflow.com/a/42046086
    """
    if start == goal:
        raise AssertionError(f'start end end were both {str(start)}')

    pq_s = []
    pq_t = []
    startCosts = dict()
    goalCosts = dict()

    startCosts[start.tile_index] = 0
    goalCosts[goal.tile_index] = 0

    startCameFrom = dict()
    goalCameFrom = dict()

    startCameFrom[start.tile_index] = False
    goalCameFrom[goal.tile_index] = False

    heapq.heappush(pq_s, (_shortestPathHeurTile(goal, start), 0, start))
    heapq.heappush(pq_t, (_shortestPathHeurTile(start, goal), 0, goal))

    i = 0

    mu = 10 ** 301  # 10**301 plays the role of infinity
    connection = None
    weight = 1

    while pq_s and pq_t:
        i += 1
        if i & 1 == 1:  # alternate between forward and backward A*
            curTile: Tile
            fu, dist, curTile = heapq.heappop(pq_s)
            if fu > mu:
                continue
            curTileCost = dist + weight
            for v in curTile.movable:
                if v.isMountain:
                    continue
                if v.isCostlyNeutral and not allowNeutralCities:
                    continue
                if v.tile_index in startCosts:
                    continue

                nextHeur = curTileCost+_shortestPathHeurTile(goal, v)
                # if nextHeur > mu:
                #     continue
                startCosts[v.tile_index] = curTileCost
                startCameFrom[v.tile_index] = curTile
                heapq.heappush(pq_s, (nextHeur, curTileCost, v))
        else:
            fu, dist, curTile = heapq.heappop(pq_t)
            if fu > mu:
                continue
            curTileCost = dist + weight
            for v in curTile.movable:
                if v.isMountain:
                    continue
                if v.isCostlyNeutral and not allowNeutralCities:
                    continue
                if v.tile_index in goalCosts:
                    continue

                nextHeur = curTileCost+_shortestPathHeurTile(start, v)
#                 if nextHeur > mu:
#                     continue
                goalCosts[v.tile_index] = curTileCost
                goalCameFrom[v.tile_index] = curTile
                heapq.heappush(pq_t, (nextHeur, curTileCost, v))

        if curTile.tile_index in startCameFrom and curTile.tile_index in goalCameFrom:
            curMu = startCosts[curTile.tile_index] + goalCosts[curTile.tile_index]
            # logbook.info(f'mu {curTile} g_s {g_s[curTile]} g_t {g_t[curTile]} = {curMu} vs best {mu}')
            if curMu < mu:
                mu = curMu
                connection = curTile
                if pq_t and pq_s:
                    stopping_distance = max(pq_t[0][0], pq_s[0][0])
                    if mu <= stopping_distance:
                        connection = curTile
                        break

    if connection is None:
        # start and goal are not connected
        return None

    #print cameFrom1
    #print cameFrom2

    pathForwards = []
    current = connection
    #print current
    while current is not False:
        #print predecessor
        pathForwards.append(current)
        current = startCameFrom[current.tile_index]

    path = Path()
    for tile in reversed(pathForwards):
        path.add_next(tile)

    current = connection
    successor = goalCameFrom[current.tile_index]
    while successor is not False:
        path.add_next(successor)
        current = successor
        successor = goalCameFrom[current.tile_index]

    return path

import sys

# Number of vertices in the graph
V = 4

# A utility function to find the vertex with minimum distance value, from
# the set of vertices not yet included in shortest path tree


def minDistance(dist, sptSet):
    # Initialize min value
    min_val = sys.maxsize
    min_index = 0

    for v in range(V):
        if sptSet[v] == False and dist[v] <= min_val:
            min_val = dist[v]
            min_index = v

    return min_index

# A utility function to print the constructed distance array


def printSolution(dist):
    print("Following matrix shows the shortest distances between every pair of vertices")
    for i in range(V):
        for j in range(V):
            if dist[i][j] == sys.maxsize:
                print("{:>7s}".format("INF"), end="")
            else:
                print("{:>7d}".format(dist[i][j]), end="")
        print()

# Solves the all-pairs shortest path problem using Johnson's algorithm


def floydWarshall(map: MapBase) -> MapMatrixInterface[MapMatrixInterface[int]]:
    # dist = [[0 for x in range(V)] for y in range(V)]
    dist: MapMatrixInterface[MapMatrixInterface[int]] = MapMatrix(map, None)
    for tile in map.get_all_tiles():
        dist[tile] = MapMatrix(map, 1000)

    # Initialize the solution matrix same as input graph matrix. Or
    # we can say the initial values of shortest distances are based
    # on shortest paths considering no intermediate vertex.
    for tile in map.get_all_tiles():
        if tile.isObstacle:
            continue
        for adj in tile.movable:
            if adj.isObstacle:
                continue
            dist[tile][adj] = 1

    # Add all vertices one by one to the set of intermediate vertices.
    # Before start of a iteration, we have shortest distances between all
    # pairs of vertices such that the shortest distances consider only the
    # vertices in set {0, 1, 2, .. k-1} as intermediate vertices.
    # After the end of a iteration, vertex no. k is added to the set of
    # intermediate vertices and the set becomes {0, 1, 2, .. k}
    for k in map.get_all_tiles():
        # Pick all vertices as source one by one
        for i in map.get_all_tiles():
            # Pick all vertices as destination for the
            # above picked source
            for j in map.get_all_tiles():
                # If vertex k is on the shortest path from
                # i to j, then update the value of dist[i][j]
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]

    return dist


def dumbassDistMatrix(map: MapBase) -> MapMatrixInterface[MapMatrixInterface[int]]:
    # dist = [[0 for x in range(V)] for y in range(V)]
    dist: MapMatrixInterface[MapMatrixInterface[int]] = MapMatrix(map, None)
    for tile in map.tiles_by_index:
        dist.raw[tile.tile_index] = build_distance_map_matrix(map, [tile])

    return dist


# def johnson(map: MapBase) -> MapMatrixInterface[MapMatrixInterface[int]]:
#     """Return distance where distance[u][v] is the min distance from u to v.
#
#     distance[u][v] is the shortest distance from vertex u to v.
#
#     g is a Graph object which can have negative edge weights.
#     """
#
#     dist: MapMatrixInterface[MapMatrixInterface[int]] = MapMatrix(map, None)
#     for tile in map.get_all_tiles():
#         dist[tile] = MapMatrix(map, 1000)
#
#     # add new vertex q
#     g.add_vertex('q')
#     # let q point to all other vertices in g with zero-weight edges
#     for v in g:
#         g.add_edge('q', v.get_key(), 0)
#
#     # compute shortest distance from vertex q to all other vertices
#     bell_dist = bellman_ford(g, g.get_vertex('q'))
#
#     # set weight(u, v) = weight(u, v) + bell_dist(u) - bell_dist(v) for each
#     # edge (u, v)
#     for v in g:
#         for n in v.get_neighbours():
#             w = v.get_weight(n)
#             v.set_weight(n, w + bell_dist[v] - bell_dist[n])
#
#     # remove vertex q
#     # This implementation of the graph stores edge (u, v) in Vertex object u
#     # Since no other vertex points back to q, we do not need to worry about
#     # removing edges pointing to q from other vertices.
#     del g.vertices['q']
#
#     # distance[u][v] will hold smallest distance from vertex u to v
#     distance = {}
#     # run dijkstra's algorithm on each source vertex
#     for v in g:
#         distance[v] = dijkstra(g, v)
#
#     # correct distances
#     for v in g:
#         for w in g:
#             distance[v][w] += bell_dist[w] - bell_dist[v]
#
#     # correct weights in original graph
#     for v in g:
#         for n in v.get_neighbours():
#             w = v.get_weight(n)
#             v.set_weight(n, w + bell_dist[n] - bell_dist[v])
#
#     return distance

#
# def bellman_ford(g, source):
#     """Return distance where distance[v] is min distance from source to v.
#
#     This will return a dictionary distance.
#
#     g is a Graph object which can have negative edge weights.
#     source is a Vertex object in g.
#     """
#     distance = dict.fromkeys(g, float('inf'))
#     distance[source] = 0
#
#     for _ in range(len(g) - 1):
#         for v in g:
#             for n in v.get_neighbours():
#                 distance[n] = min(distance[n], distance[v] + v.get_weight(n))
#
#     return distance


def dijkstra(g, source):
    """Return distance where distance[v] is min distance from source to v.

    This will return a dictionary distance.

    g is a Graph object.
    source is a Vertex object in g.
    """
    unvisited = set(g)
    distance = dict.fromkeys(g, float('inf'))
    distance[source] = 0

    while unvisited:
        # find vertex with minimum distance
        closest = min(unvisited, key=lambda v: distance[v])

        # mark as visited
        unvisited.remove(closest)

        # update distances
        for neighbour in closest.get_neighbours():
            if neighbour in unvisited:
                new_distance = distance[closest] + closest.get_weight(neighbour)
                if distance[neighbour] > new_distance:
                    distance[neighbour] = new_distance

    return distance


def get_player_tiles_near_up_to_army_amount(map: MapBase, fromTiles: typing.List[Tile], armyAmount: int, asPlayer: int = -1, tileAmountCutoff: int = 1) -> typing.List[Tile]:
    if asPlayer == -1:
        asPlayer = map.player_index

    counter = Counter(0)
    foundTiles = []

    def foreachFunc(tile: Tile, dist: int, army: int) -> bool:
        if counter.value >= armyAmount:
            return True

        if tile.player == asPlayer and tile.army > tileAmountCutoff:
            counter.value += tile.army - 1
            foundTiles.append(tile)

        return False

    found = breadth_first_find_queue(
        map,
        fromTiles,
        goalFunc=foreachFunc,
        noNeutralCities=True,
        searchingPlayer=asPlayer
    )

    return foundTiles