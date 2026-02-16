/**
 * Notification context
 */
import { createContext } from 'preact';
import { NotificationContainerType } from '../types/componentTypes';

export const NotificationContext = createContext<NotificationContainerType>({
  notifications: []
});
