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
    assert.match(root.getElementById('seats').textContent,/Old Name/);
    assert.match(root.getElementById('seats').textContent,/careful/);
    input('pfScenario','');
    assert.match(root.getElementById('preflopAdvice').textContent,/историю повышений/);
  } finally {dom.window.close();}
});
