import { ja } from './ja';

type Dict = typeof ja;
type Params = Record<string, string | number | boolean | null | undefined>;

function format(template: string, params?: Params) {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const v = params[key];
    return v === null || v === undefined ? '' : String(v);
  });
}

export function t(key: keyof Dict, params?: Params) {
  return format(ja[key], params);
}

