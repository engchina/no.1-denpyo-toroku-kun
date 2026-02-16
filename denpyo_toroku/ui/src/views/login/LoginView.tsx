import { h } from 'preact';
import { useState } from 'preact/hooks';
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

export function LoginView() {
  const dispatch = useAppDispatch();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

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
              onInput={(e: any) => setUsername(e.currentTarget.value)}
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
                onInput={(e: any) => setPassword(e.currentTarget.value)}
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
                onChange={(e: any) => setRememberMe(e.currentTarget.checked)}
              />
              <span>{t('login.rememberMe')}</span>
            </label>
            <a href="#" class="aiAuth__forgotLink">{t('login.forgotPassword')}</a>
          </div>
          <button type="submit" class="aiAuth__signInButton" disabled={loading}>
            {loading ? t('login.signingIn') : t('login.signIn')}
          </button>
        </form>
      </div>
    </section>
  );
}
