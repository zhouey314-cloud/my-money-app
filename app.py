import streamlit as st
import pandas as pd
import openai
import json
import os
from datetime import datetime

# ================= 配置区域 =================
# 页面基础设置
st.set_page_config(page_title="语音记账", page_icon="💰", layout="centered")
DATA_FILE = "my_expenses.csv"

# ================= 核心逻辑 =================
def get_ai_response(text, api_key, base_url, model_name):
    # 初始化客户端
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    
    prompt = f"""
    你是一个记账助手。请分析文本，提取以下信息并返回严格的 JSON：
    1. item: 商品名
    2. amount: 金额(数字)
    3. category: 类别(餐饮/交通/购物/居住/娱乐/医疗/其他)
    4. currency: 币种(默认CNY)
    
    用户输入: "{text}"
    只返回JSON，不要Markdown格式。
    """
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        content = response.choices[0].message.content
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        st.error(f"AI 报错: {e}")
        return None

def save_to_csv(data):
    data['date'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    df_new = pd.DataFrame([data])
    if os.path.exists(DATA_FILE):
        df_old = pd.read_csv(DATA_FILE)
        df_final = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_final = df_new
        
    df_final.to_csv(DATA_FILE, index=False)
    return df_final

# ================= 界面 UI =================
st.title("💰 智能语音记账")

with st.sidebar:
    st.header("⚙️ 第一步：填入密钥")
    # 这里默认填好了 DeepSeek 的地址，你可以改
    api_key = st.text_input("API Key", type="password", placeholder="sk-...")
    base_url = st.text_input("API 地址 (Base URL)", value="https://api.deepseek.com")
    model_name = st.text_input("模型名称", value="deepseek-chat")
    st.caption("推荐去 deepseek.com 申请 API Key，便宜又好用")

st.info("💡 手机访问时，点击输入框键盘上的【麦克风】直接说话")
user_input = st.text_area("输入花销 (例如: 打车花了30元)", height=80)

if st.button("🚀 记账", use_container_width=True):
    if not api_key:
        st.warning("请在左侧侧边栏填入 API Key")
    elif not user_input:
        st.warning("请先输入内容")
    else:
        with st.spinner("正在分析..."):
            res = get_ai_response(user_input, api_key, base_url, model_name)
            if res:
                save_to_csv(res)
                st.success(f"已记录: {res['item']} - {res['amount']}元")
                st.rerun()

st.divider()
st.subheader("📊 账本")
if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE).sort_values(by="date", ascending=False)
    st.dataframe(df, use_container_width=True)
    # 统计图
    st.bar_chart(df.groupby("category")["amount"].sum())