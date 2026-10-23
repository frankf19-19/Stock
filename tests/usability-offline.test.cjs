const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'..');
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');

function swHarness({entries={},fetcher=async()=>{throw Error('offline')},put=async()=>{}}={}){
  const events={},timers=[],life=[];
  const cache={match:async key=>entries[key],put};
  vm.runInNewContext(fs.readFileSync(path.join(root,'sw.js'),'utf8'),{
    self:{addEventListener:(name,fn)=>events[name]=fn},
    location:{origin:'https://example.test'},URL,Response,
    caches:{open:async()=>cache},
    fetch:fetcher,setTimeout:fn=>(timers.push(fn),timers.length),clearTimeout:()=>{}
  });
  return {
    request(file,mode='cors'){
      let response;
      events.fetch({
        request:{method:'GET',url:'https://example.test/Stock/'+file,mode},
        waitUntil:p=>life.push(p),respondWith:p=>response=p
      });
      return response;
    },timers,life
  };
}
test('離線資料檔只回自己的快取,查詢字串不新增副本',async()=>{
  const hit=new Response('{"ok":true}');
  const h=swHarness({entries:{'https://example.test/Stock/data.json':hit}});
  assert.equal(await h.request('data.json?t=123'),hit);
});
test('離線缺少 JSON/JS 時不能以首頁 HTML 冒充',async()=>{
  const shell=new Response('<html>shell</html>');
  const h=swHarness({entries:{'https://example.test/Stock/index.html':shell}});
  assert.equal((await h.request('missing.json')).type,'error');
  assert.equal((await h.request('missing.js')).type,'error');
});
test('離線頁面可使用 index.html 備援',async()=>{
  const shell=new Response('<html>shell</html>');
  const h=swHarness({entries:{'https://example.test/Stock/index.html':shell}});
  assert.equal(await h.request('','navigate'),shell);
});
test('離線頁面也能使用根目錄網址儲存的首頁',async()=>{
  const shell=new Response('<html>root</html>');
  const h=swHarness({entries:{'https://example.test/Stock/':shell}});
  assert.equal(await h.request('index.html','navigate'),shell);
});
test('離線完全沒有快取時回傳網路失敗,而非 undefined',async()=>{
  assert.equal((await swHarness().request('','navigate')).type,'error');
});
test('慢速網路先回快取,背景快取更新受 waitUntil 保護',async()=>{
  let finishFetch,finishPut,written=false;
  const old=new Response('old');
  const response=new Response('new');
  Object.defineProperty(response,'type',{value:'basic'});
  const h=swHarness({
    entries:{'https://example.test/Stock/data.json':old},
    fetcher:()=>new Promise(resolve=>finishFetch=resolve),
    put:()=>new Promise(resolve=>finishPut=()=>{written=true;resolve()})
  });
  const pending=h.request('data.json');
  h.timers[0]();
  assert.equal(await pending,old);
  assert.equal(h.life.length,1);
  finishFetch(response);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(written,false);
  finishPut();
  await Promise.all(h.life);
  assert.equal(written,true);
});
test('儲存空間不足仍顯示正常網路回應',async()=>{
  const response=new Response('online');
  Object.defineProperty(response,'type',{value:'basic'});
  const h=swHarness({fetcher:async()=>response,put:async()=>{throw Error('quota')}});
  assert.equal(await h.request('data.json'),response);
});
test('HTTP 錯誤仍保留原狀態,不假裝成成功資料',async()=>{
  const response=new Response('not found',{status:404});
  assert.equal((await swHarness({fetcher:async()=>response}).request('missing.json')).status,404);
});
function searchHarness(){
  const handlers={},input={value:'',addEventListener:(n,fn)=>handlers[n]=fn,blur(){}};
  const drop={hidden:true,innerHTML:'',addEventListener(){}};
  const location={hash:'#stock/2330'};
  const stocks=[{id:'2330',name:'台積電',price:2385},{id:'NVDA',name:'Nvidia',price:212}];
  const start=app.indexOf('/* 頂部快速搜尋:');
  const end=app.indexOf('/* 頂部小學堂按鈕 */',start);
  vm.runInNewContext(app.slice(start,end),{
    document:{getElementById:id=>id==='qSearch'?input:drop,addEventListener(){}},
    DATA:{stocks},location,chgHtml:()=>'',String
  });
  return {input,drop,location,
    inputText(text){input.value=text;handlers.input()},
    focus(){handlers.focus()},
    key(key,extra={}){
      const event={key,preventDefault(){},stopPropagation(){this.stopped=true},...extra};
      handlers.keydown(event);return event;
    }
  };
}
test('搜尋無結果有提示,空白時關閉提示',()=>{
  const h=searchHarness();h.inputText('不存在');
  assert.equal(h.drop.hidden,false);assert.match(h.drop.innerHTML,/找不到符合/);
  h.inputText(' ');assert.equal(h.drop.hidden,true);
});
test('選取後重新聚焦不顯示上次結果',()=>{
  const h=searchHarness();h.inputText('2330');h.key('Enter');h.focus();
  assert.equal(h.input.value,'');assert.equal(h.drop.hidden,true);
});
test('Escape 僅關閉搜尋,不冒泡到整頁返回處理',()=>{
  const h=searchHarness();h.inputText('2330');const e=h.key('Escape');
  assert.equal(e.stopped,true);assert.equal(h.location.hash,'#stock/2330');
});
test('中文組字中的 Enter 不提前跳頁',()=>{
  const h=searchHarness();h.inputText('NVDA');h.key('Enter',{isComposing:true});
  assert.equal(h.location.hash,'#stock/2330');
});
test('空清單按下箭頭再重新聚焦仍能選第一個結果',()=>{
  const h=searchHarness();h.inputText('???');h.key('ArrowDown');
  h.input.value='NVDA';h.focus();h.key('Enter');
  assert.equal(h.location.hash,'#stock/NVDA');
});
test('異常日期標示涵蓋月份/天數/閏年,保留原文',()=>{
  const code=app.slice(app.indexOf('function trendDateIssues('),app.indexOf('function trendsRender('));
  const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);
  const t={thesis:'10/42、13/1、2/29、10/23'};
  assert.deepEqual(Array.from(ctx.trendDateIssues(t,2026)),['10/42','13/1','2/29']);
  assert.deepEqual(Array.from(ctx.trendDateIssues({thesis:'2/29'},2024)),[]);
  assert.equal(t.thesis,'10/42、13/1、2/29、10/23');
});
