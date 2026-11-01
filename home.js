/* r1213 🏠 總覽(Frank 11/2:「找不到東西在哪、操作很不人性化」;常做的四件事:持股該不該賣、最愛哪檔到買點、AI Pick 買什麼、今天大盤和新聞)
   一頁看完:每檔一行(現價、該做什麼、關鍵價格),點一行就進個股;每區右上「看全部 ›」到原本的分頁。
   只讀既有資料與既有計算(stockOperationFacts / ownStrategySummary / StockCardSummary / AIP3 / 早報 / 盤勢),不新增任何交易規則。 */
(function(){
  'use strict';
  const doc=document,esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>v==null||v===''||!isFinite(+v)?null:+v;
  const fmt=(v,us)=>{v=num(v);return v==null?'—':(us?'$':'')+v.toLocaleString(undefined,{maximumFractionDigits:2});};
  const pct=v=>{v=num(v);return v==null?'—':(v>0?'+':'')+v.toFixed(2)+'%';};
  const col=v=>{v=num(v);return v==null?'var(--txt2)':v>0?'var(--up)':v<0?'var(--down)':'var(--txt2)';};
  const stock=id=>((window.DATA&&DATA.stocks)||[]).find(x=>x.id===id);
  let busy=false,lastRun=0;

  function pane(){
    let p=doc.getElementById('tp-home');
    if(!p){p=doc.createElement('div');p.className='tabPane';p.id='tp-home';p.style.display='none';
      p.innerHTML=`<div class="hm" id="hmBox">
        <section class="hm-sec" id="hmMkt"></section>
        <section class="hm-sec" id="hmPort"><div class="hm-h"><h3>💼 我的持股</h3><a href="javascript:void 0" data-go="port">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
        <section class="hm-sec" id="hmFav"><div class="hm-h"><h3>⭐ 我的最愛</h3><a href="javascript:void 0" data-go="fav">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
        <section class="hm-sec" id="hmAip"><div class="hm-h"><h3>🤖 AI Pick 模型持股</h3><a href="javascript:void 0" data-go="aipick">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
        <section class="hm-sec" id="hmNews"><div class="hm-h"><h3>📰 今日早報重點</h3><a href="javascript:void 0" data-go="news">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
      </div>`;
      const first=doc.getElementById('tp-news')||doc.querySelector('.tabPane');first.parentNode.insertBefore(p,first);
      p.addEventListener('click',e=>{const g=e.target.closest('[data-go]');if(g){e.preventDefault();go(g.dataset.go);return;}
        const r=e.target.closest('[data-sid]');if(r){location.hash='#stock/'+encodeURIComponent(r.dataset.sid);}});
    }
    return p;
  }
  function go(k){if(k==='fav'){location.hash='#fav';return;}if(location.hash)location.hash='';if(typeof setHomeTab==='function')setHomeTab(k);window.scrollTo({top:0});}
  const row=(sid,cells,tag)=>`<div class="hm-row" data-sid="${esc(sid)}" role="link" tabindex="0">${cells}${tag||''}</div>`;

  /* ── 大盤一行 + 今日盤勢一句 ── */
  async function mkt(){
    const box=doc.getElementById('hmMkt');if(!box)return;
    let idx=[];try{idx=((DATA.macro||{}).idx)||[];}catch(e){}
    const pick=k=>{const rt=window.RTIDX&&window.RTIDX[k];const it=idx.find(x=>String(x.name||'').includes(k));return rt&&rt.val?rt:it;};
    const chips=[['加權','加權'],['櫃買','櫃買']].map(([k,lb])=>{const it=pick(k);if(!it)return '';return `<span class="hm-idx"><small>${lb}</small><b>${fmt(it.val)}</b><em style="color:${col(it.chg)}">${pct(it.chg)}</em></span>`;}).join('');
    let head='',br='';
    try{const j=await viewFetch();if(j&&j.head)head=j.head;}catch(e){}
    try{if(typeof SECSTR==='undefined'||!SECSTR){if(typeof secStrLoad==='function')secStrLoad();}const a=SECSTR&&+SECSTR.a60;if(a>0)br=`<span class="hm-br">全市場 <b>${Math.round(a*100)}%</b> 股票站在季線上${a<0.35?'・<b style="color:var(--up)">大盤一起跌,錯殺股可以買</b>':''}</span>`;}catch(e){}
    box.innerHTML=`<div class="hm-mkt"><div class="hm-idxs">${chips||'<span class="dim">指數載入中…</span>'}${br}</div>
      ${head?`<div class="hm-head">🧭 ${esc(head)}</div>`:''}
      <div class="hm-links"><a href="javascript:void 0" data-go="macro">大盤與今日盤勢 ›</a><a href="javascript:void 0" data-go="news">產業早報 ›</a></div></div>`;
  }

  /* ── 持股:每檔一行(現價、損益、防守、停利) ── */
  async function port(){
    const body=doc.querySelector('#hmPort .hm-body');if(!body)return;
    const arr=(typeof portGet==='function'?portGet():[])||[];
    if(!arr.length){body.innerHTML=`<div class="hm-empty">還沒有持股紀錄。<a href="javascript:void 0" data-go="port">＋ 新增持股</a>,之後這裡會直接告訴你每檔的防守價和停利價。</div>`;return;}
    const out=[];
    for(const p of arr){
      const s=stock(p.id);if(!s)continue;const us=s.market==='US',px=num(s.price),cost=num(p.cost),pl=px&&cost?(px/cost-1)*100:null;
      let stop='—',tp='—',note='';
      try{const k=await loadK(s);const f=k&&k.ohlc?stockOperationFacts(s,k.ohlc,k.dates,true,cost):null;
        if(f&&f.check&&!f.check.jump&&f.check.liquid){
          const m=p.m||(us?'dip':f.atrp>0&&f.atrp<0.025?'low':'ma');
          if(m==='low'){stop=fmt(f.lowOwn&&f.lowOwn.stop,us);tp=fmt(f.lowOwn&&f.lowOwn.target,us);}
          else if(m==='dip'){stop=fmt(f.ownDip&&f.ownDip.stop,us);tp=fmt(f.ownDip&&f.ownDip.target,us);}
          else{stop=fmt(f.nextBelowPrice,us)+'↓';tp='季線出場';}
          const sv=num(String(stop).replace(/[^\d.]/g,''));if(px&&sv&&px<=sv)note='<span class="hm-tag hm-sell">已到防守</span>';
        }else note='<span class="hm-tag">價位待核對</span>';
      }catch(e){}
      out.push(row(s.id,`<span class="hm-nm"><b>${esc(s.name)}</b><small>${esc(s.id)}</small></span>
        <span class="hm-px"><b>${fmt(px,us)}</b><small style="color:${col(s.chg)}">${pct(s.chg)}</small></span>
        <span class="hm-pl" style="color:${col(pl)}">${pl==null?'—':(pl>0?'+':'')+pl.toFixed(1)+'%'}<small>成本 ${fmt(cost,us)}</small></span>
        <span class="hm-lv"><span>🛑 ${stop}</span><span>🎯 ${tp}</span></span>`,note));
    }
    body.innerHTML=`<div class="hm-thead"><span>股票</span><span>現價</span><span>損益</span><span>防守 / 停利</span></div>`+out.join('');
  }

  /* ── 最愛:每檔一行(該做什麼、買進/防守/賣出);可買的排前面 ── */
  async function fav(){
    const body=doc.querySelector('#hmFav .hm-body');if(!body)return;
    const ids=(typeof favList==='function'?favList():[])||[];
    if(!ids.length){body.innerHTML=`<div class="hm-empty">${typeof SB_USER!=='undefined'&&!SB_USER?'登入後才看得到你的最愛。':'還沒有最愛。'}在個股頁點名稱旁的 ☆ 就能加入,這裡會列出每檔「現在能不能買、買在哪、防守在哪」。</div>`;return;}
    const rows=[];
    for(const id of ids){
      const s=stock(id);if(!s||s.etf)continue;const us=s.market==='US';
      let m=null;
      try{const k=await loadK(s);if(k&&k.ohlc&&typeof ownStrategySummary==='function'&&typeof StockCardSummary!=='undefined'){const en=typeof favEntryOf==='function'?favEntryOf(id):null;m=StockCardSummary.fromHTML(ownStrategySummary(s,k.ohlc,k.dates,!!en,en&&en.px),doc);}}catch(e){}
      const act=m?m.action:'資料載入中';const ready=/已確認|開盤/.test(act),blocked=/先不買|待核對|過期|不追|不適用/.test(act);
      rows.push({ready,html:row(s.id,`<span class="hm-nm"><b>${esc(s.name)}</b><small>${esc(s.id)}</small></span>
        <span class="hm-px"><b>${fmt(s.price,us)}</b><small style="color:${col(s.chg)}">${pct(s.chg)}</small></span>
        <span class="hm-act ${ready?'go':blocked?'no':''}">${esc(act)}</span>
        <span class="hm-lv"><span>買 ${esc(m?m.buy:'—')}</span><span>🛑 ${esc(m?m.stop:'—')}</span><span>🎯 ${esc(m?m.sell:'—')}</span></span>`)});
    }
    rows.sort((a,b)=>b.ready-a.ready);
    body.innerHTML=`<div class="hm-thead"><span>股票</span><span>現價</span><span>現在該做什麼</span><span>買進 / 防守 / 賣出</span></div>`+rows.map(r=>r.html).join('');
  }

  /* ── AI Pick:三清單目前持有與待買 ── */
  async function aip(){
    const body=doc.querySelector('#hmAip .hm-body');if(!body)return;
    try{if(typeof aip3Load==='function')await aip3Load();}catch(e){}
    const us=window.GMKT==='US',M=typeof AIP3!=='undefined'&&AIP3?(us?AIP3.us:AIP3.tw):null;
    if(!M){body.innerHTML='<div class="hm-empty">AI Pick 資料載入中…</div>';return;}
    const nm={short:'短期',mid:'中期',long:'長期'},out=[];
    ['short','mid','long'].forEach(k=>{(M[k]&&M[k].slots||[]).forEach(p=>{
      if(p.st==='done')return;
      const q=typeof aip3Px==='function'?aip3Px(p.cur||p.id,us):{px:null};const px=q.px||p.last;const ret=p.entry&&px?(px/p.entry-1)*100:null;
      let sl='—',tp='—';try{const c=aipSlotPolicy(p,k,us);sl=fmt(c.sl,us);tp=fmt(c.tp,us);}catch(e){}
      const st=p.st==='pend'?'<span class="hm-tag hm-buy">待買</span>':`<span class="hm-tag">持有 ${p.days||0} 天</span>`;
      out.push(row(p.cur||p.id,`<span class="hm-nm"><b>${esc(p.name||p.id)}</b><small>${nm[k]}・${esc(p.cur||p.id)}</small></span>
        <span class="hm-px"><b>${fmt(px,us)}</b><small>${p.entry?'進場 '+fmt(p.entry,us):'選股日 '+fmt(p.sel_px,us)}</small></span>
        <span class="hm-pl" style="color:${col(ret)}">${ret==null?'—':(ret>0?'+':'')+ret.toFixed(1)+'%'}</span>
        <span class="hm-lv"><span>🛑 ${sl}</span><span>🎯 ${tp}</span></span>`,st));});});
    const pause=M.short&&M.short.pause&&M.short.pause.d===M.short.sel_d?`<div class="hm-note">⏸ ${esc(M.short.pause.msg)}——短期清單這週不追新股</div>`:'';
    body.innerHTML=pause+(out.length?`<div class="hm-thead"><span>股票</span><span>現價</span><span>報酬</span><span>停損 / 停利</span></div>`+out.slice(0,6).join('')+(out.length>6?`<details class="hm-more"><summary>其餘 ${out.length-6} 檔</summary>${out.slice(6).join('')}</details>`:''):'<div class="hm-empty">三個清單目前都沒有持股。</div>');
  }

  /* ── 早報前 3 則 ── */
  async function news(){
    const body=doc.querySelector('#hmNews .hm-body');if(!body)return;
    try{const j=await newsFetch();const items=(j&&j.items||[]).map((x,i)=>({x,i})).sort((a,b)=>(b.x.lv-a.x.lv)||(a.i-b.i)).map(o=>o.x).slice(0,3);
      body.innerHTML=(j&&j.mood?`<div class="hm-head">${esc(j.mood)}</div>`:'')+items.map(x=>`<div class="hm-news"><b>${esc(x.title)}</b><span>${esc(x.why||x.what||'')}</span>${(x.codes||[]).length?`<span class="hm-codes">${x.codes.slice(0,4).map(c=>`<a href="#stock/${encodeURIComponent(c.id)}">${esc(c.n)}</a>`).join('')}</span>`:''}</div>`).join('')||'<div class="hm-empty">今天的早報還沒產生。</div>';
    }catch(e){body.innerHTML='<div class="hm-empty">早報載入失敗,點「看全部」重試。</div>';}
  }

  async function render(force){
    if(busy||(!force&&Date.now()-lastRun<60e3))return;busy=true;lastRun=Date.now();
    pane();
    for(let i=0;i<60&&!((window.DATA&&DATA.stocks||[]).length);i++)await new Promise(r=>setTimeout(r,250));   // 主資料還沒到先等
    try{await Promise.all([mkt(),news(),aip()]);}catch(e){}
    try{if(typeof lvLoad==='function')await lvLoad();}catch(e){}   // 還原因子(ADJ1)沒載入時價位算不出來(手機上常見)
    try{await port();}catch(e){}
    try{await fav();}catch(e){}
    busy=false;
  }
  window.HomeView={render,pane};
  pane();
})();
