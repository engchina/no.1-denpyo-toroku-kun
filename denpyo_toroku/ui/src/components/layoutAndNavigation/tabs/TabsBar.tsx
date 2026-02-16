/**
 * タブバー（Oracle JET Redwood TabBar）による画面ナビゲーション
 * @oracle/oraclejet-preact の TabBar/TabBarItem を使用
 */
import { h } from 'preact';
import { useAppSelector, useAppDispatch } from '../../../redux/store';
import { setCurrentView } from '../../../redux/slices/applicationSlice';
import { TabBar, TabBarItem } from '@oracle/oraclejet-preact/UNSAFE_TabBar';
import { LayoutDashboard, MessageSquare, GraduationCap, BarChart3, Info } from 'lucide-react';

const tabs = [
  { id: 'dashboard', name: 'ダッシュボード', Icon: LayoutDashboard },
  { id: 'predict', name: '予測', Icon: MessageSquare },
  { id: 'train', name: '学習', Icon: GraduationCap },
  { id: 'stats', name: '統計', Icon: BarChart3 },
  { id: 'modelInfo', name: 'モデル情報', Icon: Info }
];

export function TabsBar() {
  const dispatch = useAppDispatch();
  const currentView = useAppSelector(state => state.application.currentView);

  const handleSelect = (detail: { value: string | number }) => {
    dispatch(setCurrentView(String(detail.value)));
  };

  return (
    <div class="oj-sm-margin-4x-top oj-sm-margin-4x-bottom">
      <TabBar
        selection={currentView}
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
