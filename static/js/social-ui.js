(() => {
 const t=window.gaT||((s)=>s),csrf=()=>document.querySelector('meta[name="csrf-token"]')?.content;
 const dialog=document.querySelector('[data-friends-dialog]');
 if(dialog){let endpoint,next=null,busy=false;const list=dialog.querySelector('[data-friend-list]'),status=dialog.querySelector('[data-friends-status]'),more=dialog.querySelector('[data-more-friends]');
  async function load(offset=0){if(busy)return;busy=true;status.textContent=t('Loading…');more.disabled=true;try{const response=await fetch(endpoint+'?offset='+offset,{headers:{Accept:'application/json'},cache:'no-store'});if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error();const data=await response.json();list.insertAdjacentHTML('beforeend',data.html);next=data.next_offset;more.hidden=next===null;status.textContent=list.children.length?'':t('No friends yet.');document.querySelectorAll('[data-friends-count]').forEach(node=>node.textContent=data.count);}catch(_){status.textContent=t('Could not load friends. Please sign in and try again.');}finally{busy=false;more.disabled=false;}}
  document.querySelectorAll('[data-open-friends]').forEach(button=>button.addEventListener('click',()=>{endpoint=button.dataset.friendsUrl;list.replaceChildren();dialog.showModal();load();}));
  dialog.querySelector('[data-close-friends]').addEventListener('click',()=>dialog.close());more.addEventListener('click',()=>load(next));
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  dialog.addEventListener('submit',async event=>{const form=event.target.closest('[data-friend-add]');if(!form)return;event.preventDefault();const button=form.querySelector('button');button.disabled=true;try{const response=await fetch(form.getAttribute('action'),{method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});if(!response.ok)throw Error();button.textContent=t('Request sent');}catch(_){button.disabled=false;status.textContent=t('Could not send the request. Please try again.');}});
 }
 const shell=document.querySelector('.ga-chat-shell'),expand=document.querySelector('[data-chat-expand]');
 if(shell&&expand){
  let active=false;
  function size(){if(window.visualViewport)shell.style.setProperty('--ga-chat-height',window.visualViewport.height+'px');}
  function toggle(value){active=value;document.body.classList.toggle('ga-chat-expanded',active);shell.classList.toggle('is-expanded',active);expand.setAttribute('aria-label',t(active?'Exit fullscreen':'Fullscreen chat'));expand.setAttribute('aria-pressed',String(active));expand.querySelector('[data-expand-icon]').hidden=active;expand.querySelector('[data-close-icon]').hidden=!active;size();}
  async function exit(){if(document.fullscreenElement===shell){try{await document.exitFullscreen();}catch(_){}}toggle(false);}
  expand.addEventListener('click',async()=>{if(active){await exit();return;}toggle(true);if(shell.requestFullscreen){try{await shell.requestFullscreen();}catch(_){/* Viewport fallback for unsupported browser contexts. */}}});
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement&&active)toggle(false);});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&active)exit();});window.visualViewport?.addEventListener('resize',size);
 }
 const header=document.querySelector('.ga-header');if(!header?.dataset.userId)return;
 window.gamearenaSeenLive=async payload=>{if(document.hidden||payload?.kind!=='messages'||!payload.id)return;try{await fetch('/notifications/'+Number(payload.id)+'/seen-live',{method:'POST',headers:{'X-CSRFToken':csrf(),Accept:'application/json'}});}catch(_){};};
 navigator.serviceWorker?.addEventListener('message',event=>{if(event.data?.type==='gamearena-message'&&!document.hidden){const payload=event.data.payload;if(Number(payload.owner_id)!==Number(header.dataset.userId))return;window.gamearenaSeenLive(payload);window.gamearenaNotify?.({id:payload.id,message:payload.body,target_url:payload.url});}});
})();
