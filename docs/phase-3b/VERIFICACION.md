# Verificación Fase 3B — Reservas

Fecha local: 28 de septiembre de 2026. Datos ficticios en una base PostgreSQL aislada
`bigparty_visual_3b_20260928`, servida únicamente en localhost:8004 durante la revisión.
La base, los usuarios, sesiones, comprobantes y configuración temporal se eliminaron
al terminar. No se enviaron mensajes de WhatsApp ni transferencias reales.

## Escenarios solicitados

| Escenario | Verificación | Resultado |
|---|---|---|
| A | Solicitud pública VIP 2, aprobación sin anticipo en navegador, consulta del cliente, elección Carlos Méndez y llegada | `ARRIVED`, una cuenta única y mesa ocupada |
| B | Anticipo Q300, envío de referencia e imagen por el formulario privado, revisión humana y llegada desde Gerencia | Crédito disponible Q300; tras enviar Q800 de consumo queda aplicado Q300 y saldo Q500 |
| C | Ventana de pago vencida, comando de expiración, disponibilidad consultada nuevamente | `EXPIRED`, mesa disponible |
| D | Comprobante enviado, rechazo con motivo desde Gerencia | Reserva/pago `REJECTED`, historial conservado y mesa disponible |
| E | Dos conexiones y dos hilos solicitando la misma mesa/intervalo simultáneamente | Un éxito, un rechazo y un único hold válido |

[Evidencia de dominio](verificacion-dominio.json) registra importes y estados reales,
comprobados con aserciones después de las interacciones. A/B/D se recorrieron en el
navegador; C/E se ejecutaron mediante servicios/comandos reales sobre la base temporal.
También se aprobó con anticipo desde el formulario de Gerencia.

Revisión adicional en tablet: mapa actualizado sin errores JavaScript, estado
“Reservada” para una reserva vigente, apertura ordinaria ausente con indicación de
confirmar llegada desde Gerencia, y cuenta con origen del crédito y saldo Q500.

La prueba real de subida detectó que `no-referrer` impedía validar el origen del
POST. Se corrigió a `same-origin`, manteniendo CSRF, y se volvió a subir/enviar el
comprobante exitosamente. Se añadieron pruebas de POST válido y origen extranjero.
El comprobante visible es una imagen sintética marcada como prueba, sin valor bancario.

## Capturas reales

Todas las imágenes son JPEG de viewport 1280×800, sin montaje. Reflejan momentos
distintos del recorrido; los contadores y estados cambian al completar las acciones.

- [A — Listado](A-listado.jpg)
- [B — Revisión pendiente](B-revisar-reserva.jpg)
- [C — Esperando pago](C-esperando-pago.jpg)
- [D — Revisión del comprobante](D-revisar-pago.jpg)
- [E — Confirmada](E-confirmada.jpg)
- [F — Confirmar llegada y seleccionar mesero](F-confirmar-llegada.jpg)
- [G — Página segura y formulario del cliente](G-cliente-seguro.jpg)
- [H — Cuenta con crédito y saldo](H-cuenta-credito.jpg)

## Comprobaciones automatizadas

- 780 pruebas Django: 719 anteriores + 61 de reservas/integración/concurrencia.
- 7 pruebas JavaScript: 6 anteriores + cuenta regresiva.
- `manage.py check`: sin incidencias.
- `makemigrations --check`: sin cambios pendientes.
- Migración `reservations.0001_initial` aplicada.
- `git diff --check`: sin errores.

Se detiene la implementación antes de Eventos (3C).
