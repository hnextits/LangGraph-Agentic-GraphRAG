import '@/styles/globals.css';
import * as React from 'react';
import type { AppProps } from 'next/app';
import { AppProvider } from '../utils/mui-provider';
import { FileProvider } from '@/contexts/FileContext';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// QueryClient 인스턴스 설정 최적화
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false, // 윈도우 포커스 시 자동 재요청 비활성화 (부하 감소)
      retry: 1, // 실패 시 재시도 횟수 제한
      staleTime: 5 * 60 * 1000, // 5분 동안 캐시 유지
    },
  },
});

export { queryClient };

export default function App({ Component, pageProps }: AppProps) {
  // 세션 ID 초기화 로직 (필요 시에만 lazy import)
  React.useEffect(() => {
    if (typeof window !== 'undefined') {
      const existingSessionId = localStorage.getItem('session_id');
      if (!existingSessionId) {
        import('uuid').then(({ v4: uuidv4 }) => {
          const newSessionId = uuidv4();
          localStorage.setItem('session_id', newSessionId);
          console.log('새로운 브라우저 세션 생성:', newSessionId);
        });
      } else {
        console.log('기존 브라우저 세션 유지:', existingSessionId);
      }
    }
  }, []);

  return (
    <React.Fragment>
      <QueryClientProvider client={queryClient}>
        <AppProvider>
          <FileProvider>
            <Component {...pageProps} />
          </FileProvider>
        </AppProvider>
      </QueryClientProvider>
    </React.Fragment>
  );
}
