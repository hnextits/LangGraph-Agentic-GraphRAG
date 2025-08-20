import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import '../MarkdownMessage.css'; // MarkdownMessage의 스타일을 재사용

const FileContentBox = ({ content }) => {
  return (
    <div className="markdown-content" style={{ height: '100%', overflowY: 'auto', padding: '16px', textAlign: 'left' }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 테이블 스타일링
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
  );
};

export default FileContentBox;
