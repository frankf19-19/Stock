# AGENTS.md — K研所 交接說明(給所有 AI 工具:Claude、GPT/Codex、Copilot…)

> 任何 AI 接手這個 repo 前,**先整份讀完**。這裡的規則優先於你自己的習慣。
> 擁有者:Frank(不寫程式,全部實作交給 AI;溝通一律**繁體中文**、白話)。
> 最後更新:2026-10-23(r1152)。改了架構或規則請同步更新本檔。

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

---

## 交接紀錄(每次推上去加一行,新的放最上面)

| 日期 | 版本 | 誰 | 改了什麼 |
|---|---|---|---|
| 2026-10-23 | r1152 | Claude | 推播標題股票名稱移到最前面;新增本檔 |
| 2026-10-23 | r1150~1151 | Claude | 股癌重點不見修正 + 每集永久保留(救回 31 集);build 標籤改讀 APP_BUILD |
| 2026-10-23 | r1149 | Claude | 颱風假自動偵測、休市日各處正確顯示 |
| 2026-10-23 | r1143~1148 | Claude | 錯殺低接 −40%、季線停損連 2 天、美股跌深 −35%、自由現金流欄位修正 |
