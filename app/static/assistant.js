'use strict';

const caseAssistant=(()=>{
  const state={open:false,id:null,mode:'case',tab:'review',source:null,editing:null,error:'',notice:'',busy:null};
  const drafts=new Map(),edits=new Map();
  let returnTarget=null,requestNumber=0;
  const current=()=>cases.find(c=>c.id===state.id);
  const review=c=>c?.assistant?.reviews?.at(-1);
  const action=(name,label,extra='',style='assistant-button')=>`<button type="button" class="${style}" data-assistant-action="${name}" ${extra}>${label}</button>`;
  const sourceLabels={description:'Report',location:'Location',time:'Incident time',harm:'Harm',remains:'Current condition',findings:'Field findings',status:'Case status',approvals:'Approvals'};
  const caseButton=(c,label='')=>`<button type="button" class="assistant-case-link" data-assistant-case="${esc(c.id)}">${label||`${esc(c.report.location)}<span>${esc(c.reference)}</span>`}${uiIcon('right',16)}</button>`;
  const draftValue=c=>drafts.get(c.id)?.text??c.assistant?.draft?.text??'';
  const changed=()=>{const c=current();return c&&drafts.has(c.id)&&draftValue(c)!==(c.assistant?.draft?.text||'');};

  function evidenceChanged(c){
    const r=review(c);
    if(!r)return false;
    const sort=value=>value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,sort(value[key])])):value;
    const currentSource={...c.report,status:c.status,category:c.category,priority:c.priority,findings:c.findings,
      approvals:Object.fromEntries(Object.entries(c.approvals).map(([key,value])=>[key,value.at])),assigned:!!c.approvals.triage,reference:c.reference};
    return Object.entries(r.source).some(([key,value])=>JSON.stringify(sort(value))!==JSON.stringify(sort(currentSource[key])));
  }

  function layout(content){
    if(user?.role!=='handler')return content;
    return `<div class="case-assistant-layout ${state.open?'assistant-open':''}"><div class="case-board-area">${content}</div><div id="assistant-host">${state.open?panel():''}</div></div>`;
  }

  function headerButton(){
    return `<div class="queue-heading-actions">${action('overview',uiIcon('sparkles')+'AI review')}${refreshButton('Refresh cases')}</div>`;
  }

  function cardFooter(c){
    const selected=state.open&&state.mode==='case'&&c.id===state.id;
    return `<button type="button" class="case-assistant-open" data-assistant-case="${c.id}">${uiIcon(selected?'done':'sparkles',16)}<span>${selected?'Selected case':'Review case'}</span>${uiIcon('right',16)}</button>`;
  }

  function sourceButton(fields){
    return action('source',uiIcon('file',16)+'View source',`data-source-fields="${esc(fields.join(','))}"`,'assistant-text-button');
  }

  function suggestion(c,r,key,label){
    const item=r.result[key],decision=r.decisions[key];
    const value=decision?.action!=='dismiss'&&decision?decision.value:item.value;
    const editing=state.editing===key;
    const editValue=edits.get(c.id+':'+key)??value;
    const input=key==='summary'?`<label class="sr-only" for="assistant-value">Summary</label><textarea id="assistant-value" data-assistant-edit="${key}" maxlength="3000">${esc(editValue)}</textarea>`:select(label,'assistant-value',key==='category'?categories:priorities,editValue);
    const accepted=key==='summary'||(key==='category'?categories:priorities).includes(item.value);
    return `<section class="assistant-section"><h3>${label}</h3>${editing?input:`<p class="${key==='summary'?'assistant-summary':'assistant-value'}">${esc(value)}</p>`}<p class="assistant-reason">${esc(item.reason)}</p>${sourceButton(item.sources)}${decision?`<p class="assistant-saved">${uiIcon('done',16)}${{accept:'Accepted',change:'Changed',dismiss:'Dismissed'}[decision.action]} · ${esc(decision.by)} · ${dt(decision.at)}</p>`:`<div class="assistant-actions" ${evidenceChanged(c)?'inert':''}>${editing?action('decision','Save change',`data-field="${key}" data-decision="change"`)+action('cancel-edit','Cancel','','assistant-text-button'):`${accepted?action('decision','Accept',`data-field="${key}" data-decision="accept"`):''}${action('edit',uiIcon('edit',16)+'Change',`data-field="${key}"`)}${action('decision','Dismiss',`data-field="${key}" data-decision="dismiss"`,'assistant-text-button')}`}</div>`}</section>`;
  }

  function reviewBody(c){
    const r=review(c),permitted=c.report.consent;
    if(!r)return `<section class="assistant-section"><h3>Original report</h3><p class="assistant-summary">${esc(c.report.description)}</p>${action('source',uiIcon('file',16)+'View report','','assistant-text-button')}</section><section class="assistant-section"><h3>AI review</h3><p class="assistant-reason">${!permitted?'The reporter did not consent to AI assistance.':!config.ai?.text?'AI is not connected. You can write a draft manually.':'Review the report for missing details, triage, and related incidents.'}</p>${permitted&&config.ai?.text?action('generate',uiIcon('sparkles',18)+'Prepare review','','assistant-button assistant-primary'):''}</section>${confirmedRelationships(c)}`;
    return `${action('source',uiIcon('file',16)+'Original report','','assistant-text-button')}<p class="assistant-meta">${r.model==='sample'?'Prepared example':'AI review'} · ${dt(r.at)}</p>${evidenceChanged(c)?'<p class="assistant-error">The case evidence changed. Prepare a new review.</p>':''}${suggestion(c,r,'summary','Summary')}${suggestion(c,r,'category','Suggested category')}${suggestion(c,r,'priority','Suggested priority')}<section class="assistant-section"><h3>Information needed</h3>${r.result.missing.length?`<ul class="assistant-missing">${r.result.missing.map(text=>`<li>${esc(text)}</li>`).join('')}</ul>`:'<p class="assistant-reason">No missing details were identified.</p>'}</section><section class="assistant-section"><h3>Related reports</h3><p class="assistant-meta">${r.model==='sample'?'Example includes':'AI checked'} ${r.candidates.length} candidate reports.</p>${r.result.related.map((item,index)=>relatedSuggestion(c,r,item,index)).join('')||'<p class="assistant-reason">No related reports were suggested.</p>'}</section>${confirmedRelationships(c)}${permitted&&config.ai?.text?action('generate',uiIcon('refresh',16)+'Prepare new review','','assistant-text-button'):''}`;
  }

  function confirmedRelationships(c){
    const related=groups.filter(g=>g.case_ids.includes(c.id));
    if(!related.length)return '';
    return `<section class="assistant-section"><h3>Confirmed relationships</h3>${related.map(g=>`<div class="assistant-related"><strong>${g.relationship==='recurring'?'Repeated incidents':'Reports of one incident'}</strong><p>${esc(g.reason)}</p>${g.case_ids.filter(id=>id!==c.id).map(id=>cases.find(item=>item.id===id)).filter(Boolean).map(item=>caseButton(item)).join('')}<p class="assistant-meta">${esc(g.by)} · ${dt(g.at)}</p></div>`).join('')}</section>`;
  }

  function relatedSuggestion(c,r,item,index){
    const decision=r.relationships[item.reference];
    const target=r.candidates.find(candidate=>candidate.reference===item.reference);
    const linked=groups.some(group=>group.relationship===item.relationship&&group.case_ids.includes(c.id)&&group.case_ids.includes(target?.case_id));
    return `<div class="assistant-related"><h4>${item.relationship==='same_event'?'Possible duplicate':'Repeated incident'}</h4><p><strong>${esc(item.reference)}</strong></p><p>${esc(item.reason)}</p>${item.uncertainty?`<p class="assistant-reason">${esc(item.uncertainty)}</p>`:''}${action('related-source',uiIcon('link',16)+'Compare reports',`data-index="${index}"`,'assistant-text-button')}${linked?'<p class="assistant-saved">This relationship is already confirmed.</p>':decision?`<p class="assistant-saved">${decision.action==='confirm'?'Confirmed':'Dismissed'} · ${esc(decision.by)}</p>`:`${select('Relationship','relationship-'+index,[['same_event','Same incident'],['recurring','Repeated incident']],item.relationship)}<label class="assistant-label" for="relationship-reason-${index}">Reason</label><textarea id="relationship-reason-${index}" data-related-edit="${index}" maxlength="2000">${esc(edits.get(c.id+':related:'+index)??item.reason)}</textarea><div class="assistant-actions">${action('relationship','Confirm link',`data-index="${index}" data-decision="confirm"`)}${action('relationship','Dismiss',`data-index="${index}" data-decision="dismiss"`,'assistant-text-button')}</div>`}</div>`;
  }

  function draftBody(c){
    const r=review(c),draft=draftValue(c),saved=c.assistant?.draft;
    return `<section class="assistant-section"><h3>Follow-up message</h3>${r?.result.follow_up?action('use-draft',uiIcon('sparkles',16)+'Use suggested draft','','assistant-text-button'):''}<label class="assistant-label" for="assistant-draft">Message</label><textarea id="assistant-draft" maxlength="4000" placeholder="Write a follow-up message.">${esc(draft)}</textarea><p id="assistant-draft-state" class="assistant-meta">${changed()?'Unsaved changes':saved?'Saved by '+esc(saved.by)+' · '+dt(saved.at):'Not saved'}</p><p class="assistant-reason">Save this draft for staff review.</p>${action('save-draft',uiIcon('save',16)+'Save draft',draft.trim().length<3?'disabled':'','assistant-button assistant-primary')}</section>`;
  }

  function activityBody(c){
    return `<section class="assistant-section"><h3>Case activity</h3><ol class="assistant-activity">${c.history.map(h=>`<li><strong>${esc(h.action)}</strong><span>${esc(h.by)} · ${dt(h.at)}</span><p>${esc(h.detail)}</p>${h.assistant?.review_id&&c.assistant?.reviews?.some(item=>item.id===h.assistant.review_id)?action('history-source','View source',`data-review-id="${esc(h.assistant.review_id)}"`,'assistant-text-button'):''}</li>`).join('')||'<li>No staff actions are recorded.</li>'}</ol></section>`;
  }

  function sourceBody(c){
    const r=state.source.reviewId?c.assistant?.reviews?.find(item=>item.id===state.source.reviewId):review(c);
    const primary=state.source.live?{...c.report,reference:c.reference,status:c.status,findings:c.findings,approvals:c.approvals}:r?.source||{...c.report,reference:c.reference};
    const list=[primary];
    if(state.source.reference){const target=r?.candidates.find(item=>item.reference===state.source.reference);if(target)list.push(target);}
    return `${action('source-back',uiIcon('left',16)+'Back','','assistant-text-button')}${list.map(item=>`<section class="assistant-section"><h3>${esc(item.reference)}</h3>${!state.source.live&&r?`<p class="assistant-meta">Evidence used ${dt(r.at)}</p>`:''}<dl class="assistant-source">${Object.entries(sourceLabels).filter(([key])=>!state.source.fields?.length||state.source.fields.includes(key)).map(([key,label])=>`<div><dt>${label}</dt><dd>${esc(typeof item[key]==='object'?JSON.stringify(item[key],null,2):item[key]||'Not recorded')}</dd></div>`).join('')}</dl></section>`).join('')}<p class="assistant-meta">This review uses text records. It does not inspect images.</p>`;
  }

  function overviewBody(){
    const list=cases.filter(matches),late=list.filter(c=>!c.approvals.field&&c.targets.control_due<now()),unassigned=list.filter(c=>!c.approvals.triage);
    const ordered=[...list].sort((a,b)=>Number(!b.approvals.field&&b.targets.control_due<now())-Number(!a.approvals.field&&a.targets.control_due<now()));
    return `<p class="assistant-reason">${list.length} cases match the current filters.</p><div class="assistant-stats">${action('overdue',`<strong>${late.length}</strong><span>Control overdue</span>`)}${action('unassigned',`<strong>${unassigned.length}</strong><span>Not assigned</span>`)}</div><section class="assistant-section"><h3>Cases to review</h3><p class="assistant-meta">Counts use case records and deadlines.</p>${ordered.map(c=>caseButton(c)).join('')||'<p>No cases match these filters.</p>'}</section>`;
  }

  function panel(){
    const c=current(),overview=state.mode==='overview';
    const title=overview?'Board review':c?.report.location||'Loading case';
    const busy=state.busy&&(state.busy===state.id||overview);
    return `<aside class="case-assistant" aria-labelledby="assistant-title"><header class="assistant-header"><div class="assistant-heading"><span>${uiIcon('sparkles',20)}Case assistant</span>${action('close',uiIcon('x'),`aria-label="Close case assistant"`,'icon-button')}</div>${c&&!overview?`<p class="assistant-reference">${esc(c.reference)} · ${esc(c.status)}</p>`:''}<h2 id="assistant-title" tabindex="-1">${esc(title)}</h2></header>${!overview&&!state.source?`<div class="assistant-tabs" role="tablist" aria-label="Case assistant sections">${['review','draft','activity'].map(tab=>`<button type="button" role="tab" id="assistant-tab-${tab}" data-assistant-action="tab" data-tab="${tab}" aria-selected="${state.tab===tab}" aria-controls="assistant-content" tabindex="${state.tab===tab?0:-1}">${{review:'Review',draft:'Draft',activity:'Activity'}[tab]}</button>`).join('')}</div>`:''}<div class="assistant-content" id="assistant-content" role="${!overview&&!state.source?'tabpanel':'region'}" aria-labelledby="${!overview&&!state.source?'assistant-tab-'+state.tab:'assistant-title'}" tabindex="0">${state.error?`<div class="assistant-error" role="alert">${esc(state.error)}${action('reload','Reload case','','assistant-text-button')}</div>`:''}${state.notice?`<p class="assistant-saved" role="status">${esc(state.notice)}</p>`:''}${busy?'<p class="assistant-loading" role="status">Preparing the record…</p>':''}<div ${busy?'inert aria-busy="true"':''}>${overview?overviewBody():c?state.source?sourceBody(c):state.tab==='review'?reviewBody(c):state.tab==='draft'?draftBody(c):activityBody(c):'<p>Loading case…</p>'}</div></div>${!overview&&c?`<footer class="assistant-footer">${action('open-case','Open case '+uiIcon('right',18),'','assistant-button')}<p>Approve actions in the case record.</p></footer>`:''}</aside>`;
  }

  function paint(focus=''){
    if(!$('#assistant-host')||!state.open)return;
    const scroll=$('#assistant-content')?.scrollTop||0;
    $('#assistant-host').innerHTML=panel();
    resize();
    $('#assistant-content').scrollTop=scroll;
    if(focus)document.getElementById(focus)?.focus({preventScroll:true});
  }

  function redraw(focus=''){
    if(!$('.case-assistant-layout'))return;
    const scroll=$('.case-board-area')?.scrollTop||0;
    render(caseQueue(),false);
    $('.case-board-area').scrollTop=scroll;
    if(focus)document.getElementById(focus)?.focus({preventScroll:true});
  }

  async function show(id,trigger){
    returnTarget=trigger;
    const number=++requestNumber;
    Object.assign(state,{open:true,id,mode:'case',tab:'review',source:null,editing:null,error:'',notice:''});
    redraw('assistant-title');
    try{
      const item=await api('/cases/'+id);
      cases=cases.map(c=>c.id===item.id?item:c);
      if(number===requestNumber)paint();
    }catch(error){if(number===requestNumber){state.error=error.message;paint();}}
  }

  function close(){
    requestNumber++;
    state.open=false;
    redraw();
    const selector=state.mode==='overview'?'[data-assistant-action="overview"]':`[data-assistant-case="${state.id}"]`;
    const target=returnTarget?.isConnected?returnTarget:document.querySelector(selector)||document.querySelector('[data-assistant-action="overview"]');
    target?.focus({preventScroll:true});
  }

  async function save(endpoint,fields,notice){
    const c=current();
    if(!c||state.busy)return;
    state.error='';state.notice='';state.busy=c.id;paint();
    try{
      const updated=await api('/cases/'+c.id+'/assistant/'+endpoint,{method:'POST',body:{version:c.version,...fields}});
      cases=cases.map(item=>item.id===updated.id?updated:item);
      if(endpoint==='relationship')groups=await api('/groups');
      if(endpoint==='draft')drafts.set(c.id,{text:updated.assistant.draft.text,review_id:updated.assistant.draft.review_id});
      if(state.id===c.id){state.notice=notice;state.editing=null;}
    }catch(error){if(state.id===c.id)state.error=error.message;}
    finally{state.busy=null;paint('assistant-title');}
  }

  async function handle(name,b){
    const c=current(),r=review(c);
    if(name==='overview'){
      returnTarget=b;requestNumber++;Object.assign(state,{open:true,mode:'overview',source:null,error:'',notice:''});redraw('assistant-title');
    }else if(name==='close')close();
    else if(name==='tab'){state.tab=b.dataset.tab;state.source=null;state.error='';state.notice='';state.editing=null;paint('assistant-tab-'+state.tab);$('#assistant-content').scrollTop=0;}
    else if(name==='source'){state.source={fields:b.dataset.sourceFields?.split(','),live:!b.dataset.sourceFields};paint();}
    else if(name==='source-back'){state.source=null;paint('assistant-tab-'+state.tab);}
    else if(name==='history-source'){state.source={reviewId:b.dataset.reviewId};paint();}
    else if(name==='related-source'){state.source={reference:r.result.related[Number(b.dataset.index)].reference};paint();}
    else if(name==='reload'){await show(state.id,b);}
    else if(name==='generate')await save('review',{},'AI suggestions are ready.');
    else if(name==='edit'){state.editing=b.dataset.field;paint('assistant-value');}
    else if(name==='cancel-edit'){state.editing=null;paint('assistant-title');}
    else if(name==='decision'){
      const value=b.dataset.decision==='change'?$('#assistant-value').value:'';
      await save('decision',{review_id:r.id,field:b.dataset.field,action:b.dataset.decision,value},'Decision saved.');
    }else if(name==='use-draft'){
      if(changed()){state.error='Save your current draft before using the suggestion.';paint();return;}
      drafts.set(c.id,{text:r.result.follow_up,review_id:r.id});paint('assistant-draft');
    }else if(name==='save-draft'){
      const buffer=drafts.get(c.id)||{text:draftValue(c),review_id:c.assistant?.draft?.review_id||''};
      await save('draft',buffer,'Draft saved to case activity.');
    }else if(name==='relationship'){
      const index=Number(b.dataset.index),item=r.result.related[index];
      await save('relationship',{review_id:r.id,reference:item.reference,action:b.dataset.decision,relationship:$('#relationship-'+index).value,reason:$('#relationship-reason-'+index).value},'Relationship decision saved.');
    }else if(name==='open-case'){state.open=false;await loadCase(c.id);}
    else if(name==='overdue'||name==='unassigned'){
      if(name==='overdue')filters.deadline='risk';else filters.officer='unassigned';
      redraw('assistant-title');
    }
  }

  document.addEventListener('click',event=>{
    const b=event.target.closest('button');
    if(!b||b.disabled)return;
    if(b.dataset.assistantCase){show(b.dataset.assistantCase,b);return;}
    if(b.dataset.assistantAction)handle(b.dataset.assistantAction,b).catch(error=>{state.error=error.message;paint();});
  });
  document.addEventListener('input',event=>{
    const c=current(),input=event.target;
    if(!c)return;
    if(input.id==='assistant-draft'){
      const reviewId=drafts.get(c.id)?.review_id??c.assistant?.draft?.review_id??'';
      drafts.set(c.id,{text:input.value,review_id:reviewId});
      const saveButton=$('[data-assistant-action="save-draft"]');
      if(saveButton)saveButton.disabled=input.value.trim().length<3;
      $('#assistant-draft-state').textContent=changed()?'Unsaved changes':'Saved draft';
    }
    if(input.dataset.assistantEdit)edits.set(c.id+':'+input.dataset.assistantEdit,input.value);
    if(input.dataset.relatedEdit)edits.set(c.id+':related:'+input.dataset.relatedEdit,input.value);
  });
  document.addEventListener('keydown',event=>{
    if(!state.open||!$('.case-assistant-layout'))return;
    if(event.key==='Escape'){
      event.preventDefault();if(state.source){state.source=null;paint('assistant-tab-'+state.tab);}else close();
    }
    if(event.target.closest('.assistant-tabs')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
      event.preventDefault();const tabs=['review','draft','activity'],index=tabs.indexOf(event.target.dataset.tab||state.tab);
      state.tab=tabs[event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3];
      paint('assistant-tab-'+state.tab);
    }
  });

  function reviewedValues(c){
    const decisions=evidenceChanged(c)?{}:review(c)?.decisions||{};
    return Object.fromEntries(['category','priority'].filter(key=>decisions[key]&&decisions[key].action!=='dismiss').map(key=>[key,decisions[key].value]));
  }

  function reset(){state.open=false;state.id=null;requestNumber++;drafts.clear();edits.clear();}
  function resize(){
    const host=$('#assistant-host');
    if(host&&state.open)host.style.setProperty('--assistant-height',host.clientHeight+'px');
  }
  window.addEventListener('resize',resize,{passive:true});
  window.addEventListener('scroll',resize,{passive:true});
  return {layout,headerButton,cardFooter,reviewedValues,reset,resize,isSelected:id=>state.open&&state.mode==='case'&&state.id===id};
})();
