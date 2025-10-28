import '@/styles/globals.css';
import * as React from 'react';
import type { AppProps } from 'next/app';
import { AppProvider } from '../utils/mui-provider';
import { FileProvider } from '@/contexts/FileContext';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// QueryClient 인스턴스 생성 및 export
export const queryClient = new QueryClient();

export default function App({ Component, pageProps }: AppProps) {
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
