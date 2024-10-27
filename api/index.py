from flask import Flask, render_template, request, jsonify
from datetime import timedelta, datetime
import yfinance as yf
import pandas as pd
import requests
import json
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
import urllib.parse
import os




app = Flask(__name__)

# Initialize LangChain components
template = """You are tasked with gathering information for a stock analysis. Please provide the following details:

1. **Stock Name**:
2. **Corporate Action** (only options: Split, Buyback, Bonus):

If any of these details are missing, please ask the user to provide the necessary information.

Current Input:
{user_input}

Return the Response in JSON Format"""

stock_info_prompt = PromptTemplate.from_template(template)
llm = ChatOpenAI(
    api_key=os.getenv('API_KEY'),
    base_url=os.getenv('URL')
)

# Helper functions from bonus_backtest.py
def nsefetch(payload):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
        s = requests.Session()
        s.get("http://nseindia.com", headers=headers)
        response = s.get(payload, headers=headers)
        response.raise_for_status()
        output = response.json()
        return output
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

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
    try:
        formatted_prompt = stock_info_prompt.invoke({"user_input": user_input})
        response = llm.invoke(formatted_prompt)
        
        op = json.loads(response.content)
        stock_symbol = op['Stock Name'].upper()
        corp_action = op['Corporate Action']

        filtered_df = pd.DataFrame({
            'record_date': ['2019-03-07', '2017-06-14', '2010-06-16'],
            'announcement_date': ['2019-01-18', '2017-04-25', '2010-04-23'],
            'symbol': ['WIPRO.NS', 'WIPRO.NS', 'WIPRO.NS']
        })
        returns_df = calculate_returns(filtered_df)
        return returns_df.to_dict('records')

    except Exception as e:
        return {"error": str(e)}

# Flask routes
@app.route('/')
def home():
    return render_template('chat.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    user_input = request.json.get('message')
    result = gather_and_calculate_returns(user_input)
    return jsonify(result)


@app.route('/about')
def index():
    return render_template('chat.html')
