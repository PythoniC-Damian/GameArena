/* Suggestions and rendering use text nodes; message text is never inserted as HTML. */
(() => {
  const tokenPattern = /(?<![A-Za-z0-9_@])@([A-Za-z0-9_]{1,150})(?![A-Za-z0-9_])/g;
  function check(text) {
    const tokens = [...text.matchAll(tokenPattern)];
    if (tokens.length > 5) return 'Use at most 5 individual mentions per message.';
    if (tokens.some(match => ['all','everyone','here'].includes(match[1].toLowerCase()))) return 'Mention individual players; group mentions are unavailable.';
    return '';
  }
  function activeToken(value, caret) {
    const match = value.slice(0, caret).match(/(?:^|[^A-Za-z0-9_@])@([A-Za-z0-9_]{0,150})$/);
    return match ? {start:caret-match[1].length-1,end:caret,query:match[1]} : null;
  }
  if (typeof module !== 'undefined' && module.exports) {module.exports={check,activeToken};return;}
  const main = document.querySelector('.ga-chat-shell'), input = document.getElementById('chatInput');
  if (!main || main.dataset.partnerId || !input) return;
  const box = document.getElementById('mentionSuggestions');
  const status = document.getElementById('chatStatus');
  let timer, controller, generation=0, matches=[], active=-1, token=null;
  function hide() {
    generation++; clearTimeout(timer); controller?.abort(); box.hidden=true; box.replaceChildren();
    matches=[]; active=-1; input.setAttribute('aria-expanded','false'); input.removeAttribute('aria-activedescendant');
  }
  function select(index) {
    active=(index+matches.length)%matches.length;
    [...box.children].forEach((node,i)=>node.setAttribute('aria-selected',String(i===active)));
    input.setAttribute('aria-activedescendant',`mention-option-${active}`);
    box.children[active]?.scrollIntoView({block:'nearest'});
  }
  function choose(index) {
    const user=matches[index]; if (!user || !token) return;
    const tail=input.value.slice(token.end).replace(/^[A-Za-z0-9_]*/, '');
    const value=input.value.slice(0,token.start)+'@'+user.username+' '+tail;
    const error=check(value); if (error) {status.textContent=error;hide();return;}
    const caret=token.start+user.username.length+2;
    input.value=value; hide(); input.focus(); input.setSelectionRange(caret,caret);
    input.dispatchEvent(new Event('input',{bubbles:true}));
  }
  async function lookup() {
    const current=activeToken(input.value,input.selectionStart);
    hide(); token=current;
    if (!current) return;
    const serial=generation;
    controller=new AbortController();
    try {
      const url=new URL(main.dataset.mentionsUrl,location.origin); url.searchParams.set('q',current.query);
      const response=await fetch(url,{cache:'no-store',signal:controller.signal});
      if (!response.ok) return;
      const data=await response.json(); if (generation!==serial || input.selectionStart!==current.end) return;
      matches=data.users || []; if (!matches.length) return;
      matches.forEach((user,i)=>{
        const option=document.createElement('button');option.type='button';option.id=`mention-option-${i}`;
        option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.textContent='@'+user.username;
        option.addEventListener('pointerdown',event=>event.preventDefault());option.addEventListener('click',()=>choose(i));box.append(option);
      });
      box.hidden=false; input.setAttribute('aria-expanded','true'); select(0);
    } catch (_) { /* Keep typing available if lookup is interrupted. */ }
  }
  input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');
  input.setAttribute('aria-controls','mentionSuggestions');input.setAttribute('aria-expanded','false');
  function schedule() {hide();timer=setTimeout(lookup,180);}
  input.addEventListener('input',schedule); input.addEventListener('click',schedule);
  input.addEventListener('keydown',event=>{
    if (box.hidden) return;
    if (['ArrowDown','ArrowUp','Enter','Escape','Tab'].includes(event.key)) {
      if (event.key==='Escape' || event.key==='Tab') {hide();if(event.key==='Escape')event.preventDefault();return;}
      event.preventDefault();
      if(event.key==='Enter')choose(active);else select(active+(event.key==='ArrowDown'?1:-1));
    }
  });
  input.addEventListener('keyup',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key))schedule();});
  input.addEventListener('blur',()=>setTimeout(hide,150));
  function render(element,text,mentions) {
    element.replaceChildren();const chars=Array.from(text);let cursor=0;
    for(const item of (mentions||[]).slice(0,5)) {
      if(!Number.isInteger(item.start)||!Number.isInteger(item.end)||!Number.isInteger(item.id)||item.start<cursor||item.end>chars.length||item.end<=item.start)continue;
      const label=chars.slice(item.start,item.end).join('');if(!/^@[A-Za-z0-9_]+$/.test(label))continue;
      element.append(document.createTextNode(chars.slice(cursor,item.start).join('')));
      const link=document.createElement('a');link.className='ga-chat-mention';link.href='/players/'+item.id;link.textContent=label;element.append(link);cursor=item.end;
    }
    element.append(document.createTextNode(chars.slice(cursor).join('')));
  }
  window.gaChatMentions={check,render,clear:hide};
})();
