/* r1169: calculate through the exact browser functions; read-only, no network or user data. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const contract=require('./plan_notices.js');
function build(root=__dirname,now=new Date()){
 const source=fs.readFileSync(path.join(root,'app.js'),'utf8'),start=source.indexOf('function strategyNumber('),end=source.indexOf('function refreshStrategySummaries(');if(start<0||end<=start)throw Error('Browser contract boundary missing');
 const adj=JSON.parse(fs.readFileSync(path.join(root,'adj1y.json'),'utf8')),profiles=JSON.parse(fs.readFileSync(path.join(root,'context_profiles.json'),'utf8')),data=JSON.parse(fs.readFileSync(path.join(root,'data.json'),'utf8'));
 const c={ADJ1:adj.s,newsEsc:String,a3TiersOf:()=>[],StockPlanNotices:contract};vm.createContext(c);vm.runInContext(source.slice(start,end),c);c.STOCK_CONTEXT_PROFILES=profiles;
 const shardStart=source.indexOf('function twShardKey('),shardEnd=source.indexOf('function chipShardOf(');if(shardStart<0||shardEnd<=shardStart)throw Error('Browser shard contract boundary missing');vm.runInContext(source.slice(shardStart,shardEnd),c);const shards=new Map();
 const stocks={};for(const s of data.stocks||[]){const shard=c.shardOf(s),file=path.join(root,shard);if(!shards.has(shard)){if(!fs.existsSync(file))continue;shards.set(shard,JSON.parse(fs.readFileSync(file,'utf8')));}const k=shards.get(shard)[s.id];if(!k||!Array.isArray(k.o)||!Array.isArray(k.d)||s.etf)continue;const bundle=c.stockContextNoticeInput(s,k.o,k.d,now);if(!bundle)continue;const events=contract.events(bundle);stocks[s.market+':'+s.id]={price:s.price,shard,current:bundle.current,previous:bundle.previous,events};}
 return {schema:1,version:'r1169',generated_at:now.toISOString(),code_sha256:crypto.createHash('sha256').update(source).digest('hex'),stocks};
}
module.exports={build};
if(require.main===module){try{process.stdout.write(JSON.stringify(build()));}catch(e){process.stderr.write('Plan notice calculation failed: '+e.message+'\n');process.exitCode=1;}}
