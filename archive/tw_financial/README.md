# 台股長期財報原始來源

FinMind 個股三大報表完整回應，查詢自2015-01-01起。金額單位為新台幣元，EPS為每股元；date為季末，並非公告時間。

raw/<股票>/<報表>/<SHA256>.json.gz 為不可變的來源回應，SHA256核對解壓後排序JSON位元組。versions保存替換前的衍生資料，indexes保存每輪開始前的全市場進度。

資料與修訂永久保留於公開GitHub。_config.yml排除此目錄的網站發布，網站僅讀fundamentals/tw個股衍生檔，以控制Pages容量；原始來源仍可從GitHub下載。

參考文件：https://finmind.github.io/tutor/TaiwanMarket/Fundamental/

損益表單季、資產負債季末、現金流年初累計；不能通用差分。來源可能修訂、缺季或只有半年報；衍生資料如實留空。沒有公告時刻，pit_eligible=false，不接歷史選股／AI Pick回測。
