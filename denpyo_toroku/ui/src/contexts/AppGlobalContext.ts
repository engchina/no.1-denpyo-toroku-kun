/**
 * Application global context - reference architecture pattern
 */
import { createContext } from 'preact';
import { ApplicationGlobalType } from '../types/appTypes';

export const AppGlobalContext = createContext<ApplicationGlobalType>({
  isLoading: false,
  isAuthenticated: false,
  isDrawerOpen: false,
  isSidebarCollapsed: false,
  userName: 'john.hancock@oracle.com',
  appTitle: 'Intent Classifier Service'
});
