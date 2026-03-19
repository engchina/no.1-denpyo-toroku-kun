import { useEffect } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { fetchTableBrowserTables } from '../../redux/slices/denpyoSlice';
import { t } from '../../i18n';
import { TableBrowserTab } from '../search/SearchView';

export function TableBrowserView() {
  const dispatch = useAppDispatch();
  const {
    tableBrowserTables,
    isTableBrowserTablesLoading,
    tableBrowseResult,
    isTableBrowsing,
    searchError,
  } = useAppSelector((state) => state.denpyo);

  useEffect(() => {
    dispatch(fetchTableBrowserTables());
  }, [dispatch]);

  return (
    <div class="ics-dashboard ics-dashboard--enhanced ics-search-view">
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('tableBrowser.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('tableBrowser.subtitle')}</p>
          </div>
        </div>
      </section>

      {searchError && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-error-message">
            {searchError}
          </div>
        </section>
      )}

      <TableBrowserTab
        tableBrowserTables={tableBrowserTables}
        isLoading={isTableBrowsing}
        isTableListLoading={isTableBrowserTablesLoading}
        result={tableBrowseResult}
      />
    </div>
  );
}
