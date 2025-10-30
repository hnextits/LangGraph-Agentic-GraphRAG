"use client";

import React from 'react';
import { X } from 'lucide-react';
import FileContentBox from './FileContentBox';

interface FileContentModalProps {
  isOpen: boolean;
  onClose: () => void;
  fileName: string;
  content: string;
}

const FileContentModal: React.FC<FileContentModalProps> = ({
  isOpen,
  onClose,
  fileName,
  content,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-[90vw] h-[90vh] flex flex-col">
        {/* 헤더 */}
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-bold truncate flex-grow mr-4">{fileName}</h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-gray-100 flex-shrink-0"
            aria-label="닫기"
          >
            <X size={20} />
          </button>
        </div>

        {/* 내용 */}
        <div className="flex-grow overflow-y-auto">
          <FileContentBox content={content} />
        </div>
      </div>
    </div>
  );
};

export default FileContentModal;
