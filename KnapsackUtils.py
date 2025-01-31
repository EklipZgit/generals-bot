import logbook
import time
import typing

import cppimport

KnapsackUtilsCpp = cppimport.imp('KnapsackUtilsCpp')   # Gets WAY further than anything else, I think? But ends up creating a second nested cpp/cpp/ folder and then dies
# kuc = cppimport.imp_from_filepath('cpp/KnapsackUtilsCpp.cpp')  # fails to load in cppimport\templating.py
# kuc = cppimport.imp_from_filepath('KnapsackUtilsCpp.cpp')  # ditto
# kuc = cppimport.imp_from_filepath('./cpp/KnapsackUtilsCpp.cpp')  # ditto
# kuc = cppimport.imp_from_filepath('D:\\2019_reformat_Backup\\generals-bot\\cpp\\KnapsackUtilsCpp.cpp')  # loads and compiles KnapsackUtilsCpp.cp311-win_amd64.pyd in same cpp folder before dying at ModuleNotFoundError: No module named 'KnapsackUtilsCpp'
# from KnapsackUtilsCpp import multiple_choice_knapsack_loop

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
    return KnapsackUtilsCpp.solve_multiple_choice_knapsack(items, capacity, weights, values, groups, noLog, longRuntimeThreshold)

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

