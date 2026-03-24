from contextlib import contextmanager
import logging

import pytest

from denpyo_toroku.app.services.database_service import DatabaseService


def test_validate_select_only_allows_forbidden_keywords_inside_string_literals():
    service = DatabaseService()

    service._validate_select_only(
        "SELECT * FROM RECEIPT_H WHERE MEMO = 'DELETE' AND NOTE LIKE '%DROP%'"
    )


def test_validate_tables_in_whitelist_rejects_unauthorized_comma_join():
    service = DatabaseService()

    with pytest.raises(ValueError, match="SECRET_TABLE"):
        service._validate_tables_in_whitelist(
            "SELECT * FROM RECEIPT_H h, SECRET_TABLE s WHERE h.HEADER_ID = s.HEADER_ID",
            {"RECEIPT_H"},
        )


def test_validate_tables_in_whitelist_rejects_quoted_unauthorized_table():
    service = DatabaseService()

    with pytest.raises(ValueError, match="SECRET_TABLE"):
        service._validate_tables_in_whitelist(
            'SELECT * FROM "SECRET_TABLE"',
            {"RECEIPT_H"},
        )


def test_validate_tables_in_whitelist_rejects_schema_qualified_table_reference():
    service = DatabaseService()

    with pytest.raises(ValueError, match="APPUSER\\.RECEIPT_H"):
        service._validate_tables_in_whitelist(
            "SELECT * FROM APPUSER.RECEIPT_H",
            {"RECEIPT_H"},
        )


def test_validate_tables_in_whitelist_allows_current_schema_qualified_table_reference():
    service = DatabaseService()

    service._validate_tables_in_whitelist(
        "SELECT * FROM ADMIN.RECEIPT_H",
        {"RECEIPT_H"},
        allowed_schema_names={"ADMIN"},
    )


def test_validate_tables_in_whitelist_allows_allowed_comma_join():
    service = DatabaseService()

    service._validate_tables_in_whitelist(
        "SELECT * FROM RECEIPT_H h, RECEIPT_L l WHERE h.HEADER_ID = l.HEADER_ID",
        {"RECEIPT_H", "RECEIPT_L"},
    )


def test_get_table_data_keeps_row_id_meta_and_hides_internal_rid(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def __init__(self):
            self.description = []
            self._fetchall_result = []

        def execute(self, sql, params=None):
            executed.append((sql, params))
            if "FROM USER_CONSTRAINTS" in sql:
                self._fetchall_result = [("ID",)]
            elif sql.startswith("SELECT ROWIDTOCHAR"):
                self.description = [
                    ("ROW_ID_META", None, None, None, None, None, None),
                    ("ID", None, None, None, None, None, None),
                    ("FILE_NAME", None, None, None, None, None, None),
                ]
                self._fetchall_result = [
                    ("AAABBB==", "ID-001", "sample-1.png"),
                    ("CCCDDD==", "ID-002", "sample-2.png"),
                ]

        def fetchone(self):
            return (2,)

        def fetchall(self):
            return self._fetchall_result

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
    monkeypatch.setattr(service, "_get_allowed_table_set", lambda: {"SLIPS_RAW"})

    result = service.get_table_data("SLIPS_RAW", limit=2, offset=0)

    assert result["success"] is True
    assert result["columns"] == ["ID", "FILE_NAME"]
    assert result["rows"] == [
        {"ROW_ID_META": "AAABBB==", "ID": "ID-001", "FILE_NAME": "sample-1.png"},
        {"ROW_ID_META": "CCCDDD==", "ID": "ID-002", "FILE_NAME": "sample-2.png"},
    ]
    assert "RID" not in result["rows"][0]
    assert "FROM USER_CONSTRAINTS" in executed[1][0]
    assert "ORDER BY t.ID" in executed[2][0]
    assert "ROWIDTOCHAR(t.ROWID) AS ROW_ID_META" in executed[2][0]


def test_get_table_data_orders_by_header_id_primary_key(monkeypatch):
    service = DatabaseService()
    executed = []

    class FakeCursor:
        def __init__(self):
            self.description = []
            self._fetchall_result = []

        def execute(self, sql, params=None):
            executed.append((sql, params))
            if "FROM USER_CONSTRAINTS" in sql:
                self._fetchall_result = [("HEADER_ID",)]
            elif sql.startswith("SELECT ROWIDTOCHAR"):
                self.description = [
                    ("ROW_ID_META", None, None, None, None, None, None),
                    ("HEADER_ID", None, None, None, None, None, None),
                    ("TENPOU_MEI", None, None, None, None, None, None),
                ]
                self._fetchall_result = [
                    ("AAABBB==", "HDR-001", "本店"),
                ]

        def fetchone(self):
            return (1,)

        def fetchall(self):
            return self._fetchall_result

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
    monkeypatch.setattr(service, "_get_allowed_table_set", lambda: {"RECEIPT_H"})

    result = service.get_table_data("RECEIPT_H", limit=20, offset=0)

    assert result["success"] is True
    assert result["columns"] == ["HEADER_ID", "TENPOU_MEI"]
    assert result["rows"] == [
        {"ROW_ID_META": "AAABBB==", "HEADER_ID": "HDR-001", "TENPOU_MEI": "本店"},
    ]
    assert "ORDER BY t.HEADER_ID" in executed[2][0]


def test_get_table_data_serializes_lob_and_memoryview_values(monkeypatch):
    service = DatabaseService()

    class FakeLOB:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return self.payload

    class FakeCursor:
        def __init__(self):
            self.description = []
            self._fetchall_result = []

        def execute(self, sql, params=None):
            if "FROM USER_CONSTRAINTS" in sql:
                self._fetchall_result = [("ID",)]
            elif sql.startswith("SELECT ROWIDTOCHAR"):
                self.description = [
                    ("ROW_ID_META", None, None, None, None, None, None),
                    ("ID", None, None, None, None, None, None),
                    ("ANALYSIS_RESULT", None, None, None, None, None, None),
                    ("RAW_BYTES", None, None, None, None, None, None),
                ]
                self._fetchall_result = [
                    ("AAABBB==", "ID-001", FakeLOB(b'{"status":"done"}'), memoryview(b"\xff\x00")),
                ]

        def fetchone(self):
            return (1,)

        def fetchall(self):
            return self._fetchall_result

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
    monkeypatch.setattr(service, "_get_allowed_table_set", lambda: {"SLIPS_CATEGORY"})

    result = service.get_table_data("SLIPS_CATEGORY", limit=20, offset=0)

    assert result["success"] is True
    assert result["rows"] == [
        {
            "ROW_ID_META": "AAABBB==",
            "ID": "ID-001",
            "ANALYSIS_RESULT": '{"status":"done"}',
            "RAW_BYTES": "<BLOB 2 bytes>",
        }
    ]


def test_get_table_data_returns_success_when_table_disappears_mid_query(monkeypatch, caplog):
    service = DatabaseService()

    class FakeCursor:
        def execute(self, sql, params=None):
            if sql == "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1":
                return None
            if sql == "SELECT COUNT(*) FROM RECEIPT_H":
                raise RuntimeError(
                    'ORA-00942: table or view "ADMIN"."RECEIPT_H" does not exist'
                )
            raise AssertionError(f'unexpected sql: {sql}')

        def fetchone(self):
            return (1,)

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
    monkeypatch.setattr(service, "_get_allowed_table_set", lambda: {"RECEIPT_H"})

    with caplog.at_level(logging.WARNING, logger="denpyo_toroku.app.services.database_service"):
        result = service.get_table_data("RECEIPT_H", limit=20, offset=40)

    assert result == {
        "success": True,
        "table_name": "RECEIPT_H",
        "columns": [],
        "rows": [],
        "total": 0,
        "limit": 20,
        "offset": 40,
    }
    assert any(
        record.levelno == logging.WARNING and "テーブルが存在しません (RECEIPT_H)" in record.message
        for record in caplog.records
    )
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)


def test_delete_table_row_by_rowid_cascades_line_rows_when_deleting_header(monkeypatch):
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
            if normalized_sql.startswith("SELECT HEADER_ID FROM RECEIPT_H"):
                self._fetchone_result = ("HDR-001",)
                self.rowcount = 1
            elif normalized_sql.startswith("DELETE FROM RECEIPT_L"):
                self.rowcount = 2
            elif normalized_sql.startswith("DELETE FROM RECEIPT_H"):
                self.rowcount = 1
            else:
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
    monkeypatch.setattr(service, "_get_allowed_table_set", lambda: {"RECEIPT_H", "RECEIPT_L"})
    monkeypatch.setattr(
        service,
        "get_allowed_table_names",
        lambda: [
            {
                "category_id": 1,
                "category_name": "領収書",
                "header_table_name": "RECEIPT_H",
                "line_table_name": "RECEIPT_L",
            }
        ],
    )

    result = service.delete_table_row_by_rowid("RECEIPT_H", "AAABBB==")

    assert result == {
        "success": True,
        "deleted": 1,
        "detail_deleted": 2,
        "table_type": "header",
    }
    assert commit_calls == [True]
    assert executed == [
        ("SELECT HEADER_ID FROM RECEIPT_H WHERE ROWID = CHARTOROWID(:rid)", {"rid": "AAABBB=="}),
        ("DELETE FROM RECEIPT_L WHERE HEADER_ID = :header_id", {"header_id": "HDR-001"}),
        ("DELETE FROM RECEIPT_H WHERE ROWID = CHARTOROWID(:rid)", {"rid": "AAABBB=="}),
    ]


def test_delete_table_row_by_rowid_does_not_delete_header_when_deleting_line(monkeypatch):
    service = DatabaseService()
    executed = []
    commit_calls = []

    class FakeCursor:
        def __init__(self):
            self.rowcount = 0

        def execute(self, sql, params=None):
            normalized_sql = " ".join(sql.split())
            executed.append((normalized_sql, params))
            if normalized_sql.startswith("DELETE FROM RECEIPT_L"):
                self.rowcount = 1
                return
            raise AssertionError(f"unexpected sql: {normalized_sql}")

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
    monkeypatch.setattr(service, "_get_allowed_table_set", lambda: {"RECEIPT_H", "RECEIPT_L"})
    monkeypatch.setattr(
        service,
        "get_allowed_table_names",
        lambda: [
            {
                "category_id": 1,
                "category_name": "領収書",
                "header_table_name": "RECEIPT_H",
                "line_table_name": "RECEIPT_L",
            }
        ],
    )

    result = service.delete_table_row_by_rowid("RECEIPT_L", "AAABBB==")

    assert result == {
        "success": True,
        "deleted": 1,
        "detail_deleted": 0,
        "table_type": "line",
    }
    assert commit_calls == [True]
    assert executed == [
        ("DELETE FROM RECEIPT_L WHERE ROWID = CHARTOROWID(:rid)", {"rid": "AAABBB=="}),
    ]
