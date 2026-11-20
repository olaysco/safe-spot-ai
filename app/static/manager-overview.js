'use strict';
window.ManagerOverview=(()=>{
  let panel,request=0,trigger,result;
  function close(){request++;if(panel?.open)panel.close();}
  function mount(){
    if(panel)return;
    panel=document.createElement('dialog');
    panel.className='manager-overview';
    panel.setAttribute('aria-labelledby','manager-overview-title');
    document.body.append(panel);
    panel.addEventListener('close',()=>{request++;trigger?.focus({preventScroll:true});});
    panel.addEventListener('cancel',()=>{request++;});
    panel.addEventListener('click',async event=>{
      const control=event.target.closest('button');
      if(!control)return;
      if(control.dataset.overview==='close')close();
      if(control.dataset.overview==='retry')await generate();
      if(control.dataset.overview==='cases'){
        const finding=result?.findings[Number(control.dataset.index)];
        if(!finding)return;
        const ids=new Set(finding.cases.map(c=>c.id));
        close();
        render(`${button('‹ Back to dashboard','back-desk','link back')}${workspaceHeader('AI overview','Supporting cases',finding.title)}${caseTable(cases.filter(c=>ids.has(c.id)))}`);
      }
    });
  }
  function shell(content){
    panel.innerHTML=`<header class="assistant-header"><div class="assistant-heading"><span>${uiIcon('sparkles',22)}<span id="manager-overview-title">AI overview</span></span><button class="icon-button" data-overview="close" aria-label="Close AI overview">${uiIcon('x',20)}</button></div><p class="assistant-reference">Reports received in the last ${days} days</p></header><div class="overview-content">${content}</div><footer class="overview-footer"><p>AI suggestions need staff review. No case changes are made.</p></footer>`;
  }
  function content(data){
    const labels={location:'Location to watch',attention:'Work needing attention',action:'Suggested next action'};
    return `<p class="assistant-meta">Generated ${esc(dt(data.generated_at))} · ${data.included} of ${data.total} reports included.</p>${data.excluded?`<p class="assistant-reason">${data.excluded} reports have no AI consent and were excluded.</p>`:''}${data.limited?'<p class="assistant-reason">This overview uses the latest 100 reports with AI consent.</p>':''}${data.findings.map((f,i)=>`<article class="overview-finding"><p class="eyebrow">${labels[f.kind]}</p><h3>${esc(f.title)}</h3><p>${esc(f.finding)}</p><p class="overview-action"><strong>Suggested action</strong><br>${esc(f.action)}</p><p class="assistant-reason"><strong>Uncertainty:</strong> ${esc(f.uncertainty)}</p><p class="assistant-meta">Reports: ${f.cases.map(c=>esc(c.reference)).join(', ')}</p><button class="assistant-button" data-overview="cases" data-index="${i}">Open cases (${f.cases.length})</button></article>`).join('')||`<div class="empty"><h3>${data.total===0?'No reports in this period':data.included===0?'No reports with AI consent':'No supported findings'}</h3><p>${data.included?'The available evidence does not support a useful finding.':'Use the dashboard charts to review the available records.'}</p></div>`}<button class="assistant-text-button" data-overview="retry">Generate again</button>`;
  }
  async function generate(){
    const current=++request,period=days;
    shell('<div role="status" aria-live="polite"><h3>Preparing your overview</h3><p>Checking reports, deadlines, and possible connections…</p></div>');
    panel.querySelector('[data-overview="close"]').focus();
    try{
      const data=await api('/manager/overview',{method:'POST',body:{days:period}});
      if(current!==request||!panel.open||days!==period)return;
      result=data;shell(content(data));panel.querySelector('[data-overview="close"]').focus();
    }catch(error){
      if(current!==request||!panel.open)return;
      shell(`<div role="alert"><h3>Overview unavailable</h3><p>${esc(error.message)}</p><button class="assistant-button" data-overview="retry">Try again</button></div>`);
      panel.querySelector('[data-overview="retry"]').focus();
    }
  }
  async function show(button){
    mount();trigger=button;result=null;shell('');panel.showModal();await generate();
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-manager-overview]');
    if(button&&!button.disabled)show(button);
  });
  return {close};
})();
