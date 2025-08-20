import React, { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import {
  Box,
  Button,
  Modal,
  Typography,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  IconButton,
  Paper
} from '@mui/material';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import DeleteIcon from '@mui/icons-material/Delete';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';

const modalStyle = {
  position: 'absolute',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  width: 600,
  bgcolor: 'background.paper',
  border: '2px solid #000',
  boxShadow: 24,
  p: 4,
  display: 'flex',
  flexDirection: 'column',
  maxHeight: '80vh',
};

const dropzoneStyle = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '20px',
  borderWidth: 2,
  borderRadius: '10px',
  borderColor: '#e0e0e0',
  borderStyle: 'dashed',
  backgroundColor: '#fafafa',
  color: '#bdbdbd',
  outline: 'none',
  transition: 'border .24s ease-in-out',
  cursor: 'pointer',
  minHeight: '150px',
  marginTop: '16px',
};

const FileUploadModal = ({ open, handleClose, onFilesAdd }) => {
  const [files, setFiles] = useState([]);

  const onDrop = useCallback(acceptedFiles => {
    setFiles(prevFiles => [...prevFiles, ...acceptedFiles.map(file => Object.assign(file, {
      preview: URL.createObjectURL(file)
    }))]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ 
    onDrop, 
    accept: 'image/*,application/pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt'
  });

  const handleRemoveFile = (fileToRemove) => {
    setFiles(files.filter(file => file !== fileToRemove));
  };
  
  const handleUpload = () => {
    if (typeof onFilesAdd === 'function') {
      onFilesAdd(files);
    }
    // 성공 후 모달 닫기 및 파일 목록 초기화
    handleClose();
    setFiles([]);
  };

  const fileList = files.map(file => (
    <ListItem
      key={file.path}
      secondaryAction={
        <IconButton edge="end" aria-label="delete" onClick={() => handleRemoveFile(file)}>
          <DeleteIcon />
        </IconButton>
      }
    >
      <ListItemIcon>
        <InsertDriveFileIcon />
      </ListItemIcon>
      <ListItemText
        primary={file.path}
        secondary={`${(file.size / 1024).toFixed(2)} KB`}
      />
    </ListItem>
  ));

  return (
    <Modal
      open={open}
      onClose={() => { handleClose(); setFiles([]); }}
      aria-labelledby="file-upload-modal-title"
    >
      <Box sx={modalStyle}>
        <Typography id="file-upload-modal-title" variant="h6" component="h2">
          로컬 파일 업로드
        </Typography>
        <Box {...getRootProps({ style: dropzoneStyle })}>
          <input {...getInputProps()} />
          <CloudUploadIcon sx={{ fontSize: 48, color: 'primary.main' }} />
          {
            isDragActive ?
              <Typography>여기에 파일을 드롭하세요...</Typography> :
              <Typography>파일을 드래그 앤 드롭하거나 여기를 클릭하여 선택하세요.</Typography>
          }
        </Box>
        {files.length > 0 && (
          <Paper variant="outlined" sx={{ mt: 2, flexGrow: 1, overflowY: 'auto' }}>
            <List dense>
              {fileList}
            </List>
          </Paper>
        )}
        <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end' }}>
          <Button onClick={() => { handleClose(); setFiles([]); }}>취소</Button>
          <Button 
            variant="contained" 
            onClick={handleUpload} 
            disabled={files.length === 0} 
            sx={{ ml: 1 }}
          >
            업로드 ({files.length})
          </Button>
        </Box>
      </Box>
    </Modal>
  );
};

export default FileUploadModal;
