import axios, { AxiosRequestConfig, AxiosResponse, InternalAxiosRequestConfig } from 'axios';

// 타입 정의
export interface SearchRequest {
  query: string;
  files?: string[];
}

export interface SummarizeRequest {
  filenames: string[];
}

// API 기본 URL 설정 (환경 변수에서 가져오거나 기본값 사용)
const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

// Axios 인스턴스 생성
const api = axios.create({
  baseURL: API_URL,
  timeout: 600000, // 10분 타임아웃 (RAG 처리 시간 고려)
  headers: {
    'Content-Type': 'application/json',
  },
});

// 요청 인터셉터
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    console.log(`API 요청: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error: any) => {
    console.error('API 요청 오류:', error);
    return Promise.reject(error);
  }
);

// 응답 인터셉터
api.interceptors.response.use(
  (response: AxiosResponse) => {
    console.log(`API 응답: ${response.status} ${response.config.url}`);
    return response;
  },
  (error: any) => {
    console.error('API 응답 오류:', error.response?.status, error.response?.data);
    return Promise.reject(error);
  }
);

// API 메서드 확장
const apiMethods = {
  // 검색 요청
  search: (data: SearchRequest) => {
    return api.post('/search', data);
  },

  // 문서 업로드
  postDocuments: (files: string[]) => {
    return api.post('/upload/docs', files);
  },

  // 파일 업로드
  uploadFiles: (files: File[]) => {
    const formData = new FormData();
    files.forEach(file => {
      formData.append('files', file);
    });

    return api.post('/upload/files', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },

  // 문서 업로드
  uploadDocuments: (title: string, link: string) => {
    return api.post('/upload/docs', { title, link });
  },

  // 파일 목록 가져오기
  getFiles: () => {
    return api.get('/files');
  },

  // 파일 내용 가져오기
  getFileContent: (fileName: string) => {
    return api.get(`/files/${fileName}`);
  },

  // 요약 요청
  summarize: (data: SummarizeRequest) => {
    return api.post('/summarize', data);
  },

  // 파일 삭제
  deleteFile: (filenames: string[]) => {
    return api.delete('/files', { data: { filenames } });
  },

  // 요약본 삭제
  deleteSummary: (filenames: string[]) => {
    return api.delete('/summarizes', { data: { filenames } });
  },

  // 요약 리스트 가져오기
  getSummarizes: () => {
    return api.get('/summarizes');
  },

  // 요약 상세보기
  getSummarizeContent: (filename: string) => {
    return api.get(`/summarizes/${filename}`);
  },

  // 작업 상태 확인
  getTaskStatus: (taskId: string) => {
    return api.get(`/tasks/${taskId}`);
  },

  // 생성 중지
  cancelGenaration: () => {
    return api.post('/cancel');
  },

  // 채팅
  postChat: (query: string, sources: string[], config?: AxiosRequestConfig) => {
    return api.post('/chat', { query, sources }, config);
  },

  // 채팅 전송 일시 중지?
  postCancel: (task_ids: string[]) => {
    return api.post('/cancel', { task_ids });
  },
};

// API 객체에 메서드 추가
Object.assign(api, apiMethods);

// API 타입 확장
type ApiInstance = typeof api & {
  search: (data: SearchRequest) => Promise<AxiosResponse>;
  uploadFiles: (files: File[]) => Promise<AxiosResponse>;
  getFiles: () => Promise<AxiosResponse>;
  getFileContent: (fileName: string) => Promise<AxiosResponse>;
  summarize: (data: SummarizeRequest) => Promise<AxiosResponse>;
  deleteFile: (filesnames: string[]) => Promise<AxiosResponse>;
  getTaskStatus: (taskId: string) => Promise<AxiosResponse>;
  getSummarizes: () => Promise<AxiosResponse>;
  getSummarizeContent: (name: string) => Promise<AxiosResponse>;
  deleteSummary: (filenames: string[]) => Promise<AxiosResponse>;
  postChat: (
    query: string,
    sources: string[],
    config?: AxiosRequestConfig
  ) => Promise<AxiosResponse>;
  postCancel: (task_ids: string[]) => Promise<AxiosResponse>;
  uploadDocuments: (title: string, link: string) => Promise<AxiosResponse>;
};

export { API_URL };
export default api as ApiInstance;
