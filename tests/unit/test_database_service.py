import datetime as dt
import json
import logging
from contextlib import contextmanager

import denpyo_toroku.app.services.database_service as database_service_module
from denpyo_toroku.app.services.database_service import DatabaseService


def test_build_column_comment_ddls_uses_japanese_names_and_escapes_quotes():
    ddls = DatabaseService._build_column_comment_ddls(
        "receipt_h",
        [
            {"column_name": "tenpou_mei", "column_name_jp": "店舗名"},
            {"column_name": "memo", "column_name_jp": "備考'欄"},
            {"column_name": "skip_me", "column_name_jp": ""},
            {"column_name": "", "column_name_jp": "無視"},
        ],
        "HEADER_ID",
    )

    assert ddls == [
        "COMMENT ON COLUMN RECEIPT_H.HEADER_ID IS 'ヘッダーID'",
        "COMMENT ON COLUMN RECEIPT_H.TENPOU_MEI IS '店舗名'",
        "COMMENT ON COLUMN RECEIPT_H.MEMO IS '備考''欄'",
    ]


def test_build_ddl_from_columns_injects_system_id_column_first():
    ddl = DatabaseService._build_ddl_from_columns(
        "RECEIPT_H",
        [
            {
                "column_name": "TENPOU_MEI",
                "column_name_jp": "店舗名",
                "data_type": "VARCHAR2",
                "max_length": 100,
                "is_nullable": True,
                "is_primary_key": False,
            }
        ],
        "HEADER_ID",
    )

    assert "HEADER_ID VARCHAR2(32) NOT NULL" in ddl
    assert ddl.index("HEADER_ID VARCHAR2(32) NOT NULL") < ddl.index("TENPOU_MEI VARCHAR2(100)")
    assert "CONSTRAINT PK_RECEIPT_H PRIMARY KEY (HEADER_ID)" in ddl


def test_create_category_with_tables_executes_column_comment_ddls(monkeypatch):
    service = DatabaseService()
    header_columns = [
        {
            "column_name": "TENPOU_MEI",
            "column_name_jp": "店舗名",
            "data_type": "VARCHAR2",
            "max_length": 100,
            "is_nullable": True,
            "is_primary_key": False,
        },
        {
            "column_name": "DENWA_BANGOU",
            "column_name_jp": "電話番号",
            "data_type": "VARCHAR2",
            "max_length": 20,
            "is_nullable": True,
            "is_primary_key": False,
        },
    ]
    line_columns = [
        {
            "column_name": "SHOUHIN_MEI",
            "column_name_jp": "商品名",
            "data_type": "VARCHAR2",
            "max_length": 100,
            "is_nullable": True,
            "is_primary_key": False,
        }
    ]
    executed_ddls = []

    def fake_execute_ddl(ddl_statement):
        executed_ddls.append(ddl_statement)
        return {"success": True, "message": "ok"}

    monkeypatch.setattr(service, "execute_ddl", fake_execute_ddl)
    monkeypatch.setattr(service, "upsert_category", lambda **kwargs: 42)
    monkeypatch.setattr(service, "find_category_conflicts", lambda **kwargs: [])

    result = service.create_category_with_tables(
        category_name="レシート",
        category_name_en="receipt",
        description="",
        header_table_name="RECEIPT_H",
        header_columns=header_columns,
        line_table_name="RECEIPT_L",
        line_columns=line_columns,
    )

    normalized_header = service._normalize_designer_columns(header_columns, "HEADER_ID")
    normalized_line = service._normalize_designer_columns(line_columns, "LINE_ID", "HEADER_ID")
    assert result["success"] is True
    assert result["category_id"] == 42
    assert executed_ddls == [
        service._build_ddl_from_columns("RECEIPT_H", normalized_header, "HEADER_ID"),
        "COMMENT ON COLUMN RECEIPT_H.HEADER_ID IS 'ヘッダーID'",
        "COMMENT ON COLUMN RECEIPT_H.TENPOU_MEI IS '店舗名'",
        "COMMENT ON COLUMN RECEIPT_H.DENWA_BANGOU IS '電話番号'",
        service._build_id_immutability_trigger_ddl("RECEIPT_H", "HEADER_ID"),
        service._build_ddl_from_columns("RECEIPT_L", normalized_line, "LINE_ID", "HEADER_ID"),
        "COMMENT ON COLUMN RECEIPT_L.LINE_ID IS '明細ID'",
        "COMMENT ON COLUMN RECEIPT_L.HEADER_ID IS 'ヘッダーID'",
        "COMMENT ON COLUMN RECEIPT_L.SHOUHIN_MEI IS '商品名'",
        service._build_id_immutability_trigger_ddl("RECEIPT_L", "LINE_ID"),
    ]


def test_create_category_with_tables_fails_when_column_comment_ddl_fails(monkeypatch):
    service = DatabaseService()
    executed_ddls = []
    upsert_called = {"value": False}

    def fake_execute_ddl(ddl_statement):
        executed_ddls.append(ddl_statement)
        if ddl_statement.startswith("COMMENT ON COLUMN"):
            return {"success": False, "message": "comment failed"}
        return {"success": True, "message": "ok"}

    def fake_upsert_category(**kwargs):
        upsert_called["value"] = True
        return 99

    monkeypatch.setattr(service, "execute_ddl", fake_execute_ddl)
    monkeypatch.setattr(service, "upsert_category", fake_upsert_category)
    monkeypatch.setattr(service, "find_category_conflicts", lambda **kwargs: [])

    result = service.create_category_with_tables(
        category_name="レシート",
        category_name_en="receipt",
        description="",
        header_table_name="RECEIPT_H",
        header_columns=[
            {
                "column_name": "TENPOU_MEI",
                "column_name_jp": "店舗名",
                "data_type": "VARCHAR2",
                "max_length": 100,
                "is_nullable": True,
                "is_primary_key": False,
            }
        ],
    )

    assert result["success"] is False
    assert "ヘッダーカラムコメント作成失敗" in result["message"]
    assert upsert_called["value"] is False
    assert executed_ddls[0].startswith("CREATE TABLE RECEIPT_H")
    assert executed_ddls[1] == "COMMENT ON COLUMN RECEIPT_H.HEADER_ID IS 'ヘッダーID'"


def test_execute_ddl_wraps_trigger_ddl_in_execute_immediate(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append(("COMMIT", None))

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    result = service.execute_ddl(service._build_id_immutability_trigger_ddl("RECEIPT_H", "HEADER_ID"))

    assert result["success"] is True
    assert executed[0][1] is None
    assert executed[0][0].startswith("BEGIN EXECUTE IMMEDIATE q'")
    assert "CREATE OR REPLACE TRIGGER TRG_RECEIPT_H_ID_IMM" in executed[0][0]
    assert ":OLD.HEADER_ID" in executed[0][0]
    assert ":NEW.HEADER_ID" in executed[0][0]
    assert executed[1] == ("COMMIT", None)


def test_find_category_conflicts_reuses_named_bind_for_table_name(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def __init__(self):
            self._results = iter([None, None, (1,)])

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return next(self._results)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "_ensure_management_tables", lambda: True)
    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    conflicts = service.find_category_conflicts(
        category_name="領収書",
        category_name_en="receipt",
        header_table_name="RECEIPT_H",
    )

    assert conflicts == ["テーブル名 'RECEIPT_H' は既存カテゴリで使用されています"]
    assert executed[2][1] == {"table_name": "RECEIPT_H"}
    assert ":table_name" in executed[2][0]


def test_build_ddl_from_columns_converts_legacy_clob_to_varchar2():
    ddl = DatabaseService._build_ddl_from_columns(
        "receipt_h",
        [
            {
                "column_name": "BIKOU",
                "data_type": "CLOB",
                "is_nullable": True,
                "is_primary_key": False,
            }
        ],
        "HEADER_ID",
    )

    assert "BIKOU VARCHAR2(4000)" in ddl
    assert "CLOB" not in ddl


def test_build_select_ai_profile_attributes_uses_comments_and_object_list():
    payload = DatabaseService._build_select_ai_profile_attributes(
        credential_name="DTAICR_ABC123",
        model_name="meta.llama-3.3-70b-instruct",
        region="us-chicago-1",
        compartment_id="ocid1.compartment.oc1..example",
        object_list=[{"owner": "APPUSER", "name": "RECEIPT_H"}],
        embedding_model_name="cohere.embed-v4.0",
        endpoint_id="ocid1.generativeaiendpoint.oc1.ap-osaka-1.example",
        max_tokens=4096,
        enforce_object_list=True,
        use_annotations=True,
        use_comments=True,
        use_constraints=True,
        api_format="GENERIC",
    )

    parsed = json.loads(payload)
    assert parsed == {
        "provider": "oci",
        "credential_name": "DTAICR_ABC123",
        "model": "meta.llama-3.3-70b-instruct",
        "region": "us-chicago-1",
        "oci_compartment_id": "ocid1.compartment.oc1..example",
        "object_list": [{"owner": "APPUSER", "name": "RECEIPT_H"}],
        "embedding_model": "cohere.embed-v4.0",
        "oci_endpoint_id": "ocid1.generativeaiendpoint.oc1.ap-osaka-1.example",
        "max_tokens": 4096,
        "enforce_object_list": True,
        "annotations": True,
        "comments": True,
        "constraints": True,
        "oci_apiformat": "GENERIC",
    }


def test_build_select_ai_asset_names_are_stable_and_short():
    names1 = DatabaseService._build_select_ai_asset_names("same-config")
    names2 = DatabaseService._build_select_ai_asset_names("same-config")

    assert names1 == names2
    assert set(names1.keys()) == {
        "credential_name",
        "profile_name",
        "tool_name",
        "agent_name",
        "task_name",
        "team_name",
    }
    assert all(len(value) <= 30 for value in names1.values())


def test_resolve_select_ai_model_name_uses_region_compatible_fallback_for_xai_grok():
    assert (
        DatabaseService._resolve_select_ai_model_name("xai.grok-4-1-fast-reasoning", "ap-osaka-1")
        == "meta.llama-3.3-70b-instruct"
    )


def test_resolve_select_ai_model_name_keeps_xai_grok_in_supported_region():
    assert (
        DatabaseService._resolve_select_ai_model_name("xai.grok-4-1-fast-reasoning", "us-chicago-1")
        == "xai.grok-4-1-fast-reasoning"
    )


def test_create_select_ai_profile_for_category_persists_metadata(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append(("COMMIT", None))

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "_ensure_management_tables", lambda: True)
    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        service,
        "get_category_by_id",
        lambda category_id: {
            "id": category_id,
            "category_name": "領収書",
            "header_table_name": "RECEIPT_H",
            "line_table_name": "",
        },
    )
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

    result = service.create_select_ai_profile_for_category(
        category_id=1,
        oci_auth_config={"region": "ap-osaka-1"},
        model_settings={"llm_model_id": "cohere.command-r", "compartment_id": "ocid1.compartment.oc1..x"},
    )

    assert result == {
        "success": True,
        "category_id": 1,
        "category_name": "領収書",
        "profile_name": "DTAIPR_TEST000001",
        "team_name": "DTAITM_TEST000001",
        "model_name": "meta.llama-3.3-70b-instruct",
        "region": "ap-osaka-1",
        "config_hash": "ABC123",
    }
    assert "UPDATE DENPYO_CATEGORIES" in executed[0][0]
    assert executed[0][1][:5] == ["DTAIPR_TEST000001", "DTAITM_TEST000001", 1, "ABC123", ""]
    assert executed[1] == ("COMMIT", None)


def test_extract_json_payload_reads_markdown_wrapped_json():
    payload = DatabaseService._extract_json_payload(
        """```json
{"sql":"SELECT * FROM RECEIPT_H","explanation":"日本語説明"}
```"""
    )

    assert payload["sql"] == "SELECT * FROM RECEIPT_H"
    assert payload["explanation"] == "日本語説明"


def test_execute_select_query_respects_explicit_allowed_tables(monkeypatch):
    service = DatabaseService()

    result = service.execute_select_query(
        "SELECT * FROM RECEIPT_H",
        allowed_tables={"OTHER_TABLE"},
    )

    assert result["success"] is False
    assert "許可されていないテーブル" in result["message"]


def test_execute_select_query_logs_validation_failure_at_debug_for_explicit_allowlist(caplog):
    service = DatabaseService()

    with caplog.at_level(logging.DEBUG, logger=database_service_module.logger.name):
        result = service.execute_select_query(
            "SELECT * FROM RECEIPT_H",
            allowed_tables={"OTHER_TABLE"},
        )

    assert result["success"] is False
    assert any(
        record.levelno == logging.DEBUG
        and "SQL 検証失敗（明示 allowlist 適用中）" in record.message
        for record in caplog.records
    )
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_execute_select_query_logs_validation_failure_at_warning_without_explicit_allowlist(monkeypatch, caplog):
    service = DatabaseService()
    monkeypatch.setattr(service, "_get_allowed_table_set", lambda: {"OTHER_TABLE"})

    with caplog.at_level(logging.WARNING, logger=database_service_module.logger.name):
        result = service.execute_select_query("SELECT * FROM RECEIPT_H")

    assert result["success"] is False
    assert any(
        record.levelno == logging.WARNING and "SQL 検証エラー" in record.message
        for record in caplog.records
    )


def test_execute_select_query_allows_where_clause_columns(monkeypatch):
    service = DatabaseService()

    class FakeCursor:
        description = [("HEADER_ID",), ("TENPOU_MEI",)]

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params

        def fetchall(self):
            return [("R-001", "経堂駅前店")]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    result = service.execute_select_query(
        "SELECT * FROM RECEIPT_H_2 WHERE TENPOU_MEI = '経堂駅前店'",
        allowed_tables={"RECEIPT_H_2"},
    )

    assert result["success"] is True
    assert result["rows"] == [{"HEADER_ID": "R-001", "TENPOU_MEI": "経堂駅前店"}]


def test_execute_select_query_allows_current_schema_qualified_table(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        description = [("HEADER_ID",)]

        def __init__(self):
            self._fetchone_result = None

        def execute(self, sql, params=None):
            executed.append((sql, params))
            if "CURRENT_SCHEMA" in sql:
                self._fetchone_result = ("ADMIN",)

        def fetchone(self):
            return self._fetchone_result

        def fetchall(self):
            return [("R-005",)]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    result = service.execute_select_query(
        "SELECT * FROM ADMIN.RECEIPT_H_5",
        allowed_tables={"RECEIPT_H_5"},
    )

    assert result["success"] is True
    assert result["rows"] == [{"HEADER_ID": "R-005"}]
    assert "CURRENT_SCHEMA" in executed[0][0]
    assert "FROM (SELECT * FROM ADMIN.RECEIPT_H_5)" in executed[1][0]


def test_get_table_browser_tables_includes_category_tables(monkeypatch):
    service = DatabaseService()

    class FakeCursor:
        def __init__(self):
            self._sql = ""

        def execute(self, sql, params=None):
            self._sql = sql

        def fetchall(self):
            if "FROM USER_TABLES t" in self._sql:
                return [
                    ("SLIPS_RAW", 2, "2026-03-01 00:00:00", "2026-02-28 00:00:00"),
                    ("RECEIPT_H", 5, "2026-03-04 00:00:00", "2026-03-03 00:00:00"),
                    ("RECEIPT_L", 8, "2026-03-04 00:00:00", "2026-03-03 00:00:00"),
                ]
            if "FROM USER_TAB_COLUMNS" in self._sql:
                return [
                    ("SLIPS_RAW", 9),
                    ("RECEIPT_H", 4),
                    ("RECEIPT_L", 6),
                ]
            return []

        def fetchone(self):
            if "SELECT COUNT(*) FROM SLIPS_RAW" in self._sql:
                return (2,)
            if "SELECT COUNT(*) FROM RECEIPT_H" in self._sql:
                return (5,)
            if "SELECT COUNT(*) FROM RECEIPT_L" in self._sql:
                return (8,)
            return (0,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(service, "get_allowed_table_names", lambda: [
        {
            "category_id": 10,
            "category_name": "領収書",
            "header_table_name": "RECEIPT_H",
            "line_table_name": "RECEIPT_L",
        }
    ])

    result = service.get_table_browser_tables()

    assert result == [
        {
            "table_name": "RECEIPT_H",
            "table_type": "header",
            "category_id": 10,
            "category_name": "領収書",
            "row_count": 5,
            "estimated_rows": 5,
            "column_count": 4,
            "created_at": "2026-03-03 00:00:00",
            "last_analyzed": "2026-03-04 00:00:00",
        },
        {
            "table_name": "RECEIPT_L",
            "table_type": "line",
            "category_id": 10,
            "category_name": "領収書",
            "row_count": 8,
            "estimated_rows": 8,
            "column_count": 6,
            "created_at": "2026-03-03 00:00:00",
            "last_analyzed": "2026-03-04 00:00:00",
        },
    ]


def test_insert_extracted_data_generates_system_ids(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def __init__(self):
            self.rowcount = 1
            self._fetchall_result = []

        def execute(self, sql, params=None):
            if "FROM USER_TAB_COLUMNS" in sql:
                table_name = params[0]
                if table_name == "RECEIPT_H":
                    self._fetchall_result = [("HEADER_ID", "VARCHAR2"), ("TENPOU_MEI", "VARCHAR2")]
                elif table_name == "RECEIPT_L":
                    self._fetchall_result = [("LINE_ID", "VARCHAR2"), ("HEADER_ID", "VARCHAR2"), ("SHOUHIN_MEI", "VARCHAR2")]
                else:
                    self._fetchall_result = []
                self.rowcount = 0
                return
            executed.append((sql, params))
            self.rowcount = 1

        def executemany(self, sql, params_list):
            executed.append((sql, params_list))
            self.rowcount = len(params_list)

        def fetchall(self):
            return self._fetchall_result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append(("COMMIT", None))

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    generated_ids = {
        "RECEIPT_H": "RECEIPT-H-20260306-000001",
        "RECEIPT_L": "RECEIPT-L-20260306-000001",
    }

    monkeypatch.setattr(service, "_ensure_management_tables", lambda: True)
    monkeypatch.setattr(service, "_is_safe_table_name", lambda table_name: True)
    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(service, "_generate_business_id", lambda _cursor, table_name: generated_ids[table_name.upper()])

    result = service.insert_extracted_data(
        header_table_name="RECEIPT_H",
        line_table_name="RECEIPT_L",
        header_fields=[
            {"field_name_en": "HEADER_ID", "value": "MANUAL-ID"},
            {"field_name_en": "TENPOU_MEI", "value": "渋谷店"},
        ],
        raw_lines=[
            {"LINE_ID": "MANUAL-LINE-ID", "SHOUHIN_MEI": "りんご"},
        ],
    )

    assert result["success"] is True
    assert executed[0][0] == "INSERT INTO RECEIPT_H (HEADER_ID, TENPOU_MEI) VALUES (:1, :2)"
    assert executed[0][1] == ["RECEIPT-H-20260306-000001", "渋谷店"]
    assert executed[1][0] == "INSERT INTO RECEIPT_L (LINE_ID, HEADER_ID, SHOUHIN_MEI) VALUES (:1, :2, :3)"
    assert executed[1][1] == [["RECEIPT-L-20260306-000001", "RECEIPT-H-20260306-000001", "りんご"]]


def test_insert_extracted_data_marks_failure_when_header_insert_errors(monkeypatch):
    service = DatabaseService()

    class FakeCursor:
        def __init__(self):
            self.rowcount = 1
            self._generated = False
            self._fetchall_result = []

        def execute(self, sql, params=None):
            if "FROM USER_TAB_COLUMNS" in sql:
                table_name = params[0]
                if table_name == "RECEIPT_H":
                    self._fetchall_result = [("HEADER_ID", "VARCHAR2"), ("TENPOU_MEI", "VARCHAR2")]
                else:
                    self._fetchall_result = []
                self.rowcount = 0
                return
            if "UPDATE DENPYO_ID_SEQUENCES" in sql or "INSERT INTO DENPYO_ID_SEQUENCES" in sql:
                self._generated = True
                self.rowcount = 1
                return
            if sql.startswith("INSERT INTO RECEIPT_H"):
                raise RuntimeError("ORA-00942: table or view does not exist")
            self.rowcount = 1

        def fetchall(self):
            return self._fetchall_result

        def var(self, _type):
            class FakeVar:
                def getvalue(self_inner):
                    return [1]
            return FakeVar()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "_ensure_management_tables", lambda: True)
    monkeypatch.setattr(service, "_is_safe_table_name", lambda table_name: True)
    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    result = service.insert_extracted_data(
        header_table_name="RECEIPT_H",
        line_table_name="",
        header_fields=[{"field_name_en": "TENPOU_MEI", "value": "渋谷店"}],
        raw_lines=[],
    )

    assert result["success"] is False
    assert result["header_inserted"] == 0
    assert result["line_inserted"] == 0
    assert "ヘッダーINSERTエラー" in result["message"]


def test_insert_extracted_data_coerces_date_timestamp_and_number_literals(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def __init__(self):
            self.rowcount = 1
            self._fetchall_result = []

        def execute(self, sql, params=None):
            if "FROM USER_TAB_COLUMNS" in sql:
                table_name = params[0]
                if table_name == "RECEIPT_H":
                    self._fetchall_result = [("HEADER_ID", "VARCHAR2"), ("URIAGE_DATE", "DATE")]
                elif table_name == "RECEIPT_L":
                    self._fetchall_result = [
                        ("LINE_ID", "VARCHAR2"),
                        ("HEADER_ID", "VARCHAR2"),
                        ("CREATED_AT", "TIMESTAMP(6)"),
                        ("KINGAKU", "NUMBER"),
                    ]
                else:
                    self._fetchall_result = []
                self.rowcount = 0
                return

            executed.append((sql, params))
            self.rowcount = 1

        def executemany(self, sql, params_list):
            executed.append((sql, params_list))
            self.rowcount = len(params_list)

        def fetchall(self):
            return self._fetchall_result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append(("COMMIT", None))

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    generated_ids = {
        "RECEIPT_H": "RECEIPT-H-20260306-000001",
        "RECEIPT_L": "RECEIPT-L-20260306-000001",
    }

    monkeypatch.setattr(service, "_ensure_management_tables", lambda: True)
    monkeypatch.setattr(service, "_is_safe_table_name", lambda table_name: True)
    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(service, "_generate_business_id", lambda _cursor, table_name: generated_ids[table_name.upper()])

    result = service.insert_extracted_data(
        header_table_name="RECEIPT_H",
        line_table_name="RECEIPT_L",
        header_fields=[
            {"field_name_en": "URIAGE_DATE", "value": "2026-03-06", "data_type": "DATE"},
        ],
        raw_lines=[
            {"CREATED_AT": "2026-03-06T12:34:56", "KINGAKU": "1,234"},
        ],
    )

    assert result["success"] is True
    assert executed[0][0] == "INSERT INTO RECEIPT_H (HEADER_ID, URIAGE_DATE) VALUES (:1, :2)"
    assert executed[0][1][0] == "RECEIPT-H-20260306-000001"
    assert isinstance(executed[0][1][1], dt.date)
    assert not isinstance(executed[0][1][1], dt.datetime)
    assert executed[0][1][1] == dt.date(2026, 3, 6)
    assert executed[1][0] == "INSERT INTO RECEIPT_L (LINE_ID, HEADER_ID, CREATED_AT, KINGAKU) VALUES (:1, :2, :3, :4)"
    assert executed[1][1][0][0] == "RECEIPT-L-20260306-000001"
    assert executed[1][1][0][1] == "RECEIPT-H-20260306-000001"
    assert executed[1][1][0][2] == dt.datetime(2026, 3, 6, 12, 34, 56)
    assert executed[1][1][0][3] == 1234


def test_insert_extracted_data_reports_invalid_date_before_oracle_execute(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def __init__(self):
            self.rowcount = 1
            self._fetchall_result = []

        def execute(self, sql, params=None):
            if "FROM USER_TAB_COLUMNS" in sql:
                self._fetchall_result = [("HEADER_ID", "VARCHAR2"), ("URIAGE_DATE", "DATE")]
                self.rowcount = 0
                return

            executed.append((sql, params))
            self.rowcount = 1

        def fetchall(self):
            return self._fetchall_result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append(("COMMIT", None))

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "_ensure_management_tables", lambda: True)
    monkeypatch.setattr(service, "_is_safe_table_name", lambda table_name: True)
    monkeypatch.setattr(service, "get_connection", fake_get_connection)
    monkeypatch.setattr(service, "_generate_business_id", lambda _cursor, _table_name: "RECEIPT-H-20260306-000001")

    result = service.insert_extracted_data(
        header_table_name="RECEIPT_H",
        line_table_name="",
        header_fields=[
            {"field_name_en": "URIAGE_DATE", "value": "2026-13-40", "data_type": "DATE"},
        ],
        raw_lines=[],
    )

    assert result["success"] is False
    assert "ヘッダーINSERTエラー" in result["message"]
    assert "URIAGE_DATE" in result["message"]
    assert not any(sql.startswith("INSERT INTO RECEIPT_H") for sql, _ in executed)


def test_ensure_pool_reuses_shared_pool_across_instances(monkeypatch):
    DatabaseService.close_shared_pool()
    created_pools = []

    class FakePool:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def close(self):
            self.closed = True

    class FakeOracleDb:
        @staticmethod
        def create_pool(**kwargs):
            pool = FakePool(f"pool-{len(created_pools) + 1}")
            created_pools.append({"pool": pool, "kwargs": kwargs})
            return pool

    monkeypatch.setattr(database_service_module, "ORACLEDB_AVAILABLE", True)
    monkeypatch.setattr(database_service_module, "oracledb", FakeOracleDb)
    monkeypatch.setenv("ORACLE_26AI_CONNECTION_STRING", "app_user/app_pass@sample_dsn")
    monkeypatch.setattr(DatabaseService, "_get_wallet_location", lambda self: None)

    service_a = DatabaseService()
    service_b = DatabaseService()

    try:
        assert service_a._ensure_pool() is True
        assert service_b._ensure_pool() is True
        assert len(created_pools) == 1
        assert service_a._pool is created_pools[0]["pool"]
        assert service_b._pool is created_pools[0]["pool"]
    finally:
        DatabaseService.close_shared_pool()


def test_ensure_pool_recreates_shared_pool_when_connection_settings_change(monkeypatch):
    DatabaseService.close_shared_pool()
    created_pools = []

    class FakePool:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def close(self):
            self.closed = True

    class FakeOracleDb:
        @staticmethod
        def create_pool(**kwargs):
            pool = FakePool(kwargs["dsn"])
            created_pools.append(pool)
            return pool

    monkeypatch.setattr(database_service_module, "ORACLEDB_AVAILABLE", True)
    monkeypatch.setattr(database_service_module, "oracledb", FakeOracleDb)
    monkeypatch.setattr(DatabaseService, "_get_wallet_location", lambda self: None)

    first_service = DatabaseService()
    second_service = DatabaseService()

    try:
        monkeypatch.setenv("ORACLE_26AI_CONNECTION_STRING", "app_user/app_pass@dsn_a")
        assert first_service._ensure_pool() is True
        first_pool = created_pools[0]
        assert first_pool.closed is False

        monkeypatch.setenv("ORACLE_26AI_CONNECTION_STRING", "app_user/app_pass@dsn_b")
        assert second_service._ensure_pool() is True

        assert len(created_pools) == 2
        assert first_pool.closed is True
        assert second_service._pool is created_pools[1]
    finally:
        DatabaseService.close_shared_pool()


def test_management_table_initialization_is_shared_across_instances(monkeypatch):
    DatabaseService.close_shared_pool()
    DatabaseService._shared_management_tables_initialized = False
    enter_count = {"value": 0}

    class FakeCursor:
        def execute(self, sql, params=None):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    @contextmanager
    def fake_get_connection(self):
        enter_count["value"] += 1
        yield FakeConnection()

    monkeypatch.setattr(DatabaseService, "get_connection", fake_get_connection)
    monkeypatch.setattr(
        DatabaseService,
        "_ensure_table_columns",
        lambda self, cursor, table_name, columns: None,
    )
    monkeypatch.setattr(
        DatabaseService,
        "_ensure_blob_column",
        lambda self, cursor, table_name, column_name: None,
    )

    service_a = DatabaseService()
    service_b = DatabaseService()

    try:
        assert service_a._ensure_management_tables() is True
        assert service_b._ensure_management_tables() is True
        assert enter_count["value"] == 1
    finally:
        DatabaseService._shared_management_tables_initialized = False


def test_backfill_registration_category_ids_updates_legacy_rows():
    service = DatabaseService()
    executed = []

    class FakeCursor:
        rowcount = 3

        def execute(self, sql, params=None):
            executed.append((sql, params))

    cursor = FakeCursor()
    service._backfill_registration_category_ids(cursor)

    assert len(executed) == 1
    assert "UPDATE DENPYO_REGISTRATIONS r" in executed[0][0]
    assert "SET CATEGORY_ID =" in executed[0][0]
    assert "WHERE r.CATEGORY_ID IS NULL" in executed[0][0]


def test_get_categories_uses_header_table_row_counts(monkeypatch):
    service = DatabaseService()

    class FakeCursor:
        def __init__(self):
            self._sql = ""

        def execute(self, sql, params=None):
            self._sql = sql

        def fetchall(self):
            if "FROM DENPYO_CATEGORIES c" in self._sql:
                return [
                    (
                        5, "領収証_5", "receipt_5", "RECEIPT_H_5", "RECEIPT_L_5",
                        "", "profile-a", "team-a", 1, "2026-03-08 21:20:34", "hash-1",
                        "", 1, "2026-03-08 20:00:00", "2026-03-08 21:20:34",
                    ),
                    (
                        4, "領収書_4", "receipt_4", "RECEIPT_H_4", "",
                        "", "", "", 0, None, "",
                        "", 1, "2026-03-08 17:00:00", "2026-03-08 17:25:52",
                    ),
                ]
            return []

        def fetchone(self):
            if "SELECT COUNT(*) FROM RECEIPT_H_5" in self._sql:
                return (7,)
            if "SELECT COUNT(*) FROM RECEIPT_H_4" in self._sql:
                return (0,)
            return (0,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "_ensure_management_tables", lambda: True)
    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    result = service.get_categories()

    assert [category["registration_count"] for category in result] == [7, 0]
    assert result[0]["header_table_name"] == "RECEIPT_H_5"
    assert result[1]["header_table_name"] == "RECEIPT_H_4"


def test_get_connection_recreates_pool_once_when_shared_pool_was_closed(monkeypatch):
    DatabaseService.close_shared_pool()
    created_pools = []

    class FakeConnection:
        pass

    class FakePool:
        def __init__(self, name, should_fail_once=False):
            self.name = name
            self.should_fail_once = should_fail_once
            self.acquire_calls = 0
            self.released = []
            self.closed = False

        def acquire(self):
            self.acquire_calls += 1
            if self.should_fail_once and self.acquire_calls == 1:
                raise RuntimeError("DPY-1002: connection pool is not open")
            return FakeConnection()

        def release(self, connection):
            self.released.append(connection)

        def close(self):
            self.closed = True

    class FakeOracleDb:
        @staticmethod
        def create_pool(**kwargs):
            pool = FakePool(
                f"pool-{len(created_pools) + 1}",
                should_fail_once=(len(created_pools) == 0),
            )
            created_pools.append(pool)
            return pool

    monkeypatch.setattr(database_service_module, "ORACLEDB_AVAILABLE", True)
    monkeypatch.setattr(database_service_module, "oracledb", FakeOracleDb)
    monkeypatch.setenv("ORACLE_26AI_CONNECTION_STRING", "app_user/app_pass@sample_dsn")
    monkeypatch.setattr(DatabaseService, "_get_wallet_location", lambda self: None)

    service = DatabaseService()

    try:
        with service.get_connection() as connection:
            assert isinstance(connection, FakeConnection)

        assert len(created_pools) == 2
        assert created_pools[0].acquire_calls == 1
        assert created_pools[1].acquire_calls == 1
        assert len(created_pools[1].released) == 1
    finally:
        DatabaseService.close_shared_pool()


def test_delete_category_succeeds_when_physical_table_is_missing(monkeypatch, caplog):
    service = DatabaseService()
    executed = []
    commit_calls = []

    class FakeCursor:
        def __init__(self):
            self.rowcount = 0
            self._fetchone_result = None

        def execute(self, sql, params=None):
            normalized_sql = " ".join(sql.split())
            executed.append((normalized_sql, params))
            if normalized_sql == "SELECT CATEGORY_NAME, HEADER_TABLE_NAME, LINE_TABLE_NAME FROM DENPYO_CATEGORIES WHERE ID = :1":
                self._fetchone_result = ("歯科検診問診票", "DENTAL_CHECKUP_QUESTIONNAIRE_H", "")
                return
            if normalized_sql == "SELECT COUNT(*) FROM DENPYO_REGISTRATIONS WHERE CATEGORY_ID = :1":
                self._fetchone_result = (0,)
                return
            if normalized_sql == "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1":
                self._fetchone_result = (0,)
                return
            if normalized_sql == "DELETE FROM DENPYO_CATEGORIES WHERE ID = :1":
                self.rowcount = 1
                return
            raise AssertionError(f"unexpected sql: {normalized_sql}")

        def fetchone(self):
            return self._fetchone_result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            commit_calls.append(True)

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    with caplog.at_level(logging.WARNING, logger=database_service_module.logger.name):
        result = service.delete_category(1)

    assert result == {
        "success": True,
        "message": "カテゴリを削除しました",
        "category_name": "歯科検診問診票",
        "dropped_tables": [],
    }
    assert commit_calls == [True]
    assert any(
        record.levelno == logging.WARNING
        and "カテゴリ削除時にテーブルが既に存在しません" in record.message
        for record in caplog.records
    )


def test_delete_category_succeeds_when_category_row_is_already_missing(monkeypatch):
    service = DatabaseService()
    commit_calls = []

    class FakeCursor:
        def __init__(self):
            self.rowcount = 0
            self._fetchone_result = None

        def execute(self, sql, params=None):
            normalized_sql = " ".join(sql.split())
            if normalized_sql == "SELECT CATEGORY_NAME, HEADER_TABLE_NAME, LINE_TABLE_NAME FROM DENPYO_CATEGORIES WHERE ID = :1":
                self._fetchone_result = None
                return
            raise AssertionError(f"unexpected sql: {normalized_sql}")

        def fetchone(self):
            return self._fetchone_result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            commit_calls.append(True)

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(service, "get_connection", fake_get_connection)

    result = service.delete_category(1)

    assert result == {
        "success": True,
        "message": "カテゴリは既に削除されています",
        "category_name": "",
        "dropped_tables": [],
        "already_missing": True,
    }
    assert commit_calls == []
