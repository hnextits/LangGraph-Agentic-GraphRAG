'use client';

import { useState, useEffect, useCallback } from 'react';
import api from '@/lib/api';
import FileContentBox from './FileContentBox';
import Searchbox from './SearchBox';
import FileUploadBox from './FileUploadBox';
import { useGetFiles } from '@/queries';

import { useQueryClient } from '@tanstack/react-query';

import Swal from 'sweetalert2';

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
  File,
  FileText,
  Image as ImageIcon,
  Code,
  FileType,
} from 'lucide-react';

// 타입 정의
interface SourceItem {
  id: string;
  title: string;
  taskId?: string;
  status?: 'completed' | 'processing' | 'failed';
}

interface LeftBoxProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onFileUploadClick?: () => void;
  onFilesSelected?: (files: string[]) => void;
}

const LeftBox: React.FC<LeftBoxProps> = ({
  collapsed = false,
  onToggleCollapse = () => {},
  onFileUploadClick,
  onFilesSelected,
}) => {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [isSearchModalOpen, setIsSearchModalOpen] = useState(false);
  const [isFileUploadModalOpen, setIsFileUploadModalOpen] = useState(false);
  const [checkedFiles, setCheckedFiles] = useState<string[]>([]);
  const [checked, setChecked] = useState<number[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState<SourceItem | null>(null);
  const [fileContent, setFileContent] = useState('');

  // 파일 업로드 상태 관리
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [fileUploadModalOpen, setFileUploadModalOpen] = useState(false);

  const queryClient = useQueryClient();

  // 파일 리스트 불러오기
  const { data: files, isLoading: isLoadingFiles } = useGetFiles();

  // 파일 데이터가 로드되면 sources 상태 업데이트
  useEffect(() => {
    if (files && files.length > 0) {
      const newSources = files.map(fileName => ({
        id: fileName,
        title: fileName,
        status: 'completed' as const,
      }));
      setSources(prevSources => {
        // 처리 중인 문서는 유지
        const processingSources = prevSources.filter(source => source.status === 'processing');
        return [...newSources, ...processingSources];
      });
    }
  }, [files]);

  const handleProcessingStart = (tasks: any[]) => {
    const newSources = tasks.map(task => ({
      id: task.task_id,
      title: task.title,
      status: 'processing' as const,
      taskId: task.task_id,
    }));
    setSources(prevSources => [...prevSources, ...newSources]);
  };

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
    console.log(newCheckedFiles);
    setCheckedFiles(newCheckedFiles);

    // props로 전달받은 onFilesSelected 함수가 있다면 호출
    if (onFilesSelected) {
      onFilesSelected(newCheckedFiles);
    }
  };

  // 전체 선택 핸들러
  const handleSelectAll = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked) {
      const newChecked = Array.from({ length: sources.length }, (_, i) => i);
      setChecked(newChecked);
      // 체크된 파일 이름 목록 업데이트
      const newCheckedFiles = sources.map(source => source.title);
      setCheckedFiles(newCheckedFiles);

      // props로 전달받은 onFilesSelected 함수가 있다면 호출
      if (onFilesSelected) {
        onFilesSelected(newCheckedFiles);
      }
    } else {
      setChecked([]);
      setCheckedFiles([]);

      // 선택 해제 시에도 비어있는 배열 전달
      if (onFilesSelected) {
        onFilesSelected([]);
      }
    }
  };

  const handleDelete = async () => {
    if (checkedFiles.length === 0) return;

    const result = await Swal.fire({
      title: '정말 삭제하시겠습니까?',
      text: '삭제된 파일은 복구할 수 없습니다',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: '삭제',
      cancelButtonText: '취소',
      reverseButtons: true,
    });

    if (result.isConfirmed) {
      try {
        const response = await api.deleteFile(checkedFiles);
        if (response.data?.deleted_files && response.data.deleted_files.length > 0) {
          setChecked([]);
          setCheckedFiles([]);
          Swal.fire('삭제 완료!', '파일이 삭제되었습니다.', 'success');
          queryClient.invalidateQueries({ queryKey: ['files'] });
        } else {
          const errorMessage =
            response.data?.failed_files?.length > 0
              ? `파일 삭제 실패: ${response.data.failed_files
                  .map((f: { filename: string; reason: string }) => f.filename)
                  .join(', ')}`
              : '파일 삭제에 실패했습니다.';
          Swal.fire('파일 삭제에 실패했습니다.', errorMessage, 'error');
        }
      } catch (error) {
        console.error('파일 삭제 오류 발생:', error);
        Swal.fire('오류가 발생했습니다.', '파일 삭제 중 오류가 발생했습니다.', 'error');
      }
    }
  };

  const handleOpenModal = () => {
    setIsSearchModalOpen(true);
  };

  // 파일 업로드 모달을 여는 함수
  const handleOpenFileUploadModal = () => {
    setFileUploadModalOpen(true);
  };

  // 파일 업로드 모달 핸들러
  const handleCloseFileUploadModal = () => {
    setFileUploadModalOpen(false);
  };

  // 파일 업로드 핸들러 - FileUploadBox에 전달할 콜백 함수
  const handleFilesAdd = async (addedFiles: File[]) => {
    try {
      const response = await api.uploadFiles(addedFiles);

      // 파일 업로드 완료 후 처리
      if (response.data?.success) {
        console.log('파일 업로드 성공');
      }

      return response.data;
    } catch (error) {
      console.error('파일 업로드 실패:', error);
      alert('파일 업로드에 실패했습니다. 서버 로그를 확인해주세요.');
      throw error;
    }
  };

  const handleBackToList = () => {
    setSelectedSource(null);
    setFileContent('');
  };

  const handleSourceClick = async (source: SourceItem) => {
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
      const response = await api.getFileContent(source.title);
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

    if (lowerFileName.endsWith('.pdf') || lowerFileName.endsWith('_pdf')) {
      return <FileType className="text-red-500" size={20} />;
    } else if (lowerFileName.endsWith('.md')) {
      return <FileText className="text-blue-500" size={20} />;
    } else if (
      lowerFileName.endsWith('.jpg') ||
      lowerFileName.endsWith('.png') ||
      lowerFileName.endsWith('.jpeg') ||
      lowerFileName.endsWith('.gif')
    ) {
      return <ImageIcon className="text-green-500" size={20} />;
    } else if (
      lowerFileName.endsWith('.js') ||
      lowerFileName.endsWith('.py') ||
      lowerFileName.endsWith('.java') ||
      lowerFileName.endsWith('.html') ||
      lowerFileName.endsWith('.css')
    ) {
      return <Code className="text-purple-500" size={20} />;
    }

    return <File size={20} />;
  };

  const formatFileName = (fileName: string) => {
    let name = fileName;
    // 파일 이름 끝에 .md가 반복되는 경우 모두 제거
    while (name.endsWith('.md')) {
        name = name.slice(0, -3);
    }
    // 다른 확장자도 제거
    const lastDotIndex = name.lastIndexOf('.');
    if (lastDotIndex !== -1) {
        // 하지만 알려진 확장자가 아니면, 파일 이름의 일부일 수 있으므로 제거하지 않음
        const ext = name.substring(lastDotIndex);
        const knownExts = ['.pdf', '.txt', '.hwp', '.csv', '.xlsx', '.docx', '.pptx', '.jpg', '.png', '.py', '.js', '.html', '.css'];
        if (knownExts.includes(ext.toLowerCase())) {
            name = name.substring(0, lastDotIndex);
        }
    }
    return name;
  };

  return (
    <div
      id="leftbox"
      className={`${
        collapsed ? 'w-12' : 'w-[95%]'
      } h-full border border-gray-200 rounded-2xl overflow-hidden flex flex-col`}
    >
      <div className="w-full h-full flex flex-col bg-white overflow-hidden">
        {/* Header */}
        <div
          className={`flex items-center ${
            collapsed ? 'justify-center px-1 py-2 ' : 'justify-between px-4 py-2'
          }  border-b border-gray-200 flex-shrink-0 min-h-[52px]`}
        >
          {!collapsed && <h2 className="text-lg font-bold">라이브러리</h2>}
          <button onClick={onToggleCollapse} className="p-1 rounded-md hover:bg-gray-100">
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        {/* Button Row */}
        {!collapsed ? (
          <>
            <div className="flex items-center justify-between p-1 border-b border-gray-200">
              <button
                onClick={handleOpenFileUploadModal}
                className="flex items-center px-3 py-1 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
                disabled={isUploading}
              >
                {isUploading ? (
                  <div className="animate-spin h-4 w-4 border-2 border-blue-500 rounded-full border-t-transparent mr-1"></div>
                ) : (
                  <Plus size={16} className="mr-1" />
                )}
                {isUploading ? '업로드 중' : '추가'}
              </button>
              <button
                onClick={handleOpenModal}
                className="flex items-center px-3 py-1 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
              >
                <Search size={16} className="mr-1" />
                탐색
              </button>
            </div>

            {/* 업로드 프로그레스바 */}
            {isUploading && (
              <div className="px-2 py-1 border-b border-gray-200">
                <div className="text-xs text-gray-600 mb-1 flex justify-between">
                  <span>파일 업로드 중...</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-300 ease-in-out"
                    style={{ width: `${uploadProgress}%` }}
                  ></div>
                </div>
                {uploadingFiles.length > 0 && (
                  <div className="text-xs text-gray-500 mt-1 truncate">
                    {uploadingFiles[0]}
                    {uploadingFiles.length > 1 ? ` 외 ${uploadingFiles.length - 1}개` : ''}
                  </div>
                )}
              </div>
            )}
          </>
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
            <div className="no-scrollbar flex flex-col items-center justify-start pt-2 gap-2 py-2 w-full h-full flex-grow overflow-y-auto overflow-x-hidden relative hover:scroll-button:opacity-70">
              {/* 파일 목록의 모든 파일을 개별 아이콘으로 표시 */}
              {sources.map((source, index) => {
                return (
                  // todo: 실패 처리 로직 추가해야함
                  <button
                    key={index}
                    onClick={() => handleSourceClick(source)}
                    title={formatFileName(source.title)}
                    className={`relative bg-gray-100 rounded-lg p-1.5 m-1 w-8 h-8 transition-all hover:bg-gray-200 hover:scale-105 ${
                      selectedSource?.id === source.id ? 'bg-blue-50 ring-2 ring-blue-500' : ''
                    }`}
                  >
                    {getFileIcon(source.title)}
                  </button>
                );
              })}
            </div>

            {/* 위로 스크롤 버튼 */}
            {/* <div className="scroll-button absolute top-2.5 right-2.5 z-10 opacity-0 transition-opacity duration-300">
              <button
                className="bg-white/90 shadow-md w-7 h-7 rounded-full flex items-center justify-center hover:bg-gray-100"
                onClick={() => {
                  const scrollContainer = document.querySelector(
                    'div[id="leftbox"] > div > div:nth-child(3)'
                  );
                  if (scrollContainer) {
                    scrollContainer.scrollBy({ top: -150, behavior: 'smooth' });
                  }
                }}
              >
                <ChevronUp size={16} />
              </button>
            </div> */}

            {/* 아래로 스크롤 버튼 */}
            {/* <div className="scroll-button absolute bottom-2.5 right-2.5 z-10 opacity-0 transition-opacity duration-300">
              <button
                className="bg-white/90 shadow-md w-7 h-7 rounded-full flex items-center justify-center hover:bg-gray-100"
                onClick={() => {
                  const scrollContainer = document.querySelector(
                    'div[id="leftbox"] > div > div:nth-child(3)'
                  );
                  if (scrollContainer) {
                    scrollContainer.scrollBy({ top: 150, behavior: 'smooth' });
                  }
                }}
              >
                <ChevronDown size={16} />
              </button>
            </div> */}
          </div>
        ) : (
          <div className="flex-grow overflow-y-auto p-4 no-scrollbar">
            {selectedSource ? (
              <div className="h-full flex flex-col">
                <div className="flex items-center p-2 border-b border-gray-200">
                  <button onClick={handleBackToList} className="p-1 rounded-md hover:bg-gray-100">
                    <ArrowLeft size={18} />
                  </button>
                  <h3 className="ml-2 text-base font-bold flex-grow truncate">
                    {formatFileName(selectedSource.title)}
                  </h3>
                  <button
                    onClick={() => setIsFileUploadModalOpen(true)}
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
                    className={`p-1 rounded-md ${
                      checked.length === 0 ? 'text-gray-300' : 'hover:bg-gray-100 text-gray-700'
                    }`}
                  >
                    <Trash2 size={18} />
                  </button>
                </div>

                {/* Source List */}
                <ul className="space-y-2">
                  {sources.map((source, index) => (
                    //  todo: 랜더링 조건 추가하기
                    <li
                      key={index}
                      onClick={() => handleSourceClick(source)}
                      className="p-1 mb-2 rounded border border-gray-200 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
                    >
                      <div className="flex items-center flex-grow min-w-0">
                        <div className="min-w-[40px] flex items-center justify-center">
                          {getFileIcon(source.title)}
                        </div>
                        <div className="ml-2 truncate">
                          <span className="text-sm">{formatFileName(source.title)}</span>
                        </div>
                      </div>
                      <input
                        type="checkbox"
                        onChange={handleToggle(index)}
                        checked={checked.indexOf(index) !== -1}
                        onClick={e => e.stopPropagation()}
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
      {isFileUploadModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg w-full max-w-3xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">{selectedSource?.title || '파일 내용'}</h3>
              <button
                onClick={() => setIsFileUploadModalOpen(false)}
                className="p-1 rounded-md hover:bg-gray-100"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="lucide lucide-x"
                >
                  <path d="M18 6 6 18" />
                  <path d="m6 6 12 12" />
                </svg>
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

      {/* 검색 모달 */}
      <Searchbox
        open={isSearchModalOpen}
        onClose={() => setIsSearchModalOpen(false)}
        onProcessingStart={handleProcessingStart}
      />

      {/* 파일 업로드 모달 */}
      <FileUploadBox
        isOpen={fileUploadModalOpen}
        onClose={handleCloseFileUploadModal}
        onFilesAdd={handleFilesAdd}
      />
    </div>
  );
};

export default LeftBox;
