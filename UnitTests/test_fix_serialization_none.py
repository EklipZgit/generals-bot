import unittest

from BotModules.BotSerialization import BotSerialization
from TestBase import TestBase


class SerializationNoneTests(TestBase):
    """
    Regression coverage for the live-game txtmap dump crash:

        TypeError: argument of type 'NoneType' is not a container or iterable
        at BotSerialization.convert_tile_set_to_string (BotSerialization.py)
        via BotRendering.dump_turn_data_to_string -> BotHost.save_txtmap

    bot_ek0x45.py deliberately resets bot.defensive_spanning_tree and
    bot.friendly_city_spanning_tree to None when the bot's previous move
    captured a friendly city, forcing the spanning trees to be rebuilt on a
    later recomputation pass. When the per-turn txtmap dump runs before that
    recompute happens (the analyze sections are skipped on some turns), the
    dump hands None to convert_tile_set_to_string and crashes, trashing the
    DefensiveSpanningTree field for that turn. None must serialize as an
    empty (all-zero) tile bitmap at the serialization boundary.
    """

    def test_should_serialize_none_tile_set_as_empty_bitmap(self):
        mapFile = 'GameContinuationEntries/should_load_map_data___P0YO4V4u8---0--111.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 111, fill_out_tiles=True)
        bot = type('SerializationTestBot', (), {})()
        bot._map = map

        serialized = BotSerialization.convert_tile_set_to_string(bot, None)

        allTiles = list(map.get_all_tiles())
        self.assertEqual(len(allTiles), len(serialized))
        self.assertTrue(all(char == '0' for char in serialized))
        self.assertEqual(set(), BotSerialization.convert_string_to_tile_set(bot, serialized))

    def test_should_still_round_trip_populated_tile_set(self):
        mapFile = 'GameContinuationEntries/should_load_map_data___P0YO4V4u8---0--111.txtmap'
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 111, fill_out_tiles=True)
        bot = type('SerializationTestBot', (), {})()
        bot._map = map

        tileSet = {map.GetTile(1, 1), map.GetTile(2, 1)}
        serialized = BotSerialization.convert_tile_set_to_string(bot, tileSet)

        self.assertEqual(tileSet, BotSerialization.convert_string_to_tile_set(bot, serialized))
