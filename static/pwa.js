// PWA côté client : anti-doublons, file d'attente hors-ligne, sync
(function(){
  const KEY = 'keg_queue_v1';

  function getQueue(){
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); }
    catch(e){ return []; }
  }
  function setQueue(q){
    localStorage.setItem(KEY, JSON.stringify(q));
    const b = document.querySelector('#sync-badge');
    if(b){ b.textContent = q.length ? String(q.length) : ''; }
  }
  async function ping(){
    try { const r = await fetch('/api/ping', {cache:'no-store'}); return r.ok; }
    catch(e){ return false; }
  }
  async function sendOne(item){
    const r = await fetch('/api/movement', {
      method: 'POST',
      headers: {'Content-Type':'application/json','X-From-PWA':'1'},
      body: JSON.stringify(item)
    });
    if(!r.ok) throw new Error('send failed');
    const js = await r.json();
    if(!(js && js.ok)) throw new Error('server not ok');
  }
  async function syncAll(showAlert){
    let q = getQueue();
    if(!q.length){ if(showAlert) alert('Rien à synchroniser.'); return true; }
    if(!await ping()){ if(showAlert) alert('Hors-ligne. Réessaie plus tard.'); return false; }
    for(const it of q){ await sendOne(it); }
    setQueue([]);
    if(showAlert) alert('Synchronisation terminée ✔');
    return true;
  }

  document.addEventListener('DOMContentLoaded', function(){
    // Mise à jour badge
    setQueue(getQueue());

    // Intercepter le submit HTML et tout passer par l’API (évite les doublons)
    const form = document.querySelector('form[action$="/movements/add"]') || document.querySelector('form[action="/movements/add"]');
    if(form){
      form.addEventListener('submit', async function(ev){
        ev.preventDefault(); // ⛔️ empêche l’envoi HTML
        const submitBtn = form.querySelector('button[type="submit"]');
        if(submitBtn) submitBtn.disabled = true;

        const data = Object.fromEntries(new FormData(form).entries());
        const item = {
          dt: data.dt || new Date().toISOString().slice(0,10),
          mtype: data.mtype,
          client_id: parseInt(data.client_id,10),
          beer_id: parseInt(data.beer_id,10),
          qty: parseInt(data.qty||'1',10),
          consigne_per_keg: parseFloat(data.consigne_per_keg||'0'),
          notes: data.notes || ''
        };

        try{
          await sendOne(item);
          window.location.href = '/movements';
        }catch(e){
          const q = getQueue(); q.push(item); setQueue(q);
          alert('Hors-ligne : mouvement mis en file. Utilise “Sync” quand tu as du réseau.');
          window.location.href = '/movements';
        }finally{
          if(submitBtn) submitBtn.disabled = false;
        }
      }, false);
    }

    // Bouton Sync
    const btn = document.querySelector('#sync-btn');
    if(btn){
      btn.addEventListener('click', function(e){
        e.preventDefault();
        syncAll(true);
      });
    }

    // SW
    if('serviceWorker' in navigator){
      try { navigator.serviceWorker.register('/static/service-worker.js?v=3'); } catch(e){}
    }
  });
})();
