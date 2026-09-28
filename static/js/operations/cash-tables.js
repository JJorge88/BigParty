import {normalize} from './catalog-filter.mjs';
const search = document.getElementById('cash-table-search');
search.addEventListener('input', () => {
  const query = normalize(search.value);
  const tables = [...document.querySelectorAll('[data-table-name]')];
  tables.forEach(table => { table.hidden = !normalize(table.dataset.tableName).includes(query); });
  document.getElementById('cash-no-tables').hidden = tables.some(table => !table.hidden);
});
