import React from 'react';
import { Box, Typography, IconButton, Paper, CircularProgress } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const SummaryModal = ({ open, onClose, summary, isLoading, files, timestamp }) => {
  if (!open) return null;

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
          width: '60%',
          height: '80%',
          maxWidth: '800px',
          maxHeight: '800px',
          display: 'flex',
          flexDirection: 'column',
          borderRadius: '8px',
          overflow: 'hidden',
        }}
      >
        {/* 헤더 */}
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '12px 16px',
            borderBottom: '1px solid #e0e0e0',
            backgroundColor: '#f5f5f5',
          }}
        >
          <Typography variant="h6" component="h2" sx={{ fontWeight: 'bold', fontSize: '1rem' }}>
            문서 요약 결과
          </Typography>
          <IconButton size="small" onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Box>

        {/* 요약 정보 */}
        <Box
          sx={{
            padding: '8px 16px',
            borderBottom: '1px solid #e0e0e0',
            backgroundColor: '#f9f9f9',
          }}
        >
          <Typography variant="body2" color="text.secondary">
            {timestamp && `생성 시간: ${timestamp}`}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {files && files.length > 0 && `요약 대상: ${files.join(', ')}`}
          </Typography>
        </Box>

        {/* 내용 */}
        <Box
          sx={{
            flexGrow: 1,
            padding: '16px',
            overflowY: 'auto',
            backgroundColor: '#ffffff',
          }}
        >
          {isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
              <CircularProgress />
            </Box>
          ) : (
            <Box sx={{ textAlign: 'left' }}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ node, ...props }) => <Typography variant="h4" gutterBottom sx={{ textAlign: 'left' }} {...props} />,
                  h2: ({ node, ...props }) => <Typography variant="h5" gutterBottom sx={{ textAlign: 'left' }} {...props} />,
                  h3: ({ node, ...props }) => <Typography variant="h6" gutterBottom sx={{ textAlign: 'left' }} {...props} />,
                  p: ({ node, ...props }) => <Typography variant="body1" paragraph sx={{ textAlign: 'left' }} {...props} />,
                  ul: ({ node, ...props }) => <Box component="ul" sx={{ pl: 2, textAlign: 'left' }} {...props} />,
                  ol: ({ node, ...props }) => <Box component="ol" sx={{ pl: 2, textAlign: 'left' }} {...props} />,
                  li: ({ node, ...props }) => <Typography component="li" variant="body1" sx={{ textAlign: 'left' }} {...props} />,
                  blockquote: ({ node, ...props }) => (
                    <Box
                      component="blockquote"
                      sx={{
                        borderLeft: '4px solid #ccc',
                        pl: 2,
                        py: 1,
                        my: 2,
                        bgcolor: 'rgba(0,0,0,0.03)',
                        textAlign: 'left'
                      }}
                      {...props}
                    />
                  ),
                  code: ({ node, inline, ...props }) => 
                    inline ? (
                      <Typography component="code" sx={{ backgroundColor: '#f5f5f5', p: 0.5, borderRadius: 1, fontFamily: 'monospace' }} {...props} />
                    ) : (
                      <Box 
                        component="pre" 
                        sx={{ 
                          backgroundColor: '#f5f5f5', 
                          p: 2, 
                          borderRadius: 1,
                          overflowX: 'auto',
                          textAlign: 'left',
                          '& code': { fontFamily: 'monospace' }
                        }}
                        {...props} 
                      />
                    ),
                  table: ({ node, ...props }) => (
                    <Box sx={{ overflowX: 'auto', my: 2 }}>
                      <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', textAlign: 'left' }} {...props} />
                    </Box>
                  ),
                  th: ({ node, ...props }) => (
                    <Box component="th" sx={{ borderBottom: '1px solid #ddd', p: 1, textAlign: 'left' }} {...props} />
                  ),
                  td: ({ node, ...props }) => (
                    <Box component="td" sx={{ borderBottom: '1px solid #ddd', p: 1, textAlign: 'left' }} {...props} />
                  ),
                }}
              >
                {summary || '요약 내용이 없습니다.'}
              </ReactMarkdown>
            </Box>
          )}
        </Box>
      </Paper>
    </Box>
  );
};

export default SummaryModal;
