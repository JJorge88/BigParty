import {request, setupDialogs} from './ui.js';
setupDialogs();
const dialog = document.getElementById('pin-dialog');
const form = document.getElementById('pin-form');
const input = document.getElementById('pin-input');
const enter = document.getElementById('pin-enter');
let busy = false;

function update(value) {
  input.value = value.slice(0, 6);
  enter.disabled = input.value.length < 4 || busy;
}

document.querySelectorAll('[data-user-id]').forEach(button => button.addEventListener('click', () => {
  document.getElementById('pin-title').textContent = button.dataset.userName;
  document.getElementById('pin-avatar').textContent = button.dataset.initials;
  document.getElementById('pin-user-id').value = button.dataset.userId;
  document.getElementById('pin-error').textContent = '';
  update('');
  dialog.showModal();
  input.focus();
}));

document.querySelectorAll('[data-digit]').forEach(button => button.addEventListener('click', () => {
  if (!busy) update(input.value + button.dataset.digit);
}));
document.getElementById('pin-delete')?.addEventListener('click', () => {
  if (!busy) update(input.value.slice(0, -1));
});
dialog?.addEventListener('keydown', event => {
  if (busy || event.ctrlKey || event.metaKey || event.altKey) return;
  if (/^[0-9]$/.test(event.key)) { event.preventDefault(); update(input.value + event.key); }
  else if (event.key === 'Backspace') { event.preventDefault(); update(input.value.slice(0, -1)); }
  else if (event.key === 'Enter' && event.target === input) { event.preventDefault(); if (!enter.disabled) form.requestSubmit(); }
});
dialog?.addEventListener('close', () => update(''));
form?.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || input.value.length < 4) return;
  const data = {user_id: document.getElementById('pin-user-id').value, pin: input.value};
  busy = true;
  enter.disabled = true;
  form.setAttribute('aria-busy', 'true');
  document.getElementById('pin-error').textContent = '';
  try {
    const result = await request(form.action, {method: 'POST', data});
    if (result.ok) location.replace(result.data.next);
    else document.getElementById('pin-error').textContent = result.data.message || 'No pudimos ingresar. Intenta nuevamente.';
  } catch {
    document.getElementById('pin-error').textContent = 'No pudimos conectar. Revisa la conexión e intenta nuevamente.';
  } finally {
    data.pin = '';
    busy = false;
    update('');
    form.removeAttribute('aria-busy');
  }
});
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
