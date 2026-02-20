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
import { ApplicationSettings } from '../views/applicationSettings/ApplicationSettings';
import { OciGenAiModelSettings } from '../views/ociGenAiModelSettings/OciGenAiModelSettings';
import { OciObjectStorageSettings } from '../views/ociObjectStorageSettings/OciObjectStorageSettings';
import { DatabaseSettings } from '../views/databaseSettings/DatabaseSettings';
import { UploadView } from '../views/upload/UploadView';
import { ListView } from '../views/fileList/ListView';
import { AnalysisView } from '../views/analysis/AnalysisView';
import { RegistrationView } from '../views/registration/RegistrationView';
import { CategoryView } from '../views/category/CategoryView';
import { SearchView } from '../views/search/SearchView';
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
    case 'upload':
      return <UploadView />;
    case 'fileList':
      return <ListView />;
    case 'analysis':
      return <AnalysisView />;
    case 'registration':
      return <RegistrationView />;
    case 'categorySamples':
      return <CategoryView mode="samples" />;
    case 'categoryManagement':
      return <CategoryView mode="management" />;
    case 'search':
      return <SearchView />;
    case 'applicationSettings':
      return <ApplicationSettings />;
    case 'ociGenAiModelSettings':
      return <OciGenAiModelSettings />;
    case 'ociObjectStorageSettings':
      return <OciObjectStorageSettings />;
    case 'databaseSettings':
      return <DatabaseSettings />;
    default:
      return <Dashboard />;
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
