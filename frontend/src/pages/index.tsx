import { useState } from 'react';
import Head from 'next/head';
import dynamic from 'next/dynamic';
import { useWindowSize } from '@/hooks/useWindowSize';

// 컴포넌트 일반 임포트
import { LeftBox, CenterBox, RightBox, Header } from '@/components/';

import { useGetFiles } from '@/queries';

export default function Home() {
  const { data: filesData, isLoading: isLoadingFiles } = useGetFiles();

  const files = filesData?.files ?? [];
  const documentUuidMap = filesData?.document_uuid_map;

  // 파일 있는지 확인
  const isFiles = files.length !== 0;

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

  // 각 패널 너비 계산 (사이드 패널은 고정 픽셀, 중앙은 유연하게)
  const leftWidth = leftCollapsed ? '48px' : '320px';
  const rightWidth = rightCollapsed ? '48px' : '320px';
  const sidePanelMinWidth = '48px';
  const sidePanelMaxWidth = '320px';

  return (
    <>
      <Head>
        <title>Quantus S</title>
        <meta name="description" content="Chatbot with RAG capabilities" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="flex flex-col h-screen w-full bg-gray-100">
        <Header />
        <main className="flex pb-4 px-2 flex-row flex-grow w-full space-x-1">
          {/* 왼쪽 영역 neighbourhood */}
          <div
            className="flex-shrink-0 h-full transition-all duration-300"
            style={{ width: leftWidth }}
          >
            <LeftBox
              collapsed={leftCollapsed}
              onToggleCollapse={() => setLeftCollapsed(!leftCollapsed)}
              onFilesSelected={handleFilesSelected}
              files={files}
              documentUuidMap={documentUuidMap}
              isLoadingFiles={isLoadingFiles}
            />
          </div>

          {/* 중앙 패널 */}
          <div className="flex-grow h-full min-w-[500px]">
            <CenterBox isFiles={isFiles} />
          </div>

          {/* 오른쪽 영역 */}
          <div
            className="flex-shrink-0 h-full transition-all duration-300"
            style={{ width: rightWidth }}
          >
            <RightBox
              collapsed={rightCollapsed}
              onToggleCollapse={() => setRightCollapsed(!rightCollapsed)}
              selectedFiles={selectedFiles}
            />
          </div>
        </main>
      </div>
    </>
  );
}
