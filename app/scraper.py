import json
import re
import time

import requests
from google import genai
from playwright.sync_api import sync_playwright

from .config import GEMINI_API_KEY


def get_product_info(url: str) -> dict:
    """Uses real browser (Playwright) to bypass 403s. Falls back to Gemini if needed."""

    # === Try Playwright (Real Browser - Most Reliable) ===
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()

            # 30s timeout is standard, but heavy sites might still timeout
            page.goto(url, wait_until="networkidle", timeout=30000)

            page.wait_for_timeout(3000)

            html = page.content()
            title = page.title() or "Unknown Product"

            price = None

            # Basic Regex for Indian Rupees
            price_match = re.search(r"₹[\s,]*([\d,]+(?:\.\d+)?)", html)
            if price_match:
                try:
                    price = float(price_match.group(1).replace(",", ""))
                except:
                    pass

            # Try JSON-LD for better accuracy (Standard e-commerce metadata)
            try:
                json_ld = page.locator(
                    'script[type="application/ld+json"]'
                ).first.inner_text()
                data = json.loads(json_ld)
                if isinstance(data, list):
                    data = data[0]
                if data.get("name"):
                    title = data["name"]
                offers = data.get("offers") or {}
                if isinstance(offers, dict) and offers.get("price"):
                    price = float(offers["price"])
            except:
                pass

            browser.close()

            if price is not None:
                print(
                    f"[Playwright Success] {url} → Name: {title[:60]}... | Price: ₹{price}"
                )
                return {"name": title[:120], "price": price, "source": "playwright"}
            else:
                print(
                    f"[Playwright Partial] Loaded page but couldn't find price for {url}. Falling to Gemini."
                )

    except Exception as e:
        print(
            f"[Playwright Failed] {url} → {type(e).__name__}: {e}. Falling to Gemini."
        )

    # === Fallback to Gemini ===
    if GEMINI_API_KEY and GEMINI_API_KEY.strip():
        try:
            print("[Attempting Gemini Fallback]")

            # Fetch raw page content
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            response = requests.get(url, headers=headers, timeout=10)

            # First 20k chars is usually enough for top-level DOM to save tokens
            html_snippet = response.text[:20000]

            # Initialize new client
            client = genai.Client(api_key=GEMINI_API_KEY)

            prompt = f"""
            You are a web scraping assistant. Extract the product name and the current selling price in INR from the following raw HTML snippet.
            Respond ONLY with a valid JSON object. Do not include markdown formatting like ```json.
            If you cannot find the price, set the price value to null.

            Format: {{"name": "Extracted Product Name", "price": 1234.56}}

            URL Context: {url}
            HTML Snippet:
            {html_snippet}
            """

            # --- EXPONENTIAL BACKOFF RETRY LOGIC ---
            max_retries = 5
            ai_response = None

            for attempt in range(max_retries):
                try:
                    # Call 2.5 Flash
                    ai_response = client.models.generate_content(
                        model="gemini-2.5-flash", contents=prompt
                    )
                    break  # Success! Break out of the retry loop

                except Exception as api_err:
                    if "503" in str(api_err) and attempt < max_retries - 1:
                        sleep_time = 2 ** (attempt + 1)
                        print(
                            f"[Gemini 503] Server overloaded. Retrying in {sleep_time}s..."
                        )
                        time.sleep(sleep_time)
                    else:
                        # If it's not a 503, or we're out of retries, raise the error to be caught below
                        raise api_err
            # ---------------------------------------

            # Clean and parse response to handle unexpected markdown
            clean_text = (
                ai_response.text.strip()
                .removeprefix("```json")
                .removesuffix("```")
                .strip()
            )
            extracted_data = json.loads(clean_text)

            # Safely handle the price
            parsed_price = extracted_data.get("price")
            if parsed_price is not None:
                try:
                    parsed_price = float(parsed_price)
                except (ValueError, TypeError):
                    parsed_price = None

            # --- Safely handle the name to prevent slicing errors ---
            raw_name = extracted_data.get("name")
            # If raw_name is None or empty, default it. Otherwise, force it to a string.
            final_name = str(raw_name) if raw_name else "Unknown Product"

            print(
                f"[Gemini Success] {url} → Name: {final_name[:60]}... | Price: ₹{parsed_price}"
            )

            return {"name": final_name[:120], "price": parsed_price, "source": "gemini"}

        except Exception as e:
            print(f"[Gemini Failed] Could not extract data: {e}")

    return {
        "name": "Failed to load (try again later)",
        "price": None,
        "source": "error",
    }
