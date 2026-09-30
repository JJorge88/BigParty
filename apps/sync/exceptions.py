class SyncError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class MissingDependency(SyncError):
    def __init__(self): super().__init__('MISSING_DEPENDENCY')
