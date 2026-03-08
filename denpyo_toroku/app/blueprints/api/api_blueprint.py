import configparser
import logging
import time
import json
import os
import shutil
import tempfile
import zipfile
import datetime as dt
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from flask import Blueprint, request, jsonify, g, current_app, make_response, session, redirect
from dotenv import load_dotenv
try:
    from prometheus_client import Counter, Histogram, generate_latest
    from prometheus_client import CONTENT_TYPE_LATEST
except Exception:  # pragma: no cover - optional dependency
    Counter = None
    Histogram = None
    generate_latest = None
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

from denpyo_toroku.app.util.response import Response
from denpyo_toroku.config import AppConfig
from denpyo_toroku.app.services.database_service import DatabaseService

api_blueprint = Blueprint("api_blueprint", __name__)

if Counter is not None and Histogram is not None:
    REQUEST_COUNT = Counter(
        "denpyo_toroku_http_requests_total",
        "Total HTTP requests handled by Denpyo Toroku API",
        ["method", "endpoint", "status_code"],
    )
    REQUEST_LATENCY_SECONDS = Histogram(
        "denpyo_toroku_http_request_duration_seconds",
        "HTTP request latency in seconds for Denpyo Toroku API",
        ["method", "endpoint"],
    )
else:
    REQUEST_COUNT = None
    REQUEST_LATENCY_SECONDS = None

_default_auth_username = os.environ.get("DENPYO_TOROKU_LOGIN_USERNAME", "admin")
_default_auth_password = os.environ.get("DENPYO_TOROKU_LOGIN_PASSWORD", "admin")
_OCI_MASKED_KEY = "[CONFIGURED]"
_DB_MASKED_SECRET = "[CONFIGURED]"
_DB_CONN_ENV_KEY = "ORACLE_26AI_CONNECTION_STRING"
_DB_ADB_OCID_ENV_KEY = "ADB_OCID"
_DB_REQUIRED_WALLET_FILES = ("cwallet.sso", "ewallet.pem", "sqlnet.ora", "tnsnames.ora")
_DB_UNNECESSARY_WALLET_FILES = ("README", "keystore.jks", "truststore.jks", "ojdbc.properties", "ewallet.p12")
_DB_TEST_TIMEOUT_SECONDS = 15  # DB接続テストの最大待機時間（秒）
_DB_TEST_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db_test_")
_ANALYSIS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis_job_")
_OCI_KEY_PATTERN = re.compile(
    r"-----BEGIN[\s\S]*?PRIVATE KEY-----[\s\S]*?-----END[\s\S]*?PRIVATE KEY-----"
)
_DEFAULT_OCI_REGION = "ap-osaka-1"
_DEFAULT_SELECT_AI_REGION = "us-chicago-1"
_DEFAULT_SELECT_AI_MODEL_ID = "xai.grok-code-fast-1"
_DEFAULT_SELECT_AI_MAX_TOKENS = 32768
_ANALYSIS_STALL_DETAIL = "ANALYSIS_TIMEOUT"
_DEFAULT_ANALYSIS_STALL_MINUTES = 30


def _to_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _is_session_authenticated() -> bool:
    user = session.get("user", None)
    token = session.get("token", None)
    token_expiry_ts = session.get("token_expiry_ts", None)
    if not user or not token or not token_expiry_ts:
        return False
    return dt.datetime.now().timestamp() < float(token_expiry_ts)


def _normalize_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _analysis_stall_timeout_seconds() -> int:
    raw_value = _normalize_text(os.environ.get("DENPYO_ANALYSIS_STALL_MINUTES"), "")
    try:
        minutes = int(raw_value) if raw_value else _DEFAULT_ANALYSIS_STALL_MINUTES
    except ValueError:
        minutes = _DEFAULT_ANALYSIS_STALL_MINUTES
    return max(60, minutes * 60)


def _parse_timestamp(value: Any) -> Optional[dt.datetime]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value

    text = _normalize_text(value, "")
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _is_analysis_stalled(record: Optional[Dict[str, Any]]) -> bool:
    if not record:
        return False
    if _normalize_text(record.get("status"), "").upper() != "ANALYZING":
        return False
    if bool(record.get("has_analysis_result")):
        return False

    tracked_at = _parse_timestamp(
        record.get("updated_at")
        or record.get("created_at")
        or record.get("uploaded_at")
    )
    if tracked_at is None:
        return False

    now = dt.datetime.now(tracked_at.tzinfo) if tracked_at.tzinfo else dt.datetime.now()
    return (now - tracked_at).total_seconds() >= _analysis_stall_timeout_seconds()


def _decorate_analysis_status(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not record:
        return record

    status = _normalize_text(record.get("status"), "").upper()
    is_stalled = _is_analysis_stalled(record)
    record["status"] = status or record.get("status", "")
    record["status_detail"] = _ANALYSIS_STALL_DETAIL if is_stalled else ""
    record["is_analysis_stalled"] = is_stalled
    record["can_retry_analysis"] = is_stalled or status in ("UPLOADED", "ERROR")
    return record


def _expand_path(path_value: str, default: str) -> str:
    raw = _normalize_text(path_value, default)
    if not raw:
        raw = default
    return os.path.abspath(os.path.expanduser(raw))


def _extract_region_from_endpoint(service_endpoint: str) -> str:
    endpoint = _normalize_text(service_endpoint)
    if not endpoint:
        return _DEFAULT_OCI_REGION
    match = re.search(
        r"https?://inference\.generativeai\.([a-z0-9-]+)\.oci\.oraclecloud\.com",
        endpoint,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return _DEFAULT_OCI_REGION


def _project_root_path() -> Path:
    # denpyo_toroku/app/blueprints/api/api_blueprint.py -> リポジトリルート
    return Path(__file__).resolve().parents[4]


def _env_file_path() -> Path:
    return _project_root_path() / ".env"


def _runtime_oci_defaults() -> Dict[str, str]:
    config_path = _normalize_text(
        os.environ.get("OCI_CONFIG_PATH"),
        _normalize_text(getattr(AppConfig, "OCI_CONFIG_PATH", ""), "~/.oci/config"),
    )
    profile = _normalize_text(
        os.environ.get("OCI_CONFIG_PROFILE"),
        _normalize_text(getattr(AppConfig, "OCI_CONFIG_PROFILE", ""), "DEFAULT"),
    ) or "DEFAULT"
    service_endpoint = _normalize_text(
        os.environ.get("OCI_SERVICE_ENDPOINT"),
        _normalize_text(
            getattr(AppConfig, "OCI_SERVICE_ENDPOINT", ""),
            f"https://inference.generativeai.{_runtime_oci_region_default()}.oci.oraclecloud.com",
        ),
    )
    return {
        "config_path": config_path or "~/.oci/config",
        "profile": profile,
        "region": _runtime_oci_region_default(),
        "compartment_id": _normalize_text(
            os.environ.get("OCI_CONFIG_COMPARTMENT"),
            _normalize_text(getattr(AppConfig, "OCI_CONFIG_COMPARTMENT", "")),
        ),
        "service_endpoint": service_endpoint,
        "llm_model_id": _normalize_text(
            os.environ.get("LLM_MODEL_ID"),
            _normalize_text(getattr(AppConfig, "LLM_MODEL_ID", ""), "xai.grok-code-fast-1"),
        ),
        "vlm_model_id": _normalize_text(
            os.environ.get("VLM_MODEL_ID"),
            _normalize_text(getattr(AppConfig, "VLM_MODEL_ID", ""), "google.gemini-2.5-flash"),
        ),
        "embedding_model_id": _normalize_text(
            os.environ.get("EMBEDDING_MODEL_ID"),
            _normalize_text(getattr(AppConfig, "EMBEDDING_MODEL_ID", ""), "cohere.embed-v4.0"),
        ),
        "select_ai_enabled": _to_bool(
            os.environ.get("SELECT_AI_ENABLED", getattr(AppConfig, "SELECT_AI_ENABLED", True)),
            default=True,
        ),
        "select_ai_region": _normalize_text(
            os.environ.get("SELECT_AI_REGION"),
            _normalize_text(getattr(AppConfig, "SELECT_AI_REGION", ""), _DEFAULT_SELECT_AI_REGION),
        ) or _DEFAULT_SELECT_AI_REGION,
        "select_ai_model_id": _normalize_text(
            os.environ.get("SELECT_AI_MODEL_ID"),
            _normalize_text(getattr(AppConfig, "SELECT_AI_MODEL_ID", ""), _DEFAULT_SELECT_AI_MODEL_ID),
        ) or _DEFAULT_SELECT_AI_MODEL_ID,
        "select_ai_embedding_model_id": _normalize_text(
            os.environ.get("SELECT_AI_EMBEDDING_MODEL_ID"),
            _normalize_text(getattr(AppConfig, "SELECT_AI_EMBEDDING_MODEL_ID", ""), _normalize_text(getattr(AppConfig, "EMBEDDING_MODEL_ID", ""), "cohere.embed-v4.0")),
        ),
        "select_ai_endpoint_id": _normalize_text(
            os.environ.get("SELECT_AI_ENDPOINT_ID"),
            _normalize_text(getattr(AppConfig, "SELECT_AI_ENDPOINT_ID", "")),
        ),
        "select_ai_max_tokens": int(
            os.environ.get("SELECT_AI_MAX_TOKENS", getattr(AppConfig, "SELECT_AI_MAX_TOKENS", _DEFAULT_SELECT_AI_MAX_TOKENS))
        ),
        "select_ai_enforce_object_list": _to_bool(
            os.environ.get("SELECT_AI_ENFORCE_OBJECT_LIST", getattr(AppConfig, "SELECT_AI_ENFORCE_OBJECT_LIST", True)),
            default=True,
        ),
        "select_ai_oci_apiformat": _normalize_text(
            os.environ.get("SELECT_AI_OCI_API_FORMAT"),
            _normalize_text(getattr(AppConfig, "SELECT_AI_OCI_API_FORMAT", ""), "GENERIC"),
        ) or "GENERIC",
        "select_ai_use_annotations": _to_bool(
            os.environ.get("SELECT_AI_USE_ANNOTATIONS", getattr(AppConfig, "SELECT_AI_USE_ANNOTATIONS", True)),
            default=True,
        ),
        "select_ai_use_comments": _to_bool(
            os.environ.get("SELECT_AI_USE_COMMENTS", getattr(AppConfig, "SELECT_AI_USE_COMMENTS", True)),
            default=True,
        ),
        "select_ai_use_constraints": _to_bool(
            os.environ.get("SELECT_AI_USE_CONSTRAINTS", getattr(AppConfig, "SELECT_AI_USE_CONSTRAINTS", True)),
            default=True,
        ),
        "llm_max_tokens": int(
            os.environ.get("LLM_MAX_TOKENS", getattr(AppConfig, "LLM_MAX_TOKENS", 65536))
        ),
        "llm_temperature": float(
            os.environ.get("LLM_TEMPERATURE", getattr(AppConfig, "LLM_TEMPERATURE", 0.0))
        ),
        "namespace": _normalize_text(
            os.environ.get("OCI_NAMESPACE"),
            _normalize_text(getattr(AppConfig, "OCI_NAMESPACE", "")),
        ),
        "bucket": _normalize_text(
            os.environ.get("OCI_BUCKET"),
            _normalize_text(getattr(AppConfig, "OCI_BUCKET", "")),
        ),
    }


def _runtime_oci_region_default() -> str:
    """Object Storage/ADB 画面で表示・利用する OCI region の既定値。"""
    return _normalize_text(
        os.environ.get("OCI_REGION"),
        _normalize_text(getattr(AppConfig, "OCI_REGION", ""), "ap-osaka-1"),
    )


def _fetch_object_storage_namespace_via_sdk(region: str = "") -> str:
    defaults = _runtime_oci_defaults()
    config_path = _expand_path(defaults.get("config_path", "~/.oci/config"), "~/.oci/config")
    profile = _normalize_text(defaults.get("profile", "DEFAULT"), "DEFAULT") or "DEFAULT"

    if not os.path.exists(config_path):
        return ""

    try:
        import oci  # local import to avoid import-time dependency in non-OCI flows

        config = oci.config.from_file(config_path, profile)
        if _normalize_text(region):
            config["region"] = _normalize_text(region)

        object_storage_client = oci.object_storage.ObjectStorageClient(config)
        response = object_storage_client.get_namespace()
        namespace = _normalize_text(getattr(response, "data", ""))
        return namespace
    except Exception as e:
        logging.warning("Object Storage namespace の SDK 取得に失敗: %s", e, exc_info=True)
        return ""


def _get_config_value(parser: configparser.ConfigParser, profile: str, key: str) -> str:
    if profile.upper() == "DEFAULT":
        return _normalize_text(parser.defaults().get(key))
    if parser.has_section(profile):
        return _normalize_text(parser.get(profile, key, fallback=""))
    fallback = _normalize_text(parser.defaults().get(key))
    if fallback:
        return fallback
    for section_name in parser.sections():
        value = _normalize_text(parser.get(section_name, key, fallback=""))
        if value:
            return value
    return ""


def _resolve_key_file_path(
    config_path: str,
    parser: configparser.ConfigParser,
    profile: str,
    explicit_key_file: str = "",
) -> str:
    config_dir = os.path.dirname(config_path) or "."
    configured_key = _normalize_text(explicit_key_file) or _get_config_value(parser, profile, "key_file")
    key_file = os.path.expanduser(configured_key) if configured_key else os.path.join(config_dir, "oci_api_key.pem")
    if not os.path.isabs(key_file):
        key_file = os.path.join(config_dir, key_file)
    return _expand_path(key_file, os.path.join(config_dir, "oci_api_key.pem"))


def _load_oci_settings_snapshot() -> Dict[str, Any]:
    defaults = _runtime_oci_defaults()
    config_path = _expand_path(defaults["config_path"], "~/.oci/config")
    profile = defaults["profile"] or "DEFAULT"
    parser = configparser.ConfigParser()
    if os.path.exists(config_path):
        parser.read(config_path)

    user_ocid = _get_config_value(parser, profile, "user")
    tenancy_ocid = _get_config_value(parser, profile, "tenancy")
    fingerprint = _get_config_value(parser, profile, "fingerprint")
    region = (
        _normalize_text(os.environ.get("OCI_REGION"))
        or _get_config_value(parser, profile, "region")
        or _extract_region_from_endpoint(defaults["service_endpoint"])
        or defaults.get("region", "")
    )

    key_file = _resolve_key_file_path(config_path, parser, profile)
    key_content = ""
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as key_reader:
                key_content = key_reader.read()
        except Exception:  # pragma: no cover - best effort read
            key_content = ""

    has_credentials = bool(
        user_ocid and tenancy_ocid and fingerprint and _normalize_text(key_content)
    )

    return {
        "settings": {
            "user_ocid": user_ocid,
            "tenancy_ocid": tenancy_ocid,
            "fingerprint": fingerprint,
            "region": region or _DEFAULT_OCI_REGION,
            "key_content": _OCI_MASKED_KEY if has_credentials else "",
            "config_path": config_path,
            "profile": profile,
            "key_file": key_file,
            "compartment_id": defaults["compartment_id"],
            "service_endpoint": defaults["service_endpoint"],
            "llm_model_id": defaults["llm_model_id"],
            "vlm_model_id": defaults["vlm_model_id"],
            "embedding_model_id": defaults["embedding_model_id"],
            "select_ai_enabled": defaults["select_ai_enabled"],
            "select_ai_region": defaults["select_ai_region"],
            "select_ai_model_id": defaults["select_ai_model_id"],
            "select_ai_embedding_model_id": defaults["select_ai_embedding_model_id"],
            "select_ai_endpoint_id": defaults["select_ai_endpoint_id"],
            "select_ai_max_tokens": defaults["select_ai_max_tokens"],
            "select_ai_enforce_object_list": defaults["select_ai_enforce_object_list"],
            "select_ai_oci_apiformat": defaults["select_ai_oci_apiformat"],
            "select_ai_use_annotations": defaults["select_ai_use_annotations"],
            "select_ai_use_comments": defaults["select_ai_use_comments"],
            "select_ai_use_constraints": defaults["select_ai_use_constraints"],
            "llm_max_tokens": defaults["llm_max_tokens"],
            "llm_temperature": defaults["llm_temperature"],
            "namespace": defaults["namespace"],
            "bucket": defaults["bucket"],
        },
        "has_credentials": has_credentials,
        "is_configured": has_credentials,
        "status": "configured" if has_credentials else "not_configured",
    }


def _validate_private_key_content(key_content: str) -> bool:
    content = _normalize_text(key_content)
    if not content:
        return False
    return bool(_OCI_KEY_PATTERN.search(content))


def _upsert_env_values(env_path: Path, updates: Dict[str, str]) -> None:
    lines: List[str] = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as env_reader:
            lines = env_reader.read().splitlines()
    else:
        env_path.parent.mkdir(parents=True, exist_ok=True)

    replaced_keys = set()
    updated_lines: List[str] = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            updated_lines.append(line)
            continue

        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            updated_lines.append(f"{key}={updates[key]}")
            replaced_keys.add(key)
        else:
            updated_lines.append(line)

    for key, value in updates.items():
        if key not in replaced_keys:
            updated_lines.append(f"{key}={value}")

    with open(env_path, "w", encoding="utf-8") as env_writer:
        content = "\n".join(updated_lines).rstrip()
        env_writer.write(content + "\n" if content else "")


def _apply_runtime_oci_values(settings: Dict[str, str]) -> None:
    os.environ["OCI_REGION"] = settings["region"]
    os.environ["OCI_CONFIG_PATH"] = settings["config_path"]
    os.environ["OCI_CONFIG_PROFILE"] = settings["profile"]
    os.environ["OCI_CONFIG_COMPARTMENT"] = settings["compartment_id"]
    os.environ["OCI_SERVICE_ENDPOINT"] = settings["service_endpoint"]
    os.environ["LLM_MODEL_ID"] = settings["llm_model_id"]
    os.environ["VLM_MODEL_ID"] = settings["vlm_model_id"]
    os.environ["EMBEDDING_MODEL_ID"] = settings["embedding_model_id"]
    os.environ["SELECT_AI_ENABLED"] = "true" if settings["select_ai_enabled"] else "false"
    os.environ["SELECT_AI_REGION"] = settings["select_ai_region"]
    os.environ["SELECT_AI_MODEL_ID"] = settings["select_ai_model_id"]
    os.environ["SELECT_AI_EMBEDDING_MODEL_ID"] = settings["select_ai_embedding_model_id"]
    os.environ["SELECT_AI_ENDPOINT_ID"] = settings["select_ai_endpoint_id"]
    os.environ["SELECT_AI_MAX_TOKENS"] = str(settings["select_ai_max_tokens"])
    os.environ["SELECT_AI_ENFORCE_OBJECT_LIST"] = "true" if settings["select_ai_enforce_object_list"] else "false"
    os.environ["SELECT_AI_OCI_API_FORMAT"] = settings["select_ai_oci_apiformat"]
    os.environ["SELECT_AI_USE_ANNOTATIONS"] = "true" if settings["select_ai_use_annotations"] else "false"
    os.environ["SELECT_AI_USE_COMMENTS"] = "true" if settings["select_ai_use_comments"] else "false"
    os.environ["SELECT_AI_USE_CONSTRAINTS"] = "true" if settings["select_ai_use_constraints"] else "false"
    os.environ["LLM_MAX_TOKENS"] = str(settings["llm_max_tokens"])
    os.environ["LLM_TEMPERATURE"] = str(settings["llm_temperature"])
    os.environ["OCI_NAMESPACE"] = settings["namespace"]
    os.environ["OCI_BUCKET"] = settings["bucket"]

    AppConfig.OCI_REGION = settings["region"]
    AppConfig.OCI_CONFIG_PATH = settings["config_path"]
    AppConfig.OCI_CONFIG_PROFILE = settings["profile"]
    AppConfig.OCI_CONFIG_COMPARTMENT = settings["compartment_id"]
    AppConfig.OCI_SERVICE_ENDPOINT = settings["service_endpoint"]
    AppConfig.LLM_MODEL_ID = settings["llm_model_id"]
    AppConfig.VLM_MODEL_ID = settings["vlm_model_id"]
    AppConfig.EMBEDDING_MODEL_ID = settings["embedding_model_id"]
    AppConfig.SELECT_AI_ENABLED = bool(settings["select_ai_enabled"])
    AppConfig.SELECT_AI_REGION = settings["select_ai_region"]
    AppConfig.SELECT_AI_MODEL_ID = settings["select_ai_model_id"]
    AppConfig.SELECT_AI_EMBEDDING_MODEL_ID = settings["select_ai_embedding_model_id"]
    AppConfig.SELECT_AI_ENDPOINT_ID = settings["select_ai_endpoint_id"]
    AppConfig.SELECT_AI_MAX_TOKENS = int(settings["select_ai_max_tokens"])
    AppConfig.SELECT_AI_ENFORCE_OBJECT_LIST = bool(settings["select_ai_enforce_object_list"])
    AppConfig.SELECT_AI_OCI_API_FORMAT = settings["select_ai_oci_apiformat"]
    AppConfig.SELECT_AI_USE_ANNOTATIONS = bool(settings["select_ai_use_annotations"])
    AppConfig.SELECT_AI_USE_COMMENTS = bool(settings["select_ai_use_comments"])
    AppConfig.SELECT_AI_USE_CONSTRAINTS = bool(settings["select_ai_use_constraints"])
    AppConfig.LLM_MAX_TOKENS = int(settings["llm_max_tokens"])
    AppConfig.LLM_TEMPERATURE = float(settings["llm_temperature"])
    AppConfig.OCI_NAMESPACE = settings["namespace"]
    AppConfig.OCI_BUCKET = settings["bucket"]


def _save_oci_settings(settings_payload: Dict[str, Any]) -> Dict[str, Any]:
    current_snapshot = _load_oci_settings_snapshot()
    current_settings = current_snapshot["settings"]

    config_path = _expand_path(
        _normalize_text(settings_payload.get("config_path"), current_settings.get("config_path", "~/.oci/config")),
        "~/.oci/config",
    )
    profile = _normalize_text(settings_payload.get("profile"), current_settings.get("profile", "DEFAULT")) or "DEFAULT"
    service_endpoint = _normalize_text(
        settings_payload.get("service_endpoint"),
        current_settings.get("service_endpoint", "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com"),
    )

    parser = configparser.ConfigParser()
    if os.path.exists(config_path):
        parser.read(config_path)

    key_file = _resolve_key_file_path(
        config_path=config_path,
        parser=parser,
        profile=profile,
        explicit_key_file=_normalize_text(settings_payload.get("key_file")),
    )
    provided_key_content = settings_payload.get("key_content")
    provided_key_content_normalized = _normalize_text(provided_key_content)
    has_new_key = bool(
        provided_key_content_normalized and provided_key_content_normalized != _OCI_MASKED_KEY
    )

    if has_new_key:
        if not _validate_private_key_content(provided_key_content_normalized):
            raise ValueError("Invalid PEM format for private key.")
        key_dir = os.path.dirname(key_file) or "."
        os.makedirs(key_dir, exist_ok=True)
        try:
            os.chmod(key_dir, 0o700)
        except Exception:  # pragma: no cover - filesystem dependent
            pass
        with open(key_file, "w", encoding="utf-8") as key_writer:
            key_writer.write(str(provided_key_content))
        try:
            os.chmod(key_file, 0o600)
        except Exception:  # pragma: no cover - filesystem dependent
            pass
    elif not os.path.exists(key_file):
        raise ValueError("Private key is required for initial OCI configuration.")

    user_ocid = _normalize_text(settings_payload.get("user_ocid"), current_settings.get("user_ocid", ""))
    tenancy_ocid = _normalize_text(settings_payload.get("tenancy_ocid"), current_settings.get("tenancy_ocid", ""))
    fingerprint = _normalize_text(settings_payload.get("fingerprint"), current_settings.get("fingerprint", ""))
    region = _normalize_text(settings_payload.get("region"), current_settings.get("region", ""))
    if not region:
        region = _extract_region_from_endpoint(service_endpoint)

    if profile.upper() == "DEFAULT":
        target_section = parser["DEFAULT"]
    else:
        if not parser.has_section(profile):
            parser.add_section(profile)
        target_section = parser[profile]

    target_section["user"] = user_ocid
    target_section["tenancy"] = tenancy_ocid
    target_section["fingerprint"] = fingerprint
    target_section["region"] = region
    target_section["key_file"] = key_file

    config_dir = os.path.dirname(config_path) or "."
    os.makedirs(config_dir, exist_ok=True)
    try:
        os.chmod(config_dir, 0o700)
    except Exception:  # pragma: no cover - filesystem dependent
        pass

    with open(config_path, "w", encoding="utf-8") as config_writer:
        parser.write(config_writer)
    try:
        os.chmod(config_path, 0o600)
    except Exception:  # pragma: no cover - filesystem dependent
        pass

    settings_for_env = {
        "region": region,
        "config_path": config_path,
        "profile": profile,
        "compartment_id": _normalize_text(
            settings_payload.get("compartment_id"),
            current_settings.get("compartment_id", ""),
        ),
        "service_endpoint": service_endpoint,
        "llm_model_id": _normalize_text(
            settings_payload.get("llm_model_id"),
            current_settings.get("llm_model_id", "xai.grok-code-fast-1"),
        )
        or "xai.grok-code-fast-1",
        "vlm_model_id": _normalize_text(
            settings_payload.get("vlm_model_id"),
            current_settings.get("vlm_model_id", "google.gemini-2.5-flash"),
        )
        or "google.gemini-2.5-flash",
        "embedding_model_id": _normalize_text(
            settings_payload.get("embedding_model_id"),
            current_settings.get("embedding_model_id", "cohere.embed-v4.0"),
        )
        or "cohere.embed-v4.0",
        "select_ai_enabled": _to_bool(
            settings_payload.get("select_ai_enabled"),
            default=bool(current_settings.get("select_ai_enabled", True)),
        ),
        "select_ai_region": _normalize_text(
            settings_payload.get("select_ai_region"),
            current_settings.get("select_ai_region", _DEFAULT_SELECT_AI_REGION),
        )
        or _DEFAULT_SELECT_AI_REGION,
        "select_ai_model_id": _normalize_text(
            settings_payload.get("select_ai_model_id"),
            current_settings.get("select_ai_model_id", _DEFAULT_SELECT_AI_MODEL_ID),
        )
        or _DEFAULT_SELECT_AI_MODEL_ID,
        "select_ai_embedding_model_id": _normalize_text(
            settings_payload.get("select_ai_embedding_model_id"),
            current_settings.get("select_ai_embedding_model_id", current_settings.get("embedding_model_id", "cohere.embed-v4.0")),
        )
        or current_settings.get("embedding_model_id", "cohere.embed-v4.0"),
        "select_ai_endpoint_id": _normalize_text(
            settings_payload.get("select_ai_endpoint_id"),
            current_settings.get("select_ai_endpoint_id", ""),
        ),
        "select_ai_max_tokens": int(
            settings_payload.get("select_ai_max_tokens", current_settings.get("select_ai_max_tokens", _DEFAULT_SELECT_AI_MAX_TOKENS))
        ),
        "select_ai_enforce_object_list": _to_bool(
            settings_payload.get("select_ai_enforce_object_list"),
            default=bool(current_settings.get("select_ai_enforce_object_list", True)),
        ),
        "select_ai_oci_apiformat": _normalize_text(
            settings_payload.get("select_ai_oci_apiformat"),
            current_settings.get("select_ai_oci_apiformat", "GENERIC"),
        ).upper() or "GENERIC",
        "select_ai_use_annotations": _to_bool(
            settings_payload.get("select_ai_use_annotations"),
            default=bool(current_settings.get("select_ai_use_annotations", True)),
        ),
        "select_ai_use_comments": _to_bool(
            settings_payload.get("select_ai_use_comments"),
            default=bool(current_settings.get("select_ai_use_comments", True)),
        ),
        "select_ai_use_constraints": _to_bool(
            settings_payload.get("select_ai_use_constraints"),
            default=bool(current_settings.get("select_ai_use_constraints", True)),
        ),
        "llm_max_tokens": int(
            settings_payload.get("llm_max_tokens", current_settings.get("llm_max_tokens", 65536))
        ),
        "llm_temperature": float(
            settings_payload.get("llm_temperature", current_settings.get("llm_temperature", 0.0))
        ),
        "namespace": _normalize_text(
            settings_payload.get("namespace"),
            current_settings.get("namespace", ""),
        ),
        "bucket": _normalize_text(
            settings_payload.get("bucket"),
            current_settings.get("bucket", ""),
        ),
    }

    _upsert_env_values(
        _env_file_path(),
        {
            "OCI_REGION": settings_for_env["region"],
            "OCI_CONFIG_PATH": settings_for_env["config_path"],
            "OCI_CONFIG_PROFILE": settings_for_env["profile"],
            "OCI_CONFIG_COMPARTMENT": settings_for_env["compartment_id"],
            "OCI_SERVICE_ENDPOINT": settings_for_env["service_endpoint"],
            "LLM_MODEL_ID": settings_for_env["llm_model_id"],
            "VLM_MODEL_ID": settings_for_env["vlm_model_id"],
            "EMBEDDING_MODEL_ID": settings_for_env["embedding_model_id"],
            "SELECT_AI_ENABLED": "true" if settings_for_env["select_ai_enabled"] else "false",
            "SELECT_AI_REGION": settings_for_env["select_ai_region"],
            "SELECT_AI_MODEL_ID": settings_for_env["select_ai_model_id"],
            "SELECT_AI_EMBEDDING_MODEL_ID": settings_for_env["select_ai_embedding_model_id"],
            "SELECT_AI_ENDPOINT_ID": settings_for_env["select_ai_endpoint_id"],
            "SELECT_AI_MAX_TOKENS": str(settings_for_env["select_ai_max_tokens"]),
            "SELECT_AI_ENFORCE_OBJECT_LIST": "true" if settings_for_env["select_ai_enforce_object_list"] else "false",
            "SELECT_AI_OCI_API_FORMAT": settings_for_env["select_ai_oci_apiformat"],
            "SELECT_AI_USE_ANNOTATIONS": "true" if settings_for_env["select_ai_use_annotations"] else "false",
            "SELECT_AI_USE_COMMENTS": "true" if settings_for_env["select_ai_use_comments"] else "false",
            "SELECT_AI_USE_CONSTRAINTS": "true" if settings_for_env["select_ai_use_constraints"] else "false",
            "LLM_MAX_TOKENS": str(settings_for_env["llm_max_tokens"]),
            "LLM_TEMPERATURE": str(settings_for_env["llm_temperature"]),
            "OCI_NAMESPACE": settings_for_env["namespace"],
            "OCI_BUCKET": settings_for_env["bucket"],
        },
    )
    load_dotenv(_env_file_path(), override=True)
    _apply_runtime_oci_values(settings_for_env)

    snapshot = _load_oci_settings_snapshot()
    snapshot["status"] = "saved"
    snapshot["is_configured"] = snapshot["has_credentials"]
    return snapshot


def _build_oci_test_config(request_settings: Dict[str, Any]) -> Dict[str, str]:
    snapshot = _load_oci_settings_snapshot()["settings"]
    parser = configparser.ConfigParser()

    config_path = _expand_path(
        _normalize_text(request_settings.get("config_path"), snapshot.get("config_path", "~/.oci/config")),
        "~/.oci/config",
    )
    if os.path.exists(config_path):
        parser.read(config_path)
    profile = _normalize_text(request_settings.get("profile"), snapshot.get("profile", "DEFAULT")) or "DEFAULT"
    key_file = _resolve_key_file_path(config_path, parser, profile)

    key_content = _normalize_text(request_settings.get("key_content"), snapshot.get("key_content", ""))
    if key_content == _OCI_MASKED_KEY or not key_content:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as key_reader:
                key_content = key_reader.read()
        else:
            key_content = ""

    service_endpoint = _normalize_text(request_settings.get("service_endpoint"), snapshot.get("service_endpoint", ""))
    region = _normalize_text(request_settings.get("region"), snapshot.get("region", ""))
    if not region:
        region = _extract_region_from_endpoint(service_endpoint)

    return {
        "user": _normalize_text(request_settings.get("user_ocid"), snapshot.get("user_ocid", "")),
        "tenancy": _normalize_text(request_settings.get("tenancy_ocid"), snapshot.get("tenancy_ocid", "")),
        "fingerprint": _normalize_text(request_settings.get("fingerprint"), snapshot.get("fingerprint", "")),
        "key_content": key_content,
        "region": region,
    }


def _build_oci_model_test_settings(request_settings: Dict[str, Any]) -> Dict[str, str]:
    snapshot_settings = _load_oci_settings_snapshot()["settings"]
    defaults = _runtime_oci_defaults()

    service_endpoint = _normalize_text(
        request_settings.get("service_endpoint"),
        snapshot_settings.get("service_endpoint", defaults.get("service_endpoint", "")),
    )
    if not service_endpoint:
        resolved_region = _normalize_text(
            request_settings.get("region"),
            snapshot_settings.get("region", defaults.get("region", _DEFAULT_OCI_REGION)),
        ) or _DEFAULT_OCI_REGION
        service_endpoint = f"https://inference.generativeai.{resolved_region}.oci.oraclecloud.com"
    compartment_id = _normalize_text(
        request_settings.get("compartment_id"),
        snapshot_settings.get("compartment_id", defaults.get("compartment_id", "")),
    )
    llm_model_id = _normalize_text(
        request_settings.get("llm_model_id"),
        snapshot_settings.get("llm_model_id", defaults.get("llm_model_id", "xai.grok-code-fast-1")),
    ) or "xai.grok-code-fast-1"
    vlm_model_id = _normalize_text(
        request_settings.get("vlm_model_id"),
        snapshot_settings.get("vlm_model_id", defaults.get("vlm_model_id", "google.gemini-2.5-flash")),
    ) or "google.gemini-2.5-flash"
    embedding_model_id = _normalize_text(
        request_settings.get("embedding_model_id"),
        snapshot_settings.get("embedding_model_id", defaults.get("embedding_model_id", "cohere.embed-v4.0")),
    ) or "cohere.embed-v4.0"
    llm_max_tokens = int(
        request_settings.get("llm_max_tokens", snapshot_settings.get("llm_max_tokens", defaults.get("llm_max_tokens", 65536)))
    )
    llm_temperature = float(
        request_settings.get("llm_temperature", snapshot_settings.get("llm_temperature", defaults.get("llm_temperature", 0.0)))
    )

    return {
        "service_endpoint": service_endpoint,
        "compartment_id": compartment_id,
        "llm_model_id": llm_model_id,
        "vlm_model_id": vlm_model_id,
        "embedding_model_id": embedding_model_id,
        "llm_max_tokens": llm_max_tokens,
        "llm_temperature": llm_temperature,
    }


def _parse_db_connection_string(connection_string: str) -> Dict[str, str]:
    value = _normalize_text(connection_string)
    if not value or "/" not in value or "@" not in value:
        return {"username": "", "password": "", "dsn": ""}
    user_pass, dsn = value.rsplit("@", 1)
    if "/" not in user_pass:
        return {"username": "", "password": "", "dsn": ""}
    username, password = user_pass.split("/", 1)
    return {
        "username": _normalize_text(username),
        "password": _normalize_text(password),
        "dsn": _normalize_text(dsn),
    }


def _build_db_connection_string(username: str, password: str, dsn: str) -> str:
    return f"{username}/{password}@{dsn}"


def _db_wallet_location(create_if_missing: bool = False) -> Optional[str]:
    tns_admin = _normalize_text(os.environ.get("TNS_ADMIN"))
    if tns_admin:
        path = _expand_path(tns_admin, tns_admin)
        if create_if_missing:
            os.makedirs(path, exist_ok=True)
            return path
        return path if os.path.exists(path) else None

    oracle_client_lib_dir = _normalize_text(os.environ.get("ORACLE_CLIENT_LIB_DIR"))
    if oracle_client_lib_dir:
        wallet_path = os.path.join(_expand_path(oracle_client_lib_dir, oracle_client_lib_dir), "network", "admin")
        # reference behavior: TNS_ADMIN is derived from ORACLE_CLIENT_LIB_DIR/network/admin
        os.environ["TNS_ADMIN"] = wallet_path
    else:
        wallet_path = os.path.join(str(_project_root_path()), "denpyo_toroku", "data", "wallet")

    if create_if_missing:
        os.makedirs(wallet_path, exist_ok=True)
        return wallet_path
    return wallet_path if os.path.exists(wallet_path) else None


def _extract_services_from_tnsnames(wallet_location: Optional[str]) -> List[str]:
    if not wallet_location:
        return []
    tnsnames_path = os.path.join(wallet_location, "tnsnames.ora")
    if not os.path.exists(tnsnames_path):
        return []
    try:
        with open(tnsnames_path, "r", encoding="utf-8") as reader:
            content = reader.read()
        matches = re.findall(r"^([A-Za-z0-9_-]+)\s*=", content, re.MULTILINE)
        return sorted(set(_normalize_text(item) for item in matches if _normalize_text(item)))
    except Exception:
        return []


def _wallet_is_ready(wallet_location: Optional[str]) -> bool:
    if not wallet_location:
        return False
    return all(os.path.exists(os.path.join(wallet_location, file_name)) for file_name in _DB_REQUIRED_WALLET_FILES)


def _load_database_settings_snapshot() -> Dict[str, Any]:
    conn_info = _parse_db_connection_string(os.environ.get(_DB_CONN_ENV_KEY, ""))
    adb_ocid = _normalize_text(os.environ.get(_DB_ADB_OCID_ENV_KEY, ""))
    # リージョンはOCIDと同時に取得する（.envのOCI_REGIONを優先）
    region = _normalize_text(os.environ.get("OCI_REGION"), _normalize_text(getattr(AppConfig, "OCI_REGION", ""), "ap-osaka-1"))
    wallet_location = _db_wallet_location(create_if_missing=False)
    wallet_uploaded = _wallet_is_ready(wallet_location)
    available_services = _extract_services_from_tnsnames(wallet_location)

    has_core_settings = bool(conn_info["username"] and conn_info["password"] and conn_info["dsn"])
    is_configured = has_core_settings and wallet_uploaded

    return {
        "settings": {
            "username": conn_info["username"],
            "password": _DB_MASKED_SECRET if conn_info["password"] else "",
            "dsn": conn_info["dsn"],
            "adb_ocid": adb_ocid,
            "region": region,
            "wallet_uploaded": wallet_uploaded,
            "available_services": available_services,
        },
        "wallet_location": wallet_location if wallet_uploaded else None,
        "is_connected": False,
        "is_configured": is_configured,
        "status": "configured" if is_configured else "not_configured",
    }


def _save_database_settings(settings_payload: Dict[str, Any]) -> Dict[str, Any]:
    current_snapshot = _load_database_settings_snapshot()
    current_settings = current_snapshot["settings"]
    current_conn_info = _parse_db_connection_string(os.environ.get(_DB_CONN_ENV_KEY, ""))

    username = _normalize_text(settings_payload.get("username"), current_conn_info["username"] or current_settings.get("username", ""))
    dsn = _normalize_text(settings_payload.get("dsn"), current_conn_info["dsn"] or current_settings.get("dsn", ""))

    incoming_password = settings_payload.get("password")
    incoming_password_text = _normalize_text(incoming_password)
    if incoming_password_text == _DB_MASKED_SECRET:
        password = current_conn_info["password"]
    elif incoming_password_text:
        password = incoming_password_text
    else:
        password = current_conn_info["password"]

    if not username or not password or not dsn:
        raise ValueError("ユーザー名・パスワード・DSN は必須です。")
    adb_ocid = _normalize_text(settings_payload.get("adb_ocid"), os.environ.get(_DB_ADB_OCID_ENV_KEY, ""))

    conn_string = _build_db_connection_string(username, password, dsn)
    _upsert_env_values(
        _env_file_path(),
        {
            _DB_CONN_ENV_KEY: conn_string,
            _DB_ADB_OCID_ENV_KEY: adb_ocid,
        },
    )
    load_dotenv(_env_file_path(), override=True)

    os.environ[_DB_CONN_ENV_KEY] = conn_string
    os.environ[_DB_ADB_OCID_ENV_KEY] = adb_ocid
    AppConfig.ADB_OCID = adb_ocid

    snapshot = _load_database_settings_snapshot()
    snapshot["status"] = "saved"
    return snapshot


def _database_env_connection_info(include_password: bool = False) -> Dict[str, Any]:
    conn_info = _parse_db_connection_string(os.environ.get(_DB_CONN_ENV_KEY, ""))
    adb_ocid = _normalize_text(os.environ.get(_DB_ADB_OCID_ENV_KEY, ""))
    region = _normalize_text(os.environ.get("OCI_REGION"), _normalize_text(getattr(AppConfig, "OCI_REGION", ""), "ap-osaka-1"))
    wallet_location = _db_wallet_location(create_if_missing=False)
    wallet_exists = _wallet_is_ready(wallet_location)
    available_services = _extract_services_from_tnsnames(wallet_location)

    if not conn_info["username"] or not conn_info["dsn"]:
        return {
            "success": False,
            "message": f"{_DB_CONN_ENV_KEY} 環境変数が未設定、または形式が不正です。",
            "username": None,
            "password": None,
            "dsn": None,
            "adb_ocid": adb_ocid or None,
            "region": region or None,
            "wallet_exists": wallet_exists,
            "wallet_location": wallet_location if wallet_exists else None,
            "available_services": available_services,
        }

    return {
        "success": True,
        "message": "環境変数から接続情報を取得しました。",
        "username": conn_info["username"],
        "password": conn_info["password"] if include_password else (_DB_MASKED_SECRET if conn_info["password"] else ""),
        "dsn": conn_info["dsn"],
        "adb_ocid": adb_ocid or None,
        "region": region or None,
        "wallet_exists": wallet_exists,
        "wallet_location": wallet_location if wallet_exists else None,
        "available_services": available_services,
    }


def _map_db_connection_error(error_text: str) -> str:
    if "DPY-6005" in error_text or "DPY-6000" in error_text:
        return "接続エラー: データベースが停止している可能性があります。"
    if "ORA-01017" in error_text:
        return "接続エラー: ユーザー名またはパスワードが正しくありません。"
    if "ORA-12154" in error_text:
        return "接続エラー: DSN が見つかりません。Wallet と tnsnames.ora を確認してください。"
    if "ORA-12541" in error_text:
        return "接続エラー: データベースサーバーに接続できません。"
    if "DPY-4011" in error_text:
        return "接続エラー: Wallet または TNS 設定に問題があります。"
    return f"接続エラー: {error_text}"


def _test_database_connection(settings_payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = settings_payload if isinstance(settings_payload, dict) else {}
    snapshot = _load_database_settings_snapshot()["settings"]
    env_info = _database_env_connection_info(include_password=True)

    username = _normalize_text(payload.get("username"), snapshot.get("username", ""))
    dsn = _normalize_text(payload.get("dsn"), snapshot.get("dsn", ""))
    incoming_password = _normalize_text(payload.get("password"))
    if incoming_password == _DB_MASKED_SECRET or not incoming_password:
        password = _normalize_text(env_info.get("password") if env_info.get("success") else "")
    else:
        password = incoming_password

    if not username or not password or not dsn:
        return {
            "success": False,
            "message": "接続情報が不完全です。ユーザー名・パスワード・DSN を入力してください。",
            "details": None,
        }

    wallet_location = _db_wallet_location(create_if_missing=False)
    if not _wallet_is_ready(wallet_location):
        return {
            "success": False,
            "message": f"Wallet ディレクトリが未設定、または必要ファイルが不足しています: {wallet_location}",
            "details": None,
        }

    try:
        import oracledb  # type: ignore
    except Exception:
        return {
            "success": False,
            "message": "oracledb モジュールが未インストールです。`pip install oracledb` を実行してください。",
            "details": None,
        }

    connection = None
    started_at = time.time()
    try:
        connection = oracledb.connect(
            user=username,
            password=password,
            dsn=dsn,
            config_dir=wallet_location,
            wallet_location=wallet_location,
            wallet_password=password,
            tcp_connect_timeout=10,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM DUAL")
            cursor.fetchone()
        elapsed = round(time.time() - started_at, 2)
        return {
            "success": True,
            "message": "データベース接続に成功しました。",
            "details": {
                "username": username,
                "dsn": dsn,
                "wallet_location": wallet_location,
                "elapsed_sec": str(elapsed),
            },
        }
    except Exception as e:
        return {
            "success": False,
            "message": _map_db_connection_error(str(e)),
            "details": None,
        }
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _upload_database_wallet(uploaded_file: Any) -> Dict[str, Any]:
    filename = _normalize_text(getattr(uploaded_file, "filename", ""))
    if not filename.lower().endswith(".zip"):
        raise ValueError("ZIPファイルのみ対応しています。")

    wallet_location = _db_wallet_location(create_if_missing=True)
    if not wallet_location:
        raise ValueError("Wallet の保存先を決定できませんでした。")

    with tempfile.NamedTemporaryFile(prefix="wallet_", suffix=".zip", delete=False) as temp_writer:
        temp_path = temp_writer.name
    try:
        uploaded_file.save(temp_path)

        if os.path.exists(wallet_location):
            backup_dir = f"{wallet_location}_backup_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.move(wallet_location, backup_dir)
        os.makedirs(wallet_location, exist_ok=True)

        with zipfile.ZipFile(temp_path, "r") as zip_ref:
            zip_ref.extractall(wallet_location)

        for file_name in _DB_UNNECESSARY_WALLET_FILES:
            file_path = os.path.join(wallet_location, file_name)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

        missing = [f for f in _DB_REQUIRED_WALLET_FILES if not os.path.exists(os.path.join(wallet_location, f))]
        if missing:
            raise ValueError(
                "必要な Wallet ファイルが不足しています: %s" % ", ".join(missing)
            )

        services = _extract_services_from_tnsnames(wallet_location)
        return {
            "success": True,
            "message": "Walletをアップロードしました。",
            "wallet_location": wallet_location,
            "available_services": services,
        }
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


@api_blueprint.before_request
def before_request():
    g.response = Response()
    g.request_start_time = time.time()


@api_blueprint.after_request
def after_request(response):
    endpoint = request.endpoint or "unknown"
    method = request.method
    status_code = str(response.status_code)
    duration = max(time.time() - g.get("request_start_time", time.time()), 0)

    if REQUEST_COUNT is not None and REQUEST_LATENCY_SECONDS is not None:
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status_code=status_code).inc()
        REQUEST_LATENCY_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)
    return response


@api_blueprint.route("/v1/me", methods=["GET"])
def get_current_user():
    """ERP-compatible current user endpoint."""
    user = session.get("user", None)
    user_id = session.get("user_id", None)
    role = session.get("role", "USER")
    if _is_session_authenticated():
        return jsonify({
            "authenticated": True,
            "user": user,
            "user_id": user_id,
            "role": role
        })
    return jsonify({"authenticated": False})


@api_blueprint.route("/v1/loginValidation", methods=["POST"])
def login_validation():
    """ERP-compatible login validation endpoint."""
    try:
        if request.is_json:
            data = request.get_json() or {}
            username = (data.get("username") or "").strip()
            password = data.get("password", "")
        else:
            username = (request.form.get("username", "") or "").strip()
            password = request.form.get("password", "")

        if not username or not password:
            return jsonify({"success": False, "message": "ユーザー名とパスワードは必須です"}), 400

        if username == _default_auth_username and password == _default_auth_password:
            session["user"] = username
            session["user_id"] = "admin-user-id"
            session["role"] = "ADMIN"
            session["token"] = hashlib.sha256(
                f"{username}{dt.datetime.now()}".encode()
            ).hexdigest()
            expiry_time = dt.datetime.now() + dt.timedelta(minutes=30)
            session["token_expiry_ts"] = int(expiry_time.timestamp())

            if request.is_json:
                return jsonify({
                    "success": True,
                    "message": "サインインしました",
                    "user": username,
                    "role": "ADMIN"
                })
            return redirect("/studio/", code=303)

        if request.is_json:
            return jsonify({"success": False, "message": "ユーザー名またはパスワードが正しくありません"}), 401
        return redirect("/studio/login?error=invalid", code=303)
    except Exception as e:
        logging.error("ログインエラー: %s", str(e), exc_info=True)
        return jsonify({"success": False, "message": "ログイン処理中にエラーが発生しました"}), 500


@api_blueprint.route("/logout", methods=["GET", "POST"])
def logout():
    """ERP-compatible logout endpoint."""
    session.pop("user", None)
    session.pop("user_id", None)
    session.pop("role", None)
    session.pop("token", None)
    session.pop("token_expiry_ts", None)
    return redirect("/studio/login", code=303)


@api_blueprint.route("/api/v1/auth/me", methods=["GET"])
def auth_me_compat():
    """Backward-compatible endpoint."""
    if not _is_session_authenticated():
        g.response.add_error_message("認証が必要です")
        return jsonify(g.response.get_result()), 401
    g.response.set_data({
        "email": session.get("user", _default_auth_username),
        "authenticated": True
    })
    return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/auth/login", methods=["POST"])
def auth_login_compat():
    """Backward-compatible endpoint."""
    data = request.get_json(silent=True) or {}
    username = (data.get("email") or data.get("username") or "").strip()
    password = data.get("password") or ""
    if username == _default_auth_username and password == _default_auth_password:
        session["user"] = username
        session["user_id"] = "admin-user-id"
        session["role"] = "ADMIN"
        session["token"] = hashlib.sha256(
            f"{username}{dt.datetime.now()}".encode()
        ).hexdigest()
        expiry_time = dt.datetime.now() + dt.timedelta(minutes=30)
        session["token_expiry_ts"] = int(expiry_time.timestamp())
        g.response.set_data({"email": username, "authenticated": True})
        return jsonify(g.response.get_result())
    g.response.add_error_message("ユーザー名またはパスワードが正しくありません")
    return jsonify(g.response.get_result()), 401


@api_blueprint.route("/api/v1/auth/logout", methods=["POST"])
def auth_logout_compat():
    """Backward-compatible endpoint."""
    session.pop("user", None)
    session.pop("user_id", None)
    session.pop("role", None)
    session.pop("token", None)
    session.pop("token_expiry_ts", None)
    g.response.set_data({"authenticated": False})
    return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/oci/settings", methods=["GET"])
def get_oci_settings():
    """Get current OCI application settings."""
    try:
        snapshot = _load_oci_settings_snapshot()
        g.response.set_data(snapshot)
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("OCI 設定の読み込みエラー: %s", e, exc_info=True)
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/oci/object-storage/settings", methods=["GET"])
def get_oci_object_storage_settings():
    """Get Object Storage settings. If OCI_NAMESPACE is missing, resolve via OCI SDK once."""
    try:
        snapshot = _load_oci_settings_snapshot()
        settings = snapshot.get("settings", {})
        region = _runtime_oci_region_default()

        namespace = _normalize_text(settings.get("namespace"))
        if not namespace:
            resolved_namespace = _fetch_object_storage_namespace_via_sdk(region)
            if resolved_namespace:
                _upsert_env_values(_env_file_path(), {"OCI_NAMESPACE": resolved_namespace})
                load_dotenv(_env_file_path(), override=True)
                os.environ["OCI_NAMESPACE"] = resolved_namespace
                AppConfig.OCI_NAMESPACE = resolved_namespace
                snapshot = _load_oci_settings_snapshot()
                settings = snapshot.get("settings", {})

        g.response.set_data({
            "settings": {
                "region": region,
                "namespace": _normalize_text(settings.get("namespace")),
                "bucket": _normalize_text(settings.get("bucket")),
            }
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("Object Storage 設定の読み込みエラー: %s", e, exc_info=True)
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/oci/settings", methods=["POST"])
def save_oci_settings():
    """Save OCI application settings."""
    try:
        body = request.get_json(silent=True) or {}
        settings_payload = body.get("settings") if isinstance(body.get("settings"), dict) else body
        if not isinstance(settings_payload, dict):
            g.response.add_error_message("リクエストボディが不正です。")
            return jsonify(g.response.get_result()), 422

        # 分割された設定ページからの部分更新を許可するため、現在値とマージして検証する
        current_settings = _load_oci_settings_snapshot().get("settings", {})
        merged_settings = {**current_settings, **settings_payload}

        # 必須項目は semantic-doc-search の OCI キー認証の挙動に合わせる
        required_fields = {
            "user_ocid": "ユーザー OCID",
            "tenancy_ocid": "テナンシ OCID",
            "fingerprint": "フィンガープリント",
            "region": "リージョン",
        }
        missing_fields = [
            label
            for field, label in required_fields.items()
            if not _normalize_text(merged_settings.get(field))
        ]
        if missing_fields:
            g.response.add_error_message("必須項目が未入力です: %s" % "、".join(missing_fields))
            return jsonify(g.response.get_result()), 422

        snapshot = _save_oci_settings(settings_payload)
        g.response.set_data(snapshot)
        return jsonify(g.response.get_result())
    except ValueError as e:
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 422
    except Exception as e:
        logging.error("OCI 設定の保存エラー: %s", e, exc_info=True)
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/oci/test", methods=["POST"])
def test_oci_connection():
    """Test OCI authentication settings."""
    try:
        body = request.get_json(silent=True) or {}
        settings_payload = body.get("settings") if isinstance(body.get("settings"), dict) else body
        if not isinstance(settings_payload, dict):
            g.response.add_error_message("リクエストボディが不正です。")
            return jsonify(g.response.get_result()), 422

        test_config = _build_oci_test_config(settings_payload)
        if not all([test_config["user"], test_config["tenancy"], test_config["fingerprint"], test_config["key_content"], test_config["region"]]):
            g.response.add_error_message(
                "OCI 認証情報が不足しています。ユーザー OCID / テナンシ OCID / フィンガープリント / リージョン / 秘密鍵が必須です。"
            )
            return jsonify(g.response.get_result()), 422

        import oci  # local import to avoid import-time dependency in non-OCI flows

        identity_client = oci.identity.IdentityClient(test_config)
        user_data = identity_client.get_user(test_config["user"]).data
        g.response.set_data({
            "success": True,
            "message": "OCI 接続テストに成功しました。",
            "details": {
                "user_name": getattr(user_data, "name", ""),
                "user_ocid": getattr(user_data, "id", test_config["user"]),
                "tenancy_ocid": test_config["tenancy"],
                "region": test_config["region"],
            },
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("OCI 接続テストエラー: %s", e, exc_info=True)
        g.response.set_data({
            "success": False,
            "message": "OCI 接続テストに失敗しました: %s" % str(e),
            "details": None,
        })
        return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/oci/model/test", methods=["POST"])
def test_oci_model_connection():
    """Test OCI GenAI model IDs (LLM / VLM / Embedding) individually."""
    try:
        body = request.get_json(silent=True) or {}
        settings_payload = body.get("settings") if isinstance(body.get("settings"), dict) else body
        if not isinstance(settings_payload, dict):
            g.response.add_error_message("リクエストボディが不正です。")
            return jsonify(g.response.get_result()), 422

        test_type = _normalize_text(body.get("test_type"), "llm").lower()
        if test_type not in ("llm", "vlm", "embedding"):
            g.response.add_error_message("test_type は llm / vlm / embedding のいずれかを指定してください。")
            return jsonify(g.response.get_result()), 422

        oci_auth_config = _build_oci_test_config(settings_payload)
        if not all([
            oci_auth_config["user"],
            oci_auth_config["tenancy"],
            oci_auth_config["fingerprint"],
            oci_auth_config["key_content"],
            oci_auth_config["region"],
        ]):
            g.response.add_error_message(
                "OCI 認証情報が不足しています。ユーザー OCID / テナンシ OCID / フィンガープリント / リージョン / 秘密鍵が必須です。"
            )
            return jsonify(g.response.get_result()), 422

        model_settings = _build_oci_model_test_settings(settings_payload)
        if not model_settings["service_endpoint"] or not model_settings["compartment_id"]:
            g.response.add_error_message("service_endpoint と compartment_id は必須です。")
            return jsonify(g.response.get_result()), 422

        import oci  # local import to avoid import-time dependency in non-OCI flows

        genai_client = oci.generative_ai_inference.GenerativeAiInferenceClient(
            oci_auth_config,
            service_endpoint=model_settings["service_endpoint"],
        )

        test_input_text = "こんにちわ"

        if test_type == "llm":
            model_id = model_settings["llm_model_id"]
            if not model_id:
                g.response.add_error_message("llm_model_id は必須です。")
                return jsonify(g.response.get_result()), 422

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[{"type": "TEXT", "text": test_input_text}]
                    )
                ],
                max_tokens=model_settings.get("llm_max_tokens", AppConfig.LLM_MAX_TOKENS),
                temperature=model_settings.get("llm_temperature", AppConfig.LLM_TEMPERATURE),
                is_stream=False,
            )
            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=model_settings["compartment_id"],
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(model_id=model_id),
                chat_request=chat_request,
            )
            response = genai_client.chat(chat_detail)
            result_text = ""
            chat_response = getattr(getattr(response, "data", None), "chat_response", None)
            if hasattr(chat_response, "choices") and chat_response.choices:
                message = chat_response.choices[0].message
                if hasattr(message, "content"):
                    for part in message.content:
                        if hasattr(part, "text") and part.text:
                            result_text += part.text
            g.response.set_data({
                "success": True,
                "message": "LLM モデル ID テストに成功しました。",
                "details": {
                    "test_type": "llm",
                    "input_text": test_input_text,
                    "result_text": result_text.strip(),
                    "model_id": model_id,
                    "compartment_id": model_settings["compartment_id"],
                    "region": oci_auth_config["region"],
                    "request_id": getattr(response, "request_id", ""),
                },
            })
            return jsonify(g.response.get_result())

        if test_type == "vlm":
            model_id = model_settings["vlm_model_id"]
            if not model_id:
                g.response.add_error_message("vlm_model_id は必須です。")
                return jsonify(g.response.get_result()), 422

            chat_request = oci.generative_ai_inference.models.GenericChatRequest(
                api_format="GENERIC",
                messages=[
                    oci.generative_ai_inference.models.UserMessage(
                        content=[{"type": "TEXT", "text": "画像解析モデルの接続テストです。'OK' とだけ返答してください。"}]
                    )
                ],
                max_tokens=model_settings.get("llm_max_tokens", AppConfig.LLM_MAX_TOKENS),
                temperature=model_settings.get("llm_temperature", AppConfig.LLM_TEMPERATURE),
                is_stream=False,
            )
            chat_detail = oci.generative_ai_inference.models.ChatDetails(
                compartment_id=model_settings["compartment_id"],
                serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(model_id=model_id),
                chat_request=chat_request,
            )
            response = genai_client.chat(chat_detail)
            result_text = ""
            chat_response = getattr(getattr(response, "data", None), "chat_response", None)
            if hasattr(chat_response, "choices") and chat_response.choices:
                message = chat_response.choices[0].message
                if hasattr(message, "content"):
                    for part in message.content:
                        if hasattr(part, "text") and part.text:
                            result_text += part.text
            g.response.set_data({
                "success": True,
                "message": "VLM モデル ID テストに成功しました。",
                "details": {
                    "test_type": "vlm",
                    "input_text": "テスト画像",
                    "result_text": result_text.strip(),
                    "model_id": model_id,
                    "compartment_id": model_settings["compartment_id"],
                    "region": oci_auth_config["region"],
                    "request_id": getattr(response, "request_id", ""),
                },
            })
            return jsonify(g.response.get_result())

        model_id = model_settings["embedding_model_id"]
        if not model_id:
            g.response.add_error_message("embedding_model_id は必須です。")
            return jsonify(g.response.get_result()), 422

        embed_details = oci.generative_ai_inference.models.EmbedTextDetails(
            inputs=[test_input_text],
            serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(model_id=model_id),
            compartment_id=model_settings["compartment_id"],
            input_type="CLASSIFICATION",
            truncate="END",
        )
        response = genai_client.embed_text(embed_details)
        embeddings = getattr(getattr(response, "data", None), "embeddings", []) or []
        embedding_count = len(embeddings)
        first_embedding = embeddings[0] if embedding_count > 0 else []
        embedding_dimension = len(first_embedding) if isinstance(first_embedding, list) else 0
        embedding_preview = first_embedding[:8] if isinstance(first_embedding, list) else []
        g.response.set_data({
            "success": True,
            "message": "埋め込みモデル ID テストに成功しました。",
            "details": {
                "test_type": "embedding",
                "input_text": test_input_text,
                "embedding_dimension": embedding_dimension,
                "embedding_preview": embedding_preview,
                "model_id": model_id,
                "compartment_id": model_settings["compartment_id"],
                "region": oci_auth_config["region"],
                "embedding_count": embedding_count,
                "request_id": getattr(response, "request_id", ""),
            },
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("OCI モデル ID テストエラー: %s", e, exc_info=True)
        g.response.set_data({
            "success": False,
            "message": "OCI モデル ID テストに失敗しました: %s" % str(e),
            "details": None,
        })
        return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/database/settings", methods=["GET"])
def get_database_settings():
    """Get current database settings without performing a connection test."""
    try:
        snapshot = _load_database_settings_snapshot()
        g.response.set_data(snapshot)
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("DB 設定の読み込みエラー: %s", e, exc_info=True)
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/database/settings/env", methods=["GET"])
def get_database_env_settings():
    """Read DB connection info from environment variables."""
    try:
        include_password = _to_bool(request.args.get("include_password"), default=False)
        env_info = _database_env_connection_info(include_password=include_password)
        g.response.set_data(env_info)
        if env_info.get("success", False):
            return jsonify(g.response.get_result())
        return jsonify(g.response.get_result()), 200
    except Exception as e:
        logging.error("DB 環境変数読み込みエラー: %s", e, exc_info=True)
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/database/settings", methods=["POST"])
def save_database_settings():
    """Save DB settings to .env."""
    try:
        body = request.get_json(silent=True) or {}
        settings_payload = body.get("settings") if isinstance(body.get("settings"), dict) else body
        if not isinstance(settings_payload, dict):
            g.response.add_error_message("リクエストボディが不正です。")
            return jsonify(g.response.get_result()), 422

        snapshot = _save_database_settings(settings_payload)
        g.response.set_data(snapshot)
        return jsonify(g.response.get_result())
    except ValueError as e:
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 422
    except Exception as e:
        logging.error("DB 設定の保存エラー: %s", e, exc_info=True)
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/database/settings/test", methods=["POST"])
def test_database_connection():
    """Test DB connection with current or provided settings.
    
    タイムアウト制御付きでDB接続テストを実行し、メインスレッドをブロックしないようにします。
    参考: no.1-semantic-doc-search プロジェクトの実装
    """
    try:
        body = request.get_json(silent=True) or {}
        settings_payload = body.get("settings") if isinstance(body.get("settings"), dict) else body
        
        # タイムアウト付きでDB接続テストを実行（非ブロッキング）
        started_at = time.time()
        try:
            future = _DB_TEST_EXECUTOR.submit(_test_database_connection, settings_payload)
            result = future.result(timeout=_DB_TEST_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            elapsed = round(time.time() - started_at, 2)
            logging.warning("DB 接続テストがタイムアウトしました (%s秒)", elapsed)
            result = {
                "success": False,
                "message": f"接続テストがタイムアウトしました（{elapsed}秒）。データベースが起動しているか確認してください。",
                "details": {"timeout_seconds": str(_DB_TEST_TIMEOUT_SECONDS), "elapsed_sec": str(elapsed)},
            }
        except Exception as e:
            logging.error("DB 接続テスト実行エラー: %s", e, exc_info=True)
            result = {
                "success": False,
                "message": f"接続テスト実行エラー: {str(e)}",
                "details": None,
            }
        
        g.response.set_data(result)
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("DB 接続テストエラー: %s", e, exc_info=True)
        g.response.set_data({
            "success": False,
            "message": f"接続テストエラー: {str(e)}",
            "details": None,
        })
        return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/database/settings/wallet", methods=["POST"])
def upload_database_wallet():
    """Upload wallet zip and expand it to wallet directory."""
    try:
        if "file" not in request.files:
            g.response.add_error_message("アップロードファイルが見つかりません。")
            return jsonify(g.response.get_result()), 422
        uploaded_file = request.files.get("file")
        if uploaded_file is None or not uploaded_file.filename:
            g.response.add_error_message("ファイル名が不正です。")
            return jsonify(g.response.get_result()), 422

        result = _upload_database_wallet(uploaded_file)
        g.response.set_data(result)
        return jsonify(g.response.get_result())
    except ValueError as e:
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 422
    except Exception as e:
        logging.error("Wallet アップロードエラー: %s", e, exc_info=True)
        g.response.add_error_message(str(e))
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/version", methods=["GET"])
def get_version():
    """Version endpoint."""
    g.response.set_data({
        "service": "Denpyo Toroku Service",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/api/v1/health",
            "oci_settings_get": "/api/v1/oci/settings",
            "oci_object_storage_settings_get": "/api/v1/oci/object-storage/settings",
            "oci_settings_save": "/api/v1/oci/settings",
            "oci_test": "/api/v1/oci/test",
            "oci_model_test": "/api/v1/oci/model/test",
            "db_settings_get": "/api/v1/database/settings",
            "db_settings_save": "/api/v1/database/settings",
            "db_settings_env": "/api/v1/database/settings/env",
            "db_settings_test": "/api/v1/database/settings/test",
            "db_wallet_upload": "/api/v1/database/settings/wallet",
            "dashboard_stats": "/api/v1/dashboard/stats",
            "database_init": "/api/v1/database/init",
            "docs": "/"
        }
    })
    return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    g.response.set_data({
        "status": "healthy",
        "message": "Denpyo Toroku Service is running",
        "version": "1.0.0"
    })
    return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/dashboard/stats", methods=["GET"])
def dashboard_stats():
    """ダッシュボード統計情報を返す"""
    try:
        from denpyo_toroku.app.services.database_service import DatabaseService
        db_service = DatabaseService()
        stats = db_service.get_dashboard_stats()
    except Exception as e:
        logging.warning("ダッシュボード統計取得エラー: %s", e)
        stats = {
            "upload_stats": {"total_files": 0, "this_month": 0},
            "registration_stats": {"total_registrations": 0, "this_month": 0},
            "category_stats": {"total_categories": 0, "active_categories": 0},
            "recent_activities": []
        }
    return jsonify({"data": stats})


@api_blueprint.route("/api/v1/database/init", methods=["POST"])
def database_init():
    """管理テーブルの初期化"""
    try:
        from denpyo_toroku.app.services.database_service import DatabaseService
        db_service = DatabaseService()
        result = db_service.initialize_tables()
        return jsonify({"data": result})
    except Exception as e:
        logging.error("テーブル初期化エラー: %s", e, exc_info=True)
        return jsonify({"data": {"success": False, "message": str(e)}}), 500


# ========================================
# Files API (SCR-001, SCR-002)
# ========================================

def _resolve_upload_object_prefix(upload_kind: str) -> str:
    normalized_kind = _normalize_text(upload_kind, "raw").lower()
    if normalized_kind == "category":
        object_prefix = _normalize_text(
            os.environ.get("OCI_SLIPS_CATEGORY_PREFIX"),
            _normalize_text(getattr(AppConfig, "OCI_SLIPS_CATEGORY_PREFIX", ""), "denpyo-category"),
        ).strip("/")
        return object_prefix or "denpyo-category"

    object_prefix = _normalize_text(
        os.environ.get("OCI_SLIPS_RAW_PREFIX"),
        _normalize_text(getattr(AppConfig, "OCI_SLIPS_RAW_PREFIX", ""), "denpyo-raw"),
    ).strip("/")
    return object_prefix or "denpyo-raw"


def _safe_cleanup_uploaded_artifact(
    storage_service,
    db_service,
    upload_kind: str,
    object_name: str = "",
    file_id: Optional[int] = None,
    slip_id: Optional[int] = None,
) -> None:
    """上传后续处理失败时，尽力回滚 Object Storage 与 DB 记录。"""
    normalized_object_name = _normalize_text(object_name)

    if normalized_object_name:
        try:
            rollback_result = storage_service.delete_file(normalized_object_name)
            if rollback_result.get("success"):
                logging.info("files/upload 回滚成功: object=%s", normalized_object_name)
            else:
                logging.warning(
                    "files/upload 回滚失败: object=%s message=%s",
                    normalized_object_name,
                    rollback_result.get("message", ""),
                )
        except Exception as rollback_error:
            logging.warning(
                "files/upload 回滚异常: object=%s error=%s",
                normalized_object_name,
                rollback_error,
                exc_info=True,
            )

    delete_file_record = getattr(db_service, "delete_file_record", None)
    if file_id is not None and callable(delete_file_record):
        try:
            delete_result = delete_file_record(file_id)
            if delete_result.get("success"):
                logging.info("files/upload DB回滚成功: file_id=%s", file_id)
            else:
                logging.warning(
                    "files/upload DB回滚失敗: file_id=%s message=%s",
                    file_id,
                    delete_result.get("message", ""),
                )
        except Exception as rollback_error:
            logging.warning(
                "files/upload DB回滚異常: file_id=%s error=%s",
                file_id,
                rollback_error,
                exc_info=True,
            )

    needs_slip_cleanup = slip_id is not None and (file_id is None or _normalize_text(upload_kind).lower() == "category")
    delete_slip_record = getattr(db_service, "delete_slip_record", None)
    if needs_slip_cleanup and callable(delete_slip_record):
        try:
            delete_result = delete_slip_record(upload_kind, slip_id)
            if delete_result.get("success"):
                logging.info("files/upload SLIPS回滚成功: kind=%s slip_id=%s", upload_kind, slip_id)
            else:
                logging.warning(
                    "files/upload SLIPS回滚失敗: kind=%s slip_id=%s message=%s",
                    upload_kind,
                    slip_id,
                    delete_result.get("message", ""),
                )
        except Exception as rollback_error:
            logging.warning(
                "files/upload SLIPS回滚異常: kind=%s slip_id=%s error=%s",
                upload_kind,
                slip_id,
                rollback_error,
                exc_info=True,
            )


def _upload_single_document(
    *,
    storage_service,
    db_service,
    doc_processor,
    filename: str,
    file_data: bytes,
    upload_kind: str,
    user: str,
    bucket_name: str,
    namespace: str,
    read_elapsed: float = 0.0,
    content_type_override: str = "",
    skip_validation: bool = False,
) -> Dict[str, Any]:
    object_name = ""
    file_id = None
    slip_id = None
    file_started_at = time.time()
    validate_elapsed = 0.0

    try:
        if not skip_validation:
            validate_started_at = time.time()
            validation = doc_processor.validate_file(filename, file_data)
            validate_elapsed = time.time() - validate_started_at
            if not validation.get("valid"):
                logging.warning(
                    "files/upload バリデーションNG: name=%s size=%d read=%.2fs validate=%.2fs",
                    filename, len(file_data), read_elapsed, validate_elapsed
                )
                return {
                    "success": False,
                    "error": f"{filename}: {validation.get('message', '無効なファイル')}",
                }

        content_type = content_type_override or doc_processor.detect_content_type(filename, file_data)
        object_name = doc_processor.generate_object_name(
            filename,
            prefix=_resolve_upload_object_prefix(upload_kind),
        )

        upload_started_at = time.time()
        upload_result = storage_service.upload_file(
            object_name=object_name,
            file_data=file_data,
            content_type=content_type,
            original_filename=filename,
        )
        upload_elapsed = time.time() - upload_started_at
        if not upload_result.get("success"):
            logging.error(
                "files/upload ObjectStorage NG: name=%s object=%s size=%d read=%.2fs validate=%.2fs upload=%.2fs err=%s",
                filename, object_name, len(file_data), read_elapsed, validate_elapsed, upload_elapsed,
                upload_result.get("message", "")
            )
            return {
                "success": False,
                "error": f"{filename}: {upload_result.get('message', 'アップロード失敗')}",
            }

        slip_db_started_at = time.time()
        slip_id = db_service.insert_slip_record(
            slip_kind=upload_kind,
            object_name=object_name,
            bucket_name=bucket_name,
            namespace=namespace,
            file_name=filename,
            file_size_bytes=len(file_data),
            content_type=content_type,
        )
        slip_db_elapsed = time.time() - slip_db_started_at
        if slip_id is None:
            logging.error(
                "files/upload SLIPS登録NG: name=%s object=%s size=%d read=%.2fs validate=%.2fs upload=%.2fs slips_db=%.2fs",
                filename, object_name, len(file_data), read_elapsed, validate_elapsed, upload_elapsed, slip_db_elapsed
            )
            _safe_cleanup_uploaded_artifact(
                storage_service=storage_service,
                db_service=db_service,
                upload_kind=upload_kind,
                object_name=object_name,
            )
            return {
                "success": False,
                "error": f"{filename}: SLIPS テーブル登録失敗",
            }

        db_started_at = time.time()
        file_id = db_service.insert_file_record(
            file_name=object_name,
            original_file_name=filename,
            object_storage_path=object_name,
            content_type=content_type,
            file_size=len(file_data),
            uploaded_by=user,
        )
        db_elapsed = time.time() - db_started_at
        if file_id is None:
            logging.error(
                "files/upload DB登録NG: name=%s object=%s size=%d read=%.2fs validate=%.2fs upload=%.2fs db=%.2fs",
                filename, object_name, len(file_data), read_elapsed, validate_elapsed, upload_elapsed, db_elapsed
            )
            _safe_cleanup_uploaded_artifact(
                storage_service=storage_service,
                db_service=db_service,
                upload_kind=upload_kind,
                object_name=object_name,
                slip_id=slip_id,
            )
            return {
                "success": False,
                "error": f"{filename}: データベース登録失敗",
            }

        db_service.log_activity(
            activity_type="UPLOAD",
            description=f"ファイル '{filename}' をアップロードしました",
            file_id=file_id,
            user_name=user,
        )

        uploaded_file = {
            "file_id": str(file_id),
            "file_name": object_name,
            "original_file_name": filename,
            "file_type": content_type,
            "file_size": len(file_data),
            "uploaded_at": dt.datetime.now().isoformat(),
            "status": "UPLOADED",
        }
        logging.info(
            "files/upload 完了: name=%s object=%s file_id=%s slip_id=%s size=%d read=%.2fs validate=%.2fs upload=%.2fs slips_db=%.2fs db=%.2fs total=%.2fs",
            filename, object_name, file_id, slip_id, len(file_data),
            read_elapsed, validate_elapsed, upload_elapsed, slip_db_elapsed, db_elapsed, time.time() - file_started_at
        )
        return {
            "success": True,
            "uploaded_file": uploaded_file,
            "artifact": {
                "object_name": object_name,
                "file_id": file_id,
                "slip_id": slip_id,
            },
        }
    except Exception as e:
        logging.error("ファイルアップロードエラー (%s): %s", filename, e, exc_info=True)
        if object_name:
            _safe_cleanup_uploaded_artifact(
                storage_service=storage_service,
                db_service=db_service,
                upload_kind=upload_kind,
                object_name=object_name,
                file_id=file_id,
                slip_id=slip_id,
            )
        return {"success": False, "error": f"{filename}: {str(e)}"}


@api_blueprint.route("/api/v1/files/upload", methods=["POST"])
def upload_files():
    """伝票ファイルのアップロード（multipart/form-data）"""
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.database_service import DatabaseService
    from denpyo_toroku.app.services.document_processor import DocumentProcessor

    uploaded_files = []
    errors = []
    batch_started_at = time.time()

    files = request.files.getlist("files")
    upload_kind = _normalize_text(request.form.get("upload_kind"), "raw").lower()
    if upload_kind not in ("raw", "category"):
        g.response.set_data({
            "success": False,
            "uploaded_files": [],
            "errors": ["upload_kind は 'raw' または 'category' を指定してください"],
        })
        return jsonify(g.response.get_result()), 400

    if not files or (len(files) == 1 and files[0].filename == ""):
        g.response.set_data({"success": False, "uploaded_files": [], "errors": ["ファイルが選択されていません"]})
        return jsonify(g.response.get_result()), 400

    storage_service = OCIStorageService()
    db_service = DatabaseService()
    doc_processor = DocumentProcessor(max_size_mb=AppConfig.UPLOAD_MAX_SIZE_MB)

    if not storage_service.is_configured:
        g.response.set_data({"success": False, "uploaded_files": [], "errors": ["OCI Object Storage が未設定です"]})
        return jsonify(g.response.get_result()), 400

    user = session.get("user", "")
    bucket_name = _normalize_text(getattr(storage_service, "_bucket_name", ""))
    namespace = _normalize_text(getattr(storage_service, "_namespace", ""))
    logging.info(
        "files/upload 開始: files=%d user=%s kind=%s ns=%s bucket=%s",
        len(files), user, upload_kind, namespace, bucket_name
    )

    for f in files:
        filename = f.filename or ""
        read_started_at = time.time()
        file_data = f.read()
        read_elapsed = time.time() - read_started_at

        upload_result = _upload_single_document(
            storage_service=storage_service,
            db_service=db_service,
            doc_processor=doc_processor,
            filename=filename,
            file_data=file_data,
            upload_kind=upload_kind,
            user=user,
            bucket_name=bucket_name,
            namespace=namespace,
            read_elapsed=read_elapsed,
        )
        if upload_result.get("success"):
            uploaded_files.append(upload_result["uploaded_file"])
        else:
            errors.append(upload_result.get("error", f"{filename}: アップロードに失敗しました"))

    success = len(uploaded_files) > 0
    g.response.set_data({
        "success": success,
        "uploaded_files": uploaded_files,
        "errors": errors,
    })
    logging.info(
        "files/upload 終了: uploaded=%d errors=%d elapsed=%.2fs",
        len(uploaded_files), len(errors), time.time() - batch_started_at
    )
    return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/files", methods=["GET"])
def list_files():
    """伝票ファイル一覧を取得（ページング + フィルタ）"""
    from denpyo_toroku.app.services.database_service import DatabaseService

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(100, max(1, request.args.get("page_size", 20, type=int)))
    status = request.args.get("status", None, type=str)
    upload_kind = _normalize_text(request.args.get("upload_kind"), "").lower()
    if upload_kind and upload_kind not in ("raw", "category"):
        upload_kind = ""
    if status == "":
        status = None

    offset = (page - 1) * page_size

    try:
        db_service = DatabaseService()
        files = db_service.get_files(status=status, limit=page_size, offset=offset, upload_kind=upload_kind or None)
        files = [_decorate_analysis_status(file_record) for file_record in files]
        total = db_service.get_files_count(status=status, upload_kind=upload_kind or None)
        total_pages = max(1, (total + page_size - 1) // page_size)

        g.response.set_data({
            "files": files,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })
    except Exception as e:
        logging.error("ファイル一覧取得エラー: %s", e, exc_info=True)
        g.response.set_data({
            "files": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
        })

    return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/files/<int:file_id>", methods=["GET"])
def get_file_detail(file_id: int):
    """伝票ファイル詳細を取得"""
    from denpyo_toroku.app.services.database_service import DatabaseService

    try:
        db_service = DatabaseService()
        file_record = db_service.get_file_by_id(file_id)
        if not file_record:
            g.response.add_error_message("ファイルが見つかりません")
            return jsonify(g.response.get_result()), 404
        _decorate_analysis_status(file_record)

        g.response.set_data({
            "file_id": str(file_record.get("id")),
            "file_name": file_record.get("file_name", ""),
            "original_file_name": file_record.get("original_file_name", ""),
            "storage_path": file_record.get("object_storage_path", ""),
            "file_type": file_record.get("content_type", ""),
            "file_size": file_record.get("file_size", 0),
            "status": file_record.get("status", ""),
            "analysis_kind": file_record.get("analysis_kind", ""),
            "has_analysis_result": bool(file_record.get("has_analysis_result")),
            "analyzed_at": file_record.get("analyzed_at", ""),
            "updated_at": file_record.get("updated_at", ""),
            "uploaded_by": file_record.get("uploaded_by", ""),
            "uploaded_at": file_record.get("uploaded_at", ""),
            "status_detail": file_record.get("status_detail", ""),
            "is_analysis_stalled": bool(file_record.get("is_analysis_stalled")),
            "can_retry_analysis": bool(file_record.get("can_retry_analysis")),
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("ファイル詳細取得エラー (id=%s): %s", file_id, e, exc_info=True)
        g.response.add_error_message(f"ファイル詳細の取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/files/<int:file_id>/analysis-result", methods=["GET"])
def get_file_analysis_result(file_id: int):
    """保存済みの AI 分析結果を取得"""
    try:
        db_service = DatabaseService()
        file_record = db_service.get_file_by_id(file_id)
        if file_record:
            _decorate_analysis_status(file_record)
            analysis_result = db_service.get_analysis_result(file_id)
            if not analysis_result:
                if file_record.get("is_analysis_stalled"):
                    g.response.add_error_message("AI分析が長時間完了していません。再分析してください")
                    return jsonify(g.response.get_result()), 409
                if file_record.get("status") == "ANALYZING":
                    g.response.add_error_message("AI分析はまだ完了していません")
                    return jsonify(g.response.get_result()), 409
                g.response.add_error_message("分析結果がありません")
                return jsonify(g.response.get_result()), 404

            g.response.set_data(analysis_result)
            return jsonify(g.response.get_result())

        slips_category_records = db_service.get_slips_category_files_by_ids([file_id])
        if not slips_category_records:
            g.response.add_error_message("ファイルが見つかりません")
            return jsonify(g.response.get_result()), 404

        slips_category_record = slips_category_records[0]
        _decorate_analysis_status(slips_category_record)
        analysis_result = db_service.get_slips_category_analysis_result(file_id)
        if not analysis_result:
            if slips_category_record.get("is_analysis_stalled"):
                g.response.add_error_message("AI分析が長時間完了していません。再分析してください")
                return jsonify(g.response.get_result()), 409
            if slips_category_record.get("status") == "ANALYZING":
                g.response.add_error_message("AI分析はまだ完了していません")
                return jsonify(g.response.get_result()), 409
            g.response.add_error_message("分析結果がありません")
            return jsonify(g.response.get_result()), 404

        g.response.set_data(analysis_result)
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("分析結果取得エラー (id=%s): %s", file_id, e, exc_info=True)
        g.response.add_error_message(f"分析結果の取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/files/<int:file_id>/preview", methods=["GET"])
def preview_file(file_id: int):
    """伝票ファイルのプレビューを返す（Object Storage から取得）"""
    from denpyo_toroku.app.services.database_service import DatabaseService
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService

    try:
        db_service = DatabaseService()
        # フロントエンドは常に DENPYO_FILES.ID を送信するため、
        # upload_kind に関わらず DENPYO_FILES から取得する
        file_record = db_service.get_file_by_id(file_id)

        if not file_record:
            g.response.add_error_message("ファイルが見つかりません")
            return jsonify(g.response.get_result()), 404

        storage_path = file_record.get("object_storage_path", "")
        if not storage_path:
            g.response.add_error_message("ファイルの保存先情報がありません")
            return jsonify(g.response.get_result()), 400

        storage_service = OCIStorageService()
        content = storage_service.download_file(storage_path)
        if content is None:
            g.response.add_error_message("ファイルプレビューの取得に失敗しました")
            return jsonify(g.response.get_result()), 500

        response = make_response(content)
        response.headers["Content-Type"] = file_record.get("content_type", "application/octet-stream")
        preview_name = file_record.get("original_file_name") or f"file_{file_id}"
        response.headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(preview_name)}"
        return response
    except Exception as e:
        logging.error("ファイルプレビュー取得エラー (id=%s): %s", file_id, e, exc_info=True)
        g.response.add_error_message(f"ファイルプレビューの取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


def _load_preview_pages(file_id: int) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str], int]:
    """伝票ファイルをページ画像列として読み込む"""
    from denpyo_toroku.app.services.database_service import DatabaseService
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.document_processor import DocumentProcessor

    db_service = DatabaseService()
    file_record = db_service.get_file_by_id(file_id)
    if not file_record:
        return None, [], "ファイルが見つかりません", 404

    storage_path = file_record.get("object_storage_path", "")
    if not storage_path:
        return file_record, [], "ファイルの保存先情報がありません", 400

    storage_service = OCIStorageService()
    content = storage_service.download_file(storage_path)
    if content is None:
        return file_record, [], "ファイルプレビューの取得に失敗しました", 500

    doc_processor = DocumentProcessor(max_size_mb=AppConfig.UPLOAD_MAX_SIZE_MB)
    pages = doc_processor.prepare_document_pages(content, file_record.get("original_file_name", ""))
    if not pages:
        return file_record, [], "ページ画像を生成できませんでした", 500

    return file_record, pages, None, 200


@api_blueprint.route("/api/v1/files/<int:file_id>/preview-pages", methods=["GET"])
def preview_file_pages(file_id: int):
    """伝票ファイルをページ画像一覧として返す"""
    try:
        file_record, pages, error_message, status_code = _load_preview_pages(file_id)
        if error_message:
            g.response.add_error_message(error_message)
            return jsonify(g.response.get_result()), status_code

        preview_name = file_record.get("original_file_name") or file_record.get("file_name") or f"file_{file_id}"
        g.response.set_data({
            "file_id": str(file_id),
            "file_name": preview_name,
            "page_count": len(pages),
            "pages": [
                {
                    "page_index": page.get("page_index", index),
                    "page_label": page.get("page_label") or f"ページ {index + 1}",
                    "source_name": page.get("source_name") or preview_name,
                    "content_type": page.get("content_type", "image/jpeg"),
                }
                for index, page in enumerate(pages)
            ],
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("ファイルプレビュー一覧取得エラー (id=%s): %s", file_id, e, exc_info=True)
        g.response.add_error_message(f"ファイルプレビュー一覧の取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/files/<int:file_id>/preview-pages/<int:page_index>", methods=["GET"])
def preview_file_page_image(file_id: int, page_index: int):
    """伝票ファイルの指定ページ画像を返す"""
    try:
        file_record, pages, error_message, status_code = _load_preview_pages(file_id)
        if error_message:
            g.response.add_error_message(error_message)
            return jsonify(g.response.get_result()), status_code

        if page_index < 0 or page_index >= len(pages):
            g.response.add_error_message("指定されたページが見つかりません")
            return jsonify(g.response.get_result()), 404

        page = pages[page_index]
        content = page.get("image_data", b"")
        content_type = page.get("content_type", "image/jpeg")
        preview_name = file_record.get("original_file_name") or f"file_{file_id}"
        preview_stem = Path(preview_name).stem or f"file_{file_id}"
        preview_ext = ".jpg" if content_type in ("image/jpeg", "image/jpg") else ".png"
        rendered_name = f"{preview_stem}_page_{page_index + 1}{preview_ext}"

        response = make_response(content)
        response.headers["Content-Type"] = content_type
        response.headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(rendered_name)}"
        return response
    except Exception as e:
        logging.error("ファイルプレビュー画像取得エラー (id=%s, page=%s): %s", file_id, page_index, e, exc_info=True)
        g.response.add_error_message(f"ファイルプレビュー画像の取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/files/<int:file_id>", methods=["DELETE"])
def delete_file(file_id: int):
    """伝票ファイルを削除（Object Storage → DB の順で削除）"""
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.database_service import DatabaseService

    logging.info("========== ファイル削除開始 file_id=%s ==========", file_id)
    try:
        db_service = DatabaseService()
        logging.info("[STEP 1] ファイル情報をDBから取得中... file_id=%s", file_id)
        file_record = db_service.get_file_by_id(file_id)
        if not file_record:
            logging.warning("ファイルが見つかりません file_id=%s", file_id)
            g.response.set_data({"success": False, "message": "ファイルが見つかりません"})
            return jsonify(g.response.get_result()), 404
        
        logging.info("[STEP 1] ファイル情報取得成功: file_name=%s, storage_path=%s", 
                    file_record.get('original_file_name'), 
                    file_record.get('object_storage_path'))

        # ステップ2: Object Storage から削除
        storage_path = file_record.get("object_storage_path", "")
        storage_already_missing = False
        if storage_path:
            logging.info("[STEP 2] Object Storage から削除開始: %s", storage_path)
            storage_service = OCIStorageService()
            if storage_service.is_configured:
                logging.info("[STEP 2] OCI Storage Service 設定済み (namespace=%s, bucket=%s)",
                           storage_service._namespace, storage_service._bucket_name)
                storage_result = storage_service.delete_file(storage_path)
                logging.info("[STEP 2] Object Storage 削除結果: %s", storage_result)
                storage_already_missing = bool(storage_result.get("already_missing"))
                if not storage_result.get("success"):
                    # Object Storage 削除失敗時はエラーを返す
                    logging.error("[STEP 2] Object Storage 削除失敗: %s", storage_result.get('message'))
                    g.response.set_data({
                        "success": False,
                        "message": f"Object Storage からの削除に失敗しました: {storage_result.get('message')}"
                    })
                    return jsonify(g.response.get_result()), 500
                logging.info("[STEP 2] ✅ Object Storage からファイルを削除しました: %s", storage_path)
            else:
                logging.warning("[STEP 2] OCI Storage Service が設定されていません")
        else:
            logging.warning("[STEP 2] storage_path が空です（Object Storage 削除スキップ）")

        # ステップ3: DB レコード削除
        logging.info("[STEP 3] DB レコード削除開始 file_id=%s", file_id)
        delete_result = db_service.delete_file_record(file_id)
        logging.info("[STEP 3] DB 削除結果: %s", delete_result)
        if not delete_result.get("success"):
            # DB削除失敗（Object Storageは既に削除済み）
            logging.error(
                "[STEP 3] DB削除失敗（Object Storageは削除済み） file_id=%s: %s",
                file_id,
                delete_result.get("message")
            )
            g.response.set_data(delete_result)
            return jsonify(g.response.get_result()), 400
        
        logging.info("[STEP 3] ✅ DB レコードを削除しました file_id=%s", file_id)

        # アクティビティログ
        user = session.get("user", "")
        logging.info("[STEP 4] アクティビティログ記録中 user=%s", user)
        db_service.log_activity(
            activity_type="DELETE",
            description=f"ファイル '{file_record.get('original_file_name', '')}' を削除しました",
            user_name=user,
        )
        logging.info("[STEP 4] ✅ アクティビティログ記録完了")

        logging.info("========== ファイル削除成功 file_id=%s ==========", file_id)
        success_message = "ファイルを削除しました"
        if storage_path and storage_already_missing:
            success_message = "ファイルを削除しました（Object Storage 内でファイルは既に存在しませんでした）"
        g.response.set_data({"success": True, "message": success_message})
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("========== ファイル削除エラー file_id=%s ==========", file_id)
        logging.error("ファイル削除エラー (id=%s): %s", file_id, e, exc_info=True)
        g.response.set_data({"success": False, "message": str(e)})
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/files/bulk-delete", methods=["POST"])
def bulk_delete_files():
    """伝票ファイルを一括削除（各ファイルにつき Object Storage → DB の順で削除）"""
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.database_service import DatabaseService

    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("file_ids", [])
    if not isinstance(raw_ids, list) or not raw_ids:
        g.response.add_error_message("file_ids を配列で指定してください")
        return jsonify(g.response.get_result()), 400

    db_service = DatabaseService()
    storage_service = OCIStorageService()
    user = session.get("user", "")
    deleted_ids = []
    errors = []

    for raw_id in raw_ids:
        try:
            file_id = int(raw_id)
        except (TypeError, ValueError):
            errors.append(f"{raw_id}: 不正な file_id です")
            continue

        try:
            file_record = db_service.get_file_by_id(file_id)
            if file_record:
                # ステップ1: Object Storage から削除
                storage_path = file_record.get("object_storage_path", "")
                if storage_path and storage_service.is_configured:
                    storage_result = storage_service.delete_file(storage_path)
                    if not storage_result.get("success"):
                        errors.append(
                            f"{file_id}: Object Storage 削除失敗 - {storage_result.get('message')}"
                        )
                        continue
                    if storage_result.get("already_missing"):
                        logging.info(
                            "Object Storage 内でファイルは既に存在しません: %s",
                            storage_path,
                        )
                    logging.info("Object Storage からファイルを削除しました: %s", storage_path)

                # ステップ2: DB レコード削除
                delete_result = db_service.delete_file_record(file_id)
                if not delete_result.get("success"):
                    # DB削除失敗（Object Storageは既に削除済み）
                    logging.warning(
                        "DB削除失敗（Object Storageは削除済み） file_id=%s: %s",
                        file_id,
                        delete_result.get("message")
                    )
                    errors.append(f"{file_id}: {delete_result.get('message', '削除失敗')}")
                    continue

                db_service.log_activity(
                    activity_type="DELETE",
                    description=f"ファイル '{file_record.get('original_file_name', '')}' を削除しました",
                    user_name=user,
                )
                deleted_ids.append(str(file_id))
                continue

            # Fallback: SLIPS_CATEGORY の ID で削除リクエストされたケース
            slips_category_records = db_service.get_slips_category_files_by_ids([file_id])
            if not slips_category_records:
                errors.append(f"{file_id}: ファイルが見つかりません")
                continue

            slips_category_record = slips_category_records[0]
            storage_path = slips_category_record.get("object_name", "")
            if storage_path and storage_service.is_configured:
                storage_result = storage_service.delete_file(storage_path)
                if not storage_result.get("success"):
                    errors.append(
                        f"{file_id}: Object Storage 削除失敗 - {storage_result.get('message')}"
                    )
                    continue
                if storage_result.get("already_missing"):
                    logging.info(
                        "Object Storage 内で SLIPS_CATEGORY ファイルは既に存在しません: %s",
                        storage_path,
                    )
                logging.info("Object Storage から SLIPS_CATEGORY ファイルを削除しました: %s", storage_path)

            delete_result = db_service.delete_slips_category_file_record(file_id)
            if not delete_result.get("success"):
                errors.append(f"{file_id}: {delete_result.get('message', '削除失敗')}")
                continue

            db_service.log_activity(
                activity_type="DELETE",
                description=f"SLIPS_CATEGORY ファイル '{slips_category_record.get('file_name', '')}' を削除しました",
                user_name=user,
            )
            deleted_ids.append(str(file_id))
        except Exception as e:
            logging.error("一括削除エラー (id=%s): %s", raw_id, e, exc_info=True)
            errors.append(f"{raw_id}: {str(e)}")

    g.response.set_data({
        "success": len(deleted_ids) > 0 and len(errors) == 0,
        "deleted_file_ids": deleted_ids,
        "errors": errors,
    })
    return jsonify(g.response.get_result())


def _write_image_tempfiles(images: List[Any]) -> List[str]:
    """画像列を /tmp に保存して OCR 入力用パス一覧を返す"""
    tmp_paths: List[str] = []
    for image_data, content_type in images:
        suffix = ".jpg" if content_type in ("image/jpeg", "image/jpg") else ".png"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir="/tmp")
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(image_data)
        tmp_paths.append(tmp_path)
    return tmp_paths


def _cleanup_tempfiles(paths: List[str]) -> None:
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as cleanup_error:
            logging.warning("一時ファイルの削除に失敗しました: %s, error=%s", path, cleanup_error)


def _queue_raw_file_analysis(file_id: int, category_id: int, user_name: str) -> None:
    """本登録用伝票の AI 分析をバックグラウンド実行する"""
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.document_processor import DocumentProcessor
    from denpyo_toroku.app.services.ai_service import AIService

    db_service = DatabaseService()

    try:
        category = db_service.get_category_by_id(category_id)
        if not category:
            raise ValueError("指定カテゴリが見つかりません")
        if not category.get("is_active", False):
            raise ValueError("指定カテゴリは無効です")

        table_schema = db_service.get_category_table_schema(category_id)
        if not table_schema:
            logging.warning(
                "カテゴリ構造の取得に失敗したため、テーブル名のみで分析を継続します (category_id=%s)",
                category_id,
            )
            table_schema = {
                "header_table_name": category.get("header_table_name", ""),
                "line_table_name": category.get("line_table_name", ""),
                "header_columns": [],
                "line_columns": [],
            }

        file_record = db_service.get_file_by_id(file_id)
        if not file_record:
            raise ValueError("ファイルが見つかりません")
        storage_path = file_record.get("object_storage_path", "")
        if not storage_path:
            raise ValueError("ストレージパスが設定されていません")

        storage_service = OCIStorageService()
        file_data = storage_service.download_file(storage_path)
        if not file_data:
            raise ValueError("Object Storage からファイルをダウンロードできませんでした")

        doc_processor = DocumentProcessor()
        images = doc_processor.prepare_for_ai(file_data, file_record.get("original_file_name", ""))
        if not images:
            raise ValueError("ファイルをAI分析用に変換できませんでした")

        ai_service = AIService()
        tmp_paths: List[str] = []
        try:
            tmp_paths = _write_image_tempfiles(images)
            ocr_result = ai_service.extract_text_from_images(tmp_paths)
            if not ocr_result.get("success"):
                raise ValueError(f"テキスト抽出に失敗しました: {ocr_result.get('message')}")
            extracted_text = ocr_result.get("extracted_text", "")
        finally:
            _cleanup_tempfiles(tmp_paths)

        extraction = ai_service.extract_data_from_text(
            ocr_text=extracted_text,
            category=category.get("category_name", ""),
            table_schema={
                "header_table_name": table_schema.get("header_table_name", ""),
                "line_table_name": table_schema.get("line_table_name", ""),
                "header_columns": table_schema.get("header_columns", []),
                "line_columns": table_schema.get("line_columns", []),
            },
        )
        if not extraction.get("success"):
            raise ValueError(extraction.get("message", "フィールド抽出に失敗しました"))

        result = {
            "file_id": str(file_id),
            "file_name": file_record.get("original_file_name", ""),
            "status": "ANALYZED",
            "category_id": category_id,
            "classification": {
                "category": category.get("category_name", ""),
                "confidence": 1.0,
                "description": "選択カテゴリを適用",
                "has_line_items": len(table_schema.get("line_columns", [])) > 0,
            },
            "extraction": {
                "header_fields": extraction.get("header_fields", []),
                "line_fields": extraction.get("line_fields", []),
                "line_count": extraction.get("line_count", 0),
                "raw_lines": extraction.get("raw_lines", []),
            },
            "ddl_suggestion": {
                "table_prefix": category.get("category_name_en", "") or "",
                "header_table_name": table_schema.get("header_table_name", ""),
                "line_table_name": table_schema.get("line_table_name", ""),
                "header_ddl": "",
                "line_ddl": "",
            },
            "table_schema": {
                "header_table_name": table_schema.get("header_table_name", ""),
                "line_table_name": table_schema.get("line_table_name", ""),
                "header_columns": table_schema.get("header_columns", []),
                "line_columns": table_schema.get("line_columns", []),
            },
        }

        if not db_service.save_analysis_result(file_id, "raw", result):
            raise RuntimeError("分析結果の保存に失敗しました")

        db_service.update_file_status(file_id, "ANALYZED")
        db_service.log_activity(
            activity_type="ANALYZE_COMPLETE",
            description=(
                f"ファイル '{file_record.get('original_file_name', '')}' の分析が完了"
                f"（カテゴリ: {category.get('category_name', '')}）"
            ),
            file_id=file_id,
            user_name=user_name,
        )
    except Exception as e:
        logging.error("AI分析エラー (file_id=%s): %s", file_id, e, exc_info=True)
        db_service.update_file_status(file_id, "ERROR")
        db_service.log_activity(
            activity_type="ANALYZE_ERROR",
            description=f"分析エラー: {str(e)[:200]}",
            file_id=file_id,
            user_name=user_name,
        )


def _queue_category_slip_analysis(file_ids: List[int], analysis_mode: str, user_name: str) -> None:
    """分類用サンプル伝票の AI 分析をバックグラウンド実行する"""
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.document_processor import DocumentProcessor
    from denpyo_toroku.app.services.ai_service import AIService

    db_service = DatabaseService()
    tmp_filepaths: List[str] = []

    try:
        file_records = db_service.get_files_by_ids(file_ids)
        if not file_records:
            file_records = db_service.get_slips_category_files_by_ids(file_ids)
        if not file_records:
            raise ValueError("指定されたファイルが見つかりません")

        storage_service = OCIStorageService()
        doc_processor = DocumentProcessor()
        ai_service = AIService()
        processed_file_ids: List[int] = []
        for rec in file_records:
            object_name = rec.get("object_name", "")
            file_data = storage_service.download_file(object_name)
            if not file_data:
                logging.warning("ファイルダウンロード失敗: %s", object_name)
                continue

            images = doc_processor.prepare_for_ai(file_data, rec.get("original_file_name", ""))
            if not images:
                logging.warning("AI分析用画像の生成に失敗: %s", object_name)
                continue

            for image_data, img_content_type in images:
                suffix = ".jpg" if img_content_type in ("image/jpeg", "image/jpg") else ".png"
                fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir="/tmp")
                with os.fdopen(fd, "wb") as f:
                    f.write(image_data)
                tmp_filepaths.append(tmp_path)
            if rec.get("id"):
                processed_file_ids.append(rec.get("id"))

        if not tmp_filepaths:
            raise ValueError("処理できる画像ファイルがありませんでした")

        ocr_result = ai_service.extract_text_from_images(tmp_filepaths)
        if not ocr_result.get("success"):
            raise ValueError(f"テキスト抽出に失敗しました: {ocr_result.get('message')}")

        extracted_text = ocr_result.get("extracted_text", "")
        schema_result = ai_service.generate_sql_schema_from_text(extracted_text, analysis_mode)
        if not schema_result.get("success"):
            raise ValueError(f"AIによるスキーマ設計に失敗しました: {schema_result.get('message')}")

        def _merge_fields(fields_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            seen: Dict[str, Dict[str, Any]] = {}
            required_count: Dict[str, int] = {}
            appear_count: Dict[str, int] = {}
            for field in fields_list:
                raw_key = (field.get("field_name_en") or "").strip()
                if not raw_key:
                    continue
                key = raw_key.upper().replace(" ", "_").replace("-", "_")
                original_data_type = (field.get("data_type") or "VARCHAR2").upper()
                data_type = original_data_type
                if data_type not in ("VARCHAR2", "NUMBER", "DATE", "TIMESTAMP"):
                    data_type = "VARCHAR2"

                if key not in seen:
                    max_length = None
                    if data_type == "VARCHAR2":
                        try:
                            max_length = int(field.get("max_length")) if field.get("max_length") else 100
                        except (TypeError, ValueError):
                            max_length = 100
                        if original_data_type == "CLOB" and not field.get("max_length"):
                            max_length = 4000
                    seen[key] = {
                        "column_name": key,
                        "column_name_jp": field.get("field_name") or raw_key,
                        "data_type": data_type,
                        "max_length": max_length,
                        "precision": None,
                        "scale": None,
                        "is_nullable": True,
                        "is_primary_key": False,
                    }
                    appear_count[key] = 1
                    required_count[key] = 1 if field.get("is_required") else 0
                    continue

                existing_type = seen[key].get("data_type", "VARCHAR2")
                if existing_type != data_type:
                    seen[key]["data_type"] = "VARCHAR2"
                    if not seen[key].get("max_length"):
                        seen[key]["max_length"] = 100
                    data_type = "VARCHAR2"

                if data_type == "VARCHAR2":
                    existing_len = seen[key].get("max_length") or 100
                    try:
                        new_len = int(field.get("max_length")) if field.get("max_length") else 100
                    except (TypeError, ValueError):
                        new_len = 100
                    if original_data_type == "CLOB" and not field.get("max_length"):
                        new_len = 4000
                    seen[key]["max_length"] = max(existing_len, new_len)
                appear_count[key] += 1
                if field.get("is_required"):
                    required_count[key] += 1

            for key in seen:
                if required_count.get(key, 0) == appear_count.get(key, 0) and appear_count.get(key, 0) > 0:
                    seen[key]["is_nullable"] = False

            return list(seen.values())

        header_columns = _merge_fields(schema_result.get("header_fields", []))
        if not header_columns:
            raise ValueError("分析できるファイルがありませんでした")

        line_columns = _merge_fields(schema_result.get("line_fields", [])) if analysis_mode == "header_line" else []
        category_guess = (schema_result.get("document_type_ja") or "").strip() or "伝票"
        category_map = {
            "請求書": "invoice",
            "領収書": "receipt",
            "納品書": "delivery_note",
            "注文書": "purchase_order",
            "見積書": "quotation",
            "発注書": "order_sheet",
        }
        llm_doc_type_en = re.sub(
            r"[^a-z0-9_]+",
            "_",
            (schema_result.get("document_type_en") or "").strip().lower(),
        ).strip("_")
        category_guess_en = llm_doc_type_en or category_map.get(category_guess, "slip")
        analyzed_file_ids = list(dict.fromkeys(processed_file_ids))
        result = {
            "category_guess": category_guess,
            "category_guess_en": category_guess_en,
            "analysis_mode": analysis_mode,
            "header_columns": header_columns,
            "line_columns": line_columns,
            "analyzed_file_ids": analyzed_file_ids,
        }

        for file_id in list(dict.fromkeys(file_ids)):
            if not db_service.save_category_analysis_result(file_id, result):
                raise RuntimeError(f"分析結果の保存に失敗しました (file_id={file_id})")
            db_service.update_file_status(file_id, "ANALYZED")
            db_service.update_category_file_status(file_id, "ANALYZED")
            db_service.log_activity(
                activity_type="CATEGORY_ANALYZE_COMPLETE",
                description=f"分類用サンプル伝票の分析が完了しました (file_id={file_id})",
                file_id=file_id,
                user_name=user_name,
            )
    except Exception as e:
        logging.error("分類用サンプル伝票のAI分析エラー (file_ids=%s): %s", file_ids, e, exc_info=True)
        for file_id in file_ids:
            db_service.update_file_status(file_id, "ERROR")
            db_service.update_category_file_status(file_id, "ERROR")
            db_service.log_activity(
                activity_type="CATEGORY_ANALYZE_ERROR",
                description=f"分類用サンプル伝票の分析エラー: {str(e)[:200]}",
                file_id=file_id,
                user_name=user_name,
            )
    finally:
        for path in tmp_filepaths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as cleanup_error:
                logging.warning("一時ファイルの削除に失敗しました: %s, error=%s", path, cleanup_error)


@api_blueprint.route("/api/v1/files/<int:file_id>/analyze", methods=["POST"])
def analyze_file(file_id: int):
    """伝票ファイルをAI分析する（カテゴリ指定 + フィールド抽出）"""
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.database_service import DatabaseService
    from denpyo_toroku.app.services.document_processor import DocumentProcessor
    from denpyo_toroku.app.services.ai_service import AIService

    db_service = DatabaseService()
    user = session.get("user", "")

    try:
        body = request.get_json(silent=True) or {}
        run_async = _to_bool(body.get("async"), False)
        raw_category_id = body.get("category_id")
        try:
            category_id = int(raw_category_id)
        except (TypeError, ValueError):
            g.response.set_data({"success": False, "message": "category_id は必須です"})
            return jsonify(g.response.get_result()), 400

        category = db_service.get_category_by_id(category_id)
        if not category:
            g.response.set_data({"success": False, "message": "指定カテゴリが見つかりません"})
            return jsonify(g.response.get_result()), 404
        if not category.get("is_active", False):
            g.response.set_data({"success": False, "message": "指定カテゴリは無効です"})
            return jsonify(g.response.get_result()), 400

        table_schema = db_service.get_category_table_schema(category_id)
        if not table_schema:
            logging.warning(
                "カテゴリ構造の取得に失敗したため、テーブル名のみで分析を継続します (category_id=%s)",
                category_id,
            )
            table_schema = {
                "header_table_name": category.get("header_table_name", ""),
                "line_table_name": category.get("line_table_name", ""),
                "header_columns": [],
                "line_columns": [],
            }

        # 1. ファイル取得
        file_record = db_service.get_file_by_id(file_id)
        if not file_record:
            g.response.set_data({"success": False, "message": "ファイルが見つかりません"})
            return jsonify(g.response.get_result()), 404
        _decorate_analysis_status(file_record)
        # 2. ステータスチェック（UPLOADED / ERROR / ANALYZED または停滞した ANALYZING のみ再分析可能）
        current_status = _normalize_text(file_record.get("status"), "").upper()
        if current_status == "ANALYZING" and not file_record.get("is_analysis_stalled"):
            g.response.set_data({
                "success": False,
                "message": "このファイルは現在分析中です。しばらく待ってから再取得してください"
            })
            return jsonify(g.response.get_result()), 400
        if current_status not in ("UPLOADED", "ERROR", "ANALYZED", "ANALYZING"):
            g.response.set_data({
                "success": False,
                "message": f"このファイルは分析できません（現在のステータス: {current_status}）"
            })
            return jsonify(g.response.get_result()), 400

        if run_async:
            db_service.update_file_status(file_id, "ANALYZING")
            db_service.log_activity(
                activity_type="ANALYZE_START",
                description=f"ファイル '{file_record.get('original_file_name', '')}' の分析を開始",
                file_id=file_id,
                user_name=user,
            )
            _ANALYSIS_EXECUTOR.submit(_queue_raw_file_analysis, file_id, category_id, user)
            g.response.set_data({
                "file_id": str(file_id),
                "status": "ANALYZING",
                "queued": True,
                "message": "AI分析を受け付けました",
            })
            return jsonify(g.response.get_result()), 202

        # 3. ステータスを ANALYZING に更新
        db_service.update_file_status(file_id, "ANALYZING")
        db_service.log_activity(
            activity_type="ANALYZE_START",
            description=f"ファイル '{file_record.get('original_file_name', '')}' の分析を開始",
            file_id=file_id, user_name=user,
        )

        # 4. Object Storage からファイルをダウンロード
        storage_path = file_record.get("object_storage_path", "")
        if not storage_path:
            db_service.update_file_status(file_id, "ERROR")
            g.response.set_data({"success": False, "message": "ストレージパスが設定されていません"})
            return jsonify(g.response.get_result()), 500

        storage_service = OCIStorageService()
        file_data = storage_service.download_file(storage_path)
        if not file_data:
            db_service.update_file_status(file_id, "ERROR")
            g.response.set_data({"success": False, "message": "Object Storage からファイルをダウンロードできませんでした"})
            return jsonify(g.response.get_result()), 500

        # 5. AI分析用にページ画像を準備
        doc_processor = DocumentProcessor()
        images = doc_processor.prepare_for_ai(file_data, file_record.get("original_file_name", ""))
        if not images:
            db_service.update_file_status(file_id, "ERROR")
            g.response.set_data({"success": False, "message": "ファイルをAI分析用に変換できませんでした"})
            return jsonify(g.response.get_result()), 500

        ai_service = AIService()

        # 6. VLM経由でのOCRテキスト抽出（ページごとに実行し、最後に結合）
        tmp_paths: List[str] = []
        try:
            tmp_paths = _write_image_tempfiles(images)
            ocr_result = ai_service.extract_text_from_images(tmp_paths)
            if not ocr_result.get("success"):
                db_service.update_file_status(file_id, "ERROR")
                g.response.set_data({"success": False, "message": f"テキスト抽出に失敗しました: {ocr_result.get('message')}"})
                return jsonify(g.response.get_result()), 500

            extracted_text = ocr_result.get("extracted_text", "")
        finally:
            _cleanup_tempfiles(tmp_paths)

        # 7. AI抽出（カテゴリ構造を指定してLLMでデータ生成）
        extraction = ai_service.extract_data_from_text(
            ocr_text=extracted_text,
            category=category.get("category_name", ""),
            table_schema={
                "header_table_name": table_schema.get("header_table_name", ""),
                "line_table_name": table_schema.get("line_table_name", ""),
                "header_columns": table_schema.get("header_columns", []),
                "line_columns": table_schema.get("line_columns", []),
            },
        )
        if not extraction.get("success"):
            db_service.update_file_status(file_id, "ERROR")
            g.response.set_data({
                "success": False,
                "message": extraction.get("message", "フィールド抽出に失敗しました")
            })
            return jsonify(g.response.get_result()), 500

        # 7. DDL提案（既存カテゴリテーブルをそのまま提示）
        header_fields = extraction.get("header_fields", [])
        line_fields = extraction.get("line_fields", [])
        ddl_suggestion = {
            "table_prefix": category.get("category_name_en", "") or "",
            "header_table_name": table_schema.get("header_table_name", ""),
            "line_table_name": table_schema.get("line_table_name", ""),
            "header_ddl": "",
            "line_ddl": "",
        }

        # 8. ステータスを ANALYZED に更新
        db_service.update_file_status(file_id, "ANALYZED")
        db_service.log_activity(
            activity_type="ANALYZE_COMPLETE",
            description=(
                f"ファイル '{file_record.get('original_file_name', '')}' の分析が完了"
                f"（カテゴリ: {category.get('category_name', '')}）"
            ),
            file_id=file_id, user_name=user,
        )

        # 9. レスポンス構築
        result = {
            "file_id": str(file_id),
            "file_name": file_record.get("original_file_name", ""),
            "status": "ANALYZED",
            "category_id": category_id,
            "classification": {
                "category": category.get("category_name", ""),
                "confidence": 1.0,
                "description": "選択カテゴリを適用",
                "has_line_items": len(table_schema.get("line_columns", [])) > 0,
            },
            "extraction": {
                "header_fields": header_fields,
                "line_fields": line_fields,
                "line_count": extraction.get("line_count", 0),
                "raw_lines": extraction.get("raw_lines", []),
            },
            "ddl_suggestion": {
                "table_prefix": ddl_suggestion.get("table_prefix", ""),
                "header_table_name": ddl_suggestion.get("header_table_name", ""),
                "line_table_name": ddl_suggestion.get("line_table_name", ""),
                "header_ddl": ddl_suggestion.get("header_ddl", ""),
                "line_ddl": ddl_suggestion.get("line_ddl", ""),
            },
            "table_schema": {
                "header_table_name": table_schema.get("header_table_name", ""),
                "line_table_name": table_schema.get("line_table_name", ""),
                "header_columns": table_schema.get("header_columns", []),
                "line_columns": table_schema.get("line_columns", []),
            },
        }

        if not db_service.save_analysis_result(file_id, "raw", result):
            raise RuntimeError("分析結果の保存に失敗しました")

        g.response.set_data(result)
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("AI分析エラー (file_id=%s): %s", file_id, e, exc_info=True)
        db_service.update_file_status(file_id, "ERROR")
        db_service.log_activity(
            activity_type="ANALYZE_ERROR",
            description=f"分析エラー: {str(e)[:200]}",
            file_id=file_id, user_name=user,
        )
        g.response.set_data({"success": False, "message": f"AI分析に失敗しました: {str(e)}"})
        return jsonify(g.response.get_result()), 500


# --- DDL バリデーション ヘルパー ---
_DDL_FORBIDDEN_KEYWORDS = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE)\b',
    re.IGNORECASE,
)

_TABLE_NAME_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,127}$')


def _validate_ddl(ddl: str) -> Optional[str]:
    """DDL文を検証し、問題があればエラーメッセージを返す"""
    stripped = ddl.strip()
    if not stripped.upper().startswith("CREATE TABLE"):
        return "DDLは CREATE TABLE で始まる必要があります"
    if _DDL_FORBIDDEN_KEYWORDS.search(stripped):
        return "DDLに禁止キーワードが含まれています"
    return None


@api_blueprint.route("/api/v1/files/<int:file_id>/register", methods=["POST"])
def register_file(file_id: int):
    """DB登録: DDL実行 + カテゴリ登録 + 登録レコード作成"""
    db_service = DatabaseService()
    user = session.get("user", "")

    # --- ファイル存在確認 ---
    file_record = db_service.get_file_by_id(file_id)
    if not file_record:
        g.response.set_data({"success": False, "message": "ファイルが見つかりません"})
        return jsonify(g.response.get_result()), 404

    current_status = file_record.get("status", "")
    if current_status != "ANALYZED":
        g.response.set_data({
            "success": False,
            "message": f"ステータスが ANALYZED のファイルのみ登録できます (現在: {current_status})"
        })
        return jsonify(g.response.get_result()), 400

    # --- リクエスト解析 ---
    body = request.get_json(silent=True) or {}
    category_name = (body.get("category_name") or "").strip()
    category_name_en = (body.get("category_name_en") or "").strip()
    category_id = body.get("category_id")
    header_table_name = (body.get("header_table_name") or "").strip()
    line_table_name = (body.get("line_table_name") or "").strip()
    header_ddl = (body.get("header_ddl") or "").strip()
    line_ddl = (body.get("line_ddl") or "").strip()
    ai_confidence = body.get("ai_confidence", 0)
    line_count = body.get("line_count", 0)
    # 抽出データ（データINSERT用）
    header_fields = body.get("header_fields", [])
    raw_lines = body.get("raw_lines", [])

    # --- 必須フィールド ---
    missing = []
    if not category_name:
        missing.append("category_name")
    if not header_table_name:
        missing.append("header_table_name")
    if missing:
        g.response.set_data({
            "success": False,
            "message": f"必須フィールドが不足しています: {', '.join(missing)}"
        })
        return jsonify(g.response.get_result()), 400

    # --- テーブル名バリデーション ---
    if not _TABLE_NAME_PATTERN.match(header_table_name):
        g.response.set_data({
            "success": False,
            "message": f"ヘッダーテーブル名が不正です: {header_table_name}"
        })
        return jsonify(g.response.get_result()), 400
    if line_table_name and not _TABLE_NAME_PATTERN.match(line_table_name):
        g.response.set_data({
            "success": False,
            "message": f"明細テーブル名が不正です: {line_table_name}"
        })
        return jsonify(g.response.get_result()), 400

    # --- DDL バリデーション ---
    if header_ddl:
        header_ddl_error = _validate_ddl(header_ddl)
        if header_ddl_error:
            g.response.set_data({
                "success": False,
                "message": f"ヘッダーDDLエラー: {header_ddl_error}"
            })
            return jsonify(g.response.get_result()), 400
    if line_ddl:
        line_ddl_error = _validate_ddl(line_ddl)
        if line_ddl_error:
            g.response.set_data({
                "success": False,
                "message": f"明細DDLエラー: {line_ddl_error}"
            })
            return jsonify(g.response.get_result()), 400

    try:
        # --- ヘッダーテーブル DDL 実行（指定がある場合のみ） ---
        header_table_created = False
        if header_ddl:
            header_result = db_service.execute_ddl(header_ddl)
            header_table_created = header_result.get("success", False)
            if not header_table_created:
                g.response.set_data({
                    "success": False,
                    "message": f"ヘッダーテーブル作成失敗: {header_result.get('message', '')}"
                })
                return jsonify(g.response.get_result()), 400

        # --- 明細テーブル DDL 実行（指定がある場合のみ） ---
        line_table_created = False
        if line_ddl:
            line_result = db_service.execute_ddl(line_ddl)
            line_table_created = line_result.get("success", False)
            if not line_table_created:
                g.response.set_data({
                    "success": False,
                    "message": f"明細テーブル作成失敗: {line_result.get('message', '')}"
                })
                return jsonify(g.response.get_result()), 400

        # --- 抽出データ INSERT ---
        insert_result = {"header_inserted": 0, "line_inserted": 0}
        if header_fields or raw_lines:
            insert_result = db_service.insert_extracted_data(
                header_table_name=header_table_name,
                line_table_name=line_table_name,
                header_fields=header_fields,
                raw_lines=raw_lines
            )
            if not insert_result.get("success", True):
                g.response.set_data({
                    "success": False,
                    "message": insert_result.get("message", "データINSERTに失敗しました"),
                    "header_inserted": insert_result.get("header_inserted", 0),
                    "line_inserted": insert_result.get("line_inserted", 0),
                })
                return jsonify(g.response.get_result()), 400

            expected_line_count = len(raw_lines or [])
            if header_fields and int(insert_result.get("header_inserted", 0) or 0) <= 0:
                g.response.set_data({
                    "success": False,
                    "message": insert_result.get("message", "ヘッダーデータが登録されませんでした"),
                    "header_inserted": insert_result.get("header_inserted", 0),
                    "line_inserted": insert_result.get("line_inserted", 0),
                })
                return jsonify(g.response.get_result()), 400
            if expected_line_count and int(insert_result.get("line_inserted", 0) or 0) != expected_line_count:
                g.response.set_data({
                    "success": False,
                    "message": insert_result.get("message", "明細データの一部または全部の登録に失敗しました"),
                    "header_inserted": insert_result.get("header_inserted", 0),
                    "line_inserted": insert_result.get("line_inserted", 0),
                })
                return jsonify(g.response.get_result()), 400

        # --- カテゴリ確定 ---
        resolved_category_id = None
        try:
            if category_id is not None:
                resolved_category_id = int(category_id)
        except (TypeError, ValueError):
            resolved_category_id = None

        if resolved_category_id is not None:
            existing_category = db_service.get_category_by_id(resolved_category_id)
            if not existing_category:
                g.response.set_data({"success": False, "message": "指定カテゴリが見つかりません"})
                return jsonify(g.response.get_result()), 400

            category_header_table = (existing_category.get("header_table_name") or "").strip().upper()
            category_line_table = (existing_category.get("line_table_name") or "").strip().upper()
            request_header_table = header_table_name.strip().upper()
            request_line_table = line_table_name.strip().upper()

            if category_header_table != request_header_table:
                g.response.set_data({
                    "success": False,
                    "message": (
                        "カテゴリのヘッダーテーブル名とリクエストが一致しません: "
                        f"{category_header_table} != {request_header_table}"
                    )
                })
                return jsonify(g.response.get_result()), 400

            if category_line_table != request_line_table:
                g.response.set_data({
                    "success": False,
                    "message": (
                        "カテゴリの明細テーブル名とリクエストが一致しません: "
                        f"{category_line_table or '(なし)'} != {request_line_table or '(なし)'}"
                    )
                })
                return jsonify(g.response.get_result()), 400
        else:
            resolved_category_id = db_service.upsert_category(
                category_name=category_name,
                category_name_en=category_name_en,
                header_table_name=header_table_name,
                line_table_name=line_table_name,
            )

        # --- 登録レコード作成 ---
        registration_id = db_service.insert_registration(
            file_id=file_id,
            category_name=category_name,
            header_table=header_table_name,
            line_table=line_table_name,
            header_record_id=None,
            line_count=line_count,
            ai_confidence=ai_confidence,
            registered_by=user,
        )

        # --- ファイルステータス更新 ---
        db_service.update_file_status(file_id, "REGISTERED")

        # --- アクティビティログ ---
        db_service.log_activity(
            activity_type="REGISTRATION",
            description=f"テーブル登録完了: {header_table_name}"
                        + (f", {line_table_name}" if line_table_name else ""),
            file_id=file_id,
            registration_id=registration_id,
            user_name=user,
        )

        result = {
            "success": True,
            "registration_id": registration_id,
            "category_id": resolved_category_id,
            "header_table_created": header_table_created,
            "line_table_created": line_table_created,
            "header_inserted": insert_result.get("header_inserted", 0),
            "line_inserted": insert_result.get("line_inserted", 0),
            "message": "DDL実行と登録が完了しました",
        }
        g.response.set_data(result)
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("DB登録エラー (file_id=%s): %s", file_id, e, exc_info=True)
        g.response.set_data({"success": False, "message": f"DB登録に失敗しました: {str(e)}"})
        return jsonify(g.response.get_result()), 500


# ========================================
# Category Management API
# ========================================

_CATEGORY_TABLE_NAME_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,127}$')
_ALLOWED_COL_DATA_TYPES = {"VARCHAR2", "NUMBER", "DATE", "TIMESTAMP"}
_SYSTEM_CATEGORY_COLUMN_NAME = "ID"


def _count_business_columns(columns: list) -> int:
    return sum(
        1
        for col in columns or []
        if (col.get("column_name") or "").strip().upper() != _SYSTEM_CATEGORY_COLUMN_NAME
    )


def _validate_column_defs(columns: list) -> Optional[str]:
    """カラム定義リストを検証し、問題があればエラーメッセージを返す"""
    if not columns:
        return "カラム定義が空です"
    seen_names = set()
    for col in columns:
        col_name = (col.get("column_name") or "").strip()
        if not col_name:
            return "カラム名が未入力のカラムがあります"
        if not re.match(r'^[A-Za-z][A-Za-z0-9_]{0,127}$', col_name):
            return f"カラム名 '{col_name}' は英字始まりの英数字・アンダースコアのみ使用できます"
        if col_name.upper() in seen_names:
            return f"カラム名 '{col_name}' が重複しています"
        seen_names.add(col_name.upper())
        col_name_jp = (col.get("column_name_jp") or col.get("comment") or "").strip()
        if not col_name_jp:
            return f"カラム名 '{col_name}' の日本語名は必須です"
        data_type = (col.get("data_type") or "").strip().upper()
        if data_type not in _ALLOWED_COL_DATA_TYPES:
            return f"データ型 '{data_type}' は使用できません（使用可能: {', '.join(sorted(_ALLOWED_COL_DATA_TYPES))}）"
    return None


@api_blueprint.route("/api/v1/categories/analyze-slips", methods=["POST"])
def analyze_slips_for_category():
    """SLIPS_CATEGORYファイルをAI分析してカテゴリのテーブル構造を提案する"""
    from denpyo_toroku.app.services.oci_storage_service import OCIStorageService
    from denpyo_toroku.app.services.document_processor import DocumentProcessor
    from denpyo_toroku.app.services.ai_service import AIService

    body = request.get_json(silent=True) or {}
    file_ids = body.get("file_ids", [])
    analysis_mode = body.get("analysis_mode", "header_line")
    run_async = _to_bool(body.get("async"), False)

    if not isinstance(file_ids, list) or not file_ids:
        g.response.add_error_message("file_ids は1件以上のIDリストを指定してください")
        return jsonify(g.response.get_result()), 400
    try:
        normalized_file_ids = [int(fid) for fid in file_ids]
    except (TypeError, ValueError):
        g.response.add_error_message("file_ids は数値のIDリストを指定してください")
        return jsonify(g.response.get_result()), 400

    if analysis_mode not in ("header_only", "header_line"):
        analysis_mode = "header_line"

    db_service = DatabaseService()
    file_records = db_service.get_files_by_ids(normalized_file_ids)
    if not file_records:
        file_records = db_service.get_slips_category_files_by_ids(normalized_file_ids)
    if not file_records:
        g.response.add_error_message("指定されたファイルが見つかりません")
        return jsonify(g.response.get_result()), 404

    for file_record in file_records:
        _decorate_analysis_status(file_record)

    record_by_id = {
        int(file_record.get("id")): file_record
        for file_record in file_records
        if file_record.get("id") is not None
    }
    missing_ids = [file_id for file_id in normalized_file_ids if file_id not in record_by_id]
    if missing_ids:
        g.response.add_error_message(f"指定されたファイルが見つかりません: {', '.join(map(str, missing_ids))}")
        return jsonify(g.response.get_result()), 404

    blocked_records = []
    for file_id in normalized_file_ids:
        file_record = record_by_id[file_id]
        current_status = _normalize_text(file_record.get("status"), "").upper()
        if current_status == "ANALYZING" and not file_record.get("is_analysis_stalled"):
            blocked_records.append(file_record.get("original_file_name") or file_record.get("file_name") or str(file_id))
        elif current_status not in ("UPLOADED", "ERROR", "ANALYZED", "ANALYZING"):
            blocked_records.append(file_record.get("original_file_name") or file_record.get("file_name") or str(file_id))

    if blocked_records:
        g.response.add_error_message(
            f"分析を開始できないファイルが含まれています: {', '.join(blocked_records[:3])}"
        )
        return jsonify(g.response.get_result()), 400

    for file_id in normalized_file_ids:
        db_service.update_file_status(file_id, "ANALYZING")
        db_service.update_category_file_status(file_id, "ANALYZING")
        db_service.log_activity(
            activity_type="CATEGORY_ANALYZE_START",
            description=f"分類用サンプル伝票の分析を開始しました (file_id={file_id})",
            file_id=file_id,
            user_name=session.get("user", ""),
        )

    if run_async:
        _ANALYSIS_EXECUTOR.submit(
            _queue_category_slip_analysis,
            normalized_file_ids,
            analysis_mode,
            session.get("user", ""),
        )
        g.response.set_data({
            "queued": True,
            "status": "ANALYZING",
            "file_ids": normalized_file_ids,
            "message": "AI分析を受け付けました",
        })
        return jsonify(g.response.get_result()), 202

    storage_service = OCIStorageService()
    doc_processor = DocumentProcessor()
    ai_service = AIService()

    # 全ファイルを分析してフィールドを収集
    all_header_fields: List[Dict[str, Any]] = []
    all_line_fields: List[Dict[str, Any]] = []
    tmp_filepaths = []
    processed_file_ids: List[int] = []
    schema_result: Dict[str, Any] = {}

    try:
        # 1. すべてのファイルをダウンロードし、OCR用に画像化して /tmp に保存
        for rec in file_records:
            try:
                object_name = rec.get("object_name", "")
                file_data = storage_service.download_file(object_name)
                if not file_data:
                    logging.warning("ファイルダウンロード失敗: %s", object_name)
                    continue

                images = doc_processor.prepare_for_ai(file_data, rec.get("original_file_name", ""))
                if not images:
                    logging.warning("AI分析用画像の生成に失敗: %s", object_name)
                    continue

                for image_data, img_content_type in images:
                    suffix = ".jpg" if img_content_type in ("image/jpeg", "image/jpg") else ".png"
                    fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir="/tmp")
                    with os.fdopen(fd, "wb") as f:
                        f.write(image_data)
                    tmp_filepaths.append(tmp_path)
                if rec.get("id"):
                    processed_file_ids.append(rec.get("id"))
            except Exception as e:
                logging.error("ファイルダウンロード/OCR前処理エラー (id=%s): %s", rec.get("id"), e, exc_info=True)
                continue

        if not tmp_filepaths:
            for file_id in normalized_file_ids:
                db_service.update_file_status(file_id, "ERROR")
                db_service.update_category_file_status(file_id, "ERROR")
            g.response.add_error_message("処理できる画像ファイルがありませんでした")
            return jsonify(g.response.get_result()), 500

        # 2. VLMで画像からテキストを抽出（OCRの代替）
        ocr_result = ai_service.extract_text_from_images(tmp_filepaths)
        if not ocr_result.get("success"):
            for file_id in normalized_file_ids:
                db_service.update_file_status(file_id, "ERROR")
                db_service.update_category_file_status(file_id, "ERROR")
            g.response.add_error_message(f"テキスト抽出に失敗しました: {ocr_result.get('message')}")
            return jsonify(g.response.get_result()), 500

        extracted_text = ocr_result.get("extracted_text", "")

        # 3. LLMで抽出テキストからスキーマ（JSON）を生成
        schema_result = ai_service.generate_sql_schema_from_text(extracted_text, analysis_mode)
        if not schema_result.get("success"):
            for file_id in normalized_file_ids:
                db_service.update_file_status(file_id, "ERROR")
                db_service.update_category_file_status(file_id, "ERROR")
            g.response.add_error_message(f"AIによるスキーマ設計に失敗しました: {schema_result.get('message')}")
            return jsonify(g.response.get_result()), 500
            
        # 4. JSONから header_columns, line_columns を取得する
        all_header_fields = schema_result.get("header_fields", [])
        all_line_fields = schema_result.get("line_fields", [])
        
    finally:
        # クリーンアップ: 一時ファイルを削除
        for path in tmp_filepaths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                logging.warning("一時ファイルの削除に失敗しました: %s, error=%s", path, e)




    if not all_header_fields:
        for file_id in normalized_file_ids:
            db_service.update_file_status(file_id, "ERROR")
            db_service.update_category_file_status(file_id, "ERROR")
        g.response.add_error_message("分析できるファイルがありませんでした")
        return jsonify(g.response.get_result()), 500

    # フィールドをマージ（同名のものは代表1件に集約、大文字英語名で統一）
    # is_required が全出現で true かつ全ファイルで登場した場合は NOT NULL とする
    def _merge_fields(fields_list: List[Dict]) -> List[Dict]:
        seen: Dict[str, Dict] = {}
        required_count: Dict[str, int] = {}  # is_required=true の出現数
        appear_count: Dict[str, int] = {}    # 総出現数
        for f in fields_list:
            raw_key = (f.get("field_name_en") or "").strip()
            if not raw_key:
                continue
            # snake_case を大文字に統一（スペースはアンダースコアへ）
            key = raw_key.upper().replace(" ", "_").replace("-", "_")
            original_dt = (f.get("data_type") or "VARCHAR2").upper()
            dt = original_dt
            if dt not in ("VARCHAR2", "NUMBER", "DATE", "TIMESTAMP"):
                dt = "VARCHAR2"

            if key not in seen:
                max_length = None
                if dt == "VARCHAR2":
                    raw_len = f.get("max_length")
                    try:
                        max_length = int(raw_len) if raw_len else 100
                    except (TypeError, ValueError):
                        max_length = 100
                    if original_dt == "CLOB" and not raw_len:
                        max_length = 4000
                seen[key] = {
                    "column_name": key,
                    "column_name_jp": f.get("field_name") or raw_key,
                    "data_type": dt,
                    "max_length": max_length,
                    "precision": None,
                    "scale": None,
                    "is_nullable": True,
                    "is_primary_key": False,
                }
                appear_count[key] = 1
                required_count[key] = 1 if f.get("is_required") else 0
            else:
                existing_dt = seen[key].get("data_type", "VARCHAR2")
                if existing_dt != dt:
                    # 同名カラムで型がぶれた場合は安全側に倒して文字列化する
                    seen[key]["data_type"] = "VARCHAR2"
                    if not seen[key].get("max_length"):
                        seen[key]["max_length"] = 100
                    dt = "VARCHAR2"
                # 最大長は大きい方を採用
                if dt == "VARCHAR2":
                    existing_len = seen[key].get("max_length") or 100
                    raw_new_len = f.get("max_length")
                    try:
                        new_len = int(raw_new_len) if raw_new_len else 100
                    except (TypeError, ValueError):
                        new_len = 100
                    if original_dt == "CLOB" and not raw_new_len:
                        new_len = 4000
                    seen[key]["max_length"] = max(existing_len, new_len)
                appear_count[key] += 1
                if f.get("is_required"):
                    required_count[key] += 1

        for key in seen:
            if required_count.get(key, 0) == appear_count.get(key, 0) and appear_count.get(key, 0) > 0:
                seen[key]["is_nullable"] = False

        return list(seen.values())

    header_columns = _merge_fields(all_header_fields)
    line_columns = _merge_fields(all_line_fields) if analysis_mode == "header_line" else []

    category_guess = (schema_result.get("document_type_ja") or "").strip() or "伝票"

    # 英語名の推定（LLM提案を優先。なければ簡易変換）
    category_map = {
        "請求書": "invoice", "領収書": "receipt", "納品書": "delivery_note",
        "注文書": "purchase_order", "見積書": "quotation", "発注書": "order_sheet",
    }
    llm_doc_type_en = re.sub(
        r"[^a-z0-9_]+",
        "_",
        (schema_result.get("document_type_en") or "").strip().lower(),
    ).strip("_")
    category_guess_en = (
        llm_doc_type_en
        or category_map.get(category_guess, "slip")
    )

    analyzed_file_ids = list(dict.fromkeys(processed_file_ids))

    result = {
        "category_guess": category_guess,
        "category_guess_en": category_guess_en,
        "analysis_mode": analysis_mode,
        "header_columns": header_columns,
        "line_columns": line_columns,
        "analyzed_file_ids": analyzed_file_ids,
    }
    for file_id in normalized_file_ids:
        if not db_service.save_category_analysis_result(file_id, result):
            db_service.update_file_status(file_id, "ERROR")
            db_service.update_category_file_status(file_id, "ERROR")
            g.response.add_error_message(f"分析結果の保存に失敗しました (file_id={file_id})")
            return jsonify(g.response.get_result()), 500
        db_service.update_file_status(file_id, "ANALYZED")
        db_service.update_category_file_status(file_id, "ANALYZED")
    g.response.set_data(result)
    return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/categories", methods=["POST"])
def create_category():
    """カテゴリを新規作成（テーブル作成 + DENPYO_CATEGORIES登録）"""
    try:
        body = request.get_json(silent=True) or {}
        category_name = (body.get("category_name") or "").strip()
        category_name_en = (body.get("category_name_en") or "").strip()
        description = (body.get("description") or "").strip()
        header_table_name = (body.get("header_table_name") or "").strip().upper()
        header_columns = body.get("header_columns", [])
        line_table_name = (body.get("line_table_name") or "").strip().upper() or None
        line_columns = body.get("line_columns") or []

        # バリデーション
        if not category_name:
            g.response.add_error_message("カテゴリ名は必須です")
            return jsonify(g.response.get_result()), 400
        if not category_name_en:
            g.response.add_error_message("伝票分類名（英語）は必須です")
            return jsonify(g.response.get_result()), 400

        if not header_table_name or not _CATEGORY_TABLE_NAME_PATTERN.match(header_table_name):
            g.response.add_error_message("ヘッダーテーブル名が無効です")
            return jsonify(g.response.get_result()), 400

        col_err = _validate_column_defs(header_columns)
        if col_err:
            g.response.add_error_message(f"ヘッダーカラム定義エラー: {col_err}")
            return jsonify(g.response.get_result()), 400
        if _count_business_columns(header_columns) == 0:
            g.response.add_error_message("ヘッダーテーブルに ID 以外のカラムを1つ以上定義してください")
            return jsonify(g.response.get_result()), 400

        if line_table_name:
            if not _CATEGORY_TABLE_NAME_PATTERN.match(line_table_name):
                g.response.add_error_message("明細テーブル名が無効です")
                return jsonify(g.response.get_result()), 400
            if line_columns:
                line_col_err = _validate_column_defs(line_columns)
                if line_col_err:
                    g.response.add_error_message(f"明細カラム定義エラー: {line_col_err}")
                    return jsonify(g.response.get_result()), 400
                if _count_business_columns(line_columns) == 0:
                    g.response.add_error_message("明細テーブルに ID 以外のカラムを1つ以上定義してください")
                    return jsonify(g.response.get_result()), 400

        db_service = DatabaseService()
        conflicts = db_service.find_category_conflicts(
            category_name=category_name,
            category_name_en=category_name_en,
            header_table_name=header_table_name,
            line_table_name=line_table_name or "",
        )
        if conflicts:
            g.response.add_error_message(" / ".join(conflicts))
            return jsonify(g.response.get_result()), 409

        result = db_service.create_category_with_tables(
            category_name=category_name,
            category_name_en=category_name_en,
            description=description,
            header_table_name=header_table_name,
            header_columns=header_columns,
            line_table_name=line_table_name,
            line_columns=line_columns if line_table_name else None,
        )

        if not result.get("success"):
            message = result.get("message", "カテゴリ作成に失敗しました")
            g.response.add_error_message(message)
            status_code = 409 if any(token in message for token in ("既に使用されています", "既存カテゴリ", "既にデータベース上", "重複")) else 500
            return jsonify(g.response.get_result()), status_code

        g.response.set_data(result)
        return jsonify(g.response.get_result()), 201

    except Exception as e:
        logging.error("カテゴリ作成エラー: %s", e, exc_info=True)
        g.response.add_error_message(f"カテゴリ作成に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/categories", methods=["GET"])
def get_categories():
    """カテゴリ一覧を取得"""
    try:
        db_service = DatabaseService()
        categories = db_service.get_categories()
        g.response.set_data({"categories": categories})
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("カテゴリ一覧取得エラー: %s", e, exc_info=True)
        g.response.add_error_message(f"カテゴリ一覧の取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/categories/<int:category_id>", methods=["GET"])
def get_category(category_id: int):
    """カテゴリ詳細を取得"""
    try:
        db_service = DatabaseService()
        category = db_service.get_category_by_id(category_id)
        if not category:
            g.response.add_error_message("カテゴリが見つかりません")
            return jsonify(g.response.get_result()), 404
        g.response.set_data(category)
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("カテゴリ取得エラー (id=%s): %s", category_id, e, exc_info=True)
        g.response.add_error_message(f"カテゴリの取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/categories/<int:category_id>/select-ai-profile", methods=["POST"])
def create_category_select_ai_profile(category_id: int):
    """カテゴリ単位で Select AI Agent profile / team を作成する"""
    try:
        db_service = DatabaseService()
        existing = db_service.get_category_by_id(category_id)
        if not existing:
            g.response.add_error_message("カテゴリが見つかりません")
            return jsonify(g.response.get_result()), 404

        settings_snapshot = _load_oci_settings_snapshot()
        settings = settings_snapshot.get("settings", {})
        oci_auth_config = _build_oci_test_config(settings)
        result = db_service.create_select_ai_profile_for_category(
            category_id=category_id,
            oci_auth_config=oci_auth_config,
            model_settings=settings,
        )
        if not result.get("success"):
            message = result.get("message", "Select AI profile の作成に失敗しました")
            g.response.add_error_message(message)
            if any(token in message for token in ("不足", "ありません", "無効")):
                return jsonify(g.response.get_result()), 400
            return jsonify(g.response.get_result()), 500

        g.response.set_data(result)
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("Select AI profile 作成エラー (id=%s): %s", category_id, e, exc_info=True)
        g.response.add_error_message(f"Select AI profile の作成に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/categories/<int:category_id>", methods=["PUT"])
def update_category(category_id: int):
    """カテゴリを更新（名称・説明のみ）"""
    try:
        data = request.get_json(silent=True) or {}
        category_name = (data.get("category_name") or "").strip()
        category_name_en = (data.get("category_name_en") or "").strip()
        description = (data.get("description") or "").strip()

        if not category_name:
            g.response.add_error_message("カテゴリ名は必須です")
            return jsonify(g.response.get_result()), 400
        if not category_name_en:
            g.response.add_error_message("伝票分類名（英語）は必須です")
            return jsonify(g.response.get_result()), 400

        db_service = DatabaseService()

        existing = db_service.get_category_by_id(category_id)
        if not existing:
            g.response.add_error_message("カテゴリが見つかりません")
            return jsonify(g.response.get_result()), 404

        conflicts = db_service.find_category_conflicts(
            category_name=category_name,
            category_name_en=category_name_en,
            header_table_name=existing.get("header_table_name", ""),
            line_table_name=existing.get("line_table_name", ""),
            exclude_category_id=category_id,
        )
        if conflicts:
            g.response.add_error_message(" / ".join(conflicts))
            return jsonify(g.response.get_result()), 409

        success = db_service.update_category(
            category_id, category_name, category_name_en, description
        )
        if not success:
            g.response.add_error_message("カテゴリの更新に失敗しました")
            return jsonify(g.response.get_result()), 500

        updated = db_service.get_category_by_id(category_id)
        g.response.set_data(updated)
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("カテゴリ更新エラー (id=%s): %s", category_id, e, exc_info=True)
        g.response.add_error_message(f"カテゴリの更新に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/categories/<int:category_id>/toggle", methods=["PATCH"])
def toggle_category_active(category_id: int):
    """カテゴリの有効/無効を切り替え"""
    try:
        db_service = DatabaseService()

        existing = db_service.get_category_by_id(category_id)
        if not existing:
            g.response.add_error_message("カテゴリが見つかりません")
            return jsonify(g.response.get_result()), 404

        new_state = db_service.toggle_category_active(category_id)
        if new_state is None:
            g.response.add_error_message("有効/無効の切り替えに失敗しました")
            return jsonify(g.response.get_result()), 500

        g.response.set_data({
            "id": category_id,
            "is_active": new_state,
            "message": ("有効" if new_state else "無効") + "に変更しました"
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("カテゴリ切替エラー (id=%s): %s", category_id, e, exc_info=True)
        g.response.add_error_message(f"有効/無効の切り替えに失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/categories/<int:category_id>", methods=["DELETE"])
def delete_category(category_id: int):
    """カテゴリを削除（登録がある場合は拒否）"""
    try:
        db_service = DatabaseService()

        existing = db_service.get_category_by_id(category_id)
        if not existing:
            g.response.add_error_message("カテゴリが見つかりません")
            return jsonify(g.response.get_result()), 404

        result = db_service.delete_category(category_id)
        if not result["success"]:
            g.response.add_error_message(result["message"])
            return jsonify(g.response.get_result()), 400

        g.response.set_data({"success": True, "message": result["message"]})
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("カテゴリ削除エラー (id=%s): %s", category_id, e, exc_info=True)
        g.response.add_error_message(f"カテゴリの削除に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


# ========================================
# Data Search API (SCR-006)
# ========================================

@api_blueprint.route("/api/v1/search/tables", methods=["GET"])
def get_searchable_tables():
    """検索可能なテーブル一覧を取得"""
    try:
        db_service = DatabaseService()
        tables = db_service.get_allowed_table_names()
        g.response.set_data({"tables": tables})
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("検索可能テーブル一覧取得エラー: %s", e, exc_info=True)
        g.response.add_error_message(f"テーブル一覧の取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/search/table-browser/tables", methods=["GET"])
def get_table_browser_tables():
    """テーブルブラウザ用のテーブル一覧を取得"""
    try:
        db_service = DatabaseService()
        tables = db_service.get_table_browser_tables()
        g.response.set_data({
            "tables": tables,
            "fetched_at": dt.datetime.now().isoformat()
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("テーブルブラウザ一覧取得エラー: %s", e, exc_info=True)
        g.response.add_error_message(f"テーブル一覧の取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


def _build_search_table_schemas(db_service: DatabaseService, allowed_tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table_schemas: List[Dict[str, Any]] = []
    for entry in allowed_tables:
        header_table_name = (entry.get("header_table_name") or "").strip()
        line_table_name = (entry.get("line_table_name") or "").strip()
        if header_table_name:
            cols = db_service.get_table_columns(header_table_name)
            if cols:
                table_schemas.append({
                    "table_name": header_table_name,
                    "columns": cols,
                })
        if line_table_name:
            cols = db_service.get_table_columns(line_table_name)
            if cols:
                table_schemas.append({
                    "table_name": line_table_name,
                    "columns": cols,
                })
    return table_schemas


def _should_fallback_from_select_ai(select_ai_result: Dict[str, Any]) -> bool:
    if select_ai_result.get("success") or select_ai_result.get("generated_sql"):
        return False
    if bool(select_ai_result.get("fallback_to_direct_llm")):
        return True
    message = str(select_ai_result.get("message") or "").upper()
    fallback_tokens = (
        "DBMS_CLOUD_AI",
        "DBMS_CLOUD_AI_AGENT",
        "DBMS_CLOUD",
        "ORA-20053",
        "ORA-20404",
        "ORA-01031",
        "ORA-00904",
        "ORA-06550",
    )
    return any(token in message for token in fallback_tokens)


def _run_direct_llm_search(
    db_service: DatabaseService,
    *,
    query: str,
    allowed_tables: List[Dict[str, Any]],
    allowed_table_set: set,
) -> Dict[str, Any]:
    from denpyo_toroku.app.services.ai_service import AIService

    table_schemas = _build_search_table_schemas(db_service, allowed_tables)
    if not table_schemas:
        return {
            "success": False,
            "status_code": 400,
            "error_message": "テーブル情報を取得できませんでした",
        }

    ai_service = AIService()
    ai_result = ai_service.text_to_sql(query, table_schemas)
    if not ai_result.get("success"):
        return {
            "success": False,
            "status_code": 400,
            "error_message": ai_result.get("message", "SQL生成に失敗しました"),
        }

    generated_sql = ai_result.get("sql", "")
    explanation = ai_result.get("explanation", "")
    exec_result = db_service.execute_select_query(
        generated_sql,
        max_rows=500,
        allowed_tables=allowed_table_set,
    )
    if not exec_result.get("success"):
        return {
            "success": True,
            "payload": {
                "generated_sql": generated_sql,
                "explanation": explanation,
                "results": {
                    "columns": [],
                    "rows": [],
                    "total": 0,
                },
                "error": exec_result.get("message", "クエリ実行に失敗しました"),
                "engine": "direct_llm",
                "engine_meta": {},
            },
        }

    return {
        "success": True,
        "payload": {
            "generated_sql": generated_sql,
            "explanation": explanation,
            "results": {
                "columns": exec_result.get("columns", []),
                "rows": exec_result.get("rows", []),
                "total": exec_result.get("total", 0),
            },
            "engine": "direct_llm",
            "engine_meta": {},
        },
    }


@api_blueprint.route("/api/v1/search/nl", methods=["POST"])
def natural_language_search():
    """自然言語検索（NL -> SQL -> 実行）"""
    try:
        data = request.get_json(silent=True) or {}
        query = (data.get("query") or "").strip()
        category_id = data.get("category_id")

        if not query:
            g.response.add_error_message("検索クエリを入力してください")
            return jsonify(g.response.get_result()), 400
        if category_id is None:
            g.response.add_error_message("伝票分類を選択してください")
            return jsonify(g.response.get_result()), 400

        db_service = DatabaseService()

        # 許可テーブル一覧を取得
        allowed_tables = db_service.get_allowed_table_names()
        if not allowed_tables:
            g.response.add_error_message("検索可能なテーブルがありません")
            return jsonify(g.response.get_result()), 400

        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            g.response.add_error_message("category_id は整数で指定してください")
            return jsonify(g.response.get_result()), 400

        allowed_tables = [t for t in allowed_tables if t["category_id"] == category_id]
        if not allowed_tables:
            g.response.add_error_message("指定されたカテゴリに検索可能なテーブルがありません")
            return jsonify(g.response.get_result()), 400

        allowed_table_set = db_service._build_allowed_table_set_from_entries(allowed_tables)
        settings_snapshot = _load_oci_settings_snapshot()
        settings = settings_snapshot.get("settings", {})

        if _to_bool(settings.get("select_ai_enabled"), default=True):
            oci_auth_config = _build_oci_test_config(settings)
            select_ai_result = db_service.run_select_ai_agent_search(
                query=query,
                allowed_table_entries=allowed_tables,
                oci_auth_config=oci_auth_config,
                model_settings=settings,
                max_rows=500,
            )
            if not select_ai_result.get("success"):
                if select_ai_result.get("generated_sql"):
                    g.response.set_data({
                        "generated_sql": select_ai_result.get("generated_sql", ""),
                        "explanation": select_ai_result.get("explanation", ""),
                        "results": {
                            "columns": [],
                            "rows": [],
                            "total": 0
                        },
                        "error": select_ai_result.get("message", "クエリ実行に失敗しました"),
                        "engine": select_ai_result.get("engine", "select_ai_agent"),
                        "engine_meta": select_ai_result.get("engine_meta", {}),
                    })
                    return jsonify(g.response.get_result())

                if _should_fallback_from_select_ai(select_ai_result):
                    logging.warning(
                        "Select AI Agent の基盤エラーのため direct LLM にフォールバックします: %s",
                        select_ai_result.get("message", ""),
                    )
                else:
                    g.response.add_error_message(
                        select_ai_result.get("message", "Select AI Agent での検索に失敗しました")
                    )
                    return jsonify(g.response.get_result()), 400

            else:
                g.response.set_data({
                    "generated_sql": select_ai_result.get("generated_sql", ""),
                    "explanation": select_ai_result.get("explanation", ""),
                    "results": {
                        "columns": select_ai_result.get("results", {}).get("columns", []),
                        "rows": select_ai_result.get("results", {}).get("rows", []),
                        "total": select_ai_result.get("results", {}).get("total", 0),
                    },
                    "engine": select_ai_result.get("engine", "select_ai_agent"),
                    "engine_meta": select_ai_result.get("engine_meta", {}),
                })
                return jsonify(g.response.get_result())

        direct_llm_result = _run_direct_llm_search(
            db_service,
            query=query,
            allowed_tables=allowed_tables,
            allowed_table_set=allowed_table_set,
        )
        if not direct_llm_result.get("success"):
            g.response.add_error_message(direct_llm_result.get("error_message", "検索に失敗しました"))
            return jsonify(g.response.get_result()), int(direct_llm_result.get("status_code", 400))

        g.response.set_data(direct_llm_result["payload"])
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("自然言語検索エラー: %s", e, exc_info=True)
        g.response.add_error_message(f"検索に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/search/tables/<int:category_id>/data", methods=["GET"])
def get_table_data(category_id: int):
    """カテゴリのテーブルデータを取得（ページング付き）"""
    try:
        page = max(1, request.args.get("page", 1, type=int))
        page_size = min(100, max(1, request.args.get("page_size", 50, type=int)))
        table_type = request.args.get("table_type", "header")  # header or line

        db_service = DatabaseService()

        # カテゴリ情報を取得
        category = db_service.get_category_by_id(category_id)
        if not category:
            g.response.add_error_message("カテゴリが見つかりません")
            return jsonify(g.response.get_result()), 404

        # テーブル名を決定
        if table_type == "line":
            table_name = category.get("line_table_name", "")
        else:
            table_name = category.get("header_table_name", "")

        if not table_name:
            g.response.add_error_message(f"指定されたテーブル（{table_type}）が設定されていません")
            return jsonify(g.response.get_result()), 400

        offset = (page - 1) * page_size
        result = db_service.get_table_data(table_name, limit=page_size, offset=offset)

        if not result.get("success"):
            g.response.add_error_message(result.get("message", "データ取得に失敗しました"))
            return jsonify(g.response.get_result()), 400

        total = result.get("total", 0)
        total_pages = max(1, (total + page_size - 1) // page_size)

        g.response.set_data({
            "table_name": result.get("table_name", ""),
            "table_type": table_type,
            "columns": result.get("columns", []),
            "rows": result.get("rows", []),
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        })
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("テーブルデータ取得エラー (category_id=%s): %s", category_id, e, exc_info=True)
        g.response.add_error_message(f"データ取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/search/table-browser/data", methods=["GET"])
def get_table_data_by_name():
    """テーブル名指定でデータを取得（ページング付き）"""
    try:
        table_name = (request.args.get("table_name") or "").strip()
        table_type = request.args.get("table_type", "header")
        page = max(1, request.args.get("page", 1, type=int))
        page_size = min(100, max(1, request.args.get("page_size", 50, type=int)))

        if not table_name:
            g.response.add_error_message("table_name を指定してください")
            return jsonify(g.response.get_result()), 400

        if table_type not in ("header", "line"):
            table_type = "header"

        db_service = DatabaseService()
        offset = (page - 1) * page_size
        result = db_service.get_table_data(table_name, limit=page_size, offset=offset)

        if not result.get("success"):
            g.response.add_error_message(result.get("message", "データ取得に失敗しました"))
            return jsonify(g.response.get_result()), 400

        total = result.get("total", 0)
        total_pages = max(1, (total + page_size - 1) // page_size)
        g.response.set_data({
            "table_name": result.get("table_name", "").upper(),
            "table_type": table_type,
            "columns": result.get("columns", []),
            "rows": result.get("rows", []),
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        })
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("テーブルデータ取得エラー (table_name=%s): %s", request.args.get("table_name"), e, exc_info=True)
        g.response.add_error_message(f"データ取得に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/search/table-browser/delete-row", methods=["POST"])
def delete_table_browser_row():
    """テーブルブラウザの1行をROWID指定で削除"""
    try:
        data = request.get_json(silent=True) or {}
        table_name = (data.get("table_name") or "").strip()
        row_id = (data.get("row_id") or "").strip()

        if not table_name:
            g.response.add_error_message("table_name を指定してください")
            return jsonify(g.response.get_result()), 400
        if not row_id:
            g.response.add_error_message("row_id を指定してください")
            return jsonify(g.response.get_result()), 400

        db_service = DatabaseService()
        result = db_service.delete_table_row_by_rowid(table_name, row_id)
        if not result.get("success"):
            g.response.add_error_message(result.get("message", "削除に失敗しました"))
            return jsonify(g.response.get_result()), 400

        g.response.set_data({"success": True, "deleted": result.get("deleted", 0)})
        return jsonify(g.response.get_result())
    except Exception as e:
        logging.error("テーブル行削除エラー (table_name=%s): %s", (request.get_json(silent=True) or {}).get("table_name"), e, exc_info=True)
        g.response.add_error_message(f"削除に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/metrics", methods=["GET"])
def get_metrics():
    """Prometheus metrics endpoint."""
    if generate_latest is None:
        return jsonify({"error": "prometheus_client がインストールされていません"}), 503

    payload = generate_latest()
    response = make_response(payload, 200)
    response.headers["Content-Type"] = CONTENT_TYPE_LATEST
    return response


# ========================================
# ADB (Autonomous Database) Management API
# ========================================

def _get_oci_config_for_adb() -> Optional[Dict[str, Any]]:
    """OCI設定を取得してADB操作用のconfigを返す

    ページの「リージョン」フィールドに表示される値（.envのOCI_REGION）と
    OCIクライアントが使用するregionを統一するため、~/.oci/configのregionを
    .envのOCI_REGIONで上書きする。
    """
    try:
        config_path = os.path.expanduser(AppConfig.OCI_CONFIG_PATH)
        profile = AppConfig.OCI_CONFIG_PROFILE

        if not os.path.exists(config_path):
            logging.warning("OCI設定ファイルが見つかりません: %s", config_path)
            return None

        import oci
        config = oci.config.from_file(config_path, profile)

        # ページのリージョンフィールドと統一するため、.envのOCI_REGIONで上書き
        # これにより「再取得」時に使用されるregionはページに表示される値と同じになる
        env_region = os.environ.get("OCI_REGION", AppConfig.OCI_REGION)
        if env_region:
            config["region"] = env_region

        return config
    except Exception as e:
        logging.error("OCI設定読み込みエラー: %s", e, exc_info=True)
        return None


def _get_adb_client():
    """ADBクライアントを取得"""
    try:
        import oci
        config = _get_oci_config_for_adb()
        if not config:
            return None
        return oci.database.DatabaseClient(config)
    except Exception as e:
        logging.error("ADBクライアント作成エラー: %s", e, exc_info=True)
        return None


@api_blueprint.route("/api/v1/database/adb/info", methods=["GET"])
def get_adb_info():
    """Autonomous Database情報を取得"""
    adb_ocid = os.environ.get(_DB_ADB_OCID_ENV_KEY, "").strip()

    # .envからregionを取得（デフォルトはAppConfig.OCI_REGION = ap-osaka-1）
    region = os.environ.get("OCI_REGION", AppConfig.OCI_REGION)

    if not adb_ocid:
        g.response.set_data({
            "status": "not_configured",
            "message": "ADB OCID が設定されていません。",
            "id": None,
            "display_name": None,
            "lifecycle_state": None,
            "region": region
        })
        return jsonify(g.response.get_result())

    try:
        db_client = _get_adb_client()
        if not db_client:
            g.response.set_data({
                "status": "error",
                "message": "OCI接続を確認できません。OCI設定を確認してください。",
                "id": adb_ocid,
                "display_name": None,
                "lifecycle_state": None,
                "region": region,
            })
            return jsonify(g.response.get_result())

        adb = db_client.get_autonomous_database(adb_ocid).data

        g.response.set_data({
            "status": "success",
            "message": "データベース情報を取得しました。",
            "id": adb.id,
            "display_name": adb.display_name,
            "lifecycle_state": adb.lifecycle_state,
            "db_name": getattr(adb, "db_name", None),
            "cpu_core_count": getattr(adb, "cpu_core_count", None),
            "data_storage_size_in_tbs": getattr(adb, "data_storage_size_in_tbs", None),
            "region": region
        })
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("ADB情報取得エラー: %s", e, exc_info=True)
        g.response.set_data({
            "status": "error",
            "message": f"データベース情報の取得に失敗しました: {str(e)}",
            "id": adb_ocid,
            "display_name": None,
            "lifecycle_state": None,
            "region": region,
        })
        return jsonify(g.response.get_result())


@api_blueprint.route("/api/v1/database/adb/start", methods=["POST"])
def start_adb():
    """Autonomous Databaseを起動"""
    adb_ocid = os.environ.get(_DB_ADB_OCID_ENV_KEY, "").strip()
    region = os.environ.get("OCI_REGION", AppConfig.OCI_REGION)

    if not adb_ocid:
        g.response.add_error_message("ADB OCID が設定されていません。")
        return jsonify(g.response.get_result()), 400

    try:
        db_client = _get_adb_client()
        if not db_client:
            g.response.add_error_message("OCI接続を確認できません。OCI設定を確認してください。")
            return jsonify(g.response.get_result()), 500

        # 現在の状態を確認
        adb = db_client.get_autonomous_database(adb_ocid).data

        if adb.lifecycle_state == "AVAILABLE":
            g.response.set_data({
                "status": "already_available",
                "message": "データベースは既に起動しています。",
                "id": adb.id,
                "display_name": adb.display_name,
                "lifecycle_state": adb.lifecycle_state,
                "region": region,
            })
            return jsonify(g.response.get_result())

        if adb.lifecycle_state not in ["STOPPED", "UNAVAILABLE"]:
            g.response.set_data({
                "status": "cannot_start",
                "message": f"データベースの現在の状態 ({adb.lifecycle_state}) では起動できません。",
                "id": adb.id,
                "display_name": adb.display_name,
                "lifecycle_state": adb.lifecycle_state,
                "region": region,
            })
            return jsonify(g.response.get_result())

        # 起動リクエスト送信
        db_client.start_autonomous_database(adb_ocid)

        g.response.set_data({
            "status": "accepted",
            "message": f"データベース '{adb.display_name}' の起動を開始しました。",
            "id": adb.id,
            "display_name": adb.display_name,
            "lifecycle_state": "STARTING",
            "region": region,
        })
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("ADB起動エラー: %s", e, exc_info=True)
        g.response.add_error_message(f"データベースの起動に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500


@api_blueprint.route("/api/v1/database/adb/stop", methods=["POST"])
def stop_adb():
    """Autonomous Databaseを停止"""
    adb_ocid = os.environ.get(_DB_ADB_OCID_ENV_KEY, "").strip()
    region = os.environ.get("OCI_REGION", AppConfig.OCI_REGION)

    if not adb_ocid:
        g.response.add_error_message("ADB OCID が設定されていません。")
        return jsonify(g.response.get_result()), 400

    try:
        db_client = _get_adb_client()
        if not db_client:
            g.response.add_error_message("OCI接続を確認できません。OCI設定を確認してください。")
            return jsonify(g.response.get_result()), 500

        # 現在の状態を確認
        adb = db_client.get_autonomous_database(adb_ocid).data

        if adb.lifecycle_state == "STOPPED":
            g.response.set_data({
                "status": "already_stopped",
                "message": "データベースは既に停止しています。",
                "id": adb.id,
                "display_name": adb.display_name,
                "lifecycle_state": adb.lifecycle_state,
                "region": region,
            })
            return jsonify(g.response.get_result())

        if adb.lifecycle_state not in ["AVAILABLE"]:
            g.response.set_data({
                "status": "cannot_stop",
                "message": f"データベースの現在の状態 ({adb.lifecycle_state}) では停止できません。",
                "id": adb.id,
                "display_name": adb.display_name,
                "lifecycle_state": adb.lifecycle_state,
                "region": region,
            })
            return jsonify(g.response.get_result())

        # 停止リクエスト送信
        db_client.stop_autonomous_database(adb_ocid)

        g.response.set_data({
            "status": "accepted",
            "message": f"データベース '{adb.display_name}' の停止を開始しました。",
            "id": adb.id,
            "display_name": adb.display_name,
            "lifecycle_state": "STOPPING",
            "region": region,
        })
        return jsonify(g.response.get_result())

    except Exception as e:
        logging.error("ADB停止エラー: %s", e, exc_info=True)
        g.response.add_error_message(f"データベースの停止に失敗しました: {str(e)}")
        return jsonify(g.response.get_result()), 500
