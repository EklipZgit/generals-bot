from __future__ import annotations

import typing

from BotModules.BotCentralDefense import BotCentralDefense
from BotModules.BotStateQueries import BotStateQueries
from Directives import Timings
from History import History
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet
from Models.Move import Move
from Sim.TextMapLoader import TextMapLoader
from StrategyModels import ExpansionPotential
from base.client.map import Tile, new_value_grid, PLAYER_CHAR_BY_INDEX


if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot

class BotSerialization:
    @staticmethod
    def load_resume_data(bot: EklipZBot, resume_data: typing.Dict[str, str]):
        if f'bot_target_player' in resume_data:  # ={self.player}')
            bot.targetPlayer = int(resume_data[f'bot_target_player'])
            if bot.targetPlayer >= 0:
                bot.targetPlayerObj = bot._map.players[bot.targetPlayer]
            bot.opponent_tracker.targetPlayer = bot.targetPlayer
        if f'targetPlayerExpectedGeneralLocation' in resume_data:  # ={self.targetPlayerExpectedGeneralLocation.x},{self.targetPlayerExpectedGeneralLocation.y}')
            bot.targetPlayerExpectedGeneralLocation = BotStateQueries.parse_tile_str(bot, resume_data[f'targetPlayerExpectedGeneralLocation'])
        if f'bot_locked_launch_point' in resume_data:
            bot.locked_launch_point = BotStateQueries.parse_tile_str(bot, resume_data[f'bot_locked_launch_point'])
        if f'bot_is_all_in_losing' in resume_data:  # ={self.is_all_in_losing}')
            bot.is_all_in_losing = BotStateQueries.parse_bool(bot, resume_data[f'bot_is_all_in_losing'])
        if f'bot_all_in_losing_counter' in resume_data:  # ={self.all_in_losing_counter}')
            bot.all_in_losing_counter = int(resume_data[f'bot_all_in_losing_counter'])

        if f'bot_is_all_in_army_advantage' in resume_data:  # ={self.is_all_in_army_advantage}')
            bot.is_all_in_army_advantage = BotStateQueries.parse_bool(bot, resume_data[f'bot_is_all_in_army_advantage'])
        if f'bot_is_winning_gather_cyclic' in resume_data:  # ={self.is_all_in_army_advantage}')
            bot.is_winning_gather_cyclic = BotStateQueries.parse_bool(bot, resume_data[f'bot_is_winning_gather_cyclic'])
        if f'bot_all_in_army_advantage_counter' in resume_data:  # ={self.all_in_army_advantage_counter}')
            bot.all_in_army_advantage_counter = int(resume_data[f'bot_all_in_army_advantage_counter'])
        if f'bot_all_in_army_advantage_cycle' in resume_data:  # ={self.all_in_army_advantage_cycle}')
            bot.all_in_army_advantage_cycle = int(resume_data[f'bot_all_in_army_advantage_cycle'])
        if f'bot_defend_economy' in resume_data:
            bot.defend_economy = BotStateQueries.parse_bool(bot, resume_data[f'bot_defend_economy'])

        if f'bot_timings_launch_timing' in resume_data:
            # self.timings = None
            # if self._map.turn % 50 != 0:
            cycleTurns = bot._map.turn + bot._map.remainingCycleTurns
            bot.timings = Timings(0, 0, 0, 0, 0, cycleTurns, disallowEnemyGather=True)
            bot.timings.launchTiming = int(resume_data[f'bot_timings_launch_timing'])
            bot.timings.splitTurns = int(resume_data[f'bot_timings_split_turns'])
            bot.timings.quickExpandTurns = int(resume_data[f'bot_timings_quick_expand_turns'])
            bot.timings.cycleTurns = int(resume_data[f'bot_timings_cycle_turns'])

        if f'bot_is_rapid_capturing_neut_cities' in resume_data:  # ={self.is_rapid_capturing_neut_cities}')
            bot.is_rapid_capturing_neut_cities = BotStateQueries.parse_bool(bot, resume_data[f'bot_is_rapid_capturing_neut_cities'])
        if f'bot_is_blocking_neutral_city_captures' in resume_data:  # ={self.is_blocking_neutral_city_captures}')
            bot.is_blocking_neutral_city_captures = BotStateQueries.parse_bool(bot, resume_data[f'bot_is_blocking_neutral_city_captures'])
        if f'bot_was_allowing_neutral_cities_last_turn' in resume_data:
            bot.was_allowing_neutral_cities_last_turn = BotStateQueries.parse_bool(bot, resume_data[f'bot_was_allowing_neutral_cities_last_turn'])
        if f'bot_finishing_exploration' in resume_data:  # ={self.finishing_exploration}')
            bot.finishing_exploration = BotStateQueries.parse_bool(bot, resume_data[f'bot_finishing_exploration'])
        if f'bot_targeting_army' in resume_data:  # ={self.targetingArmy.tile.x},{self.targetingArmy.tile.y}')
            bot.targetingArmy = bot.get_army_at(BotStateQueries.parse_tile_str(bot, resume_data[f'bot_targeting_army']))
        else:
            bot.targetingArmy = None
        if f'bot_cur_path' in resume_data:  # ={str(self.curPath)}')
            bot.curPath = TextMapLoader.parse_path(bot._map, resume_data[f'bot_cur_path'])
        else:
            bot.curPath = None
        if f'bot_last_move' in resume_data:
            bot.last_move = BotSerialization.convert_string_to_move(bot, resume_data[f'bot_last_move'])
        else:
            bot.last_move = None

        for player in bot._map.players:
            char = PLAYER_CHAR_BY_INDEX[player.index]
            if f'{char}Emergences' in resume_data:
                bot.armyTracker.emergenceLocationMap[player.index] = BotSerialization.convert_string_to_float_map_matrix(bot, resume_data[f'{char}Emergences'])
            elif f'targetPlayerExpectedGeneralLocation' in resume_data and player.index == bot.targetPlayer and len(bot._map.players[bot.targetPlayer].tiles) > 0:
                # only do the old behavior when explicit emergences arent available.
                bot.armyTracker.emergenceLocationMap[bot.targetPlayer][bot.targetPlayerExpectedGeneralLocation] = 5
            if f'{char}ValidGeneralPos' in resume_data:
                bot.armyTracker.valid_general_positions_by_player[player.index] = BotSerialization.convert_string_to_bool_map_matrix_set(bot, resume_data[f'{char}ValidGeneralPos'])
            if f'{char}TilesEverOwned' in resume_data:
                bot.armyTracker.tiles_ever_owned_by_player[player.index] = BotSerialization.convert_string_to_tile_set(bot, resume_data[f'{char}TilesEverOwned'])
            if f'{char}UneliminatedEmergences' in resume_data:
                bot.armyTracker.uneliminated_emergence_events[player.index] = BotSerialization.convert_string_to_tile_int_dict(bot, resume_data[f'{char}UneliminatedEmergences'])
            if f'{char}UneliminatedEmergenceCityPerfectInfo' in resume_data:
                bot.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index] = BotSerialization.convert_string_to_tile_set(bot, resume_data[f'{char}UneliminatedEmergenceCityPerfectInfo'])
            else:
                bot.armyTracker.uneliminated_emergence_event_city_perfect_info[player.index] = {t for t in bot.armyTracker.uneliminated_emergence_events[player.index].keys()}
            if f'{char}UnrecapturedEmergences' in resume_data:
                bot.armyTracker.unrecaptured_emergence_events[player.index] = BotSerialization.convert_string_to_tile_set(bot, resume_data[f'{char}UnrecapturedEmergences'])
            else:
                pUnelim = bot.armyTracker.uneliminated_emergence_events[player.index]
                pUnrecaptured = bot.armyTracker.unrecaptured_emergence_events[player.index]
                for t in bot._map.get_all_tiles():
                    if t in pUnelim:
                        pUnrecaptured.add(t)

        if f'TempFogTiles' in resume_data:
            tiles = BotSerialization.convert_string_to_tile_set(bot, resume_data[f'TempFogTiles'])
            for tile in tiles:
                tile.isTempFogPrediction = True
            if len(tiles) > 0:
                for player in bot._map.players:
                    if not bot._map.is_player_on_team_with(bot._map.player_index, player.index):
                        bot.armyTracker.should_recalc_fog_land_by_player[player.index] = False
        if f'DiscoveredNeutral' in resume_data:
            tiles = BotSerialization.convert_string_to_tile_set(bot, resume_data[f'DiscoveredNeutral'])
            for tile in tiles:
                tile.discoveredAsNeutral = True
        if f'DefensiveSpanningTree' in resume_data:
            bot.defensive_spanning_tree = BotSerialization.convert_string_to_tile_set(bot, resume_data[f'DefensiveSpanningTree'])
        if f'FriendlyCitySpanningTree' in resume_data:
            bot.friendly_city_spanning_tree = BotSerialization.convert_string_to_tile_set(bot, resume_data[f'FriendlyCitySpanningTree'])

        if 'is_custom_map' in resume_data:
            bot._map.is_custom_map = bool(resume_data['is_custom_map'])
        if 'walled_city_base_value' in resume_data:
            bot._map.walled_city_base_value = int(resume_data['walled_city_base_value'])
            bot._map.is_walled_city_game = True

        if 'PATHABLE_CITY_THRESHOLD' in resume_data:
            Tile.PATHABLE_CITY_THRESHOLD = int(resume_data['PATHABLE_CITY_THRESHOLD'])
            Tile.recalc_all_derived(bot._map.tiles_by_index)
            bot._map.distance_mapper.recalculate()
            bot._map.update_reachable()
        else:
            Tile.PATHABLE_CITY_THRESHOLD = 5  # old replays, no cities were ever pathable.
            Tile.recalc_all_derived(bot._map.tiles_by_index)

        if bot.targetPlayerExpectedGeneralLocation:
            BotCentralDefense.rebuild_intergeneral_analysis_for_central_defense(bot)

        # Rebuild islands from serialized data if available (overrides the recalculate_tile_islands done in init)
        if 'island_ids' in resume_data:
            island_id_matrix = BotSerialization.convert_string_to_island_id_matrix(bot, resume_data['island_ids'])
            Tile.recalc_all_derived(bot._map.tiles_by_index)
            bot.tileIslandBuilder.rebuild_islands_from_ids(island_id_matrix)

        bot.win_condition_analyzer.load_city_contestation_history_from_map_data(resume_data)
        bot.opponent_tracker.load_from_map_data(resume_data)
        if bot.targetPlayer >= 0:
            bot._lastTargetPlayerCityCount = bot.opponent_tracker.get_current_team_scores_by_player(bot.targetPlayer).cityCount

        bot.last_init_turn = bot._map.turn - 1

        bot.city_expand_plan = None
        bot.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0, bot._map.turn)
        bot.enemy_expansion_plan = None

        loadedArmies = TextMapLoader.load_armies(bot._map, resume_data)
        if len(loadedArmies) == 0:
            for army in bot.armyTracker.armies.values():
                army.last_moved_turn = bot._map.turn - 3

            if bot.targetingArmy:
                bot.targetingArmy.last_moved_turn = bot._map.turn - 1

            for army in bot.armyTracker.armies.values():
                if army.tile.discovered:
                    army.last_moved_turn = bot._map.turn - 1
                else:
                    army.last_moved_turn = bot._map.turn - 5

        else:
            bot.armyTracker.armies = loadedArmies

        bot.history = History()

        # force a rebuild
        bot.cityAnalyzer.reset_reachability()
        bot.last_central_defense_signature = None
        bot.is_pre_resume_init_turn = False

        return

    @staticmethod
    def convert_int_tile_2d_array_to_string(bot: EklipZBot, rows: typing.List[typing.List[int]]) -> str:
        return ','.join([str(rows[tile.x][tile.y]) for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_float_tile_2d_array_to_string(bot: EklipZBot, rows: typing.List[typing.List[float]]) -> str:
        return ','.join([f'{rows[tile.x][tile.y]:.2f}' for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_int_map_matrix_to_string(bot: EklipZBot, mapMatrix: MapMatrixInterface[int]) -> str:
        return ','.join([str(mapMatrix[tile]) for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_float_map_matrix_to_string(bot: EklipZBot, mapMatrix: MapMatrixInterface[float]) -> str:
        return ','.join([f'{mapMatrix[tile]:.2f}' for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_bool_map_matrix_to_string(bot: EklipZBot, mapMatrix: MapMatrixInterface[bool] | MapMatrixSet) -> str:
        return ''.join(["1" if mapMatrix[tile] else "0" for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_tile_set_to_string(bot: EklipZBot, tiles: typing.Set[Tile]) -> str:
        return ''.join(["1" if tile in tiles else "0" for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_tile_int_dict_to_string(bot: EklipZBot, tiles: typing.Dict[Tile, int]) -> str:
        return ','.join([str(tiles.get(tile, '')) for tile in bot._map.get_all_tiles()])

    @staticmethod
    def convert_move_to_string(move: Move) -> str:
        return f'{move.source.x},{move.source.y}>{move.dest.x},{move.dest.y}>{move.move_half}'

    @staticmethod
    def convert_string_to_int_tile_2d_array(bot: EklipZBot, data: str) -> typing.List[typing.List[int]]:
        arr = new_value_grid(bot._map, -1)

        values = data.split(',')
        i = 0
        prev = None
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            arr[tile.x][tile.y] = int(v)

            prev = tile
            i += 1

        return arr

    @staticmethod
    def convert_string_to_float_tile_2d_array(bot: EklipZBot, data: str) -> typing.List[typing.List[float]]:
        arr = new_value_grid(bot._map, 0.0)

        values = data.split(',')
        i = 0
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            if v != '':
                arr[tile.x][tile.y] = float(v)
            i += 1

        return arr

    @staticmethod
    def convert_string_to_bool_map_matrix(bot: EklipZBot, data: str) -> MapMatrixInterface[bool]:
        matrix = MapMatrix(bot._map, False)
        i = 0
        for v in data:
            if v == "1":
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                matrix[tile] = True
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_bool_map_matrix_set(bot: EklipZBot, data: str) -> MapMatrixSet:
        matrix = MapMatrixSet(bot._map)
        i = 0
        for v in data:
            if v == "1":
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                matrix.add(tile)
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_int_map_matrix(bot: EklipZBot, data: str) -> MapMatrixInterface[int]:
        matrix = MapMatrix(bot._map, -1)
        values = data.split(',')
        i = 0
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            matrix[tile] = int(v)
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_float_map_matrix(bot: EklipZBot, data: str) -> MapMatrixInterface[float]:
        matrix = MapMatrix(bot._map, -1.0)
        values = data.split(',')
        i = 0
        for v in values:
            tile = BotSerialization.get_tile_by_tile_index(bot, i)
            matrix[tile] = float(v)
            i += 1

        return matrix

    @staticmethod
    def convert_string_to_tile_set(bot: EklipZBot, data: str) -> typing.Set[Tile]:
        outputSet = set()
        i = 0
        for v in data:
            if v == "1":
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                outputSet.add(tile)
            i += 1

        return outputSet

    @staticmethod
    def convert_string_to_tile_int_dict(bot: EklipZBot, data: str) -> typing.Dict[Tile, int]:
        outputSet = {}
        i = 0
        for v in data.split(','):
            if v != "N" and v != '':
                tile = BotSerialization.get_tile_by_tile_index(bot, i)
                outputSet[tile] = int(v)
            i += 1

        return outputSet

    @staticmethod
    def convert_string_to_move(bot: EklipZBot, data: str) -> Move:
        sourceRaw, destRaw, moveHalfRaw = data.split('>')
        sourceXRaw, sourceYRaw = sourceRaw.split(',')
        destXRaw, destYRaw = destRaw.split(',')
        source = bot._map.GetTile(int(sourceXRaw), int(sourceYRaw))
        dest = bot._map.GetTile(int(destXRaw), int(destYRaw))
        return Move(source, dest, moveHalfRaw.lower() == 'true')

    @staticmethod
    def get_tile_by_tile_index(bot: EklipZBot, tileIndex: int) -> Tile:
        x, y = BotSerialization.convert_tile_server_index_to_friendly_x_y(bot, tileIndex)
        return bot._map.GetTile(x, y)

    @staticmethod
    def convert_tile_server_index_to_friendly_x_y(bot: EklipZBot, tileIndex: int) -> typing.Tuple[int, int]:
        y = tileIndex // bot._map.cols
        x = tileIndex % bot._map.cols
        return x, y

    @staticmethod
    def convert_island_builder_to_string(bot: EklipZBot, island_builder) -> str:
        """
        Serialize island unique_ids per tile as a flat list in tile_index order.
        Format: island_ids=id0,id1,id2,... (index = tile_index)
        None values are stored as empty string '' like other serialization methods.
        This format can be directly loaded into a MapMatrix[int | None].raw field.
        """
        tile_ids = []
        for tile in bot._map.tiles_by_index:
            island = island_builder.tile_island_lookup.raw[tile.tile_index]
            tile_ids.append(str(island.unique_id) if island is not None else '')
        return f'island_ids={",".join(tile_ids)}'

    @staticmethod
    def convert_string_to_island_id_matrix(bot: EklipZBot, data: str) -> MapMatrixInterface[int | None]:
        """
        Parse island_ids string and return a MapMatrix of island unique_ids.
        Returns None for tiles with no island (empty string).
        The format is a flat comma-separated list in tile_index order.
        """
        matrix = MapMatrix(bot._map, None)
        values = data.split(',')
        for tile_idx, id_str in enumerate(values):
            if id_str == '':
                matrix.raw[tile_idx] = None
            else:
                matrix.raw[tile_idx] = int(id_str)
        return matrix
