/**
 * Oracle JET Preact component type declarations
 * Enables TypeScript recognition of @oracle/oraclejet-preact modules
 */

// Module declarations for oraclejet-preact ES module CSS imports
declare module '*.styles.css' {
  const content: string;
  export default content;
}

// Ensure @oracle/oraclejet-preact subpath imports resolve
declare module '@oracle/oraclejet-preact/UNSAFE_Button' {
  export { Button } from '@oracle/oraclejet-preact/UNSAFE_Button/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_InputText' {
  export { InputText } from '@oracle/oraclejet-preact/UNSAFE_InputText/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_TextArea' {
  export { TextArea } from '@oracle/oraclejet-preact/UNSAFE_TextArea/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_NumberInputText' {
  const NumberInputText: any;
  export { NumberInputText };
}

declare module '@oracle/oraclejet-preact/UNSAFE_ProgressBar' {
  export { ProgressBar } from '@oracle/oraclejet-preact/UNSAFE_ProgressBar/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_ProgressCircle' {
  export { ProgressCircle } from '@oracle/oraclejet-preact/UNSAFE_ProgressCircle/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_MessageToast' {
  export { MessageToast } from '@oracle/oraclejet-preact/UNSAFE_MessageToast/index';
  export type { MessageToastItem } from '@oracle/oraclejet-preact/UNSAFE_MessageToast/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_TabBar' {
  export { TabBar, TabBarItem } from '@oracle/oraclejet-preact/UNSAFE_TabBar/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_TabBarCommon' {
  export { TabBarItem, RemovableTabBarItem, OverflowTabBarItem, TabBarContext, useTabBarContext, TabBarLayout, TabBarLinkItem } from '@oracle/oraclejet-preact/UNSAFE_TabBarCommon/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_Badge' {
  export { Badge } from '@oracle/oraclejet-preact/UNSAFE_Badge/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_Checkbox' {
  export { Checkbox } from '@oracle/oraclejet-preact/UNSAFE_Checkbox/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_NavigationList' {
  export { NavigationList } from '@oracle/oraclejet-preact/UNSAFE_NavigationList/index';
  export { NavigationListItem } from '@oracle/oraclejet-preact/UNSAFE_NavigationList/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_NavigationListCommon' {
  const content: any;
  export = content;
}

declare module '@oracle/oraclejet-preact/UNSAFE_DrawerPopup' {
  export { DrawerPopup } from '@oracle/oraclejet-preact/UNSAFE_DrawerPopup/index';
}

declare module '@oracle/oraclejet-preact/UNSAFE_Separator' {
  export { Separator } from '@oracle/oraclejet-preact/UNSAFE_Separator/index';
}

declare module '@oracle/oraclejet-preact/utils/UNSAFE_size' {
  export type Size = string | number;
}

declare module '@oracle/oraclejet-preact/UNSAFE_Environment' {
  import { ComponentChildren } from 'preact';
  export interface RootEnvironment {
    translations?: Record<string, Record<string, (...args: any[]) => string>>;
    user?: { locale?: string; direction?: 'rtl' | 'ltr'; forcedColors?: 'none' | 'active' };
    [key: string]: any;
  }
  export function RootEnvironmentProvider(props: { children?: ComponentChildren; environment?: RootEnvironment }): any;
  export function EnvironmentProvider(props: { children?: ComponentChildren; environment?: any }): any;
  export const EnvironmentContext: any;
}

declare module '@oracle/oraclejet-preact/resources/nls/en/bundle' {
  const bundle: Record<string, (...args: any[]) => string>;
  export default bundle;
}

declare module '@oracle/oraclejet-preact/resources/nls/ja/bundle' {
  const bundle: Record<string, (...args: any[]) => string>;
  export default bundle;
}
