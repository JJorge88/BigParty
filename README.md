# BIG PARTY — Fase 0

Fundación técnica de un sistema empresarial para bar, discoteca y restaurante en Guatemala.
Esta fase contiene únicamente configuración, usuarios, roles, permisos nativos de Django,
soporte seguro de PIN, auditoría y una página de comprobación. No incluye funciones comerciales.

## Requisitos

- macOS con Python 3.13 (no utilizar el Python 3.9 del sistema).
- PostgreSQL 17 en ejecución, con `psql`, `createuser` y `createdb` disponibles.
- Git.

Entorno verificado: macOS 27.0 ARM64, Python 3.13.14, PostgreSQL/psql 17.10,
Git 2.54.0. Dependencias: Django 5.2.17 LTS, psycopg con binarios 3.3.6 y
python-dotenv 1.2.3. Solo se añaden sus dependencias transitivas.
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
│   └── core/         # Página mínima de comprobación
├── templates/
│   ├── base.html
│   └── core/home.html
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

## Pruebas y comprobaciones

Con PostgreSQL disponible y `.venv` activado:

```sh
python manage.py check --database default
python manage.py makemigrations --check --dry-run
python manage.py test
python -m pip check
```

Las 22 pruebas cubren carga de la página y del administrador, formularios de usuarios,
roles, permisos individuales, PIN con hash y sal, confirmación y conservación del PIN,
creación de auditoría y protección frente a cambios y borrado, CSRF y archivos estáticos.
Se ejecutan sobre una base PostgreSQL temporal separada; Django la elimina al finalizar.

## Git y alcance

`.env`, `.venv`, cachés, archivos temporales, medios locales y estáticos recopilados
se excluyen de Git. `.env.example`, las dependencias y las migraciones sí se versionan.
No subir credenciales ni archivos de entorno reales.

La Fase 0 finaliza aquí. Mesas, catálogo, pedidos, inventario, pagos, caja, reservas,
eventos, APIs, sincronización y despliegue requieren autorización para fases posteriores.
