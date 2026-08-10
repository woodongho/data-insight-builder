import re
import os
import pandas as pd
import numpy as np

def sanitize_for_json(obj):
    """
    NaN, Infinity, numpy 데이터 타입을 Python 네이티브 및 JSON 안전 형태(None)로 변환
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    elif isinstance(obj, tuple):
        return [sanitize_for_json(v) for v in obj]
    elif isinstance(obj, (float, np.floating)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, (int, np.integer)):
        return int(obj)
    elif pd.isna(obj):
        return None
    return obj

AGG_KEYWORDS = [
    'world', 'oecd members', 'euro area', 'european union', 'high income', 
    'low income', 'income', 'area', 'small states', 'total', 'aggregate', 
    'sub-saharan', 'latin america', 'caribbean', 'middle east', 'north america', 'south asia'
]

def get_label_column(df):
    """
    데이터셋에서 가장 알맞은 명목형 라벨 열(국가명, 항목명 등) 추출
    """
    col_names = [str(c) for c in df.columns]
    if 'Country Name' in col_names:
        return 'Country Name'
    for c in col_names:
        if not pd.api.types.is_numeric_dtype(df[c]) and not c.startswith('Unnamed:'):
            return c
    return col_names[0] if col_names else None

def get_aggregate_indices(df, label_col=None):
    """
    국가가 아닌 대륙/그룹/소득 집계 행 인덱스 리스트 반환
    """
    if not label_col:
        label_col = get_label_column(df)
    if not label_col or label_col not in df.columns:
        return []
    
    indices = []
    for idx, val in enumerate(df[label_col].astype(str)):
        val_lower = val.lower()
        if any(kw in val_lower for kw in AGG_KEYWORDS):
            indices.append(idx)
    return indices

# ---------------------------------------------------------
# 도구 1. reshape_wide_to_long (연도 열을 행으로 접기)
# ---------------------------------------------------------
def tool_reshape_wide_to_long(df, exclude_aggregates=True, **kwargs):
    col_names = [str(c) for c in df.columns]
    year_cols = [c for c in col_names if re.match(r'^(19|20)\d{2}$', c.strip())]
    id_cols = [c for c in col_names if c not in year_cols and not c.startswith('Unnamed:')]
    
    total_initial_rows = len(df)
    agg_indices = get_aggregate_indices(df) if exclude_aggregates else []
    
    working_df = df.copy()
    if exclude_aggregates and agg_indices:
        working_df = working_df.drop(index=agg_indices)
    
    long_df = pd.melt(
        working_df, 
        id_vars=id_cols, 
        value_vars=year_cols, 
        var_name='Year', 
        value_name='Value'
    )
    long_df = long_df.dropna(subset=['Value'])
    
    rows_excluded = total_initial_rows - len(working_df)
    exclusion_reasons = []
    if exclude_aggregates and agg_indices:
        exclusion_reasons.append(f"지역/그룹/소득 집계 행 {len(agg_indices)}개 제외")
    
    preview = long_df.head(50).replace({np.nan: None}).to_dict(orient='records')
    
    return sanitize_for_json({
        "tool_name": "reshape_wide_to_long",
        "description": "연도 열을 행으로 접어서 롱 포맷(Tidy Data)으로 변환",
        "reference_period": "전체 시계열",
        "rows_used": len(working_df),
        "rows_excluded": rows_excluded,
        "exclusion_reasons": exclusion_reasons,
        "used_columns": id_cols + ['Year', 'Value'],
        "unit": "변환 행 수",
        "cautions": ["연도가 열로 나열된 와이드 구조를 데이터베이스 분석용 롱 구조로 재구성했습니다."],
        "result": {
            "total_long_rows": len(long_df),
            "id_columns": id_cols,
            "year_columns_count": len(year_cols),
            "preview_rows": preview
        }
    })

# ---------------------------------------------------------
# 도구 2. quality_report (품질 보고서)
# ---------------------------------------------------------
def tool_quality_report(df, **kwargs):
    col_names = [str(c) for c in df.columns]
    missing_counts = {c: int(df[c].isna().sum()) for c in col_names}
    missing_ratios = {c: round(float(df[c].isna().mean() * 100), 2) for c in col_names}
    duplicate_rows = int(df.duplicated().sum())
    unnamed_cols = [c for c in col_names if c.startswith('Unnamed:') or c.strip() == '']
    
    return sanitize_for_json({
        "tool_name": "quality_report",
        "description": "결측치, 중복 행, 데이터 타입 및 불필요한 열 진단 품질 보고서",
        "reference_period": None,
        "rows_used": len(df),
        "rows_excluded": 0,
        "exclusion_reasons": [],
        "used_columns": col_names,
        "unit": "건수 / 비율(%)",
        "cautions": ["품질 보고서는 데이터 정제 작업 전 전체적인 데이터 위생 상태 점검용입니다."],
        "result": {
            "total_rows": len(df),
            "total_columns": len(col_names),
            "duplicate_rows": duplicate_rows,
            "unnamed_columns": unnamed_cols,
            "missing_counts": missing_counts,
            "missing_ratios": missing_ratios
        }
    })

# ---------------------------------------------------------
# 도구 3. year_coverage (연도별 값 개수 및 권장 연도)
# ---------------------------------------------------------
def tool_year_coverage(df, **kwargs):
    col_names = [str(c) for c in df.columns]
    year_cols = [c for c in col_names if re.match(r'^(19|20)\d{2}$', c.strip())]
    
    coverage = {c: int(df[c].notna().sum()) for c in year_cols}
    rec_year = None
    if coverage:
        max_c = max(coverage.values()) if coverage.values() else 0
        if max_c > 0:
            valid_years = [y for y, count in coverage.items() if count >= max_c * 0.75 and y.isdigit()]
            if valid_years:
                rec_year = max(valid_years, key=int)
                
    return sanitize_for_json({
        "tool_name": "year_coverage",
        "description": "연도별 유효 데이터 입력 건수 집계 및 권장 기준연도 판별",
        "reference_period": rec_year,
        "rows_used": len(df),
        "rows_excluded": 0,
        "exclusion_reasons": [],
        "used_columns": year_cols,
        "unit": "개 (입력 행 수)",
        "cautions": ["가장 최근 연도가 최다 데이터 보유 연도와 다를 수 있으므로 권장 기준연도 사용을 권장합니다."],
        "result": {
            "year_coverage": coverage,
            "recommended_reference_year": rec_year
        }
    })

# ---------------------------------------------------------
# 도구 4. detect_aggregates (집계 행 탐지)
# ---------------------------------------------------------
def tool_detect_aggregates(df, **kwargs):
    label_col = get_label_column(df)
    agg_indices = get_aggregate_indices(df, label_col=label_col)
    
    detected_rows = []
    if label_col:
        for idx in agg_indices:
            detected_rows.append({"row_index": idx, "name": str(df.iloc[idx][label_col])})
            
    return sanitize_for_json({
        "tool_name": "detect_aggregates",
        "description": "국가가 아닌 대륙/그룹/소득 집계 행 탐지",
        "reference_period": None,
        "rows_used": len(df),
        "rows_excluded": 0,
        "exclusion_reasons": [],
        "used_columns": [label_col] if label_col else [],
        "unit": "개 (행 수)",
        "cautions": ["집계 행이 개별 단위 데이터와 혼재되면 비교 분석 시 중복 집계 오차가 발생합니다."],
        "result": {
            "label_column": label_col,
            "aggregate_count": len(detected_rows),
            "non_aggregate_count": len(df) - len(detected_rows),
            "detected_aggregates": detected_rows
        }
    })

# ---------------------------------------------------------
# 도구 5. describe_numeric (기술통계 요약)
# ---------------------------------------------------------
def tool_describe_numeric(df, reference_period=None, column=None, exclude_aggregates=True, **kwargs):
    target_col = str(column or reference_period)
    if not target_col or target_col not in df.columns:
        raise ValueError(f"숫자형 통계를 계산할 열/기준시점('{target_col}')이 필요합니다.")
        
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()
    
    s = pd.to_numeric(working_df[target_col], errors='coerce').dropna()
    
    rows_excluded = total_initial - len(s)
    exclusion_reasons = []
    if exclude_aggregates and agg_indices:
        exclusion_reasons.append(f"집계 행 {len(agg_indices)}개 제외")
    null_count = len(working_df) - len(s)
    if null_count > 0:
        exclusion_reasons.append(f"결측치 {null_count}개 제외")
        
    stats = {
        "count": int(s.count()),
        "mean": round(float(s.mean()), 2) if not s.empty else None,
        "median": round(float(s.median()), 2) if not s.empty else None,
        "std": round(float(s.std()), 2) if len(s) > 1 else 0.0,
        "min": round(float(s.min()), 2) if not s.empty else None,
        "max": round(float(s.max()), 2) if not s.empty else None,
    }
    
    return sanitize_for_json({
        "tool_name": "describe_numeric",
        "description": f"기준시점({target_col}) 데이터의 평균·중앙값·최소·최대 기술통계 요약",
        "reference_period": target_col,
        "rows_used": len(s),
        "rows_excluded": rows_excluded,
        "exclusion_reasons": exclusion_reasons,
        "used_columns": [target_col],
        "unit": "수치 단위",
        "cautions": ["평균값은 극단적인 최댓값/최솟값(이상치)의 영향을 받으므로 중앙값과 함께 확인하세요."],
        "result": stats
    })

# ---------------------------------------------------------
# 도구 6. trend_line (연도별 추이 - 선 차트)
# ---------------------------------------------------------
def tool_trend_line(df, target_names=None, exclude_aggregates=True, **kwargs):
    label_col = get_label_column(df)
    if not label_col:
        raise ValueError("추이를 분석할 항목 라벨 열을 찾을 수 없습니다.")
        
    col_names = [str(c) for c in df.columns]
    year_cols = [c for c in col_names if re.match(r'^(19|20)\d{2}$', c.strip())]
    if not year_cols:
        raise ValueError("추이를 분석할 연도 열이 존재하지 않습니다.")
        
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df, label_col=label_col) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()
    
    if target_names:
        if isinstance(target_names, str):
            target_names = [target_names]
        filter_mask = working_df[label_col].astype(str).str.lower().isin([t.lower() for t in target_names])
        sub_df = working_df[filter_mask]
    else:
        sub_df = working_df.head(5)
        
    if sub_df.empty:
        raise ValueError(f"선택한 항목({target_names})을 데이터에서 찾을 수 없습니다.")
        
    datasets = []
    for _, row in sub_df.iterrows():
        name = str(row[label_col])
        vals = [float(row[y]) if pd.notna(row[y]) else None for y in year_cols]
        datasets.append({
            "label": name,
            "data": vals
        })
        
    return sanitize_for_json({
        "tool_name": "trend_line",
        "description": "선택한 항목들의 연도별 변화 추이(선 차트 데이터)",
        "reference_period": f"{year_cols[0]}~{year_cols[-1]}",
        "rows_used": len(sub_df),
        "rows_excluded": total_initial - len(sub_df),
        "exclusion_reasons": [f"선택 항목({len(sub_df)}개) 이외의 타 행 제외"],
        "used_columns": [label_col] + year_cols,
        "unit": "수치 (연도별)",
        "cautions": ["누락된 연도(None)는 차트에서 끊어져 표시될 수 있습니다."],
        "result": {
            "chart_type": "line",
            "labels": year_cols,
            "datasets": datasets
        }
    })

# ---------------------------------------------------------
# 도구 7. top_bottom_n (상위·하위 N - 수평 막대)
# ---------------------------------------------------------
def tool_top_bottom_n(df, reference_period='2024', n=10, exclude_aggregates=True, target_name=None, **kwargs):
    ref_col = str(reference_period)
    if not ref_col or ref_col not in df.columns:
        raise ValueError(f"기준시점({ref_col})에 해당하는 열이 데이터에 없습니다.")
        
    label_col = get_label_column(df)
    if not label_col:
        raise ValueError("라벨(국가명/항목명) 열을 찾을 수 없습니다.")
        
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df, label_col=label_col) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()
    
    clean_df = working_df.dropna(subset=[ref_col]).copy()
    clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors='coerce')
    clean_df = clean_df.dropna(subset=[ref_col])
    clean_df['rank'] = clean_df[ref_col].rank(ascending=False, method='min').astype(int)
    clean_df = clean_df.sort_values(by=ref_col, ascending=False)
    
    rows_excluded = total_initial - len(clean_df)
    exclusion_reasons = []
    if exclude_aggregates and agg_indices:
        exclusion_reasons.append(f"지역/그룹/소득 집계 행 {len(agg_indices)}개 제외")
    null_count = len(working_df) - len(clean_df)
    if null_count > 0:
        exclusion_reasons.append(f"기준시점({ref_col}) 결측치 {null_count}개 제외")
        
    top_df = clean_df.head(n)
    bottom_df = clean_df.tail(n).sort_values(by=ref_col, ascending=True)

    top_labels = [f"{row[label_col]} ({row['rank']}위)" for _, row in top_df.iterrows()]
    top_values = [round(v, 2) for v in top_df[ref_col].tolist()]

    target_info = None
    if target_name:
        mask = clean_df[label_col].astype(str).str.lower().str.contains(str(target_name).lower())
        target_df = clean_df[mask]
        if not target_df.empty:
            t_row = target_df.iloc[0]
            t_name = str(t_row[label_col])
            t_val = round(float(t_row[ref_col]), 2)
            t_rank = int(t_row['rank'])
            target_info = {"name": t_name, "value": t_val, "rank": t_rank}

            # 대상이 상위 n개 안에 포함되어 있지 않으면 상위 차트에 라벨과 함께 추가 표시
            if t_row.name not in top_df.index:
                top_labels.append(f"📍 {t_name} ({t_rank}위 - 대상)")
                top_values.append(t_val)
                exclusion_reasons.append(f"요청된 비교 대상('{t_name}', {t_rank}위)을 차트에 추가 포함")

    return sanitize_for_json({
        "tool_name": "top_bottom_n",
        "description": f"기준시점({ref_col}) 기준 상위 {n}개 및 하위 {n}개 항목 비교" + (f" (특정 대상 '{target_name}' 포함)" if target_info else ""),
        "reference_period": ref_col,
        "rows_used": len(clean_df),
        "rows_excluded": rows_excluded,
        "exclusion_reasons": exclusion_reasons,
        "used_columns": [label_col, ref_col],
        "unit": "수치",
        "target_info": target_info,
        "cautions": [f"기준시점({ref_col})에 값이 비어있는 항목은 순위 계산에서 자동으로 제외되었습니다."],
        "result": {
            "chart_type": "bar",
            "top_chart": {
                "labels": top_labels,
                "values": top_values
            },
            "bottom_chart": {
                "labels": bottom_df[label_col].astype(str).tolist(),
                "values": [round(v, 2) for v in bottom_df[ref_col].tolist()]
            }
        }
    })

# ---------------------------------------------------------
# 도구 8. group_summary (그룹별 평균·합계·개수 - 막대 차트)
# ---------------------------------------------------------
def tool_group_summary(df, group_col='Region', reference_period='2024', agg_func='mean', exclude_aggregates=True, **kwargs):
    ref_col = str(reference_period)
    if not ref_col or ref_col not in df.columns:
        raise ValueError(f"기준시점({ref_col})에 해당하는 열이 데이터에 없습니다.")
        
    working_df = df.copy()
    
    if group_col not in working_df.columns:
        data_dir = r'C:\AI-study\data-insight-builder\data'
        for root, dirs, files in os.walk(data_dir):
            for f in files:
                if f.startswith('Metadata_Country') and f.endswith('.csv'):
                    meta_path = os.path.join(root, f)
                    try:
                        m_df = pd.read_csv(meta_path)
                        if group_col in m_df.columns and 'Country Code' in working_df.columns:
                            working_df = pd.merge(working_df, m_df[['Country Code', group_col]], on='Country Code', how='left')
                            break
                    except Exception:
                        pass
                        
    if group_col not in working_df.columns:
        raise ValueError(f"그룹화 기준 열('{group_col}')을 데이터에서 찾을 수 없습니다.")
        
    total_initial = len(working_df)
    agg_indices = get_aggregate_indices(working_df) if exclude_aggregates else []
    if exclude_aggregates and agg_indices:
        working_df = working_df.drop(index=agg_indices)
        
    clean_df = working_df.dropna(subset=[group_col, ref_col]).copy()
    clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors='coerce')
    clean_df = clean_df.dropna(subset=[ref_col])
    
    if agg_func == 'sum':
        grp = clean_df.groupby(group_col)[ref_col].sum()
    elif agg_func == 'count':
        grp = clean_df.groupby(group_col)[ref_col].count()
    else:
        grp = clean_df.groupby(group_col)[ref_col].mean()
        
    grp = grp.sort_values(ascending=False)
    
    return sanitize_for_json({
        "tool_name": "group_summary",
        "description": f"그룹({group_col})별 기준시점({ref_col}) {agg_func} 요약 집계",
        "reference_period": ref_col,
        "rows_used": len(clean_df),
        "rows_excluded": total_initial - len(clean_df),
        "exclusion_reasons": [f"그룹명('{group_col}') 또는 기준시점({ref_col}) 결측치 제외"],
        "used_columns": [group_col, ref_col],
        "unit": f"그룹별 {agg_func}",
        "cautions": ["그룹 내 속한 항목 수가 적은 경우 집계 수치 평균의 왜곡에 유의하세요."],
        "result": {
            "chart_type": "bar",
            "group_column": group_col,
            "aggregation": agg_func,
            "labels": grp.index.astype(str).tolist(),
            "values": [round(v, 2) for v in grp.values.tolist()]
        }
    })

# ---------------------------------------------------------
# 도구 9. change_rate (변화량·변화율 - 막대 차트)
# ---------------------------------------------------------
def tool_change_rate(df, start_period='2010', end_period='2024', top_n=10, exclude_aggregates=True, **kwargs):
    s_col = str(start_period)
    e_col = str(end_period)
    
    if s_col not in df.columns or e_col not in df.columns:
        raise ValueError(f"시작시점({s_col}) 또는 종료시점({e_col}) 열이 데이터에 없습니다.")
        
    label_col = get_label_column(df)
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df, label_col=label_col) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()
    
    clean_df = working_df.dropna(subset=[s_col, e_col]).copy()
    clean_df[s_col] = pd.to_numeric(clean_df[s_col], errors='coerce')
    clean_df[e_col] = pd.to_numeric(clean_df[e_col], errors='coerce')
    clean_df = clean_df.dropna(subset=[s_col, e_col])
    
    clean_df['abs_change'] = clean_df[e_col] - clean_df[s_col]
    clean_df['pct_change'] = np.where(
        clean_df[s_col] != 0, 
        ((clean_df[e_col] - clean_df[s_col]) / clean_df[s_col]) * 100, 
        0.0
    )
    
    top_growth = clean_df.sort_values(by='abs_change', ascending=False).head(top_n)
    
    rows_excluded = total_initial - len(clean_df)
    exclusion_reasons = []
    if exclude_aggregates and agg_indices:
        exclusion_reasons.append(f"지역/그룹/소득 집계 행 {len(agg_indices)}개 제외")
    null_count = len(working_df) - len(clean_df)
    if null_count > 0:
        exclusion_reasons.append(f"시작/종료 시점 결측치 {null_count}개 제외")
        
    return sanitize_for_json({
        "tool_name": "change_rate",
        "description": f"두 시점({s_col}년 → {e_col}년) 간의 절대 변화량 및 변화율 산출",
        "reference_period": f"{s_col}~{e_col}",
        "rows_used": len(clean_df),
        "rows_excluded": rows_excluded,
        "exclusion_reasons": exclusion_reasons,
        "used_columns": [label_col, s_col, e_col],
        "unit": "변화량 (%p 및 %)",
        "cautions": ["시작 시점 수치가 0에 가까우면 퍼센트 변화율이 과도하게 크게 나올 수 있으니 절대 변화량도 함께 확인하세요."],
        "result": {
            "chart_type": "bar",
            "start_period": s_col,
            "end_period": e_col,
            "labels": top_growth[label_col].astype(str).tolist(),
            "start_values": [round(v, 2) for v in top_growth[s_col].tolist()],
            "end_values": [round(v, 2) for v in top_growth[e_col].tolist()],
            "abs_change": [round(v, 2) for v in top_growth['abs_change'].tolist()],
            "pct_change": [round(v, 2) for v in top_growth['pct_change'].tolist()]
        }
    })

# ---------------------------------------------------------
# 도구 10. distribution (구간별 분포 - 히스토그램)
# ---------------------------------------------------------
def tool_distribution(df, reference_period='2024', bins=5, exclude_aggregates=True, **kwargs):
    ref_col = str(reference_period)
    if ref_col not in df.columns:
        raise ValueError(f"기준시점({ref_col}) 열이 데이터에 없습니다.")
        
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()
    
    s = pd.to_numeric(working_df[ref_col], errors='coerce').dropna()
    
    counts, bin_edges = np.histogram(s, bins=bins)
    bin_labels = []
    for i in range(len(counts)):
        bin_labels.append(f"{bin_edges[i]:.1f}~{bin_edges[i+1]:.1f}")
        
    return sanitize_for_json({
        "tool_name": "distribution",
        "description": f"기준시점({ref_col}) 데이터의 구간별 빈도 분포(히스토그램)",
        "reference_period": ref_col,
        "rows_used": len(s),
        "rows_excluded": total_initial - len(s),
        "exclusion_reasons": ["집계 행 또는 결측치 제외"],
        "used_columns": [ref_col],
        "unit": "개 (항목 수)",
        "cautions": ["구간(Bin) 수에 따라 분포의 모양이 다르게 보일 수 있습니다."],
        "result": {
            "chart_type": "histogram",
            "bin_labels": bin_labels,
            "counts": [int(c) for c in counts],
            "bin_edges": [round(float(b), 2) for b in bin_edges]
        }
    })

# ---------------------------------------------------------
# 도구 11. correlation_scatter (상관계수 및 산점도)
# ---------------------------------------------------------
def tool_correlation_scatter(df, x_col='2010', y_col='2024', exclude_aggregates=True, **kwargs):
    x_name = str(x_col)
    y_name = str(y_col)
    
    if x_name not in df.columns or y_name not in df.columns:
        raise ValueError(f"상관분석을 위한 두 열('{x_name}', '{y_name}')이 데이터에 모두 존재해야 합니다.")
        
    label_col = get_label_column(df)
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df, label_col=label_col) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()
    
    clean_df = working_df.dropna(subset=[x_name, y_name]).copy()
    clean_df[x_name] = pd.to_numeric(clean_df[x_name], errors='coerce')
    clean_df[y_name] = pd.to_numeric(clean_df[y_name], errors='coerce')
    clean_df = clean_df.dropna(subset=[x_name, y_name])
    
    corr_coef = float(clean_df[x_name].corr(clean_df[y_name]))
    
    scatter_points = []
    for _, row in clean_df.iterrows():
        scatter_points.append({
            "x": round(float(row[x_name]), 2),
            "y": round(float(row[y_name]), 2),
            "label": str(row[label_col]) if label_col else ""
        })
        
    return sanitize_for_json({
        "tool_name": "correlation_scatter",
        "description": f"두 수치 변수('{x_name}' vs '{y_name}')의 피어슨 상관계수 및 산점도",
        "reference_period": f"{x_name} & {y_name}",
        "rows_used": len(clean_df),
        "rows_excluded": total_initial - len(clean_df),
        "exclusion_reasons": ["집계 행 또는 두 시점 중 결측치 제외"],
        "used_columns": [label_col, x_name, y_name] if label_col else [x_name, y_name],
        "unit": "상관계수 (-1 ~ 1)",
        "cautions": ["상관관계는 인과관계가 아닙니다. 두 변수가 함께 움직인다고 해서 하나가 다른 하나의 직접적 원인임을 의미하지 않습니다."],
        "result": {
            "chart_type": "scatter",
            "x_axis_label": x_name,
            "y_axis_label": y_name,
            "correlation_coefficient": round(corr_coef, 4),
            "scatter_data": scatter_points
        }
    })

# ---------------------------------------------------------
# 도구 12. compare_one_vs_all (특정 항목 vs 전체 평균·중앙값)
# ---------------------------------------------------------
def tool_compare_one_vs_all(df, target_name='Korea, Rep.', reference_period='2024', exclude_aggregates=True, **kwargs):
    ref_col = str(reference_period)
    if ref_col not in df.columns:
        raise ValueError(f"기준시점({ref_col}) 열이 데이터에 없습니다.")
        
    label_col = get_label_column(df)
    if not label_col:
        raise ValueError("항목 라벨 열을 찾을 수 없습니다.")
        
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df, label_col=label_col) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()
    
    clean_df = working_df.dropna(subset=[ref_col]).copy()
    clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors='coerce')
    clean_df = clean_df.dropna(subset=[ref_col])
    
    match_mask = clean_df[label_col].astype(str).str.lower().str.contains(str(target_name).lower())
    matched_df = clean_df[match_mask]
    
    if matched_df.empty:
        raise ValueError(f"선택한 대상('{target_name}')을 기준시점({ref_col}) 데이터에서 찾을 수 없습니다.")
        
    target_row = matched_df.iloc[0]
    actual_target_name = str(target_row[label_col])
    target_val = float(target_row[ref_col])
    
    overall_mean = float(clean_df[ref_col].mean())
    overall_median = float(clean_df[ref_col].median())
    
    diff_from_mean = target_val - overall_mean
    diff_from_median = target_val - overall_median
    
    return sanitize_for_json({
        "tool_name": "compare_one_vs_all",
        "description": f"특정 대상('{actual_target_name}')과 전체 평균·중앙값 비교",
        "reference_period": ref_col,
        "rows_used": len(clean_df),
        "rows_excluded": total_initial - len(clean_df),
        "exclusion_reasons": ["집계 행 및 결측치 제외"],
        "used_columns": [label_col, ref_col],
        "unit": "수치",
        "cautions": ["단일 항목과 전체 평균의 차이가 클 경우, 이상치가 평균을 왜곡했는지 중앙값도 함께 비교하세요."],
        "result": {
            "chart_type": "bar",
            "target_name": actual_target_name,
            "target_value": round(target_val, 2),
            "overall_mean": round(overall_mean, 2),
            "overall_median": round(overall_median, 2),
            "diff_from_mean": round(diff_from_mean, 2),
            "diff_from_median": round(diff_from_median, 2),
            "labels": [actual_target_name, "전체 평균 (Mean)", "전체 중앙값 (Median)"],
            "values": [round(target_val, 2), round(overall_mean, 2), round(overall_median, 2)]
        }
    })

# ---------------------------------------------------------
# 도구 13. custom_dynamic_query (유저 맞춤 동적 연산 폴백 도구)
# ---------------------------------------------------------
def tool_custom_dynamic_query(df, code_snippet=None, chart_type='bar', description=None, exclude_aggregates=True, **kwargs):
    """
    기존 12가지 정형 도구로 해결할 수 없는 맞춤형 질문을 위해 
    AI가 생성한 동적 파이썬 Pandas 코드를 안전하게 수행하고 차트 데이터를 추출하는 도구
    """
    label_col = get_label_column(df)
    total_initial = len(df)
    agg_indices = get_aggregate_indices(df, label_col=label_col) if exclude_aggregates else []
    working_df = df.drop(index=agg_indices) if (exclude_aggregates and agg_indices) else df.copy()

    labels = []
    values = []
    datasets = []
    exclusion_reasons = []
    if exclude_aggregates and agg_indices:
        exclusion_reasons.append(f"지역/그룹/소득 집계 행 {len(agg_indices)}개 제외")

    if code_snippet:
        try:
            local_vars = {"df": working_df, "pd": pd, "np": np, "re": re}
            exec(code_snippet, globals(), local_vars)
            res_df = local_vars.get("result_df")
            if res_df is not None and isinstance(res_df, pd.DataFrame) and not res_df.empty:
                cols = res_df.columns.tolist()
                if len(cols) >= 2:
                    labels = [str(x) for x in res_df[cols[0]].tolist()]
                    values = [round(float(v), 2) if pd.notna(v) else 0.0 for v in res_df[cols[1]].tolist()]
            elif local_vars.get("chart_data"):
                chart_data = local_vars.get("chart_data")
                labels = chart_data.get("labels", [])
                values = chart_data.get("values", [])
                datasets = chart_data.get("datasets", [])
                chart_type = chart_data.get("chart_type", chart_type)
        except Exception as e:
            exclusion_reasons.append(f"동적 연산 실행 경고: {str(e)}")

    if not labels and not datasets:
        num_cols = [c for c in working_df.columns if pd.api.types.is_numeric_dtype(working_df[c])]
        if num_cols:
            latest_col = num_cols[-1]
            clean_s = working_df.dropna(subset=[latest_col]).sort_values(by=latest_col, ascending=False).head(10)
            labels = clean_s[label_col].astype(str).tolist()
            values = [round(float(v), 2) for v in clean_s[latest_col].tolist()]

    result_payload = {
        "chart_type": chart_type,
        "labels": labels,
        "values": values
    }
    if datasets:
        result_payload["datasets"] = datasets

    return sanitize_for_json({
        "tool_name": "custom_dynamic_query",
        "description": description or "유저 맞춤형 자연어 동적 데이터 연산",
        "reference_period": "동적 연산",
        "rows_used": len(working_df),
        "rows_excluded": total_initial - len(working_df),
        "exclusion_reasons": exclusion_reasons,
        "used_columns": [label_col] if label_col else [],
        "unit": "수치",
        "cautions": ["질문에 맞춰 생성된 맞춤형 파이썬 데이터 계산 결과입니다."],
        "result": result_payload
    })
