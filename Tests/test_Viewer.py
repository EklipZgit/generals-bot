import os
from multiprocessing import Queue

from base.Colors import GRAY_DARK
from base.viewer import GeneralsViewer
from StrategyModels.OpponentTrackerModels import CycleStatsData
from TestBase import TestBase


class ViewerTests(TestBase):
    def test_should_render_player_scores_when_a_teams_cycle_stats_players_list_is_empty(self):
        """
        Repro for the live FFA viewer crash: OpponentTracker removes captured
        players from CycleStatsData.players, and a fully eliminated FFA team
        ends up with players == []. draw_player_scores used to index
        players[0] while sorting the score rows, so the draw loop threw and
        every frame rendered black from that turn on.
        """
        mapFile = 'GameContinuationEntries/should_find_kill_in_ffa_position___eW64nZ8rZ---2--69.txtmap'
        map, general = self.load_map_and_general(mapFile, turn=69)

        viewInfo = self.get_renderable_view_info(map)

        deadPlayer = next(p for p in map.players if p.index != map.player_index)
        deadPlayer.dead = True

        viewInfo.team_cycle_stats = []
        for teamIdx in range(max(map.unique_teams) + 1):
            teamPlayers = [p.index for p in map.players if p.team == teamIdx]
            viewInfo.team_cycle_stats.append(CycleStatsData(teamIdx, teamPlayers))
        viewInfo.team_cycle_stats[deadPlayer.team].players = []
        viewInfo.team_last_cycle_stats = [None for _ in viewInfo.team_cycle_stats]
        viewInfo.player_fog_risks = [0 for _ in map.players]

        os.environ['SDL_VIDEODRIVER'] = 'dummy'
        viewer = GeneralsViewer(Queue(), Queue(), self._testMethodName, cell_width=30, cell_height=30)
        viewer.updateGrid(viewInfo, map)
        viewer._initViewier(alignTop=True, alignLeft=True)
        viewer.draw_player_scores()

        # every player still gets a score row, eliminated players render grayed
        scoreRowTop = int(viewer._window_size[1] - viewer.infoRowHeight - viewer.scoreRowHeight)
        scoreRowPixelColors = set()
        for x in range(2, viewer._window_size[0], 5):
            scoreRowPixelColors.add(viewer._screen.get_at((x, scoreRowTop + 2))[:3])
        self.assertIn(GRAY_DARK, scoreRowPixelColors, 'eliminated players score row should still render grayed')
        self.assertTrue(any(color != GRAY_DARK and color != (0, 0, 0) for color in scoreRowPixelColors),
                        'living players score rows should still render in player colors')
