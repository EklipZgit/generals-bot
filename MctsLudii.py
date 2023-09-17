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
from numba import jit, float32, int32

import numpy
from scipy.special import expit

from DataModels import Move
from Engine.ArmyEngineModels import ArmySimState, ArmySimResult
from PerformanceTimer import PerformanceTimer


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


class MctsDUCT(object):
    def __init__(
            self,
            # player: int,
            logStuff: bool = True,
    ):
        self.logAll: bool = False
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
    ) -> MctsEngineSummary:
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
                    maxNumBiasedActions=0,
                    # maxNumPlayoutActions=-1,  # -1 forces it to run until an actual game end state, infinite depth...?
                    maxNumPlayoutActions=7,  # -1 forces it to run until an actual game end state, infinite depth...?
                    randomGen=None  # ThreadLocalRandom.currentNode()
                )
                if self.logAll:
                    logging.info(f'  trial for node t{currentNode.context.turn} {str(currentNode.context.board_state)} resulted in \r\n    ctxEnd t{contextEnd.turn} {str(contextEnd.board_state)} \r\n    (trial t{trial.context.turn} {str(trial.context.board_state)})')

                self.trials_performed += 1

            # This computes utilities for all players at the of the playout,
            # which will all be values in [-1.0, 1.0]
            utilities: typing.List[float] = MctsDUCT.get_player_utilities_n1_1(contextEnd.board_state)

            # Backpropagate utilities through the tree
            while currentNode is not None:
                # if currentNode.totalVisitCount > 0:
                # This node was not newly expanded in this iteration
                for p in range(game.numPlayers):
                    # logging.info(f'backpropogating {str(contextEnd.board_state)} at t{contextEnd.turn} up through the tree to {str(currentNode.context.board_state)} t{currentNode.context.turn}')
                    lastSelMove = currentNode.lastSelectedMovesPerPlayer[p]
                    currentNode.visitCounts[p][lastSelMove] += 1
                    currentNode.scoreSums[p][lastSelMove] += utilities[p]
                    self.backprop_iter += 1

                currentNode.totalVisitCount += 1
                currentNode = currentNode.parent

            # Increment iteration count
            numIterations += 1

        self.iterations = numIterations

        # Return the move we wish to play
        return self.get_best_moves(root)

    def bench_random_stuff(self):
        # for i in range(-100, 100, 10):
        #     logging.info(f'fast_tanh {i} = {MctsDUCT.fast_tanh_jit(i)}')
        for i in range(-1000, 1000, 10):
            logging.info(f'fast_tanh_scaled {i} = {MctsDUCT.fast_tanh_scaled_jit(i, 0.01)}')
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
                tanhJitScaleds = [MctsDUCT.fast_tanh_scaled_jit(i, 0.01) for i in testRange]
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

        twoParentLog: float = MctsDUCT.two_parent_log_jit(current.totalVisitCount)

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
            self.nodes_explored += 1

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
        def robust_child_selection_func(node: MctsNode) -> typing.Tuple[float, BoardMoves]:
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
                        logging.info(f'p{p} t{node.context.turn} new best move had \r\n'
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
                            logging.info(f'p{p} t{node.context.turn} visit tie - new best move had \r\n'
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

                            logging.info(f'p{p} t{node.context.turn} TIEBREAK move had \r\n'
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
                logging.info(f'p{p} t{node.context.turn} best move had \r\n'
                         f'   visitCount {bestVisitCount}, \r\n'
                         f'   bestAvgScore {bestAvgScore:.3f}, \r\n'
                         f'   bestMove {str(bestMove)}')
                playerMoves.append(bestMove)
                playerScores.append(bestAvgScore)
                playerVisitCounts.append(bestVisitCount)

            boardMove = BoardMoves(playerMoves)

            logging.info(f't{node.context.turn} COMBINED move had \r\n'
                         f'   visitCounts {str(playerVisitCounts)}, \r\n'
                         f'   bestAvgScores {str([f"{s:.3f}" for s in playerScores])}, \r\n'
                         f'   bestMove {str(boardMove)}')
            return playerScores[0], boardMove

        logging.info('MCTS BUILDING BEST MOVE CHOICES')

        summary = MctsEngineSummary(
            rootNode,
            selectionFunc=robust_child_selection_func
        )
        return summary

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
        return x / (1 + abs(x))

    @staticmethod
    @jit(float32(float32), nopython=True)
    def fast_sigmoid_jit(x: float) -> float:
        """compresses stuff to stuff."""
        return x / (2 * ((x < 0.0) * -x + (x >= 0.0) * x) + 2) + 0.5

    @staticmethod
    @jit(float32(int32), nopython=True)
    def two_parent_log_jit(totalVisitCount: int) -> float:
        return 2.0 * math.log(max(1, totalVisitCount))

    @staticmethod
    @jit(float32(float32, int32), nopython=True)
    def two_parent_log_explore(twoParentLog: float, childVisitCount: int) -> float:
        return math.sqrt(twoParentLog / max(1, childVisitCount))

    @staticmethod
    def get_player_utilities_n1_1(boardState: ArmySimState) -> typing.List[float]:
        """
        Returns a list of floats (per player) between 1.0 and -1.0 where winning player is 1.0 and losing player is -1.0 and all players in between are in the range.

        @param boardState:
        @return:
        """
        netDifferential = boardState.calculate_value_int()

        # # # TODO should wins/losses be the 1.0/-1.0 extremes and just econ be much more 'middle'...?
        # econValueNeg1000To1000 = min(1000.0, max(-1000.0, netDifferential))
        # compressed = econValueNeg1000To1000 / 1000.0
        # return [compressed, 0 - compressed]

        # econValueNeg500To500 = min(500.0, max(-500.0, netDifferential))
        # compressed = econValueNeg500To500 / 500.0
        # return [compressed, 0 - compressed]
        compressed = MctsDUCT.fast_tanh_scaled_jit(netDifferential, 0.01)
        return [compressed, 0 - compressed]

        # val = 0.0
        # if netDifferential > 0:
        #     # val = 0.7
        #     val = 1.0
        # if netDifferential < 0:
        #     # val = -0.7
        #     val = -1.0
        # if netDifferential < -200:
        #     val = -1.0
        # if netDifferential > 200:
        #     val = 1.0
        #
        # return [val, 0 - val]


class MctsEngineSummary(object):
    def __init__(
            self,
            rootNode: MctsNode,
            selectionFunc: typing.Callable[[MctsNode], typing.Tuple[float, BoardMoves]]
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

        curNode = rootNode
        while curNode is not None:
            self.best_nodes.append(curNode)
            self.best_states.append(curNode.context.board_state)
            self.best_result_state = curNode.context.board_state
            self.best_moves.append(bestMoves)

            curNode = curNode.children.get(bestMoves, None)
            if curNode is not None:
                score, bestMoves = selectionFunc(curNode)


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
        self.frMoves: typing.List[Move | None] = None
        """available friendly moves"""
        self.enMoves: typing.List[Move | None] = None
        """available enemy moves"""
        self._trial: Trial | None = None
        if toClone is not None:
            # TODO this might need to be raw clone not child_board, dunno yet.
            # self.frMoves = toClone.frMoves
            # self.enMoves = toClone.enMoves
            self.board_state = toClone.board_state.clone()
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

            # numAllowedActions: int = 0
            # numAllowedBiasedActions: int = 0
            #
            # if maxNumPlayoutActions >= 0:
            #     numAllowedActions = max(0, maxNumPlayoutActions - (trial.numMoves() - numStartMoves))
            # else:
            #     numAllowedActions = maxNumPlayoutActions

            if maxNumBiasedActions >= 0:
                numAllowedBiasedActions = max(0, maxNumBiasedActions - (trial.numMoves() - numStartMoves))
            else:
                numAllowedBiasedActions = maxNumBiasedActions

            if numAllowedBiasedActions > 0 and random.randrange(10) <= 5:
                trial = self.playout_biased_move(trial, playoutMoveSelector)
                # numAllowedBiasedActions -= 1
            else:
                trial = self.playout_random_move(trial)
            iter += 1
            if iter > 50:
                logging.info(f'inf looping? {str(trial.context.board_state)}')
            if iter > 100:
                raise AssertionError('wtf, infinite looped?')

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
                e.get_next_board_state(c.turn + 1, bs, frMove, enMove)
                for enMove in c.enMoves
            ]
            for frMove in c.frMoves
        ]

        chosenRes = e.get_comparison_based_expected_result_state(
            bs.depth,
            [x for x in enumerate(c.frMoves)],
            [x for x in enumerate(c.enMoves)],
            payoffs
        )

        boardMove = BoardMoves([chosenRes.best_result_state.friendly_move, chosenRes.best_result_state.enemy_move])
        self.apply(trial.context, boardMove)
        trial.moves.append(boardMove)
        self.biased_rollout_expansions += 1

        return trial
