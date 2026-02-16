# Monkey patch must happen BEFORE any other imports to avoid MonkeyPatchWarning
# This prevents ssl-related warnings when using OCI SDK with gevent
from gevent import monkey
monkey.patch_all()

import os
import sys

denpyo_toroku_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, denpyo_toroku_base)
from denpyo_toroku.denpyo_toroku import app

if __name__ == "__main__":
    app.run()
