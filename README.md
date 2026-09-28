# BIG PARTY — Fases 0, 1A, 1B, 1C, 1D, 1E, 2A y 2B

Fundación técnica de un sistema empresarial para bar, discoteca y restaurante en Guatemala.
La Fase 0 contiene configuración, usuarios, roles, permisos nativos de Django,
soporte seguro de PIN, auditoría y una página de comprobación. La Fase 1A añade la
configuración física de áreas, zonas y mesas. La Fase 1B añade catálogo e inventario global.
La Fase 1C incorpora cuentas de mesa, subcuentas, consumo enviado y comandas lógicas.
La Fase 1D añade pagos, descuentos, reembolsos y cierre de cuentas.
La Fase 1E incorpora caja física, entregas de efectivo, conteo ciego y jornadas.
La Fase 2A inicia la interfaz operativa del mesero: dispositivo, PIN, mapa y apertura de mesas.
La Fase 2B añade catálogo y pedidos visuales, modificadores, adiciones y selección de subcuentas.
Ver cuenta y cobro visual quedan para las siguientes fases; no incluye impresión física.

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

Las 431 pruebas Django cubren carga de la página y del administrador, formularios de usuarios,
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

## Git y alcance

`.env`, `.venv`, cachés, archivos temporales, medios locales y estáticos recopilados
se excluyen de Git. `.env.example`, las dependencias y las migraciones sí se versionan.
No subir credenciales ni archivos de entorno reales.

La entrega finaliza en la Fase 2B: catálogo y pedidos visuales. Ver cuenta, cobro y división
de pago visuales, mover productos/mesas, unir mesas, caja visual, impresoras reales,
reservas, eventos, QR, dashboard ejecutivo, PDF finales, nodo local, hardware, websockets
y sincronización offline permanecen fuera de alcance. Esperar revisión antes de Fase 2C.
