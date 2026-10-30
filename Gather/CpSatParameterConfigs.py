"""
CP-SAT parameter configurations for performance testing.

These configurations can be used with _solve_tile_plan_option_arrays_with_cp_sat
to test different solver parameters and their impact on performance vs optimality.

To benchmark these configurations, see BenchmarkTools/benchmark_cp_sat_configs.py
Run with: python -m unittest BenchmarkTools.benchmark_cp_sat_configs.CpSatConfigBenchmark.test_benchmark_all_cp_sat_configs

Official OR-Tools CP-SAT Parameters (from ortools/sat/sat_parameters.proto):

TIME LIMITS:
- max_time_in_seconds (double, default=inf): Maximum time allowed in seconds to solve a problem.
  The counter starts at the beginning of the Solve() call. Can produce suboptimal solutions
  if the time limit is hit before finding the optimal solution.

WORKERS / PARALLELISM:
- num_workers (int32, default=0): Specify the number of parallel workers (threads) to use during search.
  A value of 0 means the solver will try to use all cores on the machine. A number of 1 means no parallelism.
  (Note: num_search_workers is deprecated but still supported; prefer num_workers)

PRESOLVE:
- cp_model_presolve (bool, default=true): Whether we presolve the cp_model before solving it.
  False can sometimes find better solutions but slower; True is usually faster and still optimal.
- cp_model_probing_level (int32, default=2): How much effort we spend on probing. 0 disables it completely.
- cp_model_use_sat_presolve (bool, default=true): Whether we also use the sat presolve when cp_model_presolve is true.

LINEARIZATION / LP RELAXATION:
- linearization_level (int32, default=1): A non-negative level indicating the type of constraints
  we consider in the LP relaxation.
  - Level 0: No LP relaxation is used.
  - Level 1: Only the linear constraint and full encoding are added.
  - Level 2: We also add all the Boolean constraints.
  Higher levels can be faster but might miss some optimizations.

SEARCH BRANCHING (enum SearchBranching):
- AUTOMATIC_SEARCH (0): Try to fix all literals using the underlying SAT solver's heuristics,
  then generate and fix literals until integer variables are fixed.
- FIXED_SEARCH (1): All decisions are made using a fixed order as specified in the API or
  in the CpModelProto search_strategy field.
- PORTFOLIO_SEARCH (2): Simple portfolio search used by LNS workers.
- LP_SEARCH (3): The solver will use heuristics from the LP relaxation (exploits reduced costs).
- PSEUDO_COST_SEARCH (4): Uses pseudo costs for branching (computed using historical change
  in objective bounds when decisions are taken). Works whether we use an LP or not.
- PORTFOLIO_WITH_QUICK_RESTART_SEARCH (5): Quickly tries a lot of randomized heuristics with
  a low conflict limit. Usually provides a good first solution.
- HINT_SEARCH (6): Follows the solution_hint field of the CpModelProto rather than using
  the information provided in the search_strategy.
- PARTIAL_FIXED_SEARCH (7): Like FIXED_SEARCH, but differs in how variables not listed in
  the fixed search heuristics are branched on. Starts with the specified fixed search strategy,
  but completes it using the default automatic search.
- RANDOMIZED_SEARCH (8): Randomized search. Used to increase entropy in the search.

Optimality Notes:
- max_time_in_seconds: Can produce suboptimal solutions if time limit is hit before finding optimal
- cp_model_presolve: False can sometimes find better solutions but slower; True is usually faster and still optimal
- linearization_level: Higher levels can be faster but might miss some optimizations
- search_branching: Different strategies can have different performance characteristics
"""

from dataclasses import dataclass
from typing import Any

from ortools.sat.python import cp_model


@dataclass(slots=True)
class CpSatConfig:
    """Configuration for CP-SAT solver parameters."""
    name: str
    params: dict[str, Any]
    description: str
    may_produce_suboptimal: bool = False


# Baseline - current default settings
BASELINE_CONFIG = CpSatConfig(
    name="baseline",
    params={},
    description="Current default OR-Tools CP-SAT settings (no custom parameters)",
    may_produce_suboptimal=False,
)

# Time limit configurations - these CAN produce suboptimal solutions if limit is hit
# Phased out - time limits produce suboptimal econ values
# TIME_LIMIT_5MS = CpSatConfig(
#     name="time_limit_5ms",
#     params={"max_time_in_seconds": 0.005},
#     description="5ms time limit - may produce suboptimal solutions if not converged",
#     may_produce_suboptimal=True,
# )
#
# TIME_LIMIT_10MS = CpSatConfig(
#     name="time_limit_10ms",
#     params={"max_time_in_seconds": 0.010},
#     description="10ms time limit - may produce suboptimal solutions if not converged",
#     may_produce_suboptimal=True,
# )
#
# TIME_LIMIT_20MS = CpSatConfig(
#     name="time_limit_20ms",
#     params={"max_time_in_seconds": 0.020},
#     description="20ms time limit - may produce suboptimal solutions if not converged",
#     may_produce_suboptimal=True,
# )

# Parallelism configurations
# Note: num_workers is the preferred parameter name (num_search_workers is deprecated but still supported)
SINGLE_WORKER = CpSatConfig(
    name="1_wrker",
    params={"num_workers": 1},
    description="Single search worker - reduces parallelism overhead",
    may_produce_suboptimal=False,
)

TWO_WORKERS = CpSatConfig(
    name="two_workers",
    params={"num_workers": 2},
    description="Two search workers - balance between parallelism and overhead",
    may_produce_suboptimal=False,
)

# Presolve configurations
NO_PRESOLVE = CpSatConfig(
    name="no_presolve",
    params={"cp_model_presolve": False},
    description="Disable presolve - may find better solutions but slower",
    may_produce_suboptimal=False,  # Still optimal, just slower
)

AGGRESSIVE_PRESOLVE = CpSatConfig(
    name="aggressive_presolve",
    params={"cp_model_presolve": True},
    description="Aggressive presolve enabled",
    may_produce_suboptimal=False,
)

# Linearization configurations
# Level 0: No LP relaxation
# Level 1: Only linear constraint and full encoding added
# Level 2: All Boolean constraints also added
LINEARIZATION_NONE = CpSatConfig(
    name="linearization_none",
    params={"linearization_level": 0},
    description="No LP relaxation - no linear constraints in relaxation",
    may_produce_suboptimal=False,
)

LINEARIZATION_PARTIAL = CpSatConfig(
    name="linearization_partial",
    params={"linearization_level": 1},
    description="Partial linearization - only linear constraint and full encoding added",
    may_produce_suboptimal=False,
)

LINEARIZATION_FULL = CpSatConfig(
    name="linearization_full",
    params={"linearization_level": 2},
    description="Full linearization - all Boolean constraints also added to LP",
    may_produce_suboptimal=False,
)

# Search branching configurations
BRANCHING_AUTOMATIC = CpSatConfig(
    name="branching_automatic",
    params={"search_branching": cp_model.AUTOMATIC_SEARCH},
    description="Automatic branching strategy",
    may_produce_suboptimal=False,
)

BRANCHING_PORTFOLIO = CpSatConfig(
    name="branching_portfolio",
    params={"search_branching": cp_model.PORTFOLIO_SEARCH},
    description="Portfolio search - tries multiple strategies in parallel",
    may_produce_suboptimal=False,
)

BRANCHING_FIXED = CpSatConfig(
    name="branching_fixed",
    params={"search_branching": cp_model.FIXED_SEARCH},
    description="Fixed search strategy",
    may_produce_suboptimal=False,
)

# Combined configurations for practical testing
# Phased out - produces suboptimal econ values
# FAST_BUT_MAY_SUBOPTIMAL = CpSatConfig(
#     name="fast_may_suboptimal",
#     params={
#         "max_time_in_seconds": 0.010,
#         "num_workers": 1,
#         "linearization_level": 0,  # No LP relaxation for speed
#     },
#     description="Fast config with 10ms limit, single worker, no LP relaxation - may be suboptimal",
#     may_produce_suboptimal=True,
# )

# Single worker variants - combining single_worker with other optimizations
SINGLE_WORKER_LINEARIZATION_NONE = CpSatConfig(
    name="1_wrker_linearization_none",
    params={
        "num_workers": 1,
        "linearization_level": 0,
    },
    description="Single worker with no LP relaxation",
    may_produce_suboptimal=False,
)

SINGLE_WORKER_LINEARIZATION_FULL = CpSatConfig(
    name="1_wrker_linearization_full",
    params={
        "num_workers": 1,
        "linearization_level": 2,
    },
    description="Single worker with full LP relaxation",
    may_produce_suboptimal=False,
)

SINGLE_WORKER_NO_PRESOLVE = CpSatConfig(
    name="1_wrker_no_presolve",
    params={
        "num_workers": 1,
        "cp_model_presolve": False,
    },
    description="Single worker with presolve disabled - CAN CAUSE INFINITE HANGS",
    may_produce_suboptimal=False,
)

SINGLE_WORKER_BRANCHING_PORTFOLIO = CpSatConfig(
    name="1_wrker_branching_portfolio",
    params={
        "num_workers": 1,
        "search_branching": cp_model.PORTFOLIO_SEARCH,
    },
    description="Single worker with portfolio search branching",
    may_produce_suboptimal=False,
)

SINGLE_WORKER_BRANCHING_AUTOMATIC = CpSatConfig(
    name="1_wrker_branching_automatic",
    params={
        "num_workers": 1,
        "search_branching": cp_model.AUTOMATIC_SEARCH,
    },
    description="Single worker with automatic branching",
    may_produce_suboptimal=False,
)

SINGLE_WORKER_AGGRESSIVE_PRESOLVE = CpSatConfig(
    name="1_wrker_aggressive_presolve",
    params={
        "num_workers": 1,
        "cp_model_presolve": True,
    },
    description="Single worker with aggressive presolve",
    may_produce_suboptimal=False,
)

BALANCED_PERFORMANCE = CpSatConfig(
    name="balanced_performance",
    params={
        "num_workers": 2,
        "linearization_level": 1,
        "search_branching": cp_model.PORTFOLIO_SEARCH,
    },
    description="Balanced config - should remain optimal with better performance",
    may_produce_suboptimal=False,
)

AGGRESSIVE_SPEED = CpSatConfig(
    name="aggressive_speed",
    params={
        "num_workers": 1,
        # "num_search_workers": 2,  # Explicitly use deprecated name (original default)
        "linearization_level": 2,  # Original default: all Boolean constraints added to LP
        "cp_model_presolve": True,
        "search_branching": cp_model.AUTOMATIC_SEARCH,
    },
    description="Aggressive speed optimization - original defaults (linearization_level=2, num_search_workers=1)",
    may_produce_suboptimal=False,
)

# All configurations for iteration
ALL_CONFIGS: list[CpSatConfig] = [
    LINEARIZATION_FULL,
    LINEARIZATION_PARTIAL,
    LINEARIZATION_NONE,
    BASELINE_CONFIG,
    AGGRESSIVE_SPEED,
    BRANCHING_AUTOMATIC,
    BRANCHING_PORTFOLIO,
    SINGLE_WORKER_BRANCHING_PORTFOLIO,
    SINGLE_WORKER_BRANCHING_AUTOMATIC,
    SINGLE_WORKER_AGGRESSIVE_PRESOLVE,
    BRANCHING_FIXED,
    BALANCED_PERFORMANCE,
    SINGLE_WORKER_LINEARIZATION_FULL,
    SINGLE_WORKER_NO_PRESOLVE,
    SINGLE_WORKER,
    TWO_WORKERS,
    NO_PRESOLVE,
    AGGRESSIVE_PRESOLVE,
    # Single worker variants
    # SINGLE_WORKER_LINEARIZATION_NONE, # hangs
]
