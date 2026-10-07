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
  const seenIds = new Set(), viewedIds = new Set();
  let reading = false, inboxTimer, refreshingInbox = false;
  const inbox = document.getElementById('conversationList');
  function applySeen(id) {
    seenIds.add(String(id));
    const row = messages.querySelector(`[data-message-id="${Number(id)}"]`);
    if (!row || Number(row.dataset.senderId) !== userId || row.dataset.deleted === 'true') return;
    let label = row.querySelector('[data-read-receipt]');
    if (!label) {
      const delivery = document.createElement('div'); delivery.className = 'ga-message-delivery';
      label = document.createElement('small'); label.dataset.readReceipt = ''; delivery.append(label); row.append(delivery);
    }
    label.textContent = '✓✓ Seen'; label.classList.add('ga-message-seen');
  }
  async function refreshInbox() {
    if (!inbox || refreshingInbox || document.hidden) return;
    refreshingInbox = true;
    try {
      const response = await fetch(inbox.dataset.url, {cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json(), fragment = document.createDocumentFragment();
      for (const item of data.conversations) {
        const link = document.createElement('a'); link.href = item.url; link.className = 'ga-conversation-row';
        if (Number(item.id) === partnerId) { link.classList.add('is-active'); link.setAttribute('aria-current','page'); }
        const avatar = document.createElement(item.avatar_url ? 'img' : 'span'); avatar.className = 'ga-chat-avatar';
        if (item.avatar_url) { avatar.src = item.avatar_url; avatar.alt = ''; avatar.loading = 'lazy'; avatar.width = avatar.height = 48; }
        else avatar.textContent = item.username.slice(0,1).toUpperCase();
        const copy = document.createElement('span'); copy.className = 'ga-conversation-copy';
        const name = document.createElement('strong'); name.textContent = item.username;
        const summary = document.createElement('span'); summary.textContent = `${item.own ? 'You: ' : ''}${item.preview}`; copy.append(name,summary);
        const meta = document.createElement('span'); meta.className = 'ga-conversation-meta';
        const time = document.createElement('time'); time.textContent = new Date(item.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); meta.append(time);
        if (item.unread || (item.own && item.seen)) {
          const badge = document.createElement('span'); badge.className = item.unread ? 'ga-conversation-unread' : 'ga-message-seen';
          badge.textContent = item.unread || '✓✓'; badge.setAttribute('aria-label',item.unread ? `${item.unread} unread messages` : 'Seen'); meta.append(badge);
        }
        link.append(avatar,copy,meta); fragment.append(link);
      }
      if (!data.conversations.length) { const empty = document.createElement('p'); empty.className = 'ga-muted'; empty.textContent = 'Start chatting and connect with other players.'; fragment.append(empty); }
      // Preserve focus and scroll while replacing frequently updated rows.
      if (!inbox.contains(document.activeElement)) inbox.replaceChildren(fragment);
      document.getElementById('conversationCount').textContent = data.conversations.length;
    } catch (_) {} finally { refreshingInbox = false; }
  }
  function scheduleInbox() { clearTimeout(inboxTimer); inboxTimer = setTimeout(refreshInbox,250); }
  const readObserver = partnerId && typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
    if (document.hidden) return;
    for (const entry of entries) if (entry.isIntersecting && entry.target.dataset.messageId && Number(entry.target.dataset.senderId) === partnerId) viewedIds.add(Number(entry.target.dataset.messageId));
    markRead();
  }, {threshold:0.5}) : null;
  messages.querySelectorAll('[data-message-id]').forEach(row => readObserver?.observe(row));
  const dialog = document.getElementById('messageActions');
  let actionRow, typingTimer, typingClear, lastTyping = 0;
  let lastId = Math.max(0, ...Array.from(ids).map(Number)), reply = null, catchingUp = false;
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
    if (message.client_message_id && pending.has(message.client_message_id) && message.id) { pending.get(message.client_message_id).confirm(message); return; }
    if (ids.has(String(message.id))) { if (message.deleted) removeMessage(message.id); if (message.read_at) applySeen(message.id); return; }
    if (message.id) { ids.add(String(message.id)); lastId = Math.max(lastId, Number(message.id)); }
    const sender = Number(message.sender_id || message.user_id), own = sender === userId;
    const nearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 100;
    messages.querySelector('[data-chat-empty]')?.remove();
    const row = document.createElement('div'); if (message.id) row.dataset.messageId = message.id; row.dataset.username = message.username || 'Player'; row.dataset.senderId = sender; row.dataset.deleted = String(Boolean(message.deleted)); row.tabIndex = 0; row.setAttribute('aria-label', 'Message from '+row.dataset.username+'. Swipe to reply, or press Enter for actions.');
    row.className = `${own ? 'ml-auto bg-emerald-500/10 text-emerald-200 border-emerald-500/10' : 'bg-slate-900/80 text-slate-300 border-slate-800'} w-fit max-w-[85%] break-words rounded-[28px] border p-4 shadow-sm`;
    const heading = document.createElement('div'); heading.className = 'flex items-center justify-between gap-3';
    const username = document.createElement('strong'); username.textContent = row.dataset.username;
    const timestamp = document.createElement('small'); const date = new Date(message.created_at); timestamp.className = 'ga-muted'; timestamp.textContent = Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); heading.append(username,timestamp);
    const body = document.createElement('p'); body.className = 'mt-2 whitespace-pre-wrap text-sm leading-6'; body.dataset.messageBody = ''; body.textContent = message.message;
    row.append(heading); if (message.reply) row.append(quote(message.reply)); row.append(body);
    if (own && partnerId && message.id && !message.deleted) {
      const delivery = document.createElement('div'); delivery.className = 'ga-message-delivery';
      const label = document.createElement('small'); label.dataset.readReceipt = ''; label.textContent = '✓ Sent'; delivery.append(label); row.append(delivery);
    }
    messages.append(row); if (own || nearBottom) messages.scrollTop = messages.scrollHeight;
    readObserver?.observe(row);
    if (message.read_at || seenIds.has(String(message.id))) applySeen(message.id);
    if (!own && partnerId && !document.hidden) markRead();
    return row;
  }
  async function markRead() {
    if (!partnerId || document.hidden || reading || !viewedIds.size) return;
    reading = true;
    const ids = [...viewedIds].slice(0,100);
    try {
      const response = await fetch(`/messages/${partnerId}/read`, {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify({ids})});
      if (response.ok) { ids.forEach(id => viewedIds.delete(id)); scheduleInbox(); }
    } catch (_) {} finally { reading = false; }
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
        const data = await response.json(); data.messages.forEach(render); (data.read_ids || []).forEach(applySeen); (data.deleted_ids || []).forEach(removeMessage); more = data.has_more;
      }
    } catch (_) { if (!socket.connected) status.textContent = 'Reconnecting… Your draft is saved here.'; }
    finally { catchingUp = false; markRead(); refreshInbox(); }
  }
  function joinChat() {
    socket.emit('join_user',{user_id:userId});
    socket.emit(partnerId ? 'join_direct_message' : 'join_global_chat', partnerId ? {user_id:partnerId} : {});
    status.textContent = ''; catchUp(); pumpOutbox();
  }
  socket.on('connect',joinChat); if (socket.connected) queueMicrotask(joinChat);
  socket.on('disconnect',() => { status.textContent = 'Reconnecting… Your draft is saved here.'; });
  socket.on('new_global_chat_message',message => { if (!partnerId) render(message); });
  socket.on('new_direct_message',message => {
    scheduleInbox();
    if (partnerId && ((Number(message.sender_id) === partnerId && Number(message.recipient_id) === userId) || (Number(message.sender_id) === userId && Number(message.recipient_id) === partnerId))) render(message);
  });
  socket.on('direct_messages_read',event => { if (Number(event.reader_id) === partnerId) (event.ids || []).forEach(applySeen); scheduleInbox(); });
  socket.on('conversation_access_changed',event => { if (Number(event.partner_id) === partnerId) joinChat(); });
  socket.on('socket_error',event => { status.textContent = event.message || 'Message could not be sent.'; });
  socket.on('unread_count',event => { const count = document.getElementById('dmUnreadCount'); if (count) count.textContent = `${Number(event.unread) || 0} unread messages across your inbox`; });
  function removeMessage(id) {
    const row = messages.querySelector(`[data-message-id="${Number(id)}"]`);
    if (row) {
      row.dataset.deleted = 'true'; row.querySelector('[data-message-body]').textContent = 'This message was deleted.';
      row.querySelector('[data-read-receipt]')?.remove();
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
  // Each message owns its transport, UUID and status. The composer never waits for an ACK.
  const outboxKey = `gamearena-outbox:${userId}:${partnerId || 'global'}`;
  let inFlight = 0;
  function saveOutbox() {
    try { sessionStorage.setItem(outboxKey, JSON.stringify([...pending.values()].map(item => ({payload:item.payload,reply:item.reply,created:item.created,state:item.state})))); } catch (_) {}
  }
  function pumpOutbox() {
    for (const item of pending.values()) {
      if (inFlight >= 4) break;
      if (item.state === 'queued') item.send();
    }
  }
  function addOutgoing(payload, selectedReply, created = new Date().toISOString(), failed = false) {
    const key = payload.client_message_id;
    const row = render({sender_id:userId,username:main.dataset.username,message:payload.message,reply:selectedReply,created_at:created});
    row.dataset.clientMessageId = key; row.removeAttribute('tabindex'); row.setAttribute('aria-label','Outgoing message');
    const delivery = document.createElement('div'); delivery.className = 'ga-message-delivery';
    const label = document.createElement('small'); label.setAttribute('role','status');
    const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Retry'; retry.hidden = true; retry.setAttribute('aria-label','Retry sending this message');
    delivery.append(label,retry); row.append(delivery);
    const item = {payload,reply:selectedReply,created,state:failed ? 'failed' : 'queued',row};
    let recovery, active = false, finished = false, recovering = false;
    function release() {
      clearTimeout(recovery);
      if (active) { active = false; inFlight--; }
    }
    item.confirm = message => {
      if (finished || !message.id) return;
      finished = true; release(); pending.delete(key);
      const id = String(message.id);
      if (ids.has(id)) row.remove();
      else {
        ids.add(id); lastId = Math.max(lastId, Number(message.id));
        row.dataset.messageId = id; row.dataset.deleted = String(Boolean(message.deleted)); row.tabIndex = 0;
        row.setAttribute('aria-label','Message from '+main.dataset.username+'. Swipe to reply, or press Enter for actions.');
        label.textContent = partnerId ? '✓ Sent' : 'Sent'; retry.hidden = true;
        if (partnerId) { label.dataset.readReceipt = ''; if (message.read_at || seenIds.has(id)) applySeen(id); }
        if (message.deleted) removeMessage(message.id);
      }
      saveOutbox(); pumpOutbox();
    };
    function fail(message) {
      if (finished) return;
      release(); item.state = 'failed'; label.textContent = message; retry.hidden = false;
      saveOutbox(); pumpOutbox();
    }
    async function recover() {
      if (finished || recovering) return;
      recovering = true;
      try {
        // Reuse the same UUID even after a lost response or a manual Retry.
        const response = await fetch(main.dataset.sendUrl,{method:'POST',headers:{Accept:'application/json','Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify(payload),signal:AbortSignal.timeout(15000)});
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Connection interrupted. Your message is kept here.');
        const result = await response.json();
        if (result.status === 'success') item.confirm(result);
        else fail(result.message || 'Could not send. Retry this message.');
      } catch (_) {
        if (!finished) { await catchUp(); if (!finished) fail('Not confirmed yet. Your message is kept here; tap Retry.'); }
      } finally { recovering = false; }
    }
    item.send = () => {
      if (finished || active || recovering) return;
      active = true; inFlight++; item.state = 'sending'; label.textContent = 'Sending…'; retry.hidden = true; saveOutbox();
      if (socket.connected) {
        socket.emit(partnerId ? 'send_direct_message' : 'send_global_chat_message',payload,result => {
          if (result?.status === 'success') item.confirm(result);
          else if (result?.status === 'error') fail(result.message || 'Could not send. Retry this message.');
        });
        if (!finished && active) recovery = setTimeout(recover,1500);
      } else recover();
    };
    retry.addEventListener('click', () => {
      if (active || recovering || finished) return;
      item.state = 'queued'; label.textContent = 'Queued'; retry.hidden = true; saveOutbox(); pumpOutbox();
    });
    label.textContent = failed ? 'Not confirmed yet. Tap Retry.' : 'Queued'; retry.hidden = !failed;
    pending.set(key,item); return item;
  }
  form.addEventListener('submit',event => {
    event.preventDefault(); const text = input.value.trim(); if (!text) return;
    if (pending.size >= 50) { status.textContent = 'You have 50 unsent messages. Retry them before sending more.'; return; }
    const selectedReply = reply, payload = {message:text,client_message_id:crypto.randomUUID()};
    if (partnerId) payload.user_id = partnerId; if (selectedReply) payload.reply_to_id = selectedReply.id;
    addOutgoing(payload,selectedReply);
    input.value = ''; clearReply(); emitTyping(false); status.textContent = '';
    // Retain keyboard focus so the player can immediately write the next message.
    input.focus(); saveOutbox(); pumpOutbox();
  });
  try {
    const saved = JSON.parse(sessionStorage.getItem(outboxKey) || '[]');
    if (Array.isArray(saved)) saved.slice(0,50).forEach(item => {
      const payload = item?.payload;
      if (typeof payload?.message === 'string' && payload.message.length <= 1000 && /^[a-f0-9-]{36}$/.test(payload.client_message_id) && (payload.user_id || null) === partnerId) addOutgoing(payload,item.reply,item.created,true);
    });
  } catch (_) {}
  document.addEventListener('visibilitychange',() => { if (!document.hidden) {
    messages.querySelectorAll('[data-message-id]').forEach(row => { readObserver?.unobserve(row); readObserver?.observe(row); });
    catchUp(); markRead();
  } });
  // Also recover missed events on deployments with intermittent socket transport.
  setInterval(catchUp,12000);
  messages.scrollTop = messages.scrollHeight;
})();
