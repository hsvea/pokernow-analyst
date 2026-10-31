const test=require('node:test'),assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const h=require('../pokernow_overlay_v2/history.js');
const row=(text,actorId='')=>({text,actorId});
const initial=()=>[row('-- starting hand #20 (id: demo20) No Limit Texas Hold’em --'),row('Player stacks: #1 Hero (200) | #2 Small (200) | #3 Big (200)'),row('Small posts a small blind of 1','s'),row('Big posts a big blind of 2','b')];
const state=()=>{const players=[{profileId:'h',name:'Hero',seat:0,bet:0,stack:200,dealer:true},{profileId:'s',name:'Small',seat:1,bet:1,stack:199},{profileId:'b',name:'Big',seat:2,bet:2,stack:198}];return {players,hero:players[0],board:[],call:2};};
const analyze=(rows,s=state(),more={})=>h.analyze({source:'session-log',rows,current:true,...more},s);
test('unopened with complete visible boundary and matched blinds',()=>{
 const r=analyze(initial());assert.equal(r.usable,true);assert.equal(r.scenario,'unopened');assert.equal(r.bb,2);assert.equal(r.call,2);
});
test('raise, 3bet, 4bet and exact minimum raise are reconstructed',()=>{
 const s=state(),rows=initial();rows.push(row('Hero raises to 7','h'));s.players[0].bet=7;s.players[0].stack=193;s.call=0;
 assert.equal(analyze(rows,s).scenario,'raise');
 rows.push(row('Small raises to 30','s'));s.players[1].bet=30;s.players[1].stack=170;s.call=23;
 let r=analyze(rows,s);assert.equal(r.scenario,'3bet');assert.equal(r.minRaiseTo,53);assert.equal(r.opener.profileId,'h');
 rows.push(row('Big raises to 70','b'));s.players[2].bet=70;s.players[2].stack=130;s.call=63;
 assert.equal(analyze(rows,s).scenario,'4bet');
});
test('PokerNow call amount is street total, not additional contribution',()=>{
 const s=state(),rows=initial();rows.push(row('Hero raises to 7','h'),row('Small raises to 30','s'),row('Hero calls 30','h'));
 s.players[0].bet=30;s.players[0].stack=170;s.players[1].bet=30;s.players[1].stack=170;s.call=0;
 assert.equal(analyze(rows,s).usable,true);
 s.players[0].bet=37;assert.equal(analyze(rows,s).usable,false);
});
test('limper count excludes blinds and counts players once',()=>{
 const s=state(),rows=initial();rows.push(row('Hero calls 2','h'));s.players[0].bet=2;s.players[0].stack=198;s.call=0;
 const r=analyze(rows,s);assert.equal(r.scenario,'limped');assert.equal(r.limpers,1);
});
for(const [name,edit,option] of [
 ['missing start',r=>r.shift()],['missing blind',r=>r.pop()],['unknown action',r=>r.push(row('Hero straddles 4','h'))],
 ['finished hand',r=>r.push(row('-- ending hand #20 --'))],['historical page',()=>{},{current:false}],['truncated log',()=>{},{truncated:true}],
 ['short all-in raise',r=>r.push(row('Hero raises to 3 and goes all in','h'))]
])test(name+' blocks automatic advice',()=>{const rows=initial();edit(rows);assert.equal(analyze(rows,state(),option).usable,false);});
test('unknown player identity, duplicate names, street and call mismatch block advice',()=>{
 let s=state();s.call=9;assert.equal(analyze(initial(),s).usable,false);
 s=state();s.board=['As','Kd','2h'];assert.equal(analyze(initial(),s).usable,false);
 s=state();s.handId='21';assert.equal(analyze(initial(),s).usable,false);
 s=state();s.players[1].profileId='different';assert.equal(analyze(initial(),s).usable,false);
 s=state();s.players[1].name='Hero';const rows=initial();rows.push(row('Hero calls 2'));assert.equal(analyze(rows,s).usable,false);
});
test('latest start supersedes old completed hands',()=>{
 const rows=[row('-- starting hand #19 --'),row('-- ending hand #19 --'),...initial()];assert.equal(analyze(rows).hand,'20');
});
test('adapter matches observed live DOM: newest first, actor abbr IDs, archive control',()=>{
 const doc=new JSDOM(`<div class="log-modal"><div class="log-modal-entries"><div class="entry-ctn"><span class="at">17:23</span><p class="content"><span><abbr title="Player ID: b">Big</abbr> posts a big blind of 2</span></p></div><div class="entry-ctn"><p class="content">-- starting hand #20 --</p></div></div><div class="log-modal-controls"><button class="pagination-button">Hand #19 »</button></div></div>`).window.document;
 const source=h.extract(doc);assert.equal(source.rows[0].text,'-- starting hand #20 --');assert.equal(source.rows[1].actorId,'b');assert.equal(source.current,true);
 doc.querySelector('button').textContent='« Hand #21';assert.equal(h.extract(doc).current,false);
});
test('diagnostic omits actual identities, cards, URL, notes and raw text',()=>{
 const s=state();s.hole=['As','Ah'];s.board=['Kd','7c','2s'];s.table='https://secret';s.pairingCode='secret-token';s.players[0].name='PRIVATE PERSON';
 const history=analyze(initial());history.events.push({type:'unknown',raw:'PRIVATE CHAT'});
 const result=JSON.stringify(h.diagnostic(s,history));
 for(const secret of ['PRIVATE PERSON','PRIVATE CHAT','secret-token','https://secret','As','Kd','demo20'])assert.equal(result.includes(secret),false,secret);
 assert.equal(JSON.parse(result).holeCount,2);assert.match(result,/Player 1/);
});
test('sanitized observed-format example parses every known event',()=>{
 const fixture=require('../examples/session_log_synthetic.json');
 assert.equal(fixture.rows.map(h.parse).some(e=>e.type==='unknown'),false);
 assert.equal(fixture.rows.map(h.parse).filter(e=>e.type==='raise').length,2);
});
