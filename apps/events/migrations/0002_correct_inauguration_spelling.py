from django.db import migrations


def correct_spelling(apps, schema_editor):
    Event = apps.get_model('events', 'Event')
    for event in Event.objects.filter(name__icontains='ignaguracion'):
        corrected_slug = event.slug.replace('ignaguracion', 'inauguracion')
        if corrected_slug != event.slug and Event.objects.filter(slug=corrected_slug).exclude(pk=event.pk).exists():
            corrected_slug = event.slug
        event.name = event.name.replace('ignaguracion', 'inauguración').replace('Ignaguracion', 'Inauguración')
        event.slug = corrected_slug
        event.save(update_fields=['name', 'slug'])


class Migration(migrations.Migration):
    dependencies = [('events', '0001_initial')]
    operations = [migrations.RunPython(correct_spelling, migrations.RunPython.noop)]
