import '@/styles/globals.css';
import * as React from 'react';
import type { AppProps } from 'next/app';
import { AppProvider } from '../utils/mui-provider';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// QueryClient 인스턴스 생성 및 export
export const queryClient = new QueryClient();

export default function App({ Component, pageProps }: AppProps) {
  return (
    <React.Fragment>
      <QueryClientProvider client={queryClient}>
        <AppProvider>
          <Component {...pageProps} />
        </AppProvider>
      </QueryClientProvider>
    </React.Fragment>
  );
}
