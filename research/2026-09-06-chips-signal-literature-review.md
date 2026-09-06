# 籌碼訊號文獻回顧（2026-09-06）

> 背景：`docs/superpowers/specs/2026-08-25-chips-page-signal-audit-design.md` 用專案自己的
> 回測框架驗證了 11 條籌碼規則，結論是沒有一條有穩定正向 edge。那份 spec 的背景段落提到
> Cody 一度想找外部 paper 佐證、後來改用自家真實資料回測。這份筆記是事後補做的外部文獻
> 檢索，用來交叉檢查回測結論是否跟已知學術/實務研究方向一致，並找下一步可能的分析方法。
>
> 結論先講：外部文獻**沒有**提供一個可以直接套用的新訊號，樣本量（57-63 個訊號日）仍是
> 最大限制。文獻主要功能是**驗證**現有分級判斷是否合理，以及指出「越跌越買」「外資偷偷買」
> 這類規則名稱背後真正的學術定義是什麼、跟專案現有資料能不能測出這個定義。

## 檢索方式

用 WebSearch 跑了 4 輪查詢：
1. `foreign institutional investor trading flow predict stock returns academic research`
2. `margin trading balance sentiment indicator contrarian predictor stock returns Taiwan`
3. `institutional accumulation without price impact stealth trading detection academic`
4. `三大法人 買賣超 選股 學術研究 報酬`

## 發現

### 1. 外資／法人買賣超流量的預測力——國際文獻本身就分歧

- 香港週流量能預測報酬、獲利驚喜（[Foreign institutions, local investors and momentum trading](https://www.sciencedirect.com/science/article/abs/pii/S0927539823000543)）
- 印度研究反而發現更多「外資流量是報酬的結果、不是原因」的證據（[Trading Behaviour of Foreign Institutional Investors: Evidence from Indian Stock Markets](https://pmc.ncbi.nlm.nih.gov/articles/PMC9145119/)）
- 外資投資機構能降低跨股報酬 comovement（減少錯價）（[Foreign institutional investors and stock return comovement](https://fbr.springeropen.com/articles/10.1186/s11782-018-0036-8)）

**沒有一致結論**，效果方向/大小高度依市場而異。跟本專案回測（61日/377筆 `joint_buy`：均值+1.55%但中位數-2.58%）呈現的「不穩定、被少數大贏家拉正」現象，方向上吻合——不是本專案資料或方法有問題，是這類訊號本來就不穩定。

### 2. 融資餘額——文獻定位是「情緒/槓桿指標」，不是「未來報酬預測指標」

- 台灣本地研究把融資餘額當**散戶情緒/反向指標**，且是「跟當期報酬同步的負相關」，不是「預測未來報酬」
- [Margin Credit and Stock Return Predictability（NYU Stern）](https://www.stern.nyu.edu/sites/default/files/assets/documents/DKP_Margin_Credit_20160901.pdf)：這篇文獻做的是**市場層級**（aggregate margin credit）預測後續市場報酬，不是個股層級
- [Can margin traders predict future stock returns in Japan?](https://ideas.repec.org/a/eee/pacfin/v17y2009i1p41-57.html)：日本市場也傾向認為融資是落後/反向指標

**這驗證了現有分級是對的**：`margin_bearish` 定位成「示警」而非「選股訊號」，5日內有效、拉長退化，剛好符合文獻說的「同步指標」特性——不是規則設計錯，是這類資料本質上就只適合短期示警。

### 3.「外資偷偷買」規則名稱借用的學術概念，本專案資料測不出來

- 學術上的 stealth trading（[Barclay & Warner](https://www.sciencedirect.com/science/article/abs/pii/S0304405X01000630)）指的是「大戶把單子切成中等單量、混在市場裡降低被偵測機率」，中等單量的累積價格影響異常大
- 這需要**逐筆交易的單量分布資料**才能偵測；TWSE/TPEx 的 T86 只有**當日淨買賣總額**，沒有單筆交易大小，物理上測不出真正的 stealth trading
- 專案現有的近似（連買 streak + 價格平穩）比較接近散戶論壇常見的「窄幅盤整+量縮=籌碼在收」（[Identifying Quiet Institutional Accumulation](https://traderlion.com/trading-strategies/identifying-quiet-institutional-accumulation/)），是合理近似但跟學術原意是兩回事

值得在頁面文案上更誠實一點（例如標註「近似觀察，非嚴謹學術定義」）。

### 4. 中文學術文獻幾乎搜不到三大法人買賣超的系統性研究

反過來印證了 2026-08-25 spec 當初的判斷：與其找外部 paper（別的市場、別的資料源），不如信自家用真實歷史回測出來的結果，這是目前能拿到的最直接證據。

## 下一步可能方向（未決定，待討論）

樣本量才是最大限制，**不建議**調整任何規則的門檻/權重去硬找 edge（容易 overfit，2026-08-25 spec 已有這條 non-goal）。比較誠實的方向：

- **A. 把融資餘額從「個股背離示警」改成「市場層級的槓桿情緒指標」**，餵進
  `classify_market_regime()`——這才是文獻真正驗證過的用法，不是個股層級。**建議優先討論這個**，
  文獻支持最扎實、改動範圍也最小。
- **B. 法人買進要求「低量」而非只看「平價」**：用專案已有的成交量/週轉率資料，讓「偷偷買」
  近似值更貼近文獻定義一點（雖然還是不是真正的 stealth trading）。
- **C. 等資料再累積幾個月，才測 regime-conditional 訊號**：spec 已發現 `stealth_buy` 在
  盤整 regime 有 +3%，但 n=8-9 太小不可信，需要更多月份的法人資料才能真正驗證。

## 相關文件

- `docs/superpowers/specs/2026-08-25-chips-page-signal-audit-design.md` — 原始回測稽核 spec
- `docs/superpowers/plans/2026-08-25-chips-page-evidence-tiers.md` — 已實作的視覺/資訊架構分級
- `screener/backtest.py` — 回測框架本體
