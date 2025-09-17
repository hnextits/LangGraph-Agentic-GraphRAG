"""
Simple text summarization module without using LLM.
Uses extractive summarization techniques to create summaries from markdown files.
"""
import re
import math
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """Clean text by removing extra whitespace and special characters."""
    # Remove markdown headers, links, and other formatting
    text = re.sub(r'#+ ', '', text)  # Remove headers
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Replace links with just the text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Remove bold formatting
    text = re.sub(r'\*([^*]+)\*', r'\1', text)  # Remove italic formatting
    text = re.sub(r'`([^`]+)`', r'\1', text)  # Remove code formatting
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)  # Remove list markers
    text = re.sub(r'\n\s*\n+', '\n\n', text)  # Normalize multiple newlines
    return text.strip()

def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    # Simple sentence splitting by punctuation followed by space or newline
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def calculate_word_frequencies(sentences: List[str]) -> Dict[str, int]:
    """Calculate word frequencies across all sentences."""
    word_freq = {}
    for sentence in sentences:
        words = re.findall(r'\w+', sentence.lower())
        for word in words:
            if len(word) > 1:  # Ignore single-character words
                word_freq[word] = word_freq.get(word, 0) + 1
    return word_freq

def score_sentences(sentences: List[str], word_freq: Dict[str, int]) -> List[Tuple[int, float, str]]:
    """Score sentences based on word frequency and position."""
    scores = []
    for i, sentence in enumerate(sentences):
        words = re.findall(r'\w+', sentence.lower())
        if not words:
            continue
            
        # Score based on word frequency
        word_score = sum(word_freq.get(word, 0) for word in words) / len(words)
        
        # Position score (sentences at beginning and end are more important)
        position_score = 1.0
        if i < len(sentences) * 0.2:  # First 20% of sentences
            position_score = 1.5
        elif i > len(sentences) * 0.8:  # Last 20% of sentences
            position_score = 1.2
            
        # Final score
        final_score = word_score * position_score
        scores.append((i, final_score, sentence))
    
    return scores

def summarize_text(text: str, ratio: float = 0.3) -> str:
    """
    Summarize text using extractive summarization.
    
    Args:
        text: The text to summarize
        ratio: The ratio of sentences to keep (0.0 to 1.0)
    
    Returns:
        Summarized text
    """
    if not text or text.isspace():
        return "요약할 텍스트가 없습니다."
    
    # Clean and prepare text
    cleaned_text = clean_text(text)
    sentences = split_into_sentences(cleaned_text)
    
    if len(sentences) <= 3:
        return cleaned_text  # Text is already short, return as is
    
    # Calculate word frequencies
    word_freq = calculate_word_frequencies(sentences)
    
    # Score sentences
    scored_sentences = score_sentences(sentences, word_freq)
    
    # Sort by score
    scored_sentences.sort(key=lambda x: x[1], reverse=True)
    
    # Select top sentences based on ratio
    num_sentences = max(3, math.ceil(len(sentences) * ratio))
    selected_indices = [item[0] for item in scored_sentences[:num_sentences]]
    selected_indices.sort()  # Sort to maintain original order
    
    # Reconstruct summary
    summary = " ".join(sentences[i] for i in selected_indices)
    return summary

def summarize_markdown_file(file_path: str, ratio: float = 0.3) -> str:
    """
    Read a markdown file and summarize its content.
    
    Args:
        file_path: Path to the markdown file
        ratio: The ratio of sentences to keep (0.0 to 1.0)
    
    Returns:
        Summarized text
    """
    try:
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return "요약할 파일을 찾을 수 없습니다."
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if not content or content.isspace():
            logger.warning(f"Empty file: {file_path}")
            return "요약할 텍스트가 없습니다."
        
        return summarize_text(content, ratio)
    except Exception as e:
        logger.error(f"Error summarizing file {file_path}: {e}")
        return f"파일 요약 중 오류가 발생했습니다: {str(e)}"

if __name__ == "__main__":
    # Example usage
    import sys
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        ratio = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
        summary = summarize_markdown_file(file_path, ratio)
        print(summary)
    else:
        print("Usage: python first_summary_no_llm.py <file_path> [ratio]")
