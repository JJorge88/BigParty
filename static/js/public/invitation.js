const countdown = document.querySelector('[data-countdown]');
if (countdown) {
  const eventTime = Date.parse(document.body.dataset.invitationDate);
  const serverTime = Date.parse(document.body.dataset.serverNow);
  const started = performance.now();
  const update = () => {
    const elapsed = performance.now() - started;
    const seconds = Math.max(0, Math.ceil((eventTime - serverTime - elapsed) / 1000));
    countdown.hidden = seconds <= 0;
    const values = {
      days: Math.floor(seconds / 86400),
      hours: Math.floor(seconds % 86400 / 3600),
      minutes: Math.floor(seconds % 3600 / 60),
      seconds: seconds % 60,
    };
    for (const [key, value] of Object.entries(values)) {
      const node = countdown.querySelector(`[data-${key}]`);
      if (node) node.textContent = String(value).padStart(2, '0');
    }
  };
  update();
  window.setInterval(update, 1000);
}

const share = document.querySelector('[data-share]');
const status = document.querySelector('.share-status');
if (share) share.hidden = false;
share?.addEventListener('click',async()=>{
  const url = new URL('/inauguracion', window.location.origin).href;
  const data = {title:'Inauguración · BIG PARTY',text:'Estás invitado a nuestra inauguración. Consulta la fecha, la hora y cómo llegar.',url};
  try {
    if (navigator.share) {await navigator.share(data);return;}
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(url);status.textContent='Enlace copiado. Ya puedes enviarlo.';return;
    }
  } catch(error) {if(error.name==='AbortError')return;}
  document.querySelector('.share-fallback').hidden=false;
  const input=document.querySelector('#invitation-link');input.value=url;input.focus();input.select();
  status.textContent='Copia este enlace para compartir la invitación.';
});
