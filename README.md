# BIG PARTY — Fases 0 a 3D

Fundación técnica de un sistema empresarial para bar, discoteca y restaurante en Guatemala.
La Fase 0 contiene configuración, usuarios, roles, permisos nativos de Django,
soporte seguro de PIN, auditoría y una página de comprobación. La Fase 1A añade la
configuración física de áreas, zonas y mesas. La Fase 1B añade catálogo e inventario global.
La Fase 1C incorpora cuentas de mesa, subcuentas, consumo enviado y comandas lógicas.
La Fase 1D añade pagos, descuentos, reembolsos y cierre de cuentas.
La Fase 1E incorpora caja física, entregas de efectivo, conteo ciego y jornadas.
La Fase 2A inicia la interfaz operativa del mesero: dispositivo, PIN, mapa y apertura de mesas.
La Fase 2B añade catálogo y pedidos visuales, modificadores, adiciones y selección de subcuentas.
La Fase 2C incorpora Ver cuenta, selección por cantidades, pagos y cierre explícito.
Las fases 2D–2F incorporan Caja visual, venta rápida e impresión.
Las fases 3A–3C añaden Gerencia, reservas y eventos con entradas y control de acceso.
La Fase 3D incorpora las interfaces finales de inventario, catálogo, usuarios y permisos.

## Requisitos

- macOS con Python 3.13 (no utilizar el Python 3.9 del sistema).
- PostgreSQL 17 en ejecución, con `psql`, `createuser` y `createdb` disponibles.
- Git.

Entorno verificado: macOS 27.0 ARM64, Python 3.13.14, PostgreSQL/psql 17.10,
Git 2.54.0. Dependencias: Django 5.2.17 LTS, psycopg con binarios 3.3.6 y
python-dotenv 1.2.3 y Pillow 12.3.0. Pillow valida las imágenes opcionales de productos;
es la única dependencia directa añadida en la Fase 1B.
La [rama Django 5.2 LTS](https://www.djangoproject.com/download/) es la base elegida.

Si faltan las herramientas en otra Mac con Homebrew:

```sh
brew install python@3.13 postgresql@17
brew services start postgresql@17
export PATH="$(brew --prefix postgresql@17)/bin:$PATH"
```

No reinstalar ni reinicializar un clúster PostgreSQL existente.

## Inicio en esta Mac

El entorno `.venv`, el archivo `.env`, el rol y la base de datos ya están creados,
y las migraciones están aplicadas. Desde Terminal:

```sh
cd "/Users/jorgeluismejiarodriguez/Documents/Poyectos/Big Party"
source .venv/bin/activate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

El primer comando de Django solicita tus propias credenciales; se ejecuta una sola vez.
No se ha creado un superusuario ni se incluye ninguna contraseña predeterminada.

- Página de comprobación: <http://127.0.0.1:8000/>
- Administración: <http://127.0.0.1:8000/admin/>

Para detener el servidor: `Ctrl+C`. Para salir del entorno: `deactivate`.

## Instalación desde una copia nueva

Ejecutar desde la raíz del proyecto:

```sh
"$(brew --prefix python@3.13)/bin/python3.13" -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/dev.txt
cp -n .env.example .env
chmod 600 .env
```

Editar `.env` localmente. No sobrescribir un archivo `.env` existente ni compartirlo.
Generar una clave única de Django y copiar el resultado únicamente a `DJANGO_SECRET_KEY`:

```sh
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Encerrar esa clave entre comillas simples en `.env`, ya que puede contener caracteres
especiales. Configurar también la contraseña real del rol PostgreSQL. Los valores
`replace-with-...` del ejemplo se rechazan al arrancar.

| Variable | Uso local |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` |
| `DJANGO_SECRET_KEY` | Clave aleatoria propia de la instalación |
| `DJANGO_DEBUG` | `True`; admite `True`, `False`, `1` o `0` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` |
| `DB_NAME` | `bigparty` |
| `DB_USER` | `bigparty_user` |
| `DB_PASSWORD` | Contraseña local, nunca versionada |
| `DB_HOST` | `127.0.0.1` |
| `DB_PORT` | `5432` |
| `TIME_ZONE` | `America/Guatemala` |

Las variables ya exportadas en el proceso tienen prioridad sobre `.env`.
Idioma `es`, fechas con zona horaria (`USE_TZ=True`).

### PostgreSQL

Django utiliza exclusivamente PostgreSQL, incluidas las pruebas. En una instalación
nueva, desde una cuenta administradora local de PostgreSQL y solo si no existen el rol y la base:

```sh
createuser --login --createdb --pwprompt bigparty_user
createdb --owner=bigparty_user bigparty
psql -X -d postgres -c 'GRANT CONNECT ON DATABASE postgres TO bigparty_user;'
```

`--pwprompt` solicita la contraseña sin incluirla en el historial de comandos.
Si PostgreSQL exige otra cuenta administradora, añadir `-U nombre_administrador` a
estos comandos y proporcionar su contraseña de forma interactiva. No escribirla
en el código ni en argumentos de consola.

El rol del proyecto no es superusuario y no puede crear roles. `CREATEDB` se utiliza
exclusivamente en este entorno de desarrollo para crear y destruir `test_bigparty`.
El permiso `CONNECT` a `postgres` permite al runner de Django administrar esa base temporal;
no concede acceso de escritura a tablas ajenas. No usar `test_bigparty` para datos reales.

La instalación actual conserva las reglas locales `trust` que ya tenía PostgreSQL;
no se modificó `pg_hba.conf`. Hay una contraseña aleatoria del rol guardada solo en
`.env`, pero esas reglas locales no la exigen. La autenticación del servidor deberá
revisarse en la fase correspondiente antes de exponerlo a otras máquinas.

### Migraciones y administrador

```sh
python manage.py check
python manage.py migrate
python manage.py seed_bigparty_defaults
python manage.py seed_catalog_defaults
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

`AUTH_USER_MODEL = "accounts.User"` está definido desde el inicio.
Las migraciones de `accounts` y `audit` se versionan; no deben borrarse ni regenerarse
para sustituir el modelo de usuario después de cargar datos.

## Estructura

```text
.
├── manage.py
├── config/
│   ├── settings/{base,dev,prod}.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   ├── accounts/     # AbstractUser, roles, PIN y administrador
│   ├── audit/        # Registro explícito de auditoría
│   ├── core/         # Página mínima de comprobación
│   ├── venues/       # Áreas, zonas y comando de datos iniciales
│   ├── tables/       # Mesas, servicios y vista de desarrollo
│   ├── catalog/      # Categorías, productos, precios, modificadores y combos
│   ├── inventory/    # Movimientos y servicios de inventario global
│   ├── orders/       # Cuentas, subcuentas, consumo y comandas lógicas
│   ├── payments/     # Pagos, descuentos, reembolsos y liquidación
│   └── cash/         # Caja física, entregas, conteo ciego y jornadas
├── templates/
│   ├── base.html
│   ├── core/home.html
│   ├── tables/configuration.html
│   ├── catalog/development.html
│   ├── inventory/development.html
│   ├── orders/development.html
│   ├── payments/development.html
│   └── cash/{development,business_day}.html
├── static/css/base.css
├── media/.gitkeep
├── requirements/{base,dev,prod}.txt
├── .env.example
├── .gitignore
└── README.md
```

La raíz de este repositorio es la raíz Django: no se necesita una carpeta `bigparty`
adicional. `base.py` comparte configuración, `dev.py` sirve el desarrollo local y
`prod.py` deshabilita DEBUG, exige hosts explícitos y marca las cookies como seguras.
La configuración de producción es una base, no un despliegue completo. Esta fase no
incluye instrucciones de despliegue.

El CSS declara `Inter, sans-serif`; utiliza la alternativa del sistema si Inter no está
instalada. No se descargan fuentes externas ni se construye un sistema de diseño.
`media/` está preparado para archivos locales y su contenido se excluye de Git.

## Usuarios, roles y permisos

`accounts.User` extiende `AbstractUser`. El campo `role` usa `TextChoices`:
`MESERO`, `CAJERO`, `GERENTE`, `PROPIETARIO` y `GUARDIA`. El valor inicial es `MESERO`.
La base de datos rechaza valores fuera de esta lista.

El rol clasifica al usuario; no concede permisos automáticamente. Incluso `PROPIETARIO`
no equivale a superusuario. Los permisos individuales (`user_permissions`), grupos,
`is_staff` e `is_superuser` conservan el comportamiento de Django. El administrador
permite buscar por usuario, nombre, apellido y correo, y filtrar por rol y estado.
El rol del superusuario puede ajustarse a `PROPIETARIO` desde el administrador si corresponde.

### PIN

El PIN es opcional y separado de la contraseña de acceso al administrador.
`set_pin("012345")` utiliza el hasher de Django con sal; `check_pin("012345")`
comprueba el valor. El PIN se recibe como texto de 4 a 12 dígitos ASCII para conservar
ceros iniciales. `set_pin(None)` lo deshabilita. `set_pin` no guarda el modelo:
se debe llamar después a `save(update_fields=["pin_hash"])`.

Al editar un usuario en el administrador, la sección **Cambiar PIN** solicita el nuevo
PIN dos veces, con campos ocultos. Dejar ambos vacíos conserva el anterior.
El hash no es editable ni visible en el administrador. El PIN no autentica sesiones
y no se ha implementado pantalla operativa, bloqueo por intentos ni acceso de tablets.

## Auditoría

`AuditLog` contiene usuario opcional, acción, entidad, identificador textual de entidad,
datos adicionales en JSON y fecha/hora automática. Se crean registros explícitamente
desde el código cuando una fase futura lo requiera; no existen señales globales.

Los registros se pueden consultar en el administrador con el permiso correspondiente,
pero no añadir, editar ni eliminar, incluso como superusuario. Si se elimina el usuario
relacionado, el registro se conserva con usuario nulo. Esta protección es del administrador;
no pretende ser un almacén inmutable frente a acceso directo a la base de datos.
No incluir contraseñas, PIN, hashes ni secretos en `data`.

## Fase 1A: áreas, zonas y mesas

### Datos iniciales

Con el entorno virtual activado y las migraciones aplicadas:

```sh
python manage.py seed_bigparty_defaults
```

El comando crea únicamente **Sport Bar**, **Discoteca** y **Premium**, con identificadores
`sport-bar`, `discoteca` y `premium`, y órdenes 10, 20 y 30. Es idempotente y no crea
zonas ni mesas. Usa el identificador como clave estable y conserva los nombres,
descripciones, órdenes y estados ya configurados. Si un nombre inicial existe con
otro identificador, informa del conflicto y revierte la ejecución completa sin sobrescribir datos.
En esta Mac ya se ejecutó; volver a ejecutarlo no duplica registros.

### Modelos y reglas

- `venues.Area`: nombre e identificador únicos, descripción, activación, orden y fechas.
  Las áreas son registros editables, no una enumeración cerrada.
- `venues.Zone`: pertenece a un área; nombre e identificador únicos dentro de ella.
  Incluye descripción, activación, orden y fechas. Se pueden repetir nombres e
  identificadores en áreas distintas. No hay zonas predefinidas.
- `tables.VenueTable` (visible como **Mesa**): área obligatoria, zona opcional,
  nombre único por área, capacidad positiva, activación administrativa, estado operativo,
  opción de reserva web, orden, posición, tamaño, forma y fechas.

Todos se ordenan por `sort_order`, nombre y clave primaria. `save()` ejecuta `full_clean()`
para devolver `ValidationError` en las escrituras normales. Las unicidades, la capacidad,
los estados, las formas y los límites visuales también se protegen con constraints.
La unicidad de nombres utiliza la comparación exacta de PostgreSQL; no se normalizan
automáticamente mayúsculas ni acentos.

La zona de una mesa debe pertenecer a su misma área. Además de la validación Python,
la migración `tables.0002_table_zone_area_consistency` incorpora una
[clave foránea compuesta de PostgreSQL](https://www.postgresql.org/docs/17/ddl-constraints.html#DDL-CONSTRAINTS-FK)
de `(zone_id, area_id)` hacia `Zone(id, area_id)`. También protege escrituras masivas y
cambios de área de una zona. La migración incluye su operación inversa; no utiliza señales
ni triggers propios. Para trasladar una zona con mesas, primero debe resolverse explícitamente
la asignación de esas mesas; no se trasladan automáticamente.

Las relaciones a áreas y zonas utilizan `PROTECT`. El administrador no permite borrar
áreas, zonas ni mesas, ni siquiera sin dependencias: se cambia `is_active`. No existe un
soft-delete genérico. La eliminación directa por código de registros sin dependencias
sigue siendo posible para mantenimiento deliberado; las futuras relaciones con mesas
deberán proteger su historial.

### Activación, estado y reserva web

`is_active=False` deshabilita administrativamente el registro. En una mesa,
`operational_status=OUT_OF_SERVICE` significa **Fuera de servicio** temporalmente;
`ACTIVE` significa **Activa**. Son campos independientes. No se almacenan estados
de ocupación, reserva ni pago pendiente.

`reservable_web` es una preferencia independiente y tiene valor inicial `False`.
Una mesa puede existir internamente sin ofrecerse en la web. La preferencia por sí sola
no certifica disponibilidad: todavía no hay lógica de reservas ni filtros operativos.
Desactivar un área o una zona no altera automáticamente los registros hijos.

### Distribución visual

Cada área define un plano normalizado de **0 a 100**, independiente del monitor.
Los cuatro campos de layout son decimales con dos posiciones:

- `layout_x`, `layout_y`: esquina superior izquierda; valores iniciales `0.00`.
- `layout_width`, `layout_height`: porcentajes del ancho y alto del área; valor inicial `10.00`.
  Deben estar entre `0.01` y `100.00`.
- `x + width <= 100` y `y + height <= 100`: toda la mesa debe permanecer dentro del plano.
- `layout_shape`: `RECTANGLE` (**Rectangular**, valor inicial) o `CIRCLE` (**Circular**).

Las coordenadas siempre se refieren al área completa, incluso si hay zona asignada.
Las zonas agrupan mesas y no definen subplanos. No se impide que dos mesas se superpongan;
la colocación y las colisiones se decidirán al construir el editor visual.

### Servicios y auditoría explícita

`get_area_table_map(area)` devuelve un diccionario con `area`, `zones` y `tables`.
Incluye identificadores, orden, activación, zona de cada mesa, capacidad, estado,
preferencia web y `layout` (`x`, `y`, `width`, `height`, `shape`). Las listas están
ordenadas y las coordenadas se entregan como números serializables a JSON.
Incluye registros desactivados para configuración; no representa disponibilidad.
No contiene pedidos, importes, reservas ni pagos.

`update_table_configuration(table, actor=usuario, **cambios)` actualiza únicamente
los campos suministrados. Bloquea la fila, valida y guarda mesa y auditoría en una sola
transacción. Si falla el registro de auditoría, también se revierte el cambio de mesa.
El llamador debe verificar los permisos; el administrador ya lo hace antes de invocar el servicio.

Se registran estos eventos con usuario, identificador de mesa y valor anterior/nuevo:

- `table.out_of_service`: mesa marcada fuera de servicio.
- `table.reactivated`: vuelta al estado operativo activo.
- `table.capacity_changed`: cambio de capacidad.
- `table.reservable_web_changed`: cambio de la preferencia web.

Los cambios que conservan el mismo valor no crean eventos. La activación administrativa,
posición y demás campos no generan estos eventos sensibles. Las ediciones de mesas
desde el administrador utilizan el servicio. Escrituras directas mediante ORM o SQL
no generan auditoría automáticamente; las futuras operaciones deben utilizar este servicio.

### Administrador y comprobación de desarrollo

Áreas, zonas y mesas están disponibles en `/admin/`, con búsquedas y filtros propios.
Las mesas agrupan campos en **Información**, **Ubicación**, **Reservas**,
**Distribución visual** y **Estado**. Las posiciones se editan manualmente.
Los usuarios necesitan los permisos nativos de Django; el rol `GERENTE` no los concede por sí solo.

Con `DEBUG=True`, la ruta <http://127.0.0.1:8000/dev/mesas/> muestra los datos en una
tabla sencilla, incluidos registros desactivados y áreas todavía vacías. Requiere una
sesión autenticada y los tres permisos `venues.view_area`, `venues.view_zone` y
`tables.view_venuetable` (o ser superusuario). Para entrar mediante el login del
administrador se necesita también `is_staff=True`.

Con `DEBUG=False`, esa ruta no se registra y la vista rechaza además cualquier acceso
directo. No se ha creado API pública, mapa final, drag & drop ni JavaScript propio.

## Fase 1B: catálogo e inventario global

### Categorías y productos

```sh
python manage.py seed_catalog_defaults
```

Crea **Cervezas, Licores, Cócteles, Comida, Snacks y Combos**, en ese orden. No crea
productos, precios especiales ni existencias. Es idempotente, conserva las categorías
identificadas por su slug y revierte toda la ejecución ante conflictos de nombres.
Ya se ejecutó en esta Mac y se comprobó que repetirlo no duplica registros.

`Category` contiene nombre y slug únicos, descripción, orden, activación y fechas.
`Product` pertenece a una categoría protegida contra borrado y contiene nombre, slug
único, precio general, activación, visibilidad, control de inventario, existencias,
mínimo, preparación, imagen opcional, indicador de combo y fechas. Los productos
se ordenan por el orden de categoría, nombre y clave primaria. Los nombres no son
únicos; el identificador sí lo es.

`image` es opcional. El formulario de administración valida que el archivo sea una
imagen mediante Pillow; se guarda en `media/products/` y no se versiona. No hay
miniaturas ni procesamiento adicional. El catálogo funciona sin imágenes.

### Existencias globales y disponibilidad

Hay **un solo stock por producto**, compartido por Sport Bar, Discoteca y Premium.
No hay almacenes por área. `stock_quantity` y `minimum_stock` son enteros no negativos:
en esta fase se cuentan unidades completas, sin gramos, mililitros ni recetas.

- `track_inventory=False` es el valor inicial: no se restringe la disponibilidad por stock.
  Las existencias de estos productos permanecen en cero. Antes de quitar el control
  de inventario a un producto con existencias hay que ajustarlas a cero, con motivo e historial.
- `track_inventory=True`: solo está disponible cuando `stock_quantity > 0`.
- `visible_in_pos=False`: producto interno, no vendible directamente; puede ser
  componente de un combo, por ejemplo un insumo oculto.
- `is_low_stock`: control activado y existencias menores o iguales al mínimo.
- `is_out_of_stock`: control activado y existencias en cero.
- `is_available_for_sale` / `is_product_available`: exige producto y categoría activos,
  visibilidad y existencias suficientes. No existe parámetro ni permiso para forzar
  disponibilidad de un producto agotado. Para reponerlo se registra entrada o ajuste.

Los estados son derivados, no columnas duplicadas. Los avisos de stock bajo se muestran
en la vista de inventario; no se envían notificaciones externas. La activación de una
categoría afecta la disponibilidad, sin modificar físicamente sus productos.

### Preparación

`Product.PreparationRoute` admite `AREA_BAR` (**Barra del área**), `KITCHEN` (**Cocina**)
y `NONE` (**Sin preparación**, valor inicial). Se debe configurar explícitamente en cada
producto. No se guardan Barra 1/2/3 en el producto ni se configuran impresoras. El área
de la orden determina la barra; la Fase 1C genera comandas lógicas sin impresión física.

### Precios e historial

Los importes son decimales no negativos con dos posiciones, sin símbolo monetario
en la base. Las interfaces muestran quetzales (`Q`). `ProductAreaPrice` contiene un
precio opcional por pareja producto/área, con restricción de unicidad.
`get_product_price(product, area=None)` devuelve ese precio cuando existe y, si no,
el precio general. Un precio especial de cero también se respeta. No se generan
precios especiales automáticamente ni se suman componentes para calcular el precio del combo.

Escrituras soportadas en `apps/catalog/services.py`:

```python
update_base_price(product, "25.00", user=usuario)
update_area_price(product, area, "30.00", user=usuario)
```

Ambas verifican `catalog.change_product_price`, bloquean el producto y guardan el cambio,
`ProductPriceHistory` y `AuditLog` en una transacción. Usar `Decimal`, texto decimal o
enteros para los precios, evitando floats. Cambiar a un valor idéntico no duplica historial.

`ProductPriceHistory` registra producto, área opcional, precio anterior/nuevo, autor y fecha.
Área nula significa precio general. Al crear el primer precio especial, `old_price=None`
indica que no existía ese override; las modificaciones posteriores conservan su valor anterior.
El administrador usa los servicios también al crear un producto con precio inicial distinto
de cero. El historial es de solo lectura y no se puede borrar desde el administrador.
No se permite borrar ni reasignar un precio por área desde el administrador; la eliminación
auditada de un override queda fuera de esta fase.

### Modificadores

`ModifierGroup` pertenece a un producto y define nombre, selección `SINGLE` o `MULTIPLE`,
mínimo/máximo, orden, obligatoriedad y activación. `SINGLE` tiene máximo 1; `MULTIPLE`
permite varias opciones. Siempre se exige `0 <= mínimo <= máximo`, con máximo positivo.
Un grupo opcional tiene mínimo 0; uno obligatorio tiene mínimo al menos 1.

`ModifierOption` contiene grupo, nombre, precio adicional no negativo, orden y activación.
Las opciones se editan directamente o dentro del grupo en el administrador. No consumen
inventario y no tienen ingredientes asociados. En Fase 1C, las selecciones de la línea
se validan y su precio adicional se captura al agregar el producto.

### Combos

Un `Product` con `is_combo=True` tiene precio propio, pero no controla inventario ni tiene
existencias o mínimo propios. Crear primero el producto y después agregar sus
`ComboComponent` desde la sección de componentes del administrador.

Cada componente relaciona combo y producto con cantidad entera positiva y orden.
No se permite repetir el mismo componente, autoreferencia ni combos anidados.
También se impide convertir después un componente en combo, o quitar el indicador
de combo mientras mantenga componentes. Las validaciones se ejecutan en las escrituras
individuales; no usar `bulk_create`, `update` ni SQL directo para configurar estas relaciones.

`get_combo_max_available(combo)` calcula el mínimo de `stock // cantidad` entre los
componentes controlados. Devuelve 0 si falta stock, hay componentes desactivados,
el combo no es vendible o no tiene componentes. Devuelve `None` si todos los componentes
son sin control, indicando que no existe límite por stock. Los componentes ocultos
están permitidos; sus productos y categorías deben permanecer activos.

`is_combo_available(combo)` deriva la disponibilidad de ese cálculo. Por ejemplo,
10 botellas y 30 energizantes, requiriendo 1 y 4 respectivamente, permiten 7 combos.
Estas consultas no reservan ni descuentan stock. La Fase 1C consume los componentes
transaccionalmente al enviar el pedido.

`get_sellable_products(category=None, area=None)` devuelve una lista ordenada de productos
vendibles. Filtra categoría cuando se solicita; el área es contexto para resolver precios,
nunca un inventario separado. El precio se obtiene con `get_product_price`.

### Movimientos y concurrencia

Los servicios de `apps/inventory/services.py` son la vía soportada para modificar stock:

```python
receive_stock(product, 12, user=usuario, reason="Compra")
adjust_stock(product, -2, user=usuario, reason="Rotura")
```

La entrada requiere entero positivo; el ajuste, un delta entero distinto de cero y motivo
no vacío. Ambos exigen un producto con inventario propio y verifican su permiso específico.
No aceptan unidades fraccionadas, combos ni existencias finales negativas.

Cada operación usa `transaction.atomic` y `select_for_update`, vuelve a leer el stock
persistido y guarda existencias, movimiento y auditoría en la misma transacción. Un fallo
de historial o auditoría revierte todo. Las pruebas utilizan conexiones PostgreSQL
independientes para comprobar entradas simultáneas y ajustes que compiten por el último stock.

`InventoryMovement` contiene producto, tipo (`RECEIPT` / **Entrada**, `ADJUSTMENT` / **Ajuste**),
delta, existencias anteriores y posteriores, motivo, usuario, fecha y JSON adicional.
La base comprueba el balance y los tipos/cantidades válidos. Los movimientos no se editan,
añaden manualmente ni borran desde el administrador. La Fase 1C añade consumo enviado
y devolución por anulación; no hay reembolsos de dinero. Escribir stock o precios directamente por ORM/SQL omite el historial y
no forma parte de la capa soportada.

### Administración, permisos y vistas de desarrollo

El producto agrupa **Información, Precio, Inventario, Preparación, Visual y Estado**.
El stock siempre es de solo lectura y todo producto creado desde el administrador
comienza en cero. Los precios por área tienen su propia administración con historial.

Los permisos se conceden individualmente o por grupos Django; ningún rol los recibe
automáticamente:

| Permiso | Uso |
| --- | --- |
| `catalog.change_product_price` | Cambiar precios mediante servicios y administrador |
| `inventory.view_inventory` | Consultar inventario global |
| `inventory.receive_inventory` | Registrar entradas |
| `inventory.adjust_inventory` | Registrar ajustes |

El administrador requiere además sus permisos nativos de añadir/cambiar/consultar cada
modelo; para consultar movimientos requiere `inventory.view_inventory` y el permiso
nativo de consulta. Un permiso de cambio de producto no habilita por sí solo cambiar precios.

- <http://127.0.0.1:8000/dev/catalogo/>: categorías, todos los productos (incluidos internos),
  precios generales/especiales al seleccionar área, stock, mínimo, disponibilidad,
  preparación y combos. Requiere `catalog.view_product`.
- <http://127.0.0.1:8000/dev/inventario/>: productos normales e insumos, con estados
  **Disponible**, **Stock bajo**, **Agotado** o **Sin control**. Los combos se consultan
  en catálogo. Requiere `inventory.view_inventory`; el formulario de movimientos
  muestra solo las operaciones autorizadas. Revalida permisos al enviar, exige CSRF
  y redirige tras registrar para evitar repetir el movimiento al recargar la página.

Ambas rutas requieren usuario activo con `is_staff=True`, sesión y `DEBUG=True`.
Con `DEBUG=False` no se registran y también se bloquean en la vista. Comparten únicamente
la comprobación transversal de acceso en `apps/core/mixins.py`; no se alteró la vista de mesas.

## Fase 1C: cuentas de mesa, subcuentas y órdenes

### Modelos e integridad

- `TableOrder`: mesa principal obligatoria, área de origen, responsable, usuario de apertura,
  estado, modalidad, nota general, fechas y referencia `merged_into` al unirla a otra cuenta.
  El número visible `order_number` formatea su ID PostgreSQL con un mínimo de seis dígitos
  (`000187`); no calcula `max(id)+1`. Puede haber saltos si se revierte una transacción.
- `OrderTableLink`: relación M2M de cuentas y mesas, con fechas de vinculación y liberación.
  Una única `primary_table` identifica la principal; `link.is_primary` se deriva de ella.
  Los vínculos liberados se conservan como historial, por lo que `order.tables` también los
  incluye. Para mesas actualmente vinculadas, consultar `table_links` con `released_at=None`.
- `SubAccount`: cuenta, nombre, estado y fechas. Los nombres pueden repetirse; no hay
  numeración automática ni datos personales adicionales.
- `OrderLine`: cuenta, subcuenta opcional, producto, cantidad, precios capturados,
  nota, estado, autor y fechas. Conserva nombre y condición de combo originales.
  `source_line` identifica el origen cuando se divide una línea entre subcuentas.
- `OrderLineModifier`: opción seleccionada y snapshots de nombre y precio adicional.
- `OrderLineComponent`: producto físico, unidades por unidad de línea, nombre y ruta
  capturados; marca si se descontó stock. También existe para productos normales.
  Permite enviar y devolver exactamente la composición capturada, aunque cambie el combo.
- `PreparationTicket` / `PreparationTicketItem`: cabecera, secuencia y detalles inmutables
  de preparación, con mesa, descripción, nota, cantidad, ruta y área de origen capturadas.
- `OrderActivity`: historial operativo con usuario, tipo, descripción, metadatos y fecha.
  Conserva `origin_order` al trasladar el historial a una cuenta unificada.

La base impide dos cuentas activas con la misma mesa principal y dos vínculos vigentes
para una misma mesa. Una FK compuesta diferida exige que la principal tenga un vínculo
con su cuenta; el FK obligatorio garantiza exactamente una principal. Otra FK compuesta
impide asignar una línea a una subcuenta de otra orden. Ambas se verifican al confirmar
la transacción, permitiendo abrir y unir cuentas atómicamente.

Todos los modelos operativos se administran mediante servicios. El administrador es
de solo lectura, incluso para superusuarios; no hay edición libre de precios, estados,
responsable, vínculos ni historiales. Los FK usan `PROTECT` para conservar trazabilidad.

### Apertura y modalidades

`open_table_order(table, user, responsible_waiter=None, billing_mode="SINGLE", general_note="")`
exige y captura la jornada abierta desde Fase 1E, bloquea la mesa, verifica que ella y su área estén activas, que esté en servicio y libre,
y crea la cuenta `OPEN`. El responsable puede diferir del usuario que la abre.
Otros usuarios con permisos pueden operar la misma cuenta; no se restringe al responsable.
La transferencia formal de responsable no está implementada.

Estados preparados: `OPEN`, `PARTIALLY_PAID`, `PAYMENT_PENDING`, `CLOSED`, `CANCELLED`
y `MERGED`. Los tres primeros son activos. La Fase 1D incorpora cobro y cierre mediante `payments`;
el cierre libera los vínculos vigentes dentro de la misma transacción.

`SINGLE` mantiene todas las líneas sin subcuenta. `SPLIT` permite crear subcuentas con
`create_subaccount(order, name, user)` y también mantener líneas **Sin subcuenta**;
estas siguen incluidas en el total de la orden. No se inventan nombres al abrir o unir
cuentas. Una subcuenta cerrada no admite nuevas líneas, envíos ni traslados.

`change_billing_mode(order, billing_mode, user)` solo admite una cuenta sin líneas ni
subcuentas. La unión de cuentas es el otro servicio que puede promover explícitamente
la modalidad a `SPLIT`. No hay cambio arbitrario mediante formularios de administración.

### Agregar y corregir productos

```python
add_product_to_order(order, product, 2, user, subaccount=None,
                     modifier_option_ids=[opcion.pk], notes="Sin salsa")
```

Valida producto vendible, cantidad entera positiva, subcuenta, pertenencia/activación
de modificadores y límites de sus grupos. El servidor consulta `get_product_price` con
el área de origen de la orden; no recibe precios desde el cliente.
`base_unit_price` captura ese precio y `unit_price` incluye los extras. El subtotal se
deriva de `quantity * unit_price`; cambios posteriores del catálogo no alteran la línea.

Agregar crea `DRAFT` y **no reserva ni descuenta stock**. Los borradores pueden competir
por las mismas existencias; la validación conjunta y definitiva ocurre al enviar.
Toques repetidos se agrupan solo si coinciden producto, subcuenta, nota, precio,
snapshots de modificadores y composición. Una línea `SENT` nunca recibe nuevas unidades;
una adición posterior crea un borrador nuevo.

Servicios de corrección: `increase_draft_line(line, user, quantity=1)`,
`decrease_draft_line(line, user, quantity=1)`, `remove_draft_line(line, user)` y
`update_draft_line_note(line, notes, user)`. Al retirar todas las unidades, se conserva
la línea como `CANCELLED`, sin stock ni comanda: así no se pierde su historial, incluidos
traslados previos. No se guardan líneas con cantidad cero ni se borran líneas enviadas.

### Envío y comandas lógicas

`send_order(order, user)` bloquea la cuenta y todos los productos involucrados en orden
de ID. Procesa exclusivamente sus borradores, revalida actividad y stock, agrega las
necesidades compartidas entre líneas/componentes y confirma todo en una transacción.
Si cualquier producto resulta insuficiente, no se envía ni se descuenta ninguna línea.
Repetir el envío sin borradores no crea movimientos ni comandas.

Los productos normales consumen su cantidad; un combo consume cada componente capturado
por cantidad de línea. Los productos sin control no generan movimiento de stock.
Los extras no consumen inventario. `InventoryMovement.SALE` significa **consumo enviado**,
no pago recibido, y registra `order_id`, `line_id` y la mesa en `metadata`.

Se crea una comanda lógica por acción con detalles de todas sus rutas: `AREA_BAR`
con el área de origen y `KITCHEN` para cocina compartida. `NONE` no genera detalle;
si todas las rutas son `NONE`, el envío queda en historial sin crear una comanda vacía.
Los combos siguen siendo una sola línea del cliente y se desglosan solo en sus detalles
de preparación. `get_line_combo_components(line)` expone su composición capturada.

Tipos de comanda: `NEW`, `ADDITION`, `CANCELLATION`, `UPDATE`. La secuencia aumenta por
cuenta bajo bloqueo de su fila, con unicidad en la base. El estado `CREATED` significa
registrada lógicamente; no implica impresión ni entrega. Los snapshots anteriores
no se modifican al trasladar mesas, dividir líneas o actualizar notas.

`update_sent_line_note(line, notes, user)` registra el antes/después y genera `UPDATE`
para las rutas de preparación, sin afectar stock. `update_order_note(order, note, user)`
registra cambios de la nota general de la mesa.

### Anulación y devolución

`cancel_sent_line(line, user, reason)` exige motivo y `orders.cancel_sent_order_line`.
No basta el rol de Cajero/Gerente. Marca `CANCELLED`, genera comanda `CANCELLATION`
cuando hay preparación y devuelve el stock realmente descontado mediante
`CANCELLATION_RETURN`. La operación, su actividad y auditoría son atómicas.
Una segunda anulación no devuelve stock otra vez.

**Decisión de esta fase:** toda anulación de una línea enviada devuelve stock, sin distinguir
si físicamente ya se preparó/consumió. Esa distinción permanece pendiente para cancelaciones operativas;
la Fase 1D incorpora reembolsos separados con devolución física opcional. No se permite desactivar el control de inventario ni convertir en combo
un producto con consumo enviado neto sin reintegrar: evitaría cumplir su posible devolución.

### Subcuentas, traslado de mesa y unión

`move_line_to_subaccount(line, destination, user, quantity=None)` admite traslado completo
o parcial dentro de una cuenta `SPLIT`, con origen/destino abiertos. Conserva todos los
snapshots y precios. Al dividir una línea enviada copia su composición y trazabilidad;
no descuenta stock otra vez ni modifica comandas antiguas. Cada parte puede anularse
posteriormente devolviendo solo su cantidad.

`move_order_to_table(order, destination_table, user)` mueve una cuenta de **una sola mesa**
a otra libre y operativa de la misma área. Libera el vínculo anterior y conserva sus
comandas. Nuevos envíos capturan la mesa destino. El traslado de grupos ya unidos se
rechaza: no se adopta una regla física que pueda deshacer implícitamente su unión.

`join_table_to_order(order, table, user)` agrega una mesa libre de la misma área a la
cuenta; todas sus mesas resuelven la misma orden y siguen físicamente ocupadas.

`merge_orders(primary_order, secondary_order, user)` une dos cuentas activas de la misma
área, sin subcuentas cerradas. Conserva la responsable de la principal, traslada líneas,
subcuentas e historial, incorpora la nota secundaria con su número de origen y vincula
sus mesas. La secundaria permanece como `MERGED` con `merged_into`; no se borra.
Si cualquiera usa `SPLIT`, la resultante también; las líneas sin subcuenta permanecen así.

Las comandas originales conservan cuenta y secuencia de origen; no se renumeran,
reimprimen ni generan consumos nuevos por la unión. `get_order_tickets(primary)` incluye
las comandas heredadas de sus líneas. Las nuevas comandas usan la secuencia de la cuenta
principal. No existe servicio para deshacer una unión.

### Consultas, totales y permisos

`get_active_order_for_table` resuelve cualquiera de las mesas vinculadas.
`get_operational_table_state` deriva `OUT_OF_SERVICE`, `OCCUPIED` o `AVAILABLE`, sin
agregar columnas de ocupación a `VenueTable`.

`get_order_draft_lines` / `get_order_sent_lines` consultan estados y permiten filtrar una
subcuenta; omitirla devuelve todas las líneas de ese estado. `get_order_timeline` devuelve
actividad de más reciente a más antigua, conservando autor y cuenta original tras uniones.

Los totales son decimales derivados, nunca campos duplicados:

- `get_order_pending_total`: solo `DRAFT`.
- `get_order_committed_total`: solo `SENT`.
- `get_order_grand_total` / `get_order_total`: ambos; excluyen `CANCELLED`.
- `get_subaccount_pending_total`, `get_subaccount_committed_total`,
  `get_subaccount_grand_total` / `get_subaccount_total`: equivalentes por subcuenta.

Permisos específicos, sin asignación automática por rol:
`open_table_order`, `add_order_line`, `send_order`, `cancel_sent_order_line`,
`move_order_table`, `merge_orders`, `manage_subaccounts`, todos bajo `orders`.
`add_order_line` también permite corregir borradores y notas; `manage_subaccounts`
permite mover líneas y cambiar modalidad de una cuenta vacía. Enviar/anular consume/devuelve
stock por su permiso operativo, sin exigir permisos de ajustes manuales de inventario.

### Comprobación de desarrollo

<http://127.0.0.1:8000/dev/ordenes/> permite abrir una mesa, crear subcuentas, agregar
productos con modificadores, enviar y consultar líneas, totales, comandas e historial.
Requiere `DEBUG=True`, usuario staff activo, `orders.view_tableorder` y el permiso de
cada operación. Usa POST con CSRF; el backend verifica permisos y precios.
Traslados, uniones, correcciones y anulaciones están disponibles por servicios, sin
construir todavía una interfaz operativa final. No se agregó API pública ni DRF.

Para actualizar otra copia existente:

```sh
python manage.py migrate
python manage.py check
python manage.py test
```

Migraciones nuevas: `inventory.0002_order_consumption`, `orders.0001_initial` y
`orders.0002_relational_integrity`. No se modificaron migraciones históricas ni se
crearon órdenes, mesas o productos de demostración en la base local.

## Fase 1D: pagos, división de pago y liquidación

### Registros y asignaciones por unidad

`apps/payments` añade `Payment`, `PaymentAllocation`, `OrderAdjustment`,
`AdjustmentAllocation`, `PaymentRefund` y `RefundAllocation`. Todos los importes son
`Decimal` con dos decimales; los servicios rechazan floats, valores no finitos,
importes no positivos y más de dos decimales. No hay dependencias nuevas.

`Payment` representa dinero y conserva cuenta, subcuenta opcional, método, estado,
monto original, usuario de registro, usuario/fecha de confirmación, referencia,
notas y metadatos. No guarda precios recibidos del cliente.

Cada `PaymentAllocation` identifica una línea y **una posición de unidad física**
(`unit_number`, de 1 a `OrderLine.quantity`), con el monto aplicado. Seleccionar dos
cervezas genera dos asignaciones, cada una con `quantity=1`; un pago por monto genera
asignaciones con `quantity=None`. Esto significa cobertura monetaria, no fracciones
físicas del producto. Las asignaciones de descuentos usan la misma estructura.
La combinación cabecera/línea/unidad es única dentro de cada pago o ajuste.

La distribución por monto recorre líneas por ID y unidades de menor a mayor.
Ejemplo: una cerveza Q25 puede tener Q10.13 en efectivo y Q14.87 en tarjeta,
sin cambiar su cantidad ni su precio. Las cantidades pagadas se derivan sumando
cobertura por unidad; no se suman columnas `quantity` de pagos por monto.
`get_line_payment_quantities(line)` expone unidades completas cubiertas, unidades
con verificación pendiente, unidades con saldo, cobertura parcial e importes por unidad.
Los conteos de cobertura parcial y pendiente pueden referirse a la misma unidad.

Solo se cobra `SENT`. Los precios provienen de `OrderLine.unit_price`, incluidos
los modificadores capturados; `DRAFT` y `CANCELLED` no crean cargos financieros.
Los totales operativos de `orders` siguen incluyendo borradores cuando corresponde;
para cobros se usan exclusivamente las consultas de `payments`.

### Servicios de pago y saldos

Los siguientes servicios reciben `target` como `TableOrder` o `SubAccount`:

```python
from decimal import Decimal
from apps.payments import services as payments

payments.create_selected_payment(order,
    [{"line_id": linea.pk, "quantity": 2}], "CASH", user)
payments.create_amount_payment(order, Decimal("200.00"), "CASH", user)
payments.pay_full_balance(order, "CARD", user, card_approved=True)
payments.pay_cash(order, Decimal("85.00"), user, received_amount=Decimal("100.00"))
```

Son alternativas de uso, no una secuencia obligatoria. `pay_full_balance` calcula el
saldo **disponible no reservado** desde el servidor. Los servicios aceptan
`reference`, `notes`, `received_amount` y `card_approved` cuando corresponde.
La selección de artículos escoge unidades sin pagos confirmados ni pendientes, en
orden de posición. Si una unidad tiene cobertura monetaria parcial, se completa
con pago por monto o saldo total. Un descuento previo reduce el monto pagable de esa unidad.

En `SINGLE`, `Payment.subaccount` siempre es nula. En `SPLIT` se puede cobrar una
subcuenta específica o la cuenta completa, incluidas líneas sin subcuenta. Un cobro
por subcuenta jamás puede seleccionar líneas de otra. Los saldos por subcuenta se
calculan desde las asignaciones, también cuando el pago se registró para toda la cuenta.

Consultas de orden y sus equivalentes `get_subaccount_*`:

| Consulta | Significado |
| --- | --- |
| `get_order_charge_total` | Consumo enviado menos descuentos/cortesías y créditos por reembolso |
| `get_order_confirmed_paid_total` | Dinero confirmado menos reembolsos |
| `get_order_pending_payment_total` | Dinero registrado pendiente de verificación |
| `get_order_balance` | Cargo neto menos dinero confirmado neto |

`get_financial_summary(target)` añade bruto, ajustes, reembolsos y
`available_to_pay = outstanding_balance - pending_verification`.
Un pago pendiente no reduce el saldo confirmado; **reserva** la cobertura de sus
unidades para impedir que otro pago o descuento la use. Rechazarlo libera esa reserva.

### Métodos, verificación y efectivo por entregar

- `CASH`: confirmado inmediatamente. Si se indica `received_amount`, debe alcanzar
  el pago. Se conserva en metadatos; `payment.change_due` devuelve el cambio.
  Pago Q85, recibido Q100 y cambio Q15 registra únicamente Q85 de ingreso.
- `CARD`: requiere `card_approved=True`, declaración del operador de que la terminal
  externa aprobó el cobro. No se solicitan banco, voucher, autorización ni datos de tarjeta.
- `TRANSFER` y `DEPOSIT`: referencia obligatoria e inicio `PENDING`.
  `confirm_pending_payment(payment, user)` confirma con actor y fecha;
  `reject_pending_payment(payment, user, reason)` exige motivo y conserva el pago rechazado.
  No hay integración bancaria ni envío real de dinero.

Pago mixto significa varios `Payment`: por ejemplo Q200 en efectivo + Q300 en tarjeta.
No existe `MixedPayment`. Los métodos son `TextChoices`; se podrán habilitar o
inhabilitar en una fase posterior, sin crear ahora configuración de caja.

`recorded_by` identifica quién cobró. Desde Fase 1E, efectivo registrado sin sesión por
rol `MESERO` queda `PENDING` y genera una entrega pendiente. Un cobro con `cash_session`
explícita queda `NOT_REQUIRED` y crea su entrada física. Otros roles requieren esa sesión.
`confirm_cash_handoff` registra la recepción y cambia la entrega a `DELIVERED`.
Siempre se requiere `payments.record_payment`; el rol no concede permisos automáticamente.
Los reembolsos permanecen separados de la entrada original. Ver las reglas de caja abajo.

### Estados y cierre

`refresh_order_payment_status(order)` deriva `PAYMENT_PENDING` si hay pagos pendientes,
`PARTIALLY_PAID` si existe pago confirmado/reembolsado y, en otro caso, `OPEN`.
Una cuenta pagada completamente permanece activa hasta su cierre explícito; el estado
`PARTIALLY_PAID` se utiliza también en ese intervalo, y el saldo Q0 indica liquidación.
La variante con `user` permite registrar cierres derivados de subcuentas.
Nunca reabre una cuenta o subcuenta cerrada.

Las operaciones financieras cierran automáticamente subcuentas con consumo cuando
su saldo es cero, no hay verificación pendiente y no existen borradores. Se registra
`closed_at` y actividad. Retirar el último borrador, anular una línea sin historial
financiero o trasladar el saldo no pagado también recalcula este cierre. Una nueva
consumición de la misma persona requiere otra subcuenta.

`can_close_order(order)` indica si `close_order(order, user)` puede completar el cierre.
El cierre explícito exige ausencia de borradores, saldo cero, ningún pago pendiente
e integridad entre cabeceras/asignaciones. Cierra las subcuentas restantes vacías o
con importe cero dentro de la misma transacción, y verifica las condiciones antes de
marcar `CLOSED`. Libera todos los vínculos vigentes: cualquiera de sus mesas vuelve a
estar disponible y puede abrir una cuenta nueva. No elimina vínculos históricos.

### Descuentos y cortesías

```python
payments.apply_order_adjustment(order, user,
    amount=Decimal("10.00"), reason="Promoción autorizada")
payments.apply_order_adjustment(subaccount, user, adjustment_type="COURTESY",
    selection=[{"line_id": linea.pk, "quantity": 1}], reason="Atención al cliente")
```

Requieren `apply_order_adjustment` y motivo; un rol de Gerente por sí solo no autoriza.
El permiso debe concederse solo a las personas autorizadas. Se guarda el importe
resultante y su distribución exacta; no se altera `unit_price`, no se crea un pago y
no se reintegra inventario. Un ajuste no puede superar el saldo libre de pagos y reservas.
No hay edición ni eliminación de ajustes desde el administrador.

### Reembolsos y devolución física

```python
payments.refund_payment(payment, user, amount=Decimal("10.00"),
    reason="Compensación autorizada")
payments.refund_payment(payment, user, allocation_ids=[allocation.pk],
    return_to_inventory=True, reason="Producto devuelto intacto")
```

Exigen `refund_payment`, motivo y pago confirmado. Se conserva cada reembolso y sus
asignaciones al pago original. La suma jamás puede superar lo cobrado neto disponible.
Un reembolso parcial mantiene `CONFIRMED`; al devolver todo el pago queda `REFUNDED`.

**Decisión financiera:** cada reembolso representa también una reducción comercial del
cargo por el mismo importe. Los informes muestran separadamente consumo bruto,
descuentos/cortesías, reembolsos, cargo neto y dinero neto recibido. Devolver Q10 de un
consumo pagado de Q25 deja cargo neto Q15, cobrado neto Q15 y saldo Q0. No genera una
nueva deuda ni reabre subcuentas; se admite después del cierre de la orden. No existe
un flujo de reversión para volver a cobrar ese mismo importe en esta fase.

Un reembolso por monto se distribuye contra asignaciones originales en orden estable
y **obliga `return_to_inventory=False`**. No supone devolución física.
La devolución de inventario exige asignaciones de unidades completas pagadas íntegramente
por ese pago, sin reembolsos anteriores sobre la unidad. Puede incluir descuentos previos:
se devuelve solo el dinero efectivamente pagado y la unidad física completa.
Una unidad cuyo pago se dividió entre varios pagos solo admite reembolso monetario en
esta fase; la devolución física conjunta requeriría un flujo adicional coordinado.

Si se autoriza la devolución física, se reintegran únicamente los componentes cuya
línea capturó `stock_deducted=True`, usando su composición original y creando
`InventoryMovement.REFUND_RETURN` con cuenta, línea, pago, reembolso y unidad.
Productos sin control no generan movimiento. Bloqueos y asignaciones impiden devolver
stock dos veces. La protección del catálogo considera también estas devoluciones.

La cancelación operativa de `orders` sigue siendo independiente y devuelve stock según
la regla de la Fase 1C. Una línea con cualquier asignación financiera, incluso de pago
rechazado, no puede anularse ni moverse entre subcuentas: se conserva la relación histórica.
Rechazar un pago sí permite cobrar de nuevo sus unidades. Una cuenta con historial
financiero no puede fusionarse con otra; la unión debe hacerse antes de cobrar o ajustar.
El traslado físico de una cuenta a una mesa libre de su misma área continúa permitido.

### Integridad, auditoría y acceso

Las escrituras financieras bloquean `TableOrder` con `select_for_update`
(desde Fase 1E, después de la barrera de jornada) y se confirman
mediante `transaction.atomic`; comparten ese bloqueo con las operaciones de `orders`.
Verificar/rechazar/reembolsar bloquea después el pago; devolver stock bloquea productos
por ID. Esto serializa cobros, reservas, ajustes, cierres, anulaciones y devoluciones.
Se comprueban montos de cabecera contra detalles y cobertura de cada unidad, además de
restricciones de base para importes positivos, tipos, confirmación, entrega de efectivo
y unicidad de asignaciones. No se soportan escrituras financieras directas por ORM/SQL.

Permisos individuales, sin asignación automática por rol:
`record_payment`, `verify_transfer_payment`, `reject_transfer_payment`,
`apply_order_adjustment`, `refund_payment`, `close_order`, bajo `payments`.

Cada operación crea `OrderActivity` y `AuditLog`: `PAYMENT_RECORDED`,
`PAYMENT_CONFIRMED`, `PAYMENT_REJECTED`, `ADJUSTMENT_APPLIED`, `REFUND` y `CLOSED`.
Los seis modelos financieros son de solo lectura en el administrador, incluso para
superusuarios. Los servicios son la única entrada soportada para cambios.

`get_payment_history(order)` devuelve pagos cronológicos con método, importe original,
estado, autores, referencia, fechas y relación de reembolsos.
`get_receipt_data(order_or_subaccount)` devuelve datos para futura impresión: mesas,
número de orden, líneas y precios capturados, cobertura, ajustes, pagos, reembolsos,
totales netos y fecha. Conserva `Decimal`; el consumidor puede serializarlo con
`DjangoJSONEncoder`. No genera PDF ni imprime. Para subcuentas incluye el importe
aplicado a esa subcuenta y el importe original completo del pago por separado.

### Vista de desarrollo y migraciones

<http://127.0.0.1:8000/dev/pagos/> permite seleccionar orden, consultar saldos y
subcuentas, pagar todo el saldo disponible, un monto o artículos seleccionados,
registrar los cuatro métodos, confirmar/rechazar pendientes y cerrar la orden.
La selección de artículos usa un campo JSON sencillo solo para esta herramienta dev.
Requiere sesión, staff activo, `DEBUG=True`, `payments.view_payment`, permiso de cada
operación y CSRF. El backend calcula los precios y verifica pertenencia de subcuentas.
Descuentos y reembolsos se prueban mediante servicios; no hay interfaz final.

Migraciones nuevas: `orders.0003_alter_orderactivity_activity_type`,
`inventory.0003_refund_return` y `payments.0001_initial`. No se editaron migraciones
anteriores, no se reinició la base y no se insertaron pagos ni consumos de demostración.
Para otra copia existente: ejecutar `python manage.py migrate` antes de utilizarla.

## Fase 1E: caja física y cierre de jornada

### Modelos y configuración inicial

`apps/cash` contiene:

- `CashRegister`: estación física con nombre, código único y área obligatoria. No usa
  hostname ni IP. Su código/área no se cambian después de tener sesiones, y una caja
  con sesión abierta no se puede desactivar mediante las operaciones soportadas.
- `CashSession`: jornada, estación, cajero, actor de apertura, fondo inicial, fechas,
  estado `OPEN`/`CLOSED`, conteo/autor/fecha, esperado congelado, diferencia, motivo y
  autor de cierre. Solo admite una sesión abierta simultánea por estación.
- `CashHandoff`: un registro por pago de efectivo de mesero. Conserva mesero, monto,
  estado `PENDING`/`DELIVERED` y, solo cuando se recibe, sesión, receptor y fecha.
- `CashMovement`: entrada/salida física, monto positivo, sesión, solicitante/autor,
  aprobador si corresponde y referencias al pago, entrega o reembolso original.
- `BusinessDay`: fecha comercial, estado, apertura/cierre y última reapertura.
  Solo puede existir una jornada abierta en todo el establecimiento.
- `BusinessDayReopen`: historial de cada reapertura con motivo, actor, fecha y datos
  del cierre anterior. No se sobrescribe el historial al reabrir varias veces.

Después de aplicar migraciones, el comando idempotente:

```sh
python manage.py seed_cash_defaults
```

crea `Caja Sport Bar` (`SPORT`), `Caja Discoteca` (`DISCO`) y `Caja Premium` (`PREMIUM`)
usando las áreas existentes por sus slugs. No crea áreas ni modifica configuración
existente. Si faltan áreas o un código corresponde a otra área, falla sin cambios parciales.
Puede ejecutarse después de `seed_bigparty_defaults` en una instalación nueva.
No abre una jornada ni sesiones, ni inserta movimientos de demostración.

### Jornada explícita y operación después de medianoche

```python
from datetime import date
from decimal import Decimal
from apps.cash import services as cash

# Ejemplos de apertura, ejecutados por el usuario autorizado.
day = cash.open_business_day(user, business_date=date(2026, 9, 27))
session = cash.open_cash_session(register, cashier, Decimal("500.00"), user)
```

La fecha comercial identifica la jornada completa: abrir el 27 por la noche y cerrar
el 28 por la madrugada no cambia su pertenencia ni provoca cierre automático.
Cada sesión pertenece explícitamente a una jornada; cada orden nueva captura la
jornada abierta en `TableOrder.business_day`. Desde esta fase no se pueden abrir
mesas, enviar consumos ni registrar operaciones financieras sin jornada abierta.

La FK es nullable **solo para conservar órdenes históricas**, sin inferir sus jornadas
por fechas. No se asignaron jornadas retrospectivamente en la migración.
`assign_legacy_order_to_day(order, day, user, reason)` permite regularización explícita,
con permiso `open_business_day`, motivo y auditoría; no permite reasignar una cuenta
que ya tiene jornada. Reconstruye únicamente entregas pendientes que se puedan derivar
de pagos CASH confirmados; no inventa recepciones físicas. Los cobros directos históricos
requieren una vinculación física explícita si se incorporan a una jornada operativa.
Los pendientes históricos sin jornada aparecen como bloqueadores de cierre.

Una jornada cerrada bloquea nuevas mutaciones de sus órdenes, pagos y cajas. Para
corregirla o reembolsar una cuenta de esa jornada debe reabrirse con autorización.
No se puede reabrir mientras otra jornada esté abierta. Las sesiones ya cerradas
permanecen inmutables; si se necesita mover efectivo tras reabrir, se abre una nueva
sesión de esa jornada. No hay reasignación de ventas ni movimientos entre jornadas.

### Fondo inicial y cobros directos

El fondo inicial es efectivo físico disponible, **no venta ni ingreso comercial**.
Puede ser cero. Abrir una sesión exige caja/área y cajero activos, permiso de apertura
y ausencia de otra sesión abierta de esa estación. Diferentes estaciones pueden tener
sesiones abiertas; después de cerrar una, la misma estación admite otro turno.

Los servicios de pagos aceptan ahora `cash_session` explícito:

```python
from apps.payments import services as payments

payment = payments.pay_full_balance(order, "CASH", cashier, cash_session=session)
# También disponible en create_amount_payment, create_selected_payment y pay_cash.
```

El cobro directo valida que el usuario sea el cajero de la sesión (o superusuario),
que la sesión esté abierta, sin conteo presentado, y pertenezca a la jornada de la cuenta.
En la misma transacción se crea `Payment` y un único `DIRECT_CASH_PAYMENT` por su monto.
El cambio entregado no aumenta ese monto. `cash_handoff_status` queda `NOT_REQUIRED`.
Si falla la recepción física, también se revierte el pago y sus asignaciones.

`record_direct_cash_payment(payment, session, user)` es idempotente para el mismo pago
y sesión: devuelve el movimiento existente. Otra sesión no puede apropiárselo. Esto
protege la recepción del mismo Payment; no sustituye un futuro identificador de solicitud
para reintentos de crear pagos distintos desde clientes offline.

No se añadió una segunda entidad de pago ni una FK redundante en `Payment`: la relación
física con la sesión está en `CashMovement`, con unicidad de entrada por pago.
Un usuario que cobra sin sesión debe tener rol base `MESERO` y permiso de registrar pagos;
otros roles deben proporcionar sesión explícita. Proporcionar sesión expresa contexto
físico de caja, incluso si la persona asignada a ella tiene otro rol base.

### Efectivo de meseros y recepción

Un pago CASH de mesero sin sesión queda confirmado financieramente y crea un
`CashHandoff PENDING`. Todavía no afecta el efectivo esperado de ninguna caja.
`get_pending_cash_handoffs(day=None, waiter=None)` lista mesero, pago/cuenta/mesa,
monto y fecha, con filtros opcionales; la pantalla no añade un total agregado.

```python
cash.confirm_cash_handoff(payment, session, cashier)
# También acepta el CashHandoff como primer argumento.
```

Exige `receive_waiter_cash`, pago CASH confirmado y pendiente de entrega, y una caja
abierta/activa de la misma jornada sin conteo presentado. Guarda sesión, receptor, hora,
mesero, monto, mesa/cuenta y un movimiento `WAITER_HANDOFF`. No crea otro pago ni otra venta.
Un segundo intento de confirmar la entrega se rechaza.

Se conservan `Payment.cash_handoff_status` y `CashHandoff.status` por compatibilidad,
sincronizados en la misma transacción. La entrega pendiente no tiene sesión asignada.
Por eso no bloquea el cierre individual de una caja que nunca recibió ese dinero,
pero sí bloquea el cierre de su jornada. Una entrega recibida sin movimiento coherente
impide cerrar su caja o jornada.

### Retiros y reembolsos físicos

```python
cash.create_cash_withdrawal(session, Decimal("100.00"), "Depósito en bóveda",
                            requested_by=waiter, approved_by=manager)
cash.record_cash_refund(refund, session, cashier)
```

El retiro requiere monto positivo, motivo, solicitante activo y aprobador con
`approve_cash_withdrawal`. El aprobador es el actor autenticado que ejecuta la operación;
la vista no acepta otro aprobador enviado desde el formulario. Guarda ambos usuarios
y fecha, reduce efectivo físico y no altera ventas. No puede dejar esperado negativo.

`record_cash_refund` registra exclusivamente la **salida física** de un `PaymentRefund`
existente cuyo pago original fue CASH. Requiere `record_cash_refund`, sesión abierta
no contada de la misma jornada y fondos suficientes. Crea un `CASH_REFUND` único por
reembolso; repetirlo en la misma sesión devuelve el movimiento, otra sesión se rechaza.
No vuelve a crear el reembolso financiero ni devuelve inventario otra vez.

El reembolso financiero y su eventual devolución de stock siguen en `payments`.
No generan automáticamente movimientos de caja: si la devolución de dinero ocurre
fuera de esa caja física, no se inventa una salida en ella. Los informes distinguen
reembolsos financieros y salidas físicas por reembolso.

**Regla de coherencia añadida:** el efectivo pendiente de un mesero debe entregarse
antes de reembolsar su pago. Así no queda un pago totalmente `REFUNDED` con una entrega
pendiente imposible de confirmar. La devolución directa por el mesero antes de entregar
no está implementada; necesita un flujo específico de custodia en una fase posterior.

### Efectivo esperado y privacidad

`get_expected_cash(session)` usa solo movimientos físicos:

```text
fondo inicial
+ cobros directos CASH
+ entregas recibidas de meseros
- retiros
- reembolsos físicos CASH
= efectivo esperado
```

No incluye efectivo que todavía conserva el mesero, tarjeta, transferencia ni depósito.
`get_cash_session_summary(session)` devuelve registro/cajero, fondo, cada componente,
esperado y fechas; el contado y la diferencia aparecen en ese resumen solo tras cerrar.
Es una consulta interna: **no debe exponerse directamente en una pantalla normal de caja**.

`/dev/caja/` no consulta ni muestra esperado, ventas agregadas, efectivo en caja ni
diferencia antes del conteo, incluso para un superusuario. La información individual de
entregas sigue visible a quien puede recibirlas. El administrador financiero exige
además `view_cash_session_financials`. El resumen de jornada de Gerencia también requiere
ese permiso; concederlo no habilita revelar antes el resultado en el flujo de conteo ciego.

### Conteo ciego y cierre inmutable

```python
submitted = cash.submit_blind_cash_count(session, Decimal("1480.00"), cashier)
result = cash.get_blind_close_result(session, cashier)
closed = cash.close_cash_session(session, cashier, reason="Faltante documentado")
```

La primera etapa exige `close_cash_session`, sesión abierta y contado no negativo.
Guarda el conteo una sola vez con actor y hora, calcula el esperado y la diferencia y
**congela movimientos**. Devuelve únicamente ID, importe contado y fecha de presentación.
No devuelve el esperado ni la diferencia en esa respuesta; después del registro se
pueden consultar mediante `get_blind_close_result`.

El conteo no puede reemplazarse después de conocer el esperado. No existe reapertura de
sesión ni edición del conteo. La sesión permanece `OPEN` entre conteo y cierre, por lo
que tampoco puede abrirse otra en la misma estación durante ese intervalo.

La segunda etapa vuelve a comprobar movimientos/integridad y calcula:
`difference = counted_cash - expected_cash`. Un faltante es negativo y un sobrante positivo.
Si la diferencia no es cero, exige motivo; si es cero, el motivo es opcional. Guarda
esperado final, diferencia, razón, autor/fecha y `CLOSED`. Después no admite movimientos
nuevos ni cambios financieros por servicios o administrador.

### Bloqueadores, cierre y reapertura de jornada

`get_business_day_close_blockers(day)` entrega una lista de objetos con `type`,
`description` y `object_id`, sin limitarse a un booleano. Detecta:

- órdenes activas y saldos distintos de cero;
- pagos pendientes de verificación;
- sesiones de caja abiertas, incluidas las contadas aún sin cerrar;
- entregas pendientes de meseros;
- inconsistencias entre pagos/asignaciones, entregas/movimientos y conteos congelados;
- cuentas históricas pendientes que todavía no tienen jornada.

`can_close_business_day(day)` solo devuelve verdadero para una jornada abierta sin
bloqueadores. `close_business_day(day, user)` exige `close_business_day`, bloquea y
recalcula la lista dentro de su transacción antes de guardar cierre y auditoría.
No existe cierre automático por hora.

`reopen_business_day(day, user, reason)` exige permiso propio, motivo y que no haya
otra jornada abierta. Añade un `BusinessDayReopen` y actualiza los datos de última
reapertura, conservando el cierre previo en el historial. Reabrir no modifica sesiones
cerradas ni elimina pagos o movimientos originales.

### Resumen comercial y controles transaccionales

`get_business_day_summary(day)` devuelve `gross_sales`, `adjustments`, `refunds` y
`net_sales` por separado, calculados desde las órdenes de esa jornada. Expone por método
pagos confirmados brutos, reembolsos, confirmados netos y pendientes; además incluye
sesiones abiertas/cerradas, diferencias cerradas, retiros, salidas físicas de reembolso,
entregas pendientes/recibidas y órdenes activas/cerradas. El fondo inicial no entra en ventas.
No genera PDF ni impresión.

Las operaciones usan `transaction.atomic` y bloqueos de filas. En esta primera
instalación, una barrera transaccional PostgreSQL compartida serializa las escrituras
operativas de órdenes/pagos/caja con apertura/cierre/reapertura de jornada. Se toma
siempre antes de bloquear jornada, orden/pago, sesión o productos. También protege
la primera apertura cuando aún no hay una fila de jornada que bloquear.

**Decisión de concurrencia:** se prioriza una frontera de cierre coherente para el
local sobre procesar escrituras comerciales simultáneamente. Un cierre y una nueva
orden/sesión no pueden confirmarse a la vez. Una futura optimización puede afinar la
granularidad conservando esta garantía. Constraints adicionales impiden dos jornadas
abiertas, dos sesiones abiertas de una caja o recepciones duplicadas de un pago.

Permisos explícitos de `cash`, sin asignación automática por rol:
`open_cash_session`, `receive_waiter_cash`, `approve_cash_withdrawal`,
`close_cash_session`, `view_cash_session_financials`, `open_business_day`,
`close_business_day`, `reopen_business_day` y `record_cash_refund`.
Las operaciones comerciales mantienen además sus permisos de `orders`/`payments`.
Auditoría registra apertura, cobros directos, entregas, retiros, salida por reembolso,
conteo, cierre/diferencia, cierre de jornada, reaperturas y regularización histórica.

### Administración, vistas y migraciones

`CashRegister` es editable con controles de identidad/actividad y auditoría.
`CashSession`, `CashHandoff`, `CashMovement`, `BusinessDay` y `BusinessDayReopen`
son de solo lectura: no se puede editar fondo, conteo, movimientos o estados a mano.
Las escrituras directas ORM/SQL no son una API soportada.

- <http://127.0.0.1:8000/dev/caja/>: seleccionar sesión/estación, abrir, recibir
  entregas, aprobar retiros, enviar conteo ciego y finalizar cierre.
- <http://127.0.0.1:8000/dev/jornada/>: abrir, consultar estado/bloqueadores/resumen,
  cerrar y reabrir con motivo. Los bloqueadores requieren permiso de cierre de jornada;
  el resumen comercial requiere permiso de información financiera.
- <http://127.0.0.1:8000/dev/pagos/>: incorpora selección explícita de sesión receptora
  de efectivo. La salida física de reembolso se registra por servicio en esta fase.

Todas requieren `DEBUG=True`, sesión, staff activo, permiso nativo de consulta,
permisos específicos para operar y CSRF. No se ha creado una interfaz final.

Migraciones nuevas: `cash.0001_initial` y `orders.0004_tableorder_business_day`.
No se editaron migraciones anteriores ni se reinició la base. `Payment` y sus
allocations/refunds se conservan; no necesitan una migración de campos para esta relación.

## Pruebas y comprobaciones

Con PostgreSQL disponible y `.venv` activado:

```sh
python manage.py check --database default
python manage.py makemigrations --check --dry-run
python manage.py test
python -m pip check
```

Las 484 pruebas Django cubren carga de la página y del administrador, formularios de usuarios,
roles, permisos individuales, PIN con hash y sal, confirmación y conservación del PIN,
creación de auditoría y protección frente a cambios y borrado, CSRF y archivos estáticos.
También cubren áreas, zonas, mesas, validaciones Python y constraints PostgreSQL,
coherencia entre zona y área, semilla idempotente, mapa ordenado, auditoría transaccional,
administración y acceso restringido a la vista de desarrollo.
La Fase 1B añade pruebas de categorías, precios e historial, modificadores, combos,
disponibilidad, entradas y ajustes, permisos, CSRF, imágenes inválidas, reversión ante
fallos y concurrencia real. Las 67 pruebas de las fases anteriores siguen incluidas.
La Fase 1C añade apertura, subcuentas, snapshots, agrupación de borradores, envíos,
anulaciones, devolución de componentes, movimientos parciales, uniones, totales,
administración de solo lectura y vistas dev. También prueba con conexiones independientes
doble apertura, doble envío, adiciones simultáneas, competencia por el último stock y
doble anulación. Las 133 pruebas anteriores siguen pasando.
La Fase 1D añade 78 pruebas de saldos, pagos por artículos y montos, cambio, reservas
por verificar, cobros mixtos, cierres, descuentos, reembolsos, devolución de inventario,
recibos, permisos, admin, CSRF y concurrencia real de pagos/ajustes/anulaciones.
Las 186 pruebas anteriores siguen incluidas.
La Fase 1E añade 71 pruebas de estaciones, semilla idempotente, sesiones, entregas,
retiros, reembolsos físicos, fórmula de efectivo, cierre ciego, privacidad, jornadas,
bloqueadores, reaperturas y resúmenes. La concurrencia cubre aperturas, cobros, conteos,
retiros, recepciones, devoluciones y cierre de jornada frente a nuevas órdenes/sesiones.
Las 264 pruebas anteriores se conservan, con fixtures de jornada abierta y contexto
de sesión explícito para los reembolsos de efectivo y cobros directos que lo requieren.
Se ejecutan sobre una base PostgreSQL temporal separada; Django la elimina al finalizar.

La Fase 2A añade 47 pruebas: dispositivo y cookie firmada, permiso de configuración,
selección de meseros, PIN, bloqueo persistente por dispositivo/usuario, expiración,
sesión separada, cambio de usuario, invalidación de credenciales/permisos, CSRF,
área asignada, jornada, estados derivados, consumo, tiempo, zonas, posiciones,
SINGLE/SPLIT y atribución del usuario. Las pruebas concurrentes usan conexiones
independientes para abrir la misma mesa desde dos dispositivos y para cinco PIN
fallidos simultáneos. Se conservan las 335 pruebas anteriores.

La Fase 2B añade 49 pruebas Django: catálogo real, filtros combinados, agotados y combos,
precios por área, acceso a órdenes, permisos por acción, sesión, CSRF, POST, selección y
cotización de modificadores, notas, agrupación, edición DRAFT, aislamiento de subcuentas,
envíos atómicos, inventario, destinos reales, adiciones y conservación al cambiar usuario.
Incluye el cierre de subcuentas provocado por el servicio financiero existente al retirar
el último borrador. Las 382 pruebas anteriores siguen pasando.

Dos pruebas adicionales ejecutan directamente el filtro JavaScript sin navegador ni
dependencias npm. Node.js solo es necesario para esta comprobación de desarrollo:

```sh
node --test apps/operations/tests/catalog-filter.test.mjs
```

Resultado de Fase 2B: **431 pruebas Django + 2 JavaScript aprobadas**, configuración
sin errores y `makemigrations --check --dry-run` sin cambios pendientes.

## Fase 2A — Acceso operativo del mesero

### Dispositivo y configuración inicial

`OperationalDevice` representa una tablet: nombre, código único, tipo
`WAITER_TABLET`, área obligatoria y estado activo. Se gestiona en Django Admin.
El permiso `operations.configure_operational_device` no se asigna automáticamente
por rol; crear/editar registros en Admin también exige los permisos nativos del modelo.

1. Aplicar las migraciones y arrancar el servidor local.
2. Crear un dispositivo en `/admin/operations/operationaldevice/` y asignarle su área real.
3. Abrir `/dispositivo/configurar/` en el navegador de esa tablet, con un usuario
   administrativo activo, `is_staff=True` y permiso explícito de configuración.
4. Seleccionar el dispositivo y guardar. El navegador pasa al selector de meseros.

La cookie `bigparty_device` contiene un identificador firmado, una versión de
vinculación y un nonce aleatorio propio del navegador. Dura un año, es `HttpOnly`,
`SameSite=Lax` y usa `Secure` con la configuración de producción. Cada petición
comprueba la firma, vigencia y actividad del dispositivo y del área. No se confía en
localStorage. Cambiar área, código, tipo o actividad mediante `save()`/Admin rota
la versión, revoca accesos existentes y exige configurar otra vez los navegadores;
no usar actualizaciones masivas directas para administrar dispositivos.

### PIN, permisos y sesión independiente

El selector muestra usuarios activos con `role=MESERO` y permiso
`tables.view_venuetable`. Abrir una mesa exige además `orders.open_table_order`.
El rol por sí solo no concede acciones. Configurar el PIN en el formulario de usuarios
existente, con **4 a 6 dígitos** para esta interfaz. Se reutilizan `set_pin()` y
`check_pin()`: no hay un segundo algoritmo de hash. El soporte histórico de 4–12
dígitos del modelo se conserva; un PIN anterior de más de 6 debe reemplazarse para
usar esta pantalla. El valor y su hash no se incluyen en HTML, JSON ni auditoría.

`PinAttempt` conserva los fallos por dispositivo y usuario. El quinto fallo bloquea
esa combinación durante cinco minutos; refrescar o cambiar de navegador no elimina
el bloqueo. Otro usuario o dispositivo puede operar. Al expirar se reinicia el
contador; un acceso correcto también lo reinicia. Las escrituras se serializan por
dispositivo para evitar perder intentos concurrentes.

`OperationalSession` identifica usuario, dispositivo, navegador y área en el backend.
El token aleatorio viaja en cookie `HttpOnly`; solo su hash queda en base de datos.
Un hash de autenticación permite invalidar sesiones si cambia el PIN o la contraseña.
Los permisos, actividad del usuario y área se validan nuevamente en cada petición.
El navegador tiene una sola sesión operativa vigente para esa vinculación.

Se conserva separada de la sesión administrativa: **Cambiar usuario** revoca el acceso
operativo, conserva el dispositivo, vuelve al selector y no modifica cuentas abiertas.
No hace `login()`/`logout()` de Django para sustituir al administrador por el mesero.

### Inactividad y jornada

Los valores están centralizados en `config/settings/base.py`:

| Parámetro | Valor inicial |
| --- | --- |
| `OPERATIONAL_IDLE_TIMEOUT_SECONDS` | 120 segundos |
| `OPERATIONAL_PIN_MAX_ATTEMPTS` | 5 intentos |
| `OPERATIONAL_PIN_LOCK_SECONDS` | 300 segundos |
| `OPERATIONAL_DEVICE_COOKIE_AGE` | 365 días |

El servidor rechaza sesiones vencidas. La interfaz se bloquea también al cumplirse
la inactividad, al regresar a una pestaña vencida y al restaurar páginas del historial.
Solo la interacción del usuario produce una señal de actividad, como máximo cada
30 segundos; no existe polling continuo que mantenga vivo un acceso abandonado.
Si no hay `BusinessDay OPEN`, muestra “No hay una jornada abierta.” y bloquea la
apertura. El mesero no puede abrir una jornada desde esta interfaz.

### Mapa y apertura

La consulta operativa devuelve únicamente mesas activas del área de la tablet.
Agrupa por zonas existentes, con “Área general” para las mesas sin zona. Usa el
layout configurado cuando es utilizable; coordenadas iniciales/superpuestas o
controles demasiado pequeños en la pantalla actual utilizan una cuadrícula ordenada.
En pantallas estrechas el plano se adapta a cuadrícula.

Libre, ocupada, fuera de servicio, pago parcial y pago pendiente son estados
derivados. El consumo actual usa `get_order_grand_total()` (borradores y líneas
enviadas no anuladas); no representa el saldo después de pagos/descuentos. Las mesas
unidas muestran el consumo de la cuenta compartida. El tiempo parte de `opened_at`
y se actualiza visualmente sin consultas periódicas al servidor. El botón Actualizar
trae cambios de otras tablets. Buscar admite nombre, número y ceros iniciales.

Tocar una mesa abre un panel con su capacidad, área y estado; las ocupadas muestran
responsable, consumo y tiempo. Abrir solicita SINGLE o SPLIT y llama al servicio
existente `open_table_order()`, con el usuario validado como responsable y autor,
jornada actual y vínculo de mesa. SPLIT no crea subcuentas automáticas. La apertura
respeta los bloqueos de jornada/mesa existentes y actualiza el mapa; un conflicto
muestra “La mesa acaba de ser ocupada por otro usuario.”

No hay selección libre de área ni confianza en identidades enviadas por el cliente.
Las mutaciones usan POST y CSRF; respuestas operativas no se almacenan en caché.
Las vistas `/dev/` anteriores se conservan para diagnóstico.

### Diseño y archivos

Templates Django y módulos JavaScript, sin un framework adicional. Los estilos
reutilizables viven en `static/css/operations/`: `tokens.css`, `base.css`,
`components.css`, `operational.css`. La paleta es oscura neutral con dorado champagne;
se definen variables de color, espaciado, tipografía, radios, sombras y controles.
La familia es `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`:
usa Inter si está instalada y fallback local en caso contrario, sin descargar fuentes.
Controles de al menos 48 px, teclado de 64 px, foco visible y diálogos nativos.

`static/js/operations/` separa `ui.js`, `access.js`, `session.js` y `tables.js`.
`apps/operations/` contiene modelos, autenticación, consultas, adaptador de apertura,
vistas, Admin y pruebas. `templates/operations/` contiene acceso, configuración,
mapa y base compartida. La única migración nueva es `operations.0001_initial`;
no se modificaron migraciones históricas.

### Probar localmente

```sh
source .venv/bin/activate
python manage.py migrate
python manage.py check
python manage.py makemigrations --check
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

Con usuarios, permisos, PIN, mesas y jornada reales preparados desde las herramientas
existentes, configurar la tablet y visitar <http://127.0.0.1:8000/operacion/>.
Seleccionar mesero → ingresar PIN → buscar una mesa → abrir panel → Abrir mesa →
Una sola cuenta → comprobar Ocupada → Cambiar usuario → ingresar con otro PIN.
Esperar dos minutos sin tocar la pantalla para verificar el bloqueo. Probar SPLIT
y comprobar en Admin que no aparecen subcuentas inventadas.

El recorrido de esta entrega se verificó en navegador a **1280×800 y 800×1280**,
con base PostgreSQL temporal separada de la base real, incluyendo aperturas SINGLE
y SPLIT. Las capturas de `docs/phase-2a/` contienen exclusivamente datos de prueba.
La base temporal se elimina al terminar; no se incluyen cuentas o credenciales
de demostración en la base del proyecto. Esto valida tamaños de tablet en navegador;
la verificación en hardware Android físico queda para la prueba operativa del local.

## Fase 2B — Catálogo y pedidos visuales

### Acceso y flujo

Desde una mesa ocupada, **Agregar pedido** abre
`/operacion/orden/<id>/pedido/`, dentro del namespace `operations`.
El usuario necesita los permisos explícitos correspondientes; el rol MESERO no los
concede automáticamente:

| Acción | Permiso |
| --- | --- |
| Agregar, cotizar, aumentar, reducir, eliminar y cambiar nota DRAFT | `orders.add_order_line` |
| Enviar pedido | `orders.send_order` |
| Crear subcuenta | `orders.manage_subaccounts` |

La página requiere al menos uno de esos permisos. Cada petición comprueba nuevamente
sesión operativa, dispositivo, área, orden activa y vínculo con una mesa activa del área.
Las escrituras conservan los bloqueos de jornada, orden y mesa antes de llamar a los
servicios existentes. Todas las mutaciones usan POST y CSRF. El autor se toma de la
sesión operativa; el cliente no puede elegir usuario, área o precio.

El mapa mantiene su estructura de Fase 2A, con mayor contraste, cabecera más legible,
búsqueda de mesa de 320 px y fondo del panel lateral oscurecido solo un 15%.

### Catálogo, categorías y búsqueda

`catalog_products()` proporciona productos y relaciones reales. La interfaz filtra
productos activos, visibles en POS y pertenecientes a categorías activas. Conserva
los agotados visibles y deshabilitados, consultando `is_product_available()`; los
combos dependen de sus componentes. Los productos sin control de inventario se
mantienen disponibles. El precio efectivo procede de `get_product_price(product, area)`.

Las categorías se filtran inmediatamente en el navegador; **Buscar producto** combina
nombre y categoría mediante AND, ignorando mayúsculas y acentos. Cambiar de categoría
reemplaza los resultados anteriores. **Todos** elimina solamente el filtro de categoría.
Las tarjetas priorizan nombre y precio; la imagen, cuando existe, es discreta y opcional.
**Actualizar pedido** vuelve a consultar disponibilidad y cambios de otras tablets.

### Modificadores, notas y borradores

Tocar un producto simple llama a `add_product_to_order()` sin navegación. Los productos
con grupos activos abren un diálogo con `ModifierGroup` y `ModifierOption` reales,
selección SINGLE/MULTIPLE, límites, nota opcional y cantidad desde uno.
`get_order_product_quote()` comparte validación y cálculo con la escritura del borrador:
el servidor valida grupos requeridos, mínimos, máximos y opciones, aplica extras y
devuelve el total. JavaScript no calcula precios. Agregar vuelve a validar el estado actual.

La nota se guarda en `OrderLine.notes`. El panel **Pedido actual** muestra solo DRAFT
del contexto seleccionado, sus modificadores, notas, cantidades, subtotales y total.
Los toques equivalentes se agrupan por el servicio existente. Aumentar, reducir,
eliminar y editar nota reutilizan los servicios de `orders`; una línea SENT no se edita.
Los borradores viven en la base y sobreviven a recarga, cambio de mesero y auto-lock.
Los mensajes de error permanecen visibles y no exponen trazas o excepciones internas.

### Envío, disponibilidad y adiciones

**Enviar pedido** está deshabilitado sin borradores y mantiene visible el total del
pedido actual. Reutiliza `send_order()` para comprobar y descontar inventario y generar
`PreparationTicket`/`PreparationTicketItem`; no hay impresión física.
Si otro pedido consume el stock antes del envío, la operación se revierte, conserva
los DRAFT y actualiza el catálogo con un mensaje de existencias insuficientes.

Tras un envío correcto, el panel queda sin esos DRAFT y aparece un aviso de tres segundos.
Los destinos provienen de los artículos del ticket: AREA_BAR se presenta como Barra 1
en Sport Bar, Barra 2 en Discoteca y Barra 3 en Premium; KITCHEN como Cocina y NONE
se omite. Estas etiquetas no se guardan en Product. Un envío posterior genera ADDITION
y añade «Adición» al aviso, sin reprocesar productos anteriores.

### SINGLE y SPLIT

SINGLE no muestra selector y agrega con `subaccount=NULL`. SPLIT exige crear o seleccionar
una subcuenta abierta antes de agregar, cotizar o enviar. **Nueva cuenta** solicita solo
nombre y llama a `create_subaccount()`; la cuenta nueva se selecciona automáticamente.
Cambiar de cuenta actualiza sus borradores y total sin mezclar personas. Los importes del
selector usan `get_subaccount_grand_total()`; el panel usa `get_subaccount_pending_total()`.

**Decisión de alcance del envío:** en SPLIT se envía únicamente la subcuenta seleccionada,
que corresponde al pedido visible. `send_order(order, user, subaccount=...)` admite ese
filtro opcional, conservando el comportamiento anterior cuando se omite. Otros DRAFT
permanecen guardados, incluidos los históricos sin subcuenta, que esta pantalla no muestra
ni permite crear en SPLIT. Las cuentas cerradas aparecen diferenciadas y no seleccionables.
Si un servicio cierra la cuenta seleccionada, se retira la selección; un pedido posterior
requiere otra cuenta abierta o una nueva.

### Presentación y comprobación

En horizontal se usa aproximadamente 70% catálogo y 30% pedido. En vertical, el catálogo
ocupa el ancho y **Ver pedido** abre un panel inferior con total y botón de envío.
Se conservan Inter/sans-serif y negro, carbón, blanco y champagne. La implementación
usa templates Django y módulos JavaScript con fetch, sin SPA ni dependencias nuevas.
Las mutaciones se serializan en la tablet; ante una conexión interrumpida se solicita
actualizar antes de repetir para evitar reenvíos a ciegas. No hay operación offline.

Archivos principales: `apps/operations/ordering.py`, `order_views.py`,
`templates/operations/order.html`, `static/js/operations/ordering.js`,
`catalog-filter.mjs` y `static/css/operations/ordering.css`.
No se requieren migraciones nuevas ni se modifican migraciones históricas.

El recorrido SINGLE y SPLIT se comprobó con datos reales en una **base PostgreSQL temporal
separada**, a 1280×800 y 800×1280. La jornada se abrió con el servicio backend existente.
La [verificación de Fase 2B](docs/phase-2b/verification.md) detalla resultados y capturas.
Los datos de demostración se eliminan; las imágenes conservan únicamente datos de prueba.
La prueba en hardware Android físico queda pendiente de la validación operativa del local.

## Fase 2C — Ver cuenta, dividir y cobrar

### Entrada, permisos y navegación

**Mesa ocupada → Ver cuenta** abre `/operacion/orden/<id>/cuenta/`. El pedido incluye
una acción discreta **Ver cuenta**, conservando la subcuenta seleccionada; desde la
cuenta se vuelve a **Agregar productos**. Se mantiene el acceso operativo por PIN,
área de dispositivo y usuario, independiente del administrador.

| Acción | Permiso existente |
| --- | --- |
| Consultar cuenta | `payments.view_payment`, `payments.record_payment` o `payments.close_order` |
| Preparar selección y registrar un pago | `payments.record_payment` |
| Cerrar la orden liquidada | `payments.close_order` |

No se asignan permisos automáticamente por rol ni se crean modelos o migraciones nuevas.
Se validan dispositivo, sesión, área, orden activa, mesa vinculada, subcuenta y permiso
por acción. Las escrituras bloquean jornada y orden antes de invocar los servicios financieros.

### Consumo y resumen financiero

**Total** es `charge_total` de `get_financial_summary()`: SENT válido, menos ajustes y
reembolsos según el registro financiero existente. **Pagado** muestra el confirmado neto;
**Pendiente** incluye el saldo reservado por pagos aún no verificados. Cuando hay reservas,
se muestran separadamente **Pendiente de verificación** y **Saldo disponible para cobrar**.
JavaScript no calcula esos importes.

Los DRAFT no se incluyen en cargos ni pagos; aparece «Hay productos pendientes de enviar».
Se muestran cantidad original, nombre, modificadores, nota, precio unitario, subtotal y
cobertura por unidades. Una línea parcialmente pagada permanece unida; las saldadas se
conservan en **Pagados**, colapsada inicialmente. Descuentos, cortesías y reembolsos
creados mediante las herramientas autorizadas se reflejan en importes e historial,
sin ofrecer acciones para aplicarlos desde la tablet.

### Dividir por cantidades y cobrar saldo

En SINGLE, **Dividir cuenta** permite seleccionar cantidades sin cambiar `billing_mode`.
`get_line_payment_quantities()` consulta PaymentAllocation y el registro por unidad:
las unidades con pagos confirmados o reservas no se ofrecen como totalmente impagadas.
Una unidad con abono se completa mediante pago por monto o saldo total. Los ajustes
reducen su importe elegible y los reembolsos siguen la semántica financiera existente.

El servidor cotiza selección y subtotal por línea mediante `get_payment_quote()`, que
comparte `_select`/`_distribute` con los servicios de registro. No hay subtotales Q0 grandes
en productos no seleccionados; **Continuar al pago** requiere selección válida y positiva.
**Cobrar** sin división prepara el saldo disponible completo y usa `pay_full_balance()`.
Las selecciones se conservan al volver mientras sigan disponibles; una actualización
elimina o limita cantidades que otro usuario ya pagó.

### Métodos y efectivo del mesero

- **Efectivo:** monto preparado por servidor, recibido manual o botones rápidos y cambio
  visual calculado en centavos. El backend vuelve a validar recibido y monto. Se registra
  CASH/CONFIRMED, `cash_handoff_status=PENDING`, mediante los servicios existentes.
  Se crea la entrega pendiente del mesero y no se asocia el pago a una CashSession.
- **Tarjeta:** muestra «Realiza el cobro en la terminal bancaria». El botón confirma un
  cobro ya aprobado en esa terminal y registra CARD/CONFIRMED. No se solicita voucher,
  banco, autorización ni datos de la tarjeta.
- **Transferencia y depósito:** exigen referencia y crean PENDING. Se informa que Gerencia
  debe verificar el pago; el monto queda reservado y no puede cobrarse otra vez. La mesa
  muestra Pago pendiente. Si el servicio de Gerencia rechaza después la operación,
  **Actualizar cuenta** muestra Rechazado y el importe vuelve a estar disponible.

### Pago mixto

**Pago mixto** registra un método y monto por vez, con los mismos Payment y allocations.
Por ejemplo, Q200 en efectivo sobre Q500 deja Q300 para tarjeta; una transferencia por esos
Q300 deja Q200 confirmados, Q300 por verificar y Q0 disponibles. No existe MixedPayment.
Después de cada registro se actualizan resumen e historial. El cierre queda bloqueado
mientras exista cualquier reserva.

También se puede iniciar mixto desde una selección de productos. El alcance conserva las
unidades seleccionadas, incluidas las que reciben abonos, sin tomar saldo de otras personas
ni productos. `create_amount_payment(..., unit_keys=...)` añade ese filtro opcional;
las llamadas históricas sin filtro mantienen su comportamiento.

### Confirmaciones y concurrencia

Preparar el pago no registra ni reserva dinero. La confirmación lleva una firma del servidor
vinculada a orden, subcuenta, sesión operativa, alcance e importes cotizados, con vigencia de
10 minutos (el auto-lock de 120 segundos sigue aplicando por separado). Al confirmar se
compara nuevamente el registro financiero bajo el bloqueo de la orden.

Si otra tablet pagó, se aplicó un ajuste, se cambió una reserva o se reintenta la misma
confirmación ya consumida, se rechaza con un mensaje humano y se devuelve la cuenta actual.
No se confía en precio, saldo, estado, caja o usuario enviados por el navegador. Las acciones
son POST + CSRF: `seleccion`, `preparar`, `mixto`, `efectivo`, `tarjeta`, `transferencia`,
`deposito` y `cerrar`, bajo `/operacion/orden/<id>/cuenta/`.

El navegador bloquea confirmaciones durante una petición y no reintenta automáticamente.
Si se interrumpe la conexión, solicita actualizar: el pago podría haberse registrado.
Cambiar de usuario o auto-lock invalida la confirmación anterior y nunca registra un pago
por sí mismo. Se consulta nuevamente el backend al entrar.

### SPLIT y cierres

SPLIT reutiliza la barra horizontal de cuentas. Se cobra únicamente la persona seleccionada;
las cuentas cerradas siguen consultables como **Pagada**, con Agregar productos deshabilitado.
El backend cierra una subcuenta cuando su saldo y reservas son cero y no conserva DRAFT.
Pagar a Jorge no altera el saldo de Carlos. Una nueva visita requiere una nueva subcuenta
mediante la interfaz de pedidos existente.

La orden completa permanece activa después del último pago. Cuando `can_close_order()`
lo permite y el usuario tiene permiso, aparece **Cuenta pagada → Cerrar cuenta**.
`close_order(order, user)` valida nuevamente, finaliza subcuentas correspondientes y libera
los vínculos de mesa. La confirmación muestra **Cuenta cerrada · Mesa disponible** y
**Volver a mesas**. No se cierra silenciosamente después de registrar el pago.

### Diseño, archivos y validación

Se mantiene negro/carbón/blanco/champagne e Inter/sans-serif. Cuenta usa aproximadamente
70/30 en horizontal y columnas apiladas en vertical; la selección mantiene un resumen
inferior accesible. Los formularios se muestran en la misma pantalla, sin modales anidados.
En catálogo se retiró el estado permanente «Borradores guardados», los controles de línea
son de 48×48 px y los productos deshabilitados conservan texto legible.

Archivos principales: `apps/operations/accounting.py`, `account_views.py`,
`templates/operations/account.html`, `static/js/operations/account.js`,
`payment-money.mjs`, `payment-selection.mjs` y `static/css/operations/account.css`.
Se amplió de manera compatible `apps/payments/services.py` para cotizaciones y alcance mixto.

La fase añade **53 pruebas Django** (incluidas dos carreras con tablets/conexiones separadas)
y **4 JavaScript**. Resultado acumulado: **484 Django + 6 JavaScript aprobadas**.
Comprobación de configuración sin errores y migraciones sin cambios pendientes.

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
node --test apps/operations/tests/*.test.mjs
```

Se ejecutaron los recorridos SINGLE, mixto, transferencia pendiente y SPLIT en una base
PostgreSQL desechable separada de los datos reales. Las cuatro capturas horizontales y la
vertical, junto al detalle del recorrido, están en [Verificación de Fase 2C](docs/phase-2c/verification.md).
Los datos temporales se eliminan al terminar. La validación en tablet Android física queda
pendiente de la revisión operativa del local.

## Fase 2D — Estación de caja Windows

La interfaz operativa está en **`/caja/`**. Reutiliza CashRegister, BusinessDay,
CashSession, CashHandoff y CashMovement. Las herramientas de `/dev/caja/` permanecen.

### Configurar la computadora y habilitar usuarios

1. Crear o revisar el CashRegister activo y su área en Django Admin.
2. Dar al administrador de configuración acceso staff y el permiso
   **`cash.configure_cash_register_device`**.
3. En esa computadora, abrir **`/caja/configurar/`**, ingresar al acceso administrativo
   y seleccionar la estación física: Sport Bar, Discoteca o Premium.
4. Preparar usuarios activos CAJERO o GERENTE con un PIN de **4 a 6 dígitos** y los
   permisos de las acciones que realmente realizarán. El rol no concede permisos.
5. Volver a `/caja/` y seleccionar el cajero. El PIN abre un acceso operativo
   independiente; no inicia una sesión Django Admin ni una sesión de mesero.

| Acción | Permiso requerido |
| --- | --- |
| Configurar navegador | `cash.configure_cash_register_device` + usuario staff |
| Abrir caja | `cash.open_cash_session` |
| Recibir entregas | `cash.receive_waiter_cash` |
| Solicitar retiro | `operations.request_cash_withdrawal` |
| Autorizar retiro con PIN | `cash.approve_cash_withdrawal` |
| Consultar movimientos | `cash.view_cashmovement` |
| Contar, consultar resultado y cerrar | `cash.close_cash_session` |

`cash.view_cash_session_financials` sigue protegiendo las consultas administrativas
existentes. Tenerlo **no revela totales en Caja activa**. El resultado del cierre
requiere el permiso de cierre y que el conteo ya esté registrado, como exige el
servicio de caja existente. No se otorgan permisos automáticamente a usuarios reales.

Sin estación válida solo aparece el aviso de configuración; no hay acciones de caja.
La configuración persiste un año en una cookie firmada, HttpOnly y SameSite=Lax,
restringida a `/caja/` y Secure cuando la configuración de producción lo exige.
No se usa localStorage como autoridad. Cambiar el código, área o estado de una caja
mediante su modelo rota la versión de vinculación y revoca accesos; una estación
inactiva o con área inactiva no puede usarse. Se conservan las restricciones históricas
que impiden cambiar código/área con historial o desactivar una caja abierta.

### PIN, jornada y bloqueo

Se reutilizan `User.check_pin()` y los hashes existentes. Los tokens de acceso solo
se guardan como hash y quedan ligados a estación, navegador, usuario y jornada.
Cinco fallos bloquean **estación + usuario** por cinco minutos; no bloquean globalmente
la cuenta ni otras estaciones. El PIN de autorización de retiros comparte ese control.
Cambiar contraseña/PIN, desactivar al usuario o retirar sus permisos invalida el acceso.

El timeout de caja es **10 minutos**, separado de los 2 minutos del mesero.
Se configura centralmente en `config/settings/base.py` mediante
`CASH_IDLE_TIMEOUT_SECONDS`, `CASH_PIN_MAX_ATTEMPTS`, `CASH_PIN_LOCK_SECONDS` y
`CASH_REGISTER_COOKIE_AGE`. El servidor valida la vigencia; la actividad real de teclado,
mouse o desplazamiento actualiza el acceso. Las páginas privadas no se almacenan en caché.

Se necesita una jornada OPEN. Sin ella aparece:
**No hay una jornada abierta. Solicita a Gerencia abrir la jornada.**
La caja no incorpora una pantalla para abrir jornadas. Un cambio de jornada obliga
a volver a ingresar con PIN.

### Apertura y Caja activa

**Abrir caja** solicita un fondo inicial mayor o igual a cero y llama a
`open_cash_session()`. Estación, titular y jornada proceden del servidor. Enter confirma;
no hay teclado táctil. La restricción existente impide dos sesiones abiertas en una caja.

Después de abrir, la pantalla solo presenta acciones:
**Venta rápida** y **Mesas** deshabilitadas con aviso de siguiente fase;
**Efectivo de meseros**, **Movimientos**, **Retiro de efectivo** y **Cerrar caja** según permisos.
No muestra fondo inicial, dinero en caja, esperado, diferencias, ventas ni acumulados.

La protección de privacidad es también de datos: las vistas construyen una lista
explícita de campos seguros y no pasan CashSession ni `get_cash_session_summary()`
a las plantillas. HTML y JSON previos al conteo no contienen el esperado, ni oculto.

**Cambio de cajero:** en esta fase únicamente el titular puede continuar operando
la CashSession abierta desde la interfaz normal. Otro usuario ve quién la abrió y
puede cambiar de usuario; no se cambia silenciosamente el titular ni se concede una
excepción por ser gerente. Una autorización de retiro no cambia el acceso actual.

### Entregas de meseros y retiros

**Efectivo de meseros** consulta `get_pending_cash_handoffs()` de la jornada y muestra
mesero, mesa, monto y hora, sin total pendiente. La confirmación pequeña llama a
`confirm_cash_handoff()`. La fila recibida desaparece y se muestra **Efectivo recibido**.
Las entregas de una jornada pueden recibirse en cualquiera de sus cajas autorizadas,
respetando el backend existente. Dos cajas compitiendo por la misma entrega producen
una recepción y el mensaje **Este efectivo ya fue recibido en otra caja.**

**Retiro de efectivo** requiere monto positivo, motivo, solicitante actual y selección
de una persona activa con permiso de aprobación. Esa persona introduce su PIN;
no basta escribir un nombre ni tener rol GERENTE. Cambio, Compra operativa, Entrega
a Gerencia y Otro son atajos de texto; Otro exige redactar un motivo.

`create_cash_withdrawal()` valida fondos y registra `created_by` como solicitante,
`approved_by` como aprobador verificado y la auditoría existente. No se muestra el
saldo disponible aunque falten fondos. Un formulario firmado está ligado al acceso,
la CashSession y su último movimiento: si cambia la caja o se repite la confirmación,
se rechaza y se pide actualizar. No hay reintento automático de una respuesta de red
incierta. **Movimientos** muestra cada operación en orden, referencia y monto con signo,
sin sumas, saldo corrido ni fondo inicial.

### Cierre ciego y comprobante

1. **Cerrar caja:** contar físicamente el efectivo e introducirlo en un campo vacío.
   Esta pantalla no consulta ni envía esperado, ventas, entregas o retiros.
2. **Registrar conteo:** `submit_blind_cash_count()` congela el conteo y los movimientos.
   No permite sustituirlo ni seguir recibiendo o retirando dinero.
3. **Resultado del cierre:** ahora `get_blind_close_result()` puede revelar esperado,
   contado y diferencia. Caja cuadrada permite cerrar sin motivo; un faltante o
   sobrante exige **Motivo de diferencia**, también validado en el backend.
4. **Cerrar caja:** `close_cash_session()` persiste CLOSED y datos congelados.
5. **Caja cerrada:** muestra estación, titular, hora, contado y diferencia.
   **Ver comprobante** abre HTML; no genera PDF ni recibos de venta.
6. **Finalizar sesión:** revoca el acceso y vuelve al selector. Un siguiente cajero
   puede abrir una nueva CashSession. Formularios de la anterior siguen rechazados.

Las entregas pendientes que nunca pertenecieron a esta caja no bloquean su cierre;
permanecen como pendientes de la jornada. El conteo y todas las mutaciones exigen
POST, CSRF, identidad configurada, acceso vigente, jornada y permisos. Ningún
`cash_session` enviado por el navegador puede elegir una sesión de otra estación.
La serialización usa la puerta de operaciones existente antes de bloquear estación
y acceso, en el mismo orden que los servicios contables.

### Validación y archivos

**545 pruebas Django y 6 JavaScript aprobadas.** La fase agrega 61 pruebas Django,
incluidas cuatro carreras con conexiones separadas. Se completó el recorrido manual
con una base desechable, pago real desde la interfaz del mesero, recepción, retiro,
cierre con faltante, comprobante y nueva sesión con cierre cuadrado.

Pantallas verificadas a **1280×800, 1366×768 y 1920×1080**. La prueba física en Windows
queda para el local. Detalle del recorrido y las siete capturas reales en
[Verificación de Fase 2D](docs/phase-2d/verification.md).

Archivos principales: `apps/operations/cash_security.py`, `cash_views.py`,
`cash_urls.py`, los modelos y migraciones de `cash` y `operations`,
`templates/operations/cash/`, `static/css/operations/cash.css`,
`static/js/operations/cash.js`, `test_cash_workstation.py` y `test_cash_concurrency.py`.
Los ajustes de 2C están limitados a `static/css/operations/account.css`.

## Git y alcance

`.env`, `.venv`, cachés, archivos temporales, medios locales y estáticos recopilados
se excluyen de Git. `.env.example`, las dependencias y las migraciones sí se versionan.
No subir credenciales ni archivos de entorno reales.

La entrega finaliza en la Fase 2D: estación de caja, recepción, retiros y cierre ciego.
Venta rápida, catálogo desde caja, cobro rápido y cargar a mesa quedan para Fase 2E.
Mover productos/mesas, unir mesas, Gerencia visual, impresoras reales, reservas, eventos,
QR, dashboard ejecutivo, PDF, nodo local, hardware, websockets y sincronización offline
permanecen fuera de alcance. Esperar revisión antes de continuar.

## Fase 2E — Venta rápida y mesas desde caja

Las tarjetas de Caja activa permiten iniciar ventas rápidas o cargar productos a una mesa
ocupada del área de la estación. Conservan el acceso a efectivo de meseros y la privacidad
de 2D: no muestran fondo, efectivo esperado, diferencias ni acumulados de ventas.

### Una sola arquitectura de órdenes

`TableOrder` incorpora `OrderType.TABLE` (valor de todas las órdenes existentes) y
`OrderType.QUICK_SALE`. Solo `QUICK_SALE` admite `primary_table=NULL`; exige jornada,
sesión de caja y modalidad `SINGLE`. La restricción `orders_type_origin_valid` protege
estas combinaciones en PostgreSQL. La venta rápida conserva `OrderLine`, composición,
modificadores, precios congelados, pagos, inventario e historial existentes. No existe un
segundo sistema de ventas.

Cada venta conserva el número real de orden, área, jornada, `cash_session` de origen,
`opened_by` y responsable. `customer_alias` es opcional (100 caracteres), se confirma
antes del primer pago y se audita al cambiar. No se solicitan teléfono, correo ni documento.
`fulfilled_at` registra la liberación del pedido al completar la venta, no una confirmación
física de entrega.

### Catálogo compartido

- `/caja/venta-rapida/`: nueva venta y continuación de borradores o pagos pendientes de la sesión actual.
- `/caja/orden/<id>/pedido/`: catálogo y carrito; encabezado de caja y distribución aproximada 70/30.
- `/caja/orden/<id>/cuenta/`: cobro de venta rápida con la interfaz de 2C.
- `/caja/orden/<id>/completada/`: número, total individual, métodos y aviso de Cocina.
- `/caja/mesas/`: búsqueda inmediata, estado, responsable, total y tiempo de mesas de la misma área.

Las plantillas de caja extienden `operations/order.html` y `operations/account.html`.
Se comparten `ordering.js`, `account.js`, componentes, categorías, filtros, diálogos,
modificadores, notas, cantidades y precios por área. `catalog_actions.py` concentra las
acciones comunes. Los estilos adicionales de caja son ajustes de disposición; no se
mantienen tres catálogos independientes. La búsqueda recibe foco inicial, los botones son
accesibles con teclado y los diálogos conservan Tab/Enter/Esc.

### Confirmación y cobro transaccionales

1. Crear y editar un borrador no descuenta inventario ni crea comandas.
2. **Cobrar** abre una cotización de solo lectura que incluye los borradores de la venta.
3. El primer pago valida sesión, jornada, permisos, estado y confirmación firmada. Dentro
   de una sola transacción, reutiliza `send_order` con preparación diferida, valida stock
   real bloqueado, consume componentes y registra el pago mediante los servicios existentes.
4. Un fallo de inventario, importe recibido o pago revierte líneas, stock, movimientos y pago.
5. Un pago parcial o pendiente inmoviliza stock una sola vez. La venta sigue abierta; no
   se libera Cocina ni se indica entrega. Después del primer pago se bloquea la edición
   del carrito y del alias para conservar el importe ya confirmado.
6. Con saldo cero, sin pagos pendientes y sin borradores, `payments.close_order` crea una
   única comanda lógica de Cocina cuando corresponde, registra `fulfilled_at` y cierra.

Esta estrategia reutiliza la contabilidad que opera sobre líneas `SENT`. El descuento de
stock representa reserva mientras el pago no se completa. No hay transacciones abiertas
entre acciones del navegador. El bloqueo de jornada y los bloqueos de orden/productos
mantienen el orden de adquisición usado por el backend existente.

| Método | Resultado |
| --- | --- |
| Efectivo | Sesión `OPEN` actual, `DIRECT_CASH_PAYMENT`, `NOT_REQUIRED`; nunca handoff. |
| Tarjeta | Confirmación después de la aprobación en terminal bancaria externa; sin voucher. |
| Transferencia / depósito | `Payment.PENDING`; referencia obligatoria, aviso persistente de no entregar. |
| Mixto | Un método por operación; stock una sola vez y cierre al completar el saldo confirmado. |

Gerencia podrá confirmar o rechazar transferencias con los servicios existentes. Tras
confirmación, el cierre libera Cocina; si se rechaza, el saldo puede cobrarse nuevamente
sin descontar stock dos veces. La interfaz final de Gerencia sigue pendiente. Caja solo
continúa ventas de su sesión de origen, mientras permanece abierta y sin conteo; resolver
ventas pendientes de una sesión ya finalizada corresponde al flujo posterior de Gerencia.

### Rutas de preparación y carga a mesas

| Contexto | `AREA_BAR` | `KITCHEN` | `NONE` |
| --- | --- | --- | --- |
| Venta rápida completada | Entrega directa, sin ticket | Ticket lógico al completar el cobro | Sin ticket |
| `TAKE_AT_BAR` en mesa | Entrega directa, sin ticket | Ticket lógico al confirmar adición | Sin ticket |
| `NORMAL_TABLE_SEND` en mesa | Ticket lógico de barra del área | Ticket lógico de Cocina | Sin ticket |

Todos los casos consumen el inventario aplicable, aunque no generen ticket. Los combos
consumen y enrutan cada componente. `PreparationTicket` conserva snapshots de número de
orden, caja y alias para ventas rápidas; el diseño y envío a impresoras sigue fuera de alcance.

Las mesas libres o fuera de servicio no aceptan carga. Las ocupadas, con pago parcial o
pendiente, conservan su cuenta existente. El selector cambia el botón entre **Cargar a Mesa…**
y **Enviar pedido a Mesa…**. No existe cobro de mesa en estas rutas. Solo se confirma la
adición nueva, sin volver a emitir productos anteriores.

En `SPLIT` se exige seleccionar una subcuenta abierta. Las cerradas no admiten nuevos
productos; **+ Nueva cuenta** reutiliza el servicio existente. `OrderLine.draft_origin`
separa los borradores de caja (`cash:<CashSession.id>`) de los de tablet (cadena vacía),
y `fulfillment_mode` conserva el modo confirmado para operaciones posteriores. Caja y
mesero no mezclan, modifican ni envían por accidente los borradores del otro. Un cambio de
PIN conserva los borradores de la misma sesión de caja, pero invalida confirmaciones viejas.

### Permisos, aislamiento y repetición

| Operación | Permisos adicionales a acceso válido y sesión abierta |
| --- | --- |
| Crear / continuar venta rápida | `orders.create_quick_sale`; crear también exige `orders.add_order_line` |
| Ver mesas / cargar desde caja | `orders.add_products_from_cash_register` |
| Cotizar / editar productos | `orders.add_order_line` |
| Confirmar adición | `orders.send_order` |
| Subcuentas | `orders.manage_subaccounts` |
| Registrar venta rápida | `payments.record_payment`, `payments.close_order`, `orders.send_order` |

El rol por sí solo no concede estos permisos. Se comprueban estación configurada y activa,
usuario titular, área, jornada, sesión `OPEN` sin conteo, orden activa y pertenencia. Los
cambios requieren POST y CSRF. Las confirmaciones firmadas incorporan acceso, orden,
subcuenta y versión; los pagos también distinguen acceso de caja y tablet. Un reintento o
estado obsoleto no duplica pagos, inventario ni comandas. La UI pide actualizar ante un
conflicto. Los servicios de pagos también impiden handoffs para efectivo de venta rápida.

### Migración y validación de 2E

Migración nueva: `orders.0005_alter_tableorder_options_orderline_draft_origin_and_more`.
No se modificaron migraciones históricas ni se reinició la base de datos.

Validación final: **611 pruebas Django y 6 JavaScript aprobadas**; `manage.py check`,
`makemigrations --check --dry-run` y `git diff --check` correctos. Las 66 pruebas nuevas
cubren ventas, rutas, inventario, pagos, permisos, CSRF, aislamiento, subcuentas y carreras
reales entre conexiones PostgreSQL: último stock, pago duplicado, caja+mesero y cierre+adición.

Los recorridos manuales y seis capturas reales de 1280 × 800 están documentados en
[Verificación de Fase 2E](docs/phase-2e/verification.md). Se usó y eliminó una base temporal
separada de los datos reales. La fase termina aquí: no incluye impresoras, recibos/PDF,
Gerencia final, reservas, eventos, QR, offline ni sincronización cloud.

## Fase 2F — Impresoras de red, comandas y recibos

`apps.printing` convierte los `PreparationTicketItem` existentes en trabajos persistentes.
La señal de dominio se emite después de guardar todos los ítems; órdenes no conoce sockets
ni modelos de impresora. La fase no incluye la interfaz final de Gerencia.

### Configuración inicial

```bash
python manage.py migrate
python manage.py seed_bigparty_defaults
python manage.py seed_printer_defaults
```

El seed es idempotente y conserva configuración existente. Crea `BAR-SPORT` (Barra 1,
Sport Bar), `BAR-DISCO` (Barra 2, Discoteca), `BAR-PREMIUM` (Barra 3, Premium) y `KITCHEN`
(Cocina compartida). Los hosts quedan vacíos: **no se asignan IPs ficticias**.

`Printer` contiene nombre, código único, tipo, área, host, puerto, ancho, codificación,
transliteración, tabla ESC t opcional, cortador, activo y fechas. BAR exige área; KITCHEN
exige área nula. Solo puede haber una barra activa por área y una cocina activa. Puerto
por defecto **9100**, validado entre 1 y 65535. Papel de **80 mm** por defecto o **58 mm**;
texto de 48 o 32 columnas respectivamente, pendiente de ajustar al modelo/fuente físicos.

En `/impresoras/`, staff con `printing.manage_printers` configura nombre, host, puerto,
papel, codificación, normalización, corte y estado activo. El panel muestra backend,
configuración y último resultado; `get_printer_status` también devuelve último éxito/error.
La página de prueba requiere además `printing.test_printer`. Incluye letras, números,
acentos y corte solo cuando está habilitado. No se realiza SNMP ni descubrimiento.

| Variable | Valor inicial | Uso |
| --- | --- | --- |
| `PRINTER_BACKEND` | `debug` | `debug` o `network`, independiente de `DEBUG` |
| `PRINTER_DEBUG_DIR` | `var/print-jobs/` | Directorio local ignorado por Git |
| `PRINTER_CONNECT_TIMEOUT` | `1` | Segundos totales de resolución/conexión |
| `PRINTER_WRITE_TIMEOUT` | `2` | Segundos máximos de envío TCP |
| `PRINTER_STALE_SECONDS` | `120` | Antigüedad para recuperación manual |

Los timeouts deben ser mayores que cero y como máximo 5 segundos cada uno; stale al
menos 30 segundos. La resolución DNS está acotada y admite un máximo de cuatro consultas
simultáneas; se utiliza la primera dirección resuelta. No hay sondeos ni bucles infinitos.

### Trabajos, transacciones y concurrencia

`PrintJob` conserva destino lógico, impresora, tipo (`PREPARATION`, `CANCELLATION`, `UPDATE`,
`RECEIPT`, `TEST`), estado (`PENDING`, `PRINTING`, `PRINTED`, `FAILED`), ticket/orden/pago
opcionales, snapshot Unicode, autor, intentos, error, backend/ruta de archivo y fechas.
`reprint_of` y motivo identifican copias; `request_key` evita repetir confirmaciones de UI.
`printing_started_at` y un token de reclamación identifican el intento en curso.

1. La misma transacción confirma orden, inventario, ticket y trabajos por destino.
2. `transaction.on_commit(..., robust=True)` reclama el trabajo y envía después del commit.
3. Una transacción breve bloquea solo el trabajo, cambia a `PRINTING` e incrementa intentos.
4. El transporte ocurre **fuera de una transacción de base de datos**. Después se registra
   `PRINTED` o `FAILED`. Una excepción del transporte no revierte consumo ni pagos.

Un constraint garantiza un original por `(preparation_ticket, destination_key)`; la clave
lógica se conserva aunque se reemplace la configuración de una impresora. Si falta una
impresora activa, se conserva un trabajo `FAILED`, sin impresora y con explicación,
en lugar de perder la alerta o rechazar el pedido.

La reclamación usa `select_for_update(of=('self',))` y un candado de sesión PostgreSQL
por trabajo durante el transporte. Dos conexiones competidoras no envían el mismo
original. La recuperación utiliza el mismo candado y omite trabajadores vivos. Requiere
conexión directa a PostgreSQL local o pooling de sesión, **no pooling por transacción**.

**Límite físico:** un TCP completado confirma bytes aceptados por el transporte, no papel
impreso ni preparación. Tras una desconexión parcial o caída de proceso no es posible
asegurar entrega física exactamente una vez sin confirmación del hardware. Se registra
`delivery_uncertain`; antes de reintentar se verifica si salió papel. No se presume éxito.

### Rutas y contenido

| Origen / entrega | `AREA_BAR` | `KITCHEN` | `NONE` |
| --- | --- | --- | --- |
| Mesa, envío normal | Barra de `PreparationTicketItem.area` | Cocina compartida | Sin trabajo |
| Mesa, `TAKE_AT_BAR` | Sin trabajo | Cocina compartida | Sin trabajo |
| Venta rápida | Sin trabajo | Solo al completar pago y cerrar | Sin trabajo |

Cada trabajo contiene únicamente los ítems de su destino. Un ticket mixto comparte orden,
mesa y hora entre estaciones. Adición, cancelación y actualización usan sus tickets
existentes y emiten solo productos afectados, con marcas visibles y motivo/nueva nota.
Los modificadores provienen del snapshot original, también para combos. Cocina de venta
rápida muestra pedido, caja y alias si existe, sin inventar una mesa.

Los servicios nunca reconstruyen una comanda antigua desde el catálogo vigente. El
snapshot original no se modifica al reintentar. Cambiar ancho de una impresora afecta
nuevos trabajos; un trabajo histórico conserva el layout que fue aceptado.

### Backends y futura instalación local

`PrinterBackend.send(job)` separa servicios del dispositivo. `DebugPrinterBackend` guarda
UTF-8 en `job-XXXXXXXX-attempt-XXX.txt`, un archivo por intento, sin sobrescribir historia.
Los ejemplos revisados se encuentran en [docs/phase-2f/examples](docs/phase-2f/examples).

`NetworkEscPosBackend` usa la biblioteca estándar (`socket`) al host y puerto configurados.
No se agregó `python-escpos`: en esta fase texto, inicialización, selección opcional de
tabla y corte no requieren esa dependencia; otro adaptador podrá sustituirlo. No utiliza
`window.print()`, diálogos del navegador ni drivers Windows. Las notas se limpian de
caracteres de control antes del transporte, para impedir insertar comandos ESC/POS.

Se envía ESC @, texto y avance; ESC t solo con tabla numérica configurada y GS V solo con
cortador habilitado. Referencias primarias: [ESC @ de Epson](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/esc_atsign.html),
[corte GS V](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_cv.html) y
[referencia ESC/POS](https://download4.epson.biz/sec_pubs/pos/reference_en/).

ASCII con transliteración es el valor conservador (`Cóctel` → `Coctel` en transporte).
Se admiten CP850, CP858 y UTF-8; la tabla numérica depende del hardware, sin asumir una
universal. Los caracteres restantes no soportados se sustituyen sin interrumpir el ticket.
La base y los archivos debug conservan Unicode. Corte está desactivado inicialmente.

En la instalación futura, Django/worker debe ejecutarse en el **nodo local de BIG PARTY**
con acceso a la LAN de impresoras y `PRINTER_BACKEND=network`. Configurar IPs/hosts reales,
puerto, papel, codepage y corte usando prueba física. No enviar desde cloud a IPs privadas;
una futura entrega al Local Node puede reutilizar estos trabajos/adaptadores. No se
agregaron USB, Bluetooth, logos gráficos, Celery, Redis, KDS, estados de preparación ni FEL.

### Reintentos, copias y recuperación

Existe **un intento automático** por trabajo nuevo, sin reintento automático tras error:
evita duplicaciones ambiguas y mantiene breve el request. Con dos destinos y los timeouts
iniciales, el límite de transporte es aproximadamente seis segundos en el peor caso,
más el tiempo de base de datos. Cada destino se procesa independientemente.

- `retry_print_job(job, user, scope_area=...)`: solo `FAILED`; mismo ID, mismo snapshot,
  siguiente intento y auditoría del error previo. No toca destinos ya impresos.
- `reprint_ticket(ticket, printer, user, reason, ...)`: exige original impreso, permiso,
  relación válida, impresora activa y motivo; crea otro trabajo con `reprint_of` y auditoría.
- La UI firma confirmaciones vinculadas al actor, objetivo y propósito; repetir el mismo
  formulario no crea otra copia. Las sesiones operativas vigentes se validan en cada POST.

```bash
# Recuperar trabajos PRINTING abandonados, sin volver a imprimir:
python manage.py recover_stale_print_jobs
# Solo PENDING que sobrevivieron a un cierre antes del callback; tanda máxima 100:
python manage.py process_print_jobs --limit 20
```

La recuperación marca stale como `FAILED`, conserva intentos y deja una alerta de salida
incierta. Solo después de revisar papel se usa Reintentar. El comando de pendientes nunca
reintenta `FAILED` o `PRINTING`. No hay un trabajador permanente ni calendario instalado.

### Pantallas, recibos y permisos

El pedido aceptado mantiene su resultado aunque falle una impresora. La tablet/caja muestra
“Pedido registrado. No se pudo imprimir en Cocina. Avisa a Caja/Gerencia.”. Consulta el
resultado tras el envío con hasta cinco actualizaciones breves del aviso, sin borrar
borradores ni alias. El botón Actualizar permite consultar después.

Caja ofrece **Trabajos de impresión** en `/caja/impresiones/`, inicialmente filtrado por
fallidos, con contenido conservado, reintento y copia autorizada. La vista técnica está en
`/impresoras/trabajos/`. El historial conserva trabajos; `PrintJobAdmin` es de solo lectura,
con filtros por impresora, estado, tipo y fecha y sin edición ni borrado de estados.

**Imprimir recibo** es una acción secundaria en Venta completada; cerrar cuenta en tablet
ofrece el enlace cuando el actor tiene permiso. Abrir esa pantalla no imprime. El POST
explícito exige cuenta cerrada sin saldo ni verificación pendiente; resuelve barra del
área de la orden, o de `CashRegister.area` en venta rápida. Incluye productos, cantidades,
precios, subtotal, descuentos/cortesías, reembolsos aplicables, total, pagos por método y
saldo. Un nuevo pedido de recibo conserva el original y crea una copia auditada; un
original pendiente o fallido requiere atender ese trabajo, sin multiplicarlo. No hay FEL,
NIT, datos fiscales ni PDF inventados.

| Permiso | Alcance |
| --- | --- |
| `printing.manage_printers` | Configuración staff y alcance administrativo entre áreas |
| `printing.test_printer` | Prueba, junto con configuración staff |
| `printing.view_printjob` | Historial de caja del área y admin readonly según acceso staff |
| `printing.retry_print_job` | Reintentar trabajos fallidos |
| `printing.reprint_preparation_ticket` | Copias de comandas con motivo |
| `printing.print_customer_receipt` | Recibo solicitado y sus copias |
| `orders.cancel_quick_sale` | Anulación/liberación explícita de ventas sin entregar |

No se asignan permisos automáticamente por rol. Un mesero normal no recibe permiso de
reimpresión. Caja exige acceso PIN válido, estación/jornada/sesión activa y área propia;
`manage_printers` habilita alcance amplio en historial/servicios administrativos. Las
mutaciones exigen POST y CSRF, y se verifica actor activo, relaciones e impresora activa.

### Ajustes 2E: alias y existencias de ventas inconclusas

“Cobrar” reemplaza “Ver cobro”. Alias aparece si hay al menos un componente KITCHEN;
al retirar toda la comida se oculta sin vaciar el valor que se está escribiendo.

Rechazar transferencia/depósito de venta rápida libera su reserva de inventario y
conserva el pago rechazado. **Anular / liberar reserva**, con permiso y motivo, ofrece un
flujo explícito desde Ventas rápidas. Sin cobros/pagos pendientes/ajustes, anula la venta;
si hay alguno, libera stock y conserva la cuenta para resolver el dinero. No inventa
reembolsos ni elimina historia financiera. La anulación puede conservar pagos rechazados
o totalmente reembolsados; las asignaciones siguen siendo auditables.

Continuar el cobro, confirmar un pendiente o cerrar revalida productos/existencias y
reserva otra vez atómicamente. Si no alcanza stock, no confirma el nuevo pago ni emite
Cocina. Una venta sin entregar con reembolsos libera la reserva y requiere resolver el
resto/anular; no vuelve a entregarse. Se evita devolver doble inventario si un reembolso
solicita reposición después de liberar la reserva. Las ventas entregadas no se liberan por
este mecanismo. No existe expiración automática.

Antes de presentar el conteo ciego de caja se exige liberar reservas de ventas rápidas
inconclusas; así no quedan inmovilizadas al congelar la sesión. Resolver pagos antiguos
fuera de sesión sigue correspondiendo a los servicios administrativos existentes y la
futura interfaz de Gerencia.

### Migraciones y evidencia

Solo migraciones nuevas: `orders.0006_alter_tableorder_options_and_more` y
`printing.0001_initial`. No se modificaron migraciones históricas ni datos operativos.

La validación de esta fase y las capturas están en
[Verificación 2F](docs/phase-2f/verification.md). La compatibilidad real de marca/modelo,
red, papel, acentos, cutter y ausencia de papel queda pendiente de la instalación física.

## Fase 3A — Gerencia operativa

Acceso en `/gerencia/` mediante el login dedicado `/gerencia/acceso/`, con **username y
contraseña** del usuario actual. Se usa username porque ya es único; el email del modelo
no lo es. Solo entran usuarios activos `GERENTE` o `PROPIETARIO`, incluso si un usuario
de otro rol es superusuario. El rol permite entrar, pero no sustituye los permisos.
No se crea una app, modelo ni migración: la interfaz se organiza en
`apps/operations/management/{queries,services,views,security,middleware}.py`.

### Sesión, permisos y confirmaciones

La cookie Django `bigparty_management` está limitada a `/gerencia/`, es `HttpOnly`,
`SameSite=Lax` y `Secure` con settings de producción. La sesión es independiente de
Admin, tablet y Caja: abrir/cerrar Gerencia no autentica ni desconecta esas interfaces.
El middleware conserva la sesión original para las rutas anteriores. La autenticación,
rotación de sesión, hash de contraseña y revocación por cambio de contraseña siguen
usando Django. Todas las respuestas protegidas evitan caché.

`MANAGEMENT_IDLE_TIMEOUT_SECONDS = 30 * 60` centraliza el vencimiento. Se comprueban
actividad, rol y estado activo en cada solicitud. La interfaz informa actividad de
teclado, pulsación y desplazamiento; no hay polling que mantenga viva una sesión sin
uso. Las pestañas del mismo origen comparten señales de actividad; la decisión de
expiración sigue siendo del servidor. Tras vencer se requiere autenticar de nuevo.

| Operación | Permiso |
| --- | --- |
| Importes de Inicio, jornada y cajas | `cash.view_cash_session_financials` |
| Abrir jornada | `cash.open_business_day` |
| Cerrar jornada | `cash.close_business_day` |
| Reabrir jornada | `cash.reopen_business_day` |
| Consultar pagos pendientes | `payments.view_payment`, verificar o rechazar |
| Confirmar transferencia/depósito | `payments.verify_transfer_payment` |
| Rechazar transferencia/depósito | `payments.reject_transfer_payment` |
| Consultar historial de impresión | `printing.view_printjob` o `printing.manage_printers` |
| Reintentar/reimprimir desde Gerencia | `printing.manage_printers` y permiso de la acción existente |

Los importes del pago individual están disponibles a quien tiene permiso de revisión;
los resúmenes financieros de caja requieren su permiso específico. Los datos financieros
se omiten del HTML cuando falta permiso, incluidos diferencias y motivos financieros
entre las incidencias. Los accesos normales no dirigen al gerente a Admin.

Toda mutación usa POST y CSRF. El helper de confirmación exige checkbox explícito y un
valor firmado de diez minutos ligado a usuario, sesión, acción, objeto y revisión.
Cambios de sesión, pago o jornada invalidan la confirmación. Cierre y reapertura usan
modal; rechazar y reabrir exigen motivo. Los servicios toman la barrera transaccional
existente de caja/jornada, verifican IDs y vuelven a leer el estado antes de ejecutar
los servicios del dominio. No hay escritura directa de importes ni cálculo monetario
en JavaScript o templates.

### Inicio y semántica financiera

Inicio toma exclusivamente la `BusinessDay OPEN`. Sin ella muestra “No hay jornada
abierta” y ofrece apertura solo con permiso; entrar nunca abre una jornada. Las fechas
se agrupan por jornada comercial, aunque atraviese medianoche.

- **Ventas de la jornada:** consumo enviado bruto menos descuentos/cortesías y
  reembolsos, exactamente `get_business_day_summary().net_sales`. Puede incluir consumo
  aún por cobrar; la ayuda lo identifica como consumo neto y conserva sus componentes.
- **Mesas ocupadas:** mesas físicas distintas con vínculo activo y cuenta activa de la
  jornada. Una cuenta multimesa puede ocupar varias mesas.
- **Cajas abiertas:** sesiones `OPEN`, junto al número de estaciones activas. Cierres
  cuenta sesiones; una estación puede tener distintos turnos en una misma jornada.
- **Pendientes:** transferencias/depósitos pendientes, impresiones fallidas de órdenes
  de esa jornada, entregas de efectivo pendientes e inconsistencias importantes. No se
  suman todas las cuentas o cajas abiertas como si fueran alertas excepcionales.

“Ventas por hora” representa **cobros confirmados netos**, agrupados por `confirmed_at`
en hora local. Los reembolsos se descuentan de la hora del pago original, manteniendo
su componente separado. Las horas intermedias sin cobros aparecen en cero. Un pago
completamente reembolsado aporta cero neto, no desaparece del componente reembolsado.
Los pagos `PENDING` nunca suman a esta gráfica ni a la composición confirmada.

Ventas por área usa consumo neto e incluye TABLE y QUICK_SALE según `order.area`,
incluso si un área con ventas fue desactivada. Métodos distingue efectivo, tarjeta,
transferencia y depósito, usando confirmado menos reembolsos y mostrando pendientes
por separado. El efectivo cobrado por un mesero es un pago confirmado, pero solo entra
al efectivo esperado de una caja cuando se recibe su entrega.

La gráfica es SVG generado a partir de valores del servidor, con detalle accesible por
hora; no añade Chart.js ni dependencias. Requiere atención muestra como máximo cinco
items con enlace cuando existe pantalla y permiso. Reservas, Eventos y los demás
módulos futuros están deshabilitados y no tienen pantallas ficticias.

### Cierres y consulta de cajas

`/gerencia/cierres/` muestra la jornada actual o la última si no hay abierta, con selector
de las últimas 30 fechas y consulta directa de una jornada histórica por ID. Hay KPIs,
estaciones activas, cajero, apertura, último cierre, pendientes reales y acceso a cada
sesión. La tarjeta representa la sesión más reciente; la tabla mantiene accesibles todas
las sesiones de la fecha, incluidas anteriores o de estaciones ahora inactivas.

`/gerencia/jornada/<id>/caja/<session_id>/` es de consulta. Con permiso financiero muestra
fondo, cobros asociados, efectivo esperado, retiros, entregas recibidas, pendientes del
área, últimos 30 movimientos y métodos. Cerrada añade conteo, diferencia, motivo y
resultado cuadrada/faltante/sobrante. El detalle **no permite corregir importes**;
movimientos y conteo continúan en Caja. No se genera PDF.

“Ventas asociadas” de una caja son cobros netos de ventas rápidas de esa sesión más
pagos de efectivo vinculados por sus movimientos. No se atribuyen tarjetas o
transferencias de mesas a una caja solamente por coincidir el usuario: ese vínculo no
existe en el modelo. El total completo por método pertenece a la jornada.

El cierre utiliza `get_business_day_close_blockers()` sin sustituir sus reglas. Muestra
cada motivo, deshabilita el botón si hay pendientes y los recalcula dentro de
`close_business_day()` al confirmar. El resumen conserva ventas brutas, ajustes,
reembolsos, netas, métodos, resultados de cajas, retiros e incidencias. Diferencias ya
justificadas e impresiones fallidas se muestran para seguimiento, pero no se convierten
en nuevos bloqueos que el servicio de cierre no contempla.

Después aparece el resumen final con fecha comercial, hora y usuario. La reapertura
es un enlace discreto, exige permiso, motivo y confirmación y llama a
`reopen_business_day()`. Se mantienen `BusinessDayReopen` y auditoría existentes.
Reabrir la jornada no reabre las cajas cerradas. La consulta es del estado persistido
de la jornada; no pretende ser una nueva versión histórica inmutable de reportes.

### Revisión de pagos e impresión

`/gerencia/pagos-pendientes/` muestra solo TRANSFER/DEPOSIT `PENDING` de la jornada
abierta: mesa/pedido, monto, método, referencia, actor, hora y área. El detalle valida
la relación pago–jornada. Confirmar usa `confirm_pending_payment()`; rechazar usa
`reject_pending_payment()`. El pago se conserva y su motivo se presenta. La cuenta y
subcuentas se actualizan según los servicios actuales; la finalización explícita de
cuentas/ventas rápidas sigue en POS, no se agrega una regla de autocierre en Gerencia.
El mesero recibe el estado real al refrescar, sin WebSockets ni intervención en tablet.
No se añaden comprobantes de imagen.

`/gerencia/impresiones/` reutiliza consultas, acciones y la lista del historial de Fase
2F dentro de la sesión Gerencia. No reconstruye configuración de impresoras. Los enlaces
de las alertas no requieren iniciar otra sesión en Admin. No se implementa inventario
visual ni gestión de stock en esta fase.

### Consultas, pruebas y revisión

Los snapshots de lectura agrupan líneas, pagos, ajustes, asignaciones, reembolsos,
vínculos de mesas, sesiones y movimientos. Reutilizan `unit_ledger`, `_assert_ledger`
y resúmenes del dominio. Son transitorios y **no autorizan escrituras**; los servicios
vuelven a leer con bloqueos. La prueba de consultas compara una orden con nueve,
incluyendo pagos y reembolsos, para detectar crecimiento por orden.

Validación y capturas reales: [docs/phase-3a/VERIFICACION.md](docs/phase-3a/VERIFICACION.md).
No se inicia Fase 3B / Reservas.

## Fase 3B — Reservas normales

`apps/reservations` es el dominio propio de reservas. Gerencia incorpora
`/gerencia/reservas/`, filtros, búsqueda, revisión, creación interna y configuración.
No se implementan eventos, QR, entradas, mapa público premium, reportes de reservas,
SMS, gateway ni envío automático de WhatsApp.

### Modelos y configuración

- `ReservationSettings`: configuración global singleton (id=1); en ausencia de fila
  usa valores iniciales sin escribir desde GET. Reservas habilitadas, duración 180 min,
  retención pública 15 min, ventana de transferencia 15 min y anticipo deshabilitado.
  Gerencia puede ajustar estos valores con `configure_reservations`.
- `Reservation`: tipo `NORMAL`, mesa/área, nombre/teléfono internacional, fecha/hora,
  duración, personas, inicio/fin con zona horaria, condiciones de anticipo congeladas
  al aprobar, responsables/fechas/motivos y relación única con `TableOrder` al llegar.
  El teléfono incluye prefijo de país, por ejemplo `+502 5555 5555`.
- `ReservationPayment`: transferencia independiente de los pagos de cuenta; monto,
  referencia, comprobante privado, revisión y motivo. Una reserva admite un envío;
  el rechazo es terminal y una nueva solicitud obtiene nuevos identificadores.
- `ReservationCredit` y `ReservationCreditAllocation`: origen del prepago confirmado
  y asignación persistida por unidad de consumo. No son descuentos ni pagos de caja.

Anticipo `FIXED` (Q) o `PERCENTAGE` (%). Para porcentaje, **Gerencia ingresa el consumo
estimado como base** (`payment_base_amount`); se conserva el cálculo y se redondea a
centavos con `ROUND_HALF_UP`. No se infiere un precio por persona ni por mesa.
`CREDIT` significa abono al consumo; `FEE`, cargo de reserva que no reduce la cuenta.
Los cambios de configuración afectan aprobaciones y creaciones posteriores, no los
importes ya aprobados. Habilitar/deshabilitar reservas controla nuevas solicitudes;
las existentes conservan su flujo y sus compromisos.

### Disponibilidad y concurrencia

`get_available_tables(date, time, duration, party_size=None, area=None)` devuelve
mesas activas, de áreas activas, en servicio, reservables en web y con capacidad
suficiente. Usa intervalos semiabiertos `[inicio, fin)`; admite cruce de medianoche
y reservas consecutivas. Retienen el intervalo:

- `PENDING_REVIEW` mientras `hold_expires_at > now`.
- `AWAITING_PAYMENT` mientras `payment_expires_at > now`.
- `PAYMENT_REVIEW` hasta decisión humana, sin expiración automática.
- `CONFIRMED` hasta llegada, cancelación o no-show.
- `ARRIVED` conserva su intervalo mientras su cuenta siga activa; cerrar la cuenta
  lo libera. Así una llegada anticipada no permite reservar de nuevo el mismo tramo.

Los vencimientos dejan de bloquear inmediatamente aunque el comando aún no corra.
Los GET muestran “Expirada” como estado efectivo y no mutan registros. El comando
persiste `EXPIRED` y su auditoría. La disponibilidad actual también considera cuentas
activas; una cuenta abierta no permite predecir disponibilidad futura: Gerencia
resuelve cualquier mesa aún ocupada al recibir al cliente.

`create_public_reservation_request(...)` revalida dentro de `transaction.atomic`.
Todas las escrituras usan el mismo bloqueo asesor transaccional de la instalación
que caja (`lock_operation_gate`) y bloquean reserva/mesa con `select_for_update`.
La llegada toma primero la jornada abierta; este orden es coherente con apertura,
traslado, unión, cobro y cierre. Las dos solicitudes concurrentes no pueden confirmar
una misma disponibilidad. Los servicios son la frontera de escritura; no se admiten
actualizaciones directas de estados desde Admin ni formularios genéricos.

Se evaluó `ExclusionConstraint`: un predicado estático no representa los holds
activos según `now()` sin materializar sus vencimientos primero. En esta fase se
elige bloqueo transaccional + validación dentro del bloqueo, conservando la barrera
ya existente del local. No se agrega `btree_gist`. La base impone unicidad de token,
código, pago por reserva, crédito por pago, llegada por cuenta y asignación por
unidad, además de intervalos/montos/cantidades positivos. Índices: estado, fecha,
mesa+fecha e inicio; token/código tienen índices únicos. La serialización global
es deliberada para una instalación; escalar a varios locales requiere revisar la
clave y granularidad del bloqueo antes de permitir escritores independientes.

### Servicios y estados

`create_public_reservation_request(table, customer_name, customer_phone, date,
time, party_size)` → `PENDING_REVIEW`. No requiere ni crea jornadas futuras.

`create_manual_reservation(..., user, duration=..., payment_required=..., ...)`
crea `CONFIRMED` o `AWAITING_PAYMENT`, sin hold previo. Admite mesas internas no
habilitadas en web, siempre activas, con capacidad y sin solapamientos.

`approve_reservation` confirma sin pago o abre la ventana de transferencia.
`reject_reservation` exige motivo y libera la retención. Los servicios de pago son
`submit_reservation_payment`, `confirm_reservation_payment` y
`reject_reservation_payment`; los estados recorren:

`PENDING_REVIEW → AWAITING_PAYMENT → PAYMENT_REVIEW → CONFIRMED → ARRIVED`.

Sin anticipo, aprobación pasa directamente a `CONFIRMED`. El rechazo del pago lleva
pago y reserva a `REJECTED`, con motivo obligatorio. `cancel_reservation` conserva
registros y exige motivo cuando hay compromiso confirmado o anticipo; la interfaz
siempre pide motivo. `mark_reservation_no_show` es explícito, solo para confirmadas
a partir de su hora, con motivo opcional. No hay devolución automática; pagos
confirmados y pagos pendientes de una reserva cancelada se conservan para posterior
resolución humana. Una reserva llegada ya se opera desde su cuenta, no se cancela
retroactivamente como reserva.

Cada transición, expiración, cambio de configuración y asignación de crédito produce
`AuditLog`. El código público `BP-R-` usa diez caracteres aleatorios no ambiguos;
no sirve como secreto. `secure_token` usa 32 bytes criptográficamente aleatorios.

### Página privada, comprobantes y WhatsApp

`/reservas/r/<secure_token>/` permite únicamente consultar esa reserva y enviar su
transferencia mientras la ventana sea válida. No hay búsqueda pública por teléfono
ni endpoint de enumeración. La página no muestra nombres/teléfonos de clientes,
IDs internos ni motivos internos; usa CSRF, `no-store`, `noindex` y política de
referencia `same-origin`. Esta última conserva CSRF en formularios sin compartir el
URL privado con otros sitios; los enlaces externos usan `noreferrer`.
Referencia técnica: [CSRF de Django 5.2](https://docs.djangoproject.com/en/5.2/ref/csrf/).

El importe debe coincidir exactamente con el aprobado y la referencia es obligatoria.
Comprobante obligatorio para solicitudes públicas; opcional para reservas internas.
Se verifica el contenido real con Pillow: JPEG/PNG/WebP, máximo 5 MB, y rechazo de
imágenes inválidas o con riesgo de descompresión excesiva. No hay OCR.

Los comprobantes se guardan fuera de `MEDIA_ROOT`, en
`private/reservation-proofs/` (`RESERVATION_PROOF_ROOT`), ignorado por Git. No tienen
ruta pública de medios. Gerencia los sirve mediante una vista autenticada con permiso
de consulta de reservas, MIME verificado, `nosniff` y caché privada deshabilitada.
Incluir ese directorio en respaldos privados; no publicarlo mediante el servidor web.

Configurar `PUBLIC_BASE_URL` con la URL externa del establecimiento, usando HTTPS
en despliegue. Los enlaces `wa.me` llevan mensajes prellenados de aprobación,
anticipo, confirmación o rechazo genérico humanizado; no se copian motivos internos.
El operador revisa y envía manualmente. No se llama a WhatsApp ni se envían mensajes
desde el servidor. Los datos de la cuenta bancaria se proporcionan por el local;
no se inventan en la página de pago.

### Llegada y crédito trazable

`confirm_reservation_arrival(reservation, user, responsible_waiter)` requiere
reserva confirmada, mesa/área activas, mesa libre, jornada `OPEN` y selección de
un usuario activo con rol `MESERO`. Solo exige el permiso específico de llegada;
reutiliza la primitiva interna de apertura, sin asignar permisos a roles.
Crea una única cuenta `SINGLE`, `opened_by` es quien confirma y conserva `party_size`
como dato histórico. No calcula cargos por ausencias de personas. La llegada humana
puede adelantarse o retrasarse, pero no desplaza otra retención vigente ni una cuenta
ocupada. Gerencia debe revisar la fecha y mesa antes de confirmar.

Si hubo anticipo `CREDIT`, crea crédito disponible al vincular la cuenta. Al enviar
consumo, lo asigna por orden de líneas/unidades a saldo disponible, dentro de la
misma transacción. Ejemplo verificado:

| Concepto | Importe |
|---|---:|
| Consumo comercial | Q800.00 |
| Anticipo confirmado de reserva | Q300.00 |
| Saldo por cobrar en mesa | Q500.00 |

No crea `Payment CASH/CARD/TRANSFER` ni ajuste falso. El historial financiero,
cuenta tablet/Caja y recibo muestran el anticipo separado. Ventas netas siguen en
Q800; cobrar los Q500 restantes suma Q500 al método usado. El prepago ya recibido
se conserva en reservas y no se cuenta nuevamente como cobro de la jornada de
llegada. Reportes de anticipos/obligaciones quedan para una fase futura.

Un anticipo superior al consumo conserva el remanente, incluso al cerrar la cuenta;
no se devuelve, borra ni convierte en propina. Refund del anticipo es una decisión
posterior. Las líneas cubiertas por crédito no se anulan ni trasladan por fuera del
historial financiero. En esta fase las cuentas con crédito conservan `SINGLE` y no
se fusionan con otras cuentas; se evita redistribuir dinero sin una regla explícita.
Los reembolsos normales no pueden superar los pagos normales ni devolver el crédito.

El mapa deriva estados con prioridad:
`OUT_OF_SERVICE > PAYMENT_PENDING > PARTIALLY_PAID > OCCUPIED > RESERVED > AVAILABLE`.
`RESERVED` requiere una reserva confirmada cuyo intervalo contiene el momento actual.
No se guarda en `VenueTable`. Abrir/trasladar/unir a esa mesa por el flujo ordinario
se bloquea; la tablet indica que Gerencia debe registrar la llegada.

### Permisos y administración

Permisos independientes, **sin asignación automática por rol**:
`view_reservations`, `create_reservation`, `approve_reservation`,
`reject_reservation`, `verify_reservation_payment`, `reject_reservation_payment`,
`cancel_reservation`, `confirm_reservation_arrival`, `mark_reservation_no_show`,
`configure_reservations` (app label `reservations`).

Gerencia mantiene su autenticación y sesión aisladas. Consulta y acciones verifican
permisos en servidor; transiciones sensibles además usan confirmación firmada con
usuario, sesión, acción, reserva y revisión. Se rechazan formularios obsoletos.
Admin registra los tres modelos principales como consulta: no agrega, elimina ni
edita estados o pagos. La configuración se modifica en Gerencia mediante servicio.

### Expiración, migración y verificación

```bash
python manage.py migrate
python manage.py expire_reservation_holds
python manage.py expire_reservation_payments
python manage.py check
python manage.py makemigrations --check
python manage.py test
node --test apps/operations/tests/*.test.mjs
```

Los comandos son idempotentes y no alteran `PAYMENT_REVIEW`. No se instala Celery
ni se programa cron todavía. Un futuro proceso del nodo puede invocarlos cada minuto.
Migración `reservations.0001_initial` sin cambios de datos en cuentas existentes.

Verificación de esta fase: **780 pruebas Django (61 nuevas) y 7 JavaScript**.
La expectativa anterior de mesa genéricamente ocupada después de abonar se actualiza
a `PARTIALLY_PAID`, de acuerdo con la prioridad solicitada. En Gerencia Inicio la
serie se llama “Cobros confirmados por hora”; ventas siguen siendo consumo neto y
las alertas de entregas pendientes muestran mesa/monto, sin usuario técnico ni ID.

Escenarios A–E, capturas reales de 1280×800 y decisiones de revisión visual:
[Verificación Fase 3B](docs/phase-3b/VERIFICACION.md).

La Fase 3B quedó completada; la implementación de Eventos se documenta a continuación.

## Fase 3C — Eventos, entradas, aforo y acceso

`apps.events` es un dominio independiente de `apps.reservations`. No añade campos
ni migra datos de reservas normales, órdenes o pagos comerciales. Sus ventas no se
mezclan con consumo, anticipos de reserva ni cobros de una jornada de Caja.

### Modelos y creación

| Modelo | Responsabilidad |
|---|---|
| `Event` | Información, imagen, intervalo con zona horaria, aforo y estado |
| `EventSettings` | Retención, ventana de pago e instrucciones de transferencia |
| `EventTicketType` | Precio, cupo individual, ventana de venta, máximo por compra y cortesía |
| `EventTableConfiguration` | Mesa habilitada, capacidad snapshot, tipo de acceso y cover por persona |
| `EventPurchase` | Comprador, estado, plazos, código público y secreto del portal |
| `EventPurchaseItem` | Cantidad y precio unitario histórico de cada tipo |
| `EventTableReservation` | Una mesa completa, importe histórico y estado propio |
| `EventPurchasePayment` | Transferencia declarada, referencia, comprobante privado y revisión |
| `EventTicket` | Un acceso individual, número humano, secreto QR y trazabilidad de uso/cancelación |
| `EventScheduleHistory` | Fechas anteriores/nuevas, autor y motivo de reprogramación |
| `GuardLoginAttempt` | Límite de intentos de PIN por usuario/IP con identificadores HMAC; nunca guarda PIN |

Gerencia activa **Eventos** en `/gerencia/eventos/`. El asistente guarda el borrador
tras el paso 1 y continúa con entradas, mesas/aforo y revisión/publicación. Usa
Inter, carbón y champagne del sistema existente. Las fechas de inicio y fin son
explícitas: 3 oct 21:00 → 4 oct 03:00. No se supone que termina el mismo día.
No se crean tipos de entrada automáticamente.

Estados: `DRAFT`, `PUBLISHED`, `RESCHEDULED`, `FINISHED`, `CANCELLED`.
“En curso” se deriva del intervalo en eventos publicados/reprogramados. Publicar
requiere imagen, fechas coherentes, aforo positivo, entradas de venta activas si
la venta está habilitada y configuración dentro del límite. El servicio devuelve
errores estructurados para la revisión. No se elimina mediante interfaz/Admin.

`duplicate_event` copia únicamente información, tipos, mesas, cover y capacidades;
crea otro slug y `DRAFT`, sin fecha de publicación, compras, pagos, entradas ni
historial de accesos. La imagen existente se referencia como archivo inmutable;
reemplazarla en un evento no cambia la del otro.

### Capacidad y concurrencia

La capacidad configurada es **cuotas individuales activas + capacidad de mesas
habilitadas**. Cortesías forman parte de la cuota individual. Los compromisos de
un tipo desactivado siguen reservando su parte del aforo. Publicar o editar un
evento publicado no permite superar el máximo ni reducir cuotas por debajo de
lo comprometido.

Ejemplo: Preventa 200 + General 340 + VIP 150 + Cortesía 50 = 740; diez mesas de
seis personas = 60; total 800. Una mesa VIP de seis personas con cover Q100 cuesta
Q600 y emite seis entradas VIP, **sin consumir otros seis lugares de la cuota
individual VIP**. No hay consumo mínimo, depósito adicional ni compra parcial de
una mesa. La capacidad snapshot nunca sigue cambios posteriores de `VenueTable`.

`get_event_capacity_summary` devuelve máximo, holds, individuales vendidos,
cortesías, accesos de mesas, utilizados y restante. Cuenta tickets vigentes
(`VALID`/`USED`) una sola vez; una reserva confirmada no añade otra vez sus seis
personas. `USED` equivale a un ingreso, sin salidas ni reingreso. Tras cancelar,
el aforo vigente deja de contar las entradas, pero los indicadores históricos de
entradas vendidas y los pagos se conservan.

Todos los servicios que modifican cupos bloquean primero la fila de `Event` dentro
de `transaction.atomic()`. Después bloquean compra/pago o ticket, siempre en ese
orden. PostgreSQL decide la disponibilidad al escribir. También se serializan
ediciones de configuración, cortesías, expiración, cancelación y snapshots.
No hay contadores redundantes, colas ni consistencia eventual.

La disponibilidad de mesa es **por evento**. Las reservas normales conservan su
agenda y comportamiento; esta fase no integra ni reasigna mesas de la operación
normal. La planificación de eventos y reservas normales debe coordinarse en Gerencia.

### Compras, retenciones y transferencias

`/eventos/<slug>/` acepta eventos `PUBLISHED` y `RESCHEDULED`. La reprogramación es
un estado público informativo, compatible con nuevas ventas. Una compra contiene
varios tipos individuales **o** una mesa completa. La mezcla de ambas modalidades
en una compra queda excluida deliberadamente.

Un tipo individual se ofrece solo si está activo, tiene precio positivo, no es
cortesía, su ventana inclusiva ya comenzó y no terminó, quedan cuota y aforo y el
evento permite ventas. No se activa un tipo futuro por agotarse otro. No se vende
tras el fin del evento. Cortesías Q0 se emiten desde Gerencia, con permiso explícito,
autor, cantidad y motivo opcional; no requieren transferencia ficticia.

`create_purchase` valida límites, nombre/teléfono y precios en servidor y toma
snapshots. `PENDING_PAYMENT` retiene cupo. Los dos plazos comienzan al crear la
compra; vence el primero entre retención y ventana de pago, ambos de 15 minutos
por defecto. Se configuran en `/gerencia/eventos/configuracion/` y aplican a nuevas
compras. Configura allí las instrucciones bancarias reales antes de abrir ventas.
No se inventa una cuenta bancaria.

`submit_event_payment` exige referencia, imagen real y monto exactamente igual al
total. Cambia a `PAYMENT_REVIEW`: ya no expira automáticamente. Confirmar registra
revisor/fecha, marca compra y transferencia `CONFIRMED` y emite exactamente N tickets.
La confirmación y `generate_purchase_tickets` son idempotentes. Rechazar exige
motivo y libera cupos/mesa sin emitir tickets. No se confirma editando un dropdown.

```bash
python manage.py expire_event_purchases
```

El comando es idempotente, solo expira `PENDING_PAYMENT` vencidas y sincroniza el
estado de la reserva de mesa. Las consultas ignoran holds vencidos aunque aún no
se haya ejecutado el comando. No se instala un programador en esta fase.

### Portal, QR y PDF

`/eventos/compra/<secure_token>/` es un portal privado sin login que muestra solo
esa compra. El token tiene 256 bits aleatorios y es independiente de cada QR.
El código humano `BP-C-…` y el número `BP-E26-…` no son secretos ni sirven para
acceder al portal. Los números de ticket usan sufijo aleatorio único para evitar
secuencias globales innecesarias.

Los QR contienen únicamente `PUBLIC_BASE_URL/entrada/<qr_token>/`; no incluyen
nombre, teléfono, importe ni el secreto del portal. La página individual tampoco
muestra esos datos. El portal confirmado permite descargar un PDF individual o
un PDF combinado, **una entrada por página**, nunca un ZIP. El comprador distribuye
cada QR sin nombrar invitados. Las cortesías se pueden volver a consultar/descargar
en Gerencia (las 30 más recientes); la emisión redirige para evitar repetición por
refrescar un POST.

Se usa [qrcode](https://pypi.org/project/qrcode/) para PNG dinámico y
[ReportLab](https://docs.reportlab.com/install/open_source_installation/) para PDF,
sin navegador ni dependencia de conversión del sistema. El PDF contiene evento,
fecha, tipo, número, QR, estado y comprador; el portal controla la descarga. Con
los mismos datos y `PUBLIC_BASE_URL` produce los mismos bytes. Reprogramar/cancelar
se refleja en las siguientes descargas, conservando el QR. El PDF no consulta
precios actuales ni altera estados.

Los enlaces manuales `wa.me` tras confirmar/rechazar incluyen el portal construido
con `PUBLIC_BASE_URL`. No hay API, envío automático ni contacto realizado por el
servidor. Gerencia decide si abre y envía el mensaje.

### Guardia, seguridad y operación local

`/acceso/` usa usuario + PIN existente en `accounts.User`, rol activo `GUARDIA` y
`events.scan_event_ticket`. No asigna permisos por rol. La cookie HttpOnly
`bigparty_access`, limitada a `/acceso/`, es independiente de Gerencia/Admin/Tablet.
Expira a los 30 minutos de inactividad. Cinco intentos fallidos bloquean durante
cinco minutos; permisos y elegibilidad se comprueban en cada solicitud.

El guardia solo ve resultado, evento, tipo y hora original si ya fue utilizada.
No puede consultar compradores, importes ni administración. `validate_and_use_ticket`
bloquea evento/ticket, registra el primer `VALID → USED` y devuelve `USED` en el
segundo intento sin sobrescribir hora/guardia. Evento cancelado responde `CANCELLED`;
evento finalizado no admite ingresos. No se impone una ventana horaria adicional
al escaneo: Gerencia habilita mediante publicación y cierra manualmente al finalizar.

El lector [Nimiq qr-scanner](https://github.com/nimiq/qr-scanner) 1.4.2, incluido con
licencia MIT en `static/vendor/qr-scanner`, utiliza la cámara tras pulsar Activar.
Necesita HTTPS en teléfonos; localhost permite desarrollo. Pausa entre resultados
y permite continuar con Siguiente entrada. Si no hay conexión, no muestra un acceso
válido local inventado. Se probó decodificación real de PNG con el mismo lector;
**no se probó una cámara física de teléfono**. Los campos de token/imagen de prueba
solo se renderizan con `DEBUG=True`; no son búsqueda de compradores ni UI de producción.

Todas las mutaciones HTTP conservan CSRF. Revisión de pago usa confirmación firmada
con usuario/sesión/compra/versión; reprogramar/cancelar/finalizar/cortesías requieren
confirmación explícita del formulario. Los servicios vuelven a validar permisos,
estados y cupos. Portal, QR, PDF y comprobantes no se cachean ni se indexan; se usa
`Referrer-Policy: same-origin` para conservar CSRF y evitar filtrar tokens a terceros.

Imagen de evento y comprobantes: JPEG, PNG o WebP reales, hasta 5 MB, verificados
con Pillow; la extensión se normaliza según el formato leído. Comprobantes viven en
`private/event-proofs/`, fuera de `MEDIA_ROOT`; solamente Gerencia con permiso de
compras puede leerlos. Respalda ese directorio como información privada. Admin
registra todos los modelos solo para lectura, sin mutaciones de pagos/estados.

### Reprogramar, cancelar y preparar snapshots

`reschedule_event` exige motivo y guarda `EventScheduleHistory`. Conserva todos
los tokens y no desplaza automáticamente las ventanas de venta de los tipos;
Gerencia puede ajustar esas ventanas con su permiso. `cancel_event` exige motivo,
cancela todas las entradas (también las utilizadas), preserva sus datos de uso,
compras confirmadas y pagos, y cancela las compras aún sin confirmar. No ejecuta
reembolsos. Los portales muestran la cancelación. `finish_event` usa `change_event`
y requiere resolver comprobantes pendientes; no hay cron de finalización.

`build_event_access_snapshot` devuelve evento/identificador/estado, `generated_at`,
`schema_version=1`, checksum/version SHA-256 determinista y tickets con hash SHA-256
del token, estado y tipo. Incluye utilizados/cancelados para permitir futuras
revocaciones; nunca nombre, teléfono, importe ni token del portal. Obtiene un corte
coherente bajo el mismo bloqueo del evento. Es una función interna exportable;
no hay endpoint público de descarga, Local Node ni protocolo de sincronización.

### Permisos, migración y comprobación

Permisos `events`: `view_events`, `create_event`, `change_event`, `publish_event`,
`duplicate_event`, `reschedule_event`, `cancel_event`, `manage_event_ticket_types`,
`manage_event_tables`, `view_event_purchases`, `verify_event_payment`,
`reject_event_payment`, `issue_courtesy_tickets`, `view_event_capacity`,
`scan_event_ticket`. Asignarlos explícitamente a usuarios/grupos autorizados.
Configurar plazos/finalizar reutiliza `change_event`; no se añade otro permiso implícito.

Auditoría: creación/edición/publicación, tipos/mesas, duplicación, reprogramación,
cancelación de evento/tickets, compras, comprobantes/revisión, emisión de entradas,
cortesías, expiración y escaneos válidos/duplicados. No registra secretos QR/portal.
Única migración nueva: `events.0001_initial`, con índices de estado/fecha, relaciones
y unicidad de tokens/números. No cambia migraciones históricas de otras apps.

```bash
python -m pip install -r requirements/dev.txt
python manage.py migrate
python manage.py check
python manage.py makemigrations --check
python manage.py test
node --test apps/operations/tests/*.test.mjs
```

Resultado final: **859 pruebas Django (79 nuevas) y 7 JavaScript**. Ocho pruebas de
concurrencia usan conexiones PostgreSQL distintas e hilos simultáneos; cubren última
cuota, última mesa, aforo global, doble confirmación/generación, dos guardias,
confirmar/rechazar y escanear/cancelar.

[Verificación y capturas 3C](docs/phase-3c/VERIFICACION.md) y
[evidencia de dominio](docs/phase-3c/verificacion-dominio.json).
No se implementan gateway, envíos automáticos, devoluciones, Local Node, sincronización
cloud ni sitio premium. La Fase 3D se documenta en la sección siguiente.

## Fase 3D — Inventario, catálogo, usuarios y permisos

Gerencia incorpora **Inventario** (`/gerencia/inventario/`) y **Usuarios**
(`/gerencia/usuarios/`) desde Administrar en Inicio. El encabezado conserva Inicio,
Cierres, Reservas y Eventos. Reportes, Auditoría y Configuración siguen pendientes.
Una alerta agregada enlaza los productos activos con stock bajo o agotado; no suma
cada producto al contador de pendientes de la jornada.

### Inventario y catálogo

- Listado paginado de 25 productos, búsqueda por nombre/identificador, categoría y
  estados derivados: Disponible, Stock bajo, Agotado y Sin control. Los indicadores
  cuentan productos activos; el listado también permite editar productos inactivos.
  Stock bajo excluye agotados para evitar duplicarlos en los indicadores.
- Atención muestra hasta 10 productos, ordenados por existencias ascendentes.
  Los combos no tienen inventario propio: su detalle muestra disponibilidad y
  máximo calculados por `get_combo_max_available()` con los componentes existentes.
- Entrada usa `receive_stock()`; ajuste usa `adjust_stock()`, cantidad positiva,
  dirección Aumentar/Reducir y motivo obligatorio. Se conservan bloqueos, movimientos
  y auditoría. Ninguna pantalla habilita vender existencias agotadas.
- Movimientos son de sólo lectura, con paginación y filtros por producto, tipo y día
  local. El detalle muestra los últimos 10; el enlace Ver todos conserva el producto.
- Crear/editar productos no admite `stock_quantity`, aunque se envíe manualmente.
  Crear empieza en cero; las existencias iniciales se reciben después. Formularios
  separados por Información, Precio, Inventario y Preparación. Activar/desactivar
  conserva historial; no hay borrado de productos ni categorías desde Gerencia.
- Precio general se actualiza mediante `update_base_price()`, incluso al crear.
  Establecer/modificar un precio especial usa `update_area_price()`; quitarlo usa
  `remove_area_price()`, registra el regreso al precio general y auditoría explícita
  de eliminación del precio especial. El detalle muestra los últimos 15 cambios.
  Todos requieren `catalog.change_product_price`; sin él el precio está bloqueado.
- Categorías permiten nombre, identificador, descripción, orden numérico y estado.
  Modificadores permiten grupos y opciones, selección única/múltiple, límites,
  obligatoriedad, orden, precio adicional y activación. No se añade stock a opciones.
  Componentes de combos se agregan/editan/retiran con sus validaciones existentes;
  no permiten autoreferencia ni combos anidados.
- Imagen opcional con vista previa; se valida contenido real JPEG/PNG/WebP, hasta
  5 MB, y se normaliza la extensión. No se añaden dependencias ni procesamiento pesado.
- Lecturas requieren `inventory.view_inventory`. Entradas/ajustes y precios usan
  sus permisos explícitos; edición de catálogo usa los permisos Django del modelo.
  Las pantallas cargan relaciones de forma conjunta y paginan listados.

### Usuarios y credenciales

Se reutiliza `accounts.User`. La lista busca nombre/apellido/usuario y filtra roles
MESERO, CAJERO, GERENTE, PROPIETARIO, GUARDIA o inactivos. Último acceso toma el mayor
entre `last_login` y la creación de sesiones de tablet/caja; si no existe registro,
se muestra así. Sólo se informa si el PIN está configurado, nunca sus hashes.

Crear Mesero/Cajero/Guardia exige PIN inicial y confirmación, de **4–6 dígitos**.
Gerente/Propietario exige contraseña y confirmación con los validadores Django.
Se usan `set_pin()` y `set_password()`; no hay contraseñas predeterminadas. Se conserva
la compatibilidad del modelo con PIN históricos de 4–12 dígitos; los nuevos PIN de
Gerencia se limitan a 4–6, como la operación tablet/caja. Se rechazan identificadores
que colisionen ignorando mayúsculas para evitar ambigüedad en el ingreso de guardias.

El detalle ofrece identidad, rol, credenciales, permisos y actividad administrativa
reciente. Restablecer PIN abre un modal sin revelar el anterior. Revoca las sesiones
PIN existentes de tablet/caja; Guardia verifica la huella de credenciales en cada
request. Cambiar sólo PIN no cierra Gerencia. Cambiar contraseña invalida las sesiones
Django anteriores mediante su hash de autenticación. No hay correo ni perfil propio
nuevo; los cambios de contraseña de esta fase son administrativos.

Desactivar requiere confirmación firmada, vinculada a sesión/usuario/estado y con
caducidad. Impide nuevos ingresos y bloquea cookies antiguas; se preserva historial.
El último propietario activo no puede desactivarse ni cambiar de rol. Las escrituras
de usuarios comparten una puerta transaccional de PostgreSQL y bloqueo de usuario,
por lo que dos desactivaciones simultáneas tampoco dejan cero propietarios activos.
Es una protección de la interfaz/servicios normales; Django Admin sigue siendo técnico.

### Matriz de permisos y seguridad

`apps/accounts/permissions.py` publica únicamente permisos especiales declarados en
modelos de negocio seleccionados y una lista explícita de permisos estándar útiles.
Se agrupan en Operación, Caja, Inventario, Reservas, Eventos, Gerencia, Impresión y
Usuarios. Todos se resuelven contra `auth.Permission`: no hay otra matriz ni grupos
nuevos. Los permisos heredados de grupos existentes se muestran como tales y no se
retiran aquí; tampoco se alteran permisos técnicos fuera de la lista expuesta.

Cambiar rol **no cambia permisos**. Los permisos sugeridos requieren confirmación y
son **aditivos**, auditables y editables después. Mesero/Cajero incluyen acceso y
operación habitual; Gerente recibe sugerencias de consulta; Propietario puede aplicar
el catálogo completo con confirmación; Guardia sólo escaneo. Nada se concede por una
condición global de rol Propietario. Superuser/staff permanecen fuera del formulario.

Para cambiar a Guardia se exige retirar explícitamente los permisos incompatibles.
No se borran silenciosamente. Si provienen de grupos o son permisos técnicos no
expuestos, se resuelven en Django Admin. La matriz de Guardia ofrece sólo escanear.

Además de `accounts.view_user`, `add_user` y `change_user`, la migración
`accounts.0002_alter_user_options` crea únicamente:

| Permiso | Acción |
| --- | --- |
| `reset_user_pin` | Restablecer PIN |
| `change_user_credentials` | Cambiar contraseña administrativa |
| `change_user_role` | Cambiar rol base |
| `activate_user` | Activar/desactivar |
| `manage_user_permissions` | Asignar/retirar permisos y aplicar sugerencias |

Cada operación exige sesión Gerencia, POST, CSRF y su permiso. No se asignan estos
permisos automáticamente a cuentas reales. Un administrador sólo puede administrar
permisos que posee y no puede editar/recuperar una cuenta más privilegiada, incluso
inactiva. Las cuentas técnicas staff/superuser requieren un superusuario técnico.
Edición de identidad/permisos compara una revisión del estado leído bajo bloqueo;
si otro administrador lo cambió, se pide actualizar en lugar de sobrescribir.

Auditoría registra actor, destinatario y fecha para altas, identidad, rol, estado,
PIN/contraseña, adiciones/retiros de permisos y sugerencias. Credenciales y hashes no
aparecen en auditoría, mensajes o formularios renderizados. Parámetros sensibles y
variables de credenciales se marcan para su exclusión de reportes de errores en producción.
Las herramientas de prueba de `/acceso/` sólo se renderizan con `DEBUG=True`.

### Verificación 3D

La suite incluye pruebas de interfaz, permisos, CSRF, imágenes inválidas, stock no
editable, historial de precios, modificadores, combos, credenciales y sesiones,
escalamiento de privilegios, última administración y concurrencia real con conexiones
PostgreSQL separadas. Evidencias, recorrido manual y capturas A–J en
[verificación 3D](docs/phase-3d/VERIFICACION.md). No se implementa Fase 3E.

Resultado verificado de Fase 3D: **902 pruebas Django (43 nuevas) y 7 JavaScript**.
Las capturas y pruebas de recorrido usan una base aislada eliminada al terminar.

## Fase 3E — Reportes, auditoría y configuración

Gerencia incorpora `/gerencia/reportes/`, `/gerencia/auditoria/` y
`/gerencia/configuracion/`. El encabezado conserva Inicio, Cierres, Reservas y
Eventos. Los enlaces de Administrar requieren permisos individuales; el rol
Gerente o Propietario no concede acceso por sí solo.

### Reportes y significado de los importes

Se ofrecen diez reportes: resumen de jornada, productos, áreas, meseros, cajas,
pagos, cancelaciones/reembolsos, descuentos/cortesías, reservas y eventos.
El periodo permite jornada abierta, fecha comercial específica o rango inclusivo
de hasta **93 días**. Ventas, pagos, ajustes, reembolsos, entregas y sesiones de caja
se seleccionan mediante `BusinessDay`, no mediante la fecha civil de creación.
Una venta después de medianoche conserva la jornada a la que pertenece. Los
pedidos históricos sin jornada no se asignan implícitamente a una fecha.

- **Bruto:** cantidad × precio final de las líneas `SENT`, incluidos modificadores.
  Borradores y líneas anuladas no son ventas. Un combo cuenta como producto
  comercial; sus componentes solo representan consumo de inventario.
- **Ajustes y reembolsos por producto/área/mesero:** asignaciones efectivas a las
  líneas, sumadas por separado para evitar multiplicar filas al combinar relaciones.
  **Consumo neto = bruto − ajustes − reembolsos.**
- **Cobros confirmados netos:** pagos `CONFIRMED` o `REFUNDED` menos sus
  reembolsos. Pendientes y rechazados aparecen en columnas independientes.
  Deshabilitar un método no elimina su información del reporte.
- **Abonos de reserva aplicados:** solo `ReservationCreditAllocation` aplicado
  a consumo enviado; el crédito disponible todavía no utilizado no reduce el saldo.
  **Saldo = consumo neto − cobros confirmados netos − abonos aplicados.**
  Estos abonos no se suman otra vez como un ingreso nuevo del punto de venta.
- Los pedidos por área incluyen mesas y ventas rápidas. Los conteos excluyen el
  contenedor `MERGED` para no duplicar cuentas; los vínculos históricos permiten
  contar mesas distintas. La categoría del producto es la categoría **actual**;
  su nombre comercial viene de la instantánea de la línea.
- El reporte de meseros distingue responsabilidad comercial (`responsible_waiter`),
  cobros registrados por usuario (`recorded_by`) y entregas (`CashHandoff.waiter`).
  No es un ranking de desempeño.
- Caja: fondo + ingresos directos + entregas − retiros − reembolsos en efectivo.
  Contado y diferencia solo se presentan para sesiones cerradas. No se introducen
  nuevas reglas de liquidación ni cierres automáticos.
- Cancelaciones y reembolsos son secciones distintas. La anulación presenta un
  importe informativo y comprueba las devoluciones de inventario registradas;
  los reembolsos muestran el dinero efectivamente devuelto. Se diferencian
  borradores retirados, productos enviados anulados y ventas rápidas anuladas.
- **Reservas y eventos no tienen una FK propia a BusinessDay.** Sus reportes usan
  las fechas programadas locales dentro del mismo intervalo de fechas elegido,
  y lo indican en el título de cada sección. No representan cobros bancarios por
  fecha de depósito. Los anticipos confirmados `CREDIT` y `FEE` permanecen separados.
- Eventos: ingreso confirmado exclusivamente desde `EventPurchasePayment`.
  Cortesías aportan cero. Entradas vendidas individuales, cortesías y accesos de
  mesa son categorías separadas; usadas significa `used_at` registrado. Los
  conteos conservan entradas emitidas aunque después se anulen. “Por verificar”
  suma comprobantes `PENDING`; una intención de compra sin comprobante no es ingreso.

Los agregados se calculan en PostgreSQL. Cada conjunto admite como máximo 5,000
filas, con 25 filas por página; el exceso solicita reducir el periodo sin presentar
un total parcial como completo. El resumen muestra los 20 productos principales
por bruto. Las lecturas del reporte usan una instantánea transaccional consistente.

### PDF

Todos los reportes exportan con **ReportLab**, sin agregar bibliotecas de producción.
El PDF incluye identidad, periodo, fecha/hora de Guatemala, usuario, totales,
tablas con encabezados repetidos y numeración. Usa papel blanco, texto oscuro y
acento discreto; los motivos extensos pueden continuar entre páginas.
La respuesta es directa, autenticada, `no-store`, con nombre sanitizado, sin un
modelo `ReportFile`, almacenamiento público ni enlaces permanentes. Máximo 1,000
filas por PDF; cuando se excede, se solicita reducir el periodo. Se omiten tablas
sin filas. El ejemplo en `output/pdf/` contiene únicamente datos ficticios de QA.

### Auditoría

Se reutiliza `AuditLog` en un listado paginado y detalle de **solo lectura**.
Filtros: fechas locales, nombre/usuario, módulo, acción y referencia de entidad.
La búsqueda no consulta el JSON privado. Los módulos incluyen Operación, Caja,
Inventario, Pagos, Reservas, Eventos, Impresión, Usuarios y Configuración.
Acciones desconocidas reciben una descripción genérica segura; registros sin
usuario muestran “Sistema”. El visor agrega contexto de producto/mesa mediante
consultas por lotes y no inventa información histórica ausente.

La presentación usa una **lista explícita de campos y tipos permitidos**. No
serializa el JSON, ni recorre objetos anidados arbitrarios. Cambios admitidos de
identidad/configuración se proyectan campo por campo; importes e identificadores
se validan numéricamente. Texto con patrones de credenciales/tokens se reserva.
Contraseñas, PIN, hashes, claves de sesión y tokens completos nunca se extraen de
sus campos. El Admin técnico mantiene su protección contra edición y borrado.

### Configuración

Se añadieron únicamente `BusinessSettings`, `PaymentMethodSettings` y
`BankTransferSettings`. Las migraciones inicializan los cuatro códigos de pago
sin conceder permisos a usuarios existentes.

- **Negocio:** nombre editable; por ahora zona `America/Guatemala`, moneda `GTQ`
  y símbolo `Q` permanecen fijos para preservar consistencia histórica. El nombre
  se usa en los nuevos PDF. No se refactorizaron los recibos previos ni se agregó FEL.
- **Métodos de pago:** cuatro códigos inmutables, habilitación y orden editables.
  Al volver a abrir la cuenta/cobro, los botones reflejan la configuración. Un
  navegador ya abierto también encuentra la validación del servicio al intentar
  pagar. La desactivación y la creación de pagos comparten la barrera transaccional
  existente. Confirmar/rechazar pendientes y reembolsar pagos previos sigue permitido.
  Esta disponibilidad corresponde a los cobros operativos `Payment`; los portales
  de reservas y eventos mantienen sus flujos propios de transferencia.
- **Transferencias web:** banco, titular, número de cuenta e instrucciones públicas;
  no se almacenan credenciales bancarias. Reservas y eventos muestran estos datos
  cuando requieren transferencia. Sin configuración completa/habilitada aparece
  un error administrativo explícito y se pide contactar al negocio antes de pagar.
  Se eligió esta alternativa para conservar solicitudes y comprobantes históricos.
- **Reservas/Eventos:** enlaces y resumen de sus configuraciones existentes.
  **Impresoras:** enlace a `/impresoras/`, conteo de equipos y de impresoras con
  fallos en los últimos siete días. Los trabajos sin impresora no cuentan como
  dispositivos fallidos. Su editor técnico conserva inicio de sesión técnico,
  `is_staff` y permisos existentes.
- **Mesas/Dispositivos:** resumen y acceso técnico cuando el usuario tiene acceso
  al Admin correspondiente; no se creó otro editor de mesas ni administración MDM.
- **Seguridad/Sistema:** tiempos de sesión, intentos y bloqueo de PIN, zona horaria,
  modo de desarrollo y backend de impresión en solo lectura. `PUBLIC_BASE_URL`
  sigue en el entorno. No se muestran secretos ni parámetros de conexión de BD.

Todo cambio realizado desde las nuevas pantallas requiere POST, CSRF, sesión de
Gerencia vigente y permiso específico, y genera `AuditLog`. Las lecturas no crean
configuración de negocio/banco automáticamente. No se ofrece borrar métodos.

Permisos nuevos (sin asignación automática):
`core.view_reports`, `core.export_reports_pdf`, `audit.view_audit_log`,
`core.view_configuration`, `core.change_business_configuration`,
`core.change_payment_method_configuration` y `core.change_bank_transfer_configuration`.
Están disponibles en la matriz de permisos de Gerencia existente.

Se corrigieron también “Visible en punto de venta” y el mensaje de contraseña
“No requerida para este rol” en usuarios operativos sin contraseña.

### Validación 3E

Ver `docs/phase-3e/VERIFICACION.md`, las diez capturas A–J y el PDF de demostración.
La verificación usa una base local temporal, datos ficticios y limpieza posterior.
No se inicia website, Local Node, sincronización, failover ni módulos fiscales.

## Fase 4A — Website público premium

La portada y los flujos públicos usan Django Templates, Inter local y JavaScript
ligero. La identidad combina negro, carbón y champagne. No se agregó una SPA,
un segundo motor de reservas/pagos ni modelos nuevos.

### Rutas públicas

| Ruta | Uso |
| --- | --- |
| `/` | Portada, siguiente evento publicado y tres experiencias |
| `/eventos/` | Calendario paginado de eventos publicados o reprogramados vigentes |
| `/eventos/<slug>/` | Detalle, selección de entradas mixtas o mesa de evento |
| `/reservas/` | Fecha, hora y número de personas |
| `/reservas/mesas/` | Mapa público filtrado por área |
| `/reservas/datos/` | Nombre, teléfono y resumen de mesa; selección firmada |
| `/reservas/r/<token>/` | Portal privado de reserva normal |
| `/eventos/compra/<token>/` | Portal privado de compra y sus PDF |
| `/entrada/<token>/` | Entrada individual; no concede acceso al portal de compra |
| `/sitemap.xml`, `/robots.txt` | Descubrimiento público y exclusiones de indexación |

### Reservas normales

Fecha/hora/personas → mapa → nombre/teléfono → solicitud recibida. El mapa usa
`get_available_tables()` como fuente de disponibilidad y muestra únicamente mesas
reservables en web de áreas activas. Los estados visibles son disponible/no
disponible; no se publican clientes, pedidos ni razones operativas. Si una
configuración aún no tiene posiciones distintas, se muestra una cuadrícula por
área. Los planos configurados conservan posiciones y formas con desplazamiento
local en pantallas pequeñas. La selección conserva nombre, área y capacidad.

Una selección firmada vale 30 minutos, pero **no retiene** una mesa. Solo el POST
válido llama a `create_public_reservation_request()`, que vuelve a validar y
bloquea la disponibilidad de forma transaccional. Una selección antigua, mesa
retirada o conflicto de disponibilidad produce una recuperación clara. Los
servicios mantienen la duración y el plazo de retención configurados.

El resumen explica el anticipo previsto antes de solicitar. Un importe fijo
muestra el monto y su aplicación. Si la política es porcentual, se comunica que
Gerencia debe fijar el consumo estimado y el monto antes de pagar. La solicitud
pública no inventa esa base ni confirma automáticamente: los términos definitivos
se muestran después de la aprobación en el portal existente.

El portal distingue solicitud, aprobación pendiente de pago, comprobante en
revisión, confirmación, llegada, rechazo/cancelación y expiración. Las reservas
normales no generan QR. La confirmación de llegada conserva el flujo de Gerencia.

### Eventos, compras y entradas

El detalle muestra tipos activos de venta dentro de su ventana, incluidos tipos
agotados, y mesas habilitadas disponibles. Los botones +/− respetan máximos; el
servidor valida nuevamente tipos, ventanas, cantidad, mesa y aforo. Se pueden
combinar tipos de entrada o comprar una mesa completa. El total se actualiza en
centavos, y solo se solicitan nombre y teléfono.

Una mesa muestra capacidad, precio por persona y total. Ejemplo verificado:
VIP 2, seis personas × Q100 = Q600; después de confirmar el pago se generan seis
entradas individuales. `create_purchase()`, los holds, la revisión de transferencia,
la emisión de tickets y los PDF son los servicios existentes. No se cambió el
control de acceso ni el motor de documentos.

Los portales muestran el plazo real del servidor. El contador calcula tiempo
transcurrido con reloj monotónico del navegador; al llegar a cero recarga el estado
real. Al volver a una pestaña después de 15 segundos se actualiza si no hay un
formulario editado. También existe «Actualizar estado». No hay polling continuo.
Los comprobantes aceptan JPEG/PNG/WebP hasta 5 MB con validación del backend.

### Banco y privacidad

Ambos portales usan la configuración bancaria central de Gerencia. Banco,
titular, cuenta e instrucciones proceden de `BankTransferSettings`; no hay datos
bancarios reales inventados. Si falta configuración, se explica que Gerencia debe
completarla antes de pagar. Los comprobantes mantienen su almacenamiento privado
y su acceso restringido.

Los tokens existentes y sus rutas conservan compatibilidad. Portales, QR y PDF
mantienen no-store/noindex y separación entre compradores. La selección y el mapa
también son noindex y no-cache. Formularios POST conservan CSRF. No se exponen
estadísticas internas de aforo, identidades ajenas ni enlaces administrativos.

### SEO, imágenes y comportamiento móvil

`PUBLIC_BASE_URL` es la base absoluta de canonical, Open Graph y sitemap, además
de los enlaces seguros existentes. El valor local por defecto es
`http://localhost:8000`; se configura mediante el entorno, sin dominio de producción
fijo. El sitemap solo incluye portada, calendario, inicio de reservas y eventos
públicos vigentes. `robots.txt` excluye Gerencia, operación, caja, acceso, QR y
portales privados. No se publicó schema Event porque aún no hay ubicación real
configurada que permita completarlo correctamente.

La imagen conceptual provisional pesa aproximadamente 110 KiB en WebP. Inter se
sirve desde `static/fonts/` con su licencia OFL; no hay solicitudes a Google Fonts.
Hero y fuente se precargan, las imágenes secundarias usan carga diferida y el
calendario está paginado. La imagen de cada evento sigue siendo la administrada
en Gerencia. No se inventaron redes sociales, teléfono ni dirección del negocio.

Imágenes editoriales reemplazables sin migraciones: `PUBLIC_HERO_IMAGE`,
`PUBLIC_SPORT_BAR_IMAGE`, `PUBLIC_DISCOTECA_IMAGE` y `PUBLIC_PREMIUM_IMAGE` reciben
rutas relativas a static. `PUBLIC_LEVEL_IMAGES` reúne las tres últimas en settings.
Hasta disponer de fotografía real, las áreas reutilizan encuadres del mismo recurso
conceptual. Prompt y procedencia en `docs/phase-4a/IMAGEN.md`.

Móvil: menú compacto con Escape y foco, formularios de una columna, controles de
44 px, total fijo durante selección y QR grandes. Verificados 390×844, 430×932,
tablet y escritorio. Sin JavaScript, formularios y cantidades nativas siguen
utilizando el backend y las áreas quedan visibles.

También se ajustó 3E: referencia humana de producto en auditoría, conteos separados
de impresoras registradas/configuradas/con fallos, y aclaración de que los pagos
por verificar ya están incluidos en el saldo pendiente. Los cálculos no cambiaron.

Evidencia y capturas: `docs/phase-4a/VERIFICACION.md`. No se inició Local Node,
despliegue, sincronización offline, PWA, analytics ni FEL.
