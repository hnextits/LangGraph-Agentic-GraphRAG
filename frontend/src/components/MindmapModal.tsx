'use client';

import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { X, Loader2, Network, Clock } from 'lucide-react';

interface MindmapModalProps {
  open: boolean;
  onClose: () => void;
  file: string;
}

export default function MindmapModal({ open, onClose, file }: MindmapModalProps) {
  const [content, setContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (open && file) {
      loadContent();
    }
  }, [open, file]);

  const loadContent = async () => {
    setIsLoading(true);
    try {
      const response = await api.getMindmapContent(file, 'html');
      setContent(response.data.content);
    } catch (error) {
      console.error('마인드맵 로드 실패:', error);
      setContent('<p style="text-align: center; padding: 40px; color: #999;">마인드맵을 불러올 수 없습니다.</p>');
    } finally {
      setIsLoading(false);
    }
  };

  // 파일명 포맷팅
  const formatFileName = (fileName: string) => {
    return fileName.replace(/_mindmap_interactive\.html$/, '').replace(/_/g, ' ');
  };

  // 현재 시간
  const currentTime = new Date().toLocaleString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[9999] p-4">
      <div className="bg-white rounded-xl w-full h-full max-w-[95vw] max-h-[95vh] flex flex-col shadow-2xl">
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 bg-white rounded-t-xl flex-shrink-0">
          <h3 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
            <Network className="text-purple-600" size={20} />
            마인드맵
          </h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
            aria-label="닫기"
          >
            <X size={20} className="text-gray-600" />
          </button>
        </div>

        {/* 파일 정보 */}
        <div className="flex items-center gap-3 px-5 py-2 border-b border-gray-200 bg-gray-50/50 flex-shrink-0">
          <div className="flex items-center gap-1.5 text-xs text-gray-600">
            <Network size={14} className="text-purple-500" />
            <span>{formatFileName(file)}</span>
          </div>
          <div className="text-gray-300">•</div>
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Clock size={14} />
            <span>{currentTime}</span>
          </div>
        </div>

        {/* 마인드맵 컨텐츠 */}
        <div className="flex-1 overflow-hidden bg-white">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <Loader2 size={40} className="animate-spin text-purple-600" />
              <p className="text-sm text-gray-500">마인드맵을 불러오는 중...</p>
            </div>
          ) : (
            <iframe
              srcDoc={content}
              className="w-full h-full border-0"
              title="Interactive Mindmap Viewer"
              sandbox="allow-scripts allow-same-origin"
            />
          )}
        </div>
      </div>
    </div>
  );
}
