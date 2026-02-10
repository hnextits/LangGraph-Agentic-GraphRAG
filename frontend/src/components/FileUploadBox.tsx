import { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { useQueryClient } from '@tanstack/react-query';
import { X, UploadCloud, File as FileIcon, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import api from '@/lib/api';

interface FileUploadBoxProps {
  isOpen: boolean;
  onClose: () => void;
  onFilesAdd?: (files: File[]) => Promise<any>;
}

interface UploadingFile {
  file: File;
  progress: number;
  status: 'pending' | 'uploading' | 'success' | 'error' | 'processing';
  error?: string;
  taskId?: string;
  message?: string;
}

const SUPPORTED_FORMAT_MESSAGE =
  '지원 형식: TXT, PDF, DOC, DOCX, HWP, HWPX, PPT, PPTX, XLS, XLSX, CSV, MD, JPG, PNG, MP4, MOV, AVI, MKV, WEBM, MP3, WAV, M4A, FLAC';

const formatFileSize = (size: number) => {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(size / 1024).toFixed(1)} KB`;
};

const FileUploadBox: React.FC<FileUploadBoxProps> = ({ isOpen, onClose, onFilesAdd }) => {
  const queryClient = useQueryClient();
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const pollAbortRef = useRef<boolean>(false);

  const onDrop = useCallback((acceptedFiles: File[], fileRejections: any[]) => {
    const validFiles = acceptedFiles.map(file => ({
      file,
      progress: 0,
      status: 'pending' as const,
    }));

    const rejectedFiles = fileRejections.map((rejection: any) => ({
      file: rejection.file,
      progress: 0,
      status: 'error' as const,
      error: rejection.errors?.[0]?.message || '지원하지 않는 파일 형식이거나 용량 초과입니다.',
    }));

    setUploadingFiles(prev => [...prev, ...validFiles, ...rejectedFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
      'application/pdf': ['.pdf'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/vnd.hancom.hwp': ['.hwp'],
      'application/vnd.hancom.hwpx': ['.hwpx'],
      'application/vnd.ms-powerpoint': ['.ppt'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
      'application/vnd.ms-excel': ['.xls'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'text/csv': ['.csv'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'video/mp4': ['.mp4'],
      'video/quicktime': ['.mov'],
      'video/x-msvideo': ['.avi'],
      'video/x-matroska': ['.mkv'],
      'video/webm': ['.webm'],
      'audio/mpeg': ['.mp3'],
      'audio/wav': ['.wav'],
      'audio/mp4': ['.m4a'],
      'audio/flac': ['.flac'],
    },
    maxSize: 200 * 1024 * 1024, // 200MB
  });

  const handleRemoveFile = (index: number) => {
    setUploadingFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleUpload = async () => {
    if (!uploadingFiles.length || isUploading) return;
    setIsUploading(true);
    setUploadingFiles(prev => prev.map(f => ({ ...f, status: 'uploading', progress: 0, message: '업로드 중...' })));

    const filesToUpload = uploadingFiles.map(item => item.file);

    try {
      let uploadResult: any = null;
      if (onFilesAdd) {
        uploadResult = await onFilesAdd(filesToUpload);
      } else {
        const response = await api.uploadFiles(filesToUpload);
        uploadResult = response.data;
      }

      const tasksFromServer: { filename: string; task_id: string }[] = uploadResult?.files || [];
      if (!tasksFromServer.length) {
        throw new Error('Upload failed');
      }

      // 매핑: 업로드한 파일 이름 -> taskId
      setUploadingFiles(prev =>
        prev.map(f => {
          const matched = tasksFromServer.find(t => t.filename === f.file.name || t.filename === f.file.name.replace(/\s+/g, '_'));
          return matched
            ? { ...f, status: 'processing', progress: 0, taskId: matched.task_id, message: '처리 대기 중...' }
            : { ...f, status: 'error', error: '태스크 할당 실패' };
        })
      );

      // 태스크 상태 폴링
      pollAbortRef.current = false;
      const pollSingleTask = async (taskId: string) => {
        if (!taskId || taskId === 'undefined') {
          console.error('유효하지 않은 taskId로 폴링을 시도했습니다.');
          return 'failed';
        }
        let failureCount = 0;
        while (!pollAbortRef.current) {
          try {
            const res = await api.getTaskStatus(taskId);
            const task = res.data;
            const progress = Math.min(task.progress ?? 0, 100);
            const statusText = task.status;
            const message = task.message || task.status;

            setUploadingFiles(prev =>
              prev.map(f =>
                f.taskId === taskId
                  ? {
                      ...f,
                      progress: progress,
                      message: message || f.message,
                      status:
                        statusText === 'completed' || statusText === 'index_completed'
                          ? 'success'
                          : statusText === 'failed' || statusText === 'index_failed' || statusText === 'cancelled'
                          ? 'error'
                          : 'processing',
                    }
                  : f
              )
            );

            if (statusText === 'completed' || statusText === 'index_completed' || statusText === 'failed' || statusText === 'index_failed' || statusText === 'cancelled') {
              return statusText;
            }
            failureCount = 0; // 성공적으로 응답 받으면 실패 카운터 초기화
          } catch (err) {
            failureCount += 1;
            setUploadingFiles(prev =>
              prev.map(f =>
                f.taskId === taskId
                  ? {
                      ...f,
                      message: '상태 조회 재시도 중...',
                      status: failureCount >= 3 ? 'error' : f.status,
                      error: failureCount >= 3 ? '상태 조회 실패' : undefined,
                    }
                  : f
              )
            );
            if (failureCount >= 3) {
              return 'failed';
            }
          }
          await new Promise(resolve => setTimeout(resolve, 1200));
        }
        return 'failed';
      };

      const pollResults = await Promise.all(tasksFromServer.map(t => pollSingleTask(t.task_id)));
      
      // 모든 파일 처리가 완료(성공 또는 실패)되었는지 확인
      const anySuccess = pollResults.some(r => r === 'completed' || r === 'index_completed');
      
      if (anySuccess) {
        // 성공한 파일이 하나라도 있으면 목록 갱신
        await queryClient.invalidateQueries({ queryKey: ['files'] });
      }

      // 0.8초 후 모달 닫기 (성공한 파일이 있을 경우)
      if (anySuccess) {
        setTimeout(() => {
          onClose();
          setUploadingFiles([]);
        }, 800);
      } else {
        setUploadingFiles(prev =>
          prev.map(f =>
            f.status === 'success'
              ? f
              : { ...f, status: 'error', error: f.error || '처리 실패 또는 취소' }
          )
        );
      }
    } catch (error) {
      console.error('파일 업로드 오류:', error);
      setUploadingFiles(prev => prev.map(f => ({ ...f, status: 'error', error: '업로드 실패' })));
    } finally {
      pollAbortRef.current = true;
      setIsUploading(false);
    }
  };

  const handleCancelUpload = async () => {
    const taskIds = uploadingFiles
      .filter(f => f.taskId && (f.status === 'processing' || f.status === 'uploading'))
      .map(f => f.taskId!);

    if (taskIds.length > 0) {
      try {
        await api.cancelTasks(taskIds);
      } catch (err) {
        console.error('취소 요청 실패:', err);
      }
    }
    pollAbortRef.current = true;
    setIsUploading(false);
    setUploadingFiles(prev =>
      prev.map(f =>
        f.status === 'processing' || f.status === 'uploading'
          ? { ...f, status: 'error', message: '취소됨', progress: 0 }
          : f
      )
    );
  };

  useEffect(() => {
    return () => {
      pollAbortRef.current = true;
    };
  }, []);

  const handleModalClose = () => {
    if (isUploading) return; // 업로드 진행 중에는 닫기 불가
    setUploadingFiles([]);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={isUploading ? undefined : handleModalClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">파일 업로드</h2>
          <button
            onClick={handleModalClose}
            disabled={isUploading}
            className={`p-1 rounded-full ${isUploading ? 'cursor-not-allowed opacity-50' : 'hover:bg-gray-100'}`}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4 overflow-y-auto">
          {/* Dropzone */}
          <div
            {...getRootProps()}
            className={`p-6 border-2 border-dashed rounded-lg text-center cursor-pointer transition-colors ${
              isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
            }`}
          >
            <input {...getInputProps()} />
            <div className="flex flex-col items-center gap-2 text-gray-500">
              <UploadCloud size={32} className={isDragActive ? 'text-blue-600' : 'text-gray-400'} />
              <p className="text-sm font-semibold">
                {isDragActive
                  ? '파일을 여기에 놓으세요...'
                  : '파일을 드래그 앤 드롭하거나 클릭하여 선택하세요'}
              </p>
            </div>
          </div>
          <div className="bg-gray-50 rounded-md p-3 border border-gray-100">
            <p className="text-[11px] text-gray-500 leading-relaxed">
              <span className="font-semibold text-gray-600 mr-1">지원 형식:</span>
              TXT, PDF, DOC, DOCX, HWP, HWPX, PPT, PPTX, XLS, XLSX, CSV, MD, JPG, PNG, MP4, MOV, AVI, MKV, WEBM, MP3, WAV, M4A, FLAC (최대 200MB)
            </p>
          </div>

          {/* File List */}
          {uploadingFiles.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-gray-700">업로드 파일 ({uploadingFiles.length})</h3>
              <ul className="space-y-2">
                {uploadingFiles.map((item, index) => (
                  <li
                    key={index}
                    className="p-3 border rounded-md bg-white shadow-sm flex items-center gap-4 relative overflow-hidden"
                  >
                    <FileIcon className="text-gray-400 flex-shrink-0" size={20} />
                    <div className="flex-grow min-w-0 space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-gray-800 truncate">{item.file.name}</p>
                        {(item.status === 'uploading' || item.status === 'processing' || item.status === 'success') && (
                          <p className="text-[11px] text-blue-600 font-semibold w-10 text-right">
                            {Math.round(item.progress)}%
                          </p>
                        )}
                      </div>
                      
                      {/* Inline log message */}
                      {item.message && (
                        <p className="text-[10px] text-gray-500 truncate italic">
                          {item.message}
                        </p>
                      )}

                      {(item.status === 'uploading' || item.status === 'processing') && (
                        <div className="h-1 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 transition-all duration-300 ease-in-out"
                            style={{ width: `${item.progress}%` }}
                          />
                        </div>
                      )}
                    </div>
                    <div className="flex-shrink-0">
                      {item.status === 'pending' && (
                        <button
                          onClick={() => handleRemoveFile(index)}
                          className="p-1 rounded-full hover:bg-gray-100"
                        >
                          <X size={14} className="text-gray-400" />
                        </button>
                      )}
                      {item.status === 'success' && (
                        <CheckCircle size={18} className="text-green-500" />
                      )}
                      {item.status === 'error' && (
                        <AlertCircle size={18} className="text-red-500" />
                      )}
                    </div>
                    {item.status === 'error' && item.error && (
                      <p className="absolute bottom-1 right-3 text-[10px] text-red-600 font-medium">{item.error}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end p-4 border-t border-gray-200 gap-3">
          {isUploading ? (
            <button
              onClick={handleCancelUpload}
              className="px-4 py-2 text-sm font-medium text-white bg-red-500 rounded-md hover:bg-red-600 flex items-center gap-2"
            >
              <X size={16} />
              <span>중지 / 취소</span>
            </button>
          ) : (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 hover:bg-gray-50"
              >
                닫기
              </button>
              <button
                onClick={handleUpload}
                disabled={uploadingFiles.length === 0}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                업로드
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default FileUploadBox;
