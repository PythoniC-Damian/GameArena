(() => {
  'use strict';
  document.querySelectorAll('[data-password-target]').forEach(toggle => {
    const input = document.getElementById(toggle.dataset.passwordTarget);
    if (!input) return;
    toggle.addEventListener('click', () => {
      const visible = input.type === 'password'; input.type = visible ? 'text' : 'password';
      toggle.setAttribute('aria-pressed', String(visible)); toggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
      toggle.querySelector('[data-password-show]').hidden = visible;
      toggle.querySelector('[data-password-hide]').hidden = !visible;
    });
  });
  document.querySelectorAll('form[data-auth-form]').forEach(form => {
    const button = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!button) return;
    const label = button.tagName === 'INPUT' ? button.value : button.textContent;
    const status = document.createElement('p');
    status.className = 'mt-3 text-sm text-slate-400';
    status.setAttribute('role', 'status');
    button.after(status);
    const agreement = form.querySelector('[data-required-agreement]');
    const resend = form.hasAttribute('data-resend-code');
    let submitting = false;
    const until = Date.now() + Number(form.dataset.cooldown || 0) * 1000;
    function update() {
      const seconds = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      button.disabled = submitting || seconds > 0 || Boolean(agreement && !agreement.checked);
      const countdown = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
      status.textContent = seconds ? (resend ? `You can request another code in ${countdown}.` : `Please wait ${seconds} seconds before trying again.`) : '';
      const text = submitting ? 'Please wait…' : resend && seconds ? `Resend in ${countdown}` : label;
      if (button.tagName === 'INPUT') button.value = text;
      else button.textContent = text;
      return seconds;
    }
    if (agreement) agreement.addEventListener('change', update);
    update();
    const timer = setInterval(() => { if (!update()) clearInterval(timer); }, 1000);
    form.addEventListener('submit', event => {
      if (submitting || Date.now() < until || (agreement && !agreement.checked)) { event.preventDefault(); return; }
      if (!form.checkValidity()) return;
      submitting = true;
      update();
    });
    window.addEventListener('pageshow', () => { submitting = false; update(); });
  });
})();
