/**
 * パンくずリスト（Oracle JET の Breadcrumb パターン）
 * VDOM/Preact で oj-cca-breadcrumb の挙動を模倣
 * 区切りは Oracle JET の慣例に合わせて「/」を使用
 * 表示: ホーム / [現在ページ]
 */
import { h } from 'preact';
import { useCallback } from 'preact/hooks';
import { useAppSelector, useAppDispatch } from '../../../redux/store';
import { setCurrentView } from '../../../redux/slices/applicationSlice';

interface NavItem {
  path: string;
  label: string;
}

interface BreadcrumbProps {
  navItems: NavItem[];
}

export function Breadcrumb({ navItems }: BreadcrumbProps) {
  const dispatch = useAppDispatch();
  const currentView = useAppSelector(state => state.application.currentView);

  const handleNavigate = useCallback((path: string) => {
    dispatch(setCurrentView(path));
  }, [dispatch]);

  // Find the current nav item label
  const currentItem = navItems.find(item => item.path === currentView);
  const currentLabel = currentItem ? currentItem.label : 'ダッシュボード';
  const isHome = currentView === 'dashboard';

  return (
    <div class="oj-breadcrumb-container" role="navigation" aria-label="パンくずリスト">
      <div class="oj-breadcrumb">
        {/* Home item */}
        {isHome ? (
          <span class="oj-breadcrumb-item oj-breadcrumb-item-current" aria-current="page">
            ホーム
          </span>
        ) : (
          <span class="oj-breadcrumb-item">
            <a
              href="javascript:void(0)"
              class="oj-breadcrumb-item-link"
              onClick={() => handleNavigate('dashboard')}
            >
              ホーム
            </a>
          </span>
        )}

        {/* Separator + Current page */}
        {!isHome && (
          <span class="oj-breadcrumb-item">
            <span class="oj-breadcrumb-separator" aria-hidden="true">/</span>
            <span class="oj-breadcrumb-item-current" aria-current="page">
              {currentLabel}
            </span>
          </span>
        )}
      </div>
    </div>
  );
}
