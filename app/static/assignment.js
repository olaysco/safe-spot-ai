'use strict';
window.SafeSpotAssignment = (() => {
  function resultPanel(result) {
    if (!result) return '<p class="hint">Compare officers before approving an assignment.</p>';
    const recommended = result.candidates.find(row => row.id === result.recommended_officer_id);
    return `<p class="assignment-source">${result.source === 'ai' ? 'AI department suggestion · Capacity rules' : 'Department selection · Capacity rules'}</p>
      <p>${esc(result.reason)}</p>
      ${recommended ? `<div class="assignment-choice"><strong>Recommended: ${esc(recommended.name)}</strong><p>${esc(recommended.department)} · ${recommended.active_cases} active cases / ${recommended.capacity} case limit</p><button type="button" class="secondary" data-assignment-use="${esc(recommended.id)}">Use this recommendation</button></div>` : `<p class="inset">${result.needs_manager ? 'No suitable officer has capacity. Request manager review before assignment.' : 'Select a department to compare officers.'}</p>`}
      <details><summary>Compare officers and capacity</summary><div class="table-wrap"><table><caption>Recorded officer availability</caption><thead><tr><th>Officer</th><th>Department</th><th>Active / limit</th><th>Reason</th></tr></thead><tbody>${result.candidates.map(row => `<tr><td>${esc(row.name)}${row.demo ? '<br><small>Fictional staff data</small>' : ''}</td><td>${esc(row.department || 'Not recorded')}</td><td>${row.active_cases} / ${row.capacity}</td><td>${esc(row.reason)}</td></tr>`).join('')}</tbody></table></div></details>
      <p class="hint">${esc(result.basis)}</p><p class="hint">Checked ${dt(result.generated_at)}. Approval checks capacity again.</p>`;
  }
  function render(caseRecord) {
    const previous = caseRecord.assignment_recommendation;
    return `<section class="assignment-panel" aria-labelledby="assignment-heading"><h3 id="assignment-heading">Department and capacity</h3>
      <p>Suggest a department from the report, then compare officer availability.</p>
      ${select('Department', 'department', [['', 'Ask AI or select a department'], ...(config.departments || [])], caseRecord.department || previous?.department || '')}
      <button type="button" class="secondary" data-assignment-prepare>Compare available officers</button>
      <div id="assignment-result" aria-live="polite">${resultPanel(previous)}</div></section>`;
  }
  document.addEventListener('change', event => {
    if (event.target.id !== 'department') return;
    const panel = document.getElementById('assignment-result');
    if (panel) panel.innerHTML = '<p class="hint">The department changed. Compare officers again.</p>';
  });
  document.addEventListener('click', async event => {
    const prepare = event.target.closest('[data-assignment-prepare]');
    const use = event.target.closest('[data-assignment-use]');
    if (use && selected) {
      const recommendation = selected.assignment_recommendation;
      if (!recommendation || recommendation.recommended_officer_id !== use.dataset.assignmentUse) return;
      document.getElementById('officer_id').value = use.dataset.assignmentUse;
      document.getElementById('department').value = recommendation.department;
      const officer = recommendation.candidates.find(row => row.id === use.dataset.assignmentUse);
      const reason = document.getElementById('reason');
      if (!reason.value.trim()) reason.value = `${recommendation.reason} ${officer.reason}`;
      message('The recommendation is selected. Review it before approval.');
    }
    if (!prepare || prepare.disabled || !selected) return;
    const caseId = selected.id, version = selected.version;
    const department = document.getElementById('department').value;
    const panel = document.getElementById('assignment-result');
    prepare.disabled = true;
    panel.textContent = 'Checking department and capacity…';
    try {
      const response = await api(`/cases/${caseId}/assignment-recommendation`, {method: 'POST', body: {version, department}});
      if (!panel.isConnected || selected?.id !== caseId) return;
      selected = response.case;
      if (document.getElementById('department').value !== department) {
        panel.textContent = 'The department changed. Compare officers again.';
        return;
      }
      document.getElementById('department').value = response.recommendation.department;
      panel.innerHTML = resultPanel(response.recommendation);
    } catch (error) {
      if (panel.isConnected) panel.textContent = error.message;
    } finally {
      prepare.disabled = false;
    }
  });
  return {render};
})();
