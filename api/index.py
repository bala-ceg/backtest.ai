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

template = """You are tasked with gathering information for a stock analysis. Please provide the following details:

1. **Stock Name**:
2. **Corporate Action** (only options: Split, Buyback, Bonus):

If any of these details are missing, please ask the user to provide the necessary information.

Current Input:
{user_input}

Return the Response in JSON Format"""



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
        stock_info_prompt = PromptTemplate.from_template(template)
        llm = ChatOpenAI(api_key=os.getenv('API_KEY'),base_url=os.getenv('URL'))
        conn_string = f'user={os.environ.get("user")} password={os.environ.get("password")} host={os.environ.get("host")} port={os.environ.get("port")} dbname={os.environ.get("db")}'
        formatted_prompt = stock_info_prompt.invoke({"user_input": user_input})
        response = llm.invoke(formatted_prompt)
        print(response)
        
        op = json.loads(response.content)
        stock_symbol = op['Stock Name'].upper()
        corp_action = op['Corporate Action']
        
        if not stock_symbol.endswith(".NS"):
            stock_symbol += ".NS

        if corp_action.upper() not in ['SPLIT', 'BONUS', 'BUYBACK']:
            return jsonify({"error": "Please provide only the corporate action of 'SPLIT', 'BONUS', or 'BUYBACK' to proceed"}), 400

        if not is_valid_stock(stock_symbol):
            return jsonify({"error": f"The stock symbol {stock_symbol} is not valid or not listed on a recognized exchange."}), 400

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

        if not filtered_df.empty:
            filtered_df['record_date'] = pd.to_datetime(filtered_df['record_date'])
            filtered_df['announcement_date'] = pd.to_datetime(filtered_df['announcement_date'])
        else:
            return jsonify({"error": f"No {corp_action} corporate announcements found for {stock_symbol}."}), 400

        
        returns_df = calculate_returns(filtered_df)
      
        return jsonify(returns_df.to_dict('records')), 200

    except Exception as e:
        print("Error: ", op['error'])
        return jsonify({"error": op['error']}), 400

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
    result = gather_and_calculate_returns(user_input)
    return result







