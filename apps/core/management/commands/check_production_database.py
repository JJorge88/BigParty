from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help='Revisa privilegios peligrosos y tamaño; solo lectura, sin ALTER ROLE.'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')
            flags=cursor.fetchone()
            cursor.execute("SELECT count(*) FROM pg_roles WHERE rolname<>current_user AND (rolsuper OR rolcreatedb OR rolcreaterole) AND pg_has_role(current_user,oid,'MEMBER')")
            inherited=cursor.fetchone()[0]
            cursor.execute('SELECT pg_database_size(current_database())')
            size=cursor.fetchone()[0]
        self.stdout.write(f'Tamaño PostgreSQL: {size} bytes.')
        if any(flags) or inherited:
            raise CommandError('UNSAFE_APP_ROLE: la aplicación no debe tener ni poder asumir SUPERUSER, CREATEDB o CREATEROLE. El rol de tests/restore es separado.')
        self.stdout.write('Rol de aplicación sin privilegios administrativos detectados.')
