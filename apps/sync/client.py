"""Only this module performs cloud HTTP; never called by a POS service/view."""
import hmac
import http.client
import json
import time
from django.conf import settings
from .exceptions import SyncError
from .security import cloud_url,signature,response_signature
from .serializers import canonical
from .api import no_duplicates


class SyncClient:
    def __init__(self,node_uuid):self.node=str(node_uuid)
    def request(self,endpoint,data=None):
        url=cloud_url();path='/api/sync/v1/'+endpoint+'/'
        method='GET' if data is None else 'POST'
        payload=b'' if data is None else canonical({'protocol':settings.SYNC_PROTOCOL_VERSION,'app_version':settings.APP_VERSION,**data})
        if len(payload)>settings.SYNC_MAX_BODY_BYTES:raise SyncError('PAYLOAD_TOO_LARGE')
        timestamp=str(int(time.time()));signed=signature(method,path,timestamp,payload,self.node)
        cls=http.client.HTTPSConnection if url.scheme=='https' else http.client.HTTPConnection
        connection=cls(url.hostname,url.port,timeout=settings.SYNC_CONNECT_TIMEOUT)
        try:
            connection.connect();connection.sock.settimeout(settings.SYNC_READ_TIMEOUT)
            connection.request(method,path,body=payload,headers={'Content-Type':'application/json','X-BP-Node':self.node,'X-BP-Timestamp':timestamp,'X-BP-Signature':signed})
            response=connection.getresponse();raw=response.read(settings.SYNC_MAX_BODY_BYTES+1)
            if len(raw)>settings.SYNC_MAX_BODY_BYTES:raise SyncError('RESPONSE_TOO_LARGE')
            if not hmac.compare_digest(response.getheader('X-BP-Response-Signature',''),response_signature(signed,raw)):raise SyncError('INVALID_RESPONSE_SIGNATURE')
            data=json.loads(raw,object_pairs_hook=no_duplicates)
            if not isinstance(data,dict):raise SyncError('INVALID_RESPONSE')
            if response.status!=200:
                code=data.get('code')
                raise SyncError(code if code in ('INCOMPATIBLE_PROTOCOL_OR_APP','AUTHENTICATION_FAILED','SYNC_DISABLED','EVENT_TOO_LARGE','HTTPS_REQUIRED','INVALID_BODY','SYNC_UNAVAILABLE','INVALID_BATCH','EVENT_UUID_REUSED') else 'REMOTE_ERROR')
            return data
        except SyncError:raise
        except (OSError,http.client.HTTPException):raise SyncError('NETWORK_UNAVAILABLE')
        except (ValueError,TypeError,UnicodeError):raise SyncError('INVALID_RESPONSE')
        finally:connection.close()
