"""資料來源邊界（2026-11-26）：每日流程只能用 TWSE／TPEx 官方，FinMind／yfinance 只准出現在歷史回補。

CLAUDE.md「資料來源規則」以前只靠人記；這支測試靜態掃全部程式碼（AST），回補來源的名字一出現在白名單外就失敗。
要新增回補功能：放進 scrapers/backfill.py，main.py 的入口函式登記在下面的 BACKFILL_ENTRYPOINTS。
靜態掃描抓不到的寫法：importlib.import_module("yfinance")、getattr 字串取函式——不要這樣寫。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"tests", "research", "docs", ".claude", ".agents", ".git", "__pycache__", "data",
             ".venv", "venv", "env", "site-packages"}  # venv 建在 repo 裡時別把 yfinance 套件本身掃進來

# 歷史回補才用的資料來源（FinMind 走 requests＋FINMIND_URL，yfinance 是套件）
SOURCE_NAMES = {
    "yfinance", "backfill_yfinance", "backfill_twse_monthly", "_fetch_finmind_history",
    "_fetch_yfinance_one_stock", "FINMIND_URL", "FINMIND_TOKEN",
}
SOURCE_STRINGS = ("finmindtrade.com",)
# main.py 裡呼叫回補來源的函式；它們只能從命令列分派（if __name__ == "__main__"）呼叫
BACKFILL_ENTRYPOINTS = {"backfill_twse", "backfill_yf", "_full_rebuild"}

SOURCE_ALLOWED_FILES = {"scrapers/backfill.py"}
SOURCE_ALLOWED_DEFS = {"scrapers/chips.py": {"FINMIND_TOKEN"}}  # token 從 .env 讀，定義在這


def _py_files():
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if not SKIP_DIRS & set(rel.parts):
            yield rel.as_posix(), ast.parse(p.read_text(encoding="utf-8"), filename=str(rel))


def _is_main_guard(node) -> bool:
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")


def _names(node):
    """節點本身引用到的名字（Name、屬性、import、字串常數）。"""
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, ast.Attribute):
        yield node.attr
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield from node.module.split(".")
        for a in node.names:
            yield from a.name.split(".")
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        for s in SOURCE_STRINGS:
            if s in node.value:
                yield s


def _refs(tree):
    """(行號, 名字, 所在頂層位置)；位置是頂層函式名、"__main__"（命令列分派）或 "<module>"。"""
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            where = top.name
        elif _is_main_guard(top):
            where = "__main__"
        else:
            where = "<module>"
        for node in ast.walk(top):
            for name in _names(node):
                yield node.lineno, name, where, isinstance(top, (ast.Import, ast.ImportFrom))


def _violations():
    bad = []
    for rel, tree in _py_files():
        for line, name, where, is_import in _refs(tree):
            if name in SOURCE_NAMES or name in SOURCE_STRINGS:
                if rel in SOURCE_ALLOWED_FILES or name in SOURCE_ALLOWED_DEFS.get(rel, set()):
                    continue
                # main.py 頂層只准 import scrapers.backfill 的函式；頂層 import yfinance 等於每日流程也拿得到 yf
                if rel == "main.py" and (where in BACKFILL_ENTRYPOINTS or (is_import and name != "yfinance")):
                    continue
                bad.append(f"{rel}:{line} 用到回補來源 {name}（在 {where}）")
            elif name in BACKFILL_ENTRYPOINTS:
                if rel == "main.py" and where in BACKFILL_ENTRYPOINTS | {"__main__"}:
                    continue
                bad.append(f"{rel}:{line} 每日流程呼叫回補入口 {name}（在 {where}）")
    return bad


def test_backfill_sources_stay_in_backfill_paths():
    bad = _violations()
    assert not bad, (
        "每日流程只能用 TWSE／TPEx 官方 API，FinMind／yfinance 只准用在歷史回補：\n  "
        + "\n  ".join(bad)
        + "\n→ 回補程式放 scrapers/backfill.py，main.py 的入口函式登記在這支測試的 BACKFILL_ENTRYPOINTS，"
          "只從命令列（if __name__ == '__main__'）呼叫。真的是新回補功能才改這支測試的白名單。"
    )


def test_boundary_detects_violations(tmp_path, monkeypatch):
    # 確認掃描器真的抓得到：每日模組 import yfinance、直接打 FinMind 網址、每日函式呼叫回補入口
    (tmp_path / "scrapers").mkdir()
    (tmp_path / "scrapers" / "twse.py").write_text(
        "import yfinance as yf\nURL = 'https://api.finmindtrade.com/api/v4/data'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "def backfill_yf():\n    import yfinance\n\n"
        "def run_daily():\n    backfill_yf()\n\n"
        "if __name__ == '__main__':\n    backfill_yf()\n"
        "import yfinance as yf\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    bad = _violations()
    assert "scrapers/twse.py:1 用到回補來源 yfinance（在 <module>）" in bad
    assert "scrapers/twse.py:2 用到回補來源 finmindtrade.com（在 <module>）" in bad
    assert "main.py:5 每日流程呼叫回補入口 backfill_yf（在 run_daily）" in bad
    assert "main.py:9 用到回補來源 yfinance（在 <module>）" in bad
    assert len(bad) == 4  # backfill_yf 裡的 import、__main__ 的呼叫都是允許的
