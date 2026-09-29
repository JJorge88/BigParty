# Fase 4A.1 · verificación del refinamiento público

29 de septiembre de 2026. Base: `2e430d6`.

## Resultado

- Suite completa: **945 pruebas Django, OK** (70,599 s en la ejecución final).
- JavaScript: **13 pruebas, OK**. Incluye foco y cierre del menú, moneda y cambio
  de preferencia de movimiento reducido.
- Cinco pruebas Django nuevas: fecha/hora local, precisión monetaria, validación
  geométrica, render de plano/cuadrícula/área vacía y componentes con assets separados.
- `manage.py check`, `makemigrations --check --dry-run` y `git diff --check`: correctos.
- Cero modelos o migraciones nuevos. Ningún cambio en servicios transaccionales,
  importes, holds, pagos, emisión de tickets o reglas de disponibilidad.
- Se conservan canonical, OG, sitemap, robots y noindex/no-store privados; las
  pruebas existentes de SEO, permisos, aislamiento y concurrencia siguen pasando.
- CSS exclusivamente público. Gerencia, POS y Caja conservan sus estilos.

Los PermissionDenied/CSRF de pruebas negativas son esperados. Continúa la
advertencia preexistente de fecha sin zona horaria en una prueba de eventos.

## Recorridos y decisiones comprobadas

Home mantiene la fotografía conceptual solo en el hero visible. El evento destacado
ocupa el ancho del contenido; Sport Bar, Discoteca y Premium tienen composiciones
abstractas independientes y disposición asimétrica. Reserva y fallback de evento
poseen sus propios espacios para fotografías. Calendario breve solo si hay más
fechas publicadas. No se añadieron datos comerciales inventados al footer.

Listado comprobado con uno, dos y tres eventos. Detalle con selector sin cajas,
2 General + 1 VIP = Q350, avance al formulario y foco en el nombre. Barra inferior
con total y acción, sin cambiar los cálculos ni los campos enviados.

Mapa real con círculos y rectángulos: coordenadas y dimensiones preservadas,
selección champagne, mesas no disponibles sin radio. La escala mínima se calcula
para etiquetas legibles; no se ensancha cada mesa por separado. Cuadrícula cuando
faltan posiciones válidas y mensaje cuando un área activa no tiene mesas web.
Selección de Mesa 04, cambio de áreas y resumen de selección comprobados.

Portales solicitada, esperando pago y confirmada revisados. Código de reserva
secundario al titular. Banco/titular/cuenta proceden de BankTransferSettings;
se verificaron tanto datos habilitados como el estado sin configuración. Se
mantienen monto, referencia, comprobante y CTA. Entradas General/VIP con QR grande
negro sobre blanco, número y PDF por entrada. El generador de QR/PDF no se modificó.

Menú móvil con Inicio, Eventos, Reservas y Reservar mesa: apertura, foco inicial,
Escape y restauración del foco comprobados en navegador. Prueba JS cubre Tab,
Shift+Tab, cierre al pasar a escritorio y liberación del contenido. Revelados
opcionales de 12 px, hover leve y soporte de movimiento reducido en CSS y JS;
la prueba simula preferencia inicial reducida y cambio durante la sesión. No se
cambió la preferencia de accesibilidad del sistema del usuario.

Fechas públicas en español con año y hora 24 h; timezone local aplicado antes de
formatear. Q100 en marketing, Q100.50 si existen centavos y Q100.00 en pagos. Los
controles nativos de fecha/hora mantienen la representación del navegador/SO.

## Entorno de revisión

Base independiente `bigparty_visual_4a1_20260929`, puerto local 8004 y medios
exclusivos en `/tmp`. Clientes, banco, eventos y fotografías de validación de
fixture ficticios. La imagen del evento de prueba se dejó vacía después de su
publicación para recorrer el fallback. No se modificaron datos habituales.
Los plazos temporales fueron 120 minutos para permitir la revisión.

Servidor, base, medios y comprobantes de este entorno retirados al terminar.
Los QR de las capturas ya no tienen respaldo activo. No hay despliegue ni fase 4B.

## Matriz responsive

Cinco rutas en seis viewports: **30 verificaciones**, sin desbordamiento horizontal
de documento. Se revisaron imágenes de cada combinación y medidas del DOM en
[responsive.json](captures/responsive.json). El plano mantiene scroll interno
solo cuando la geometría exige una escala mayor para leer las etiquetas.

La captura nativa del navegador integrado está limitada por el panel disponible:
los renders 768×1024 y 1920×1080 tienen archivos de 768×989 y 1847×1080,
respectivamente. La emulación y las medidas DOM sí corresponden al tamaño
solicitado; esas imágenes tienen un pequeño recorte de borde, sin reescalado ni
relleno artificial. Los otros cuatro tamaños se capturaron completos.

| Pantalla | 390×844 | 430×932 | 768×1024 | 1280×800 | 1440×900 | 1920×1080 |
| --- | --- | --- | --- | --- | --- | --- |
| Home | [Ver](captures/qa-home-390.jpg) | [Ver](captures/qa-home-430.jpg) | [Ver](captures/qa-home-768.jpg) | [Ver](captures/qa-home-1280.jpg) | [Ver](captures/qa-home-1440.jpg) | [Ver](captures/qa-home-1920.jpg) |
| Entradas del evento | [Ver](captures/qa-event-390.jpg) | [Ver](captures/qa-event-430.jpg) | [Ver](captures/qa-event-768.jpg) | [Ver](captures/qa-event-1280.jpg) | [Ver](captures/qa-event-1440.jpg) | [Ver](captures/qa-event-1920.jpg) |
| Mapa de reservas | [Ver](captures/qa-map-390.jpg) | [Ver](captures/qa-map-430.jpg) | [Ver](captures/qa-map-768.jpg) | [Ver](captures/qa-map-1280.jpg) | [Ver](captures/qa-map-1440.jpg) | [Ver](captures/qa-map-1920.jpg) |
| Transferencia | [Ver](captures/qa-transfer-390.jpg) | [Ver](captures/qa-transfer-430.jpg) | [Ver](captures/qa-transfer-768.jpg) | [Ver](captures/qa-transfer-1280.jpg) | [Ver](captures/qa-transfer-1440.jpg) | [Ver](captures/qa-transfer-1920.jpg) |
| Portal de tickets | [Ver](captures/qa-tickets-390.jpg) | [Ver](captures/qa-tickets-430.jpg) | [Ver](captures/qa-tickets-768.jpg) | [Ver](captures/qa-tickets-1280.jpg) | [Ver](captures/qa-tickets-1440.jpg) | [Ver](captures/qa-tickets-1920.jpg) |

## Capturas adicionales

- [01-home-desktop](captures/01-home-desktop.jpg)
- [02-proximo-evento](captures/02-proximo-evento.jpg)
- [03-experiencias](captures/03-experiencias.jpg)
- [04-home-mobile](captures/04-home-mobile.jpg)
- [05-mapa-mobile](captures/05-mapa-mobile.jpg)
- [06-mapa-fallback](captures/06-mapa-fallback.jpg)
- [07-reserva-inicio](captures/07-reserva-inicio.jpg)
- [08-reserva-solicitada](captures/08-reserva-solicitada.jpg)
- [09-reserva-transferencia](captures/09-reserva-transferencia.jpg)
- [10-evento-detalle](captures/10-evento-detalle.jpg)
- [11-reserva-confirmada](captures/11-reserva-confirmada.jpg)
- [12-eventos-varios](captures/12-eventos-varios.jpg)
- [13-evento-unico](captures/13-evento-unico.jpg)
- [14-eventos-dos](captures/14-eventos-dos.jpg)
- [15-menu-mobile](captures/15-menu-mobile.jpg)

Las fotografías definitivas y cómo sustituir cada composición están en
[ASSETS-PENDIENTES.md](ASSETS-PENDIENTES.md).
