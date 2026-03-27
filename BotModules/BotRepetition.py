import logbook

from base.client.map import Tile


class BotRepetition:
    @staticmethod
    def detect_repetition_at_all(bot, turns=4, numReps=2) -> bool:
        curTurn = bot._map.turn
        reps = 0
        prevMove = None
        for turn in range(int(curTurn - turns), curTurn):
            if turn in bot.history.move_history:
                for lastMove in bot.history.move_history[turn]:
                    if (
                            prevMove is not None
                            and turn not in bot.history.droppedHistory
                            and lastMove is not None
                            and (
                            (lastMove.dest == prevMove.source and lastMove.source == prevMove.dest)
                            or (lastMove.source == prevMove.source and lastMove.dest == prevMove.dest)
                    )
                    ):
                        reps += 1
                        if reps == numReps:
                            logbook.info(
                                f"  ---    YOOOOOOOOOO detected {reps} repetitions on {lastMove.source.x},{lastMove.source.y} -> {lastMove.dest.x},{lastMove.dest.y} in the last {turns} turns")
                            return True
                    prevMove = lastMove

        return False

    @staticmethod
    def detect_repetition(bot, move, turns=4, numReps=2):
        if move is None:
            return False
        curTurn = bot._map.turn
        reps = 0
        for turn in range(int(curTurn - turns), curTurn):
            if turn in bot.history.move_history:
                for oldMove in bot.history.move_history[turn]:
                    if turn not in bot.history.droppedHistory and (oldMove is not None
                                                                    and ((oldMove.dest == move.source and oldMove.source == move.dest)
                                                                         or (oldMove.source == move.source and oldMove.dest == move.dest))):
                        reps += 1
                        if reps == numReps:
                            logbook.info(
                                f"  ---    YOOOOOOOOOO detected {reps} repetitions on {move.source.x},{move.source.y} -> {move.dest.x},{move.dest.y} in the last {turns} turns")
                            return True
        return False

    @staticmethod
    def detect_repetition_tile(bot, tile: Tile, turns=6, numReps=2):
        if tile is None:
            return False
        curTurn = bot._map.turn
        reps = 0
        for turn in range(int(curTurn - turns), curTurn):
            if turn in bot.history.move_history:
                for oldMove in bot.history.move_history[turn]:
                    if turn not in bot.history.droppedHistory and oldMove is not None and oldMove.dest == tile:
                        reps += 1
                        if reps == numReps:
                            logbook.info(
                                f"  ---    YOOOOOOOOOO detected {reps} repetitions on {tile.x},{tile.y} in the last {turns} turns")
                            return True
        return False

    @staticmethod
    def move_half_on_repetition(bot, move, repetitionTurns, repCount=3):
        if BotRepetition.detect_repetition(bot, move, repetitionTurns, repCount):
            move.move_half = True
        return move

    @staticmethod
    def dropped_move(bot, fromTile=None, toTile=None, movedHalf=None):
        log = True
        lastMove = None
        if (bot._map.turn - 1) in bot.history.move_history:
            lastMove = bot.history.move_history[bot._map.turn - 1][0]
        if movedHalf is None and lastMove is not None:
            movedHalf = lastMove.move_half
        elif movedHalf is None:
            movedHalf = False
        if fromTile is None or toTile is None:
            if lastMove is None:
                if log:
                    logbook.info("DM: False because no last move")
                return False
            fromTile = lastMove.source
            toTile = lastMove.dest
        if fromTile.player != bot.general.player:
            if log:
                logbook.info("DM: False because another player captured fromTile so our move may or may not have been processed first")
            return False
        expectedFrom = 1
        expectedToDeltaOnMiss = 0
        if bot._map.is_army_bonus_turn:
            expectedFrom += 1
            if toTile.player != -1:
                expectedToDeltaOnMiss += 1
        if (fromTile.isCity or fromTile.isGeneral) and bot._map.is_city_bonus_turn:
            expectedFrom += 1
        if ((toTile.isCity and toTile.player != -1) or toTile.isGeneral) and bot._map.is_city_bonus_turn:
            expectedToDeltaOnMiss += 1
        dropped = True
        if not movedHalf:
            if fromTile.army <= expectedFrom:
                if log:
                    logbook.info("DM: False because fromTile.army {} <= expectedFrom {}".format(fromTile.army, expectedFrom))
                dropped = False
            else:
                if log:
                    logbook.info("DM: True because fromTile.army {} <= expectedFrom {}".format(fromTile.army, expectedFrom))
                dropped = True
        else:
            if abs(toTile.delta.armyDelta) != expectedToDeltaOnMiss:
                if log:
                    logbook.info("DM: False because movedHalf and toTile delta {} != expectedToDeltaOnMiss {}".format(abs(toTile.delta.armyDelta), expectedToDeltaOnMiss))
                dropped = False
            else:
                if log:
                    logbook.info("DM: True because movedHalf and toTile delta {} == expectedToDeltaOnMiss {}".format(abs(toTile.delta.armyDelta), expectedToDeltaOnMiss))
                dropped = True
        if dropped:
            bot.history.droppedHistory[bot._map.turn - 1] = True
        return dropped
