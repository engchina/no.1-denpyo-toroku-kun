from pathlib import Path

from denpyo_toroku.app.blueprints.api import api_blueprint as api_bp
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
    monkeypatch.setenv("LLM_MODEL_ID", "xai.grok-code-fast-1")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")

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
        "llm_model_id": "xai.grok-code-fast-1",
        "embedding_model_id": "cohere.embed-v4.0",
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
    assert "OCI_CONFIG_PROFILE=DEFAULT" in env_text
    assert "OCI_CONFIG_COMPARTMENT=ocid1.compartment.oc1..test" in env_text

    assert AppConfig.OCI_CONFIG_PATH == str(config_path)
    assert AppConfig.OCI_CONFIG_PROFILE == "DEFAULT"
    assert AppConfig.OCI_CONFIG_COMPARTMENT == "ocid1.compartment.oc1..test"


def test_build_oci_model_test_settings_prefers_request_payload(monkeypatch):
    monkeypatch.setenv("OCI_SERVICE_ENDPOINT", "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com")
    monkeypatch.setenv("OCI_CONFIG_COMPARTMENT", "ocid1.compartment.oc1..env")
    monkeypatch.setenv("LLM_MODEL_ID", "xai.grok-code-fast-1")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")

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
    monkeypatch.setenv("LLM_MODEL_ID", "google.gemini-2.5-flash")
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "cohere.embed-v4.0")

    result = api_bp._build_oci_model_test_settings({})

    assert result["service_endpoint"] == "https://inference.generativeai.uk-london-1.oci.oraclecloud.com"
    assert result["compartment_id"] == "ocid1.compartment.oc1..fallback"
    assert result["llm_model_id"] == "google.gemini-2.5-flash"
    assert result["embedding_model_id"] == "cohere.embed-v4.0"
