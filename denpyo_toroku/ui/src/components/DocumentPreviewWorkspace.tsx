import { useEffect, useMemo, useState } from 'preact/hooks';
import { AlertTriangle, ImageIcon, Loader2 } from 'lucide-react';
import { apiGet } from '../utils/apiUtils';
import { t } from '../i18n';
import type { DocumentPreviewPage, DocumentPreviewResponse } from '../types/denpyoTypes';

type ViewerMode = 'fit-width' | 'fit-page' | 'zoom';

type PreviewWorkspacePage = DocumentPreviewPage & {
  fileId: string;
  fileName: string;
  key: string;
};

const ZOOM_STEPS: readonly number[] = [100, 125, 150, 175, 200, 250, 300];

function buildPageKey(fileId: string, pageIndex: number): string {
  return `${fileId}:${pageIndex}`;
}

export function DocumentPreviewWorkspace({
  fileIds,
  title,
  hint,
}: {
  fileIds: Array<string | number>;
  title?: string;
  hint?: string;
}) {
  const normalizedFileIds = useMemo(
    () => Array.from(new Set((fileIds || []).map((fileId) => String(fileId || '')).filter(Boolean))),
    [fileIds.map((fileId) => String(fileId || '')).join(',')]
  );
  const [pages, setPages] = useState<PreviewWorkspacePage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [imgErrors, setImgErrors] = useState<Record<string, boolean>>({});
  const [activePageKey, setActivePageKey] = useState<string>('');
  const [viewerMode, setViewerMode] = useState<ViewerMode>('fit-width');
  const [zoomPercent, setZoomPercent] = useState<number>(ZOOM_STEPS[1]);

  useEffect(() => {
    let cancelled = false;

    const loadPages = async () => {
      if (normalizedFileIds.length === 0) {
        setPages([]);
        setLoadError('');
        setActivePageKey('');
        return;
      }

      setIsLoading(true);
      setLoadError('');

      try {
        const responses = await Promise.all(
          normalizedFileIds.map((fileId) => apiGet<DocumentPreviewResponse>(`/api/v1/files/${fileId}/preview-pages`))
        );
        if (cancelled) return;

        const nextPages = responses.flatMap((response) =>
          (response.pages || []).map((page) => ({
            ...page,
            fileId: response.file_id,
            fileName: response.file_name,
            key: buildPageKey(response.file_id, page.page_index),
          }))
        );

        setPages(nextPages);
        setActivePageKey((currentKey) => {
          if (currentKey && nextPages.some((page) => page.key === currentKey)) {
            return currentKey;
          }
          return nextPages[0]?.key || '';
        });
      } catch (error: unknown) {
        if (cancelled) return;
        setPages([]);
        setActivePageKey('');
        setLoadError(error instanceof Error ? error.message : t('documentPreview.loadFailed'));
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    setImgErrors({});
    setViewerMode('fit-width');
    setZoomPercent(ZOOM_STEPS[1]);
    void loadPages();

    return () => {
      cancelled = true;
    };
  }, [normalizedFileIds.join(',')]);

  const activePage = pages.find((page) => page.key === activePageKey) || pages[0] || null;
  const currentIndex = activePage ? pages.findIndex((page) => page.key === activePage.key) : -1;
  const currentLabel = activePage
    ? t('category.designer.imagePosition', { current: currentIndex + 1, total: pages.length })
    : '';
  const currentZoomLabel =
    viewerMode === 'fit-width'
      ? t('category.designer.zoomLabelFitWidth')
      : viewerMode === 'fit-page'
        ? t('category.designer.zoomLabelFitPage')
        : `${zoomPercent}%`;
  const zoomStepIndex = Math.max(0, ZOOM_STEPS.indexOf(zoomPercent));
  const canZoomOut = viewerMode === 'zoom' && zoomStepIndex > 0;
  const canZoomIn = viewerMode !== 'zoom' || zoomStepIndex < ZOOM_STEPS.length - 1;
  const currentImageHasError = activePage ? Boolean(imgErrors[activePage.key]) : false;
  const currentImageClass =
    viewerMode === 'fit-page'
      ? 'ics-category-viewer__image ics-category-viewer__image--fit-page'
      : viewerMode === 'zoom'
        ? 'ics-category-viewer__image ics-category-viewer__image--zoom'
        : 'ics-category-viewer__image ics-category-viewer__image--fit-width';

  const handleZoom = (direction: 'in' | 'out') => {
    if (direction === 'out' && viewerMode !== 'zoom') return;

    const baseIndex = viewerMode === 'zoom' ? Math.max(0, ZOOM_STEPS.indexOf(zoomPercent)) : 0;
    const nextIndex = direction === 'in'
      ? Math.min(ZOOM_STEPS.length - 1, baseIndex + 1)
      : Math.max(0, baseIndex - 1);
    const nextZoom = ZOOM_STEPS[nextIndex] ?? ZOOM_STEPS[0];

    if (nextZoom <= ZOOM_STEPS[0]) {
      setViewerMode('fit-width');
      setZoomPercent(ZOOM_STEPS[0]);
      return;
    }

    setViewerMode('zoom');
    setZoomPercent(nextZoom);
  };

  return (
    <div class="ics-category-review-panel">
      <div class="ics-card ics-card--flat ics-category-review-card">
        <div class="ics-card-header">
          <div class="ics-category-review-card__heading">
            <ImageIcon size={16} />
            <span>{title || t('category.designer.reviewWorkspace')}</span>
            {activePage && <span class="ics-category-review-card__meta">{currentLabel}</span>}
          </div>
          <div class="ics-category-review-toolbar">
            <button
              type="button"
              class={`ics-ops-btn ics-ops-btn--ghost ics-category-review-toolbar__btn ${viewerMode === 'fit-width' ? 'is-active' : ''}`}
              onClick={() => {
                setViewerMode('fit-width');
                setZoomPercent(ZOOM_STEPS[0]);
              }}
              title={t('category.designer.fitWidth')}
            >
              <span>{t('category.designer.fitWidthShort')}</span>
            </button>
            <button
              type="button"
              class={`ics-ops-btn ics-ops-btn--ghost ics-category-review-toolbar__btn ${viewerMode === 'fit-page' ? 'is-active' : ''}`}
              onClick={() => setViewerMode('fit-page')}
              title={t('category.designer.fitPage')}
            >
              <span>{t('category.designer.fitPageShort')}</span>
            </button>
            <button
              type="button"
              class="ics-ops-btn ics-ops-btn--ghost ics-category-review-toolbar__btn"
              onClick={() => handleZoom('out')}
              disabled={!canZoomOut}
              title={t('category.designer.zoomOut')}
              aria-label={t('category.designer.zoomOut')}
            >
              <span>-</span>
            </button>
            <span class="ics-category-review-toolbar__status">{currentZoomLabel}</span>
            <button
              type="button"
              class="ics-ops-btn ics-ops-btn--ghost ics-category-review-toolbar__btn"
              onClick={() => handleZoom('in')}
              disabled={!canZoomIn}
              title={t('category.designer.zoomIn')}
              aria-label={t('category.designer.zoomIn')}
            >
              <span>+</span>
            </button>
          </div>
        </div>

        <div class="ics-card-body ics-category-review-card__body">
          {hint && <p class="ics-form-hint">{hint}</p>}

          {isLoading ? (
            <div class="ics-category-viewer__empty">
              <Loader2 size={30} class="ics-spin" />
              <span>{t('common.loading')}</span>
            </div>
          ) : loadError ? (
            <div class="ics-category-viewer__empty">
              <AlertTriangle size={30} />
              <span>{loadError}</span>
            </div>
          ) : !activePage ? (
            <div class="ics-category-viewer__empty">
              <ImageIcon size={30} />
              <span>{t('documentPreview.noPages')}</span>
            </div>
          ) : (
            <>
              <div class="ics-category-viewer">
                <div class={`ics-category-viewer__stage ${viewerMode === 'fit-page' ? 'ics-category-viewer__stage--fit-page' : ''}`}>
                  {currentImageHasError ? (
                    <div class="ics-category-viewer__empty">
                      <ImageIcon size={30} />
                      <span>{t('documentPreview.loadFailed')}</span>
                    </div>
                  ) : (
                    <img
                      src={`/studio/api/v1/files/${activePage.fileId}/preview-pages/${activePage.page_index}`}
                      alt={activePage.page_label || activePage.fileName}
                      class={currentImageClass}
                      style={viewerMode === 'zoom' ? { width: `${zoomPercent}%`, maxWidth: 'none' } : undefined}
                      onError={() => setImgErrors((prev) => ({ ...prev, [activePage.key]: true }))}
                    />
                  )}
                </div>
              </div>

              <div class="ics-category-review-card__caption">
                <strong>{activePage.page_label || activePage.fileName}</strong>
                <span>{activePage.source_name || activePage.fileName}</span>
              </div>

              {pages.length > 1 && (
                <div class="ics-category-thumbnail-strip">
                  {pages.map((page, index) => {
                    const hasError = Boolean(imgErrors[page.key]);
                    const selected = page.key === activePage.key;
                    return (
                      <button
                        type="button"
                        key={page.key}
                        class={`ics-category-thumbnail ${selected ? 'is-active' : ''}`}
                        onClick={() => setActivePageKey(page.key)}
                        aria-pressed={selected}
                        title={page.source_name || t('category.designer.selectImage', { index: index + 1 })}
                      >
                        <div class="ics-category-thumbnail__frame">
                          {hasError ? (
                            <div class="ics-category-thumbnail__error">
                              <ImageIcon size={18} />
                            </div>
                          ) : (
                            <img
                              src={`/studio/api/v1/files/${page.fileId}/preview-pages/${page.page_index}`}
                              alt={page.page_label || page.fileName}
                              onError={() => setImgErrors((prev) => ({ ...prev, [page.key]: true }))}
                            />
                          )}
                        </div>
                        <span class="ics-category-thumbnail__label">{page.page_label || t('category.designer.imageLabel', { index: index + 1 })}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
