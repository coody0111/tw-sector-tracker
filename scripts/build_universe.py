"""
scripts/build_universe.py
一次性腳本：從現有 MoneyDJ 資料建立 stock_universe.csv。

輸出: data/stock_universe.csv
  stock_id | stock_name | meta_sector | sub_sector | note

建立後只需手動 review「note」欄有 ⚠️ 的股票，修正後 commit。
日後新股上市直接在 CSV 補一行即可，不需重跑 MoneyDJ。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from config import META_PRIORITY_LIST, get_meta_by_priority

SECTOR_CSV  = Path("data/sectors/industry_sectors.csv")
UNIVERSE_CSV = Path("data/stock_universe.csv")


def build() -> None:
    df = pd.read_csv(SECTOR_CSV, encoding="utf-8")

    # 每支股票的所有子族群（去重）
    stock_subs: dict[str, dict] = {}
    for _, row in df.iterrows():
        sid = str(row["stock_id"])
        if sid not in stock_subs:
            stock_subs[sid] = {"stock_name": row["stock_name"], "subs": set()}
        stock_subs[sid]["subs"].add(row["sector_name"])

    rows = []
    ambiguous = []

    for sid, info in stock_subs.items():
        subs = list(info["subs"])
        name = info["stock_name"]

        # 依優先序找 META
        meta = get_meta_by_priority(subs)

        # 找出命中的 sub_sector（在優先序中最先命中的那個）
        matched_sub = None
        if meta:
            for _meta, _subs in META_PRIORITY_LIST:
                if _meta == meta:
                    for s in _subs:
                        if s in subs:
                            matched_sub = s
                            break
                    break

        # 計算股票橫跨幾個 META（用來標記爭議股）
        matched_metas = set()
        for _meta, _subs in META_PRIORITY_LIST:
            if any(s in subs for s in _subs):
                matched_metas.add(_meta)

        note = ""
        if len(matched_metas) > 1:
            others = matched_metas - {meta}
            note = f"⚠️ 也在 {', '.join(sorted(others))}"
            ambiguous.append((sid, name, meta, matched_sub, note))

        if meta is None:
            meta = "其他電子"
            matched_sub = subs[0] if subs else ""
            note = f"⚠️ 未命中任何 META，原始: {', '.join(sorted(subs)[:3])}"
            ambiguous.append((sid, name, meta, matched_sub, note))

        rows.append({
            "stock_id":   sid,
            "stock_name": name,
            "meta_sector": meta,
            "sub_sector":  matched_sub or "",
            "note":        note,
        })

    universe_df = pd.DataFrame(rows).sort_values(["meta_sector", "stock_id"])
    universe_df.to_csv(UNIVERSE_CSV, index=False, encoding="utf-8-sig")

    lines = []
    lines.append(f"[OK] 輸出 {len(universe_df)} 支股票 -> {UNIVERSE_CSV}")
    lines.append(f"     META 共 {universe_df['meta_sector'].nunique()} 個")
    lines.append("")

    if ambiguous:
        lines.append(f"[!]  需人工 review 的股票（{len(ambiguous)} 支）：")
        lines.append(f"{'股票ID':<8} {'名稱':<10} {'指定META':<15} note")
        lines.append("-" * 70)
        for sid, name, meta, sub, note in sorted(ambiguous):
            note_clean = note.replace("⚠️ ", "")
            lines.append(f"{sid:<8} {name:<10} {meta:<15} {note_clean}")
    else:
        lines.append("[OK] 無爭議股票")

    lines.append("")
    lines.append("分配結果：")
    for meta, cnt in universe_df.groupby("meta_sector").size().sort_values(ascending=False).items():
        lines.append(f"  {meta:<18} {cnt:>4} 支")

    report = "\n".join(lines)
    Path("data/universe_build_report.txt").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    build()
