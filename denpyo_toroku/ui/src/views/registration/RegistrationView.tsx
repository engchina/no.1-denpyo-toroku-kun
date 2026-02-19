/**
 * RegistrationView - DB登録確認画面 (SCR-004)
 * DDL編集・テーブル作成・登録レコード作成
 */
import { h } from 'preact';
import { useState, useCallback, useEffect } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { registerFile, clearRegistrationResult, clearAnalysisResult } from '../../redux/slices/denpyoSlice';
import { setCurrentView } from '../../redux/slices/applicationSlice';
import { t } from '../../i18n';
import type { ExtractedField, RegistrationRequest } from '../../types/denpyoTypes';
import {
  ArrowLeft,
  Database,
  FileText,
  Table2,
  Sparkles,
  Loader2,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';

export function RegistrationView() {
  const dispatch = useAppDispatch();
  const analysisResult = useAppSelector(state => state.denpyo.analysisResult);
  const isRegistering = useAppSelector(state => state.denpyo.isRegistering);
  const registrationResult = useAppSelector(state => state.denpyo.registrationResult);
  const error = useAppSelector(state => state.denpyo.error);

  // ローカル編集ステート
  const [headerTableName, setHeaderTableName] = useState('');
  const [lineTableName, setLineTableName] = useState('');
  const [headerDDL, setHeaderDDL] = useState('');
  const [lineDDL, setLineDDL] = useState('');
  const [tableMode, setTableMode] = useState<'header_only' | 'header_line'>('header_line');
  const [headerFields, setHeaderFields] = useState<ExtractedField[]>([]);
  const [previewLine, setPreviewLine] = useState<Record<string, string>>({});
  const [isConfirmed, setIsConfirmed] = useState(false);
  const [validationError, setValidationError] = useState('');

  // 分析結果から初期値を設定
  useEffect(() => {
    if (analysisResult) {
      const ddl = analysisResult.ddl_suggestion;
      setHeaderTableName(ddl.header_table_name || '');
      setLineTableName(ddl.line_table_name || '');
      setHeaderDDL(ddl.header_ddl || '');
      setLineDDL(ddl.line_ddl || '');
      setHeaderFields(analysisResult.extraction.header_fields || []);
      const firstLine = (analysisResult.extraction.raw_lines || [])[0] || {};
      const normalizedLine: Record<string, string> = {};
      Object.entries(firstLine).forEach(([key, value]) => {
        normalizedLine[key] = String(value ?? '');
      });
      setPreviewLine(normalizedLine);

      const hasLineSuggestion = Boolean(
        (analysisResult.extraction.line_fields || []).length > 0 ||
        (analysisResult.extraction.raw_lines || []).length > 0 ||
        ddl.line_table_name ||
        ddl.line_ddl
      );
      setTableMode(hasLineSuggestion ? 'header_line' : 'header_only');
      setIsConfirmed(false);
      setValidationError('');
    }
  }, [analysisResult]);

  const handleBack = useCallback(() => {
    dispatch(clearRegistrationResult());
    dispatch(setCurrentView('analysis'));
  }, [dispatch]);

  const handleBackToList = useCallback(() => {
    dispatch(clearRegistrationResult());
    dispatch(clearAnalysisResult());
    dispatch(setCurrentView('fileList'));
  }, [dispatch]);

  const handleRegister = useCallback(async () => {
    if (!analysisResult) return;

    // バリデーション
    if (!isConfirmed) {
      setValidationError(t('registration.error.notConfirmed'));
      return;
    }
    if (!headerTableName.trim()) {
      setValidationError(t('registration.error.noHeaderTable'));
      return;
    }
    if (!headerDDL.trim()) {
      setValidationError(t('registration.error.noHeaderDDL'));
      return;
    }
    if (tableMode === 'header_line' && !lineTableName.trim()) {
      setValidationError(t('registration.error.noLineTable'));
      return;
    }
    if (tableMode === 'header_line' && !lineDDL.trim()) {
      setValidationError(t('registration.error.noLineDDL'));
      return;
    }
    setValidationError('');

    const useLine = tableMode === 'header_line';
    const rawLines = useLine && Object.keys(previewLine).length > 0
      ? [previewLine as Record<string, unknown>]
      : [];

    const data: RegistrationRequest = {
      category_name: analysisResult.classification.category,
      category_name_en: analysisResult.ddl_suggestion.table_prefix || '',
      header_table_name: headerTableName.trim(),
      line_table_name: useLine ? lineTableName.trim() : '',
      header_ddl: headerDDL.trim(),
      line_ddl: useLine ? lineDDL.trim() : '',
      ai_confidence: analysisResult.classification.confidence,
      line_count: rawLines.length,
      // データINSERT用
      header_fields: headerFields,
      raw_lines: rawLines,
    };

    dispatch(registerFile({ fileId: analysisResult.file_id, data }));
  }, [dispatch, analysisResult, headerTableName, lineTableName, headerDDL, lineDDL, tableMode, headerFields, previewLine, isConfirmed]);

  // 分析結果なし
  if (!analysisResult) {
    return (
      <div class="ics-dashboard ics-dashboard--enhanced">
        <section class="ics-ops-hero">
          <div class="ics-ops-hero__header">
            <div>
              <h2>{t('registration.title')}</h2>
            </div>
            <div class="ics-ops-hero__controls">
              <button class="ics-ops-btn ics-ops-btn--ghost" onClick={handleBackToList}>
                <ArrowLeft size={14} />
                <span>{t('analysis.backToList')}</span>
              </button>
            </div>
          </div>
        </section>
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-body">
              <div class="ics-empty-text">{t('registration.noAnalysis')}</div>
            </div>
          </div>
        </section>
      </div>
    );
  }

  const { classification, extraction } = analysisResult;
  const linePreviewColumns = Object.keys(previewLine);

  // 登録完了
  if (registrationResult?.success) {
    return (
      <div class="ics-dashboard ics-dashboard--enhanced">
        <section class="ics-ops-hero">
          <div class="ics-ops-hero__header">
            <div>
              <h2>
                <Database size={20} class="oj-sm-margin-2x-end" />
                {t('registration.title')}
              </h2>
            </div>
          </div>
        </section>
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-body">
              <div class="ics-registration-success">
                <CheckCircle2 size={48} class="ics-registration-success__icon" />
                <h3>{t('registration.success')}</h3>
                <p>{registrationResult.message}</p>
                <div class="ics-registration-success__details">
                  <span>Registration ID: {registrationResult.registration_id}</span>
                </div>
                <button
                  class="ics-ops-btn ics-ops-btn--primary"
                  onClick={handleBackToList}
                >
                  <ArrowLeft size={14} />
                  <span>{t('analysis.backToList')}</span>
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      {/* ヘッダー */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>
              <Database size={20} class="oj-sm-margin-2x-end" />
              {t('registration.title')}
            </h2>
            <p class="ics-ops-hero__subtitle">{t('registration.subtitle')}</p>
          </div>
          <div class="ics-ops-hero__controls">
            <button class="ics-ops-btn ics-ops-btn--ghost" onClick={handleBack}>
              <ArrowLeft size={14} />
              <span>{t('registration.backToAnalysis')}</span>
            </button>
          </div>
        </div>
        <div class="ics-ops-hero__meta">
          <span>{analysisResult.file_name}</span>
        </div>
      </section>

      {/* 分析サマリー KPI */}
      <section class="ics-ops-kpiGrid">
        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label">
            <FileText size={14} />
            {t('analysis.classification.category')}
          </div>
          <div class="ics-ops-kpiCard__value">{classification.category}</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label">
            <Sparkles size={14} />
            {t('analysis.classification.confidence')}
          </div>
          <div class="ics-ops-kpiCard__value">{Math.round(classification.confidence * 100)}%</div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label">
            <Table2 size={14} />
            {t('registration.fieldCount')}
          </div>
          <div class="ics-ops-kpiCard__value">
            {extraction.header_fields.length}H / {extraction.line_fields.length}L
          </div>
          <div class="ics-ops-kpiCard__meta">
            {tableMode === 'header_line'
              ? t('registration.lineCount', { count: extraction.line_count })
              : t('registration.headerOnlyMode')}
          </div>
        </article>
      </section>

      {/* テーブル作成方式 */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header">
            <span class="oj-typography-heading-xs">{t('registration.tableMode.title')}</span>
          </div>
          <div class="ics-card-body">
            <div class="ics-table-mode-group">
              <label class="ics-table-mode-option">
                <input
                  type="radio"
                  name="tableMode"
                  checked={tableMode === 'header_only'}
                  onChange={() => setTableMode('header_only')}
                />
                <span>{t('registration.tableMode.headerOnly')}</span>
              </label>
              <label class="ics-table-mode-option">
                <input
                  type="radio"
                  name="tableMode"
                  checked={tableMode === 'header_line'}
                  onChange={() => setTableMode('header_line')}
                />
                <span>{t('registration.tableMode.headerAndLine')}</span>
              </label>
            </div>
          </div>
        </div>
      </section>

      {/* テーブル名入力 */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <Database size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">{t('registration.tableNames')}</span>
          </div>
          <div class="ics-card-body">
            <div class="ics-table-name-grid">
              <div class="ics-table-name-field">
                <label class="ics-table-name-field__label">{t('registration.tableName.header')}</label>
                <input
                  type="text"
                  class="ics-table-name-input"
                  value={headerTableName}
                  onInput={(e) => setHeaderTableName((e.target as HTMLInputElement).value)}
                  placeholder="e.g. INV_HEADER"
                />
              </div>
              <div class="ics-table-name-field">
                <label class="ics-table-name-field__label">{t('registration.tableName.line')}</label>
                <input
                  type="text"
                  class="ics-table-name-input"
                  value={lineTableName}
                  onInput={(e) => setLineTableName((e.target as HTMLInputElement).value)}
                  placeholder="e.g. INV_LINES"
                  disabled={tableMode === 'header_only'}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 生成テーブルプレビュー（編集可） */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header">
            <span class="oj-typography-heading-xs">{t('registration.preview.title')}</span>
          </div>
          <div class="ics-card-body">
            <div class="ics-table-preview-block">
              <div class="ics-table-preview-title">{t('registration.preview.header')}</div>
              {headerFields.length > 0 ? (
                <table class="ics-table">
                  <thead>
                    <tr>
                      <th>{t('analysis.table.fieldNameEn')}</th>
                      <th>{t('analysis.table.sampleValue')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {headerFields.map((field, i) => (
                      <tr key={i}>
                        <td>{field.field_name_en || field.field_name}</td>
                        <td>
                          <input
                            type="text"
                            class="ics-table-edit-input"
                            value={String(field.value ?? '')}
                            onInput={(e) => {
                              const value = (e.target as HTMLInputElement).value;
                              setHeaderFields(prev => prev.map((f, idx) => (idx === i ? { ...f, value } : f)));
                            }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div class="ics-empty-text">{t('analysis.noResult')}</div>
              )}
            </div>

            {tableMode === 'header_line' && (
              <div class="ics-table-preview-block">
                <div class="ics-table-preview-title">{t('registration.preview.lineOneRow')}</div>
                {linePreviewColumns.length > 0 ? (
                  <div style={{ overflowX: 'auto' }}>
                    <table class="ics-table">
                      <thead>
                        <tr>
                          {linePreviewColumns.map((col) => (
                            <th key={col}>{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          {linePreviewColumns.map((col) => (
                            <td key={col}>
                              <input
                                type="text"
                                class="ics-table-edit-input"
                                value={String(previewLine[col] ?? '')}
                                onInput={(e) => {
                                  const value = (e.target as HTMLInputElement).value;
                                  setPreviewLine(prev => ({ ...prev, [col]: value }));
                                }}
                              />
                            </td>
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div class="ics-empty-text">{t('registration.preview.noLineData')}</div>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* DDLエディタ */}
      <section class="ics-ops-grid ics-ops-grid--two">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <span class="oj-typography-heading-xs">{t('registration.ddl.header')}</span>
          </div>
          <div class="ics-card-body">
            <textarea
              class="ics-ddl-editor"
              rows={16}
              value={headerDDL}
              onInput={(e) => setHeaderDDL((e.target as HTMLTextAreaElement).value)}
            />
          </div>
        </div>
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <span class="oj-typography-heading-xs">{t('registration.ddl.line')}</span>
          </div>
          <div class="ics-card-body">
            <textarea
              class="ics-ddl-editor"
              rows={16}
              value={lineDDL}
              onInput={(e) => setLineDDL((e.target as HTMLTextAreaElement).value)}
              disabled={tableMode === 'header_only'}
            />
          </div>
        </div>
      </section>

      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-registration-confirm">
          <label class="ics-table-mode-option">
            <input
              type="checkbox"
              checked={isConfirmed}
              onChange={(e) => setIsConfirmed((e.target as HTMLInputElement).checked)}
            />
            <span>{t('registration.confirm')}</span>
          </label>
        </div>
      </section>

      {/* エラー表示 */}
      {(validationError || error) && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-registration-error">
            <AlertCircle size={16} />
            <span>{validationError || error}</span>
          </div>
        </section>
      )}

      {/* アクション */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-registration-actions">
          <button
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={handleBack}
            disabled={isRegistering}
          >
            <ArrowLeft size={14} />
            <span>{t('registration.backToAnalysis')}</span>
          </button>
          <button
            class="ics-ops-btn ics-ops-btn--primary"
            onClick={handleRegister}
            disabled={isRegistering}
          >
            {isRegistering ? (
              <>
                <Loader2 size={14} class="ics-spin" />
                <span>{t('registration.executing')}</span>
              </>
            ) : (
              <>
                <Database size={14} />
                <span>{t('registration.execute')}</span>
              </>
            )}
          </button>
        </div>
      </section>
    </div>
  );
}
