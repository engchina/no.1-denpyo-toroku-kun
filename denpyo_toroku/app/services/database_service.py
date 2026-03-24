"""
データベースサービス

Oracle ADB (Autonomous Database) との連携を管理します。
- 接続プール管理（遅延初期化）
- 管理テーブルの初期化
- 伝票データの登録・検索
- 動的DDL実行（AI提案のテーブル作成）

参考: no.1-semantic-doc-search/backend/app/services/database_service.py
"""
import logging
import json
import os
import re
import threading
import time
import hashlib
import datetime as dt
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# oracledb モジュールの遅延インポート
try:
    import oracledb
    ORACLEDB_AVAILABLE = True
except ImportError:
    logger.warning("oracledb モジュールが利用できません。pip install oracledb を実行してください。")
    ORACLEDB_AVAILABLE = False


# 管理テーブル DDL
_MANAGEMENT_TABLES_DDL = [
    """
    CREATE TABLE DENPYO_FILES (
        ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        FILE_NAME VARCHAR2(500) NOT NULL,
        ORIGINAL_FILE_NAME VARCHAR2(500),
        OBJECT_STORAGE_PATH VARCHAR2(1000),
        CONTENT_TYPE VARCHAR2(100),
        FILE_SIZE NUMBER,
        STATUS VARCHAR2(50) DEFAULT 'UPLOADED',
        ANALYSIS_KIND VARCHAR2(30),
        ANALYSIS_RESULT BLOB,
        ANALYSIS_RESULT_1 BLOB,
        ANALYSIS_RESULT_2 BLOB,
        ANALYSIS_RESULT_3 BLOB,
        ANALYZED_AT TIMESTAMP,
        UPLOADED_BY VARCHAR2(100),
        UPLOADED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE DENPYO_CATEGORIES (
        ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        CATEGORY_NAME VARCHAR2(200) NOT NULL,
        CATEGORY_NAME_EN VARCHAR2(200),
        HEADER_TABLE_NAME VARCHAR2(128),
        LINE_TABLE_NAME VARCHAR2(128),
        DESCRIPTION VARCHAR2(1000),
        SELECT_AI_PROFILE_NAME VARCHAR2(128),
        SELECT_AI_TEAM_NAME VARCHAR2(128),
        SELECT_AI_READY NUMBER(1) DEFAULT 0,
        SELECT_AI_SYNCED_AT TIMESTAMP,
        SELECT_AI_CONFIG_HASH VARCHAR2(64),
        SELECT_AI_LAST_ERROR VARCHAR2(2000),
        IS_ACTIVE NUMBER(1) DEFAULT 1,
        CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT UQ_CATEGORY_NAME UNIQUE (CATEGORY_NAME),
        CONSTRAINT UQ_CAT_NAME_EN UNIQUE (CATEGORY_NAME_EN),
        CONSTRAINT UQ_CAT_HDR_TBL UNIQUE (HEADER_TABLE_NAME),
        CONSTRAINT UQ_CAT_LINE_TBL UNIQUE (LINE_TABLE_NAME)
    )
    """,
    """
    CREATE TABLE DENPYO_REGISTRATIONS (
        ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        FILE_ID NUMBER NOT NULL,
        CATEGORY_ID NUMBER,
        CATEGORY_NAME VARCHAR2(200),
        HEADER_TABLE_NAME VARCHAR2(128),
        LINE_TABLE_NAME VARCHAR2(128),
        HEADER_RECORD_ID NUMBER,
        LINE_COUNT NUMBER DEFAULT 0,
        AI_CONFIDENCE NUMBER(5,4),
        STATUS VARCHAR2(50) DEFAULT 'REGISTERED',
        REGISTERED_BY VARCHAR2(100),
        REGISTERED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT FK_REG_FILE FOREIGN KEY (FILE_ID) REFERENCES DENPYO_FILES(ID),
        CONSTRAINT FK_REG_CATEGORY FOREIGN KEY (CATEGORY_ID) REFERENCES DENPYO_CATEGORIES(ID)
    )
    """,
    """
    CREATE TABLE DENPYO_ACTIVITY_LOG (
        ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        ACTIVITY_TYPE VARCHAR2(50) NOT NULL,
        DESCRIPTION VARCHAR2(1000),
        FILE_ID NUMBER,
        REGISTRATION_ID NUMBER,
        USER_NAME VARCHAR2(100),
        CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE DENPYO_ID_SEQUENCES (
        TABLE_NAME VARCHAR2(128) NOT NULL,
        SEQ_DATE CHAR(8) NOT NULL,
        LAST_VALUE NUMBER NOT NULL,
        UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT PK_DENPYO_ID_SEQUENCES PRIMARY KEY (TABLE_NAME, SEQ_DATE)
    )
    """,
]

def _sql_literal(value: str) -> str:
    return (value or "").replace("'", "''")


_SLIPS_RAW_DEFAULT_PREFIX = os.environ.get("OCI_SLIPS_RAW_PREFIX", "denpyo-raw") or "denpyo-raw"
_SLIPS_CATEGORY_DEFAULT_PREFIX = os.environ.get("OCI_SLIPS_CATEGORY_PREFIX", "denpyo-category") or "denpyo-category"

SLIPS_RAW_TABLE_DDL = f"""
CREATE TABLE SLIPS_RAW (
    ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    PREFIX VARCHAR2(50) DEFAULT '{_sql_literal(_SLIPS_RAW_DEFAULT_PREFIX)}' NOT NULL,
    OBJECT_NAME VARCHAR2(1024) NOT NULL,
    BUCKET_NAME VARCHAR2(256) NOT NULL,
    NAMESPACE VARCHAR2(256) NOT NULL,
    FILE_NAME VARCHAR2(512) NOT NULL,
    FILE_SIZE_BYTES NUMBER,
    CONTENT_TYPE VARCHAR2(100),
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT UQ_SLIPS_RAW_OBJECT UNIQUE (NAMESPACE, BUCKET_NAME, OBJECT_NAME)
)
"""

SLIPS_RAW_INDEX_DDL = """
CREATE INDEX IDX_SLIPS_RAW_BUCKET ON SLIPS_RAW(BUCKET_NAME, NAMESPACE)
"""

SLIPS_CATEGORY_TABLE_DDL = f"""
CREATE TABLE SLIPS_CATEGORY (
    ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    PREFIX VARCHAR2(50) DEFAULT '{_sql_literal(_SLIPS_CATEGORY_DEFAULT_PREFIX)}' NOT NULL,
    OBJECT_NAME VARCHAR2(1024) NOT NULL,
    BUCKET_NAME VARCHAR2(256) NOT NULL,
    NAMESPACE VARCHAR2(256) NOT NULL,
    FILE_NAME VARCHAR2(512) NOT NULL,
    FILE_SIZE_BYTES NUMBER,
    CONTENT_TYPE VARCHAR2(100),
    STATUS VARCHAR2(20) DEFAULT 'UPLOADED',
    ANALYSIS_RESULT BLOB,
    ANALYSIS_RESULT_1 BLOB,
    ANALYSIS_RESULT_2 BLOB,
    ANALYSIS_RESULT_3 BLOB,
    ANALYZED_AT TIMESTAMP,
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT UQ_SLIPS_CATEGORY_OBJECT UNIQUE (NAMESPACE, BUCKET_NAME, OBJECT_NAME)
)
"""

_SLIPS_CATEGORY_ALTER_DDLS = [
    "ALTER TABLE SLIPS_CATEGORY ADD (STATUS VARCHAR2(20) DEFAULT 'UPLOADED')",
    "ALTER TABLE SLIPS_CATEGORY ADD (ANALYSIS_RESULT BLOB)",
    "ALTER TABLE SLIPS_CATEGORY ADD (ANALYSIS_RESULT_1 BLOB)",
    "ALTER TABLE SLIPS_CATEGORY ADD (ANALYSIS_RESULT_2 BLOB)",
    "ALTER TABLE SLIPS_CATEGORY ADD (ANALYSIS_RESULT_3 BLOB)",
    "ALTER TABLE SLIPS_CATEGORY ADD (ANALYZED_AT TIMESTAMP)",
    "ALTER TABLE SLIPS_CATEGORY ADD (UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
]

SLIPS_CATEGORY_INDEX_DDL = """
CREATE INDEX IDX_SLIPS_CATEGORY_BUCKET ON SLIPS_CATEGORY(BUCKET_NAME, NAMESPACE)
"""

_HEADER_ID_COLUMN_NAME = "HEADER_ID"
_LINE_ID_COLUMN_NAME = "LINE_ID"
_LEGACY_USER_TABLE_ID_COLUMN_NAME = "ID"
_USER_TABLE_SYSTEM_ID_COLUMN_NAMES = {_HEADER_ID_COLUMN_NAME, _LINE_ID_COLUMN_NAME}
_SYSTEM_ID_COLUMN_MAX_LENGTH = 32
_SYSTEM_ID_JP_NAMES = {
    _HEADER_ID_COLUMN_NAME: "ヘッダーID",
    _LINE_ID_COLUMN_NAME: "明細ID",
}

_SELECT_AI_CREDENTIAL_PREFIX = "DTAICR_"
_SELECT_AI_PROFILE_PREFIX = "DTAIPR_"
_SELECT_AI_TOOL_PREFIX = "DTAITL_"
_SELECT_AI_AGENT_PREFIX = "DTAIAG_"
_SELECT_AI_TASK_PREFIX = "DTAITS_"
_SELECT_AI_TEAM_PREFIX = "DTAITM_"
_SELECT_AI_MAX_IDENTIFIER_LENGTH = 30
_SELECT_AI_DEFAULT_RESPONSE_LANGUAGE = "日本語"
_SELECT_AI_AGENT_ROLE = (
    "You are the Denpyo registration application's Oracle data search agent. "
    "Translate user questions into one safe Oracle SELECT statement by using the SQL tool. "
    "Never invent tables or columns."
)
_SELECT_AI_TASK_INSTRUCTION = (
    "Use the SQL tool to create exactly one Oracle SELECT statement for the user's request. "
    "Return strict JSON only with keys sql and explanation. "
    "sql must be a single SELECT statement without markdown, comments, or trailing narration. "
    "explanation must be concise and written in Japanese."
)
_SELECT_AI_XAI_GROK_REGIONS = {
    "US-ASHBURN-1",
    "US-CHICAGO-1",
    "US-PHOENIX-1",
}
_SELECT_AI_REGION_MODEL_FALLBACKS = {
    "AP-OSAKA-1": "meta.llama-3.3-70b-instruct",
    "EU-FRANKFURT-1": "meta.llama-3.3-70b-instruct",
    "UK-LONDON-1": "meta.llama-3.3-70b-instruct",
    "SA-SAOPAULO-1": "meta.llama-3.3-70b-instruct",
}
_CATEGORY_SELECT_AI_COLUMN_DEFINITIONS = [
    ("SELECT_AI_PROFILE_NAME", "SELECT_AI_PROFILE_NAME VARCHAR2(128)"),
    ("SELECT_AI_TEAM_NAME", "SELECT_AI_TEAM_NAME VARCHAR2(128)"),
    ("SELECT_AI_READY", "SELECT_AI_READY NUMBER(1) DEFAULT 0"),
    ("SELECT_AI_SYNCED_AT", "SELECT_AI_SYNCED_AT TIMESTAMP"),
    ("SELECT_AI_CONFIG_HASH", "SELECT_AI_CONFIG_HASH VARCHAR2(64)"),
    ("SELECT_AI_LAST_ERROR", "SELECT_AI_LAST_ERROR VARCHAR2(2000)"),
]
_ANALYSIS_RESULT_ATTEMPT_COLUMNS = (
    "ANALYSIS_RESULT_1",
    "ANALYSIS_RESULT_2",
    "ANALYSIS_RESULT_3",
)


class DatabaseService:
    """データベースサービス

    Oracle ADB に対する接続管理と伝票データ操作を提供します。
    接続プールの遅延初期化とThin mode対応を行います。
    """

    # プール設定
    POOL_MIN = 2
    POOL_MAX = 10
    POOL_INCREMENT = 1
    TCP_CONNECT_TIMEOUT = 10
    _shared_pool = None
    _shared_pool_config_key: Optional[str] = None
    _pool_lock = threading.RLock()
    _shared_management_tables_initialized = False
    _management_tables_lock = threading.RLock()
    _shared_slips_tables_initialized = False
    _slips_tables_lock = threading.RLock()

    def __init__(self):
        self._pool = None
        self._management_tables_initialized = False
        self._slips_tables_initialized = False
        self._user_ai_agent_teams_team_name_supported: Optional[bool] = None

    @classmethod
    def _reset_shared_initialization_flags(cls) -> None:
        cls._shared_management_tables_initialized = False
        cls._shared_slips_tables_initialized = False

    @staticmethod
    def _wallet_fingerprint(wallet_location: Optional[str]) -> str:
        if not wallet_location or not os.path.isdir(wallet_location):
            return ""

        fingerprints = []
        try:
            for entry_name in sorted(os.listdir(wallet_location)):
                entry_path = os.path.join(wallet_location, entry_name)
                try:
                    stat_result = os.stat(entry_path)
                    fingerprints.append(
                        f"{entry_name}:{stat_result.st_size}:{stat_result.st_mtime_ns}"
                    )
                except OSError:
                    fingerprints.append(f"{entry_name}:unavailable")
        except OSError:
            return wallet_location

        return "|".join(fingerprints)

    def _build_pool_config_key(
        self,
        conn_info: Dict[str, str],
        wallet_location: Optional[str],
    ) -> str:
        raw_value = "|".join(
            [
                conn_info.get("username", ""),
                conn_info.get("password", ""),
                conn_info.get("dsn", ""),
                wallet_location or "",
                self._wallet_fingerprint(wallet_location),
            ]
        )
        return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_pool_not_open_error(error: Exception) -> bool:
        message = str(error or "")
        upper_message = message.upper()
        return "DPY-1002" in upper_message or "CONNECTION POOL IS NOT OPEN" in upper_message

    @staticmethod
    def _is_missing_table_error(error: Exception) -> bool:
        message = str(error or "")
        upper_message = message.upper()
        return "ORA-00942" in upper_message or (
            "TABLE OR VIEW" in upper_message and "DOES NOT EXIST" in upper_message
        )

    def _parse_connection_string(self) -> Dict[str, str]:
        """環境変数から接続文字列をパース"""
        conn_str = os.environ.get("ORACLE_26AI_CONNECTION_STRING", "")
        if not conn_str or "/" not in conn_str or "@" not in conn_str:
            return {"username": "", "password": "", "dsn": ""}
        user_pass, dsn = conn_str.rsplit("@", 1)
        if "/" not in user_pass:
            return {"username": "", "password": "", "dsn": ""}
        username, password = user_pass.split("/", 1)
        return {"username": username.strip(), "password": password.strip(), "dsn": dsn.strip()}

    def _get_wallet_location(self) -> Optional[str]:
        """Wallet場所を取得"""
        tns_admin = os.environ.get("TNS_ADMIN")
        if tns_admin and os.path.exists(tns_admin):
            return tns_admin

        lib_dir = os.environ.get("ORACLE_CLIENT_LIB_DIR")
        if lib_dir:
            wallet_path = os.path.join(lib_dir, "network", "admin")
            if os.path.exists(wallet_path):
                os.environ["TNS_ADMIN"] = wallet_path
                return wallet_path
        return None

    def _ensure_pool(self) -> bool:
        """接続プールの初期化を保証"""
        cls = type(self)
        conn_info = self._parse_connection_string()
        shared_pool = cls._shared_pool

        if shared_pool is not None and (not conn_info["username"] or not conn_info["dsn"]):
            self._pool = shared_pool
            return True

        if not ORACLEDB_AVAILABLE:
            logger.error("oracledb モジュールが利用できません")
            return False

        if not conn_info["username"] or not conn_info["dsn"]:
            logger.error("データベース接続文字列が未設定です")
            return False

        wallet_location = self._get_wallet_location()
        pool_config_key = self._build_pool_config_key(conn_info, wallet_location)

        if shared_pool is not None and cls._shared_pool_config_key == pool_config_key:
            self._pool = shared_pool
            return True

        with cls._pool_lock:
            shared_pool = cls._shared_pool
            if shared_pool is not None and cls._shared_pool_config_key == pool_config_key:
                self._pool = shared_pool
                return True

            if shared_pool is not None:
                try:
                    shared_pool.close()
                    logger.info("データベース接続設定の変更を検知したため既存プールを閉じました")
                except Exception as e:
                    logger.warning("既存接続プール閉鎖エラー: %s", e)
                finally:
                    cls._shared_pool = None
                    cls._shared_pool_config_key = None
                    cls._reset_shared_initialization_flags()

            try:
                pool_kwargs = {
                    "user": conn_info["username"],
                    "password": conn_info["password"],
                    "dsn": conn_info["dsn"],
                    "min": self.POOL_MIN,
                    "max": self.POOL_MAX,
                    "increment": self.POOL_INCREMENT,
                    "tcp_connect_timeout": self.TCP_CONNECT_TIMEOUT,
                }
                if wallet_location:
                    pool_kwargs["config_dir"] = wallet_location
                    pool_kwargs["wallet_location"] = wallet_location
                    pool_kwargs["wallet_password"] = conn_info["password"]

                cls._shared_pool = oracledb.create_pool(**pool_kwargs)
                cls._shared_pool_config_key = pool_config_key
                cls._reset_shared_initialization_flags()
                self._pool = cls._shared_pool
                logger.info(
                    "データベース接続プールを作成しました (min=%d, max=%d)",
                    self.POOL_MIN,
                    self.POOL_MAX,
                )
                return True
            except Exception as e:
                logger.error("接続プール作成エラー: %s", e, exc_info=True)
                self._pool = None
                cls._shared_pool = None
                cls._shared_pool_config_key = None
                return False

    @contextmanager
    def get_connection(self):
        """接続プールからコネクションを取得するコンテキストマネージャー"""
        cls = type(self)
        connection = None
        pool = None

        for attempt in range(2):
            if not self._ensure_pool():
                raise ConnectionError("データベース接続プールが利用できません")

            pool = cls._shared_pool
            if pool is None:
                raise ConnectionError("データベース接続プールが初期化されていません")

            try:
                connection = pool.acquire()
                break
            except Exception as e:
                if attempt > 0 or not self._is_pool_not_open_error(e):
                    raise

                logger.warning("closed な接続プールを検知したため再初期化します: %s", e)
                with cls._pool_lock:
                    if cls._shared_pool is pool:
                        cls._shared_pool = None
                        cls._shared_pool_config_key = None
                        cls._reset_shared_initialization_flags()
                self._pool = None
                pool = None

        if connection is None or pool is None:
            raise ConnectionError("データベース接続の取得に失敗しました")

        try:
            yield connection
        finally:
            if connection is not None:
                try:
                    pool.release(connection)
                except Exception:
                    pass

    def initialize_tables(self) -> Dict[str, Any]:
        """管理テーブルを初期化"""
        results = []
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    for ddl in _MANAGEMENT_TABLES_DDL:
                        table_name = ddl.strip().split("(")[0].split()[-1]
                        try:
                            cursor.execute(ddl)
                            results.append({"table": table_name, "status": "created"})
                            logger.info("テーブルを作成しました: %s", table_name)
                        except Exception as e:
                            error_str = str(e)
                            if "ORA-00955" in error_str:
                                results.append({"table": table_name, "status": "already_exists"})
                            else:
                                results.append({"table": table_name, "status": "error", "message": str(e)})
                                logger.error("テーブル作成エラー (%s): %s", table_name, e)

                    for table_name, ddl in (
                        ("SLIPS_RAW", SLIPS_RAW_TABLE_DDL),
                        ("IDX_SLIPS_RAW_BUCKET", SLIPS_RAW_INDEX_DDL),
                        ("SLIPS_CATEGORY", SLIPS_CATEGORY_TABLE_DDL),
                        ("IDX_SLIPS_CATEGORY_BUCKET", SLIPS_CATEGORY_INDEX_DDL),
                    ):
                        try:
                            cursor.execute(ddl)
                            results.append({"table": table_name, "status": "created"})
                            logger.info("テーブルを作成しました: %s", table_name)
                        except Exception as e:
                            error_str = str(e)
                            if "ORA-00955" in error_str:
                                results.append({"table": table_name, "status": "already_exists"})
                            else:
                                results.append({"table": table_name, "status": "error", "message": str(e)})
                                logger.error("テーブル作成エラー (%s): %s", table_name, e)
                    conn.commit()

            return {"success": True, "tables": results}
        except Exception as e:
            logger.error("テーブル初期化エラー: %s", e, exc_info=True)
            return {"success": False, "message": str(e), "tables": results}

    def _ensure_management_tables(self) -> bool:
        """DENPYO_* 管理テーブルの存在を保証"""
        cls = type(self)
        if cls._shared_management_tables_initialized:
            self._management_tables_initialized = True
            return True

        with cls._management_tables_lock:
            if cls._shared_management_tables_initialized:
                self._management_tables_initialized = True
                return True

            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        for ddl in _MANAGEMENT_TABLES_DDL:
                            try:
                                cursor.execute(ddl)
                            except Exception as e:
                                if "ORA-00955" not in str(e):
                                    logger.error("管理テーブル DDL 実行エラー: %s", e, exc_info=True)
                                    return False
                        self._ensure_table_columns(
                            cursor,
                            "DENPYO_FILES",
                            [
                                ("ANALYSIS_KIND", "ANALYSIS_KIND VARCHAR2(30)"),
                                ("ANALYSIS_RESULT", "ANALYSIS_RESULT BLOB"),
                                ("ANALYSIS_RESULT_1", "ANALYSIS_RESULT_1 BLOB"),
                                ("ANALYSIS_RESULT_2", "ANALYSIS_RESULT_2 BLOB"),
                                ("ANALYSIS_RESULT_3", "ANALYSIS_RESULT_3 BLOB"),
                                ("ANALYZED_AT", "ANALYZED_AT TIMESTAMP"),
                            ],
                        )
                        self._ensure_table_columns(
                            cursor,
                            "DENPYO_CATEGORIES",
                            _CATEGORY_SELECT_AI_COLUMN_DEFINITIONS,
                        )
                        self._ensure_blob_column(cursor, "DENPYO_FILES", "ANALYSIS_RESULT")
                        for column_name in _ANALYSIS_RESULT_ATTEMPT_COLUMNS:
                            self._ensure_blob_column(cursor, "DENPYO_FILES", column_name)
                        self._backfill_registration_category_ids(cursor)
                    conn.commit()
                cls._shared_management_tables_initialized = True
                self._management_tables_initialized = True
                return True
            except Exception as e:
                logger.error("管理テーブル初期化エラー: %s", e, exc_info=True)
                return False

    def _ensure_table_columns(
        self,
        cursor,
        table_name: str,
        column_definitions: List[tuple[str, str]],
    ) -> None:
        """既存テーブルに不足カラムがあれば追加する"""
        cursor.execute(
            "SELECT COLUMN_NAME FROM USER_TAB_COLUMNS WHERE TABLE_NAME = :1",
            [table_name.upper()],
        )
        existing_columns = {str(row[0]).upper() for row in cursor.fetchall()}
        for column_name, column_ddl in column_definitions:
            if column_name.upper() in existing_columns:
                continue
            try:
                cursor.execute(f"ALTER TABLE {table_name.upper()} ADD ({column_ddl})")
                logger.info("テーブル %s にカラムを追加しました: %s", table_name.upper(), column_name.upper())
            except Exception as e:
                error_str = str(e)
                if "ORA-01430" in error_str:
                    continue
                logger.error(
                    "テーブル %s へのカラム追加エラー (%s): %s",
                    table_name.upper(),
                    column_name.upper(),
                    e,
                    exc_info=True,
                )
                raise

    def _backfill_registration_category_ids(self, cursor) -> None:
        """履歴登録レコードの CATEGORY_ID をカテゴリ定義から補完する。"""
        cursor.execute(
            """
            UPDATE DENPYO_REGISTRATIONS r
               SET CATEGORY_ID = (
                   SELECT c.ID
                     FROM DENPYO_CATEGORIES c
                    WHERE UPPER(NVL(c.HEADER_TABLE_NAME, '')) = UPPER(NVL(r.HEADER_TABLE_NAME, ''))
                      AND UPPER(NVL(c.LINE_TABLE_NAME, '')) = UPPER(NVL(r.LINE_TABLE_NAME, ''))
               )
             WHERE r.CATEGORY_ID IS NULL
               AND EXISTS (
                   SELECT 1
                     FROM DENPYO_CATEGORIES c
                    WHERE UPPER(NVL(c.HEADER_TABLE_NAME, '')) = UPPER(NVL(r.HEADER_TABLE_NAME, ''))
                      AND UPPER(NVL(c.LINE_TABLE_NAME, '')) = UPPER(NVL(r.LINE_TABLE_NAME, ''))
               )
            """
        )
        updated = getattr(cursor, "rowcount", 0) or 0
        if updated > 0:
            logger.info("登録レコードの CATEGORY_ID を %d 件補完しました", updated)

    def _get_column_data_type(self, cursor, table_name: str, column_name: str) -> str:
        cursor.execute(
            """SELECT DATA_TYPE
                 FROM USER_TAB_COLUMNS
                WHERE TABLE_NAME = :1
                  AND COLUMN_NAME = :2""",
            [table_name.upper(), column_name.upper()],
        )
        row = cursor.fetchone()
        return str(row[0]).upper() if row and row[0] else ""

    @staticmethod
    def _normalize_oracle_data_type(data_type: str) -> str:
        normalized = str(data_type or "").strip().upper()
        if normalized.startswith("TIMESTAMP"):
            return "TIMESTAMP"
        if normalized.startswith("DATE"):
            return "DATE"
        if normalized.startswith("NUMBER"):
            return "NUMBER"
        if normalized.startswith("VARCHAR2"):
            return "VARCHAR2"
        return normalized

    def _get_table_column_data_types(self, cursor, table_name: str) -> Dict[str, str]:
        cursor.execute(
            """SELECT COLUMN_NAME, DATA_TYPE
                 FROM USER_TAB_COLUMNS
                WHERE TABLE_NAME = :1""",
            [table_name.upper()],
        )
        return {
            str(row[0]).upper(): self._normalize_oracle_data_type(row[1])
            for row in cursor.fetchall() or []
            if row and row[0]
        }

    @staticmethod
    def _normalize_timestamp_value(value: dt.datetime) -> dt.datetime:
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    @classmethod
    def _parse_date_literal(cls, value: Any, column_name: str) -> Optional[dt.date]:
        if value is None:
            return None
        if isinstance(value, dt.datetime):
            return cls._normalize_timestamp_value(value).date()
        if isinstance(value, dt.date):
            return value
        if not isinstance(value, str):
            raise ValueError(f"カラム {column_name} の日付形式が不正です: {value}")

        normalized = value.strip()
        if not normalized:
            return None

        try:
            return dt.date.fromisoformat(normalized)
        except ValueError:
            pass

        iso_candidate = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        try:
            return cls._normalize_timestamp_value(dt.datetime.fromisoformat(iso_candidate)).date()
        except ValueError:
            pass

        for fmt in (
            "%Y/%m/%d",
            "%Y%m%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
        ):
            try:
                return dt.datetime.strptime(normalized, fmt).date()
            except ValueError:
                continue

        raise ValueError(f"カラム {column_name} の日付形式が不正です: {value}")

    @classmethod
    def _parse_timestamp_literal(cls, value: Any, column_name: str) -> Optional[dt.datetime]:
        if value is None:
            return None
        if isinstance(value, dt.datetime):
            return cls._normalize_timestamp_value(value)
        if isinstance(value, dt.date):
            return dt.datetime.combine(value, dt.time.min)
        if not isinstance(value, str):
            raise ValueError(f"カラム {column_name} の日時形式が不正です: {value}")

        normalized = value.strip()
        if not normalized:
            return None

        iso_candidate = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        try:
            return cls._normalize_timestamp_value(dt.datetime.fromisoformat(iso_candidate))
        except ValueError:
            pass

        if "T" not in normalized:
            try:
                return dt.datetime.combine(dt.date.fromisoformat(normalized), dt.time.min)
            except ValueError:
                pass

        for fmt in (
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M",
            "%Y%m%d%H%M%S",
            "%Y%m%d",
        ):
            try:
                parsed = dt.datetime.strptime(normalized, fmt)
                if fmt in ("%Y/%m/%d", "%Y%m%d"):
                    parsed = dt.datetime.combine(parsed.date(), dt.time.min)
                return parsed
            except ValueError:
                continue

        raise ValueError(f"カラム {column_name} の日時形式が不正です: {value}")

    @classmethod
    def _coerce_insert_value(cls, value: Any, data_type: str, column_name: str) -> Any:
        normalized_type = cls._normalize_oracle_data_type(data_type)
        if normalized_type == "NUMBER":
            if value is None:
                return None
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float, Decimal)):
                return value
            if not isinstance(value, str):
                raise ValueError(f"カラム {column_name} の数値形式が不正です: {value}")

            normalized = (
                value.strip()
                .replace(",", "")
                .replace("，", "")
                .replace("¥", "")
                .replace("￥", "")
            )
            if not normalized:
                return None
            try:
                if re.fullmatch(r"[+-]?\d+", normalized):
                    return int(normalized)
                return Decimal(normalized)
            except (InvalidOperation, ValueError):
                raise ValueError(f"カラム {column_name} の数値形式が不正です: {value}") from None

        if normalized_type == "DATE":
            return cls._parse_date_literal(value, column_name)

        if normalized_type == "TIMESTAMP":
            return cls._parse_timestamp_literal(value, column_name)

        return value

    def _ensure_blob_column(self, cursor, table_name: str, column_name: str) -> None:
        table_name = table_name.upper()
        column_name = column_name.upper()
        existing_type = self._get_column_data_type(cursor, table_name, column_name)
        if existing_type == "BLOB":
            return
        if not existing_type:
            cursor.execute(f"ALTER TABLE {table_name} ADD ({column_name} BLOB)")
            return
        if existing_type != "CLOB":
            logger.warning(
                "テーブル %s.%s は BLOB/CLOB 以外の型です: %s",
                table_name,
                column_name,
                existing_type,
            )
            return

        temp_column = f"{column_name}_TMP"
        temp_type = self._get_column_data_type(cursor, table_name, temp_column)
        if not temp_type:
            cursor.execute(f"ALTER TABLE {table_name} ADD ({temp_column} BLOB)")
        elif temp_type != "BLOB":
            raise ValueError(f"一時カラム {table_name}.{temp_column} の型が不正です: {temp_type}")

        cursor.execute(
            f"""
DECLARE
  v_dest BLOB;
  v_dest_offset INTEGER;
  v_src_offset INTEGER;
  v_lang_ctx INTEGER;
  v_warning INTEGER;
BEGIN
  FOR rec IN (
    SELECT ROWID AS rid, {column_name} AS src_lob
      FROM {table_name}
     WHERE {column_name} IS NOT NULL
  ) LOOP
    DBMS_LOB.CREATETEMPORARY(v_dest, TRUE);
    v_dest_offset := 1;
    v_src_offset := 1;
    v_lang_ctx := DBMS_LOB.DEFAULT_LANG_CTX;
    v_warning := 0;
    DBMS_LOB.CONVERTTOBLOB(
      v_dest,
      rec.src_lob,
      DBMS_LOB.LOBMAXSIZE,
      v_dest_offset,
      v_src_offset,
      NLS_CHARSET_ID('AL32UTF8'),
      v_lang_ctx,
      v_warning
    );
    UPDATE {table_name}
       SET {temp_column} = v_dest
     WHERE ROWID = rec.rid;
    DBMS_LOB.FREETEMPORARY(v_dest);
  END LOOP;
END;"""
        )
        cursor.execute(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
        cursor.execute(f"ALTER TABLE {table_name} RENAME COLUMN {temp_column} TO {column_name}")
        logger.info("テーブル %s の %s を CLOB から BLOB に移行しました", table_name, column_name)

    def _decode_json_blob(self, raw_value: Any) -> Optional[Dict[str, Any]]:
        if raw_value is None:
            return None
        try:
            raw_payload = raw_value.read() if hasattr(raw_value, "read") else raw_value
            if isinstance(raw_payload, memoryview):
                raw_payload = raw_payload.tobytes()
            if isinstance(raw_payload, bytes):
                raw_payload = raw_payload.decode("utf-8")
            if not raw_payload:
                return None
            parsed = json.loads(raw_payload)
            return parsed if isinstance(parsed, dict) else None
        except Exception as e:
            logger.warning("分析結果BLOBのJSON解析に失敗しました: %s", e)
            return None

    def _build_attempt_blob_payloads(self, analysis_result: Dict[str, Any]) -> List[Optional[bytes]]:
        raw_attempts = analysis_result.get("analysis_attempts") if isinstance(analysis_result, dict) else None
        attempts = [attempt for attempt in raw_attempts if isinstance(attempt, dict)] if isinstance(raw_attempts, list) else []
        if not attempts and isinstance(analysis_result, dict):
            attempts = [analysis_result]

        payloads: List[Optional[bytes]] = []
        for index in range(len(_ANALYSIS_RESULT_ATTEMPT_COLUMNS)):
            attempt = attempts[index] if index < len(attempts) else None
            payloads.append(json.dumps(attempt, ensure_ascii=False).encode("utf-8") if attempt else None)
        return payloads

    def _merge_analysis_attempts_into_result(
        self,
        analysis_result: Optional[Dict[str, Any]],
        attempt_rows: List[Any],
    ) -> Optional[Dict[str, Any]]:
        attempt_results = [
            decoded
            for decoded in (self._decode_json_blob(raw_value) for raw_value in attempt_rows)
            if decoded is not None
        ]
        if analysis_result is None:
            if not attempt_results:
                return None
            merged = dict(attempt_results[0])
            merged["analysis_attempts"] = attempt_results
            return merged

        if attempt_results:
            merged = dict(analysis_result)
            merged["analysis_attempts"] = attempt_results
            return merged
        return analysis_result

    def execute_ddl(self, ddl_statement: str) -> Dict[str, Any]:
        """動的DDLを実行（AI提案のテーブル作成用）"""
        statement_to_execute = ddl_statement  # except ブロックからも参照できるよう try 外で初期化
        try:
            statement_to_execute = self._prepare_ddl_for_execution(ddl_statement)
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(statement_to_execute)
                conn.commit()
            return {"success": True, "message": "DDL実行完了"}
        except Exception as e:
            error_str = str(e)
            if "ORA-00955" in error_str:
                return {"success": True, "message": "テーブルは既に存在します"}
            if "ORA-02264" in error_str:
                # 変換後の DDL を渡す（制約名は _qualify_constraint_names で書き換え済み）
                detail = self._describe_ora02264(statement_to_execute, e)
                logger.error("DDL実行エラー: %s", detail, exc_info=True)
                return {"success": False, "message": detail}
            logger.error("DDL実行エラー: %s", e, exc_info=True)
            return {"success": False, "message": str(e)}

    def _describe_ora02264(self, ddl_statement: str, original_error: Exception) -> str:
        """ORA-02264 発生時に、競合している制約名を特定して詳細メッセージを返す"""
        constraint_names = re.findall(
            r'\bCONSTRAINT\s+([A-Za-z0-9_$#"]+)',
            ddl_statement,
            re.IGNORECASE,
        )
        constraint_names = [n.strip('"') for n in constraint_names]
        if not constraint_names:
            return f"制約名がすでに存在します (ORA-02264)。DDL文を確認してください。元エラー: {original_error}"
        try:
            placeholders = ", ".join(f":n{i}" for i in range(len(constraint_names)))
            bind = {f"n{i}": name.upper() for i, name in enumerate(constraint_names)}
            query = (
                f"SELECT constraint_name, table_name, constraint_type "
                f"FROM user_constraints "
                f"WHERE constraint_name IN ({placeholders})"
            )
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, bind)
                    rows = cursor.fetchall()
            if rows:
                conflicts = ", ".join(
                    f"{r[0]}（テーブル: {r[1]}, 種別: {r[2]}）" for r in rows
                )
                return (
                    f"制約名がすでに存在するため DDL を実行できません (ORA-02264)。"
                    f"競合している制約: {conflicts}"
                )
            names_str = ", ".join(constraint_names)
            return (
                f"制約名がすでに存在します (ORA-02264)。"
                f"DDL内の制約名: {names_str}。元エラー: {original_error}"
            )
        except Exception:
            names_str = ", ".join(constraint_names)
            return (
                f"制約名がすでに存在します (ORA-02264)。"
                f"DDL内の制約名: {names_str}。元エラー: {original_error}"
            )

    @staticmethod
    def _qualify_constraint_names(ddl: str) -> str:
        """CREATE TABLE DDL 内の CONSTRAINT 名をテーブル名でプレフィックスし、
        スキーマ全体での名前衝突を防ぐ。

        スキップ条件: 制約名がすでに「<TABLE_NAME>_」で始まっている場合。
        128 字を超える場合は末尾 8 桁の MD5 ハッシュで一意性を保証。
        CREATE TABLE が含まれない DDL（TRIGGER, COMMENT ON 等）はそのまま返す。
        """
        # CREATE TABLE が含まれない DDL はトリガーやコメントなので対象外
        table_match = re.search(r'\bCREATE\s+TABLE\s+(\w+)', ddl, re.IGNORECASE)
        if not table_match:
            return ddl

        table_name = table_match.group(1).upper()
        prefix = table_name + "_"
        _MAX_IDENT = 128  # Oracle 12.2+ の識別子最大長

        def _make_name(constraint_name: str) -> str:
            candidate = f"{table_name}_{constraint_name}"
            if len(candidate) <= _MAX_IDENT:
                return candidate
            # 超過する場合はハッシュ末尾で一意性を保証（合計 128 字）
            hash_sfx = hashlib.md5(candidate.encode()).hexdigest()[:8].upper()
            return f"{candidate[:_MAX_IDENT - 9]}_{hash_sfx}"

        def _replace(m: re.Match) -> str:
            orig = m.group(1).strip('"')
            normalized_orig = orig.upper()
            # 既に「TABLE_NAME_」で始まっている場合も、長すぎる識別子は安全な長さへ正規化する
            if normalized_orig.startswith(prefix):
                safe_name = orig if len(orig) <= _MAX_IDENT else _make_name(orig[len(prefix):])
                return f"CONSTRAINT {safe_name}"
            return f"CONSTRAINT {_make_name(orig)}"

        return re.sub(
            r'\bCONSTRAINT\s+([A-Za-z0-9_$#"]+)',
            _replace,
            ddl,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _prepare_ddl_for_execution(ddl_statement: str) -> str:
        """必要に応じて DDL を EXECUTE IMMEDIATE で包み、疑似レコードを bind と誤解されないようにする。
        CREATE TABLE DDL に対しては制約名をテーブル名でプレフィックスする。
        トリガー DDL は先にラップ判定し、ラップ後に制約名正規化は行わない。
        """
        normalized_statement = (ddl_statement or "").strip()
        if not normalized_statement:
            raise ValueError("DDL文が空です")
        # トリガー等は EXECUTE IMMEDIATE でラップするだけ（制約名変換不要）
        if DatabaseService._requires_execute_immediate_wrapper(normalized_statement):
            return DatabaseService._build_execute_immediate_block(normalized_statement)
        # CREATE TABLE DDL のみ制約名を正規化
        return DatabaseService._qualify_constraint_names(normalized_statement)

    @staticmethod
    def _requires_execute_immediate_wrapper(ddl_statement: str) -> bool:
        upper_statement = ddl_statement.upper()
        return (
            "CREATE OR REPLACE TRIGGER" in upper_statement
            or ":OLD." in upper_statement
            or ":NEW." in upper_statement
        )

    @staticmethod
    def _build_execute_immediate_block(ddl_statement: str) -> str:
        delimiters = (
            ("[", "]"),
            ("{", "}"),
            ("<", ">"),
            ("(", ")"),
            ("!", "!"),
            ("~", "~"),
            ("^", "^"),
        )
        for start_delimiter, end_delimiter in delimiters:
            if start_delimiter not in ddl_statement and end_delimiter not in ddl_statement:
                return f"BEGIN EXECUTE IMMEDIATE q'{start_delimiter}{ddl_statement}{end_delimiter}'; END;"

        escaped_statement = ddl_statement.replace("'", "''")
        return f"BEGIN EXECUTE IMMEDIATE '{escaped_statement}'; END;"

    def _ensure_slips_tables(self) -> bool:
        """SLIPS_RAW / SLIPS_CATEGORY テーブルとインデックスの存在を保証"""
        cls = type(self)
        if cls._shared_slips_tables_initialized:
            self._slips_tables_initialized = True
            return True

        with cls._slips_tables_lock:
            if cls._shared_slips_tables_initialized:
                self._slips_tables_initialized = True
                return True

            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        for ddl in (
                            SLIPS_RAW_TABLE_DDL,
                            SLIPS_RAW_INDEX_DDL,
                            SLIPS_CATEGORY_TABLE_DDL,
                            SLIPS_CATEGORY_INDEX_DDL,
                        ):
                            try:
                                cursor.execute(ddl)
                            except Exception as e:
                                if "ORA-00955" not in str(e):
                                    logger.error("SLIPS テーブル DDL 実行エラー: %s", e, exc_info=True)
                                    return False
                        # 既存テーブルにカラム追加（ORA-01430 は無視）
                        for alter_ddl in _SLIPS_CATEGORY_ALTER_DDLS:
                            try:
                                cursor.execute(alter_ddl)
                            except Exception as e:
                                if "ORA-01430" not in str(e):
                                    logger.warning("SLIPS_CATEGORY ALTER エラー (無視可): %s", e)
                        self._ensure_blob_column(cursor, "SLIPS_CATEGORY", "ANALYSIS_RESULT")
                        for column_name in _ANALYSIS_RESULT_ATTEMPT_COLUMNS:
                            self._ensure_blob_column(cursor, "SLIPS_CATEGORY", column_name)
                    conn.commit()
                cls._shared_slips_tables_initialized = True
                self._slips_tables_initialized = True
                return True
            except Exception as e:
                logger.error("SLIPS テーブル初期化エラー: %s", e, exc_info=True)
                return False

    def insert_slip_record(
        self,
        slip_kind: str,
        object_name: str,
        bucket_name: str,
        namespace: str,
        file_name: str,
        file_size_bytes: int,
        content_type: str,
    ) -> Optional[int]:
        """アップロード済みファイル情報を SLIPS_RAW / SLIPS_CATEGORY に登録"""
        if not self._ensure_slips_tables():
            return None

        kind = (slip_kind or "raw").strip().lower()
        if kind == "category":
            table_name = "SLIPS_CATEGORY"
            prefix_value = os.environ.get("OCI_SLIPS_CATEGORY_PREFIX", "denpyo-category") or "denpyo-category"
        elif kind == "raw":
            table_name = "SLIPS_RAW"
            prefix_value = os.environ.get("OCI_SLIPS_RAW_PREFIX", "denpyo-raw") or "denpyo-raw"
        else:
            logger.error("不正な SLIP 種別です: %s", slip_kind)
            return None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    slip_id_var = cursor.var(int)
                    cursor.execute(
                        f"""INSERT INTO {table_name}
                        (PREFIX, OBJECT_NAME, BUCKET_NAME, NAMESPACE, FILE_NAME, FILE_SIZE_BYTES, CONTENT_TYPE)
                        VALUES (:1, :2, :3, :4, :5, :6, :7)
                        RETURNING ID INTO :8""",
                        [
                            prefix_value,
                            object_name,
                            bucket_name,
                            namespace,
                            file_name,
                            file_size_bytes,
                            content_type,
                            slip_id_var,
                        ]
                    )
                conn.commit()
                return slip_id_var.getvalue()[0]
        except Exception as e:
            logger.error("SLIPS 登録エラー (kind=%s): %s", slip_kind, e, exc_info=True)
            return None

    def delete_slip_record(self, slip_kind: str, slip_id: int) -> Dict[str, Any]:
        """SLIPS_RAW / SLIPS_CATEGORY のレコードを削除"""
        kind = (slip_kind or "raw").strip().lower()
        if kind == "category":
            table_name = "SLIPS_CATEGORY"
        elif kind == "raw":
            table_name = "SLIPS_RAW"
        else:
            return {"success": False, "message": f"不正な SLIP 種別です: {slip_kind}"}

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM {table_name} WHERE ID = :1",
                        [slip_id]
                    )
                    deleted = cursor.rowcount
                conn.commit()

            if deleted > 0:
                return {"success": True, "message": f"{table_name} レコードを削除しました"}
            return {"success": False, "message": "ファイルが見つかりません"}
        except Exception as e:
            logger.error("%s 削除エラー (id=%s): %s", table_name, slip_id, e, exc_info=True)
            return {"success": False, "message": str(e)}

    def insert_extracted_data(
        self,
        header_table_name: str,
        line_table_name: str,
        header_fields: List[Dict[str, Any]],
        raw_lines: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """AI抽出データをユーザーテーブルにINSERT

        Args:
            header_table_name: ヘッダーテーブル名
            line_table_name: 明細テーブル名
            header_fields: ヘッダーフィールド [{field_name_en, value, data_type}, ...]
            raw_lines: 明細行データ [{field_name_en: value, ...}, ...]

        Returns:
            {success, header_inserted, line_inserted, message}
        """
        result = {
            "success": True,
            "header_inserted": 0,
            "line_inserted": 0,
            "message": "",
            "errors": [],
        }

        try:
            if not self._ensure_management_tables():
                return {
                    "success": False,
                    "header_inserted": 0,
                    "line_inserted": 0,
                    "message": "管理テーブルの初期化に失敗しました",
                }
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # --- ヘッダーデータ INSERT ---
                    generated_header_id = None
                    if header_table_name and header_fields:
                        if not self._is_safe_table_name(header_table_name):
                            raise ValueError(f"不正なテーブル名です: {header_table_name}")
                        try:
                            header_type_map = self._get_table_column_data_types(cursor, header_table_name)
                            header_cols = []
                            header_vals = []
                            generated_header_id = self._generate_business_id(cursor, header_table_name)
                            header_cols.append(_HEADER_ID_COLUMN_NAME)
                            header_vals.append(generated_header_id)
                            for field in header_fields:
                                col_name = field.get("field_name_en", "").upper()
                                value = field.get("value")
                                if col_name == _HEADER_ID_COLUMN_NAME:
                                    continue
                                if col_name and value is not None:
                                    header_cols.append(col_name)
                                    header_vals.append(
                                        self._coerce_insert_value(
                                            value,
                                            header_type_map.get(col_name) or field.get("data_type", ""),
                                            col_name,
                                        )
                                    )

                            if header_cols:
                                col_str = ", ".join(header_cols)
                                placeholders = ", ".join([f":{i+1}" for i in range(len(header_vals))])
                                insert_sql = f"INSERT INTO {header_table_name.upper()} ({col_str}) VALUES ({placeholders})"
                                cursor.execute(insert_sql, header_vals)
                                result["header_inserted"] = cursor.rowcount
                        except Exception as e:
                            error_message = f"ヘッダーINSERTエラー: {str(e)}"
                            logger.warning(error_message)
                            result["success"] = False
                            result["errors"].append(error_message)

                    # --- 明細データ INSERT ---
                    if line_table_name and raw_lines:
                        if not self._is_safe_table_name(line_table_name):
                            raise ValueError(f"不正なテーブル名です: {line_table_name}")
                        try:
                            line_type_map = self._get_table_column_data_types(cursor, line_table_name)
                        except Exception as e:
                            error_message = f"明細INSERTエラー: {str(e)}"
                            logger.warning(error_message)
                            result["success"] = False
                            result["errors"].append(error_message)
                            line_type_map = None

                        if line_type_map is not None:
                            line_inserted = 0
                            
                            # Gather all standard column names that appear in any raw line
                            all_cols_set = set()
                            for line in raw_lines:
                                for col_name in line.keys():
                                    normalized_col_name = str(col_name or "").upper()
                                    if normalized_col_name not in (_HEADER_ID_COLUMN_NAME, _LINE_ID_COLUMN_NAME):
                                        all_cols_set.add(normalized_col_name)

                            line_cols = [_LINE_ID_COLUMN_NAME]
                            if generated_header_id is not None:
                                line_cols.append(_HEADER_ID_COLUMN_NAME)
                            
                            ordered_dynamic_cols = sorted(list(all_cols_set))
                            line_cols.extend(ordered_dynamic_cols)

                            bulk_vals = []
                            for line in raw_lines:
                                line_id = self._generate_business_id(cursor, line_table_name)
                                row_vals = [line_id]
                                if generated_header_id is not None:
                                    row_vals.append(generated_header_id)

                                # Create a dict with uppercased keys and coerced values
                                processed_line = {}
                                for col_name, value in line.items():
                                    normalized_col_name = str(col_name or "").upper()
                                    if normalized_col_name in (_HEADER_ID_COLUMN_NAME, _LINE_ID_COLUMN_NAME) or value is None:
                                        continue
                                    processed_line[normalized_col_name] = self._coerce_insert_value(
                                        value,
                                        line_type_map.get(normalized_col_name, ""),
                                        normalized_col_name,
                                    )
                                
                                for dynamic_col in ordered_dynamic_cols:
                                    row_vals.append(processed_line.get(dynamic_col, None))
                                
                                bulk_vals.append(row_vals)

                            if line_cols and bulk_vals:
                                try:
                                    col_str = ", ".join(line_cols)
                                    placeholders = ", ".join([f":{i+1}" for i in range(len(line_cols))])
                                    insert_sql = f"INSERT INTO {line_table_name.upper()} ({col_str}) VALUES ({placeholders})"
                                    cursor.executemany(insert_sql, bulk_vals)
                                    line_inserted += len(bulk_vals)
                                except Exception as e:
                                    error_message = f"明細INSERTエラー (executemany): {str(e)}"
                                    logger.warning(error_message)
                                    result["success"] = False
                                    result["errors"].append(error_message)

                            result["line_inserted"] = line_inserted

                conn.commit()

            if result["errors"]:
                if result["header_inserted"] > 0 or result["line_inserted"] > 0:
                    result["message"] = (
                        f"ヘッダー: {result['header_inserted']}件, 明細: {result['line_inserted']}件を登録しました。"
                        f" 一部でエラーが発生しました: {' / '.join(result['errors'])}"
                    )
                else:
                    result["message"] = " / ".join(result["errors"])
            elif result["header_inserted"] > 0 or result["line_inserted"] > 0:
                result["message"] = f"ヘッダー: {result['header_inserted']}件, 明細: {result['line_inserted']}件を登録しました"
            else:
                result["message"] = "登録対象データがありませんでした"

            return result

        except Exception as e:
            logger.error("データINSERTエラー: %s", e, exc_info=True)
            return {
                "success": False,
                "header_inserted": 0,
                "line_inserted": 0,
                "message": f"データINSERTエラー: {str(e)}"
            }

    def insert_file_record(self, file_name: str, original_file_name: str,
                           object_storage_path: str, content_type: str,
                           file_size: int, uploaded_by: str = "") -> Optional[int]:
        """ファイルレコードを登録"""
        if not self._ensure_management_tables():
            return None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    file_id_var = cursor.var(int)
                    cursor.execute(
                        """INSERT INTO DENPYO_FILES
                        (FILE_NAME, ORIGINAL_FILE_NAME, OBJECT_STORAGE_PATH, CONTENT_TYPE, FILE_SIZE, UPLOADED_BY)
                        VALUES (:1, :2, :3, :4, :5, :6)
                        RETURNING ID INTO :7""",
                        [file_name, original_file_name, object_storage_path,
                         content_type, file_size, uploaded_by, file_id_var]
                    )
                    conn.commit()
                    return file_id_var.getvalue()[0]
        except Exception as e:
            logger.error("ファイルレコード登録エラー: %s", e, exc_info=True)
            return None

    def insert_registration(self, file_id: int, category_id: Optional[int],
                            category_name: str,
                            header_table: str, line_table: str,
                            header_record_id: int, line_count: int,
                            ai_confidence: float, registered_by: str = "") -> Optional[int]:
        """登録レコードを作成"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    reg_id_var = cursor.var(int)
                    cursor.execute(
                        """INSERT INTO DENPYO_REGISTRATIONS
                        (FILE_ID, CATEGORY_ID, CATEGORY_NAME, HEADER_TABLE_NAME, LINE_TABLE_NAME,
                         HEADER_RECORD_ID, LINE_COUNT, AI_CONFIDENCE, REGISTERED_BY)
                        VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9)
                        RETURNING ID INTO :10""",
                        [file_id, category_id, category_name, header_table, line_table,
                         header_record_id, line_count, ai_confidence, registered_by, reg_id_var]
                    )
                    conn.commit()
                    return reg_id_var.getvalue()[0]
        except Exception as e:
            logger.error("登録レコード作成エラー: %s", e, exc_info=True)
            return None

    def upsert_category(self, category_name: str, category_name_en: str,
                        header_table_name: str, line_table_name: str,
                        description: str = "") -> Optional[int]:
        """カテゴリレコードを作成または更新"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # 既存チェック
                    cursor.execute(
                        "SELECT ID FROM DENPYO_CATEGORIES WHERE CATEGORY_NAME = :1",
                        [category_name]
                    )
                    row = cursor.fetchone()

                    if row:
                        # 更新
                        category_id = row[0]
                        cursor.execute(
                            """UPDATE DENPYO_CATEGORIES
                            SET CATEGORY_NAME_EN = :1, HEADER_TABLE_NAME = :2,
                                LINE_TABLE_NAME = :3, DESCRIPTION = :4,
                                UPDATED_AT = CURRENT_TIMESTAMP
                            WHERE ID = :5""",
                            [category_name_en, header_table_name,
                             line_table_name, description, category_id]
                        )
                    else:
                        # 新規作成
                        cat_id_var = cursor.var(int)
                        cursor.execute(
                            """INSERT INTO DENPYO_CATEGORIES
                            (CATEGORY_NAME, CATEGORY_NAME_EN, HEADER_TABLE_NAME,
                             LINE_TABLE_NAME, DESCRIPTION)
                            VALUES (:1, :2, :3, :4, :5)
                            RETURNING ID INTO :6""",
                            [category_name, category_name_en, header_table_name,
                             line_table_name, description, cat_id_var]
                        )
                        category_id = cat_id_var.getvalue()[0]

                    conn.commit()
                    return category_id
        except Exception as e:
            logger.error("カテゴリ upsert エラー: %s", e, exc_info=True)
            return None

    # ── カテゴリ管理 ─────────────────────────────────

    def get_categories(self) -> List[Dict[str, Any]]:
        """全カテゴリ一覧を実テーブルの行数付きで取得"""
        if not self._ensure_management_tables():
            return []
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT c.ID, c.CATEGORY_NAME, c.CATEGORY_NAME_EN,
                                  c.HEADER_TABLE_NAME, c.LINE_TABLE_NAME,
                                  c.DESCRIPTION, c.SELECT_AI_PROFILE_NAME, c.SELECT_AI_TEAM_NAME,
                                  c.SELECT_AI_READY, c.SELECT_AI_SYNCED_AT, c.SELECT_AI_CONFIG_HASH,
                                  c.SELECT_AI_LAST_ERROR, c.IS_ACTIVE, c.CREATED_AT, c.UPDATED_AT
                        FROM DENPYO_CATEGORIES c
                        ORDER BY c.CREATED_AT DESC"""
                    )
                    categories = []
                    header_table_names: List[str] = []
                    for row in cursor.fetchall():
                        header_table_name = str(row[3] or "").strip().upper()
                        if self._is_safe_table_name(header_table_name):
                            header_table_names.append(header_table_name)
                        categories.append({
                            "id": row[0],
                            "category_name": row[1],
                            "category_name_en": row[2] or "",
                            "header_table_name": row[3] or "",
                            "line_table_name": row[4] or "",
                            "description": row[5] or "",
                            "select_ai_profile_name": row[6] or "",
                            "select_ai_team_name": row[7] or "",
                            "select_ai_profile_ready": bool(row[8]),
                            "select_ai_last_synced_at": str(row[9]) if row[9] else "",
                            "select_ai_config_hash": row[10] or "",
                            "select_ai_last_error": row[11] or "",
                            "is_active": bool(row[12]),
                            "created_at": str(row[13]) if row[13] else "",
                            "updated_at": str(row[14]) if row[14] else "",
                            "registration_count": 0,
                        })

                    row_count_map = self._get_existing_table_row_counts(cursor, header_table_names)
                    for category in categories:
                        header_table_name = str(category.get("header_table_name") or "").strip().upper()
                        category["registration_count"] = int(row_count_map.get(header_table_name, 0))
                    return categories
        except Exception as e:
            logger.error("カテゴリ一覧取得エラー: %s", e, exc_info=True)
            return []

    def get_category_by_id(self, category_id: int) -> Optional[Dict[str, Any]]:
        """IDでカテゴリレコードを取得"""
        if not self._ensure_management_tables():
            return None
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, CATEGORY_NAME, CATEGORY_NAME_EN,
                                  HEADER_TABLE_NAME, LINE_TABLE_NAME,
                                  DESCRIPTION, SELECT_AI_PROFILE_NAME, SELECT_AI_TEAM_NAME,
                                  SELECT_AI_READY, SELECT_AI_SYNCED_AT, SELECT_AI_CONFIG_HASH,
                                  SELECT_AI_LAST_ERROR, IS_ACTIVE, CREATED_AT, UPDATED_AT
                        FROM DENPYO_CATEGORIES WHERE ID = :1""",
                        [category_id]
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    return {
                        "id": row[0],
                        "category_name": row[1],
                        "category_name_en": row[2] or "",
                        "header_table_name": row[3] or "",
                        "line_table_name": row[4] or "",
                        "description": row[5] or "",
                        "select_ai_profile_name": row[6] or "",
                        "select_ai_team_name": row[7] or "",
                        "select_ai_profile_ready": bool(row[8]),
                        "select_ai_last_synced_at": str(row[9]) if row[9] else "",
                        "select_ai_config_hash": row[10] or "",
                        "select_ai_last_error": row[11] or "",
                        "is_active": bool(row[12]),
                        "created_at": str(row[13]) if row[13] else "",
                        "updated_at": str(row[14]) if row[14] else "",
                    }
        except Exception as e:
            logger.error("カテゴリ取得エラー (id=%s): %s", category_id, e, exc_info=True)
            return None

    def _save_category_select_ai_profile_metadata_with_cursor(
        self,
        cursor,
        *,
        category_id: int,
        profile_name: str,
        team_name: str,
        config_hash: str,
        ready: bool,
        error_message: str = "",
    ) -> None:
        cursor.execute(
            """UPDATE DENPYO_CATEGORIES
                  SET SELECT_AI_PROFILE_NAME = :1,
                      SELECT_AI_TEAM_NAME = :2,
                      SELECT_AI_READY = :3,
                      SELECT_AI_SYNCED_AT = CURRENT_TIMESTAMP,
                      SELECT_AI_CONFIG_HASH = :4,
                      SELECT_AI_LAST_ERROR = :5,
                      UPDATED_AT = CURRENT_TIMESTAMP
                WHERE ID = :6""",
            [
                (profile_name or "").strip(),
                (team_name or "").strip(),
                1 if ready else 0,
                (config_hash or "").strip(),
                (error_message or "")[:2000],
                category_id,
            ],
        )

    def save_category_select_ai_profile_metadata(
        self,
        *,
        category_id: int,
        profile_name: str,
        team_name: str,
        config_hash: str,
        ready: bool,
        error_message: str = "",
    ) -> bool:
        if not self._ensure_management_tables():
            return False
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    self._save_category_select_ai_profile_metadata_with_cursor(
                        cursor,
                        category_id=category_id,
                        profile_name=profile_name,
                        team_name=team_name,
                        config_hash=config_hash,
                        ready=ready,
                        error_message=error_message,
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.error("カテゴリ Select AI profile メタデータ更新エラー (id=%s): %s", category_id, e, exc_info=True)
            return False

    def get_category_table_schema(self, category_id: int) -> Optional[Dict[str, Any]]:
        """カテゴリに紐づくテーブル構造（HEADER/LINE）を取得"""
        category = self.get_category_by_id(category_id)
        if not category:
            return None

        header_table_name = (category.get("header_table_name") or "").upper()
        line_table_name = (category.get("line_table_name") or "").upper()

        if not header_table_name or not self._is_safe_table_name(header_table_name):
            return None
        if line_table_name and not self._is_safe_table_name(line_table_name):
            return None

        def _fetch_columns(cursor, table_name: str) -> List[Dict[str, Any]]:
            cursor.execute(
                """SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, DATA_PRECISION, DATA_SCALE, NULLABLE
                FROM USER_TAB_COLUMNS
                WHERE TABLE_NAME = :1
                ORDER BY COLUMN_ID""",
                [table_name]
            )
            column_rows = cursor.fetchall()

            # カラムコメントを USER_COL_COMMENTS から取得
            cursor.execute(
                """SELECT COLUMN_NAME, COMMENTS
                FROM USER_COL_COMMENTS
                WHERE TABLE_NAME = :1""",
                [table_name]
            )
            comments_map: Dict[str, str] = {row[0]: (row[1] or "") for row in cursor.fetchall()}

            cols: List[Dict[str, Any]] = []
            for row in column_rows:
                cols.append({
                    "column_name": row[0],
                    "data_type": row[1],
                    "data_length": row[2],
                    "precision": row[3],
                    "scale": row[4],
                    "nullable": row[5],
                    "comment": comments_map.get(row[0], ""),
                })
            return cols

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    header_columns = _fetch_columns(cursor, header_table_name)
                    line_columns = _fetch_columns(cursor, line_table_name) if line_table_name else []

            if not header_columns:
                return None

            return {
                "category_id": category.get("id"),
                "category_name": category.get("category_name", ""),
                "category_name_en": category.get("category_name_en", ""),
                "header_table_name": header_table_name,
                "line_table_name": line_table_name,
                "header_columns": header_columns,
                "line_columns": line_columns,
            }
        except Exception as e:
            logger.error("カテゴリテーブル構造取得エラー (id=%s): %s", category_id, e, exc_info=True)
            return None

    def update_category(self, category_id: int, category_name: str,
                        category_name_en: str, description: str) -> bool:
        """カテゴリの名称・説明を更新（テーブル名は変更不可）"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """UPDATE DENPYO_CATEGORIES
                        SET CATEGORY_NAME = :1, CATEGORY_NAME_EN = :2,
                            DESCRIPTION = :3, UPDATED_AT = CURRENT_TIMESTAMP
                        WHERE ID = :4""",
                        [category_name, category_name_en, description, category_id]
                    )
                    updated = cursor.rowcount
                conn.commit()
                return updated > 0
        except Exception as e:
            logger.error("カテゴリ更新エラー (id=%s): %s", category_id, e, exc_info=True)
            return False

    def find_category_conflicts(
        self,
        category_name: str,
        category_name_en: str = "",
        header_table_name: str = "",
        line_table_name: str = "",
        exclude_category_id: Optional[int] = None,
    ) -> List[str]:
        """カテゴリ名・英語名・テーブル名の重複を検出する"""
        if not self._ensure_management_tables():
            raise ConnectionError("管理テーブルの初期化に失敗しました")

        category_name = (category_name or "").strip()
        category_name_en = (category_name_en or "").strip()
        header_table_name = (header_table_name or "").strip().upper()
        line_table_name = (line_table_name or "").strip().upper()

        conflicts: List[str] = []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                owned_table_names = set()
                if exclude_category_id is not None:
                    cursor.execute(
                        """SELECT HEADER_TABLE_NAME, LINE_TABLE_NAME
                             FROM DENPYO_CATEGORIES
                            WHERE ID = :1""",
                        [exclude_category_id],
                    )
                    owned_row = cursor.fetchone()
                    if owned_row:
                        for table_name in owned_row:
                            normalized_name = str(table_name or "").strip().upper()
                            if normalized_name:
                                owned_table_names.add(normalized_name)

                if category_name:
                    sql = "SELECT ID FROM DENPYO_CATEGORIES WHERE CATEGORY_NAME = :1"
                    params: List[Any] = [category_name]
                    if exclude_category_id is not None:
                        sql += " AND ID <> :2"
                        params.append(exclude_category_id)
                    cursor.execute(sql, params)
                    if cursor.fetchone():
                        conflicts.append(f"伝票分類名 '{category_name}' は既に使用されています")

                if category_name_en:
                    sql = "SELECT ID FROM DENPYO_CATEGORIES WHERE UPPER(CATEGORY_NAME_EN) = :1"
                    params = [category_name_en.upper()]
                    if exclude_category_id is not None:
                        sql += " AND ID <> :2"
                        params.append(exclude_category_id)
                    cursor.execute(sql, params)
                    if cursor.fetchone():
                        conflicts.append(f"伝票分類名（英語） '{category_name_en}' は既に使用されています")

                requested_table_names = [name for name in (header_table_name, line_table_name) if name]
                if requested_table_names:
                    seen_names = set()
                    for table_name in requested_table_names:
                        if table_name in seen_names:
                            conflicts.append(f"テーブル名 '{table_name}' が重複しています")
                            continue
                        seen_names.add(table_name)

                        sql = """
                            SELECT ID
                              FROM DENPYO_CATEGORIES
                             WHERE (UPPER(HEADER_TABLE_NAME) = :table_name
                                OR UPPER(LINE_TABLE_NAME) = :table_name)
                        """
                        params: Dict[str, Any] = {"table_name": table_name}
                        if exclude_category_id is not None:
                            sql += " AND ID <> :exclude_category_id"
                            params["exclude_category_id"] = exclude_category_id
                        cursor.execute(sql, params)
                        if cursor.fetchone():
                            conflicts.append(f"テーブル名 '{table_name}' は既存カテゴリで使用されています")
                            continue

                        if table_name in owned_table_names:
                            continue

                        cursor.execute(
                            "SELECT TABLE_NAME FROM USER_TABLES WHERE TABLE_NAME = :1",
                            [table_name],
                        )
                        if cursor.fetchone():
                            conflicts.append(f"テーブル名 '{table_name}' は既にデータベース上に存在します")

        return conflicts

    def toggle_category_active(self, category_id: int) -> Optional[bool]:
        """カテゴリの有効/無効を切り替え、新しい状態を返す"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """UPDATE DENPYO_CATEGORIES
                        SET IS_ACTIVE = CASE WHEN IS_ACTIVE = 1 THEN 0 ELSE 1 END,
                            UPDATED_AT = CURRENT_TIMESTAMP
                        WHERE ID = :1""",
                        [category_id]
                    )
                    if cursor.rowcount == 0:
                        return None
                    cursor.execute(
                        "SELECT IS_ACTIVE FROM DENPYO_CATEGORIES WHERE ID = :1",
                        [category_id]
                    )
                    new_val = cursor.fetchone()
                conn.commit()
                return bool(new_val[0]) if new_val else None
        except Exception as e:
            logger.error("カテゴリ有効/無効切替エラー (id=%s): %s", category_id, e, exc_info=True)
            return None

    def delete_category(self, category_id: int) -> Dict[str, Any]:
        """カテゴリを削除（登録がある場合は拒否）"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT CATEGORY_NAME, HEADER_TABLE_NAME, LINE_TABLE_NAME FROM DENPYO_CATEGORIES WHERE ID = :1",
                        [category_id],
                    )
                    category_row = cursor.fetchone()
                    if not category_row:
                        return {
                            "success": True,
                            "message": "カテゴリは既に削除されています",
                            "category_name": "",
                            "dropped_tables": [],
                            "already_missing": True,
                        }

                    category_name = category_row[0] or ""
                    header_table_name = str(category_row[1] or "").strip().upper()
                    line_table_name = str(category_row[2] or "").strip().upper()

                    reg_count = self._get_table_row_count_if_exists(cursor, header_table_name)
                    if reg_count > 0:
                        return {
                            "success": False,
                            "message": f"登録済みデータが {reg_count} 件あるため削除できません"
                        }

                    cursor.execute(
                        "DELETE FROM DENPYO_REGISTRATIONS WHERE CATEGORY_ID = :1",
                        [category_id]
                    )

                    dropped_tables: List[str] = []
                    for table_name in [line_table_name, header_table_name]:
                        if not table_name:
                            continue
                        if not self._is_safe_table_name(table_name):
                            logger.warning(
                                "カテゴリ削除時に不正なテーブル名をスキップします (category_id=%s, table=%s)",
                                category_id,
                                table_name,
                            )
                            continue

                        try:
                            cursor.execute(
                                "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1",
                                [table_name],
                            )
                            if int(cursor.fetchone()[0] or 0) == 0:
                                logger.warning(
                                    "カテゴリ削除時にテーブルが既に存在しません (category_id=%s, table=%s)",
                                    category_id,
                                    table_name,
                                )
                                continue

                            cursor.execute(f"DROP TABLE {table_name} PURGE")
                            dropped_tables.append(table_name)
                        except Exception as table_error:
                            if self._is_missing_table_error(table_error):
                                logger.warning(
                                    "カテゴリ削除時にテーブルが既に存在しません (category_id=%s, table=%s): %s",
                                    category_id,
                                    table_name,
                                    table_error,
                                )
                                continue
                            raise

                    cursor.execute(
                        "DELETE FROM DENPYO_CATEGORIES WHERE ID = :1",
                        [category_id]
                    )
                    deleted = cursor.rowcount
                conn.commit()

            if deleted > 0:
                return {
                    "success": True,
                    "message": "カテゴリを削除しました",
                    "category_name": category_name,
                    "dropped_tables": dropped_tables,
                }
            return {
                "success": True,
                "message": "カテゴリは既に削除されています",
                "category_name": category_name if "category_name" in locals() else "",
                "dropped_tables": dropped_tables if "dropped_tables" in locals() else [],
                "already_missing": True,
            }
        except Exception as e:
            logger.error("カテゴリ削除エラー (id=%s): %s", category_id, e, exc_info=True)
            return {"success": False, "message": str(e)}

    def _get_existing_table_row_counts(self, cursor, table_names: List[str]) -> Dict[str, int]:
        """存在するユーザーテーブルの実行数を返す。未存在テーブルは 0 件扱い。"""
        normalized_names: List[str] = []
        seen_names = set()
        for table_name in table_names:
            normalized_name = str(table_name or "").strip().upper()
            if not self._is_safe_table_name(normalized_name) or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            normalized_names.append(normalized_name)

        if not normalized_names:
            return {}

        bind_map = {f"tn{i}": name for i, name in enumerate(normalized_names)}
        in_clause = ", ".join(f":tn{i}" for i in range(len(normalized_names)))

        cursor.execute(
            f"""SELECT TABLE_NAME
                  FROM USER_TABLES
                 WHERE TABLE_NAME IN ({in_clause})""",
            bind_map,
        )
        existing_table_names = {
            str(row[0] or "").strip().upper()
            for row in cursor.fetchall()
            if row and row[0]
        }

        row_count_map: Dict[str, int] = {}
        for table_name in normalized_names:
            if table_name not in existing_table_names:
                row_count_map[table_name] = 0
                continue
            row_count_map[table_name] = self._get_table_row_count_if_exists(cursor, table_name)
        return row_count_map

    def _get_table_row_count_if_exists(self, cursor, table_name: str) -> int:
        """対象テーブルが存在する場合のみ実行数を返す。未存在時は 0。"""
        normalized_table_name = str(table_name or "").strip().upper()
        if not self._is_safe_table_name(normalized_table_name):
            return 0

        cursor.execute(
            "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1",
            [normalized_table_name],
        )
        if int(cursor.fetchone()[0] or 0) == 0:
            return 0

        try:
            cursor.execute(f"SELECT COUNT(*) FROM {normalized_table_name}")
            count_row = cursor.fetchone()
            return int(count_row[0] or 0) if count_row else 0
        except Exception as e:
            if self._is_missing_table_error(e):
                logger.warning("テーブル行数取得時にテーブルが存在しません (%s): %s", normalized_table_name, e)
                return 0
            logger.warning("テーブル行数取得エラー (%s): %s", normalized_table_name, e)
            return 0

    # ── カテゴリ作成フロー ──────────────────────────────

    def get_slips_category_files_by_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        """IDのリストでSLIPS_CATEGORYレコードを取得（OCI Object Storage パス付き）"""
        if not ids:
            return []
        try:
            placeholders = ",".join([f":{i+1}" for i in range(len(ids))])
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""SELECT ID, OBJECT_NAME, BUCKET_NAME, NAMESPACE,
                                   FILE_NAME, FILE_SIZE_BYTES, CONTENT_TYPE, STATUS, CREATED_AT,
                                   CASE WHEN ANALYSIS_RESULT IS NOT NULL THEN 1 ELSE 0 END AS HAS_ANALYSIS_RESULT,
                                   UPDATED_AT
                        FROM SLIPS_CATEGORY
                        WHERE ID IN ({placeholders})
                        ORDER BY CREATED_AT DESC""",
                        ids
                    )
                    result = []
                    for row in cursor.fetchall():
                        result.append({
                            "id": row[0],
                            "object_name": row[1],
                            "bucket_name": row[2],
                            "namespace": row[3],
                            "file_name": row[4],
                            "original_file_name": row[4],
                            "file_size": row[5],
                            "content_type": row[6] or "image/jpeg",
                            "status": row[7] or "UPLOADED",
                            "created_at": str(row[8]) if row[8] else "",
                            "has_analysis_result": bool(row[9]),
                            "updated_at": str(row[10]) if row[10] else "",
                        })
                    return result
        except Exception as e:
            logger.error("SLIPS_CATEGORY ファイル取得エラー (ids=%s): %s", ids, e, exc_info=True)
            return []

    def get_slips_category_file_by_object_name(self, object_name: str) -> Optional[Dict[str, Any]]:
        """OBJECT_NAME で SLIPS_CATEGORY レコードを取得"""
        if not self._ensure_slips_tables():
            return None

        normalized_object_name = (object_name or "").strip()
        if not normalized_object_name:
            return None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, OBJECT_NAME, BUCKET_NAME, NAMESPACE,
                                  FILE_NAME, FILE_SIZE_BYTES, CONTENT_TYPE, STATUS, CREATED_AT,
                                  CASE WHEN ANALYSIS_RESULT IS NOT NULL THEN 1 ELSE 0 END AS HAS_ANALYSIS_RESULT,
                                  UPDATED_AT
                             FROM SLIPS_CATEGORY
                            WHERE OBJECT_NAME = :1""",
                        [normalized_object_name],
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    return {
                        "id": row[0],
                        "object_name": row[1],
                        "bucket_name": row[2],
                        "namespace": row[3],
                        "file_name": row[4],
                        "original_file_name": row[4],
                        "file_size": row[5],
                        "content_type": row[6] or "image/jpeg",
                        "status": row[7] or "UPLOADED",
                        "created_at": str(row[8]) if row[8] else "",
                        "has_analysis_result": bool(row[9]),
                        "updated_at": str(row[10]) if row[10] else "",
                    }
        except Exception as e:
            logger.error("SLIPS_CATEGORY ファイル取得エラー (object_name=%s): %s", object_name, e, exc_info=True)
            return None

    def get_slips_category_analysis_result(self, file_id: int) -> Optional[Dict[str, Any]]:
        """SLIPS_CATEGORY に保存された分析結果を取得"""
        if not self._ensure_slips_tables():
            return None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ANALYSIS_RESULT, ANALYSIS_RESULT_1, ANALYSIS_RESULT_2, ANALYSIS_RESULT_3, ANALYZED_AT
                             FROM SLIPS_CATEGORY
                            WHERE ID = :1""",
                        [file_id],
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None

                    parsed_result = self._merge_analysis_attempts_into_result(
                        self._decode_json_blob(row[0]),
                        list(row[1:4]),
                    )
                    if parsed_result is None:
                        return None
                    return {
                        "analysis_kind": "category",
                        "result": parsed_result,
                        "analyzed_at": str(row[4]) if row[4] else "",
                    }
        except Exception as e:
            logger.error("SLIPS_CATEGORY 分析結果取得エラー (id=%s): %s", file_id, e, exc_info=True)
            return None

    def get_slips_category_analysis_result_by_object_name(self, object_name: str) -> Optional[Dict[str, Any]]:
        """OBJECT_NAME で SLIPS_CATEGORY に保存された分析結果を取得"""
        if not self._ensure_slips_tables():
            return None

        normalized_object_name = (object_name or "").strip()
        if not normalized_object_name:
            return None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ANALYSIS_RESULT, ANALYSIS_RESULT_1, ANALYSIS_RESULT_2, ANALYSIS_RESULT_3, ANALYZED_AT
                             FROM SLIPS_CATEGORY
                            WHERE OBJECT_NAME = :1""",
                        [normalized_object_name],
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None

                    parsed_result = self._merge_analysis_attempts_into_result(
                        self._decode_json_blob(row[0]),
                        list(row[1:4]),
                    )
                    if parsed_result is None:
                        return None
                    return {
                        "analysis_kind": "category",
                        "result": parsed_result,
                        "analyzed_at": str(row[4]) if row[4] else "",
                    }
        except Exception as e:
            logger.error("SLIPS_CATEGORY 分析結果取得エラー (object_name=%s): %s", object_name, e, exc_info=True)
            return None

    def update_category_file_status(self, file_id: int, status: str) -> bool:
        """SLIPS_CATEGORY のステータスを更新"""
        if not self._ensure_slips_tables():
            return False
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE SLIPS_CATEGORY SET STATUS = :1, UPDATED_AT = CURRENT_TIMESTAMP WHERE ID = :2",
                        [status, file_id],
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.error("SLIPS_CATEGORY ステータス更新エラー (id=%s): %s", file_id, e, exc_info=True)
            return False

    def save_category_analysis_result(self, file_id: int, analysis_result: Dict[str, Any]) -> bool:
        """SLIPS_CATEGORY の分析結果を保存"""
        if not self._ensure_slips_tables():
            return False
        try:
            payload = json.dumps(analysis_result, ensure_ascii=False).encode("utf-8")
            attempt_payloads = self._build_attempt_blob_payloads(analysis_result)
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """UPDATE SLIPS_CATEGORY
                           SET ANALYSIS_RESULT = :1,
                               ANALYSIS_RESULT_1 = :2,
                               ANALYSIS_RESULT_2 = :3,
                               ANALYSIS_RESULT_3 = :4,
                               ANALYZED_AT = CURRENT_TIMESTAMP,
                               STATUS = 'ANALYZED',
                               UPDATED_AT = CURRENT_TIMESTAMP
                         WHERE ID = :5""",
                        [payload, *attempt_payloads, file_id],
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.error("SLIPS_CATEGORY 分析結果保存エラー (id=%s): %s", file_id, e, exc_info=True)
            return False

    def get_slips_raw_files_by_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        """IDのリストでSLIPS_RAWレコードを取得（OCI Object Storage パス付き）"""
        if not ids:
            return []
        try:
            placeholders = ",".join([f":{i+1}" for i in range(len(ids))])
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""SELECT ID, OBJECT_NAME, BUCKET_NAME, NAMESPACE,
                                   FILE_NAME, FILE_SIZE_BYTES, CONTENT_TYPE, CREATED_AT
                        FROM SLIPS_RAW
                        WHERE ID IN ({placeholders})
                        ORDER BY CREATED_AT DESC""",
                        ids
                    )
                    result = []
                    for row in cursor.fetchall():
                        result.append({
                            "id": row[0],
                            "object_name": row[1],
                            "bucket_name": row[2],
                            "namespace": row[3],
                            "file_name": row[4],
                            "file_size": row[5],
                            "content_type": row[6] or "application/octet-stream",
                            "created_at": str(row[7]) if row[7] else "",
                        })
                    return result
        except Exception as e:
            logger.error("SLIPS_RAW ファイル取得エラー (ids=%s): %s", ids, e, exc_info=True)
            return []

    def delete_slips_category_file_record(self, file_id: int) -> Dict[str, Any]:
        """SLIPS_CATEGORY のファイルレコードを削除"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM SLIPS_CATEGORY WHERE ID = :1",
                        [file_id]
                    )
                    deleted = cursor.rowcount
                conn.commit()

            if deleted > 0:
                return {"success": True, "message": "SLIPS_CATEGORY ファイルを削除しました"}
            return {"success": False, "message": "ファイルが見つかりません"}
        except Exception as e:
            logger.error("SLIPS_CATEGORY ファイル削除エラー (id=%s): %s", file_id, e, exc_info=True)
            return {"success": False, "message": str(e)}

    @staticmethod
    def _build_ddl_from_columns(
        table_name: str,
        columns: List[Dict[str, Any]],
        id_column_name: str,
        fk_column_name: Optional[str] = None,
    ) -> str:
        """カラム定義リストからCREATE TABLE DDLを生成"""
        col_defs = []
        pk_cols = []
        for col in DatabaseService._normalize_designer_columns(columns, id_column_name, fk_column_name):
            col_name = col.get("column_name", "").upper()
            if not col_name:
                continue
            data_type = col.get("data_type", "VARCHAR2").upper()
            max_length = col.get("max_length")
            precision = col.get("precision")
            scale = col.get("scale")
            is_nullable = col.get("is_nullable", True)
            is_pk = col.get("is_primary_key", False)

            # 型定義
            if data_type == "VARCHAR2":
                length = int(max_length) if max_length else 500
                type_def = f"VARCHAR2({length})"
            elif data_type == "NUMBER":
                if precision and scale:
                    type_def = f"NUMBER({int(precision)},{int(scale)})"
                elif precision:
                    type_def = f"NUMBER({int(precision)})"
                else:
                    type_def = "NUMBER"
            elif data_type in ("DATE", "TIMESTAMP"):
                type_def = data_type
            elif data_type == "CLOB":
                length = int(max_length) if max_length else 4000
                type_def = f"VARCHAR2({length})"
            else:
                type_def = "VARCHAR2(500)"

            null_clause = "" if is_nullable else " NOT NULL"
            col_defs.append(f"    {col_name} {type_def}{null_clause}")
            if is_pk:
                pk_cols.append(col_name)

        if pk_cols:
            pk_name = f"PK_{table_name}"
            col_defs.append(f"    CONSTRAINT {pk_name} PRIMARY KEY ({', '.join(pk_cols)})")

        cols_sql = ",\n".join(col_defs)
        return f"CREATE TABLE {table_name.upper()} (\n{cols_sql}\n)"

    @staticmethod
    def _build_column_comment_ddls(
        table_name: str,
        columns: List[Dict[str, Any]],
        id_column_name: str,
        fk_column_name: Optional[str] = None,
    ) -> List[str]:
        """カラム定義リストから COMMENT ON COLUMN DDL を生成"""
        table_name = (table_name or "").strip().upper()
        if not table_name:
            return []

        ddls: List[str] = []
        for col in DatabaseService._normalize_designer_columns(columns, id_column_name, fk_column_name):
            col_name = str(col.get("column_name") or "").strip().upper()
            comment = str(col.get("column_name_jp") or col.get("comment") or "").strip()
            if not col_name or not comment:
                continue
            ddls.append(
                f"COMMENT ON COLUMN {table_name}.{col_name} IS '{_sql_literal(comment)}'"
            )
        return ddls

    @staticmethod
    def _system_id_column(id_column_name: str) -> Dict[str, Any]:
        if id_column_name not in _USER_TABLE_SYSTEM_ID_COLUMN_NAMES:
            raise ValueError(f"サポートされていないシステム列です: {id_column_name}")
        return {
            "column_name": id_column_name,
            "column_name_jp": _SYSTEM_ID_JP_NAMES[id_column_name],
            "data_type": "VARCHAR2",
            "max_length": _SYSTEM_ID_COLUMN_MAX_LENGTH,
            "is_nullable": False,
            "is_primary_key": True,
        }

    @staticmethod
    def _normalize_designer_columns(
        columns: Optional[List[Dict[str, Any]]],
        id_column_name: str,
        fk_column_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = [dict(DatabaseService._system_id_column(id_column_name))]
        
        if fk_column_name:
            fk_col = dict(DatabaseService._system_id_column(fk_column_name))
            fk_col["is_primary_key"] = False
            normalized.append(fk_col)

        for raw_col in columns or []:
            col_name = str(raw_col.get("column_name") or "").strip().upper()
            if not col_name:
                continue
            if col_name == _LEGACY_USER_TABLE_ID_COLUMN_NAME:
                raise ValueError("ユーザーテーブルでは ID 列は使用できません。HEADER_ID / LINE_ID を使用してください")
            if col_name in (id_column_name, fk_column_name):
                continue
            if col_name in _USER_TABLE_SYSTEM_ID_COLUMN_NAMES:
                raise ValueError(f"{col_name} はこのテーブルではシステム列として予約されています")
            normalized.append(
                {
                    **raw_col,
                    "column_name": col_name,
                    "column_name_jp": str(raw_col.get("column_name_jp") or raw_col.get("comment") or "").strip(),
                    "data_type": str(raw_col.get("data_type") or "VARCHAR2").strip().upper(),
                    "is_nullable": bool(raw_col.get("is_nullable", True)),
                    "is_primary_key": False,
                }
            )
        return normalized

    @staticmethod
    def _build_id_prefix(table_name: str) -> str:
        normalized_name = re.sub(r"[^A-Z0-9_]+", "_", (table_name or "").strip().upper()).strip("_")
        if normalized_name.endswith("_H"):
            base_name = normalized_name[:-2]
            type_code = "H"
        elif normalized_name.endswith("_L"):
            base_name = normalized_name[:-2]
            type_code = "L"
        else:
            base_name = normalized_name
            type_code = "R"
        base_name = (base_name or normalized_name or "DENPYO")[:12].strip("_") or "DENPYO"
        return f"{base_name}-{type_code}"

    @staticmethod
    def _build_table_scoped_object_name(
        prefix: str,
        table_name: str,
        suffix: str = "",
        *,
        max_length: int = 128,
    ) -> str:
        normalized_prefix = re.sub(r"[^A-Z0-9_]+", "_", (prefix or "").strip().upper()).strip("_") or "OBJ"
        normalized_table_name = re.sub(r"[^A-Z0-9_]+", "_", (table_name or "").strip().upper()).strip("_") or "DENPYO"
        normalized_suffix = re.sub(r"[^A-Z0-9_]+", "_", (suffix or "").strip().upper()).strip("_")
        digest_source = "::".join(part for part in (normalized_prefix, normalized_table_name, normalized_suffix) if part)
        digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest().upper()[:8]

        parts = [normalized_prefix, normalized_table_name, digest]
        if normalized_suffix:
            parts.append(normalized_suffix)
        candidate = "_".join(parts)
        if len(candidate) <= max_length:
            return candidate

        reserved_length = len(normalized_prefix) + len(digest) + 2
        if normalized_suffix:
            reserved_length += len(normalized_suffix) + 1
        available_table_length = max(1, max_length - reserved_length)
        trimmed_table_name = normalized_table_name[:available_table_length].rstrip("_") or normalized_table_name[:available_table_length]

        trimmed_parts = [normalized_prefix, trimmed_table_name, digest]
        if normalized_suffix:
            trimmed_parts.append(normalized_suffix)
        return "_".join(trimmed_parts)

    @staticmethod
    def _build_id_immutability_trigger_ddl(table_name: str, id_column_name: str) -> str:
        if id_column_name not in _USER_TABLE_SYSTEM_ID_COLUMN_NAMES:
            raise ValueError(f"サポートされていないシステム列です: {id_column_name}")
        normalized_table_name = (table_name or "").strip().upper()
        trigger_name = DatabaseService._build_table_scoped_object_name("TRG", normalized_table_name, "ID_IMM")
        return f"""
CREATE OR REPLACE TRIGGER {trigger_name}
BEFORE UPDATE OF {id_column_name} ON {normalized_table_name}
FOR EACH ROW
BEGIN
    IF NVL(:OLD.{id_column_name}, ' ') <> NVL(:NEW.{id_column_name}, ' ') THEN
        RAISE_APPLICATION_ERROR(-20001, '{id_column_name} は更新できません');
    END IF;
END;"""

    def _generate_business_id(self, cursor, table_name: str) -> str:
        normalized_table_name = (table_name or "").strip().upper()
        if not normalized_table_name or not self._is_safe_table_name(normalized_table_name):
            raise ValueError(f"不正なテーブル名です: {table_name}")

        seq_date = time.strftime("%Y%m%d")
        prefix = self._build_id_prefix(normalized_table_name)

        while True:
            next_value_var = cursor.var(int)
            cursor.execute(
                """UPDATE DENPYO_ID_SEQUENCES
                      SET LAST_VALUE = LAST_VALUE + 1,
                          UPDATED_AT = CURRENT_TIMESTAMP
                    WHERE TABLE_NAME = :1
                      AND SEQ_DATE = :2
                RETURNING LAST_VALUE INTO :3""",
                [normalized_table_name, seq_date, next_value_var],
            )
            if cursor.rowcount:
                next_value = next_value_var.getvalue()[0]
                return f"{prefix}-{seq_date}-{int(next_value):06d}"
            try:
                cursor.execute(
                    """INSERT INTO DENPYO_ID_SEQUENCES (TABLE_NAME, SEQ_DATE, LAST_VALUE)
                       VALUES (:1, :2, 1)""",
                    [normalized_table_name, seq_date],
                )
                return f"{prefix}-{seq_date}-000001"
            except Exception as e:
                if "ORA-00001" in str(e):
                    continue
                raise

    def create_category_with_tables(
        self,
        category_name: str,
        category_name_en: str,
        description: str,
        header_table_name: str,
        header_columns: List[Dict[str, Any]],
        line_table_name: Optional[str] = None,
        line_columns: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """カラム定義からDDLを生成し、テーブル作成 + カテゴリ登録を行う"""
        result = {
            "success": False,
            "category_id": None,
            "category_name": category_name,
            "header_table_name": header_table_name,
            "line_table_name": line_table_name or "",
            "header_table_created": False,
            "line_table_created": False,
            "message": "",
        }

        if not header_table_name or not header_columns:
            result["message"] = "ヘッダーテーブル名とカラム定義は必須です"
            return result

        header_columns = self._normalize_designer_columns(header_columns, "HEADER_ID")
        line_columns = self._normalize_designer_columns(line_columns, "LINE_ID", "HEADER_ID") if line_table_name and line_columns else []

        conflicts = self.find_category_conflicts(
            category_name=category_name,
            category_name_en=category_name_en,
            header_table_name=header_table_name,
            line_table_name=line_table_name or "",
        )
        if conflicts:
            result["message"] = " / ".join(conflicts)
            return result

        # DDL生成
        header_ddl = self._build_ddl_from_columns(header_table_name, header_columns, "HEADER_ID")
        header_comment_ddls = self._build_column_comment_ddls(header_table_name, header_columns, "HEADER_ID")
        header_trigger_ddl = self._build_id_immutability_trigger_ddl(header_table_name, "HEADER_ID")
        line_ddl = None
        line_comment_ddls: List[str] = []
        line_trigger_ddl = ""
        if line_table_name and line_columns:
            line_ddl = self._build_ddl_from_columns(line_table_name, line_columns, "LINE_ID", "HEADER_ID")
            line_comment_ddls = self._build_column_comment_ddls(line_table_name, line_columns, "LINE_ID", "HEADER_ID")
            line_trigger_ddl = self._build_id_immutability_trigger_ddl(line_table_name, "LINE_ID")

        # ヘッダーテーブル作成
        header_res = self.execute_ddl(header_ddl)
        if not header_res.get("success"):
            result["message"] = f"ヘッダーテーブル作成失敗: {header_res.get('message', '')}"
            return result
        result["header_table_created"] = True
        for comment_ddl in header_comment_ddls:
            comment_res = self.execute_ddl(comment_ddl)
            if not comment_res.get("success"):
                result["message"] = f"ヘッダーカラムコメント作成失敗: {comment_res.get('message', '')}"
                return result
        header_trigger_res = self.execute_ddl(header_trigger_ddl)
        if not header_trigger_res.get("success"):
            result["message"] = f"ヘッダーID更新禁止トリガー作成失敗: {header_trigger_res.get('message', '')}"
            return result

        # 明細テーブル作成（任意）
        if line_ddl:
            line_res = self.execute_ddl(line_ddl)
            if not line_res.get("success"):
                result["message"] = f"明細テーブル作成失敗: {line_res.get('message', '')}"
                return result
            result["line_table_created"] = True
            for comment_ddl in line_comment_ddls:
                comment_res = self.execute_ddl(comment_ddl)
                if not comment_res.get("success"):
                    result["message"] = f"明細カラムコメント作成失敗: {comment_res.get('message', '')}"
                    return result
            line_trigger_res = self.execute_ddl(line_trigger_ddl)
            if not line_trigger_res.get("success"):
                result["message"] = f"明細ID更新禁止トリガー作成失敗: {line_trigger_res.get('message', '')}"
                return result

        # カテゴリレコード保存
        cat_id = self.upsert_category(
            category_name=category_name,
            category_name_en=category_name_en or "",
            header_table_name=header_table_name.upper(),
            line_table_name=(line_table_name or "").upper() if line_table_name else "",
            description=description or "",
        )
        if cat_id is None:
            result["message"] = "カテゴリレコードの保存に失敗しました"
            return result

        result["success"] = True
        result["category_id"] = cat_id
        result["message"] = "カテゴリとテーブルを作成しました"
        return result

    # ── データ検索 ─────────────────────────────────

    _TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _TABLE_BROWSER_TARGETS = ("SLIPS_RAW", "SLIPS_CATEGORY")

    @staticmethod
    def _coerce_db_text(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "read"):
            return str(value.read() or "")
        return str(value)

    @staticmethod
    def _serialize_db_value(value: Any) -> Any:
        """DB 取得値を JSON で返却可能な値へ正規化する。"""
        if value is None:
            return None

        if hasattr(value, "read"):
            value = value.read()

        if isinstance(value, memoryview):
            value = value.tobytes()

        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return f"<BLOB {len(value)} bytes>"

        return value

    @classmethod
    def _serialize_db_row(cls, columns: List[str], row: Any) -> Dict[str, Any]:
        return {
            column: cls._serialize_db_value(value)
            for column, value in zip(columns, row)
        }

    @staticmethod
    def _build_allowed_table_set_from_entries(table_entries: List[Dict[str, Any]]) -> set:
        allowed = set()
        for entry in table_entries:
            header_table_name = str(entry.get("header_table_name") or "").upper()
            line_table_name = str(entry.get("line_table_name") or "").upper()
            if header_table_name:
                allowed.add(header_table_name)
            if line_table_name:
                allowed.add(line_table_name)
        return allowed

    @staticmethod
    def _build_select_ai_identifier(prefix: str, fingerprint: str) -> str:
        normalized_prefix = re.sub(r"[^A-Z0-9_]", "_", (prefix or "").upper())
        digest = hashlib.sha1((fingerprint or "").encode("utf-8")).hexdigest().upper()[:12]
        identifier = f"{normalized_prefix}{digest}"
        return identifier[:_SELECT_AI_MAX_IDENTIFIER_LENGTH]

    @classmethod
    def _build_select_ai_asset_names(cls, config_fingerprint: str) -> Dict[str, str]:
        return {
            "credential_name": cls._build_select_ai_identifier(_SELECT_AI_CREDENTIAL_PREFIX, f"cred:{config_fingerprint}"),
            "profile_name": cls._build_select_ai_identifier(_SELECT_AI_PROFILE_PREFIX, f"profile:{config_fingerprint}"),
            "tool_name": cls._build_select_ai_identifier(_SELECT_AI_TOOL_PREFIX, f"tool:{config_fingerprint}"),
            "agent_name": cls._build_select_ai_identifier(_SELECT_AI_AGENT_PREFIX, f"agent:{config_fingerprint}"),
            "task_name": cls._build_select_ai_identifier(_SELECT_AI_TASK_PREFIX, f"task:{config_fingerprint}"),
            "team_name": cls._build_select_ai_identifier(_SELECT_AI_TEAM_PREFIX, f"team:{config_fingerprint}"),
        }

    @staticmethod
    def _resolve_select_ai_model_name(model_name: str, region: str) -> str:
        normalized_model = str(model_name or "").strip()
        normalized_model_upper = normalized_model.upper()
        normalized_region_upper = str(region or "").strip().upper()
        if not normalized_model or not normalized_region_upper:
            return normalized_model

        if normalized_model_upper.startswith("XAI.GROK") and normalized_region_upper not in _SELECT_AI_XAI_GROK_REGIONS:
            return _SELECT_AI_REGION_MODEL_FALLBACKS.get(normalized_region_upper, normalized_model)
        return normalized_model

    @staticmethod
    def _build_select_ai_profile_attributes(
        *,
        credential_name: str,
        model_name: str,
        region: str,
        compartment_id: str,
        object_list: List[Dict[str, str]],
        embedding_model_name: str = "",
        endpoint_id: str = "",
        max_tokens: int = 0,
        enforce_object_list: bool = True,
        use_annotations: bool = True,
        use_comments: bool,
        use_constraints: bool = True,
        api_format: str = "",
    ) -> str:
        attributes: Dict[str, Any] = {
            "provider": "oci",
            "credential_name": credential_name,
            "model": model_name,
            "region": region,
            "oci_compartment_id": compartment_id,
            "object_list": object_list,
            "enforce_object_list": bool(enforce_object_list),
            "annotations": bool(use_annotations),
            "comments": bool(use_comments),
            "constraints": bool(use_constraints),
        }
        if str(embedding_model_name or "").strip():
            attributes["embedding_model"] = str(embedding_model_name).strip()
        if str(endpoint_id or "").strip():
            attributes["oci_endpoint_id"] = str(endpoint_id).strip()
        if int(max_tokens or 0) > 0:
            attributes["max_tokens"] = int(max_tokens)
        normalized_api_format = str(api_format or "").strip().upper()
        if normalized_api_format:
            attributes["oci_apiformat"] = normalized_api_format
        return json.dumps(attributes, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _build_select_ai_tool_attributes(profile_name: str) -> str:
        return json.dumps({
            "tool_type": "SQL",
            "tool_params": {
                "profile_name": profile_name,
            },
        }, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _build_select_ai_agent_attributes(profile_name: str) -> str:
        return json.dumps({
            "profile_name": profile_name,
            "role": _SELECT_AI_AGENT_ROLE,
        }, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _build_select_ai_task_attributes(tool_name: str, response_language: str = _SELECT_AI_DEFAULT_RESPONSE_LANGUAGE) -> str:
        instruction = (
            f"{_SELECT_AI_TASK_INSTRUCTION} "
            f"The explanation value must be written in {response_language}."
        )
        return json.dumps({
            "instruction": instruction,
            "tools": [tool_name],
            "enable_human_tool": False,
        }, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _build_select_ai_team_attributes(agent_name: str, task_name: str) -> str:
        return json.dumps({
            "agents": [
                {
                    "name": agent_name,
                    "task": task_name,
                }
            ],
            "process": "sequential",
        }, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _build_select_ai_run_team_params(conversation_id: str) -> str:
        return json.dumps({
            "conversation_id": str(conversation_id or "").strip(),
        }, ensure_ascii=False, separators=(",", ":"))

    def _create_select_ai_conversation(self, cursor) -> str:
        cursor.execute(
            """
            SELECT DBMS_CLOUD_AI.CREATE_CONVERSATION
            FROM DUAL
            """
        )
        row = cursor.fetchone()
        conversation_id = self._coerce_db_text(row[0] if row else "").strip()
        if not conversation_id:
            raise ValueError("Select AI Agent 用 conversation_id を作成できませんでした")
        return conversation_id

    @staticmethod
    def _is_select_ai_conversation_error(error_message_upper: str) -> bool:
        return (
            "CONVERSATION_ID" in error_message_upper
            or "DBMS_CLOUD_AI_CONVERSATION_PROMPT$" in error_message_upper
            or ("ORA-01400" in error_message_upper and "CONVERSATION" in error_message_upper)
        )

    @staticmethod
    def _extract_json_payload(text: str) -> Dict[str, Any]:
        source = (text or "").strip()
        if not source:
            return {}

        source = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", source)
        source = re.sub(r"\s*```$", "", source)

        try:
            parsed = json.loads(source)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", source)
        if not match:
            return {}

        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_select_statement(text: str) -> str:
        match = re.search(r"\bSELECT\b[\s\S]*", text or "", flags=re.IGNORECASE)
        if not match:
            return ""
        candidate = match.group(0).strip()
        
        # If the extracted statement caught trailing JSON structure (e.g. from Select AI)
        json_tail_match = re.search(r'",\s*"[a-zA-Z0-9_]+"\s*:', candidate)
        if json_tail_match:
            candidate = candidate[:json_tail_match.start()]
            
        if candidate.endswith('"}'):
            candidate = candidate[:-2]
        elif candidate.endswith('}'):
            candidate = candidate[:-1].rstrip().rstrip('"')
            
        # Unescape quotes and slashes if string was a JSON literal
        try:
            candidate = candidate.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
        except Exception:
            pass

        if candidate.endswith(";"):
            candidate = candidate[:-1].rstrip()
        return candidate

    @staticmethod
    def _normalize_generated_select(sql: str) -> str:
        candidate = (sql or "").strip()
        while candidate.endswith(";"):
            candidate = candidate[:-1].rstrip()
        return candidate

    def _object_exists(self, cursor, sql: str, params: Dict[str, Any]) -> bool:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return bool(row and int(row[0] or 0) > 0)

    @staticmethod
    def _is_oracle_invalid_identifier_error(error: Exception, identifier: str = "") -> bool:
        message = str(error or "").upper()
        if "ORA-00904" not in message:
            return False
        return not identifier or identifier.upper() in message

    @staticmethod
    def _is_oracle_already_exists_error(error: Exception) -> bool:
        message = str(error or "").upper()
        return (
            "ORA-00955" in message
            or "ALREADY EXISTS" in message
            or "DUPLICATE" in message
        )

    def _get_current_schema_name(self, cursor) -> str:
        cursor.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL")
        row = cursor.fetchone()
        return str((row[0] if row else "") or "").upper()

    def _ensure_select_ai_credential(
        self,
        cursor,
        *,
        credential_name: str,
        oci_auth_config: Dict[str, str],
    ) -> None:
        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD.DROP_CREDENTIAL(credential_name => :credential_name);
                END;
                """,
                {"credential_name": credential_name},
            )
        except Exception as e:
            logger.debug("Credential drop failed or skipped: %s", e)

        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD.CREATE_CREDENTIAL(
                        credential_name => :credential_name,
                        user_ocid => :user_ocid,
                        tenancy_ocid => :tenancy_ocid,
                        private_key => :private_key,
                        fingerprint => :fingerprint
                    );
                END;
                """,
                {
                    "credential_name": credential_name,
                    "user_ocid": oci_auth_config["user"],
                    "tenancy_ocid": oci_auth_config["tenancy"],
                    "private_key": oci_auth_config["key_content"],
                    "fingerprint": oci_auth_config["fingerprint"],
                },
            )
        except Exception as e:
            if self._is_oracle_already_exists_error(e):
                logger.debug("Credential already exists: %s", credential_name)
            else:
                raise

    def _ensure_select_ai_profile(
        self,
        cursor,
        *,
        profile_name: str,
        attributes_json: str,
    ) -> None:
        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI.DROP_PROFILE(profile_name => :profile_name);
                END;
                """,
                {"profile_name": profile_name},
            )
        except Exception as e:
            logger.debug("Profile drop failed or skipped: %s", e)

        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI.CREATE_PROFILE(
                        profile_name => :profile_name,
                        attributes => :attributes
                    );
                END;
                """,
                {
                    "profile_name": profile_name,
                    "attributes": attributes_json,
                },
            )
        except Exception as e:
            if self._is_oracle_already_exists_error(e):
                logger.debug("Profile already exists: %s", profile_name)
            else:
                raise

    def _ensure_select_ai_tool(
        self,
        cursor,
        *,
        tool_name: str,
        attributes_json: str,
    ) -> None:
        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.DROP_TOOL(tool_name => :tool_name);
                END;
                """,
                {"tool_name": tool_name},
            )
        except Exception as e:
            logger.debug("Tool drop failed or skipped: %s", e)

        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.CREATE_TOOL(
                        tool_name => :tool_name,
                        attributes => :attributes
                    );
                END;
                """,
                {
                    "tool_name": tool_name,
                    "attributes": attributes_json,
                },
            )
        except Exception as e:
            if self._is_oracle_already_exists_error(e):
                logger.debug("Tool already exists: %s", tool_name)
            else:
                raise

    def _ensure_select_ai_agent(
        self,
        cursor,
        *,
        agent_name: str,
        attributes_json: str,
    ) -> None:
        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.DROP_AGENT(agent_name => :agent_name);
                END;
                """,
                {"agent_name": agent_name},
            )
        except Exception as e:
            logger.debug("Agent drop failed or skipped: %s", e)

        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.CREATE_AGENT(
                        agent_name => :agent_name,
                        attributes => :attributes
                    );
                END;
                """,
                {
                    "agent_name": agent_name,
                    "attributes": attributes_json,
                },
            )
        except Exception as e:
            if self._is_oracle_already_exists_error(e):
                logger.debug("Agent already exists: %s", agent_name)
            else:
                raise

    def _ensure_select_ai_task(
        self,
        cursor,
        *,
        task_name: str,
        attributes_json: str,
    ) -> None:
        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.DROP_TASK(task_name => :task_name);
                END;
                """,
                {"task_name": task_name},
            )
        except Exception as e:
            logger.debug("Task drop failed or skipped: %s", e)

        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.CREATE_TASK(
                        task_name => :task_name,
                        attributes => :attributes
                    );
                END;
                """,
                {
                    "task_name": task_name,
                    "attributes": attributes_json,
                },
            )
        except Exception as e:
            if self._is_oracle_already_exists_error(e):
                logger.debug("Task already exists: %s", task_name)
            else:
                raise

    def _ensure_select_ai_team(
        self,
        cursor,
        *,
        team_name: str,
        attributes_json: str,
    ) -> None:
        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.DROP_TEAM(team_name => :team_name);
                END;
                """,
                {"team_name": team_name},
            )
        except Exception as e:
            logger.debug("Team drop failed or skipped: %s", e)

        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_CLOUD_AI_AGENT.CREATE_TEAM(
                        team_name => :team_name,
                        attributes => :attributes
                    );
                END;
                """,
                {
                    "team_name": team_name,
                    "attributes": attributes_json,
                },
            )
        except Exception as e:
            if self._is_oracle_already_exists_error(e):
                logger.info("Select AI team は既に存在するため再作成をスキップします: %s", team_name)
            else:
                raise

    def _ensure_select_ai_agent_assets(
        self,
        cursor,
        *,
        allowed_table_names: set,
        oci_auth_config: Dict[str, str],
        model_settings: Dict[str, Any],
    ) -> Dict[str, str]:
        if not allowed_table_names:
            raise ValueError("検索可能なテーブルがありません")

        llm_model_id = str(model_settings.get("select_ai_model_id") or model_settings.get("llm_model_id") or "").strip()
        embedding_model_id = str(model_settings.get("select_ai_embedding_model_id") or "").strip()
        endpoint_id = str(model_settings.get("select_ai_endpoint_id") or "").strip()
        compartment_id = str(model_settings.get("compartment_id") or "").strip()
        region = str(model_settings.get("select_ai_region") or oci_auth_config.get("region") or "").strip()
        if not all([llm_model_id, compartment_id, region]):
            raise ValueError("Select AI Agent の実行に必要な OCI / GenAI 設定が不足しています")
        select_ai_model_id = self._resolve_select_ai_model_name(llm_model_id, region)
        select_ai_max_tokens = int(model_settings.get("select_ai_max_tokens") or 0)
        select_ai_enforce_object_list = bool(model_settings.get("select_ai_enforce_object_list", True))
        select_ai_use_annotations = bool(model_settings.get("select_ai_use_annotations", True))
        select_ai_use_comments = bool(model_settings.get("select_ai_use_comments", True))
        select_ai_use_constraints = bool(model_settings.get("select_ai_use_constraints", True))
        if select_ai_model_id != llm_model_id:
            logger.info(
                "Select AI Agent 用モデルをリージョン互換の設定へ切り替えます: requested=%s region=%s resolved=%s",
                llm_model_id,
                region,
                select_ai_model_id,
            )

        schema_name = self._get_current_schema_name(cursor)
        object_list = [{"owner": schema_name, "name": table_name} for table_name in sorted(allowed_table_names)]
        config_payload = {
            "model": select_ai_model_id,
            "embedding_model": embedding_model_id,
            "compartment_id": compartment_id,
            "region": region,
            "endpoint_id": endpoint_id,
            "max_tokens": select_ai_max_tokens,
            "enforce_object_list": select_ai_enforce_object_list,
            "api_format": str(model_settings.get("select_ai_oci_apiformat") or "").strip().upper(),
            "use_annotations": select_ai_use_annotations,
            "use_comments": select_ai_use_comments,
            "use_constraints": select_ai_use_constraints,
            "objects": object_list,
            "oci_user": str(oci_auth_config.get("user") or "").strip(),
            "oci_tenancy": str(oci_auth_config.get("tenancy") or "").strip(),
            "oci_fingerprint": str(oci_auth_config.get("fingerprint") or "").strip(),
        }
        config_fingerprint = hashlib.sha1(
            json.dumps(config_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest().upper()
        asset_names = self._build_select_ai_asset_names(config_fingerprint)

        self._ensure_select_ai_credential(
            cursor,
            credential_name=asset_names["credential_name"],
            oci_auth_config=oci_auth_config,
        )
        self._ensure_select_ai_profile(
            cursor,
            profile_name=asset_names["profile_name"],
            attributes_json=self._build_select_ai_profile_attributes(
                credential_name=asset_names["credential_name"],
                model_name=select_ai_model_id,
                region=region,
                compartment_id=compartment_id,
                object_list=object_list,
                embedding_model_name=embedding_model_id,
                endpoint_id=endpoint_id,
                max_tokens=select_ai_max_tokens,
                enforce_object_list=select_ai_enforce_object_list,
                use_annotations=select_ai_use_annotations,
                use_comments=select_ai_use_comments,
                use_constraints=select_ai_use_constraints,
                api_format=str(model_settings.get("select_ai_oci_apiformat") or "").strip(),
            ),
        )
        self._ensure_select_ai_tool(
            cursor,
            tool_name=asset_names["tool_name"],
            attributes_json=self._build_select_ai_tool_attributes(asset_names["profile_name"]),
        )
        self._ensure_select_ai_agent(
            cursor,
            agent_name=asset_names["agent_name"],
            attributes_json=self._build_select_ai_agent_attributes(asset_names["profile_name"]),
        )
        self._ensure_select_ai_task(
            cursor,
            task_name=asset_names["task_name"],
            attributes_json=self._build_select_ai_task_attributes(asset_names["tool_name"]),
        )
        self._ensure_select_ai_team(
            cursor,
            team_name=asset_names["team_name"],
            attributes_json=self._build_select_ai_team_attributes(asset_names["agent_name"], asset_names["task_name"]),
        )
        return {
            **asset_names,
            "config_fingerprint": config_fingerprint,
            "model_name": select_ai_model_id,
            "region": region,
        }

    def create_select_ai_profile_for_category(
        self,
        *,
        category_id: int,
        oci_auth_config: Dict[str, str],
        model_settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        """カテゴリ単位で Select AI Agent profile / team を作成または再利用する。"""
        if not self._ensure_management_tables():
            return {"success": False, "message": "管理テーブルの初期化に失敗しました"}

        category = self.get_category_by_id(category_id)
        if not category:
            return {"success": False, "message": "カテゴリが見つかりません"}

        allowed_table_entries = [{
            "category_id": category["id"],
            "category_name": category["category_name"],
            "header_table_name": category.get("header_table_name", ""),
            "line_table_name": category.get("line_table_name", ""),
        }]
        allowed_table_names = self._build_allowed_table_set_from_entries(allowed_table_entries)
        if not allowed_table_names:
            return {"success": False, "message": "Select AI profile の作成に必要なテーブルがありません"}

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    asset_names = self._ensure_select_ai_agent_assets(
                        cursor,
                        allowed_table_names=allowed_table_names,
                        oci_auth_config=oci_auth_config,
                        model_settings=model_settings,
                    )
                    self._save_category_select_ai_profile_metadata_with_cursor(
                        cursor,
                        category_id=category_id,
                        profile_name=asset_names["profile_name"],
                        team_name=asset_names["team_name"],
                        config_hash=asset_names.get("config_fingerprint", ""),
                        ready=True,
                        error_message="",
                    )
                conn.commit()

            return {
                "success": True,
                "category_id": category_id,
                "category_name": category.get("category_name", ""),
                "profile_name": asset_names["profile_name"],
                "team_name": asset_names["team_name"],
                "model_name": asset_names.get("model_name", ""),
                "region": asset_names.get("region", ""),
                "config_hash": asset_names.get("config_fingerprint", ""),
            }
        except Exception as e:
            logger.error("カテゴリ Select AI profile 作成エラー (id=%s): %s", category_id, e, exc_info=True)
            self.save_category_select_ai_profile_metadata(
                category_id=category_id,
                profile_name=str(category.get("select_ai_profile_name") or ""),
                team_name=str(category.get("select_ai_team_name") or ""),
                config_hash=str(category.get("select_ai_config_hash") or ""),
                ready=False,
                error_message=str(e),
            )
            return {"success": False, "message": str(e)}

    def get_allowed_table_names(self) -> List[Dict[str, Any]]:
        """DENPYO_CATEGORIES から有効なユーザーテーブル名を取得"""
        if not self._ensure_management_tables():
            return []
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, CATEGORY_NAME, HEADER_TABLE_NAME, LINE_TABLE_NAME,
                                  SELECT_AI_PROFILE_NAME, SELECT_AI_TEAM_NAME,
                                  SELECT_AI_READY, SELECT_AI_SYNCED_AT, SELECT_AI_LAST_ERROR
                        FROM DENPYO_CATEGORIES WHERE IS_ACTIVE = 1
                        ORDER BY CATEGORY_NAME"""
                    )
                    tables = []
                    for row in cursor.fetchall():
                        tables.append({
                            "category_id": row[0],
                            "category_name": row[1],
                            "header_table_name": row[2] or "",
                            "line_table_name": row[3] or "",
                            "select_ai_profile_name": row[4] or "",
                            "select_ai_team_name": row[5] or "",
                            "select_ai_profile_ready": bool(row[6]),
                            "select_ai_last_synced_at": str(row[7]) if row[7] else "",
                            "select_ai_last_error": row[8] or "",
                        })
                    return tables
        except Exception as e:
            logger.error("許可テーブル一覧取得エラー: %s", e, exc_info=True)
            return []

    def _is_safe_table_name(self, table_name: str) -> bool:
        return bool(table_name and self._TABLE_NAME_PATTERN.match(table_name))

    def get_table_browser_tables(self) -> List[Dict[str, Any]]:
        """テーブルブラウザ用の一覧情報を取得（行数・作成日時など）"""
        table_entries: List[Dict[str, Any]] = []

        for entry in self.get_allowed_table_names():
            header_table_name = (entry.get("header_table_name") or "").upper()
            line_table_name = (entry.get("line_table_name") or "").upper()
            if self._is_safe_table_name(header_table_name):
                table_entries.append({
                    "table_name": header_table_name,
                    "table_type": "header",
                    "category_id": int(entry.get("category_id") or 0),
                    "category_name": entry.get("category_name") or "",
                })
            if self._is_safe_table_name(line_table_name):
                table_entries.append({
                    "table_name": line_table_name,
                    "table_type": "line",
                    "category_id": int(entry.get("category_id") or 0),
                    "category_name": entry.get("category_name") or "",
                })

        normalized_entries: List[Dict[str, Any]] = []
        safe_table_names: List[str] = []
        seen_table_names = set()
        for entry in table_entries:
            table_name = (entry.get("table_name") or "").upper()
            if not self._is_safe_table_name(table_name) or table_name in seen_table_names:
                continue
            seen_table_names.add(table_name)
            safe_table_names.append(table_name)
            normalized_entries.append({
                "table_name": table_name,
                "table_type": entry.get("table_type", "header"),
                "category_id": int(entry.get("category_id") or 0),
                "category_name": entry.get("category_name") or "",
            })

        if not safe_table_names:
            return []

        meta_map: Dict[str, Dict[str, Any]] = {
            table_name: {
                "row_count": 0,
                "estimated_rows": 0,
                "column_count": 0,
                "created_at": "",
                "last_analyzed": "",
            }
            for table_name in safe_table_names
        }

        existing_table_names: set = set()

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    bind_map = {f"tn{i}": name for i, name in enumerate(safe_table_names)}
                    in_clause = ", ".join([f":tn{i}" for i in range(len(safe_table_names))])

                    cursor.execute(
                        f"""SELECT t.TABLE_NAME, NVL(t.NUM_ROWS, 0), t.LAST_ANALYZED, o.CREATED
                        FROM USER_TABLES t
                        LEFT JOIN USER_OBJECTS o
                          ON o.OBJECT_NAME = t.TABLE_NAME
                         AND o.OBJECT_TYPE = 'TABLE'
                        WHERE t.TABLE_NAME IN ({in_clause})""",
                        bind_map
                    )
                    for row in cursor.fetchall():
                        table_name = str(row[0] or "").upper()
                        if table_name not in meta_map:
                            continue
                        existing_table_names.add(table_name)
                        meta_map[table_name]["estimated_rows"] = int(row[1] or 0)
                        meta_map[table_name]["last_analyzed"] = str(row[2]) if row[2] else ""
                        meta_map[table_name]["created_at"] = str(row[3]) if row[3] else ""

                    if not existing_table_names:
                        return []

                    cursor.execute(
                        f"""SELECT TABLE_NAME, COUNT(*)
                        FROM USER_TAB_COLUMNS
                        WHERE TABLE_NAME IN ({in_clause})
                        GROUP BY TABLE_NAME""",
                        bind_map
                    )
                    for row in cursor.fetchall():
                        table_name = str(row[0] or "").upper()
                        if table_name not in meta_map:
                            continue
                        meta_map[table_name]["column_count"] = int(row[1] or 0)

                    for table_name in sorted(existing_table_names):
                        try:
                            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                            count_row = cursor.fetchone()
                            actual_count = int(count_row[0]) if count_row and count_row[0] is not None else 0
                            meta_map[table_name]["row_count"] = actual_count
                        except Exception as count_error:
                            logger.warning("テーブル行数取得スキップ (%s): %s", table_name, count_error)
                            meta_map[table_name]["row_count"] = meta_map[table_name]["estimated_rows"]
        except Exception as e:
            logger.error("テーブルブラウザ一覧取得エラー: %s", e, exc_info=True)
            return []

        result: List[Dict[str, Any]] = []
        for entry in normalized_entries:
            table_name = entry["table_name"]
            # 未作成テーブルは表示対象外（エラーにはしない）
            if table_name not in existing_table_names:
                continue
            meta = meta_map.get(table_name, {})
            result.append({
                **entry,
                "row_count": meta.get("row_count", 0),
                "estimated_rows": meta.get("estimated_rows", 0),
                "column_count": meta.get("column_count", 0),
                "created_at": meta.get("created_at", ""),
                "last_analyzed": meta.get("last_analyzed", ""),
            })

        result.sort(key=lambda x: x["table_name"])
        return result

    def _get_allowed_table_set(self) -> set:
        """許可されたテーブル名のセットを取得（大文字）"""
        allowed = set()
        for entry in self.get_allowed_table_names():
            if entry["header_table_name"]:
                allowed.add(entry["header_table_name"].upper())
            if entry["line_table_name"]:
                allowed.add(entry["line_table_name"].upper())
        allowed.update(self._TABLE_BROWSER_TARGETS)
        return allowed

    def get_table_columns(
        self,
        table_name: str,
        use_comments: bool = False,
        use_constraints: bool = False,
        use_annotations: bool = False,
        allowed_table_set: Optional[set] = None,
    ) -> List[Dict[str, str]]:
        """テーブルのカラム情報を取得（許可テーブルのみ）

        Args:
            table_name: テーブル名
            use_comments: True の場合、USER_COL_COMMENTS から列コメントも取得する
            use_constraints: True の場合、主キー・外部キー・ユニーク制約情報も取得する
            use_annotations: True の場合、Oracle アノテーション (USER_ANNOTATIONS_USAGE) も取得する
            allowed_table_set: 事前計算済みの許可テーブル集合。未指定時は都度取得する
        """
        if not table_name:
            return []

        # セキュリティ: 許可テーブルかチェック
        allowed = allowed_table_set or self._get_allowed_table_set()
        if table_name.upper() not in allowed:
            logger.warning("許可されていないテーブルへのアクセス試行: %s", table_name)
            return []

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, NULLABLE
                        FROM USER_TAB_COLUMNS
                        WHERE TABLE_NAME = :1
                        ORDER BY COLUMN_ID""",
                        [table_name.upper()]
                    )
                    columns = []
                    for row in cursor.fetchall():
                        columns.append({
                            "column_name": row[0],
                            "data_type": row[1],
                            "data_length": row[2],
                            "nullable": row[3],
                            "comment": "",
                            "constraints": [],
                            "annotations": [],
                        })

                    if not columns:
                        return columns

                    # 列コメントを取得
                    if use_comments:
                        try:
                            cursor.execute(
                                """SELECT COLUMN_NAME, COMMENTS
                                FROM USER_COL_COMMENTS
                                WHERE TABLE_NAME = :1""",
                                [table_name.upper()]
                            )
                            comments_map = {row[0]: (row[1] or "") for row in cursor.fetchall()}
                            for col in columns:
                                col["comment"] = comments_map.get(col["column_name"], "")
                        except Exception as e:
                            logger.warning("列コメント取得エラー (%s): %s", table_name, e)

                    # 制約情報を取得（PK / UNIQUE / FK）
                    if use_constraints:
                        try:
                            cursor.execute(
                                """SELECT cols.COLUMN_NAME, cons.CONSTRAINT_TYPE,
                                          r_cons.TABLE_NAME AS REF_TABLE,
                                          r_cols.COLUMN_NAME AS REF_COLUMN
                                   FROM USER_CONSTRAINTS cons
                                   JOIN USER_CONS_COLUMNS cols
                                     ON cols.CONSTRAINT_NAME = cons.CONSTRAINT_NAME
                                    AND cols.TABLE_NAME = cons.TABLE_NAME
                                   LEFT JOIN USER_CONSTRAINTS r_cons
                                     ON r_cons.CONSTRAINT_NAME = cons.R_CONSTRAINT_NAME
                                   LEFT JOIN USER_CONS_COLUMNS r_cols
                                     ON r_cols.CONSTRAINT_NAME = cons.R_CONSTRAINT_NAME
                                    AND r_cols.POSITION = cols.POSITION
                                  WHERE cons.TABLE_NAME = :1
                                    AND cons.CONSTRAINT_TYPE IN ('P', 'U', 'R')
                                  ORDER BY cons.CONSTRAINT_TYPE, cols.POSITION""",
                                [table_name.upper()]
                            )
                            constraints_map: Dict[str, List[str]] = {}
                            for row in cursor.fetchall():
                                col_name = row[0]
                                c_type = row[1]
                                ref_table = row[2] or ""
                                ref_col = row[3] or ""
                                if c_type == "P":
                                    label = "PK"
                                elif c_type == "U":
                                    label = "UNIQUE"
                                elif c_type == "R" and ref_table:
                                    label = f"FK->{ref_table}.{ref_col}" if ref_col else f"FK->{ref_table}"
                                else:
                                    label = c_type
                                constraints_map.setdefault(col_name, []).append(label)
                            for col in columns:
                                col["constraints"] = constraints_map.get(col["column_name"], [])
                        except Exception as e:
                            logger.warning("制約情報取得エラー (%s): %s", table_name, e)

                    # アノテーション情報を取得（Oracle 23ai: USER_ANNOTATIONS_USAGE）
                    if use_annotations:
                        try:
                            cursor.execute(
                                """SELECT COLUMN_NAME, ANNOTATION_NAME, ANNOTATION_VALUE
                                   FROM USER_ANNOTATIONS_USAGE
                                  WHERE OBJECT_TYPE = 'COLUMN'
                                    AND OBJECT_NAME = :1""",
                                [table_name.upper()]
                            )
                            annotations_map: Dict[str, List[Dict[str, str]]] = {}
                            for row in cursor.fetchall():
                                col_name = row[0] or ""
                                if col_name:
                                    annotations_map.setdefault(col_name, []).append({
                                        "name": row[1] or "",
                                        "value": row[2] or "",
                                    })
                            for col in columns:
                                col["annotations"] = annotations_map.get(col["column_name"], [])
                        except Exception as e:
                            logger.warning("アノテーション取得エラー (%s): %s", table_name, e)

                    return columns
        except Exception as e:
            logger.error("カラム情報取得エラー (%s): %s", table_name, e, exc_info=True)
            return []

    def _get_primary_key_columns(self, cursor, table_name: str) -> List[str]:
        """テーブルの主キー列を順序付きで取得する。見つからない場合は空配列。"""
        normalized_table_name = (table_name or "").strip().upper()
        if not normalized_table_name:
            return []

        cursor.execute(
            """SELECT cols.COLUMN_NAME
                 FROM USER_CONSTRAINTS cons
                 JOIN USER_CONS_COLUMNS cols
                   ON cols.CONSTRAINT_NAME = cons.CONSTRAINT_NAME
                  AND cols.TABLE_NAME = cons.TABLE_NAME
                WHERE cons.TABLE_NAME = :1
                  AND cons.CONSTRAINT_TYPE = 'P'
                ORDER BY cols.POSITION""",
            [normalized_table_name],
        )
        return [
            str(row[0]).strip().upper()
            for row in cursor.fetchall()
            if row and row[0] and self._is_safe_table_name(str(row[0]).strip().upper())
        ]

    def _build_table_data_order_by_clause(self, cursor, table_name: str) -> str:
        """テーブルブラウザの安定した並び順を返す。主キー優先、なければ ROWID。"""
        pk_columns = self._get_primary_key_columns(cursor, table_name)
        if pk_columns:
            return ", ".join(f"t.{column_name}" for column_name in pk_columns)
        return "t.ROWID"

    def _validate_select_only(self, sql: str) -> None:
        """SQL が SELECT 文のみかを検証（禁止キーワードチェック）"""
        normalized_sql = self._normalize_generated_select(sql)
        sanitized_sql = self._sanitize_sql_for_analysis(normalized_sql)
        normalized = sanitized_sql.strip().upper()

        # SELECT で始まることを確認
        if not normalized.startswith("SELECT"):
            raise ValueError("SELECT 文のみ実行できます")

        # 禁止キーワードチェック
        forbidden = re.compile(
            r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|MERGE)\b',
            re.IGNORECASE
        )
        if forbidden.search(sanitized_sql):
            raise ValueError("許可されていない SQL キーワードが含まれています")

    @staticmethod
    def _sanitize_sql_for_analysis(sql: str) -> str:
        """文字列リテラルとコメントを空白化し、構文解析用の SQL を返す。"""
        source = sql or ""
        result: List[str] = []
        index = 0
        length = len(source)

        while index < length:
            current = source[index]
            next_char = source[index + 1] if index + 1 < length else ""

            if current == "'" and next_char != "":
                result.append(" ")
                index += 1
                while index < length:
                    char = source[index]
                    result.append(" " if char != "\n" else "\n")
                    if char == "'":
                        if index + 1 < length and source[index + 1] == "'":
                            result.append(" ")
                            index += 2
                            continue
                        index += 1
                        break
                    index += 1
                continue

            if current == "-" and next_char == "-":
                result.extend([" ", " "])
                index += 2
                while index < length and source[index] != "\n":
                    result.append(" ")
                    index += 1
                continue

            if current == "/" and next_char == "*":
                result.extend([" ", " "])
                index += 2
                while index < length:
                    char = source[index]
                    following = source[index + 1] if index + 1 < length else ""
                    result.append(" " if char != "\n" else "\n")
                    if char == "*" and following == "/":
                        result.append(" ")
                        index += 2
                        break
                    index += 1
                continue

            result.append(current)
            index += 1

        return "".join(result)

    @staticmethod
    def _tokenize_sql_structure(sql: str) -> List[Dict[str, str]]:
        """SQL 構造解析用にトークン化する。文字列リテラルは事前に除去しておくこと。"""
        tokens: List[Dict[str, str]] = []
        index = 0
        length = len(sql or "")

        while index < length:
            current = sql[index]
            if current.isspace():
                index += 1
                continue

            if current == '"':
                index += 1
                identifier_chars: List[str] = []
                while index < length:
                    char = sql[index]
                    if char == '"':
                        if index + 1 < length and sql[index + 1] == '"':
                            identifier_chars.append('"')
                            index += 2
                            continue
                        index += 1
                        break
                    identifier_chars.append(char)
                    index += 1
                tokens.append({
                    "kind": "identifier",
                    "value": "".join(identifier_chars),
                })
                continue

            if current.isalpha() or current in ("_", "$", "#"):
                start = index
                index += 1
                while index < length and (sql[index].isalnum() or sql[index] in ("_", "$", "#")):
                    index += 1
                tokens.append({
                    "kind": "word",
                    "value": sql[start:index],
                })
                continue

            if current == ".":
                tokens.append({
                    "kind": "dot",
                    "value": current,
                })
                index += 1
                continue

            if current in "(),;":
                tokens.append({
                    "kind": "symbol",
                    "value": current,
                })
                index += 1
                continue

            tokens.append({
                "kind": "symbol",
                "value": current,
            })
            index += 1

        return tokens

    @staticmethod
    def _token_upper(token: Dict[str, str]) -> str:
        return str(token.get("value") or "").upper()

    @staticmethod
    def _is_identifier_token(token: Optional[Dict[str, str]]) -> bool:
        if not token:
            return False
        return token.get("kind") in ("word", "identifier") and bool(token.get("value"))

    @classmethod
    def _skip_balanced_parentheses(cls, tokens: List[Dict[str, str]], start_index: int) -> int:
        depth = 0
        index = start_index
        while index < len(tokens):
            value = tokens[index].get("value")
            if value == "(":
                depth += 1
            elif value == ")":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        return index

    @classmethod
    def _skip_relation_alias(cls, tokens: List[Dict[str, str]], index: int) -> int:
        alias_stop_keywords = {
            "WHERE", "GROUP", "ORDER", "HAVING", "CONNECT", "START",
            "UNION", "MINUS", "INTERSECT", "EXCEPT", "FETCH", "OFFSET",
            "FOR", "MODEL", "JOIN", "INNER", "LEFT", "RIGHT", "FULL",
            "CROSS", "NATURAL", "OUTER", "ON", "USING",
        }
        if index < len(tokens) and cls._token_upper(tokens[index]) == "AS":
            index += 1
        if (
            index < len(tokens)
            and cls._is_identifier_token(tokens[index])
            and cls._token_upper(tokens[index]) not in alias_stop_keywords
        ):
            index += 1
        return index

    @classmethod
    def _parse_relation_reference(
        cls,
        tokens: List[Dict[str, str]],
        start_index: int,
    ) -> (Optional[Dict[str, Any]], int):
        if start_index >= len(tokens) or not cls._is_identifier_token(tokens[start_index]):
            return None, start_index

        segments = [str(tokens[start_index].get("value") or "").upper()]
        index = start_index + 1
        while index + 1 < len(tokens):
            if tokens[index].get("kind") != "dot" or not cls._is_identifier_token(tokens[index + 1]):
                break
            segments.append(str(tokens[index + 1].get("value") or "").upper())
            index += 2

        return {
            "table_name": segments[-1],
            "qualified_name": segments,
            "is_qualified": len(segments) > 1,
        }, index

    @classmethod
    def _extract_table_references_from_sql(cls, sql: str) -> List[Dict[str, Any]]:
        tokens = cls._tokenize_sql_structure(cls._sanitize_sql_for_analysis(sql))
        references: List[Dict[str, Any]] = []
        clause_end_keywords = {
            "WHERE", "GROUP", "ORDER", "HAVING", "CONNECT", "START",
            "UNION", "MINUS", "INTERSECT", "EXCEPT", "FETCH", "OFFSET",
            "FOR", "MODEL",
        }
        index = 0

        while index < len(tokens):
            token_upper = cls._token_upper(tokens[index])
            if token_upper == "FROM":
                index += 1
                while index < len(tokens):
                    current = tokens[index]
                    current_upper = cls._token_upper(current)
                    if current_upper in clause_end_keywords or current.get("value") == ")":
                        break
                    if current_upper in {"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "OUTER", "ON", "USING"}:
                        break
                    if current.get("value") == ",":
                        index += 1
                        continue
                    if current.get("value") == "(":
                        index = cls._skip_balanced_parentheses(tokens, index)
                        index = cls._skip_relation_alias(tokens, index)
                        continue

                    reference, next_index = cls._parse_relation_reference(tokens, index)
                    if reference:
                        references.append(reference)
                        index = cls._skip_relation_alias(tokens, next_index)
                        continue

                    index += 1
                continue

            if token_upper == "JOIN":
                index += 1
                if index < len(tokens) and tokens[index].get("value") == "(":
                    index = cls._skip_balanced_parentheses(tokens, index)
                    index = cls._skip_relation_alias(tokens, index)
                    continue

                reference, next_index = cls._parse_relation_reference(tokens, index)
                if reference:
                    references.append(reference)
                    index = cls._skip_relation_alias(tokens, next_index)
                    continue

            index += 1

        return references

    def _validate_tables_in_whitelist(
        self,
        sql: str,
        allowed: set,
        allowed_schema_names: Optional[set] = None,
    ) -> None:
        """SQL 内のテーブルが許可リストにあるか検証"""
        references = self._extract_table_references_from_sql(sql)
        normalized_allowed_schema_names = {
            str(schema_name or "").strip().upper()
            for schema_name in (allowed_schema_names or set())
            if str(schema_name or "").strip()
        }
        qualified = []
        for ref in references:
            if not ref.get("is_qualified"):
                continue
            qualified_name = [str(segment or "").strip().upper() for segment in (ref.get("qualified_name") or [])]
            if len(qualified_name) == 2 and qualified_name[0] in normalized_allowed_schema_names:
                continue
            qualified.append(".".join(qualified_name))
        if qualified:
            raise ValueError(f"スキーマ修飾されたテーブル参照は許可されていません: {', '.join(qualified)}")

        referenced = {str(ref.get("table_name") or "").upper() for ref in references if ref.get("table_name")}
        unauthorized = referenced - allowed
        if unauthorized:
            raise ValueError(f"許可されていないテーブルが参照されています: {', '.join(unauthorized)}")

    def execute_select_query(self, sql: str, max_rows: int = 500, allowed_tables: Optional[set] = None) -> Dict[str, Any]:
        """SELECT 文のみ実行（安全なクエリ実行）"""
        try:
            normalized_sql = self._normalize_generated_select(sql)
            # セキュリティ検証
            self._validate_select_only(normalized_sql)
            allowed = allowed_tables or self._get_allowed_table_set()
            if not allowed:
                return {"success": False, "message": "検索可能なテーブルがありません", "columns": [], "rows": [], "total": 0}
            has_schema_qualified_reference = any(
                ref.get("is_qualified")
                for ref in self._extract_table_references_from_sql(normalized_sql)
            )
            try:
                self._validate_tables_in_whitelist(normalized_sql, allowed)
            except ValueError as e:
                if not has_schema_qualified_reference:
                    raise
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        current_schema_name = self._get_current_schema_name(cursor)
                        self._validate_tables_in_whitelist(
                            normalized_sql,
                            allowed,
                            allowed_schema_names={current_schema_name},
                        )
                        limited_sql = f"SELECT * FROM ({normalized_sql}) WHERE ROWNUM <= :max_rows"
                        cursor.execute(limited_sql, {"max_rows": max_rows})
                        columns = [desc[0] for desc in cursor.description]
                        rows_raw = cursor.fetchall()
                        rows = [self._serialize_db_row(columns, row) for row in rows_raw]
                        return {
                            "success": True,
                            "columns": columns,
                            "rows": rows,
                            "total": len(rows),
                        }

            limited_sql = f"SELECT * FROM ({normalized_sql}) WHERE ROWNUM <= :max_rows"

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(limited_sql, {"max_rows": max_rows})
                    columns = [desc[0] for desc in cursor.description]
                    rows_raw = cursor.fetchall()
                    rows = [self._serialize_db_row(columns, row) for row in rows_raw]
                    return {
                        "success": True,
                        "columns": columns,
                        "rows": rows,
                        "total": len(rows),
                    }
        except ValueError as e:
            if allowed_tables is None:
                logger.warning("SQL 検証エラー: %s", e)
            else:
                logger.debug("SQL 検証失敗（明示 allowlist 適用中）: %s", e)
            return {"success": False, "message": str(e), "columns": [], "rows": [], "total": 0}
        except Exception as e:
            logger.error("クエリ実行エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"クエリ実行エラー: {str(e)}", "columns": [], "rows": [], "total": 0}

    def run_select_ai_agent_search(
        self,
        *,
        query: str,
        allowed_table_entries: List[Dict[str, Any]],
        oci_auth_config: Dict[str, str],
        model_settings: Dict[str, Any],
        max_rows: int = 500,
    ) -> Dict[str, Any]:
        """Oracle Select AI Agent を利用して自然言語検索を実行する。"""
        if not query or not query.strip():
            return {"success": False, "message": "検索クエリが空です"}

        allowed_tables = self._build_allowed_table_set_from_entries(allowed_table_entries)
        if not allowed_tables:
            return {"success": False, "message": "検索可能なテーブルがありません"}

        if not all([
            oci_auth_config.get("user"),
            oci_auth_config.get("tenancy"),
            oci_auth_config.get("fingerprint"),
            oci_auth_config.get("key_content"),
            oci_auth_config.get("region"),
        ]):
            return {"success": False, "message": "OCI 認証情報が不足しています"}

        category_ids = {
            int(entry.get("category_id"))
            for entry in allowed_table_entries
            if entry.get("category_id") not in (None, "")
        }
        target_category_id = next(iter(category_ids)) if len(category_ids) == 1 else None
        asset_names: Dict[str, Any] = {}
        conversation_id = ""

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    asset_names = self._ensure_select_ai_agent_assets(
                        cursor,
                        allowed_table_names=allowed_tables,
                        oci_auth_config=oci_auth_config,
                        model_settings=model_settings,
                    )
                    if target_category_id is not None:
                        self._save_category_select_ai_profile_metadata_with_cursor(
                            cursor,
                            category_id=target_category_id,
                            profile_name=asset_names["profile_name"],
                            team_name=asset_names["team_name"],
                            config_hash=asset_names.get("config_fingerprint", ""),
                            ready=True,
                            error_message="",
                        )
                    conn.commit()
                    conversation_id = self._create_select_ai_conversation(cursor)

                    cursor.execute(
                        """
                        SELECT DBMS_CLOUD_AI_AGENT.RUN_TEAM(
                            team_name => :team_name,
                            user_prompt => :user_prompt,
                            params => :params
                        )
                        FROM DUAL
                        """,
                        {
                            "team_name": asset_names["team_name"],
                            "user_prompt": query.strip(),
                            "params": self._build_select_ai_run_team_params(conversation_id),
                        },
                    )
                    row = cursor.fetchone()

            raw_response = self._coerce_db_text(row[0] if row else "")
            parsed = self._extract_json_payload(raw_response)
            generated_sql = self._normalize_generated_select(
                str(parsed.get("sql") or parsed.get("generated_sql") or "").strip()
            )
            if not generated_sql:
                generated_sql = self._normalize_generated_select(self._extract_select_statement(raw_response))

            explanation = str(parsed.get("explanation") or "").strip()
            if not generated_sql:
                return {
                    "success": False,
                    "message": "Select AI Agent 応答から SQL を取得できませんでした",
                    "raw_response": raw_response,
                }

            exec_result = self.execute_select_query(
                generated_sql,
                max_rows=max_rows,
                allowed_tables=allowed_tables,
            )
            if not exec_result.get("success"):
                return {
                    "success": False,
                    "message": exec_result.get("message", "クエリ実行に失敗しました"),
                    "generated_sql": generated_sql,
                    "explanation": explanation,
                    "raw_response": raw_response,
                    "engine": "select_ai_agent",
                    "engine_meta": {
                        "profile_name": asset_names["profile_name"],
                        "team_name": asset_names["team_name"],
                        "model_name": asset_names.get("model_name", ""),
                        "region": asset_names.get("region", ""),
                        "conversation_id": conversation_id,
                        "config_hash": asset_names.get("config_fingerprint", ""),
                        "api_format": str(model_settings.get("select_ai_oci_apiformat") or "").strip().upper(),
                        "use_comments": bool(model_settings.get("select_ai_use_comments", True)),
                    },
                }

            return {
                "success": True,
                "generated_sql": generated_sql,
                "explanation": explanation,
                "results": {
                    "columns": exec_result.get("columns", []),
                    "rows": exec_result.get("rows", []),
                    "total": exec_result.get("total", 0),
                },
                "engine": "select_ai_agent",
                "engine_meta": {
                    "profile_name": asset_names["profile_name"],
                    "team_name": asset_names["team_name"],
                    "model_name": asset_names.get("model_name", ""),
                    "region": asset_names.get("region", ""),
                    "conversation_id": conversation_id,
                    "config_hash": asset_names.get("config_fingerprint", ""),
                    "api_format": str(model_settings.get("select_ai_oci_apiformat") or "").strip().upper(),
                    "use_comments": bool(model_settings.get("select_ai_use_comments", True)),
                },
            }
        except Exception as e:
            error_message = str(e)
            error_message_upper = error_message.upper()
            should_fallback_to_direct_llm = False
            if target_category_id is not None:
                self.save_category_select_ai_profile_metadata(
                    category_id=target_category_id,
                    profile_name=str(asset_names.get("profile_name") or ""),
                    team_name=str(asset_names.get("team_name") or ""),
                    config_hash=str(asset_names.get("config_fingerprint") or ""),
                    ready=bool(asset_names),
                    error_message=error_message,
                )
            if "ORA-20404" in error_message_upper or "OBJECT NOT FOUND" in error_message_upper:
                should_fallback_to_direct_llm = True
                error_message = (
                    "Select AI Agent の実行に失敗しました。現在のモデルまたは OCI Generative AI "
                    "エンドポイント設定では Select AI Agent を実行できません: %s" % str(e)
                )
            elif self._is_select_ai_conversation_error(error_message_upper):
                should_fallback_to_direct_llm = True
                error_message = (
                    "Select AI Agent の実行に失敗しました。Web / 接続プール経由の Select AI Agent 実行では "
                    "conversation_id が必要です。RUN_TEAM(params) に conversation_id を指定してください: %s"
                    % str(e)
                )
            elif (
                "ORA-01031" in error_message_upper
                or "INSUFFICIENT PRIVILEGES" in error_message_upper
                or "PLS-00201" in error_message_upper
                or "MUST BE DECLARED" in error_message_upper
            ):
                should_fallback_to_direct_llm = True
                error_message = (
                    "Select AI Agent の実行に失敗しました。DBMS_CLOUD / DBMS_CLOUD_AI / "
                    "DBMS_CLOUD_AI_AGENT の利用権限を確認してください: %s" % str(e)
                )
            if should_fallback_to_direct_llm:
                logger.warning("Select AI Agent 自然言語検索は direct LLM にフォールバックします: %s", error_message)
            else:
                logger.error("Select AI Agent 自然言語検索エラー: %s", error_message, exc_info=True)
            return {
                "success": False,
                "message": error_message,
                "fallback_to_direct_llm": should_fallback_to_direct_llm,
            }

    def get_table_data(self, table_name: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """テーブルデータをページング付きで取得"""
        if not table_name:
            return {"success": False, "message": "テーブル名が指定されていません",
                    "table_name": "", "columns": [], "rows": [], "total": 0}

        # セキュリティ: 許可テーブルかチェック
        allowed = self._get_allowed_table_set()
        table_name_upper = table_name.upper()
        if table_name_upper not in allowed:
            logger.warning("許可されていないテーブルへのアクセス試行: %s", table_name)
            return {"success": False, "message": "許可されていないテーブルです",
                    "table_name": table_name, "columns": [], "rows": [], "total": 0}

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Oracleテーブル存在チェック（DROP TABLE後などに備えて）
                    cursor.execute(
                        "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1",
                        [table_name_upper]
                    )
                    if int(cursor.fetchone()[0] or 0) == 0:
                        # 物理テーブルが存在しない場合は空データとして正常返却
                        return {"success": True, "table_name": table_name_upper,
                                "columns": [], "rows": [], "total": 0,
                                "limit": limit, "offset": offset}

                    # 総件数取得
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name_upper}")
                    total = cursor.fetchone()[0]
                    order_by_clause = self._build_table_data_order_by_clause(cursor, table_name_upper)

                    # データ取得（ページング）
                    # 行削除に使うため、ROWIDを ROW_ID_META として含める（表示カラムからは除外可能）
                    cursor.execute(
                        f"""SELECT ROWIDTOCHAR(t.ROWID) AS ROW_ID_META, t.*
                          FROM {table_name_upper} t
                         ORDER BY {order_by_clause}
                         OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY""",
                        {"offset": offset, "limit": limit}
                    )
                    columns = [desc[0] for desc in cursor.description]
                    rows_raw = cursor.fetchall()
                    rows = [self._serialize_db_row(columns, row) for row in rows_raw]
                    display_columns = [c for c in columns if c != "ROW_ID_META"]

                    return {
                        "success": True,
                        "table_name": table_name_upper,
                        "columns": display_columns,
                        "rows": rows,
                        "total": total,
                        "limit": limit,
                        "offset": offset,
                    }
        except Exception as e:
            # ORA-00942: テーブルが存在しない（USER_TABLES確認後に削除されたレースコンディション含む）
            # 物理テーブルが存在しない場合は空データとして正常返却
            if self._is_missing_table_error(e):
                logger.warning("テーブルが存在しません (%s): %s", table_name_upper, e)
                return {"success": True, "table_name": table_name_upper,
                        "columns": [], "rows": [], "total": 0,
                        "limit": limit, "offset": offset}
            logger.error("テーブルデータ取得エラー (%s): %s", table_name, e, exc_info=True)
            return {"success": False, "message": f"データ取得エラー: {str(e)}",
                    "table_name": table_name, "columns": [], "rows": [], "total": 0}

    def delete_table_row_by_rowid(self, table_name: str, rowid: str) -> Dict[str, Any]:
        """ROWID指定でテーブル行を削除"""
        if not table_name:
            return {"success": False, "message": "テーブル名が指定されていません"}
        if not rowid:
            return {"success": False, "message": "row_id が指定されていません"}

        table_name_upper = table_name.upper()

        if not self._is_safe_table_name(table_name_upper):
            return {"success": False, "message": "不正なテーブル名です"}

        if not re.match(r"^[A-Za-z0-9+/=]+$", rowid):
            return {"success": False, "message": "不正な row_id 形式です"}

        # get_allowed_table_names() を1回だけ呼び出し、許可チェックとリレーション取得を兼ねる
        entries = self.get_allowed_table_names()
        allowed = self._build_allowed_table_set_from_entries(entries)
        allowed.update(self._TABLE_BROWSER_TARGETS)
        if table_name_upper not in allowed:
            logger.warning("許可されていないテーブルへの削除試行: %s", table_name)
            return {"success": False, "message": "許可されていないテーブルです"}

        relation = self._find_allowed_table_relation(table_name_upper, entries=entries)

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    detail_deleted = 0
                    if relation.get("table_type") == "header":
                        cursor.execute(
                            f"SELECT {_HEADER_ID_COLUMN_NAME} FROM {table_name_upper} WHERE ROWID = CHARTOROWID(:rid)",
                            {"rid": rowid}
                        )
                        header_row = cursor.fetchone()
                        if not header_row:
                            return {"success": False, "message": "対象レコードが見つかりません"}

                        header_id = header_row[0]
                        line_table_name = str(relation.get("line_table_name") or "").upper()
                        if line_table_name and self._is_safe_table_name(line_table_name):
                            # ラインテーブルが物理的に存在する場合のみ削除（ORA-00942防止）
                            cursor.execute(
                                "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1",
                                [line_table_name]
                            )
                            if int(cursor.fetchone()[0] or 0) > 0:
                                cursor.execute(
                                    f"DELETE FROM {line_table_name} WHERE {_HEADER_ID_COLUMN_NAME} = :header_id",
                                    {"header_id": header_id}
                                )
                                detail_deleted = int(cursor.rowcount or 0)

                    cursor.execute(
                        f"DELETE FROM {table_name_upper} WHERE ROWID = CHARTOROWID(:rid)",
                        {"rid": rowid}
                    )
                    deleted = cursor.rowcount
                conn.commit()

            if deleted > 0:
                return {
                    "success": True,
                    "deleted": deleted,
                    "detail_deleted": detail_deleted,
                    "table_type": relation.get("table_type", ""),
                }
            return {"success": False, "message": "対象レコードが見つかりません"}
        except Exception as e:
            if self._is_missing_table_error(e):
                logger.warning("テーブルが存在しません (%s): %s", table_name_upper, e)
                return {"success": False, "message": "テーブルが存在しません"}
            logger.error("ROWID削除エラー (%s, %s): %s", table_name_upper, rowid, e, exc_info=True)
            return {"success": False, "message": f"削除エラー: {str(e)}"}

    def _find_allowed_table_relation(
        self, table_name: str, entries: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        table_name_upper = (table_name or "").upper()
        if entries is None:
            entries = self.get_allowed_table_names()
        for entry in entries:
            header_table_name = str(entry.get("header_table_name") or "").upper()
            line_table_name = str(entry.get("line_table_name") or "").upper()
            if table_name_upper == header_table_name:
                return {
                    "table_type": "header",
                    "header_table_name": header_table_name,
                    "line_table_name": line_table_name,
                    "category_id": int(entry.get("category_id") or 0),
                    "category_name": entry.get("category_name") or "",
                }
            if table_name_upper == line_table_name:
                return {
                    "table_type": "line",
                    "header_table_name": header_table_name,
                    "line_table_name": line_table_name,
                    "category_id": int(entry.get("category_id") or 0),
                    "category_name": entry.get("category_name") or "",
                }
        return {
            "table_type": "",
            "header_table_name": "",
            "line_table_name": "",
            "category_id": 0,
            "category_name": "",
        }

    def delete_allowed_table(self, table_name: str) -> Dict[str, Any]:
        """許可済みテーブルのみ DROP TABLE する"""
        if not table_name:
            return {"success": False, "message": "テーブル名が指定されていません"}

        table_name_upper = table_name.upper()
        allowed = self._get_allowed_table_set()
        if table_name_upper not in allowed:
            logger.warning("許可されていないテーブルへの削除試行: %s", table_name)
            return {"success": False, "message": "許可されていないテーブルです"}

        if not self._is_safe_table_name(table_name_upper):
            return {"success": False, "message": "不正なテーブル名です"}

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME = :1",
                        [table_name_upper]
                    )
                    table_exists = int(cursor.fetchone()[0] or 0) > 0
                    if not table_exists:
                        return {"success": False, "message": "対象テーブルが見つかりません"}

                    cursor.execute(f"DROP TABLE {table_name_upper} PURGE")
                conn.commit()

            return {"success": True, "table_name": table_name_upper}
        except Exception as e:
            logger.error("テーブル削除エラー (%s): %s", table_name_upper, e, exc_info=True)
            return {"success": False, "message": f"削除エラー: {str(e)}"}

    def log_activity(self, activity_type: str, description: str,
                     file_id: int = None, registration_id: int = None,
                     user_name: str = "") -> None:
        """アクティビティログを記録"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO DENPYO_ACTIVITY_LOG
                        (ACTIVITY_TYPE, DESCRIPTION, FILE_ID, REGISTRATION_ID, USER_NAME)
                        VALUES (:1, :2, :3, :4, :5)""",
                        [activity_type, description, file_id, registration_id, user_name]
                    )
                conn.commit()
        except Exception as e:
            logger.error("アクティビティログ記録エラー: %s", e, exc_info=True)

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """ダッシュボード統計情報を取得"""
        stats = {
            "upload_stats": {"total_files": 0, "this_month": 0},
            "registration_stats": {"total_registrations": 0, "this_month": 0},
            "category_stats": {"total_categories": 0, "active_categories": 0},
            "recent_activities": [],
        }

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # ファイル統計
                    cursor.execute("SELECT COUNT(*) FROM DENPYO_FILES")
                    stats["upload_stats"]["total_files"] = cursor.fetchone()[0]

                    cursor.execute(
                        "SELECT COUNT(*) FROM DENPYO_FILES WHERE UPLOADED_AT >= TRUNC(SYSDATE, 'MM')"
                    )
                    stats["upload_stats"]["this_month"] = cursor.fetchone()[0]

                    # 登録統計
                    cursor.execute("SELECT COUNT(*) FROM DENPYO_REGISTRATIONS")
                    stats["registration_stats"]["total_registrations"] = cursor.fetchone()[0]

                    cursor.execute(
                        "SELECT COUNT(*) FROM DENPYO_REGISTRATIONS WHERE REGISTERED_AT >= TRUNC(SYSDATE, 'MM')"
                    )
                    stats["registration_stats"]["this_month"] = cursor.fetchone()[0]

                    # カテゴリ統計
                    cursor.execute("SELECT COUNT(*) FROM DENPYO_CATEGORIES")
                    stats["category_stats"]["total_categories"] = cursor.fetchone()[0]

                    cursor.execute("SELECT COUNT(*) FROM DENPYO_CATEGORIES WHERE IS_ACTIVE = 1")
                    stats["category_stats"]["active_categories"] = cursor.fetchone()[0]

                    # 最近のアクティビティ
                    cursor.execute(
                        """SELECT ACTIVITY_TYPE, DESCRIPTION, FILE_ID, CREATED_AT
                        FROM DENPYO_ACTIVITY_LOG
                        ORDER BY CREATED_AT DESC
                        FETCH FIRST 10 ROWS ONLY"""
                    )
                    for row in cursor.fetchall():
                        stats["recent_activities"].append({
                            "type": row[0],
                            "description": row[1],
                            "file_id": row[2],
                            "created_at": str(row[3]) if row[3] else "",
                        })

        except Exception as e:
            logger.warning("ダッシュボード統計取得エラー (テーブル未作成の可能性): %s", e)

        return stats

    def get_files(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
        upload_kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """ファイル一覧を取得（DENPYO_FILES 基準）"""
        if not self._ensure_management_tables():
            return []
        kind = (upload_kind or "").strip().lower()
        raw_prefix = (os.environ.get("OCI_SLIPS_RAW_PREFIX", "denpyo-raw") or "denpyo-raw").strip("/")
        category_prefix = (os.environ.get("OCI_SLIPS_CATEGORY_PREFIX", "denpyo-category") or "denpyo-category").strip("/")
        
        path_prefix = None
        if kind == "raw":
            path_prefix = raw_prefix
        elif kind == "category":
            path_prefix = category_prefix

        try:
            normalized_status = (status or "").strip().upper()

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    if kind == "category":
                        query = """SELECT f.ID, f.FILE_NAME, f.ORIGINAL_FILE_NAME, f.CONTENT_TYPE, f.FILE_SIZE, f.STATUS, f.UPLOADED_BY, f.UPLOADED_AT,
                                          CASE
                                              WHEN f.ANALYSIS_RESULT IS NOT NULL OR sc.ANALYSIS_RESULT IS NOT NULL THEN 1
                                              ELSE 0
                                          END AS HAS_ANALYSIS_RESULT,
                                          f.UPDATED_AT
                                   FROM DENPYO_FILES f
                                   LEFT JOIN SLIPS_CATEGORY sc ON sc.OBJECT_NAME = f.OBJECT_STORAGE_PATH
                                   WHERE 1=1"""
                    else:
                        query = """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, CONTENT_TYPE, FILE_SIZE, STATUS, UPLOADED_BY, UPLOADED_AT,
                                          CASE WHEN ANALYSIS_RESULT IS NOT NULL THEN 1 ELSE 0 END AS HAS_ANALYSIS_RESULT,
                                          UPDATED_AT
                                   FROM DENPYO_FILES WHERE 1=1"""
                    params = []

                    if path_prefix:
                        path_column = "f.OBJECT_STORAGE_PATH" if kind == "category" else "OBJECT_STORAGE_PATH"
                        query += f" AND {path_column} LIKE :{len(params)+1}"
                        params.append(f"{path_prefix}/%")
                    
                    if normalized_status:
                        status_column = "f.STATUS" if kind == "category" else "STATUS"
                        query += f" AND {status_column} = :{len(params)+1}"
                        params.append(normalized_status)
                    
                    order_column = "f.UPLOADED_AT" if kind == "category" else "UPLOADED_AT"
                    query += f" ORDER BY {order_column} DESC OFFSET :{len(params)+1} ROWS FETCH NEXT :{len(params)+2} ROWS ONLY"
                    params.extend([offset, limit])
                    
                    cursor.execute(query, params)

                    files = []
                    for row in cursor.fetchall():
                        files.append({
                            "file_id": str(row[0]),
                            "file_name": row[1],
                            "original_file_name": row[2],
                            "content_type": row[3],
                            "file_size": row[4],
                            "status": row[5],
                            "uploaded_by": row[6] or "",
                            "uploaded_at": str(row[7]) if row[7] else "",
                            "has_analysis_result": bool(row[8]),
                            "updated_at": str(row[9]) if row[9] else "",
                        })
                    return files
        except Exception as e:
            logger.error("ファイル一覧取得エラー: %s", e, exc_info=True)
            return []

    def get_files_count(self, status: str = None, upload_kind: Optional[str] = None) -> int:
        """ファイル総件数を取得（DENPYO_FILES 基準）"""
        if not self._ensure_management_tables():
            return 0
        kind = (upload_kind or "").strip().lower()
        raw_prefix = (os.environ.get("OCI_SLIPS_RAW_PREFIX", "denpyo-raw") or "denpyo-raw").strip("/")
        category_prefix = (os.environ.get("OCI_SLIPS_CATEGORY_PREFIX", "denpyo-category") or "denpyo-category").strip("/")
        
        path_prefix = None
        if kind == "raw":
            path_prefix = raw_prefix
        elif kind == "category":
            path_prefix = category_prefix

        try:
            normalized_status = (status or "").strip().upper()

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    query = "SELECT COUNT(*) FROM DENPYO_FILES WHERE 1=1"
                    params = []

                    if path_prefix:
                        query += f" AND OBJECT_STORAGE_PATH LIKE :{len(params)+1}"
                        params.append(f"{path_prefix}/%")
                    
                    if normalized_status:
                        query += f" AND STATUS = :{len(params)+1}"
                        params.append(normalized_status)
                    
                    cursor.execute(query, params)
                    return cursor.fetchone()[0]
        except Exception as e:
            logger.error("ファイル件数取得エラー: %s", e, exc_info=True)
            return 0

    def get_file_by_id(self, file_id: int) -> Optional[Dict[str, Any]]:
        """IDでファイルレコードを取得"""
        if not self._ensure_management_tables():
            return None
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, OBJECT_STORAGE_PATH,
                                  CONTENT_TYPE, FILE_SIZE, STATUS, ANALYSIS_KIND, UPLOADED_BY, UPLOADED_AT,
                                  CASE WHEN ANALYSIS_RESULT IS NOT NULL THEN 1 ELSE 0 END AS HAS_ANALYSIS_RESULT,
                                  ANALYZED_AT, UPDATED_AT
                        FROM DENPYO_FILES WHERE ID = :1""",
                        [file_id]
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    return {
                        "id": row[0],
                        "file_name": row[1],
                        "original_file_name": row[2],
                        "object_storage_path": row[3],
                        "content_type": row[4],
                        "file_size": row[5],
                        "status": row[6],
                        "analysis_kind": row[7],
                        "uploaded_by": row[8],
                        "uploaded_at": str(row[9]) if row[9] else "",
                        "has_analysis_result": bool(row[10]),
                        "analyzed_at": str(row[11]) if row[11] else "",
                        "updated_at": str(row[12]) if row[12] else "",
                    }
        except Exception as e:
            logger.error("ファイル取得エラー (id=%s): %s", file_id, e, exc_info=True)
            return None

    def get_file_by_object_storage_path(self, object_storage_path: str) -> Optional[Dict[str, Any]]:
        """OBJECT_STORAGE_PATH でファイルレコードを取得"""
        if not self._ensure_management_tables():
            return None

        normalized_path = (object_storage_path or "").strip()
        if not normalized_path:
            return None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, OBJECT_STORAGE_PATH,
                                  CONTENT_TYPE, FILE_SIZE, STATUS, ANALYSIS_KIND, UPLOADED_BY, UPLOADED_AT,
                                  CASE WHEN ANALYSIS_RESULT IS NOT NULL THEN 1 ELSE 0 END AS HAS_ANALYSIS_RESULT,
                                  ANALYZED_AT, UPDATED_AT
                           FROM DENPYO_FILES
                          WHERE OBJECT_STORAGE_PATH = :1""",
                        [normalized_path],
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    return {
                        "id": row[0],
                        "file_name": row[1],
                        "original_file_name": row[2],
                        "object_storage_path": row[3],
                        "content_type": row[4],
                        "file_size": row[5],
                        "status": row[6],
                        "analysis_kind": row[7],
                        "uploaded_by": row[8],
                        "uploaded_at": str(row[9]) if row[9] else "",
                        "has_analysis_result": bool(row[10]),
                        "analyzed_at": str(row[11]) if row[11] else "",
                        "updated_at": str(row[12]) if row[12] else "",
                    }
        except Exception as e:
            logger.error("ファイル取得エラー (object_storage_path=%s): %s", object_storage_path, e, exc_info=True)
            return None

    def get_files_by_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        """IDのリストでDENPYO_FILESレコードを取得"""
        if not ids:
            return []
        if not self._ensure_management_tables():
            return []
        try:
            placeholders = ",".join([f":{i+1}" for i in range(len(ids))])
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, OBJECT_STORAGE_PATH,
                                   CONTENT_TYPE, FILE_SIZE, STATUS, UPLOADED_BY, UPLOADED_AT,
                                   CASE WHEN ANALYSIS_RESULT IS NOT NULL THEN 1 ELSE 0 END AS HAS_ANALYSIS_RESULT,
                                   UPDATED_AT
                        FROM DENPYO_FILES
                        WHERE ID IN ({placeholders})
                        ORDER BY UPLOADED_AT DESC""",
                        ids,
                    )
                    result = []
                    for row in cursor.fetchall():
                        result.append({
                            "id": row[0],
                            "file_name": row[1],
                            "original_file_name": row[2],
                            "object_name": row[3],
                            "object_storage_path": row[3],
                            "content_type": row[4] or "image/jpeg",
                            "file_size": row[5],
                            "status": row[6],
                            "uploaded_by": row[7],
                            "uploaded_at": str(row[8]) if row[8] else "",
                            "has_analysis_result": bool(row[9]),
                            "updated_at": str(row[10]) if row[10] else "",
                        })
                    return result
        except Exception as e:
            logger.error("DENPYO_FILES ファイル取得エラー (ids=%s): %s", ids, e, exc_info=True)
            return []

    def save_analysis_result(self, file_id: int, analysis_kind: str, analysis_result: Dict[str, Any]) -> bool:
        """分析結果 JSON を保存し、分析完了日時を更新"""
        if not self._ensure_management_tables():
            return False

        try:
            payload = json.dumps(analysis_result, ensure_ascii=False).encode("utf-8")
            attempt_payloads = (
                self._build_attempt_blob_payloads(analysis_result)
                if (analysis_kind or "").strip().lower() == "category"
                else [None] * len(_ANALYSIS_RESULT_ATTEMPT_COLUMNS)
            )
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """UPDATE DENPYO_FILES
                           SET ANALYSIS_KIND = :1,
                               ANALYSIS_RESULT = :2,
                               ANALYSIS_RESULT_1 = :3,
                               ANALYSIS_RESULT_2 = :4,
                               ANALYSIS_RESULT_3 = :5,
                               ANALYZED_AT = CURRENT_TIMESTAMP,
                               UPDATED_AT = CURRENT_TIMESTAMP
                         WHERE ID = :6""",
                        [analysis_kind, payload, *attempt_payloads, file_id],
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.error("分析結果保存エラー (id=%s): %s", file_id, e, exc_info=True)
            return False

    def get_analysis_result(self, file_id: int) -> Optional[Dict[str, Any]]:
        """保存済み分析結果を取得"""
        if not self._ensure_management_tables():
            return None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ANALYSIS_KIND, ANALYSIS_RESULT, ANALYSIS_RESULT_1, ANALYSIS_RESULT_2, ANALYSIS_RESULT_3, ANALYZED_AT
                             FROM DENPYO_FILES
                            WHERE ID = :1""",
                        [file_id],
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None

                    analysis_kind = row[0] or ""
                    base_result = self._decode_json_blob(row[1])
                    parsed_result = (
                        self._merge_analysis_attempts_into_result(base_result, list(row[2:5]))
                        if str(analysis_kind).strip().lower() == "category"
                        else base_result
                    )
                    if parsed_result is None:
                        return None
                    return {
                        "analysis_kind": analysis_kind,
                        "result": parsed_result,
                        "analyzed_at": str(row[5]) if row[5] else "",
                    }
        except Exception as e:
            logger.error("分析結果取得エラー (id=%s): %s", file_id, e, exc_info=True)
            return None

    def delete_file_record(self, file_id: int) -> Dict[str, Any]:
        """ファイルレコードを削除（登録済みの場合は拒否）"""
        logger.info("[DB] delete_file_record 開始 file_id=%s", file_id)
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    logger.info("[DB] ファイルパス取得中 file_id=%s", file_id)
                    cursor.execute(
                        "SELECT OBJECT_STORAGE_PATH FROM DENPYO_FILES WHERE ID = :1",
                        [file_id]
                    )
                    file_row = cursor.fetchone()
                    if not file_row:
                        logger.warning("❌ [DB] ファイルが見つかりません file_id=%s", file_id)
                        return {"success": False, "message": "ファイルが見つかりません"}
                    object_storage_path = file_row[0] or ""

                    # 登録済みチェック
                    logger.info("[DB] 登録済みチェック中 file_id=%s", file_id)
                    cursor.execute(
                        "SELECT COUNT(*) FROM DENPYO_REGISTRATIONS WHERE FILE_ID = :1",
                        [file_id]
                    )
                    reg_count = cursor.fetchone()[0]
                    logger.info("[DB] 登録済み件数: %d (file_id=%s)", reg_count, file_id)
                    if reg_count > 0:
                        logger.warning("❌ [DB] 登録済みファイルは削除できません file_id=%s", file_id)
                        return {"success": False, "message": "登録済みファイルは削除できません"}

                    # アクティビティログも削除
                    logger.info("[DB] アクティビティログ削除中 file_id=%s", file_id)
                    cursor.execute(
                        "DELETE FROM DENPYO_ACTIVITY_LOG WHERE FILE_ID = :1",
                        [file_id]
                    )
                    log_deleted = cursor.rowcount
                    logger.info("[DB] アクティビティログ削除件数: %d (file_id=%s)", log_deleted, file_id)
                    
                    logger.info("[DB] ファイルレコード削除中 file_id=%s", file_id)
                    cursor.execute(
                        "DELETE FROM DENPYO_FILES WHERE ID = :1",
                        [file_id]
                    )
                    deleted = cursor.rowcount
                    logger.info("[DB] ファイルレコード削除件数: %d (file_id=%s)", deleted, file_id)

                    # 伝票一覧は raw 管理のため、SLIPS_RAW の同一 OBJECT_NAME を削除
                    raw_deleted = 0
                    if deleted > 0 and object_storage_path:
                        try:
                            cursor.execute(
                                "DELETE FROM SLIPS_RAW WHERE OBJECT_NAME = :1",
                                [object_storage_path]
                            )
                            raw_deleted = cursor.rowcount
                        except Exception as raw_error:
                            logger.warning(
                                "[DB] SLIPS_RAW 削除をスキップ (file_id=%s, object=%s): %s",
                                file_id,
                                object_storage_path,
                                raw_error,
                            )
                        logger.info(
                            "[DB] SLIPS_RAW削除件数 file_id=%s object=%s raw=%d",
                            file_id,
                            object_storage_path,
                            raw_deleted,
                        )
                    
                logger.info("[DB] commit 中 file_id=%s", file_id)
                conn.commit()
                logger.info("[DB] commit 完了 file_id=%s", file_id)

            if deleted > 0:
                logger.info("✅ [DB] ファイルを削除しました file_id=%s", file_id)
                return {"success": True, "message": "ファイルを削除しました"}
            logger.warning("❌ [DB] ファイル削除件数が 0 でした file_id=%s", file_id)
            return {"success": False, "message": "ファイル削除に失敗しました"}
        except Exception as e:
            logger.error("❌ [DB] ファイル削除エラー (id=%s): %s", file_id, e, exc_info=True)
            return {"success": False, "message": str(e)}

    def update_file_status(self, file_id: int, status: str) -> bool:
        """ファイルステータスを更新"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE DENPYO_FILES SET STATUS = :1, UPDATED_AT = CURRENT_TIMESTAMP WHERE ID = :2",
                        [status, file_id]
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.error("ステータス更新エラー (id=%s): %s", file_id, e, exc_info=True)
            return False

    @classmethod
    def close_shared_pool(cls) -> None:
        """共有接続プールを閉じる"""
        with cls._pool_lock:
            if cls._shared_pool is not None:
                try:
                    cls._shared_pool.close()
                    logger.info("データベース接続プールを閉じました")
                except Exception as e:
                    logger.error("接続プール閉鎖エラー: %s", e)
                finally:
                    cls._shared_pool = None
                    cls._shared_pool_config_key = None
                    cls._reset_shared_initialization_flags()

    def close_pool(self) -> None:
        """接続プールを閉じる"""
        type(self).close_shared_pool()
        self._pool = None
        self._management_tables_initialized = False
        self._slips_tables_initialized = False
