from datetime import datetime, timezone
from flask_login import UserMixin
from ext import db


def get_utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bonus_balance = db.Column(db.Float, default=0.0)
    referral_code = db.Column(db.String(20), unique=True, nullable=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    date_created = db.Column(db.DateTime, default=get_utc_now)

    orders = db.relationship('Order', backref='buyer', lazy=True)
    likes = db.relationship('ProductLike', backref='user', lazy=True, cascade="all, delete-orphan")
    reviews = db.relationship('Review', backref='author', lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade="all, delete-orphan")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    ingredients = db.Column(db.String(255), nullable=True)
    allergens = db.Column(db.String(255), nullable=True)
    dietary_tag = db.Column(db.String(50), default='standard')
    cooking_time = db.Column(db.String(50), default="7-8 წუთი")
    unit = db.Column(db.String(30), default="1 კგ")
    weight_info = db.Column(db.String(50), nullable=True)
    price = db.Column(db.Float, nullable=False)
    wholesale_price = db.Column(db.Float, nullable=True)
    category = db.Column(db.String(50), nullable=False)

    image_file = db.Column(db.String(500), default='')
    is_featured = db.Column(db.Boolean, default=False)
    in_stock = db.Column(db.Boolean, default=True)
    stock_qty = db.Column(db.Integer, default=20)
    date_posted = db.Column(db.DateTime, default=get_utc_now)

    likes = db.relationship('ProductLike', backref='product', lazy=True, cascade="all, delete-orphan")
    reviews = db.relationship('Review', backref='product', lazy=True, cascade="all, delete-orphan")

    @property
    def image_url(self):
        if self.image_file and self.image_file.startswith(('http://', 'https://')):
            return self.image_file
        if self.image_file and self.image_file != 'default_food.png':
            return f"/static/uploads/{self.image_file}"
        return "https://images.unsplash.com/photo-1625220194771-7ebdea0b70b9?auto=format&fit=crop&w=900&q=80"


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    delivery_slot = db.Column(db.String(100), default='რაც შეიძლება სწრაფად (1-2 სთ)')
    notes = db.Column(db.Text, nullable=True)

    items_summary = db.Column(db.Text, nullable=False)
    items_json = db.Column(db.Text, nullable=True)
    subtotal = db.Column(db.Float, nullable=False)
    discount_amount = db.Column(db.Float, default=0.0)
    referral_code_used = db.Column(db.String(20), nullable=True)
    referral_rewarded = db.Column(db.Boolean, default=False)
    bonus_used = db.Column(db.Float, default=0.0)
    bonus_rewarded = db.Column(db.Boolean, default=False)
    shipping_fee = db.Column(db.Float, default=5.0)
    total_price = db.Column(db.Float, nullable=False)

    payment_method = db.Column(db.String(50), default='cash')
    receipt_image = db.Column(db.String(255), nullable=True)

    status = db.Column(db.String(30), default='pending')
    created_at = db.Column(db.DateTime, default=get_utc_now)


class ProductLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=get_utc_now)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    date_posted = db.Column(db.DateTime, default=get_utc_now)

    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    trigger_review = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=get_utc_now)