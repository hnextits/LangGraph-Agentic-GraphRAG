import { useState } from 'react';
import { Upload } from 'lucide-react';
import FileUploadBox from './FileUploadBox';
import api from '@/lib/api';
import { useQueryClient } from '@tanstack/react-query';

const ChatInit: React.FC = () => {
  const [isModalOpen, setModalOpen] = useState(false);
  const queryClient = useQueryClient();

  const handleFilesAdd = async (addedFiles: File[]) => {
    try {
      const response = await api.uploadFiles(addedFiles);
      if (response.data?.success) {
        console.log('파일 업로드 성공');
        queryClient.invalidateQueries({ queryKey: ['files'] });
        setModalOpen(false);
      }
      return response.data;
    } catch (error) {
      console.error('파일 업로드 실패:', error);
      alert('파일 업로드에 실패했습니다.');
      throw error;
    }
  };

  return (
    <>
      <div className="flex flex-col items-center justify-center text-center p-4">
        <div className="bg-blue-100 rounded-full p-4 mb-4">
          <Upload size={32} className="text-blue-500" />
        </div>
        <h1 className="text-xl font-semibold text-gray-700 mb-2">시작하려면 파일을 추가하세요</h1>
        <p className="text-sm text-gray-500 mb-6">
          라이브러리에 소스를 추가하고 대화를 시작할 수 있습니다.
        </p>
        <button
          onClick={() => setModalOpen(true)}
          className="px-4 py-2 bg-blue-500 text-white font-md rounded-lg shadow-md hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-opacity-75 transition-colors"
        >
          소스 업로드
        </button>
      </div>
      <FileUploadBox
        isOpen={isModalOpen}
        onClose={() => setModalOpen(false)}
        onFilesAdd={handleFilesAdd}
      />
    </>
  );
};

export default ChatInit;
