import {request, setupDialogs} from './ui.js';
setupDialogs();

for (const button of document.querySelectorAll('[data-user]')) {
  button.addEventListener('click', () => {
    document.getElementById('selected-user-id').value = button.dataset.user;
    document.getElementById('selected-user').textContent = button.dataset.name;
    document.getElementById('cash-pin').value = '';
    document.querySelector('#pin-dialog [data-form-error]').hidden = true;
    document.getElementById('pin-dialog').showModal();
    document.getElementById('cash-pin').focus();
  });
}
for (const button of document.querySelectorAll('[data-handoff]')) {
  button.addEventListener('click', () => {
    document.getElementById('handoff-id').value = button.dataset.handoff;
    for (const key of ['waiter', 'table', 'amount']) {
      document.getElementById(`handoff-${key}`).textContent = (key === 'amount' ? 'Q' : '') + button.dataset[key];
    }
    document.querySelector('#handoff-dialog [data-form-error]').hidden = true;
    document.getElementById('handoff-dialog').showModal();
  });
}
for (const button of document.querySelectorAll('[data-reason]')) {
  button.addEventListener('click', () => {
    const input = document.getElementById('withdraw-reason');
    input.value = button.dataset.reason;
    input.focus();
  });
}
for (const form of document.querySelectorAll('[data-cash-form]')) {
  let pending = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending) return;
    pending = true;
    const buttons = [...form.querySelectorAll('button:not([type=button])')];
    const data = new FormData(form);
    buttons.forEach(button => { button.disabled = true; });
    let error = form.querySelector('[data-form-error]');
    if (!error) {
      error = document.createElement('p');
      error.className = 'form-error';
      error.setAttribute('role', 'alert');
      form.append(error);
    }
    error.hidden = true;
    try {
      const result = await request(form.action, {method: 'POST', data});
      if (result.ok && result.data.next) { location.replace(result.data.next); return; }
      error.textContent = result.data.message || 'No se pudo completar la operación. Actualiza la pantalla.';
      error.hidden = false;
      if (result.data.refresh) {
        // El mensaje permanece visible; la fila ya entregada desaparece incluso si se cancela.
        const id = data.get('handoff');
        [...document.querySelectorAll('[data-handoff]')].find(row => row.dataset.handoff === id)?.closest('.cash-row')?.remove();
      }
    } catch {
      error.textContent = 'No se pudo confirmar la respuesta. Actualiza la pantalla antes de repetir la operación.';
      error.hidden = false;
    } finally {
      form.querySelectorAll('input[type=password]').forEach(input => { input.value = ''; });
      pending = false;
      buttons.forEach(button => { button.disabled = false; });
    }
  });
}
setTimeout(() => document.querySelectorAll('[data-feedback]').forEach(node => node.remove()), 4500);
