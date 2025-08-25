import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import api from '@/lib/api';
import FileContentBox from './FileContentBox';

// 아이콘 임포트
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  Trash2,
  ArrowLeft,
  ExternalLink,
  ChevronUp,
  ChevronDown,
  AlertCircle,
  File,
  FileText,
  Image as ImageIcon,
  Code,
  FileType
} from 'lucide-react';

// 타입 정의
interface SourceItem {
  id: string;
  title: string;
  status: 'processing' | 'indexing' | 'queued' | 'completed' | 'failed' | 'index_completed' | 'index_failed';
  taskId?: string;
}

interface LeftboxProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onFileUploadClick?: () => void;
}

const Leftbox = ({ 
  collapsed = false, 
  onToggleCollapse = () => {}, 
  onFileUploadClick 
}: LeftboxProps) => {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [checkedFiles, setCheckedFiles] = useState<string[]>([]);
  const [checked, setChecked] = useState<number[]>([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState<SourceItem | null>(null);
  const [fileContent, setFileContent] = useState('');
  const [fileContentModalOpen, setFileContentModalOpen] = useState(false);

  // 체크된 파일 목록이 변경될 때마다 전역 이벤트 발생
  useEffect(() => {
    // 커스텀 이벤트를 통해 체크된 파일 목록 공유
    const event = new CustomEvent('checkedFilesUpdated', {
      detail: { files: checkedFiles }
    });
    window.dispatchEvent(event);
  }, [checkedFiles]);

  const fetchDocuments = useCallback(async () => {
    try {
      setIsLoading(true);
      console.log('파일 목록 새로고침 중...');
      const response = await api.get('/api/files');
      const data = response.data;
      
      // 백엔드는 파일 이름 문자열의 배열을 반환합니다.
      const formattedSources = data.files.map((doc: string) => ({ 
        title: doc,
        id: doc,
        status: 'completed' as const
      }));
      
      setSources(currentSources => {
        // 처리 중이거나 인덱싱 중인 항목 유지
        const processingSources = currentSources.filter((s: SourceItem) => 
          s.status === 'processing' || s.status === 'indexing' || s.status === 'queued');
        const completedTitles = new Set(formattedSources.map((s: SourceItem) => s.title));
        const uniqueProcessingSources = processingSources.filter((s: SourceItem) => !completedTitles.has(s.title));
        return [...formattedSources, ...uniqueProcessingSources];
      });
      
      console.log('파일 목록 새로고침 완료');
    } catch (error) {
      console.error('파일 목록 가져오기 실패:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // refreshTrigger가 변경될 때마다 파일 목록을 새로고침
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments, refreshTrigger]);
  
  // 외부에서 새로고침을 트리거할 수 있는 함수
  const refreshFileList = useCallback(() => {
    setRefreshTrigger(prev => prev + 1);
  }, []);
  
  // 컴포넌트 마운트 시 파일 목록 새로고침 이벤트 리스너 등록
  useEffect(() => {
    // 파일 업로드 완료 후 새로고침을 위한 이벤트 리스너
    const handleFileUploadComplete = () => {
      console.log('파일 업로드 완료 이벤트 감지, 파일 목록 새로고침');
      refreshFileList();
    };
    
    // 이벤트 리스너 등록
    window.addEventListener('fileUploadComplete', handleFileUploadComplete);
    
    // 컴포넌트 언마운트 시 이벤트 리스너 제거
    return () => {
      window.removeEventListener('fileUploadComplete', handleFileUploadComplete);
    };
  }, [refreshFileList]);
  
  // 초기 로드 시 파일 목록 가져오기
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleProcessingStart = (tasks: any[]) => {
    const newSources = tasks.map(task => ({
      id: task.task_id,
      title: task.title,
      status: 'processing' as const,
      taskId: task.task_id,
    }));
    setSources(prevSources => [...prevSources, ...newSources]);
  };

  useEffect(() => {
    const processingSources = sources.filter(s => (s.status === 'processing' || s.status === 'indexing') && s.taskId);
    if (processingSources.length === 0) return;

    const interval = setInterval(() => {
      processingSources.forEach(source => {
        api.get(`/api/task_status/${source.taskId}`)
          .then(response => {
            const task = response.data;
            if (task.status === 'completed' || task.status === 'failed' || task.status === 'index_completed' || task.status === 'index_failed') {
              setSources(prevSources =>
                prevSources.map(s =>
                  s.taskId === source.taskId ? { ...s, status: task.status as any } : s
                )
              );
              // 완료되거나 인덱싱된 경우 전체 목록을 새로고침
              if(task.status === 'completed' || task.status === 'index_completed') {
                fetchDocuments();
              }
            }
          })
          .catch(error => console.error(`Error fetching status for task ${source.taskId}:`, error));
      });
    }, 3000); // 3초마다 확인

    // 컴포넌트 언마운트 또는 의존성 변경 시 인터벌 정리
    return () => clearInterval(interval);
  }, [sources, fetchDocuments]);

  // 개별 체크박스 토글 핸들러
  const handleToggle = (value: number) => () => {
    const currentIndex = checked.indexOf(value);
    const newChecked = [...checked];

    if (currentIndex === -1) {
      newChecked.push(value);
    } else {
      newChecked.splice(currentIndex, 1);
    }

    setChecked(newChecked);
    
    // 체크된 파일 이름 목록 업데이트
    const newCheckedFiles = newChecked.map(index => sources[index].title);
    setCheckedFiles(newCheckedFiles);
  };

  // 전체 선택 핸들러
  const handleSelectAll = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked) {
      const newChecked = Array.from({ length: sources.length }, (_, i) => i);
      setChecked(newChecked);
      // 체크된 파일 이름 목록 업데이트
      const newCheckedFiles = sources.map(source => source.title);
      setCheckedFiles(newCheckedFiles);
    } else {
      setChecked([]);
      setCheckedFiles([]);
    }
  };

  // 선택 삭제 핸들러
  const handleDelete = () => {
    const newSources = sources.filter((_, index) => !checked.includes(index));
    setSources(newSources);
    setChecked([]);
    setCheckedFiles([]);
  };

  const handleOpenModal = () => {
    setIsModalOpen(true);
  };
  
  // 파일 업로드 모달을 여는 함수
  const handleOpenFileUploadModal = () => {
    if (onFileUploadClick) onFileUploadClick();
  };
  
  // 검색 모달을 여는 함수
  const handleOpenSearchModal = () => {
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
  };

  const handleBackToList = () => {
    setSelectedSource(null);
    setFileContent('');
  };

  const handleSourceClick = async (source: SourceItem) => {
    if (source.status === 'processing' || source.status === 'failed') {
      console.log(`Source '${source.title}' is not ready.`);
      return;
    }

    // 접은 상태에서 파일을 클릭하면 패널을 펼침
    if (collapsed) {
      onToggleCollapse();
    }

    if (selectedSource && selectedSource.id === source.id) {
      return; // 이미 선택된 파일이면 아무것도 안 함
    }

    setIsLoading(true);
    setSelectedSource(source);

    try {
      const response = await api.get(`/api/file/${source.title}`);
      const data = response.data;
      setFileContent(data.content);
    } catch (error) {
      console.error(error);
      setFileContent('파일 내용을 불러오는 데 실패했습니다.');
    } finally {
      setIsLoading(false);
    }
  };

  // 파일 확장자에 따른 아이콘 선택 함수
  const getFileIcon = (fileName: string) => {
    const lowerFileName = fileName.toLowerCase();
    
    if (lowerFileName.endsWith('.pdf')) {
      return <FileType className="text-red-500" size={20} />;
    } else if (lowerFileName.endsWith('.md')) {
      return <FileText className="text-blue-500" size={20} />;
    } else if (lowerFileName.endsWith('.jpg') || lowerFileName.endsWith('.png') || lowerFileName.endsWith('.jpeg') || lowerFileName.endsWith('.gif')) {
      return <ImageIcon className="text-green-500" size={20} />;
    } else if (lowerFileName.endsWith('.js') || lowerFileName.endsWith('.py') || lowerFileName.endsWith('.java') || lowerFileName.endsWith('.html') || lowerFileName.endsWith('.css')) {
      return <Code className="text-purple-500" size={20} />;
    }
    
    return <File size={20} />;
  };

  return (
    <div 
      id="leftbox" 
      className={`${collapsed ? 'w-12' : 'w-[95%]'} h-[95%] border border-gray-200 rounded-2xl overflow-hidden flex flex-col`}
    >
      <div className="w-full h-full flex flex-col bg-white overflow-hidden">
        {/* Header */}
        <div className={`flex justify-between items-center ${collapsed ? 'px-1 py-2' : 'px-4 py-2'} border-b border-gray-200 flex-shrink-0 min-h-[52px]`}>
          {!collapsed && (
            <h2 className="text-lg font-bold">라이브러리</h2>
          )}
          <button 
            onClick={onToggleCollapse}
            className="p-1 rounded-md hover:bg-gray-100"
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        {/* Button Row */}
        {!collapsed ? (
          <div className="flex items-center justify-between p-1 border-b border-gray-200">
            <button 
              onClick={onFileUploadClick}
              className="flex items-center px-3 py-1 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
            >
              <Plus size={16} className="mr-1" />
              추가
            </button>
            <button 
              onClick={handleOpenModal}
              className="flex items-center px-3 py-1 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
            >
              <Search size={16} className="mr-1" />
              탐색
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 py-2 border-b border-gray-200">
            <button 
              onClick={onFileUploadClick}
              title="파일 추가"
              className="p-1.5 bg-gray-100 rounded-lg hover:bg-gray-200 w-8 h-8 flex items-center justify-center"
            >
              <Plus size={16} />
            </button>
            <button 
              onClick={handleOpenModal}
              title="파일 탐색"
              className="p-1.5 bg-gray-100 rounded-lg hover:bg-gray-200 w-8 h-8 flex items-center justify-center"
            >
              <Search size={16} />
            </button>
          </div>
        )}

        {/* Source Panel Content */}
        {collapsed ? (
          <div className="flex flex-col items-center h-[calc(100%-130px)] relative overflow-hidden w-full">
            {/* 파일 목록 영역 - 접힌 상태 */}
            <div className="flex flex-col items-center justify-start pt-2 gap-2 py-2 w-full h-full flex-grow overflow-y-auto overflow-x-hidden scrollbar-thin scrollbar-thumb-gray-400 scrollbar-track-transparent relative hover:scroll-button:opacity-70">
              {/* 파일 목록의 모든 파일을 개별 아이콘으로 표시 */}
              {sources.map((source, index) => {
                // 파일 상태에 따라 아이콘 표시 방식 변경
                if (source.status === 'processing') {
                  return (
                    <div 
                      key={index}
                      title={`${source.title} (처리 중...)`}
                      className="relative bg-gray-100 rounded-lg p-1.5 m-1 w-8 h-8 transition-all"
                    >
                      <div className="opacity-50">
                        {getFileIcon(source.title)}
                      </div>
                      <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2">
                        <div className="animate-spin h-4 w-4 border-2 border-blue-500 rounded-full border-t-transparent"></div>
                      </div>
                    </div>
                  );
                } else if (source.status === 'failed') {
                  return (
                    <div 
                      key={index}
                      title={`${source.title} (처리 실패)`}
                      className="relative bg-red-50 rounded-lg p-1.5 m-1 w-8 h-8 transition-all"
                    >
                      <AlertCircle className="text-red-500" size={16} />
                    </div>
                  );
                } else {
                  return (
                    <button 
                      key={index}
                      onClick={() => handleSourceClick(source)}
                      title={source.title}
                      className={`relative bg-gray-100 rounded-lg p-1.5 m-1 w-8 h-8 transition-all hover:bg-gray-200 hover:scale-105 ${
                        selectedSource?.id === source.id ? 'bg-blue-50 ring-2 ring-blue-500' : ''
                      }`}
                    >
                      {getFileIcon(source.title)}
                    </button>
                  );
                }
              })}
            </div>
            
            {/* 위로 스크롤 버튼 */}
            <div className="scroll-button absolute top-2.5 right-2.5 z-10 opacity-0 transition-opacity duration-300">
              <button 
                className="bg-white/90 shadow-md w-7 h-7 rounded-full flex items-center justify-center hover:bg-gray-100"
                onClick={() => {
                  const scrollContainer = document.querySelector('div[id="leftbox"] > div > div:nth-child(3)');
                  if (scrollContainer) {
                    scrollContainer.scrollBy({ top: -150, behavior: 'smooth' });
                  }
                }}
              >
                <ChevronUp size={16} />
              </button>
            </div>
            
            {/* 아래로 스크롤 버튼 */}
            <div className="scroll-button absolute bottom-2.5 right-2.5 z-10 opacity-0 transition-opacity duration-300">
              <button 
                className="bg-white/90 shadow-md w-7 h-7 rounded-full flex items-center justify-center hover:bg-gray-100"
                onClick={() => {
                  const scrollContainer = document.querySelector('div[id="leftbox"] > div > div:nth-child(3)');
                  if (scrollContainer) {
                    scrollContainer.scrollBy({ top: 150, behavior: 'smooth' });
                  }
                }}
              >
                <ChevronDown size={16} />
              </button>
            </div>
          </div>
        ) : (
          <div className="flex-grow overflow-y-auto p-4">
            {selectedSource ? (
              <div className="h-full flex flex-col">
                <div className="flex items-center p-2 border-b border-gray-200">
                  <button 
                    onClick={handleBackToList}
                    className="p-1 rounded-md hover:bg-gray-100"
                  >
                    <ArrowLeft size={18} />
                  </button>
                  <h3 className="ml-2 text-base font-bold flex-grow truncate">
                    {selectedSource.title}
                  </h3>
                  <button 
                    onClick={() => setFileContentModalOpen(true)}
                    title="모달로 보기"
                    className="p-1 rounded-md hover:bg-gray-100"
                  >
                    <ExternalLink size={18} />
                  </button>
                </div>
                <div className="flex-grow p-4 overflow-y-auto">
                  {isLoading ? (
                    <div className="flex justify-center items-center h-full">
                      <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent"></div>
                    </div>
                  ) : (
                    <FileContentBox content={fileContent} />
                  )}
                </div>
              </div>
            ) : (
              <>
                <div className="flex justify-between items-center px-2 mb-2 h-9">
                  <div className="flex items-center">
                    <input
                      type="checkbox"
                      onChange={handleSelectAll}
                      checked={sources.length > 0 && checked.length === sources.length}
                      className="mr-2 h-4 w-4"
                    />
                    <span className="text-sm">전체 선택</span>
                  </div>
                  <button 
                    onClick={handleDelete} 
                    disabled={checked.length === 0}
                    className={`p-1 rounded-md ${checked.length === 0 ? 'text-gray-300' : 'hover:bg-gray-100 text-gray-700'}`}
                  >
                    <Trash2 size={18} />
                  </button>
                </div>

                {/* Source List */}
                <ul className="space-y-2">
                  {sources.map((source, index) => (
                    <li 
                      key={index}
                      onClick={() => handleSourceClick(source)}
                      className="p-1 mb-2 rounded border border-gray-200 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
                    >
                      {source.status === 'processing' ? (
                        <div className="w-full p-2">
                          <div className="overflow-hidden text-ellipsis whitespace-nowrap text-sm">{source.title}</div>
                          <div className="w-full bg-gray-200 rounded-full h-1.5 mt-1">
                            <div className="bg-blue-500 h-1.5 rounded-full animate-pulse" style={{ width: '60%' }}></div>
                          </div>
                          <div className="text-xs text-gray-500 mt-1">처리중...</div>
                        </div>
                      ) : (
                        <>
                          <div className="flex items-center flex-grow min-w-0">
                            <div className="min-w-[40px] flex items-center justify-center">
                              {source.status === 'failed' ? (
                                <AlertCircle className="text-red-500" size={20} />
                              ) : (
                                getFileIcon(source.title)
                              )}
                            </div>
                            <div className="ml-2 truncate">
                              <span className={`text-sm ${source.status === 'failed' ? 'text-red-500' : ''}`}>
                                {source.status === 'failed' ? "처리 실패" : source.title}
                              </span>
                            </div>
                          </div>
                        </>
                      )}
                      <input
                        type="checkbox"
                        onChange={handleToggle(index)}
                        checked={checked.indexOf(index) !== -1}
                        onClick={(e) => e.stopPropagation()}
                        className="mr-1 h-4 w-4"
                      />
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </div>
      
      {/* 파일 내용 모달 */}
      {fileContentModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg w-full max-w-3xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">{selectedSource?.title || '파일 내용'}</h3>
              <button
                onClick={() => setFileContentModalOpen(false)}
                className="p-1 rounded-md hover:bg-gray-100"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-x"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
              </button>
            </div>
            <div className="p-0 overflow-auto flex-grow">
              {isLoading ? (
                <div className="flex justify-center items-center p-8">
                  <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent"></div>
                </div>
              ) : (
                <FileContentBox content={fileContent} />
              )}
            </div>
          </div>
        </div>
      )}
      
      {/* 검색 모달 - 나중에 구현 */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg w-full max-w-3xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">문서 검색</h3>
              <button
                onClick={handleCloseModal}
                className="p-1 rounded-md hover:bg-gray-100"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-x"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
              </button>
            </div>
            <div className="p-4">
              <p>검색 기능은 추후 구현 예정입니다.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Leftbox;
