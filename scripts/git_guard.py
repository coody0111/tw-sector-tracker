"""git hook 守門（2026-11-26）：把 CLAUDE.md 裡靠自律的 git 規則改成 commit／push 當下直接擋。

githooks/pre-commit、githooks/pre-push 是轉接檔，實際規則在這裡：
- pre-commit
  1. 不能 commit .env（.env.example 可以）、data/ 底下的檔案。
  2. master 只收排程產出的 docs/（11/04：在 master 改程式，被排程一起推上網）。
     發佈用的 `git merge dev` 不經過 pre-commit，不受影響。
  3. debug-tasks.md、bug-reports.md 只能往最下面加（09/02：交接插到最上面，好幾天沒人驗）。
     合併中（MERGE_HEAD）不檢查：兩邊各自 append，合起來本來就不是單純接在後面。
- pre-push：dev、debug、laptop-debug 不能 push（未驗證的程式不進 public repo）。

安裝（每台電腦一次，三個 worktree 共用）：git config core.hooksPath githooks
真的要破例：commit／push 加 --no-verify，並告訴 Cody 為什麼。
"""
import subprocess
import sys
from pathlib import PurePosixPath

APPEND_ONLY = ("debug-tasks.md", "bug-reports.md")
NO_PUSH_BRANCHES = {"dev", "debug", "laptop-debug"}
BYPASS_HINT = "真的要破例：加 --no-verify，並告訴 Cody 為什麼。"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True)


def forbidden_paths(paths: list[str]) -> list[str]:
    bad = []
    for p in paths:
        name = PurePosixPath(p).name
        if p.startswith("data/") or (name.startswith(".env") and name != ".env.example"):
            bad.append(p)
    return bad


def master_non_docs(branch: str | None, paths: list[str]) -> list[str]:
    if branch != "master":
        return []
    return [p for p in paths if not p.startswith("docs/")]


def is_append_only(old: str | None, new: str | None) -> bool:
    if old is None:
        return True
    if new is None:
        return False
    return new.replace("\r\n", "\n").startswith(old.replace("\r\n", "\n"))


def pushed_protected_branches(stdin_lines: list[str]) -> list[str]:
    # pre-push 的 stdin 每行：<local ref> <local sha> <remote ref> <remote sha>
    bad = []
    for line in stdin_lines:
        parts = line.split()
        if len(parts) == 4 and parts[2].removeprefix("refs/heads/") in NO_PUSH_BRANCHES:
            bad.append(parts[2].removeprefix("refs/heads/"))
    return bad


def _show(spec: str) -> str | None:
    r = _git("show", spec)
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None


def pre_commit() -> int:
    r = _git("symbolic-ref", "--short", "-q", "HEAD")
    branch = r.stdout.decode().strip() or None
    paths = _git("diff", "--cached", "--name-only", "--diff-filter=ACMRD").stdout.decode("utf-8").split()
    errors = []
    if bad := forbidden_paths(paths):
        errors.append("❌ 不能 commit 機敏檔或資料：" + "、".join(bad))
        errors.append("   → `git restore --staged <檔案>` 拿掉；.env 跟 data/ 只留在本機。")
    if bad := master_non_docs(branch, paths):
        errors.append("❌ master 資料夾只收排程產出的 docs/，這些不是：" + "、".join(bad))
        errors.append("   → 程式改在 ../tw-sector-tracker-dev（dev），Debugger ✅ 後照「發佈到 master」merge 進來。")
    if _git("rev-parse", "-q", "--verify", "MERGE_HEAD").returncode != 0:
        for name in APPEND_ONLY:
            if name in paths and not is_append_only(_show(f"HEAD:{name}"), _show(f":{name}")):
                errors.append(f"❌ {name} 只能往檔案最下面加，這次改到了既有內容（或刪掉了檔案）。")
                errors.append(f"   → `git diff --cached {name}` 看改了哪裡，把新段落移到最後面。")
    if errors:
        print("\n".join(errors + [BYPASS_HINT]))
        return 1
    return 0


def pre_push(stdin_lines: list[str]) -> int:
    if bad := pushed_protected_branches(stdin_lines):
        print("❌ 這些分支不 push：" + "、".join(sorted(set(bad))))
        print("   → dev／debug 只在本機；發佈是在 master 資料夾 merge dev 後 push master。筆電只 push laptop。")
        print(BYPASS_HINT)
        return 1
    return 0


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if argv[1:2] == ["pre-commit"]:
        return pre_commit()
    if argv[1:2] == ["pre-push"]:
        return pre_push(sys.stdin.read().splitlines())
    print("用法：python scripts/git_guard.py pre-commit|pre-push")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
