import json, os, csv

RAW = r"C:/Users/chunh/.workbuddy/skills/cn-stock-factor/data/raw"
CFG = r"C:/Users/chunh/.workbuddy/skills/cn-stock-factor/config"

# universe
univ = []
with open(os.path.join(CFG, "universe.csv"), newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        row = {k.lstrip("\ufeff"): v for k, v in row.items()}
        univ.append(row["ticker"].strip())
univ_set = set(univ)
print(f"universe = {len(univ_set)} unique tickers")

def tk(sym):
    return sym[2:] if sym and len(sym) > 2 else sym

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def syms_kline(d):
    out = set()
    for it in d.get("data", {}).get("data", []):
        out.add(tk(it.get("symbol")))
    return out

def syms_dictdata(d):  # finance income/balance: d["data"]["data"] = {sym: [...]}
    out = set()
    dd = d.get("data", {}).get("data", {})
    if isinstance(dd, dict):
        for k in dd.keys():
            out.add(tk(k))
    return out

def syms_quote(d):  # d["data"] = {sym: {...}}
    out = set()
    dd = d.get("data", {})
    if isinstance(dd, dict):
        for k in dd.keys():
            out.add(tk(k))
    return out

def syms_fund(d):
    out = set()
    # fund flow shape varies; try common
    dd = d.get("data", {})
    if isinstance(dd, dict):
        for k in dd.keys():
            if k in ("date",): continue
            out.add(tk(k))
    # sometimes list
    lst = d.get("data", {}).get("data") or d.get("data")
    if isinstance(lst, list):
        for it in lst:
            if isinstance(it, dict) and "symbol" in it:
                out.add(tk(it["symbol"]))
    return out

print("\n=== KLINE ===")
ks = set()
for i in range(6):
    p = os.path.join(RAW, f"kline_{i}.json")
    if os.path.exists(p):
        ks |= syms_kline(load(p))
print(f"  union={len(ks)}; missing={len(univ_set-ks)}")

print("\n=== QUOTE ===")
qp = os.path.join(RAW, "quote_0.json")
if os.path.exists(qp):
    qs = syms_quote(load(qp))
    print(f"  union={len(qs)}; match_universe={len(qs & univ_set)}; missing={len(univ_set-qs)}; extra={len(qs-univ_set)}")
else:
    print("  quote_0.json MISSING")

print("\n=== FIN INCOME ===")
fi = set()
for i in range(10):
    p = os.path.join(RAW, f"fin_inc_{i}.json")
    if os.path.exists(p):
        s = syms_dictdata(load(p))
        print(f"  fin_inc_{i}: {len(s)} syms")
        fi |= s
print(f"  union={len(fi)}; missing={len(univ_set-fi)}")

print("\n=== FIN BALANCE ===")
fb = set()
for i in range(6):
    p = os.path.join(RAW, f"fin_bal_{i}.json")
    if os.path.exists(p):
        s = syms_dictdata(load(p))
        print(f"  fin_bal_{i}: {len(s)} syms")
        fb |= s
print(f"  union={len(fb)}; missing={len(univ_set-fb)}")

print("\n=== FUND FLOW ===")
fnd = set()
for i in range(10):
    p = os.path.join(RAW, f"fund_{i}.json")
    if os.path.exists(p):
        s = syms_fund(load(p))
        print(f"  fund_{i}: {len(s)} syms")
        fnd |= s
print(f"  union={len(fnd)}; missing={len(univ_set-fnd)}")

print("\n=== GAPS ===")
print("  kline missing:", sorted(univ_set-ks))
print("  quote missing:", sorted(univ_set-qs) if os.path.exists(qp) else "N/A")
print("  fin_inc missing:", sorted(univ_set-fi))
print("  fin_bal missing:", sorted(univ_set-fb))
print("  fund missing:", sorted(univ_set-fnd))
