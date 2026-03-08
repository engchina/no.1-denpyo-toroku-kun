import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';

import { Cpu, Bot, Network, Sparkles, RefreshCw } from 'lucide-react';
import { apiGet, apiPost } from '../../utils/apiUtils';
import { useAppDispatch } from '../../redux/store';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { t } from '../../i18n';

const DEFAULT_LLM_MODEL = 'xai.grok-code-fast-1';
const DEFAULT_VLM_MODEL = 'google.gemini-2.5-flash';
const DEFAULT_EMBEDDING_MODEL = 'cohere.embed-v4.0';
const DEFAULT_ENDPOINT = 'https://inference.generativeai.us-chicago-1.oci.oraclecloud.com';
const DEFAULT_SELECT_AI_REGION = 'us-chicago-1';
const DEFAULT_SELECT_AI_MODEL = 'xai.grok-code-fast-1';
const DEFAULT_SELECT_AI_MAX_TOKENS = 32768;
const DEFAULT_SELECT_AI_API_FORMAT = 'GENERIC';
const DEFAULT_OCR_ROTATION_ANGLES = '0,90,180,270';
const DEFAULT_OCR_IMAGE_MAX_EDGE_STEPS = '2400,1800,1400,1100';

interface OciModelSettingsForm {
  compartment_id: string;
  service_endpoint: string;
  llm_model_id: string;
  vlm_model_id: string;
  embedding_model_id: string;
  ocr_rotation_angles: string;
  ocr_image_max_edge_steps: string;
  ocr_empty_response_primary_max_retries: number;
  ocr_empty_response_secondary_max_retries: number;
  select_ai_enabled: boolean;
  select_ai_region: string;
  select_ai_model_id: string;
  select_ai_embedding_model_id: string;
  select_ai_endpoint_id: string;
  select_ai_max_tokens: number;
  select_ai_enforce_object_list: boolean;
  select_ai_oci_apiformat: string;
  select_ai_use_annotations: boolean;
  select_ai_use_comments: boolean;
  select_ai_use_constraints: boolean;
  llm_max_tokens: number;
  llm_temperature: number;
}

interface OciSettingsSnapshot {
  settings: OciModelSettingsForm;
}

interface OciModelTestResult {
  success: boolean;
  message?: string;
  details?: {
    test_type?: 'llm' | 'vlm' | 'embedding';
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
  vlm_model_id: DEFAULT_VLM_MODEL,
  embedding_model_id: DEFAULT_EMBEDDING_MODEL,
  ocr_rotation_angles: DEFAULT_OCR_ROTATION_ANGLES,
  ocr_image_max_edge_steps: DEFAULT_OCR_IMAGE_MAX_EDGE_STEPS,
  ocr_empty_response_primary_max_retries: 1,
  ocr_empty_response_secondary_max_retries: 0,
  select_ai_enabled: true,
  select_ai_region: DEFAULT_SELECT_AI_REGION,
  select_ai_model_id: DEFAULT_SELECT_AI_MODEL,
  select_ai_embedding_model_id: DEFAULT_EMBEDDING_MODEL,
  select_ai_endpoint_id: '',
  select_ai_max_tokens: DEFAULT_SELECT_AI_MAX_TOKENS,
  select_ai_enforce_object_list: true,
  select_ai_oci_apiformat: DEFAULT_SELECT_AI_API_FORMAT,
  select_ai_use_annotations: true,
  select_ai_use_comments: true,
  select_ai_use_constraints: true,
  llm_max_tokens: 65536,
  llm_temperature: 0.0
};

export function OciGenAiModelSettings() {
  const dispatch = useAppDispatch();
  const [settings, setSettings] = useState<OciModelSettingsForm>(EMPTY_SETTINGS);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isLlmTesting, setIsLlmTesting] = useState<boolean>(false);
  const [isVlmTesting, setIsVlmTesting] = useState<boolean>(false);
  const [isEmbeddingTesting, setIsEmbeddingTesting] = useState<boolean>(false);
  const [llmResultText, setLlmResultText] = useState<string>('');
  const [vlmResultText, setVlmResultText] = useState<string>('');
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
      const target = event.target as HTMLInputElement | HTMLSelectElement;
      setSettings(prev => {
        let val: string | number | boolean = target.value;
        if (
          field === 'llm_max_tokens'
          || field === 'llm_temperature'
          || field === 'select_ai_max_tokens'
          || field === 'ocr_empty_response_primary_max_retries'
          || field === 'ocr_empty_response_secondary_max_retries'
        ) {
          val = Number(val);
        } else if (target instanceof HTMLInputElement && target.type === 'checkbox') {
          val = target.checked;
        } else if (field === 'select_ai_oci_apiformat') {
          val = String(val).toUpperCase();
        }
        return { ...prev, [field]: val };
      });
    },
    []
  );

  const toggleSelectAiEnabled = useCallback(() => {
    setSettings(prev => ({ ...prev, select_ai_enabled: !prev.select_ai_enabled }));
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    try {
      const snapshot = await apiPost<OciSettingsSnapshot>('/api/v1/oci/settings', settings);
      applySnapshot(snapshot);
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
  }, [applySnapshot, dispatch, settings]);

  const handleModelTest = useCallback(async (testType: 'llm' | 'vlm' | 'embedding') => {
    const isLlm = testType === 'llm';
    const isVlm = testType === 'vlm';
    if (isLlm) {
      setIsLlmTesting(true);
    } else if (isVlm) {
      setIsVlmTesting(true);
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
      } else if (isVlm) {
        const input = result.details?.input_text || t('settings.model.testResult.vlmInput');
        const output = result.details?.result_text || '';
        setVlmResultText(`IN: ${input}\nOUT: ${output}`);
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
            : isVlm
              ? (result.success ? t('notify.settings.vlmTestOk') : t('notify.settings.vlmTestFailed'))
              : (result.success ? t('notify.settings.embeddingTestOk') : t('notify.settings.embeddingTestFailed'))
        ),
        autoClose: result.success
      }));
    } catch (err: any) {
      if (isLlm) {
        setLlmResultText('');
      } else if (isVlm) {
        setVlmResultText('');
      } else {
        setEmbeddingResultText('');
      }
      dispatch(addNotification({
        type: 'error',
        message: err.message || (
          isLlm
            ? t('notify.settings.llmTestRequestFailed')
            : isVlm
              ? t('notify.settings.vlmTestRequestFailed')
              : t('notify.settings.embeddingTestRequestFailed')
        )
      }));
    } finally {
      if (isLlm) {
        setIsLlmTesting(false);
      } else if (isVlm) {
        setIsVlmTesting(false);
      } else {
        setIsEmbeddingTesting(false);
      }
    }
  }, [dispatch, settings]);

  const isActionLocked = isLoading || isSaving || isLlmTesting || isVlmTesting || isEmbeddingTesting;
  const endpointDomain = useMemo(() => {
    try {
      return new URL(settings.service_endpoint || DEFAULT_ENDPOINT).host;
    } catch {
      return settings.service_endpoint || DEFAULT_ENDPOINT;
    }
  }, [settings.service_endpoint]);
  const selectAiModelSummary = settings.select_ai_model_id || DEFAULT_SELECT_AI_MODEL;
  const selectAiRegionSummary = settings.select_ai_region || DEFAULT_SELECT_AI_REGION;

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
            <div class="applicationSettingsView__heroMetricLabel">VLM</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">{settings.vlm_model_id || DEFAULT_VLM_MODEL}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">Embedding</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">{settings.embedding_model_id || DEFAULT_EMBEDDING_MODEL}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">{t('settings.model.selectAi.summaryLabel')}</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">
              {settings.select_ai_enabled ? t('settings.model.selectAi.engine.agent') : t('settings.model.selectAi.engine.direct')}
            </div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">{t('settings.model.selectAi.region')}</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">{selectAiRegionSummary}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">{t('settings.model.selectAi.modelId')}</div>
            <div class="applicationSettingsView__heroMetricValue applicationSettingsView__heroMetricValue--compact">{selectAiModelSummary}</div>
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
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.vlmModelId')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.vlm_model_id}
                onInput={updateField('vlm_model_id')}
                placeholder={DEFAULT_VLM_MODEL}
              />
            </label>
            <label class="applicationSettingsView__field applicationSettingsView__field--wide">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.embeddingModelId')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.embedding_model_id}
                onInput={updateField('embedding_model_id')}
                placeholder={DEFAULT_EMBEDDING_MODEL}
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.llmMaxTokens')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                type="number"
                min="4096"
                max="98304"
                value={settings.llm_max_tokens}
                onInput={updateField('llm_max_tokens')}
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.llmTemperature')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                type="number"
                step="0.1"
                min="0.0"
                max="1.0"
                value={settings.llm_temperature}
                onInput={updateField('llm_temperature')}
              />
            </label>

            <div class="applicationSettingsView__field applicationSettingsView__field--wide applicationSettingsView__field--section">
              <div class="applicationSettingsView__fieldLabel">{t('settings.model.ocr.title')}</div>
              <p class="applicationSettingsView__hint applicationSettingsView__hint--flush">
                {t('settings.model.ocr.subtitle')}
              </p>
            </div>

            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.ocr.primaryRetries')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                type="number"
                min="0"
                max="10"
                value={settings.ocr_empty_response_primary_max_retries}
                onInput={updateField('ocr_empty_response_primary_max_retries')}
              />
              <span class="applicationSettingsView__hint applicationSettingsView__hint--flush">
                {t('settings.model.ocr.primaryRetriesHint')}
              </span>
            </label>

            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.ocr.secondaryRetries')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                type="number"
                min="0"
                max="10"
                value={settings.ocr_empty_response_secondary_max_retries}
                onInput={updateField('ocr_empty_response_secondary_max_retries')}
              />
              <span class="applicationSettingsView__hint applicationSettingsView__hint--flush">
                {t('settings.model.ocr.secondaryRetriesHint')}
              </span>
            </label>

            <label class="applicationSettingsView__field applicationSettingsView__field--wide">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.ocr.rotationAngles')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.ocr_rotation_angles}
                onInput={updateField('ocr_rotation_angles')}
                placeholder={DEFAULT_OCR_ROTATION_ANGLES}
              />
              <span class="applicationSettingsView__hint applicationSettingsView__hint--flush">
                {t('settings.model.ocr.rotationAnglesHint')}
              </span>
            </label>

            <label class="applicationSettingsView__field applicationSettingsView__field--wide">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.ocr.imageMaxEdgeSteps')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.ocr_image_max_edge_steps}
                onInput={updateField('ocr_image_max_edge_steps')}
                placeholder={DEFAULT_OCR_IMAGE_MAX_EDGE_STEPS}
              />
              <span class="applicationSettingsView__hint applicationSettingsView__hint--flush">
                {t('settings.model.ocr.imageMaxEdgeStepsHint')}
              </span>
            </label>

            <div class="applicationSettingsView__field applicationSettingsView__field--wide applicationSettingsView__field--section">
              <div class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.title')}</div>
              <p class="applicationSettingsView__hint applicationSettingsView__hint--flush">
                {t('settings.model.selectAi.subtitle')}
              </p>
            </div>

            <section class="applicationSettingsView__field applicationSettingsView__field--wide applicationSettingsView__switchRow">
              <span
                class={`applicationSettingsView__toggleOption ${!settings.select_ai_enabled ? 'is-active' : ''}`}
              >
                {t('settings.model.selectAi.engine.direct')}
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={settings.select_ai_enabled}
                aria-label={t('settings.model.selectAi.enable')}
                class={`applicationSettingsView__toggleSwitch ${settings.select_ai_enabled ? 'is-on' : ''}`}
                onClick={toggleSelectAiEnabled}
              >
                <span class="applicationSettingsView__toggleSwitchTrack">
                  <span class="applicationSettingsView__toggleSwitchThumb" />
                </span>
              </button>
              <span
                class={`applicationSettingsView__toggleOption ${settings.select_ai_enabled ? 'is-active' : ''}`}
              >
                {t('settings.model.selectAi.engine.agent')}
              </span>
            </section>

            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.region')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.select_ai_region}
                onInput={updateField('select_ai_region')}
                placeholder={DEFAULT_SELECT_AI_REGION}
              />
              <span class="applicationSettingsView__hint applicationSettingsView__hint--flush">{t('settings.model.selectAi.regionHint')}</span>
            </label>

            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.modelId')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.select_ai_model_id}
                onInput={updateField('select_ai_model_id')}
                placeholder={DEFAULT_SELECT_AI_MODEL}
              />
              <span class="applicationSettingsView__hint applicationSettingsView__hint--flush">{t('settings.model.selectAi.modelHint')}</span>
            </label>

            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.embeddingModelId')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.select_ai_embedding_model_id}
                onInput={updateField('select_ai_embedding_model_id')}
                placeholder={DEFAULT_EMBEDDING_MODEL}
              />
            </label>

            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.maxTokens')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                type="number"
                min="256"
                max="65536"
                value={settings.select_ai_max_tokens}
                onInput={updateField('select_ai_max_tokens')}
              />
            </label>

            <label class="applicationSettingsView__field applicationSettingsView__field--wide">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.endpointId')}</span>
              <input
                class="ics-input applicationSettingsView__modelInput"
                value={settings.select_ai_endpoint_id}
                onInput={updateField('select_ai_endpoint_id')}
                placeholder="ocid1.generativeaiendpoint.oc1..aaaa..."
              />
              <span class="applicationSettingsView__hint applicationSettingsView__hint--flush">{t('settings.model.selectAi.endpointHint')}</span>
            </label>

            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.apiFormat')}</span>
              <select
                class="ics-input applicationSettingsView__modelInput"
                value={settings.select_ai_oci_apiformat}
                onChange={updateField('select_ai_oci_apiformat')}
              >
                <option value="GENERIC">GENERIC</option>
                <option value="COHERE">COHERE</option>
              </select>
            </label>

            <div class="applicationSettingsView__field" />

            <label class="applicationSettingsView__field applicationSettingsView__toggleField">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.enforceObjectList')}</span>
              <span class="applicationSettingsView__toggleRow">
                <input
                  type="checkbox"
                  checked={settings.select_ai_enforce_object_list}
                  onChange={updateField('select_ai_enforce_object_list')}
                />
                <span class="applicationSettingsView__toggleText">
                  {settings.select_ai_enforce_object_list ? t('common.enabled') : t('common.disabled')}
                </span>
              </span>
            </label>

            <label class="applicationSettingsView__field applicationSettingsView__toggleField">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.useConstraints')}</span>
              <span class="applicationSettingsView__toggleRow">
                <input
                  type="checkbox"
                  checked={settings.select_ai_use_constraints}
                  onChange={updateField('select_ai_use_constraints')}
                />
                <span class="applicationSettingsView__toggleText">
                  {settings.select_ai_use_constraints ? t('common.enabled') : t('common.disabled')}
                </span>
              </span>
            </label>

            <label class="applicationSettingsView__field applicationSettingsView__toggleField">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.useComments')}</span>
              <span class="applicationSettingsView__toggleRow">
                <input
                  type="checkbox"
                  checked={settings.select_ai_use_comments}
                  onChange={updateField('select_ai_use_comments')}
                />
                <span class="applicationSettingsView__toggleText">
                  {settings.select_ai_use_comments ? t('common.enabled') : t('common.disabled')}
                </span>
              </span>
            </label>

            <label class="applicationSettingsView__field applicationSettingsView__toggleField">
              <span class="applicationSettingsView__fieldLabel">{t('settings.model.selectAi.useAnnotations')}</span>
              <span class="applicationSettingsView__toggleRow">
                <input
                  type="checkbox"
                  checked={settings.select_ai_use_annotations}
                  onChange={updateField('select_ai_use_annotations')}
                />
                <span class="applicationSettingsView__toggleText">
                  {settings.select_ai_use_annotations ? t('common.enabled') : t('common.disabled')}
                </span>
              </span>
            </label>
          </div>

          <div class="applicationSettingsView__modelStack">
            <div class="applicationSettingsView__modelToolbar">
              <div class="applicationSettingsView__modelToolbarGroup">
                <span class="applicationSettingsView__toolbarLabel"><Sparkles size={14} /> {t('settings.action.save')}</span>
                <button
                  class="ics-ops-btn ics-ops-btn--primary"
                  onClick={() => { void handleSave(); }}
                  disabled={isActionLocked}
                >
                  {isSaving ? t('settings.action.saving') : t('settings.action.save')}
                </button>
              </div>

              <div class="applicationSettingsView__modelToolbarGroup">
                <span class="applicationSettingsView__toolbarLabel"><Bot size={14} /> Model Test</span>
                <div class="ics-action-bar">
                  <button
                    class="ics-ops-btn ics-ops-btn--ghost"
                    onClick={() => { void handleModelTest('llm'); }}
                    disabled={isActionLocked}
                  >
                    {isLlmTesting ? t('settings.model.action.testingLlm') : t('settings.model.action.testLlm')}
                  </button>
                  <button
                    class="ics-ops-btn ics-ops-btn--ghost"
                    onClick={() => { void handleModelTest('vlm'); }}
                    disabled={isActionLocked}
                  >
                    {isVlmTesting ? t('settings.model.action.testingVlm') : t('settings.model.action.testVlm')}
                  </button>
                  <button
                    class="ics-ops-btn ics-ops-btn--ghost"
                    onClick={() => { void handleModelTest('embedding'); }}
                    disabled={isActionLocked}
                  >
                    {isEmbeddingTesting ? t('settings.model.action.testingEmbedding') : t('settings.model.action.testEmbedding')}
                  </button>
                </div>
              </div>
            </div>

            <div class="applicationSettingsView__modelResultGrid">
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
                  <Network size={14} /> {t('settings.model.testResult.vlm')}
                </span>
                <textarea
                  class="ics-input applicationSettingsView__resultTextArea"
                  rows={4}
                  readOnly
                  value={vlmResultText}
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
        </div>
      </section>
    </div>
  );
}
