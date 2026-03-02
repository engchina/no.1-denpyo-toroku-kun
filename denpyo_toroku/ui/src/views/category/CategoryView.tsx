/**
 * CategoryView - 伝票分類管理画面 (SCR-005)
 *
 * 機能:
 *  A. SLIPS_CATEGORY ファイル一覧 + AI 分析フロー
 *     1. SLIPS_CATEGORY アップロードファイル一覧（最大5件選択）
 *     2. AI 分析モード選択 (HEADER only / HEADER+LINE)
 *     3. テーブルデザイナー UI（カラム追加/削除/編集）
 *     4. テーブル作成 → 伝票分類登録
 *  B. 伝票分類一覧 CRUD (参照・編集・削除・有効/無効)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import {
  fetchCategories,
  updateCategory,
  toggleCategoryActive,
  deleteCategory,
  bulkDeleteFiles,
  fetchSlipsCategoryFiles,
  analyzeSlipsForCategory,
  fetchCategoryAnalysisResult,
  createCategoryWithTables,
  clearCategoryAnalysis,
  setSlipsCategoryPage,
  setSlipsCategoryPageSize,
  fetchTableDataByName,
} from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import Pagination from '../../components/Pagination';
import { usePagination } from '../../hooks/usePagination';
import { useSelection } from '../../hooks/useSelection';
import { useToastConfirm } from '../../hooks/useToastConfirm';
import { t } from '../../i18n';
import { APP_ROUTES } from '../../constants/routes';
import { getCurrentSearchParams, readScopedNumber, replaceSearchParams, setScopedValue } from '../../utils/queryScope';
import { apiPost } from '../../utils/apiUtils';
import { useLocation, useNavigate } from 'react-router-dom';
import type {
  DenpyoCategory,
  DenpyoFile,
  CategoryUpdateRequest,
  TableColumnDef,
  CategoryAnalysisResult,
  CategoryCreateRequest,
} from '../../types/denpyoTypes';
import {
  RefreshCw,
  Pencil,
  Trash2,
  Eye,
  ToggleLeft,
  ToggleRight,
  X,
  Save,
  Loader2,
  Sparkles,
  Plus,
  Database,
  ChevronDown,
  ChevronUp,
  FileText,
  Table2,
  ImageIcon,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  MinusCircle,
  FileSearch,
} from 'lucide-react';
import { StatusBadge } from '../../components/common/StatusBadge';

// ─── Utils ───────────────────────────────────────────────────────────────────

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString('ja-JP')} ${date.toLocaleTimeString('ja-JP')}`;
}

function formatFileSize(bytes: number | null | undefined): string {
  if (typeof bytes !== 'number' || Number.isNaN(bytes) || bytes < 0) return '--';
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function buildDDLPreview(tableName: string, columns: TableColumnDef[]): string {
  if (!tableName || columns.length === 0) return '';
  const colDefs = columns.map(col => {
    const name = col.column_name.toUpperCase();
    let typeDef: string;
    if (col.data_type === 'VARCHAR2') {
      typeDef = `VARCHAR2(${col.max_length || 500})`;
    } else if (col.data_type === 'NUMBER') {
      if (col.precision && col.scale != null) {
        typeDef = `NUMBER(${col.precision},${col.scale})`;
      } else if (col.precision) {
        typeDef = `NUMBER(${col.precision})`;
      } else {
        typeDef = 'NUMBER';
      }
    } else {
      typeDef = col.data_type;
    }
    const nullClause = col.is_nullable ? '' : ' NOT NULL';
    const pkMark = col.is_primary_key ? ' -- PK' : '';
    return `    ${name} ${typeDef}${nullClause}${pkMark}`;
  });
  const pkCols = columns.filter(c => c.is_primary_key).map(c => c.column_name.toUpperCase());
  if (pkCols.length > 0) {
    const pkName = `PK_${tableName.substring(0, 20).toUpperCase()}`;
    colDefs.push(`    CONSTRAINT ${pkName} PRIMARY KEY (${pkCols.join(', ')})`);
  }
  return `CREATE TABLE ${tableName.toUpperCase()} (\n${colDefs.join(',\n')}\n)`;
}

const DATA_TYPES = ['VARCHAR2', 'NUMBER', 'DATE', 'TIMESTAMP'] as const;
const PAGINATION_PAGE_SIZE_OPTIONS = [20, 50, 100];
const CATEGORY_SAMPLES_QUERY_SCOPE = 'cs';
const CATEGORY_MANAGEMENT_QUERY_SCOPE = 'cm';
type SortDirection = 'asc' | 'desc';
type SlipsSortKey = 'file_name' | 'file_type' | 'file_size' | 'uploaded_at';
type CategorySortKey =
  | 'category_name'
  | 'category_name_en'
  | 'header_table_name'
  | 'registration_count'
  | 'is_active'
  | 'created_at';
type PreviewTabType = 'header' | 'line';

function compareValues(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;

  if (typeof a === 'number' && typeof b === 'number') {
    return a - b;
  }

  const aDate = new Date(String(a)).getTime();
  const bDate = new Date(String(b)).getTime();
  if (!Number.isNaN(aDate) && !Number.isNaN(bDate)) {
    return aDate - bDate;
  }

  const aNum = Number(a);
  const bNum = Number(b);
  if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
    return aNum - bNum;
  }

  return String(a).localeCompare(String(b), 'ja');
}

function getDefaultDataSortColumn(columns: string[]): string {
  if (!columns.length) return '';
  const target = new Set(['created_at', 'uploaded_at', 'create_time', 'upload_time', 'created_date', 'uploaded_date']);
  const matched = columns.find((col) => target.has(col.trim().toLowerCase()));
  return matched || columns[0];
}

function formatCellValue(value: any): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function FileStatusBadge({ status }: { status: DenpyoFile['status'] }) {
  const variantMap: Record<DenpyoFile['status'], 'info' | 'warning' | 'success' | 'primary' | 'error'> = {
    UPLOADED: 'info',
    ANALYZING: 'warning',
    ANALYZED: 'success',
    REGISTERED: 'primary',
    ERROR: 'error',
  };
  const iconMap: Record<DenpyoFile['status'], any> = {
    UPLOADED: FileText,
    ANALYZING: Loader2,
    ANALYZED: CheckCircle2,
    REGISTERED: Database,
    ERROR: MinusCircle,
  };
  const labelMap: Record<DenpyoFile['status'], Parameters<typeof t>[0]> = {
    UPLOADED: 'fileList.status.uploaded',
    ANALYZING: 'fileList.status.analyzing',
    ANALYZED: 'fileList.status.analyzed',
    REGISTERED: 'fileList.status.registered',
    ERROR: 'fileList.status.error',
  };
  const Icon = iconMap[status] || FileText;
  return (
    <StatusBadge variant={variantMap[status] || 'info'} icon={status === 'ANALYZING' ? () => <Icon size={14} class="ics-spin" /> : Icon}>
      {t(labelMap[status] || 'fileList.status.uploaded')}
    </StatusBadge>
  );
}

function hasViewableResult(file: Pick<DenpyoFile, 'status' | 'has_analysis_result'>): boolean {
  return Boolean(file.has_analysis_result) || file.status === 'ANALYZED' || file.status === 'REGISTERED';
}

function isImageFile(fileName: string | null | undefined): boolean {
  if (!fileName) return false;
  return /\.(png|jpe?g|gif|bmp|webp|svg)$/i.test(fileName);
}

// ─── Category Edit Modal (existing CRUD) ─────────────────────────────────────

function EditModal({
  category,
  onSave,
  onClose,
  isSaving,
}: {
  category: DenpyoCategory;
  onSave: (data: CategoryUpdateRequest) => void;
  onClose: () => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(category.category_name);
  const [nameEn, setNameEn] = useState(category.category_name_en);
  const [desc, setDesc] = useState(category.description);

  const handleSubmit = useCallback(
    (e: Event) => {
      e.preventDefault();
      if (!name.trim()) return;
      onSave({ category_name: name.trim(), category_name_en: nameEn.trim(), description: desc.trim() });
    },
    [name, nameEn, desc, onSave]
  );

  return (
    <div class="ics-modal-overlay" onClick={onClose}>
      <div class="ics-modal" onClick={(e: Event) => e.stopPropagation()}>
        <div class="ics-modal__header">
          <h3>{t('category.edit.title')}</h3>
          <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div class="ics-modal__body">
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.name')}</label>
              <input
                type="text"
                class="ics-form-input"
                value={name}
                onInput={(e: Event) => setName((e.target as HTMLInputElement).value)}
                required
              />
            </div>
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.nameEn')}</label>
              <input
                type="text"
                class="ics-form-input"
                value={nameEn}
                onInput={(e: Event) => setNameEn((e.target as HTMLInputElement).value)}
              />
            </div>
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.description')}</label>
              <textarea
                class="ics-form-textarea"
                value={desc}
                rows={3}
                onInput={(e: Event) => setDesc((e.target as HTMLTextAreaElement).value)}
              />
            </div>
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.headerTable')}</label>
              <input type="text" class="ics-form-input" value={category.header_table_name} disabled />
            </div>
            {category.line_table_name && (
              <div class="ics-form-group">
                <label class="ics-form-label">{t('category.col.lineTable')}</label>
                <input type="text" class="ics-form-input" value={category.line_table_name} disabled />
              </div>
            )}
          </div>
          <div class="ics-modal__footer">
            <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={onClose} disabled={isSaving}>
              {t('common.cancel')}
            </button>
            <button type="submit" class="ics-ops-btn ics-ops-btn--primary" disabled={isSaving || !name.trim()}>
              {isSaving ? <Loader2 size={14} class="ics-spin" /> : <Save size={14} />}
              <span>{isSaving ? t('common.saving') : t('common.save')}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Analysis Mode Modal ──────────────────────────────────────────────────────

function AnalysisModeModal({
  selectedCount,
  onConfirm,
  onClose,
}: {
  selectedCount: number;
  onConfirm: (mode: 'header_only' | 'header_line') => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<'header_only' | 'header_line'>('header_only');

  return (
    <div class="ics-modal-overlay" onClick={onClose}>
      <div class="ics-modal" style={{ maxWidth: '480px' }} onClick={(e: Event) => e.stopPropagation()}>
        <div class="ics-modal__header">
          <h3>{t('category.analyze.modeTitle')}</h3>
          <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div class="ics-modal__body">
          <p class="ics-form-hint" style={{ marginBottom: '16px' }}>
            {t('category.analyze.modeDesc', { count: selectedCount })}
          </p>
          <div class="ics-radio-group">
            <label class="ics-radio-label">
              <input
                type="radio"
                name="analysisMode"
                value="header_only"
                checked={mode === 'header_only'}
                onChange={() => setMode('header_only')}
              />
              <span class="ics-radio-text">
                <strong>{t('category.analyze.modeHeaderOnly')}</strong>
                <span class="ics-form-hint">{t('category.analyze.modeHeaderOnlyDesc')}</span>
              </span>
            </label>
            <label class="ics-radio-label">
              <input
                type="radio"
                name="analysisMode"
                value="header_line"
                checked={mode === 'header_line'}
                onChange={() => setMode('header_line')}
              />
              <span class="ics-radio-text">
                <strong>{t('category.analyze.modeHeaderLine')}</strong>
                <span class="ics-form-hint">{t('category.analyze.modeHeaderLineDesc')}</span>
              </span>
            </label>
          </div>
        </div>
        <div class="ics-modal__footer">
          <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button type="button" class="ics-ops-btn ics-ops-btn--primary" onClick={() => onConfirm(mode)}>
            <Sparkles size={14} />
            <span>{t('category.analyze.start')}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Column Editor Row ────────────────────────────────────────────────────────

function ColumnRow({
  col,
  index,
  onChange,
  onDelete,
}: {
  col: TableColumnDef;
  index: number;
  onChange: (index: number, updated: TableColumnDef) => void;
  onDelete: (index: number) => void;
}) {
  const update = (patch: Partial<TableColumnDef>) => onChange(index, { ...col, ...patch });

  return (
    <tr>
      <td class="ics-table__cell--center" style={{ width: '32px' }}>
        <span class="ics-text-muted">{index + 1}</span>
      </td>
      <td>
        <input
          type="text"
          class="ics-form-input ics-form-input--sm"
          value={col.column_name}
          title={col.column_name}
          placeholder="COLUMN_NAME"
          onInput={(e: Event) => update({ column_name: (e.target as HTMLInputElement).value.toUpperCase() })}
        />
      </td>
      <td>
        <input
          type="text"
          class="ics-form-input ics-form-input--sm"
          value={col.column_name_jp}
          title={col.column_name_jp}
          placeholder={t('category.designer.colNameJp')}
          onInput={(e: Event) => update({ column_name_jp: (e.target as HTMLInputElement).value })}
        />
      </td>
      <td style={{ minWidth: '120px' }}>
        <select
          class="ics-form-select ics-form-select--sm"
          value={col.data_type}
          onChange={(e: Event) => update({ data_type: (e.target as HTMLSelectElement).value as TableColumnDef['data_type'] })}
        >
          {DATA_TYPES.map(dt => (
            <option key={dt} value={dt}>{dt}</option>
          ))}
        </select>
      </td>
      <td style={{ width: '80px' }}>
        {(col.data_type === 'VARCHAR2') && (
          <input
            type="number"
            class="ics-form-input ics-form-input--sm"
            value={col.max_length ?? 500}
            min="1"
            max="4000"
            onInput={(e: Event) => update({ max_length: parseInt((e.target as HTMLInputElement).value, 10) || 500 })}
          />
        )}
        {(col.data_type === 'NUMBER') && (
          <input
            type="number"
            class="ics-form-input ics-form-input--sm"
            value={col.precision ?? ''}
            min="1"
            max="38"
            placeholder="精度"
            onInput={(e: Event) => {
              const v = parseInt((e.target as HTMLInputElement).value, 10);
              update({ precision: isNaN(v) ? undefined : v });
            }}
          />
        )}
      </td>
      <td class="ics-table__cell--center" style={{ width: '60px' }}>
        <input
          type="checkbox"
          checked={!col.is_nullable}
          onChange={(e: Event) => update({ is_nullable: !(e.target as HTMLInputElement).checked })}
          title="NOT NULL"
        />
      </td>
      <td class="ics-table__cell--center" style={{ width: '50px' }}>
        <input
          type="checkbox"
          checked={col.is_primary_key}
          onChange={(e: Event) => update({ is_primary_key: (e.target as HTMLInputElement).checked })}
          title="Primary Key"
        />
      </td>
      <td class="ics-table__cell--center" style={{ width: '44px' }}>
        <button
          type="button"
          class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
          onClick={() => onDelete(index)}
          title={t('common.delete')}
        >
          <Trash2 size={14} />
        </button>
      </td>
    </tr>
  );
}

// ─── Table Designer Panel ─────────────────────────────────────────────────────

function TableDesigner({
  label,
  tableName,
  columns,
  onTableNameChange,
  onColumnsChange,
}: {
  label: string;
  tableName: string;
  columns: TableColumnDef[];
  onTableNameChange: (name: string) => void;
  onColumnsChange: (cols: TableColumnDef[]) => void;
}) {
  const [showPreview, setShowPreview] = useState(false);

  const addColumn = () => {
    onColumnsChange([
      ...columns,
      {
        column_name: `COL_${columns.length + 1}`,
        column_name_jp: '',
        data_type: 'VARCHAR2',
        max_length: 500,
        is_nullable: true,
        is_primary_key: false,
      },
    ]);
  };

  const updateColumn = (index: number, updated: TableColumnDef) => {
    const newCols = [...columns];
    newCols[index] = updated;
    onColumnsChange(newCols);
  };

  const deleteColumn = (index: number) => {
    onColumnsChange(columns.filter((_, i) => i !== index));
  };

  const ddlPreview = buildDDLPreview(tableName, columns);

  return (
    <div class="ics-table-designer">
      <div class="ics-table-designer__header">
        <Table2 size={16} />
        <span>{label}</span>
      </div>
      <div class="ics-table-designer__table-name-row">
        <label class="ics-form-label">{t('category.designer.tableName')}</label>
        <input
          type="text"
          class="ics-form-input"
          value={tableName}
          placeholder="TABLE_NAME"
          onInput={(e: Event) => onTableNameChange((e.target as HTMLInputElement).value.toUpperCase())}
        />
      </div>

      <div class="ics-table-designer__grid-wrap">
        <table class="ics-table ics-table--compact">
          <thead>
            <tr>
              <th>#</th>
              <th>{t('category.designer.colName')}</th>
              <th>{t('category.designer.colNameJp')}</th>
              <th>{t('category.designer.dataType')}</th>
              <th>{t('category.designer.length')}</th>
              <th title="NOT NULL">NN</th>
              <th title="Primary Key">PK</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {columns.map((col, i) => (
              <ColumnRow
                key={i}
                col={col}
                index={i}
                onChange={updateColumn}
                onDelete={deleteColumn}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div class="ics-table-designer__actions">
        <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={addColumn}>
          <Plus size={14} />
          <span>{t('category.designer.addColumn')}</span>
        </button>
        <button
          type="button"
          class="ics-ops-btn ics-ops-btn--ghost"
          onClick={() => setShowPreview(v => !v)}
        >
          {showPreview ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          <span>{t('category.designer.sqlPreview')}</span>
        </button>
      </div>

      {showPreview && ddlPreview && (
        <div class="ics-table-designer__sql-preview">
          <pre>{ddlPreview}</pre>
        </div>
      )}
    </div>
  );
}

// ─── Image List ──────────────────────────────────────────────────────────────

function ImageList({
  fileIds,
  onPreview,
}: {
  fileIds: number[];
  onPreview: (fileId: number) => void;
}) {
  const [imgErrors, setImgErrors] = useState<Record<number, boolean>>({});

  useEffect(() => {
    setImgErrors({});
  }, [fileIds.join(',')]);

  return (
    <div class="ics-category-image-list">
      {fileIds.map((fileId, idx) => {
        const hasError = Boolean(imgErrors[fileId]);
        return (
          <button
            type="button"
            key={fileId}
            class="ics-category-image-card"
            onClick={() => onPreview(fileId)}
            title={`分析画像 ${idx + 1} をプレビュー`}
          >
            <div class="ics-category-image-card__frame">
              {hasError ? (
                <div class="ics-category-image-card__error">
                  <ImageIcon size={30} />
                  <span>画像を読み込めませんでした</span>
                </div>
              ) : (
                <img
                  src={`/studio/api/v1/files/${fileId}/preview?upload_kind=category`}
                  alt={`分析画像 ${idx + 1}`}
                  onError={() => setImgErrors(prev => ({ ...prev, [fileId]: true }))}
                />
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ─── Table Designer Inline Panel ─────────────────────────────────────────────

function TableDesignerPanel({
  analysisResult,
  onConfirm,
  onClose,
  isCreating,
}: {
  analysisResult: CategoryAnalysisResult;
  onConfirm: (req: CategoryCreateRequest) => void;
  onClose: () => void;
  isCreating: boolean;
}) {
  const [categoryName, setCategoryName] = useState(analysisResult.category_guess || '');
  const [categoryNameEn, setCategoryNameEn] = useState(analysisResult.category_guess_en || '');
  const [description, setDescription] = useState('');
  const [headerTableName, setHeaderTableName] = useState(
    (analysisResult.category_guess_en || 'slip').toUpperCase() + '_H'
  );
  const [headerColumns, setHeaderColumns] = useState<TableColumnDef[]>(analysisResult.header_columns || []);
  const [lineTableName, setLineTableName] = useState(
    analysisResult.analysis_mode === 'header_line'
      ? (analysisResult.category_guess_en || 'slip').toUpperCase() + '_L'
      : ''
  );
  const [lineColumns, setLineColumns] = useState<TableColumnDef[]>(analysisResult.line_columns || []);
  const [activeTab, setActiveTab] = useState<'header' | 'line'>('header');
  const [validationError, setValidationError] = useState('');

  const hasLine = analysisResult.analysis_mode === 'header_line';
  const fileIds = analysisResult.analyzed_file_ids ?? [];
  const [previewFileId, setPreviewFileId] = useState<number | null>(null);

  useEffect(() => {
    if (!previewFileId) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPreviewFileId(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewFileId]);

  const handleConfirm = () => {
    setValidationError('');
    if (!categoryName.trim()) {
      setValidationError(t('category.designer.errorNoCategoryName'));
      return;
    }
    if (!headerTableName.trim()) {
      setValidationError(t('category.designer.errorNoHeaderTable'));
      return;
    }
    if (headerColumns.length === 0) {
      setValidationError(t('category.designer.errorNoHeaderCols'));
      return;
    }
    for (const col of headerColumns) {
      if (!col.column_name.trim()) {
        setValidationError(t('category.designer.errorEmptyColName'));
        return;
      }
    }
    if (hasLine && lineTableName.trim() && lineColumns.length > 0) {
      for (const col of lineColumns) {
        if (!col.column_name.trim()) {
          setValidationError(t('category.designer.errorEmptyColName'));
          return;
        }
      }
    }

    const req: CategoryCreateRequest = {
      category_name: categoryName.trim(),
      category_name_en: categoryNameEn.trim(),
      description: description.trim(),
      header_table_name: headerTableName.trim().toUpperCase(),
      header_columns: headerColumns,
    };
    if (hasLine && lineTableName.trim() && lineColumns.length > 0) {
      req.line_table_name = lineTableName.trim().toUpperCase();
      req.line_columns = lineColumns;
    }
    onConfirm(req);
  };

  return (
    <section class="ics-ops-grid ics-ops-grid--one">
      <div class="ics-card ics-ops-panel">
        {/* パネルヘッダー */}
        <div class="ics-card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Database size={18} />
            <span class="oj-typography-heading-xs">{t('category.designer.title')}</span>
          </div>
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={onClose}
            disabled={isCreating}
            title={t('common.cancel')}
          >
            <X size={16} />
          </button>
        </div>

        <div class="ics-card-body ics-card-body--designer">
          {/* 2カラムレイアウト: 左=画像プレビュー、右=フォーム */}
          <div
            class="ics-category-designer-layout"
            style={{ gridTemplateColumns: fileIds.length > 0 ? '1fr 2fr' : '1fr' }}
          >
            {/* 左カラム: 画像プレビュー */}
            {fileIds.length > 0 && (
              <div class="ics-category-image-panel">
                <p class="ics-form-hint" style={{ marginBottom: '8px' }}>
                  <ImageIcon size={12} style={{ display: 'inline', marginRight: '4px' }} />
                  分析した画像（{fileIds.length}件）
                </p>
                <ImageList fileIds={fileIds} onPreview={setPreviewFileId} />
              </div>
            )}

            {/* 右カラム: フォーム */}
            <div class="ics-category-designer-right">
              {/* 伝票分類基本情報 */}
              <div class="ics-card ics-card--flat">
                <div class="ics-card-header">
                  <span class="oj-typography-heading-xs">{t('category.designer.categoryInfo')}</span>
                </div>
                <div class="ics-card-body">
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
                    <div class="ics-form-group">
                      <label class="ics-form-label">{t('category.col.name')} *</label>
                      <input
                        type="text"
                        class="ics-form-input"
                        value={categoryName}
                        onInput={(e: Event) => setCategoryName((e.target as HTMLInputElement).value)}
                        placeholder={t('category.designer.categoryNamePlaceholder')}
                      />
                    </div>
                    <div class="ics-form-group">
                      <label class="ics-form-label">{t('category.col.nameEn')}</label>
                      <input
                        type="text"
                        class="ics-form-input"
                        value={categoryNameEn}
                        onInput={(e: Event) => setCategoryNameEn((e.target as HTMLInputElement).value)}
                        placeholder="invoice"
                      />
                    </div>
                  </div>
                  <div class="ics-form-group">
                    <label class="ics-form-label">{t('category.col.description')}</label>
                    <textarea
                      class="ics-form-textarea"
                      value={description}
                      rows={2}
                      onInput={(e: Event) => setDescription((e.target as HTMLTextAreaElement).value)}
                      placeholder={t('category.designer.descriptionPlaceholder')}
                    />
                  </div>
                </div>
              </div>

              {/* テーブルデザイナー タブ */}
              {hasLine && (
                <div class="ics-tabs" style={{ marginBottom: '8px' }}>
                  <button
                    type="button"
                    class={`ics-tab ${activeTab === 'header' ? 'ics-tab--active' : ''}`}
                    onClick={() => setActiveTab('header')}
                  >
                    <FileText size={14} />
                    {t('category.designer.tabHeader')}
                  </button>
                  <button
                    type="button"
                    class={`ics-tab ${activeTab === 'line' ? 'ics-tab--active' : ''}`}
                    onClick={() => setActiveTab('line')}
                  >
                    <Table2 size={14} />
                    {t('category.designer.tabLine')}
                  </button>
                </div>
              )}

              {(!hasLine || activeTab === 'header') && (
                <TableDesigner
                  label={t('category.designer.headerTable')}
                  tableName={headerTableName}
                  columns={headerColumns}
                  onTableNameChange={setHeaderTableName}
                  onColumnsChange={setHeaderColumns}
                />
              )}

              {hasLine && activeTab === 'line' && (
                <TableDesigner
                  label={t('category.designer.lineTable')}
                  tableName={lineTableName}
                  columns={lineColumns}
                  onTableNameChange={setLineTableName}
                  onColumnsChange={setLineColumns}
                />
              )}

              {validationError && (
                <div class="ics-alert ics-alert--error">
                  {validationError}
                </div>
              )}

              {/* アクションボタン */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', paddingTop: '8px' }}>
                <button
                  type="button"
                  class="ics-ops-btn ics-ops-btn--ghost"
                  onClick={onClose}
                  disabled={isCreating}
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="button"
                  class="ics-ops-btn ics-ops-btn--primary"
                  onClick={handleConfirm}
                  disabled={isCreating}
                >
                  {isCreating ? <Loader2 size={14} class="ics-spin" /> : <Database size={14} />}
                  <span>{isCreating ? t('category.designer.creating') : t('category.designer.createTable')}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      {previewFileId && (
        <div class="ics-modal-overlay" onClick={() => setPreviewFileId(null)}>
          <div class="ics-modal ics-modal--xl ics-fileListView__previewModal" onClick={(e: Event) => e.stopPropagation()}>
            <div class="ics-modal__header">
              <h3>分析画像プレビュー</h3>
              <button
                type="button"
                class="ics-ops-btn ics-ops-btn--ghost"
                onClick={() => setPreviewFileId(null)}
                title={t('common.close')}
              >
                <X size={16} />
              </button>
            </div>
            <div class="ics-modal__body ics-fileListView__previewBody">
              <img
                src={`/studio/api/v1/files/${previewFileId}/preview?upload_kind=category`}
                alt="分析画像プレビュー"
                class="ics-fileListView__previewImage"
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

// ─── Main View ────────────────────────────────────────────────────────────────

type CategoryViewMode = 'samples' | 'management';

export function CategoryView({ mode = 'samples' }: { mode?: CategoryViewMode }) {
  const dispatch = useAppDispatch();
  const { requestConfirm, confirmToast } = useToastConfirm();
  const analysisPanelRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const initialSearchParams = getCurrentSearchParams();
  const resultFileId = new URLSearchParams(location.search).get('resultFileId');

  // Redux state
  const categories = useAppSelector(state => state.denpyo.categories);
  const isCategoriesLoading = useAppSelector(state => state.denpyo.isCategoriesLoading);
  const slipsCategoryFiles = useAppSelector(state => state.denpyo.slipsCategoryFiles);
  const slipsCategoryTotal = useAppSelector(state => state.denpyo.slipsCategoryTotal);
  const slipsCategoryPage = useAppSelector(state => state.denpyo.slipsCategoryPage);
  const slipsCategoryPageSize = useAppSelector(state => state.denpyo.slipsCategoryPageSize);
  const slipsCategoryTotalPages = useAppSelector(state => state.denpyo.slipsCategoryTotalPages);
  const isSlipsCategoryLoading = useAppSelector(state => state.denpyo.isSlipsCategoryLoading);
  const categoryAnalysisResult = useAppSelector(state => state.denpyo.categoryAnalysisResult);
  const isCategoryAnalyzing = useAppSelector(state => state.denpyo.isCategoryAnalyzing);
  const isCategoryCreating = useAppSelector(state => state.denpyo.isCategoryCreating);
  const tableBrowseResult = useAppSelector(state => state.denpyo.tableBrowseResult);
  const isTableBrowsing = useAppSelector(state => state.denpyo.isTableBrowsing);

  // Local state
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [editTarget, setEditTarget] = useState<DenpyoCategory | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [showAnalysisModeModal, setShowAnalysisModeModal] = useState(false);
  const [isBulkDeletingSlips, setIsBulkDeletingSlips] = useState(false);
  const [isBulkDeletingCategories, setIsBulkDeletingCategories] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<{ fileId: string; fileName: string } | null>(null);
  const [slipsGoToPageInput, setSlipsGoToPageInput] = useState('');
  const [slipsSortKey, setSlipsSortKey] = useState<SlipsSortKey>('uploaded_at');
  const [slipsSortDirection, setSlipsSortDirection] = useState<SortDirection>('desc');
  const [categorySortKey, setCategorySortKey] = useState<CategorySortKey>('created_at');
  const [categorySortDirection, setCategorySortDirection] = useState<SortDirection>('desc');
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [previewTab, setPreviewTab] = useState<PreviewTabType>('header');
  const [previewPage, setPreviewPage] = useState(1);
  const [previewPageSize, setPreviewPageSize] = useState(20);
  const [previewGoToPageInput, setPreviewGoToPageInput] = useState('');
  const [previewSortColumn, setPreviewSortColumn] = useState('');
  const [previewSortDirection, setPreviewSortDirection] = useState<SortDirection>('desc');
  const [isBulkDeletingPreviewRows, setIsBulkDeletingPreviewRows] = useState(false);
  const [deletingPreviewRowId, setDeletingPreviewRowId] = useState<string | null>(null);
  const [categoryPageSize, setCategoryPageSize] = useState(() => {
    if (mode !== 'management') return 20;
    const nextPageSize = readScopedNumber(initialSearchParams, CATEGORY_MANAGEMENT_QUERY_SCOPE, 'ps', 20);
    return PAGINATION_PAGE_SIZE_OPTIONS.includes(nextPageSize) ? nextPageSize : 20;
  });
  const [categoryInitialPage] = useState(() => {
    if (mode !== 'management') return 1;
    const nextPage = readScopedNumber(initialSearchParams, CATEGORY_MANAGEMENT_QUERY_SCOPE, 'p', 1);
    return nextPage >= 1 ? nextPage : 1;
  });
  const [isSamplesQueryReady, setIsSamplesQueryReady] = useState(mode !== 'samples');
  const isCategoryPageSizeInitRef = useRef(true);

  const sortedSlipsCategoryFiles = useMemo(() => {
    const factor = slipsSortDirection === 'asc' ? 1 : -1;
    return [...slipsCategoryFiles].sort((a, b) => {
      if (slipsSortKey === 'file_name') {
        return factor * a.file_name.localeCompare(b.file_name, 'ja');
      }
      if (slipsSortKey === 'file_type') {
        return factor * (a.file_type || '').localeCompare(b.file_type || '', 'ja');
      }
      if (slipsSortKey === 'file_size') {
        return factor * ((a.file_size || 0) - (b.file_size || 0));
      }
      const aTime = new Date(a.uploaded_at || '').getTime() || 0;
      const bTime = new Date(b.uploaded_at || '').getTime() || 0;
      return factor * (aTime - bTime);
    });
  }, [slipsCategoryFiles, slipsSortDirection, slipsSortKey]);

  const sortedCategories = useMemo(() => {
    const factor = categorySortDirection === 'asc' ? 1 : -1;
    return [...categories].sort((a, b) => {
      if (categorySortKey === 'category_name') {
        return factor * a.category_name.localeCompare(b.category_name, 'ja');
      }
      if (categorySortKey === 'category_name_en') {
        return factor * (a.category_name_en || '').localeCompare(b.category_name_en || '', 'en');
      }
      if (categorySortKey === 'header_table_name') {
        return factor * (a.header_table_name || '').localeCompare(b.header_table_name || '', 'en');
      }
      if (categorySortKey === 'registration_count') {
        return factor * ((a.registration_count || 0) - (b.registration_count || 0));
      }
      if (categorySortKey === 'is_active') {
        return factor * (Number(a.is_active) - Number(b.is_active));
      }
      const aTime = new Date(a.created_at || '').getTime() || 0;
      const bTime = new Date(b.created_at || '').getTime() || 0;
      return factor * (aTime - bTime);
    });
  }, [categories, categorySortDirection, categorySortKey]);

  const selectedCategory = useMemo(
    () => categories.find((cat) => cat.id === selectedCategoryId) || null,
    [categories, selectedCategoryId]
  );
  const hasLineTable = Boolean(selectedCategory?.line_table_name);
  const previewTableType: PreviewTabType = previewTab === 'line' && hasLineTable ? 'line' : 'header';
  const previewTableName = previewTableType === 'line'
    ? selectedCategory?.line_table_name || ''
    : selectedCategory?.header_table_name || '';
  const sortedPreviewRows = useMemo(() => {
    if (!tableBrowseResult?.rows || tableBrowseResult.rows.length === 0 || !previewSortColumn) {
      return tableBrowseResult?.rows || [];
    }
    const factor = previewSortDirection === 'asc' ? 1 : -1;
    return [...tableBrowseResult.rows].sort((a, b) => factor * compareValues(a[previewSortColumn], b[previewSortColumn]));
  }, [tableBrowseResult?.rows, previewSortColumn, previewSortDirection]);
  const isPreviewResultMatched = Boolean(
    tableBrowseResult &&
    previewTableName &&
    tableBrowseResult.table_name?.toUpperCase() === previewTableName.toUpperCase() &&
    tableBrowseResult.table_type === previewTableType
  );

  // 伝票分類一覧ページネーション (client-side)
  const categoryPagination = usePagination(sortedCategories, { pageSize: categoryPageSize, initialPage: categoryInitialPage });

  // 伝票分類一覧選択 (useSelection)
  const categorySelection = useSelection<DenpyoCategory>({
    getItemId: (cat) => String(cat.id),
    isSelectable: (cat) => cat.registration_count === 0,
  });
  const previewRowSelection = useSelection<Record<string, any>>({
    getItemId: (row) => {
      const raw = row.ROW_ID_META;
      return (raw === null || raw === undefined || raw === '') ? '' : String(raw);
    },
    isSelectable: (row) => {
      const raw = row.ROW_ID_META;
      return raw !== null && raw !== undefined && raw !== '';
    },
  });

  // Load data on mount
  const loadSlipsFiles = useCallback(() => {
    dispatch(fetchSlipsCategoryFiles({ page: slipsCategoryPage, pageSize: slipsCategoryPageSize }));
  }, [dispatch, slipsCategoryPage, slipsCategoryPageSize]);

  const loadCategories = useCallback(() => {
    dispatch(fetchCategories());
  }, [dispatch]);

  useEffect(() => {
    if (mode !== 'samples') return;
    const params = getCurrentSearchParams();
    const nextPage = readScopedNumber(params, CATEGORY_SAMPLES_QUERY_SCOPE, 'p', 1);
    const nextPageSize = readScopedNumber(params, CATEGORY_SAMPLES_QUERY_SCOPE, 'ps', 20);
    if (nextPage >= 1) {
      dispatch(setSlipsCategoryPage(nextPage));
    }
    if (PAGINATION_PAGE_SIZE_OPTIONS.includes(nextPageSize)) {
      dispatch(setSlipsCategoryPageSize(nextPageSize));
    }
    setIsSamplesQueryReady(true);
  }, [mode, dispatch]);

  useEffect(() => {
    if (mode === 'samples') {
      if (!isSamplesQueryReady) return;
      loadSlipsFiles();
      return;
    }
    loadCategories();
  }, [mode, isSamplesQueryReady, loadSlipsFiles, loadCategories]);

  useEffect(() => {
    if (mode !== 'samples' || !isSamplesQueryReady) return;
    const hasAnalyzingFiles = slipsCategoryFiles.some(file => file.status === 'ANALYZING');
    if (!hasAnalyzingFiles) return;
    const timer = window.setInterval(() => {
      loadSlipsFiles();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [isSamplesQueryReady, loadSlipsFiles, mode, slipsCategoryFiles]);

  useEffect(() => {
    if (mode !== 'samples' || !resultFileId) return;
    dispatch(fetchCategoryAnalysisResult(resultFileId));
  }, [dispatch, mode, resultFileId]);

  useEffect(() => {
    if (mode !== 'samples' || !isSamplesQueryReady) return;
    const params = getCurrentSearchParams();
    setScopedValue(params, CATEGORY_SAMPLES_QUERY_SCOPE, 'p', slipsCategoryPage);
    setScopedValue(params, CATEGORY_SAMPLES_QUERY_SCOPE, 'ps', slipsCategoryPageSize);
    replaceSearchParams(params);
  }, [mode, isSamplesQueryReady, slipsCategoryPage, slipsCategoryPageSize]);

  useEffect(() => {
    if (mode !== 'management') return;
    const params = getCurrentSearchParams();
    setScopedValue(params, CATEGORY_MANAGEMENT_QUERY_SCOPE, 'p', categoryPagination.currentPage);
    setScopedValue(params, CATEGORY_MANAGEMENT_QUERY_SCOPE, 'ps', categoryPageSize);
    replaceSearchParams(params);
  }, [mode, categoryPagination.currentPage, categoryPageSize]);

  // ── Slips file list pagination ────────────────────────────────────────────
  const handleSlipsPageChange = useCallback((newPage: number) => {
    dispatch(setSlipsCategoryPage(newPage));
  }, [dispatch]);

  const handleSlipsPageSizeChange = useCallback((nextPageSize: number) => {
    if (!PAGINATION_PAGE_SIZE_OPTIONS.includes(nextPageSize)) return;
    setSelectedFileIds(new Set());
    dispatch(setSlipsCategoryPageSize(nextPageSize));
  }, [dispatch]);

  const handleSlipsGoToPage = useCallback(() => {
    const target = parseInt(slipsGoToPageInput, 10);
    if (!Number.isNaN(target) && target >= 1 && target <= slipsCategoryTotalPages) {
      dispatch(setSlipsCategoryPage(target));
      setSlipsGoToPageInput('');
    }
  }, [dispatch, slipsGoToPageInput, slipsCategoryTotalPages]);

  const handleSlipsSort = useCallback((nextKey: SlipsSortKey) => {
    setSlipsSortKey(prevKey => {
      if (prevKey === nextKey) {
        setSlipsSortDirection(prevDir => (prevDir === 'asc' ? 'desc' : 'asc'));
        return prevKey;
      }
      setSlipsSortDirection('asc');
      return nextKey;
    });
  }, []);
  const handleCategorySort = useCallback((nextKey: CategorySortKey) => {
    setCategorySortKey(prevKey => {
      if (prevKey === nextKey) {
        setCategorySortDirection(prevDir => (prevDir === 'asc' ? 'desc' : 'asc'));
        return prevKey;
      }
      setCategorySortDirection('asc');
      return nextKey;
    });
  }, []);

  // 分析結果が届いたらパネルへスクロール
  useEffect(() => {
    if (categoryAnalysisResult && analysisPanelRef.current) {
      analysisPanelRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [categoryAnalysisResult]);

  // ── File selection ──────────────────────────────────────────────────────────

  const toggleFileSelect = useCallback((id: string) => {
    setSelectedFileIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < 5) {
        next.add(id);
      }
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    const targetIds = sortedSlipsCategoryFiles.slice(0, 5).map(f => String(f.file_id));
    const areAllTargetSelected =
      targetIds.length > 0 &&
      targetIds.every(id => selectedFileIds.has(id));

    if (areAllTargetSelected) {
      setSelectedFileIds(new Set());
    } else {
      setSelectedFileIds(new Set(targetIds));
    }
  }, [selectedFileIds, sortedSlipsCategoryFiles]);

  // Reset file selection when page changes
  useEffect(() => {
    setSelectedFileIds(new Set());
  }, [slipsCategoryPage]);

  // Client-side category list: reset page on page size change
  useEffect(() => {
    if (isCategoryPageSizeInitRef.current) {
      isCategoryPageSizeInitRef.current = false;
      return;
    }
    categoryPagination.reset();
    categorySelection.deselectAll();
  }, [categoryPageSize]);

  useEffect(() => {
    if (mode !== 'management') return;
    categoryPagination.reset();
    categorySelection.deselectAll();
  }, [mode, categorySortKey, categorySortDirection]);

  useEffect(() => {
    if (mode !== 'management') return;
    if (categories.length === 0) {
      setSelectedCategoryId(null);
      return;
    }
    const currentExists = selectedCategoryId !== null && categories.some((cat) => cat.id === selectedCategoryId);
    if (!currentExists) {
      setSelectedCategoryId(categories[0].id);
    }
  }, [mode, categories, selectedCategoryId]);

  useEffect(() => {
    if (previewTab === 'line' && !hasLineTable) {
      setPreviewTab('header');
    }
  }, [previewTab, hasLineTable]);

  useEffect(() => {
    setPreviewPage(1);
    setPreviewGoToPageInput('');
    setPreviewSortColumn('');
    setPreviewSortDirection('desc');
    previewRowSelection.reset();
  }, [selectedCategoryId, previewTab]);

  useEffect(() => {
    previewRowSelection.reset();
  }, [previewPage, previewTableName, previewTableType]);

  useEffect(() => {
    if (!tableBrowseResult?.columns || tableBrowseResult.columns.length === 0) {
      setPreviewSortColumn('');
      return;
    }
    if (!previewSortColumn || !tableBrowseResult.columns.includes(previewSortColumn)) {
      setPreviewSortColumn(getDefaultDataSortColumn(tableBrowseResult.columns));
      setPreviewSortDirection('desc');
    }
  }, [tableBrowseResult?.columns, previewSortColumn]);

  const requestCategoryPreview = useCallback(() => {
    if (mode !== 'management' || !selectedCategory || !previewTableName) return;
    dispatch(
      fetchTableDataByName({
        tableName: previewTableName,
        tableType: previewTableType,
        page: previewPage,
        pageSize: previewPageSize,
      })
    );
  }, [dispatch, mode, selectedCategory, previewTableName, previewTableType, previewPage, previewPageSize]);

  useEffect(() => {
    requestCategoryPreview();
  }, [requestCategoryPreview]);

  // ── AI Analysis flow ────────────────────────────────────────────────────────

  const handleAnalyzeSingleFile = useCallback((fileId: string) => {
    setSelectedFileIds(new Set([fileId]));
    setShowAnalysisModeModal(true);
  }, []);

  const handleDeleteSlipFile = useCallback((fileId: string, fileName: string) => {
    requestConfirm({
      message: t('fileList.confirmDelete', { name: fileName }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        try {
          const result = await dispatch(bulkDeleteFiles([fileId])).unwrap();
          const deletedCount = result.deleted_file_ids.length;
          if (deletedCount > 0) {
            dispatch(
              addNotification({
                type: 'success',
                message: t('fileList.notify.deleted', { name: fileName }),
                autoClose: true,
              })
            );
            setSelectedFileIds(prev => {
              const next = new Set(prev);
              next.delete(fileId);
              return next;
            });
            loadSlipsFiles();
          } else {
            dispatch(
              addNotification({
                type: 'error',
                message: t('fileList.notify.deleteFailed', { name: fileName }),
                autoClose: true,
              })
            );
          }
        } catch {
          dispatch(
            addNotification({
              type: 'error',
              message: t('fileList.notify.deleteFailed', { name: fileName }),
              autoClose: true,
            })
          );
        }
      },
    });
  }, [dispatch, loadSlipsFiles, requestConfirm]);

  const handleAnalysisModeConfirm = async (mode: 'header_only' | 'header_line') => {
    setShowAnalysisModeModal(false);
    dispatch(clearCategoryAnalysis());
    try {
      await dispatch(
        analyzeSlipsForCategory({
          fileIds: Array.from(selectedFileIds).map(id => parseInt(id, 10)),
          analysisMode: mode,
        })
      ).unwrap();
      loadSlipsFiles();
      dispatch(
        addNotification({
          type: 'success',
          message: t('category.notify.analyzeQueued'),
          autoClose: true,
        })
      );
    } catch {
      dispatch(
        addNotification({
          type: 'error',
          message: t('category.notify.analyzeFailed'),
          autoClose: true,
        })
      );
    }
  };

  const handleDesignerClose = () => {
    dispatch(clearCategoryAnalysis());
    setSelectedFileIds(new Set());
    if (mode === 'samples' && resultFileId) {
      navigate(APP_ROUTES.categorySamples, { replace: true });
    }
  };

  const handleViewCategoryResult = useCallback(async (fileId: string) => {
    try {
      await dispatch(fetchCategoryAnalysisResult(fileId)).unwrap();
      navigate(`${APP_ROUTES.categorySamples}?resultFileId=${encodeURIComponent(fileId)}`);
    } catch (e: any) {
      dispatch(
        addNotification({
          type: 'error',
          message: e?.message || t('analysis.noStoredResult'),
          autoClose: true,
        })
      );
    }
  }, [dispatch, navigate]);

  const handleCreateCategory = async (req: CategoryCreateRequest) => {
    try {
      await dispatch(createCategoryWithTables(req)).unwrap();
      dispatch(
        addNotification({
          type: 'success',
          message: t('category.notify.created', { name: req.category_name }),
          autoClose: true,
        })
      );
      dispatch(clearCategoryAnalysis());
      setSelectedFileIds(new Set());
      if (mode === 'samples' && resultFileId) {
        navigate(APP_ROUTES.categorySamples, { replace: true });
      }
    } catch {
      dispatch(
        addNotification({
          type: 'error',
          message: t('category.notify.createFailed'),
          autoClose: true,
        })
      );
    }
  };

  const handleBulkDeleteSlips = useCallback(() => {
    const targetIds = Array.from(selectedFileIds);
    if (targetIds.length === 0) return;

    requestConfirm({
      message: t('fileList.confirmBulkDelete', { count: targetIds.length }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        setIsBulkDeletingSlips(true);
        try {
          const result = await dispatch(bulkDeleteFiles(targetIds)).unwrap();
          setSelectedFileIds(new Set());
          if (result.errors.length > 0) {
            dispatch(
              addNotification({
                type: 'warning',
                message: t('fileList.notify.bulkDeletedWithErrors', {
                  deleted: result.deleted_file_ids.length,
                  errors: result.errors.length,
                }),
                autoClose: true,
              })
            );
          } else {
            dispatch(
              addNotification({
                type: 'success',
                message: t('fileList.notify.bulkDeleted', { count: result.deleted_file_ids.length }),
                autoClose: true,
              })
            );
          }
          loadSlipsFiles();
        } catch {
          dispatch(
            addNotification({
              type: 'error',
              message: t('fileList.notify.bulkDeleteFailed'),
              autoClose: true,
            })
          );
        } finally {
          setIsBulkDeletingSlips(false);
        }
      },
    });
  }, [dispatch, loadSlipsFiles, requestConfirm, selectedFileIds]);

  const handleBulkDeleteCategories = useCallback(() => {
    const selectedIds = Array.from(categorySelection.selectedIds);
    const targetCategories = categories.filter(cat => selectedIds.includes(String(cat.id)) && cat.registration_count === 0);
    if (targetCategories.length === 0) return;

    requestConfirm({
      message: t('category.confirmBulkDelete', { count: targetCategories.length }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        setIsBulkDeletingCategories(true);
        let successCount = 0;
        let failedCount = 0;
        for (const cat of targetCategories) {
          try {
            await dispatch(deleteCategory(cat.id)).unwrap();
            successCount += 1;
          } catch {
            failedCount += 1;
          }
        }
        categorySelection.deselectAll();
        if (successCount > 0 && failedCount === 0) {
          dispatch(
            addNotification({
              type: 'success',
              message: t('category.notify.bulkDeleted', { count: successCount }),
              autoClose: true,
            })
          );
        } else if (successCount > 0 && failedCount > 0) {
          dispatch(
            addNotification({
              type: 'warning',
              message: t('category.notify.bulkDeletedWithErrors', {
                deleted: successCount,
                errors: failedCount,
              }),
              autoClose: true,
            })
          );
        } else {
          dispatch(
            addNotification({
              type: 'error',
              message: t('category.notify.bulkDeleteFailed'),
              autoClose: true,
            })
          );
        }
        setIsBulkDeletingCategories(false);
      },
    });
  }, [categories, categorySelection, dispatch, requestConfirm]);

  // ── Category CRUD ───────────────────────────────────────────────────────────

  const handleToggle = useCallback(
    async (cat: DenpyoCategory) => {
      try {
        await dispatch(toggleCategoryActive(cat.id)).unwrap();
        dispatch(
          addNotification({
            type: 'success',
            message: t('category.notify.toggled', { name: cat.category_name }),
            autoClose: true,
          })
        );
      } catch {
        dispatch(
          addNotification({
            type: 'error',
            message: t('category.notify.toggleFailed'),
            autoClose: true,
          })
        );
      }
    },
    [dispatch]
  );

  const handleDelete = useCallback(
    (cat: DenpyoCategory) => {
      requestConfirm({
        message: t('category.confirmDelete', { name: cat.category_name }),
        confirmLabel: t('common.delete'),
        cancelLabel: t('common.cancel'),
        severity: 'warning',
        onConfirm: async () => {
          try {
            await dispatch(deleteCategory(cat.id)).unwrap();
            dispatch(
              addNotification({
                type: 'success',
                message: t('category.notify.deleted', { name: cat.category_name }),
                autoClose: true,
              })
            );
          } catch {
            dispatch(
              addNotification({
                type: 'error',
                message: t('category.notify.deleteFailed'),
                autoClose: true,
              })
            );
          }
        },
      });
    },
    [dispatch, requestConfirm]
  );

  const handleSave = useCallback(
    async (data: CategoryUpdateRequest) => {
      if (!editTarget) return;
      setIsSaving(true);
      try {
        await dispatch(updateCategory({ categoryId: editTarget.id, data })).unwrap();
        setEditTarget(null);
        dispatch(
          addNotification({
            type: 'success',
            message: t('category.notify.updated', { name: data.category_name }),
            autoClose: true,
          })
        );
      } catch {
        dispatch(
          addNotification({
            type: 'error',
            message: t('category.notify.updateFailed'),
            autoClose: true,
          })
        );
      } finally {
        setIsSaving(false);
      }
    },
    [dispatch, editTarget]
  );

  // ── Render ──────────────────────────────────────────────────────────────────

  const selectableOnPageIds = sortedSlipsCategoryFiles.map(file => String(file.file_id)).slice(0, 5);
  const allSelectedOnPage =
    selectableOnPageIds.length > 0 &&
    selectableOnPageIds.every(id => selectedFileIds.has(id));
  const slipsRangeStart = slipsCategoryTotal === 0 ? 0 : ((slipsCategoryPage - 1) * slipsCategoryPageSize) + 1;
  const slipsRangeEnd = slipsCategoryTotal === 0 ? 0 : Math.min(slipsCategoryPage * slipsCategoryPageSize, slipsCategoryTotal);
  const categoryRangeStart = categoryPagination.totalItems === 0 ? 0 : categoryPagination.startIndex;
  const categoryRangeEnd = categoryPagination.totalItems === 0 ? 0 : categoryPagination.endIndex;
  const previewTotalPages = tableBrowseResult?.total_pages || 1;
  const previewTotal = tableBrowseResult?.total || 0;
  const previewRangeStart = previewTotal === 0 ? 0 : ((previewPage - 1) * previewPageSize) + 1;
  const previewRangeEnd = previewTotal === 0 ? 0 : Math.min(previewPage * previewPageSize, previewTotal);
  const renderSlipsSortIcon = (key: SlipsSortKey) => {
    if (slipsSortKey !== key) return <ArrowUpDown size={13} />;
    return slipsSortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />;
  };
  const renderCategorySortIcon = (key: CategorySortKey) => {
    if (categorySortKey !== key) return <ArrowUpDown size={13} />;
    return categorySortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />;
  };
  const renderPreviewSortIcon = (column: string) => {
    if (previewSortColumn !== column) return <ArrowUpDown size={13} />;
    return previewSortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />;
  };
  const handleCategoryRowSelect = useCallback((catId: number) => {
    setSelectedCategoryId(catId);
  }, []);
  const handleCategoryRowKeyDown = useCallback((e: KeyboardEvent, catId: number) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleCategoryRowSelect(catId);
    }
  }, [handleCategoryRowSelect]);
  const handlePreviewSort = useCallback((nextColumn: string) => {
    if (!nextColumn) return;
    setPreviewSortColumn((prevColumn) => {
      if (prevColumn === nextColumn) {
        setPreviewSortDirection((prevDir) => (prevDir === 'asc' ? 'desc' : 'asc'));
        return prevColumn;
      }
      setPreviewSortDirection('asc');
      return nextColumn;
    });
  }, []);
  const handlePreviewPageSizeChange = useCallback((nextPageSize: number) => {
    if (!PAGINATION_PAGE_SIZE_OPTIONS.includes(nextPageSize)) return;
    setPreviewPageSize(nextPageSize);
    setPreviewPage(1);
    setPreviewGoToPageInput('');
  }, []);
  const handlePreviewPageChange = useCallback((nextPage: number) => {
    if (nextPage >= 1 && nextPage <= previewTotalPages) {
      setPreviewPage(nextPage);
    }
  }, [previewTotalPages]);
  const handlePreviewGoToPage = useCallback(() => {
    const target = parseInt(previewGoToPageInput, 10);
    if (!Number.isNaN(target) && target >= 1 && target <= previewTotalPages) {
      setPreviewPage(target);
      setPreviewGoToPageInput('');
    }
  }, [previewGoToPageInput, previewTotalPages]);
  const getPreviewRowId = useCallback((row: Record<string, any>): string | null => {
    const raw = row.ROW_ID_META;
    if (raw === null || raw === undefined || raw === '') return null;
    return String(raw);
  }, []);
  const handleDeletePreviewRow = useCallback((row: Record<string, any>) => {
    const rowId = getPreviewRowId(row);
    if (!rowId || !previewTableName) return;
    requestConfirm({
      message: t('search.browser.deleteRowConfirm'),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        setDeletingPreviewRowId(rowId);
        try {
          await apiPost<{ success: boolean }>('/api/v1/search/table-browser/delete-row', {
            table_name: previewTableName,
            row_id: rowId,
          });
          dispatch(addNotification({
            type: 'success',
            message: t('search.browser.deleteRowSuccess'),
          }));
          requestCategoryPreview();
        } catch {
          dispatch(addNotification({
            type: 'error',
            message: t('search.browser.deleteRowFailed'),
          }));
        } finally {
          setDeletingPreviewRowId(null);
        }
      },
    });
  }, [getPreviewRowId, previewTableName, requestConfirm, dispatch, requestCategoryPreview]);
  const handleBulkDeletePreviewRows = useCallback(() => {
    if (!previewTableName || previewRowSelection.selectedCount === 0) return;
    const targetRowIds = Array.from(previewRowSelection.selectedIds);
    requestConfirm({
      message: t('search.browser.confirmBulkDelete', { count: targetRowIds.length }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        setIsBulkDeletingPreviewRows(true);
        let deletedCount = 0;
        let failedCount = 0;
        for (const rowId of targetRowIds) {
          try {
            await apiPost<{ success: boolean }>('/api/v1/search/table-browser/delete-row', {
              table_name: previewTableName,
              row_id: rowId,
            });
            deletedCount += 1;
          } catch {
            failedCount += 1;
          }
        }
        previewRowSelection.deselectAll();
        requestCategoryPreview();
        if (deletedCount > 0 && failedCount === 0) {
          dispatch(addNotification({
            type: 'success',
            message: t('search.browser.bulkDeleteSuccess', { count: deletedCount }),
          }));
        } else if (deletedCount > 0) {
          dispatch(addNotification({
            type: 'warning',
            message: t('search.browser.bulkDeletePartial', { deleted: deletedCount, errors: failedCount }),
          }));
        } else {
          dispatch(addNotification({
            type: 'error',
            message: t('search.browser.bulkDeleteFailed'),
          }));
        }
        setIsBulkDeletingPreviewRows(false);
      },
    });
  }, [previewTableName, previewRowSelection.selectedCount, previewRowSelection.selectedIds, requestConfirm, requestCategoryPreview, dispatch, previewRowSelection]);

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      {/* Page Header */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t(mode === 'samples' ? 'category.sample.title' : 'category.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t(mode === 'samples' ? 'category.sample.subtitle' : 'category.subtitle')}</p>
          </div>
        </div>
      </section>

      {mode === 'samples' && (
        <>
          {/* ═══ Section A: SLIPS_CATEGORY ファイル一覧 ═══ */}
          <section class="ics-ops-grid ics-ops-grid--one">
            <div class="ics-card ics-ops-panel">
              <div class="ics-card-header ics-card-header--table-toolbar">
                <div class="ics-unified-table-header">
                  <span class="oj-typography-heading-xs">{t('category.slipsFiles.title')}</span>
                  <div class="ics-unified-table-toolbar">
                    <div class="ics-unified-table-toolbar__group">
                      <button
                        class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger ics-ops-btn--bulk-danger"
                        onClick={handleBulkDeleteSlips}
                        disabled={selectedFileIds.size === 0 || isBulkDeletingSlips || isSlipsCategoryLoading}
                      >
                        <Trash2 size={14} />
                        <span>{t('fileList.bulkDelete')}</span>
                      </button>
                      <span class="ics-unified-table-toolbar__meta">
                        {t('category.slipsFiles.selected', { count: selectedFileIds.size })}
                      </span>
                    </div>
                    <div class="ics-unified-table-toolbar__group ics-unified-table-toolbar__group--secondary">
                      <button
                        class="ics-ops-btn ics-ops-btn--ghost"
                        onClick={loadSlipsFiles}
                        disabled={isSlipsCategoryLoading}
                      >
                        <RefreshCw size={14} class={isSlipsCategoryLoading ? 'ics-spin' : ''} />
                        <span>{t('category.refresh')}</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <div class="ics-card-body">
                {slipsCategoryFiles.length > 0 ? (
                  <div class="ics-table-wrapper">
                    <table class="ics-table">
                      <thead>
                        <tr>
                          <th style={{ width: '40px' }}>
                            <input
                              type="checkbox"
                              checked={allSelectedOnPage}
                              ref={(el) => {
                                if (!el) return;
                                el.indeterminate = selectedFileIds.size > 0 && !allSelectedOnPage;
                              }}
                              onChange={toggleSelectAll}
                              disabled={selectableOnPageIds.length === 0}
                              aria-label={t('category.slipsFiles.selectAll')}
                              title={t('category.slipsFiles.selectAll')}
                            />
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSlipsSort('file_name')}>
                              {t('category.slipsFiles.colFileName')}
                              {renderSlipsSortIcon('file_name')}
                            </button>
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSlipsSort('file_type')}>
                              {t('category.slipsFiles.colType')}
                              {renderSlipsSortIcon('file_type')}
                            </button>
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSlipsSort('file_size')}>
                              {t('category.slipsFiles.colSize')}
                              {renderSlipsSortIcon('file_size')}
                            </button>
                          </th>
                          <th>{t('fileList.col.status')}</th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleSlipsSort('uploaded_at')}>
                              {t('category.slipsFiles.colUploadedAt')}
                              {renderSlipsSortIcon('uploaded_at')}
                            </button>
                          </th>
                          <th>{t('category.col.actions')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedSlipsCategoryFiles.map((file: DenpyoFile) => {
                          const fileId = String(file.file_id);
                          const selected = selectedFileIds.has(fileId);
                          const disabledByMax = !selected && selectedFileIds.size >= 5;
                          return (
                            <tr
                              key={fileId}
                              class={selected ? 'ics-table__row--selected' : ''}
                              onClick={(e: Event) => {
                                const target = e.target as HTMLElement;
                                if (target.closest('input[type="checkbox"]')) return;
                                if (!disabledByMax) toggleFileSelect(fileId);
                              }}
                              style={{ cursor: disabledByMax ? 'not-allowed' : 'pointer', opacity: disabledByMax ? 0.5 : 1 }}
                            >
                              <td class="ics-table__cell--center">
                                <input
                                  type="checkbox"
                                  checked={selected}
                                  onChange={() => !disabledByMax && toggleFileSelect(fileId)}
                                  disabled={disabledByMax}
                                  aria-label={t('fileList.selectFile')}
                                />
                              </td>
                              <td class="ics-fileListView__fileNameCell">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                  <FileText size={14} />
                                  <span>{file.file_name}</span>
                                </div>
                              </td>
                              <td>
                                <code class="ics-code">{file.file_type || t('upload.kind.category')}</code>
                              </td>
                              <td>{formatFileSize(file.file_size)}</td>
                              <td><FileStatusBadge status={file.status} /></td>
                              <td class="oj-text-color-secondary">{formatDateTime(file.uploaded_at)}</td>
                              <td class="ics-fileListView__actions" onClick={(e: Event) => e.stopPropagation()}>
                                <button
                                  type="button"
                                  class="ics-ops-btn ics-ops-btn--ghost"
                                  onClick={() => setPreviewTarget({ fileId, fileName: file.file_name })}
                                  title={t('fileList.previewFile')}
                                >
                                  <Eye size={14} />
                                </button>
                                <button
                                  type="button"
                                  class="ics-ops-btn ics-ops-btn--ghost"
                                  onClick={() => handleViewCategoryResult(fileId)}
                                  title={t('fileList.viewResult')}
                                  disabled={!hasViewableResult(file)}
                                >
                                  <FileSearch size={14} />
                                </button>
                                <button
                                  type="button"
                                  class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--accent"
                                  onClick={() => handleAnalyzeSingleFile(fileId)}
                                  disabled={isCategoryAnalyzing || !['UPLOADED', 'ERROR'].includes(file.status)}
                                  title={t('fileList.analyzeFile')}
                                >
                                  {isCategoryAnalyzing && selectedFileIds.has(fileId)
                                    ? <Loader2 size={14} class="ics-spin" />
                                    : <Sparkles size={14} />
                                  }
                                </button>
                                <button
                                  type="button"
                                  class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                                  onClick={() => handleDeleteSlipFile(fileId, file.file_name)}
                                  disabled={isBulkDeletingSlips || isSlipsCategoryLoading}
                                  title={t('fileList.deleteFile')}
                                >
                                  <Trash2 size={14} />
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div class="ics-empty-text">
                    {isSlipsCategoryLoading
                      ? t('common.loading')
                      : t('category.slipsFiles.noData')}
                  </div>
                )}
                <Pagination
                  currentPage={slipsCategoryPage}
                  totalPages={slipsCategoryTotalPages}
                  totalItems={slipsCategoryTotal}
                  pageSize={slipsCategoryPageSize}
                  pageSizeOptions={PAGINATION_PAGE_SIZE_OPTIONS}
                  onPageSizeChange={handleSlipsPageSizeChange}
                  goToPageInput={slipsGoToPageInput}
                  onPageChange={handleSlipsPageChange}
                  onGoToPageInputChange={setSlipsGoToPageInput}
                  onGoToPage={handleSlipsGoToPage}
                  rangeStart={slipsRangeStart}
                  rangeEnd={slipsRangeEnd}
                  showGoToPage={false}
                  isFirstPage={slipsCategoryPage <= 1 || isSlipsCategoryLoading}
                  isLastPage={slipsCategoryPage >= slipsCategoryTotalPages || isSlipsCategoryLoading}
                  position="bottom"
                  show
                  summaryPlacement="controls"
                />
              </div>
            </div>
          </section>
          {previewTarget && (
            <div class="ics-modal-overlay" onClick={() => setPreviewTarget(null)}>
              <div class="ics-modal ics-modal--xl ics-fileListView__previewModal" onClick={(e: Event) => e.stopPropagation()}>
                <div class="ics-modal__header">
                  <h3>{previewTarget.fileName || t('fileList.previewFile')}</h3>
                  <button
                    type="button"
                    class="ics-ops-btn ics-ops-btn--ghost"
                    onClick={() => setPreviewTarget(null)}
                    title={t('common.close')}
                  >
                    <X size={16} />
                  </button>
                </div>
                <div class="ics-modal__body ics-fileListView__previewBody">
                  {isImageFile(previewTarget.fileName) ? (
                    <img
                      src={`/studio/api/v1/files/${previewTarget.fileId}/preview?upload_kind=category`}
                      alt={previewTarget.fileName || t('fileList.previewFile')}
                      class="ics-fileListView__previewImage"
                    />
                  ) : (
                    <iframe
                      src={`/studio/api/v1/files/${previewTarget.fileId}/preview?upload_kind=category`}
                      title={previewTarget.fileName || t('fileList.previewFile')}
                      class="ics-fileListView__previewFrame"
                    />
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ═══ Section: AI分析結果 テーブルデザイナー（インラインパネル） ═══ */}
          {categoryAnalysisResult && (
            <div ref={analysisPanelRef}>
              <TableDesignerPanel
                analysisResult={categoryAnalysisResult}
                onConfirm={handleCreateCategory}
                onClose={handleDesignerClose}
                isCreating={isCategoryCreating}
              />
            </div>
          )}
        </>
      )}

      {/* ═══ Section B: 伝票分類一覧 ═══ */}
      {mode === 'management' && (
        <>
          <section class="ics-ops-grid ics-ops-grid--one">
            <div class="ics-card ics-ops-panel">
              <div class="ics-card-header ics-card-header--table-toolbar">
                <div class="ics-unified-table-header">
                  <span class="oj-typography-heading-xs">{t('category.tableTitle')}</span>
                  <div class="ics-unified-table-toolbar">
                    <div class="ics-unified-table-toolbar__group">
                      <button
                        type="button"
                        class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger ics-ops-btn--bulk-danger"
                        onClick={handleBulkDeleteCategories}
                        disabled={categorySelection.selectedCount === 0 || isBulkDeletingCategories || isCategoriesLoading}
                      >
                        <Trash2 size={14} />
                        <span>{t('fileList.bulkDelete')}</span>
                      </button>
                      <span class="ics-unified-table-toolbar__meta">
                        {t('category.slipsFiles.selected', { count: categorySelection.selectedCount })}
                      </span>
                    </div>
                    <div class="ics-unified-table-toolbar__group ics-unified-table-toolbar__group--secondary">
                      <button
                        class="ics-ops-btn ics-ops-btn--ghost"
                        onClick={loadCategories}
                        disabled={isCategoriesLoading}
                      >
                        <RefreshCw size={14} class={isCategoriesLoading ? 'ics-spin' : ''} />
                        <span>{t('category.refresh')}</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <div class="ics-card-body">
                {categories.length > 0 ? (
                  <div class="ics-table-wrapper">
                    <table class="ics-table">
                      <thead>
                        <tr>
                          <th style={{ width: '40px' }}>
                            <input
                              type="checkbox"
                              checked={categorySelection.isAllSelected(categoryPagination.paginatedItems)}
                              ref={(el) => {
                                if (!el) return;
                                const pageItems = categoryPagination.paginatedItems;
                                const allSelected = categorySelection.isAllSelected(pageItems);
                                const hasSelectedOnPage = pageItems.some(cat => categorySelection.isSelected(String(cat.id)));
                                el.indeterminate = !allSelected && hasSelectedOnPage;
                              }}
                              onChange={() => {
                                if (categorySelection.isAllSelected(categoryPagination.paginatedItems)) {
                                  categorySelection.deselectAll();
                                } else {
                                  categorySelection.selectAll(categoryPagination.paginatedItems);
                                }
                              }}
                              aria-label={t('common.selectAll')}
                            />
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleCategorySort('category_name')}>
                              {t('category.col.name')}
                              {renderCategorySortIcon('category_name')}
                            </button>
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleCategorySort('category_name_en')}>
                              {t('category.col.nameEn')}
                              {renderCategorySortIcon('category_name_en')}
                            </button>
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleCategorySort('header_table_name')}>
                              {t('category.col.headerTable')}
                              {renderCategorySortIcon('header_table_name')}
                            </button>
                          </th>
                          <th>{t('category.col.lineTable')}</th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleCategorySort('registration_count')}>
                              {t('category.col.registrations')}
                              {renderCategorySortIcon('registration_count')}
                            </button>
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleCategorySort('is_active')}>
                              {t('category.col.status')}
                              {renderCategorySortIcon('is_active')}
                            </button>
                          </th>
                          <th>
                            <button type="button" class="ics-fileListView__sortBtn" onClick={() => handleCategorySort('created_at')}>
                              {t('category.col.createdAt')}
                              {renderCategorySortIcon('created_at')}
                            </button>
                          </th>
                          <th>{t('category.col.actions')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {categoryPagination.paginatedItems.map(cat => (
                          <tr
                            key={cat.id}
                            role="button"
                            tabIndex={0}
                            class={`${cat.is_active ? '' : 'ics-table__row--inactive'} ${selectedCategoryId === cat.id ? 'ics-table-row--selected' : ''} ${categorySelection.isSelected(String(cat.id)) ? 'ics-table__row--selected' : ''}`}
                            onClick={() => handleCategoryRowSelect(cat.id)}
                            onKeyDown={(e) => handleCategoryRowKeyDown(e, cat.id)}
                          >
                            <td class="ics-table__cell--center">
                              <input
                                type="checkbox"
                                checked={categorySelection.isSelected(String(cat.id))}
                                onChange={() => categorySelection.toggle(String(cat.id))}
                                onClick={(e: Event) => e.stopPropagation()}
                                disabled={cat.registration_count > 0}
                                aria-label={t('common.selectAll')}
                              />
                            </td>
                            <td class="ics-table__cell--name">{cat.category_name}</td>
                            <td class="oj-text-color-secondary">{cat.category_name_en || '--'}</td>
                            <td>
                              <code class="ics-code">{cat.header_table_name}</code>
                            </td>
                            <td>
                              {cat.line_table_name ? (
                                <code class="ics-code">{cat.line_table_name}</code>
                              ) : (
                                '--'
                              )}
                            </td>
                            <td>{cat.registration_count}</td>
                            <td class="ics-table__cell--center">
                              <StatusBadge
                                variant={cat.is_active ? 'success' : 'inactive'}
                                icon={cat.is_active ? CheckCircle2 : MinusCircle}
                              >
                                {cat.is_active
                                  ? t('category.status.active')
                                  : t('category.status.inactive')}
                              </StatusBadge>
                            </td>
                            <td class="oj-text-color-secondary">{formatDateTime(cat.created_at)}</td>
                            <td class="ics-fileListView__actions" onClick={(e: Event) => e.stopPropagation()}>
                              <button
                                type="button"
                                class="ics-ops-btn ics-ops-btn--ghost"
                                onClick={() => handleToggle(cat)}
                                title={
                                  cat.is_active
                                    ? t('category.action.deactivate')
                                    : t('category.action.activate')
                                }
                              >
                                {cat.is_active ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
                              </button>
                              <button
                                type="button"
                                class="ics-ops-btn ics-ops-btn--ghost"
                                onClick={() => setEditTarget(cat)}
                                title={t('category.action.edit')}
                              >
                                <Pencil size={14} />
                              </button>
                              <button
                                type="button"
                                class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                                onClick={() => handleDelete(cat)}
                                disabled={cat.registration_count > 0}
                                title={
                                  cat.registration_count > 0
                                    ? t('category.cannotDelete')
                                    : t('category.action.delete')
                                }
                              >
                                <Trash2 size={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div class="ics-empty-text">
                    {isCategoriesLoading ? t('common.loading') : t('category.noData')}
                  </div>
                )}
                <Pagination
                  currentPage={categoryPagination.currentPage}
                  totalPages={categoryPagination.totalPages}
                  totalItems={categoryPagination.totalItems}
                  pageSize={categoryPageSize}
                  pageSizeOptions={PAGINATION_PAGE_SIZE_OPTIONS}
                  onPageSizeChange={setCategoryPageSize}
                  goToPageInput={categoryPagination.goToPageInput}
                  onPageChange={categoryPagination.goToPage}
                  onGoToPageInputChange={categoryPagination.setGoToPageInput}
                  onGoToPage={categoryPagination.handleGoToPage}
                  rangeStart={categoryRangeStart}
                  rangeEnd={categoryRangeEnd}
                  showGoToPage={false}
                  isFirstPage={categoryPagination.isFirstPage}
                  isLastPage={categoryPagination.isLastPage}
                  position="bottom"
                  show
                  summaryPlacement="controls"
                />
              </div>
            </div>
          </section>
          <section class="ics-ops-grid ics-ops-grid--one">
            <div class="ics-card ics-ops-panel">
              <div class="ics-card-header ics-card-header--table-toolbar">
                <div class="ics-unified-table-header">
                  <div class="ics-browser-title-wrap">
                    <span class="oj-typography-heading-xs">{t('category.preview.title')}</span>
                    {selectedCategory && <span class="ics-browser-table-chip">{selectedCategory.category_name}</span>}
                    {previewTableName && <span class="ics-browser-table-chip">{previewTableName}</span>}
                  </div>
                  <div class="ics-unified-table-toolbar">
                    <div class="ics-unified-table-toolbar__group">
                      <button
                        type="button"
                        class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger ics-ops-btn--bulk-danger"
                        onClick={handleBulkDeletePreviewRows}
                        disabled={previewRowSelection.selectedCount === 0 || isBulkDeletingPreviewRows || isTableBrowsing}
                      >
                        {isBulkDeletingPreviewRows ? <Loader2 size={14} class="ics-spin" /> : <Trash2 size={14} />}
                        <span>{t('fileList.bulkDelete')}</span>
                      </button>
                      <span class="ics-unified-table-toolbar__meta">
                        {t('search.browser.selectedRows', { count: previewRowSelection.selectedCount })}
                      </span>
                    </div>
                    <div class="ics-unified-table-toolbar__group ics-unified-table-toolbar__group--secondary">
                      <button
                        type="button"
                        class="ics-ops-btn ics-ops-btn--ghost"
                        onClick={requestCategoryPreview}
                        disabled={!selectedCategory || !previewTableName || isTableBrowsing}
                      >
                        {isTableBrowsing ? <Loader2 size={14} class="ics-spin" /> : <RefreshCw size={14} />}
                        <span>{t('search.browser.refresh')}</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <div class="ics-card-body">
                {selectedCategory && hasLineTable && (
                  <div class="ics-tabs" style={{ marginBottom: '12px' }}>
                    <button
                      type="button"
                      class={`ics-tab ${previewTab === 'header' ? 'ics-tab--active' : ''}`}
                      onClick={() => setPreviewTab('header')}
                    >
                      <FileText size={14} />
                      {t('search.browser.header')}
                    </button>
                    <button
                      type="button"
                      class={`ics-tab ${previewTab === 'line' ? 'ics-tab--active' : ''}`}
                      onClick={() => setPreviewTab('line')}
                    >
                      <Table2 size={14} />
                      {t('search.browser.line')}
                    </button>
                  </div>
                )}

                {!selectedCategory && (
                  <div class="ics-empty-text">{t('category.preview.noSelection')}</div>
                )}

                {selectedCategory && isTableBrowsing && (
                  <div class="ics-loading oj-sm-margin-4x-top">
                    <Loader2 size={24} class="ics-spin" />
                    <span>{t('common.loading')}</span>
                  </div>
                )}

                {selectedCategory && !isTableBrowsing && isPreviewResultMatched && tableBrowseResult && (
                  <div class="ics-browser-results">
                    {tableBrowseResult.rows && tableBrowseResult.rows.length > 0 ? (
                      <>
                        <div class="ics-table-wrapper">
                          <table class="ics-table">
                            <thead>
                              <tr>
                                <th style={{ width: '40px' }}>
                                  <input
                                    type="checkbox"
                                    checked={previewRowSelection.isAllSelected(sortedPreviewRows)}
                                    ref={(el) => {
                                      if (!el) return;
                                      const selectableRowIds = sortedPreviewRows
                                        .map((row) => row.ROW_ID_META)
                                        .filter((raw) => raw !== null && raw !== undefined && raw !== '')
                                        .map((raw) => String(raw));
                                      const allSelected = previewRowSelection.isAllSelected(sortedPreviewRows);
                                      const hasSelected = selectableRowIds.some((id) => previewRowSelection.isSelected(id));
                                      el.indeterminate = !allSelected && hasSelected;
                                    }}
                                    onChange={() => {
                                      if (previewRowSelection.isAllSelected(sortedPreviewRows)) {
                                        previewRowSelection.deselectAll();
                                      } else {
                                        previewRowSelection.selectAll(sortedPreviewRows);
                                      }
                                    }}
                                    aria-label={t('common.selectAll')}
                                  />
                                </th>
                                {tableBrowseResult.columns.map((column) => (
                                  <th key={column}>
                                    <button type="button" class="ics-fileListView__sortBtn" onClick={() => handlePreviewSort(column)}>
                                      {column}
                                      {renderPreviewSortIcon(column)}
                                    </button>
                                  </th>
                                ))}
                                <th>{t('search.browser.col.actions')}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {sortedPreviewRows.map((row, rowIndex) => {
                                const rowId = getPreviewRowId(row);
                                return (
                                  <tr key={rowIndex}>
                                    <td class="ics-table__cell--center">
                                      <input
                                        type="checkbox"
                                        checked={rowId ? previewRowSelection.isSelected(rowId) : false}
                                        onChange={() => {
                                          if (rowId) previewRowSelection.toggle(rowId);
                                        }}
                                        disabled={row.ROW_ID_META === null || row.ROW_ID_META === undefined || row.ROW_ID_META === ''}
                                      />
                                    </td>
                                    {tableBrowseResult.columns.map((column) => (
                                      <td key={column}>{formatCellValue(row[column])}</td>
                                    ))}
                                    <td class="ics-fileListView__actions">
                                      <button
                                        type="button"
                                        class="ics-ops-btn ics-ops-btn--ghost"
                                        onClick={() => handleDeletePreviewRow(row)}
                                        disabled={!rowId || deletingPreviewRowId === rowId || isBulkDeletingPreviewRows || isTableBrowsing}
                                        title={t('common.delete')}
                                      >
                                        {deletingPreviewRowId === rowId
                                          ? <Loader2 size={14} class="ics-spin" />
                                          : <Trash2 size={14} />
                                        }
                                      </button>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                        <Pagination
                          currentPage={previewPage}
                          totalPages={previewTotalPages}
                          totalItems={previewTotal}
                          pageSize={previewPageSize}
                          pageSizeOptions={PAGINATION_PAGE_SIZE_OPTIONS}
                          onPageSizeChange={handlePreviewPageSizeChange}
                          goToPageInput={previewGoToPageInput}
                          onPageChange={handlePreviewPageChange}
                          onGoToPageInputChange={setPreviewGoToPageInput}
                          onGoToPage={handlePreviewGoToPage}
                          rangeStart={previewRangeStart}
                          rangeEnd={previewRangeEnd}
                          showGoToPage={false}
                          isFirstPage={previewPage <= 1 || isTableBrowsing}
                          isLastPage={previewPage >= previewTotalPages || isTableBrowsing}
                          position="bottom"
                          show
                          summaryPlacement="controls"
                        />
                      </>
                    ) : (
                      <div class="ics-empty-text">{t('search.browser.noData')}</div>
                    )}
                  </div>
                )}

                {selectedCategory && !isTableBrowsing && !isPreviewResultMatched && (
                  <div class="ics-empty-text">{t('common.loading')}</div>
                )}
              </div>
            </div>
          </section>
        </>
      )}

      {/* ─── Modals ─── */}

      {mode === 'samples' && showAnalysisModeModal && (
        <AnalysisModeModal
          selectedCount={selectedFileIds.size}
          onConfirm={handleAnalysisModeConfirm}
          onClose={() => setShowAnalysisModeModal(false)}
        />
      )}

      {mode === 'management' && editTarget && (
        <EditModal
          category={editTarget}
          onSave={handleSave}
          onClose={() => setEditTarget(null)}
          isSaving={isSaving}
        />
      )}

      {confirmToast}
    </div>
  );
}
