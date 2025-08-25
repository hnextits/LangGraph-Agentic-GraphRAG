import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import api from '@/lib/api';

// 아이콘 임포트
import {
  X,
  Upload,
  File,
  Loader2,
  CheckCircle,
  AlertCircle
} from 'lucide-react';

interface FileUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onFilesAdd?: (files: File[]) => Promise<void>;
}

interface UploadingFile {
  file: File;
  progress: number;
  status: 'pending' | 'uploading' | 'success' | 'error';
  error?: string;
}

const FileUploadModal: React.FC<FileUploadModalProps> = ({ isOpen, onClose, onFilesAdd }) => {
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map(file => ({
      file,
      progress: 0,
      status: 'pending' as const
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
      'image/png': ['.png']
    }
  });

  const handleRemoveFile = (index: number) => {
    setUploadingFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleUpload = async () => {
    if (uploadingFiles.length === 0 || isUploading) return;
    
    setIsUploading(true);
    
    // 모든 파일의 상태를 'uploading'으로 변경
    setUploadingFiles(prev => 
      prev.map(file => ({
        ...file,
        status: 'uploading',
        progress: 0
      }))
    );
    
    const filesToUpload = uploadingFiles.map(item => item.file);
    
    try {
      // 업로드 진행 상황을 시뮬레이션하기 위한 인터벌
      const progressInterval = setInterval(() => {
        setUploadingFiles(prev => 
          prev.map(file => ({
            ...file,
            progress: Math.min(file.progress + Math.random() * 20, 95)
          }))
        );
      }, 500);
      
      // 실제 파일 업로드 요청
      let uploadSuccess = true;
      try {
        if (onFilesAdd) {
          await onFilesAdd(filesToUpload);
        } else {
          const response = await api.uploadFiles(filesToUpload);
          uploadSuccess = response.data.success;
        }
      } catch (error) {
        uploadSuccess = false;
        throw error; // 오류를 다시 던져서 catch 블록에서 처리하게 함
      } finally {
        clearInterval(progressInterval);
      }
      
      if (uploadSuccess) {
        // 모든 파일 업로드 성공
        setUploadingFiles(prev => 
          prev.map(file => ({
            ...file,
            status: 'success',
            progress: 100
          }))
        );
        
        // 파일 업로드 완료 이벤트 발생
        const event = new CustomEvent('fileUploadComplete');
        window.dispatchEvent(event);
        
        // 3초 후 모달 닫기
        setTimeout(() => {
          onClose();
          setUploadingFiles([]);
        }, 3000);
      } else {
        // 일부 또는 전체 파일 업로드 실패
        setUploadingFiles(prev => 
          prev.map(file => ({
            ...file,
            status: 'error',
            error: '업로드 실패',
            progress: 0
          }))
        );
      }
    } catch (error) {
      console.error('파일 업로드 오류:', error);
      
      // 모든 파일 업로드 실패
      setUploadingFiles(prev => 
        prev.map(file => ({
          ...file,
          status: 'error',
          error: '서버 연결 오류',
          progress: 0
        }))
      );
    } finally {
      setIsUploading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg w-full max-w-lg max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="text-lg font-medium">파일 업로드</h3>
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-gray-100"
          >
            <X size={20} />
          </button>
        </div>
        
        <div className="p-4 flex-grow overflow-y-auto">
          {/* 드롭존 */}
          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center cursor-pointer transition-colors ${
              isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400'
            }`}
          >
            <input {...getInputProps()} />
            <Upload size={36} className={`mb-2 ${isDragActive ? 'text-blue-500' : 'text-gray-400'}`} />
            <p className="text-center text-gray-600">
              {isDragActive
                ? '파일을 여기에 놓으세요...'
                : '파일을 드래그 앤 드롭하거나 클릭하여 선택하세요'}
            </p>
            <p className="text-xs text-gray-500 mt-1">
              지원 형식: TXT, PDF, DOC, DOCX, MD, JPG, PNG
            </p>
          </div>
          
          {/* 업로드 파일 목록 */}
          {uploadingFiles.length > 0 && (
            <div className="mt-4">
              <h4 className="font-medium mb-2">업로드 파일 ({uploadingFiles.length})</h4>
              <ul className="space-y-2">
                {uploadingFiles.map((item, index) => (
                  <li key={index} className="border rounded-md p-2">
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center">
                        <File size={16} className="mr-2 text-gray-500" />
                        <span className="text-sm truncate max-w-[200px]">{item.file.name}</span>
                        <span className="text-xs text-gray-500 ml-2">
                          {(item.file.size / 1024).toFixed(1)} KB
                        </span>
                      </div>
                      {item.status === 'pending' && (
                        <button
                          onClick={() => handleRemoveFile(index)}
                          className="p-1 rounded-md hover:bg-gray-100 text-gray-500"
                        >
                          <X size={16} />
                        </button>
                      )}
                      {item.status === 'uploading' && (
                        <div className="text-xs text-blue-500">
                          {item.progress.toFixed(0)}%
                        </div>
                      )}
                      {item.status === 'success' && (
                        <CheckCircle size={16} className="text-green-500" />
                      )}
                      {item.status === 'error' && (
                        <AlertCircle size={16} className="text-red-500" />
                      )}
                    </div>
                    
                    {/* 진행 상태 바 */}
                    {item.status === 'uploading' && (
                      <div className="w-full bg-gray-200 rounded-full h-1.5">
                        <div
                          className="bg-blue-500 h-1.5 rounded-full"
                          style={{ width: `${item.progress}%` }}
                        ></div>
                      </div>
                    )}
                    
                    {/* 오류 메시지 */}
                    {item.status === 'error' && item.error && (
                      <p className="text-xs text-red-500 mt-1">{item.error}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        
        <div className="p-4 border-t flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50 mr-2"
          >
            취소
          </button>
          <button
            onClick={handleUpload}
            disabled={uploadingFiles.length === 0 || isUploading}
            className={`px-4 py-2 rounded-md flex items-center ${
              uploadingFiles.length === 0 || isUploading
                ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
                : 'bg-blue-500 text-white hover:bg-blue-600'
            }`}
          >
            {isUploading ? (
              <>
                <Loader2 size={16} className="mr-2 animate-spin" />
                업로드 중...
              </>
            ) : (
              <>
                <Upload size={16} className="mr-2" />
                업로드
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default FileUploadModal;
