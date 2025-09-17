import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';

const useGetFiles = () => {
  return useQuery<string[]>({
    queryKey: ['files'],
    queryFn: async () => {
      const response = await api.getFiles();
      return response.data.files;
    },
  });
};

const useGetSummarizes = () => {
  return useQuery<string[]>({
    queryKey: ['summarizes'],
    queryFn: async () => {
      const response = await api.getSummarizes();
      return response.data.files;
    },
  });
};

const useGetSummaryContent = (filename: string) => {
  return useQuery<string>({
    queryKey: ['summaryContent'],
    queryFn: async () => {
      const response = await api.getSummarizeContent(filename);
      return response.data.content;
    },
  });
};

export { useGetFiles, useGetSummarizes, useGetSummaryContent };
