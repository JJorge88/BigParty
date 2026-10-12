"""Exercise the Windows-to-Ubuntu data migration on the historical schema."""
from datetime import timedelta
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class InaugurationMigrationTests(TransactionTestCase):
    def test_existing_names_and_slug_collisions_survive_upgrade(self):
        executor = MigrationExecutor(connection)
        previous = [('events', '0001_initial')]
        target = [('events', '0002_correct_inauguration_spelling')]
        executor.migrate(previous)
        try:
            old_apps = executor.loader.project_state(previous).apps
            User = old_apps.get_model('accounts', 'User')
            Event = old_apps.get_model('events', 'Event')
            user = User.objects.create(username='migration-only')
            start = timezone.now()
            defaults = dict(created_by_id=user.pk, starts_at=start,
                            ends_at=start + timedelta(hours=2))
            normal = Event.objects.create(name='Ignaguracion viernes',
                                          slug='ignaguracion-viernes', **defaults)
            collision = Event.objects.create(name='ignaguracion sábado',
                                             slug='ignaguracion-sabado', **defaults)
            existing = Event.objects.create(name='Evento existente',
                                            slug='inauguracion-sabado', **defaults)
            executor = MigrationExecutor(connection)
            executor.migrate(target)
            Event = executor.loader.project_state(target).apps.get_model('events', 'Event')
            normal = Event.objects.get(pk=normal.pk)
            collision = Event.objects.get(pk=collision.pk)
            self.assertEqual((normal.name, normal.slug),
                             ('Inauguración viernes', 'inauguracion-viernes'))
            self.assertEqual((collision.name, collision.slug),
                             ('inauguración sábado', 'ignaguracion-sabado'))
            self.assertEqual(Event.objects.get(pk=existing.pk).name, 'Evento existente')
            self.assertEqual(Event.objects.count(), 3)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
