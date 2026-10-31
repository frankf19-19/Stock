const test=require('node:test'),assert=require('node:assert/strict'),L=require('../site_layout.js'),S=require('../stock_card_summary.js');
class Element{
 constructor(tag,doc){this.tagName=tag;this.ownerDocument=doc;this.children=[];this.dataset={};this.listeners={};this.open=false;}
 append(...els){for(const el of els){if(el.parentElement)el.parentElement.children.splice(el.parentElement.children.indexOf(el),1);el.parentElement=this;this.children.push(el);}}
 before(el){const p=this.parentElement;if(el.parentElement)el.parentElement.children.splice(el.parentElement.children.indexOf(el),1);p.children.splice(p.children.indexOf(this),0,el);el.parentElement=p;}
 addEventListener(k,f){this.listeners[k]=f;}
 contains(el){return this.children.includes(el)||this.children.some(c=>c.contains(el));}
 querySelectorAll(){return this.children.flatMap(c=>[...(c.dataset.layoutFold?[c]:[]),...c.querySelectorAll()]);}
}
const fixture=()=>{const doc={createElement:tag=>new Element(tag,doc)},root=doc.createElement('root'),original=doc.createElement('chart');original.id='same-chart';original.onclick=()=>42;root.append(original);return {doc,root,original};};
test('整理移動原節點，既有圖表、ID、事件與資料仍是同一份',()=>{const {root,original}=fixture(),callback=original.onclick,d=L.fold(original,'詳細資料','move-test');assert.equal(root.children.length,1);assert.equal(d.children[1],original);assert.equal(original.onclick,callback);assert.equal(original.onclick(),42);assert.equal(original.id,'same-chart');assert.equal(d.open,false);assert.equal(L.fold(original,'詳細資料','move-test'),d);assert.equal(d.children.length,2);});
test('重繪保留使用者已展開的研究，不把價格更新變成關閉詳情',()=>{const {root,original}=fixture(),d=L.fold(original,'研究','remember-test');d.open=true;L.remember(root);const next=fixture();assert.equal(L.fold(next.original,'研究','remember-test').open,true);});
test('買賣總覽與最愛三價相同，總覽跳完整計畫而非連回自己',()=>{const m={id:'2330',market:'TW',buy:'2,595',stop:'2,205',sell:'3,375',action:'等待確認',condition:'11/02 收盤確認'},brief=S.render(m,{overview:true}),card=S.render(m);for(const price of ['2,595','2,205','3,375']){assert.ok(brief.includes(price));assert.ok(card.includes(price));}assert.match(brief,/data-card-view="overview"/);assert.match(brief,/data-stock-section="stk_k"/);assert.doesNotMatch(brief,/href="#stock\/2330"/);assert.match(card,/href="#stock\/2330"/);});
test('個股總覽不用另一檔的baseK，報告與各章仍能找到',()=>{const fs=require('fs'),src=fs.readFileSync(require.resolve('../app.js'),'utf8'),fn=src.slice(src.indexOf('function refreshStockBrief('),src.indexOf('function refreshStrategySummaries('));assert.doesNotMatch(fn,/:baseK/);assert.match(fn,/m.id!==s.id\|\|m.market!==s.market/);assert.match(src,/\['stk_ai','stk_3','stk_m','stk_rpt','stk_p','stk_e'\]/);assert.match(src,/選擇本頁區塊/);assert.match(src,/aria-expanded/);});
