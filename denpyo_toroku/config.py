import configparser
import argparse
import os
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (project/.env)
# override=False ensures real environment variables take precedence
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env", override=False)


class AppConfig:

    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"))

    # Debug mode
    DENPYO_TOROKU_DEBUG_MODE = os.environ.get("DENPYO_TOROKU_DEBUG_MODE", "")

    # App
    DEFAULT_REQUEST_END_DATE_DELAY = int(config["app"]["default_request_end_date_delay"])
    if not config.has_option("app", "secret_key"):
        config.set("app", "secret_key", "")
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"), "w", encoding="utf-8") as newini:
            config.write(newini)
    FLASK_APP_STRING = str(config["app"]["secret_key"])

    # Service
    DENPYO_TOROKU_BASE = os.environ.get("DENPYO_TOROKU_BASE", "")
    WEBAPP_PORT = os.environ.get("WEBAPP_PORT", "5000")

    # OCI Configuration
    OCI_CONFIG_PATH = os.environ.get("OCI_CONFIG_PATH", "~/.oci/config")
    OCI_CONFIG_PROFILE = os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT")
    OCI_CONFIG_COMPARTMENT = os.environ.get("OCI_CONFIG_COMPARTMENT", "")
    OCI_SERVICE_ENDPOINT = os.environ.get(
        "OCI_SERVICE_ENDPOINT",
        "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com"
    )

    # Base directory (denpyo_toroku/)
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # Classifier
    MODEL_DIR = os.environ.get("MODEL_DIR", os.path.join(_BASE_DIR, "models"))
    _default_model_rel = config.get("classifier", "default_model_path", fallback="models/intent_model_production.pkl")
    MODEL_PATH = os.environ.get("MODEL_PATH", os.path.join(_BASE_DIR, _default_model_rel))
    EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", config.get("classifier", "embedding_model_id", fallback="cohere.embed-v4.0"))
    ENABLE_CACHE = os.environ.get("ENABLE_CACHE", "true").lower() == "true"
    CACHE_SIZE = int(os.environ.get("CACHE_SIZE", config.get("classifier", "cache_size", fallback="10000")))
    BATCH_SIZE = int(os.environ.get("BATCH_SIZE", config.get("classifier", "batch_size", fallback="96")))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # Database
    DB_HOST = os.environ.get("DB_HOST", "")
    DB_PORT = os.environ.get("DB_PORT", "")
    DB_SERVICE = os.environ.get("DB_SERVICE", "")
    DB_USER = os.environ.get("DB_USER", "")
    MAX_POOL_SIZE = int(config["database"]["max_pool_size"])

    # Security
    HOSTNAME = os.environ.get("HOSTNAME", "")
    LOAD_BALANCER_ALIAS = os.environ.get("LOAD_BALANCER_ALIAS", "")

    # Install mode
    SETUP_MODE = os.environ.get("SETUP_MODE", "")
    INSTALL_MODE = os.environ.get("INSTALL_MODE", "")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--get-config", "-g", action="store_true", help="Get the value for the config 'KEY'")

    args = vars(parser.parse_args())

    if not args:
        logging.error("No command passed to the AppConfig CLI. Exiting")
        exit(1)

    if args.get("get_config", None):
        os.environ["FLASK_APP_STRING"] = AppConfig.FLASK_APP_STRING
        os.system("echo $FLASK_APP_STRING")
