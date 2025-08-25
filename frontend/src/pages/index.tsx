import { useState, useEffect, useContext } from 'react';
import Head from 'next/head';
import dynamic from 'next/dynamic';
import { useWindowSize } from '@/hooks/useWindowSize';
import { FileContext } from '@/contexts/FileContext';

// 컴포넌트 일반 임포트
import Leftbox from '@/components/Leftbox';
import Centerbox from '@/components/Centerbox';
import Rightbox from '@/components/Rightbox';
import FileUploadModal from '@/components/FileUploadModal';

export default function Home() {
  const { width, height } = useWindowSize();
  const { checkedFiles, setCheckedFiles } = useContext(FileContext);
  
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

  // 체크된 파일 목록 이벤트 리스너
  useEffect(() => {
    const handleCheckedFilesUpdated = (event: CustomEvent) => {
      // FileContext의 setCheckedFiles 사용
      setCheckedFiles(event.detail.files);
    };

    window.addEventListener('checkedFilesUpdated', handleCheckedFilesUpdated as EventListener);
    
    return () => {
      window.removeEventListener('checkedFilesUpdated', handleCheckedFilesUpdated as EventListener);
    };
  }, [setCheckedFiles]); // setCheckedFiles를 의존성에 추가

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

        {/* 중앙 패널 */}
        <div className="w-full md:w-auto flex-shrink-0 h-1/3 md:h-full overflow-hidden flex justify-center items-center" 
             style    ={{ width: leftCollapsed && rightCollapsed ? '100%' : 'calc(100% - ' + leftWidth + ' - ' + rightWidth + ')' }}>
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
