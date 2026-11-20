'use strict';
window.SafeSpotCapacity = (() => {
  let records = [];
  function renderRows(data) {
    records = data.officers;
    return `<p class="hint">${esc(data.basis)}</p><div class="capacity-grid">${records.map((row, index) => `<section class="assignment-panel"><h3>${esc(row.name)}</h3>${row.demo ? '<p class="hint">Fictional staff data</p>' : ''}<p id="capacity-count-${index}"><strong>${row.active_cases}</strong> active cases · <strong>${row.remaining}</strong> unused case places</p><label class="label" for="capacity-department-${index}">Department</label><select id="capacity-department-${index}">${[['', 'Select a department'], ...data.departments.map(name => [name, name])].map(([value, label]) => `<option value="${esc(value)}" ${value === row.department ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select><label class="label" for="capacity-limit-${index}">Active case limit</label><input class="input" id="capacity-limit-${index}" type="number" min="0" max="50" step="1" value="${row.capacity}"><label class="radio"><input type="checkbox" id="capacity-available-${index}" ${row.available ? 'checked' : ''}><span>Available for assignment</span></label><button type="button" class="secondary" data-capacity-save="${index}">Save capacity</button><p id="capacity-status-${index}" role="status">${row.modified_at ? `Updated ${dt(row.modified_at)} by ${esc(row.modified_by_name || 'Manager')}` : 'No manager update recorded.'}</p></section>`).join('')}</div>`;
  }
  function render() {
    return '<section class="section"><h2>Officer capacity</h2><p>Review departments, availability, and case limits before assigning work.</p><button type="button" class="secondary" data-capacity-load>Manage officer capacity</button><div id="capacity-records"></div></section>';
  }
  document.addEventListener('click', async event => {
    const load = event.target.closest('[data-capacity-load]');
    const save = event.target.closest('[data-capacity-save]');
    if (load && !load.disabled) {
      const host = document.getElementById('capacity-records');
      load.disabled = true;
      host.textContent = 'Loading officer capacity…';
      try {
        const data = await api('/manager/capacity');
        if (host.isConnected) host.innerHTML = renderRows(data);
      } catch (error) { if (host.isConnected) host.textContent = error.message; }
      finally { load.disabled = false; }
    }
    if (save && !save.disabled) {
      const index = Number(save.dataset.capacitySave), row = records[index];
      if (!row) return;
      const status = document.getElementById(`capacity-status-${index}`);
      const input = document.getElementById(`capacity-limit-${index}`);
      if (!input.reportValidity() || input.value === '') return;
      const body = {version: row.version, department: document.getElementById(`capacity-department-${index}`).value,
        capacity: Number(input.value), available: document.getElementById(`capacity-available-${index}`).checked};
      save.disabled = true;
      const controls = [...save.closest('.assignment-panel').querySelectorAll('input,select')];
      controls.forEach(control => { control.disabled = true; });
      try {
        const data = await api(`/manager/capacity/${row.id}`, {method: 'POST', body});
        const updated = data.officers.find(item => item.id === row.id);
        if (status.isConnected) {
          records[index] = updated;
          document.getElementById(`capacity-count-${index}`).textContent = `${updated.active_cases} active cases · ${updated.remaining} unused case places`;
          status.textContent = `Capacity saved ${dt(updated.modified_at)} by ${updated.modified_by_name || 'Manager'}. Existing assignments remain unchanged.`;
        }
      } catch (error) { if (status.isConnected) status.textContent = error.message; }
      finally { save.disabled = false; controls.forEach(control => { control.disabled = false; }); }
    }
  });
  return {render};
})();
