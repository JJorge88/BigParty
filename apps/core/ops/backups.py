"""PostgreSQL official tools, private files, external manifests and safe restore."""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import psycopg
from psycopg import sql
from django.conf import settings
from django.core.management.base import CommandError
from .files import atomic_json, private_root, digest_file, require_space

FORMAT = 1
KINDS = {'database': 'database', 'media': 'media'}


def root():
    value = private_root(settings.BACKUP_ROOT)
    for part in ('database', 'media', 'manifests', 'logs'):
        (value / part).mkdir(parents=True, exist_ok=True, mode=0o700)
    return value


def tool(name):
    candidate = str(Path(settings.PG_BIN_DIR) / (name + ('.exe' if os.name == 'nt' else ''))) if settings.PG_BIN_DIR else shutil.which(name)
    if not candidate or not Path(candidate).is_file():
        raise CommandError('POSTGRES_TOOL_MISSING: configura PG_BIN_DIR.')
    return candidate


def db_parameters(database=None):
    config = settings.DATABASES['default']
    return dict(dbname=database or config['NAME'], user=config['USER'], password=config['PASSWORD'],
                host=config.get('HOST') or 'localhost', port=config.get('PORT') or '5432', connect_timeout=5)


@contextmanager
def pg_environment(database=None):
    config = db_parameters(database)
    # libpq reads a private temporary file, never a password in process arguments.
    with tempfile.TemporaryDirectory(prefix='bigparty-pgpass-') as directory:
        path = Path(directory) / 'pgpass'
        escape = lambda value: str(value).replace('\\', '\\\\').replace(':', '\\:')
        path.write_text(':'.join(escape(config[key]) for key in ('host','port','dbname','user','password')) + '\n')
        path.chmod(0o600)
        environment = {k:v for k,v in os.environ.items() if not k.startswith('PG')}
        environment.update(PGPASSFILE=str(path), PGHOST=str(config['host']), PGPORT=str(config['port']),
                           PGUSER=config['user'], PGDATABASE=config['dbname'], PGCONNECT_TIMEOUT='5')
        try:
            yield environment
        finally:
            path.unlink(missing_ok=True)


def run_tool(name, arguments, database=None):
    with pg_environment(database) as environment:
        try:
            result = subprocess.run([tool(name), *arguments], env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=settings.BACKUP_TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise CommandError('POSTGRES_TOOL_UNAVAILABLE_OR_TIMEOUT') from None
    if result.returncode:
        raise CommandError('POSTGRES_TOOL_FAILED: revisa versión, permisos, espacio y conectividad.')
    return result.stdout


def fingerprint(connection):
    """Digest every row in a stable order; never emits row contents or credentials."""
    connection.execute("SET LOCAL TIME ZONE 'UTC'")
    connection.execute("SET LOCAL datestyle = 'ISO, YMD'")
    connection.execute("SET LOCAL intervalstyle = 'postgres'")
    tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    result = {}
    for (name,) in tables:
        digest = hashlib.sha256(); count = 0
        query = sql.SQL('SELECT md5(row_to_json(t)::text) FROM {} t ORDER BY 1').format(sql.Identifier('public', name))
        with connection.cursor(name='backup_fingerprint') as cursor:
            cursor.execute(query)
            for (row_hash,) in cursor:
                digest.update(row_hash.encode()); count += 1
        result[name] = {'count':count, 'sha256':digest.hexdigest()}
    return result


def metadata(connection=None):
    node = None
    if settings.DEPLOYMENT_MODE == 'local_node' and connection:
        if connection.execute("SELECT to_regclass('public.localnode_localnodeidentity')").fetchone()[0]:
            row = connection.execute('SELECT node_uuid FROM localnode_localnodeidentity WHERE id=1').fetchone()
            node = str(row[0]) if row else None
        if not node:
            raise CommandError('NODE_NOT_INITIALIZED')
    return {'schema_version':FORMAT, 'created_at':datetime.now(timezone.utc).isoformat(),
            'deployment_mode':settings.DEPLOYMENT_MODE, 'node_uuid':node,
            'app_version':settings.APP_VERSION, 'app_commit':settings.APP_COMMIT,
            'database_name':str(settings.DATABASES['default']['NAME']),
            'postgres_version':connection.execute('SHOW server_version').fetchone()[0] if connection else None}


def identifier(kind):
    mode = 'local' if settings.DEPLOYMENT_MODE == 'local_node' else settings.DEPLOYMENT_MODE
    return f'bigparty-{mode}-{datetime.now(timezone.utc):%Y-%m-%dT%H%M%S}-{uuid.uuid4().hex[:8]}-{kind}'


def publish(info, path, started):
    info.update(file_name=path.name, file_size=path.stat().st_size, sha256=digest_file(path),
                status='SUCCESS', duration_seconds=round(time.monotonic()-started,3))
    destination = root() / 'manifests' / (info['backup_id'] + '.json')
    atomic_json(destination, info)
    record('success', info['kind'], info['backup_id'])
    return destination


def record(status, kind, backup_id=''):
    # No payload, connection strings, paths or subprocess stderr in logs.
    atomic_json(root() / 'logs' / f'last-{kind}.json',
        {'status':status, 'kind':kind, 'backup_id':backup_id, 'at':datetime.now(timezone.utc).isoformat()})


def backup_database():
    started = time.monotonic(); destination = root()
    backup_id = identifier('database'); path = destination / 'database' / (backup_id + '.dump')
    partial = path.with_suffix('.partial')
    try:
        require_space(destination)
        with psycopg.connect(**db_parameters()) as connection:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            size = connection.execute('SELECT pg_database_size(current_database())').fetchone()[0]
            require_space(destination, size)
            info = metadata(connection)
            snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
            os.close(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            run_tool('pg_dump', ['--format=custom', '--no-password', '--no-owner', '--no-privileges',
                '--snapshot='+snapshot, '--file='+str(partial)])
            if not partial.is_file() or partial.stat().st_size < 5 or partial.open('rb').read(5) != b'PGDMP':
                raise CommandError('EMPTY_OR_INVALID_DUMP')
            run_tool('pg_restore', ['--list', str(partial)])
            info['verification'] = fingerprint(connection)
            info['media_required'] = required_media(connection)
        partial.chmod(0o600); os.replace(partial, path)
        info.update(backup_id=backup_id, kind='database', format='postgres-custom')
        return publish(info, path, started)
    except (OSError, psycopg.Error, CommandError):
        record('FAILED', 'database', backup_id)
        raise CommandError('BACKUP_DATABASE_FAILED: no se publicó un backup exitoso.') from None
    finally:
        partial.unlink(missing_ok=True)


def media_roots():
    return {'public':Path(settings.MEDIA_ROOT), 'reservation-proofs':Path(settings.RESERVATION_PROOF_ROOT),
            'event-proofs':Path(settings.EVENT_PROOF_ROOT)}


def backup_media():
    started = time.monotonic(); destination = root(); backup_id = identifier('media')
    path = destination / 'media' / (backup_id + '.zip'); partial = path.with_suffix('.partial')
    files = []
    excluded=[Path(settings.STATIC_ROOT),Path(settings.PRINTER_DEBUG_DIR)]
    for setting in ('LOCAL_LOG_ROOT','SUPPORT_LOG_ROOT','SYNC_LOG_ROOT'):
        if getattr(settings,setting,None):excluded.append(Path(getattr(settings,setting)))
    excluded=[folder.resolve() for folder in excluded]
    try:
        for label, source in media_roots().items():
            if source.is_symlink():raise CommandError('SYMLINK_MEDIA_ROOT')
            if not source.exists():continue
            for item in sorted(source.rglob('*')):
                if item.is_symlink():raise CommandError('SYMLINK_MEDIA_FILE')
                if item.is_file():
                    relative = item.relative_to(source)
                    if any(item.resolve().is_relative_to(folder) for folder in excluded):continue
                    if any(part.startswith('.') for part in relative.parts) or item.suffix.lower() in ('.tmp','.pdf','.log'):
                        continue
                    files.append((label+'/'+relative.as_posix(), item))
        require_space(destination, sum(path.stat().st_size for _,path in files))
        inventory = {}
        os.close(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for name, item in files:
                before = item.stat()
                archive.write(item, name)
                after = item.stat()
                if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
                    raise CommandError('MEDIA_CHANGED_DURING_BACKUP')
                inventory[name] = {'size':after.st_size}
        # Re-read persisted ZIP metadata: on Windows, from_file() can retain
        # backslashes in orig_filename while writing forward slashes on disk.
        # Reading through the writer then compares these different names.
        with zipfile.ZipFile(partial, 'r') as archive:
            for name, entry in inventory.items():
                with archive.open(name) as stream:
                    entry['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        partial.chmod(0o600); os.replace(partial, path)
        info = metadata()
        if settings.DEPLOYMENT_MODE == 'local_node':
            try:
                with psycopg.connect(**db_parameters()) as connection:
                    info = metadata(connection)
            except psycopg.Error:
                # Media can still be rescued when PostgreSQL is unavailable.
                info['identity_unavailable'] = True
        info.update(backup_id=backup_id, kind='media', format='zip', entries=inventory)
        return publish(info, path, started)
    except (OSError, CommandError, zipfile.BadZipFile):
        record('FAILED','media',backup_id)
        raise CommandError('BACKUP_MEDIA_FAILED') from None
    finally:
        partial.unlink(missing_ok=True)


def read_manifest(manifest):
    manifest = Path(manifest)
    try:
        if manifest.is_symlink() or manifest.stat().st_size > 64*1024*1024:raise ValueError
        value = json.loads(manifest.read_text())
        if not isinstance(value,dict) or value['schema_version'] != FORMAT or value['status'] != 'SUCCESS':raise ValueError
        if value['kind'] not in (*KINDS,'full'):raise ValueError
        if not re.fullmatch(r'[A-Za-z0-9-]{10,150}', value['backup_id']):raise ValueError
        date = datetime.fromisoformat(value['created_at'])
        if date.tzinfo is None:raise ValueError
        if value['kind'] in KINDS:
            if type(value['file_size']) is not int or value['file_size'] <= 0:raise ValueError
            if not re.fullmatch(r'[a-f0-9]{64}', value['sha256']):raise ValueError
            name = value['file_name']
            if Path(name).name != name or '/' in name or '\\' in name:raise ValueError
            if value['format'] != ('postgres-custom' if value['kind']=='database' else 'zip'):raise ValueError
            extension = '.dump' if value['kind']=='database' else '.zip'
            if name != value['backup_id']+extension:raise ValueError
        return value
    except (OSError,ValueError,KeyError,TypeError):
        raise CommandError('INVALID_MANIFEST') from None


def _verify(manifest, *, mark=True):
    manifest = Path(manifest).absolute(); info = read_manifest(manifest)
    if info['kind'] == 'full':
        children = info.get('children', [])
        if not isinstance(children,list) or len(children) != 2:raise CommandError('INVALID_FULL_MANIFEST')
        child_kinds=set()
        for child in children:
            if not re.fullmatch(r'bigparty-[A-Za-z0-9-]+\.json',child['manifest']):raise CommandError('INVALID_FULL_MANIFEST')
            child_path = manifest.parent / child['manifest']
            if digest_file(child_path) != child['sha256']:raise CommandError('MANIFEST_CHECKSUM_MISMATCH')
            child_info=read_manifest(child_path)
            if child_info['kind'] not in KINDS:raise CommandError('INVALID_FULL_CHILD')
            child_kinds.add(child_info['kind'])
            verify(child_path, mark=False)
        if child_kinds != set(KINDS):raise CommandError('INVALID_FULL_MANIFEST')
    else:
        path = manifest.parent.parent / KINDS[info['kind']] / info['file_name']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != info['file_size'] or digest_file(path) != info['sha256']:
            raise CommandError('BACKUP_CHECKSUM_MISMATCH')
        if info['kind']=='database':
            with path.open('rb') as stream:
                if stream.read(5) != b'PGDMP':raise CommandError('INVALID_DUMP_FORMAT')
            run_tool('pg_restore',['--list',str(path)])
        else:
            with zipfile.ZipFile(path) as archive:
                entries = info.get('entries',{})
                if len(archive.namelist()) != len(set(archive.namelist())) or set(archive.namelist()) != set(entries):raise CommandError('INVALID_MEDIA_INVENTORY')
                for entry in archive.infolist():
                    name = PurePosixPath(entry.filename)
                    if name.is_absolute() or '..' in name.parts or ':' in entry.filename or '\\' in entry.filename or not name.parts or name.parts[0] not in media_roots() or stat.S_ISLNK(entry.external_attr >> 16):
                        raise CommandError('UNSAFE_ARCHIVE_PATH')
                    with archive.open(entry) as stream:
                        checksum = hashlib.file_digest(stream,'sha256').hexdigest()
                    if checksum != entries[entry.filename]['sha256'] or entry.file_size != entries[entry.filename]['size']:
                        raise CommandError('MEDIA_CHECKSUM_MISMATCH')
    if mark:
        atomic_json(manifest.with_suffix('.verified.json'),{'backup_id':info['backup_id'],'manifest_sha256':digest_file(manifest),'verified_at':datetime.now(timezone.utc).isoformat()})
    return info


def verify(manifest, *, mark=True):
    try:
        return _verify(manifest, mark=mark)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError):
        raise CommandError('INVALID_OR_UNREADABLE_BACKUP') from None


def backup_full():
    try:
        db = backup_database(); media = backup_media()
        info = read_manifest(db); backup_id = identifier('full')
        media_info=read_manifest(media)
        available=media_info['entries']
        if any(name not in available for name in info.get('media_required',[])):
            record('FAILED','full',backup_id)
            raise CommandError('FULL_MEDIA_INCOMPLETE: falta media referida por el snapshot de base de datos.')
        full = {key:info[key] for key in ('schema_version','created_at','deployment_mode','node_uuid','app_version','app_commit','database_name','postgres_version')}
        full.update(backup_id=backup_id,kind='full',status='SUCCESS',file_size=info['file_size']+media_info['file_size'],consistency='database snapshot; media copied afterwards; verify references before release',
                    children=[{'manifest':p.name,'sha256':digest_file(p)} for p in (db,media)])
        destination = root()/'manifests'/(backup_id+'.json'); atomic_json(destination,full)
        verify(destination); record('success','full',backup_id)
        return destination
    except (CommandError, OSError):
        record("FAILED", "full")
        raise


def restore_database(manifest, target, confirm=False):
    if not confirm:raise CommandError('Requiere --confirm y una base de destino nueva.')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',target or '') or target in (str(settings.DATABASES['default']['NAME']),'postgres','template0','template1'):
        raise CommandError('UNSAFE_RESTORE_TARGET')
    info = verify(manifest)
    if info['kind'] != 'database':raise CommandError('DATABASE_MANIFEST_REQUIRED')
    from .recovery import enter
    # Fail closed before creating/restoring a database, including failed restores.
    enter('Database restoration in progress; compare sync before release', target_database=target)
    path = Path(manifest).resolve().parent.parent/'database'/info['file_name']
    # A new empty target only. Never DROP, --clean or overwrite an existing database.
    with psycopg.connect(**db_parameters('postgres'),autocommit=True) as connection:
        if connection.execute('SELECT 1 FROM pg_database WHERE datname=%s',(target,)).fetchone():
            raise CommandError('TARGET_ALREADY_EXISTS')
        connection.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
    try:
        run_tool('pg_restore',['--no-password','--no-owner','--no-privileges','--exit-on-error','--single-transaction','--dbname='+target,str(path)],target)
    except CommandError:
        raise CommandError('RESTORE_FAILED: destino conservado para diagnóstico; no se borró ninguna base.') from None
    enter('Database restored; compare sync state before releasing', target_database=target)
    return info


def restore_media(manifest, target, force=False, confirm=False):
    info = verify(manifest)
    if info['kind'] != 'media':raise CommandError('MEDIA_MANIFEST_REQUIRED')
    destination = private_root(target)
    if destination.exists() and (not force or not confirm):raise CommandError('TARGET_EXISTS: requiere --force --confirm para reemplazar archivos coincidentes.')
    require_space(destination, sum(row['size'] for row in info['entries'].values()))
    archive_path = Path(manifest).resolve().parent.parent/'media'/info['file_name']
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            out = destination / entry.filename
            if not out.resolve().is_relative_to(destination):raise CommandError('UNSAFE_TARGET_PATH')
            if any(p.is_symlink() for p in (out,*out.parents)):raise CommandError('SYMLINK_RESTORE_TARGET')
        destination.mkdir(parents=True,exist_ok=True,mode=0o700)
        for entry in archive.infolist():
            out = destination / entry.filename; out.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd,temporary = tempfile.mkstemp(dir=out.parent,prefix='.restore-')
            try:
                with os.fdopen(fd,'wb') as output, archive.open(entry) as stream:
                    shutil.copyfileobj(stream,output)
                    output.flush();os.fsync(output.fileno())
                os.replace(temporary,out)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return info


def retain(apply=False):
    manifests = []
    for path in (root()/'manifests').glob('*.json'):
        if path.name.endswith('.verified.json'):continue
        try:info = read_manifest(path)
        except CommandError:continue  # Never remove unknown/invalid files.
        manifests.append((path,info))
    keep = set()
    for kind in (*KINDS,'full'):
        rows = sorted((r for r in manifests if r[1]['kind']==kind),key=lambda r:r[1]['created_at'],reverse=True)
        if rows:keep.add(rows[0][0].name)  # Always preserve latest successful backup.
        for setting,fmt in [('BACKUP_KEEP_HOURLY','%Y%m%d%H'),('BACKUP_KEEP_DAILY','%Y%m%d'),('BACKUP_KEEP_WEEKLY','%G%V'),('BACKUP_KEEP_MONTHLY','%Y%m')]:
            buckets = set()
            for path,info in rows:
                bucket = datetime.fromisoformat(info['created_at']).astimezone(timezone.utc).strftime(fmt)
                if bucket not in buckets and len(buckets)<getattr(settings,setting):
                    keep.add(path.name);buckets.add(bucket)
    for path,info in manifests:
        if path.name in keep and info['kind']=='full':keep.update(c['manifest'] for c in info['children'])
    candidates = [(path,info) for path,info in manifests if path.name not in keep]
    # Verify retained recovery points BEFORE deleting anything.
    if apply:
        for path,info in manifests:
            if path.name in keep:verify(path,mark=False)
        for path,info in candidates:
            verify(path,mark=False)
        for path,info in candidates:
            if info['kind'] in KINDS:(root()/KINDS[info['kind']]/info['file_name']).unlink()
            path.unlink();path.with_suffix('.verified.json').unlink(missing_ok=True)
    return [path.name for path,_ in candidates]


def copy_secondary(manifest):
    source = Path(manifest).resolve(); info = verify(source)
    destination = private_root(settings.BACKUP_SECONDARY_ROOT)
    if destination==root() or destination.is_relative_to(root()) or root().is_relative_to(destination):raise CommandError('SECONDARY_MUST_BE_SEPARATE')
    paths = [source]
    if info['kind']=='full':
        for child in info['children']:copy_secondary(source.parent/child['manifest'])
    else:paths.append(source.parent.parent/KINDS[info['kind']]/info['file_name'])
    for path in paths:
        out = destination/path.relative_to(source.parent.parent)
        out.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        require_space(out.parent,path.stat().st_size)
        temporary = out.with_suffix(out.suffix+'.partial')
        shutil.copyfile(path,temporary);temporary.chmod(0o600)
        if digest_file(path)!=digest_file(temporary):raise CommandError('SECONDARY_CHECKSUM_FAILED')
        os.replace(temporary,out)
    verify(destination/'manifests'/source.name)
    return destination/'manifests'/source.name


def offsite(manifest):
    verify(manifest)
    try:
        argv = json.loads(settings.BACKUP_OFFSITE_COMMAND)
        if not isinstance(argv,list) or not argv or any(not isinstance(v,str) for v in argv):raise ValueError
        # Adapter receives the manifest; it must transfer referenced artifacts and verify receipt.
        result = subprocess.run([*argv,str(Path(manifest).resolve())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=settings.BACKUP_TIMEOUT_SECONDS)
        if result.returncode:raise ValueError
    except (ValueError,OSError,subprocess.TimeoutExpired):raise CommandError('OFFSITE_ADAPTER_FAILED') from None
    record('adapter_completed','offsite')


def required_media(connection):
    result=[]
    for table,field,prefix in [('events_event','image','public'),('catalog_product','image','public'),('events_eventpurchasepayment','proof_image','event-proofs'),('reservations_reservationpayment','proof_image','reservation-proofs')]:
        if connection.execute('SELECT to_regclass(%s)',('public.'+table,)).fetchone()[0]:
            query=sql.SQL("SELECT {} FROM {} WHERE {} <> ''").format(sql.Identifier(field),sql.Identifier(table),sql.Identifier(field))
            for (name,) in connection.execute(query):result.append(prefix+'/'+name)
    return sorted(set(result))


# A filesystem lock also works when the database is unavailable. Full backups nest
# component backups under the same process context, without acquiring a second lock.
from contextvars import ContextVar
from functools import wraps
from .locking import file_lock
_backup_locked=ContextVar('backup_locked',default=False)
def exclusive(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        if _backup_locked.get():return function(*args,**kwargs)
        try:
            with file_lock(root()/'logs'/'backup.lock'):
                token=_backup_locked.set(True)
                try:return function(*args,**kwargs)
                finally:_backup_locked.reset(token)
        except BlockingIOError:
            raise CommandError('BACKUP_BUSY: otra tarea de backup/restore está ejecutándose.') from None
        except OSError:
            raise CommandError('BACKUP_FILESYSTEM_UNAVAILABLE: revisa permisos y espacio.') from None
    return wrapped
backup_database=exclusive(backup_database)
backup_media=exclusive(backup_media)
backup_full=exclusive(backup_full)
retain=exclusive(retain)
copy_secondary=exclusive(copy_secondary)
offsite=exclusive(offsite)

restore_database=exclusive(restore_database)
restore_media=exclusive(restore_media)


def health():
    """Small manager alert; cached to avoid scanning files on every navigation."""
    from django.core.cache import cache
    key = 'backup-health:' + hashlib.sha256(str(settings.BACKUP_ROOT).encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None: return cached
    result = {'ok': False, 'message': 'Falta configurar el respaldo automático.'}
    if settings.BACKUP_ROOT:
        latest = None
        for path in (Path(settings.BACKUP_ROOT) / 'manifests').glob('*-full.json'):
            try:
                row = read_manifest(path)
                if latest is None or row['created_at'] > latest['created_at']: latest = row
            except CommandError: continue
        if latest:
            old = (datetime.now(timezone.utc) - datetime.fromisoformat(latest['created_at'])).total_seconds() > settings.BACKUP_MAX_AGE_HOURS * 3600
            result = {'ok': not old, 'message': 'El respaldo está atrasado. Revisa el proceso automático.' if old else 'Respaldo reciente disponible.'}
        else: result['message'] = 'No hay un respaldo completo registrado.'
        try:
            last = json.loads((Path(settings.BACKUP_ROOT) / 'logs' / 'last-full.json').read_text())
            if last.get('status') == 'FAILED': result = {'ok': False, 'message': 'El último respaldo falló. Revisa el almacenamiento y el proceso automático.'}
        except (ValueError, OSError): pass
    cache.set(key, result, 30)
    return result
