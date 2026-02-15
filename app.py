import streamlit as st
import vertexai
from vertexai.generative_models import GenerativeModel, Part, Tool, SafetySetting
import pandas as pd
import json
import os
import time
import datetime
from io import BytesIO
from dotenv import load_dotenv
from google.cloud import storage
from google.api_core import exceptions
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import warnings

# Suppress Deprecation Warnings (Vertex AI & Streamlit)
warnings.filterwarnings("ignore", category=UserWarning, module="vertexai")
warnings.filterwarnings("ignore", category=UserWarning, module="streamlit")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

# --- Configuration & Environment ---
load_dotenv()

st.set_page_config(
    page_title="捜査本部 (Receipt Deca Extended)",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Custom CSS (Light Theme for Readability)
st.markdown("""
<style>
    /* Global Background (Streamlit Default is white, but ensuring) */
    .stApp {
        background-color: #ffffff;
        color: #333333;
    }
    
    /* Sidebar */
    .stSidebar {
        background-color: #f0f2f6;
    }
    
    /* Headers - Maintaining Hard-Boiled Vibe but Readable */
    h1, h2, h3 {
        font-family: 'Courier New', Courier, monospace;
        color: #111111;
        font-weight: bold;
    }
    
    /* Buttons - Keep Red for GUILTY vibe but cleaner */
    .stButton>button {
        color: #ffffff;
        background-color: #d32f2f;
        border: 2px solid #b71c1c;
        font-weight: bold;
    }
    
    /* Text Area - White background, black text */
    .stTextArea textarea {
        background-color: #ffffff;
        color: #333333;
        border: 1px solid #ccc;
    }
    
    /* Alerts - Softer colors for readability */
    .stAlert {
        padding: 10px;
        border-radius: 5px;
    }
    
    /* Card-like look for results */
    div[data-testid="stMetricValue"] {
        color: #000;
    }
</style>
""", unsafe_allow_html=True)

# --- Constants & State ---
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or "agentic-hackathon-v4"
GEMINI_LOCATION = "global" 

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "receipt-deca-history-agentic-hackathon-v4")
ANALYSIS_HISTORY_FILE = "analysis_history.json"
NOTE_HISTORY_FILE = "note_history.json"

MAX_ANALYSIS_HISTORY = 20
MAX_NOTE_HISTORY = 10

# Initialize Session State
if 'results' not in st.session_state:
    st.session_state.results = None
if 'advice' not in st.session_state:
    st.session_state.advice = None

# --- Sidebar Configuration ---
st.sidebar.title("🕵️ 捜査設定")

# Production Configuration (Hidden)
user_project_id = PROJECT_ID
user_location = GEMINI_LOCATION

# Debug mode renamed for production vibe
debug_mode = st.sidebar.checkbox("詳細捜査ログを表示", value=False)

# Initialize Vertex AI
if user_project_id:
    try:
        vertexai.init(project=user_project_id, location=user_location)
        if debug_mode: st.sidebar.success("通信確立 (Vertex AI Initialized)")
    except Exception as e:
        st.sidebar.error(f"通信エラー: {e}")

# --- Helper Functions: GCS & Persistence (Unchanged) ---

def get_gcs_blob(filename):
    """Get GCS blob object."""
    if not user_project_id:
        return None
    try:
        client = storage.Client(project=user_project_id)
        bucket = client.bucket(BUCKET_NAME)
        return bucket.blob(filename)
    except Exception as e:
        if debug_mode: st.sidebar.error(f"GCS Connection Error: {e}")
        return None

def load_json_from_gcs(filename):
    """Load JSON data from GCS, returning empty list if not found or error."""
    blob = get_gcs_blob(filename)
    if not blob: return []
    
    try:
        if blob.exists():
            data = blob.download_as_text()
            return json.loads(data)
    except Exception as e:
        if debug_mode: st.sidebar.warning(f"Failed to load {filename}: {e}")
    return []

@retry(
    stop=stop_after_attempt(5), 
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(exceptions.PreconditionFailed)
)
def save_json_to_gcs_with_retry(filename, new_record, max_items):
    """
    Save record to GCS with Optimistic Locking (if_generation_match).
    Retries on PreconditionFailed (412).
    """
    blob = get_gcs_blob(filename)
    if not blob: return

    current_data = []
    generation = None
    
    try:
        blob.reload()
        if blob.exists():
            current_data = json.loads(blob.download_as_text())
            generation = blob.generation
        else:
            generation = 0 
    except exceptions.NotFound:
        generation = 0
    except Exception as e:
        if debug_mode: st.sidebar.error(f"Error reading for save: {e}")
        pass

    current_data.append(new_record)
    updated_data = current_data[-max_items:]

    try:
        blob.upload_from_string(
            json.dumps(updated_data, ensure_ascii=False, indent=2),
            content_type="application/json",
            if_generation_match=generation
        )
    except exceptions.PreconditionFailed:
        if debug_mode: st.sidebar.warning("Collision detected (412), retrying...")
        raise 
    except Exception as e:
        st.error(f"Save failed: {e}")

def save_analysis_record(items, daily_note, advice_summary):
    """Save full analysis record."""
    record = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "daily_note": daily_note,
        "advice_summary": advice_summary
    }
    save_json_to_gcs_with_retry(ANALYSIS_HISTORY_FILE, record, MAX_ANALYSIS_HISTORY)

def save_note_record(daily_note):
    """Save simple note record."""
    if not daily_note: return
    record = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "daily_note": daily_note
    }
    save_json_to_gcs_with_retry(NOTE_HISTORY_FILE, record, MAX_NOTE_HISTORY)

# --- Common AI Helpers ---

def clean_json_string(text):
    """Clean markdown code blocks from string to get raw JSON."""
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    return text.strip()

# --- Multi-Agent System Architecture ---

class AgentBase:
    """Base class for all agents."""
    def __init__(self, model_name="gemini-2.5-pro"):
        self.model = GenerativeModel(model_name)

    def execute(self, context):
        raise NotImplementedError

class HealthAdvisorAgent(AgentBase):
    """Specialist for health risks, fatigue, and lifestyle."""
    def execute(self, context):
        prompt = f"""
        あなたは「健康管理顧問 (Health Advisor)」だ。
        提供された情報から、体調不良の兆候、栄養過不足、生活リズムの乱れを分析せよ。
        
        【コンテキスト】
        {context}
        
        出力形式 (JSONのみ):
        ```json
        {{
            "health_risk_assessment": "...",
            "improvement_suggestion": "..."
        }}
        ```
        深刻なリスクがない場合は、"health_risk_assessment": "特になし" とせよ。
        """
        try:
            response = self.model.generate_content(prompt)
            return json.loads(clean_json_string(response.text))
        except Exception:
            return {"health_risk_assessment": "", "improvement_suggestion": ""}

class FitnessAgent(AgentBase):
    """Specialist for body composition, training, and PFC balance."""
    def execute(self, context):
        prompt = f"""
        あなたは「肉体改造トレーナー (Fitness Coach)」だ。
        提供された情報から、筋肉合成、ダイエット効率、PFCバランス、トレーニング観点で分析せよ。
        
        【コンテキスト】
        {context}
        
        出力形式 (JSONのみ):
        ```json
        {{
            "body_composition_assessment": "...",
            "training_nutrition_suggestion": "..."
        }}
        ```
        関連性が低い場合は空文字を返せ。
        """
        try:
            response = self.model.generate_content(prompt)
            return json.loads(clean_json_string(response.text))
        except Exception:
            return {"body_composition_assessment": "", "training_nutrition_suggestion": ""}

class AdviceOrchestrator(AgentBase):
    """Main Agent: Routes tasks and synthesizes final advice."""
    
    def __init__(self):
        super().__init__()
        self.health_agent = HealthAdvisorAgent()
        self.fitness_agent = FitnessAgent()

    def route_agents(self, daily_note, current_items):
        """Decide which agents to call based on context."""
        prompt = f"""
        以下の情報に基づき、助言を求めるべき専門家を選定せよ。
        
        メモ: {daily_note}
        購入品: {str(current_items)}
        
        選択肢:
        - HEALTH: 体調不良、疲れ、病気、胃腸、生活習慣
        - FITNESS: ダイエット、筋肉、筋トレ、増量、減量、プロテイン
        
        出力 (JSON):
        ```json
        {{
            "call_health": true/false,
            "call_fitness": true/false
        }}
        ```
        """
        try:
            response = self.model.generate_content(prompt)
            return json.loads(clean_json_string(response.text))
        except:
            return {"call_health": True, "call_fitness": True} # Fallback: Call all

    def synthesize(self, context, health_res, fitness_res):
        """Synthesize final advice."""
        prompt = f"""
        あなたは「生活安全課のベテラン刑事 (Main Adviser)」だ。
        各専門家からの報告を統合し、最終的なアドバイスを作成せよ。
        
        【コンテキスト】
        {context}
        
        【専門家報告】
        - 健康顧問: {json.dumps(health_res, ensure_ascii=False)}
        - トレーナー: {json.dumps(fitness_res, ensure_ascii=False)}
        
        出力形式 (JSON):
        ```json
        {{
          "trend_analysis": "...",     // 全体的な傾向（衝動買いなど）
          "nutrition_comment": "...",  // 栄養バランス
          "spending_comment": "...",   // 節約・無駄遣い
          "health_advice": "...",      // 健康顧問の意見要約（なければ空文字）
          "fitness_advice": "...",     // トレーナーの意見要約（なければ空文字）
          "actionable_advice": "..."   // 次のアクション（刑事口調で）
        }}
        ```
        """
        try:
            response = self.model.generate_content(prompt)
            return json.loads(clean_json_string(response.text))
        except Exception as e:
            if debug_mode: st.error(f"Synthesis Error: {e}")
            return {}

    def run(self, daily_note, current_items, past_notes, past_analysis):
        # 1. Prepare Context
        context_str = f"""
        【今回の買い物】
        - メモ: {daily_note}
        - 購入品: {json.dumps(current_items, ensure_ascii=False)}
        【過去履歴】
        - メモ: {json.dumps(past_notes, ensure_ascii=False)}
        - 分析: {json.dumps(past_analysis, ensure_ascii=False)}
        """
        
        # 2. Routing
        routing = self.route_agents(daily_note, current_items)
        if debug_mode: st.sidebar.write("🤖 Agent Routing:", routing)
        
        # 3. Agent Execution
        health_res = {}
        fitness_res = {}
        
        if routing.get("call_health"):
            health_res = self.health_agent.execute(context_str)
        
        if routing.get("call_fitness"):
            fitness_res = self.fitness_agent.execute(context_str)
            
        # 4. Synthesis
        final_output = self.synthesize(context_str, health_res, fitness_res)
        return final_output

# Instantiate Orchestrator
orchestrator = AdviceOrchestrator()

# --- Existing Logic (OCR & Market Check) ---

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=20))
def analyze_receipt(image_bytes):
    """OCR: Parse receipt image to JSON using Gemini 2.5 Flash Image."""
    model = GenerativeModel("gemini-2.5-flash-image")
    
    prompt = """
    あなたは優秀な鑑識官だ。
    このレシート画像を分析し、購入された「品目名(item)」と「単価(price)」を抽出せよ。
    結果は以下のJSONフォーマットのみを出力すること。それ以外の文字は一切不要だ。
    ```json
    [{"item": "卵", "price": 250}, {"item": "牛乳", "price": 180}]
    ```
    注意:
    - 割引などは無視し、元の単価を抽出せよ。
    - 合計金額などは不要。個々の商品リストのみが必要だ。
    - OCRが不完全な場合は推測して補完せよ。
    """
    
    image_part = Part.from_data(data=image_bytes, mime_type="image/jpeg")
    
    try:
        response = model.generate_content([image_part, prompt])
        text = clean_json_string(response.text)
        return json.loads(text)
    except Exception as e:
        if debug_mode: st.error(f"解析エラー詳細: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=20))
def investigate_item(item, price):
    """Market Check: Grounding check and Reasoning using Gemini 2.5 Pro."""
    model = GenerativeModel("gemini-2.5-pro")
    
    # Dynamic Import for Google Search Tool
    GoogleSearch = None
    try:
        from vertexai.generative_models import GoogleSearch
        tools = [Tool(google_search=GoogleSearch())]
    except ImportError:
        try:
             # Fallback for older SDKs or different structures
             tools = [Tool.from_dict({"google_search": {}})]
        except:
             return "System Error: Google Search Tool not available."

    prompt = f"""
    対象品目: {item}
    購入価格: {price}円
    
    任務:
    1. Google検索を使用し、この品目の現在の一般的な日本のスーパーマーケットでの市場価格（底値〜平均価格）を調査せよ。
    2. 購入価格と市場価格を比較せよ。
    3. 判定基準:
       - 購入価格 > 市場価格 * 1.2 (20%以上高い) の場合 -> 「有罪」(GUILTY)
       - それ以外の場合 -> 「無罪」(INNOCENT)
    4. 出力:
       ハードボイルドな刑事として報告せよ。
       最後に必ず以下のJSON形式のデータを末尾に付加すること。
    
    ---REPORT_DATA---
    {{
        "item": "{item}",
        "purchase_price": {price},
        "market_price": "調査した価格範囲",
        "verdict": "GUILTY or INNOCENT",
        "comment": "刑事のコメント"
    }}
    """
    
    try:
        response = model.generate_content(prompt, tools=tools)
        # Handle multiple parts
        full_text = "".join([part.text for part in response.candidates[0].content.parts if part.text])
        return full_text
    except Exception as e:
        return f"捜査不能: {item} (Error: {e}) ---REPORT_DATA--- {{}}"

# --- Main Application Logic ---

st.title("🕵️ レシート刑事 (Receipt Deca Extended)")
st.caption("Enhanced Memory & Multi-Agent Advice System")

# 1. Input Section
uploaded_file = st.file_uploader("証拠（レシート画像）を提出しろ", type=["jpg", "jpeg", "png"])
daily_note = st.text_area("捜査資料（今日のメモ・体調・目的など）", placeholder="例: 今週は野菜中心にする。ちょっと疲れている。")

if uploaded_file and user_project_id:
    image_bytes = uploaded_file.getvalue()
    st.image(image_bytes, caption="提出された証拠物件", use_container_width=True)
    
    if st.button("捜査開始 (Analyze)"):
        with st.status("合同捜査本部による解析進行中...", expanded=True) as status:
            
            # Step 1: OCR Analysis
            status.write("🔍 鑑識班: 画像解析中...")
            raw_items = analyze_receipt(image_bytes)
            
            if not raw_items:
                status.update(label="捜査失敗: 画像から情報を読み取れませんでした。", state="error")
                st.stop()
            
            status.write(f"✅ 鑑識報告: {len(raw_items)} 点の品目を確認。")
            
            # Step 2: Save Note History (Immediately)
            if daily_note:
                status.write("💾 書記官: 捜査メモを記録中...")
                save_note_record(daily_note)

            # Step 3: Market Investigation (Loop)
            status.write("🚓 捜査員: 裏取り（市場価格調査）を開始...")
            st.session_state.results = []
            final_items_for_record = []
            
            progress_bar = st.progress(0)
            for i, item_data in enumerate(raw_items):
                item_name = item_data.get("item")
                item_price = item_data.get("price")
                
                if item_name and item_price:
                    # Rate limit handling
                    time.sleep(1.5)
                    
                    response_text = investigate_item(item_name, item_price)
                    
                    # Parse Result
                    display_text = response_text
                    json_data = {"item": item_name, "purchase_price": item_price, "verdict": "UNKNOWN"}
                    
                    if "---REPORT_DATA---" in response_text:
                        parts = response_text.split("---REPORT_DATA---")
                        display_text = parts[0].strip()
                        try:
                            parsed = json.loads(clean_json_string(parts[1]))
                            if parsed: json_data = parsed
                        except: pass
                    
                    st.session_state.results.append({
                        "display_text": display_text,
                        "data": json_data
                    })
                    final_items_for_record.append(json_data)
                
                progress_bar.progress((i + 1) / len(raw_items))
            
            # Step 4: Advice Generation (Multi-Agent)
            status.write("🧠 プロファイラー: 専門家チームを招集し、分析中...")
            
            past_notes = load_json_from_gcs(NOTE_HISTORY_FILE)
            past_analysis = load_json_from_gcs(ANALYSIS_HISTORY_FILE)
            
            # CALL ORCHESTRATOR
            advice_data = orchestrator.run(daily_note, final_items_for_record, past_notes, past_analysis)
            st.session_state.advice = advice_data

            # Step 5: Save Full Analysis Record
            status.write("📂 管理官: 最終報告書を保存中...")
            advice_summary = advice_data.get("actionable_advice", "") if advice_data else ""
            save_analysis_record(final_items_for_record, daily_note, advice_summary)
            
            status.update(label="捜査完了 (Investigation Complete)", state="complete")

# 2. Display Results
if st.session_state.results:
    st.divider()
    st.subheader("🕵️ 捜査経過")
    for res in st.session_state.results:
        d = res["data"]
        alert_func = st.error if d.get("verdict") == "GUILTY" else st.success
        alert_func(res["display_text"], icon="🚨" if d.get("verdict") == "GUILTY" else "✅")

# 3. Display Advice (Updated for Multi-Agent)
if st.session_state.advice:
    st.divider()
    st.subheader("🧠 総合プロファイル結果 (合同捜査会議)")
    
    ad = st.session_state.advice
    
    # Row 1: General & Action
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**📉 節約分析**\n\n{ad.get('spending_comment', '分析なし')}")
        st.info(f"**🥗 栄養分析**\n\n{ad.get('nutrition_comment', '分析なし')}")
    with col2:
        st.warning(f"**💥 衝動買い分析**\n\n{ad.get('trend_analysis', '分析なし')}")
        st.success(f"**✨ 最終的助言 (Next Action)**\n\n{ad.get('actionable_advice', '特になし')}")

    # Row 2: Specialist Opinions (if active)
    has_health = bool(ad.get("health_advice"))
    has_fitness = bool(ad.get("fitness_advice"))
    
    if has_health or has_fitness:
        st.divider()
        st.caption("専門家からの追加報告")
        s_col1, s_col2 = st.columns(2)
        
        with s_col1:
            if has_health:
                st.error(f"**🏥 保健顧問の所見**\n\n{ad.get('health_advice')}")
        
        with s_col2:
            if has_fitness:
                st.info(f"**💪 トレーナーの指導**\n\n{ad.get('fitness_advice')}")

# 4. Sidebar History Display
st.sidebar.divider()
st.sidebar.subheader("📂 過去の捜査資料")

tabs = st.sidebar.tabs(["📄 解析履歴", "📝 メモ履歴"])

with tabs[0]:
    hist_analysis = load_json_from_gcs(ANALYSIS_HISTORY_FILE)
    if hist_analysis:
        for rec in reversed(hist_analysis):
            ts = rec.get("timestamp", "-")
            note = rec.get("daily_note", "")[:20]
            if note: note = f"({note}...)"
            st.markdown(f"**{ts}** {note}")
            
            # Quick summary of items
            items_summary = ", ".join([i.get("item","") for i in rec.get("items", [])[:3]])
            st.caption(f"品目: {items_summary}...")
            st.divider()
    else:
        st.info("履歴なし")

with tabs[1]:
    hist_notes = load_json_from_gcs(NOTE_HISTORY_FILE)
    if hist_notes:
        for rec in reversed(hist_notes):
            st.text(f"{rec.get('timestamp')}\n{rec.get('daily_note')}")
            st.divider()
    else:
        st.info("メモなし")
