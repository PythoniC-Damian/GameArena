document.getElementById('paymentForm').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector('button'), status = document.getElementById('paymentStatus');
  if (button.disabled) return;
  button.disabled = true; button.setAttribute('aria-busy', 'true'); status.textContent = 'Opening secure checkout…';
  try {
    const response = await fetch(form.dataset.url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.csrf_token.value}, signal: AbortSignal.timeout(30000)});
    const data = await response.json();
    if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Unable to open checkout.');
    const url = new URL(data.authorization_url);
    if (url.protocol !== 'https:') throw new Error('Checkout could not be opened. Please try again.');
    window.location.assign(url.href);
  } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'The response timed out. Check your entry before trying again.' : error.message; }
  finally { button.disabled = false; button.removeAttribute('aria-busy'); }
});
