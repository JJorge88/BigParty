# Imágenes editoriales provisionales

Los cinco archivos `*-concept.webp` se generaron con IA el 30 de septiembre de 2026,
a petición del usuario, para ocupar los espacios sin fotografías de la web pública.
Son ambientes imaginados: no documentan instalaciones ni eventos reales de BIG PARTY.

| Archivo | Uso |
| --- | --- |
| sport-bar-concept.webp | Tarjeta Sport Bar |
| discoteca-concept.webp | Tarjeta Discoteca |
| premium-concept.webp | Tarjeta Premium |
| reservation-concept.webp | Sección de reservas |
| event-fallback-concept.webp | Eventos sin imagen propia |

Se conserva la imagen principal existente. Las nuevas imágenes están codificadas en
WebP, sin cambiar su composición, para reducir la descarga. Los textos alternativos
las identifican como ambientes ilustrativos.

Para sustituirlas por fotos reales, guarda las fotos en `static/images/public/` y
configura `PUBLIC_SPORT_BAR_IMAGE`, `PUBLIC_DISCOTECA_IMAGE`, `PUBLIC_PREMIUM_IMAGE`,
`PUBLIC_RESERVATION_IMAGE` y `PUBLIC_EVENT_FALLBACK_IMAGE` con su ruta relativa a
`static`. Reinicia el servidor tras cambiar estas variables. Las imágenes propias
de cada evento siguen teniendo prioridad sobre la portada genérica.
