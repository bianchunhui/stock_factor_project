"""Clean Eastmoney-exported HSI 93 constituents (Table.xlsx) into project standard CSV.

Output: data/hsi_constituents_20260709.csv
Columns: ticker(5-digit), name, industry, total_mv(yuan), pe_ttm, pb, total_shares, float_shares
"""
import pandas as pd
import re

SRC = r"C:\Users\chunh\Downloads\Table.xlsx"
OUT = "data/hsi_constituents_20260709.csv"

df = pd.read_excel(SRC)
# column headers may have leading/trailing spaces
for c in df.columns:
    nc = str(c).strip()
    if nc != c:
        df.rename(columns={c: nc}, inplace=True)
print(f"Loaded: {df.shape[0]} rows, {df.shape[1]} cols")
print("Columns:", list(df.columns))

# --- ticker: zero-pad to 5 digits (HK convention) ---
df["ticker"] = df["代码"].astype(str).str.strip().str.zfill(5)

# --- name / industry ---
df["name"] = df["名称"].astype(str).str.strip()
df["industry"] = df["所属行业"].astype(str).str.strip()

# --- numeric parsers ---
def parse_cn_num(s):
    """Parse Chinese magnitude number like '2.07万亿' / '834.0亿' / '1511亿' -> yuan (float)."""
    if pd.isna(s):
        return None
    s = str(s).strip()
    if s in ("", "-", "nan", "None"):
        return None
    # extract leading numeric part
    m = re.match(r"^(-?[\d.]+)", s)
    if not m:
        try:
            return float(s)
        except Exception:
            return None
    val = float(m.group(1))
    # unit scaling (check multi-char first)
    if "万亿" in s:
        val *= 1e12
    elif "亿" in s:
        val *= 1e8
    elif "万" in s:
        val *= 1e4
    return val

df["total_mv"] = df["总市值"].apply(parse_cn_num)
df["float_mv"] = df["流通市值"].apply(parse_cn_num)
df["total_shares"] = df["总股本"].apply(parse_cn_num)
df["float_shares"] = df["流通股本"].apply(parse_cn_num)

def parse_float(s):
    if pd.isna(s):
        return None
    s = str(s).strip()
    if s in ("", "-", "nan", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None

df["pe_ttm"] = df["市盈率(动)"].apply(parse_float)
df["pb"] = df["市净率"].apply(parse_float)

# --- assemble output ---
out = df[["ticker", "name", "industry", "total_mv", "float_mv",
          "pe_ttm", "pb", "total_shares", "float_shares"]].copy()
out = out.sort_values("ticker").reset_index(drop=True)

# sanity: check duplicate tickers
assert out["ticker"].is_unique, "Duplicate tickers found!"

out.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"Saved -> {OUT} ({len(out)} rows)")
print()
print(out.to_string(index=False))
print()
print("MV unit: yuan | shares unit: shares (not yet scaled to actual count)")
print("Note: 总股本/流通股本 from EM are in '股' already (e.g. 192.1亿 -> parsed to 1.921e10)")
