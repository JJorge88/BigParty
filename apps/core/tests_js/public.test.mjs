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

import {formatQuetzales} from '../../../static/js/public/helpers.mjs';
import {initMenu} from '../../../static/js/public/menu.mjs';
test('public totals preserve cents but omit empty decimal places',()=>{
 assert.equal(formatQuetzales(35000),'Q350');assert.equal(formatQuetzales(123450),'Q1,234.50');
 assert.equal(formatQuetzales(1),'Q0.01');assert.equal(formatQuetzales(0),'Q0');
});
test('mobile menu traps tab, closes on Escape or desktop and restores the page',()=>{
 const document=new EventTarget();
 function element(){
  const el=new EventTarget(),attrs=new Map(),classes=new Set();
  el.setAttribute=(key,value)=>attrs.set(key,value);el.getAttribute=key=>attrs.get(key);
  el.classList={add:key=>classes.add(key),remove:key=>classes.delete(key)};
  el.focus=()=>document.activeElement=el;el.closest=()=>el;
  return el;
 }
 const button=element(),nav=element(),body=element(),main={},footer={},links=[element(),element(),element(),element()];
 const viewport=new EventTarget();viewport.matches=true;nav.querySelectorAll=()=>links;
 initMenu({button,nav,body,main,footer,document,viewport});
 button.dispatchEvent(new Event('click'));
 assert.equal(button.getAttribute('aria-expanded'),'true');assert.equal(document.activeElement,links[0]);assert.equal(main.inert,true);
 function key(key,shiftKey=false){const e=new Event('keydown',{cancelable:true});Object.assign(e,{key,shiftKey});document.dispatchEvent(e);return e;}
 links.at(-1).focus();assert.equal(key('Tab').defaultPrevented,true);assert.equal(document.activeElement,button);
 key('Tab',true);assert.equal(document.activeElement,links.at(-1));
 key('Escape');assert.equal(document.activeElement,button);assert.equal(main.inert,false);assert.equal(footer.inert,false);
 assert.equal(button.getAttribute('aria-expanded'),'false');
 button.dispatchEvent(new Event('click'));viewport.matches=false;viewport.dispatchEvent(new Event('change'));
 assert.equal(button.getAttribute('aria-expanded'),'false');assert.equal(main.inert,false);
});

import {initReveals} from '../../../static/js/public/motion.mjs';
test('reduced motion skips reveals and a live preference change reveals pending content',()=>{
 const preference=new EventTarget();preference.matches=true;
 const classes=new Set(),node={classList:{add:c=>classes.add(c)}};
 let observed=0,disconnected=false,callback;
 class Observer {constructor(cb){callback=cb;}observe(){observed++;}unobserve(){observed--;}disconnect(){disconnected=true;}}
 initReveals({elements:[node],preference,Observer});
 assert.equal(observed,0);assert.equal(classes.size,0);
 preference.matches=false;initReveals({elements:[node],preference,Observer});
 assert.equal(observed,1);assert.equal(classes.has('reveal-ready'),true);
 callback([{isIntersecting:false,target:node}]);assert.equal(classes.has('is-visible'),false);
 preference.matches=true;preference.dispatchEvent(new Event('change'));
 assert.equal(disconnected,true);assert.equal(classes.has('is-visible'),true);
});
