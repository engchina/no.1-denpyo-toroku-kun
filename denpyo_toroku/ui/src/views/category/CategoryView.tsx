/**
 * CategoryView - カテゴリ管理画面 (SCR-005)
 * 一覧表示 + 有効/無効切替 + 編集 + 削除
 */
import { h } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import {
  fetchCategories,
  updateCategory,
  toggleCategoryActive,
  deleteCategory
} from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { useToastConfirm } from '../../hooks/useToastConfirm';
import { t } from '../../i18n';
import { DenpyoCategory, CategoryUpdateRequest } from '../../types/denpyoTypes';
import {
  RefreshCw,
  Pencil,
  Trash2,
  ToggleLeft,
  ToggleRight,
  X,
  Save,
  Loader2
} from 'lucide-react';

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return `${date.toLocaleDateString('ja-JP')} ${date.toLocaleTimeString('ja-JP')}`;
}

function EditModal({
  category,
  onSave,
  onClose,
  isSaving
}: {
  category: DenpyoCategory;
  onSave: (data: CategoryUpdateRequest) => void;
  onClose: () => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(category.category_name);
  const [nameEn, setNameEn] = useState(category.category_name_en);
  const [desc, setDesc] = useState(category.description);

  const handleSubmit = useCallback((e: Event) => {
    e.preventDefault();
    if (!name.trim()) return;
    onSave({
      category_name: name.trim(),
      category_name_en: nameEn.trim(),
      description: desc.trim()
    });
  }, [name, nameEn, desc, onSave]);

  return (
    <div class="ics-modal-overlay" onClick={onClose}>
      <div class="ics-modal" onClick={(e: Event) => e.stopPropagation()}>
        <div class="ics-modal__header">
          <h3>{t('category.edit.title')}</h3>
          <button type="button" class="ics-ops-btn ics-ops-btn--ghost" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div class="ics-modal__body">
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.name')}</label>
              <input
                type="text"
                class="ics-form-input"
                value={name}
                onInput={(e: Event) => setName((e.target as HTMLInputElement).value)}
                required
              />
            </div>
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.nameEn')}</label>
              <input
                type="text"
                class="ics-form-input"
                value={nameEn}
                onInput={(e: Event) => setNameEn((e.target as HTMLInputElement).value)}
              />
            </div>
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.description')}</label>
              <textarea
                class="ics-form-textarea"
                value={desc}
                rows={3}
                onInput={(e: Event) => setDesc((e.target as HTMLTextAreaElement).value)}
              />
            </div>
            <div class="ics-form-group">
              <label class="ics-form-label">{t('category.col.headerTable')}</label>
              <input
                type="text"
                class="ics-form-input"
                value={category.header_table_name}
                disabled
              />
            </div>
            {category.line_table_name && (
              <div class="ics-form-group">
                <label class="ics-form-label">{t('category.col.lineTable')}</label>
                <input
                  type="text"
                  class="ics-form-input"
                  value={category.line_table_name}
                  disabled
                />
              </div>
            )}
          </div>
          <div class="ics-modal__footer">
            <button
              type="button"
              class="ics-ops-btn ics-ops-btn--ghost"
              onClick={onClose}
              disabled={isSaving}
            >
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              class="ics-ops-btn ics-ops-btn--primary"
              disabled={isSaving || !name.trim()}
            >
              {isSaving ? <Loader2 size={14} class="ics-spin" /> : <Save size={14} />}
              <span>{isSaving ? t('common.saving') : t('common.save')}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function CategoryView() {
  const dispatch = useAppDispatch();
  const { requestConfirm, confirmToast } = useToastConfirm();
  const categories = useAppSelector(state => state.denpyo.categories);
  const isLoading = useAppSelector(state => state.denpyo.isCategoriesLoading);
  const [editTarget, setEditTarget] = useState<DenpyoCategory | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const loadCategories = useCallback(() => {
    dispatch(fetchCategories());
  }, [dispatch]);

  useEffect(() => {
    loadCategories();
  }, [loadCategories]);

  const handleToggle = useCallback(async (cat: DenpyoCategory) => {
    try {
      await dispatch(toggleCategoryActive(cat.id)).unwrap();
      dispatch(addNotification({
        type: 'success',
        message: t('category.notify.toggled', { name: cat.category_name }),
        autoClose: true
      }));
    } catch {
      dispatch(addNotification({
        type: 'error',
        message: t('category.notify.toggleFailed'),
        autoClose: true
      }));
    }
  }, [dispatch]);

  const handleDelete = useCallback((cat: DenpyoCategory) => {
    requestConfirm({
      message: t('category.confirmDelete', { name: cat.category_name }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      severity: 'warning',
      onConfirm: async () => {
        try {
          await dispatch(deleteCategory(cat.id)).unwrap();
          dispatch(addNotification({
            type: 'success',
            message: t('category.notify.deleted', { name: cat.category_name }),
            autoClose: true
          }));
        } catch {
          dispatch(addNotification({
            type: 'error',
            message: t('category.notify.deleteFailed'),
            autoClose: true
          }));
        }
      }
    });
  }, [dispatch, requestConfirm]);

  const handleSave = useCallback(async (data: CategoryUpdateRequest) => {
    if (!editTarget) return;
    setIsSaving(true);
    try {
      await dispatch(updateCategory({ categoryId: editTarget.id, data })).unwrap();
      setEditTarget(null);
      dispatch(addNotification({
        type: 'success',
        message: t('category.notify.updated', { name: data.category_name }),
        autoClose: true
      }));
    } catch {
      dispatch(addNotification({
        type: 'error',
        message: t('category.notify.updateFailed'),
        autoClose: true
      }));
    } finally {
      setIsSaving(false);
    }
  }, [dispatch, editTarget]);

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      {/* Header */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('category.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('category.subtitle')}</p>
          </div>
          <div class="ics-ops-hero__controls">
            <button
              class="ics-ops-btn ics-ops-btn--primary"
              onClick={loadCategories}
              disabled={isLoading}
            >
              <RefreshCw size={14} class={isLoading ? 'ics-spin' : ''} />
              <span>{isLoading ? t('common.loading') : t('category.refresh')}</span>
            </button>
          </div>
        </div>
        <div class="ics-ops-hero__meta">
          <span>{t('category.totalCategories', { count: categories.length })}</span>
        </div>
      </section>

      {/* Table */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div class="ics-card-header">
            <span class="oj-typography-heading-xs">{t('category.tableTitle')}</span>
          </div>
          <div class="ics-card-body">
            {categories.length > 0 ? (
              <table class="ics-table">
                <thead>
                  <tr>
                    <th>{t('category.col.name')}</th>
                    <th>{t('category.col.nameEn')}</th>
                    <th>{t('category.col.headerTable')}</th>
                    <th>{t('category.col.lineTable')}</th>
                    <th>{t('category.col.registrations')}</th>
                    <th>{t('category.col.status')}</th>
                    <th>{t('category.col.createdAt')}</th>
                    <th>{t('category.col.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map(cat => (
                    <tr key={cat.id} class={cat.is_active ? '' : 'ics-table__row--inactive'}>
                      <td class="ics-table__cell--name">{cat.category_name}</td>
                      <td class="oj-text-color-secondary">{cat.category_name_en || '--'}</td>
                      <td><code class="ics-code">{cat.header_table_name}</code></td>
                      <td>{cat.line_table_name ? <code class="ics-code">{cat.line_table_name}</code> : '--'}</td>
                      <td>{cat.registration_count}</td>
                      <td>
                        <span class={`ics-badge ${cat.is_active ? 'ics-badge-success' : 'ics-badge-error'}`}>
                          {cat.is_active ? t('category.status.active') : t('category.status.inactive')}
                        </span>
                      </td>
                      <td class="oj-text-color-secondary">{formatDateTime(cat.created_at)}</td>
                      <td>
                        <button
                          type="button"
                          class="ics-ops-btn ics-ops-btn--ghost"
                          onClick={() => handleToggle(cat)}
                          title={cat.is_active ? t('category.action.deactivate') : t('category.action.activate')}
                        >
                          {cat.is_active ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
                        </button>
                        <button
                          type="button"
                          class="ics-ops-btn ics-ops-btn--ghost"
                          onClick={() => setEditTarget(cat)}
                          title={t('category.action.edit')}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          class="ics-ops-btn ics-ops-btn--ghost ics-ops-btn--danger"
                          onClick={() => handleDelete(cat)}
                          disabled={cat.registration_count > 0}
                          title={cat.registration_count > 0 ? t('category.cannotDelete') : t('category.action.delete')}
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div class="ics-empty-text">
                {isLoading ? t('common.loading') : t('category.noData')}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Edit Modal */}
      {editTarget && (
        <EditModal
          category={editTarget}
          onSave={handleSave}
          onClose={() => setEditTarget(null)}
          isSaving={isSaving}
        />
      )}
      {confirmToast}
    </div>
  );
}
