(function(){
  const KEY='keg_queue_v1';

  function getQueue(){
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch(e){ return []; }
  }
  function setQueue(q){ localStorage.setItem(KEY, JSON.stringify(q)); updateBadge(); }

  function updateBadge(){
    const n = getQueue().length;
    const badge = document.querySelector('#sync-badge');
    if(badge){ badge.textContent = n>0 ? String(n) : ''; }
  }

  async function ping(){
    try{
      const res = await fetch('/api/ping');
      return res.ok;
    }catch(e){ return false; }
  }

  async function sendOne(item){
    const res = await fetch('/api/movement', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(item)
    });
    if(!res.ok){ throw new Error('send failed'); }
    const js = await res.json();
    if(!js.ok){ throw new Error('server not ok'); }
  }

  async function syncAll(){
    let q = getQueue();
    if(q.length===0){ return true; }
    const online = await ping();
    if(!online){ throw new Error('offline'); }
    for(let i=0;i<q.length;i++){
      await sendOne(q[i]);
    }
    setQueue([]);
    return true;
  }

  async function trySync(showAlert){
    try{
      await syncAll();
      if(showAlert) alert('Synchronisation terminée ✔');
    }catch(e){
      if(showAlert) alert("Impossible de synchroniser (hors‑ligne ?).");
    }finally{
      updateBadge();
    }
  }

  // expose
  window.KegPWA = { getQueue, setQueue, trySync };

  // Intercept movement form
  document.addEventListener('DOMContentLoaded', function(){
    updateBadge();
    const form = document.querySelector('form[action$="/movements/add"]') || document.querySelector('form[action="/movements/add"]') || document.querySelector('form[method="post"]');
    if(form && location.pathname.includes('/movements/add')){
      form.addEventListener('submit', async function(ev){
        try{
          const data = Object.fromEntries(new FormData(form).entries());
          // Normalize payload
          const item = {
            dt: data.dt || new Date().toISOString().slice(0,10),
            mtype: data.mtype,
            client_id: parseInt(data.client_id,10),
            beer_id: parseInt(data.beer_id,10),
            qty: parseInt(data.qty||'1',10),
            consigne_per_keg: parseFloat(data.consigne_per_keg||'0'),
            notes: data.notes||''
          };
          // Try online first
          const ok = await fetch('/api/movement', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(item)
          }).then(r=>r.json()).catch(()=>({ok:false, offline:true}));

          if(ok && ok.ok){
            // normal flow online
          }else{
            // queue offline
            const q = getQueue(); q.push(item); setQueue(q);
            alert('Mouvement enregistré hors‑ligne. Il sera synchronisé plus tard.');
          }
        }catch(e){
          // best‑effort queue
          const q = getQueue();
          q.push({error:'unknown', ts: Date.now()});
          setQueue(q);
        }
        // let server redirect regardless, to keep UX consistent
      }, {once:false});
    }

    // Sync button
    const btn = document.querySelector('#sync-btn');
    if(btn){
      btn.addEventListener('click', function(e){
        e.preventDefault();
        trySync(true);
      });
    }
  });

})();