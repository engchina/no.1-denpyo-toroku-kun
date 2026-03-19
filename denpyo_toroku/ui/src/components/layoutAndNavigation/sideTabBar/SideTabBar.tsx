/**
 * SideTabBar - 参照（AgentStudio）のレイアウトに合わせた常設サイドナビ。
 * グループ: 伝票登録 / データ参照 / 設定
 * 参照 MHTML に合わせて Lucide React のアイコンを使用。
 */
import { useAppSelector, useAppDispatch } from '../../../redux/store';
import { toggleSidebar } from '../../../redux/slices/applicationSlice';
import { useNavigate, useLocation } from 'react-router-dom';
import { APP_ROUTES } from '../../../constants/routes';
import { t } from '../../../i18n';
import {
  SlidersHorizontal,
  Cpu,
  HardDrive,
  PanelLeftClose,
  PanelLeftOpen,
  LayoutDashboard,
  Database,
  Upload,
  FileText,
  Files,
  Tags,
  Search,
  Table2,
  MessageSquareText,
  type LucideIcon
} from 'lucide-react';

type TKey = Parameters<typeof t>[0];

interface NavItemDef {
  id: string;
  nameKey: TKey;
  Icon: LucideIcon;
  path: string;
}

interface NavGroup {
  labelKey: TKey;
  items: NavItemDef[];
}

const navGroups: NavGroup[] = [
  {
    labelKey: 'nav.section.denpyo',
    items: [
      { id: 'dashboard', nameKey: 'nav.dashboard', Icon: LayoutDashboard, path: APP_ROUTES.dashboard },
      { id: 'upload', nameKey: 'nav.upload', Icon: Upload, path: APP_ROUTES.upload },
      { id: 'categorySamples', nameKey: 'nav.categorySamples', Icon: Files, path: APP_ROUTES.categorySamples },
      { id: 'categoryManagement', nameKey: 'nav.categoryManagement', Icon: Tags, path: APP_ROUTES.categoryManagement },
      { id: 'fileList', nameKey: 'nav.fileList', Icon: FileText, path: APP_ROUTES.fileList },
      { id: 'search', nameKey: 'nav.dataSearch', Icon: Search, path: APP_ROUTES.search }
    ]
  },
  {
    labelKey: 'nav.section.reference',
    items: [
      { id: 'tableBrowser', nameKey: 'nav.tableBrowser', Icon: Table2, path: APP_ROUTES.tableBrowser }
    ]
  },
  {
    labelKey: 'nav.section.settings',
    items: [
      { id: 'applicationSettings', nameKey: 'nav.applicationSettings', Icon: SlidersHorizontal, path: APP_ROUTES.settingsApplication },
      { id: 'ociGenAiModelSettings', nameKey: 'nav.ociGenAiModelSettings', Icon: Cpu, path: APP_ROUTES.settingsOciGenAi },
      { id: 'ociObjectStorageSettings', nameKey: 'nav.ociObjectStorageSettings', Icon: HardDrive, path: APP_ROUTES.settingsObjectStorage },
      { id: 'databaseSettings', nameKey: 'nav.databaseSettings', Icon: Database, path: APP_ROUTES.settingsDatabase },
      { id: 'promptSettings', nameKey: 'nav.promptSettings', Icon: MessageSquareText, path: APP_ROUTES.settingsPrompts }
    ]
  }
];

export function SideTabBar() {
  const dispatch = useAppDispatch();
  const collapsed = useAppSelector(state => state.application.isSidebarCollapsed);
  const location = useLocation();
  const navigate = useNavigate();

  const containerCls = `navigationSideMenu__container${collapsed ? ' navigationSideMenu__container--collapsed' : ''
    }`;
  const isItemSelected = (path: string) =>
    location.pathname === path || location.pathname.startsWith(`${path}/`);

  return (
    <nav class={containerCls} aria-label={t('nav.sidebar.aria')}>
      <div
        class={`navigationSideMenu__toggleBtn ${collapsed ? 'navigationSideMenu__toggleBtn--collapsed' : 'navigationSideMenu__toggleBtn--expanded'
          }`}
      >
        <button
          type="button"
          class="navigationSideMenu__iconToggle"
          aria-label={collapsed ? t('nav.sidebar.expand') : t('nav.sidebar.collapse')}
          title={collapsed ? t('nav.sidebar.expand') : t('nav.sidebar.collapse')}
          onClick={() => { dispatch(toggleSidebar()); }}
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>
      <div class={`navigationSideMenu__main${collapsed ? ' navigationSideMenu__main--collapsed' : ''}`}>
        {navGroups.map(group => (
          <div key={group.labelKey}>
            <p
              class={`oj-typography-body-sm oj-typography-semi-bold oj-sm-margin-3x-top oj-sm-margin-1x-bottom${collapsed ? ' navigationSideMenu__groupLabel--collapsed' : ''
                }`}
            >
              {t(group.labelKey)}
            </p>
            <div class={`navigationSideMenu__container-group${collapsed ? ' navigationSideMenu__container-group--collapsed' : ''}`}>
              {group.items.map(item => {
                const isSelected = isItemSelected(item.path);
                const label = t(item.nameKey);
                return (
                  <div
                    key={item.id}
                    class={`sideTabBar__rootTab--withoutChildren${collapsed ? ' sideTabBar__rootTab--withoutChildren--collapsed' : ''}`}
                  >
                    <button
                      type="button"
                      class={`sideTabBar__tab-content${collapsed ? ' sideTabBar__tab-content--collapsed' : ''}${isSelected ? ' sideTabBar__tab-content--selected' : ''}`}
                      aria-current={isSelected ? 'page' : undefined}
                      aria-label={collapsed ? label : undefined}
                      title={collapsed ? label : undefined}
                      onClick={() => navigate(item.path)}
                    >
                      <figure class="genericIcon genericIcon__button genericIcon__extra-small">
                        <item.Icon size={15} strokeWidth={2.5} />
                      </figure>
                      {!collapsed && (
                        <span class="sideTabBar__tab-item">
                          <div class="sideTabBar__tab-itemContent">{label}</div>
                        </span>
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </nav>
  );
}
