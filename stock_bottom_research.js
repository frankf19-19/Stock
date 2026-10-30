/* r1190: close-only bottom structure, separated from extreme-price observation and trade orders. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.StockBottomResearch=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),fmt=v=>Number.isFinite(v)?v.toLocaleString('zh-TW',{maximumFractionDigits:2}):'—';
 const stages={neutral:'目前沒有本次底部結構',falling:'收盤仍在20日低點',waiting:'跌深整理，尚未確認',reclaim:'初步止跌，仍須防再破底',breakout:'底部突破條件成立',failed:'反彈失敗，再破底'},methods={immediate:'超跌後直接買',reclaim10:'等站回10日線',break20:'等突破20日高'};
 function facts(b,dates){if(!Array.isArray(b)||b.length<160||!Array.isArray(dates)||b.length!==dates.length)return null;const n=b.length;
  if(!b.slice(-160).every(r=>r.length>=5&&r.slice(0,4).every(v=>Number.isFinite(+v)&&+v>0)&&+r[1]>=Math.max(+r[0],+r[3])&&+r[2]<=Math.min(+r[0],+r[3])&&Number.isFinite(+r[4])&&+r[4]>=0))return null;
  const c=b.map(r=>+r[3]),mean=(i,w)=>c.slice(i-w+1,i+1).reduce((a,x)=>a+x,0)/w,min=(i,w)=>Math.min(...c.slice(i-w+1,i+1)),max=(i,w)=>Math.max(...c.slice(i-w+1,i+1)),deep=[],low=[],up=[],recent=[];
  for(let i=119;i<n;i++){deep[i]=c[i]/max(i,120)<=.9;low[i]=c[i]<=min(i,20);recent[i]=deep.slice(Math.max(119,i-19),i+1).some(Boolean);up[i]=c[i]>mean(i,10)&&!low.slice(i-2,i+1).some(Boolean);}
  let anchor=null,anchorDay=null;for(let i=Math.max(140,n-20);i<n-1;i++)if(recent[i]&&up[i]&&!(recent[i-1]&&up[i-1])){anchor=min(i,20);anchorDay=dates[i];}
  const i=n-1,br=c[i]>Math.max(...b.slice(i-20,i).map(r=>+r[1])),failed=anchor!=null&&c[i]<anchor;
  const stage=failed?'failed':recent[i]&&br?'breakout':recent[i]&&up[i]?'reclaim':low[i]?'falling':recent[i]?'waiting':'neutral';
  let reclaimStart=i,breakStart=i;while(reclaimStart>140&&recent[reclaimStart-1]&&up[reclaimStart-1])reclaimStart--;while(breakStart>140&&recent[breakStart-1]&&c[breakStart-1]>Math.max(...b.slice(breakStart-21,breakStart-1).map(r=>+r[1])))breakStart--;
  return {ma10:mean(i,10),priorHigh20:Math.max(...b.slice(i-20,i).map(r=>+r[1])),noNewLow3:!low.slice(-3).some(Boolean),reclaimSince:recent[i]&&up[i]?dates[reclaimStart]:null,breakoutSince:recent[i]&&br?dates[breakStart]:null,stage,asof:dates[i],close:c[i],dd120:c[i]/max(i,120)-1,recentDeep:!!recent[i],up:!!up[i],break20:br,anchor,anchorDay,rawConfirm10:mean(i,9),rawBreak20:Math.max(...b.slice(-20).map(r=>+r[1])),rawInvalid:anchor!=null?anchor:min(i,20),recentNewLow:low.slice(-2).some(Boolean)};
 }
 // r1191: explicit close-condition status, not a calibrated bottom probability or new order.
 function badgeHTML(s,f){const p=f?.bottom,valid=p&&f.check&&!f.check.jump&&f.check.liquid&&!s.etf;
  const status=(on,isBreak=false)=>!valid?'待核對':p.stage==='failed'?(isBreak?'未出現':'已失效'):p.stage==='neutral'?'不判定':on?'已出現':'未出現';
  const up=valid&&p.recentDeep&&p.up,br=valid&&p.recentDeep&&p.break20;
  return '<div class="bottom-signal-badge" data-bottom-badge="'+esc(s.market+':'+s.id)+'"><b>止跌訊號：'+status(up)+'</b><b>底部突破：'+status(br,true)+'</b><small>'+(valid?esc(p.asof)+' 完整收盤・結構參考':'資料待核對，不當成沒有訊號')+'</small></div>';
 }
 function signalHTML(p,money){
  const active=p.stage!=='failed',reclaim=active&&p.recentDeep&&p.up,br=active&&p.recentDeep&&p.break20,neutral=p.stage==='neutral',failed=p.stage==='failed';
  const status=(on,isBreak=false)=>failed?(isBreak?'未出現':'已失效'):neutral?'不判定':on?'已出現':'未出現',mark=on=>on?'✓':'○';
  const conclusions={falling:'尚未止跌：收盤仍創低，現在不當成底部。',waiting:'尚未止跌：跌深後整理，止跌條件還沒全部成立。',reclaim:'初步止跌訊號已出現；還要核對底部突破條件。',breakout:'底部突破訊號已出現；仍可能反彈失敗。',failed:'先前止跌已失效：收盤再破固定低點。',neutral:'近期沒有跌深，不把正常走勢標成落底。'};
  const row=(name,on,since)=>'<div class="bottom-signal-row"><span>'+name+'</span><strong style="color:'+(failed?'var(--down)':on?'var(--up)':'var(--amber)')+'">'+status(on,name==='底部突破訊號')+'</strong>'+(on&&since?'<small>本次連續成立自 '+esc(since)+'</small>':'')+'</div>';
  return '<div class="bottom-signal-box" data-bottom-stage="'+esc(p.stage)+'"><p class="bottom-verdict">'+esc(conclusions[p.stage]||'資料待核對')+'</p>'+row('止跌訊號',reclaim,p.reclaimSince)+row('底部突破訊號',br,p.breakoutSince)+'<p class="dim-note">檢查日：'+esc(p.asof)+' 完整收盤。'+(failed?'原初步止跌日：'+esc(p.anchorDay)+'；固定低點 '+money(p.anchor)+' 已失守。':'')+'</p><ul class="bottom-checks"><li>'+mark(p.recentDeep)+' 近20日曾離本股120日最高收盤跌至少10%</li><li>'+mark(p.noNewLow3)+' 連續3日未創20日最低收盤</li><li>'+mark(p.up||p.close>p.ma10)+' 收盤站上10日線</li><li>'+mark(p.break20)+' 收盤突破前20日最高價</li></ul><p class="dim-note">止跌須前3項同時成立；底部突破須第1、4項成立。這是收盤條件訊號，不代表已知最低點或自動買進。</p></div>';
 }
 function render(s,e,f){const key=s.market+':'+s.id,p=f?.bottom,link='<a class="plan-notice-link" onclick="event.stopPropagation()" href="research/r1190/report.html#'+encodeURIComponent(key)+'">🔬 本股超跌、初步止跌、底部突破的逐次結果</a>',head='<section class="plain-plan-card stock-bottom-study" data-bottom-key="'+esc(key)+'"><h4>止跌與底部訊號</h4>',tail='</details></section>';
  if(!p||!f?.check||f.check.jump||!f.check.liquid||s.etf)return head+'<div class="bottom-signal-box" data-bottom-stage="unavailable"><p><b>止跌訊號：待核對</b><br><b>底部突破訊號：待核對</b></p><p>完整收盤、流動性或價格連續性待核對，暫不確認底部。</p></div><details class="plan-more"><summary>本股底部研究</summary>'+link+tail;
  const money=v=>(s.market==='US'?'US$':'')+fmt(v)+(s.market==='US'?'／股':' 元／股');let h=head+signalHTML(p,money)+'<p><strong>'+esc(stages[p.stage])+'</strong>・'+esc(p.asof)+' 完整收盤</p>';
  h+='<p>離本股120日最高收盤 '+fmt(p.dd120*100)+'%。'+(p.stage==='failed'?'已跌破 '+esc(p.anchorDay)+' 初步止跌時固定的 '+money(p.anchor)+'，先前反彈條件失效。':p.stage==='breakout'?'本次收盤已突破前20日高，不追認為下一次新買點；下次觀察價會更新，也不保證不再跌。':p.stage==='reclaim'?'站回10日線且3日沒有新的20日最低收盤，屬初步止跌。':'超跌或籌碼亮燈，都不能單獨證明已落底。')+'</p>';
  h+='<dl class="plan-prices"><div class="plan-price-row"><dt>'+(p.close>=p.confirm10?'10日線維持價（已站上）':'下次站回10日線價')+'</dt><dd><strong>'+money(p.confirm10)+'</strong><small>'+(p.close>=p.confirm10?'目前已站上，不追認為新收復買點。':'')+'下一完整收盤核對；'+(p.recentNewLow?'最近2日有新低，仍須先等3日不再創低。':'還須維持3日不再創20日低點。')+'</small></dd></div><div class="plan-price-row"><dt>下次底部突破價</dt><dd><strong>'+money(p.confirm20)+'</strong><small>收盤站上前20日高；只有近期跌深才稱底部結構。</small></dd></div><div class="plan-price-row"><dt>'+(p.anchor!=null?(p.stage==='failed'?'已跌破的初步止跌線':'初步止跌固定警戒'):'收盤破底警戒')+'</dt><dd><strong>'+money(p.invalid)+'</strong><small>'+(p.anchor!=null?'固定採 '+esc(p.anchorDay)+' 的低點，不隨新低下修。':'低於近期最低收盤；')+'供觀察，持股停損仍按原買法。</small></dd></div></dl><p class="dim-note">盤中到價不當收盤確認；這三價是結構核對，不是新增買單或保證底部。實際買進、防守、賣出仍看上方原計畫。</p><details class="plan-more"><summary>本股底部訊號是否有用？</summary>';
  if(!e||e.key!==key||!/^\d{4}-\d{2}-\d{2}$/.test(e.asof)||e.asof>p.asof)return h+'<p>本股極端超跌研究尚未取得或日期未對齊，不借其他股票的上漲比例。</p>'+link+tail;
  const x=e.periods.audit;h+='<p>本股極端超跌事件：2016–2020 '+e.periods.development.episodes+'／2021–2023 '+e.periods.validation.episodes+'／2024後 '+x.episodes+' 次；其中近期完整60根 '+x.complete60+' 次，其餘截止估值；資料至 '+esc(e.asof)+'。每次同一60根個股K終點比較，等不到確認保留空手0%，不是只挑成交的贏家。</p><div style="overflow-x:auto"><table><thead><tr><th>研究買法</th><th>成交／事件</th><th>含空手每次淨報酬</th><th>20日內再破低</th></tr></thead><tbody>';
  for(const [k,name] of Object.entries(methods)){const z=x.methods[k];h+='<tr><td>'+name+'</td><td>'+z.filled+'/'+x.episodes+'</td><td>'+(z.avg_all_pct==null?'—':fmt(z.avg_all_pct)+'%')+'</td><td>'+(z.anchor_observed20?z.broke_anchor20+'/'+z.anchor_observed20:'資料不足')+'</td></tr>';}
  return h+'</tbody></table></div><p class="dim-note">極端定義用本股當時已知的近750根分位與至少10%回落；上方結構只描述目前價格，兩者不混當同一個買訊。事件可能同時發生在多股；歷史各期已被研究，少樣本不推定本股最佳買法。研究含雙邊各0.3%費用及期末估值，不是正式策略績效或資金年化。</p>'+link+tail;
 }
 return {facts,render,stages,methods,signalHTML,badgeHTML};
});
