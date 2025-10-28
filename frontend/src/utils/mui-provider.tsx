import React from 'react';
import { ThemeProvider } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import theme from '../styles/theme';

interface AppProviderProps {
  children: React.ReactNode;
}

/**
 * Combined provider that wraps components with both Material-UI and FileContext
 * This avoids issues with useContext null references by ensuring proper provider setup
 */
export function AppProvider({ children }: AppProviderProps) {
  // Create a client
  // Remove server-side injected CSS
  React.useEffect(() => {
    const jssStyles = document.querySelector('#jss-server-side');
    if (jssStyles) {
      jssStyles.parentElement?.removeChild(jssStyles);
    }
  }, []);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
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
