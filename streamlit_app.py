import streamlit as st, json, gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
from openai import OpenAI
import base64

# API 및 클라이언트 설정
apikey = st.secrets["openai"]["api_key"]
client = OpenAI(api_key=apikey)

# ── 기본 설정 ──
st.set_page_config(page_title="수학 문제 피드백 시스템", page_icon="🧮", layout="centered")

@st.cache_resource
def connect_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        json.loads(st.secrets["google_sheets"]["service_account"]), scope
    )
    client = gspread.authorize(creds)
    book = client.open_by_key(st.secrets["google_sheets"]["sheet_id"])
    return {
        "survey":     book.worksheet("survey"),
        "answers":    book.worksheet("answers"),
        "prompt":     book.worksheet("prompt"),
        "questions":  book.worksheet("questions"),
    }

# 시트 연결
ws = connect_sheet()

# ── 프롬프트 시트 읽기 ───────────────────────────────
def get_prompts():
    system_prompt = ws["prompt"].acell("B1").value
    user_prompt   = ws["prompt"].acell("B2").value
    return system_prompt, user_prompt

# ── 활성화된 문제 1개 불러오기 ──────────────────────
def get_active_question():
    import pandas as pd
    df = pd.DataFrame(ws["questions"].get_all_records())
    df_active = df[df["active"] == "TRUE"]
    if df_active.empty:
        return None, None, None, None
    row = df_active.iloc[0]
    return row["문제"], row["채점기준"], row["모범답안"], row["정답"]

@st.cache_data(show_spinner=False)
def analyze_image_with_gpt(base64_image: str, mime: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "이미지는 학생의 수학 서술형 답안입니다."},
            {"role": "user", "content": [
                {"type": "text", "text": (
                    "학생의 수학 서술형 풀이를 설명해주세요. "
                    "수식은 latex로 변환하여 작성하고, 한글 보이는 부분은 그대로 적어주세요. "
                    "교사 시점에서 채점하기 쉬운 설명을 해주세요."
                )},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64_image}"}}
            ]}
        ]
    )
    return response.choices[0].message.content.strip()

# ── 세션 상태 초기화 ─────────────────────────
for k, v in {"logged_in": False, "sid": None, "page": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 로그인 처리 ───────────────────────────────
if not st.session_state["logged_in"]:
    st.title("🧮 수학 문제 피드백 시스템")
    with st.form("login", clear_on_submit=True):
        sid = st.text_input("학번")
        pw  = st.text_input("비밀번호", type="password")
        ok  = st.form_submit_button("로그인", type="primary")
    if ok and sid and pw == "1234":
        st.session_state.update({"logged_in": True, "sid": sid, "page": None})
        st.rerun()
    else:
        st.error("아이디 혹은 비밀번호를 확인해주세요.")
    st.stop()

# ── 로그아웃 버튼 ────────────────────────────
def logout():
    for k in ["logged_in", "sid", "page"]:
        st.session_state[k] = False if k == "logged_in" else None
    st.rerun()

# ── 상단 메뉴/로그아웃 ─────────────────────────
_, col_home, col_logout = st.columns([0.5, 0.25, 0.25], gap="small")
if col_home.button("🏠 홈", use_container_width=True, key="btn_home"):
    st.session_state["page"] = None
    st.rerun()
if col_logout.button("🔒 로그아웃", use_container_width=True, key="btn_logout"):
    logout()

# 스타일링
st.markdown(
    """
    <style>
    button[data-testid="btn_home"], button[data-testid="btn_logout"] {
        color: white !important;
        border: none !important;
    }
    button[data-testid="btn_home"] { background: #2b83ba !important; }
    button[data-testid="btn_logout"] { background: #0074c2 !important; }
    button[data-testid="btn_home"]:hover, button[data-testid="btn_logout"]:hover {
        opacity: 0.9; cursor: pointer;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── 메뉴 화면 (문제 해결으로 바로 이동) ─────────────────
if st.session_state["page"] is None:
    st.success(f"{st.session_state['sid']}님, 문제 해결 페이지로 이동합니다.")
    if st.button("🔎 문제 해결", use_container_width=True, key="btn_solve"):
        st.session_state["page"] = "solve"
        st.rerun()
    st.stop()

# ── 페이지: 문제 해결 ───────────────────────────
if st.session_state["page"] == "solve":
    st.header("🔎 문제 해결")

    # 시트에서 문제 불러오기
    question_text, rubric, model_answer, correct_answer = get_active_question()
    if not question_text:
        st.warning("활성화된 문제가 없습니다.")
        st.stop()

    st.markdown("#### 📘 현재 문제")
    st.markdown(question_text)
    st.divider()

    # 이미지 업로드 및 해석
    img_up = st.file_uploader("풀이 이미지 (선택)", type=["jpg","jpeg","png"])
    image_analysis = ""
    if img_up:
        img = Image.open(img_up)
        st.image(img, caption=f"{img_up.name} | {img.size}px | {img_up.type}")
        with st.spinner("이미지 해석 중..."):
            try:
                b64 = base64.b64encode(img_up.getvalue()).decode()
                mime = img_up.type or "image/png"
                image_analysis = analyze_image_with_gpt(b64, mime)
                st.markdown("#### 🧠 이미지 해석 결과:")
                st.success(image_analysis)
            except Exception as e:
                st.error(f"이미지 해석 중 오류 발생: {e}")

    # 텍스트 풀이 입력
    text_ans = st.text_area("텍스트 풀이 입력", height=180)

    # 피드백 요청
    col1, col2 = st.columns(2)
    p_first, p_blank = get_prompts()
    combined_input = f"이미지 해석 결과:\n{image_analysis}\n\n텍스트 풀이:\n{text_ans.strip()}"
    prompt = (p_first if text_ans.strip() else p_blank or "").format(
        question="수학 서술형 문제", answer=combined_input
    )

    with col1:
        if st.button("피드백 받기", use_container_width=True):
            try:
                img_block = []
                if img_up:
                    mime = img_up.type or "image/png"
                    b64 = base64.b64encode(img_up.getvalue()).decode()
                    img_block = [{"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}}]
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role":"developer","content":prompt},
                        {"role":"user","content":[{"type":"text","text":combined_input}]+img_block},
                    ], max_tokens=300,
                )
                feedback = response.choices[0].message.content.strip().split("\n\n")[0]
                if img_up: st.caption("✅ Vision API 정보 포함")
                st.info(feedback)
                ws["answers"].append_row([
                    datetime.now().isoformat(), st.session_state["sid"],
                    "피드백(이미지)" if img_up else "피드백",
                    text_ans.replace("\n", " "), feedback
                ], value_input_option="USER_ENTERED")
            except Exception as e:
                st.error(f"GPT 피드백 요청 오류: {e}")

    with col2:
        if st.button("도움 요청 (힌트)", use_container_width=True):
            hint_prompt = f"{p_blank}\n문제: {question_text}"
            hint = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role":"user","content":hint_prompt}],
                max_tokens=100
            ).choices[0].message.content.strip()
            st.info(hint)
            ws["answers"].append_row([
                datetime.now().isoformat(), st.session_state["sid"],
                "힌트", "", hint
            ], value_input_option="USER_ENTERED")

    if st.button("최종 제출", type="primary", use_container_width=True):
        ws["answers"].append_row([
            datetime.now().isoformat(), st.session_state["sid"],
            "최종제출", text_ans.replace("\n", " "), ""
        ], value_input_option="USER_ENTERED")
        st.success("답안이 제출되었습니다.")
