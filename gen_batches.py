import csv, os

# read universe
uni = []
with open("C:/Users/chunh/.workbuddy/skills/cn-stock-factor/config/universe.csv") as f:
    r = csv.reader(f)
    next(r)
    for row in r:
        if row:
            uni.append(row[0])
print("universe:", len(uni))

def wcode(t):
    return ("sh" + t) if t.startswith(("60", "68")) else ("sz" + t)

codes = [wcode(t) for t in uni]
print("total codes:", len(codes))

# 30-code batches
B = 30
batches = [codes[i:i+B] for i in range(0, len(codes), B)]
print("num batches (30):", len(batches))
for i, b in enumerate(batches):
    s = ",".join(b)
    # save to file for reference
    with open(f"C:/Users/chunh/ZCodeProject/stock_factor_project/_batch_{i}.txt", "w") as f:
        f.write(s)
    print(f"--- batch {i} ({len(b)} codes) ---")
    print(s)
    print()
