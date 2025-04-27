import streamlit as st
import pypyodbc as podbc
import pandas as pd
import time
from groq import Groq
import re

# Initialize Groq client
client = Groq(api_key="your token")

# Set Streamlit layout to wide
st.set_page_config(layout="wide")

# Custom CSS for styling
st.markdown("""
<style>
    .stTextInput input {border-radius: 10px;}
    .stButton button {border-radius: 10px; background: #4CAF50; color: white;}
    .reportview-container {background: #f0f2f6;}
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    h1 {
        text-align: center;
        font-size: 2.5rem;
        color: #4CAF50;
        margin-bottom: 4rem;
    }
</style>
""", unsafe_allow_html=True)

# Database connection management
def get_connection():
    if 'db_connection' not in st.session_state:
        raise Exception("Not connected to database")
    return st.session_state.db_connection

# Sidebar for connection
with st.sidebar:
    st.title("Database Configuration ")
    
    with st.form("connection_form"):
        server = st.text_input("Server", "localhost")
        database = st.text_input("Database", "Empoyees")
        auth_type = st.radio("Authentication", ["Windows Auth", "SQL Server Auth"])
        username = st.text_input("Username")
        password = st.text_input("Password",type="password")
        
        if st.form_submit_button("Connect"):
            try:
                conn_str = (
                    f"Driver={{ODBC Driver 17 for SQL Server}};"
                    f"Server={server};"
                    f"Database={database};"
                )
                conn_str += "Trusted_Connection=yes;" if auth_type == "Windows Auth" else f"UID={username};PWD={password};"
                conn = podbc.connect(conn_str)
                st.session_state.db_connection = conn
                st.success("Connected successfully!")

                cursor = conn.cursor()
                cursor.execute("""
                    SELECT TABLE_SCHEMA, TABLE_NAME 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_TYPE = 'BASE TABLE'
                """)
                st.session_state.tables = cursor.fetchall()
                st.session_state.schemas = list(set([t[0] for t in st.session_state.tables]))

            except Exception as e:
                st.error(f"Connection failed: {str(e)}")

    if 'schemas' in st.session_state:
        selected_schema = st.selectbox("Schema", st.session_state.schemas)
        schema_tables = [t[1] for t in st.session_state.tables if t[0] == selected_schema]
       # selected_table = st.selectbox("Table", schema_tables)
       # st.session_state.selected_table = (selected_schema, selected_table)

# Initialize chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    st.session_state.chat_history.append({
        "role": "assistant",
        "content": " How can I help you with your database today?"
    })

# Chat display
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
user_input = st.chat_input("Type your message here...")

# Helper Functions
def extract_metadata(schema):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = '{schema}'
        """)
        rows = cursor.fetchall()
        metadata = {}
        for table_name, column_name, data_type in rows:
            full_col = f"[{schema}].[{table_name}].[{column_name}]"
            metadata[full_col] = data_type
        return metadata
    except Exception as e:
        st.error(f"Metadata extraction failed: {str(e)}")
        return None


def generate_sql(question, metadata):
    prompt = f"""
    You are a senior SQL developer working with Microsoft SQL Server (T-SQL).
    for the question: {question}
    Use T-SQL syntax :\n
    for this Schema {metadata}
    Only include columns that are **relevant** to the question — do NOT include all columns.
    Include TOP instead of LIMIT.
    Ensure all SELECT columns are aliased with table name, e.g., `p.name AS product_name`.
    Convert money fields using CAST() when needed.
    """
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a SQL expert."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.3
        )
        return re.findall(r"SELECT.*?;", response.choices[0].message.content, re.DOTALL | re.IGNORECASE)[0]
    except Exception as e:
        st.error(f"Query generation failed: {str(e)}")
        return None

def execute_query(query):
    try:
        conn = get_connection()
        return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Query execution failed: {str(e)}")
        return None

def explain_results(question, df):
    prompt = f"""
    Answer this question: {question}
    Based on this data: {df.to_csv(index=False)}
    Use clear language and highlight key insights.
    """
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a data analyst."},
                {"role": "user", "content": prompt}
            ],
            model="deepseek-r1-distill-llama-70b",
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Explanation failed: {str(e)}")
        return None
    
def render_typing_effect(response_text):
    output_area = st.empty()
    typed = ""
    for char in response_text:
        typed += char
        output_area.markdown(typed)
        time.sleep(0.004)

# Handle user input
if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing your question..."):
            metadata = extract_metadata(selected_schema)
            if metadata:
                sql = generate_sql(user_input, metadata)
                if sql:
                    results = execute_query(sql)
                    explanation = explain_results(user_input, results) if results is not None else None

                    full_reply = f"Here’s your SQL:\n```sql\n{sql}\n```"
                    if results is not None:
                        st.dataframe(results)
                        full_reply += "\n\n" + explanation
                    render_typing_effect(full_reply)
                    st.session_state.chat_history.append({"role": "assistant", "content": full_reply})
                else:
                    error_msg = "Sorry, I couldn't generate a SQL query."
                    st.markdown(error_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})

# Centered title at bottom
st.markdown("<h1>Data Science SQL Agents </h1>", unsafe_allow_html=True)

# Help section
with st.expander(" Tips"):
    st.markdown("""
    **Example Questions:**
    - "Show me the top 5 most expensive products in Database"
    - "What is the average horsepower by manufacturer?"
    - "List Employesss sorted by thier salaries"

    **Tips:**
    - Use natural language
    - Be specific about what you're looking for
    - Mention columns or metrics if possible
    """)
