/**
 * App.tsx - Root application component
 * Reference AgentStudio Grid Layout: Header(span3) + SideNav + Content(span2) + Footer(span3)
 */
import { useMemo, useEffect } from 'preact/hooks';
import { Provider } from 'react-redux';
import { store, useAppSelector, useAppDispatch } from '../redux/store';
import { RootEnvironmentProvider } from '@oracle/oraclejet-preact/UNSAFE_Environment';
import type { RootEnvironment } from '@oracle/oraclejet-preact/UNSAFE_Environment';
import jaBundle from '@oracle/oraclejet-preact/resources/nls/ja/bundle';
import { Header } from './layoutAndNavigation/header/Header';
import { SideTabBar } from './layoutAndNavigation/sideTabBar/SideTabBar';
import { Footer } from './layoutAndNavigation/footer/Footer';
import { WelcomeView } from '../views/welcome/WelcomeView';
import { Dashboard } from '../views/dashboard/Dashboard';
import { Predict } from '../views/predict/Predict';
import { Train } from '../views/train/Train';
import { Stats } from '../views/stats/Stats';
import { ModelInfo } from '../views/modelInfo/ModelInfo';
import { ApplicationSettings } from '../views/applicationSettings/ApplicationSettings';
import { DatabaseSettings } from '../views/databaseSettings/DatabaseSettings';
import { NotificationContainer } from './NotificationContainer';
import { LoginView } from '../views/login/LoginView';
import { setAuthenticated, setUserName } from '../redux/slices/applicationSlice';
import { apiGet } from '../utils/apiUtils';
import { t } from '../i18n';
import '../styles/app.css';

function ViewSwitcher() {
  const currentView = useAppSelector(state => state.application.currentView);

  switch (currentView) {
    case 'gettingStarted':
      return <WelcomeView />;
    case 'dashboard':
      return <Dashboard />;
    case 'predict':
      return <Predict />;
    case 'train':
      return <Train />;
    case 'stats':
      return <Stats />;
    case 'modelInfo':
      return <ModelInfo />;
    case 'applicationSettings':
      return <ApplicationSettings />;
    case 'databaseSettings':
      return <DatabaseSettings />;
    default:
      return <WelcomeView />;
  }
}

function AppLayout() {
  const dispatch = useAppDispatch();
  const isAuthenticated = useAppSelector(state => state.application.isAuthenticated);
  const isSidebarCollapsed = useAppSelector(state => state.application.isSidebarCollapsed);

  const layoutClass = isSidebarCollapsed
    ? 'aaiLayout--asideLess__expanded'
    : 'aaiLayout--asideLess';

  useEffect(() => {
    const loadSession = async () => {
      try {
        const me = await apiGet<{ user?: string; authenticated: boolean }>('/v1/me');
        dispatch(setUserName(me.user || 'admin'));
        dispatch(setAuthenticated(Boolean(me.authenticated)));
      } catch {
        dispatch(setAuthenticated(false));
      }
    };
    loadSession();
  }, [dispatch]);

  if (!isAuthenticated) {
    return (
      <>
        <LoginView />
        <NotificationContainer />
      </>
    );
  }

  return (
    <main
      id="aaiLayout"
      aria-label={t('app.aria.mainRegion')}
      tabIndex={0}
      class={layoutClass}
    >
      <Header />
      <SideTabBar />
      <section class="aaiSection aaiLayout--item oj-sm-padding-6x aaiLayout--item__span2">
        <ViewSwitcher />
      </section>
      <Footer />
      <NotificationContainer />
    </main>
  );
}

export function App() {
  const environment = useMemo<RootEnvironment>(() => ({
    translations: {
      '@oracle/oraclejet-preact': jaBundle
    },
    user: { locale: 'ja-JP', direction: 'ltr' }
  }), []);

  return (
    <RootEnvironmentProvider environment={environment}>
      <Provider store={store}>
        <AppLayout />
      </Provider>
    </RootEnvironmentProvider>
  );
}
