import React, { useState, useEffect } from 'react';
import { useGetSummaries } from '@/queries';
import api from '@/lib/api';
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  FileText,
  AlertCircle,
  Trash2,
  File,
  Image as ImageIcon,
  Code,
  FileType,
  Circle,
  CircleCheck,
  Brain,
  RefreshCw,
  Network,
  FileBarChart,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import SummaryModal from './SummaryModal';
import MindmapModal from './MindmapModal';
import Swal from 'sweetalert2';

interface RightBoxProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  selectedFiles?: string[];
}

const RightBox: React.FC<RightBoxProps> = React.memo(({
  collapsed = false,
  onToggleCollapse = () => {},
  selectedFiles = [],
}) => {
  const queryClient = useQueryClient();

  const {
    data: summarizedFiles = [],
    isLoading: isSummariesLoading,
    isError: isSummariesError,
  } = useGetSummaries();

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // 탭 상태
  const [activeTab, setActiveTab] = useState<'summary' | 'mindmap' | 'report'>('summary');
  const [isRefreshing, setIsRefreshing] = useState(false);

  // 모달 관련 상태
  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [mindmapModalOpen, setMindmapModalOpen] = useState(false);
  const [modalFile, setModalFile] = useState<string>('');

  const [checkedSummarizes, setCheckedSummarizes] = useState<string[]>([]);
  const [checkedMindmaps, setCheckedMindmaps] = useState<string[]>([]);
  const [checkedReports, setCheckedReports] = useState<string[]>([]);

  // 마인드맵 목록
  const [mindmaps, setMindmaps] = useState<string[]>([]);
  const [isMindmapsLoading, setIsMindmapsLoading] = useState(false);

  const handleOpenModal = (filename: string) => {
    setSummaryModalOpen(true);
    setModalFile(filename);
  };

  const handleCloseModal = () => {
    setSummaryModalOpen(false);
    setModalFile('');
  };

  const handleOpenMindmapModal = (filename: string) => {
    setMindmapModalOpen(true);
    setModalFile(filename);
  };

  const handleCloseMindmapModal = () => {
    setMindmapModalOpen(false);
    setModalFile('');
  };

  const handleSelectAll = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (activeTab === 'summary') {
      if (e.target.checked) {
        setCheckedSummarizes([...summarizedFiles]);
      } else {
        setCheckedSummarizes([]);
      }
    } else if (activeTab === 'mindmap') {
      if (e.target.checked) {
        setCheckedMindmaps([...mindmaps]);
      } else {
        setCheckedMindmaps([]);
      }
    } else if (activeTab === 'report') {
      if (e.target.checked) {
        setCheckedReports([]);
      } else {
        setCheckedReports([]);
      }
    }
  };

  const handleToggle = (file: string) => () => {
    if (activeTab === 'summary') {
      const currentIndex = checkedSummarizes.indexOf(file);
      const newChecked = [...checkedSummarizes];
      if (currentIndex === -1) {
        newChecked.push(file);
      } else {
        newChecked.splice(currentIndex, 1);
      }
      setCheckedSummarizes(newChecked);
    } else if (activeTab === 'mindmap') {
      const currentIndex = checkedMindmaps.indexOf(file);
      const newChecked = [...checkedMindmaps];
      if (currentIndex === -1) {
        newChecked.push(file);
      } else {
        newChecked.splice(currentIndex, 1);
      }
      setCheckedMindmaps(newChecked);
    }
  };

  const handleDelete = async () => {
    let itemsToDelete: string[] = [];
    let itemType = '';

    if (activeTab === 'summary') {
      if (checkedSummarizes.length === 0) return;
      itemsToDelete = checkedSummarizes;
      itemType = '요약';
    } else if (activeTab === 'mindmap') {
      if (checkedMindmaps.length === 0) return;
      itemsToDelete = checkedMindmaps;
      itemType = '마인드맵';
    } else {
      return;
    }

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
        if (activeTab === 'summary') {
          const response = await api.deleteSummary(itemsToDelete);
          if (response.data?.deleted_files && response.data.deleted_files.length > 0) {
            setCheckedSummarizes([]);
            Swal.fire('삭제 완료!', `${itemType}이 삭제되었습니다.`, 'success');
            queryClient.invalidateQueries({ queryKey: ['summaries'] });
          } else {
            const errorMessage =
              response.data?.failed_files?.length > 0
                ? `${itemType} 삭제 실패: ${response.data.failed_files
                    .map((f: { filename: string; reason: string }) => f.filename)
                    .join(', ')}`
                : `${itemType} 삭제에 실패했습니다.`;
            Swal.fire('삭제 실패!', errorMessage, 'error');
          }
        } else if (activeTab === 'mindmap') {
          // 마인드맵 삭제는 개별 API 호출
          for (const filename of itemsToDelete) {
            await api.deleteMindmap(filename);
          }
          setCheckedMindmaps([]);
          Swal.fire('삭제 완료!', `${itemType}이 삭제되었습니다.`, 'success');
          await loadMindmaps();
        }
      } catch (error) {
        console.error(`${itemType} 삭제 실패:`, error);
        Swal.fire('오류 발생!', `${itemType} 삭제 중 오류가 발생했습니다.`, 'error');
      }
    }
  };

  useEffect(() => {
    setError(null);
  }, [selectedFiles]);

  // 새로고침 핸들러
  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      if (activeTab === 'summary') {
        await queryClient.invalidateQueries({ queryKey: ['summaries'] });
      } else if (activeTab === 'mindmap') {
        await loadMindmaps();
      }
    } finally {
      setTimeout(() => setIsRefreshing(false), 500);
    }
  };

  // 마인드맵 목록 로드
  const loadMindmaps = async () => {
    setIsMindmapsLoading(true);
    try {
      const response = await api.getMindmaps();
      setMindmaps(response.data.mindmaps || []);
    } catch (error) {
      console.error('마인드맵 목록 로드 실패:', error);
    } finally {
      setIsMindmapsLoading(false);
    }
  };

  // 마인드맵 탭 활성화 시 목록 로드
  useEffect(() => {
    if (activeTab === 'mindmap') {
      loadMindmaps();
    }
  }, [activeTab]);

  const formatFileName = (fileName: string) => {
    // 'summary_' 접두사 제거
    let name = fileName.startsWith('summary_') ? fileName.substring(8) : fileName;
    // 파일 이름 끝에 .md가 반복되는 경우 모두 제거
    while (name.endsWith('.md')) {
      name = name.slice(0, -3);
    }
    return name;
  };

  // 파일 확장자에 따른 아이콘 선택 함수
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

  return (
    <div
      className="w-full h-full border border-gray-200 rounded-2xl overflow-hidden flex flex-col"
    >
      <div className="w-full h-full flex flex-col bg-white overflow-hidden">
        {/* Header */}
        <div
          className={`flex items-center ${
            collapsed ? 'justify-center px-1 py-2' : 'justify-between px-4 py-2'
          } border-b border-gray-200 flex-shrink-0 min-h-[52px]`}
        >
          {!collapsed && <h2 className="text-lg font-bold">결과</h2>}
          <button onClick={onToggleCollapse} className="p-1 rounded-md hover:bg-gray-100">
            {collapsed ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
          </button>
        </div>

        {/* Tabs */}
        {!collapsed && (
          <div className="flex items-center justify-between px-2 py-2 border-b border-gray-200 bg-gray-50/50">
            <div className="flex gap-1">
              <button
                onClick={() => setActiveTab('summary')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                  activeTab === 'summary'
                    ? 'bg-blue-100 text-blue-700 font-semibold'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                <FileText size={16} />
                요약
              </button>
              <button
                onClick={() => setActiveTab('mindmap')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                  activeTab === 'mindmap'
                    ? 'bg-purple-100 text-purple-700 font-semibold'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                <Network size={16} />
                마인드맵
              </button>
              <button
                onClick={() => setActiveTab('report')}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                  activeTab === 'report'
                    ? 'bg-green-100 text-green-700 font-semibold'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                <FileBarChart size={16} />
                보고서
              </button>
            </div>
          </div>
        )}

        {/* Content */}
        {collapsed ? (
          <div className="flex flex-col items-center w-full h-full">
            {/* 파일 목록 (접힘) */}
            <div className="flex-grow w-full flex flex-col items-center gap-2 py-2 overflow-y-auto no-scrollbar">
              {summarizedFiles.length > 0 ? (
                summarizedFiles.map((file, index) => (
                  <button
                    key={index}
                    onClick={() => handleOpenModal(file)}
                    title={formatFileName(file)}
                    className="p-1.5 bg-gray-100 rounded-lg hover:bg-gray-200 w-8 h-8 flex items-center justify-center mb-1 flex-shrink-0"
                  >
                    {getFileIcon(file)}
                  </button>
                ))
              ) : (
                <div className="p-2 text-gray-400">
                  <FileText size={20} />
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex-grow flex flex-col overflow-hidden">
            {/* 탭 컨텐츠 */}
            <>
              {/* 에러 메시지 */}
              {error && (
                <div className="m-2 p-3 bg-red-50 border border-red-200 rounded-md flex items-start flex-shrink-0">
                  <AlertCircle size={16} className="text-red-500 mr-2 mt-0.5" />
                  <p className="text-red-600 text-sm">{error}</p>
                </div>
              )}

              <div className="h-full flex flex-col flex-grow overflow-hidden">
              <div className="flex-shrink-0 flex justify-between items-center p-2 border-b border-gray-200 bg-gray-50/50">
                <div className="flex items-center gap-2 px-1">
                  <label className="relative flex items-center justify-center h-5 w-5 cursor-pointer">
                    <input
                      type="checkbox"
                      onChange={handleSelectAll}
                      checked={
                        activeTab === 'summary'
                          ? summarizedFiles.length > 0 && checkedSummarizes.length === summarizedFiles.length
                          : activeTab === 'mindmap'
                          ? mindmaps.length > 0 && checkedMindmaps.length === mindmaps.length
                          : false
                      }
                      className="sr-only"
                    />
                    {((activeTab === 'summary' && summarizedFiles.length > 0 && checkedSummarizes.length === summarizedFiles.length) ||
                      (activeTab === 'mindmap' && mindmaps.length > 0 && checkedMindmaps.length === mindmaps.length)) ? (
                      <CircleCheck className="h-5 w-5 text-blue-500" />
                    ) : (
                      <Circle className="h-5 w-5 text-gray-400" />
                    )}
                  </label>
                  <span className="text-sm font-medium text-gray-700">전체 선택</span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={handleRefresh}
                    disabled={isRefreshing}
                    className="p-1 rounded-md text-gray-600 hover:bg-gray-200 disabled:opacity-50"
                    title="새로고침"
                  >
                    <RefreshCw size={18} className={isRefreshing ? 'animate-spin' : ''} />
                  </button>
                  <button
                    onClick={handleDelete}
                    disabled={
                      activeTab === 'summary'
                        ? checkedSummarizes.length === 0
                        : activeTab === 'mindmap'
                        ? checkedMindmaps.length === 0
                        : true
                    }
                    className={`p-1 rounded-md disabled:text-gray-300 disabled:cursor-not-allowed text-gray-600 hover:bg-gray-200`}
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
              </div>

              <div className="flex-grow overflow-y-auto no-scrollbar p-2 relative">
                {activeTab === 'summary' && isSummariesLoading ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
                    <Loader2 size={48} className="mb-4 animate-spin" />
                    <p className="text-lg font-medium">요약 목록을 불러오는 중...</p>
                  </div>
                ) : activeTab === 'summary' && isSummariesError ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-red-400">
                    <AlertCircle size={48} className="mb-4" />
                    <p className="text-lg font-medium">목록을 불러오는데 실패했습니다.</p>
                  </div>
                ) : activeTab === 'summary' && summarizedFiles.length > 0 ? (
                  <ul className="space-y-2">
                    {summarizedFiles.map((file, index) => {
                      const isChecked = checkedSummarizes.includes(file);
                      return (
                        <li
                          key={index}
                          onClick={() => handleOpenModal(file)}
                          className="px-1 py-2 mb-2 flex items-center justify-between hover:bg-gray-50 cursor-pointer gap-2"
                        >
                          <label className="relative flex items-center justify-center h-5 w-5 cursor-pointer" onClick={e => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={handleToggle(file)}
                              className="sr-only"
                            />
                            {isChecked ? (
                              <CircleCheck className="h-5 w-5 text-blue-500" />
                            ) : (
                              <Circle className="h-5 w-5 text-gray-400" />
                            )}
                          </label>
                          <div className="flex items-center flex-grow min-w-0">
                            <div className="min-w-[40px] flex items-center justify-center">
                              {getFileIcon(file)}
                            </div>
                            <div className="ml-2 truncate">
                              <span className="text-sm">{formatFileName(file)}</span>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                ) : activeTab === 'mindmap' && isMindmapsLoading ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
                    <Loader2 size={48} className="mb-4 animate-spin" />
                    <p className="text-lg font-medium">마인드맵 목록을 불러오는 중...</p>
                  </div>
                ) : activeTab === 'mindmap' && mindmaps.length > 0 ? (
                  <ul className="space-y-2">
                    {mindmaps.map((file, index) => {
                      const isChecked = checkedMindmaps.includes(file);
                      return (
                        <li
                          key={index}
                          onClick={() => handleOpenMindmapModal(file)}
                          className="px-1 py-2 mb-2 flex items-center hover:bg-gray-50 cursor-pointer gap-2"
                        >
                          <label className="relative flex items-center justify-center h-5 w-5 cursor-pointer" onClick={e => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={handleToggle(file)}
                              className="sr-only"
                            />
                            {isChecked ? (
                              <CircleCheck className="h-5 w-5 text-blue-500" />
                            ) : (
                              <Circle className="h-5 w-5 text-gray-400" />
                            )}
                          </label>
                          <div className="flex items-center flex-grow min-w-0">
                            <div className="min-w-[40px] flex items-center justify-center">
                              <div className="bg-purple-100 rounded-md p-1 items-center">
                                <Network className="text-purple-500" size={20} />
                              </div>
                            </div>
                            <div className="ml-2 truncate">
                              <span className="text-sm">{file}</span>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                ) : activeTab === 'report' ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
                    <FileBarChart size={64} className="mb-4" />
                    <p className="text-center px-6 text-lg font-medium leading-relaxed">
                      보고서 기능은 준비 중입니다.
                    </p>
                  </div>
                ) : (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
                    {activeTab === 'summary' ? (
                      <FileText size={64} className="mb-4 text-blue-400" />
                    ) : activeTab === 'mindmap' ? (
                      <Network size={64} className="mb-4 text-purple-400" />
                    ) : (
                      <FileBarChart size={64} className="mb-4 text-green-400" />
                    )}
                    <p className="text-center px-6 text-lg font-medium leading-relaxed max-w-md whitespace-pre-line">
                      {activeTab === 'summary'
                        ? "파일을 선택하고 '요약' 버튼을 클릭하여\n문서 요약을 확인해보세요."
                        : activeTab === 'mindmap'
                        ? "파일을 선택하고 '마인드맵' 버튼을 클릭하여\n마인드맵을 생성해보세요."
                        : '보고서 기능은 준비 중입니다.'}
                    </p>
                  </div>
                )}
              </div>
            </div>
            </>
          </div>
        )}
      </div>

      <SummaryModal open={summaryModalOpen} onClose={handleCloseModal} file={modalFile} />
      <MindmapModal open={mindmapModalOpen} onClose={handleCloseMindmapModal} file={modalFile} />
    </div>
  );
});

export default RightBox;
