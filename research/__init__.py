"""因子研究套件（唯讀，與 production 掃盤流程隔離）。

只讀 data/screener.db 的 daily_prices，不觸每日 TWSE/TPEx 流程。
設計見 quant-notes/factor/eval-harness-design.md。
"""
