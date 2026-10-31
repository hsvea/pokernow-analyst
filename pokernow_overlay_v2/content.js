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
  let profileCache = {};
  let profileReceived = 0;
  let observedBB = null;
  let previousRaw = null;
  let lastTableChange = Date.now();
  let tableSignature = '';
  let handNotice = '';
  let selectedPlayer = null;
  let bridgeEpoch = 0;
  let diagnosticPreview = null;
  let lastBridgeOK = 0;
  let bridgeMessage = 'Передача выключена';
  let scale = Math.max(.8, Math.min(1.2, Number(settings.scale) || 1));
  let compact = settings.compact !== false;
  let activeView = settings.activeView==='players'?'players':'hand';
  const overlayVersion='15.0.1'; // Version of this loaded script, even after an extension update.
  const handCollector=globalThis.PokerNowHistory.collector();
  const tableRecorder=globalThis.PokerNowTableCapture.recorder(Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
  let captureResult=null;
  let tableCaptureSupported=null;

  const persist = () => {
    try { localStorage.setItem(storageKey, JSON.stringify({ x: settings.x, y: settings.y, notes, showBadges, minimized, scale, compact, activeView })); } catch {};
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
    // PokerNow renders the button as a sibling of the seats, not inside a player.
    const markers=$$('.dealer-button-ctn');
    const dealerSeats=markers.map(e=>e.className.match(/(?:^|\s)dealer-position-(\d+)(?:\s|$)/)?.[1]);
    const dealerSeat=dealerSeats.length===1&&dealerSeats[0]!==undefined?Number(dealerSeats[0]):null;
    return $$('.table-player').map(el=>{
      const link = $('a[href*="/players/"]',el);
      if (!link) return null;
      const name = getText(link);
      if (!name) return null;
      const stackEl = $('.table-player-stack',el) || $('[class*="player-stack"]',el);
      const betEl = $('[class*="bet-value"]',el);
      const statusEl = $('.table-player-status-icon, .table-player-status-message',el);
      const playerCards = readCards(el);
      const profileId = (link.getAttribute('href') || '').split('/players/')[1]?.split(/[/?#]/)[0] || '';
      const seatMatch = [...el.classList].join(' ').match(/(?:^|\s)table-player-(\d+)(?:\s|$)/);
      const seatRaw = el.getAttribute('data-seat') ?? (seatMatch ? seatMatch[1] : null);
      return {el,name,profileId,seat:seatRaw===null?null:Number(seatRaw),
        dealer:markers.length?dealerSeat!==null&&seatRaw!==null&&Number(seatRaw)===dealerSeat:!!$('.dealer-button, .table-player-dealer',el)||el.classList.contains('dealer'),
        waitingNextHand:!!$('.waiting-next-hand',el)||/in next hand/i.test(getText(statusEl)),
        stack:normalizeNumber(getText(stackEl)),bet:normalizeNumber(getText(betEl))||0,
        status:getText(statusEl),isMe:el.classList.contains('you-player'),
        folded:el.classList.contains('fold')||el.classList.contains('folded')||/\bfold\b/i.test(getText(statusEl)),
        cards:playerCards};
    }).filter(Boolean);
  }
  function getState() {
    const players = readPlayers();
    const hero = players.find(x=>x.isMe) || null;
    const board = readCards($('.table-cards')).slice(0,5);
    const hole = hero?.cards || [];
    const variant=getText($('.game-type-ctn .current-type'));
    const holdem=/^(NLH|NLHE|No Limit (?:Texas )?Hold.?em)$/i.test(variant);
    const actions = readCall();
    const blindPoster=players.find(p=>/big blind/i.test(p.status)&&p.bet>0);
    observedBB=null;
    const blindText=getText($('.table-blinds, .blind-value, .blinds'));
    const blindMatch=blindText.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/);
    if(blindPoster) observedBB=blindPoster.bet;
    else if(blindMatch && Number(blindMatch[2])>0) observedBB=Number(blindMatch[2]);
    const pot = readPot();
    const opponents = Math.max(1,players.filter(x=>x!==hero&&!x.folded).length);
    const hand = [hole,...board].map(x=>Array.isArray(x)?x.join(','):x).join('|');
    const duplicateCards = new Set([...hole,...board]).size !== [...hole,...board].length;
    const handId=getText($('.hand-number, .current-hand-number')) || $('.table-container[data-hand-id]')?.getAttribute('data-hand-id') || '';
    const dealer=players.find(p=>p.dealer);
    return {players,hero,hole,board,pot,opponents,...actions,hand,duplicateCards,bb:observedBB,variant,holdem,
      table:location.pathname,handId,dealerKey:dealer?(dealer.profileId||dealer.name):'',
      street: board.length===0?'PREFLOP':board.length===3?'FLOP':board.length===4?'TURN':board.length===5?'RIVER':'РАЗДАЧА'};
  }

  const host = document.createElement('div');
  host.id='pnow-rta-extension-root';
  host.style.cssText='position:fixed;inset:0;z-index:2147483600;pointer-events:none;';
  const root=host.attachShadow({mode:'closed'});
  root.innerHTML=`<style>
    :host{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#e8fbff}
    *{box-sizing:border-box}
    [hidden]{display:none!important}
    #panel{transform-origin:top left;position:fixed;left:calc(100vw - 380px);top:70px;width:348px;max-width:calc(100vw - 16px);min-width:300px;max-height:calc(100vh - 20px);overflow:hidden;display:flex;flex-direction:column;border-radius:16px;border:1px solid rgba(44,217,238,.62);background:linear-gradient(135deg,rgba(14,30,47,.97),rgba(6,12,25,.975));box-shadow:0 12px 50px rgba(0,0,0,.6),0 0 20px rgba(6,208,244,.2);pointer-events:auto;font-size:13px;line-height:1.35}
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
    input,textarea,select{min-width:0;width:100%;padding:7px;border:1px solid #2c5768;background:#061b2c;color:#e6fcff;border-radius:6px;font:inherit}
    input:focus,textarea:focus{outline:1px solid #47cbdc}
    .inputrow{display:grid;grid-template-columns:80px 1fr;gap:7px;align-items:center;margin:7px 0}
    .small{font-size:11px}.subtle{color:#7ba8b5}
    details{margin-top:10px;border-top:1px solid #244454;padding-top:8px}
    details summary{cursor:pointer;color:#a7eaf1;font-weight:700;user-select:none}
    .foot{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:10px;color:#7299ad;font-size:10px}
    #seats{position:fixed;inset:0;pointer-events:none}
    .seat{position:fixed;max-width:145px;min-width:90px;transform:translate(-50%,0);pointer-events:auto;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center;border:1px solid rgba(51,172,199,.68);background:rgba(1,18,31,.88);color:#d5f6fe;padding:4px 8px;border-radius:7px;box-shadow:0 3px 14px #0009;font-size:10px;line-height:1.4;text-shadow:0 1px 1px #000}
    .seat.me{border-color:#ffcc6e;box-shadow:0 0 12px #c48d3380}
    .seat.folded{opacity:.6}
    .seat b{font-size:11px;color:#fff}
    .seat .caption{color:#8bd6e8}
    .decision{border:1px solid #2b6875;border-radius:12px;background:#0b303a;padding:12px;margin-bottom:8px}
    #decisionAction{display:block;font-size:25px;font-weight:800;line-height:1.2;color:#76f0c8;margin:5px 0}
    #decisionContext{color:#a8d3e0;font-size:12px}#decisionReason{font-size:12px;color:#cce5e8}
    #decisionQuality{color:#ffd58b;font-size:11px}#situation{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin:8px 0}
    .fact{border:1px solid #244b59;border-radius:6px;padding:6px;font-size:11px;white-space:pre-line}
    .fact.manual{border-color:#b69149}.fact.missing{border-color:#865d4b;color:#ffd1a4}
    #freshness,#connection{font-size:11px;margin:5px 0;color:#8fc9ce}#freshness.warn{color:#ffd58b}
    #profileDetail{white-space:pre-line;border:1px solid #3c6e7e;border-radius:9px;padding:10px;margin:8px 0;background:#102a3a}
    .seat:focus-visible{outline:2px solid #f4d180}.seat.selected{border-color:#f4d180}
    .seat .sample{color:#ffd58b}#viewControls{display:flex;gap:7px;align-items:center;margin:9px 0}#viewControls select{width:90px}
    .viewTabs{display:flex;gap:6px;margin:10px 0}.viewTabs button{flex:1}.viewTabs [aria-selected="true"]{background:#1a6370;border-color:#69dedb;color:white}
    .statsScroll{overflow:auto;margin:10px 0}#activeStats{border-collapse:collapse;min-width:590px;width:100%;font-size:11px}
    #activeStats th,#activeStats td{text-align:right;border-bottom:1px solid #244b59;padding:7px 5px;white-space:nowrap}
    #activeStats th:first-child,#activeStats td:first-child{text-align:left}#activeStats td button{max-width:125px;overflow:hidden;text-overflow:ellipsis;padding:3px 5px}
    #activeStats tr.selected{background:#16404d}#tableProfileDetail{white-space:pre-line;font-size:12px;border-left:3px solid #3b9baf;padding:8px}
    #tableStatsMessage{font-size:12px;color:#afd4dc;margin:8px 0}.statsHint{font-size:10px;color:#8fb4c2}
    @media(max-width:630px){#panel{width:310px}.metric b{font-size:15px}}
  </style>
  <div id="seats"></div>
  <section id="panel" role="region" aria-label="PokerNow RTA overlay">
    <div id="drag" class="header">
      <div class="brand">♠ PokerNow <em>Analyst</em> <small id="overlayVersion">v${overlayVersion}</small></div>
      <div class="tools"><button class="icon" id="seatsToggle" title="Показать/скрыть панели игроков">♟</button><button class="icon" id="minToggle" title="Свернуть/развернуть">−</button><button class="icon" id="close" title="Закрыть оверлей">×</button></div>
    </div>
    <div id="body">
      <div class="status"><i id="stateDot" class="dot"></i><span id="stateText">Ожидаю данные стола…</span></div>
      <div id="connection" role="status">Windows · передача выключена</div>
      <div id="captureStatus" class="small" role="status"></div>
      <div class="small subtle">Сбор со стола работает без журнала. Полные истории — дополнительно из открытого LOG или CSV.</div>
      <div id="freshness"></div>
      <div class="viewTabs" role="tablist" aria-label="Раздел оверлея"><button id="handTab" role="tab" aria-controls="handView" aria-selected="true">Раздача</button><button id="playersTab" role="tab" aria-controls="tablePlayersView" aria-selected="false">Игроки</button></div>
      <div id="handView" role="tabpanel" aria-labelledby="handTab">
      <div class="strip" id="cards"></div>
      <details id="historySection"><summary id="historyToggle">История действий · префлоп</summary>
        <div id="historyStatus" class="muted" style="margin:8px 0">Открой LOG / LEDGER</div>
        <div id="historySummary" class="small"></div>
        <ol id="historyEvents" class="small" style="padding-left:20px;max-height:180px;overflow:auto"></ol>
        <div class="muted">Читается только открытый Session Log. Архивная раздача и неполные данные не используются для автоподсказки.</div>
      </details>
      <section id="preflopPanel">
        <div class="decision" id="preflopAdvice" aria-live="polite">
          <div id="decisionContext">PREFLOP</div><strong id="decisionAction">Ожидание карт</strong>
          <div id="decisionReason"></div><div id="decisionQuality">Эвристика · не GTO</div>
        </div>
        <div id="situation" aria-label="Распознанная ситуация"></div>
        <details><summary>Параметры префлопа / ручная поправка</summary>
          <div class="inputrow"><label for="pfBB">BB</label><input id="pfBB" type="number" min="0" step="any" placeholder="Укажи большой блайнд" /></div>
          <div class="inputrow"><label for="pfPlayers">Игроков</label><input id="pfPlayers" type="number" min="2" max="10" placeholder="Авто" /></div>
          <div class="inputrow"><label for="pfPosition">Позиция</label><select id="pfPosition"><option value="">Авто, если распознана</option>${['UTG','UTG+1','UTG+2','MP','LJ','HJ','CO','BTN','SB','BB'].map(p=>`<option>${p}</option>`).join('')}</select></div>
          <div class="inputrow"><label for="pfScenario">До тебя</label><select id="pfScenario"><option value="">Авто / неизвестно</option><option value="unopened">Без повышений</option><option value="limped">Лимперы</option><option value="raise">Рейз</option><option value="3bet">3-бет</option><option value="4bet">4-бет</option></select></div>
          <div class="inputrow"><label for="pfLimpers">Лимперов</label><input id="pfLimpers" type="number" min="0" max="9" placeholder="Авто" /></div>
          <div class="inputrow"><label for="pfStack">Эфф. стек*</label><input id="pfStack" type="number" min="0" step="any" placeholder="Авто" /></div>
          <div class="inputrow"><label for="pfFacing">Ставка до</label><input id="pfFacing" type="number" min="0" step="any" placeholder="Авто" /></div>
          <div class="inputrow"><label for="pfOwn">Уже внесено</label><input id="pfOwn" type="number" min="0" step="any" placeholder="Авто" /></div>
          <button id="pfReset">Сбросить ситуацию</button>
          <div class="muted">* Остаток эффективного стека. Историю рейзов нельзя надёжно восстановить по одной сумме: при повышении выбери её вручную. Проверяй BB и позицию. Эвристика, не GTO.</div>
        </details>
      </section>
      <div id="equitySummary" class="small" role="status"></div>
      <div class="small subtle">Equity — доля банка против случайных рук, не точный шанс против диапазона соперника. Порог колла — цена колла / итоговый банк.</div>
      <div id="viewControls"><button id="compactToggle">Подробнее</button><label for="scaleSelect">Масштаб</label><select id="scaleSelect"><option value="0.8">80%</option><option value="1">100%</option><option value="1.2">120%</option></select><button id="positionReset" title="Вернуть панель в окно">↺</button></div>
      <div id="profileDetail" hidden></div>
      <div id="analytics">
      <div class="grid">
        <div class="metric"><small>Банк</small><b id="pot">—</b></div>
        <div class="metric"><small>Нужно коллировать</small><b id="call">—</b></div>
        <div class="metric"><small>Pot Odds</small><b id="odds">—</b></div>
      </div>
      <div class="equity"><div class="equityHead"><div><div class="muted">Equity vs случайные руки</div><strong id="equity">—</strong></div><div class="muted" id="equityMeta">Нет карт</div></div><div class="bar"><i id="equityBar"></i></div><div class="muted" id="equityNote">Monte Carlo · открытые карты, без чтения скрытых рук</div></div>
      <div class="insight" id="advice">Ожидаю данные…</div>
      <div class="row"><label>Оппонентов в симуляции</label><span id="oppInfo">—</span></div>
      <div class="row"><label>Расчётный EV колла*</label><strong id="ev">—</strong></div>
      </div>
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
      <details id="diagnosticSection"><summary>Ошибка распознавания</summary>
        <p class="muted">Подготовить обезличенный снимок. Ники, ID, URL стола, карты, заметки и код сопряжения исключены. Ничего не отправляется автоматически.</p>
        <button id="diagnosticPrepare">Предпросмотр диагностики</button>
        <textarea id="diagnosticPreview" readonly rows="7" hidden aria-label="Предпросмотр диагностики"></textarea>
        <button id="diagnosticSave" hidden>Сохранить этот JSON</button>
      </details>
      <details><summary>Заметки за столом</summary><textarea id="notes" rows="3" maxlength="4000" placeholder="Заметки (сохраняются только в этом браузере)"></textarea></details>
      </div>
      <section id="tablePlayersView" role="tabpanel" aria-labelledby="playersTab" hidden>
        <div id="tableStatsMessage" role="status">Ожидание стола</div>
        <label class="inputrow">Источник <select id="statsSource"><option value="live">Со стола</option><option value="complete">Полные руки (LOG / CSV)</option></select></label>
        <div class="statsHint" id="statsBasis"></div>
        <label class="row"><span>Только в раздаче*</span><input id="playersInHand" type="checkbox" style="width:auto" /></label>
        <div class="inputrow"><label for="playersSort">Сортировка</label><select id="playersSort"><option value="seat">За столом</option><option value="hands">Число рук</option><option value="vpip">VPIP</option><option value="name">Ник</option></select></div>
        <div class="statsScroll"><table id="activeStats"><thead><tr><th scope="col">Игрок</th><th scope="col">Рук</th><th scope="col">VPIP</th><th scope="col">PFR</th><th scope="col">3-bet</th><th scope="col">F/3-bet</th><th scope="col">AF</th><th scope="col">Статус</th></tr></thead><tbody id="activeStatsBody"></tbody></table></div>
        <div class="statsHint">Прокрути таблицу вправо для остальных показателей. «—» — нет данных или возможностей. Менее 50 рук: малая выборка; большее число не гарантирует надёжности. * По видимому статусу, без проверки полной истории.</div>
        <div id="tableProfileDetail" hidden></div>
      </section>
      <div class="foot"><span>* EV по случайным рукам, без рейка и фолд-эквити; не GTO</span><span>Alt+R — панель</span></div>
    </div>
  </section>`;
  document.documentElement.appendChild(host);
  const el = id => root.getElementById(id);
  const panel = el('panel');
  function applyTab(){
    const players=activeView==='players';panel.style.width=players?'650px':'';if(current)clampPanel();el('handView').hidden=players;el('tablePlayersView').hidden=!players;
    el('handTab').setAttribute('aria-selected',String(!players));el('playersTab').setAttribute('aria-selected',String(players));persist();
  }
  el('handTab').onclick=()=>{activeView='hand';applyTab();};
  el('playersTab').onclick=()=>{activeView='players';applyTab();renderTablePlayers();};
  for(const id of ['handTab','playersTab'])el(id).onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();activeView=event.key==='Home'?'hand':event.key==='End'?'players':activeView==='hand'?'players':'hand';applyTab();el(activeView==='hand'?'handTab':'playersTab').focus();
  };
  el('playersInHand').onchange=renderTablePlayers;el('playersSort').onchange=renderTablePlayers;
  el('statsSource').onchange=()=>{el('playersSort').value='seat';renderTablePlayers();};
  applyTab();
  el('diagnosticPrepare').onclick=()=>{
    diagnosticPreview=JSON.stringify(globalThis.PokerNowHistory.diagnostic(current||{},current?.history||{}),null,2);
    el('diagnosticPreview').value=diagnosticPreview;el('diagnosticPreview').hidden=false;el('diagnosticSave').hidden=false;
  };
  el('diagnosticSave').onclick=()=>{
    if(!diagnosticPreview)return;
    const url=URL.createObjectURL(new Blob([diagnosticPreview],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='PokerNow-diagnostic-v14.json';root.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const setText = (id, v) => { el(id).textContent = String(v); };
  const pfOverrides=['pfPlayers','pfPosition','pfScenario','pfLimpers','pfStack','pfFacing','pfOwn'];
  ['pfBB',...pfOverrides].forEach(id=>el(id).addEventListener('input',()=>update()));
  el('pfReset').onclick=()=>{resetHand('Ситуация сброшена вручную');update();};
  if (Number.isFinite(settings.x) && Number.isFinite(settings.y)) {
    panel.style.left=Math.max(0,Math.min(innerWidth-120,settings.x))+'px';
    panel.style.top=Math.max(0,Math.min(innerHeight-55,settings.y))+'px';
  }
  function clampPanel(){
    const rect=panel.getBoundingClientRect();
    settings.x=Math.max(0,Math.min(innerWidth-rect.width,rect.left));
    settings.y=Math.max(0,Math.min(innerHeight-Math.min(rect.height,80*scale),rect.top));
    panel.style.left=settings.x+'px';panel.style.top=settings.y+'px';
    panel.style.maxHeight=Math.max(120,(innerHeight-settings.y-8)/scale)+'px';
  }
  function applyView(){
    panel.style.transform=`scale(${scale})`;
    panel.style.maxWidth=Math.max(200,(innerWidth-16)/scale)+'px';
    panel.style.minWidth='0';
    el('analytics').hidden=compact;
    el('compactToggle').textContent=compact?'Подробнее':'Компактно';
    el('scaleSelect').value=String(scale);
    clampPanel();persist();
  }
  el('compactToggle').onclick=()=>{compact=!compact;applyView();};
  el('scaleSelect').onchange=()=>{scale=Number(el('scaleSelect').value);applyView();};
  el('positionReset').onclick=()=>{panel.style.left='16px';panel.style.top='60px';applyView();};
  applyView();
  function applyMin(){el('body').hidden=minimized;el('minToggle').textContent=minimized?'+':'−';persist();}
  applyMin();
  el('close').onclick=()=>{destroyed=true;observer.disconnect();clearTimeout(debounceId);clearInterval(pollId);window.removeEventListener('resize', onResize);document.removeEventListener('visibilitychange', onVisibility);window.removeEventListener('keydown', hotkey);host.remove();};
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
    bridgeEpoch++;profileCache={};lastBridgeOK=0;
    chrome.storage.local.set({pairingCode,bridgeEnabled});
  };
  el('bridgeEnable').onchange=()=>{
    pairingCode=el('pairInput').value.trim().toLowerCase();
    if (!/^[a-f0-9]{24}$/.test(pairingCode)){
      bridgeEnabled=false;el('bridgeEnable').checked=false;
      setText('bridgeStatus','Нужен корректный 24-символьный код из Windows-приложения');return;
    }
    bridgeEpoch++;profileCache={};lastBridgeOK=0;
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
    settings.x=Math.min(Math.max(0,innerWidth-panel.getBoundingClientRect().width),Math.max(0,drag.left+ev.clientX-drag.x));
    settings.y=Math.min(innerHeight-40,Math.max(0,drag.top+ev.clientY-drag.y));
    panel.style.left=settings.x+'px';panel.style.top=settings.y+'px';clampPanel();
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
    if(v.paused){simToken++;lastEquity=null;lastSignature='';setText('equity','—');el('equityBar').style.width='0%';setText('equityMeta','Пауза');renderAdvice(v);return;}
    const signature=[v.hole.join(','),v.board.join(','),v.opponents].join('|');
    if(signature===lastSignature && lastEquity!==null)return;
    lastSignature=signature;lastEquity=null;trialsRun=0;
    const token=++simToken;
    if(v.hole.length!==2||![0,3,4,5].includes(v.board.length)||v.duplicateCards){setText('equity','—');el('equityBar').style.width='0%';setText('equityMeta','Нужны карты');setText('equityNote',v.duplicateCards?'Ошибка: повторяющиеся карты':'Ожидание двух карт Hero и корректного борда');renderAdvice(v);return;}
    const used=new Set([...v.hole,...v.board]);const remaining=allCards.filter(c=>!used.has(c));
    const needed=(5-v.board.length)+2*v.opponents;
    if(remaining.length<needed){setText('equity','—');setText('equityMeta','Ошибка колоды');return;}
    setText('equity','…');setText('equityMeta','Расчёт');el('equityBar').style.width='0%';renderAdvice(v);
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
      if(trialsRun>=total){lastEquity=score/total;setText('equity','≈ '+(lastEquity*100).toFixed(1)+'%');el('equityBar').style.width=(lastEquity*100).toFixed(1)+'%';setText('equityMeta',total+' сим.');setText('equityNote','Случайные диапазоны · погрешность Монте-Карло · не GTO');renderAdvice(current||v);}
      else setTimeout(chunk,0);
    }
    setTimeout(chunk,0);
  }
  function renderAdvice(v){
    const box=el('advice');box.className='insight';
    const p=v.pot, c=v.call;
    const validPot=Number.isFinite(p)&&p>=0, validCall=Number.isFinite(c)&&c>=0;
    const odds=validPot&&validCall&&p+c>0 ? c/(p+c):null;
    setText('equitySummary',v.paused?'Equity: — · '+v.paused:v.duplicateCards||v.hole.length!==2?'Equity: — · нужны две корректные карты':'Equity: '+(lastEquity===null?'считаю…':(lastEquity*100).toFixed(1)+'%')+' · '+(c===0?'чек без доплаты':'порог колла: '+(odds===null?'—':(odds*100).toFixed(1)+'%')));
    setText('odds',odds===null?'—':(odds*100).toFixed(1)+'%');
    let ev=null;
    if(lastEquity!==null&&odds!==null){ev=lastEquity*(p+c)-c;setText('ev',(ev>=0?'+':'')+money(ev));}
    else setText('ev','—');
    if(v.paused){box.textContent=v.paused;setText('ev','—');return;}
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
      const key=p.profileId?'p:'+p.profileId:'n:'+p.name.toLowerCase();used.add(key);
      let node=[...layer.children].find(n=>n.dataset.seat===key);
      if(!node){node=document.createElement('button');node.type='button';node.setAttribute('data-seat',key);layer.appendChild(node);node.onclick=()=>{selectedPlayer=selectedPlayer===key?null:key;if(selectedPlayer && minimized){minimized=false;applyMin();}renderProfile();};}
      node.setAttribute('aria-label','Профиль: '+p.name);
      node.className='seat'+(selectedPlayer===key?' selected':'')+(p.isMe?' me':'')+(p.folded?' folded':'');
      const rect=p.el.getBoundingClientRect();
      node.style.left=Math.max(65,Math.min(innerWidth-65,rect.left+rect.width/2))+'px';
      let top=rect.bottom+4;
      if(top>innerHeight-63)top=rect.top-43;
      node.style.top=Math.max(3,top)+'px';
      node.textContent='';
      const b=document.createElement('b');b.textContent=p.name+(p.isMe?' ★':'');
      const info=document.createElement('div');info.className='caption';info.textContent=(p.stack==null?'Stack ?':money(p.stack))+(p.bet?' · Bet '+money(p.bet):'')+(p.status?' · '+p.status.slice(0,18):'');
      node.append(b,info);
      const profile=profileCache[p.profileId?'p:'+p.profileId:'n:'+p.name.toLowerCase()];
      if(profile && bridgeEnabled && Date.now()-profileReceived<8000){
        const stats=document.createElement('div');
        stats.textContent=profile.hands?`VPIP ${profile.vpip}% · PFR ${profile.pfr}% · ${profile.hands} рук`:'Нет импортированных раздач';
        node.append(stats);
        if(profile.hands<50){const sample=document.createElement('div');sample.className='sample';sample.textContent='Малая выборка';node.append(sample);}
      }
    });
    layer.querySelectorAll('[data-seat]').forEach(node=>{if(!used.has(node.dataset.seat))node.remove();});
  }

  function renderProfile(){
    const box=el('profileDetail');
    const player=current?.players.find(p=>(p.profileId?'p:'+p.profileId:'n:'+p.name.toLowerCase())===selectedPlayer);
    box.hidden=!player;
    el('tableProfileDetail').hidden=!player;
    if(!player){selectedPlayer=null;return;}
    const profile=bridgeEnabled && Date.now()-profileReceived<8000?profileCache[selectedPlayer]:null;
    box.textContent=player.name+' · '+(player.profileId?'PokerNow ID':'Только ник — личность не подтверждена')+'\n'+
      (profile?`${profile.hands} рук${profile.hands<50?' · малая выборка':''}\nРанее: ${(profile.aliases||[]).filter(n=>n!==player.name).join(', ')||'—'}\nЗаметка: ${profile.note||'—'}\nИзменить заметку можно в Windows-приложении.`:'Нет свежей связи с профилем в Windows-приложении.');
    if(profile){const op=profile.opportunities||{};box.textContent+='\nВозможностей 3-bet: '+(op.threebet||0)+' · против 3-bet: '+(op.f3bet||0)+' · postflop-коллов для AF: '+(op.post_call||0);}
    el('tableProfileDetail').textContent=box.textContent;
    if(profile?.live){const l=profile.live;const detail='\nСо стола: '+l.seen+' частичных наблюдений рук · '+l.actions+' действий\nCall '+l.call+' · Raise '+l.raise+' · Bet '+l.bet+' · Check '+l.check+' · Fold '+l.fold+' · изменений ставки без распознанного действия: '+l.chips;box.textContent+=detail;el('tableProfileDetail').textContent+=detail;}
  }
  function renderTablePlayers(){
    if(!current)return;
    const fresh=bridgeEnabled && lastBridgeOK>0 && Date.now()-profileReceived<8000;
    const liveMode=el('statsSource').value==='live';
    const headers=liveMode?['Игрок','Руки*','Действий','Call','Raise','Bet','Check','Fold']:['Игрок','Рук','VPIP','PFR','3-bet','F/3-bet','AF','Статус'];
    root.querySelectorAll('#activeStats th').forEach((th,i)=>th.textContent=headers[i]);
    setText('statsBasis',liveMode?'Наблюдения со стола, без LOG. Руки* — частичные наблюдения, не полные истории; перезагрузка страницы может разделить одну руку. Действия могут быть пропущены. По всем сохранённым столам; типы игр не разделены.':'Полные сохранённые руки из LOG / CSV. VPIP/PFR не вычисляются из неполных наблюдений. Типы игр не разделены.');
    const all=current.players||[], seen=new Set();
    let players=all.filter(p=>{const key=p.profileId?'p:'+p.profileId:'n:'+p.name.toLowerCase();if(seen.has(key))return false;seen.add(key);return true;});
    if(el('playersInHand').checked)players=players.filter(p=>!p.folded&&!/away|offline|in next hand|sitting out/i.test(p.status||''));
    const profile=p=>fresh?profileCache[p.profileId?'p:'+p.profileId:'n:'+p.name.toLowerCase()]:null;
    const sort=el('playersSort').value;
    if(sort==='name')players.sort((a,b)=>a.name.localeCompare(b.name));
    else if(sort==='hands'||sort==='vpip')players.sort((a,b)=>(profile(b)?.[sort]??-1)-(profile(a)?.[sort]??-1));
    setText('tableStatsMessage',players.length+' за столом'+(fresh?' · статистика из Windows':bridgeEnabled?' · нет свежего ответа Windows':' · включи передачу данных для статистики'));
    const body=el('activeStatsBody'),used=new Set();
    const pct=v=>v==null?'—':v+'%';
    let rowIndex=0;
    for(const p of players){
      const key=p.profileId?'p:'+p.profileId:'n:'+p.name.toLowerCase();used.add(key);
      let row=[...body.children].find(n=>n.dataset.player===key);
      if(!row){row=document.createElement('tr');row.dataset.player=key;for(let i=0;i<8;i++)row.appendChild(document.createElement('td'));
        const button=document.createElement('button');button.onclick=()=>{selectedPlayer=key;renderProfile();renderTablePlayers();};row.children[0].append(button);body.append(row);}
      const st=profile(p),h=st?.hands;
      row.classList.toggle('selected',selectedPlayer===key);
      row.children[0].firstChild.textContent=p.name+(p.isMe?' ★':'');row.children[0].firstChild.title=p.name+' · открыть профиль';
      const l=st?.live;
      const values=liveMode?['seen','actions','call','raise','bet','check','fold'].map(k=>l?.[k]??'—'):[h==null?'—':h+(h<50?' ⚠':''),pct(st?.vpip),pct(st?.pfr),pct(st?.threebet),pct(st?.f3bet),st?.af??'—',p.status||(p.folded?'Fold':'За столом')];
      values.forEach((v,i)=>row.children[i+1].textContent=String(v));
      row.children[1].title=h==null?'Нет связи со статистикой':h===0?'Нет сохранённых рук':h<50?'Малая выборка':'Количество сохранённых рук';
      row.children[4].title='Возможностей 3-bet: '+(st?.opportunities?.threebet??'—');row.children[5].title='Возможностей против 3-bet: '+(st?.opportunities?.f3bet??'—');
      if(liveMode){row.children[1].title='Частичные наблюдения рук, не полные истории';row.children[4].title='Замеченные Raise';row.children[5].title='Замеченные Bet';}
      if(body.children[rowIndex]!==row)body.insertBefore(row,body.children[rowIndex]||null);
      rowIndex++;
    }
    [...body.children].forEach(row=>{if(!used.has(row.dataset.player))row.remove();});
    if(selectedPlayer&&!used.has(selectedPlayer)){el('tableProfileDetail').hidden=true;}
  }
  function renderCapture(){
    const source=current?.logSource;
    const state=!bridgeEnabled?'включи передачу в Windows':tableCaptureSupported===false?'обнови Windows-приложение до v15':document.hidden?'пауза: вкладка скрыта':!lastBridgeOK||Date.now()-lastBridgeOK>=8000?'нет связи с Windows · очередь сохраняется до закрытия страницы':'со стола · работает без LOG';
    setText('captureStatus','Сбор: '+state+' · очередь действий '+tableRecorder.size()+' · полных рук '+handCollector.size()+(captureResult?' · #'+(captureResult.number||'')+' '+captureResult.reason:'')+(tableRecorder.warning()?' · '+tableRecorder.warning():'')+(handCollector.warning()?' · '+handCollector.warning():''));
  }
  function sendBridge(raw){
    if (!bridgeEnabled || !/^[a-f0-9]{24}$/.test(pairingCode)) return;
    const now=Date.now();
    if (now-lastBridgeSent<1700) return;
    lastBridgeSent=now;
    const epoch=bridgeEpoch, table=raw.table;
    const snapshot={
      tableId: location.pathname.split('/games/')[1]?.split('/')[0] || 'unknown',
      street:raw.street, pot:raw.pot, call:raw.call, onTurn:raw.onTurn,
      hole:raw.hole, board:raw.board,
      hero:raw.hero?{name:raw.hero.name, stack:raw.hero.stack}:null,
      capturedHand:handCollector.next(),
      tableEvents:tableRecorder.batch(),
      players:raw.players.map(p=>({name:p.name,profileId:p.profileId,stack:p.stack,
        bet:p.bet,status:p.status,isMe:p.isMe,folded:p.folded}))
    };
    chrome.runtime.sendMessage({type:'PN_ANALYST_SNAPSHOT',token:pairingCode,snapshot}, reply=>{
      if(destroyed||epoch!==bridgeEpoch||table!==location.pathname)return;
      const err=chrome.runtime.lastError;
      if(reply?.ok){profileCache=reply.profiles||{};profileReceived=Date.now();lastBridgeOK=Date.now();}
      else {profileCache={};lastBridgeOK=0;}
      if(reply?.extensionReloaded){bridgeEnabled=false;setText('bridgeStatus','Расширение обновлено. Обнови вкладку стола, чтобы загрузить новую версию.');return;}
      if(reply?.ok && reply.capture){captureResult=reply.capture;handCollector.ack(String(reply.capture.number));}
      if(reply?.ok && Array.isArray(reply.tableAck))tableRecorder.ack(reply.tableAck);
      if(reply?.ok)tableCaptureSupported=Array.isArray(reply.tableAck);
      if(reply?.ok && snapshot.capturedHand && reply.capture===undefined)captureResult={reason:'Обнови Windows-приложение для сохранения рук'};
      bridgeMessage=err?'Ошибка расширения: '+err.message:
        reply?.ok?'● Связь с Windows · '+new Date().toLocaleTimeString():
        'Нет связи: '+(reply?.error||'запусти приложение');
      setText('bridgeStatus',bridgeMessage);renderConnection();renderProfile();renderTablePlayers();renderCapture();
    });
  }

  function resetHand(reason){
    pfOverrides.forEach(id=>el(id).value='');el('pfBB').value='';
    ['holeInput','boardInput','potInput','callInput','oppInput'].forEach(id=>el(id).value='');
    manualEnabled=false;el('manualEnable').checked=false;
    simToken++;lastSignature='';lastEquity=null;trialsRun=0;
    handNotice=reason;selectedPlayer=null;
  }
  function trackHand(raw){
    const old=previousRaw;
    if(old){
      const tableChanged=raw.table!==old.table;
      const nextHand=tableChanged || (raw.handId && old.handId && raw.handId!==old.handId)
        || (old.board.length>0 && raw.board.length===0)
        || (old.hole.join(',')!==raw.hole.join(','))
        || (raw.dealerKey && old.dealerKey && raw.dealerKey!==old.dealerKey)
        || (old.hero?.profileId!==raw.hero?.profileId);
      if(nextHand)resetHand(tableChanged?'Другой стол · ручные данные сброшены':'Смена раздачи/карт · ручные данные сброшены');
      if(tableChanged){bridgeEpoch++;profileCache={};lastBridgeOK=0;lastBridgeSent=0;}
    }
    previousRaw=raw;
    const signature=JSON.stringify([raw.table,raw.handId,raw.hole,raw.board,raw.pot,raw.call,raw.onTurn,raw.players.map(p=>[p.profileId,p.name,p.bet,p.stack,p.status,p.dealer,p.folded])]);
    if(signature!==tableSignature){tableSignature=signature;lastTableChange=Date.now();}
    raw.paused=!raw.holdem || raw.hole.length>2?'Тип игры '+(raw.variant||'не определён')+' · подсказки и equity доступны только для NL Hold’em':document.hidden?'Вкладка скрыта · подсказки приостановлены':Date.now()-lastTableChange>90000?'Стол не менялся более 90 секунд · проверь соединение PokerNow':!raw.hero?'Hero не определён':raw.hero.folded?'Hero уже сбросил карты':'';
  }
  function renderConnection(){
    setText('connection',!bridgeEnabled?'Windows · передача выключена':lastBridgeOK && Date.now()-lastBridgeOK<8000?'Windows · подключено':'Windows · нет свежего ответа');
  }
  function renderPreflop(v){
    el('preflopPanel').hidden=v.board.length!==0;
    if(v.board.length)return;
    const pf=globalThis.PokerNowPreflop;
    const value=(id,auto)=>el(id).value.trim()===''?auto:Number(el(id).value);
    const history=v.history?.usable?v.history:null;
    const hero=v.hero, bb=value('pfBB',history?.bb??v.bb), count=value('pfPlayers',v.players.filter(p=>!p.waitingNextHand).length);
    const position=el('pfPosition').value||pf.inferPosition(v.players,hero);
    const own=value('pfOwn',history?.heroBet??hero?.bet??0);
    const active=v.players.filter(p=>!p.isMe&&!p.folded);
    const facing=value('pfFacing',history?.facing??(bb?Math.max(bb,...v.players.map(p=>p.bet||0)):null));
    const totals=active.filter(p=>p.stack!==null).map(p=>p.stack+p.bet);
    const autoStack=hero?.stack==null?null:Math.min(hero.stack,Math.max(0,(totals.length?Math.max(...totals):hero.stack+own)-own));
    const stack=value('pfStack',autoStack);
    const bigBlind=v.players.find(p=>/big blind/i.test(p.status)||pf.inferPosition(v.players,p)==='BB');
    const limpers=value('pfLimpers',history?.limpers??(bigBlind&&bb?v.players.filter(p=>!p.isMe&&!p.folded&&p!==bigBlind&&p.bet===bb).length:null));
    let scenario=el('pfScenario').value||history?.scenario;
    if(!scenario && !v.logSource?.rows.length && bb && facing<=bb)scenario=pf.unraisedSituation(v.players,hero,bb)?.scenario;
    const labels={unopened:'Без рейза',limped:'Лимперы',raise:'Рейз','3bet':'3-бет','4bet':'4-бет'};
    const facts=[['BB',bb,'pfBB'],['Позиция',position,'pfPosition'],['Игроков',count,'pfPlayers'],['Эфф. остаток',stack,'pfStack'],['Ставка до',facing,'pfFacing'],['Уже внесено',own,'pfOwn'],['До тебя',labels[scenario]||null,'pfScenario'],['Лимперов',history?limpers:scenario==='unopened'?0:scenario==='limped'?limpers:null,'pfLimpers']];
    const container=el('situation');container.replaceChildren();
    for(const [label,val,id] of facts){
      const fact=document.createElement('div'), manual=el(id).value!=='';
      const fromHistory=history&&['pfBB','pfOwn','pfFacing','pfLimpers','pfScenario'].includes(id);
      fact.className='fact'+(val==null?' missing':manual?' manual':'');
      fact.textContent=label+': '+(val??'неизвестно')+'\n'+(manual?'вручную':val==null?'нужно уточнить':id==='pfPosition'?'по фишке дилера':fromHistory?'из журнала · сверено':'из видимого стола');
      container.append(fact);
    }
    setText('decisionContext',[v.hole.join(' '),position||'позиция ?',bb&&stack!=null?(stack/bb).toFixed(1)+' BB остаток':'стек ?'].join(' · '));
    setText('decisionQuality','Эвристика · не GTO · '+(facts.some(f=>el(f[2]).value!=='')?'есть ручные поправки':'видимые данные'));
    try{
      if(v.paused)throw new Error(v.paused);
      if(history && !v.onTurn && !el('pfScenario').value)throw new Error('История прочитана · жду хода Hero');
      if(v.duplicateCards)throw new Error('Повторяются карты — проверь распознавание');
      if(!bb || bb<=0)throw new Error('Укажи BB в параметрах префлопа');
      if(scenario==='limped' && limpers===null)throw new Error('Укажи число лимперов');
      if(stack==null)throw new Error('Укажи эффективный остаток стека');
      if(!scenario)throw new Error(facing>bb?'Виден рейз, но число повышений неизвестно. Выбери «Рейз / 3-бет / 4-бет» в параметрах или открой LOG.':'Не удалось подтвердить блайнды и предыдущие действия. Проверь позицию BB и ставки.');
      const r=pf.recommend({cards:v.hole,players:count,position,bb,stack,totalBet:facing,heroBet:own,scenario,limpers:scenario==='limped'?limpers:0,minRaiseTo:history && ['pfBB','pfFacing','pfScenario','pfOwn'].every(id=>el(id).value==='')?history.minRaiseTo:undefined});
      setText('decisionAction',r.action+(r.target!==null?' до '+money(r.target):r.action==='CALL'?' '+money(r.call):''));
      setText('decisionReason',r.reason);
    }catch(err){setText('decisionAction','Нужно уточнить');setText('decisionReason',err.message+' · параметры ниже');}
  }

  function renderHistory(v){
    const h=v.history;
    setText('historyToggle',h?.usable?'История · начало видно, сверено':h?.status==='postflop'?'История · постфлоп':'История · нужна проверка');
    setText('historyStatus',h?.reason||'Открой LOG / LEDGER');
    setText('historySummary',h?.usable?'Повышений: '+h.raises+' · лимперов: '+h.limpers+' · колл: '+money(h.call)+(h.opener?' · открылся: '+h.opener.name+' ('+(globalThis.PokerNowPreflop.inferPosition(v.players,v.players.find(p=>p.profileId===h.opener.profileId))||'позиция ?')+')':''):'');
    const list=el('historyEvents');list.replaceChildren();
    const labels={sb:'малый блайнд',bb:'большой блайнд',raise:'рейз до',call:'колл до',check:'чек',fold:'фолд',street:'улица',unknown:'неизвестный формат',end:'конец раздачи'};
    for(const event of (h?.events||[]).filter(e=>!['stacks','admin'].includes(e.type)).slice(-30)){
      const item=document.createElement('li');item.textContent=(event.name?event.name+' · ':'')+(labels[event.type]||event.type)+(event.amount!=null?' '+money(event.amount):'')+(event.street?' '+event.street:'');list.append(item);
    }
  }
  function update(){
    if(destroyed)return;
    const raw=getState();
    raw.logSource=globalThis.PokerNowHistory.extract(document);
    if(current && current.table!==raw.table)captureResult=null;
    handCollector.observe(raw.logSource,raw.table);
    raw.history=globalThis.PokerNowHistory.analyze(raw.logSource,raw);
    if(!raw.handId && raw.logSource.current)raw.handId=raw.history.handId||'';
    trackHand(raw);
    if(bridgeEnabled&&!document.hidden)tableRecorder.observe(raw);else tableRecorder.pause();
    current=getEffective(raw);
    sendBridge(raw);
    const v=current;
    renderPreflop(v);renderHistory(v);
    renderConnection();renderProfile();renderTablePlayers();renderCapture();
    setText('freshness',v.paused||handNotice||'Данные из видимого стола · проверяй ситуацию');
    el('freshness').classList.toggle('warn',!!v.paused);
    setText('stateText',v.paused?'ПАУЗА · '+v.street:v.hero?'LIVE · '+v.street+(v.onTurn?' · ТВОЙ ХОД':''):'Стол открыт · Hero не определён');
    el('stateDot').classList.toggle('ok',!!v.hero&&!v.paused);
    setText('pot',money(v.pot));setText('call',money(v.call));setText('oppInfo',v.opponents+' · '+v.players.length+' за столом');
    const autoPosition=globalThis.PokerNowPreflop.inferPosition(v.players,v.hero);
    el('cards').innerHTML=`<span class="small subtle" title="Позиция по фишке дилера">HERO · ${autoPosition||'позиция ?'}</span>${(v.hole.length?v.hole:['','']).map(displayCards).join('')}<span class="small subtle">BOARD</span>${(v.board.length?v.board:['','','']).map(displayCards).join('')}`;
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
  observer.observe(document.body||document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','data-hand-id']});
  function onResize(){clampPanel();persist();schedule();}
  function onVisibility(){simToken++;lastSignature='';lastEquity=null;update();}
  window.addEventListener('resize',onResize);
  document.addEventListener('visibilitychange',onVisibility);
  update();
  // Even when PokerNow replaces its entire table tree without observable text, poll gently.
  const pollId=setInterval(()=>{if(!destroyed&&document.getElementById('pnow-rta-extension-root'))schedule();},2500);
})();
