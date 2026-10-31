/* PokerNow RTA Overlay — local read-only HUD. No network, no click automation. */
(() => {
  'use strict';
  if (!/https?:\/\/(?:www\.)?pokernow\.(?:com|club)\/games\//.test(location.href)) return;
  if (document.getElementById('pnow-rta-extension-root')) return;

  const $ = (s, from=document) => from.querySelector(s);
  const $$ = (s, from=document) => Array.from(from.querySelectorAll(s));
  const storageKey = 'pnow-rta-overlay-v1';
  const settings = (() => { try { return JSON.parse(localStorage.getItem(storageKey)) || {}; } catch { return {}; } })();
  let notes = settings.notes || '';
  let showBadges = settings.showBadges !== false;
  let minimized = !!settings.minimized;
  let manualEnabled = false;
  let current = null;
  let simToken = 0;
  let lastSignature = '';
  let lastEquity = null;
  let trialsRun = 0;
  let debounceId = null;
  let destroyed = false;
  let pairingCode = '';
  let bridgeEnabled = false;
  let lastBridgeSent = 0;

  const persist = () => {
    try { localStorage.setItem(storageKey, JSON.stringify({ x: settings.x, y: settings.y, notes, showBadges, minimized })); } catch {};
  };

  // Read-only inspection of public/visible DOM: never accesses PokerNow network or game actions.
  const normalizeNumber = v => {
    const str = String(v || '').replace(/\s/g, '').replace(/,/g, '');
    const m = str.match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : null;
  };
  const money = n => n == null || !Number.isFinite(n) ? '—' : Number(n).toLocaleString('ru-RU',{maximumFractionDigits:2});
  const getText = el => el?.textContent?.trim() || '';
  const suits = { h:'h', hearts:'h', heart:'h', '♥':'h', '♡':'h', d:'d', diamond:'d', diamonds:'d','♦':'d','♢':'d',s:'s', spade:'s', spades:'s','♠':'s','♤':'s',c:'c',club:'c',clubs:'c','♣':'c','♧':'c' };
  const suitGlyphs = {h:'♥',d:'♦',c:'♣',s:'♠'};
  const rankList = '23456789TJQKA';
  const allCards = Array.from({length:13*4},(_,i)=>rankList[i>>2]+ 'cdhs'[i%4]);
  const normCard = text => {
    const m = String(text||'').replace(/10/gi,'T').replace(/[♣♧]/g,'c').replace(/[♦♢]/g,'d').replace(/[♥♡]/g,'h').replace(/[♠♤]/g,'s').trim().match(/^([2-9TJQKA])([CDHS])$/i);
    return m ? m[1].toUpperCase()+m[2].toLowerCase() : null;
  };
  function readCard(container) {
    const val = getText($('.value',container)).replace(/^10$/,'T').toUpperCase();
    if (!/^[2-9TJQKA]$/.test(val)) return null;
    const suitEls = $$('.suit',container);
    for (const s of suitEls.reverse()) {
      const text = getText(s).toLowerCase();
      let suit = suits[text];
      if (!suit) suit = [...s.classList].map(c=>suits[c.toLowerCase()]).find(Boolean);
      if (suit) return val+suit;
    }
    return null;
  }
  function readCards(parent) {
    if (!parent) return [];
    const result = $$('.card-container',parent).map(readCard).filter(Boolean);
    return [...new Set(result)];
  }
  function readPot() {
    const el = $('.table-pot-size');
    if (!el) return null;
    const text = getText(el);
    const total = text.match(/total\s*[:]?\s*([\d,.]+)/i);
    if (total) return normalizeNumber(total[1]);
    const nums = text.match(/\d[\d,.]*/g) || [];
    return nums.length ? normalizeNumber(nums[nums.length - 1]) : null;
  }
  function readCall() {
    const area = $('.action-buttons');
    if (!area) return {call: null, onTurn: false, action:''};
    const myTurn = !!$('.table-player.decision-current.you-player') || /your turn/i.test(getText(area));
    const buttonTexts = $$('button',area).filter(b=>!b.disabled).map(getText);
    const btn = buttonTexts.find(t=>/\bcall\b/i.test(t) && !/call any|auto/i.test(t));
    const check = buttonTexts.some(t=>/\bcheck\b/i.test(t) && !/check or fold/i.test(t));
    return {call: btn ? normalizeNumber(btn.replace(/^.*?\bcall\b/i,'')) : check ? 0 : null,
      onTurn: myTurn || buttonTexts.some(t=>/^call\b|^fold\b|^raise\b|^bet\b/i.test(t)) && !/^(?:check or fold|call any)$/i.test(buttonTexts.join('')),
      action: buttonTexts.filter(t=>/^(fold|call|check|raise|bet|all in)/i.test(t)).slice(0,4).join(' · ')};
  }
  function readPlayers() {
    return $$('.table-player').map(el=>{
      const link = $('a[href*="/players/"]',el);
      if (!link) return null;
      const name = getText(link);
      if (!name) return null;
      const stackEl = $('.table-player-stack',el) || $('[class*="player-stack"]',el);
      const betEl = $('[class*="bet-value"]',el);
      const statusEl = $('.table-player-status-message',el);
      const playerCards = readCards(el);
      const profileId = (link.getAttribute('href') || '').split('/players/')[1]?.split(/[/?#]/)[0] || '';
      return {el,name,profileId,stack:normalizeNumber(getText(stackEl)),bet:normalizeNumber(getText(betEl))||0,
        status:getText(statusEl),isMe:el.classList.contains('you-player'),
        folded:el.classList.contains('fold')||el.classList.contains('folded')||/\bfold\b/i.test(getText(statusEl)),
        cards:playerCards};
    }).filter(Boolean);
  }
  function getState() {
    const players = readPlayers();
    const hero = players.find(x=>x.isMe) || null;
    const board = readCards($('.table-cards')).slice(0,5);
    const hole = hero?.cards?.slice(0,2) || [];
    const actions = readCall();
    const pot = readPot();
    const opponents = Math.max(1,players.filter(x=>x!==hero&&!x.folded).length);
    const hand = [hole,...board].map(x=>Array.isArray(x)?x.join(','):x).join('|');
    const duplicateCards = new Set([...hole,...board]).size !== [...hole,...board].length;
    return {players,hero,hole,board,pot,opponents,...actions,hand,duplicateCards,
      street: board.length===0?'PREFLOP':board.length===3?'FLOP':board.length===4?'TURN':board.length===5?'RIVER':'РАЗДАЧА'};
  }

  const host = document.createElement('div');
  host.id='pnow-rta-extension-root';
  host.style.cssText='position:fixed;inset:0;z-index:2147483600;pointer-events:none;';
  const root=host.attachShadow({mode:'closed'});
  root.innerHTML=`<style>
    :host{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#e8fbff}
    *{box-sizing:border-box}
    #panel{position:fixed;left:calc(100vw - 380px);top:70px;width:348px;max-width:calc(100vw - 16px);min-width:300px;max-height:calc(100vh - 20px);overflow:hidden;display:flex;flex-direction:column;border-radius:16px;border:1px solid rgba(44,217,238,.62);background:linear-gradient(135deg,rgba(14,30,47,.97),rgba(6,12,25,.975));box-shadow:0 12px 50px rgba(0,0,0,.6),0 0 20px rgba(6,208,244,.2);pointer-events:auto;font-size:13px;line-height:1.35}
    .header{display:flex;align-items:center;justify-content:space-between;padding:12px 13px;background:linear-gradient(90deg,#0b3442,#0c2035);cursor:grab;user-select:none;touch-action:none;border-bottom:1px solid #17485b}
    .header:active{cursor:grabbing}
    .brand{font-size:15px;font-weight:800;letter-spacing:.3px}.brand em{font-style:normal;color:#50e9e7}
    .tools{display:flex;align-items:center;gap:5px}
    button{background:#142a3d;border:1px solid #285366;color:#d2efff;border-radius:8px;cursor:pointer;padding:5px 9px;font:inherit;touch-action:manipulation}
    button:hover{border-color:#60e6f6;background:#1a3f52}
    .icon{min-width:27px;padding:3px 5px;font-weight:700}
    #body{overflow-y:auto;padding:10px 12px 12px;scrollbar-width:thin;scrollbar-color:#2b7885 #0a1b2a}
    .status{font-size:11px;color:#85acc5;margin:0 0 9px;display:flex;align-items:center;gap:6px}
    .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#ffd66e;box-shadow:0 0 7px #ffd66e}
    .dot.ok{background:#42e1af;box-shadow:0 0 7px #42e1af}
    .strip{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:3px 0 10px}
    .pill{background:#0c3040;color:#bceaff;border:1px solid #205368;border-radius:6px;padding:4px 6px;font-weight:700;font-size:12px}
    .pill.hero{border-color:#f3c15c;color:#ffe19b}
    .eyebrow{color:#7bc2d0;text-transform:uppercase;font-size:10px;font-weight:700;letter-spacing:.9px;margin:12px 0 6px}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
    .metric{background:#081d2c;border:1px solid #1c4556;border-radius:9px;padding:8px 7px;min-height:57px}
    .metric small{display:block;color:#83b3c7;font-size:10px;margin-bottom:3px}
    .metric b{font-size:19px;color:#f1fdff;letter-spacing:.2px}
    .metric .green{color:#54f1bc}.metric .amber{color:#ffd17c}
    .equity{border:1px solid #17666a;border-radius:11px;background:linear-gradient(110deg,#0b2d35,#14243b);padding:10px 12px;margin:10px 0}
    .equityHead{display:flex;justify-content:space-between;align-items:end}
    .equityHead strong{font-size:26px;color:#75f7d0;font-variant-numeric:tabular-nums}
    .bar{height:7px;background:#153347;border-radius:7px;overflow:hidden;margin:7px 0}
    .bar i{display:block;width:0%;height:100%;background:linear-gradient(90deg,#28afe8,#45e8ac);transition:width .3s}
    .muted{color:#88adbc;font-size:11px}
    .insight{padding:8px 10px;border-left:3px solid #4199b7;border-radius:4px;background:#0c2638;color:#cfe4ee;font-size:12px}
    .insight.positive{border-color:#53e1aa}.insight.negative{border-color:#ffc56b}
    .row{display:flex;justify-content:space-between;gap:9px;margin:7px 0;align-items:center}
    .row label{color:#a7cad8}
    input,textarea{min-width:0;width:100%;padding:7px;border:1px solid #2c5768;background:#061b2c;color:#e6fcff;border-radius:6px;font:inherit}
    input:focus,textarea:focus{outline:1px solid #47cbdc}
    .inputrow{display:grid;grid-template-columns:80px 1fr;gap:7px;align-items:center;margin:7px 0}
    .small{font-size:11px}.subtle{color:#7ba8b5}
    details{margin-top:10px;border-top:1px solid #244454;padding-top:8px}
    details summary{cursor:pointer;color:#a7eaf1;font-weight:700;user-select:none}
    .foot{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:10px;color:#7299ad;font-size:10px}
    #seats{position:fixed;inset:0;pointer-events:none}
    .seat{position:fixed;max-width:145px;min-width:90px;transform:translate(-50%,0);pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center;border:1px solid rgba(51,172,199,.68);background:rgba(1,18,31,.88);color:#d5f6fe;padding:4px 8px;border-radius:7px;box-shadow:0 3px 14px #0009;font-size:10px;line-height:1.4;text-shadow:0 1px 1px #000}
    .seat.me{border-color:#ffcc6e;box-shadow:0 0 12px #c48d3380}
    .seat.folded{opacity:.6}
    .seat b{font-size:11px;color:#fff}
    .seat .caption{color:#8bd6e8}
    @media(max-width:630px){#panel{width:310px}.metric b{font-size:15px}}
  </style>
  <div id="seats"></div>
  <section id="panel" role="region" aria-label="PokerNow RTA overlay">
    <div id="drag" class="header">
      <div class="brand">♠ PokerNow <em>RTA</em></div>
      <div class="tools"><button class="icon" id="seatsToggle" title="Показать/скрыть панели игроков">♟</button><button class="icon" id="minToggle" title="Свернуть/развернуть">−</button><button class="icon" id="close" title="Закрыть оверлей">×</button></div>
    </div>
    <div id="body">
      <div class="status"><i id="stateDot" class="dot"></i><span id="stateText">Ожидаю данные стола…</span></div>
      <div class="strip" id="cards"></div>
      <div class="grid">
        <div class="metric"><small>Банк</small><b id="pot">—</b></div>
        <div class="metric"><small>Нужно коллировать</small><b id="call">—</b></div>
        <div class="metric"><small>Pot Odds</small><b id="odds">—</b></div>
      </div>
      <div class="equity"><div class="equityHead"><div><div class="muted">Equity vs случайные руки</div><strong id="equity">—</strong></div><div class="muted" id="equityMeta">Нет карт</div></div><div class="bar"><i id="equityBar"></i></div><div class="muted" id="equityNote">Monte Carlo · открытые карты, без чтения скрытых рук</div></div>
      <div class="insight" id="advice">Ожидаю данные…</div>
      <div class="row"><label>Оппонентов в симуляции</label><span id="oppInfo">—</span></div>
      <div class="row"><label>Расчётный EV колла*</label><strong id="ev">—</strong></div>
      <details id="manualSection"><summary>✎ Ручная корректировка данных</summary>
        <label class="row"><span>Использовать ручные значения</span><input id="manualEnable" type="checkbox" style="width:auto" /></label>
        <div id="manualForm">
          <div class="inputrow"><label for="holeInput">Мои карты</label><input id="holeInput" placeholder="Ah Kd" /></div>
          <div class="inputrow"><label for="boardInput">Борд</label><input id="boardInput" placeholder="Qs Jh 2c" /></div>
          <div class="inputrow"><label for="potInput">Банк</label><input id="potInput" type="number" min="0" step="any" placeholder="Авто" /></div>
          <div class="inputrow"><label for="callInput">Call</label><input id="callInput" type="number" min="0" step="any" placeholder="Авто" /></div>
          <div class="inputrow"><label for="oppInput">Оппоненты</label><input id="oppInput" type="number" min="1" max="9" step="1" placeholder="Авто" /></div>
          <div class="row"><button id="clearManual">Сбросить значения</button><span class="small subtle">Для нестандартных столов</span></div>
        </div>
      </details>
      <details><summary>🖥 Windows Analyst · сбор метрик</summary>
        <div class="muted" style="margin:8px 0">Связь с приложением через 127.0.0.1. Передаётся только видимое состояние стола. Включается вручную.</div>
        <div class="inputrow"><label for="pairInput">Код из Windows</label><input id="pairInput" placeholder="24 символа из программы" maxlength="24" autocomplete="off" /></div>
        <label class="row"><span>Передавать данные</span><input id="bridgeEnable" type="checkbox" style="width:auto" /></label>
        <div id="bridgeStatus" class="small subtle">Не подключено</div>
      </details>
      <details><summary>Заметки за столом</summary><textarea id="notes" rows="3" maxlength="4000" placeholder="Заметки (сохраняются только в этом браузере)"></textarea></details>
      <div class="foot"><span>* EV по случайным рукам, без рейка и фолд-эквити; не GTO</span><span>Alt+R — панель</span></div>
    </div>
  </section>`;
  document.documentElement.appendChild(host);
  const el = id => root.getElementById(id);
  const panel = el('panel');
  const setText = (id, v) => { el(id).textContent = String(v); };
  if (Number.isFinite(settings.x) && Number.isFinite(settings.y)) {
    panel.style.left=Math.max(0,Math.min(innerWidth-120,settings.x))+'px';
    panel.style.top=Math.max(0,Math.min(innerHeight-55,settings.y))+'px';
  }
  function applyMin(){el('body').hidden=minimized;el('minToggle').textContent=minimized?'+':'−';persist();}
  applyMin();
  el('close').onclick=()=>{destroyed=true;observer.disconnect();clearTimeout(debounceId);clearInterval(pollId);window.removeEventListener('resize', schedule);window.removeEventListener('keydown', hotkey);host.remove();};
  el('minToggle').onclick=()=>{minimized=!minimized;applyMin();};
  el('seatsToggle').onclick=()=>{showBadges=!showBadges;el('seats').style.display=showBadges?'':'none';persist();};
  el('seats').style.display=showBadges?'':'none';
  el('pairInput').value = pairingCode;
  el('bridgeEnable').checked = bridgeEnabled;
  el('pairInput').oninput = () => {
    pairingCode = el('pairInput').value.trim().toLowerCase();
    if (!/^[a-f0-9]{24}$/.test(pairingCode)) {
      bridgeEnabled=false;el('bridgeEnable').checked=false;
    }
    chrome.storage.local.set({pairingCode,bridgeEnabled});
  };
  el('bridgeEnable').onchange=()=>{
    pairingCode=el('pairInput').value.trim().toLowerCase();
    if (!/^[a-f0-9]{24}$/.test(pairingCode)){
      bridgeEnabled=false;el('bridgeEnable').checked=false;
      setText('bridgeStatus','Нужен корректный 24-символьный код из Windows-приложения');return;
    }
    bridgeEnabled=el('bridgeEnable').checked;chrome.storage.local.set({pairingCode,bridgeEnabled});lastBridgeSent=0;update();
    setText('bridgeStatus',bridgeEnabled?'Соединение…':'Передача выключена');
  };
  chrome.storage.local.get(['pairingCode','bridgeEnabled'], cfg=>{
    pairingCode=typeof cfg?.pairingCode==='string'?cfg.pairingCode:'';
    bridgeEnabled=!!cfg?.bridgeEnabled && /^[a-f0-9]{24}$/.test(pairingCode);
    el('pairInput').value=pairingCode;el('bridgeEnable').checked=bridgeEnabled;
    if(bridgeEnabled){lastBridgeSent=0;update();}
  });
  el('notes').value=notes;
  el('notes').oninput=()=>{notes=el('notes').value;persist();};
  function hotkey(ev){if(ev.altKey && ev.key.toLowerCase()==='r' && !ev.repeat){ev.preventDefault();minimized=!minimized;applyMin();}}
  window.addEventListener('keydown',hotkey);
  // Dragging is limited to the title bar, not table inputs or buttons.
  let drag=null;
  el('drag').addEventListener('pointerdown',ev=>{
    if(ev.button!==0||ev.target.closest('button'))return;
    drag={x:ev.clientX,y:ev.clientY,left:panel.getBoundingClientRect().left,top:panel.getBoundingClientRect().top};
    el('drag').setPointerCapture(ev.pointerId);
  });
  el('drag').addEventListener('pointermove',ev=>{
    if(!drag)return;
    settings.x=Math.min(innerWidth-80,Math.max(0,drag.left+ev.clientX-drag.x));
    settings.y=Math.min(innerHeight-40,Math.max(0,drag.top+ev.clientY-drag.y));
    panel.style.left=settings.x+'px';panel.style.top=settings.y+'px';
  });
  el('drag').addEventListener('pointerup',()=>{if(drag){drag=null;persist();}});
  el('drag').addEventListener('pointercancel',()=>{drag=null;});
  el('manualEnable').onchange=()=>{manualEnabled=el('manualEnable').checked;update();};
  ['holeInput','boardInput','potInput','callInput','oppInput'].forEach(id=>el(id).addEventListener('input',()=>{if(manualEnabled)update();}));
  el('clearManual').onclick=()=>{['holeInput','boardInput','potInput','callInput','oppInput'].forEach(id=>el(id).value='');manualEnabled=false;el('manualEnable').checked=false;update();};
  const parseInputCards=(s,max)=>String(s).replace(/[,;]+/g,' ').split(/\s+/).map(normCard).filter(Boolean).slice(0,max);
  function getEffective(s){
    const v={...s};
    if(manualEnabled){
      if(el('holeInput').value.trim())v.hole=parseInputCards(el('holeInput').value,2);
      if(el('boardInput').value.trim())v.board=parseInputCards(el('boardInput').value,5);
      for(const [id,key] of [['potInput','pot'],['callInput','call'],['oppInput','opponents']]){
        if(el(id).value.trim()!=='') v[key]=Number(el(id).value);
      }
      v.opponents=Math.min(9,Math.max(1,Math.floor(v.opponents)));
      v.duplicateCards=new Set([...v.hole,...v.board]).size!==v.hole.length+v.board.length;
      v.street=v.board.length===0?'PREFLOP':v.board.length===3?'FLOP':v.board.length===4?'TURN':v.board.length===5?'RIVER':'РАЗДАЧА';
    }
    return v;
  }

  // 5-card rank encoding (15-based integer digits) and best-5-of-7 evaluator.
  function evaluate5(cards) {
    const vals=cards.map(c=>rankList.indexOf(c[0])+2).sort((a,b)=>b-a);
    const flush=cards.every(c=>c[1]===cards[0][1]);
    const counts=new Map();for(const v of vals)counts.set(v,(counts.get(v)||0)+1);
    const unique=[...new Set(vals)];if(unique.includes(14))unique.push(1);
    let straight=0;
    for(let i=0;i<=unique.length-5;i++) if(unique[i]-unique[i+4]===4){straight=unique[i];break;}
    const byCount=[...counts].map(([v,n])=>({v,n})).sort((a,b)=>b.n-a.n||b.v-a.v);
    const pack=(cat,ks)=>{let score=cat;for(let i=0;i<5;i++)score=score*15+(ks[i]||0);return score;}; // fixed-width category ranking
    if(flush && straight)return pack(8,[straight]);
    if(byCount[0].n===4)return pack(7,[byCount[0].v,byCount[1].v]);
    if(byCount[0].n===3&&byCount[1].n>=2)return pack(6,[byCount[0].v,byCount[1].v]);
    if(flush)return pack(5,vals);
    if(straight)return pack(4,[straight]);
    if(byCount[0].n===3)return pack(3,[byCount[0].v,...byCount.slice(1).map(x=>x.v).sort((a,b)=>b-a)]);
    if(byCount[0].n===2&&byCount[1].n===2){const pairs=[byCount[0].v,byCount[1].v].sort((a,b)=>b-a);return pack(2,[...pairs,byCount[2].v]);}
    if(byCount[0].n===2)return pack(1,[byCount[0].v,...byCount.slice(1).map(x=>x.v).sort((a,b)=>b-a)]);
    return pack(0,vals);
  }
  function eval7(cards){let best=-1;const n=cards.length;for(let a=0;a<n-4;a++)for(let b=a+1;b<n-3;b++)for(let c=b+1;c<n-2;c++)for(let d=c+1;d<n-1;d++)for(let e=d+1;e<n;e++){const score=evaluate5([cards[a],cards[b],cards[c],cards[d],cards[e]]);if(score>best)best=score;}return best;}
  // A Monte Carlo estimate for random, independent 2-card opponents; not a preflop/GTO range solver.
  function calculateAsync(v){
    const signature=[v.hole.join(','),v.board.join(','),v.opponents].join('|');
    if(signature===lastSignature && lastEquity!==null)return;
    lastSignature=signature;lastEquity=null;trialsRun=0;
    const token=++simToken;
    if(v.hole.length!==2||![0,3,4,5].includes(v.board.length)||v.duplicateCards){setText('equity','—');el('equityBar').style.width='0%';setText('equityMeta','Нужны карты');setText('equityNote',v.duplicateCards?'Ошибка: повторяющиеся карты':'Ожидание двух карт Hero и корректного борда');renderAdvice(v);return;}
    const used=new Set([...v.hole,...v.board]);const remaining=allCards.filter(c=>!used.has(c));
    const needed=(5-v.board.length)+2*v.opponents;
    if(remaining.length<needed){setText('equity','—');setText('equityMeta','Ошибка колоды');return;}
    setText('equity','…');setText('equityMeta','Расчёт');el('equityBar').style.width='0%';
    const total=v.opponents<=2?1800:v.opponents<=5?1000:550;
    let score=0;
    function chunk(){
      if(token!==simToken||destroyed)return;
      for(let iter=0;iter<Math.min(70,total-trialsRun);iter++){
        const shuffled=remaining.slice();
        // Only shuffle as many cards as needed (partial Fisher–Yates).
        for(let i=0;i<needed;i++){const j=i+Math.floor(Math.random()*(shuffled.length-i));[shuffled[i],shuffled[j]]=[shuffled[j],shuffled[i]];}
        const b=[...v.board,...shuffled.slice(0,5-v.board.length)];
        const heroRank=eval7([...v.hole,...b]);
        let highest=heroRank;let ties=1;
        let ix=5-v.board.length;
        for(let p=0;p<v.opponents;p++){
          const enemy=eval7([shuffled[ix++],shuffled[ix++],...b]);
          if(enemy>highest){highest=enemy;ties=1;}
          else if(enemy===highest)ties++;
        }
        if(heroRank===highest)score+=1/ties;
      }
      trialsRun+=Math.min(70,total-trialsRun);
      if(trialsRun>=total){lastEquity=score/total;setText('equity','≈ '+(lastEquity*100).toFixed(1)+'%');el('equityBar').style.width=(lastEquity*100).toFixed(1)+'%';setText('equityMeta',total+' сим.');setText('equityNote','Случайные диапазоны · погрешность Монте-Карло · не GTO');renderAdvice(v);}
      else setTimeout(chunk,0);
    }
    setTimeout(chunk,0);
  }
  function renderAdvice(v){
    const box=el('advice');box.className='insight';
    const p=v.pot, c=v.call;
    const validPot=Number.isFinite(p)&&p>=0, validCall=Number.isFinite(c)&&c>=0;
    const odds=validPot&&validCall&&p+c>0 ? c/(p+c):null;
    setText('odds',odds===null?'—':(odds*100).toFixed(1)+'%');
    let ev=null;
    if(lastEquity!==null&&odds!==null){ev=lastEquity*(p+c)-c;setText('ev',(ev>=0?'+':'')+money(ev));}
    else setText('ev','—');
    if(v.duplicateCards){box.textContent='Повторяются карты — исправь их вручную.';return;}
    if(v.hole.length!==2){box.textContent='Твои карты пока не видны. Сядь за стол или введи карты вручную.';return;}
    if(c===0){box.textContent='Доступен чек: для продолжения не требуется оплачивать ставку. Equity показано относительно случайных рук.';return;}
    if(!validPot || !validCall){box.textContent='Нет достоверной суммы банка/колла. При необходимости введи значения вручную.';return;}
    if(lastEquity===null){box.textContent='Считаю вероятность выигрыша для '+v.opponents+' оппонентов…';return;}
    if(ev>=0){box.classList.add('positive');box.textContent='Equity выше математического порога колла против случайных рук. Это не рекомендация GTO: реальный диапазон ставки соперника может быть существенно сильнее.';}
    else {box.classList.add('negative');box.textContent='Equity ниже математического порога колла против случайных рук. Оценка не учитывает конкретный диапазон соперника и будущие улицы.';}
  }
  function displayCards(c){const sym=c?c[0]+suitGlyphs[c[1]]:'—';return `<span class="pill ${c&&'hd'.includes(c[1])?'hero':''}">${sym}</span>`;}
  function renderSeats(s){
    if(!showBadges){el('seats').replaceChildren();return;}
    const layer=el('seats');
    // Reusing nodes avoids HUD flicker during repeated board animations.
    const used=new Set();
    s.players.forEach((p,i)=>{
      const key=String(i);used.add(key);
      let node=layer.querySelector('[data-seat="'+key+'"]');
      if(!node){node=document.createElement('div');node.setAttribute('data-seat',key);layer.appendChild(node);}
      node.className='seat'+(p.isMe?' me':'')+(p.folded?' folded':'');
      const rect=p.el.getBoundingClientRect();
      node.style.left=Math.max(65,Math.min(innerWidth-65,rect.left+rect.width/2))+'px';
      let top=rect.bottom+4;
      if(top>innerHeight-63)top=rect.top-43;
      node.style.top=Math.max(3,top)+'px';
      node.textContent='';
      const b=document.createElement('b');b.textContent=p.name+(p.isMe?' ★':'');
      const info=document.createElement('div');info.className='caption';info.textContent=(p.stack==null?'Stack ?':money(p.stack))+(p.bet?' · Bet '+money(p.bet):'')+(p.status?' · '+p.status.slice(0,18):'');
      node.append(b,info);
    });
    layer.querySelectorAll('[data-seat]').forEach(node=>{if(!used.has(node.dataset.seat))node.remove();});
  }

  function sendBridge(raw){
    if (!bridgeEnabled || !/^[a-f0-9]{24}$/.test(pairingCode)) return;
    const now=Date.now();
    if (now-lastBridgeSent<1700) return;
    lastBridgeSent=now;
    const snapshot={
      tableId: location.pathname.split('/games/')[1]?.split('/')[0] || 'unknown',
      street:raw.street, pot:raw.pot, call:raw.call, onTurn:raw.onTurn,
      hole:raw.hole, board:raw.board,
      hero:raw.hero?{name:raw.hero.name, stack:raw.hero.stack}:null,
      players:raw.players.map(p=>({name:p.name,profileId:p.profileId,stack:p.stack,
        bet:p.bet,status:p.status,isMe:p.isMe,folded:p.folded}))
    };
    chrome.runtime.sendMessage({type:'PN_ANALYST_SNAPSHOT',token:pairingCode,snapshot}, reply=>{
      if(destroyed)return;
      const err=chrome.runtime.lastError;
      setText('bridgeStatus',err?'Ошибка расширения: '+err.message:
        reply?.ok?'● Связь с Windows · '+new Date().toLocaleTimeString():
        'Нет связи: '+(reply?.error||'запусти приложение'));
    });
  }

  function update(){
    if(destroyed)return;
    const raw=getState();
    current=getEffective(raw);
    sendBridge(raw);
    const v=current;
    setText('stateText',v.hero?'LIVE · '+v.street+(v.onTurn?' · ТВОЙ ХОД':''):'Стол открыт · Hero не определён');
    el('stateDot').classList.toggle('ok',!!v.hero);
    setText('pot',money(v.pot));setText('call',money(v.call));setText('oppInfo',v.opponents+' · '+v.players.length+' за столом');
    el('cards').innerHTML=`<span class="small subtle">HERO</span>${(v.hole.length?v.hole:['','']).map(displayCards).join('')}<span class="small subtle">BOARD</span>${(v.board.length?v.board:['','','']).map(displayCards).join('')}`;
    if(v.action)setText('stateText',el('stateText').textContent+' · '+v.action.slice(0,45));
    renderSeats(v);
    const before=lastSignature;
    calculateAsync(v);
    if(before===lastSignature)renderAdvice(v);
  }
  function schedule(){if(debounceId)clearTimeout(debounceId);debounceId=setTimeout(update,170);}
  const observer=new MutationObserver(mutations=>{
    // Ignore our own host changes; closed-loop mutations should not trigger scans.
    if(mutations.some(m=>m.target!==host&&!host.contains(m.target)))schedule();
  });
  observer.observe(document.body||document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});
  window.addEventListener('resize',schedule);
  update();
  // Even when PokerNow replaces its entire table tree without observable text, poll gently.
  const pollId=setInterval(()=>{if(!destroyed&&document.getElementById('pnow-rta-extension-root'))schedule();},2500);
})();
