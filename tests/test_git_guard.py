import subprocess

import pytest

from scripts.git_guard import (
    forbidden_paths, is_append_only, master_non_docs, pre_commit, pre_push, pushed_protected_branches,
)


def test_forbidden_paths_blocks_env_and_data_but_not_example():
    paths = [".env", "config/.env.local", ".env.example", "data/screener.db", "docs/data/x.json", "main.py"]
    assert forbidden_paths(paths) == [".env", "config/.env.local", "data/screener.db"]


def test_master_only_allows_docs():
    paths = ["docs/index.html", "docs/weekly/2026-11-20.html", "main.py", "debug-tasks.md"]
    assert master_non_docs("master", paths) == ["main.py", "debug-tasks.md"]
    assert master_non_docs("dev", paths) == []
    assert master_non_docs(None, paths) == []  # detached HEAD（rebase 中）不管


@pytest.mark.parametrize("old,new,ok", [
    (None, "## a\n", True),                     # 新檔
    ("## a\n", "## a\n## b\n", True),           # 接在後面
    ("## a\r\n", "## a\n## b\n", True),         # 只差換行符號
    ("## a\n", "## b\n## a\n", False),          # 插到最上面（09/02 的雷）
    ("## a\n- [ ] x\n", "## a\n- [x] x\n", False),  # 改到舊內容
    ("## a\n", None, False),                    # 刪檔
])
def test_is_append_only(old, new, ok):
    assert is_append_only(old, new) is ok


def test_pushed_protected_branches():
    z = "0" * 40
    lines = [
        f"refs/heads/master {z} refs/heads/master {z}",
        f"refs/heads/laptop {z} refs/heads/laptop {z}",
        f"refs/heads/dev {z} refs/heads/dev {z}",
        f"refs/heads/x {z} refs/heads/laptop-debug {z}",
    ]
    assert pushed_protected_branches(lines) == ["dev", "dev", "laptop-debug"]
    assert pre_push(lines) == 1
    assert pre_push(lines[:2]) == 0


def test_pushed_protected_branches_blocks_debug_into_master():
    z = "0" * 40
    assert pushed_protected_branches([f"refs/heads/debug {z} refs/heads/master {z}"]) == ["debug"]


# ---- pre_commit 整合：在 tmp 建真的 git repo ----

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "dev")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "debug-tasks.md").write_text("## [1] 舊交接\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _stage(repo, name, text):
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", name)


def test_pre_commit_allows_append(repo):
    _stage(repo, "debug-tasks.md", "## [1] 舊交接\n\n## [2] 新交接\n")
    assert pre_commit() == 0


def test_pre_commit_blocks_prepend(repo, capsys):
    _stage(repo, "debug-tasks.md", "## [2] 新交接\n\n## [1] 舊交接\n")
    assert pre_commit() == 1
    assert "debug-tasks.md 只能往檔案最下面加" in capsys.readouterr().out


def test_pre_commit_blocks_env_and_data(repo, capsys):
    _stage(repo, ".env", "TOKEN=x\n")
    _stage(repo, "data/a.csv", "x\n")
    assert pre_commit() == 1
    out = capsys.readouterr().out
    assert ".env" in out and "data/a.csv" in out


def test_pre_commit_master_only_docs(repo, capsys):
    _git(repo, "checkout", "-q", "-b", "master")
    _stage(repo, "docs/index.html", "<html></html>")
    assert pre_commit() == 0
    _stage(repo, "main.py", "print(1)\n")
    assert pre_commit() == 1
    assert "master 資料夾只收排程產出的 docs/" in capsys.readouterr().out


def test_pre_commit_chinese_filenames_not_quoted(repo, capsys):
    _git(repo, "checkout", "-q", "-b", "master")
    _stage(repo, "docs/週報 測試.html", "<html></html>")
    assert pre_commit() == 0
    _stage(repo, "data/中文.csv", "x\n")
    assert pre_commit() == 1
    assert "data/中文.csv" in capsys.readouterr().out


def test_pre_commit_skips_append_check_during_merge(repo):
    _stage(repo, "debug-tasks.md", "## [0] 另一邊\n## [1] 舊交接\n")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    # 直接寫檔（git merge 自己也是這樣）；新版 git 不准 update-ref 寫 MERGE_HEAD（CI 上的 ubuntu git 會擋）
    (repo / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")
    assert pre_commit() == 0
