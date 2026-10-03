(() => {
  const enable = document.querySelector('[data-enable-push]');
  const disable = document.querySelector('[data-disable-push]');
  const status = document.querySelector('[data-push-status]');
  if (!enable || !status) return;
  let configured, registration;
  function keyBytes(value) {
    const base64 = value.replace(/-/g,'+').replace(/_/g,'/');
    const raw = atob(base64 + '='.repeat((4-base64.length%4)%4));
    return Uint8Array.from(raw, character => character.charCodeAt(0));
  }
  async function update(method, subscription) {
    const response = await fetch('/notifications/push', {method,headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify({subscription})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Could not save notification preferences.');
  }
  async function setup() {
    if (!window.isSecureContext || !('Notification' in window) || !('PushManager' in window) || !('serviceWorker' in navigator)) {
      enable.disabled = true; status.textContent = 'Device notifications are unavailable in this browser. On iPhone, install GameArena on your Home Screen and open it there.'; return;
    }
    try {
      const response = await fetch('/notifications/push', {cache:'no-store'});
      if (!response.ok) throw new Error('Could not check phone notifications.');
      configured = await response.json();
      if (!configured.configured) { enable.disabled = true; status.textContent = 'Phone notifications are being set up. Live in-app notifications already work.'; return; }
      registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      enable.hidden = !!subscription; disable.hidden = !subscription;
      status.textContent = subscription ? 'Device permission is enabled. Use Enable if your account has changed.' : 'Enable to receive notifications on this device.';
      if (subscription) await update('POST', subscription.toJSON());
    } catch (error) { status.textContent = error.message; }
  }
  enable.addEventListener('click', async () => {
    if (!configured?.configured || !registration) return;
    enable.disabled = true;
    try {
      if (await Notification.requestPermission() !== 'granted') throw new Error('Notifications were not allowed. You can change this in your browser settings.');
      const subscription = await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(configured.public_key)});
      try { await update('POST', subscription.toJSON()); } catch (error) { await subscription.unsubscribe(); throw error; }
      enable.hidden = true; disable.hidden = false; status.textContent = 'Notifications enabled on this device.';
    } catch (error) { status.textContent = error.message; } finally { enable.disabled = false; }
  });
  disable.addEventListener('click', async () => {
    disable.disabled = true;
    try {
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) { await update('DELETE', subscription.toJSON()); await subscription.unsubscribe(); }
      enable.hidden = false; disable.hidden = true; status.textContent = 'Notifications disabled on this device.';
    } catch (error) { status.textContent = error.message; } finally { disable.disabled = false; }
  });
  setup();
})();
