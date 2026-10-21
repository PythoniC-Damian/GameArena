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
  };
  const find = selector => root.querySelector(selector);
  const all = selector => root.querySelectorAll(selector);
  const form = find('#shop-action');
  let selected = data.selected;
  let filter = 'all';
  function paint(element, key, background) {
    const theme = data.catalog[key]?.theme;
    const [color, glow] = colors[theme] || ['#a9bccf', 'transparent'];
    element.style.setProperty('--selected', color);
    element.style.setProperty('--glow', glow);
    if (background) element.style.background = theme
      ? `repeating-linear-gradient(125deg,transparent 0 24px,#ffffff09 25px 26px),radial-gradient(ellipse at top right,${glow},transparent 80%),linear-gradient(120deg,#152a31,#0c1727)`
      : '#102132';
  }
  function renderSelection() {
    const item = data.catalog[selected];
    const preview = { ...data.equipped };
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
  renderSelection();
})();
