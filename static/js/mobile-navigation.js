/* Main-tab gestures: right advances, left returns. Native scrolling stays native. */
(() => {
  function destination(index,count,dx,dy,elapsed) {
    if (Math.abs(dx)<90 || Math.abs(dy)>65 || Math.abs(dx)<Math.abs(dy)*1.8 || elapsed>700 || elapsed<40) return -1;
    const next=index+(dx>0?1:-1);
    return next>=0 && next<count ? next : -1;
  }
  if(typeof module!=='undefined' && module.exports){module.exports={destination};return;}
  const nav=document.querySelector('.ga-bottom-nav[data-tab-swipe=true]');
  if(!nav)return;
  const links=[...nav.querySelectorAll('a')],index=links.findIndex(link=>link.hasAttribute('aria-current'));
  if(index<0)return;
  const excluded='a,button,input,textarea,select,form,[contenteditable],[role=slider],dialog,[data-menu],[data-carousel],[data-shop-collections],[data-no-tab-swipe],.ga-chat-shell,.ga-bottom-nav';
  let start=null,navigating=false;
  function blocked(target){
    if(target.closest(excluded) || document.querySelector('dialog[open],[data-menu][open]'))return true;
    for(let node=target;node && node!==document.body;node=node.parentElement){
      if(node.scrollWidth>node.clientWidth+2 && /auto|scroll/.test(getComputedStyle(node).overflowX))return true;
    }
    return false;
  }
  document.addEventListener('touchstart',event=>{
    start=null;
    if(navigating || !matchMedia('(max-width:767px)').matches || event.touches.length!==1 || blocked(event.target))return;
    if(document.activeElement?.matches('input,textarea,select,[contenteditable]'))return;
    const point=event.touches[0];
    // Leave the edges to the browser/OS back and forward gestures.
    if(point.clientX<32 || point.clientX>innerWidth-32)return;
    start={x:point.clientX,y:point.clientY,time:performance.now()};
  },{passive:true});
  document.addEventListener('touchmove',event=>{
    if(!start)return;
    if(event.touches.length!==1){start=null;return;}
    const point=event.touches[0];
    if(Math.abs(point.clientY-start.y)>65)start=null;
  },{passive:true});
  document.addEventListener('touchcancel',()=>{start=null;},{passive:true});
  document.addEventListener('touchend',event=>{
    const gesture=start;start=null;
    if(!gesture || event.touches.length || event.changedTouches.length!==1 || String(window.getSelection()||'').trim())return;
    const point=event.changedTouches[0];
    const next=destination(index,links.length,point.clientX-gesture.x,point.clientY-gesture.y,performance.now()-gesture.time);
    if(next<0)return;
    const target=new URL(links[next].href,location.href);
    if(target.origin!==location.origin)return;
    navigating=true;location.assign(target.href);
  },{passive:true});
  window.addEventListener('pageshow',()=>{navigating=false;start=null;});
})();
