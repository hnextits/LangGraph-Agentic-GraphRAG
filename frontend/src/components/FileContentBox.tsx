"use client";

import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';

interface FileContentBoxProps {
  content: string;
}

const FileContentBox: React.FC<FileContentBoxProps> = ({ content }) => {
  const [fileType, setFileType] = useState<'text' | 'markdown' | 'code' | 'image'>('text');
  const [language, setLanguage] = useState<string>('');
  
  useEffect(() => {
    // 파일 내용 분석하여 타입 결정
    if (content.startsWith('data:image')) {
      setFileType('image');
    } else if (content.match(/^```[a-z]*\n/m) || content.includes('# ') || content.includes('## ') || content.includes('- ') || content.includes('* ')) {
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
  }, [content]);

  // 이미지 파일 렌더링
  if (fileType === 'image') {
    return (
      <div className="flex justify-center items-center p-4">
        <img src={content} alt="File content" className="max-w-full max-h-[70vh] object-contain" />
      </div>
    );
  }

  // 마크다운 렌더링
  if (fileType === 'markdown') {
    return (
      <div className="p-4 prose prose-sm max-w-none dark:prose-invert markdown-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({node, inline, className, children, ...props}) {
              const match = /language-(\w+)/.exec(className || '');
              return !inline && match ? (
                <SyntaxHighlighter
                  style={vscDarkPlus as any}
                  language={match[1]}
                  PreTag="div"
                  {...props}
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              ) : (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            },
            table({node, ...props}) {
              return (
                <div className="overflow-x-auto w-full">
                  <table className="markdown-table" {...props} />
                </div>
              );
            }
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
