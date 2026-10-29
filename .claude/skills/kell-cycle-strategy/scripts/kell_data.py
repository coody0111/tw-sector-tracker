#!/usr/bin/env python3
"""Kell 價格週期分析的資料快照。

用法：python3 kell_data.py TICKER [INDEX]   （INDEX 預設 QQQ）
需要：pip install yfinance pandas

輸出步驟1所需的全部資料：日線/週線 10/20 EMA、50/200 SMA、距10EMA乖離、
週線延伸紀錄、近期K棒、相對強度、基本面、財報日期，以及指數的市場紅綠燈判斷。
"""
import sys
import warnings

warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf

WEEKLY_EXT = 7.0  # 週線距10週EMA的延伸門檻（%），見 references/extension-rules.md


def daily(t):
    d = yf.Ticker(t).history(period="2y", interval="1d", auto_adjust=False)
    d["e10"] = d.Close.ewm(span=10, adjust=False).mean()
    d["e20"] = d.Close.ewm(span=20, adjust=False).mean()
    d["s50"] = d.Close.rolling(50).mean()
    d["s200"] = d.Close.rolling(200).mean()
    d["v20"] = d.Volume.rolling(20).mean()
    d["ext10"] = (d.Close / d.e10 - 1) * 100
    d["vol_x"] = d.Volume / d.v20
    return d


def weekly(t):
    w = yf.Ticker(t).history(period="5y", interval="1wk", auto_adjust=False)
    w["e10"] = w.Close.ewm(span=10, adjust=False).mean()
    w["e20"] = w.Close.ewm(span=20, adjust=False).mean()
    w["ext10"] = (w.Close / w.e10 - 1) * 100
    return w


def pct(a, b):
    return (a / b - 1) * 100


def ext_episodes(w, weeks=78):
    """找出近 N 週內週線距10週EMA超過門檻的延伸段（上下兩側），供計算第幾次延伸。"""
    w = w.tail(weeks)
    out, cur = [], None
    for idx, x in w.ext10.items():
        side = "上" if x >= WEEKLY_EXT else "下" if x <= -WEEKLY_EXT else None
        if side and cur and cur["side"] == side:
            if abs(x) > abs(cur["peak"]):
                cur.update(peak=x, date=idx)
        elif side:
            cur = {"side": side, "peak": x, "date": idx}
            out.append(cur)
        else:
            cur = None
    return out


def snapshot(t, d, w):
    c = d.iloc[-1]
    wk = w.iloc[-1]
    hi, lo = d.Close.tail(252).max(), d.Close.tail(252).min()
    print(f"\n===== {t}  收盤 {c.Close:.2f}（{d.index[-1].date()}）")
    print(f"日線  10EMA {c.e10:.2f}  20EMA {c.e20:.2f}  50SMA {c.s50:.2f}  200SMA {c.s200:.2f}")
    print(f"      距10EMA {c.ext10:+.2f}%   10EMA{'>' if c.e10 > c.e20 else '<'}20EMA "
          f"（間距 {pct(c.e10, c.e20):+.2f}%）   50SMA{'>' if c.s50 > c.s200 else '<'}200SMA")
    print(f"週線  10週EMA {wk.e10:.2f}  20週EMA {wk.e20:.2f}  距10週EMA {wk.ext10:+.2f}%")
    print(f"52週  高 {hi:.2f}（距 {pct(c.Close, hi):+.1f}%）  低 {lo:.2f}（距 {pct(c.Close, lo):+.1f}%）")
    print(f"量    今日量/20日均量 {c.vol_x:.2f}x")
    eps = ext_episodes(w)
    if eps:
        print(f"週線延伸紀錄（近78週，門檻 ±{WEEKLY_EXT:.0f}%）：")
        for e in eps:
            print(f"   {e['date'].date()}  往{e['side']}  峰值 {e['peak']:+.1f}%")
    print("近15日：")
    cols = ["Open", "High", "Low", "Close", "vol_x", "e10", "e20", "ext10"]
    print(d[cols].tail(15).round(2).to_string())
    print("近12週：")
    print(w[["Open", "High", "Low", "Close", "e10", "e20", "ext10"]].tail(12).round(2).to_string())


def market_light(idx, d, w):
    """本 skill 的操作化門檻；Kell 本人只給了定性描述，見 references/portfolio-construction.md。"""
    c, wk = d.iloc[-1], w.iloc[-1]
    if wk.Close < wk.e10 and (wk.Close < wk.e20 or c.Close < c.s50):
        light = "🔴 紅燈：跌破10週EMA，且跌破20週EMA或50日線"
    elif wk.Close < wk.e10 or c.Close < c.e20 or wk.ext10 >= WEEKLY_EXT:
        light = "🟡 黃燈：" + ("週線已延伸" if wk.ext10 >= WEEKLY_EXT else "跌破日線20EMA或10週EMA")
    else:
        light = "🟢 綠燈：站在10週EMA與日線20EMA之上，且週線未延伸"
    print(f"\n===== 市場紅綠燈（{idx}）：{light}")


def rel_strength(t, idx):
    print("\n===== 相對強度（%）")
    print(f"{'':6} {'1個月':>7} {'3個月':>7} {'6個月':>7} {'距52週高':>9}")
    for s in [t, idx, "IWM"]:
        h = yf.Ticker(s).history(period="1y").Close
        r = [pct(h.iloc[-1], h.iloc[-n]) for n in (21, 63, 126)] + [pct(h.iloc[-1], h.max())]
        print(f"{s:6} " + " ".join(f"{x:+7.1f}" for x in r[:3]) + f" {r[3]:+9.1f}")


def fundamentals(t):
    tk = yf.Ticker(t)
    i = tk.info
    print("\n===== 基本面")
    g = lambda k: i.get(k)
    print(f"市值 {g('marketCap')}  均量 {g('averageVolume')}  beta {g('beta')}")
    print(f"營收年增 {g('revenueGrowth')}  盈餘年增 {g('earningsGrowth')}  毛利率 {g('grossMargins')}")
    try:
        q = tk.quarterly_income_stmt.loc[["Total Revenue", "Diluted EPS"]].T.sort_index().dropna()
        print(q.tail(5).to_string())
    except Exception:
        print("（季度損益表無法取得）")
    try:
        print("下次財報：", tk.calendar.get("Earnings Date"))
    except Exception:
        print("（財報日期無法取得）")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    t = sys.argv[1].upper()
    idx = (sys.argv[2] if len(sys.argv) > 2 else "QQQ").upper()
    for s in (t, idx):
        snapshot(s, daily(s), weekly(s))
    market_light(idx, daily(idx), weekly(idx))
    rel_strength(t, idx)
    fundamentals(t)


if __name__ == "__main__":
    main()
