import json, os

RAW = "C:/Users/chunh/.workbuddy/skills/cn-stock-factor/data/raw"

def load(name):
    with open(os.path.join(RAW, name), encoding="utf-8") as f:
        return json.load(f)

# finance income
fi = load("fin_inc_0.json")
print("=== fin_inc_0 ===")
print("top keys:", list(fi.keys()))
dd = fi.get("data", {}).get("data", None)
print("data.data type:", type(dd).__name__, "len:", len(dd) if hasattr(dd,'__len__') else 'n/a')
if isinstance(dd, dict):
    print("symbols:", list(dd.keys())[:5], "... count:", len(dd))
    sample_sym = list(dd.keys())[0]
    print("sample sym:", sample_sym, "rows type:", type(dd[sample_sym]).__name__)
    if isinstance(dd[sample_sym], list) and dd[sample_sym]:
        print("sample fields:", list(dd[sample_sym][0].keys())[:15])
elif isinstance(dd, list):
    print("first item keys:", list(dd[0].keys()) if dd else 'empty')

# finance balance
fb = load("fin_bal_0.json")
print("\n=== fin_bal_0 ===")
dd2 = fb.get("data", {}).get("data", None)
print("data.data type:", type(dd2).__name__, "len:", len(dd2) if hasattr(dd2,'__len__') else 'n/a')
if isinstance(dd2, dict):
    print("symbols:", list(dd2.keys())[:5], "... count:", len(dd2))
    sample_sym = list(dd2.keys())[0]
    if isinstance(dd2[sample_sym], list) and dd2[sample_sym]:
        print("sample fields:", list(dd2[sample_sym][0].keys())[:15])
elif isinstance(dd2, list):
    print("first item keys:", list(dd2[0].keys()) if dd2 else 'empty')

# benchmark
bm = load("benchmark_0.json")
print("\n=== benchmark_0 ===")
print("top keys:", list(bm.keys()))
def extract_nodes(d):
    nodes=None
    if isinstance(d.get("data"), dict):
        if "nodes" in d["data"]:
            nodes=d["data"]["nodes"]
        elif "data" in d["data"] and isinstance(d["data"]["data"], list):
            nodes=d["data"]["data"]
    if isinstance(d.get("data"), list):
        nodes=d["data"]
    return nodes
nodes = extract_nodes(bm)
print("nodes type:", type(nodes).__name__, "len:", len(nodes) if hasattr(nodes,'__len__') else 'n/a')
if nodes and isinstance(nodes, list):
    print("first node:", nodes[0])
    print("last node:", nodes[-1])

# quote
q = load("quote_0.json")
print("\n=== quote_0 ===")
print("top keys:", list(q.keys()))
d2 = q.get("data", {})
if isinstance(d2, dict):
    print("data keys count:", len(d2))
    ks = list(d2.keys())
    print("first 5 symbols:", ks[:5])
    print("last 5 symbols:", ks[-5:])
    if ks:
        print("sample fields:", list(d2[ks[0]].keys())[:20])
