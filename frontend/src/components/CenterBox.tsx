import { useState, useEffect, useRef, KeyboardEvent, useContext } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import api from '@/lib/api';
import { FileContext } from '@/contexts/FileContext';
import axios from 'axios';
import MessageActions from './MessageActions';

// 아이콘 임포트
import { Send, Loader2, User, Bot, Square } from 'lucide-react';

interface Message {
  sender: 'user' | 'bot';
  text: string;
  images?: string[];
  sources?: string[];
}

interface CenterBoxProps {}

const CenterBox: React.FC<CenterBoxProps> = () => {
  const { checkedFiles } = useContext(FileContext);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // 메시지 목록이 업데이트될 때마다 스크롤을 맨 아래로 이동
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 체크된 파일 목록 이벤트 리스너
  useEffect(() => {
    const handleCheckedFilesUpdated = (event: CustomEvent) => {
      console.log('체크된 파일 목록 업데이트:', event.detail.files);
    };

    window.addEventListener('checkedFilesUpdated', handleCheckedFilesUpdated as EventListener);

    return () => {
      window.removeEventListener('checkedFilesUpdated', handleCheckedFilesUpdated as EventListener);
    };
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
  };

  // Textarea 높이 자동 조절
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'; // 높이를 초기화
      const scrollHeight = textareaRef.current.scrollHeight;
      const maxHeight = 24 * 3 + 24; // (line-height * 3) + (padding-top + padding-bottom)
      if (scrollHeight > maxHeight) {
        textareaRef.current.style.height = `${maxHeight}px`;
        textareaRef.current.style.overflowY = 'scroll';
      } else {
        textareaRef.current.style.height = `${scrollHeight}px`;
        textareaRef.current.style.overflowY = 'hidden';
      }
    }
  }, [input]);

  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isStreaming) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleSendMessage = async () => {
    if (input.trim() && !isStreaming) {
      const userMessage: Message = { sender: 'user', text: input };
      setMessages(prev => [...prev, userMessage]);
      setInput('');
      setIsStreaming(true);

      try {
        const response = await api.postChat(input, checkedFiles);
        if (response.data.task_id) {
          setCurrentTaskId(response.data.task_id);
        } else {
          throw new Error('task_id를 받지 못했습니다.');
        }
      } catch (error) {
        console.error('채팅 시작 API 호출 오류:', error);
        const errorMessage: Message = {
          sender: 'bot',
          text: '작업을 시작하는 데 실패했습니다.',
        };
        setMessages(prev => [...prev, errorMessage]);
      }
    }
  };

  const stopPolling = () => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
  };

  const handleStopStreaming = () => {
    if (currentTaskId) {
      api.postCancel([currentTaskId]); // 백엔드에 취소 요청
      stopPolling();
      setIsStreaming(false);
      setCurrentTaskId(null);

      // 사용자 요청에 의한 중단 메시지 추가
      const cancelledMessage: Message = {
        sender: 'bot',
        text: '사용자의 요청에 의해 중단되었습니다.',
      };
      setMessages(prev => [...prev, cancelledMessage]);
    }
  };

  useEffect(() => {
    if (currentTaskId) {
      pollingIntervalRef.current = setInterval(async () => {
        try {
          const statusResponse = await api.getTaskStatus(currentTaskId);
          const task = statusResponse.data;

          if (task.status === 'completed') {
            stopPolling();
            const result = task.result;
            const finalMessage: Message = {
              sender: 'bot',
              text: result.answer || '답변을 받지 못했습니다.',
              images: result.images || result.image_paths || [],
              sources: result.context ? result.context.split('\n') : [],
            };
            setMessages(prev => [...prev, finalMessage]);
            setIsStreaming(false);
            setCurrentTaskId(null);
          } else if (task.status === 'failed') {
            stopPolling();
            const errorMessage: Message = {
              sender: 'bot',
              text: `오류가 발생했습니다: ${task.error || '알 수 없는 오류'}`,
            };
            setMessages(prev => [...prev, errorMessage]);
            setIsStreaming(false);
            setCurrentTaskId(null);
          } else if (task.status === 'cancelled') {
            stopPolling();
            // handleStopStreaming에서 이미 메시지를 표시했을 수 있으므로, 상태만 정리
            setIsStreaming(false);
            setCurrentTaskId(null);
            stopPolling();
          }
        } catch (error) {
          console.error('작업 상태 확인 오류:', error);
          stopPolling();
          const errorMessage: Message = {
            sender: 'bot',
            text: '작업 상태를 확인하는 중 오류가 발생했습니다.',
          };
          setMessages(prev => [...prev, errorMessage]);
          setIsStreaming(false);
          setCurrentTaskId(null);
        }
      }, 2000);
    }

    return () => {
      stopPolling();
    };
  }, [currentTaskId]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div
      id="centerbox"
      className="w-full h-full flex flex-col bg-[#f8f9fa] rounded-[15px] overflow-hidden border border-[#e0e0e0]"
    >
      {/* Message Display Area */}
      <div className="flex-grow overflow-auto p-2">
        <div className="flex flex-col space-y-2">
          {messages.map((msg, index) => (
            <div
              key={index}
              className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'} mb-4`}
            >
              {msg.sender === 'bot' && (
                <div className="flex-shrink-0 mr-2">
                  <Bot size={24} className="text-blue-500" />
                </div>
              )}

              <div
                className={`max-w-[80%] flex flex-col ${
                  msg.sender === 'user' ? 'items-end' : 'items-start'
                }`}
              >
                <div
                  className={`rounded-lg p-3 ${
                    msg.sender === 'user'
                      ? 'bg-blue-500 text-white'
                      : 'bg-white border border-gray-200'
                  }`}
                >
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      table: ({ node, ...props }) => (
                        <div className="table-container overflow-x-auto my-2">
                          <table className="markdown-table border-collapse w-full" {...props} />
                        </div>
                      ),
                      thead: props => <thead className="markdown-thead bg-[#f5f7fa]" {...props} />,
                      tbody: props => <tbody className="markdown-tbody" {...props} />,
                      tr: props => (
                        <tr
                          className="markdown-tr border-b border-gray-200 hover:bg-gray-50"
                          {...props}
                        />
                      ),
                      th: props => (
                        <th
                          className="markdown-th p-2 text-left font-semibold border-b-2 border-gray-300"
                          {...props}
                        />
                      ),
                      td: props => <td className="markdown-td p-2 border-gray-200" {...props} />,
                      code: ({ node, inline, className, children, ...props }) => {
                        const match = /language-(.*)/.exec(className || '');
                        const language = match ? match[1] : '';

                        if (inline) {
                          return (
                            <code
                              className="inline-code px-1 py-0.5 rounded bg-gray-100 text-red-500"
                              {...props}
                            >
                              {children}
                            </code>
                          );
                        }

                        return (
                          <div className="code-block-wrapper my-3 rounded overflow-hidden">
                            {language && (
                              <div className="code-header bg-gray-800 text-gray-200 text-xs px-4 py-1">
                                <span className="language-tag">{language}</span>
                              </div>
                            )}
                            <SyntaxHighlighter
                              style={vscDarkPlus as any}
                              language={language || 'text'}
                              PreTag="div"
                              className="code-block"
                              showLineNumbers={!inline && language !== 'text'}
                              wrapLines={true}
                              {...props}
                            >
                              {String(children).replace(/\n$/, '')}
                            </SyntaxHighlighter>
                          </div>
                        );
                      },
                      a: ({ href, children }) => (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="markdown-link text-blue-600 hover:underline"
                        >
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {msg.text}
                  </ReactMarkdown>

                  {/* 이미지 갤러리 */}
                  {msg.images && msg.images.length > 0 && (
                    <div className="image-gallery mt-3 space-y-3">
                      {msg.images.map((img, idx) => {
                        // @ts-ignore
                        let base64ForDisplay = typeof img === 'string' ? img : img?.base64 || '';
                        let isValidBase64 =
                          base64ForDisplay.startsWith('data:image/') ||
                          base64ForDisplay.startsWith('data:application/');

                        return (
                          <div key={idx} className="border border-gray-200 p-2 rounded">
                            <div className="font-medium text-sm mb-2">이미지 {idx + 1}</div>

                            {isValidBase64 ? (
                              <>
                                <div className="text-center">
                                  <img
                                    src={base64ForDisplay}
                                    alt={`이미지 ${idx + 1}`}
                                    className="mx-auto my-2 max-w-full max-h-[300px] object-contain rounded cursor-pointer"
                                    loading="eager"
                                    onClick={() => {
                                      const newWindow = window.open();
                                      if (newWindow) {
                                        newWindow.document.write(`
                                          <html>
                                            <head><title>이미지 ${idx + 1}</title></head>
                                            <body style="margin:0; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f0f0f0;">
                                              <img src="${base64ForDisplay}" style="max-width:100%; max-height:100%; object-fit:contain;" alt="이미지 ${
                                          idx + 1
                                        }">
                                            </body>
                                          </html>
                                        `);
                                      }
                                    }}
                                  />
                                </div>

                                <div className="mt-2 text-xs text-gray-500 text-center">
                                  클릭하면 새 탭에서 확대됩니다.
                                </div>
                              </>
                            ) : (
                              <div className="p-3 bg-red-100 text-red-700 text-center rounded">
                                <p>이미지를 표시할 수 없습니다</p>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                {msg.sender === 'bot' && (
                  <div className="w-full flex justify-end">
                    <MessageActions content={msg.text} />
                  </div>
                )}
              </div>

              {msg.sender === 'user' && (
                <div className="flex-shrink-0 ml-2">
                  <User size={24} className="text-blue-500" />
                </div>
              )}
            </div>
          ))}
          {isStreaming && (
            <div className="flex items-center space-x-1 ml-1">
              <div className="animate-spin">
                <Loader2 size={20} />
              </div>
              <p className="text-base">답변 생성 중...</p>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area */}
      <div className="p-4 border-t border-gray-200">
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyPress}
            placeholder="메시지를 입력하세요... (Shift+Enter로 줄바꿈)"
            className="w-full p-4 pr-20 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none overflow-hidden no-scrollbar"
            disabled={isStreaming}
            rows={1}
            style={{ lineHeight: '1.5rem' }} // 24px
          />
          <div className="absolute inset-y-0 right-0 flex items-center pr-2">
            {isStreaming ? (
              <button
                onClick={handleStopStreaming}
                className="p-2 bg-red-500 text-white rounded-lg hover:bg-red-600 focus:outline-none"
                title="중지"
              >
                <Square size={20} />
              </button>
            ) : (
              <button
                onClick={handleSendMessage}
                className="p-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 focus:outline-none disabled:bg-gray-300"
                disabled={!input.trim()}
                title="전송"
              >
                <Send size={20} />
              </button>
            )}
          </div>
        </div>

        {/* 선택된 파일 표시 */}
        {checkedFiles.length > 0 && (
          <div className="mt-2 text-xs text-gray-500">
            <span>선택된 파일: {checkedFiles.length}개</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {checkedFiles.map((file, index) => (
                <span
                  key={index}
                  className="bg-gray-100 px-2 py-0.5 rounded-full truncate max-w-[150px]"
                >
                  {file}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CenterBox;
