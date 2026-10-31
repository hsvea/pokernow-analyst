const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const src=name=>fs.readFileSync(require('node:path').join(__dirname,'../pokernow_overlay_v2',name),'utf8');
test('bridge reloads only a matching on-disk version once and rejects foreign tabs',async()=>{
  const vm=require('node:vm');
  let listener, reloads=0, requests=0, saved={};
  const sandbox={AbortSignal, setTimeout:fn=>fn(),fetch:async url=>{
    requests++;
    return {ok:true,json:async()=>url.startsWith('http:')?{ok:true,version:'12.0.0',profiles:{}}:{version:'12.0.0'}};
  },chrome:{runtime:{onMessage:{addListener:fn=>listener=fn},getManifest:()=>({version:'11.0.0'}),getURL:p=>'chrome-extension://fixture/'+p,reload:()=>reloads++},storage:{local:{get:async()=>saved,set:async value=>{saved=value;}}}}};
  vm.runInNewContext(src('background.js'),sandbox);
  const send=url=>new Promise(resolve=>listener({type:'PN_ANALYST_SNAPSHOT',token:'a'.repeat(24),snapshot:{players:[]}},{tab:{url}},resolve));
  assert.equal((await send('https://example.com/games/1')).ok,false);
  assert.equal(requests,0);
  assert.equal((await send('https://www.pokernow.com/games/1')).extensionReloaded,true);
  assert.equal(reloads,1);
  await send('https://www.pokernow.com/games/1');
  assert.equal(reloads,1);
});
test('overlay renders preflop advice and stable-ID profile on a fixture table',async()=>{
  const players=Array.from({length:6},(_,i)=>`<div class="table-player table-player-${i} ${i===2?'you-player':''}"><a href="/players/id${i}">${i===0?'Renamed':'Player '+i}</a><div class="table-player-stack">200</div><div class="table-player-status-message">${i===5?'big blind':''}</div><span class="bet-value">${i===5?'2':'0'}</span>${i===3?'<span class="dealer-button"></span>':''}${i===2?'<div class="card-container"><span class="value">A</span><span class="suit">s</span></div><div class="card-container"><span class="value">A</span><span class="suit">h</span></div>':''}</div>`).join('');
  const dom=new JSDOM('<body><div class="table-cards"></div>'+players+'</body>',{url:'https://www.pokernow.com/games/fixture',runScripts:'outside-only',pretendToBeVisual:true});
  try {
    const w=dom.window;
    const original=w.Element.prototype.attachShadow;
    w.Element.prototype.attachShadow=function(){return original.call(this,{mode:'open'});};
    w.chrome={storage:{local:{get:(_,cb)=>w.queueMicrotask(()=>cb({pairingCode:'a'.repeat(24),bridgeEnabled:true})),set:()=>{}}},runtime:{lastError:null,sendMessage:(_,cb)=>w.queueMicrotask(()=>cb({ok:true,version:'11.0.0',profiles:{'p:id0':{hands:20,vpip:30,pfr:15,aliases:['Old Name','Renamed'],note:'careful'}}}))}};
    w.eval(src('preflop.js'));
    w.eval(src('content.js'));
    await new Promise(r=>setTimeout(r,25));
    const root=w.document.getElementById('pnow-rta-extension-root').shadowRoot;
    const input=(id,value)=>{const e=root.getElementById(id);e.value=value;e.dispatchEvent(new w.Event('input'));};
    input('pfBB','2');input('pfScenario','raise');input('pfFacing','6');input('pfPosition','CO');
    assert.match(root.getElementById('preflopAdvice').textContent,/3-BET до 18/);
    assert.match(root.getElementById('seats').textContent,/VPIP 30%/);
    root.querySelector('[data-seat="p:id0"]').click();
    assert.match(root.getElementById('profileDetail').textContent,/Old Name/);
    assert.match(root.getElementById('profileDetail').textContent,/careful/);
    assert.match(root.getElementById('seats').textContent,/Малая выборка/);
    input('pfScenario','');
    assert.match(root.getElementById('preflopAdvice').textContent,/историю повышений/);
  } finally {dom.window.close();}
});
const fixture=()=>{
  const dom=new JSDOM(`<body><div class="table-container" data-hand-id="1"><div class="table-cards"></div>${Array.from({length:3},(_,i)=>`<div class="table-player table-player-${i} ${i===0?'you-player':''}"><a href="/players/id${i}">Player ${i}</a><div class="table-player-stack">200</div><div class="table-player-status-message">${i===2?'big blind':''}</div><span class="bet-value">${i===2?'2':'0'}</span>${i===0?'<span class="dealer-button"></span><div class="card-container"><span class="value">A</span><span class="suit">s</span></div><div class="card-container"><span class="value">A</span><span class="suit">h</span></div>':''}</div>`).join('')}</div></body>`,{url:'https://www.pokernow.com/games/fixture',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window, original=w.Element.prototype.attachShadow;
  w.Element.prototype.attachShadow=function(){return original.call(this,{mode:'open'});};
  w.chrome={storage:{local:{get:(_,cb)=>cb({}),set:()=>{}}},runtime:{lastError:null,sendMessage:()=>{}}};
  w.eval(src('preflop.js'));w.eval(src('content.js'));
  const root=w.document.getElementById('pnow-rta-extension-root').shadowRoot;
  const el=id=>root.getElementById(id);
  const input=(id,value)=>{el(id).value=value;el(id).dispatchEvent(new w.Event('input'));};
  return {dom,w,root,el,input,tick:()=>input('pfPlayers',el('pfPlayers').value)};
};
test('same cards in new hand clear manual cards, BB and scenario',()=>{
 const {dom,w,el,input,tick}=fixture();try{
 input('pfBB','2');input('pfScenario','raise');input('pfFacing','6');input('potInput','999');
 el('manualEnable').checked=true;el('manualEnable').dispatchEvent(new w.Event('change'));
 w.document.querySelector('.table-container').setAttribute('data-hand-id','2');tick();
 for(const id of ['pfBB','pfScenario','pfFacing','potInput'])assert.equal(el(id).value,'');
 assert.equal(el('manualEnable').checked,false);assert.match(el('freshness').textContent,/сброшены/);
 }finally{dom.window.close();}
});
test('BB evidence is not retained when it disappears',()=>{
 const {dom,w,el,tick}=fixture();try{
 assert.match(el('situation').textContent,/BB: 2/);
 w.document.querySelector('.table-player-2 .table-player-status-message').textContent='';tick();
 assert.match(el('situation').textContent,/BB: неизвестно/);assert.equal(el('decisionAction').textContent,'Нужно уточнить');
 }finally{dom.window.close();}
});
test('hidden and stale table stop advice; a fresh state resumes',()=>{
 const {dom,w,el,input,tick}=fixture();try{
 input('pfBB','2');input('pfScenario','raise');input('pfFacing','6');
 assert.match(el('decisionAction').textContent,/3-BET/);
 Object.defineProperty(w.document,'hidden',{value:true,configurable:true});w.document.dispatchEvent(new w.Event('visibilitychange'));
 assert.match(el('decisionReason').textContent,/скрыта/);assert.equal(el('equity').textContent,'—');
 Object.defineProperty(w.document,'hidden',{value:false,configurable:true});
 const now=w.Date.now();w.Date.now=()=>now+91000;tick();assert.match(el('decisionReason').textContent,/90 секунд/);
 w.document.querySelector('.table-player-1 .table-player-stack').textContent='199';tick();assert.match(el('decisionAction').textContent,/3-BET/);
 }finally{dom.window.close();}
});
test('view controls persist and stable ID opens a player detail',()=>{
 const {dom,w,root,el}=fixture();try{
 assert.equal(el('analytics').hidden,true);el('compactToggle').click();
 el('scaleSelect').value='0.8';el('scaleSelect').dispatchEvent(new w.Event('change'));el('minToggle').click();
 const saved=JSON.parse(w.localStorage.getItem('pnow-rta-overlay-v1'));
 assert.equal(saved.compact,false);assert.equal(saved.scale,.8);assert.equal(saved.minimized,true);assert.equal(el('body').hidden,true);
 root.querySelector('[data-seat="p:id1"]').click();assert.match(el('profileDetail').textContent,/Player 1/);
 }finally{dom.window.close();}
});
test('board reset and table change invalidate previous manual situation',()=>{
 const {dom,w,el,input,tick}=fixture();try{
 w.document.querySelector('.table-cards').innerHTML='<div class="card-container"><span class="value">K</span><span class="suit">c</span></div>';tick();input('holeInput','Kd Kh');
 w.document.querySelector('.table-cards').innerHTML='';tick();assert.equal(el('holeInput').value,'');
 input('pfBB','8');w.history.pushState({},'', '/games/another');tick();assert.equal(el('pfBB').value,'');assert.match(el('freshness').textContent,/Другой стол/);
 }finally{dom.window.close();}
});
