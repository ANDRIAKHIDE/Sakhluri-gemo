from datetime import datetime, timezone
from flask_login import UserMixin
from ext import db

def get_utc_now():
    return datetime.now(timezone.utc)


# --- 1. მომხმარებლის მოდელი ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    date_created = db.Column(db.DateTime, default=get_utc_now)

    # კავშირები
    orders = db.relationship('Order', backref='buyer', lazy=True)
    likes = db.relationship('ProductLike', backref='user', lazy=True, cascade="all, delete-orphan")
    reviews = db.relationship('Review', backref='author', lazy=True, cascade="all, delete-orphan")


# --- 2. პროდუქტის (ნახევარფაბრიკატის) მოდელი ---
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    ingredients = db.Column(db.String(255), nullable=True)   # შემადგენლობა
    cooking_time = db.Column(db.String(50), default="7-8 წუთი") # მომზადების დრო
    unit = db.Column(db.String(30), default="1 კგ")          # '1 ცალი', '1 კგ', '1 სეტი'
    weight_info = db.Column(db.String(50), nullable=True)    # მაგ: '~95 გრ' ან '1000 გრ'
    price = db.Column(db.Float, nullable=False)              # საცალო ფასი
    wholesale_price = db.Column(db.Float, nullable=True)     # საბითუმო ფასი (სურვილისამებრ)
    category = db.Column(db.String(50), nullable=False)      # ხინკალი, პელმენი, ხორცეული, ბლინები, სეტები

    image_file = db.Column(db.String(255), default='default_food.png')
    is_featured = db.Column(db.Boolean, default=False)       # რჩეული / ბესტსელერი
    in_stock = db.Column(db.Boolean, default=True)           # მარაგშია თუ არა
    date_posted = db.Column(db.DateTime, default=get_utc_now)

    likes = db.relationship('ProductLike', backref='product', lazy=True, cascade="all, delete-orphan")
    reviews = db.relationship('Review', backref='product', lazy=True, cascade="all, delete-orphan")


# --- 3. შეკვეთის (ORDER) მოდელი ---
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # სტუმარსაც შეუძლია შეკვეთა
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    items_summary = db.Column(db.Text, nullable=False)       # შეკვეთილი პროდუქტების სია ტექსტურად/JSON-ად
    subtotal = db.Column(db.Float, nullable=False)
    shipping_fee = db.Column(db.Float, default=5.0)
    total_price = db.Column(db.Float, nullable=False)

    payment_method = db.Column(db.String(50), default='cash') # 'cash' (კურიერთან) ან 'transfer' (გადარიცხვა)
    receipt_image = db.Column(db.String(255), nullable=True)

    # სტატუსი: 'pending' (ახალი), 'preparing' (მზადდება), 'delivered' (მიტანილია), 'cancelled' (გაუქმებული)
    status = db.Column(db.String(30), default='pending')
    created_at = db.Column(db.DateTime, default=get_utc_now)


# --- 4. მოწონებების (FAVORITES) მოდელი ---
class ProductLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=get_utc_now)


# --- 5. შეფასების (REVIEW) მოდელი ---
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    date_posted = db.Column(db.DateTime, default=get_utc_now)

    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
