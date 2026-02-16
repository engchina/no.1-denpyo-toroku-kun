/**
 * Notifications state slice
 */
import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { NotificationItem, NotificationContainerType } from '../../types/componentTypes';

const initialState: NotificationContainerType = {
  notifications: []
};

let nextId = 1;

const notificationsSlice = createSlice({
  name: 'notifications',
  initialState,
  reducers: {
    addNotification(state, action: PayloadAction<Omit<NotificationItem, 'id' | 'timestamp'>>) {
      state.notifications.push({
        ...action.payload,
        id: String(nextId++),
        timestamp: Date.now()
      });
    },
    removeNotification(state, action: PayloadAction<string>) {
      state.notifications = state.notifications.filter(n => n.id !== action.payload);
    },
    clearNotifications(state) {
      state.notifications = [];
    }
  }
});

export const { addNotification, removeNotification, clearNotifications } = notificationsSlice.actions;

export default notificationsSlice.reducer;
