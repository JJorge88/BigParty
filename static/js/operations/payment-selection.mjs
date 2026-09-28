// Conserva cantidades útiles al recibir una cuenta actualizada después de un conflicto.
export function reconcileSelection(selection, lines) {
  const available = new Map(lines.map(line => [line.id, line.available_quantity]));
  return new Map([...selection]
    .map(([id, quantity]) => [id, Math.min(quantity, available.get(id) || 0)])
    .filter(([, quantity]) => quantity > 0));
}
