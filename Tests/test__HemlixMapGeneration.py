import os
import pathlib
import random
import time
import traceback
import typing

import logbook

import SearchUtils
from DistanceMapperImpl import DistanceMapperImpl
from Sim.GameSimulator import GameSimulatorHost
from TestBase import TestBase
from ViewInfo import TargetStyle
from base.client.map import MapBase
from base.client.tile import TILE_EMPTY, Tile
from bot_ek0x45 import EklipZBot


class MapGenerationPlayground(TestBase):
    def test_generate_basic_map(self):
        renderDebug = False
        startTime = time.perf_counter()
        # dont waste time randomizing movables, this is only relevant to human.exe and should not matter in map generation
        MapBase.DO_NOT_RANDOMIZE = True

        numMapsToGenerate = 1000
        for i in range(numMapsToGenerate):
            # uncomment to test the runtime of the existing map generator on your machine, to compare.
            # map = self.generate_map_current(minimumSpawnDistance=15, mountainRatio=0.25, fairness=1.0)
            map = self.generate_map_hemlix(minimumSpawnDistance=15, mountainRatio=0.25, fairness=1.0)
            if renderDebug:
                self.render_map(map)

        self.begin_capturing_logging()
        logbook.info(f'took {time.perf_counter() - startTime:.3f} seconds to generate {numMapsToGenerate} maps.')

    def generate_map_current(self, minimumSpawnDistance=15, mountainRatio=0.25, fairness=1.0) -> MapBase:
        """
        This is basically the same generation algo as the generals.io server currently uses (actually this is slightly more optimized than current server, but will be how the server works next patch).
        @param minimumSpawnDistance:
        @param mountainRatio: the ratio of tiles that should end up being mountains.
        @param fairness:
        @return:
        """
        self.stop_capturing_logging()

        iterationCount = 0
        while iterationCount < 10000:
            iterationCount += 1

            width = random.randint(19, 25)
            height = random.randint(19, 25)

            map = MapBase(
                player_index=0,
                teams=None,
                user_names=['Hemlix', 'EklipZ'],
                turn=1,
                map_grid_y_x=[[Tile(x, y, tileIndex=y * width + x) for x in range(width)] for y in range(height)],
                replay_url='not real',
                replay_id='not real',
                modifiers=[],
            )

            # this stuff doesnt exist on the server code, this is just necessary for the human.exe framework to function so you can reuse the reachable BFS checks.
            distanceMapper = DistanceMapperImpl(map)
            map.distance_mapper = distanceMapper

            foundGenSpawns = False
            genA = None
            genB = None
            while not foundGenSpawns:
                genAX = random.randint(0, width - 1)
                genAY = random.randint(0, height - 1)

                genBX = random.randint(0, width - 1)
                genBY = random.randint(0, height - 1)

                if abs(genAX - genBX) + abs(genAY - genBY) >= minimumSpawnDistance:
                    foundGenSpawns = True

                    genA = map.GetTile(genAX, genAY)
                    genA.isGeneral = True
                    genA.tile = 0
                    genA.player = 0
                    genA.army = 1
                    map.generals[0] = genA

                    genB = map.GetTile(genBX, genBY)
                    genB.isGeneral = True
                    genB.tile = 1
                    genB.player = 1
                    genB.army = 1
                    map.generals[1] = genB

            allTileIndexes = [t.tile_index for t in map.get_all_tiles() if not t.isGeneral]

            random.shuffle(allTileIndexes)

            for i in range(int(len(allTileIndexes) * mountainRatio)):
                mapTile = map.tiles_by_index[allTileIndexes[i]]
                map.convert_tile_to_mountain(mapTile)

            if map.distance_mapper.get_distance_between(genA, genB) > 999:
                # invalid map, generals cannot reach each other through mountains. Reroll the map.
                continue

            return map

        raise Exception(f'exceeded the iteration count limit {iterationCount}, something is wrong in the map generator and no maps are valid or returned.')

    def generate_map_hemlix(self, minimumSpawnDistance=15, mountainRatio=0.25, fairness=1.0) -> MapBase:
        """
        Create your own version here.

        @param minimumSpawnDistance:
        @param mountainRatio: the ratio of tiles that should end up being mountains.
        @param fairness:
        @return:
        """
        self.stop_capturing_logging()

        iterationCount = 0
        while iterationCount < 10000:
            iterationCount += 1

            width = random.randint(20, 26)
            height = random.randint(20, 26)

            map = MapBase(
                player_index=0,
                teams=None,
                user_names=['Hemlix', 'EklipZ'],
                turn=1,
                map_grid_y_x=[[Tile(x, y, tileIndex=y * width + x) for x in range(width)] for y in range(height)],
                replay_url='not real',
                replay_id='not real',
                modifiers=[],
            )

            # this stuff doesnt exist on the server code, this is just necessary for the human.exe framework to function so you can reuse the reachable BFS checks.
            distanceMapper = DistanceMapperImpl(map)
            map.distance_mapper = distanceMapper

            foundGenSpawns = False
            genA = None
            genB = None
            while not foundGenSpawns:
                genAX = random.randint(0, width - 1)
                genAY = random.randint(0, height - 1)

                genBX = random.randint(0, width - 1)
                genBY = random.randint(0, height - 1)

                if abs(genAX - genBX) + abs(genAY - genBY) >= minimumSpawnDistance:
                    foundGenSpawns = True

                    genA = map.GetTile(genAX, genAY)
                    genA.isGeneral = True
                    genA.tile = 0
                    genA.player = 0
                    genA.army = 1
                    map.generals[0] = genA

                    genB = map.GetTile(genBX, genBY)
                    genB.isGeneral = True
                    genB.tile = 1
                    genB.player = 1
                    genB.army = 1
                    map.generals[1] = genB

            allTileIndexes = [t.tile_index for t in map.get_all_tiles() if not t.isGeneral]

            random.shuffle(allTileIndexes)

            for i in range(int(len(allTileIndexes) * mountainRatio)):
                mapTile = map.tiles_by_index[allTileIndexes[i]]
                map.convert_tile_to_mountain(mapTile)

            if map.distance_mapper.get_distance_between(genA, genB) > 999:
                # invalid map, generals cannot reach each other through mountains. Reroll the map.
                continue

            return map

        raise Exception(f'exceeded the iteration count limit {iterationCount}, something is wrong in the map generator and no maps are valid or returned.')
