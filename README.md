# BIG PARTY — Fases 0, 1A y 1B

Fundación técnica de un sistema empresarial para bar, discoteca y restaurante en Guatemala.
La Fase 0 contiene configuración, usuarios, roles, permisos nativos de Django,
soporte seguro de PIN, auditoría y una página de comprobación. La Fase 1A añade la
configuración física de áreas, zonas y mesas. La Fase 1B añade catálogo e inventario global.
No incluye pedidos, ventas, pagos ni caja.

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
│   └── inventory/    # Movimientos y servicios de inventario global
├── templates/
│   ├── base.html
│   ├── core/home.html
│   ├── tables/configuration.html
│   ├── catalog/development.html
│   └── inventory/development.html
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
de una orden futura determinará la barra; no hay comandas en esta entrega.

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
inventario y no tienen ingredientes asociados. La selección concreta por un cliente y
el cálculo del precio de esa selección se integrarán cuando exista el módulo de órdenes.

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
Estas consultas no reservan ni descuentan stock: la venta y el consumo conjunto de
componentes deberán implementarse de forma transaccional en la fase correspondiente.

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
añaden manualmente ni borran desde el administrador. No existen movimientos de ventas
ni reembolsos. Escribir stock o precios directamente por ORM/SQL omite el historial y
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

## Pruebas y comprobaciones

Con PostgreSQL disponible y `.venv` activado:

```sh
python manage.py check --database default
python manage.py makemigrations --check --dry-run
python manage.py test
python -m pip check
```

Las 133 pruebas cubren carga de la página y del administrador, formularios de usuarios,
roles, permisos individuales, PIN con hash y sal, confirmación y conservación del PIN,
creación de auditoría y protección frente a cambios y borrado, CSRF y archivos estáticos.
También cubren áreas, zonas, mesas, validaciones Python y constraints PostgreSQL,
coherencia entre zona y área, semilla idempotente, mapa ordenado, auditoría transaccional,
administración y acceso restringido a la vista de desarrollo.
La Fase 1B añade pruebas de categorías, precios e historial, modificadores, combos,
disponibilidad, entradas y ajustes, permisos, CSRF, imágenes inválidas, reversión ante
fallos y concurrencia real. Las 67 pruebas de las fases anteriores siguen incluidas.
Se ejecutan sobre una base PostgreSQL temporal separada; Django la elimina al finalizar.

## Git y alcance

`.env`, `.venv`, cachés, archivos temporales, medios locales y estáticos recopilados
se excluyen de Git. `.env.example`, las dependencias y las migraciones sí se versionan.
No subir credenciales ni archivos de entorno reales.

La entrega finaliza en la Fase 1B: catálogo e inventario. Pedidos, ventas, pagos, caja,
reservas reales, eventos, mapa visual, APIs, sincronización y despliegue requieren
autorización para fases posteriores.
