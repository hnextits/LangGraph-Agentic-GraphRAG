#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 페이지별 레벨 확인 테스트 코드 (사용자 제공 형식 기반)
"""

import fitz  # PyMuPDF
import sys
from pathlib import Path
from datetime import datetime
from pprint import pprint

# 스크립트 위치를 기준으로 backend/ 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

def main():
    # PDF 파일 경로 설정
    pdf_path = BASE_DIR / "data_pipeline" / "doc" / "원가회계데이터샘플-250401.pdf"
    
    if not Path(pdf_path).exists():
        print(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return
    
    print(f"PDF 분석 시작: {pdf_path}")
    print("=" * 80)
    
    # 마크다운 내용을 저장할 리스트
    md_content = []
    md_content.append(f"# PDF 레벨 분석 결과")
    md_content.append(f"")
    md_content.append(f"**파일명:** {Path(pdf_path).name}")
    md_content.append(f"**분석 시간:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md_content.append(f"")
    
    # PDF 열기
    doc = fitz.open(pdf_path)
    
    # TOC 출력 및 저장
    print("\n1. TOC 분석")
    md_content.append("## 1. TOC (목차) 분석")
    md_content.append("")
    
    toc = doc.get_toc(simple=False)
    if toc:
        md_content.append(f"총 TOC 항목 수: {len(toc)}")
        md_content.append("")
        md_content.append("| 레벨 | 제목 | 페이지 |")
        md_content.append("|------|------|--------|")
        
        for i, item in enumerate(toc):
            level, title, page = item[0], item[1], item[2]
            print(f"TOC {i+1}: 레벨 {level}, 제목: '{title}', 페이지: {page}")
            md_content.append(f"| {level} | {title} | {page} |")
    else:
        print("TOC가 없습니다.")
        md_content.append("TOC가 없습니다.")
    
    md_content.append("")
    
    # 페이지 정보 출력 및 저장
    print("\n2. 페이지 정보")
    md_content.append("## 2. 페이지 정보")
    md_content.append("")
    
    total_pages = doc.page_count
    print(f"총 페이지 수: {total_pages}")
    md_content.append(f"**총 페이지 수:** {total_pages}")
    md_content.append("")
    
    # 페이지별 레벨 분석 및 저장
    print("\n3. 페이지별 레벨 분석")
    md_content.append("## 3. 페이지별 레벨 분석")
    md_content.append("")
    
    page_levels = {}
    if toc:
        # TOC 기반 페이지 레벨 매핑
        for i, item in enumerate(toc):
            level, title, page = item[0], item[1], item[2]
            if page not in page_levels or level < page_levels[page]:
                page_levels[page] = level
        
        # 모든 페이지에 대해 레벨 할당
        current_level = None
        md_content.append("| 페이지 | 레벨 | 비고 |")
        md_content.append("|--------|------|------|")
        
        for page_num in range(1, total_pages + 1):
            if page_num in page_levels:
                current_level = page_levels[page_num]
                note = "TOC 시작 페이지"
            else:
                note = "상속된 레벨"
            
            print(f"페이지 {page_num}: 레벨 {current_level if current_level else 'N/A'}")
            md_content.append(f"| {page_num} | {current_level if current_level else 'N/A'} | {note} |")
    else:
        md_content.append("TOC가 없어 페이지별 레벨을 분석할 수 없습니다.")
        for page_num in range(1, total_pages + 1):
            print(f"페이지 {page_num}: 레벨 N/A (TOC 없음)")
    
    md_content.append("")
    
    # 필터링 결과 출력 및 저장
    print("\n4. 필터링 결과")
    md_content.append("## 4. 필터링 결과")
    md_content.append("")
    
    if toc:
        levels = [item[0] for item in toc]
        has_level_2_or_higher = any(level >= 2 for level in levels)
        
        if has_level_2_or_higher:
            level_1_pages = [item[2] for item in toc if item[0] == 1]
            filtered_pages = []
            current_level = None
            
            for page_num in range(1, total_pages + 1):
                if page_num in page_levels:
                    current_level = page_levels[page_num]
                
                if current_level != 1:
                    filtered_pages.append(page_num)
            
            print(f"레벨 2 이상이 존재하므로 레벨 1 페이지를 제외합니다.")
            print(f"제외될 레벨 1 페이지: {level_1_pages}")
            print(f"변환될 페이지 수: {len(filtered_pages)}/{total_pages}")
            
            md_content.append(f"**필터링 적용:** 레벨 2 이상이 존재하므로 레벨 1 페이지를 제외")
            md_content.append(f"**제외될 레벨 1 페이지:** {level_1_pages}")
            md_content.append(f"**변환될 페이지 수:** {len(filtered_pages)}/{total_pages}")
            md_content.append(f"**변환될 페이지:** {filtered_pages}")
        else:
            print("레벨 2 이상이 없으므로 모든 페이지를 변환합니다.")
            print(f"변환될 페이지 수: {total_pages}/{total_pages}")
            
            md_content.append(f"**필터링 적용:** 레벨 2 이상이 없으므로 모든 페이지를 변환")
            md_content.append(f"**변환될 페이지 수:** {total_pages}/{total_pages}")
    else:
        print("TOC가 없으므로 모든 페이지를 변환합니다.")
        md_content.append("**필터링 적용:** TOC가 없으므로 모든 페이지를 변환")
        md_content.append(f"**변환될 페이지 수:** {total_pages}/{total_pages}")
    
    md_content.append("")
    
    # 레벨 매핑 출력 및 저장
    print("\n5. 레벨 매핑")
    md_content.append("## 5. 레벨 매핑 요약")
    md_content.append("")
    
    if toc:
        level_counts = {}
        for item in toc:
            level = item[0]
            level_counts[level] = level_counts.get(level, 0) + 1
        
        print("레벨별 항목 수:")
        md_content.append("**레벨별 항목 수:**")
        md_content.append("")
        
        for level in sorted(level_counts.keys()):
            count = level_counts[level]
            print(f"  레벨 {level}: {count}개")
            md_content.append(f"- 레벨 {level}: {count}개")
    else:
        print("TOC가 없어 레벨 매핑을 생성할 수 없습니다.")
        md_content.append("TOC가 없어 레벨 매핑을 생성할 수 없습니다.")
    
    doc.close()
    
    # 마크다운 파일로 저장
    md_text = "\n".join(md_content)
    pdf_name = Path(pdf_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_filename = f"pdf_level_analysis_{pdf_name}_{timestamp}.md"
    md_path = Path(pdf_path).parent / md_filename
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_text)
    
    print(f"\n결과가 저장되었습니다: {md_path}")
    
    print("\n분석 완료!")


if __name__ == "__main__":
    main()
