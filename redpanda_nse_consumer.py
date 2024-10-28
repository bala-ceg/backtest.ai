from kafka import KafkaConsumer
from supabase import create_client
import logging
import json
import os

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
table_name = os.environ.get("TABLE_NAME")

supabase = create_client(supabase_url, supabase_key)

consumer = KafkaConsumer(
  bootstrap_servers=os.environ.get("RP_HOST"),
  security_protocol="SASL_SSL",
  sasl_mechanism="SCRAM-SHA-256",
  sasl_plain_username=os.environ.get("RP_USER"),
  sasl_plain_password=os.environ.get("RP_PASSWORD"),
  auto_offset_reset="earliest",
  enable_auto_commit=False,
  consumer_timeout_ms=10000
)

consumer.subscribe(os.environ.get("RP_TOPIC"))


try:
    for message in consumer:
        topic_info = f"topic: {message.topic} ({message.partition}|{message.offset})"
        
        try:
            decoded_value = message.value.decode('utf-8')
            components = decoded_value.split(',')
            
            row_data = {
                'record_date': components[0],
                'announcement_date': components[1],
                'symbol': components[2],
                'action': components[3]
            }

        except Exception as e:
            logging.error(f"Error processing message value: {e}")
            continue

        logging.info(f"{topic_info}, row_data: {row_data}")

        try:
            supabase.table('nsecorpactions').insert(row_data).execute()
            logging.info(f"Inserted row: {row_data} into your_table_name")
        except Exception as e:
            logging.error(f"Error inserting row into Supabase: {e}")

except Exception as e:
    logging.error(f"Error consuming messages: {e}")
