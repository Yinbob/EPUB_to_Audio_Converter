// 纯离线事件逻辑夹具，不启动浏览器，不代表真实听众回答或视觉验收。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const page = fs.readFileSync(process.argv[2], 'utf8');
const payload = page.match(/<script id="trial-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
const data = JSON.parse(payload);
function fixture(saved = null, brokenStorage = false) {
  class Element {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.value = ''; this.textContent = ''; this.disabled = false; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren() { this.children = []; }
    setAttribute(key, value) { this[key] = value; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    click() { if (!this.disabled) this.listeners.click?.({target:this}); }
    pause() { this.paused = true; }
    focus() { this.focused = true; }
  }
  const elements = new Map();
  for (const id of ['trial-data','storage-warning','notice','position','answered','progress','target','choices','references','previous','next','skip','download','participant','start','clear']) elements.set(id,new Element(id==='target'?'audio':'div'));
  elements.get('trial-data').textContent = payload;
  elements.get('storage-warning').hidden = true;
  const store = new Map(saved ? [['role-listening:'+data.pack_id,JSON.stringify(saved)]] : []);
  const blobs = [], confirmations = [], links = [], documentListeners = {};
  const context = vm.createContext({
    document:{getElementById:id=>elements.get(id),createElement:tag=>{const e=new Element(tag);if(tag==='a')links.push(e);return e;},createTextNode:text=>({textContent:text}),querySelectorAll:()=>[elements.get('target'),...elements.get('references').children.map(row=>row.children[1])],addEventListener:(name,cb)=>documentListeners[name]=cb},
    sessionStorage:{getItem:key=>{if(brokenStorage)throw Error('unavailable');return store.get(key)||null;},setItem:(key,value)=>{if(brokenStorage)throw Error('unavailable');store.set(key,value);},removeItem:key=>store.delete(key)},
    confirm:()=>confirmations.length ? confirmations.shift() : true,
    Blob, URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:unit-test';},revokeObjectURL:()=>{}},setTimeout:cb=>cb(),
  });
  vm.runInContext(script, context, {timeout:1000});
  return {context,elements,store,blobs,confirmations,links,
    select:role=>{const input=elements.get('references').children.find(row=>row.children[0].children[0].value===role).children[0].children[0];input.listeners.change();},
    get:id=>elements.get(id),
  };
}
async function main() {
  const f = fixture();
  assert.equal(f.get('choices').disabled,true);
  assert.equal(f.get('download').disabled,true);
  f.get('participant').value='=BAD'; f.get('start').click();
  assert.equal(f.get('choices').disabled,true);
  f.get('participant').value='synthetic_qa'; f.get('start').click();
  assert.equal(f.get('choices').disabled,false);
  assert.equal(f.get('participant').readOnly,true);
  const role=Object.keys(data.trials[0].reference_voices)[0];
  f.select(role); assert.equal(f.get('answered').textContent,`已回答 1 / ${data.trials.length}`);
  f.get('next').click(); f.get('previous').click();
  assert.equal(f.get('references').children[0].children[0].children[0].checked,true);
  f.get('download').click();
  const csv=await f.blobs[0].text();
  assert.equal(f.links[0].download,'responses_synthetic_qa.csv');
  assert(csv.includes(`"synthetic_qa","${data.trials[0].trial_id}","${role}"`));
  assert(csv.includes(`"","${data.trials[1].trial_id}",""`));
  assert.equal(csv.trim().split('\r\n').length,data.trials.length+1);
  const saved=JSON.parse([...f.store.values()][0]);
  const resumed=fixture(saved);
  assert.equal(resumed.get('participant').value,'synthetic_qa');
  assert.equal(resumed.get('answered').textContent,`已回答 1 / ${data.trials.length}`);
  resumed.confirmations.push(false);resumed.get('clear').click();
  assert.equal(resumed.get('choices').disabled,false);
  resumed.get('skip').click();assert.equal(resumed.get('answered').textContent,`已回答 0 / ${data.trials.length}`);
  resumed.get('clear').click();assert.equal(resumed.get('choices').disabled,true);
  const tampered=fixture({...saved,responses:{unknown:'角色1',[data.trials[0].trial_id]:'invalid'}});
  assert.equal(tampered.get('answered').textContent,`已回答 0 / ${data.trials.length}`);
  const limited=fixture(null,true);
  assert.equal(limited.get('storage-warning').hidden,false);
  limited.get('participant').value='synthetic_qa';limited.get('start').click();
  limited.select(role);limited.get('download').click();assert.equal(limited.blobs.length,1);
  process.stdout.write(JSON.stringify({checks:'offline_events_and_csv',synthetic_only:true,csv}));
}
main().catch(error=>{console.error(error);process.exit(1);});
