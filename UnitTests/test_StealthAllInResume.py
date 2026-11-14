from BotModules.BotRendering import BotRendering
from BotModules.BotStealthAllIn import BotStealthAllIn, StealthAllInState
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.map import MapBase


class StealthAllInResumeTests(TestBase):
    """Round-trip the committed stealth/WRP route through txtmap serialization."""

    def __init__(self, methodName: str = ...) -> None:
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    @staticmethod
    def _build_map_text() -> str:
        """Open 7x7 map with generals at opposite corners."""
        rows = (
            'A......',
            '.......',
            '.......',
            '.......',
            '.......',
            '.......',
            '......B')
        tileTextByCell = {
            '.': '   ',
            'A': 'aG1',
            'B': 'bG1',
        }
        border = '|  ' * len(rows[0])
        mapRows = [''.join(tileTextByCell[cell] for cell in row) for row in rows]
        return '\n'.join((border, *mapRows, border, 'aTiles=1', 'bTiles=1'))

    def _load_bot_on_open_map(self):
        gameMap, _ = self.load_map_and_general_from_string(
            self._build_map_text(),
            turn=1,
            player_index=0,
            respect_undiscovered=True)
        gameMap.resume_data = {}
        gameMap.resume_data_is_txtmap = False
        simHost = GameSimulatorHost(
            gameMap,
            player_with_viewer=gameMap.player_index,
            playerMapVision=gameMap,
            botInitOnly=True)
        bot = self.get_debug_render_bot(simHost, gameMap.player_index)
        return gameMap, bot

    def test_committed_wrp_route_survives_txtmap_round_trip(self):
        """A committed route dumped mid-all-in resumes executing the remaining steps."""
        gameMap, bot = self._load_bot_on_open_map()
        # Committed routes always reference the bot's vision map (bot._map), which is what
        # load_resume_data parses tile coordinates against - not the simulator's true map.
        headTile = bot._map.GetTile(1, 0)
        midTile = bot._map.GetTile(2, 0)
        tailTile = bot._map.GetTile(3, 0)
        headTile.player = 0
        headTile.army = 50

        flankPath = Path()
        flankPath.add_next(headTile)
        committedRoute = Path()
        committedRoute.add_next(headTile)
        committedRoute.add_next(midTile)
        committedRoute.add_next(tailTile)

        bot.targetPlayer = 1
        bot.targetPlayerExpectedGeneralLocation = bot._map.GetTile(6, 5)
        bot.stealth_all_in = StealthAllInState(
            launch_tile=headTile,
            entry_tile=headTile,
            flank_path=flankPath,
            launch_turn=gameMap.turn,
            wrp_job=None,
            committed_route=committedRoute,
            committed_turn=gameMap.turn,
            last_route_move=None,
            used_normal_gather_fallback_turns=2,
            generation=3,
            is_undefendable_hunt=False,
            is_truncated_front=True)
        bot.stealth_all_in_generation = 7

        resumeData = TextMapLoader.load_data_from_string(
            BotRendering.dump_turn_data_to_string(bot))
        self.assertIn('bot_stealth_committed_route', resumeData)
        self.assertIn('bot_stealth_is_truncated_front', resumeData)

        # Simulate loading a fresh bot from the txtmap: clear stealth state, then reload.
        bot.stealth_all_in = None
        bot.stealth_all_in_generation = 0
        bot.load_resume_data(resumeData)

        restored = bot.stealth_all_in
        self.assertIsNotNone(restored, 'committed WRP route did not resume from txtmap')
        self.assertEqual(
            [headTile, midTile, tailTile],
            restored.committed_route.tileList)
        self.assertIs(headTile, restored.launch_tile)
        self.assertIs(headTile, restored.entry_tile)
        self.assertEqual([headTile], restored.flank_path.tileList)
        self.assertEqual(gameMap.turn, restored.launch_turn)
        self.assertEqual(gameMap.turn, restored.committed_turn)
        self.assertEqual(3, restored.generation)
        self.assertEqual(7, bot.stealth_all_in_generation)
        self.assertEqual(2, restored.used_normal_gather_fallback_turns)
        self.assertFalse(restored.is_undefendable_hunt)
        self.assertTrue(restored.is_truncated_front)
        self.assertIsNone(restored.wrp_job)
        self.assertIsNone(restored.last_route_move)

        # The resumed route must keep executing: the next committed move is head -> mid.
        move = BotStealthAllIn.get_committed_route_move(
            bot,
            threat=None,
            defense_critical_tiles=set(),
            king_kill_path=None,
            race_chance=0.0)
        self.assertIsNotNone(move)
        self.assertIs(headTile, move.source)
        self.assertIs(midTile, move.dest)
        self.assertEqual([midTile, tailTile], restored.committed_route.tileList)
