from Models import Move
from bot_ek0x45 import EklipZBot


class UnfairPlayBot(EklipZBot):
    def __init__(self, playOpening: bool = False, expandRound2: bool = False, gatherToGenRound: int = -1, launchAttack: bool = False, surrenderTurn: int = 2000, shouldBlob: bool = False):
        super().__init__()
        self.play_opening: bool = playOpening
        self.expand_round_2: bool = expandRound2
        self.gather_to_gen_round: int = gatherToGenRound
        self.launch_attack: bool = launchAttack
        self.surrender_turn: int = surrenderTurn
        self.should_blob: bool = shouldBlob

    def pick_move_after_prep(self, is_lag_move=False) -> Move | None:
        curRound = self.get_round(self._map.turn)

        if self.play_opening and self._map.turn < 50:
            return super().pick_move_after_prep(is_lag_move)

        if self.expand_round_2 and self._map.turn < 50:
            leafMove = self.find_leaf_move(self.leafMoves)
            if leafMove is not None:
                return leafMove

        if self.launch_attack:
            move, path = self.check_for_king_kills_and_races(threat=None, force=True)
            if move is not None:
                return move
            if path is not None:
                return path.get_first_move()

            if curRound < self.gather_to_gen_round:
                return super().pick_move_after_prep(is_lag_move)

        if curRound == self.gather_to_gen_round:
            turnsLeft = self._map.remainingCycleTurns
            move, val, turns, nodes = self.get_gather_to_target_tiles([self.general], 0.1, turnsLeft)
            return move

        if self._map.turn >= self.surrender_turn:
            self.surrender_func()

        if self.should_blob:
            leafMove = self.find_leaf_move(self.leafMoves)
            if leafMove is not None:
                return leafMove

        # if nothing else, just AFK gathering to general?
        move, val, turns, nodes = self.get_gather_to_target_tiles([self.general], 0.1, self._map.remainingCycleTurns)
        return move

    def get_round(self, turn: int):
        return (turn // 50) + 1
