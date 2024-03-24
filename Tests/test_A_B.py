from TestBase import TestBase
from bot_ek0x45 import EklipZBot


class ABTests(TestBase):
    def test__mcts_should_always_win__vs__brute_force__top_left_bottom_right(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'SymmetricTestMaps/even_playground_map_small__top_left_bot_right.txtmap'

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__mcts_should_always_win__vs__brute_force__top_right_bottom_left(self):
        numRuns = 50
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'SymmetricTestMaps/even_playground_map_small__top_right_bot_left.txtmap'

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            # aBot.mcts_engine.final_playout_estimation_depth = 1
            aBot.engine_honor_mcts_expanded_expected_score = True
            aBot.engine_army_nearby_tiles_range = 6

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False
            # this was how brute force was during the original testing.
            bBot.engine_allow_enemy_no_op = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__mcts_should_always_win__vs__brute_force__left_right(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True
        mapFile = 'SymmetricTestMaps/even_playground_map_small__left_right.txtmap'

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            aBot.engine_force_multi_tile_mcts = True

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False
            # this was how brute force was during the original testing.
            bBot.engine_allow_enemy_no_op = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__brute_force_should_beat_no_engine(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = False

            # original brute force had this false while it was true for mcts.
            # it is now true for both. and brute force is still beating no engine.
            # 13-7
            # aBot.engine_allow_enemy_no_op = False

            # see if brute force does better with the force or not.
            # brute force lost 9-11 with this, lol.
            # aBot.engine_allow_force_incoming_armies_towards = True

            # aBot.engine_allow_enemy_no_op = False

        def configure_b(bBot: EklipZBot):
            bBot.disable_engine = True

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__mcts_should_beat_no_engine(self):
        numRuns = 20
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            # hodgepodge of currently winning a-b tests
            # 10-9
            # aBot.mcts_engine.total_playout_move_count = 6
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 0
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = 0
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = True
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5

            #13-7
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.RobustChild)
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = True
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5

            # (Same as above but using maxValue selection instead of robust child)
            # 10-10

            # try robust child again?
            # 12-7, codified
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.RobustChild)

            # 12-8...?
            # 15-5
            # 11-9
            # TODO come back to this.
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = False

            # nothing? 10-10

            # 10-10 D:
            # aBot.engine_force_multi_tile_mcts = True

        def configure_b(bBot: EklipZBot):
            bBot.disable_engine = True

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__mcts_should_always_win__vs__brute_force__left_vs_right(self):
        mapFile = 'SymmetricTestMaps/even_playground_map_small__left_right.txtmap'
        numRuns = 100
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_a(aBot: EklipZBot):
            aBot.engine_use_mcts = True
            # 4 went 46-54
            # 2 went 51-48
            # aBot.mcts_engine.final_playout_estimation_depth = 2

            # aBot.mcts_engine.final_playout_estimation_depth = 2
            aBot.engine_honor_mcts_expanded_expected_score = True

        def configure_b(bBot: EklipZBot):
            bBot.engine_use_mcts = False
            bBot.engine_allow_enemy_no_op = False

        self.a_b_test(numRuns, configureA=configure_a, configureB=configure_b, debugMode=debugMode, mapFile=mapFile)

    def test__A_B_test_mcts__num1__left_vs_right(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_b(bBot: EklipZBot):
            # bBot.behavior_max_allowed_quick_expand = 5
            pass

        def configure_a(aBot: EklipZBot):
            # 163-190...? AGAIN
            # 246-220, AGAIN
            # 207-174
            # aBot.behavior_max_allowed_quick_expand = 7  # b 5

            # 143-119, AGAIN but codifying in the meantime
            # 218-241, AGAIN
            # 259-206
            # aBot.behavior_max_allowed_quick_expand = 8  # b 5
            # aBot.behavior_pre_gather_greedy_leaves_army_ratio_cutoff = 1.02  # was 0.98

            # try just 0.98
            # 98-85, try again
            # 215-178
            # aBot.behavior_pre_gather_greedy_leaves_army_ratio_cutoff = 0.98  # was 0.95

            # 133-133
            # aBot.behavior_pre_gather_greedy_leaves_army_ratio_cutoff = 0.98  # was 0.95
            # aBot.behavior_pre_gather_greedy_leaves_offset = -7  # was -5

            # 138-162.
            # aBot.behavior_pre_gather_greedy_leaves_offset = -15  # was -5

            # # 249-213
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 1  # b is 5. 10 is actually the old value
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 1

            # 230-243, pretty meaningless. Try 1...?
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 10  # b is 5. 10 is actually the old value

            # 232-227, meaningless
            # aBot.mcts_engine.explore_factor = 1.0

            # 221-236
            # aBot.mcts_engine.explore_factor = 1.1  # b 1.05

            # 121-127
            # aBot.mcts_engine.explore_factor = 0.95  # b 1.05

            # 126-121, AGAIN
            # 130-118, FUCK
            # TODO circle back to this
            # aBot.engine_allow_enemy_no_op = False

            # 120-125
            # aBot.behavior_losing_on_economy_skip_defense_threshold = 0.9

            #47-53, again
            #70-97, meh
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 4  # was 0

            # 244-256
            # aBot.expansion_allow_leaf_moves = False

            # doesn't seem to do too much, but does seem to lose.
            # aBot.mcts_engine.explore_factor = 1.5

            # # a winning!? nvm pretty even-ish
            # aBot.mcts_engine.utility_compression_ratio = 0.005
            # bBot.mcts_engine.utility_compression_ratio = 0.01

            # not meaningful
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 10
            # aBot.mcts_engine.total_playout_move_count = 15

            # so far, significant. WHOO won quite a few in a row. Codified.
            # aBot.allow_force_incoming_armies_towards = False

            # seemed about 50-50...? Maybe slightly better, worth coming back to
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 5
            # aBot.mcts_engine.total_playout_move_count = 7

            # failure
            # aBot.mcts_engine.biased_move_ratio_while_available = 1.0
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 5
            # aBot.mcts_engine.total_playout_move_count = 4
            # aBot.mcts_engine.min_random_playout_moves_initial = 2

            # this shit does nothing...?
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue)
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 5
            # aBot.mcts_engine.total_playout_move_count = 4

            # seems to be winning, codified
            # aBot.mcts_engine.eval_params.kills_friendly_armies_10_fraction = -10
            # aBot.mcts_engine.eval_params.kills_enemy_armies_10_fraction = 10

            # seems to be winning, codified
            # aBot.mcts_engine.explore_factor = 1.3

            # seems to be winning! codified
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue)
            # aBot.mcts_engine.explore_factor = 1.5

            # bad
            # aBot.mcts_engine.utility_compression_ratio = 0.03
            # aBot.mcts_engine.utility_compression_ratio = 0.005

            # seems good, codified
            # aBot.mcts_engine.total_playout_move_count = 6

            # a won 193 vs b won 200. So my biased stuff is fucked, good to know. Disabling it for now.
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.1
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 2

            # TODO above might be last good change? Everything after inversed? Start reverse verifying...
            # 28-21, re-codified for now. Come back to this.
            # aBot.mcts_engine.total_playout_move_count = 6

            ####### ok this was 18-32 loss, the 'dont propogate initial results' is correct.
            # 22-28 on re-verification.
            # aBot.mcts_engine.skip_first_result_backpropogation = False

            # ###20-18, maybe just because more iterations? Keep trying.
            # ######18-22, so 38-40. try again
            # #####22-18, so 60-58. Seems meaningless.
            # #####TODO revisit later after tuning other things.
            # 28-22, try again.
            # 24-26 after starting by winning almost 10 in a row, wtf distribution. AGAIN!
            # 32-18, so 84-66, codified
            # aBot.mcts_engine.allow_random_repetitions = True

            # #####24-15? Continuing
            # ######round 2, 28-22 so 52-37. Codifying as 4.
            # test 5 again.
            # 23-27. TEST AGAIN.
            # 24-26. OK TRY HIGHER :D
            # aBot.mcts_engine.total_playout_move_count = 5

            # 27-22, AGAIN
            # 28-22 codifying
            # aBot.mcts_engine.total_playout_move_count = 7

            # try 8?
            # 46-54 ok 7 it is.
            # aBot.mcts_engine.total_playout_move_count = 8

            # 53-44, AGAIN
            # 115-132, (so 168-176). try reducing to 1?
            # aBot.mcts_engine.min_random_playout_moves_initial = 3

            # 133-113, AGAIN
            # killed at 20-15, codifying
            # aBot.mcts_engine.min_random_playout_moves_initial = 1

            # 135-115, codified. Confirmed by expanded_expected vs _expected which won by similar marging, and just _expected won against none at all, so very conclusively good.
            # aBot.engine_honor_mcts_expanded_expected_score = True

            # killed 61-79
            # 114-131 fml
            # aBot.engine_army_nearby_tiles_range = 6  # was 4. 5 being tested in parallel, as well.

            # try 3
            # killed 45-70
            # aBot.engine_army_nearby_tiles_range = 3  # was 4. 5 being tested in parallel, as well.
            # ok so based on the other data I think we need to increase range but reduce the armies-per-scrim limit for now. To like, 3 or 2 or something.

            # 117-130, try 6?
            # aBot.engine_army_nearby_tiles_range = 8
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 120-125
            # aBot.engine_army_nearby_tiles_range = 6
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 90-158
            # aBot.expansion_use_multi_per_dist_per_tile = True  # note no force single
            # aBot.expansion_single_iteration_time_cap = 0.01

            # 121-94. Unclear based on other runs, and dont know what B was. Rerunning against b=2
            # 116-132, so 2 seems to be winner. Try 1...?
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 3

            # 84-79 killed due to lots of errors, restarting
            # 120-130
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 1
            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__A_B_test_mcts__num2__left_vs_right(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_b(bBot: EklipZBot):
            pass

        def configure_a(aBot: EklipZBot):
            # killed 189-189, wtf...? Trying again
            # 180-197
            aBot.mcts_engine.explore_factor = 0.2  # current = 1.05

            # killed 184-175
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 30  # b 15

            #196-160, AGAIN but pre-codifying
            # 237-229
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 15  # b 20

            # 197-191
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -0.9  # b 0

            # 219-240
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 0.9  # b 0

            # killed 92-95, try 0.9
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 1.9  # b 0

            # killed at 80-61 is I realized I needed to divide by 10
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 3  # b 0

            # 130-127
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 2

            # 139-121, AGAIN
            # killed 132-111 because already codified 0.98 and testing 1.02
            # aBot.behavior_pre_gather_greedy_leaves_army_ratio_cutoff = 1.0  # was 0.95

            # 138-166
            # aBot.behavior_pre_gather_greedy_leaves_army_ratio_cutoff = 0.9  # was 0.95

            # # 267-202, codified
            # aBot.expansion_force_no_global_visited = False  # was true, AFTER the expansion fixups. Trying false.

            # running as-is against old,
            # 222-156
            # aBot.expansion_force_no_global_visited = False  # was true

            # b is 50. This should literally not
            # matter, at all. Should be purely visual for how robust the path we render on screen is,
            # shouldn't affect actual move selection in the slightest.
            # 228-222 so ok, pretty meaningless yeah.
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 1

            # 137-112, AGAIN with it as fucked as it is now
            # 119-115, meh, again.
            # 200-266
            # aBot.expansion_use_cutoff = False

            # 117-133
            # aBot.behavior_losing_on_economy_skip_defense_threshold = 0.8

            #58-68, bad
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 2

            # 70-108, definitely bad
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -1

            # 40-60, trying -1
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -6

            # 25-25, codifying for now.
            # aBot.mcts_engine.offset_initial_differential = True

            # ####187-204, so, bad.
            # retrying, 21-28, so ok, legit bad.
            # aBot.mcts_engine.offset_initial_differential = True
            # aBot.mcts_engine.utility_compression_ratio = 0.07

            # 21-29 yikes
            # aBot.mcts_engine.utility_compression_ratio = 0.03

            # try other direction...?
            # 22-28
            # if bad, try scaling down explore to compensate.
            # 28-22, try MORE
            # 51-47 (so 79-69, codified! WHOO!)
            # aBot.mcts_engine.utility_compression_ratio = 0.005
            # aBot.mcts_engine.explore_factor = 1.1

            # play with it a bit more.
            # 48-52, lets try a bit lower
            # aBot.mcts_engine.utility_compression_ratio = 0.007
            # aBot.mcts_engine.explore_factor = 1.1

            #lower
            # 56-44, codified
            # aBot.mcts_engine.utility_compression_ratio = 0.004
            # aBot.mcts_engine.explore_factor = 1.1

            # try even lower...?
            # 47-52, .0035?
            # aBot.mcts_engine.utility_compression_ratio = 0.003
            # aBot.mcts_engine.explore_factor = 1.1

            # 123-122, perfectly even. Try in tweaking explore factor......?
            # aBot.mcts_engine.utility_compression_ratio = 0.0035
            # aBot.mcts_engine.explore_factor = 1.1

            # Try in tweaking explore factor
            # 134-112, AGAIN but codified
            # 115-133, test again...?
            # aBot.mcts_engine.utility_compression_ratio = 0.004  # emptyVal, just noting
            # aBot.mcts_engine.explore_factor = 1.0  # was 1.1 when starting this run

            # try 1.05...?
            # killed 81-75, codifying...? I'm bored of this
            # aBot.mcts_engine.utility_compression_ratio = 0.004  # emptyVal, just noting
            # aBot.mcts_engine.explore_factor = 1.05  # was 1.0 when starting this run

            # TESTING B == 0.0
            # 124-124
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.5

            # b = 0.5
            # codified in advance, at 126-105
            # 130-116
            # wait, what? with b at 0.5 this went 86-160
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.85

            # accidentally killed 52-66 but wanted to switch to dist 3 anyway
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.0
            # aBot.gather_include_distance_from_enemy_general_large_map_as_negatives = 0.0

            # just per_tile
            # 78-172 lol
            # aBot.expansion_use_multi_per_tile = True
            # aBot.expansion_force_no_global_visited = False

            # 104-118, try again inversed...?
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 2  # was 0 but codified in the meantime

            # 112-138
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 1  # b is 2
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4  # b is 3

            # 129-119 buth other one went 120-130 so even, try again.
            # 218-279, ok definitely bad
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4  # b is 3

            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__A_B_test_mcts__num3__left_vs_right(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_b(bBot: EklipZBot):
            # bBot.mcts_engine.explore_factor = 1.05  # current = 1.05
            # # bBot.mcts_engine.biased_move_ratio_while_available = 0.47
            pass

        def configure_a(aBot: EklipZBot):
            aBot.mcts_engine.explore_factor = 0.5  # current = 0.5
            aBot.mcts_engine.utility_compression_ratio = 0.002  # current 0.004

            # 169-210
            # 173-215
            # aBot.mcts_engine.explore_factor = 0.1  # current = 1.05
            # aBot.mcts_engine.utility_compression_ratio = 0.01  # current 0.004

            # 201-202
            # aBot.mcts_engine.explore_factor = 0.5  # current = 1.05
            # aBot.mcts_engine.utility_compression_ratio = 0.01  # current 0.004

            # killed 185-185
            # aBot.mcts_engine.explore_factor = 0.5  # current = 1.05
            # aBot.mcts_engine.utility_compression_ratio = 0.015  # current 0.004

            # 180-190
            # aBot.behavior_max_allowed_quick_expand = 6  # b 7

            # 101-84
            # aBot.behavior_max_allowed_quick_expand = 7  # b 8

            # 209-239
            # aBot.behavior_max_allowed_quick_expand = 10  # b 8

            # 226-221
            # aBot.behavior_max_allowed_quick_expand = 3  # b 5

            # killed 22-40
            # aBot.behavior_max_allowed_quick_expand = 0

            # try 3 (b is -5)
            # 151-113, AGAIN
            # codified at 20-11 but continuing to run, which got 192-181
            # aBot.behavior_pre_gather_greedy_leaves_offset = -3

            # 130-156
            # aBot.behavior_pre_gather_greedy_leaves_offset = -10

            # killed 239-143
            # aBot.expansion_force_global_visited_stage_1 = True  # was false
            # aBot.expansion_force_no_global_visited = True  # was true

            # 219-243
            # aBot.expansion_use_cutoff = False
            # aBot.expansion_use_leaf_moves_first = True

            # 117-120, meaningless.
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.42

            # aBot.mcts_engine.biased_move_ratio_while_available = 0.47  # 129-115 vs b 0.53

            # was 48-52 or something in another test, but 0.45 is showing promise.
            # 121-128, so 0.4 too low
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.4

            # 107-140
            # aBot.behavior_losing_on_economy_skip_defense_threshold = 0.85

            # 88-92, meaningless, again
            # 50-69, bad
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = +1

            # 39-58, try +1
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -20

            # Test reverting the no op bonus...
            # 24-26
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 0
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = 0

            # try middle ground
            # 25-25, seems this doesn't matter...?
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 5
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -5

            # try increasing it a bit to 1 full econ...?
            # 23-27
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 10
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -10

            # try asymmetric enemy vs friendly...?
            # 27-23, try more.
            # 29-31, f it.
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 12
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -5

            # try near 0 one more time..
            # 24-26, meaningless. Ok ignore.
            # aBot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 2
            # aBot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = -2

            # play with penalty
            # 46-52, try increasing...?
            # aBot.mcts_engine.eval_params.friendly_move_penalty_10_fraction = 0
            # aBot.mcts_engine.eval_params.enemy_move_penalty_10_fraction = 0

            # 46-54, try again, variance...?
            # 58-42 lol...? AGAIN?
            # 129-118, AGAIN @ 233-214 ACTUALLY NVM WHO CARES CODIFIED FOR NOW LETS TEST MORE INTERESTING STUFF LIKE FINAL PLAYOUT
            # aBot.mcts_engine.eval_params.friendly_move_penalty_10_fraction = 4
            # aBot.mcts_engine.eval_params.enemy_move_penalty_10_fraction = -4

            # 108-142 :s
            # aBot.mcts_engine.final_playout_estimation_depth = 4

            # try reducing to 2...?
            # aBot.mcts_engine.final_playout_estimation_depth = 2

            # 131-118, confirms other results too, codified.
            # aBot.engine_honor_mcts_expanded_expected_score = True
            # aBot.engine_honor_mcts_expected_score = False

            # killed 82-88, again
            # 123-124, meaningless or worse
            # aBot.engine_army_nearby_tiles_range = 5  # was 4

            # codified, 128-119
            # aBot.mcts_engine.eval_params.always_reward_dead_army_no_ops = True  # was false

            # 108-138, huh
            # aBot.engine_army_nearby_tiles_range = 6
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3

            # what about range 5...?
            # 122-125
            # aBot.engine_army_nearby_tiles_range = 5
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3

            # try 3.....?
            # 125-123. What about a lower limit?
            # aBot.engine_army_nearby_tiles_range = 5
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3

            # 106-131
            # aBot.engine_army_nearby_tiles_range = 5
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 125-104, codified
            # aBot.engine_army_nearby_tiles_range = 4
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 115-135, ok per tile is worse as expected.
            # aBot.expansion_use_multi_per_tile = True
            # aBot.expansion_use_multi_per_dist_per_tile = False

            # 117-132
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.5  # was 0

            # 262-236, interesting. Codified.
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 7  # current 4

            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__A_B_test_mcts__num4__left_vs_right(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_b(bBot: EklipZBot):
            pass

        def configure_a(aBot: EklipZBot):
            aBot.mcts_engine.explore_factor = 0.15  # current = 1.05

            # 231-237
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 25  # b 15

            # 189-191
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 25  # b 20

            # 222-233
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 30  # b 20

            # 214-243, try 30...?
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 40  # b 20

            # killed 106-139
            # aBot.engine_honor_mcts_expected_score = True
            # aBot.engine_honor_mcts_expanded_expected_score = False

            # 106-111 when b was 1 I think
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 5
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 6

            # codified in advance but ended up 112-108
            # aBot.behavior_pre_gather_greedy_leaves_offset = 0  # b is -3

            # killed 121-133 because codified other direction already.
            # aBot.behavior_pre_gather_greedy_leaves_army_ratio_cutoff = 0.9  # b is 0.95

            # 142-149, AGAIN
            # 125-132
            # aBot.behavior_allow_pre_gather_greedy_leaves = False  # b true obviously

            # 249-214, codified. Thought this was already codified, weird.
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue)

            # fully codified, killed 252-144=1.75 exactly
            # aBot.expansion_force_global_visited_stage_1 = True  # was false
            # aBot.expansion_force_no_global_visited = True  # was true
            # aBot.expansion_use_iterative_negative_tiles = True  # was false

            # 244-228, already codified. Retest, though
            # hung 96-83
            # aBot.expansion_use_leaf_moves_first = True

            # promising in another test so pre-emptively starting this run to get more confirmation.
            # 250-245. AGAIN vs 0.4
            # 239-227, however in other test it did 229-265 so i'm confused. Again...? This is feeling like a waste of time. Not running again.
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.45

            # 230-265
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = False  # currently true

            # 27-23 after fixing a-b. Trying more. (now with offset true and 6 rollouts):
            # 29-21, codifying. :D BIASED IS BACK BABYYYYY
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = True
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5

            # try leaving bias up but re-including positional win detection:
            # 31-19, fucking, bias worked the whole time and we didn't need this shit...?
            # try again. 20-30 lmao, so 51-49, try again...?
            # 26-24, seems basically completely even weirdly enough.
            # TODO come back and play with this later after tweaking other bias stuff.
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = False

            # play with biased moves always first.
            # 24-26, try again.
            # 47-53, ok. what about 75% of the time?
            # aBot.mcts_engine.biased_move_ratio_while_available = 1.0
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4

            # 47-53 again. Try lower...?
            # 48-51, ignore for now
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.4
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 4

            # try 7->8 with high sim count
            # 159-134, ok so bigger is better...? AGAIN just to be sure.
            # 150-145, codifying
            # aBot.mcts_engine.total_playout_move_count = 8

            # 153-146, nuked in favor of _expanded_expected_score which did much better both against this and against neither.
            # aBot.engine_honor_mcts_expected_score = True

            # killed 80-76, again
            # killed at 140-124, codified
            # aBot.engine_mcts_scrim_armies_per_player_limit = 3  # currently 4

            # 158-137, codified...?
            # aBot.expansion_single_iteration_time_cap = 0.03  # currently 0.02
            # re-confirm but flipped, b is 0.03 now and this is 0.02

            # 145-149, about even
            # aBot.expansion_single_iteration_time_cap = 0.02  # currently 0.03

            # 134-162. Ok, try 10
            # aBot.mcts_engine.total_playout_move_count = 15  # current 8

            # even
            # aBot.mcts_engine.total_playout_move_count = 10  # current 8

            # 146-128, codified
            # aBot.engine_always_include_last_move_tile_in_scrims = True  # was false but codified in meantime

            # 136-162
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 3  # was 2

            # 120-130
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 4 # was 3

            # 123-127
            # aBot.expansion_single_iteration_time_cap = 0.12

            # 254-243. Confirming with another run since previous runs indicated otherwise. This may have changed due to the 'tiles gathered to this turn' de-restriction?
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 3  # currently 2
            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode)

    def test__A_B_test_mcts__num5__left_vs_right(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False

        def configure_b(bBot: EklipZBot):
            # bBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.RobustChild)
            # bBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 1
            pass

        def configure_a(aBot: EklipZBot):
            # pre-codifying but current is True
            #213-183
            aBot.behavior_allow_defense_army_scrim = False

            # 233-242 AGAIN
            # 201-180, killed
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue)

            # 181-185
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 15  # b 1, should do NOTHING

            # 245-206 wtf...? why would this change anything, AGAIN
            # codifying in advance though...? b still 5
            # 221-225
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 20  # b 5, should do NOTHING

            # killed 95-119
            # aBot.mcts_engine.disable_positional_win_detection_in_rollouts = False

            # 141-153, AGAIN
            # 151-140, AGAIN
            # 86-87, lmao
            # 196-186 lol, AGAIN with tweaked params!
            # aBot.behavior_allow_pre_gather_greedy_leaves = False  # b true obviously

            # 229-233 but other tests did 249-214 and 244-218 so we're currently at 722-665, 52% winrate, so barely.
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue)

            # codifying in advance
            # 242-138 = 1.7536
            # aBot.expansion_force_global_visited_stage_1 = True  # was false
            # aBot.expansion_force_no_global_visited = False  # was true. Tweaked from run4, only diff between 4 and 5 here
            # aBot.expansion_use_iterative_negative_tiles = True  # was false

            # 258-204, codified
            # aBot.expansion_use_leaf_moves_first = True

            # 238-255, hmm
            # aBot.behavior_losing_on_economy_skip_defense_threshold = 0.75

            # 227-267
            # aBot.behavior_losing_on_economy_skip_defense_threshold = 0.93

            # 245-255. Implemented long-move-cutoff and trying again
            # aBot.expansion_single_iteration_time_cap = 0.055  # from 0.1, small tile time at 0.055

            # 18-22, bad.
            # aBot.mcts_engine.explore_factor = 2.0
            # aBot.mcts_engine.offset_initial_differential = True

            # 29-20. Trying again.
            # killed @ 18-11 making it 48-31 in favor of robust child.
            # Codified.
            # TODO test again later with large game size to be sure. with
            #  configureB=lambda bBot: bBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue),
            # aBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.RobustChild)

            # This should not be good, but if it is, that might be why brute force was winning sometimes.
            #  Assuming that a and b werent swapped and mcts was beating brute force the whole time.
            # 28-22, shit. TODO try again later
            # aBot.engine_allow_enemy_no_op = False

            # NEXT try this instead...?
            # 21-29, shit, try engine_allow_enemy_no_op_false again
            # aBot.mcts_engine.allow_random_no_ops = False

            # 24-25, try again.
            # 25-24, so 49-49, boring, who cares.
            # aBot.engine_allow_enemy_no_op = False

            # 25-25
            # 27-22, codified because thats the direction we want to go anyway.
            # aBot.engine_force_multi_tile_mcts = True

            # try reducing this...?
            # 22-27, AGAIN
            # 112-136, so SOME bias is definitely good.
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 2

            # try more...?
            # 113-131
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 6
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.5  # emptyVal, just noting what it is right now.

            # try adjusting the ratio
            # 118-130
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.6

            # 119-122 ...? but everything else did well so still codified.
            # aBot.engine_honor_mcts_expanded_expected_score = True

            # try this again
            # killed at 89-76 due to long running, running again.
            # 122-125
            # aBot.engine_allow_enemy_no_op = False

            # 123-119, codified i guess
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.3  # b is 0.5

            # 117-130, but 0.75 has already been codified
            # aBot.gather_include_distance_from_enemy_general_as_negatives = 0.4  # b is 0.3

            # 124-121
            # aBot.expansion_use_multi_per_dist_per_tile = True
            # aBot.expansion_single_iteration_time_cap = 0.01  # current 0.02

            # try again, against 0.03, with multi-tile
            # 103-141. Fixed now, though. Try again.
            # aBot.expansion_use_multi_per_dist_per_tile = True
            # aBot.expansion_force_no_global_visited = True

            # 119-109, codified
            # aBot.expansion_single_iteration_time_cap = 0.06

            # 122-127
            # aBot.expansion_small_tile_time_ratio = 0.5  # was 1.0

            # 127-122, try full small time...?
            # aBot.expansion_single_iteration_time_cap = 0.1  # was 0.06
            # aBot.expansion_small_tile_time_ratio = 0.5  # was 1.0

            # 126-121
            # aBot.expansion_small_tile_time_ratio = 1.0
            pass

        self.a_b_test(
            numRuns,
            configureA=configure_a,
            configureB=configure_b,
            # configureB=lambda bBot: bBot.mcts_engine.set_node_selection_function(MoveSelectionFunction.MaxAverageValue),
            debugMode=debugMode)

    def test_A_B__OTHER__1(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        self.begin_capturing_logging()

        def configure_b(bBot: EklipZBot):
            # bBot.expansion_length_weight_offset = -0.3
            # bBot.behavior_launch_timing_offset = +4
            bBot.expansion_always_include_non_terminating_leafmoves_in_iteration = False

            pass

        def configure_a(aBot: EklipZBot):
            # only in stage 2
            aBot.expansion_always_include_non_terminating_leafmoves_in_iteration = True

            # 189-179, killed
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 10  # b is 5
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 5  # b is 10

            # 133-117, AGAIN
            # 131-106, codified
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 5
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 10

            # 182-187, huh. Try 2...?
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 10

            # 184-200, trying again with leaf move army cutoff changes
            # killed 96-171
            # aBot.expansion_length_weight_offset = 0.0  # vs -0.3
            # aBot.expansion_use_leaf_moves_first = False

            # 140-155
            # aBot.expansion_full_time_limit = 0.3

            # 238-238, AGAIN
            # 232-237, meaningless, .4 it is
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.35  # b is now 0.4

            # 229-265
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.45  # b is now 0.4

            # 134-113, whoo! A-B against 0.4, now. Other tests are retesting 0.45 as well as 0.4, so now a-b them.
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.45

            # 113-135
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.55

            # 54-66
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.45  # b was 0.5, and biased allowed is 7 now.

            # 84-91
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.6  # b was 0.5, and biased allowed is 7 now.

            # 112-138. Try higher...?
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.35  # was 0.5, and biased allowed is 7 now.

            # codified
            # aBot.expansion_force_no_global_visited = True
            # aBot.expansion_single_iteration_time_cap = 0.02

            # 3 went 19-11 against gather_include_distance_from_enemy_general_as_negatives 0.85
            # 3 went 18-11 against gather_include_distance_from_enemy_general_as_negatives 0.5, codified
            # aBot.gather_include_distance_from_enemy_TERRITORY_as_negatives = 3

            # 121-128
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.7 # current 0.5

            # 251-246, but did worse than the other test of 7, 0.5. Testing 0.33 with 7 above
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 6  # was 4
            # aBot.mcts_engine.biased_move_ratio_while_available = 0.33  # was 0.5, so this should be the same number of biased moves on average per move but it will go later in the trial

            pass

        self.a_b_test(
            numRuns=numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode,
            debugModeTurnTime=0.25,
            debugModeRenderAllPlayers=False,
            # mapFile='SymmetricTestMaps/even_playground_map_small_short_spawns__top_left_bot_right.txtmap',
            noCities=None,
        )

    def test_A_B__OTHER__2(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        self.begin_capturing_logging()

        def configure_b(bBot: EklipZBot):
            bBot.expansion_enemy_expansion_plan_inbound_penalty = 0.6
            pass

        def configure_a(aBot: EklipZBot):
            # 156-152
            aBot.expansion_enemy_expansion_plan_inbound_penalty = 0.55  # b = 0.6, the current

            # # 174-158
            # aBot.expansion_enemy_expansion_plan_inbound_penalty = 0.95  # b = 0.0, the current

            # 283-213
            # aBot.expansion_always_include_non_terminating_leafmoves_in_iteration = True
            # aBot.expansion_allow_gather_plan_extension = True

            # pre-codified at 14-10 but UNDONE
            # aBot.expansion_length_weight_offset = 0.8  # b is 0.5

            # 127-96, codified, trying 0.8
            # aBot.expansion_length_weight_offset = 0.5  # b is 0.3

            # 202-166, significant, AGAIN
            # pre-codifying 94-61 finished 161-102
            # aBot.expansion_length_weight_offset = 0.1  # b = 0.0

            # 176-210 (where b was -0.3
            # aBot.expansion_length_weight_offset = -0.6

            # 250-217, codified.
            # aBot.behavior_launch_timing_offset = +3  # b is +4

            # 117-128
            # aBot.behavior_launch_timing_offset = +5  # b is +4

            # 114-132, huh...? Bigger should always be better here we'd have thought. AGAIN
            # 109-139 ok try 5
            # aBot.behavior_launch_timing_offset = +6  # b is +4

            # 126-119
            # aBot.behavior_launch_timing_offset = 4

            # 85-87, again
            # 67-56, ok but it lost mostly in other games soooooo
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 2

            # 108-137, so, we're making engine moves when we shouldn't be. Try higher..?
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -1  # current 0

            # RUNNING WITH NOT PER DIST PER TILE
            # aBot.expansion_use_multi_per_dist_per_tile = True
            # aBot.expansion_force_no_global_visited = False

            # 108-123
            # aBot.gather_include_distance_from_enemy_TILES_as_negatives = 2
            # aBot.engine_always_include_last_move_tile_in_scrims = True
            # aBot.engine_mcts_scrim_armies_per_player_limit = 1

            # 103-125 unclear B, rerunning with B False, 3
            # 129-121...?
            # aBot.engine_always_include_last_move_tile_in_scrims = True
            # aBot.engine_mcts_scrim_armies_per_player_limit = 2

            # 114-134, ok so this is bad
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 6 # current 4

            # 245-251. 7 already won elsewhere so nuking
            # aBot.mcts_engine.biased_playouts_allowed_per_trial = 3  # current 4

            pass

        self.a_b_test(
            numRuns=numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode,
            debugModeTurnTime=0.001,
            debugModeRenderAllPlayers=False,
            noCities=None,
        )

    def test_A_B__OTHER__3(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        self.begin_capturing_logging()

        def configure_b(bBot: EklipZBot):
            bBot.expansion_enemy_expansion_plan_inbound_penalty = 0.6
            # bBot.behavior_max_allowed_quick_expand = 7
            # bBot.expansion_length_weight_offset = -0.3
            # bBot.expansion_allow_gather_plan_extension = False
            pass

        def configure_a(aBot: EklipZBot):
            # 146-152
            aBot.expansion_enemy_expansion_plan_inbound_penalty = 0.75  # b = 0.6, the current

            # 188-160
            # aBot.expansion_enemy_expansion_plan_inbound_penalty = 0.75  # b = 0.0, the current

            # aBot.behavior_max_allowed_quick_expand = 0

            # 257-237
            # aBot.expansion_allow_gather_plan_extension = True

            # 194-198, b -0.3, AGAIN
            # 191-180, not significant
            # aBot.expansion_length_weight_offset = 0.0
            # 82-96, ok thats enough of these to convince me this is bad.
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 3

            # 118-131
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = 2  # was 0

            # 226-272
            # aBot.engine_mcts_move_estimation_net_differential_cutoff = -8  # was 0
            pass

        self.a_b_test(
            numRuns=numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode,
            debugModeTurnTime=0.5,
            debugModeRenderAllPlayers=False,
            noCities=None,
        )

    def test_A_B__OTHER__4(self):
        numRuns = 500
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        self.begin_capturing_logging()

        def configure_b(bBot: EklipZBot):
            bBot.expansion_enemy_expansion_plan_inbound_penalty = 0.6

            # bBot.engine_include_path_pre_expansion = False

            # bBot.expansion_length_weight_offset = -0.3
            # bBot.behavior_launch_timing_offset = +4
            pass

        def configure_a(aBot: EklipZBot):
            # 134-157
            aBot.expansion_enemy_expansion_plan_inbound_penalty = 0.5  # b = 0.6, the current

            # killed 126-137
            # aBot.expansion_enemy_expansion_plan_inbound_penalty = 0.45  # b = 0.6, the current

            # # 200-135
            # aBot.expansion_enemy_expansion_plan_inbound_penalty = 0.6  # b = 0.0, the current

            # aBot.engine_include_path_pre_expansion = True

            # in stage 1 and 2
            # 261-234
            # aBot.expansion_always_include_non_terminating_leafmoves_in_iteration = True

            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 50  # v 20

            # pre codified at 19-10
            # killed 192-173
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 20  # v 10

            # 129-102
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_moves = 5  # v 1
            # aBot.mcts_engine.min_expanded_visit_count_to_count_for_score = 10  # v 1

            # 129-102
            # aBot.expansion_length_weight_offset = 0.3  # b is 0.1

            # 193-196, not significant
            # aBot.expansion_length_weight_offset = -0.1
            # aBot.expansion_use_leaf_moves_first = False

            # 127-120, codified but rerunning
            # 230-239...? codified already under other tho because 260-200 over there.
            # aBot.behavior_launch_timing_offset = +3  # b is +4

            # 111-138, so bigger def not always better.
            # aBot.behavior_launch_timing_offset = +7  # b is +4

            # 113-134, so later launch timing always wins lol...?
            # aBot.behavior_launch_timing_offset = +2  # b is +4

            # 96-154
            # aBot.behavior_launch_timing_offset = -2

            # 45-73, killed
            # aBot.behavior_launch_timing_offset = -4

            # 78-47, retesting with larger game size but god damn
            # 76-52, so yeah, bad
            # aBot.behavior_early_retake_bonus_gather_turns = 0  # b is 3
            pass

        self.a_b_test(
            numRuns=numRuns,
            configureA=configure_a,
            configureB=configure_b,
            debugMode=debugMode,
            debugModeTurnTime=0.4,
            debugModeRenderAllPlayers=False,
            noCities=None,
        )