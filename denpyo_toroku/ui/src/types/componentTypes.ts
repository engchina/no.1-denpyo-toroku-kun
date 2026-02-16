/**
 * UI Component type definitions
 */

export interface NotificationItem {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
  timestamp: number;
  autoClose?: boolean;
}

/**
 * JET MessageToast compatible message item
 */
export interface JetMessageToastItem {
  summary: string;
  detail?: string;
  severity?: 'error' | 'warning' | 'confirmation' | 'info' | 'none';
  autoTimeout?: 'on' | 'off';
  closeAffordance?: 'on' | 'off';
}

export interface NotificationContainerType {
  notifications: NotificationItem[];
}

export interface TabItem {
  id: string;
  name: string;
  icon?: string;
  closeable?: boolean;
}

export interface StatusBadgeProps {
  status: string;
  label?: string;
}

export interface ConfidenceDisplayProps {
  confidence: number;
}
