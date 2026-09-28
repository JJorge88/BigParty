export function csrfToken() {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
}

export async function request(url, {method = 'GET', data} = {}) {
  const response = await fetch(url, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: {Accept: 'application/json', ...(method === 'POST' ? {'X-CSRFToken': csrfToken()} : {})},
    body: data ? new URLSearchParams(data) : undefined,
  });
  const content = response.headers.get('Content-Type') || '';
  const result = content.includes('application/json') ? await response.json() : {};
  if (response.status === 401) {
    document.body.classList.add('is-locking');
    location.replace(result.next || '/operacion/acceso/');
    throw new Error('Ingresa nuevamente con tu PIN.');
  }
  return {ok: response.ok, status: response.status, data: result};
}

let toastTimer;
export function toast(message, error = false, duration = 3000) {
  const element = document.getElementById('toast');
  clearTimeout(toastTimer);
  // Un dialog ocupa la capa superior del navegador; el aviso debe vivir dentro
  // del panel abierto para conservar contraste y anunciarse a lectores de pantalla.
  const dialogs = [...document.querySelectorAll('dialog[open]')];
  (dialogs.at(-1) || document.body).append(element);
  element.textContent = message;
  element.classList.toggle('toast--error', error);
  element.hidden = false;
  toastTimer = setTimeout(() => { element.hidden = true; }, duration);
}

export function setupDialogs() {
  document.querySelectorAll('[data-close]').forEach(button => {
    button.addEventListener('click', () => document.getElementById(button.dataset.close).close());
  });
  document.querySelectorAll('dialog').forEach(dialog => {
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
  });
}

export function icon(name, className = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('aria-hidden', 'true');
  if (className) svg.setAttribute('class', className);
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#icon-${name}`);
  svg.append(use);
  return svg;
}

export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
