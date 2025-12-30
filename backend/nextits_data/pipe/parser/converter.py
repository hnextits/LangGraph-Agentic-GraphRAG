import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Union
import xml.etree.ElementTree as ET

# 지원 확장자 집합
SUPPORTED_OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".hwp",
    ".hwpx",
}


def is_office_file(file_path: str) -> bool:
    """Office/HWP 류 파일 여부"""
    return Path(file_path).suffix.lower() in SUPPORTED_OFFICE_EXTENSIONS


def _run_soffice(cmd: list) -> subprocess.CompletedProcess:
    print(f"[parser] 실행: {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _which_or_warn(cmd_name: str) -> Optional[str]:
    path = shutil.which(cmd_name)
    if not path:
        print(f"[parser] '{cmd_name}' 명령을 찾을 수 없습니다. 설치를 확인하세요.")
    return path


def convert_hwp_to_pdf_via_hwp5html(input_path: str, output_dir: str) -> Optional[str]:
    """
    HWP 전용 폴백: hwp5html → wkhtmltopdf.
    필요한 도구:
      - hwp5html (pyhwp 설치 시 제공)
      - wkhtmltopdf
    """
    hwp5html = _which_or_warn("hwp5html")
    wkhtmltopdf = _which_or_warn("wkhtmltopdf")
    if not (hwp5html and wkhtmltopdf):
        return None
    in_path = Path(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{in_path.stem}.html"
    pdf_path = out_dir / f"{in_path.stem}.pdf"

    try:
        # HWP -> HTML
        print(f"[parser] hwp5html 변환: {in_path} -> {html_path}")
        with open(html_path, "w", encoding="utf-8") as f:
            html_proc = subprocess.run(
                [hwp5html, str(in_path)],
                stdout=f,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        if html_proc.returncode != 0:
            print(f"[parser] hwp5html 실패 (code {html_proc.returncode}): {html_proc.stderr}")
            return None

        # HTML -> PDF
        print(f"[parser] wkhtmltopdf 변환: {html_path} -> {pdf_path}")
        pdf_proc = subprocess.run(
            [wkhtmltopdf, str(html_path), str(pdf_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if pdf_proc.returncode != 0:
            print(f"[parser] wkhtmltopdf 실패 (code {pdf_proc.returncode}): {pdf_proc.stderr}")
            return None

        if pdf_path.exists():
            print(f"[parser] HWP 폴백 변환 성공: {pdf_path}")
            return str(pdf_path)
        else:
            print("[parser] wkhtmltopdf 완료했지만 PDF를 찾지 못했습니다.")
            return None
    except Exception as e:
        print(f"[parser] HWP 폴백 변환 중 예외 발생: {e}")
        return None


def convert_pdf_to_pngs(pdf_path: str, output_dir: str, stem: str, dpi: int = 300) -> List[str]:
    """PDF → PNG 렌더링 공통 함수."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png_dir = out_dir / f"{stem}_pages"
    png_dir.mkdir(parents=True, exist_ok=True)
    png_pattern = str(png_dir / f"{stem}_page-%03d.png")

    gs_cmd = [
        "gs",
        "-sDEVICE=png16m",
        f"-r{dpi}",
        "-o",
        png_pattern,
        pdf_path,
    ]
    print(f"[parser] PDF→PNG 렌더링: {' '.join(gs_cmd)}")
    gs_result = subprocess.run(
        gs_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if gs_result.returncode != 0:
        print(f"[parser] PDF→PNG 렌더링 실패 (code {gs_result.returncode}): {gs_result.stderr}")
        return []

    pngs = sorted(png_dir.glob("*.png"))
    if pngs:
        print(f"[parser] PDF→PNG 변환 성공: {len(pngs)}개 생성 -> {png_dir}")
    else:
        print("[parser] PDF→PNG 렌더링 후 파일을 찾지 못했습니다.")
    return [str(p) for p in pngs]


def _hwpx_unit_to_px(value: Optional[str]) -> Optional[str]:
    """HWP 단위(1/100 mm 기반) 값을 px로 대략 변환."""
    if not value:
        return None
    try:
        # HWPUNIT(1/100 mm) -> mm -> px (약 3.78px per mm)
        mm = int(value) / 100.0
        px = int(mm * 3.78)
        return f"{max(px, 1)}px"
    except (ValueError, TypeError):
        return None


def _looks_like_hwpx_archive(file_path: Union[str, Path]) -> bool:
    """확장자는 .hwp라도 내부가 HWPX(Zip/XML) 구조인지 감지."""
    path = Path(file_path)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return any(
                name.startswith("Contents/") and name.endswith(".xml")
                for name in zf.namelist()
            )
    except zipfile.BadZipFile:
        return False


def _hwpx_to_html(input_path: str, output_dir: str) -> Optional[Path]:
    """
    HWPX를 HTML로 변환 (텍스트+표 포함). 레이아웃/이미지 최소 보존.
    """
    in_path = Path(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{in_path.stem}.html"

    try:
        paragraphs: List[dict] = []
        consumed_paragraph_ids = set()
        body_blacklist = set()
        table_blocks: List[dict] = []

        ns = {
            "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
            "hh": "http://www.hancom.co.kr/hwpml/2011/head",
        }

        def _para_text(para) -> Optional[str]:
            texts = []
            for t_node in para.findall(".//hp:t", ns):
                if t_node.text:
                    stripped = t_node.text.strip()
                    if stripped:
                        texts.append(stripped)
            joined = " ".join(texts).strip()
            return joined or None

        def _collect_paragraphs_outside_tables(node) -> List[dict]:
            collected: List[dict] = []

            def traverse(elem, inside_table: bool = False):
                tag = elem.tag
                is_table = tag == "{http://www.hancom.co.kr/hwpml/2011/paragraph}tbl"
                current_inside = inside_table or is_table
                if tag == "{http://www.hancom.co.kr/hwpml/2011/paragraph}p" and not current_inside:
                    has_table_child = elem.find(".//hp:tbl", ns) is not None
                    if has_table_child:
                        return
                    para_id = elem.attrib.get("id")
                    is_consumed = para_id and para_id in consumed_paragraph_ids
                    if not is_consumed:
                        text = _para_text(elem)
                        if text and text not in body_blacklist:
                            collected.append(
                                {
                                    "text": text,
                                    "page_break": elem.attrib.get("pageBreak") in {"1", "true", "TRUE"},
                                }
                            )
                for child in list(elem):
                    traverse(child, current_inside)

            traverse(node, inside_table=False)
            return collected

        def _collect_tables(root) -> List[dict]:
            tables = []
            for tbl in root.findall(".//hp:tbl", ns):
                table_info = {
                    "col_widths": [],
                    "rows": [],
                }

                grid = tbl.find("./hp:tblGrid", ns)
                if grid is not None:
                    for col in grid.findall("./hp:gridCol", ns):
                        table_info["col_widths"].append(
                            _hwpx_unit_to_px(col.attrib.get("width"))
                        )

                col_cnt = int(tbl.attrib.get("colCnt", len(table_info["col_widths"]) or 0))
                occupied = set()
                row_idx = 0
                for tr in tbl.findall("./hp:tr", ns):
                    row_cells = []
                    col_idx = 0
                    while (row_idx, col_idx) in occupied:
                        col_idx += 1

                    for tc in tr.findall("./hp:tc", ns):
                        while (row_idx, col_idx) in occupied:
                            col_idx += 1
                        cell_span = tc.find("./hp:cellSpan", ns)
                        colspan = int(cell_span.attrib.get("colSpan", "1")) if cell_span is not None else 1
                        rowspan = int(cell_span.attrib.get("rowSpan", "1")) if cell_span is not None else 1

                        cell_sz = tc.find("./hp:cellSz", ns)
                        width_style = _hwpx_unit_to_px(cell_sz.attrib.get("width")) if cell_sz is not None else None
                        height_style = _hwpx_unit_to_px(cell_sz.attrib.get("height")) if cell_sz is not None else None

                        margin_style = []
                        cell_margin = tc.find("./hp:cellMargin", ns)
                        if cell_margin is not None:
                            top = _hwpx_unit_to_px(cell_margin.attrib.get("top"))
                            right = _hwpx_unit_to_px(cell_margin.attrib.get("right"))
                            bottom = _hwpx_unit_to_px(cell_margin.attrib.get("bottom"))
                            left = _hwpx_unit_to_px(cell_margin.attrib.get("left"))
                            padding_vals = [v or "4px" for v in [top, right, bottom, left]]
                            margin_style.append(f"padding:{' '.join(padding_vals)};")

                        style_parts = margin_style or ["padding:6px;"]
                        if width_style:
                            style_parts.append(f"min-width:{width_style};")
                        if height_style:
                            style_parts.append(f"min-height:{height_style};")

                        cell_paragraphs = []
                        for para in tc.findall(".//hp:p", ns):
                            text = _para_text(para)
                            if not text:
                                continue
                            para_id = para.attrib.get("id")
                            if para_id:
                                consumed_paragraph_ids.add(para_id)
                            cell_paragraphs.append(text)
                            body_blacklist.add(text)
                        content = "<br/>".join(cell_paragraphs) if cell_paragraphs else "&nbsp;"

                        is_header = tc.attrib.get("header") == "1"

                        row_cells.append(
                            {
                                "content": content,
                                "colspan": colspan,
                                "rowspan": rowspan,
                                "is_header": is_header,
                                "style": "".join(style_parts),
                            }
                        )

                        for r in range(rowspan):
                            for c in range(colspan):
                                if r == 0 and c == 0:
                                    continue
                                occupied.add((row_idx + r, col_idx + c))
                        col_idx += colspan
                    table_info["rows"].append(row_cells)
                    row_idx += 1
                    if col_cnt and col_idx < col_cnt:
                        occupied = {pos for pos in occupied if pos[0] >= row_idx}
                tables.append(table_info)
            return tables

        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(in_path, "r") as zf:
                zf.extractall(tmpdir)

            contents_dir = Path(tmpdir) / "Contents"
            xml_files = sorted(contents_dir.glob("*.xml"))
            if not xml_files:
                print("[parser] HWPX 폴백: XML을 찾지 못했습니다.")
                return None

            for xf in xml_files:
                try:
                    tree = ET.parse(xf)
                    root = tree.getroot()
                    paragraphs.extend(_collect_paragraphs_outside_tables(root))
                    table_blocks.extend(_collect_tables(root))
                except Exception as e:
                    print(f"[parser] XML 파싱 중 예외 발생: {e}")
                    continue

        if not paragraphs and not table_blocks:
            print("[parser] HWPX 폴백: 추출된 텍스트/표가 없습니다.")
            return None

        html_parts = [
            "<html><head><meta charset='utf-8'>",
            "<style>",
            "body{font-family:'Noto Sans KR',Pretendard,sans-serif;font-size:14px;color:#222;line-height:1.6;}",
            ".hwpx-table{border-collapse:collapse;margin:16px 0;width:100%;table-layout:fixed;}",
            ".hwpx-table th{background:#f2f5ff;text-align:center;font-weight:600;}",
            ".hwpx-table th,.hwpx-table td{border:1px solid #c9cedc;vertical-align:top;}",
            ".hwpx-table tr:nth-child(even){background:#fbfcff;}",
            ".page-break{page-break-before:always;}",
            "</style></head><body>",
        ]
        for entry in paragraphs:
            if entry.get("page_break"):
                html_parts.append("<div class='page-break'></div>")
            text = entry.get("text")
            if text:
                html_parts.append(f"<p>{text}</p>")
        for tbl in table_blocks:
            html_parts.append("<table class='hwpx-table'>")
            if tbl["col_widths"]:
                html_parts.append("<colgroup>")
                for width in tbl["col_widths"]:
                    if width:
                        html_parts.append(f"<col style='width:{width};'/>")
                    else:
                        html_parts.append("<col/>")
                html_parts.append("</colgroup>")
            for row in tbl["rows"]:
                html_parts.append("<tr>")
                for cell in row:
                    tag = "th" if cell["is_header"] else "td"
                    attrs = []
                    if cell["colspan"] > 1:
                        attrs.append(f"colspan='{cell['colspan']}'")
                    if cell["rowspan"] > 1:
                        attrs.append(f"rowspan='{cell['rowspan']}'")
                    if cell["style"]:
                        attrs.append(f"style=\"{cell['style']}\"")
                    html_parts.append(f"<{tag} {' '.join(attrs)}>{cell['content']}</{tag}>")
                html_parts.append("</tr>")
            html_parts.append("</table><br/>")
        html_parts.append("</body></html>")
        html_path.write_text("\n".join(html_parts), encoding="utf-8")
        return html_path
    except Exception as e:
        print(f"[parser] HWPX HTML 변환 중 예외 발생: {e}")
        return None


def convert_hwpx_to_pdf_via_xml(input_path: str, output_dir: str) -> Optional[str]:
    """
    HWPX 전용 폴백: XML→HTML 생성 후 wkhtmltopdf로 PDF 변환.
    """
    wkhtmltopdf = _which_or_warn("wkhtmltopdf")
    if not wkhtmltopdf:
        return None

    in_path = Path(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{in_path.stem}.pdf"

    html_path = _hwpx_to_html(str(in_path), str(out_dir))
    if not html_path:
        return None

    try:
        print(f"[parser] HWPX 폴백: wkhtmltopdf 변환 {html_path} -> {pdf_path}")
        pdf_proc = subprocess.run(
            [wkhtmltopdf, str(html_path), str(pdf_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if pdf_proc.returncode != 0:
            print(f"[parser] wkhtmltopdf 실패 (code {pdf_proc.returncode}): {pdf_proc.stderr}")
            return None

        if pdf_path.exists():
            print(f"[parser] HWPX 폴백 변환 성공: {pdf_path}")
            return str(pdf_path)
        else:
            print("[parser] HWPX 폴백: PDF를 찾지 못했습니다.")
            return None
    except Exception as e:
        print(f"[parser] HWPX 폴백 변환 중 예외 발생: {e}")
        return None


def convert_hwpx_to_png_via_wkhtmltoimage(input_path: str, output_dir: str, dpi: int = 300) -> List[str]:
    """
    HWPX → HTML → PNG (wkhtmltoimage).
    단일 긴 페이지 이미지를 생성. 표/양식 구조 유지 목적.
    """
    wkhtmltoimage = _which_or_warn("wkhtmltoimage")
    if not wkhtmltoimage:
        return []

    in_path = Path(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = _hwpx_to_html(str(in_path), str(out_dir))
    if not html_path:
        return []

    png_path = out_dir / f"{in_path.stem}.png"
    try:
        cmd = [
            wkhtmltoimage,
            f"--dpi",
            str(dpi),
            str(html_path),
            str(png_path),
        ]
        print(f"[parser] HWPX→PNG (wkhtmltoimage): {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(f"[parser] wkhtmltoimage 실패 (code {proc.returncode}): {proc.stderr}")
            return []
        if png_path.exists():
            print(f"[parser] HWPX PNG 변환 성공: {png_path}")
            return [str(png_path)]
        else:
            print("[parser] HWPX PNG 변환 후 파일을 찾지 못했습니다.")
            return []
    except Exception as e:
        print(f"[parser] HWPX PNG 변환 중 예외 발생: {e}")
        return []


def convert_to_pdf(input_path: str, output_dir: Optional[str] = None) -> Optional[str]:
    """
    LibreOffice (soffice)로 Office/HWP/HWPX → PDF 변환.
    변환 성공 시 PDF 경로 반환, 실패 시 None.
    """
    in_path = Path(input_path)
    if not in_path.exists():
        print(f"[parser] 입력 파일이 없습니다: {in_path}")
        return None

    if output_dir is None:
        output_dir = str(in_path.parent)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(in_path),
        ]
        result = _run_soffice(cmd)
        if result.returncode != 0:
            print(f"[parser] 변환 실패 (code {result.returncode}): {result.stderr}")
            return None

        # 생성된 PDF 경로 계산 (동일 basename)
        pdf_path = out_dir / f"{in_path.stem}.pdf"
        if pdf_path.exists():
            print(f"[parser] 변환 성공: {pdf_path}")
            return str(pdf_path)
        else:
            print("[parser] 변환 완료했지만 PDF가 확인되지 않습니다.")
            # HWP/HWPX 폴백 (LibreOffice가 필터를 못 쓸 때)
            suffix = in_path.suffix.lower()
            is_hwpx_container = suffix == ".hwpx" or _looks_like_hwpx_archive(in_path)
            if suffix in [".hwp", ".hwpx"]:
                print("[parser] HWP/HWPX 폴백(hwp5html → wkhtmltopdf) 시도")
                fallback = convert_hwp_to_pdf_via_hwp5html(str(in_path), str(out_dir))
                if fallback:
                    return fallback
                if is_hwpx_container:
                    print("[parser] HWPX 구조 XML 폴백(wkhtmltopdf) 시도")
                    return convert_hwpx_to_pdf_via_xml(str(in_path), str(out_dir))
            return None
    except FileNotFoundError:
        print("[parser] soffice 명령을 찾을 수 없습니다. LibreOffice를 설치하세요.")
        return None
    except Exception as e:
        print(f"[parser] 변환 중 예외 발생: {e}")
        return None


def convert_ppt_to_pngs(input_path: str, output_dir: Optional[str] = None, dpi: int = 300) -> List[str]:
    """
    PPT/PPTX → 슬라이드별 PNG 변환.
    - 1단계: PDF로 변환
    - 2단계: PDF 각 페이지를 PNG로 렌더링
    반환: 생성된 PNG 경로 리스트(정렬)
    """
    in_path = Path(input_path)
    if not in_path.exists():
        print(f"[parser] 입력 파일이 없습니다: {in_path}")
        return []

    if output_dir is None:
        output_dir = str(in_path.parent)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1) PPT → PDF 변환
        pdf_path = convert_to_pdf(str(in_path), output_dir=str(out_dir))
        if not pdf_path:
            print("[parser] PPT를 PDF로 변환하지 못했습니다.")
            return []

        # 2) PDF → PNG 렌더링 (슬라이드별)
        png_dir = out_dir / f"{in_path.stem}_slides"
        png_dir.mkdir(parents=True, exist_ok=True)
        png_pattern = str(png_dir / f"{in_path.stem}_page-%03d.png")

        gs_cmd = [
            "gs",
            "-sDEVICE=png16m",
            f"-r{dpi}",
            "-o",
            png_pattern,
            pdf_path,
        ]
        print(f"[parser] PDF→PNG 렌더링: {' '.join(gs_cmd)}")
        gs_result = subprocess.run(
            gs_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if gs_result.returncode != 0:
            print(f"[parser] PDF→PNG 렌더링 실패 (code {gs_result.returncode}): {gs_result.stderr}")
            return []

        pngs = sorted(png_dir.glob("*.png"))
        if pngs:
            print(f"[parser] PPT PNG 변환 성공: {len(pngs)}개 생성 -> {png_dir}")
        else:
            print("[parser] PDF→PNG 렌더링 후 파일을 찾지 못했습니다.")
        return [str(p) for p in pngs]
    except FileNotFoundError as e:
        print(f"[parser] 명령을 찾을 수 없습니다: {e}")
        print("LibreOffice(soffice)와 ghostscript(gs)가 설치되어 있는지 확인하세요.")
        return []
    except Exception as e:
        print(f"[parser] PPT PNG 변환 중 예외 발생: {e}")
        return []


def convert_excel_to_pdf_fit_width(input_path: str, output_dir: Optional[str] = None) -> Optional[str]:
    """
    Excel → PDF 변환 시 너비 1페이지 맞춤(FitToWidth=1, FitToHeight=0) 옵션을 시도.
    일부 LibreOffice 버전에서만 동작할 수 있으므로, 실패 시 기본 변환으로 폴백.
    """
    in_path = Path(input_path)
    if not in_path.exists():
        print(f"[parser] 입력 파일이 없습니다: {in_path}")
        return None

    if output_dir is None:
        output_dir = str(in_path.parent)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # LibreOffice 필터 옵션 시도 (버전별 지원 여부 상이)
    filter_option = 'calc_pdf_Export:FitToWidth=1,FitToHeight=0'

    try:
        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            f"pdf:{filter_option}",
            "--outdir",
            str(out_dir),
            str(in_path),
        ]
        result = _run_soffice(cmd)
        if result.returncode != 0:
            print(f"[parser] Excel fit-to-width 변환 실패 (code {result.returncode}): {result.stderr}")
            print("[parser] 기본 PDF 변환으로 폴백합니다.")
            return convert_to_pdf(str(in_path), output_dir=str(out_dir))

        pdf_path = out_dir / f"{in_path.stem}.pdf"
        if pdf_path.exists():
            print(f"[parser] Excel fit-to-width 변환 성공: {pdf_path}")
            return str(pdf_path)
        else:
            print("[parser] 변환 완료했지만 PDF가 확인되지 않습니다. 기본 변환으로 폴백.")
            return convert_to_pdf(str(in_path), output_dir=str(out_dir))
    except FileNotFoundError:
        print("[parser] soffice 명령을 찾을 수 없습니다. LibreOffice를 설치하세요.")
        return None
    except Exception as e:
        print(f"[parser] Excel 변환 중 예외 발생: {e}")
        return None


def cli():
    """
    테스트/단독 실행용 CLI:
      python converter.py --mode pdf --input file.docx --outdir /tmp/out
      python converter.py --mode pdf-png --input file.hwpx --outdir /tmp/out  # PDF 변환 후 PNG 렌더링
      python converter.py --mode ppt-png --input file.pptx --outdir /tmp/out
      python converter.py --mode excel-pdf-fit --input file.xlsx --outdir /tmp/out
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Office/HWP 변환 테스트 CLI\n"
        "- mode pdf: doc/docx/xls/xlsx/ppt/pptx/hwp/hwpx → PDF\n"
        "- mode pdf-png: 위 변환 후 PDF→PNG 렌더링 (gs 필요)\n"
        "- mode ppt-png: ppt/pptx → PDF → 슬라이드별 PNG (ghostscript 필요)\n"
        "- mode excel-pdf-fit: xls/xlsx 너비 1페이지 맞춤 PDF"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["pdf", "pdf-png", "ppt-png", "excel-pdf-fit"],
    )
    parser.add_argument("--input", required=True, help="입력 파일 경로")
    parser.add_argument("--outdir", help="출력 디렉토리 (미지정 시 입력 파일 폴더)")
    parser.add_argument("--dpi", type=int, default=300, help="PNG 렌더링 DPI (기본 300)")
    args = parser.parse_args()

    if args.mode == "pdf":
        result = convert_to_pdf(args.input, args.outdir)
        print(f"[cli] 결과: {result}")
    elif args.mode == "pdf-png":
        pdf_path = None
        if str(args.input).lower().endswith(".pdf"):
            pdf_path = args.input
        else:
            pdf_path = convert_to_pdf(args.input, args.outdir)
        if pdf_path:
            stem = Path(pdf_path).stem
            pngs = convert_pdf_to_pngs(pdf_path, args.outdir or str(Path(pdf_path).parent), stem, dpi=args.dpi)
            print(f"[cli] PNG {len(pngs)}개 생성: {pngs}")
        else:
            print("[cli] PDF 변환에 실패하여 PNG 생성 불가")
    elif args.mode == "ppt-png":
        result = convert_ppt_to_pngs(args.input, args.outdir)
        print(f"[cli] 결과 파일 {len(result)}개: {result}")
    elif args.mode == "excel-pdf-fit":
        result = convert_excel_to_pdf_fit_width(args.input, args.outdir)
        print(f"[cli] 결과: {result}")


if __name__ == "__main__":
    cli()
