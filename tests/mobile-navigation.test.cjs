const {test}=require('node:test');const assert=require('node:assert/strict');
const {destination}=require('../static/js/mobile-navigation.js');
test('right advances Tournaments to Leaderboard; left returns',()=>{
 assert.equal(destination(1,4,130,10,250),2);assert.equal(destination(2,4,-130,10,250),1);
});
test('vertical scrolling, short movements and long presses do not navigate',()=>{
 for(const [dx,dy,ms] of [[30,0,200],[100,90,200],[95,60,200],[120,0,900],[120,0,10]])assert.equal(destination(1,4,dx,dy,ms),-1);
});
test('main tabs do not wrap beyond either end',()=>{
 assert.equal(destination(0,4,-120,0,200),-1);assert.equal(destination(3,4,120,0,200),-1);
});
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
test('page gestures respect forms, browser edges, carousels and vertical scrolling',()=>{
 function gesture({blocked=false,x=100,vertical=false}={}){
  const handlers={},links=['/','/tournaments','/leaderboard','/profile'].map((href,i)=>({href:'https://gamearena01.com'+href,hasAttribute:()=>i===1}));
  const nav={querySelectorAll:()=>links};let now=0,result=null;
  const target={closest:()=>blocked?{}:null,scrollWidth:100,clientWidth:100,parentElement:null};
  const context={URL,innerWidth:390,matchMedia:()=>({matches:true}),performance:{now:()=>now},getComputedStyle:()=>({overflowX:'visible'}),location:{href:'https://gamearena01.com/tournaments',origin:'https://gamearena01.com',assign:value=>{result=value;}},window:{getSelection:()=>'',addEventListener(){}},document:{activeElement:null,body:{},querySelector:q=>q.startsWith('.ga-bottom-nav')?nav:null,addEventListener:(name,handler)=>{handlers[name]=handler;}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/js/mobile-navigation.js'),'utf8'),context);
  handlers.touchstart({target,touches:[{clientX:x,clientY:100}]});now=250;
  if(vertical)handlers.touchmove({touches:[{clientX:x+10,clientY:190}]});
  handlers.touchend({touches:[],changedTouches:[{clientX:x+140,clientY:110}]});return result;
 }
 assert.equal(gesture(),'https://gamearena01.com/leaderboard');
 assert.equal(gesture({blocked:true}),null);assert.equal(gesture({x:10}),null);assert.equal(gesture({vertical:true}),null);
});
