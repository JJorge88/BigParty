import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class SyncIdentity(models.Model):
    entity_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    model_label = models.CharField(max_length=100)
    object_pk = models.CharField(max_length=100)
    origin = models.CharField(max_length=40)
    version = models.PositiveBigIntegerField(default=0)
    payload_digest = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['model_label','object_pk'], name='sync_identity_object_unique')]


class SyncOutboxEvent(models.Model):
    event_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    entity_type = models.CharField(max_length=100)
    entity_uuid = models.UUIDField()
    operation = models.CharField(max_length=30, default='UPSERT')
    entity_version = models.PositiveBigIntegerField()
    payload = models.JSONField()
    schema_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    available_at = models.DateTimeField(default=timezone.now)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=80, blank=True)
    sent_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=12, default='PENDING', db_index=True)
    class Meta:
        ordering = ['pk']
        indexes = [models.Index(fields=['status','attempt_count','id'],name='sync_outbox_retry_idx')]
        constraints = [models.UniqueConstraint(fields=['entity_type','entity_uuid','entity_version'],name='sync_outbox_entity_version_unique')]


class SyncInboxEvent(models.Model):
    event_uuid = models.UUIDField(unique=True)
    source = models.CharField(max_length=40)
    entity_type = models.CharField(max_length=100)
    entity_uuid = models.UUIDField()
    entity_version = models.PositiveBigIntegerField()
    operation = models.CharField(max_length=30)
    schema_version = models.PositiveIntegerField()
    payload = models.JSONField()
    envelope_digest = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=12, default='RECEIVED', db_index=True)
    error = models.CharField(max_length=80, blank=True)
    last_attempt_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=['status','last_attempt_at','id'],name='sync_inbox_retry_idx')]


class SyncCursor(models.Model):
    source = models.CharField(max_length=40, unique=True)
    last_sequence = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class CloudSyncChange(models.Model):
    # Allocated while holding the source gate until COMMIT: no sequence/commit inversion.
    sequence = models.PositiveBigIntegerField(unique=True)
    event_uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    entity_type = models.CharField(max_length=100)
    entity_uuid = models.UUIDField()
    entity_version = models.PositiveBigIntegerField()
    operation = models.CharField(max_length=30, default='UPSERT')
    payload = models.JSONField()
    schema_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['sequence']


class SyncRuntimeState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    feed_sequence = models.PositiveBigIntegerField(default=0)
    last_successful_sync_at = models.DateTimeField(null=True)
    last_attempt_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=80, blank=True)
    last_push_at = models.DateTimeField(null=True)
    last_pull_at = models.DateTimeField(null=True)
    last_seen_at = models.DateTimeField(null=True)
    reported_pending = models.PositiveBigIntegerField(default=0)
    reported_app_version = models.CharField(max_length=100, blank=True)
    reported_app_commit = models.CharField(max_length=100, blank=True)
    sync_requested = models.BooleanField(default=False)
    bootstrap_phase = models.CharField(max_length=30, default='NOT_STARTED')
    bootstrap_progress = models.JSONField(default=dict)
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(pk=1),name='sync_runtime_singleton')]


class SyncConflict(models.Model):
    conflict_uuid = models.UUIDField(default=uuid.uuid4,unique=True)
    event_uuid = models.UUIDField(unique=True)
    entity_type = models.CharField(max_length=100)
    entity_uuid = models.UUIDField()
    conflict_type = models.CharField(max_length=60)
    local_version = models.PositiveBigIntegerField(default=0)
    remote_version = models.PositiveBigIntegerField(default=0)
    payload_summary = models.JSONField(default=dict)
    status = models.CharField(max_length=12,default='OPEN',db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)
    resolution = models.CharField(max_length=250,blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True)


class CloudToLocalCommand(models.Model):
    command_uuid = models.UUIDField(default=uuid.uuid4,unique=True)
    target_node_uuid = models.UUIDField()
    command_type = models.CharField(max_length=40)
    payload = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20,default='PENDING',db_index=True)
    result_code = models.CharField(max_length=80,blank=True)
    applied_at = models.DateTimeField(null=True)


class LocalCommandInbox(models.Model):
    command_uuid = models.UUIDField(unique=True)
    envelope_digest = models.CharField(max_length=64)
    command_type = models.CharField(max_length=40)
    payload = models.JSONField()
    status = models.CharField(max_length=20,default='RECEIVED')
    result_code = models.CharField(max_length=80,blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True)
    acknowledged_at = models.DateTimeField(null=True)


class RemoteActor(models.Model):
    actor_uuid = models.UUIDField(unique=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    origin = models.CharField(max_length=40)


class CloudAccessScan(models.Model):
    scan_uuid = models.UUIDField(unique=True)
    node_uuid = models.UUIDField()
    event_uuid = models.UUIDField(null=True)
    token_digest = models.CharField(max_length=64)
    result = models.CharField(max_length=10)
    scanned_at = models.DateTimeField()
    guard_uuid = models.UUIDField()
    guard_name = models.CharField(max_length=200)
    received_at = models.DateTimeField(auto_now_add=True)


class CloudTicketDigest(models.Model):
    token_digest = models.CharField(max_length=64,unique=True)
    ticket = models.OneToOneField('events.EventTicket',on_delete=models.PROTECT)


class SyncAccessEvent(models.Model):
    snapshot = models.OneToOneField('localnode.LocalEventAccessSnapshot',on_delete=models.PROTECT)
    event_uuid = models.UUIDField()
