# FASE 4A.2 — Información pública del establecimiento

La Home conserva su composición, fotografía y tipografía. Se agregan «Planifica tu noche», «Encuéntranos» y 12 preguntas frecuentes en acordeones nativos, accesibles con teclado y sin depender de JavaScript. El footer enlaza a ubicación y FAQ; el header conserva sus entradas actuales.

## Configuración y publicación

Gerencia → Configuración → Negocio ofrece cuatro páginas: Información, Ubicación, Horarios e Ingreso. Requieren los permisos existentes `core.view_configuration` y `core.change_business_configuration`.

Se amplía el singleton `BusinessSettings`, sin duplicarlo:

- `latitude`: **14.559363833208103**; `longitude`: **-89.35266491165514**.
- `address_text` y `public_phone`: vacíos por defecto. Se omiten tanto de la información pública como del JSON-LD mientras no estén configurados.
- `minimum_entry_age`: 18; identificación física válida, vestimenta casual elegante y seguridad con los textos solicitados.
- Descripción adicional de vestimenta y política de ingreso opcionales, inicialmente vacías.

El contacto usa formato internacional con `+` y código de país. Al guardar un número aparecen WhatsApp (`wa.me`) y Contacto (`tel:`); al vaciarlo desaparece todo el bloque. No se agregó información de parqueo, promociones, horarios inventados ni estado «Abierto ahora».

`BusinessOpeningHours` contiene `weekday`, `is_open`, `opens_at`, `closes_at` y `sort_order`. Hay como máximo una fila por día, con nombres en español y orden por `sort_order`, luego `weekday`. La migración no crea horarios. Gerencia muestra inicialmente siete días cerrados sin escribir en la base al consultar el formulario. Guardar publica únicamente los días abiertos. Apertura y cierre deben existir y ser diferentes; si el cierre es anterior a la apertura, corresponde al día siguiente. Al cerrar un día desde Gerencia se limpian sus horas y se oculta públicamente.

Latitud y longitud tienen validación de formulario/modelo y restricciones de base de datos. También se protegen el rango del día, la unicidad de cada día, la edad y los intervalos abiertos. Los formularios conservan CSRF y los controles de recuperación y autoridad existentes.

## Mapa y dependencias externas

El mapa utiliza el [iframe estándar de OpenStreetMap](https://wiki.openstreetmap.org/wiki/Export#Embeddable_HTML), con marcador y encuadre calculados desde `BusinessSettings`. No requiere claves ni una API paga. Durante la revisión, el embed estándar de Google no terminó de dibujarse; el de OpenStreetMap sí se renderizó con el punto correcto.

«Cómo llegar» abre Google Maps en una pestaña externa con `api=1` y `destination=latitude,longitude`. No se especifica un origen ni se solicita ubicación al visitante. La política del sitio mantiene `geolocation=()`.

El iframe es una dependencia externa: puede transferir al proveedor la IP, datos del navegador y el origen del sitio, y está sujeto a sus propias políticas y disponibilidad. Carga de forma diferida, conserva la atribución de OpenStreetMap y usa `strict-origin-when-cross-origin`. No se agregó analítica ni un gestor de cookies. La CSP permite únicamente `https://www.openstreetmap.org` como iframe en Home; las demás rutas conservan su protección. El enlace a Google sigue disponible si el mapa externo no carga.

El mapa es 4:3 en móvil, seguido de la información y el CTA; en escritorio se integra junto a los datos del negocio.

## Textos, FAQ y SEO

Ingreso, identificación, vestimenta, seguridad y política proceden directamente de la configuración. Edad y horarios de la FAQ comparten esa fuente. Sin horarios publicados, la FAQ remite a la información de cada evento sin anunciar días ficticios.

La explicación de reservas distingue solicitud, aprobación, anticipo y verificación de pago; conserva el seguimiento por enlace privado. La FAQ aclara que llegar con menos personas no invalida automáticamente una reserva normal. No se agregan límites de llegada, penalidades ni porcentajes de devolución.

Eventos explica accesos individuales, QR único y capacidad completa de las mesas, con precio según evento y sin consumo mínimo adicional. Cover describe el ingreso y su cálculo por capacidad sin precios fijos. Reprogramar mantiene las entradas para la nueva fecha; cancelar las invalida y requiere gestión de BIG PARTY, sin prometer devolución automática. Se revisaron los servicios existentes; no se modificó su lógica.

Home publica JSON-LD de tipo [NightClub](https://schema.org/NightClub), con nombre, URL pública configurada y GeoCoordinates. Dirección y teléfono son opcionales. Solo los días abiertos producen [OpeningHoursSpecification](https://schema.org/OpeningHoursSpecification), incluidos cierres después de medianoche. El JSON se serializa escapando caracteres HTML; los textos configurables se muestran escapados.

## Auditoría y migración

Los guardados registran `CONFIGURATION_UPDATED` con actor y valores anteriores/nuevos. Ubicación, teléfono, edad, reglas y horarios aparecen en el visor de auditoría. No se registran credenciales. Los cambios se guardan en una transacción y respetan el bloqueo operativo existente.

Nueva migración: `apps/core/migrations/0003_public_venue_information.py`. Se aplicó a `bigparty_pilot`; no se editaron migraciones anteriores ni se crearon horarios de ejemplo en el piloto.

## Verificación

- 19 pruebas nuevas: modelos, validaciones, orden, cruce de medianoche, configuración opcional, mapa, reglas, FAQ, JSON-LD y escape de HTML; permisos, POST, CSRF, auditoría y manipulación de formularios.
- Suite completa: **1,070 pruebas aprobadas**.
- Después de los últimos ajustes de mapa y formulario: **62 pruebas relacionadas aprobadas**.
- JavaScript público: **6 pruebas aprobadas**.
- `check`, `makemigrations --check --dry-run` y `git diff --check` sin incidencias.
- El entorno tenía dependencias parcialmente descargadas de iCloud. Para verificar se usó una copia temporal de las mismas versiones fijadas; no se cambiaron dependencias del proyecto.

La revisión de navegador se realizó en una base temporal independiente, con credenciales efímeras. Los horarios, la edad y el número utilizados allí son datos de prueba, no información publicada del establecimiento. No se inició Local Node ni se hizo despliegue.

## Capturas

- [Ubicación en escritorio](captures/01-location-desktop.jpg)
- [Planifica tu noche](captures/02-plan-desktop.jpg)
- [Preguntas frecuentes](captures/03-faq-desktop.jpg)
- [Ubicación móvil](captures/04-location-mobile.jpg)
- [Home móvil completa](captures/05-home-mobile.jpg)
- [Secciones de Gerencia](captures/06-management-sections.jpg)
- [Edición de horarios](captures/07-management-hours.jpg)
- [Ejemplo de horario en la base temporal](captures/08-location-hours.jpg)

Commit solicitado: `feat: add public venue information and opening hours`.

### Recorrido de navegador completado

Home en escritorio y 390 px: sin desbordamiento horizontal; contacto y horarios ausentes cuando están vacíos. Publicación de sábado 20:00–04:00, cierre del día y retirada pública comprobados. Cambio de edad a 21 reflejado en el acordeón abierto. Teléfono de prueba publicado como enlace WhatsApp correcto y eliminado después, sin huecos en el diseño. «Cómo llegar» abrió una pestaña de Google Maps con el destino oficial. Cero errores JavaScript de página. El piloto real quedó con edad 18, dirección y teléfono vacíos y cero días publicados.
