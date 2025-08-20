import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import './MarkdownMessage.css';

const MarkdownMessage = ({ text, isUser }) => {
  // 텍스트가 객체인 경우 content 속성을 사용하고, 문자열인 경우 그대로 사용
  const content = typeof text === 'object' ? text.content || '' : text || '';
  
  // 이미지가 있는 경우 (text가 객체이고 images 속성이 있는 경우)
  // 백엔드에서 받은 이미지 배열 (문자열 또는 객체일 수 있음)
  const rawImages = text?.images || [];

  // 렌더링을 위해 이미지 데이터를 객체 형태로 정규화합니다.
  const images = rawImages.map((img, idx) => {
    if (typeof img === 'string') {
      // Base64 문자열인 경우 객체로 변환
      return {
        base64: img,
        title: `이미지 ${idx + 1}`,
        path: 'N/A', // 경로 정보가 없으므로 N/A 처리
      };
    }
    // 이미 객체 형태인 경우 그대로 반환
    return img;
  });

  return (
    <div className={`markdown-message ${isUser ? 'user' : 'bot'}`}>
      <div className="markdown-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // 테이블 스타일링 개선
            table: ({ node, ...props }) => (
              <div className="table-container">
                <table className="markdown-table" {...props} />
              </div>
            ),
            thead: (props) => <thead className="markdown-thead" {...props} />,
            tbody: (props) => <tbody className="markdown-tbody" {...props} />,
            tr: (props) => <tr className="markdown-tr" {...props} />,
            th: (props) => <th className="markdown-th" {...props} />,
            td: (props) => <td className="markdown-td" {...props} />,
            // 코드 블록
            code: ({ node, inline, className, children, ...props }) => {
              const match = /language-(.*)/.exec(className || '');
              const language = match ? match[1] : '';
              
              if (inline) {
                return <code className="inline-code" {...props}>{children}</code>;
              }
              
              return (
                <div className="code-block-wrapper">
                  {language && (
                    <div className="code-header">
                      <span className="language-tag">{language}</span>
                    </div>
                  )}
                  <SyntaxHighlighter
                    style={vscDarkPlus}
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
              <a href={href} target="_blank" rel="noopener noreferrer" className="markdown-link">
                {children}
              </a>
            )
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
      
      {/* 별도 이미지 렌더링 */}
      {!isUser && images && images.length > 0 && (
        <div className="image-gallery">
          
          {images.map((img, idx) => {
            // 이미지 데이터 로깅
            console.log(`Rendering image ${idx}:`, {
              hasBase64: !!img.base64,
              base64Length: img.base64 ? img.base64.length : 0,
              base64Start: img.base64 ? img.base64.substring(0, 50) : 'none',
              base64HasDataPrefix: img.base64 ? img.base64.startsWith('data:') : false,
              title: img.title,
              path: img.original_path || '없음'
            });
            
            // 백엔드에서 처리된 base64 문자열 그대로 사용
            let base64ForDisplay = img.base64 || '';
            let isValidBase64 = base64ForDisplay.startsWith('data:image/') || 
                               base64ForDisplay.startsWith('data:application/');
            
            return (
              <div key={idx}>
                <div style={{ marginBottom: '10px', border: '1px solid #ddd', padding: '10px', borderRadius: '4px' }}>
                  <div style={{ marginBottom: '8px', fontWeight: 'bold' }}>
                    이미지 {idx + 1}
                  </div>
                  
                  {isValidBase64 ? (
                    <>
                      <div style={{ position: 'relative', textAlign: 'center' }}>
                        <img 
                          src={base64ForDisplay}
                          alt={img.title || `이미지 ${idx + 1}`}
                          className="markdown-image"
                          loading="eager"
                          onError={(e) => {
                            console.error(`이미지 ${idx+1} 로드 오류:`, e);
                            console.error(`이미지 ${idx+1} base64 데이터:`, base64ForDisplay.substring(0, 100));
                            e.target.style.display = 'none';
                            e.target.parentNode.innerHTML += `<div style="padding: 20px; background: #f8d7da; color: #721c24; text-align: center; margin-top: 10px;">
                              <p>이미지 로드 오류</p>
                              <p>Base64 데이터 시작: ${base64ForDisplay.substring(0, 30)}...</p>
                            </div>`;
                          }}
                          onLoad={(e) => {
                            console.log(`이미지 ${idx+1} 로드 성공`, e.target.naturalWidth, 'x', e.target.naturalHeight);
                          }}
                          style={{
                            display: 'block',
                            margin: '10px auto',
                            maxWidth: '100%',
                            maxHeight: '300px',
                            objectFit: 'contain',
                            borderRadius: '4px',
                            cursor: 'pointer'
                          }}
                          onClick={() => {
                            // 이미지 클릭 시 새 탭에서 열기
                            const newWindow = window.open();
                            newWindow.document.write(`
                              <html>
                                <head><title>${img.title || `이미지 ${idx+1}`}</title></head>
                                <body style="margin:0; display:flex; justify-content:center; align-items:center; min-height:100vh; background:#f0f0f0;">
                                  <img src="${base64ForDisplay}" style="max-width:100%; max-height:100%; object-fit:contain;" alt="${img.title || `이미지 ${idx+1}`}">
                                </body>
                              </html>
                            `);
                          }}
                        />
                      </div>
                      
                      <div style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
                        <div>파일 경로: {img.path || '알 수 없음'}</div>
                        <div>클릭하면 새 탭에서 확대됩니다.</div>
                      </div>
                    </>
                  ) : (
                    <div style={{ 
                      padding: '20px', 
                      background: '#f8d7da', 
                      color: '#721c24', 
                      textAlign: 'center',
                      borderRadius: '4px'
                    }}>
                      <p>이미지를 표시할 수 없습니다</p>
                      <p style={{ fontSize: '12px' }}>
                        Base64 데이터: {base64ForDisplay ? '있음' : '없음'} 
                        {base64ForDisplay && ` (${base64ForDisplay.length} chars)`}
                      </p>
                      <p style={{ fontSize: '12px' }}>경로: {img.path || '알 수 없음'}</p>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default MarkdownMessage;
