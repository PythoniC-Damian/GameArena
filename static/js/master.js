(() => {
  document.querySelectorAll('[data-pro-track]').forEach(track => {
    track.addEventListener('keydown', event => {
      if (event.target !== track || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      track.scrollBy({left:(event.key === 'ArrowRight' ? 1 : -1) * (track.firstElementChild.getBoundingClientRect().width + 14),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    });
  });
  const welcome = document.querySelector('[data-pro-welcome]');
  if (welcome && typeof welcome.showModal === 'function') {
    const key = 'gamearenaProWelcome:v1';
    let seen = false;
    try {seen = sessionStorage.getItem(key) === 'seen';} catch (_) {}
    if (!seen) {
      const previousFocus = document.activeElement;
      welcome.showModal(); document.body.classList.add('ga-pro-modal-open');
      try {sessionStorage.setItem(key,'seen');} catch (_) {}
      welcome.addEventListener('close',() => {document.body.classList.remove('ga-pro-modal-open');previousFocus?.focus();});
      welcome.querySelector('[data-pro-close]').addEventListener('click',() => welcome.close());
      welcome.addEventListener('click',event => {if (event.target.closest('a')) welcome.close();});
    }
  }

  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';
  async function post(url, payload) {
    const response = await fetch(url, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':csrf(),Accept:'application/json'}, body:JSON.stringify(payload)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || (response.status === 403 ? 'An active Master membership is required.' : 'Could not save. Please try again.'));
    return data;
  }
  const appearance = document.querySelector('[data-master-appearance]');
  if (appearance) {
    let pending = false, queued = false;
    const feedback = appearance.querySelector('[data-master-feedback]');
    const surface = appearance.closest('[data-profile-theme]');
    const avatar = surface.querySelector('[data-master-avatar]');
    let saved = {frame:appearance.elements.frame.value,profile_theme:appearance.elements.profile_theme.value};
    function preview() { avatar.dataset.frame = appearance.elements.frame.value; surface.dataset.profileTheme = appearance.elements.profile_theme.value; }
    async function save() {
      queued = true;
      if (pending) return;
      pending = true;
      const submit = appearance.querySelector('button[type=submit]'); submit.disabled = true;
      while (queued) {
        queued = false;
        const payload = {frame:appearance.elements.frame.value, profile_theme:appearance.elements.profile_theme.value};
        preview(); feedback.textContent = 'Saving…';
        try { const data = await post(appearance.getAttribute('action'),payload); saved = payload; feedback.textContent = data.message; }
        catch (error) { if (!queued) {appearance.elements.frame.value = saved.frame; appearance.elements.profile_theme.value = saved.profile_theme; preview();} feedback.textContent = error.message; }
      }
      pending = false; submit.disabled = false;
    }
    appearance.addEventListener('change',save);
    appearance.addEventListener('submit',event => {event.preventDefault(); save();});
  }
  document.querySelectorAll('[data-saved-url]').forEach(group => {
    let busy = false;
    group.addEventListener('click',async event => {
      const button = event.target.closest('[data-save-action]');
      if (!button || busy) return;
      busy = true; const buttons = [...group.querySelectorAll('button')]; buttons.forEach(b => b.disabled=true);
      const feedback = group.querySelector('[data-master-feedback]');
      try {
        const action = button.dataset.saveAction;
        const data = await post(group.dataset.savedUrl,{action,enabled:button.dataset.enabled==='true'});
        feedback.textContent = data.message;
        const save = group.querySelector('[data-save-action=save], [data-save-action=remove]');
        if (save) {save.dataset.saveAction = data.saved ? 'remove':'save'; save.textContent = data.saved ? 'Saved · remove':'Save tournament';}
        const reminder = group.querySelector('[data-save-action=reminder]');
        if (reminder) {reminder.textContent=data.reminder?'Reminder on':'Remind me'; reminder.dataset.enabled=String(!data.reminder); reminder.setAttribute('aria-pressed',String(data.reminder));}
        if (!data.saved && group.closest('[data-saved-row]')) {const row=group.closest('[data-saved-row]');row.replaceChildren();const text=document.createElement('p');text.className='ga-muted';text.textContent=data.message;row.append(text);}
      } catch(error) {feedback.textContent=error.message;}
      finally {busy=false;buttons.forEach(b=>b.disabled=false);}
    });
  });
})();
