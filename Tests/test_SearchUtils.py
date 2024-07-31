import inspect
import itertools
import random
import time
import typing
import unittest

import logbook

import SearchUtils
from Models import Move
from DistanceMapperImpl import DistanceMapperImpl
from Path import Path
from SearchUtils import dest_breadth_first_target
from Sim.GameSimulator import GameSimulatorHost, GameSimulator
from Tests.TestBase import TestBase
from ViewInfo import PathColorer
from base.client.tile import Tile, MapBase
from base.viewer import GeneralsViewer
from DangerAnalyzer import DangerAnalyzer


class SearchUtilsTests(TestBase):
    def test_dest_breadth_first_target__calculates_short_path_values_correctly__normal_tile(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(3)]
                target = board[0][0]
                target.army = 5

                threatTile = board[2][0]
                threatTile.player = 1
                threatTile.army = 9

                map = self.get_test_map(board, turn=turn)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[target],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)


    def test_dest_breadth_first_target__calculates_longer_path_values_correctly__targeting_normal_tile(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
                target = board[0][0]
                target.army = 5

                threatTile = board[9][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. So to kill tile @ 5 it takes 18 + 5 = 23
                threatTile.army = 23

                map = self.get_test_map(board, turn=turn)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[target],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_short_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(3)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[2][0]
                threatTile.player = 1
                threatTile.army = 9
                if turn == 1:
                    threatTile.army += 1

                map = self.get_test_map(board, turn=turn)
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_longer_odd_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(10)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[9][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 27

                map = self.get_test_map(board, turn=turn)
                armyAmount = 0.5
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=11,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEquals(1, path.value)

    def test_dest_breadth_first_target__calculates_longer_even_path_values_correctly__targeting_general(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(11)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[10][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 29
                if turn == 1:
                    # on this odd turn, the general increments before we get there so we actually wouldn't find a path
                    threatTile.army += 1

                map = self.get_test_map(board, turn=turn)
                sim = GameSimulator(map)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=12,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                sim.set_next_move(1, Move(map.GetTile(0, 10), map.GetTile(0, 9)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 9), map.GetTile(0, 8)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 8), map.GetTile(0, 7)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 7), map.GetTile(0, 6)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 6), map.GetTile(0, 5)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 5), map.GetTile(0, 4)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 4), map.GetTile(0, 3)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 3), map.GetTile(0, 2)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 2), map.GetTile(0, 1)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 1), map.GetTile(0, 0)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                self.assertEqual(1, sim.sim_map.GetTile(0, 0).player)

                # self.render_map(map)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEqual(1, path.value)

    def test_dest_breadth_first_target__does_not_find_path_when_cannot_kill(self):
        # test both odd and even turns. Pairs with the above test, which tests EXACTLY one more army than this test, which accurate kills in all scenarios.
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(11)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[10][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 28
                if turn == 1:
                    # on this odd turn, the general increments before we get there so we actually wouldn't find a path
                    threatTile.army += 1

                map = self.get_test_map(board, turn=turn)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=12,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)
                self.assertIsNone(path)

    def test_dest_breadth_first_target__calculates_longer_even_path_values_correctly__targeting_general_even_path_length(self):
        # test both odd and even turns
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(12)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[11][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 32
                # not needed on even path lengths
                # if turn == 1:
                #     # on this odd turn, the general increments before we get there so we actually wouldn't find a path
                #     threatTile.army += 1

                map = self.get_test_map(board, turn=turn)
                sim = GameSimulator(map)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=13,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                sim.set_next_move(1, Move(map.GetTile(0, 11), map.GetTile(0, 10)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 10), map.GetTile(0, 9)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 9), map.GetTile(0, 8)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 8), map.GetTile(0, 7)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 7), map.GetTile(0, 6)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 6), map.GetTile(0, 5)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 5), map.GetTile(0, 4)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 4), map.GetTile(0, 3)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 3), map.GetTile(0, 2)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 2), map.GetTile(0, 1)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 1), map.GetTile(0, 0)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                self.assertEqual(1, sim.sim_map.GetTile(0, 0).player)

                # self.render_map(map)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNotNone(path)
                self.assertEqual(1, path.value)

    def test_dest_breadth_first_target__does_not_find_path_when_cannot_kill__targeting_general_even_path_length(self):
        # test both odd and even turns. Pairs with the above test, which tests EXACTLY one more army than this test, which accurate kills in all scenarios.
        turnsToTest = [0, 1, 2]
        for turn in turnsToTest:
            with self.subTest(turn=turn):
                board = [[Tile(x, y, tile=0, army=1, player=0) for x in range(1)] for y in range(12)]
                general = board[0][0]
                general.isGeneral = True
                general.army = 5

                threatTile = board[11][0]
                threatTile.player = 1
                # 2 army lost per move, 9 moves. During that time general increments 4 times so 4 more army. So to kill general @ 5 it takes 18 + 5 + 4 = 27
                threatTile.army = 31
                # not needed on even path lengths
                # if turn == 1:
                #     # on this odd turn, the general increments before we get there so we actually wouldn't find a path
                #     threatTile.army += 1

                map = self.get_test_map(board, turn=turn)
                sim = GameSimulator(map)
                armyAmount = 1
                path = dest_breadth_first_target(
                    map=map,
                    goalList=[general],
                    targetArmy=armyAmount,
                    maxTime=0.05,
                    maxDepth=13,
                    negativeTiles=None,
                    searchingPlayer=1,
                    dontEvacCities=False,
                    dupeThreshold=3,
                    noLog=False)

                sim.set_next_move(1, Move(map.GetTile(0, 11), map.GetTile(0, 10)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 10), map.GetTile(0, 9)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 9), map.GetTile(0, 8)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 8), map.GetTile(0, 7)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 7), map.GetTile(0, 6)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 6), map.GetTile(0, 5)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 5), map.GetTile(0, 4)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 4), map.GetTile(0, 3)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 3), map.GetTile(0, 2)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 2), map.GetTile(0, 1)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                sim.set_next_move(1, Move(map.GetTile(0, 1), map.GetTile(0, 0)))
                sim.execute_turn(dont_require_all_players_to_move=True)
                self.assertEqual(0, sim.sim_map.GetTile(0, 0).player)
                expectedArmy = 0
                if turn == 1:
                    # the general survives at 0, then gets an increment, so has 1 army
                    expectedArmy = 1
                self.assertEqual(expectedArmy, sim.sim_map.GetTile(0, 0).army)

                # self.render_map(map)

                # val = path.calculate_value(forPlayer=1)
                # self.assertEquals(1, val)
                self.assertIsNone(path)

    def test_bfs_find_queue_returns_path(self):
        mapFile = 'GameContinuationEntries/should_complete_danger_tile_kill___Bgk8TIUR2---0--108.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)
        startTile = map.GetTile(2, 12)
        midTile = map.GetTile(2, 15)

        def pathToGenFunc(current: Tile, curArmyAmt: int, distance: int) -> bool:
            if current == general:
                return True
            return False

        path = SearchUtils.breadth_first_find_queue(map, [startTile], pathToGenFunc, noNeutralCities = True, searchingPlayer = startTile.player)

        self.assertIsNotNone(path)
        self.assertEqual(4, path.length)

    def test_bfs_find_queue_returns_path_despite_army_blocking(self):
        mapFile = 'GameContinuationEntries/should_complete_danger_tile_kill___Bgk8TIUR2---0--108.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)
        startTile = map.GetTile(2, 12)
        midTile = map.GetTile(2, 14)
        midTile.army = 14

        def pathToGenFunc(current: Tile, curArmyAmt: int, distance: int) -> bool:
            if current == general:
                return True
            return False

        path = SearchUtils.breadth_first_find_queue(map, [startTile], pathToGenFunc, noNeutralCities = True, searchingPlayer = startTile.player)

        self.assertIsNotNone(path)
        self.assertEqual(4, path.length)

    def test_bfs_dynamic_max__and__bfs_dynamic_max_global_visited__return_same(self):
        # .889 vs .729
        MapBase.DO_NOT_RANDOMIZE = True
        mapFile = 'GameContinuationEntries/should_complete_danger_tile_kill___Bgk8TIUR2---0--108.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)

        def valFunc(tile, prio):
            dist, negVal = prio
            if dist == 0:
                return None

            return (0 - negVal) / dist

        def prioFunc(tile, lastPrio):
            dist, negVal = lastPrio
            if tile.player == general.player:
                negVal -= tile.army
            else:
                negVal += tile.army

            return dist + 1, negVal

        startTiles: typing.Dict[Tile, typing.Tuple[object, int]] = {
            enemyGeneral: ((0, 0), 0)
        }

        start = time.perf_counter()
        oldPath: Path = None
        for i in range(10):
            oldPath = SearchUtils.breadth_first_dynamic_max(map, startTiles, valFunc, priorityFunc=prioFunc, useGlobalVisitedSet=True, maxTurns=10000, maxDepth=1000, noNeutralCities=True, forceOld=True)
        oldTook = time.perf_counter() - start

        start = time.perf_counter()
        newPath: Path = None
        for i in range(10):
            newPath = SearchUtils.breadth_first_dynamic_max_global_visited(map, startTiles, valFunc, priorityFunc=prioFunc, maxTurns=10000, maxDepth=1000, noNeutralCities=True)
        newTook = time.perf_counter() - start

        start = time.perf_counter()
        oldPath: Path = None
        for i in range(10):
            oldPath = SearchUtils.breadth_first_dynamic_max(map, startTiles, valFunc, priorityFunc=prioFunc, useGlobalVisitedSet=True, maxTurns=10000, maxDepth=1000, noNeutralCities=True, forceOld=True)
        oldTook = time.perf_counter() - start

        oldNode = oldPath.start
        newNode = newPath.start
        while oldNode and newNode:
            self.assertEqual(oldNode.tile, newNode.tile)
            oldNode = oldNode.next
            newNode = newNode.next

        self.assertIsNone(oldNode)
        self.assertIsNone(newNode)

        self.assertEqual(oldPath.length, newPath.length)
        self.assertEqual(oldPath.value, newPath.value)
        self.assertEqual(oldPath.econValue, newPath.econValue)

        self.assertLess(newTook, oldTook, f'new algo should be faster than the one that duplicates all the fucking tileLists wtf yo')
        self.begin_capturing_logging()
        logbook.info(f'old took {oldTook:.5f}, new took {newTook:.5f}')

    def test_bfs_dynamic_max_per_tile__and__bfs_dynamic_max_per_tile_global_visited__return_same(self):
        # 0.818 vs new 0.675
        MapBase.DO_NOT_RANDOMIZE = True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)

        def valFunc(tile, prio):
            dist, negVal, desiredArmy = prio
            if dist == 0 or negVal >= 0:
                return None

            return (0 - negVal) / dist

        def prioFunc(tile, lastPrio):
            dist, negVal, desiredArmy = lastPrio
            if negVal + desiredArmy < 0:
                return None

            if tile.player == general.player:
                negVal -= tile.army
            else:
                negVal += tile.army

            return dist + 1, negVal, desiredArmy

        startTiles: typing.Dict[Tile, typing.Tuple[object, int]] = {
            enemyGeneral: ((0, 0, 1000), 0),
            map.GetTile(0, 1): ((7, 0, 1), 0),
            map.GetTile(12, 12): ((7, 0, 1), 0),
        }

        start = time.perf_counter()
        newPaths: typing.Dict[Tile, Path] = None
        for i in range(50):
            newPaths = SearchUtils.breadth_first_dynamic_max_per_tile_global_visited(map, startTiles, valFunc, priorityFunc=prioFunc, maxTurns=10000, maxDepth=1000, noNeutralCities=True)
        newTook = time.perf_counter() - start

        start = time.perf_counter()
        oldPaths: typing.Dict[Tile, Path] = None
        for i in range(50):
            oldPaths = SearchUtils.breadth_first_dynamic_max_per_tile(map, startTiles, valFunc, priorityFunc=prioFunc, useGlobalVisitedSet=True, maxTurns=10000, maxDepth=1000, noNeutralCities=True, forceOld=True)
        oldTook = time.perf_counter() - start

        start = time.perf_counter()
        newPaths: typing.Dict[Tile, Path] = None
        for i in range(50):
            newPaths = SearchUtils.breadth_first_dynamic_max_per_tile_global_visited(map, startTiles, valFunc, priorityFunc=prioFunc, maxTurns=10000, maxDepth=1000, noNeutralCities=True)
        newTook = time.perf_counter() - start

        for tile in startTiles.keys():
            newPath = newPaths[tile]
            oldPath = oldPaths[tile]
            newNode = newPath.start
            oldNode = oldPath.start
            while oldNode and newNode:
                self.assertEqual(oldNode.tile, newNode.tile)
                oldNode = oldNode.next
                newNode = newNode.next

            self.assertIsNone(oldNode)
            self.assertIsNone(newNode)

            self.assertEqual(oldPath.length, newPath.length)
            self.assertEqual(oldPath.value, newPath.value)
            self.assertEqual(oldPath.econValue, newPath.econValue)

        self.assertLess(newTook, oldTook, f'new algo should be faster than the one that duplicates all the fucking tileLists wtf yo')
        self.begin_capturing_logging()
        logbook.info(f'old took {oldTook:.5f}, new took {newTook:.5f}')
        paths = [l for l in oldPaths.values()]
        paths.extend(newPaths.values())
        # self.render_paths(map, paths, 'paths are cool...?')

    def test_bfs_dynamic_max_per_tile_per_dist__and__bfs_dynamic_max_per_tile_per_dist_global_visited__return_same(self):
        # 0.080 vs 0.045
        MapBase.DO_NOT_RANDOMIZE = True
        mapFile = 'GameContinuationEntries/should_recognize_gather_into_top_path_is_best___wQWfDjiGX---0--250.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 108, fill_out_tiles=True)

        def valFunc(tile, prio):
            dist, negVal, desiredArmy = prio
            if dist == 0 or negVal >= 0:
                return None

            return 0 - negVal

        def prioFunc(tile, lastPrio):
            dist, negVal, desiredArmy = lastPrio
            if negVal + desiredArmy < 0:
                return None

            if tile.player == general.player:
                negVal -= tile.army
            else:
                negVal += tile.army

            return dist + 1, negVal, desiredArmy

        startTiles: typing.Dict[Tile, typing.Tuple[object, int]] = {
            enemyGeneral: ((0, 0, 1000), 0),
            map.GetTile(0, 1): ((6, 0, 1), 0),
            map.GetTile(12, 12): ((8, 0, 1), 0),
        }

        start = time.perf_counter()
        newPaths: typing.Dict[Tile, typing.List[Path]] = None
        for i in range(40):
            newPaths = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance_global_visited(map, startTiles, valFunc, priorityFunc=prioFunc, maxTurns=10000, maxDepth=1000, noNeutralCities=True, noLog=True)
        newTook = time.perf_counter() - start

        start = time.perf_counter()
        oldPaths: typing.Dict[Tile, typing.List[Path]] = None
        for i in range(40):
            oldPaths = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(map, startTiles, valFunc, priorityFunc=prioFunc, useGlobalVisitedSet=True, maxTurns=10000, maxDepth=1000, noNeutralCities=True, forceOld=True)
        oldTook = time.perf_counter() - start

        start = time.perf_counter()
        newPaths: typing.Dict[Tile, typing.List[Path]] = None
        for i in range(40):
            newPaths = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance_global_visited(map, startTiles, valFunc, priorityFunc=prioFunc, maxTurns=10000, maxDepth=1000, noNeutralCities=True, noLog=True)
        newTook = time.perf_counter() - start

        start = time.perf_counter()
        oldPaths: typing.Dict[Tile, typing.List[Path]] = None
        for i in range(40):
            oldPaths = SearchUtils.breadth_first_dynamic_max_per_tile_per_distance(map, startTiles, valFunc, priorityFunc=prioFunc, useGlobalVisitedSet=True, maxTurns=10000, maxDepth=1000, noNeutralCities=True, forceOld=True)
        oldTook = time.perf_counter() - start
        #
        # paths = [l for l in itertools.chain.from_iterable(newPaths.values())]
        # self.render_paths(map, paths, 'old paths are cool...?')

        for tile in startTiles.keys():
            for i, oldPath in enumerate(oldPaths[tile]):
                newPath = newPaths[tile][i]

                self.assertEqual(oldPath.length, newPath.length)
                self.assertEqual(oldPath.value, newPath.value)
                self.assertEqual(oldPath.econValue, newPath.econValue)

                # these asserts dont work for this algo for whatever reason, they end up with different permutations of the same value paths
                # oldNode = oldPath.start
                # newNode = newPath.start
                # while oldNode and newNode:
                #     if oldNode.tile != newNode.tile:
                #         # self.assertEqual(oldNode.tile.player, newNode.tile.player)
                #         # self.assertEqual(oldNode.tile.army, newNode.tile.army)
                #         self.render_paths(map, [oldPath, newPath], f'{oldPath} / {newPath}')
                #     oldNode = oldNode.next
                #     newNode = newNode.next
                # self.assertIsNone(oldNode)
                # self.assertIsNone(newNode)

        self.assertLess(newTook, oldTook, f'new algo should be faster than the one that duplicates all the fucking tileLists wtf yo')
        self.begin_capturing_logging()
        logbook.info(f'old took {oldTook:.5f}, new took {newTook:.5f}')
        # paths = [l for l in itertools.chain.from_iterable(oldPaths.values())]
        # paths.extend(itertools.chain.from_iterable(newPaths.values()))
        # self.render_paths(map, paths, 'paths are cool...?')
