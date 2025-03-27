#!/usr/bin/env python3
# Import necessary libraries
import sys
import requests
from bs4 import BeautifulSoup
import lxml
import smtplib
import re
import json
import time
from urllib.parse import urlparse
import typer
from typing import Optional, List, Dict
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = typer.Typer()

def extract_asin(url: str) -> Optional[str]:
    """
    Extract ASIN from Amazon product URL

    Args:
        url (str): Amazon product URL

    Returns:
        str: ASIN or None if not found
    """
    # Extract ASIN using regex pattern for /dp/ASIN format
    asin_match = re.search(r'/dp/([A-Z0-9]{10})(?:/|\?|$)', url)

    # If no match found, try another common pattern
    if not asin_match:
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.split('/')

        # Check if path contains 'dp' followed by ASIN
        for i, part in enumerate(path_parts):
            if part == 'dp' and i+1 < len(path_parts) and len(path_parts[i+1]) == 10:
                return path_parts[i+1]

        # If still no match, look for any 10-character alphanumeric segment that might be ASIN
        asin_match = re.search(r'/([A-Z0-9]{10})(?:/|\?|$)', url)
        if asin_match:
            return asin_match.group(1)

        return None
    else:
        return asin_match.group(1)

def create_associate_url(asin: str, associate_id: str = None) -> str:
    """
    Create Amazon associate URL from ASIN

    Args:
        asin (str): Amazon ASIN
        associate_id (str): Your Amazon Associate ID (optional)

    Returns:
        str: Amazon associate URL
    """
    if associate_id is None:
        associate_id = os.getenv('AMAZON_ASSOCIATE_ID', 'yourtrackingid')
    return f"https://www.amazon.com/dp/{asin}/ref=nosim?tag={associate_id}"

def get_amazon_price(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Scrape Amazon product page and return product price and delivery price

    Args:
        url (str): Amazon product URL

    Returns:
        tuple: (item_price, delivery_price)
    """
    # Headers to mimic a browser visit
    headers = {
        'Accept-Language': "en-US,en;q=0.9",
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 Edg/107.0.1418.35"
    }

    # Send a request to the URL
    response = requests.get(url, headers=headers)

    # Check if request was successful
    if response.status_code != 200:
        print(f"Error: Unable to access the URL. Status code: {response.status_code}")
        return None, None

    # Parse the HTML content of the page
    soup = BeautifulSoup(response.content, "lxml")

    # Find the element that contains the price
    try:
        item_price = soup.find("span", class_="a-offscreen").getText()
        delivery_price_element = soup.find("span", {"data-csa-c-content-id": "DEXUnifiedCXPDM"})
        delivery_price = delivery_price_element.get("data-csa-c-delivery-price") if delivery_price_element else None

        return item_price, delivery_price
    except AttributeError:
        print("Error: Could not find price elements on the page")
        return None, None

def send_telegram_message(message: str, bot_token: str = None, chat_id: str = None) -> bool:
    """
    Send a message via Telegram

    Args:
        message (str): Message to send
        bot_token (str): Telegram bot token (optional)
        chat_id (str): Telegram chat ID (optional)

    Returns:
        bool: True if message was sent successfully
    """
    if bot_token is None:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if chat_id is None:
        chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id:
        print("Error: Telegram credentials not found in environment variables")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=data)
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return False

def load_products(filename: str = "products.json") -> List[Dict]:
    """
    Load product URLs from JSON file

    Args:
        filename (str): Path to JSON file

    Returns:
        List[Dict]: List of product dictionaries
    """
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {filename} not found")
        return []
    except json.JSONDecodeError:
        print(f"Error: {filename} is not valid JSON")
        return []

def monitor_products(
    products: List[Dict],
    associate_id: str = None,
    bot_token: str = None,
    chat_id: str = None,
    sleep_minutes: int = 20
) -> None:
    """
    Monitor products until free shipping is available

    Args:
        products (List[Dict]): List of product dictionaries
        associate_id (str): Amazon Associate ID (optional)
        bot_token (str): Telegram bot token (optional)
        chat_id (str): Telegram chat ID (optional)
        sleep_minutes (int): Minutes to sleep between checks
    """
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\nChecking prices at {current_time}")

        for product in products:
            url = product.get('url')
            name = product.get('name', 'Unknown Product')

            if not url:
                continue

            # Extract ASIN and create associate URL
            asin = extract_asin(url)
            if not asin:
                print(f"Error: Could not extract ASIN from URL for {name}")
                continue

            associate_url = create_associate_url(asin, associate_id)

            # Get price and shipping
            item_price, delivery_price = get_amazon_price(associate_url)

            if not item_price:
                print(f"Error: Could not get price for {name}")
                continue

            # Check if shipping is free
            if delivery_price and delivery_price.lower() == "free":
                message = (
                    f"🎉 Free shipping available for {name}!\n"
                    f"Price: {item_price}\n"
                    f"Link: {associate_url}"
                )

                if send_telegram_message(message, bot_token, chat_id):
                    print(f"Notification sent for {name}")
                else:
                    print(f"Failed to send notification for {name}")
            else:
                print(f"{name}: {item_price} (Shipping: {delivery_price or 'Unknown'})")

        print(f"\nSleeping for {sleep_minutes} minutes...")
        time.sleep(sleep_minutes * 60)

@app.command()
def check_price(
    url: str = typer.Argument(..., help="Amazon product URL"),
    associate_id: str = typer.Option(None, help="Your Amazon Associate ID (optional)")
):
    """Check price for a single Amazon product"""
    # Extract ASIN
    asin = extract_asin(url)
    if not asin:
        print("Error: Could not extract ASIN from URL. Using original URL.")
        asin_url = url
    else:
        asin_url = f"https://www.amazon.com/dp/{asin}"
        print(f"Cleaned URL: {asin_url}")

    associate_url = create_associate_url(asin, associate_id)
    print(f"Associate URL: {associate_url}")
    print(f"Processing URL: {associate_url}")

    item_price, delivery_price = get_amazon_price(associate_url)

    if item_price:
        print(f"Item price: {item_price}")
        print(f"Delivery price: {delivery_price}")
    else:
        print("Failed to retrieve price information")

@app.command()
def monitor(
    associate_id: str = typer.Option(None, help="Your Amazon Associate ID (optional)"),
    sleep_minutes: int = typer.Option(20, help="Minutes to sleep between checks"),
    products_file: str = typer.Option("products.json", help="Path to products JSON file")
):
    """Monitor products from JSON file until free shipping is available"""
    products = load_products(products_file)
    if not products:
        print("No products to monitor. Please check your products.json file.")
        return

    print(f"Starting to monitor {len(products)} products...")
    monitor_products(products, associate_id, sleep_minutes=sleep_minutes)

if __name__ == "__main__":
    app()
