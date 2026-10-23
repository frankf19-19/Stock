const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const helper=app.slice(app.indexOf('function outlookObservation('),app.indexOf('async function fundAlertUI('));
const meta=app.slice(app.indexOf('function trendHistoryLabel('),app.indexOf('function trendsRender('));
const ctx={newsEsc:s=>String(s)};vm.createContext(ctx);vm.runInContext(helper+meta,ctx);
test('資料全缺不視為持平或看升',()=>{
 const o=ctx.outlookObservation({},null,null);
 assert.match(o.title,/資料不足/);assert.doesNotMatch(o.title,/持平|看升|看降/);
});
test('null 與空值不能當作零營收',()=>{
 const o=ctx.outlookObservation({pe:null},{ry:[10,null],om:[null],ocfr:null},null);
 assert.match(o.title,/資料不足/);assert.equal(o.lines.some(x=>x.startsWith('📈')),false);
});
test('營運與價格只是自身事實,不讀取大盤或計升降票',()=>{
 const o=ctx.outlookObservation({pe:20},{rm:['2026-08','2026-09'],ry:[40,20],fq:['2025Q2','2026Q1','2026Q2'],om:[10,13,12]},null);
 assert.match(o.lines.join(' '),/變化 -20/);
 assert.match(o.lines.join(' '),/去年同季 \+2/);
 assert.doesNotMatch(o.title,/看升|看降|多空拉鋸/);
 assert.doesNotMatch(helper,/yextData|\^TWII|oUp|oDn/);
});
test('法人缺一類資料不補零,不捏造合計',()=>{
 const o=ctx.outlookObservation({}, {f:Array(40).fill(1)},null);
 assert.equal(o.lines.some(x=>x.startsWith('🏦')),false);
 assert.match(o.lines.join(' '),/完整三大法人/);
});
test('重新出現與首次分開標示',()=>{
 const a={first_seen:'2026-10-17',current_streak_days:1,total_seen_days:5,window_days:7,seen_last_14_days:5,missing_days:1,new_source_count:0};
 const result=ctx.trendHistoryLabel(a,{date:'2026-10-23'});
 assert.match(result,/再度收錄/);assert.doesNotMatch(result,/首次收錄/);assert.match(result,/缺 1 天/);
});
test('連續起日使用本次起日,不冒用歷史首次',()=>{
 const result=ctx.trendHistoryLabel({first_seen:'2025-01-01',current_streak_days:2,current_streak_start:'2026-10-22',total_seen_days:50,window_days:14,seen_last_14_days:2,missing_days:0},{date:'2026-10-23'});
 assert.match(result,/本次連續 2 天（自 10\/22）/);
});
