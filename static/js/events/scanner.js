import QrScanner from '../../vendor/qr-scanner/qr-scanner.min.js';
const root = document.querySelector('.scanner');
const video = document.querySelector('#camera');
const frame = document.querySelector('.camera-frame');
const result = document.querySelector('#scan-result');
const next = document.querySelector('#next-scan');
const start = document.querySelector('#start-camera');
const error = document.querySelector('#camera-error');
let busy = false;
const scanner = new QrScanner(video, value => scan(value.data), {preferredCamera: 'environment', maxScansPerSecond: 5, returnDetailedScanResult: true});
async function scan(token) {
  if (busy) return;
  busy = true;
  scanner.stop();
  error.textContent = '';
  try {
    const response = await fetch(root.dataset.scanUrl, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value}, body: JSON.stringify({token})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se registró el acceso. Intenta nuevamente.');
    result.dataset.result = data.result;
    document.querySelector('#scan-label').textContent = data.label;
    document.querySelector('#scan-kind').textContent = data.ticket_type ? `Entrada ${data.ticket_type}` : '';
    document.querySelector('#scan-event').textContent = data.event || 'Control de acceso';
    document.querySelector('#scan-time').textContent = data.used_at ? `${data.result === 'USED' ? 'Hora original' : 'Acceso registrado'}: ${new Date(data.used_at).toLocaleTimeString('es-GT')}` : '';
    frame.hidden = true; result.hidden = false; next.hidden = false; start.hidden = true;
  } catch (exception) {
    error.textContent = exception.message || 'Sin conexión. No se ha confirmado el acceso.';
    busy = false; start.hidden = false;
  }
}
async function camera() {
  busy = false; result.hidden = true; next.hidden = true; frame.hidden = false; error.textContent = '';
  try { await scanner.start(); start.hidden = true; }
  catch (_) { error.textContent = 'No se pudo abrir la cámara. Permite su uso y abre esta página mediante HTTPS (o localhost en desarrollo).'; start.hidden = false; }
}
start.addEventListener('click', camera);
next.addEventListener('click', camera);
document.querySelector('#dev-scan-form')?.addEventListener('submit', event => {event.preventDefault(); busy = false; scan(document.querySelector('#dev-token').value);});
window.addEventListener('pagehide', () => scanner.destroy());
document.addEventListener('visibilitychange', () => {if (document.hidden) {scanner.stop(); start.hidden = false;}});

document.querySelector('#dev-qr-image')?.addEventListener('change', async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const decoded = await QrScanner.scanImage(file, {returnDetailedScanResult: true});
    busy = false;
    await scan(decoded.data);
  } catch (_) {error.textContent = 'No se encontró un QR legible en la imagen de prueba.';}
});
