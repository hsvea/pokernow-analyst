/* Local-only bridge. Send nothing until user explicitly enables pairing in the HUD. */
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type !== 'PN_ANALYST_SNAPSHOT') return;
  if (!sender.tab || !/^https:\/\/(?:www\.)?pokernow\.(?:com|club)\/games\//.test(sender.tab.url || '')) {
    respond({ok: false, error:'invalid tab'});
    return;
  }
  const token = message.token;
  const snapshot = message.snapshot;
  if (typeof token !== 'string' || !/^[a-f0-9]{24}$/.test(token) || !snapshot || typeof snapshot !== 'object') {
    respond({ok: false, error: 'invalid pairing data'});
    return;
  }
  fetch('http://127.0.0.1:8765/v1/snapshot', {
    method:'POST', headers:{'Content-Type':'application/json', 'Authorization': 'Bearer '+token},
    body:JSON.stringify(snapshot), cache:'no-store', signal:AbortSignal.timeout(2700)
  }).then(async r => {
    if (!r.ok) throw new Error('HTTP '+r.status);
    const data=await r.json();
    const current=chrome.runtime.getManifest().version;
    if(data.version && data.version!==current){
      try{
        const disk=await fetch(chrome.runtime.getURL('manifest.json'),{cache:'no-store'}).then(r=>r.json());
        const stored=await chrome.storage.local.get('lastReloadVersion');
        if(disk.version===data.version && stored.lastReloadVersion!==data.version){
          await chrome.storage.local.set({lastReloadVersion:data.version});
          data.extensionReloaded=true;
          setTimeout(()=>chrome.runtime.reload(),750);
        }
      }catch(_){ /* Manual Reload in Opera remains available. */ }
    }
    respond(data);
  }).catch(err => respond({ok:false,error:String(err?.message||err)}));
  return true;
});
