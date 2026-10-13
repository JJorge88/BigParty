const form = document.querySelector('[data-report-period]');
if (form) {
  const period = form.querySelector('[name="period"]');
  const field = name => form.querySelector(`[name="${name}"]`)?.closest('div');
  const update = () => {
    const range = period.value === 'range';
    const dated = period.value !== 'current';
    for (const name of ['start', 'end']) {
      const box = field(name);
      if (!box) continue;
      box.hidden = name === 'start' ? !dated : !range;
      box.querySelector('input').disabled = box.hidden;
    }
  };
  period.addEventListener('change', update);
  update();
}
