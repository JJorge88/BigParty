/** Marketing reveals are optional; reduced motion always leaves content visible. */
export function initReveals({elements, preference, Observer}) {
  if (!Observer || preference.matches) return;
  const observer = new Observer(entries => entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('is-visible');
      observer.unobserve(entry.target);
    }
  }), {threshold: 0.08});
  elements.forEach(node => {node.classList.add('reveal-ready'); observer.observe(node);});
  const preferenceChange = () => {
    if (preference.matches) {
      observer.disconnect();
      elements.forEach(node => node.classList.add('is-visible'));
    }
  };
  if (preference.addEventListener) preference.addEventListener('change', preferenceChange);
  else preference.addListener?.(preferenceChange);
}
