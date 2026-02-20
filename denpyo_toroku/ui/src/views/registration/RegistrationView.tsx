/**
 * RegistrationView - DB登録確認画面 (SCR-004)
 * INSERTデータ確認・登録
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

  const [headerTableName, setHeaderTableName] = useState('');
  const [lineTableName, setLineTableName] = useState('');
  const [headerFields, setHeaderFields] = useState<ExtractedField[]>([]);
  const [lineRows, setLineRows] = useState<Record<string, string>[]>([]);
  const [isConfirmed, setIsConfirmed] = useState(false);
  const [validationError, setValidationError] = useState('');
  const [activeTab, setActiveTab] = useState<'header' | 'line'>('header');

  useEffect(() => {
    if (!analysisResult) return;

    const ddl = analysisResult.ddl_suggestion;
    setHeaderTableName(ddl.header_table_name || '');
    setLineTableName(ddl.line_table_name || '');
    setHeaderFields(analysisResult.extraction.header_fields || []);

    const extractedLines = (analysisResult.extraction.raw_lines || []).map(row => {
      const normalized: Record<string, string> = {};
      Object.entries(row || {}).forEach(([key, value]) => {
        normalized[key] = String(value ?? '');
      });
      return normalized;
    });

    if (extractedLines.length > 0) {
      setLineRows(extractedLines);
    } else {
      const fallbackLine: Record<string, string> = {};
      (analysisResult.extraction.line_fields || []).forEach(field => {
        const key = field.field_name_en || field.field_name;
        if (key) fallbackLine[key] = String(field.value ?? '');
      });
      setLineRows(Object.keys(fallbackLine).length > 0 ? [fallbackLine] : []);
    }

    setActiveTab('header');
    setIsConfirmed(false);
    setValidationError('');
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

  const updateHeaderFieldValue = (index: number, value: string) => {
    setHeaderFields(prev => prev.map((f, idx) => (idx === index ? { ...f, value } : f)));
  };

  const updateLineCell = (rowIndex: number, col: string, value: string) => {
    setLineRows(prev => prev.map((row, idx) => (idx === rowIndex ? { ...row, [col]: value } : row)));
  };

  const handleRegister = useCallback(async () => {
    if (!analysisResult) return;

    if (!isConfirmed) {
      setValidationError(t('registration.error.notConfirmed'));
      return;
    }
    if (!headerTableName.trim()) {
      setValidationError(t('registration.error.noHeaderTable'));
      return;
    }
    setValidationError('');

    const normalizedLineRows = lineRows
      .map(row => {
        const normalized: Record<string, string> = {};
        Object.entries(row).forEach(([key, value]) => {
          normalized[key] = String(value ?? '');
        });
        return normalized;
      })
      .filter(row => Object.keys(row).length > 0);

    const data: RegistrationRequest = {
      category_id: analysisResult.category_id,
      category_name: analysisResult.classification.category,
      category_name_en: analysisResult.ddl_suggestion.table_prefix || '',
      header_table_name: headerTableName.trim(),
      line_table_name: lineTableName.trim(),
      ai_confidence: analysisResult.classification.confidence,
      line_count: normalizedLineRows.length,
      header_fields: headerFields,
      raw_lines: normalizedLineRows,
    };

    dispatch(registerFile({ fileId: analysisResult.file_id, data }));
  }, [dispatch, analysisResult, headerTableName, lineTableName, headerFields, lineRows, isConfirmed]);

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

  const { classification } = analysisResult;
  const lineColumns = Array.from(new Set(lineRows.flatMap(row => Object.keys(row))));

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
            {headerFields.length}H / {lineRows.length}L
          </div>
          <div class="ics-ops-kpiCard__meta">
            {t('registration.lineCount', { count: lineRows.length })}
          </div>
        </article>
      </section>

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
                <input type="text" class="ics-table-name-input" value={headerTableName} disabled />
              </div>
              <div class="ics-table-name-field">
                <label class="ics-table-name-field__label">{t('registration.tableName.line')}</label>
                <input type="text" class="ics-table-name-input" value={lineTableName || '--'} disabled />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header">
            <span class="oj-typography-heading-xs">{t('registration.preview.title')}</span>
          </div>
          <div class="ics-card-body">
            <div class="ics-tabs" style={{ marginBottom: '8px' }}>
              <button
                type="button"
                class={`ics-tab ${activeTab === 'header' ? 'ics-tab--active' : ''}`}
                onClick={() => setActiveTab('header')}
              >
                <FileText size={14} />
                {t('registration.tabHeader')}
              </button>
              <button
                type="button"
                class={`ics-tab ${activeTab === 'line' ? 'ics-tab--active' : ''}`}
                onClick={() => setActiveTab('line')}
              >
                <Table2 size={14} />
                {t('registration.tabLine')}
              </button>
            </div>

            {activeTab === 'header' && (
              <div style={{ overflowX: 'auto' }}>
                <table class="ics-table ics-table--compact">
                  <thead>
                    <tr>
                      <th>{t('registration.col.no')}</th>
                      <th>{t('registration.col.fieldName')}</th>
                      <th>{t('registration.col.fieldNameEn')}</th>
                      <th>{t('registration.col.dataType')}</th>
                      <th>{t('registration.col.value')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {headerFields.map((field, i) => (
                      <tr key={i}>
                        <td>{i + 1}</td>
                        <td>{field.field_name}</td>
                        <td>{field.field_name_en || field.field_name}</td>
                        <td>{field.data_type}</td>
                        <td>
                          <input
                            type="text"
                            class="ics-table-edit-input"
                            value={String(field.value ?? '')}
                            onInput={(e: Event) => updateHeaderFieldValue(i, (e.target as HTMLInputElement).value)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {activeTab === 'line' && (
              <>
                {lineRows.length > 0 ? (
                  <div style={{ overflowX: 'auto' }}>
                    <table class="ics-table ics-table--compact">
                      <thead>
                        <tr>
                          <th>{t('registration.col.rowNo')}</th>
                          {lineColumns.map(col => (
                            <th key={col}>{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {lineRows.map((row, rowIndex) => (
                          <tr key={rowIndex}>
                            <td>{rowIndex + 1}</td>
                            {lineColumns.map(col => (
                              <td key={`${rowIndex}-${col}`}>
                                <input
                                  type="text"
                                  class="ics-table-edit-input"
                                  value={String(row[col] ?? '')}
                                  onInput={(e: Event) => updateLineCell(rowIndex, col, (e.target as HTMLInputElement).value)}
                                />
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div class="ics-empty-text">{t('registration.preview.noLineData')}</div>
                )}
              </>
            )}
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

      {(validationError || error) && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-registration-error">
            <AlertCircle size={16} />
            <span>{validationError || error}</span>
          </div>
        </section>
      )}

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
