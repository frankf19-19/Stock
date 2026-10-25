const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8'),core=source.slice(source.indexOf('function strategyNumber('),source.indexOf('function refreshStrategySummaries('));
function ctx(){const c={newsEsc:x=>String(x).replace(/</g,'&lt;'),a3TiersOf:()=>[],ADJ1:{}};vm.createContext(c);vm.runInContext(core,c);return c;}
const dates=Array.from({length:270},(_,i)=>new Date(Date.UTC(2025,0,1+i)).toISOString().slice(0,10)),bars=dates.map(()=>[100,120,98,100,1e6]),tw={id:'2330',name:'台積電',market:'TW',price:100};
test('主畫面先列股票名稱與每股價格，研究指標不搶版面',()=>{const h=ctx().ownStrategySummary(tw,bars,dates,false,null),main=h.split('<details')[0];assert.match(main,/台積電（2330）/);assert.match(main,/100 元／股/);assert.match(main,/最新可用報價/);assert.doesNotMatch(main,/ATR|0 筆|完整跌深交易/);});
test('兩種買法各自說明價格用途，低接門檻不叫合理價',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,false,null);assert.match(h,/買法一/);assert.match(h,/跌到多少可以買/);assert.match(h,/72 元／股/);assert.match(h,/不是合理價、目標價/);assert.match(h,/盤中碰到就買/);});
test('成本80的低接停損68、停利96，沒有用現價100重算',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,true,80);assert.match(h,/68 元／股/);assert.match(h,/96 元／股/);assert.doesNotMatch(h,/85 元／股|120 元／股<\/strong>（成本上方/);});
test('未持有的停損停利須明列假設基準；技術突破不虛構固定停利',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,false,null);assert.match(h,/停損／停利先按買在/);assert.match(h,/實際成交後按成本重算/);assert.match(h,/沒有固定停利價/);assert.doesNotMatch(h,/停損為 <strong>/);});
test('美股只有已驗證跌深買法，不混入台股技術出場',()=>{const h=ctx().strategyPlainHTML({...tw,id:'NVDA',name:'Nvidia',market:'US'},bars,dates,false,null);assert.match(h,/78 美元／股/);assert.doesNotMatch(h,/買法一|連續2天收盤都低於/);});
test('模型、研究及完整規則預設收合，數字與原紀錄仍保留',()=>{const h=ctx().ownStrategySummary(tw,bars,dates,false,null);assert.match(h,/AI 模擬帳戶怎麼做/);assert.match(h,/價格起伏與歷史研究/);assert.match(h,/完整規則與條件檢核/);assert.doesNotMatch(h,/<details[^>]*\sopen[ >]/);assert.match(h,/平均真實波幅/);});
test('風險統計金額直接說明不是股價或買賣價格',()=>{const h=ctx().stockProfileHTML(tw,bars,dates,false,null,new Date('2026-10-25T12:00Z'));assert.match(h,/不是台積電的股價/);assert.match(h,/不是買進、停損或停利價/);});

test('台積電示例依可交易價格列出1550假設買價與1315／1860出場價',()=>{const c=ctx(),b=dates.map(()=>[2385,2590,2380,2385,1e6]),h=c.strategyPlainHTML({...tw,price:2385},b,dates,false,null);assert.match(h,/1,550 元／股/);assert.match(h,/1,315 元／股/);assert.match(h,/1,860 元／股/);assert.match(h,/等待/);assert.match(h,/首次收盤跌到/);assert.match(h,/只在條件成立後執行/);});
test('創高進場價須嚴格高於前高且符合台股價格跳動',()=>{const c=ctx();assert.equal(c.strategyBreakPrice(2590),2595);assert.equal(c.strategyBreakPrice(50),50.1);assert.equal(c.strategyBreakPrice(null),null);});
test('實際成本只套該筆價格；不使用現價或模型成本',()=>{const c=ctx(),p=c.strategyDipPricePlan(tw,2000,true);assert.equal(p.entry,2000);assert.equal(p.stop,1700);assert.equal(p.target,2400);assert.equal(p.actual,true);assert.equal(p.hold,60);});
test('美股價格計畫保留20／30／90及美分價格',()=>{const c=ctx(),p=c.strategyDipPricePlan({market:'US'},158.19);assert.equal(p.stop,126.55);assert.equal(p.target,205.65);assert.equal(p.hold,90);assert.equal(p.actual,false);});
test('未成交的低接門檻不因四捨五入提高到真實觸發價以上',()=>{const c=ctx(),b=dates.map(()=>[100,120.007,98,100,1e6]),h=c.strategyPlainHTML({...tw,market:'US'},b,dates,false,null);assert.match(h,/78 美元／股/);assert.doesNotMatch(h,/78.01 美元／股/);});
test('缺成本或無效數字不產生假價格',()=>{const c=ctx();for(const x of [null,0,-1,NaN,Infinity])assert.equal(c.strategyDipPricePlan(tw,x),null);});

test('主畫面直接回答跌到多少買，創高改成另一套收合策略',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,false,null),main=h.slice(h.indexOf('original-dip-plan')).split('<details')[0];assert.match(main,/首次收盤跌到 72 元／股 以下，下一交易日開盤買入/);assert.match(main,/跌到多少停損/);assert.match(main,/漲到多少停利/);assert.doesNotMatch(main,/進場觀察／假設買價|買法一|未成交試算/);assert.match(h,/另一種策略：向上創高才買/);});
test('目前100、買入價72，清楚說還要跌28元及28%',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,false,null);assert.match(h,/還要再跌 28 元／股（28.0%）/);});
test('買入價格依每檔自己的價格歷史計算，不使用同一固定金額',()=>{const c=ctx(),a=c.strategyPlainHTML(tw,bars,dates,false,null),b=c.strategyPlainHTML({...tw,id:'TEST',price:200},bars.map(x=>x.map((v,i)=>i<4?v*2:v)),dates,false,null);assert.match(a,/72 元／股 以下/);assert.match(b,/144 元／股 以下/);});
test('已在跌深區但非首次達價不重複買入',()=>{const b=bars.map(x=>x.slice());[100,90,82,75,70,70].forEach((v,i)=>{b[b.length-6+i]=[v,120,v-2,v,1e6];});const h=ctx().strategyPlainHTML({...tw,price:70},b,dates,false,null);assert.match(h,/這次不是首次達價，不重複買入/);assert.match(h,/已到此價以下/);});
