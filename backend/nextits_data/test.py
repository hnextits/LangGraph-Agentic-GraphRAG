import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from io import StringIO

# 형님의 테이블 구조를 문자열로 복사
html_data = """
<table>
    <tr>
        <td>구 분</td>
        <td><l></td>
        <td>’16년말</td>
        <td>’17년말</td>
        <td>’18년말</td>
        <td>’19년말</td>
        <td>’20.5.15</td>
    </tr>
    <tr>
        <td>코스닥 150</td>
        <td>지수값</td>
        <td>936.09</td>
        <td>1,413.80</td>
        <td>1,166.25</td>
        <td>1,029.57</td>
        <td>1,066.33</td>
    </tr>
    <tr>
        <td><t></td>
        <td>(수익률A)</td>
        <td>(△14.55%)</td>
        <td>(+51.03%)</td>
        <td>(△17.51%)</td>
        <td>(△11.72%)</td>
        <td>(+3.57%)</td>
    </tr>
    <tr>
        <td>코스닥</td>
        <td>지수값</td>
        <td>631.44</td>
        <td>798.42</td>
        <td>675.65</td>
        <td>669.83</td>
        <td>691.93</td>
    </tr>
    <tr>
        <td><t></td>
        <td>(수익률B)</td>
        <td>(△7.5%)</td>
        <td>(+26.44%)</td>
        <td>(△15.38%)</td>
        <td>(△0.86%)</td>
        <td>(+3.30%)</td>
    </tr>
    <tr>
        <td>수익률 차이(A-B)</td>
        <td><l></td>
        <td>△7.09%p</td>
        <td>+24.59%p</td>
        <td>△2.13%p</td>
        <td>△10.86%p</td>
        <td>(+0.27%)</td>
    </tr>
</table>
"""

# Pandas를 사용하여 HTML 테이블을 읽고 정제
df_list = pd.read_html(StringIO(html_data))
df = df_list[0].fillna('')
df = df.iloc[1:]
df.columns = ['구분', '항목', '16년말', '17년말', '18년말', '19년말', '20.5.15']

# 데이터 클리닝 함수 (수익률만 추출)
def clean_return(val):
    val = str(val).replace('(', '').replace(')', '').replace('%', '').replace('p', '').replace(' ', '')
    if '△' in val:
        val = val.replace('△', '-')
    if '+' in val:
        val = val.replace('+', '')
    try:
        return float(val)
    except ValueError:
        return 0.0

# 수익률 데이터 추출 및 변환
returns_df = df[df['항목'].str.contains('수익률')]
returns_df = returns_df.set_index('항목').drop(['구분'], axis=1)
time_points = returns_df.columns
kosdaq150_returns = returns_df.loc['(수익률A)'].apply(clean_return).values
kosdaq_returns = returns_df.loc['(수익률B)'].apply(clean_return).values

# --- Matplotlib 시각화 코드 ---
plt.rcParams['font.family'] = 'Malgun Gothic' # 한글 폰트 설정 (Windows 기준)
# plt.rcParams['font.family'] = 'AppleGothic' # Mac 사용자용
plt.rcParams['axes.unicode_minus'] = False # 마이너스 폰트 깨짐 방지

fig, ax = plt.subplots(figsize=(10, 6))
width = 0.35
x = np.arange(len(time_points))

rects1 = ax.bar(x - width/2, kosdaq150_returns, width, label='KOSDAQ 150 (수익률 A)', color='#1f77b4')
rects2 = ax.bar(x + width/2, kosdaq_returns, width, label='KOSDAQ (수익률 B)', color='#ff7f0e')

ax.set_title('KOSDAQ 150 vs KOSDAQ 연도별 수익률 비교', fontsize=14, fontweight='bold')
ax.set_ylabel('수익률 (%)')
ax.set_xticks(x)
ax.set_xticklabels(time_points)
ax.axhline(0, color='gray', linewidth=0.8)

ax.legend()
plt.grid(axis='y', linestyle='--', alpha=0.7)
plt.tight_layout()

# 💾 저장 명령어 추가
output_filename = 'kosdaq_returns_comparison.png'
plt.savefig(output_filename, dpi=300, bbox_inches='tight')

# plt.show() # 저장만 하려면 주석 처리

print(f"✅ 그래프가 '{output_filename}' 파일로 성공적으로 저장되었습니다.")
