/**
 * 伝票登録システム - Redux state slice
 * Phase 1: ダッシュボード統計 + ヘルス
 * Phase 2: ファイルアップロード + 一覧
 * Phase 3: AI分析
 * Phase 4: DB登録
 * Phase 5: カテゴリ管理
 */
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import {
  DenpyoSliceState,
  HealthData,
  DashboardStats,
  FileListResponse,
  FileUploadResponse,
  FileStatus,
  AnalysisResult,
  RegistrationRequest,
  RegistrationResponse,
  DenpyoCategory,
  CategoryUpdateRequest,
  SearchableTable,
  NLSearchRequest,
  NLSearchResponse,
  TableBrowseResult
} from '../../types/denpyoTypes';
import { apiGet, apiPost, apiPostWithTimeout, apiUpload, apiDelete, apiPut, apiPatch } from '../../utils/apiUtils';

const initialState: DenpyoSliceState = {
  dashboardStats: null,
  isDashboardLoading: false,
  health: null,
  isHealthLoading: false,
  isUploading: false,
  uploadResult: null,
  fileList: {
    files: [],
    total: 0,
    page: 1,
    pageSize: 20,
    totalPages: 0,
    statusFilter: null
  },
  isFileListLoading: false,
  isDeleting: false,
  analysisResult: null,
  isAnalyzing: false,
  analyzingFileId: null,
  isRegistering: false,
  registrationResult: null,
  categories: [],
  isCategoriesLoading: false,
  // データ検索 (SCR-006)
  searchableTables: [],
  isSearchableTablesLoading: false,
  nlSearchResult: null,
  isNLSearching: false,
  tableBrowseResult: null,
  isTableBrowsing: false,
  searchError: null,
  error: null
};

export const fetchHealth = createAsyncThunk(
  'denpyo/fetchHealth',
  async () => {
    return await apiGet<HealthData>('/api/v1/health');
  }
);

export const fetchDashboardStats = createAsyncThunk(
  'denpyo/fetchDashboardStats',
  async () => {
    return await apiGet<DashboardStats>('/api/v1/dashboard/stats');
  }
);

export const uploadFiles = createAsyncThunk(
  'denpyo/uploadFiles',
  async (files: File[]) => {
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    return await apiUpload<FileUploadResponse>('/api/v1/files/upload', formData);
  }
);

export const fetchFileList = createAsyncThunk(
  'denpyo/fetchFileList',
  async (params: { page?: number; pageSize?: number; status?: FileStatus | null }) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.pageSize) qs.set('page_size', String(params.pageSize));
    if (params.status) qs.set('status', params.status);
    const query = qs.toString();
    return await apiGet<FileListResponse>(`/api/v1/files${query ? '?' + query : ''}`);
  }
);

export const deleteFile = createAsyncThunk(
  'denpyo/deleteFile',
  async (fileId: string) => {
    await apiDelete<{ success: boolean }>(`/api/v1/files/${fileId}`);
    return fileId;
  }
);

export const analyzeFile = createAsyncThunk(
  'denpyo/analyzeFile',
  async (fileId: string) => {
    return await apiPost<AnalysisResult>(`/api/v1/files/${fileId}/analyze`);
  }
);

export const registerFile = createAsyncThunk(
  'denpyo/registerFile',
  async ({ fileId, data }: { fileId: string; data: RegistrationRequest }) => {
    const result = await apiPost<RegistrationResponse>(`/api/v1/files/${fileId}/register`, data);
    return { ...result, file_id: fileId };
  }
);

// --- カテゴリ管理 ---

export const fetchCategories = createAsyncThunk(
  'denpyo/fetchCategories',
  async () => {
    const res = await apiGet<{ categories: DenpyoCategory[] }>('/api/v1/categories');
    return res.categories;
  }
);

export const updateCategory = createAsyncThunk(
  'denpyo/updateCategory',
  async ({ categoryId, data }: { categoryId: number; data: CategoryUpdateRequest }) => {
    return await apiPut<DenpyoCategory>(`/api/v1/categories/${categoryId}`, data);
  }
);

export const toggleCategoryActive = createAsyncThunk(
  'denpyo/toggleCategoryActive',
  async (categoryId: number) => {
    return await apiPatch<{ id: number; is_active: boolean }>(`/api/v1/categories/${categoryId}/toggle`);
  }
);

export const deleteCategory = createAsyncThunk(
  'denpyo/deleteCategory',
  async (categoryId: number) => {
    await apiDelete<{ success: boolean }>(`/api/v1/categories/${categoryId}`);
    return categoryId;
  }
);

// --- データ検索 (SCR-006) ---

export const fetchSearchableTables = createAsyncThunk(
  'denpyo/fetchSearchableTables',
  async () => {
    const res = await apiGet<{ tables: SearchableTable[] }>('/api/v1/search/tables');
    return res.tables;
  }
);

export const nlSearch = createAsyncThunk(
  'denpyo/nlSearch',
  async (params: NLSearchRequest) => {
    // GenAI 呼び出しのため 60 秒タイムアウト
    return await apiPostWithTimeout<NLSearchResponse>('/api/v1/search/nl', params, 60000);
  }
);

export const fetchTableData = createAsyncThunk(
  'denpyo/fetchTableData',
  async (params: { categoryId: number; page?: number; pageSize?: number; tableType?: 'header' | 'line' }) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.pageSize) qs.set('page_size', String(params.pageSize));
    if (params.tableType) qs.set('table_type', params.tableType);
    const query = qs.toString();
    return await apiGet<TableBrowseResult>(`/api/v1/search/tables/${params.categoryId}/data${query ? '?' + query : ''}`);
  }
);

const denpyoSlice = createSlice({
  name: 'denpyo',
  initialState,
  reducers: {
    clearError(state) {
      state.error = null;
    },
    clearUploadResult(state) {
      state.uploadResult = null;
    },
    clearAnalysisResult(state) {
      state.analysisResult = null;
      state.analyzingFileId = null;
    },
    clearRegistrationResult(state) {
      state.registrationResult = null;
    },
    setFileListPage(state, action) {
      state.fileList.page = action.payload;
    },
    setFileListStatusFilter(state, action) {
      state.fileList.statusFilter = action.payload;
      state.fileList.page = 1;
    },
    clearSearchResults(state) {
      state.nlSearchResult = null;
      state.tableBrowseResult = null;
      state.searchError = null;
    },
    clearSearchError(state) {
      state.searchError = null;
    }
  },
  extraReducers: (builder) => {
    // Health
    builder
      .addCase(fetchHealth.pending, (state) => {
        state.isHealthLoading = true;
      })
      .addCase(fetchHealth.fulfilled, (state, action) => {
        state.isHealthLoading = false;
        state.health = action.payload;
        state.error = null;
      })
      .addCase(fetchHealth.rejected, (state, action) => {
        state.isHealthLoading = false;
        state.error = action.error.message || 'ヘルス情報の取得に失敗しました';
      });

    // Dashboard Stats
    builder
      .addCase(fetchDashboardStats.pending, (state) => {
        state.isDashboardLoading = true;
      })
      .addCase(fetchDashboardStats.fulfilled, (state, action) => {
        state.isDashboardLoading = false;
        state.dashboardStats = action.payload;
      })
      .addCase(fetchDashboardStats.rejected, (state, action) => {
        state.isDashboardLoading = false;
        state.error = action.error.message || 'ダッシュボード情報の取得に失敗しました';
      });

    // Upload Files
    builder
      .addCase(uploadFiles.pending, (state) => {
        state.isUploading = true;
        state.uploadResult = null;
      })
      .addCase(uploadFiles.fulfilled, (state, action) => {
        state.isUploading = false;
        state.uploadResult = action.payload;
      })
      .addCase(uploadFiles.rejected, (state, action) => {
        state.isUploading = false;
        state.error = action.error.message || 'アップロードに失敗しました';
      });

    // File List
    builder
      .addCase(fetchFileList.pending, (state) => {
        state.isFileListLoading = true;
      })
      .addCase(fetchFileList.fulfilled, (state, action) => {
        state.isFileListLoading = false;
        state.fileList.files = action.payload.files;
        state.fileList.total = action.payload.total;
        state.fileList.page = action.payload.page;
        state.fileList.pageSize = action.payload.page_size;
        state.fileList.totalPages = action.payload.total_pages;
      })
      .addCase(fetchFileList.rejected, (state, action) => {
        state.isFileListLoading = false;
        state.error = action.error.message || 'ファイル一覧の取得に失敗しました';
      });

    // Delete File
    builder
      .addCase(deleteFile.pending, (state) => {
        state.isDeleting = true;
      })
      .addCase(deleteFile.fulfilled, (state, action) => {
        state.isDeleting = false;
        state.fileList.files = state.fileList.files.filter(
          f => String(f.file_id) !== String(action.payload)
        );
        state.fileList.total = Math.max(0, state.fileList.total - 1);
      })
      .addCase(deleteFile.rejected, (state, action) => {
        state.isDeleting = false;
        state.error = action.error.message || 'ファイルの削除に失敗しました';
      });

    // Analyze File
    builder
      .addCase(analyzeFile.pending, (state, action) => {
        state.isAnalyzing = true;
        state.analyzingFileId = action.meta.arg;
        state.analysisResult = null;
        // fileList内のステータスをANALYZINGに更新
        const file = state.fileList.files.find(
          f => String(f.file_id) === String(action.meta.arg)
        );
        if (file) file.status = 'ANALYZING';
      })
      .addCase(analyzeFile.fulfilled, (state, action) => {
        state.isAnalyzing = false;
        state.analysisResult = action.payload;
        state.analyzingFileId = null;
        // fileList内のステータスをANALYZEDに更新
        const file = state.fileList.files.find(
          f => String(f.file_id) === String(action.payload.file_id)
        );
        if (file) file.status = 'ANALYZED';
      })
      .addCase(analyzeFile.rejected, (state, action) => {
        state.isAnalyzing = false;
        state.error = action.error.message || 'AI分析に失敗しました';
        // fileList内のステータスをERRORに更新
        if (state.analyzingFileId) {
          const file = state.fileList.files.find(
            f => String(f.file_id) === String(state.analyzingFileId)
          );
          if (file) file.status = 'ERROR';
        }
        state.analyzingFileId = null;
      });

    // Register File
    builder
      .addCase(registerFile.pending, (state) => {
        state.isRegistering = true;
        state.registrationResult = null;
      })
      .addCase(registerFile.fulfilled, (state, action) => {
        state.isRegistering = false;
        state.registrationResult = action.payload;
        // fileList内のステータスをREGISTEREDに更新
        const file = state.fileList.files.find(
          f => String(f.file_id) === String(action.payload.file_id)
        );
        if (file) file.status = 'REGISTERED';
      })
      .addCase(registerFile.rejected, (state, action) => {
        state.isRegistering = false;
        state.error = action.error.message || 'DB登録に失敗しました';
      });

    // Categories
    builder
      .addCase(fetchCategories.pending, (state) => {
        state.isCategoriesLoading = true;
      })
      .addCase(fetchCategories.fulfilled, (state, action) => {
        state.isCategoriesLoading = false;
        state.categories = action.payload;
      })
      .addCase(fetchCategories.rejected, (state, action) => {
        state.isCategoriesLoading = false;
        state.error = action.error.message || 'カテゴリ一覧の取得に失敗しました';
      });

    builder
      .addCase(updateCategory.fulfilled, (state, action) => {
        const idx = state.categories.findIndex(c => c.id === action.payload.id);
        if (idx !== -1) {
          state.categories[idx] = { ...state.categories[idx], ...action.payload };
        }
      })
      .addCase(updateCategory.rejected, (state, action) => {
        state.error = action.error.message || 'カテゴリの更新に失敗しました';
      });

    builder
      .addCase(toggleCategoryActive.fulfilled, (state, action) => {
        const cat = state.categories.find(c => c.id === action.payload.id);
        if (cat) cat.is_active = action.payload.is_active;
      })
      .addCase(toggleCategoryActive.rejected, (state, action) => {
        state.error = action.error.message || '有効/無効の切り替えに失敗しました';
      });

    builder
      .addCase(deleteCategory.fulfilled, (state, action) => {
        state.categories = state.categories.filter(c => c.id !== action.payload);
      })
      .addCase(deleteCategory.rejected, (state, action) => {
        state.error = action.error.message || 'カテゴリの削除に失敗しました';
      });

    // Data Search (SCR-006)
    builder
      .addCase(fetchSearchableTables.pending, (state) => {
        state.isSearchableTablesLoading = true;
      })
      .addCase(fetchSearchableTables.fulfilled, (state, action) => {
        state.isSearchableTablesLoading = false;
        state.searchableTables = action.payload;
      })
      .addCase(fetchSearchableTables.rejected, (state, action) => {
        state.isSearchableTablesLoading = false;
        state.searchError = action.error.message || '検索可能テーブルの取得に失敗しました';
      });

    builder
      .addCase(nlSearch.pending, (state) => {
        state.isNLSearching = true;
        state.nlSearchResult = null;
        state.searchError = null;
      })
      .addCase(nlSearch.fulfilled, (state, action) => {
        state.isNLSearching = false;
        state.nlSearchResult = action.payload;
        if (action.payload.error) {
          state.searchError = action.payload.error;
        }
      })
      .addCase(nlSearch.rejected, (state, action) => {
        state.isNLSearching = false;
        state.searchError = action.error.message || '自然言語検索に失敗しました';
      });

    builder
      .addCase(fetchTableData.pending, (state) => {
        state.isTableBrowsing = true;
        state.searchError = null;
      })
      .addCase(fetchTableData.fulfilled, (state, action) => {
        state.isTableBrowsing = false;
        state.tableBrowseResult = action.payload;
      })
      .addCase(fetchTableData.rejected, (state, action) => {
        state.isTableBrowsing = false;
        state.searchError = action.error.message || 'テーブルデータの取得に失敗しました';
      });
  }
});

export const { clearError, clearUploadResult, clearAnalysisResult, clearRegistrationResult, setFileListPage, setFileListStatusFilter, clearSearchResults, clearSearchError } = denpyoSlice.actions;

export default denpyoSlice.reducer;
