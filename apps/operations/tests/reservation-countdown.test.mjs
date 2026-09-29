import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../../../static/js/operations/reservations.js', import.meta.url), 'utf8');
const {remainingLabel} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
test('countdown reaches expiry and cannot show negative time', () => {
  const now = Date.parse('2026-09-28T20:00:00Z');
  assert.equal(remainingLabel('2026-09-28T20:15:00Z', now), '15:00');
  assert.equal(remainingLabel('2026-09-28T19:59:59Z', now), 'Plazo vencido');
  assert.equal(remainingLabel('invalid', now), 'Plazo vencido');
});
