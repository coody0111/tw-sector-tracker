# Personal Watchlist Workspace

## Goal

讓使用者手動挑選幾支股票加入個人 watchlist，並在獨立的 `watchlist.html` 查看目前資料。Watchlist 是使用者的持續觀察清單，不是 sector 分類、scanner 結果或持倉紀錄。

## Scope

### Must have

- 從首頁個股明細加入／移除股票。
- 使用瀏覽器 `localStorage` 保存股票代號與使用者備註。
- 新增獨立 `docs/watchlist.html`，只顯示使用者選入的股票。
- 每支股票顯示既有可取得的最新價格、單日漲跌、近 5/7/10/14 日報酬、成交量比與籌碼摘要。
- 顯示 Oliver Kell 工作流欄位：Weekly context、Daily context、Pivotal Point、Risk state；本階段資料不足時明確顯示「尚未建立」，不可偽造分析結論。
- 自選股不存在或資料過期時保留清單項目，標示資料狀態，不讓它靜默消失。
- 提供空清單狀態與回到首頁的入口。

### Out of scope

- 帳號、雲端同步、跨裝置同步。
- 自動將 scanner 或 sector 結果加入 watchlist。
- 下單、持倉、損益或券商整合。
- 這一輪建立 Oliver 型態辨識演算法；只預留明確欄位與 fail-soft 顯示。

## Data model

```js
{
  "2330": {
    "note": "等待週線整理完成",
    "addedAt": "2026-09-04T00:00:00.000Z"
  }
}
```

Only the stock id, note, and added timestamp are user-owned state. Market data is generated into the page and refreshed by the normal project pipeline.

## Interaction contract

- `加入自選` adds a stock id idempotently and changes to `已在自選`.
- `移除自選` removes only that stock id after the user action; no other item changes.
- Notes are edited locally and survive reload.
- The page reads the same localStorage key as the index controls and renders only matching stock ids.
- Missing or malformed localStorage falls back to an empty watchlist without crashing.

## Oliver interpretation

The watchlist is the user's selected input to the Oliver workflow:

```text
My Watchlist
  -> Weekly trend/context
  -> Daily price-cycle context
  -> Pivotal Point
  -> Risk warning / next action
```

Scanner evidence may explain why a stock was discovered, but it must not silently add the stock. Sector context is optional and must be labeled as a project layer.

## Acceptance criteria

- Generated page contains the watchlist controls and embedded stock data.
- Add/remove and note editing are localStorage-backed and idempotent.
- XSS payloads in stock names and notes render as text, never executable markup.
- Empty, malformed, unknown, and stale watchlist entries render safely.
- Existing index navigation and stock detail behavior remain unchanged.
