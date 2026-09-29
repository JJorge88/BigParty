# Fase 3E — Verificación

Fecha: 29/09/2026. Datos completamente ficticios en la base local aislada
`bigparty_visual_3e_20260929`, servidor temporal en 127.0.0.1:8004.

## Pruebas automatizadas

- Suite completa: **927 pruebas Django**, correctas (86.434 s).
- 25 pruebas nuevas para reportes, configuración, auditoría y casos de reservas/eventos.
- JavaScript: **7 pruebas**, correctas.
- `check`: sin incidencias. `makemigrations --check --dry-run`: sin cambios pendientes.
- Migraciones nuevas aplicadas: `audit.0002`, `core.0001`, `core.0002`.
- Se verificaron permisos explícitos, CSRF, POST, rechazo de métodos deshabilitados,
  conservación de historial/revisión de pendientes, auditoría sin usuario,
  metadatos sensibles anidados y PDF con motivos que continúan entre páginas.
- La prueba de crédito compara el saldo con el servicio financiero existente:
  Q300 de anticipo con Q100 de consumo aplica únicamente Q100, no Q300.

## Revisión del navegador y del PDF

1. Ingreso con Julia Morales, usuario ficticio sin privilegio de superusuario.
2. Hub y los diez reportes abiertos y leídos con datos reales del dominio de prueba.
3. Resumen: bruto **Q600**, ajustes **Q30**, reembolsos **Q10**, neto **Q560**;
   cobros netos **Q290**, pendientes **Q50**, saldo **Q270**.
4. Productos: cerveza, 16 unidades / Q400 brutos / Q360 netos;
   combo, 2 unidades / Q200. No se expandieron sus componentes como ventas.
5. Área: dos pedidos, incluida una venta rápida. Meseros distingue responsable y actor.
6. Caja: fondo Q500, esperado Q575, contado Q570, diferencia **−Q5**, retiro Q75.
7. Cancelación de dos cervezas por Q50 con devolución de inventario; reembolso Q10
   separado, sin devolución de inventario. Descuento Q30 con motivo y autorizador.
8. Reservas por fecha programada; evento con dos entradas vendidas, dos cortesías
   y **Q200 confirmados**. Compra sin comprobante no sumó ingresos pendientes.
9. Descarga desde el botón PDF con sesión autorizada y nombre español sanitizado.
   Se inspeccionaron visualmente **las cuatro páginas** renderizadas con Poppler;
   tablas, acentos, totales y pies legibles, sin recortes. El documento exportado
   se conserva en `output/pdf/big-party-jornada-2026-09-29.pdf`.
10. Auditoría filtrada por **Julia + Inventario**; detalle de cambio de precio
    Q25 → Q30, contexto de producto y ausencia de datos reservados.
11. Tarjeta deshabilitada y reactivada desde el navegador. El POS real se comprobó
    mediante cliente HTTP Django con CSRF, vinculación de dispositivo y sesión
    operativa válidas: botón Tarjeta ausente y servicio rechazando nuevos cobros.
    Evidencia en `verificacion-http.json`. Historial: Q150 bruto, Q10 reembolso,
    Q140 neto, conservado después de reactivar.
12. Datos bancarios ficticios configurados y visibles en reserva pendiente y
    compra de evento pendiente. No se enviaron pagos reales.
13. Configuraciones existentes de reservas y eventos abiertas. Impresoras abrió
    su acceso técnico existente; se verificó mediante usuario técnico ficticio.
14. Responsive: hub en 1440, 768 y 390 píxeles, sin desborde horizontal de la página.
    Tabla de caja a 390 px: documento 390, contenedor 356, tabla 1067; el desplazamiento
    horizontal queda dentro del contenedor. Evidencia en `responsive.json`.

## Capturas

A Reportes; B Resumen; C Productos; D Cajas; E PDF renderizado; F Auditoría;
G Detalle; H Configuración; I Métodos de pago deshabilitando Tarjeta;
J Datos de transferencia. Capturas de navegador de 1280×800; PDF a 1280×906.
Las capturas contienen datos de demostración, no información de producción.

## Decisiones y límites

- Venta y cobro por jornada; reservas/eventos por fecha programada porque carecen
  de FK de jornada. Se explica tanto en pantalla como en README.
- 93 días, hasta 5,000 filas por conjunto y 25 por página; hasta 1,000 filas por PDF.
- Moneda y zona horaria fijas; nombre editable. URL pública y seguridad en entorno.
- Sin banco completo se muestra error administrativo explícito; no se interrumpen
  solicitudes ni comprobantes históricos. Los cuatro métodos configurables
  corresponden a cobros operativos; los portales conservan su flujo de transferencia.
- Los permisos nuevos no se asignan automáticamente en la base de operación.
- La configuración técnica de impresoras/dispositivos conserva su acceso existente.
- No se inició ninguna fase posterior a 3E.

## Limpieza

Al finalizar se detuvo el servidor temporal, se cerraron sus pestañas, se eliminó
la base aislada y sus archivos de imágenes/comprobantes, scripts y sesiones.
Se conservan únicamente evidencia, capturas y PDF de demostración en el proyecto.
