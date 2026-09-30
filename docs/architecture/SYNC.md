# Sincronización de aplicación — Fase 4C

Una instalación Cloud y un Local Node, PostgreSQL independiente en cada entorno.
Protocolo 1. No hay replicación de PostgreSQL, dumps, rsync, multi-master ni Celery.
`SYNC_ENABLED=false` mantiene el comportamiento 4B y no inicia transporte.

## Autoridad y contratos

| Dominio | Autoridad | Réplica/uso |
| --- | --- | --- |
| Áreas, zonas, mesas, catálogo, precios, modificadores, componentes | Local | Cloud: web pública y reportes, sin edición |
| Jornadas/reaperturas, cajas/sesiones, entregas y movimientos | Local | Cloud: estados y detalle financiero |
| Cuentas, vínculos de mesas, subcuentas, líneas/componentes | Local | Cloud: reportes, sin ejecutar servicios de venta |
| Pagos operativos/asignaciones, ajustes, devoluciones | Local | Cloud: consulta; únicamente comandos de verificar/rechazar pendientes |
| Inventario/movimientos y stock actual | Local | Cloud: historial y asignación del stock final; no descontar otra vez |
| Usuarios operativos y permisos | Local | Cloud recibe UUID, nombre, rol, activo; **no permisos ni credenciales** |
| Reservas, pagos de reserva y configuración | Cloud | Local: reservas relevantes y llegada controlada |
| Eventos, tipos, configuración de mesas, compras/items/pagos/tickets | Cloud | Local: información operativa de evento y snapshot firmado de acceso |
| Configuración bancaria pública | Cloud | Local: lectura de datos públicos de transferencia |
| LocalAccessScan | Local | Cloud: evidencia, actualización controlada de ticket y conflictos |
| Printer, PrintJob, dispositivos, sesiones, auditoría general | Exclusivamente local/no replicados | Nunca se reimprime por recibir datos |

El registry enumera cada entidad, campos revisados, autoridad, codec, applier,
dependencias y schema_version. No hay exportador de modelos ni descubrimiento por
signals. Compras, compradores, comprobantes y tokens de tickets permanecen en Cloud:
el canal de acceso transmite digests y el snapshot firmado de 4B. No se crean copias
locales completas de EventPurchase/Item/Payment/TableReservation/EventTicket.

Las reservas se incluyen si son futuras o activas (pendiente, esperando pago,
pago en revisión, confirmada). Una reserva ya publicada sigue enviando sus estados
terminales aunque deje de ser relevante, para retirar el bloqueo local. El teléfono
y nombre se incluyen para atención y validación del servicio existente; no el token
privado ni el comprobante. El historial terminal nunca publicado no entra al baseline.

## Identidad y transacciones

`SyncIdentity`: UUID global estable, model_label + object_pk únicos, origen y versión
lógica. Los PK solo tienen significado en su propia base. Se asigna identidad lazy.
Las FK viajan como UUID. Dinero: Decimal textual exacto. Fechas: ISO 8601 UTC con zona.
Los identificadores numéricos internos del snapshot 4B siguen siendo identificadores
del origen de ese formato; el wrapper de sincronización añade el UUID global del evento.

Los servicios mutadores revisados usan `sync_atomic` y captura explícita de sus
objetos/dependencias. Escritura de negocio y outbox/feed se confirman en **la misma
transacción**. No se usa on_commit para guardar una outbox después del commit, porque
un fallo entre ambos perdería operaciones. Tampoco hay HTTP en la transacción de venta.
Cambios de modelos directamente por shell/SQL no son una interfaz soportada de operación.
El admin de catálogo/usuarios/mesas/cajas también captura explícitamente sus cambios.

Una fila singleton bloqueada ordena las escrituras del origen hasta COMMIT. Así las
versiones y secuencias publicadas no se adelantan a otra transacción todavía abierta.
El coste es serializar brevemente escrituras locales: decisión para un solo nodo,
no una solución para múltiples establecimientos. Un payload sin cambios no emite versión.

La cuenta incluye su vínculo principal con UUID, versión y payload revisado. Esa
pareja se aplica junta por la FK circular existente; su evento independiente es
idempotente. Al mover una subcuenta, sus líneas conservan la relación compuesta con
el mismo pedido en esa transacción. No se desactivan restricciones históricas.

## Outbox, inbox y feed

Outbox local: UUID único de evento, UUID/tipo/versión de entidad, UPSERT o DELETE
excepcional, payload/schema, fechas, intentos/error seguro y PENDING/SENT/FAILED.
Los agregados incluyen dependencias explícitas y los servicios capturan historiales
creados (inventario, caja, asignaciones, etc.). No se sincroniza AuditLog completo.

Inbox: un event_uuid identifica un sobre inmutable. Reenvío idéntico APPLIED se
reconoce sin tocar negocio. Mismo UUID con otro contenido/origen se rechaza. Una
versión antigua de la entidad no sobrescribe una nueva. Cada evento usa transacción
y savepoint, y verifica restricciones diferidas antes de marcar APPLIED. Una FK
faltante o restricción pendiente queda DEFERRED; schema incompatible queda FAILED.
Un fallo no confirma una aplicación parcial.

Los appliers asignan estado, no vuelven a vender/cobrar/descontar/imprimir. Stock
actual viaja separado de InventoryMovement: recibir el historial no cambia stock.
No se borran historiales. Solo ProductAreaPrice y ComboComponent admiten DELETE
explícito; una línea borrador retirada se conserva CANCELLED cuando sync está activo.
Los borrados de inlines del admin están deshabilitados; usar los servicios de Gerencia.

CloudSyncChange es un feed con secuencia global monotónica asignada bajo el bloqueo
hasta commit, solo de autoridad Cloud y mensajes de conflicto. Local persiste inbox
antes de adelantar SyncCursor. No depende de updated_at ni del reloj para deltas.
DEFERRED se reintenta; los nuevos envíos tienen prioridad sobre intentos repetidos
para que una dependencia posterior no quede bloqueada por el primer lote.

## Transporte y seguridad

API privada: `/api/sync/v1/{push,pull,ack,status}/`. POST push/pull/ack, GET status.
Sesión web no autentica esa API. HMAC-SHA256 incluye método, path/query, timestamp,
SHA256 del body y UUID del nodo esperado. Ventana ±300 segundos, comparación constante.
Las respuestas se firman ligadas a la firma de la petición. HTTPS obligatorio;
HTTP solo con bandera explícita y loopback para pruebas. Sin redirecciones del cliente.

SYNC_SHARED_SECRET y ACCESS_SNAPSHOT_SIGNING_KEY deben tener al menos 32 bytes y
vivir en entorno privado. No se guardan en DB, logs, repo ni UI. Ambos equipos deben
tener hora sincronizada con las herramientas del sistema operativo, sin NTP propio.
Protocolo y APP_VERSION deben ser compatibles antes del intercambio de datos.
El receptor rechaza campos extra y valida tipos/enum/moneda/referencias y schema.
No hay binarios, imágenes, PDFs, contraseñas, PIN, sesiones ni tokens de recuperación.

Lotes por defecto de 100, máximo configurable de 1000; cuerpo máximo 20 MiB, con
presupuesto menor para cada lote/evento. Un snapshot que exceda el límite se detiene
con EVENT_TOO_LARGE; no se recorta ni se omiten tickets. Reducir el lote no divide
un snapshot único: requiere revisar tamaño/diseño antes de continuar.
Timeouts separados: conexión 3 s, lectura 8 s por defecto. Sin dependencia nueva de
rate limiting; usar límites existentes del proxy y acceso exclusivo al endpoint privado.

## Reservas, acceso y comandos

Local ejecuta el servicio existente de llegada, abre una sola cuenta, marca ARRIVED
y publica la cuenta y `reservation.arrived`. Cloud espera dependencias y vincula la
misma cuenta si la reserva está CONFIRMED. Si ya fue cancelada/rechazada/atendida,
registra conflicto sin cerrar ni borrar la cuenta local. Un espejo posterior no
revierte una llegada local ni su cuenta. No se ofrece sobrescritura genérica.

Emisión, anulación y reprogramación de eventos/tickets generan automáticamente el
snapshot firmado 4B. Importar conserva USED local; CANCELLED tiene precedencia.
Cada scan contiene UUID, digest, resultado, fecha, guardia y nodo. Cloud conserva
la evidencia y cambia el ticket a USED si era válido. Si estaba USED o CANCELLED,
registra conflicto con ambos tiempos disponibles y conserva el estado conocido.
Dos escaneos físicos offline en entornos desconectados no pueden impedirse con
sincronización posterior: quedan detectados para revisión humana.

Solo VERIFY_OPERATIONAL_PAYMENT y REJECT_OPERATIONAL_PAYMENT. Cloud valida gerente,
permiso, método y estado, guarda comando con payment_uuid y expected_version. No
edita el pago. Antes de entregar por primera vez vuelve a revisar el permiso del
solicitante. Tras DELIVERED, el sobre es inmutable para permitir reenvíos seguros.
Local valida nodo, tipo, actor/permiso y versión/estado/jornada; ejecuta los servicios
existentes bajo transacción. La representación del actor no recibe permisos persistentes
ni acceso web; la autorización puntual se limita al servicio solicitado.

LocalCommandInbox evita repetir comandos y devuelve APPLIED, FAILED o REJECTED_STALE.
ACK perdido se reenvía sin repetir negocio. Cloud muestra PENDING/DELIVERED y el
resultado terminal, y recibe el nuevo estado del pago por la outbox habitual.
Un cambio local previo prevalece: comando obsoleto no fuerza nada. No hay RPC para
mesas, inventario, precios, caja o usuarios.

## Worker, UI y recuperación

Worker independiente de Waitress, un ciclo por 15 s y backoff 15/30/60/120/240/300 s.
Lock advisory PostgreSQL evita ciclos concurrentes. POS continúa si Cloud o worker
caen. Reiniciar conserva outbox, inbox, cursores, identidades y comandos en PostgreSQL.
`sync_once` ejecuta un ciclo; `retry_failed_sync` vuelve a hacer elegibles fallidos,
sin reescribir negocio; `check_sync --probe` solo hace diagnóstico/handshake.

Gerencia → Configuración → Sincronización muestra último contacto, último éxito,
pendientes, fallidos, dependencias, comandos y conflictos. “Sincronizar ahora” deja
una bandera para el worker; no hace red dentro del request del POS. No afirma “Online”.
Cloud guarda last_seen, versión/commit y pendientes reportados. Marcar revisado cambia
solo la revisión del conflicto. `sync.log` rota (5 MiB × 5), sin payload ni traceback.
Auditoría: bootstrap, conflictos, comandos/resultados, no cada heartbeat.

El bootstrap requiere `--confirm`, conserva datos y checkpoints por entidad. La
conexión inicial necesita revisar identidades si ambos sistemas tienen estructura
preexistente. El mapa explícito relaciona UUID compartido con el PK propio; nunca
se unen registros por coincidencia de PK/nombre. No se reemplazan identidades ya
asignadas. Consultar el runbook para orden de puesta en marcha y recuperación.

## Límites de esta fase

Un nodo; sin failover automático, backup/restore, media sync, purge de historiales,
telemetría externa ni hardening 4D. Los usuarios administrativos propios de Cloud
se provisionan por su mecanismo de despliegue; la réplica de usuarios locales no
permite iniciar sesión. Las pruebas Windows físicas quedan a cargo de la instalación:
los scripts PowerShell se entregan, pero no se ejecutan en Mac.

## Evidencia de validación 4C

La prueba reproducible con dos PostgreSQL y dos Waitress temporales comprobó PK
locales diferentes, bootstrap por HTTP, caída simulada de 30 minutos, reinicio real
del servidor local con outbox pendiente, reconexión y pérdida de respuesta tras aplicar.
También verificó cierre de caja con diferencia cero, confirmación remota y comando
obsoleto, llegada offline, conflictos por cancelación de reserva/ticket y unión de
cuentas con subcuentas bajo las FK compuestas existentes.

Carga: 1000 eventos en diez ciclos de 100, sin duplicados y con inbox completamente
APPLIED. Medición de consultas del receptor: 175 para 10 entidades, 1702 para 100;
crecimiento aproximadamente lineal en esta prueba (no un benchmark de capacidad).
Los reintentos de inbox rotan por último intento, con índices propios de sync, para
que dependencias sin resolver no bloqueen indefinidamente a las siguientes.
Las bases y carpetas temporales se eliminaron y se verificó que no quedara ninguna.

Validación final: **1001 pruebas Django (28 nuevas) y 13 JavaScript aprobadas**.
`manage.py check`, `makemigrations --check --dry-run` y `git diff --check` sin errores.
Las tres migraciones nuevas pertenecen exclusivamente a apps/sync.
