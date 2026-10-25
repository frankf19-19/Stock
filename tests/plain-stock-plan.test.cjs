const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8'),core=source.slice(source.indexOf('function strategyNumber('),source.indexOf('function refreshStrategySummaries('));
function ctx(){const c={newsEsc:x=>String(x).replace(/</g,'&lt;'),a3TiersOf:()=>[],ADJ1:{}};vm.createContext(c);vm.runInContext(core,c);return c;}
const dates=Array.from({length:270},(_,i)=>new Date(Date.UTC(2025,0,1+i)).toISOString().slice(0,10)),bars=dates.map(()=>[100,120,98,100,1e6]),tw={id:'2330',name:'台積電',market:'TW',price:100};
test('主畫面先列股票名稱與每股價格，研究指標不搶版面',()=>{const h=ctx().ownStrategySummary(tw,bars,dates,false,null),main=h.split('<details')[0];assert.match(main,/台積電（2330）/);assert.match(main,/100 元／股/);assert.match(main,/最新可用報價/);assert.doesNotMatch(main,/ATR|0 筆|完整跌深交易/);});
test('兩種買法各自說明價格用途，低接門檻不叫合理價',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,false,null);assert.match(h,/買法一/);assert.match(h,/買法二/);assert.match(h,/72 元／股/);assert.match(h,/不是合理價、目標價/);assert.match(h,/盤中碰到就買/);});
test('成本80的低接停損68、停利96，沒有用現價100重算',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,true,80);assert.match(h,/68 元／股/);assert.match(h,/96 元／股/);assert.doesNotMatch(h,/85 元／股|120 元／股<\/strong>（成本上方/);});
test('未持有不虛構停損停利；技術突破不虛構固定停利',()=>{const h=ctx().strategyPlainHTML(tw,bars,dates,false,null);assert.match(h,/需要你的實際買進成本/);assert.match(h,/沒有固定停利價/);assert.doesNotMatch(h,/停損為 <strong>/);});
test('美股只有已驗證跌深買法，不混入台股技術出場',()=>{const h=ctx().strategyPlainHTML({...tw,id:'NVDA',name:'Nvidia',market:'US'},bars,dates,false,null);assert.match(h,/78 美元／股/);assert.doesNotMatch(h,/買法一|連續2天收盤都低於/);});
test('模型、研究及完整規則預設收合，數字與原紀錄仍保留',()=>{const h=ctx().ownStrategySummary(tw,bars,dates,false,null);assert.match(h,/AI 模擬帳戶怎麼做/);assert.match(h,/價格起伏與歷史研究/);assert.match(h,/完整規則與條件檢核/);assert.doesNotMatch(h,/<details[^>]*\sopen[ >]/);assert.match(h,/平均真實波幅/);});
test('風險統計金額直接說明不是股價或買賣價格',()=>{const h=ctx().stockProfileHTML(tw,bars,dates,false,null,new Date('2026-10-25T12:00Z'));assert.match(h,/不是台積電的股價/);assert.match(h,/不是買進、停損或停利價/);});
