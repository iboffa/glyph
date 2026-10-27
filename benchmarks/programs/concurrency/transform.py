"""CPU-parallel reference: persistent worker processes, serialized integer chunks."""
from concurrent.futures import ProcessPoolExecutor
import sys
from time import perf_counter


def transform(x):
    value = x + 1
    for _ in range(64):
        value = value * 48271 % 2147483647
    return value


def main():
    n, repeats, workers = map(int, sys.argv[1:])
    data = list(range(n))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        start = perf_counter()
        result = list(pool.map(transform, data, chunksize=256))
        first = perf_counter() - start
        start = perf_counter()
        for r in range(repeats):
            data[0] = r
            result = list(pool.map(transform, data, chunksize=256))
        elapsed = perf_counter() - start
    print(sum(result))
    print(first)
    print(elapsed)


if __name__ == '__main__':
    main()
