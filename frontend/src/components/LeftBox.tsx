'use client';

import { useState, useEffect, useMemo } from 'react';
import api from '@/lib/api';
import FileContentBox from './FileContentBox';
import Searchbox from './SearchBox';
import FileUploadBox from './FileUploadBox';
import { useGetFiles, FileListResponse } from '@/queries';
import { useQueryClient } from '@tanstack/react-query';
import Swal from 'sweetalert2';
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  Trash2,
  ArrowLeft,
  ExternalLink,
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
  const [documentUuidMap, setDocumentUuidMap] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState<number[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState<SourceItem | null>(null);
  const [fileContent, setFileContent] = useState('');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [fileUploadModalOpen, setFileUploadModalOpen] = useState(false);

  const queryClient = useQueryClient();

  const { data: fileList, isLoading: isLoadingFiles } = useGetFiles({
    onError: (error: Error) => {
      console.error('파일 목록을 불러오는 데 실패했습니다:', error);
      Swal.fire('오류', '파일 목록을 불러오는 데 실패했습니다. 서버 상태를 확인해주세요.', 'error');
    },
  });

  const files = useMemo<string[]>(() => fileList?.files ?? [], [fileList]);

  useEffect(() => {
    if (fileList) {
      const { files: fileNames, document_uuid_map } = fileList;

      if (document_uuid_map) {
        setDocumentUuidMap(document_uuid_map);
      } else {
        setDocumentUuidMap({});
      }

      const newSources = fileNames.map((fileName: string) => ({
        id: fileName,
        title: fileName,
        status: 'completed' as const,
      }));
      setSources(prevSources => {
        const processingSources = prevSources.filter(source => source.status === 'processing');
        const existingFiles = new Set(prevSources.map((s: SourceItem) => s.title));
        const uniqueNewSources = newSources.filter((s: SourceItem) => !existingFiles.has(s.title));
        return [...uniqueNewSources, ...processingSources];
      });
    }
  }, [fileList]);

  const handleProcessingStart = (tasks: any[]) => {
    const newSources = tasks.map(task => ({
      id: task.task_id,
      title: task.title,
      status: 'processing' as const,
      taskId: task.task_id,
    }));
    setSources(prevSources => [...prevSources, ...newSources]);
  };

  const handleToggle = (value: number) => () => {
    const currentIndex = checked.indexOf(value);
    const newChecked = [...checked];
    if (currentIndex === -1) {
      newChecked.push(value);
    } else {
      newChecked.splice(currentIndex, 1);
    }
    setChecked(newChecked);
    const newCheckedFiles = newChecked.map(index => sources[index].title);
    setCheckedFiles(newCheckedFiles);
    if (onFilesSelected) {
      onFilesSelected(newCheckedFiles);
    }
  };

  const handleSelectAll = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked) {
      const newChecked = sources.map((_, i) => i);
      setChecked(newChecked);
      const newCheckedFiles = sources.map(source => source.title);
      setCheckedFiles(newCheckedFiles);
      if (onFilesSelected) {
        onFilesSelected(newCheckedFiles);
      }
    } else {
      setChecked([]);
      setCheckedFiles([]);
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
        const uuidPayload: Record<string, string> = {};
        checkedFiles.forEach(filename => {
          const uuid = documentUuidMap[filename];
          if (uuid) {
            uuidPayload[filename] = uuid;
          }
        });

        await api.deleteFile(checkedFiles, uuidPayload);

        setChecked([]);
        setCheckedFiles([]);
        Swal.fire('삭제 완료!', '파일이 삭제되었습니다.', 'success');
        queryClient.invalidateQueries({ queryKey: ['files'] });
      } catch (error) {
        console.error('파일 삭제 오류 발생:', error);
        Swal.fire('오류가 발생했습니다.', '파일 삭제 중 오류가 발생했습니다.', 'error');
      }
    }
  };

  const handleOpenModal = () => setIsSearchModalOpen(true);
  const handleOpenFileUploadModal = () => setFileUploadModalOpen(true);
  const handleCloseFileUploadModal = () => setFileUploadModalOpen(false);

  const handleFilesAdd = async (addedFiles: File[]) => {
    try {
      const response = await api.uploadFiles(addedFiles);
      if (response.data?.success) {
        console.log('파일 업로드 성공');
        queryClient.invalidateQueries({ queryKey: ['files'] });
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
    if (collapsed) onToggleCollapse();
    if (selectedSource?.id === source.id) return;
    setIsLoading(true);
    setSelectedSource(source);
    try {
      const response = await api.getFileContent(source.title);
      setFileContent(response.data.content);
    } catch (error) {
      console.error(error);
      setFileContent('파일 내용을 불러오는 데 실패했습니다.');
    } finally {
      setIsLoading(false);
    }
  };

  const getFileIcon = (fileName: string) => {
    const lowerFileName = fileName.toLowerCase();
    if (lowerFileName.endsWith('.pdf') || lowerFileName.endsWith('_pdf'))
      return <FileType className="text-red-500" size={20} />;
    if (lowerFileName.endsWith('.md')) return <FileText className="text-blue-500" size={20} />;
    if (
      lowerFileName.endsWith('.jpg') ||
      lowerFileName.endsWith('.png') ||
      lowerFileName.endsWith('.jpeg') ||
      lowerFileName.endsWith('.gif')
    )
      return <ImageIcon className="text-green-500" size={20} />;
    if (
      lowerFileName.endsWith('.js') ||
      lowerFileName.endsWith('.py') ||
      lowerFileName.endsWith('.java') ||
      lowerFileName.endsWith('.html') ||
      lowerFileName.endsWith('.css')
    )
      return <Code className="text-purple-500" size={20} />;
    return <File size={20} />;
  };

  const formatFileName = (fileName: string) => {
    let name = fileName;
    while (name.endsWith('.md')) {
      name = name.slice(0, -3);
    }
    const lastDotIndex = name.lastIndexOf('.');
    if (lastDotIndex !== -1) {
      const ext = name.substring(lastDotIndex);
      const knownExts = [
        '.pdf',
        '.txt',
        '.hwp',
        '.csv',
        '.xlsx',
        '.docx',
        '.pptx',
        '.jpg',
        '.png',
        '.py',
        '.js',
        '.html',
        '.css',
      ];
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

        {!collapsed ? (
          <>
            {/* --- Action Toolbar --- */}
            <div className="flex items-center justify-between p-2 border-b border-gray-200 bg-gray-50/50">
              <div className="flex gap-2">
                <button
                  onClick={handleOpenFileUploadModal}
                  disabled={isUploading}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-sm rounded-md bg-white border border-gray-300 hover:bg-gray-100 disabled:opacity-50"
                >
                  {isUploading ? (
                    <div className="animate-spin h-4 w-4 border-2 border-blue-500 rounded-full border-t-transparent"></div>
                  ) : (
                    <Plus size={16} />
                  )}
                  추가
                </button>
                <button
                  onClick={handleOpenModal}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-sm rounded-md bg-white border border-gray-300 hover:bg-gray-100"
                >
                  <Search size={16} />
                  탐색
                </button>
              </div>
            </div>

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
              onClick={handleOpenFileUploadModal}
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
            <div className="no-scrollbar flex flex-col items-center justify-start pt-2 gap-2 py-2 w-full h-full flex-grow overflow-y-auto overflow-x-hidden relative">
              {sources.map((source, index) => (
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
              ))}
            </div>
          </div>
        ) : (
          <div className="flex-grow flex flex-col overflow-hidden">
            {selectedSource ? (
              <div className="h-full flex flex-col">
                <div className="flex items-center p-2 border-b border-gray-200 flex-shrink-0">
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
                <div className="flex-grow p-4 overflow-y-auto no-scrollbar">
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
              <div className="h-full flex flex-col">
                <div className="flex-shrink-0 flex justify-between items-center p-2 border-b border-gray-200 bg-gray-50/50">
                  <div className="flex items-center">
                    <input
                      type="checkbox"
                      onChange={handleSelectAll}
                      checked={sources.length > 0 && checked.length === sources.length}
                      className="mr-2 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm font-medium text-gray-700">전체 선택</span>
                  </div>
                  <button
                    onClick={handleDelete}
                    disabled={checked.length === 0}
                    className={`p-1 rounded-md disabled:text-gray-300 disabled:cursor-not-allowed text-gray-600 hover:bg-gray-200`}
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
                <div className="flex-grow overflow-y-auto no-scrollbar p-2">
                  <ul className="space-y-2">
                    {sources.map((source, index) => (
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
                </div>
              </div>
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
                  viewBox="0 0 24"
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
