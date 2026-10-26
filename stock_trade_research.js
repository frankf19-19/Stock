/* r1171: show the actual per-stock r1170 study in the primary card. Research, never execution. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.StockTradeResearch=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const labels={trend20:'月線回檔承接',trend60:'季線回檔承接',break20:'突破20日高',break60:'突破60日高',range20:'盤整低檔承接',reclaim60:'收復季線'};
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const pct=x=>Number.isFinite(x)?(x>0?'+':'')+(Math.sign(x)*Math.round(Math.abs(x)*100+1e-8)/100).toFixed(2)+'%':'無資料';
 const iso=d=>typeof d==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(d)&&Number.isFinite(Date.parse(d+'T00:00:00Z'))&&new Date(d+'T00:00:00Z').toISOString().slice(0,10)===d;
 const modelOK=m=>m&&['d','v','a'].every(k=>{const a=m[k];return Array.isArray(a)&&a.length===6&&Number.isInteger(a[0])&&a[0]>=0&&Number.isInteger(a[1])&&a[1]>=0&&a[1]<=a[0]&&(a[2]===null||Number.isFinite(a[2]))&&(a[3]===null||Number.isFinite(a[3]))&&Number.isInteger(a[4])&&Number.isInteger(a[5]);});
 function clock(market,now){const a=new Intl.DateTimeFormat('en-CA',{timeZone:market==='US'?'America/New_York':'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(now)),v=Object.fromEntries(a.map(x=>[x.type,x.value]));return {day:v.year+'-'+v.month+'-'+v.day,minute:+v.hour*60+(+v.minute)};}
 function review(market,now,calendar){if(!calendar||!calendar[market.toLowerCase()])return '下個市場交易日完整收盤後（休市日待核對）';const c=clock(market,now),holidays=calendar[market.toLowerCase()],close=market==='US'?960:810;let day=c.day;const open=d=>{const w=new Date(d+'T12:00:00Z').getUTCDay();return w!==0&&w!==6&&!holidays[d];};if(c.minute>=close||!open(day)){for(let i=0;i<20;i++){day=new Date(Date.parse(day+'T12:00:00Z')+864e5).toISOString().slice(0,10);if(open(day))break;}}return day+(market==='US'?' 紐約正常收盤16:00後（提早休市依公告）':' 台灣13:30收盤後');}
 function state(s,e,options={}){
  const now=options.now??Date.now(),today=clock(s.market,now).day;
  if(!e||!e.models||typeof e.models!=='object')return {status:'missing',title:'研究資料尚未取得',reason:'尚未核對本股六種買法，暫不列買價。'};
  const selected=e.selected,v=selected&&e.models[selected]&&e.models[selected].v;
  if(!selected)return {status:'rejected',title:'六種買法未選出合格候選',reason:'本股開發期的完成樣本、報酬或風險檢查未達門檻；不是套用別股的結論。'};
  if(!labels[selected]||!modelOK(e.models[selected]))return {status:'missing',title:'本股研究欄位待核對',reason:'研究資料未完整對齊，暫不列買價。'};
  if(!e.supported){let reason=!v?'本股驗證資料不足。':Number.isFinite(v[2])&&v[2]<=0?'驗證期每筆平均 '+pct(v[2])+'，這種買法沒有穩定支持。':v[1]<6?'驗證期僅 '+v[1]+' 筆完成交易，尚不足以支持採用。':v[4]*2<v[5]?'驗證期有交易的 '+v[5]+' 年，只有 '+v[4]+' 年平均獲利，跨年度不穩定。':'驗證期獲利因子 '+(v[3]??'無有限值')+' 未達1.1，獲利不足以支持採用。';return {status:'rejected',title:'不採用「'+labels[selected]+'」進場',reason};}
  const p=e.plan,check=options.check;
  if(!p||!p.ordered)return {status:'no_plan',title:'候選有歷史支持，目前沒有合格價位',reason:'不硬湊買價；等新的完整收盤重新檢查價格結構。'};
  if(![p.asof,p.confirm_day,p.order_day].every(iso)||!(p.asof<p.confirm_day&&p.confirm_day<p.order_day)||p.asof>today||![20,40,60].includes(p.hold)||![p.trigger,p.upper,p.stop,p.target].every(x=>Number.isFinite(x)&&x>0)||!(p.stop<p.upper&&p.trigger<=p.upper&&p.upper<p.target))return {status:'missing',title:'候選價位待核對',reason:'日期或價位結構無法核對，暫不列買價。'};
  if(today>p.confirm_day||check&&check.asof>p.confirm_day)return {status:'expired',title:'這份候選計畫已到期',reason:p.confirm_day+' 的確認期限已過，不追認買點；等新的計畫。'};
  const cal=options.calendar&&options.calendar[s.market.toLowerCase()];
  if(!cal)return {status:'missing',title:'候選交易日期待核對',reason:'休市表尚未取得，暫不列可掛單的價位與時間。'};
  if([p.confirm_day,p.order_day].some(d=>cal[d]||[0,6].includes(new Date(d+'T12:00Z').getUTCDay())))return {status:'missing',title:'候選時程遇到休市',reason:'原確認日或掛單日已休市，須重算時程，不能照原日期下單。'};
  if(!check||check.jump||!check.liquid||check.asof<p.asof)return {status:'missing',title:'完整價格資料待核對',reason:'完整收盤、還原口徑或成交量尚未通過檢查，暫不列買價。'};
  if(!(Number(s.price)>p.stop&&Number(s.price)<p.target))return {status:'invalid',title:'報價已越過這份候選的有效範圍',reason:'本次價格已失效，不能沿用原買價或賣價。'};
  return {status:'candidate',title:labels[selected]+'：有條件的研究候選',reason:'先等指定收盤條件；尚未啟動買單，不因盤中碰價就買進。',plan:p};
 }
 function render(s,e,options={}){
  if(e&&(!e.models||typeof e.models!=='object'))e=null;
  const st=state(s,e,options),now=options.now??Date.now(),next=review(s.market,now,options.calendar),us=s.market==='US',money=x=>Number(x).toLocaleString('zh-TW',{maximumFractionDigits:2})+(us?' 美元／股':' 元／股'),row=(k,v,n='')=>`<div class="plan-price-row"><dt>${esc(k)}</dt><dd><strong>${esc(v)}</strong>${n?'<small>'+esc(n)+'</small>':''}</dd></div>`,selected=e&&e.selected,model=selected&&e.models[selected];
  let h=`<section class="stock-context plain-plan-card inline-trade-study" data-study-status="${st.status}" data-study-key="${esc(s.market+':'+s.id)}"><h4>${esc(st.title)}</h4><p class="study-decision">${esc(st.reason)}</p>`;
  if(modelOK(model))h+=`<p class="study-evidence">本股「${esc(labels[selected])}」：開發期 ${model.d[0]} 筆，平均 ${pct(model.d[2])}；驗證期 ${model.v[0]} 筆，平均 <b>${pct(model.v[2])}</b>；近期稽核 ${model.a[0]} 筆，平均 ${pct(model.a[2])}。${e.supported?'分段初步檢查通過，仍未晉級正式策略。':'未通過，不因近期又轉正就改判。'}</p>`;
  if(st.plan){const p=st.plan;h+=`<dl class="plan-prices">${row('收盤確認價',money(p.trigger),p.confirm==='cross'?'完整收盤必須突破；只碰到不算。':'回到評估區、收盤不低於前日並站回此線。')}${row('買價上限',money(p.upper),'確認成立才考慮；高於上限不追。')}${row('確認時間',p.confirm_day+(us?' 紐約收盤後':' 台灣13:30收盤後'))}${row('只在哪天掛單',p.order_day+(us?' 紐約正常時段9:30–16:00':' 台灣9:00–13:30'),'前一天確認成立才掛一天限價；當日未成交即取消。')}${row('停損賣出價',money(p.stop),'開盤已低於防守就取消買單；持有後跳空可能賣得更低。')}${row('停利賣出價',money(p.target),'觸價退出的研究條件，不是保證會漲到。')}${row('時間出場',`成交後第 ${p.hold} 根可用日K收盤`,'先觸及停損／停利先退出；停牌或缺K可能延後。')}</dl><p class="dim-note">${esc(p.asof)} 固定研究計畫。確認日已破防守或到目標即取消；不是已成交紀錄，取整價也未證實實盤績效。</p>`;}
  else h+=`<dl class="study-wait"><div><dt>現在怎麼做</dt><dd>不按未通過或已過期的研究價掛買單。</dd></div><div><dt>下次檢查時間</dt><dd>${esc(next)}</dd></div></dl>`;
  h+=`<details class="plan-more study-comparison"><summary>本股六種買法：研究結果直接看</summary>${e?`<p class="dim-note">${esc(e.start)}～${esc(e.asof)}，${esc(e.bars)} 根日K。表內為含成本每筆平均，非組合年化；筆數含期末未平倉估值，門檻僅計完成筆數。</p><div class="inline-study-scroll"><table><thead><tr><th>買法</th><th>開發期</th><th>驗證期</th><th>近期</th></tr></thead><tbody>${Object.entries(e.models).filter(([k,v])=>labels[k]&&modelOK(v)).map(([k,v])=>`<tr><th>${esc(labels[k])}</th>${['d','v','a'].map(t=>'<td>'+v[t][0]+'筆<br>'+pct(v[t][2])+'</td>').join('')}</tr>`).join('')}</tbody></table></div><p class="dim-note">開發期2016–2020；驗證期2021–2023；近期2024年後。僅開發期挑候選，驗證期不通過就不採用。現存股庫、日K撮合、停牌與已研究歷史等限制仍在。</p>`:'<p>研究資料載入中或暫時無法取得；稍後會重試，不把缺資料當零筆。</p>'}<a href="research/r1170/report.html#${encodeURIComponent(s.market+':'+s.id)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">完整研究報告與永久紀錄</a></details></section>`;
  return h;
 }
 return {state,render,review,clock,labels};
});
