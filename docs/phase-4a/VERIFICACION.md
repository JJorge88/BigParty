# FASE 4A — Verificación

Fecha: 29 de septiembre de 2026. Base inicial: `2cf4fb0`.

## Resultado automatizado

- Suite completa final: **940 pruebas Django, OK**, 79,420 s.
- JavaScript: **10 pruebas, OK**.
- `manage.py check`: sin problemas.
- `makemigrations --check --dry-run`: sin cambios; cero migraciones nuevas.
- `git diff --check`: sin errores de espacios.
- 13 pruebas Django nuevas para la experiencia pública; las pruebas anteriores
  de dominio, aislamiento, imágenes, PDF, permisos y concurrencia siguen pasando.
- Comprobaciones JS de límites, cantidades enteras, total mixto en centavos y
  contador basado en hora del servidor. Menú, selección por área, pasos y total
  también se recorrieron en navegador.

La suite incluye pruebas simultáneas reales con PostgreSQL: última mesa, último
cupo, aforo global, doble confirmación, emisión idempotente y doble lectura de QR.
Los mensajes PermissionDenied/CSRF de las pruebas negativas son esperados. Permanece
una advertencia preexistente de fecha sin zona en una prueba de formulario de evento.

## Recorridos verificados

Entorno aislado: base `bigparty_visual_4a_20260929`, servidor local puerto 8004,
medios y comprobantes temporales. Banco y clientes de demostración. Los plazos
se fijaron en 60 minutos para permitir capturas; no se modificaron los valores
de la base habitual. La base temporal, los comprobantes y el servidor se eliminaron
al finalizar la verificación. Los QR de estas capturas quedan sin respaldo activo.

1. Portada desktop y mobile: hero, CTAs, siguiente evento publicado, Sport Bar,
   Discoteca y Premium. El listado muestra únicamente estados públicos vigentes.
2. Fecha 04/10/2026, 20:00, cuatro personas; selección de Mesa 04. Se mostró el
   anticipo previsto Q200 antes del envío. POST público produjo un único hold
   PENDING_REVIEW y portal «Solicitud recibida».
3. Dos pestañas cargaron la misma selección antes del primer envío. La segunda
   solicitud recibió HTTP 409 y «Esta mesa acaba de ser reservada o ya no está
   disponible». Una prueba adicional usa dos clientes HTTP independientes.
4. Aprobación desde la ruta de Gerencia con sesión, CSRF y confirmación firmada:
   AWAITING_PAYMENT, Q200 y cuenta bancaria de prueba visibles en el portal.
5. Comprobante PNG enviado al portal por HTTP con CSRF → PAYMENT_REVIEW;
   verificación firmada de Gerencia → CONFIRMED. Portal actualizado visualmente.
   La reserva normal no emite QR.
6. Evento Champagne Nights: botones +/− seleccionaron 2 General × Q100 y
   1 VIP × Q150. Total visible y backend Q350. Nombre/teléfono → portal con hold.
7. Comprobante validado por HTTP; confirmación firmada de Gerencia produjo tres
   tickets. Portal mostró 2 General y 1 VIP, cada uno con QR y botón PDF.
8. Mesa de evento VIP 2: seis personas × Q100 = Q600. La selección cambió el
   total a Q600; después de confirmar el pago se emitieron seis tickets.
9. Descargas PDF verificadas por sus rutas HTTP: respuesta PDF, cabecera `%PDF`,
   3/6 páginas en archivos completos y 1 página individual. El navegador integrado
   no entregó confirmación del evento de descarga; la validación del archivo se
   completó por HTTP y lectura del PDF, sin alterar el motor existente.
10. Hold adicional de 12 segundos: se observó 00:10, luego recarga automática y
    «El plazo terminó» desde el backend, sin mantener formulario ni contador.

Las transiciones públicas se recorrieron en navegador. Los envíos de comprobante
y las confirmaciones de Gerencia se ejecutaron mediante sus rutas HTTP existentes
con CSRF y confirmación firmada; no se sustituyó el estado final directamente en DB.

## Pantallas y accesibilidad

- 390×844 y 430×932: portada, calendario, detalle, reservas, mapa y portal sin
  desbordamiento horizontal de página; el plano configurado usa scroll interno.
- 768×1024: detalle de evento y navegación de tablet.
- 1280×720 / 1280×900: escritorio, selección, resumen y tarjetas QR.
- Menú móvil abre/cierra, Escape devuelve el foco; labels de formularios y radio
  buttons; selección por área, mesa no disponible no seleccionable; resumen con
  anuncio accesible y total persistente. Sin errores JS observados en consola.
- Se corrigieron durante QA el selector del total y la proporción de imágenes
  con dimensiones HTML, y se volvieron a comprobar las pantallas afectadas.

## Seguridad, SEO y rendimiento

Canonical y Open Graph utilizan PUBLIC_BASE_URL; la imagen de evento se obtiene
del modelo. Sitemap solo de rutas públicas. Portales/QR/PDF no-store y noindex,
CSRF vigente, códigos públicos no sustituyen tokens y un ticket no abre la compra.
Comprobantes siguen privados, con validación JPEG/PNG/WebP y límite de 5 MB.

Hero WebP: 112 888 bytes. Inter variable local: 352 240 bytes, licencia OFL incluida.
CSS público aproximadamente 22 KiB y JavaScript total aproximadamente 5,4 KiB sin
comprimir. Sin librerías de frontend ni llamadas a CDNs; calendario paginado.
No se realizaron pruebas de carga ni despliegue de producción.

## Capturas A–L

| Captura | Evidencia |
| --- | --- |
| [A · Home desktop](captures/A-home-desktop.jpg) | Hero y CTAs |
| [B · Home mobile](captures/B-home-mobile.jpg) | 390×844 |
| [C · Eventos](captures/C-eventos.jpg) | Calendario público |
| [D · Evento detalle](captures/D-evento-detalle.jpg) | Imagen y fecha |
| [E · Compra entradas](captures/E-compra-entradas.jpg) | 2 General + 1 VIP |
| [F · Pago evento](captures/F-pago-evento.jpg) | Banco, total y comprobante |
| [G · Portal con tickets](captures/G-portal-tickets.jpg) | QR y PDF por entrada |
| [H · Fecha/hora](captures/H-reserva-fecha-hora.jpg) | Inicio de reserva |
| [I · Mapa](captures/I-mapa-mesas.jpg) | Mesa 04 seleccionada |
| [J · Solicitada](captures/J-reserva-solicitada.jpg) | Hold pendiente de revisión |
| [K · Esperando pago](captures/K-reserva-esperando-pago.jpg) | Anticipo Q200 |
| [L · Confirmada](captures/L-reserva-confirmada.jpg) | Reserva normal confirmada |

## Decisiones y siguiente fase

Se reutilizaron todos los servicios transaccionales existentes. La selección
firmada no constituye un hold. No se creó un CMS ni un modelo de contacto; no se
inventaron dirección, teléfono o redes. Las imágenes son conceptuales provisionales
reemplazables mediante settings; ver [procedencia y prompt](IMAGEN.md).

Las correcciones menores 3E no alteran cálculos ni permisos. Cero migraciones.
No se inicia 4B, Local Node, offline sync, Nginx, Gunicorn, despliegue, dominio real,
analytics, pixel, PWA ni FEL. La siguiente fase queda pendiente de revisión y
alcance del usuario. Fotografías reales y datos públicos verificados siguen siendo
contenido por aportar antes de una publicación real.
