from flask import Blueprint, render_template, request, redirect, url_for, flash
from .models import Product
from .database import db
from .scraper import get_product_info
from .scheduler import send_telegram_alert # <-- NEW IMPORT
from datetime import datetime

bp = Blueprint('main', __name__)

@bp.route('/', methods=['GET', 'POST'])
def dashboard():
    if request.method == 'POST':
        url = request.form.get('url').strip()
        try:
            target = float(request.form.get('target_price'))
        except (TypeError, ValueError):
            flash("Target price must be a valid number", "danger")
            return redirect(url_for('main.dashboard'))

        if not url.startswith(('http://', 'https://')):
            flash("Please enter a valid URL", "danger")
            return redirect(url_for('main.dashboard'))

        # Create product
        product = Product(url=url, target_price=target)
        db.session.add(product)
        db.session.commit()

        # Fetch info
        info = get_product_info(url)
        product.product_name = info.get("name", "Unknown Product")
        product.current_price = info.get("price")
        product.last_checked = datetime.utcnow()
        
        # --- NEW: Instant Telegram Alert Logic ---
        fetched_price = info.get("price")
        if fetched_price is not None:
            if fetched_price <= target:
                product.is_alerted = True # Lock it so the scheduler doesn't double-send
                send_telegram_alert(product.product_name, product.url, target, fetched_price)
        # -----------------------------------------
        
        db.session.commit()

        if fetched_price is not None:
            flash(f"Product added successfully! Current price: ₹{fetched_price}", "success")
        elif info.get("name") != "Failed to load (try again later)":
            flash(f"Product added (Name: {info.get('name')[:30]}...), but could not fetch latest price. Will retry.", "warning")
        else:
            flash("Product added, but failed to fetch data. Will retry in background.", "warning")

        return redirect(url_for('main.dashboard'))

    products = Product.query.all()
    return render_template('dashboard.html', products=products)


@bp.route('/delete/<int:id>')
def delete(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash("Product removed successfully", "info")
    return redirect(url_for('main.dashboard'))


@bp.route('/check-now')
def check_now():
    from .scheduler import check_prices
    from flask import current_app
    check_prices(current_app)
    flash("✅ All prices have been refreshed!", "success")
    return redirect(url_for('main.dashboard'))