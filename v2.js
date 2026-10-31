/* r1203 K研所 v2 版面(Frank 10/31 晚:「可以整個大改版」;順序 早報、大盤、AI Pick、持股、我的最愛)
   只搬動既有節點、沿用原本的事件與資料;不刪任何功能。
   - 電腦(≥1024px):左側導覽列 + 上方細工具列
   - 平板(641~1023px):上方橫向分頁
   - 手機(≤640px):底部導覽(早報/大盤/AI Pick/持股/最愛/更多)
   - 「今日盤勢」併入「大盤」頁最上面 */
(function(){
  'use strict';
  const doc=document,root=doc.documentElement;
  root.classList.add('v2');
  const NAV=[['news','📰','產業早報'],['macro','📊','大盤'],['aipick','🤖','AI Pick'],['port','💼','我的持股'],['fav','⭐','我的最愛']];
  const NAV2=[['stocks','📈','選股'],['etf','🧺','ETF'],['gooaye','🎙️','節目']];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  /* ── 今日盤勢併入大盤 ── */
  function mergeView(){
    const view=doc.getElementById('tp-view'),macro=doc.getElementById('tp-macro');
    if(!view||!macro||macro.dataset.v2merged)return;macro.dataset.v2merged='1';
    const wrap=doc.createElement('section');wrap.id='v2Today';wrap.className='v2-today';
    [...view.children].forEach(el=>wrap.append(el));
    const t=wrap.querySelector('.sec-title');if(t)t.innerHTML='🧭 今日盤勢 <span>為什麼漲跌・現在跌到哪・早晚自動更新</span>';
    macro.prepend(wrap);
  }
  /* ── setHomeTab:view → macro,打開大盤時一起載入今日盤勢 ── */
  function patchTabs(){
    if(typeof window.setHomeTab!=='function'||window.setHomeTab.__v2)return;
    const orig=window.setHomeTab;
    const f=function(t){if(t==='view')t='macro';const r=orig.call(this,t);if(t==='macro'){try{if(typeof viewLoad==='function')setTimeout(()=>{try{viewLoad();}catch(e){}},0);}catch(e){}}sync();return r;};
    f.__v2=true;window.setHomeTab=f;
    const tabs=doc.getElementById('homeTabs');
    if(tabs)tabs.querySelectorAll('button[data-tab]').forEach(b=>b.onclick=()=>window.setHomeTab(b.dataset.tab));
  }
  function go(key){
    if(key==='fav'){if(location.hash!=='#fav')location.hash='#fav';}
    else{if(location.hash)location.hash='';window.setHomeTab(key);}
    window.scrollTo({top:0,behavior:'auto'});setTimeout(sync,0);
  }
  function current(){
    if(location.hash==='#fav')return 'fav';
    if(/^#stock\//.test(location.hash))return '';
    const b=doc.querySelector('#homeTabs button.on');return b?b.dataset.tab==='view'?'macro':b.dataset.tab:'news';
  }
  /* ── 電腦左側導覽 ── */
  function sidebar(){
    if(doc.getElementById('v2side'))return;
    const side=doc.createElement('aside');side.id='v2side';side.setAttribute('aria-label','主選單');
    const logo=doc.querySelector('header h1');
    const item=([k,ic,lb])=>`<button type="button" data-v2="${k}"><span class="v2-ic">${ic}</span><span>${esc(lb)}</span></button>`;
    side.innerHTML=`<a class="v2-logo" href="#" data-v2="news"></a><div class="v2-mkt"></div><nav class="v2-nav">${NAV.map(item).join('')}<div class="v2-sep">更多</div>${NAV2.map(item).join('')}</nav><div class="v2-foot"></div>`;
    if(logo)side.querySelector('.v2-logo').append(logo.cloneNode(true));
    side.addEventListener('click',e=>{const b=e.target.closest('[data-v2]');if(!b)return;e.preventDefault();go(b.dataset.v2);});
    doc.body.prepend(side);
    /* 市場切換與帳號/提醒/小學堂/主題:電腦放側欄,手機/平板放回原位(依螢幕寬度來回搬,節點與事件不變) */
    const homes={};const ids=['gmktBar','authBtn','alertBtn','learnBtn','themeSel','pwaBtn'];
    ids.forEach(id=>{const el=doc.getElementById(id);if(el)homes[id]={p:el.parentNode,n:el.nextSibling};});
    const mq=window.matchMedia('(min-width:1024px)');
    const place=()=>{ids.forEach(id=>{const el=doc.getElementById(id),h=homes[id];if(!el||!h)return;
      if(mq.matches){const dest=id==='gmktBar'?side.querySelector('.v2-mkt'):side.querySelector('.v2-foot');if(el.parentNode!==dest)dest.append(el);}
      else if(el.parentNode!==h.p){if(h.n&&h.n.parentNode===h.p)h.p.insertBefore(el,h.n);else h.p.append(el);}});};
    place();try{mq.addEventListener('change',place);}catch(e){mq.addListener(place);}
  }
  /* ── 上方細工具列:搜尋 + 資料時間;其餘按鈕已移到側欄 ── */
  function topbar(){
    const head=doc.querySelector('header');if(!head||head.dataset.v2)return;head.dataset.v2='1';
    head.classList.add('v2-top');
    const fav=doc.getElementById('favBtn');if(fav)fav.classList.add('v2-hide');   // 最愛已在主選單
    /* r1207:「工具」打開時改成浮出的小面板,不再把頁首撐開 */
    const ht=head.querySelector('.header-tools');
    if(ht&&!ht.querySelector('.ht-pop')){const pop=doc.createElement('div');pop.className='ht-pop';[...ht.children].forEach(c=>{if(c.tagName!=='SUMMARY')pop.append(c);});ht.append(pop);
      doc.addEventListener('click',e=>{if(ht.open&&!ht.contains(e.target))ht.open=false;});
      new MutationObserver(()=>{[...ht.children].forEach(c=>{if(c.tagName!=='SUMMARY'&&c!==pop)pop.append(c);});}).observe(ht,{childList:true});}
  }
  /* ── 手機底部導覽:重建成 早報/大盤/AI Pick/持股/最愛/更多 ── */
  function mobileNav(){
    const nav=doc.getElementById('mobNav');if(!nav||nav.dataset.v2)return;nav.dataset.v2='1';
    const items=[['news','📰','早報'],['macro','📊','大盤'],['aipick','🤖','AI Pick'],['port','💼','持股'],['fav','⭐','最愛']];
    nav.innerHTML=items.map(([k,ic,lb])=>`<button type="button" data-v2="${k}"><span class="mi">${ic}</span>${lb}</button>`).join('')+`<button type="button" data-v2="__more" aria-haspopup="dialog"><span class="mi">☰</span>更多</button>`;
    nav.onclick=e=>{const b=e.target.closest('[data-v2]');if(!b)return;if(b.dataset.v2==='__more'){if(typeof WorkspaceNavigation!=='undefined')WorkspaceNavigation.open(doc);return;}go(b.dataset.v2);};
    window.__mobNavSync=sync;
  }
  function sync(){
    const k=current();
    doc.querySelectorAll('#v2side [data-v2],#mobNav [data-v2]').forEach(b=>{const on=b.dataset.v2===k&&!b.classList.contains('v2-logo');b.classList.toggle('on',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    root.classList.toggle('v2-detail',!!location.hash&&location.hash!=='#fav');
  }
  /* r1207:App(加到主畫面)上方狀態列顏色跟著目前主題的底色,不再是紅色 */
  function themeColor(){try{const bg=getComputedStyle(doc.body).backgroundColor;if(!bg)return;doc.querySelectorAll('meta[name="theme-color"]').forEach(m=>m.setAttribute('content',bg));}catch(e){}}
  function init(){
    themeColor();try{new MutationObserver(()=>setTimeout(themeColor,50)).observe(root,{attributes:true,attributeFilter:['data-theme','class']});}catch(e){}
    try{mergeView();}catch(e){}
    try{patchTabs();}catch(e){}
    try{sidebar();}catch(e){}
    try{topbar();}catch(e){}
    try{mobileNav();}catch(e){}
    sync();
    window.addEventListener('hashchange',()=>setTimeout(sync,0));
    /* 有些模組晚一點才建好手機導覽,再補一次 */
    setTimeout(()=>{try{mobileNav();sync();}catch(e){}},1500);
    /* 開站若停在已併入的「今日盤勢」,轉到大盤 */
    const cur=doc.querySelector('#homeTabs button.on');if(cur&&cur.dataset.tab==='view')window.setHomeTab('macro');
    if(cur&&cur.dataset.tab==='macro'){try{viewLoad();}catch(e){}}
  }
  if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',init);else init();
})();
