# Checklist previa a go-live — pendiente 4E

4D prepara código/runbooks; **no habilita go-live**. Responsable técnico y Gerencia firman evidencia de cada punto en instalación real. Referencias: [backups](BACKUPS.md), [recuperación](DISASTER-RECOVERY.md), [hardening](../security/HARDENING.md), [Local Windows](LOCAL-NODE-WINDOWS.md), [sync](SYNC-RUNBOOK.md).

## Entorno y acceso

- [ ] Commit/versiones exactos registrados; Python 3.13 y PG17 compatibles, requisitos prod instalados, pip check y revisión de avisos de seguridad.
- [ ] DEBUG false; hosts sin comodín; CSRF origins exactos; URLs/mode correctos en ambos nodos.
- [ ] Tres secretos aleatorios/independientes presentes y copia segura; previous sync vacío salvo ventana documentada; plan de rotación y sesiones/tokens/snapshots.
- [ ] Usuario OS dedicado sin admin/sudo; código de solo lectura; ACL mínimas en entorno, media privada, backups, estado, logs y TEMP.
- [ ] Rol app sin SUPERUSER/CREATEDB/CREATEROLE ni membresías peligrosas; check_production_database pasa; roles de migración/backup/recovery separados y grants probados.
- [ ] Superusuario inicial con contraseña fuerte custodiada; usuarios/roles/permisos reales revisados; PINs individuales/lockout; revocar cuentas de prueba.
- [ ] HTTPS certificado y cadena confiable en todas las tablets; Caddy/Nginx correcto; puerto WSGI/DB solo loopback; proxy validado con IP real y headers no falsificables.
- [ ] Firewall Cloud/Windows/LAN/impresoras/administración revisado; no exponer privada/debug/backups.
- [ ] check, migrate --check y check --deploy pasan con excepciones HSTS documentadas y aceptadas para el dominio real.
- [ ] Zona horaria America/Guatemala, hora sincronizada y timestamps scheduler/UTC entendidos.

## Operación y recuperación

- [ ] DB, media, comprobantes, static, logs, estado y backups ubicados correctamente; disco libre/crecimiento/umbral revisados.
- [ ] Backup DB múltiple al día (inicial 6h, objetivo 1h tras medir), full nocturno y postcierre programados con cuenta de servicio y detección de fallo.
- [ ] Copia secundaria verificada y **full externo diario obligatorio** contratado/configurado/probado. Credenciales/clave de cifrado recuperables sin PC original. Ninguna carpeta local simulando mount NAS ausente.
- [ ] Retención dry-run revisada y tarea apply programada tras copias; política secundaria/offsite independiente, sin borrar última copia válida.
- [ ] Restore real en entorno aislado desde copia externa, DB/media/UUID/invariantes/sync/POS probados; RPO/RTO medidos con volumen real y aceptados.
- [ ] Operador sabe activar recovery, detener worker/autostart, revisar Cloud y liberar con complete_recovery; runbook de backup antiguo/Cloud perdido ensayado.
- [ ] Identidad Local coincide con Cloud, no hay segundo nodo simultáneo; bootstrap/reconciliación autorizados y controlados; versiones protocolo/app compatibles.
- [ ] Sync funciona con caída/reconexión Internet y no duplica ventas/pagos; cola/conflictos monitoreados, secretos no aparecen en logs.
- [ ] Maintenance cada 5 min, expira holds/pagos/compras bajo autoridad correcta; stale prints a revisión sin reimpresión; worker programado separadamente.
- [ ] Gerencia puede ver estado backup/antigüedad/verificación sin ver rutas sensibles; responsables revisan fallos diariamente.
- [ ] check_data_integrity/verify_restored_system sin errores; auditoría inaccesible para edición/borrado ordinario.

## Validación física y comercial

- [ ] Ajustes comerciales: razón social, moneda, horarios/jornada, áreas/mesas, precios/impuestos, inventario, reservas/eventos/capacidades.
- [ ] Configuración bancaria real revisada y probada; ningún placeholder en web pública.
- [ ] Apertura/cierre de caja y jornada, pagos mixtos/transferencias, devoluciones y permisos comprobados con Gerencia.
- [ ] IPs/puertos de impresoras reales, rutas y papel correctos; venta no se revierte si falla impresora; reimpresión deliberada.
- [ ] Snapshots QR exportados/importados, clave/source correctos, acceso offline y cámara HTTPS probados en hardware real.
- [ ] Navegación pública/Gerencia/POS, CSP, formularios, uploads, PDF y páginas de error comprobados en desktop/tablets sin tracebacks ni datos privados.
- [ ] DNS/dominio/certificados, servicios Windows/Ubuntu, autoarranque y recuperación tras corte eléctrico configurados solo en 4E autorizada.
- [ ] Soporte/escalamiento, custodia de secretos/copias, acceso remoto y calendario de simulacros acordados; plan rollback firmado.

Estado: **pendiente de ejecución física**. No iniciar despliegue ni cambiar DNS por el solo hecho de aprobar la suite automatizada.
