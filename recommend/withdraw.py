"""集保更新後撤回（2026-10-26 Cody：「需要有撤回理由」）：集保補進來後，收盤版推薦過、但同一訊號日已不再符合的股票。
新一週集保進來後，「大戶週增」（big1w）換成當週的週增，收盤時靠舊一週大增命中大戶路線的股票會掉出前 10%
（Debugger 複本：06-18 撤回 3537／6155、10-16 撤回 3701，都是大戶路線；2026-10-26 更正原先「總股數改變 inst5」的推測）。
回測用的是「含集保當天」的版本，所以以集保更新版為準：撤回、附理由、成績單標「撤回」不計成績。"""
import pandas as pd

from recommend.strategies.breakout import PR_TOP, TRUST_DAYS

WITHDRAWN = "撤回"
_PR_ROUTES = {"法人": ("inst5_pr", "法人買超占股本"), "外資": ("fpct5_pr", "外資持股增幅"), "大戶": ("big1w_pr", "大戶週增")}


def _route_ok(route: str, row: pd.Series) -> bool:
    if route == "投信":
        return bool(pd.notna(row["trust_days10"]) and row["trust_days10"] >= TRUST_DAYS)
    v = row[_PR_ROUTES[route][0]]
    return bool(pd.notna(v) and v >= PR_TOP)


def _route_text(route: str, row: pd.Series) -> str:
    if route == "投信":
        v = row["trust_days10"]
        return f"投信 10 日買超 {0 if pd.isna(v) else v:.0f} 天（需 ≥ {TRUST_DAYS} 天）"
    col, label = _PR_ROUTES[route]
    v = row[col]
    if pd.isna(v):
        return f"{label}：無資料"
    return f"{label}排名前 {(1 - v) * 100:.1f}%（需前 {(1 - PR_TOP) * 100:.0f}%）"   # 一位小數：0.895 不會顯示成「前 10%」


def withdraw_reasons(features: pd.DataFrame, day, cards: list) -> list:
    """cards：收盤版推薦過、集保更新版已沒有的卡片。逐條看收盤時命中的路線，現在哪幾條不成立。"""
    today = features[features["date"] == pd.Timestamp(day)].set_index("stock_id")
    out = []
    for c in cards:
        routes = [r for r in (c.get("routes") or "").split(",") if r]
        if c["stock_id"] in today.index:
            row = today.loc[c["stock_id"]]
            lost = [_route_text(r, row) for r in routes if not _route_ok(r, row)]
        else:
            lost = []
        out.append({"stock_id": c["stock_id"], "stock_name": c.get("stock_name"), "meta_sector": c.get("meta_sector"),
                    "routes": c.get("routes"),
                    "reason": "；".join(lost) if lost else "籌碼路線仍命中，其他條件改變"})
    return out


def mark_withdrawn(con, cards: list, day) -> int:
    """成績單把這幾筆標成撤回（不再追蹤、不計成績）。回傳更新筆數。"""
    d = pd.Timestamp(day).date()
    for c in cards:
        con.execute("UPDATE recommendations SET exit_reason = ? WHERE strategy = ? AND stock_id = ? AND signal_date = ?",
                    [WITHDRAWN, c["strategy"], c["stock_id"], d])
    return len(cards)
