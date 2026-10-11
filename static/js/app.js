(() => {
  'use strict';
  document.querySelectorAll('[data-flash]').forEach(message => setTimeout(() => message.remove(),4000));
  const header = document.querySelector('.ga-header');
  if (!header) return;
  const menus = Array.from(document.querySelectorAll('[data-menu]'));
  const logoutDialog = document.getElementById('logoutConfirmation');
  let logoutTrigger;
  document.querySelectorAll('form[action="/logout"]').forEach(form => form.addEventListener('submit', event => {
    if (form.querySelector('[name="confirmed"]') || !logoutDialog?.showModal) return;
    event.preventDefault(); logoutTrigger = form.closest('details')?.querySelector('summary') || event.submitter; closeMenus(); logoutDialog.showModal();
  }));
  logoutDialog?.querySelector('[data-cancel-logout]').addEventListener('click', () => logoutDialog.close());
  logoutDialog?.addEventListener('close', () => logoutTrigger?.focus());
  function closeMenus(restoreFocus = false) {
    menus.forEach(menu => { if (menu.open) { menu.open = false; if (restoreFocus) menu.querySelector('summary').focus(); } });
  }
  menus.forEach(menu => {
    const summary = menu.querySelector('summary');
    summary.setAttribute('aria-expanded', 'false');
    menu.addEventListener('toggle', () => {
      summary.setAttribute('aria-expanded', String(menu.open));
      if (menu.open) menus.forEach(other => { if (other !== menu) other.open = false; });
    });
    menu.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); closeMenus(true); }
      if (event.key === 'ArrowDown' && event.target === summary) { event.preventDefault(); menu.open = true; menu.querySelector('.ga-menu a')?.focus(); }
    });
    menu.addEventListener('focusout', () => setTimeout(() => { if (document.activeElement !== document.body && !menu.contains(document.activeElement)) menu.open = false; }, 0));
  });
  document.addEventListener('click', event => { if (!menus.some(menu => menu.contains(event.target))) closeMenus(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenus(true); });
  function updateUnread(count) {
    if (!Number.isFinite(Number(count))) return;
    count = Math.max(0, Number(count));
    document.querySelectorAll('[data-unread-badge]').forEach(badge => { badge.textContent = count > 99 ? '99+' : String(count); badge.hidden = count === 0; });
    document.querySelectorAll('.ga-notifications').forEach(link => link.setAttribute('aria-label', count ? `Notifications, ${count} unread` : 'Notifications'));
  }
  let refreshing;
  const notificationMenu = document.querySelector('[data-notification-menu]');
  const panel = notificationMenu?.querySelector('[data-notification-preview]');
  let previewRequest;
  function internalURL(value) {
    try { const url = new URL(value, location.origin); return url.origin === location.origin && ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch (_) { return null; }
  }
  async function loadPreview() {
    if (!panel || previewRequest) return;
    if (panel.contains(document.activeElement)) notificationMenu.querySelector('summary').focus();
    panel.textContent = 'Loading updates…';
    previewRequest = true;
    try {
      const response = await fetch(notificationMenu.querySelector('[data-preview-url]').dataset.previewUrl, {cache:'no-store',headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error('Recent updates could not be loaded.');
      const data = await response.json(); updateUnread(data.unread); panel.replaceChildren();
      if (!data.notifications.length) { panel.textContent = 'You’re all caught up. New updates will appear here.'; return; }
      data.notifications.forEach(item => {
        const row = document.createElement('article'); row.className = 'ga-preview-item'; row.classList.toggle('is-unread', item.unread);
        const link = document.createElement('a'); link.textContent = item.message; link.href = internalURL(item.target_url) || '/notifications'; row.append(link);
        const time = document.createElement('small'); const date = new Date(item.created_at); time.textContent = Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); row.append(time);
        if (item.unread) {
          const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Mark read';
          button.addEventListener('click', async () => { button.disabled = true; try { await markRead(item.read_url); } catch (_) { button.disabled = false; button.textContent = 'Retry marking read'; } }); row.append(button);
        }
        panel.append(row);
      });
    } catch (error) { panel.textContent = error.message || 'Could not load updates.'; const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry'; retry.addEventListener('click', loadPreview); panel.append(retry); }
    finally { previewRequest = false; }
  }
  async function markRead(url) {
    const response = await fetch(url, {method:'POST',headers:{Accept:'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content}});
    if (!response.ok) throw new Error('Could not update notifications.');
    const data = await response.json(); updateUnread(data.unread); await loadPreview();
  }
  notificationMenu?.addEventListener('toggle', () => { if (notificationMenu.open) loadPreview(); });
  document.querySelector('[data-notifications-read-all]')?.addEventListener('click', async event => {
    const button = event.currentTarget; button.disabled = true;
    try { await markRead(button.dataset.url); } catch (error) { panel.textContent = error.message; } finally { button.disabled = false; }
  });
  window.gamearenaNotify = payload => {
    if (!payload?.message) return;
    let stack = document.querySelector('.ga-toast-stack');
    if (!stack) { stack = document.createElement('div'); stack.className = 'ga-toast-stack'; stack.setAttribute('aria-live','polite'); document.body.append(stack); }
    const toast = document.createElement('div'); toast.className = 'ga-toast';
    const text = document.createElement('a'); text.textContent = payload.message; text.href = internalURL(payload.target_url) || '/notifications';
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label','Dismiss notification'); close.addEventListener('click', () => toast.remove()); toast.append(text,close); stack.append(toast);
    while (stack.children.length > 3) stack.firstElementChild.remove();
    setTimeout(() => toast.remove(), 4000);
  };
  const updatingConnections = new Set(), connectionReads = new Map();
  function connectionWidgets(id) {
    return Array.from(document.querySelectorAll('[data-player-connection]')).filter(widget => Number(widget.dataset.playerConnection) === Number(id));
  }
  function applyConnection(id, data) {
    connectionWidgets(id).forEach(widget => { widget.outerHTML = data.controls_html; });
    const chat = document.querySelector('.ga-chat-shell');
    if (Number(chat?.dataset.partnerId) === Number(id)) {
      chat.dataset.introduction = String(!['open','accepted'].includes(data.connection.state));
      const input = document.getElementById('chatInput'), submit = document.querySelector('#chatForm button[type=submit]');
      if (input) input.disabled = !data.connection.can_send;
      if (submit) submit.disabled = !data.connection.can_send;
      const status = document.getElementById('chatStatus');
      if (status) status.textContent = data.connection.can_send ? '' : 'Wait for your player request to be accepted before messaging.';
    }
    window.dispatchEvent(new CustomEvent('gamearena:connection-updated', {detail:{partnerId:Number(id)}}));
  }
  window.gamearenaRefreshConnection = async id => {
    const widget = connectionWidgets(id)[0];
    if (!widget || updatingConnections.has(Number(id)) || connectionReads.has(Number(id))) return;
    connectionReads.set(Number(id), true);
    try {
      const response = await fetch(widget.dataset.url, {cache:'no-store', headers:{Accept:'application/json'}});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
      const data = await response.json();
      // A newer POST replaces the widget; an older GET must not overwrite it.
      if (widget.isConnected && !updatingConnections.has(Number(id))) applyConnection(id, data);
    } catch (_) {} finally { connectionReads.delete(Number(id)); }
  };
  document.addEventListener('submit', async event => {
    const form = event.target, widget = form.closest('[data-player-connection]');
    if (!widget) return;
    event.preventDefault();
    const id = Number(widget.dataset.playerConnection);
    if (updatingConnections.has(id)) return;
    updatingConnections.add(id);
    const payload = new FormData(form), button = event.submitter || form.querySelector('button'), label = button.textContent;
    widget.setAttribute('aria-busy','true'); widget.querySelectorAll('button').forEach(item => { item.disabled = true; }); button.textContent = 'Updating…';
    widget.querySelector('[data-connection-error]')?.remove();
    try {
      const response = await fetch(widget.dataset.url, {method:'POST',body:payload,headers:{Accept:'application/json'}});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
        throw new Error(response.status === 429 ? 'Please wait before sending another request.' : 'Could not update this request. Please try again.');
      }
      const data = await response.json(); applyConnection(id, data);
      if (data.message) window.gamearenaNotify({message:data.message,target_url:location.pathname});
    } catch (error) {
      const feedback = document.createElement('p'); feedback.className = 'ga-muted'; feedback.dataset.connectionError = ''; feedback.setAttribute('role','alert'); feedback.textContent = error.message; widget.append(feedback);
      widget.querySelectorAll('button').forEach(item => { item.disabled = false; }); button.textContent = label;
    } finally { updatingConnections.delete(id); widget.removeAttribute('aria-busy'); }
  });
  function refreshConnections() { document.querySelectorAll('[data-player-connection]').forEach(widget => window.gamearenaRefreshConnection(Number(widget.dataset.playerConnection))); }
  window.addEventListener('pageshow', event => { if (event.persisted) refreshConnections(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshConnections(); });
  function refreshUnread() {
    if (!header.dataset.unreadUrl || refreshing) return;
    refreshing = fetch(header.dataset.unreadUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(response => response.ok ? response.json() : null)
      .then(data => { if (data) updateUnread(data.unread); }).catch(() => {})
      .finally(() => { refreshing = null; });
  }
  if (header.dataset.userId && typeof io === 'function') {
    const socket = window.gamearenaSocket || (window.gamearenaSocket = io());
    socket.on('connect', () => { socket.emit('join_user', { user_id: Number(header.dataset.userId) }); refreshUnread(); refreshConnections(); });
    socket.on('player_connection_changed', payload => window.gamearenaRefreshConnection(Number(payload.partner_id)));
    if (socket.connected) socket.emit('join_user', { user_id: Number(header.dataset.userId) });
    socket.on('notification', payload => {
      refreshUnread();
      window.gamearenaNotify(payload);
      if (notificationMenu?.open) loadPreview();
      const list = document.querySelector('[data-live-notifications]');
      if (!list || !payload?.message || (payload.id && list.querySelector(`[data-notification-id="${Number(payload.id)}"]`))) return;
      list.querySelector('[data-notification-empty]')?.remove();
      const row = document.createElement('article'); row.className = 'ga-record block';
      if (payload.id) row.dataset.notificationId = String(payload.id);
      const text = document.createElement('p'); text.textContent = payload.message; row.append(text);
      if (payload.target_url) {
        const url = new URL(payload.target_url, location.origin);
        if (url.origin === location.origin) { const link = document.createElement('a'); link.href = url.href; link.textContent = 'View update'; row.append(link); }
      }
      list.prepend(row); while (list.children.length > 5) list.lastElementChild.remove();
    });
    socket.on('notification_unread_count', payload => updateUnread(payload?.unread));
    window.addEventListener('pageshow', event => { if (event.persisted) refreshUnread(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshUnread(); });
  }
  document.querySelectorAll('form[data-saving]').forEach(form => form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
  }));
  const themeOptions = document.querySelector('[data-theme-url]');
  let savedTheme = document.documentElement.dataset.theme, savingTheme = false, desiredTheme = savedTheme;
  async function persistTheme() {
    if (savingTheme || desiredTheme === savedTheme) return;
    savingTheme = true;
    const theme = desiredTheme, feedback = document.getElementById('themeStatus');
    feedback.textContent = 'Saving theme…';
    try {
      const response = await fetch(themeOptions.dataset.themeUrl, {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify({theme})});
      if (!response.ok) throw new Error('Theme could not be saved. Please choose it again.');
      savedTheme = theme; try { localStorage.setItem('gamearenaTheme',theme); } catch (_) {}
      feedback.textContent = 'Theme saved.';
    } catch (error) {
      desiredTheme = savedTheme; document.documentElement.dataset.theme = savedTheme;
      themeOptions.querySelectorAll('input').forEach(input => { input.checked = input.value === savedTheme; });
      feedback.textContent = error.message;
    } finally { savingTheme = false; if (desiredTheme !== savedTheme) persistTheme(); }
  }
  themeOptions?.querySelectorAll('input[name=theme]').forEach(input => input.addEventListener('change', () => {
    if (!input.checked) return;
    desiredTheme = input.value; document.documentElement.dataset.theme = desiredTheme; persistTheme();
  }));
  document.querySelectorAll('[data-confirm]').forEach(form => form.addEventListener('submit', event => { if (!window.confirm(form.dataset.confirm)) event.preventDefault(); }));
  document.querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
    if (img.dataset.fallbackApplied) return;
    img.dataset.fallbackApplied = 'true';
    if (img.classList.contains('ga-avatar-small') || img.classList.contains('ga-avatar')) { img.alt = 'Player avatar'; img.removeAttribute('src'); }
    else img.src = '/static/images/gaming-fallback.svg';
  }));
})();
