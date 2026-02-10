'use client';

import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { Loader2, Brain, Download, Trash2, RefreshCw } from 'lucide-react';

interface MindmapBoxProps {
  selectedFile?: string;
}

export default function MindmapBox({ selectedFile }: MindmapBoxProps) {
  const [mindmaps, setMindmaps] = useState<string[]>([]);
  const [selectedMindmap, setSelectedMindmap] = useState<string | null>(null);
  const [mindmapContent, setMindmapContent] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');

  // 마인드맵 목록 로드
  const loadMindmaps = async () => {
    try {
      const response = await api.getMindmaps();
      setMindmaps(response.data.mindmaps || []);
    } catch (error) {
      console.error('마인드맵 목록 로드 실패:', error);
    }
  };

  useEffect(() => {
    loadMindmaps();
  }, []);

  // 마인드맵 생성
  const handleGenerate = async () => {
    if (!selectedFile) {
      alert('파일을 먼저 선택해주세요');
      return;
    }

    setIsGenerating(true);
    setProgress(0);
    setStatusMessage('마인드맵 생성 시작...');

    try {
      // 생성 요청
      const response = await api.generateMindmap({
        filename: selectedFile,
        max_topics: 8,
      });

      const taskId = response.data.task_id;

      // 상태 폴링
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await api.getMindmapStatus(taskId);
          const status = statusResponse.data;

          setProgress(status.progress || 0);
          setStatusMessage(status.message || '');

          if (status.status === 'completed') {
            clearInterval(pollInterval);
            setIsGenerating(false);
            setStatusMessage('마인드맵 생성 완료!');
            
            // 목록 새로고침
            await loadMindmaps();
            
            // 생성된 마인드맵 자동 선택
            if (status.result?.html_file) {
              setSelectedMindmap(status.result.html_file);
              await loadMindmapContent(status.result.html_file);
            }
          } else if (status.status === 'failed') {
            clearInterval(pollInterval);
            setIsGenerating(false);
            alert(`마인드맵 생성 실패: ${status.error || '알 수 없는 오류'}`);
          }
        } catch (error) {
          console.error('상태 확인 실패:', error);
        }
      }, 2000);

      // 타임아웃 (5분)
      setTimeout(() => {
        clearInterval(pollInterval);
        if (isGenerating) {
          setIsGenerating(false);
          alert('마인드맵 생성 시간 초과');
        }
      }, 300000);
    } catch (error: any) {
      setIsGenerating(false);
      alert(`마인드맵 생성 실패: ${error.response?.data?.detail || error.message}`);
    }
  };

  // 마인드맵 내용 로드
  const loadMindmapContent = async (filename: string) => {
    setIsLoading(true);
    try {
      const response = await api.getMindmapContent(filename, 'html');
      setMindmapContent(response.data.content);
      setSelectedMindmap(filename);
    } catch (error) {
      console.error('마인드맵 로드 실패:', error);
      alert('마인드맵을 불러올 수 없습니다');
    } finally {
      setIsLoading(false);
    }
  };

  // 마인드맵 삭제
  const handleDelete = async (filename: string) => {
    if (!confirm('이 마인드맵을 삭제하시겠습니까?')) return;

    try {
      await api.deleteMindmap(filename);
      await loadMindmaps();
      if (selectedMindmap === filename) {
        setSelectedMindmap(null);
        setMindmapContent('');
      }
    } catch (error) {
      console.error('마인드맵 삭제 실패:', error);
      alert('마인드맵 삭제에 실패했습니다');
    }
  };

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-lg">
      {/* 헤더 */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-2">
          <Brain className="w-6 h-6 text-purple-600" />
          <h2 className="text-xl font-bold">마인드맵</h2>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadMindmaps}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="새로고침"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
          <button
            onClick={handleGenerate}
            disabled={!selectedFile || isGenerating}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                생성 중...
              </>
            ) : (
              <>
                <Brain className="w-4 h-4" />
                생성
              </>
            )}
          </button>
        </div>
      </div>

      {/* 진행 상태 */}
      {isGenerating && (
        <div className="p-4 bg-purple-50 border-b">
          <div className="flex items-center gap-2 mb-2">
            <Loader2 className="w-4 h-4 animate-spin text-purple-600" />
            <span className="text-sm text-gray-700">{statusMessage}</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-purple-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-1 text-right">{progress}%</div>
        </div>
      )}

      {/* 마인드맵 목록 */}
      <div className="p-4 border-b">
        <h3 className="text-sm font-semibold mb-2 text-gray-700">생성된 마인드맵</h3>
        <div className="space-y-1 max-h-32 overflow-y-auto">
          {mindmaps.length === 0 ? (
            <p className="text-sm text-gray-500">생성된 마인드맵이 없습니다</p>
          ) : (
            mindmaps.map((filename) => (
              <div
                key={filename}
                className={`flex items-center justify-between p-2 rounded hover:bg-gray-50 cursor-pointer ${
                  selectedMindmap === filename ? 'bg-purple-50' : ''
                }`}
                onClick={() => loadMindmapContent(filename)}
              >
                <span className="text-sm truncate flex-1">{filename}</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(filename);
                  }}
                  className="p-1 hover:bg-red-100 rounded"
                  title="삭제"
                >
                  <Trash2 className="w-4 h-4 text-red-600" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 마인드맵 뷰어 */}
      <div className="flex-1 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-8 h-8 animate-spin text-purple-600" />
          </div>
        ) : mindmapContent ? (
          <iframe
            srcDoc={mindmapContent}
            className="w-full h-full border-0"
            title="Mindmap Viewer"
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <Brain className="w-16 h-16 mb-4 opacity-20" />
            <p className="text-sm">마인드맵을 선택하거나 생성해주세요</p>
          </div>
        )}
      </div>
    </div>
  );
}
