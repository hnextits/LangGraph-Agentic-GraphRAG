"""
Segment-based document processor for NotebookLM-style mindmap generation.
This module handles document segmentation, keyword extraction, and topic clustering
without requiring embeddings or vector databases.
"""

import re
import nltk
import hashlib
from typing import List, Dict, Any, Set, Tuple
from collections import defaultdict, Counter
import logging

logger = logging.getLogger("mindmap_generator")


class DocumentSegment:
    """Represents a single segment of a document with tracking information."""
    
    def __init__(self, segment_id: str, text: str, start_pos: int, end_pos: int):
        self.segment_id = segment_id
        self.text = text
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.keywords: Set[str] = set()
        self.entities: Set[str] = set()
        
    def __repr__(self):
        return f"Segment({self.segment_id}, {len(self.text)} chars, {len(self.keywords)} keywords)"


class SegmentProcessor:
    """Handles document segmentation and keyword analysis."""
    def __init__(self):
        self.content: str = ""
        self.segments: List[DocumentSegment] = []
        self.segment_map: Dict[str, DocumentSegment] = {}

    def process(self, content: str):
        """Processes the given document content."""
        self.content = content
        self.segments = self._split_into_segments(content)
        self.segment_map = {seg.segment_id: seg for seg in self.segments}

    def get_all_segments(self) -> List[DocumentSegment]:
        """Returns all processed document segments."""
        return self.segments
        
    def _split_into_segments(self, content: str) -> List[DocumentSegment]:
        """Split document into meaningful segments."""
        
        # This implementation is similar to fixed-size segmentation, which was the default.
        # We'll keep this logic.
        # Ensure required NLTK data is downloaded
        for resource in ['punkt', 'punkt_tab']:
            try:
                nltk.data.find(f'tokenizers/{resource}')
            except LookupError:
                logger.info(f"NLTK resource '{resource}' not found. Downloading...")
                nltk.download(resource)

        sentences = nltk.sent_tokenize(content)
        
        segments = []
        segment_idx = 0
        current_chunk = []
        current_length = 0
        current_pos = 0
        chunk_size = 500 # Default chunk size

        for sentence in sentences:
            sentence_len = len(sentence)
            if current_length + sentence_len > chunk_size and current_chunk:
                # Create segment
                segment_text = ' '.join(current_chunk)
                segment_id = f"seg_{segment_idx:03d}"
                start_pos = content.find(segment_text, current_pos)
                end_pos = start_pos + len(segment_text)
                
                segment = DocumentSegment(
                    segment_id=segment_id,
                    text=segment_text,
                    start_pos=start_pos,
                    end_pos=end_pos
                )
                segments.append(segment)
                
                segment_idx += 1
                current_pos = end_pos
                current_chunk = [sentence]
                current_length = sentence_len
            else:
                current_chunk.append(sentence)
                current_length += sentence_len
        
        # Add final segment
        if current_chunk:
            segment_text = ' '.join(current_chunk)
            segment_id = f"seg_{segment_idx:03d}"
            start_pos = content.find(segment_text, current_pos)
            end_pos = start_pos + len(segment_text)
            
            segment = DocumentSegment(
                segment_id=segment_id,
                text=segment_text,
                start_pos=start_pos,
                end_pos=end_pos
            )
            segments.append(segment)
        
        logger.info(f"Document segmented into {len(segments)} segments")
        return segments
    
    def _segment_by_paragraph(self, content: str) -> List[DocumentSegment]:
        """Segment by paragraph breaks (double newlines or markdown headers)."""
        segments = []
        
        # Split by double newlines or markdown headers
        pattern = r'\n\s*\n|^#{1,6}\s+.*$'
        parts = re.split(pattern, content, flags=re.MULTILINE)
        
        current_pos = 0
        segment_idx = 0
        
        for part in parts:
            part = part.strip()
            if not part or len(part) < 50:  # Skip very short segments
                current_pos += len(part) + 2  # Account for newlines
                continue
                
            segment_id = f"seg_{segment_idx:03d}"
            
            # Find actual position in original content
            start_pos = content.find(part, current_pos)
            end_pos = start_pos + len(part)
            
            segment = DocumentSegment(
                segment_id=segment_id,
                text=part,
                start_pos=start_pos,
                end_pos=end_pos
            )
            segments.append(segment)
            
            current_pos = end_pos
            segment_idx += 1
            
        return segments
    
    def _segment_by_semantic_breaks(self, content: str) -> List[DocumentSegment]:
        """Segment by semantic breaks (topic shifts, headers, etc)."""
        # Look for markdown headers, bullet points, numbered lists
        pattern = r'(?:^#{1,6}\s+.*$|^\d+\.\s+|^[-*]\s+)'
        
        segments = []
        lines = content.split('\n')
        current_segment = []
        current_pos = 0
        segment_idx = 0
        
        for line in lines:
            if re.match(pattern, line.strip()) and current_segment:
                # Start new segment
                segment_text = '\n'.join(current_segment).strip()
                if len(segment_text) >= 50:
                    segment_id = f"seg_{segment_idx:03d}"
                    start_pos = content.find(segment_text, current_pos)
                    end_pos = start_pos + len(segment_text)
                    
                    segment = DocumentSegment(
                        segment_id=segment_id,
                        text=segment_text,
                        start_pos=start_pos,
                        end_pos=end_pos
                    )
                    segments.append(segment)
                    segment_idx += 1
                    current_pos = end_pos
                    
                current_segment = [line]
            else:
                current_segment.append(line)
        
        # Add final segment
        if current_segment:
            segment_text = '\n'.join(current_segment).strip()
            if len(segment_text) >= 50:
                segment_id = f"seg_{segment_idx:03d}"
                start_pos = content.find(segment_text, current_pos)
                end_pos = start_pos + len(segment_text)
                
                segment = DocumentSegment(
                    segment_id=segment_id,
                    text=segment_text,
                    start_pos=start_pos,
                    end_pos=end_pos
                )
                segments.append(segment)
        
        return segments
    
    def _segment_by_fixed_size(self, content: str, chunk_size: int = 500) -> List[DocumentSegment]:
        """Segment by fixed character size with sentence boundary awareness."""
        segments = []
        segment_idx = 0
        
        # Split into sentences first
        sentences = re.split(r'(?<=[.!?])\s+', content)
        
        current_chunk = []
        current_length = 0
        current_pos = 0
        
        for sentence in sentences:
            sentence_len = len(sentence)
            
            if current_length + sentence_len > chunk_size and current_chunk:
                # Create segment
                segment_text = ' '.join(current_chunk)
                segment_id = f"seg_{segment_idx:03d}"
                start_pos = content.find(segment_text, current_pos)
                end_pos = start_pos + len(segment_text)
                
                segment = DocumentSegment(
                    segment_id=segment_id,
                    text=segment_text,
                    start_pos=start_pos,
                    end_pos=end_pos
                )
                segments.append(segment)
                
                segment_idx += 1
                current_pos = end_pos
                current_chunk = [sentence]
                current_length = sentence_len
            else:
                current_chunk.append(sentence)
                current_length += sentence_len
        
        # Add final segment
        if current_chunk:
            segment_text = ' '.join(current_chunk)
            segment_id = f"seg_{segment_idx:03d}"
            start_pos = content.find(segment_text, current_pos)
            end_pos = start_pos + len(segment_text)
            
            segment = DocumentSegment(
                segment_id=segment_id,
                text=segment_text,
                start_pos=start_pos,
                end_pos=end_pos
            )
            segments.append(segment)
        
        logger.info(f"Document segmented into {len(segments)} segments")
        return segments
    
    def get_segment_text(self, segment_id: str) -> str:
        """Get text content for a segment ID."""
        segment = self.segment_map.get(segment_id)
        return segment.text if segment else ""
    
    def get_segments_for_cluster(self, cluster: Dict[str, Any]) -> List[DocumentSegment]:
        """Get all segment objects for a cluster."""
        return [
            self.segment_map[seg_id] 
            for seg_id in cluster['segment_ids'] 
            if seg_id in self.segment_map
        ]
