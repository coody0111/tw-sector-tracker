"""根目錄 .bat 只能是 ASCII、CRLF（2026-11-26）。

cmd 用主控台 code page（桌電 cp950）讀 .bat：UTF-8 中文會切錯行，把註解片段當指令執行
（當時 end-work.bat 的註解裡剛好有「git add . + push master」）；chcp 65001 只修好顯示、切行照錯。
LF 換行在 cmd 也會讓 goto／call 標籤跑掉。
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BATS = sorted(ROOT.glob("*.bat"))


def test_bat_files_exist():
    assert BATS, "根目錄應該有 start-desktop.bat／start-laptop.bat／end-work.bat"


@pytest.mark.parametrize("bat", BATS, ids=lambda p: p.name)
def test_bat_is_ascii(bat):
    bad = [(i, line) for i, line in enumerate(bat.read_bytes().split(b"\n"), 1) if not line.isascii()]
    assert not bad, (
        f"{bat.name} 有非 ASCII 字元（第 {', '.join(str(i) for i, _ in bad)} 行）。"
        "cmd 會用 cp950 讀，UTF-8 中文會切錯行；訊息請改英文。"
    )


@pytest.mark.parametrize("bat", BATS, ids=lambda p: p.name)
def test_bat_is_crlf(bat):
    data = bat.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n"), (
        f"{bat.name} 有 LF 換行，cmd 要 CRLF。.gitattributes 已設 *.bat eol=crlf，重新 checkout 或轉換換行即可。"
    )
