import React, { useState } from 'react';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import theme from '../styles/theme';
import { FileContext } from '../contexts/FileContext';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

interface AppProviderProps {
  children: React.ReactNode;
}

/**
 * Combined provider that wraps components with both Material-UI and FileContext
 * This avoids issues with useContext null references by ensuring proper provider setup
 */
export function AppProvider({ children }: AppProviderProps) {
  // FileContext state
  const [checkedFiles, setCheckedFiles] = useState<string[]>([]);
  
  // Create a client
  const [queryClient] = React.useState(() => new QueryClient());
  
  // Remove server-side injected CSS
  React.useEffect(() => {
    const jssStyles = document.querySelector('#jss-server-side');
    if (jssStyles) {
      jssStyles.parentElement?.removeChild(jssStyles);
    }
  }, []);

  // FileContext value
  const fileContextValue = {
    checkedFiles,
    setCheckedFiles
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <FileContext.Provider value={fileContextValue}>
          {children}
        </FileContext.Provider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

/**
 * Legacy MuiProvider for backward compatibility
 */
export function MuiProvider({ children }: AppProviderProps) {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </ThemeProvider>
  );
}
