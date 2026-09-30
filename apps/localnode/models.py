import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class LocalNodeIdentity(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    node_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120, default='BIG PARTY Principal')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(pk=1), name='localnode_single_identity')]


class LocalEventAccessSnapshot(models.Model):
    source = models.CharField(max_length=100)
    event_public_identifier = models.CharField(max_length=180)
    event_name = models.CharField(max_length=140)
    event_status = models.CharField(max_length=20)
    version = models.CharField(max_length=64)
    checksum = models.CharField(max_length=64)
    generated_at = models.DateTimeField()
    imported_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'event_public_identifier'], name='localnode_source_event_unique')]


class LocalAccessTicket(models.Model):
    snapshot = models.ForeignKey(LocalEventAccessSnapshot, on_delete=models.PROTECT, related_name='tickets')
    token_digest = models.CharField(max_length=64, unique=True)
    ticket_type_name = models.CharField(max_length=100)
    status = models.CharField(max_length=10)
    # Only a local successful scan sets used_at; source USED has no invented timestamp.
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status__in=['VALID','USED','CANCELLED']), name='localnode_ticket_status')]


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Los accesos son registros inmutables.')

    def delete(self):
        raise ValidationError('Los accesos son registros inmutables.')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('Los accesos son registros inmutables.')


class LocalAccessScan(models.Model):
    node = models.ForeignKey(LocalNodeIdentity, on_delete=models.PROTECT)
    event_identifier = models.CharField(max_length=280, blank=True)
    snapshot_version = models.CharField(max_length=64, blank=True)
    token_digest = models.CharField(max_length=64)
    result = models.CharField(max_length=10)
    scanned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    scanned_at = models.DateTimeField(auto_now_add=True, db_index=True)
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        default_permissions = ('view',)
        constraints = [models.CheckConstraint(condition=Q(result__in=['VALID','USED','CANCELLED','INVALID']), name='localnode_scan_result')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Los accesos son registros inmutables.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Los accesos son registros inmutables.')
