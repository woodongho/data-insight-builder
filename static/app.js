/* =========================================================
   AI Data Insight Builder - Frontend Logic (Vanilla JS + Chart.js)
   ========================================================= */

let currentChart = null;
let currentDiagnosis = null;
let currentToolResult = null;
let currentQueryParams = {};
let currentMarkdownReport = "";
let logCount = 0;

const TOOL_KOREAN_NAMES = {
    "reshape_wide_to_long": "와이드 ↔ 롱 포맷 변환 (연도 열을 행으로 접기)",
    "quality_report": "데이터 품질 종합 보고서 (결측치·중복·유령열 진단)",
    "year_coverage": "연도별 데이터 충실도 & 권장 기준연도 판별",
    "detect_aggregates": "대륙·그룹·소득 집계 행 자동 감지",
    "describe_numeric": "수치 요약 통계 (평균·중앙값·최소·최대)",
    "trend_line": "연도별 시계열 변화 추이 (선 그래프)",
    "top_bottom_n": "기준연도 상위 N개 vs 하위 N개 비교 (막대 그래프)",
    "group_summary": "대륙·그룹별 평균 요약 비교 (막대 그래프)",
    "change_rate": "두 시점 간 성과 변화량·변화율 비교",
    "distribution": "수치 구간별 분포 상태 (히스토그램)",
    "correlation_scatter": "두 변수 간 상관계수 & 연관성 분석 (산점도)",
    "compare_one_vs_all": "특정 나라(한국) vs 전체 평균 대조 분석",
    "custom_dynamic_query": "유저 맞춤형 동적 연산 (자연어 커스텀 분석)"
};

function getToolDisplayName(toolKey) {
    return TOOL_KOREAN_NAMES[toolKey] || toolKey;
}

// ---------------------------------------------------------
// 1. 프론트엔드 콘솔 로거 (개인정보/API Key/CSV 원본 로그 금지)
// ---------------------------------------------------------
function logConsole(tag, message, level = 'system') {
    logCount++;
    const logBody = document.getElementById('console-log-body');
    const logCountSpan = document.getElementById('log-count');
    
    if (logCountSpan) logCountSpan.textContent = logCount;

    const entry = document.createElement('div');
    entry.className = `log-entry log-${level}`;
    const timestamp = new Date().toLocaleTimeString();
    entry.textContent = `[${timestamp}] [${tag}] ${message}`;

    if (logBody) {
        logBody.appendChild(entry);
        logBody.scrollTop = logBody.scrollHeight;
    }

    console.log(`[${tag}] ${message}`);
}

// ---------------------------------------------------------
// 2. 초기화 & Health Check
// ---------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    logConsole('PAGE', '페이지 로드 완료');
    checkHealthStatus();
    initEventListeners();
});

async function checkHealthStatus() {
    try {
        const res = await fetch('/health');
        if (!res.ok) throw new Error('서버 연결 실패');
        const data = await res.json();

        const badge = document.getElementById('api-status-badge');
        const modelBadge = document.getElementById('model-name-badge');

        if (data.api_key_configured) {
            badge.className = 'status-badge status-ok';
            badge.textContent = 'API Key: 설정 완료';
        } else {
            badge.className = 'status-badge status-error';
            badge.textContent = 'API Key: 미설정 (.env 확인)';
        }

        if (modelBadge && data.model) {
            modelBadge.textContent = `Model: ${data.model}`;
        }
    } catch (err) {
        logConsole('ERROR', `Health Check 실패: ${err.message}`, 'error');
        const badge = document.getElementById('api-status-badge');
        if (badge) {
            badge.className = 'status-badge status-error';
            badge.textContent = '서버 응답 없음';
        }
    }
}

// ---------------------------------------------------------
// 3. 이벤트 리스너 등록
// ---------------------------------------------------------
function initEventListeners() {
    const fileInput = document.getElementById('csv-file-input');
    const dropZone = document.getElementById('drop-zone');
    const btnSuggest = document.getElementById('btn-suggest');
    const btnRunTool = document.getElementById('btn-run-tool');
    const btnExplainA = document.getElementById('btn-explain-mode-a');
    const btnExplainB = document.getElementById('btn-explain-mode-b');
    const btnDownloadMd = document.getElementById('btn-download-md');
    const btnSubmitQuery = document.getElementById('btn-submit-query');
    const inputQuestion = document.getElementById('input-custom-question');
    const consoleToggle = document.getElementById('console-toggle');
    const toolSelect = document.getElementById('select-active-tool');

    if (consoleToggle) {
        consoleToggle.addEventListener('click', () => {
            document.querySelector('.console-drawer').classList.toggle('collapsed');
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                handleFileUpload(e.target.files[0]);
            }
        });
    }

    if (dropZone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropZone.classList.add('drag-over');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropZone.classList.remove('drag-over');
            }, false);
        });

        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length > 0) {
                handleFileUpload(files[0]);
            }
        });
    }

    if (btnSuggest) btnSuggest.addEventListener('click', requestAISuggestions);
    if (btnRunTool) btnRunTool.addEventListener('click', executeSelectedTool);
    if (btnExplainA) btnExplainA.addEventListener('click', () => requestAIExplanation('A'));
    if (btnExplainB) btnExplainB.addEventListener('click', () => requestAIExplanation('B'));
    if (btnDownloadMd) btnDownloadMd.addEventListener('click', downloadMarkdownReport);

    if (btnSubmitQuery) {
        btnSubmitQuery.addEventListener('click', () => {
            const q = inputQuestion.value.trim();
            if (q) submitCustomQuery(q);
            else alert('질문 내용을 입력해주세요.');
        });
    }

    const btnGotoVis = document.getElementById('btn-goto-vis');
    if (btnGotoVis) {
        btnGotoVis.addEventListener('click', () => {
            const runSec = document.getElementById('run-section');
            if (runSec) {
                runSec.classList.remove('hidden');
                runSec.scrollIntoView({ behavior: 'smooth' });
            }
        });
    }

    if (inputQuestion) {
        inputQuestion.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const q = inputQuestion.value.trim();
                if (q) submitCustomQuery(q);
                else alert('질문 내용을 입력해주세요.');
            }
        });
    }

    // 예시 질문 칩 버튼 이벤트 연결
    document.querySelectorAll('.chip-btn').forEach(chip => {
        chip.addEventListener('click', (e) => {
            const q = e.currentTarget.getAttribute('data-question');
            if (inputQuestion) inputQuestion.value = q;
            submitCustomQuery(q);
        });
    });

    if (toolSelect) {
        toolSelect.addEventListener('change', onToolSelectChange);
    }
}

// ---------------------------------------------------------
// 4. CSV 업로드 및 /inspect 요청
// ---------------------------------------------------------
async function handleFileUpload(file) {
    if (!file.name.toLowerCase().endsWith('.csv')) {
        alert('CSV 파일(.csv)만 업로드 가능합니다.');
        logConsole('ERROR', `허용되지 않은 파일 형식: ${file.name}`, 'error');
        return;
    }

    const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
    logConsole('UPLOAD', `파일 선택: ${file.name} (${fileSizeMB} MB)`, 'upload');

    const formData = new FormData();
    formData.append('file', file);

    const fileInfoDiv = document.getElementById('file-info-display');
    fileInfoDiv.classList.remove('hidden');
    fileInfoDiv.textContent = `📄 업로드 파일: ${file.name} (${fileSizeMB} MB)`;

    logConsole('INSPECT', '진단 요청 시작 (/inspect)', 'inspect');

    try {
        const res = await fetch('/inspect', {
            method: 'POST',
            body: formData
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '진단 실패');

        currentDiagnosis = data;
        logConsole('INSPECT', `진단 응답 수신 (행: ${data.total_rows}, 열: ${data.total_columns}, 경고: ${data.warnings.length}개)`, 'inspect');

        renderInspectionResults(data);

    } catch (err) {
        logConsole('ERROR', `진단 실패: ${err.message}`, 'error');
        alert(`진단 실패: ${err.message}`);
    }
}

// ---------------------------------------------------------
// 5. 진단 결과 화면 렌더링
// ---------------------------------------------------------
function renderInspectionResults(data) {
    document.getElementById('inspect-result-section').classList.remove('hidden');
    document.getElementById('custom-query-section').classList.remove('hidden');

    document.getElementById('meta-encoding').textContent = data.encoding;
    document.getElementById('meta-skipped-lines').textContent = `${data.skipped_header_lines}줄`;
    document.getElementById('meta-total-rows').textContent = `${data.total_rows}행`;
    document.getElementById('meta-total-cols').textContent = `${data.total_columns}열`;
    document.getElementById('meta-rec-year').textContent = data.recommended_reference_year ? `${data.recommended_reference_year}년` : 'N/A';
    document.getElementById('meta-agg-count').textContent = `${data.aggregate_rows_detected.length}개`;

    document.getElementById('meta-year-cols').textContent = data.year_date_columns.join(', ') || '없음';
    document.getElementById('meta-unnamed-cols').textContent = data.unnamed_or_empty_columns.join(', ') || '없음';

    const warningsBox = document.getElementById('warnings-box');
    const warningsList = document.getElementById('warnings-list');
    warningsList.innerHTML = '';

    if (data.warnings && data.warnings.length > 0) {
        warningsBox.classList.remove('hidden');
        data.warnings.forEach(w => {
            const li = document.createElement('li');
            li.textContent = w;
            warningsList.appendChild(li);
        });
    } else {
        warningsBox.classList.add('hidden');
    }

    renderPreviewTable(data.column_names, data.preview_rows);

    const refInput = document.getElementById('input-ref-period');
    if (refInput && data.recommended_reference_year) {
        refInput.value = data.recommended_reference_year;
    }
}

function renderPreviewTable(columns, rows) {
    const thead = document.getElementById('preview-thead');
    const tbody = document.getElementById('preview-tbody');
    thead.innerHTML = '';
    tbody.innerHTML = '';

    if (!columns || !rows) return;

    const trHead = document.createElement('tr');
    columns.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col;
        trHead.appendChild(th);
    });
    thead.appendChild(trHead);

    rows.forEach(row => {
        const tr = document.createElement('tr');
        columns.forEach(col => {
            const td = document.createElement('td');
            const val = row[col];
            td.textContent = (val !== null && val !== undefined) ? val : '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

// ---------------------------------------------------------
// 6. /query (자연어 자유 질문 분석)
// ---------------------------------------------------------
async function submitCustomQuery(question) {
    logConsole('QUERY', `자연어 질문 입력: "${question}"`, 'suggest');

    const resultCard = document.getElementById('query-result-card');
    const answerBody = document.getElementById('query-answer-body');
    const toolBadge = document.getElementById('query-tool-badge');

    resultCard.classList.remove('hidden');
    answerBody.innerHTML = '<p class="notice-banner">🤖 AI가 질문을 분석하고 적절한 파이썬 계산을 수행하고 있습니다...</p>';
    toolBadge.textContent = 'AI 도구 선택 및 계산 중...';

    try {
        const res = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '질문 분석 실패');

        logConsole('QUERY', `AI 답변 및 계산 완료 (도구: ${data.korean_tool_name})`, 'run');

        toolBadge.textContent = `실행 도구: ${data.korean_tool_name}`;
        answerBody.innerHTML = marked.parse(data.answer || '답변 없음');

        // 파이썬 계산 결과를 차트에 자동 시각화
        if (data.primary_result) {
            currentToolResult = data.primary_result;
            // AI 라우터가 추출한 파라미터 전체(n, target_name 등) 보존
            currentQueryParams = Object.assign({}, data.primary_params || {});
            if (data.primary_result.target_info && data.primary_result.target_info.name) {
                currentQueryParams.target_name = data.primary_result.target_info.name;
            }

            document.getElementById('run-section').classList.remove('hidden');
            renderRunSummary(data.primary_result);
            renderChart(data.primary_result);
            
            const toolSelect = document.getElementById('select-active-tool');
            if (toolSelect && data.tool_used) {
                const actualTool = data.tool_used;
                let userOpt = toolSelect.querySelector('option[data-is-user-query="true"]');
                if (!userOpt) {
                    userOpt = document.createElement('option');
                    userOpt.setAttribute('data-is-user-query', 'true');
                    toolSelect.insertBefore(userOpt, toolSelect.firstChild);
                }
                userOpt.value = actualTool;
                const shortQ = question.length > 20 ? question.substring(0, 20) + "..." : question;
                userOpt.textContent = `🤖 유저요구도구: ${data.korean_tool_name} ("${shortQ}")`;
                toolSelect.value = actualTool;
                updatePeriodControls(actualTool);
            }
        }

    } catch (err) {
        logConsole('ERROR', `질문 분석 실패: ${err.message}`, 'error');
        alert(`질문 분석 실패: ${err.message}`);
    }
}

// ---------------------------------------------------------
// 7. /suggest (Gemini AI 도구 추천 제안)
// ---------------------------------------------------------
async function requestAISuggestions() {
    logConsole('SUGGEST', 'AI 도구 제안 요청 시작 (/suggest)', 'suggest');

    const suggestSection = document.getElementById('suggest-section');
    const grid = document.getElementById('suggestions-grid');
    grid.innerHTML = '<div class="notice-banner">🤖 Gemini AI가 데이터 진단 결과를 바탕으로 한글 최적 분석 도구를 선별하고 있습니다...</div>';
    suggestSection.classList.remove('hidden');

    try {
        const res = await fetch('/suggest', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '제안 실패');

        logConsole('SUGGEST', `AI 도구 제안 응답 수신 (제안 개수: ${data.total_suggestions}개)`, 'suggest');
        renderSuggestionsGrid(data.suggestions);

        populateToolSelect(data.suggestions);
        document.getElementById('run-section').classList.remove('hidden');

    } catch (err) {
        logConsole('ERROR', `AI 제안 실패: ${err.message}`, 'error');
        alert(`AI 제안 실패: ${err.message}`);
    }
}

function renderSuggestionsGrid(suggestions) {
    const grid = document.getElementById('suggestions-grid');
    grid.innerHTML = '';

    if (!suggestions || suggestions.length === 0) {
        grid.innerHTML = '<p>추천된 도구가 없습니다.</p>';
        return;
    }

    suggestions.forEach(s => {
        const card = document.createElement('div');
        card.className = 'suggestion-card';

        const paramsStr = JSON.stringify(s.params || {});
        const koreanTitle = getToolDisplayName(s.tool);

        card.innerHTML = `
            <div>
                <h3>🔧 ${koreanTitle}</h3>
                <p class="why-text"><strong>추천 이유:</strong> ${s.why || ''}</p>
                <div class="caution-text">⚠️ <strong>주의:</strong> ${s.caution || ''}</div>
            </div>
            <button class="btn primary-btn btn-select-suggestion" data-tool="${s.tool}" data-params='${paramsStr}'>
                ▶ 이 분석 실행하기
            </button>
        `;
        grid.appendChild(card);
    });

    document.querySelectorAll('.btn-select-suggestion').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const tool = e.currentTarget.getAttribute('data-tool');
            const params = JSON.parse(e.currentTarget.getAttribute('data-params')) || {};
            
            currentQueryParams = Object.assign({}, params);
            
            const toolSelect = document.getElementById('select-active-tool');
            if (toolSelect) toolSelect.value = tool;
            
            updatePeriodControls(tool);

            executeToolWithParams(tool, params);
        });
    });
}

function populateToolSelect(suggestions) {
    const select = document.getElementById('select-active-tool');
    select.innerHTML = '';

    const allTools = [
        "top_bottom_n", "trend_line", "group_summary", "describe_numeric",
        "change_rate", "distribution", "correlation_scatter", "compare_one_vs_all",
        "reshape_wide_to_long", "quality_report", "year_coverage", "detect_aggregates"
    ];

    allTools.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = getToolDisplayName(t);
        select.appendChild(opt);
    });
}

const TWO_POINT_TOOLS = ['change_rate', 'correlation_scatter', 'trend_line', 'custom_dynamic_query'];

function updatePeriodControls(toolName) {
    const singleGroup = document.getElementById('group-single-period');
    const twoGroup = document.getElementById('group-two-period');
    if (!singleGroup || !twoGroup) return;

    const isTwoPoint = ['change_rate', 'correlation_scatter', 'trend_line'].includes(toolName) || 
                       (toolName === 'custom_dynamic_query' && (currentQueryParams.start_period || currentQueryParams.start_year));

    if (isTwoPoint) {
        singleGroup.classList.add('hidden');
        twoGroup.classList.remove('hidden');

        const sInput = document.getElementById('input-start-period');
        const eInput = document.getElementById('input-end-period');

        if (sInput) sInput.value = currentQueryParams.start_period || currentQueryParams.start_year || currentQueryParams.x_col || '2010';
        if (eInput) eInput.value = currentQueryParams.end_period || currentQueryParams.end_year || currentQueryParams.y_col || currentQueryParams.reference_period || '2024';
    } else {
        twoGroup.classList.add('hidden');
        singleGroup.classList.remove('hidden');

        const refInput = document.getElementById('input-ref-period');
        if (refInput) refInput.value = currentQueryParams.reference_period || '2024';
    }
}

function onToolSelectChange() {
    const select = document.getElementById('select-active-tool');
    const selectedOpt = select ? select.selectedOptions[0] : null;
    if (selectedOpt && !selectedOpt.hasAttribute('data-is-user-query')) {
        currentQueryParams = {};
    }
    const tool = select ? select.value : '';
    updatePeriodControls(tool);
    logConsole('RUN', `도구 선택 변경: ${getToolDisplayName(tool)}`, 'run');
}

// ---------------------------------------------------------
// 8. /run (Pandas 수치 연산 및 Chart.js 시각화)
// ---------------------------------------------------------
async function executeSelectedTool() {
    const toolSelect = document.getElementById('select-active-tool');
    const tool = toolSelect ? toolSelect.value : '';
    const excludeAgg = document.getElementById('check-exclude-agg').checked;

    let params = Object.assign({}, currentQueryParams, { exclude_aggregates: excludeAgg });

    const twoGroup = document.getElementById('group-two-period');
    const isTwoGroupVisible = twoGroup && !twoGroup.classList.contains('hidden');

    if (isTwoGroupVisible || (TWO_POINT_TOOLS.includes(tool) && tool !== 'custom_dynamic_query')) {
        const startPeriod = document.getElementById('input-start-period').value.trim() || '2010';
        const endPeriod = document.getElementById('input-end-period').value.trim() || '2024';
        
        params.start_period = startPeriod;
        params.end_period = endPeriod;
        params.start_year = startPeriod;
        params.end_year = endPeriod;
        params.x_col = startPeriod;
        params.y_col = endPeriod;
        params.reference_period = endPeriod;
    } else {
        const refPeriod = document.getElementById('input-ref-period').value.trim() || '2024';
        params.reference_period = refPeriod;
    }

    executeToolWithParams(tool, params);
}

async function executeToolWithParams(tool, params) {
    const koreanName = getToolDisplayName(tool);
    logConsole('RUN', `도구 실행 시작: ${koreanName} (기준시점: ${params.reference_period || 'N/A'})`, 'run');

    const errorBox = document.getElementById('run-error-box');

    try {
        const res = await fetch('/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool, params })
        });

        const data = await res.json();

        if (!res.ok) {
            logConsole('ERROR', `도구 실행 실패: ${data.error || '알 수 없는 오류'}`, 'error');
            
            if (errorBox) {
                errorBox.classList.remove('hidden');
                document.getElementById('run-error-message').textContent = data.error || '도구 실행에 실패했습니다.';
                document.getElementById('run-error-reason').textContent = `❓ 발생 원인: ${data.reason || '입력 파라미터 조건이 맞지 않습니다.'}`;
                document.getElementById('run-error-suggestion').innerHTML = `💡 <strong>조치 가이드:</strong> ${data.suggestion || '기준 시점 연도를 변경하거나 대상 항목을 확인해 보세요.'}`;
                
                document.getElementById('run-meta-summary').classList.add('hidden');
                if (currentChart) {
                    currentChart.destroy();
                    currentChart = null;
                }
            } else {
                alert(`도구 실행 실패: ${data.error}\n원인: ${data.reason}\n조치: ${data.suggestion}`);
            }
            return;
        }

        if (errorBox) errorBox.classList.add('hidden');
        currentToolResult = data;
        logConsole('RUN', `도구 실행 성공 (사용 행: ${data.rows_used}, 제외 행: ${data.rows_excluded})`, 'run');

        renderRunSummary(data);
        renderChart(data);

    } catch (err) {
        logConsole('ERROR', `통신/도구 오류: ${err.message}`, 'error');
        if (errorBox) {
            errorBox.classList.remove('hidden');
            document.getElementById('run-error-message').textContent = '도구 실행 처리 중 네트워크 또는 서버 예외가 발생했습니다.';
            document.getElementById('run-error-reason').textContent = `❓ 원인: ${err.message}`;
            document.getElementById('run-error-suggestion').textContent = '💡 서버 상태 및 입력값을 확인 후 다시 시도해 주세요.';
        }
    }
}

function renderRunSummary(data) {
    const summaryDiv = document.getElementById('run-meta-summary');
    summaryDiv.classList.remove('hidden');

    document.getElementById('run-rows-used').textContent = data.rows_used;
    document.getElementById('run-rows-excluded').textContent = data.rows_excluded;
    document.getElementById('run-exclusion-reasons').textContent = (data.exclusion_reasons || []).join(', ') || '없음';
}

// ---------------------------------------------------------
// 9. Chart.js 캔버스 시각화 렌더링
// ---------------------------------------------------------
function renderChart(payload) {
    const canvas = document.getElementById('insight-chart');
    if (!canvas) return;

    if (currentChart) {
        currentChart.destroy();
    }

    const res = payload.result || {};
    const chartType = res.chart_type || 'bar';

    let config = {
        type: 'bar',
        data: { labels: [], datasets: [] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#f8fafc' } }
            },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } }
            }
        }
    };

    if (chartType === 'line') {
        config.type = 'line';
        config.data.labels = res.labels || [];
        config.data.datasets = (res.datasets || []).map((ds, idx) => ({
            label: ds.label,
            data: ds.data,
            borderColor: getPaletteColor(idx),
            backgroundColor: getPaletteColor(idx, 0.2),
            tension: 0.2
        }));

    } else if (chartType === 'histogram') {
        config.type = 'bar';
        config.data.labels = res.bin_labels || [];
        config.data.datasets = [{
            label: '항목 수 (빈도)',
            data: res.counts || [],
            backgroundColor: 'rgba(99, 102, 241, 0.7)',
            borderColor: '#6366f1',
            borderWidth: 1
        }];

    } else if (chartType === 'scatter') {
        config.type = 'scatter';
        config.data.datasets = [{
            label: `상관계수: ${res.correlation_coefficient}`,
            data: (res.scatter_data || []).map(p => ({ x: p.x, y: p.y })),
            backgroundColor: 'rgba(56, 189, 248, 0.7)'
        }];
        config.options.scales.x.title = { display: true, text: res.x_axis_label, color: '#38bdf8' };
        config.options.scales.y.title = { display: true, text: res.y_axis_label, color: '#38bdf8' };

    } else {
        config.type = 'bar';
        if (res.datasets && res.datasets.length > 0) {
            config.data.labels = res.labels || [];
            config.data.datasets = res.datasets.map((ds, idx) => ({
                label: ds.label,
                data: ds.data,
                backgroundColor: getPaletteColor(idx, 0.7),
                borderColor: getPaletteColor(idx, 1.0),
                borderWidth: 1
            }));
        } else if (res.top_chart) {
            const labels = res.top_chart.labels || [];
            const values = res.top_chart.values || [];
            const bgColors = labels.map(l => (l.includes('📍') || l.includes('대상') || l.includes('Korea')) ? 'rgba(234, 179, 8, 0.95)' : 'rgba(56, 189, 248, 0.7)');
            const borderColors = labels.map(l => (l.includes('📍') || l.includes('대상') || l.includes('Korea')) ? '#eab308' : '#38bdf8');

            config.data.labels = labels;
            config.data.datasets = [{
                label: payload.description || `상위 항목 비교`,
                data: values,
                backgroundColor: bgColors,
                borderColor: borderColors,
                borderWidth: 1
            }];
        } else {
            const labels = res.labels || [];
            const values = res.values || [];
            const bgColors = labels.map(l => (l.includes('📍') || l.includes('대상') || l.includes('Korea')) ? 'rgba(234, 179, 8, 0.95)' : 'rgba(168, 85, 247, 0.7)');
            const borderColors = labels.map(l => (l.includes('📍') || l.includes('대상') || l.includes('Korea')) ? '#eab308' : '#a855f7');

            config.data.labels = labels;
            config.data.datasets = [{
                label: payload.description || '수치 결과',
                data: values,
                backgroundColor: bgColors,
                borderColor: borderColors,
                borderWidth: 1
            }];
        }
    }

    currentChart = new Chart(canvas, config);
    logConsole('CHART', `차트 렌더 완료 (타입: ${config.type})`, 'chart');
}

function getPaletteColor(index, alpha = 1.0) {
    const colors = [
        `rgba(56, 189, 248, ${alpha})`,
        `rgba(168, 85, 247, ${alpha})`,
        `rgba(34, 197, 94, ${alpha})`,
        `rgba(245, 158, 11, ${alpha})`,
        `rgba(244, 63, 94, ${alpha})`
    ];
    return colors[index % colors.length];
}

// ---------------------------------------------------------
// 10. /explain (Gemini AI 보고서 생성 모드 A/B)
// ---------------------------------------------------------
async function requestAIExplanation(mode) {
    logConsole('EXPLAIN', `AI 해석 보고서 요청 시작 (모드=${mode})`, 'explain');

    const explainSection = document.getElementById('explain-section');
    const explainOutput = document.getElementById('explain-output');
    const modeBadge = document.getElementById('explain-mode-badge');

    explainOutput.innerHTML = '<p class="notice-banner">🤖 Gemini AI가 규격화된 인사이트 보고서를 작성 중입니다...</p>';
    modeBadge.textContent = mode === 'A' ? '모드 A (허술한 비교용)' : '모드 B (정식 규격 보고서)';
    explainSection.classList.remove('hidden');

    try {
        const res = await fetch('/explain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '보고서 생성 실패');

        currentMarkdownReport = data.explanation || '';
        logConsole('EXPLAIN', `AI 해석 보고서 수신 완료 (모드=${mode})`, 'explain');

        explainOutput.innerHTML = marked.parse(currentMarkdownReport);

    } catch (err) {
        logConsole('ERROR', `보고서 생성 실패: ${err.message}`, 'error');
        alert(`보고서 생성 실패: ${err.message}`);
    }
}

// ---------------------------------------------------------
// 11. 마크다운(.md) 보고서 파일 다운로드 기능
// ---------------------------------------------------------
function downloadMarkdownReport() {
    if (!currentMarkdownReport) {
        alert('다운로드할 마크다운 보고서 내용이 없습니다.');
        return;
    }

    const filename = currentDiagnosis ? currentDiagnosis.filename : 'data';
    const baseName = filename.replace(/\.[^/.]+$/, "");
    const downloadFileName = `${baseName}_insight_report.md`;

    const blob = new Blob([currentMarkdownReport], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadFileName;
    document.body.appendChild(a);
    a.click();
    
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    logConsole('DOWNLOAD', `마크다운 보고서 파일 다운로드 완료: ${downloadFileName}`, 'explain');
}
