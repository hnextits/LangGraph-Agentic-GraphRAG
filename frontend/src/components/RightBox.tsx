import React, { useState, useEffect } from 'react';
import { useGetSummaries } from '@/queries';
import api from '@/lib/api';
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Loader2,
  FileText,
  AlertCircle,
  Trash2,
  File,
  Image as ImageIcon,
  Code,
  FileType,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import SummaryModal from './SummaryModal';
import Swal from 'sweetalert2';

interface RightBoxProps {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  selectedFiles?: string[];
}

const RightBox: React.FC<RightBoxProps> = ({
  collapsed = false,
  onToggleCollapse = () => {},
  selectedFiles = [],
}) => {
  const queryClient = useQueryClient();

  const {
    data: summarizedFiles = [],
    isLoading: isSummariesLoading,
    isError: isSummariesError,
  } = useGetSummarizes();

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // 모달 관련 상태
  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [modalFile, setModalFile] = useState<string>('');

  const [checkedSummarizes, setCheckedSummarizes] = useState<string[]>([]);

  // 요약 생성 핸들러
  const handleGenerateSummary = async () => {
    if (selectedFiles.length === 0) {
      setError('요약할 파일을 선택해주세요.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await api.summarize({
        filenames: selectedFiles,
      });
      queryClient.invalidateQueries({ queryKey: ['summarizes'] });
    } catch (error) {
      console.error('요약 요청 실패:', error);
      setError('서버 연결에 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenModal = (filename: string) => {
    setSummaryModalOpen(true);
    setModalFile(filename);
  };

  const handleCloseModal = () => {
    setSummaryModalOpen(false);
    setModalFile('');
  };

  const handleSelectAll = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.checked) {
      setCheckedSummarizes([...summarizedFiles]);
    } else {
      setCheckedSummarizes([]);
    }
  };

  const handleToggle = (file: string) => () => {
    const currentIndex = checkedSummarizes.indexOf(file);
    const newChecked = [...checkedSummarizes];

    if (currentIndex === -1) {
      newChecked.push(file);
    } else {
      newChecked.splice(currentIndex, 1);
    }

    setCheckedSummarizes(newChecked);
  };

  const handleDelete = async () => {
    if (checkedSummarizes.length === 0) return;

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
        const response = await api.deleteSummary(checkedSummarizes);
        if (response.data?.deleted_files && response.data.deleted_files.length > 0) {
          setCheckedSummarizes([]);
          Swal.fire('삭제 완료!', '요약이 삭제되었습니다.', 'success');
          queryClient.invalidateQueries({ queryKey: ['summarizes'] });
        } else {
          const errorMessage =
            response.data?.failed_files?.length > 0
              ? `요약 삭제 실패: ${response.data.failed_files
                  .map((f: { filename: string; reason: string }) => f.filename)
                  .join(', ')}`
              : '요약 삭제에 실패했습니다.';
          Swal.fire('삭제 실패!', errorMessage, 'error');
        }
      } catch (error) {
        console.error('요약 삭제 실패:', error);
        Swal.fire('오류 발생!', '요약 삭제 중 오류가 발생했습니다.', 'error');
      }
    }
  };

  useEffect(() => {
    setError(null);
  }, [selectedFiles]);

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
  const getFileIcon = (fileName: string, size: number = 20) => {
    const lowerFileName = fileName.toLowerCase();

    if (lowerFileName.endsWith('.pdf') || lowerFileName.endsWith('_pdf')) {
      return <FileType className="text-red-500" size={size} />;
    } else if (lowerFileName.endsWith('.md')) {
      return <FileText className="text-blue-500" size={size} />;
    } else if (
      lowerFileName.endsWith('.jpg') ||
      lowerFileName.endsWith('.png') ||
      lowerFileName.endsWith('.jpeg') ||
      lowerFileName.endsWith('.gif')
    ) {
      return <ImageIcon className="text-green-500" size={size} />;
    } else if (
      lowerFileName.endsWith('.js') ||
      lowerFileName.endsWith('.py') ||
      lowerFileName.endsWith('.java') ||
      lowerFileName.endsWith('.html') ||
      lowerFileName.endsWith('.css')
    ) {
      return <Code className="text-purple-500" size={size} />;
    }

    return <File size={size} />;
  };

  return (
    <div
      className={`${
        collapsed ? 'w-12' : 'w-[95%]'
      } h-full border border-gray-200 rounded-2xl overflow-hidden flex flex-col`}
    >
      <div className="w-full h-full flex flex-col bg-white overflow-hidden">
        {/* Header */}
        <div
          className={`flex items-center ${
            collapsed ? 'px-1 py-2 justify-center' : 'px-4 py-2 justify-between'
          } border-b border-gray-200 flex-shrink-0 min-h-[52px]`}
        >
          {!collapsed && <h2 className="text-lg font-bold">요약</h2>}
          <button onClick={onToggleCollapse} className="p-1 rounded-md hover:bg-gray-100">
            {collapsed ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
          </button>
        </div>

        {/* Content */}
        {collapsed ? (
          <div className="flex flex-col items-center w-full h-full">
            {/* 요약 생성 버튼 (접힘) */}
            <div className="w-full p-2 flex justify-center">
              <button
                onClick={handleGenerateSummary}
                disabled={isLoading || selectedFiles.length === 0}
                title="요약 생성하기"
                className={`relative bg-gray-100 rounded-lg p-1.5 w-8 h-8 flex items-center justify-center transition-all hover:bg-gray-200 hover:scale-105 ${
                  selectedFiles.length > 0 && !isLoading
                    ? 'bg-blue-50 ring-2 ring-blue-500'
                    : 'disabled:opacity-50 disabled:cursor-not-allowed'
                }`}
              >
                {isLoading ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <RefreshCw size={16} />
                )}
              </button>
            </div>

            {/* 구분선 */}
            <hr className="w-full border-t border-gray-200" />

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
                    {getFileIcon(file, 16)}
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
            {/* --- Action Toolbar --- */}
            <div className="flex items-center justify-between p-2 border-b border-gray-200 bg-gray-50/50">
              <button
                onClick={handleGenerateSummary}
                disabled={isLoading || selectedFiles.length === 0}
                className="flex items-center gap-1.5 px-2.5 py-1 text-sm rounded-md bg-white border border-gray-300 hover:bg-gray-100 disabled:opacity-50 w-full justify-center"
              >
                {isLoading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    <span>요약 생성 중...</span>
                  </>
                ) : (
                  <>
                    <RefreshCw size={16} />
                    <span>요약 생성하기</span>
                  </>
                )}
              </button>
            </div>
            <div className="p-2 border-b border-gray-200 text-xs text-gray-500">
              {selectedFiles.length > 0 ? (
                <span>선택된 파일: {selectedFiles.length}개</span>
              ) : (
                <span className="text-red-500">요약할 파일을 선택해주세요.</span>
              )}
            </div>

            {/* 에러 메시지 */}
            {error && (
              <div className="m-2 p-3 bg-red-50 border border-red-200 rounded-md flex items-start flex-shrink-0">
                <AlertCircle size={16} className="text-red-500 mr-2 mt-0.5" />
                <p className="text-red-600 text-sm">{error}</p>
              </div>
            )}

            <div className="h-full flex flex-col flex-grow overflow-hidden">
              <div className="flex-shrink-0 flex justify-between items-center p-2 border-b border-gray-200 bg-gray-50/50">
                <div className="flex items-center">
                  <input
                    type="checkbox"
                    onChange={handleSelectAll}
                    checked={
                      summarizedFiles.length > 0 &&
                      checkedSummarizes.length === summarizedFiles.length
                    }
                    className="mr-2 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm font-medium text-gray-700">전체 선택</span>
                </div>
                <button
                  onClick={handleDelete}
                  disabled={checkedSummarizes.length === 0}
                  className={`p-1 rounded-md disabled:text-gray-300 disabled:cursor-not-allowed text-gray-600 hover:bg-gray-200`}
                >
                  <Trash2 size={18} />
                </button>
              </div>

              <div className="flex-grow overflow-y-auto no-scrollbar p-2">
                {isSummariesLoading ? (
                  <div className="flex flex-col items-center justify-center h-[200px] text-gray-400">
                    <Loader2 size={32} className="mb-2 animate-spin" />
                    <p>요약 목록을 불러오는 중...</p>
                  </div>
                ) : isSummariesError ? (
                  <div className="flex flex-col items-center justify-center h-[200px] text-red-400">
                    <AlertCircle size={32} className="mb-2" />
                    <p>목록을 불러오는데 실패했습니다.</p>
                  </div>
                ) : summarizedFiles.length > 0 ? (
                  <ul className="space-y-2">
                    {summarizedFiles.map((file, index) => {
                      const isChecked = checkedSummarizes.includes(file);
                      return (
                        <li
                          key={index}
                          onClick={() => handleOpenModal(file)}
                          className="p-1 mb-2 rounded border border-gray-200 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
                        >
                          <div className="flex items-center flex-grow min-w-0">
                            <div className="min-w-[40px] flex items-center justify-center">
                              {getFileIcon(file)}
                            </div>
                            <div className="ml-2 truncate">
                              <span className="text-sm">{formatFileName(file)}</span>
                            </div>
                          </div>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onClick={e => e.stopPropagation()}
                            onChange={handleToggle(file)}
                            className="mr-1 h-4 w-4"
                          />
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <div className="flex flex-col items-center justify-center h-[200px] text-gray-400">
                    <FileText size={48} className="mb-2" />
                    <p className="text-center px-4">
                      파일을 선택하고 '요약 생성하기' 버튼을 클릭하여 문서 요약을 확인해보세요.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <SummaryModal open={summaryModalOpen} onClose={handleCloseModal} file={modalFile} />
    </div>
  );
};

export default RightBox;
