/* r1188: individual path evidence only; never changes an order, price policy or model position. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.StockIndividualPaths=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),names={break_low:'低波動突破',break_mid:'中波動突破',break_high:'高波動突破',dip25_high_weak:'跌深止跌',dip40_weak:'跌40%首日',us_dip35:'美股跌深'};
 function group(s,f){return s.market==='US'?'us_dip35':f&&Number.isFinite(f.atrp)&&f.atrp>0?(f.atrp<.025?'break_low':f.atrp<.04?'break_mid':'dip25_high_weak'):null;}
 function render(s,e,f){
  const key=s.market+':'+s.id,g=group(s,f),link='<a class="plan-notice-link" onclick="event.stopPropagation()" href="research/r1188/report.html'+(g?'?method='+encodeURIComponent(g):'')+'#'+encodeURIComponent(key)+'">🔬 本股逐筆進出場與持有路徑</a>';
  if(!e||e.key!==key||!g||!e.groups||!e.groups[g])return '<section class="plain-plan-card stock-individual"><h4>本股買賣特性</h4><p>本股的逐筆研究資料尚未取得，不借另一檔的紀錄。</p>'+link+'</section>';
  if(!/^\d{4}-\d{2}-\d{2}$/.test(e.asof)||f&&f.check&&e.asof>f.check.asof)return '<section class="plain-plan-card stock-individual"><h4>本股買賣特性</h4><p>最新收盤與研究日期尚未對齊，先核對資料。</p>'+link+'</section>';
  const all=e.groups[g],x=all.audit,n=x&&x.n||0,fmt=v=>Number.isFinite(v)?v.toLocaleString('zh-TW',{maximumFractionDigits:2}):'—';
  let h='<section class="plain-plan-card stock-individual" data-individual-key="'+esc(key)+'"><h4>本股買賣特性・'+esc(names[g])+'</h4><p>本股同買法筆數：2016–2020 '+(all.development?.n||0)+'／2021–2023 '+(all.validation?.n||0)+'／2024後 '+n+'。以下是這一檔自己的紀錄。</p>';
  if(!n)h+='<p>本股2024後沒有這種買法的進場紀錄；仍可查看本股其他買法，不能把別股表現當成本股勝率。</p>';
  else{
   if(n<10)h+='<p class="dim-note">近期僅 '+n+' 筆，以下是本股紀錄，不是已證實的命中率或最佳參數。</p>';
   const touch=x.hit&&x.hit['10'];h+='<ul><li>持有中可確認回落的中位數 '+fmt(x.mae_median_pct)+'%；'+(touch?.n?touch.n+'/'+n+' 筆曾到達買價上方10%，達到者中位 '+fmt(touch.median_days)+' 個交易日。':'尚未觀察到達買價上方10%的交易。')+'</li>';
   h+='<li>停損後20個交易日收盤回到原含成本門檻：'+(x.stop_observed20_n?x.stop_recovered20_n+'/'+x.stop_observed20_n+' 筆。':'沒有足夠的完整觀察。')+(Number.isFinite(x.tp_after20_median_pct)?'停利後20日收盤變動中位 '+fmt(x.tp_after20_median_pct)+'%。':'停利後20日尚無完整觀察。')+'</li>';
   h+='<li>'+x.regime_changed_n+'/'+n+' 筆在持有中跨過波動分類；已買部位不能因此換停損停利。'+(x.open_marks?'本期另含 '+x.open_marks+' 筆期末估值。':'')+'</li></ul>';
  }
  return h+'<p class="dim-note">達標日數按本股有紀錄的日期計算，停牌或缺資料會讓實際等待更久。研究截至 '+esc(e.asof)+'；排除無法確定先後的出場日高低點，回落與到價時間屬可確認下限。事後反彈不等於當初不該停損；這些統計不直接改寫買賣價。</p>'+link+'</section>';
 }
 async function decode(r){const b=new Uint8Array(await r.arrayBuffer());if(b[0]===31&&b[1]===139){if(typeof DecompressionStream==='undefined')throw Error('gzip unavailable');return new Response(new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip'))).json();}return JSON.parse(new TextDecoder().decode(b));}
 return {render,group,decode};
});
