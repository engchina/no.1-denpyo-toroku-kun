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
import os
import re
import time
from contextlib import contextmanager
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
        IS_ACTIVE NUMBER(1) DEFAULT 1,
        CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT UQ_CATEGORY_NAME UNIQUE (CATEGORY_NAME)
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
    CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT UQ_SLIPS_CATEGORY_OBJECT UNIQUE (NAMESPACE, BUCKET_NAME, OBJECT_NAME)
)
"""

SLIPS_CATEGORY_INDEX_DDL = """
CREATE INDEX IDX_SLIPS_CATEGORY_BUCKET ON SLIPS_CATEGORY(BUCKET_NAME, NAMESPACE)
"""


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

    def __init__(self):
        self._pool = None
        self._management_tables_initialized = False
        self._slips_tables_initialized = False

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
        if self._pool is not None:
            return True

        if not ORACLEDB_AVAILABLE:
            logger.error("oracledb モジュールが利用できません")
            return False

        conn_info = self._parse_connection_string()
        if not conn_info["username"] or not conn_info["dsn"]:
            logger.error("データベース接続文字列が未設定です")
            return False

        wallet_location = self._get_wallet_location()

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

            self._pool = oracledb.create_pool(**pool_kwargs)
            logger.info("データベース接続プールを作成しました (min=%d, max=%d)", self.POOL_MIN, self.POOL_MAX)
            return True
        except Exception as e:
            logger.error("接続プール作成エラー: %s", e, exc_info=True)
            self._pool = None
            return False

    @contextmanager
    def get_connection(self):
        """接続プールからコネクションを取得するコンテキストマネージャー"""
        if not self._ensure_pool():
            raise ConnectionError("データベース接続プールが利用できません")

        connection = None
        try:
            connection = self._pool.acquire()
            yield connection
        finally:
            if connection is not None:
                try:
                    self._pool.release(connection)
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
        if self._management_tables_initialized:
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
                conn.commit()
            self._management_tables_initialized = True
            return True
        except Exception as e:
            logger.error("管理テーブル初期化エラー: %s", e, exc_info=True)
            return False

    def execute_ddl(self, ddl_statement: str) -> Dict[str, Any]:
        """動的DDLを実行（AI提案のテーブル作成用）"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(ddl_statement)
                conn.commit()
            return {"success": True, "message": "DDL実行完了"}
        except Exception as e:
            error_str = str(e)
            if "ORA-00955" in error_str:
                return {"success": True, "message": "テーブルは既に存在します"}
            logger.error("DDL実行エラー: %s", e, exc_info=True)
            return {"success": False, "message": str(e)}

    def _ensure_slips_tables(self) -> bool:
        """SLIPS_RAW / SLIPS_CATEGORY テーブルとインデックスの存在を保証"""
        if self._slips_tables_initialized:
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
                conn.commit()
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
            "message": ""
        }

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # --- ヘッダーデータ INSERT ---
                    if header_table_name and header_fields:
                        header_cols = []
                        header_vals = []
                        for field in header_fields:
                            col_name = field.get("field_name_en", "").upper()
                            value = field.get("value")
                            if col_name and value is not None:
                                header_cols.append(col_name)
                                header_vals.append(value)

                        if header_cols:
                            col_str = ", ".join(header_cols)
                            placeholders = ", ".join([f":{i+1}" for i in range(len(header_vals))])
                            insert_sql = f"INSERT INTO {header_table_name.upper()} ({col_str}) VALUES ({placeholders})"
                            try:
                                cursor.execute(insert_sql, header_vals)
                                result["header_inserted"] = cursor.rowcount
                            except Exception as e:
                                logger.warning("ヘッダーINSERTエラー: %s", e)
                                result["message"] += f"ヘッダーINSERTエラー: {str(e)}. "

                    # --- 明細データ INSERT ---
                    if line_table_name and raw_lines:
                        line_inserted = 0
                        for line in raw_lines:
                            line_cols = []
                            line_vals = []
                            for col_name, value in line.items():
                                if col_name and value is not None:
                                    line_cols.append(col_name.upper())
                                    line_vals.append(value)

                            if line_cols:
                                col_str = ", ".join(line_cols)
                                placeholders = ", ".join([f":{i+1}" for i in range(len(line_vals))])
                                insert_sql = f"INSERT INTO {line_table_name.upper()} ({col_str}) VALUES ({placeholders})"
                                try:
                                    cursor.execute(insert_sql, line_vals)
                                    line_inserted += cursor.rowcount
                                except Exception as e:
                                    logger.warning("明細INSERTエラー (line): %s", e)

                        result["line_inserted"] = line_inserted

                conn.commit()

            if result["header_inserted"] > 0 or result["line_inserted"] > 0:
                result["message"] = f"ヘッダー: {result['header_inserted']}件, 明細: {result['line_inserted']}件を登録しました"
            elif not result["message"]:
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

    def insert_registration(self, file_id: int, category_name: str,
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
                        (FILE_ID, CATEGORY_NAME, HEADER_TABLE_NAME, LINE_TABLE_NAME,
                         HEADER_RECORD_ID, LINE_COUNT, AI_CONFIDENCE, REGISTERED_BY)
                        VALUES (:1, :2, :3, :4, :5, :6, :7, :8)
                        RETURNING ID INTO :9""",
                        [file_id, category_name, header_table, line_table,
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
        """全カテゴリ一覧を登録件数付きで取得"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT c.ID, c.CATEGORY_NAME, c.CATEGORY_NAME_EN,
                                  c.HEADER_TABLE_NAME, c.LINE_TABLE_NAME,
                                  c.DESCRIPTION, c.IS_ACTIVE, c.CREATED_AT, c.UPDATED_AT,
                                  COUNT(r.ID) AS REGISTRATION_COUNT
                        FROM DENPYO_CATEGORIES c
                        LEFT JOIN DENPYO_REGISTRATIONS r ON c.ID = r.CATEGORY_ID
                        GROUP BY c.ID, c.CATEGORY_NAME, c.CATEGORY_NAME_EN,
                                 c.HEADER_TABLE_NAME, c.LINE_TABLE_NAME,
                                 c.DESCRIPTION, c.IS_ACTIVE, c.CREATED_AT, c.UPDATED_AT
                        ORDER BY c.CREATED_AT DESC"""
                    )
                    categories = []
                    for row in cursor.fetchall():
                        categories.append({
                            "id": row[0],
                            "category_name": row[1],
                            "category_name_en": row[2] or "",
                            "header_table_name": row[3] or "",
                            "line_table_name": row[4] or "",
                            "description": row[5] or "",
                            "is_active": bool(row[6]),
                            "created_at": str(row[7]) if row[7] else "",
                            "updated_at": str(row[8]) if row[8] else "",
                            "registration_count": row[9],
                        })
                    return categories
        except Exception as e:
            logger.error("カテゴリ一覧取得エラー: %s", e, exc_info=True)
            return []

    def get_category_by_id(self, category_id: int) -> Optional[Dict[str, Any]]:
        """IDでカテゴリレコードを取得"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, CATEGORY_NAME, CATEGORY_NAME_EN,
                                  HEADER_TABLE_NAME, LINE_TABLE_NAME,
                                  DESCRIPTION, IS_ACTIVE, CREATED_AT, UPDATED_AT
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
                        "is_active": bool(row[6]),
                        "created_at": str(row[7]) if row[7] else "",
                        "updated_at": str(row[8]) if row[8] else "",
                    }
        except Exception as e:
            logger.error("カテゴリ取得エラー (id=%s): %s", category_id, e, exc_info=True)
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
                        "SELECT COUNT(*) FROM DENPYO_REGISTRATIONS WHERE CATEGORY_ID = :1",
                        [category_id]
                    )
                    reg_count = cursor.fetchone()[0]
                    if reg_count > 0:
                        return {
                            "success": False,
                            "message": f"登録済みデータが {reg_count} 件あるため削除できません"
                        }

                    cursor.execute(
                        "DELETE FROM DENPYO_CATEGORIES WHERE ID = :1",
                        [category_id]
                    )
                    deleted = cursor.rowcount
                conn.commit()

            if deleted > 0:
                return {"success": True, "message": "カテゴリを削除しました"}
            return {"success": False, "message": "カテゴリが見つかりません"}
        except Exception as e:
            logger.error("カテゴリ削除エラー (id=%s): %s", category_id, e, exc_info=True)
            return {"success": False, "message": str(e)}

    # ── データ検索 ─────────────────────────────────

    _TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def get_allowed_table_names(self) -> List[Dict[str, Any]]:
        """DENPYO_CATEGORIES から有効なユーザーテーブル名を取得"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, CATEGORY_NAME, HEADER_TABLE_NAME, LINE_TABLE_NAME
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
                        })
                    return tables
        except Exception as e:
            logger.error("許可テーブル一覧取得エラー: %s", e, exc_info=True)
            return []

    def _is_safe_table_name(self, table_name: str) -> bool:
        return bool(table_name and self._TABLE_NAME_PATTERN.match(table_name))

    def get_table_browser_tables(self) -> List[Dict[str, Any]]:
        """テーブルブラウザ用の一覧情報を取得（行数・作成日時など）"""
        entries: List[Dict[str, Any]] = []
        for category in self.get_allowed_table_names():
            if category.get("header_table_name"):
                entries.append({
                    "table_name": category["header_table_name"].upper(),
                    "table_type": "header",
                    "category_id": category["category_id"],
                    "category_name": category["category_name"],
                })
            if category.get("line_table_name"):
                entries.append({
                    "table_name": category["line_table_name"].upper(),
                    "table_type": "line",
                    "category_id": category["category_id"],
                    "category_name": category["category_name"],
                })

        if not entries:
            return []

        safe_table_names = sorted({e["table_name"] for e in entries if self._is_safe_table_name(e["table_name"])})
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
                        table_name = row[0]
                        meta_map[table_name]["estimated_rows"] = int(row[1] or 0)
                        meta_map[table_name]["last_analyzed"] = str(row[2]) if row[2] else ""
                        meta_map[table_name]["created_at"] = str(row[3]) if row[3] else ""

                    cursor.execute(
                        f"""SELECT TABLE_NAME, COUNT(*)
                        FROM USER_TAB_COLUMNS
                        WHERE TABLE_NAME IN ({in_clause})
                        GROUP BY TABLE_NAME""",
                        bind_map
                    )
                    for row in cursor.fetchall():
                        table_name = row[0]
                        meta_map[table_name]["column_count"] = int(row[1] or 0)

                    for table_name in safe_table_names:
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
        for entry in entries:
            table_name = entry["table_name"]
            meta = meta_map.get(table_name, {})
            result.append({
                "table_name": table_name,
                "table_type": entry["table_type"],
                "category_id": entry["category_id"],
                "category_name": entry["category_name"],
                "row_count": meta.get("row_count", 0),
                "estimated_rows": meta.get("estimated_rows", 0),
                "column_count": meta.get("column_count", 0),
                "created_at": meta.get("created_at", ""),
                "last_analyzed": meta.get("last_analyzed", ""),
            })

        result.sort(key=lambda x: (x["category_name"], x["table_type"], x["table_name"]))
        return result

    def _get_allowed_table_set(self) -> set:
        """許可されたテーブル名のセットを取得（大文字）"""
        allowed = set()
        for entry in self.get_allowed_table_names():
            if entry["header_table_name"]:
                allowed.add(entry["header_table_name"].upper())
            if entry["line_table_name"]:
                allowed.add(entry["line_table_name"].upper())
        return allowed

    def get_table_columns(self, table_name: str) -> List[Dict[str, str]]:
        """テーブルのカラム情報を取得（許可テーブルのみ）"""
        if not table_name:
            return []

        # セキュリティ: 許可テーブルかチェック
        allowed = self._get_allowed_table_set()
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
                        })
                    return columns
        except Exception as e:
            logger.error("カラム情報取得エラー (%s): %s", table_name, e, exc_info=True)
            return []

    def _validate_select_only(self, sql: str) -> None:
        """SQL が SELECT 文のみかを検証（禁止キーワードチェック）"""
        import re
        normalized = sql.strip().upper()

        # SELECT で始まることを確認
        if not normalized.startswith("SELECT"):
            raise ValueError("SELECT 文のみ実行できます")

        # 禁止キーワードチェック
        forbidden = re.compile(
            r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|MERGE)\b',
            re.IGNORECASE
        )
        if forbidden.search(sql):
            raise ValueError("許可されていない SQL キーワードが含まれています")

    def _extract_table_names_from_sql(self, sql: str) -> set:
        """SQL からテーブル名を抽出（簡易パーサー）"""
        import re
        # FROM / JOIN の後のテーブル名を抽出
        pattern = re.compile(
            r'\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)',
            re.IGNORECASE
        )
        matches = pattern.findall(sql)
        return {m.upper() for m in matches}

    def _validate_tables_in_whitelist(self, sql: str, allowed: set) -> None:
        """SQL 内のテーブルが許可リストにあるか検証"""
        referenced = self._extract_table_names_from_sql(sql)
        unauthorized = referenced - allowed
        if unauthorized:
            raise ValueError(f"許可されていないテーブルが参照されています: {', '.join(unauthorized)}")

    def execute_select_query(self, sql: str, max_rows: int = 500) -> Dict[str, Any]:
        """SELECT 文のみ実行（安全なクエリ実行）"""
        try:
            # セキュリティ検証
            self._validate_select_only(sql)
            allowed = self._get_allowed_table_set()
            if not allowed:
                return {"success": False, "message": "検索可能なテーブルがありません", "columns": [], "rows": [], "total": 0}
            self._validate_tables_in_whitelist(sql, allowed)

            # 行数制限を追加
            limited_sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= :max_rows"

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(limited_sql, {"max_rows": max_rows})
                    columns = [desc[0] for desc in cursor.description]
                    rows_raw = cursor.fetchall()
                    rows = [dict(zip(columns, row)) for row in rows_raw]
                    return {
                        "success": True,
                        "columns": columns,
                        "rows": rows,
                        "total": len(rows),
                    }
        except ValueError as e:
            logger.warning("SQL 検証エラー: %s", e)
            return {"success": False, "message": str(e), "columns": [], "rows": [], "total": 0}
        except Exception as e:
            logger.error("クエリ実行エラー: %s", e, exc_info=True)
            return {"success": False, "message": f"クエリ実行エラー: {str(e)}", "columns": [], "rows": [], "total": 0}

    def get_table_data(self, table_name: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """テーブルデータをページング付きで取得"""
        if not table_name:
            return {"success": False, "message": "テーブル名が指定されていません",
                    "table_name": "", "columns": [], "rows": [], "total": 0}

        # セキュリティ: 許可テーブルかチェック
        allowed = self._get_allowed_table_set()
        if table_name.upper() not in allowed:
            logger.warning("許可されていないテーブルへのアクセス試行: %s", table_name)
            return {"success": False, "message": "許可されていないテーブルです",
                    "table_name": table_name, "columns": [], "rows": [], "total": 0}

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # 総件数取得
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name.upper()}")
                    total = cursor.fetchone()[0]

                    # データ取得（ページング）
                    cursor.execute(
                        f"""SELECT * FROM {table_name.upper()}
                        ORDER BY 1
                        OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY""",
                        {"offset": offset, "limit": limit}
                    )
                    columns = [desc[0] for desc in cursor.description]
                    rows_raw = cursor.fetchall()
                    rows = [dict(zip(columns, row)) for row in rows_raw]

                    return {
                        "success": True,
                        "table_name": table_name.upper(),
                        "columns": columns,
                        "rows": rows,
                        "total": total,
                        "limit": limit,
                        "offset": offset,
                    }
        except Exception as e:
            logger.error("テーブルデータ取得エラー (%s): %s", table_name, e, exc_info=True)
            return {"success": False, "message": f"データ取得エラー: {str(e)}",
                    "table_name": table_name, "columns": [], "rows": [], "total": 0}

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
        """ファイル一覧を取得"""
        kind = (upload_kind or "").strip().lower()
        raw_prefix = (os.environ.get("OCI_SLIPS_RAW_PREFIX", "denpyo-raw") or "denpyo-raw").strip("/")
        category_prefix = (os.environ.get("OCI_SLIPS_CATEGORY_PREFIX", "denpyo-category") or "denpyo-category").strip("/")
        path_prefix = None
        if kind == "raw":
            path_prefix = raw_prefix
        elif kind == "category":
            path_prefix = category_prefix

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    if status and path_prefix:
                        cursor.execute(
                            """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, CONTENT_TYPE, FILE_SIZE,
                                      STATUS, UPLOADED_BY, UPLOADED_AT
                            FROM DENPYO_FILES
                            WHERE STATUS = :1
                              AND OBJECT_STORAGE_PATH LIKE :2
                            ORDER BY UPLOADED_AT DESC
                            OFFSET :3 ROWS FETCH NEXT :4 ROWS ONLY""",
                            [status, f"{path_prefix}/%", offset, limit]
                        )
                    elif status:
                        cursor.execute(
                            """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, CONTENT_TYPE, FILE_SIZE,
                                      STATUS, UPLOADED_BY, UPLOADED_AT
                            FROM DENPYO_FILES WHERE STATUS = :1
                            ORDER BY UPLOADED_AT DESC
                            OFFSET :2 ROWS FETCH NEXT :3 ROWS ONLY""",
                            [status, offset, limit]
                        )
                    elif path_prefix:
                        cursor.execute(
                            """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, CONTENT_TYPE, FILE_SIZE,
                                      STATUS, UPLOADED_BY, UPLOADED_AT
                            FROM DENPYO_FILES
                            WHERE OBJECT_STORAGE_PATH LIKE :1
                            ORDER BY UPLOADED_AT DESC
                            OFFSET :2 ROWS FETCH NEXT :3 ROWS ONLY""",
                            [f"{path_prefix}/%", offset, limit]
                        )
                    else:
                        cursor.execute(
                            """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, CONTENT_TYPE, FILE_SIZE,
                                      STATUS, UPLOADED_BY, UPLOADED_AT
                            FROM DENPYO_FILES
                            ORDER BY UPLOADED_AT DESC
                            OFFSET :1 ROWS FETCH NEXT :2 ROWS ONLY""",
                            [offset, limit]
                        )

                    files = []
                    for row in cursor.fetchall():
                        files.append({
                            "id": row[0],
                            "file_name": row[1],
                            "original_file_name": row[2],
                            "content_type": row[3],
                            "file_size": row[4],
                            "status": row[5],
                            "uploaded_by": row[6],
                            "uploaded_at": str(row[7]) if row[7] else "",
                        })
                    return files
        except Exception as e:
            logger.error("ファイル一覧取得エラー: %s", e, exc_info=True)
            return []

    def get_files_count(self, status: str = None, upload_kind: Optional[str] = None) -> int:
        """ファイル総件数を取得"""
        kind = (upload_kind or "").strip().lower()
        raw_prefix = (os.environ.get("OCI_SLIPS_RAW_PREFIX", "denpyo-raw") or "denpyo-raw").strip("/")
        category_prefix = (os.environ.get("OCI_SLIPS_CATEGORY_PREFIX", "denpyo-category") or "denpyo-category").strip("/")
        path_prefix = None
        if kind == "raw":
            path_prefix = raw_prefix
        elif kind == "category":
            path_prefix = category_prefix

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    if status and path_prefix:
                        cursor.execute(
                            "SELECT COUNT(*) FROM DENPYO_FILES WHERE STATUS = :1 AND OBJECT_STORAGE_PATH LIKE :2",
                            [status, f"{path_prefix}/%"]
                        )
                    elif status:
                        cursor.execute(
                            "SELECT COUNT(*) FROM DENPYO_FILES WHERE STATUS = :1",
                            [status]
                        )
                    elif path_prefix:
                        cursor.execute(
                            "SELECT COUNT(*) FROM DENPYO_FILES WHERE OBJECT_STORAGE_PATH LIKE :1",
                            [f"{path_prefix}/%"]
                        )
                    else:
                        cursor.execute("SELECT COUNT(*) FROM DENPYO_FILES")
                    return cursor.fetchone()[0]
        except Exception as e:
            logger.error("ファイル件数取得エラー: %s", e, exc_info=True)
            return 0

    def get_file_by_id(self, file_id: int) -> Optional[Dict[str, Any]]:
        """IDでファイルレコードを取得"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT ID, FILE_NAME, ORIGINAL_FILE_NAME, OBJECT_STORAGE_PATH,
                                  CONTENT_TYPE, FILE_SIZE, STATUS, UPLOADED_BY, UPLOADED_AT
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
                        "uploaded_by": row[7],
                        "uploaded_at": str(row[8]) if row[8] else "",
                    }
        except Exception as e:
            logger.error("ファイル取得エラー (id=%s): %s", file_id, e, exc_info=True)
            return None

    def delete_file_record(self, file_id: int) -> Dict[str, Any]:
        """ファイルレコードを削除（登録済みの場合は拒否）"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # 登録済みチェック
                    cursor.execute(
                        "SELECT COUNT(*) FROM DENPYO_REGISTRATIONS WHERE FILE_ID = :1",
                        [file_id]
                    )
                    if cursor.fetchone()[0] > 0:
                        return {"success": False, "message": "登録済みファイルは削除できません"}

                    # アクティビティログも削除
                    cursor.execute(
                        "DELETE FROM DENPYO_ACTIVITY_LOG WHERE FILE_ID = :1",
                        [file_id]
                    )
                    cursor.execute(
                        "DELETE FROM DENPYO_FILES WHERE ID = :1",
                        [file_id]
                    )
                    deleted = cursor.rowcount
                conn.commit()

            if deleted > 0:
                return {"success": True, "message": "ファイルを削除しました"}
            return {"success": False, "message": "ファイルが見つかりません"}
        except Exception as e:
            logger.error("ファイル削除エラー (id=%s): %s", file_id, e, exc_info=True)
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

    def close_pool(self) -> None:
        """接続プールを閉じる"""
        if self._pool is not None:
            try:
                self._pool.close()
                logger.info("データベース接続プールを閉じました")
            except Exception as e:
                logger.error("接続プール閉鎖エラー: %s", e)
            finally:
                self._pool = None
