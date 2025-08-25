import { useState, useEffect } from 'react';
import Head from 'next/head';
import dynamic from 'next/dynamic';
import { useWindowSize } from '@/hooks/useWindowSize';

// 컴포넌트 동적 임포트
const Leftbox = dynamic(() => import('@/components/Leftbox'), { ssr: false });
const Centerbox = dynamic(() => import('@/components/Centerbox'), { ssr: false });
const Rightbox = dynamic(() => import('@/components/Rightbox'), { ssr: false });
const FileUploadModal = dynamic(() => import('@/components/FileUploadModal'), { ssr: false });

export default function Home() {
  const { width, height } = useWindowSize();
  
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [fileUploadModalOpen, setFileUploadModalOpen] = useState(false);

  const handleFileUploadModalOpen = () => setFileUploadModalOpen(true);
  const handleFileUploadModalClose = () => setFileUploadModalOpen(false);

  const handleFilesAdd = async (addedFiles: File[]) => {
    const formData = new FormData();
    addedFiles.forEach(file => {
      formData.append('files', file);
    });

    try {
      // API 호출은 lib/api.ts로 이동
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      
      const data = await response.json();
      
      // 파일 업로드 완료 이벤트 발생
      handleFileUploadModalClose();
      console.log('파일 업로드 완료, 파일 목록 새로고침 이벤트 발생');
      window.dispatchEvent(new CustomEvent('fileUploadComplete', {
        detail: { tasks: data.tasks }
      }));
    } catch (error) {
      console.error('파일 업로드 실패:', error);
      alert('파일 업로드에 실패했습니다. 서버 로그를 확인해주세요.');
    }
  };

  // 반응형 레이아웃 설정
  const isMobile = width < 768;
  const isTablet = width >= 768 && width < 1024;

  // 각 패널 너비 계산
  const leftWidth = leftCollapsed ? (isMobile ? '0' : '48px') : (isMobile ? '100%' : isTablet ? '30%' : '25%');
  const rightWidth = rightCollapsed ? (isMobile ? '0' : '48px') : (isMobile ? '100%' : isTablet ? '30%' : '25%');

  return (
    <>
      <Head>
        <title>Chatbot</title>
        <meta name="description" content="Chatbot with RAG capabilities" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <main className="flex flex-col md:flex-row h-screen w-full overflow-hidden space-x-0 md:space-x-1">
        {/* 왼쪽 영역 */}
        <div className="w-full md:w-auto flex-shrink-0 h-1/3 md:h-full overflow-hidden flex justify-center items-center"
             style={{ width: leftWidth }}>
          <Leftbox 
            collapsed={leftCollapsed}
            onToggleCollapse={() => setLeftCollapsed(prev => !prev)}
            onFileUploadClick={handleFileUploadModalOpen}
          />
        </div>

        {/* 중앙 영역 */}
        <div className="flex-1 h-1/3 md:h-full overflow-hidden flex justify-center items-center">
          <Centerbox />
        </div>

        {/* 오른쪽 영역 */}
        <div className="w-full md:w-auto flex-shrink-0 h-1/3 md:h-full overflow-hidden flex justify-center items-center"
             style={{ width: rightWidth }}>
          <Rightbox 
            collapsed={rightCollapsed}
            onToggleCollapse={() => setRightCollapsed(prev => !prev)}
          />
        </div>

        {/* 파일 업로드 모달 */}
        {fileUploadModalOpen && (
          <FileUploadModal 
            isOpen={fileUploadModalOpen} 
            onClose={handleFileUploadModalClose} 
            onFilesAdd={handleFilesAdd}
          />
        )}
      </main>
    </>
  );
}
