(() => {
  'use strict';
  const controls=document.querySelector('[data-wallet-currency]');
  if(!controls)return;
  const selector=document.getElementById('walletDisplayCurrency'),status=document.getElementById('walletRateStatus'),retry=controls.querySelector('[data-retry-rates]');
  const t=window.gaT||((text)=>text),locale=document.documentElement.lang||'en';
  const state={currency:'GP',snapshot:null};
  let saving=0,refreshing=false,quoteSequence=0,saveQueue=Promise.resolve();
  const csrf=document.querySelector('meta[name="csrf-token"]').content;
  function format(naira,currency=state.currency){
    if(currency==='GP')return Number(naira).toLocaleString(locale,{maximumFractionDigits:2})+' GP';
    const rate=currency==='NGN'?1:Number(state.snapshot?.rates[currency]);
    if(!Number.isFinite(rate)||rate<=0)return Number(naira).toLocaleString(locale)+' GP';
    const value=Number(naira)*rate;
    return new Intl.NumberFormat(locale,{style:'currency',currency}).format(value);
  }
  function refresh(){
    document.querySelectorAll('[data-money-naira],[data-money-kobo]').forEach(el=>{
      if(el.dataset.balanceHidden==='true'){el.textContent='****';return;}
      const value=el.hasAttribute('data-money-kobo')?Number(el.dataset.moneyKobo)/100:Number(el.dataset.moneyNaira);
      el.textContent=(el.dataset.moneySign||'')+format(value);
    });
    const equivalent=document.getElementById('walletNairaEquivalent'),balance=document.getElementById('walletBalance');
    if(equivalent&&balance){equivalent.hidden=state.currency==='GP';equivalent.textContent=balance.dataset.balanceHidden==='true'?'****':t('Wallet value')+': '+Number(balance.dataset.moneyNaira).toLocaleString(locale)+' GP';}
    const output=document.querySelector('[data-match-quote-result]');
    if(output?.dataset.quoteGp)output.textContent=output.dataset.quoteGp+' GP · '+format(Number(output.dataset.quoteGp))+'. '+t('Quote valid for 5 minutes. Rounded up to whole GP.');
  }
  function describe(){
    if(!state.snapshot){status.textContent=t('Rates unavailable. GP and NGN remain available.');return;}
    const source=new Date(state.snapshot.source_updated_at*1000).toLocaleString(locale);
    status.textContent=(state.snapshot.stale?t('Rates are stale. Match quotes are paused.')+' ':t('Indicative rates.'))+' '+t('Source updated')+': '+source+'. '+t('Checked hourly. Bank payments settle in NGN.');
  }
  function save(currency){
    const sequence=++saving;
    saveQueue=saveQueue.then(async()=>{
      try{
        const response=await fetch(controls.dataset.saveUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf,Accept:'application/json'},body:JSON.stringify({currency}),signal:AbortSignal.timeout(15000)});
        if(!response.ok)throw Error();
      }catch(_){if(sequence===saving)status.textContent=t('Currency changed for this visit. Could not save your preference.');}
    });
  }
  function option(code,meta){
    let name=meta?.name||code;
    try{name=new Intl.DisplayNames([locale],{type:'currency'}).of(code)||name;}catch(_){}
    return new Option(code+' · '+name,code);
  }
  async function loadRates(){
    if(refreshing)return;refreshing=true;retry.hidden=true;
    try{
      const response=await fetch(controls.dataset.ratesUrl,{headers:{Accept:'application/json'},cache:'no-store',signal:AbortSignal.timeout(15000)});
      if(!response.ok||response.redirected)throw Error();
      const snapshot=await response.json();
      if(snapshot.base!=='NGN'||!snapshot.rates?.USD||!snapshot.currencies)throw Error();
      state.snapshot=snapshot;
      selector.replaceChildren(new Option('GP · GameArena','GP'));
      const ordered=['NGN','USD','GBP','EUR',...Object.keys(snapshot.currencies).filter(c=>!['NGN','USD','GBP','EUR'].includes(c)).sort()];
      ordered.forEach(code=>{if(snapshot.rates[code])selector.add(option(code,snapshot.currencies[code]));});
      const wanted=state.currency==='GP'?controls.dataset.defaultCurrency:state.currency;
      state.currency=wanted==='GP'||snapshot.rates[wanted]?wanted:'GP';selector.value=state.currency;
      const quoteSelect=document.querySelector('[data-match-quote-currency]');
      if(quoteSelect){const previous=quoteSelect.value;quoteSelect.replaceChildren(...Array.from(selector.options).map(el=>new Option(el.text,el.value)));quoteSelect.value=previous||'USD';}
      describe();refresh();
    }catch(_){
      if(state.snapshot)state.snapshot.stale=true;
      if(!state.snapshot&&controls.dataset.defaultCurrency==='NGN'){state.currency='NGN';selector.value='NGN';}
      describe();retry.hidden=false;refresh();
    }finally{refreshing=false;}
  }
  selector.addEventListener('change',()=>{state.currency=selector.value;controls.dataset.defaultCurrency=state.currency;refresh();describe();save(state.currency);});
  retry.addEventListener('click',loadRates);
  window.GameArenaWalletCurrency={state,format,refresh};
  const quoteForm=document.querySelector('[data-match-value-quote]');
  if(quoteForm){
    const output=quoteForm.querySelector('[data-match-quote-result]');
    quoteForm.addEventListener('input',()=>{quoteSequence++;delete output.dataset.quoteGp;output.textContent='';});
    quoteForm.addEventListener('submit',async event=>{
      event.preventDefault();const sequence=++quoteSequence,button=quoteForm.querySelector('button');button.disabled=true;output.textContent=t('Calculating…');
      try{
        const response=await fetch(quoteForm.action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf,Accept:'application/json'},body:JSON.stringify({amount:quoteForm.elements.amount.value,currency:quoteForm.elements.currency.value}),signal:AbortSignal.timeout(15000)});
        const data=await response.json();if(sequence!==quoteSequence)return;
        if(!response.ok||!Number.isSafeInteger(data.amount_gp))throw Error(data.error||t('Could not calculate a quote.'));
        output.dataset.quoteGp=String(data.amount_gp);refresh();
        setTimeout(()=>{if(sequence===quoteSequence){delete output.dataset.quoteGp;output.textContent=t('Quote expired. Calculate again.');}},Math.max(0,data.expires_at*1000-Date.now()));
      }catch(error){if(sequence===quoteSequence)output.textContent=error.message||t('Could not calculate a quote.');}
      finally{button.disabled=false;}
    });
  }
  refresh();loadRates();
  setInterval(loadRates,3600000);
  setInterval(()=>{if(state.snapshot&&Date.now()/1000-state.snapshot.source_updated_at>7200){state.snapshot.stale=true;describe();}},60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.snapshot&&Date.now()/1000>=state.snapshot.refresh_after)loadRates();});
})();
