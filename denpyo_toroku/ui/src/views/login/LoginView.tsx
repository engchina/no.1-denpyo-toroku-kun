import { h } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useAppDispatch } from '../../redux/store';
import { setAuthenticated, setUserName } from '../../redux/slices/applicationSlice';
import { apiGet } from '../../utils/apiUtils';
import { t } from '../../i18n';

type LoginResponse = {
  success: boolean;
  user?: string;
  role?: string;
  message?: string;
};

const REMEMBER_ME_STORAGE_KEY = 'denpyo_toroku.rememberMe';
const REMEMBERED_USERNAME_STORAGE_KEY = 'denpyo_toroku.rememberedUsername';

export function LoginView() {
  const dispatch = useAppDispatch();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    try {
      const persistedRememberMe = window.localStorage.getItem(REMEMBER_ME_STORAGE_KEY);
      const shouldRemember = persistedRememberMe !== 'false';
      setRememberMe(shouldRemember);
      if (shouldRemember) {
        setUsername(window.localStorage.getItem(REMEMBERED_USERNAME_STORAGE_KEY) || '');
      }
    } catch {
      // Ignore storage access failures and keep in-memory defaults.
    }
  }, []);

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const response = await fetch('/studio/v1/loginValidation', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          username,
          password,
          remember_me: rememberMe
        })
      });
      const loginResp = (await response.json()) as LoginResponse;
      if (!response.ok || !loginResp.success) {
        throw new Error(loginResp.message || t('login.error.invalidCreds'));
      }
      const me = await apiGet<{ authenticated: boolean; user?: string }>('/v1/me');
      if (me.authenticated) {
        if (typeof window !== 'undefined') {
          try {
            if (rememberMe) {
              window.localStorage.setItem(REMEMBER_ME_STORAGE_KEY, 'true');
              window.localStorage.setItem(REMEMBERED_USERNAME_STORAGE_KEY, username);
            } else {
              window.localStorage.setItem(REMEMBER_ME_STORAGE_KEY, 'false');
              window.localStorage.removeItem(REMEMBERED_USERNAME_STORAGE_KEY);
            }
          } catch {
            // Ignore storage access failures and continue the login flow.
          }
        }
        dispatch(setUserName(me.user || username));
        dispatch(setAuthenticated(true));
      } else {
        setError(t('login.error.invalidCreds'));
        dispatch(setAuthenticated(false));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('login.error.failed'));
      dispatch(setAuthenticated(false));
    } finally {
      setLoading(false);
    }
  };

  const handleRememberMeChange = (nextChecked: boolean) => {
    setRememberMe(nextChecked);
    if (!nextChecked && typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(REMEMBER_ME_STORAGE_KEY, 'false');
        window.localStorage.removeItem(REMEMBERED_USERNAME_STORAGE_KEY);
      } catch {
        // Ignore storage access failures and keep the UI responsive.
      }
    }
  };

  return (
    <section class="aiAuth__container">
      <div class="aiAuth__card aai-fadeIn-animation-08">
        <div class="aiAuth__cardTop">
          <div class="aiAuth__userAvatar" aria-hidden="true">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
            </svg>
          </div>
          <h2 class="aiAuth__title">{t('login.title')}</h2>
          <p class="aiAuth__subtitle">{t('login.subtitle')}</p>
        </div>
        <form onSubmit={handleSubmit} class="aiAuth__form">
          {error && <div class="aiAuth__error">{error}</div>}
          <section class="aiAuth__fieldGroup">
            <label class="aiAuth__label" for="login-email">
              {t('common.email')} <span class="required">*</span>
            </label>
            <input
              id="login-email"
              class="aiAuth__input"
              type="text"
              placeholder={t('login.emailPlaceholder')}
              value={username}
              autoComplete="username"
              onInput={(e: any) => setUsername(e.currentTarget.value)}
              onInvalid={(e: any) => e.currentTarget.setCustomValidity(t('login.validation.required'))}
              onChange={(e: any) => e.currentTarget.setCustomValidity('')}
              required
            />
          </section>
          <section class="aiAuth__fieldGroup">
            <label class="aiAuth__label" for="login-password">
              {t('common.password')} <span class="required">*</span>
            </label>
            <div class="aiAuth__inputWrapper">
              <input
                id="login-password"
                class="aiAuth__input"
                type={showPassword ? 'text' : 'password'}
                placeholder={t('login.passwordPlaceholder')}
                value={password}
                autoComplete="current-password"
                onInput={(e: any) => setPassword(e.currentTarget.value)}
                onInvalid={(e: any) => e.currentTarget.setCustomValidity(t('login.validation.required'))}
                onChange={(e: any) => e.currentTarget.setCustomValidity('')}
                required
              />
              <button
                type="button"
                class="togglePassword"
                aria-label={t('login.togglePassword')}
                onClick={() => setShowPassword(prev => !prev)}
              >
                <span
                  class={`${showPassword ? 'oj-inputpassword-hide-password-icon' : 'oj-inputpassword-show-password-icon'} oj-component-icon`}
                  aria-hidden="true"
                ></span>
              </button>
            </div>
          </section>
          <div class="aiAuth__loginOptions">
            <label class="aiAuth__checkbox">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e: any) => handleRememberMeChange(e.currentTarget.checked)}
              />
              <span>{t('login.rememberMe')}</span>
            </label>
          </div>
          <button type="submit" class="aiAuth__signInButton" disabled={loading}>
            {loading ? t('login.signingIn') : t('login.signIn')}
          </button>
        </form>
      </div>
    </section>
  );
}
