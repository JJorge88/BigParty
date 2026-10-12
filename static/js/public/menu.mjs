/** Small public menu controller: escape, focus containment and desktop cleanup. */
export function initMenu({button, nav, body, main, footer, document, viewport}) {
  if (!button || !nav) return;
  const links = () => [...nav.querySelectorAll('a')];
  const isOpen = () => button.getAttribute('aria-expanded') === 'true';
  function close(restore = false) {
    nav.classList.remove('is-open'); body.classList.remove('menu-open');
    button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-label', 'Abrir menú');
    if(main) main.inert = false;
    if(footer) footer.inert = false;
    if(restore) button.focus();
  }
  button.addEventListener('click', () => {
    if(isOpen()) return close(true);
    nav.classList.add('is-open'); body.classList.add('menu-open');
    button.setAttribute('aria-expanded', 'true'); button.setAttribute('aria-label', 'Cerrar menú');
    if(main) main.inert = true;
    if(footer) footer.inert = true;
    links()[0]?.focus();
  });
  document.addEventListener('keydown', event => {
    if(!isOpen()) return;
    if(event.key === 'Escape') { event.preventDefault(); close(true); }
    if(event.key === 'Tab') {
      const focusables = [button, ...links()];
      const first = focusables[0], last = focusables.at(-1);
      if(event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if(!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  nav.addEventListener('click', event => { if(event.target.closest('a')) close(); });
  const viewportChange = () => { if(!viewport.matches) close(); };
  if(viewport.addEventListener) viewport.addEventListener('change', viewportChange);
  else viewport.addListener?.(viewportChange);
  return {close};
}
