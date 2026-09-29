# Fase 2F — Verificación

Revisión del 28 de septiembre de 2026 (America/Guatemala). Impresión lógica y backend TCP
implementados; compatibilidad física pendiente. No se avanzó a Gerencia.

## Validación automática

- `python manage.py check`: sin incidencias.
- `python manage.py makemigrations --check --dry-run`: sin cambios pendientes.
- `python manage.py test --noinput`: **680 aprobadas**, 69 nuevas sobre las 611 de 2E.
- `node --test apps/operations/tests/*.test.mjs`: **6 aprobadas**.
- `git diff --check`: correcto.
- Migraciones nuevas `orders.0006_alter_tableorder_options_and_more` y
  `printing.0001_initial`, aplicadas a la base temporal y a la base local existente.
- Seed en base local: cuatro impresoras, host vacío, puerto 9100 y papel 80 mm;
  ningún trabajo de prueba insertado en datos reales.

Las pruebas nuevas cubren constraints, códigos/áreas, seed idempotente, tres barras,
cocina compartida, NONE, tickets mixtos, snapshots, adición/cancelación/actualización,
venta rápida, TAKE_AT_BAR, reserva/rechazo/anulación/reembolso, revalidación de stock,
conteo de caja, recibos explícitos/copias, permisos, ámbito de área, tokens y CSRF.

La suite de transporte verifica Unicode, transliteración, codepage/corte opcionales,
control de caracteres ESC, ancho 58/80, archivos sin sobrescritura, host/puerto/timeouts,
fallos de conexión/envío y DNS lento. Las pruebas con `TransactionTestCase` usan
conexiones PostgreSQL concurrentes: reclamación doble, creación de originales,
trabajador vivo frente a recuperación stale, rollback y callbacks fuera de transacción.
El fallo de Cocina no revierte stock ni repite la barra.

## Recorrido debug con datos aislados

Se creó `bigparty_visual_2f_20260928`, independiente de los datos locales, con backend
debug y salida `/private/tmp/bp2f-print-jobs`. Se usaron personas/productos de prueba y
ninguna IP física. Los escenarios de dominio se ejecutaron mediante servicios Django
reales con commits; se inspeccionaron los archivos generados y se verificaron sus rutas.
La configuración, prueba, recibos, alias, reintento y reimpresión se comprobaron además
con navegador real, Django y PostgreSQL, a 1280 × 800.

| Paso solicitado | Resultado / archivo conservado |
| --- | --- |
| Mesa 07: 2 Gallo + 1 Hamburguesa | [Barra 2: solo Gallo](examples/01-new-barra-2.txt) y [Cocina: solo Hamburguesa](examples/02-new-cocina.txt), mismo pedido y hora |
| Adición 1 Corona | [Solo Corona en Barra 2](examples/03-addition-barra-2.txt), sin consumo anterior |
| Cancelar Corona | [CANCELACIÓN](examples/04-cancellation-barra-2.txt), producto y motivo |
| Nueva nota de hamburguesa | [ACTUALIZACIÓN Cocina](examples/05-update-cocina.txt), “Sin salsa” |
| Venta rápida: 2 Gallo + Hamburguesa | [Solo Cocina](examples/06-new-cocina.txt), pedido 000002, Caja Discoteca, alias Juan, sin mesa ni barra; cero trabajos antes del pago/cierre |
| Cargar a mesa, “Se lo lleva” | [Solo Cocina](examples/07-addition-cocina.txt) |
| Cargar a mesa, “Enviar a mesa” | [Barra 2](examples/08-addition-barra-2.txt) y [Cocina](examples/09-addition-cocina.txt) |
| Página de prueba desde configuración | [Texto y acentos de prueba](examples/10-prueba-barra-2.txt), trabajo #10 |
| Recibo solicitado en Venta completada | [Recibo 80 mm](examples/11-recibo-barra-2.txt), Q100.00, Efectivo Q100.00, saldo Q0.00; trabajo #11 |
| Otra solicitud explícita de recibo | [Copia auditada](examples/12-copia-recibo-barra-2.txt), #12 vinculado a #11 |
| Reimpresión autorizada de comanda | [Copia Cocina con motivo](examples/15-reimpresion-cocina.txt), #15 vinculado a #14 |
| Papel 58 mm | [Página de prueba 32 columnas](examples/16-prueba-58mm.txt) |

El recibo solo apareció después del POST del botón: ni cerrar la venta ni entrar en la
pantalla de recibo creó trabajos de ese tipo. Otra pulsación explícita generó una copia;
la repetición del mismo formulario/token está cubierta por pruebas automáticas.

Para verificar fallo independiente se creó Mesa 08 con Gallo + Hamburguesa. Un adaptador
debug de prueba falló únicamente para Cocina: #13 Barra 2 = PRINTED, 1 intento; #14 Cocina
= FAILED, 1 intento. En `/caja/impresiones/`, Reintentar cambió #14 a PRINTED, 2 intentos,
sin alterar #13. Después, Reimprimir con motivo creó #15 y conservó ambos originales.
No se usó una IP falsa para simular el fallo.

También se escribió “Alias conservado”, se retiró la hamburguesa y se volvió a agregar:
el campo se ocultó y recuperó su valor. “Cobrar” quedó visible en el catálogo. Después,
se anuló la venta de prueba con motivo; la pantalla confirmó la liberación y regresó a
Ventas rápidas sin dejar el borrador disponible.

## Capturas reales

- [Configuración de las cuatro impresoras](01-impresoras.png).
- [Venta completada con acción secundaria de recibo](02-venta-completada.png).
- [Recibo solicitado: trabajo impreso](03-recibo-solicitado.png).
- [Alias conservado al retirar y volver a agregar comida](04-alias-conservado.png).
- [Cocina fallida, aislada](05-fallo-aislado.png).
- [Reintento: Cocina 2 intentos / Barra 2 1 intento](06-reintento-aislado.png).
- [Lista después de anular la venta de prueba](07-venta-anulada.png).

La base temporal y su servidor se retiraron después de la revisión; los ejemplos y
capturas permanecen en este directorio. No se copiaron usuarios, contraseñas, ventas ni
trabajos de prueba a la base local del proyecto.

## Decisiones y límites

- Un intento automático después del commit; reintento manual acotado por trabajo.
- Constraint por ticket/destino lógico y candado PostgreSQL durante I/O; sin Celery/Redis.
- Trabajo FAILED sin impresora si falta una ruta, para no perder el pedido ni su alerta.
- Copias explícitas con relación al original, motivo y auditoría; no edición/borrado admin.
- Snapshots conservan Unicode y papel original; transliteración afecta solo al transporte.
- ASCII inicial, cutter apagado, sin tabla ESC t asumida ni dependencia de un fabricante.
- Rechazo/liberación/reembolso de venta sin entregar devuelve reserva; continuar revalida.
  El conteo bloquea reservas inconclusas todavía inmovilizadas. No hay expiración automática.
- TCP aceptado no prueba salida física. Un envío parcial o proceso caído requiere revisar
  papel antes de reintentar; stale queda FAILED y nunca se reimprime por sí solo.

Pendiente con impresoras reales: modelos/marca, direcciones y puertos LAN, ancho/fuente,
acentos y tabla ESC/POS, soporte de corte, desconexión/papel agotado y prueba desde el nodo
local de BIG PARTY. No se ha afirmado una prueba física ni compatibilidad universal.
