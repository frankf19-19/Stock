/* r1189: own-stock signal-time context diagnostics; never selects a buy/sell policy. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.StockContextResearch=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const axes={return20:[-.10,.10],volume_ratio:[1.5],ma60_slope:[0],extension20:[0,.10]},names={return20:'近20日漲跌',volume_ratio:'成交量／前20日平均',ma60_slope:'季線近20日方向',extension20:'收盤離月線'},bins={return20:['跌逾10%','介於−10%與+10%','漲至少10%'],volume_ratio:['未達1.5倍','至少1.5倍'],ma60_slope:['季線下降','季線持平或上升'],extension20:['月線下方','月線上方未達10%','高於月線至少10%']},policies={baseline:'原賣法',weak20:'持有20個有成交日仍沒漲，次開盤賣',protect10:'收盤獲利10%後，次日起提高含費用防守'};
 const fmt=v=>Number.isFinite(v)?v.toLocaleString('zh-TW',{maximumFractionDigits:2}):'—';
 function classify(v){const out={};for(const k in axes)out[k]=Number.isFinite(v?.[k])?axes[k].filter(x=>v[k]+1e-12>=x).length:null;return out;}
 function features(b){if(!Array.isArray(b)||b.length<80)return null;const n=b.length,mean=(w,end)=>b.slice(end-w,end).reduce((z,r)=>z+(+r[3]),0)/w,close=+b[n-1][3],volume=+b[n-1][4],old=b.slice(-21,-1),den=old.reduce((z,r)=>z+(+r[4]),0)/20;
  if(!b.slice(-80).every(r=>Number.isFinite(+r[3])&&+r[3]>0)||!old.every(r=>Number.isFinite(+r[4])&&+r[4]>=0)||!(Number.isFinite(volume)&&Number.isFinite(den)&&volume>0&&den>0))return null;
  return {return20:close/(+b[n-21][3])-1,volume_ratio:volume/den,ma60_slope:mean(60,n)/mean(60,n-20)-1,extension20:close/mean(20,n)-1};}
 function group(s,f){return s.market==='US'?'us_dip35':Number.isFinite(f?.atrp)&&f.atrp>0?(f.atrp<.025?'break_low':f.atrp<.04?'break_mid':'dip25_high_weak'):null;}
 function render(s,e,f){const key=s.market+':'+s.id,g=group(s,f),start='<details class="plan-more stock-own-context" data-own-context-key="'+esc(key)+'"><summary>本股當前走勢與兩種賣法：詳細研究</summary>',end='</details>',link='<p><a class="plan-notice-link" onclick="event.stopPropagation()" href="research/r1189/report.html'+(g?'?method='+g:'')+'#'+encodeURIComponent(key)+'">🔬 本股不同狀況的進出場與逐筆價格</a></p>';
  if(!f?.check||f.check.jump||!f.check.liquid||s.etf||!f.context)return start+'<p>完整收盤、量能或價格連續性待核對，暫不套用相似狀況研究。</p>'+link+end;
  if(!e||e.key!==key||!g||!e.groups?.[g])return start+'<p>正在讀取本股研究；不借用其他股票的結果。</p>'+link+end;
  if(!/^\d{4}-\d{2}-\d{2}$/.test(e.asof)||e.asof>f.check.asof)return start+'<p>本股研究與完整收盤日期尚未對齊，先核對資料。</p>'+link+end;
  const current=classify(f.context),period=e.groups[g].audit;let h=start+'<p>目前狀況按 '+esc(f.check.asof)+' 完整收盤；歷史固定至 '+esc(e.asof)+'。先依上方買進／防守／賣出價與確認條件，這裡不另發買訊。</p><div style="overflow-x:auto"><table><thead><tr><th>本股目前狀況</th><th>近期同狀況筆數</th><th>歷史每筆淨報酬</th><th>歷史最差筆</th></tr></thead><tbody>';
  const pct=v=>Number.isFinite(v)?fmt(v)+'%':'—';
  for(const k in axes){const i=current[k],v=f.context[k],x=period[k+':'+i],value=k==='volume_ratio'?fmt(v)+'倍':pct(v*100);h+='<tr><td>'+esc(names[k])+' '+value+'<br>'+esc(bins[k][i]||'待資料')+'</td><td>'+(x?.n??0)+'</td><td>'+pct(x?.avg)+'</td><td>'+pct(x?.worst)+'</td></tr>';}
  h+='</tbody></table></div><p class="dim-note">四列各自篩選同股、同買法2024後的紀錄，可能重複；不是同時符合四項，更不是預測勝率。沒有紀錄留空，不代表沒有風險；訊號成立那天須重算量價狀況。</p>';
  const x=period.all;h+='<p>本股同買法三期筆數：'+e.groups[g].development.all.n+'／'+e.groups[g].validation.all.n+'／'+x.n+'。近期同一批買點比較：</p><ul>';
  for(const p of ['weak20','protect10']){const v=x.exits[p];h+='<li>'+esc(policies[p])+'：'+(v.avg==null?'沒有紀錄':'每筆 '+fmt(v.avg)+'%，比原法'+(v.delta>=0?'多 ':'少 ')+fmt(Math.abs(v.delta))+' 個百分點')+'。</li>';}
  return h+'</ul><p class="dim-note">以上含期末估值、每邊0.3%費用；樣本少與時期差異須一起看，不憑本股最高數字換賣法。保本防守遇跳空仍可能虧損。兩種新賣法尚未接入正式策略或通知。</p>'+link+end;
 }
 return {features,classify,group,render,axes,names,bins,policies,fmt};
});
