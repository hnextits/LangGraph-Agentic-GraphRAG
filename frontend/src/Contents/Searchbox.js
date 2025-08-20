/**
 * React와 필요한 훅(useState, useEffect)을 가져옵니다.
 * - React: React 라이브러리의 핵심입니다.
 * - useState: 컴포넌트에서 상태(state)를 관리하기 위한 훅입니다. 상태가 변경되면 컴포넌트가 다시 렌더링됩니다.
 * - useEffect: 컴포넌트의 생명주기(생성, 업데이트, 소멸)에 맞춰 특정 작업을 수행하게 해주는 훅입니다.
 */
import React, { useState, useEffect } from 'react';
import api from '../api';

/**
 * Material-UI 라이브러리에서 UI를 구성하는 데 필요한 컴포넌트들을 가져옵니다.
 * 각 컴포넌트는 웹 페이지의 특정 부분을 담당합니다.
 * - Box: 레이아웃을 잡기 위한 기본적인 컨테이너 컴포넌트입니다. (div와 비슷)
 * - Typography: 텍스트를 표시하기 위한 컴포넌트입니다. (p, h1, h2 등)
 * - Button: 클릭 가능한 버튼입니다.
 * - Modal: 현재 화면 위에 새로운 창(모달)을 띄울 때 사용합니다.
 * - TextField: 사용자가 텍스트를 입력할 수 있는 입력 필드입니다.
 * - CircularProgress: 로딩 중임을 나타내는 원형 아이콘입니다.
 * - List, ListItem, ListItemText: 목록을 만들기 위한 컴포넌트들입니다.
 * - Link: 하이퍼링크를 만듭니다.
 * - Checkbox: 체크박스입니다.
 * - FormControlLabel: 체크박스 같은 컨트롤 옆에 라벨을 붙여줍니다.
 */
import {
  Box, Typography, Button, Modal, TextField, CircularProgress, List, ListItem, ListItemText, Link, Checkbox, FormControlLabel
} from '@mui/material';

// 검색 모달 창의 기본 스타일을 정의하는 객체입니다.
// CSS 속성을 JavaScript 객체 형태로 작성합니다.
const modalStyle = {
  position: 'absolute', // 절대 위치
  top: '50%', // 화면 세로 중앙
  left: '50%', // 화면 가로 중앙
  transform: 'translate(-50%, -50%)', // 정확한 중앙 정렬을 위한 보정
  width: 500, // 너비 500px
  bgcolor: 'background.paper', // 배경색 (테마에 정의된 종이 색상)
  border: '2px solid #000', // 검은색 2px 테두리
  boxShadow: 24, // 그림자 효과
  p: 4, // 안쪽 여백 (padding)
};

/**
 * SearchModal 컴포넌트를 정의합니다.
 * 이 컴포넌트는 검색 기능을 가진 모달 창 전체를 담당합니다.
 * @param {object} props - 부모 컴포넌트로부터 전달받는 속성들입니다.
 * @param {boolean} props.open - 모달이 열려있는지 여부를 나타냅니다.
 * @param {function} props.onClose - 모달을 닫는 함수입니다.
 * @param {function} props.onProcessingStart - 문서 처리 시작을 알리는 함수입니다.
 */
const SearchModal = ({ open, onClose, onProcessingStart }) => {
  // useState 훅을 사용하여 컴포넌트의 상태를 관리합니다.
  // const [상태이름, 상태를변경하는함수] = useState(초기값);

  // 검색어 상태 관리. 초기값은 '검색어를 입력하세요.'
  const [searchTerm, setSearchTerm] = useState('검색어를 입력하세요.');
  // 검색 결과 목록 상태 관리. 초기값은 빈 배열.
  const [results, setResults] = useState([]);
  // 로딩 상태 관리. API 호출 중일 때 true가 됩니다. 초기값은 false.
  const [loading, setLoading] = useState(false);
  // 체크된 항목들의 인덱스를 저장하는 상태 관리. 초기값은 빈 배열.
  const [checked, setChecked] = useState([]);

  /**
   * useEffect 훅을 사용하여 'open' 상태가 변경될 때마다 특정 작업을 수행합니다.
   * 여기서는 모달이 열릴 때(open이 true가 될 때) 내부 상태를 초기화합니다.
   * 이렇게 하면 사용자가 모달을 닫았다가 다시 열 때 항상 깨끗한 상태에서 시작할 수 있습니다.
   */
  useEffect(() => {
    if (open) {
      setSearchTerm('검색어를 입력하세요.'); // 검색어 초기화
      setResults([]); // 검색 결과 목록 비우기
      setChecked([]); // 체크된 항목 초기화
      setLoading(false); // 로딩 상태 초기화
    }
  }, [open]); // 이 배열 안에 있는 값이 변경될 때만 useEffect 내부 함수가 실행됩니다.

  // 검색창(TextField)에 포커스가 갔을 때 실행되는 함수입니다.
  const handleFocus = () => {
    // 현재 검색어가 placeholder 텍스트와 같다면, 빈 문자열로 바꿔줍니다.
    if (searchTerm === '검색어를 입력하세요.') {
      setSearchTerm('');
    }
  };

  // 검색창에서 포커스가 벗어났을 때 실행되는 함수입니다.
  const handleBlur = () => {
    // 검색창 내용의 앞뒤 공백을 제거했을 때 아무것도 없다면, 다시 placeholder 텍스트를 보여줍니다.
    if (!searchTerm.trim()) {
      setSearchTerm('검색어를 입력하세요.');
    }
  };

  // '검색' 버튼을 클릭하거나 Enter 키를 눌렀을 때 실행될 함수입니다.
  const handleSearch = async () => {
    // 검색어가 비어있거나 placeholder 텍스트 그대로일 경우, 경고창을 띄우고 함수를 종료합니다.
    if (!searchTerm.trim() || searchTerm === '검색어를 입력하세요.') {
      alert('검색어를 입력해주세요!');
      return; // 함수 실행 중단
    }

    setLoading(true); // 로딩 상태를 true로 변경하여 로딩 스피너를 보여줍니다.
    try {
      // fetch 함수를 사용하여 백엔드 API에 검색 요청을 보냅니다.
      // async/await 문법을 사용하여 비동기 네트워크 요청을 동기 코드처럼 쉽게 작성합니다.
      const response = await api.post('/api/search', { query: searchTerm });
      const data = response.data;
      // API 응답에서 'results' 키의 값을 가져오고, 만약 없다면 빈 배열을 사용합니다.
      const searchResults = data.results || [];
      setResults(searchResults); // 검색 결과 상태를 업데이트합니다.
      setChecked([]); // 검색 결과가 새로 나왔으므로, 체크박스 선택 상태를 초기화합니다.
    } catch (error) {
      // try 블록 안에서 에러가 발생하면 이 코드가 실행됩니다.
      console.error('API 호출 중 오류 발생:', error); // 콘솔에 에러 메시지를 출력합니다.
      alert('검색 중 오류가 발생했습니다.'); // 사용자에게 에러 발생을 알립니다.
    } finally {
      // try/catch 결과와 상관없이 항상 마지막에 실행됩니다.
      setLoading(false); // 로딩 상태를 false로 변경하여 로딩 스피너를 숨깁니다.
    }
  };

  // 검색 결과 목록의 각 항목을 클릭(체크)할 때 실행되는 함수입니다.
  const handleToggle = (value) => () => {
    const currentIndex = checked.indexOf(value); // 현재 클릭된 항목이 이미 'checked' 배열에 있는지 확인합니다.
    const newChecked = [...checked]; // 상태를 직접 수정하지 않기 위해 'checked' 배열을 복사합니다. (불변성 유지)

    if (currentIndex === -1) {
      // 배열에 없다면 새로 추가합니다.
      newChecked.push(value);
    } else {
      // 배열에 이미 있다면 제거합니다.
      newChecked.splice(currentIndex, 1);
    }

    setChecked(newChecked); // 업데이트된 배열로 상태를 변경합니다.
  };

  // '전체 선택' 체크박스를 클릭할 때 실행되는 함수입니다.
  const handleSelectAll = (event) => {
    // 체크박스가 체크되었다면
    if (event.target.checked) {
      // 모든 검색 결과의 인덱스로 새로운 배열을 만들어 'checked' 상태를 업데이트합니다.
      const newChecked = results.map((result, index) => index);
      setChecked(newChecked);
      return;
    }
    // 체크가 해제되었다면 'checked' 상태를 빈 배열로 만듭니다.
    setChecked([]);
  };

  // '확인' 버튼을 클릭할 때 실행되는 함수입니다.
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
          link: doc.link,     // url → link로 변경
          snippet: doc.snippet
        }));
      const responses = await Promise.all(promises);
      const successfulTasks = responses.filter(res => res.data && res.data.task_id).map(res => ({
        ...res.data, 
        title: selectedDocs.find(d => d.link === res.data.link)?.title || res.data.title || 'Unknown Title'
      }));

      if (successfulTasks.length > 0) {
        alert(`${successfulTasks.length}개의 문서 처리가 시작되었습니다.`);
        onProcessingStart(successfulTasks); // 부모 컴포넌트에 처리 시작을 알림
        onClose(); // 성공적으로 처리 시작 후 모달 닫기
      } else {
        throw new Error('모든 문서 처리 시작에 실패했습니다.');
      }
    } catch (error) {
      alert(`오류가 발생했습니다: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 이 부분이 실제로 화면에 그려지는 JSX 코드입니다.
  return (
    <>
      {/* 검색 모달. open, onClose 같은 속성으로 동작을 제어합니다. */}
      <Modal
        open={open} // 부모에게 받은 open 상태에 따라 모달이 보이거나 사라집니다.
        onClose={onClose} // 모달 바깥을 클릭하거나 ESC 키를 누르면 onClose 함수가 실행됩니다.
        aria-labelledby="search-modal-title"
      >
        {/* 모달의 내용물입니다. 위에서 정의한 modalStyle이 적용됩니다. */}
        <Box sx={modalStyle}>
          <Typography id="search-modal-title" variant="h6" component="h2">
            출처 탐색
          </Typography>
          {/* 검색어 입력 필드 */}
          <TextField
            fullWidth // 가로 폭을 100%로 설정
            label="검색어" // 입력 필드 라벨
            variant="outlined" // 테두리 스타일
            margin="normal" // 위아래 여백
            value={searchTerm} // 입력 필드의 값은 searchTerm 상태와 연결됩니다.
            onChange={(e) => setSearchTerm(e.target.value)} // 내용이 변경될 때마다 searchTerm 상태를 업데이트합니다.
            onFocus={handleFocus} // 포커스가 갔을 때
            onBlur={handleBlur} // 포커스를 잃었을 때
            autoFocus // 모달이 열릴 때 자동으로 포커스를 줍니다.
            onKeyPress={(e) => { // 키보드를 눌렀을 때
              if (e.key === 'Enter') { // 만약 누른 키가 'Enter'라면
                handleSearch(); // 검색을 실행합니다.
              }
            }}
          />

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

          {/* 검색 결과 표시 영역 */}
          <Box sx={{ mt: 2 }}>
            {/* loading 상태가 true일 때만 이 부분을 렌더링합니다. (조건부 렌더링) */}
            {loading && (
              <Box sx={{ display: 'flex', justifyContent: 'center' }}>
                <CircularProgress />
                <Typography sx={{ ml: 2 }}>검색 중...</Typography>
              </Box>
            )}
            
            {/* results 배열에 항목이 1개 이상 있을 때만 이 부분을 렌더링합니다. */}
            {results.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="h6" sx={{ mb: 2 }}>
                  검색 결과 ({results.length}개)
                </Typography>
                
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        onChange={handleSelectAll} // 체크 시 handleSelectAll 함수 실행
                        checked={checked.length === results.length && results.length > 0} // 모든 항목이 체크되었는지 여부
                        indeterminate={checked.length > 0 && checked.length < results.length} // 일부만 체크되었는지 여부
                      />
                    }
                    label="전체 선택"
                  />
                  <Button 
                    variant="contained" 
                    onClick={handleConfirm} // 클릭 시 handleConfirm 함수 실행
                    disabled={checked.length === 0 || loading} // 체크된 항목이 없거나 로딩 중일 때 비활성화
                    size="small"
                  >
                    {loading ? <CircularProgress size={20} /> : `확인 (${checked.length})`}
                  </Button>
                </Box>
                
                {/* 스크롤 가능한 결과 목록 영역 */}
                <Box sx={{ maxHeight: 300, overflowY: 'auto' }}>
                  <List>
                    {/* results 배열을 순회하며 각 항목을 ListItem으로 만듭니다. (map 함수) */}
                    {results.map((result, index) => (
                      <ListItem 
                        key={index} // React가 각 항목을 구분하기 위한 고유한 key
                        dense 
                        button 
                        onClick={handleToggle(index)} // 클릭 시 handleToggle 함수 실행
                        sx={{ 
                          border: '1px solid #e0e0e0', 
                          mb: 1, 
                          borderRadius: 1,
                          '&:hover': {
                            backgroundColor: '#f5f5f5'
                          }
                        }}
                      >
                        <Checkbox
                          edge="start"
                          checked={checked.indexOf(index) !== -1} // 이 항목이 체크되었는지 여부
                          tabIndex={-1}
                          disableRipple
                        />
                        <ListItemText
                          primary={
                            <Link 
                              href={result.link} 
                              target="_blank" // 새 탭에서 열기
                              rel="noopener" 
                              onClick={(e) => e.stopPropagation()} // 링크 클릭 시 ListItem의 onClick 이벤트는 막기
                              sx={{ fontWeight: 'bold', color: '#1976d2' }}
                            >
                              {result.title}
                            </Link>
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
    </>
  );
};

export default SearchModal;
