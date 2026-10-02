(() => {
  'use strict';
  const header = document.querySelector('.ga-header');
  if (!header) return;
  const menus = Array.from(document.querySelectorAll('[data-menu]'));
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
    menu.addEventListener('focusout', () => setTimeout(() => { if (!menu.contains(document.activeElement)) menu.open = false; }, 0));
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
  function refreshUnread() {
    if (!header.dataset.unreadUrl || refreshing) return;
    refreshing = fetch(header.dataset.unreadUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(response => response.ok ? response.json() : null)
      .then(data => { if (data) updateUnread(data.unread); }).catch(() => {})
      .finally(() => { refreshing = null; });
  }
  if (header.dataset.userId && typeof io === 'function') {
    const socket = window.gamearenaSocket || (window.gamearenaSocket = io());
    socket.on('connect', () => { socket.emit('join_user', { user_id: Number(header.dataset.userId) }); refreshUnread(); });
    if (socket.connected) socket.emit('join_user', { user_id: Number(header.dataset.userId) });
    socket.on('notification', payload => {
      refreshUnread();
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
    window.addEventListener('pageshow', refreshUnread);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshUnread(); });
  }
  document.querySelectorAll('form[data-saving]').forEach(form => form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
  }));
  document.querySelectorAll('[data-confirm]').forEach(form => form.addEventListener('submit', event => { if (!window.confirm(form.dataset.confirm)) event.preventDefault(); }));
  document.querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
    if (img.dataset.fallbackApplied) return;
    img.dataset.fallbackApplied = 'true';
    if (img.classList.contains('ga-avatar-small') || img.classList.contains('ga-avatar')) { img.alt = 'Player avatar'; img.removeAttribute('src'); }
    else img.src = '/static/images/gaming-fallback.svg';
  }));
})();
