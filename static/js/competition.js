/* Refresh assigned match state without overwriting a player's unfinished form. */
(() => {
 const root=document.querySelector('[data-competition-live]');
 if(!root) return;
 let dirty=false,busy=false,pending=false,timer;
 document.querySelectorAll('form').forEach(form=>{form.addEventListener('input',()=>dirty=true);form.addEventListener('change',()=>dirty=true);});
 const feedback=root.querySelector('[data-live-feedback]');
 async function update(){
  if(document.hidden)return;
  if(busy){pending=true;return;}
  busy=true;const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);
  try{const response=await fetch(root.dataset.statusUrl,{cache:'no-store',headers:{Accept:'application/json'},signal:controller.signal});
   if(response.status===401||response.status===403){clearInterval(timer);return;}
   if(!response.ok)return;const data=await response.json();
   if(data.signature===root.dataset.state)return;
   if(dirty){if(feedback&&!feedback.querySelector('button')){feedback.textContent=gaT('Your match has updated. Your unsent form has been kept.');const button=document.createElement('button');button.type='button';button.className='ga-button ga-button-secondary';button.textContent=gaT('Load match update');button.addEventListener('click',()=>location.reload());feedback.append(' ',button);}return;}
   if(data.match_url&&data.match_url!==root.dataset.matchUrl&&!data.closed)location.assign(data.match_url);else location.reload();
  }catch(_){}finally{clearTimeout(timeout);busy=false;if(pending){pending=false;queueMicrotask(update);}}
 }
 const eventId=Number(root.dataset.statusUrl.match(/tournament\/(\d+)/)?.[1]);
 const socket=window.gamearenaSocket;
 const watch=()=>{if(eventId)socket.emit('watch_competition',{tournament_id:eventId});};
 if(socket){if(socket.connected)watch();socket.on('connect',()=>{watch();update();});socket.on('competition_update',payload=>{if(payload?.tournament_id===eventId)update();});}
 timer=setInterval(update,20000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)update();});
 root.querySelectorAll('[data-copy-text]').forEach(button=>button.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(button.dataset.copyText);button.textContent=gaT('Copied');}catch(_){if(feedback)feedback.textContent=gaT('Select and copy the room details above.');}}));
 const deadlines=[...root.querySelectorAll('[data-deadline]')];
 if(deadlines.length){const tick=()=>deadlines.forEach(el=>{const seconds=Math.max(0,Math.ceil((new Date(el.dataset.deadline)-Date.now())/1000));el.textContent=seconds?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`:gaT('Closed');if(!seconds)root.querySelectorAll('[data-checkin-submit]').forEach(button=>button.disabled=true);});tick();setInterval(tick,1000);}
})();
