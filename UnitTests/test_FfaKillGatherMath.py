"""Material regressions for the imported Bruddah t100 continuation."""

from dataclasses import replace

from Models.Move import Move
from Strategy.FfaKillGatherMath import (
    FfaGatherForecast,
    FfaGatherPosition,
    FfaKillScenario,
    calculate_route_cost,
    certify_gather_scenarios,
    certify_kill,
    certify_retained_head_continuation,
    materialize_gather_position,
    project_forward_gather,
    project_safe_front,
)
from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import TILE_MOUNTAIN, Tile


ENTRY = 'GameContinuationEntries/should_all_in_nearby_players_as_fast_as_possible___50ZwYtndy---0--100.txtmap'

# Frozen literal schedules from the material probe, not a heuristic regenerated
# by the test. The second schedule keeps the forward root stationary throughout.
FIRST_GATHER = (
    '18,26>18,25;19,25>18,25;17,25>17,24;20,24>20,23;16,24>17,24;'
    '21,23>20,23;17,24>18,24;20,23>20,22;19,23>18,23;20,22>20,21;'
    '20,21>20,20;19,18>19,19;18,18>18,19;17,18>17,19;18,25>18,24;'
    '18,24>18,23;18,23>18,22;18,22>17,22;17,22>17,21;17,21>17,20;'
    '17,20>17,19;22,19>22,20;22,20>21,20;21,20>20,20;20,20>19,20;'
    '19,20>19,19;19,19>18,19;18,19>17,19')
SECOND_GATHER = (
    '19,27>18,27;18,27>18,26;19,26>18,26;20,25>20,24;16,25>17,25;'
    '21,24>20,24;23,18>22,18;22,17>22,18;18,26>18,25;17,25>17,24;'
    '20,24>20,23;22,18>22,19;17,24>18,24;20,23>20,22;20,22>20,21;'
    '20,21>20,20;14,18>14,19;18,25>18,24;18,24>18,23;18,23>18,22;'
    '18,22>17,22;17,22>17,21;17,21>17,20;17,20>17,19;22,19>22,20;'
    '22,20>21,20;21,20>20,20;20,20>19,20;19,20>19,19;19,19>18,19;'
    '18,19>17,19;17,19>16,19;16,19>15,19;15,19>14,19;14,19>13,19')


def _moves(game_map: MapBase, encoded: str) -> list[Move]:
    """Resolve a frozen adjacent-move schedule against one map instance."""
    moves: list[Move] = []
    for encoded_move in encoded.split(';'):
        source, dest = encoded_move.split('>')
        sx, sy = (int(v) for v in source.split(','))
        dx, dy = (int(v) for v in dest.split(','))
        moves.append(Move(game_map.GetTile(sx, sy), game_map.GetTile(dx, dy)))
    return moves


class FfaKillGatherMathTests(TestBase):
    """Keep the first-wave and two-cycle obligations independently testable."""

    __slots__ = ()

    def _position(self) -> tuple[MapBase, FfaGatherForecast, list[Tile]]:
        """Load only the bot's imported knowledge and replay the literal gather."""
        game_map, _ = self.load_map_and_general(ENTRY, respect_undiscovered=True, turn=100)
        # The txtmap loader leaves discovered=False on visible-cell tokens when
        # respect_undiscovered=True. Production Tile.update marks precisely
        # these non-fog tile codes discovered; reproduce that hydration without
        # revealing any fog tile or using replay truth.
        for tile in game_map.tiles_by_index:
            if tile.tile >= TILE_MOUNTAIN:
                tile.discovered = True
        gather = project_forward_gather(
            game_map, _moves(game_map, FIRST_GATHER), game_map.GetTile(17, 19), 0, 7)
        self.assertIsNotNone(gather)
        assert gather is not None
        prefix = [game_map.GetTile(x, y) for x, y in (
            (17, 19), (16, 19), (15, 19), (14, 19), (13, 19))]
        return game_map, gather, prefix

    def test_safe_front_keeps_the_gathered_material_without_touching_live_state(self) -> None:
        """The head survives all enemy standing and can receive the next gather."""
        game_map, gather, prefix = self._position()
        self.assertEqual(72, gather.launch_army)
        self.assertEqual(128, gather.position.turn)
        front = project_safe_front(game_map, gather, prefix, 0, 7, 46, 39, 1)
        self.assertIsNotNone(front)
        assert front is not None
        self.assertEqual(1, front.safety.margin)
        self.assertEqual(132, front.position.turn)
        self.assertEqual(64, front.position.armies[front.head_tile_index])
        self.assertEqual(62, front.enemy_standing)
        original_standing = game_map.players[0].standingArmy
        projected = materialize_gather_position(game_map, front.position, 0)
        self.assertEqual(107, projected.players[0].standingArmy)
        self.assertEqual(62, projected.players[0].tileCount)
        self.assertEqual(169, projected.scores[0].total)
        self.assertEqual(64, projected.GetTile(13, 19).army)
        self.assertEqual(0, projected.GetTile(13, 19).player)
        self.assertEqual(100, game_map.turn)
        self.assertEqual(7, game_map.GetTile(13, 19).player)
        self.assertEqual(2, game_map.GetTile(13, 19).army)
        self.assertEqual(original_standing, game_map.players[0].standingArmy)

    def test_safe_front_rejects_an_unaffordable_or_unpriced_next_step(self) -> None:
        """The next reveal is not licensed merely because four steps are safe."""
        game_map, gather, prefix = self._position()
        unsafe_prefix = prefix + [game_map.GetTile(12, 19)]
        cost = calculate_route_cost(game_map, unsafe_prefix, 0, 7)
        self.assertEqual(10, cost)
        projection = certify_kill(100, 28, 5, 72, cost, 46, 39, 1)
        self.assertFalse(projection.certified)
        self.assertLess(projection.margin, 0)
        self.assertIsNone(project_safe_front(game_map, gather, unsafe_prefix, 0, 7, 46, 39, 1))
        game_map.GetTile(13, 19).player = 1
        self.assertIsNone(project_safe_front(game_map, gather, prefix, 0, 7, 46, 39, 1))

    def test_retained_head_margin_cancels_enemy_army_spent_on_the_front(self) -> None:
        """No army is invented when target fields decline to withdraw."""
        game_map, gather, prefix = self._position()
        front = project_safe_front(game_map, gather, prefix, 0, 7, 46, 39, 1)
        self.assertIsNotNone(front)
        assert front is not None
        # 0: every surplus withdrawn; 4: each observed field kept its surplus;
        # 62: even the entire conservative standing reserve defends the prefix.
        for spent in (0, 4, 62):
            with self.subTest(enemy_standing_spent=spent):
                armies = list(front.position.armies)
                armies[front.head_tile_index] -= spent
                position: FfaGatherPosition = replace(front.position, armies=tuple(armies))
                projected = materialize_gather_position(game_map, position, 0)
                moves = _moves(projected, SECOND_GATHER)
                head = projected.tiles_by_index[front.head_tile_index]
                self.assertTrue(all(move.source != head for move in moves))
                forecast = project_forward_gather(projected, moves, head, 0, 7)
                self.assertIsNotNone(forecast)
                assert forecast is not None
                self.assertEqual(127 - spent, forecast.launch_army)
                finish = [projected.GetTile(x, y) for x, y in (
                    (13, 19), (12, 19), (12, 18), (12, 17))]
                cost = calculate_route_cost(
                    projected, finish, 0, 7, hypothesized_general=finish[-1])
                self.assertEqual(5, cost)
                scenarios = [FfaKillScenario(
                    hypothesis_index=finish[-1].tile_index,
                    route_tile_indexes=tuple(tile.tile_index for tile in finish))]
                spent_front = replace(
                    front, position=position, enemy_standing=front.enemy_standing - spent)
                projections = certify_retained_head_continuation(
                    projected, spent_front, moves, scenarios, 0, 7, 39, 1, 170)
                self.assertIsNotNone(projections)
                assert projections is not None
                self.assertEqual(1, projections[0].margin)
                self.assertTrue(projections[0].certified)
                self.assertIsNone(certify_retained_head_continuation(
                    projected, spent_front, moves, scenarios, 0, 7, 39, 1, 169))
                self.assertIsNone(certify_retained_head_continuation(
                    projected, spent_front, [Move(head, projected.GetTile(14, 19))],
                    scenarios, 0, 7, 39, 1, 200))
                self.assertIsNone(certify_retained_head_continuation(
                    projected, spent_front, moves, [], 0, 7, 39, 1, 200))
                certificate = certify_kill(
                    projected.turn, len(moves), len(finish) - 1, forecast.launch_army,
                    cost, front.enemy_standing - spent, 39, 1)
                self.assertTrue(certificate.certified)
                self.assertEqual(1, certificate.margin)
                self.assertEqual(70, projected.turn - 100 + len(moves) + len(finish) - 1)

    def test_first_wave_certifies_34_turns_without_discarding_other_hypotheses(self) -> None:
        """A short first kill and the harder fallback are distinct obligations."""
        game_map, gather, _ = self._position()
        sources = [2] * 30 + [3] + [2] * 7
        first = certify_kill(
            100, 28, 6, gather.launch_army, 11, 46, 39, 1,
            enemy_ordinary_armies=sources)
        harder = certify_kill(
            100, 28, 7, gather.launch_army, 13, 46, 39, 1,
            enemy_ordinary_armies=sources)
        self.assertTrue(first.certified)
        self.assertEqual(1, first.margin)
        self.assertEqual(34, first.gather_turns + first.route_turns)
        self.assertFalse(harder.certified)
        self.assertEqual(-2, harder.margin)
        route = [game_map.GetTile(x, y) for x, y in (
            (17, 19), (16, 19), (15, 19), (14, 19), (13, 19), (12, 19), (12, 18))]
        scenarios = [FfaKillScenario(
            hypothesis_index=route[-1].tile_index,
            route_tile_indexes=tuple(tile.tile_index for tile in route))]
        projections = certify_gather_scenarios(
            game_map, gather, scenarios, 0, 7, 46, 39, 1, 134,
            enemy_ordinary_armies=sources)
        self.assertIsNotNone(projections)
        assert projections is not None
        self.assertTrue(projections[0].certified)
        self.assertEqual(1, projections[0].margin)
