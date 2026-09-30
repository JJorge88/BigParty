# Recuperación de desastres — BIG PARTY

Runbook Fase 4D, probado con datos temporales. **Sin failover de segundo nodo, sin despliegue físico y sin conciliación automática de backups antiguos.** Responsable técnico ejecuta; Gerencia autoriza reapertura después de validar caja/ventas. Registrar versión, incidente, manifiestos, tiempos y decisión sin copiar datos personales ni secretos a logs/tickets.

## Secuencia común: recuperar el mismo nodo o Cloud

1. Detener el servicio/tarea `sync_worker` y su reinicio automático; detener mantenimiento y programación de backups/retención durante el incidente. Bloquear acceso operativo y público en el proxy si la DB está caída. No mantener dos instancias operando con el mismo UUID.
2. Configurar `RECOVERY_MODE=true` en el entorno privado y ejecutar `python manage.py enter_recovery_mode` si la aplicación puede cargar configuración. El marcador en `OPERATIONS_STATE_ROOT/recovery.json` funciona sin DB. No depende de memoria. El middleware bloquea POS/mutaciones; Gerencia permite consultas con banner; el worker rechaza arrancar y las operaciones de dominio quedan bloqueadas. `/healthz/` sigue siendo liveness y `/readyz/` informa DB.
3. Preservar disco/DB dañados para diagnóstico; copiar backups a un volumen sano privado. Recuperar entorno/secretos por el canal seguro separado. No están incluidos en el backup; sin claves originales ciertos tokens/snapshots no serán válidos. Instalar la **misma versión/commit** Python 3.13, dependencias fijadas y herramientas PG17, antes de plantear actualización.
4. Elegir full verificado y, si corresponde, un DB posterior que tenga toda su media requerida. No mezclar componentes sin revisar referencias. Ejecutar `python manage.py verify_backup /privado/manifests/bigparty-...-full.json`. Verificar también el manifest DB y media seleccionados.
5. Restaurar **a una base nueva**, con un usuario temporal de recuperación autorizado a CREATE DATABASE. Ejemplo:

   ```text
   python manage.py restore_database /privado/manifests/bigparty-...-database.json --target-database bigparty_recovered_20260929 --confirm
   python manage.py restore_media /privado/manifests/bigparty-...-media.json --target-directory /privado/restored-media
   ```

   `restore_database` consume el manifest, no solo el `.dump`. Rechaza DB activa/configurada, postgres/templates, nombres inseguros y cualquier destino existente. Usa `pg_restore --single-transaction --exit-on-error`, nunca DROP ni `--clean`; un fallo conserva el destino para diagnóstico y el modo recuperación permanece activo. Espacio/privilegios/servidor los revisa el operador antes. No reintentar sobre ese mismo destino: inspeccionarlo y escoger otro nombre si hace falta.

   `restore_media` extrae `public/`, `reservation-proofs/`, `event-proofs/` en una carpeta nueva separada de las ubicaciones activas. Si ya existe exige **ambos** `--force --confirm`; reemplaza solo nombres coincidentes, conserva los demás. Preferir siempre carpeta nueva. No apunta automáticamente al storage operativo ni expone pruebas privadas.
6. Ajustar `DB_NAME` al destino. Dar permisos al rol normal de aplicación y dejar de usar el rol de recuperación. Revisión DBA: owner/schema, tablas y secuencias, permisos para futuras migraciones; ver HARDENING. En Local: `LOCAL_MEDIA_ROOT=/privado/restored-media/public`, `LOCAL_PRIVATE_ROOT=/privado/restored-media`. En Cloud: `PUBLIC_MEDIA_ROOT` al `public` restaurado y las dos variables de proofs a sus respectivos subdirectorios. Caddy/Nginx solo sirven public. Conservar `OPERATIONS_STATE_ROOT`, el marcador y `RECOVERY_MODE=true`.
7. Antes de iniciar tráfico o cambiar datos:

   ```text
   python manage.py migrate --check
   python manage.py check
   python manage.py check --deploy
   python manage.py verify_restored_system --manifest /privado/manifests/bigparty-...-database.json
   python manage.py check_data_integrity
   python manage.py check_recovery
   python manage.py check_sync
   ```

   `verify_restored_system` comprueba migraciones, conteos, referencias media, identidad local, invariantes y compara huellas exactas de **todas** las tablas del snapshot cuando recibe `--manifest`. No abrir sesiones web antes de esta comparación: auth/sesiones/auditoría legítimamente cambian filas. No imprimir datos sensibles. Sin `--manifest` es diagnóstico actual, no comparación exacta. Los archivos se comparan por SHA al verificar/restaurar ZIP. En Local ejecutar además `collectstatic --noinput` si cambia el paquete y `check_local_node`.
8. Comparar sync con Cloud: UUID del nodo, event_uuid pendientes, última secuencia/cursor, inbox/outbox/conflictos y versiones. Documentar qué cambios quedan después del backup. **No resetear cursores, identidades, outbox o runtime**. No ejecutar bootstrap para “arreglar” una restauración. No editar saldos/inventario genéricamente.
9. Con revisión completa, cambiar `RECOVERY_MODE=false` en el entorno **manteniendo el marcador activo**. Ejecutar:

   ```text
   python manage.py complete_recovery --confirm --sync-reviewed
   ```

   `exit_recovery_mode` es alias con las mismas protecciones. Exige confirmación/revisión, DB destino correcta e integridad/migraciones/media válidas. No reinicia automáticamente el worker ni decide por el operador si Cloud y un backup antiguo son compatibles. Si el flag de entorno sigue true, rechaza salida. No borrar el marcador manualmente como atajo.
10. Reiniciar aplicación con el entorno revisado; reiniciar worker **explícitamente** después de aprobar conciliación. Probar una operación controlada POS/caja sin alterar ventas históricas, impresión y QR según checklist. Revisar estados sync, sin duplicar documentos comerciales. Restaurar tareas programadas y crear/verificar un nuevo full/copia externa. Registrar RTO y pérdida estimada.

## Casos

### Corrupción PostgreSQL / error humano

Conservar evidencia. Usar punto previo al daño en base nueva; no reparar con SQL genérico. Si el daño se sincronizó, la réplica también puede estar afectada. Reconstrucción de cambios posteriores requiere revisión del dominio y conciliación explícita; detenerse antes de liberar recuperación si no se puede demostrar integridad.

### Disco o Local Node perdido (mismo nodo)

Recuperar desde copia **fuera del equipo**, nuevo disco/PC protegido, PostgreSQL y misma versión. Seguir secuencia común. La tabla `LocalNodeIdentity` del dump conserva `node_uuid`; configurar Cloud/Local con ese mismo UUID. Confirmar que el hardware viejo está apagado/aislado. Recuperar media privada y secretos. Dirección LAN, certificado raíz, impresoras y tareas requieren validación física en 4E. El hardware diferente no convierte esta recuperación lógica en un nodo nuevo.

### Instalación de nodo realmente nuevo

Base vacía y procedimiento `init_local_node`/`prepare_local_node` de LOCAL-NODE-WINDOWS. **No clonar un dump de otro nodo para cambiarle solamente el UUID**: dejaría identidades, eventos y ownership incompatibles. Planificar enrolamiento/baseline autorizado y actualizar la configuración Cloud para el nodo elegido. Dos nodos activos y failover están fuera de 4D.

### Cloud perdido

Detener ingreso público y worker Local, restaurar Cloud en nueva DB/media por secuencia común. Comparar qué eventos Local ya marcó SENT después del punto Cloud restaurado; no suponer que el worker los reenviará automáticamente. Conservar outbox Local e identificar UUID exactos a reentregar mediante procedimiento supervisado. No marcar masivamente todo como pendiente ni fabricar UUID nuevos. El drill prueba el caso con outbox pendiente restaurada y Cloud que ya recibió esos mismos UUID: reintento idempotente sin duplicaciones. Recuperar eventos ausentes posteriores es conciliación de incidente, no reparación automática implementada.

### Backup Local de seis horas atrás / sync inconsistente

1. Worker y autoarranque detenidos; recuperación activa.
2. Restaurar y ejecutar diagnóstico/huellas antes de tráfico.
3. Comparar cursor local con feed Cloud e inbox; comparar UUID/versiones/outbox con evidencia Cloud posterior.
4. Inventariar ventas/pagos/stock/caja/reservas ocurridos después del backup; la réplica no contiene necesariamente todos los datos privados ni todas las entidades locales.
5. Diseñar reconciliación específica con revisión técnica y de Gerencia. No limpiar cursores ni inventar eventos, no repetir cobros/impresiones para “reconstruir”. Mantener operación suspendida si hay divergencia no resuelta.
6. Solo tras resolver y validar, completar recovery y una ronda sync controlada, revisar conflictos/contadores y decidir reinicio continuo.

### Deploy incorrecto

Detener tráfico/worker, preservar full previo, código/entorno/logs seguros. Volver al commit conocido si schema compatible; no ejecutar migraciones reversas a ciegas. Si incompatible, restaurar full en DB nueva con código correspondiente y conciliar cambios posteriores. No restaurar DB automáticamente solo porque falló arranque.

### Pérdida de media

Verificar ZIP y restaurar en carpeta nueva; comparar SHA256, permisos y referencias DB. Cambiar rutas/proxy de público únicamente después de validación. Si el DB es posterior a media, los archivos faltantes deben recuperarse de otra copia; `verify_restored_system` los identifica. No publicar comprobantes privados para facilitar diagnóstico.

### Secreto comprometido

Aislar acceso, detener sync, revocar credenciales involucradas y revisar auditoría. Aplicar rotación según HARDENING, cerrar sesiones afectadas y actualizar backup/cifrado si correspondiera. No usar ventana de clave anterior para una clave comprometida: revocarla inmediatamente y coordinar caída breve. Conservar backups antiguos protegidos y plan de verificación de snapshots; no pegar secretos en chat/logs/CLI.

## Validación reproducible

En Mac, con PostgreSQL de desarrollo y `PG_BIN_DIR` de PG17, ejecutar `.venv/bin/python scripts/validate_recovery.py`. Solo usa bases aleatorias propias; las destruye/restaura y limpia al terminar. No ejecuta tareas Windows, instala servicios, cambia DNS ni toca servidores externos. Salida satisfactoria: `4D DISASTER DRILL COMPLETE` y limpieza confirmada. Incluye hashes DB/media, preservación de UUID, recovery bloqueante, POS reabierto, Cloud restaurado, worker HTTP reconectado, idempotencia, maintenance y `check --deploy` en ambos perfiles. Véase BACKUPS para medición y limitaciones de RPO/RTO.
