/* ══════════════════════════════════════════════════════════════════
   K研所 · mobile.js · build r762
   手機版 App 化行為層。只在 ≤640px 生效,不改 app.js 任何函式,
   全部用「渲染後加工 + MutationObserver」介入,桌機零影響。
   ══════════════════════════════════════════════════════════════════ */
(function(){
'use strict';

var MQ = window.matchMedia('(max-width:640px)');
function isMob(){ return MQ.matches; }

/* ── 工具 ───────────────────────────────────────────────────────── */
function num(x){ var v = parseFloat(String(x).replace(/[^0-9.\-]/g,'')); return isFinite(v)?v:null; }

/* 從 DATA.stocks 取原始資料 */
function stockOf(id){
  try{
    var arr = (window.DATA && DATA.stocks) || [];
    for(var i=0;i<arr.length;i++) if(arr[i].id===id) return arr[i];
  }catch(e){}
  return null;
}

/* 主力動向:外資5日 + 投信5日 淨張數。kv 格式如「買超 +18,420張」 */
function netOf(s){
  var kv = (s && s.c && s.c.kv) || {}, n = 0, ok = false;
  ['外資5日','投信5日'].forEach(function(k){
    var v = kv[k]; if(v==null) return;
    var m = String(v).match(/([買賣])超\s*[+-]?([\d,\.]+)/);
    if(!m) return;
    ok = true;
    n += (m[1]==='買'?1:-1) * (Math.abs(parseFloat(m[2].replace(/,/g,''))) || 0);
  });
  return ok ? n : null;
}

/* 依當前清單的分佈自我校準,避免固定門檻在大小型股之間失真 */
function flowScale(nets){
  var a = nets.filter(function(v){ return v!=null; }).map(Math.abs).sort(function(x,y){return x-y;});
  if(!a.length) return {lo:0, hi:0};
  var at = function(p){ return a[Math.min(a.length-1, Math.floor(a.length*p))]; };
  return { lo: at(0.25), hi: at(0.70) };
}
var FLOW = {
  b2:['☀️','大買'], b1:['🌤','小買'], n0:['☁️','中立'], s1:['🌧','小賣'], s2:['⛈','大賣']
};
function flowKey(net, sc){
  if(net==null) return null;
  var a = Math.abs(net);
  if(a <= sc.lo) return 'n0';
  if(net > 0) return a >= sc.hi ? 'b2' : 'b1';
  return a >= sc.hi ? 's2' : 's1';
}

/* ── 選股清單:轉成資料列 ───────────────────────────────────────── */
function enhanceGrid(){
  var g = document.getElementById('grid');
  if(!g || !isMob()) return;
  var cards = [].slice.call(g.querySelectorAll('.card'));
  if(!cards.length) return;

  /* 本輪所有卡的主力淨額,先算分佈 */
  var recs = cards.map(function(c){
    var s = stockOf(c.dataset.id);
    return { el:c, s:s, net: s ? netOf(s) : null };
  });
  var sc = flowScale(recs.map(function(r){ return r.net; }));

  recs.forEach(function(r){
    var c = r.el;
    if(c.dataset.mob === '1') return;          // 同一輪只加工一次
    c.dataset.mob = '1';
    var s = r.s;

    /* (a) 綜合分數 → 名稱列的小藥丸 */
    var scEl = c.querySelector('.score-in b');
    var nameEl = c.querySelector('.c-name');
    if(scEl && nameEl && !nameEl.querySelector('.mob-sc')){
      var v = num(scEl.textContent);
      var pill = document.createElement('span');
      pill.className = 'mob-sc' + (v!=null && v>=75 ? ' hi' : '');
      pill.textContent = (v==null ? '–' : v);
      var codeEl = nameEl.querySelector('.c-code');
      if(codeEl) codeEl.appendChild(pill); else nameEl.appendChild(pill);
    }

    /* (b) 主力動向欄 */
    if(!c.querySelector('.mob-flow')){
      var k = flowKey(r.net, sc);
      var f = document.createElement('div');
      f.className = 'mob-flow ' + (k || 'n0');
      if(k){
        f.innerHTML = '<span class="fi">'+FLOW[k][0]+'</span><span class="fl">'+FLOW[k][1]+'</span>';
        f.title = '外資+投信 5 日合計 ' + (r.net>0?'買超 +':'賣超 ') + Math.round(r.net).toLocaleString() + ' 張';
      }else{
        f.innerHTML = '<span class="fl" style="color:var(--dim)">—</span>';
      }
      var price = c.querySelector('.c-price');
      if(price) c.insertBefore(f, price); else c.appendChild(f);
    }

    /* (c) 兩行漲跌 + 漲跌停色塊 */
    var pxEl = c.querySelector('.c-price .px');
    var chgEl = c.querySelector('.c-price > span:not(.px)');
    if(chgEl && !chgEl.classList.contains('mob-chg')){
      var pct = s ? s.chg : num(chgEl.textContent);
      var price0 = s ? s.price : num(pxEl && pxEl.textContent);
      if(pct==null || !isFinite(pct)){
        chgEl.className = 'mob-chg flat';
        chgEl.innerHTML = '<b>–</b><i>–</i>';
      }else{
        var abs = (price0!=null && isFinite(price0) && (100+pct)!==0)
                  ? price0 * pct / (100 + pct) : null;
        var cls = pct>0 ? 'pos' : pct<0 ? 'neg' : 'flat';
        var sign = pct>0 ? '▲' : pct<0 ? '▼' : '–';
        var absTxt = abs==null ? '' : (Math.abs(abs) >= 100
                      ? Math.round(Math.abs(abs))
                      : Math.abs(abs).toFixed(Math.abs(abs)<10 ? 2 : 1));
        chgEl.className = 'mob-chg ' + cls;
        chgEl.innerHTML = '<b>' + sign + (absTxt || '') + '</b>' +
                          '<i>' + Math.abs(pct).toFixed(2) + '%</i>';
        /* 台股漲跌停:股價套實心色塊 */
        if(pxEl && s && s.market === 'TW'){
          if(pct >= 9.4) pxEl.classList.add('lim-u');
          else if(pct <= -9.4) pxEl.classList.add('lim-d');
        }
      }
    }
  });

  buildThead(g);
}

/* 可排序表頭 */
function buildThead(g){
  if(document.querySelector('.mob-thead')) { syncThead(); return; }
  var sel = document.getElementById('sortSel');
  var h = document.createElement('div');
  h.className = 'mob-thead';
  h.innerHTML =
    '<b data-sk="total">個股<span class="ar">▼</span></b>' +
    '<b class="th-c" data-sk="chip">主力動向<span class="ar">▼</span></b>' +
    '<b class="th-r">股價</b>' +
    '<b class="th-r" data-sk="chg">漲跌幅<span class="ar">▼</span></b>';
  g.parentNode.insertBefore(h, g);
  h.addEventListener('click', function(e){
    var t = e.target.closest('[data-sk]');
    if(!t || !sel) return;
    sel.value = t.dataset.sk;
    sel.dispatchEvent(new Event('change', {bubbles:true}));
    setTimeout(syncThead, 30);
  });
  syncThead();
}
function syncThead(){
  var h = document.querySelector('.mob-thead'), sel = document.getElementById('sortSel');
  if(!h || !sel) return;
  h.querySelectorAll('[data-sk]').forEach(function(b){
    b.classList.toggle('on', b.dataset.sk === sel.value);
  });
}

/* ── 底部黏著指數列 ─────────────────────────────────────────────── */
var IDX_KEYS = ['加權','櫃買','台指','電子'];
function buildIdxBar(){
  if(!isMob()) return;
  var bar = document.getElementById('mobIdxBar');
  if(!bar){
    bar = document.createElement('div');
    bar.id = 'mobIdxBar';
    document.body.appendChild(bar);
    bar.addEventListener('click', function(){
      var t = document.querySelector('#homeTabs [data-tab="macro"]');
      if(location.hash) location.hash = '';
      if(t) t.click();
      window.scrollTo({top:0, behavior:'smooth'});
    });
  }
  var list = [];
  try{
    if(typeof rtIdxApply === 'function') rtIdxApply();
    list = ((window.DATA && DATA.macro && DATA.macro.idx) || []);
  }catch(e){}
  var pick = [];
  IDX_KEYS.forEach(function(k){
    var it = list.find(function(x){ return String(x.name||'').indexOf(k) >= 0; });
    if(it && pick.indexOf(it) < 0) pick.push(it);
  });
  if(!pick.length){ bar.innerHTML = '<span class="mi-k">指數載入中…</span>'; return; }
  bar.innerHTML = pick.slice(0,4).map(function(it){
    var c = num(it.chg);
    var cls = c==null ? 'flat' : c>0 ? 'pos' : c<0 ? 'neg' : 'flat';
    var sign = c==null ? '' : c>0 ? '▲' : c<0 ? '▼' : '';
    var v = num(it.val);
    return '<span class="' + cls + '">' +
             '<span class="mi-k">' + String(it.name||'').slice(0,4) + '</span>' +
             '<span class="mi-v">' + (v==null?'—':v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})) + '</span>' +
             '<span class="mi-c">' + sign + (c==null?'':Math.abs(c).toFixed(2)) + '</span>' +
           '</span>';
  }).join('');
}

/* ── 啟動 ───────────────────────────────────────────────────────── */
/* 手機一律用「籌碼黑」;不寫進 localStorage,免得蓋掉電腦版偏好 */
function forceDark(){
  if(!isMob()) return;
  try{
    if(document.documentElement.dataset.theme==='kdark') return;
    if(typeof applyTheme!=='function'){ document.documentElement.dataset.theme='kdark'; return; }
    var keep=null;
    try{ keep=localStorage.getItem('theme3l'); }catch(e){}
    applyTheme('kdark',true);   // r761:必須 redraw——TradingView 是 iframe,不重建就會停在亮色
    try{ keep===null ? localStorage.removeItem('theme3l') : localStorage.setItem('theme3l',keep); }catch(e){}
  }catch(e){ document.documentElement.dataset.theme='kdark'; }
}


/* ── r759:底部導覽改線性圖示(取代 emoji) ───────────────────── */
var NAV_ICON={
  macro:'<path d="M4 19V10M10 19V5M16 19v-6M22 19H2"/>',
  aipick:'<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M9 13h.01M15 13h.01M9.5 16.5h5"/>',
  stocks:'<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  etf:'<path d="M5 9h14l-1.4 9.1a2 2 0 0 1-2 1.9H8.4a2 2 0 0 1-2-1.9L5 9z"/><path d="M9 9V6a3 3 0 0 1 6 0v3"/>',
  gooaye:'<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  port:'<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 12h18"/>',
  __fav:'<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z"/>'
};
function polishNav(){
  var nav=document.getElementById('mobNav'); if(!nav) return;
  nav.querySelectorAll('button[data-mn]').forEach(function(b){
    if(b.dataset.mobIcon==='1') return;
    var d=NAV_ICON[b.dataset.mn]; if(!d) return;
    var mi=b.querySelector('.mi'); if(!mi) return;
    mi.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '+
      'stroke-linecap="round" stroke-linejoin="round" width="22" height="22">'+d+'</svg>';
    b.dataset.mobIcon='1';
  });
}

/* ── r759:左側策略欄 —— 拆成 圖示/名稱/檔數 三段,高度統一 ──── */
function polishRail(){
  var seg=document.getElementById('stratSeg'); if(!seg) return;
  seg.querySelectorAll('button[data-st]').forEach(function(b){
    if(b.dataset.mobRail==='1') return;
    var cntEl=b.querySelector('span'), cnt=cntEl?cntEl.textContent.trim():'';
    if(cntEl) cntEl.remove();
    var txt=(b.textContent||'').trim();
    /* 開頭的圖示字元(emoji 或 ◀ ▶)切出來 */
    var m=txt.match(/^([\uD800-\uDBFF][\uDC00-\uDFFF]\uFE0F?|[\u2190-\u27BF\uFE0F]+)\s*([\s\S]*)$/);
    var icon=m?m[1]:'', name=m?m[2]:txt;
    b.innerHTML='<span class="ri">'+icon+'</span><span class="rn">'+name+'</span>'+
                (cnt?'<span class="rc">'+cnt+'</span>':'');
    b.dataset.mobRail='1';
  });
}

/* ── r759:機會雷達卡片 —— 標籤收進名稱列 ────────────────────── */
function polishRadar(){
  var box=document.getElementById('radar'); if(!box) return;
  box.querySelectorAll('.r-card').forEach(function(c){
    if(c.dataset.mobCard==='1') return;
    c.dataset.mobCard='1';
  });
}


/* ── r760:產業篩選 chip 補上檔數(比照 XQ 的「全部 22 / 加碼 8」) ── */
function polishChips(){
  var box=document.getElementById('chips'); if(!box) return;
  var arr=(window.DATA&&DATA.stocks)||[]; if(!arr.length) return;
  var gm=window.GMKT||'TW';
  var pool=arr.filter(function(s){ return !s.etf && s.market===gm; });
  box.querySelectorAll('.chip').forEach(function(b){
    if(b.dataset.mobChip==='1') return;
    var key=b.dataset.s, nm=(b.textContent||'').trim();
    var n = key==='全部' ? pool.length
          : pool.filter(function(x){ return x.sector===key; }).length;
    b.innerHTML='<span class="cl"></span><span class="cn"></span>';
    b.querySelector('.cl').textContent=nm;
    b.querySelector('.cn').textContent=n;
    b.dataset.mobChip='1';
  });
}

function boot(){
  if(!isMob()) return;
  forceDark();
  polishNav();
  polishRail();
  polishRadar();
  polishChips();
  enhanceGrid();
  buildIdxBar();

  /* #grid 每次重畫(換排序/篩選/更多)就重新加工 */
  /* 導覽列由 app.js 延遲建立,重試幾次 */
  [300,900,2000].forEach(function(t){ setTimeout(polishNav,t); });

  /* 策略欄 / 雷達每次重畫都要重新整形 */
  var seg=document.getElementById('stratSeg');
  if(seg && !seg.__mobObs){
    seg.__mobObs=new MutationObserver(function(){ clearTimeout(seg.__t); seg.__t=setTimeout(polishRail,30); });
    seg.__mobObs.observe(seg,{childList:true});
  }
  var cb=document.getElementById('chips');
  if(cb && !cb.__mobObs){
    cb.__mobObs=new MutationObserver(function(){ clearTimeout(cb.__t); cb.__t=setTimeout(polishChips,30); });
    cb.__mobObs.observe(cb,{childList:true});
  }
  var rb=document.getElementById('radar');
  if(rb && !rb.__mobObs){
    rb.__mobObs=new MutationObserver(function(){ clearTimeout(rb.__t); rb.__t=setTimeout(polishRadar,30); });
    rb.__mobObs.observe(rb,{childList:true});
  }

  var g = document.getElementById('grid');
  if(g && !g.__mobObs){
    g.__mobObs = new MutationObserver(function(){
      clearTimeout(g.__mobT);
      g.__mobT = setTimeout(enhanceGrid, 40);
    });
    g.__mobObs.observe(g, {childList:true});
  }
  setInterval(buildIdxBar, 5000);
}

if(document.readyState === 'loading')
  document.addEventListener('DOMContentLoaded', function(){ setTimeout(boot, 400); });
else setTimeout(boot, 400);

/* 資料較慢到位時補跑幾次 */
[1200, 2500, 5000].forEach(function(t){ setTimeout(function(){ if(isMob()){ enhanceGrid(); buildIdxBar(); polishNav(); polishRail(); polishRadar(); polishChips(); } }, t); });

/* 轉向 / 視窗尺寸變化 */
MQ.addEventListener ? MQ.addEventListener('change', function(){ setTimeout(boot, 200); })
                    : window.addEventListener('resize', function(){ setTimeout(boot, 200); });

window.__mobRefresh = function(){ enhanceGrid(); buildIdxBar(); polishNav(); polishRail(); polishRadar(); polishChips(); };
})();
