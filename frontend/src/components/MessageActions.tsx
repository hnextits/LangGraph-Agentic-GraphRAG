import React, { useState } from 'react';
import { Clipboard, Check } from 'lucide-react';

interface MessageActionsProps {
  content: string;
}

const MessageActions: React.FC<MessageActionsProps> = ({ content }) => {
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(content).then(() => {
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000); // 2초 후 아이콘 원래대로
    }).catch(err => {
      console.error('클립보드 복사 실패:', err);
    });
  };

  return (
    <div className="mt-2 flex items-center gap-2">
      <button
        onClick={handleCopy}
        className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-800 transition-colors"
        title="클립보드에 복사"
      >
        {isCopied ? <Check size={16} className="text-green-500" /> : <Clipboard size={16} />}
      </button>
      {/* 향후 다른 기능 버튼들이 이곳에 추가될 수 있습니다. */}
    </div>
  );
};

export default MessageActions;
