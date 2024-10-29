from flask import Flask, render_template, request, jsonify
from datetime import timedelta, datetime
import yfinance as yf
import pandas as pd
import json
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
import urllib.parse
import os
import psycopg2



app = Flask(__name__)

# Initialize LangChain components
stockanalysis_template = """You are tasked with gathering information for a stock analysis. Please provide the following details:

1. **Stock Name**:
2. **Corporate Action** (only options: Split, Buyback, Bonus):

If any of these details are missing, please ask the user to provide the necessary information.

Current Input:
{user_input}

Return the Response in JSON Format"""

rationales = {
    "BUYBACK": "Buybacks signal that the company believes its shares are undervalued, which can boost investor confidence and demand, potentially leading to an increase in share price.",
    "BONUS": "Issuing bonus shares increases the number of shares outstanding, which can make the stock more affordable and attractive to a broader range of investors, potentially boosting demand.",
    "SPLIT": "Stock splits make shares more affordable for investors by reducing the price per share while maintaining the company's market capitalization, often leading to increased liquidity and demand."
}



stock_info_prompt = PromptTemplate.from_template(stockanalysis_template)




def generate_analysis_prompt(df_head: str, corporate_action: str) -> str:
    """
    Generates a prompt for analyzing the impact of a corporate action on stock performance.

    Parameters:
    - df_head (str): A string representation of the DataFrame head.
    - corporate_action (str): The type of corporate action (Buyback, Bonus Shares, Split).

    Returns:
    - str: The formatted prompt for analysis.
    """
    # Prepare the rationale for the specified corporate action
    rationale_text = rationales.get(corporate_action, "No rationale available.")

    prompt = f"""
    You are working with a Pandas DataFrame in Python named `df`. This DataFrame contains stock performance data following the corporate action: {corporate_action}. The columns include:
    - `symbol`: The stock symbol
    - `announcement_date`: The date the corporate action was announced
    - `record_date`: The date the corporate action was recorded
    - `record_date_return`: The return on the record date
    - `3m`: The 3-month return after the corporate action
    - `6m`: The 6-month return after the corporate action
    - `1y`: The 1-year return after the corporate action
    - `3y`: The 3-year return after the corporate action

    This is the result of `print(df.head())`:

        {df_head}

    **Hypothesis:** Corporate actions such as Buybacks, Bonuses, and Splits tend to increase the share price in both the short term and long term.

    **Rationale for Corporate Action:**
    - **{corporate_action}:** {rationale_text}

    **Analysis Instructions:**
    1. **Explain the rationale and significance of the corporate action.**
    2. **Analyze the impact of this corporate action on the stock's performance, ignoring any `NaN` values.**
       - Discuss trends or patterns observed in the returns over different time periods (3 months, 6 months, 1 year, and 3 years).
       - Address the following:
         - Has this corporate action had a positive or negative impact on returns across these periods?
         - Is there a trend of increasing or decreasing returns over time?
         - Are there any notable insights on how this corporate action might influence long-term stock performance?

    **Conclusion:** Based on your analysis, state whether you support or refute the hypothesis regarding the impact of this corporate action on share prices in the short and long term.
    """
    
    return prompt.strip()



def is_valid_stock(symbol):
    try:
        stock = yf.Ticker(symbol)
        stock_info = stock.info
        return stock_info.get('exchange') in ['NSI']
    except Exception:
        return False

def calculate_returns(df):
    def get_next_price(stock_data, target_date, max_forward_days=5):
        target_date = pd.to_datetime(target_date).normalize()
        mask = (stock_data.index >= target_date) & (stock_data.index <= target_date + timedelta(days=max_forward_days))
        future_dates = stock_data.index[mask]
        
        if not future_dates.empty:
            next_date = future_dates[0]
            return stock_data.loc[next_date]['Adj Close'].item()
        return None

    def calculate_return(start_price, end_price):
        if start_price is not None and end_price is not None:
            return f"{round(((end_price - start_price) / start_price) * 100, 2)}%"
        return None

    results = []
    for idx, row in df.iterrows():
        try:
            announcement_date = pd.to_datetime(row['announcement_date']).normalize()
            record_date = pd.to_datetime(row['record_date']).normalize()
            symbol = row['symbol']

            end_dates = {
                '3m': announcement_date + timedelta(days=90),
                '6m': announcement_date + timedelta(days=180),
                '1y': announcement_date + timedelta(days=365),
                '3y': announcement_date + timedelta(days=1095)
            }

            stock_data = yf.download(
                symbol,
                start=(announcement_date - timedelta(days=10)).strftime('%Y-%m-%d'),
                end=(end_dates['3y'] + timedelta(days=10)).strftime('%Y-%m-%d'),
                progress=False
            )

            stock_data.index = pd.DatetimeIndex([idx.date() for idx in stock_data.index])
            
            announcement_price = get_next_price(stock_data, announcement_date)
            if announcement_price is None:
                continue

            record_price = get_next_price(stock_data, record_date)
            record_date_return = calculate_return(announcement_price, record_price)

            period_returns = {}
            for period, end_date in end_dates.items():
                end_price = get_next_price(stock_data, end_date)
                period_returns[period] = calculate_return(announcement_price, end_price)

            results.append({
                'symbol': symbol,
                'announcement_date': row['announcement_date'].strftime('%Y-%m-%d'),
                'record_date': row['record_date'].strftime('%Y-%m-%d'),
                'record_date_return': record_date_return,
                **period_returns
            })

        except Exception as e:
            print(f"Error processing {row['symbol']} on {row['announcement_date']}: {str(e)}")
            continue

    return pd.DataFrame(results)

def gather_and_calculate_returns(user_input):
    print(user_input)
    try:
        formatted_prompt = stock_info_prompt.invoke({"user_input": user_input})
        llm = ChatOpenAI(api_key=os.getenv('API_KEY'),base_url=os.getenv('URL'))
        conn_string = f'user={os.environ.get("user")} password={os.environ.get("password")} host={os.environ.get("host")} port={os.environ.get("port")} dbname={os.environ.get("db")}'
        response = llm.invoke(formatted_prompt)
        print(response)
        
        op = json.loads(response.content)
        stock_symbol = op['Stock Name'].upper()
        corp_action = op['Corporate Action']

        if not stock_symbol.endswith(".NS"):
            stock_symbol += ".NS"

        if corp_action.upper() not in ['SPLIT', 'BONUS', 'BUYBACK']:
            return f"Please provide only the corporate action of 'SPLIT', 'BONUS', or 'BUYBACK' to proceed", None

        if not is_valid_stock(stock_symbol):
            return f"The stock symbol {stock_symbol} is not valid or not listed on a recognized exchange.", None

        corpaction_query = """
            SELECT 
                symbol, 
                record_date, 
                announcement_date, 
                action 
            FROM 
                nse_corpactions
            WHERE 
                action = %s AND symbol = %s
            ORDER BY 
                record_date, 
                announcement_date;
        """
        conn = psycopg2.connect(conn_string)
        filtered_df = pd.read_sql_query(corpaction_query, conn, params=(corp_action.lower(), stock_symbol))

        if filtered_df.empty:
            return f"No {corp_action} corporate announcements found for {stock_symbol}.", None
            
        filtered_df['record_date'] = pd.to_datetime(filtered_df['record_date'])
        filtered_df['announcement_date'] = pd.to_datetime(filtered_df['announcement_date'])
        returns_df = calculate_returns(filtered_df)
        
        return returns_df,corp_action.upper()

    except Exception as e:
        print("Error: ", op['error'])
        return jsonify({"error": op['error']}), 400

def analyze_reasoning(df,corp_action):
    df_head = df.head().to_string()
    formatted_prompt = generate_analysis_prompt(df_head, corp_action)
    llm = ChatOpenAI(api_key=os.getenv('API_KEY'),base_url=os.getenv('URL'))
    output = llm.invoke(formatted_prompt)
    return output.content


# Flask routes
@app.route('/')
def home():
    return render_template('chat.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    print(request.data)  # Log raw data for debugging
    print(request.get_json())  
    data = request.get_json()
    user_input = data.get('query')
    print(user_input)
    analysis_data,corp_action = gather_and_calculate_returns(user_input)
    print(analysis_data,corp_action)
    if corp_action is None:
        return jsonify({"error": analysis_data }), 400
    reasoning_data = analyze_reasoning(analysis_data,corp_action)
    print(reasoning_data)
    return jsonify({"analysis": analysis_data.to_dict('records'), "reasoning": reasoning_data}),200





