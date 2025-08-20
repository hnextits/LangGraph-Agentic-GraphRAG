### 명령어 cd /home/nextits2/.conda/envs/workbox
### python embedding_system.py --json data/combined_metadata_2.json --type image
### python embedding_system.py --json data/test_text_2.json --type text

import os
import re
import json
import time
import faiss
import numpy as np
import pickle
import requests
import torch
import logging
import hashlib
import uuid
from typing import List, Dict, Tuple, Any, Optional
from PIL import Image
from transformers import AutoTokenizer, AutoModel, AutoProcessor
import faiss
from tqdm import tqdm
from shared_embedding import shared_embedding

# 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

class VectorDBService:
    """
    RAG 시스템을 위한 벡터 DB 서비스
    이미지와 텍스트 메타데이터를 위한 별도의 FAISS 인덱스를 관리하며, 
    임베딩 생성 및 벡터 DB 저장/검색 기능을 제공합니다.
    """
    def __init__(self, 
             model_name="Qwen/Qwen3-Embedding-4B",  # 여기를 변경
             device=None,
             vector_dimension=2560,
             index_path="faiss_test",
             index_type="IP"):
        """
        벡터 DB 서비스 초기화
        
        Args:
            model_name: 사용할 멀티모달 모델 이름
            device: 사용할 디바이스 (None이면 자동 감지)
            vector_dimension: 벡터 차원 수
            index_path: 인덱스 저장 경로 (디렉토리)
            index_type: 인덱스 유형 ("L2" 또는 "IP" - 내적)
        """
        self.model_name = model_name
        self.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        self.vector_dimension = vector_dimension
        self.index_path = index_path
        self.index_type = index_type
        self.ollama_host = 'http://ollama:11434'  # Docker 컨테이너 이름으로 변경
        
        # 이미지 메타데이터 리스트
        self.image_metadata_list = []
        
        # 모델 및 프로세서 로드
        self._load_model()
        
        # FAISS 인덱스 초기화
        self._init_indices()

        # 공유 임베딩 모델 인스턴스 초기화
        self.shared_embedding = shared_embedding
    
    def _load_model(self):
        """모델 및 프로세서 로드"""
        print(f"모델 로드 중: {self.model_name} (디바이스: {self.device})")
        
        try:
            # Hugging Face에서 Qwen3-Embedding-4B 모델 로드
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                padding_side='left'
            )
            # config에서 GENERATOR_TORCH_DTYPE 설정 확인
            try:
                from config import RAGConfig
                rag_config = RAGConfig()
                if rag_config.GENERATOR_TORCH_DTYPE == "auto":
                    torch_dtype = "auto"
                else:
                    torch_dtype = torch.float16
            except Exception as e:
                # config 로드 실패 시 기본값 사용
                logger.warning(f"Config 로드 실패: {e}, 기본 dtype 사용")
                torch_dtype = torch.float16
            
            self.model = AutoModel.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                torch_dtype=torch_dtype,
                device_map="auto"  # 자동 GPU 배치
                # attn_implementation="flash_attention_2"  # H100 최적화
            )
            
            logger.info(f"이미지 임베딩 모델 dtype 설정: {torch_dtype}")
            
            # 모델 평가 모드로 설정 (학습 비활성화)
            self.model.eval()
            
            # Qwen3-Embedding-4B 모델의 임베딩 차원 설정
            self.vector_dimension = 2560
            
            print(f"Hugging Face 모델 로드 완료: {self.model_name} (임베딩 차원: {self.vector_dimension})")
            
        except Exception as e:
            print(f"모델 로드 실패: {str(e)}")
            raise
    
    def _init_indices(self):
        """이미지 메타데이터를 위한 FAISS 인덱스 초기화"""
        # 디렉토리 생성
        os.makedirs(self.index_path, exist_ok=True)
        
        # 이미지 인덱스 초기화
        if self.index_type == "IP":
            self.image_index = faiss.IndexFlatIP(self.vector_dimension)
        else:
            self.image_index = faiss.IndexFlatL2(self.vector_dimension)
            
        # 인덱스 저장 경로
        self.image_index_path = os.path.join(self.index_path, "image_index.faiss")
        
        # 저장된 인덱스가 있으면 로드
        if os.path.exists(self.image_index_path):
            self.image_index = faiss.read_index(self.image_index_path)
            print(f"이미지 인덱스 로드 완룼: {self.image_index_path}")
    
    def generate_text_embedding(self, text: str, metadata: dict = None) -> np.ndarray:
        """
        텍스트 임베딩 생성 - text에 가중치를 부여하고 나머지 필드는 문맥 정보로만 활용
        개선된 가중치 부여 방식으로 임베딩 차별화 강화
        
        Args:
            text: 임베딩할 텍스트 (가중치 부여됨)
            metadata: 텍스트 메타데이터 (제목, 페이지 번호, 파일 경로 등)
            
        Returns:
            텍스트 임베딩 벡터 (numpy 배열)
        """
        if text is None or (isinstance(text, str) and text.strip() == ''):
            print("[경고] 임베딩할 텍스트가 null이거나 비어있습니다.")
            return np.zeros(self.vector_dimension, dtype=np.float16)
        
        try:
            # 텍스트 정규화 - 공백 제거 및 줄바꿈 정리
            text = text.strip()
            
            # 텍스트 길이 확인 및 로깅
            text_length = len(text)
            token_count = len(self.tokenizer.encode(text))
            print(f"원본 텍스트 길이: {text_length}자, 토큰 수: {token_count}")
            
            # 텍스트 분할 - 너무 길면 중요 부분만 추출
            # 토큰 수가 1000개 이상이면 처음과 끝 부분만 사용
            if token_count > 1000:
                # 처음 500개 토큰에 해당하는 텍스트와 마지막 300개 토큰에 해당하는 텍스트 추출
                first_part_tokens = self.tokenizer.encode(text, truncation=True, max_length=500)
                first_part = self.tokenizer.decode(first_part_tokens)
                
                # 마지막 부분 추출 (뒤에서부터 300개 토큰)
                all_tokens = self.tokenizer.encode(text, truncation=True, max_length=2000)
                if len(all_tokens) > 800:  # 충분히 긴 경우에만 분할
                    last_part_tokens = all_tokens[-300:]
                    last_part = self.tokenizer.decode(last_part_tokens)
                    text = first_part + "\n\n[...중략...]\n\n" + last_part
                    print(f"텍스트가 너무 길어 처음과 끝 부분만 사용: {len(self.tokenizer.encode(text))} 토큰")
            
            # 개선된 가중치 부여 방식
            # 1. 핵심 텍스트 반복 (5번) - 더 강한 가중치 부여
            # 2. 명시적 마커 추가로 중요도 강조
            weighted_text = (
                "[핵심내용]\n" + text + "\n[/핵심내용]\n\n" +
                "[핵심내용]\n" + text + "\n[/핵심내용]\n\n" +
                "[핵심내용]\n" + text + "\n[/핵심내용]\n\n" +
                "[핵심내용]\n" + text + "\n[/핵심내용]\n\n" +
                "[핵심내용]\n" + text + "\n[/핵심내용]"
            )
            
            # 문맥 정보 구성 (가중치 없이 참조 정보로만 활용)
            context_parts = []
            
            if metadata:
                # 제목 추출 (문맥 정보)
                title = metadata.get("title", "")
                if title:
                    context_parts.append(f"제목: {title}")
                
                # 페이지 번호 추출 (문맥 정보)
                page_num = metadata.get("page_num", "")
                if page_num:
                    context_parts.append(f"페이지: {page_num}")
                
                # 파일 경로 추출 (문맥 정보)
                file_path = metadata.get("file_path", "") or metadata.get("image_path", "")
                if file_path:
                    # 파일명만 추출
                    file_name = os.path.basename(file_path)
                    context_parts.append(f"파일: {file_name}")
            
            # 문맥 정보를 문자열로 결합
            context_text = "\n".join(context_parts) if context_parts else ""
            
            # 가중치가 적용된 텍스트와 문맥 정보를 결합
            # 문맥 정보는 가중치 없이 참조용으로만 사용
            if context_text:
                final_text = weighted_text + "\n\n[문맥정보]\n" + context_text + "\n[/문맥정보]"
            else:
                final_text = weighted_text
            
            # 최종 텍스트 토큰 수 확인
            final_token_count = len(self.tokenizer.encode(final_text))
            print(f"최종 임베딩 텍스트 토큰 수: {final_token_count} (최대 2048)")
            
            # Hugging Face 모델을 사용하여 임베딩 생성
            with torch.no_grad():  # 그래디언트 계산 비활성화
                # 토크나이징 (토큰 길이 2048로 증가하여 최대한 많은 정보 보존)
                inputs = self.tokenizer(final_text, return_tensors="pt", padding=True, truncation=True, max_length=2048).to(self.device)
                
                # 토큰 수 확인 및 로깅
                actual_tokens = inputs['input_ids'].shape[1]
                print(f"실제 토크나이징된 토큰 수: {actual_tokens}")
                
                # 모델을 통한 임베딩 생성
                outputs = self.model(**inputs)
                
                # 마지막 히든 스테이트의 평균을 임베딩으로 사용
                # 개선: [CLS] 토큰만 사용하는 대신 전체 시퀀스의 평균 사용
                # 이렇게 하면 전체 텍스트의 의미를 더 잘 포착할 수 있음
                last_hidden = outputs.last_hidden_state.cpu().numpy()[0]
                
                # 마스크가 있는 경우 마스크된 부분 제외하고 평균 계산
                if 'attention_mask' in inputs:
                    mask = inputs['attention_mask'].cpu().numpy()[0]
                    # 마스크가 1인 위치만 평균 계산에 포함
                    masked_hidden = last_hidden[mask.astype(bool)]
                    embedding = np.mean(masked_hidden, axis=0)
                else:
                    # [CLS] 토큰과 전체 시퀀스 평균을 결합
                    cls_embedding = last_hidden[0]  # [CLS] 토큰
                    mean_embedding = np.mean(last_hidden, axis=0)  # 전체 평균
                    embedding = (cls_embedding + mean_embedding) / 2  # 둘의 평균
                
                # 정규화
                norm = np.linalg.norm(embedding)
                if norm > 1e-10:  # 0으로 나누기 방지
                    embedding = embedding / norm
                
                # 임베딩 통계 로깅
                print(f"임베딩 생성 완료: 차원={len(embedding)}, 노름={np.linalg.norm(embedding):.4f}")
                print(f"임베딩 통계: 평균={np.mean(embedding):.4f}, 표준편차={np.std(embedding):.4f}")
                
                return embedding
        except Exception as e:
            print(f"텍스트 임베딩 생성 오류: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return np.zeros(self.vector_dimension, dtype=np.float16)
    
    def generate_batch_embeddings(self, texts: List[str], batch_size=4) -> np.ndarray:
        """
        여러 텍스트의 임베딩을 배치로 생성 (Hugging Face 모델 사용)
        
        Args:
            texts: 임베딩할 텍스트 목록
            batch_size: 배치 처리 크기
            
        Returns:
            텍스트 임베딩 벡터 배열 (numpy 배열)
        """
        # null 텍스트 필터링
        filtered_texts = []
        for i, text in enumerate(texts):
            if text is None or (isinstance(text, str) and text.strip() == ''):
                print(f"[건너뛰기] 배치 임베딩에서 null 텍스트 발견 (인덱스: {i})")
                continue
            filtered_texts.append(text)
            
        if not filtered_texts:
            print("[경고] 배치에 유효한 텍스트가 없습니다.")
            return np.array([])
            
        all_embeddings = []
        
        try:
            # 배치 단위로 처리 (필터링된 텍스트 사용)
            for i in range(0, len(filtered_texts), batch_size):
                batch_texts = filtered_texts[i:i+batch_size]
                
                with torch.no_grad():  # 그래디언트 계산 비활성화
                    # 토크나이징 - 배치 처리
                    inputs = self.tokenizer(batch_texts, return_tensors="pt", padding=True, truncation=True, 
                                           max_length=512).to(self.device)
                    
                    # 모델을 통한 임베딩 생성
                    outputs = self.model(**inputs)
                    
                    # [CLS] 토큰 (첫 번째 토큰)의 임베딩을 사용
                    batch_embeddings = outputs.last_hidden_state[:, 0, :].cpu().numpy()
                    
                    # 배치 단위로 정규화 (axis=1로 각 벡터별 정규화)
                    norms = np.linalg.norm(batch_embeddings, axis=1, keepdims=True)
                    # 0으로 나누기 방지
                    norms = np.where(norms > 1e-10, norms, 1e-10)
                    batch_embeddings = batch_embeddings / norms
                    
                    all_embeddings.append(batch_embeddings)
            
            # 모든 배치 결합
            return np.vstack(all_embeddings) if all_embeddings else np.array([])
        except Exception as e:
            print(f"배치 임베딩 생성 실패: {str(e)}")
            import traceback
            print(traceback.format_exc())
            # Return an empty array instead of None to avoid 'NoneType' object is not iterable error
            return np.array([])
    
    def add_to_index(self, embedding: np.ndarray, metadata: Dict[str, Any], content_type: str = "image"):
        """
        이미지 및 차트 메타데이터 임베딩과 메타데이터를 인덱스에 추가
        
        Args:
            embedding: 추가할 임베딩 벡터
            metadata: 해당 임베딩의 메타데이터
            content_type: 콘텐츠 유형 ("image" 또는 "chart")
            
        Returns:
            추가 성공 여부 (bool)
        """
        # 이미지와 차트 모두 동일한 인덱스에 추가 (con_type으로 구분)
        if content_type not in ["image", "chart"]:
            print(f"이 시스템은 이미지와 차트 메타데이터만 지원합니다. 현재 유형: {content_type}")
            return False
            
        try:
            # 2D 배열로 변환 (FAISS는 2D 배열을 기대함)
            if len(embedding.shape) == 1:
                embedding = embedding.reshape(1, -1)
            
            # NaN/Inf 값 검사
            if not np.isfinite(embedding).all():
                print("경고: 임베딩에 NaN 또는 Inf 값이 포함되어 있습니다. 이 항목은 건너뜅니다.")
                return False
            
            # 정규화 (내적 유사도 인덱스인 경우)
            if self.index_type == "IP":
                norm = np.linalg.norm(embedding, axis=1, keepdims=True)
                norm = np.where(norm > 1e-10, norm, 1e-10)  # 0으로 나누기 방지
                embedding = embedding / norm
            
            # 이미지 인덱스에 추가
            self.image_index.add(embedding.astype('float32'))
            self.image_metadata_list.append(metadata)
            
            return True
            
        except Exception as e:
            print(f"인덱스에 항목 추가 중 오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def generate_image_embedding(self, image_path: str, metadata: dict = None) -> np.ndarray:
        """
        이미지 임베딩 생성 (텍스트 임베딩과 동일한 방식 사용)
        
        Args:
            image_path: 이미지 파일 경로
            metadata: 이미지 메타데이터 (제목, 캡션, 태그 등)
            
        Returns:
            이미지 임베딩 벡터 (numpy 배열)
        """
        if not image_path or not os.path.exists(image_path):
            print(f"[경고] 이미지 파일을 찾을 수 없음: {image_path}")
            return np.zeros(self.vector_dimension, dtype=np.float16)
        
        try:
            # 이미지 경로와 메타데이터를 포함한 프롬프트 구성
            prompt = f"Image path: {image_path}"
            
            if metadata:
                # 태그 추출
                tags = metadata.get("tags", [])
                if tags:
                    prompt += f"\nTags: {', '.join(tags)}"
                
                # 제목 추출
                title = metadata.get("title", "")
                if title:
                    prompt += f"\nTitle: {title}"
                
                # 캡션 추출
                caption = metadata.get("caption", "")
                if caption:
                    prompt += f"\nCaption: {caption}"
                
                # 부제목 추출
                subtitle = metadata.get("subtitle", "")
                if subtitle:
                    prompt += f"\nSubtitle: {subtitle}"
                
                # 색인 추출
                index = metadata.get("index", "")
                if index:
                    prompt += f"\nIndex: {index}"
            
            # Hugging Face 모델을 사용하여 임베딩 생성
            try:
                # 토크나이저로 텍스트 인코딩
                inputs = self.tokenizer(prompt, return_tensors="pt", padding=True, truncation=True, max_length=512)
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                # 모델 추론 (그래디언트 계산 없이)
                with torch.no_grad():
                    outputs = self.model(**inputs)
                
                # [CLS] 토큰 임베딩 추출 (첫 번째 토큰)
                embedding = outputs.last_hidden_state[:, 0, :].cpu().numpy()[0]
                
                # 정규화
                norm = np.linalg.norm(embedding)
                if norm > 1e-10:  # 0으로 나누기 방지
                    embedding = embedding / norm
                    
                return embedding
            except Exception as e:
                print(f"Hugging Face 모델 추론 오류: {str(e)}")
                import traceback
                traceback.print_exc()
                return np.zeros(self.vector_dimension)
        except Exception as e:
            print(f"이미지 임베딩 생성 오류: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return np.zeros(self.vector_dimension, dtype=np.float16)
    
    def _process_image_data(self, data, image_base_path="static"):
        """
        이미지 메타데이터 처리 및 인덱싱 - 개선된 버전
        임베딩 차별화를 위한 텍스트 처리 및 메타데이터 활용 강화
        """
        indexed_count = 0
        skipped_count = 0
        empty_text_count = 0
        
        print(f"이미지 메타데이터 처리 시작: 총 {len(data)}개 항목")
        
        for item in tqdm(data, desc="이미지 메타데이터 처리"):
            try:
                if 'metadata' in item:
                    metadata = item['metadata'].copy()
                else:
                    metadata = item.copy()
                
                # 고유 ID 확인 (없으면 생성)
                item_id = metadata.get('id', '')
                if not item_id:
                    item_id = f"img_{uuid.uuid4().hex[:8]}"
                    metadata['id'] = item_id
                
                # 이미지 경로 확인
                image_path = metadata.get('file_path') or metadata.get('image_path')
                if not image_path or not os.path.exists(image_path):
                    print(f"[건너뛰기] 이미지 파일을 찾을 수 없음: {item_id}")
                    skipped_count += 1
                    continue
                
                # ================================================================= #
                # 텍스트 및 메타데이터 추출 및 전처리 (개선된 버전)
                # ================================================================= #
                
                # 1. 필요한 필드만 추출 (title, page_num, file_path, text)
                text = metadata.get('text', '')
                text = text.strip() if isinstance(text, str) else ''
                
                title = metadata.get('title', '')
                title = title.strip() if isinstance(title, str) else ''
                
                page_num = metadata.get('page_num', '')
                file_path = image_path  # 이미 위에서 추출한 image_path 사용
                
                # 필요한 필드만 사용하므로 tags 관련 코드 제거
                
                # 2. text 필드가 비어있는 경우 바로 건너뛰기
                if not text:
                    print(f"[건너뛰기] ID {item_id}: text 필드가 비어있음")
                    empty_text_count += 1
                    continue
                
                # 3. 텍스트 정규화
                # 공백 및 특수문자 정규화
                text = re.sub(r'\s+', ' ', text).strip()
                
                # 텍스트 해시 생성 (로깅용)
                text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
                
                # 4. 임베딩용 메타데이터 구성 (문맥 정보로 활용)
                processed_metadata = {
                    'title': title,
                    'page_num': page_num,
                    'file_path': image_path
                }
                
                # 필요한 필드만 사용하므로 tags 관련 코드 제거
                
                # 5. 텍스트 보강 - 제목이 있고 본문에 제목이 포함되지 않은 경우 제목을 텍스트 앞에 추가
                # 이렇게 하면 제목의 중요 키워드가 임베딩에 반영됨
                if title and title not in text:
                    # 제목을 텍스트 앞에 추가하여 중요도 강화
                    text = f"{title}\n\n{text}"
                
                # ================================================================= #
                
                # 임베딩 생성 (개선된 가중치 부여 방식 적용)
                print(f"ID {item_id} 임베딩 생성 시작: 텍스트 길이 {len(text)}자")
                embedding = self.generate_text_embedding(text)
                
                # 임베딩 유효성 검사
                if embedding is None or not np.any(embedding):
                    print(f"[경고] ID {item_id}: 유효하지 않은 임베딩 생성됨")
                    skipped_count += 1
                    continue
                
                # 임베딩 통계 계산 (디버깅용)
                embedding_norm = np.linalg.norm(embedding)
                embedding_mean = np.mean(embedding)
                embedding_std = np.std(embedding)
                
                print(f"ID {item_id} 임베딩 생성 완료: 노름={embedding_norm:.4f}, 평균={embedding_mean:.4f}, 표준편차={embedding_std:.4f}")
                
                # 메타데이터 정리 및 추가 정보
                metadata['image_path'] = image_path
                
                # con_type 설정 - 기존 con_type이 있으면 유지, 없으면 타입 추론
                if 'con_type' not in metadata:
                    # 파일명이나 경로에 'chart'가 포함되어 있으면 chart 타입으로 설정
                    if 'chart' in image_path.lower() or ('title' in metadata and 'chart' in metadata.get('title', '').lower()):
                        metadata['con_type'] = 'chart'
                    else:
                        metadata['con_type'] = 'image'
                
                metadata['description'] = text[:500] + ('...' if len(text) > 500 else '')  # 설명 필드 추가 (잘라서)
                metadata['embedding'] = embedding  # 임베딩 벡터 저장 (검색 시 활용)
                metadata['text_hash'] = text_hash  # 텍스트 해시 저장 (중복 확인용)
                
                # 인덱스에 추가 - con_type을 content_type으로 사용
                content_type = metadata.get('con_type', 'image')  # 메타데이터에서 con_type 가져오기
                if self.add_to_index(embedding, metadata, content_type):
                    indexed_count += 1
                    if indexed_count % 10 == 0:
                        print(f"진행 상황: {indexed_count}개 인덱싱 완료 (타입: {content_type})")

            except Exception as e:
                import traceback
                print(f"이미지 메타데이터 처리 중 오류 발생: {str(e)}")
                print(f"문제 항목: {item.get('metadata', {}).get('id', 'unknown')}")
                traceback.print_exc()
                skipped_count += 1
        
        # 처리 결과 요약
        print(f"이미지 메타데이터 인덱싱 완료: 총 {len(data)}개 중 {indexed_count}개 성공, {skipped_count}개 건너뛰")
        print(f"건너뛰 이유: 빈 텍스트 {empty_text_count}개, 오류 {skipped_count - empty_text_count}개")
        
        return indexed_count
    
    def process_json_data(self, json_path, image_base_path="static", append_mode=True, content_type="image"):
        """
        이미지 및 차트 메타데이터 JSON 파일을 처리하여 벡터 DB에 저장
        파일 경로나 디렉토리 경로를 받아 처리
        
        Args:
            json_path: JSON 파일 경로 또는 JSON 파일이 있는 디렉토리 경로
            image_base_path: 이미지 파일 기본 경로 (사용되지 않음)
            append_mode: True이면 기존 인덱스에 추가, False이면 덮어쓰기
            content_type: 처리할 데이터 유형 ("image" 또는 "chart")
            
        Returns:
            인덱싱된 항목 수
        """
        if content_type not in ["image", "chart"]:
            raise ValueError("이 시스템은 이미지와 차트 메타데이터 처리를 지원합니다. content_type='image' 또는 'chart'를 사용하세요.")
        
        # 경로 존재 확인
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"경로를 찾을 수 없습니다: {json_path}")
        
        # 디렉토리인지 파일인지 확인
        total_indexed = 0
        if os.path.isdir(json_path):
            print(f"디렉토리 처리 시작: {json_path}")
            json_files = [os.path.join(json_path, f) for f in os.listdir(json_path) 
                         if f.lower().endswith('.json')]
            
            if not json_files:
                print(f"경고: {json_path} 디렉토리에 JSON 파일이 없습니다.")
                return 0
                
            print(f"발견된 JSON 파일 수: {len(json_files)}")
            
            # 처음 파일은 append_mode 적용, 나머지는 무조건 추가
            for i, json_file in enumerate(json_files):
                print(f"\n[{i+1}/{len(json_files)}] 파일 처리 중: {os.path.basename(json_file)}")
                current_append_mode = append_mode if i == 0 else True
                try:
                    indexed = self._process_single_json_file(json_file, image_base_path, current_append_mode, content_type)
                    total_indexed += indexed
                except Exception as e:
                    print(f"경고: {json_file} 처리 중 오류 발생: {str(e)}")
                    import traceback
                    traceback.print_exc()
            
            return total_indexed
        else:
            # 단일 파일 처리
            return self._process_single_json_file(json_path, image_base_path, append_mode, content_type)
    
    def process_directory_recursively(self, dir_path, append_mode=True):
        """
        디렉토리를 재귀적으로 탐색하며 모든 파일을 처리
        """
        total_indexed = 0
        for root, _, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    if file.lower().endswith('.json'):
                        print(f"Processing JSON file: {file_path}")
                        indexed = self._process_single_json_file(file_path, '', append_mode, 'image')
                        total_indexed += indexed
                        append_mode = True  # 첫 파일 이후에는 항상 추가 모드
                    elif file.lower().endswith('.txt'):
                        print(f"Processing text file: {file_path}")
                        with open(file_path, 'r', encoding='utf-8') as f:
                            text_content = f.read()
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            text_content = f.read()
                        metadata = {
                            'source': file_path,
                            'type': 'text',
                            'title': os.path.basename(file_path)
                        }
                        if self.add_text_embedding(text_content, metadata):
                            total_indexed += 1

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    import traceback
                    traceback.print_exc()

        return total_indexed



    def generate_text_embedding(self, text):
        return self.shared_embedding.generate_embedding(text)

    def add_text_embedding(self, text, metadata):
        """
        주어진 텍스트에 대한 임베딩을 생성하고 DB에 추가
        """
        if not text or not isinstance(text, str):
            print("Warning: Invalid text for embedding. Skipping.")
            return False

        try:
            embedding = self.generate_text_embedding(text)
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            if embedding is None:
                return False

            # 임베딩 유효성 검사
            if embedding is None or not np.any(embedding):
                print(f"[경고] 유효하지 않은 임베딩 생성됨")
                return False

            # 임베딩 통계 계산 (디버깅용)
            embedding_norm = np.linalg.norm(embedding)
            embedding_mean = np.mean(embedding)
            embedding_std = np.std(embedding)
            
            print(f"텍스트 임베딩 생성 완료: 노름={embedding_norm:.4f}, 평균={embedding_mean:.4f}, 표준편차={embedding_std:.4f}")
            
            # 메타데이터 정리 및 추가 정보
            metadata['text'] = text[:500] + ('...' if len(text) > 500 else '')  # 설명 필드 추가 (잘라서)
            metadata['embedding'] = embedding  # 임베딩 벡터 저장 (검색 시 활용)
            
            # 인덱스에 추가
            if self.add_to_index(embedding, metadata, "text"):
                print(f"텍스트 인덱싱 완료: {metadata.get('source', 'unknown')}")
                return True
            else:
                return False
        except Exception as e:
            print(f"Error adding text embedding: {e}")
            return False

    def _process_single_json_file(self, json_file_path, image_base_path="static", append_mode=True, content_type="image"):
        """
        이미지 및 차트 메타데이터 JSON 파일을 처리하여 벡터 DB에 저장
        
        Args:
            json_file_path: JSON 파일 경로
            image_base_path: 이미지 파일 기본 경로 (사용되지 않음)
            append_mode: True이면 기존 인덱스에 추가, False이면 덮어쓰기
            content_type: 처리할 데이터 유형 ("image" 또는 "chart")
            
        Returns:
            인덱싱된 항목 수
        """
        # 데이터 로드
        print(f"데이터 파일 로드 중: {json_file_path}")
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"JSON 파일 로드 완료: {json_file_path}")
        except Exception as e:
            raise ValueError(f"JSON 파일 로드 실패: {str(e)}")
        
        # 이미지 메타데이터 추출
        
        # 데이터 구조 확인
        items = []
        
        # 데이터 구조 분석 및 처리
        if isinstance(data, dict) and "metadata" in data:
            print("JSON 구조: metadata 키 포함 (객체 형태)")
            # metadata 내의 각 아이템 처리
            for key, item in data["metadata"].items():
                item["id"] = key
                items.append(item)
        elif isinstance(data, list):
            print("JSON 구조: 배열 형태")
            # 배열 내 각 항목 처리
            for item_obj in data:
                # 각 항목에 metadata 키가 있는지 확인
                if isinstance(item_obj, dict) and "metadata" in item_obj:
                    item = item_obj["metadata"]
                    # id가 없으면 임의로 생성
                    if "id" not in item:
                        item["id"] = f"item_{len(items)}"
                    items.append(item)
                elif isinstance(item_obj, dict):
                    # metadata 키가 없으면 항목 자체를 사용
                    # id가 없으면 임의로 생성
                    if "id" not in item_obj:
                        item_obj["id"] = f"item_{len(items)}"
                    items.append(item_obj)
        else:
            print("JSON 형식 오류: 지원되지 않는 형식입니다. 객체 내 'metadata' 필드 또는 배열 형태여야 합니다.")
            return 0
        
        print(f"처리할 항목 수: {len(items)}")
        
        # 이미지 메타데이터 처리
        if content_type != "image":
            raise ValueError("이 시스템은 이미지 메타데이터 처리만 지원합니다.")
        
        if not append_mode:
            # 덮어쓰기 모드인 경우 기존 인덱스 초기화
            print("이미지 인덱스 초기화 (덮어쓰기 모드)")
            self.image_index = self._create_empty_index()
            self.image_metadata_list = []
        
        # 이미지 데이터 처리
        indexed_count = self._process_image_data(items, image_base_path)
        
        # 인덱스 저장
        if indexed_count > 0:
            self.save_index()
            print(f"인덱스 저장 완료: {indexed_count}개 항목")
        
        return indexed_count
    
    def get_text_embedding(self, text: str) -> np.ndarray:
        """
        텍스트 임베딩 생성 (RAG 시스템에서 사용)
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            텍스트 임베딩 벡터 (numpy 배열)
        """
        return self.generate_text_embedding(text)
        
    def get_image_embedding(self, image_path: str) -> np.ndarray:
        """
        이미지 임베딩 생성 (RAG 시스템에서 사용)
        
        Args:
            image_path: 이미지 파일 경로
            
        Returns:
            이미지 임베딩 벡터 (numpy 배열)
        """
        return self.generate_image_embedding(image_path)
        
    def search_in_index(self, query_embedding: np.ndarray, content_type: str = "image", top_k: int = 5) -> Tuple[np.ndarray, np.ndarray]:
        """
        인덱스에서 검색 (RAG 시스템에서 사용)
        PyTorch를 사용하여 정규화 및 내적 계산을 통한 유사도 검색 수행
        
        Args:
            query_embedding: 검색 쿼리 임베딩
            content_type: 검색할 콘텐츠 유형 ("이미지"만 지원)
            top_k: 반환할 최대 결과 수
            
        Returns:
            (distances, indices): 거리와 인덱스의 튜플
        """
        import torch.nn.functional as F
        
        if content_type != "image":
            raise ValueError("이 시스템은 이미지 메타데이터 처리만 지원합니다.")
        
        if not hasattr(self, 'image_index'):
            raise ValueError("이미지 인덱스를 찾을 수 없습니다.")
            
        # FAISS 사용 방식과 PyTorch 방식 중 선택
        use_pytorch = True  # PyTorch 방식 사용
        
        if use_pytorch:
            try:
                # 쿼리 임베딩을 텐서로 변환
                if len(query_embedding.shape) == 1:
                    query_embedding = query_embedding.reshape(1, -1)
                query_tensor = torch.tensor(query_embedding, device=self.device)
                
                # 인덱스의 모든 임베딩을 텐서로 변환 (이미 저장된 경우 재사용)
                if not hasattr(self, 'index_tensor') or self.index_tensor is None:
                    # FAISS 인덱스에서 모든 벡터 가져오기
                    index_vectors = faiss.extract_index_vector(self.image_index)
                    if index_vectors is None or self.image_index.ntotal == 0:
                        # 인덱스가 비어있으면 FAISS 방식으로 검색
                        return self.image_index.search(query_embedding.astype('float32'), top_k)
                        
                    self.index_tensor = torch.tensor(index_vectors, device=self.device)
                
                # 정규화
                query_tensor = F.normalize(query_tensor, p=2, dim=1)
                index_tensor = F.normalize(self.index_tensor, p=2, dim=1)
                
                # 내적 계산 (코사인 유사도)
                similarities = torch.matmul(query_tensor, index_tensor.T)
                
                # 상위 k개 결과 가져오기
                distances, indices = torch.topk(similarities, k=min(top_k, self.image_index.ntotal))
                
                return distances.cpu().numpy(), indices.cpu().numpy()
                
            except Exception as e:
                print(f"PyTorch 검색 오류, FAISS 방식으로 돌아감: {str(e)}")
                import traceback
                traceback.print_exc()
        
        # 오류 발생 시 또는 PyTorch 방식을 사용하지 않는 경우 FAISS 방식 사용
        if len(query_embedding.shape) == 1:
            query_embedding = query_embedding.reshape(1, -1)
            
        # 정규화 (내적 유사도 인덱스인 경우)
        if self.index_type == "IP":
            norm = np.linalg.norm(query_embedding, axis=1, keepdims=True)
            norm = np.where(norm > 1e-10, norm, 1e-10)
            query_embedding = query_embedding / norm
            
        return self.image_index.search(query_embedding.astype('float32'), top_k)
            
    def get_metadata(self, index: int, content_type: str = "image") -> Dict[str, Any]:
        """
        인덱스에 해당하는 메타데이터 조회 (RAG 시스템에서 사용)
        
        Args:
            index: 메타데이터 인덱스
            content_type: 콘텐츠 유형 ("이미지"만 지원)
            
        Returns:
            메타데이터 딕셔너리
        """
        if content_type != "image":
            raise ValueError("이 시스템은 이미지 메타데이터 처리만 지원합니다.")
            
        if 0 <= index < len(self.image_metadata_list):
            return self.image_metadata_list[index]
        else:
            raise IndexError(f"이미지 메타데이터에서 인덱스 {index}를 찾을 수 없습니다.")
            
    def save_index(self, content_type_to_save: str = "image"):
        """이미지 메타데이터 인덱스와 메타데이터 저장
        FAISS 인덱스(.faiss) 파일과 메타데이터(.pkl) 파일을 생성합니다.
        """
        try:
            import pickle
            os.makedirs(self.index_path, exist_ok=True)
            
            if content_type_to_save != "image":
                print("이 시스템은 이미지 메타데이터만 지원합니다.")
                return False

            if hasattr(self, 'image_index') and hasattr(self, 'image_index_path') and hasattr(self, 'image_metadata_list'):
                # FAISS 인덱스 파일 저장
                faiss.write_index(self.image_index, self.image_index_path)
                
                # 메타데이터를 PKL 파일로 저장
                image_meta_path = os.path.join(self.index_path, "image_metadata.pkl")
                with open(image_meta_path, 'wb') as f:
                    pickle.dump(self.image_metadata_list, f)
                
                # 이전 버전과의 호환성을 위해 JSON 파일도 저장 (선택사항)
                # NumPy 배열을 JSON으로 저장할 수 없으므로 임베딩 배열 제외
                image_json_path = os.path.join(self.index_path, "image_metadata.json")
                json_safe_metadata = []
                for item in self.image_metadata_list:
                    # 임시 사본을 만들어 embedding 필드 제거
                    json_item = item.copy()
                    if 'embedding' in json_item:
                        del json_item['embedding']
                    json_safe_metadata.append(json_item)
                
                with open(image_json_path, 'w', encoding='utf-8') as f:
                    json.dump(json_safe_metadata, f, ensure_ascii=False, indent=4)
                
                print(f"이미지 인덱스 ({self.image_index.ntotal}개 항목) 저장 완료: {self.image_index_path}")
                print(f"이미지 메타데이터 저장 완료: {image_meta_path}")
                return True
            else:
                print("경고: 이미지 인덱스, 경로 또는 메타데이터 리스트가 제대로 초기화되지 않았습니다.")
                return False
            
        except Exception as e:
            print(f"인덱스 저장 중 오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
            
    def load_index(self):
        """저장된 이미지 인덱스와 메타데이터 로드
        FAISS 인덱스(.faiss)와 메타데이터(.pkl) 파일을 로드합니다.
        """
        try:
            import pickle
            
            # 이미지 인덱스 로드
            if os.path.exists(self.image_index_path):
                self.image_index = faiss.read_index(self.image_index_path)
                print(f"이미지 인덱스 로드 완료: {self.image_index.ntotal} 개의 벡터")
                
                # 이미지 메타데이터 로드 - PKL 파일 우선
                image_pkl_path = os.path.join(self.index_path, "image_metadata.pkl")
                image_json_path = os.path.join(self.index_path, "image_metadata.json")
                
                if os.path.exists(image_pkl_path):
                    with open(image_pkl_path, 'rb') as f:
                        self.image_metadata_list = pickle.load(f)
                    print(f"PKL 파일에서 이미지 메타데이터 로드 완료: {len(self.image_metadata_list)} 항목")
                # PKL 파일이 없는 경우 JSON 파일 사용 (후방 호환성)
                elif os.path.exists(image_json_path):
                    with open(image_json_path, 'r', encoding='utf-8') as f:
                        self.image_metadata_list = json.load(f)
                    print(f"JSON 파일에서 이미지 메타데이터 로드 완료: {len(self.image_metadata_list)} 항목")
                else:
                    print(f"경고: 이미지 메타데이터 파일을 찾을 수 없습니다.")
                    self.image_metadata_list = []
            else:
                print(f"경고: 이미지 인덱스 파일을 찾을 수 없습니다: {self.image_index_path}")
            
            return True
            
        except Exception as e:
            print(f"인덱스 로드 중 오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

# 사용 예시
if __name__ == "__main__":
    import argparse

    # 명령행 인수 처리
    parser = argparse.ArgumentParser(description="이미지 메타데이터 전용 임베딩 생성 시스템")
    parser.add_argument("--json", "-j", help="처리할 JSON 파일 경로 또는 디렉토리")
    parser.add_argument("--index", "-i", default="faiss_test", help="인덱스 저장 경로")
    parser.add_argument("--model", "-m", default="Qwen/Qwen3-Embedding-4B", help="사용할 모델 이름")
    parser.add_argument("--overwrite", "-o", action="store_true", help="기존 인덱스를 덮어씀")
    parser.add_argument("--type", "-t", choices=["image"], default="image", 
                        help="처리할 데이터 유형 (이미지 메타데이터만 지원)")
    parser.add_argument("--base-path", "-b", default="", help="이미지 파일 기본 경로 (사용하지 않음, 절대 경로 사용)")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")
    
    args = parser.parse_args()
    
    # 벡터 DB 서비스 초기화
    index_path = "faiss_test" if args.index == "text_index" else args.index
    vector_db_service = VectorDBService(
        model_name=args.model,
        index_path=index_path
    )
    
    # JSON 파일 처리
    if args.json:
        try:
            # append_mode 설정 (--overwrite 옵션이 있으면 False, 없으면 True)
            append_mode = not args.overwrite
            if os.path.isdir(args.json):
                indexed_count = vector_db_service.process_directory_recursively(
                    args.json,
                    append_mode=append_mode
                )
            else:
                indexed_count = vector_db_service.process_json_data(
                    args.json, 
                    append_mode=append_mode,
                    content_type=args.type
                )
            
            if indexed_count > 0:
                # 인덱스 저장 (처리된 content_type 명시)
                if vector_db_service.save_index(content_type_to_save=args.type):
                    print(f"인덱스 저장 완료: {vector_db_service.index_path} (유형: {args.type})")

                else:
                    print(f"{args.type} 유형의 인덱스 저장 실패.")
            else:
                print("처리할 데이터가 없거나, 인덱싱된 항목이 없습니다.")
        except Exception as e:
            print(f"JSON 데이터 처리 실패: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    # 사용법 출력
    if not args.json:
        print("사용법:")
        print("  이미지 메타데이터 임베딩 생성: python embedding_system.py --json <json_file_path_or_directory> [--index <index_path>] [--model <model_name>] [--overwrite]")
        print("  예시 (단일 파일): python embedding_system.py --json /path/to/image_metadata.json --index test_index")
        print("  예시 (디렉토리): python embedding_system.py --json /home/nextits2/.conda/envs/workbox/gui/chatbot/backend/nextits_data/Results/5.Completion_results/image")
        print("\n지원하는 데이터 유형: 이미지 메타데이터만")
        print("\n참고: 검색 기능은 rag_system.py에서 제공합니다.")
