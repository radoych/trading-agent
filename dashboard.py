import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px

# 1. Page Configuration
st.set_page_config(page_title="AI Trader Dashboard", layout="wide")

st.title("🚀 AI Trading Agent: Live Session")
st.markdown("---")

# 2. Sidebar for Controls
st.sidebar.header("Dashboard Settings")
if st.sidebar.button('🔄 Refresh Data'):
    st.rerun()

# 3. Load Data from logger.py output
LOG_FILE = "trade_logs.json"

def load_data():
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()
    with open(LOG_FILE, "r") as f:
        data = json.load(f)
    return pd.DataFrame(data)

df = load_data()

# 4. Main Dashboard Layout
if not df.empty:
    # Key Metrics (Top Row)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Trades", len(df))
    with col2:
        buy_count = len(df[df['action'] == 'BUY'])
        st.metric("Total Buys", buy_count)
    with col3:
        last_price = df['price'].iloc[-1]
        st.metric("Last Trade Price", f"${last_price:,.2f}")

    st.markdown("---")

    # Visualization and Table
    left_col, right_col = st.columns([2, 1])

    with left_col:
        st.subheader("📈 Trade History Visualization")
        # Creating a timeline of trades
        fig = px.scatter(df, x="timestamp", y="price", 
                         color="action", size_max=20,
                         title="Executed Trades over Time",
                         labels={"price": "Execution Price", "timestamp": "Time"},
                         color_discrete_map={"BUY": "#00FF00", "SELL": "#FF0000"})
        st.plotly_chart(fig, use_container_width=True)

    with right_col:
        st.subheader("📄 Recent Logs")
        # Display the most recent 10 trades
        st.dataframe(df.sort_values(by="timestamp", ascending=False).head(10), use_container_width=True)

    # Expanded Analysis
    with st.expander("See full reasoning for trades"):
        for index, row in df.iterrows():
            st.write(f"**{row['timestamp']} - {row['symbol']}**: {row.get('status', 'Completed')}")
            st.info(f"Reasoning: {row.get('reason', 'Manual override or test signal')}")

else:
    st.warning("No trade data found. Make sure your bot has executed at least one test_signal or live trade.")
    st.info("Check that 'trade_logs.json' exists in your directory.")