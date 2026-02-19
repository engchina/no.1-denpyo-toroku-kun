import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';
import { Cpu, Bot, Network, Sparkles } from 'lucide-react';
import { apiGet, apiPost } from '../../utils/apiUtils';
import { useAppDispatch } from '../../redux/store';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { t } from '../../i18n';

const DEFAULT_LLM_MODEL = 'google.gemini-2.5-pro';
const DEFAULT_EMBEDDING_MODEL = 'cohere.embed-v4.0';
const DEFAULT_ENDPOINT = 'https://inference.generativeai.us-chicago-1.oci.oraclecloud.com';

interface OciModelSettingsForm {
  compartment_id: string;
  service_endpoint: string;
  llm_model_id: string;
  embedding_model_id: string;
}

interface OciSettingsSnapshot {
  settings: OciModelSettingsForm;
}

interface OciModelTestResult {
  success: boolean;
  message?: string;
  details?: {
    test_type?: 'llm' | 'embedding';
    input_text?: string;
    result_text?: string;
    embedding_dimension?: number;
    embedding_preview?: number[];
  };
}

const EMPTY_SETTINGS: OciModelSettingsForm = {
  compartment_id: '',
  service_endpoint: DEFAULT_ENDPOINT,
  llm_model_id: DEFAULT_LLM_MODEL,
  embedding_model_id: DEFAULT_EMBEDDING_MODEL
};

export function OciGenAiModelSettings() {
  const dispatch = useAppDispatch();
  const [settings, setSettings] = useState<OciModelSettingsForm>(EMPTY_SETTINGS);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isLlmTesting, setIsLlmTesting] = useState<boolean>(false);
  const [isEmbeddingTesting, setIsEmbeddingTesting] = useState<boolean>(false);
  const [llmResultText, setLlmResultText] = useState<string>('');
  const [embeddingResultText, setEmbeddingResultText] = useState<string>('');

  const applySnapshot = useCallback((snapshot: OciSettingsSnapshot) => {
    setSettings({
      ...EMPTY_SETTINGS,
      ...snapshot.settings
    });
  }, []);

  const loadSettings = useCallback(async () => {
    setIsLoading(true);
    try {
      const snapshot = await apiGet<OciSettingsSnapshot>('/api/v1/oci/settings');
      applySnapshot(snapshot);
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.settings.loadFailed')
      }));
    } finally {
      setIsLoading(false);
    }
  }, [applySnapshot, dispatch]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const updateField = useCallback(
    (field: keyof OciModelSettingsForm) => (event: Event) => {
      const target = event.target as HTMLInputElement;
      setSettings(prev => ({ ...prev, [field]: target.value }));
    },
    []
  );

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    try {
      await apiPost('/api/v1/oci/settings', settings);
      dispatch(addNotification({
        type: 'success',
        message: t('notify.settings.savedOk'),
        autoClose: true
      }));
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.settings.saveFailed')
      }));
    } finally {
      setIsSaving(false);
    }
  }, [dispatch, settings]);

  const handleModelTest = useCallback(async (testType: 'llm' | 'embedding') => {
    const isLlm = testType === 'llm';
    if (isLlm) {
      setIsLlmTesting(true);
    } else {
      setIsEmbeddingTesting(true);
    }

    try {
      const result = await apiPost<OciModelTestResult>('/api/v1/oci/model/test', {
        settings,
        test_type: testType
      });
      if (isLlm) {
        const input = result.details?.input_text || 'こんにちわ';
        const output = result.details?.result_text || '';
        setLlmResultText(`IN: ${input}\nOUT: ${output}`);
      } else {
        const input = result.details?.input_text || 'こんにちわ';
        const dimension = result.details?.embedding_dimension ?? 0;
        const preview = (result.details?.embedding_preview || []).join(', ');
        setEmbeddingResultText(`IN: ${input}\nDIM: ${dimension}\nVEC[0..7]: [${preview}]`);
      }
      dispatch(addNotification({
        type: result.success ? 'success' : 'error',
        message: result.message || (
          isLlm
            ? (result.success ? t('notify.settings.llmTestOk') : t('notify.settings.llmTestFailed'))
            : (result.success ? t('notify.settings.embeddingTestOk') : t('notify.settings.embeddingTestFailed'))
        ),
        autoClose: result.success
      }));
    } catch (err: any) {
      if (isLlm) {
        setLlmResultText('');
      } else {
        setEmbeddingResultText('');
      }
      dispatch(addNotification({
        type: 'error',
        message: err.message || (isLlm ? t('notify.settings.llmTestRequestFailed') : t('notify.settings.embeddingTestRequestFailed'))
      }));
    } finally {
      if (isLlm) {
        setIsLlmTesting(false);
      } else {
        setIsEmbeddingTesting(false);
      }
    }
  }, [dispatch, settings]);

  const isActionLocked = isLoading || isSaving || isLlmTesting || isEmbeddingTesting;
  const endpointDomain = useMemo(() => {
    try {
      return new URL(settings.service_endpoint || DEFAULT_ENDPOINT).host;
    } catch {
      return settings.service_endpoint || DEFAULT_ENDPOINT;
    }
  }, [settings.service_endpoint]);

  return (
    <div class="applicationSettingsView applicationSettingsView--enhanced applicationSettingsView--model">
      <section class="applicationSettingsView__hero">
        <div class="applicationSettingsView__heroHeader">
          <div class="genericHeading">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">{t('settings.model.title')}</h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                {t('settings.model.subtitle')}
              </p>
            </div>
          </div>

          <div class="applicationSettingsView__heroMeta">
            <Button
              label={isLoading ? t('settings.refreshing') : t('settings.refresh')}
              variant="outlined"
              size="sm"
              onAction={() => { void loadSettings(); }}
              isDisabled={isLoading || isSaving}
            />
          </div>
        </div>

        <div class="applicationSettingsView__heroMetrics applicationSettingsView__heroMetrics--model">
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">Endpoint</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">{endpointDomain}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">LLM</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">{settings.llm_model_id || DEFAULT_LLM_MODEL}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">Embedding</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">{settings.embedding_model_id || DEFAULT_EMBEDDING_MODEL}</div>
          </div>
        </div>
      </section>

      <section class="ics-card applicationSettingsView__panel oj-sm-padding-7x">
        <div class="ics-card-header applicationSettingsView__cardHeader">
          <div class="applicationSettingsView__titleWrap">
            <Cpu size={16} />
            <span class="oj-typography-heading-xs">{t('settings.model.title')}</span>
          </div>
        </div>

        <div class="ics-card-body">
          <div class="applicationSettingsView__grid applicationSettingsView__modelGrid">
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.oci.compartmentOcid')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.compartment_id}
                onInput={updateField('compartment_id')}
                placeholder="ocid1.compartment.oc1..aaaa..."
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.serviceEndpoint')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.service_endpoint}
                onInput={updateField('service_endpoint')}
                placeholder={DEFAULT_ENDPOINT}
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.llmModelId')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.llm_model_id}
                onInput={updateField('llm_model_id')}
                placeholder={DEFAULT_LLM_MODEL}
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.embeddingModelId')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.embedding_model_id}
                onInput={updateField('embedding_model_id')}
                placeholder={DEFAULT_EMBEDDING_MODEL}
              />
            </label>
          </div>

          <div class="applicationSettingsView__modelToolbar oj-sm-margin-2x-top">
            <div class="applicationSettingsView__modelToolbarGroup">
              <span class="applicationSettingsView__toolbarLabel"><Sparkles size={14} /> {t('settings.action.save')}</span>
              <Button
                label={isSaving ? t('settings.action.saving') : t('settings.action.save')}
                onAction={() => { void handleSave(); }}
                isDisabled={isActionLocked}
              />
            </div>

            <div class="applicationSettingsView__modelToolbarGroup">
              <span class="applicationSettingsView__toolbarLabel"><Bot size={14} /> Model Test</span>
              <Button
                label={isLlmTesting ? t('settings.model.action.testingLlm') : t('settings.model.action.testLlm')}
                variant="outlined"
                size="sm"
                onAction={() => { void handleModelTest('llm'); }}
                isDisabled={isActionLocked}
              />
              <Button
                label={isEmbeddingTesting ? t('settings.model.action.testingEmbedding') : t('settings.model.action.testEmbedding')}
                variant="outlined"
                size="sm"
                onAction={() => { void handleModelTest('embedding'); }}
                isDisabled={isActionLocked}
              />
            </div>
          </div>

          <div class="applicationSettingsView__modelResultGrid oj-sm-margin-2x-top">
            <label class="applicationSettingsView__field applicationSettingsView__resultPanel">
              <span class="applicationSettingsView__fieldLabel applicationSettingsView__resultTitle">
                <Bot size={14} /> {t('settings.model.testResult.llm')}
              </span>
              <textarea
                class="ics-input applicationSettingsView__resultTextArea"
                rows={4}
                readOnly
                value={llmResultText}
                placeholder={t('settings.model.testResult.placeholder')}
              />
            </label>

            <label class="applicationSettingsView__field applicationSettingsView__resultPanel">
              <span class="applicationSettingsView__fieldLabel applicationSettingsView__resultTitle">
                <Network size={14} /> {t('settings.model.testResult.embedding')}
              </span>
              <textarea
                class="ics-input applicationSettingsView__resultTextArea"
                rows={4}
                readOnly
                value={embeddingResultText}
                placeholder={t('settings.model.testResult.placeholder')}
              />
            </label>
          </div>
        </div>
      </section>
    </div>
  );
}
