document.getElementById('paymentForm').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector('button'), status = document.getElementById('paymentStatus');
  if (button.disabled) return;
  button.disabled = true; button.setAttribute('aria-busy', 'true'); status.textContent = 'Opening secure checkout…';
  try {
    const response = await fetch(form.dataset.url, {method:'POST',headers:{Accept:'application/json','X-CSRFToken':form.csrf_token.value},body:new FormData(form),signal:AbortSignal.timeout(30000)});
    if (response.redirected || response.status === 401) throw new Error('Your session has expired. Log in again before paying.');
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Checkout is temporarily unavailable. Refresh this page and try again.');
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('Checkout returned an invalid response. Please try again shortly.'); }
    if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Unable to open checkout.');
    let url;
    try { url = new URL(data.authorization_url); } catch (_) { throw new Error('Checkout did not return a valid payment link. Please try again.'); }
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) throw new Error('Checkout did not return a secure payment link. Please try again.');
    window.location.assign(url.href);
  } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'The response timed out. Check your entry before trying again.' : error.message; }
  finally { button.disabled = false; button.removeAttribute('aria-busy'); }
});
