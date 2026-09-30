# Prueba piloto local — Mac y tablet Android

Este piloto usa PostgreSQL **bigparty_pilot**, desarrollo con DEBUG=True e impresión debug. No usa Cloud, sincronización, Local Node de producción ni Fase 4E. Los datos son ficticios; no introducir ventas ni credenciales de producción. No hay comando de reset.

## 1. Preparar PostgreSQL y el entorno privado

En el Mac se dejó creada/migrada la base `bigparty_pilot` y un archivo privado `.env.pilot` ignorado por Git. Si ya existen, conservarlos y continuar con el paso 2. Para preparar otro entorno, usar PostgreSQL 17 y Python 3.13 del proyecto; el usuario PostgreSQL de desarrollo necesita CREATEDB para crear la base y ejecutar tests.

En una terminal ubicada en el proyecto, indicar el usuario PostgreSQL local y crear la base **solo si no existe**:

```zsh
read -r 'DB_USER?Usuario PostgreSQL local: '
export DB_USER
/opt/homebrew/opt/postgresql@17/bin/createdb --host=127.0.0.1 --username="$DB_USER" --password bigparty_pilot
```

Si PostgreSQL está instalado en otra ruta, utilizar su `createdb` equivalente. El password lo pide PostgreSQL; no pegarlo en el comando. No sustituir el nombre por la DB habitual.

Crear/editar `.env.pilot` en el proyecto con permisos de lectura solo para tu usuario (`chmod 600 .env.pilot`). Debe contener las variables de esta tabla. Las credenciales de conexión PostgreSQL y DJANGO_SECRET_KEY se guardan allí, nunca en Git/README. Usar una clave Django aleatoria propia del piloto; no es la contraseña de Gerente Demo.

| Variable | Valor del piloto |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` |
| `DEPLOYMENT_MODE` | `development` |
| `DJANGO_DEBUG` | `True` |
| `DB_NAME` | `bigparty_pilot` |
| `DB_USER`, `DB_PASSWORD` | usuario y password PostgreSQL local elegidos |
| `DB_HOST`, `DB_PORT` | `127.0.0.1`, `5432` |
| `DJANGO_SECRET_KEY` | clave aleatoria privada del piloto |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` |
| `DEV_LAN_HOST` | IP Wi-Fi exacta del Mac, o vacío antes de usar tablet |
| `SYNC_ENABLED` | `false` |
| `RECOVERY_MODE` | `false` |
| `PRINTER_BACKEND` | `debug` |
| `PRINTER_DEBUG_DIR` | ruta absoluta a `var/pilot/print-jobs` en el proyecto |
| `OPERATIONS_STATE_ROOT` | ruta absoluta a `var/pilot/operations` en el proyecto; solo desarrollo |

La política privada de producción/recuperación de 4D sigue intacta. Estas rutas y DEBUG corresponden exclusivamente a desarrollo; no ejecutar restauraciones de producción desde este entorno.

## 2. Seleccionar explícitamente la base piloto

Ejecutar en **cada terminal** usada para el piloto:

```zsh
export BIGPARTY_ENV_FILE="$PWD/.env.pilot"
export DJANGO_SETTINGS_MODULE=config.settings.dev
export DEPLOYMENT_MODE=development
export DJANGO_DEBUG=True
export DB_NAME=bigparty_pilot
export SYNC_ENABLED=false
export RECOVERY_MODE=false
export PRINTER_BACKEND=debug
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
```

Las variables ya exportadas en el proceso prevalecen sobre `.env.pilot`; revisar `DB_USER/DB_HOST/DB_PORT` si se viene de otra sesión. Usar conexión loopback al Mac, nunca credenciales/host Cloud. No editar `.env` habitual. El seed rechaza cualquier nombre distinto de `bigparty_pilot`, DEBUG=False, modo distinto de development, sync activo, recuperación o impresión de red.

## 3. Sembrar datos y elegir credenciales

Sin credenciales, este comando crea los datos pero **no inventa PIN ni contraseña**:

```zsh
.venv/bin/python manage.py seed_pilot_demo
```

Para habilitar el acceso, elegir un PIN de **4–6 dígitos** compatible con los accesos existentes y una contraseña de gerente que cumpla los validadores Django. En zsh se pueden capturar sin mostrarlos ni escribir valores literales en el historial:

```zsh
read -rs 'PILOT_PIN?PIN elegido para los usuarios demo: '; echo
read -rs 'PILOT_MANAGER_PASSWORD?Contraseña elegida para Gerente Demo: '; echo
.venv/bin/python manage.py seed_pilot_demo \
  --pin "$PILOT_PIN" \
  --manager-password "$PILOT_MANAGER_PASSWORD"
unset PILOT_PIN PILOT_MANAGER_PASSWORD
```

El comando admite ambos argumentos opcionales, usa `set_pin()`/`set_password()` y no imprime las credenciales ni las registra en auditoría. Al pasarlos como argumentos pueden ser visibles brevemente para otros procesos del mismo usuario; utilizar únicamente el equipo personal de pruebas. No se deja ninguna contraseña demo fija en código/documentación/Git.

Es idempotente: repetir no repone stock consumido, no restaura precios o mesas modificados, no abre jornadas y no crea órdenes. Identifica sus registros mediante entradas de auditoría `pilot.demo.created`, sin modelos nuevos. Los permisos mínimos faltantes de los usuarios demo con su rol original se completan sin quitar permisos adicionales; las credenciales solo cambian si se proporcionan y son diferentes. Colisiones con identificadores ajenos al demo abortan toda la carga; no adopta usuarios/productos/mesas ajenos. No borrar los marcadores de auditoría. Si se eliminó un registro demo identificado, informa el conflicto sin resetear la operación.

### Datos iniciales

| Área | Zonas y mesas | Total |
|---|---|---:|
| Discoteca | Pista Central: Mesa 01–06; Barra / Periferia: Mesa 07–08; Zona VIP: VIP 1–2 | 10 |
| Sport Bar | Salón: Sport 01–03; Barra: Sport 04 y Sport VIP 1 | 5 |
| Premium | Premium: Premium 01–03; VIP: Premium VIP 1 | 4 |

Mesas normales de 4 personas y VIP de 6, activas/reservables, libres inicialmente. Coordenadas por zona en dos columnas, sin cruces, tamaño 40% ×27% y filas separadas; no se dejan todas en (0,0). El layout real se mantiene en tablet con viewport mayor de 760 px. En pantallas menores, la interfaz existente adapta a rejilla para legibilidad; para evaluar el plano usar tablet horizontal, zoom normal y ancho CSS superior a 760 px. No se modificó ese comportamiento del POS.

| Producto | Precio Q | Stock inicial | Ruta |
|---|---:|---:|---|
| Gallo | 25 | 100 | Barra del área |
| Cabro | 25 | 80 | Barra del área |
| Corona | 30 | 80 | Barra del área |
| Whisky | 45 | 40 | Barra del área |
| Ron | 40 | 40 | Barra del área |
| Mojito | 40 | sin control | Barra del área |
| Margarita | 45 | sin control | Barra del área |
| Hamburguesa | 65 | 40 | Cocina |
| Papas fritas | 30 | 50 | Cocina |
| Nachos | 35 | 50 | Cocina |
| Hielo | 0 | 100 | Sin preparación; oculto en POS |
| Combo BIG | 110 | sin stock propio | Según componentes |

Stock inicial mediante el servicio de inventario y su historial. Categorías existentes reutilizadas, sin categoría adicional para hielo. Slugs de productos demo con prefijo `pilot-`. Premium: Gallo Q30, Corona Q35, Whisky Q50; precios generales conservados. Combo BIG utiliza `ComboComponent`: una Hamburguesa, unas Papas fritas y una Gallo.

Modificadores opcionales: Hamburguesa → Preparación SINGLE (Normal, Sin cebolla, Sin tomate), Extras MULTIPLE (queso +Q10, tocino +Q15). Whisky → Preparación SINGLE (Solo, Con hielo, Con soda) y Extras MULTIPLE (Energética +Q15).

| Usuario | Rol y permisos |
|---|---|
| `carlos_demo`, `andrea_demo` | MESERO: mapa, abrir mesa, subcuentas, productos, enviar, pagos operativos, cerrar cuenta y recibo. Sin administración. |
| `luis_caja_demo` | CAJERO: abrir/contar/cerrar caja, venta rápida y carga a mesa (incluye agregar/enviar productos), recibir efectivo y solicitar retiro. Sin aprobar retiros ni administración. |
| `gerente_demo` | GERENTE: permisos explícitos del catálogo de negocio, jornada, pagos, inventario, usuarios, reservas/eventos, reportes, auditoría y configuración. Staff solo para configurar navegadores; **no superuser**. |
| `guardia_demo` | GUARDIA: únicamente `events.scan_event_ticket`. Sin POS, Caja ni Gerencia. |

Dispositivo: **Tablet Discoteca Demo**, código **TAB-DISCO-DEMO**, tipo WAITER_TABLET, área Discoteca, activo. Sin cookies creadas por el seed. Cajas Sport Bar/Discoteca/Premium y rutas Barra 1/2/3/Cocina se reutilizan o crean con los seeds existentes; no se inventan IPs. No se crean LocalNodeIdentity, eventos de sincronización, reservas, eventos comerciales ni tickets QR.

## 4. Encontrar IP Wi-Fi y abrir acceso LAN

Mac y Android deben estar en el mismo Wi-Fi, sin aislamiento de clientes/red de invitados. Consultar Ajustes del Sistema → Wi-Fi → Detalles → TCP/IP, o identificar primero la interfaz:

```zsh
networksetup -listallhardwareports
# Usar el Device de Wi-Fi; normalmente en0:
ipconfig getifaddr en0
export DEV_LAN_HOST="$(ipconfig getifaddr en0)"
.venv/bin/python manage.py check
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

`DEV_LAN_HOST` añade **solo esa IP** a ALLOWED_HOSTS y `http://IP:8000` a CSRF_TRUSTED_ORIGINS. No se utiliza `*`. Admite IP concreta IPv4/IPv6, rechaza URLs, puertos y comodines. Reiniciar runserver si cambia la IP por DHCP; mantener actualizado `.env.pilot` si se guarda allí. El servidor queda ligado a la LAN durante esta prueba; detenerlo con Ctrl+C al terminar. No abrir puertos en el router ni publicar en Internet. Si macOS solicita acceso entrante, permitirlo únicamente para esta prueba en la red privada.

En Mac abrir `http://localhost:8000/gerencia/`. En tablet abrir `http://IP_DEL_MAC:8000/operacion/`; **localhost en Android apunta a la tablet**, no al Mac. Mantener siempre el mismo host en cada navegador: las cookies son independientes entre localhost e IP.

HTTP LAN permite probar POS/Caja/Gerencia, pero la cámara QR del navegador requiere HTTPS confiable. En este piloto HTTP no se promete cámara Android; Guardia puede probar acceso/interfaz sin generar entradas válidas innecesarias. No activar Local Node ni configurar TLS de producción para resolverlo aquí.

## 5. Entrar y configurar navegadores

1. **Gerencia (Mac):** `/gerencia/`, usuario `gerente_demo` y contraseña elegida. Abrir la jornada manualmente en Jornadas. No hay jornada abierta por el seed.
2. **Tablet de meseros:** en el navegador Android abrir `/admin/login/?next=/dispositivo/configurar/`, ingresar como `gerente_demo` y seleccionar **Tablet Discoteca Demo**. Esta sesión técnica es independiente de Gerencia. Cerrar sesión técnica después de asociar, conservando la cookie del dispositivo (no borrar datos del navegador). Ir a `/operacion/`, elegir Carlos o Andrea e ingresar PIN.
3. **Caja (Mac u otro navegador):** abrir `/admin/login/?next=/caja/configurar/`, usar gerente y seleccionar **Caja Discoteca**. Cerrar la sesión técnica; entrar a `/caja/`, elegir Luis Caja Demo y PIN. Abrir CashSession manualmente con fondo inicial elegido. Gerencia y Caja mantienen sus propias sesiones.
4. **Guardia:** `/acceso/`, usuario Guardia Demo y PIN. Solo dispone del permiso de escaneo.

Si se cambia de host, se usa incógnito o se borran cookies, repetir asociación de dispositivo/caja. No ejecutar seeds para configurar cookies.

## 6. Recorrido funcional sugerido

1. Confirmar las 19 mesas libres antes de operar. En Discoteca comprobar las tres zonas y el plano en tablet horizontal.
2. Abrir Mesa 01 con Carlos, crear subcuentas, añadir Gallo y Hamburguesa; elegir preparación y extras. Enviar y consultar cuenta.
3. Revisar salida debug de Barra 2 y Cocina en `var/pilot/print-jobs`; nunca se envía a impresoras reales. Un combo descuenta sus tres componentes, no un stock propio.
4. Cambiar a Andrea y revisar el comportamiento de permisos/responsable y la actualización entre Mac/tablet sin repetir el envío.
5. Registrar pago operativo, comprobar saldo y cerrar la cuenta usando sus controles existentes. El efectivo del mesero debe recibirse en Caja mediante entrega, no considerarse efectivo recibido automáticamente.
6. En Caja hacer una venta rápida y probar carga a una mesa abierta; comprobar movimientos y recepción de efectivo. Un retiro requiere autorización de Gerente con PIN; Luis solo lo solicita.
7. Para comparar precios Premium, configurar explícitamente otro contexto de prueba desde los flujos existentes (p. ej. asociar navegador de Caja a Caja Premium y abrir su sesión). No cambiar áreas de sesiones con operaciones pendientes. Confirmar Gallo Q30, Corona Q35, Whisky Q50 y precio general intacto.
8. Revisar inventario, reportes, auditoría, configuración y formularios de reservas/eventos con Gerente. Crear datos comerciales solo manualmente si hacen falta para la prueba.
9. Contar/cerrar Caja, comprobar entregas/pagos pendientes y cerrar jornada desde Gerencia. Registrar incidencias observadas, sin modificar reglas de negocio durante el piloto.

## 7. Comprobaciones y limpieza

```zsh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test
```

Con DB_NAME=bigparty_pilot, Django crea/elimina **test_bigparty_pilot** para la suite; el seed en tests usa aislamiento controlado. Los tests verifican DEBUG y entorno, colisiones, idempotencia, hashes, permisos, usuarios, mesas/layout, stock/precios, modificadores, combo, dispositivo, ausencia de jornada/órdenes y DEV_LAN_HOST. No se necesitan migraciones nuevas.

Para empezar otra vez: detener runserver y conexiones del piloto, comprobar nombre y eliminar **solo la base completa dedicada**:

```zsh
/opt/homebrew/opt/postgresql@17/bin/dropdb --host=127.0.0.1 --username="$DB_USER" --password bigparty_pilot
```

Luego repetir createdb, migrate y seed. No hay `reset_pilot_demo`, `flush` ni borrado selectivo de datos de negocio. La base habitual, archivos de entorno y otros proyectos no se limpian. El borrado de esta base no se ejecutó durante la preparación: queda disponible para la prueba manual.
