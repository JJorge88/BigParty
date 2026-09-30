import logging
import re

class SyncSafeFilter(logging.Filter):
    def filter(self,record):
        event=record.msg if record.msg in ('sync_failed','sync_succeeded','sync_event') else 'sync_event'
        parts=[event]
        for name in ('event_uuid','entity_type','sync_status','sync_code'):
            value=getattr(record,name,'')
            if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value):parts.append(name+'='+value)
        record.msg=' '.join(parts);record.args=();record.exc_info=record.exc_text=record.stack_info=None
        return True
