const {test}=require('node:test');
const assert=require('node:assert/strict');
const {check,activeToken}=require('../static/js/chat-mentions.js');
test('mention suggestions narrow the token at the caret without parsing emails',()=>{
 assert.deepEqual(activeToken('Hello @Bat',10),{start:6,end:10,query:'Bat'});
 assert.deepEqual(activeToken('@B other',2),{start:0,end:2,query:'B'});
 assert.equal(activeToken('mail@example.com',16),null);
 assert.equal(activeToken('Hello @Batman ',14),null);
});
test('five individual mentions maximum and no group tags',()=>{
 assert.equal(check('@B @C @D @E @F'),'');
 assert.match(check('@B @C @D @E @F @G'),/at most 5/);
 for(const text of ['@all','@Everyone','@HERE'])assert.match(check(text),/unavailable/);
 assert.equal(check('mail@example.com @Batman'),'');
});
