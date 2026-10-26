const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const catalog=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c',`
import ast,json,pathlib
module=ast.parse(pathlib.Path('gamearena/market.py').read_text(encoding='utf-8'))
node=next(n.value for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CATALOG' for t in n.targets))
print(json.dumps({ast.literal_eval(k):{kw.arg:ast.literal_eval(kw.value) for kw in v.keywords} for k,v in zip(node.keys,node.values)}))
`],{cwd:root,encoding:'utf8'}));
for(const item of Object.values(catalog)) item.current_price=item.price;
function shop(selected='arena-origin', collectionOptions=null) {
  function element(){return {dataset:{},style:{values:{},setProperty(key,value){this.values[key]=value;}}};}
  const elements={};
  for(const key of ['.player-cover','.player-avatar','.player-name','[data-selected-name]','[data-selected-description]','[data-bundle-note]','.shop-confirm-area','[data-feedback]'])elements[key]=element();
  const button={};
  const form={elements:{item_key:{},price_gp:{},confirm:{}},querySelector:()=>button,addEventListener:()=>{}};
  elements['#shop-action']=form;
  let click;
  const data={catalog,owned:[],equipped:{frame:'',card:'',nameplate:''},selected,buyBase:'/shop/',equipUrl:'/shop/equip'};
  const intervals=new Map(),timeouts=new Map(),listeners={},trackListeners={};let nextTimer=0;
  const track={clientWidth:390,scrollLeft:0,classList:{add(){},remove(){}},addEventListener:(name,fn)=>{trackListeners[name]=fn;},scrollTo({left}){this.scrollLeft=left;},setPointerCapture(){},hasPointerCapture(){return false;}};
  const collections=collectionOptions?{querySelectorAll:()=>Array(5).fill({}),querySelector:()=>track,contains:()=>false,addEventListener:(name,fn)=>{listeners[name]=fn;}}:null;
  elements['[data-shop-collections]']=collections;
  const page={querySelector:key=>elements[key],querySelectorAll:()=>[],addEventListener:(type,handler)=>{if(type==='click')click=handler;}};
  const context={window:{addEventListener(){}},setInterval:(fn,ms)=>{const id=++nextTimer;intervals.set(id,{fn,ms});return id;},clearInterval:id=>intervals.delete(id),setTimeout:(fn)=>{const id=++nextTimer;timeouts.set(id,fn);return id;},clearTimeout:id=>timeouts.delete(id),document:{body:{dataset:{}},hidden:false,activeElement:null,addEventListener(){},getElementById:id=>id==='arena-shop'?page:{textContent:JSON.stringify(data)}},URL,location:{href:'https://example.test/shop'},history:{replaceState(){}},matchMedia:()=>({matches:!!collectionOptions?.reduced})};
  vm.runInNewContext(fs.readFileSync(path.join(root,'static/js/shop.js'),'utf8'),context);
  return {elements,form,button,track,trackListeners,intervals,settle(){for(const fn of timeouts.values())fn();timeouts.clear();},tryOn(key){click({preventDefault(){},target:{closest:selector=>selector==='[data-try]'?{dataset:{try:key}}:null}});}};
}
function color(view,slot){return view.elements[slot].style.values['--selected'];}
test('every frame and nameplate retains its own colour when other slots change',()=>{
  const view=shop('vanguard-frame');
  view.tryOn('emerald-nameplate');
  assert.equal(color(view,'.player-avatar'),'#73edc0');
  for(const [key,item] of Object.entries(catalog).filter(([,item])=>item.slot==='frame')) {
    view.tryOn(key);
    assert.equal(color(view,'.player-avatar'),item.color);
    for(const [nameplate,plate] of Object.entries(catalog).filter(([,item])=>item.slot==='nameplate')) {
      view.tryOn(nameplate);
      const plateColor=color(view,'.player-name');
      assert.equal(color(view,'.player-avatar'),item.color);
      for(const [card] of Object.entries(catalog).filter(([,item])=>item.slot==='card')) {
        view.tryOn(card);
        assert.equal(color(view,'.player-avatar'),item.color);
        assert.equal(color(view,'.player-name'),plateColor);
      }
    }
  }
});
test('bundles replace their three slots; individual try-ons only replace their own slot',()=>{
  const view=shop('emerald-bundle');
  const green=color(view,'.player-avatar'),name=color(view,'.player-name');
  view.tryOn('midnight-card');
  assert.equal(color(view,'.player-cover'),'#c4a2ff');
  assert.equal(color(view,'.player-avatar'),green);
  assert.equal(color(view,'.player-name'),name);
  view.tryOn('neon-bundle');
  assert.equal(color(view,'.player-avatar'),catalog['neon-circuit'].color);
  assert.equal(color(view,'.player-name'),'#c4a2ff');
});
test('mixing previews keeps payment action and consent scoped to the selected item',()=>{
  const view=shop('vanguard-frame');
  view.form.elements.confirm.checked=true;
  view.tryOn('solar-nameplate');
  assert.equal(view.form.action,'/shop/solar-nameplate/buy');
  assert.equal(view.form.elements.price_gp.value,'250');
  assert.equal(view.form.elements.confirm.checked,false);
  assert.equal(view.form.elements.confirm.required,true);
  assert.equal(color(view,'.player-avatar'),catalog['vanguard-frame'].color);
});


test('five collection slides advance every four seconds and wrap without changing the try-on',()=>{
  const view=shop('obsidian-card',{});
  const tick=()=>{const timer=[...view.intervals.values()][0];assert.equal(timer.ms,4000);timer.fn();};
  for(let index=1;index<=5;index++){tick();assert.equal(view.track.scrollLeft,(index%5)*390);}
  assert.equal(view.elements['.player-cover'].dataset.arenaCard,'obsidian-card');
  assert.equal(view.form.elements.item_key.value,'obsidian-card');
});
test('collection keyboard and mouse drag navigate independently of purchasing',()=>{
  const view=shop('astral-card',{});
  view.trackListeners.keydown({target:view.track,key:'End',preventDefault(){}});
  assert.equal(view.track.scrollLeft,4*390);
  view.trackListeners.keydown({target:view.track,key:'Home',preventDefault(){}});
  view.trackListeners.pointerdown({button:0,pointerType:'mouse',pointerId:1,clientX:350,clientY:90});
  view.trackListeners.pointermove({pointerId:1,clientX:40,clientY:92,preventDefault(){}});
  view.trackListeners.pointerup({pointerId:1});
  assert.equal(view.track.scrollLeft,390);
  let prevented=false;view.trackListeners.click({preventDefault(){prevented=true;},stopPropagation(){}});
  assert.equal(prevented,true);
  assert.equal(view.form.elements.item_key.value,'astral-card');
});
test('reduced motion keeps manual collection navigation without autoplay',()=>{
  const view=shop('frost-card',{reduced:true});
  assert.equal(view.intervals.size,0);
  view.trackListeners.keydown({target:view.track,key:'ArrowRight',preventDefault(){}});
  assert.equal(view.track.scrollLeft,390);
  view.track.scrollLeft=3*390;view.trackListeners.scroll();view.settle();
  assert.equal(view.intervals.size,0);
});
