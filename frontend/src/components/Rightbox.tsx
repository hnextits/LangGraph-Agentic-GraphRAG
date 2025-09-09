import { useState, useEffect, useContext } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import api from '@/lib/api';
import { FileContext } from '@/contexts/FileContext';

// 아이콘 임포트
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Loader2,
  FileText,
  AlertCircle
} from 'lucide-react';

interface RightboxProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

const Rightbox: React.FC<RightboxProps> = ({ 
  collapsed = false, 
  onToggleCollapse = () => {}
}) => {
  const { checkedFiles } = useContext(FileContext);
  const [summary, setSummary] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerateSummary = async () => {
    if (checkedFiles.length === 0) {
      setError('요약할 파일을 선택해주세요.');
      return;
    }

    setIsLoading(true);
    setError(null);
    
    // 디버깅 로그 추가
    console.log('요약 요청할 파일 목록:', checkedFiles);

    try {
      const response = await api.summarize({
        file_names: checkedFiles // 'files'에서 'file_names'로 변경 (백엔드 API 파라미터와 일치시킴)
      });

      if (response.data && response.data.summary) {
        setSummary(response.data.summary);
      } else {
        setError('요약 생성에 실패했습니다.');
      }
    } catch (error) {
      console.error('요약 요청 실패:', error);
      setError('서버 연결에 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setIsLoading(false);
    }
  };

  // 체크된 파일 목록이 변경될 때마다 요약 초기화
  useEffect(() => {
    setSummary('');
    setError(null);
  }, [checkedFiles]);

  return (
    <div 
      className={`${collapsed ? 'w-12' : 'w-[95%]'} h-[95%] border border-gray-200 rounded-2xl overflow-hidden flex flex-col`}
    >
      <div className="w-full h-full flex flex-col bg-white overflow-hidden">
        {/* Header */}
        <div className={`flex justify-between items-center ${collapsed ? 'px-1 py-2' : 'px-4 py-2'} border-b border-gray-200 flex-shrink-0 min-h-[52px]`}>
          {!collapsed && (
            <h2 className="text-lg font-bold">요약</h2>
          )}
          <button 
            onClick={onToggleCollapse}
            className="p-1 rounded-md hover:bg-gray-100"
          >
            {collapsed ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
          </button>
        </div>

        {/* Content */}
        {collapsed ? (
          <div className="flex flex-col items-center gap-2 py-2">
            <button 
              onClick={() => {
                onToggleCollapse();
                if (checkedFiles.length > 0 && !summary) {
                  handleGenerateSummary();
                }
              }}
              title="요약 보기"
              className="p-1.5 bg-gray-100 rounded-lg hover:bg-gray-200 w-8 h-8 flex items-center justify-center"
            >
              <FileText size={16} />
            </button>
          </div>
        ) : (
          <div className="flex-grow overflow-y-auto p-4">
            {/* 요약 생성 버튼 */}
            <div className="mb-4">
              <button
                onClick={handleGenerateSummary}
                disabled={isLoading || checkedFiles.length === 0}
                className={`flex items-center justify-center px-4 py-2 rounded-md w-full ${
                  isLoading || checkedFiles.length === 0
                    ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-500 text-white hover:bg-blue-600'
                }`}
              >
                {isLoading ? (
                  <>
                    <Loader2 size={16} className="mr-2 animate-spin" />
                    요약 생성 중...
                  </>
                ) : (
                  <>
                    <RefreshCw size={16} className="mr-2" />
                    요약 생성하기
                  </>
                )}
              </button>
              
              {/* 선택된 파일 정보 */}
              <div className="mt-2 text-xs text-gray-500">
                {checkedFiles.length > 0 ? (
                  <span>선택된 파일: {checkedFiles.length}개</span>
                ) : (
                  <span className="text-red-500">요약할 파일을 선택해주세요.</span>
                )}
              </div>
            </div>

            {/* 에러 메시지 */}
            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md flex items-start">
                <AlertCircle size={16} className="text-red-500 mr-2 mt-0.5" />
                <p className="text-red-600 text-sm">{error}</p>
              </div>
            )}

            {/* 요약 내용 */}
            {summary ? (
              <div className="prose prose-sm max-w-none markdown-content">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code({node, inline, className, children, ...props}) {
                      const match = /language-(\w+)/.exec(className || '');
                      return !inline && match ? (
                        <SyntaxHighlighter
                          style={vscDarkPlus as any}
                          language={match[1]}
                          PreTag="div"
                          {...props}
                        >
                          {String(children).replace(/\n$/, '')}
                        </SyntaxHighlighter>
                      ) : (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    },
                    table({node, ...props}) {
                      return (
                        <div className="overflow-x-auto w-full">
                          <table className="markdown-table" {...props} />
                        </div>
                      );
                    }
                  }}
                >
                  {summary}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-[200px] text-gray-400">
                <FileText size={48} className="mb-2" />
                <p className="text-center">
                  {isLoading ? '요약을 생성하는 중입니다...' : '파일을 선택하고 요약 생성하기 버튼을 클릭하세요.'}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default Rightbox;
