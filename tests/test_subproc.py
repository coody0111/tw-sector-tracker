import subprocess
import sys
import time

import pytest

from subproc import run_tree

# 父程序開一個拿著同一條 stdout 的孫程序，自己也睡著——就是 11/03 卡住的 git push 那種結構
_PARENT_WITH_GRANDCHILD = (
    "import subprocess, sys, time;"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
    "time.sleep(60)"
)


def test_run_tree_returns_output():
    r = run_tree([sys.executable, "-c", "print('hi')"], timeout=30,
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert r.returncode == 0
    assert r.stdout.strip() == "hi"


def test_run_tree_timeout_kills_grandchild_holding_pipe():
    """subprocess.run(timeout=) 在這種情況會等孫程序放開 pipe（約 60 秒）；run_tree 要在逾時後很快返回。"""
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_tree([sys.executable, "-c", _PARENT_WITH_GRANDCHILD], timeout=2,
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert time.monotonic() - started < 20
