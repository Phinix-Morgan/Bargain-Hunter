from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from .models import Product
from .scraper import get_product_info
from .database import db
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import threading
import requests

scheduler = BackgroundScheduler(timezone="UTC")
lock = threading.Lock()

def send_telegram_alert(product_name, url, target_price, current_price):
    """Sends a markdown-formatted alert message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram credentials missing in .env. Skipping alert.")
        return

    # Using Markdown formatting for a clean, readable alert
    message = (
        f"🚨 *PRICE DROP ALERT* 🚨\n\n"
        f"📦 *Product:* {product_name[:60]}...\n"
        f"💰 *Current Price:* ₹{current_price}\n"
        f"🎯 *Target Price:* ₹{target_price}\n\n"
        f"🔗 [Click here to view product]({url})"
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(api_url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"📱 Telegram alert sent for: {product_name[:30]}...")
        else:
            print(f"❌ Telegram API Error: {response.text}")
    except Exception as e:
        print(f"❌ Failed to send Telegram alert: {e}")


def check_prices(app):
    with app.app_context():
        with lock:
            products = Product.query.all()
            for p in products:
                info = get_product_info(p.url)
                
                p.product_name = info["name"]
                p.current_price = info["price"]
                p.last_checked = datetime.utcnow()

                if info["price"] is not None:
                    # If the price drops below target AND we haven't alerted yet
                    if info["price"] <= p.target_price and not p.is_alerted:
                        p.is_alerted = True
                        send_telegram_alert(p.product_name, p.url, p.target_price, info["price"])
                    
                    # If the price goes back up, reset the alert flag so it can trigger again later
                    elif info["price"] > p.target_price and p.is_alerted:
                        p.is_alerted = False

                db.session.commit()

def start_scheduler(app):
    scheduler.add_job(
        check_prices,
        trigger="interval",
        minutes=30,
        args=[app],
        id="price_checker",
        replace_existing=True
    )
    scheduler.start()
    print("✅ Price checker started (every 30 minutes)")