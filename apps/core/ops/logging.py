import logging
import re

class SafeSupportFilter(logging.Filter):
    def filter(self,record):
        event=record.msg if record.msg in ('server_error','pdf_failed','maintenance_failed') else 'server_event'
        reference=getattr(record,'support_reference','')
        code=getattr(record,'status_code',None)
        record.msg=event+((' reference='+reference) if isinstance(reference,str) and re.fullmatch('[a-f0-9]{12}',reference) else '')+((' status='+str(code)) if type(code) is int else '')
        record.args=();record.exc_info=record.exc_text=record.stack_info=None
        return True
