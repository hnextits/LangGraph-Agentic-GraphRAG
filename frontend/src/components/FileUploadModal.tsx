import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { 
  Modal, 
  Box, 
  Typography, 
  Button, 
  LinearProgress, 
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  ListItemSecondaryAction,
  Paper,
  Divider
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import UploadIcon from '@mui/icons-material/Upload';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import CircularProgress from '@mui/material/CircularProgress';
import api from '@/lib/api';

interface FileUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onFilesAdd?: (files: File[]) => Promise<void>;
}

interface UploadingFile {
  file: File;
  progress: number;
  status: 'pending' | 'uploading' | 'success' | 'error';
  error?: string;
}

const FileUploadModal: React.FC<FileUploadModalProps> = ({ isOpen, onClose, onFilesAdd }) => {
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map(file => ({
      file,
      progress: 0,
      status: 'pending' as const
    }));
    
    setUploadingFiles(prev => [...prev, ...newFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
      'application/pdf': ['.pdf'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png']
    }
  });

  const handleRemoveFile = (index: number) => {
    setUploadingFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleUpload = async () => {
    if (uploadingFiles.length === 0 || isUploading) return;
    
    setIsUploading(true);
    
    // 모든 파일의 상태를 'uploading'으로 변경
    setUploadingFiles(prev => 
      prev.map(file => ({
        ...file,
        status: 'uploading',
        progress: 0
      }))
    );
    
    const filesToUpload = uploadingFiles.map(item => item.file);
    
    try {
      // 업로드 진행 상황을 시뮬레이션하기 위한 인터벌
      const progressInterval = setInterval(() => {
        setUploadingFiles(prev => 
          prev.map(file => ({
            ...file,
            progress: Math.min(file.progress + Math.random() * 20, 95)
          }))
        );
      }, 500);
      
      // 실제 파일 업로드 요청
      let uploadSuccess = true;
      try {
        if (onFilesAdd) {
          await onFilesAdd(filesToUpload);
        } else {
          const response = await api.uploadFiles(filesToUpload);
          uploadSuccess = response.data.success;
        }
      } catch (error) {
        uploadSuccess = false;
        throw error; // 오류를 다시 던져서 catch 블록에서 처리하게 함
      } finally {
        clearInterval(progressInterval);
      }
      
      if (uploadSuccess) {
        // 모든 파일 업로드 성공
        setUploadingFiles(prev => 
          prev.map(file => ({
            ...file,
            status: 'success',
            progress: 100
          }))
        );
        
        // 파일 업로드 완료 이벤트 발생
        const event = new CustomEvent('fileUploadComplete');
        window.dispatchEvent(event);
        
        // 3초 후 모달 닫기
        setTimeout(() => {
          onClose();
          setUploadingFiles([]);
        }, 3000);
      } else {
        // 일부 또는 전체 파일 업로드 실패
        setUploadingFiles(prev => 
          prev.map(file => ({
            ...file,
            status: 'error',
            error: '업로드 실패',
            progress: 0
          }))
        );
      }
    } catch (error) {
      console.error('파일 업로드 오류:', error);
      
      // 모든 파일 업로드 실패
      setUploadingFiles(prev => 
        prev.map(file => ({
          ...file,
          status: 'error',
          error: '서버 연결 오류',
          progress: 0
        }))
      );
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      aria-labelledby="file-upload-modal-title"
      aria-describedby="file-upload-modal-description"
    >
      <Paper
        sx={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '100%',
          maxWidth: 500,
          maxHeight: '90vh',
          borderRadius: 2,
          boxShadow: 24,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden'
        }}
      >
        {/* 헤더 */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', p: 2, borderBottom: '1px solid #e0e0e0' }}>
          <Typography variant="h6" id="file-upload-modal-title">
            파일 업로드
          </Typography>
          <IconButton onClick={onClose} size="small">
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>
        
        {/* 본문 */}
        <Box sx={{ p: 2, flexGrow: 1, overflow: 'auto' }}>
          {/* 드롭존 */}
          <Box
            {...getRootProps()}
            sx={{
              border: '2px dashed',
              borderColor: isDragActive ? 'primary.main' : 'grey.300',
              borderRadius: 1,
              p: 3,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              transition: 'all 0.2s',
              bgcolor: isDragActive ? 'primary.50' : 'background.paper',
              '&:hover': {
                borderColor: 'primary.light'
              }
            }}
          >
            <input {...getInputProps()} />
            <UploadIcon sx={{ fontSize: 40, mb: 1, color: isDragActive ? 'primary.main' : 'grey.400' }} />
            <Typography align="center" color="textSecondary">
              {isDragActive
                ? '파일을 여기에 놓으세요...'
                : '파일을 드래그 앤 드롭하거나 클릭하여 선택하세요'}
            </Typography>
            <Typography variant="caption" color="textSecondary" sx={{ mt: 0.5 }}>
              지원 형식: TXT, PDF, DOC, DOCX, MD, JPG, PNG
            </Typography>
          </Box>
          
          {/* 업로드 파일 목록 */}
          {uploadingFiles.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                업로드 파일 ({uploadingFiles.length})
              </Typography>
              <List dense disablePadding>
                {uploadingFiles.map((item, index) => (
                  <ListItem key={index} sx={{ border: '1px solid #e0e0e0', borderRadius: 1, mb: 1, p: 1 }}>
                    <ListItemIcon sx={{ minWidth: 36 }}>
                      <InsertDriveFileIcon fontSize="small" color="action" />
                    </ListItemIcon>
                    <ListItemText 
                      primary={
                        <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                          {item.file.name}
                        </Typography>
                      }
                      secondary={
                        <Typography variant="caption" color="textSecondary">
                          {(item.file.size / 1024).toFixed(1)} KB
                        </Typography>
                      }
                    />
                    <ListItemSecondaryAction>
                      {item.status === 'pending' && (
                        <IconButton edge="end" size="small" onClick={() => handleRemoveFile(index)}>
                          <CloseIcon fontSize="small" />
                        </IconButton>
                      )}
                      {item.status === 'uploading' && (
                        <Typography variant="caption" color="primary">
                          {item.progress.toFixed(0)}%
                        </Typography>
                      )}
                      {item.status === 'success' && (
                        <CheckCircleIcon fontSize="small" color="success" />
                      )}
                      {item.status === 'error' && (
                        <ErrorIcon fontSize="small" color="error" />
                      )}
                    </ListItemSecondaryAction>
                    
                    {/* 진행 상태 바 */}
                    {item.status === 'uploading' && (
                      <Box sx={{ width: '100%', mt: 1 }}>
                        <LinearProgress variant="determinate" value={item.progress} />
                      </Box>
                    )}
                    
                    {/* 오류 메시지 */}
                    {item.status === 'error' && item.error && (
                      <Typography variant="caption" color="error" sx={{ mt: 0.5, display: 'block' }}>
                        {item.error}
                      </Typography>
                    )}
                  </ListItem>
                ))}
              </List>
            </Box>
          )}
        </Box>
        
        {/* 푸터 */}
        <Box sx={{ p: 2, borderTop: '1px solid #e0e0e0', display: 'flex', justifyContent: 'flex-end' }}>
          <Button 
            onClick={onClose} 
            variant="outlined" 
            color="inherit" 
            sx={{ mr: 1 }}
          >
            취소
          </Button>
          <Button
            onClick={handleUpload}
            variant="contained"
            color="primary"
            disabled={uploadingFiles.length === 0 || isUploading}
            startIcon={isUploading ? <CircularProgress size={16} /> : <UploadIcon />}
          >
            {isUploading ? '업로드 중...' : '업로드'}
          </Button>
        </Box>
      </Paper>
    </Modal>
  );
};

export default FileUploadModal;
