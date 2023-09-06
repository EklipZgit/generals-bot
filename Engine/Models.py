from __future__ import annotations

import typing

from DataModels import Move
from base.client.map import Tile


class SimTile(object):
    def __init__(self, sourceTile: Tile, army: int | None = None, player: int | None = None):
        self.source_tile = sourceTile
        self.army = sourceTile.army if army is None else army
        self.player = sourceTile.player if player is None else player

    def __str__(self):
        return f"[{self.source_tile.x},{self.source_tile.y} p{self.player} a{self.army}]"

    def __repr__(self):
        return str(self)


class ArmySimState(object):
    def __init__(
            self,
            remainingCycleTurns: int,
            simTiles: typing.Dict[Tile, SimTile] | None = None,
            friendlyLivingArmies: typing.Dict[Tile, SimTile] | None = None,
            enemyLivingArmies: typing.Dict[Tile, SimTile] | None = None
    ):
        if simTiles is None:
            simTiles = {}

        if friendlyLivingArmies is None:
            friendlyLivingArmies = {}

        if enemyLivingArmies is None:
            enemyLivingArmies = {}

        self.remaining_cycle_turns: int = remainingCycleTurns

        self.depth: int = 0

        self.tile_differential: int = 0
        """negative means they captured our tiles, positive means we captured theirs"""

        self.city_differential: int = 0
        """
        negative means they have that many more cities active than us, positive means we have more. 
        This is as of the CURRENT board state; bonuses owned is covered under the *city_control_turns fields.
        """

        self.captures_enemy: bool = False
        """if kill on enemy general appears guaranteed"""

        self.captured_by_enemy: bool = False
        """if kill against our general appears guaranteed"""

        self.can_force_repetition: bool = False
        """if we can force a repetition in our favor"""

        self.can_enemy_force_repetition: bool = False
        """if the enemy can force a repetition in their favor"""

        self.kills_all_friendly_armies: bool = False
        """If their armies kill friendly armies with 3+ army to spare (ignoring remaining tile capture)"""

        self.kills_all_enemy_armies: bool = False
        """If our armies kill all enemy armies with 3+ army to spare (ignoring remaining tile capture)"""

        self.sim_tiles: typing.Dict[Tile, SimTile] = simTiles
        """
        the set of tiles that have been involved in the scrim so far, tracking the current owner and army amount on them
        """

        self.controlled_city_turn_differential: int = 0
        """
        for cities in the scrim area, this is how many turns were controlled by a different player than the 
        current owner at sim start. 
        Positive means we gained city bonus overall, negative means enemy gained city bonus overall.
        """

        self.friendly_living_armies: typing.Dict[Tile, SimTile] = friendlyLivingArmies
        """
        Actively alive friendly armies at this point in the board state
        """

        self.enemy_living_armies: typing.Dict[Tile, SimTile] = enemyLivingArmies
        """
        Actively alive enemy armies at this point in the board state
        """

        self.friendly_skipped_move_count: int = 0
        """How many times friendly has no-opped already"""

        self.enemy_skipped_move_count: int = 0
        """How many times enemy has no-opped already"""

        self.friendly_move: Move | None = None
        """Friendly move made to reach this board state"""

        self.enemy_move: Move | None = None
        """Enemy move made to reach this board state"""

        self.prev_friendly_move: Move | None = None
        """Friendly move made before the last move to reach this board state, for detecting repetitions"""

        self.prev_enemy_move: Move | None = None
        """Enemy move made before the last move to reach this board state, for detecting repetitions"""

        self.repetition_count: int = 0

        self.parent_board: ArmySimState | None = None

        self.friendly_move_generator: typing.Callable[[ArmySimState], typing.List[Move | None]] = None
        """ Generate the friendly moves. MUST set this before running a scan. """

        self.enemy_move_generator: typing.Callable[[ArmySimState], typing.List[Move | None]] = None
        """ Generate the friendly moves. MUST set this before running a scan. """

        self.initial_differential: int = 0

    def get_child_board(self) -> ArmySimState:
        copy = ArmySimState(
            self.remaining_cycle_turns - 1,
            self.sim_tiles.copy(),
            self.friendly_living_armies.copy(),
            self.enemy_living_armies.copy()
        )
        copy.tile_differential = self.tile_differential
        copy.city_differential = self.city_differential
        copy.captures_enemy = self.captures_enemy
        copy.captured_by_enemy = self.captured_by_enemy
        copy.can_force_repetition = self.can_force_repetition
        copy.can_enemy_force_repetition = self.can_enemy_force_repetition
        copy.kills_all_friendly_armies = self.kills_all_friendly_armies
        copy.kills_all_enemy_armies = self.kills_all_enemy_armies
        copy.controlled_city_turn_differential = self.controlled_city_turn_differential
        copy.friendly_skipped_move_count = self.friendly_skipped_move_count
        copy.enemy_skipped_move_count = self.enemy_skipped_move_count
        copy.repetition_count = self.repetition_count
        copy.depth = self.depth + 1
        copy.friendly_move_generator = self.friendly_move_generator
        copy.enemy_move_generator = self.enemy_move_generator
        copy.initial_differential = self.initial_differential

        copy.prev_friendly_move = self.friendly_move
        copy.prev_enemy_move = self.enemy_move
        copy.parent_board = self

        return copy

    def get_moves_string(self):
        frMoves = []
        enMoves = []
        curState = self
        # intentionally while .parent_board isn't none to skip the top board, since it will show both moves as None
        while curState.parent_board is not None:
            frMoves.insert(0, curState.friendly_move)
            enMoves.insert(0, curState.enemy_move)
            curState = curState.parent_board

        fr = f'fr: {" -> ".join([str(move.dest).ljust(5) if move is not None else "None " for move in frMoves])}'
        en = f'en: {" -> ".join([str(move.dest).ljust(5) if move is not None else "None " for move in enMoves])}'

        return f"{fr}\r\n{en}"

    def __repr__(self):
        return f'{str(self)} [{self.get_moves_string()}]'

    def __str__(self):
        pieces = [f'(d{self.depth}) {self.get_econ_value():+d}']

        if self.kills_all_friendly_armies and self.kills_all_enemy_armies:
            pieces.append(f'x ')
        elif self.kills_all_friendly_armies:
            pieces.append(f'x-')
        elif self.kills_all_enemy_armies:
            pieces.append(f'x+')

        if self.can_enemy_force_repetition and self.can_force_repetition:
            pieces.append('REP')
        elif self.can_force_repetition:
            pieces.append('REP+')
        elif self.can_enemy_force_repetition:
            pieces.append('REP-')

        if self.captures_enemy:
            pieces.append('WIN')

        if self.captured_by_enemy:
            pieces.append('LOSS')

        return ' '.join(pieces)

    def calculate_value(self) -> typing.Tuple:
        econDiff = self.get_econ_value()
        return (
            # self.calculate_value_int(),  # todo hack...?
            self.captures_enemy,
            not self.captured_by_enemy,
            # self.can_force_repetition,
            # not self.can_enemy_force_repetition,
            econDiff,
            self.friendly_skipped_move_count,
            0 - self.enemy_skipped_move_count,
            self.kills_all_enemy_armies,
            not self.kills_all_friendly_armies,
        )

    def calculate_value_int(self) -> int:
        """Gets a (10x econ diff based) integer representation of the value of the board state. Used for Nashpy"""
        econDiff = self.get_econ_value() * 10
        if self.captures_enemy:
            econDiff += 10000
        if self.captured_by_enemy:
            econDiff -= 10000
        # skipped moves are worth 0.7 econ each
        econDiff += self.friendly_skipped_move_count * 5
        #enemy skipped moves are worth slightly less..? than ours?
        econDiff -= self.enemy_skipped_move_count * 5

        # if self.kills_all_enemy_armies:
        #     econDiff += 5
        # if self.kills_all_friendly_armies:
        #     econDiff -= 5

        return econDiff

    def get_econ_value(self) -> int:
        return (self.tile_differential
                + 25 * self.city_differential
                + self.controlled_city_turn_differential)  # TODO need to approximate the city differential for the scrim duration when pruning scrim?

    def generate_friendly_moves(self) -> typing.List[Move | None]:
        return self.friendly_move_generator(self)

    def generate_enemy_moves(self) -> typing.List[Move | None]:
        return self.enemy_move_generator(self)


class ArmySimResult(object):
    def __init__(self, resultState: ArmySimState | None = None):
        self.best_result_state: ArmySimState = resultState

        self.best_result_state_depth: int = 0

        self.net_economy_differential: int = 0

        self.expected_best_moves: typing.List[typing.Tuple[Move, Move]] = []
        """A list of (friendly, enemy) move tuples that the min-max best move board state is expected to take"""

        self.expected_moves_cache: ArmySimCache = None
        """
        A cache of the current and alternate move branches (for the enemy, since we know what 
        move we will make we dont care about our alternates), out to cacheDepth depth, 
        to be used on future turns to save time recalculating the full board tree from 
        scratch every turn. If the move wasn't in cache, then we didn't think it was remotely valuable.
        IF the opp makes a move outside this dict and our board evaluation goes down, then the analysis
        here was poor and should be logged and tests written to predict the better opponent move next time.
        """

    def calculate_value(self) -> typing.Tuple:
        return self.best_result_state.calculate_value_int(), False

    def __str__(self):
        return f'({self.net_economy_differential:+d}) {str(self.best_result_state)}'

    def __repr__(self):
        return f'{str(self)} [{self.calculate_value()}]'


class ArmySimCache(object):
    def __init__(
            self,
            friendlyMove: Move,
            enemyMove: Move,
            simState: ArmySimState,
            subTreeCache: typing.Dict[Tile, ArmySimCache] | None = None
    ):
        self.friendly_move: Move = friendlyMove
        self.enemy_move: Move = enemyMove
        self.sim_state: ArmySimState = simState
        self.move_tree_cache: typing.Dict[Tile, ArmySimCache] | None = subTreeCache

