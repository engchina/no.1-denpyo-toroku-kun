from denpyo_toroku.app.services.database_service import DatabaseService
from contextlib import contextmanager


def test_ensure_select_ai_team_creates_team_when_team_name_lookup_is_unavailable():
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))

    service._ensure_select_ai_team(FakeCursor(), team_name="TEAM_A", attributes_json="{}")

    assert len(executed) == 2
    assert "DBMS_CLOUD_AI_AGENT.DROP_TEAM" in executed[0][0]
    assert "DBMS_CLOUD_AI_AGENT.CREATE_TEAM" in executed[1][0]
    assert executed[1][1] == {"team_name": "TEAM_A", "attributes": "{}"}


def test_ensure_select_ai_team_ignores_duplicate_create_when_team_name_lookup_is_unavailable():
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))
            if "DBMS_CLOUD_AI_AGENT.CREATE_TEAM" in sql:
                raise Exception("ORA-00955: name is already used by an existing object")

    service._ensure_select_ai_team(FakeCursor(), team_name="TEAM_A", attributes_json="{}")

    assert len(executed) == 2
    assert "DBMS_CLOUD_AI_AGENT.CREATE_TEAM" in executed[1][0]


def test_run_select_ai_agent_search_marks_single_category_profile_ready(monkeypatch):
    service = DatabaseService()
    executed = []
    fetch_results = [
        ("conv-test-001",),
        ('{"sql":"SELECT HEADER_ID FROM RECEIPT_H","explanation":"ok"}',),
    ]

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return fetch_results.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append(("COMMIT", None))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        service,
        "_ensure_select_ai_agent_assets",
        lambda *args, **kwargs: {
            "profile_name": "DTAIPR_TEST000001",
            "team_name": "DTAITM_TEST000001",
            "model_name": "meta.llama-3.3-70b-instruct",
            "region": "ap-osaka-1",
            "config_fingerprint": "ABC123",
        },
    )
    monkeypatch.setattr(
        service,
        "execute_select_query",
        lambda sql, max_rows=500, allowed_tables=None: {
            "success": True,
            "columns": ["HEADER_ID"],
            "rows": [{"HEADER_ID": "R-001"}],
            "total": 1,
        },
    )

    result = service.run_select_ai_agent_search(
        query="領収書を検索",
        allowed_table_entries=[
            {
                "category_id": 7,
                "category_name": "領収書",
                "header_table_name": "RECEIPT_H",
                "line_table_name": "",
            }
        ],
        oci_auth_config={
            "user": "ocid1.user.oc1..example",
            "tenancy": "ocid1.tenancy.oc1..example",
            "fingerprint": "aa:bb",
            "key_content": "PRIVATE KEY",
            "region": "ap-osaka-1",
        },
        model_settings={
            "llm_model_id": "cohere.command-r",
            "compartment_id": "ocid1.compartment.oc1..example",
        },
    )

    assert result["success"] is True
    assert result["engine_meta"]["conversation_id"] == "conv-test-001"
    assert result["engine_meta"]["model_name"] == "meta.llama-3.3-70b-instruct"
    assert result["engine_meta"]["region"] == "ap-osaka-1"
    assert result["engine_meta"]["config_hash"] == "ABC123"
    assert "UPDATE DENPYO_CATEGORIES" in executed[0][0]
    assert executed[0][1] == [
        "DTAIPR_TEST000001",
        "DTAITM_TEST000001",
        1,
        "ABC123",
        "",
        7,
    ]
    assert "DBMS_CLOUD_AI.CREATE_CONVERSATION" in executed[2][0]
    assert "DBMS_CLOUD_AI_AGENT.RUN_TEAM" in executed[3][0]
    assert executed[3][1]["params"] == '{"conversation_id":"conv-test-001"}'


def test_run_select_ai_agent_search_flags_endpoint_not_found_for_direct_fallback(monkeypatch):
    service = DatabaseService()

    class FakeCursor:
        def execute(self, sql, params=None):
            if "RUN_TEAM" in sql:
                raise Exception(
                    "ORA-20053: Job DTAITM_TEST000001_TASK_0 failed: "
                    "ORA-20404: Object not found - "
                    "https://inference.generativeai.ap-osaka-1.oci.my$cloud_domain/20231130/actions/chat"
                )

        def fetchone(self):
            return ("conv-test-002",)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        service,
        "_ensure_select_ai_agent_assets",
        lambda *args, **kwargs: {
            "profile_name": "DTAIPR_TEST000001",
            "team_name": "DTAITM_TEST000001",
            "model_name": "meta.llama-3.3-70b-instruct",
            "region": "ap-osaka-1",
            "config_fingerprint": "ABC123",
        },
    )
    monkeypatch.setattr(service, "save_category_select_ai_profile_metadata", lambda **kwargs: None)

    result = service.run_select_ai_agent_search(
        query="領収書を検索",
        allowed_table_entries=[
            {
                "category_id": 7,
                "category_name": "領収書",
                "header_table_name": "RECEIPT_H",
                "line_table_name": "",
            }
        ],
        oci_auth_config={
            "user": "ocid1.user.oc1..example",
            "tenancy": "ocid1.tenancy.oc1..example",
            "fingerprint": "aa:bb",
            "key_content": "PRIVATE KEY",
            "region": "ap-osaka-1",
        },
        model_settings={
            "llm_model_id": "xai.grok-4-1-fast-reasoning",
            "compartment_id": "ocid1.compartment.oc1..example",
        },
    )

    assert result["success"] is False
    assert result["fallback_to_direct_llm"] is True
    assert "OCI Generative AI エンドポイント設定" in result["message"]


def test_run_select_ai_agent_search_flags_missing_conversation_id_for_direct_fallback(monkeypatch):
    service = DatabaseService()

    class FakeCursor:
        def execute(self, sql, params=None):
            if "RUN_TEAM" in sql:
                raise Exception(
                    'ORA-20000: ORA-01400: cannot insert NULL into '
                    '("C##CLOUD$SERVICE"."DBMS_CLOUD_AI_CONVERSATION_PROMPT$"."CONVERSATION_ID#") '
                    'ORA-06512: at "C##CLOUD$SERVICE.DBMS_CLOUD_AI_AGENT", line 10015'
                )

        def fetchone(self):
            return ("conv-test-003",)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        service,
        "_ensure_select_ai_agent_assets",
        lambda *args, **kwargs: {
            "profile_name": "DTAIPR_TEST000001",
            "team_name": "DTAITM_TEST000001",
            "model_name": "xai.grok-4-1-fast-reasoning",
            "region": "us-chicago-1",
            "config_fingerprint": "ABC123",
        },
    )
    monkeypatch.setattr(service, "save_category_select_ai_profile_metadata", lambda **kwargs: None)

    result = service.run_select_ai_agent_search(
        query="領収書を検索",
        allowed_table_entries=[
            {
                "category_id": 7,
                "category_name": "領収書",
                "header_table_name": "RECEIPT_H",
                "line_table_name": "",
            }
        ],
        oci_auth_config={
            "user": "ocid1.user.oc1..example",
            "tenancy": "ocid1.tenancy.oc1..example",
            "fingerprint": "aa:bb",
            "key_content": "PRIVATE KEY",
            "region": "us-chicago-1",
        },
        model_settings={
            "llm_model_id": "xai.grok-4-1-fast-reasoning",
            "compartment_id": "ocid1.compartment.oc1..example",
        },
    )

    assert result["success"] is False
    assert result["fallback_to_direct_llm"] is True
    assert "conversation_id" in result["message"]
