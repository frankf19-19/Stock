const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8');
function ctx(){const c={irEsc:v=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),irFileForm:()=>'',mdLite:s=>s};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function irToneBadge('),source.indexOf('function irHistoryHTML(')),c);return c;}
function facts(summary,refs=[{k:'第三季營收(美元十億元)',v:'46.72'}]){return {numbers:refs,summary};}
const tsmc=()=>JSON.parse(fs.readFileSync('ir/2330.json','utf8')).conf.find(c=>c.ai).ai;
test('真實台積電摘要的十倍單位差異能被指出，原文不改寫',()=>{const c=ctx(),a=tsmc(),before=JSON.stringify(a),xs=c.irAiUnitIssues(a);assert.ok(xs.some(x=>x.text.includes('46.72')&&x.ratio===0.1));assert.ok(xs.some(x=>x.text.includes('1,494.24')&&x.ratio===0.1));const h=c.irAiUnitAuditHTML(a);assert.match(h,/金額單位需核對/);assert.match(h,/尚未核對原始簡報/);assert.equal(JSON.stringify(a),before);});
test('正確換算不同數字與原單位都不誤報',()=>{const c=ctx();assert.equal(c.irAiUnitIssues(facts('營收為美元467.2億元')).length,0);assert.equal(c.irAiUnitIssues(facts('營收為美元46.72十億元')).length,0);});
test('同值不同幣別或不同科目不嫁接比較',()=>{const c=ctx();assert.equal(c.irAiUnitIssues(facts('營收為新台幣46.72億元')).length,0);assert.equal(c.irAiUnitIssues(facts('淨利為美元46.72億元')).length,0);});
test('表格同科目同值有兩種單位時不猜哪個才對',()=>{const c=ctx();assert.equal(c.irAiUnitIssues(facts('營收為美元46.72百萬元',[{k:'營收(美元十億元)',v:'46.72'},{k:'營收(美元億元)',v:'46.72'}])).length,0);});
test('表格值本身含單位與英文字百萬也能核對',()=>{const c=ctx();assert.equal(c.irAiUnitIssues(facts('營收為美元46.72億元',[{k:'營收',v:'USD46.72 billion'}])).length,1);assert.equal(c.irAiUnitIssues(facts('Revenue was USD46.72 billion',[{k:'Revenue (USD million)',v:'46.72'}])).length,1);});
test('金額後置幣別能讀取，完整千分位不可讀成子數字',()=>{const c=ctx();const m=c.irMoneyMentions('營收為1,494.24億美元');assert.equal(m.length,1);assert.equal(m[0].value,1494.24);assert.equal(m[0].currency,'USD');});
test('百分比、每股元、日期和沒有明確幣別不當金額衝突',()=>{const c=ctx();assert.equal(c.irAiUnitIssues(facts('毛利率46.72%，EPS46.72元，營收46.72億元')).length,0);assert.equal(c.irAiUnitIssues(facts('營收成長46.72%')).length,0);assert.equal(c.irAiUnitIssues({numbers:[{k:'EPS(美元)',v:'46.72'}],summary:'EPS美元46.72元'}).length,0);});
test('缺資料不生成通過驗證徽章，也不憑空補數字',()=>{const c=ctx();assert.equal(c.irAiUnitIssues({}).length,0);assert.equal(c.irAiUnitAuditHTML({}), '');});
test('提示轉義來源文字，不能插入HTML',()=>{const c=ctx(),a=facts('營收為美元46.72億元',[{k:'<script>營收(美元十億元)</script>',v:'46.72'}]);assert.doesNotMatch(c.irAiUnitAuditHTML(a),/<script>/);assert.match(c.irAiUnitAuditHTML(a),/&lt;script&gt;/);});
test('正面與成長動能用紅色，保守與風險用綠色',()=>{const c=ctx();assert.match(c.irToneBadge('正面'),/var\(--up\)/);assert.match(c.irToneBadge('保守'),/var\(--down\)/);const h=c.irAiHTML({ai:{drivers:['需求改善'],risks:['匯率風險']}},{});assert.match(h,/color:var\(--up\)">🚀 成長動能/);assert.match(h,/color:var\(--down\)">⚠️ 風險/);});
test('有單位差異時仍保留完整摘要、表格與全文',()=>{const c=ctx(),a=tsmc(),h=c.irAiHTML({d:'2026-10-15',ai:a},{});assert.ok(h.includes(c.irEsc(a.summary)));assert.match(h,/簡報關鍵數字/);assert.match(h,/深度分析全文/);assert.match(h,/金額單位需核對/);});
