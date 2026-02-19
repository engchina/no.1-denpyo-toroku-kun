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
    OCI_REGION = os.environ.get("OCI_REGION", "ap-osaka-1")
    OCI_SERVICE_ENDPOINT = os.environ.get(
        "OCI_SERVICE_ENDPOINT",
        "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com"
    )

    # OCI Object Storage
    OCI_BUCKET = os.environ.get("OCI_BUCKET", "")
    OCI_NAMESPACE = os.environ.get("OCI_NAMESPACE", "")
    OCI_OBJECT_PREFIX = os.environ.get("OCI_OBJECT_PREFIX", "denpyo-raw")
    OCI_SLIPS_RAW_PREFIX = os.environ.get("OCI_SLIPS_RAW_PREFIX", "denpyo-raw")
    OCI_SLIPS_CATEGORY_PREFIX = os.environ.get("OCI_SLIPS_CATEGORY_PREFIX", "denpyo-category")

    # AI Model Configuration
    VISION_MODEL_NAME = os.environ.get(
        "VISION_MODEL_NAME",
        config.get("ai", "vision_model_name", fallback="google.gemini-2.5-flash")
    )
    LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "google.gemini-2.5-flash")
    EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")

    # Storage limits
    UPLOAD_MAX_SIZE_MB = int(os.environ.get(
        "UPLOAD_MAX_SIZE_MB",
        config.get("storage", "upload_max_size_mb", fallback="20")
    ))
    ALLOWED_EXTENSIONS = os.environ.get(
        "ALLOWED_EXTENSIONS",
        config.get("storage", "allowed_extensions", fallback="pdf,jpeg,jpg,png")
    ).split(",")

    # Base directory (denpyo_toroku/)
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # Database
    ORACLE_CLIENT_LIB_DIR = os.environ.get("ORACLE_CLIENT_LIB_DIR", "")
    ORACLE_26AI_CONNECTION_STRING = os.environ.get("ORACLE_26AI_CONNECTION_STRING", "")
    ADB_OCID = os.environ.get("ADB_OCID", "")
    MAX_POOL_SIZE = int(config["database"]["max_pool_size"])

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

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
