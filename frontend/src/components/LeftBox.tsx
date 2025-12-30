import React, { useState, useEffect, useContext, useMemo, useCallback } from 'react';
import api from '@/lib/api';
import FileContentBox from './FileContentBox';
import FileContentModal from './FileContentModal';
import Searchbox from './SearchBox';
import FileUploadBox from './FileUploadBox';
import ReportModal from './ReportModal';
import { useQueryClient } from '@tanstack/react-query';
import AlertModal from './AlertModal';
import { FileContext } from '@/contexts/FileContext';
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
  FileType,
  FileSpreadsheet,
  Presentation,
  ImageIcon,
  Code,
  WandSparkles,
  Loader2,
  Circle,
  CircleCheck,
  Network,
  FileBarChart,
  Music,
  Video,
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
  files: string[] | undefined;
  documentUuidMap?: Record<string, string>;
  isLoadingFiles: boolean;
}

const LeftBox: React.FC<LeftBoxProps> = React.memo(({
  collapsed = false,
  onToggleCollapse = () => {},
  onFileUploadClick,
  onFilesSelected,
  files,
  documentUuidMap,
  isLoadingFiles,
}) => {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [isSearchModalOpen, setIsSearchModalOpen] = useState(false);
  const [isFileUploadModalOpen, setIsFileUploadModalOpen] = useState(false);
  const [isFileContentModalOpen, setIsFileContentModalOpen] = useState(false);
  const [checked, setChecked] = useState<number[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState<SourceItem | null>(null);
  const [fileContent, setFileContent] = useState('');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [fileUploadModalOpen, setFileUploadModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isDeleteSuccessModalOpen, setIsDeleteSuccessModalOpen] = useState(false);
  const [isDeleteFailModalOpen, setIsDeleteFailModalOpen] = useState(false);
  const [deleteErrorMessage, setDeleteErrorMessage] = useState('');

  // 요약 관련 상태
  const [isSummaryLoading, setIsSummaryLoading] = useState<boolean>(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [isSelectFileModalOpen, setIsSelectFileModalOpen] = useState(false);
  const [isNotSupportSummaryModalOpen, setIsNotSupportSummaryModalOpen] = useState(false); // 요약을 지원하지 않는 팡리 경고 모달

  // 마인드맵 관련 상태
  const [isMindmapLoading, setIsMindmapLoading] = useState<boolean>(false);
  const [isSelectFileForMindmapModalOpen, setIsSelectFileForMindmapModalOpen] = useState(false);
  const [isMindmapSuccessModalOpen, setIsMindmapSuccessModalOpen] = useState(false);
  const [isMindmapErrorModalOpen, setIsMindmapErrorModalOpen] = useState(false);
  const [mindmapErrorMessage, setMindmapErrorMessage] = useState('');

  // 보고서 관련 상태
  const [isReportLoading, setIsReportLoading] = useState<boolean>(false);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);

  const queryClient = useQueryClient();
  const {
    checkedFilenames,
    setCheckedFilenames,
    checkedFileUuids,
    setCheckedFileUuids,
    documentUuidMap: contextDocumentUuidMap,
    setDocumentUuidMap,
  } = useContext(FileContext);

  useEffect(() => {
    if (files) {
      const newSources = files.map(fileName => ({
        id: fileName,
        title: fileName,
        status: 'completed' as const,
      }));
      setSources(newSources);
    }
  }, [files]);

  useEffect(() => {
    if (documentUuidMap) {
      setDocumentUuidMap(documentUuidMap);
    }
  }, [documentUuidMap, setDocumentUuidMap]);

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
    setCheckedFilenames(newCheckedFiles);

    const uuidMap = documentUuidMap ?? contextDocumentUuidMap;
    const newCheckedUuids = newCheckedFiles
      .map(filename => uuidMap[filename])
      .filter((uuid): uuid is string => Boolean(uuid));
    setCheckedFileUuids(newCheckedUuids);

    if (onFilesSelected) {
      onFilesSelected(newCheckedFiles);
    }
  };

  const handleSelectAll = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked) {
      const newChecked = sources.map((_, i) => i);
      setChecked(newChecked);
      const newCheckedFiles = sources.map(source => source.title);
      setCheckedFilenames(newCheckedFiles);
      const uuidMap = documentUuidMap ?? contextDocumentUuidMap;
      const newCheckedUuids = newCheckedFiles
        .map(filename => uuidMap[filename])
        .filter((uuid): uuid is string => Boolean(uuid));
      setCheckedFileUuids(newCheckedUuids);
      if (onFilesSelected) {
        onFilesSelected(newCheckedFiles);
      }
    } else {
      setChecked([]);
      setCheckedFilenames([]);
      setCheckedFileUuids([]);
      if (onFilesSelected) {
        onFilesSelected([]);
      }
    }
  };

  const handleDelete = () => {
    if (checkedFilenames.length === 0) return;
    setIsDeleteModalOpen(true);
  };

  const confirmDelete = async () => {
    setIsDeleteModalOpen(false);
    try {
      const response = await api.deleteFile(checkedFilenames, documentUuidMap ?? contextDocumentUuidMap);
      if (response.data?.deleted_files?.length > 0) {
        setChecked([]);
        setCheckedFilenames([]);
        setCheckedFileUuids([]);
        queryClient.invalidateQueries({ queryKey: ['files'] });
        setIsDeleteSuccessModalOpen(true);
      } else {
        const errorMessage =
          response.data?.failed_files?.length > 0
            ? `파일 삭제 실패: ${response.data.failed_files
                .map((f: { filename: string; reason: string }) => f.filename)
                .join(', ')}`
            : '파일 삭제에 실패했습니다.';
        setDeleteErrorMessage(errorMessage);
        setIsDeleteFailModalOpen(true);
      }
    } catch (error) {
      console.error('파일 삭제 오류 발생:', error);
      setDeleteErrorMessage('파일 삭제 중 오류가 발생했습니다.');
      setIsDeleteFailModalOpen(true);
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
      return (
        <div className="bg-red-100 rounded-md p-1 items-center">
          <FileType className="text-red-500" size={20} />
        </div>
      );
    if (lowerFileName.endsWith('.md'))
      return (
        <div className="bg-blue-100 rounded-md p-1 items-center">
          <FileText className="text-blue-500" size={20} />
        </div>
      );
    if (
      lowerFileName.endsWith('.hwp') ||
      lowerFileName.endsWith('.hwpx') ||
      lowerFileName.endsWith('.doc') ||
      lowerFileName.endsWith('.docx')
    )
      return (
        <div className="bg-indigo-100 rounded-md p-1 items-center">
          <FileText className="text-indigo-600" size={20} />
        </div>
      );
    if (
      lowerFileName.endsWith('.xls') ||
      lowerFileName.endsWith('.xlsx') ||
      lowerFileName.endsWith('.csv')
    )
      return (
        <div className="bg-emerald-100 rounded-md p-1 items-center">
          <FileSpreadsheet className="text-emerald-600" size={20} />
        </div>
      );
    if (
      lowerFileName.endsWith('.ppt') ||
      lowerFileName.endsWith('.pptx')
    )
      return (
        <div className="bg-amber-100 rounded-md p-1 items-center">
          <Presentation className="text-amber-600" size={20} />
        </div>
      );
    if (
      lowerFileName.endsWith('.jpg') ||
      lowerFileName.endsWith('.png') ||
      lowerFileName.endsWith('.jpeg') ||
      lowerFileName.endsWith('.gif')
    )
      return (
        <div className="bg-green-100 rounded-md p-1 items-center">
          <ImageIcon className="text-green-500" size={20} />
        </div>
      );
    // 음성 파일
    if (
      lowerFileName.endsWith('.mp3') ||
      lowerFileName.endsWith('.wav') ||
      lowerFileName.endsWith('.ogg') ||
      lowerFileName.endsWith('.flac')
    )
      return (
        <div className="bg-orange-100 rounded-md p-1 items-center">
          <Music className="text-orange-500" size={20} />
        </div>
      );
    // 영상 파일
    if (
      lowerFileName.endsWith('.mp4') ||
      lowerFileName.endsWith('.mov') ||
      lowerFileName.endsWith('.avi') ||
      lowerFileName.endsWith('.wmv') ||
      lowerFileName.endsWith('.webm')
    )
      return (
        <div className="bg-pink-100 rounded-md p-1 items-center">
          <Video className="text-pink-500" size={20} />
        </div>
      );
    if (
      lowerFileName.endsWith('.js') ||
      lowerFileName.endsWith('.py') ||
      lowerFileName.endsWith('.java') ||
      lowerFileName.endsWith('.html') ||
      lowerFileName.endsWith('.css')
    )
      return (
        <div className="bg-purple-100 rounded-md p-1 items-center">
          <Code className="text-purple-500" size={20} />
        </div>
      );
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

  // 요약 생성 핸들러
  const handleGenerateSummary = async () => {
    if (checkedFilenames.length === 0) {
      setIsSelectFileModalOpen(true);
      return;
    }

    setIsSummaryLoading(true);
    setSummaryError(null);

    try {
      await api.summarize({
        filenames: checkedFilenames,
      });
      queryClient.invalidateQueries({ queryKey: ['summaries'] });
    } catch (error) {
      console.error('요약 요청 실패:', error);
      setSummaryError('서버 연결에 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.'); // TODO: 이 에러도 AlertModal로 표시
    } finally {
      setIsSummaryLoading(false);
    }
  };

  // 마인드맵 생성 핸들러
  const handleGenerateMindmap = async () => {
    if (checkedFilenames.length === 0) {
      setIsSelectFileForMindmapModalOpen(true);
      return;
    }

    if (checkedFilenames.length > 1) {
      setMindmapErrorMessage('마인드맵은 한 번에 하나의 파일만 생성할 수 있습니다.');
      setIsMindmapErrorModalOpen(true);
      return;
    }

    setIsMindmapLoading(true);

    try {
      const response = await api.generateMindmap({
        filename: checkedFilenames[0],
        max_topics: 8,
      });
      
      if (response.data?.task_id) {
        setIsMindmapSuccessModalOpen(true);
        // RightBox의 마인드맵 탭으로 전환하도록 이벤트 발생 (선택사항)
      }
    } catch (error) {
      console.error('마인드맵 생성 실패:', error);
      setMindmapErrorMessage('마인드맵 생성 중 오류가 발생했습니다.');
      setIsMindmapErrorModalOpen(true);
    } finally {
      setIsMindmapLoading(false);
    }
  };

  // 보고서 생성 핸들러
  const handleGenerateReport = async () => {
    setIsReportModalOpen(true);
  };

  // 보고서 생성 실행
  const handleReportGenerate = async (file: File, templateType: string) => {
    setIsReportLoading(true);
    try {
      // TODO: 보고서 생성 API 구현
      console.log('보고서 생성:', file.name, templateType);
      // await api.generateReport({ file, templateType });
      alert(`${templateType} 양식으로 보고서 생성이 시작되었습니다.`);
    } catch (error) {
      console.error('보고서 생성 실패:', error);
      alert('보고서 생성 중 오류가 발생했습니다.');
    } finally {
      setIsReportLoading(false);
    }
  };

  return (
    <div
      id="leftbox"
      className="w-full h-full border border-gray-200 rounded-2xl overflow-hidden flex flex-col"
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
            <div className="flex flex-col gap-2 p-2 border-b border-gray-200 bg-gray-50/50">
              <div className="flex gap-2 w-full">
                <button
                  onClick={handleOpenFileUploadModal}
                  disabled={isUploading}
                  className="flex items-center justify-center gap-1.5 px-2 py-2 text-sm rounded-md bg-white border border-gray-300 hover:bg-gray-100 disabled:opacity-50 flex-1 h-[36px]"
                >
                  {isUploading ? (
                    <div className="animate-spin h-4 w-4 border-2 border-blue-500 rounded-full border-t-transparent"></div>
                  ) : (
                    <Plus size={16} />
                  )}
                  <span className="text-xs">추가</span>
                </button>
                <button
                  onClick={handleOpenModal}
                  className="flex items-center justify-center gap-1.5 px-2 py-2 text-sm rounded-md bg-white border border-gray-300 hover:bg-gray-100 flex-1 h-[36px]"
                >
                  <Search size={16} />
                  <span className="text-xs">탐색</span>
                </button>
              </div>
              {/* 요약/마인드맵/보고서 버튼 */}
              <div className="flex gap-2 w-full">
                <button
                  onClick={handleGenerateSummary}
                  disabled={isSummaryLoading}
                  className="flex items-center justify-center gap-1.5 px-2 py-2 text-sm rounded-md bg-blue-50 border border-blue-500 text-blue-500 hover:bg-blue-100 disabled:opacity-50 flex-1"
                >
                  {isSummaryLoading ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      <span className="text-xs">생성중...</span>
                    </>
                  ) : (
                    <>
                      <WandSparkles size={16} />
                      <span className="text-xs">요약</span>
                    </>
                  )}
                </button>
                <button
                  onClick={handleGenerateMindmap}
                  disabled={isMindmapLoading}
                  className="flex items-center justify-center gap-1.5 px-2 py-2 text-sm rounded-md bg-purple-50 border border-purple-500 text-purple-500 hover:bg-purple-100 disabled:opacity-50 flex-1"
                >
                  {isMindmapLoading ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      <span className="text-xs">생성중...</span>
                    </>
                  ) : (
                    <>
                      <Network size={16} />
                      <span className="text-xs">마인드맵</span>
                    </>
                  )}
                </button>
                <button
                  onClick={handleGenerateReport}
                  disabled={isReportLoading}
                  className="flex items-center justify-center gap-1.5 px-2 py-2 text-sm rounded-md bg-green-50 border border-green-500 text-green-500 hover:bg-green-100 disabled:opacity-50 flex-1"
                >
                  {isReportLoading ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      <span className="text-xs">생성중...</span>
                    </>
                  ) : (
                    <>
                      <FileBarChart size={16} />
                      <span className="text-xs">보고서</span>
                    </>
                  )}
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
              className="p-1 bg-gray-100 rounded-md hover:bg-gray-200 w-8 h-8 flex items-center justify-center"
            >
              <Plus size={18} />
            </button>
            <button
              onClick={handleOpenModal}
              title="파일 탐색"
              className="p-1 bg-gray-100 rounded-md hover:bg-gray-200 w-8 h-8 flex items-center justify-center"
            >
              <Search size={18} />
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
                  className={`flex items-center justify-center bg-gray-100 rounded-md p-1 w-8 h-8 transition-all hover:bg-gray-200 ${
                    selectedSource?.id === source.id ? 'bg-blue-50 ring-2 ring-blue-500' : ''
                  }`}
                >
                  <div className="flex items-center justify-center w-full h-full">
                    {getFileIcon(source.title)}
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex-grow flex flex-col overflow-hidden relative">
            {selectedSource ? (
              <div className="absolute inset-0 flex flex-col bg-white z-10">
                <div className="flex items-center p-2 border-b border-gray-200 flex-shrink-0 bg-white">
                  <button onClick={handleBackToList} className="p-1 rounded-md hover:bg-gray-100">
                    <ArrowLeft size={18} />
                  </button>
                  <h3 className="ml-2 text-base font-bold flex-grow truncate">
                    {formatFileName(selectedSource.title)}
                  </h3>
                  <button
                    onClick={() => setIsFileContentModalOpen(true)}
                    title="모달로 보기"
                    className="p-1 rounded-md hover:bg-gray-100"
                  >
                    <ExternalLink size={18} />
                  </button>
                </div>
                <div className="flex-grow overflow-y-auto no-scrollbar p-4 min-h-0 bg-white">
                  {isLoading ? (
                    <div className="flex justify-center items-center h-full">
                      <div className="animate-spin h-8 w-8 border-4 border-blue-500 rounded-full border-t-transparent"></div>
                    </div>
                  ) : (
                    <FileContentBox content={fileContent} forceMarkdown />
                  )}
                </div>
              </div>
            ) : (
              <div className="h-full flex flex-col">
                <div className="flex-shrink-0 flex justify-between items-center p-2 border-b border-gray-200 bg-gray-50/50">
                  <div className="flex items-center gap-2 px-1">
                    <label className="relative flex items-center justify-center h-5 w-5 cursor-pointer">
                      <input
                        type="checkbox"
                        onChange={handleSelectAll}
                        checked={sources.length > 0 && checked.length === sources.length}
                        className="sr-only"
                      />
                      {sources.length > 0 && checked.length === sources.length ? (
                        <CircleCheck className="h-5 w-5 text-blue-500" />
                      ) : (
                        <Circle className="h-5 w-5 text-gray-400" />
                      )}
                    </label>
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
                        className="px-1 py-2 mb-2 flex items-center justify-between hover:bg-gray-50 cursor-pointer gap-2"
                      >
                        <label className="relative flex items-center justify-center h-5 w-5 cursor-pointer" onClick={e => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            onChange={handleToggle(index)}
                            checked={checked.indexOf(index) !== -1}
                            className="sr-only"
                          />
                          {checked.indexOf(index) !== -1 ? (
                            <CircleCheck className="h-5 w-5 text-blue-500" />
                          ) : (
                            <Circle className="h-5 w-5 text-gray-400" />
                          )}
                        </label>
                        <div className="flex items-center flex-grow min-w-0">
                          <div className="min-w-[40px] flex items-center justify-center">
                            {getFileIcon(source.title)}
                          </div>
                          <div className="truncate">
                            <span className="text-sm">{formatFileName(source.title)}</span>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

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

      {/* 삭제 확인 모달 */}
      <AlertModal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        onConfirm={confirmDelete}
        title="정말 삭제하시겠습니까?"
        content={`선택한 ${checkedFilenames.length}개의 파일을 삭제합니다. 이 작업은 되돌릴 수 없습니다.`}
        iconType="warning"
        confirmButtonText="삭제"
        cancelButtonText="취소"
      />

      {/* 삭제 성공 모달 */}
      <AlertModal
        isOpen={isDeleteSuccessModalOpen}
        onClose={() => setIsDeleteSuccessModalOpen(false)}
        title="삭제 완료"
        content="파일이 성공적으로 삭제되었습니다."
        iconType="success"
        confirmButtonText={null}
        cancelButtonText={null}
      />

      {/* 삭제 실패 모달 */}
      <AlertModal
        isOpen={isDeleteFailModalOpen}
        onClose={() => setIsDeleteFailModalOpen(false)}
        title="삭제 실패"
        content={deleteErrorMessage}
        iconType="error"
        confirmButtonText={null}
        cancelButtonText={null}
      />

      {/* 파일 선택 요청 모달 */}
      <AlertModal
        isOpen={isSelectFileModalOpen}
        onClose={() => setIsSelectFileModalOpen(false)}
        title="알림"
        content="요약할 파일을 선택해주세요."
        iconType="warning"
        confirmButtonText={null}
        cancelButtonText={null}
      />

      {/* 요약 불가 경고 모달 */}
      <AlertModal
        isOpen={isNotSupportSummaryModalOpen}
        onClose={() => setIsNotSupportSummaryModalOpen(false)}
        title="알림"
        content="해당 파일은 요약 기능을 지원하지 않습니다."
        iconType="warning"
        confirmButtonText={null}
        cancelButtonText={null}
      />

      {/* 마인드맵 파일 선택 요청 모달 */}
      <AlertModal
        isOpen={isSelectFileForMindmapModalOpen}
        onClose={() => setIsSelectFileForMindmapModalOpen(false)}
        title="알림"
        content="마인드맵을 생성할 파일을 선택해주세요."
        iconType="warning"
        confirmButtonText={null}
        cancelButtonText={null}
      />

      {/* 마인드맵 생성 성공 모달 */}
      <AlertModal
        isOpen={isMindmapSuccessModalOpen}
        onClose={() => setIsMindmapSuccessModalOpen(false)}
        title="마인드맵 생성 시작"
        content="마인드맵 생성이 시작되었습니다. 우측 마인드맵 탭에서 확인하세요."
        iconType="success"
        confirmButtonText={null}
        cancelButtonText={null}
      />

      {/* 마인드맵 생성 실패 모달 */}
      <AlertModal
        isOpen={isMindmapErrorModalOpen}
        onClose={() => setIsMindmapErrorModalOpen(false)}
        title="마인드맵 생성 실패"
        content={mindmapErrorMessage}
        iconType="error"
        confirmButtonText={null}
        cancelButtonText={null}
      />

      {/* 보고서 생성 모달 */}
      <ReportModal
        isOpen={isReportModalOpen}
        onClose={() => setIsReportModalOpen(false)}
        onGenerate={handleReportGenerate}
      />

      {/* 파일 내용 모달 */}
      <FileContentModal
        isOpen={isFileContentModalOpen}
        onClose={() => setIsFileContentModalOpen(false)}
        fileName={selectedSource?.title || ''}
        content={fileContent}
      />
    </div>
  );
});

export default LeftBox;
