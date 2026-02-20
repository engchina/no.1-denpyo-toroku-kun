import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { AlertTriangle, AlertCircle, CheckCircle, Info, X } from 'lucide-react';

type ConfirmSeverity = 'error' | 'warning' | 'confirmation' | 'info' | 'none';

type ToastConfirmRequest = {
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
        style={{ maxWidth: '520px' }}
        role="alertdialog"
        aria-modal="true"
        aria-label={request.message}
        onClick={(e: Event) => e.stopPropagation()}
      >
        <div class="ics-modal__header">
          <h3 class="ics-toast-confirm-modal__title">
            <span class="ics-toast-confirm-modal__icon" style={{ color: accentColor }}>
              <SeverityIcon severity={sev} />
            </span>
            <span>{request.message}</span>
          </h3>
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={onClose}
            aria-label="閉じる"
          >
            <X size={16} />
          </button>
        </div>
        <div class="ics-modal__footer">
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={onClose}
          >
            {request.cancelLabel}
          </button>
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
            onClick={onConfirm}
          >
            {request.confirmLabel}
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
