from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    bot_token = os.getenv("BOT_TOKEN")
    encryption_key = os.getenv("ENCRYPTION_KEY")
    admin_telegram_ids = [int(x) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x]
    database_path = os.getenv("DATABASE_PATH", "escrow_data.db")
    admin_username = os.getenv("ADMIN_USERNAME", "")
    
    # API key for BlockCypher
    blockcypher_api_key = os.getenv("BLOCKCYPHER_API_KEY", "")

def load_config():
    return Config()