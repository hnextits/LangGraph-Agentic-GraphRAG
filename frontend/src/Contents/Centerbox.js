import React, { useState, useRef, useEffect } from 'react';
import { Box, TextField, Button, Typography, Stack, CircularProgress, IconButton } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import MarkdownMessage from '../MarkdownMessage';
import api from '../api';
import 'katex/dist/katex.min.css';

const Centerbox = () => {
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sources] = useState([]);
  const abortControllerRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages]);



  const handleSend = async () => {
    if (input.trim() === '' || isLoading) return;

    const userMessage = { sender: 'user', text: input };
    setMessages(prevMessages => [...prevMessages, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // HTTP API 호출 - api.js의 axios 인스턴스 사용
      abortControllerRef.current = new AbortController();
      
      const response = await api.post('/api/v1/chat', {
        query: input,
        sources: sources
      }, {
        signal: abortControllerRef.current.signal
      });

      // axios는 자동으로 JSON 파싱하고 에러 상태 처리함
      const data = response.data;
      
      // 백엔드 응답 형식에 맞게 처리
      const botMessage = {
        sender: 'bot',
        text: data.answer || '응답을 받을 수 없습니다.',
        images: data.images || []
      };
      
      setMessages(prevMessages => [...prevMessages, botMessage]);
    } catch (error) {
      console.error('API 호출 오류:', error);
      const errorMessage = { sender: 'bot', text: '메시지 전송 중 오류가 발생했습니다.' };
      setMessages(prevMessages => [...prevMessages, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Box
      id="centerbox"
      sx={{
        width: '100%',
        height: '95%',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: '#f8f9fa', // Light gray background for the whole chat area
        borderRadius: '15px',
        overflow: 'hidden',
        border: '1px solid #e0e0e0'
      }}
    >
      {/* Message Display Area */}
      <Box sx={{ flexGrow: 1, overflow: 'auto', p: 2 }}>
        <Stack spacing={2}>
          {messages.map((msg, index) => (
            <MarkdownMessage
              key={index}
              text={{
                content: msg.text,
                images: msg.images || []
              }}
              isUser={msg.sender === 'user'}
            />
          ))}
          {isLoading && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ ml: 1 }}>
              <CircularProgress size={20} />
              <Typography variant="body1">답변 생성 중...</Typography>
            </Stack>
          )}
          <div ref={messagesEndRef} />
        </Stack>
      </Box>

      {/* Input Area */}
      <Box sx={{ p: 2, borderTop: '1px solid #e0e0e0', backgroundColor: '#fff' }}>
        
        <Stack direction="row" spacing={1}>
          <TextField
            fullWidth
            variant="outlined"
            placeholder="질문을 입력하세요..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && !isLoading && handleSend()}
            disabled={isLoading}
            sx={{ 
              '& .MuiOutlinedInput-root': {
                borderRadius: '20px',
              },
            }}
          />
          <IconButton color="primary" onClick={handleSend} disabled={isLoading}>
            <SendIcon />
          </IconButton>
        </Stack>
      </Box>
    </Box>
  );
};

export default Centerbox;
