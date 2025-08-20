import React, { useState, useEffect } from 'react';
import api from './api';
import './App.css';
import { Box, Grid } from '@mui/material';
import Leftbox from './Contents/Leftbox';
import Centerbox from './Contents/Centerbox';
import Rightbox from './Contents/Rightbox';
import FileContentBox from './Contents/FileContentBox'; // Import the new component
import FileUploadModal from './Contents/FileUploadModal';

function App() {
  const [windowSize, setWindowSize] = useState({
    width: window.innerWidth,
    height: window.innerHeight
  });

  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [fileUploadModalOpen, setFileUploadModalOpen] = useState(false);





  const handleFileUploadModalOpen = () => setFileUploadModalOpen(true);
  const handleFileUploadModalClose = () => setFileUploadModalOpen(false);

  const handleFilesAdd = async (addedFiles) => {
    const formData = new FormData();
    addedFiles.forEach(file => {
      formData.append('files', file);
    });

    try {
      const response = await api.post('/api/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      // 파일 추가 성공 시 모달을 닫습니다.
      handleFileUploadModalClose();
      
      // 파일 업로드 완료 이벤트 발생
      console.log('파일 업로드 완료, 파일 목록 새로고침 이벤트 발생');
      window.dispatchEvent(new CustomEvent('fileUploadComplete', {
        detail: { tasks: response.data.tasks }
      }));

    } catch (error) {
      console.error('파일 업로드 실패:', error);
      alert('파일 업로드에 실패했습니다. 서버 로그를 확인해주세요.');
    }
  };

  // 반응형 디자인을 위한 창 크기 감지
  useEffect(() => {
    const handleResize = () => {
      setWindowSize({
        width: window.innerWidth,
        height: window.innerHeight
      });
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // 반응형 레이아웃 설정
  const isMobile = windowSize.width < 768;
  const isTablet = windowSize.width >= 768 && windowSize.width < 1024;

  // 각 패널 너비 계산
  const leftWidth = leftCollapsed ? (isMobile ? '0' : '48px') : (isMobile ? '100%' : isTablet ? '30%' : '25%');
  const rightWidth = rightCollapsed ? (isMobile ? '0' : '48px') : (isMobile ? '100%' : isTablet ? '30%' : '25%');

  return (
    <div className="App" style={{
      display: 'flex',
      flexDirection: isMobile ? 'column' : 'row',
      height: '100vh',
      width: '100%',
      overflow: 'hidden',
      gap: '5px' // Add gap between panels
    }}>
      {/* 왼쪽 영역 */}
      <div style={{
        width: leftWidth,
        flexShrink: 0, // Prevent shrinking
        height: isMobile ? '33%' : '100%',
        overflow: 'hidden',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center'
      }}>
        <Leftbox 
          collapsed={leftCollapsed}
          onToggleCollapse={() => setLeftCollapsed(prev=>!prev)}
          onFileUploadClick={handleFileUploadModalOpen}
        />
      </div>

      {/* 중앙 영역 */}
      <div style={{
        flex: 1,
        height: isMobile ? '34%' : '100%',
        overflow: 'hidden',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center'
      }}>
        <Centerbox />
      </div>

      {/* 오른쪽 영역 - 모바일에서는 맨 아래, 태블릿에서는 숨김, 데스크탑에서만 표시 */}
      <div style={{
        width: rightWidth,
        flexShrink: 0, // Prevent shrinking
        height: isMobile ? '33%' : '100%',
        overflow: 'hidden',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center'
      }}>
        <Rightbox 
          collapsed={rightCollapsed}
          onToggleCollapse={() => setRightCollapsed(prev=>!prev)}
        />
      </div>

      <FileUploadModal 
        open={fileUploadModalOpen} 
        handleClose={handleFileUploadModalClose} 
        onFilesAdd={handleFilesAdd}
      />
    </div>
  );
}

export default App;
