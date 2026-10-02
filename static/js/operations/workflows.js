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
