import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { Button } from '@oracle/oraclejet-preact/UNSAFE_Button';
import { Upload, CheckCircle, XCircle, Database, Power, PowerOff, RefreshCw } from 'lucide-react';
import { apiGet, apiPost, apiPostWithTimeout } from '../../utils/apiUtils';
import { useAppDispatch } from '../../redux/store';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { t } from '../../i18n';

const BASE_URL = '/studio';

interface DatabaseSettingsForm {
  username: string;
  password: string;
  dsn: string;
  adb_ocid?: string;
  region?: string;
  wallet_uploaded: boolean;
  available_services: string[];
}

interface DatabaseSettingsSnapshot {
  settings: DatabaseSettingsForm;
  is_connected?: boolean;
  is_configured?: boolean;
  status: string;
  wallet_location?: string | null;
}

interface DatabaseEnvInfo {
  success: boolean;
  message: string;
  username: string | null;
  password: string | null;
  dsn: string | null;
  adb_ocid?: string | null;
  region?: string | null;
  wallet_exists: boolean;
  wallet_location?: string | null;
  available_services: string[];
}

interface DatabaseConnectionTestResult {
  success: boolean;
  message: string;
  details?: Record<string, string | null>;
}

interface AdbInfo {
  status: string;
  message: string;
  id?: string | null;
  display_name?: string | null;
  lifecycle_state?: string | null;
  db_name?: string | null;
  cpu_core_count?: number | null;
  data_storage_size_in_tbs?: number | null;
  region?: string | null;
}

interface AdbOperationResult {
  status: string;
  message: string;
  timestamp: string;
  lifecycle_state?: string | null;
}

const EMPTY_DB_SETTINGS: DatabaseSettingsForm = {
  username: '',
  password: '',
  dsn: '',
  adb_ocid: '',
  region: '',
  wallet_uploaded: false,
  available_services: []
};

function isConfiguredStatus(status: string): boolean {
  return status === 'configured' || status === 'saved';
}

function statusLabel(status: string): string {
  return isConfiguredStatus(status) ? t('common.configured') : t('common.notConfigured');
}

function getStatusClassName(status: string): string {
  return isConfiguredStatus(status) ? 'ics-status-healthy' : 'ics-status-unknown';
}

const ADB_LIFECYCLE_LABEL_KEYS: Record<string, Parameters<typeof t>[0]> = {
  AVAILABLE: 'settings.adb.lifecycle.AVAILABLE',
  STARTING: 'settings.adb.lifecycle.STARTING',
  STOPPING: 'settings.adb.lifecycle.STOPPING',
  STOPPED: 'settings.adb.lifecycle.STOPPED',
  UNAVAILABLE: 'settings.adb.lifecycle.UNAVAILABLE',
  PROVISIONING: 'settings.adb.lifecycle.PROVISIONING',
  TERMINATING: 'settings.adb.lifecycle.TERMINATING',
  TERMINATED: 'settings.adb.lifecycle.TERMINATED',
  FAILED: 'settings.adb.lifecycle.FAILED',
  UPDATING: 'settings.adb.lifecycle.UPDATING',
  RESTORING: 'settings.adb.lifecycle.RESTORING',
  BACKUP_IN_PROGRESS: 'settings.adb.lifecycle.BACKUP_IN_PROGRESS',
  MAINTENANCE_IN_PROGRESS: 'settings.adb.lifecycle.MAINTENANCE_IN_PROGRESS',
  ROLE_CHANGE_IN_PROGRESS: 'settings.adb.lifecycle.ROLE_CHANGE_IN_PROGRESS',
  UPGRADING: 'settings.adb.lifecycle.UPGRADING',
  INACCESSIBLE: 'settings.adb.lifecycle.INACCESSIBLE',
  STANDBY: 'settings.adb.lifecycle.STANDBY'
};

export function DatabaseSettings() {
  const dispatch = useAppDispatch();
  const walletFileInputRef = useRef<HTMLInputElement>(null);

  const [dbSettings, setDbSettings] = useState<DatabaseSettingsForm>(EMPTY_DB_SETTINGS);
  const [dbStatus, setDbStatus] = useState<string>('not_configured');
  const [dbWalletLocation, setDbWalletLocation] = useState<string>('');
  const [dbIsLoading, setDbIsLoading] = useState<boolean>(true);
  const [dbIsSaving, setDbIsSaving] = useState<boolean>(false);
  const [dbIsTesting, setDbIsTesting] = useState<boolean>(false);
  const [dbIsRefreshingEnv, setDbIsRefreshingEnv] = useState<boolean>(false);
  const [dbIsUploadingWallet, setDbIsUploadingWallet] = useState<boolean>(false);
  const [dbTestResult, setDbTestResult] = useState<DatabaseConnectionTestResult | null>(null);
  const [walletFileName, setWalletFileName] = useState<string>('');

  // ADB Management State
  const [adbInfo, setAdbInfo] = useState<AdbInfo | null>(null);
  const [adbIsLoading, setAdbIsLoading] = useState<boolean>(false);
  const [adbIsStarting, setAdbIsStarting] = useState<boolean>(false);
  const [adbIsStopping, setAdbIsStopping] = useState<boolean>(false);
  const [adbOperationResults, setAdbOperationResults] = useState<AdbOperationResult[]>([]);

  const applyDbSnapshot = useCallback((snapshot: DatabaseSettingsSnapshot) => {
    const next = {
      ...EMPTY_DB_SETTINGS,
      ...snapshot.settings,
      available_services: Array.isArray(snapshot.settings?.available_services) ? snapshot.settings.available_services : []
    };
    setDbSettings(next);
    setDbStatus(snapshot.status || (snapshot.is_configured ? 'configured' : 'not_configured'));
    setDbWalletLocation(snapshot.wallet_location || '');
  }, []);

  const loadDatabaseSettings = useCallback(async () => {
    setDbIsLoading(true);
    try {
      const snapshot = await apiGet<DatabaseSettingsSnapshot>('/api/v1/database/settings');
      applyDbSnapshot(snapshot);
      
      // 常にADB情報を取得（region表示のため）
      setAdbIsLoading(true);
      try {
        const adbResult = await apiGet<AdbInfo>('/api/v1/database/adb/info');
        setAdbInfo(adbResult);
      } catch (err: any) {
        // ADB情報取得エラーは静かに失敗（regionのみの取得失敗は致命的ではない）
        console.warn('ADB info fetch failed:', err.message);
      } finally {
        setAdbIsLoading(false);
      }
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.dbSettings.loadFailed')
      }));
    } finally {
      setDbIsLoading(false);
    }
  }, [applyDbSnapshot, dispatch]);

  useEffect(() => {
    void loadDatabaseSettings();
  }, [loadDatabaseSettings]);

  const updateDbField = useCallback(
    (field: keyof DatabaseSettingsForm) => (event: Event) => {
      const target = event.target as HTMLInputElement | HTMLSelectElement;
      setDbSettings(prev => ({ ...prev, [field]: target.value }));
    },
    []
  );

  const validateDbBeforeAction = useCallback((requirePassword: boolean = true): boolean => {
    const missing: string[] = [];
    if (!dbSettings.username.trim()) missing.push(t('settings.db.field.username'));
    if (!dbSettings.dsn.trim()) missing.push(t('settings.db.field.dsn'));
    const passwordMissing = !dbSettings.password.trim();
    if (requirePassword && passwordMissing) missing.push(t('settings.db.field.password'));

    if (missing.length > 0) {
      dispatch(addNotification({
        type: 'warning',
        message: t('notify.requiredFields.missing', { fields: missing.join('、') })
      }));
      return false;
    }
    return true;
  }, [dbSettings.dsn, dbSettings.password, dbSettings.username, dispatch]);

  const handleDbRefreshFromEnv = useCallback(async () => {
    setDbIsRefreshingEnv(true);
    try {
      const envInfo = await apiGet<DatabaseEnvInfo>('/api/v1/database/settings/env');
      setDbSettings(prev => ({
        ...prev,
        username: envInfo.username || prev.username,
        password: envInfo.password || (prev.password || ''),
        dsn: envInfo.dsn || prev.dsn,
        adb_ocid: envInfo.adb_ocid || prev.adb_ocid || '',
        region: envInfo.region || prev.region || '',
        wallet_uploaded: envInfo.wallet_exists,
        available_services: Array.isArray(envInfo.available_services) ? envInfo.available_services : prev.available_services
      }));
      setDbWalletLocation(envInfo.wallet_location || '');
      if (envInfo.success) {
        setDbStatus(envInfo.wallet_exists && !!(envInfo.username && envInfo.dsn) ? 'configured' : 'not_configured');
        dispatch(addNotification({ type: 'success', message: t('notify.dbSettings.envLoadedOk'), autoClose: true }));
      } else {
        dispatch(addNotification({ type: 'warning', message: envInfo.message || t('notify.dbSettings.envLoadFailed') }));
      }
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.dbSettings.envLoadFailed')
      }));
    } finally {
      setDbIsRefreshingEnv(false);
    }
  }, [dispatch]);

  const handleDbSave = useCallback(async () => {
    if (!validateDbBeforeAction(true)) return;
    setDbIsSaving(true);
    setDbTestResult(null);
    try {
      const snapshot = await apiPost<DatabaseSettingsSnapshot>('/api/v1/database/settings', dbSettings);
      applyDbSnapshot(snapshot);
      dispatch(addNotification({
        type: 'success',
        message: t('notify.dbSettings.savedOk'),
        autoClose: true
      }));
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.dbSettings.saveFailed')
      }));
    } finally {
      setDbIsSaving(false);
    }
  }, [applyDbSnapshot, dbSettings, dispatch, validateDbBeforeAction]);

  const handleDbTest = useCallback(async () => {
    if (!validateDbBeforeAction(false)) return;
    setDbIsTesting(true);
    try {
      // タイムアウト付きでDB接続テストを実行（非ブロッキング）
      const result = await apiPostWithTimeout<DatabaseConnectionTestResult>('/api/v1/database/settings/test', { settings: dbSettings });
      setDbTestResult(result);
      if (result.success) {
        dispatch(addNotification({
          type: 'success',
          message: result.message || t('notify.dbSettings.testOk'),
          autoClose: true
        }));
      } else {
        dispatch(addNotification({
          type: 'error',
          message: result.message || t('notify.dbSettings.testFailed')
        }));
      }
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.dbSettings.testRequestFailed')
      }));
    } finally {
      setDbIsTesting(false);
    }
  }, [dbSettings, dispatch, validateDbBeforeAction]);

  const handleWalletUpload = useCallback(async (event: Event) => {
    const target = event.target as HTMLInputElement;
    const file = target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.zip')) {
      dispatch(addNotification({ type: 'warning', message: t('notify.dbSettings.walletInvalidZip') }));
      target.value = '';
      return;
    }

    setDbIsUploadingWallet(true);
    setWalletFileName(file.name);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(`${BASE_URL}/api/v1/database/settings/wallet`, {
        method: 'POST',
        credentials: 'same-origin',
        body: formData
      });
      const body = await response.json();
      if (!response.ok) {
        const message = body?.errorMessages?.[0] || t('notify.dbSettings.walletUploadFailed');
        throw new Error(message);
      }

      const result = body?.data || {};
      setDbWalletLocation(result.wallet_location || '');
      setDbSettings(prev => ({
        ...prev,
        wallet_uploaded: true,
        available_services: Array.isArray(result.available_services) ? result.available_services : prev.available_services,
        dsn: prev.dsn || (Array.isArray(result.available_services) && result.available_services.length > 0 ? result.available_services[0] : prev.dsn)
      }));
      setDbStatus('saved');
      dispatch(addNotification({ type: 'success', message: result.message || t('notify.dbSettings.walletUploadedOk'), autoClose: true }));
    } catch (err: any) {
      dispatch(addNotification({ type: 'error', message: err.message || t('notify.dbSettings.walletUploadFailed') }));
    } finally {
      target.value = '';
      setDbIsUploadingWallet(false);
    }
  }, [dispatch]);

  // ADB Management Functions
  const loadAdbInfo = useCallback(async () => {
    setAdbIsLoading(true);
    try {
      const result = await apiGet<AdbInfo>('/api/v1/database/adb/info');
      setAdbInfo(result);
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.adb.infoFailed')
      }));
    } finally {
      setAdbIsLoading(false);
    }
  }, [dispatch]);

  const handleAdbStart = useCallback(async () => {
    setAdbIsStarting(true);
    try {
      const result = await apiPost<AdbInfo>('/api/v1/database/adb/start', {});
      setAdbInfo(prev => ({ ...prev, ...result, region: result.region || prev?.region || null }));
      
      const operationResult: AdbOperationResult = {
        status: result.status,
        message: result.message,
        timestamp: new Date().toLocaleString('ja-JP'),
        lifecycle_state: result.lifecycle_state
      };
      setAdbOperationResults(prev => [operationResult, ...prev]);

      if (result.status === 'accepted') {
        dispatch(addNotification({ type: 'success', message: result.message, autoClose: true }));
      } else if (result.status === 'already_available') {
        dispatch(addNotification({ type: 'info', message: t('notify.adb.alreadyAvailable'), autoClose: true }));
      } else if (result.status === 'cannot_start') {
        dispatch(addNotification({ type: 'warning', message: t('notify.adb.cannotStart') }));
      }
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.adb.startFailed')
      }));
    } finally {
      setAdbIsStarting(false);
    }
  }, [dispatch]);

  const handleAdbStop = useCallback(async () => {
    setAdbIsStopping(true);
    try {
      const result = await apiPost<AdbInfo>('/api/v1/database/adb/stop', {});
      setAdbInfo(prev => ({ ...prev, ...result, region: result.region || prev?.region || null }));
      
      const operationResult: AdbOperationResult = {
        status: result.status,
        message: result.message,
        timestamp: new Date().toLocaleString('ja-JP'),
        lifecycle_state: result.lifecycle_state
      };
      setAdbOperationResults(prev => [operationResult, ...prev]);

      if (result.status === 'accepted') {
        dispatch(addNotification({ type: 'success', message: result.message, autoClose: true }));
      } else if (result.status === 'already_stopped') {
        dispatch(addNotification({ type: 'info', message: t('notify.adb.alreadyStopped'), autoClose: true }));
      } else if (result.status === 'cannot_stop') {
        dispatch(addNotification({ type: 'warning', message: t('notify.adb.cannotStop') }));
      }
    } catch (err: any) {
      dispatch(addNotification({
        type: 'error',
        message: err.message || t('notify.adb.stopFailed')
      }));
    } finally {
      setAdbIsStopping(false);
    }
  }, [dispatch]);

  const getAdbLifecycleLabel = useCallback((state: string | null | undefined): string => {
    if (!state) return t('settings.adb.statusUnknown');
    const key = ADB_LIFECYCLE_LABEL_KEYS[state];
    return key ? t(key) : state;
  }, []);

  const getAdbStatusClassName = useCallback((state: string | null | undefined): string => {
    if (!state) return 'ics-status-unknown';
    switch (state) {
      case 'AVAILABLE':
        return 'ics-status-healthy';
      case 'STARTING':
      case 'STOPPING':
      case 'UPDATING':
      case 'RESTORING':
        return 'ics-status-warning';
      case 'STOPPED':
      case 'UNAVAILABLE':
        return 'ics-status-inactive';
      case 'FAILED':
      case 'INACCESSIBLE':
        return 'ics-status-error';
      default:
        return 'ics-status-unknown';
    }
  }, []);

  return (
    <div class="applicationSettingsView applicationSettingsView--enhanced">
      <section class="applicationSettingsView__hero">
        <div class="applicationSettingsView__heroHeader">
          <div class="genericHeading">
            <div class="genericHeading--headings">
              <h1 class="genericHeading--headings__title genericHeading--headings__title--default">{t('settings.db.title')}</h1>
            </div>
          </div>
          <div class="applicationSettingsView__heroMeta">
            <span class={`applicationSettingsView__heroBadge ${getStatusClassName(dbStatus)}`}>{statusLabel(dbStatus)}</span>
          </div>
        </div>
      </section>

      {/* ADB Management Section */}
      <section class="ics-card applicationSettingsView__panel oj-sm-padding-7x">
        <div class="ics-card-header applicationSettingsView__cardHeader">
          <div class="applicationSettingsView__titleWrap">
            <Database size={16} />
            <span class="oj-typography-heading-xs">{t('settings.adb.title')}</span>
          </div>
          <div class="applicationSettingsView__headerActions">
            <Button
              label={adbIsLoading ? t('settings.adb.refreshing') : t('settings.adb.refresh')}
              variant="outlined"
              size="sm"
              onAction={() => { void loadAdbInfo(); }}
              isDisabled={adbIsLoading || adbIsStarting || adbIsStopping}
            />
            <span class={`applicationSettingsView__heroBadge ${getAdbStatusClassName(adbInfo?.lifecycle_state)}`}>
              {adbInfo?.lifecycle_state ? getAdbLifecycleLabel(adbInfo.lifecycle_state) : t('settings.adb.statusUnknown')}
            </span>
          </div>
        </div>
        <div class="ics-card-body">
          <p class="applicationSettingsView__description">{t('settings.adb.description')}</p>
          
          <div class="applicationSettingsView__grid">
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.adb.field.region')}</span>
              <input class="ics-input" value={dbSettings.region || ''} readonly />
            </label>
            
            <label class="applicationSettingsView__field applicationSettingsView__field--wide">
              <span class="applicationSettingsView__fieldLabel">{t('settings.adb.field.ocid')}*</span>
              <input class="ics-input" value={dbSettings.adb_ocid || ''} readonly placeholder="ocid1.autonomousdatabase.oc1.." />
            </label>
          </div>
          
          <div class="applicationSettingsView__actions" style="margin-bottom: 20px;">
            <Button
              label={adbIsStarting ? t('settings.adb.action.starting') : t('settings.adb.action.start')}
              onAction={() => { void handleAdbStart(); }}
              isDisabled={adbIsLoading || adbIsStarting || adbIsStopping || !dbSettings.adb_ocid}
            />
            <Button
              label={adbIsStopping ? t('settings.adb.action.stopping') : t('settings.adb.action.stop')}
              variant="outlined"
              onAction={() => { void handleAdbStop(); }}
              isDisabled={adbIsLoading || adbIsStarting || adbIsStopping || !dbSettings.adb_ocid}
            />
          </div>

          {adbInfo?.display_name && (
            <div class="applicationSettingsView__adbInfo">
              <div class="applicationSettingsView__grid applicationSettingsView__grid--2col">
                <div class="applicationSettingsView__field">
                  <span class="applicationSettingsView__fieldLabel">{t('settings.adb.field.displayName')}</span>
                  <div class="applicationSettingsView__fieldValue">{adbInfo.display_name || '-'}</div>
                </div>
                <div class="applicationSettingsView__field">
                  <span class="applicationSettingsView__fieldLabel">{t('settings.adb.field.status')}</span>
                  <div class="applicationSettingsView__fieldValue">{getAdbLifecycleLabel(adbInfo.lifecycle_state)}</div>
                </div>
              </div>
            </div>
          )}

          {adbOperationResults.length > 0 && (
            <div class="applicationSettingsView__operationResults">
              <div class="applicationSettingsView__operationResultsHeader">
                <span class="oj-typography-heading-xs">{t('settings.adb.operationResult.title')}</span>
              </div>
              <ul class="applicationSettingsView__operationResultsList">
                {adbOperationResults.map((result, index) => (
                  <li key={index} class="applicationSettingsView__operationResultItem">
                    <span class="applicationSettingsView__operationResultTimestamp">{result.timestamp}</span>
                    <span class={`applicationSettingsView__operationResultStatus applicationSettingsView__operationResultStatus--${result.status}`}>
                      {result.status}
                    </span>
                    <span class="applicationSettingsView__operationResultMessage">{result.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      <section class="ics-card applicationSettingsView__panel oj-sm-padding-7x">
        <div class="ics-card-header applicationSettingsView__cardHeader">
          <div class="applicationSettingsView__titleWrap">
            <Database size={16} />
            <span class="oj-typography-heading-xs">{t('settings.db.title')}</span>
          </div>
          <div class="applicationSettingsView__headerActions">
            <Button
              label={dbIsLoading ? t('settings.refreshing') : t('settings.refresh')}
              variant="outlined"
              size="sm"
              onAction={() => { void loadDatabaseSettings(); }}
              isDisabled={dbIsLoading || dbIsSaving || dbIsTesting || dbIsRefreshingEnv || dbIsUploadingWallet}
            />
            <Button
              label={dbIsRefreshingEnv ? t('settings.db.refreshingFromEnv') : t('settings.db.refreshFromEnv')}
              variant="outlined"
              size="sm"
              onAction={() => { void handleDbRefreshFromEnv(); }}
              isDisabled={dbIsLoading || dbIsSaving || dbIsTesting || dbIsRefreshingEnv || dbIsUploadingWallet}
            />
          </div>
        </div>

        <div class="ics-card-body">
          <div class="applicationSettingsView__grid">
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.db.field.username')}*</span>
              <input class="ics-input" value={dbSettings.username} onInput={updateDbField('username')} placeholder="admin" />
            </label>
            <label class="applicationSettingsView__field">
              <span class="applicationSettingsView__fieldLabel">{t('settings.db.field.password')}*</span>
              <input class="ics-input" type="password" value={dbSettings.password} onInput={updateDbField('password')} placeholder="******" />
            </label>
            {dbSettings.available_services.length > 0 ? (
              <label class="applicationSettingsView__field applicationSettingsView__field--wide">
                <span class="applicationSettingsView__fieldLabel">{t('settings.db.field.dsn')}*</span>
                <select class="ics-input" value={dbSettings.dsn} onChange={updateDbField('dsn')}>
                  <option value="">{t('settings.db.dsn.selectPlaceholder')}</option>
                  {dbSettings.available_services.map((service) => (
                    <option key={service} value={service}>{service}</option>
                  ))}
                </select>
              </label>
            ) : (
              <label class="applicationSettingsView__field applicationSettingsView__field--wide">
                <span class="applicationSettingsView__fieldLabel">{t('settings.db.field.dsn')}*</span>
                <input class="ics-input" value={dbSettings.dsn} onInput={updateDbField('dsn')} placeholder="adb_high" />
              </label>
            )}
          </div>

          <div class="applicationSettingsView__walletSection">
            <span class="applicationSettingsView__fieldLabel">{t('settings.db.wallet.title')}</span>
            <div class="predictView__dropZone applicationSettingsView__dropZone" onClick={() => walletFileInputRef.current?.click()}>
              <Upload size={22} />
              <p class="oj-typography-body-md">{t('settings.db.wallet.uploadCta')}</p>
              <p class="oj-typography-body-sm">{t('settings.db.wallet.help')}</p>
              <input ref={walletFileInputRef} type="file" accept=".zip" class="send-off-screen" onChange={handleWalletUpload} />
            </div>
            {walletFileName && <div class="applicationSettingsView__walletFileName">{t('settings.db.wallet.selected')}: {walletFileName}</div>}
            <div class="applicationSettingsView__walletStatusWrap">
              <span class="applicationSettingsView__walletStatusLabel">{t('settings.db.wallet.status')}:</span>
              <span class={dbSettings.wallet_uploaded ? 'applicationSettingsView__walletStatusOk' : 'applicationSettingsView__walletStatusNg'}>
                {dbSettings.wallet_uploaded ? t('settings.db.wallet.statusConfigured') : t('settings.db.wallet.statusNotConfigured')}
              </span>
            </div>
            {dbWalletLocation && <div class="applicationSettingsView__walletLocation">{t('settings.db.wallet.location')}: {dbWalletLocation}</div>}
          </div>

          <div class="applicationSettingsView__actions">
            <Button
              label={dbIsSaving ? t('settings.action.saving') : t('settings.db.action.save')}
              onAction={() => { void handleDbSave(); }}
              isDisabled={dbIsLoading || dbIsSaving || dbIsTesting || dbIsRefreshingEnv || dbIsUploadingWallet}
            />
            <Button
              label={dbIsTesting ? t('settings.action.testing') : t('settings.db.action.test')}
              variant="outlined"
              onAction={() => { void handleDbTest(); }}
              isDisabled={dbIsLoading || dbIsSaving || dbIsTesting || dbIsRefreshingEnv || dbIsUploadingWallet}
            />
          </div>
          <p class="applicationSettingsView__hint">{t('settings.db.hint')}</p>
        </div>
      </section>

      {dbTestResult && (
        <section class={`ics-card ${dbTestResult.success ? 'ics-card-success' : 'ics-card-error'}`}>
          <div class="ics-card-header applicationSettingsView__titleWrap">
            {dbTestResult.success ? <CheckCircle size={16} /> : <XCircle size={16} />}
            <span class="oj-typography-heading-xs">{t('settings.db.testResult.title')}</span>
          </div>
          <div class="ics-card-body">
            <p class={dbTestResult.success ? 'applicationSettingsView__successText' : 'ics-error-text'}>{dbTestResult.message}</p>
            {dbTestResult.details && (
              <div class="applicationSettingsView__detailsGrid">
                {Object.entries(dbTestResult.details).map(([key, value]) => (
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
