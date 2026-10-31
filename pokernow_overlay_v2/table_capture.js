/* Observed table actions, deliberately separate from complete hand histories. */
(function(root){
'use strict';
function recorder(session){
 let previous=null,hand=0,seq=0,warning='',boundTable=null;const pending=new Map();
 const action=p=>{const m=(p.status||'').trim().match(/^(call|raise|bet|check|fold)(?:s|ed)?\b/i);return m?m[1].toLowerCase():p.folded?'fold':null;};
 function push(p,kind,state){
  if(pending.size>=500){warning='Очередь заполнена: часть наблюдений пропущена';return;}
  const id=session+':'+(++seq);
  pending.set(id,{id,hand:session+':h'+hand,profileId:p.profileId||'',name:p.name,kind,street:state.street,bet:Number.isFinite(p.bet)?p.bet:0});
 }
 return {
  observe(state){
   if(boundTable!==null&&boundTable!==state.table){pending.clear();previous=null;warning='';}
   boundTable=state.table;
   const changed=!previous || previous.table!==state.table || (state.dealerKey&&previous.dealerKey&&state.dealerKey!==previous.dealerKey) || (previous.board.length>0&&state.board.length===0) || (state.handId&&previous.handId&&state.handId!==previous.handId);
   if(previous&&previous.table!==state.table){pending.clear();warning='';}
   if(changed)hand++;
   const old=new Map((previous?.players||[]).map(p=>[p.profileId||p.name,p]));
   for(const p of state.players){
    const before=old.get(p.profileId||p.name);
    if(changed||!before){if(!p.waitingNextHand)push(p,'seen',state);continue;}
    const nowAction=action(p),oldAction=action(before);
    // A persistent Fold/Check badge is not a new action on every scan or street.
    if(nowAction&&(nowAction!==oldAction || (['call','raise','bet'].includes(nowAction)&&p.bet>before.bet)))push(p,nowAction,state);
    else if(p.bet>before.bet)push(p,'chips',state); // Do not guess call vs raise or blind.
   }
   previous={...state,players:state.players.map(p=>({...p}))};
  },
  batch:()=>[...pending.values()].slice(0,80),
  ack(ids){for(const id of ids||[])pending.delete(id);},
  size:()=>pending.size,
  pause(){previous=null;},
  warning:()=>warning
 };
}
const api={recorder};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.PokerNowTableCapture=api;
})(globalThis);
