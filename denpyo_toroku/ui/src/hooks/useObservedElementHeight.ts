import type { JSX } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';

export function buildSyncedPanelMaxHeightStyle(height: number | null): JSX.CSSProperties | undefined {
  if (!height) return undefined;

  return {
    '--ics-synced-panel-max-height': `${height}px`
  } as JSX.CSSProperties;
}

export function useObservedElementHeight<T extends HTMLElement>(enabled = true) {
  const [element, setElement] = useState<T | null>(null);
  const [height, setHeight] = useState<number | null>(null);
  const elementRef = useCallback((node: T | null) => {
    setElement(currentElement => (currentElement === node ? currentElement : node));
  }, []);

  useEffect(() => {
    if (!enabled || !element) {
      setHeight(null);
      return;
    }

    const updateHeight = () => {
      const nextHeight = Math.round(element.getBoundingClientRect().height);
      setHeight(currentHeight => (currentHeight === nextHeight ? currentHeight : nextHeight));
    };

    updateHeight();

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateHeight);
      return () => window.removeEventListener('resize', updateHeight);
    }

    const observer = new ResizeObserver(() => updateHeight());
    observer.observe(element);
    window.addEventListener('resize', updateHeight);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateHeight);
    };
  }, [element, enabled]);

  return { elementRef, height };
}
