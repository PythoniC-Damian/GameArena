(() => {
  const root = document.getElementById('arena-shop');
  const source = document.getElementById('shop-data');
  if (!root || !source) return;
  const data = JSON.parse(source.textContent);
  const owned = new Set(data.owned);
  const t = text => window.gaT ? window.gaT(text) : text;
  const colors = {
    emerald: ['#73edc0', '#25d79a55'], neon: ['#c4a2ff', '#7d4bd577'],
    solar: ['#ffc18a', '#f5893b55'], arctic: ['#91d9ff', '#2586c366'],
    astral: ['#bb9aff', '#965bff55'], crimson: ['#ff708c', '#f43f5e44'],
    frost: ['#9be9ff', '#38bdf855'], obsidian: ['#f4d58a', '#d4a43d44'],
  };
  const find = selector => root.querySelector(selector);
  const all = selector => root.querySelectorAll(selector);
  const form = find('#shop-action');
  let selected = data.selected;
  const preview = { ...data.equipped };
  let filter = 'all';
  function paint(element, key, background) {
    const item = data.catalog[key];
    const theme = item?.theme;
    const [themeColor, themeGlow] = colors[theme] || ['#a9bccf', 'transparent'];
    const color = item?.color || themeColor;
    const glow = item?.glow || themeGlow;
    element.style.setProperty('--selected', color);
    element.style.setProperty('--glow', glow);
    element.dataset.arenaCard = item?.slot === 'card' ? key : '';
    element.dataset.frame = item?.slot === 'frame' ? key : '';
    element.dataset.arenaNameplate = item?.slot === 'nameplate' ? key : '';
    if (background) element.style.background = theme
      ? `var(--arena-card-wash,radial-gradient(ellipse at top right,${glow},transparent 80%)),var(--arena-card-pattern,repeating-linear-gradient(125deg,transparent 0 24px,#ffffff09 25px 26px)),linear-gradient(120deg,#152a31,#0c1727)`
      : '#102132';
  }
  function renderSelection() {
    const item = data.catalog[selected];
    (item.components || [selected]).forEach(key => { preview[data.catalog[key].slot] = key; });
    paint(find('.player-cover'), preview.card, true);
    paint(find('.player-avatar'), preview.frame, false);
    paint(find('.player-name'), preview.nameplate, false);
    find('[data-selected-name]').textContent = item.name;
    find('[data-selected-description]').textContent = t(item.description);
    find('[data-bundle-note]').textContent = item.slot === 'bundle'
      ? 'Includes all three items. The displayed price accounts for components you already own.' : '';
    const isOwned = owned.has(selected);
    const isEquipped = (item.components || [selected]).every(key => data.equipped[data.catalog[key].slot] === key);
    form.action = isOwned ? data.equipUrl : data.buyBase + encodeURIComponent(selected) + '/buy';
    form.elements.item_key.value = selected;
    form.elements.price_gp.value = String(item.current_price);
    form.elements.confirm.checked = false;
    form.elements.confirm.required = !isOwned;
    find('.shop-confirm-area').hidden = isOwned;
    const button = form.querySelector('button[type=submit]');
    button.disabled = isOwned && isEquipped;
    button.textContent = isOwned ? (isEquipped ? t('Equipped') : t('Equip'))
      : (item.current_price ? `${t('Buy with GP')} - ${item.current_price} GP` : `${t('Add to collection')} - ${t('Free')}`);
    find('[data-feedback]').textContent = (isEquipped ? t('Currently equipped') + ': ' : t('Previewing') + ' ') + item.name;
  }
  root.addEventListener('click', event => {
    const tryOn = event.target.closest('[data-try]');
    if (tryOn && data.catalog[tryOn.dataset.try]) {
      event.preventDefault(); selected = tryOn.dataset.try; renderSelection();
      const url = new URL(location.href); url.searchParams.set('item', selected);
      history.replaceState(null, '', url);
      if (matchMedia('(max-width:760px)').matches) find('#shop-preview').scrollIntoView({ block: 'start', behavior: 'auto' });
      return;
    }
    const category = event.target.closest('[data-filter]');
    if (category) {
      filter = category.dataset.filter;
      all('[data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button === category)));
      let visible = 0;
      all('.shop-item').forEach(card => {
        card.hidden = filter === 'owned' ? card.dataset.owned !== 'true' : filter !== 'all' && card.dataset.category !== filter;
        if (!card.hidden) visible++;
      });
      find('[data-empty]').hidden = visible > 0;
      return;
    }
    const view = event.target.closest('button[data-view]');
    if (view) {
      find('.shop-preview').dataset.view = view.dataset.view;
      all('button[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button === view)));
    }
  });
  form.addEventListener('submit', () => { form.querySelector('button[type=submit]').disabled = true; });
  const collections = root.querySelector('[data-shop-collections]');
  if (collections) {
    const slides = [...collections.querySelectorAll('[data-collection]')];
    const track = collections.querySelector('[data-collection-track]');
    const reduced = matchMedia('(prefers-reduced-motion:reduce)').matches || document.body.dataset.reduceMotion === 'true';
    let index = 0, timer, settle, pointer = null, dragged = false, hovering = false;
    function stop() { clearInterval(timer); }
    function start() {
      stop();
      if (!reduced && slides.length > 1 && !document.hidden && !pointer && !hovering && !collections.contains(document.activeElement))
        timer = setInterval(() => show(index + 1), 4000);
    }
    function show(next) {
      index = (next + slides.length) % slides.length;
      track.scrollTo({ left: index * track.clientWidth, behavior: reduced ? 'auto' : 'smooth' });
    }
    track.addEventListener('scroll', () => {
      stop(); clearTimeout(settle);
      settle = setTimeout(() => {
        if (pointer) return;
        index = Math.max(0, Math.min(slides.length - 1, Math.round(track.scrollLeft / track.clientWidth)));
        start();
      }, 160);
    }, { passive: true });
    track.addEventListener('keydown', event => {
      if (event.target !== track || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      show(event.key === 'Home' ? 0 : event.key === 'End' ? slides.length - 1 : index + (event.key === 'ArrowRight' ? 1 : -1));
    });
    track.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      dragged = false; stop();
      if (event.pointerType !== 'touch') pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, left: track.scrollLeft };
    });
    track.addEventListener('pointermove', event => {
      if (!pointer || pointer.id !== event.pointerId) return;
      const dx = event.clientX - pointer.x, dy = event.clientY - pointer.y;
      if (!dragged && (Math.abs(dx) < 8 || Math.abs(dx) <= Math.abs(dy))) return;
      if (!dragged) { dragged = true; track.setPointerCapture(event.pointerId); track.classList.add('is-dragging'); }
      event.preventDefault(); track.scrollLeft = pointer.left - dx;
    });
    function release(event) {
      if (pointer && pointer.id === event.pointerId) {
        if (track.hasPointerCapture(event.pointerId)) track.releasePointerCapture(event.pointerId);
        pointer = null; track.classList.remove('is-dragging');
        if (dragged) show(Math.round(track.scrollLeft / track.clientWidth));
      }
      start();
    }
    track.addEventListener('pointerup', release);
    track.addEventListener('pointercancel', release);
    track.addEventListener('pointerleave', event => { if (pointer && !dragged) release(event); });
    track.addEventListener('click', event => { if (dragged) { event.preventDefault(); event.stopPropagation(); } }, true);
    collections.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') { hovering = true; stop(); } });
    collections.addEventListener('pointerleave', () => { hovering = false; start(); });
    collections.addEventListener('focusin', stop);
    collections.addEventListener('focusout', () => setTimeout(start, 0));
    document.addEventListener('visibilitychange', start);
    window.addEventListener('resize', () => { show(index); start(); });
    window.addEventListener('pagehide', () => { stop(); clearTimeout(settle); });
    start();
  }
  renderSelection();
})();
