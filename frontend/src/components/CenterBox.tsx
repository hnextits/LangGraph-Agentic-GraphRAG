import React, { useState, useEffect, useRef, KeyboardEvent, useContext, useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkEmoji from 'remark-emoji';
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import python from 'react-syntax-highlighter/dist/cjs/languages/prism/python';
import javascript from 'react-syntax-highlighter/dist/cjs/languages/prism/javascript';
import json from 'react-syntax-highlighter/dist/cjs/languages/prism/json';
import markdown from 'react-syntax-highlighter/dist/cjs/languages/prism/markdown';
import bash from 'react-syntax-highlighter/dist/cjs/languages/prism/bash';

SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('javascript', javascript);
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('markdown', markdown);
SyntaxHighlighter.registerLanguage('bash', bash);
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import api from '@/lib/api';
import { FileContext } from '@/contexts/FileContext';
import MessageActions from './MessageActions';
import ChatInit from './ChatInit';
import ImageSlider from './ImageSlider';
import ImageZoomModal from './ImageZoomModal';

// 아이콘 임포트
import { ArrowUp, Loader2, CircleUserRound, Bot, Square } from 'lucide-react';

// 이미지 객체 인터페이스 정의
interface ImageData {
  base64: string;
  type?: string;
  alt?: string;
  title?: string;
}

interface Message {
  sender: 'user' | 'bot';
  text: string;
  images?: (string | ImageData)[];
  sources?: string[];
  timestamp?: Date;
}

interface CenterBoxProps {
  isFiles: boolean;
}

const CenterBox: React.FC<CenterBoxProps> = React.memo(({ isFiles }) => {
  const { checkedFilenames, checkedFileUuids } = useContext(FileContext);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // 이미지 모달 상태
  const [zoomModalOpen, setZoomModalOpen] = useState(false);
  const [zoomImages, setZoomImages] = useState<string[]>([]);
  const [zoomInitialIndex, setZoomInitialIndex] = useState(0);

  const handleOpenZoom = (images: string[], index: number) => {
    setZoomImages(images);
    setZoomInitialIndex(index);
    setZoomModalOpen(true);
  };

  // 메시지 목록이 업데이트될 때마다 스크롤을 맨 아래로 이동
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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
      const userMessage: Message = { 
        sender: 'user', 
        text: input,
        timestamp: new Date()
      };
      setMessages(prev => [...prev, userMessage]);
      setInput('');
      setIsStreaming(true);

      try {
        const effectiveSources = checkedFileUuids.length > 0 ? checkedFileUuids : checkedFilenames;

        const response = await api.postChat(input, effectiveSources);
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
          timestamp: new Date()
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
        timestamp: new Date()
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
              timestamp: new Date()
            };
            console.log('Bot response with images:', result.images);
            setMessages(prev => [...prev, finalMessage]);
            setIsStreaming(false);
            setCurrentTaskId(null);
          } else if (task.status === 'failed') {
            stopPolling();
            const errorMessage: Message = {
              sender: 'bot',
              text: `오류가 발생했습니다: ${task.error || '알 수 없는 오류'}`,
              timestamp: new Date()
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
            timestamp: new Date()
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

  const hasSelectedFiles = checkedFilenames.length > 0;
  const selectedFilesLine = checkedFilenames.join(', ');

  return (
    <div
      id="centerbox"
      className="w-full h-full flex flex-col bg-[#f8f9fa] rounded-[15px] overflow-hidden border border-[#e0e0e0]"
    >
      <div
        className={`flex items-center ${'justify-between px-4 py-2'}  border-b border-gray-200 flex-shrink-0 min-h-[52px]`}
      >
        {<h2 className="text-lg font-bold">채팅</h2>}
      </div>

      {/* Message Display Area */}
      <div className="flex-grow overflow-hidden relative">
        <div className="absolute inset-0 overflow-y-auto p-4 no-scrollbar">
          {(!isFiles || messages.length === 0) ? (
            <div className="h-full flex items-center justify-center">
              <ChatInit />
            </div>
          ) : (
            <div className="flex flex-col space-y-4">
              {messages.map((msg, index) => (
                <div
                  key={index}
                  className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {msg.sender === 'bot' && (
                    <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-gray-100 mr-2">
                      <Bot size={24} className="text-gray-600" />
                    </div>
                  )}

                  <div
                    className={`max-w-[80%] flex flex-col ${
                      msg.sender === 'user' ? 'items-end' : 'items-start'
                    }`}
                  >
                    {/* 타임스탬프 */}
                    <div className="text-xs text-gray-400 mb-1 px-1">
                      {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString('ko-KR', {
                        hour: '2-digit',
                        minute: '2-digit'
                      }) : ''}
                    </div>
                    
                    <div
                      className={`rounded-lg p-3 ${
                        msg.sender === 'user'
                          ? 'bg-blue-500 text-white'
                          : 'bg-white border border-gray-200'
                      }`}
                    >
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkEmoji as any]}
                        components={{
                          table: ({ node, ...props }) => (
                            <div className="table-container overflow-x-auto my-2">
                              <table className="markdown-table border-collapse w-full" {...props} />
                            </div>
                          ),
                          thead: props => (
                            <thead className="markdown-thead bg-[#f5f7fa]" {...props} />
                          ),
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

                      {/* 이미지 갤러리/슬라이더 */}
                      {msg.images && msg.images.length > 0 && (
                        <ImageSlider 
                          images={msg.images.map(img => {
                            if (typeof img === 'string') return img;
                            let b64 = (img as ImageData).base64 || '';
                            return b64.startsWith('data:') ? b64 : `data:image/png;base64,${b64}`;
                          })} 
                          onImageClick={(index) => {
                            const allUrls = msg.images!.map(img => {
                              if (typeof img === 'string') return img;
                              let b64 = (img as ImageData).base64 || '';
                              return b64.startsWith('data:') ? b64 : `data:image/png;base64,${b64}`;
                            });
                            handleOpenZoom(allUrls, index);
                          }}
                        />
                      )}
                    </div>
                    {msg.sender === 'bot' && (
                      <div className="w-full flex justify-end">
                        <MessageActions content={msg.text} />
                      </div>
                    )}
                  </div>

                  {msg.sender === 'user' && (
                    <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-blue-50 ml-2">
                      <CircleUserRound size={24} className="text-blue-500" />
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
          )}
        </div>
      </div>

      {/* Selected files indicator above prompt divider */}
      <div className="px-4 py-2 text-xs text-gray-600 bg-[#f8f9fa] flex flex-wrap gap-1 min-h-[40px] border-t border-gray-200">
        <span className="font-semibold whitespace-nowrap">선택된 파일:</span>
        <span className={`truncate ${hasSelectedFiles ? 'text-gray-700' : 'text-gray-400'}`}>
          {hasSelectedFiles ? selectedFilesLine : '없음'}
        </span>
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
            disabled={isStreaming || !isFiles}
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
                <ArrowUp size={20} />
              </button>
            )}
          </div>
        </div>

      </div>
      <ImageZoomModal 
        isOpen={zoomModalOpen}
        onClose={() => setZoomModalOpen(false)}
        images={zoomImages}
        initialIndex={zoomInitialIndex}
      />
    </div>
  );
});

export default CenterBox;
