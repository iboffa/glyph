import sys
from time import perf_counter

n, repeats, seed = map(int, sys.argv[1:])
a = [(i * 17 + seed) % 1000 for i in range(n)]
checksum = 0
start = perf_counter()
for r in range(repeats):
    a[r % n] = (a[r % n] + r) % 1000
    checksum += sum(a)
elapsed = perf_counter() - start
print(checksum)
print(elapsed)
