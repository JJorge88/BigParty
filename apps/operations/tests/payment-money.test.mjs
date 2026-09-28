import test from 'node:test';
import assert from 'node:assert/strict';
import {cents, changeLabel} from '../../../static/js/operations/payment-money.mjs';

test('efectivo: cambio decimal exacto, incluido recibido exacto', () => {
  assert.equal(changeLabel('300', '275.00'), 'Q25.00');
  assert.equal(changeLabel('0.30', '0.10'), 'Q0.20');
  assert.equal(changeLabel('275', '275.00'), 'Q0.00');
});
test('rechaza importes vacíos, negativos, no finitos y fracciones de centavo', () => {
  for (const value of ['', '-1', 'NaN', 'Infinity', '1.001', '1e2']) assert.equal(cents(value), null);
  assert.equal(changeLabel('20', '25'), '—');
});
