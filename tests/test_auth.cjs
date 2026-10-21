const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../frontend/auth.js'),'utf8');
function setup(search='') {
  const memory = new Map(); let destination='', fetchCount=0;
  const cfg={domain:'https://example.auth.ap-south-1.amazoncognito.com',clientId:'client',redirectUri:'http://localhost:8000/',logoutUri:'http://localhost:8000/',apiUrl:'https://api.example/prod',scopes:'openid aquacloud/read aquacloud/export'};
  const ctx={window:{AQUACLOUD_AUTH:cfg},crypto:require('node:crypto').webcrypto,TextEncoder,Uint8Array,URL,URLSearchParams,btoa,atob,Date,sessionStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},location:{search,pathname:'/',assign:v=>destination=v},history:{replaceState:()=>{}},fetch:async()=>{fetchCount++;throw new Error('unexpected fetch');}};
  vm.createContext(ctx); vm.runInContext(source,ctx);
  return {auth:ctx.window.AquaAuth,ctx,memory,get destination(){return destination},get fetchCount(){return fetchCount}};
}
test('PKCE uses S256, cryptographic state and one-use verifier',async()=>{
  const t=setup(); await t.auth.login(); const url=new URL(t.destination); const txn=JSON.parse(t.memory.get('aquacloud.pkce'));
  assert.equal(url.searchParams.get('response_type'),'code'); assert.equal(url.searchParams.get('code_challenge_method'),'S256');
  const hash=require('node:crypto').createHash('sha256').update(txn.verifier).digest('base64url');
  assert.equal(url.searchParams.get('code_challenge'),hash); assert.equal(url.searchParams.get('state'),txn.state); assert.equal(txn.verifier.length,43);
});
test('missing or wrong state prevents code exchange',async()=>{
  for(const query of ['?code=bad','?code=bad&state=wrong']) { const t=setup(query); await assert.rejects(t.auth.initialize()); assert.equal(t.fetchCount,0); }
});
test('expired transaction prevents code exchange',async()=>{
  const t=setup('?code=bad&state=state'); t.memory.set('aquacloud.pkce',JSON.stringify({state:'state',verifier:'x',created:Date.now()-700000}));
  await assert.rejects(t.auth.initialize()); assert.equal(t.fetchCount,0); assert.equal(t.memory.size,0);
});
test('tokens never go to an arbitrary API and anonymous requests fail',()=>{
  const t=setup(); assert.throws(()=>t.auth.headers('https://attacker.example')); assert.throws(()=>t.auth.headers('https://api.example/prod')); assert.equal(t.auth.canExport(),false);
});
test('valid code exchange keeps tokens in memory and applies UI role',async()=>{
  const t=setup('?code=test&state=state');t.memory.set('aquacloud.pkce',JSON.stringify({state:'state',verifier:'verifier',created:Date.now()}));
  const token='header.'+Buffer.from(JSON.stringify({token_use:'access',client_id:'client',exp:Math.floor(Date.now()/1000)+600,'cognito:groups':['Operator']})).toString('base64url')+'.signature';
  t.ctx.fetch=async(url,options)=>{assert.equal(url,'https://example.auth.ap-south-1.amazoncognito.com/oauth2/token');assert.equal(options.body.get('code_verifier'),'verifier');return {ok:true,json:async()=>({token_type:'Bearer',access_token:token,expires_in:600})};};
  await t.auth.initialize();assert.equal(t.auth.canExport(),true);assert.equal(t.memory.size,0);assert.equal(t.auth.headers('https://api.example/prod').Authorization,'Bearer '+token);t.auth.clear();assert.equal(t.auth.signedIn(),false);
});
