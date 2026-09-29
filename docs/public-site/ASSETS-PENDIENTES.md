# Fotografías pendientes · BIG PARTY

La fotografía conceptual actual se muestra únicamente en el hero de Home.
Sport Bar, Discoteca, Premium, reservas y eventos sin imagen tienen composiciones
editoriales abstractas de CSS. No representan fotografías reales del local.
No se han copiado materiales de la referencia conceptual.

| Archivo recomendado | Relación / orientación | Contenido y uso | Configuración |
| --- | --- | --- | --- |
| `home-hero.webp` | 16:9 o 3:2 · horizontal | Ambiente general con gente y luz del local. Dejar espacio oscuro a la izquierda para el titular; sujeto principal visible en recorte móvil central/derecho. | `PUBLIC_HERO_IMAGE` |
| `sport-bar.webp` | 4:5 · vertical | Encuentro de amigos, barra o pantallas reales del Sport Bar. Bloque 01 de experiencias. | `PUBLIC_SPORT_BAR_IMAGE` |
| `discoteca.webp` | 4:5 · vertical | Pista, música y energía del espacio real. Bloque 02, de mayor tamaño. | `PUBLIC_DISCOTECA_IMAGE` |
| `premium.webp` | 4:5 · vertical | Mesas y ambiente real del área Premium. Bloque 03. | `PUBLIC_PREMIUM_IMAGE` |
| `reservation.webp` | 4:5 con recorte 5:4 · vertical | Mesa preparada o encuentro de grupo. Inicio de reservas y sección de reserva en Home. | `PUBLIC_RESERVATION_IMAGE` |
| `event-fallback.webp` | 4:3 con recorte panorámico · horizontal | Ambiente independiente para eventos aún sin cartel. Sin texto de una fecha concreta. | `PUBLIC_EVENT_FALLBACK_IMAGE` |
| `evento-[slug].webp` | 4:3 · horizontal | Foto o cartel propio de cada evento, con contenido principal protegido frente a recortes. Listado, destacado y detalle. | Imagen del evento en Gerencia, campo existente `Event.image` |

Guardar assets optimizados en `static/images/public/`; las variables reciben rutas
relativas a `static`, por ejemplo `images/public/sport-bar.webp`. Las variables de
experiencias, reserva y fallback son opcionales: vacías mantienen la composición
editorial, nunca reutilizan automáticamente el hero. Los archivos definitivos no
se han creado ni se deben activar las rutas de ejemplo antes de subirlos.

Recomendación de entrega: originales de al menos 2000 px por lado largo, versión
WebP optimizada y autorización para su uso público. Evitar texto incrustado cerca
de los bordes. Verificar recortes en móvil antes de sustituir cada asset.

Open Graph conserva la imagen propia del evento cuando existe y el respaldo de
marca ya implementado para enlaces sin imagen. El respaldo de metadatos no se
repite como fotografía dentro de las páginas.

BusinessSettings no incluye dirección, contacto ni Instagram. El footer no inventa
esos datos ni añade campos nuevos en esta fase.
