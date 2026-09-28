from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial"), ("inventory", "0002_order_consumption")]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE orders_tableorder ADD CONSTRAINT orders_primary_table_link_fk
                FOREIGN KEY (id, primary_table_id)
                REFERENCES orders_ordertablelink (order_id, table_id)
                DEFERRABLE INITIALLY DEFERRED;
                ALTER TABLE orders_orderline ADD CONSTRAINT orders_line_subaccount_order_fk
                FOREIGN KEY (subaccount_id, order_id)
                REFERENCES orders_subaccount (id, order_id)
                DEFERRABLE INITIALLY DEFERRED;
            """,
            reverse_sql="""
                ALTER TABLE orders_orderline DROP CONSTRAINT orders_line_subaccount_order_fk;
                ALTER TABLE orders_tableorder DROP CONSTRAINT orders_primary_table_link_fk;
            """,
        ),
    ]
