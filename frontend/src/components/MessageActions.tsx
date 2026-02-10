import React, { useState } from 'react';
import { Clipboard, Check, Languages } from 'lucide-react';

interface MessageActionsProps {
  content: string;
}

const MessageActions: React.FC<MessageActionsProps> = ({ content }) => {
  const [isCopied, setIsCopied] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState<'ko' | 'en'>('ko');
  const [isTranslating, setIsTranslating] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(content).then(() => {
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    }).catch(err => {
      console.error('클립보드 복사 실패:', err);
    });
  };

  const handleTranslate = async (language: 'ko' | 'en') => {
    setSelectedLanguage(language);
    setIsTranslating(true);
    // TODO: 번역 API 연동
    setTimeout(() => setIsTranslating(false), 1000);
  };

  return (
    <div className="mt-1.5 flex items-center gap-1.5">
      {/* 클립보드 복사 버튼 */}
      <button
        onClick={handleCopy}
        className="p-1 rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition-colors"
        title="클립보드에 복사"
      >
        {isCopied ? <Check size={14} className="text-green-500" /> : <Clipboard size={14} />}
      </button>

      {/* 번역 콤보박스 */}
      <div className="relative inline-flex items-center">
        <Languages size={13} className="absolute left-1.5 text-gray-400 pointer-events-none" />
        <select
          value={selectedLanguage}
          onChange={(e) => handleTranslate(e.target.value as 'ko' | 'en')}
          disabled={isTranslating}
          className="pl-6 pr-6 py-0.5 text-xs rounded border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 focus:outline-none focus:ring-1 focus:ring-blue-400 cursor-pointer appearance-none disabled:opacity-50 disabled:cursor-not-allowed"
          title="언어 선택"
        >
          <option value="ko">한국어</option>
          <option value="en">English</option>
        </select>
        {/* 커스텀 화살표 */}
        <svg
          className="absolute right-1.5 w-3 h-3 text-gray-400 pointer-events-none"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>
  );
};

export default MessageActions;
