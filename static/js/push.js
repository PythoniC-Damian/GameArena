(() => {
  let enable = document.querySelector('[data-enable-push]');
  let invitation;
  const userId = document.querySelector('.ga-header')?.dataset.userId;
  if (!enable && userId) {
    invitation = document.createElement('aside');
    invitation.className = 'ga-card ga-push-invitation'; invitation.hidden = true;
    invitation.setAttribute('aria-label','Device notifications');
    invitation.innerHTML = '<div><h2 class="ga-section-title">Stay in the game</h2><p class="ga-muted">Get messages and tournament updates when GameArena is closed.</p><p data-push-status class="ga-muted" role="status"></p></div><div class="ga-connection-controls"><button type="button" class="ga-button ga-button-primary" data-enable-push>Enable notifications</button><button type="button" class="ga-button ga-button-secondary" data-push-later>Later</button><button type="button" data-disable-push hidden>Disable</button></div>';
    document.querySelector('.ga-header').insertAdjacentElement('afterend',invitation);
    enable = invitation.querySelector('[data-enable-push]');
  }
  const disable = document.querySelector('[data-disable-push]');
  const status = document.querySelector('[data-push-status]');
  if (!enable || !status) return;
  const test = document.querySelector('[data-test-push]');
  const dismissKey = 'gamearenaPushLater:' + userId;
  let dismissedUntil = 0;
  try { dismissedUntil = Number(localStorage.getItem(dismissKey)) || 0; } catch (_) {}
  invitation?.querySelector('[data-push-later]')?.addEventListener('click', () => {
    invitation.hidden = true;
    try { localStorage.setItem(dismissKey,String(Date.now() + 7*24*60*60*1000)); } catch (_) {}
  });
  let configured, registration;
  function showState(enabled) { if (invitation && enabled) invitation.hidden = true; enable.hidden = enabled; disable.hidden = !enabled; if (test) test.hidden = !enabled; }
  function keyBytes(value) {
    const clean = String(value || '').trim().replace(/\s/g,'');
    const base64 = clean.replace(/-/g,'+').replace(/_/g,'/');
    const raw = atob(base64 + '='.repeat((4-base64.length%4)%4));
    const bytes = Uint8Array.from(raw, character => character.charCodeAt(0));
    if (bytes.length !== 65 || bytes[0] !== 4) throw new Error('Server notification key format is invalid. Please report the key-format diagnostic to GameArena support.');
    return bytes;
  }
  async function pushFetch(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try { return await fetch(url, {...options, signal:controller.signal}); }
    catch (error) { if (error.name === 'AbortError') throw new Error('Notification setup timed out. Please try again.'); throw error; }
    finally { clearTimeout(timeout); }
  }
  async function update(method, subscription) {
    const response = await pushFetch('/notifications/push', {method,headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify({subscription})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Could not save notification preferences.');
  }
  async function setup() {
    if (!window.isSecureContext || !('Notification' in window) || !('PushManager' in window) || !('serviceWorker' in navigator)) {
      enable.disabled = true; status.textContent = 'Device notifications are unavailable in this browser. On iPhone, install GameArena on your Home Screen and open it there.'; return;
    }
    try {
      const response = await pushFetch('/notifications/push', {cache:'no-store'});
      if (!response.ok) throw new Error('Could not check phone notifications.');
      configured = await response.json();
      if (!configured.configured) { enable.disabled = true; status.textContent = 'Device notifications need server configuration. Please contact GameArena support.'; return; }
      if (configured.public_key_status && !configured.public_key_status.valid) {
        enable.disabled = true; status.textContent = configured.public_key_status.error + ' No key values are displayed.'; return;
      }
      keyBytes(configured.public_key);
      registration = await Promise.race([navigator.serviceWorker.ready, new Promise((_,reject) => setTimeout(() => reject(new Error('Service worker is not ready. Reload GameArena and try again.')), 10000))]);
      const subscription = await registration.pushManager.getSubscription();
      showState(!!subscription);
      status.textContent = subscription ? 'Notifications enabled for this device and account.' : 'Enable to receive notifications on this device.';
      if (subscription) {
        // Link an existing, previously permitted subscription to this account.
        // A short tab-scoped cache avoids saving it on every navigation.
        const encoded = new TextEncoder().encode(subscription.endpoint);
        const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoded))).map(b=>b.toString(16).padStart(2,'0')).join('');
        const linkedKey = 'gamearenaPushLinked:' + userId + ':' + hash;
        let linkedAt = 0; try { linkedAt = Number(sessionStorage.getItem(linkedKey)) || 0; } catch (_) {}
        if (!invitation || Date.now()-linkedAt > 5*60*1000) {
          await update('POST', subscription.toJSON());
          try { sessionStorage.setItem(linkedKey,String(Date.now())); } catch (_) {}
        }
      } else if (invitation && Notification.permission !== 'denied' && Date.now() >= dismissedUntil) {
        invitation.hidden = false;
      }
    } catch (error) { status.textContent = error.message; }
  }
  enable.addEventListener('click', async () => {
    if (!configured?.configured || !registration) return;
    enable.disabled = true;
    try {
      if (await Notification.requestPermission() !== 'granted') throw new Error('Notifications were not allowed. You can change this in your browser settings.');
      const subscription = await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(configured.public_key)});
      try { await update('POST', subscription.toJSON()); } catch (error) { await subscription.unsubscribe(); throw error; }
      showState(true); status.textContent = 'Notifications enabled on this device.';
    } catch (error) { status.textContent = error.message; if (invitation && Notification.permission === 'denied') invitation.hidden = true; } finally { enable.disabled = false; }
  });
  disable.addEventListener('click', async () => {
    disable.disabled = true;
    try {
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) { await update('DELETE', subscription.toJSON()); await subscription.unsubscribe(); }
      showState(false); status.textContent = 'Notifications disabled on this device.';
    } catch (error) { status.textContent = error.message; } finally { disable.disabled = false; }
  });
  test?.addEventListener('click', async () => {
    test.disabled = true;
    try {
      const response = await pushFetch('/notifications/push/test', {method:'POST', headers:{'X-CSRFToken':document.querySelector('meta[name=csrf-token]').content}});
      const data = await response.json(); if (!response.ok) throw new Error(data.error || data.message || 'Could not queue the test notification.');
      status.textContent = data.message;
    } catch (error) { status.textContent = error.message; } finally { test.disabled = false; }
  });
  setup();
})();
