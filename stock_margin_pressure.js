/* r1193: observed balance reduction, not an inferred account liquidation probability. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.StockMarginPressure=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=x=>typeof x==='number'&&Number.isFinite(x),fmt=x=>num(x)?x.toLocaleString('zh-TW',{maximumFractionDigits:2}):'—',signed=x=>(x>0?'+':'')+fmt(x),day=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(x)&&Number.isFinite(Date.parse(x+'T00:00:00Z'))&&new Date(x+'T00:00:00Z').toISOString().slice(0,10)===x;
 function scenario(x,price){if(!num(price)||price<=0||!num(x.cost)||x.cost<=0||x.loan_ratio!==.6||x.trigger_ratio!==1.3)return null;const line=x.cost*.6*1.3;return {...x,line,maintenance_pct:price/(x.cost*.6)*100,to_line_pct:(line/price-1)*100};}
 function render(s,e,f,now=new Date()){
  if(s.market!=='TW'||s.etf)return '';
  const head='<section class="plain-plan-card stock-margin-pressure" data-margin-key="'+esc(s.id)+'"><h4>融資減了多少？離壓力價多遠？</h4>',tail='</section>';
  if(!e||e.id!==s.id||!day(e.asof)||e.asof>now.toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'}))return head+'<p>本股融資資料待讀取或日期待核對，不借別股數字。</p><details class="plan-more"><summary>看單筆融資成本情境：130%價位與距離</summary><p>本股資料待核對，不提供情境數字。</p></details>'+tail;
  const a=e.windows?.['5'],b=e.windows?.['20'],pk=e.peak60,close=e.close,valid5=a&&num(a.pct)&&num(a.price_pct)&&!a.discontinuity;
  let verdict='先看融資餘額與價格，不能判斷是否有人將被斷頭。';
  if(e.balance===0)verdict='最新融資餘額為零；先核對資料與停資狀態，不判定已洗清。';
  else if(valid5)verdict=a.delta<0?(a.price_pct<0?'融資減少，但價格仍跌：槓桿在退，還不能說賣壓結束。':'融資減少、同期價格未跌：有去槓桿現象，是否止跌看本股訊號。'):a.delta>0?(a.price_pct<0?'融資增加、同期價格走弱：槓桿部位仍在增加。':'融資與價格同步增加：後續下跌時仍要觀察槓桿變化。'):'融資餘額近5日大致持平。';
  let h=head+'<p><strong>'+esc(verdict)+'</strong></p><p>融資資料日 '+esc(e.asof)+'：<b>'+fmt(e.balance)+' 張</b>。'+(f?.bottom&&f?.check?.liquid&&!f.check.jump?'本股價格結構：'+esc(({falling:'尚未止跌',waiting:'尚未止跌',reclaim:'初步止跌',breakout:'底部突破',failed:'止跌失效',neutral:'無近期跌深'})[f.bottom.stage])+ '。':'')+'</p><dl class="plan-prices">';
  for(const [n,w] of [['5',a],['20',b],['60',e.windows?.['60']]])h+='<div class="plan-price-row"><dt>近'+n+'交易日融資增減</dt><dd><strong>'+(w?signed(w.delta)+' 張':'資料不足')+'</strong><small>'+(w?esc(w.from)+'～'+esc(w.to)+'；'+(w.pct==null?'比例待核對':signed(w.pct)+'%')+'；'+(w.complete?'每日紀錄完整':'中間缺日，僅比較兩端餘額'):'不以零補缺值')+'</small></dd></div>';
  h+='<div class="plan-price-row"><dt>近60日高峰後減少</dt><dd><strong>'+(pk&&pk.complete&&!pk.discontinuity?fmt(pk.removed)+' 張／'+fmt(pk.removed_pct)+'%':'待補齊或核對')+'</strong><small>'+(pk?'高峰 '+esc(pk.date)+'：'+fmt(pk.balance)+' 張；已收錄 '+pk.observed+'/60 日。':'未取得本股高峰')+'餘額下降不等於全部是斷頭賣出。</small></dd></div></dl>';
  const px=num(s.price)&&s.price>0?s.price:close,rows=(e.scenarios||[]).map(x=>scenario(x,px)).filter(Boolean),stress=rows.find(x=>x.label==='假設買在近20日最高收盤');
  if(stress)h+='<div class="bottom-signal-box"><b>近20日高價買進情境（非實際融資戶）</b><p>假設買價 '+fmt(stress.cost)+' 元、借六成，目前單筆情境維持率 <b>'+fmt(stress.maintenance_pct)+'%</b>。130%情境價 <b>'+fmt(stress.line)+' 元</b>：<b>'+(stress.to_line_pct<0?'目前價格再跌 '+fmt(-stress.to_line_pct)+'% 到此線':stress.to_line_pct>0?'目前已低於此線，需回升 '+fmt(stress.to_line_pct)+'% 回線':'目前價格正好在此線')+'</b>。</p><small>這不是本股融資戶成本或券商追繳預告；使用價格 '+fmt(px)+' 元，融資資料日 '+esc(e.asof)+'。</small></div>';
  h+='<p class="dim-note">公開資料沒有融資戶實際借款、抵繳品或整戶部位，無法認定「快爆了」或算出真實整戶維持率。</p><details class="plan-more"><summary>看單筆融資成本情境：130%價位與距離</summary><p>以下只是「假設買在某價、借六成、未還款且無其他擔保品」的單筆算式，<b>不是本股融資戶平均成本、真實維持率或斷頭預告</b>。未計利息、股利、抵繳與不同成數。</p>';
  h+='<p>試算用價格 '+fmt(px)+' 元／股'+(px!==close?'（最新可用報價；融資餘額仍是 '+esc(e.asof)+'）':'（'+esc(e.asof)+' 收盤）')+'。</p>';
  if(rows.length)h+='<div style="overflow-x:auto"><table style="min-width:650px"><thead><tr><th>成本假設</th><th>假設買價</th><th>單筆情境維持率</th><th>130%情境價</th><th>距離情境價</th></tr></thead><tbody>'+rows.map(x=>'<tr><td>'+esc(x.label)+'<small style="display:block">'+esc(x.from)+'～'+esc(x.to)+'</small></td><td>'+fmt(x.cost)+'</td><td>'+fmt(x.maintenance_pct)+'%</td><td>'+fmt(x.line)+' 元</td><td>'+(x.to_line_pct<0?'再跌 '+fmt(-x.to_line_pct)+'%':x.to_line_pct>0?'已低於此線；需回升 '+fmt(x.to_line_pct)+'% 回線':'正好在此情境線')+'</td></tr>').join('')+'</tbody></table></div>';else h+='<p>資料或價格連續性不足，暫不試算情境價。</p>';
  h+='<p class="dim-note">公式：情境維持率＝目前價格÷（假設買價×60%）；130%情境價＝假設買價×60%×130%。顯示兩位小數供試算，未取成下單跳動單位。</p><p><a href="https://www.twse.com.tw/staticFiles/news/news/tsecnews/ff80808183645bda01838415d7e7005c.pdf">證交所：追繳看整戶，且有通知與補繳程序</a> · <a href="margin_pressure.csv">下載全股融資增減CSV（固定資料日）</a></p>';
  for(const warning of e.warnings||[])h+='<p>'+esc(warning)+'</p>';
  return h+'</details>'+tail;
 }
 return {scenario,render};
});
