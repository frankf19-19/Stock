# AGENTS.md — K研所 交接說明(給所有 AI 工具:Claude、GPT/Codex、Copilot…)

> 任何 AI 接手這個 repo 前,**先整份讀完**。這裡的規則優先於你自己的習慣。
> 擁有者:Frank(不寫程式,全部實作交給 AI;溝通一律**繁體中文**、白話)。
> 最後更新:2026-10-23(r1155)。改了架構或規則請同步更新本檔。

---

## 0. 多個 AI 輪流維護的協作規則(最重要)

1. **一次只讓一個 AI 動程式。** 換手前確認上一個 AI 的改動已經推上 `main`。
2. **動手前先同步**:`git pull --rebase origin main`。推之前再同步一次。後台機器人每幾分鐘就 commit 資料檔,不同步一定撞車。
3. **只做「檢查/建議」的 AI 不要推 code**:把問題清單交給 Frank,由負責實作的 AI 驗證後再改。
4. **要改程式但不確定的 AI**:開分支 + Pull Request,不要直接推 `main`。
5. **每次推上去都在本檔最下面「交接紀錄」加一行**:日期、版本號、改了什麼、誰改的。
6. **不要在對話裡要求或貼出任何金鑰/token/密碼。**

---

## 1. 這是什麼

台股(上市櫃約 1,800 檔)+ 美股(S&P 500)的個人量化研究網站,**零成本**、全自動。
- 網站:<https://frankf19-19.github.io/Stock/>(GitHub Pages,靜態)
- 後台:GitHub Actions(Python)定時抓資料、算分數、回測、跑 AI Pick,結果 commit 回 repo
- 即時報價/推播排程:Cloudflare Worker(**原始碼不在這個 repo**,只有台股哨兵 `worker_sentinel.js` 的參考版;美股推播哨兵只在 Cloudflare 上)
- 雲端同步(最愛/持股):Supabase;推播:Web Push(VAPID)

## 2. 檔案地圖

### 前端(三個檔要一起看)
| 檔案 | 內容 |
|---|---|
| `index.html` | 外殼、分頁骨架;載入 `app.css?v=rXXXX`、`app.js?v=rXXXX` |
| `app.js` | **全部前端邏輯**(約 2.6 萬行,單檔)。`const APP_BUILD='rXXXX'` 是版本號 |
| `app.css` | 樣式;主題用 CSS 變數(`--up` 紅=漲、`--down` 綠=跌) |
| `sw.js` | Service Worker:離線快取 + **推播顯示格式**(`aipTitle()` 把股票名稱移到標題最前面) |
| `mobile.js` | 手機版調整 |

### 後台(Python,`.github/workflows/*.yml` 排程呼叫)
| 檔案 | 用途 |
|---|---|
| `update_data.py` | 主資料(報價、財報、籌碼、分數)→ `data.json`、`c/*.json`(籌碼分片)、`k/*.json`(K 線) |
| `update_quotes.py` | 盤中每 5 分鐘掃 MIS 即時價;**自動偵測颱風假/臨時休市**(`unscheduled_closure`) |
| `aip3.py` | **AI Pick 三清單**(短/中/長期,台股+美股)→ `aip3.json`、`aip3_live.json` |
| `aipick.py`、`trader.py`、`pvsleeve.py`、`strat_os.py` | 舊 AI Pick、主力 20 檔帳戶(量價籌碼模型)、錯殺低接實戰追蹤 → `aipick.json` |
| `market_view.py` | 盤勢解讀(AI 寫)→ `view.json` |
| `listen_gooaye.py`、`listen_show.py` | 股癌/財經皓角 podcast AI 整理 → `gooaye.json`、`yth.json`(+ `*_hist/` 月歸檔,永久) |
| `listen_conf.py`、`listen_us.py` | 法說會簡報 AI 讀(MOPS)/ 美股 SEC 8-K 財報新聞稿 → `ir/`、`ir_us/` |
| `fetch_holidays.py`、`market_day.py` | 休市行事曆 `holidays.json`(證交所官方 + NYSE 規則 + 資料學到的颱風假) |
| `notify.py` | Web Push 推播(最愛/持股/內部人等) |
| `*_study.py` | **回測器**(見第 6 節),手動跑,不在排程裡 |

### 資料
- `archive/`:歷史資料(K 線 2012~、法人、月營收、除權息還原…),**只增不減**
- `data.json`、`c/`、`k/`、`m/`、`e/`…:網站直接讀的資料
- 研究報告(回測結果表格)存在 Frank 的 claude.ai 專案「股票」裡,不在 repo;結論已寫進程式註解與網站上的「🧪 為什麼規則是這樣」表

## 3. Frank 的規則(違反就是 bug)

**訊號與內容**
- 網站上所有判斷/訊號都要**先用真實歷史資料回測驗證**才能顯示;沒驗證的要標「參考」或「實測不準」。不要自己加沒回測過的指標當買賣訊號。
- 買賣時機、停損、停利一律用**具體價格**,不要用分數/排名門檻。說明要白話。
- 每檔個股要有:目前狀況、可以買的價格範圍、停損價、停利價。以**個股自己**為主,不要拿個股跟大盤比。
- 台灣慣例:**紅 = 漲/偏多,綠 = 跌/偏空**,全站一致。

**資料**
- **永遠不要砍資料**。所有紀錄(訊號、AI Pick、交易、淨值、AI 整理、外部來源資料)永久保存。檔案要改格式先遷移,不能覆蓋丟失。
- 歷史資料至少回溯 10 年。
- 外部來源(FinMind 等)的資料要自己存一份,來源停了也不能消失。

**功能**
- **不要自行刪除或隱藏網站區塊**。「整理」= 排版或補缺,不是刪除;要刪先問 Frank。沒在用的可以收合(紀錄保留)。
- 所有數字要即時(盤中跟著即時價走)。
- 颱風假等臨時休市要能即時應變,不能當交易日運作。

**成本與安全**
- **零成本**:不改用付費 API(例外:FinMind Sponsor 是 Frank 自己訂的)。AI 用免費額度(Gemini)。
- 金鑰只放 GitHub Secrets / Cloudflare Worker secrets:`FINMIND_TOKEN`、`GEMINI_KEY`、`FRED_API_KEY`、`VAPID_PRIVATE_KEY`、`SB_SERVICE_KEY`、`SB_UID`、`ANTHROPIC_API_KEY` 等。**絕不寫進程式碼或 commit。**
- FinMind 條款:網站不能顯示它的即時資料(只用盤後資料集),要標明來源「FinMind」。
- SEC 抓資料的 User-Agent 用 `klab.research@gmail.com`,不要用 Frank 的個人信箱。
- **法規**:收費提供個股買賣建議需要投顧執照(證券投資信託及顧問法)。Frank 在評估上架收費,**在他確認方向之前不要加任何付費/會員收費功能。**

## 4. 版本號與部署

1. 每次改前端就升版:`rXXXX → rXXXX+1`,**只改這 4 處**:
   - `app.js`:`const APP_BUILD='rXXXX';`
   - `index.html`:`<meta name="build" content="rXXXX">`、`app.css?v=rXXXX`、`app.js?v=rXXXX`
   - ⚠ **不要用全文取代**(`sed s/r1151/r1152/g` 之類):註解裡的歷史版本號會被一起改壞(2026-10-23 曾發生,已用 git 歷史還原 42 處)。
   - 狀態列的「build」標籤會自動讀 `APP_BUILD`,不用另外改。
2. 註解標版本:新改動在程式旁寫 `// r1153:為什麼這樣改(回測數字)`。
3. 推送:`git pull --rebase origin main && git push origin HEAD:main`。被拒(cannot lock ref)就等幾秒再同步重推。
4. commit 訊息用中文,開頭寫版本號,例如 `r1153 錯殺低接…`。
5. GitHub Pages 約 1~2 分鐘生效。Frank 用狀態列的 `build rXXXX` 確認上線。
6. 後台 workflow:很多共用 `concurrency: group: kdata`,避免同時寫資料檔(2026-09 曾因兩個 workflow 同時推造成分片損毀)。新 workflow 會寫 `c/`、`k/` 的話也要用 `kdata`。
7. GitHub 排程常延遲好幾小時甚至整班不跑:**程式不可以用「現在幾點」推斷是哪一班**(例:`market_view.py` 00:00~05:59 一律當前一天晚上版)。`cron_guard.py` 會補點漏跑的排程。

## 5. 改完怎麼驗證(必做)

- 語法:`node -e "new Function(require('fs').readFileSync('app.js','utf8'))"`;Python 用 `python3 -c "import ast;ast.parse(open('x.py').read())"`。
- 實際開頁面:本機起靜態伺服器(要支援 gzip),用 Playwright/Chromium 打開,檢查 console 沒有錯誤、相關區塊有正確內容。
  - 個股頁的區塊是章節式的(`document.documentElement.dataset.chap` = `ov`/`0`/`1`/`2`/`3`),收合的區塊有 `.sec-body.closed`,要先展開才看得到。
  - 美股要先 `setGMKT('US')`。
- **函式在 `try{}catch{}` 裡出錯會被吞掉、整段變空白**(r1144 就這樣讓美股買賣計畫消失 20 分鐘)——改完一定要確認輸出不是空的,不能只看「沒報錯」。

## 6. 回測器(新規則上線前用)

| 檔案 | 用途 | 跑法 |
|---|---|---|
| `short_bt_study.py` | AI Pick 短期清單:完整重現選股+組合績效(年化/回落/最差年) | `python3 short_bt_study.py "<變體名>" …` |
| `plan_bt_study.py` | 個股買賣計畫:事件研究(進場事件 × 出場規則,每筆平均/勝率/獲利因子/正年) | `python3 plan_bt_study.py <mode>` |
| `us_plan_bt_study.py` | 美股版(S&P 500 現成分股,有倖存者偏差) | `python3 us_plan_bt_study.py` |

- 資料:`archive/k/tw`、`archive/inst/tw`、`archive/rev/tw`、`archive/adj_tw.json.gz`(除權息還原);來回成本 0.6%;2016~2026。
- 第一次跑會建快取 pkl(約 400MB,不要 commit)。
- 判斷標準:新做法要在**平均、勝率或獲利因子、正年數**都更好,而且前後半段都成立,才算有效;只有某一項更好的叫「取捨」,交給 Frank 決定。

## 7. 目前有效的規則(都回測過,別隨手改)

- **短期清單**:每週最後交易日收盤選 5 檔(離 52 週高 ≤10% × 強勢訊號綜合分 ≥4,同分低波動優先),下個交易日開盤買,最多 15 日,+20% 停利 / −15% 停損。試過 40 種改法,只有「同分低波動優先」三項同時更好。
- **錯殺低接(台股)**:離 60 日高跌 ≥**40%** 的第一天 → 隔天開盤買,+20% / −15% / 最多 60 天(−30% 只有 +3.2%/54%,−40% +6.4%/63%)。
- **跌深低接(美股)**:離 60 日高跌 ≥**35%** 的第一天 → +30% / −20% / 最多 90 天。
- **通用買賣計畫(台股)**:突破買法只在離 52 週高 ≤10% 有效;停損 = **連續 2 天**收盤跌破季線;一般技術面買進不設固定停利;不加碼;被洗出後再創 52 週新高照買。
- **美股**:位置、均線、KD/RSI、帶量突破等之後 20 天都沒有穩定好壞 → 美股只用跌深低接當買點。
- 大盤濾網(0050 跌破 200 日線不進場)多次驗證**沒用**,不要加。

## 8. 已知地雷

- MIS 即時報價:休市日/開盤前回的是前一交易日資料 → 用報價日期判斷,不能當成今天(r1047)。
- FinMind 全市場季報(只給日期)最新一季可能是**累計數**,要拆成單季(`< 0.85×` 規則)。
- GitHub runner 是淺層 checkout,`git log` 看不到歷史;要歷史用 GitHub API。
- 證交所、櫃買 OpenAPI 常擋 GitHub 的 IP。
- SEC 要合法的聯絡信箱 User-Agent,`github.io` 網域會被拒。
- Cloudflare Worker `/fgl` 只接受帶網站 Origin/Referer 的請求。
- Gemini 回應會被截斷:關閉 thinking(`thinkingBudget: 0`)並檢查完整性。
- ECharts 在 `display:none` 裡初始化寬度是 0,展開時要 `resize`。

## 9. r1153 維護交接（Codex，2026-10-23）

- **接手基準**：r1152，main 提交 `582ca487ebfe03d28235e47612f210e4df580b73`。Claude 接手前先同步最新 main、讀本檔，勿再覆蓋舊交接包；下一次修改以前端實際版本往上升版。
- **修改範圍**：`app.js`（搜尋狀態、鍵盤/中文組字、AI 日期標示、版本）、`app.css`（搜尋無結果提示）、`index.html`（允許縮放、合併重複字型載入、搜尋動態提示與版本）、`sw.js`（離線備援/快取生命週期）、本檔及 `tests/usability-offline.test.cjs`。
- **本批不改**：選股/買賣/評分規則、後台排程、Cloudflare、登入/雲端持股、推播格式、任何歷史或即時資料檔。不存在的日期（例如 10/42）保留原文與新聞來源，只標示待核對，不猜測正確日期。
- **離線行為**：資料檔缺少自己的快取時保留網路失敗，不能用首頁 HTML 冒充 JSON/JS；只有頁面導覽能依序使用 index.html 或 /Stock/ 首頁快取。背景快取更新受 waitUntil 保護；保留原本 stock-pwa-v3 與 5 秒慢網路回快取設定。
- **本機驗證**：`node --test tests/usability-offline.test.cjs` 共 14 項通過（8 項 SW、5 項搜尋、1 項日期）；app.js/sw.js 語法檢查與 git diff --check 通過。已開啟支援 gzip 的本機站，確認 2330/NVDA 搜尋、個股切換、Escape 留在個股、舊清單不殘留、技術章節與無效日期提示；當時擷取的 console error 為空。未驗證真實帳號持股/推播，亦未宣稱在實體手機測過縮放/離線。
- **部署已驗收**：2026-10-23，[PR #3](https://github.com/frankf19-19/Stock/pull/3) 已 squash 合併為 `464dd7e1f82ed077b525d9497d2f59bc1b56fa9a`；[Pages 執行 39941243081](https://github.com/frankf19-19/Stock/actions/runs/39941243081) 成功。正式站 meta/CSS/JS 為 r1153、允許縮放；實測無結果提示、2330/NVDA 個股內容、Escape 留在原個股、清空舊清單與美股技術章節；驗證擷取的 console error 為空。若要回退本批程式，可針對上述 squash commit 使用 `git revert 464dd7e1f82ed077b525d9497d2f59bc1b56fa9a`，先檢查後續修改並同步 main，保留機器人資料提交。
- **回退方式**：針對本批 PR 的程式提交建立 revert，保留後續機器人資料提交；不要 reset/force-push main、不要用舊版整個目錄覆蓋。若已經有後續前端版，先逐段確認差異再回退，避免連帶回退其他 AI 修改。
- **待後續處理**：① app.js 的「市場半年投票」仍以個股對比加權，與第 3 節規則不一致，需依既有研究規則處理，不得自行增加未回測訊號。② fetch_trends.py 的 hist 仍有 [-400:] 截斷；日檔仍保留，應從永久日檔遷移/重建摘要後再調整。③ 前端只檢查日曆合法性，不代表 AI 敘述已驗證，產生端仍需補日期與引用事件對應檢查。

---

## 10. r1154 營運追蹤與永久趨勢（Codex，2026-10-23）

- **基準**：main `e6101b79838da48c1021178852fdcbb2f7cefbb0`。本批經 Frank 要求研究後授權繼續實作與部署；第 9 節待辦①②由本批處理，③事件與引用事實核對仍待後續。
- **半年區塊**：改為「未來半年營運追蹤（參考）」，保留區塊，以本股營收、同季營益率、現金流、估值、法人、大戶與自身價格回顧列已知資料及下次核對事項。移除對大盤的相對比較及八項升降投票；缺資料明列不足，不當零或判持平。不是半年報酬預測，未新增買賣訊號，原買賣計畫及健診其他列不變。
- **資料來源**：既有 `trends/YYYY-MM-DD.json` 是每日首版，永久保留。本次 7 個日檔逐一核對雜湊完全未變；遷移前 latest（含舊 hist）已備份於 `trends/revisions/2026-10-23/`。已丟失且無原始檔的歷史不憑空補造。
- **新格式**：`trends_history.py` 維護完整 `trends/history.json`，不再截 400 天；`trends.json` 為輕量 v2 衍生檔、不再重複攜帶全 hist。`first_seen` 是全歷史首次，`current_streak_start/current_streak_days` 是本次逐曆日連續，`total_seen_days` 是累計收錄天數。近 14 日以資料最早日期為下限，明列缺檔天數；缺檔中斷連續、不等於趨勢消失。
- **同日重跑**：首次日檔不可覆寫；新版本寫 `trends/revisions/日期/內容雜湊.json`，`trends/active.json` 指向各日有效版本，同日只算一次。可解析的 AI 回應與輸入另存 `trends/raw/日期/內容雜湊.json`（含未達發布數量者）。現有 news workflow 已收錄整個 trends/，不用新增排程。
- **復原**：latest 或索引有問題，先備份現況，再跑 `python fetch_trends.py --rebuild-history`，僅讀永久資料、不呼叫 AI、不需要 requests。一般當日已有首版也直接重建，不重花額度。有效版本索引若格式或路徑錯誤會停止，先核對版本再修復，不要刪除修訂或 raw。索引與 latest 各自原子寫入，非跨檔交易，中斷後可以重建。
- **前端統計**：分開顯示首次、本次連續、累計、近 14 日與缺檔；再出現不標「新」。新增來源依同一 key 的 URL 與所有已存過去日檔去重，只表示新引用網址，不等於新發布新聞或新產業證據。既有無效日期標示保留原文。
- **引用**：新產生趨勢至少兩個有效引用編號，保留全部有效引用；目前仍不能保證兩個獨立事件、來源內容真偽或日期完全正確。key 改名的顯式別名遷移尚未實作，禁止自動模糊合併歷史。
- **驗證**：20 項 Node + 13 項 Python 測試通過，含 502→503 天歷史、缺日、跨年、再出現、同日重跑、壞 latest 重建、越界版本路徑與缺資料判讀。另實際本機 gzip 站確認台股 2330 新區塊完整呈現。執行：`node --test tests/*.test.cjs`、`python -m unittest discover -s tests -p 'test_*.py'`。
- **接手與回退**：Claude 先同步 main 並讀本節。只針對本批程式差異回退，歷史、新增修訂、raw、索引及後續機器人資料一律保留；不要直接整個 PR revert 而刪除新增的資料檔，不要 reset/force-push main。

---

## 11. r1155 個股長期歷史（Codex，2026-10-23）

- Frank 澄清「400 天以上」是指**個股股價／財報**，不是要求補造 400 份產業趨勢日報。第 10 節的 7 天只指 AI 趨勢功能於 2026-10-17 新增後的實際發布紀錄。不要混淆股價、財報與 AI 日報三種歷史。
- r1154 已由 [PR #4](https://github.com/frankf19-19/Stock/pull/4) 合併為 `6b628478bcc1fed2c830867ebe9f798c4a982de8`；[Pages 39945903009](https://github.com/frankf19-19/Stock/actions/runs/39945903009) 成功，正式站半年區塊與趨勢新統計已驗證。
- 真實永久庫：台積電日 K 2012-01-02 起 3,616 筆（截至 2026-10-16），NVDA 2012-01-03 起 3,718 筆（截至 2026-10-15）；近期 k/ 提供較新的交易日。台積電現用季報 2024Q3~2026Q2 共 8 季、月營收現用 28 月，永久月營收自 2011-12 起；美股另有 archive/usf_hist.json.gz。資料不足或新上市不補假值。
- r1155 修正：archDaily 原先僅允許 TW，導致美股「全部」一直只用近期分片。現在依 TW/US 讀各自分年 gzip 永久庫；同日用近期分片優先，排序去重，近期分片沒有資料時仍可讀永久庫。只接圖表 yOHLC，不變更 loadK 或買賣訊號輸入。仍由使用者點「全部」才載長期庫，首頁不整批下載多年資料。
- K 線標示筆數、起訖與跨曆日數；日 K 根數是交易日，不能把 400 曆日當成 400 根。原來「全部」的深度提醒誤寫 all，已改對應實際 max。
- 本機 gzip 實測：台積電「全部」3,620 根、2012-01-02~2026-10-22（5,408 曆日）；NVDA 3,723 根、2012-01-03~2026-10-22（5,407 曆日）。近期資料已併入永久庫，無假造日 K。
- 現存待辦：backfill_k.py 雖寫 KEEP_BARS=780/TARGET=760，但 MONTHS=14，且 save_all 用舊單字首分片命名；不能直接啟動舊回補 workflow 來宣稱補足三年。應先改成依現行分片與並行鎖、優先永久庫、確認還原口徑後再動後台。現有 8 季已超過 400 曆日，不應把財報補成每日重複數字。
- 測試：新增 tests/long-history.test.cjs 7 項（台美分片路徑、排序去重、近期同日優先、無近期分片、同長度補早期、壞資料與圖表隔離）；共 27 Node + 13 Python 測試。

---

## 交接紀錄(每次推上去加一行,新的放最上面)

| 日期 | 版本 | 誰 | 改了什麼 |
|---|---|---|---|
| 2026-10-23 | r1155 | Codex | 釐清個股歷史超過400天需求；美股全部日/週K接2012起永久庫，近期資料優先合併、顯示曆日跨度；7項新增測試，原訊號輸入不變 |
| 2026-10-23 | r1154 | Codex | 半年改本股營運追蹤、移除大盤投票；永久趨勢索引、嚴格逐日統計、不可變修訂與免 AI 重建；既有 7 日檔不變、33 項測試通過 |
| 2026-10-23 | r1153 驗收 | Codex | PR #3 已合併、Pages 成功，正式站搜尋/台美股個股/Escape/錯誤紀錄已驗收；第 9 節補記部署提交與精確回退方式 |
| 2026-10-23 | r1153 | Codex | 搜尋無結果/舊清單/Escape/中文組字修正;允許放大、移除重複字型;離線資料與網頁備援分流、快取更新生命週期;AI 無效日期標示;14 項回歸測試 |
| 2026-10-23 | r1152 | Claude | 推播標題股票名稱移到最前面;新增本檔 |
| 2026-10-23 | r1150~1151 | Claude | 股癌重點不見修正 + 每集永久保留(救回 31 集);build 標籤改讀 APP_BUILD |
| 2026-10-23 | r1149 | Claude | 颱風假自動偵測、休市日各處正確顯示 |
| 2026-10-23 | r1143~1148 | Claude | 錯殺低接 −40%、季線停損連 2 天、美股跌深 −35%、自由現金流欄位修正 |
