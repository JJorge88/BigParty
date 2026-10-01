const form = document.querySelector('#table-form');
const board = document.querySelector('.floor-plan');
const table = document.querySelector('#floor-selected');
const field = name => form.elements.namedItem(name);
const number = name => Number(field(name).value) || 0;
const status = document.querySelector('#floor-status');
let dirty = false;
function draw() {
  const width = Math.min(100, Math.max(.01, number('layout_width')));
  const height = Math.min(100, Math.max(.01, number('layout_height')));
  Object.assign(table.style, {left:`${number('layout_x')}%`, top:`${number('layout_y')}%`, width:`${width}%`, height:`${height}%`});
  table.classList.toggle('floor-table--circle', field('layout_shape').value === 'CIRCLE');
  table.querySelector('strong').textContent = field('name').value || 'Nueva mesa';
  table.querySelector('small').textContent = `${number('capacity')} pers.`;
  table.hidden = false;
}
function changed() { dirty = true; status.textContent = 'Cambios sin guardar'; draw(); }
function move(x, y) {
  field('layout_x').value = Math.max(0, Math.min(100 - number('layout_width'), x)).toFixed(2);
  field('layout_y').value = Math.max(0, Math.min(100 - number('layout_height'), y)).toFixed(2);
  changed();
}
let drag;
table.addEventListener('pointerdown', event => {
  if(event.button !== 0 || form.closest('[data-sync-readonly]')) return;
  drag = {x:event.clientX, y:event.clientY, left:number('layout_x'), top:number('layout_y')};
  table.setPointerCapture(event.pointerId);
});
table.addEventListener('pointermove', event => {
  if(!drag) return;
  const rect = board.getBoundingClientRect();
  move(drag.left + (event.clientX-drag.x)/rect.width*100, drag.top + (event.clientY-drag.y)/rect.height*100);
});
for(const name of ['pointerup','pointercancel','lostpointercapture']) table.addEventListener(name,()=>{drag=null;});
table.addEventListener('keydown', event => {
  const directions = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
  if(!directions[event.key] || form.closest('[data-sync-readonly]')) return;
  event.preventDefault();
  const [x,y] = directions[event.key]; const step = event.shiftKey ? 5 : 1;
  move(number('layout_x')+x*step,number('layout_y')+y*step);
});
form.addEventListener('input',changed);
form.addEventListener('change',changed);
form.addEventListener('submit',()=>{dirty=false;});
window.addEventListener('beforeunload', event => {if(dirty){event.preventDefault();event.returnValue='';}});
draw();
