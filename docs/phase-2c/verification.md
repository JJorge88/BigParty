# Verificación Fase 2C — 28 de septiembre de 2026

La prueba se ejecutó con Django y PostgreSQL reales en una base desechable separada.
Los usuarios, dispositivo, jornada, mesas, productos, inventario, consumos y pagos eran
datos temporales. No se utilizaron terminales bancarias ni dinero real.

## Pruebas automáticas

- Suite completa: **484 pruebas Django aprobadas**, incluidas 53 nuevas de esta fase.
- JavaScript: **6 pruebas aprobadas**, incluidas cambio exacto y recuperación de selecciones obsoletas.
- `manage.py check`: sin errores.
- `makemigrations --check --dry-run`: sin cambios.
- Dos carreras reales entre tablets/conexiones: mismas unidades y monto concurrente.
  En ambas, una confirmación pasó y la otra recibió un conflicto humano, sin duplicar pagos.
- Se mantienen las suites anteriores de catálogo, pedidos, pagos, caja, jornada y sesiones.

## SINGLE — Mesa 07

1. Jornada abierta mediante el servicio existente, dispositivo Discoteca y acceso Carlos por PIN.
2. Apertura visual SINGLE; cuatro Gallo a Q30 y dos hamburguesas a Q65, con modificador Normal.
3. Envío a preparación y navegación Pedido → Ver cuenta: total Q250, pagado Q0, pendiente Q250.
4. Dividir cuenta → seleccionar dos Gallo → monto Q60, sin cambiar modalidad SINGLE.
5. Efectivo recibido Q100: cambio Q40. Confirmación: pago Q60; dos Gallo pagadas y dos pendientes.
6. Cobrar saldo: tarjeta Q190, confirmado tras la indicación de terminal bancaria.
7. Saldo Q0, productos conservados en Pagados y botón Cerrar cuenta.
8. Cierre explícito: Mesa 07 disponible; regreso al mapa con estado Libre.

Los registros backend confirmaron CASH Q60 con entrega PENDING y CARD Q190 confirmado.
El efectivo del mesero no generó movimiento directo en una sesión de caja.

## Mixto — Mesa 08

1. Apertura SINGLE, consumo enviado de diez Ron añejo a Q50: Q500.
2. Pago mixto → efectivo Q200, recibido exacto y cambio Q0.
3. Resumen e historial: total Q500, pagado Q200, pendiente Q300.
4. Segundo método: tarjeta Q300. Saldo cero y cierre explícito; mesa Libre.
5. Se repitió la preparación de una cuenta temporal equivalente para guardar capturas
   con Q200 confirmados y Q300 pendientes. La división muestra seis unidades disponibles
   de diez originales y permite seleccionar dos por Q100; las cuatro ya pagadas no se ofrecen.

## Transferencia — Mesa 09

1. Nueva mesa SINGLE con Gallo Q30 enviado.
2. Transferencia: botón deshabilitado sin referencia; referencia temporal ingresada.
3. Registro PENDING: Q0 confirmado, Q30 por verificar, Q0 disponible para otro cobro.
4. No aparece Cerrar cuenta; Cobrar está deshabilitado. En mapa: Pago pendiente.

Depósito, rechazo posterior, reservas en mixto, descuentos y reembolsos están cubiertos
por las pruebas automatizadas. La interfaz de aprobación de Gerencia no forma parte de esta fase.

## SPLIT — Mesa 10

1. Apertura SPLIT y creación visual de Jorge y Carlos.
2. Jorge: Gallo Q30; Carlos: Alitas Q70. Ambos pedidos enviados separadamente.
3. Ver cuenta → Jorge → tarjeta Q30.
4. Jorge cambia a Pagada, mantiene historial y productos en sección Pagados, sin agregar productos.
5. Carlos permanece abierto con Q70 por cobrar; no se puede cerrar la mesa completa.
6. Vista de Carlos revisada a 800×1280: documento y viewport de 800 px, sin desbordamiento horizontal.

## Capturas reales

Capturas del sitio ejecutándose, sin montaje ni sustitución de contenido:

- A. [Ver cuenta — 1280×800](account-1280x800.png): Mesa 07 y consumo enviado de Q250.
- B. [Dividir cuenta — 1280×800](divide-1280x800.png): selección financiera tras un abono,
  cuatro unidades pagadas, seis disponibles, dos seleccionadas por Q100.
- C. [Pago en efectivo — 1280×800](cash-1280x800.png): Q60 a pagar, Q100 recibidos y Q40 de cambio.
- D. [Pago mixto — 1280×800](mixed-1280x800.png): Q500 de total, Q200 confirmado, Q300 pendiente.
- [SPLIT vertical — 800×1280](split-800x1280.png).

La consola del navegador no registró errores ni advertencias durante estos recorridos.
Las confirmaciones se mantuvieron explícitas; no hubo pagos automáticos ni impresión.
La base temporal y los scripts de preparación se eliminaron al terminar. Las imágenes
conservan exclusivamente datos de prueba.

Pendiente: revisión del usuario y validación en hardware Android del local. Caja visual,
Gerencia final, movimiento/unión de mesas, impresoras, reservas, eventos y QR siguen fuera
de alcance.
