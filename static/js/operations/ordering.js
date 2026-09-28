import {request, setupDialogs, toast, element} from './ui.js';
import {filterProducts} from './catalog-filter.mjs';
import './session.js';

setupDialogs();
let state = JSON.parse(document.getElementById('order-state').textContent);
let category = '';
let pending = 0;
let selectionPending = false;
let blocked = false;
let queue = Promise.resolve();
let product = null;
let quantity = 1;
let noteLine = null;
let quoteVersion = 0;
let quoteReady = false;
let quoteTimer;
const baseUrl = document.body.dataset.orderUrl;
const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };
const productDialog = $('product-dialog');
const accountDialog = $('account-dialog');
const noteDialog = $('note-dialog');
const search = $('product-search');
const contextReady = () => !blocked && state.has_open_day && (state.billing_mode === 'SINGLE' || state.selected_account !== null);

function payload(data, account = state.selected_account) {
  const body = new URLSearchParams({subaccount: account || '', send_token: state.send_token || ''});
  Object.entries(data).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach(item => body.append(key, item));
    else body.set(key, value);
  });
  return body;
}
function showError(message) {
  text('order-error', message || '');
  $('order-error').hidden = !message;
}
function updateControls() {
  const busy = pending > 0 || selectionPending;
  $('send-order').disabled = busy || !contextReady() || !state.permissions.send_order || !state.drafts.length;
  $('new-account').disabled = busy || blocked || !state.has_open_day || !state.permissions.manage_subaccounts;
  $('refresh-order').disabled = busy;
  $('add-configured').disabled = busy || !quoteReady || !contextReady() || !state.permissions.add_order_line;
  document.querySelectorAll('.account-tab').forEach(button => { button.disabled = busy || button.dataset.closed === 'true'; });
  document.querySelectorAll('[data-line-action]').forEach(button => { button.disabled = busy || !contextReady() || !state.permissions.add_order_line; });
}
function renderProducts() {
  const grid = $('product-grid');
  grid.replaceChildren();
  const products = filterProducts(state.products, category, search.value);
  products.forEach(item => {
    const card = element('button', 'product-card');
    card.type = 'button';
    card.disabled = selectionPending || !item.available || !contextReady() || !state.permissions.add_order_line;
    card.dataset.product = item.id;
    const row = element('span', 'product-name-row');
    row.append(element('strong', '', item.name));
    if (item.image) {
      const img = document.createElement('img');
      img.src = item.image; img.alt = ''; img.loading = 'lazy'; img.className = 'product-image';
      img.addEventListener('error', () => img.remove(), {once: true});
      row.append(img);
    }
    card.append(row, element('span', 'product-kind', item.is_combo ? 'Combo' : item.groups.length ? 'Personalizable' : item.category_name));
    const meta = element('span', 'product-meta');
    meta.append(element('span', 'product-price', item.price));
    if (!item.available) meta.append(element('span', 'product-stock', 'Agotado'));
    else { const add = element('span', 'product-add', '+'); add.setAttribute('aria-hidden', 'true'); meta.append(add); }
    card.append(meta);
    card.addEventListener('click', () => {
      if (item.groups.length) configureProduct(item);
      else mutate('agregar', {product: item.id, quantity: 1});
    });
    grid.append(card);
  });
  $('catalog-empty').hidden = products.length > 0;
}
function renderCategories() {
  const tabs = $('category-tabs');
  tabs.replaceChildren();
  [{id: '', name: 'Todos'}, ...state.categories].forEach(item => {
    const button = element('button', 'category-tab', item.name);
    button.type = 'button'; button.setAttribute('aria-pressed', String(String(item.id) === String(category)));
    button.addEventListener('click', () => {
      category = item.id;
      tabs.querySelectorAll('button').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
      renderProducts();
    });
    tabs.append(button);
  });
}
function renderAccounts() {
  $('split-section').hidden = state.billing_mode !== 'SPLIT';
  const tabs = $('account-tabs'); tabs.replaceChildren();
  state.accounts.forEach(account => {
    const button = element('button', 'account-tab'); button.type = 'button';
    button.dataset.closed = String(account.closed);
    button.setAttribute('aria-pressed', String(account.id === state.selected_account));
    button.append(element('strong', '', account.name), element('small', '', account.closed ? `${account.total} · Cerrada` : account.total));
    button.disabled = account.closed;
    button.addEventListener('click', () => loadAccount(account.id));
    tabs.append(button);
  });
  $('account-needed').hidden = state.billing_mode !== 'SPLIT' || !!state.selected_account;
  $('account-needed').querySelector('p').textContent = state.accounts.some(account => !account.closed) ? 'Selecciona una cuenta para comenzar el pedido.' : 'Crea una cuenta para comenzar el pedido.';
}
function lineButton(label, action, line, content) {
  const button = element('button', 'icon-button'); button.type = 'button';
  button.setAttribute('aria-label', `${label} ${line.name}`); button.dataset.lineAction = action;
  button.append(document.createTextNode(content));
  button.addEventListener('click', () => mutate(action, {line: line.id}));
  return button;
}
function renderDrafts() {
  const lines = $('draft-lines'); lines.replaceChildren();
  state.drafts.forEach(line => {
    const card = element('article', 'draft-line'); card.dataset.line = line.id;
    const heading = element('div', 'draft-line-heading');
    heading.append(element('strong', '', `${line.quantity} × ${line.name}`), element('span', 'line-price', line.subtotal));
    card.append(heading);
    if (line.modifiers.length) card.append(element('p', 'line-detail', line.modifiers.join(' · ')));
    if (line.notes) card.append(element('p', 'line-note', line.notes));
    const actions = element('div', 'line-actions');
    const controls = element('div', 'quantity-controls');
    controls.append(lineButton('Reducir', 'reducir', line, '−'), element('span', 'line-quantity', line.quantity), lineButton('Aumentar', 'aumentar', line, '+'));
    const note = element('button', 'line-note-button', line.notes ? 'Editar nota' : '+ Nota');
    note.type = 'button'; note.dataset.lineAction = 'nota'; note.setAttribute('aria-label', `Nota para ${line.name}`);
    note.addEventListener('click', () => { noteLine = line.id; text('note-product', line.name); $('draft-note').value = line.notes; noteDialog.showModal(); $('draft-note').focus(); });
    actions.append(controls, note, lineButton('Eliminar', 'eliminar', line, '×'));
    card.append(actions); lines.append(card);
  });
  $('draft-empty').hidden = state.drafts.length > 0;
  text('draft-count', state.draft_quantity); text('mobile-count', state.draft_quantity);
  text('draft-total', state.draft_total); text('mobile-total', state.draft_total);
  text('cart-context', state.selected_name);
}
function render() {
  const accountLink = $('order-account-link');
  if (accountLink) accountLink.href = baseUrl.replace('/pedido/', '/cuenta/') + (state.selected_account ? `?subaccount=${state.selected_account}` : '');
  renderCategories(); renderAccounts(); renderProducts(); renderDrafts(); updateControls(); fulfillmentLabel();
  if (!state.has_open_day) showError('No hay una jornada abierta. Solicita a Gerencia revisar la jornada.');
}

async function loadAccount(account = state.selected_account) {
  if (pending || selectionPending) return;
  selectionPending = true; updateControls();
  renderProducts();
  try {
    const result = await request(`${baseUrl}?${new URLSearchParams({subaccount: account || ''})}`);
    if (!result.ok) { blocked = true; showError(result.data.message || 'No pudimos consultar el pedido. Vuelve a mesas.'); }
    else { state = result.data.state; blocked = false; showError(''); }
  } catch { showError('No pudimos conectar. Actualiza antes de continuar.'); }
  finally { selectionPending = false; render(); }
}

function mutate(action, data, {closeProduct = false} = {}) {
  const body = payload(data);
  pending++; updateControls();
  const operation = queue.then(async () => {
    try {
      if (blocked) return false;
      const result = await request(`${baseUrl}${action}/`, {method: 'POST', data: body});
      if (result.ok && result.data.next) { location.assign(result.data.next); return true; }
      if (result.data.state) state = result.data.state;
      if (result.ok) {
        showError('');
        if (action === 'enviar') {
          $('current-order').classList.remove('is-expanded');
          $('cart-toggle').setAttribute('aria-expanded', 'false');
          text('cart-toggle-label', 'Ver pedido ↑');
        }
        if (action === 'cuenta') accountDialog.close();
        if (action === 'nota') noteDialog.close();
        if (closeProduct && productDialog.open) productDialog.close();
        toast(result.data.message);
      } else {
        if (!result.data.state) blocked = true;
        showError(result.data.message || 'No pudimos completar la acción. Actualiza el pedido.');
        toast(result.data.message || 'No pudimos completar la acción.', true);
      }
      return result.ok;
    } catch {
      blocked = true;
      showError('Se interrumpió la conexión. Actualiza el pedido antes de repetir la acción.');
      return false;
    } finally { pending--; render(); }
  });
  queue = operation.catch(() => {});
  return operation;
}

function chosenModifiers() { return [...$('modifier-groups').querySelectorAll('input:checked')].map(input => input.value); }
function groupSelectionsValid() {
  return product.groups.every(group => {
    const count = $('modifier-groups').querySelectorAll(`input[data-group="${group.id}"]:checked`).length;
    return count >= group.min && count <= group.max;
  });
}
function scheduleQuote() {
  clearTimeout(quoteTimer);
  const version = ++quoteVersion;
  quoteReady = false;
  text('product-quantity', quantity); text('product-quote', '—'); $('add-configured').disabled = true;
  $('quantity-minus').disabled = quantity <= 1; $('quantity-plus').disabled = quantity >= 9999;
  $('product-error').hidden = true;
  if (!groupSelectionsValid()) { text('product-error', 'Completa las opciones requeridas.'); $('product-error').hidden = false; return; }
  const data = payload({product: product.id, quantity, modifiers: chosenModifiers()});
  quoteTimer = setTimeout(async () => {
    try {
      const result = await request(`${baseUrl}cotizar/`, {method: 'POST', data});
      if (version !== quoteVersion || !productDialog.open) return;
      if (result.ok) { quoteReady = true; text('product-quote', result.data.quote.total); updateControls(); }
      else { text('product-error', result.data.message || 'Revisa las opciones del producto.'); $('product-error').hidden = false; }
    } catch { if (version === quoteVersion) { text('product-error', 'No pudimos consultar el precio. Cambia una opción para reintentar.'); $('product-error').hidden = false; } }
  }, 120);
}
function configureProduct(item) {
  product = item; quantity = 1;
  text('product-title', item.name); text('product-base-price', `Precio base ${item.price}`); $('product-note').value = '';
  const groups = $('modifier-groups'); groups.replaceChildren();
  item.groups.forEach(group => {
    const fieldset = element('fieldset', 'modifier-group');
    fieldset.append(element('legend', '', group.name), element('p', 'modifier-hint', `${group.required ? 'Obligatorio' : 'Opcional'} · ${group.type === 'SINGLE' ? 'Elige una opción' : `Elige hasta ${group.max} opciones`}${group.min > 1 ? ` · Mínimo ${group.min}` : ''}`));
    group.options.forEach(option => {
      const label = element('label', 'modifier-option');
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = option.id; input.dataset.group = group.id;
      input.addEventListener('change', () => {
        const checked = [...fieldset.querySelectorAll('input:checked')];
        if (input.checked && group.type === 'SINGLE') checked.forEach(other => { if (other !== input) other.checked = false; });
        else if (checked.length > group.max) { input.checked = false; toast(`Puedes elegir hasta ${group.max} opciones.`, true); }
        scheduleQuote();
      });
      label.append(input, element('span', '', option.name));
      if (option.has_extra) label.append(element('small', '', `+${option.extra}`));
      fieldset.append(label);
    });
    groups.append(fieldset);
  });
  productDialog.showModal(); scheduleQuote();
}
search.addEventListener('input', renderProducts);
$('refresh-order').addEventListener('click', () => loadAccount());
$('send-order').addEventListener('click', () => {
  if (pending) return;
  if (state.cash_mode === 'quick') mutate('cobrar', {alias: $('customer-alias')?.value || ''});
  else mutate('enviar', {fulfillment_mode: document.querySelector('[name=fulfillment_mode]:checked')?.value || 'NORMAL_TABLE_SEND'});
});
function fulfillmentLabel() {
  if (state.cash_mode !== 'table') return;
  const taking = document.querySelector('[name=fulfillment_mode]:checked')?.value === 'TAKE_AT_BAR';
  $('send-order').textContent = `${taking ? 'Cargar a' : 'Enviar pedido a'} ${state.table_name}`;
}
document.querySelectorAll('[name=fulfillment_mode]').forEach(input => input.addEventListener('change', fulfillmentLabel));

$('new-account').addEventListener('click', () => { $('account-name').value = ''; $('account-error').hidden = true; accountDialog.showModal(); $('account-name').focus(); });
$('account-form').addEventListener('submit', async event => {
  event.preventDefault(); if (pending) return;
  const button = event.submitter; button.disabled = true;
  const ok = await mutate('cuenta', {name: $('account-name').value});
  if (!ok) { text('account-error', $('order-error').textContent); $('account-error').hidden = false; }
  button.disabled = false;
});
$('product-form').addEventListener('submit', async event => {
  event.preventDefault(); if (pending || $('add-configured').disabled) return;
  $('add-configured').disabled = true;
  await mutate('agregar', {product: product.id, quantity, modifiers: chosenModifiers(), notes: $('product-note').value}, {closeProduct: true});
  if (productDialog.open) scheduleQuote();
});
$('quantity-minus').addEventListener('click', () => { quantity = Math.max(1, quantity - 1); scheduleQuote(); });
$('quantity-plus').addEventListener('click', () => { quantity = Math.min(9999, quantity + 1); scheduleQuote(); });
productDialog.addEventListener('close', () => { quoteVersion++; clearTimeout(quoteTimer); });
$('note-form').addEventListener('submit', async event => {
  event.preventDefault(); if (pending) return;
  const button = event.submitter; button.disabled = true;
  await mutate('nota', {line: noteLine, notes: $('draft-note').value}); button.disabled = false;
});
$('cart-toggle').addEventListener('click', () => {
  const expanded = $('current-order').classList.toggle('is-expanded');
  $('cart-toggle').setAttribute('aria-expanded', String(expanded));
  text('cart-toggle-label', expanded ? 'Cerrar ↓' : 'Ver pedido ↑');
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') { $('current-order').classList.remove('is-expanded'); $('cart-toggle').setAttribute('aria-expanded', 'false'); text('cart-toggle-label', 'Ver pedido ↑'); } });
render();

if (state.cash_mode) search.focus();
