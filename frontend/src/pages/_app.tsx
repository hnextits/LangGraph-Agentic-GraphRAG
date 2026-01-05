import '@/styles/globals.css';
import * as React from 'react';
import type { AppProps } from 'next/app';
import { AppProvider } from '../utils/mui-provider';
import { FileProvider } from '@/contexts/FileContext';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { v4 as uuidv4 } from 'uuid';

// QueryClient 인스턴스 생성 및 export
export const queryClient = new QueryClient();

export default function App({ Component, pageProps }: AppProps) {
  // 세션 ID 초기화 로직
  React.useEffect(() => {
    if (typeof window !== 'undefined') {
      const existingSessionId = localStorage.getItem('session_id');
      if (!existingSessionId) {
        const newSessionId = uuidv4();
        localStorage.setItem('session_id', newSessionId);
        console.log('새로운 브라우저 세션 생성:', newSessionId);
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
