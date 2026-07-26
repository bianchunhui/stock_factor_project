"""验证 FACTOR_CATALOG 与 ALL_FACTORS 的一致性。"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\chunh\ZCodeProject\stock_factor_project")

from config.universe import FACTOR_CATALOG
from factors import ALL_FACTORS, FACTOR_CLASS_MAP

print("=== FACTOR_CATALOG ===")
print(f"  条目数: {len(FACTOR_CATALOG)}")
for name, (cat, direction, need_pit, desc) in FACTOR_CATALOG.items():
    print(f"  {name:12s} cat={cat:12s} dir={direction:+d} pit={need_pit}  {desc}")

print(f"\n=== ALL_FACTORS ===")
print(f"  因子类数: {len(ALL_FACTORS)}")
for cls in ALL_FACTORS:
    f = cls() if isinstance(cls, type) else cls
    print(f"  {f.name:12s} cat={f.category:12s} dir={f.direction:+d} pit={f.need_pit}")

print(f"\n=== 一致性检查 ===")
catalog_names = set(FACTOR_CATALOG.keys())
factor_names = set(FACTOR_CLASS_MAP.keys())

only_catalog = catalog_names - factor_names
only_factors = factor_names - catalog_names

if only_catalog:
    print(f"  [BAD] 在 CATALOG 但不在 ALL_FACTORS: {only_catalog}")
else:
    print("  [OK] CATALOG 中的因子名全部存在于 ALL_FACTORS")

if only_factors:
    print(f"  [BAD] 在 ALL_FACTORS 但不在 CATALOG: {only_factors}")
else:
    print("  [OK] ALL_FACTORS 中的因子名全部存在于 CATALOG")

# 逐个检查 direction / need_pit / category 是否一致
print("\n=== 属性一致性 ===")
all_ok = True
for cls in ALL_FACTORS:
    f = cls() if isinstance(cls, type) else cls
    if f.name not in FACTOR_CATALOG:
        continue
    cat, direction, need_pit, desc = FACTOR_CATALOG[f.name]
    mismatches = []
    if cat != f.category:
        mismatches.append(f"category: catalog={cat} vs code={f.category}")
    if direction != f.direction:
        mismatches.append(f"direction: catalog={direction} vs code={f.direction}")
    if need_pit != f.need_pit:
        mismatches.append(f"need_pit: catalog={need_pit} vs code={f.need_pit}")
    if mismatches:
        print(f"  [BAD] {f.name}: {'; '.join(mismatches)}")
        all_ok = False

if all_ok:
    print("  [OK] 所有因子的 category/direction/need_pit 属性一致")

print(f"\n总计: CATALOG={len(FACTOR_CATALOG)}, ALL_FACTORS={len(ALL_FACTORS)}")
