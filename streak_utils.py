"""共用的連續天數（streak）計算工具。"""


def calc_streak(values) -> int:
    """計算末端連買(正)或連賣(負)天數；正值代表連續買超，負值代表連續賣超。

    `screener/patterns.py` 與 `processors/performance.py` 原本各自維護一份完全等價
    的實作，合併成這支共用函式避免以後改一處漏改另一處。
    """
    values = list(values)
    if not values:
        return 0
    if values[-1] > 0:
        streak = 0
        for v in reversed(values):
            if v > 0:
                streak += 1
            else:
                break
        return streak
    elif values[-1] < 0:
        streak = 0
        for v in reversed(values):
            if v < 0:
                streak += 1
            else:
                break
        return -streak
    return 0
