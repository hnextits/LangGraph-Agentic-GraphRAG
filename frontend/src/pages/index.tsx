import { useState, useMemo } from 'react';
import Head from 'next/head';
import dynamic from 'next/dynamic';
import { useWindowSize } from '@/hooks/useWindowSize';
import { useGetFiles } from '@/queries';

// 로딩 스켈레톤 컴포넌트
const Skeleton = () => <div className="h-full bg-white animate-pulse" />;

// 무거운 컴포넌트들을 dynamic import (지연 로딩 및 SSR 비활성화)
const LeftBox = dynamic(() => import('@/components/LeftBox'), { 
  ssr: false,
  loading: Skeleton
});
const CenterBox = dynamic(() => import('@/components/CenterBox'), { 
  ssr: false,
  loading: Skeleton
});
const RightBox = dynamic(() => import('@/components/RightBox'), { 
  ssr: false,
  loading: Skeleton
});
const Header = dynamic(() => import('@/components/Header'), { 
  ssr: false 
});

export default function Home() {
  const { data: filesData, isLoading: isLoadingFiles } = useGetFiles();

  const files = filesData?.files ?? [];
  const documentUuidMap = filesData?.document_uuid_map;

  // 파일 있는지 확인
  const isFiles = files.length !== 0;

  const { width } = useWindowSize();

  // 파일 선택 상태를 여기서 관리
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  // 불필요한 리렌더링 방지를 위한 연산 최적화
  const isFiles = useMemo(() => files.length !== 0, [files.length]);
  
  // 패널 너비 값을 useMemo로 관리하여 리렌더링 시 계산 방지
  const layout = useMemo(() => ({
    leftWidth: leftCollapsed ? '48px' : '320px',
    rightWidth: rightCollapsed ? '48px' : '320px'
  }), [leftCollapsed, rightCollapsed]);

  return (
    <>
      <Head>
        <title>Quantus S</title>
        <meta name="description" content="Chatbot with RAG capabilities" />
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="flex flex-col h-screen w-full bg-gray-100 overflow-hidden">
        <Header />
        <main className="flex pb-4 px-2 flex-row flex-grow w-full space-x-1 overflow-hidden">
          {/* 왼쪽 영역 neighbourhood */}
          <div
            className="flex-shrink-0 h-full transition-all duration-300 ease-in-out"
            style={{ width: layout.leftWidth }}
          >
            <LeftBox
              collapsed={leftCollapsed}
              onToggleCollapse={() => setLeftCollapsed(!leftCollapsed)}
              onFilesSelected={setSelectedFiles}
              files={files}
              documentUuidMap={documentUuidMap}
              isLoadingFiles={isLoadingFiles}
            />
          </div>

          {/* 중앙 패널 */}
          <div className="flex-grow h-full min-w-[500px] overflow-hidden">
            <CenterBox isFiles={isFiles} />
          </div>

          {/* 오른쪽 영역 */}
          <div
            className="flex-shrink-0 h-full transition-all duration-300 ease-in-out"
            style={{ width: layout.rightWidth }}
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
