import { useCallback, useRef, useState } from 'preact/hooks';
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

  return (
    <div class="ics-toast-confirm" role="alertdialog" aria-label={request.message}>
      {/* .ics-modal__header と同一構造: justify-content: space-between */}
      <div class="ics-toast-confirm__header">
        <div class="ics-toast-confirm__title">
          <span class="ics-toast-confirm__icon" style={{ color: accentColor }}>
            <SeverityIcon severity={sev} />
          </span>
          <p class="ics-toast-confirm__message">{request.message}</p>
        </div>
        {/* .ics-modal__header の X ボタンと同じクラス・サイズ */}
        <button
          type="button"
          class="ics-ops-btn ics-ops-btn--ghost"
          onClick={onClose}
          aria-label="閉じる"
        >
          <X size={16} />
        </button>
      </div>
      {/* .ics-modal__footer と同一構造: キャンセル（左）→ 実行（右） */}
      <div class="ics-toast-confirm__footer">
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
