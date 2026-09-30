from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('localnode', '0001_initial')]
    operations = [migrations.RunSQL(
        sql="""
        CREATE FUNCTION localnode_reject_scan_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Local access scans are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER localnode_scan_immutable
        BEFORE UPDATE OR DELETE ON localnode_localaccessscan
        FOR EACH ROW EXECUTE FUNCTION localnode_reject_scan_mutation();
        """,
        reverse_sql="""
        DROP TRIGGER localnode_scan_immutable ON localnode_localaccessscan;
        DROP FUNCTION localnode_reject_scan_mutation();
        """,
    )]
