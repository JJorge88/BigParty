# Verificación de Fase 2A

Fecha: 28 de septiembre de 2026. Desarrollo local; sin despliegue.

## Pruebas automatizadas

- `python manage.py check`: sin incidencias.
- `python manage.py makemigrations --check`: sin cambios pendientes.
- `python manage.py test`: **382 pruebas aprobadas**, 47 nuevas y 335 anteriores.
- Concurrencia real en PostgreSQL: dos tablets abren la misma mesa → una apertura
  y un conflicto amigable; cinco fallos de PIN concurrentes → bloqueo persistente.
- Migración `operations.0001_initial` aplicada; migraciones históricas conservadas.

## Recorrido de navegador

Se creó una base PostgreSQL desechable, `bigparty_visual_2a_20260928`, con seis
meseros y doce mesas exclusivamente para esta comprobación. El servidor temporal
utilizó el puerto 8012 y la base real no recibió esos datos.

1. Iniciar sesión administrativa y configurar Tablet Discoteca 01.
2. Seleccionar Carlos Méndez y escribir su PIN con los botones del teclado.
3. Entrar al mapa: solo Discoteca, mesas agrupadas en dos zonas.
4. Buscar `7`: aparece Mesa 07.
5. Abrir el panel libre, comprobar área y capacidad.
6. Seleccionar Una sola cuenta: Mesa 07 pasa a Ocupada, muestra Carlos como
   responsable, Q0.00 y el aviso de apertura; catálogo/cuenta siguen deshabilitados.
7. Cambiar usuario y entrar como Ana López con su propio PIN. Mesa 07 conserva
   la cuenta y la responsabilidad de Carlos.
8. Abrir otra mesa con Cuentas separadas y comprobar el resultado.
9. Dejar la interfaz sin interacción: vuelve al selector tras unos dos minutos.
10. Volver a entrar con PIN y comprobar que las mesas siguen abiertas.

Se verificaron el selector, teclado, mapa y panel en 1280×800 y 800×1280.
La vista vertical no produjo desbordamiento horizontal. Los estados de pago parcial,
pago pendiente y fuera de servicio se mostraron junto con consumo y tiempo real.
El aviso de apertura se ajustó para aparecer dentro del panel y conservar contraste.
Se verificó una zona con posiciones configuradas: controles de 147×203 px en un
lienzo de 736×580 px, junto a otra zona con cuadrícula. Sin errores JavaScript
registrados en la comprobación final.

Las capturas adjuntas contienen datos temporales, no representan la operación real:

- `table-open.png`: Mesa 07 ocupada por Carlos, vista desde la sesión de Ana.
- `map-portrait.png`: mapa vertical después de volver a ingresar con PIN.

El servidor temporal y la base de prueba se eliminan al concluir. La base del
proyecto conserva cero dispositivos, sesiones operativas, intentos PIN, órdenes y
jornadas abiertas de esta prueba. Para operar realmente hay que configurar usuarios,
permisos, dispositivo y jornada mediante las herramientas existentes.

No se probó una tablet Android física. Quedan pendientes la revisión del usuario
y el trabajo visual de catálogo/pedidos correspondiente a Fase 2B.
