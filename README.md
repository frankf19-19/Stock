# 三力選股儀表板

產業前景 × 基本面 × 籌碼面 × 技術線型|台股為主、美股為輔。
靜態網頁 + GitHub Actions 自動更新,部署在 GitHub Pages。

## 部署步驟(一次搞定,約 5 分鐘)

### 1. 建立 repo 並推上去
到 GitHub 建一個新 repo(例如 `stock-radar`,設 **Public**,Pages 免費版需要公開),然後:

```bash
cd stock-radar          # 這個資料夾
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的帳號/stock-radar.git
git push -u origin main
```

### 2. 開啟 Actions 寫入權限(重要!)
Repo → **Settings → Actions → General → Workflow permissions**
→ 勾選 **Read and write permissions** → Save。
(沒開這個,機器人無法 commit data.json)

### 3. 等第一次自動更新完成
Push 之後到 **Actions** 分頁,會看到 `daily-update` 正在跑(約 2–3 分鐘),
跑完會自動 commit 一個 `data.json` —— 這就是真實數據。

### 4. 開啟 GitHub Pages
Repo → **Settings → Pages** → Source 選 **Deploy from a branch**
→ Branch 選 `main` / `(root)` → Save。
一兩分鐘後網址就是:`https://你的帳號.github.io/stock-radar/`

打開網頁,右上角徽章應顯示綠色「**即時數據**」。

### 5.(選用)FinMind Token
免費註冊 https://finmindtrade.com 取得 token,可提高 API 流量上限:
Repo → Settings → Secrets and variables → Actions → New repository secret
→ Name 填 `FINMIND_TOKEN`,Value 貼 token。沒設也能跑,只是流量上限較低。

## 更新機制總覽

| 機制 | 時機 | 內容 |
|---|---|---|
| `update.yml` | 每次 push + 每交易日 19:30 | 基本面、籌碼、K線、新聞、匯率(完整) |
| `update_quotes.yml` | 開盤 09:00–13:50 每 10 分鐘 | 盤中成交價、漲跌幅、加權指數(輕量) |
| 網頁「↻ 更新資訊」按鈕 | 手動 | 重抓 data.json + 證交所/櫃買收盤 + 即時匯率 |
| 網頁自動輪詢 | 開盤時段每 3 分鐘 | 自動重抓 data.json、重算機會雷達 |

## 常見問題

**Q:本機雙擊 index.html 顯示「範例資料」?**
正常。瀏覽器禁止 `file://` 讀取本地 data.json。推上 GitHub Pages(或本機
`python -m http.server` 後開 http://localhost:8000)就會讀到真實數據。

**Q:盤中報價會延遲多久?**
GitHub Actions 排程本身可能延遲數分鐘,實際約 10–15 分鐘更新一次;
GitHub Pages CDN 另有最多約 10 分鐘快取。等級是「盤中雷達」,
不是逐筆報價——秒級行情請開 XQ。

**Q:想加/減股票?**
編輯 `update_data.py` 開頭的 `UNIVERSE` 清單(代號、名稱、產業、論點),
push 後自動生效。

**Q:Actions 排程沒準時跑?**
GitHub 對閒置 repo 的排程會降頻,偶爾手動進 Actions 按 Run workflow 可保持活躍;
repo 60 天無 commit 會自動停用排程(本專案每天自動 commit,通常不會遇到)。

## 免責聲明
本專案為個人研究工具,所有評分與訊號皆為規則化資料整理,
不構成任何投資建議。投資一定有風險,交易前請自行判斷並負責。
