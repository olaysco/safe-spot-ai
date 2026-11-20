const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const loadDesk=source.slice(source.indexOf('async function loadDesk('),source.indexOf('function matches('));
function setup(loaded=true){
  const pending=[],renders=[],messages=[],calls=[];
  const context={navigationVersion:1,deskLoaded:loaded,deskRequest:null,user:{id:'manager',role:'manager'},view:'desk',cases:[],staff:[],groups:[],
    api(path){calls.push(path);return new Promise((resolve,reject)=>pending.push({resolve,reject}));},
    render(html){renders.push(html);},message(...args){messages.push(args);},dashboard(){return 'Dashboard';},caseQueue(){return 'Cases';},workspaceHeader(){return 'Header';}};
  vm.createContext(context);vm.runInContext(loadDesk,context);
  return {context,pending,renders,messages,calls};
}
test('Returning to the dashboard displays cached records before the server responds',async()=>{
  const s=setup();const request=s.context.loadDesk();
  assert.deepEqual(s.renders,['Dashboard']);
  assert.deepEqual(s.messages,[['Refreshing records…']]);
  s.pending.forEach(p=>p.resolve([]));await request;
  assert.equal(s.renders.length,2);
});
test('Repeated dashboard clicks share one pending data request',async()=>{
  const s=setup();const first=s.context.loadDesk();s.context.navigationVersion++;
  const second=s.context.loadDesk();
  assert.deepEqual(s.calls,['/cases','/staff']);
  s.pending.forEach(p=>p.resolve([]));await Promise.all([first,second]);
  assert.equal(s.renders.length,3);
});
test('A late response cannot replace the report page',async()=>{
  const s=setup();const request=s.context.loadDesk();
  s.context.view='report';s.context.navigationVersion++;
  s.pending.forEach(p=>p.resolve([{id:'late'}]));await request;
  assert.equal(s.renders.length,1);
  assert.deepEqual(s.context.cases,[]);
});
test('A failed refresh keeps cached records and shows the failure',async()=>{
  const s=setup();const request=s.context.loadDesk();
  s.pending[0].reject(new Error('Offline'));s.pending[1].resolve([]);await request;
  assert.equal(s.renders.length,1);
  assert.match(s.messages.at(-1)[0],/last loaded records/);
  assert.equal(s.messages.at(-1)[1],true);
});
test('The first dashboard visit shows a loading state',async()=>{
  const s=setup(false);const request=s.context.loadDesk();
  assert.match(s.renders[0],/Loading records/);
  s.pending.forEach(p=>p.resolve([]));await request;
  assert.equal(s.renders.at(-1),'Dashboard');
});
