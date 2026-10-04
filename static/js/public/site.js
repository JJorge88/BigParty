import {clampQuantity, totalCents, remainingSeconds, formatCountdown, formatQuetzales} from './helpers.mjs';
document.documentElement.classList.add('js');
import {initReveals} from './motion.mjs';
import {initMenu} from './menu.mjs';
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
try {
 initMenu({button:document.querySelector('[data-menu-toggle]'), nav:document.getElementById('public-nav'),
  body:document.body, main:document.querySelector('main'), footer:document.querySelector('footer'),
  document, viewport:matchMedia('(max-width:700px)')});
} catch(error) { console.error('No fue posible iniciar el menú.', error); }
try {
 initReveals({elements:[...document.querySelectorAll('[data-reveal]')], preference:reducedMotion, Observer:window.IntersectionObserver});
} catch(error) { console.error('No fue posible iniciar las animaciones.', error); }
const areas=[...document.querySelectorAll('[data-area]')];
const tabs=[...document.querySelectorAll('[data-area-select]')];
function selectArea(slug){areas.forEach(area=>area.hidden=area.dataset.area!==slug);tabs.forEach(tab=>tab.setAttribute('aria-pressed',String(tab.dataset.areaSelect===slug)));}
tabs.forEach(tab=>tab.addEventListener('click',()=>selectArea(tab.dataset.areaSelect)));
if(tabs.length)selectArea(tabs[0].dataset.areaSelect);
const map=document.querySelector('[data-map-form]');
const mapButton=map?.querySelector('button[type=submit], .selection-bar button');
if(mapButton)mapButton.disabled=true;
map?.addEventListener('change',()=>{const selected=map.querySelector('input:checked');if(selected){document.querySelector('[data-table-summary]').textContent=`${selected.dataset.tableName} · ${selected.dataset.tableArea} · ${selected.dataset.tableCapacity} personas`;mapButton.disabled=false;}});
const checkout=document.querySelector('[data-checkout]');
if(checkout && checkout.dataset.enhanced!=='true'){
 checkout.dataset.enhanced='true';
 const quantities=[...checkout.querySelectorAll('[data-price]')];
 const tables=[...checkout.querySelectorAll('[name=table]')];
 const total=checkout.querySelector('[data-total-display]');
 const action=checkout.querySelector('[data-purchase-action]');
 const guest=checkout.querySelector('[data-checkout-guest]');

 function update(){
  const table=tables.find(t=>t.checked);
  const summary=checkout.querySelector('[data-event-table-summary]');
  if(summary)summary.textContent=table?table.dataset.tableSummary:'Selecciona una mesa disponible para ver tu elección.';
  const cents=table?Math.round(Number(table.dataset.total)*100):totalCents(quantities.map(input=>({quantity:input.value,maximum:input.max,price:input.dataset.price})));
  total.textContent=formatQuetzales(cents);action.disabled=cents<=0 || checkout.hasAttribute('data-preview');
  quantities.forEach(input=>{const stepper=input.closest('.stepper');stepper.querySelector('[data-delta="-1"]').disabled=Number(input.value)<=0;stepper.querySelector('[data-delta="1"]').disabled=Number(input.value)>=Number(input.max);});
 }
 quantities.forEach(input=>input.addEventListener('input',()=>{input.value=clampQuantity(input.value,input.max);tables.forEach(t=>t.checked=false);update();}));
 checkout.querySelectorAll('[data-delta]').forEach(button=>button.addEventListener('click',()=>{const input=button.closest('.stepper').querySelector('input');input.value=clampQuantity(Number(input.value)+Number(button.dataset.delta),input.max);tables.forEach(t=>t.checked=false);update();}));
 tables.forEach(table=>table.addEventListener('change',()=>{quantities.forEach(input=>input.value=0);update();}));
 checkout.querySelector('[data-clear-table]')?.addEventListener('click',()=>{tables.forEach(t=>t.checked=false);update();});
 guest.hidden=true;action.type='button';action.textContent='Continuar ↗';
 action.addEventListener('click',()=>{if(guest.hidden){guest.hidden=false;guest.scrollIntoView({behavior:reducedMotion.matches?'auto':'smooth',block:'start'});guest.querySelector('input')?.focus({preventScroll:true});action.textContent='Confirmar y pagar ↗';}else{checkout.requestSubmit();}});
 update();
}
const started=performance.now();
let revalidating=false;
const countdowns=[...document.querySelectorAll('[data-deadline]')];
function tick(){countdowns.forEach(node=>{const seconds=remainingSeconds(node.dataset.deadline,document.body.dataset.serverNow,performance.now()-started);node.textContent=formatCountdown(seconds);if(seconds===0 && !revalidating){revalidating=true;node.textContent='Actualizando…';location.replace(location.href);}});}
if(countdowns.length){tick();setInterval(tick,1000);}
// Las transiciones de Gerencia se consultan al volver a la pestaña o con el enlace de actualización.
// No recargar mientras alguien está completando el comprobante.
let dirty=false;document.querySelectorAll('form[method=post]').forEach(form=>form.addEventListener('input',()=>dirty=true));
document.addEventListener('visibilitychange',()=>{if(!document.hidden && document.querySelector('[data-live-portal]') && !dirty && performance.now()-started>15000)location.reload();});
