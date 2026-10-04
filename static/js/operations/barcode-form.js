const mode = document.getElementById('id_mode');
const code = document.getElementById('id_code');
if (mode && code) {
  const update = () => {
    const existing = mode.value === 'keep';
    code.closest('[data-field]').hidden = !existing;
    code.disabled = !existing;
    code.required = existing;
  };
  mode.addEventListener('change', update);
  update();
}
