const test=require('node:test'),assert=require('node:assert/strict'),S=require('../stock_card_summary.js');
function fixture({warning='',state='',market='',conditional=false}={}){
 const el=(text='',q={},all={},dataset={})=>({textContent:text,dataset,querySelector:k=>q[k]||null,querySelectorAll:k=>all[k]||[]});
 const row=(label,value,how)=>el('',{'.pbx-l':el(label),'.pbx-v':el(value),'.pbx-how':el(how)}),rows=[row('買進','2,595','11/02 收盤站上這個價 → 11/03 開盤買'),row('防守','2,205','買進價 −15%,碰到就賣'),row('賣出',conditional?'2,205':'3,375',conditional?'連續 2 天收盤跌破各日季線，下一交易日開盤全數賣出':'買進價 +30%,最多抱 90 個交易日')];
 const col=el('',{'.pbx-h':el('突破買法'),'.pbx-st':el(state)},{'.pbx-r':rows,'.pbx-cond':market?[el('大盤有沒有一起跌：'+market)]:[]}),box=el('',{'.pbx-col':col,':scope > .pbx-st':el(warning),'.pbx-asof':el('價格條件用 2026-10-30 收盤算')}),root=el('',{},{},{id:'2330',strategy:'TW'}),content=el('',{'.strategy-summary':root,'.pbx':box});return {createElement:()=>({set innerHTML(x){},content})};
}
test('短卡沿用原三價及收盤時間，不帶研究折疊與長表',()=>{const m=S.fromHTML('',fixture()),h=S.render(m);assert.equal(m.buy,'2,595');assert.equal(m.stop,'2,205');assert.equal(m.sell,'3,375');assert.match(h,/11\/02 收盤站上/);assert.match(h,/href="#stock\/2330"/);assert.doesNotMatch(h,/<details|<table|回測|勝率/);});
test('資料過期或市場不符優先於已確認，不把精簡變成立刻買進',()=>{assert.match(S.fromHTML('',fixture({warning:'資料未更新',state:'✅ 已確認'})).action,/先不買/);assert.match(S.fromHTML('',fixture({market:'現在不買',state:'✅ 已確認'})).action,/先不買/);assert.match(S.fromHTML('',fixture({state:'訊號已過期，不追'})).action,/過期/);});
test('季線退出保留條件，不把同一季線值誤稱固定停利',()=>{const m=S.fromHTML('',fixture({conditional:true}));assert.equal(m.sell,'跌破季線才賣');assert.match(m.exit,/連續2日.*下一交易日開盤/);assert.doesNotMatch(S.render(m),/賣出<\/dt><dd>2,205/);});
test('短卡文字逃逸且連結編碼，不把來源說明當HTML執行',()=>{const h=S.render({id:'A/B',market:'US',action:'<img src=x onerror=alert(1)>',buy:'$123.45'});assert.doesNotMatch(h,/<img/);assert.match(h,/&lt;img/);assert.match(h,/#stock\/A%2FB/);assert.match(h,/\$123\.45/);});
test('AI模型只留狀態，不混入模型買價或長篇紀錄',()=>{assert.equal(S.ai('持有中 買2420；下一交易日開盤賣出'),'AI Pick：準備賣掉，詳見個股');assert.equal(S.ai('持有中 買2420'),'AI Pick：目前有買（跟你的持股無關）');assert.equal(S.ai('沒有買進訊號'),'AI Pick：暫無買進訊號');assert.doesNotMatch(S.ai('持有中 買2420'),/2420/);});
test('結構摘要分清止跌失效、反彈與破底觀察，不宣稱一定落底',()=>{
 const text=t=>({textContent:t}),row=(name,price)=>({querySelector:k=>k==='dt'?text(name):text(price)});
 const q=stage=>({querySelector:()=>({querySelector:()=>({dataset:{bottomStage:stage}}),querySelectorAll:()=>[row('下次站回10日線價','2,420 元／股'),row('下次底部突破價','2,595 元／股'),row('初步止跌固定警戒','2,300 元／股')]})});
 const failed=S.insights(q('failed'));assert.match(failed[0].text,/止跌失敗/);assert.match(failed[2].text,/已跌破 2,300/);assert.match(S.insights(q('breakout'))[0].text,/不代表最低點一定過了/);assert.match(S.insights(q('neutral'))[0].text,/不用看落底/);assert.deepEqual(S.insights(q('unavailable')),[]);
 assert.match(S.render({id:'2330',insights:failed}),/漲過 2,595/);
});
test('逐筆模型策略沿原停損停利，長期不冒充自動賣出，排定出場優先',()=>{
 const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(require.resolve('../app.js'),'utf8');
 const ctx={StockCardSummary:S,newsEsc:String,AIPK:null,a3TiersOf:()=>[{k:'short',sl:{st:'hold',entry:100,days:5,x_open:true}},{k:'long',sl:{st:'hold',entry:100,lv:{sl:90,tp:150}}}]};vm.createContext(ctx);
 vm.runInContext(source.slice(source.indexOf('function strategyNumber('),source.indexOf('function aipHydrateWeekly(')),ctx);
 vm.runInContext(source.slice(source.indexOf('function compactAIPick('),source.indexOf('function favKbSplit(')),ctx);
 const h=ctx.compactAIPick({id:'2330',market:'TW'},{txt:'持有中'});assert.match(h,/短期：下個交易日開盤賣/);assert.match(h,/跌破 85 賣、漲到 120 賣/);assert.match(h,/最多再抱10個交易日/);assert.match(h,/長期：還抱著｜每季檢查一次/);assert.match(h,/90／150 只是參考價，不會自動賣/);assert.doesNotMatch(h,/買100/);
 ctx.a3TiersOf=()=>[];ctx.AIPK={trader:{pv:{rules:{stop_atr:null,sell_rank:200},pos:[{id:'2330',stop:null,tp:3187.5}],pend:[{id:'2330',act:'sell'}]}}};const pv=ctx.compactAIPick({id:'2330',market:'TW'},{});assert.match(pv,/下個交易日開盤賣/);assert.doesNotMatch(pv,/跌破/);assert.match(pv,/前200名/);assert.doesNotMatch(pv,/待資料/);ctx.a3TiersOf=()=>[{k:'mid',sl:{st:'pend',sel_px:200,sl_r:.1,tp_r:.4,hold_r:60}}];
 const us=ctx.compactAIPick({id:'AAPL',market:'US'},{txt:'待成交'});assert.match(us,/跌破 \$180 賣、漲到 \$280 賣/);assert.match(us,/最多抱60個交易日/);assert.match(us,/買到後價位會重算/);
});

test('美股未列入清單與沒有持有文字，不誤判成模型持股',()=>{assert.equal(S.ai('不在美股三清單內(AI交易員目前也沒有持有這檔)'),'AI Pick：未列入美股三清單');});
