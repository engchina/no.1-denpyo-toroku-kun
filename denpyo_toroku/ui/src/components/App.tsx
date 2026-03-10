/**
 * App.tsx - Root application component
 * Reference AgentStudio Grid Layout: Header(span3) + SideNav + Content(span2) + Footer(span3)
 */
import { useMemo, useEffect, useState } from 'preact/hooks';
import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom';
import { Provider } from 'react-redux';
import { store, useAppSelector, useAppDispatch } from '../redux/store';
import { RootEnvironmentProvider } from '@oracle/oraclejet-preact/UNSAFE_Environment';
import type { RootEnvironment } from '@oracle/oraclejet-preact/UNSAFE_Environment';
import jaBundle from '@oracle/oraclejet-preact/resources/nls/ja/bundle';
import { Header } from './layoutAndNavigation/header/Header';
import { SideTabBar } from './layoutAndNavigation/sideTabBar/SideTabBar';
import { Footer } from './layoutAndNavigation/footer/Footer';
const WelcomeView = lazy(() => import('../views/welcome/WelcomeView').then(m => ({ default: m.WelcomeView })));
const Dashboard = lazy(() => import('../views/dashboard/Dashboard').then(m => ({ default: m.Dashboard })));
const ApplicationSettings = lazy(() => import('../views/applicationSettings/ApplicationSettings').then(m => ({ default: m.ApplicationSettings })));
const OciGenAiModelSettings = lazy(() => import('../views/ociGenAiModelSettings/OciGenAiModelSettings').then(m => ({ default: m.OciGenAiModelSettings })));
const OciObjectStorageSettings = lazy(() => import('../views/ociObjectStorageSettings/OciObjectStorageSettings').then(m => ({ default: m.OciObjectStorageSettings })));
const DatabaseSettings = lazy(() => import('../views/databaseSettings/DatabaseSettings').then(m => ({ default: m.DatabaseSettings })));
const UploadView = lazy(() => import('../views/upload/UploadView').then(m => ({ default: m.UploadView })));
const ListView = lazy(() => import('../views/fileList/ListView').then(m => ({ default: m.ListView })));
const RegistrationView = lazy(() => import('../views/registration/RegistrationView').then(m => ({ default: m.RegistrationView })));
const CategoryView = lazy(() => import('../views/category/CategoryView').then(m => ({ default: m.CategoryView })));
const SearchView = lazy(() => import('../views/search/SearchView').then(m => ({ default: m.SearchView })));
import { NotificationContainer } from './NotificationContainer';
import { LoginView } from '../views/login/LoginView';
import { setAuthenticated, setUserName } from '../redux/slices/applicationSlice';
import { apiGet } from '../utils/apiUtils';
import { clearPaginationParamsOutsideView } from '../utils/queryScope';
import { APP_ROUTES } from '../constants/routes';
import { t } from '../i18n';
import '../styles/app.css';

function AppShell() {
  const isSidebarCollapsed = useAppSelector(state => state.application.isSidebarCollapsed);

  const layoutClass = isSidebarCollapsed
    ? 'aaiLayout--asideLess__expanded'
    : 'aaiLayout--asideLess';

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
        <Suspense fallback={<div class="oj-sm-padding-4x">Loading...</div>}>
          <Outlet />
        </Suspense>
      </section>
      <Footer />
      <NotificationContainer />
    </main>
  );
}

function LocationListener() {
  const location = useLocation();
  useEffect(() => {
    clearPaginationParamsOutsideView(location.pathname);
  }, [location.pathname]);
  return null;
}

function ProtectedLayout() {
  const isAuthenticated = useAppSelector(state => state.application.isAuthenticated);
  const location = useLocation();
  if (!isAuthenticated) {
    const from = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={APP_ROUTES.login} state={{ from }} replace />;
  }
  return <AppShell />;
}

function LoginPage() {
  return (
    <>
      <LoginView />
      <NotificationContainer />
    </>
  );
}

function LoginRoute() {
  const isAuthenticated = useAppSelector(state => state.application.isAuthenticated);
  const location = useLocation();
  const redirectTarget = (location.state as { from?: string } | null)?.from;
  if (isAuthenticated) {
    const nextPath = redirectTarget && redirectTarget !== APP_ROUTES.login
      ? redirectTarget
      : APP_ROUTES.dashboard;
    return <Navigate to={nextPath} replace />;
  }
  return <LoginPage />;
}

function AnalysisRouteRedirect() {
  const location = useLocation();
  return <Navigate to={`${APP_ROUTES.registration}${location.search}`} replace />;
}

function AppRoutes() {
  const dispatch = useAppDispatch();
  const isAuthenticated = useAppSelector(state => state.application.isAuthenticated);
  const [sessionReady, setSessionReady] = useState(false);

  useEffect(() => {
    const loadSession = async () => {
      try {
        const me = await apiGet<{ user?: string; authenticated: boolean }>('/v1/me');
        dispatch(setUserName(me.user || 'admin'));
        dispatch(setAuthenticated(Boolean(me.authenticated)));
      } catch {
        dispatch(setAuthenticated(false));
      } finally {
        setSessionReady(true);
      }
    };
    loadSession();
  }, [dispatch]);

  if (!sessionReady) {
    return <div class="oj-sm-padding-4x">Loading...</div>;
  }

  return (
    <>
      <LocationListener />
      <Routes>
        <Route path={APP_ROUTES.login} element={<LoginRoute />} />
        <Route element={<ProtectedLayout />}>
          <Route path={APP_ROUTES.welcome} element={<WelcomeView />} />
          <Route path={APP_ROUTES.dashboard} element={<Dashboard />} />
          <Route path={APP_ROUTES.upload} element={<UploadView />} />
          <Route path={APP_ROUTES.fileList} element={<ListView />} />
          <Route path={APP_ROUTES.analysis} element={<AnalysisRouteRedirect />} />
          <Route path={APP_ROUTES.registration} element={<RegistrationView />} />
          <Route path={APP_ROUTES.categorySamples} element={<CategoryView mode="samples" />} />
          <Route path={APP_ROUTES.categoryManagement} element={<CategoryView mode="management" />} />
          <Route path={APP_ROUTES.search} element={<SearchView />} />
          <Route path={APP_ROUTES.settingsApplication} element={<ApplicationSettings />} />
          <Route path={APP_ROUTES.settingsOciGenAi} element={<OciGenAiModelSettings />} />
          <Route path={APP_ROUTES.settingsObjectStorage} element={<OciObjectStorageSettings />} />
          <Route path={APP_ROUTES.settingsDatabase} element={<DatabaseSettings />} />
        </Route>
        <Route
          path="/"
          element={<Navigate to={isAuthenticated ? APP_ROUTES.dashboard : APP_ROUTES.login} replace />}
        />
        <Route
          path="*"
          element={<Navigate to={isAuthenticated ? APP_ROUTES.dashboard : APP_ROUTES.login} replace />}
        />
      </Routes>
    </>
  );
}

export function App() {
  const APP_BASE_PATH = (typeof window !== 'undefined' && /^\/studio(\/|$)/.test(window.location.pathname))
    ? '/studio'
    : undefined;
  const environment = useMemo<RootEnvironment>(() => ({
    translations: {
      '@oracle/oraclejet-preact': jaBundle
    },
    user: { locale: 'ja-JP', direction: 'ltr' }
  }), []);

  return (
    <RootEnvironmentProvider environment={environment}>
      <Provider store={store}>
        <BrowserRouter basename={APP_BASE_PATH}>
          <AppRoutes />
        </BrowserRouter>
      </Provider>
    </RootEnvironmentProvider>
  );
}
