/**
 * Notification hook for dispatching notifications through Redux
 */
import { useCallback } from 'preact/hooks';
import { useAppDispatch } from '../redux/store';
import { addNotification, removeNotification, clearNotifications } from '../redux/slices/notificationsSlice';

export function useNotification() {
  const dispatch = useAppDispatch();

  const notify = useCallback((type: 'info' | 'success' | 'warning' | 'error', message: string, autoClose = true) => {
    dispatch(addNotification({ type, message, autoClose }));
  }, [dispatch]);

  const notifySuccess = useCallback((message: string) => {
    notify('success', message);
  }, [notify]);

  const notifyError = useCallback((message: string) => {
    notify('error', message, false);
  }, [notify]);

  const notifyWarning = useCallback((message: string) => {
    notify('warning', message);
  }, [notify]);

  const notifyInfo = useCallback((message: string) => {
    notify('info', message);
  }, [notify]);

  const dismiss = useCallback((id: string) => {
    dispatch(removeNotification(id));
  }, [dispatch]);

  const clearAll = useCallback(() => {
    dispatch(clearNotifications());
  }, [dispatch]);

  return { notify, notifySuccess, notifyError, notifyWarning, notifyInfo, dismiss, clearAll };
}
