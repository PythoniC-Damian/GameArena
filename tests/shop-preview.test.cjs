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
function shop(selected='arena-origin') {
  function element(){return {style:{values:{},setProperty(key,value){this.values[key]=value;}}};}
  const elements={};
  for(const key of ['.player-cover','.player-avatar','.player-name','[data-selected-name]','[data-selected-description]','[data-bundle-note]','.shop-confirm-area','[data-feedback]'])elements[key]=element();
  const button={};
  const form={elements:{item_key:{},price_gp:{},confirm:{}},querySelector:()=>button,addEventListener:()=>{}};
  elements['#shop-action']=form;
  let click;
  const data={catalog,owned:[],equipped:{frame:'',card:'',nameplate:''},selected,buyBase:'/shop/',equipUrl:'/shop/equip'};
  const page={querySelector:key=>elements[key],querySelectorAll:()=>[],addEventListener:(type,handler)=>{if(type==='click')click=handler;}};
  const context={window:{},document:{getElementById:id=>id==='arena-shop'?page:{textContent:JSON.stringify(data)}},URL,location:{href:'https://example.test/shop'},history:{replaceState(){}},matchMedia:()=>({matches:false})};
  vm.runInNewContext(fs.readFileSync(path.join(root,'static/js/shop.js'),'utf8'),context);
  return {elements,form,button,tryOn(key){click({preventDefault(){},target:{closest:selector=>selector==='[data-try]'?{dataset:{try:key}}:null}});}};
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

