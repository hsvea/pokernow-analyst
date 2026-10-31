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
