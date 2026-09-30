const content = document.querySelector('[data-sync-readonly]');
if (content) {
  for (const form of content.querySelectorAll('form')) {
    if ((form.method || '').toLowerCase() !== 'post') continue;
    // Arrival is the sole local operation on a cloud-owned reservation.
    const arrival = form.querySelector('[name="action"][value="arrive"]');
    if (arrival && content.dataset.syncReadonly === 'cloud') continue;
    form.hidden = true;
    for (const control of form.elements) control.disabled = true;
  }
  for (const link of content.querySelectorAll('a[href]')) {
    if (/\/(crear|nueva|nuevo|editar|entrada|ajuste|precio|pin|password|permisos|estado|abrir|cerrar|reabrir)\//.test(new URL(link.href).pathname)) {
      link.hidden = true;
      link.removeAttribute('href');
    }
  }
}
