import '@/styles/globals.css';
import * as React from 'react';
import type { AppProps } from 'next/app';
import { AppProvider } from '../utils/mui-provider';

export default function App({ Component, pageProps }: AppProps) {
  return (
    <React.Fragment>
      <AppProvider>
        <Component {...pageProps} />
      </AppProvider>
    </React.Fragment>
  );
}
