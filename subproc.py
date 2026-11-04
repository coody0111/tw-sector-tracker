"""子程序逾時要連整棵程序樹一起結束（2026-11-04）。

`subprocess.run(timeout=...)` 只砍直接子程序；孫程序（例如 main.py 底下的 git push）會繼續拿著
stdout／stderr pipe，Windows 上逾時後的 communicate() 就一直等不到 pipe 關閉，呼叫端跟著卡住。
11/03 22:00 一次卡住的 git push 就這樣讓排程鎖 22 小時沒釋放、11/04 盤中和收盤全部沒跑。
"""
import os
import signal
import subprocess

_DRAIN_SEC = 10  # 砍完程序樹後再等 pipe 關閉的上限；還有漏網的孫程序就不等了


def kill_tree(pid: int) -> None:
    """結束 pid 跟它底下所有子孫程序。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    try:
        os.killpg(pid, signal.SIGKILL)  # run_tree 在 POSIX 用 start_new_session，pid 就是 process group id
    except (ProcessLookupError, PermissionError):
        pass


def run_tree(cmd: list, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    """用法同 subprocess.run（不支援 check／capture_output，改傳 stdout=PIPE）；逾時時把整棵程序樹
    結束後再拋 TimeoutExpired。"""
    if os.name != "nt":
        kwargs.setdefault("start_new_session", True)
    with subprocess.Popen(cmd, **kwargs) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            proc.kill()
            try:
                out, err = proc.communicate(timeout=_DRAIN_SEC)
            except subprocess.TimeoutExpired:
                out, err = None, None
            raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
