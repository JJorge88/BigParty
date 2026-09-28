// Solo presentación del efectivo recibido. El monto del cobro llega del servidor.
export function cents(value) {
  const text = String(value).trim();
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ''] = text.split('.');
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
}
export function changeLabel(received, amount) {
  const cash = cents(received), due = cents(amount);
  return cash === null || due === null || cash < due ? '—' : `Q${((cash - due) / 100).toFixed(2)}`;
}
