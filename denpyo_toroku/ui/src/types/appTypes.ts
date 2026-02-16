/**
 * Application-level type definitions
 */

export interface ApplicationGlobalType {
  isLoading: boolean;
  isAuthenticated: boolean;
  currentView: string;
  isDrawerOpen: boolean;
  isSidebarCollapsed: boolean;
  userName: string;
  appTitle: string;
}

export interface FooterLink {
  name: string;
  linkId: string;
  linkTarget: string;
}

export interface NavItem {
  id: string;
  name: string;
  icon: string;
}
