import requests
import pandas as pd
import urllib.parse
from datetime import datetime
import os
import csv
import socket
from kafka import KafkaProducer

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

def get_corpaction_data(stock_symbol, corp_action):
    symbol_for_nse = stock_symbol.replace(".NS", "")
    corp_data = nsefetch(f'https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol_for_nse}&subject={corp_action.upper()}')
    
    if not corp_data:
        print(f"No data returned for {symbol_for_nse} with action {corp_action}.")
        return None
    
    corpaction_df = pd.DataFrame(corp_data)

    if 'subject' not in corpaction_df.columns:
        print(f"'subject' column missing for {symbol_for_nse} with action {corp_action}. Response data:\n{corp_data}")
        return None

    if corpaction_df.empty and corp_action.upper() == 'BUYBACK':
        corp_data = nsefetch(f'https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol_for_nse}')
        corpaction_df = pd.DataFrame(corp_data)
        
        if 'subject' not in corpaction_df.columns:
            print(f"'subject' column missing in re-fetch for {symbol_for_nse} with action {corp_action}. Response data:\n{corp_data}")
            return None

        pattern = r'Buyback|Buy Back'
        corpaction_df = corpaction_df[corpaction_df['subject'].str.contains(pattern, case=False, na=False)]
    
    if corpaction_df.empty:
        return None  

    corpaction_df = corpaction_df[['subject', 'recDate', 'symbol']].copy()
    corpaction_df['record_date'] = pd.to_datetime(corpaction_df['recDate'], format='mixed', errors='coerce')
    corpaction_df['record_date'] = corpaction_df['record_date'].dt.strftime('%d-%m-%Y')
    corpaction_df = corpaction_df[['symbol', 'record_date']]
    return corpaction_df

def get_corpannounce_data(symbol_for_nse, corp_action):
    data = nsefetch(f'https://www.nseindia.com/api/quote-equity?symbol={symbol_for_nse}')
    if not data or 'info' not in data:
        return None  
    encoded_name = urllib.parse.quote(data['info']['companyName'])

    if corp_action.upper() == 'SPLIT':
        url = f'https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol_for_nse}&subject=Stock split&issuer={encoded_name}'
    else:
        url = f'https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol_for_nse}&subject={corp_action.upper()}&issuer={encoded_name}'

    corpannounce_data = nsefetch(url)
    corpannounce_df = pd.DataFrame(corpannounce_data)
    
    if corpannounce_df.empty:
        return None  
    
    corpannounce_df = corpannounce_df.rename(columns={'sort_date': 'announcement_date'})
    corpannounce_df['announcement_date'] = pd.to_datetime(corpannounce_df['announcement_date']).dt.strftime('%d-%m-%Y')
    corpannounce_df = corpannounce_df[['symbol', 'announcement_date', 'smIndustry', 'desc']]
    return corpannounce_df

def filter_merged_data(stock_symbol, corp_action):
    symbol_for_nse = stock_symbol.replace(".NS", "")
    corpaction_df = get_corpaction_data(stock_symbol, corp_action)
    if corpaction_df is None:
        return None

    corpannounce_df = get_corpannounce_data(symbol_for_nse, corp_action)
    if corpannounce_df is None:
        return None

    corpaction_df['record_date'] = pd.to_datetime(corpaction_df['record_date'], format='%d-%m-%Y')
    corpannounce_df['announcement_date'] = pd.to_datetime(corpannounce_df['announcement_date'], format='%d-%m-%Y')

    merged_df = pd.merge(corpaction_df, corpannounce_df, on='symbol', how='inner')
    current_year = datetime.now().year

    merged_df = merged_df[(merged_df['record_date'].dt.year == merged_df['announcement_date'].dt.year)]
    merged_df['year'] = merged_df['record_date'].dt.year
    merged_df['symbol'] = merged_df['symbol'] + ".NS"
    merged_df = merged_df[['record_date', 'announcement_date', 'symbol', 'desc']]
    merged_df = merged_df.sort_values(by=['record_date', 'announcement_date'])

    filtered_df = merged_df.drop_duplicates(subset=['record_date'], keep='first')
    return filtered_df

def save_filtered_data_to_csv(symbols_csv_path, corp_actions, output_csv_path):
    symbols_df = pd.read_csv(symbols_csv_path)
    symbols = symbols_df['Symbol'].tolist()

    for corp_action in corp_actions:
        for stock_symbol in symbols:
            filtered_df = filter_merged_data(stock_symbol, corp_action)
            
            if filtered_df is not None and not filtered_df.empty:
                if not os.path.isfile(output_csv_path):
                    filtered_df.to_csv(output_csv_path, mode='w', index=False)
                    print(f"Data for {stock_symbol} with action {corp_action} written to {output_csv_path}")
                else:
                    filtered_df.to_csv(output_csv_path, mode='a', index=False, header=False)
                    print(f"Data for {stock_symbol} with action {corp_action} appended to {output_csv_path}")
            else:
                print(f"No data to save for {stock_symbol} with action {corp_action}")

def send_data_to_kafka(output_csv_path):
    producer = KafkaProducer(
        bootstrap_servers=os.environ.get("RP_HOST"),
        security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-256",
        sasl_plain_username=os.environ.get("RP_USER"),
        sasl_plain_password=os.environ.get("RP_PASSWORD")
        )

    hostname = str.encode(socket.gethostname())

    def on_success(metadata):
        print(f"Sent to topic '{metadata.topic}' at offset {metadata.offset}")

    def on_error(e):
        print(f"Error sending message: {e}")

    # Read from the CSV file and send records to the producer
    with open(output_csv_path, mode='r', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        next(reader)  # Skip the header row
        for row in reader:
            msg = ','.join(row)  # Join the row elements into a single string
            future = producer.send(
               os.environ.get("RP_TOPIC"),
                key=hostname,
                value=str.encode(msg)
            )
            future.add_callback(on_success)
            future.add_errback(on_error)

    producer.flush()
    producer.close()

# Main execution flow
symbols_csv_path = '/Users/bseetharaman/Desktop/Bala/Hackathon/redpanda/ind_niftytotalmarket_list.csv'  
corp_actions = ['SPLIT', 'BONUS', 'BUYBACK']  
output_csv_path = 'corporate_actions.csv'

# Save filtered data to CSV
save_filtered_data_to_csv(symbols_csv_path, corp_actions, output_csv_path)

# Send the saved data to Kafka
send_data_to_kafka(output_csv_path)
