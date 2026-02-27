export const APP_ROUTES = {
  login: '/login',
  welcome: '/welcome',
  dashboard: '/dashboard',
  upload: '/upload',
  fileList: '/file-list',
  analysis: '/analysis',
  registration: '/registration',
  categorySamples: '/category/samples',
  categoryManagement: '/category/management',
  search: '/search',
  settingsApplication: '/settings/application',
  settingsOciGenAi: '/settings/oci-genai',
  settingsObjectStorage: '/settings/oci-object-storage',
  settingsDatabase: '/settings/database',
} as const;

export const FEATURE_ROUTES = {
  upload: APP_ROUTES.upload,
  fileList: APP_ROUTES.fileList,
  categorySamples: APP_ROUTES.categorySamples,
  categoryManagement: APP_ROUTES.categoryManagement,
  search: APP_ROUTES.search,
} as const;

export type FeatureRouteKey = keyof typeof FEATURE_ROUTES;

