# Instalar BIG PARTY Local Node en Windows

Guía preparada en Fase 4B; **no ejecutar aún en el establecimiento**. Scripts revisados desde Mac, pendientes de prueba física Windows/CA/impresoras en 4F. No se incluye sincronización automática. Trabajar con un responsable técnico en los pasos de base, firewall y certificados.

## 1. Preparar Windows

Actualizar Windows y reiniciar. Crear una cuenta Windows dedicada al nodo, con acceso solo a la aplicación y sus carpetas de datos; usarla también para las tareas programadas. Desactivar suspensión del servidor durante operación. Mantener LAN/router/switch y energía estables. No guardar contraseñas en scripts.

## 2. Reservar dirección y nombre LAN

Configurar reserva DHCP/IP fija con el administrador de red. Elegir un nombre interno, por ejemplo `pos.bigparty.lan`; registrar ese nombre en DNS del router para que TODOS los clientes lo resuelvan sin DNS público. Un archivo hosts solo aplica al equipo donde se instala y suele ser inadecuado para teléfonos. No depender de mDNS `.local` sin probar compatibilidad. Usar siempre el mismo nombre en enlaces, cookies y certificado.

## 3. Instalar PostgreSQL 17

Instalar PostgreSQL 17 para Windows desde su distribución oficial; habilitar su servicio de arranque automático. Conservar credenciales administrativas fuera del repo. Configurar `listen_addresses='localhost'`. En `pg_hba.conf`, conexiones loopback de aplicación con `scram-sha-256`; **nunca `trust`** en instalación real. Reiniciar el servicio tras cambiar configuración. No abrir 5432 a tablets/PCs.

## 4. Instalar Python

Instalar Python 3.13 de 64 bits con Python Launcher (`py`). Confirmar `py -3.13 --version` en PowerShell. El entorno de producción utiliza Waitress, no `runserver`.

## 5. Obtener el proyecto

Copiar/descargar una versión revisada del repositorio, por ejemplo `C:\Big Party`. Evitar carpetas temporales, OneDrive o unidades de red para base y datos. No copiar `.env`, sesiones, dumps ni secretos de desarrollo. La instalación inicial de dependencias necesita Internet o paquetes aprobados previamente descargados; la operación posterior no.

## 6. Crear el entorno virtual

Abrir PowerShell en el proyecto (las comillas son necesarias con espacios):

```powershell
Set-Location -LiteralPath 'C:\Big Party'
py -3.13 -m venv '.venv'
```

El instalador también crea `.venv` si no existe. No hace falta activar el entorno; scripts usan su ejecutable completo.

## 7. Instalar dependencias

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r '.\requirements\prod.txt'
```

Incluye Waitress 3.0.2 y WhiteNoise 6.12.0. Caddy se instala aparte; no es paquete Python. El script de instalación puede repetir este paso sin borrar datos.

## 8. Crear base y usuario

Con SQL Shell/psql como administrador PostgreSQL, crear el usuario dedicado y asignarle contraseña interactivamente (no ponerla en archivos ni historial SQL):

```sql
CREATE ROLE bigparty_app LOGIN;
\password bigparty_app
CREATE DATABASE bigparty OWNER bigparty_app;
```

Usar contraseña aleatoria fuerte. La aplicación no debe usar el superusuario `postgres`. El usuario propietario necesita permisos de migración sobre SU base; no privilegios de superusuario/creación de otras bases. PostgreSQL verifica la contraseña por SCRAM.

## 9. Configurar entorno y datos persistentes

Copiar `.env.local-node.example` a `.env.local-node` y editarlo localmente. Completar secretos aleatorios independientes: `DJANGO_SECRET_KEY` y `ACCESS_SNAPSHOT_SIGNING_KEY` (esta última compartida con el exportador fuente). No reutilizar contraseñas. Completar `DB_PASSWORD`, hostname, hosts explícitos y orígenes HTTPS. `PUBLIC_BASE_URL` debe coincidir con la URL pública real que contienen los QR.

Crear `C:\BigPartyData\media`, `C:\BigPartyData\private` y `C:\BigPartyData\log`. Limitar permisos Windows a la cuenta del nodo/administradores; Caddy solo necesita lectura de media. Usar rutas absolutas en variables `LOCAL_MEDIA_ROOT`, `LOCAL_PRIVATE_ROOT`, `LOCAL_LOG_ROOT`. La carpeta privada debe quedar fuera de media. DB/media/privados/identidad son persistentes, no caché desechable. Backups completos serán 4D; no se crea ninguna tarea de copia ahora.

`APP_VERSION` y `APP_COMMIT` identifican la versión instalada, sin secretos. `PRINTER_BACKEND=network`; `LOCAL_NODE_HTTPS=True`; Waitress bind `127.0.0.1`, puerto configurable `8000`. El ejemplo Caddy usa IPv4 loopback: si se elige `::1`, adaptar también su upstream. Variables del proceso prevalecen sobre el archivo: evitar variables globales heredadas de otros entornos.

## 10. Aplicar migraciones

El instalador agrupa pasos 7 y 10–13 y luego diagnóstico:

```powershell
powershell.exe -NoProfile -File '.\deploy\windows\install-local-node.ps1'
```

Si falta `.env.local-node`, lo copia y sale con código 1 para que se complete. Reejecutar después. Para operaciones manuales en esta consola:

```powershell
$env:BIGPARTY_ENV_FILE = (Join-Path (Get-Location).Path '.env.local-node')
$env:DJANGO_SETTINGS_MODULE = 'config.settings.local_node'
$env:DEPLOYMENT_MODE = 'local_node'
& '.\.venv\Scripts\python.exe' manage.py migrate --noinput
```

No aplicar migraciones si se seleccionó una base incorrecta. Los scripts no borran bases ni datos. Si la política Windows impide ejecutar scripts, revisar su procedencia y desbloquear los archivos verificados según la política de la organización; no desactivar globalmente la seguridad.

## 11. Recolectar assets

```powershell
& '.\.venv\Scripts\python.exe' manage.py collectstatic --noinput
```

Repetir al actualizar assets; reiniciar Waitress después. WhiteNoise sirve CSS, JS, QR worker, fuentes e imágenes estáticas desde `staticfiles`. No usa CDN ni `runserver`. No borrar la colección mientras el nodo atiende usuarios.

## 12. Preparar defaults y usuarios

```powershell
& '.\.venv\Scripts\python.exe' manage.py prepare_local_node
```

Idempotente: áreas, catálogo base, cajas, impresoras e identidad. No crea usuarios automáticamente ni copia catálogo del cloud. Crear explícitamente el primer usuario técnico autorizado con `manage.py createsuperuser`; luego configurar GERENTE/PROPIETARIO, meseros, cajeros y guardias con sus permisos y PIN mediante las pantallas existentes. El superusuario técnico no reemplaza los roles operativos. Verificar catálogo, precios, stock y mesas reales antes de operar.

## 13. Inicializar identidad

`prepare_local_node` ya ejecuta `init_local_node`; puede repetirse:

```powershell
& '.\.venv\Scripts\python.exe' manage.py init_local_node
```

Conserva UUID y nombre existentes. El UUID no cambia por reinicio/actualización/restore íntegro. No crear dos servidores activos desde la misma copia de base.

## 14. Iniciar Waitress

```powershell
powershell.exe -NoProfile -File '.\deploy\windows\start-local-node.ps1'
```

Espera PostgreSQL con reintentos limitados a una ventana de 60 segundos y timeout corto por conexión; si falla sale 1. Comprueba identidad, configuración y static. Escucha solo loopback; Caddy es la entrada LAN. La ventana permanece ocupada mientras funciona. No ejecutar dos instancias. Logs rotan a 5 MiB y cinco copias por canal: `application.log`, `printing.log`; errores se expresan mediante códigos seguros, sin PIN/credenciales/URLs/tokens.

## 15. Preparar Caddy y HTTPS

Descargar/verificar Caddy oficial para Windows manualmente (ningún script instala binarios). Copiar `deploy/windows/Caddyfile.example` a un archivo local `Caddyfile`. Configurar para la cuenta que ejecuta Caddy las variables `LOCAL_NODE_HOSTNAME`, `LOCAL_NODE_PORT`, `LOCAL_MEDIA_ROOT`; **Caddy no lee `.env.local-node` automáticamente**.

```powershell
$env:LOCAL_NODE_HOSTNAME = 'pos.bigparty.lan'
$env:LOCAL_NODE_PORT = '8000'
$env:LOCAL_MEDIA_ROOT = 'C:/BigPartyData/media'
& 'C:\Caddy\caddy.exe' validate --config 'C:\Big Party\deploy\windows\Caddyfile' --adapter caddyfile
& 'C:\Caddy\caddy.exe' run --config 'C:\Big Party\deploy\windows\Caddyfile' --adapter caddyfile
```

`tls internal` crea una CA privada local. Instalar y confiar **solo su certificado raíz público** en cada PC/tablet/teléfono mediante procedimiento autorizado; nunca distribuir la clave privada de la CA. Mantener el almacenamiento de Caddy persistente, protegido y asociado a la misma cuenta, para no regenerar la CA al reiniciar. No incluir CA, certificados ni claves en Git. No se automatiza confianza de móviles en esta fase.

La cámara QR móvil requiere HTTPS con certificado confiable; `http://IP-LAN` no es una alternativa fiable. El fallback `LOCAL_NODE_HTTPS=False` existe exclusivamente para simulación/desarrollo y desactiva cookies Secure. No usarlo en instalación real. Caddy sirve únicamente imágenes de `LOCAL_MEDIA_ROOT`; nunca apuntar `file_server` a la raíz del proyecto, datos o comprobantes privados. No habilitar access logging de URLs.

## 16. Configurar firewall

Con administrador Windows, permitir TCP 443 entrante únicamente desde la subred LAN autorizada/perfil privado. No exponer puerto 8000 ni 5432, ni hacer port-forwarding WAN en el router. El ejemplo desactiva redirección HTTP automática; los clientes usan explícitamente `https://hostname`. Verificar desde otra PC que 443 funciona y PostgreSQL/Waitress no son accesibles directamente. Las impresoras requieren conectividad TCP desde el nodo a sus IP/puertos LAN.

## 17. Arranque automático con Task Scheduler

Crear tarea «BIG PARTY Local Node»:

- Cuenta dedicada con permisos sobre proyecto/datos; «ejecutar tanto si el usuario inició sesión como si no». Configurar credencial por la interfaz Windows, sin guardarla en script.
- Trigger «Al iniciar», retraso de 30 segundos.
- Acción programa `powershell.exe`; argumentos `-NoProfile -File "C:\Big Party\deploy\windows\start-local-node.ps1"`; «Iniciar en» `C:\Big Party` (campo separado, sin comillas).
- Si falla, reiniciar cada minuto, máximo 3 intentos; permitir ejecución manual; si ya se ejecuta, **no iniciar otra instancia**.
- Desactivar «detener si dura más de»; ajustar condiciones de energía/suspensión para servidor.

PostgreSQL debe ser servicio automático. Crear otra tarea equivalente para Caddy con `caddy.exe run --config "C:\Big Party\deploy\windows\Caddyfile" --adapter caddyfile`, misma cuenta/entorno persistente, sin instancias duplicadas. No usar `caddy start` en tarea supervisada. Probar reinicio Windows y arranque sin sesión interactiva durante 4F. No se necesitan NSSM/WinSW.

## 18. Diagnóstico y salud

```powershell
powershell.exe -NoProfile -File '.\deploy\windows\check-local-node.ps1'
Invoke-RestMethod 'http://127.0.0.1:8000/healthz/'
Invoke-RestMethod 'http://127.0.0.1:8000/readyz/'
```

Health responde `status: ok`; readiness responde 503 si PostgreSQL falla. Ambas permiten comprobación local HTTP y no exponen configuración. Desde la LAN usar HTTPS con nombre/certificado. `check_local_node` devuelve 1 si falta un requisito; ausencia de snapshots/impresoras configuradas genera avisos y debe resolverse antes de abrir al público. Impresora apagada no significa nodo caído. Página autorizada: `/gerencia/configuracion/nodo-local/`.

## 19. Configurar impresoras y accesos QR

En Gerencia/Impresoras asignar IP fija LAN, puerto, papel/encoding y rutas Barra/Cocina. Defaults no conocen IP reales. Hacer impresión de prueba y verificar contenido físico, cortes y caracteres. No reimprimir a ciegas un envío incierto. El backend de red usa TCP LAN; debug es solo simulación explícita.

Exportar snapshot desde la base fuente y trasladarlo por medio autorizado; importar en nodo:

```powershell
& '.\.venv\Scripts\python.exe' manage.py import_event_access_snapshot 'C:\Transferencias\evento-firmado.json'
```

Clave/fuente deben coincidir. Ver eventos, fecha y cantidad en Gerencia. Probar primer scan VÁLIDA y segundo YA UTILIZADA con entradas de prueba. No consumir entradas reales como prueba. Importar nueva versión no reabre USED, y CANCELLED prevalece. Ventas/cancelaciones posteriores al archivo no llegan solas; acceso debe operar en un único nodo hasta tener sync. Ver [arquitectura y formato](../architecture/LOCAL-NODE.md).

## 20. Preparar tablets/PCs y validar caída de Internet

Abrir `https://hostname/operacion/`, configurar OperationalDevice con sesión técnica de `/admin/` y luego mesero/PIN. Gerencia tiene sesión independiente; iniciar sesión en Gerencia no autoriza automáticamente el configurador técnico. En cada PC de caja abrir `/caja/`, asociar caja y acceder como cajero. Gerencia usa `/gerencia/`; guardias `/acceso/`. Las cookies se ligan al hostname y rutas; cambiar de nombre requiere nueva configuración/login.

Con datos de prueba: abrir jornada/caja/mesa, agregar y enviar pedido, comprobar stock/comanda, registrar efectivo y tarjeta manual, recibir handoff, retirar con autorización y cerrar cuenta/caja. Registrar transferencia/depósito PENDING sin autoconfirmar. Desconectar solo Internet, **mantener LAN**, repetir accesos y recursos locales; validar QR importado. `/reservas/` y compras públicas deben seguir deshabilitadas por LAN. Reconectar sin esperar sincronización: todavía no existe. No iniciar operación real hasta aprobar la validación física 4F.

Referencias técnicas: [Waitress detrás de proxy](https://docs.pylonsproject.org/projects/waitress/en/latest/reverse-proxy.html), [WhiteNoise/Django](https://whitenoise.readthedocs.io/en/stable/django.html), [Caddy TLS interno](https://caddyserver.com/docs/caddyfile/directives/tls). Windows, confianza de CA y hardware quedan pendientes de ejecución física; esta guía no declara un despliegue realizado.
