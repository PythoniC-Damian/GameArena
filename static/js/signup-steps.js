(() => {
  const form=document.querySelector('[data-signup-steps]');if(!form)return;
  const steps=[...form.querySelectorAll('[data-signup-step]')],status=document.querySelector('[data-step-status]');let current=0;
  const show=index=>{current=index;steps.forEach((step,i)=>step.hidden=i!==index);status.textContent=(window.gaT?.('Step {number} of 3')||'Step {number} of 3').replace('{number}',index+1);steps[index].querySelector('input:not([type=hidden]),button')?.focus();};
  const valid=()=>[...steps[current].querySelectorAll('input')].every(input=>input.reportValidity());
  form.querySelectorAll('[data-signup-next]').forEach(button=>button.addEventListener('click',()=>{if(valid())show(current+1);}));
  form.querySelectorAll('[data-signup-back]').forEach(button=>button.addEventListener('click',()=>show(current-1)));
  form.addEventListener('keydown',event=>{if(event.key==='Enter' && current<2 && event.target.tagName==='INPUT'){event.preventDefault();if(valid())show(current+1);}});
  status.hidden=false;form.querySelectorAll('[data-signup-next],[data-signup-back]').forEach(item=>item.hidden=false);
  form.addEventListener('invalid',event=>{const index=steps.findIndex(step=>step.contains(event.target));if(index>=0)show(index);},true);
  form.querySelector('[data-google-signup]').addEventListener('click',event=>{
    if(!valid()){event.preventDefault();return;}
    form.querySelectorAll('[data-email-fields] input').forEach(input=>input.disabled=true);
  });
  form.addEventListener('submit',event=>{
    if(event.submitter?.hasAttribute('data-google-signup'))return;
    if(current<2){event.preventDefault();if(valid())show(current+1);}
  });
  window.addEventListener('pageshow',()=>form.querySelectorAll('[data-email-fields] input').forEach(input=>input.disabled=false));
  const invalid=steps.findIndex(step=>step.querySelector('[data-field-error]'));
  show(invalid<0?0:invalid);
})();
