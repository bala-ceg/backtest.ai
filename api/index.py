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

        if corp_action.upper() not in ['SPLIT', 'BONUS', 'BUYBACK']:
            return "Please provide only the corporate action of 'SPLIT', 'BONUS', or 'BUYBACK' to proceed."

        if not stock_symbol.endswith(".NS"):
            stock_symbol += ".NS"

        if not is_valid_stock(stock_symbol):
            return f"The stock symbol {stock_symbol} is not valid or not listed on a recognized exchange."

        symbol_for_nse = stock_symbol.replace(".NS", "")
        
        corp_data = nsefetch(f'https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol_for_nse}&subject={corp_action.upper()}')
        corpaction_df = pd.DataFrame(corp_data)

        if corpaction_df.empty and corp_action.upper() == 'BUYBACK':
            corp_data = nsefetch(f'https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol_for_nse}')
            corpaction_df = pd.DataFrame(corp_data)
            pattern = r'Buyback|Buy Back'
            corpaction_df = corpaction_df[corpaction_df['subject'].str.contains(pattern, case=False, na=False)]
            
        if corpaction_df.empty:
            return f"No {corp_action} corporate actions found for {symbol_for_nse}."

        # Process corporate actions data
        corpaction_df = corpaction_df[['subject', 'recDate', 'symbol']].copy()
        corpaction_df['record_date'] = pd.to_datetime(corpaction_df['recDate'])
        corpaction_df['record_date'] = corpaction_df['record_date'].dt.strftime('%d-%m-%Y')
        corpaction_df = corpaction_df[['symbol', 'record_date']]

        # Fetch company data
        data = nsefetch(f'https://www.nseindia.com/api/quote-equity?symbol={symbol_for_nse}')
        encoded_name = urllib.parse.quote(data['info']['companyName'])

        # Fetch announcements
        if corp_action.upper() == 'SPLIT':
            corpannounce_data = nsefetch(f'https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol_for_nse}&subject=Stock split&issuer={encoded_name}')
        else:
            corpannounce_data = nsefetch(f'https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol_for_nse}&subject={corp_action.upper()}&issuer={encoded_name}')
        
        corpannounce_df = pd.DataFrame(corpannounce_data)
        
        if corpannounce_df.empty:
            return f"No {corp_action} corporate announcements found for {symbol_for_nse}."

        # Process announcements data
        corpannounce_df = corpannounce_df.rename(columns={'sort_date': 'announcement_date'})
        corpannounce_df = corpannounce_df[['smIndustry', 'announcement_date', 'symbol', 'desc']].copy()
        corpannounce_df['announcement_date'] = pd.to_datetime(corpannounce_df['announcement_date'])
        corpannounce_df['announcement_date'] = corpannounce_df['announcement_date'].dt.strftime('%d-%m-%Y')
        corpannounce_df = corpannounce_df[['symbol', 'announcement_date', 'smIndustry', 'desc']]

        # Merge and process final dataset
        corpaction_df['record_date'] = pd.to_datetime(corpaction_df['record_date'], format='%d-%m-%Y')
        corpannounce_df['announcement_date'] = pd.to_datetime(corpannounce_df['announcement_date'], format='%d-%m-%Y')
        
        merged_df = pd.merge(corpaction_df, corpannounce_df, on='symbol', how='inner')
        merged_df = merged_df[merged_df['record_date'].dt.year == merged_df['announcement_date'].dt.year]
        
        merged_df['year'] = merged_df['record_date'].dt.year
        merged_df['symbol'] = merged_df['symbol'] + ".NS"
        merged_df = merged_df[['record_date', 'announcement_date', 'symbol', 'desc']]
        
        # Sort and filter duplicates
        merged_df = merged_df.sort_values(by=['record_date', 'announcement_date'])
        filtered_df = merged_df.drop_duplicates(subset=['record_date'], keep='first')

        # Calculate returns
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
