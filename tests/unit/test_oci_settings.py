from pathlib import Path

from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp
from denpyo_toroku.app.services import ai_service
from denpyo_toroku.config import AppConfig


VALID_TEST_KEY = """-----BEGIN PRIVATE KEY-----
abc123
-----END PRIVATE KEY-----"""


def test_validate_private_key_content():
    assert api_bp._validate_private_key_content(VALID_TEST_KEY) is True
    assert api_bp._validate_private_key_content("not a pem key") is False
    assert api_bp._validate_private_key_content("") is False


def test_save_oci_settings_persists_config_env_and_snapshot(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    config_path = tmp_path / "oci" / "config"

    monkeypatch.setattr(api_bp, "_env_file_path", lambda: env_path)
    monkeypatch.setenv("OCI_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OCI_CONFIG_PROFILE", "DEFAULT")
    monkeypatch.setenv("OCI_CONFIG_COMPARTMENT", "")
    monkeypatch.setenv("OCI_SERVICE_ENDPOINT", "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com")
    monkeypatch.setenv("LLM_MODEL_ID", "xai.grok-4-1-fast-reasoning")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")
    monkeypatch.setenv("SELECT_AI_ENABLED", "true")
    monkeypatch.setenv("SELECT_AI_REGION", "ap-osaka-1")
    monkeypatch.setenv("SELECT_AI_MODEL_ID", "meta.llama-3.3-70b-instruct")
    monkeypatch.setenv("SELECT_AI_EMBEDDING_MODEL_ID", "cohere.embed-v4.0")
    monkeypatch.setenv("SELECT_AI_ENDPOINT_ID", "")
    monkeypatch.setenv("SELECT_AI_MAX_TOKENS", "4096")
    monkeypatch.setenv("SELECT_AI_ENFORCE_OBJECT_LIST", "true")
    monkeypatch.setenv("SELECT_AI_OCI_API_FORMAT", "GENERIC")
    monkeypatch.setenv("SELECT_AI_USE_ANNOTATIONS", "true")
    monkeypatch.setenv("SELECT_AI_USE_COMMENTS", "true")
    monkeypatch.setenv("SELECT_AI_USE_CONSTRAINTS", "true")

    result = api_bp._save_oci_settings({
        "user_ocid": "ocid1.user.oc1..test",
        "tenancy_ocid": "ocid1.tenancy.oc1..test",
        "fingerprint": "aa:bb:cc:dd",
        "region": "us-chicago-1",
        "key_content": VALID_TEST_KEY,
        "config_path": str(config_path),
        "profile": "DEFAULT",
        "compartment_id": "ocid1.compartment.oc1..test",
        "service_endpoint": "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
        "llm_model_id": "xai.grok-4-1-fast-reasoning",
        "embedding_model_id": "cohere.embed-v4.0",
        "select_ai_enabled": True,
        "select_ai_region": "ap-osaka-1",
        "select_ai_model_id": "meta.llama-3.3-70b-instruct",
        "select_ai_embedding_model_id": "cohere.embed-v4.0",
        "select_ai_endpoint_id": "ocid1.generativeaiendpoint.oc1.ap-osaka-1.example",
        "select_ai_max_tokens": 8192,
        "select_ai_enforce_object_list": False,
        "select_ai_oci_apiformat": "GENERIC",
        "select_ai_use_annotations": False,
        "select_ai_use_comments": False,
        "select_ai_use_constraints": False,
    })

    assert result["status"] == "saved"
    assert result["has_credentials"] is True
    assert result["settings"]["key_content"] == api_bp._OCI_MASKED_KEY

    key_file = Path(result["settings"]["key_file"])
    assert config_path.exists()
    assert key_file.exists()
    assert "BEGIN PRIVATE KEY" in key_file.read_text(encoding="utf-8")

    env_text = env_path.read_text(encoding="utf-8")
    assert f"OCI_CONFIG_PATH={config_path}" in env_text
    assert "OCI_REGION=us-chicago-1" in env_text
    assert "OCI_CONFIG_PROFILE=DEFAULT" in env_text
    assert "OCI_CONFIG_COMPARTMENT=ocid1.compartment.oc1..test" in env_text
    assert "SELECT_AI_ENABLED=true" in env_text
    assert "SELECT_AI_REGION=ap-osaka-1" in env_text
    assert "SELECT_AI_MODEL_ID=meta.llama-3.3-70b-instruct" in env_text
    assert "SELECT_AI_EMBEDDING_MODEL_ID=cohere.embed-v4.0" in env_text
    assert "SELECT_AI_ENDPOINT_ID=ocid1.generativeaiendpoint.oc1.ap-osaka-1.example" in env_text
    assert "SELECT_AI_MAX_TOKENS=8192" in env_text
    assert "SELECT_AI_ENFORCE_OBJECT_LIST=false" in env_text
    assert "SELECT_AI_OCI_API_FORMAT=GENERIC" in env_text
    assert "SELECT_AI_USE_ANNOTATIONS=false" in env_text
    assert "SELECT_AI_USE_COMMENTS=false" in env_text
    assert "SELECT_AI_USE_CONSTRAINTS=false" in env_text

    assert AppConfig.OCI_CONFIG_PATH == str(config_path)
    assert AppConfig.OCI_REGION == "us-chicago-1"
    assert AppConfig.OCI_CONFIG_PROFILE == "DEFAULT"
    assert AppConfig.OCI_CONFIG_COMPARTMENT == "ocid1.compartment.oc1..test"
    assert AppConfig.SELECT_AI_ENABLED is True
    assert AppConfig.SELECT_AI_REGION == "ap-osaka-1"
    assert AppConfig.SELECT_AI_MODEL_ID == "meta.llama-3.3-70b-instruct"
    assert AppConfig.SELECT_AI_EMBEDDING_MODEL_ID == "cohere.embed-v4.0"
    assert AppConfig.SELECT_AI_ENDPOINT_ID == "ocid1.generativeaiendpoint.oc1.ap-osaka-1.example"
    assert AppConfig.SELECT_AI_MAX_TOKENS == 8192
    assert AppConfig.SELECT_AI_ENFORCE_OBJECT_LIST is False
    assert AppConfig.SELECT_AI_OCI_API_FORMAT == "GENERIC"
    assert AppConfig.SELECT_AI_USE_ANNOTATIONS is False
    assert AppConfig.SELECT_AI_USE_COMMENTS is False
    assert AppConfig.SELECT_AI_USE_CONSTRAINTS is False


def test_build_oci_model_test_settings_prefers_request_payload(monkeypatch):
    monkeypatch.setenv("OCI_SERVICE_ENDPOINT", "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com")
    monkeypatch.setenv("OCI_CONFIG_COMPARTMENT", "ocid1.compartment.oc1..env")
    monkeypatch.setenv("LLM_MODEL_ID", "xai.grok-4-1-fast-reasoning")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")
    monkeypatch.setenv("SELECT_AI_ENABLED", "false")
    monkeypatch.setenv("SELECT_AI_OCI_API_FORMAT", "COHERE")
    monkeypatch.setenv("SELECT_AI_REGION", "eu-frankfurt-1")
    monkeypatch.setenv("SELECT_AI_MODEL_ID", "meta.llama-3.3-70b-instruct")
    monkeypatch.setenv("SELECT_AI_EMBEDDING_MODEL_ID", "cohere.embed-english-v3.0")
    monkeypatch.setenv("SELECT_AI_MAX_TOKENS", "2048")
    monkeypatch.setenv("SELECT_AI_ENFORCE_OBJECT_LIST", "true")
    monkeypatch.setenv("SELECT_AI_USE_ANNOTATIONS", "true")
    monkeypatch.setenv("SELECT_AI_USE_COMMENTS", "false")
    monkeypatch.setenv("SELECT_AI_USE_CONSTRAINTS", "true")

    result = api_bp._build_oci_model_test_settings({
        "service_endpoint": "https://inference.generativeai.ap-osaka-1.oci.oraclecloud.com",
        "compartment_id": "ocid1.compartment.oc1..request",
        "llm_model_id": "meta.llama-3.3-70b-instruct",
        "embedding_model_id": "cohere.embed-english-v3.0",
    })

    assert result["service_endpoint"] == "https://inference.generativeai.ap-osaka-1.oci.oraclecloud.com"
    assert result["compartment_id"] == "ocid1.compartment.oc1..request"
    assert result["llm_model_id"] == "meta.llama-3.3-70b-instruct"
    assert result["embedding_model_id"] == "cohere.embed-english-v3.0"


def test_build_oci_model_test_settings_uses_runtime_defaults(monkeypatch):
    monkeypatch.setenv("OCI_SERVICE_ENDPOINT", "https://inference.generativeai.uk-london-1.oci.oraclecloud.com")
    monkeypatch.setenv("OCI_CONFIG_COMPARTMENT", "ocid1.compartment.oc1..fallback")
    monkeypatch.setenv("LLM_MODEL_ID", "google.gemini-2.5-pro")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")
    monkeypatch.setenv("SELECT_AI_ENABLED", "true")
    monkeypatch.setenv("SELECT_AI_OCI_API_FORMAT", "GENERIC")
    monkeypatch.setenv("SELECT_AI_REGION", "uk-london-1")
    monkeypatch.setenv("SELECT_AI_MODEL_ID", "google.gemini-2.5-pro")
    monkeypatch.setenv("SELECT_AI_EMBEDDING_MODEL_ID", "cohere.embed-v4.0")
    monkeypatch.setenv("SELECT_AI_MAX_TOKENS", "4096")
    monkeypatch.setenv("SELECT_AI_ENFORCE_OBJECT_LIST", "true")
    monkeypatch.setenv("SELECT_AI_USE_ANNOTATIONS", "true")
    monkeypatch.setenv("SELECT_AI_USE_COMMENTS", "true")
    monkeypatch.setenv("SELECT_AI_USE_CONSTRAINTS", "true")

    result = api_bp._build_oci_model_test_settings({})

    assert result["service_endpoint"] == "https://inference.generativeai.uk-london-1.oci.oraclecloud.com"
    assert result["compartment_id"] == "ocid1.compartment.oc1..fallback"
    assert result["llm_model_id"] == "google.gemini-2.5-pro"
    assert result["embedding_model_id"] == "cohere.embed-v4.0"


def test_load_oci_settings_snapshot_prefers_runtime_region_over_config(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "oci"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config"
    key_path = config_dir / "oci_api_key.pem"
    key_path.write_text(VALID_TEST_KEY, encoding="utf-8")
    config_path.write_text(
        """[DEFAULT]\nuser=ocid1.user.oc1..test\ntenancy=ocid1.tenancy.oc1..test\nfingerprint=aa:bb:cc:dd\nregion=us-phoenix-1\nkey_file=oci_api_key.pem\n""",
        encoding="utf-8",
    )

    monkeypatch.setenv("OCI_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OCI_CONFIG_PROFILE", "DEFAULT")
    monkeypatch.setenv("OCI_REGION", "ap-osaka-1")
    monkeypatch.setenv("OCI_SERVICE_ENDPOINT", "https://inference.generativeai.uk-london-1.oci.oraclecloud.com")

    snapshot = api_bp._load_oci_settings_snapshot()

    assert snapshot["settings"]["region"] == "ap-osaka-1"


def test_build_oci_model_test_settings_builds_endpoint_from_region_when_missing(monkeypatch):
    monkeypatch.delenv("OCI_SERVICE_ENDPOINT", raising=False)
    monkeypatch.setenv("OCI_REGION", "eu-frankfurt-1")
    monkeypatch.setenv("OCI_CONFIG_COMPARTMENT", "ocid1.compartment.oc1..fallback")
    monkeypatch.setenv("LLM_MODEL_ID", "google.gemini-2.5-pro")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")

    result = api_bp._build_oci_model_test_settings({"service_endpoint": "", "region": "eu-frankfurt-1"})

    assert result["service_endpoint"] == "https://inference.generativeai.eu-frankfurt-1.oci.oraclecloud.com"


def test_runtime_oci_defaults_use_select_ai_specific_defaults(monkeypatch):
    monkeypatch.delenv("SELECT_AI_REGION", raising=False)
    monkeypatch.delenv("SELECT_AI_MODEL_ID", raising=False)
    monkeypatch.delenv("SELECT_AI_MAX_TOKENS", raising=False)
    monkeypatch.delattr(AppConfig, "SELECT_AI_REGION", raising=False)
    monkeypatch.delattr(AppConfig, "SELECT_AI_MODEL_ID", raising=False)
    monkeypatch.delattr(AppConfig, "SELECT_AI_MAX_TOKENS", raising=False)

    defaults = api_bp._runtime_oci_defaults()

    assert defaults["select_ai_region"] == "us-chicago-1"
    assert defaults["select_ai_model_id"] == "xai.grok-4-1-fast-reasoning"
    assert defaults["select_ai_max_tokens"] == 32768


def test_runtime_oci_defaults_use_ocr_defaults_and_legacy_fallback(monkeypatch):
    monkeypatch.delenv("GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", raising=False)
    monkeypatch.delenv("GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", raising=False)
    monkeypatch.delenv("GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", raising=False)
    monkeypatch.delenv("GENAI_OCR_ROTATION_ANGLES", raising=False)
    monkeypatch.delenv("GENAI_OCR_IMAGE_MAX_EDGE_STEPS", raising=False)
    monkeypatch.delattr(AppConfig, "GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", raising=False)
    monkeypatch.delattr(AppConfig, "GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", raising=False)
    monkeypatch.delattr(AppConfig, "GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", raising=False)
    monkeypatch.delattr(AppConfig, "GENAI_OCR_ROTATION_ANGLES", raising=False)
    monkeypatch.delattr(AppConfig, "GENAI_OCR_IMAGE_MAX_EDGE_STEPS", raising=False)

    defaults = api_bp._runtime_oci_defaults()

    assert defaults["ocr_empty_response_primary_max_retries"] == 1
    assert defaults["ocr_empty_response_secondary_max_retries"] == 0
    assert defaults["ocr_rotation_angles"] == "0,90,180,270"
    assert defaults["ocr_image_max_edge_steps"] == "2400,1800,1400,1100"

    monkeypatch.setenv("GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", "3")

    legacy_defaults = api_bp._runtime_oci_defaults()

    assert legacy_defaults["ocr_empty_response_primary_max_retries"] == 3
    assert legacy_defaults["ocr_empty_response_secondary_max_retries"] == 0


def test_save_oci_settings_persists_ocr_settings_and_refreshes_ai_service(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    config_path = tmp_path / "oci" / "config"

    monkeypatch.setattr(api_bp, "_env_file_path", lambda: env_path)
    monkeypatch.setenv("OCI_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OCI_CONFIG_PROFILE", "DEFAULT")
    monkeypatch.setenv("OCI_CONFIG_COMPARTMENT", "")
    monkeypatch.setenv("OCI_SERVICE_ENDPOINT", "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com")
    monkeypatch.setenv("LLM_MODEL_ID", "xai.grok-4-1-fast-reasoning")
    monkeypatch.setenv("VLM_MODEL_ID", "google.gemini-2.5-pro")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")
    monkeypatch.setenv("GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", "1")
    monkeypatch.setenv("GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", "1")
    monkeypatch.setenv("GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", "0")
    monkeypatch.setenv("GENAI_OCR_ROTATION_ANGLES", "0,90,180,270")
    monkeypatch.setenv("GENAI_OCR_IMAGE_MAX_EDGE_STEPS", "2400,1800,1400,1100")
    monkeypatch.setenv("SELECT_AI_ENABLED", "true")
    monkeypatch.setenv("SELECT_AI_REGION", "ap-osaka-1")
    monkeypatch.setenv("SELECT_AI_MODEL_ID", "meta.llama-3.3-70b-instruct")
    monkeypatch.setenv("SELECT_AI_EMBEDDING_MODEL_ID", "cohere.embed-v4.0")
    monkeypatch.setenv("SELECT_AI_ENDPOINT_ID", "")
    monkeypatch.setenv("SELECT_AI_MAX_TOKENS", "4096")
    monkeypatch.setenv("SELECT_AI_ENFORCE_OBJECT_LIST", "true")
    monkeypatch.setenv("SELECT_AI_OCI_API_FORMAT", "GENERIC")
    monkeypatch.setenv("SELECT_AI_USE_ANNOTATIONS", "true")
    monkeypatch.setenv("SELECT_AI_USE_COMMENTS", "true")
    monkeypatch.setenv("SELECT_AI_USE_CONSTRAINTS", "true")

    monkeypatch.setattr(AppConfig, "GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(AppConfig, "GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(AppConfig, "GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(AppConfig, "GENAI_OCR_ROTATION_ANGLES", "0,90,180,270", raising=False)
    monkeypatch.setattr(AppConfig, "GENAI_OCR_IMAGE_MAX_EDGE_STEPS", "2400,1800,1400,1100", raising=False)

    monkeypatch.setattr(ai_service, "GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(ai_service, "GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(ai_service, "GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(ai_service, "GENAI_OCR_ROTATION_ANGLES", (0,), raising=False)
    monkeypatch.setattr(ai_service, "GENAI_OCR_IMAGE_MAX_EDGE_STEPS", (1024,), raising=False)

    result = api_bp._save_oci_settings({
        "user_ocid": "ocid1.user.oc1..test",
        "tenancy_ocid": "ocid1.tenancy.oc1..test",
        "fingerprint": "aa:bb:cc:dd",
        "region": "us-chicago-1",
        "key_content": VALID_TEST_KEY,
        "config_path": str(config_path),
        "profile": "DEFAULT",
        "compartment_id": "ocid1.compartment.oc1..test",
        "service_endpoint": "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
        "llm_model_id": "xai.grok-4-1-fast-reasoning",
        "vlm_model_id": "google.gemini-2.5-pro",
        "embedding_model_id": "cohere.embed-v4.0",
        "ocr_empty_response_primary_max_retries": 2,
        "ocr_empty_response_secondary_max_retries": 1,
        "ocr_rotation_angles": "90,270,90",
        "ocr_image_max_edge_steps": "2600, 1800, 2600, invalid",
        "select_ai_enabled": True,
        "select_ai_region": "ap-osaka-1",
        "select_ai_model_id": "meta.llama-3.3-70b-instruct",
        "select_ai_embedding_model_id": "cohere.embed-v4.0",
        "select_ai_endpoint_id": "ocid1.generativeaiendpoint.oc1.ap-osaka-1.example",
        "select_ai_max_tokens": 8192,
        "select_ai_enforce_object_list": False,
        "select_ai_oci_apiformat": "GENERIC",
        "select_ai_use_annotations": False,
        "select_ai_use_comments": False,
        "select_ai_use_constraints": False,
    })

    env_text = env_path.read_text(encoding="utf-8")

    assert "GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES=2" in env_text
    assert "GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES=2" in env_text
    assert "GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES=1" in env_text
    assert "GENAI_OCR_ROTATION_ANGLES=0,90,270" in env_text
    assert "GENAI_OCR_IMAGE_MAX_EDGE_STEPS=2600,1800" in env_text
    assert result["settings"]["ocr_empty_response_primary_max_retries"] == 2
    assert result["settings"]["ocr_empty_response_secondary_max_retries"] == 1
    assert result["settings"]["ocr_rotation_angles"] == "0,90,270"
    assert result["settings"]["ocr_image_max_edge_steps"] == "2600,1800"
    assert AppConfig.GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES == 2
    assert AppConfig.GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES == 2
    assert AppConfig.GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES == 1
    assert AppConfig.GENAI_OCR_ROTATION_ANGLES == "0,90,270"
    assert AppConfig.GENAI_OCR_IMAGE_MAX_EDGE_STEPS == "2600,1800"
    assert ai_service.GENAI_OCR_EMPTY_RESPONSE_MAX_RETRIES == 2
    assert ai_service.GENAI_OCR_EMPTY_RESPONSE_PRIMARY_MAX_RETRIES == 2
    assert ai_service.GENAI_OCR_EMPTY_RESPONSE_SECONDARY_MAX_RETRIES == 1
    assert ai_service.GENAI_OCR_ROTATION_ANGLES == (0, 90, 270)
    assert ai_service.GENAI_OCR_IMAGE_MAX_EDGE_STEPS == (2600, 1800)
