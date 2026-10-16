(() => {
  let activeDialog, previousFocus;
  const main = document.querySelector('main');
  const bankSelect = document.getElementById('withdrawBank');
  const accountInput = document.getElementById('accountNumber');
  const withdrawForm = document.getElementById('withdrawForm');
  const withdrawButton = withdrawForm.querySelector('button[type="submit"]');
  const accountStatus = document.getElementById('resolvedAccountName');
  const retryAccount = document.getElementById('retryAccount');
  let verifiedAccount = null, resolveTimer, resolveController, resolveSequence = 0;
  function resetAccount() {
    clearTimeout(resolveTimer); resolveController?.abort(); resolveSequence++;
    verifiedAccount = null; withdrawButton.disabled = true; retryAccount.hidden = true;
    accountStatus.textContent = window.gaT('Select your bank and enter your account number.');
  }
  async function resolveAccount() {
    resetAccount();
    const number = accountInput.value.trim(), bank = bankSelect.value;
    if (!bank || !/^[0-9]{10}$/.test(number)) return;
    const sequence = resolveSequence;
    const controller = new AbortController();
    resolveController = controller;
    const timeout = setTimeout(() => controller.abort(), 20000);
    accountStatus.textContent = window.gaT('Verifying account holder…');
    try {
      const response = await fetch(withdrawForm.dataset.resolveUrl, {method:'POST', headers:{Accept:'application/json','Content-Type':'application/json','X-CSRFToken':withdrawForm.csrf_token.value},body:JSON.stringify({bank_code:bank,account_number:number}),signal:controller.signal,cache:'no-store'});
      if (response.redirected || response.status === 401) throw new Error(window.gaT('Your session expired. Log in again.'));
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Account verification is unavailable. Please retry.');
      const data = await response.json();
      if (!response.ok || !data.account_name || !data.verification_token) throw new Error(data.message || 'Unable to verify this account.');
      if (sequence !== resolveSequence || bank !== bankSelect.value || number !== accountInput.value.trim()) return;
      verifiedAccount = {bank,number,token:data.verification_token,expires:Date.now()+290000};
      accountStatus.textContent = data.account_name + ' · ' + data.bank_name;
      withdrawButton.disabled = false;
    } catch (error) {
      if (sequence !== resolveSequence) return;
      accountStatus.textContent = error.name === 'AbortError' ? 'Verification timed out. Please retry.' : error.message;
      retryAccount.hidden = false;
    } finally { clearTimeout(timeout); }
  }
  function accountChanged() { resetAccount(); resolveTimer = setTimeout(resolveAccount, 400); }
  bankSelect.addEventListener('change', accountChanged);
  accountInput.addEventListener('input', accountChanged);
  retryAccount.addEventListener('click', resolveAccount);
  const balance = document.getElementById('walletBalance'), toggle = document.getElementById('toggleBalance');
  if (balance && toggle) {
    const amount = balance.textContent, equivalent = document.getElementById('walletNairaEquivalent'), equivalentText = equivalent?.textContent; let hidden = false;
    try { hidden = localStorage.getItem('gamearenaHideBalance') === '1'; } catch (_) {}
    function drawBalance() {
      document.querySelectorAll('[data-wallet-balance]').forEach(el=>{el.dataset.balanceHidden=String(hidden);el.textContent=hidden?'****':window.GameArenaWalletCurrency?.format(Number(el.dataset.moneyNaira))||el.dataset.moneyNaira+' GP';});
      balance.dataset.balanceHidden=String(hidden);
      balance.textContent = hidden ? '****' : (window.GameArenaWalletCurrency?.format(Number(balance.dataset.moneyNaira)) || amount); if(equivalent) equivalent.textContent=hidden?'****':equivalentText;
      window.GameArenaWalletCurrency?.refresh();
      toggle.setAttribute('aria-label', hidden ? 'Show balance' : 'Hide balance');
      toggle.setAttribute('aria-pressed', String(hidden));
      toggle.querySelector('[data-eye-open]').hidden = hidden;
      toggle.querySelector('[data-eye-closed]').hidden = !hidden;
    }
    toggle.addEventListener('click', () => {hidden = !hidden; drawBalance(); try {localStorage.setItem('gamearenaHideBalance',hidden?'1':'0');} catch (_) {}});
    drawBalance();
  }
  const naira = value => '₦' + (value / 100).toLocaleString('en-NG',{minimumFractionDigits:value % 100 ? 2 : 0,maximumFractionDigits:2});
  const gpInput = document.getElementById('depositGpAmount'), depositInput = document.getElementById('depositAmount');
  function gpToNaira(value) { if (!/^[0-9]{1,10}$/.test(String(value).trim())) return NaN; return Number(value); }
  depositInput.addEventListener('input',()=>{gpInput.value=depositInput.value ? Number(depositInput.value) : '';document.getElementById('depositConversion').textContent=depositInput.value ? window.gaT('You receive {gp} GP for {amount}.',{gp:gpInput.value,amount:naira(Number(depositInput.value)*100)}) : '1 GP = ₦1';});
  gpInput.addEventListener('input',()=>{const amount=gpToNaira(gpInput.value);depositInput.value=Number.isSafeInteger(amount) ? amount : '';document.getElementById('depositConversion').textContent=Number.isSafeInteger(amount) ? window.gaT('You receive {gp} GP for {amount}.',{gp:gpInput.value,amount:naira(amount*100)}) : window.gaT('Enter a whole GP amount.');});
  document.getElementById('withdrawAmount').addEventListener('input',()=>{
    document.getElementById('confirmWithdrawalFee').checked=false;
    const amount=gpToNaira(document.getElementById('withdrawAmount').value),gross=Number.isSafeInteger(amount) ? amount*100 : 0,fee=Math.min(Number.isSafeInteger(amount)?amount:0,20000);
    document.getElementById('withdrawGross').textContent=naira(gross);document.getElementById('withdrawFee').textContent=naira(fee);document.getElementById('withdrawPayout').textContent=naira(gross-fee);
    [['withdrawGross',gross],['withdrawFee',fee],['withdrawPayout',gross-fee]].forEach(([id,value])=>document.getElementById(id).dataset.moneyKobo=String(value));
    document.getElementById('withdrawPayoutSettlement').textContent=naira(gross-fee);window.GameArenaWalletCurrency?.refresh();
  });
  async function loadBanks() {
    const status = document.getElementById('bankStatus'), retry = document.getElementById('retryBanks');
    resetAccount(); status.textContent = 'Loading supported banks…'; retry.hidden = true;
    bankSelect.disabled = true;
    try {
      const response = await fetch(bankSelect.dataset.url, {headers:{Accept:'application/json'},cache:'no-store',signal: AbortSignal.timeout(30000)});
      if (response.redirected || response.status === 401) throw new Error('Your session has expired. Log in again to load banks.');
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The bank service is temporarily unavailable. Please try again.');
      const data = await response.json();
      if (!response.ok || !data.banks?.length) throw new Error(data.message || 'No banks are available. Please try again.');
      bankSelect.replaceChildren(new Option(window.gaT('Choose your bank'), ''));
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
  window.openWithdrawModal = (source='purchased') => { document.getElementById('withdrawSource').value=source; open('withdrawModal'); };
  document.getElementById('withdrawSource').addEventListener('change',()=>{document.getElementById('confirmWithdrawalFee').checked=false;});
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
      const amount = withdrawal ? gpToNaira(document.getElementById(field).value) : Number(document.getElementById(field).value);
      const status = form.querySelector('[data-form-status]');
      if (!Number.isSafeInteger(amount) || amount < 100) { status.textContent = window.gaT('Enter a whole amount of at least ₦100.'); return; }
      const body = withdrawal ? {amount_gp:document.getElementById(field).value,fee_policy:'gp-withdrawal-v1',fee_kobo:Math.min(amount,20000),fee_consent:document.getElementById('confirmWithdrawalFee').checked} : {amount_gp:String(amount)};
      if (withdrawal) {
        if (bankSelect.disabled || !bankSelect.value) { status.textContent = 'Choose a supported bank before requesting a withdrawal.'; return; }
        if (!verifiedAccount || verifiedAccount.bank !== bankSelect.value || verifiedAccount.number !== accountInput.value.trim() || verifiedAccount.expires < Date.now()) { status.textContent = 'Verify your account holder name before withdrawing.'; resolveAccount(); return; }
        body.wallet_source = document.getElementById('withdrawSource').value;
        body.verification_token = verifiedAccount.token;
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
        if (!response.ok || data.status !== 'success') {
          status.textContent = data.message || 'Unable to complete this request.';
          if (withdrawal && data.receipt_url?.startsWith('/wallet/transactions/')) {
            const link = document.createElement('a'); link.href = data.receipt_url; link.textContent = ' View receipt'; status.append(link);
          }
          return;
        }
        if (withdrawal) {
          sessionStorage.removeItem('gamearena-withdrawal-idempotency-key'); status.textContent = data.message || 'Withdrawal submitted.'; window.location.assign(data.receipt_url);
        } else {
          const url = new URL(data.authorization_url);
          if (url.protocol !== 'https:') throw new Error('Checkout could not be opened. Please try again.');
          window.location.assign(url.href);
        }
      } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'The response timed out. Check transaction history before retrying.' : error.message; }
      finally { delete form.dataset.busy; button.disabled = withdrawal && (!verifiedAccount || verifiedAccount.expires < Date.now()); button.removeAttribute('aria-busy'); }
    });
  }
})();

(() => {
  const track=document.querySelector('.ga-wallet-track');if(!track)return;
  const cards=[...track.querySelectorAll('[data-wallet-card]')],dots=[...document.querySelectorAll('[data-wallet-index]')];let active=0;
  function go(index){active=Math.max(0,Math.min(cards.length-1,index));track.scrollTo({left:track.scrollLeft+cards[active].getBoundingClientRect().left-track.getBoundingClientRect().left,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
  dots.forEach((dot,i)=>dot.addEventListener('click',()=>go(i)));
  document.querySelectorAll('[data-wallet-step]').forEach(button=>button.addEventListener('click',()=>go(active+Number(button.dataset.walletStep))));
  track.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();go(active+(e.key==='ArrowRight'?1:-1));}});
  const observer=new IntersectionObserver(entries=>{entries.forEach(entry=>{if(entry.intersectionRatio>.6){active=cards.indexOf(entry.target);dots.forEach((dot,i)=>dot.setAttribute('aria-current',String(i===active)));document.querySelectorAll('[data-wallet-step]').forEach(button=>button.disabled=Number(button.dataset.walletStep)<0?active===0:active===cards.length-1);}});},{root:track,threshold:.6});cards.forEach(card=>observer.observe(card));
})();
