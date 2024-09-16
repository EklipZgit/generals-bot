from timeit import timeit

import logbook
import random
import time
import traceback
import typing
from unittest import mock

import SearchUtils
from ArmyEngine import ArmyEngine, ArmySimResult
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from Models import Move
from Engine.ArmyEngineModels import calc_value_int, calc_econ_value, ArmySimState
from MctsLudii import MctsDUCT, MoveSelectionFunction
from PerformanceTelemetry import PerformanceTelemetry
from TestBase import TestBase
from bot_ek0x45 import EklipZBot


class RandomPythonStuffBenchmarkTests(TestBase):
    def test_bench_dict_list_get_or_create_options(self):
        self.begin_capturing_logging()
        for numItems in [1, 10, 100, 1000]:
            for numGets in [1, 10, 100, 1000, 10000]:
                if numGets < numItems:
                    continue
                with self.subTest(numItems=numItems, numGets=numGets):
                    numRuns = 10000000 // numGets

                    result = timeit('''
for i in randList:
    col = myDict.get(i, [])
    myDict[i] = col
    col.append(i)
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: get(, []) always assign: {result:.3f} seconds ({numRuns * numGets} ops')

                    # benchmark the task
                    result = timeit('''
for i in randList:
    col = myDict.get(i, [])
    if not col:
        myDict[i] = col
    col.append(i)
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: get(, []) len check: {result:.3f} seconds ({numRuns * numGets} ops')

                    result = timeit('''
for i in randList:
    col = myDict.get(i, None)
    if col is None:
        col = []
        myDict[i] = col
    col.append(i)
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: get(, None) check none: {result:.3f} seconds ({numRuns * numGets} ops')

                    result = timeit('''
for i in randList:
    col = myDict.get(i)
    if col is None:
        col = []
        myDict[i] = col
    col.append(i)
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: get() check none: {result:.3f} seconds ({numRuns * numGets} ops')

                    result = timeit('''
for i in randList:
    try:
        col = myDict[i]
    except:
        col = []
        myDict[i] = col
    col.append(i)
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: try except: {result:.3f} seconds ({numRuns * numGets} ops')

                    result = timeit('''
for i in randList:
    try:
        col = myDict[i]
    except KeyError:
        col = []
        myDict[i] = col
    col.append(i)
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: try except KeyError: {result:.3f} seconds ({numRuns * numGets} ops')


    def test_bench_dict_int_get_or_create_options(self):
        self.begin_capturing_logging()
        for numItems in [1, 10, 100, 1000]:
            for numGets in [1, 10, 100, 1000, 10000]:
                if numGets < numItems:
                    continue
                with self.subTest(numItems=numItems, numGets=numGets):
                    numRuns = 100000000 // numGets
                    # d = deque()
                    # self.assertFalse(bool(d))
                    # d.append(1)
                    # self.assertTrue(bool(d))

                    # benchmark the task
                    result = timeit('''
for i in randList:
    myDict[i] = myDict.get(i, 0) + 1
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: get(, 0) col + 1: {result:.3f} seconds ({numRuns * numGets} ops')

                    result = timeit('''
for i in randList:
    try:
        myDict[i] += 1
    except:
        myDict[i] = 1
                        ''',
                        setup=f'''
import random
myDict = dict()
keys = [i for i in range({numItems})]
randList = [r for r in random.choices(keys, k={numGets})]
                        ''',
                        number=numRuns)

                    # report the result
                    logbook.info(f'{numItems} items, {numGets} gets: try except: {result:.3f} seconds ({numRuns * numGets} ops')
