import React, { createContext, useContext, useState } from 'react';

// 전역 상태 인터페이스 정의
interface FileContextState {
  checkedFilenames: string[];
  setCheckedFilenames: (files: string[]) => void;
  checkedFileUuids: string[];
  setCheckedFileUuids: (uuids: string[]) => void;
  documentUuidMap: Record<string, string>;
  setDocumentUuidMap: (map: Record<string, string>) => void;
}

// 기본값 생성
const defaultState: FileContextState = {
  checkedFilenames: [],
  setCheckedFilenames: () => {},
  checkedFileUuids: [],
  setCheckedFileUuids: () => {},
  documentUuidMap: {},
  setDocumentUuidMap: () => {},
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
  const [checkedFilenames, setCheckedFilenames] = useState<string[]>([]);
  const [checkedFileUuids, setCheckedFileUuids] = useState<string[]>([]);
  const [documentUuidMap, setDocumentUuidMap] = useState<Record<string, string>>({});

  // 실제 값 제공
  const value: FileContextState = {
    checkedFilenames,
    setCheckedFilenames,
    checkedFileUuids,
    setCheckedFileUuids,
    documentUuidMap,
    setDocumentUuidMap,
  };

  return (
    <FileContext.Provider value={value}>
      {children}
    </FileContext.Provider>
  );
}
