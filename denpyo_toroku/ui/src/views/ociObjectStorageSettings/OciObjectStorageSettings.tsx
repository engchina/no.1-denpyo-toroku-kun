import { useCallback, useEffect, useState } from 'preact/hooks';

import { HardDrive, RefreshCw } from 'lucide-react';
import { apiGet, apiPost } from '../../utils/apiUtils';
import { useAppDispatch } from '../../redux/store';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { t } from '../../i18n';

const DEFAULT_REGION = 'ap-osaka-1';

interface OciObjectStorageSettingsForm {
  region: string;
  namespace: string;
  bucket: string;
}

interface OciSettingsSnapshot {
  settings: OciObjectStorageSettingsForm;
}

const EMPTY_SETTINGS: OciObjectStorageSettingsForm = {
  region: DEFAULT_REGION,
  namespace: '',
  bucket: ''
};

export function OciObjectStorageSettings() {
  const dispatch = useAppDispatch();
  const [settings, setSettings] = useState<OciObjectStorageSettingsForm>(EMPTY_SETTINGS);
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
      const snapshot = await apiGet<OciSettingsSnapshot>('/api/v1/oci/object-storage/settings');
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
    (field: keyof OciObjectStorageSettingsForm) => (event: Event) => {
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
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">{t('settings.storage.title')}</h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                {t('settings.storage.subtitle')}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section class="ics-card applicationSettingsView__panel oj-sm-padding-7x">
        <div class="ics-card-header applicationSettingsView__cardHeader">
          <div class="applicationSettingsView__titleWrap">
            <HardDrive size={16} />
            <span class="oj-typography-heading-xs">{t('settings.storage.title')}</span>
          </div>
          <div class="applicationSettingsView__headerActions">
            <button
              class="ics-ops-btn ics-ops-btn--ghost"
              onClick={() => { void loadSettings(); }}
              disabled={isLoading || isSaving}
            >
              <RefreshCw size={14} class={isLoading ? 'ics-spin' : ''} />
              <span>{isLoading ? t('settings.refreshing') : t('settings.refresh')}</span>
            </button>
          </div>
        </div>
        <div class="ics-card-body">
          <div class="applicationSettingsView__grid">
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.oci.region')}</span>
              <input
                class="ics-input"
                value={settings.region}
                readOnly
                placeholder={DEFAULT_REGION}
              />
            </label>
            <div />
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.objectStorageBucket')}</span>
              <input
                class="ics-input"
                value={settings.bucket}
                onInput={updateField('bucket')}
                placeholder="denpyo-files"
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.objectStorageNamespace')}</span>
              <input
                class="ics-input"
                value={settings.namespace}
                readOnly
                placeholder="axxxxxxxx"
              />
            </label>
          </div>
          <div class="applicationSettingsView__actions">
            <button
              class="ics-ops-btn ics-ops-btn--primary"
              onClick={() => { void handleSave(); }}
              disabled={isLoading || isSaving}
            >
              {isSaving ? t('settings.action.saving') : t('settings.action.save')}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
