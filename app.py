import streamlit as st
import pandas as pd
import openai
from ledger import DuplicateExpense, InvalidExpense, load_ledger, parse_model_response, save_expense

# ================= 配置区域 =================
# 页面基础设置
DATA_FILE = "my_expenses.csv"

# ================= 核心逻辑 =================
def get_ai_response(text, api_key, base_url, model_name):
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
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        content = response.choices[0].message.content
        return parse_model_response(content)
    except Exception:
        # Provider exceptions may contain request details, endpoints or credentials.
        st.error("解析未通过或服务调用失败，本次未写入账本。请核对配置和返回格式。")
        return None

def save_to_csv(data, *, allow_duplicate=False):
    return pd.DataFrame(save_expense(data, DATA_FILE, allow_duplicate=allow_duplicate))

# ================= 界面 UI =================
def main():
    st.set_page_config(page_title="语音记账", page_icon="💰", layout="centered")
    st.title("💰 智能语音记账")
    st.caption("Legacy 本地实验：模型提取尚未完成人工准确性评测，请逐笔核对。")
    with st.sidebar:
        st.header("⚙️ 服务配置")
        api_key = st.text_input("API Key", type="password", placeholder="sk-...")
        base_url = st.text_input("API 地址 (Base URL)", value="https://api.deepseek.com")
        model_name = st.text_input("模型名称", value="deepseek-chat")
        st.caption("只有点击记账才调用你配置的服务；输入文本会发送给该服务。")
    st.info("💡 手机访问时，可使用键盘麦克风输入。此应用本身不转写音频。")
    user_input = st.text_area("输入花销 (例如: 打车花了30元)", height=80)
    allow_duplicate = st.checkbox("已人工核对：允许同一分钟内另一笔完全相同的明细", value=False)
    if st.button("🚀 记账", use_container_width=True):
        if not api_key or not user_input.strip():
            st.warning("请先填入配置和内容。")
        else:
            with st.spinner("正在分析..."):
                res = get_ai_response(user_input, api_key, base_url, model_name)
                if res is not None:
                    try:
                        save_to_csv(res, allow_duplicate=allow_duplicate)
                    except DuplicateExpense:
                        st.warning("同一分钟已有完全相同的明细，本次未重复写入。确有两笔时请先人工核对。")
                    except (InvalidExpense, OSError):
                        st.error("账本校验或安全写入失败，原文件已保留。请先检查或备份账本。")
                    else:
                        st.success("已记录。请核对下方明细的金额、币种和分类。")
                        st.rerun()
    st.divider()
    st.subheader("📊 账本")
    try:
        rows = load_ledger(DATA_FILE)
    except (InvalidExpense, OSError):
        st.error("账本格式异常，未覆盖原文件。请参考 README 的离线检查与恢复步骤。")
        return
    if rows:
        df = pd.DataFrame(rows).sort_values(by="date", ascending=False)
        st.dataframe(df, use_container_width=True)
        currency = st.selectbox("按币种查看分类统计（不同币种不相加）", sorted(df.currency.unique()))
        selected = df[df.currency == currency].copy()
        selected['amount'] = pd.to_numeric(selected['amount'])
        st.bar_chart(selected.groupby('category')['amount'].sum())


if __name__ == '__main__':
    main()
