/**
 * 伝票登録システム - 型定義
 */

// --- ヘルスチェック（既存流用） ---

export interface HealthData {
  status: string;
  version: string;
  uptime_seconds: number;
  timestamp?: string;
  message?: string;
}

export interface ApiResponse<T> {
  data?: T;
  errorMessages?: string[];
  warningMessages?: string[];
}

// --- ダッシュボード ---

export interface DashboardStats {
  upload_stats: {
    total_files: number;
    this_month: number;
  };
  registration_stats: {
    total_registrations: number;
    this_month: number;
  };
  category_stats: {
    total_categories: number;
    active_categories: number;
  };
  recent_activities: RecentActivity[];
}

export interface RecentActivity {
  id: string;
  type: 'UPLOAD' | 'REGISTRATION';
  file_name: string;
  timestamp: string;
  status: 'SUCCESS' | 'ERROR';
  category_name?: string;
}

// --- 伝票ファイル ---

export type FileStatus = 'UPLOADED' | 'ANALYZING' | 'ANALYZED' | 'REGISTERED' | 'ERROR';

export interface DenpyoFile {
  file_id: string;
  file_name: string;
  file_type: string;
  file_size: number;
  storage_path?: string;
  uploaded_at: string;
  uploaded_by?: string;
  status: FileStatus;
  category_id?: string;
  category_name?: string;
  registered_at?: string;
}

export interface FileListResponse {
  files: DenpyoFile[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface FileUploadResponse {
  success: boolean;
  uploaded_files: DenpyoFile[];
  errors: string[];
}

// --- 分類 ---

export interface DenpyoCategory {
  id: number;
  category_name: string;
  category_name_en: string;
  header_table_name: string;
  line_table_name: string;
  description: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  registration_count: number;
}

export interface CategoryUpdateRequest {
  category_name: string;
  category_name_en: string;
  description: string;
}

// --- AI 分析 ---

export interface AIFieldAnalysis {
  field_name: string;
  data_type: string;
  max_length?: number;
  precision?: number;
  scale?: number;
  sample_values: string[];
  frequency: number;
  is_required: boolean;
  is_primary_key: boolean;
  is_header: boolean;
}

export interface AIAnalysisResult {
  file_id: string;
  fields: AIFieldAnalysis[];
}

export interface InvoiceClassification {
  category: string;
  confidence: number;
  description: string;
  has_line_items: boolean;
}

export interface ExtractedField {
  field_name: string;
  field_name_en: string;
  value: string;
  data_type: string;
  max_length?: number;
}

export interface FieldExtraction {
  header_fields: ExtractedField[];
  line_fields: ExtractedField[];
  line_count: number;
  raw_lines: Record<string, any>[];
}

export interface DDLSuggestion {
  table_prefix: string;
  header_table_name: string;
  line_table_name: string;
  header_ddl: string;
  line_ddl: string;
}

export interface AnalysisResult {
  file_id: string;
  file_name: string;
  status: FileStatus;
  classification: InvoiceClassification;
  extraction: FieldExtraction;
  ddl_suggestion: DDLSuggestion;
}

// --- 登録 ---

export interface RegistrationRequest {
  category_name: string;
  category_name_en: string;
  header_table_name: string;
  line_table_name: string;
  header_ddl: string;
  line_ddl: string;
  ai_confidence: number;
  line_count: number;
  // データINSERT用
  header_fields?: ExtractedField[];
  raw_lines?: Record<string, any>[];
}

export interface RegistrationResponse {
  success: boolean;
  registration_id: number;
  category_id: number;
  header_table_created: boolean;
  line_table_created: boolean;
  header_inserted?: number;
  line_inserted?: number;
  message: string;
}

export interface ExtractedFieldValue {
  value: any;
  confidence: number;
  data_type: string;
}

export interface ExtractedInvoiceData {
  file_id: string;
  file_name: string;
  header_fields: Record<string, ExtractedFieldValue>;
  line_items?: Array<Record<string, ExtractedFieldValue>>;
}

export interface RegistrationResult {
  file_id: string;
  success: boolean;
  message: string;
  inserted_rows?: number;
}

// --- 検索 ---

export interface NLSearchResult {
  generated_sql: string;
  results: {
    rows: Record<string, any>[];
    columns: string[];
    total: number;
  };
}

// --- データ検索 (SCR-006) ---

export interface SearchableTable {
  category_id: number;
  category_name: string;
  header_table_name: string;
  line_table_name: string;
}

export interface TableBrowserTable {
  table_name: string;
  table_type: 'header' | 'line';
  category_id: number;
  category_name: string;
  row_count: number;
  estimated_rows: number;
  column_count: number;
  created_at: string;
  last_analyzed: string;
}

export interface NLSearchRequest {
  query: string;
  category_id?: number;
}

export interface NLSearchResponse {
  generated_sql: string;
  explanation: string;
  results: {
    columns: string[];
    rows: Record<string, any>[];
    total: number;
  };
  error?: string;
}

export interface TableBrowseResult {
  table_name: string;
  table_type: 'header' | 'line';
  columns: string[];
  rows: Record<string, any>[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// --- Redux State ---

export interface FileListState {
  files: DenpyoFile[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  statusFilter: FileStatus | null;
}

export interface DenpyoSliceState {
  // ダッシュボード
  dashboardStats: DashboardStats | null;
  isDashboardLoading: boolean;

  // ヘルス
  health: HealthData | null;
  isHealthLoading: boolean;

  // ファイルアップロード
  isUploading: boolean;
  uploadResult: FileUploadResponse | null;

  // ファイル一覧
  fileList: FileListState;
  isFileListLoading: boolean;
  isDeleting: boolean;

  // AI分析
  analysisResult: AnalysisResult | null;
  isAnalyzing: boolean;
  analyzingFileId: string | null;

  // DB登録
  isRegistering: boolean;
  registrationResult: RegistrationResponse | null;

  // カテゴリ管理
  categories: DenpyoCategory[];
  isCategoriesLoading: boolean;

  // データ検索 (SCR-006)
  searchableTables: SearchableTable[];
  isSearchableTablesLoading: boolean;
  tableBrowserTables: TableBrowserTable[];
  isTableBrowserTablesLoading: boolean;
  nlSearchResult: NLSearchResponse | null;
  isNLSearching: boolean;
  tableBrowseResult: TableBrowseResult | null;
  isTableBrowsing: boolean;
  searchError: string | null;

  // 共通
  error: string | null;
}
