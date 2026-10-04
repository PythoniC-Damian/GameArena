(() => {
  const main = document.querySelector('.ga-chat-shell');
  if (!main || typeof io !== 'function') return;
  const socket = window.gamearenaSocket || (window.gamearenaSocket = io());
  const userId = Number(main.dataset.userId), partnerId = Number(main.dataset.partnerId) || null;
  const form = document.getElementById('chatForm'), input = document.getElementById('chatInput');
  const messages = document.getElementById('messages'), status = document.getElementById('chatStatus');
  const preview = document.getElementById('replyPreview');
  const ids = new Set(Array.from(messages.querySelectorAll('[data-message-id]')).map(row => row.dataset.messageId));
  const pending = new Map();
  const dialog = document.getElementById('messageActions');
  let actionRow, typingTimer, typingClear, lastTyping = 0;
  let lastId = Math.max(0, ...Array.from(ids).map(Number)), sending = false, reply = null, catchingUp = false;
  function clearReply() { reply = null; preview.hidden = true; preview.querySelector("strong").textContent = ""; preview.querySelector("p").textContent = ""; }
  function chooseReply(row) {
    if (row.dataset.deleted === 'true') return;
    reply = {id:Number(row.dataset.messageId),username:row.dataset.username || 'Player',message:row.querySelector('[data-message-body]').textContent.slice(0,200)};
    preview.querySelector('strong').textContent = `Replying to ${reply.username}`;
    preview.querySelector('p').textContent = reply.message; preview.hidden = false; input.focus();
  }
  function quote(parent) {
    const block = document.createElement('blockquote'); block.className = 'ga-chat-quote'; block.dataset.quoteId = parent.id;
    const name = document.createElement('strong'); name.textContent = parent.username;
    const text = document.createElement('p'); text.textContent = parent.message;
    block.append(name,text); return block;
  }
  function render(message) {
    if (message.client_message_id && pending.has(message.client_message_id)) { pending.get(message.client_message_id).confirm(message); }
    if (ids.has(String(message.id))) { if (message.deleted) removeMessage(message.id); return; }
    if (message.id) { ids.add(String(message.id)); lastId = Math.max(lastId, Number(message.id)); }
    const sender = Number(message.sender_id || message.user_id), own = sender === userId;
    const nearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 100;
    messages.querySelector('[data-chat-empty]')?.remove();
    const row = document.createElement('div'); row.dataset.messageId = message.id; row.dataset.username = message.username || 'Player'; row.dataset.senderId = sender; row.dataset.deleted = String(Boolean(message.deleted)); row.tabIndex = 0; row.setAttribute('aria-label', 'Message from '+row.dataset.username+'. Swipe to reply, or press Enter for actions.');
    row.className = `${own ? 'ml-auto bg-emerald-500/10 text-emerald-200 border-emerald-500/10' : 'bg-slate-900/80 text-slate-300 border-slate-800'} w-fit max-w-[85%] break-words rounded-[28px] border p-4 shadow-sm`;
    const heading = document.createElement('div'); heading.className = 'flex items-center justify-between gap-3';
    const username = document.createElement('strong'); username.textContent = row.dataset.username;
    const timestamp = document.createElement('small'); const date = new Date(message.created_at); timestamp.className = 'ga-muted'; timestamp.textContent = Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); heading.append(username,timestamp);
    const body = document.createElement('p'); body.className = 'mt-2 whitespace-pre-wrap text-sm leading-6'; body.dataset.messageBody = ''; body.textContent = message.message;
    row.append(heading); if (message.reply) row.append(quote(message.reply)); row.append(body);
    messages.append(row); if (own || nearBottom) messages.scrollTop = messages.scrollHeight;
    if (!own && partnerId && !document.hidden) markRead();
  }
  async function markRead() {
    if (!partnerId) return;
    try { await fetch(`/messages/${partnerId}/read`, {method:'POST',headers:{'X-CSRFToken':document.querySelector('meta[name=csrf-token]').content}}); } catch (_) {}
  }
  async function catchUp() {
    if (catchingUp || document.hidden) return;
    catchingUp = true;
    try {
      let more = true, pages = 0;
      while (more && pages++ < 20) {
        const url = new URL(main.dataset.historyUrl, location.origin); url.searchParams.set('after',lastId);
        const response = await fetch(url,{cache:'no-store'});
        if (!response.ok) { if (response.status === 403) status.textContent = 'This conversation is unavailable. Check blocking and direct-message settings.'; break; }
        const data = await response.json(); data.messages.forEach(render); (data.deleted_ids || []).forEach(removeMessage); more = data.has_more;
      }
    } catch (_) { if (!socket.connected) status.textContent = 'Reconnecting… Your draft is saved here.'; }
    finally { catchingUp = false; }
  }
  function joinChat() {
    socket.emit('join_user',{user_id:userId});
    socket.emit(partnerId ? 'join_direct_message' : 'join_global_chat', partnerId ? {user_id:partnerId} : {});
    status.textContent = ''; catchUp();
  }
  socket.on('connect',joinChat); if (socket.connected) joinChat();
  socket.on('disconnect',() => { status.textContent = 'Reconnecting… Your draft is saved here.'; });
  socket.on('new_global_chat_message',message => { if (!partnerId) render(message); });
  socket.on('new_direct_message',message => {
    if (partnerId && ((Number(message.sender_id) === partnerId && Number(message.recipient_id) === userId) || (Number(message.sender_id) === userId && Number(message.recipient_id) === partnerId))) render(message);
  });
  socket.on('conversation_access_changed',event => { if (Number(event.partner_id) === partnerId) joinChat(); });
  socket.on('socket_error',event => { status.textContent = event.message || 'Message could not be sent.'; });
  socket.on('unread_count',event => { const count = document.getElementById('dmUnreadCount'); if (count) count.textContent = `${Number(event.unread) || 0} unread messages across your inbox`; });
  function removeMessage(id) {
    const row = messages.querySelector(`[data-message-id="${Number(id)}"]`);
    if (row) {
      row.dataset.deleted = 'true'; row.querySelector('[data-message-body]').textContent = 'This message was deleted.';
      row.querySelector('.ga-chat-quote')?.remove();
    }
    messages.querySelectorAll(`[data-quote-id="${Number(id)}"] p`).forEach(text => { text.textContent = 'This message was deleted.'; });
    if (reply?.id === Number(id)) clearReply();
  }
  socket.on('chat_message_deleted', event => { if (event.kind === (partnerId ? 'direct' : 'global')) removeMessage(event.id); });
  function openActions(row) {
    if (!row || row.dataset.deleted === 'true') return;
    actionRow = row;
    dialog.querySelector('[data-delete-message]').hidden = Number(row.dataset.senderId) !== userId;
    dialog.querySelector('[data-delete-confirm]').hidden = true;
    dialog.querySelector('[data-action-status]').textContent = '';
    dialog.showModal();
  }
  dialog.querySelector('[data-action-reply]').addEventListener('click', () => { const row = actionRow; dialog.close(); chooseReply(row); });
  dialog.querySelector('[data-delete-message]').addEventListener('click', () => { dialog.querySelector('[data-delete-confirm]').hidden = false; });
  dialog.querySelector('[data-delete-confirm]').addEventListener('click', async () => {
    const button = dialog.querySelector('[data-delete-confirm]'); button.disabled = true;
    try {
      const url = main.dataset.deleteUrl.replace('/0/delete', `/${actionRow.dataset.messageId}/delete`);
      const response = await fetch(url, {method:'POST',headers:{Accept:'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content}});
      if (!response.ok) throw new Error('Unable to delete this message. Please try again.');
      removeMessage(actionRow.dataset.messageId); dialog.close();
    } catch (error) { dialog.querySelector('[data-action-status]').textContent = error.message; }
    finally { button.disabled = false; }
  });
  dialog.querySelector('[data-action-cancel]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => actionRow?.focus());
  messages.addEventListener('contextmenu', event => { const row = event.target.closest('[data-message-id]'); if (row) { event.preventDefault(); openActions(row); } });
  messages.addEventListener('keydown', event => { if (event.target.matches('[data-message-id]') && (event.key === 'Enter' || (event.shiftKey && event.key === 'F10'))) { event.preventDefault(); openActions(event.target); } });
  let drag, hold;
  messages.addEventListener('pointerdown', event => {
    const row = event.target.closest('[data-message-id]'); if (!row || event.target.closest('button,a,summary,input')) return;
    drag = {x:event.clientX,y:event.clientY,row};
    hold = setTimeout(() => { if (drag) { openActions(row); drag = null; } }, 550);
  });
  messages.addEventListener('pointermove', event => {
    if (!drag) return;
    const x = event.clientX-drag.x, y = event.clientY-drag.y;
    if (Math.abs(x)>8 || Math.abs(y)>8) clearTimeout(hold);
    if (Math.abs(y)<30) drag.row.style.transform = `translateX(${Math.max(-64,Math.min(64,x))}px)`;
  });
  function endDrag(event) {
    clearTimeout(hold);
    if (drag) {
      drag.row.style.transform = '';
      if (event.type === 'pointerup' && Math.abs(event.clientX-drag.x)>48 && Math.abs(event.clientY-drag.y)<30) chooseReply(drag.row);
    }
    drag = null;
  }
  messages.addEventListener('pointerup', endDrag); messages.addEventListener('pointercancel', endDrag);
  preview.querySelector('button').addEventListener('click',clearReply);
  function emitTyping(active) {
    if (socket.connected) socket.emit('chat_typing',{user_id:partnerId,typing:active});
  }
  input.addEventListener('input', () => {
    clearTimeout(typingTimer);
    if (Date.now()-lastTyping>1800) { emitTyping(Boolean(input.value.trim())); lastTyping=Date.now(); }
    typingTimer=setTimeout(() => emitTyping(false),2200);
  });
  input.addEventListener('blur', () => emitTyping(false));
  socket.on('chat_typing', event => {
    if (Number(event.user_id) === userId || (partnerId && Number(event.user_id) !== partnerId)) return;
    const indicator=document.getElementById('chatTyping'); clearTimeout(typingClear);
    indicator.hidden=!event.typing; indicator.querySelector('[data-typing-name]').textContent=`${event.username} is typing`;
    typingClear=setTimeout(() => { indicator.hidden=true; },3500);
  });
  form.addEventListener('submit',event => {
    event.preventDefault(); const text = input.value.trim(); if (!text || sending) return;
    const selectedReply = reply, key = crypto.randomUUID();
    const payload = {message:text,client_message_id:key};
    if (partnerId) payload.user_id = partnerId; if (selectedReply) payload.reply_to_id = selectedReply.id;
    const button=form.querySelector('button[type=submit]'); sending=true; button.disabled=true; status.textContent='Sending…'; emitTyping(false);
    let finished=false, recovery;
    function confirm(message) {
      if (finished) return; finished=true; clearTimeout(recovery); pending.delete(key);
      sending=false; button.disabled=false;
      if (input.value.trim() === text) input.value=''; if (reply === selectedReply) clearReply();
      status.textContent='';
      if (message.id && !ids.has(String(message.id))) render({...message,sender_id:userId,recipient_id:partnerId,username:main.dataset.username,message:text,reply:selectedReply,created_at:message.created_at || new Date().toISOString()});
    }
    function fail(message) {
      if (finished) return; finished=true; pending.delete(key); clearTimeout(recovery); sending=false; button.disabled=false; status.textContent=message;
    }
    async function recover() {
      if (finished) return;
      try {
        // The same UUID makes transport recovery safe even if the socket save succeeded.
        const response=await fetch(main.dataset.sendUrl,{method:'POST',headers:{Accept:'application/json','Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify(payload),signal:AbortSignal.timeout(20000)});
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The messaging service is unavailable. Your draft is saved.');
        const result=await response.json();
        if (result.status==='success') confirm(result); else fail(result.message || 'Unable to send. Your draft is saved.');
      } catch (error) { if (!finished) { await catchUp(); if (!finished) fail(error.name === 'TimeoutError' ? 'Still reconnecting. Your draft is saved; check recent messages before retrying.' : error.message); } }
    }
    pending.set(key,{confirm});
    if (socket.connected) {
      socket.emit(partnerId ? 'send_direct_message' : 'send_global_chat_message',payload,result => {
        if (result?.status==='success') confirm(result); else if (result?.status==='error') fail(result.message);
      });
      recovery=setTimeout(recover,5000);
    } else recover();
  });
  document.addEventListener('visibilitychange',() => { if (!document.hidden) { catchUp(); markRead(); } });
  // Also recover missed events on deployments with intermittent socket transport.
  setInterval(catchUp,12000);
  messages.scrollTop = messages.scrollHeight;
})();
