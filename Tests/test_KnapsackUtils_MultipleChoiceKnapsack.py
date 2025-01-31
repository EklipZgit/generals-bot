import inspect
import random
import time
import typing
import unittest

import KnapsackUtils
import SearchUtils
from SearchUtils import dest_breadth_first_target
from Tests.TestBase import TestBase
from base.client.tile import Tile
from base.viewer import GeneralsViewer
from DangerAnalyzer import DangerAnalyzer


class KnapsackUtils_MCKP_Tests(TestBase):
    def execute_multiple_choice_knapsack_with_tuples(
            self,
            groupItemWeightValues: typing.List[typing.Tuple[int, object, int, int]],
            capacity: int):
        items = []
        groups = []
        weights = []
        values = []

        for (group, item, weight, value) in groupItemWeightValues:
            items.append(item)
            groups.append(group)
            weights.append(weight)
            values.append(value)

        return KnapsackUtils.solve_multiple_choice_knapsack(items, capacity, weights, values, groups, noLog=False, longRuntimeThreshold=10.0)

    def generate_item_test_set(self, simulatedItemCount, simulatedGroupCount, maxWeightPerItem, maxValuePerItem, groupSkew = None):
        groupItemWeightValues = []
        r = random.Random()

        # at least one per group
        for i in range(simulatedGroupCount):
            item = i
            group = i
            value = r.randint(0, maxValuePerItem)
            weight = r.randint(1, maxWeightPerItem)
            groupItemWeightValues.append((group, item, weight, value))

        # then random groups after that
        for i in range(simulatedItemCount - simulatedGroupCount):
            item = i + simulatedGroupCount
            if groupSkew and r.random() < groupSkew:
                # use an existing group instead of a new one
                group = groupItemWeightValues[r.randint(simulatedGroupCount - 1, len(groupItemWeightValues) - 1)][0]
            else:
                group = r.randint(0, simulatedGroupCount - 1)
            value = r.randint(0, maxValuePerItem)
            weight = r.randint(1, maxWeightPerItem)
            groupItemWeightValues.append((group, item, weight, value))

        groupItemWeightValues = [t for t in sorted(groupItemWeightValues)]

        return groupItemWeightValues

    def test_multiple_choice_knapsack_solver__more_capacity_than_items__0_1_base_case__includes_all(self):
        groupItemWeightValues = [
            (0, 'a', 1, 1),
            (0, 'b', 1, 1),
            (0, 'c', 1, 1),
            (0, 'd', 1, 1),
            (0, 'e', 1, 1),
            (0, 'f', 1, 1),
            (0, 'g', 1, 1),
            (0, 'h', 1, 1),
            (0, 'i', 1, 1),
            (0, 'j', 1, 1),
            (0, 'k', 1, 1),
            (0, 'l', 1, 1),
            (0, 'm', 1, 1),
            (0, 'n', 1, 1),
            (0, 'o', 1, 1),
            (0, 'p', 1, 1),
            (0, 'q', 1, 1),
            (0, 'r', 1, 1),
            (0, 's', 1, 1),
            (0, 't', 1, 1),
            (0, 'u', 1, 1),
            (0, 'v', 1, 1),
            (0, 'w', 1, 1),
            (0, 'x', 1, 1),
            (0, 'y', 1, 1),
            (0, 'z', 1, 1)
        ]

        # give each own group for this test
        i = 0
        for groupItemWeightValue in groupItemWeightValues:
            (group, item, weight, value) = groupItemWeightValue
            groupItemWeightValues[i] = i, item, weight, value
            i += 1

        maxValue, items = self.execute_multiple_choice_knapsack_with_tuples(groupItemWeightValues, capacity=50)

        #should have included every letter once, as this boils down to the 0-1 knapsack problem
        self.assertEqual(26, maxValue)
        self.assertEqual(26, len(items))

    def test_multiple_choice_knapsack_solver__respects_groups(self):
        groupItemWeightValues = [
            (0, 'a', 1, 2),
            (0, 'b', 1, 1),
            (0, 'c', 1, 1),
            (0, 'd', 1, 1),
            (0, 'e', 1, 1),
            (0, 'f', 1, 1),
            (0, 'g', 1, 1),
            (0, 'h', 1, 1),
            (0, 'i', 1, 1),
            (0, 'j', 1, 1),
            (0, 'k', 1, 1),
            (0, 'l', 1, 1),
            (0, 'm', 1, 1),
            (0, 'n', 1, 1),
            (0, 'o', 1, 1),
            (0, 'p', 1, 1),
            (0, 'q', 1, 1),
            (0, 'r', 1, 1),
            (0, 's', 1, 1),
            (0, 't', 1, 1),
            (0, 'u', 1, 1),
            (0, 'v', 1, 1),
            (0, 'w', 1, 1),
            (0, 'x', 1, 1),
            (0, 'y', 1, 1),
            (0, 'z', 1, 1)
        ]

        # give first 10 own group, rest are 0
        i = 0
        for groupItemWeightValue in groupItemWeightValues:
            if i >= 10:
                break
            (group, item, weight, value) = groupItemWeightValue
            groupItemWeightValues[i] = i, item, weight, value
            i += 1


        maxValue, items = self.execute_multiple_choice_knapsack_with_tuples(groupItemWeightValues, capacity=50)

        #should have included every letter from first 10 once, and a should be the group '0' entry worth 2, so value 11
        self.assertEqual(11, maxValue)
        self.assertEqual(10, len(items))


    def test_multiple_choice_knapsack_solver__with_constrained_capacity__finds_best_group_subset(self):
        groupItemWeightValues = [
            (0, 'a', 7, 10),
            (0, 'b', 5, 8),
            (0, 'c', 2, 5),
            (1, 'd', 5, 5),
            (1, 'e', 2, 3),
        ]

        maxValue, items = self.execute_multiple_choice_knapsack_with_tuples(groupItemWeightValues, capacity=7)

        # at 7 capacity, we expect it to pick b (5, 8) and e (2, 3) for 11 at weight 7
        self.assertEqual(11, maxValue)
        self.assertEqual(2, len(items))


    def test_multiple_choice_knapsack_solver__with_constrained_capacity__handles_group_gaps(self):
        groupItemWeightValues = [
            (0, 'a', 7, 10),
            (0, 'b', 5, 8),
            (0, 'c', 2, 5),
            (1, 'd', 5, 5),
            (1, 'e', 2, 3),
        ]

        maxValue, items = self.execute_multiple_choice_knapsack_with_tuples(groupItemWeightValues, capacity=7)

        # at 7 capacity, we expect it to pick b (5, 8) and e (2, 3) for 11 at weight 7
        self.assertEqual(11, maxValue)
        self.assertEqual(2, len(items))



    def test_multiple_choice_knapsack_solver__should_not_have_insane_time_complexity(self):
        # envision our worst case gather scenario, lets say a depth 75 gather. We might want to run this 50 times against 200 items from maybe 40 groups each time
        # gathers may have a large max value so lets generate values on the scale of 150
        simulatedItemCount = 200
        simulatedGroupCount = 50
        maxValuePerItem = 150
        maxWeightPerItem = 5
        capacity = 75

        groupItemWeightValues = self.generate_item_test_set(simulatedItemCount, simulatedGroupCount, maxWeightPerItem, maxValuePerItem)

        start = time.perf_counter()
        maxValue, items = self.execute_multiple_choice_knapsack_with_tuples(groupItemWeightValues, capacity=capacity)
        self.assertGreater(maxValue, 0)
        # doubt we ever find less than this
        self.assertGreater(len(items), 20)
        endTime = time.perf_counter()
        duration = endTime - start
        self.assertLess(duration, 0.003)

    def test_multiple_choice_knapsack_solver__should_not_have_insane_time_complexity__high_item_count_low_group_count(self):
        # envision our worst case gather scenario, lets say a depth 75 gather. We might want to run this 50 times against 200 items from maybe 40 groups each time
        # gathers may have a large max value so lets generate values on the scale of 150
        simulatedItemCount = 400
        simulatedGroupCount = 21
        maxValuePerItem = 150
        maxWeightPerItem = 20
        capacity = 75

        groupItemWeightValues = self.generate_item_test_set(simulatedItemCount, simulatedGroupCount, maxWeightPerItem, maxValuePerItem)

        start = time.perf_counter()
        maxValue, items = self.execute_multiple_choice_knapsack_with_tuples(groupItemWeightValues, capacity=capacity)
        self.assertGreater(maxValue, 0)
        # doubt we ever find less than this
        self.assertGreater(len(items), 20)
        endTime = time.perf_counter()
        duration = endTime - start
        self.assertLess(duration, 0.003)

    def test_multiple_choice_knapsack_solver__should_not_have_insane_time_complexity__low_item_count_same_group_count(self):
        # TIME PERFORMANCE NOTES:
        # Scales exponentially with item count, 100 items = 15ms, 200 items = 50ms, 400 items = 160ms
        # Lower numbers of groups slightly increase the runtime by like 20% linearly (so, 50 ms 0-1 to 56ms ish with a pure 50/50 split on groups).
        # value does not matter at all to runtime
        # average item weight does slightly change it, see below for how it interacts with capacity
        # capacity is the big one, the less items you can fit in the solution regardless of input size, the faster it runs.
        # capacity 750 with 200 items = 570ms (now 80ms)
        # capacity 750 with 100 items = 138ms (now 27ms)
        # capacity 75 with 400 items = 138ms (now 20ms)
        # capacity 75 with 400 items, avg weight 10 = 217ms (now 15ms)
        # capacity 75 with 400 items, avg weight 2 = 246ms (now 20ms)

        sumRuntimes = 0.0
        countRuns = 0

        for groupCount in [1, 2, 3, 4, 5, 10, 15, 25, 50, 100, 150, 300]:
            for groupSkew in [0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]:
                simulatedItemCount = 300
                simulatedGroupCount = groupCount
                maxValuePerItem = 150
                maxWeightPerItem = 10
                capacity = 750

                sumTime = 0.0
                for i in range(20):
                    groupItemWeightValues = self.generate_item_test_set(simulatedItemCount, simulatedGroupCount, maxWeightPerItem, maxValuePerItem, groupSkew)
                    start = time.perf_counter()
                    maxValue, items = self.execute_multiple_choice_knapsack_with_tuples(groupItemWeightValues, capacity=capacity)
                    endTime = time.perf_counter()
                    duration = endTime - start
                    countRuns += 1
                    sumRuntimes += duration
                    sumTime += duration
                self.assertGreater(maxValue, 0)
                # doubt we ever find less than this
                # self.assertEqual(len(items), simulatedGroupCount)

                groups = [gi[0] for gi in groupItemWeightValues]

                sizes = []
                curSize = 0
                curGroup = -1
                for g in groups:
                    if g != curGroup:
                        if curGroup != -1:
                            sizes.append((curSize, curGroup))
                        curSize = 1
                        curGroup = g
                        continue
                    curSize += 1
                sizes.append((curSize, curGroup))

                groupIndexRemaps = [0] * (curGroup + 1)

                sortedSizes = sorted(sizes)
                for i, (size, g) in enumerate(sortedSizes):
                    groupIndexRemaps[g] = i

                medianIdx = int(len(groups) / 2)
                medianGroup = groups[medianIdx]
                medianSize = sizes[medianGroup][0]
                averageSize = sum(s[0] for s in sizes) / len(sizes)
                averageSizeByTile = sum(sizes[g][0] for g in groups) / len(groups)
                largestSize = sortedSizes[-1][0]
                smallestSize = sortedSizes[0][0]

                print(f'{simulatedGroupCount:3d}g, {groupSkew:.2f} skew: {sumTime:8.5f} - small {smallestSize:3d} <> {largestSize:3d} large, avg {averageSize:5.1f}, avg by N {averageSizeByTile:5.1f}, median {medianSize:3d} (group {medianGroup:3d}) -- {simulatedItemCount} items, {capacity} capacity, {simulatedGroupCount} groups')
        print(f'TOTAL RUNTIME {sumRuntimes:.3f}, iterations {countRuns}  (per run avg {sumRuntimes/countRuns:.5f}')

    # TESTS STOLEN FROM https://github.com/tmarinkovic/multiple-choice-knapsack-problem/blob/master/test/knapsack/MultipleChoiceKnapsackProblemTest.java
    def test_shouldReturnDesiredSolution2(self):
        capacity, values, weights, groups = self.getProblem2()
        items = [i for i in range(len(values))]
        maxValue, maxItems = KnapsackUtils.solve_multiple_choice_knapsack(items, capacity, weights, values, groups, noLog=False, longRuntimeThreshold=10.0)

        expected = [False, False, True,  False, False,
                    False, False, True,  False, False,
                    False, True,  False, False, False,
                    True,  False, False, False, False,
                    True,  False, False, False, False]

        self.assertEqual(42, maxValue)
        for i, shouldInclude in enumerate(expected):
            if shouldInclude:
                self.assertIn(i, maxItems)
            else:
                self.assertNotIn(i, maxItems)


    def test_shouldReturnDesiredSolution3(self):
        capacity, values, weights, groups = self.getProblem3()
        items = [i for i in range(len(values))]
        maxValue, maxItems = KnapsackUtils.solve_multiple_choice_knapsack(items, capacity, weights, values, groups, noLog=False, longRuntimeThreshold=10.0)

        expected = [True,  False, False, False, False,
                    False, False, True,  False, False,
                    False, True,  False, False, False,
                    True,  False, False, False, False,
                    False, True,  False, False, False]

        self.assertEqual(144, maxValue)
        for i, shouldInclude in enumerate(expected):
            if shouldInclude:
                self.assertIn(i, maxItems)
            else:
                self.assertNotIn(i, maxItems)


    def test_shouldReturnDesiredSolution4(self):
        capacity, values, weights, groups = self.getProblem4()
        items = [i for i in range(len(values))]
        maxValue, maxItems = KnapsackUtils.solve_multiple_choice_knapsack(items, capacity, weights, values, groups, noLog=False, longRuntimeThreshold=10.0)

        expected = [False, False, False, False, False,
                    False, False, False, False, False,
                    True,  False, False, False, False,
                    False, False, False, False, False,
                    True,  False, False, False, False]

        self.assertEqual(105, maxValue)
        for i, shouldInclude in enumerate(expected):
            if shouldInclude:
                self.assertIn(i, maxItems)
            else:
                self.assertNotIn(i, maxItems)

    def getProblem2(self):
        W = 10
        profit = [
                0,  0,  3,  4,  5,
                0,  4,  6,  10, 10,
                5,  8,  12, 18, 17,
                10, 12, 18, 30, 24,
                15, 20, 27, 44, 30]

        weight = [
                0, 0, 1, 2,  5,
                0, 1, 2, 5,  10,
                1, 2, 4, 9,  17,
                2, 3, 6, 15, 24,
                3, 5, 9, 22, 30]

        group = [
                0, 0, 0, 0, 0,
                1, 1, 1, 1, 1,
                2, 2, 2, 2, 2,
                3, 3, 3, 3, 3,
                4, 4, 4, 4, 4]
        return (W, profit, weight, group)

    def getProblem3(self):
        W = 12
        profit = [
                100, 100, 3,  4,  5,
                0,   4,   6,  10, 10,
                5,   8,   12, 18, 17,
                10,  12,  18, 30, 24,
                15,  20,  27, 44, 30]
        weight = [
                1, 1, 1, 2,  5,
                0, 1, 2, 5,  10,
                1, 2, 4, 9,  17,
                2, 3, 6, 15, 24,
                3, 5, 9, 22, 30]
        group = [
                0, 0, 0, 0, 0,
                1, 1, 1, 1, 1,
                2, 2, 2, 2, 2,
                3, 3, 3, 3, 3,
                4, 4, 4, 4, 4]
        return (W, profit, weight, group)

    def getProblem4(self):
        W = 2
        profit = [
                1,   1,  3,   4,  5,
                0,   4,  6,   10, 10,
                5,   8,  12,  18, 17,
                10,  12, 18,  30, 24,
                100, 100, 27, 44, 30]
        weight = [
                10, 10, 1, 2,  5,
                0,  1,  2, 5,  10,
                1,  2,  4, 9,  17,
                2,  3,  6, 15, 24,
                1,  1,  9, 22, 30]
        group = [
                0, 0, 0, 0, 0,
                1, 1, 1, 1, 1,
                2, 2, 2, 2, 2,
                3, 3, 3, 3, 3,
                4, 4, 4, 4, 4]
        return (W, profit, weight, group)