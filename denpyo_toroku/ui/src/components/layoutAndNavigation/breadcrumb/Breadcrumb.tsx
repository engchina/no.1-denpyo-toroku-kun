/**
 * パンくずリスト（Oracle JET の Breadcrumb パターン）
 * VDOM/Preact で oj-cca-breadcrumb の挙動を模倣
 * 区切りは Oracle JET の慣例に合わせて「/」を使用
 * 表示: ホーム / [現在ページ]
 */
import { useLocation, useNavigate } from 'react-router-dom';
import { APP_ROUTES } from '../../../constants/routes';

interface NavItem {
  path: string;
  label: string;
}

interface BreadcrumbProps {
  navItems: NavItem[];
}

export function Breadcrumb({ navItems }: BreadcrumbProps) {
  const location = useLocation();
  const navigate = useNavigate();

  // Find the current nav item label
  const currentItem = navItems.find(item => item.path === location.pathname);
  const currentLabel = currentItem ? currentItem.label : 'ダッシュボード';
  const isHome = location.pathname === APP_ROUTES.dashboard;

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
              href={APP_ROUTES.dashboard}
              class="oj-breadcrumb-item-link"
              onClick={(e) => {
                e.preventDefault();
                navigate(APP_ROUTES.dashboard);
              }}
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
