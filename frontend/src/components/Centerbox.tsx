import { useState, useEffect, useRef, KeyboardEvent, useContext } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import api from '@/lib/api';
import { FileContext } from '@/contexts/FileContext';

// 아이콘 임포트
import {
  Send,
  Loader2,
  User,
  Bot
} from 'lucide-react';

interface Message {
  sender: 'user' | 'bot';
  text: string;
  images?: string[];
}

interface CenterboxProps {}

const Centerbox: React.FC<CenterboxProps> = () => {
  const { checkedFiles } = useContext(FileContext);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

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


  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value);
  };

  const handleKeyPress = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !isLoading) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleSendMessage = async () => {
    if (input.trim() === '' || isLoading) return;

    const userMessage: Message = { sender: 'user', text: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // HTTP API 호출
      abortControllerRef.current = new AbortController();
      
      const response = await api.post('/api/v1/chat', {
        query: input,
        sources: checkedFiles
      }, {
        signal: abortControllerRef.current.signal as any
      });

      // 백엔드 응답 형식에 맞게 처리
      const botMessage: Message = {
        sender: 'bot',
        text: (response.data as any)?.answer || '응답을 받을 수 없습니다.',
        images: (response.data as any)?.images || []
      };
      
      setMessages(prev => [...prev, botMessage]);
    } catch (error) {
      console.error('API 호출 오류:', error);
      
      const errorMessage: Message = {
        sender: 'bot',
        text: '메시지 전송 중 오류가 발생했습니다.'
      };
      
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div
      id="centerbox"
      className="w-full h-[95%] flex flex-col bg-[#f8f9fa] rounded-[15px] overflow-hidden border border-[#e0e0e0]"
    >
      {/* Message Display Area */}
      <div className="flex-grow overflow-auto p-2">
        <div className="flex flex-col space-y-2">
          {messages.map((msg, index) => (
            <div key={index} className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'} mb-4`}>
              {msg.sender === 'bot' && (
                <div className="flex-shrink-0 mr-2">
                  <Bot size={24} className="text-blue-500" />
                </div>
              )}
              
              <div className={`max-w-[80%] rounded-lg p-3 ${
                msg.sender === 'user' 
                  ? 'bg-blue-500 text-white' 
                  : 'bg-white border border-gray-200'
              }`}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    // 테이블 스타일링 개선
                    table: ({ node, ...props }) => (
                      <div className="table-container overflow-x-auto my-2">
                        <table className="markdown-table border-collapse w-full" {...props} />
                      </div>
                    ),
                    thead: (props) => <thead className="markdown-thead bg-[#f5f7fa]" {...props} />,
                    tbody: (props) => <tbody className="markdown-tbody" {...props} />,
                    tr: (props) => <tr className="markdown-tr border-b border-gray-200 hover:bg-gray-50" {...props} />,
                    th: (props) => <th className="markdown-th p-2 text-left font-semibold border-b-2 border-gray-300" {...props} />,
                    td: (props) => <td className="markdown-td p-2 border-gray-200" {...props} />,
                    // 코드 블록
                    code: ({ node, inline, className, children, ...props }) => {
                      const match = /language-(.*)/.exec(className || '');
                      const language = match ? match[1] : '';
                      
                      if (inline) {
                        return <code className="inline-code px-1 py-0.5 rounded bg-gray-100 text-red-500" {...props}>{children}</code>;
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
                    // 링크 (새 탭에서 열기)
                    a: ({ href, children }) => (
                      <a href={href} target="_blank" rel="noopener noreferrer" className="markdown-link text-blue-600 hover:underline">
                        {children}
                      </a>
                    )
                  }}
                >
                  {msg.text}
                </ReactMarkdown>
                
                {/* 이미지 갤러리 */}
                {msg.images && msg.images.length > 0 && (
                  <div className="image-gallery mt-3 space-y-3">
                    {msg.images.map((img, idx) => {
                      // 이미지 데이터 처리
                      // @ts-ignore - 이미지 타입 정의 문제 해결
                      let base64ForDisplay = typeof img === 'string' ? img : img?.base64 || '';
                      let isValidBase64 = base64ForDisplay.startsWith('data:image/') || 
                                        base64ForDisplay.startsWith('data:application/');
                      
                      return (
                        <div key={idx} className="border border-gray-200 p-2 rounded">
                          <div className="font-medium text-sm mb-2">
                            이미지 {idx + 1}
                          </div>
                          
                          {isValidBase64 ? (
                            <>
                              <div className="text-center">
                                <img 
                                  src={base64ForDisplay}
                                  alt={`이미지 ${idx + 1}`}
                                  className="mx-auto my-2 max-w-full max-h-[300px] object-contain rounded cursor-pointer"
                                  loading="eager"
                                  onClick={() => {
                                    // 이미지 클릭 시 새 탭에서 열기
                                    const newWindow = window.open();
                                    if (newWindow) {
                                      newWindow.document.write(`
                                        <html>
                                          <head><title>이미지 ${idx+1}</title></head>
                                          <body style="margin:0; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f0f0f0;">
                                            <img src="${base64ForDisplay}" style="max-width:100%; max-height:100%; object-fit:contain;" alt="이미지 ${idx+1}">
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
              
              {msg.sender === 'user' && (
                <div className="flex-shrink-0 ml-2">
                  <User size={24} className="text-blue-500" />
                </div>
              )}
            </div>
          ))}
          {isLoading && (
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
      <div className="p-2 border-t border-[#e0e0e0] bg-white">
        <div className="flex space-x-1">
          <input
            className="w-full rounded-[20px] border border-gray-300 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="질문을 입력하세요..."
            value={input}
            onChange={handleInputChange}
            onKeyPress={handleKeyPress}
            disabled={isLoading}
          />
          <button 
            className="text-blue-500 p-2 rounded-full hover:bg-blue-50 disabled:text-gray-400"
            onClick={handleSendMessage} 
            disabled={isLoading || input.trim() === ''}
          >
            {isLoading ? (
              <Loader2 size={20} className="animate-spin" />
            ) : (
              <Send size={20} />
            )}
          </button>
        </div>
        
        {/* 선택된 파일 표시 */}
        {checkedFiles.length > 0 && (
          <div className="mt-2 text-xs text-gray-500">
            <span>선택된 파일: {checkedFiles.length}개</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {checkedFiles.map((file, index) => (
                <span key={index} className="bg-gray-100 px-2 py-0.5 rounded-full truncate max-w-[150px]">
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

export default Centerbox;
