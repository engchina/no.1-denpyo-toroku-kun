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
import type { RegistrationRequest } from '../../types/denpyoTypes';
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
  const [validationError, setValidationError] = useState('');

  // 分析結果から初期値を設定
  useEffect(() => {
    if (analysisResult?.ddl_suggestion) {
      const ddl = analysisResult.ddl_suggestion;
      setHeaderTableName(ddl.header_table_name || '');
      setLineTableName(ddl.line_table_name || '');
      setHeaderDDL(ddl.header_ddl || '');
      setLineDDL(ddl.line_ddl || '');
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
    if (!headerTableName.trim()) {
      setValidationError(t('registration.error.noHeaderTable'));
      return;
    }
    if (!headerDDL.trim()) {
      setValidationError(t('registration.error.noHeaderDDL'));
      return;
    }
    setValidationError('');

    const data: RegistrationRequest = {
      category_name: analysisResult.classification.category,
      category_name_en: analysisResult.ddl_suggestion.table_prefix || '',
      header_table_name: headerTableName.trim(),
      line_table_name: lineTableName.trim(),
      header_ddl: headerDDL.trim(),
      line_ddl: lineDDL.trim(),
      ai_confidence: analysisResult.classification.confidence,
      line_count: analysisResult.extraction.line_count,
      // データINSERT用
      header_fields: analysisResult.extraction.header_fields,
      raw_lines: analysisResult.extraction.raw_lines,
    };

    dispatch(registerFile({ fileId: analysisResult.file_id, data }));
  }, [dispatch, analysisResult, headerTableName, lineTableName, headerDDL, lineDDL]);

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
            {t('registration.lineCount', { count: extraction.line_count })}
          </div>
        </article>
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
                />
              </div>
            </div>
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
            />
          </div>
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
