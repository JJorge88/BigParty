# Operación de sincronización — BIG PARTY 4C

## Preparación

Usar la misma revisión compatible de la aplicación y PostgreSQL independiente.
No activar en una base Cloud que todavía opera ventas/caja como autoridad. Revisar
la [matriz de autoridad](../architecture/SYNC.md) y la identidad de datos existentes.
No se hace merge automático de dos historiales de ventas.

1. Aplicar las migraciones nuevas en cada entorno con su configuración propia.
2. Conservar/inicializar LocalNodeIdentity según 4B. Anotar su UUID, nunca regenerarlo
   para resolver un error de conexión. Debe coincidir con SYNC_NODE_UUID en Cloud.
3. Completar el ejemplo correspondiente: SYNC_ENABLED=true, APP_VERSION, APP_COMMIT,
   SYNC_SHARED_SECRET aleatorio de al menos 32 bytes, ACCESS_SNAPSHOT_SIGNING_KEY
   compartida de al menos 32 bytes y mismo ACCESS_SNAPSHOT_SOURCE.
4. En Local, SYNC_CLOUD_URL debe ser la raíz HTTPS de Cloud. No añadir `/api/sync/`.
   En Cloud, configurar el proxy HTTPS conforme al despliegue existente y sus hosts.
   SYNC_ALLOW_HTTP_DEVELOPMENT=false en ambos; loopback es solo para validación.
5. Mantener relojes Windows/Cloud sincronizados por el sistema operativo. Configurar
   carpeta de logs escribible y archivo de entorno privado. No pegar claves en la UI.
6. Crear el gerente administrativo de Cloud mediante el despliegue existente. Las
   representaciones recibidas de usuarios locales no tienen contraseña ni PIN válidos.

No ejecutar el worker hasta completar la revisión de baseline. Los comandos siguientes
usan `python manage.py ...` con el entorno y la base correctos, no la configuración
de desarrollo por accidente. En Windows los scripts cargan `.env.local-node`.

## Primer enlace y datos preexistentes

- Si Cloud está vacío: preparar Cloud, ejecutar `bootstrap_sync --confirm` allí; arrancar
  su servidor; en Local ejecutar `check_sync --probe` y `bootstrap_sync --confirm`.
  El catálogo/mesas locales llegará a Cloud antes de que se creen reservas sobre él.
- Si Cloud ya tiene reservas/eventos referidos a mesas existentes en ambos lados,
  establecer primero un **mapa revisado de identidad**, en ambos entornos, para cada
  objeto compartido: área/zona/mesa, catálogo si procede y dependencias. Cada fila usa
  el PK de **ese entorno** y el mismo UUID global. Nunca asumir igualdad de integer PK.
- El archivo JSON es una lista con `model_label`, `object_pk`, `entity_uuid`. Ejemplo
  con identificadores ficticios: `[{"model_label":"venues.area","object_pk":"7",
  "entity_uuid":"f295b008-1b6a-46f3-a111-6dad3604ef11"}]`. La fila correspondiente
  local puede usar otro object_pk. El archivo no contiene credenciales.
- Ejecutar `bootstrap_sync --confirm --identity-map /ruta/mapa.json` en Cloud **antes**
  de publicar referencias; arrancar Cloud; ejecutar el equivalente en Local. El mapa
  admite objetos propios y réplicas preexistentes, asigna el origen según autoridad
  y no sustituye UUID ya asignados. Revisar/guardar este mapa como registro operativo.
- Si ya se asignó una identidad equivocada, detener la sincronización y revisar con
  soporte. No resetear UUID/cursor ni borrar tablas para “hacer que pase”.

Local hace handshake, recibe baseline Cloud, produce baseline propio y drena en lotes.
Las dependencias aún ausentes quedan guardadas y se reintentan después de enviar el
baseline propio. Incluye historial financiero, movimientos e ingresos locales 4B.
No reconstruye ventas ni ejecuta otra vez sus servicios. Checkpoints hacen reanudable
el comando, con rondas acotadas. COMPLETE confirma entrega; NEEDS_ATTENTION requiere
revisar pendientes/dependencias y volver a ejecutarlo después de corregir la causa.
La interrupción no borra datos. No hay purge ni limpieza de outbox/inbox en esta fase.

## Operación diaria

`sync_worker` es un proceso separado del servidor POS. `sync_once` hace un ciclo y
termina con error si el transporte/handshake falla. `check_sync` muestra configuración,
último contacto y colas sin revelar secretos. `check_sync --probe` verifica conectividad
y compatibilidad, sin subir operaciones. Con SYNC_ENABLED=false no hace red.

En Gerencia → Configuración → Sincronización revisar:

- Último contacto y último ciclo completado (no son garantía de “Online”).
- Pendientes/fallidos/esperando dependencias; Cloud muestra pendientes reportados.
- Solicitudes de pago PENDING/DELIVERED y resultados terminales.
- Conflictos y su referencia de negocio. “Marcar revisado” no modifica la venta/ticket.

“Sincronizar ahora” solicita un ciclo al worker. Si no hay worker, queda solicitado;
no convierte al servidor web en worker. Durante una caída se respeta el backoff.

## Cloud no responde / outbox crece

El POS conserva su base local y sigue funcionando. Comprobar que el worker está vivo,
PostgreSQL local disponible, URL/HTTPS/DNS y acceso a Cloud. Consultar códigos seguros
en sync.log y `check_sync --probe`. No copiar bases de datos ni reiniciar el POS como
primer remedio. El worker reintenta con 15/30/60/120/240/300 s y vuelve a 15 s al recuperar.
Si el worker murió, reiniciarlo; outbox/inbox/cursor/ACK siguen persistidos.

Si hay contacto reciente pero no drena: revisar FAILED y DEFERRED, versión de aplicación,
identidades compartidas y límites de tamaño. Un esquema incompatible no debe ignorarse.
Un evento grande se conserva FAILED; un snapshot grande impide avanzar ese punto del
feed y requiere revisión. Nunca saltar el cursor ni recortar tickets para continuar.

## Evento fallido / dependencia pendiente

Identificar event_uuid, entity_type y código sin imprimir el payload completo. Verificar
que la entidad de referencia exista con la identidad correcta y que ambos lados usen
la misma versión compatible. Unicidad pendiente también puede necesitar un cambio
anterior para liberar una mesa. Los envíos con menos intentos tienen prioridad para
que las dependencias nuevas puedan llegar.

Corregir la causa con un cambio revisado; después ejecutar `retry_failed_sync` en el
receptor y, si la outbox también está FAILED, en el emisor. Solo hace elegibles eventos;
no sobreescribe datos ni cambia sus UUID. DEFERRED se reintenta automáticamente.
Repetir `sync_once` o dejar al worker. Un APPLIED reenviado es reconocido sin duplicar.

## Conflictos de reservas/acceso

Si llegó una reserva ya cancelada en Cloud, se conserva la cuenta local. Revisar
con Gerencia el servicio efectivamente prestado; la UI no fuerza Cloud a ARRIVED.
Si un ticket fue admitido offline y luego se conoce su cancelación/uso previo,
Cloud conserva CANCELLED/USED y ambos registros disponibles. No borrar el scan ni
reabrir el ticket. Documentar la decisión de negocio y marcar el conflicto revisado.
No existe un botón genérico “usar Local/Cloud”.

## Comandos de pagos

Gerencia Cloud solicita verificar/rechazar solo transferencias/depósitos pendientes.
Hasta que Local ejecute y confirme el comando, el espejo conserva el estado anterior.
Un REJECTED_STALE significa que cambió la versión, estado o jornada: revisar la cuenta
actual, no reenviar forzando una versión. Un ACK perdido es seguro al reintentar.
Una solicitud ya DELIVERED conserva su autorización puntual e identidad; la revocación
se valida antes de la primera entrega. No reutilizar command_uuid con otro payload.

## Rotación de claves / reloj / versiones

Pausar únicamente el worker, actualizar el secreto en los dos entornos privados,
reiniciar sus procesos para recargar entorno y verificar handshake. No hay ventana
con dos secretos simultáneos. Reiniciar worker y reintentar: no cambian los event UUID.
ACCESS_SNAPSHOT_SIGNING_KEY es independiente; coordinarla también antes de importar
snapshots firmados con la nueva clave. Nunca borrar las admisiones locales anteriores.

AUTHENTICATION_FAILED: revisar UUID esperado, secreto y reloj. HTTPS_REQUIRED: revisar
URL/proxy, no habilitar HTTP en producción. INCOMPATIBLE_PROTOCOL_OR_APP: desplegar
revisiones compatibles y declarar APP_VERSION; la lista de compatibilidad debe ser
explícita. No bajar schema_version artificialmente ni ampliar compatibilidad a ciegas.

## Windows — tarea separada

Entregar `deploy/windows/start-sync-worker.ps1` y `check-sync.ps1`. Ambos cargan el
helper 4B, usan rutas literales/argumentos separados, no evalúan dotenv ni imprimen
secretos; devuelven 0/1. `check-sync.ps1 -Probe` añade handshake de solo lectura.

En Task Scheduler crear **BIG PARTY Sync Worker**:

- Cuenta del servicio local con acceso a entorno, PostgreSQL y carpeta de logs.
- Trigger: al iniciar el equipo; arrancar después de PostgreSQL (reintentos activados).
- Programa: `powershell.exe`.
- Argumentos: `-NoProfile -File "C:\BigParty\deploy\windows\start-sync-worker.ps1"`.
  Ajustar a la ruta instalada, incluyendo comillas si contiene espacios.
- Directorio de inicio: raíz real de BIG PARTY.
- Ejecutar aunque no haya sesión iniciada; no iniciar una segunda instancia si ya corre.
- Reiniciar si falla, cada minuto, con varios intentos; sin límite de ejecución por horas.
- Waitress conserva su tarea independiente. Detener worker no debe detener Waitress.

Probar allí inicio tras reiniciar Windows, corte/restablecimiento de red y diagnóstico
sin secretos. **Estos scripts no se ejecutaron en Mac**. No cambiar la política de
PowerShell global ni añadir reglas de firewall como parte de 4C.

## Validación reproducible en Mac

`python manage.py test apps.sync.tests` incluye auth, rollback, idempotencia, versiones,
fallos de transporte, dependencias, comandos obsoletos y límites de consultas.
`python scripts/validate_sync_two_instances.py` requiere PostgreSQL local/CREATE DATABASE:
crea bases con nombres aleatorios, dos servidores Waitress y claves temporales.
No usa bases de operación ni copia dumps. El bloque finally detiene sus servidores y
elimina exclusivamente sus dos bases. Comprueba POS offline, stock 27, caja, reserva,
comandos, QR/snapshot, respuesta perdida, conflicto visible y 1000 eventos/lotes de 100.
La caída de 30 minutos se simula con reloj lógico/backoff; no se espera media hora real.

Fuera de alcance: backups/restauración, retención/purge, failover, sincronización de
media, multi-nodo y hardening adicional. No iniciar 4D con estos comandos.
