import gc

import logbook
import time
import typing

import DebugHelper
import Gather
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Sim.TextMapLoader import TextMapLoader
from TestBase import TestBase
from base.client.tile import TILE_EMPTY, Tile
from bot_ek0x45 import EklipZBot


class GatherBulkTests(TestBase):
    def get_debug_render_bot(self, simHost: GameSimulatorHost, player: int = -2) -> EklipZBot:
        bot = super().get_debug_render_bot(simHost, player)

        bot.info_render_gather_values = True
        bot.info_render_centrality_distances = True
        Gather.USE_DEBUG_ASSERTS = True
        DebugHelper.IS_DEBUGGING = True

        return bot

    def run_adversarial_gather_test_all_algorithms(
            self,
            testMapStr: str,
            targetXYs: typing.List[typing.Tuple[int, int]],
            depth: int,
            expectedGather: int | None,
            inclNegative: bool,
            useTrueVal: bool = False,
            targetsAreEnemy: bool | None = None,
            testTiming: bool = False,
            render: bool = False,
            renderLive: bool = False,
            incIterMax: bool = True,
            incLiveFast: bool = False,
            incMaxIter1: bool = False,
            incGreedy: bool = False,
            incRecurse: bool = False,
            incGathSetQuick: bool = True,
            incChatGptDp: bool = False,
            incChatGptDpStack: bool = False,
            incApproxPcst: bool = True,
            negativeTiles: typing.Set[Tile] | None = None,
            playerIndex: int = 0,
    ):
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testMapStr, 102, player_index=playerIndex)
        # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general_from_string(testMapStr, 102)
        if targetsAreEnemy is not None:
            tgPlayer = general.player
            if targetsAreEnemy:
                tgPlayer = enemyGeneral.player
            for x, y in targetXYs:
                mapTg = map.GetTile(x, y)
                rawMapTg = rawMap.GetTile(x, y)
                mapTg.player = tgPlayer
                rawMapTg.player = tgPlayer

        self.begin_capturing_logging()
        self.disable_search_time_limits_and_enable_debug_asserts()
        simHost = GameSimulatorHost(map, player_with_viewer=-2, playerMapVision=rawMap, allAfkExceptMapPlayer=True)
        # gc.disable()
        msgs = []
        if testTiming:
            # dont skew the timing with the expensive debug asserts.
            Gather.USE_DEBUG_ASSERTS = False
        else:
            Gather.USE_DEBUG_ASSERTS = True

        bot = simHost.bot_hosts[general.player].eklipz_bot

        gatherMatrix = bot.get_gather_tiebreak_matrix()
        captureMatrix = bot.get_expansion_weight_matrix()
        valueMatrix = Gather.build_gather_capture_pure_value_matrix(map, general.player, negativeTiles=negativeTiles, gatherMatrix=gatherMatrix, captureMatrix=captureMatrix, prioritizeCaptureHighArmyTiles=False, useTrueValueGathered=useTrueVal)

        targets = [bot._map.GetTile(x, y) for x, y in targetXYs]

        viewInfo = self.get_renderable_view_info(map)
        start = time.perf_counter()
        # move, valGathered, turnsUsed, nodes = bot.get_gather_to_target_tiles(
        #     targets,
        #     1.0,
        #     depth,
        #     shouldLog=False,
        #     negativeSet=negativeTiles,
        #     useTrueValueGathered=useTrueVal,
        #     priorityMatrix=gatherMatrix,
        #     includeGatherTreeNodesThatGatherNegative=inclNegative)

        valGathered, turnsUsed, nodes = Gather.knapsack_depth_gather_with_values(
            map,
            targets,
            depth,
            targetArmy=-1,
            distPriorityMap=None,
            negativeTiles=negativeTiles,
            searchingPlayer=map.player_index,
            viewInfo=None,
            useTrueValueGathered=useTrueVal,
            incrementBackward=False,
            includeGatherTreeNodesThatGatherNegative=inclNegative,
            priorityMatrix=gatherMatrix,
            cutoffTime=time.perf_counter() + 1.0,
            fastMode=False,
            shouldLog=False)
        dur = time.perf_counter() - start

        # viewInfo = bot.viewInfo
        # msg = f"LIVE {valGathered} / {expectedGather},  {turnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
        msg = f"LIVE {valGathered} gathered in {turnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

        for n in nodes:
            n.strip_all_prunes()
        msgs.append(msg)
        if render and renderLive:
            viewInfo = self.get_renderable_view_info(map)
            viewInfo.add_info_multi_line(f'LIVE is currently a depth based iterative prune backoff '
                'custom designed by me (the only outside algo used here '
                'is just a priority-queue-for-tiebreaks based Breadth '
                'First Search).\nIterations are a full T turn gather, '
                'which is then greedily pruned to some fraction of T '
                'turns, the "kept" tiles encoded into the next iterations '
                'start tiles, and then repeated until T is reached. \nEach '
                'iteration is a full BFS, recording the maximum value path achieved from each '
                'start tile per distance from that tile, and then at the end of each iteration '
                'a multiple-choice-knapsack solver is run to find the highest '
                'value combination of paths found that fits in the T remaining '
                'turns.')
            viewInfo.gatherNodes = nodes
            self.render_view_info(map, viewInfo, msg)
        else:
            logbook.info(msg)
        gc.collect()

        if incIterMax:
            start = time.perf_counter()
            # move, liveFastValGathered, liveFastTurnsUsed, liveFastNodes = bot.get_gather_to_target_tiles(
            #     targets,
            #     1.0,
            #     depth,
            #     shouldLog=False,
            #     negativeSet=negativeTiles,
            #     useTrueValueGathered=useTrueVal,
            #     includeGatherTreeNodesThatGatherNegative=inclNegative,
            #     fastMode=True)
            iterMaxValGathered, iterMaxTurnsUsed, iterMaxNodes = Gather.knapsack_max_gather_with_values(
                map,
                targets,
                depth,
                targetArmy=-1,
                distPriorityMap=None,
                negativeTiles=negativeTiles,
                searchingPlayer=map.player_index,
                viewInfo=None,
                useTrueValueGathered=useTrueVal,
                incrementBackward=False,
                includeGatherTreeNodesThatGatherNegative=inclNegative,
                priorityMatrix=gatherMatrix,
                cutoffTime=time.perf_counter() + 1.0,
                fastMode=False,
                shouldLog=False)
            
            dur = time.perf_counter() - start

            # msg = f"FAST {iterMaxValGathered} / {expectedGather},  {iterMaxTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"ITER MAX {iterMaxValGathered} gathered in {iterMaxTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

            for n in iterMaxNodes:
                n.strip_all_prunes()
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(f'ITER MAX is new variation of LIVE ITER that doesnt care about depth (aka cant be used for defense) and thus can use a heuristic depth first search instead of breadth first like normal ITER.')
                viewInfo.gatherNodes = iterMaxNodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incLiveFast:
            start = time.perf_counter()
            # move, liveFastValGathered, liveFastTurnsUsed, liveFastNodes = bot.get_gather_to_target_tiles(
            #     targets,
            #     1.0,
            #     depth,
            #     shouldLog=False,
            #     negativeSet=negativeTiles,
            #     useTrueValueGathered=useTrueVal,
            #     includeGatherTreeNodesThatGatherNegative=inclNegative,
            #     fastMode=True)
            liveFastValGathered, liveFastTurnsUsed, liveFastNodes = Gather.knapsack_depth_gather_with_values(
                map,
                targets,
                depth,
                targetArmy=-1,
                distPriorityMap=None,
                negativeTiles=negativeTiles,
                searchingPlayer=map.player_index,
                viewInfo=None,
                useTrueValueGathered=useTrueVal,
                incrementBackward=False,
                includeGatherTreeNodesThatGatherNegative=inclNegative,
                priorityMatrix=gatherMatrix,
                cutoffTime=time.perf_counter() + 1.0,
                fastMode=True,
                shouldLog=False)

            dur = time.perf_counter() - start

            # msg = f"FAST {liveFastValGathered} / {expectedGather},  {liveFastTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"ITER FAST {liveFastValGathered} gathered in {liveFastTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

            for n in liveFastNodes:
                n.strip_all_prunes()
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(f'ITER FAST is the same as LIVE, but uses much larger fractions of T for each iteration, achieving a much much faster result but with lower quality output.')
                viewInfo.gatherNodes = liveFastNodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incMaxIter1:
            start = time.perf_counter()
            itr1ValGathered, itr1TurnsUsed, itr1Nodes = Gather.knapsack_depth_gather_with_values(
                map,
                targets,
                depth,
                targetArmy=-1,
                distPriorityMap=None,
                negativeTiles=negativeTiles,
                searchingPlayer=map.player_index,
                viewInfo=None,
                useTrueValueGathered=useTrueVal,
                incrementBackward=False,
                includeGatherTreeNodesThatGatherNegative=inclNegative,
                priorityMatrix=gatherMatrix,
                cutoffTime=time.perf_counter() + 2.0,
                fastMode=False,
                slowMode=True,
                shouldLog=False)
            dur = time.perf_counter() - start

            # msg = f"ITER 1 {itr1ValGathered} / {expectedGather},  {itr1TurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"ITER SLOW {itr1ValGathered} gathered in {itr1TurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

            for n in itr1Nodes:
                n.strip_all_prunes()
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(f'ITER SLOW is the same as LIVE, but locks the iteration turns to 1. So ITER SLOW for a 65 move gather will do a 65 move iteration, prune it down to a single added tile. Then a 64 move iteration, pruned to 2. Then a 63 move iteration, pruned to 3. Etc. In practice this can actually achieve worse results because I use a special variation of an iteration for the very first iteration (when there are only a few root nodes for the gather) because the multiple choice portion of the iteration on too few start points will result in choosing an optimal path to the target, and another (or even 2 more) suboptimal paths to the target, which then arent always fully pruned out. The backoff gather with a larger start prune tends to leave more of the "best path to target" intact where too small starting increments can lead to more forking suboptimal paths to target being left in the final output.')
                viewInfo.gatherNodes = itr1Nodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incChatGptDp:
            start = time.perf_counter()
            rootTiles = set(targets)
            val, gathSet = Gather.cutesy_chatgpt_gather(
                map,
                targetTurns=depth,
                rootTiles=rootTiles,
                searchingPlayer=general.player,
                # tilesToIncludeIfPossible={general},
                # negativeTiles=negs,
                valueMatrix=valueMatrix,
                # viewInfo=viewInfo,
            )

            plan = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
                map,
                rootTiles=rootTiles,
                tiles=gathSet,
                searchingPlayer=general.player,
                priorityMatrix=valueMatrix,
                negativeTiles=negativeTiles,
                useTrueValueGathered=useTrueVal,
                # includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
                # includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
                # pruneToTurns=targetTurns,
                # skipTiles=skipTiles,
                # captures={t for t in gathSet if not map.is_tile_on_team_with(t, general.player)},
                viewInfo=None
            )

            gptValGathered = plan.gathered_army
            gptTurnsUsed = plan.length

            # msg = f"GptDp {gptValGathered} / {expectedGather},  {gptTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"GptDp {gptValGathered} gathered in {gptTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(f'GptDp is a kind-of-dynamic-programming gather approach chat GPT came up with which absolutely did not work the way it output the code but was close enough that I think I captured roughly what it was trying to do. It effectively runs a greedy (actually its own implementation was completely naive) depth first search from every gatherable tile, recording a max gather value at time of reach for each turn each other tile was reached at. When reaching a tile that has been reached previously or in a previous start tile iteration, if the current value is better than the previous, the visited set is updated. The core problem of this is that it is effectively doing a travelling salesman with no backtracking, so while it actually outputs surprisingly good results (after I added priority queues to make it less naive), there will just be certain tiles that it can never gather WITH other tiles because there is no high value travelling salesman path to fork two tiles, whereas my other algorithms easily understand that a gather is inherently forking and can easily visit tiles that would not be reachable in EG a hamiltonion path or circuit of length T, which this algo will always avoid. My attempts to convert the depth first iterative portion to a backtracking open-set approach fail due to the "update the historical visits with better value / visited set" part of the algo, which invalidates the previous open set. I still believe this sort of approach has promise, I just havent sorted out how to fix the open-set problem. It is also pretty slow, as implemented.')
                viewInfo.gatherNodes = plan.root_nodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incChatGptDpStack:
            start = time.perf_counter()
            rootTiles = set(targets)
            val, gathSet = Gather.cutesy_chatgpt_gather_stack(
                map,
                targetTurns=depth,
                rootTiles=rootTiles,
                searchingPlayer=general.player,
                # tilesToIncludeIfPossible={general},
                # negativeTiles=negs,
                valueMatrix=valueMatrix,
                # viewInfo=viewInfo,
            )

            plan = Gather.convert_contiguous_tile_tree_to_gather_capture_plan(
                map,
                rootTiles=rootTiles,
                tiles=gathSet,
                searchingPlayer=general.player,
                priorityMatrix=valueMatrix,
                negativeTiles=negativeTiles,
                useTrueValueGathered=useTrueVal,
                # includeGatherPriorityAsEconValues=includeGatherPriorityAsEconValues,
                # includeCapturePriorityAsEconValues=includeCapturePriorityAsEconValues,
                # pruneToTurns=targetTurns,
                # skipTiles=skipTiles,
                # captures={t for t in gathSet if not map.is_tile_on_team_with(t, general.player)},
                viewInfo=None
            )

            gptStackValGathered = plan.gathered_army
            gptStackTurnsUsed = plan.length

            # msg = f"GptDpStack {gptStackValGathered} / {expectedGather},  {gptStackTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"GptDpStack {gptStackValGathered} gathered in {gptStackTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(f'GptDpStack is the naive stack implementation, the closest to what chat gpt actually recommended that really seemed to work.')
                viewInfo.gatherNodes = plan.root_nodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incGreedy:
            start = time.perf_counter()
            greedyStart = time.perf_counter()
            greedyValGathered, greedyTurnsUsed, greedyNodes = Gather.greedy_backpack_gather_values(
                map,
                startTiles=targets,
                turns=depth,
                searchingPlayer=general.player,
                useTrueValueGathered=useTrueVal,
                includeGatherTreeNodesThatGatherNegative=inclNegative,
                negativeTiles=negativeTiles,
                shouldLog=False)
            greedyDur = time.perf_counter() - greedyStart
            for n in greedyNodes:
                n.strip_all_prunes()
            # msg = f"GREED {greedyValGathered} / {expectedGather},  {greedyTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"GREED {greedyValGathered} gathered in {greedyTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(f'GREED is similar to LIVE except instead of storing multiple max values per tile, per distance, and multiple-choice-knapsacking them and then pruning, INSTEAD what greed does is effectively just run the "give me the highest gather value / turns path from the current start tiles, and we\'ll include that in the plan". It does no pruning and has a highly variable runtime because the max value path length in any iteration could be of size 1, or size RemainingTurns. If it is size RemainingTurns, then the gather is over. If it is size 1, we could in worst case do RemainingTurns-1 more searches, each of which is a roughly ~1ms complex heuristic search, scaling with large maps. It was not uncommon to see a single gather calculation take 135ms on large FFA maps before I switched to the per-tile-per-distance-knapsack gathers. GREED can often find better solutions than the iterative prune approach, but its runtime is much less predictable and it is also MUCH more prone to fall into poor plan traps, as can be seen here. On average ITERATIVE produces better results and much more consistent gather times.')
                viewInfo.gatherNodes = greedyNodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incRecurse:
            start = time.perf_counter()
            recurseStart = time.perf_counter()
            recurseValGathered, usedTurns, recurseNodes = Gather.knapsack_depth_gather_with_values(
                map,
                startTiles=targets,
                turns=depth,
                searchingPlayer=general.player,
                useTrueValueGathered=useTrueVal,
                includeGatherTreeNodesThatGatherNegative=inclNegative,
                negativeTiles=negativeTiles,
                ignoreStartTile=True,
                shouldLog=False,
                useRecurse=True
            )
            recurseDur = time.perf_counter() - recurseStart
            recurseTurnsUsed = 0
            for n in recurseNodes:
                n.strip_all_prunes()
                recurseTurnsUsed += n.gatherTurns

            # msg = f"RECUR {recurseValGathered} / {expectedGather},  {recurseTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"RECUR {recurseValGathered} gathered in {recurseTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(
                    f'Recursive is a variant of the Iterative gather where instead of iterative prune, it does a merge-sort style approach to the gather where it tries a couple variants of prune depths for each level, recursively trying variations down the stack. It was my first attempt at what became the iterative prune algo, and while it can be tweaked to run faster than GREED, did not really produce better results, and is inconsistent.')

                viewInfo.gatherNodes = recurseNodes
                self.render_view_info(map, viewInfo,msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incApproxPcst:
            start = time.perf_counter()
            plan = Gather.gather_approximate_turns_to_tiles(
                map,
                rootTiles=targets,
                approximateTargetTurns=depth,
                asPlayer=general.player,
                gatherMatrix=gatherMatrix,
                captureMatrix=captureMatrix,
                negativeTiles=negativeTiles,
                prioritizeCaptureHighArmyTiles=False,
                useTrueValueGathered=useTrueVal,
                # tilesToIncludeIfPossible={general},
                # negativeTiles=negs,
                # viewInfo=viewInfo,
            )

            pcstValGathered = plan.gathered_army
            pcstTurnsUsed = plan.length

            viewInfo.add_info_line("C fast-prize-collecting-steiner-tree + gradient parameter search")
            # msg = f"ApproxPCST {pcstValGathered} / {expectedGather},  {pcstTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"ApproxPCST {pcstValGathered} gathered in {pcstTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(
                    f'This was my first foray into the prize-collecting-steiner-tree area (where a gather of T moves to a specific tile / set of tiles can be considered a rooted prize collecting steiner tree search of size T+(numroot tiles). For this algo I am using a fast C implementation of a prize collecting steiner tree approximator. However it has no way to tune the size of the tree output, it simply tries to maximize the (reward/cost-per-node), where cost per node is "one move". So in order to get "roughly" T turns, I use a gradient search where I start with naive multiplication factors + offsets for both "cost" and "prize" and do some weird sort of binary-search like thing to try to hone in on the combination of parameters that gets closest to outputting a steiner tree of size T. The drawback to this is that it is not super consistent, and one of the things you want from an "approximate turns gather" like this (which is what most humans are always doing in their heads btw) is to throw away things that dont make sense. The parameter hunt will find plans that "dont make sense" because the code asks for a 45 turn gather and by golly, its gonna try to find one, even if what makes the most sense is EITHER 20 turns, or 50+ turns, and nothing in between (EG, a large FFA map with 13 cities already where youve already gathered all the cities remotely close to the opponents land). This approach is both fast and tuneable though, so I am considering implementing this algo myself so that I can give it more domain specific knowledge or something. Runtime-wise it performs well for large turn sizes but is less competitive at small turns.')
                viewInfo.gatherNodes = plan.root_nodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        if incGathSetQuick:
            start = time.perf_counter()
            rootTiles = set(targets)
            plan = Gather.gath_set_quick(
                map,
                targetTurns=depth,
                rootTiles=rootTiles,
                searchingPlayer=general.player,
                negativeTiles=negativeTiles,
                useTrueValueGathered=useTrueVal,
                # tilesToIncludeIfPossible={general},
                # negativeTiles=negs,
                valueMatrix=valueMatrix,
                # viewInfo=viewInfo,
            )

            gathSetQuickValGathered = plan.gathered_army
            gathSetQuickTurnsUsed = plan.length

            # msg = f"GathSetQuick {gathSetQuickValGathered} / {expectedGather},  {gathSetQuickTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msg = f"GathSetQuick {gathSetQuickValGathered} gathered in {gathSetQuickTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"
            msgs.append(msg)
            if render:
                viewInfo = self.get_renderable_view_info(map)
                viewInfo.add_info_multi_line(
                    f'GathSetQuick is a WIP algo I designed myself based vaguely on concepts from kruskals MST algo and friends. Effectively start with the T largest gatherable tiles. Then connect any disconnected parts of the set to make one fully connected set to make some new larger set of gathered tiles, and prune it. This isnt GUARANTEED to actually contain all of the tiles that would be in the optimal gather of that size (imagine an adversarial input where every tile along the very edges of the map was a gatherable 50, but towards the middle where your gather target root tile is is a bunch of 25s, the algo would start with all the 50s and connect them and then prune and only successfully gather a few 50s when it could have gathered ALL the 25s in the middle, or whatever. But that example seems highly unlikely in the real world). I have not yet implemented a min-cut algo for the "prune" portion of this algorithm, it is using a simple DFS based "safe prune finder" which is guaranteed to find a set of non-disconnecting nodes to safely prune, but isnt guaranteed to find ALL of them (or even a lot of them) so it regularly prunes good tiles before worse tiles. It also doesnt understand it can prune branches, so it\'ll leave a 25 at the end of a string of 1s and prune a bunch of 10s instead, when pruning the 6x1s + the 1x25 would be better.')

                viewInfo.gatherNodes = plan.root_nodes
                self.render_view_info(map, viewInfo, msg)
            else:
                logbook.info(msg)
            gc.collect()

        logbook.info(f'\r\n\r\nFINAL OUTPUT\r\n')
        for msg in msgs:
            logbook.info(msg)

        if not testTiming:
            if incRecurse and recurseValGathered > valGathered:
                self.fail(f'gather depth {depth} gathered {valGathered} compared to recurse {recurseValGathered}')

            if incGreedy and greedyValGathered > valGathered:
                self.fail(f'gather depth {depth} gathered {valGathered} compared to greedy {greedyValGathered}')
            if expectedGather is not None:
                self.assertEqual(expectedGather, valGathered)
            self.assertEqual(depth, turnsUsed)

        if testTiming:
            if incRecurse and dur > recurseDur:
                self.fail(f'gather depth {depth} took {dur:.3f} compared to recurse {recurseDur:.3f}')

            if incGreedy and dur > greedyDur:
                self.fail(f'gather depth {depth} took {dur:.3f} compared to greedy {greedyDur:.3f}')

            if dur > 0.05:
                self.fail(f'gather depth {depth} took {dur:.3f}')

    def test_gather__adversarial_to_large_iterative_gather_to_small_tileset(self):
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |
aG1  a11  a2   a3   a2   a3   a1   a21
a21  a21  a2   a2   a2   a1   a1   a1  
a21  b1   b1   b1   b1   b1   a2   a3  
a21  a21  a2   a2   a2   a1   a2   a1  
a11  a21  a2   a3   a2   a6   a2   a21
a2   a2   a2   a3   a1   a1   a1   b1  
a2   a2   a2   a23  a15  b1   b1   b1  
a2   a3   a2   a3   b1   b1   b1   b1  
a2   a2   a1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a1   b1   b1   b1   b1   b1   bG1  b1
|    |    |    |    | 
player_index=0
"""
        cases = [
            (24, 235),
            (25, 236),
            (26, 237),
            (27, 238),
            (2, 40),
            (1, 20),
            (3, 60),
            (4, 80),
            (5, 100),
            (6, 120),
            (7, 130),  # now we run out of 21 tiles within 1 extension, next best is a 10 @ 1,0 or 0,4
            (8, 140),  # ditto, other one
            (9, 141),  # next best is just a 2 (1)
            (10, 147),  # grab the 23 on 3,6 in place of the 11s
            (11, 161),  # add on the 4,6 15
            (12, 171),  # add the 11 back in
            (13, 181),  # add other 11 back in
            (14, 183),  # add a 3
            (15, 187),  # swap the 3 for 6 + 2 (so 183 - 2 + 6)
            (16, 197),  # swap the 11 for reaching for 21 + 2.  198 is possible but bot prioritizes returning to trunk, which is desireable, so i wont assert the 198.
            (17, 207),  # add the 11 back in. 208 ditto above
            (18, 214),
            (19, 224),
            (20, 226),
            (21, 230),
            (22, 232),
            (23, 233),
            (28, 239),
            (29, 240),
        ]

        targetsAreEnemyCases = [
            False,
            True,
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]

        inclNegative = False

        for depth, expectedGather in cases:
            if depth > 10:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
            for targetsAreEnemy in targetsAreEnemyCases:
                with self.subTest(depth=depth, expectedGather=expectedGather, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        expectedGather,
                        inclNegative,
                        targetsAreEnemy=targetsAreEnemy,
                        testTiming=False,
                        render=debugMode)

            with self.subTest(depth=depth, expectedGather=expectedGather, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather,
                    inclNegative,
                    testTiming=True,
                    render=False)

    def test_gather__basic_gather_all_combinations_of_true_val_neg_val(self):
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = """
|    |    |    |    |    |    |    |
aG1  a1   a2   a3   a2   a3   a1   a11
a1   a1   a1   a1   a1   a1   a1   a1  
a1   N10  N10  N10  N10  N10  a1   a3  
a2   a2                                
a2   a2   a2   a3   a2   a6   a2   a11
a2   a2   a2   a3   a1   a1   a1   b1  
a2   a2   a2   a23  a15  b1   b1   b1  
a2   a3   a2   a3   b1   b1   b1   b1  
a2   a2   a1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b2   b2   b2  
a1   b1   b1   b1   b1   b2   bG70 b2
|    |    |    |    | 
player_index=0
"""
        cases = [
            (3, 4),
            (1, 1),
            (2, 2),
            (4, 4),
            (5, 5),
            (6, 6),
            (7, 7),
            (8, 8),
            (9, 9),
            (10, 10),
            (11, 11),
            (12, 12),
            (13, 13),
            (14, 14),
            (15, 15),
            (16, 16),
            (17, 17),
            (18, 18),
            (19, 19),
            (20, 20),
            (21, 21),
            (22, 22),
            (23, 23),
            (24, 24),
            (25, 25),
            (26, 26),
            (27, 27),
            (28, 28),
            (29, 29),
        ]

        targetsAreEnemyCases = [
            False,
            True,
            None,
        ]

        incNegCases = [
            False,
            True
        ]

        trueValCases = [
            False,
            True
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]

        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        for depth, expectedGather in cases:
            if depth > 6:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
            for targetsAreEnemy in targetsAreEnemyCases:
                for useTrueGatherVal in trueValCases:
                    for incNegative in incNegCases:
                        with self.subTest(
                                depth=depth,
                                # expectedGather=expectedGather,
                                incNegative=incNegative,
                                useTrueGatherVal=useTrueGatherVal,
                                targetsAreEnemy=targetsAreEnemy
                        ):
                            self.run_adversarial_gather_test_all_algorithms(
                                testData,
                                targetXYs,
                                depth,
                                None,
                                inclNegative=incNegative,
                                useTrueVal=useTrueGatherVal,
                                targetsAreEnemy=targetsAreEnemy,
                                testTiming=False,
                                render=debugMode,
                                # incGreedy=False,
                                # incRecurse=False,
                            )

    def test_gather__adversarial_far_tiles_to_gather(self):
        """
        Test which represents a scenario where all of the players army is far from the main gather path, but is all clustered.
        Ideally the algo should find an optimal path to the cluster and then produce the main tree within the cluster, rather than producing suboptimal paths to the cluster.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = """
|    |    |    |    |    |    |    |
aG1  a2   a2   a2   a2   a2   a2   a2 
a2   a2   a2   a2   a2   a2   a2   a2  
a2   b1   b1   b1   b1   b1   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2 
a2   a2   a2   a2   a2   a2   a2   a2  
a2   a2   a2   a2   a2   a2   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a1   a2   a2   a1   a1   a1  
a10  a5   a5   a4   a5   a5   a5   a10
a10  a5   a5   a5   a5   a5   a10  a15
a15  a5   b5   b5   b5   b5   b5   a25
a20  b1   b1   b1   b1   b1   bG1  b1
|    |    |    |    | 
player_index=0
"""
        cases = [
            (24, 147),
            (1, 1),
            (2, 2),
            (3, 3),
            (4, 4),
            (5, 5),
            (6, 6),
            (7, 7),
            (8, 11),  # we can pick up our first 10
            (9, 17),  # our 5 and 10
            (10, 26),  # grab the 23 on 3,6 in place of the 11s
            (11, 40),
            (12, 59),  # 61 poss
            (13, 63),  # 65 poss
            (14, 67),  # 69 poss
            (15, 83),  # 83 if you switch to right side gather
            (16, 83),  #
            (17, 87),  #
            (18, 92),
            (19, 106),
            (20, 126),
            # for these higher ones, iterative produces two branches.
            # Need to implement a mid-tree disconnect-prune-reconnect approach to have it iteratively build a maximum connection in the tree
            (21, 135),
            (22, 142),
            (23, 146),
            (24, 147),
            (25, 151),
            (26, 165),
            (27, 169),
            (28, 173),
        ]

        targetsAreEnemyCases = [
            False,
            True,
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]
        inclNegative = True

        for depth, expectedGather in cases:
            if depth > 24:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
            for targetsAreEnemy in targetsAreEnemyCases:
                with self.subTest(depth=depth, expectedGather=expectedGather, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        expectedGather,
                        inclNegative,
                        targetsAreEnemy=targetsAreEnemy,
                        testTiming=False,
                        render=debugMode,
                        # incGreedy=False,
                        # incRecurse=False
                    )

            with self.subTest(depth=depth, expectedGather=expectedGather, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather,
                    inclNegative,
                    testTiming=True,
                    render=False)

    def test_gather__adversarial_far_tiles_to_gather__through_enemy_lines(self):
        """
        Same as test_gather__adversarial_far_tiles_to_gather, except must also break through a line of enemy tiles
        that divides the high value gather cluster from the low value cluster.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = """
|    |    |    |    |    |    |    |
aG1  a2   a2   a2   a2   a2   a2   a2 
a2   a2   a2   a2   a2   a2   a2   a2  
a2   b1   b1   b1   b1   b1   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2  
a2   a2   a2   a2   a2   a2   a2   a2 
b3   b3   b3   b3   b3   b3   b3   b3  
a2   a2   a2   a2   a2   a2   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a2   a1   a2   a1   a1   a1  
a1   a1   a1   a2   a2   a1   a1   a1  
a10  a5   a5   a4   a5   a5   a5   a10
a10  a5   a5   a5   a5   a5   a10  a15
a15  a5   b5   b5   b5   b5   b5   a25
a20  b1   b1   b1   b1   b1   bG1  b1
|    |    |    |    | 
player_index=0
"""
        cases = [
            (8, 9),
            (1, 1),
            (2, 2),
            (3, 3),
            (4, 4),
            (5, 5),
            (6, 6),
            (7, 7),
            (9, 17 - 2),  # our 5 and 10
            (10, 26 - 2),  # grab the 23 on 3,6 in place of the 11s
            (11, 40 - 2),
            (12, 59 - 2),  # 61 poss
            (13, 63 - 2),  # 65 poss
            (14, 67 - 2),  # 69 poss
            (15, 83 - 2),  # 83 if you switch to right side gather
            (16, 83 - 2),  #
            (17, 87 - 2),  #
            (18, 92 - 2),
            (19, 106 - 2),
            (20, 126 - 2),
            # for these higher ones, iterative produces two branches.
            # Need to implement a mid-tree disconnect-prune-reconnect approach to have it iteratively build a maximum connection in the tree
            (21, 135 - 4),
            (22, 139 - 4),
            (23, 143 - 4),
            (24, 147 - 4),
            (25, 151 - 4),
            (26, 165 - 4),
            (27, 169 - 4),
            (28, 173 - 4),
        ]

        targetsAreEnemyCases = [
            False,
            True,
        ]

        targetXYs = [
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (5, 2)
        ]

        inclNegative = True
        useTrueVal = False

        for depth, expectedGather in cases:
            for targetsAreEnemy in targetsAreEnemyCases:
                if depth > 7:
                    debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
                with self.subTest(depth=depth, expectedGather=expectedGather, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        expectedGather,
                        inclNegative,
                        useTrueVal=useTrueVal,
                        targetsAreEnemy=targetsAreEnemy,  # whether tiles are friendly or enemy should not matter to the amount gathered
                        testTiming=False,
                        render=debugMode,
                    )

            with self.subTest(depth=depth, expectedGather=expectedGather, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather,
                    inclNegative,
                    useTrueVal=useTrueVal,
                    targetsAreEnemy=True,
                    testTiming=True,
                    render=False,
                )

    def test_gather__adversarial_large_gather__big_map(self):
        """
        Same as test_gather__adversarial_far_tiles_to_gather, except must also break through a line of enemy tiles
        that divides the high value gather cluster from the low value cluster.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        testData = TextMapLoader.get_map_raw_string_from_file('GameContinuationEntries/should_not_do_infinite_intercepts_costing_tons_of_time___qg3nAW1cN---1--708.txtmap')
        cases = [
            35,
            45,
            55,
            65,
            75,
            85,
        ]

        targetXYs = [
            (23, 4),
        ]

        inclNegative = False
        useTrueVal = True

        for depth in cases:
            with self.subTest(depth=depth):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    expectedGather=None,
                    inclNegative=inclNegative,
                    useTrueVal=useTrueVal,
                    targetsAreEnemy=True,
                    testTiming=True,
                    render=debugMode,
                    playerIndex=1,
                )

    def test_gather__adversarial_to_large_iterative_gather_to_enemy_general(self):
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |
aG1  a11  a2   a3   a2   a3   a1   a21
a21  a21  a2   a2   a2   a1   a1   a1  
a21  b1   b1   b1   b1   b1   a2   a3  
a21  a21  a2   a2   a2   a1   a2   a1  
a11  a21  a2   a3   a2   a6   a2   a21
a2   a2   a2   a3   a1   a1   a1   b1  
a2   a2   a2   a23  a15  b1   b1   b1  
a2   a3   a2   a3   b1   b1   b1   b1  
a2   a2   a1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a2   a2   b1   b1   b1   b1   b1   b1  
a1   b1   b1   b1   b1   b1   bG1  b1
|    |    |    |    | 
player_index=0
"""
        cases = [
            (35),
            (27),
            (24),
            (25),
            (26),
            (2),
            (1),
            (3),
            (4),
            (5),
            (6),
            (7),  # now we run out of 21 tiles within 1 extension, next best is a 10 @ 1,0 or 0,4
            (8),  # ditto, other one
            (9),  # next best is just a 2 (1)
            (10),  # grab the 23 on 3,6 in place of the 11s
            (11),  # add on the 4,6 15
            (12),  # add the 11 back in
            (13),  # add other 11 back in
            (14),  # add a 3
            (15),  # swap the 3 for 6 + 2 (so 183 - 2 + 6)
            (16),  # swap the 11 for reaching for 21 + 2.  198 is possible but bot prioritizes returning to trunk, which is desireable, so i wont assert the 198.
            (17),  # add the 11 back in. 208 ditto above
            (18),
            (19),
            (20),
            (21),
            (22),
            (23),
            (28),
            (29),
        ]

        targetsAreEnemyCases = [
            # False,
            True,
        ]

        targetXYs = [
            (6, 13),
        ]

        inclNegative = False

        for depth in cases:
            if depth > 10:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
            for targetsAreEnemy in targetsAreEnemyCases:
                with self.subTest(depth=depth, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        0,
                        inclNegative,
                        targetsAreEnemy=targetsAreEnemy,
                        testTiming=False,
                        render=debugMode)

            with self.subTest(depth=depth, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    0,
                    inclNegative,
                    testTiming=True,
                    render=False)

    def test_gather__adversarial_to_large_iterative_gather_to_enemy_general__much_larger(self):
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  a11  a2   a2   a3   a3   a3   a3   a3   a3   a3   a2   a2   a3   a1   a3   a21
a21  a21  a2   a2   a2   a2   a2   M    a2   a2   a2   a2   a2   a1   a1   a2   a1  
a21  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   M    b1   b1   a2   b1   a3  
a2   a2   a2   a2   a3   a3   a3   M    a3   a3   a3   a1   a1   a1   a1   a3   M  
a21  a21  a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a1   a2   a2   M  
a11  a21  a2   a2   a3   a3   a3   a3   a3   a3   M    a2   a2   a6   a2   a3   a21
a2   a2   a2   a2   a3   a3   a3   a3   M    a3   a3   a1   a1   a1   a1   a3   b1  
a2   a2   a2   a2   a23                 M    a15  a15  b1   b1        b1  
a2   a2   a2   a2   a3   a1   a1   a1   a1   b15  b15  a1   a1   a1   a1   a1   b1  
a2   a2   a2   a2   a3   a1   a1   M    a1   b15  b15  a1   M    a1   a1   a1   b1  
a2   a2   a2   M    a23            b5   b5   a15  a15  b1   b1   b1   b5   
a2   a3   M    a2   a1   a3   a2   b3   b3   a1   a3   b1   b1   b1   b1   b3   b1  
a11  a21  a2   a2   a1   a3   a2   b3   b3   a1   a3   a2   a2   a6   a2   b3   a21
a2   a2   a2   a2   a1   a3   a2   b3   b3   a1   M    a1   a1   a1   a1   M    b1  
a2   a2   a2   a2   a23            b5   b5        M    a15  b1   b5   a5  
a2   a3   a2   a2   a3   M    a3   a3   a3   a3   a3   b1   b1   b1   b1   a3   b1  
a2   a2   M    a1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a2   a2   b1   b1   b1   b1   M    b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a30  b1   M    a30  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   bG1  b1   b1
|    |    |    |    |    |    |    |    |    |    |    |   | 
player_index=0
"""
        cases = [
            (65),
            (45),
            (35),
            (25),
            (15),
            (2),
            (1),
            (3),
            (4),
            (5),
            (6),
            (7),  # now we run out of 21 tiles within 1 extension, next best is a 10 @ 1,0 or 0,4
            (8),  # ditto, other one
            (9),  # next best is just a 2 (1)
            (10),  # grab the 23 on 3,6 in place of the 11s
            (11),  # add on the 4,6 15
            (12),  # add the 11 back in
            (13),  # add other 11 back in
            (14),  # add a 3
            (15),  # swap the 3 for 6 + 2 (so 183 - 2 + 6)
            (16),  # swap the 11 for reaching for 21 + 2.  198 is possible but bot prioritizes returning to trunk, which is desireable, so i wont assert the 198.
            (17),  # add the 11 back in. 208 ditto above
            (18),
            (19),
            (20),
            (21),
            (22),
            (23),
            (28),
            (29),
        ]

        targetsAreEnemyCases = [
            # False,
            True,
        ]

        targetXYs = [
            (14, 18),
        ]

        inclNegative = False

        for depth in cases:
            if depth > 10:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
            for targetsAreEnemy in targetsAreEnemyCases:
                with self.subTest(depth=depth, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        0,
                        inclNegative,
                        targetsAreEnemy=targetsAreEnemy,
                        useTrueVal=True,
                        testTiming=True,
                        render=debugMode)

            with self.subTest(depth=depth, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    0,
                    inclNegative,
                    testTiming=True,
                    render=False)

    def test_gather__adversarial_to_large_iterative_gather_to_enemy_general__much_larger__uniform_garbage(self):
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        @return:
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  a11  a2   a2   a3   a3   a3   a3   a3   a3   a3   a2   a2   a3   a1   a3   a3
a3   a3   a2   a2   a2   a2   a2   M    a2   a2   a2   a2   a2   a1   a1   a2   a1  
a3   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   M    b1   b1   a2   b1   a3  
a3   a2   a2   a2   a3   a3   a3   M    a3   a3   a3   a1   a1   a1   a1   a3   M  
a3   a3   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a1   a2   a2   M  
a3   a3   a2   a2   a3   a3   a3   a3   a3   a3   M    a2   a2   a6   a2   a3   a3 
a3   a2   a2   a2   a3   a3   a3   a3   M    a3   a3   a1   a1   a1   a1   a3   b1  
a3   a2   a2   a2   a3                  M    a15  a15  b1   b1        b1  
a3   a2   a2   a2   a3   a1   a1   a1   a1   b25  b25  a1   a1   a1   a1   a1   b1  
a3   a2   a2   a2   a3   a1   a1   M    a1   b25  b25  a1   M    a1   a1   a1   b1  
a3   a2   a2   M    a3             b5   b5   a15  a15  b1   b1   b1   b5   
a3   a3   M    a2   a1   a3   a2   b3   b3   a1   a3   b1   b1   b1   b1   b3   b1  
a3   a3   a2   a2   a1   a3   a2   b3   b3   a1   a3   a2   a2   a6   a2   b3   a3
a3   a2   a2   a2   a1   a3   a2   b3   b3   a1   M    a1   a1   a1   a1   M    b1  
a3   a2   a2   a2   a3             b5   b5        M    a15  b1   b5   a5  
a3   a3   a2   a2   a3   M    a3   a3   a3   a3   a3   b1   b1   b1   b1   a3   b1  
a3   a2   M    a1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   a2   b1   b1   b1   b1   M    b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   b1   M    a30  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   bG1  b1   b1
|    |    |    |    |    |    |    |    |    |    |    |   | 
player_index=0
"""
        cases = [
            (45),
            (35),
            (65),
            (25),
            (15),
            (2),
            (1),
            (3),
            (4),
            (5),
            (6),
            (7),  # now we run out of 21 tiles within 1 extension, next best is a 10 @ 1,0 or 0,4
            (8),  # ditto, other one
            (9),  # next best is just a 2 (1)
            (10),  # grab the 23 on 3,6 in place of the 11s
            (11),  # add on the 4,6 15
            (12),  # add the 11 back in
            (13),  # add other 11 back in
            (14),  # add a 3
            (15),  # swap the 3 for 6 + 2 (so 183 - 2 + 6)
            (16),  # swap the 11 for reaching for 21 + 2.  198 is possible but bot prioritizes returning to trunk, which is desireable, so i wont assert the 198.
            (17),  # add the 11 back in. 208 ditto above
            (18),
            (19),
            (20),
            (21),
            (22),
            (23),
            (28),
            (29),
        ]

        targetsAreEnemyCases = [
            # False,
            True,
        ]

        targetXYs = [
            (14, 18),
        ]

        inclNegative = False

        for depth in cases:
            if depth > 10:
                debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
            for targetsAreEnemy in targetsAreEnemyCases:
                with self.subTest(depth=depth, targetsAreEnemy=targetsAreEnemy):
                    self.run_adversarial_gather_test_all_algorithms(
                        testData,
                        targetXYs,
                        depth,
                        0,
                        inclNegative,
                        useTrueVal=True,
                        targetsAreEnemy=targetsAreEnemy,
                        testTiming=True,
                        render=debugMode)

            with self.subTest(depth=depth, timing=True):
                self.run_adversarial_gather_test_all_algorithms(
                    testData,
                    targetXYs,
                    depth,
                    0,
                    inclNegative,
                    useTrueVal=True,
                    testTiming=True,
                    render=False)

    def test_depth_gather_iterative(self):
        #
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  a11  a2   a2   a3   a3   a3   a3   a3   a3   a3   a2   a2   a3   a1   a3   a3
a3   a3   a2   a2   a2   a2   a2   M    a2   a2   a2   a2   a2   a1   a1   a2   a1  
a3   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   M    b1   b1   a2   b1   a3  
a3   a2   a2   a2   a3   a3   a3   M    a3   a3   a3   a1   a1   a1   a1   a3   M  
a3   a3   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a1   a2   a2   M  
a3   a3   a2   a2   a3   a3   a3   a3   a3   a3   M    a2   a2   a6   a2   a3   a3 
a3   a2   a2   a2   a3   a3   a3   a3   M    a3   a3   a1   a1   a1   a1   a3   b1  
a3   a2   a2   a2   a3                  M    a15  a15  b1   b1        b1  
a3   a2   a2   a2   a3   a1   a1   a1   a1   b25  b25  a1   a1   a1   a1   a1   b1  
a3   a2   a2   a2   a3   a1   a1   M    a1   b25  b25  a1   M    a1   a1   a1   b1  
a3   a2   a2   M    a3             b5   b5   a15  a15  b1   b1   b1   b5   
a3   a3   M    a2   a1   a3   a2   b3   b3   a1   a3   b1   b1   b1   b1   b3   b1  
a3   a3   a2   a2   a1   a3   a2   b3   b3   a1   a3   a2   a2   a6   a2   b3   a3
a3   a2   a2   a2   a1   a3   a2   b3   b3   a1   M    a1   a1   a1   a1   M    b1  
a3   a2   a2   a2   a3             b5   b5        M    a15  b1   b5   a5  
a3   a3   a2   a2   a3   M    a3   a3   a3   a3   a3   b1   b1   b1   b1   a3   b1  
a3   a2   M    a1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   a2   b1   b1   b1   b1   M    b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   b1   M    a30  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   bG1  b1   b1
|    |    |    |    |    |    |    |    |    |    |    |   | 
player_index=0
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 100)

        self.begin_capturing_logging()
        Gather.USE_DEBUG_ASSERTS = True
        start = time.perf_counter()
        targets = [enemyGeneral]
        depth = 65
        negativeTiles = set()
        useTrueVal = True
        inclNegative = False
        gatherMatrix = None
        iterDepthValGathered, iterDepthTurnsUsed, iterDepthNodes = Gather.knapsack_depth_gather_with_values(
            map,
            targets,
            depth,
            targetArmy=-1,
            distPriorityMap=None,
            negativeTiles=negativeTiles,
            searchingPlayer=map.player_index,
            viewInfo=None,
            useTrueValueGathered=useTrueVal,
            incrementBackward=False,
            includeGatherTreeNodesThatGatherNegative=inclNegative,
            priorityMatrix=gatherMatrix,
            cutoffTime=time.perf_counter() + 1.0,
            fastMode=False,
            shouldLog=False)

        # msg = f"FAST {iterDepthValGathered} / {expectedGather},  {iterDepthTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
        msg = f"ITER DEPTH {iterDepthValGathered} gathered in {iterDepthTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

        for n in iterDepthNodes:
            n.strip_all_prunes()
        if debugMode:
            viewInfo = self.get_renderable_view_info(map)
            # viewInfo.add_info_multi_line(f'ITER DEPTH')
            viewInfo.gatherNodes = iterDepthNodes
            self.render_view_info(map, viewInfo, msg)
        else:
            logbook.info(msg)

    def test_max_gather_iterative(self):
        #
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  a11  a2   a2   a3   a3   a3   a3   a3   a3   a3   a2   a2   a3   a1   a3   a3
a3   a3   a2   a2   a2   a2   a2   M    a2   a2   a2   a2   a2   a1   a1   a2   a1  
a3   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   M    b1   b1   a2   b1   a3  
a3   a2   a2   a2   a3   a3   a3   M    a3   a3   a3   a1   a1   a1   a1   a3   M  
a3   a3   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a1   a2   a2   M  
a3   a3   a2   a2   a3   a3   a3   a3   a3   a3   M    a2   a2   a6   a2   a3   a3 
a3   a2   a2   a2   a3   a3   a3   a3   M    a3   a3   a1   a1   a1   a1   a3   b1  
a3   a2   a2   a2   a3                  M    a15  a15  b1   b1        b1  
a3   a2   a2   a2   a3   a1   a1   a1   a1   b25  b25  a1   a1   a1   a1   a1   b1  
a3   a2   a2   a2   a3   a1   a1   M    a1   b25  b25  a1   M    a1   a1   a1   b1  
a3   a2   a2   M    a3             b5   b5   a15  a15  b1   b1   b1   b5   
a3   a3   M    a2   a1   a3   a2   b3   b3   a1   a3   b1   b1   b1   b1   b3   b1  
a3   a3   a2   a2   a1   a3   a2   b3   b3   a1   a3   a2   a2   a6   a2   b3   a3
a3   a2   a2   a2   a1   a3   a2   b3   b3   a1   M    a1   a1   a1   a1   M    b1  
a3   a2   a2   a2   a3             b5   b5        M    a15  b1   b5   a5  
a3   a3   a2   a2   a3   M    a3   a3   a3   a3   a3   b1   b1   b1   b1   a3   b1  
a3   a2   M    a1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   a2   b1   b1   b1   b1   M    b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   b1   M    a30  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   bG1  b1   b1
|    |    |    |    |    |    |    |    |    |    |    |   | 
player_index=0
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 100)

        self.begin_capturing_logging()
        Gather.USE_DEBUG_ASSERTS = True
        start = time.perf_counter()
        targets = [enemyGeneral]
        depth = 65
        negativeTiles = set()
        useTrueVal = True
        inclNegative = False
        gatherMatrix = None
        iterMaxValGathered, iterMaxTurnsUsed, iterMaxNodes = Gather.knapsack_max_gather_with_values(
            map,
            targets,
            depth,
            targetArmy=-1,
            distPriorityMap=None,
            negativeTiles=negativeTiles,
            searchingPlayer=map.player_index,
            viewInfo=None,
            useTrueValueGathered=useTrueVal,
            incrementBackward=False,
            includeGatherTreeNodesThatGatherNegative=inclNegative,
            priorityMatrix=gatherMatrix,
            cutoffTime=time.perf_counter() + 1.0,
            fastMode=False,
            shouldLog=False)

        # msg = f"FAST {iterMaxValGathered} / {expectedGather},  {iterMaxTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
        msg = f"ITER MAX {iterMaxValGathered} gathered in {iterMaxTurnsUsed} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

        for n in iterMaxNodes:
            n.strip_all_prunes()
        if debugMode:
            viewInfo = self.get_renderable_view_info(map)
            viewInfo.add_info_multi_line(f'ITER MAX is new variation of LIVE ITER that doesnt care about depth (aka cant be used for defense) and thus can use a heuristic depth first search instead of breadth first like normal ITER.')
            viewInfo.gatherNodes = iterMaxNodes
            self.render_view_info(map, viewInfo, msg)
        else:
            logbook.info(msg)

    def test_GathSetPruneReconnect(self):
        #
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  a11  a2   a2   a3   a3   a3   a3   a3   a3   a3   a2   a2   a3   a1   a3   a3
a3   a3   a2   a2   a2   a2   a2   M    a2   a2   a2   a2   a2   a1   a1   a2   a1  
a3   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   M    b1   b1   a2   b1   a3  
a3   a2   a2   a2   a3   a3   a3   M    a3   a3   a3   a1   a1   a1   a1   a3   M  
a3   a3   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a1   a2   a2   M  
a3   a3   a2   a2   a3   a3   a3   a3   a3   a3   M    a2   a2   a6   a2   a3   a3 
a3   a2   a2   a2   a3   a3   a3   a3   M    a3   a3   a1   a1   a1   a1   a3   b1  
a3   a2   a2   a2   a3                  M    a15  a15  b1   b1        b1  
a3   a2   a2   a2   a3   a1   a1   a1   a1   b25  b25  a1   a1   a1   a1   a1   b1  
a3   a2   a2   a2   a3   a1   a1   M    a1   b25  b25  a1   M    a1   a1   a1   b1  
a3   a2   a2   M    a3             b5   b5   a15  a15  b1   b1   b1   b5   
a3   a3   M    a2   a1   a3   a2   b3   b3   a1   a3   b1   b1   b1   b1   b3   b1  
a3   a3   a2   a2   a1   a3   a2   b3   b3   a1   a3   a2   a2   a6   a2   b3   a3
a3   a2   a2   a2   a1   a3   a2   b3   b3   a1   M    a1   a1   a1   a1   M    b1  
a3   a2   a2   a2   a3             b5   b5        M    a15  b1   b5   a5  
a3   a3   a2   a2   a3   M    a3   a3   a3   a3   a3   b1   b1   b1   b1   a3   b1  
a3   a2   M    a1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   a2   b1   b1   b1   b1   M    b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   b1   M    a30  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   bG1  b1   b1
|    |    |    |    |    |    |    |    |    |    |    |   | 
player_index=0
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 100)

        self.begin_capturing_logging()
        Gather.USE_DEBUG_ASSERTS = True
        Gather.USE_DEBUG_LOGGING = True
        start = time.perf_counter()
        targets = {enemyGeneral}
        depth = 65
        negativeTiles = set()
        useTrueVal = True
        inclNegative = False

        gatherMatrix = Gather.build_gather_capture_pure_value_matrix(map, general.player, negativeTiles, useTrueValueGathered=useTrueVal, prioritizeCaptureHighArmyTiles=False)

        plan = Gather.get_gather_plan_set_prune(
            map,
            targets,
            gatherMatrix,
            depth,
            negativeTiles=negativeTiles,
            viewInfo=None,
            useTrueValueGathered=useTrueVal,
            renderLive=False,
            # cutoffTime=time.perf_counter() + 1.0
        )

        # msg = f"FAST {iterMaxValGathered} / {expectedGather},  {iterMaxTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
        msg = f"GathSetPruneReconn {plan.gathered_army} gathered in {plan.length} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

        # for n in iterMaxNodes:
        #     n.strip_all_prunes()
        if debugMode:
            viewInfo = self.get_renderable_view_info(map)
            viewInfo.add_info_multi_line(f'GathSetPruneReconnect is new algo based around greedily pruning a connected set with no regard for disconnecting the graph, and then reconnecting it, and decreasing the prune likelihood of pruned nodes that were then used in a reconnect attempt')
            viewInfo.gatherNodes = plan.root_nodes
            self.render_view_info(map, viewInfo, msg)
        else:
            logbook.info(msg)

    def test_GatherMaxIterativeSet_PruneReconnect(self):
        #
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  a11  a2   a2   a3   a3   a3   a3   a3   a3   a3   a2   a2   a3   a1   a3   a3
a3   a3   a2   a2   a2   a2   a2   M    a2   a2   a2   a2   a2   a1   a1   a2   a1  
a3   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   M    b1   b1   a2   b1   a3  
a3   a2   a2   a2   a3   a3   a3   M    a3   a3   a3   a1   a1   a1   a1   a3   M  
a3   a3   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a1   a2   a2   M  
a3   a3   a2   a2   a3   a3   a3   a3   a3   a3   M    a2   a2   a6   a2   a3   a3 
a3   a2   a2   a2   a3   a3   a3   a3   M    a3   a3   a1   a1   a1   a1   a3   b1  
a3   a2   a2   a2   a3                  M    a15  a15  b1   b1        b1  
a3   a2   a2   a2   a3   a1   a1   a1   a1   b25  b25  a1   a1   a1   a1   a1   b1  
a3   a2   a2   a2   a3   a1   a1   M    a1   b25  b25  a1   M    a1   a1   a1   b1  
a3   a2   a2   M    a3             b5   b5   a15  a15  b1   b1   b1   b5   
a3   a3   M    a2   a1   a3   a2   b3   b3   a1   a3   b1   b1   b1   b1   b3   b1  
a3   a3   a2   a2   a1   a3   a2   b3   b3   a1   a3   a2   a2   a6   a2   b3   a3
a3   a2   a2   a2   a1   a3   a2   b3   b3   a1   M    a1   a1   a1   a1   M    b1  
a3   a2   a2   a2   a3             b5   b5        M    a15  b1   b5   a5  
a3   a3   a2   a2   a3   M    a3   a3   a3   a3   a3   b1   b1   b1   b1   a3   b1  
a3   a2   M    a1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   a2   b1   b1   b1   b1   M    b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   b1   M    a30  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   bG1  b1   b1
|    |    |    |    |    |    |    |    |    |    |    |   | 
player_index=0
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 100)

        self.begin_capturing_logging()
        Gather.USE_DEBUG_ASSERTS = True
        Gather.USE_DEBUG_LOGGING = True
        start = time.perf_counter()
        targets = {enemyGeneral}
        depth = 65
        negativeTiles = set()
        useTrueVal = True
        inclNegative = False

        gatherMatrix = Gather.build_gather_capture_pure_value_matrix(map, general.player, negativeTiles, useTrueValueGathered=useTrueVal, prioritizeCaptureHighArmyTiles=False)
        armyCostMatrix = Gather.build_gather_capture_pure_value_matrix(map, general.player, negativeTiles, useTrueValueGathered=True, prioritizeCaptureHighArmyTiles=False)

        plan = Gather.gather_max_set_iterative_plan(
            map,
            targets,
            depth,
            gatherMatrix,
            armyCostMatrix,
            # negativeTiles=negativeTiles,
            renderLive=False,
            viewInfo=None,
            searchingPlayer=general.player

            # useTrueValueGathered=useTrueVal,
            # renderLive=False,
            # cutoffTime=time.perf_counter() + 1.0
        )

        # msg = f"FAST {iterMaxValGathered} / {expectedGather},  {iterMaxTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"
        msg = f"GatherMaxSet PRUNE RECON {plan.gathered_army} gathered in {plan.length} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

        # for n in iterMaxNodes:
        #     n.strip_all_prunes()
        if debugMode:
            viewInfo = self.get_renderable_view_info(map)
            viewInfo.add_info_multi_line(f'GatherMaxSet PRUNE RECONNECT is a set-based (instead of tree based) variant of LIVE ITER, that allows for non breadth-first traversal via heuristics, and prunes naively and reconnects intelligently, all while building up the same iterative process as normal LIVE ITER.')
            viewInfo.gatherNodes = plan.root_nodes
            self.render_view_info(map, viewInfo, msg)
        else:
            logbook.info(msg)

    def test_GatherMaxIterativeSet_PruneReconnect__Profile(self):
        #
        """
        Produces a scenario where gathers max value paths produce results away from the main cluster, and
         where leaves on suboptimal parts of the cluster are intentionally larger than leaves on optimal parts of the
         cluster to try to induce suboptimal prunes that prune the lower value leaves from the higher value cluster
         over the higher value leaves from the poorer-value-per-turn offshoots, leaving a suboptimal gather plan.
        """
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        testData = """
|    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |    |
aG1  a11  a2   a2   a3   a3   a3   a3   a3   a3   a3   a2   a2   a3   a1   a3   a3
a3   a3   a2   a2   a2   a2   a2   M    a2   a2   a2   a2   a2   a1   a1   a2   a1  
a3   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   M    b1   b1   a2   b1   a3  
a3   a2   a2   a2   a3   a3   a3   M    a3   a3   a3   a1   a1   a1   a1   a3   M  
a3   a3   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a2   a1   a2   a2   M  
a3   a3   a2   a2   a3   a3   a3   a3   a3   a3   M    a2   a2   a6   a2   a3   a3 
a3   a2   a2   a2   a3   a3   a3   a3   M    a3   a3   a1   a1   a1   a1   a3   b1  
a3   a2   a2   a2   a3                  M    a15  a15  b1   b1        b1  
a3   a2   a2   a2   a3   a1   a1   a1   a1   b25  b25  a1   a1   a1   a1   a1   b1  
a3   a2   a2   a2   a3   a1   a1   M    a1   b25  b25  a1   M    a1   a1   a1   b1  
a3   a2   a2   M    a3             b5   b5   a15  a15  b1   b1   b1   b5   
a3   a3   M    a2   a1   a3   a2   b3   b3   a1   a3   b1   b1   b1   b1   b3   b1  
a3   a3   a2   a2   a1   a3   a2   b3   b3   a1   a3   a2   a2   a6   a2   b3   a3
a3   a2   a2   a2   a1   a3   a2   b3   b3   a1   M    a1   a1   a1   a1   M    b1  
a3   a2   a2   a2   a3             b5   b5        M    a15  b1   b5   a5  
a3   a3   a2   a2   a3   M    a3   a3   a3   a3   a3   b1   b1   b1   b1   a3   b1  
a3   a2   M    a1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   a2   b1   b1   b1   b1   M    b1   b1   b1   b1   b1   b1   b1   b1   b1   a5  
a3   b1   M    a30  b1   b1   b1   b1   b1   b1   b1   b1   b1   b1   bG1  b1   b1
|    |    |    |    |    |    |    |    |    |    |    |   | 
player_index=0
        """
        map, general, enemyGeneral = self.load_map_and_generals_from_string(testData, 100)

        #     ...
        #     print(f"{fib(35) = }")
        # ...(
        #     ...
        # Stats(profile)
        # ....strip_dirs()
        # ....sort_stats(SortKey.CALLS)
        # ....print_stats()
        # ...     )
        self.begin_capturing_logging()
        Gather.USE_DEBUG_ASSERTS = True
        Gather.USE_DEBUG_LOGGING = True
        start = time.perf_counter()
        targets = {enemyGeneral}
        depth = 65
        negativeTiles = set()
        useTrueVal = True
        inclNegative = False

        gatherMatrix = Gather.build_gather_capture_pure_value_matrix(map, general.player, negativeTiles, useTrueValueGathered=useTrueVal, prioritizeCaptureHighArmyTiles=False)
        armyCostMatrix = Gather.build_gather_capture_pure_value_matrix(map, general.player, negativeTiles, useTrueValueGathered=True, prioritizeCaptureHighArmyTiles=False)

        from cProfile import Profile
        from pstats import SortKey, Stats
        with Profile() as profile:
            plan = Gather.gather_max_set_iterative_plan(
                map,
                targets,
                depth,
                gatherMatrix,
                armyCostMatrix,
                # negativeTiles=negativeTiles,
                renderLive=False,
                viewInfo=None,
                searchingPlayer=general.player

                # useTrueValueGathered=useTrueVal,
                # renderLive=False,
                # cutoffTime=time.perf_counter() + 1.0
            )
            msg = f"GatherMaxSet PRUNE RECON {plan.gathered_army} gathered in {plan.length} moves ({depth} requested) in {(time.perf_counter() - start) * 1000.0:.1f}ms"

            (
                Stats(profile)
                .strip_dirs()
                .sort_stats(SortKey.CALLS)
                .print_stats(20)
            )
            (
                Stats(profile)
                .strip_dirs()
                .sort_stats(SortKey.TIME)
                .print_stats(20)
            )

        # msg = f"FAST {iterMaxValGathered} / {expectedGather},  {iterMaxTurnsUsed} / {depth} in {(time.perf_counter() - start) * 1000.0:.1f}ms"

        # for n in iterMaxNodes:
        #     n.strip_all_prunes()
        if debugMode:
            viewInfo = self.get_renderable_view_info(map)
            viewInfo.add_info_multi_line(f'GatherMaxSet PRUNE RECONNECT is a set-based (instead of tree based) variant of LIVE ITER, that allows for non breadth-first traversal via heuristics, and prunes naively and reconnects intelligently, all while building up the same iterative process as normal LIVE ITER.')
            viewInfo.gatherNodes = plan.root_nodes
            self.render_view_info(map, viewInfo, msg)
        else:
            logbook.info(msg)