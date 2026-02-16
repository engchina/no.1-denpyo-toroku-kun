import os
import logging
import logging.config


class LoggerUtil:
    # 既定は denpyo_toroku ディレクトリ
    _default_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    denpyo_toroku_base = os.environ.get('DENPYO_TOROKU_BASE', '') or _default_base

    @classmethod
    def configure_logging(cls, log_file_name='denpyo_toroku'):
        default_logging = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'default': {
                    'format': '[%(asctime)s.%(msecs)03d] [Pid: %(process)d] [Tid: %(thread)d] [%(levelname)7s] File %(filename)s, line %(lineno)d - %(message)s',
                }
            },
            'handlers': {
                'regular': {
                    'level': 'INFO',
                    'formatter': 'default',
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(cls.denpyo_toroku_base, 'log', log_file_name + '.log'),
                    'maxBytes': 20 * 1024 * 1024,
                    'backupCount': 5
                },
                'error': {
                    'level': 'ERROR',
                    'formatter': 'default',
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(cls.denpyo_toroku_base, 'log', log_file_name + '.err'),
                    'maxBytes': 20 * 1024 * 1024,
                    'backupCount': 5
                }
            },
            'loggers': {
                'root': {
                    'handlers': ['regular', 'error'],
                    'level': 'INFO',
                }
            }
        }
        logging.config.dictConfig(default_logging)

    @classmethod
    def setup_logger(cls, log_file_name='denpyo_toroku'):
        if not cls.denpyo_toroku_base:
            cls.denpyo_toroku_base = os.environ.get('DENPYO_TOROKU_BASE', '') or cls._default_base

        log_dir = os.path.join(cls.denpyo_toroku_base, 'log')
        os.makedirs(log_dir, exist_ok=True)

        logger = logging.getLogger()
        log_file_path = os.path.join(log_dir, log_file_name + '.log')

        log_file_exists = any(
            isinstance(handler, logging.FileHandler) and handler.baseFilename == log_file_path
            for handler in logger.handlers
        )

        if not log_file_exists:
            cls.configure_logging(log_file_name)
        else:
            logger.info('ロガーはすでに設定済みです（%s）。初期化をスキップします。', log_file_name)
