/**
 * Notification container - Oracle JET Redwood MessageToast
 * Uses @oracle/oraclejet-preact MessageToast component
 */
import { h } from 'preact';
import { useMemo, useCallback } from 'preact/hooks';
import { useAppSelector, useAppDispatch } from '../redux/store';
import { removeNotification } from '../redux/slices/notificationsSlice';
import { MessageToast } from '@oracle/oraclejet-preact/UNSAFE_MessageToast';
import type { MessageToastItem } from '@oracle/oraclejet-preact/UNSAFE_MessageToast';

type SeverityType = 'error' | 'warning' | 'confirmation' | 'info' | 'none';

const severityMap: Record<string, SeverityType> = {
  success: 'confirmation',
  warning: 'warning',
  error: 'error',
  info: 'info'
};

export function NotificationContainer() {
  const dispatch = useAppDispatch();
  const notifications = useAppSelector(state => state.notifications.notifications);

  const toastData = useMemo(() => {
    return notifications.map(n => ({
      key: n.id,
      data: {
        summary: n.message,
        severity: severityMap[n.type] || ('info' as SeverityType),
        autoTimeout: (n.autoClose !== false ? 'on' : 'off') as 'on' | 'off',
        closeAffordance: 'on' as const
      } as MessageToastItem,
      metadata: { key: n.id }
    }));
  }, [notifications]);

  const handleClose = useCallback((item: any) => {
    const key = item?.key ?? item?.metadata?.key;
    if (key) {
      dispatch(removeNotification(String(key)));
    }
  }, [dispatch]);

  if (notifications.length === 0) return null;

  return (
    <MessageToast
      data={toastData}
      onClose={handleClose}
      position="top-end"
      offset={{ horizontal: 16, vertical: 60 }}
    />
  );
}
