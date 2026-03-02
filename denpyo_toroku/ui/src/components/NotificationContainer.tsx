/**
 * Notification container - Custom toast notifications
 * Replaces Oracle JET MessageToast with app-native design system styling
 */
import { h } from 'preact';
import { useCallback, useEffect, useRef } from 'preact/hooks';
import { useAppSelector, useAppDispatch } from '../redux/store';
import { removeNotification } from '../redux/slices/notificationsSlice';
import type { NotificationItem } from '../types/componentTypes';
import { CheckCircle, AlertCircle, AlertTriangle, Info, X } from 'lucide-react';

const AUTO_CLOSE_DURATION = 5000;

const ICON_MAP: Record<NotificationItem['type'], typeof CheckCircle> = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

function ToastItem({
  notification,
  onDismiss,
}: {
  notification: NotificationItem;
  onDismiss: (id: string) => void;
}) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const itemRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (notification.autoClose !== false) {
      timerRef.current = setTimeout(() => {
        if (itemRef.current) {
          itemRef.current.classList.add('ics-toast-item--removing');
          setTimeout(() => onDismiss(notification.id), 280);
        } else {
          onDismiss(notification.id);
        }
      }, AUTO_CLOSE_DURATION);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [notification.id, notification.autoClose, onDismiss]);

  const handleClose = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (itemRef.current) {
      itemRef.current.classList.add('ics-toast-item--removing');
      setTimeout(() => onDismiss(notification.id), 280);
    } else {
      onDismiss(notification.id);
    }
  }, [notification.id, onDismiss]);

  const Icon = ICON_MAP[notification.type];

  return (
    <div
      ref={itemRef}
      class={`ics-toast-item ics-toast-item--${notification.type}`}
      role="alert"
      aria-live="assertive"
    >
      <span class="ics-toast-item__icon">
        <Icon size={18} />
      </span>
      <span class="ics-toast-item__message">{notification.message}</span>
      <button
        type="button"
        class="ics-toast-item__close"
        onClick={handleClose}
        aria-label="閉じる"
      >
        <X size={14} />
      </button>
    </div>
  );
}

export function NotificationContainer() {
  const dispatch = useAppDispatch();
  const notifications = useAppSelector(state => state.notifications.notifications);

  const handleDismiss = useCallback((id: string) => {
    dispatch(removeNotification(id));
  }, [dispatch]);

  if (notifications.length === 0) return null;

  return (
    <div class="ics-toast-container" aria-label="通知">
      {notifications.map(n => (
        <ToastItem
          key={n.id}
          notification={n}
          onDismiss={handleDismiss}
        />
      ))}
    </div>
  );
}
