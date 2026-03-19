/**
 * AnalysisView - AI分析結果・データ登録確認画面 (SCR-003)
 * 伝票分類のDBテーブル構造に基づいて抽出データを確認する
 */
import { useCallback, useEffect } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { clearAnalysisResult, fetchAnalysisResult } from '../../redux/slices/denpyoSlice';
import { useLocation, useNavigate } from 'react-router-dom';
import { APP_ROUTES } from '../../constants/routes';
import { t } from '../../i18n';
import type { TableColumnInfo, ExtractedField } from '../../types/denpyoTypes';
import {
  ArrowLeft,
  Sparkles,
  FileText,
  Table2,
  Loader2,
  Database,
  CheckCircle2,
} from 'lucide-react';
import { StatusBadge } from '../../components/common/StatusBadge';

/** DBカラム一覧に対し抽出フィールドをマッピングして表示するテーブル */
function ColumnDataTable({
  columns,
  fields,
  tableTitle,
}: {
  columns: TableColumnInfo[];
  fields: ExtractedField[];
  tableTitle: string;
}) {
  // field_name_en (UPPERCASE) → 抽出値 のマップ
  const valueMap = Object.fromEntries(
    fields.map(f => [(f.field_name_en || '').toUpperCase(), f])
  );

  if (columns.length === 0 && fields.length === 0) return null;

  // テーブルスキーマがない場合は抽出フィールドをそのまま表示
  const rows = columns.length > 0
    ? columns.map(col => {
      const matched = valueMap[col.column_name.toUpperCase()];
      return {
        column_name: col.column_name,
        label: col.comment || matched?.field_name || col.column_name,
        data_type: col.data_type,
        value: matched?.value ?? '',
      };
    })
    : fields.map(f => ({
      column_name: f.field_name_en || f.field_name,
      label: f.field_name,
      data_type: f.data_type,
      value: f.value ?? '',
    }));

  return (
    <section class="ics-ops-grid ics-ops-grid--one">
      <div class="ics-card ics-ops-panel">
        <div class="ics-card-header oj-flex oj-sm-align-items-center">
          <FileText size={18} class="oj-sm-margin-2x-end" />
          <span class="oj-typography-heading-xs">{tableTitle}</span>
        </div>
        <div class="ics-card-body">
          <div class="ics-table-wrapper">
            <table class="ics-table ics-table--compact">
              <thead>
                <tr>
                  <th style={{ width: '30%' }}>{t('analysis.confirm.colLabel')}</th>
                  <th style={{ width: '25%' }}>{t('analysis.confirm.colName')}</th>
                  <th style={{ width: '15%' }}>{t('analysis.table.dataType')}</th>
                  <th>{t('analysis.confirm.colValue')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td class="ics-table__cell--name">{row.label}</td>
                    <td class="oj-text-color-secondary" style={{ fontFamily: 'monospace', fontSize: '0.85em' }}>
                      {row.column_name}
                    </td>
                    <td>
                      <StatusBadge variant="info">{row.data_type}</StatusBadge>
                    </td>
                    <td>
                      {row.value !== '' ? (
                        <strong>{String(row.value)}</strong>
                      ) : (
                        <span class="oj-text-color-secondary">--</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}

/** 明細データを列コメント付きテーブルで表示 */
function LineDataTable({
  lineColumns,
  rawLines,
  lineCount,
}: {
  lineColumns: TableColumnInfo[];
  rawLines: Record<string, any>[];
  lineCount: number;
}) {
  if (rawLines.length === 0) return null;

  // カラム順序: スキーマがあればそれに従う
  const colKeys = lineColumns.length > 0
    ? lineColumns.map(c => c.column_name)
    : Array.from(new Set(rawLines.flatMap(r => Object.keys(r))));

  const commentMap = Object.fromEntries(
    lineColumns.map(c => [c.column_name, c.comment || c.column_name])
  );

  return (
    <section class="ics-ops-grid ics-ops-grid--one">
      <div class="ics-card ics-ops-panel">
        <div class="ics-card-header oj-flex oj-sm-align-items-center">
          <Table2 size={18} class="oj-sm-margin-2x-end" />
          <span class="oj-typography-heading-xs">
            {t('analysis.confirm.lineDataTitle', { count: lineCount })}
          </span>
        </div>
        <div class="ics-card-body">
          <div class="ics-table-wrapper" style={{ overflowX: 'auto' }}>
            <table class="ics-table ics-table--compact">
              <thead>
                <tr>
                  <th class="ics-table__index-col">#</th>
                  {colKeys.map(key => (
                    <th key={key} title={key}>
                      <div>{commentMap[key] || key}</div>
                      <div style={{ fontWeight: 'normal', fontSize: '0.78em', color: 'var(--oj-text-color-secondary, #888)', fontFamily: 'monospace' }}>
                        {key}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rawLines.map((row, i) => (
                  <tr key={i}>
                    <td class="ics-table__index-col oj-text-color-secondary">{i + 1}</td>
                    {colKeys.map(key => (
                      <td key={key}>{String(row[key] ?? '')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}

export function AnalysisView() {
  const dispatch = useAppDispatch();
  const analysisResult = useAppSelector(state => state.denpyo.analysisResult);
  const isAnalyzing = useAppSelector(state => state.denpyo.isAnalyzing);
  const navigate = useNavigate();
  const location = useLocation();
  const fileId = new URLSearchParams(location.search).get('fileId');

  useEffect(() => {
    if (!fileId) return;
    if (analysisResult && String(analysisResult.file_id) === String(fileId)) return;
    dispatch(fetchAnalysisResult(fileId));
  }, [analysisResult, dispatch, fileId]);

  const handleBack = useCallback(() => {
    dispatch(clearAnalysisResult());
    navigate(APP_ROUTES.fileList);
  }, [dispatch, navigate]);

  // ローディング中
  if (isAnalyzing) {
    return (
      <div class="ics-dashboard ics-dashboard--enhanced">
        <section class="ics-ops-hero">
          <div class="ics-ops-hero__header">
            <div>
              <h2>{t('analysis.title')}</h2>
            </div>
          </div>
        </section>
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-analysis-loading">
              <Loader2 size={48} class="ics-spin" />
              <p>{t('analysis.analyzing')}</p>
            </div>
          </div>
        </section>
      </div>
    );
  }

  // 結果なし
  if (!analysisResult) {
    return (
      <div class="ics-dashboard ics-dashboard--enhanced">
        <section class="ics-ops-hero">
          <div class="ics-ops-hero__header">
            <div>
              <h2>{t('analysis.title')}</h2>
            </div>
            <div class="ics-ops-hero__controls">
              <button class="ics-ops-btn ics-ops-btn--ghost" onClick={handleBack}>
                <ArrowLeft size={14} />
                <span>{t('analysis.backToList')}</span>
              </button>
            </div>
          </div>
        </section>
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-body">
              <div class="ics-empty-text">{t('analysis.noResult')}</div>
            </div>
          </div>
        </section>
      </div>
    );
  }

  const { classification, extraction, table_schema } = analysisResult;
  const headerColumns = table_schema?.header_columns ?? [];
  const lineColumns = table_schema?.line_columns ?? [];
  const headerTableName = table_schema?.header_table_name ?? analysisResult.ddl_suggestion.header_table_name;
  const lineTableName = table_schema?.line_table_name ?? analysisResult.ddl_suggestion.line_table_name;

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      {/* ヘッダー */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>
              <Sparkles size={20} class="oj-sm-margin-2x-end" />
              {t('analysis.title')}
            </h2>
            <p class="ics-ops-hero__subtitle">{t('analysis.subtitle')}</p>
          </div>
          <div class="ics-ops-hero__controls">
            <button class="ics-ops-btn ics-ops-btn--ghost" onClick={handleBack}>
              <ArrowLeft size={14} />
              <span>{t('analysis.backToList')}</span>
            </button>
          </div>
        </div>
        <div class="ics-ops-hero__meta">
          <span>{analysisResult.file_name}</span>
        </div>
      </section>

      {/* 分類・テーブル情報 KPI */}
      <section class="ics-ops-kpiGrid">
        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label">
            <FileText size={14} />
            {t('analysis.classification.category')}
          </div>
          <div class="ics-ops-kpiCard__value">{classification.category}</div>
          <div class="ics-ops-kpiCard__meta">{classification.description}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label">
            <Database size={14} />
            {t('analysis.confirm.headerTable')}
          </div>
          <div class="ics-ops-kpiCard__value" style={{ fontFamily: 'monospace', fontSize: '1rem' }}>
            {headerTableName || '--'}
          </div>
          <div class="ics-ops-kpiCard__meta">
            {t('analysis.confirm.colCount', { count: headerColumns.length || extraction.header_fields.length })}
          </div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label">
            <Table2 size={14} />
            {t('analysis.confirm.lineTable')}
          </div>
          <div class="ics-ops-kpiCard__value" style={{ fontFamily: 'monospace', fontSize: '1rem' }}>
            {lineTableName || '--'}
          </div>
          <div class="ics-ops-kpiCard__meta">
            {extraction.line_count > 0
              ? t('analysis.confirm.lineCount', { count: extraction.line_count })
              : t('analysis.classification.no')}
          </div>
        </article>
      </section>

      {/* ヘッダーデータ確認 */}
      <ColumnDataTable
        columns={headerColumns}
        fields={extraction.header_fields}
        tableTitle={t('analysis.confirm.headerDataTitle', { table: headerTableName || '' })}
      />

      {/* 明細データ確認 */}
      <LineDataTable
        lineColumns={lineColumns}
        rawLines={extraction.raw_lines}
        lineCount={extraction.line_count}
      />

      {/* 登録ボタン */}
      {analysisResult.status === 'ANALYZED' && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-registration-actions">
            <button
              class="ics-ops-btn ics-ops-btn--primary"
              onClick={() => navigate(APP_ROUTES.registration)}
            >
              <CheckCircle2 size={14} />
              <span>{t('analysis.goToRegister')}</span>
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
