'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { Loader2, X } from 'lucide-react';

// 타입 정의
interface SearchResult {
  title: string;
  link: string;
  snippet: string;
}

interface SearchBoxProps {
  open: boolean;
  onClose: () => void;
  onProcessingStart: (tasks: any[]) => void;
}

const SearchBox: React.FC<SearchBoxProps> = ({ open, onClose, onProcessingStart }) => {
  const queryClient = useQueryClient();

  // 상태 관리
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [checked, setChecked] = useState<number[]>([]);

  // 모달이 열릴 때마다 상태 초기화
  useEffect(() => {
    if (open) {
      setSearchTerm('');
      setResults([]);
      setChecked([]);
      setLoading(false);
    }
  }, [open]);

  // 검색 실행 핸들러
  const handleSearch = async () => {
    if (!searchTerm.trim()) {
      alert('검색어를 입력해주세요!');
      return;
    }

    setLoading(true);
    try {
      const response = await api.search({ query: searchTerm });
      const searchResults = response.data.results || [];
      setResults(searchResults);
      setChecked([]);
    } catch (error) {
      console.error('API 호출 중 오류 발생:', error);
      alert('검색 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  // 체크박스 토글 핸들러
  const handleToggle = (value: number) => () => {
    const currentIndex = checked.indexOf(value);
    const newChecked = [...checked];

    if (currentIndex === -1) {
      newChecked.push(value);
    } else {
      newChecked.splice(currentIndex, 1);
    }

    setChecked(newChecked);
  };

  // 전체 선택 핸들러
  const handleSelectAll = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked) {
      const newChecked = results.map((_, index) => index);
      setChecked(newChecked);
      return;
    }
    setChecked([]);
  };

  // 확인 버튼 핸들러
  const handleConfirm = async () => {
    if (checked.length === 0) {
      alert('추가할 문서를 선택해주세요.');
      return;
    }

    setLoading(true);
    const selectedDocs = checked.map(index => results[index]);

    try {
      const promises = selectedDocs.map(doc => api.uploadDocuments(doc.title, doc.link));

      const responses = await Promise.all(promises);
      const successfulTasks = responses
        .filter(res => res.data && res.data.task_id)
        .map(res => ({
          ...res.data,
          title:
            selectedDocs.find(d => d.link === res.data.link)?.title ||
            res.data.title ||
            'Unknown Title',
        }));

      if (successfulTasks.length > 0) {
        onProcessingStart(successfulTasks);
        queryClient.invalidateQueries({ queryKey: ['files'] });
        onClose();
      } else {
        throw new Error('모든 문서 처리 시작에 실패했습니다.');
      }
    } catch (error: any) {
      alert(`오류가 발생했습니다: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  if (!open) return null;

  // 모달 렌더링
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">출처 탐색</h2>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-gray-100">
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4 overflow-y-auto">
          {/* 검색어 입력 필드 */}
          <div className="flex gap-2">
            <input
              type="text"
              className="flex-grow border border-gray-300 rounded-md p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              autoFocus
              placeholder="검색어를 입력하세요."
              onKeyDown={e => {
                if (e.key === 'Enter') handleSearch();
              }}
            />
            <button
              onClick={handleSearch}
              disabled={loading}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
            >
              {loading && <Loader2 className="animate-spin" size={16} />}
              검색
            </button>
          </div>

          {/* 검색 결과 영역 */}
          {loading && (
            <div className="flex justify-center items-center gap-2 text-gray-500 text-sm">
              <Loader2 className="animate-spin" size={18} />
              <span>검색 중...</span>
            </div>
          )}

          {results.length > 0 && (
            <div className="space-y-3">
              <div className="flex justify-between items-center border-b pb-2">
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    onChange={handleSelectAll}
                    checked={checked.length === results.length}
                    ref={input => {
                      if (input)
                        input.indeterminate = checked.length > 0 && checked.length < results.length;
                    }}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="font-medium">전체 선택</span>
                </label>
                <button
                  onClick={handleConfirm}
                  disabled={checked.length === 0 || loading}
                  className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
                >
                  {loading && <Loader2 className="animate-spin" size={14} />}
                  확인 ({checked.length})
                </button>
              </div>

              <ul className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {results.map((result, index) => (
                  <li
                    key={index}
                    onClick={handleToggle(index)}
                    className="p-3 border rounded-md bg-white shadow-sm cursor-pointer hover:bg-gray-50 flex items-start gap-3"
                  >
                    <input
                      type="checkbox"
                      checked={checked.includes(index)}
                      onChange={handleToggle(index)}
                      onClick={e => e.stopPropagation()}
                      className="mt-1 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <div className="flex-grow min-w-0">
                      <a
                        href={result.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                        className="block font-medium text-blue-600 truncate hover:underline"
                      >
                        {result.title}
                      </a>
                      <p className="text-xs text-gray-600 mt-1 line-clamp-2">{result.snippet}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-4 border-t border-gray-200">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium border border-gray-300 rounded-md hover:bg-gray-50"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
};

export default SearchBox;
