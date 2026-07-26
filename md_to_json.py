"""md_to_json.py
把 westock-data npm 工具输出的 markdown 表 (raw_npx/{inc,bal,fund}_*.md)
转成 land.py 能直接解析的 JSON:
  fin_inc_{i}.json : {"data":{"data":{sym:[period dicts]}}}
  fin_bal_{i}.json : {"data":{"data":{sym:[period dicts]}}}
  fund_{i}.json    : {"data":{sym:{fields}}}
income 表没有 GrossProfitTTM -> 用 TotalOperatingRevenueTTM - TotalOperatingCostTTM 计算补上,
使 gpm 因子可用。
"""
import json, glob, os, re

SRC = r"C:/Users/chunh/ZCodeProject/stock_factor_project/raw_npx"
RAW = r"C:/Users/chunh/.workbuddy/skills/cn-stock-factor/data/raw"


def fnum(s):
    try:
        return float(s)
    except Exception:
        return None


def parse_md(path):
    """返回 (header列表, [数据dict行...])，跳过 [Batch] 行与分隔行。"""
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    table = [ln.rstrip("\n") for ln in lines if ln.lstrip().startswith("|")]
    if not table:
        return [], []
    header = [c.strip() for c in table[0].split("|")][1:-1]
    # 分隔行判定: 所有单元格都是 --- 或 :-- 之类
    data_start = 1
    if len(table) > 1:
        cells = [c.strip() for c in table[1].split("|")][1:-1]
        if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            data_start = 2
    for ln in table[data_start:]:
        vals = [c.strip() for c in ln.split("|")][1:-1]
        if len(vals) != len(header):
            continue
        rows.append(dict(zip(header, vals)))
    return header, rows


def convert_inc(path):
    _, rows = parse_md(path)
    out = {}
    for r in rows:
        sym = r.get("symbol") or r.get("SecuCode") or r.get("code")
        if not sym:
            continue
        end = r.get("EndDate") or r.get("_date") or r.get("date")
        rev = fnum(r.get("TotalOperatingRevenueTTM"))
        cost = fnum(r.get("TotalOperatingCostTTM"))
        gp = (rev - cost) if (rev is not None and cost is not None) else None
        p = {
            "EndDate": end,
            "OperatingRevenueTTM": r.get("OperatingRevenueTTM", ""),
            "NPParentCompanyOwnersTTM": r.get("NPParentCompanyOwnersTTM", ""),
            "OperatingProfitTTM": r.get("OperatingProfitTTM", ""),
            "TotalOperatingRevenueTTM": r.get("TotalOperatingRevenueTTM", ""),
            "BasicEPS": r.get("BasicEPS", ""),
        }
        if gp is not None:
            p["GrossProfitTTM"] = ("%.4f" % gp)
        out.setdefault(sym, []).append(p)
    return {"data": {"data": out}}


def convert_bal(path):
    _, rows = parse_md(path)
    out = {}
    for r in rows:
        sym = r.get("symbol") or r.get("SecuCode") or r.get("code")
        if not sym:
            continue
        end = r.get("EndDate") or r.get("_date") or r.get("date")
        p = {
            "EndDate": end,
            "TotalShareholderEquity": r.get("TotalShareholderEquity", ""),
            "TotalLiability": r.get("TotalLiability", ""),
            "TotalCurrentAssets": r.get("TotalCurrentAssets", ""),
            "TotalNonCurrentAssets": r.get("TotalNonCurrentAssets", ""),
        }
        out.setdefault(sym, []).append(p)
    return {"data": {"data": out}}


def convert_fund(path):
    _, rows = parse_md(path)
    out = {}
    for r in rows:
        sym = r.get("symbol") or r.get("SecuCode") or r.get("code")
        if not sym:
            continue
        out[sym] = {
            "MainNetFlow": r.get("MainNetFlow", ""),
            "MainNetFlow5D": r.get("MainNetFlow5D", ""),
            "MainNetFlow20D": r.get("MainNetFlow20D", ""),
            "RetailInFlow": r.get("RetailInFlow", ""),
            "RetailOutFlow": r.get("RetailOutFlow", ""),
            "BlockNetFlow": r.get("BlockNetFlow", ""),
            "JumboNetFlow": r.get("JumboNetFlow", ""),
            "MidNetFlow": r.get("MidNetFlow", ""),
            "SmallNetFlow": r.get("SmallNetFlow", ""),
            "MainInflowCircRate": r.get("MainInflowCircRate", ""),
        }
    return {"data": out}


def main():
    for prefix, conv in (("inc", convert_inc), ("bal", convert_bal), ("fund", convert_fund)):
        files = sorted(glob.glob(os.path.join(SRC, f"{prefix}_*.md")))
        total_sym = 0
        for i, fp in enumerate(files):
            obj = conv(fp)
            # 取该文件实际符号数
            if prefix == "fund":
                nsym = len(obj["data"])
            else:
                nsym = len(obj["data"]["data"])
            total_sym += nsym
            tgt = os.path.join(RAW, f"fin_{prefix}_{i}.json" if prefix != "fund" else f"fund_{i}.json")
            with open(tgt, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
        print(f"{prefix}: {len(files)} files, {total_sym} symbol-records -> raw/fin_{prefix}_*.json / fund_*.json")


if __name__ == "__main__":
    main()
