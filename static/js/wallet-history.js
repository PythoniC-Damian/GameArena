document.querySelectorAll('.ga-history-filters select').forEach(select => select.addEventListener('change', () => select.form.requestSubmit()));
