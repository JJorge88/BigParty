export function clampQuantity(value, maximum) {
  const n = Number(value);
  return Math.min(Math.max(0, Number(maximum) || 0), Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0);
}
export function totalCents(rows) {
  return rows.reduce((sum, row) => sum + clampQuantity(row.quantity, row.maximum) * Math.round(Number(row.price) * 100), 0);
}
export function remainingSeconds(deadline, serverNow, elapsedMilliseconds) {
  const remaining = Date.parse(deadline) - Date.parse(serverNow) - elapsedMilliseconds;
  return Number.isFinite(remaining) ? Math.max(0, Math.ceil(remaining / 1000)) : 0;
}
export function formatCountdown(seconds) {
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}

export function formatQuetzales(cents) {
  const amount = cents / 100;
  return 'Q' + new Intl.NumberFormat('en-US', {
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2, maximumFractionDigits: 2
  }).format(amount);
}
