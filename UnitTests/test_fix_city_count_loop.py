import unittest

from TestBase import TestBase
from base.client.map import Score
from base.client.tile import Tile, TILE_EMPTY


class CityCountLoopFixTests(TestBase):
    """
    Repro for live FFA crash:
        AssertionError('INFINITE LOOPED IN TEAM CITY HANDLER')
        at base/client/map.py calculate_player_deltas

    Observed in live game logs:
        - game qGoCzDQ16 ~t484: 'CITY_COUNT team ++ Incrementing p6 cities' ran
          from 64 to 109 before asserting; 'Player captured: p2 by p6' and
          'CITY_COUNT increasing capturer p6 cities from 109' followed the crash.
        - game O2w___Bui t598: 'team5 realEnemyCities 664 based on
          actualEnemyTeamDelta 664, friendlyFightDelta 0 (teamCurrentCities 9)'
          -> 'Trying to make cities for team 5 match 664 vs current 9' -> p5 ran
          9->109 (exactly the 100-iteration cap) -> assert. p5 had just captured p7.
        - game Fcfx3IxPg t568: 'team1 realEnemyCities 231 ... teamCurrentCities 16'
          right after 'topolog captured acknowknot' -> same runaway.

    Root cause reproduced here: when a team captures a player, the capturer's
    actualScoreDelta for that update includes the victim's entire transferred
    score (army+tiles), which is NOT city income. friendlyFightDelta only tracks
    OUR unexplained delta so it stays 0 for enemy-vs-enemy captures. The
    `abs(diff) < 6 or friendlyFightDelta == 0` clause then assigned that inflated
    realEnemyCities as newCityCount and the +/-1 corrective while loops ran to
    the iteration cap and asserted.
    """

    def _build_ffa_city_bonus_turn_map(self, turn: int = 4):
        """
        Builds a tiny FFA map (teams=None) on a city-bonus-only turn (even turn,
        not a 50-turn army bonus), with use_basic_city_counter forced off so
        calculate_player_deltas exercises the score-delta city estimation path.

        @param turn: even turn number (city bonus turn, not army bonus).
        @return: (MapBase, board) tuple.
        """
        width = 3
        board = [
            [Tile(x, y, tile=TILE_EMPTY, army=0, player=-1, tileIndex=y * width + x) for x in range(width)]
            for y in range(1)
        ]
        map = self.get_test_map(board, turn=turn, num_players=3)
        map.use_basic_city_counter = False
        return map, board

    def test_calculate_player_deltas__enemy_capture_score_inflation_does_not_runaway(self):
        """
        Enemy p1's score delta is +664 (it captured p2 this update, inheriting
        the victim's score). Pre-fix this set newCityCount=664 and the corrective
        loop incremented p1.cityCount one at a time until the iter cap asserted.
        Post-fix the bogus realEnemyCities is ignored and p1 keeps 9 cities.
        """
        map, board = self._build_ffa_city_bonus_turn_map()

        myPlayer = map.players[0]
        capturer = map.players[1]
        victim = map.players[2]

        # Our player: consistent bookkeeping (1 owned city + general = 2) and a
        # clean +2 score delta matching city income so friendlyFightDelta == 0,
        # exactly like the live crash logs.
        board[0][0].player = 0
        myPlayer.cities = [board[0][0]]
        myPlayer.cityCount = 2
        myPlayer.score = 102

        capturer.cities = []
        capturer.cityCount = 9
        capturer.score = 1664  # lastScores 1000 + 664 from the captured player

        victim.dead = True

        map.scoreHistory[1] = [
            Score(0, 100, 10, False),
            Score(1, 1000, 100, False),
            Score(2, 0, 0, True),
        ]

        map.calculate_player_deltas()

        self.assertEqual(9, capturer.cityCount,
                         'a capture-inflated score delta must not be converted into fake enemy cities')

    def test_calculate_player_deltas__enemy_capture_score_inflation_does_not_runaway_decrement(self):
        """
        Same runaway in the decrement direction: realEnemyCities lands far below
        teamCurrentCities (e.g. tracking was previously inflated to 150 and the
        team has a normal turn). Pre-fix the `or friendlyFightDelta == 0` clause
        set newCityCount=realEnemyCities and the decrement loop ran to the cap.
        """
        map, board = self._build_ffa_city_bonus_turn_map()

        myPlayer = map.players[0]
        capturer = map.players[1]
        victim = map.players[2]

        board[0][0].player = 0
        myPlayer.cities = [board[0][0]]
        myPlayer.cityCount = 2
        myPlayer.score = 102

        capturer.cities = []
        capturer.cityCount = 150
        capturer.score = 1005  # modest +5 delta; realEnemyCities lands at 5

        victim.dead = True

        map.scoreHistory[1] = [
            Score(0, 100, 10, False),
            Score(1, 1000, 100, False),
            Score(2, 0, 0, True),
        ]

        map.calculate_player_deltas()

        # The cityDifference <= -20 branch interprets the huge negative diff as
        # 'they spent army taking a neutral city' and applies a single +1, which
        # is the intended bounded corrective. The runaway decrement to
        # realEnemyCities (5) must NOT happen.
        self.assertEqual(151, capturer.cityCount)

    def test_calculate_player_deltas__small_city_drift_still_resyncs(self):
        """
        Regression guard: the legit resync path must still work. Enemy shows an
        unexplained +5 score over expected city income on a bonus turn ->
        realEnemyCities is within the +-6 sanity bound and cityCount corrects
        9 -> 14 through the normal increment loop.
        """
        map, board = self._build_ffa_city_bonus_turn_map()

        myPlayer = map.players[0]
        enemy = map.players[1]
        victim = map.players[2]

        board[0][0].player = 0
        myPlayer.cities = [board[0][0]]
        myPlayer.cityCount = 2
        myPlayer.score = 102

        enemy.cities = []
        enemy.cityCount = 9
        enemy.score = 1014  # +14: expected 9 city income + 5 unexplained

        victim.dead = True

        map.scoreHistory[1] = [
            Score(0, 100, 10, False),
            Score(1, 1000, 100, False),
            Score(2, 0, 0, True),
        ]

        map.calculate_player_deltas()

        self.assertEqual(14, enemy.cityCount)
        self.assertEqual(map.turn, enemy.cityGainedTurn)

    def test_calculate_player_deltas__large_diff_with_friendly_fight_still_waits(self):
        """
        Regression guard for the unchanged WAITING branch: when our own score
        delta is unexplained (friendlyFightDelta != 0), a large enemy
        realEnemyCities diff must not be applied.
        """
        map, board = self._build_ffa_city_bonus_turn_map()

        myPlayer = map.players[0]
        enemy = map.players[1]
        victim = map.players[2]

        board[0][0].player = 0
        myPlayer.cities = [board[0][0]]
        myPlayer.cityCount = 2
        myPlayer.score = 100  # +0 actual vs +2 expected -> friendlyFightDelta = 2

        enemy.cities = []
        enemy.cityCount = 9
        enemy.score = 1020  # realEnemyCities = 20 + 2 = 22, diff 13 >= 6

        victim.dead = True

        map.scoreHistory[1] = [
            Score(0, 100, 10, False),
            Score(1, 1000, 100, False),
            Score(2, 0, 0, True),
        ]

        map.calculate_player_deltas()

        self.assertEqual(9, enemy.cityCount)
