import {request, setupDialogs, toast, icon, element} from './ui.js';
import './session.js';
setupDialogs();
let map = JSON.parse(document.getElementById('table-map-data').textContent);
let selectedId = null;
let submitting = false;
const panel = document.getElementById('table-panel');
const openDialog = document.getElementById('open-dialog');
const search = document.getElementById('table-search');
const canOpen = document.body.dataset.canOpen === 'true';
const allTables = () => map.groups.flatMap(group => group.tables);
const selected = () => allTables().find(table => table.id === selectedId);
const text = (id, value) => { document.getElementById(id).textContent = value || ''; };

function elapsed(timestamp) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(timestamp)) / 60000));
  return {compact: `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`,
          description: `${Math.floor(minutes / 60)} h ${minutes % 60} min`};
}
function updateTimes() {
  document.querySelectorAll('[data-opened-at]').forEach(node => { node.textContent = elapsed(node.dataset.openedAt).compact; });
  if (selected()?.opened_at) text('panel-time', elapsed(selected().opened_at).description);
}
function badge(table) {
  const node = element('span', 'badge');
  node.dataset.state = table.state;
  node.append(element('i', 'status-dot'), document.createTextNode(table.state_label));
  return node;
}
function tile(table) {
  const button = element('button', `table-tile shape-${table.shape}`);
  button.type = 'button';
  button.dataset.tableId = table.id;
  button.dataset.state = table.state;
  button.dataset.search = table.name;
  button.setAttribute('aria-haspopup', 'dialog');
  button.setAttribute('aria-expanded', String(panel.open && table.id === selectedId));
  Object.entries({x: table.layout.x, y: table.layout.y, w: table.layout.width, h: table.layout.height}).forEach(([key, value]) => button.style.setProperty(`--${key}`, `${value}%`));
  const top = element('span', 'tile-top');
  top.append(element('strong', 'tile-name', table.name), icon('table', 'tile-icon'));
  const bottom = element('span', 'tile-bottom');
  if (table.order_id) {
    const time = element('span', 'tile-time');
    const clock = element('span', '', table.elapsed);
    clock.dataset.openedAt = table.opened_at;
    time.append(icon('clock'), clock);
    bottom.append(element('span', 'tile-total', table.total), time);
  } else bottom.append(element('span', 'tile-ready', table.state === 'AVAILABLE' ? 'Lista para abrir' : 'No disponible'));
  button.append(top, badge(table), bottom);
  return button;
}
function fitLayouts() {
  // Las coordenadas válidas pueden resultar demasiado pequeñas en otra tablet.
  // Conservar el plano solo si todos los controles caben y siguen siendo legibles.
  document.querySelectorAll('[data-zone]').forEach((section, index) => {
    const grid = section.querySelector('.table-grid');
    grid.classList.toggle('table-layout', !!map.groups[index]?.has_layout);
    if (!grid.classList.contains('table-layout') || !grid.getBoundingClientRect().width) return;
    const bounds = grid.getBoundingClientRect();
    const rectangles = [...grid.children].filter(node => !node.hidden).map(node => node.getBoundingClientRect());
    const tooSmall = rectangles.some(rect => rect.width < 144 || rect.height < 145 || rect.right > bounds.right + 1 || rect.bottom > bounds.bottom + 1);
    const overlap = rectangles.some((a, i) => rectangles.slice(i + 1).some(b => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom));
    if (tooSmall || overlap) grid.classList.remove('table-layout');
  });
}
function updateMap(data) {
  map = data;
  const groups = document.getElementById('map-groups');
  groups.replaceChildren();
  map.groups.forEach(group => {
    const section = element('section', 'map-zone');
    section.dataset.zone = '';
    const heading = element('div', 'zone-heading');
    heading.append(element('h2', '', group.name), element('span', 'zone-count', group.tables.length));
    const grid = element('div', `table-grid${group.has_layout ? ' table-layout' : ''}`);
    group.tables.forEach(table => grid.append(tile(table)));
    section.append(heading, grid);
    groups.append(section);
  });
  text('map-count', `${map.table_count} mesas · ${map.available_count} libres · ${map.occupied_count} ocupadas`);
  document.getElementById('map-empty').hidden = !!map.table_count;
  document.getElementById('day-block').hidden = map.has_open_day;
  document.getElementById('map-content').hidden = !map.has_open_day;
  if (!map.has_open_day) { panel.close(); openDialog.close(); }
  fitLayouts();
  filterTables();
  updateTimes();
}
function updatePanel() {
  const table = selected();
  if (!table) { panel.close(); return; }
  const occupied = !!table.order_id;
  const outOfService = table.state === 'OUT_OF_SERVICE';
  text('panel-name', table.name);
  text('panel-area', table.area);
  text('panel-zone', map.groups.find(group => group.tables.some(item => item.id === table.id))?.name);
  text('panel-capacity', `${table.capacity} personas`);
  const status = document.getElementById('panel-state');
  status.dataset.state = table.state;
  status.replaceChildren(element('i', 'status-dot'), document.createTextNode(table.state_label));
  text('panel-waiter', table.responsible);
  text('panel-total', table.total);
  const accountLink = document.getElementById('view-account-link');
  if (accountLink && table.order_id) accountLink.href = `/operacion/orden/${table.order_id}/cuenta/`;
  const addOrderLink = document.getElementById('add-order-link');
  if (addOrderLink && table.order_id) addOrderLink.href = `/operacion/orden/${table.order_id}/pedido/`;
  ['panel-time-row', 'panel-waiter-row', 'panel-total-row'].forEach(id => { document.getElementById(id).hidden = !occupied; });
  document.getElementById('open-table-button').hidden = outOfService || occupied || !canOpen;
  document.getElementById('future-actions').hidden = !occupied || outOfService;
  document.getElementById('panel-no-permission').hidden = canOpen || occupied || outOfService;
  updateTimes();
}
function chooseTable(id) {
  selectedId = id;
  if (!selected()) { panel.close(); return; }
  updatePanel();
  if (!panel.open) panel.showModal();
  document.querySelectorAll('[data-table-id]').forEach(button => button.setAttribute('aria-expanded', String(Number(button.dataset.tableId) === id)));
}
document.getElementById('map-groups').addEventListener('click', event => {
  const button = event.target.closest('[data-table-id]');
  if (button) chooseTable(Number(button.dataset.tableId));
});
panel.addEventListener('close', () => document.querySelectorAll('[data-table-id]').forEach(button => button.setAttribute('aria-expanded', 'false')));
document.getElementById('open-table-button').addEventListener('click', () => {
  text('open-title', `Abrir ${selected().name}`);
  document.getElementById('open-error').hidden = true;
  openDialog.showModal();
});
function normalized(value) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\b0+(\d)/g, '$1').trim();
}
function filterTables() {
  const query = normalized(search.value);
  let matches = 0;
  document.querySelectorAll('[data-zone]').forEach(zone => {
    let visible = 0;
    zone.querySelectorAll('[data-table-id]').forEach(button => {
      button.hidden = !normalized(button.dataset.search).includes(query);
      if (!button.hidden) { visible++; matches++; }
    });
    zone.hidden = visible === 0;
  });
  document.getElementById('search-empty').hidden = !query || matches > 0;
}
search.addEventListener('input', () => { filterTables(); fitLayouts(); });
document.querySelectorAll('[data-billing]').forEach(button => button.addEventListener('click', async () => {
  if (submitting || !selected()) return;
  submitting = true;
  const tableId = selectedId;
  document.querySelectorAll('[data-billing]').forEach(option => { option.disabled = true; });
  openDialog.setAttribute('aria-busy', 'true');
  try {
    const result = await request(`/operacion/mesas/${tableId}/abrir/`, {method: 'POST', data: {billing_mode: button.dataset.billing}});
    if (result.data.map) updateMap(result.data.map);
    if (result.ok || result.status === 409) {
      openDialog.close();
      if (map.has_open_day) chooseTable(tableId);
      toast(result.data.message, !result.ok);
    } else {
      const error = document.getElementById('open-error');
      error.textContent = result.data.message || 'No pudimos abrir la mesa. Actualiza e intenta nuevamente.';
      error.hidden = false;
    }
  } catch { toast('No pudimos conectar. Actualiza las mesas antes de intentar nuevamente.', true); }
  finally {
    submitting = false;
    openDialog.removeAttribute('aria-busy');
    document.querySelectorAll('[data-billing]').forEach(option => { option.disabled = false; });
  }
}));
document.querySelectorAll('[data-refresh]').forEach(button => button.addEventListener('click', async () => {
  button.disabled = true;
  try {
    const result = await request(document.body.dataset.mapUrl);
    if (result.ok) { updateMap(result.data); if (panel.open) updatePanel(); toast('Mesas actualizadas'); }
    else toast('No pudimos actualizar las mesas.', true);
  } catch { toast('No pudimos conectar. Revisa la conexión.', true); }
  finally { button.disabled = false; }
}));
updateTimes();
fitLayouts();
window.addEventListener('resize', fitLayouts);
setInterval(updateTimes, 30000);
