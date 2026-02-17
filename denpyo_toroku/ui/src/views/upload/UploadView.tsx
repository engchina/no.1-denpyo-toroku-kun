/**
 * UploadView - 伝票ファイルアップロード画面 (SCR-001)
 * Drag & Drop + ファイル選択 + バリデーション + アップロード
 */
import { h } from 'preact';
import { useState, useCallback, useRef } from 'preact/hooks';
import { useAppDispatch, useAppSelector } from '../../redux/store';
import { uploadFiles, clearUploadResult } from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { t } from '../../i18n';
import {
  Upload,
  FileUp,
  X,
  CheckCircle,
  AlertCircle,
  Loader2,
  File as FileIcon
} from 'lucide-react';

const ALLOWED_TYPES = [
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/tiff',
  'image/bmp'
];

const ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'];
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB
const MAX_FILES = 10;

interface SelectedFile {
  file: File;
  error: string | null;
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function validateFile(file: File): string | null {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return t('upload.error.invalidType');
  }
  if (file.size > MAX_FILE_SIZE) {
    return t('upload.error.tooLarge');
  }
  return null;
}

export function UploadView() {
  const dispatch = useAppDispatch();
  const isUploading = useAppSelector(state => state.denpyo.isUploading);
  const uploadResult = useAppSelector(state => state.denpyo.uploadResult);

  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((files: FileList | File[]) => {
    const newFiles: SelectedFile[] = Array.from(files).map(file => ({
      file,
      error: validateFile(file)
    }));

    setSelectedFiles(prev => {
      const combined = [...prev, ...newFiles];
      if (combined.length > MAX_FILES) {
        dispatch(addNotification({
          type: 'warning',
          message: t('upload.error.tooManyFiles', { max: MAX_FILES }),
          autoClose: true
        }));
        return combined.slice(0, MAX_FILES);
      }
      return combined;
    });
  }, [dispatch]);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (e.dataTransfer?.files) {
      addFiles(e.dataTransfer.files);
    }
  }, [addFiles]);

  const handleFileSelect = useCallback((e: Event) => {
    const input = e.target as HTMLInputElement;
    if (input.files) {
      addFiles(input.files);
      input.value = '';
    }
  }, [addFiles]);

  const removeFile = useCallback((index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleUpload = useCallback(async () => {
    const validFiles = selectedFiles.filter(sf => !sf.error).map(sf => sf.file);
    if (validFiles.length === 0) return;

    try {
      const result = await dispatch(uploadFiles(validFiles)).unwrap();
      setSelectedFiles([]);
      dispatch(addNotification({
        type: result.errors.length > 0 ? 'warning' : 'success',
        message: t('upload.notify.complete', {
          success: result.uploaded_files.length,
          errors: result.errors.length
        }),
        autoClose: true
      }));
    } catch {
      dispatch(addNotification({
        type: 'error',
        message: t('upload.notify.failed'),
        autoClose: true
      }));
    }
  }, [selectedFiles, dispatch]);

  const handleClearResult = useCallback(() => {
    dispatch(clearUploadResult());
  }, [dispatch]);

  const validCount = selectedFiles.filter(sf => !sf.error).length;
  const errorCount = selectedFiles.filter(sf => sf.error).length;

  return (
    <div class="ics-dashboard ics-dashboard--enhanced">
      {/* ヘッダー */}
      <section class="ics-ops-hero">
        <div class="ics-ops-hero__header">
          <div>
            <h2>{t('upload.title')}</h2>
            <p class="ics-ops-hero__subtitle">{t('upload.subtitle')}</p>
          </div>
        </div>
      </section>

      {/* ドロップゾーン */}
      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div
            class={`ics-upload-dropzone${isDragOver ? ' ics-upload-dropzone--active' : ''}${isUploading ? ' ics-upload-dropzone--disabled' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => !isUploading && fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ALLOWED_EXTENSIONS.join(',')}
              onChange={handleFileSelect}
              class="ics-upload-dropzone__input"
            />
            <Upload size={40} class="ics-upload-dropzone__icon" />
            <p class="ics-upload-dropzone__text">{t('upload.dropzone.text')}</p>
            <p class="ics-upload-dropzone__hint">{t('upload.dropzone.hint')}</p>
          </div>
        </div>
      </section>

      {/* 選択ファイル一覧 */}
      {selectedFiles.length > 0 && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-header oj-flex oj-sm-align-items-center oj-sm-justify-content-space-between">
              <span class="oj-typography-heading-xs">
                {t('upload.selectedFiles', { count: selectedFiles.length })}
              </span>
              <div class="oj-flex oj-sm-gap-2">
                {errorCount > 0 && (
                  <span class="ics-badge ics-badge-error">
                    {t('upload.errorCount', { count: errorCount })}
                  </span>
                )}
                <button
                  class="ics-ops-btn ics-ops-btn--primary"
                  onClick={handleUpload}
                  disabled={isUploading || validCount === 0}
                >
                  {isUploading ? (
                    <>
                      <Loader2 size={14} class="ics-spin" />
                      <span>{t('upload.uploading')}</span>
                    </>
                  ) : (
                    <>
                      <FileUp size={14} />
                      <span>{t('upload.action', { count: validCount })}</span>
                    </>
                  )}
                </button>
              </div>
            </div>
            <div class="ics-card-body">
              <div class="ics-upload-fileList">
                {selectedFiles.map((sf, index) => (
                  <div key={`${sf.file.name}-${index}`} class={`ics-upload-fileItem${sf.error ? ' ics-upload-fileItem--error' : ''}`}>
                    <div class="ics-upload-fileItem__info">
                      <FileIcon size={16} />
                      <span class="ics-upload-fileItem__name">{sf.file.name}</span>
                      <span class="ics-upload-fileItem__size">{formatFileSize(sf.file.size)}</span>
                    </div>
                    <div class="ics-upload-fileItem__actions">
                      {sf.error && (
                        <span class="ics-upload-fileItem__errorMsg">
                          <AlertCircle size={14} />
                          {sf.error}
                        </span>
                      )}
                      <button
                        type="button"
                        class="ics-upload-fileItem__remove"
                        onClick={() => removeFile(index)}
                        disabled={isUploading}
                        aria-label={t('common.close')}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* アップロード結果 */}
      {uploadResult && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel">
            <div class="ics-card-header oj-flex oj-sm-align-items-center oj-sm-justify-content-space-between">
              <span class="oj-typography-heading-xs">
                <CheckCircle size={18} class="ics-icon-success oj-sm-margin-2x-end" />
                {t('upload.result.title')}
              </span>
              <button
                type="button"
                class="ics-ops-btn ics-ops-btn--ghost"
                onClick={handleClearResult}
              >
                <X size={14} />
              </button>
            </div>
            <div class="ics-card-body">
              {uploadResult.uploaded_files.length > 0 && (
                <div class="ics-upload-resultGroup">
                  <p class="ics-upload-resultGroup__label">
                    {t('upload.result.success', { count: uploadResult.uploaded_files.length })}
                  </p>
                  {uploadResult.uploaded_files.map(f => (
                    <div key={f.file_id} class="ics-upload-resultItem ics-upload-resultItem--success">
                      <CheckCircle size={14} />
                      <span>{f.file_name}</span>
                    </div>
                  ))}
                </div>
              )}
              {uploadResult.errors.length > 0 && (
                <div class="ics-upload-resultGroup">
                  <p class="ics-upload-resultGroup__label">
                    {t('upload.result.errors', { count: uploadResult.errors.length })}
                  </p>
                  {uploadResult.errors.map((err, i) => (
                    <div key={i} class="ics-upload-resultItem ics-upload-resultItem--error">
                      <AlertCircle size={14} />
                      <span>{err}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
