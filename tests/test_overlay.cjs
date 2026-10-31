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
  const dom=new JSDOM('<body><div class="game-type-ctn"><span class="current-type">NLH</span></div><div class="table-cards"></div>'+players+'</body>',{url:'https://www.pokernow.com/games/fixture',runScripts:'outside-only',pretendToBeVisual:true});
  try {
    const w=dom.window;
    const original=w.Element.prototype.attachShadow;
    w.Element.prototype.attachShadow=function(){return original.call(this,{mode:'open'});};
    w.chrome={storage:{local:{get:(_,cb)=>w.queueMicrotask(()=>cb({pairingCode:'a'.repeat(24),bridgeEnabled:true})),set:()=>{}}},runtime:{lastError:null,sendMessage:(_,cb)=>w.queueMicrotask(()=>cb({ok:true,version:'11.0.0',profiles:{'p:id0':{hands:20,vpip:30,pfr:15,aliases:['Old Name','Renamed'],note:'careful'}}}))}};
    w.eval(src('preflop.js'));
    w.eval(src('history.js'));w.eval(src('table_capture.js'));w.eval(src('content.js'));
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
    assert.match(root.getElementById('preflopAdvice').textContent,/число повышений неизвестно/);
    root.getElementById('playersTab').click();root.getElementById('statsSource').value='complete';root.getElementById('statsSource').dispatchEvent(new w.Event('change'));
    assert.match(root.getElementById('activeStatsBody').textContent,/30%/);
    w.chrome.runtime.sendMessage=()=>{}; // Simulate an app that stopped answering.
    const now=w.Date.now();w.Date.now=()=>now+9000;input('pfPlayers','6');
    assert.doesNotMatch(root.getElementById('activeStatsBody').textContent,/30%/);
  } finally {dom.window.close();}
});
const fixture=()=>{
  const dom=new JSDOM(`<body><div class="game-type-ctn"><span class="current-type">NLH</span></div><div class="table-container" data-hand-id="1"><div class="table-cards"></div>${Array.from({length:3},(_,i)=>`<div class="table-player table-player-${i} ${i===0?'you-player':''}"><a href="/players/id${i}">Player ${i}</a><div class="table-player-stack">200</div><div class="table-player-status-message">${i===2?'big blind':''}</div><span class="bet-value">${i===2?'2':'0'}</span>${i===0?'<span class="dealer-button"></span><div class="card-container"><span class="value">A</span><span class="suit">s</span></div><div class="card-container"><span class="value">A</span><span class="suit">h</span></div>':''}</div>`).join('')}</div></body>`,{url:'https://www.pokernow.com/games/fixture',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window, original=w.Element.prototype.attachShadow;
  w.Element.prototype.attachShadow=function(){return original.call(this,{mode:'open'});};
  w.chrome={storage:{local:{get:(_,cb)=>cb({}),set:()=>{}}},runtime:{lastError:null,sendMessage:()=>{}}};
  w.eval(src('preflop.js'));w.eval(src('history.js'));w.eval(src('table_capture.js'));w.eval(src('content.js'));
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
test('live-log adapter supplies raise scenario only for a matched current hand',()=>{
 const {dom,w,el,tick}=fixture();try{
 w.document.querySelector('.table-container').setAttribute('data-hand-id','demo');
 w.document.querySelector('.table-player-1 .bet-value').textContent='1';
 w.document.querySelector('.table-player-2 .bet-value').textContent='6';
 w.document.querySelector('.table-player-2 .table-player-status-message').textContent='raise';
 const area=w.document.createElement('div');area.className='action-buttons';area.innerHTML='Your turn <button>Call 6</button>';w.document.body.append(area);
 const rows=[['-- starting hand #1 (id: demo) No Limit Texas Hold’em --',''],['Player 1 posts a small blind of 1','id1'],['Player 2 posts a big blind of 2','id2'],['Player 2 raises to 6','id2']];
 const log=w.document.createElement('div');log.className='log-modal';
 log.innerHTML='<div class="log-modal-entries">'+rows.reverse().map(([text,id])=>'<div class="entry-ctn"><p class="content">'+(id?'<abbr title="Player ID: '+id+'">'+text.split(' ').slice(0,2).join(' ')+'</abbr>'+text.slice(8):text)+'</p></div>').join('')+'</div><div class="log-modal-controls"></div>';
 w.document.body.append(log);tick();
 assert.match(el('historyStatus').textContent,/сверены/);
 assert.match(el('decisionAction').textContent,/3-BET до 18/);
 assert.equal(el('pfScenario').value,'');assert.match(el('situation').textContent,/из журнала/);
 log.querySelector('.log-modal-controls').innerHTML='<button class="pagination-button">« Hand #2</button>';tick();
 assert.match(el('historyStatus').textContent,/архивная/);assert.equal(el('decisionAction').textContent,'Нужно уточнить');
 }finally{dom.window.close();}
});
test('PLO5 is explicitly unsupported and five hero cards are never truncated to Holdem',()=>{
 const {dom,w,el,tick}=fixture();try{
 w.document.querySelector('.current-type').textContent='PLO5';
 w.document.querySelector('.you-player').insertAdjacentHTML('beforeend','<div class="card-container"><span class="value">K</span><span class="suit">d</span></div><div class="card-container"><span class="value">Q</span><span class="suit">h</span></div><div class="card-container"><span class="value">J</span><span class="suit">c</span></div>');tick();
 assert.match(el('decisionReason').textContent,/PLO5/);assert.equal(el('equity').textContent,'—');
 el('diagnosticPrepare').click();const diagnostic=JSON.parse(el('diagnosticPreview').value);
 assert.equal(diagnostic.holeCount,5);assert.equal(diagnostic.variant,'PLO5');assert.equal(diagnostic.players[0].name,'Player 1');
 assert.equal(el('diagnosticSave').hidden,false);
 }finally{dom.window.close();}
});
test('players tab shows current membership only and removes departed players',()=>{
 const {dom,w,el,root,tick}=fixture();try{
 el('playersTab').click();assert.equal(el('handView').hidden,true);assert.equal(el('tablePlayersView').hidden,false);
 assert.equal(el('activeStatsBody').children.length,3);
 assert.match(el('tableStatsMessage').textContent,/включи передачу/);
 w.document.querySelector('.table-player-1').remove();tick();
 assert.equal(el('activeStatsBody').children.length,2);
 assert.equal(root.querySelector('[data-player="p:id1"]'),null);
 w.document.querySelector('.table-player-2').classList.add('folded');tick();
 assert.equal(el('activeStatsBody').children.length,2);
 el('playersInHand').checked=true;el('playersInHand').dispatchEvent(new w.Event('change'));
 assert.equal(el('activeStatsBody').children.length,1);
 el('playersTab').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
 assert.equal(el('handView').hidden,false);
 }finally{dom.window.close();}
});

test('separate PokerNow dealer chip sets position and follows button movement',()=>{
 const {dom,w,el,tick}=fixture();try{
 const marker=w.document.createElement('div');marker.className='dealer-button-ctn dealer-position-2';
 w.document.querySelector('.table-container').append(marker);tick();
 assert.match(el('situation').textContent,/Позиция: SB/);
 assert.match(el('situation').textContent,/по фишке дилера/);
 assert.match(el('cards').textContent,/HERO · SB/);
 marker.className='dealer-button-ctn dealer-position-1';tick();
 assert.match(el('situation').textContent,/Позиция: BB/);
 // A malformed or duplicate external marker must not fall back to an old nested chip.
 marker.className='dealer-button-ctn';tick();
 assert.match(el('cards').textContent,/позиция \?/);
 marker.className='dealer-button-ctn dealer-position-1';marker.after(marker.cloneNode());tick();
 assert.match(el('cards').textContent,/позиция \?/);
 }finally{dom.window.close();}
});
test('real status icons identify next-hand arrivals without removing folded seats',()=>{
 const {dom,w,el,tick}=fixture();try{
 const player=w.document.querySelector('.table-player-1');
 player.insertAdjacentHTML('beforeend','<p class="table-player-status-icon waiting-next-hand">In Next Hand</p>');tick();
 assert.match(el('situation').textContent,/Игроков: 2/);
 assert.match(el('cards').textContent,/HERO · SB/);
 player.querySelector('.table-player-status-icon').className='table-player-status-icon fold';
 player.querySelector('.table-player-status-icon').textContent='Fold';tick();
 assert.match(el('situation').textContent,/Игроков: 3/);
 assert.match(el('cards').textContent,/HERO · BTN/);
 // Position remains visible on the flop, where the preflop panel is hidden.
 w.document.querySelector('.table-cards').innerHTML=['2','3','4'].map(v=>'<div class="card-container"><span class="value">'+v+'</span><span class="suit">d</span></div>').join('');tick();
 assert.equal(el('preflopPanel').hidden,true);
 assert.match(el('cards').textContent,/HERO · BTN/);
 }finally{dom.window.close();}
});

test('overlay shows loaded version and sends complete hands until Windows acknowledges',()=>{
 const {dom,w,el,tick}=fixture();try{
 assert.equal(el('overlayVersion').textContent,'v'+JSON.parse(src('manifest.json')).version);
 assert.match(el('captureStatus').textContent,/включи передачу/);
 w.document.body.insertAdjacentHTML('beforeend','<div class="log-modal"><div class="log-modal-entries"><div class="entry-ctn"><p class="content">-- ending hand #12 --</p></div><div class="entry-ctn"><p class="content">Player stacks: #1 A (100) | #2 B (100)</p></div><div class="entry-ctn"><p class="content">-- starting hand #12 No Limit Texas Hold\'em --</p></div></div></div>');
 let sent;w.chrome.runtime.sendMessage=(message,cb)=>{sent=message.snapshot;cb({ok:true,tableAck:message.snapshot.tableEvents.map(e=>e.id),capture:{number:'12',status:'saved',added:1,total:1,reason:'Сохранена'},profiles:{}});};
 el('pairInput').value='a'.repeat(24);el('bridgeEnable').checked=true;el('bridgeEnable').dispatchEvent(new w.Event('change'));
 assert.equal(sent.capturedHand.number,'12');assert.match(el('captureStatus').textContent,/полных рук 0/);assert.match(el('captureStatus').textContent,/Сохранена/);
 w.document.querySelector('.log-modal').remove();tick();assert.match(el('captureStatus').textContent,/без LOG/);
 }finally{dom.window.close();}
});

test('visible table action is sent without LOG and appears in live statistics',()=>{
 const {dom,w,el,tick}=fixture();try{
 let sent=[];
 w.chrome.runtime.sendMessage=(m,cb)=>{sent.push(...m.snapshot.tableEvents);cb({ok:true,tableAck:m.snapshot.tableEvents.map(e=>e.id),profiles:{'p:id0':{hands:0,live:{seen:1,actions:1,call:1,raise:0,bet:0,check:0,fold:0}}}});};
 el('pairInput').value='a'.repeat(24);el('bridgeEnable').checked=true;el('bridgeEnable').dispatchEvent(new w.Event('change'));
 w.document.querySelector('.table-player-0 .table-player-status-message').textContent='call';
 w.document.querySelector('.table-player-0 .bet-value').textContent='2';
 const now=w.Date.now();w.Date.now=()=>now+2000;tick();
 assert.equal(sent.filter(e=>e.kind==='call').length,1);tick();assert.equal(sent.filter(e=>e.kind==='call').length,1);
 assert.match(el('captureStatus').textContent,/работает без LOG/);
 el('playersTab').click();assert.equal(el('statsSource').value,'live');assert.match(el('statsBasis').textContent,/частичные/);
 assert.equal(el('activeStatsBody').children[0].children[3].textContent,'1');
 }finally{dom.window.close();}
});

test('ordinary preflop without LOG or big-blind text produces advice and compact percentages',()=>{
 const {dom,w,el,tick}=fixture();try{
 w.document.querySelector('.table-player-2 .table-player-status-message').textContent='';
 w.document.body.insertAdjacentHTML('beforeend','<div class="blind-value">1 / 2</div>');tick();
 assert.match(el('situation').textContent,/До тебя: Без рейза/);
 assert.match(el('decisionAction').textContent,/RAISE/);
 assert.match(el('equitySummary').textContent,/Equity:/);
 assert.equal(el('equitySummary').closest('#analytics'),null);
 w.document.querySelector('.table-player-1 .bet-value').textContent='2';tick();
 assert.match(el('situation').textContent,/До тебя: Лимперы/);
 assert.match(el('situation').textContent,/Лимперов: 1/);
 assert.match(el('decisionAction').textContent,/RAISE/);
 w.document.querySelector('.table-player-1 .bet-value').textContent='6';tick();
 assert.match(el('decisionReason').textContent,/число повышений неизвестно/);
 }finally{dom.window.close();}
});
