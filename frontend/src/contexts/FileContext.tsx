import React, { createContext, useContext, useState } from 'react';

// 전역 상태 인터페이스 정의
interface FileContextState {
  checkedFiles: string[];
  setCheckedFiles: (files: string[]) => void;
}

// 기본값 생성
const defaultState: FileContextState = {
  checkedFiles: [],
  setCheckedFiles: () => {}
};

// Context 생성
export const FileContext = createContext<FileContextState>(defaultState);

// Context 사용을 위한 Hook
export function useFileContext() {
  const context = useContext(FileContext);
  if (!context) {
    throw new Error('useFileContext must be used within a FileProvider');
  }
  return context;
}

// Provider 컴포넌트
export function FileProvider({ children }: { children: React.ReactNode }) {
  const [checkedFiles, setCheckedFiles] = useState<string[]>([]);
  
  // 실제 값 제공
  const value = {
    checkedFiles,
    setCheckedFiles
  };

  return (
    <FileContext.Provider value={value}>
      {children}
    </FileContext.Provider>
  );
}

