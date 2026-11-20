const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8');
const helpers=source.slice(source.indexOf('function photoRecord('),source.indexOf('function reportView('));
function setup(){
  const file=Object.assign(new Blob(['photo'],{type:'image/jpeg'}),{name:'evidence.jpg'}),revoked=[];
  let resolve,reject,calls=0;
  const context={photos:[file],photoReview:new Map(),photoConsent:true,draft:{description:'Original report'},FormData,
    URL:{createObjectURL:()=> 'blob:preview',revokeObjectURL:url=>revoked.push(url)},$:()=>null,
    api(){calls++;return new Promise((yes,no)=>{resolve=yes;reject=no;});}};
  vm.createContext(context);vm.runInContext(helpers,context);
  return {context,file,revoked,get resolve(){return resolve;},get reject(){return reject;},get calls(){return calls;}};
}
test('Photo analysis requires separate consent',async()=>{
  const s=setup();s.context.photoConsent=false;await s.context.analyseReportPhoto(0);
  assert.equal(s.calls,0);assert.equal(s.context.photos.length,1);
});
test('An analysis failure preserves the report and selected photo',async()=>{
  const s=setup(),pending=s.context.analyseReportPhoto(0);
  s.reject(new Error('Service unavailable.'));await pending;
  assert.equal(s.context.draft.description,'Original report');
  assert.equal(s.context.photos[0],s.file);
  assert.match(s.context.photoReview.get(s.file).error,/unchanged/);
  assert.equal(s.context.photoReview.get(s.file).busy,false);
});
test('A late analysis cannot restore photos after report cleanup',async()=>{
  const s=setup(),pending=s.context.analyseReportPhoto(0);
  s.context.clearReportPhotos();
  s.resolve({observations:['Cable across a route'],possible_hazards:[],question:'',uncertainty:'Check the photo.'});await pending;
  assert.equal(s.context.photos.length,0);assert.equal(s.context.photoReview.size,0);
  assert.deepEqual(s.revoked,['blob:preview']);
  assert.equal(s.context.draft.description,'Original report');
});
test('AI observations do not change report text without confirmation',async()=>{
  const s=setup(),pending=s.context.analyseReportPhoto(0);
  s.resolve({observations:['Cable across a route'],possible_hazards:['Possible trip hazard'],question:'',uncertainty:'Check the photo.'});await pending;
  assert.equal(s.context.draft.description,'Original report');
  assert.equal(s.context.photoReview.get(s.file).applied,false);
});
function sampleSetup(){
  const s=setup();
  Object.assign(s.context,{samplePhotoLoading:false,File,fetch:async()=>({ok:true,blob:async()=>new Blob(['sample'],{type:'image/png'})}),message:()=>{}});
  return s;
}
test('The sample preserves report text and does not enable AI consent',async()=>{
  const s=sampleSetup();s.context.photoConsent=false;
  await s.context.addSamplePhoto();await s.context.addSamplePhoto();
  assert.equal(s.context.photos.length,2);
  assert.equal(s.context.photos[1].type,'image/png');
  assert.equal(s.context.photoConsent,false);
  assert.equal(s.context.draft.description,'Original report');
  assert.equal(s.calls,0);
});
test('A sample download cannot exceed the photo limit',async()=>{
  const s=sampleSetup();let finish;
  s.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
  const pending=s.context.addSamplePhoto();
  s.context.photos.push(s.file,s.file);
  finish({ok:true,blob:async()=>new Blob(['sample'])});await pending;
  assert.equal(s.context.photos.length,3);
});
test('A sample download cannot restore a cleared report',async()=>{
  const s=sampleSetup();let finish;
  s.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
  const pending=s.context.addSamplePhoto();s.context.clearReportPhotos();
  finish({ok:true,blob:async()=>new Blob(['sample'])});await pending;
  assert.equal(s.context.photos.length,0);
});
test('A failed sample download permits another attempt',async()=>{
  const s=sampleSetup();s.context.fetch=async()=>({ok:false});
  await s.context.addSamplePhoto();
  assert.equal(s.context.photos.length,1);assert.equal(s.context.samplePhotoLoading,false);
});
