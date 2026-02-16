import { h } from 'preact';
import { useEffect } from 'preact/hooks';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  isBusy?: boolean;
  confirmVariant?: 'primary' | 'danger';
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmLabel,
  cancelLabel = 'キャンセル',
  isBusy = false,
  confirmVariant = 'primary',
  onConfirm,
  onCancel
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!isOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isBusy) {
        onCancel();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, isBusy, onCancel]);

  if (!isOpen) return null;

  return (
    <div class="aaiModalOverlay" role="presentation" onClick={() => !isBusy && onCancel()}>
      <div
        class="icsConfirmModal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={event => event.stopPropagation()}
      >
        <h3 class="icsConfirmModal__title">{title}</h3>
        <p class="icsConfirmModal__message">{message}</p>
        <div class="icsConfirmModal__actions">
          <button
            class="ics-ops-btn ics-ops-btn--ghost"
            onClick={onCancel}
            disabled={isBusy}
          >
            <span>{cancelLabel}</span>
          </button>
          <button
            class={`ics-ops-btn ${confirmVariant === 'danger' ? 'ics-ops-btn--danger' : 'ics-ops-btn--primary'}`}
            onClick={onConfirm}
            disabled={isBusy}
          >
            <span>{isBusy ? '処理中…' : confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
