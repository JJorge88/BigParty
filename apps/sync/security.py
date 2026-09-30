import hashlib
import hmac
import time
import uuid
from urllib.parse import urlsplit
from django.conf import settings
from .exceptions import SyncError


def signature(method,path,timestamp,body,node):
    if len(settings.SYNC_SHARED_SECRET.encode())<32:raise SyncError('SYNC_NOT_CONFIGURED')
    text='\n'.join([method.upper(),path,str(timestamp),hashlib.sha256(body).hexdigest(),str(node)])
    return hmac.new(settings.SYNC_SHARED_SECRET.encode(),text.encode(),hashlib.sha256).hexdigest()


def authenticate(request,body):
    if not settings.SYNC_ENABLED or settings.DEPLOYMENT_MODE!='cloud':raise SyncError('SYNC_DISABLED')
    if not request.is_secure() and not (settings.SYNC_ALLOW_HTTP_DEVELOPMENT and request.META.get('REMOTE_ADDR') in ('127.0.0.1','::1')):raise SyncError('HTTPS_REQUIRED')
    node=request.headers.get('X-BP-Node','');stamp=request.headers.get('X-BP-Timestamp','')
    provided=request.headers.get('X-BP-Signature','')
    try:
        if str(uuid.UUID(node))!=str(uuid.UUID(settings.SYNC_NODE_UUID)):raise ValueError
        if abs(time.time()-int(stamp))>300:raise ValueError
    except (ValueError,TypeError,AttributeError):raise SyncError('AUTHENTICATION_FAILED')
    expected=signature(request.method,request.get_full_path(),stamp,body,node)
    if not provided or not hmac.compare_digest(expected,provided):raise SyncError('AUTHENTICATION_FAILED')
    return node


def response_signature(request_signature,body):
    return hmac.new(settings.SYNC_SHARED_SECRET.encode(),(request_signature+'\n'+hashlib.sha256(body).hexdigest()).encode(),hashlib.sha256).hexdigest()


def compatible(data):
    if not isinstance(data,dict) or type(data.get('protocol')) is not int or data.get('protocol')!=settings.SYNC_PROTOCOL_VERSION or data.get('app_version') not in settings.SYNC_COMPATIBLE_APP_VERSIONS:raise SyncError('INCOMPATIBLE_PROTOCOL_OR_APP')


def cloud_url():
    parsed=urlsplit(settings.SYNC_CLOUD_URL)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise SyncError('INVALID_CLOUD_URL')
    if parsed.scheme!='https' and not (parsed.scheme=='http' and settings.SYNC_ALLOW_HTTP_DEVELOPMENT and parsed.hostname in ('localhost','127.0.0.1','::1')):raise SyncError('HTTPS_REQUIRED')
    return parsed
