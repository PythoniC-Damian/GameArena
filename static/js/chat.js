(() => {
  const main = document.querySelector('.ga-chat-shell');
  if (!main || typeof io !== 'function') return;
  const socket = window.gamearenaSocket || (window.gamearenaSocket = io());
  const userId = Number(main.dataset.userId), partnerId = Number(main.dataset.partnerId) || null;
  const form = document.getElementById('chatForm'), input = document.getElementById('chatInput');
  const messages = document.getElementById('messages'), status = document.getElementById('chatStatus');
  const preview = document.getElementById('replyPreview');
  const ids = new Set(Array.from(messages.querySelectorAll('[data-message-id]')).map(row => row.dataset.messageId));
  let lastId = Math.max(0, ...Array.from(ids).map(Number)), sending = false, reply = null, catchingUp = false;
  function clearReply() { reply = null; preview.hidden = true; }
  function chooseReply(row) {
    reply = {id:Number(row.dataset.messageId),username:row.dataset.username || 'Player',message:row.querySelector('[data-message-body]').textContent.slice(0,200)};
    preview.querySelector('strong').textContent = `Replying to ${reply.username}`;
    preview.querySelector('p').textContent = reply.message; preview.hidden = false; input.focus();
  }
  function quote(parent) {
    const block = document.createElement('blockquote'); block.className = 'ga-chat-quote';
    const name = document.createElement('strong'); name.textContent = parent.username;
    const text = document.createElement('p'); text.textContent = parent.message;
    block.append(name,text); return block;
  }
  function render(message) {
    if (ids.has(String(message.id))) return;
    if (message.id) { ids.add(String(message.id)); lastId = Math.max(lastId, Number(message.id)); }
    const sender = Number(message.sender_id || message.user_id), own = sender === userId;
    const nearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 100;
    messages.querySelector('[data-chat-empty]')?.remove();
    const row = document.createElement('div'); row.dataset.messageId = message.id; row.dataset.username = message.username || 'Player';
    row.className = `${own ? 'ml-auto bg-emerald-500/10 text-emerald-200 border-emerald-500/10' : 'bg-slate-900/80 text-slate-300 border-slate-800'} w-fit max-w-[85%] break-words rounded-[28px] border p-4 shadow-sm`;
    const heading = document.createElement('div'); heading.className = 'flex items-center justify-between gap-3';
    const username = document.createElement('strong'); username.textContent = row.dataset.username;
    const timestamp = document.createElement('small'); const date = new Date(message.created_at); timestamp.className = 'ga-muted'; timestamp.textContent = Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); heading.append(username,timestamp);
    const body = document.createElement('p'); body.className = 'mt-2 whitespace-pre-wrap text-sm leading-6'; body.dataset.messageBody = ''; body.textContent = message.message;
    row.append(heading); if (message.reply) row.append(quote(message.reply)); row.append(body);
    const button = document.createElement('button'); button.type = 'button'; button.className = 'ga-chat-reply-button'; button.dataset.reply = ''; button.textContent = 'Reply'; button.setAttribute('aria-label',`Reply to ${row.dataset.username}`); row.append(button);
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
        const data = await response.json(); data.messages.forEach(render); more = data.has_more;
      }
    } catch (_) { if (!socket.connected) status.textContent = 'Reconnecting… Your draft is saved here.'; }
    finally { catchingUp = false; }
  }
  function joinChat() {
    socket.emit('join_user',{user_id:userId});
    socket.emit(partnerId ? 'join_direct_message' : 'join_global_chat', partnerId ? {user_id:partnerId} : {});
    status.textContent = 'Connected'; catchUp();
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
  messages.addEventListener('click',event => { const button = event.target.closest('[data-reply]'); if (button) chooseReply(button.closest('[data-message-id]')); });
  let drag;
  messages.addEventListener('pointerdown',event => { const row = event.target.closest('[data-message-id]'); if (row && !event.target.closest('button,a,summary')) drag = {x:event.clientX,y:event.clientY,row}; });
  messages.addEventListener('pointerup',event => { if (drag && Math.abs(event.clientX-drag.x)>48 && Math.abs(event.clientY-drag.y)<30 && window.getSelection()?.type !== 'Range') chooseReply(drag.row); drag = null; });
  messages.addEventListener('pointercancel',() => { drag = null; });
  preview.querySelector('button').addEventListener('click',clearReply);
  form.addEventListener('submit',event => {
    event.preventDefault(); const text = input.value.trim(); if (!text || sending) return;
    if (!socket.connected) { status.textContent = 'Reconnect to send. Your draft is still here.'; return; }
    const selectedReply = reply; const payload = {message:text};
    if (partnerId) payload.user_id = partnerId; if (selectedReply) payload.reply_to_id = selectedReply.id;
    sending = true; const button = form.querySelector('button[type=submit]'); button.disabled = true; status.textContent = 'Sending…';
    socket.timeout(8000).emit(partnerId ? 'send_direct_message' : 'send_global_chat_message',payload,(error,result) => {
      sending = false; button.disabled = false;
      if (!error && result?.status === 'success') {
        render({id:result.id,sender_id:userId,recipient_id:partnerId,username:main.dataset.username,message:text,reply:selectedReply,created_at:new Date().toISOString()});
        if (input.value.trim() === text) input.value = ''; if (reply === selectedReply) clearReply(); status.textContent = 'Sent';
      } else { status.textContent = result?.message || 'Delivery was not confirmed. Check recent messages before retrying.'; catchUp(); }
    });
  });
  document.addEventListener('visibilitychange',() => { if (!document.hidden) { catchUp(); markRead(); } });
  // Also recover missed events on deployments with intermittent socket transport.
  setInterval(catchUp,12000);
  messages.scrollTop = messages.scrollHeight;
})();
