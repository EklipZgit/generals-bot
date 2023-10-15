import logging
import random
import time
import traceback
import typing
from unittest import mock

import SearchUtils
from ArmyEngine import ArmyEngine, ArmySimResult
from ArmyTracker import Army
from BoardAnalyzer import BoardAnalyzer
from DataModels import Move
from Engine.ArmyEngineModels import calc_value_int, calc_econ_value, ArmySimState
from MctsLudii import MctsDUCT, MoveSelectionFunction
from Sim.GameSimulator import GameSimulatorHost, GameSimulator
from TestBase import TestBase
from base.client.map import Tile, MapBase
from bot_ek0x45 import EklipZBot


class ArmyEngineBenchmarkTests(TestBase):
    # perf benching changes
    # PRE ANY OPTIMIZATIONS
    """

nArmy, nTile, +Army, depth, biasD
4,     4,     5,    15,     7: dur 0.3119, iter   575, nodesExplored   575, rollouts   575,
                      backprops  1532, rolloutExpansions  8626, biasedRolloutExpansions  3085
4,     4,     5,    50,     7: dur 0.3034, iter   223, nodesExplored   223, rollouts   223,
                      backprops   529, rolloutExpansions 11180, biasedRolloutExpansions  1565
4,     4,     5,   100,     7: dur 0.3130, iter   118, nodesExplored   118, rollouts   118,
                      backprops   262, rolloutExpansions 11837, biasedRolloutExpansions   828
4,     4,     5,   100,    30: dur 0.3144, iter   120, nodesExplored   120, rollouts   120,
                      backprops   270, rolloutExpansions 12051, biasedRolloutExpansions  3613
4,     4,    20,    15,     7: dur 0.3021, iter   577, nodesExplored   577, rollouts   577,
                      backprops  1567, rolloutExpansions  8658, biasedRolloutExpansions  3075
4,     4,    20,    50,     7: dur 0.3048, iter   228, nodesExplored   228, rollouts   228,
                      backprops   555, rolloutExpansions 11440, biasedRolloutExpansions  1601
4,     4,    20,   100,     7: dur 0.3062, iter   118, nodesExplored   118, rollouts   118,
                      backprops   265, rolloutExpansions 11870, biasedRolloutExpansions   830
4,     4,    20,   100,    30: dur 0.3071, iter   111, nodesExplored   111, rollouts   111,
                      backprops   248, rolloutExpansions 11099, biasedRolloutExpansions  3325
4,    11,     5,    15,     7: dur 0.3038, iter   545, nodesExplored   545, rollouts   545,
                      backprops  1431, rolloutExpansions  8179, biasedRolloutExpansions  2923
4,    11,     5,    50,     7: dur 0.3061, iter   211, nodesExplored   211, rollouts   211,
                      backprops   497, rolloutExpansions 10555, biasedRolloutExpansions  1477
4,    11,     5,   100,     7: dur 0.3092, iter   115, nodesExplored   115, rollouts   115,
                      backprops   257, rolloutExpansions 11550, biasedRolloutExpansions   808
4,    11,     5,   100,    30: dur 0.3117, iter   109, nodesExplored   109, rollouts   109,
                      backprops   241, rolloutExpansions 10903, biasedRolloutExpansions  3266
4,    11,    20,    15,     7: dur 0.3108, iter   625, nodesExplored   625, rollouts   625,
                      backprops  1710, rolloutExpansions  9376, biasedRolloutExpansions  3361
4,    11,    20,    50,     7: dur 0.3086, iter   215, nodesExplored   215, rollouts   215,
                      backprops   520, rolloutExpansions 10770, biasedRolloutExpansions  1507
4,    11,    20,   100,     7: dur 0.3212, iter   105, nodesExplored   105, rollouts   105,
                      backprops   235, rolloutExpansions 10495, biasedRolloutExpansions   735
4,    11,    20,   100,    30: dur 0.3074, iter   105, nodesExplored   105, rollouts   105,
                      backprops   235, rolloutExpansions 10376, biasedRolloutExpansions  3127
15,     4,     5,    15,     7: dur 0.3192, iter   291, nodesExplored   291, rollouts   291,
                      backprops   598, rolloutExpansions  4371, biasedRolloutExpansions  1559
15,     4,     5,    50,     7: dur 0.3309, iter   136, nodesExplored   136, rollouts   136,
                      backprops   273, rolloutExpansions  6805, biasedRolloutExpansions   952
15,     4,     5,   100,     7: dur 0.3093, iter    70, nodesExplored    70, rollouts    70,
                      backprops   141, rolloutExpansions  7070, biasedRolloutExpansions   494
15,     4,     5,   100,    30: dur 0.3100, iter    69, nodesExplored    69, rollouts    69,
                      backprops   138, rolloutExpansions  6930, biasedRolloutExpansions  2076
15,     4,    20,    15,     7: dur 0.3177, iter   294, nodesExplored   294, rollouts   294,
                      backprops   604, rolloutExpansions  4419, biasedRolloutExpansions  1567
15,     4,    20,    50,     7: dur 0.3408, iter   137, nodesExplored   137, rollouts   137,
                      backprops   277, rolloutExpansions  6880, biasedRolloutExpansions   963
15,     4,    20,   100,     7: dur 0.3118, iter    70, nodesExplored    70, rollouts    70,
                      backprops   140, rolloutExpansions  7010, biasedRolloutExpansions   490
15,     4,    20,   100,    30: dur 0.3092, iter    65, nodesExplored    65, rollouts    65,
                      backprops   131, rolloutExpansions  6590, biasedRolloutExpansions  1974
15,    11,     5,    15,     7: dur 0.3199, iter   293, nodesExplored   293, rollouts   293,
                      backprops   601, rolloutExpansions  4399, biasedRolloutExpansions  1581
15,    11,     5,    50,     7: dur 0.3142, iter   110, nodesExplored   110, rollouts   110,
                      backprops   221, rolloutExpansions  5515, biasedRolloutExpansions   772
15,    11,     5,   100,     7: dur 0.3113, iter    64, nodesExplored    64, rollouts    64,
                      backprops   129, rolloutExpansions  6470, biasedRolloutExpansions   452
15,    11,     5,   100,    30: dur 0.3028, iter    62, nodesExplored    62, rollouts    62,
                      backprops   124, rolloutExpansions  6240, biasedRolloutExpansions  1870
15,    11,    20,    15,     7: dur 0.3115, iter   267, nodesExplored   267, rollouts   267,
                      backprops   548, rolloutExpansions  4018, biasedRolloutExpansions  1442
15,    11,    20,    50,     7: dur 0.3056, iter   109, nodesExplored   109, rollouts   109,
                      backprops   220, rolloutExpansions  5490, biasedRolloutExpansions   768
15,    11,    20,   100,     7: dur 0.3102, iter    64, nodesExplored    64, rollouts    64,
                      backprops   128, rolloutExpansions  6420, biasedRolloutExpansions   449
15,    11,    20,   100,    30: dur 0.3061, iter    56, nodesExplored    56, rollouts    56,
                      backprops   112, rolloutExpansions  5621, biasedRolloutExpansions  1682
AVG:
dur 0.3116, iter   195, nodesExplored   195, rollouts   195,
                      backprops   461, rolloutExpansions  8225, biasedRolloutExpansions  1694


LARGE
nArmy, nTile, +Army, depth, biasD
3,     0,     5,    15,     0: dur 0.3113, iter   733, nodesExplored   733, rollouts   733,
                      backprops  2042, rolloutExpansions 10998, biasedRolloutExpansions     0
3,     0,     5,    15,     7: dur 0.3208, iter   674, nodesExplored   674, rollouts   674,
                      backprops  1897, rolloutExpansions 10116, biasedRolloutExpansions  3621
3,     0,     5,    50,     0: dur 0.3024, iter   248, nodesExplored   248, rollouts   248,
                      backprops   636, rolloutExpansions 12405, biasedRolloutExpansions     0
3,     0,     5,    50,     7: dur 0.3041, iter   254, nodesExplored   254, rollouts   254,
                      backprops   661, rolloutExpansions 12700, biasedRolloutExpansions  1778
3,     0,     5,   200,     0: dur 0.3066, iter    62, nodesExplored    62, rollouts    62,
                      backprops   139, rolloutExpansions 12535, biasedRolloutExpansions     0
3,     0,     5,   200,     7: dur 0.3118, iter    67, nodesExplored    67, rollouts    67,
                      backprops   152, rolloutExpansions 13419, biasedRolloutExpansions   473
3,     0,     5,   200,    30: dur 0.3063, iter    72, nodesExplored    72, rollouts    72,
                      backprops   165, rolloutExpansions 13700, biasedRolloutExpansions  2154
3,     0,     5,   200,   100: dur 0.3080, iter    69, nodesExplored    69, rollouts    69,
                      backprops   157, rolloutExpansions 12682, biasedRolloutExpansions  5042
3,     0,    20,    15,     0: dur 0.3130, iter   728, nodesExplored   728, rollouts   728,
                      backprops  2064, rolloutExpansions 10926, biasedRolloutExpansions     0
3,     0,    20,    15,     7: dur 0.3089, iter   632, nodesExplored   632, rollouts   632,
                      backprops  1749, rolloutExpansions  9486, biasedRolloutExpansions  3398
3,     0,    20,    50,     0: dur 0.3052, iter   241, nodesExplored   241, rollouts   241,
                      backprops   623, rolloutExpansions 12055, biasedRolloutExpansions     0
3,     0,    20,    50,     7: dur 0.3011, iter   253, nodesExplored   253, rollouts   253,
                      backprops   659, rolloutExpansions 12670, biasedRolloutExpansions  1773
3,     0,    20,   200,     0: dur 0.3130, iter    57, nodesExplored    57, rollouts    57,
                      backprops   125, rolloutExpansions 11472, biasedRolloutExpansions     0
3,     0,    20,   200,     7: dur 0.3021, iter    62, nodesExplored    62, rollouts    62,
                      backprops   139, rolloutExpansions 12498, biasedRolloutExpansions   440
3,     0,    20,   200,    30: dur 0.3073, iter    69, nodesExplored    69, rollouts    69,
                      backprops   157, rolloutExpansions 13413, biasedRolloutExpansions  2088
3,     0,    20,   200,   100: dur 0.3040, iter    70, nodesExplored    70, rollouts    70,
                      backprops   158, rolloutExpansions 12782, biasedRolloutExpansions  5074
3,     4,     5,    15,     0: dur 0.3043, iter   681, nodesExplored   681, rollouts   681,
                      backprops  1908, rolloutExpansions 10215, biasedRolloutExpansions     0
3,     4,     5,    15,     7: dur 0.3014, iter   625, nodesExplored   625, rollouts   625,
                      backprops  1723, rolloutExpansions  9376, biasedRolloutExpansions  3342
3,     4,     5,    50,     0: dur 0.3115, iter   240, nodesExplored   240, rollouts   240,
                      backprops   611, rolloutExpansions 12020, biasedRolloutExpansions     0
3,     4,     5,    50,     7: dur 0.3016, iter   232, nodesExplored   232, rollouts   232,
                      backprops   597, rolloutExpansions 11620, biasedRolloutExpansions  1626
3,     4,     5,   200,     0: dur 0.3144, iter    60, nodesExplored    60, rollouts    60,
                      backprops   128, rolloutExpansions 11966, biasedRolloutExpansions     0
3,     4,     5,   200,     7: dur 0.3185, iter    60, nodesExplored    60, rollouts    60,
                      backprops   132, rolloutExpansions 12051, biasedRolloutExpansions   422
3,     4,     5,   200,    30: dur 0.3053, iter    66, nodesExplored    66, rollouts    66,
                      backprops   147, rolloutExpansions 13031, biasedRolloutExpansions  1988
3,     4,     5,   200,   100: dur 0.3133, iter    63, nodesExplored    63, rollouts    63,
                      backprops   141, rolloutExpansions 12020, biasedRolloutExpansions  4779
3,     4,    20,    15,     0: dur 0.3366, iter   813, nodesExplored   813, rollouts   813,
                      backprops  2312, rolloutExpansions 12198, biasedRolloutExpansions     0
3,     4,    20,    15,     7: dur 0.3073, iter   668, nodesExplored   668, rollouts   668,
                      backprops  1921, rolloutExpansions 10024, biasedRolloutExpansions  3599
3,     4,    20,    50,     0: dur 0.3052, iter   259, nodesExplored   259, rollouts   259,
                      backprops   682, rolloutExpansions 12995, biasedRolloutExpansions     0
3,     4,    20,    50,     7: dur 0.3058, iter   243, nodesExplored   243, rollouts   243,
                      backprops   629, rolloutExpansions 12165, biasedRolloutExpansions  1703
3,     4,    20,   200,     0: dur 0.3221, iter    62, nodesExplored    62, rollouts    62,
                      backprops   139, rolloutExpansions 12420, biasedRolloutExpansions     0
3,     4,    20,   200,     7: dur 0.3132, iter    64, nodesExplored    64, rollouts    64,
                      backprops   146, rolloutExpansions 12838, biasedRolloutExpansions   450
3,     4,    20,   200,    30: dur 0.3222, iter    67, nodesExplored    67, rollouts    67,
                      backprops   150, rolloutExpansions 13064, biasedRolloutExpansions  2007
3,     4,    20,   200,   100: dur 0.3349, iter    64, nodesExplored    64, rollouts    64,
                      backprops   144, rolloutExpansions 12626, biasedRolloutExpansions  5032
3,    11,     5,    15,     0: dur 0.3210, iter   742, nodesExplored   742, rollouts   742,
                      backprops  2071, rolloutExpansions 11143, biasedRolloutExpansions     0
3,    11,     5,    15,     7: dur 0.3055, iter   658, nodesExplored   658, rollouts   658,
                      backprops  1816, rolloutExpansions  9882, biasedRolloutExpansions  3542
3,    11,     5,    50,     0: dur 0.3085, iter   240, nodesExplored   240, rollouts   240,
                      backprops   617, rolloutExpansions 12040, biasedRolloutExpansions     0
3,    11,     5,    50,     7: dur 0.3024, iter   234, nodesExplored   234, rollouts   234,
                      backprops   585, rolloutExpansions 11740, biasedRolloutExpansions  1643
3,    11,     5,   200,     0: dur 0.3125, iter    58, nodesExplored    58, rollouts    58,
                      backprops   126, rolloutExpansions 11596, biasedRolloutExpansions     0
3,    11,     5,   200,     7: dur 0.3131, iter    59, nodesExplored    59, rollouts    59,
                      backprops   132, rolloutExpansions 11946, biasedRolloutExpansions   418
3,    11,     5,   200,    30: dur 0.3061, iter    62, nodesExplored    62, rollouts    62,
                      backprops   136, rolloutExpansions 12249, biasedRolloutExpansions  1865
3,    11,     5,   200,   100: dur 0.3077, iter    66, nodesExplored    66, rollouts    66,
                      backprops   147, rolloutExpansions 12578, biasedRolloutExpansions  5004
3,    11,    20,    15,     0: dur 0.3109, iter   790, nodesExplored   790, rollouts   790,
                      backprops  2330, rolloutExpansions 11854, biasedRolloutExpansions     0
3,    11,    20,    15,     7: dur 0.3024, iter   710, nodesExplored   710, rollouts   710,
                      backprops  2019, rolloutExpansions 10662, biasedRolloutExpansions  3798
3,    11,    20,    50,     0: dur 0.3009, iter   244, nodesExplored   244, rollouts   244,
                      backprops   635, rolloutExpansions 12210, biasedRolloutExpansions     0
3,    11,    20,    50,     7: dur 0.3066, iter   256, nodesExplored   256, rollouts   256,
                      backprops   673, rolloutExpansions 12835, biasedRolloutExpansions  1796
3,    11,    20,   200,     0: dur 0.3121, iter    62, nodesExplored    62, rollouts    62,
                      backprops   142, rolloutExpansions 12374, biasedRolloutExpansions     0
3,    11,    20,   200,     7: dur 0.3021, iter    65, nodesExplored    65, rollouts    65,
                      backprops   147, rolloutExpansions 13072, biasedRolloutExpansions   460
3,    11,    20,   200,    30: dur 0.3091, iter    67, nodesExplored    67, rollouts    67,
                      backprops   154, rolloutExpansions 12619, biasedRolloutExpansions  1982
3,    11,    20,   200,   100: dur 0.3335, iter    67, nodesExplored    67, rollouts    67,
                      backprops   152, rolloutExpansions 13046, biasedRolloutExpansions  5195
8,     0,     5,    15,     0: dur 0.3163, iter   530, nodesExplored   530, rollouts   530,
                      backprops  1238, rolloutExpansions  7957, biasedRolloutExpansions     0
8,     0,     5,    15,     7: dur 0.3115, iter   449, nodesExplored   449, rollouts   449,
                      backprops  1025, rolloutExpansions  6738, biasedRolloutExpansions  2401
8,     0,     5,    50,     0: dur 0.3012, iter   179, nodesExplored   179, rollouts   179,
                      backprops   378, rolloutExpansions  8990, biasedRolloutExpansions     0
8,     0,     5,    50,     7: dur 0.3012, iter   180, nodesExplored   180, rollouts   180,
                      backprops   382, rolloutExpansions  9045, biasedRolloutExpansions  1266
8,     0,     5,   200,     0: dur 0.3540, iter    56, nodesExplored    56, rollouts    56,
                      backprops   113, rolloutExpansions 11258, biasedRolloutExpansions     0
8,     0,     5,   200,     7: dur 0.3429, iter    58, nodesExplored    58, rollouts    58,
                      backprops   118, rolloutExpansions 11758, biasedRolloutExpansions   411
8,     0,     5,   200,    30: dur 0.3357, iter    61, nodesExplored    61, rollouts    61,
                      backprops   123, rolloutExpansions 12214, biasedRolloutExpansions  1833
8,     0,     5,   200,   100: dur 0.3236, iter    52, nodesExplored    52, rollouts    52,
                      backprops   106, rolloutExpansions 10455, biasedRolloutExpansions  4164
8,     0,    20,    15,     0: dur 0.3098, iter   524, nodesExplored   524, rollouts   524,
                      backprops  1215, rolloutExpansions  7866, biasedRolloutExpansions     0
8,     0,    20,    15,     7: dur 0.3013, iter   436, nodesExplored   436, rollouts   436,
                      backprops   999, rolloutExpansions  6550, biasedRolloutExpansions  2337
8,     0,    20,    50,     0: dur 0.3009, iter   191, nodesExplored   191, rollouts   191,
                      backprops   405, rolloutExpansions  9560, biasedRolloutExpansions     0
8,     0,    20,    50,     7: dur 0.3061, iter   188, nodesExplored   188, rollouts   188,
                      backprops   398, rolloutExpansions  9445, biasedRolloutExpansions  1322
8,     0,    20,   200,     0: dur 0.3425, iter    56, nodesExplored    56, rollouts    56,
                      backprops   114, rolloutExpansions 11358, biasedRolloutExpansions     0
8,     0,    20,   200,     7: dur 0.3462, iter    58, nodesExplored    58, rollouts    58,
                      backprops   118, rolloutExpansions 11730, biasedRolloutExpansions   410
8,     0,    20,   200,    30: dur 0.3362, iter    61, nodesExplored    61, rollouts    61,
                      backprops   123, rolloutExpansions 12215, biasedRolloutExpansions  1833
8,     0,    20,   200,   100: dur 0.3156, iter    56, nodesExplored    56, rollouts    56,
                      backprops   114, rolloutExpansions 11180, biasedRolloutExpansions  4410
8,     4,     5,    15,     0: dur 0.3280, iter   496, nodesExplored   496, rollouts   496,
                      backprops  1128, rolloutExpansions  7449, biasedRolloutExpansions     0
8,     4,     5,    15,     7: dur 0.3098, iter   420, nodesExplored   420, rollouts   420,
                      backprops   942, rolloutExpansions  6304, biasedRolloutExpansions  2260
8,     4,     5,    50,     0: dur 0.3011, iter   170, nodesExplored   170, rollouts   170,
                      backprops   357, rolloutExpansions  8530, biasedRolloutExpansions     0
8,     4,     5,    50,     7: dur 0.3011, iter   166, nodesExplored   166, rollouts   166,
                      backprops   348, rolloutExpansions  8340, biasedRolloutExpansions  1167
8,     4,     5,   200,     0: dur 0.3242, iter    52, nodesExplored    52, rollouts    52,
                      backprops   104, rolloutExpansions 10400, biasedRolloutExpansions     0
8,     4,     5,   200,     7: dur 0.3188, iter    52, nodesExplored    52, rollouts    52,
                      backprops   104, rolloutExpansions 10400, biasedRolloutExpansions   364
8,     4,     5,   200,    30: dur 0.3343, iter    58, nodesExplored    58, rollouts    58,
                      backprops   117, rolloutExpansions 11696, biasedRolloutExpansions  1755
8,     4,     5,   200,   100: dur 0.3185, iter    44, nodesExplored    44, rollouts    44,
                      backprops    90, rolloutExpansions  8886, biasedRolloutExpansions  3548
8,     4,    20,    15,     0: dur 0.3179, iter   497, nodesExplored   497, rollouts   497,
                      backprops  1137, rolloutExpansions  7468, biasedRolloutExpansions     0
8,     4,    20,    15,     7: dur 0.3024, iter   383, nodesExplored   383, rollouts   383,
                      backprops   856, rolloutExpansions  5746, biasedRolloutExpansions  2049
8,     4,    20,    50,     0: dur 0.3306, iter   164, nodesExplored   164, rollouts   164,
                      backprops   342, rolloutExpansions  8215, biasedRolloutExpansions     0
8,     4,    20,    50,     7: dur 0.3269, iter   162, nodesExplored   162, rollouts   162,
                      backprops   339, rolloutExpansions  8130, biasedRolloutExpansions  1138
8,     4,    20,   200,     0: dur 0.3191, iter    42, nodesExplored    42, rollouts    42,
                      backprops    84, rolloutExpansions  8413, biasedRolloutExpansions     0
8,     4,    20,   200,     7: dur 0.3062, iter    42, nodesExplored    42, rollouts    42,
                      backprops    86, rolloutExpansions  8558, biasedRolloutExpansions   299
8,     4,    20,   200,    30: dur 0.3084, iter    44, nodesExplored    44, rollouts    44,
                      backprops    88, rolloutExpansions  8820, biasedRolloutExpansions  1323
8,     4,    20,   200,   100: dur 0.3181, iter    42, nodesExplored    42, rollouts    42,
                      backprops    85, rolloutExpansions  8499, biasedRolloutExpansions  3391
8,    11,     5,    15,     0: dur 0.3006, iter   411, nodesExplored   411, rollouts   411,
                      backprops   913, rolloutExpansions  6177, biasedRolloutExpansions     0
8,    11,     5,    15,     7: dur 0.3129, iter   420, nodesExplored   420, rollouts   420,
                      backprops   942, rolloutExpansions  6304, biasedRolloutExpansions  2256
8,    11,     5,    50,     0: dur 0.3010, iter   147, nodesExplored   147, rollouts   147,
                      backprops   307, rolloutExpansions  7365, biasedRolloutExpansions     0
8,    11,     5,    50,     7: dur 0.3011, iter   153, nodesExplored   153, rollouts   153,
                      backprops   318, rolloutExpansions  7670, biasedRolloutExpansions  1073
8,    11,     5,   200,     0: dur 0.3157, iter    42, nodesExplored    42, rollouts    42,
                      backprops    86, rolloutExpansions  8580, biasedRolloutExpansions     0
8,    11,     5,   200,     7: dur 0.3190, iter    46, nodesExplored    46, rollouts    46,
                      backprops    92, rolloutExpansions  9220, biasedRolloutExpansions   322
8,    11,     5,   200,    30: dur 0.3117, iter    44, nodesExplored    44, rollouts    44,
                      backprops    89, rolloutExpansions  8920, biasedRolloutExpansions  1338
8,    11,     5,   200,   100: dur 0.3265, iter    43, nodesExplored    43, rollouts    43,
                      backprops    88, rolloutExpansions  8757, biasedRolloutExpansions  3467
8,    11,    20,    15,     0: dur 0.3300, iter   458, nodesExplored   458, rollouts   458,
                      backprops  1048, rolloutExpansions  6870, biasedRolloutExpansions     0
8,    11,    20,    15,     7: dur 0.3139, iter   404, nodesExplored   404, rollouts   404,
                      backprops   911, rolloutExpansions  6061, biasedRolloutExpansions  2162
8,    11,    20,    50,     0: dur 0.3086, iter   157, nodesExplored   157, rollouts   157,
                      backprops   329, rolloutExpansions  7875, biasedRolloutExpansions     0
8,    11,    20,    50,     7: dur 0.3376, iter   166, nodesExplored   166, rollouts   166,
                      backprops   350, rolloutExpansions  8340, biasedRolloutExpansions  1167
8,    11,    20,   200,     0: dur 0.3065, iter    46, nodesExplored    46, rollouts    46,
                      backprops    93, rolloutExpansions  9278, biasedRolloutExpansions     0
8,    11,    20,   200,     7: dur 0.3094, iter    44, nodesExplored    44, rollouts    44,
                      backprops    88, rolloutExpansions  8816, biasedRolloutExpansions   308
8,    11,    20,   200,    30: dur 0.3135, iter    44, nodesExplored    44, rollouts    44,
                      backprops    89, rolloutExpansions  8820, biasedRolloutExpansions  1327
8,    11,    20,   200,   100: dur 0.3101, iter    42, nodesExplored    42, rollouts    42,
                      backprops    85, rolloutExpansions  8504, biasedRolloutExpansions  3401
25,     0,     5,    15,     0: dur 0.3097, iter   217, nodesExplored   217, rollouts   217,
                      backprops   438, rolloutExpansions  3262, biasedRolloutExpansions     0
25,     0,     5,    15,     7: dur 0.3086, iter   199, nodesExplored   199, rollouts   199,
                      backprops   401, rolloutExpansions  2998, biasedRolloutExpansions  1069
25,     0,     5,    50,     0: dur 0.3262, iter    97, nodesExplored    97, rollouts    97,
                      backprops   194, rolloutExpansions  4850, biasedRolloutExpansions     0
25,     0,     5,    50,     7: dur 0.3072, iter    98, nodesExplored    98, rollouts    98,
                      backprops   197, rolloutExpansions  4935, biasedRolloutExpansions   690
25,     0,     5,   200,     0: dur 0.3094, iter    35, nodesExplored    35, rollouts    35,
                      backprops    70, rolloutExpansions  7000, biasedRolloutExpansions     0
25,     0,     5,   200,     7: dur 0.3076, iter    34, nodesExplored    34, rollouts    34,
                      backprops    69, rolloutExpansions  6980, biasedRolloutExpansions   244
25,     0,     5,   200,    30: dur 0.3197, iter    34, nodesExplored    34, rollouts    34,
                      backprops    68, rolloutExpansions  6840, biasedRolloutExpansions  1026
25,     0,     5,   200,   100: dur 0.3142, iter    32, nodesExplored    32, rollouts    32,
                      backprops    64, rolloutExpansions  6447, biasedRolloutExpansions  2553
25,     0,    20,    15,     0: dur 0.3305, iter   247, nodesExplored   247, rollouts   247,
                      backprops   498, rolloutExpansions  3705, biasedRolloutExpansions     0
25,     0,    20,    15,     7: dur 0.3074, iter   182, nodesExplored   182, rollouts   182,
                      backprops   366, rolloutExpansions  2743, biasedRolloutExpansions   982
25,     0,    20,    50,     0: dur 0.3039, iter    92, nodesExplored    92, rollouts    92,
                      backprops   185, rolloutExpansions  4630, biasedRolloutExpansions     0
25,     0,    20,    50,     7: dur 0.3107, iter    92, nodesExplored    92, rollouts    92,
                      backprops   184, rolloutExpansions  4605, biasedRolloutExpansions   644
25,     0,    20,   200,     0: dur 0.3131, iter    33, nodesExplored    33, rollouts    33,
                      backprops    67, rolloutExpansions  6700, biasedRolloutExpansions     0
25,     0,    20,   200,     7: dur 0.3150, iter    34, nodesExplored    34, rollouts    34,
                      backprops    69, rolloutExpansions  6980, biasedRolloutExpansions   244
25,     0,    20,   200,    30: dur 0.3175, iter    34, nodesExplored    34, rollouts    34,
                      backprops    69, rolloutExpansions  6980, biasedRolloutExpansions  1047
25,     0,    20,   200,   100: dur 0.3158, iter    32, nodesExplored    32, rollouts    32,
                      backprops    64, rolloutExpansions  6460, biasedRolloutExpansions  2587
25,     4,     5,    15,     0: dur 0.3361, iter   247, nodesExplored   247, rollouts   247,
                      backprops   497, rolloutExpansions  3705, biasedRolloutExpansions     0
25,     4,     5,    15,     7: dur 0.3108, iter   209, nodesExplored   209, rollouts   209,
                      backprops   420, rolloutExpansions  3136, biasedRolloutExpansions  1122
25,     4,     5,    50,     0: dur 0.3255, iter    96, nodesExplored    96, rollouts    96,
                      backprops   193, rolloutExpansions  4845, biasedRolloutExpansions     0
25,     4,     5,    50,     7: dur 0.3038, iter    91, nodesExplored    91, rollouts    91,
                      backprops   183, rolloutExpansions  4585, biasedRolloutExpansions   641
25,     4,     5,   200,     0: dur 0.3226, iter    33, nodesExplored    33, rollouts    33,
                      backprops    66, rolloutExpansions  6660, biasedRolloutExpansions     0
25,     4,     5,   200,     7: dur 0.3144, iter    32, nodesExplored    32, rollouts    32,
                      backprops    64, rolloutExpansions  6400, biasedRolloutExpansions   224
25,     4,     5,   200,    30: dur 0.3166, iter    33, nodesExplored    33, rollouts    33,
                      backprops    66, rolloutExpansions  6640, biasedRolloutExpansions   996
25,     4,     5,   200,   100: dur 0.3052, iter    30, nodesExplored    30, rollouts    30,
                      backprops    60, rolloutExpansions  6000, biasedRolloutExpansions  2397
25,     4,    20,    15,     0: dur 0.3200, iter   219, nodesExplored   219, rollouts   219,
                      backprops   439, rolloutExpansions  3291, biasedRolloutExpansions     0
25,     4,    20,    15,     7: dur 0.3068, iter   190, nodesExplored   190, rollouts   190,
                      backprops   381, rolloutExpansions  2851, biasedRolloutExpansions  1017
25,     4,    20,    50,     0: dur 0.3196, iter    93, nodesExplored    93, rollouts    93,
                      backprops   186, rolloutExpansions  4665, biasedRolloutExpansions     0
25,     4,    20,    50,     7: dur 0.3067, iter    91, nodesExplored    91, rollouts    91,
                      backprops   182, rolloutExpansions  4555, biasedRolloutExpansions   637
25,     4,    20,   200,     0: dur 0.3103, iter    32, nodesExplored    32, rollouts    32,
                      backprops    65, rolloutExpansions  6497, biasedRolloutExpansions     0
25,     4,    20,   200,     7: dur 0.3146, iter    32, nodesExplored    32, rollouts    32,
                      backprops    65, rolloutExpansions  6560, biasedRolloutExpansions   229
25,     4,    20,   200,    30: dur 0.3129, iter    33, nodesExplored    33, rollouts    33,
                      backprops    67, rolloutExpansions  6700, biasedRolloutExpansions  1005
25,     4,    20,   200,   100: dur 0.3025, iter    29, nodesExplored    29, rollouts    29,
                      backprops    58, rolloutExpansions  5855, biasedRolloutExpansions  2317
25,    11,     5,    15,     0: dur 0.3039, iter   209, nodesExplored   209, rollouts   209,
                      backprops   421, rolloutExpansions  3147, biasedRolloutExpansions     0
25,    11,     5,    15,     7: dur 0.3156, iter   180, nodesExplored   180, rollouts   180,
                      backprops   361, rolloutExpansions  2703, biasedRolloutExpansions   970
25,    11,     5,    50,     0: dur 0.3133, iter    85, nodesExplored    85, rollouts    85,
                      backprops   170, rolloutExpansions  4260, biasedRolloutExpansions     0
25,    11,     5,    50,     7: dur 0.3049, iter    82, nodesExplored    82, rollouts    82,
                      backprops   165, rolloutExpansions  4145, biasedRolloutExpansions   580
25,    11,     5,   200,     0: dur 0.3169, iter    27, nodesExplored    27, rollouts    27,
                      backprops    55, rolloutExpansions  5580, biasedRolloutExpansions     0
25,    11,     5,   200,     7: dur 0.3044, iter    28, nodesExplored    28, rollouts    28,
                      backprops    56, rolloutExpansions  5660, biasedRolloutExpansions   198
25,    11,     5,   200,    30: dur 0.3058, iter    28, nodesExplored    28, rollouts    28,
                      backprops    57, rolloutExpansions  5740, biasedRolloutExpansions   861
25,    11,     5,   200,   100: dur 0.3111, iter    28, nodesExplored    28, rollouts    28,
                      backprops    56, rolloutExpansions  5652, biasedRolloutExpansions  2271
25,    11,    20,    15,     0: dur 0.3267, iter   224, nodesExplored   224, rollouts   224,
                      backprops   451, rolloutExpansions  3373, biasedRolloutExpansions     0
25,    11,    20,    15,     7: dur 0.3101, iter   202, nodesExplored   202, rollouts   202,
                      backprops   407, rolloutExpansions  3042, biasedRolloutExpansions  1080
25,    11,    20,    50,     0: dur 0.3146, iter    85, nodesExplored    85, rollouts    85,
                      backprops   170, rolloutExpansions  4265, biasedRolloutExpansions     0
25,    11,    20,    50,     7: dur 0.3025, iter    85, nodesExplored    85, rollouts    85,
                      backprops   170, rolloutExpansions  4260, biasedRolloutExpansions   596
25,    11,    20,   200,     0: dur 0.3121, iter    28, nodesExplored    28, rollouts    28,
                      backprops    57, rolloutExpansions  5780, biasedRolloutExpansions     0
25,    11,    20,   200,     7: dur 0.3050, iter    27, nodesExplored    27, rollouts    27,
                      backprops    54, rolloutExpansions  5440, biasedRolloutExpansions   190
25,    11,    20,   200,    30: dur 0.3040, iter    27, nodesExplored    27, rollouts    27,
                      backprops    54, rolloutExpansions  5440, biasedRolloutExpansions   816
25,    11,    20,   200,   100: dur 0.3055, iter    24, nodesExplored    24, rollouts    24,
                      backprops    49, rolloutExpansions  4956, biasedRolloutExpansions  1970
AVG:
dur 0.3134, iter   180, nodesExplored   180, rollouts   180,
                      backprops   435, rolloutExpansions  8615, biasedRolloutExpansions  1126
    """

    # AFTER JUST ROLLOUT NO-COPY:
    """
nArmy, nTile, +Army, depth, biasD
4,     4,     5,    15,     7: dur 0.3122, iter   485, nodesExplored   485, rollouts   485, 
                      backprops  1280, rolloutExpansions  7281, biasedRolloutExpansions  2621
4,     4,     5,    50,     7: dur 0.3021, iter   289, nodesExplored   289, rollouts   289, 
                      backprops   709, rolloutExpansions 14475, biasedRolloutExpansions  2026
4,     4,     5,   100,     7: dur 0.3019, iter    90, nodesExplored    90, rollouts    90, 
                      backprops   193, rolloutExpansions  9000, biasedRolloutExpansions   630
4,     4,     5,   100,    30: dur 0.3041, iter   156, nodesExplored   156, rollouts   156, 
                      backprops   360, rolloutExpansions 15598, biasedRolloutExpansions  4680
4,     4,    20,    15,     7: dur 0.3048, iter   544, nodesExplored   544, rollouts   544, 
                      backprops  1463, rolloutExpansions  8164, biasedRolloutExpansions  2913
4,     4,    20,    50,     7: dur 0.3008, iter   276, nodesExplored   276, rollouts   276, 
                      backprops   687, rolloutExpansions 13845, biasedRolloutExpansions  1938
4,     4,    20,   100,     7: dur 0.3058, iter   167, nodesExplored   167, rollouts   167, 
                      backprops   389, rolloutExpansions 16705, biasedRolloutExpansions  1170
4,     4,    20,   100,    30: dur 0.3038, iter   165, nodesExplored   165, rollouts   165, 
                      backprops   389, rolloutExpansions 16465, biasedRolloutExpansions  4937
4,    11,     5,    15,     7: dur 0.3045, iter   664, nodesExplored   664, rollouts   664, 
                      backprops  1772, rolloutExpansions  9969, biasedRolloutExpansions  3550
4,    11,     5,    50,     7: dur 0.3035, iter   291, nodesExplored   291, rollouts   291, 
                      backprops   715, rolloutExpansions 14565, biasedRolloutExpansions  2039
4,    11,     5,   100,     7: dur 0.3009, iter   158, nodesExplored   158, rollouts   158, 
                      backprops   360, rolloutExpansions 15889, biasedRolloutExpansions  1112
4,    11,     5,   100,    30: dur 0.3064, iter   163, nodesExplored   163, rollouts   163, 
                      backprops   379, rolloutExpansions 16338, biasedRolloutExpansions  4893
4,    11,    20,    15,     7: dur 0.3056, iter   430, nodesExplored   430, rollouts   430, 
                      backprops  1123, rolloutExpansions  6460, biasedRolloutExpansions  2305
4,    11,    20,    50,     7: dur 0.3016, iter   168, nodesExplored   168, rollouts   168, 
                      backprops   393, rolloutExpansions  8417, biasedRolloutExpansions  1178
4,    11,    20,   100,     7: dur 0.3085, iter    95, nodesExplored    95, rollouts    95, 
                      backprops   209, rolloutExpansions  9537, biasedRolloutExpansions   667
4,    11,    20,   100,    30: dur 0.3019, iter    91, nodesExplored    91, rollouts    91, 
                      backprops   202, rolloutExpansions  9095, biasedRolloutExpansions  2733
15,     4,     5,    15,     7: dur 0.3138, iter   334, nodesExplored   334, rollouts   334, 
                      backprops   691, rolloutExpansions  5022, biasedRolloutExpansions  1793
15,     4,     5,    50,     7: dur 0.3023, iter   150, nodesExplored   150, rollouts   150, 
                      backprops   305, rolloutExpansions  7530, biasedRolloutExpansions  1054
15,     4,     5,   100,     7: dur 0.3101, iter    98, nodesExplored    98, rollouts    98, 
                      backprops   196, rolloutExpansions  9830, biasedRolloutExpansions   688
15,     4,     5,   100,    30: dur 0.3033, iter    89, nodesExplored    89, rollouts    89, 
                      backprops   180, rolloutExpansions  8980, biasedRolloutExpansions  2691
15,     4,    20,    15,     7: dur 0.3199, iter   340, nodesExplored   340, rollouts   340, 
                      backprops   702, rolloutExpansions  5113, biasedRolloutExpansions  1823
15,     4,    20,    50,     7: dur 0.3016, iter   147, nodesExplored   147, rollouts   147, 
                      backprops   298, rolloutExpansions  7395, biasedRolloutExpansions  1035
15,     4,    20,   100,     7: dur 0.3052, iter    99, nodesExplored    99, rollouts    99, 
                      backprops   200, rolloutExpansions  9970, biasedRolloutExpansions   697
15,     4,    20,   100,    30: dur 0.3021, iter    94, nodesExplored    94, rollouts    94, 
                      backprops   189, rolloutExpansions  9430, biasedRolloutExpansions  2826
15,    11,     5,    15,     7: dur 0.3116, iter   317, nodesExplored   317, rollouts   317, 
                      backprops   654, rolloutExpansions  4767, biasedRolloutExpansions  1711
15,    11,     5,    50,     7: dur 0.3044, iter   147, nodesExplored   147, rollouts   147, 
                      backprops   297, rolloutExpansions  7370, biasedRolloutExpansions  1031
15,    11,     5,   100,     7: dur 0.3058, iter    86, nodesExplored    86, rollouts    86, 
                      backprops   173, rolloutExpansions  8630, biasedRolloutExpansions   604
15,    11,     5,   100,    30: dur 0.3024, iter    81, nodesExplored    81, rollouts    81, 
                      backprops   164, rolloutExpansions  8190, biasedRolloutExpansions  2451
15,    11,    20,    15,     7: dur 0.3113, iter   199, nodesExplored   199, rollouts   199, 
                      backprops   404, rolloutExpansions  2985, biasedRolloutExpansions  1065
15,    11,    20,    50,     7: dur 0.3045, iter    74, nodesExplored    74, rollouts    74, 
                      backprops   149, rolloutExpansions  3720, biasedRolloutExpansions   520
15,    11,    20,   100,     7: dur 0.3017, iter    82, nodesExplored    82, rollouts    82, 
                      backprops   165, rolloutExpansions  8260, biasedRolloutExpansions   578
15,    11,    20,   100,    30: dur 0.3028, iter    69, nodesExplored    69, rollouts    69, 
                      backprops   138, rolloutExpansions  6906, biasedRolloutExpansions  2072
AVG:
dur 0.3053, iter   207, nodesExplored   207, rollouts   207, 
                      backprops   485, rolloutExpansions  9559, biasedRolloutExpansions  1938

nArmy, nTile, +Army, depth, biasD
3,     0,     5,    15,     0: dur 0.3164, iter   924, nodesExplored   924, rollouts   924, 
                      backprops  2623, rolloutExpansions 13870, biasedRolloutExpansions     0
3,     0,     5,    15,     7: dur 0.3078, iter   770, nodesExplored   770, rollouts   770, 
                      backprops  2193, rolloutExpansions 11557, biasedRolloutExpansions  4114
3,     0,     5,    50,     0: dur 0.3132, iter   362, nodesExplored   362, rollouts   362, 
                      backprops   963, rolloutExpansions 18105, biasedRolloutExpansions     0
3,     0,     5,    50,     7: dur 0.3005, iter   351, nodesExplored   351, rollouts   351, 
                      backprops   932, rolloutExpansions 17585, biasedRolloutExpansions  2461
3,     0,     5,   200,     0: dur 0.3032, iter   114, nodesExplored   114, rollouts   114, 
                      backprops   276, rolloutExpansions 22864, biasedRolloutExpansions     0
3,     0,     5,   200,     7: dur 0.3013, iter   124, nodesExplored   124, rollouts   124, 
                      backprops   304, rolloutExpansions 24671, biasedRolloutExpansions   870
3,     0,     5,   200,    30: dur 0.3038, iter   130, nodesExplored   130, rollouts   130, 
                      backprops   318, rolloutExpansions 25003, biasedRolloutExpansions  3908
3,     0,     5,   200,   100: dur 0.3075, iter   133, nodesExplored   133, rollouts   133, 
                      backprops   326, rolloutExpansions 23953, biasedRolloutExpansions  9491
3,     0,    20,    15,     0: dur 0.3125, iter   879, nodesExplored   879, rollouts   879, 
                      backprops  2491, rolloutExpansions 13194, biasedRolloutExpansions     0
3,     0,    20,    15,     7: dur 0.3073, iter   755, nodesExplored   755, rollouts   755, 
                      backprops  2154, rolloutExpansions 11326, biasedRolloutExpansions  4049
3,     0,    20,    50,     0: dur 0.3031, iter   346, nodesExplored   346, rollouts   346, 
                      backprops   926, rolloutExpansions 17305, biasedRolloutExpansions     0
3,     0,    20,    50,     7: dur 0.3044, iter   359, nodesExplored   359, rollouts   359, 
                      backprops   967, rolloutExpansions 17980, biasedRolloutExpansions  2517
3,     0,    20,   200,     0: dur 0.3094, iter   112, nodesExplored   112, rollouts   112, 
                      backprops   270, rolloutExpansions 22506, biasedRolloutExpansions     0
3,     0,    20,   200,     7: dur 0.3013, iter   121, nodesExplored   121, rollouts   121, 
                      backprops   293, rolloutExpansions 24126, biasedRolloutExpansions   850
3,     0,    20,   200,    30: dur 0.3052, iter   131, nodesExplored   131, rollouts   131, 
                      backprops   323, rolloutExpansions 25155, biasedRolloutExpansions  3934
3,     0,    20,   200,   100: dur 0.3055, iter   130, nodesExplored   130, rollouts   130, 
                      backprops   320, rolloutExpansions 23539, biasedRolloutExpansions  9366
3,     4,     5,    15,     0: dur 0.3170, iter   871, nodesExplored   871, rollouts   871, 
                      backprops  2430, rolloutExpansions 13074, biasedRolloutExpansions     0
3,     4,     5,    15,     7: dur 0.3061, iter   752, nodesExplored   752, rollouts   752, 
                      backprops  2094, rolloutExpansions 11284, biasedRolloutExpansions  4038
3,     4,     5,    50,     0: dur 0.3027, iter   342, nodesExplored   342, rollouts   342, 
                      backprops   897, rolloutExpansions 17100, biasedRolloutExpansions     0
3,     4,     5,    50,     7: dur 0.3016, iter   330, nodesExplored   330, rollouts   330, 
                      backprops   873, rolloutExpansions 16540, biasedRolloutExpansions  2315
3,     4,     5,   200,     0: dur 0.3093, iter   108, nodesExplored   108, rollouts   108, 
                      backprops   252, rolloutExpansions 21627, biasedRolloutExpansions     0
3,     4,     5,   200,     7: dur 0.3017, iter   118, nodesExplored   118, rollouts   118, 
                      backprops   278, rolloutExpansions 23506, biasedRolloutExpansions   826
3,     4,     5,   200,    30: dur 0.3047, iter   118, nodesExplored   118, rollouts   118, 
                      backprops   282, rolloutExpansions 23305, biasedRolloutExpansions  3560
3,     4,     5,   200,   100: dur 0.3044, iter   118, nodesExplored   118, rollouts   118, 
                      backprops   283, rolloutExpansions 22145, biasedRolloutExpansions  8815
3,     4,    20,    15,     0: dur 0.3004, iter   880, nodesExplored   880, rollouts   880, 
                      backprops  2629, rolloutExpansions 13203, biasedRolloutExpansions     0
3,     4,    20,    15,     7: dur 0.3098, iter   774, nodesExplored   774, rollouts   774, 
                      backprops  2195, rolloutExpansions 11611, biasedRolloutExpansions  4181
3,     4,    20,    50,     0: dur 0.3114, iter   367, nodesExplored   367, rollouts   367, 
                      backprops   993, rolloutExpansions 18380, biasedRolloutExpansions     0
3,     4,    20,    50,     7: dur 0.3020, iter   336, nodesExplored   336, rollouts   336, 
                      backprops   907, rolloutExpansions 16819, biasedRolloutExpansions  2355
3,     4,    20,   200,     0: dur 0.3048, iter   111, nodesExplored   111, rollouts   111, 
                      backprops   271, rolloutExpansions 22169, biasedRolloutExpansions     0
3,     4,    20,   200,     7: dur 0.3015, iter   121, nodesExplored   121, rollouts   121, 
                      backprops   296, rolloutExpansions 24085, biasedRolloutExpansions   848
3,     4,    20,   200,    30: dur 0.3043, iter   121, nodesExplored   121, rollouts   121, 
                      backprops   299, rolloutExpansions 23781, biasedRolloutExpansions  3637
3,     4,    20,   200,   100: dur 0.3041, iter   111, nodesExplored   111, rollouts   111, 
                      backprops   270, rolloutExpansions 21686, biasedRolloutExpansions  8595
3,    11,     5,    15,     0: dur 0.3142, iter   914, nodesExplored   914, rollouts   914, 
                      backprops  2620, rolloutExpansions 13723, biasedRolloutExpansions     0
3,    11,     5,    15,     7: dur 0.3036, iter   752, nodesExplored   752, rollouts   752, 
                      backprops  2110, rolloutExpansions 11283, biasedRolloutExpansions  4052
3,    11,     5,    50,     0: dur 0.3066, iter   349, nodesExplored   349, rollouts   349, 
                      backprops   915, rolloutExpansions 17480, biasedRolloutExpansions     0
3,    11,     5,    50,     7: dur 0.3025, iter   340, nodesExplored   340, rollouts   340, 
                      backprops   899, rolloutExpansions 17040, biasedRolloutExpansions  2385
3,    11,     5,   200,     0: dur 0.3042, iter   112, nodesExplored   112, rollouts   112, 
                      backprops   264, rolloutExpansions 22448, biasedRolloutExpansions     0
3,    11,     5,   200,     7: dur 0.3052, iter   114, nodesExplored   114, rollouts   114, 
                      backprops   271, rolloutExpansions 22777, biasedRolloutExpansions   798
3,    11,     5,   200,    30: dur 0.3016, iter   116, nodesExplored   116, rollouts   116, 
                      backprops   269, rolloutExpansions 23058, biasedRolloutExpansions  3502
3,    11,     5,   200,   100: dur 0.3026, iter   111, nodesExplored   111, rollouts   111, 
                      backprops   262, rolloutExpansions 21638, biasedRolloutExpansions  8582
3,    11,    20,    15,     0: dur 0.3107, iter   851, nodesExplored   851, rollouts   851, 
                      backprops  2579, rolloutExpansions 12769, biasedRolloutExpansions     0
3,    11,    20,    15,     7: dur 0.3065, iter   841, nodesExplored   841, rollouts   841, 
                      backprops  2433, rolloutExpansions 12623, biasedRolloutExpansions  4499
3,    11,    20,    50,     0: dur 0.3007, iter   357, nodesExplored   357, rollouts   357, 
                      backprops   968, rolloutExpansions 17888, biasedRolloutExpansions     0
3,    11,    20,    50,     7: dur 0.3089, iter   358, nodesExplored   358, rollouts   358, 
                      backprops   980, rolloutExpansions 17899, biasedRolloutExpansions  2509
3,    11,    20,   200,     0: dur 0.3041, iter   108, nodesExplored   108, rollouts   108, 
                      backprops   261, rolloutExpansions 21687, biasedRolloutExpansions     0
3,    11,    20,   200,     7: dur 0.3076, iter   122, nodesExplored   122, rollouts   122, 
                      backprops   297, rolloutExpansions 24118, biasedRolloutExpansions   856
3,    11,    20,   200,    30: dur 0.3015, iter   134, nodesExplored   134, rollouts   134, 
                      backprops   337, rolloutExpansions 24650, biasedRolloutExpansions  3929
3,    11,    20,   200,   100: dur 0.3040, iter   112, nodesExplored   112, rollouts   112, 
                      backprops   276, rolloutExpansions 21555, biasedRolloutExpansions  8607
8,     0,     5,    15,     0: dur 0.3209, iter   621, nodesExplored   621, rollouts   621, 
                      backprops  1485, rolloutExpansions  9316, biasedRolloutExpansions     0
8,     0,     5,    15,     7: dur 0.3057, iter   494, nodesExplored   494, rollouts   494, 
                      backprops  1144, rolloutExpansions  7410, biasedRolloutExpansions  2650
8,     0,     5,    50,     0: dur 0.3072, iter   242, nodesExplored   242, rollouts   242, 
                      backprops   522, rolloutExpansions 12105, biasedRolloutExpansions     0
8,     0,     5,    50,     7: dur 0.3029, iter   241, nodesExplored   241, rollouts   241, 
                      backprops   521, rolloutExpansions 12085, biasedRolloutExpansions  1691
8,     0,     5,   200,     0: dur 0.3068, iter    84, nodesExplored    84, rollouts    84, 
                      backprops   171, rolloutExpansions 16800, biasedRolloutExpansions     0
8,     0,     5,   200,     7: dur 0.3059, iter    89, nodesExplored    89, rollouts    89, 
                      backprops   185, rolloutExpansions 17920, biasedRolloutExpansions   627
8,     0,     5,   200,    30: dur 0.3078, iter    83, nodesExplored    83, rollouts    83, 
                      backprops   170, rolloutExpansions 16692, biasedRolloutExpansions  2505
8,     0,     5,   200,   100: dur 0.3017, iter    88, nodesExplored    88, rollouts    88, 
                      backprops   180, rolloutExpansions 17401, biasedRolloutExpansions  6906
8,     0,    20,    15,     0: dur 0.2790, iter   493, nodesExplored   493, rollouts   493, 
                      backprops  1152, rolloutExpansions  7401, biasedRolloutExpansions     0
8,     0,    20,    15,     7: dur 0.3008, iter   512, nodesExplored   512, rollouts   512, 
                      backprops  1190, rolloutExpansions  7687, biasedRolloutExpansions  2754
8,     0,    20,    50,     0: dur 0.3023, iter   237, nodesExplored   237, rollouts   237, 
                      backprops   514, rolloutExpansions 11880, biasedRolloutExpansions     0
8,     0,    20,    50,     7: dur 0.3071, iter   241, nodesExplored   241, rollouts   241, 
                      backprops   520, rolloutExpansions 12070, biasedRolloutExpansions  1689
8,     0,    20,   200,     0: dur 0.3025, iter    82, nodesExplored    82, rollouts    82, 
                      backprops   168, rolloutExpansions 16570, biasedRolloutExpansions     0
8,     0,    20,   200,     7: dur 0.3025, iter    87, nodesExplored    87, rollouts    87, 
                      backprops   180, rolloutExpansions 17520, biasedRolloutExpansions   613
8,     0,    20,   200,    30: dur 0.3020, iter    90, nodesExplored    90, rollouts    90, 
                      backprops   186, rolloutExpansions 18124, biasedRolloutExpansions  2721
8,     0,    20,   200,   100: dur 0.3027, iter    88, nodesExplored    88, rollouts    88, 
                      backprops   180, rolloutExpansions 17397, biasedRolloutExpansions  6927
8,     4,     5,    15,     0: dur 0.3114, iter   571, nodesExplored   571, rollouts   571, 
                      backprops  1319, rolloutExpansions  8574, biasedRolloutExpansions     0
8,     4,     5,    15,     7: dur 0.3050, iter   459, nodesExplored   459, rollouts   459, 
                      backprops  1034, rolloutExpansions  6885, biasedRolloutExpansions  2459
8,     4,     5,    50,     0: dur 0.3031, iter   201, nodesExplored   201, rollouts   201, 
                      backprops   426, rolloutExpansions 10095, biasedRolloutExpansions     0
8,     4,     5,    50,     7: dur 0.3117, iter   197, nodesExplored   197, rollouts   197, 
                      backprops   417, rolloutExpansions  9875, biasedRolloutExpansions  1382
8,     4,     5,   200,     0: dur 0.3031, iter    73, nodesExplored    73, rollouts    73, 
                      backprops   150, rolloutExpansions 14731, biasedRolloutExpansions     0
8,     4,     5,   200,     7: dur 0.3111, iter    68, nodesExplored    68, rollouts    68, 
                      backprops   138, rolloutExpansions 13599, biasedRolloutExpansions   476
8,     4,     5,   200,    30: dur 0.3036, iter    80, nodesExplored    80, rollouts    80, 
                      backprops   164, rolloutExpansions 16135, biasedRolloutExpansions  2421
8,     4,     5,   200,   100: dur 0.3024, iter    77, nodesExplored    77, rollouts    77, 
                      backprops   157, rolloutExpansions 15352, biasedRolloutExpansions  6084
8,     4,    20,    15,     0: dur 0.3068, iter   563, nodesExplored   563, rollouts   563, 
                      backprops  1317, rolloutExpansions  8446, biasedRolloutExpansions     0
8,     4,    20,    15,     7: dur 0.2773, iter   419, nodesExplored   419, rollouts   419, 
                      backprops   949, rolloutExpansions  6286, biasedRolloutExpansions  2249
8,     4,    20,    50,     0: dur 0.3051, iter   211, nodesExplored   211, rollouts   211, 
                      backprops   452, rolloutExpansions 10555, biasedRolloutExpansions     0
8,     4,    20,    50,     7: dur 0.3035, iter   200, nodesExplored   200, rollouts   200, 
                      backprops   423, rolloutExpansions 10005, biasedRolloutExpansions  1400
8,     4,    20,   200,     0: dur 0.3070, iter    72, nodesExplored    72, rollouts    72, 
                      backprops   146, rolloutExpansions 14439, biasedRolloutExpansions     0
8,     4,    20,   200,     7: dur 0.3021, iter    74, nodesExplored    74, rollouts    74, 
                      backprops   151, rolloutExpansions 14829, biasedRolloutExpansions   519
8,     4,    20,   200,    30: dur 0.3019, iter    75, nodesExplored    75, rollouts    75, 
                      backprops   154, rolloutExpansions 15054, biasedRolloutExpansions  2263
8,     4,    20,   200,   100: dur 0.3027, iter    67, nodesExplored    67, rollouts    67, 
                      backprops   137, rolloutExpansions 13568, biasedRolloutExpansions  5384
8,    11,     5,    15,     0: dur 0.3151, iter   564, nodesExplored   564, rollouts   564, 
                      backprops  1308, rolloutExpansions  8467, biasedRolloutExpansions     0
8,    11,     5,    15,     7: dur 0.3043, iter   479, nodesExplored   479, rollouts   479, 
                      backprops  1089, rolloutExpansions  7194, biasedRolloutExpansions  2587
8,    11,     5,    50,     0: dur 0.3023, iter   214, nodesExplored   214, rollouts   214, 
                      backprops   455, rolloutExpansions 10735, biasedRolloutExpansions     0
8,    11,     5,    50,     7: dur 0.3009, iter   214, nodesExplored   214, rollouts   214, 
                      backprops   455, rolloutExpansions 10720, biasedRolloutExpansions  1500
8,    11,     5,   200,     0: dur 0.3029, iter    75, nodesExplored    75, rollouts    75, 
                      backprops   152, rolloutExpansions 15036, biasedRolloutExpansions     0
8,    11,     5,   200,     7: dur 0.3028, iter    74, nodesExplored    74, rollouts    74, 
                      backprops   151, rolloutExpansions 14940, biasedRolloutExpansions   522
8,    11,     5,   200,    30: dur 0.3078, iter    68, nodesExplored    68, rollouts    68, 
                      backprops   139, rolloutExpansions 13755, biasedRolloutExpansions  2064
8,    11,     5,   200,   100: dur 0.3171, iter    64, nodesExplored    64, rollouts    64, 
                      backprops   129, rolloutExpansions 12786, biasedRolloutExpansions  5084
8,    11,    20,    15,     0: dur 0.2974, iter   505, nodesExplored   505, rollouts   505, 
                      backprops  1222, rolloutExpansions  7587, biasedRolloutExpansions     0
8,    11,    20,    15,     7: dur 0.3058, iter   461, nodesExplored   461, rollouts   461, 
                      backprops  1057, rolloutExpansions  6927, biasedRolloutExpansions  2485
8,    11,    20,    50,     0: dur 0.3023, iter   206, nodesExplored   206, rollouts   206, 
                      backprops   442, rolloutExpansions 10345, biasedRolloutExpansions     0
8,    11,    20,    50,     7: dur 0.3035, iter   200, nodesExplored   200, rollouts   200, 
                      backprops   424, rolloutExpansions 10015, biasedRolloutExpansions  1402
8,    11,    20,   200,     0: dur 0.3020, iter    69, nodesExplored    69, rollouts    69, 
                      backprops   141, rolloutExpansions 13953, biasedRolloutExpansions     0
8,    11,    20,   200,     7: dur 0.3083, iter    76, nodesExplored    76, rollouts    76, 
                      backprops   154, rolloutExpansions 15194, biasedRolloutExpansions   532
8,    11,    20,   200,    30: dur 0.3026, iter    71, nodesExplored    71, rollouts    71, 
                      backprops   144, rolloutExpansions 14223, biasedRolloutExpansions  2138
8,    11,    20,   200,   100: dur 0.3020, iter    63, nodesExplored    63, rollouts    63, 
                      backprops   129, rolloutExpansions 12697, biasedRolloutExpansions  5040
25,     0,     5,    15,     0: dur 0.3343, iter   279, nodesExplored   279, rollouts   279, 
                      backprops   563, rolloutExpansions  4189, biasedRolloutExpansions     0
25,     0,     5,    15,     7: dur 0.3157, iter   182, nodesExplored   182, rollouts   182, 
                      backprops   367, rolloutExpansions  2743, biasedRolloutExpansions   981
25,     0,     5,    50,     0: dur 0.3060, iter   115, nodesExplored   115, rollouts   115, 
                      backprops   231, rolloutExpansions  5790, biasedRolloutExpansions     0
25,     0,     5,    50,     7: dur 0.3032, iter   110, nodesExplored   110, rollouts   110, 
                      backprops   221, rolloutExpansions  5525, biasedRolloutExpansions   773
25,     0,     5,   200,     0: dur 0.3064, iter    51, nodesExplored    51, rollouts    51, 
                      backprops   102, rolloutExpansions 10259, biasedRolloutExpansions     0
25,     0,     5,   200,     7: dur 0.3058, iter    43, nodesExplored    43, rollouts    43, 
                      backprops    87, rolloutExpansions  8740, biasedRolloutExpansions   305
25,     0,     5,   200,    30: dur 0.3062, iter    50, nodesExplored    50, rollouts    50, 
                      backprops   101, rolloutExpansions 10160, biasedRolloutExpansions  1524
25,     0,     5,   200,   100: dur 0.3042, iter    48, nodesExplored    48, rollouts    48, 
                      backprops    97, rolloutExpansions  9758, biasedRolloutExpansions  3876
25,     0,    20,    15,     0: dur 0.3101, iter   243, nodesExplored   243, rollouts   243, 
                      backprops   490, rolloutExpansions  3657, biasedRolloutExpansions     0
25,     0,    20,    15,     7: dur 0.3066, iter   209, nodesExplored   209, rollouts   209, 
                      backprops   419, rolloutExpansions  3136, biasedRolloutExpansions  1110
25,     0,    20,    50,     0: dur 0.2845, iter   105, nodesExplored   105, rollouts   105, 
                      backprops   210, rolloutExpansions  5265, biasedRolloutExpansions     0
25,     0,    20,    50,     7: dur 0.3067, iter   109, nodesExplored   109, rollouts   109, 
                      backprops   218, rolloutExpansions  5450, biasedRolloutExpansions   763
25,     0,    20,   200,     0: dur 0.3078, iter    50, nodesExplored    50, rollouts    50, 
                      backprops   100, rolloutExpansions 10000, biasedRolloutExpansions     0
25,     0,    20,   200,     7: dur 0.3032, iter    50, nodesExplored    50, rollouts    50, 
                      backprops   100, rolloutExpansions 10040, biasedRolloutExpansions   351
25,     0,    20,   200,    30: dur 0.3031, iter    50, nodesExplored    50, rollouts    50, 
                      backprops   100, rolloutExpansions 10060, biasedRolloutExpansions  1509
25,     0,    20,   200,   100: dur 0.3090, iter    48, nodesExplored    48, rollouts    48, 
                      backprops    97, rolloutExpansions  9737, biasedRolloutExpansions  3881
25,     4,     5,    15,     0: dur 0.3212, iter   260, nodesExplored   260, rollouts   260, 
                      backprops   524, rolloutExpansions  3912, biasedRolloutExpansions     0
25,     4,     5,    15,     7: dur 0.3116, iter   212, nodesExplored   212, rollouts   212, 
                      backprops   425, rolloutExpansions  3180, biasedRolloutExpansions  1149
25,     4,     5,    50,     0: dur 0.3034, iter   111, nodesExplored   111, rollouts   111, 
                      backprops   223, rolloutExpansions  5565, biasedRolloutExpansions     0
25,     4,     5,    50,     7: dur 0.3034, iter   105, nodesExplored   105, rollouts   105, 
                      backprops   211, rolloutExpansions  5290, biasedRolloutExpansions   740
25,     4,     5,   200,     0: dur 0.3038, iter    46, nodesExplored    46, rollouts    46, 
                      backprops    92, rolloutExpansions  9220, biasedRolloutExpansions     0
25,     4,     5,   200,     7: dur 0.3050, iter    45, nodesExplored    45, rollouts    45, 
                      backprops    90, rolloutExpansions  9020, biasedRolloutExpansions   315
25,     4,     5,   200,    30: dur 0.3061, iter    43, nodesExplored    43, rollouts    43, 
                      backprops    86, rolloutExpansions  8640, biasedRolloutExpansions  1296
25,     4,     5,   200,   100: dur 0.3058, iter    38, nodesExplored    38, rollouts    38, 
                      backprops    76, rolloutExpansions  7630, biasedRolloutExpansions  3040
25,     4,    20,    15,     0: dur 0.3119, iter   217, nodesExplored   217, rollouts   217, 
                      backprops   438, rolloutExpansions  3267, biasedRolloutExpansions     0
25,     4,    20,    15,     7: dur 0.3056, iter   182, nodesExplored   182, rollouts   182, 
                      backprops   366, rolloutExpansions  2734, biasedRolloutExpansions   979
25,     4,    20,    50,     0: dur 0.3020, iter    98, nodesExplored    98, rollouts    98, 
                      backprops   197, rolloutExpansions  4930, biasedRolloutExpansions     0
25,     4,    20,    50,     7: dur 0.3024, iter    93, nodesExplored    93, rollouts    93, 
                      backprops   187, rolloutExpansions  4690, biasedRolloutExpansions   656
25,     4,    20,   200,     0: dur 0.3037, iter    39, nodesExplored    39, rollouts    39, 
                      backprops    78, rolloutExpansions  7860, biasedRolloutExpansions     0
25,     4,    20,   200,     7: dur 0.3034, iter    43, nodesExplored    43, rollouts    43, 
                      backprops    87, rolloutExpansions  8700, biasedRolloutExpansions   304
25,     4,    20,   200,    30: dur 0.3043, iter    44, nodesExplored    44, rollouts    44, 
                      backprops    89, rolloutExpansions  8940, biasedRolloutExpansions  1341
25,     4,    20,   200,   100: dur 0.3080, iter    42, nodesExplored    42, rollouts    42, 
                      backprops    84, rolloutExpansions  8400, biasedRolloutExpansions  3337
25,    11,     5,    15,     0: dur 0.3061, iter   216, nodesExplored   216, rollouts   216, 
                      backprops   433, rolloutExpansions  3240, biasedRolloutExpansions     0
25,    11,     5,    15,     7: dur 0.3134, iter   194, nodesExplored   194, rollouts   194, 
                      backprops   390, rolloutExpansions  2914, biasedRolloutExpansions  1029
25,    11,     5,    50,     0: dur 0.3018, iter    91, nodesExplored    91, rollouts    91, 
                      backprops   183, rolloutExpansions  4595, biasedRolloutExpansions     0
25,    11,     5,    50,     7: dur 0.3136, iter    89, nodesExplored    89, rollouts    89, 
                      backprops   179, rolloutExpansions  4475, biasedRolloutExpansions   626
25,    11,     5,   200,     0: dur 0.3127, iter    39, nodesExplored    39, rollouts    39, 
                      backprops    79, rolloutExpansions  7980, biasedRolloutExpansions     0
25,    11,     5,   200,     7: dur 0.3127, iter    38, nodesExplored    38, rollouts    38, 
                      backprops    76, rolloutExpansions  7660, biasedRolloutExpansions   268
25,    11,     5,   200,    30: dur 0.3043, iter    39, nodesExplored    39, rollouts    39, 
                      backprops    78, rolloutExpansions  7840, biasedRolloutExpansions  1176
25,    11,     5,   200,   100: dur 0.3052, iter    36, nodesExplored    36, rollouts    36, 
                      backprops    73, rolloutExpansions  7311, biasedRolloutExpansions  2900
25,    11,    20,    15,     0: dur 0.3189, iter   222, nodesExplored   222, rollouts   222, 
                      backprops   447, rolloutExpansions  3334, biasedRolloutExpansions     0
25,    11,    20,    15,     7: dur 0.3058, iter   181, nodesExplored   181, rollouts   181, 
                      backprops   363, rolloutExpansions  2719, biasedRolloutExpansions   971
25,    11,    20,    50,     0: dur 0.3024, iter   100, nodesExplored   100, rollouts   100, 
                      backprops   201, rolloutExpansions  5035, biasedRolloutExpansions     0
25,    11,    20,    50,     7: dur 0.3019, iter    87, nodesExplored    87, rollouts    87, 
                      backprops   175, rolloutExpansions  4390, biasedRolloutExpansions   614
25,    11,    20,   200,     0: dur 0.3040, iter    38, nodesExplored    38, rollouts    38, 
                      backprops    76, rolloutExpansions  7640, biasedRolloutExpansions     0
25,    11,    20,   200,     7: dur 0.3047, iter    37, nodesExplored    37, rollouts    37, 
                      backprops    75, rolloutExpansions  7560, biasedRolloutExpansions   264
25,    11,    20,   200,    30: dur 0.3040, iter    34, nodesExplored    34, rollouts    34, 
                      backprops    68, rolloutExpansions  6860, biasedRolloutExpansions  1029
25,    11,    20,   200,   100: dur 0.3054, iter    32, nodesExplored    32, rollouts    32, 
                      backprops    65, rolloutExpansions  6500, biasedRolloutExpansions  2593
AVG:
dur 0.3055, iter   225, nodesExplored   225, rollouts   225, 
                      backprops   555, rolloutExpansions 12594, biasedRolloutExpansions  1647

    """

    def test_benchmark_mcts(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        """
        rollout lrg
        AVG:
        dur 0.3055, iter   225, nodesExplored   225, rollouts   225, 
                              backprops   555, rolloutExpansions 12594, biasedRolloutExpansions  1647
        rollout smll
        AVG:
        dur 0.3053, iter   207, nodesExplored   207, rollouts   207, 
                              backprops   485, rolloutExpansions  9559, biasedRolloutExpansions  1938
                              
        nothing lrg
        AVG:
        dur 0.3134, iter   180, nodesExplored   180, rollouts   180,
                              backprops   435, rolloutExpansions  8615, biasedRolloutExpansions  1126
                              
        nothing smll
        AVG:
        dur 0.3116, iter   195, nodesExplored   195, rollouts   195,
                              backprops   461, rolloutExpansions  8225, biasedRolloutExpansions  1694
        """
        results = {}

        trialsPerParamSet = 10

        for allowedArmyCount in [15, 4]:
            for extraValuableTiles in [4, 11]:
                for valuableTileArmy in [20, 5]:
                    for rolloutDepth in [100, 50, 15]:
                        for biasedMax in [7, 30]:
#         for allowedArmyCount in [3, 8, 25]:
#             for extraValuableTiles in [0, 4, 11]:
#                 for valuableTileArmy in [5, 20]:
#                     for rolloutDepth in [15, 50, 200]:
#                         for biasedMax in [0, 7, 30, 100]:
                            if biasedMax > rolloutDepth // 2:
                                continue
                            for i in range(trialsPerParamSet):
                                mapFile = 'GameContinuationEntries/scrim_playground_benchmarker_holding_enemy_city.txtmap'
                                map, general, enemyGeneral = self.load_map_and_generals(mapFile, 204, fill_out_tiles=True)

                                # rawMap, _ = self.load_map_and_general(mapFile, respect_undiscovered=True, turn=204)

                                for player in [map.players[general.player], map.players[enemyGeneral.player]]:
                                    for _ in range(extraValuableTiles):
                                        tile = random.choice(player.tiles)
                                        # rawMapTile = rawMap.GetTile(tile.x, tile.y)
                                        tile.army += valuableTileArmy
                                        # rawMapTile.army += valuableTileArmy
                                #
                                # # self.enable_search_time_limits_and_disable_debug_asserts()
                                # simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap,
                                #                             allAfkExceptMapPlayer=True)
                                # bot = simHost.get_bot(general.player)
                                bot = EklipZBot()
                                bot.initialize_map_for_first_time(map)
                                bot.targetPlayer = enemyGeneral.player
                                bot.perf_timer.begin_move(42)
                                bot.init_turn()
                                bot.perform_move_prep()

                                # bot.mcts_engine.explore_factor = 0.2
                                bot.mcts_engine.biased_playouts_allowed_per_trial = biasedMax
                                bot.mcts_engine.rollout_depth = rolloutDepth
                                bot.behavior_end_of_turn_scrim_army_count = allowedArmyCount
                                # bot.init_turn()
                                # bot.viewInfo.turnInc()
                                # bot.viewInfo.armyTracker = bot.armyTracker
                                start = time.perf_counter()
                                # self.begin_capturing_logging()
                                result = bot.find_end_of_turn_sim_result(None, None, time_limit=0.3)
                                duration = time.perf_counter() - start
                                summary = bot.mcts_engine.last_summary

                                key = allowedArmyCount, extraValuableTiles, valuableTileArmy, rolloutDepth, biasedMax
                                existingResults = results.get(key, [])
                                if len(existingResults) == 0:
                                    results[key] = existingResults

                                existingResults.append((summary.iterations, summary.nodes_explored, summary.trials_performed, summary.backprop_iter, summary.rollout_expansions, summary.biased_rollout_expansions, duration))

                                if debugMode or duration < 0.2:
                                    bot.extract_engine_result_paths_and_render_sim_moves(result)
                                    bot.prep_view_info_for_render()
                                    self.render_view_info(bot._map, bot.viewInfo)

        self.begin_capturing_logging()
        logging.info('nArmy, nTile, +Army, depth, biasD')

        outer_cumulative_iterations = 0
        outer_cumulative_nodes_explored = 0
        outer_cumulative_trials_performed = 0
        outer_cumulative_backprop_iter = 0
        outer_cumulative_rollout_expansions = 0
        outer_cumulative_biased_rollout_expansions = 0
        outer_cumulative_duration = 0.0

        for resultCombo in sorted(results.keys()):
            resultList = results[resultCombo]

            # allowedArmyCount, extraValuableTiles, valuableTileArmy, rolloutDepth, biasedMax = resultCombo

            cumulative_iterations = 0
            cumulative_nodes_explored = 0
            cumulative_trials_performed = 0
            cumulative_backprop_iter = 0
            cumulative_rollout_expansions = 0
            cumulative_biased_rollout_expansions = 0
            cumulative_duration = 0.0
            for (
                    iterations,
                    nodes_explored,
                    trials_performed,
                    backprop_iter,
                    rollout_expansions,
                    biased_rollout_expansions,
                    duration
            ) in resultList:
                cumulative_iterations += iterations
                cumulative_nodes_explored += nodes_explored
                cumulative_trials_performed += trials_performed
                cumulative_backprop_iter += backprop_iter
                cumulative_rollout_expansions += rollout_expansions
                cumulative_biased_rollout_expansions += biased_rollout_expansions
                cumulative_duration += duration

                outer_cumulative_iterations += iterations
                outer_cumulative_nodes_explored += nodes_explored
                outer_cumulative_trials_performed += trials_performed
                outer_cumulative_backprop_iter += backprop_iter
                outer_cumulative_rollout_expansions += rollout_expansions
                outer_cumulative_biased_rollout_expansions += biased_rollout_expansions
                outer_cumulative_duration += duration

            avg_iterations = int(cumulative_iterations / len(resultList))
            avg_nodes_explored = int(cumulative_nodes_explored / len(resultList))
            avg_trials_performed = int(cumulative_trials_performed / len(resultList))
            avg_backprop_iter = int(cumulative_backprop_iter / len(resultList))
            avg_rollout_expansions = int(cumulative_rollout_expansions / len(resultList))
            avg_biased_rollout_expansions = int(cumulative_biased_rollout_expansions / len(resultList))
            avg_duration = cumulative_duration / len(resultList)

            logging.info(
                f'{", ".join([str(v).rjust(5) for v in resultCombo])}: dur {avg_duration:.4f}, iter {str(avg_iterations).rjust(5)}, nodesExplored {str(avg_nodes_explored).rjust(5)}, rollouts {str(avg_trials_performed).rjust(5)}, \n                      backprops {str(avg_backprop_iter).rjust(5)}, rolloutExpansions {str(avg_rollout_expansions).rjust(5)}, biasedRolloutExpansions {str(avg_biased_rollout_expansions).rjust(5)}')

        outer_avg_iterations = int(outer_cumulative_iterations / (len(results) * trialsPerParamSet))
        outer_avg_nodes_explored = int(outer_cumulative_nodes_explored / (len(results) * trialsPerParamSet))
        outer_avg_trials_performed = int(outer_cumulative_trials_performed / (len(results) * trialsPerParamSet))
        outer_avg_backprop_iter = int(outer_cumulative_backprop_iter / (len(results) * trialsPerParamSet))
        outer_avg_rollout_expansions = int(outer_cumulative_rollout_expansions / (len(results) * trialsPerParamSet))
        outer_avg_biased_rollout_expansions = int(outer_cumulative_biased_rollout_expansions / (len(results) * trialsPerParamSet))
        outer_avg_duration = outer_cumulative_duration / (len(results) * trialsPerParamSet)

        logging.info(
            f'AVG:\ndur {outer_avg_duration:.4f}, iter {str(outer_avg_iterations).rjust(5)}, nodesExplored {str(outer_avg_nodes_explored).rjust(5)}, rollouts {str(outer_avg_trials_performed).rjust(5)}, \n                      backprops {str(outer_avg_backprop_iter).rjust(5)}, rolloutExpansions {str(outer_avg_rollout_expansions).rjust(5)}, biasedRolloutExpansions {str(outer_avg_biased_rollout_expansions).rjust(5)}')
