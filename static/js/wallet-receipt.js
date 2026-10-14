(() => {
  const receipt = document.getElementById('walletReceipt');
  const button = document.getElementById('shareReceipt');
  const status = document.getElementById('receiptActionStatus');
  if (!receipt || !button) return;
  document.querySelectorAll('.ga-copy-id').forEach(copy => copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(copy.parentElement.querySelector('[data-copy-value]').textContent.trim()); status.textContent = 'Copied.'; }
    catch (_) { status.textContent = 'Copy is unavailable. Select the transaction ID or reference to copy it.'; }
  }));
  async function receiptFiles() {
    const rows = [...receipt.querySelectorAll('[data-receipt-row]')].map(row => [row.querySelector('dt').textContent.trim(), row.dataset.shareValue || row.querySelector('dd').textContent.trim()]);
    const canvas = document.createElement('canvas'); canvas.width = 1080;
    const ctx = canvas.getContext('2d');
    function wrap(text, maxWidth) {
      const lines = []; let line = '';
      for (const char of text) { if (ctx.measureText(line + char).width > maxWidth && line) { lines.push(line); line = ''; } line += char; }
      if (line) lines.push(line); return lines;
    }
    ctx.font = '28px sans-serif';
    const details = rows.map(([label,value]) => { const font = /ID|reference|code/.test(label) ? '24px monospace' : '28px sans-serif'; ctx.font = font; return {label,font,lines:wrap(value,560)}; });
    canvas.height = 570 + details.reduce((height,row) => height + Math.max(65,row.lines.length * 36 + 24), 0) + 140;
    ctx.fillStyle = '#080f1d'; ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle = '#101b2d'; ctx.fillRect(24,24,1032,canvas.height-48);
    ctx.save(); ctx.beginPath(); ctx.rect(24,24,1032,canvas.height-48); ctx.clip();
    ctx.fillStyle = '#edf4fb'; ctx.globalAlpha = 0.035; ctx.font = 'bold 58px sans-serif';
    for (let y=80;y<canvas.height+200;y+=180) for(let x=-100;x<1200;x+=370) {ctx.save();ctx.translate(x,y);ctx.rotate(-0.35);ctx.fillText('GameArena',0,0);ctx.restore();}
    ctx.restore();
    ctx.fillStyle = '#080f1d'; for(let x=48;x<1080;x+=64){ctx.beginPath();ctx.arc(x,24,12,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.arc(x,canvas.height-24,12,0,Math.PI*2);ctx.fill();}
    ctx.fillStyle = '#34d399'; ctx.beginPath(); ctx.roundRect(64,52,64,64,16);ctx.fill(); ctx.fillStyle = '#04241b'; ctx.font = 'bold 42px sans-serif'; ctx.fillText('G',79,100);
    ctx.fillStyle = '#edf4fb'; ctx.font = 'bold 38px sans-serif'; ctx.fillText('GameArena',148,98);
    ctx.fillStyle = '#a5b4c8'; ctx.font = '28px sans-serif'; ctx.fillText('Transaction receipt',64,170);
    ctx.strokeStyle = '#26354b'; ctx.beginPath();ctx.moveTo(64,475);ctx.lineTo(1016,475);ctx.stroke();
    ctx.textAlign = 'center'; ctx.fillStyle = '#a5b4c8'; ctx.font = '30px sans-serif'; ctx.fillText(receipt.dataset.receiptType,540,282);
    ctx.fillStyle = '#edf4fb'; ctx.font = 'bold 62px sans-serif'; ctx.fillText(receipt.dataset.receiptAmount,540,367);
    ctx.fillStyle = receipt.dataset.receiptStatus === 'Successful' ? '#34d399' : receipt.dataset.receiptStatus === 'Failed' ? '#f87171' : '#fbbf24';
    ctx.font = 'bold 30px sans-serif'; ctx.fillText(receipt.dataset.receiptStatus,540,428); ctx.textAlign = 'left';
    let y = 555;
    for (const row of details) {
      ctx.font = '26px sans-serif'; ctx.fillStyle = '#a5b4c8'; ctx.fillText(row.label,64,y);
      ctx.font = row.font; ctx.fillStyle = '#edf4fb'; row.lines.forEach((line,i) => ctx.fillText(line,430,y+i*36));
      y += Math.max(65,row.lines.length * 36 + 24);
    }
    ctx.fillStyle = '#a5b4c8'; ctx.font = '24px sans-serif'; ctx.fillText('gamearena01.com · Status recorded on this receipt',64,y+40);
    ctx.fillText('For support, quote your GameArena transaction ID.',64,y+80);
    const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/png'));
    if (!blob) throw new Error('Receipt could not be created. Please try again.');
    return {image:new File([blob],receipt.dataset.receiptId+'.png',{type:'image/png'}),pdf:pdfFile(canvas)};
  }
  function pdfFile(canvas) {
    const jpeg = Uint8Array.from(atob(canvas.toDataURL('image/jpeg',0.93).split(',')[1]), char => char.charCodeAt(0));
    const encoder = new TextEncoder(), chunks = [], offsets = [0]; let length = 0;
    const add = data => {const bytes = typeof data === 'string' ? encoder.encode(data) : data; chunks.push(bytes); length += bytes.length;};
    const object = (id,content) => {offsets[id]=length;add(id+' 0 obj\n');add(content);add('\nendobj\n');};
    add('%PDF-1.4\n');
    object(1,'<< /Type /Catalog /Pages 2 0 R >>');
    object(2,'<< /Type /Pages /Kids [3 0 R] /Count 1 >>');
    object(3,'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Receipt 4 0 R >> >> /Contents 5 0 R >>');
    offsets[4]=length;add('4 0 obj\n<< /Type /XObject /Subtype /Image /Width '+canvas.width+' /Height '+canvas.height+' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length '+jpeg.length+' >>\nstream\n');add(jpeg);add('\nendstream\nendobj\n');
    const scale=Math.min(515/canvas.width,762/canvas.height),w=canvas.width*scale,h=canvas.height*scale;
    const commands='q '+w.toFixed(3)+' 0 0 '+h.toFixed(3)+' '+((595-w)/2).toFixed(3)+' '+(802-h).toFixed(3)+' cm /Receipt Do Q';
    object(5,'<< /Length '+encoder.encode(commands).length+' >>\nstream\n'+commands+'\nendstream');
    const xref=length;add('xref\n0 6\n0000000000 65535 f \n');
    for(let i=1;i<=5;i++)add(String(offsets[i]).padStart(10,'0')+' 00000 n \n');
    add('trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+xref+'\n%%EOF\n');
    return new File(chunks,receipt.dataset.receiptId+'.pdf',{type:'application/pdf'});
  }
  const dialog=document.getElementById('receiptShareDialog'), preview=document.getElementById('receiptSharePreview');
  const shareStatus=document.getElementById('receiptShareStatus');
  const imageButton=document.getElementById('shareReceiptImage'), pdfButton=document.getElementById('shareReceiptPdf');
  let preparedFiles;
  imageButton.disabled=pdfButton.disabled=true;
  receiptFiles().then(files=>{preparedFiles=files;preview.src=URL.createObjectURL(files.image);imageButton.disabled=pdfButton.disabled=false;shareStatus.textContent='Choose a format. Shared account numbers are masked.';}).catch(()=>{shareStatus.textContent='Unable to create your receipt. Refresh and try again.';});
  button.addEventListener('click',()=>dialog.showModal());
  document.getElementById('closeReceiptShare').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();}});
  async function share(file) {
    imageButton.disabled=pdfButton.disabled=true;
    try {
      if (navigator.share && navigator.canShare?.({files:[file]})) {
        await navigator.share({title:'GameArena transaction receipt',files:[file]}); shareStatus.textContent='Receipt sent to your selected app.';
      } else {
        const url=URL.createObjectURL(file),link=document.createElement('a');
        link.href=url;link.download=file.name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
        shareStatus.textContent='Receipt downloaded. You can share this file from your device.';
      }
    } catch(error) {shareStatus.textContent=error.name==='AbortError'?'Sharing cancelled.':error.name==='NotAllowedError'?'File sharing was blocked by your browser. Allow sharing or try another browser.':(error.message||'Unable to share this receipt.');}
    finally {imageButton.disabled=pdfButton.disabled=false;}
  }
  imageButton.addEventListener('click',()=>{if(preparedFiles)share(preparedFiles.image);});
  pdfButton.addEventListener('click',()=>{if(preparedFiles)share(preparedFiles.pdf);});
})();
