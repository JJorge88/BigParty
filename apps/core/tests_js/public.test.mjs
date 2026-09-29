import test from 'node:test';
import assert from 'node:assert/strict';
import {clampQuantity,totalCents,remainingSeconds,formatCountdown} from '../../../static/js/public/helpers.mjs';
test('quantities start at zero and respect bounds and integer values',()=>{
 assert.equal(clampQuantity(-1,5),0);assert.equal(clampQuantity(9,5),5);assert.equal(clampQuantity('bad',5),0);assert.equal(clampQuantity(2.8,5),2);
});
test('mixed cart totals use integer cents',()=>{
 assert.equal(totalCents([{quantity:2,price:100,maximum:10},{quantity:1,price:150,maximum:10}]),35000);
 assert.equal(totalCents([{quantity:6,price:100,maximum:6}]),60000);
});
test('countdown uses server time and elapsed monotonic time, never device calendar',()=>{
 assert.equal(remainingSeconds('2026-10-01T20:15:00Z','2026-10-01T20:00:00Z',30000),870);
 assert.equal(remainingSeconds('2026-10-01T20:00:00Z','2026-10-01T20:00:00Z',1000),0);
 assert.equal(remainingSeconds('bad','bad',1000),0);assert.equal(formatCountdown(65),'01:05');
});
