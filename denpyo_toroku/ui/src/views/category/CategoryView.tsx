/**
 * CategoryView - カテゴリ管理画面 (SCR-005)
 *
 * 機能:
 *  A. SLIPS_CATEGORY ファイル一覧 + AI 分析フロー
 *     1. SLIPS_CATEGORY アップロードファイル一覧（最大5件選択）
 *     2. AI 分析モード選択 (HEADER only / HEADER+LINE)
 *     3. テーブルデザイナー UI（カラム追加/削除/編集）
 *     4. テーブル作成 → カテゴリ登録
 *  B. カテゴリ一覧 CRUD (参照・編集・削除・有効/無効)
 */
import { h, Fragment } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import {
  fetchCategories,
  updateCategory,
  toggleCategoryActive,
  deleteCategory,
  fetchSlipsCategoryFiles,
  analyzeSlipsForCategory,
  createCategoryWithTables,
  clearCategoryAnalysis,
} from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { useToastConfirm } from '../../hooks/useToastConfirm';
import { t } from '../../i18n';
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
  CheckSquare,
  Square,
  FileText,
  Table2,
} from 'lucide-react';

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

const DATA_TYPES = ['VARCHAR2', 'NUMBER', 'DATE', 'TIMESTAMP', 'CLOB'] as const;

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
  onConfirm: (mode: 'header' | 'header_line') => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<'header' | 'header_line'>('header_line');

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
                value="header_line"
                checked={mode === 'header_line'}
                onChange={() => setMode('header_line')}
              />
              <span class="ics-radio-text">
                <strong>{t('category.analyze.modeHeaderLine')}</strong>
                <span class="ics-form-hint">{t('category.analyze.modeHeaderLineDesc')}</span>
              </span>
            </label>
            <label class="ics-radio-label">
              <input
                type="radio"
                name="analysisMode"
                value="header"
                checked={mode === 'header'}
                onChange={() => setMode('header')}
              />
              <span class="ics-radio-text">
                <strong>{t('category.analyze.modeHeaderOnly')}</strong>
                <span class="ics-form-hint">{t('category.analyze.modeHeaderOnlyDesc')}</span>
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
          placeholder="COLUMN_NAME"
          onInput={(e: Event) => update({ column_name: (e.target as HTMLInputElement).value.toUpperCase() })}
        />
      </td>
      <td>
        <input
          type="text"
          class="ics-form-input ics-form-input--sm"
          value={col.column_name_jp}
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
        <strong>{label}</strong>
      </div>
      <div class="ics-form-group ics-form-group--inline">
        <label class="ics-form-label">{t('category.designer.tableName')}</label>
        <input
          type="text"
          class="ics-form-input"
          value={tableName}
          placeholder="TABLE_NAME"
          onInput={(e: Event) => onTableNameChange((e.target as HTMLInputElement).value.toUpperCase())}
          style={{ maxWidth: '300px' }}
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

// ─── Table Designer Modal ─────────────────────────────────────────────────────

function TableDesignerModal({
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
    <div class="ics-modal-overlay" onClick={onClose}>
      <div
        class="ics-modal ics-modal--xl"
        style={{ maxWidth: '900px', maxHeight: '90vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        onClick={(e: Event) => e.stopPropagation()}
      >
        <div class="ics-modal__header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Database size={18} />
            <h3>{t('category.designer.title')}</h3>
          </div>
          <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={onClose} disabled={isCreating}>
            <X size={16} />
          </button>
        </div>

        <div class="ics-modal__body" style={{ overflowY: 'auto', flex: 1 }}>
          {/* カテゴリ基本情報 */}
          <div class="ics-card ics-card--flat" style={{ marginBottom: '16px' }}>
            <div class="ics-card-header">
              <span class="oj-typography-heading-xs">{t('category.designer.categoryInfo')}</span>
            </div>
            <div class="ics-card-body">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
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
            <div class="ics-alert ics-alert--error" style={{ marginTop: '12px' }}>
              {validationError}
            </div>
          )}
        </div>

        <div class="ics-modal__footer">
          <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={onClose} disabled={isCreating}>
            {t('common.cancel')}
          </button>
          <button type="button" class="ics-ops-btn ics-ops-btn--primary" onClick={handleConfirm} disabled={isCreating}>
            {isCreating ? <Loader2 size={14} class="ics-spin" /> : <Database size={14} />}
            <span>{isCreating ? t('category.designer.creating') : t('category.designer.createTable')}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main View ────────────────────────────────────────────────────────────────

export function CategoryView() {
  const dispatch = useAppDispatch();
  const { requestConfirm, confirmToast } = useToastConfirm();

  // Redux state
  const categories = useAppSelector(state => state.denpyo.categories);
  const isCategoriesLoading = useAppSelector(state => state.denpyo.isCategoriesLoading);
  const slipsCategoryFiles = useAppSelector(state => state.denpyo.slipsCategoryFiles);
  const slipsCategoryTotal = useAppSelector(state => state.denpyo.slipsCategoryTotal);
  const isSlipsCategoryLoading = useAppSelector(state => state.denpyo.isSlipsCategoryLoading);
  const categoryAnalysisResult = useAppSelector(state => state.denpyo.categoryAnalysisResult);
  const isCategoryAnalyzing = useAppSelector(state => state.denpyo.isCategoryAnalyzing);
  const isCategoryCreating = useAppSelector(state => state.denpyo.isCategoryCreating);

  // Local state
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [editTarget, setEditTarget] = useState<DenpyoCategory | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [showAnalysisModeModal, setShowAnalysisModeModal] = useState(false);
  const [showDesignerModal, setShowDesignerModal] = useState(false);

  // Load data on mount
  const loadSlipsFiles = useCallback(() => {
    dispatch(fetchSlipsCategoryFiles({ page: 1, pageSize: 50 }));
  }, [dispatch]);

  const loadCategories = useCallback(() => {
    dispatch(fetchCategories());
  }, [dispatch]);

  useEffect(() => {
    loadSlipsFiles();
    loadCategories();
  }, [loadSlipsFiles, loadCategories]);

  // Show designer when analysis result arrives
  useEffect(() => {
    if (categoryAnalysisResult) {
      setShowDesignerModal(true);
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
    if (selectedFileIds.size === Math.min(slipsCategoryFiles.length, 5)) {
      setSelectedFileIds(new Set());
    } else {
      const ids = slipsCategoryFiles.slice(0, 5).map(f => f.file_id);
      setSelectedFileIds(new Set(ids));
    }
  }, [selectedFileIds, slipsCategoryFiles]);

  // ── AI Analysis flow ────────────────────────────────────────────────────────

  const handleAnalyzeClick = () => {
    if (selectedFileIds.size === 0) return;
    setShowAnalysisModeModal(true);
  };

  const handleAnalysisModeConfirm = async (mode: 'header' | 'header_line') => {
    setShowAnalysisModeModal(false);
    try {
      await dispatch(
        analyzeSlipsForCategory({
          fileIds: Array.from(selectedFileIds).map(id => parseInt(id, 10)),
          analysisMode: mode,
        })
      ).unwrap();
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
    setShowDesignerModal(false);
    dispatch(clearCategoryAnalysis());
    setSelectedFileIds(new Set());
  };

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
      setShowDesignerModal(false);
      dispatch(clearCategoryAnalysis());
      setSelectedFileIds(new Set());
      loadCategories();
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

  const allSelectedOnPage =
    slipsCategoryFiles.length > 0 &&
    selectedFileIds.size >= Math.min(slipsCategoryFiles.length, 5);

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      {/* Page Header */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('category.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('category.subtitle')}</p>
          </div>
        </div>
      </section>

      {/* ═══ Section A: SLIPS_CATEGORY ファイル一覧 ═══ */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header">
            <span class="oj-typography-heading-xs">{t('category.slipsFiles.title')}</span>
            <div class="ics-card-header__actions">
              <span class="ics-badge ics-badge-info">
                {t('category.slipsFiles.selected', { count: selectedFileIds.size })}
              </span>
              <button
                class="ics-ops-btn ics-ops-btn--primary"
                onClick={handleAnalyzeClick}
                disabled={selectedFileIds.size === 0 || isCategoryAnalyzing}
              >
                {isCategoryAnalyzing ? (
                  <Loader2 size={14} class="ics-spin" />
                ) : (
                  <Sparkles size={14} />
                )}
                <span>
                  {isCategoryAnalyzing
                    ? t('category.analyze.analyzing')
                    : t('category.analyze.button')}
                </span>
              </button>
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
          <div class="ics-card-body">
            <p class="ics-form-hint" style={{ marginBottom: '8px' }}>
              {t('category.slipsFiles.hint')}
            </p>
            {slipsCategoryFiles.length > 0 ? (
              <table class="ics-table">
                <thead>
                  <tr>
                    <th style={{ width: '40px' }}>
                      <button
                        type="button"
                        class="ics-ops-btn ics-ops-btn--ghost"
                        onClick={toggleSelectAll}
                        title={t('category.slipsFiles.selectAll')}
                      >
                        {allSelectedOnPage ? <CheckSquare size={16} /> : <Square size={16} />}
                      </button>
                    </th>
                    <th>{t('category.slipsFiles.colFileName')}</th>
                    <th>{t('category.slipsFiles.colType')}</th>
                    <th>{t('category.slipsFiles.colSize')}</th>
                    <th>{t('category.slipsFiles.colUploadedAt')}</th>
                  </tr>
                </thead>
                <tbody>
                  {slipsCategoryFiles.map((file: DenpyoFile) => {
                    const selected = selectedFileIds.has(file.file_id);
                    const disabledByMax = !selected && selectedFileIds.size >= 5;
                    return (
                      <tr
                        key={file.file_id}
                        class={selected ? 'ics-table__row--selected' : ''}
                        onClick={() => !disabledByMax && toggleFileSelect(file.file_id)}
                        style={{ cursor: disabledByMax ? 'not-allowed' : 'pointer', opacity: disabledByMax ? 0.5 : 1 }}
                      >
                        <td class="ics-table__cell--center">
                          {selected ? <CheckSquare size={16} /> : <Square size={16} />}
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <FileText size={14} />
                            <span class="ics-table__cell--name">{file.file_name}</span>
                          </div>
                        </td>
                        <td>
                          <code class="ics-code">{file.file_type || '--'}</code>
                        </td>
                        <td>{formatFileSize(file.file_size)}</td>
                        <td class="oj-text-color-secondary">{formatDateTime(file.uploaded_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div class="ics-empty-text">
                {isSlipsCategoryLoading
                  ? t('common.loading')
                  : t('category.slipsFiles.noData')}
              </div>
            )}
            {slipsCategoryTotal > slipsCategoryFiles.length && (
              <p class="ics-form-hint" style={{ marginTop: '8px' }}>
                {t('category.slipsFiles.showingOf', {
                  shown: slipsCategoryFiles.length,
                  total: slipsCategoryTotal,
                })}
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ═══ Section B: カテゴリ一覧 ═══ */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header">
            <span class="oj-typography-heading-xs">{t('category.tableTitle')}</span>
            <div class="ics-card-header__actions">
              <span class="ics-text-muted">{t('category.totalCategories', { count: categories.length })}</span>
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
          <div class="ics-card-body">
            {categories.length > 0 ? (
              <table class="ics-table">
                <thead>
                  <tr>
                    <th>{t('category.col.name')}</th>
                    <th>{t('category.col.nameEn')}</th>
                    <th>{t('category.col.headerTable')}</th>
                    <th>{t('category.col.lineTable')}</th>
                    <th>{t('category.col.registrations')}</th>
                    <th>{t('category.col.status')}</th>
                    <th>{t('category.col.createdAt')}</th>
                    <th>{t('category.col.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map(cat => (
                    <tr key={cat.id} class={cat.is_active ? '' : 'ics-table__row--inactive'}>
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
                      <td>
                        <span
                          class={`ics-badge ${cat.is_active ? 'ics-badge-success' : 'ics-badge-error'}`}
                        >
                          {cat.is_active
                            ? t('category.status.active')
                            : t('category.status.inactive')}
                        </span>
                      </td>
                      <td class="oj-text-color-secondary">{formatDateTime(cat.created_at)}</td>
                      <td>
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
            ) : (
              <div class="ics-empty-text">
                {isCategoriesLoading ? t('common.loading') : t('category.noData')}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ─── Modals ─── */}

      {showAnalysisModeModal && (
        <AnalysisModeModal
          selectedCount={selectedFileIds.size}
          onConfirm={handleAnalysisModeConfirm}
          onClose={() => setShowAnalysisModeModal(false)}
        />
      )}

      {showDesignerModal && categoryAnalysisResult && (
        <TableDesignerModal
          analysisResult={categoryAnalysisResult}
          onConfirm={handleCreateCategory}
          onClose={handleDesignerClose}
          isCreating={isCategoryCreating}
        />
      )}

      {editTarget && (
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
