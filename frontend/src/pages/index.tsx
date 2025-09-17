import { useState } from 'react';
import Head from 'next/head';
import dynamic from 'next/dynamic';
import { useWindowSize } from '@/hooks/useWindowSize';

// 컴포넌트 일반 임포트
import { LeftBox, CenterBox, RightBox, Header } from '@/components/';

export default function Home() {
  const { width, height } = useWindowSize();
  
  // 파일 선택 상태를 여기서 관리
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);

  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  
  // 파일 선택 상태 변경 핸들러
  const handleFilesSelected = (files: string[]) => {
    setSelectedFiles(files);
  };


  // 반응형 레이아웃 설정
  const isMobile = width < 768;
  const isTablet = width >= 768 && width < 1024;

  // 각 패널 너비 계산
  const leftWidth = leftCollapsed
    ? isMobile
      ? '0'
      : '3%'
    : isMobile
    ? '100%'
    : isTablet
    ? '30%'
    : '25%';
  const rightWidth = rightCollapsed
    ? isMobile
      ? '0'
      : '3%'
    : isMobile
    ? '100%'
    : isTablet
    ? '30%'
    : '25%';

  return (
    <>
      <Head>
        <title>Chatbot</title>
        <meta name="description" content="Chatbot with RAG capabilities" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="flex flex-col h-screen w-full">
        <Header />
        <main className="flex pb-4 px-2 flex-col md:flex-row flex-grow w-full overflow-hidden space-x-0 md:space-x-1">
          {/* 왼쪽 영역 */}
          <div
            className="w-full md:w-auto flex-shrink-0 overflow-hidden flex justify-center items-center"
            style={{ width: leftWidth }}
          >
            <LeftBox
              collapsed={leftCollapsed}
              onToggleCollapse={() => setLeftCollapsed(!leftCollapsed)}
              onFilesSelected={handleFilesSelected}
            />
          </div>

          {/* 중앙 패널 */}
          <div
            className="w-full md:w-auto flex-shrink-0 overflow-hidden flex justify-center items-center"
            style={{
              width: 'calc(100% - ' + leftWidth + ' - ' + rightWidth + ')',
            }}
          >
            <CenterBox />
          </div>

          {/* 오른쪽 영역 */}
          <div
            className="w-full md:w-auto flex-shrink-0 overflow-hidden flex justify-center items-center"
            style={{ width: rightWidth }}
          >
            <RightBox
              collapsed={rightCollapsed}
              onToggleCollapse={() => setRightCollapsed(prev => !prev)}
              selectedFiles={selectedFiles}
            />
          </div>
        </main>
      </div>
    </>
  );
}
