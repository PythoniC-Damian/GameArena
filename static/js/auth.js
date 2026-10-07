(() => {
  'use strict';
  document.querySelectorAll('form[data-auth-form]').forEach(form => {
    const button = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!button) return;
    const label = button.tagName === 'INPUT' ? button.value : button.textContent;
    const status = document.createElement('p');
    status.className = 'mt-3 text-sm text-slate-400';
    status.setAttribute('role', 'status');
    button.after(status);
    let submitting = false;
    const until = Date.now() + Number(form.dataset.cooldown || 0) * 1000;
    function update() {
      const seconds = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      button.disabled = submitting || seconds > 0;
      status.textContent = seconds ? `Please wait ${seconds} seconds before trying again.` : '';
      const text = submitting ? 'Please wait…' : label;
      if (button.tagName === 'INPUT') button.value = text;
      else button.textContent = text;
      return seconds;
    }
    update();
    const timer = setInterval(() => { if (!update()) clearInterval(timer); }, 1000);
    form.addEventListener('submit', event => {
      if (submitting || Date.now() < until) { event.preventDefault(); return; }
      if (!form.checkValidity()) return;
      submitting = true;
      update();
    });
    window.addEventListener('pageshow', () => { submitting = false; update(); });
  });
})();
