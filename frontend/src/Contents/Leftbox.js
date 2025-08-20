import React, { useState, useEffect, useCallback } from 'react';
import { 
  Box, 
  List, 
  ListItem, 
  ListItemText, 
  Checkbox, 
  IconButton, 
  Button, 
  Typography, 
  LinearProgress, 
  ListItemIcon, 
  FormControlLabel,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent
} from '@mui/material';
import api, { API_URL } from '../api';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import SearchIcon from '@mui/icons-material/Search';
import KeyboardDoubleArrowRightIcon from '@mui/icons-material/KeyboardDoubleArrowRight';
import KeyboardDoubleArrowLeftIcon from '@mui/icons-material/KeyboardDoubleArrowLeft';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import DescriptionIcon from '@mui/icons-material/Description';
import ImageIcon from '@mui/icons-material/Image';
import CodeIcon from '@mui/icons-material/Code';
import CloseIcon from '@mui/icons-material/Close';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';

import SearchModal from './Searchbox';
import FileContentBox from './FileContentBox';

const Leftbox = ({ collapsed = false, onToggleCollapse = () => {}, onFileUploadClick }) => {
  const [sources, setSources] = useState([]); // 파일 목록 상태를 내부에서 관리
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [checkedFiles, setCheckedFiles] = useState([]); // 체크된 파일 목록 상태 관리
  const [checked, setChecked] = useState([]); // 체크된 항목의 인덱스를 저장하는 상태
  const [refreshTrigger, setRefreshTrigger] = useState(0); // 새로고침 트리거 상태

  // 체크된 파일 목록이 변경될 때마다 전역 이벤트 발생
  useEffect(() => {
    // 커스텀 이벤트를 통해 체크된 파일 목록 공유
    const event = new CustomEvent('checkedFilesUpdated', {
      detail: { files: checkedFiles }
    });
    window.dispatchEvent(event);
  }, [checkedFiles]);

  const [isLoading, setIsLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [fileContentModalOpen, setFileContentModalOpen] = useState(false);

  const fetchDocuments = useCallback(async () => {
    try {
      setIsLoading(true);
      console.log('파일 목록 새로고침 중...');
      const response = await api.get('/api/files');
      const data = response.data;
      // 백엔드는 파일 이름 문자열의 배열을 반환합니다. (예: ["file1.pdf", "file2.pdf"])
      // 각 문자열(doc)을 객체로 변환합니다.
      const formattedSources = data.files.map(doc => ({ 
        title: doc, // doc 자체가 파일 이름 문자열입니다.
        id: doc,    // doc을 고유 ID로 사용합니다.
        status: 'completed' 
      }));
      setSources(currentSources => {
        // 처리 중이거나 인덱싱 중인 항목 유지
        const processingSources = currentSources.filter(s => 
          s.status === 'processing' || s.status === 'indexing' || s.status === 'queued');
        const completedTitles = new Set(formattedSources.map(s => s.title));
        const uniqueProcessingSources = processingSources.filter(s => !completedTitles.has(s.title));
        return [...formattedSources, ...uniqueProcessingSources];
      });
      console.log('파일 목록 새로고침 완료');
    } catch (error) {
      console.error('파일 목록 가져오기 실패:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // refreshTrigger가 변경될 때마다 파일 목록을 새로고침
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments, refreshTrigger]);
  
  // 외부에서 새로고침을 트리거할 수 있는 함수
  const refreshFileList = useCallback(() => {
    setRefreshTrigger(prev => prev + 1); // 트리거 값 증가
  }, []);
  
  // 컴포넌트 마운트 시 파일 목록 새로고침 이벤트 리스너 등록
  useEffect(() => {
    // 파일 업로드 완료 후 새로고침을 위한 이벤트 리스너
    const handleFileUploadComplete = () => {
      console.log('파일 업로드 완료 이벤트 감지, 파일 목록 새로고침');
      refreshFileList();
    };
    
    // 이벤트 리스너 등록
    window.addEventListener('fileUploadComplete', handleFileUploadComplete);
    
    // 컴포넌트 언마운트 시 이벤트 리스너 제거
    return () => {
      window.removeEventListener('fileUploadComplete', handleFileUploadComplete);
    };
  }, [refreshFileList]);
  
  // 초기 로드 시 파일 목록 가져오기
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleProcessingStart = (tasks) => {
    const newSources = tasks.map(task => ({
      id: task.task_id,
      title: task.title,
      status: 'processing',
      taskId: task.task_id,
    }));
    setSources(prevSources => [...prevSources, ...newSources]);
  };

  useEffect(() => {
    const processingSources = sources.filter(s => (s.status === 'processing' || s.status === 'indexing') && s.taskId);
    if (processingSources.length === 0) return;

    const interval = setInterval(() => {
      processingSources.forEach(source => {
        api.get(`/api/task_status/${source.taskId}`)
          .then(response => {
            const task = response.data;
            if (task.status === 'completed' || task.status === 'failed' || task.status === 'index_completed' || task.status === 'index_failed') {
              setSources(prevSources =>
                prevSources.map(s =>
                  s.taskId === source.taskId ? { ...s, status: task.status } : s
                )
              );
              // Once completed or indexed, we might want to refresh the whole list to get proper metadata
              if(task.status === 'completed' || task.status === 'index_completed') {
                fetchDocuments();
              }
            }
          })
          .catch(error => console.error(`Error fetching status for task ${source.taskId}:`, error));
      });
    }, 3000); // Check every 3 seconds

    // Cleanup interval when component unmounts or dependencies change
    return () => clearInterval(interval);
  }, [sources, fetchDocuments]);
  

  // 개별 체크박스 토글 핸들러
  const handleToggle = (value) => () => {
    const currentIndex = checked.indexOf(value);
    const newChecked = [...checked];

    if (currentIndex === -1) {
      newChecked.push(value);
    } else {
      newChecked.splice(currentIndex, 1);
    }

    setChecked(newChecked);
    
    // 체크된 파일 이름 목록 업데이트
    const newCheckedFiles = newChecked.map(index => sources[index].title);
    setCheckedFiles(newCheckedFiles);
  };

  // 전체 선택 핸들러
  const handleSelectAll = (event) => {
    if (event.target.checked) {
      const newChecked = Array.from({ length: sources.length }, (_, i) => i);
      setChecked(newChecked);
      // 체크된 파일 이름 목록 업데이트
      const newCheckedFiles = sources.map(source => source.title);
      setCheckedFiles(newCheckedFiles);
    } else {
      setChecked([]);
      setCheckedFiles([]);
    }
  };

  // 선택 삭제 핸들러
  const handleDelete = () => {
    const newSources = sources.filter((_, index) => !checked.includes(index));
    setSources(newSources);
    setChecked([]);
    setCheckedFiles([]);
  };

  const handleOpenModal = () => {
    setIsModalOpen(true);
  };
  
  // 파일 업로드 모달을 여는 함수
  const handleOpenFileUploadModal = () => {
    onFileUploadClick();
  };
  
  // 검색 모달을 여는 함수
  const handleOpenSearchModal = () => {
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
  };

  const handleBackToList = () => {
    setSelectedSource(null);
    setFileContent('');
  };

  const handleSourceClick = async (source) => {
    if (source.status === 'processing' || source.status === 'failed') {
      console.log(`Source '${source.title}' is not ready.`);
      return;
    }

    // 접은 상태에서 파일을 클릭하면 패널을 펼침
    if (collapsed) {
      onToggleCollapse();
    }

    if (selectedSource && selectedSource.id === source.id) {
      return; // 이미 선택된 파일이면 아무것도 안 함
    }

    setIsLoading(true);
    setSelectedSource(source);

    try {
      const response = await api.get(`/api/file/${source.title}`);
      const data = response.data;
      setFileContent(data.content);
      // 모달은 자동으로 열지 않고, 모달 버튼을 클릭해야만 열림
      // setFileContentModalOpen(true);
    } catch (error) {
      console.error(error);
      setFileContent('파일 내용을 불러오는 데 실패했습니다.');
    } finally {
      setIsLoading(false);
    }
  };

  

  
  return (
    <div id="leftbox" style={{width: collapsed ? '48px' : '95%', height: '95%', border: '1px solid #e0e0e0', borderRadius: '15px', overflow: 'hidden', display: 'flex', flexDirection: 'column'}}>
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
        {/* Header - 1/3 영역 */}
        <Box sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: collapsed ? '8px 4px' : '8px 16px',
          borderBottom: '1px solid #e0e0e0',
          flexShrink: 0,
          minHeight: '52px', // 헤더 높이 고정
        }}>
          {!collapsed && (
            <Typography variant="h6" sx={{ fontSize: '1.1rem', fontWeight: 'bold' }}>
              라이브러리
            </Typography>
          )}
          <IconButton onClick={onToggleCollapse} size="small">
            {collapsed ? <KeyboardDoubleArrowRightIcon /> : <KeyboardDoubleArrowLeftIcon />}
          </IconButton>
        </Box>

        {/* Button Row */}
        {!collapsed ? (
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', p: 0.5, borderBottom: '1px solid #e0e0e0' }}>
            <Button 
              variant="outlined" 
              startIcon={<AddIcon fontSize="small" />} 
              size="small" 
              onClick={onFileUploadClick}
              sx={{ 
                height: '32px', 
                fontSize: '0.8rem',
                borderRadius: '6px',
                textTransform: 'none',
                fontWeight: 'normal',
                px: 1.5
              }}
            >
              추가
            </Button>
            <Button 
              variant="outlined" 
              startIcon={<SearchIcon fontSize="small" />} 
              size="small" 
              onClick={handleOpenModal}
              sx={{ 
                height: '32px', 
                fontSize: '0.8rem',
                borderRadius: '6px',
                textTransform: 'none',
                fontWeight: 'normal',
                px: 1.5
              }}
            >
              탐색
            </Button>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1, py: 1, borderBottom: '1px solid #e0e0e0' }}>
            <IconButton 
              size="small" 
              onClick={onFileUploadClick}
              title="파일 추가"
              sx={{ 
                backgroundColor: '#f5f5f5',
                borderRadius: '8px',
                padding: '6px',
                width: '32px',
                height: '32px',
                '&:hover': { backgroundColor: '#e0e0e0' }
              }}
            >
              <AddIcon fontSize="small" />
            </IconButton>
            <IconButton 
              size="small" 
              onClick={handleOpenModal}
              title="파일 탐색"
              sx={{ 
                backgroundColor: '#f5f5f5',
                borderRadius: '8px',
                padding: '6px',
                width: '32px',
                height: '32px',
                '&:hover': { backgroundColor: '#e0e0e0' }
              }}
            >
              <SearchIcon fontSize="small" />
            </IconButton>
          </Box>
        )}

        {/* Source Panel Content */}
        {collapsed ? (
          <Box sx={{ 
            display: 'flex', 
            flexDirection: 'column', 
            alignItems: 'center', 
            height: 'calc(100% - 130px)', /* 아이콘 버튼 영역 고려하여 높이 조정 */
            position: 'relative',
            overflow: 'hidden',
            width: '100%'
          }}>

          {/* 파일 목록 영역 - 접힌 상태에서는 전체 공간 사용 */}
          <Box sx={{ 
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center', 
            justifyContent: 'flex-start',
            paddingTop: '8px',
            gap: 1,
            py: 1,
            width: '100%',
            height: '100%',
            flexGrow: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            '&::-webkit-scrollbar': { width: '4px' },
            '&::-webkit-scrollbar-thumb': { 
              backgroundColor: '#bdbdbd',
              borderRadius: '3px',
              '&:hover': { backgroundColor: '#9e9e9e' }
            },
            scrollbarWidth: 'thin',
            msOverflowStyle: 'auto',
            position: 'relative',
            '&:hover .scroll-button': {
              opacity: 0.7
            }
          }}
        >
              {/* 파일 목록의 모든 파일을 개별 아이콘으로 표시 */}
              {sources.map((source, index) => {
                // 파일 확장자에 따라 적절한 아이콘 선택
                const fileName = source.title.toLowerCase();
                let icon = <InsertDriveFileIcon />;
                let iconColor = 'inherit';
                
                if (fileName.endsWith('.pdf')) {
                  icon = <PictureAsPdfIcon />;
                  iconColor = 'error';
                } else if (fileName.endsWith('.md')) {
                  icon = <DescriptionIcon />;
                  iconColor = 'primary';
                } else if (fileName.endsWith('.jpg') || fileName.endsWith('.png') || fileName.endsWith('.jpeg') || fileName.endsWith('.gif')) {
                  icon = <ImageIcon />;
                  iconColor = 'success';
                } else if (fileName.endsWith('.js') || fileName.endsWith('.py') || fileName.endsWith('.java') || fileName.endsWith('.html') || fileName.endsWith('.css')) {
                  icon = <CodeIcon />;
                  iconColor = 'secondary';
                }
                
                // 파일 상태에 따라 아이콘 표시 방식 변경
                if (source.status === 'processing') {
                  return (
                    <IconButton 
                      key={index}
                      size="small" 
                      disabled
                      title={`${source.title} (처리 중...)`}
                      sx={{ 
                        position: 'relative',
                        backgroundColor: '#f5f5f5',
                        borderRadius: '8px',
                        padding: collapsed ? '6px' : '8px',
                        margin: '4px',
                        width: collapsed ? '32px' : '42px',
                        height: collapsed ? '32px' : '42px',
                        transition: 'all 0.2s ease'
                      }}
                    >
                      {React.cloneElement(icon, { color: iconColor, sx: { opacity: 0.5 } })}
                      <CircularProgress 
                        size={16} 
                        sx={{ 
                          position: 'absolute', 
                          top: '50%', 
                          left: '50%', 
                          marginTop: '-8px', 
                          marginLeft: '-8px' 
                        }} 
                      />
                    </IconButton>
                  );
                } else if (source.status === 'failed') {
                  return (
                    <IconButton 
                      key={index}
                      size="small" 
                      disabled
                      title={`${source.title} (처리 실패)`}
                      sx={{ 
                        position: 'relative',
                        backgroundColor: '#fff0f0',
                        borderRadius: '8px',
                        padding: collapsed ? '6px' : '8px',
                        margin: '4px',
                        width: collapsed ? '32px' : '42px',
                        height: collapsed ? '32px' : '42px',
                        transition: 'all 0.2s ease'
                      }}
                    >
                      <ErrorOutlineIcon color="error" />
                    </IconButton>
                  );
                } else {
                  return (
                    <IconButton 
                      key={index}
                      size="small" 
                      onClick={() => handleSourceClick(source)}
                      title={source.title}
                      sx={{ 
                        position: 'relative',
                        backgroundColor: '#f5f5f5',
                        borderRadius: '8px',
                        padding: collapsed ? '6px' : '8px',
                        margin: '4px',
                        width: collapsed ? '32px' : '42px',
                        height: collapsed ? '32px' : '42px',
                        transition: 'all 0.2s ease',
                        '&:hover': { 
                          backgroundColor: '#e0e0e0',
                          transform: 'scale(1.05)'
                        },
                        ...(selectedSource?.id === source.id ? {
                          backgroundColor: '#e3f2fd',
                          boxShadow: '0 0 0 2px #2196f3'
                        } : {})
                      }}
                    >
                      {React.cloneElement(icon, { color: iconColor })}
                    </IconButton>
                  );
                }
              })}
            </Box>
            
            {/* 위로 스크롤 버튼 - 파일 목록 영역 위에 겹쳐서 표시 */}
            <Box 
              className="scroll-button"
              sx={{
                position: 'absolute',
                top: '10px',
                right: '10px',
                zIndex: 5,
                opacity: 0,
                transition: 'opacity 0.3s'
              }}
            >
              <IconButton 
                size="small" 
                sx={{ 
                  backgroundColor: 'rgba(255, 255, 255, 0.9)',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
                  width: '28px',
                  height: '28px',
                  '&:hover': { backgroundColor: 'rgba(240, 240, 240, 1)' } 
                }}
                onClick={() => {
                  const scrollContainer = document.querySelector('div[id="leftbox"] > div > div:nth-child(3)');
                  if (scrollContainer) {
                    scrollContainer.scrollBy({ top: -150, behavior: 'smooth' });
                  }
                }}
              >
                <KeyboardArrowUpIcon fontSize="small" />
              </IconButton>
            </Box>
            
            {/* 아래로 스크롤 버튼 - 파일 목록 영역 위에 겹쳐서 표시 */}
            <Box 
              className="scroll-button"
              sx={{
                position: 'absolute',
                bottom: '10px',
                right: '10px',
                zIndex: 5,
                opacity: 0,
                transition: 'opacity 0.3s'
              }}
            >
              <IconButton 
                size="small" 
                sx={{ 
                  backgroundColor: 'rgba(255, 255, 255, 0.9)',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
                  width: '28px',
                  height: '28px',
                  '&:hover': { backgroundColor: 'rgba(240, 240, 240, 1)' } 
                }}
                onClick={() => {
                  const scrollContainer = document.querySelector('div[id="leftbox"] > div > div:nth-child(3)');
                  if (scrollContainer) {
                    scrollContainer.scrollBy({ top: 150, behavior: 'smooth' });
                  }
                }}
              >
                <KeyboardArrowDownIcon fontSize="small" />
              </IconButton>
            </Box>
          </Box>
        ) : (
          <Box sx={{ flexGrow: 1, overflowY: 'auto', padding: '16px' }}>
            {selectedSource ? (
              <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', p: 1, borderBottom: '1px solid #e0e0e0' }}>
                  <IconButton onClick={handleBackToList} size="small">
                    <ArrowBackIcon />
                  </IconButton>
                  <Typography variant="h6" sx={{ ml: 1, fontSize: '1rem', fontWeight: 'bold', flexGrow: 1 }}>
                    {selectedSource.title}
                  </Typography>
                  <IconButton 
                    size="small" 
                    onClick={() => setFileContentModalOpen(true)} 
                    title="모달로 보기"
                  >
                    <OpenInNewIcon />
                  </IconButton>
                </Box>
                <Box sx={{ flexGrow: 1, p: 2, overflowY: 'auto' }}>
                  {isLoading ? (
                    <CircularProgress />
                  ) : (
                    <FileContentBox content={fileContent} />
                  )}
                </Box>
              </Box>
            ) : (
              <>
                <Box
                  sx={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '0px 8px',
                    mb: 1,
                    height: '36px'
                  }}
                >
                  <FormControlLabel
                    label={<Typography sx={{ fontSize: '0.875rem' }}>전체 선택</Typography>}
                    control={
                      <Checkbox
                        size="small"
                        onChange={handleSelectAll}
                        checked={sources.length > 0 && checked.length === sources.length}
                        indeterminate={checked.length > 0 && checked.length < sources.length}
                      />
                    }
                  />
                  <IconButton size="small" onClick={handleDelete} disabled={checked.length === 0}>
                    <DeleteIcon />
                  </IconButton>
                </Box>

                {/* Source List */}
                <List sx={{ p: 0 }}>
                  {sources.map((source, index) => (
                    <ListItem 
                      key={index} 
                      dense 
                      button 
                      onClick={() => handleSourceClick(source)}
                      sx={{ 
                        p: 0.5, 
                        mb: 1, 
                        borderRadius: 1,
                        border: '1px solid #e0e0e0',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        '&:hover': {
                          backgroundColor: '#f5f5f5',
                        }
                      }}
                    >
                      {source.status === 'processing' ? (
                        <Box sx={{ width: '100%', p: 1 }}>
                          <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{source.title}</Typography>
                          <LinearProgress />
                          <Typography variant="caption" color="text.secondary">처리중...</Typography>
                        </Box>
                      ) : (
                        <>
                          <ListItemIcon sx={{ minWidth: '40px' }}>
                            {source.status === 'failed' ? <ErrorOutlineIcon color="error" /> : (
                              (() => {
                                const ext = source.title.toLowerCase();
                                if (ext.endsWith('.pdf')) return <PictureAsPdfIcon color="error" />;
                                if (ext.endsWith('.md')) return <DescriptionIcon color="primary" />;
                                if (ext.endsWith('.jpg') || ext.endsWith('.png') || ext.endsWith('.jpeg') || ext.endsWith('.gif')) return <ImageIcon color="success" />;
                                if (ext.endsWith('.js') || ext.endsWith('.py') || ext.endsWith('.java') || ext.endsWith('.html') || ext.endsWith('.css')) return <CodeIcon color="secondary" />;
                                return <InsertDriveFileIcon />;
                              })()
                            )}
                          </ListItemIcon>
                          <ListItemText
                            primary={source.status === 'failed' ? "처리 실패" : source.title}
                            primaryTypographyProps={{ sx: { fontSize: '0.875rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: source.status === 'failed' ? 'error.main' : 'text.primary' } }}
                          />
                        </>
                      )}
                      <Checkbox
                        edge="end"
                        size="small"
                        onChange={handleToggle(index)}
                        checked={checked.indexOf(index) !== -1}
                        onClick={(e) => e.stopPropagation()}
                        sx={{ mr: 0.5, padding: '4px' }}
                      />
                    </ListItem>
                  ))}
                </List>
              </>
            )}
          </Box>
        )}
      </Box>
      
      {/* 검색 모달 */}
      <SearchModal 
        open={isModalOpen} 
        onClose={handleCloseModal} 
        onProcessingStart={handleProcessingStart} 
        onDocumentAdded={fetchDocuments} // 문서 추가 후 목록 새로고침 콜백 전달
      />
      
      {/* 파일 내용 모달 */}
      <Dialog
        open={fileContentModalOpen}
        onClose={() => setFileContentModalOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          {selectedSource?.title || '파일 내용'}
          <IconButton
            aria-label="close"
            onClick={() => setFileContentModalOpen(false)}
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers sx={{ padding: 0 }}>
          {isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
              <CircularProgress />
            </Box>
          ) : (
            <FileContentBox content={fileContent} />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};


export default Leftbox;
