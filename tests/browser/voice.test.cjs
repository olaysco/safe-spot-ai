const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app/static/voice.js', 'utf8');
function setup(supported=true) {
  let instance;
  class Recognition {
    constructor(){instance=this;}
    start(){this.onstart();}
    stop(){this.onend();}
    abort(){this.aborted=true;this.onend();}
  }
  const window={isSecureContext:true,addEventListener(){},SpeechRecognition:supported?Recognition:null};
  vm.runInNewContext(source,{window,document:{addEventListener(){}}});
  const input={value:'Original words',readOnly:false};
  const button={disabled:false,setAttribute(){},addEventListener(event,fn){this.click=fn;}};
  const status={textContent:''};
  let saved='';
  const preview={final:{textContent:''},interim:{textContent:''}};
  window.SafeSpotVoice.attach(input,button,status,text=>{saved=text;},preview);
  return {input,button,status,preview,window,get instance(){return instance;},get saved(){return saved;}};
}
test('Voice input appends text once and restores editing',()=>{
  const s=setup();s.button.click();
  assert.equal(s.input.readOnly,true);
  const result=Object.assign([{transcript:'New spoken words'}],{isFinal:true});
  s.instance.onresult({resultIndex:0,results:[result]});
  s.instance.onresult({resultIndex:0,results:[result]});
  assert.equal(s.saved,'Original words New spoken words');
  s.button.click();
  assert.equal(s.input.readOnly,false);
  assert.match(s.status.textContent,/Check and edit/);
});
test('Permission failure preserves text and permits another attempt',()=>{
  const s=setup();s.button.click();s.instance.onerror({error:'not-allowed'});
  assert.equal(s.input.value,'Original words');
  assert.equal(s.input.readOnly,false);
  assert.equal(s.button.disabled,false);
  assert.match(s.status.textContent,/Microphone access/);
});
test('Navigation stops recognition and ignores late results',()=>{
  const s=setup();s.button.click();s.window.SafeSpotVoice.stop();
  assert.equal(s.instance.aborted,true);
  s.instance.onresult({resultIndex:0,results:[Object.assign([{transcript:'Late text'}],{isFinal:true})]});
  assert.equal(s.input.value,'Original words');
});
test('Unsupported browsers keep typing available',()=>{
  const s=setup(false);
  assert.equal(s.button.disabled,true);
  assert.equal(s.input.readOnly,false);
  assert.match(s.status.textContent,/unavailable/);
});

test('Interim speech stays separate from confirmed transcript',()=>{
  const s=setup();s.button.click();
  s.instance.onresult({resultIndex:0,results:[Object.assign([{transcript:'Unfinished speech'}],{isFinal:false})]});
  assert.equal(s.input.value,'Original words');
  assert.equal(s.window.SafeSpotVoice.getTranscript(),'');
  assert.match(s.preview.interim.textContent,/Unfinished speech/);
  s.instance.onresult({resultIndex:0,results:[Object.assign([{transcript:'Completed speech'}],{isFinal:true})]});
  assert.equal(s.window.SafeSpotVoice.getTranscript(),'Completed speech');
  assert.equal(s.preview.interim.textContent,'');
  s.button.click();s.input.value='Edited report';
  assert.equal(s.window.SafeSpotVoice.getTranscript(),'Completed speech');
  s.window.SafeSpotVoice.reset();
  assert.equal(s.window.SafeSpotVoice.getTranscript(),'');
});
