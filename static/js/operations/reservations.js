export function remainingLabel(deadline, now = Date.now()) {
  const seconds = Math.max(0, Math.ceil((Date.parse(deadline) - now) / 1000));
  if (!Number.isFinite(seconds) || seconds === 0) return 'Plazo vencido';
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}
if (typeof document !== 'undefined') {
  const refresh = () => document.querySelectorAll('[data-deadline]').forEach(node => {
    node.textContent = remainingLabel(node.dataset.deadline);
  });
  refresh();
  setInterval(refresh, 1000);
}
