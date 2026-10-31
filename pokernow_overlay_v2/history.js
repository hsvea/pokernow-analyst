/* Visible Session Log adapter, observed on PokerNow 2026-10-31. No game/network access. */
(function(root){
'use strict';
const number=s=>/^\d+(?:,\d{3})*(?:\.\d+)?$/.test(s)?Number(s.replace(/,/g,'')):null;
const equal=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<.001;
function parse(row){
 const text=String(row.text||'').trim();
 let m=text.match(/^--\s*starting hand\s*#(\d+)\s*(?:\(id:\s*([^ )]+)\))?(.*)$/i);
 if(m)return {type:'start',hand:m[1],handId:m[2]||m[1],variant:m[3]};
 if(/^--\s*ending hand/i.test(text))return {type:'end'};
 m=text.match(/^(Flop|Turn|River):\s*(.*)$/i);
 if(m)return {type:'street',street:m[1].toLowerCase()};
 if(/^Player stacks:/i.test(text))return {type:'stacks'};
 // Only known administrative events may be ignored. Unknown wording blocks advice.
 if(/^The (?:admin approved the player .+ participation with a stack of [\d,.]+\.|player .+ (?:requested a seat\.|quits the game with a stack of [\d,.]+\.))$/.test(text))return {type:'admin'};
 m=text.match(/^(.+?) (posts a small blind of|posts a big blind of|raises to|calls|checks|folds)(?:\s+([\d,.]+))?(?:\s+and go(?:es)? all in)?\s*$/i);
 if(!m)return {type:'unknown'};
 const verb=m[2].toLowerCase(), type=verb.includes('small blind')?'sb':verb.includes('big blind')?'bb':verb==='raises to'?'raise':verb==='calls'?'call':verb==='checks'?'check':'fold';
 const amount=m[3]===undefined?null:number(m[3]);
 if(['sb','bb','raise','call'].includes(type)?amount===null||amount<0:amount!==null)return {type:'unknown'};
 return {type,actor:row.actorId?'p:'+row.actorId:'n:'+m[1],name:m[1],amount};
}
function extract(doc){
 const modal=doc.querySelector('.log-modal');
 if(!modal || modal.hidden || modal.getAttribute('aria-hidden')==='true')return {source:'none',rows:[],current:false};
 const entries=Array.from(modal.querySelectorAll('.log-modal-entries > .entry-ctn'));
 const rows=entries.slice(0,400).map(e=>{
   const p=e.querySelector('p.content');
   const actor=p?.querySelector('abbr[title^="Player ID: "]');
   return {text:(p?.textContent||'').trim().slice(0,1500),actorId:actor?.getAttribute('title').slice(11)||''};
 });
 const historical=Array.from(modal.querySelectorAll('.pagination-button')).some(b=>/^\s*«/.test(b.textContent));
 return {source:'session-log',current:!historical,truncated:entries.length>400,rows:rows.reverse()};
}
function analyze(source,state){
 const result={status:'partial',reason:'Открой LOG / LEDGER: нужен журнал текущей раздачи',events:[],handId:null,scenario:null,bb:null,limpers:0,raises:0,opener:null,call:null,minRaiseTo:null,usable:false};
 if(!source?.rows?.length)return result;
 const all=source.rows.map(parse), start=all.map(e=>e.type).lastIndexOf('start');
 if(start<0){result.reason='Начало раздачи не видно — история неполная';return result;}
 const first=all[start];result.handId=first.handId;result.hand=first.hand;result.variant=first.variant;
 const events=all.slice(start+1);result.events=events;
 const stop=why=>{result.reason=why;return result;};
 if(source.truncated)return stop('Журнал обрезан — история неполная');
 if(!source.current)return stop('Открыта архивная раздача — автоопределение выключено');
 if(state.handId && state.handId!==first.handId && state.handId!==first.hand)return stop('Номер раздачи журнала не совпадает со столом');
 if(events.some(e=>e.type==='unknown'))return stop('Есть нераспознанные строки — уточни ситуацию вручную');
 if(events.some(e=>e.type==='end'))return stop('Эта раздача уже завершена');
 const boardStreet=state.board?.length===0?'preflop':state.board?.length===3?'flop':state.board?.length===4?'turn':state.board?.length===5?'river':'unknown';
 const streets=events.filter(e=>e.type==='street');
 if((streets.at(-1)?.street||'preflop')!==boardStreet)return stop('Улица журнала не совпадает с бордом');
 if(boardStreet!=='preflop'){result.status='postflop';return stop('История отображается; автоматический разбор — только префлоп');}
 const players=state.players||[], byActor=new Map(), amounts=new Map();
 function player(e){
   if(byActor.has(e.actor))return byActor.get(e.actor);
   const matches=players.filter(p=>e.actor.startsWith('p:')?p.profileId===e.actor.slice(2):p.name===e.name);
   if(matches.length!==1)return null;
   const p=matches[0];byActor.set(e.actor,p);return p;
 }
 let sb=null,bb=null,high=0,lastIncrement=0,actionSeen=false;
 const limpers=new Set(),folded=new Set();
 for(const e of events){
   if(['stacks','admin'].includes(e.type))continue;
   const p=player(e);if(!p)return stop('Игрок журнала не сопоставлен однозначно с местом');
   if(folded.has(p))return stop('Действие после фолда — проверь порядок журнала');
   const previous=amounts.get(p)||0;
   if(e.type==='sb'||e.type==='bb'){
     if(actionSeen || (e.type==='sb'?sb:bb) || e.amount<=0)return stop('Неоднозначные блайнды или порядок строк');
     if(e.type==='sb')sb={p,amount:e.amount};else bb={p,amount:e.amount};
     amounts.set(p,e.amount);high=Math.max(high,e.amount);lastIncrement=high;continue;
   }
   actionSeen=true;
   if(!sb||!bb||sb.p===bb.p||sb.amount>bb.amount)return stop('Оба блайнда не подтверждены');
   if(e.type==='raise'){
     if(e.amount<=high || e.amount<=previous)return stop('Повышение не увеличивает ставку');
     const increment=e.amount-high;
     // Short all-in raises need reopening rules absent from this heuristic.
     if(increment+0.001<lastIncrement)return stop('Неполное повышение all-in: нужен ручной разбор');
     lastIncrement=increment;high=e.amount;amounts.set(p,e.amount);
     result.raises++;if(!result.opener)result.opener={name:p.name,profileId:p.profileId,seat:p.seat};
   }else if(e.type==='call'){
     // PokerNow logs the street total: a player who raised to 7 later "calls 30".
     if(e.amount<previous||e.amount>high)return stop('Колл не согласуется со ставками');
     if(e.amount<high && p.stack!==0)return stop('Неполный колл без подтверждённого all-in');
     if(result.raises===0 && p!==bb.p)limpers.add(p);
     amounts.set(p,e.amount);
   }else if(e.type==='check'){
     if(!equal(previous,high))return stop('Чек при неоплаченной ставке — история неполная');
   }else if(e.type==='fold')folded.add(p);
 }
 if(!sb||!bb||sb.p===bb.p||sb.amount>bb.amount)return stop('Оба блайнда не подтверждены');
 for(const p of players){
   if(!equal(p.bet||0,amounts.get(p)||0))return stop('Ставки журнала расходятся со столом — жду обновления');
   if(folded.has(p) && !p.folded)return stop('Фолд журнала ещё не подтверждён столом');
 }
 const hero=state.hero;
 if(!hero)return stop('Hero не определён');
 const call=Math.min(hero.stack??Infinity,Math.max(0,high-(amounts.get(hero)||0)));
 if(state.call!=null && !equal(call,state.call))return stop('Цена колла не совпадает с кнопками стола');
 if(result.raises>3)return stop('Больше 4-бета — сценарий вне модели');
 result.bb=bb.amount;result.limpers=limpers.size;result.call=call;result.facing=high;
 result.heroBet=amounts.get(hero)||0;result.minRaiseTo=high+lastIncrement;
 result.scenario=['unopened','raise','3bet','4bet'][result.raises];
 if(!result.raises&&limpers.size)result.scenario='limped';
 result.status='matched';result.usable=true;result.reason='Начало видно · действия сверены со ставками стола';
 return result;
}
function diagnostic(state,history){
 const players=state.players||[], aliases=new Map();
 players.forEach((p,i)=>{aliases.set('p:'+p.profileId,'Player '+(i+1));aliases.set('n:'+p.name,'Player '+(i+1));});
 const safeEvents=(history.events||[]).map(e=>({type:e.type,actor:e.actor?(aliases.get(e.actor)||'Unknown player'):undefined,amount:e.amount??undefined,street:e.street}));
 return {schema:1,extension:'13.0.0',variant:state.variant||'unknown',street:state.street,boardCount:state.board?.length||0,holeCount:state.hole?.length||0,pot:state.pot,call:state.call,
   players:players.map((p,i)=>({name:'Player '+(i+1),seat:p.seat,stack:p.stack,bet:p.bet,folded:p.folded,isMe:p.isMe,dealer:p.dealer})),
   history:{status:history.status,reason:history.reason,scenario:history.scenario,raises:history.raises,events:safeEvents},
   privacy:'No names, PokerNow IDs, table URL, pairing code, notes, raw log or card values.'};
}
const api={parse,extract,analyze,diagnostic};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.PokerNowHistory=api;
})(globalThis);
