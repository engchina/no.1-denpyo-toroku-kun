import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { AlertTriangle, AlertCircle, CheckCircle, Info, X, Check } from 'lucide-react';
import { t } from '../i18n';

type ConfirmSeverity = 'error' | 'warning' | 'confirmation' | 'info' | 'none';

type ToastConfirmRequest = {
  title?: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  severity?: ConfirmSeverity;
  onConfirm: () => void | Promise<void>;
};

type PendingConfirmRequest = ToastConfirmRequest & {
  id: string;
};

const SEVERITY_ACCENT: Record<ConfirmSeverity, string> = {
  warning:      '#d97706',
  error:        '#dc2626',
  confirmation: '#16a34a',
  info:         '#2563eb',
  none:         '#60646c',
};

function SeverityIcon({ severity }: { severity: ConfirmSeverity }) {
  switch (severity) {
    case 'error':        return <AlertCircle size={16} />;
    case 'confirmation': return <CheckCircle size={16} />;
    case 'info':         return <Info size={16} />;
    default:             return <AlertTriangle size={16} />;
  }
}

function ToastConfirmPopup({
  request,
  onConfirm,
  onClose,
}: {
  request: PendingConfirmRequest;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const sev = request.severity ?? 'warning';
  const accentColor = SEVERITY_ACCENT[sev];
  const titleId = `${request.id}-title`;
  const messageId = `${request.id}-message`;
  const title = request.title || t('common.confirmAction', { action: request.confirmLabel });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div class="ics-modal-overlay" onClick={onClose}>
      <div
        class="ics-modal ics-toast-confirm-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
        onClick={(e: Event) => e.stopPropagation()}
      >
        <div class="ics-modal__header ics-toast-confirm-modal__header">
          <div class="ics-toast-confirm-modal__heading">
            <span class="ics-toast-confirm-modal__icon" style={{ color: accentColor }}>
              <SeverityIcon severity={sev} />
            </span>
            <h3 id={titleId} class="ics-toast-confirm-modal__title">{title}</h3>
          </div>
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost ics-toast-confirm-modal__close"
            onClick={onClose}
            aria-label={t('common.close')}
          >
            <X size={16} />
          </button>
        </div>
        <div class="ics-modal__body ics-toast-confirm-modal__body">
          <p id={messageId} class="ics-toast-confirm-modal__message">{request.message}</p>
        </div>
        <div class="ics-modal__footer ics-toast-confirm-modal__footer">
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={onClose}
          >
            <X size={14} />
            <span>{request.cancelLabel}</span>
          </button>
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
            onClick={onConfirm}
          >
            <Check size={14} />
            <span>{request.confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

export function useToastConfirm() {
  const [pendingRequest, setPendingRequest] = useState<PendingConfirmRequest | null>(null);
  const nextIdRef = useRef(1);

  const closeConfirmToast = useCallback(() => {
    setPendingRequest(null);
  }, []);

  const requestConfirm = useCallback((request: ToastConfirmRequest) => {
    const id = `toast-confirm-${nextIdRef.current++}`;
    setPendingRequest({ ...request, id });
  }, []);

  const handleConfirm = useCallback(async () => {
    if (!pendingRequest) return;
    const onConfirm = pendingRequest.onConfirm;
    setPendingRequest(null);
    await onConfirm();
  }, [pendingRequest]);

  const confirmToast = pendingRequest ? (
    <ToastConfirmPopup
      request={pendingRequest}
      onConfirm={handleConfirm}
      onClose={closeConfirmToast}
    />
  ) : null;

  return { requestConfirm, confirmToast };
}
