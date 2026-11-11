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
  const NAV=[['home','🏠','總覽'],['news','📰','產業早報'],['macro','📊','大盤'],['aipick','🤖','AI Pick'],['port','💼','我的持股'],['fav','⭐','我的最愛']];
  const NAV2=[['trend','🔭','未來產業'],['stocks','📈','選股'],['etf','🧺','ETF'],['gooaye','🎙️','節目']];
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
    const b=doc.querySelector('#homeTabs button.on');return b?b.dataset.tab==='view'?'macro':b.dataset.tab:'home';
  }
  /* ── 電腦左側導覽 ── */
  function sidebar(){
    if(doc.getElementById('v2side'))return;
    const side=doc.createElement('aside');side.id='v2side';side.setAttribute('aria-label','主選單');
    const logo=doc.querySelector('header h1');
    const item=([k,ic,lb])=>`<button type="button" data-v2="${k}"><span class="v2-ic">${ic}</span><span>${esc(lb)}</span></button>`;
    side.innerHTML=`<a class="v2-logo" href="#" data-v2="home"></a><div class="v2-mkt"></div><nav class="v2-nav">${NAV.map(item).join('')}<div class="v2-sep">更多</div>${NAV2.map(item).join('')}</nav><div class="v2-foot"></div>`;
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
    const items=[['home','🏠','總覽'],['macro','📊','大盤'],['aipick','🤖','AI Pick'],['port','💼','持股'],['fav','⭐','最愛']];   // r1213:早報在總覽與更多
    nav.innerHTML=items.map(([k,ic,lb])=>`<button type="button" data-v2="${k}"><span class="mi">${ic}</span>${lb}</button>`).join('')+`<button type="button" data-v2="__more" aria-haspopup="dialog"><span class="mi">☰</span>更多</button>`;
    nav.onclick=e=>{const b=e.target.closest('[data-v2]');if(!b)return;if(b.dataset.v2==='__more'){if(typeof WorkspaceNavigation!=='undefined')WorkspaceNavigation.open(doc);return;}go(b.dataset.v2);};
    window.__mobNavSync=sync;
  }
  /* ── r1222 手機:頁首縮成一列(標誌・搜尋・鈴鐺),登入/工具搬到「更多」;底部「更多」只列底部導覽沒有的頁 + 帳號與設定 ── */
  const mqM=window.matchMedia('(max-width:640px)');
  function mobileCompact(){
    const head=doc.querySelector('header .head-in');if(!head||head.dataset.v2m)return;head.dataset.v2m='1';
    const hold=doc.createElement('div');hold.id='v2hold';hold.hidden=true;doc.body.append(hold);
    const ids=['authBtn','header-tools'];const homes={};
    const get=id=>id==='header-tools'?head.querySelector('.header-tools'):doc.getElementById(id);
    ids.forEach(id=>{const el=get(id);if(el)homes[id]={el,p:el.parentNode,n:el.nextSibling};});
    const place=()=>{Object.values(homes).forEach(h=>{if(!h.el)return;
      if(mqM.matches){if(h.el.parentNode!==hold&&!h.el.closest('.workspace-menu'))hold.append(h.el);}
      else if(h.el.parentNode!==h.p){if(h.n&&h.n.parentNode===h.p)h.p.insertBefore(h.el,h.n);else h.p.append(h.el);}});};
    place();try{mqM.addEventListener('change',place);}catch(e){mqM.addListener(place);}
    window.__v2moveBack=()=>{Object.values(homes).forEach(h=>{if(mqM.matches&&h.el.parentNode!==hold)hold.append(h.el);});};
  }
  function patchMenu(){
    if(typeof window.WorkspaceNavigation==='undefined'||WorkspaceNavigation.__v2)return;
    const orig=WorkspaceNavigation.open;
    WorkspaceNavigation.open=function(d){const r=orig.call(this,d);try{const dlg=doc.querySelector('dialog.workspace-menu');if(!dlg||!mqM.matches)return r;
      const inNav=new Set([...doc.querySelectorAll('#mobNav [data-v2]')].map(b=>b.dataset.v2));
      dlg.querySelectorAll('.workspace-page-list [data-page]').forEach(b=>{if(inNav.has(b.dataset.page))b.remove();});
      const h=dlg.querySelector('.workspace-menu-head h2');if(h)h.textContent='更多';const sub=dlg.querySelector('.workspace-menu-head p');if(sub)sub.textContent='其他頁面、帳號與設定';
      const grid=dlg.querySelector('.workspace-page-list');const lb=doc.getElementById('learnBtn');
      if(grid&&lb){const b=doc.createElement('button');b.type='button';b.dataset.v2learn='1';b.innerHTML='<strong>📚 小學堂</strong><small>每天學一點・白話課</small>';b.onclick=()=>{dlg.close();setTimeout(()=>lb.click(),50);};grid.append(b);}
      if(!dlg.dataset.v2bd){dlg.dataset.v2bd='1';dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close();});}
      const sec=doc.createElement('div');sec.className='v2-acct';sec.innerHTML='<div class="v2-sep">帳號與設定</div><div class="v2-acct-row"></div>';
      const row=sec.querySelector('.v2-acct-row');const hold=doc.getElementById('v2hold');
      const auth=doc.getElementById('authBtn');if(auth)row.append(auth);
      const ht=hold&&hold.querySelector('.header-tools');if(ht){const pop=ht.querySelector('.ht-pop');[...(pop||ht).children].forEach(c=>{if(c.tagName!=='SUMMARY'&&c.id!=='favBtn'&&c.id!=='secNav'&&c.id!=='learnBtn'&&!c.matches('nav'))row.append(c);});sec.dataset.ht='1';}
      const bell=doc.createElement('button');bell.type='button';bell.className='btn-ghost';bell.textContent='🔔 通知設定';bell.onclick=()=>{dlg.close();setTimeout(()=>{const b=doc.getElementById('alertBtn');if(b)b.click();},50);};row.append(bell);
      row.addEventListener('click',e=>{const t=e.target.closest('button,a');if(t&&t!==bell)setTimeout(()=>{try{dlg.close();}catch(x){}},80);});
      dlg.append(sec);
      dlg.addEventListener('close',()=>{try{const ht2=hold&&hold.querySelector('.header-tools');const pop=ht2&&(ht2.querySelector('.ht-pop')||ht2);[...row.children].forEach(c=>{if(c.id==='authBtn')hold.append(c);else if(c!==bell&&pop)pop.append(c);});sec.remove();}catch(e){}},{once:true});
    }catch(e){}return r;};
    WorkspaceNavigation.__v2=true;
  }
  /* r1223 手機個股頁:名稱/價格的黏頂列只在大標題捲出畫面後才出現;最愛卡細節收摺 */
  function stockCtx(){
    if(!mqM.matches){root.classList.remove('ctx-show');return;}
    const head=doc.querySelector('#detailView .m-head');if(!head||head.dataset.v2io)return;head.dataset.v2io='1';
    try{const io=new IntersectionObserver(es=>{es.forEach(e=>root.classList.toggle('ctx-show',!e.isIntersecting&&e.boundingClientRect.top<0));},{threshold:0});io.observe(head);}catch(e){}
  }
  function favFold(){
    if(!mqM.matches)return;
    doc.querySelectorAll('#favBox .strategy-summary').forEach(sc=>{if(sc.dataset.v2fold)return;
      const parts=['.sc-signals','.sc-insights'].map(q=>sc.querySelector(q)).filter(Boolean);if(!parts.length)return;sc.dataset.v2fold='1';
      const d=doc.createElement('details');d.className='v2-scfold';d.innerHTML='<summary>止跌進度與細節</summary>';parts[0].before(d);parts.forEach(p=>d.append(p));});
  }
  /* r1224 更像 App:手機頂列 = 頁名・台股/美股・搜尋鈕・鈴鐺;搜尋框點了才展開;頁名跟著目前頁面 */
  const TITLE={home:'總覽',news:'產業早報',macro:'大盤',aipick:'AI Pick',port:'我的持股',fav:'我的最愛',stocks:'選股',etf:'ETF',gooaye:'節目',view:'大盤',trend:'未來產業'};
  function appBar(){
    const head=doc.querySelector('header .head-in');if(!head||doc.getElementById('v2top'))return;
    const bar=doc.createElement('div');bar.id='v2top';
    bar.innerHTML='<div class="v2t-l"><span class="v2t-logo"></span><b class="v2t-title">總覽</b></div><div class="v2t-mkt"></div><button type="button" class="v2t-search" aria-label="搜尋股票">🔍</button><div class="v2t-bell"></div>';
    const logo=doc.querySelector('header h1 .lgo');if(logo)bar.querySelector('.v2t-logo').append(logo.cloneNode(true));
    head.prepend(bar);
    const homes={};const ids=['gmktBar','alertBtn'];
    ids.forEach(id=>{const el=doc.getElementById(id);if(el)homes[id]={el,p:el.parentNode,n:el.nextSibling};});
    const place=()=>{ids.forEach(id=>{const h=homes[id];if(!h)return;const dest=id==='gmktBar'?bar.querySelector('.v2t-mkt'):bar.querySelector('.v2t-bell');
      if(mqM.matches){if(h.el.parentNode!==dest)dest.append(h.el);}
      else if(h.el.parentNode===dest){if(h.n&&h.n.parentNode===h.p)h.p.insertBefore(h.el,h.n);else h.p.append(h.el);}});
      if(!mqM.matches)root.classList.remove('v2-search');};
    place();try{mqM.addEventListener('change',place);}catch(e){mqM.addListener(place);}
    bar.querySelector('.v2t-search').onclick=()=>{const on=root.classList.toggle('v2-search');if(on)setTimeout(()=>{const q=doc.getElementById('qSearch');if(q)q.focus();},30);else{const q=doc.getElementById('qSearch');if(q){q.value='';q.dispatchEvent(new Event('input'));}}};
    doc.addEventListener('click',e=>{if(!root.classList.contains('v2-search'))return;if(e.target.closest('#v2top,.qs-wrap,.qs-drop'))return;root.classList.remove('v2-search');},true);
    doc.addEventListener('keydown',e=>{if(e.key==='Escape'&&root.classList.contains('v2-search'))root.classList.remove('v2-search');});
  }
  function syncTitle(){
    const t=doc.querySelector('#v2top .v2t-title');if(!t)return;
    let k=current(),txt=TITLE[k]||'';
    if(/^#stock\//.test(location.hash)){const id=decodeURIComponent(location.hash.slice(7));const s=(window.DATA&&DATA.stocks||[]).find(x=>x.id===id);txt=s?s.name:'個股';}
    else if(!k&&location.hash==='#learn')txt='小學堂';else if(!k&&location.hash)txt=(doc.querySelector('#detailView .m-head h2')||{}).textContent||'';
    t.textContent=txt||'K研所';
    if(/^#stock\//.test(location.hash))root.classList.remove('v2-search');
    root.classList.toggle('v2-home',k==='home'&&!location.hash);
  }
  function sync(){
    const k=current();
    doc.querySelectorAll('#v2side [data-v2],#mobNav [data-v2]').forEach(b=>{const on=b.dataset.v2===k&&!b.classList.contains('v2-logo');b.classList.toggle('on',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    root.classList.toggle('v2-detail',!!location.hash&&location.hash!=='#fav');
    try{syncTitle();}catch(e){}
  }
  /* r1207:App(加到主畫面)上方狀態列顏色跟著目前主題的底色,不再是紅色 */
  function themeColor(){try{const bg=getComputedStyle(doc.body).backgroundColor;if(!bg)return;doc.querySelectorAll('meta[name="theme-color"]').forEach(m=>m.setAttribute('content',bg));}catch(e){}}
  /* r1232 手機:長頁面上方的「快速跳段」列(往下滑才出現)+ 往下滑時收起底部指數列,往上滑再出現 */
  function jumpItems(){
    if(location.hash||!mqM.matches)return [];
    const k=current(),pane=doc.getElementById('tp-'+k);if(!pane||!pane.offsetParent)return [];
    const out=[],clean=t=>String(t||'').replace(/^[\s▸▾▶▼►]+/,'').replace(/[|｜].*$/,'').trim();
    if(k==='trend')pane.querySelectorAll('.tr-card').forEach(e=>{const b=e.querySelector('b');const t=clean(b&&b.textContent);if(t)out.push({el:e,t:t.length>9?t.slice(0,9)+'…':t});});
    else pane.querySelectorAll('.sec-title,.a3-card>.a3-h').forEach(e=>{if(!e.offsetParent)return;
      let t=e.classList.contains('a3-h')?clean((e.querySelector('b')||e).textContent):clean(e.childNodes[0]&&e.childNodes[0].textContent);
      if(!t)t=clean(e.textContent);if(!t)return;out.push({el:e,t:t.length>10?t.slice(0,10)+'…':t});});
    return out.length>=3?out:[];
  }
  let JI=[],JSIG='';
  function jumpPaint(){
    let bar=doc.getElementById('v2jump');
    if(!bar){bar=doc.createElement('nav');bar.id='v2jump';bar.setAttribute('aria-label','快速跳到這一頁的某一段');doc.body.append(bar);
      bar.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
        if(b.dataset.top){window.scrollTo({top:0,behavior:'smooth'});return;}
        const it=JI[+b.dataset.i];if(!it||!it.el.isConnected)return;
        try{const sec=it.el.dataset&&it.el.dataset.sec,body=sec&&doc.getElementById('sb-'+sec);if(body&&body.classList.contains('closed'))it.el.click();}catch(x){}
        const off=(doc.querySelector('header')||{}).offsetHeight||52;
        setTimeout(()=>window.scrollTo({top:Math.max(0,it.el.getBoundingClientRect().top+window.scrollY-off-bar.offsetHeight-6),behavior:'smooth'}),30);});}
    JI=jumpItems();const sig=current()+'|'+JI.map(x=>x.t).join('|');
    if(sig!==JSIG){JSIG=sig;bar.innerHTML=JI.length?'<button type="button" data-top="1" aria-label="回到最上面">⬆ 頂端</button>'+JI.map((x,i)=>'<button type="button" data-i="'+i+'">'+x.t.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))+'</button>').join(''):'';}
    return bar;
  }
  function jumpInit(){
    let lastY=window.scrollY,tick=0,lastBuild=0;
    const run=()=>{tick=0;const y=window.scrollY,hd=doc.querySelector('header'),off=(hd&&hd.offsetHeight)||52;
      if(!mqM.matches){root.classList.remove('v2-jump','v2-sd');return;}
      root.style.setProperty('--v2jt',off+'px');
      if(Math.abs(y-lastY)>6){root.classList.toggle('v2-sd',y>lastY&&y>120);lastY=y;}
      const now=Date.now();let bar=doc.getElementById('v2jump');
      if(!bar||now-lastBuild>700){lastBuild=now;bar=jumpPaint();}
      const show=JI.length>0&&y>260&&!location.hash;root.classList.toggle('v2-jump',show);
      if(show){let on=-1;const lim=off+bar.offsetHeight+24;for(let i=0;i<JI.length;i++){if(JI[i].el.isConnected&&JI[i].el.getBoundingClientRect().top<=lim)on=i;}
        bar.querySelectorAll('button[data-i]').forEach(b=>{const o=+b.dataset.i===on;if(o!==b.classList.contains('on')){b.classList.toggle('on',o);if(o)try{bar.scrollTo({left:Math.max(0,b.offsetLeft-80),behavior:'smooth'});}catch(e){}}});}
    };
    window.addEventListener('scroll',()=>{if(!tick)tick=requestAnimationFrame(run);},{passive:true});
    window.addEventListener('hashchange',()=>{JSIG='';root.classList.remove('v2-jump','v2-sd');setTimeout(run,300);});
  }
  function init(){
    themeColor();try{new MutationObserver(()=>setTimeout(themeColor,50)).observe(root,{attributes:true,attributeFilter:['data-theme','class']});}catch(e){}
    try{mergeView();}catch(e){}
    try{patchTabs();}catch(e){}
    try{sidebar();}catch(e){}
    try{topbar();}catch(e){}
    try{mobileNav();}catch(e){}
    try{mobileCompact();}catch(e){}
    try{appBar();}catch(e){}
    try{patchMenu();}catch(e){}
    try{jumpInit();}catch(e){}
    sync();
    window.addEventListener('hashchange',()=>setTimeout(sync,0));
    try{new MutationObserver(()=>{clearTimeout(window.__v2t);window.__v2t=setTimeout(()=>{try{stockCtx();favFold();syncTitle();}catch(e){}},250);}).observe(doc.getElementById('detailView')||doc.body,{childList:true,subtree:true});}catch(e){}
    /* 有些模組晚一點才建好手機導覽,再補一次 */
    setTimeout(()=>{try{mobileNav();patchMenu();sync();}catch(e){}},1500);
    /* 開站若停在已併入的「今日盤勢」,轉到大盤 */
    const cur=doc.querySelector('#homeTabs button.on');if(cur&&cur.dataset.tab==='view')window.setHomeTab('macro');
    if(cur&&cur.dataset.tab==='home'&&!location.hash)window.setHomeTab('home');   // r1213:總覽在 app.js 啟動時還沒建好,補一次
    if(cur&&cur.dataset.tab==='macro'){try{viewLoad();}catch(e){}}
  }
  if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',init);else init();
})();
