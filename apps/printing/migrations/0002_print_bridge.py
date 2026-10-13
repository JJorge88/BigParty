from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('printing', '0001_initial')]
    operations = [
        migrations.CreateModel(
            name='PrintBridge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('token_digest', models.CharField(editable=False, max_length=64, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ('name',)},
        ),
        migrations.AddField(model_name='printer', name='bridge', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='printers', to='printing.printbridge')),
        migrations.AddField(model_name='printer', name='queue_name', field=models.CharField(blank=True, max_length=200)),
        migrations.AddConstraint(model_name='printer', constraint=models.CheckConstraint(
            condition=(models.Q(('bridge__isnull', True), ('queue_name', '')) |
                       (models.Q(('bridge__isnull', False)) & ~models.Q(('queue_name', '')) & models.Q(('host', '')))),
            name='printing_bridge_configuration')),
    ]
