import sys
from time import perf_counter

n, repeats, x = map(int, sys.argv[1:])
start = perf_counter()
for r in range(repeats):
    for i in range(n):
        x = x * 48271 % 2147483647
elapsed = perf_counter() - start
print(x)
print(elapsed)
