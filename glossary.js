/* r1215 白話小辭典(Frank 11/02:「整個網站要很白話,讓小白也看得懂」)
   專有名詞自動加虛線底線,點一下(電腦滑過去)跳出一句白話解釋。
   只包住文字、不改任何數字或計算;按鈕、連結、表單、選單裡面不動。 */
(function(){
  'use strict';
  const doc=document;
  const G={
    '季線':'近 3 個月(60 個交易日)的平均收盤價。股價在季線上面＝中期偏強,跌破＝轉弱。',
    '月線':'近 1 個月(20 個交易日)的平均收盤價。',
    '年線':'近 1 年(約 240 個交易日)的平均收盤價。股價在年線上＝長期趨勢向上。',
    '半年線':'近半年(約 120 個交易日)的平均收盤價。',
    '週線':'近 1 週(5 個交易日)的平均收盤價。',
    '均線':'一段時間的平均收盤價,例如 20 日均線＝近 20 天平均價。股價在均線上＝偏強。',
    '乖離':'股價離平均價多遠。負很多＝跌太深,正很多＝漲太快。',
    '融資':'跟券商借錢買股票(多半是散戶)。融資一直增加＝散戶借錢追高;大減＝散戶被迫賣出或退場。',
    '融券':'跟券商借股票來賣,賭它會跌。',
    '券資比':'融券 ÷ 融資。越高代表賭它跌的人越多,之後回補可能推升股價。',
    '外資':'外國的投資機構。買賣金額大,常影響大型股。',
    '投信':'國內的基金公司。常連續買同一檔,中小型股影響大。',
    '自營商':'券商用自己的錢買賣,多半是短線。',
    '法人':'外資、投信、自營商的合稱(大機構)。',
    '三大法人':'外資、投信、自營商這三種大機構。',
    '分點':'券商的分公司。看「哪一家分公司」在大買大賣,可以看出特定大戶的動作。',
    '主力':'買賣量大、能影響股價的大戶或機構。',
    '籌碼':'股票現在在誰手上(大戶、散戶、法人),以及最近誰在買、誰在賣。',
    '大戶':'持股很多的人(這裡指 400 張或 1000 張以上)。',
    '散戶':'一般小額投資人(這裡指 100 張以下)。',
    '集保':'集保中心每週公布的股東持股分布,可以看出大戶、散戶的比例變化。',
    '本益比':'股價 ÷ 每股一年賺的錢。數字越高＝股價相對越貴(或市場期待越高)。',
    '股價淨值比':'股價 ÷ 每股淨值(公司資產扣掉負債)。越高＝相對越貴。',
    'EPS':'每股盈餘:公司每一股賺多少錢。',
    '每股盈餘':'公司每一股賺多少錢(EPS)。',
    'ROE':'股東權益報酬率:公司用股東的錢,一年能賺幾 %。越高越會賺錢。',
    '殖利率':'一年配的股利 ÷ 股價。像存款利率,越高配得越多。',
    'YoY':'跟去年同期比的成長率。',
    '年增':'跟去年同期比,成長了多少 %。',
    '月增':'跟上個月比,成長了多少 %。',
    '營收':'公司賣東西收到的錢(還沒扣成本)。',
    '毛利率':'賣東西扣掉成本後,剩下的比例。越高＝越好賺。',
    '除權息':'公司發股利的那天,股價會扣掉股利的金額。',
    '停損':'事先設好「跌到多少就賣」,避免越賠越多。',
    '停利':'事先設好「漲到多少就賣」,把賺到的先收進口袋。',
    '防守價':'跌破就該賣的價位(停損價)。',
    '回測':'用過去的歷史資料測試:假如以前照這個方法做,結果會怎樣。不保證未來一樣。',
    '勝率':'過去照這個方法做,賺錢的次數佔幾成。',
    '年化':'換算成平均一年賺(賠)幾 %。',
    '最大回落':'帳戶從最高點最多跌掉幾 %,代表最慘的時候要忍受多大的虧損。',
    '樣本':'過去出現過幾次,次數越多結果越可信。',
    '中位數':'把所有結果排好,正中間那個數,比平均數不容易被極端值影響。',
    'ATR':'平均每天的漲跌幅度,用來看這檔股票平常晃動多大。',
    'KD':'短線強弱指標(0~100)。80 以上＝短線很熱,20 以下＝短線很冷。',
    'RSI':'短線強弱指標(0~100)。70 以上＝漲很多,30 以下＝跌很多。',
    'MACD':'看趨勢方向和力道的指標,柱子由綠翻紅＝轉強。',
    'OBV':'把上漲日的量加、下跌日的量減,看買盤累積的力道。',
    '量比':'今天成交量是平常(近 20 天平均)的幾倍。',
    '爆量':'成交量突然比平常大很多。',
    '成交值':'一天買賣的總金額。',
    '突破':'股價漲過之前一直過不去的高點。',
    '支撐':'跌到這附近常有人買、比較跌不下去的價位。',
    '壓力':'漲到這附近常有人賣、比較漲不上去的價位。',
    '跳空':'今天開盤價和昨天收盤價差很多,中間沒有成交。',
    '漲停':'一天最多能漲的幅度(台股 10%)。',
    '跌停':'一天最多能跌的幅度(台股 10%)。',
    '落底':'跌到最低點、開始不再跌。',
    '止跌':'不再創新低,開始穩住。',
    '錯殺':'好公司被大盤拖累一起大跌,跌得不合理。',
    '超跌':'跌得比平常多很多。',
    '吃貨':'某個大戶或券商分點持續在買進、累積股票。',
    '倒貨':'大戶持續在賣出手上的股票。',
    '隔日沖':'今天買、明天就賣的短線大戶,常造成隔天賣壓。',
    '加權':'台股大盤指數(上市股票)。',
    '櫃買':'上櫃股票的大盤指數,中小型股為主。',
    '費半':'美國費城半導體指數,台股科技股常跟著它走。',
    'VIX':'美股恐慌指數。數字越高＝市場越害怕。',
    'ETF':'一次買一籃子股票的基金,在股市像股票一樣買賣。',
    '市值':'股價 × 股數,現在值多少錢。',
    '未實現損益':'還沒賣掉、帳面上的賺賠。',
    '加碼':'已經有的股票再多買一些。',
    '多頭':'上漲的趨勢。',
    '空頭':'下跌的趨勢。',
    '放空':'借股票來賣,賭它會跌。',
    '空單':'借股票來賣、賭它會跌的部位。',
    '期貨':'約定未來用某個價格買賣的合約,常被用來押大盤漲跌。',
    '未平倉':'還沒結清的期貨或選擇權合約數量。',
    '選擇權':'付一點錢買「未來可以用某價格買或賣」的權利。',
    '市場寬度':'全市場有幾成股票在上漲趨勢中;越少＝大盤越弱。',
    '綜合分':'本站把基本面、籌碼、技術面加起來的分數。',
  };
  const keys=Object.keys(G).sort((a,b)=>b.length-a.length);
  const esc=k=>k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const RE=new RegExp('('+keys.map(esc).join('|')+')');
  const SKIP='A,BUTTON,SUMMARY,SELECT,OPTION,TEXTAREA,INPUT,LABEL,SCRIPT,STYLE,NOSCRIPT,svg,CANVAS,CODE,PRE,H1,TITLE,ABBR';
  const SKIPC='.kv dt,[data-g],.gbulb,#v2side,header,#mobNav,#chapTabs,#chapSub,#homeTabs,.gl,.gl-pop,[contenteditable],.ht-pop,#stockDock,#navBack,.workspace-menu,footer,.site-foot,.c-code,.hm-idx,.btm-tag,.ext-tag,.vw-bd';
  const BLOCK='.sec-body,.hm-sec,.a3-card,.dim-block,.fav-card,.pt-card,.r-card,section,details,.layout-fold,li,tr,p';
  function blockOf(el){return el.closest(BLOCK)||doc.body;}
  function wrap(node){
    const t=node.nodeValue;if(!t||t.length<2||!RE.test(t))return;
    const el=node.parentElement;if(!el||el.closest(SKIP)||el.closest(SKIPC))return;
    const blk=blockOf(el),used={has:k=>!!blk.querySelector('.gl[data-gl="'+k+'"]'),add:()=>{}};   // 每個區塊每個詞只標第一次;區塊重畫後重新標
    const parts=t.split(RE);if(parts.length<3)return;
    let any=false;const done=new Set();const frag=doc.createDocumentFragment();
    parts.forEach((p,i)=>{
      if(i%2===1&&G[p]&&!used.has(p)&&!done.has(p)){done.add(p);any=true;const s=doc.createElement('span');s.className='gl';s.dataset.gl=p;s.title=G[p];s.tabIndex=0;s.textContent=p;frag.append(s);}
      else if(p)frag.append(doc.createTextNode(p));
    });
    if(any)node.replaceWith(frag);
  }
  function scan(root){
    if(!root||root.nodeType!==1||root.closest&&root.closest(SKIPC))return;
    const w=doc.createTreeWalker(root,NodeFilter.SHOW_TEXT);const list=[];let n;
    while(n=w.nextNode()){if(RE.test(n.nodeValue))list.push(n);if(list.length>4000)break;}
    list.forEach(wrap);
  }
  let pend=new Set(),tm=0;
  function queue(el){pend.add(el);if(tm)return;tm=setTimeout(()=>{tm=0;const L=[...pend];pend=new Set();
    L.forEach(e=>{if(e.isConnected&&!L.some(o=>o!==e&&o.contains(e)))try{scan(e);}catch(x){}});},350);}
  /* 點一下顯示解釋 */
  let pop=null;
  function show(el){
    if(!pop){pop=doc.createElement('div');pop.className='gl-pop';pop.setAttribute('role','tooltip');doc.body.append(pop);}
    pop.innerHTML='<b></b><span></span>';pop.querySelector('b').textContent=el.dataset.gl;pop.querySelector('span').textContent=G[el.dataset.gl]||'';
    pop.style.display='block';const r=el.getBoundingClientRect(),pw=Math.min(300,innerWidth-24);pop.style.width=pw+'px';
    let x=Math.max(12,Math.min(r.left,innerWidth-pw-12)),y=r.bottom+6;
    const ph=pop.offsetHeight;if(y+ph>innerHeight-8)y=Math.max(8,r.top-ph-6);
    pop.style.left=x+'px';pop.style.top=y+'px';
  }
  function hide(){if(pop)pop.style.display='none';}
  doc.addEventListener('click',e=>{const g=e.target.closest&&e.target.closest('.gl');if(g){e.preventDefault();e.stopPropagation();show(g);return;}hide();},true);
  doc.addEventListener('keydown',e=>{const g=e.target.closest&&e.target.closest('.gl');if(g&&(e.key==='Enter'||e.key===' ')){e.preventDefault();show(g);}if(e.key==='Escape')hide();});
  addEventListener('scroll',hide,{passive:true});
  function init(){
    const root=doc.querySelector('.wrap')||doc.body;
    queue(root);
    new MutationObserver(ms=>{for(const m of ms){if(m.type==='childList')m.addedNodes.forEach(a=>{if(a.nodeType===1&&!a.classList.contains('gl')&&!a.classList.contains('gl-pop'))queue(a);else if(a.nodeType===3&&a.parentElement)queue(a.parentElement);});}}).observe(root,{childList:true,subtree:true});
  }
  window.Glossary={G,scan};
  if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',init);else init();
})();
