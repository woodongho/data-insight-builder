import os
import io
import csv
import re
import json
import time
import logging
import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from google import genai
from google.genai import types

import tools

# 환경변수 로드 (.env)
load_dotenv()

# 백엔드 전용 Python logging 설정 (print 사용 안 함)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("data-insight-builder")

app = Flask(__name__)

# 업로드 최대 용량 제한 설정 (MB)
max_mb = int(os.getenv("MAX_UPLOAD_MB", 10))
app.config['MAX_CONTENT_LENGTH'] = max_mb * 1024 * 1024

# 메모리에 1개의 데이터셋만 보관하는 전역 상태
CURRENT_DATASET = None

TOOL_CATALOG = [
    {"tool": "reshape_wide_to_long", "name": "연도 열을 행으로 접기 (Tidy Data 변환)"},
    {"tool": "quality_report", "name": "품질 보고서 (결측·중복·타입 진단)"},
    {"tool": "year_coverage", "name": "연도별 값 개수 및 권장 기준연도"},
    {"tool": "detect_aggregates", "name": "대륙/그룹/소득 집계 행 감지"},
    {"tool": "describe_numeric", "name": "숫자형 기술통계 (평균·중앙값·최소·최대)"},
    {"tool": "trend_line", "name": "연도별 추이 (선 차트)"},
    {"tool": "top_bottom_n", "name": "기준연도 상위·하위 N개 (수평 막대)"},
    {"tool": "group_summary", "name": "그룹(Region)별 집계 (막대 차트)"},
    {"tool": "change_rate", "name": "두 시점 간 변화량·변화율"},
    {"tool": "distribution", "name": "구간별 빈도 분포 (히스토그램)"},
    {"tool": "correlation_scatter", "name": "상관계수 및 산점도"},
    {"tool": "compare_one_vs_all", "name": "특정 대상(한국) vs 전체 평균·중앙값 비교"},
    {"tool": "custom_dynamic_query", "name": "유저 맞춤형 동적 연산 (자연어 커스텀 분석)"}
]

ALLOWED_TOOL_NAMES = {t["tool"] for t in TOOL_CATALOG}
TOOL_CATALOG_MAP = {t["tool"]: t["name"] for t in TOOL_CATALOG}

TOOL_FUNCTIONS = {
    "reshape_wide_to_long": tools.tool_reshape_wide_to_long,
    "quality_report": tools.tool_quality_report,
    "year_coverage": tools.tool_year_coverage,
    "detect_aggregates": tools.tool_detect_aggregates,
    "describe_numeric": tools.tool_describe_numeric,
    "trend_line": tools.tool_trend_line,
    "top_bottom_n": tools.tool_top_bottom_n,
    "group_summary": tools.tool_group_summary,
    "change_rate": tools.tool_change_rate,
    "distribution": tools.tool_distribution,
    "correlation_scatter": tools.tool_correlation_scatter,
    "compare_one_vs_all": tools.tool_compare_one_vs_all,
    "custom_dynamic_query": tools.tool_custom_dynamic_query
}

STRICT_REF_TOOLS = {
    "describe_numeric", "top_bottom_n", "group_summary", 
    "change_rate", "distribution", "correlation_scatter", "compare_one_vs_all"
}

def call_gemini_with_retry(client, model_name, contents, config=None, max_retries=3):
    """
    Gemini API 일시적 503 UNAVAILABLE / 429 RateLimit 발생 시 자동 지연 후 재시도 (최대 3회)
    """
    for attempt in range(1, max_retries + 1):
        try:
            if config:
                return client.models.generate_content(model=model_name, contents=contents, config=config)
            else:
                return client.models.generate_content(model=model_name, contents=contents)
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "ResourceExhausted" in err_str) and attempt < max_retries:
                sleep_sec = attempt * 1.5
                logger.warning(f"[AI] Gemini API 일시적 혼잡(503/429) 감지. {sleep_sec}초 후 자동 재시도 ({attempt}/{max_retries})...")
                time.sleep(sleep_sec)
            else:
                raise e

@app.route('/', methods=['GET'])
def index():
    logger.info("[REQUEST] GET /")
    return render_template('index.html')

def detect_encoding_and_header(file_bytes):
    encodings = ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']
    successful_encoding = None
    decoded_text = None

    for enc in encodings:
        try:
            decoded_text = file_bytes.decode(enc)
            successful_encoding = enc
            logger.info(f"[ENCODING] {enc} 시도 성공")
            break
        except UnicodeDecodeError:
            logger.info(f"[ENCODING] {enc} 시도 실패")
            continue

    if not successful_encoding or decoded_text is None:
        raise ValueError("지원하는 인코딩(utf-8-sig, utf-8, cp949, euc-kr)으로 파일 글자를 읽을 수 없습니다.")

    lines = decoded_text.splitlines()
    if not lines or not any(l.strip() for l in lines):
        raise ValueError("빈 CSV 파일입니다. 데이터 내용이 없습니다.")

    best_idx = 0
    max_cols = 0
    for idx, line in enumerate(lines[:15]):
        if not line.strip():
            continue
        try:
            row = next(csv.reader([line]))
            non_empty = [col for col in row if col.strip()]
            if len(non_empty) > max_cols:
                max_cols = len(non_empty)
                best_idx = idx
        except Exception:
            continue

    if max_cols == 0:
        raise ValueError("CSV 헤더(열 이름) 행을 감지할 수 없습니다.")

    logger.info(f"[HEADER] 헤더 줄 감지 결과 (건너뛴 줄 수: {best_idx})")
    
    csv_io = io.StringIO("\n".join(lines[best_idx:]))
    df = pd.read_csv(csv_io)

    return df, successful_encoding, best_idx

def diagnose_dataset(df, filename, filesize, encoding, skipped_lines):
    total_rows, total_cols = df.shape
    col_names = [str(c) for c in df.columns]

    column_types = {col: str(df[col].dtype) for col in col_names}
    numeric_columns = [col for col in col_names if pd.api.types.is_numeric_dtype(df[col])]
    text_columns = [col for col in col_names if not pd.api.types.is_numeric_dtype(df[col])]
    year_date_columns = [
        col for col in col_names 
        if re.match(r'^(19|20)\d{2}$', col.strip()) or 'date' in col.lower() or 'year' in col.lower()
    ]

    missing_counts = {col: int(df[col].isna().sum()) for col in col_names}
    missing_ratios = {col: round(float(df[col].isna().mean() * 100), 2) for col in col_names}
    duplicate_rows_count = int(df.duplicated().sum())

    unnamed_or_empty_columns = [
        col for col in col_names 
        if col.startswith('Unnamed:') or col.strip() == ''
    ]

    year_coverage = {}
    if year_date_columns:
        for col in year_date_columns:
            year_coverage[col] = int(df[col].notna().sum())

    recommended_reference_year = None
    if year_coverage:
        max_valid = max(year_coverage.values()) if year_coverage.values() else 0
        if max_valid > 0:
            valid_years = [y for y, count in year_coverage.items() if count >= max_valid * 0.75]
            if valid_years:
                numeric_years = [y for y in valid_years if y.isdigit()]
                if numeric_years:
                    recommended_reference_year = max(numeric_years, key=int)
                else:
                    recommended_reference_year = valid_years[-1]

    agg_keywords = [
        'world', 'oecd members', 'euro area', 'european union', 'high income', 
        'low income', 'income', 'area', 'small states', 'total', 'aggregate', 
        'sub-saharan', 'latin america', 'caribbean', 'middle east', 'north america', 'south asia'
    ]
    label_col = 'Country Name' if 'Country Name' in col_names else (text_columns[0] if text_columns else None)
    
    aggregate_rows_detected = []
    if label_col:
        for idx, val in enumerate(df[label_col].astype(str)):
            val_lower = val.lower()
            if any(kw in val_lower for kw in agg_keywords):
                aggregate_rows_detected.append({"row_index": idx, "name": val})

    preview_df = df.head(10).replace({np.nan: None})
    preview_rows = preview_df.to_dict(orient='records')

    warnings = []
    if skipped_lines > 0:
        warnings.append(f"상단 주석 메모 {skipped_lines}줄을 감지하여 스킵하고 {skipped_lines + 1}번째 줄을 헤더로 읽었습니다.")
    if unnamed_or_empty_columns:
        warnings.append(f"이름이 없거나 자동 생성된 Unnamed 열이 감지되었습니다: {unnamed_or_empty_columns}")
    if duplicate_rows_count > 0:
        warnings.append(f"중복된 행이 {duplicate_rows_count}개 감지되었습니다.")
    if aggregate_rows_detected:
        warnings.append(f"국가가 아닌 지역/그룹/소득 집계 행이 {len(aggregate_rows_detected)}개 포함되어 있습니다.")
    if year_coverage and recommended_reference_year:
        latest_year = max([y for y in year_coverage.keys() if y.isdigit()], key=int, default=None)
        if latest_year and latest_year != recommended_reference_year:
            warnings.append(f"가장 최근 연도({latest_year}년)는 데이터 입력률이 낮습니다. 데이터가 충분히 채워진 {recommended_reference_year}년을 기준연도로 권장합니다.")

    logger.info(f"[DIAGNOSE] 진단 완료 warnings={len(warnings)}")

    return {
        "filename": filename,
        "filesize_bytes": filesize,
        "encoding": encoding,
        "skipped_header_lines": skipped_lines,
        "total_rows": total_rows,
        "total_columns": total_cols,
        "column_names": col_names,
        "column_types": column_types,
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "year_date_columns": year_date_columns,
        "missing_counts": missing_counts,
        "missing_ratios": missing_ratios,
        "duplicate_rows_count": duplicate_rows_count,
        "unnamed_or_empty_columns": unnamed_or_empty_columns,
        "year_coverage": year_coverage,
        "recommended_reference_year": recommended_reference_year,
        "aggregate_rows_detected": aggregate_rows_detected,
        "preview_rows": preview_rows,
        "warnings": warnings
    }

@app.route('/health', methods=['GET'])
def health():
    logger.info("[REQUEST] GET /health")
    api_key = os.getenv("GEMINI_API_KEY")
    key_configured = bool(api_key and api_key.strip() and api_key != "your_gemini_api_key_here")
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    
    return jsonify({
        "status": "ok",
        "api_key_configured": key_configured,
        "model": model_name
    })

@app.route('/inspect', methods=['POST'])
def inspect():
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /inspect")

    if 'file' not in request.files:
        logger.error("[ERROR] 업로드 파일 누락")
        return jsonify({"error": "업로드된 파일이 없습니다."}), 400

    file = request.files['file']
    filename = file.filename

    if not filename or not filename.lower().endswith('.csv'):
        logger.error(f"[ERROR] 허용되지 않은 파일 형식: {filename}")
        return jsonify({"error": "CSV 파일(.csv)만 업로드 가능합니다."}), 400

    file_bytes = file.read()
    filesize = len(file_bytes)
    logger.info(f"[FILE] name={filename} size={filesize} bytes")

    if filesize == 0:
        logger.error("[ERROR] 빈 파일 업로드")
        return jsonify({"error": "업로드된 파일이 비어 있습니다."}), 400

    try:
        df, encoding, skipped_lines = detect_encoding_and_header(file_bytes)
    except Exception as e:
        logger.error(f"[ERROR] CSV 해석 오류: {str(e)}")
        return jsonify({"error": str(e)}), 400

    logger.info(f"[CSV] parsing 완료 rows={len(df)} columns={len(df.columns)}")

    diagnosis_result = diagnose_dataset(df, filename, filesize, encoding, skipped_lines)

    CURRENT_DATASET = {
        "df": df,
        "filename": filename,
        "filesize": filesize,
        "encoding": encoding,
        "skipped_lines": skipped_lines,
        "diagnosis": diagnosis_result
    }

    return jsonify(diagnosis_result)

def analyze_run_error(e, df, tool_name, params):
    err_str = str(e)
    year_cols = [c for c in df.columns if re.match(r'^(19|20)\d{2}$', str(c).strip())]
    korean_tool = TOOL_CATALOG_MAP.get(tool_name, tool_name)
    ref_period = params.get("reference_period") or params.get("column") or params.get("start_period") or ""

    if "기준시점" in err_str or "열이 데이터에 없습니다" in err_str or "KeyError" in err_str or "입력해야 합니다" in err_str:
        latest_years = ", ".join(year_cols[-5:]) if year_cols else "2024"
        return {
            "error": f"도구 '{korean_tool}' 실행 중 기준 시점 오류가 발생했습니다.",
            "reason": f"입력하신 기준 시점/연도('{ref_period}')가 CSV 데이터셋 열(Header)에 존재하지 않습니다.",
            "suggestion": f"데이터가 존재하는 연도({latest_years}) 중 하나를 '기준 시점(연도)' 상자에 입력해 주세요.",
            "available_years": year_cols
        }
    elif "찾을 수 없습니다" in err_str or "empty" in err_str.lower() or "대상" in err_str:
        return {
            "error": f"도구 '{korean_tool}' 항목 필터링 실패",
            "reason": f"선택된 대상 항목('{params.get('target_name', 'N/A')}')을 데이터셋에서 찾을 수 없습니다.",
            "suggestion": "대상 국가명/항목명을 영문 정식명칭(예: 'Korea, Rep.' 또는 'Korea')으로 정확히 입력해 보세요."
        }
    elif "두 열" in err_str or "상관분석" in err_str:
        return {
            "error": f"도구 '{korean_tool}' 수치 연산 실패",
            "reason": f"상관분석에 필요한 두 연도/수치 열이 데이터셋에 부족합니다. ({err_str})",
            "suggestion": "다른 시점이나 두 수치 열을 포함하도록 데이터를 확인하세요."
        }
    else:
        return {
            "error": f"도구 '{korean_tool}' 실행 실패 ({err_str})",
            "reason": "데이터셋 조건이나 선택된 도구의 입력 파라미터가 맞지 않습니다.",
            "suggestion": "기준 시점을 데이터가 유효한 다른 연도로 변경하거나 집계 행 자동 제외 옵션을 체크/해제해 보세요."
        }

@app.route('/suggest', methods=['POST'])
def suggest():
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /suggest")

    if not CURRENT_DATASET or 'diagnosis' not in CURRENT_DATASET:
        logger.error("[ERROR] 진단 결과 미존재")
        return jsonify({"error": "먼저 CSV 파일을 업로드하여 진단을 수행하세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.strip() == "" or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에서 설정해주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    diag = CURRENT_DATASET["diagnosis"]
    df = CURRENT_DATASET["df"]

    rec_year = diag.get("recommended_reference_year") or "2024"

    diag_summary = {
        "filename": diag["filename"],
        "total_rows": diag["total_rows"],
        "total_columns": diag["total_columns"],
        "recommended_reference_year": rec_year,
        "year_date_columns": diag.get("year_date_columns", [])[:10],
        "text_columns": diag.get("text_columns", []),
        "numeric_columns": diag.get("numeric_columns", [])[:15],
        "warnings": diag.get("warnings", []),
        "aggregate_rows_count": len(diag.get("aggregate_rows_detected", []))
    }

    prompt = f"""
당신은 전 세계 통계 및 CSV 데이터 분석 전문가입니다.
아래 데이터셋 진단 요약과 12가지 분석 도구 카탈로그를 참조하여, 이 데이터에서 실행 가능한 가장 가치 있고 유용한 분석 도구를 3~5개 골라 제안해주세요.

[데이터셋 진단 요약]
{json.dumps(diag_summary, ensure_ascii=False, indent=2)}

[허용된 12가지 도구 카탈로그 (이 도구명만 사용 가능)]
{json.dumps(TOOL_CATALOG, ensure_ascii=False, indent=2)}

[절대 지켜야 할 규칙]
1. 응답은 오직 요청된 JSON 형식만 출력해야 합니다.
2. 'tool' 항목의 값은 위 12가지 카탈로그에 있는 영문 도구명만 사용해야 합니다.
3. 'params'에는 데이터셋 진단 요약에 존재하는 열 이름과 파라미터를 명시하세요.
4. 'reference_period'는 진단에서 권장된 연도('{rec_year}')를 최우선으로 활용하세요.
5. 제안 항목 수는 3개 이상 5개 이하로 구성하세요.

[JSON 출력 양식 규격]
{{
  "suggestions": [
    {{
      "tool": "top_bottom_n",
      "params": {{
        "reference_period": "{rec_year}",
        "n": 10,
        "exclude_aggregates": true
      }},
      "reference_period": "{rec_year}",
      "why": "이 분석이 해당 데이터셋에서 필요한 구체적 이유",
      "caution": "결과를 해석할 때 주의할 점"
    }}
  ]
}}
"""

    logger.info(f"[AI] suggest 요청 시작 (model={model_name})")

    try:
        client = genai.Client(api_key=api_key)
        response = call_gemini_with_retry(
            client=client,
            model_name=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        logger.info("[AI] suggest 응답 수신 성공")

        raw_text = response.text
        suggest_data = json.loads(raw_text)

        raw_suggestions = suggest_data.get("suggestions", [])
        validated_suggestions = []
        year_cols = diag.get("year_date_columns", [])

        for s in raw_suggestions:
            if not isinstance(s, dict):
                continue
            t_name = s.get("tool")
            if t_name not in ALLOWED_TOOL_NAMES:
                continue

            t_params = s.get("params") or {}
            is_ok = False

            # 1차 실행 및 필요시 검증 자동 보정
            try:
                if t_name == "custom_dynamic_query":
                    tools.tool_custom_dynamic_query(df, **t_params)
                else:
                    tool_func = TOOL_FUNCTIONS[t_name]
                    tool_func(df, **t_params)
                is_ok = True
            except Exception as ex1:
                try:
                    repaired = dict(t_params)
                    if "reference_period" in repaired or t_name in STRICT_REF_TOOLS:
                        repaired["reference_period"] = rec_year
                    if t_name == "correlation_scatter" and len(year_cols) >= 2:
                        repaired["x_col"] = year_cols[0]
                        repaired["y_col"] = year_cols[-1]

                    if t_name == "custom_dynamic_query":
                        tools.tool_custom_dynamic_query(df, **repaired)
                    else:
                        tool_func = TOOL_FUNCTIONS[t_name]
                        tool_func(df, **repaired)
                    
                    s["params"] = repaired
                    is_ok = True
                except Exception as ex2:
                    logger.warning(f"[SUGGEST] 제안 검증 실패로 제외 (tool={t_name}): {ex1}")
                    is_ok = False

            if is_ok:
                s["is_validated"] = True
                validated_suggestions.append(s)

        logger.info(f"[AI] 수치 연산 검증 완료 제안 개수: {len(validated_suggestions)}/{len(raw_suggestions)}")

        return jsonify({
            "model_used": model_name,
            "total_suggestions": len(validated_suggestions),
            "suggestions": validated_suggestions
        })

    except Exception as e:
        logger.error(f"[ERROR] Gemini suggest 오류: {str(e)}")
        return jsonify({"error": f"Gemini 분석 제안 생성 중 오류 발생: {str(e)}"}), 500

@app.route('/run', methods=['POST'])
def run_tool():
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /run")

    if not CURRENT_DATASET or 'df' not in CURRENT_DATASET:
        logger.error("[ERROR] 데이터셋 미존재")
        return jsonify({"error": "분석할 CSV 데이터셋이 없습니다. 먼저 /inspect 로 업로드하세요."}), 400

    data = request.get_json() or {}
    tool_name = data.get("tool")
    params = data.get("params") or {}

    if not tool_name or tool_name not in TOOL_FUNCTIONS:
        logger.error(f"[ERROR] 미지원 도구 요청: {tool_name}")
        return jsonify({"error": f"지원하지 않거나 존재하지 않는 도구입니다: '{tool_name}'"}), 400

    ref_period = params.get("reference_period") or params.get("column") or params.get("start_period")
    if tool_name in STRICT_REF_TOOLS and not ref_period:
        logger.error(f"[ERROR] {tool_name} 필수 파라미터(reference_period) 누락")
        return jsonify({"error": f"'{tool_name}' 도구를 실행하려면 기준 시점(reference_period)을 필수로 입력해야 합니다."}), 400

    df = CURRENT_DATASET["df"]

    try:
        if tool_name == "custom_dynamic_query":
            result_payload = tools.tool_custom_dynamic_query(df, **params)
        else:
            tool_func = TOOL_FUNCTIONS[tool_name]
            result_payload = tool_func(df, **params)

        rows_used = result_payload.get("rows_used", len(df))
        rows_excluded = result_payload.get("rows_excluded", 0)

        logger.info(f"[TOOL] 도구명={tool_name}, 파라미터={params}, 사용행수={rows_used}, 제외행수={rows_excluded}")
        logger.info("[RESPONSE] status=200")

        CURRENT_DATASET["last_run_result"] = result_payload
        CURRENT_DATASET["last_user_question"] = None

        return jsonify(result_payload)

    except Exception as e:
        logger.error(f"[ERROR] 도구 실행 실패: {str(e)}")
        error_info = analyze_run_error(e, df, tool_name, params)
        return jsonify(error_info), 400

@app.route('/query', methods=['POST'])
def query_question():
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /query")

    if not CURRENT_DATASET or 'df' not in CURRENT_DATASET:
        logger.error("[ERROR] 데이터셋 미존재")
        return jsonify({"error": "먼저 CSV 파일을 업로드하여 진단을 수행하세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.strip() == "" or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에서 설정해주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    data = request.get_json() or {}
    user_question = data.get("question", "").strip()

    if not user_question:
        return jsonify({"error": "질문 내용을 입력해주세요."}), 400

    df = CURRENT_DATASET["df"]
    diag = CURRENT_DATASET["diagnosis"]
    rec_year = diag.get("recommended_reference_year") or "2024"

    logger.info(f"[AI] NLQuery 의도 파악 시작 (질문='{user_question}')")

    intent_prompt = f"""
당신은 데이터 분석 지능형 라우터입니다.
사용자의 질문과 CSV 데이터 진단을 읽고, 질문에 대답하기 가장 적절한 분석 도구 1~2개를 선정하거나, 기존 12개 기본 도구로 처리하기 어려운 맞춤 질문인 경우 'custom_dynamic_query'를 선택하세요.

[사용자 질문]
"{user_question}"

[데이터셋 정보]
- 전체 행 수: {diag.get('total_rows')}, 전체 열 수: {diag.get('total_columns')}
- 권장 기준연도: {rec_year}
- 주요 열 목록: {json.dumps(diag.get('column_names', [])[:25], ensure_ascii=False)}

[허용 도구 카탈로그]
{json.dumps(TOOL_CATALOG, ensure_ascii=False, indent=2)}

[핵심 라우팅 지침]
1. 사용자가 특정 대상(예: "한국", "대한민국", "Korea", "미국", "Japan" 등)의 위치나 순위를 상위/하위 N개와 함께 언급한 경우:
   - primary_tool: "top_bottom_n"
   - primary_params: {{ "reference_period": "{rec_year}", "n": 10, "target_name": "Korea, Rep.", "exclude_aggregates": true }}
   (반드시 primary_params에 'target_name'으로 질문에 등장한 대상 국가명을 영문/원문 형태로 기재하세요)

2. 질문이 상위/하위 순위, 시계열 추이, 상관관계, 구간분포 등 12가지 정형 도구 범위 내라면 알맞은 도구를 선택하세요.

3. 질문이 기존 12가지 도구만으로 완벽히 표현하기 어려운 맞춤형 질문인 경우:
   - primary_tool: "custom_dynamic_query"
   - primary_params: {{
       "description": "질문에 부합하는 동적 연산 설명",
       "code_snippet": "result_df = df.dropna(subset=['{rec_year}']).sort_values(by='{rec_year}', ascending=False).head(10)[['{diag.get('column_names', ['Country Name'])[0]}', '{rec_year}']]"
     }}

[JSON 응답 양식]
{{
  "primary_tool": "top_bottom_n",
  "primary_params": {{ "reference_period": "{rec_year}", "n": 10, "target_name": "Korea, Rep.", "exclude_aggregates": true }},
  "secondary_tool": "compare_one_vs_all",
  "secondary_params": {{ "target_name": "Korea, Rep.", "reference_period": "{rec_year}", "exclude_aggregates": true }}
}}
"""

    try:
        client = genai.Client(api_key=api_key)
        intent_res = call_gemini_with_retry(
            client=client,
            model_name=model_name,
            contents=intent_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        intent_data = json.loads(intent_res.text)
        primary_tool_name = intent_data.get("primary_tool", "top_bottom_n")
        primary_params = intent_data.get("primary_params") or {"reference_period": rec_year, "n": 10, "exclude_aggregates": True}

        logger.info(f"[TOOL] NLQuery 1차 실행: tool={primary_tool_name}, params={primary_params}")
        
        if primary_tool_name == "custom_dynamic_query":
            primary_result = tools.tool_custom_dynamic_query(df, **primary_params)
        else:
            tool_func = TOOL_FUNCTIONS.get(primary_tool_name, tools.tool_top_bottom_n)
            primary_result = tool_func(df, **primary_params)

        secondary_result = None
        sec_tool_name = intent_data.get("secondary_tool")
        sec_params = intent_data.get("secondary_params")
        if sec_tool_name and sec_tool_name in TOOL_FUNCTIONS and sec_params:
            try:
                sec_func = TOOL_FUNCTIONS[sec_tool_name]
                secondary_result = sec_func(df, **sec_params)
            except Exception as se:
                logger.warning(f"Secondary tool execution skipped: {se}")

        answer_prompt = f"""
당신은 친절한 AI 데이터 데이터 컨설턴트입니다.
사용자의 질문에 대해 아래 [Pandas 실제 수치 연산 결과]만을 근거로 명확하고 친절하게 답변해주세요.

[사용자 질문]
"{user_question}"

[Pandas 1차 연산 결과]
{json.dumps(primary_result, ensure_ascii=False, indent=2)}

[Pandas 2차 연산 결과 (있을 경우)]
{json.dumps(secondary_result, ensure_ascii=False, indent=2) if secondary_result else '없음'}

[작성 규칙]
1. 계산 결과에 있는 실제 수치와 순위를 언급하며 구체적으로 답변하세요.
2. 사용된 행 수와 제외된 행 수/사유를 언급하여 분석의 투명성을 보여주세요.
3. 중학생도 이해할 수 있게 쉬운 한국어 마크다운으로 답변을 작성하세요.
"""
        ans_res = call_gemini_with_retry(
            client=client,
            model_name=model_name,
            contents=answer_prompt
        )

        logger.info("[AI] NLQuery 답변 생성 성공")

        CURRENT_DATASET["last_run_result"] = primary_result
        CURRENT_DATASET["last_user_question"] = user_question

        return jsonify({
            "question": user_question,
            "tool_used": primary_tool_name,
            "primary_params": primary_params,
            "korean_tool_name": TOOL_CATALOG_MAP.get(primary_tool_name, primary_tool_name),
            "primary_result": primary_result,
            "secondary_result": secondary_result,
            "answer": ans_res.text
        })

    except Exception as e:
        logger.error(f"[ERROR] 자연어 질문 처리 오류: {str(e)}")
        return jsonify({"error": f"Gemini API 일시적 혼잡(503) 또는 질문 처리 오류가 발생했습니다: {str(e)}. 잠시 후 다시 시도해 주세요."}), 500

@app.route('/explain', methods=['POST'])
def explain():
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /explain")

    if not CURRENT_DATASET or 'diagnosis' not in CURRENT_DATASET:
        logger.error("[ERROR] 진단 결과 미존재")
        return jsonify({"error": "먼저 CSV 파일을 업로드하고 분석 도구를 실행하세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.strip() == "" or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에서 설정해주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    data = request.get_json() or {}
    mode = str(data.get("mode", "B")).upper()

    diag = CURRENT_DATASET["diagnosis"]
    last_result = CURRENT_DATASET.get("last_run_result")

    logger.info(f"[AI] explain 요청 시작 (모드={mode}, model={model_name})")

    try:
        client = genai.Client(api_key=api_key)

        if mode == "A":
            prompt_a = f"""
당신은 일반적인 AI 조교입니다.
아래 CSV 파일 진단 정보만 바탕으로 이 데이터를 분석해서 종합 분석 보고서를 작성해 주세요.

[CSV 파일 정보]
- 파일명: {diag.get('filename')}
- 행 수: {diag.get('total_rows')}, 열 수: {diag.get('total_columns')}
- 열 이름: {json.dumps(diag.get('column_names', [])[:20], ensure_ascii=False)}

자유로운 서식으로 이 데이터에 대한 보고서를 작성해주세요.
"""
            response = call_gemini_with_retry(
                client=client,
                model_name=model_name,
                contents=prompt_a
            )
            logger.info("[AI] explain 모드 A 응답 수신 성공")
            return jsonify({
                "mode": "A",
                "explanation": response.text,
                "note": "모드 A는 계산 결과 없이 진단 정보만 전달된 허술한 비교용 보고서입니다."
            })

        else:
            if not last_result:
                return jsonify({"error": "정식 보고서(모드 B) 작성을 위해서는 먼저 /run 으로 분석 도구를 실행해야 합니다."}), 400

            last_question = CURRENT_DATASET.get("last_user_question")
            question_context = f"\n- 사용자 특정 분석 질문: \"{last_question}\"" if last_question else ""

            prompt_b = f"""
당신은 신뢰성을 최우선으로 하는 데이터 분석 전문가입니다.
반드시 아래에 제공된 [Pandas 수치 계산 결과]와 [데이터셋 배경 정보]만을 바탕으로 보고서를 작성해야 합니다.

[데이터셋 진단 및 배경]
- 파일명: {diag.get('filename')}
- 전체 행 수: {diag.get('total_rows')}, 전체 열 수: {diag.get('total_columns')}
- 지표 정의: 세계은행 인구 대비 인터넷 사용자 비율 지표 (국제전기통신연합 ITU 데이터베이스 출처){question_context}

[Pandas 수치 계산 결과]
{json.dumps(last_result, ensure_ascii=False, indent=2)}

[엄격한 8대 작성 규칙]
1. 제공된 계산 결과에 있는 숫자만 사용하고, 직접 계산하거나 추정하지 마세요.
2. 제공된 데이터에 없는 국가, 연도, 열 이름을 절대로 언급하거나 지어내지 마세요.
3. 기준 시점과 사용된 행 수, 제외된 행 수와 제외 이유를 본문에 반드시 명확히 표기하세요.
4. 상관관계를 설명할 때는 절대로 '인과관계(원인과 결과)'로 표현하지 마세요.
5. 지표의 정의와 출처를 보고서 앞부분에 표기하세요.
6. 데이터로 확인할 수 없는 것은 "이 데이터로는 확인할 수 없다"라고 명확히 적으세요.
7. 중학생도 이해할 수 있게 쉬운 말로 쓰되 정확성을 훼손하지 마세요. (사용자의 원래 질문이 있다면 질문에 대답하는 방향으로 요약 제시)
8. 아래 지정된 7개 마크다운 헤더 제목 구조를 정확히 지켜서 작성하세요.

[필수 마크다운 출력 구조]
## 무엇을 봤는가
## 데이터 출처와 정의
## 기준 시점과 제외된 항목
## 계산 결과
## 읽어낼 수 있는 것
## 이 데이터로는 알 수 없는 것
## 다음에 확인해볼 것
"""
            response = call_gemini_with_retry(
                client=client,
                model_name=model_name,
                contents=prompt_b
            )
            logger.info("[AI] explain 모드 B 응답 수신 성공")
            return jsonify({
                "mode": "B",
                "explanation": response.text,
                "note": "모드 B는 Pandas 계산 수치만 사용하여 엄격한 규격을 준수한 정식 보고서입니다."
            })

    except Exception as e:
        logger.error(f"[ERROR] Gemini explain 오류: {str(e)}")
        return jsonify({"error": f"AI 해석 보고서 생성 중 오류 발생: {str(e)}"}), 500

if __name__ == '__main__':
    debug_mode = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    logger.info(f"Starting Flask dev server on http://127.0.0.1:5000 (debug={debug_mode})")
    app.run(host='127.0.0.1', port=5000, debug=debug_mode)
