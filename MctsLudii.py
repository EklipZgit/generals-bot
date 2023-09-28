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
from enum import Enum

from numba import jit, float32, int32

import numpy
from scipy.special import expit

from DataModels import Move
from Engine.ArmyEngineModels import ArmySimState, ArmySimResult, ArmySimEvaluationParams
from PerformanceTimer import PerformanceTimer
from base.client.map import MapBase


#
# A simple example implementation of Decoupled UCT, for simultaneous-move
# games. Note that this example is primarily intended to show how to build
# a search tree for simultaneous-move games in Ludii. This implementation
# is by no means intended to be an optimal (in terms of optimisations /
# computational efficiency) implementation of the algorithm.
#
# Only supports deterministic, simultaneous-move games.
#
# @author Dennis Soemers, translated to python by Travis Drake

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

    def __repr__(self):
        return str(self)


class MoveSelectionFunction(Enum):
    RobustChild = 1
    MaxAverageValue = 2


class MctsDUCT(object):
    def __init__(
            self,
            # player: int,
            logStuff: bool = True,
            nodeSelectionFunction: MoveSelectionFunction = MoveSelectionFunction.RobustChild,
    ):
        self.logAll: bool = False
        self.player = 0
        """This isn't the actual player int from generals game, this is just the playing-players index into the players array. The 'bot' is always the first player from MCTS's point of view."""

        self._iterations: int = 0
        self._trials_performed: int = 0
        self._backprop_iter: int = 0
        self._nodes_explored: int = 0
        self.eval_params: ArmySimEvaluationParams = ArmySimEvaluationParams()

        self.should_log = logStuff
        self.reset()

        self.offset_initial_differential: bool = True

        self.biased_playouts_allowed_per_trial: int = 7  # 7 beat 4 on 0.5 ratio 262-236
        self.biased_move_ratio_while_available: float = 0.4

        # 4 outperformed 6 in 52-37 games, but might've been the flipped a-b
        # after fixing a-b and other tuning, 6 beat 4 28-21
        self.total_playout_move_count: int = 8
        self.min_random_playout_moves_initial: int = 1
        self.allow_random_repetitions: bool = True
        self.allow_random_no_ops: bool = True
        self.disable_positional_win_detection_in_rollouts: bool = True  # TODO try turning this back off again soon
        self.final_playout_estimation_depth: int = 0

        self.exploit_factor: float = 1.0
        self.explore_factor: float = 1.05
        self.utility_compression_ratio: float = 0.004

        # dropped, this performed horrible on False so algo is definitely implemented correct.
        # self.skip_first_result_backpropogation: bool = True

        # todo verify UCB1-tuned implementation matches
        #  https://github.com/Yelp/MOE/blob/master/moe/bandit/ucb/ucb1_tuned.py#L78-L79
        #  https://www.turing.com/kb/guide-on-upper-confidence-bound-algorithm-in-reinforced-learning#:~:text=is%20called%20%E2%80%98C%E2%80%99.-,UCB%2D1%20Tuned,-For%20UCB1%2DTuned

        self._node_selection_function: typing.Callable[[MctsNode], typing.Tuple[float, BoardMoves]] = self._get_selection_func_from_enum(nodeSelectionFunction)

    def reset(self):
        self._iterations: int = 0
        self._trials_performed: int = 0
        self._backprop_iter: int = 0
        self._nodes_explored: int = 0

    def set_node_selection_function(self, selectionFunc: MoveSelectionFunction):
        self._node_selection_function = self._get_selection_func_from_enum(selectionFunc)

    def select_action(
            self,
            game: Game,
            context: Context,
            maxTime: float,
            maxIterations: int,
            # maxDepth: int,  # he didn't use this
    ) -> MctsEngineSummary:
        # Start out by creating a new root node (no tree reuse in this example)
        root: MctsNode = MctsNode(None, context)

        # We'll respect any limitations on max seconds and max iterations (don't care about max depth)
        startTime = time.perf_counter()
        stopTime: float = startTime + maxTime
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
                if currentNode.context.trial.over():
                    # We've reached a terminal state
                    break

                currentNode = self.select_or_expand_child_node(currentNode)

                if currentNode.totalVisitCount == 0:
                    # We've expanded a new node, time for playout!
                    break

            contextEnd: Context = currentNode.context

            if not contextEnd.trial.over():
                # Run a playout if we don't already have a terminal game state in node
                contextEnd = Context(contextEnd)  # clone the context

                # trial contains the moves played.
                trial = game.playout(
                    contextEnd,
                    playoutMoveSelector=None,
                    maxNumBiasedActions=self.biased_playouts_allowed_per_trial,
                    biasedMoveRatio=self.biased_move_ratio_while_available,
                    # maxNumPlayoutActions=-1,  # -1 forces it to run until an actual game end state, infinite depth...?
                    maxNumPlayoutActions=self.total_playout_move_count,  # -1 forces it to run until an actual game end state, infinite depth...?
                    minRandomInitialMoves=self.min_random_playout_moves_initial,
                )
                if self.logAll:
                    logging.info(f'  trial for node t{currentNode.context.turn} {str(currentNode.context.board_state)} resulted in \r\n    ctxEnd t{contextEnd.turn} {str(contextEnd.board_state)} \r\n    (trial t{trial.context.turn} {str(trial.context.board_state)})')

                self._trials_performed += 1

            # This computes utilities for all players at the of the playout,
            # which will all be values in [-1.0, 1.0]
            utilities: typing.List[float] = self.get_player_utilities_n1_1(contextEnd.board_state)
            if self.logAll:
                logging.info(f'boardState {str(contextEnd.board_state)} compressed to {", ".join([f"{compressed:.4f}" for compressed in utilities])}')

            # Backpropagate utilities through the tree
            while currentNode is not None:
                if currentNode.totalVisitCount > 0:
                    # This node was not newly expanded in this iteration
                    for p in range(game.numPlayers):
                        # logging.info(f'backpropogating {str(contextEnd.board_state)} at t{contextEnd.turn} up through the tree to {str(currentNode.context.board_state)} t{currentNode.context.turn}')
                        lastSelMove = currentNode.lastSelectedMovesPerPlayer[p]
                        currentNode.visitCounts[p][lastSelMove] += 1
                        currentNode.scoreSums[p][lastSelMove] += utilities[p]

                self._backprop_iter += 1
                currentNode.totalVisitCount += 1
                currentNode = currentNode.parent

            # Increment iteration count
            numIterations += 1

        duration = time.perf_counter() - startTime
        self._iterations = numIterations

        # Return the move we wish to play
        summary = self.get_best_moves(root)
        summary.duration = duration
        summary.iterations = self._iterations
        summary.trials_performed = self._trials_performed
        summary.backprop_iter = self._backprop_iter
        summary.nodes_explored = self._nodes_explored
        summary.rollout_expansions = root.context.game._rollout_expansions
        summary.biased_rollout_expansions = root.context.game._biased_rollout_expansions

        return summary

    def bench_random_stuff(self):
        # for i in range(-100, 100, 10):
        #     logging.info(f'fast_tanh {i} = {MctsDUCT.fast_tanh_jit(i)}')
        for i in range(-1000, 1000, 10):
            logging.info(f'fast_tanh_scaled {i} = {MctsDUCT.fast_tanh_scaled_jit(i, self.utility_compression_ratio)}')
        logging.info(f'fast_tanh_scaled {10000} = {MctsDUCT.fast_tanh_scaled_jit(10000, self.utility_compression_ratio)}')
        logging.info(f'fast_tanh_scaled {-10000} = {MctsDUCT.fast_tanh_scaled_jit(-10000, self.utility_compression_ratio)}')

        for i in range(-100, 100, 10):
            logging.info(f'fast_sigmoid {i} = {MctsDUCT.fast_sigmoid_jit(i)}')
        for i in range(-100, 100, 10):
            logging.info(f'expit {i} = {expit([i])[0]}')

        testRange = numpy.arange(-10000.0, 10000.0, 0.01)
        timer = PerformanceTimer()
        with timer.begin_move(0):
            with timer.begin_move_event('wtf?'):
                tanhs = [MctsDUCT.fast_tanh(i) for i in testRange]
            with timer.begin_move_event('sigmoids'):
                sigmoids = [MctsDUCT.fast_sigmoid(i) for i in testRange]
            with timer.begin_move_event('expits'):
                expits = [expit([i])[0] for i in testRange]

            with timer.begin_move_event('tanhs_jit'):
                tanhJits = [MctsDUCT.fast_tanh_jit(i) for i in testRange]
            with timer.begin_move_event('tanhs_scaled_jit'):
                tanhJitScaleds = [MctsDUCT.fast_tanh_scaled_jit(i, self.utility_compression_ratio) for i in testRange]
            with timer.begin_move_event('sigmoids_jit'):
                sigmoidJits = [MctsDUCT.fast_sigmoid_jit(i) for i in testRange]
            with timer.begin_move_event('tanhs'):
                tanhs = [MctsDUCT.fast_tanh(i) for i in testRange]

        for entry in sorted(timer.current_move.event_list, key=lambda e: e.get_duration(), reverse=True):
            logging.info(f'{entry.get_duration():.3f} {entry.event_name}'.lstrip('0'))

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
        playerMoves: typing.List[Move | None] = []
        game: Game = current.context.game
        numPlayers: int = game.numPlayers

        twoParentLog: float = MctsDUCT.two_parent_log_jit(self.explore_factor, current.totalVisitCount)

        for p in range(numPlayers):
            bestMove: Move | None = None
            bestValue: float = -1000000000  # negative inf
            numBestFound: int = 0

            for i, move in enumerate(current.legalMovesPerPlayer[p]):
                exploit: float = 1.0
                curMoveVisits = current.visitCounts[p][i]
                curMoveSumScore = -10000
                if curMoveVisits != 0:
                    curMoveSumScore = current.scoreSums[p][i]
                    exploit = curMoveSumScore / curMoveVisits
                explore: float = MctsDUCT.two_parent_log_explore(twoParentLog, childVisitCount=curMoveVisits)

                ucb1Value: float = exploit + explore

                if self.logAll:
                    logging.info(f't{current.context.turn} p{p} move {str(move)}, oit {exploit:.3f}, ore {explore:.3f}, ucb1 {ucb1Value:.3f} vs {bestValue:.3f}')
                if ucb1Value >= bestValue:
                    if ucb1Value == bestValue:
                        numBestFound += 1
                        if self.get_rand_int() % numBestFound == 0:
                            # this case implements random tie-breaking
                            bestMove = move
                            current.lastSelectedMovesPerPlayer[p] = i
                    else:
                        bestValue = ucb1Value
                        bestMove = move
                        numBestFound = 1
                        current.lastSelectedMovesPerPlayer[p] = i

            playerMoves.append(bestMove)
        frMove = playerMoves[0]
        enMove = playerMoves[1]
        combinedMove: BoardMoves = BoardMoves([frMove, enMove])

        node: MctsNode | None = current.children.get(combinedMove, None)
        if node is not None:
            if self.logAll:
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
            self._nodes_explored += 1

            if self.logAll:
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
    def get_best_moves(
            self,
            rootNode: MctsNode
    ) -> MctsEngineSummary:
        logging.info('MCTS BUILDING BEST MOVE CHOICES')

        summary = MctsEngineSummary(
            rootNode,
            selectionFunc=self._node_selection_function,
            game=rootNode.context.game,
            finalPlayoutEstimationDepth=self.final_playout_estimation_depth
        )
        return summary

    def robust_child_selection_func(self, node: MctsNode) -> typing.Tuple[float, BoardMoves]:
        playerMoves: typing.List[Move | None] = []
        playerScores: typing.List[float] = []
        playerVisitCounts: typing.List[int] = []

        for p, pMoves in enumerate(node.legalMovesPerPlayer):
            bestMove: BoardMoves | None = None
            bestVisitCount: int = -1
            numBestFound: int = 0
            bestAvgScore: float = -10000  # neg inf

            for i, move in enumerate(pMoves):
                sumScores: float = node.scoreSums[p][i]
                visitCount: int = node.visitCounts[p][i]
                avgScore: float = -10.0
                if visitCount != 0:
                    avgScore = sumScores / visitCount

                logging.info(f'p{p} t{node.context.turn} move {str(move)} visits {visitCount} score {avgScore:.3f}')

            for i, move in enumerate(pMoves):
                sumScores: float = node.scoreSums[p][i]
                visitCount: int = node.visitCounts[p][i]
                avgScore: float = -10.0
                if visitCount != 0:
                    avgScore = sumScores / visitCount

                if visitCount > bestVisitCount:
                    logging.info(f'p{p} t{node.context.turn} new best move {str(move)} had \r\n'
                                 f'   visitCount {visitCount} > bestVisitCount {bestVisitCount}, \r\n'
                                 f'   avgScore {avgScore:.3f} vs bestAvgScore {bestAvgScore:.3f}, \r\n'
                                 f'   new bestMove {str(move)} > old bestMove {str(bestMove)}, \r\n'
                                 f'   new bestState {str(node.context.board_state)}')
                    bestVisitCount = visitCount
                    bestMove = move
                    bestAvgScore = avgScore
                    numBestFound = 1
                elif visitCount == bestVisitCount:
                    if avgScore > bestAvgScore:
                        logging.info(f'p{p} t{node.context.turn} visit tie - new best move {str(move)} had \r\n'
                                     f'   avgScore {avgScore:.3f} vs bestAvgScore {bestAvgScore:.3f}, \r\n'
                                     f'   visitCount {visitCount} > bestVisitCount {bestVisitCount}, \r\n'
                                     f'   new bestMove {str(move)} > old bestMove {str(bestMove)}, \r\n'
                                     f'   new bestState {str(node.context.board_state)}')
                        bestVisitCount = visitCount
                        bestMove = move
                        bestAvgScore = avgScore
                        numBestFound = 1
                    elif avgScore == bestAvgScore:
                        numBestFound += 1

                        logging.info(f'p{p} t{node.context.turn} TIEBREAK move {str(move)} had \r\n'
                                     f'   visitCount {visitCount} == bestVisitCount {bestVisitCount}, \r\n'
                                     f'   avgScore {avgScore:.3f} vs bestAvgScore {bestAvgScore:.3f}, \r\n'
                                     f'   move {str(move)} vs bestMove {str(bestMove)}, \r\n'
                                     f'   state {str(node.context.board_state)}')
                        if self.get_rand_int() % numBestFound == 0:
                            logging.info('  (won tie break)')
                            # this case implements random tie-breaking
                            bestMove = move
                            bestAvgScore = avgScore
                        else:
                            logging.info('  (lost tie break)')
            logging.info(f'p{p} t{node.context.turn} best move {str(bestMove)} had \r\n'
                         f'   visitCount {bestVisitCount}, \r\n'
                         f'   bestAvgScore {bestAvgScore:.3f}')
            playerMoves.append(bestMove)
            playerScores.append(bestAvgScore)
            playerVisitCounts.append(bestVisitCount)

        boardMove = BoardMoves(playerMoves)

        logging.info(f't{node.context.turn} COMBINED move {str(boardMove)} had \r\n'
                     f'   visitCounts {str(playerVisitCounts)}, \r\n'
                     f'   bestAvgScores {str([f"{s:.3f}" for s in playerScores])}')
        return playerScores[0], boardMove

    def maximum_average_value_selection_func(self, node: MctsNode) -> typing.Tuple[float, BoardMoves]:
        playerMoves: typing.List[Move | None] = []
        playerScores: typing.List[float] = []
        playerVisitCounts: typing.List[int] = []

        for p, pMoves in enumerate(node.legalMovesPerPlayer):
            bestMove: BoardMoves | None = None
            bestVisitCount: int = -1
            numBestFound: int = 0
            bestAvgScore: float = -10000  # neg inf

            for i, move in enumerate(pMoves):
                sumScores: float = node.scoreSums[p][i]
                visitCount: int = node.visitCounts[p][i]
                avgScore: float = -10.0
                if visitCount != 0:
                    avgScore = sumScores / visitCount

                logging.info(f'p{p} t{node.context.turn} move {str(move)} visits {visitCount} score {avgScore:.3f}')

            for i, move in enumerate(pMoves):
                sumScores: float = node.scoreSums[p][i]
                visitCount: int = node.visitCounts[p][i]
                avgScore: float = -10.0
                if visitCount != 0:
                    avgScore = sumScores / visitCount

                if avgScore > bestAvgScore:
                    logging.info(f'p{p} t{node.context.turn} visit tie - new best move {str(move)} had \r\n'
                                 f'   avgScore {avgScore:.3f} vs bestAvgScore {bestAvgScore:.3f}, \r\n'
                                 f'   visitCount {visitCount} > bestVisitCount {bestVisitCount}, \r\n'
                                 f'   new bestMove {str(move)} > old bestMove {str(bestMove)}, \r\n'
                                 f'   new bestState {str(node.context.board_state)}')
                    bestVisitCount = visitCount
                    bestMove = move
                    bestAvgScore = avgScore
                    numBestFound = 1
                elif avgScore == bestAvgScore:
                    numBestFound += 1

                    logging.info(f'p{p} t{node.context.turn} TIEBREAK move {str(move)} had \r\n'
                                 f'   avgScore {avgScore:.3f} vs bestAvgScore {bestAvgScore:.3f}, \r\n'
                                 f'   visitCount {visitCount} == bestVisitCount {bestVisitCount}, \r\n'
                                 f'   move {str(move)} vs bestMove {str(bestMove)}, \r\n'
                                 f'   state {str(node.context.board_state)}')
                    if self.get_rand_int() % numBestFound == 0:
                        logging.info('  (won tie break)')
                        # this case implements random tie-breaking
                        bestMove = move
                        bestAvgScore = avgScore
                    else:
                        logging.info('  (lost tie break)')
            logging.info(f'p{p} t{node.context.turn} best move {str(bestMove)} had \r\n'
                         f'   visitCount {bestVisitCount}, \r\n'
                         f'   bestAvgScore {bestAvgScore:.3f}')
            playerMoves.append(bestMove)
            playerScores.append(bestAvgScore)
            playerVisitCounts.append(bestVisitCount)

        boardMove = BoardMoves(playerMoves)

        logging.info(f't{node.context.turn} COMBINED move {str(boardMove)} had \r\n'
                     f'   visitCounts {str(playerVisitCounts)}, \r\n'
                     f'   bestAvgScores {str([f"{s:.3f}" for s in playerScores])}')
        return playerScores[0], boardMove

    def get_rand_int(self):
        return random.randrange(10000000)

    @staticmethod
    def fast_tanh(x: float) -> float:
        """Returns between -1 and 1, where -3 as input is very close to -1 already and 3 is very close to 1 output already. Somehow this is faster than the jit'd version...?"""
        return x / (1 + abs(x))

    @staticmethod
    def fast_sigmoid(x: float) -> float:
        """compresses stuff to stuff."""
        return x / (2 * ((x < 0.0) * -x + (x >= 0.0) * x) + 2) + 0.5

    @staticmethod
    @jit(float32(float32), nopython=True)
    def fast_tanh_jit(x: float) -> float:
        """Returns between -1 and 1, where -3 as input is very close to -1 already and 3 is very close to 1 output already."""
        return x / (1 + abs(x))

    @staticmethod
    @jit(float32(float32, float32), nopython=True)
    def fast_tanh_scaled_jit(x: float, scaleFactor: float) -> float:
        """Returns between -1 and 1, where -3 as input is very close to -1 already and 3 is very close to 1 output already."""
        x = x * scaleFactor
        return x / (1.0 + abs(x))

    # @staticmethod
    # @jit(float32(float32, float32), nopython=True)
    # def reverse_fast_tanh_scaled_jit(x: float, scaleFactor: float) -> float:
    #     """Returns between -1 and 1, where -3 as input is very close to -1 already and 3 is very close to 1 output already."""
    #
    #     x = x / (1 + abs(x))
    #     return x / scaleFactor

    @staticmethod
    @jit(float32(float32), nopython=True)
    def fast_sigmoid_jit(x: float) -> float:
        """compresses stuff to stuff."""
        return x / (2 * ((x < 0.0) * -x + (x >= 0.0) * x) + 2) + 0.5

    @staticmethod
    @jit(float32(float32, int32), nopython=True)
    def two_parent_log_jit(exploreFactor: float, totalVisitCount: int) -> float:
        return exploreFactor * math.log(max(1, totalVisitCount))

    @staticmethod
    @jit(float32(float32, int32), nopython=True)
    def two_parent_log_explore(twoParentLog: float, childVisitCount: int) -> float:
        return math.sqrt(twoParentLog / max(1, childVisitCount))

    def get_player_utilities_n1_1(self, boardState: ArmySimState) -> typing.List[float]:
        """
        Returns a list of floats (per player) between 1.0 and -1.0 where winning player is 1.0 and losing player is -1.0 and all players in between are in the range.

        @param boardState:
        @return:
        """
        netDifferential = boardState.calculate_value_int()
        if self.offset_initial_differential:
            netDifferential -= boardState.initial_differential * 10

        compressed = MctsDUCT.fast_tanh_scaled_jit(netDifferential, self.utility_compression_ratio)
        return [compressed, 0 - compressed]
        # return [compressed, MctsDUCT.fast_tanh_scaled_jit(0 - netDifferential, self.utility_compression_ratio)]  # verify that the compression function is symmetric

    def decompress_player_utility(self, compressed: float) -> float:
        # x = x * scaleFactor
        # return x / (1 + abs(x))

        # compressed is y, solving for x:
        # if x is negative,
        # x = 0 - (y / (y - 1))
        # else
        # x = y / (y + 1)

        decompressed = 0
        if compressed < 0:
            decompressed = compressed / (compressed + 1.0)
        else:
            decompressed = 0.0 - (compressed / (compressed - 1.0))

        return decompressed / self.utility_compression_ratio

    def _get_selection_func_from_enum(self, nodeSelectionFunction: MoveSelectionFunction):
        if nodeSelectionFunction == MoveSelectionFunction.RobustChild:
            return self.robust_child_selection_func
        elif nodeSelectionFunction == MoveSelectionFunction.MaxAverageValue:
            return self.maximum_average_value_selection_func

        raise NotImplemented(f'{str(nodeSelectionFunction)}')


class MctsEngineSummary(object):
    def __init__(
            self,
            rootNode: MctsNode,
            selectionFunc: typing.Callable[[MctsNode], typing.Tuple[float, BoardMoves]],
            game: Game,
            finalPlayoutEstimationDepth: int
    ):
        """

        @param rootNode:
        @param selectionFunc:
        """
        self.root_node: MctsNode = rootNode
        self.best_moves: typing.List[BoardMoves] = []
        self.best_states: typing.List[ArmySimState] = []
        self.best_nodes: typing.List[MctsNode] = []
        self.best_result_state: ArmySimState = rootNode.context.board_state

        score, bestMoves = selectionFunc(rootNode)
        self.expected_score: float = score

        nextScore = score

        curNode = rootNode
        lastNode = rootNode
        bestMovesNotApplied = True
        while True:
            self.best_nodes.append(curNode)
            self.best_states.append(curNode.context.board_state)
            self.best_moves.append(bestMoves)

            lastNode = curNode
            curNode = curNode.children.get(bestMoves, None)

            # break if we hit a node that hasn't really been tested outside of a single trial, instead do a biased final trial.
            if curNode is None or (curNode.totalVisitCount <= 3 and not curNode.context.trial.over()):
                break

            nextScore, bestMoves = selectionFunc(curNode)

            if curNode.totalVisitCount > 10 or curNode.context.trial.over():
                # dont record score for nodes once we hit low confidence.
                score = nextScore

        # tack on the final game state
        finalContext = Context(lastNode.context)
        if not finalContext.trial.over():
            if (
                    (finalContext.board_state.friendly_move is not None and finalContext.board_state.friendly_move == bestMoves.playerMoves[0])
                    or (finalContext.board_state.enemy_move is not None and finalContext.board_state.enemy_move == bestMoves.playerMoves[1])
            ):
                raise AssertionError('wut')
            game.apply(finalContext, bestMoves)
            self.best_states.append(finalContext.board_state)
            # these are already appended in the loop above
            # self.best_moves.append(bestMoves)

        self.expanded_best_result_state: ArmySimState = finalContext.board_state
        """The expected board state from expanded nodes, without a final biased trial."""

        # run a biased trial to apply to the final moves to try to more accurately represent the expected outcome.
        # This wont affect the float-estimated-score but will affect the raw 'net differential' of the final estimated board state.
        # Stuff should use the score estimation instead, though.
        oldDisablePosition = game._disablePositionalWinDetectionInRollouts
        game._disablePositionalWinDetectionInRollouts = True
        try:
            trialCtx = Context(finalContext)
            if finalPlayoutEstimationDepth > 0 and not trialCtx.trial.over():
                simTilePrefix = "\r\n    "
                logging.info(f'beginning final estimation playout from {str(finalContext.board_state)}.')
                logging.info(f'Moves so far: \r\n    {simTilePrefix.join([str(boardMove) for boardMove in self.best_moves])}\r\n')
                logging.info(
                    f'simTiles so far:\r\n    {simTilePrefix.join([str(simTile) for simTile in finalContext.board_state.sim_tiles.values()])}\r\n')

                game.playout(
                    trialCtx,
                    playoutMoveSelector=None,
                    biasedMoveRatio=1.0,
                    maxNumBiasedActions=finalPlayoutEstimationDepth,
                    maxNumPlayoutActions=finalPlayoutEstimationDepth,
                    minRandomInitialMoves=0,
                )

                lastContext = finalContext
                for boardMove in trialCtx.trial.moves:
                    finalContext = Context(finalContext)
                    logging.info(f'Move: {str(boardMove)}')
                    game.apply(finalContext, boardMove)
                    logging.info(f'simTiles:\r\n    {simTilePrefix.join([str(simTile) for simTile in finalContext.board_state.sim_tiles.values()])}\r\nboard state {str(finalContext.board_state)}\r\n')
                    if finalContext.board_state.captures_enemy or finalContext.board_state.captured_by_enemy:
                        break
                    self.best_states.append(finalContext.board_state)
                    self.best_moves.append(boardMove)
                    lastContext = finalContext
                finalContext = lastContext
        finally:
            game._disablePositionalWinDetectionInRollouts = oldDisablePosition

        self.best_result_state: ArmySimState = finalContext.board_state
        """Includes the speculative final expansion board state."""

        self.duration: float = 0.0
        self.iterations: int = 0
        self.trials_performed: int = 0
        self.backprop_iter: int = 0
        self.nodes_explored: int = 0
        self.rollout_expansions = 0
        self.biased_rollout_expansions: int = 0
        self.expanded_expected_score: float = score

    def __str__(self):
        return f'[{self.expected_score:.3f} : {self.expanded_expected_score:.3f} : {str(self.expanded_best_result_state)} : {str(self.best_result_state)}]'

    def __repr__(self):
        return str(self)

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

        self.legalMovesPerPlayer: typing.List[typing.List[Move | None]] = [[] for p in range(numPlayers)]
        """ For every player index, a list of legal moves in this node """

        # allLegalMoves: typing.List[BoardMoves] = context.get_legal_moves()

        # # For every active player in this state, compute their legal moves
        # for p in range(numPlayers):
        #     # TODO IF WE NEED TO INCLUDE MORE THAN TWO PLAYERS AT ONCE...?
        #     # moves = AIUtils.extractMovesForMover(allLegalMoves, p)
        #     # TODO this might actually be intended to be JUST the players move options, not the pair of every move/response...?
        #     self.legalMovesPerPlayer[p] = allLegalMoves

        self.legalMovesPerPlayer[0] = self.context.board_state.generate_friendly_moves()

        self.legalMovesPerPlayer[1] = self.context.board_state.generate_enemy_moves()

        self.visitCounts: typing.List[typing.List[int]] = [[0 for move in playerMoves] for playerMoves in self.legalMovesPerPlayer]
        """ For every player, for every child move, a visit count """

        self.scoreSums: typing.List[typing.List[float]] = [[0.0 for move in playerMoves] for playerMoves in self.legalMovesPerPlayer]
        """ For every player, for every child move, a sum of backpropagated scores """

        self.lastSelectedMovesPerPlayer: typing.List[int] = [-1 for p in range(numPlayers)]
        """
        For every player, the index of the legal move we selected for
        that player in this node in the last (current) MCTS iteration.
        """

    def __str__(self):
        return str(self.context)

    def __repr__(self):
        return str(self)


class Context(object):
    def __init__(self, toClone: Context | None = None):
        self.turn: int = 0
        self.game: Game | None = None
        self.engine = None  # untyped to avoid circular refs for now
        self.board_state: ArmySimState | None = None
        # self.frMoves: typing.List[Move | None] = None
        # """available friendly moves"""
        # self.enMoves: typing.List[Move | None] = None
        # """available enemy moves"""
        if toClone is not None:
            # TODO this might need to be raw clone not child_board, dunno yet.
            # self.frMoves = toClone.frMoves
            # self.enMoves = toClone.enMoves
            self.board_state = toClone.board_state.clone()
            self.engine = toClone.engine
            self.game = toClone.game
            self.turn = toClone.turn

        self.trial: Trial = Trial(self)

    def set_initial_board_state(self, engine, state: ArmySimState, game: Game, turn: int):
        self.board_state = state
        self.engine = engine
        self.turn = turn
        self.game = game
        self.trial = Trial(self)
    #
    # def get_legal_moves(self) -> typing.List[BoardMoves]:
    #     self.frMoves: typing.List[Move | None] = self.board_state.generate_friendly_moves()
    #
    #     self.enMoves: typing.List[Move | None] = self.board_state.generate_enemy_moves()
    #
    #     moves: typing.List[BoardMoves] = []
    #     for frIdx, frMove in enumerate(self.frMoves):
    #         for enIdx, enMove in enumerate(self.enMoves):
    #             moves.append(BoardMoves([frMove, enMove]))
    #
    #     return moves

    def __str__(self):
        return f't{self.turn} {str(self.board_state)} {str(self.board_state.friendly_move)} {str(self.board_state.enemy_move)}'

    def __repr__(self):
        return str(self)


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
    def __init__(
            self,
            player: int,
            otherPlayers: typing.List[int],
            allowRandomRepetitions: bool,
            allowRandomNoOps: bool,
            disablePositionalWinDetectionInRollouts: bool
    ):
        self.numPlayers: int = 1 + len(otherPlayers)

        self.friendly_player: int = player
        self.enemy_player: int = otherPlayers[0]

        self._rollout_expansions = 0
        self._biased_rollout_expansions: int = 0

        self._allowRandomRepetitions: bool = allowRandomRepetitions

        self._allowRandomNoOps: bool = allowRandomNoOps

        self._disablePositionalWinDetectionInRollouts: bool = disablePositionalWinDetectionInRollouts

    def playout(
        self,
        context: Context,
        playoutMoveSelector: typing.Callable[[ArmySimState, typing.List[BoardMoves]], BoardMoves] | None,
        maxNumBiasedActions: int,
        maxNumPlayoutActions: int,
        biasedMoveRatio: float,
        minRandomInitialMoves: int
    ) -> Trial:
        """
        TD: Run a rollout....?
        Runs a rollout.
        DOES modify context...?
        Runs biased moves until it runs out of the max number of biased moves, then runs random moves...?

        @param minRandomInitialMoves:
        @param context:
        @param playoutMoveSelector:
        @param maxNumBiasedActions:
        @param maxNumPlayoutActions: limits the depth of the rollout from THIS point, regardless of how deep we already are...?
        @param biasedMoveRatio: the ratio at which to play biased moves, if available.
        @return:
        """

        trial: Trial = context.trial

        if self._disablePositionalWinDetectionInRollouts:
            oldFriendlyKillThreat: bool = trial.context.engine.friendly_has_kill_threat
            oldEnemyKillThreat: bool = trial.context.engine.enemy_has_kill_threat
            trial.context.engine.friendly_has_kill_threat = False
            trial.context.engine.enemy_has_kill_threat = False

        try:
            numStartMoves: int = trial.numMoves()
            iter = 0

            numAllowedBiasedActions = maxNumBiasedActions
            alwaysBiased = biasedMoveRatio == 1.0

            while True:
                # logging.info(f'playouting {str(trial.context.board_state)} at t{trial.context.turn}')
                if (
                    trial.over()
                    or 0 <= maxNumPlayoutActions <= trial.numMoves() - numStartMoves
                ):
                    break

                # if maxNumBiasedActions >= 0:
                #     numAllowedBiasedActions = max(0, maxNumBiasedActions - (trial.numMoves() - numStartMoves))
                # else:
                #     numAllowedBiasedActions = maxNumBiasedActions

                if iter >= minRandomInitialMoves and numAllowedBiasedActions > 0 and (alwaysBiased or random.random() <= biasedMoveRatio):
                    trial = self.playout_biased_move(trial, playoutMoveSelector)
                    numAllowedBiasedActions -= 1
                else:
                    trial = self.playout_random_move(trial)
                iter += 1
                if iter > 70:
                    logging.info(f'inf looping? {str(trial.context.board_state)}')
                if iter > 80:
                    raise AssertionError('wtf, infinite looped?')

            self._rollout_expansions += iter

        finally:
            if self._disablePositionalWinDetectionInRollouts:
                trial.context.engine.friendly_has_kill_threat = oldFriendlyKillThreat
                trial.context.engine.enemy_has_kill_threat = oldEnemyKillThreat

        return trial

    def apply(self, context: Context, combinedMove: BoardMoves):
        """
        Applies moves to a context, updating its turn and current board state.
        @param context:
        @param combinedMove:
        @return:
        """
        # nextTurn = context.turn + 1
        context.board_state = context.engine.get_next_board_state(
            context.turn + 1,
            context.board_state,
            frMove=combinedMove.playerMoves[0],
            enMove=combinedMove.playerMoves[1])
        context.turn += 1

    def playout_random_move(self, trial: Trial) -> Trial:
        bs = trial.context.board_state
        frMoves: typing.List[Move | None] = bs.generate_friendly_moves()

        enMoves: typing.List[Move | None] = bs.generate_enemy_moves()

        # TODO not efficient, move to some sort of move generator, or make these all yields so they can be filtered live
        if not self._allowRandomRepetitions:
            frMoves = [m for m in frMoves if m is None or bs.friendly_move is None or m.dest != bs.friendly_move.source]
            enMoves = [m for m in enMoves if m is None or bs.enemy_move is None or m.dest != bs.enemy_move.source]

        if not self._allowRandomNoOps:
            frMoves = [m for m in frMoves if m is not None]
            enMoves = [m for m in enMoves if m is not None]

        chosenFr = random.choice(frMoves) if len(frMoves) > 0 else None

        chosenEn = random.choice(enMoves) if len(enMoves) > 0 else None

        chosen = BoardMoves([chosenFr, chosenEn])
        self.apply(trial.context, chosen)
        trial.moves.append(chosen)
        return trial

    def playout_biased_move__comparison_engine_slow(
            self,
            trial: Trial,
            playoutMoveSelector: typing.Callable[[ArmySimState, typing.List[BoardMoves]], BoardMoves] | None,
    ) -> Trial:
        c = trial.context
        bs = c.board_state
        e = c.engine
        frMoves = bs.friendly_move_generator(bs)
        enMoves = bs.enemy_move_generator(bs)
        payoffs = [
            [
                e.get_next_board_state(c.turn + 1, bs, frMove, enMove)
                for enMove in enMoves
            ]
            for frMove in frMoves
        ]

        chosenRes = e.get_comparison_based_expected_result_state(
            bs.depth,
            [x for x in enumerate(frMoves)],
            [x for x in enumerate(enMoves)],
            payoffs
        )

        boardMove = BoardMoves([chosenRes.friendly_move, chosenRes.enemy_move])
        self.apply(trial.context, boardMove)
        trial.moves.append(boardMove)
        self._biased_rollout_expansions += 1

        return trial

    def playout_biased_move(
            self,
            trial: Trial,
            playoutMoveSelector: typing.Callable[[ArmySimState, typing.List[BoardMoves]], BoardMoves] | None,
    ) -> Trial:
        c = trial.context
        bs = c.board_state

        frMoves: typing.List[Move | None] = bs.generate_friendly_moves()

        enMoves: typing.List[Move | None] = bs.generate_enemy_moves()

        bestFrMove = self.pick_best_move_heuristic(self.friendly_player, frMoves, bs, prevMove=bs.friendly_move)
        bestEnMove = self.pick_best_move_heuristic(self.enemy_player, enMoves, bs, prevMove=bs.enemy_move)

        # if bestFrMove is not None and bs.friendly_move is not None and bestFrMove.dest.x == bs.friendly_move.source.x and bestFrMove.dest.y == bs.friendly_move.source.y:
        #     logging.info('wtf')
        #     raise AssertionError("?")
        #
        # if bestEnMove is not None and bs.enemy_move is not None and bestEnMove.dest.x == bs.enemy_move.source.x and bestEnMove.dest.y == bs.enemy_move.source.y:
        #     logging.info('wtf')
        #     raise AssertionError("?")

        chosen = BoardMoves([bestFrMove, bestEnMove])
        self.apply(trial.context, chosen)
        trial.moves.append(chosen)

        self._biased_rollout_expansions += 1

        return trial

    @staticmethod
    def pick_best_move_heuristic(
        player: int,
        moves: typing.List[Move | None],
        boardState: ArmySimState,
        prevMove: Move | None,
    ) -> Move | None:
        best = None
        bestVal = 0
        numBestFound = 1
        for move in moves:
            if move is None:
                continue  # none already covered by the existing bestVal = 0 and best = None

            val = 2  # cap neutral
            st = boardState.sim_tiles.get(move.dest, None)
            # if st:
            #     # then we're playing within the already scrimmed tiles. These are less valuable than running off into new territory.
            #     if st.player == player:
            #         val = 0
            #
            #         if prevMove is not None and move.dest == prevMove.source:
            #             val = -10  # dont repetition in trials, if the tile is still owned by us and still in the play area.
            #     else:
            #         # must be enemy tile because its in the scrim
            #         val = 4
            # else:
            #     if move.dest.player == player:
            #         val = 1
            #     elif move.dest.player >= 0:
            #         val = 6
            #     elif move.dest.isCity:
            #         val = -20
            #     # else this is indeed a neutral capture, continue

            # new logic
            p = move.dest.player
            a = move.dest.army
            if move.dest.isCity and not move.dest.isNeutral:
                a += boardState.depth // 2
            if st:
                # then we're playing within the already scrimmed tiles. These are less valuable than running off into new territory.
                val -= 2
                p = st.player
                a = st.army

            if p == player:
                val = 1
            elif p >= 0:
                val = 6
                if move.dest.isCity or move.dest.isGeneral:
                    src = boardState.sim_tiles.get(move.source)
                    if src.army - 1 > a:
                        val += 10
                        if move.dest.isGeneral:
                            val += 20
            elif move.dest.isCity:
                # else this is indeed a neutral capture, dont cap neutral cities
                val = -20

            if bestVal < val:
                bestVal = val
                numBestFound = 1
                best = move
            elif bestVal == val:
                numBestFound += 1
                if random.randrange(0, numBestFound) == 0:
                    # implements random tiebreaks
                    best = move

        return best
