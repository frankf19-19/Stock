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
      p.addEventListener('click',e=>{if(e.target.closest('a[href^="#stock/"],a[target="_blank"]'))return;const gs=e.target.closest('[data-gosec]');if(gs){e.preventDefault();goSec(gs.dataset.gosec);return;}
        if(!e.target.closest('a,summary,details.hm-indhelp')){const it=e.target.closest('[data-ind]');if(it){openInd(it.dataset.ind);return;}}
        const g=e.target.closest('[data-go]');if(g){e.preventDefault();go(g.dataset.go);return;}
        const r=e.target.closest('[data-sid]');if(r){location.hash='#stock/'+encodeURIComponent(r.dataset.sid);}});
      p.addEventListener('keydown',e=>{if(e.key!=='Enter'&&e.key!==' ')return;const it=e.target.closest('[data-ind],[data-go][role],[data-sid]');if(it&&it===e.target){e.preventDefault();it.click();}});
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
    const usM=window.GMKT==='US';const chips=(usM?[['S&P','S&P 500'],['那斯達克','那斯達克']]:[['加權','加權'],['櫃買','櫃買']]).map(([k,lb])=>{const it=pick(k);if(!it)return '';return `<span class="hm-idx" data-go="macro" role="link" tabindex="0" style="cursor:pointer"><small>${lb}</small><b>${fmt(it.val)}</b><em style="color:${col(it.chg)}">${pct(it.chg)}</em>${it.d?`<small>${String(it.d).slice(5).replace('-','/')} 收盤</small>`:''}</span>`;}).join('');
    let head='',br='';
    let vtag='';try{const j=await viewFetch();if(j&&j.head){head=j.head;if(j.date)vtag=`${String(j.date).slice(5).replace('-','/')} ${j.slot==='pm'?'晚上':'早上'}版`;}}catch(e){}
    if(!usM)try{if(typeof SECSTR==='undefined'||!SECSTR){if(typeof secStrLoad==='function')secStrLoad();}const a=SECSTR&&+SECSTR.a60;if(a>0){const pc=Math.round(a*100)===35?(a*100).toFixed(1):Math.round(a*100);br=`<span class="hm-br">有成交量的股票${a<0.5?'只有':''} <b>${pc}%</b> 在近 3 個月平均價之上${SECSTR.asof?'('+String(SECSTR.asof).slice(5).replace('-','/')+')':''}・${a<0.35?'<b style="color:var(--up)">大盤一起大跌,跌深的好股票可以撿</b>':a<0.45?'大盤偏弱,接近跌深買點門檻 35%':a<0.6?'大盤普通':'大盤強'}</span>`;};}catch(e){}
    box.innerHTML=`<div class="hm-mkt"><div class="hm-idxs">${chips||'<span class="dim">指數載入中…</span>'}${br}</div>
      ${head?`<div class="hm-head" data-go="macro" role="link" tabindex="0" style="cursor:pointer">🧭 ${esc(head)}${vtag?` <small class="dim" style="font-weight:400;font-size:12px">(盤勢解讀 ${vtag})</small>`:''}</div>`:''}
      <div class="hm-links"><a href="javascript:void 0" data-go="macro">大盤與今日盤勢 ›</a><a href="javascript:void 0" data-go="news">產業早報 ›</a></div></div>`;
  }

  /* ── r1235 大盤重要指標(Frank 11/12:總覽不放持股/最愛,改放三大法人、期貨、融資這些)
        全部讀既有資料(DATA.macro.futtab / credit / idx / fx),只陳述事實(今天多少、連幾天、比昨天增減),不下買賣判斷 ── */
  async function ind(){
    const body=doc.querySelector('#hmInd .hm-body');if(!body)return;
    let Y=null,ME=null;try{if(typeof yextData==='function')Y=await yextData();}catch(e){}
    try{if(typeof marginEstLoad==='function')ME=await marginEstLoad();}catch(e){}
    const M=(window.DATA&&DATA.macro)||{},idx=M.idx||[],fx=M.fx||{};
    const md=d=>d?String(d).replace(/\//g,'-').slice(5).replace('-','/'):'';
    const sg=(v,dec=1,unit='')=>{v=num(v);return v==null?'—':(v>0?'+':'')+v.toLocaleString(undefined,{minimumFractionDigits:dec,maximumFractionDigits:dec})+unit;};
    const tile=(lb,val,c,sub,key)=>`<div class="hm-ind"${key?` data-ind="${key}" role="button" tabindex="0" title="點開看走勢與說明"`:''}><small>${lb}${key?'<i>›</i>':''}</small><b style="color:${c||'var(--txt)'}">${val}</b><span>${sub||''}</span></div>`;
    const grp=(t,d,tiles,sec)=>{tiles=tiles.filter(Boolean);return tiles.length?`<div class="hm-indg"><div class="hm-indt">${t}${d?` <small>${d}</small>`:''}${sec?`<a href="javascript:void 0" data-gosec="${sec}">完整表格 ›</a>`:''}</div><div class="hm-inds">${tiles.join('')}</div></div>`:'';};
    const ix=k=>idx.find(x=>String(x.name||'').includes(k));
    const ixT=(k,lb,dec=2)=>{const it=ix(k);if(!it||num(it.val)==null)return '';return tile(lb,fmt(it.val),'',`<em style="color:${col(it.chg)}">${pct(it.chg)}</em>${it.d?' '+md(it.d):''}`,'ix:'+k);};
    /* r1236:費半(yext ^SOX)、台積電 ADR(站內美股 TSM;1 張 ADR = 5 股台積電)、大盤融資維持率(margin_est.json) */
    const soxT=()=>{try{const E=Y&&Y.series&&Y.series['^SOX'];if(!E)return '';let v=null,pv=null,ts=null;
      const m=E.m;if(m&&m.c&&m.c.length&&m.prev>0){v=m.c[m.c.length-1];pv=m.prev;ts=m.t&&m.t[m.t.length-1];}   // 日線序列會慢一兩天,優先用分鐘資料(最新價 vs 前一天收盤)
      else{const d=E.d,c=d&&d.c,n=c&&c.length;if(n>=2){v=c[n-1];pv=c[n-2];ts=d.t[n-1];}}
      if(!(v>0&&pv>0))return '';const ch=(v/pv-1)*100;let dt='';
      try{if(ts){const D=new Date(ts*1000),live=Date.now()-ts*1000<25*60e3;dt=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',month:'2-digit',day:'2-digit'}).format(D).replace('-','/')+(live?' 盤中':' 美東');}}catch(e){}
      return tile('費城半導體指數',fmt(v),'',`<em style="color:${col(ch)}">${pct(ch)}</em> ${dt}・台股電子股常跟著它走`,'ix:SOX');}catch(e){return '';}};
    const adrT=()=>{try{const t=stock('TSM'),w=stock('2330');if(!t||!(num(t.price)>0))return '';let sub=`<em style="color:${col(t.chg)}">${pct(t.chg)}</em>`;
      if(w&&num(w.price)>0&&num(fx.USDTWD)>0){const eq=t.price*fx.USDTWD/5,pm=(eq/w.price-1)*100;sub+=`・換算約 ${fmt(Math.round(eq))} 元,比台股台積電 ${fmt(w.price)} ${pm>=0?'貴':'便宜'} ${Math.abs(pm).toFixed(1)}%`;}
      return tile('台積電 ADR(美股)','$'+fmt(t.price),'',sub,'stock:TSM');}catch(e){return '';}};
    if(window.GMKT==='US'){
      const vx=ix('VIX'),sp=ix('利差');
      body.innerHTML=grp('🇺🇸 美股指數','',[ixT('S&P','S&P 500'),ixT('那斯達克','那斯達克'),ixT('道瓊','道瓊'),soxT(),adrT()])
        +grp('🌡 風險與資金','',[vx&&num(vx.val)!=null?tile('VIX 恐慌指數',fmt(vx.val),'',`<em style="color:${col(vx.chg)}">${pct(vx.chg)}</em>・${vx.val>=30?'市場很緊張':vx.val>=20?'市場偏緊張':'市場平靜'}`,'ix:VIX'):'',
          sp&&num(sp.val)!=null?tile('美債 10 年 − 2 年利差',sg(sp.val,2,'%'),'',sp.val<0?'短率高於長率(倒掛)':'長率高於短率(正常)','go:macro'):'',
          num(fx.DXY)!=null?tile('美元指數',fmt(fx.DXY),'','數字越大=美元越強','ix:DXY'):''])||'<div class="hm-empty">指標資料還沒到,稍後自動更新。</div>';
      return;
    }
    const T=(M.futtab||[]).filter(r=>r&&r.d),R=T[T.length-1],P=T[T.length-2],C=M.credit||null;
    const streak=k=>{let n=0,dir=0;for(let i=T.length-1;i>=0;i--){const v=num(T[i][k]);if(v==null||v===0)break;const d=v>0?1:-1;if(!dir)dir=d;if(d!==dir)break;n++;}return n>=2?`連 ${n} 天${n>=T.length?'以上':''}${dir>0?'買超':'賣超'}`:(dir>0?'今天買超':dir<0?'今天賣超':'');};
    const flow=(k,lb)=>R&&num(R[k])!=null?tile(lb,sg(R[k],1,' 億'),col(R[k]),streak(k),'ft:'+k):'';
    const dlt=(k,unit,dec=0)=>P&&num(R[k])!=null&&num(P[k])!=null?`比前一天 ${sg(R[k]-P[k],dec,unit)}`:'';
    let h='';
    if(R){
      const tot=['f','t','dl'].reduce((a,k)=>a+(num(R[k])||0),0);
      h+=grp('🏦 三大法人今天買賣超',md(R.d),[flow('f','外資'),flow('t','投信'),flow('dl','自營商'),tile('三大法人合計',sg(tot,1,' 億'),col(tot),tot>0?'合計買超':'合計賣超','ft:tot')],'mk_fut');
      const a5=T.slice(-6,-1).map(r=>num(r.amt)).filter(v=>v>0),av=a5.length?a5.reduce((a,b)=>a+b,0)/a5.length:null;
      h+=grp('📈 期貨與選擇權(收盤後公布)',md(R.d),[
        num(R.txf)!=null?tile('外資台指期淨部位',sg(R.txf,0,' 口'),col(R.txf),`${R.txf<0?'淨空單':'淨多單'}・${dlt('txf',' 口')}`,'ft:txf'):'',
        num(R.t10)!=null?tile('前十大交易人淨部位',sg(R.t10,0,' 口'),col(R.t10),`${R.t10<0?'淨空單':'淨多單'}・${dlt('t10',' 口')}`,'ft:t10'):'',
        num(R.leek)!=null?tile('散戶多空比',sg(R.leek,1,'%'),'',`${R.leek>0?'散戶偏多':'散戶偏空'}・${dlt('leek',' 點',1)}`,'ft:leek'):'',
        num(R.pcr)!=null?tile('選擇權 賣權/買權 比',fmt(R.pcr),'',`${R.pcr>=100?'賣權未平倉比買權多':'買權未平倉比賣權多'}・${dlt('pcr','',1)}`,'ft:pcr'):''],'mk_fut');
      const cs=[num(R.amt)!=null?tile('今天成交金額',fmt(Math.round(R.amt))+' 億','',av?`近 5 天平均 ${fmt(Math.round(av))} 億・${R.amt>=av?'比平常多':'比平常少'} ${Math.abs((R.amt/av-1)*100).toFixed(0)}%`:'','ft:amt'):''];
      if(C&&num(C.fin)!=null){const H=C.h&&C.h.fin||[],f5=H.length>=6?C.fin-H[H.length-6]:null;
        cs.push(tile('融資餘額',fmt(C.fin)+' 億','',`借錢買股票的總額・${md(C.d)} 比前一天 <em style="color:${col(C.finD)}">${sg(C.finD,1,' 億')}</em>${f5!=null?`・近 5 天 ${sg(f5,1,' 億')}`:''}`,'fin'));}
      try{const K=ME&&ME.mkt;if(K&&K.r>0&&typeof marginLevel==='function'){const lv=marginLevel(K.r),H=(K.h||[]).map(x=>x[1]),p5=H.length>5?H[H.length-6]:null;
        cs.push(tile('大盤融資維持率(上市)',`${K.r.toFixed(1)}%`,lv.c,`<em style="color:${lv.c}">${lv.k}</em>・${lv.t.split(';')[0]}${p5!=null?`・比 5 天前 ${(K.r-p5>=0?'+':'')+(K.r-p5).toFixed(1)} 點`:''}・${md(K.d)}`,'mrate'));}}catch(e){}
      if(num(fx.USDTWD)!=null)cs.push(tile('美元兌台幣',fmt(fx.USDTWD),'','數字變大=台幣變弱(外資匯出時常見)','fx'));
      h+=grp('💰 資金',' ',cs);
    }
    const vx=ix('VIX');
    h+=grp('🌙 美股昨晚','',[ixT('S&P','S&P 500'),ixT('那斯達克','那斯達克'),soxT(),adrT(),vx&&num(vx.val)!=null?tile('VIX 恐慌指數',fmt(vx.val),'',`<em style="color:${col(vx.chg)}">${pct(vx.chg)}</em>・${vx.val>=30?'市場很緊張':vx.val>=20?'市場偏緊張':'市場平靜'}`,'ix:VIX'):'']);
    body.innerHTML=h?h+`<details class="tidy-fold hm-indhelp"><summary>這些數字怎麼看(白話)</summary><div class="dim-note">
      <b>三大法人</b>:外資、投信(基金公司)、自營商(券商自己的錢)今天在股票上買的比賣的多多少;紅色=買超、綠色=賣超。<br>
      <b>外資台指期淨部位</b>:外資在期貨上「看漲的單 − 看跌的單」。負的不一定是看壞,外資常用空單替手上的股票保險;重點看空單是變多還是變少。<br>
      <b>前十大交易人</b>:期貨市場最大的 10 個戶頭合起來偏多還是偏空。<br>
      <b>散戶多空比</b>:小額交易人偏多還是偏空;正的=散戶偏多。<br>
      <b>賣權/買權比</b>:高於 100 表示押跌(或買保險)的未平倉比押漲的多。<br>
      <b>融資餘額</b>:大家借錢買股票的總金額;大跌時如果明顯減少,代表借錢買的人被洗出去了。<br>
      <b>大盤融資維持率</b>:借錢買的股票現在值多少 ÷ 借了多少錢。剛買進大約 166.7%;掉到 130% 以下券商會要求補錢,不補就會被賣掉。數字越低=借錢買的人壓力越大。<br>
      <b>費城半導體指數</b>:美國半導體股的指數;台積電和台股電子股常跟著它的方向走。<br>
      <b>台積電 ADR</b>:台積電在美國掛牌的股票,台股開盤前可以先看它昨晚漲跌;「貴/便宜」是換算回台幣後跟台股台積電比。<br>
      這裡只列事實(今天多少、連幾天、比昨天增減),不是買賣訊號;各指標的歷史表格與驗證過的用法在「大盤」分頁。</div></details>`
      :'<div class="hm-empty">指標資料還沒到,稍後自動更新。</div>';
  }

  /* ── r1237 指標卡點開:近期走勢圖 + 每天數字 + 白話說明 + 到大盤頁完整表格(Frank:所有卡片都要能點進去看) ── */
  const IND={
    'ft:f':{t:'外資買賣超',u:' 億',bar:1,sec:'mk_fut',h:'外資今天在台股買的金額減掉賣的金額。紅色=買超、綠色=賣超。外資資金大,連續多天同方向時對大盤影響最明顯;單一天的數字起伏很大,看「連續幾天」比看單日有用。'},
    'ft:t':{t:'投信買賣超',u:' 億',bar:1,sec:'mk_fut',h:'投信就是基金公司。金額比外資小,但常集中買中小型股;季底、年底前有作帳行情時比較積極。'},
    'ft:dl':{t:'自營商買賣超',u:' 億',bar:1,sec:'mk_fut',h:'自營商是券商用自己的錢買賣,進出很快,而且有一部分是為了避險,參考性比外資、投信低。'},
    'ft:tot':{t:'三大法人合計買賣超',u:' 億',bar:1,sec:'mk_fut',h:'外資 + 投信 + 自營商加起來。合計買超而指數卻跌,代表賣壓來自散戶或大股東;反過來也一樣。'},
    'ft:txf':{t:'外資台指期淨部位',u:' 口',bar:1,dec:0,sec:'mk_fut',h:'外資在台指期貨上「看漲的單 − 看跌的單」。負的=淨空單。外資手上有大量股票,常用期貨空單當保險,所以長期是負的很正常;重點是空單在增加(更保守)還是減少(比較放心)。'},
    'ft:t10':{t:'前十大交易人淨部位',u:' 口',bar:1,dec:0,sec:'mk_fut',h:'期貨市場部位最大的 10 個戶頭合起來偏多還是偏空。正的=淨多單。這群人資金大、資訊多,方向突然翻轉時值得留意。'},
    'ft:leek':{t:'散戶多空比',u:'%',dec:1,sec:'mk_fut',h:'小額交易人(散戶)在小型台指期上偏多還是偏空。正的=散戶偏多。市場上常把它當反向參考,但站內沒有驗證過「散戶偏多就會跌」,只列事實。'},
    'ft:pcr':{t:'選擇權 賣權/買權 比',u:'',dec:1,sec:'mk_fut',h:'賣權未平倉量 ÷ 買權未平倉量 × 100。高於 100 表示賣權比較多。賣權多可能是有人押跌,也可能是大戶賣出賣權在撐盤,所以單看這個數字不能判斷方向,要看它的變化。'},
    'ft:amt':{t:'每天成交金額',u:' 億',bar:2,dec:0,sec:'mk_fut',h:'上市股票一整天的成交金額。上漲時量放大=有人追;下跌時量放大=有人急著賣;量很小代表大家在觀望。'},
    'fin':{t:'融資餘額',u:' 億',dec:1,sec:'mk_risk',h:'大家跟券商借錢買股票的總金額(上市)。一路增加代表散戶槓桿越開越大;大跌時如果快速減少,代表借錢買的人被迫賣出或認賠,通常要等它減到一個程度賣壓才會輕。'},
    'mrate':{t:'大盤融資維持率(上市)',u:'%',dec:1,sec:'mk_temp',ref:[[166.7,'剛買進'],[130,'追繳線']],h:'借錢買的股票現在值多少 ÷ 借了多少錢。剛買進大約 166.7%;掉到 130% 以下券商會要求補錢,不補就會被賣掉。數字越低=借錢買的人壓力越大。用公開數字直接算,只含站內有收錄的股票,會略偏低。'},
    'fx':{t:'美元兌台幣',u:'',sec:'mk_ext',h:'1 美元換多少台幣。數字變大=台幣變弱,常見於外資把錢匯出去的時候;數字變小=台幣變強,常見於外資匯入。'},
    'ix:S&P':{t:'S&P 500',y:'^GSPC',h:'美國 500 家大公司的指數,代表美股整體。台股開盤常會先反應它前一晚的漲跌。'},
    'ix:那斯達克':{t:'那斯達克',y:'^IXIC',h:'美國科技股為主的指數。台股電子股比重高,跟它的連動比跟 S&P 500 還明顯。'},
    'ix:道瓊':{t:'道瓊工業',y:'^DJI',h:'美國 30 家老牌大公司的指數,傳統產業比重高。'},
    'ix:SOX':{t:'費城半導體指數',y:'^SOX',h:'美國 30 檔半導體股的指數(輝達、博通、台積電 ADR 都在裡面)。台積電和台股電子股常跟著它的方向走,是台股開盤前最值得看的一個數字。走勢圖用每天收盤,會比上面的最新數字慢一到兩天。'},
    'ix:VIX':{t:'VIX 恐慌指數',y:'^VIX',ref:[[20,'偏緊張'],[30,'很緊張']],h:'用選擇權價格算出來的「市場預期未來一個月會多震盪」。20 以下算平靜,20~30 偏緊張,30 以上很緊張。通常股市大跌時它會衝高。'},
    'ix:DXY':{t:'美元指數',y:'DX-Y.NYB',h:'美元對一籃子主要貨幣的強弱。美元變強時,資金容易從新興市場(包含台股)流出。'}
  };
  async function indSeries(key){
    const M=(window.DATA&&DATA.macro)||{},S=IND[key];let out=[];
    try{
      if(key.startsWith('ft:')){const k=key.slice(3);out=(M.futtab||[]).filter(r=>r&&r.d).map(r=>[r.d,k==='tot'?['f','t','dl'].reduce((a,x)=>a+(num(r[x])||0),0):num(r[k])]);}
      else if(key==='fin'){const H=(M.credit||{}).h||{};out=(H.d||[]).map((d,i)=>[d,num((H.fin||[])[i])]);}
      else if(key==='mrate'){const ME=typeof marginEstLoad==='function'?await marginEstLoad():null;out=((ME&&ME.mkt&&ME.mkt.h)||[]).map(x=>[x[0],num(x[1])]);}
      else if(S&&S.y){const Y=typeof yextData==='function'?await yextData():null,d=Y&&Y.series&&Y.series[S.y]&&Y.series[S.y].d;
        if(d&&d.c)out=d.c.map((c,i)=>[new Date(d.t[i]*1000).toISOString().slice(0,10),num(c)]).slice(-90);}
    }catch(e){}
    return out.filter(x=>x[1]!=null);
  }
  async function openInd(key){
    if(key.startsWith('stock:')){location.hash='#stock/'+encodeURIComponent(key.slice(6));return;}
    if(key.startsWith('go:')){go(key.slice(3));return;}
    const S=IND[key];if(!S)return;
    let dlg=doc.getElementById('hmIndDlg');
    if(!dlg){dlg=doc.createElement('dialog');dlg.id='hmIndDlg';dlg.className='hm-dlg';doc.body.append(dlg);
      dlg.addEventListener('click',e=>{if(e.target===dlg||e.target.closest('[data-close]'))dlg.close();const g=e.target.closest('[data-dsec]');if(g){dlg.close();goSec(g.dataset.dsec);}});
}
    const L=await indSeries(key),dec=S.dec??(S.y?2:1),u=S.u||'',md=d=>String(d).slice(5).replace('-','/');
    const f=v=>(S.bar===1&&v>0?'+':'')+(+v).toLocaleString(undefined,{minimumFractionDigits:dec,maximumFractionDigits:dec})+u;
    const last=L[L.length-1],vals=L.map(x=>x[1]),hi=vals.length?Math.max(...vals):null,lo=vals.length?Math.min(...vals):null;
    const fxNow=key==='fx'?((window.DATA&&DATA.macro&&DATA.macro.fx)||{}):null;
    const rows=L.slice().reverse().slice(0,30).map((x,i,a)=>{const pv=a[i+1],d=pv?x[1]-pv[1]:null;return `<tr><td>${md(x[0])}</td><td style="color:${S.bar===1?col(x[1]):'inherit'}">${f(x[1])}</td><td style="color:${col(d)}">${d==null?'—':(d>0?'+':'')+d.toLocaleString(undefined,{minimumFractionDigits:dec,maximumFractionDigits:dec})}</td></tr>`;}).join('');
    dlg.innerHTML=`<div class="hm-dlg-in"><div class="hm-dlg-h"><h3>${esc(S.t)}</h3><button type="button" data-close aria-label="關閉">關閉 ✕</button></div>
      ${last?`<div class="hm-dlg-now"><b style="color:${S.bar===1?col(last[1]):'var(--txt)'}">${f(last[1])}</b><span>${md(last[0])}${L.length>1?`・近 ${L.length} 個交易日最高 ${f(hi)}、最低 ${f(lo)}`:''}</span></div>`
        :fxNow?`<div class="hm-dlg-now"><b>${fmt(fxNow.USDTWD)}</b><span>目前匯率${num(fxNow.JPYTWD)?`・日圓 ${fxNow.JPYTWD}`:''}${num(fxNow.DXY)?`・美元指數 ${fmt(fxNow.DXY)}`:''}</span></div>`:'<div class="hm-empty">這個指標的歷史資料還沒到。</div>'}
      <p class="hm-dlg-help">${esc(S.h)}</p>
      ${L.length>1?`<div class="hm-dlg-ch" id="hmIndCh"></div><div class="hm-dlg-tb"><table><thead><tr><th>日期</th><th>數值</th><th>比前一天</th></tr></thead><tbody>${rows}</tbody></table></div>`:''}
      <p class="dim-note" style="margin:8px 0 0">只列事實,不是買賣訊號。</p>
      ${S.sec?`<button type="button" class="hm-dlg-go" data-dsec="${S.sec}">到「大盤」頁看完整表格與相關指標 ›</button>`:S.y?`<button type="button" class="hm-dlg-go" data-dsec="mk_idx">到「大盤」頁看更多 ›</button>`:''}</div>`;
    if(!dlg.open)dlg.showModal();
    try{const el=doc.getElementById('hmIndCh');if(el&&L.length>1){   // 自己畫 SVG(不依賴外部圖表庫,開得快、離線也有)
      const W=600,H=210,pl=6,pr=6,pt=12,pb=22,bar=!!S.bar,n=L.length,refs=(S.ref||[]).filter(r=>r[0]>=lo*0.9&&r[0]<=hi*1.1);
      let mn=Math.min(lo,...refs.map(r=>r[0])),mx=Math.max(hi,...refs.map(r=>r[0]));if(bar){mn=Math.min(mn,0);mx=Math.max(mx,0);}
      const pad=(mx-mn)*0.06||1;if(!bar||mn<0)mn-=pad;mx+=pad;if(bar&&mn>=0)mn=0;
      const X=i=>pl+(W-pl-pr)*(n===1?.5:(i+(bar?.5:0))/(bar?n:n-1)),Yv=v=>pt+(H-pt-pb)*(1-(v-mn)/(mx-mn)),bw=Math.max(2,(W-pl-pr)/n*0.68);
      let g='';
      if(bar)g+=`<line x1="${pl}" x2="${W-pr}" y1="${Yv(0)}" y2="${Yv(0)}" stroke="var(--line)"/>`+L.map((x,i)=>{const y0=Yv(0),y1=Yv(x[1]);return `<rect x="${(X(i)-bw/2).toFixed(1)}" y="${Math.min(y0,y1).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1,Math.abs(y1-y0)).toFixed(1)}" rx="2" fill="${S.bar===2?'var(--amber)':x[1]>=0?'var(--up)':'var(--down)'}"><title>${md(x[0])} ${f(x[1])}</title></rect>`;}).join('');
      else g+=`<polyline fill="none" stroke="var(--amber)" stroke-width="2.2" stroke-linejoin="round" points="${L.map((x,i)=>X(i).toFixed(1)+','+Yv(x[1]).toFixed(1)).join(' ')}"/><circle cx="${X(n-1).toFixed(1)}" cy="${Yv(L[n-1][1]).toFixed(1)}" r="4" fill="var(--amber)"/>`;
      g+=refs.map(r=>`<line x1="${pl}" x2="${W-pr}" y1="${Yv(r[0])}" y2="${Yv(r[0])}" stroke="var(--txt2)" stroke-dasharray="5 4" opacity=".7"/><text x="${W-pr}" y="${Yv(r[0])-4}" text-anchor="end" font-size="12" fill="var(--txt2)">${esc(r[1])} ${r[0]}</text>`).join('');
      const ticks=[0,Math.floor((n-1)/2),n-1].filter((v,i,a)=>a.indexOf(v)===i);
      g+=ticks.map(i=>`<text x="${X(i).toFixed(1)}" y="${H-5}" text-anchor="${i===0?'start':i===n-1?'end':'middle'}" font-size="12" fill="var(--txt2)">${md(L[i][0])}</text>`).join('');
      g+=`<text x="${pl}" y="${pt}" font-size="12" fill="var(--txt2)">${f(hi)}</text>`+(bar&&lo>=0?'':`<text x="${pl}" y="${H-pb-3}" font-size="12" fill="var(--txt2)">${f(lo)}</text>`);
      el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%;height:100%;display:block" role="img" aria-label="${esc(S.t)} 近 ${n} 個交易日走勢">${g}</svg>`;}}catch(e){}
  }
  function goSec(k){go('macro');let n=0;const tryGo=()=>{const t=doc.querySelector('#tp-macro .sec-title[data-sec="'+k+'"]');if(t&&t.offsetParent){const b=doc.getElementById('sb-'+k);if(b&&b.classList.contains('closed'))t.click();if(typeof jumpToEl==='function')jumpToEl(t);}else if(n++<20)setTimeout(tryGo,200);};setTimeout(tryGo,150);}

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
      body.innerHTML=(j&&j.mood?`<div class="hm-head">${esc(j.mood)}</div>`:'')+items.map(x=>`<div class="hm-news" data-go="news" role="link" tabindex="0" style="cursor:pointer"><b>${esc(x.title)}</b><span>${esc(x.why||x.what||'')}</span>${(x.codes||[]).length?`<span class="hm-codes">${x.codes.slice(0,4).map(c=>`<a href="#stock/${encodeURIComponent(c.id)}">${esc(c.n)}</a>`).join('')}</span>`:''}</div>`).join('')||'<div class="hm-empty">今天的早報還沒產生。</div>';
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
    try{ind().catch(()=>{});}catch(e){}
    try{await Promise.all([mkt(),news(),aip(),learn(),trend()]);}catch(e){}
    try{if(typeof lvLoad==='function')await lvLoad();}catch(e){}   // 還原因子(ADJ1)沒載入時價位算不出來(手機上常見)
    /* r1235:總覽不再放持股、最愛(各自有分頁,底部列一按就到);port()/fav() 保留但不呼叫 */
    busy=false;
  }
  window.HomeView={render,pane};
  pane();
})();
