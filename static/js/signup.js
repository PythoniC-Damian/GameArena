(() => {
  const form=document.querySelector('[data-signup-form]');if(!form)return;
  const emailFields=[...form.querySelectorAll('[data-email-fields] input')];
  const status=form.querySelector('[data-google-status]'),t=window.gaT||((text)=>text);
  form.querySelector('[data-google-signup]').addEventListener('click',event=>{
    // Google needs age and consent, but does not use the email/password inputs.
    const shared=[form.elements.date_of_birth,form.elements.accept_terms];
    if(!shared.every(input=>input.checkValidity())){
      event.preventDefault();status.hidden=false;status.textContent=t('Enter your date of birth and accept the terms below to continue with Google.');
      shared.find(input=>!input.checkValidity()).reportValidity();return;
    }
    status.hidden=false;status.textContent=t('Connecting to Google…');
    emailFields.forEach(input=>input.disabled=true);
  });
  window.addEventListener('pageshow',()=>{emailFields.forEach(input=>input.disabled=false);status.hidden=true;status.textContent='';});
})();
