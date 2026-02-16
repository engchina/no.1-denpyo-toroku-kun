/**
 * Predict - 単一/バッチのテキスト意図予測。
 * プリセット、入力整形、結果操作を含むワークフロー。
 */
import { h, Fragment } from 'preact';
import { useState, useCallback, useRef, useEffect, useMemo } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { predictSingle, predictBatch } from '../../redux/slices/classifierSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { PredictionMode, getConfidenceLabel, getConfidenceClass } from '../../enums/classifierEnums';
import { PredictionResult, BatchPredictionResponse } from '../../types/classifierTypes';
import { formatPercentage } from '../../utils/apiUtils';
import { t } from '../../i18n';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';
import { ProgressBar } from '@oracle/oraclejet-preact/UNSAFE_ProgressBar';
import { ProgressCircle } from '@oracle/oraclejet-preact/UNSAFE_ProgressCircle';
import { usePagination } from '../../hooks/usePagination';
import { Pagination } from '../../components/Pagination';
import * as XLSX from 'xlsx';
import {
  Send,
  FileText,
  ChevronDown,
  ChevronUp,
  BarChart2,
  Settings,
  Target,
  MessageSquare,
  Upload,
  Sparkles,
  Wand2,
  ShieldCheck,
  Zap,
  Search,
  History
} from 'lucide-react';

const BATCH_LIMIT = 1000;
const BATCH_RESULTS_PAGE_SIZE = 20;
const BATCH_RESULTS_DISPLAY_ROWS = 10;
const RECENT_SINGLE_HISTORY_LIMIT = 8;

type BatchFilter = 'all' | 'review' | 'auto';
type BatchSort = 'index' | 'confidence_desc' | 'confidence_asc' | 'intent';
type PredictPresetId = 'balanced' | 'precision' | 'recall' | 'throughput';
type ActivePreset = PredictPresetId | 'custom';

interface PredictPreset {
  id: PredictPresetId;
  name: string;
  description: string;
  confidenceThreshold: number;
  topK: number;
  returnProba: boolean;
  unknownOnLowConf: boolean;
  unknownIntentLabel: string;
}

interface BatchDisplayRow extends PredictionResult {
  sourceIndex: number;
}

interface RecentPrediction {
  text: string;
  intent: string;
  confidence?: number;
  timestamp: string;
}

interface BatchInputDiagnostics {
  totalLines: number;
  validLines: number;
  duplicateLines: number;
  blankLines: number;
}

const PREDICT_PRESETS: PredictPreset[] = [
  {
    id: 'balanced',
    name: 'バランス',
    description: '通常運用向けの標準設定（汎用）。',
    confidenceThreshold: 0.58,
    topK: 3,
    returnProba: true,
    unknownOnLowConf: true,
    unknownIntentLabel: 'UNKNOWN'
  },
  {
    id: 'precision',
    name: '精度優先',
    description: '信頼度しきい値を高めにして、自動処理を安全側に寄せます。',
    confidenceThreshold: 0.72,
    topK: 5,
    returnProba: true,
    unknownOnLowConf: true,
    unknownIntentLabel: 'UNKNOWN'
  },
  {
    id: 'recall',
    name: '網羅性優先',
    description: 'UNKNOWN への振り分けを抑えて、意図のカバレッジを広げます。',
    confidenceThreshold: 0.40,
    topK: 5,
    returnProba: true,
    unknownOnLowConf: false,
    unknownIntentLabel: 'UNKNOWN'
  },
  {
    id: 'throughput',
    name: 'スループット優先',
    description: '大規模バッチ向けに、返却サイズと処理遅延を抑えます。',
    confidenceThreshold: 0.45,
    topK: 1,
    returnProba: false,
    unknownOnLowConf: false,
    unknownIntentLabel: 'UNKNOWN'
  }
];

const SINGLE_SAMPLE_TEXTS = [
  '注文の配送状況を確認したいです。',
  '先ほどの注文をキャンセルしてください。',
  '支払いが失敗してしまうのですが、どうすればいいですか？',
  '電子領収書を発行してもらえますか？',
  'このプランとプロ版の違いは何ですか？'
];

function splitCsvRow(row: string): string[] {
  const cells: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let i = 0; i < row.length; i += 1) {
    const char = row[i];
    if (char === '"') {
      const next = row[i + 1];
      if (inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === ',' && !inQuotes) {
      cells.push(current.trim());
      current = '';
      continue;
    }

    current += char;
  }

  cells.push(current.trim());
  return cells;
}

function detectBatchDiagnostics(rawText: string): BatchInputDiagnostics {
  const lines = rawText.split(/\r?\n/);
  const normalized = lines.map((line) => line.trim());
  const valid = normalized.filter(Boolean);
  const uniqueCount = new Set(valid).size;

  return {
    totalLines: lines.length,
    validLines: valid.length,
    duplicateLines: Math.max(0, valid.length - uniqueCount),
    blankLines: Math.max(0, normalized.filter((line) => line.length === 0).length)
  };
}

function toConfidencePercent(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(1)}%`;
}

function confidenceValue(value?: number | null): number {
  if (value == null || Number.isNaN(value)) return -1;
  return value;
}

function makeCsv(rows: BatchDisplayRow[], unknownLabel: string): string {
  const header = [
    'index',
    'text',
    'intent',
    'confidence',
    'routing',
    'low_confidence',
    'threshold_applied'
  ];

  const escapeCsv = (value: string | number | boolean | null | undefined): string => {
    const s = String(value ?? '');
    if (s.includes('"') || s.includes(',') || s.includes('\n')) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  };

  const lines = rows.map((row) => {
    const isUnknown = row.intent?.toUpperCase() === unknownLabel.toUpperCase();
    const reviewLabel = row.low_confidence || isUnknown
      ? '要確認'
      : getConfidenceLabel(row.confidence ?? 0);

    return [
      escapeCsv(row.sourceIndex),
      escapeCsv(row.text),
      escapeCsv(row.intent),
      escapeCsv(row.confidence != null ? formatPercentage(row.confidence, 2) : ''),
      escapeCsv(reviewLabel),
      escapeCsv(Boolean(row.low_confidence)),
      escapeCsv(row.threshold_applied != null ? formatPercentage(row.threshold_applied, 0) : '')
    ].join(',');
  });

  return [header.join(','), ...lines].join('\n');
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  document.execCommand('copy');
  document.body.removeChild(textArea);
}

export function Predict() {
  const dispatch = useAppDispatch();
  const stats = useAppSelector(state => state.classifier.stats);

  const [mode, setMode] = useState<PredictionMode>(PredictionMode.SINGLE);
  const [singleText, setSingleText] = useState('');
  const [batchText, setBatchText] = useState('');

  const [confidenceThreshold, setConfidenceThreshold] = useState(0.58);
  const [topK, setTopK] = useState(3);
  const [unknownOnLowConf, setUnknownOnLowConf] = useState(true);
  const [unknownIntentLabel, setUnknownIntentLabel] = useState('UNKNOWN');
  const [returnProba, setReturnProba] = useState(true);
  const [activePreset, setActivePreset] = useState<ActivePreset>('balanced');

  const [isLoading, setIsLoading] = useState(false);
  const [singleResult, setSingleResult] = useState<PredictionResult | null>(null);
  const [batchResults, setBatchResults] = useState<BatchPredictionResponse | null>(null);

  const [batchFilter, setBatchFilter] = useState<BatchFilter>('all');
  const [batchSearch, setBatchSearch] = useState('');
  const [batchSort, setBatchSort] = useState<BatchSort>('index');
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const [recentPredictions, setRecentPredictions] = useState<RecentPrediction[]>([]);
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);

  const [copiedSingle, setCopiedSingle] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const normalizedUnknownLabel = (unknownIntentLabel.trim() || 'UNKNOWN').toUpperCase();

  const recommendedThreshold = (() => {
    const summary = stats?.model?.training_summary;
    if (!summary) return null;
    const test = summary.test_accuracy ?? 0;
    const gap = summary.overfitting_gap ?? 0;
    if (test < 0.75) return { value: 0.50, range: '0.40 - 0.55', reason: 'モデルがまだ不安定です。確認許容範囲を広めに設定してください。' };
    if (gap > 0.10) return { value: 0.68, range: '0.60 - 0.75', reason: '過学習の傾向があります。安全な振り分けのためしきい値を上げてください。' };
    if (test >= 0.90 && gap < 0.05) return { value: 0.53, range: '0.45 - 0.60', reason: 'モデルの品質は良好です。バランス型のしきい値で十分です。' };
    return { value: 0.58, range: '0.50 - 0.65', reason: '信頼度が混在するトラフィック向けのバランス型しきい値を使用してください。' };
  })();

  const batchDiagnostics = useMemo(() => detectBatchDiagnostics(batchText), [batchText]);

  const preparedBatchLines = useMemo(
    () => batchText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
    [batchText]
  );

  const batchRows = useMemo<BatchDisplayRow[]>(
    () => (batchResults?.results || []).map((result, idx) => ({ ...result, sourceIndex: idx + 1 })),
    [batchResults]
  );

  const isReviewNeeded = useCallback((row: PredictionResult) => {
    const isUnknownIntent = (row.intent || '').toUpperCase() === normalizedUnknownLabel;
    return Boolean(row.low_confidence) || isUnknownIntent;
  }, [normalizedUnknownLabel]);

  const filteredBatchResults = useMemo(() => {
    const query = batchSearch.trim().toLowerCase();

    let rows = batchRows.filter((row) => {
      if (batchFilter === 'review') return isReviewNeeded(row);
      if (batchFilter === 'auto') return !isReviewNeeded(row);
      return true;
    });

    if (query) {
      rows = rows.filter((row) => (
        (row.text || '').toLowerCase().includes(query)
        || (row.intent || '').toLowerCase().includes(query)
      ));
    }

    const sorted = [...rows];

    if (batchSort === 'confidence_desc') {
      sorted.sort((a, b) => confidenceValue(b.confidence) - confidenceValue(a.confidence));
    } else if (batchSort === 'confidence_asc') {
      sorted.sort((a, b) => confidenceValue(a.confidence) - confidenceValue(b.confidence));
    } else if (batchSort === 'intent') {
      sorted.sort((a, b) => (a.intent || '').localeCompare(b.intent || ''));
    } else {
      sorted.sort((a, b) => a.sourceIndex - b.sourceIndex);
    }

    return sorted;
  }, [batchRows, batchFilter, batchSearch, batchSort, isReviewNeeded]);

  const batchUnknownCount = useMemo(
    () => batchRows.filter((row) => isReviewNeeded(row)).length,
    [batchRows, isReviewNeeded]
  );

  const batchAutoCount = batchRows.length - batchUnknownCount;
  const batchUnknownRate = batchRows.length > 0 ? batchUnknownCount / batchRows.length : 0;

  const batchAverageConfidence = useMemo(() => {
    const valid = batchRows.filter((row) => row.confidence != null);
    if (valid.length === 0) return null;
    const sum = valid.reduce((acc, row) => acc + (row.confidence || 0), 0);
    return sum / valid.length;
  }, [batchRows]);

  const reviewRows = useMemo(
    () => batchRows.filter((row) => isReviewNeeded(row)),
    [batchRows, isReviewNeeded]
  );

  const singleRanking = useMemo(() => {
    if (!singleResult) return [] as Array<{ intent: string; probability: number }>;

    if (singleResult.all_probabilities) {
      return Object.entries(singleResult.all_probabilities)
        .map(([intent, probability]) => ({ intent, probability }))
        .sort((a, b) => b.probability - a.probability);
    }

    if (singleResult.top_k_intents && singleResult.top_k_intents.length > 0) {
      return [...singleResult.top_k_intents]
        .sort((a, b) => b.probability - a.probability);
    }

    return [] as Array<{ intent: string; probability: number }>;
  }, [singleResult]);

  const batchPagination = usePagination(filteredBatchResults, { pageSize: BATCH_RESULTS_PAGE_SIZE });

  useEffect(() => {
    batchPagination.reset();
  }, [batchFilter, batchSearch, batchSort, batchResults]);

  useEffect(() => {
    if (expandedRow == null) return;
    const exists = filteredBatchResults.some((row) => row.sourceIndex === expandedRow);
    if (!exists) {
      setExpandedRow(null);
    }
  }, [filteredBatchResults, expandedRow]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key !== 'Enter') return;
      e.preventDefault();
      if (isLoading) return;
      if (mode === PredictionMode.SINGLE) {
        void handleSinglePredict();
      } else {
        void handleBatchPredict();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  useEffect(() => {
    if (!copiedSingle) return;
    const timer = window.setTimeout(() => setCopiedSingle(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copiedSingle]);

  const applyPreset = useCallback((preset: PredictPreset) => {
    setConfidenceThreshold(preset.confidenceThreshold);
    setTopK(preset.topK);
    setReturnProba(preset.returnProba);
    setUnknownOnLowConf(preset.unknownOnLowConf);
    setUnknownIntentLabel(preset.unknownIntentLabel);
    setActivePreset(preset.id);
    dispatch(addNotification({
      type: 'info',
      message: `プリセット「${preset.name}」を適用しました`,
      autoClose: true
    }));
  }, [dispatch]);

  const markPresetCustom = useCallback(() => {
    if (activePreset !== 'custom') {
      setActivePreset('custom');
    }
  }, [activePreset]);

  const withPredictionOptions = useMemo(() => ({
    return_proba: returnProba,
    confidence_threshold: confidenceThreshold,
    top_k: topK,
    unknown_on_low_conf: unknownOnLowConf,
    unknown_intent_label: unknownIntentLabel.trim() || 'UNKNOWN'
  }), [returnProba, confidenceThreshold, topK, unknownOnLowConf, unknownIntentLabel]);

  const handleSinglePredict = useCallback(async () => {
    if (!singleText.trim()) {
      dispatch(addNotification({ type: 'warning', message: '予測するテキストを入力してください', autoClose: true }));
      return;
    }

    setIsLoading(true);
    setSingleResult(null);

    try {
      const result = await dispatch(
        predictSingle({
          text: singleText.trim(),
          ...withPredictionOptions
        })
      ).unwrap();

      setSingleResult(result);

      setRecentPredictions((prev) => {
        const newItem: RecentPrediction = {
          text: result.text,
          intent: result.intent,
          confidence: result.confidence,
          timestamp: new Date().toISOString()
        };

        const deduped = prev.filter((item) => item.text !== result.text);
        return [newItem, ...deduped].slice(0, RECENT_SINGLE_HISTORY_LIMIT);
      });
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || '予測に失敗しました' }));
    } finally {
      setIsLoading(false);
    }
  }, [singleText, withPredictionOptions, dispatch]);

  const handleBatchPredict = useCallback(async () => {
    if (preparedBatchLines.length === 0) {
      dispatch(addNotification({ type: 'warning', message: '少なくとも 1 行のテキストを入力してください', autoClose: true }));
      return;
    }

    const linesToPredict = preparedBatchLines.slice(0, BATCH_LIMIT);
    if (preparedBatchLines.length > BATCH_LIMIT) {
      dispatch(addNotification({
        type: 'warning',
        message: `入力は ${preparedBatchLines.length} 行あります。先頭 ${BATCH_LIMIT} 行のみ予測しました。`,
        autoClose: true
      }));
    }

    setIsLoading(true);
    setBatchResults(null);
    setExpandedRow(null);

    try {
      const result = await dispatch(predictBatch({
        texts: linesToPredict,
        ...withPredictionOptions
      })).unwrap();

      setBatchResults(result);
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || '一括予測に失敗しました' }));
    } finally {
      setIsLoading(false);
    }
  }, [preparedBatchLines, withPredictionOptions, dispatch]);

  const handlePredict = useCallback(async () => {
    if (mode === PredictionMode.SINGLE) {
      await handleSinglePredict();
    } else {
      await handleBatchPredict();
    }
  }, [mode, handleSinglePredict, handleBatchPredict]);

  const applyBatchLines = useCallback((lines: string[], sourceName: string) => {
    const cleaned = lines.map((line) => String(line || '').trim()).filter(Boolean);

    if (cleaned.length === 0) {
      dispatch(addNotification({ type: 'warning', message: 'ファイルに有効なテキストが見つかりませんでした', autoClose: true }));
      return;
    }

    const limited = cleaned.slice(0, BATCH_LIMIT);
    if (cleaned.length > BATCH_LIMIT) {
      dispatch(addNotification({
        type: 'warning',
        message: `${cleaned.length} 行を読み込み、先頭 ${BATCH_LIMIT} 行に絞りました`,
        autoClose: true
      }));
    }

    setBatchText(limited.join('\n'));
    setUploadedFileName(sourceName);
    dispatch(addNotification({
      type: 'success',
      message: `${sourceName} から ${limited.length} 件のテキストを読み込みました`,
      autoClose: true
    }));
  }, [dispatch]);

  const parseXlsx = useCallback((file: File): Promise<string[]> => (
    new Promise((resolve, reject) => {
      const reader = new FileReader();

      reader.onload = (ev) => {
        try {
          const data = new Uint8Array(ev.target?.result as ArrayBuffer);
          const workbook = XLSX.read(data, { type: 'array' });
          const firstSheet = workbook.SheetNames[0];

          if (!firstSheet) {
            resolve([]);
            return;
          }

          const worksheet = workbook.Sheets[firstSheet];
          const rows = XLSX.utils.sheet_to_json(worksheet, { header: 1 }) as any[][];

          if (!rows || rows.length === 0) {
            resolve([]);
            return;
          }

          const header = rows[0] || [];
          const textColIdx = header.findIndex(
            (item: any) => String(item || '').trim().toLowerCase() === 'text'
          );

          const hasTextHeader = textColIdx >= 0;
          const col = hasTextHeader ? textColIdx : 0;
          const dataRows = hasTextHeader ? rows.slice(1) : rows;
          const lines = dataRows
            .map((row) => String(row?.[col] ?? '').trim())
            .filter(Boolean);

          resolve(lines);
        } catch (err) {
          reject(err);
        }
      };

      reader.onerror = (err) => reject(err);
      reader.readAsArrayBuffer(file);
    })
  ), []);

  const parseCsv = useCallback(async (file: File): Promise<string[]> => {
    const content = await file.text();
    const rows = content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

    if (rows.length === 0) return [];

    const headerCells = splitCsvRow(rows[0]).map((cell) => cell.toLowerCase());
    const textColIdx = headerCells.findIndex((cell) => cell === 'text');
    const hasHeader = textColIdx >= 0;
    const targetCol = hasHeader ? textColIdx : 0;

    return rows
      .slice(hasHeader ? 1 : 0)
      .map((row) => splitCsvRow(row)[targetCol] || '')
      .map((text) => text.trim())
      .filter(Boolean);
  }, []);

  const parseTxt = useCallback(async (file: File): Promise<string[]> => {
    const content = await file.text();
    return content.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  }, []);

  const handleFileUpload = useCallback(async (e: Event) => {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    const lowerName = file.name.toLowerCase();
    const isXlsx = lowerName.endsWith('.xlsx');
    const isCsv = lowerName.endsWith('.csv');
    const isTxt = lowerName.endsWith('.txt');

    if (!isXlsx && !isCsv && !isTxt) {
      dispatch(addNotification({
        type: 'error',
        message: '未対応の形式です。.xlsx / .csv / .txt を使用してください。',
        autoClose: true
      }));
      if (input) input.value = '';
      return;
    }

    try {
      let lines: string[] = [];
      if (isXlsx) {
        lines = await parseXlsx(file);
      } else if (isCsv) {
        lines = await parseCsv(file);
      } else {
        lines = await parseTxt(file);
      }

      applyBatchLines(lines, file.name);
    } catch {
      dispatch(addNotification({ type: 'error', message: 'アップロードしたファイルの解析に失敗しました', autoClose: true }));
    } finally {
      if (input) input.value = '';
    }
  }, [dispatch, parseXlsx, parseCsv, parseTxt, applyBatchLines]);

  const handleNormalizeBatchText = useCallback(() => {
    const lines = batchText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length === 0) {
      dispatch(addNotification({ type: 'warning', message: '整形できる行がありません', autoClose: true }));
      return;
    }

    const unique = Array.from(new Set(lines));
    const removed = lines.length - unique.length;
    const limited = unique.slice(0, BATCH_LIMIT);

    setBatchText(limited.join('\n'));
    setUploadedFileName(null);

    dispatch(addNotification({
      type: 'success',
      message: `一括入力を整形しました（重複 ${removed} 行を削除）。`,
      autoClose: true
    }));

    if (unique.length > BATCH_LIMIT) {
      dispatch(addNotification({
        type: 'warning',
        message: `API 上限により先頭 ${BATCH_LIMIT} 行のみ使用します。`,
        autoClose: true
      }));
    }
  }, [batchText, dispatch]);

  const handleTrimToLimit = useCallback(() => {
    if (preparedBatchLines.length <= BATCH_LIMIT) {
      dispatch(addNotification({ type: 'info', message: '入力はすでに上限内です', autoClose: true }));
      return;
    }

    setBatchText(preparedBatchLines.slice(0, BATCH_LIMIT).join('\n'));
    setUploadedFileName(null);
    dispatch(addNotification({
      type: 'info',
      message: `先頭 ${BATCH_LIMIT} 行に絞りました`,
      autoClose: true
    }));
  }, [preparedBatchLines, dispatch]);

  const handleClear = useCallback(() => {
    setSingleText('');
    setBatchText('');
    setSingleResult(null);
    setBatchResults(null);
    setExpandedRow(null);
    setUploadedFileName(null);
    setBatchFilter('all');
    setBatchSearch('');
    setBatchSort('index');
    batchPagination.reset();
  }, [batchPagination]);

  const triggerDownloadCsv = useCallback((filename: string, csvContent: string) => {
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, []);

  const handleExportCsv = useCallback((scope: 'all' | 'review' | 'current') => {
    if (!batchRows.length) {
      dispatch(addNotification({ type: 'info', message: '出力できる一括結果がありません', autoClose: true }));
      return;
    }

    let targetRows: BatchDisplayRow[] = [];
    if (scope === 'all') {
      targetRows = batchRows;
    } else if (scope === 'review') {
      targetRows = reviewRows;
    } else {
      targetRows = filteredBatchResults;
    }

    if (targetRows.length === 0) {
      dispatch(addNotification({ type: 'info', message: '選択した範囲に出力対象がありません', autoClose: true }));
      return;
    }

    const csv = makeCsv(targetRows, normalizedUnknownLabel);
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `predict_${scope}_${ts}.csv`;
    triggerDownloadCsv(filename, csv);

    dispatch(addNotification({
      type: 'success',
      message: `${targetRows.length} 件を ${filename} に出力しました`,
      autoClose: true
    }));
  }, [batchRows, reviewRows, filteredBatchResults, normalizedUnknownLabel, triggerDownloadCsv, dispatch]);

  const handleCopyReviewTexts = useCallback(async () => {
    if (reviewRows.length === 0) {
      dispatch(addNotification({ type: 'info', message: '要確認のテキストがありません', autoClose: true }));
      return;
    }

    try {
      const text = reviewRows.map((row) => row.text).join('\n');
      await copyToClipboard(text);
      dispatch(addNotification({ type: 'success', message: `要確認テキスト ${reviewRows.length} 件をコピーしました`, autoClose: true }));
    } catch {
      dispatch(addNotification({ type: 'error', message: '要確認テキストのコピーに失敗しました', autoClose: true }));
    }
  }, [reviewRows, dispatch]);

  const handleCopySingleResult = useCallback(async () => {
    if (!singleResult) return;
    try {
      await copyToClipboard(JSON.stringify(singleResult, null, 2));
      setCopiedSingle(true);
    } catch {
      dispatch(addNotification({ type: 'error', message: '結果 JSON のコピーに失敗しました', autoClose: true }));
    }
  }, [singleResult, dispatch]);

  const handleLoadSampleSingleText = useCallback(() => {
    const sample = SINGLE_SAMPLE_TEXTS[Math.floor(Math.random() * SINGLE_SAMPLE_TEXTS.length)];
    setSingleText(sample);
  }, []);

  const handleUseRowAsSingleInput = useCallback((text: string) => {
    setMode(PredictionMode.SINGLE);
    setSingleText(text);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  const singleRoutingGuidance = useMemo(() => {
    if (!singleResult || singleResult.confidence == null) {
      return {
        label: '手動確認を推奨',
        detail: 'この結果には信頼度が含まれていません。',
        className: 'ics-badge-warning'
      };
    }

    const conf = singleResult.confidence;
    if (conf >= 0.7) {
      return {
        label: '自動処理して問題なし',
        detail: '信頼度が高いため、自動処理で進められます。',
        className: 'ics-badge-success'
      };
    }

    if (conf >= 0.4) {
      return {
        label: '要確認',
        detail: '信頼度が中程度のため、確認キューへ振り分けてください。',
        className: 'ics-badge-warning'
      };
    }

    return {
      label: '手動対応へエスカレーション',
      detail: '信頼度が低いため、手動対応を優先してください。',
      className: 'ics-badge-danger'
    };
  }, [singleResult]);

  return (
    <div class="predictView predictView--enhanced">
      <section class="predictView__hero">
        <div class="predictView__heroHeader">
          <div class="genericHeading">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">
                予測
              </h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                入力から結果の処理まで、運用可能な意図識別フローを構築します。
              </p>
            </div>
          </div>

          <div class="predictView__heroMeta">
            <span class="predictView__heroBadge"><Sparkles size={14} /> 戦略: {activePreset === 'custom' ? 'カスタム' : PREDICT_PRESETS.find(p => p.id === activePreset)?.name}</span>
            <span class="predictView__heroBadge"><ShieldCheck size={14} /> しきい値: {(confidenceThreshold * 100).toFixed(0)}%</span>
            <span class="predictView__heroBadge"><Zap size={14} /> 上位 K 件: {topK}</span>
          </div>
        </div>

        <div class="predictView__heroMetrics">
          <div class="predictView__heroMetric">
            <div class="predictView__heroMetricLabel">モード</div>
            <div class="predictView__heroMetricValue">{mode === PredictionMode.SINGLE ? '単一' : '一括'}</div>
          </div>
          <div class="predictView__heroMetric">
            <div class="predictView__heroMetricLabel">UNKNOWN振り分け</div>
            <div class="predictView__heroMetricValue">{unknownOnLowConf ? '有効' : '無効'}</div>
          </div>
          <div class="predictView__heroMetric">
            <div class="predictView__heroMetricLabel">一括上限</div>
            <div class="predictView__heroMetricValue">{BATCH_LIMIT} 件</div>
          </div>
          <div class="predictView__heroMetric">
            <div class="predictView__heroMetricLabel">要確認率</div>
            <div class="predictView__heroMetricValue">{batchRows.length > 0 ? `${(batchUnknownRate * 100).toFixed(1)}%` : '--'}</div>
          </div>
        </div>
      </section>

      <div class="predictView__modeTabs">
        <button
          class={`predictView__modeTab ${mode === PredictionMode.SINGLE ? 'predictView__modeTab--active' : ''}`}
          onClick={() => {
            setMode(PredictionMode.SINGLE);
            setBatchResults(null);
            setExpandedRow(null);
          }}
        >
          <Send size={15} />
          <span>単一</span>
        </button>
        <button
          class={`predictView__modeTab ${mode === PredictionMode.BATCH ? 'predictView__modeTab--active' : ''}`}
          onClick={() => {
            setMode(PredictionMode.BATCH);
            setSingleResult(null);
          }}
        >
          <FileText size={15} />
          <span>一括</span>
        </button>
      </div>

      <div class="genericHeading">
        <div class="genericHeading--headings">
          <h1 class="genericHeading--headings__title genericHeading--headings__title--default">予測戦略</h1>
          <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
            まず戦略を定義し、推論を実行し、最後にリスクごとに振り分けます。
          </p>
        </div>
      </div>

      <div class="predictView__presetGrid">
        {PREDICT_PRESETS.map((preset) => (
          <div
            key={preset.id}
            class={`predictView__presetCard ${activePreset === preset.id ? 'predictView__presetCard--active' : ''}`}
          >
            <div class="predictView__presetHead">
              <div class="predictView__presetName">{preset.name}</div>
              {activePreset === preset.id && <span class="predictView__presetBadge">適用中</span>}
            </div>
            <div class="predictView__presetDesc">{preset.description}</div>
            <div class="predictView__presetMeta">
              <span>しきい値 {(preset.confidenceThreshold * 100).toFixed(0)}%</span>
              <span>上位 K 件 {preset.topK}</span>
              <span>{preset.returnProba ? '確率付き' : '確率なし'}</span>
            </div>
            <Button label="適用" variant="outlined" size="sm" onAction={() => applyPreset(preset)} isDisabled={isLoading} />
          </div>
        ))}
      </div>

      <div class="predictView__optionsGrid">
        <div class="oj-panel oj-sm-padding-7x predictView__optionCard">
          <div class="predictView__optionHeader">
            <figure class="genericIcon genericIcon__extra-small genericIcon__neutralLight">
              <Settings size={18} strokeWidth={2} />
            </figure>
            <div>
              <span class="oj-typography-subheading-xs">確率を返す</span>
              <p class="predictView__optionHelp">全カテゴリの分布を返し、境界サンプルの分析に役立てます。</p>
            </div>
          </div>
          <label class="predictView__switchRow">
            <input
              type="checkbox"
              checked={returnProba}
              onChange={(e: any) => {
                setReturnProba(e.target.checked);
                markPresetCustom();
              }}
            />
            <span>{returnProba ? '有効' : '無効'}</span>
          </label>
        </div>

        <div class="oj-panel oj-sm-padding-7x predictView__optionCard">
          <div class="predictView__optionHeader">
            <figure class="genericIcon genericIcon__extra-small genericIcon__neutralLight">
              <Target size={18} strokeWidth={2} />
            </figure>
            <div>
              <span class="oj-typography-subheading-xs">信頼度しきい値</span>
              <p class="predictView__optionHelp">しきい値未満の結果は確認キューに振り分けられます。</p>
            </div>
          </div>

          <div class="predictView__sliderRow">
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={confidenceThreshold}
              class="ics-slider"
              onInput={(e: any) => {
                setConfidenceThreshold(parseFloat(e.target.value));
                markPresetCustom();
              }}
            />
            <span class="predictView__sliderValue">{(confidenceThreshold * 100).toFixed(0)}%</span>
          </div>

          {recommendedThreshold && (
            <div class="predictView__recommendationBox">
              <div>
                <div class="predictView__recommendationTitle">推奨: {recommendedThreshold.range}</div>
                <div class="predictView__recommendationDesc">{recommendedThreshold.reason}</div>
              </div>
              <Button
                label="適用"
                variant="outlined"
                size="sm"
                onAction={() => {
                  setConfidenceThreshold(recommendedThreshold.value);
                  markPresetCustom();
                }}
                isDisabled={isLoading}
              />
            </div>
          )}
        </div>

        <div class="oj-panel oj-sm-padding-7x predictView__optionCard">
          <div class="predictView__optionHeader">
            <figure class="genericIcon genericIcon__extra-small genericIcon__neutralLight">
              <BarChart2 size={18} strokeWidth={2} />
            </figure>
            <div>
              <span class="oj-typography-subheading-xs">上位 K 件</span>
              <p class="predictView__optionHelp">候補として返す意図数（1〜10 を推奨）。</p>
            </div>
          </div>
          <input
            type="number"
            min={1}
            max={10}
            step={1}
            class="ics-input"
            value={topK}
            onInput={(e: any) => {
              const next = Math.max(1, Math.min(10, Number.parseInt(e.target.value || '1', 10)));
              setTopK(next);
              markPresetCustom();
            }}
          />
        </div>

        <div class="oj-panel oj-sm-padding-7x predictView__optionCard">
          <div class="predictView__optionHeader">
            <figure class="genericIcon genericIcon__extra-small genericIcon__neutralLight">
              <Wand2 size={18} strokeWidth={2} />
            </figure>
            <div>
              <span class="oj-typography-subheading-xs">{t('predict.lowConfidenceRouting')}</span>
              <p class="predictView__optionHelp">信頼度が低い場合に UNKNOWN として扱うかどうか。</p>
            </div>
          </div>

          <label class="predictView__switchRow">
            <input
              type="checkbox"
              checked={unknownOnLowConf}
              onChange={(e: any) => {
                setUnknownOnLowConf(Boolean(e.target.checked));
                markPresetCustom();
              }}
            />
            <span>{unknownOnLowConf ? t('common.enabled') : t('common.disabled')}</span>
          </label>

          <div class="predictView__fieldBlock">
            <label class="predictView__fieldLabel">UNKNOWN ラベル</label>
            <input
              type="text"
              class="ics-input"
              value={unknownIntentLabel}
              maxLength={40}
              onInput={(e: any) => {
                setUnknownIntentLabel(e.target.value || 'UNKNOWN');
                markPresetCustom();
              }}
              placeholder="UNKNOWN"
            />
          </div>
        </div>
      </div>

      <div class="genericHeading oj-sm-margin-8x-top">
        <div class="genericHeading--headings">
          <h1 class="genericHeading--headings__title genericHeading--headings__title--default">
            {mode === PredictionMode.SINGLE ? '単一入力' : '一括入力'}
          </h1>
          <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
            {mode === PredictionMode.SINGLE
              ? 'テキストを 1 件入力して、予測結果を確認します。'
              : 'ファイルのアップロードや貼り付けで一括推論します（実行前に整形可能）。'}
          </p>
        </div>
      </div>

      <div class="oj-panel oj-sm-padding-7x predictView__panel">
        <div class="predictView__panelHeader">
          <div class="predictView__panelHeaderLeft">
            <figure class="genericIcon genericIcon__extra-small genericIcon__primaryDark">
              <MessageSquare size={20} strokeWidth={2} />
            </figure>
            <div>
              <span class="oj-typography-subheading-xs">
                {mode === PredictionMode.SINGLE ? '単一テキスト予測' : '一括テキスト予測'}
              </span>
              <p class="oj-typography-body-sm oj-text-color-secondary predictView__panelSubtitle">
                {mode === PredictionMode.SINGLE
                  ? t('predict.input.hint')
                  : `推奨: 重複を除去してから実行（最大 ${BATCH_LIMIT} 件）`}
              </p>
            </div>
          </div>

          {mode === PredictionMode.SINGLE ? (
            <Button label="サンプルを読み込む" variant="outlined" onAction={handleLoadSampleSingleText} isDisabled={isLoading} />
          ) : (
            <div class="predictView__panelHeaderActions">
              <Button label="整形" variant="outlined" onAction={handleNormalizeBatchText} isDisabled={isLoading} />
              <Button label={`上限 ${BATCH_LIMIT} 件に絞る`} variant="outlined" onAction={handleTrimToLimit} isDisabled={isLoading} />
            </div>
          )}
        </div>

        {mode === PredictionMode.SINGLE ? (
          <div>
            <textarea
              class="ics-input predictView__singleInput"
              rows={4}
              placeholder={t('predict.input.example')}
              value={singleText}
              disabled={isLoading}
              onInput={(e: any) => setSingleText(e.target.value)}
              onKeyDown={(e: any) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                  void handleSinglePredict();
                }
              }}
            />

            <div class="predictView__inputMeta">
              <span class="oj-typography-body-sm oj-text-color-secondary">{singleText.trim().length} 文字</span>
              <span class="oj-typography-body-sm oj-text-color-secondary">言語に依存しない意図分類</span>
            </div>

            <div class="predictView__sampleRow">
              {SINGLE_SAMPLE_TEXTS.map((sample) => (
                <button
                  key={sample}
                  class="predictView__sampleBtn"
                  onClick={() => setSingleText(sample)}
                  type="button"
                >
                  {sample}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.csv,.txt"
              class="predictView__hiddenFileInput"
              onChange={handleFileUpload}
            />

            <div
              class="predictView__dropZone"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e: DragEvent) => {
                e.preventDefault();
                e.stopPropagation();
                (e.currentTarget as HTMLElement).classList.add('predictView__dropZone--active');
              }}
              onDragLeave={(e: DragEvent) => {
                e.preventDefault();
                (e.currentTarget as HTMLElement).classList.remove('predictView__dropZone--active');
              }}
              onDrop={(e: DragEvent) => {
                e.preventDefault();
                (e.currentTarget as HTMLElement).classList.remove('predictView__dropZone--active');
                const file = e.dataTransfer?.files?.[0];
                if (file) {
                  const dt = new DataTransfer();
                  dt.items.add(file);
                  if (fileInputRef.current) {
                    fileInputRef.current.files = dt.files;
                    fileInputRef.current.dispatchEvent(new Event('change', { bubbles: true }));
                  }
                }
              }}
            >
              <Upload size={24} strokeWidth={1.5} class="predictView__dropZoneIcon" />
              <span class="oj-typography-body-md">
                {uploadedFileName
                  ? <span>読み込み済み: <strong>{uploadedFileName}</strong></span>
                  : 'ここにファイルをドロップするか、クリックしてアップロード'}
              </span>
              <span class="oj-typography-body-sm oj-text-color-secondary predictView__dropZoneHint">
                対応形式: .xlsx / .csv / .txt
              </span>
            </div>

            <div class="predictView__batchStatsGrid oj-sm-margin-4x-top">
              <div class="predictView__batchStat">
                <span>総行数</span>
                <strong>{batchDiagnostics.totalLines}</strong>
              </div>
              <div class="predictView__batchStat">
                <span>有効行数</span>
                <strong>{batchDiagnostics.validLines}</strong>
              </div>
              <div class="predictView__batchStat">
                <span>重複</span>
                <strong>{batchDiagnostics.duplicateLines}</strong>
              </div>
              <div class="predictView__batchStat">
                <span>空行</span>
                <strong>{batchDiagnostics.blankLines}</strong>
              </div>
            </div>

            <textarea
              class="ics-input predictView__batchInput"
              rows={10}
              placeholder={'注文状況を確認したい\nクーポンが使えない\n領収書を再発行できますか'}
              value={batchText}
              onInput={(e: any) => {
                setBatchText(e.target.value);
                setUploadedFileName(null);
              }}
              disabled={isLoading}
            />

            <div class="predictView__inputMeta">
              <span class="oj-typography-body-sm oj-text-color-secondary">
                準備完了: {preparedBatchLines.length} 行
              </span>
              <span class="oj-typography-body-sm oj-text-color-secondary">
                {preparedBatchLines.length > BATCH_LIMIT ? `先頭 ${BATCH_LIMIT} 行を使用` : `${BATCH_LIMIT} 行以内`}
              </span>
            </div>
          </div>
        )}

        <div class="predictView__actionRow oj-sm-margin-4x-top">
          <Button
            label={isLoading ? '予測中…' : (mode === PredictionMode.SINGLE ? '予測' : '一括予測')}
            onAction={() => { void handlePredict(); }}
            isDisabled={isLoading}
          />
          <Button label="クリア" variant="outlined" onAction={handleClear} isDisabled={isLoading} />
          <span class="predictView__hotkeyHint">ショートカット: Ctrl/Cmd + Enter</span>
        </div>
      </div>

      {isLoading && (
        <div class="predictView__statusPanel">
          <div class="predictView__statusHeader">
            <ProgressCircle value={-1} size="sm" />
            <span class="oj-typography-subheading-xs">予測を実行中</span>
          </div>
          <p class="oj-typography-body-md predictView__statusText">処理中…</p>
          <p class="oj-typography-body-sm oj-text-color-secondary">
            予測には数秒かかる場合があります…
          </p>
        </div>
      )}

      {singleResult && mode === PredictionMode.SINGLE && !isLoading && (
        <div>
          <div class="genericHeading oj-sm-margin-8x-top">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">単一結果</h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                予測結果、信頼度、ルーティングの目安。
              </p>
            </div>
          </div>

          <div class="oj-panel oj-sm-padding-7x oj-sm-margin-4x-top predictView__panel">
            <div class="predictView__resultKpiGrid">
              <div class="predictView__resultKpi">
                <span class="predictView__resultKpiLabel">予測意図</span>
                <span class="predictView__resultKpiValue">{singleResult.intent}</span>
              </div>
              <div class="predictView__resultKpi">
                <span class="predictView__resultKpiLabel">信頼度</span>
                <span class={`predictView__resultKpiValue ${getConfidenceClass(singleResult.confidence ?? 0)}`}>
                  {toConfidencePercent(singleResult.confidence)}
                </span>
              </div>
              <div class="predictView__resultKpi">
                <span class="predictView__resultKpiLabel">ルーティング</span>
                <span class={`predictView__resultKpiValue ${getConfidenceClass(singleResult.confidence ?? 0)}`}>
                  {singleResult.confidence != null ? getConfidenceLabel(singleResult.confidence) : '--'}
                </span>
              </div>
              <div class="predictView__resultKpi">
                <span class="predictView__resultKpiLabel">適用しきい値</span>
                <span class="predictView__resultKpiValue">
                  {singleResult.threshold_applied != null ? formatPercentage(singleResult.threshold_applied, 0) : '--'}
                </span>
              </div>
            </div>

            <div class="predictView__nextAction oj-sm-margin-4x-top">
              <div class="predictView__nextActionHead">
                <ShieldCheck size={15} />
                <span>対応の目安</span>
              </div>
              <div class="predictView__nextActionBody">
                <span class={singleRoutingGuidance.className}>{singleRoutingGuidance.label}</span>
                <span class="oj-typography-body-sm oj-text-color-secondary">{singleRoutingGuidance.detail}</span>
              </div>
            </div>

            <div class="predictView__copyRow oj-sm-margin-4x-top">
              <span class="oj-typography-body-sm oj-text-color-secondary predictView__copyRowText">
                入力: {singleResult.text}
              </span>
              <Button
                label={copiedSingle ? 'コピーしました' : 'JSON をコピー'}
                variant="outlined"
                size="sm"
                onAction={() => { void handleCopySingleResult(); }}
              />
            </div>

            {singleRanking.length > 0 && (
              <div class="oj-sm-margin-4x-top">
                <div class="predictView__rankedHeader">
                  <BarChart2 size={16} class="predictView__rankedHeaderIcon" />
                  <span class="oj-typography-subheading-xs">意図ランキング</span>
                </div>
                <table class="ics-table">
                  <thead>
                    <tr>
                      <th>意図</th>
                      <th style={{ width: '110px' }}>確率</th>
                      <th>分布</th>
                    </tr>
                  </thead>
                  <tbody>
                    {singleRanking.map((item) => (
                      <tr key={item.intent}>
                        <td><span class="ics-class-tag">{item.intent}</span></td>
                        <td>{(item.probability * 100).toFixed(2)}%</td>
                        <td><ProgressBar value={item.probability * 100} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {recentPredictions.length > 0 && (
            <div class="oj-panel oj-sm-padding-7x oj-sm-margin-4x-top predictView__historyPanel">
              <div class="predictView__historyHead">
                <History size={16} />
                <span class="oj-typography-subheading-xs">最近の予測</span>
              </div>
              <div class="predictView__historyList">
                {recentPredictions.map((item, idx) => (
                  <button
                    key={`${item.text}-${idx}`}
                    class="predictView__historyItem"
                    onClick={() => {
                      setMode(PredictionMode.SINGLE);
                      setSingleText(item.text);
                    }}
                    type="button"
                  >
                    <span class="predictView__historyText">{item.text}</span>
                    <span class="predictView__historyMeta">
                      {item.intent} {item.confidence != null ? `(${toConfidencePercent(item.confidence)})` : ''}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {batchResults && mode === PredictionMode.BATCH && !isLoading && (
        <div>
          <div class="genericHeading oj-sm-margin-8x-top">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">一括結果</h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                {batchResults.total} 件を分類（{batchResults.processing_time.toFixed(3)} 秒）
              </p>
            </div>
          </div>

          <div class="predictView__batchSummaryGrid oj-sm-margin-4x-top">
            <div class="predictView__batchSummaryCard">
              <span>合計</span>
              <strong>{batchRows.length}</strong>
            </div>
            <div class="predictView__batchSummaryCard">
              <span>要確認</span>
              <strong>{batchUnknownCount}</strong>
            </div>
            <div class="predictView__batchSummaryCard">
              <span>自動処理</span>
              <strong>{batchAutoCount}</strong>
            </div>
            <div class="predictView__batchSummaryCard">
              <span>平均信頼度</span>
              <strong>{batchAverageConfidence != null ? toConfidencePercent(batchAverageConfidence) : '--'}</strong>
            </div>
          </div>

          <div class="oj-panel oj-sm-padding-7x oj-sm-margin-4x-top predictView__panel">
            <div class="predictView__batchControls">
              <div class="predictView__filterGroup">
                <button
                  class={`predictView__filterBtn ${batchFilter === 'all' ? 'predictView__filterBtn--active' : ''}`}
                  onClick={() => setBatchFilter('all')}
                >
                  すべて ({batchRows.length})
                </button>
                <button
                  class={`predictView__filterBtn ${batchFilter === 'review' ? 'predictView__filterBtn--active' : ''}`}
                  onClick={() => setBatchFilter('review')}
                >
                  要確認 ({batchUnknownCount})
                </button>
                <button
                  class={`predictView__filterBtn ${batchFilter === 'auto' ? 'predictView__filterBtn--active' : ''}`}
                  onClick={() => setBatchFilter('auto')}
                >
                  自動処理 ({batchAutoCount})
                </button>
              </div>

              <div class="predictView__controlTools">
                <label class="predictView__searchWrap">
                  <Search size={14} />
                  <input
                    class="ics-input predictView__searchInput"
                    type="text"
                    placeholder="テキスト/意図を検索"
                    value={batchSearch}
                    onInput={(e: any) => setBatchSearch(e.target.value)}
                  />
                </label>

                <select
                  class="ics-input predictView__sortSelect"
                  value={batchSort}
                  onChange={(e: any) => setBatchSort(e.target.value as BatchSort)}
                >
                  <option value="index">並び替え: 元の順序</option>
                  <option value="confidence_desc">並び替え: 信頼度（高い順）</option>
                  <option value="confidence_asc">並び替え: 信頼度（低い順）</option>
                  <option value="intent">並び替え: 意図</option>
                </select>

                <Button label="現在の結果を出力" variant="outlined" size="sm" onAction={() => handleExportCsv('current')} />
                <Button label="要確認のみ出力" variant="outlined" size="sm" onAction={() => handleExportCsv('review')} />
                <Button label="全件を出力" variant="outlined" size="sm" onAction={() => handleExportCsv('all')} />
                <Button label="要確認テキストをコピー" variant="outlined" size="sm" onAction={() => { void handleCopyReviewTexts(); }} />
              </div>
            </div>

            <Pagination
              currentPage={batchPagination.currentPage}
              totalPages={batchPagination.totalPages}
              totalItems={batchPagination.totalItems}
              goToPageInput={batchPagination.goToPageInput}
              onPageChange={batchPagination.goToPage}
              onGoToPageInputChange={batchPagination.setGoToPageInput}
              onGoToPage={batchPagination.handleGoToPage}
              isFirstPage={batchPagination.isFirstPage}
              isLastPage={batchPagination.isLastPage}
              position="top"
              show={batchPagination.showPagination}
            />

            {batchPagination.totalItems === 0 ? (
              <div class="predictView__emptyBlock">
                <FileText size={24} />
                <p>該当するデータがありません。</p>
              </div>
            ) : (
              <div class="predictView__tableContainer" style={{ maxHeight: `${BATCH_RESULTS_DISPLAY_ROWS * 41 + 42}px` }}>
                <table class="ics-table ics-table--sticky">
                  <thead>
                    <tr>
                      <th style={{ width: '52px' }}>#</th>
                      <th>テキスト</th>
                      <th style={{ width: '150px' }}>意図</th>
                      <th style={{ width: '120px' }}>信頼度</th>
                      <th style={{ width: '120px' }}>振り分け</th>
                      <th style={{ width: '96px' }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {batchPagination.paginatedItems.map((row) => (
                      <Fragment key={`batch-${row.sourceIndex}`}>
                        <tr>
                          <td class="ics-text-muted">{row.sourceIndex}</td>
                          <td class="ics-text-truncate" title={row.text}>{row.text}</td>
                          <td><span class="ics-class-tag">{row.intent}</span></td>
                          <td>
                            <span class={getConfidenceClass(row.confidence ?? 0)}>{toConfidencePercent(row.confidence)}</span>
                          </td>
                          <td>
                            <span class={getConfidenceClass(row.confidence ?? 0)}>
                              {row.confidence != null ? getConfidenceLabel(row.confidence) : '--'}
                            </span>
                          </td>
                          <td>
                            <div class="predictView__rowActions">
                              <button
                                class="predictView__expandBtn"
                                title="単一入力として使用"
                                onClick={() => handleUseRowAsSingleInput(row.text)}
                              >
                                <MessageSquare size={13} />
                              </button>
                              {row.all_probabilities && (
                                <button
                                  class={`predictView__expandBtn ${expandedRow === row.sourceIndex ? 'predictView__expandBtn--active' : ''}`}
                                  onClick={() => setExpandedRow(expandedRow === row.sourceIndex ? null : row.sourceIndex)}
                                  title="確率分布を表示"
                                >
                                  {expandedRow === row.sourceIndex ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>

                        {expandedRow === row.sourceIndex && row.all_probabilities && (
                          <tr class="ics-expanded-row">
                            <td colSpan={6}>
                              <div class="ics-expandedRowBody">
                                <div class="ics-inlineHeader">
                                  <BarChart2 size={14} class="ics-text-muted" />
                                  <span class="oj-typography-body-sm oj-typography-semi-bold">確率分布</span>
                                </div>
                                <table class="ics-table">
                                  <thead>
                                    <tr>
                                      <th>意図</th>
                                      <th style={{ width: '110px' }}>確率</th>
                                      <th>分布</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {Object.entries(row.all_probabilities)
                                      .sort(([, a], [, b]) => b - a)
                                      .map(([intent, probability]) => (
                                        <tr key={`${row.sourceIndex}-${intent}`}>
                                          <td><span class="ics-class-tag">{intent}</span></td>
                                          <td>{(probability * 100).toFixed(2)}%</td>
                                          <td><ProgressBar value={probability * 100} /></td>
                                        </tr>
                                      ))}
                                  </tbody>
                                </table>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <Pagination
              currentPage={batchPagination.currentPage}
              totalPages={batchPagination.totalPages}
              totalItems={batchPagination.totalItems}
              goToPageInput={batchPagination.goToPageInput}
              onPageChange={batchPagination.goToPage}
              onGoToPageInputChange={batchPagination.setGoToPageInput}
              onGoToPage={batchPagination.handleGoToPage}
              isFirstPage={batchPagination.isFirstPage}
              isLastPage={batchPagination.isLastPage}
              position="bottom"
              show={batchPagination.showPagination}
            />
          </div>
        </div>
      )}
    </div>
  );
}
