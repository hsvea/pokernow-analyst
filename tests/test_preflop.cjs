const test=require('node:test');
const assert=require('node:assert/strict');
const pf=require('../pokernow_overlay_v2/preflop.js');
const base={cards:['As','Ah'],players:6,position:'CO',bb:2,stack:200,totalBet:2,heroBet:0,scenario:'unopened'};
test('all table sizes have unique positions',()=>{for(let n=2;n<=10;n++){assert.equal(pf.positions(n).length,n);assert.equal(new Set(pf.positions(n)).size,n);}});
test('AA opens',()=>assert.equal(pf.recommend(base).action,'RAISE'));
test('72o folds UTG',()=>assert.equal(pf.recommend({...base,cards:['7s','2h'],position:'UTG'}).action,'FOLD'));
test('BB checks weak hand for free',()=>assert.equal(pf.recommend({...base,cards:['7s','2h'],position:'BB',heroBet:2}).action,'CHECK'));
test('AA faces 3BB opening: 3bet to 18',()=>assert.equal(pf.recommend({...base,scenario:'raise',totalBet:6}).target,18));
test('AA versus 3bet',()=>assert.equal(pf.recommend({...base,scenario:'3bet',totalBet:18}).action,'4-BET'));
test('KK versus 4bet',()=>assert.equal(pf.recommend({...base,cards:['Ks','Kh'],scenario:'4bet',totalBet:45}).action,'CALL'));
test('weak hand versus 4bet folds',()=>assert.equal(pf.recommend({...base,cards:['8s','7s'],scenario:'4bet',totalBet:45}).action,'FOLD'));
test('raise never exceeds effective stack',()=>{const r=pf.recommend({...base,scenario:'raise',totalBet:8,stack:10});assert.equal(r.target,10);});
test('stack insufficient to raise produces call',()=>{const r=pf.recommend({...base,scenario:'raise',totalBet:8,stack:5});assert.equal(r.action,'CALL');assert.equal(r.call,5);});
test('sizing includes limpers',()=>assert.equal(pf.recommend({...base,scenario:'limped',limpers:2}).target,9));
test('duplicate cards rejected',()=>assert.throws(()=>pf.recommend({...base,cards:['As','As']})));
test('unknown history produces no invented advice',()=>assert.throws(()=>pf.recommend({...base,scenario:''})));
test('invalid bb rejected',()=>assert.throws(()=>pf.recommend({...base,bb:0})));
test('missing position rejected',()=>assert.throws(()=>pf.recommend({...base,position:null})));
test('invalid table size rejected',()=>assert.throws(()=>pf.recommend({...base,players:11})));
test('contradictory action and bet rejected',()=>assert.throws(()=>pf.recommend({...base,totalBet:10})));
test('button position from seats',()=>{const p=Array.from({length:6},(_,seat)=>({seat,dealer:seat===3}));assert.equal(pf.inferPosition(p,p[3]),'BTN');assert.equal(pf.inferPosition(p,p[4]),'SB');assert.equal(pf.inferPosition(p,p[5]),'BB');});
test('heads up button is small blind',()=>{const p=[{seat:0,dealer:true},{seat:1}];assert.equal(pf.inferPosition(p,p[0]),'SB');});
test('unknown dealer does not invent position',()=>assert.equal(pf.inferPosition([{seat:0},{seat:1}],{seat:0}),null));

test('sparse seats and folded players preserve clockwise positions',()=>{
 const p=[{seat:10},{seat:2,dealer:true,folded:true},{seat:5,folded:true},{seat:7}];
 assert.deepEqual(p.map(h=>pf.inferPosition(p,h)),['CO','BTN','SB','BB']);
});
test('new arrivals have no position until dealt in',()=>{
 const p=[{seat:1,dealer:true},{seat:4,waitingNextHand:true},{seat:8}];
 assert.equal(pf.inferPosition(p,p[0]),'SB');assert.equal(pf.inferPosition(p,p[1]),null);
 assert.equal(pf.inferPosition(p,p[2]),'BB');
});
test('ambiguous and duplicate seats fail closed',()=>{
 const p=[{seat:1,dealer:true},{seat:1}];assert.equal(pf.inferPosition(p,p[0]),null);
 p[1].seat=2;p[1].dealer=true;assert.equal(pf.inferPosition(p,p[0]),null);
});

test('unraised table identifies BB by seat without status labels',()=>{
 const p=[{seat:1,dealer:true,bet:0},{seat:3,bet:1},{seat:7,bet:2},{seat:9,bet:0}];
 assert.deepEqual(pf.unraisedSituation(p,p[3],2),{scenario:'unopened',limpers:0});
 p[0].bet=2;assert.deepEqual(pf.unraisedSituation(p,p[3],2),{scenario:'limped',limpers:1});
 p[0].bet=6;assert.equal(pf.unraisedSituation(p,p[3],2),null);
 p[0].bet=0;p[2].bet=0;assert.equal(pf.unraisedSituation(p,p[3],2),null);
});

const raiseState=()=>{const players=[{profileId:'a',seat:0,dealer:true,bet:0},{profileId:'b',seat:1,bet:1},{profileId:'c',seat:2,bet:2}];return {table:'one',dealerKey:'a',handId:'',board:[],bb:2,holdem:true,players,hero:players[0]};};
test('visible sequential raises, calls and repeated scans reconstruct raise/3bet/4bet',()=>{
 const t=pf.raiseTracker(),s=raiseState();assert.equal(t.observe(s,0).scenario,'unopened');
 s.players[1].bet=6;let r=t.observe(s,100);assert.equal(r.scenario,'raise');assert.equal(r.minRaiseTo,10);
 assert.equal(t.observe(s,200).raises,1);
 s.players[2].bet=6;assert.equal(t.observe(s,300).raises,1);
 s.players[0].bet=18;r=t.observe(s,400);assert.equal(r.scenario,'3bet');assert.equal(r.minRaiseTo,30);
 s.players[1].bet=40;r=t.observe(s,500);assert.equal(r.scenario,'4bet');assert.deepEqual(r.targets,[6,18,40]);
 s.players[2].bet=80;assert.equal(t.observe(s,600).usable,false);
});
test('joining after raise requires an observed unraised baseline; new hand recovers',()=>{
 const t=pf.raiseTracker(),s=raiseState();s.players[1].bet=6;
 assert.equal(t.observe(s,0).usable,false);s.players[0].bet=18;assert.equal(t.observe(s,100).usable,false);
 s.dealerKey='b';s.players[0].bet=0;s.players[1].bet=1;assert.equal(t.observe(s,200).usable,true);
});
test('multiple changed bets, gaps, hidden tab and short raises do not invent history',()=>{
 for(const mutate of [s=>{s.players[0].bet=6;s.players[1].bet=18;},s=>{s.players[1].bet=3;},s=>{s.players.pop();},s=>{s.players[2].bet=0;}]){
  const t=pf.raiseTracker(),s=raiseState();t.observe(s,0);mutate(s);assert.equal(t.observe(s,100).usable,false);
 }
 const t=pf.raiseTracker(),s=raiseState();t.observe(s,0);s.players[1].bet=6;assert.equal(t.observe(s,6000).usable,false);
 t.observe(s,6100,false);assert.equal(t.observe(s,6200).usable,false);
});
test('table switch and postflop discard the previous raise chain',()=>{
 const t=pf.raiseTracker(),s=raiseState();t.observe(s,0);s.players[1].bet=6;t.observe(s,100);
 s.table='two';assert.equal(t.observe(s,200).usable,false);
 s.board=['As','Kd','2h'];assert.equal(t.observe(s,300).usable,false);
 s.board=[];s.players[1].bet=1;assert.equal(t.observe(s,400).raises,0);
});

test('postflop price comparison is explicit about its random-range assumption',()=>{
 assert.equal(pf.postflopDecision({pot:100,call:0,equity:null}).action,'CHECK');
 assert.equal(pf.postflopDecision({pot:100,call:50,equity:.5}).action,'CALL · ориентир');
 assert.equal(pf.postflopDecision({pot:100,call:50,equity:.1}).action,'FOLD · ориентир');
 assert.equal(pf.postflopDecision({pot:100,call:50,equity:.34}).action,'Пограничный колл');
 assert.equal(pf.postflopDecision({pot:null,call:10,equity:.9}).action,'Нет цены колла');
 assert.equal(pf.postflopDecision({pot:100,call:10,equity:null}).action,'Считаю equity…');
 assert.match(pf.postflopDecision({pot:100,call:50,equity:.5}).reason,/случайных рук/);
});
