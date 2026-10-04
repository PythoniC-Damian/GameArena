(() => {
  let activeDialog, previousFocus;
  const main = document.querySelector('main');
  const bankSelect = document.getElementById('withdrawBank');
  async function loadBanks() {
    const status = document.getElementById('bankStatus'), retry = document.getElementById('retryBanks');
    status.textContent = 'Loading supported banks…'; retry.hidden = true;
    bankSelect.disabled = true;
    try {
      const response = await fetch(bankSelect.dataset.url, {headers:{Accept:'application/json'},cache:'no-store',signal: AbortSignal.timeout(30000)});
      if (response.redirected || response.status === 401) throw new Error('Your session has expired. Log in again to load banks.');
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The bank service is temporarily unavailable. Please try again.');
      const data = await response.json();
      if (!response.ok || !data.banks?.length) throw new Error(data.message || 'No banks are available. Please try again.');
      bankSelect.replaceChildren(new Option('Choose your bank', ''));
      data.banks.forEach(bank => bankSelect.add(new Option(bank.name, bank.code)));
      bankSelect.disabled = false; status.textContent = '';
    } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'Loading banks timed out. Please try again.' : error.message; retry.hidden = false; }
  }
  document.getElementById('retryBanks').addEventListener('click', loadBanks);
  function open(id) {
    previousFocus = document.activeElement;
    activeDialog = document.getElementById(id);
    activeDialog.classList.remove('hidden'); activeDialog.classList.add('flex');
    main.inert = true;
    activeDialog.querySelector('input:not([type="hidden"])').focus();
    if (id === 'withdrawModal' && bankSelect.options.length < 2) loadBanks();
  }
  function close() {
    if (!activeDialog) return;
    activeDialog.classList.add('hidden'); activeDialog.classList.remove('flex');
    activeDialog = null; main.inert = false; previousFocus?.focus();
  }
  window.openAddMoneyModal = () => open('addMoneyModal');
  window.openWithdrawModal = () => open('withdrawModal');
  window.closeAddMoneyModal = window.closeWithdrawModal = close;
  document.addEventListener('keydown', event => {
    if (!activeDialog) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const controls = [...activeDialog.querySelectorAll('button, select, input:not([type="hidden"])')].filter(el => !el.disabled && !el.hidden);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  document.querySelectorAll('.ga-dialog').forEach(el => el.addEventListener('click', event => { if (event.target === el) close(); }));
  for (const [id, field, withdrawal] of [['addMoneyForm', 'depositAmount', false], ['withdrawForm', 'withdrawAmount', true]]) {
    const form = document.getElementById(id);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (form.dataset.busy || !form.reportValidity()) return;
      const amount = Number(document.getElementById(field).value);
      const status = form.querySelector('[data-form-status]');
      if (!Number.isSafeInteger(amount) || amount < 100) { status.textContent = 'Enter a whole amount of at least ₦100.'; return; }
      const body = { amount };
      if (withdrawal) {
        if (bankSelect.disabled || !bankSelect.value) { status.textContent = 'Choose a supported bank before requesting a withdrawal.'; return; }
        body.bank_name = bankSelect.selectedOptions[0].textContent;
        body.bank_code = bankSelect.value;
        body.account_number = document.getElementById('accountNumber').value.trim();
        // Retain this key on an unknown outcome, including a lost response.
        // The backend owns idempotency and all accounting decisions.
        body.idempotency_key = sessionStorage.getItem('gamearena-withdrawal-idempotency-key') || crypto.randomUUID().replaceAll('-', '');
        sessionStorage.setItem('gamearena-withdrawal-idempotency-key', body.idempotency_key);
      }
      const button = form.querySelector('button[type="submit"]');
      form.dataset.busy = 'true'; button.disabled = true; button.setAttribute('aria-busy', 'true');
      status.textContent = withdrawal ? 'Submitting withdrawal…' : 'Opening secure checkout…';
      try {
        const response = await fetch(form.dataset.url, { method: 'POST', headers: {'Accept':'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': form.csrf_token.value}, body: JSON.stringify(body), signal: AbortSignal.timeout(30000) });
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The service is unavailable. Check your session and transaction history before retrying.');
        const data = await response.json();
        if (withdrawal && data.withdrawal_status === 'failed') sessionStorage.removeItem('gamearena-withdrawal-idempotency-key');
        if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Unable to complete this request.');
        if (withdrawal) {
          sessionStorage.removeItem('gamearena-withdrawal-idempotency-key'); status.textContent = data.message || 'Withdrawal submitted.'; window.location.reload();
        } else {
          const url = new URL(data.authorization_url);
          if (url.protocol !== 'https:') throw new Error('Checkout could not be opened. Please try again.');
          window.location.assign(url.href);
        }
      } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'The response timed out. Check transaction history before retrying.' : error.message; }
      finally { delete form.dataset.busy; button.disabled = false; button.removeAttribute('aria-busy'); }
    });
  }
})();
