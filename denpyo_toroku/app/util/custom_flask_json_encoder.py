from flask.json.provider import DefaultJSONProvider
from enum import Enum

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if hasattr(obj, 'get_ui_json') and callable(obj.get_ui_json):
            return obj.get_ui_json()
        if isinstance(obj, Enum):
            return obj.value
        if _HAS_NUMPY:
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        return super().default(obj)
