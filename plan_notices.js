/* r1169: Shared price-observation contract. Never an execution or validated buy signal. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.StockPlanNotices=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const kinds=['fp_confirm','fp_entry','fp_stop','fp_target'];
 function hash(text){let h=2166136261;for(const c of text)h=Math.imul(h^c.charCodeAt(0),16777619);return (h>>>0).toString(16);}
 function usable(p,now){return p&&/^\d{4}-\d{2}-\d{2}$/.test(p.asof)&&Number.isFinite(Date.parse(p.asof+'T00:00:00Z'))&&new Date(p.asof+'T00:00:00Z').toISOString().slice(0,10)===p.asof&&[p.entry,p.low,p.stop,p.target,p.confirm,p.close].every(x=>Number.isFinite(x)&&x>0)&&p.stop<p.low&&p.low<=p.entry&&p.entry<p.target&&now-Date.parse(p.asof+'T00:00:00Z')>=0&&now-Date.parse(p.asof+'T00:00:00Z')<=14*864e5;}
 function status(p){return p.reclaimed?'原等待條件已發生，先不買、不追價。':p.invalidated?'原計畫已失效，先不買、重新評估。':!p.valid?'目前先不買：獲利空間與防守風險不合。':p.evidence==='small'?'目前先不買：本股前後期樣本不足。':p.evidence==='unstable'?'目前先不買：本股歷史表現不穩。':p.evidence!=='positive'?'目前先不買：本股研究資料不足。':'新買法仍在研究；到價不等於可以買進。';}
 function events(input){const now=Number.isFinite(input.now)?input.now:Date.now(),p=input.current,old=input.previous,px=Number(input.price),pc=Number(input.prevClose),out=new Map();if(!usable(p,now)||!(px>0&&Number.isFinite(px)))return [];
  const unit=input.market==='US'?'美元／股':'元／股',money=x=>Number(x).toLocaleString('zh-TW',{maximumFractionDigits:2})+' '+unit;
  function add(kind,plan,level,title,action,triggerPrice=px,closeDay=null){const signature=hash([plan.kind,plan.low,plan.entry,plan.confirm,plan.stop,plan.target].join('|')),key=[kind,input.market,input.id,plan.asof,signature].join('|');const closeLine=closeDay?'完整收盤 '+closeDay+'：'+money(triggerPrice)+'；最新可用價 '+money(px):'最新可用價 '+money(px);out.set(kind,{kind,k:kind==='fp_stop'?'sl':kind==='fp_target'?'tp':'buy',title,level,price:px,asof:plan.asof,planKey:key,source:key,text:closeLine+'\n'+action+'\n依 '+plan.asof+' 個股計畫；'+status(plan)+'僅為價位觀察，不是成交或持股賣出指令。'});}
  const lower=p.kind==='reclaim'?p.confirm:p.low;
  if(!p.reclaimed&&lower<=p.entry&&px>=lower&&px<=p.entry&&px>p.stop&&px<p.target)add('fp_entry',p,p.entry,'📍 到個股買入評估區',p.kind==='reclaim'?'評估區 '+money(lower)+'～'+money(p.entry)+'；仍須完整收盤站回 '+money(p.confirm)+'。':'評估區 '+money(p.low)+'～'+money(p.entry)+'；收盤止跌後再評估，超過上限不追。');
  if(px<=p.stop)add('fp_stop',p,p.stop,'⚠ 跌破個股計畫防守價','防守參考 '+money(p.stop)+' 已跌破；該份計畫暫停，重新檢查風險。');
  if(px>=p.target)add('fp_target',p,p.target,'🎯 到個股反彈賣價','反彈賣價參考 '+money(p.target)+' 已到達；查看原持有策略與成本後再決定。');
  if(p.kind==='reclaim'&&Number.isFinite(pc)&&pc<p.confirm&&p.close>=p.confirm)add('fp_confirm',p,p.confirm,'📍 完整收盤站回評估價','收復評估線 '+money(p.confirm)+'；只代表收盤條件，不能追認為新買點。',p.close,p.asof);
  // A completed close may invalidate yesterday's watched level before today's plan moves it.
  if(usable(old,now)&&old.asof<p.asof&&Number.isFinite(pc)){
   if(old.kind==='reclaim'&&pc<old.confirm&&p.close>=old.confirm)add('fp_confirm',old,old.confirm,'📍 完整收盤站回原計畫評估價','原計畫收復線 '+money(old.confirm)+'；目前計畫可能已更新，先核對，不直接買進。',p.close,p.asof);
   if(pc>old.stop&&p.close<=old.stop)add('fp_stop',old,old.stop,'⚠ 收盤跌破原計畫防守價','原防守價 '+money(old.stop)+' 已跌破；不因今天重算較低價而漏掉風險。',p.close,p.asof);
   if(pc<old.target&&p.close>=old.target)add('fp_target',old,old.target,'🎯 收盤到原計畫反彈賣價','原反彈賣價 '+money(old.target)+' 已到；不是你的實際成交。',p.close,p.asof);
   const low=old.kind==='reclaim'?old.confirm:old.low;
   if(!out.has('fp_entry')&&!old.reclaimed&&low<=old.entry&&p.close>=low&&p.close<=old.entry&&(pc<low||pc>old.entry))add('fp_entry',old,old.entry,'📍 收盤進入原計畫評估區','原評估區 '+money(low)+'～'+money(old.entry)+'；目前計畫已重算，先核對，不直接買進。',p.close,p.asof);
  }
  return [...out.values()].sort((a,b)=>(a.kind==='fp_stop'?-1:0)-(b.kind==='fp_stop'?-1:0));
 }
 return {kinds,events,status};
});
