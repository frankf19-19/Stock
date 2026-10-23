const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('app.js','utf8');
const helper=src.slice(src.indexOf('function mergePriceHistory('),src.indexOf('const ARCHK='));
function merge(a,b){const c={};vm.createContext(c);vm.runInContext(helper,c);return JSON.parse(JSON.stringify(c.mergePriceHistory(a,b)));}
test('長期資料排序去重且近期同日價格優先',()=>{const r=merge({dates:['2026-10-22'],ohlc:[[1,3,1,3,8]]},{d:['2012-01-03','2026-10-22'],o:[[1,2,1,2,5],[1,2,1,2,6]]});assert.deepEqual(r.dates,['2012-01-03','2026-10-22']);assert.equal(r.ohlc[1][3],3);});
test('近期分片缺少時仍可展示永久歷史',()=>assert.equal(merge(null,{d:['2012-01-03'],o:[[1,2,1,2,5]]}).dates[0],'2012-01-03'));
test('同樣筆數的永久庫仍能補較早日期,不以筆數決定',()=>assert.equal(merge({dates:['2026-10-22'],ohlc:[[1,2,1,2,5]]},{d:['2012-01-03'],o:[[1,2,1,2,5]]}).dates.length,2));
test('壞收盤與無日期資料不冒充歷史',()=>assert.deepEqual(merge(null,{d:['2012-01-03','bad'],o:[[1,2,1,null,5],[1,2,1,2,5]]}),null));
for(const [market,id,sh] of [['TW','2330','23'],['US','NVDA','n']])test(market+' 全部日K讀取正確永久分片',async()=>{const urls=[];const c={Date,DecompressionStream:function(){},twShardKey:()=>sh,fetch:async u=>{urls.push(u);return {ok:false};}};vm.createContext(c);vm.runInContext(src.slice(src.indexOf('const ARCHK='),src.indexOf('const MCACHE=')),c);await c.archDaily({market,id});assert.ok(urls.length>10);assert.ok(urls.every(u=>u.startsWith('archive/k/'+market.toLowerCase()+'/')&&u.endsWith('/'+sh+'.json.gz')));});
test('永久庫讀取只接在圖表,loadK保留現有訊號輸入',()=>{const y=src.slice(src.indexOf('async function yOHLC('),src.indexOf('function mergePriceHistory('));assert.match(y,/range==='max'/);assert.match(y,/mergePriceHistory\(base,await archDaily\(s\)\)/);const l=src.slice(src.indexOf('async function loadK('),src.indexOf('async function loadK(')+11000);assert.doesNotMatch(l,/archDaily\(/);});
