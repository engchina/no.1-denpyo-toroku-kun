/**
 * @license
 * Copyright (c) 2024, 2026, Oracle and/or its affiliates.
 * Licensed under The Universal Permissive License (UPL), Version 1.0
 * as shown at https://oss.oracle.com/licenses/upl/
 * @ignore
 */
/**
 * 伝票登録サービスのメインアプリケーションコントローラー
 * ナビゲーション、モジュール読み込み、グローバル状態を管理
 */
define(['knockout', 'ojs/ojcontext', 'ojs/ojmodule-element-utils', 'ojs/ojknockouttemplateutils',
        'ojs/ojresponsiveutils', 'ojs/ojresponsiveknockoututils', 'ojs/ojarraydataprovider',
        'ojs/ojmodule-element', 'ojs/ojknockout'],
    function(ko, Context, moduleUtils, KnockoutTemplateUtils,
             ResponsiveUtils, ResponsiveKnockoutUtils, ArrayDataProvider) {

        function ControllerViewModel() {
            var self = this;

            this.KnockoutTemplateUtils = KnockoutTemplateUtils;

            // アクセシビリティ告知
            this.manner = ko.observable('polite');
            this.message = ko.observable();
            document.getElementById('globalBody').addEventListener('announce', function(event) {
                self.message(event.detail.message);
                self.manner(event.detail.manner);
            }, false);

            // レスポンシブ用メディアクエリ
            var smQuery = ResponsiveUtils.getFrameworkQuery(ResponsiveUtils.FRAMEWORK_QUERY_KEY.SM_ONLY);
            this.smScreen = ResponsiveKnockoutUtils.createMediaQueryObservable(smQuery);
            var mdQuery = ResponsiveUtils.getFrameworkQuery(ResponsiveUtils.FRAMEWORK_QUERY_KEY.MD_UP);
            this.mdScreen = ResponsiveKnockoutUtils.createMediaQueryObservable(mdQuery);

            // ローディング状態
            this.loader = ko.observable(false);

            // ユーザー情報
            this.user_id = ko.observable('管理者');
            this.userName = ko.observable('管理者');

            // タブ／サイドメニューのナビゲーション
            var navItems = [
                { id: 'dashboard', name: 'ダッシュボード', icon: 'oj-ux-ico-home', title: 'ダッシュボード', section: 'dashboard' },
                { id: 'predict',   name: '予測',         icon: 'oj-ux-ico-chat', title: '予測',         section: 'predict' },
                { id: 'train',     name: '学習',         icon: 'oj-ux-ico-education', title: '学習',     section: 'train' },
                { id: 'stats',     name: '統計',         icon: 'oj-ux-ico-bar-chart', title: '統計',     section: 'stats' },
                { id: 'modelInfo', name: 'モデル情報',   icon: 'oj-ux-ico-information-s', title: 'モデル情報', section: 'modelInfo' }
            ];

            this.topTabDataProvider = new ArrayDataProvider(navItems, { keyAttributes: 'id' });
            this.sideBarNavigationDataProvider = new ArrayDataProvider(navItems, { keyAttributes: 'id' });

            // 選択中メニュー項目
            this.selectedMenuItem = ko.observable('dashboard');
            this.currentSelectedMenuItem = ko.observable('dashboard');
            this.sideBarSelectedItem = ko.observable('dashboard');
            this.currentItem = ko.observable('dashboard');

            // サイドメニュー（ドロワー）
            this.isSideMenuOpen = ko.observable(false);

            this.openSideMenu = function() {
                self.isSideMenuOpen(true);
            };

            this.closeSideMenu = function() {
                self.isSideMenuOpen(false);
            };

            this.collapsibleSideNavigationClickHandler = function(event) {
                self.isSideMenuOpen(false);
                var itemId = event.detail.key;
                self.selectedMenuItem(itemId);
                self.currentSelectedMenuItem(itemId);
            };

            // oj-module 用のモジュール設定（各タブが ViewModel + View を読み込む）
            // name を指定すると viewModels/{name} と views/{name}.html を自動解決
            this.dashboardModuleConfig = ko.observable(
                moduleUtils.createConfig({ name: 'dashboard' })
            );
            this.predictModuleConfig = ko.observable(
                moduleUtils.createConfig({ name: 'predict' })
            );
            this.statsModuleConfig = ko.observable(
                moduleUtils.createConfig({ name: 'stats' })
            );
            this.modelInfoModuleConfig = ko.observable(
                moduleUtils.createConfig({ name: 'modelInfo' })
            );
            this.trainModuleConfig = ko.observable(
                moduleUtils.createConfig({ name: 'train' })
            );

            // ユーザーメニューのアクション
            this.menuItemAction = function(event) {
                var selectedValue = event.detail.selectedValue;
                if (selectedValue === 'logout') {
                    window.location.href = '/logout';
                } else if (selectedValue === 'Help') {
                    window.open('https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm', '_blank');
                }
            };

            // 先頭へ戻るボタン
            this.scrollToTop = function() {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            };

            // スクロール位置に応じて先頭へ戻るボタンを表示／非表示
            window.addEventListener('scroll', function() {
                var scrollBtn = document.getElementById('scrollToTopBtn');
                if (scrollBtn) {
                    if (window.pageYOffset > 300) {
                        scrollBtn.classList.add('visible');
                    } else {
                        scrollBtn.classList.remove('visible');
                    }
                }
            });

            // Common Drawer/Modal
            this.showDrawer = ko.observable(false);
            this.drawerTitle = ko.observable('');

            this.openDrawer = function(title) {
                self.drawerTitle(title || '詳細');
                self.showDrawer(true);
            };

            this.closeDrawer = function() {
                self.showDrawer(false);
            };

            // フッターリンク
            this.footerLinks = [
                { name: 'Oracle について', linkId: 'aboutOracle', linkTarget: 'http://www.oracle.com/us/corporate/index.html#menu-about' },
                { name: 'お問い合わせ', linkId: 'contactUs', linkTarget: 'http://www.oracle.com/us/corporate/contact/index.html' },
                { name: '法的通知', linkId: 'legalNotices', linkTarget: 'http://www.oracle.com/us/legal/index.html' },
                { name: '利用規約', linkId: 'termsOfUse', linkTarget: 'http://www.oracle.com/us/legal/terms/index.html' },
                { name: 'プライバシー', linkId: 'yourPrivacyRights', linkTarget: 'http://www.oracle.com/us/legal/privacy/index.html' }
            ];
        }

        // Release the application bootstrap busy state
        Context.getPageContext().getBusyContext().applicationBootstrapComplete();

        return new ControllerViewModel();
    }
);
