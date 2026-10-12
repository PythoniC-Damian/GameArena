(() => {
  const form = document.querySelector('[data-live-search]');
  if (!form) return;
  const input = form.querySelector('[name=q]'), results = document.querySelector('[data-search-results]'), status = document.querySelector('[data-search-status]');
  let timer, controller, version = 0;
  function change() {
    clearTimeout(timer); controller?.abort(); const current = ++version;
    const query = input.value.trim();
    if (query.length < 2) { results.textContent = 'Enter at least two characters to search.'; status.textContent = ''; results.removeAttribute('aria-busy'); return; }
    status.textContent = 'Searching...'; results.setAttribute('aria-busy','true');
    timer = setTimeout(async () => {
      controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const url = new URL(form.action, location.href); url.searchParams.set('q',query); url.searchParams.set('live','1');
        const response = await fetch(url, {signal:controller.signal, cache:'no-store',headers:{Accept:'application/json'}});
        if (!response.ok) throw new Error('Could not search');
        const data = await response.json();
        if (current !== version) return;
        results.innerHTML = data.html; status.textContent = 'Results updated.';
        const display = new URL(location.href); display.searchParams.set('q',query); history.replaceState(null,'',display);
      } catch (_) { if (current === version) status.textContent = 'Could not update results. Try again or press Search.'; }
      finally { clearTimeout(timeout); if (current === version) results.removeAttribute('aria-busy'); }
    }, 250);
  }
  input.addEventListener('input', event => { if (!event.isComposing) change(); });
  input.addEventListener('compositionend', change);
  form.addEventListener('submit', event => { event.preventDefault(); change(); });
})();
