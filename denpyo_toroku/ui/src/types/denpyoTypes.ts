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
export type FileStatusDetail = 'ANALYSIS_TIMEOUT' | '';

export interface DenpyoFile {
  file_id: string;
  file_name: string;
  original_file_name?: string;
  file_type: string;
  content_type?: string;
  file_size: number;
  storage_path?: string;
  uploaded_at: string;
  updated_at?: string;
  uploaded_by?: string;
  status: FileStatus;
  status_detail?: FileStatusDetail;
  is_analysis_stalled?: boolean;
  can_retry_analysis?: boolean;
  has_analysis_result?: boolean;
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
  select_ai_profile_name?: string;
  select_ai_team_name?: string;
  select_ai_profile_ready?: boolean;
  select_ai_last_synced_at?: string;
  select_ai_config_hash?: string;
  select_ai_last_error?: string;
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

export interface TableColumnInfo {
  column_name: string;
  data_type: string;
  data_length?: number;
  precision?: number;
  scale?: number;
  nullable?: string;
  comment?: string;
}

export interface CategoryTableSchema {
  header_table_name: string;
  line_table_name?: string;
  header_columns: TableColumnInfo[];
  line_columns: TableColumnInfo[];
}

export interface PageOcrText {
  page_index: number;
  text: string;
}

export interface AnalysisResult {
  file_id: string;
  file_name: string;
  status: FileStatus;
  category_id?: number;
  classification: InvoiceClassification;
  extraction: FieldExtraction;
  ddl_suggestion: DDLSuggestion;
  table_schema?: CategoryTableSchema;
  page_texts?: PageOcrText[];
}

export interface AnalysisQueuedResponse {
  file_id?: string;
  file_ids?: number[];
  status: FileStatus;
  queued: boolean;
  message?: string;
}

export interface StoredAnalysisResultResponse<T> {
  analysis_kind: 'raw' | 'category' | string;
  result: T;
  analyzed_at?: string;
}

export interface DocumentPreviewPage {
  page_index: number;
  page_label: string;
  source_name: string;
  content_type: string;
}

export interface DocumentPreviewResponse {
  file_id: string;
  file_name: string;
  page_count: number;
  pages: DocumentPreviewPage[];
}

// --- 登録 ---

export interface RegistrationRequest {
  category_id?: number;
  category_name: string;
  category_name_en: string;
  header_table_name: string;
  line_table_name: string;
  header_ddl?: string;
  line_ddl?: string;
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

// --- 伝票分類作成フロー (SCR-005 新機能) ---

// SLIPS_CATEGORY files use the existing DenpyoFile shape returned by /api/v1/files
// (file_id: string, file_name: string as OBJECT_NAME, original_file_name: FILE_NAME, etc.)
// Re-exported as alias for clarity in the creation flow.
export type SlipsCategoryFile = DenpyoFile;

export interface TableColumnDef {
  column_name: string;        // English name (Oracle column name), e.g. INVOICE_DATE
  column_name_jp: string;     // Japanese label
  sample_data?: string;       // sample value for review only
  data_type: 'VARCHAR2' | 'NUMBER' | 'DATE' | 'TIMESTAMP';
  max_length?: number;        // for VARCHAR2
  precision?: number;         // for NUMBER
  scale?: number;             // for NUMBER
  is_nullable: boolean;
  is_primary_key: boolean;
}

export interface CategoryAnalysisAttempt {
  attempt_number?: number;
  category_guess: string;
  category_guess_en: string;
  analysis_mode: 'header_only' | 'header_line';
  header_columns: TableColumnDef[];
  line_columns: TableColumnDef[];
  analyzed_file_ids?: number[];
  file_page_texts?: Record<string, PageOcrText[]>;
}

export interface CategoryAnalysisResult extends CategoryAnalysisAttempt {
  analysis_attempts?: CategoryAnalysisAttempt[];
}

export interface CategoryCreateRequest {
  category_name: string;
  category_name_en: string;
  description: string;
  header_table_name: string;
  header_columns: TableColumnDef[];
  line_table_name?: string;
  line_columns?: TableColumnDef[];
}

export interface CategoryCreateResponse {
  success: boolean;
  category_id: number;
  category_name: string;
  header_table_name: string;
  line_table_name?: string;
  header_table_created: boolean;
  line_table_created: boolean;
  message: string;
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
  select_ai_profile_name?: string;
  select_ai_team_name?: string;
  select_ai_profile_ready?: boolean;
  select_ai_last_synced_at?: string;
  select_ai_last_error?: string;
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

export interface CategorySchemaColumn {
  column_name: string;
  logical_name: string;
  data_type: string;
  nullable: string;
}

export interface CategorySchemaTable {
  table_name: string;
  logical_name: string;
  columns: CategorySchemaColumn[];
}

export interface CategorySchema {
  category_id: number;
  category_name: string;
  header: CategorySchemaTable;
  line: CategorySchemaTable | null;
}

export interface NLSearchRequest {
  query: string;
  category_id: number;
}

export interface NLSearchEngineMeta {
  profile_name?: string;
  team_name?: string;
  api_format?: string;
  use_comments?: boolean;
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
  engine?: 'select_ai_agent' | 'direct_llm';
  engine_meta?: NLSearchEngineMeta;
}

export type NLSearchJobStatus = 'pending' | 'running' | 'done' | 'error';

export interface NLSearchAsyncStartResponse {
  job_id: string;
  status: NLSearchJobStatus;
}

export interface NLSearchJobResponse {
  job_id: string;
  status: NLSearchJobStatus;
  created_at?: number;
  result?: NLSearchResponse;
  error_message?: string;
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

export interface DeleteTableBrowserRowResponse {
  success: boolean;
  deleted: number;
  detail_deleted?: number;
  table_type?: 'header' | 'line' | '';
}

// --- Redux State ---

export interface FileListState {
  files: DenpyoFile[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
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

  // 伝票分類管理
  categories: DenpyoCategory[];
  isCategoriesLoading: boolean;

  // 伝票分類作成フロー (SCR-005 新機能)
  slipsCategoryFiles: DenpyoFile[];
  slipsCategoryTotal: number;
  slipsCategoryPage: number;
  slipsCategoryPageSize: number;
  slipsCategoryTotalPages: number;
  isSlipsCategoryLoading: boolean;
  categoryAnalysisResult: CategoryAnalysisResult | null;
  isCategoryAnalyzing: boolean;
  isCategoryCreating: boolean;
  categoryCreateResult: CategoryCreateResponse | null;

  // データ検索 (SCR-006)
  searchableTables: SearchableTable[];
  isSearchableTablesLoading: boolean;
  tableBrowserTables: TableBrowserTable[];
  isTableBrowserTablesLoading: boolean;
  nlSearchResult: NLSearchResponse | null;
  activeNLSearchRequestId?: string | null;
  isNLSearching: boolean;
  nlSearchAsyncJobId: string | null;
  nlSearchAsyncJobStatus: NLSearchJobStatus | null;
  nlSearchAsyncJobStartedAt: number | null;
  tableBrowseResult: TableBrowseResult | null;
  isTableBrowsing: boolean;
  searchError: string | null;
  // 検索画面UI状態 (ページ遷移後も保持)
  searchActiveTab: 'nlSearch' | 'tableBrowser';
  nlSearchQuery: string;
  nlSearchCategoryId: number | undefined;
  nlCategorySchema: CategorySchema | null;
  isNlCategorySchemaLoading: boolean;

  // 共通
  error: string | null;
}
