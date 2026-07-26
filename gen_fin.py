import csv, os

uni = []
with open("C:/Users/chunh/.workbuddy/skills/cn-stock-factor/config/universe.csv") as f:
    r = csv.reader(f); next(r)
    for row in r:
        if row: uni.append(row[0])

def wcode(t):
    return ("sh"+t) if t.startswith(("60","68")) else ("sz"+t)
codes = [wcode(t) for t in uni]
print("total", len(codes))

# income 30-code batches (num=8), inc_0 already fetched = codes[0:30]
print("===== INCOME (num=8, 30/call) need inc_1..inc_9 =====")
inc = [codes[i:i+30] for i in range(0,300,30)]
for i,b in enumerate(inc):
    print(f"INC_{i}:{len(b)}:{','.join(b)}")

print()
print("===== BALANCE (num=1, 50/call) bal_0..bal_5 =====")
bal = [codes[i:i+50] for i in range(0,300,50)]
for i,b in enumerate(bal):
    print(f"BAL_{i}:{len(b)}:{','.join(b)}")
