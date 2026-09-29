import {request, toast, element} from './ui.js';
import {cents, changeLabel} from './payment-money.mjs';
import {reconcileSelection as availableSelection} from './payment-selection.mjs';
import './session.js';

let state = JSON.parse(document.getElementById('account-state').textContent);
let view = 'account', method = '', mixed = false, busy = false, blocked = false;
let selection = new Map(), quote = null, scope = '', scopeAmount = '', scopeComplete = false;
let quoteVersion = 0, quoteTimer;
const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };
const show = (id, visible) => { $(id).hidden = !visible; };
const url = document.body.dataset.accountUrl;
const methodNames = {efectivo:'Pago en efectivo', tarjeta:'Pago con tarjeta', transferencia:'Transferencia', deposito:'Depósito'};
const confirmNames = {efectivo:'Confirmar pago en efectivo', tarjeta:'Confirmar pago con tarjeta', transferencia:'Registrar transferencia', deposito:'Registrar depósito'};
function error(message = '') { text('account-error', message); show('account-error', !!message); }
function data(values = {}) { return new URLSearchParams({subaccount:state.selected_account || '', ...values}); }
function clearQuote() { quoteVersion++; clearTimeout(quoteTimer); quote = null; }
function reconcileSelection() {
  selection = availableSelection(selection, state.lines);
}
function resetPayment() {
  clearQuote(); method = ''; mixed = false; scope = ''; scopeAmount = ''; scopeComplete = false;
  $('cash-received').value = ''; $('payment-reference').value = ''; $('mixed-amount').value = '';
}
function accountView() { view = 'account'; resetPayment(); render(); }
function controls() {
  $('refresh-account').disabled = busy;
  $('collect-all').disabled = busy || blocked || !state.can_pay;
  $('divide-account').disabled = busy || blocked || !state.can_pay || !state.lines.some(line => line.available_quantity);
  $('continue-payment').disabled = busy || blocked || !quote;
  $('close-account').disabled = busy || blocked || !state.can_close;
  $('confirm-payment').disabled = busy || blocked || !quote || !method ||
    (method === 'efectivo' && changeLabel($('cash-received').value, quote.amount) === '—') ||
    (['transferencia','deposito'].includes(method) && !$('payment-reference').value.trim());
  document.querySelectorAll('[data-quantity], .account-tab, [data-method], #mixed-method, #back-account, #cancel-payment').forEach(button => { button.disabled = busy; });
  $('mixed-amount').disabled = busy; $('cash-received').disabled = busy; $('payment-reference').disabled = busy;
  document.querySelectorAll('.quick-cash button').forEach(button => { button.disabled = busy; });
}
function lineCard(line, dividing = false) {
  const card = element('article', 'consumption-line');
  const body = element('div', 'consumption-description');
  body.append(element('strong', '', `${line.quantity} × ${line.name}`));
  if (line.modifiers.length) body.append(element('p', 'line-detail', line.modifiers.join(' · ')));
  if (line.notes) body.append(element('p', 'line-note', line.notes));
  body.append(element('p', 'line-unit-price', `${line.unit_price} c/u`));
  const status = [];
  if (line.paid_quantity) status.push(`${line.paid_quantity} pagadas`);
  if (line.outstanding_quantity) status.push(`${line.outstanding_quantity} pendientes`);
  if (line.pending_quantity) status.push(`${line.pending_quantity} por verificar`);
  if (line.adjusted_quantity) status.push(`${line.adjusted_quantity} con cortesía / descuento`);
  if (line.partial_quantity) status.push(`${line.partial_quantity} con abono`);
  body.append(element('p', 'line-coverage', status.join(' · ') || 'Sin saldo pendiente'));
  card.append(body);
  if (dividing) {
    const controls = element('div', 'selection-controls');
    controls.append(element('small', '', `Disponible: ${line.available_quantity}`));
    const group = element('div', 'quantity-controls');
    const value = selection.get(line.id) || 0;
    for (const [delta, label] of [[-1,'−'],[1,'+']]) {
      const button = element('button', 'icon-button', label); button.type = 'button'; button.dataset.quantity = line.id;
      button.setAttribute('aria-label', `${delta < 0 ? 'Reducir' : 'Seleccionar'} ${line.name}`);
      button.addEventListener('click', () => {
        const next = Math.max(0, Math.min(line.available_quantity, (selection.get(line.id) || 0) + delta));
        selection.set(line.id, next); updateSelection();
      });
      group.append(button);
      if (delta < 0) group.append(element('output', '', value));
    }
    controls.append(group);
    if (value && quote?.line_amounts[String(line.id)]) controls.append(element('strong', 'selected-line-total', quote.line_amounts[String(line.id)]));
    card.append(controls);
  } else card.append(element('strong', 'consumption-subtotal', line.subtotal));
  return card;
}
function history(target) {
  target.replaceChildren();
  if (!state.history.length) target.append(element('p', 'muted', 'Todavía no hay pagos registrados.'));
  state.history.forEach(payment => {
    const row = element('div', 'payment-history-row');
    const detail = element('div'); detail.append(element('strong', '', payment.method));
    detail.append(element('span', `payment-status status-${payment.status.toLowerCase()}`, payment.status_label));
    if (payment.reference) detail.append(element('small', 'payment-reference', payment.reference));
    if (payment.refunded) detail.append(element('small', 'payment-reference', `Reembolsado ${payment.refunded}`));
    row.append(detail, element('strong', '', payment.amount)); target.append(row);
  });
}
function render() {
  const summary = state.summary;
  text('financial-context', state.selected_name);
  text('financial-total', summary.charge_total); text('financial-paid', summary.confirmed_paid); text('financial-balance', summary.outstanding_balance);
  text('financial-reserved', summary.pending_verification); text('financial-available', summary.available_to_pay);
  show('reserved-summary', state.has_pending); show('draft-warning', state.has_drafts); show('pending-warning', state.has_pending);
  if (state.quick_sale) {
    text('pending-warning', 'Pago pendiente de verificación por Gerencia. No entregar todavía.');
    text('scope-complete', state.has_pending ? 'Pago pendiente de verificación. La venta sigue abierta; no entregar todavía.' : 'Pago registrado. Revisa el saldo para completar la venta.');
  }
  show('gross-row', state.has_adjustments || state.has_refunds); text('gross-value', summary.gross_total);
  show('adjustments-row', state.has_adjustments); text('adjustments-value', `−${summary.adjustments}`);
  show('refunds-row', state.has_refunds); text('refunds-value', `−${summary.refunds}`);
  show('accounts-section', state.billing_mode === 'SPLIT' && view === 'account');
  const tabs = $('financial-accounts'); tabs.replaceChildren();
  state.accounts.forEach(account => {
    const button = element('button', 'account-tab'); button.type = 'button';
    button.setAttribute('aria-pressed', String(state.selected_account === account.id));
    button.append(element('strong', '', account.name), element('small', '', account.closed ? 'Pagada' : `${account.balance} ${account.pending ? '· Por verificar' : 'pendiente'}`));
    button.addEventListener('click', () => refresh(account.id)); tabs.append(button);
  });
  document.querySelectorAll('.add-products').forEach(link => { link.href = state.order_url; link.hidden = !state.can_add || view !== 'account'; });
  show('consumption-view', view === 'account'); show('division-view', view === 'divide'); show('payment-view', view === 'payment');
  show('back-account', view !== 'account'); show('account-actions', view === 'account');
  show('divide-account', state.billing_mode === 'SINGLE' && !state.quick_sale); show('close-section', state.can_close && view !== 'divide');
  show('paid-account-note', state.account_closed); show('collect-all', !state.account_closed && !state.can_close);
  text('collect-all', state.selected_account ? `Cobrar a ${state.selected_name}` : 'Cobrar');
  text('view-title', view === 'divide' ? 'Dividir cuenta' : view === 'payment' ? (mixed ? 'Pago mixto' : `Cobrar ${state.table_name}`) : 'Ver cuenta');
  text('view-eyebrow', view === 'divide' ? 'SELECCIÓN POR CANTIDAD' : view === 'payment' ? state.selected_name : state.quick_sale ? 'VENTA RÁPIDA' : 'CONSUMO DE LA MESA');
  const unpaid = $('unpaid-lines'), paid = $('paid-lines'); unpaid.replaceChildren(); paid.replaceChildren();
  state.lines.forEach(line => (line.settled ? paid : unpaid).append(lineCard(line)));
  show('paid-section', !!paid.children.length); text('paid-count', `${paid.children.length} productos`);
  show('account-empty', !state.lines.length); text('account-empty-title', state.billing_mode === 'SPLIT' && !state.selected_account ? 'Selecciona una cuenta' : 'Sin consumo enviado');
  const selectionLines = $('selection-lines'); selectionLines.replaceChildren();
  state.lines.filter(line => line.available_quantity).forEach(line => selectionLines.append(lineCard(line, true)));
  show('selection-summary', view === 'divide'); text('selection-total', quote?.amount_label || 'Q0.00');
  history($('payment-history')); history($('mixed-payment-history')); show('mixed-history', view === 'payment' && mixed);
  show('mixed-entry', mixed && !scopeComplete); show('mixed-method', !mixed); show('scope-complete', scopeComplete);
  show('payment-methods', !scopeComplete); show('payment-form', !!method && !scopeComplete);
  text('payment-amount-label', mixed ? 'Disponible de este pago' : 'Monto a pagar');
  text('payment-amount', mixed ? scopeAmount : quote?.amount_label || '—');
  show('cash-fields', method === 'efectivo'); show('card-fields', method === 'tarjeta'); show('reference-fields', ['transferencia','deposito'].includes(method));
  text('method-title', methodNames[method] || ''); text('confirm-payment', confirmNames[method] || 'Confirmar pago');
  document.querySelectorAll('[data-method]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.method === method)));
  const quick = $('quick-cash'); quick.replaceChildren();
  if (quote) quote.quick_cash.forEach(item => { const button = element('button', 'button', item.label); button.type = 'button'; button.addEventListener('click', () => { $('cash-received').value = item.value; cashChange(); }); quick.append(button); });
  cashChange(); controls();
}
function cashChange() { text('cash-change', quote ? changeLabel($('cash-received').value, quote.amount) : '—'); controls(); }
async function refresh(account = state.selected_account) {
  if (busy) return; busy = true; clearQuote(); controls();
  try {
    const result = await request(`${url}?${new URLSearchParams({subaccount:account || ''})}`);
    if (result.ok && result.data.next) { location.replace(result.data.next); return; }
    if (!result.ok) { blocked = true; error(result.data.message || 'Vuelve a mesas para consultar la cuenta.'); }
    else { state = result.data.state; blocked = false; error(); show('payment-feedback', false); view = 'account'; resetPayment(); selection.clear(); }
  } catch { blocked = true; error('No pudimos conectar. Actualiza la cuenta antes de continuar.'); }
  finally { busy = false; render(); }
}
async function prepare(values, action = 'preparar') {
  const result = await request(`${url}${action}/`, {method:'POST', data:data(values)});
  if (!result.ok) {
    if (result.data.state) { state = result.data.state; reconcileSelection(); }
    error(result.data.message || 'No pudimos preparar el pago. Actualiza la cuenta.');
    return null;
  }
  return result.data.quote;
}
function updateSelection() {
  reconcileSelection();
  clearQuote(); render(); error();
  const rows = [...selection].filter(([, quantity]) => quantity > 0).map(([line_id, quantity]) => ({line_id, quantity}));
  if (!rows.length) return;
  const version = quoteVersion;
  quoteTimer = setTimeout(async () => {
    try {
      const value = await prepare({selection:JSON.stringify(rows)}, 'seleccion');
      if (version !== quoteVersion || view !== 'divide') return;
      quote = value; render();
    } catch { if (version === quoteVersion) { error('No pudimos consultar la selección. Actualiza la cuenta.'); controls(); } }
  }, 120);
}
$('divide-account').addEventListener('click', () => { view = 'divide'; resetPayment(); error(); updateSelection(); });
$('continue-payment').addEventListener('click', () => { if (!quote || busy) return; scope = quote.token; scopeAmount = quote.amount_label; view = 'payment'; render(); });
$('collect-all').addEventListener('click', async () => {
  if (busy) return; busy = true; resetPayment(); show('payment-feedback', false); controls(); error();
  try { quote = await prepare({mode:'full'}); if (quote) { scope = quote.token; scopeAmount = quote.amount_label; view = 'payment'; } }
  catch { error('No pudimos consultar el saldo. Actualiza la cuenta.'); }
  finally { busy = false; render(); }
});
function prepareMixed() {
  show('payment-feedback', false);
  clearQuote(); controls(); error();
  const amount = $('mixed-amount').value, version = quoteVersion;
  if (cents(amount) === null || cents(amount) <= 0) { render(); return; }
  quoteTimer = setTimeout(async () => {
    try { const value = await prepare({amount, scope}, 'mixto'); if (version === quoteVersion) { quote = value; render(); } }
    catch { if (version === quoteVersion) error('No pudimos validar el monto. Actualiza la cuenta.'); }
  }, 150);
}
$('mixed-method').addEventListener('click', () => { mixed = true; method = ''; clearQuote(); render(); $('mixed-amount').focus(); });
$('mixed-amount').addEventListener('input', prepareMixed);
document.querySelectorAll('[data-method]').forEach(button => button.addEventListener('click', () => { method = button.dataset.method; show('payment-feedback', false); $('cash-received').value = ''; $('payment-reference').value = ''; render(); if (method === 'efectivo') $('cash-received').focus(); }));
$('cash-received').addEventListener('input', cashChange); $('payment-reference').addEventListener('input', controls);
$('payment-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !quote || $('confirm-payment').disabled) return;
  busy = true; controls(); error();
  try {
    const result = await request(`${url}${method}/`, {method:'POST', data:data({token:quote.token, received:$('cash-received').value, reference:$('payment-reference').value})});
    if (result.ok && result.data.next) { location.replace(result.data.next); return; }
    if (result.data.state) state = result.data.state;
    clearQuote();
    if (!result.ok) { if (!result.data.state) blocked = true; error(result.data.message || 'No pudimos registrar el pago. Actualiza la cuenta.'); view = 'account'; resetPayment(); }
    else {
      const message = result.data.message + (method === 'efectivo' ? ` · Cambio ${result.data.payment.change}` : '');
      text('payment-feedback', message); show('payment-feedback', result.data.payment.status !== 'PENDING'); toast(message);
      if (mixed) {
        method = ''; $('mixed-amount').value = ''; $('cash-received').value = ''; $('payment-reference').value = '';
        if (state.can_pay && !state.account_closed) {
          const remaining = await prepare({mode:'full', scope});
          if (remaining) { scope = remaining.token; scopeAmount = remaining.amount_label; }
          else { scopeComplete = true; scopeAmount = 'Q0.00'; error(); }
        } else { scopeComplete = true; scopeAmount = 'Q0.00'; }
      } else { view = 'account'; resetPayment(); selection.clear(); }
    }
  } catch { clearQuote(); blocked = true; view = 'account'; error('Se interrumpió la conexión. El pago puede haberse registrado. Actualiza la cuenta antes de repetirlo.'); }
  finally { busy = false; render(); }
});
$('close-account').addEventListener('click', async () => {
  if (busy) return; busy = true; controls(); error();
  try {
    const result = await request(`${url}cerrar/`, {method:'POST', data:data()});
    if (result.ok && result.data.next) { location.replace(result.data.next); return; }
    if (result.ok) {
      ['account-layout','accounts-section','draft-warning','pending-warning','payment-feedback'].forEach(id => show(id,false));
      document.querySelectorAll('.add-products').forEach(link => { link.hidden = true; });
      if (result.data.receipt_url) { $('closed-receipt').href = result.data.receipt_url; $('closed-receipt').hidden = false; }
      show('closed-view',true); $('refresh-account').hidden = true; toast('Cuenta cerrada');
    } else { if (result.data.state) state = result.data.state; error(result.data.message || 'No se pudo cerrar. Actualiza la cuenta.'); render(); }
  } catch { blocked = true; error('No pudimos confirmar el cierre. Vuelve a mesas para comprobar el estado.'); }
  finally { busy = false; controls(); }
});
$('refresh-account').addEventListener('click', () => refresh());
$('back-account').addEventListener('click', accountView); $('cancel-payment').addEventListener('click', accountView);
render();

if (state.quick_sale && state.can_pay) $('collect-all').click();
