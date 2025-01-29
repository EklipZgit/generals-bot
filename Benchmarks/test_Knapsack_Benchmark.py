import KnapsackUtilsCython
import time
import KnapsackUtilsPy
import random
import timeit

def get_args(n):
    random.seed(0)
    items = list(range(n))
    values = [random.randrange(200) for _ in range(len(items))]
    weights = [random.randrange(10, 40) for _ in range(len(items))]
    groups = sorted([random.randrange(50) for _ in range(len(items))])
    for i in range(len(groups)):
        if i+1 < len(groups) and groups[i+1] - groups[i] > 1:
            groups[i+1] = groups[i] + 1
    group0 = groups[0]
    for i in range(len(groups)):
        groups[i] -= group0
    capacity = sum(weights) // 3
    return dict(items=items, values=values, weights=weights, groups=groups, capacity=capacity, longRuntimeThreshold=100)

args = [get_args(i) for i in [2, 3, 10, 50, 100, 500, 1500, 2000]]

def main():
    for a in args:
        code = f'solve_multiple_choice_knapsack(**{a})' 
        cythontime = timeit.timeit(code, setup="from KnapsackUtilsCython import solve_multiple_choice_knapsack", number=10)
        cppimporttime = timeit.timeit(code, setup="from KnapsackUtilsPy import solve_multiple_choice_knapsack", number=10)
        print(f"{len(a['items'])=}")
        print(f"{cythontime=} {cppimporttime=} {cppimporttime/cythontime=}")


if __name__ == '__main__':
    main()
