# Logo de la invitación temporal

`big-party-logo.png` conserva sin modificaciones el logo de la invitación de referencia proporcionada por el usuario:
https://xn--invitacincarlosygraciela-nmc.my.canva.site/invitacion

Recurso original: `_assets/media/f60a80273c5ed118216c7c90bdde1a15.png` (800 × 800, PNG transparente).

La página `/ignaguracion` usa el jueves 22 de octubre a las 14:00 mostrado en la referencia. El año 2026 se infirió del calendario actual y coincide con el jueves; puede ajustarse mediante `PUBLIC_INVITATION_STARTS_AT` (ISO con zona horaria).

Para retirar la página, definir `PUBLIC_INVITATION_ENABLED=False` y reiniciar Django. No se incluye en la navegación ni en el sitemap y solicita no indexación. No crea eventos, reservas ni ventas.

El botón «Cómo llegar» usa las coordenadas oficiales de BusinessSettings. Antes de compartir fuera de la red local, se requiere alojamiento público y configurar `PUBLIC_BASE_URL` para los metadatos y la vista previa del enlace.
