import React from 'react';
import { Box, Typography, IconButton, Paper, CircularProgress, Chip } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import DescriptionIcon from '@mui/icons-material/Description';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkEmoji from 'remark-emoji';
import { useGetSummaryContent } from '@/queries';

// 타입 정의
interface SummaryModalProps {
  open: boolean;
  onClose: () => void;
  file: string;
}

const SummaryModal: React.FC<SummaryModalProps> = ({ open, onClose, file }) => {
  if (!open) return null;

  const { data, isLoading } = useGetSummaryContent(file);

  // 파일명에서 summary_ 제거 및 .md 제거
  const formatFileName = (fileName: string) => {
    let name = fileName.startsWith('summary_') ? fileName.substring(8) : fileName;
    while (name.endsWith('.md')) {
      name = name.slice(0, -3);
    }
    return name;
  };

  // 현재 시간
  const currentTime = new Date().toLocaleString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <Box
      sx={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 1300,
      }}
    >
      <Paper
        sx={{
          width: '90%',
          height: '90%',
          maxWidth: '1200px',
          maxHeight: '900px',
          display: 'flex',
          flexDirection: 'column',
          borderRadius: '12px',
          overflow: 'hidden',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.12)',
        }}
      >
        {/* 헤더 */}
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '12px 20px',
            borderBottom: '1px solid #e5e7eb',
            backgroundColor: '#ffffff',
          }}
        >
          <Typography variant="h6" component="h2" sx={{ fontWeight: 600, color: '#1f2937', fontSize: '1.125rem' }}>
            📄 문서 요약
          </Typography>
          <IconButton size="small" onClick={onClose} sx={{ '&:hover': { backgroundColor: '#f3f4f6' } }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>

        {/* 요약 정보 */}
        <Box
          sx={{
            padding: '8px 20px',
            borderBottom: '1px solid #e5e7eb',
            backgroundColor: '#f9fafb',
            display: 'flex',
            gap: 1.5,
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <DescriptionIcon sx={{ fontSize: '14px', color: '#3b82f6' }} />
            <Typography variant="caption" sx={{ color: '#4b5563', fontSize: '0.75rem' }}>
              {formatFileName(file)}
            </Typography>
          </Box>
          <Box sx={{ color: '#d1d5db', fontSize: '0.75rem' }}>•</Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <AccessTimeIcon sx={{ fontSize: '14px', color: '#6b7280' }} />
            <Typography variant="caption" sx={{ color: '#6b7280', fontSize: '0.75rem' }}>
              {currentTime}
            </Typography>
          </Box>
        </Box>

        {/* 내용 */}
        <Box
          sx={{
            flexGrow: 1,
            padding: '20px 24px',
            overflowY: 'auto',
            backgroundColor: '#ffffff',
            '&::-webkit-scrollbar': {
              width: '6px',
            },
            '&::-webkit-scrollbar-track': {
              backgroundColor: '#f9fafb',
            },
            '&::-webkit-scrollbar-thumb': {
              backgroundColor: '#d1d5db',
              borderRadius: '3px',
              '&:hover': {
                backgroundColor: '#9ca3af',
              },
            },
          }}
        >
          {isLoading ? (
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                height: '100%',
              }}
            >
              <CircularProgress />
            </Box>
          ) : (
            <Box sx={{ textAlign: 'left', lineHeight: 1.8 }}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkEmoji]}
                components={{
                  h1: ({ node, ...props }) => (
                    <Typography
                      variant="h5"
                      gutterBottom
                      sx={{
                        textAlign: 'left',
                        fontWeight: 700,
                        color: '#111827',
                        mt: 2.5,
                        mb: 1.5,
                        pb: 0.75,
                        borderBottom: '2px solid #e5e7eb',
                        fontSize: '1.5rem',
                      }}
                      {...props}
                    />
                  ),
                  h2: ({ node, ...props }) => (
                    <Typography
                      variant="h6"
                      gutterBottom
                      sx={{
                        textAlign: 'left',
                        fontWeight: 600,
                        color: '#1f2937',
                        mt: 2,
                        mb: 1.25,
                        fontSize: '1.25rem',
                      }}
                      {...props}
                    />
                  ),
                  h3: ({ node, ...props }) => (
                    <Typography
                      variant="subtitle1"
                      gutterBottom
                      sx={{
                        textAlign: 'left',
                        fontWeight: 600,
                        color: '#374151',
                        mt: 1.75,
                        mb: 0.75,
                        fontSize: '1.125rem',
                      }}
                      {...props}
                    />
                  ),
                  p: ({ node, ...props }) => (
                    <Typography
                      variant="body1"
                      paragraph
                      sx={{
                        textAlign: 'left',
                        color: '#374151',
                        lineHeight: 1.75,
                        mb: 1.5,
                        fontSize: '0.95rem',
                      }}
                      {...props}
                    />
                  ),
                  ul: ({ node, ...props }) => (
                    <Box component="ul" sx={{ pl: 3, textAlign: 'left', mb: 2 }} {...props} />
                  ),
                  ol: ({ node, ...props }) => (
                    <Box component="ol" sx={{ pl: 3, textAlign: 'left', mb: 2 }} {...props} />
                  ),
                  li: ({ node, ...props }) => (
                    <Typography
                      component="li"
                      variant="body2"
                      sx={{
                        textAlign: 'left',
                        color: '#4b5563',
                        mb: 0.5,
                        lineHeight: 1.7,
                        fontSize: '0.9rem',
                      }}
                      {...props}
                    />
                  ),
                  blockquote: ({ node, ...props }) => (
                    <Box
                      component="blockquote"
                      sx={{
                        borderLeft: '3px solid #3b82f6',
                        pl: 2,
                        py: 1,
                        my: 1.5,
                        bgcolor: '#f0f9ff',
                        textAlign: 'left',
                        borderRadius: '0 4px 4px 0',
                        fontStyle: 'italic',
                        color: '#1e40af',
                        fontSize: '0.9rem',
                      }}
                      {...props}
                    />
                  ),
                  code: ({ node, inline, ...props }) =>
                    inline ? (
                      <Typography
                        component="code"
                        sx={{
                          backgroundColor: '#fef3c7',
                          color: '#92400e',
                          px: 0.75,
                          py: 0.25,
                          borderRadius: '3px',
                          fontFamily: '"Fira Code", "Consolas", monospace',
                          fontSize: '0.85em',
                        }}
                        {...props}
                      />
                    ) : (
                      <Box
                        component="pre"
                        sx={{
                          backgroundColor: '#1f2937',
                          color: '#f3f4f6',
                          p: 2,
                          borderRadius: '6px',
                          overflowX: 'auto',
                          textAlign: 'left',
                          my: 1.5,
                          '& code': {
                            fontFamily: '"Fira Code", "Consolas", monospace',
                            fontSize: '0.85em',
                          },
                        }}
                        {...props}
                      />
                    ),
                  table: ({ node, ...props }) => (
                    <Box sx={{ overflowX: 'auto', my: 3 }}>
                      <Box
                        component="table"
                        sx={{
                          borderCollapse: 'collapse',
                          width: '100%',
                          textAlign: 'left',
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                        }}
                        {...props}
                      />
                    </Box>
                  ),
                  th: ({ node, ...props }) => (
                    <Box
                      component="th"
                      sx={{
                        borderBottom: '2px solid #d1d5db',
                        p: 1.5,
                        textAlign: 'left',
                        backgroundColor: '#f9fafb',
                        fontWeight: 600,
                        color: '#374151',
                      }}
                      {...props}
                    />
                  ),
                  td: ({ node, ...props }) => (
                    <Box
                      component="td"
                      sx={{
                        borderBottom: '1px solid #e5e7eb',
                        p: 1.5,
                        textAlign: 'left',
                        color: '#4b5563',
                      }}
                      {...props}
                    />
                  ),
                }}
              >
                {data || '📭 요약 내용이 없습니다.'}
              </ReactMarkdown>
            </Box>
          )}
        </Box>
      </Paper>
    </Box>
  );
};

export default SummaryModal;
