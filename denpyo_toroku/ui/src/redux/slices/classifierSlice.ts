/**
 * 分類器の state slice（ヘルス/統計/モデル情報/学習/予測）
 */
import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import {
  ClassifierSliceState,
  HealthData,
  StatsData,
  ModelInfo,
  PredictionResult,
  BatchPredictionResponse,
  TrainingState,
  ValidationResult,
  TrainingProfile
} from '../../types/classifierTypes';
import { apiGet, apiPost } from '../../utils/apiUtils';

const initialTrainingState: TrainingState = {
  status: 'idle',
  progress: '',
  results: null,
  error: null,
  started_at: null,
  finished_at: null
};

const initialState: ClassifierSliceState = {
  health: null,
  stats: null,
  modelInfo: null,
  trainingState: initialTrainingState,
  isHealthLoading: false,
  isStatsLoading: false,
  isModelInfoLoading: false,
  error: null
};

// 非同期 thunk
export const fetchHealth = createAsyncThunk(
  'classifier/fetchHealth',
  async () => {
    return await apiGet<HealthData>('/api/v1/health');
  }
);

export const fetchStats = createAsyncThunk(
  'classifier/fetchStats',
  async () => {
    return await apiGet<StatsData>('/api/v1/stats');
  }
);

export const fetchModelInfo = createAsyncThunk(
  'classifier/fetchModelInfo',
  async () => {
    return await apiGet<ModelInfo>('/api/v1/model/info');
  }
);

export const predictSingle = createAsyncThunk(
  'classifier/predictSingle',
  async (params: {
    text: string;
    return_proba?: boolean;
    confidence_threshold?: number;
    top_k?: number;
    unknown_on_low_conf?: boolean;
    unknown_intent_label?: string;
  }) => {
    return await apiPost<PredictionResult>('/api/v1/predict/single', params);
  }
);

export const predictBatch = createAsyncThunk(
  'classifier/predictBatch',
  async (params: {
    texts: string[];
    return_proba?: boolean;
    confidence_threshold?: number;
    top_k?: number;
    unknown_on_low_conf?: boolean;
    unknown_intent_label?: string;
  }) => {
    return await apiPost<BatchPredictionResponse>('/api/v1/predict', params);
  }
);

export const startTraining = createAsyncThunk(
  'classifier/startTraining',
  async (params: {
    training_data?: Array<{ text: string; label: string }>;
    params?: Record<string, string | number | boolean>;
  }) => {
    const body: Record<string, any> = {};
    if (params.training_data && params.training_data.length > 0) {
      body.training_data = params.training_data;
    }
    if (params.params) {
      body.params = params.params;
    }
    return await apiPost<{
      message: string;
      status: string;
      profile?: TrainingProfile;
      params?: Record<string, string | number | boolean>;
    }>('/api/v1/train', body);
  }
);

export const fetchTrainingStatus = createAsyncThunk(
  'classifier/fetchTrainingStatus',
  async () => {
    return await apiGet<TrainingState>('/api/v1/train/status');
  }
);

export const validateTrainingData = createAsyncThunk(
  'classifier/validateTrainingData',
  async (params: { training_data: Array<{ text: string; label: string }> }) => {
    return await apiPost<ValidationResult>('/api/v1/train/validate', params);
  }
);

export const reloadModel = createAsyncThunk(
  'classifier/reloadModel',
  async () => {
    return await apiPost<{ message: string }>('/api/v1/model/reload');
  }
);

export const clearCache = createAsyncThunk(
  'classifier/clearCache',
  async () => {
    return await apiPost<{ message: string }>('/api/v1/cache/clear');
  }
);

const classifierSlice = createSlice({
  name: 'classifier',
  initialState,
  reducers: {
    clearError(state) {
      state.error = null;
    },
    resetTrainingState(state) {
      state.trainingState = initialTrainingState;
    },
    updateTrainingState(state, action: PayloadAction<Partial<TrainingState>>) {
      state.trainingState = { ...state.trainingState, ...action.payload };
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

    // Stats
    builder
      .addCase(fetchStats.pending, (state) => {
        state.isStatsLoading = true;
      })
      .addCase(fetchStats.fulfilled, (state, action) => {
        state.isStatsLoading = false;
        state.stats = action.payload;
      })
      .addCase(fetchStats.rejected, (state, action) => {
        state.isStatsLoading = false;
        state.error = action.error.message || '統計の取得に失敗しました';
      });

    // Model Info
    builder
      .addCase(fetchModelInfo.pending, (state) => {
        state.isModelInfoLoading = true;
      })
      .addCase(fetchModelInfo.fulfilled, (state, action) => {
        state.isModelInfoLoading = false;
        state.modelInfo = action.payload;
      })
      .addCase(fetchModelInfo.rejected, (state, action) => {
        state.isModelInfoLoading = false;
        state.error = action.error.message || 'モデル情報の取得に失敗しました';
      });

    // Training
    builder
      .addCase(startTraining.fulfilled, (state, action) => {
        state.trainingState.status = 'running';
        state.trainingState.progress = '学習を開始しました…';
        state.trainingState.error = null;
        if (action.payload.profile) {
          state.trainingState.dataset_profile = action.payload.profile;
        }
        if (action.payload.params) {
          state.trainingState.params = action.payload.params;
        }
      })
      .addCase(startTraining.rejected, (state, action) => {
        state.trainingState.status = 'failed';
        state.trainingState.error = action.error.message || '学習の開始に失敗しました';
      });

    builder
      .addCase(fetchTrainingStatus.fulfilled, (state, action) => {
        state.trainingState = action.payload;
      });

    // Model reload
    builder
      .addCase(reloadModel.fulfilled, (state) => {
        state.error = null;
      })
      .addCase(reloadModel.rejected, (state, action) => {
        state.error = action.error.message || 'モデルの再読み込みに失敗しました';
      });
  }
});

export const { clearError, resetTrainingState, updateTrainingState } = classifierSlice.actions;

export default classifierSlice.reducer;
