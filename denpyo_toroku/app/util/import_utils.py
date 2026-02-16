import logging
import traceback
from importlib import import_module
from denpyo_toroku.app.util import import_enabled


class ImportUtil():

    def __init__(self):
        self.modules_enabled = import_enabled.import_enabled

    def import_blueprint(self, module_name, class_name):
        logging.info("モジュールを読み込み: %s", class_name)
        module_ref = None
        blueprint = None
        try:
            module_ref = import_module(module_name)
            try:
                blueprint = getattr(module_ref, class_name)
            except AttributeError as e:
                logging.error(e)
        except ImportError:
            logging.error("モジュールが存在しません: %s", module_name)

        return blueprint

    def register_blueprints(self, app):
        for key in self.modules_enabled["blueprints"]:
            blueprint = None
            blueprint = self.import_blueprint(self.modules_enabled["blueprints"][key], key)
            if blueprint:
                # 参照アーキテクチャ: すべての Blueprint を /studio/ プレフィックス配下に登録
                app.register_blueprint(blueprint, url_prefix="/studio/")

    def import_python_file(self, module_name, class_name):
        logging.info("モジュールを読み込み: %s", class_name)
        module_ref = None
        class_attr = None
        try:
            module_ref = import_module(module_name)
            try:
                class_attr = getattr(module_ref, class_name)
            except AttributeError as e:
                logging.error(e)
                logging.error(traceback.format_exc())
        except ImportError:
            logging.error("モジュールが存在しません: %s", module_name)

        return class_attr

    def register_global_middlewares(self, app):
        for key in self.modules_enabled["global_middlewares"]:
            middleware = None
            middleware = self.import_python_file(self.modules_enabled["global_middlewares"][key], key)
            if middleware:
                middleware(app)

    def register_error_handlers(self, app):
        for key in self.modules_enabled["error_handlers"]:
            error_handler = None
            error_handler = self.import_python_file(self.modules_enabled["error_handlers"][key], key)
            if error_handler:
                error_handler(app)
