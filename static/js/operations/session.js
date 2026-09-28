import {request} from './ui.js';
const timeout = Number(document.body.dataset.idleTimeout) * 1000;
let lastActivity = Date.now();
let lastHeartbeat = Date.now();
let heartbeatPending = false;
let locking = false;

async function lock() {
  if (locking) return;
  locking = true;
  document.body.classList.add('is-locking');
  try { await request(document.body.dataset.lockUrl, {method: 'POST'}); }
  catch { /* El backend también rechaza la sesión vencida. */ }
  finally { location.replace(document.body.dataset.accessUrl); }
}

function activity() {
  if (locking) return;
  if (Date.now() - lastActivity >= timeout) { lock(); return; }
  lastActivity = Date.now();
  if (!heartbeatPending && Date.now() - lastHeartbeat >= Math.min(30000, timeout / 3)) {
    heartbeatPending = true;
    request(document.body.dataset.activityUrl, {method: 'POST'})
      .then(result => { if (result.ok) lastHeartbeat = Date.now(); })
      .catch(() => {})
      .finally(() => { heartbeatPending = false; });
  }
}
['pointerdown', 'keydown', 'touchstart', 'scroll'].forEach(name => document.addEventListener(name, activity, {passive: true, capture: true}));
setInterval(() => { if (Date.now() - lastActivity >= timeout) lock(); }, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - lastActivity >= timeout) lock(); });
window.addEventListener('pageshow', event => {
  if (event.persisted) { document.body.classList.add('is-locking'); location.reload(); }
});
