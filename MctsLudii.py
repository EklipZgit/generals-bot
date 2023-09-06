"""
Converted to python from
https://github.com/Ludeme/LudiiExampleAI/blob/master/src/mcts/ExampleDUCT.java

"""
from __future__ import annotations

import logging
import math
import random
import time
import typing

from DataModels import Move
from Engine.Models import ArmySimState, ArmySimResult


#
# package mcts;
#
# import java.util.ArrayList;
# import java.util.HashMap;
# import java.util.List;
# import java.util.Map;
# import java.util.concurrent.ThreadLocalRandom;
#
# import game.Game;
# import main.collections.FastArrayList;
# import other.AI;
# import other.RankUtils;
# import other.action.Action;
# import other.context.Context;
# import other.move.Move;
# import utils.AIUtils;
#
# /**
#  * A simple example implementation of Decoupled UCT, for simultaneous-move
#  * games. Note that this example is primarily intended to show how to build
#  * a search tree for simultaneous-move games in Ludii. This implementation
#  * is by no means intended to be an optimal (in terms of optimisations /
#  * computational efficiency) implementation of the algorithm.
#  *
#  * Only supports deterministic, simultaneous-move games.
#  *
#  * @author Dennis Soemers
#  */
# public class ExampleDUCT extends AI
# {

class BoardMoves(object):
    def __init__(self, actions: typing.List[Move | None]):
        self.playerMoves: typing.List[Move | None] = actions
        """ Each players move at this board state. """

    def __hash__(self):
        return hash((self.playerMoves[0], self.playerMoves[1]))

    def __eq__(self, other):
        if isinstance(other, BoardMoves):
            return self.playerMoves[0] == other.playerMoves[0] and self.playerMoves[1] == other.playerMoves[1]
        return False

    def __str__(self):
        return f'[{"  ".join([str(m) for m in self.playerMoves])}]'


class MctsDUCT(object):
    def __init__(
            self,
            # player: int,
            logStuff: bool = True,
    ):
        self.player = 0
        self.should_log = logStuff
        self.iterations: int = 0
        self.trials_performed = 0
        self.backprop_iter = 0
        self.nodes_explored = 0

    def select_action(
            self,
            game: Game,
            context: Context,
            maxTime: float,
            maxIterations: int,
            # maxDepth: int,  # he didn't use this
    ) -> typing.Tuple[float, BoardMoves, ArmySimState]:

        # Start out by creating a new root node (no tree reuse in this example)
        root: MctsNode = MctsNode(None, context)

        # We'll respect any limitations on max seconds and max iterations (don't care about max depth)
        stopTime: float = time.perf_counter() + maxTime
        if maxTime <= 0.0:
            stopTime += 10000.0
        maxIts: int = maxIterations
        if maxIts < 0:
            maxIts = 1000000000

        numIterations: int = 0

        # Our main loop through MCTS iterations
        while (
            numIterations < maxIts                       # Respect iteration limit
            and time.perf_counter() < stopTime           # Respect time limit
            # and not self.wantsInterrupt()                # Respect GUI user clicking the pause button
        ):
            # Start in root node
            currentNode: MctsNode = root

            # Traverse tree
            while True:
                if currentNode.context.trial().over():
                    # We've reached a terminal state
                    break

                currentNode = self.select_or_expand_child_node(currentNode)

                if currentNode.totalVisitCount == 0:
                    # We've expanded a new node, time for playout!
                    break

            contextEnd: Context = currentNode.context

            if not contextEnd.trial().over():
                # Run a playout if we don't already have a terminal game state in node
                contextEnd = Context(contextEnd)  # clone the context

                # trial contains the moves played.
                trial = game.playout(
                    contextEnd,
                    ais=None,
                    thinkingTime=-1.0,
                    playoutMoveSelector=None,
                    maxNumBiasedActions=5,
                    # maxNumPlayoutActions=-1,  # -1 forces it to run until an actual game end state, infinite depth...?
                    maxNumPlayoutActions=25,  # -1 forces it to run until an actual game end state, infinite depth...?
                    randomGen=None  # ThreadLocalRandom.currentNode()
                )

                self.trials_performed += 1

            # This computes utilities for all players at the of the playout,
            # which will all be values in [-1.0, 1.0]
            utilities: typing.List[float] = MctsDUCT.get_player_utilities_n1_1(contextEnd.board_state)

            # Backpropagate utilities through the tree
            while currentNode is not None:
                if currentNode.totalVisitCount > 0:
                    # This node was not newly expanded in this iteration
                    for p in range(game.numPlayers):
                        # logging.info(f'backpropogating {str(contextEnd.board_state)} at t{contextEnd.turn} up through the tree to {str(currentNode.context.board_state)} t{currentNode.context.turn}')
                        currentNode.visitCounts[p][currentNode.lastSelectedMovesPerPlayer[p]] += 1
                        currentNode.scoreSums[p][currentNode.lastSelectedMovesPerPlayer[p]] += utilities[p]
                        self.backprop_iter += 1

                currentNode.totalVisitCount += 1
                currentNode = currentNode.parent

            # Increment iteration count
            numIterations += 1

        self.iterations = numIterations

        # Return the move we wish to play
        return self.finalMoveSelection(root)

    """
     * Selects child of the given "current" node according to UCB1 equation.
     * This method also implements the "Expansion" phase of MCTS, and creates
     * a new node if the given current node has unexpanded moves.
     *
     * @param current
     * @return Selected node (if it has 0 visits, it will be a newly-expanded node).
     """
    def select_or_expand_child_node(
            self,
            current: MctsNode,
    ) -> MctsNode:
        # Every player selects its move based on its own, decoupled statistics
        playerMoves: typing.List[BoardMoves] = []
        game: Game = current.context.game
        numPlayers: int = game.numPlayers

        for p in range(numPlayers):
            bestMove: BoardMoves | None = None
            bestValue: float = -10000000000000  # negative inf
            twoParentLog: float = 2.0 * math.log(max(1, current.totalVisitCount))
            numBestFound: int = 0

            for i, move in enumerate(current.legalMovesPerPlayer[p]):
                exploit: float = 1.0
                if current.visitCounts[p][i] != 0:
                    exploit = current.scoreSums[p][i] / current.visitCounts[p][i]

                explore: float = math.sqrt(twoParentLog / max(1, current.visitCounts[p][i]))

                ucb1Value: float = exploit + explore

                if ucb1Value > bestValue:
                    bestValue = ucb1Value
                    bestMove = move
                    numBestFound = 1
                    current.lastSelectedMovesPerPlayer[p] = i
                elif ucb1Value == bestValue:
                    numBestFound += 1
                    if self.get_rand_int() % numBestFound == 0:
                        # this case implements random tie-breaking
                        bestMove = move
                        current.lastSelectedMovesPerPlayer[p] = i

            playerMoves.append(bestMove)

        combinedMove: BoardMoves = BoardMoves([playerMoves[0].playerMoves[0], playerMoves[1].playerMoves[1]])

        node: MctsNode | None = current.children.get(combinedMove, None)
        if node is not None:
            logging.info(f'existing node t{node.context.turn} board move {str(combinedMove)}')
            # We already have a node for this combination of moves
            return node
        else:
            # We need to create a new node for this combination of moves
            # TODO ?
            # combinedMove.setMover(numPlayers + 1)

            context: Context = Context(current.context)  # clone
            context.game.apply(context, combinedMove)

            newNode: MctsNode = MctsNode(current, context)
            current.children[combinedMove] = newNode
            self.nodes_explored += 1
            logging.info(f'expanding new child node t{context.turn} board move {str(combinedMove)} state {str(context.board_state)}')
            return newNode

    """
     * Selects the move we wish to play using the "Robust Child" strategy
     * (meaning that we play the move leading to the child of the root node
     * with the highest visit count).
     *
     * @param rootNode
     * @return
     """
    def finalMoveSelection(
            self,
            rootNode: MctsNode
    ) -> typing.Tuple[float, BoardMoves, ArmySimState]:
        bestMove: BoardMoves | None = None
        bestAvgScore: float = -10000000000  # neg inf
        numBestFound: int = 0
        bestState = None

        for i, move in enumerate(rootNode.legalMovesPerPlayer[self.player]):
            sumScores: float = rootNode.scoreSums[self.player][i]
            visitCount: int = rootNode.visitCounts[self.player][i]
            avgScore: float = -1.0
            if visitCount != 0:
                avgScore = sumScores / visitCount

            if avgScore > bestAvgScore:
                logging.info(f'new best move had \r\n'
                             f'   avgScore {avgScore} > bestAvgScore {bestAvgScore}, \r\n'
                             f'   new bestMove {str(move)} > old bestMove {str(bestMove)}, \r\n'
                             f'   new bestState {str(rootNode.context.board_state)}')
                bestAvgScore = avgScore
                bestMove = move
                bestState = rootNode.context.board_state
                numBestFound = 1
            elif avgScore == bestAvgScore:
                numBestFound += 1
                logging.info(f'TIEBREAK move had \r\n'
                             f'   avgScore {avgScore} > bestAvgScore {bestAvgScore}, \r\n'
                             f'   new bestMove {str(move)} > old bestMove {str(bestMove)}, \r\n'
                             f'   new bestState {str(rootNode.context.board_state)}')
                if self.get_rand_int() % numBestFound == 0:
                    logging.info('  (won tie break)')
                    # this case implements random tie-breaking
                    bestMove = move
                    bestState = rootNode.context.board_state
                else:
                    logging.info('  (lost tie break)')

        return bestAvgScore, bestMove, bestState

    def get_rand_int(self):
        return random.randrange(10000000)

    @staticmethod
    def get_player_utilities_n1_1(boardState: ArmySimState) -> typing.List[float]:
        """
        Returns a list of floats (per player) between 1.0 and -1.0 where winning player is 1.0 and losing player is -1.0 and all players in between are in the range.

        @param boardState:
        @return:
        """
        netDifferential = boardState.get_econ_value() - boardState.initial_differential
        # # TODO should wins/losses be the 1.0/-1.0 extremes and just econ be much more 'middle'...?
        # econValueNeg100To100 = min(100.0, max(-100.0, netDifferential))
        # compressed = econValueNeg100To100 / 100.0
        # return [compressed, 0 - compressed]

        val = 0.0
        if netDifferential > 0:
            # val = 0.7
            val = 1.0
        if netDifferential < 0:
            # val = -0.7
            val = -1.0
        if netDifferential < -200:
            val = -1.0
        if netDifferential > 200:
            val = 1.0

        return [val, 0 - val]


class MctsNode(object):
    def __init__(
            self,
            parent: MctsNode | None,
            context: Context,
    ):
        self.parent: MctsNode | None = parent
        """ Our parent node """

        self.context: Context = context
        """ This objects contains the game state for this node (this is why we don't support stochastic games) """

        self.totalVisitCount: int = 0
        """ Total visit count going through this node """

        self.children: typing.Dict[BoardMoves, MctsNode] = {}
        """ Mapping from lists of actions (one per active player) to child nodes """

        game: Game = context.game
        numPlayers: int = game.numPlayers

        self.legalMovesPerPlayer: typing.List[typing.List[BoardMoves] | None] = [None for p in range(numPlayers)]
        """ For every player index, a list of legal moves in this node """

        allLegalMoves: typing.List[BoardMoves] = context.get_legal_moves()

        # For every active player in this state, compute their legal moves
        for p in range(numPlayers):
            # TODO IF WE NEED TO INCLUDE MORE THAN TWO PLAYERS AT ONCE...?
            # moves = AIUtils.extractMovesForMover(allLegalMoves, p)
            # TODO this might actually be intended to be JUST the players move options, not the pair of every move/response...?
            self.legalMovesPerPlayer[p] = allLegalMoves

        self.visitCounts: typing.List[typing.List[int]] = [[0 for move in playerMoves] for playerMoves in self.legalMovesPerPlayer]
        """ For every player, for every child move, a visit count """

        self.scoreSums: typing.List[typing.List[float]] = [[0.0 for move in playerMoves] for playerMoves in self.legalMovesPerPlayer]
        """ For every player, for every child move, a sum of backpropagated scores """

        self.lastSelectedMovesPerPlayer: typing.List[int] = [0 for p in range(numPlayers)]
        """
        For every player, the index of the legal move we selected for
        that player in this node in the last (current) MCTS iteration.
        """


class Context(object):
    def __init__(self, toClone: Context | None = None):
        self.turn: int = 0
        self.game: Game | None = None
        self.engine = None  # untyped to avoid circular refs for now
        self.board_state: ArmySimState | None = None
        self.frMoves: typing.List[Move | None] = None
        self.enMoves: typing.List[Move | None] = None
        self._trial: Trial | None = None
        if toClone is not None:
            # TODO this might need to be raw clone not child_board, dunno yet.
            # self.frMoves = toClone.frMoves
            # self.enMoves = toClone.enMoves
            self.board_state = toClone.board_state.get_child_board()
            self.engine = toClone.engine
            self.game = toClone.game
            self.turn = toClone.turn

    def set_initial_board_state(self, engine, state: ArmySimState, game: Game, turn: int):
        self.board_state = state
        self.engine = engine
        self.turn = turn
        self.game = game

    def trial(self) -> Trial:
        if self._trial is None:
            self._trial = Trial(self)
        return self._trial

    def get_legal_moves(self) -> typing.List[BoardMoves]:
        self.frMoves: typing.List[Move | None] = self.board_state.generate_friendly_moves()

        self.enMoves: typing.List[Move | None] = self.board_state.generate_enemy_moves()

        moves: typing.List[BoardMoves] = []
        for frIdx, frMove in enumerate(self.frMoves):
            for enIdx, enMove in enumerate(self.enMoves):
                moves.append(BoardMoves([frMove, enMove]))

        return moves


class Trial(object):
    def __init__(self, context: Context):
        self.context: Context = context
        self.moves: typing.List[BoardMoves] = []  # MoveSequence? https://github.com/Ludeme/Ludii/blob/master/Core/src/other/move/MoveSequence.java#L20
        """ The moves that were played to reach the current context state. """

    def over(self) -> bool:
        if self.context.board_state.kills_all_enemy_armies and self.context.board_state.kills_all_friendly_armies:
            return True
        if self.context.board_state.captures_enemy or self.context.board_state.captured_by_enemy:
            return True
        # if self.context.board_state.
        return False

    def numMoves(self) -> int:
        return len(self.moves)


class Game(object):
    def __init__(self):
        self.numPlayers: int = 2
        self.rollout_expansions = 0
        self.biased_rollout_expansions: int = 0

    def playout(
            self,
            context: Context,
            ais: typing.List[None] | None,
            thinkingTime: float,
            playoutMoveSelector: typing.Callable[[ArmySimState, typing.List[BoardMoves]], BoardMoves] | None,
            maxNumBiasedActions: int,
            maxNumPlayoutActions: int,
            randomGen: None
    ) -> Trial:
        """
        TD: Run a rollout....?
        Runs a rollout.
        DOES modify context...?
        Runs biased moves until it runs out of the max number of biased moves, then runs random moves...?

        @param context:
        @param ais: lol
        @param thinkingTime:
        @param playoutMoveSelector:
        @param maxNumBiasedActions:
        @param maxNumPlayoutActions: limits the depth of the rollout from THIS point, regardless of how deep we already are...?
        @param randomGen:
        @return:
        """

        # TODO should maybe turn this check into an assertion? or always run it???
        # if (!context.haveStarted())
        #     System.err.println("Didn't start!");

        # final Random rng = (randomGen != null) ? randomGen : ThreadLocalRandom.current();

        trial: Trial = context.trial()
        numStartMoves: int = trial.numMoves()
        iter = 0
        while True:
            self.rollout_expansions += 1
            # logging.info(f'playouting {str(trial.context.board_state)} at t{trial.context.turn}')
            if (
                trial.over()
                or 0 <= maxNumPlayoutActions <= trial.numMoves() - numStartMoves
            ):
                break

            numAllowedActions: int = 0
            numAllowedBiasedActions: int = 0

            if maxNumPlayoutActions >= 0:
                numAllowedActions = max(0, maxNumPlayoutActions - (trial.numMoves() - numStartMoves))
            else:
                numAllowedActions = maxNumPlayoutActions

            if maxNumBiasedActions >= 0:
                numAllowedBiasedActions = max(0, maxNumBiasedActions - (trial.numMoves() - numStartMoves))
            else:
                numAllowedBiasedActions = maxNumBiasedActions

            if numAllowedBiasedActions <= 0 and random.randrange(10) <= 0:
                trial = self.playout_random_move(trial)
            else:
                trial = self.playout_biased_move(trial, playoutMoveSelector)
                # numAllowedBiasedActions -= 1
            iter += 1
            if iter > 50:
                logging.info(f'inf looping? {str(trial.context.board_state)}')
            if iter > 100:
                raise AssertionError('wtf, infinite looped?')

        return trial

    def apply(self, context: Context, combinedMove: BoardMoves):
        nextTurn = context.turn + 1
        context.board_state = context.engine.get_next_board_state(nextTurn, context.board_state, combinedMove.playerMoves[0], combinedMove.playerMoves[1])
        context.turn = nextTurn

    def playout_random_move(self, trial: Trial) -> Trial:
        chosen = random.choice(trial.context.get_legal_moves())
        self.apply(trial.context, chosen)
        trial.moves.append(chosen)
        return trial

    def playout_biased_move(
            self,
            trial: Trial,
            playoutMoveSelector: typing.Callable[[ArmySimState, typing.List[BoardMoves]], BoardMoves] | None,
    ) -> Trial:
        c = trial.context
        bs = c.board_state
        e = c.engine
        c.get_legal_moves()
        payoffs = [
            [
                ArmySimResult(e.get_next_board_state(c.turn + 1, bs, frMove, enMove))
                for enMove in c.enMoves
            ]
            for frMove in c.frMoves
        ]

        chosenRes = e.get_comparison_based_expected_result_state(
            bs,
            [x for x in enumerate(c.frMoves)],
            [x for x in enumerate(c.enMoves)],
            payoffs
        )

        boardMove = BoardMoves([chosenRes.best_result_state.friendly_move, chosenRes.best_result_state.enemy_move])
        self.apply(trial.context, boardMove)
        trial.moves.append(boardMove)
        self.biased_rollout_expansions += 1

        return trial
