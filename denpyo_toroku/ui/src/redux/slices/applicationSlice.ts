/**
 * Application global state slice
 */
import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { ApplicationGlobalType } from '../../types/appTypes';

const initialState: ApplicationGlobalType = {
  isLoading: false,
  isAuthenticated: false,
  currentView: 'dashboard',
  isDrawerOpen: false,
  isSidebarCollapsed: false,
  userName: 'hello@oracle.com',
  appTitle: 'AI Database Private Agent Factory'
};

const applicationSlice = createSlice({
  name: 'application',
  initialState,
  reducers: {
    setLoading(state, action: PayloadAction<boolean>) {
      state.isLoading = action.payload;
    },
    setAuthenticated(state, action: PayloadAction<boolean>) {
      state.isAuthenticated = action.payload;
    },
    setCurrentView(state, action: PayloadAction<string>) {
      state.currentView = action.payload;
    },
    toggleDrawer(state) {
      state.isDrawerOpen = !state.isDrawerOpen;
    },
    setDrawerOpen(state, action: PayloadAction<boolean>) {
      state.isDrawerOpen = action.payload;
    },
    toggleSidebar(state) {
      state.isSidebarCollapsed = !state.isSidebarCollapsed;
    },
    setSidebarCollapsed(state, action: PayloadAction<boolean>) {
      state.isSidebarCollapsed = action.payload;
    },
    setUserName(state, action: PayloadAction<string>) {
      state.userName = action.payload;
    }
  }
});

export const {
  setLoading,
  setAuthenticated,
  setCurrentView,
  toggleDrawer,
  setDrawerOpen,
  toggleSidebar,
  setSidebarCollapsed,
  setUserName
} = applicationSlice.actions;

export default applicationSlice.reducer;
