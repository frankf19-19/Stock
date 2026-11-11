/* r1213 🏠 總覽(Frank 11/2:「找不到東西在哪、操作很不人性化」;常做的四件事:持股該不該賣、最愛哪檔到買點、AI Pick 買什麼、今天大盤和新聞)
   r1235(Frank 11/12):總覽拿掉持股與最愛,改放大盤重要指標(三大法人、期貨選擇權、融資、成交值、匯率、美股)
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
        <section class="hm-sec" id="hmInd"><div class="hm-h"><h3>📊 大盤重要指標</h3><a href="javascript:void 0" data-go="macro">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
        <section class="hm-sec" id="hmNews"><div class="hm-h"><h3>📰 今日早報重點</h3><a href="javascript:void 0" data-go="news">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
        <section class="hm-sec" id="hmAip"><div class="hm-h"><h3>🤖 AI Pick 目前買了哪些</h3><a href="javascript:void 0" data-go="aipick">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
        <section class="hm-sec" id="hmTrend"><div class="hm-h"><h3>🔭 未來產業</h3><a href="javascript:void 0" data-go="trend">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
        <section class="hm-sec" id="hmLearn"><div class="hm-h"><h3>📚 每天學一點</h3><a href="javascript:void 0" data-go="learn">看全部 ›</a></div><div class="hm-body">載入中…</div></section>
      </div>`;
      const first=doc.getElementById('tp-news')||doc.querySelector('.tabPane');first.parentNode.insertBefore(p,first);
      p.addEventListener('click',e=>{const g=e.target.closest('[data-go]');if(g){e.preventDefault();go(g.dataset.go);return;}
        const r=e.target.closest('[data-sid]');if(r){location.hash='#stock/'+encodeURIComponent(r.dataset.sid);}});
    }
    return p;
  }
  function go(k){if(k==='fav'){location.hash='#fav';return;}if(k==='learn'){location.hash='#learn';return;}if(location.hash)location.hash='';if(typeof setHomeTab==='function')setHomeTab(k);window.scrollTo({top:0});}
  const row=(sid,cells,tag)=>`<div class="hm-row" data-sid="${esc(sid)}" role="link" tabindex="0">${cells}${tag||''}</div>`;

  /* ── 大盤一行 + 今日盤勢一句 ── */
  async function mkt(){
    const box=doc.getElementById('hmMkt');if(!box)return;
    let idx=[];try{idx=((DATA.macro||{}).idx)||[];}catch(e){}
    const pick=k=>{const rt=window.RTIDX&&window.RTIDX[k];const it=idx.find(x=>String(x.name||'').includes(k));return rt&&rt.val?rt:it;};
    const usM=window.GMKT==='US';const chips=(usM?[['S&P','S&P 500'],['那斯達克','那斯達克']]:[['加權','加權'],['櫃買','櫃買']]).map(([k,lb])=>{const it=pick(k);if(!it)return '';return `<span class="hm-idx"><small>${lb}</small><b>${fmt(it.val)}</b><em style="color:${col(it.chg)}">${pct(it.chg)}</em>${it.d?`<small>${String(it.d).slice(5).replace('-','/')} 收盤</small>`:''}</span>`;}).join('');
    let head='',br='';
    let vtag='';try{const j=await viewFetch();if(j&&j.head){head=j.head;if(j.date)vtag=`${String(j.date).slice(5).replace('-','/')} ${j.slot==='pm'?'晚上':'早上'}版`;}}catch(e){}
    if(!usM)try{if(typeof SECSTR==='undefined'||!SECSTR){if(typeof secStrLoad==='function')secStrLoad();}const a=SECSTR&&+SECSTR.a60;if(a>0){const pc=Math.round(a*100)===35?(a*100).toFixed(1):Math.round(a*100);br=`<span class="hm-br">有成交量的股票${a<0.5?'只有':''} <b>${pc}%</b> 在近 3 個月平均價之上${SECSTR.asof?'('+String(SECSTR.asof).slice(5).replace('-','/')+')':''}・${a<0.35?'<b style="color:var(--up)">大盤一起大跌,跌深的好股票可以撿</b>':a<0.45?'大盤偏弱,接近跌深買點門檻 35%':a<0.6?'大盤普通':'大盤強'}</span>`;};}catch(e){}
    box.innerHTML=`<div class="hm-mkt"><div class="hm-idxs">${chips||'<span class="dim">指數載入中…</span>'}${br}</div>
      ${head?`<div class="hm-head">🧭 ${esc(head)}${vtag?` <small class="dim" style="font-weight:400;font-size:12px">(盤勢解讀 ${vtag})</small>`:''}</div>`:''}
      <div class="hm-links"><a href="javascript:void 0" data-go="macro">大盤與今日盤勢 ›</a><a href="javascript:void 0" data-go="news">產業早報 ›</a></div></div>`;
  }

  /* ── r1235 大盤重要指標(Frank 11/12:總覽不放持股/最愛,改放三大法人、期貨、融資這些)
        全部讀既有資料(DATA.macro.futtab / credit / idx / fx),只陳述事實(今天多少、連幾天、比昨天增減),不下買賣判斷 ── */
  function ind(){
    const body=doc.querySelector('#hmInd .hm-body');if(!body)return;
    const M=(window.DATA&&DATA.macro)||{},idx=M.idx||[],fx=M.fx||{};
    const md=d=>d?String(d).replace(/\//g,'-').slice(5).replace('-','/'):'';
    const sg=(v,dec=1,unit='')=>{v=num(v);return v==null?'—':(v>0?'+':'')+v.toLocaleString(undefined,{minimumFractionDigits:dec,maximumFractionDigits:dec})+unit;};
    const tile=(lb,val,c,sub)=>`<div class="hm-ind"><small>${lb}</small><b style="color:${c||'var(--txt)'}">${val}</b><span>${sub||''}</span></div>`;
    const grp=(t,d,tiles)=>{tiles=tiles.filter(Boolean);return tiles.length?`<div class="hm-indg"><div class="hm-indt">${t}${d?` <small>${d}</small>`:''}</div><div class="hm-inds">${tiles.join('')}</div></div>`:'';};
    const ix=k=>idx.find(x=>String(x.name||'').includes(k));
    const ixT=(k,lb,dec=2)=>{const it=ix(k);if(!it||num(it.val)==null)return '';return tile(lb,fmt(it.val),'',`<em style="color:${col(it.chg)}">${pct(it.chg)}</em>${it.d?' '+md(it.d):''}`);};
    if(window.GMKT==='US'){
      const vx=ix('VIX'),sp=ix('利差');
      body.innerHTML=grp('🇺🇸 美股指數','',[ixT('S&P','S&P 500'),ixT('那斯達克','那斯達克'),ixT('道瓊','道瓊')])
        +grp('🌡 風險與資金','',[vx&&num(vx.val)!=null?tile('VIX 恐慌指數',fmt(vx.val),'',`<em style="color:${col(vx.chg)}">${pct(vx.chg)}</em>・${vx.val>=30?'市場很緊張':vx.val>=20?'市場偏緊張':'市場平靜'}`):'',
          sp&&num(sp.val)!=null?tile('美債 10 年 − 2 年利差',sg(sp.val,2,'%'),'',sp.val<0?'短率高於長率(倒掛)':'長率高於短率(正常)'):'',
          num(fx.DXY)!=null?tile('美元指數',fmt(fx.DXY),'','數字越大=美元越強'):''])||'<div class="hm-empty">指標資料還沒到,稍後自動更新。</div>';
      return;
    }
    const T=(M.futtab||[]).filter(r=>r&&r.d),R=T[T.length-1],P=T[T.length-2],C=M.credit||null;
    const streak=k=>{let n=0,dir=0;for(let i=T.length-1;i>=0;i--){const v=num(T[i][k]);if(v==null||v===0)break;const d=v>0?1:-1;if(!dir)dir=d;if(d!==dir)break;n++;}return n>=2?`連 ${n} 天${n>=T.length?'以上':''}${dir>0?'買超':'賣超'}`:(dir>0?'今天買超':dir<0?'今天賣超':'');};
    const flow=(k,lb)=>R&&num(R[k])!=null?tile(lb,sg(R[k],1,' 億'),col(R[k]),streak(k)):'';
    const dlt=(k,unit,dec=0)=>P&&num(R[k])!=null&&num(P[k])!=null?`比前一天 ${sg(R[k]-P[k],dec,unit)}`:'';
    let h='';
    if(R){
      const tot=['f','t','dl'].reduce((a,k)=>a+(num(R[k])||0),0);
      h+=grp('🏦 三大法人今天買賣超',md(R.d),[flow('f','外資'),flow('t','投信'),flow('dl','自營商'),tile('三大法人合計',sg(tot,1,' 億'),col(tot),tot>0?'合計買超':'合計賣超')]);
      const a5=T.slice(-6,-1).map(r=>num(r.amt)).filter(v=>v>0),av=a5.length?a5.reduce((a,b)=>a+b,0)/a5.length:null;
      h+=grp('📈 期貨與選擇權(收盤後公布)',md(R.d),[
        num(R.txf)!=null?tile('外資台指期淨部位',sg(R.txf,0,' 口'),col(R.txf),`${R.txf<0?'淨空單':'淨多單'}・${dlt('txf',' 口')}`):'',
        num(R.t10)!=null?tile('前十大交易人淨部位',sg(R.t10,0,' 口'),col(R.t10),`${R.t10<0?'淨空單':'淨多單'}・${dlt('t10',' 口')}`):'',
        num(R.leek)!=null?tile('散戶多空比',sg(R.leek,1,'%'),'',`${R.leek>0?'散戶偏多':'散戶偏空'}・${dlt('leek',' 點',1)}`):'',
        num(R.pcr)!=null?tile('選擇權 賣權/買權 比',fmt(R.pcr),'',`${R.pcr>=100?'賣權未平倉比買權多':'買權未平倉比賣權多'}・${dlt('pcr','',1)}`):'']);
      const cs=[num(R.amt)!=null?tile('今天成交金額',fmt(Math.round(R.amt))+' 億','',av?`近 5 天平均 ${fmt(Math.round(av))} 億・${R.amt>=av?'比平常多':'比平常少'} ${Math.abs((R.amt/av-1)*100).toFixed(0)}%`:''):''];
      if(C&&num(C.fin)!=null){const H=C.h&&C.h.fin||[],f5=H.length>=6?C.fin-H[H.length-6]:null;
        cs.push(tile('融資餘額',fmt(C.fin)+' 億','',`借錢買股票的總額・${md(C.d)} 比前一天 <em style="color:${col(C.finD)}">${sg(C.finD,1,' 億')}</em>${f5!=null?`・近 5 天 ${sg(f5,1,' 億')}`:''}`));}
      if(num(fx.USDTWD)!=null)cs.push(tile('美元兌台幣',fmt(fx.USDTWD),'','數字變大=台幣變弱(外資匯出時常見)'));
      h+=grp('💰 資金',' ',cs);
    }
    const vx=ix('VIX');
    h+=grp('🌙 美股昨晚','',[ixT('S&P','S&P 500'),ixT('那斯達克','那斯達克'),vx&&num(vx.val)!=null?tile('VIX 恐慌指數',fmt(vx.val),'',`<em style="color:${col(vx.chg)}">${pct(vx.chg)}</em>・${vx.val>=30?'市場很緊張':vx.val>=20?'市場偏緊張':'市場平靜'}`):'']);
    body.innerHTML=h?h+`<details class="tidy-fold hm-indhelp"><summary>這些數字怎麼看(白話)</summary><div class="dim-note">
      <b>三大法人</b>:外資、投信(基金公司)、自營商(券商自己的錢)今天在股票上買的比賣的多多少;紅色=買超、綠色=賣超。<br>
      <b>外資台指期淨部位</b>:外資在期貨上「看漲的單 − 看跌的單」。負的不一定是看壞,外資常用空單替手上的股票保險;重點看空單是變多還是變少。<br>
      <b>前十大交易人</b>:期貨市場最大的 10 個戶頭合起來偏多還是偏空。<br>
      <b>散戶多空比</b>:小額交易人偏多還是偏空;正的=散戶偏多。<br>
      <b>賣權/買權比</b>:高於 100 表示押跌(或買保險)的未平倉比押漲的多。<br>
      <b>融資餘額</b>:大家借錢買股票的總金額;大跌時如果明顯減少,代表借錢買的人被洗出去了。<br>
      這裡只列事實(今天多少、連幾天、比昨天增減),不是買賣訊號;各指標的歷史表格與驗證過的用法在「大盤」分頁。</div></details>`
      :'<div class="hm-empty">指標資料還沒到,稍後自動更新。</div>';
  }

  /* ── 持股:每檔一行(現價、損益、防守、停利) ── */
  async function port(){
    const body=doc.querySelector('#hmPort .hm-body');if(!body)return;
    const arr=(typeof portGet==='function'?portGet():[])||[];
    if(!arr.length){body.innerHTML=`<div class="hm-empty">還沒有持股紀錄。<a href="javascript:void 0" data-go="port">＋ 新增持股</a>,之後這裡會直接告訴你每檔跌到多少該賣、漲到多少可以賣。</div>`;return;}
    const out=[];
    for(const p of arr){
      const s=stock(p.id);if(!s)continue;const us=s.market==='US',px=num(s.price),cost=num(p.cost),pl=px&&cost?(px/cost-1)*100:null;
      let stop='—',tp='—',note='';
      try{const k=await loadK(s);const f=k&&k.ohlc?stockOperationFacts(s,k.ohlc,k.dates,true,cost):null;
        if(f&&f.check&&!f.check.jump&&f.check.liquid){
          const m=p.m||(us?'dip':f.atrp>0&&f.atrp<0.025?'low':'ma');
          if(m==='low'){stop=fmt(f.lowOwn&&f.lowOwn.stop,us);tp=fmt(f.lowOwn&&f.lowOwn.target,us);}
          else if(m==='dip'){stop=fmt(f.ownDip&&f.ownDip.stop,us);tp=fmt(f.ownDip&&f.ownDip.target,us);}
          else{stop=fmt(f.nextBelowPrice,us);tp='跌破季線才賣';}
          const sv=num(String(stop).replace(/[^\d.]/g,'')),tv=num(String(tp).replace(/[^\d.]/g,''));
          if(m==='ma'){if(f.check.below2)note='<span class="hm-tag hm-sell">連 2 天跌破季線,照計畫該賣</span>';else if(f.check.below)note='<span class="hm-tag">已跌破季線 1 天</span>';}
          else if(px&&sv&&px<=sv)note='<span class="hm-tag hm-sell">已跌破,照計畫該賣</span>';
          else if(px&&tv&&px>=tv)note='<span class="hm-tag">已超過目標價,照計畫應已賣</span>';   // r1218
        }else if(s.etf)note='<span class="hm-tag">ETF 不套用買賣規則</span>';else note='<span class="hm-tag">價位待核對</span>';
      }catch(e){}
      out.push(row(s.id,`<span class="hm-nm"><b>${esc(s.name)}</b><small>${esc(s.id)}</small></span>
        <span class="hm-px"><b>${fmt(px,us)}</b><small style="color:${col(s.chg)}">${pct(s.chg)}</small></span>
        <span class="hm-pl" style="color:${col(pl)}">${pl==null?'—':(pl>0?'+':'')+pl.toFixed(1)+'%'}<small>成本 ${fmt(cost,us)}</small></span>
        <span class="hm-lv"><span>🛑 跌破 ${stop} 賣</span><span>🎯 ${/季線/.test(tp)?tp:'目標 '+tp}</span></span>`,note));
    }
    body.innerHTML=`<div class="hm-thead"><span>股票</span><span>現價</span><span>賺賠</span><span>什麼時候賣</span></div>`+out.join('');
  }

  /* ── 最愛:每檔一行(該做什麼、買進/防守/賣出);可買的排前面 ── */
  async function fav(){
    const body=doc.querySelector('#hmFav .hm-body');if(!body)return;
    const ids=(typeof favList==='function'?favList():[])||[];
    if(!ids.length){body.innerHTML=`<div class="hm-empty">${typeof SB_USER!=='undefined'&&!SB_USER?'登入後才看得到你的最愛。':'還沒有最愛。'}在個股頁點名稱旁的 ☆ 就能加入,這裡會列出每檔「現在能不能買、買在多少、跌到多少要賣」。</div>`;return;}
    const rows=[];
    for(const id of ids){
      const s=stock(id);if(!s||s.etf)continue;const us=s.market==='US';
      let m=null;
      try{const k=await loadK(s);if(k&&k.ohlc&&typeof ownStrategySummary==='function'&&typeof StockCardSummary!=='undefined'){const en=typeof favEntryOf==='function'?favEntryOf(id):null;m=StockCardSummary.fromHTML(ownStrategySummary(s,k.ohlc,k.dates,!!en,en&&en.px),doc);}}catch(e){}
      const act=m?m.action:'資料載入中';const ready=/已確認|開盤/.test(act),blocked=/先不買|待核對|過期|不追|不適用/.test(act);
      rows.push({ready,html:row(s.id,`<span class="hm-nm"><b>${esc(s.name)}</b><small>${esc(s.id)}</small></span>
        <span class="hm-px"><b>${fmt(s.price,us)}</b><small style="color:${col(s.chg)}">${pct(s.chg)}</small></span>
        <span class="hm-act ${ready?'go':blocked?'no':''}">${esc(act)}</span>
        <span class="hm-lv"><span>買點 ${esc(m?m.buy:'—')}</span><span>🛑 跌破 ${esc(m?m.stop:'—')} 賣</span><span>🎯 ${m&&/季線/.test(m.sell)?esc(m.sell):'目標 '+esc(m?m.sell:'—')}</span></span>`)});
    }
    rows.sort((a,b)=>b.ready-a.ready);
    body.innerHTML=`<div class="hm-thead"><span>股票</span><span>現價</span><span>現在該做什麼</span><span>買點 / 跌破就賣 / 目標</span></div>`+rows.map(r=>r.html).join('');
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
      const st=p.st==='pend'?'<span class="hm-tag hm-buy">下個交易日開盤買</span>':`<span class="hm-tag">持有 ${p.days||0} 天</span>`;
      out.push(row(p.cur||p.id,`<span class="hm-nm"><b>${esc(p.name||p.id)}</b><small>${nm[k]}・${esc(p.cur||p.id)}</small></span>
        <span class="hm-px"><b>${fmt(px,us)}</b><small>${p.entry?'買在 '+fmt(p.entry,us):'選到時 '+fmt(p.sel_px,us)}${p.w&&p.w!==1?'・'+(+p.w).toFixed(2)+'×':''}</small></span>
        <span class="hm-pl" style="color:${col(ret)}">${ret==null?'—':(ret>0?'+':'')+ret.toFixed(1)+'%'}</span>
        <span class="hm-lv"><span>🛑 跌破 ${sl} 賣</span><span>🎯 目標 ${tp}</span></span>`,st));});});
    const pause=M.short&&M.short.pause&&M.short.pause.d===M.short.sel_d?`<div class="hm-note">⏸ ${esc(M.short.pause.msg)}——短期清單這週先不買新股</div>`:'';
    body.innerHTML=pause+(out.length?`<div class="hm-thead"><span>股票</span><span>現價</span><span>賺賠</span><span>什麼時候賣</span></div>`+out.slice(0,6).join('')+(out.length>6?`<details class="hm-more"><summary>其餘 ${out.length-6} 檔</summary>${out.slice(6).join('')}</details>`:''):'<div class="hm-empty">三個清單目前都沒有持股。</div>');
  }

  /* ── 早報前 3 則 ── */
  async function news(){
    const body=doc.querySelector('#hmNews .hm-body');if(!body)return;
    try{const j=await newsFetch();const items=(j&&j.items||[]).map((x,i)=>({x,i})).sort((a,b)=>(b.x.lv-a.x.lv)||(a.i-b.i)).map(o=>o.x).slice(0,3);
      body.innerHTML=(j&&j.mood?`<div class="hm-head">${esc(j.mood)}</div>`:'')+items.map(x=>`<div class="hm-news"><b>${esc(x.title)}</b><span>${esc(x.why||x.what||'')}</span>${(x.codes||[]).length?`<span class="hm-codes">${x.codes.slice(0,4).map(c=>`<a href="#stock/${encodeURIComponent(c.id)}">${esc(c.n)}</a>`).join('')}</span>`:''}</div>`).join('')||'<div class="hm-empty">今天的早報還沒產生。</div>';
    }catch(e){body.innerHTML='<div class="hm-empty">早報載入失敗,點「看全部」重試。</div>';}
  }

  /* ── 每天學一點:今日一課・今日好書・節目重點・產業新聞(learn_daily.py,永久累積) ── */
  let LD=null;
  async function learnLoad(){if(LD)return LD;try{const r=await fetch('learn_daily.json?v='+Math.floor(Date.now()/600e3));if(r.ok)LD=await r.json();}catch(e){}return LD;}
  window.__learnLoad=learnLoad;
  async function learn(){
    const body=doc.querySelector('#hmLearn .hm-body');if(!body)return;
    const D=await learnLoad();const d=D&&D.days&&D.days[(D.dates||[]).slice(-1)[0]];
    if(!d){body.innerHTML='<div class="hm-empty">每天早上 6:35 早報之後產生,第一天還沒到。</div>';return;}
    const L=d.lesson,md=x=>String(x||'').slice(5).replace('-','/');
    const lesson=L?`<div class="ld-lesson"><div class="ld-k">今日一課 <small>${md(d.d)}</small></div><b class="ld-t">${esc(L.title)}</b><div class="ld-one">${esc(d.one_line||L.what)}</div>
      <details class="ld-more"><summary>看整課</summary><p><b>是什麼</b>:${esc(L.what)}</p><p><b>今天為什麼重要</b>:${esc(L.why_today)}</p><p><b>下次怎麼用</b>:${esc(L.how)}</p></details></div>`
      :`<div class="ld-lesson"><div class="ld-k">今日一課</div><div class="dim">今天的課還在產生(早報之後),先看下面的好書與節目。</div></div>`;
    const B=d.book,book=B?`<div class="ld-book"><div class="ld-k">今日好書</div><b>《${esc(B.title)}》</b>${B.author?` <small>${esc(B.author)}</small>`:''}<div class="dim">${esc(B.pick_why||B.why||'')}</div>${B.url?`<a href="${esc(B.url)}" target="_blank" rel="noopener">看這本書 ›</a>`:''}</div>`:'';
    const shows=(d.shows||[]).filter(s=>s.pts&&s.pts.length).map(s=>`<div class="ld-show"><div class="ld-k">${esc(s.name)} <small>${md(s.dt)}</small></div><div>${esc(s.pts[0])}</div>${s.url?`<a href="${esc(s.url)}" target="_blank" rel="noopener">聽這集 ›</a>`:''}</div>`).join('');
    const groups=(d.groups||[]).slice(0,8).map(g=>`<span class="ld-chip" data-go="news">${esc(g.g)} <b>${g.n}</b></span>`).join('');
    body.innerHTML=lesson+`<div class="ld-grid">${book}${shows}</div>`+(groups?`<div class="ld-k" style="margin-top:8px">今天產業新聞</div><div class="ld-chips">${groups}</div>`:'');
  }
  /* ── 未來產業:趨勢一行一個(階段・名稱・幾檔相關台股) ── */
  async function trend(){
    const body=doc.querySelector('#hmTrend .hm-body');if(!body)return;
    let T=null;try{T=typeof trendsLoad==='function'?await trendsLoad():null;}catch(e){}
    if(!T||!(T.trends||[]).length){body.innerHTML='<div class="hm-empty">每天早上跟著早報產生。</div>';return;}
    const stC={'萌芽':'var(--t-blue)','成形':'var(--up)','主流':'var(--amber)','過熱':'var(--down)'};
    body.innerHTML=T.trends.slice(0,6).map(t=>`<div class="hm-row hm-trend" data-go="trend" role="link" tabindex="0"><span class="news-cat" style="color:${stC[t.stage]||'var(--txt2)'};border-color:${stC[t.stage]||'var(--line)'}">${esc(t.stage)}</span><span class="hm-nm"><b>${esc(t.name)}</b><small>${esc(t.horizon||'1~3 年')}・${(t.tw||[]).length} 檔相關台股${t.current_streak_days>1?'・連續 '+t.current_streak_days+' 天':''}</small></span><span class="dim" style="font-size:12.5px;line-height:1.5">${esc(String(t.thesis||'').slice(0,42))}…</span></div>`).join('');
  }
  async function render(force){
    if(busy||(!force&&Date.now()-lastRun<60e3))return;busy=true;lastRun=Date.now();
    pane();
    for(let i=0;i<60&&!((window.DATA&&DATA.stocks||[]).length);i++)await new Promise(r=>setTimeout(r,250));   // 主資料還沒到先等
    try{ind();}catch(e){}
    try{await Promise.all([mkt(),news(),aip(),learn(),trend()]);}catch(e){}
    try{if(typeof lvLoad==='function')await lvLoad();}catch(e){}   // 還原因子(ADJ1)沒載入時價位算不出來(手機上常見)
    /* r1235:總覽不再放持股、最愛(各自有分頁,底部列一按就到);port()/fav() 保留但不呼叫 */
    busy=false;
  }
  window.HomeView={render,pane};
  pane();
})();
