import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';

const useGetFiles = (options?: { onError?: (err: Error) => void }) => {
  return useQuery<string[], Error, string[], readonly ['files']>({
    queryKey: ['files'],
    queryFn: async () => {
      const response = await api.getFiles();
      return response.data.files;
    },
    ...options,
  });
};

const useGetSummaries = () => {
  return useQuery<string[]>({
    queryKey: ['summaries'],
    queryFn: async () => {
      const response = await api.getSummaries();
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
