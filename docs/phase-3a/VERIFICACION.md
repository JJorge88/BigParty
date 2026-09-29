# Verificación — Fase 3A

Revisión local del 28 de septiembre de 2026. Alcance completado: Gerencia operativa.
No se inició Reservas ni otra función de Fase 3B.

## Pruebas automatizadas

- `python manage.py check`: sin incidencias.
- `python manage.py makemigrations --check --dry-run`: sin cambios pendientes.
- `python manage.py test --noinput`: **719 pruebas aprobadas**, 49,273 segundos en la
  ejecución final (680 anteriores + 39 nuevas de Gerencia).
- `node --test apps/operations/tests/*.test.mjs`: **6 aprobadas**.
- `git diff --check`: sin errores de formato.

Las 39 pruebas de Gerencia cubren rol, propietario, usuario no permitido/inactivo,
contraseña, revocación, cookies independientes de Admin, expiración del servidor,
ausencia/apertura de jornada, confirmación explícita, permisos por acción, gross/net,
ajustes, reembolsos parciales/totales, multimesa, QUICK_SALE, cruces de medianoche,
horas vacías, áreas desactivadas con ventas, métodos, pendientes e impresión fallida.
También cubren cajas abiertas/cerradas, varias sesiones por estación, privacidad,
diferencias e incidencias, bloqueos reales, revalidación tras crear un nuevo bloqueo,
cierre/reapertura y auditoría, transferencia/depósito, motivos, confirmaciones vencidas,
cruzadas entre sesiones/acciones, doble envío, CSRF, métodos HTTP y alcance de IDs.

La prueba de rendimiento compara 1 y 9 órdenes con pagos y reembolsos: el número de
consultas no crece por orden. La jornada manual con 8 órdenes, 3 cajas y sus movimientos
usó **25 consultas** para la capa de datos del Inicio después de cargar los permisos.
Este dato excluye autenticación, sesión y renderizado HTTP; no es una medición de
latencia ni de carga de producción.

## Prueba manual real

Se creó exclusivamente la base desechable `bigparty_visual_3a_20260928`, con impresoras
en backend debug, tres áreas, tres cajas, seis ventas rápidas y dos cuentas de mesas.
La cuenta Sport Bar ocupó dos mesas. El usuario de Gerencia tuvo rol GERENTE y permisos
explícitos, sin ser staff ni superusuario. Los datos y nombres de las capturas son de
prueba. No hubo comunicación bancaria ni impresión física.

1. Inicio: ventas brutas Q5,950; ajustes Q100; reembolsos Q50; netas Q5,800. Cobros
   confirmados iniciales Q5,300 y pagos pendientes Q500, separados.
2. Se verificaron 3 mesas físicas ocupadas, 2 cajas abiertas de 3 y 4 alertas relevantes:
   transferencia, depósito, fallo de impresión y una entrega de efectivo pendiente.
3. La gráfica horaria incluyó cobros antes y después de medianoche de la misma jornada.
   Áreas: Sport Bar Q1,700; Discoteca Q2,200; Premium Q1,900.
4. Caja Discoteca abierta: ventas asociadas Q1,500, esperado Q1,000 y retiros Q200.
5. Caja Premium cerrada: fondo Q300, esperado Q1,300, contado Q1,280 y faltante Q20
   con motivo conservado. No hubo controles para modificar importes desde Gerencia.
6. Cierres mostró 8 motivos iniciales. El botón estuvo deshabilitado tanto en Cierres
   como en la pantalla de resumen previo. Tras revisar pagos quedaron 6 motivos.
   La prueba automatizada adicional comprobó el POST forzado con bloqueos y el bloqueo
   nuevo creado después de abrir el resumen.
7. Se confirmó desde el navegador la transferencia Q350, con modal y checkbox. Se
   mostró “Pago confirmado”, usuario y hora. Desapareció de la lista de pendientes.
8. Se rechazó desde el navegador el depósito Q150, con motivo y confirmación. El pago
   y su motivo permanecieron registrados.
9. Mediante los servicios existentes de Caja/Pagos se recibió la entrega pendiente,
   se sustituyó el depósito rechazado por tarjeta, se finalizaron las cuentas y se
   contaron/cerraron las cajas. Gerencia permanece como consulta de caja.
10. El resumen pasó a 3 cajas cerradas, 0 abiertas y **0 blockers**. Sport: esperado y
    contado Q1,200; Discoteca: Q1,000; Premium conservó Q1,300/Q1,280 y diferencia −Q20.
11. Se cerró la jornada desde el navegador, usando modal y checkbox. Aparecieron
    “Jornada cerrada”, fecha comercial, hora, usuario y resumen final de Q5,800 netos.
12. Se reabrió desde el enlace discreto, con motivo y confirmación. Apareció “Jornada
    reabierta”; las tres cajas conservaron el cierre.
13. Se consultaron y verificaron los registros `cash.day_closed`, `cash.day_reopened`,
    `orders.payment_confirmed`, `orders.payment_rejected` y `BusinessDayReopen`.
    La evidencia agregada está en [verificacion-dominio.json](verificacion-dominio.json).
14. Se revisó Inicio a 1920×1080, 1440×900, 1366×768 y tablet 768×1024; se verificó que
    el documento no desbordaba horizontalmente. También se comprobó navegación de
    Cierres en tablet. El historial del navegador no mostró errores de consola.
15. Se cerraron navegador y servidor temporales, se eliminó la base desechable y sus
    archivos de impresión/fixtures/credenciales. La base real no recibió estos datos.
    El servidor propio de revisión en 127.0.0.1:8003 se actualizó al código de Fase 3A.

## Capturas

Archivos originales del navegador, JPEG de **1280×800**, sin retoques. Las pantallas
largas permiten desplazamiento vertical; estas imágenes representan su primera vista.
La captura B corresponde al estado posterior a la revisión de pagos y anterior al
cierre de las cajas. A y F conservan el estado inicial pendiente.

| Captura | Pantalla |
| --- | --- |
| [A](A-inicio.jpg) | Inicio de Gerencia |
| [B](B-cierres.jpg) | Cierres |
| [C](C-caja-abierta.jpg) | Detalle de caja abierta |
| [D](D-caja-cerrada.jpg) | Detalle de caja cerrada |
| [E](E-cerrar-jornada.jpg) | Resumen previo al cierre |
| [F](F-pago-pendiente.jpg) | Pago pendiente |
| [G](G-jornada-cerrada.jpg) | Jornada cerrada |
| [H](H-confirmacion-cierre.jpg) | Modal de confirmación, evidencia adicional |

## Decisiones y límites

- Paquete dentro de `operations`, sin app ni modelos nuevos.
- Username y contraseña; no se usa el PIN de meseros como acceso remoto.
- Reutilización de servicios y auditoría. Los snapshots solo optimizan lectura.
- Ventas netas (consumo) y cobros netos confirmados mantienen sus significados distintos.
- Sin gráficos de dependencias externas, PDF, cargas de comprobantes, WebSockets ni
  edición directa de cajas desde Gerencia.
- El historial de impresión se reutiliza. Los fallos no se añaden como bloqueos de
  cierre nuevos; las condiciones siguen perteneciendo al servicio existente.
- La reapertura no genera un informe histórico inmutable nuevo; conserva el historial
  de reapertura existente y la consulta del estado de la jornada.
- Reservas, Eventos y demás módulos pendientes permanecen deshabilitados, a la espera
  de revisión y especificación de la fase correspondiente.
