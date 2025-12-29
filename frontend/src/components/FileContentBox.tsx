"use client";

import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';

interface FileContentBoxProps {
  content: string;
  forceMarkdown?: boolean;
}

const FileContentBox: React.FC<FileContentBoxProps> = ({ content, forceMarkdown = false }) => {
  const [fileType, setFileType] = useState<'text' | 'markdown' | 'code' | 'image'>('text');
  const [language, setLanguage] = useState<string>('');
  
  useEffect(() => {
    // 파일 내용 분석하여 타입 결정
    if (content.startsWith('data:image')) {
      setFileType('image');
    } else if (
      forceMarkdown ||
      content.match(/^```[a-z]*\n/m) ||
      content.includes('# ') ||
      content.includes('## ') ||
      content.includes('- ') ||
      content.includes('* ') ||
      content.includes('<table') ||
      content.includes('<tr') ||
      content.includes('<td') ||
      content.trim().startsWith('###')
    ) {
      setFileType('markdown');
    } else if (content.includes('function ') || content.includes('class ') || content.includes('import ') || content.includes('from ') || content.includes('def ')) {
      setFileType('code');
      
      // 코드 언어 추측
      if (content.includes('def ') || content.includes('import ') && content.includes('from ')) {
        setLanguage('python');
      } else if (content.includes('function ') || content.includes('const ') || content.includes('let ')) {
        setLanguage('javascript');
      } else {
        setLanguage('');
      }
    } else {
      setFileType('text');
    }
  }, [content, forceMarkdown]);

  // 이미지 파일 렌더링
  if (fileType === 'image') {
    return (
      <div className="flex justify-center items-center p-4">
        <img src={content} alt="File content" className="max-w-full max-h-[70vh] object-contain" />
      </div>
    );
  }

  // 마크다운 렌더링 (CenterBox와 동일한 스타일)
  if (fileType === 'markdown') {
    return (
      <div className="p-4 prose prose-sm max-w-none dark:prose-invert markdown-content markdown-body message">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
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
          {content}
        </ReactMarkdown>
      </div>
    );
  }

  // 코드 렌더링
  if (fileType === 'code') {
    return (
      <div className="p-0">
        <SyntaxHighlighter
          language={language || 'text'}
          style={vscDarkPlus as any}
          customStyle={{ margin: 0, borderRadius: 0 }}
          showLineNumbers={true}
        >
          {content}
        </SyntaxHighlighter>
      </div>
    );
  }

  // 일반 텍스트 렌더링
  return (
    <div className="p-4 whitespace-pre-wrap font-mono text-sm">
      {content}
    </div>
  );
};

export default FileContentBox;
