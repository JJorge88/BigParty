import test from 'node:test';
import assert from 'node:assert/strict';
import {filterProducts} from '../../../static/js/operations/catalog-filter.mjs';

const products = [{name:'Gallo',category_id:1}, {name:'Cabro',category_id:1}, {name:'Hamburguesa',category_id:2}, {name:'Cóctel Gallo',category_id:3}];
test('cambiar categorías no conserva productos anteriores', () => {
  assert.deepEqual(filterProducts(products, 1, '').map(p => p.name), ['Gallo','Cabro']);
  assert.deepEqual(filterProducts(products, 2, '').map(p => p.name), ['Hamburguesa']);
  assert.equal(filterProducts(products, '', '').length, 4);
});
test('la búsqueda combina categoría, mayúsculas y acentos', () => {
  assert.deepEqual(filterProducts(products, '1', ' GALLO ').map(p => p.name), ['Gallo']);
  assert.deepEqual(filterProducts(products, 2, 'Gallo'), []);
  assert.deepEqual(filterProducts(products, '', 'coctel').map(p => p.name), ['Cóctel Gallo']);
});
