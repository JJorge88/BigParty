from django.db import migrations


def defaults(apps, schema_editor):
    model = apps.get_model('core', 'PaymentMethodSettings')
    for index, code in enumerate(('CASH', 'CARD', 'TRANSFER', 'DEPOSIT')):
        model.objects.get_or_create(method=code, defaults={'enabled': True, 'display_order': index})


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]
    operations = [migrations.RunPython(defaults, migrations.RunPython.noop)]
