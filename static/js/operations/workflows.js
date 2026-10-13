// Ayudas de presentación. El servidor sigue validando permisos y datos.
const forms = document.querySelectorAll('form[data-flow-form]');
for (const form of forms) {
  let submitting = false;
  const openParents = element => {for (const detail of form.querySelectorAll('details')) if(detail.contains(element)) detail.open = true;};
  form.addEventListener('invalid', event => openParents(event.target), true);
  form.querySelectorAll('.errorlist').forEach(errors => {if(errors.textContent.trim()) openParents(errors);});
  form.querySelectorAll('[data-form-errors] a').forEach(link => link.addEventListener('click',()=>{
    const field = document.getElementById(link.hash.slice(1)); if(field){openParents(field);field.focus();}
  }));
  form.addEventListener('submit', event => {
    if(submitting){event.preventDefault();return;}
    if(!form.checkValidity()) return;
    submitting=true; form.setAttribute('aria-busy','true');
    queueMicrotask(()=>{if(event.defaultPrevented){submitting=false;form.removeAttribute('aria-busy');}});
    // Keep the submitter enabled: its name/value selects the server action.
  });
  window.addEventListener('pageshow',()=>{submitting=false;form.removeAttribute('aria-busy');});
}
document.querySelector('[data-form-errors]')?.focus();
// Menú lateral fijo en computadora y desplegable en pantallas pequeñas.
const sidebar = document.querySelector('.manager-sidebar-panel');
if (sidebar) {
  const smallScreen = window.matchMedia('(max-width: 900px)');
  const adaptMenu = () => { sidebar.open = !smallScreen.matches; };
  adaptMenu();
  smallScreen.addEventListener('change', adaptMenu);
  sidebar.addEventListener('keydown', event => {
    if (event.key === 'Escape' && smallScreen.matches && sidebar.open) {
      sidebar.open = false;
      sidebar.querySelector('summary').focus();
    }
  });
}

const productSetup=document.querySelector('[data-product-setup]');
if(productSetup){
 const adaptStock=()=>{
  const tracking=productSetup.querySelector('#id_track_inventory');
  const saleType=productSetup.querySelector('#id_sale_type');
  const tracked=tracking?tracking.checked:saleType?.value==='UNIT';
  for(const name of ['initial_stock','minimum_stock','inventory_unit','purchase_size','purchase_label']){const box=productSetup.querySelector(`[data-field="${name}"]`);if(box)box.hidden=!tracked;}
 };
 for(const name of ['track_inventory','uses_recipe','is_combo']) productSetup.querySelector(`[name="${name}"]`)?.addEventListener('change',event=>{
  if(event.target.name==='uses_recipe'&&event.target.checked){productSetup.querySelector('#id_track_inventory').checked=false;productSetup.querySelector('#id_is_combo').checked=false;}
  if(event.target.name==='is_combo'&&event.target.checked){productSetup.querySelector('#id_track_inventory').checked=false;productSetup.querySelector('#id_uses_recipe').checked=false;}
  adaptStock();
 });
 adaptStock();
 productSetup.querySelector('#id_sale_type')?.addEventListener('change',adaptStock);
}

// A readable summary before saving products or manual reservations.
for(const form of document.querySelectorAll('[data-reservation-setup]')){
 let approved=false, submitter;
 const dialog=document.createElement('dialog');dialog.className='dialog';
 const title=document.createElement('h2');title.textContent='Revisa antes de guardar';
 const summary=document.createElement('dl');summary.className='setup-review';
 const actions=document.createElement('div');actions.className='admin-form-footer';
 const back=document.createElement('button');back.type='button';back.className='admin-button';back.textContent='Corregir datos';
 const save=document.createElement('button');save.type='button';save.className='admin-button admin-button--primary';save.textContent='Confirmar y guardar';
 actions.append(back,save);dialog.append(title,summary,actions);form.append(dialog);
 back.addEventListener('click',()=>dialog.close());
 save.addEventListener('click',()=>{approved=true;dialog.close();form.requestSubmit(submitter);});
 form.addEventListener('submit',event=>{
  if(approved){approved=false;return;}
  event.preventDefault();submitter=event.submitter;summary.replaceChildren();
  const names=form.matches('[data-product-setup]')?['name','category','base_price','preparation_route','track_inventory','initial_stock','uses_recipe','inventory_unit','purchase_size','purchase_label','visible_in_pos']:['date','time','duration','party_size','table','customer_name','customer_phone','payment_required','payment_type','payment_value','payment_application'];
  for(const name of names){
   const field=form.querySelector(`[name="${name}"]`);if(!field)continue;
   if(name.startsWith('payment_')&&name!=='payment_required'&&!form.querySelector('[name="payment_required"]').checked)continue;
   const dt=document.createElement('dt');dt.textContent=field.labels?.[0]?.textContent||name;
   const dd=document.createElement('dd');dd.textContent=field.type==='checkbox'?(field.checked?'Sí':'No'):field.tagName==='SELECT'?field.selectedOptions[0]?.textContent:field.value||'—';
   summary.append(dt,dd);
  }
  const price=form.querySelector('[name="base_price"]');save.textContent=price&&Number(price.value)===0?'Guardar con precio Q0.00':'Confirmar y guardar';
  dialog.showModal();
 });
}
