"""Allowlisted event logging: no URLs, POST bodies, exception values or credentials."""
import logging

class SafeEventFilter(logging.Filter):
    EVENTS = {'node_starting','node_ready','database_unavailable','runtime_stopped','print_job_printed','print_job_failed'}

    def filter(self, record):
        event = record.msg if isinstance(record.msg, str) and record.msg in self.EVENTS else 'runtime_event'
        status = getattr(record, 'status_code', None)
        record.msg = event + (f' status={status}' if type(status) is int else '')
        record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True
