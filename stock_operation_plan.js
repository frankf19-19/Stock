/* r1172: present existing rules as an entry plan and a separate holding plan. No new trading rule. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.StockOperationPlan=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function clock(market,now){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:market==='US'?'America/New_York':'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(now)),p=Object.fromEntries(parts.map(x=>[x.type,x.value]));return {day:p.year+'-'+p.month+'-'+p.day,minute:+p.hour*60+(+p.minute)};}
 function session(day,market,calendar,inclusive=false){const h=calendar&&calendar[market.toLowerCase()];if(!h||!/^\d{4}-\d{2}-\d{2}$/.test(day))return null;let t=Date.parse(day+'T12:00:00Z');if(!Number.isFinite(t)||new Date(t).toISOString().slice(0,10)!==day)return null;for(let i=0;i<25;i++){if(i||!inclusive)t+=864e5;const d=new Date(t),key=d.toISOString().slice(0,10);if(d.getUTCDay()!==0&&d.getUTCDay()!==6&&!h[key])return key;}return null;}
 function schedule(market,asof,now,calendar){const c=clock(market,now),open=market==='US'?570:540,close=market==='US'?960:810;
  const confirm=session(c.day,market,calendar,c.minute<close),order=confirm&&session(confirm,market,calendar),signalOrder=session(asof,market,calendar),missed=!!signalOrder&&(signalOrder<c.day||signalOrder===c.day&&c.minute>=open);
  return {confirm,order,signalOrder,missed,stale:!!signalOrder&&(signalOrder<c.day||signalOrder===c.day&&c.minute>=close),clock:c};
 }
 function render(s,f,options={}){
  const us=s.market==='US',money=v=>Number.isFinite(v)&&v>0?v.toLocaleString('zh-TW',{maximumFractionDigits:2})+(us?' 美元／股':' 元／股'):'待資料核對',row=(k,v,n='')=>`<div class="plan-price-row"><dt>${esc(k)}</dt><dd><strong>${esc(v)}</strong>${n?'<small>'+esc(n)+'</small>':''}</dd></div>`,date=(d,type)=>d?d+(us?(type==='open'?' 紐約正常開盤9:30':' 紐約正常收盤16:00後'):(type==='open'?' 台灣9:00開盤':' 台灣13:30收盤後')):'交易日曆待核對';
  if(!f||!f.check||f.check.jump||!f.check.liquid)return `<section class="plain-plan-card operation-plan"><h4>買進與持有分開看</h4><p>完整收盤、還原或成交資料待核對，暫不確認新買單或持股出場。這不表示股票不能買。</p></section>`;
  const r=f.check,q=schedule(s.market,r.asof,options.now??Date.now(),options.calendar),safe=!!q.confirm&&!q.stale,hasCost=Number.isFinite(f.cost)&&f.cost>0;
  let h=`<section class="plain-plan-card operation-plan" data-operation-key="${esc(s.market+':'+s.id)}"><h4>買進與持有分開看</h4><p class="context-tag">依本站既有${us?'跌深承接':'創高突破／季線出場'}規則；不是用其他研究買法的成敗決定整檔股票。</p><div class="operation-part operation-entry"><h5>① 還沒買：${us?'等首次跌深條件':'看新的創高條件'}</h5>`;
  if(!safe)h+=`<p class="operation-action">${q.stale?'最近完整收盤資料尚未跟上市場交易日，暫不掛新的買單。':'交易日曆尚未核對，先不排買單日期。'}</p>`;
  else if(us){
   const ready=r.dip==='first'&&!q.missed;
   h+=`<p class="operation-action">${ready?'最近完整收盤首次符合跌深條件，核對下一交易日開盤。':r.dip==='already'?'已在跌深區，但不是首次達價，不重複新增買單。':r.dip==='first'?'這次訊號對應的開盤已過，不追認為現在的新買點。':'目前等待；首次收盤跌到下列條件價，才看隔日開盤。'}</p><dl class="plan-prices">${row('收盤買進條件價',money(f.dipEntry)+' 以下','離本股60日高跌35%的首次完整收盤，才符合本站既有美股買法。')}${row('確認時間',date(ready?r.asof:q.confirm,'close'))}${row('買進時間',date(ready?q.signalOrder:q.order,'open'),'僅在前一收盤首次確認後，按下一交易日實際開盤價；未設固定限價或追價上限。')}${row('停損試算',money(f.dipHypothetical&&f.dipHypothetical.stop),'假設買在上述條件價、成本下方20%；實際開盤成交不同，必須重算。')}${row('停利試算',money(f.dipHypothetical&&f.dipHypothetical.target),'同一假設買價、成本上方30%；實際成交不同，必須重算。')}</dl>`;
  }else{
   const confirmed=r.breaks.length>0&&!q.missed,eligible=f.breakEligible&&f.breakEligible.length;
   h+=`<p class="operation-action">${confirmed?'最近完整收盤已符合原創高條件，只對應下列開盤時點。':eligible?'等待收盤至少到 '+money(f.breakEntry)+'，再核對是否符合原創高條件。':'近期創高條件已發生或資料不足，不能把同一波反覆當作新買點。'}</p><dl class="plan-prices">${row(confirmed?'當次收盤確認門檻':'下一次收盤觀察價',money(confirmed?f.signalEntry:f.breakEntry),confirmed?'已確認的收盤為 '+money(r.close)+'；不把模型成本當你的買價。':'收盤須首次突破前60／120／250日高之一，且接近當天52週高；碰價不等於條件完成。')}${row('確認時間',date(confirmed?r.asof:q.confirm,'close'))}${row('符合後買進時間',date(confirmed?q.signalOrder:q.order,'open'),'按該交易日實際開盤價買，尚無法預知成交價；原規則沒有固定追價上限。')}${row('未符合怎麼做','不掛買單，收盤後重算','這份觀察價只用於下一次收盤核對；不是隔天一定買，也不保留過期訊號。')}</dl>`;
  }
  h+='</div><div class="operation-part operation-hold"><h5>② 如果已持有：依原買法處理</h5>';
  if(hasCost)h+=`<p>你已填買入成本 <b>${esc(money(f.cost))}</b>${Number(s.price)>0?'；目前每股價差 '+esc(Math.abs(Number(s.price)-f.cost).toLocaleString('zh-TW',{maximumFractionDigits:2})+(us?' 美元／股':' 元／股'))+'（'+(Number(s.price)>=f.cost?'＋':'－')+Math.abs((Number(s.price)/f.cost-1)*100).toFixed(2)+'%，未扣費用）':''}。成本不代表已選定持有策略。</p>`;
  else h+='<p class="dim-note">尚未提供你的買入成本；不以現價或AI模型成交價冒充持股成本。</p>';
  if(us){
   if(hasCost&&f.ownDip)h+=`<p class="operation-action">若這筆持股採用本站跌深承接策略，按你填的成本計算：</p><dl class="plan-prices">${row('停損賣出價',money(f.ownDip.stop),'成本下方20%；跳空可能以更低價格成交。')}${row('停利賣出價',money(f.ownDip.target),'成本上方30%；先觸及停損或停利先退出。')}${row('持有期限','自實際買入起最多90交易日','未提供實際買入日期時，不編造到期日；不是從今天重新起算。')}</dl>`;
   else h+='<p>若採用跌深承接：停損為實際成本下方20%、停利為上方30%，最多90交易日。未填成本與買入日，不能算出你這筆持股的退出價與到期日。</p>';
  }else if(!safe){
   h+=`<p class="operation-action">最新完整收盤或交易日曆尚未核對，先不以舊資料排新的出場時間。</p><dl class="plan-prices">${row('最後已知季線',money(r.ma60),'截至 '+r.asof+'；先核對最新完整收盤，不能把舊防守判斷價沿用到今天。')}${row('原持有規則','連續2天收盤跌破各日季線後，下一交易日開盤','本策略沒有固定停利；已存在的模型出場紀錄仍依原紀錄核對。')}</dl>`;
  }else{
   const sell=r.below2,waiting=r.below&&!r.below2;
   h+=`<p class="operation-action">${sell?'若這筆採用創高突破策略：已連續兩個完整收盤跌破季線，依規則處理出場。':waiting?'若這筆採用創高突破策略：目前只跌破季線1天，還沒完成2天出場條件。':'若這筆採用創高突破策略：最近收盤未觸發季線2日出場條件，依原規則續追蹤。'}</p><dl class="plan-prices">${row('最近收盤季線',money(r.ma60),'這是60日平均線，會每天更新；不是固定盤中停損單。')}${!sell?row('下一收盤防守判斷',money(f.nextBelowPrice)+' 以下',waiting?'若下一完整收盤在此價以下，即構成連續第2天跌破，才於再下一交易日開盤出場。':'若下一完整收盤在此價以下，先記第1天；仍須下一次收盤再低於更新後的季線，才符合出場。'):''}${row(sell?'規則出場時間':waiting?'若再跌破的出場時間':'何時賣出',sell?date(q.signalOrder,'open'):waiting?date(q.order,'open'):'連續2天收盤跌破各日季線後，下一交易日開盤',sell&&q.missed?'此開盤時點已過；請核對實際成交，這裡不假設你已賣出。':'只依已完成收盤判斷，盤中碰到不直接賣；實際開盤成交價不能預先確定。')}${row('停利／減碼','本策略不設固定停利或分批減碼','沿用季線條件讓獲利延續；不為了湊一個賣價而新增未驗證規則。')}</dl>`;
  }
  h+='</div>';
  h+=`<p class="operation-model-note">🤖 ${f.models>0?'本股另有AI模型持有紀錄；模型部位各照原停損、停利與到期規則，不因「還沒買」區的等待狀態而賣出。':'AI模型帳與你的持股分開；沒有模型部位也不代表整檔股票不能買。'}模型持有不等於現在又有新買點。</p><p class="dim-note">價格條件依 ${esc(r.asof)} 完整收盤與目前還原資料；盤後更新、除權息或休市會改變判斷價與日期。上方是條件計畫，不是已送出或已成交的委託。</p></section>`;
  return h;
 }
 return {render,clock,session,schedule};
});
