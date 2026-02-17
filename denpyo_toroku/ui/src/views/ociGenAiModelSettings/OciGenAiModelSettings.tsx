import { useCallback, useEffect, useState } from 'preact/hooks';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';
import { Cpu } from 'lucide-react';
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

  return (
    <div class="applicationSettingsView applicationSettingsView--enhanced">
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
      </section>

      <section class="ics-card applicationSettingsView__panel oj-sm-padding-7x">
        <div class="ics-card-header applicationSettingsView__cardHeader">
          <div class="applicationSettingsView__titleWrap">
            <Cpu size={16} />
            <span class="oj-typography-heading-xs">{t('settings.model.title')}</span>
          </div>
          <div class="applicationSettingsView__headerActions">
            <Button
              label={isLoading ? t('settings.refreshing') : t('settings.refresh')}
              variant="outlined"
              size="sm"
              onAction={() => { void loadSettings(); }}
              isDisabled={isLoading || isSaving}
            />
          </div>
        </div>
        <div class="ics-card-body">
          <div class="applicationSettingsView__grid">
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.oci.compartmentOcid')}</span>
              <input
                class="ics-input"
                value={settings.compartment_id}
                onInput={updateField('compartment_id')}
                placeholder="ocid1.compartment.oc1..aaaa..."
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.serviceEndpoint')}</span>
              <input
                class="ics-input"
                value={settings.service_endpoint}
                onInput={updateField('service_endpoint')}
                placeholder={DEFAULT_ENDPOINT}
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.llmModelId')}</span>
              <input
                class="ics-input"
                value={settings.llm_model_id}
                onInput={updateField('llm_model_id')}
                placeholder={DEFAULT_LLM_MODEL}
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.embeddingModelId')}</span>
              <input
                class="ics-input"
                value={settings.embedding_model_id}
                onInput={updateField('embedding_model_id')}
                placeholder={DEFAULT_EMBEDDING_MODEL}
              />
            </label>
          </div>
          <div class="applicationSettingsView__actions">
            <Button
              label={isSaving ? t('settings.action.saving') : t('settings.action.save')}
              onAction={() => { void handleSave(); }}
              isDisabled={isLoading || isSaving}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
