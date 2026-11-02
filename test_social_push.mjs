import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./static/sw.js',import.meta.url),'utf8');
function worker({visible=false,existing=[]}={}){
 const handlers={},shown=[],messages=[];
 const self={location:{origin:'https://gamearena.test'},addEventListener:(name,fn)=>handlers[name]=fn,
  clients:{matchAll:async()=>visible?[{visibilityState:'visible',postMessage:data=>messages.push(data)}]:[]},
  registration:{getNotifications:async()=>existing,showNotification:async(title,options)=>shown.push({title,...options})}};
 vm.runInNewContext(source,{self,URL,console});
 return {shown,messages,async push(data){let pending;handlers.push({data:{json:()=>data},waitUntil:promise=>pending=promise});await pending;}};
}
test('visible app receives a message popup event instead of a tray notification',async()=>{
 const w=worker({visible:true});await w.push({id:1,kind:'messages',group:'messages',body:'Hello'});
 assert.equal(w.shown.length,0);assert.equal(w.messages[0].type,'gamearena-message');
});
test('background message summaries share a stable tag and keep at most seven sender entries',async()=>{
 const w=worker();const entries=Array.from({length:9},(_,i)=>({sender_id:i}));
 await w.push({id:2,kind:'messages',group:'messages',entries,version:2,url:'/chat',body:'Two messages'});
 await w.push({id:3,kind:'messages',group:'messages',entries,version:3,url:'/chat',body:'Three messages'});
 assert.equal(w.shown[0].tag,w.shown[1].tag);assert.equal(w.shown[1].data.entries.length,7);
 assert.equal(w.shown[1].data.url,'/chat');
});
test('friend requests use their own category and older queued pushes cannot overwrite a newer summary',async()=>{
 const w=worker({existing:[{data:{version:10}}]});await w.push({id:2,group:'messages',version:2});assert.equal(w.shown.length,0);
 const request=worker();await request.push({id:5,kind:'requests',group:'requests',version:5,url:'https://untrusted.example/'});
 assert.equal(request.shown[0].tag,'gamearena-requests');assert.equal(request.shown[0].data.url,'/notifications');
});
