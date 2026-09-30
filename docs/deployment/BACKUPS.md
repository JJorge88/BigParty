# Backups BIG PARTY — Fase 4D

Preparado y probado en macOS con bases desechables. No se ha desplegado en Windows ni Ubuntu. Responsable: administrador técnico; Gerencia comprueba diariamente fecha/resultado y escala fallos. La instalación física y el destino externo se concretan en 4E.

## Qué se conserva

`backup_database` usa PostgreSQL 17 `pg_dump --format=custom`, sin password en argumentos. El password pasa por un `PGPASSFILE` temporal privado, eliminado al terminar. No se usan fixtures como backup principal. Incluye todos los datos/tablas: usuarios, negocio, auditoría, identidad local y estado completo de sync (identity, outbox, inbox, cursores, conflictos, runtime).

`backup_media` comprime en ZIP únicamente los árboles persistentes de imágenes públicas, comprobantes de reservas y comprobantes de eventos. Omite archivos ocultos, `.tmp`, `.pdf`, `.log`; static, impresiones debug y PDFs regenerables deben vivir fuera de esos árboles. Rechaza enlaces simbólicos. Los comprobantes mantienen almacenamiento privado tras restauración.

`backup_full` crea DB + media y un manifest que referencia ambos manifests y sus SHA256. PostgreSQL comparte un snapshot consistente con la comprobación de tablas. El digest de cada tabla se calcula en ese snapshot usando hashes de filas ordenados; permite comparación exacta después de restaurar sin imprimir registros. Este recorrido adicional cuesta IO/ordenamiento y debe medirse con datos reales.

Media se copia después del dump, sin transacción distribuida con el filesystem. Se detectan cambios de tamaño/mtime durante la copia y ausencia de archivos referidos por el snapshot DB; no se publica un full exitoso si faltan. Mantener archivos subidos inmutables (nombres aleatorios existentes). Para restauración estricta de un cierre, ejecutar full con la actividad pública/operativa detenida brevemente o en ventana de baja actividad. Archivos posteriores pueden acompañar al snapshot y no implican ventas recuperadas adicionales.

**Cloud replica ≠ backup. Local replica ≠ backup. Outbox ≠ backup.** La sincronización no conserva una historia de restauración y puede replicar un error.

## Carpetas y permisos

Configurar `.env.local-node` o entorno Cloud desde los ejemplos, sin subir secretos a Git:

- `BACKUP_ROOT`: absoluto, privado, fuera del checkout, document root, static, media y comprobantes. Subcarpetas `database/`, `media/`, `manifests/`, `logs/`.
- `BACKUP_SECONDARY_ROOT`: otra carpeta absoluta privada, sin anidamiento con la primera. Una segunda carpeta del mismo disco no protege contra pérdida del disco.
- `OPERATIONS_STATE_ROOT`: privado y persistente, separado de todo lo anterior público; contiene recuperación y contadores. Debe sobrevivir reinicios/despliegues.
- `PG_BIN_DIR`: ejecutables PostgreSQL 17, incluidos `pg_dump` y `pg_restore` (`.exe` en Windows).
- `MIN_FREE_DISK_GB=2`: reserva mínima más tamaño estimado. Para DB se reserva también su tamaño actual; para ZIP suma de archivos. Un disco puede llenarse durante la tarea: revisar el resultado, no solo el chequeo inicial.

Unix: directorios 0700, archivos 0600, usuario de servicio y umask 0077. En Windows configurar ACL NTFS explícitas: servicio/administrador de backup, sin Users/Everyone; proteger también TEMP del usuario de servicio (pgpass). `chmod` no sustituye ACL NTFS. No crear un alias web hacia backups, estado ni carpetas privadas. Volumen BitLocker/FileVault/LUKS y medio externo cifrado; custodiar claves de recuperación fuera del equipo. No se implementa criptografía propia.

Manifest JSON externo: ID, fecha UTC, modo, UUID local (media lo consulta si PostgreSQL está disponible; si no, marca identidad no disponible), versión/commit configurados, nombre DB, versión PostgreSQL, archivo, tamaño, SHA256, resultado y duración. Media incluye inventario por archivo. El nombre Windows-safe incorpora fecha, sufijo aleatorio y tipo. No incluye passwords, tokens ni contenido de filas. La DB no es necesaria para verificar un backup. `verify_backup` produce un recibo `.verified.json` separado ligado al hash del manifest; los manifests no se modifican al verificar.

## Comandos

Ejecutar desde el proyecto con su Python y entorno correcto. En Windows usar `.venv\Scripts\python.exe`; ejemplos siguientes usan `python`:

```text
python manage.py backup_database --secondary
python manage.py backup_media --secondary
python manage.py backup_full --secondary
python manage.py backup_after_business_day
python manage.py verify_backup /ruta/privada/manifests/bigparty-...-full.json
python manage.py retain_backups
python manage.py retain_backups --apply
```

`backup_after_business_day` identifica el cierre más reciente y no lo repite si ya lo respaldó. Es comando separado del cierre: nunca dentro de su transacción. Si hay copia secundaria configurada, también la verifica. Los comandos salen con error si falla la tarea; consultar `logs/last-*.json` y el estado del scheduler. Un fallo en el adaptador externo no transforma un backup local en backup externo.

`verify_backup` valida esquema, nombre, tamaño, SHA256 y formato real: catálogo `pg_restore --list` o inventario ZIP completo y hashes por archivo. Rechaza rutas absolutas, traversal, enlaces y duplicados ZIP. **Esto verifica el archivo; la restauración real periódica sigue siendo obligatoria.** SHA256 no autentica contra alguien capaz de reemplazar archivo y manifest: proteger permisos e idealmente conservar una copia externa inmutable.

Solo se restauran manifests de origen confiable. Un dump PostgreSQL puede contener SQL ejecutable. No restaurar archivos recibidos de desconocidos.

## Retención y frecuencia

Valores iniciales configurables: `BACKUP_KEEP_HOURLY=4`, `DAILY=14`, `WEEKLY=8`, `MONTHLY=6`. Son cantidades de intervalos representados con el backup más reciente por intervalo UTC, no promesas de cantidad exacta ni antigüedad máxima. Se conserva la unión de esos grupos y siempre el más reciente de cada tipo. Un full conservado protege sus componentes. Antes de borrar, se verifican tanto los conservados como los candidatos; corrupción interrumpe el borrado. Archivos desconocidos/invalid manifests no se borran automáticamente. `retain_backups` sin `--apply` solo enumera candidatos. Locks de filesystem evitan competir backup/copia/retención en la misma instalación. Ejecutar retención diaria después de copia verificada; revisar también crecimiento de secundarios, que no se purgan desde el primario.

Base inicial: DB **cada 6 horas** (00,06,12,18), full nocturno 05:00 y full postcierre mediante tarea separada cada 15 minutos. Tras medir datos reales, objetivo recomendado DB **cada hora** si la carga lo permite; las ventas pueden justificar WAL/PITR futuro, fuera de 4D. Ajustar `BACKUP_MAX_AGE_HOURS` (8 para 6h; 2 para 1h). Si una tarea sigue ejecutándose, no iniciar otra; registrar fallo y revisar retrasos.

### Windows Task Scheduler (preparación; no instalado)

Usuario dedicado sin privilegios de administrador, “ejecutar aunque no haya sesión iniciada”, carpeta inicial del proyecto, política de script firmada/aprobada de la organización. Acción: `powershell.exe -NoProfile -NonInteractive -File "C:\ruta\Big Party\deploy\windows\backup-database.ps1" -Secondary`. No pasar passwords por argumentos.

| Tarea | Script/acción | Frecuencia |
|---|---|---|
| DB | `backup-database.ps1 -Secondary` | cada 6h; cambiar a 1h tras medir |
| Full | `backup-full.ps1 -Secondary` | diario 05:00 |
| Postcierre | `backup-after-business-day.ps1` | cada 15 min |
| Mantenimiento | `maintenance.ps1` | cada 5 min |
| Retención | Python `manage.py retain_backups --apply` con el mismo entorno privado | diario, tras verificar full/copia |
| Sync | `start-sync-worker.ps1` existente | al iniciar; una sola instancia, reinicio con espera |

El entorno se lee mediante python-dotenv, nunca se evalúa como código PowerShell. Aplicar la cuenta/entorno también a la tarea de retención. Configurar “no iniciar nueva instancia”, recuperar tareas omitidas y aviso por código de salida distinto de cero. Recovery bloquea mantenimiento y worker; deshabilitar sus reinicios durante un incidente.

### Ubuntu systemd (ejemplos; no instalado)

`deploy/linux/` contiene wrappers portables y pares service/timer `.example` para DB, full y mantenimiento. Revisar usuario `bigparty`, `/opt/bigparty`, `/etc/bigparty/cloud.env`, permisos, ejecutables y zona horaria antes de copiar a `/etc/systemd/system/`. Los servicios DB/full solicitan copia secundaria; el mount debe estar disponible y verificado. No confundir una carpeta vacía local con NAS montado. Añadir dependencia de mount `RequiresMountsFor=` acorde al servidor. Habilitar timers solo en 4E. Full: 05:00; DB: cada 6h; maintenance: 5min. Verificar `systemctl list-timers` y `journalctl -u bigparty-full.service` sin compartir secretos. Añadir tarea diaria de retención después del full/copia con el mismo entorno. Mantener `sync_worker` como servicio separado con reinicio limitado según SYNC-RUNBOOK.

## Copia fuera del equipo: requisito obligatorio

**Al menos un full diario debe terminar fuera del equipo** y verificarse allí. No hay proveedor ni credenciales integrados. El responsable debe elegir NAS/volumen externo rotado/S3 compatible/rclone con cifrado, control de acceso, retención e idealmente inmutabilidad. Probar acceso a la copia sin el equipo original. Una copia secundaria en el mismo disco no cumple este requisito.

Interfaz opcional: `BACKUP_OFFSITE_COMMAND` es un array JSON de ejecutable y argumentos, por ejemplo una ruta a un adaptador propio revisado (sin secretos en argv). `backup_full --offsite` añade como último argumento el manifest absoluto. El adaptador debe transferir ese manifest, los dos manifests hijos y sus archivos, verificar hashes en destino y salir 0 solo con recibo duradero; errores salen distinto de cero. No usa shell. La aplicación registra únicamente que el adaptador terminó; **no certifica disponibilidad remota por sí sola**. Programar esta acción nocturna cuando exista el destino; no dejar producción dependiendo de un adaptador vacío.

## Restauración, RPO y RTO

Consultar [DISASTER-RECOVERY.md](DISASTER-RECOVERY.md). DB objetivo hasta 6h de cambios con programación inicial, hasta 1h si se adopta horario y las tareas/copia funcionan. Media objetivo hasta intervalo full; pérdida total del equipo puede dejar solo el último full externo diario (hasta 24h). Estos son objetivos, no garantías: fallos de copia amplían la pérdida. Sync puede ayudar a comparar evidencia pero nunca reemplaza el punto de recuperación.

RTO se mide desde detección hasta reapertura autorizada: provisión, descarga externa, restore, media, diagnósticos, conciliación sync y prueba del POS. No hay SLA comercial todavía. El pequeño drill de desarrollo no representa disco real, red externa ni volumen proyectado. Repetir antes de go-live, después de cambios relevantes y mensualmente; responsable conserva fecha, versión, tamaños, tiempos y resultado, sin datos sensibles.

## Evidencia Fase 4D

`scripts/validate_recovery.py` crea bases con nombre aleatorio, datos representativos, imágenes/comprobantes, outbox pendiente; hace full/copia/verificación, destruye únicamente esas bases, restaura otras nuevas, compara cada tabla por conteo/hash exacto, comprueba media/identidad/recuperación/POS y reconecta el worker real a un Cloud restaurado en loopback. Termina eliminando bases/archivos temporales. Requiere rol **de desarrollo** con CREATEDB; nunca ejecutar contra nombres reales ni con credenciales de producción.

Medición macOS, Python 3.13.14, PostgreSQL 17.10, dataset pequeño: dump local **aproximadamente 405 KB (~396 KiB), ~0.2 s**; ZIP de dos imágenes sintéticas **640 bytes, ≤0.005 s**. Datos representativos: 1 venta cerrada, 1 pago Q50, stock descontado, caja/jornada cerradas, 1 reserva, 1 evento, 2 entradas, 28 eventos de sync. No es benchmark científico ni base suficiente para prometer rendimiento a escala. Se conserva 6h como ejemplo inicial; se recomienda medir y reducir a 1h para ventas antes de puesta en marcha si no afecta operación.

Referencias oficiales: [pg_dump PostgreSQL 17](https://www.postgresql.org/docs/17/app-pgdump.html), [pg_restore PostgreSQL 17](https://www.postgresql.org/docs/17/app-pgrestore.html).
