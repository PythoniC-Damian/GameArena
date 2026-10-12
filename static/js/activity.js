(() => {
  const root = document.querySelector('[data-activity-dashboard]');
  if (!root) return;
  const status = document.querySelector('[data-activity-status]');
  let busy = false, pending = false, timer, lastHTML = root.innerHTML;
  async function refresh() {
    if (document.hidden) return;
    if (busy) { pending = true; return; }
    busy = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(root.dataset.liveUrl, {cache:'no-store', headers:{Accept:'application/json'}, signal:controller.signal});
      if (!response.ok) throw new Error('Could not update activity');
      const data = await response.json();
      const opened = !!root.querySelector('details[open]');
      if (typeof data.html !== 'string') throw new Error('Invalid activity response');
      if (data.html !== lastHTML) {
        root.innerHTML = data.html; lastHTML = data.html;
        if (opened) root.querySelector('details')?.setAttribute('open','');
      }
      status.textContent = 'Live updates enabled. Last synced ' + new Date().toLocaleTimeString();
    } catch (_) { status.textContent = 'Connection interrupted. Retrying automatically; displayed data may be older.'; }
    finally { clearTimeout(timeout); busy = false; if (pending) { pending = false; schedule(); } }
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(refresh, 250); }
  const socket = window.gamearenaSocket;
  if (socket) { socket.on('activity_updated', schedule); socket.on('connect', schedule); }
  // Reconcile registrations, calendar rollover, and missed or disconnected events.
  setInterval(refresh, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) schedule(); });
  window.addEventListener('online', schedule);
  refresh();
})();
