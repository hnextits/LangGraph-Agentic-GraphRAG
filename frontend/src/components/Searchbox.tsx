"use client";

import { useState, useEffect } from 'react';
import api from '@/lib/api';

// Material UI 컴포넌트
import {
  Box,
  Typography,
  Button,
  Modal,
  TextField,
  CircularProgress,
  List,
  ListItem,
  ListItemText,
  Checkbox,
  FormControlLabel,
  Link as MuiLink
} from '@mui/material';

// 타입 정의
interface SearchResult {
  title: string;
  link: string;
  snippet: string;
}

interface SearchboxProps {
  open: boolean;
  onClose: () => void;
  onProcessingStart: (tasks: any[]) => void;
}

// 모달 스타일 정의
const modalStyle = {
  position: 'absolute' as 'absolute',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  width: 500,
  bgcolor: 'background.paper',
  border: '2px solid #000',
  boxShadow: 24,
  p: 4,
};

const Searchbox: React.FC<SearchboxProps> = ({ open, onClose, onProcessingStart }) => {
  // 상태 관리
  const [searchTerm, setSearchTerm] = useState<string>('검색어를 입력하세요.');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [checked, setChecked] = useState<number[]>([]);

  // 모달이 열릴 때마다 상태 초기화
  useEffect(() => {
    if (open) {
      setSearchTerm('검색어를 입력하세요.');
      setResults([]);
      setChecked([]);
      setLoading(false);
    }
  }, [open]);

  // 검색창 포커스 핸들러
  const handleFocus = () => {
    if (searchTerm === '검색어를 입력하세요.') {
      setSearchTerm('');
    }
  };

  // 검색창 블러 핸들러
  const handleBlur = () => {
    if (!searchTerm.trim()) {
      setSearchTerm('검색어를 입력하세요.');
    }
  };

  // 검색 실행 핸들러
  const handleSearch = async () => {
    if (!searchTerm.trim() || searchTerm === '검색어를 입력하세요.') {
      alert('검색어를 입력해주세요!');
      return;
    }

    setLoading(true);
    try {
      const response = await api.search({ query: searchTerm });
      const searchResults = response.data.results || [];
      setResults(searchResults);
      setChecked([]);
    } catch (error) {
      console.error('API 호출 중 오류 발생:', error);
      alert('검색 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  // 체크박스 토글 핸들러
  const handleToggle = (value: number) => () => {
    const currentIndex = checked.indexOf(value);
    const newChecked = [...checked];

    if (currentIndex === -1) {
      newChecked.push(value);
    } else {
      newChecked.splice(currentIndex, 1);
    }

    setChecked(newChecked);
  };

  // 전체 선택 핸들러
  const handleSelectAll = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked) {
      const newChecked = results.map((_, index) => index);
      setChecked(newChecked);
      return;
    }
    setChecked([]);
  };

  // 확인 버튼 핸들러
  const handleConfirm = async () => {
    if (checked.length === 0) {
      alert('추가할 문서를 선택해주세요.');
      return;
    }

    setLoading(true);
    const selectedDocs = checked.map(index => results[index]);

    try {
      const promises = selectedDocs.map(doc => 
        api.post('/api/add_document_from_search', {
          title: doc.title,
          link: doc.link,
          snippet: doc.snippet
        })
      );
      
      const responses = await Promise.all(promises);
      const successfulTasks = responses
        .filter(res => res.data && res.data.task_id)
        .map(res => ({
          ...res.data,
          title: selectedDocs.find(d => d.link === res.data.link)?.title || res.data.title || 'Unknown Title'
        }));

      if (successfulTasks.length > 0) {
        alert(`${successfulTasks.length}개의 문서 처리가 시작되었습니다.`);
        onProcessingStart(successfulTasks);
        onClose();
      } else {
        throw new Error('모든 문서 처리 시작에 실패했습니다.');
      }
    } catch (error: any) {
      alert(`오류가 발생했습니다: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 모달 렌더링
  return (
    <Modal
      open={open}
      onClose={onClose}
      aria-labelledby="search-modal-title"
    >
      <Box sx={modalStyle}>
        <Typography id="search-modal-title" variant="h6" component="h2">
          출처 탐색
        </Typography>
        
        {/* 검색어 입력 필드 */}
        <TextField
          fullWidth
          label="검색어"
          variant="outlined"
          margin="normal"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onFocus={handleFocus}
          onBlur={handleBlur}
          autoFocus
          onKeyPress={(e) => {
            if (e.key === 'Enter') {
              handleSearch();
            }
          }}
        />

        {/* 버튼 영역 */}
        <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
          <Button variant="outlined" onClick={onClose}>취소</Button>
          <Button 
            variant="contained" 
            onClick={handleSearch}
            disabled={loading}
          >
            검색
          </Button>
        </Box>

        {/* 검색 결과 영역 */}
        <Box sx={{ mt: 2 }}>
          {/* 로딩 표시 */}
          {loading && (
            <Box sx={{ display: 'flex', justifyContent: 'center' }}>
              <CircularProgress />
              <Typography sx={{ ml: 2 }}>검색 중...</Typography>
            </Box>
          )}
          
          {/* 검색 결과 목록 */}
          {results.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                검색 결과 ({results.length}개)
              </Typography>
              
              {/* 전체 선택 및 확인 버튼 */}
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <FormControlLabel
                  control={
                    <Checkbox
                      onChange={handleSelectAll}
                      checked={checked.length === results.length && results.length > 0}
                      indeterminate={checked.length > 0 && checked.length < results.length}
                    />
                  }
                  label="전체 선택"
                />
                <Button 
                  variant="contained" 
                  onClick={handleConfirm}
                  disabled={checked.length === 0 || loading}
                  size="small"
                >
                  {loading ? <CircularProgress size={20} /> : `확인 (${checked.length})`}
                </Button>
              </Box>
              
              {/* 스크롤 가능한 결과 목록 */}
              <Box sx={{ maxHeight: 300, overflowY: 'auto' }}>
                <List>
                  {results.map((result, index) => (
                    <ListItem 
                      key={index}
                      dense 
                      onClick={handleToggle(index)}
                      sx={{ 
                        border: '1px solid #e0e0e0', 
                        mb: 1, 
                        borderRadius: 1,
                        cursor: 'pointer',
                        '&:hover': {
                          backgroundColor: '#f5f5f5'
                        }
                      }}
                    >
                      <Checkbox
                        edge="start"
                        checked={checked.indexOf(index) !== -1}
                        tabIndex={-1}
                        disableRipple
                      />
                      <ListItemText
                        primary={
                          <MuiLink 
                            href={result.link} 
                            target="_blank"
                            rel="noopener"
                            onClick={(e) => e.stopPropagation()}
                            sx={{ fontWeight: 'bold', color: '#1976d2' }}
                          >
                            {result.title}
                          </MuiLink>
                        }
                        secondary={
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            {result.snippet}
                          </Typography>
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              </Box>
            </Box>
          )}
        </Box>
      </Box>
    </Modal>
  );
};

export default Searchbox;
