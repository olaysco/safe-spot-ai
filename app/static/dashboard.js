'use strict';
function dashboardBuckets(list, periodDays, end) {
  const start=end-periodDays*86400, width=periodDays*86400/6;
  return Array.from({length:6},(_,i)=>{
    const from=start+i*width,to=start+(i+1)*width;
    const records=list.filter(c=>c.created>=from&&(i===5?c.created<=to:c.created<to));
    const completed=records.filter(c=>c.approvals.field);
    return {label:new Date(from*1000).toLocaleDateString('en-GB',{day:'numeric',month:'short'}),count:records.length,completed:completed.length,mean:completed.length?completed.reduce((sum,c)=>sum+Math.max(0,c.approvals.field.at-c.created)/3600,0)/completed.length:null};
  });
}
function dashboardTable(headings,rows) {
  return `<details class="dashboard-data"><summary>View chart data</summary><div class="table-wrap"><table><caption class="sr-only">Chart data</caption><thead><tr>${headings.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map((v,i)=>`<td data-label="${esc(headings[i])}">${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
}
function dashboardPlot(data,key,title) {
  const isCount=key==='count',max=Math.max(1,...data.map(d=>d[key]??0)),x=i=>55+i*78,y=v=>165-v/max*115;
  const format=v=>isCount?String(v):v.toFixed(1);
  const marks=data.map((d,i)=>{
    if(d[key]===null)return '';
    const value=d[key],previous=data[i-1];
    return `${isCount?`<rect x="${x(i)-14}" y="${y(value)}" width="28" height="${165-y(value)}" class="chart-bar"/>`:previous?.[key]!==null&&previous?`<line x1="${x(i-1)}" y1="${y(previous[key])}" x2="${x(i)}" y2="${y(value)}" class="chart-line"/>`:''}<circle cx="${x(i)}" cy="${y(value)}" r="4" class="${isCount?'chart-bar':'chart-point'}"/><text x="${x(i)}" y="${y(value)-12}" text-anchor="middle">${format(value)}</text>`;
  }).join('');
  return `<section class="panel dashboard-chart"><h2>${title}</h2><p class="hint">${isCount?'Reports received in each period.':'Average hours to approved risk control, grouped by report receipt date.'}</p><svg viewBox="0 0 500 215" role="img" aria-label="${title}. Open the chart data for exact values."><text x="8" y="18">${isCount?'Reports':'Hours'}</text>${[0,max].map(v=>`<line x1="45" x2="470" y1="${y(v)}" y2="${y(v)}" class="chart-gridline"/><text x="5" y="${y(v)+5}">${format(v)}</text>`).join('')}${marks}${data.map((d,i)=>`<text x="${x(i)}" y="195" text-anchor="middle">${esc(d.label)}</text>`).join('')}</svg>${!isCount&&data.every(d=>d.mean===null)?'<p>No approved risk controls in this period.</p>':''}${dashboardTable(['Period start',isCount?'Reports':'Average hours',...(isCount?[]:['Approved controls'])],data.map(d=>[d.label,d[key]===null?'No approved controls':format(d[key]),...(isCount?[]:[d.completed])]))}</section>`;
}
function dashboardTargetState(c,key,dueKey,end) {
  const approval=c.approvals[key],due=c.targets[dueKey];
  if(approval)return approval.at<=due?'Met':'Missed';
  if(due<end)return 'Overdue';
  return due<=end+3600?'Due soon':'Within target';
}
function dashboardCharts(list,periodDays,end) {
  const data=dashboardBuckets(list,periodDays,end),labels=['Met','Missed','Overdue','Due soon','Within target'];
  const measures=[['First review','triage','review_due'],['Risk control','field','control_due']];
  const rows=measures.map(([name,key,due])=>[name,...labels.map(label=>list.filter(c=>dashboardTargetState(c,key,due,end)===label).length)]);
  const targets=`<section class="panel dashboard-chart"><h2>Internal target performance</h2><p class="hint">Targets use each case priority. These are internal targets, not HSE reporting deadlines.</p>${rows.map(row=>`<h3>${row[0]}</h3><div class="dashboard-stacked" role="img" aria-label="${row[0]}: ${labels.map((label,i)=>`${label} ${row[i+1]}`).join(', ')}">${row.slice(1).map((n,i)=>n?`<span class="target-${i}" style="width:${100*n/list.length}%">${n}</span>`:'').join('')}</div>`).join('')}<div class="dashboard-legend">${labels.map((label,i)=>`<span><i class="target-${i}"></i>${label}</span>`).join('')}</div>${list.length?'':'<p>No reports in this period.</p>'}${dashboardTable(['Measure',...labels],rows)}</section>`;
  const locations=[...new Set(list.map(c=>c.report.location))].map(name=>({name,count:list.filter(c=>c.report.location===name).length})).sort((a,b)=>b.count-a.count);
  const max=Math.max(1,...locations.map(l=>l.count));
  const locationChart=`<section class="panel dashboard-chart"><h2>Reports by location</h2><p class="hint">Select a location to view its reports below.</p>${locations.map(l=>`<button class="dashboard-location" data-location="${esc(l.name)}" aria-pressed="${locationFilter===l.name}"><span>${esc(l.name)}</span><span class="dashboard-track" aria-hidden="true"><span style="width:${100*l.count/max}%"></span></span><strong>${l.count}</strong></button>`).join('')||'<p>No reports in this period.</p>'}${dashboardTable(['Location','Reports'],locations.map(l=>[l.name,l.count]))}</section>`;
  return `<div class="dashboard-charts">${dashboardPlot(data,'count','Incident trend')}${targets}${locationChart}${dashboardPlot(data,'mean','Time to risk control')}</div>`;
}
