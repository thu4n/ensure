import os
from pathlib import Path
from dotenv import load_dotenv

# Base repo root directory
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Data cache paths
DATA_DIR = BASE_DIR / ".data"
ACCOUNTS_CACHE_FILE = DATA_DIR / "accounts.json"
CATEGORIES_CACHE_FILE = DATA_DIR / "categories.json"
CATEGORY_SAMPLES_CACHE_FILE = DATA_DIR / "category_samples.json"

# API & Model Configuration
SURE_API_URL = os.getenv("SURE_API_URL", "http://sure-web.self-host.orb.local/api/v1/")
SURE_API_KEY = os.getenv("SURE_API_KEY", "")
MODEL_ID = "mlx-community/Llama-3.2-3B-Instruct-4bit"
DEFAULT_ACCOUNT_ID = os.getenv("DEFAULT_ACCOUNT_ID", "81cb8465-1cad-47d5-8061-b8e4baa954db")  # Wallet
DEFAULT_CATEGORY_ID = "adaac5f4-5de7-4d2b-b3d9-45079ebf6208"  # Main meal

EXTRACTION_SCHEMA = {
    "account": "string (must match one of the available accounts name exactly)",
    "amount": "number (positive numeric value, convert 45k -> 45000)",
    "name": "string (short title/merchant, e.g. 'Coffee', 'Grab Ride', 'Banh Mi')",
    "currency": "string (e.g. VND, USD, EUR)",
    "date": "string (YYYY-MM-DD format)",
    "category": "string (must match one of the available categories exactly)",
}
