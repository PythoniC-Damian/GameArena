(() => {
  const start = () => {
    const state = window.gaPrivacy || {decided:false,analytics:false};
    const panel = document.createElement('section');
    panel.className = 'ga-cookie-panel'; panel.setAttribute('aria-label','Cookie choices');
    panel.innerHTML = '<button type="button" class="ga-cookie-close" aria-label="Close privacy notice">×</button><strong>Your privacy choices</strong><p>Essential cookies support sign-in and security. Optional usage analytics stay off unless you accept.</p><div><button class="ga-button" data-choice="reject">Reject optional analytics</button><button class="ga-button" data-choice="accept">Accept optional analytics</button></div><a href="/privacy/choices">Details and change choices</a><p role="status"></p>';
    let dismissed=false;try{dismissed=sessionStorage.getItem('gaPrivacyDismissed')==='1';}catch(_){}
    panel.hidden = state.decided || dismissed; document.body.append(panel);
    panel.querySelector('.ga-cookie-close').addEventListener('click',()=>{panel.hidden=true;try{sessionStorage.setItem('gaPrivacyDismissed','1');}catch(_){};});
    document.querySelectorAll('[data-privacy-choices]').forEach(link => link.addEventListener('click', event => {event.preventDefault();panel.hidden=false;panel.querySelector('button').focus();}));
    panel.querySelectorAll('[data-choice]').forEach(button => button.addEventListener('click', async () => {
      const buttons = panel.querySelectorAll('button'); buttons.forEach(item=>item.disabled=true);
      try {
        const response = await fetch('/privacy/choices',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({choice:button.dataset.choice})});
        if(!response.ok) throw new Error();
        const result=await response.json();window.gaPrivacy={decided:true,analytics:result.analytics};panel.hidden=true;
      } catch (_) {panel.querySelector('[role="status"]').textContent='Could not save. Use the details link or try again.';}
      finally {buttons.forEach(item=>item.disabled=false);}
    }));
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start);else start();
})();
