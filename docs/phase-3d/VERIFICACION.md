# Verificación Fase 3D

Fecha: 29 de septiembre de 2026. Base: `07905e8` (Fase 3C).

## Alcance

Interfaces de Gerencia para inventario, catálogo, categorías, modificadores, combos,
precios por área, usuarios y permisos. Se reutilizan modelos y servicios existentes.
Una sola migración nueva de opciones/permisos: `accounts.0002_alter_user_options`.
No se añaden modelos ni dependencias. No se desarrolla Fase 3E.

## Pruebas automatizadas

- Suite Django completa: **902 pruebas**, incluyendo **43 nuevas** para Fase 3D.
- JavaScript: **7 pruebas**, todas correctas.
- `manage.py check`: sin problemas.
- `makemigrations --check --dry-run`: sin cambios pendientes.
- `git diff --check`: sin errores de formato.

Las pruebas nuevas cubren estados/filtros/búsqueda, límite de permisos, entradas y
ajustes con auditoría, cantidades inválidas, saldo negativo, precio general y especial,
eliminación de precio especial, historial, creación sin stock directo, activación,
imagen inválida, categorías sin borrado, grupos/opciones y validaciones de combos.

Usuarios: altas de los cinco roles, PIN y contraseña con hash, valores inválidos,
confirmación, reset sin eco de secretos, permisos explícitos, sesiones operativas,
cambio de rol conservando permisos, guardia compatible, lista de permisos reales,
permisos externos preservados, presets confirmados/aditivos, edición obsoleta,
protección de cuentas técnicas o más privilegiadas (también inactivas), desactivación,
CSRF, POST y consultas sin crecimiento N+1.

Dos pruebas con conexiones PostgreSQL separadas verifican desactivación simultánea
de propietarios y edición simultánea de permisos. En ambos casos una operación
confirma y la otra se rechaza conservando el estado válido.

## Recorrido manual con datos aislados

Se creó exclusivamente para esta revisión la base `bigparty_visual_3d_20260929`.
Todos los nombres, productos, credenciales y movimientos de las capturas pertenecen
a esa base de demostración. No se alteraron usuarios ni existencias reales.

### En navegador

1. Ingreso a Gerencia y apertura de Inventario desde Administrar.
2. Comprobación de productos disponibles, con stock bajo y agotados.
3. Gallo inicia con 6 unidades y mínimo 12.
4. Registrar entrada de 24: queda en 30 y registra motivo/responsable.
5. Ajustar Reducir 2, motivo Rotura: queda en 28.
6. Cambiar precio general Q25 → Q28.
7. Establecer precio Premium Q35 y verificar ambos cambios en historial.
8. Crear Papas BIG, precio Q40, control de stock, mínimo 5 y preparación Cocina.
   Empieza en cero y aparece agotado.
9. Registrar entrada inicial de 20.
10. Crear grupo Extras, selección múltiple, y opción Extra queso +Q10.
11. Revisar listado/detalle de usuarios, matriz y modal de PIN.
12. Verificar que el formulario de alta cambia entre PIN y contraseña según rol.
13. Comprobar apertura y cierre del modal; no se muestra credencial anterior.
14. Revisar consola: sin errores ni advertencias en las pantallas nuevas.

### Peticiones de aplicación con CSRF habilitado

Para altas, credenciales y permisos se usó el cliente HTTP de Django sobre la misma
base temporal, con inicio de sesión normal, cookies, tokens CSRF y confirmaciones
firmadas. No se introdujeron credenciales nuevas mediante automatización del navegador.

1. Crear Mesero, Cajero y Guardia con PIN inicial y confirmación.
2. Aplicar sugerencias mediante la confirmación real de cada pantalla.
3. Ingresar a tablet con Mesero.
4. Restablecer PIN: cookie antigua bloqueada, PIN anterior rechazado y nuevo aceptado.
5. Ingresar a PC/caja con Cajero y permisos sugeridos.
6. Ingresar a `/acceso/` con Guardia; comprobar que sólo posee `scan_event_ticket`.
7. Desactivar Mesero mediante confirmación: cookie e ingreso posterior bloqueados.
8. Intentar desactivar al único Propietario: rechazo con explicación y estado intacto.
9. Consultar el catálogo que consume POS: Papas BIG disponible y Extra queso presente.
10. Comprobar en base temporal stock final de Gallo (28), movimiento de Rotura,
    precio general Q28, Premium Q35 y dos cambios de precio.

Resultado: todas las comprobaciones correctas. La base, servidor y credenciales
temporales fueron eliminados al terminar; las capturas y este informe son la evidencia.

## Responsive y capturas

Capturas A–J a **1280 × 800**. Formulario de usuario verificado también a
**1440 × 900**, **1366 × 768**, **1920 × 1080** y **768 × 1024**. En tablet se revisaron
además inventario, detalle de producto, detalle de usuario y matriz de permisos.
No hubo desbordamiento horizontal de la página; las tablas conservan su contenedor
con desplazamiento cuando hace falta. Medidas en `responsive-check.json`.

| Captura | Archivo |
| --- | --- |
| A · Inventario | [A-inventario.jpg](A-inventario.jpg) |
| B · Producto | [B-producto.jpg](B-producto.jpg) |
| C · Registrar entrada | [C-registrar-entrada.jpg](C-registrar-entrada.jpg) |
| D · Ajustar stock | [D-ajustar-stock.jpg](D-ajustar-stock.jpg) |
| E · Movimientos | [E-movimientos.jpg](E-movimientos.jpg) |
| F · Usuarios | [F-usuarios.jpg](F-usuarios.jpg) |
| G · Detalle usuario | [G-detalle-usuario.jpg](G-detalle-usuario.jpg) |
| H · Permisos | [H-permisos.jpg](H-permisos.jpg) |
| I · Crear usuario | [I-crear-usuario.jpg](I-crear-usuario.jpg) |
| J · Restablecer PIN | [J-reset-pin.jpg](J-reset-pin.jpg) |

## Decisiones de operación

- PIN inicial obligatorio para Mesero/Cajero/Guardia; contraseña inicial obligatoria
  para Gerente/Propietario. Las credenciales administrativas se establecen individualmente.
- No hay permisos automáticos por rol. Sugerencias siempre explícitas y aditivas.
- No se permite tomar control de usuarios con permisos que el administrador no posee,
  aunque estén inactivos. Staff/superuser no son campos de esta interfaz.
- Cambio a Guardia exige retirar permisos incompatibles por una acción explícita.
  Los heredados o técnicos se resuelven en Admin; no se borran silenciosamente.
- Usuarios y productos se desactivan, no se borran. Modificadores usan estado activo;
  componentes sí se pueden retirar sin alterar los registros históricos de consumo.
- Historial resumido de precios: últimos 15; movimientos: últimos 10 y enlace al listado
  paginado. Los registros anteriores permanecen en la base de datos.
- No se incorporaron correo, perfil personal completo, exportaciones ni panel global
  de auditoría. Son ajenos a esta fase.

Pendiente de revisión del usuario. **No avanzar a Fase 3E.**
