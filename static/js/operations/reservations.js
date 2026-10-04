export function remainingLabel(deadline, now = Date.now()) {
  const seconds = Math.max(0, Math.ceil((Date.parse(deadline) - now) / 1000));
  if (!Number.isFinite(seconds) || seconds === 0) return 'Plazo vencido';
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}
if (typeof document !== 'undefined') {
  const refresh = () => document.querySelectorAll('[data-deadline]').forEach(node => {
    node.textContent = remainingLabel(node.dataset.deadline);
  });
  refresh();
  setInterval(refresh, 1000);
}

// Availability is advisory. The transactional service rechecks on confirmation.
const setup=typeof document==='undefined'?null:document.querySelector('[data-reservation-setup]');
if(setup){
 const field=name=>setup.querySelector(`[name="${name}"]`), status=document.getElementById('reservation-availability');
 let controller;
 const availability=async()=>{
  controller?.abort();controller=new AbortController();
  const params=new URLSearchParams();
  for(const name of ['date','time','duration','party_size']){if(!field(name).value)return;params.set(name,field(name).value);}
  status.textContent='Buscando mesas disponibles…';
  const table=field('table'), selected=table.value;
  try{
   const response=await fetch(setup.dataset.availabilityUrl+'?'+params,{signal:controller.signal});const data=await response.json();
   if(!response.ok)throw new Error(data.error||'No se pudo consultar disponibilidad.');
   table.replaceChildren(new Option('Selecciona una mesa disponible',''));
   for(const row of data.tables)table.add(new Option(row.label,row.id));
   if(data.tables.some(row=>String(row.id)===selected))table.value=selected;
   status.textContent=data.tables.length?`${data.tables.length} mesas disponibles. Selecciona una; verificaremos otra vez al guardar.`:'No hay mesas disponibles para ese horario y grupo. Cambia los datos.';
  }catch(error){if(error.name!=='AbortError')status.textContent=error.message;}
 };
 let availabilityTimer;
 for(const name of ['date','time','duration','party_size']){
  field(name).addEventListener('change',availability);
  field(name).addEventListener('input',()=>{clearTimeout(availabilityTimer);availabilityTimer=setTimeout(availability,200);});
 }
 const payment=()=>{
  const required=field('payment_required').checked, percent=field('payment_type').value==='PERCENTAGE';
  for(const name of ['payment_type','payment_value','payment_application','payment_base_amount']){
   const box=field(name).closest('[data-reservation-field]');
   if(box)box.hidden=!required||(name==='payment_base_amount'&&!percent);
   field(name).disabled=!required;
  }
 };
 field('payment_required').addEventListener('change',payment);field('payment_type').addEventListener('change',payment);payment();availability();
}
