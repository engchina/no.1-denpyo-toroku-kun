import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import type { LucideIcon } from 'lucide-react';
import { X } from 'lucide-react';
import { t } from '../i18n';

type ConfirmSeverity = 'error' | 'warning' | 'confirmation' | 'info' | 'none';
type ConfirmVariant = 'primary' | 'danger';

export type ToastConfirmRequest = {
  title?: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  severity?: ConfirmSeverity;
  confirmVariant?: ConfirmVariant;
  confirmIcon?: LucideIcon;
  onConfirm: () => void | Promise<void>;
};

type PendingConfirmRequest = ToastConfirmRequest & {
  id: string;
};

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
  const titleId = `${request.id}-title`;
  const messageId = `${request.id}-message`;
  const title = request.title || t('common.confirmAction', { action: request.confirmLabel });
  const confirmVariant = request.confirmVariant ?? ((sev === 'warning' || sev === 'error') ? 'danger' : 'primary');
  const ConfirmIcon = request.confirmIcon;
  const confirmButtonClass = confirmVariant === 'danger'
    ? 'ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger'
    : 'ics-ops-btn ics-ops-btn--primary';

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
          <h3 id={titleId} class="ics-toast-confirm-modal__title">{title}</h3>
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
          <p id={messageId} class="ics-form-hint ics-toast-confirm-modal__message">{request.message}</p>
        </div>
        <div class="ics-modal__footer ics-toast-confirm-modal__footer">
          <button
            type="button"
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={onClose}
          >
            <span>{request.cancelLabel}</span>
          </button>
          <button
            type="button"
            class={confirmButtonClass}
            onClick={onConfirm}
          >
            {ConfirmIcon && <ConfirmIcon size={14} />}
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
