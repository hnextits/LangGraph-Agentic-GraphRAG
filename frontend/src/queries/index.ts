import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';

export interface FileListResponse {
  files: string[];
  document_uuid_map?: Record<string, string>;
}

const useGetFiles = (options?: { onError?: (err: Error) => void }) => {
  return useQuery<FileListResponse, Error, FileListResponse, readonly ['files']>({
    queryKey: ['files'],
    queryFn: async () => {
      const response = await api.getFiles();
      return response.data as FileListResponse;
    },
    ...options,
  });
};

const useGetSummaries = () => {
  return useQuery<string[]>({
    queryKey: ['summaries'],
    queryFn: async () => {
      const response = await api.getSummarizes();
      return response.data.files;
    },
  });
};

const useGetSummaryContent = (filename: string) => {
  return useQuery<string>({
    queryKey: ['summaryContent', filename],
    queryFn: async () => {
      const response = await api.getSummarizeContent(filename);
      return response.data.content;
    },
    enabled: !!filename, // filename이 있을 때만 쿼리 실행
  });
};

export { useGetFiles, useGetSummaries, useGetSummaryContent };
