import csv, os

CFG = r"C:/Users/chunh/.workbuddy/skills/cn-stock-factor/config/universe.csv"
OUT = r"C:/Users/chunh/ZCodeProject/stock_factor_project"

univ = []
with open(CFG, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        univ.append(r["ticker"].strip())

def w(t):
    return ("sh" + t) if t.startswith(("60", "68")) else ("sz" + t)

def batches(arr, n):
    return [arr[i:i + n] for i in range(0, len(arr), n)]

def write(name, seq):
    with open(os.path.join(OUT, name), "w") as f:
        for b in seq:
            f.write(",".join(w(t) for t in b) + "\n")

# income: num=5, 10/call (safe vs westock row-cap) -> 30 calls
write("npx_inc.txt", batches(univ, 10))
# balance: num=1, 50/call -> 6 calls
write("npx_bal.txt", batches(univ, 50))
# fund: 50/call -> 6 calls
write("npx_fund.txt", batches(univ, 50))

print("universe:", len(univ))
print("inc batches:", len(batches(univ, 10)))
print("bal batches:", len(batches(univ, 50)))
print("fund batches:", len(batches(univ, 50)))
