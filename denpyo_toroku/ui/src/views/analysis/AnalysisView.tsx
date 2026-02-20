/**
 * AnalysisView - AI分析結果表示画面 (SCR-003)
 * 分類結果・抽出フィールド・DDL提案を表示
 */
import { h } from 'preact';
import { useState, useCallback } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { clearAnalysisResult } from '../../redux/slices/denpyoSlice';
import { setCurrentView } from '../../redux/slices/applicationSlice';
import { t } from '../../i18n';
import {
  ArrowLeft,
  Sparkles,
  Copy,
  Check,
  FileText,
  Table2,
  Code2,
  Loader2,
  Database
} from 'lucide-react';

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div class="ics-confidence-bar__wrapper">
      <div class="ics-confidence-bar">
        <div class="ics-confidence-bar__fill" style={{ width: `${pct}%` }} />
      </div>
      <span class="ics-confidence-bar__label">{pct}%</span>
    </div>
  );
}

function DDLCard({ title, ddl }: { title: string; ddl: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(ddl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [ddl]);

  return (
    <div class="ics-card ics-ops-panel">
      <div class="ics-card-header oj-flex oj-sm-align-items-center oj-sm-justify-content-space-between">
        <span class="oj-typography-heading-xs">
          <Code2 size={16} class="oj-sm-margin-2x-end" />
          {title}
        </span>
        {ddl && (
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={handleCopy}
            title={copied ? t('analysis.ddl.copied') : t('analysis.ddl.copy')}
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
            <span>{copied ? t('analysis.ddl.copied') : t('analysis.ddl.copy')}</span>
          </button>
        )}
      </div>
      <div class="ics-card-body">
        {ddl ? (
          <pre class="ics-code-block">{ddl}</pre>
        ) : (
          <div class="ics-empty-text">{t('analysis.noResult')}</div>
        )}
      </div>
    </div>
  );
}

export function AnalysisView() {
  const dispatch = useAppDispatch();
  const analysisResult = useAppSelector(state => state.denpyo.analysisResult);
  const isAnalyzing = useAppSelector(state => state.denpyo.isAnalyzing);

  const handleBack = useCallback(() => {
    dispatch(clearAnalysisResult());
    dispatch(setCurrentView('fileList'));
  }, [dispatch]);

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

  const { classification, extraction, ddl_suggestion } = analysisResult;

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

      {/* 分類結果 */}
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
            <Sparkles size={14} />
            {t('analysis.classification.confidence')}
          </div>
          <div class="ics-ops-kpiCard__value">
            <ConfidenceBar value={classification.confidence} />
          </div>
        </article>

        <article class="ics-ops-kpiCard">
          <div class="ics-ops-kpiCard__label">
            <Table2 size={14} />
            {t('analysis.classification.hasLineItems')}
          </div>
          <div class="ics-ops-kpiCard__value">
            <span class={`ics-badge ${classification.has_line_items ? 'ics-badge-success' : 'ics-badge-info'}`}>
              {classification.has_line_items ? t('analysis.classification.yes') : t('analysis.classification.no')}
            </span>
          </div>
          <div class="ics-ops-kpiCard__meta">
            {classification.has_line_items
              ? t('analysis.rawData.title', { count: extraction.line_count })
              : ''}
          </div>
        </article>
      </section>

      {/* ヘッダーフィールド */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header oj-flex oj-sm-align-items-center">
            <FileText size={18} class="oj-sm-margin-2x-end" />
            <span class="oj-typography-heading-xs">{t('analysis.headerFields.title')}</span>
          </div>
            <div class="ics-card-body">
              {extraction.header_fields.length > 0 ? (
                <div class="ics-table-wrapper">
                  <table class="ics-table">
                    <thead>
                      <tr>
                        <th>{t('analysis.table.fieldName')}</th>
                        <th>{t('analysis.table.fieldNameEn')}</th>
                        <th>{t('analysis.table.dataType')}</th>
                        <th>{t('analysis.table.maxLength')}</th>
                        <th>{t('analysis.table.sampleValue')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {extraction.header_fields.map((f, i) => (
                        <tr key={i}>
                          <td>{f.field_name}</td>
                          <td class="oj-text-color-secondary">{f.field_name_en}</td>
                          <td><span class="ics-badge ics-badge-info">{f.data_type}</span></td>
                          <td>{f.max_length ?? '--'}</td>
                          <td class="ics-table__cell--name">{f.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div class="ics-empty-text">{t('analysis.noResult')}</div>
              )}
          </div>
        </div>
      </section>

      {/* 明細フィールド */}
      {extraction.line_fields.length > 0 && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-header oj-flex oj-sm-align-items-center">
              <Table2 size={18} class="oj-sm-margin-2x-end" />
              <span class="oj-typography-heading-xs">{t('analysis.lineFields.title')}</span>
            </div>
            <div class="ics-card-body">
              <div class="ics-table-wrapper">
                <table class="ics-table">
                  <thead>
                    <tr>
                      <th>{t('analysis.table.fieldName')}</th>
                      <th>{t('analysis.table.fieldNameEn')}</th>
                      <th>{t('analysis.table.dataType')}</th>
                      <th>{t('analysis.table.maxLength')}</th>
                      <th>{t('analysis.table.sampleValue')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {extraction.line_fields.map((f, i) => (
                      <tr key={i}>
                        <td>{f.field_name}</td>
                        <td class="oj-text-color-secondary">{f.field_name_en}</td>
                        <td><span class="ics-badge ics-badge-info">{f.data_type}</span></td>
                        <td>{f.max_length ?? '--'}</td>
                        <td class="ics-table__cell--name">{f.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* 実データ (raw_lines) */}
      {extraction.raw_lines.length > 0 && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-header oj-flex oj-sm-align-items-center">
              <Table2 size={18} class="oj-sm-margin-2x-end" />
              <span class="oj-typography-heading-xs">
                {t('analysis.rawData.title', { count: extraction.line_count })}
              </span>
            </div>
            <div class="ics-card-body">
              <div class="ics-table-wrapper">
                <table class="ics-table">
                  <thead>
                    <tr>
                      {Object.keys(extraction.raw_lines[0]).map(key => (
                        <th key={key}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {extraction.raw_lines.map((row, i) => (
                      <tr key={i}>
                        {Object.values(row).map((val, j) => (
                          <td key={j}>{String(val ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* DDL提案 */}
      <section class="ics-ops-grid ics-ops-grid--two">
        <DDLCard
          title={t('analysis.ddl.headerTitle')}
          ddl={ddl_suggestion.header_ddl}
        />
        <DDLCard
          title={t('analysis.ddl.lineTitle')}
          ddl={ddl_suggestion.line_ddl}
        />
      </section>

      {/* 登録ボタン */}
      {analysisResult.status === 'ANALYZED' && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-registration-actions">
            <button
              class="ics-ops-btn ics-ops-btn--primary"
              onClick={() => dispatch(setCurrentView('registration'))}
            >
              <Database size={14} />
              <span>{t('analysis.goToRegister')}</span>
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
