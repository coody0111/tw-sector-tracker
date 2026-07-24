# 族群分類校正層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 MoneyDJ 自動分類之上加一層可存活於重跑的人工校正（`data/sector_overrides.csv`），先修正光通訊那叢 4 檔。

**Architecture:** `build_universe.py` 自動分類算完後、寫出 `stock_universe.csv` 之前，最後套用 override CSV：命中股號就覆蓋 meta/sub 並清掉 ⚠️。校正邏輯抽成純函式（`load_overrides` / `apply_overrides`）以便單元測試。實際重跑（重爬 MoneyDJ + rebuild）為 gated 操作步驟，由 Cody 執行並先 diff review。

**Tech Stack:** Python 3.12、pandas、csv（標準庫）、pytest。

## Global Constraints

- 對應 spec：`docs/superpowers/specs/2026-07-23-sector-override-layer-design.md`
- 校正只影響 override 清單明列的股號；不改 `META_PRIORITY_LIST` 關鍵字優先序；不改分類主來源。
- `data/` 被 `.gitignore` 整個 ignore；新檔 `data/sector_overrides.csv` 需一次 `git add -f` 才會被追蹤（比照 `stock_universe.csv`）。
- 依 CLAUDE.md：開發者不自跑資料抓取；`--update-sectors` 重爬由 Cody 執行。
- 檔案編碼統一 `utf-8-sig`（與現有 `stock_universe.csv` 一致）。
- 過渡期：光通訊 4 檔（2455/3081/4991/6442）目前已直接手改在 `data/stock_universe.csv`，重建接手前保持有效。

---

### Task 1: 校正純函式 + 單元測試

**Files:**
- Create: `scripts/__init__.py`
- Modify: `scripts/build_universe.py`（新增 import、`OVERRIDES_CSV` 常數、`load_overrides`、`apply_overrides`）
- Test: `tests/test_build_universe.py`

**Interfaces:**
- Produces:
  - `load_overrides(path: Path = OVERRIDES_CSV) -> dict[str, dict]`
    回傳 `{stock_id: {"meta_sector": str, "sub_sector": str, "source_note": str}}`；檔案不存在回傳 `{}`。
  - `apply_overrides(rows: list[dict], overrides: dict[str, dict]) -> list[str]`
    就地修改 `rows`（每個 row 是含 `stock_id/stock_name/meta_sector/sub_sector/note` 的 dict）；回傳 universe 中找不到的 override 股號清單。

- [ ] **Step 1: 建立 `scripts/__init__.py`（讓測試可 `from scripts.build_universe import ...`）**

建立空檔 `scripts/__init__.py`（0 bytes 即可）。

- [ ] **Step 2: 寫失敗測試 `tests/test_build_universe.py`**

```python
from pathlib import Path

from scripts.build_universe import load_overrides, apply_overrides


def test_load_overrides_missing_file_returns_empty(tmp_path):
    assert load_overrides(tmp_path / "nope.csv") == {}


def test_load_overrides_reads_rows(tmp_path):
    p = tmp_path / "ov.csv"
    p.write_text(
        "stock_id,meta_sector,sub_sector,source_note\n"
        "3081,光通訊,光通訊,財報狗題材:光通訊\n",
        encoding="utf-8-sig",
    )
    ov = load_overrides(p)
    assert ov["3081"]["meta_sector"] == "光通訊"
    assert ov["3081"]["sub_sector"] == "光通訊"
    assert ov["3081"]["source_note"] == "財報狗題材:光通訊"


def test_apply_overrides_replaces_meta_sub_and_clears_warning():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造",
             "note": "⚠️ 也在 光通訊"}]
    overrides = {"3081": {"meta_sector": "光通訊", "sub_sector": "光通訊",
                          "source_note": "財報狗題材:光通訊"}}
    unmatched = apply_overrides(rows, overrides)
    assert rows[0]["meta_sector"] == "光通訊"
    assert rows[0]["sub_sector"] == "光通訊"
    assert rows[0]["note"] == "手動校正:財報狗題材:光通訊"
    assert unmatched == []


def test_apply_overrides_empty_sub_keeps_auto_sub():
    rows = [{"stock_id": "1234", "stock_name": "X",
             "meta_sector": "其他電子", "sub_sector": "自動子族",
             "note": ""}]
    overrides = {"1234": {"meta_sector": "光通訊", "sub_sector": "",
                          "source_note": "手動"}}
    apply_overrides(rows, overrides)
    assert rows[0]["meta_sector"] == "光通訊"
    assert rows[0]["sub_sector"] == "自動子族"  # override sub 留空 → 保留自動值


def test_apply_overrides_unmatched_id_returns_warning():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造", "note": ""}]
    overrides = {"9999": {"meta_sector": "光通訊", "sub_sector": "光通訊",
                          "source_note": "x"}}
    unmatched = apply_overrides(rows, overrides)
    assert unmatched == ["9999"]
    assert rows[0]["meta_sector"] == "晶圓代工"  # 未命中不動其他股


def test_apply_overrides_no_overrides_leaves_unchanged():
    rows = [{"stock_id": "3081", "stock_name": "聯亞",
             "meta_sector": "晶圓代工", "sub_sector": "IC製造", "note": ""}]
    unmatched = apply_overrides(rows, {})
    assert unmatched == []
    assert rows[0]["meta_sector"] == "晶圓代工"
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `python -m pytest tests/test_build_universe.py -v`
Expected: FAIL（`ImportError: cannot import name 'load_overrides'`）

- [ ] **Step 4: 在 `build_universe.py` 實作函式**

在檔案頂端 import 區加入 `import csv`（`from pathlib import Path` 已存在）。

在 `UNIVERSE_CSV = Path("data/stock_universe.csv")`（第 21 行）之後新增常數：

```python
OVERRIDES_CSV = Path("data/sector_overrides.csv")
```

在 `def build()` 之前新增兩個函式：

```python
def load_overrides(path: Path = OVERRIDES_CSV) -> dict[str, dict]:
    """讀取人工校正表；檔案不存在時回傳空 dict（視為無校正）。"""
    if not path.exists():
        return {}
    overrides: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sid = (row.get("stock_id") or "").strip()
            if not sid:
                continue
            overrides[sid] = {
                "meta_sector": (row.get("meta_sector") or "").strip(),
                "sub_sector": (row.get("sub_sector") or "").strip(),
                "source_note": (row.get("source_note") or "").strip(),
            }
    return overrides


def apply_overrides(rows: list[dict], overrides: dict[str, dict]) -> list[str]:
    """將 overrides 套用到 rows（就地修改）。

    命中 stock_id 時覆蓋 meta_sector；override 的 sub_sector 非空才覆蓋（留空保留
    自動值）；note 改標「手動校正:<source_note>」並清除原 ⚠️ 爭議標記。
    回傳 universe 中找不到的 override 股號清單，供呼叫端警告。
    """
    matched = set()
    for row in rows:
        sid = str(row["stock_id"])
        ov = overrides.get(sid)
        if not ov:
            continue
        matched.add(sid)
        row["meta_sector"] = ov["meta_sector"]
        if ov["sub_sector"]:
            row["sub_sector"] = ov["sub_sector"]
        row["note"] = f"手動校正:{ov['source_note']}" if ov["source_note"] else "手動校正"
    return [sid for sid in overrides if sid not in matched]
```

- [ ] **Step 5: 執行測試確認通過**

Run: `python -m pytest tests/test_build_universe.py -v`
Expected: PASS（6 passed）

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/build_universe.py tests/test_build_universe.py
git commit -m "feat(universe): 族群校正純函式 load_overrides/apply_overrides + 測試"
```

---

### Task 2: 整合進 build() + 缺檔錯誤處理 + 種子 CSV

**Files:**
- Modify: `scripts/build_universe.py`（`build()` 內：缺輸入檔明確報錯、套用 overrides、報告未命中警告）
- Create: `data/sector_overrides.csv`

**Interfaces:**
- Consumes: Task 1 的 `load_overrides`、`apply_overrides`。

- [ ] **Step 1: 建立種子 `data/sector_overrides.csv`**

內容（`utf-8-sig`）：

```
stock_id,meta_sector,sub_sector,source_note
2455,光通訊,光通訊,財報狗題材:光通訊
3081,光通訊,光通訊,財報狗題材:光通訊
4991,光通訊,光通訊,財報狗題材:光通訊
6442,光通訊,光通訊,財報狗題材:光通訊
```

- [ ] **Step 2: 缺輸入檔明確報錯**

在 `build()` 開頭（現 `df = pd.read_csv(SECTOR_CSV, ...)` 之前）加入：

```python
    if not SECTOR_CSV.exists():
        raise SystemExit(
            f"[錯誤] 找不到 {SECTOR_CSV}。請先執行 `python main.py --update-sectors` "
            f"重新從 MoneyDJ 產生族群中繼檔後再跑 build。"
        )
```

- [ ] **Step 3: 在寫出 CSV 前套用 overrides**

在 `build()` 內，`for` 迴圈組完 `rows` 之後、`universe_df = pd.DataFrame(rows)...`（現第 82 行）之前插入：

```python
    # 最後套用人工校正（財報狗題材佐證），使其在每次 rebuild 後仍存活
    overrides = load_overrides()
    missing_override_ids = apply_overrides(rows, overrides)
```

- [ ] **Step 4: 報告未命中的 override 股號**

在產生報告的 `lines` 區塊（現「分配結果」列印之前）加入：

```python
    if missing_override_ids:
        lines.append("")
        lines.append(f"[!]  overrides 中有 {len(missing_override_ids)} 檔在 universe 找不到"
                     f"（下市或代號錯）：{', '.join(sorted(missing_override_ids))}")
```

- [ ] **Step 5: 以暫存輸入實跑 build 驗證整合（不動真實檔）**

用一個最小 `industry_sectors.csv` 暫存驗證 override 生效。Run：

```bash
python - <<'PY'
import csv, tempfile, os
from pathlib import Path
import scripts.build_universe as bu

# 模擬自動分類結果：3081 原本被歸晶圓代工
rows = [{"stock_id": "3081", "stock_name": "聯亞",
         "meta_sector": "晶圓代工", "sub_sector": "IC製造", "note": "⚠️ 也在 光通訊"},
        {"stock_id": "2330", "stock_name": "台積電",
         "meta_sector": "晶圓代工", "sub_sector": "晶圓代工", "note": ""}]
ov = bu.load_overrides()  # 讀真實 data/sector_overrides.csv
missing = bu.apply_overrides(rows, ov)
assert rows[0]["meta_sector"] == "光通訊", rows[0]
assert rows[0]["note"] == "手動校正:財報狗題材:光通訊", rows[0]
assert rows[1]["meta_sector"] == "晶圓代工", rows[1]  # 未列入者不動
print("OK 整合驗證通過；overrides 缺檔清單:", missing)
PY
```

Expected: 印出 `OK 整合驗證通過；overrides 缺檔清單: []`

- [ ] **Step 6: 執行既有測試確認無回歸**

Run: `python -m pytest tests/test_build_universe.py -v`
Expected: PASS

- [ ] **Step 7: Commit（含 `-f` 強制追蹤 override 檔）**

```bash
git add -f data/sector_overrides.csv
git add scripts/build_universe.py
git commit -m "feat(universe): build 套用 sector_overrides + 缺輸入檔明確報錯 + 光通訊4檔種子"
```

---

### Task 3（Gated，操作步驟；Cody 執行）: 重爬重建 + diff review

> 這一步會產生**全新** `stock_universe.csv`，可能有多檔隨 MoneyDJ 最新資料變動（與本次校正無關）。**必須先 diff review 才放行**。不做這步也不影響現況（4 檔手改仍生效）。
>
> ✅ **exchange 欄已由 build 自動保留**：`build_universe.py` 現在會從既有 `stock_universe.csv` 帶回每檔的 `exchange`（TWSE/TPEx），並輸出 6 欄正確欄序。重建**不會再整欄清掉 exchange**（已根除歷史踩過的地雷）。唯一殘留：**新上市股**在舊檔沒有、exchange 會留空 → 需 `update_exchange.py` 補；即使漏跑也只影響少數新股，不再打斷整個每日流程。

- [ ] **Step 1: 重爬 MoneyDJ 族群（Cody，約 15 分）**

Run: `python main.py --update-sectors`
Expected: 產生 `data/sectors/industry_sectors.csv`，log 顯示 `Sectors saved to ...`

- [ ] **Step 2: 重建 universe**

Run: `python scripts/build_universe.py`
Expected: 印出分配結果；若 overrides 有缺檔會列警告。輸出 6 欄、**既有股 exchange 已保留**，只有新上市股 exchange 留空。

- [ ] **Step 3: 補新上市股的 exchange 欄（建議）**

Run: `python scripts/update_exchange.py`
Expected: 取得 TWSE 上市清單，把留空的新股補上 TWSE/TPEx。需為交易日才抓得到 TWSE 清單。（既有股 exchange 已由 build 保留，此步主要是補新股。）

- [ ] **Step 4: diff review 新舊 universe**

Run: `git diff data/stock_universe.csv`
逐段檢視變動是否合理：
- 新股/下市屬正常。
- 光通訊 4 檔（2455/3081/4991/6442）meta 應為 `光通訊`，note 應顯示 `手動校正:財報狗題材:光通訊`（**注意**：interim 手改版的這 4 行 note 是空的，重建後會變成 `手動校正:...`，屬預期差異，非異常）。
- **確認 `exchange` 欄仍在且大多已填**（若整欄空白代表 Step 3 漏跑或非交易日）。

- [ ] **Step 5: 確認合理才 commit**

```bash
git add data/stock_universe.csv data/universe_build_report.txt
git commit -m "chore(universe): 重建族群並套用校正層（rebuild + overrides + exchange）"
```

若 diff 有非預期大規模改動 → 先停下來與 Cody 確認，不要直接 commit。

---

## 交付與驗證（給 Debugger）

- [ ] `load_overrides` / `apply_overrides` 單元測試全綠
- [ ] override 只動清單內股號，未列入者不受影響
- [ ] override sub/meta 留空 → 保留自動值；命中 → 清除 ⚠️
- [ ] 缺輸入檔給明確錯誤而非裸例外
- [ ] （Task 3 若執行）重建後 `stock_universe.csv` 仍有 `exchange` 欄（update_exchange.py 有跑）
- [ ] 上市/上櫃資料來源無混用（本變更不碰行情/籌碼來源）
- [ ] 不影響 main.py 每日流程（僅 universe 建置階段）
