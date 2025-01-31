// cppimport

/*
<%
import sys
compiler_args = {
    'linux': ['-std=c++20', '-ggdb3'],
    'win32': ['/std:c++17']
}
cfg['extra_compile_args'] = compiler_args.get(sys.platform, [])
setup_pybind11(cfg)
%>
*/

#define PYBIND11_DETAILED_ERROR_MESSAGES
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/chrono.h>
#include <vector>
#include <tuple>
#include <stdexcept>
#include <cmath>
#include <chrono>
#include <unordered_set>
#include <pybind11/embed.h>

#define FMTARG(x) py::arg(#x) = (x)

using namespace pybind11::literals;
namespace py = pybind11;


[[noreturn]] static void raiseAssertionError(std::string&& msg) {
    PyErr_SetString(PyExc_AssertionError, msg.c_str());
    throw py::error_already_set();
}

static double estimateRuntime(
    int n,
    int capacity,
    int maxGroupSize)
{
    double maxGrSq = std::sqrt(maxGroupSize);
    double estTime = n * capacity * std::sqrt(maxGroupSize) * 0.00000022;
    if (maxGroupSize == n) estTime = n * capacity * 0.00000022;
    return estTime;
}

/**
 *  Solves knapsack where you need to knapsack a bunch of things, but must pick at most one thing from each group of things
 *  #Example
 *  items = ['a', 'b', 'c']
 *  values = [60, 100, 120]
 *  weights = [10, 20, 30]
 *  groups = [0, 1, 1]
 *  capacity = 50
 *  maxValue, itemList = solve_multiple_choice_knapsack(items, capacity, weights, values, groups)
 *
 *  Extensively optimized by Travis Drake / EklipZgit by an order of magnitude, original implementation cloned from: https://gist.github.com/USM-F/1287f512de4ffb2fb852e98be1ac271d
 * \param items list of the items to be maximized in the knapsack. Can be a list of literally anything, just used to return the chosen items back as output.
 * \param capacity the capacity of weights that can be taken.
 * \param weights list of the items weights, in same order as items.
 * \param values list of the items values, in same order as items.
 * \param groups list of the items group id number, in same order as items. MUST start with 0, and cannot skip group numbers.
 * \return returns a tuple of the maximum value that was found to fit in the knapsack, along with the list of optimal items that reached that max value.
 */
std::tuple<int, std::vector<py::object>> solve_multiple_choice_knapsack(
    const std::vector<py::object>& items,
    int capacity,
    const std::vector<int>& weights,
    const std::vector<int>& values,
    const std::vector<int>& groups,
    bool noLog = true,
    double longRuntimeThreshold = 0.005)
{
    py::object logbook_info = py::module_::import("logbook").attr("info");

    using namespace std::chrono;
    auto timeStart = high_resolution_clock::now();
    
    if (groups.empty() || groups[0] != 0) {
        throw std::invalid_argument("Groups must start with 0 and increment by one for each new group.");
    }
    
    std::vector<std::pair<int, int>> groupStartEnds;
    int lastGroup = -1, lastGroupIndex = 0, maxGroupSize = 0, curGroupSize = 0;
    for (size_t i = 0; i < groups.size(); ++i) {
        int group = groups[i];
        if (group > lastGroup) {
            if (curGroupSize > maxGroupSize) maxGroupSize = curGroupSize;
            if (lastGroup > -1) groupStartEnds.emplace_back(lastGroupIndex, i);
            if (group > lastGroup + 1) throw std::invalid_argument("Groups must be contiguous.");
            lastGroupIndex = i;
            lastGroup = group;
            curGroupSize = 0;
        }
        curGroupSize++;
    }
    groupStartEnds.emplace_back(lastGroupIndex, groups.size());
    if (curGroupSize > maxGroupSize) maxGroupSize = curGroupSize;
    
    int n = values.size();
    std::vector<std::vector<int>> K(n + 1, std::vector<int>(capacity + 1, 0));

    double estTime = estimateRuntime(n, capacity, maxGroupSize);
    
    if (estTime > longRuntimeThreshold) {
        throw std::runtime_error("Knapsack potential long run detected");
    }

    if (!noLog) {
        logbook_info("estimated knapsack time: {estTime:.3f} (n {n} * capacity {capacity} * math.sqrt(maxGroupSize {maxGroupSize}))"_s.format(**py::dict(FMTARG(estTime), FMTARG(n), FMTARG(maxGroupSize), FMTARG(capacity))));
    }

    for (int curCapacity = 1; curCapacity < capacity + 1; ++curCapacity) {
        for (int i = 1; i < n+1; ++i) {
            /// K is zero-initialized.
            // if (i == 0 || curCapacity == 0) {
            //     K[i][curCapacity] = 0;
            // } else
            if (weights[i - 1] <= curCapacity) {
                int sub_max = 0;
                int prev_group = groups[i-1] - 1;
                int subKRow = curCapacity - weights[i - 1];
                if (prev_group >= 0) {
                    auto [prevGroupStart, prevGroupEnd] = groupStartEnds[prev_group];
                    for (int j = prevGroupStart + 1; j < prevGroupEnd + 1; ++j) {
                        if (K[j][subKRow] > sub_max) {
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

    int res = K[n][capacity];

    if (!noLog) {
        auto timeTaken = high_resolution_clock::now() - timeStart;
        logbook_info("Value Found {res} in {timeTaken}"_s.format(**py::dict("res"_a=res, "timeTaken"_a=timeTaken)));
    }

    std::vector<py::object> includedItems;
    std::vector<int> includedGroups;
    int w = capacity, lastTakenGroup = -1;
    for (int i = n; i > 0 && res > 0; --i) {
        if (w < 0) {
            auto errmsg = "w < 0 in knapsack items determiner?? res {res} i {i} w {w}"_s.format(**py::dict(FMTARG(res), FMTARG(i), FMTARG(w))).cast<std::string>();
            raiseAssertionError(std::move(errmsg));
        }

        // either the result comes from the
        // top (K[i-1][w]) or from (val[i-1]
        // + K[i-1] [w-wt[i-1]]) as in Knapsack
        // table. If it comes from the latter
        // one/ it means the item is included.
        // THIS IS WHY VALUE MUST BE INTS
        if (res == K[i - 1][w]) continue;

        int group = groups[i - 1];
        if (group == lastTakenGroup) continue;
        includedGroups.push_back(group);
        lastTakenGroup = group;
        includedItems.push_back(items[i - 1]);
        if (!noLog) {
            logbook_info("item at index {i-1} with value {values[i-1]} and weight {weights[i-1]} was included... adding it to output. (Res {res})"_s.format(**py::dict("values"_a=py::dict(FMTARG(i-1)), "weights"_a=py::dict(FMTARG(i-1)), FMTARG(res), FMTARG(i-1))));
        }

        // Since this weight is included
        // its value is deducted
        res -= values[i - 1];
        w -= weights[i - 1];
    }

    if (!noLog) {
        auto uniqueGroupsIncluded = std::unordered_set<int>(includedGroups.begin(), includedGroups.end()); 
        if (uniqueGroupsIncluded.size() != includedGroups.size()) {
            raiseAssertionError("Yo, the multiple choice knapsacker failed to be distinct by groups");
        }
        auto msg = 
            "multiple choice knapsack completed on {n} items for capacity {capacity} finding value {K[n][capacity]} in Duration {timeDiff}"_s.format(
                **py::dict(
                    FMTARG(n),
                    FMTARG(capacity),
                    "timeDiff"_a = high_resolution_clock::now() - timeStart,
                    "K"_a = py::dict(
                        "n"_a = py::dict (
                            "capacity"_a = K[n][capacity]
                        )
                    )
                )
            );
        logbook_info(std::move(msg.cast<std::string>()));
    }

    return {K[n][capacity], includedItems};
}

PYBIND11_MODULE(KnapsackUtilsCpp, m) {
    m.doc() = "C++ impl of multiple_choice_knapsack"; // optional module docstring

    m.def("solve_multiple_choice_knapsack", &solve_multiple_choice_knapsack, 
        "items"_a, "capacity"_a, "weights"_a,
        "values"_a, "groups"_a, "noLog"_a, 
        "longRuntimeThreshold"_a
    );
}