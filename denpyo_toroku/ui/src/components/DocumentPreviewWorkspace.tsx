import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { AlertTriangle, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, ImageIcon, Loader2, RotateCcw, RotateCw } from 'lucide-react';
import { apiGet } from '../utils/apiUtils';
import { t } from '../i18n';
import type { DocumentPreviewPage, DocumentPreviewResponse, PageOcrText } from '../types/denpyoTypes';

type ViewerMode = 'fit-width' | 'fit-page' | 'zoom';
type PageImageMetrics = {
  width: number;
  height: number;
};

type PreviewWorkspacePage = DocumentPreviewPage & {
  fileId: string;
  fileName: string;
  key: string;
};

const ZOOM_STEPS: readonly number[] = [100, 125, 150, 175, 200, 250, 300];

function buildPageKey(fileId: string, pageIndex: number): string {
  return `${fileId}:${pageIndex}`;
}

function normalizeRotation(rotation: number): number {
  const normalized = rotation % 360;
  return normalized < 0 ? normalized + 360 : normalized;
}

export function DocumentPreviewWorkspace({
  fileIds,
  title,
  hint,
  collapsible = false,
  isCollapsed = false,
  onToggleCollapsed,
  pageTextsByFileId,
}: {
  fileIds: Array<string | number>;
  title?: string;
  hint?: string;
  collapsible?: boolean;
  isCollapsed?: boolean;
  onToggleCollapsed?: (nextCollapsed: boolean) => void;
  pageTextsByFileId?: Record<string, PageOcrText[]>;
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
  const [pageMetrics, setPageMetrics] = useState<Record<string, PageImageMetrics>>({});
  const [pageRotations, setPageRotations] = useState<Record<string, number>>({});
  const [showVlmPanel, setShowVlmPanel] = useState(false);
  const viewerRef = useRef<HTMLDivElement | null>(null);

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
    setPageMetrics({});
    setPageRotations({});
    setViewerMode('fit-width');
    setZoomPercent(ZOOM_STEPS[1]);
    setShowVlmPanel(false);
    void loadPages();

    return () => {
      cancelled = true;
    };
  }, [normalizedFileIds.join(',')]);

  const activePage = pages.find((page) => page.key === activePageKey) || pages[0] || null;
  const currentIndex = activePage ? pages.findIndex((page) => page.key === activePage.key) : -1;
  const activePageVlmText = useMemo(() => {
    if (!activePage || !pageTextsByFileId) return '';
    return (pageTextsByFileId[activePage.fileId] ?? []).find((pt) => pt.page_index === activePage.page_index)?.text ?? '';
  }, [activePage?.fileId, activePage?.page_index, pageTextsByFileId]);
  const hasAnyPageTexts = useMemo(
    () => pageTextsByFileId != null && Object.values(pageTextsByFileId).some((arr) => arr.length > 0),
    [pageTextsByFileId]
  );
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
  const currentPageRotation = activePage ? normalizeRotation(pageRotations[activePage.key] ?? 0) : 0;
  const showThumbnailStrip = pages.length > 0;
  const canToggleCollapse = collapsible && typeof onToggleCollapsed === 'function';
  const collapsedTitle = [title || t('category.designer.reviewWorkspace'), currentLabel].filter(Boolean).join(' ');
  const currentImageFrameClass =
    viewerMode === 'fit-page'
      ? 'ics-category-viewer__frame ics-category-viewer__frame--fit-page'
      : viewerMode === 'zoom'
        ? 'ics-category-viewer__frame ics-category-viewer__frame--zoom'
        : 'ics-category-viewer__frame ics-category-viewer__frame--fit-width';

  const getPageLayout = (pageKey: string) => {
    const metrics = pageMetrics[pageKey];
    const rotation = normalizeRotation(pageRotations[pageKey] ?? 0);
    const isQuarterTurn = rotation % 180 !== 0;
    const originalAspectRatio = metrics ? metrics.width / metrics.height : 1;
    const displayAspectRatio = metrics
      ? isQuarterTurn
        ? metrics.height / metrics.width
        : originalAspectRatio
      : 1;

    return {
      metrics,
      rotation,
      displayAspectRatio,
      rotationShellStyle: {
        width: metrics && isQuarterTurn ? `${originalAspectRatio * 100}%` : '100%',
        height: metrics && isQuarterTurn ? `${(1 / originalAspectRatio) * 100}%` : '100%',
        transform: `translate(-50%, -50%) rotate(${rotation}deg)`,
      },
    };
  };

  const buildMainFrameStyle = (pageKey: string) => {
    const { displayAspectRatio } = getPageLayout(pageKey);
    if (viewerMode === 'fit-page') {
      return {
        width: `min(100%, calc((100vh - 420px) * ${displayAspectRatio}))`,
        maxWidth: '100%',
        aspectRatio: `${displayAspectRatio}`,
      };
    }
    if (viewerMode === 'zoom') {
      return {
        width: `${zoomPercent}%`,
        maxWidth: 'none',
        aspectRatio: `${displayAspectRatio}`,
      };
    }
    return {
      width: '100%',
      aspectRatio: `${displayAspectRatio}`,
    };
  };

  const buildThumbnailFrameStyle = (pageKey: string) => {
    const { displayAspectRatio } = getPageLayout(pageKey);
    return {
      width: `min(100%, calc(var(--ics-thumbnail-frame-height) * ${displayAspectRatio}))`,
      maxWidth: '100%',
      aspectRatio: `${displayAspectRatio}`,
    };
  };

  const handleImageLoad = (pageKey: string) => (event: Event) => {
    const target = event.currentTarget as HTMLImageElement | null;
    if (!target?.naturalWidth || !target?.naturalHeight) return;

    setPageMetrics((prev) => {
      const current = prev[pageKey];
      if (current && current.width === target.naturalWidth && current.height === target.naturalHeight) {
        return prev;
      }
      return {
        ...prev,
        [pageKey]: {
          width: target.naturalWidth,
          height: target.naturalHeight,
        },
      };
    });
  };

  useEffect(() => {
    if (!activePage) return;

    const viewer = viewerRef.current;
    if (!viewer) return;

    const frame = viewer.querySelector('.ics-category-viewer__frame') as HTMLDivElement | null;
    if (!frame) return;

    const animationFrame = window.requestAnimationFrame(() => {
      const nextLeft = Math.max(0, (frame.offsetLeft + frame.offsetWidth / 2) - (viewer.clientWidth / 2));
      viewer.scrollTo({
        left: nextLeft,
        top: 0,
        behavior: 'auto',
      });
    });

    return () => window.cancelAnimationFrame(animationFrame);
  }, [
    activePage?.key,
    currentPageRotation,
    viewerMode,
    pageMetrics[activePage?.key || '']?.width,
    pageMetrics[activePage?.key || '']?.height,
  ]);

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

  const handleRotate = (direction: 'left' | 'right') => {
    if (!activePage) return;

    setPageRotations((prev) => {
      const currentRotation = normalizeRotation(prev[activePage.key] ?? 0);
      const delta = direction === 'right' ? 90 : -90;
      const nextRotation = normalizeRotation(currentRotation + delta);

      if (nextRotation === 0) {
        const nextRotations = { ...prev };
        delete nextRotations[activePage.key];
        return nextRotations;
      }

      return {
        ...prev,
        [activePage.key]: nextRotation,
      };
    });
  };

  return (
    <div class={`ics-category-review-panel ${isCollapsed ? 'is-collapsed' : ''}`}>
      <div class={`ics-card ics-card--flat ics-category-review-card ${isCollapsed ? 'is-collapsed' : ''}`}>
        {isCollapsed ? (
          <div class="ics-category-review-rail" title={collapsedTitle} aria-label={collapsedTitle}>
            <div class="ics-category-review-rail__marker">
              <ImageIcon size={18} />
            </div>
            {activePage && <span class="ics-category-review-rail__meta">{currentIndex + 1}</span>}
            {canToggleCollapse && (
              <button
                type="button"
                class="ics-ops-btn ics-ops-btn--ghost ics-category-review-toolbar__btn ics-category-review-toolbar__btn--toggle ics-category-review-rail__toggle"
                onClick={() => onToggleCollapsed?.(false)}
                title={t('category.designer.expandReview')}
                aria-label={t('category.designer.expandReview')}
                aria-expanded={false}
              >
                <ChevronRight size={15} />
              </button>
            )}
          </div>
        ) : (
          <div class={`ics-card-header ics-category-review-card__header ${isCollapsed ? 'ics-category-review-card__header--collapsed' : ''}`}>
            <div class="ics-category-review-card__heading">
              <ImageIcon size={16} />
              <span class="ics-category-review-card__headingLabel">{title || t('category.designer.reviewWorkspace')}</span>
              {activePage && !isCollapsed && <span class="ics-category-review-card__meta">{currentLabel}</span>}
            </div>
            <div class="ics-category-review-toolbar">
              {!isCollapsed && (
                <>
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
                    onClick={() => handleRotate('left')}
                    disabled={!activePage}
                    title={t('category.designer.rotateLeft')}
                    aria-label={t('category.designer.rotateLeft')}
                  >
                    <RotateCcw size={15} />
                  </button>
                  <button
                    type="button"
                    class="ics-ops-btn ics-ops-btn--ghost ics-category-review-toolbar__btn"
                    onClick={() => handleRotate('right')}
                    disabled={!activePage}
                    title={t('category.designer.rotateRight')}
                    aria-label={t('category.designer.rotateRight')}
                  >
                    <RotateCw size={15} />
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
                </>
              )}
              {canToggleCollapse && (
                <button
                  type="button"
                  class="ics-ops-btn ics-ops-btn--ghost ics-category-review-toolbar__btn ics-category-review-toolbar__btn--toggle"
                  onClick={() => onToggleCollapsed?.(!isCollapsed)}
                  title={isCollapsed ? t('category.designer.expandReview') : t('category.designer.collapseReview')}
                  aria-label={isCollapsed ? t('category.designer.expandReview') : t('category.designer.collapseReview')}
                  aria-expanded={!isCollapsed}
                >
                  {isCollapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
                </button>
              )}
            </div>
          </div>
        )}

        {!isCollapsed && (
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
                <div class="ics-category-viewer" ref={viewerRef}>
                  <div class={`ics-category-viewer__stage ${viewerMode === 'fit-page' ? 'ics-category-viewer__stage--fit-page' : ''}`}>
                    {currentImageHasError ? (
                      <div class="ics-category-viewer__empty">
                        <ImageIcon size={30} />
                        <span>{t('documentPreview.loadFailed')}</span>
                      </div>
                    ) : (
                      <div class={currentImageFrameClass} style={buildMainFrameStyle(activePage.key)}>
                        <div class="ics-category-viewer__rotation" style={getPageLayout(activePage.key).rotationShellStyle}>
                          <img
                            src={`/studio/api/v1/files/${activePage.fileId}/preview-pages/${activePage.page_index}`}
                            alt={activePage.page_label || activePage.fileName}
                            class="ics-category-viewer__image"
                            onLoad={handleImageLoad(activePage.key)}
                            onError={() => setImgErrors((prev) => ({ ...prev, [activePage.key]: true }))}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {showThumbnailStrip && (
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
                              <div class="ics-category-thumbnail__media" style={buildThumbnailFrameStyle(page.key)}>
                                <div class="ics-category-thumbnail__rotation" style={getPageLayout(page.key).rotationShellStyle}>
                                  <img
                                    src={`/studio/api/v1/files/${page.fileId}/preview-pages/${page.page_index}`}
                                    alt={page.page_label || page.fileName}
                                    class="ics-category-thumbnail__image"
                                    onLoad={handleImageLoad(page.key)}
                                    onError={() => setImgErrors((prev) => ({ ...prev, [page.key]: true }))}
                                  />
                                </div>
                              </div>
                            )}
                          </div>
                          <span class="ics-category-thumbnail__label">{page.page_label || t('category.designer.imageLabel', { index: index + 1 })}</span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {hasAnyPageTexts && (
                  <div class="ics-vlm-panel">
                    <button
                      type="button"
                      class="ics-vlm-panel__toggle"
                      onClick={() => setShowVlmPanel((prev) => !prev)}
                      aria-expanded={showVlmPanel}
                    >
                      {showVlmPanel ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      <span>{showVlmPanel ? t('documentPreview.vlmOutputHide') : t('documentPreview.vlmOutputShow')}</span>
                    </button>
                    {showVlmPanel && (
                      <div class="ics-vlm-panel__body">
                        <div class="ics-vlm-panel__label">{t('documentPreview.vlmOutput')}</div>
                        {activePageVlmText ? (
                          <pre class="ics-vlm-panel__text">{activePageVlmText}</pre>
                        ) : (
                          <div class="ics-vlm-panel__empty">{t('documentPreview.vlmOutputEmpty')}</div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
