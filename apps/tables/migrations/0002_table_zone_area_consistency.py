from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("venues", "0001_initial"),
        ("tables", "0001_initial"),
    ]

    operations = [
        # Django 5.2 no ofrece ForeignKey multicolumna pública. PostgreSQL garantiza
        # la coherencia incluso con update/bulk_create y al trasladar una zona.
        # MATCH SIMPLE permite zone_id=NULL, manteniendo area_id obligatorio.
        migrations.RunSQL(
            sql="""
                ALTER TABLE tables_venuetable
                ADD CONSTRAINT tables_zone_matches_area_fk
                FOREIGN KEY (zone_id, area_id)
                REFERENCES venues_zone (id, area_id)
                MATCH SIMPLE ON UPDATE RESTRICT ON DELETE RESTRICT;
            """,
            reverse_sql="""
                ALTER TABLE tables_venuetable
                DROP CONSTRAINT tables_zone_matches_area_fk;
            """,
        ),
    ]
