import json, os
from collections import Counter

RAW = "C:/Users/chunh/.workbuddy/skills/cn-stock-factor/data/raw"
TOOLRES = "C:/Users/chunh/.workbuddy/projects/c-Users-chunh-ZCodeProject-stock_factor_project/52c18d3e-bfdf-480c-843d-a7b74c13f1d8/tool-results"

uni = []
with open("C:/Users/chunh/.workbuddy/skills/cn-stock-factor/config/universe.csv") as f:
    next(f)
    for line in f:
        line = line.strip()
        if not line:
            continue
        uni.append(line.split(",")[0])
print("universe count:", len(uni))

def kline_symbols(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    syms = []
    arr = d.get("data", {}).get("data", [])
    if isinstance(arr, dict):
        arr = [arr]
    for row in arr:
        if isinstance(row, dict) and "symbol" in row:
            syms.append(row["symbol"])
    return syms

sources = {
    "kline_0 (raw)": os.path.join(RAW, "kline_0.json"),
    "K1 (a3df40)": os.path.join(TOOLRES, "mcp-connector-proxy-westock-mcp_data_kline-1783786274043-a3df40.txt"),
    "K2 (2d2893)": os.path.join(TOOLRES, "mcp-connector-proxy-westock-mcp_data_kline-1783786274655-2d2893.txt"),
    "K3 (5dd179)": os.path.join(TOOLRES, "mcp-connector-proxy-westock-mcp_data_kline-1783786276373-5dd179.txt"),
    "K4 (cf880d)": os.path.join(TOOLRES, "mcp-connector-proxy-westock-mcp_data_kline-1783786274924-cf880d.txt"),
    "K5 (52ac11)": os.path.join(TOOLRES, "mcp-connector-proxy-westock-mcp_data_kline-1783786273690-52ac11.txt"),
}

all_syms = []
for name, path in sources.items():
    if os.path.exists(path):
        s = kline_symbols(path)
        all_syms += s
        print(f"{name}: {len(s)} symbols  first={s[:3]} last={s[-3:]}")
    else:
        print(f"{name}: MISSING")

print("union count:", len(set(all_syms)))
missing = set(("sh" + t if t.startswith(("60", "68")) else "sz" + t) for t in uni) - set(all_syms)
print("missing vs universe:", sorted(missing)[:20], "total missing:", len(missing))
c = Counter(all_syms)
dups = [k for k, v in c.items() if v > 1]
print("duplicates:", dups[:20], "total dups:", len(dups))
