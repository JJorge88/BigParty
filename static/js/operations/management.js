import {setupDialogs, csrfToken} from './ui.js';

setupDialogs();
document.querySelectorAll('[data-open-dialog]').forEach(button => {
  button.addEventListener('click', () => document.getElementById(button.dataset.openDialog)?.showModal());
});

// Las lecturas automáticas no prolongan la sesión: solo la actividad del usuario.
const body = document.body;
const timeout = Number(body.dataset.idleTimeout) * 1000;
let lastActivity = Date.now();
let lastSent = Date.now();
let checking = false;
let expired = false;
const activityChannel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('bigparty-management-activity') : null;
if (activityChannel) activityChannel.onmessage = event => {
  if (event.data?.type === 'activity' && Number.isFinite(event.data.at)) {
    lastActivity = Math.max(lastActivity, Math.min(event.data.at, Date.now()));
  }
};
async function endSession() {
  if (expired) return;
  expired = true;
  body.classList.add('is-locking');
  try {
    await fetch(body.dataset.logoutUrl, {method:'POST', credentials:'same-origin',
      headers:{'X-CSRFToken':csrfToken()}});
  } finally { location.replace(body.dataset.loginUrl); }
}
async function userActivity() {
  if (expired) return;
  const now = Date.now();
  if (now - lastActivity >= timeout) return endSession();
  lastActivity = now;
  activityChannel?.postMessage({type:'activity',at:now});
  if (checking || now - lastSent < 30000) return;
  checking = true;
  try {
    const response = await fetch(body.dataset.activityUrl, {method:'POST', credentials:'same-origin',
      cache:'no-store', headers:{'X-CSRFToken':csrfToken(),Accept:'application/json'}});
    if (response.status === 401 || response.redirected) return endSession();
    if (response.ok) lastSent = now;
  } catch { /* El servidor conserva su propio vencimiento, incluso sin conexión. */ }
  finally { checking = false; }
}
if (timeout > 0) {
  ['pointerdown','keydown','scroll'].forEach(name => document.addEventListener(name,userActivity,{passive:true}));
  setInterval(() => { if (Date.now() - lastActivity >= timeout) endSession(); }, 5000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - lastActivity >= timeout) endSession();
  });
}
