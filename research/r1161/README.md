# r1161 個股策略適用性：Claude 接手說明

本批只發布每檔波動／研究證據／自設成本風險參考。沒有修改任何正式成交、排序、停損或推播規則。新研究方案全部不晉級，詳細結果見同目錄報告。

## 網站資料契約

- `strategy_profiles.json` 是2422檔固定研究快照；鍵為 `市場:代碼`，不是每日勝率或即時訊號。
- completed 是2016起本股跌深策略、不重疊且已完成的交易數。0不等於沒有價格歷史，missing不等於0。20筆只是一個研究最低門檻，不代表有效。
- 每檔 `as_of` 可能不同，例如2330研究價格截至2026-10-16；畫面目前波動按已載入完整日K計算，截至2026-10-22，明確分開日期。
- 網站只讀約213KB快照，不載原始來源或全市場多年K。ATR用20日簡單平均真實波幅，非Wilder平滑ATR，並非模型中期停損的替代輸入。
- ETF、歷史備援、未對齊／無效K、還原因子未載入時不推定波動。台股近61日有斷層則不解讀ATR距離。
- 風險試算僅自設成本＋原跌深停損，雙邊0.3%假設，不接入AI Pick其他策略、不寫持股。未填成本不用現價補。

## 重跑與永久保存

`python stock_adaptive_research.py --market both --output research/local-r1161.json`

`python build_stock_profiles.py`

需要numpy、pandas及repo既有研究引擎。研究截止日是 `stock_adaptive_research.ASOF`，目前固定2026-10-23；更換截止／輸入要另存新版本與結果，不可把舊研究默認成新驗證。build預先按SHA保存替換前及本次快照到archive/stock_research/profile_versions，不刪舊版本。本批沒有新增自動排程。

公開公司行動原回應在 `archive/stock_research/r1161/raw`。只新增既有還原表沒有的同日事件，避免雙重調整；衝突不猜。這是研究載入器補充，沒有把這些因子回灌網站ADJ1或正式交易引擎。它不等於精確計入減資退款／現金股利的財富帳。

結果JSON裡的source_commit及sources SHA是原研究輸入，不是部署後main。原研究的額外來源路徑為本機outputs/r1161_sources，已將相同位元組移存repo上面raw路徑；其SHA可核對。部署版研究引擎只修改此來源路徑以便攜帶；原研究結果不重寫。不同股票當前分類／現有股庫有倖存者偏差；當前財報pit_eligible=false，禁止回填作歷史已知因子。

## 驗證與回退

`node --test tests/*.test.cjs`

`python -m unittest discover -s tests -p 'test_*.py'`

Windows TEMP/TMP設工作區.cache。新stock-profile.test.cjs驗證完整日K、價格與日期異常、分市場索引、樣本不足、ETF與成本隔離及快照和實測例子的數量一致。研究測試另含無未來資料選股、未實現損失、同日雙觸價、停牌／零量取消、公司行動不雙重調整。

回退只處理前端與快照讀取程式。保留所有研究、公開來源、版本快照及後續機器人資料，不要整個PR revert刪資料。

逐筆帳以.json.gz保存，解壓後與原始outputs JSON逐位元組相同；這只是儲存格式，原始本機結果與交接ZIP仍保留。
