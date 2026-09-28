import test from 'node:test';
import assert from 'node:assert/strict';
import {reconcileSelection} from '../../../static/js/operations/payment-selection.mjs';

test('una línea pagada por otra tablet deja de bloquear nuevas selecciones', () => {
  const result = reconcileSelection(new Map([[1,2],[2,1]]), [{id:1,available_quantity:0},{id:2,available_quantity:3}]);
  assert.deepEqual([...result], [[2,1]]);
});
test('reduce cantidades obsoletas y conserva selección todavía disponible', () => {
  const result = reconcileSelection(new Map([[1,4],[2,2],[3,1]]), [{id:1,available_quantity:2},{id:2,available_quantity:5}]);
  assert.deepEqual([...result], [[1,2],[2,2]]);
});
