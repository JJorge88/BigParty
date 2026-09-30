# Hardening — BIG PARTY Fase 4D

Configuración preparada; las cuentas reales, ACL, firewall, certificados, tareas y copias externas se validan en 4E. No se modificó infraestructura real. Referencia base: [checklist oficial Django 5.2](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

## Identidades de sistema operativo y PostgreSQL

Windows: cuenta dedicada de servicio sin Administrators, inicio de sesión de servicio/tarea solo según necesidad; RDP restringido a administradores autorizados. Ubuntu: usuario `bigparty` sin sudo, código/dependencias no escribibles por el proceso web; solo carpetas persistentes/logs/estado necesarias escribibles. Parches del SO/PG y antivirus/EDR según política. Cifrar discos y custodiar recovery keys separadas. Scripts systemd con umask 0077, NoNewPrivileges y PrivateTmp; revisar mounts/UID antes de activar.

PostgreSQL: escuchar loopback si aplicación y DB comparten host; no abrir 5432 a Internet/LAN innecesariamente. Autenticación SCRAM, sin `trust`; conexiones remotas solo por red privada/TLS y reglas `pg_hba.conf` concretas. No hay passwords predeterminados ni incluidos en repositorio.

Separar roles:

- Aplicación: LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE; CONNECT a DB, USAGE en schema, SELECT/INSERT/UPDATE/DELETE en tablas necesarias y USAGE/SELECT/UPDATE en secuencias. Sin membresía en roles administrativos ni permiso de cambiar a ellos.
- Migración: rol owner del schema/objetos, utilizado solo en deploy controlado. Configurar `ALTER DEFAULT PRIVILEGES FOR ROLE <migration_owner>` para futuros objetos y conceder al rol app; revisar funciones/extensiones que realmente se utilicen.
- Backup: CONNECT/USAGE/SELECT a tablas y acceso requerido a secuencias, sin SUPERUSER/CREATEDB; considerar pg_read_all_data solo si el alcance multi-DB es aceptable. Probar dump completo con ese rol. Seleccionarlo con un archivo de entorno privado específico, nunca cambiar credenciales del proceso web en caliente.
- Recuperación: rol temporal con CREATEDB y permisos de restauración. El dump no restaura owners/ACL: el rol restaurador posee los objetos nuevos. Tras restaurar, el DBA reasigna propiedad al rol de migración y grants al rol app, valida, retira credenciales de restore y ejecuta aplicación con el rol normal.
- Desarrollo/tests: CREATEDB requerido por tests y drills. **No copiar el usuario local actual a producción.**

`python manage.py check_production_database` revisa flags administrativos del rol activo, membresías peligrosas y tamaño DB; falla si encuentra privilegios incompatibles con aplicación. Es lectura; nunca ejecuta ALTER ROLE. Correr con credenciales **app**, no backup/restore/tests. No sustituye revisión completa de ACL, schema, RLS o extensiones. No modificar automáticamente privilegios reales desde una prueba de desarrollo.

Autovacuum permanece habilitado. Monitorear tamaño DB, espacio, crecimiento de logs y duración del dump; revisar estadísticas/índices con DBA si hay degradación. No ejecutar VACUUM FULL ni purga histórica automática desde mantenimiento.

## Secretos y rotación

Producción y local_node exigen DJANGO_SECRET_KEY aleatoria (mínimo 50 caracteres), SYNC_SHARED_SECRET y ACCESS_SNAPSHOT_SIGNING_KEY (mínimo 32 bytes e independientes); no pueden quedar vacías incluso con sync apagado. Generarlas con gestor seguro; archivos de entorno fuera de público, ACL mínima, nunca Git, historial de terminal, argumentos o capturas. `OPERATIONS_STATE_ROOT` también es obligatorio, absoluto, persistente y separado del proyecto/media/static.

Para rotar **sync** planificadamente:

1. Generar nueva clave; mantener anterior solo durante ventana coordinada de máximo 24h.
2. Cloud: nueva en `SYNC_SHARED_SECRET`, vieja en `SYNC_SHARED_SECRET_PREVIOUS`, fecha ISO8601 con zona en `SYNC_SECRET_PREVIOUS_UNTIL` (futuro ≤24h). Reiniciar/revisar arranque.
3. El servidor acepta ambas durante esa ventana; firma la respuesta con la clave que autenticó la petición, para que el nodo aún antiguo la valide. El cliente siempre firma con su clave actual.
4. Actualizar Local a nueva; probar handshake/push/pull/ack y revisar cola/conflictos. Remover previous/deadline de ambos y reiniciar antes del vencimiento.
5. En proceso en ejecución, la clave vieja deja de aceptarse al vencer; una configuración previous vencida rechaza un nuevo arranque. No dejar secretos antiguos configurados indefinidamente. Si se comprometió una clave, no dar ventana de gracia: revocar y coordinar interrupción.

**Snapshot QR:** no hay keyring nuevo. Mantener distribución/exportación del lado que firma mientras se coordina sustitución en Cloud y Local, regenerar e importar snapshots vigentes con la nueva clave, probar QR offline y después retirar la antigua. Los blobs antiguos firmados con la anterior no serán verificables por la nueva; conservar copia protegida y procedimiento de soporte. No cambiarla sin inventario de snapshots en uso ni cortar acceso a mitad de un evento.

**Django SECRET_KEY:** cambio coordinado del entorno/reinicio; puede invalidar sesiones, tokens firmados, enlaces/confirmaciones y otros datos basados en firma. Planificar cierre de sesiones y reautenticación, revisar tokens públicos vigentes y emitir reemplazos por sus flujos autorizados. No regenerar ventas ni cobros. No hay botón web ni fallback ilimitado de claves.

Backups contienen información de negocio y hashes/credenciales de cuentas: proteger como producción. Recuperar secretos del gestor seguro por separado. `check_repo_safety` revisa archivos versionados por nombres privados, patrones comunes y claves configuradas presentes literalmente; solo reporta ubicación/código. No escanea todo el historial ni sustituye una auditoría o detección universal. Ejecutar después de añadir archivos al índice y antes de commit. No incluir dumps, `.env` reales, certificados privados o copias de DB.

## Django, HTTPS y proxy

DEBUG=False, hosts/orígenes CSRF explícitos. Se mantienen los cuatro validadores Django de contraseña. Cookies de sesión HttpOnly y Secure sobre HTTPS; CSRF Secure; SameSite=Lax y dominio no compartido. Dev puede usar HTTP; simulación local HTTP debe ser explícita y nunca considerarse producción.

Cloud redirige a HTTPS; HSTS inicial 3600 s, sin includeSubDomains ni preload hasta conocer todos los subdominios/certificados. Excepciones documentadas a `check --deploy`: **W005 y W021** silenciadas en Cloud por esa decisión; no registrar dominio en preload durante preparación. Local LAN: **W004** silenciada, HSTS=0 hasta validación física de CA interna. No se silencian errores de cookies, clave, DEBUG o HTTPS. Ejecutar `check --deploy` con el perfil y HTTPS reales; la simulación HTTP no pasa todos los controles de producción.

Caddy/Nginx termina TLS y solo envía al proceso WSGI en loopback. No exponer puerto Waitress. Waitress debe confiar en `x-forwarded-proto` y `x-forwarded-for` **solo** del proxy loopback, y limpiar headers no confiables. Runtime Local lo configura así. Para Cloud usar configuración equivalente (trusted_proxy=127.0.0.1, trusted_proxy_count=1, trusted_proxy_headers de esos dos headers, clear_untrusted_proxy_headers=True, expose_tracebacks=False). El proxy reemplaza `X-Forwarded-For` con la IP de cliente comprobada; no aceptar cadenas arbitrarias de Internet. Django no confía directamente en un X-Forwarded-Proto recibido de cualquier cliente.

Rate limits usan REMOTE_ADDR que valida WSGI, ignoran XFF de petición. Confirmar en 4E que clientes distintos no colapsan todos a 127.0.0.1; ajustar umbrales para NAT empresarial real, sin desactivar lockout PIN. Firewall: Local 443 solo red autorizada, impresoras IP/puertos específicos; Cloud 443 público, SSH administrativo restringido; no abrir DB, debug print ni carpetas privadas. Certificados/cadena confiable en tablets: cámara requiere contexto seguro HTTPS. Scanner se niega a iniciarla en contexto inseguro; localhost solo para desarrollo.

Headers: nosniff, Referrer-Policy=same-origin, X-Frame-Options=DENY; CSP self para scripts/conexiones, worker self/blob, imágenes self/data/blob, estilos inline necesarios por mapas/plantillas, object none/base self/form self/frame-ancestors none. Permissions-Policy camera=(self), micrófono/geolocalización deshabilitados. No se añadió dependencia CSP. QR y scripts son locales; revisar consola, navegación, cámara real y CSS en dispositivos en 4E.

## Archivos e imágenes

Imágenes de evento, comprobantes de reserva/evento: límite 5 MiB, formato real JPEG/PNG/WebP con Pillow verify + decodificación, decompression-bomb warning tratado como error. Nombre normalizado a extensión real y storage aleatorio UUID; no ejecutar/servir HTML según nombre suministrado. Pruebas incluyen `../`, Unicode, barra Windows y doble extensión. Nuevos uploads no confían en extensión/MIME; los archivos históricos siguen requiriendo controles/ACL. Limitar cuerpo también en proxy (tamaño suficiente para multipart de 5 MiB, por ejemplo 6 MiB), timeout y carga simultánea.

Imágenes públicas de eventos/productos en PUBLIC_MEDIA_ROOT o LOCAL_MEDIA_ROOT. Comprobantes en raíces privadas fuera de media y sin alias web; endpoints autorizados existentes verifican usuario/token de acceso. Configurar proxy para servir solo la raíz pública, nunca private, backups, logs, estado o checkout. No usar un alias `/media/` al directorio padre de todos los datos.

## Abuso, mantenimiento y logs

Por IP/ventana de 300s, valores configurables: login Gerencia/PIN/admin 20, formularios públicos 12, carga de comprobantes 10, API sync 120 (también GET). 429 incluye Retry-After. Lockout PIN existente se conserva. Contadores JSON privados, claves hash sin IP literal; lock filesystem entre procesos de la misma instalación. Error de almacenamiento limita acceso con 503. No es rate limiting distribuido ni mitigación DDoS: una futura granja de instancias necesita backend compartido o límite en proxy. Revisar volumen de locks; no borrarlos mientras haya procesos usando contadores. No puede garantizar disponibilidad bajo ataque de IPs ilimitadas.

`run_maintenance` cada cinco minutos: Cloud (o instalación sin sync) expira holds/reservas/pagos/compras; Local con sync no modifica entidades de autoridad Cloud. Local recupera trabajos de impresión atascados a revisión/FAILED, **sin reimprimir**. Borra únicamente JSON de contadores con nombre hash conocido y antigüedad >24h; conserva lock files y todos los datos comerciales. No borra media/backups/PDFs genéricamente. En recovery se detiene. Si Cloud deja de expirar holds, capacidad puede quedar retenida: supervisar tarea, no confiar en intervención manual.

`check_local_node` incluye espacio libre y reserva MIN_FREE_DISK_GB. Gerencia → Configuración → Backups muestra último DB/media/full, tamaño, fecha, última verificación ligada al manifest, intento fallido y antigüedad; solo lectura con permiso view_configuration, sin rutas absolutas ni botón restore. Backup antiguo no cambia `/healthz/`; no confundir liveness con preparación ni backup.

`check_data_integrity` es solo lectura: órdenes/links activos duplicados por mesa, stock negativo, cajas abiertas duplicadas, pagos sobreasignados, órdenes cerradas con saldo/verificación pendiente, tickets USED sin hora, reservas ARRIVED sin orden, identidades sync repetidas y cursores/feed inválidos. Constraints DB existentes ya cubren unicidad de órdenes/links/caja, stock, identidades y montos básicos; no se duplicaron ni se agregaron modelos/migraciones. No repara ni cambia estados. Auditoría conserva admin de solo lectura sin crear/editar/borrar.

Páginas 400/403/404/500 sobrias con marca y referencia de soporte, sin excepción/traceback. Logs `support.log` rotan 5 MiB ×5; filtros eliminan argumentos, exception y payloads, registran evento/ref/status. Logs Local/sync existentes también filtrados/rotados. No activar DEBUG para compartir errores. PDF de reportes informa fallo comprensible y no toca negocio; impresión/sync fallidos permanecen fuera de la transacción de venta. Proteger acceso y retención de logs; no reenviarlos indiscriminadamente.

## Dependencias y actualizaciones

Revisión sobre Python **3.13.14**, PostgreSQL/cliente **17.10**. Base/dev/prod continúan separados y fijados; Django 5.2.17, psycopg 3.3.6, Pillow 12.3.0, ReportLab 5.0.1; producción Waitress 3.0.2/WhiteNoise 6.12.0; pypdf solo dev/tests. No se añadieron librerías pesadas ni se actualizaron versiones indiscriminadamente. `pip check` valida compatibilidad instalada, no ausencia de CVEs. Revisar avisos de seguridad oficiales y paquetes del SO antes de producción y aplicar actualizaciones probadas en entorno aparte con full previo. Bandit no instalado/ejecutado en esta fase; no declarar una auditoría externa ni certificación de seguridad.
