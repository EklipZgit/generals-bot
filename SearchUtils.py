"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""
import heapq
import types
from heapq import heappush, heappop

import logbook
import math
import typing
import time
from collections import deque

from heapq_max import heappush_max, heappop_max

# from numba import jit, float32, int64

from Interfaces import MapMatrixInterface, TileSet
from Path import Path
from test.test_float import INF
from base.client.tile import Tile
from base.client.map import MapBase, new_value_grid
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

    if map.teammates:
        if skipTiles:
            skipTiles = skipTiles.copy()
        else:
            skipTiles = set()
        for tId in map.teammates:
            if map.generals[tId] and map.generals[tId].isGeneral and map.generals[tId].player == tId:
                skipTiles.add(map.generals[tId])

    frontier = HeapQueue()
    visited = [[None for _ in range(map.rows)] for _ in range(map.cols)]
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
            frontier.put((startVal, goal, startDist, startArmy, goalInc, None))
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
    baseTurn = map.turn
    qq = frontier.queue
    while qq:
        iter += 1

        (prioVals, current, dist, army, goalInc, fromTile) = frontier.get()
        if visited[current.x][current.y] is not None:
            continue
        if skipTiles and current in skipTiles:
            if not noLog and iter < 100: logbook.info(
                f"PopSkipped skipTile current {current.toString()}, army {army}, goalInc {goalInc}, targetArmy {targetArmy}")
            continue
        if current.isMountain or (
                current.isCity and noNeutralCities and current.player == -1 and current not in goalList) or (
                not current.discovered and current.isNotPathable
        ):
            if not noLog and iter < 100:
                logbook.info(f"PopSkipped Mountain, neutCity or Obstacle current {current.toString()}")
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
                goalInc -= 0.5
                if isInc:
                    nextArmy -= int(goalInc * 2)
            else:
                goalInc += 0.5
                if isInc:
                    nextArmy += int(goalInc * 2)

        notNegativeTile = negativeTiles is None or current not in negativeTiles

        if isTeam:
            if notNegativeTile:
                nextArmy += current.army
        else:
            if notNegativeTile:
                nextArmy -= current.army
            else:
                nextArmy -= 1
        newDist = dist + 1

        visited[current.x][current.y] = (nextArmy, fromTile)

        if nextArmy >= targetArmy and nextArmy > foundArmy and current.player == searchingPlayer and current.army > 1:
            foundGoal = True
            foundDist = newDist
            foundArmy = nextArmy
            endNode = current
            if not noLog and iter < 100:
                logbook.info(
                    f"GOAL popped {current.toString()}, army {nextArmy}, goalInc {goalInc}, targetArmy {targetArmy}, processing")
            break

        if isInc:  #(current.x == 2 and current.y == 7) or (current.x == 2 and current.y == 8) or (current.x == 2 and current.y == 9) or (current.x == 3 and current.y == 9) or (current.x == 4 and current.y == 9) or (current.x == 5 and current.y == 9)
            nextArmy -= int(2 * goalInc)

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
    return abs(goal.x - cur.x) + abs(goal.y - cur.y)


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
    frontier = HeapQueue()
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

    qq = frontier.queue
    while qq:
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
        f"A* KILL SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
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
    cost_so_far = {}
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = startDist
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = 0
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None
    start = time.perf_counter()
    iter = 0
    foundDist = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, current = heapq.heappop(frontier)
        dist = cost_so_far[current]

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current == goal:
            foundDist = dist
            break

        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next == came_from[current]:
                    continue
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCity and next.isNeutral and not allowNeutralCities:
                    continue

                new_cost = dist + 1
                curNextCost = cost_so_far.get(next, None)
                if next not in cost_so_far or new_cost < curNextCost:
                    cost_so_far[next] = new_cost
                    priority = dist + 1 + _shortestPathHeurTile(goal, next)
                    heapq.heappush(frontier, (priority, next))
                    # logbook.info("a* enqueued next")
                    came_from[next] = current

    if not noLog:
        logbook.info(
            f"a_star_find SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal not in came_from:
        return None

    pathObject = Path()
    pathObject.add_next(goal)
    node = goal
    while came_from[node] is not None:
        # logbook.info("Node {},{}".format(node.x, node.y))
        node = came_from[node]
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
            cost_so_far[start] = startDist
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = 0
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None
    start = time.perf_counter()
    iter = 0
    foundDist = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, current = heapq.heappop(frontier)
        dist = cost_so_far[current]

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current == goal:
            foundDist = dist
            break

        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next == came_from[current]:
                    continue
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCity and next.isNeutral and not allowNeutralCities:
                    continue

                new_cost = dist + 1
                curNextCost = cost_so_far.get(next, None)
                if next not in cost_so_far or new_cost < curNextCost:
                    cost_so_far[next] = new_cost
                    priority = dist + 1 + _shortestPathHeurTile(goal, next)
                    heapq.heappush(frontier, (priority, next))
                    # logbook.info("a* enqueued next")
                    came_from[next] = current

    if not noLog:
        logbook.info(
            f"a_star_find_raw SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal not in came_from:
        return None

    tileList = [goal]
    node = goal
    while came_from[node] is not None:
        node = came_from[node]
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
            cost_so_far[start] = startDist
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = 0
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None
    start = time.perf_counter()
    iter = 0
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, current = heapq.heappop(frontier)
        dist = cost_so_far[current]

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current == goal:
            break

        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next == came_from[current]:
                    continue
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCity and next.isNeutral and not allowNeutralCities:
                    continue

                new_cost = dist + 1
                if next in tryAvoid:
                    new_cost += 0.05
                curNextCost = cost_so_far.get(next, None)
                if next not in cost_so_far or new_cost < curNextCost:
                    cost_so_far[next] = new_cost
                    extraCost = 0
                    if next in tryAvoid:
                        extraCost = 0.3
                    priority = dist + 1 + _shortestPathHeurTile(goal, next) + extraCost
                    heapq.heappush(frontier, (priority, next))
                    # logbook.info("a* enqueued next")
                    came_from[next] = current

    if not noLog:
        logbook.info(
            f"a_star_find_raw SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal not in came_from:
        return None

    tileList = [goal]
    node = goal
    while came_from[node] is not None:
        node = came_from[node]
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
    cost_so_far: MapMatrixInterface[int] = MapMatrix(map, 1000)
    if isinstance(startTiles, dict):
        for start in startTiles.keys():
            startDist = startTiles[start]
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = startDist
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = 0
            heapq.heappush(frontier, (cost_so_far[start], start))
            came_from[start] = None

    start = time.perf_counter()
    iter = 0
    foundDist = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, current = heapq.heappop(frontier)
        dist = cost_so_far[current]

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current == goal:
            foundDist = dist
            break

        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next == came_from[current]:
                    continue
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCity and next.isNeutral and not allowNeutralCities:
                    continue

                new_cost = dist + 1
                curNextCost = cost_so_far[next]
                if next not in cost_so_far or new_cost < curNextCost:
                    cost_so_far[next] = new_cost
                    priority = dist + 1 + _shortestPathHeurTile(goal, next)
                    heapq.heappush(frontier, (priority, next))
                    # logbook.info("a* enqueued next")
                    came_from[next] = current

    if not noLog:
        logbook.info(
            f"A* FIND SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    if goal not in came_from:
        return None

    pathObject = Path()
    pathObject.add_next(goal)
    node = goal
    dist = foundDist
    while came_from[node] is not None:
        # logbook.info("Node {},{}".format(node.x, node.y))
        node = came_from[node]
        dist -= 1
        pathObject.add_start(node)

    if not noLog:
        logbook.info(f"A* FOUND KILLPATH OF LENGTH {pathObject.length} VALUE {pathObject.value}\n{pathObject.toString()}")
    # pathObject.calculate_value(startTiles[0].player, teams=map._teams)
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
            cost_so_far[start] = startDist
            heapq.heappush(frontier, (cost_so_far[start], start))
    else:
        for start in startTiles:
            if not noLog:
                logbook.info(f"a* enqueued start tile {start.toString()}")
            # if (start.player == map.player_index and start.isGeneral and map.turn > GENERAL_HALF_TURN):
            #    startArmy = start.army / 2
            cost_so_far[start] = 0
            heapq.heappush(frontier, (cost_so_far[start], start))
    start = time.perf_counter()
    iter = 0
    foundDist = -1
    depthEvaluated = 0

    while frontier:
        iter += 1
        prio, current = heapq.heappop(frontier)
        dist = cost_so_far[current]

        if dist > depthEvaluated:
            depthEvaluated = dist
        if current == goal:
            foundDist = dist
            break

        if dist < maxDepth:
            for next in current.movable:  # new spots to try
                if next.isMountain or ((not next.discovered) and next.isNotPathable):
                    # logbook.info("a* mountain")
                    continue
                if next.isCity and next.isNeutral and not allowNeutralCities:
                    continue

                new_cost = dist + 1
                curNextCost = cost_so_far.get(next, None)
                if next not in cost_so_far or new_cost < curNextCost:
                    cost_so_far[next] = new_cost
                    priority = dist + 1 + _shortestPathHeurTile(goal, next)
                    heapq.heappush(frontier, (priority, next))
                    # logbook.info("a* enqueued next")

    if not noLog:
        logbook.info(
            f"A* FIND SEARCH ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")

    return foundDist


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
    frontier = HeapQueue()
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
    qq = frontier.queue
    while qq:
        iter += 1

        (prioVals, dist, current, parent) = frontier.get()
        if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
            visited[current.x][current.y][dist] = (prioVals, parent)
        # TODO no globalVisitedSet
        if current in globalVisitedSet or (skipTiles and current in skipTiles):
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
                if next == parent:
                    continue
                if (next.isMountain
                        or (noNeutralCities and next.player == -1 and next.isCity)
                        or (not next.discovered and next.isNotPathable)):
                    continue
                newDist = dist + 1
                nextVal = priorityFunc(next, prioVals)
                if nextVal is not None:
                    frontier.put((nextVal, newDist, next, current))

    if not noLog:
        logbook.info(
            f"BFS-DYNAMIC ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
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
                    nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
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
            if current in globalVisitedSet:
                continue
            globalVisitedSet.add(current)
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
            if current in globalVisitedSet:
                continue
            globalVisitedSet.add(current)
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
        if iter & 64 == 0:
            elapsed = time.perf_counter() - start
            if elapsed > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
                logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE-PER-DIST BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
                break

        (prioVals, dist, current, parent, nodeList, startTile) = frontier.get()
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):
        if useGlobalVisitedSet:
            if current in globalVisitedSet:
                continue
            globalVisitedSet.add(current)
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
                    nextTile.player != -1 or (preferNeutral and nextTile.isCity == False)):
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
                if tile.player != -1 and tile.isCity or tile.isGeneral:
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
                    or (noNeutralCities and next.player == -1 and next.isCity)
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
                pathObject.value += priorityMatrix[tile]

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
                if tile.player != -1 and tile.isCity or tile.isGeneral:
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
                    or (noNeutralCities and next.player == -1 and next.isCity)
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

    frontier: typing.List[typing.Tuple[typing.Any, int, int, Tile, Tile | None]] = []
    """prioObj, distance (incl startDist), curTurns (starting at 0 per search), nextTile, fromTile, maxDict"""

    fromTileLookup: MapMatrixInterface[typing.Tuple[typing.Any, Tile]] = MapMatrix(map, None)
    # fromTileLookup: typing.Dict[int, typing.Tuple[typing.Any, Tile]] = {}

    maxValuesDict = {}

    # maxValuesTMP: typing.Dict[Tile, typing.Dict[int, typing.Any]] = {}
    # maxPriosTMP: typing.Dict[Tile, typing.Dict[int, typing.Any]] = {}
    # endNodesTMP: typing.Dict[Tile, typing.Dict[int, Tile]] = {}

    if isinstance(startTiles, dict):
        for tile, (startPriorityObject, distance) in startTiles.items():
            startVal = startPriorityObject
            startDict = {}
            maxValuesDict[tile] = startDict
            heapq.heappush(frontier, (startVal, distance, 0, tile, None, startDict))
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
        if iter & 64 == 0:
            elapsed = time.perf_counter() - start
            if elapsed > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING or iter > maxIterations:
                logbook.info(f"BFS-DYNAMIC-MAX-PER-TILE-PER-DIST BREAKING EARLY @ {time.perf_counter() - start:.3f} iter {iter}")
                break

        (prioVals, dist, curTurns, current, parent, maxDict) = heapq.heappop(frontier)
        # if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
        # if current in globalVisitedSet or (skipTiles != None and current in skipTiles):

        fromVal = fromTileLookup.raw[current.tile_index]
        # fromVal = fromTileLookup.get(current.tile_index, None)
        if fromVal is not None:
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
            if (next.isMountain
                    or (noNeutralCities and next.player == -1 and next.isCity)
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
        preferNeutral=False):
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
    frontier = HeapQueue()
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
    qq = frontier.queue
    while qq:
        iter += 1
        if iter % 1000 == 0 and time.perf_counter() - start > maxTime and not BYPASS_TIMEOUTS_FOR_DEBUGGING:
            logbook.info("BI-DIR BREAKING")
            break

        (prioVals, dist, current, parent) = frontier.get()
        if dist not in visited[current.x][current.y] or visited[current.x][current.y][dist][0] > prioVals:
            visited[current.x][current.y][dist] = (prioVals, parent)
        # TODO no globalVisitedSet
        if current in globalVisitedSet or (skipTiles and current in skipTiles):
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
                if next == parent:
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
        f"BI-DIR BFS-FIND ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
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
    pathObject.calculate_value(searchingPlayer, teams=map.team_ids_by_player_index, incrementBackwards=incrementBackward)
    logbook.info(
        f"BI-DIR DYNAMIC BFS FOUND PATH LENGTH {pathObject.length} VALUE {pathObject.value}\n   {pathObject.toString()}")
    return pathObject


def breadth_first_find_queue(
        map,
        startTiles,
        goalFunc: typing.Callable[[Tile, int, int], bool],
        maxTime=0.1,
        maxDepth=200,
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
    nodeValues: MapMatrixInterface[typing.Tuple[int, Tile | None]] = MapMatrix(map)  # (army, fromTile)
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
    iter = 0
    start = time.perf_counter()
    foundGoal = False
    foundArmy = -100000
    foundDist = 1000
    endNode = None
    depthEvaluated = 0
    while frontier:
        iter += 1
        (current, dist, army, goalInc) = frontier.pop()
        if current in visited or (skipTiles and current in skipTiles):
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
            for nextTile in nextSearch:  # new spots to try
                if (
                    (
                        not bypassDefaultSkipLogic
                        and (
                            nextTile.isMountain
                            or (noNeutralCities and nextTile.isCity and nextTile.player == -1)
                            or (not nextTile.discovered and nextTile.isNotPathable)
                        )
                    )
                    or nextTile in visited
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
                newDist = dist + 1
                curTuple = nodeValues.raw[nextTile.tile_index]
                if curTuple is None or curTuple[0] < nextArmy:
                    nodeValues.raw[nextTile.tile_index] = (nextArmy, current)
                frontier.appendleft((nextTile, newDist, nextArmy, goalInc))

    if not noLog:
        logbook.info(
            f"BFS-FIND-QUEUE ITERATIONS {iter}, DURATION: {time.perf_counter() - start:.4f}, DEPTH: {depthEvaluated}")
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
        (army, node) = nodeValues.raw[node.tile_index]
        dist -= 1
    (startArmy, startNode) = nodes[0]
    pathObject = Path(foundArmy)
    pathObject.add_next(startNode)
    dist = foundDist
    for i, armyNode in enumerate(nodes[-2::-1]):
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
    goalFunc is goalFunc(current, dist)
    prioFunc is prioFunc(tile) - bigger is better, tuples supported, True comes before False etc.
    bypassDefaultSkipLogic allows you to search through undiscovered mountains etc.
    """

    frontier = deque()
    visited: typing.Set[Tile] = set()
    if isinstance(startTiles, dict):
        for tile in startTiles.keys():
            startDist = startTiles[tile]
            if tile.isMountain and not bypassDefaultSkipLogic:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            frontier.appendleft((tile, startDist))
    else:
        for tile in startTiles:
            if tile.isMountain and not bypassDefaultSkipLogic:
                # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
                continue
            frontier.appendleft((tile, 0))
    iter = 0
    start = time.perf_counter()
    foundDist = 1000
    while frontier:
        iter += 1
        (current, dist) = frontier.pop()
        if current in visited or (skipTiles and current in skipTiles):
            continue
        visited.add(current)
        if goalFunc(current, dist):
            foundDist = dist
            break
        for next in current.movable:  # new spots to try
            if (
                not bypassDefaultSkipLogic
                and (
                    next.isMountain
                    or (noNeutralCities and next.isCity and next.player == -1)
                    or (not next.discovered and next.isNotPathable)
                )
            ):
                continue

            newDist = dist + 1
            frontier.appendleft((next, newDist))

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
    globalVisited = MapMatrixSet(map)
    if skipTiles:
        for tile in skipTiles:
            if not noLog:
                logbook.info(f"    skipTiles contained {tile}")
            globalVisited.raw[tile.tile_index] = True

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
        if globalVisited.raw[current.tile_index]:
            continue
        if dist > maxDepth:
            break
        globalVisited.raw[current.tile_index] = True
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)) and dist > 0:
            continue

        if foreachFunc(current):
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))
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
    globalVisited = MapMatrixSet(map)
    if skipTiles:
        for tile in skipTiles:
            if not noLog:
                logbook.info(f"    skipTiles contained {tile}")
            globalVisited.raw[tile.tile_index] = True

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
        if globalVisited.raw[current.tile_index]:
            continue
        if dist > maxDepth:
            break
        globalVisited.raw[current.tile_index] = True
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
    globalVisited = MapMatrixSet(map)
    if skipTiles:
        for tile in skipTiles:
            if not noLog:
                logbook.info(f"    skipTiles contained {tile}")
            globalVisited.raw[tile.tile_index] = True

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
        if globalVisited.raw[current.tile_index]:
            continue
        if dist > maxDepth:
            break
        globalVisited.raw[current.tile_index] = True
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
    globalVisited = MapMatrixSet(map)
    if skipTiles:
        for tile in skipTiles:
            globalVisited.raw[tile.tile_index] = True

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
        if globalVisited.raw[current.tile_index]:
            continue
        if dist > maxDepth:
            break
        globalVisited.raw[current.tile_index] = True
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)):
            continue

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))
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

    # TODO benchmark this...? TODO if we ALWAYS mapmatrix then we can direct-access grid for better perf.
    if maxDepth < map.rows // 3:
        globalVisited = set()
    else:
        globalVisited = MapMatrixSet(map)

    for tile in startTiles:
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()
        if current.isNotPathable:
            continue
        if current in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current)

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))


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

    # TODO benchmark this...? TODO if we ALWAYS mapmatrix then we can direct-access grid for better perf.
    if maxDepth < map.rows // 3:
        globalVisited = set()
    else:
        globalVisited = MapMatrixSet(map)

    for dist, tile in startTiles:
        frontier.appendleft((tile, dist, 0))

    while frontier:
        (current, dist, depth) = frontier.pop()
        if current.isNotPathable:
            continue
        if current in globalVisited:
            continue
        if depth > maxDepth:
            break
        globalVisited.add(current)

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

    # TODO benchmark this...? TODO if we ALWAYS mapmatrix then we can direct-access grid for better perf.
    if maxDepth < map.rows // 3:
        globalVisited = set()
    else:
        globalVisited = MapMatrixSet(map)

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()
        if current.isObstacle:
            continue
        if current in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current)

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))


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

    # TODO benchmark this...? TODO if we ALWAYS mapmatrix then we can direct-access grid for better perf.
    if maxDepth < map.rows // 3:
        globalVisited = set()
    else:
        globalVisited = MapMatrixSet(map)

    for tile in startTiles:
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()
        if current in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current)

        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))


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

    # TODO benchmark this...? TODO if we ALWAYS mapmatrix then we can direct-access grid for better perf.
    if maxDepth < map.rows // 3:
        globalVisited = set()
    else:
        globalVisited = MapMatrixSet(map)

    for tile in startTiles:
        if tile.isMountain:
            # logbook.info("BFS DEST SKIPPING MOUNTAIN {},{}".format(goal.x, goal.y))
            continue
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()
        if current.isObstacle:
            continue
        if current in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current)

        if foreachFunc(current):
            continue

        # intentionally placed after the foreach func, skipped tiles are still foreached, they just aren't traversed
        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))


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
            globalVisited[tile.x][tile.y] = 1000

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
        prevDist = globalVisited[current.x][current.y]
        if prevDist:
            if prevDist < dist:
                revisitFunc(current, dist)
            continue
        if dist > maxDepth:
            break
        globalVisited[current.x][current.y] = True
        if not bypassDefaultSkip and (current.isMountain or (not current.discovered and current.isNotPathable)):
            continue
        if foreachFunc(current, dist):
            continue

        newDist = dist + 1
        for next in current.movable:  # new spots to try
            frontier.appendleft((next, newDist))
    if not noLog:
        logbook.info(
            f"Completed breadth_first_foreach_dist_revisit_callback. startTiles[0] {startTiles[0].x},{startTiles[0].y}: ITERATIONS {iter}, DURATION {time.perf_counter() - start:.3f}, DEPTH {dist}")


def build_distance_map_incl_mountains(map, startTiles, skipTiles=None) -> typing.List[typing.List[int]]:
    """
    Builds a distance map to everything including mountains (but does not path through mountains / neutral cities).

    @param map:
    @param startTiles:
    @param skipTiles:
    @return:
    """
    distanceMap = new_value_grid(map, 1000)

    if skipTiles is not None and not isinstance(skipTiles, set):
        newSkipTiles = {t for t in skipTiles}
        skipTiles = newSkipTiles

    if skipTiles is None:
        def bfs_dist_mapper(tile, dist) -> bool:
            if dist < distanceMap[tile.x][tile.y]:
                distanceMap[tile.x][tile.y] = dist

            return tile.isObstacle
    else:
        def bfs_dist_mapper(tile, dist) -> bool:
            if tile in skipTiles:
                return True

            if dist < distanceMap[tile.x][tile.y]:
                distanceMap[tile.x][tile.y] = dist

            return tile.isObstacle

    breadth_first_foreach_dist_fast_no_default_skip(map, startTiles, 1000, bfs_dist_mapper)
    return distanceMap


def build_distance_map(map: MapBase, startTiles: typing.List[Tile], skipTiles: typing.Set[Tile] | typing.Iterable[Tile] | None = None, maxDepth: int = 1000) -> typing.List[typing.List[int]]:
    distanceMap = new_value_grid(map, 1000)

    if skipTiles is not None and not isinstance(skipTiles, set):
        newSkipTiles = {t for t in skipTiles}
        skipTiles = newSkipTiles

    if not skipTiles:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            distanceMap[tile.x][tile.y] = dist

            return tile.isNeutral and tile.isCity
    else:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if tile in skipTiles:
                return True

            distanceMap[tile.x][tile.y] = dist

            return tile.isNeutral and tile.isCity

    breadth_first_foreach_dist_fast_incl_neut_cities(
        map,
        startTiles,
        maxDepth,
        bfs_dist_mapper)

    return distanceMap


def build_distance_map_matrix(map, startTiles, skipTiles=None, maxDepth: int = 1000) -> MapMatrixInterface[int]:
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

            return tile.isNeutral and tile.isCity
    else:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if tile in skipTiles:
                return True

            distanceMap.raw[tile.tile_index] = dist

            return tile.isNeutral and tile.isCity

    breadth_first_foreach_dist_fast_incl_neut_cities(
        map,
        startTiles,
        maxDepth,
        bfs_dist_mapper)

    return distanceMap


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

            return tile.isNeutral and tile.isCity
    else:
        def bfs_dist_mapper(tile: Tile, dist: int) -> bool:
            if tile in skipTiles:
                return True

            distanceMap.raw[tile.tile_index] = dist

            return tile.isNeutral and tile.isCity

    frontier: typing.Deque[typing.Tuple[Tile, int, int]] = deque()

    # TODO benchmark this...? TODO if we ALWAYS mapmatrix then we can direct-access grid for better perf.
    if maxDepth < map.rows // 3:
        globalVisited = set()
    else:
        globalVisited = MapMatrixSet(map)

    for dist, tile in startTiles:
        frontier.appendleft((tile, dist, 0))

    while frontier:
        (current, dist, depth) = frontier.pop()
        if current.isNotPathable:
            continue
        if current in globalVisited:
            continue
        if depth > maxDepth:
            break
        globalVisited.add(current)

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
    globalVisited = MapMatrixSet(map)

    for tile in startTiles:
        frontier.appendleft((tile, 0))

    while frontier:
        (current, dist) = frontier.pop()
        if current in globalVisited:
            continue
        if dist > maxDepth:
            break
        globalVisited.add(current)
        if current.isMountain or (not current.discovered and current.isNotPathable):
            continue

        distanceMap[current] = dist
        if current.isNeutral and current.isCity:
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
                if v.isCity and v.isNeutral and not allowNeutralCities:
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
                if v.isCity and v.isNeutral and not allowNeutralCities:
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
    g_s = dict()
    g_t = dict()

    g_s[start] = 0
    g_t[goal] = 0

    cameFrom1 = dict()
    cameFrom2 = dict()

    def euclidean_distance(v: Tile, goal: Tile) -> float:
        return ((v.x - goal.x)**2 + (v.y - goal.y)**2) ** 0.5
        # return abs(v.x - goal.x) + abs(v.y - goal.y)

    def h1(v: Tile) -> float:  # heuristic for forward search (from start to goal)
        return euclidean_distance(v, goal)

    def h2(v: Tile) -> float:  # heuristic for backward search (from goal to start)
        return euclidean_distance(v, start)

    cameFrom1[start] = False
    cameFrom2[goal] = False

    heapq.heappush(pq_s, (h1(start), start))
    heapq.heappush(pq_t, (h2(goal), goal))

    i = 0

    mu = 10 ** 301  # 10**301 plays the role of infinity
    connection = None
    weight = 1

    while pq_s and pq_t:
        i += 1
        if i & 1 == 1:  # alternate between forward and backward A*
            curTile: Tile
            fu, curTile = heapq.heappop(pq_s)
            # closed_s.add(curTile)
            for v in curTile.movable:
                if v.isMountain:
                    continue
                if v.isCity and v.isNeutral and not allowNeutralCities:
                    continue
                # weight = graph[curTile][v]['weight']
                curTileCost = g_s[curTile] + weight
                if v in g_s:
                    if curTileCost < g_s[v]:
                        g_s[v] = curTileCost
                        cameFrom1[v] = curTile

                        # closed_s.discard(v)
                        # if v in pq_s:
                        #     pq_s.update((g_s[v]+h1(v), v))
                        # else:
                        #     pq_s.append((g_s[v]+h1(v), v))
                else:
                    g_s[v] = curTileCost
                    cameFrom1[v] = curTile
                    heapq.heappush(pq_s, (curTileCost+h1(v), v))
        else:
            fu, curTile = heapq.heappop(pq_t)
            # closed_t.add(curTile)
            for v in curTile.movable:
                if v.isMountain:
                    continue
                if v.isCity and v.isNeutral and not allowNeutralCities:
                    continue
                # weight = graph[curTile][v]['weight']

                curTileCost = g_t[curTile] + weight
                if v in g_t:
                    if curTileCost < g_t[v]:
                        g_t[v] = curTileCost
                        cameFrom2[v] = curTile

                        # closed_t.discard(v)
                        # if v in pq_t:
                        #     pq_t.update((g_t[v]+h2(v), v))
                        # else:
                        #     pq_t.append((g_t[v]+h2(v), v))
                else:
                    g_t[v] = curTileCost
                    cameFrom2[v] = curTile
                    heapq.heappush(pq_t, (curTileCost+h2(v), v))

        if curTile in cameFrom1 and curTile in cameFrom2:
            curMu = g_s[curTile] + g_t[curTile]
            # logbook.info(f'mu {curTile} g_s {g_s[curTile]} g_t {g_t[curTile]} = {curMu} vs best {mu}')
            if curMu < mu:
                mu = curMu
                connection = curTile
                # done = True
                if len(pq_t) and len(pq_s):
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
    for tile in map.get_all_tiles():
        dist[tile] = build_distance_map_matrix(map, [tile])

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