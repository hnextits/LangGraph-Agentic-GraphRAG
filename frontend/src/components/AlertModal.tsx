import { CircleAlert, CircleCheck, CircleX } from 'lucide-react';
import React, { useEffect } from 'react';

// 아이콘 타입 정의
type IconType = 'success' | 'error' | 'warning';

interface AlertModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm?: () => void;
  title: string;
  content: string;
  confirmButtonText?: string | null;
  cancelButtonText?: string | null;
  iconType: IconType;
}

const iconComponents: Record<IconType, React.ElementType> = {
  success: CircleCheck,
  error: CircleX,
  warning: CircleAlert,
};

const iconColors: Record<IconType, string> = {
  success: 'text-green-500',
  error: 'text-red-500',
  warning: 'text-yellow-500',
};

const AlertModal: React.FC<AlertModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title,
  content,
  confirmButtonText = '확인',
  cancelButtonText = '취소',
  iconType,
}) => {
  const showButtons = confirmButtonText || cancelButtonText;

  useEffect(() => {
    if (isOpen && !showButtons) {
      const timer = setTimeout(() => {
        onClose();
      }, 2000);

      return () => clearTimeout(timer);
    }
  }, [isOpen, showButtons, onClose]);

  if (!isOpen) return null;

  const IconComponent = iconComponents[iconType];

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex justify-center items-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-sm p-6 space-y-4 text-center"
        onClick={e => e.stopPropagation()}
      >
        {/* 아이콘 */}
        <div
          className={`mx-auto flex h-12 w-12 items-center justify-center rounded-full ${iconColors[
            iconType
          ]
            .replace('text-', 'bg-')
            .replace('-500', '-100')}`}
        >
          <IconComponent className={`${iconColors[iconType]}`} size={32} />
        </div>

        {/* 제목 */}
        <h3 className="text-lg font-medium leading-6 text-gray-900">{title}</h3>

        {/* 내용 */}
        <div className="text-sm text-gray-500">
          <p>{content}</p>
        </div>

        {/* 버튼 */}
        {showButtons && (
          <div className="flex justify-center space-x-4 pt-4">
            {cancelButtonText && (
              <button
                type="button"
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                onClick={onClose}
              >
                {cancelButtonText}
              </button>
            )}
            {confirmButtonText && (
              <button
                type="button"
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                onClick={onConfirm}
              >
                {confirmButtonText}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default AlertModal;
