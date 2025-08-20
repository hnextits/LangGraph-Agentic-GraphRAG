import React, { useState, useEffect } from 'react';
import { Box, Typography, IconButton, Button, Paper, Grid, Divider, List, ListItem, ListItemButton, ListItemIcon, ListItemText, CircularProgress } from '@mui/material';
import KeyboardDoubleArrowLeftIcon from '@mui/icons-material/KeyboardDoubleArrowLeft';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import EditIcon from '@mui/icons-material/Edit';
import GraphicEqIcon from '@mui/icons-material/GraphicEq'; // AI 오디오 오버뷰
import OndemandVideoIcon from '@mui/icons-material/OndemandVideo'; // 동영상 개요
import AccountTreeIcon from '@mui/icons-material/AccountTree'; // 마인드맵
import ArticleIcon from '@mui/icons-material/Article'; // 요약
import DescriptionIcon from '@mui/icons-material/Description'; // 요약 히스토리
import api from '../api';
import SummaryModal from './SummaryModal';

// A styled component for the feature tiles
const FeatureTile = ({ icon, title, color, bgColor, sx }) => (
  <Paper
    elevation={2}
    sx={{
      ...sx,
      height: '100%',
      padding: '16px',
      textAlign: 'left',
      backgroundColor: bgColor,
      color: color,
      borderRadius: '12px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      cursor: 'pointer',
      '&:hover': {
        opacity: 0.9,
      },
    }}
  >
    <Box display="flex" justifyContent="space-between" alignItems="center">
        {icon}
        <IconButton size="small" sx={{ color: 'inherit' }}><MoreVertIcon /></IconButton>
    </Box>
    <Typography sx={{ fontWeight: 'bold', mt: 2 }}>{title}</Typography>
  </Paper>
);

const Rightbox = ({ collapsed = false, onToggleCollapse = () => {} }) => {
  // 선택된 파일 목록을 App 컴포넌트로부터 받아오기 위한 상태
  const [checkedFiles, setCheckedFiles] = useState([]);
  // 요약 모달 상태
  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  // 요약 내용 상태
  const [summaryContent, setSummaryContent] = useState('');
  // 로딩 상태
  const [isLoading, setIsLoading] = useState(false);
  // 요약 히스토리 상태
  const [summaryHistory, setSummaryHistory] = useState([]);
  // 현재 선택된 요약 정보
  const [currentSummary, setCurrentSummary] = useState({
    summary: '',
    files: [],
    timestamp: ''
  });

  // 전역 이벤트 리스너를 통해 체크된 파일 목록 받기
  useEffect(() => {
    const handleCheckedFilesUpdate = (event) => {
      if (event.detail && Array.isArray(event.detail.files)) {
        setCheckedFiles(event.detail.files);
      }
    };

    window.addEventListener('checkedFilesUpdated', handleCheckedFilesUpdate);
    return () => {
      window.removeEventListener('checkedFilesUpdated', handleCheckedFilesUpdate);
    };
  }, []);

  // 요약 버튼 클릭 핸들러
  const handleSummarize = async () => {
    if (checkedFiles.length === 0) {
      alert('요약할 파일을 선택해주세요.');
      return;
    }

    setIsLoading(true);
    setSummaryModalOpen(true);
    setSummaryContent('');

    try {
      const response = await api.post('/api/summary/summarize', {
        file_names: checkedFiles
      });

      const newSummary = {
        summary: response.data.summary,
        files: response.data.files,
        timestamp: response.data.timestamp
      };

      setSummaryContent(response.data.summary);
      setCurrentSummary(newSummary);
      
      // 히스토리에 추가
      setSummaryHistory(prev => [newSummary, ...prev]);
    } catch (error) {
      console.error('요약 생성 중 오류 발생:', error);
      setSummaryContent('요약 생성 중 오류가 발생했습니다. 다시 시도해주세요.');
    } finally {
      setIsLoading(false);
    }
  };

  // 요약 모달 닫기 핸들러
  const handleCloseSummaryModal = () => {
    setSummaryModalOpen(false);
  };

  // 히스토리 항목 클릭 핸들러
  const handleHistoryItemClick = (summary) => {
    setCurrentSummary(summary);
    setSummaryContent(summary.summary);
    setSummaryModalOpen(true);
  };

  return (
    <div id="rightbox" style={{width: collapsed ? '48px' : '95%', height: '95%', border: '1px solid #e0e0e0', borderRadius: '15px', overflow: 'hidden', display: 'flex', flexDirection: 'column'}}>
      <Box
        sx={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: '#fff',
          overflow: 'hidden',
        }}
      >
        {/* Panel Header */}
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: collapsed ? '8px 4px' : '8px 16px',
            borderBottom: '1px solid #e0e0e0',
            flexShrink: 0,
            minHeight: '52px', // 헤더 높이 고정
          }}
        >
          {!collapsed && (
            <Typography variant="h6" component="h2" sx={{ fontWeight: 'bold', fontSize: '1rem' }}>
            스튜디오
           </Typography>
          )}
          <IconButton size="small" onClick={onToggleCollapse}>
            {collapsed ? <KeyboardDoubleArrowLeftIcon /> : <KeyboardDoubleArrowLeftIcon style={{transform:'rotate(180deg)'}} />}
          </IconButton>
        </Box>

        {/* Scrollable Content Area */}
        {!collapsed && (
         <Box sx={{ flexGrow: 1, overflowY: 'auto', padding: '16px' }}>
          {/* Feature Creation Tiles */}
          <Grid container spacing={2} alignItems="stretch">
            <Grid item xs={6} sx={{ display: 'flex', width: '45%'}}>
              <FeatureTile icon={<GraphicEqIcon />} title="AI 오디오 오버뷰" bgColor="#e3f2fd" color="#0d47a1" sx={{ flex: 1 }} />
            </Grid>
            <Grid item xs={6} sx={{ display: 'flex', width: '45%'}}>
              <FeatureTile icon={<OndemandVideoIcon />} title="동영상 개요" bgColor="#e8f5e9" color="#1b5e20" sx={{ flex: 1 }} />
            </Grid>
            <Grid item xs={6} sx={{ display: 'flex', width: '45%'}}>
              <FeatureTile icon={<AccountTreeIcon />} title="마인드맵" bgColor="#fce4ec" color="#880e4f" sx={{ flex: 1 }} />
            </Grid>
            <Grid item xs={6} sx={{ display: 'flex', width: '45%'}}>
              <FeatureTile 
                icon={<ArticleIcon />} 
                title="요약" 
                bgColor="#fff3e0" 
                color="#e65100" 
                sx={{ flex: 1, cursor: 'pointer' }} 
                onClick={handleSummarize}
              />
            </Grid>
          </Grid>

          <Divider sx={{ my: 3 }} />

          {/* 요약 히스토리 */}
          <Box>
            <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 'bold' }}>
              요약 히스토리
            </Typography>
            <List disablePadding>
              {summaryHistory.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
                  요약 히스토리가 없습니다.
                </Typography>
              ) : (
                summaryHistory.map((item, index) => (
                  <ListItem 
                    key={index} 
                    disablePadding 
                    sx={{ mb: 1, border: '1px solid #e0e0e0', borderRadius: 1 }}
                  >
                    <ListItemButton onClick={() => handleHistoryItemClick(item)}>
                      <ListItemIcon>
                        <DescriptionIcon />
                      </ListItemIcon>
                      <ListItemText 
                        primary={item.files.join(', ')} 
                        secondary={item.timestamp} 
                        primaryTypographyProps={{ 
                          noWrap: true, 
                          style: { maxWidth: '180px' } 
                        }}
                      />
                    </ListItemButton>
                  </ListItem>
                ))
              )}
            </List>
          </Box>
        </Box>
        )}

        {/* 요약 버튼 */}
        <Box sx={{ padding: '16px', borderTop: '1px solid #e0e0e0', flexShrink: 0 }}>
          <Button 
            fullWidth 
            variant="outlined" 
            startIcon={isLoading ? <CircularProgress size={20} /> : <ArticleIcon />}
            onClick={handleSummarize}
            disabled={isLoading || checkedFiles.length === 0}
          >
            {isLoading ? '요약 생성 중...' : '요약 생성'}
          </Button>
        </Box>
      </Box>

      {/* 요약 모달 */}
      <SummaryModal 
        open={summaryModalOpen}
        onClose={handleCloseSummaryModal}
        summary={summaryContent}
        isLoading={isLoading}
        files={currentSummary.files}
        timestamp={currentSummary.timestamp}
      />
    </div>  
  );
};

export default Rightbox;
