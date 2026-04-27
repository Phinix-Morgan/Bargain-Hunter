import json
import os
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from google import genai

from .database import db
from .models import PriceHistory, Product
from .scheduler import send_telegram_alert
from .scraper import get_product_info

bp = Blueprint("main", __name__)

# ── Gemini client setup ───────────────────────────────────────────────────────
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL = "gemini-2.5-flash"


@bp.route("/", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        url = request.form.get("url").strip()
        try:
            target = float(request.form.get("target_price"))
        except (TypeError, ValueError):
            flash("Target price must be a valid number", "danger")
            return redirect(url_for("main.dashboard"))

        if not url.startswith(("http://", "https://")):
            flash("Please enter a valid URL", "danger")
            return redirect(url_for("main.dashboard"))

        product = Product(url=url, target_price=target)
        db.session.add(product)
        db.session.commit()

        info = get_product_info(url)
        product.product_name = info.get("name", "Unknown Product")
        product.current_price = info.get("price")
        product.last_checked = datetime.utcnow()

        fetched_price = info.get("price")
        if fetched_price is not None:
            history_entry = PriceHistory(product_id=product.id, price=fetched_price)
            db.session.add(history_entry)

            if fetched_price <= target:
                product.is_alerted = True
                send_telegram_alert(
                    product.product_name, product.url, target, fetched_price
                )

        db.session.commit()

        if fetched_price is not None:
            flash(
                f"Product added successfully! Current price: ₹{fetched_price}",
                "success",
            )
        elif info.get("name") != "Failed to load (try again later)":
            flash(
                f"Product added (Name: {info.get('name')[:30]}...), but could not fetch latest price. Will retry.",
                "warning",
            )
        else:
            flash(
                "Product added, but failed to fetch data. Will retry in background.",
                "warning",
            )

        return redirect(url_for("main.dashboard"))

    products = Product.query.order_by(Product.id.desc()).all()
    return render_template("dashboard.html", products=products)


@bp.route("/delete/<int:id>")
def delete(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash("Product removed successfully", "info")
    return redirect(url_for("main.dashboard"))


@bp.route("/check-now")
def check_now():
    from flask import current_app

    from .scheduler import check_prices

    check_prices(current_app)
    flash("✅ All prices have been refreshed!", "success")
    return redirect(url_for("main.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# PRICE HISTORY API
# ─────────────────────────────────────────────────────────────────────────────
@bp.route("/api/price-history/<int:product_id>")
def price_history_api(product_id):
    product = Product.query.get_or_404(product_id)

    days = request.args.get("days", 30, type=int)
    days = max(1, min(days, 365))

    since = datetime.utcnow() - timedelta(days=days)

    records = (
        PriceHistory.query.filter_by(product_id=product_id)
        .filter(PriceHistory.timestamp >= since)
        .order_by(PriceHistory.timestamp.asc())
        .all()
    )

    if not records:
        records = (
            PriceHistory.query.filter_by(product_id=product_id)
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

    if not records:
        return jsonify(
            {
                "has_data": False,
                "labels": [],
                "prices": [],
                "lowest": None,
                "highest": None,
                "average": None,
                "target": product.target_price,
                "current": product.current_price,
                "count": 0,
            }
        )

    actual_days = (records[-1].timestamp - records[0].timestamp).days or 1

    def fmt_label(dt):
        if actual_days <= 7:
            return dt.strftime("%a %-d")
        elif actual_days <= 60:
            return dt.strftime("%-d %b")
        else:
            return dt.strftime("%b '%y")

    labels = [fmt_label(r.timestamp) for r in records]
    prices = [round(r.price, 2) for r in records]
    lowest = round(min(prices), 2)
    highest = round(max(prices), 2)
    average = round(sum(prices) / len(prices), 2)

    return jsonify(
        {
            "has_data": True,
            "labels": labels,
            "prices": prices,
            "lowest": lowest,
            "highest": highest,
            "average": average,
            "target": product.target_price,
            "current": product.current_price,
            "count": len(records),
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI DEAL ANALYSIS API
# ─────────────────────────────────────────────────────────────────────────────
@bp.route("/api/gemini-deal-analysis", methods=["POST"])
def gemini_deal_analysis():
    try:
        body = request.get_json(force=True)

        product_name = body.get("product_name", "Unknown Product")
        current = body.get("current")
        target = body.get("target")
        lowest = body.get("lowest")
        highest = body.get("highest")
        average = body.get("average")
        count = body.get("count", 1)
        prices = body.get("prices", [])

        prompt = f"""
You are an expert e-commerce price analyst for Indian shoppers.
Analyse the following real price data for a product and return a JSON deal analysis.

PRODUCT: {product_name}
CURRENT PRICE: ₹{current}
TARGET / ALERT PRICE: ₹{target}
LOWEST EVER RECORDED: ₹{lowest}
HIGHEST EVER RECORDED: ₹{highest}
AVERAGE PRICE: ₹{average}
NUMBER OF PRICE RECORDS: {count}
RECENT PRICE TREND (oldest to newest): {prices[-10:] if prices else []}

Return ONLY valid JSON — no markdown fences, no extra text — in this exact schema:

{{
  "score": <integer 0-100>,
  "verdict": <one of: "Great Deal" | "Average Deal" | "Overpriced" | "Neutral">,
  "verdict_emoji": <one of: "🔥" | "⚠️" | "❌" | "➖">,
  "description": "<2-3 sentence plain-English analysis for an Indian shopper. Mention specific rupee amounts. Be direct and helpful.>",
  "breakdown": {{
    "vs_target": {{
      "score": <integer 0-100>,
      "label": "<short 1-line insight about price vs target>",
      "color": "<hex: use #98971a for good, #fabd2f for okay, #fb4934 for bad>"
    }},
    "vs_lowest": {{
      "score": <integer 0-100>,
      "label": "<short 1-line insight about price vs historical low>",
      "color": "<hex color>"
    }},
    "vs_average": {{
      "score": <integer 0-100>,
      "label": "<short 1-line insight about price vs average>",
      "color": "<hex color>"
    }}
  }},
  "trend": <one of: "falling" | "rising" | "stable" | "unknown">,
  "recommendation": "<One punchy action sentence: Buy now / Wait / Watch>",
  "confidence": <integer 0-100>
}}

Scoring guide:
- score >= 70  → Great Deal
- score 40-69  → Average Deal
- score < 40   → Overpriced
- If count < 3, set confidence lower and note limited data in description.
- vs_target score:  100 if current <= target, scale down proportionally above target.
- vs_lowest score:  100 if current equals lowest, 0 if current equals highest.
- vs_average score: 100 if well below average, 0 if well above average.
- trend: compare last 3 prices — falling if decreasing, rising if increasing, stable if flat.

Return ONLY the JSON object. No markdown. No explanation outside the JSON.
"""

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )

        raw = response.text.strip()

        # Strip markdown fences if Gemini wraps anyway
        if raw.startswith("```"):
            lines = [l for l in raw.split("\n") if not l.startswith("```")]
            raw = "\n".join(lines).strip()

        parsed = json.loads(raw)
        parsed["score"] = max(0, min(100, int(parsed.get("score", 50))))

        return jsonify({"ok": True, "analysis": parsed})

    except Exception as e:
        # Graceful fallback — UI never breaks
        return jsonify(
            {
                "ok": False,
                "error": str(e),
                "analysis": {
                    "score": 50,
                    "verdict": "Neutral",
                    "verdict_emoji": "➖",
                    "description": "AI analysis could not be completed right now. Please try again.",
                    "breakdown": {
                        "vs_target": {
                            "score": 50,
                            "label": "Data unavailable",
                            "color": "#928374",
                        },
                        "vs_lowest": {
                            "score": 50,
                            "label": "Data unavailable",
                            "color": "#928374",
                        },
                        "vs_average": {
                            "score": 50,
                            "label": "Data unavailable",
                            "color": "#928374",
                        },
                    },
                    "trend": "unknown",
                    "recommendation": "Try again later.",
                    "confidence": 0,
                },
            }
        ), 200
