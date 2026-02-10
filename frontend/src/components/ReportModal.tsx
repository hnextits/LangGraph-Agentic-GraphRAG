import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { X, UploadCloud, File as FileIcon, CheckCircle, AlertCircle, FileText, FileSpreadsheet, MessageSquare, Lightbulb, Settings } from 'lucide-react';

interface ReportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onGenerate?: (file: File, templateType: string) => Promise<void>;
}

interface UploadedFile {
  file: File;
  status: 'uploaded' | 'error';
  error?: string;
}

type TemplateType = '품의서' | '보고서' | '회의록' | '제안서' | '커스텀';

const SUPPORTED_FORMAT_MESSAGE = '지원 형식: TXT, PDF, DOC, DOCX, MD, JPG, PNG, MP4, MOV, AVI, MKV, WEBM, MP3, WAV, M4A, FLAC';

const formatFileSize = (size: number) => {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(size / 1024).toFixed(1)} KB`;
};

const templateButtons: { type: TemplateType; icon: React.ElementType; color: string; bgColor: string; borderColor: string }[] = [
  { type: '품의서', icon: FileText, color: 'text-blue-600', bgColor: 'bg-blue-50', borderColor: 'border-blue-500' },
  { type: '보고서', icon: FileSpreadsheet, color: 'text-green-600', bgColor: 'bg-green-50', borderColor: 'border-green-500' },
  { type: '회의록', icon: MessageSquare, color: 'text-purple-600', bgColor: 'bg-purple-50', borderColor: 'border-purple-500' },
  { type: '제안서', icon: Lightbulb, color: 'text-orange-600', bgColor: 'bg-orange-50', borderColor: 'border-orange-500' },
  { type: '커스텀', icon: Settings, color: 'text-gray-600', bgColor: 'bg-gray-50', borderColor: 'border-gray-500' },
];

const ReportModal: React.FC<ReportModalProps> = ({ isOpen, onClose, onGenerate }) => {
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateType | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const onDrop = useCallback((acceptedFiles: File[], fileRejections: any[]) => {
    if (acceptedFiles.length > 0) {
      // 첫 번째 파일만 사용
      setUploadedFile({
        file: acceptedFiles[0],
        status: 'uploaded',
      });
    }

    if (fileRejections.length > 0) {
      setUploadedFile({
        file: fileRejections[0].file,
        status: 'error',
        error: fileRejections[0].errors?.[0]?.message || '지원하지 않는 파일 형식이거나 용량 초과입니다.',
      });
    }
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
    multiple: false, // 단일 파일만 허용
  });

  const handleRemoveFile = () => {
    setUploadedFile(null);
    setSelectedTemplate(null);
  };

  const handleTemplateSelect = (template: TemplateType) => {
    setSelectedTemplate(template);
  };

  const handleGenerate = async () => {
    if (!uploadedFile || !selectedTemplate || uploadedFile.status === 'error') return;

    setIsGenerating(true);
    try {
      if (onGenerate) {
        await onGenerate(uploadedFile.file, selectedTemplate);
      }
      // 성공 후 모달 닫기
      setTimeout(() => {
        onClose();
        setUploadedFile(null);
        setSelectedTemplate(null);
      }, 500);
    } catch (error) {
      console.error('보고서 생성 오류:', error);
      alert('보고서 생성 중 오류가 발생했습니다.');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleClose = () => {
    if (!isGenerating) {
      onClose();
      setUploadedFile(null);
      setSelectedTemplate(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={handleClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">보고서 생성</h2>
          <button 
            onClick={handleClose} 
            className="p-1 rounded-full hover:bg-gray-100"
            disabled={isGenerating}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-6 overflow-y-auto">
          {/* 파일 업로드 */}
          <div className="space-y-3">
            <h3 className="text-md font-semibold">
              파일 업로드
            </h3>
            
            {!uploadedFile ? (
              <>
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
                <div className="flex flex-col gap-2 text-gray-500 bg-gray-200/70 rounded-lg py-4 px-6">
                  <p className="text-xs text-gray-600">{SUPPORTED_FORMAT_MESSAGE}</p>
                  <p className="text-xs text-gray-600">파일 크기: 최대 200MB</p>
                  <p className="text-xs text-gray-600">※ 한 번에 하나의 파일만 업로드 가능합니다</p>
                </div>
              </>
            ) : (
              <div className="p-4 border rounded-lg flex items-center gap-4 bg-gray-50">
                <FileIcon className="text-gray-500 flex-shrink-0" size={32} />
                <div className="flex-grow min-w-0">
                  <p className="text-sm font-medium truncate">{uploadedFile.file.name}</p>
                  <p className="text-xs text-gray-500">{formatFileSize(uploadedFile.file.size)}</p>
                </div>
                <div className="flex-shrink-0 flex items-center gap-2">
                  {uploadedFile.status === 'uploaded' && (
                    <CheckCircle size={24} className="text-green-500" />
                  )}
                  {uploadedFile.status === 'error' && (
                    <AlertCircle size={24} className="text-red-500" />
                  )}
                  <button
                    onClick={handleRemoveFile}
                    className="p-1 rounded-full hover:bg-gray-200"
                    disabled={isGenerating}
                  >
                    <X size={20} className="text-gray-500" />
                  </button>
                </div>
                {uploadedFile.status === 'error' && uploadedFile.error && (
                  <p className="text-xs text-red-600 mt-2">{uploadedFile.error}</p>
                )}
              </div>
            )}
          </div>

          {/* 양식 선택 */}
          {uploadedFile && uploadedFile.status === 'uploaded' && (
            <div className="space-y-3">
              <h3 className="text-md font-semibold">
                양식 선택
              </h3>
              
              <div className="grid grid-cols-5 gap-2">
                {templateButtons.map(({ type, icon: Icon, color, bgColor, borderColor }) => (
                  <button
                    key={type}
                    onClick={() => handleTemplateSelect(type)}
                    disabled={isGenerating}
                    className={`p-2 rounded-lg border-2 transition-all hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed ${
                      selectedTemplate === type
                        ? `${borderColor} ${bgColor} shadow-md`
                        : 'border-gray-200 bg-white hover:border-gray-300'
                    }`}
                  >
                    <div className="flex flex-col items-center gap-1">
                      <Icon 
                        size={24} 
                        className={selectedTemplate === type ? color : 'text-gray-400'}
                      />
                      <span className={`text-xs font-medium ${
                        selectedTemplate === type ? color : 'text-gray-600'
                      }`}>
                        {type}
                      </span>
                    </div>
                  </button>
                ))}
              </div>

              {selectedTemplate && (
                <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-sm text-blue-700">
                    <span className="font-semibold">{selectedTemplate} 양식</span>이 선택되었습니다.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end p-4 border-t border-gray-200 gap-3">
          <button
            onClick={handleClose}
            disabled={isGenerating}
            className="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            취소
          </button>
          <button
            onClick={handleGenerate}
            disabled={!uploadedFile || !selectedTemplate || uploadedFile.status === 'error' || isGenerating}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isGenerating ? (
              <>
                <div className="animate-spin h-4 w-4 border-2 border-white rounded-full border-t-transparent"></div>
                <span>생성 중...</span>
              </>
            ) : (
              '보고서 생성'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ReportModal;
