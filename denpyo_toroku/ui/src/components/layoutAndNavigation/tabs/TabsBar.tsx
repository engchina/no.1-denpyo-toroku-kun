/**
 * タブバー（Oracle JET Redwood TabBar）による画面ナビゲーション
 * @oracle/oraclejet-preact の TabBar/TabBarItem を使用
 */
import { useLocation, useNavigate } from 'react-router-dom';
import { APP_ROUTES } from '../../../constants/routes';
import { TabBar, TabBarItem } from '@oracle/oraclejet-preact/UNSAFE_TabBar';
import { LayoutDashboard, Upload, FileText, Search, SlidersHorizontal } from 'lucide-react';

const tabs = [
  { id: APP_ROUTES.dashboard, name: 'ダッシュボード', Icon: LayoutDashboard },
  { id: APP_ROUTES.upload, name: 'アップロード', Icon: Upload },
  { id: APP_ROUTES.fileList, name: 'ファイル一覧', Icon: FileText },
  { id: APP_ROUTES.search, name: '検索', Icon: Search },
  { id: APP_ROUTES.settingsApplication, name: '設定', Icon: SlidersHorizontal }
];

export function TabsBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedTab = location.pathname.startsWith('/settings/')
    ? APP_ROUTES.settingsApplication
    : location.pathname;

  const handleSelect = (detail: { value: string | number }) => {
    navigate(String(detail.value));
  };

  return (
    <div class="oj-sm-margin-4x-top oj-sm-margin-4x-bottom">
      <TabBar
        selection={selectedTab}
        onSelect={handleSelect}
        layout="condense"
        edge="top"
        aria-label="メインナビゲーション"
      >
        {tabs.map(tab => (
          <TabBarItem
            key={tab.id}
            itemKey={tab.id}
            label={tab.name}
            icon={<tab.Icon size={16} />}
          />
        ))}
      </TabBar>
    </div>
  );
}
