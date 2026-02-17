import logging
import os
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

# Set DENPYO_TOROKU_BASE so logger and other components can find the right directory
_denpyo_toroku_dir = os.path.dirname(os.path.abspath(__file__))
if not os.environ.get('DENPYO_TOROKU_BASE'):
    os.environ['DENPYO_TOROKU_BASE'] = _denpyo_toroku_dir

from denpyo_toroku.app.util.logger import LoggerUtil
from denpyo_toroku.config import AppConfig
from denpyo_toroku.app.util.import_utils import ImportUtil
from denpyo_toroku.app.util.custom_flask_json_encoder import CustomJSONProvider

app = Flask(__name__, template_folder="./")
app.secret_key = AppConfig.FLASK_APP_STRING or "denpyo-toroku-default-secret-key"
app.session_interface = SecureCookieSessionInterface()
app.config.from_object("denpyo_toroku.auth_config")

# Debug mode
app.debug = AppConfig.DENPYO_TOROKU_DEBUG_MODE.lower() == "true" if AppConfig.DENPYO_TOROKU_DEBUG_MODE else False

# Custom JSON provider for numpy types
app.json = CustomJSONProvider(app)

# Setup logger
LoggerUtil.setup_logger("denpyo_toroku")

# Register blueprints, middlewares, error handlers
denpyo_toroku_import = ImportUtil()
denpyo_toroku_import.register_blueprints(app)
denpyo_toroku_import.register_global_middlewares(app)
denpyo_toroku_import.register_error_handlers(app)

# Initialize services (lazy - will be created on first use)
app.services = {}


webapp_port = os.environ.get("WEBAPP_PORT", None)

if __name__ == "__main__":
    if webapp_port:
        app.run(host="0.0.0.0", port=int(webapp_port))
    else:
        app.run(host="0.0.0.0", port=5000)
