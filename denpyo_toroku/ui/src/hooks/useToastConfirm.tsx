import { h } from 'preact';
import { useCallback, useMemo, useRef, useState } from 'preact/hooks';
import { MessageToast } from '@oracle/oraclejet-preact/UNSAFE_MessageToast';
import type { Item } from '@oracle/oraclejet-preact/utils/UNSAFE_dataProvider';
import type { MessageToastItem } from '@oracle/oraclejet-preact/UNSAFE_MessageToast';

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

export function useToastConfirm() {
  const [pendingRequest, setPendingRequest] = useState<PendingConfirmRequest | null>(null);
  const nextIdRef = useRef(1);

  const closeConfirmToast = useCallback(() => {
    setPendingRequest(null);
  }, []);

  const requestConfirm = useCallback((request: ToastConfirmRequest) => {
    const id = `toast-confirm-${nextIdRef.current++}`;
    setPendingRequest({
      ...request,
      id
    });
  }, []);

  const handleConfirm = useCallback(async () => {
    if (!pendingRequest) return;
    const onConfirm = pendingRequest.onConfirm;
    setPendingRequest(null);
    await onConfirm();
  }, [pendingRequest]);

  const handleToastClose = useCallback((_item: Item<string, MessageToastItem>) => {
    setPendingRequest(null);
  }, []);

  const renderers = useMemo(() => {
    return {
      confirmActions: () => {
        if (!pendingRequest) return null;
        return (
          <div class="ics-toast-confirm__actions">
            <button type="button" class="ics-ops-btn ics-ops-btn--danger" onClick={handleConfirm}>
              {pendingRequest.confirmLabel}
            </button>
            <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={closeConfirmToast}>
              {pendingRequest.cancelLabel}
            </button>
          </div>
        );
      }
    };
  }, [pendingRequest, handleConfirm, closeConfirmToast]);

  const confirmToast = pendingRequest ? (
    <MessageToast
      data={[
        {
          key: pendingRequest.id,
          data: {
            summary: pendingRequest.message,
            severity: pendingRequest.severity || 'warning',
            autoTimeout: 'off',
            closeAffordance: 'on'
          },
          metadata: { key: pendingRequest.id }
        }
      ]}
      detailRendererKey="confirmActions"
      renderers={renderers}
      onClose={handleToastClose}
      position="top-end"
      offset={{ horizontal: 16, vertical: 60 }}
    />
  ) : null;

  return {
    requestConfirm,
    confirmToast
  };
}
