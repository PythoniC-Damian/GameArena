/* File checks and local previews; the server independently decodes every upload. */
(() => {
  const form = document.querySelector('[data-organizer-artwork]');
  if (!form) return;
  const fields = [...form.querySelectorAll('input[type="file"][name="images"]')];
  const feedback = form.querySelector('[data-upload-feedback]');
  const urls = new Map();
  function validate() {
    const picked = fields.filter(field => field.files.length);
    let error = '';
    if (picked.length && picked.length !== 3) error = gaT('Choose all 3 images to replace the carousel.');
    if (picked.some(field => field.files[0].size > 1024 * 1024)) error = gaT('Each tournament image must be 1 MB or smaller.');
    fields.forEach(field => field.setCustomValidity(error));
    feedback.textContent = error;
  }
  fields.forEach(field => field.addEventListener('change', () => {
    const preview = field.parentElement.querySelector('[data-upload-preview]');
    if (urls.has(field)) URL.revokeObjectURL(urls.get(field));
    const file = field.files[0];
    preview.hidden = !file;
    if (file) { const url = URL.createObjectURL(file); urls.set(field, url); preview.src = url; }
    else preview.removeAttribute('src');
    validate();
  }));
})();
