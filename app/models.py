from datetime import datetime

from .database import db


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(500), nullable=True)
    url = db.Column(db.String, nullable=False)
    target_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float, nullable=True)
    last_checked = db.Column(db.DateTime, nullable=True)
    is_alerted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to automatically delete history if product is removed
    history = db.relationship(
        "PriceHistory", backref="product", lazy=True, cascade="all, delete-orphan"
    )


class PriceHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    price = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
