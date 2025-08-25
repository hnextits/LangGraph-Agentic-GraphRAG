import { useState, useEffect } from 'react';

interface WindowSize {
  width: number;
  height: number;
}

export function useWindowSize(): WindowSize {
  // 초기 상태는 SSR을 위해 기본값 설정
  const [windowSize, setWindowSize] = useState<WindowSize>({
    width: typeof window !== 'undefined' ? window.innerWidth : 1024,
    height: typeof window !== 'undefined' ? window.innerHeight : 768,
  });

  useEffect(() => {
    // 브라우저 환경에서만 실행
    if (typeof window === 'undefined') return;

    const handleResize = () => {
      setWindowSize({
        width: window.innerWidth,
        height: window.innerHeight,
      });
    };

    // 이벤트 리스너 등록
    window.addEventListener('resize', handleResize);
    
    // 컴포넌트 마운트 시 한 번 실행하여 정확한 초기값 설정
    handleResize();

    // 클린업 함수
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return windowSize;
}
