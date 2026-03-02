/**
 * ApplicationSettings - OCI 設定管理。
 * 読み込み/保存/接続テストのフローを提供。
 */
import { useCallback, useEffect, useRef, useState } from 'preact/hooks';

import { Upload, KeyRound, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { StatusBadge } from '../../components/common/StatusBadge';
import { apiGet, apiPost } from '../../utils/apiUtils';
import { useAppDispatch } from '../../redux/store';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { t } from '../../i18n';

const MASKED_KEY = '[CONFIGURED]';
const DEFAULT_REGION = 'us-chicago-1';
const PEM_PATTERN = /-----BEGIN[\s\S]*?PRIVATE KEY-----[\s\S]*?-----END[\s\S]*?PRIVATE KEY-----/;

interface OciSettingsForm {
  user_ocid: string;
  tenancy_ocid: string;
  fingerprint: string;
  region: string;
  key_content: string;
  config_path: string;
  profile: string;
  key_file?: string;
}

interface OciSettingsSnapshot {
  settings: OciSettingsForm;
  is_configured: boolean;
  has_credentials: boolean;
  status: string;
}

interface OciConnectionTestResult {
  success: boolean;
  message: string;
  details?: Record<string, string | null>;
}

const EMPTY_SETTINGS: OciSettingsForm = {
  user_ocid: '',
  tenancy_ocid: '',
  fingerprint: '',
  region: DEFAULT_REGION,
  key_content: '',
  config_path: '~/.oci/config',
  profile: 'DEFAULT'
};

function isConfiguredStatus(status: string): boolean {
  return status === 'configured' || status === 'saved';
}

function statusLabel(status: string): string {
  return isConfiguredStatus(status) ? t('common.configured') : t('common.notConfigured');
}



function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error(t('notify.file.readFailed')));
    reader.readAsText(file);
  });
}

export function ApplicationSettings() {
  const dispatch = useAppDispatch();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [settings, setSettings] = useState<OciSettingsForm>(EMPTY_SETTINGS);
  const [status, setStatus] = useState<string>('not_configured');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<OciConnectionTestResult | null>(null);
  const [privateKeyPreview, setPrivateKeyPreview] = useState<string>('');

  const applySnapshot = useCallback((snapshot: OciSettingsSnapshot) => {
    const next = {
      ...EMPTY_SETTINGS,
      ...snapshot.settings
    };
    setSettings(next);
    setStatus(snapshot.status || (snapshot.is_configured ? 'configured' : 'not_configured'));
    if (next.key_content && next.key_content !== MASKED_KEY) {
      setPrivateKeyPreview(next.key_content.slice(0, 240));
    } else {
      setPrivateKeyPreview('');
    }
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
    (field: keyof OciSettingsForm) => (event: Event) => {
      const target = event.target as HTMLInputElement | HTMLSelectElement;
      setSettings(prev => ({ ...prev, [field]: target.value }));
    },
    []
  );

  const handlePrivateKeyUpload = useCallback(async (event: Event) => {
    const target = event.target as HTMLInputElement;
    const file = target.files?.[0];
    if (!file) return;
    try {
      const content = (await readTextFile(file)).trim();
      if (!PEM_PATTERN.test(content)) {
        throw new Error(t('notify.privateKey.invalidPem'));
      }
      setSettings(prev => ({ ...prev, key_content: content }));
      setPrivateKeyPreview(content.slice(0, 240));
      setTestResult(null);
      dispatch(addNotification({ type: 'success', message: t('notify.privateKey.loadedOk'), autoClose: true }));
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || t('notify.privateKey.loadFailed') }));
    } finally {
      target.value = '';
    }
  }, [dispatch]);

  const clearPrivateKey = useCallback(() => {
    setSettings(prev => ({ ...prev, key_content: '' }));
    setPrivateKeyPreview('');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    dispatch(addNotification({ type: 'info', message: t('notify.privateKey.cleared'), autoClose: true }));
  }, [dispatch]);

  const validateBeforeAction = useCallback((): boolean => {
    const missing: string[] = [];
    if (!settings.user_ocid.trim()) missing.push(t('settings.field.userOcid'));
    if (!settings.tenancy_ocid.trim()) missing.push(t('settings.field.tenancyOcid'));
    if (!settings.fingerprint.trim()) missing.push(t('settings.field.fingerprint'));
    if (!settings.region.trim()) missing.push(t('settings.oci.region'));
    if (missing.length > 0) {
      dispatch(addNotification({
        type: 'warning',
        message: t('notify.requiredFields.missing', { fields: missing.join('、') })
      }));
      return false;
    }

    if (!settings.key_content.trim()) {
      dispatch(addNotification({
        type: 'warning',
        message: t('notify.privateKey.required')
      }));
      return false;
    }
    return true;
  }, [dispatch, settings.fingerprint, settings.key_content, settings.region, settings.tenancy_ocid, settings.user_ocid]);

  const handleSave = useCallback(async () => {
    if (!validateBeforeAction()) return;
    setIsSaving(true);
    setTestResult(null);
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
  }, [applySnapshot, dispatch, settings, validateBeforeAction]);

  const handleTestConnection = useCallback(async () => {
    if (!validateBeforeAction()) return;
    setIsTesting(true);
    try {
      const result = await apiPost<OciConnectionTestResult>('/api/v1/oci/test', { settings });
      setTestResult(result);
      if (result.success) {
        dispatch(addNotification({
          type: 'success',
          message: result.message || t('notify.settings.testOk'),
          autoClose: true
        }));
      } else {
        dispatch(addNotification({
          type: 'error',
          message: result.message || t('notify.settings.testFailed')
        }));
      }
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.settings.testRequestFailed')
      }));
    } finally {
      setIsTesting(false);
    }
  }, [dispatch, settings, validateBeforeAction]);

  return (
    <div class="applicationSettingsView applicationSettingsView--enhanced">
      <section class="applicationSettingsView__hero">
        <div class="applicationSettingsView__heroHeader">
          <div class="genericHeading">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">{t('settings.app.title')}</h1>
              <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
                {t('settings.app.subtitle')}
              </p>
            </div>
          </div>

          <div class="applicationSettingsView__heroMeta">
            <StatusBadge
              class="applicationSettingsView__heroBadge"
              variant={isConfiguredStatus(status) ? 'success' : 'unknown'}
              icon={isConfiguredStatus(status) ? CheckCircle : XCircle}
            >
              {statusLabel(status)}
            </StatusBadge>
          </div>
        </div>

        <div class="applicationSettingsView__heroMetrics">
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">{t('settings.oci.authStatus')}</div>
            <div class="applicationSettingsView__heroMetricValue">{statusLabel(status)}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">{t('settings.oci.region')}</div>
            <div class="applicationSettingsView__heroMetricValue">{settings.region || DEFAULT_REGION}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">{t('settings.field.profile')}</div>
            <div class="applicationSettingsView__heroMetricValue">{settings.profile || 'DEFAULT'}</div>
          </div>
          <div class="applicationSettingsView__heroMetric">
            <div class="applicationSettingsView__heroMetricLabel">{t('settings.field.privateKey')}</div>
            <div class="applicationSettingsView__heroMetricValue">
              {settings.key_content ? (settings.key_content === MASKED_KEY ? t('common.configured') : t('settings.privateKey.loaded')) : t('common.notConfigured')}
            </div>
          </div>
        </div>
      </section>

      <section class="ics-card applicationSettingsView__panel oj-sm-padding-7x">
        <div class="ics-card-header applicationSettingsView__cardHeader">
          <div class="applicationSettingsView__titleWrap">
            <KeyRound size={16} />
            <span class="oj-typography-heading-xs">{t('settings.oci.authSettingsTitle')}</span>
          </div>
          <div class="applicationSettingsView__headerActions">
            <button
              class="ics-ops-btn ics-ops-btn--ghost"
              onClick={() => { void loadSettings(); }}
              disabled={isLoading || isSaving || isTesting}
            >
              <RefreshCw size={14} class={isLoading ? 'ics-spin' : ''} />
              <span>{isLoading ? t('settings.refreshing') : t('settings.refresh')}</span>
            </button>
          </div>
        </div>
        <div class="ics-card-body">
          <div class="applicationSettingsView__grid">
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.userOcid')}*</span>
              <input
                class="ics-input"
                value={settings.user_ocid}
                onInput={updateField('user_ocid')}
                placeholder="ocid1.user.oc1..aaaa..."
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.tenancyOcid')}*</span>
              <input
                class="ics-input"
                value={settings.tenancy_ocid}
                onInput={updateField('tenancy_ocid')}
                placeholder="ocid1.tenancy.oc1..aaaa..."
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.fingerprint')}*</span>
              <input
                class="ics-input"
                value={settings.fingerprint}
                onInput={updateField('fingerprint')}
                placeholder="aa:bb:cc:dd:..."
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.oci.region')}*</span>
              <input
                class="ics-input"
                value={settings.region}
                onInput={updateField('region')}
                placeholder="us-chicago-1"
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.configPath')}</span>
              <input
                class="ics-input"
                value={settings.config_path}
                onInput={updateField('config_path')}
                placeholder="~/.oci/config"
              />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.field.profile')}</span>
              <input
                class="ics-input"
                value={settings.profile}
                onInput={updateField('profile')}
                placeholder="DEFAULT"
              />
            </label>
          </div>

          <div class="applicationSettingsView__privateKeySection">
            <span class="applicationSettingsView__fieldLabel">{t('settings.field.privateKey')}*</span>
            <div
              class="predictView__dropZone applicationSettingsView__dropZone"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload size={22} />
              <p class="oj-typography-body-md">{t('settings.privateKey.uploadCta')}</p>
              <p class="oj-typography-body-sm">
                {settings.key_content === MASKED_KEY
                  ? t('settings.privateKey.helpConfigured')
                  : t('settings.privateKey.helpClickUpload')}
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pem,.key"
                class="send-off-screen"
                onChange={handlePrivateKeyUpload}
              />
            </div>
            {settings.key_content && settings.key_content !== MASKED_KEY && (
              <div class="applicationSettingsView__privateKeyPreview">
                <div class="applicationSettingsView__privateKeyPreviewHead">
                  <span>{t('settings.privateKey.loaded')}</span>
                  <button class="ics-btn" onClick={clearPrivateKey}>{t('common.clear')}</button>
                </div>
                <pre class="applicationSettingsView__privateKeyCode">{privateKeyPreview}{settings.key_content.length > 240 ? '...' : ''}</pre>
              </div>
            )}
            {settings.key_content === MASKED_KEY && (
              <div class="applicationSettingsView__privateKeyConfigured">
                <CheckCircle size={14} />
                <span>{t('settings.privateKey.configuredOnServer')}</span>
              </div>
            )}
          </div>

          <div class="applicationSettingsView__actions">
            <div class="ics-action-bar">
              <button
                class="ics-ops-btn ics-ops-btn--primary"
                onClick={() => { void handleSave(); }}
                disabled={isLoading || isSaving || isTesting}
              >
                {isSaving ? t('settings.action.saving') : t('settings.action.save')}
              </button>
              <button
                class="ics-ops-btn ics-ops-btn--ghost"
                onClick={() => { void handleTestConnection(); }}
                disabled={isLoading || isSaving || isTesting}
              >
                {isTesting ? t('settings.action.testing') : t('settings.action.test')}
              </button>
            </div>
          </div>
          <p class="applicationSettingsView__hint">
            {t('settings.hint')}
          </p>
        </div>
      </section>

      {testResult && (
        <section class={`ics-card ${testResult.success ? 'ics-card-success' : 'ics-card-error'}`}>
          <div class="ics-card-header applicationSettingsView__titleWrap">
            {testResult.success ? <CheckCircle size={16} /> : <XCircle size={16} />}
            <span class="oj-typography-heading-xs">{t('settings.testResult.title')}</span>
          </div>
          <div class="ics-card-body">
            <p class={testResult.success ? 'applicationSettingsView__successText' : 'ics-error-text'}>
              {testResult.message}
            </p>
            {testResult.details && (
              <div class="applicationSettingsView__detailsGrid">
                {Object.entries(testResult.details).map(([key, value]) => (
                  <div class="applicationSettingsView__detailItem" key={key}>
                    <span class="applicationSettingsView__detailKey">{key}</span>
                    <span class="applicationSettingsView__detailValue">{value || '-'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
