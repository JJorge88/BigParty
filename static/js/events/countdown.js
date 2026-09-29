const node = document.querySelector('[data-deadline]');
if (node) {
  const render = () => {
    const remaining = Math.max(0, Math.ceil((Date.parse(node.dataset.deadline) - Date.now()) / 1000));
    node.textContent = remaining ? `Cupo reservado · ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')} para enviar tu comprobante` : 'El plazo terminó. Actualiza para revisar tu compra.';
    if (!remaining) clearInterval(timer);
  };
  const timer = setInterval(render, 1000);
  render();
}
