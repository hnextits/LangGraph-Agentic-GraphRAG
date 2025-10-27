import { useState, useCallback } from 'react';
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
  status: 'pending' | 'uploading' | 'success' | 'error';
  error?: string;
}

const FileUploadBox: React.FC<FileUploadBoxProps> = ({ isOpen, onClose, onFilesAdd }) => {
  const queryClient = useQueryClient();
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map(file => ({
      file,
      progress: 0,
      status: 'pending' as const,
    }));
    setUploadingFiles(prev => [...prev, ...newFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
      'application/pdf': ['.pdf'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
    },
  });

  const handleRemoveFile = (index: number) => {
    setUploadingFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleUpload = async () => {
    setIsUploading(true);
    setUploadingFiles(prev => prev.map(f => ({ ...f, status: 'uploading', progress: 0 })));

    const filesToUpload = uploadingFiles.map(item => item.file);

    try {
      const progressInterval = setInterval(() => {
        setUploadingFiles(prev =>
          prev.map(f =>
            f.status === 'uploading'
              ? { ...f, progress: Math.min(f.progress + Math.random() * 20, 95) }
              : f
          )
        );
      }, 500);

      let uploadSuccess = false;
      if (onFilesAdd) {
        await onFilesAdd(filesToUpload);
        uploadSuccess = true;
      } else {
        const response = await api.uploadFiles(filesToUpload);
        uploadSuccess = response.data.success;
      }

      clearInterval(progressInterval);

      if (uploadSuccess) {
        setUploadingFiles(prev => prev.map(f => ({ ...f, status: 'success', progress: 100 })));
        queryClient.invalidateQueries({ queryKey: ['files'] });
        setTimeout(() => {
          onClose();
          setUploadingFiles([]);
        }, 1000);
      } else {
        throw new Error('Upload failed');
      }
    } catch (error) {
      console.error('파일 업로드 오류:', error);
      setUploadingFiles(prev => prev.map(f => ({ ...f, status: 'error', error: '업로드 실패' })));
    } finally {
      setIsUploading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">파일 업로드</h2>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-gray-100">
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-2 overflow-y-auto">
          {/* Dropzone */}
          <div
            {...getRootProps()}
            className={`p-8 border-2 border-dashed rounded-lg text-center cursor-pointer transition-colors ${
              isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
            }`}
          >
            <input {...getInputProps()} />
            <div className="flex flex-col items-center gap-2 text-gray-500">
              <UploadCloud size={40} className={isDragActive ? 'text-blue-600' : 'text-gray-400'} />
              <p className="font-semibold">
                {isDragActive
                  ? '파일을 여기에 놓으세요...'
                  : '파일을 드래그 앤 드롭하거나 클릭하여 선택하세요'}
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-2 text-gray-500 bg-gray-200/70 rounded-lg py-8 px-10 ">
            <p className="text-xs text-gray-600">지원 형식: TXT, PDF, DOC, DOCX, MD, JPG, PNG</p>
            <p className="text-xs text-gray-600">파일 크기: 2MB</p>
          </div>

          {/* File List */}
          {uploadingFiles.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-md font-semibold">업로드 파일 ({uploadingFiles.length})</h3>
              <ul className="space-y-2">
                {uploadingFiles.map((item, index) => (
                  <li
                    key={index}
                    className="p-3 border rounded-md flex items-center gap-4 relative overflow-hidden"
                  >
                    <FileIcon className="text-gray-500 flex-shrink-0" size={24} />
                    <div className="flex-grow min-w-0">
                      <p className="text-sm font-medium truncate">{item.file.name}</p>
                      <p className="text-xs text-gray-500">
                        {(item.file.size / 1024).toFixed(1)} KB
                      </p>
                    </div>
                    <div className="flex-shrink-0">
                      {item.status === 'pending' && (
                        <button
                          onClick={() => handleRemoveFile(index)}
                          className="p-1 rounded-full hover:bg-gray-200"
                        >
                          <X size={16} className="text-gray-500" />
                        </button>
                      )}
                      {item.status === 'uploading' && (
                        <p className="text-sm text-blue-600 font-medium">
                          {item.progress.toFixed(0)}%
                        </p>
                      )}
                      {item.status === 'success' && (
                        <CheckCircle size={20} className="text-green-500" />
                      )}
                      {item.status === 'error' && (
                        <AlertCircle size={20} className="text-red-500" />
                      )}
                    </div>
                    {item.status === 'uploading' && (
                      <div
                        className="absolute bottom-0 left-0 h-0.5 bg-blue-500 transition-all duration-300 ease-in-out"
                        style={{ width: `${item.progress}%` }}
                      ></div>
                    )}
                    {item.status === 'error' && item.error && (
                      <p className="absolute bottom-1 right-3 text-xs text-red-600">{item.error}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end p-4 border-t border-gray-200 gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 hover:bg-gray-50"
          >
            취소
          </button>
          <button
            onClick={handleUpload}
            disabled={uploadingFiles.length === 0 || isUploading}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isUploading ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>업로드 중...</span>
              </>
            ) : (
              '업로드'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default FileUploadBox;
