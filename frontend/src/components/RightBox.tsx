import React, { useState, useEffect } from 'react';
import { useGetSummarizes } from '@/queries';
import api from '@/lib/api';
import {
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Loader2,
  FileText,
  AlertCircle,
  Trash2,
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

  const formatFileName = (file: string) => file.replace(/^summary_/, '').replace(/\.md$/, '');

  return (
    <div
      className={`${
        collapsed ? 'w-12' : 'w-[95%]'
      } h-full border border-gray-200 rounded-2xl overflow-hidden flex flex-col`}
    >
      <div className="w-full h-full flex flex-col bg-white overflow-hidden">
        {/* Header */}
        <div
          className={`flex justify-between items-center ${
            collapsed ? 'px-1 py-2' : 'px-4 py-2'
          } border-b border-gray-200 flex-shrink-0 min-h-[52px]`}
        >
          {!collapsed && <h2 className="text-lg font-bold">요약</h2>}
          <button onClick={onToggleCollapse} className="p-1 rounded-md hover:bg-gray-100">
            {collapsed ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
          </button>
        </div>

        {/* Content */}
        {collapsed ? (
          <div className="flex flex-col items-center gap-2 py-2">
            {summarizedFiles.length > 0 ? (
              summarizedFiles.map((file, index) => (
                <button
                  key={index}
                  onClick={() => {
                    handleOpenModal(file);
                  }}
                  title={file.replace('summary_', '')}
                  className="p-1.5 bg-gray-100 rounded-lg hover:bg-gray-200 w-8 h-8 flex items-center justify-center mb-1"
                >
                  <FileText size={16} />
                </button>
              ))
            ) : (
              <button
                onClick={() => {
                  onToggleCollapse();
                }}
                title="요약 보기"
                className="p-1.5 bg-gray-100 rounded-lg hover:bg-gray-200 w-8 h-8 flex items-center justify-center"
              >
                <FileText size={16} />
              </button>
            )}
          </div>
        ) : (
          <div className="flex-grow overflow-y-auto p-4">
            {/* 요약 생성 버튼 */}
            <div className="mb-4">
              <button
                onClick={handleGenerateSummary}
                disabled={isLoading || selectedFiles.length === 0}
                className={`flex items-center justify-center px-4 py-2 rounded-md w-full ${
                  isLoading || selectedFiles.length === 0
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

              <div className="mt-2 text-xs text-gray-500">
                {selectedFiles.length > 0 ? (
                  <span>선택된 파일: {selectedFiles.length}개</span>
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

            <div className="flex flex-col items-center justify-center h-[200px] text-gray-400">
              <FileText size={48} className="mb-2" />
              <p className="text-center">
                {isLoading
                  ? '요약을 생성하는 중입니다...'
                  : '파일을 선택하고 요약 생성하기 버튼을 클릭하세요.'}
              </p>
            </div>

            {/* 삭제 */}
            <div className="flex justify-between items-center px-2 mb-2 h-9">
              <div className="flex items-center">
                <input
                  type="checkbox"
                  onChange={handleSelectAll}
                  checked={
                    summarizedFiles.length > 0 &&
                    checkedSummarizes.length === summarizedFiles.length
                  }
                  className="mr-2 h-4 w-4"
                />
                <span className="text-sm">전체 선택</span>
              </div>
              <button
                onClick={handleDelete}
                disabled={checkedSummarizes.length === 0}
                className={`p-1 rounded-md ${
                  checkedSummarizes.length === 0
                    ? 'text-gray-300 cursor-not-allowed'
                    : 'hover:bg-gray-100 text-gray-700 cursor-pointer'
                }`}
              >
                <Trash2 size={18} />
              </button>
            </div>

            <div className="">
              {isSummariesLoading ? (
                <p className="text-sm text-gray-400">불러오는 중...</p>
              ) : isSummariesError ? (
                <p className="text-sm text-red-400">불러오기 실패</p>
              ) : summarizedFiles.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {summarizedFiles.map((file, index) => {
                    const isChecked = checkedSummarizes.includes(file);
                    return (
                      <div
                        key={index}
                        className="border rounded-md p-3 text-sm text-gray-700 shadow-sm bg-gray-50 hover:bg-gray-100 cursor-pointer flex justify-between items-center"
                        onClick={() => handleOpenModal(file)}
                      >
                        <span>{formatFileName(file)}</span>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onClick={e => e.stopPropagation()}
                          onChange={handleToggle(file)}
                          className="ml-4 h-4 w-4"
                        />
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-gray-400">요약된 파일이 없습니다.</p>
              )}
            </div>
          </div>
        )}
      </div>

      <SummaryModal open={summaryModalOpen} onClose={handleCloseModal} file={modalFile} />
    </div>
  );
};

export default RightBox;
