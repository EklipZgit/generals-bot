// cppimport
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <vector>

using IntList = std::vector<int>;

std::vector<std::vector<int>>& multiple_choice_knapsack_loop(
    size_t capacity,
    size_t n,
    IntList& weights,
    IntList& values,
    IntList& groups,
    std::vector<std::vector<int>>& K,
    std::vector<std::pair<int, int>>& groupStartEnds
) {
    for (int curCapacity = 0; curCapacity < capacity + 1; ++curCapacity) {
        for (size_t i = 0; i < n+1; ++i) {
            if (i == 0 || curCapacity == 0) {
                K[i][curCapacity] = 0;
            } else if (weights[i - 1] <= curCapacity) {
                int sub_max = 0;
                int prev_group = groups[i-1] - 1;
                int subKRow = curCapacity - weights[i - 1];
                if (prev_group >= 0) {
                    auto [prevGroupStart, prevGroupEnd] = groupStartEnds[prev_group];
                    for (int j = prevGroupStart + 1; j < prevGroupEnd + 1; ++j) {
                        if (groups[j - 1] == prev_group && K[j][subKRow] > sub_max) {
                            sub_max = K[j][subKRow];
                        }
                    }
                }
                K[i][curCapacity] = std::max(sub_max + values[i - 1], K[i - 1][curCapacity]);
            } else {
                K[i][curCapacity] = K[i - 1][curCapacity];
            }
        }
    }
    return K;
}

PYBIND11_MODULE(KnapsackUtilsCpp, m) {
    m.doc() = "multiple_choice_knapsack_loop native"; // optional module docstring

    m.def("multiple_choice_knapsack_loop", &multiple_choice_knapsack_loop, "multiple_choice_knapsack_loop native");
}
/*
<%
import sys
compiler_args = {
    'linux': [],
    'windows': ['/std:c++17']
}
cfg['extra_compile_args'] = compiler_args.get(sys.platform, [])
setup_pybind11(cfg)
%>
*/


/*
def solve_multiple_choice_knapsack(
        items: typing.List[typing.Any],
        capacity: int,
        weights: typing.List[int],
        values: typing.List[int],
        groups: typing.List[int],
        noLog: bool = True,
        longRuntimeThreshold = 0.005
) -> typing.Tuple[int, typing.List[typing.Any]]:
    """
    Solves knapsack where you need to knapsack a bunch of things, but must pick at most one thing from each group of things
    #Example
    items = ['a', 'b', 'c']
    values = [60, 100, 120]
    weights = [10, 20, 30]
    groups = [0, 1, 1]
    capacity = 50
    maxValue, itemList = solve_multiple_choice_knapsack(items, capacity, weights, values, groups)

    Extensively optimized by Travis Drake / EklipZgit by an order of magnitude, original implementation cloned from: https://gist.github.com/USM-F/1287f512de4ffb2fb852e98be1ac271d

    @param items: list of the items to be maximized in the knapsack. Can be a list of literally anything, just used to return the chosen items back as output.
    @param capacity: the capacity of weights that can be taken.
    @param weights: list of the items weights, in same order as items
    @param values: list of the items values, in same order as items
    @param groups: list of the items group id number, in same order as items. MUST start with 0, and cannot skip group numbers.
    @return: returns a tuple of the maximum value that was found to fit in the knapsack, along with the list of optimal items that reached that max value.
    """

    timeStart = time.perf_counter()
    groupStartEnds: typing.List[typing.Tuple[int, int]] = []
    if groups[0] != 0:
        raise AssertionError('Groups must start with 0 and increment by one for each new group. Items should be ordered by group.')

    lastGroup = -1
    lastGroupIndex = 0
    maxGroupSize = 0
    curGroupSize = 0
    for i, group in enumerate(groups):
        if group > lastGroup:
            if curGroupSize > maxGroupSize:
                maxGroupSize = curGroupSize
            if lastGroup > -1:
                groupStartEnds.append((lastGroupIndex, i))
                curGroupSize = 0
            if group > lastGroup + 1:
                raise AssertionError('Groups must have no gaps. if you have group 0, and 2, group 1 must be included between them.')
            lastGroupIndex = i
            lastGroup = group

        curGroupSize += 1

    groupStartEnds.append((lastGroupIndex, len(groups)))
    if curGroupSize > maxGroupSize:
        maxGroupSize = curGroupSize

    # if BYPASS_TIMEOUTS_FOR_DEBUGGING:
    if len(values) > 0:
        if not isinstance(values[0], int):
            raise AssertionError('values are all required to be ints or this algo will not function')

    n = len(values)
    K = [[0 for x in range(capacity + 1)] for x in range(n + 1)]
    """knapsack max values"""

    maxGrSq = math.sqrt(maxGroupSize)
    estTime = n * capacity * math.sqrt(maxGroupSize) * 0.00000022
    """rough approximation of the time it will take on MY machine, I set an arbitrary warning threshold"""
    if maxGroupSize == n:
        # this is a special case that behaves like 0-1 knapsack and doesn't multiply by max group size at all, due to the -1 check in the loop below.
        estTime = n * capacity * 0.00000022

    if estTime > longRuntimeThreshold:
        raise AssertionError(f"Knapsack potential long run est {estTime:.3f}: the inputs (n {n} * capacity {capacity} * math.sqrt(maxGroupSize {maxGroupSize}) {maxGrSq}) are going to result in a substantial runtime, maybe try a different algorithm")
    if not noLog:
        logbook.info(f'estimated knapsack time: {estTime:.3f} (n {n} * capacity {capacity} * math.sqrt(maxGroupSize {maxGroupSize}) {maxGrSq:.1f})')

    for curCapacity in range(capacity + 1):
        for i in range(n + 1):
            if i == 0 or curCapacity == 0:
                K[i][curCapacity] = 0
            elif weights[i - 1] <= curCapacity:
                sub_max = 0
                prev_group = groups[i - 1] - 1
                subKRow = curCapacity - weights[i - 1]
                if prev_group > -1:
                    prevGroupStart, prevGroupEnd = groupStartEnds[prev_group]
                    for j in range(prevGroupStart + 1, prevGroupEnd + 1):
                        if groups[j - 1] == prev_group and K[j][subKRow] > sub_max:
                            sub_max = K[j][subKRow]
                K[i][curCapacity] = max(sub_max + values[i - 1], K[i - 1][curCapacity])
            else:
                K[i][curCapacity] = K[i - 1][curCapacity]

    res = K[n][capacity]
    timeTaken = time.perf_counter() - timeStart
    if not noLog:
        logbook.info(f"Value Found {res} in {timeTaken:.3f}")
    includedItems = []
    includedGroups = []
    w = capacity
    lastTakenGroup = -1
    for i in range(n, 0, -1):
        if res <= 0:
            break
        if i == 0:
            raise AssertionError(f"i == 0 in knapsack items determiner?? res {res} i {i} w {w}")
        if w < 0:
            raise AssertionError(f"w < 0 in knapsack items determiner?? res {res} i {i} w {w}")
        # either the result comes from the
        # top (K[i-1][w]) or from (val[i-1]
        # + K[i-1] [w-wt[i-1]]) as in Knapsack
        # table. If it comes from the latter
        # one/ it means the item is included.
        # THIS IS WHY VALUE MUST BE INTS
        if res == K[i - 1][w]:
            continue

        group = groups[i - 1]
        if group == lastTakenGroup:
            continue

        includedGroups.append(group)
        lastTakenGroup = group
        # This item is included.
        if not noLog:
            logbook.info(
                f"item at index {i - 1} with value {values[i - 1]} and weight {weights[i - 1]} was included... adding it to output. (Res {res})")
        includedItems.append(items[i - 1])

        # Since this weight is included
        # its value is deducted
        res = res - values[i - 1]
        w = w - weights[i - 1]

    if not noLog:
        uniqueGroupsIncluded = set(includedGroups)
        if len(uniqueGroupsIncluded) != len(includedGroups):
            raise AssertionError("Yo, the multiple choice knapsacker failed to be distinct by groups")
        logbook.info(
            f"multiple choice knapsack completed on {n} items for capacity {capacity} finding value {K[n][capacity]} in Duration {time.perf_counter() - timeStart:.3f}")

    return K[n][capacity], includedItems


def solve_knapsack(
        items: typing.List[typing.Any],
        capacity: int,
        weights: typing.List[int],
        values: typing.List[int]
) -> typing.Tuple[int, typing.List[typing.Any]]:
    """
    Stolen from https://www.geeksforgeeks.org/0-1-knapsack-problem-dp-10/
    Python3 code for Dynamic Programming
    based solution for 0-1 Knapsack problem

    returns the combined value, and list of items that fit in a knapsack of a given capacity.
    @param items:
    @param capacity:
    @param weights:
    @param values:
    @return:
    """
    for value in values:
        if not isinstance(value, int):
            raise AssertionError('values are all required to be ints or this algo will not function')

    timeStart = time.perf_counter()
    n = len(items)
    K = [[0 for w in range(capacity + 1)]
         for i in range(n + 1)]

    # Build table K[][] in bottom up manner
    for i in range(n + 1):
        for w in range(capacity + 1):
            if i == 0 or w == 0:
                K[i][w] = 0
            elif weights[i - 1] <= w:
                K[i][w] = max(
                    values[i - 1] + K[i - 1][w - weights[i - 1]],
                    K[i - 1][w])
            else:
                K[i][w] = K[i - 1][w]

    # stores the result of Knapsack
    res = K[n][capacity]
    logbook.info("Value Found {}".format(res))
    includedItems = []
    w = capacity
    for i in range(n, 0, -1):
        if res <= 0:
            break
        if i == 0:
            raise AssertionError("i == 0 in knapsack items determiner?? res {} i {} w {}".format(res, i, w))
            break
        if w < 0:
            raise AssertionError("w < 0 in knapsack items determiner?? res {} i {} w {}".format(res, i, w))
            break
        # either the result comes from the
        # top (K[i-1][w]) or from (val[i-1]
        # + K[i-1] [w-wt[i-1]]) as in Knapsack
        # table. If it comes from the latter
        # one/ it means the item is included.
        # THIS IS WHY VALUE MUST BE INTS
        if res == K[i - 1][w]:
            continue

        # This item is included.
        logbook.info(
            f"item at index {i - 1} with value {values[i - 1]} and weight {weights[i - 1]} was included... adding it to output. (Res {res})")
        includedItems.append(items[i - 1])

        # Since this weight is included
        # its value is deducted
        res = res - values[i - 1]
        w = w - weights[i - 1]

    logbook.info(
        f"knapsack completed on {n} items for capacity {capacity} finding value {K[n][capacity]} in Duration {time.perf_counter() - timeStart:.3f}")
    return K[n][capacity], includedItems


*/