import { useCallback, useEffect, useState } from 'preact/hooks';

import { MessageSquareText, RotateCcw, ChevronDown, ChevronUp } from 'lucide-react';
import { apiGet, apiPost } from '../../utils/apiUtils';
import { useAppDispatch } from '../../redux/store';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { t } from '../../i18n';
import { useToastConfirm } from '../../hooks/useToastConfirm';

const PROMPT_KEY_ORDER = [
  'ocr_output_rules',
  'structured_data_reading',
  'selection_schema_design',
  'classify_invoice',
  'extract_data_value_rules',
  'extract_text_value_rules',
  'extract_schema_completeness',
  'extract_schema_oracle_design',
  'generate_sql_requirements',
  'suggest_ddl_rules',
  'text_to_sql_constraints',
] as const;

type PromptKey = typeof PROMPT_KEY_ORDER[number];

interface PromptEntry {
  default: string;
  current: string | null;
  is_customized: boolean;
}

interface PromptSettingsData {
  prompts: Record<PromptKey, PromptEntry>;
}

export function PromptSettings() {
  const dispatch = useAppDispatch();
  const { requestConfirm, confirmToast } = useToastConfirm();

  const [promptData, setPromptData] = useState<PromptSettingsData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [savingKey, setSavingKey] = useState<PromptKey | null>(null);
  const [isResettingAll, setIsResettingAll] = useState<boolean>(false);
  const [resettingKey, setResettingKey] = useState<PromptKey | null>(null);
  const [edits, setEdits] = useState<Partial<Record<PromptKey, string>>>({});
  const [showDefault, setShowDefault] = useState<Partial<Record<PromptKey, boolean>>>({});

  const loadSettings = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await apiGet<PromptSettingsData>('/api/v1/prompts');
      setPromptData(data);
      const initialEdits: Partial<Record<PromptKey, string>> = {};
      for (const key of PROMPT_KEY_ORDER) {
        const entry = data.prompts[key];
        if (entry?.is_customized && entry.current) {
          initialEdits[key] = entry.current;
        }
      }
      setEdits(initialEdits);
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || t('notify.prompts.loadFailed') }));
    } finally {
      setIsLoading(false);
    }
  }, [dispatch]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const getPersistedValue = useCallback((key: PromptKey, entry: PromptEntry): string => {
    return entry.is_customized ? (entry.current ?? '') : '';
  }, []);

  const handleSave = useCallback(async (key: PromptKey) => {
    setSavingKey(key);
    try {
      await apiPost('/api/v1/prompts', { prompts: { [key]: edits[key] ?? null } });
      await loadSettings();
      dispatch(addNotification({ type: 'success', message: t('notify.prompts.savedOk'), autoClose: true }));
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || t('notify.prompts.saveFailed') }));
    } finally {
      setSavingKey(null);
    }
  }, [dispatch, edits, loadSettings]);

  const handleResetOne = useCallback(async (key: PromptKey) => {
    const entry = promptData?.prompts[key];
    if (!entry) return;

    const persistedValue = getPersistedValue(key, entry);
    const currentEditValue = edits[key] ?? persistedValue;
    const hasUnsavedChanges = currentEditValue !== persistedValue;

    if (!entry.is_customized) {
      if (!hasUnsavedChanges) return;
      setEdits(prev => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      dispatch(addNotification({ type: 'success', message: t('notify.prompts.resetOk'), autoClose: true }));
      return;
    }

    setResettingKey(key);
    try {
      await apiPost('/api/v1/prompts/reset', { keys: [key] });
      setEdits(prev => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      await loadSettings();
      dispatch(addNotification({ type: 'success', message: t('notify.prompts.resetOk'), autoClose: true }));
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || t('notify.prompts.resetFailed') }));
    } finally {
      setResettingKey(null);
    }
  }, [dispatch, edits, getPersistedValue, loadSettings, promptData]);

  const handleResetAll = useCallback(async () => {
    setIsResettingAll(true);
    try {
      await apiPost('/api/v1/prompts/reset', {});
      setEdits({});
      await loadSettings();
      dispatch(addNotification({ type: 'success', message: t('notify.prompts.resetOk'), autoClose: true }));
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || t('notify.prompts.resetFailed') }));
    } finally {
      setIsResettingAll(false);
    }
  }, [dispatch, loadSettings]);

  const handleResetOneClick = useCallback((key: PromptKey) => {
    requestConfirm({
      title: t('settings.prompts.action.resetOne'),
      message: t('settings.prompts.confirm.resetOne'),
      confirmLabel: t('settings.prompts.action.resetOne'),
      cancelLabel: t('common.cancel'),
      confirmVariant: 'primary',
      confirmIcon: RotateCcw,
      onConfirm: async () => {
        await handleResetOne(key);
      },
    });
  }, [handleResetOne, requestConfirm]);

  const handleResetAllClick = useCallback(() => {
    requestConfirm({
      title: t('settings.prompts.action.resetAll'),
      message: t('settings.prompts.confirm.resetAll'),
      confirmLabel: t('settings.prompts.action.resetAll'),
      cancelLabel: t('common.cancel'),
      confirmVariant: 'primary',
      confirmIcon: RotateCcw,
      onConfirm: handleResetAll,
    });
  }, [handleResetAll, requestConfirm]);

  const isBusy = isResettingAll || savingKey !== null || resettingKey !== null;

  const customizedCount = promptData
    ? PROMPT_KEY_ORDER.filter(k => promptData.prompts[k]?.is_customized).length
    : 0;

  return (
    <div class="applicationSettingsView applicationSettingsView--enhanced">
      <section class="applicationSettingsView__hero">
        <div class="applicationSettingsView__heroHeader">
          <div class="genericHeading">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">
                {t('settings.prompts.title')}
              </h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                {t('settings.prompts.subtitle')}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section class="ics-card applicationSettingsView__panel oj-sm-padding-7x">
        <div class="ics-card-header applicationSettingsView__cardHeader">
          <div class="applicationSettingsView__titleWrap">
            <MessageSquareText size={16} />
            <span class="oj-typography-heading-xs">{t('settings.prompts.title')}</span>
            {customizedCount > 0 && (
              <span class="applicationSettingsView__promptBadge applicationSettingsView__promptBadge--custom">
                {t('settings.prompts.customizedCount', { count: customizedCount } as any)}
              </span>
            )}
          </div>
          <div class="applicationSettingsView__headerActions">
            <button
              class="ics-ops-btn ics-ops-btn--ghost"
              onClick={handleResetAllClick}
              disabled={isBusy || customizedCount === 0}
            >
              <RotateCcw size={14} class={isResettingAll ? 'ics-spin' : ''} />
              <span>{isResettingAll ? t('settings.prompts.action.resetting') : t('settings.prompts.action.resetAll')}</span>
            </button>
          </div>
        </div>

        <div class="ics-card-body">
          {isLoading ? (
            <p class="applicationSettingsView__hint">{t('settings.prompts.loading')}</p>
          ) : promptData ? (
            <div class="applicationSettingsView__promptList">
              {PROMPT_KEY_ORDER.map((key) => {
                const entry = promptData.prompts[key];
                if (!entry) return null;
                const persistedValue = getPersistedValue(key, entry);
                const editValue = edits[key] ?? persistedValue;
                const isShowingDefault = !!showDefault[key];
                const isSavingThis = savingKey === key;
                const isResettingThis = resettingKey === key;
                const hasUnsavedChanges = editValue !== persistedValue;
                const canResetThis = entry.is_customized || hasUnsavedChanges;

                return (
                  <div
                    key={key}
                    class={`applicationSettingsView__promptItem${entry.is_customized ? ' applicationSettingsView__promptItem--customized' : ''}`}
                  >
                    <div class="applicationSettingsView__promptHeader">
                      <div class="applicationSettingsView__promptMeta">
                        <span class="applicationSettingsView__promptName">
                          {t(`settings.prompts.key.${key}` as Parameters<typeof t>[0])}
                        </span>
                        {entry.is_customized ? (
                          <span class="applicationSettingsView__promptBadge applicationSettingsView__promptBadge--custom">
                            {t('settings.prompts.customizedBadge')}
                          </span>
                        ) : (
                          <span class="applicationSettingsView__promptBadge applicationSettingsView__promptBadge--default">
                            {t('settings.prompts.defaultBadge')}
                          </span>
                        )}
                      </div>
                      <div class="applicationSettingsView__promptActions">
                        <button
                          class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--xs"
                          onClick={() => setShowDefault(prev => ({ ...prev, [key]: !prev[key] }))}
                        >
                          {isShowingDefault ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                          <span>{isShowingDefault ? t('settings.prompts.hideDefault') : t('settings.prompts.showDefault')}</span>
                        </button>
                        <button
                          class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--xs"
                          onClick={() => handleResetOneClick(key)}
                          disabled={isBusy || !canResetThis}
                        >
                          <RotateCcw size={12} class={isResettingThis ? 'ics-spin' : ''} />
                          <span>{t('settings.prompts.action.resetOne')}</span>
                        </button>
                      </div>
                    </div>

                    <p class="applicationSettingsView__promptDesc">
                      {t(`settings.prompts.key.${key}.desc` as Parameters<typeof t>[0])}
                    </p>

                    {isShowingDefault && (
                      <div class="applicationSettingsView__promptDefaultWrap">
                        <span class="applicationSettingsView__promptDefaultLabel">
                          {t('settings.prompts.defaultBadge')}
                        </span>
                        <pre class="applicationSettingsView__promptDefaultText">{entry.default}</pre>
                      </div>
                    )}

                    <textarea
                      class="ics-input applicationSettingsView__promptTextarea"
                      value={editValue}
                      placeholder={t('settings.prompts.placeholder')}
                      rows={6}
                      onInput={(e) => {
                        const val = (e.target as HTMLTextAreaElement).value;
                        setEdits(prev => ({ ...prev, [key]: val }));
                      }}
                    />

                    <div class="applicationSettingsView__promptSaveRow">
                      <button
                        class="ics-ops-btn ics-ops-btn--primary"
                        onClick={() => { void handleSave(key); }}
                        disabled={isBusy}
                      >
                        {isSavingThis ? t('settings.prompts.action.saving') : t('settings.prompts.action.save')}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      </section>
      {confirmToast}
    </div>
  );
}
