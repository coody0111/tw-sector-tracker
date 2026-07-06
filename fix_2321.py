"""
桌電用：修正 2321(東訊) 2026-07-02 的 close=0 髒值 → 13.9。
只有在 close<=0 時才改（已正確就不動，可安全重複執行）。
靠 CSV header 對欄位，不管批次/realtime 哪種格式都能改對。
改完請執行： python main.py --reimport
"""
import io, os

CSV = "data/daily_prices/2026-07-02.csv"
SID = "2321"
GOOD_CLOSE = "13.9"   # 06-30/07-01 的穩定真實價（FinMind/即時當天都壞成 0，故用此值）

if not os.path.exists(CSV):
    print(f"找不到 {CSV}，桌電可能沒有這天的資料，無需處理。")
    raise SystemExit

with io.open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    lines = f.readlines()

header = lines[0].rstrip("\r\n").split(",")
def idx(name): return header.index(name) if name in header else -1
i_sid, i_close, i_chg, i_pct = idx("stock_id"), idx("close"), idx("change"), idx("change_pct")
if min(i_sid, i_close) < 0:
    print(f"header 沒有 stock_id/close 欄位，格式異常，請人工檢查：{header}")
    raise SystemExit

changed = False
for n, ln in enumerate(lines[1:], start=1):
    cols = ln.rstrip("\r\n").split(",")
    if len(cols) <= max(i_sid, i_close) or cols[i_sid] != SID:
        continue
    try:
        cur = float(cols[i_close])
    except ValueError:
        cur = None
    print(f"目前 {SID} close = {cols[i_close]!r}")
    if cur is None or cur <= 0:
        cols[i_close] = GOOD_CLOSE
        if i_chg >= 0: cols[i_chg] = "0.0"      # 跟前一日 13.9 相同 → 無漲跌
        if i_pct >= 0: cols[i_pct] = "0.0"
        lines[n] = ",".join(cols) + "\n"
        changed = True
        print(f"  → 已改成 close={GOOD_CLOSE}, change=0.0, change_pct=0.0")
    else:
        print("  → 已是正常值(>0)，不動。")
    break
else:
    print(f"{CSV} 裡沒有 {SID} 這筆，無需處理。")

if changed:
    with io.open(CSV, "w", encoding="utf-8-sig", newline="") as f:
        f.writelines(lines)
    print("\n✅ CSV 已修正。請接著執行： python main.py --reimport")
else:
    print("\n（沒有變更，不需要 reimport）")
