import random
import timeit
import pandas
import tqdm
import time
import math
import collections

import multiprocessing


def brute(worker, data_list, processes=8):
    """
    Run multiprocess workers
    :param worker: worker function
    :param data_list: data to distribute between workers, one entry per worker
    :param processes: number of parallel processes
    :return: list of worker return values
    """
    pool = multiprocessing.Pool(processes=processes)
    result = pool.map(worker, data_list)
    pool.close()
    return result

def generate_group(len_groups, len_set_groups):
    ret = [0] * len_groups
    chosen = set(random.sample(range(1, len_groups), k=len_set_groups-1))
    for i in range(len_groups):
        if i in chosen:
            ret[i] = ret[i-1] + 1
        else:
            ret[i] = ret[i-1]
    return ret

def get_args(items_len, grpups_len=None):
    # random.seed(0)
    items = list(range(items_len))
    values = [random.randrange(200) for _ in range(len(items))]
    weights = [random.randrange(10, 40) for _ in range(len(items))]
    if grpups_len is not None:
        groups = generate_group(items_len, grpups_len)
    else:
        groups = sorted([random.randrange(len(items)//5+3) for _ in range(len(items))])
    for i in range(len(groups)):
        if i+1 < len(groups) and groups[i+1] - groups[i] > 1:
            groups[i+1] = groups[i] + 1
    group0 = groups[0]
    for i in range(len(groups)):
        groups[i] -= group0
    capacity = sum(weights) // 3
    return dict(items=items, values=values, weights=weights, groups=groups, capacity=capacity, longRuntimeThreshold=1000)

# args = [*[get_args(i) for i in [2, 3, 10, 50, 100, 500, 1500]], *[get_args(200, k) for k in [12]*20]]
args = [get_args(200, k) for k in [1,2,3,6,8,14,22,50,80, 130]*200]

def timeit_div(code, setup, max_time=2):
    
    locals = {}
    exec(setup, locals=locals, globals={})
    start = time.perf_counter()
    exec(code, locals=locals, globals={})
    end = time.perf_counter()

    iterations = math.ceil(max_time/(end-start)) - 1
    if iterations == 0:
        return end-start
    return (timeit.timeit(code, setup, number=iterations)+(end-start)) / (iterations + 1)

# def timeit_div(code, setup, max_time=2, number=1000):
    
#     globals = {}
#     exec(setup, globals=globals)
#     code = compile(code, "<dummy>", "exec")
#     while totaltime < max_time and i < number:
#         start = time.perf_counter()
#         exec(code, globals=globals)
#         end = time.perf_counter()
#         totaltime += end - start
#         i += 1
    
#     # return [totaltime / i, i]
#     return totaltime / i

def worker(args):
    a, setup, max_time = args
    code = f'solve_multiple_choice_knapsack(**{a})'
    return timeit_div(code, setup, max_time)

def get_group_len(groups, **args):
    return collections.Counter(groups).most_common(1)[0][1]

VERSIONS = {
    # "cython": "from KnapsackUtilsCython import solve_multiple_choice_knapsack",
    # "cpp_loop": "from KnapsackUtilsPy import solve_multiple_choice_knapsack",
    "cpp_full": "from KnapsackUtils import solve_multiple_choice_knapsack as solve_multiple_choice_knapsack",
    # "cpp_noinit": "from KnapsackUtils import solve_multiple_choice_knapsack as solve_multiple_choice_knapsack",
    # "pure_py": "from KnapsackUtilsPy import solve_multiple_choice_knapsack_purepy as solve_multiple_choice_knapsack",
}    

def compare_versions():
    args = [get_args(n, k) for n in [1,2,3,6,8,14,22,50,80,130,500,1300]*100 for k in filter(lambda x: x <= n, [1, 2, 4, 8, 12, 40, 80, 120, 450])]
    
    pandas.set_option('display.max_columns', None)
    pandas.set_option('display.max_rows', None)
    pandas.set_option('display.width', 1000)
    df = pandas.DataFrame(columns=[
        "len(items)",
        "group count",
        "max group len",
        *VERSIONS
    ])
    
    rows = {}
    for a in args:
        row = {"len(items)": len(a["items"]), "group count": len(set(a['groups']))}
        row["max group len"] = collections.Counter(a["groups"]).most_common(1)[0][1]
        rows[str(a)] = row
        
    for version, setup in VERSIONS.items():
        brute_args = [
            (a, setup, 0.4) for a in args
        ]
        for a, duration in zip(args, brute(worker, tqdm.tqdm(brute_args, desc=f"Running {version}"), processes=32)):
            rows[str(a)][version] = duration

        
    for row in rows.values():
        # print(f"{cythontime=} {cpptime=} {cpp2time=} {cpptime/cythontime=} {cythontime/cpp2time=} {purepytime/cpp2time=}")
        df = df._append(row, ignore_index=True)
        
    # df["pure_py/cpp_full"] = df["pure_py"] / df["cpp_full"]
    # df["cpp_loop/cpp_full"] = df["cpp_loop"] / df["cpp_full"]
    # df["cpp_full/cpp_noinit"] = df["cpp_full"] / df["cpp_noinit"]

    print(df)
    # print(df.sort_values(['cpp_full/cpp_noinit', 'len(items)', 'group count']))
    
def plot_runtime():
    cppfull = "cpp_full"
    df = pandas.DataFrame(columns=[
        "len(items)",
        "group count",
        "max group len",
        cppfull,
    ])
    
    brute_args = [
        (a, VERSIONS[cppfull], 0.2) for a in args
    ]
    
    for a, full_cpp_time in tqdm.tqdm(zip(args, brute(worker, brute_args, processes=32))):
        # code = f'solve_multiple_choice_knapsack(**{a})'
        row = {"len(items)": len(a["items"]), "group count": len(set(a['groups']))}
        row["max group len"] = collections.Counter(a["groups"]).most_common(1)[0][1]
        row[cppfull] = full_cpp_time
        df = df._append(row, ignore_index=True)
        
    pandas.set_option('display.max_columns', None)
    pandas.set_option('display.max_rows', None)
    pandas.set_option('display.width', 1000)
    print(df.sort_values([       "cpp_full", "len(items)",
        "group count",
        "max group len",
    ]))
    ax = df.plot(x="cpp_full", y="group count", kind="scatter", color='DarkBlue', label="group count")
    df.plot(x="cpp_full", y="max group len", kind="scatter", color='DarkGreen', ax=ax, label="max group len")
    ax.get_figure().savefig('fig.png')


def main():
    # plot_runtime()
    compare_versions()

# run as python -m Benchmarks.test_Knapsack_Benchmark
if __name__ == '__main__':
    main()
