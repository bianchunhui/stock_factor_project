import csv, os

CFG = r"C:/Users/chunh/.workbuddy/skills/cn-stock-factor/config"

univ = []
with open(os.path.join(CFG, "universe.csv"), newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        univ.append(row["ticker"].strip())

def wcode(t):
    return ("sh" + t) if t.startswith(("60", "68")) else ("sz" + t)

def batches(arr, n):
    return [arr[i:i+n] for i in range(0, len(arr), n)]

def emit(label, seq):
    print(f"\n#### {label}")
    for i, b in enumerate(seq):
        print(f"-- {label}_{i} ({len(b)} codes):")
        print(",".join(wcode(t) for t in b))

emit("INCOME_num8_30", batches(univ, 30))      # 10 calls
emit("BALANCE_num1_50", batches(univ, 50))     # 6 calls
emit("QUOTE_150", batches(univ, 150))          # 2 calls
emit("FUND_20", batches(univ, 20))             # 15 calls
