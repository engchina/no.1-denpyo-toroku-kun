/**
 * UploadView - 伝票ファイルアップロード画面 (SCR-001)
 * Drag & Drop + ファイル選択 + バリデーション + アップロード
 * ファイルごとの逐次アップロードと進捗ステータス表示
 */
import { useState, useCallback, useRef } from 'preact/hooks';
import { useAppDispatch } from '../../redux/store';
import { clearUploadResult, setUploadResult } from '../../redux/slices/denpyoSlice';
import { addNotification } from '../../redux/slices/notificationsSlice';
import { apiUploadWithProgress } from '../../utils/apiUtils';
import type { FileUploadResponse } from '../../types/denpyoTypes';
import { t } from '../../i18n';
import {
  Upload,
  FileUp,
  X,
  CheckCircle,
  AlertCircle,
  Loader2,
  Clock,
  File as FileIcon
} from 'lucide-react';

const ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.zip'];
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
const MAX_FILES = 10;

type UploadFileStatus = 'pending' | 'uploading' | 'done' | 'error';

interface SelectedFile {
  file: File;
  error: string | null;
  uploadStatus?: UploadFileStatus;
  uploadError?: string;
  uploadProgress?: number;
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

  const [uploadKind, setUploadKind] = useState<'raw' | 'category'>('raw');
  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploadingLocal, setIsUploadingLocal] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((files: FileList | File[]) => {
    const newFiles: SelectedFile[] = Array.from(files).map(file => ({
      file,
      error: validateFile(file),
      uploadProgress: 0
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

  const handleCloseSelectedFiles = useCallback(() => {
    if (isUploadingLocal) return;
    setSelectedFiles([]);
    dispatch(clearUploadResult());
  }, [dispatch, isUploadingLocal]);

  const handleUpload = useCallback(async () => {
    const validFiles = selectedFiles.filter(sf => !sf.error);
    if (validFiles.length === 0) return;

    setIsUploadingLocal(true);
    dispatch(clearUploadResult());

    // Mark all valid files as pending
    setSelectedFiles(prev =>
      prev.map(sf => (
        sf.error
          ? sf
          : { ...sf, uploadStatus: 'pending' as UploadFileStatus, uploadError: undefined, uploadProgress: 0 }
      ))
    );

    const allUploadedFiles: any[] = [];
    const allErrors: string[] = [];

    for (const sf of validFiles) {
      const fileRef = sf.file;

      // Mark current file as uploading
      setSelectedFiles(prev =>
        prev.map(s => (
          s.file === fileRef
            ? { ...s, uploadStatus: 'uploading' as UploadFileStatus, uploadProgress: Math.max(s.uploadProgress || 0, 1) }
            : s
        ))
      );

      try {
        const formData = new FormData();
        formData.append('files', fileRef);
        formData.append('upload_kind', uploadKind);
        const result = await apiUploadWithProgress<FileUploadResponse>(
          '/api/v1/files/upload',
          formData,
          (progressPercent) => {
            setSelectedFiles(prev =>
              prev.map(s => (
                s.file === fileRef
                  ? {
                    ...s,
                    uploadStatus: 'uploading' as UploadFileStatus,
                    uploadProgress: Math.max(s.uploadProgress || 0, progressPercent)
                  }
                  : s
              ))
            );
          }
        );

        if (result.uploaded_files && result.uploaded_files.length > 0) {
          allUploadedFiles.push(...result.uploaded_files);
          setSelectedFiles(prev =>
            prev.map(s => (
              s.file === fileRef
                ? { ...s, uploadStatus: 'done' as UploadFileStatus, uploadProgress: 100 }
                : s
            ))
          );
        } else {
          const errMsg = (result.errors && result.errors[0]) || t('upload.notify.failed');
          allErrors.push(`${fileRef.name}: ${errMsg}`);
          setSelectedFiles(prev =>
            prev.map(s => (
              s.file === fileRef
                ? {
                  ...s,
                  uploadStatus: 'error' as UploadFileStatus,
                  uploadError: errMsg,
                  uploadProgress: Math.max(s.uploadProgress || 0, 100)
                }
                : s
            ))
          );
        }
      } catch (e: any) {
        const errMsg = e?.message || t('upload.notify.failed');
        allErrors.push(`${fileRef.name}: ${errMsg}`);
        setSelectedFiles(prev =>
          prev.map(s => (
            s.file === fileRef
              ? { ...s, uploadStatus: 'error' as UploadFileStatus, uploadError: errMsg }
              : s
          ))
        );
      }
    }

    setIsUploadingLocal(false);

    // Update Redux upload result for the result display section
    dispatch(setUploadResult({
      success: allUploadedFiles.length > 0,
      uploaded_files: allUploadedFiles,
      errors: allErrors
    }));

    dispatch(addNotification({
      type: allErrors.length === 0 ? 'success' : (allUploadedFiles.length > 0 ? 'warning' : 'error'),
      message: t('upload.notify.complete', {
        success: allUploadedFiles.length,
        errors: allErrors.length
      }),
      autoClose: true
    }));
  }, [selectedFiles, uploadKind, dispatch]);

  const validCount = selectedFiles.filter(sf => !sf.error).length;
  const errorCount = selectedFiles.filter(sf => sf.error).length;
  const pendingCount = selectedFiles.filter(sf => !sf.error && !sf.uploadStatus).length;

  // Progress counts for display during upload
  const doneCount = selectedFiles.filter(sf => sf.uploadStatus === 'done' || sf.uploadStatus === 'error').length;
  const totalUploadingCount = selectedFiles.filter(sf => sf.uploadStatus !== undefined && !sf.error).length;
  const overallProgressPercent = totalUploadingCount > 0
    ? Math.round(
      selectedFiles
        .filter(sf => sf.uploadStatus !== undefined && !sf.error)
        .reduce((sum, sf) => sum + (sf.uploadProgress || 0), 0) / totalUploadingCount
    )
    : 0;

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
          <div class="ics-card-body">
            <div class="ics-upload-kindSelector" role="radiogroup" aria-label={t('upload.kind.label')}>
              <span class="ics-upload-kindSelector__label">{t('upload.kind.label')}</span>
              <label class="ics-upload-kindOption">
                <input
                  type="radio"
                  name="upload-kind"
                  value="raw"
                  checked={uploadKind === 'raw'}
                  onChange={() => setUploadKind('raw')}
                  disabled={isUploadingLocal}
                />
                <span>{t('upload.kind.raw')}</span>
              </label>
              <label class="ics-upload-kindOption">
                <input
                  type="radio"
                  name="upload-kind"
                  value="category"
                  checked={uploadKind === 'category'}
                  onChange={() => setUploadKind('category')}
                  disabled={isUploadingLocal}
                />
                <span>{t('upload.kind.category')}</span>
              </label>
            </div>
          </div>
        </div>
      </section>

      <section class="ics-ops-grid ics-ops-grid--one">
        <div class="ics-card ics-ops-panel">
          <div
            class={`predictView__dropZone applicationSettingsView__dropZone${isDragOver ? ' predictView__dropZone--active' : ''}${isUploadingLocal ? ' ics-upload-dropzone--disabled' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => !isUploadingLocal && fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ALLOWED_EXTENSIONS.join(',')}
              onChange={handleFileSelect}
              class="send-off-screen"
            />
            <Upload size={22} />
            <p class="oj-typography-body-md">{t('upload.dropzone.text')}</p>
            <p class="oj-typography-body-sm">{t('upload.dropzone.hint')}</p>
          </div>
        </div>
      </section>

      {/* 選択ファイル一覧 */}
      {selectedFiles.length > 0 && (
        <section class="ics-ops-grid ics-ops-grid--one">
          <div class="ics-card ics-ops-panel ics-upload-selectedPanel">
            <div class="ics-card-header ics-upload-selectedHeader">
              <div class="ics-upload-selectedHeader__main">
                <span class="oj-typography-heading-xs">
                  {t('upload.selectedFiles', { count: selectedFiles.length })}
                </span>
                <div class="ics-upload-summaryChips">
                  <span class="ics-upload-summaryChip ics-upload-summaryChip--neutral">
                    {t('upload.status.pending')} {pendingCount}件
                  </span>
                  <span class="ics-upload-summaryChip ics-upload-summaryChip--info">
                    {t('upload.action', { count: validCount })}
                  </span>
                  {errorCount > 0 && (
                    <span class="ics-upload-summaryChip ics-upload-summaryChip--error">
                      {t('upload.errorCount', { count: errorCount })}
                    </span>
                  )}
                  {totalUploadingCount > 0 && (
                    <span class="ics-upload-summaryChip ics-upload-summaryChip--progress">
                      {t('upload.progress', { current: doneCount, total: totalUploadingCount })} ({overallProgressPercent}%)
                    </span>
                  )}
                </div>
              </div>
              <div class="ics-upload-selectedHeader__actions">
                <button
                  type="button"
                  class="ics-ops-btn ics-ops-btn--ghost"
                  onClick={handleCloseSelectedFiles}
                  disabled={isUploadingLocal}
                >
                  <X size={14} />
                  <span>{t('common.close')}</span>
                </button>
                <button
                  class="ics-ops-btn ics-ops-btn--primary"
                  onClick={handleUpload}
                  disabled={isUploadingLocal || validCount === 0}
                >
                  {isUploadingLocal ? (
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
              {(isUploadingLocal || totalUploadingCount > 0) && (
                <div class="ics-upload-overallProgress">
                  <div class="ics-upload-overallProgress__bar">
                    <div
                      class="ics-upload-overallProgress__fill"
                      style={{ width: `${overallProgressPercent}%` }}
                    />
                  </div>
                  <span class="ics-upload-overallProgress__text">{overallProgressPercent}%</span>
                </div>
              )}
              <div class="ics-upload-fileList">
                {selectedFiles.map((sf, index) => {
                  const itemClass = [
                    'ics-upload-fileItem',
                    sf.error ? 'ics-upload-fileItem--error' : '',
                    sf.uploadStatus === 'uploading' ? 'ics-upload-fileItem--uploading' : '',
                    sf.uploadStatus === 'done' ? 'ics-upload-fileItem--done' : ''
                  ].filter(Boolean).join(' ');

                  return (
                    <div key={`${sf.file.name}-${index}`} class={itemClass}>
                      <div class="ics-upload-fileItem__main">
                        <div class="ics-upload-fileItem__info">
                          <FileIcon size={16} />
                          <span class="ics-upload-fileItem__name">{sf.file.name}</span>
                          <span class="ics-upload-fileItem__size">{formatFileSize(sf.file.size)}</span>
                        </div>
                        {(sf.uploadStatus === 'uploading' || sf.uploadStatus === 'done' || sf.uploadStatus === 'error') && (
                          <div class="ics-upload-fileItem__progressBarWrap">
                            <div class="ics-upload-fileItem__progressBar">
                              <div
                                class={[
                                  'ics-upload-fileItem__progressFill',
                                  sf.uploadStatus === 'error' ? 'ics-upload-fileItem__progressFill--error' : '',
                                  sf.uploadStatus === 'done' ? 'ics-upload-fileItem__progressFill--done' : ''
                                ].filter(Boolean).join(' ')}
                                style={{ width: `${sf.uploadProgress || 0}%` }}
                              />
                            </div>
                            <span class="ics-upload-fileItem__progressText">{sf.uploadProgress || 0}%</span>
                          </div>
                        )}
                      </div>
                      <div class="ics-upload-fileItem__actions">
                        {/* バリデーションエラー（アップロード前） */}
                        {sf.error && !sf.uploadStatus && (
                          <span class="ics-upload-fileItem__errorMsg">
                            <AlertCircle size={14} />
                            {sf.error}
                          </span>
                        )}
                        {/* アップロードステータス表示 */}
                        {sf.uploadStatus && (
                          <span class={`ics-upload-fileItem__uploadStatus ics-upload-status--${sf.uploadStatus}`}>
                            {sf.uploadStatus === 'pending' && <Clock size={14} />}
                            {sf.uploadStatus === 'uploading' && <Loader2 size={14} class="ics-spin" />}
                            {sf.uploadStatus === 'done' && <CheckCircle size={14} />}
                            {sf.uploadStatus === 'error' && <AlertCircle size={14} />}
                            <span>
                              {sf.uploadStatus === 'error' && sf.uploadError
                                ? sf.uploadError
                                : t(`upload.status.${sf.uploadStatus}`)}
                            </span>
                          </span>
                        )}
                        <button
                          type="button"
                          class="ics-upload-fileItem__remove"
                          onClick={() => removeFile(index)}
                          disabled={isUploadingLocal}
                          aria-label={t('common.close')}
                        >
                          <X size={14} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>
      )}

    </div>
  );
}
