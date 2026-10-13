// Sólo presentación. El servidor vuelve a validar credenciales, rol y permisos.
document.querySelectorAll('[data-auto-open]').forEach(dialog => dialog.showModal());
const userForm = document.querySelector('[data-user-form]');
if (userForm) {
  const role = userForm.querySelector('[name="role"]');
  const update = () => {
    const manager = ['GERENTE', 'PROPIETARIO'].includes(role.value);
    const area = userForm.querySelector('[data-field="work_area"]');
    if (area) {
      area.hidden = role.value !== 'MESERO';
      area.querySelector('select').disabled = area.hidden;
    }
    for (const key of ['pin', 'password']) {
      const field = userForm.querySelector(`[data-field="${key}"]`);
      if (!field) continue;
      field.hidden = key === 'pin' ? manager : !manager;
      field.querySelector('.flow-optional')?.remove();
      const input=field.querySelector('input'); if(input) input.required=!field.hidden;
      field.querySelector('input').disabled = field.hidden;
    }
    const confirmation = userForm.querySelector('[data-field="confirm"] label');
    if (confirmation) confirmation.textContent = manager ? 'Confirmar contraseña' : 'Confirmar PIN';
  };
  role.addEventListener('change', update);
  update();
}
