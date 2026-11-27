import os
import io
import csv
import json
import uuid
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session, jsonify, Response, send_file
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from models import User, Product, Order, ProductLike, Review, Notification
from flask import Response

from ext import db
from models import User, Product, Order, ProductLike, Review

main = Blueprint('main', __name__)

CATEGORIES = ['კერძები', 'ტკბილეული', 'სასმელები']

def get_default_product_image(title, category):
    t = (title or '').lower()
    if 'ხინკალ' in t:
        return 'default_khinkali.jpg'
    if 'ბლინ' in t:
        return 'default_blini.jpg'
    if 'პილმენ' in t or 'პელმენ' in t or 'ვარენიკ' in t:
        return 'default_pelmeni.jpg'
    if category == 'ტკბილეული':
        return 'default_sweets.jpg'
    if category == 'სასმელები':
        return 'default_drinks.jpg'
    return 'default_khinkali.jpg'

DIETARY_LABELS = {
    'standard': 'კლასიკური',
    'fasting': 'სამარხვო'
}

DELIVERY_SLOTS = [
    'რაც შეიძლება სწრაფად (1-2 სთ)',
    'დღეს: 14:00 – 18:00',
    'დღეს: 18:00 – 21:00',
    'ხვალ: 11:00 – 15:00',
    'ხვალ: 18:00 – 21:00'
]


def generate_referral_code(username, user_id):
    clean = ''.join(ch for ch in username.upper() if ch.isalnum())[:5]
    if len(clean) < 3:
        clean = "GEMO"
    return f"{clean}{user_id}5"


def send_telegram_alert(message_text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urllib.parse.urlencode({
            'chat_id': chat_id,
            'text': message_text,
            'parse_mode': 'HTML'
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception as e:
        print(f"Telegram alert skipped: {e}")


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('ამ გვერდზე წვდომა მხოლოდ ადმინისტრატორს აქვს!', 'danger')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function


def save_uploaded_file(file_obj, prefix="img"):
    if not file_obj or file_obj.filename == '':
        return None
    upload_folder = current_app.config['UPLOAD_FOLDER']
    ext = os.path.splitext(secure_filename(file_obj.filename))[1].lower() or '.jpg'
    filename = f"{prefix}_{uuid.uuid4().hex[:10]}{ext}"
    file_obj.save(os.path.join(upload_folder, filename))
    return filename


def get_cart_details():
    raw_cart = session.get('cart', {})
    if isinstance(raw_cart, list):
        raw_cart = {str(pid): 1 for pid in raw_cart}
        session['cart'] = raw_cart

    items = []
    subtotal = 0.0
    total_count = 0

    for pid_str, qty in list(raw_cart.items()):
        if not str(pid_str).isdigit():
            continue
        product = Product.query.get(int(pid_str))
        avail = product.stock_qty or 0 if product else 0
        if product and product.in_stock and avail > 0 and qty > 0:
            actual_qty = min(qty, avail)
            line_total = round(product.price * actual_qty, 2)
            subtotal += line_total
            total_count += actual_qty
            items.append({
                'product': product,
                'quantity': actual_qty,
                'line_total': line_total
            })

    subtotal = round(subtotal, 2)
    is_box_combo = session.get('is_box_combo', False) and len(items) >= 3
    box_discount = round(subtotal * 0.10, 2) if is_box_combo else 0.0
    discounted_subtotal = round(subtotal - box_discount, 2)

    shipping_fee = 0.0 if (discounted_subtotal >= 50.0 or discounted_subtotal == 0) else 5.0
    total_price = round(discounted_subtotal + shipping_fee, 2)

    return items, subtotal, box_discount, shipping_fee, total_price, total_count


@main.app_context_processor
def inject_globals():
    cart_items, _, _, _, cart_total, cart_count = get_cart_details()

    unread_notifications = []
    pending_review_order = None
    pending_review_products = []

    if current_user.is_authenticated:
        unread_notifications = Notification.query.filter_by(
            user_id=current_user.id, is_read=False
        ).order_by(Notification.created_at.desc()).all()

        # ვამოწმებთ, ხომ არ აქვს მომხმარებელს შეკვეთა სტატუსით "delivered", რომელიც ჯერ არ შეუფასებია
        review_notif = Notification.query.filter_by(
            user_id=current_user.id, trigger_review=True, is_read=False
        ).first()

        if review_notif and review_notif.order_id:
            order = Order.query.get(review_notif.order_id)
            if order and order.items_json:
                try:
                    items_map = json.loads(order.items_json)
                    for pid_str in items_map.keys():
                        prod = Product.query.get(int(pid_str))
                        if prod:
                            already_reviewed = Review.query.filter_by(
                                user_id=current_user.id,
                                product_id=prod.id
                            ).first()
                            if not already_reviewed:
                                pending_review_products.append(prod)
                    if pending_review_products:
                        pending_review_order = order
                    else:
                        # თუ ყველა პროდუქტი უკვე შეფასებულია, ვხურავთ ტრიგერს
                        review_notif.trigger_review = False
                        db.session.commit()
                except Exception:
                    pass

    return dict(
        cart_count=cart_count,
        mini_cart_items=cart_items,
        mini_cart_total=cart_total,
        categories=CATEGORIES,
        dietary_labels=DIETARY_LABELS,
        user_notifications=unread_notifications,
        pending_review_order=pending_review_order,
        pending_review_products=pending_review_products
    )


# --- 1. მთავარი გვერდი ---
@main.route('/')
def home():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    dietary = request.args.get('dietary', '').strip()

    products_query = Product.query.filter(Product.in_stock == True, Product.stock_qty > 0)

    if query:
        products_query = products_query.filter(
            Product.title.ilike(f'%{query}%') | Product.description.ilike(f'%{query}%')
        )
    if category:
        products_query = products_query.filter_by(category=category)
    if dietary == 'fasting':
        products_query = products_query.filter_by(dietary_tag='fasting')

    products = products_query.order_by(Product.is_featured.desc(), Product.id.asc()).all()

    user_liked_ids = []
    if current_user.is_authenticated:
        user_liked_ids = [like.product_id for like in ProductLike.query.filter_by(user_id=current_user.id).all()]

    return render_template(
        'home.html',
        products=products,
        user_liked_ids=user_liked_ids,
        selected_category=category,
        selected_dietary=dietary,
        search_query=query
    )


# --- საოჯახო ბოქსის კონსტრუქტორი ---
@main.route('/build-box', methods=['GET', 'POST'])
def build_box():
    products = Product.query.filter(Product.in_stock == True, Product.stock_qty > 0).order_by(Product.category.asc(), Product.id.asc()).all()

    if request.method == 'POST':
        selected_map = {}
        for p in products:
            qty_raw = request.form.get(f'qty_{p.id}', '0').strip()
            if qty_raw.isdigit() and int(qty_raw) > 0:
                selected_map[str(p.id)] = min(int(qty_raw), p.stock_qty or 0)

        if len(selected_map) < 3:
            flash('10%-იანი კომბო-ფასდაკლების მისაღებად აირჩიეთ მინიმუმ 3 განსხვავებული პროდუქტი.', 'warning')
            return redirect(url_for('main.build_box'))

        session['cart'] = selected_map
        session['is_box_combo'] = True
        session.modified = True
        flash('თქვენი საოჯახო ბოქსი აეწყო 10%-იანი კომბო-ფასდაკლებით!', 'success')
        return redirect(url_for('main.cart'))

    return render_template('build_box.html', products=products)


# --- 2. პროდუქტის დეტალური გვერდი ---
@main.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    reviews = Review.query.filter_by(product_id=product.id).order_by(Review.date_posted.desc()).all()
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 5.0

    is_liked = False
    can_review = False
    if current_user.is_authenticated:
        is_liked = ProductLike.query.filter_by(user_id=current_user.id, product_id=product.id).first() is not None
        has_order = Order.query.filter(
            Order.buyer_id == current_user.id,
            Order.status != 'cancelled'
        ).count() > 0
        can_review = has_order or current_user.is_admin

    related = Product.query.filter(
        Product.category == product.category,
        Product.id != product.id,
        Product.in_stock == True,
        Product.stock_qty > 0
    ).limit(3).all()

    return render_template(
        'product_detail.html',
        product=product,
        reviews=reviews,
        avg_rating=avg_rating,
        is_liked=is_liked,
        can_review=can_review,
        related=related
    )


@main.route('/product/<int:product_id>/review', methods=['POST'])
@login_required
def add_review(product_id):
    product = Product.query.get_or_404(product_id)

    has_order = Order.query.filter(
        Order.buyer_id == current_user.id,
        Order.status != 'cancelled'
    ).count() > 0

    if not has_order and not current_user.is_admin:
        flash('შეფასების დაწერა შეუძლიათ მხოლოდ იმ მომხმარებლებს, ვისაც ერთი შეკვეთა მაინც აქვთ გაფორმებული.', 'warning')
        return redirect(url_for('main.product_detail', product_id=product.id))

    rating = int(request.form.get('rating', 5))
    comment = request.form.get('comment', '').strip()

    new_review = Review(
        rating=max(1, min(5, rating)),
        comment=comment,
        product_id=product.id,
        user_id=current_user.id
    )
    db.session.add(new_review)
    db.session.commit()
    flash('მადლობა შეფასებისთვის!', 'success')
    return redirect(url_for('main.product_detail', product_id=product.id))


# --- 3. მოწონება ---
@main.route('/product/<int:product_id>/like', methods=['POST'])
@login_required
def toggle_like(product_id):
    existing = ProductLike.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        liked = False
    else:
        db.session.add(ProductLike(user_id=current_user.id, product_id=product_id))
        db.session.commit()
        liked = True
    return jsonify({'success': True, 'liked': liked})


# --- 4. კალათა ---
@main.route('/cart')
def cart():
    items, subtotal, box_discount, shipping_fee, total_price, _ = get_cart_details()
    return render_template(
        'cart.html',
        items=items,
        subtotal=subtotal,
        box_discount=box_discount,
        shipping_fee=shipping_fee,
        total_price=total_price
    )


@main.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    avail = product.stock_qty or 0
    if not product.in_stock or avail <= 0:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'ეს პროდუქტი მარაგში აღარ არის'})
        flash('ეს პროდუქტი მარაგში აღარ არის.', 'warning')
        return redirect(request.referrer or url_for('main.home'))

    qty = max(1, int(request.form.get('quantity', 1)))

    cart_dict = session.get('cart', {})
    if not isinstance(cart_dict, dict):
        cart_dict = {}

    pid_str = str(product.id)
    new_qty = min(cart_dict.get(pid_str, 0) + qty, avail)

    cart_dict[pid_str] = new_qty
    session['cart'] = cart_dict
    session.modified = True

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        cart_items, _, _, _, cart_total, total_count = get_cart_details()
        mini_items = [
            {
                'title': item['product'].title,
                'qty': item['quantity'],
                'line_total': f"{item['line_total']:.2f}"
            }
            for item in cart_items
        ]
        return jsonify({
            'success': True,
            'cart_count': total_count,
            'cart_total': f"{cart_total:.2f}",
            'mini_items': mini_items,
            'message': f'✓ „{product.title}“ დაემატა კალათაში'
        })

    flash(f'„{product.title}“ ({qty} {product.unit}) დაემატა კალათაში!', 'success')
    return redirect(request.referrer or url_for('main.home'))


@main.route('/cart/update/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    cart = session.get('cart', {})
    pid = str(product_id)
    action = request.form.get('action')
    product = Product.query.get_or_404(product_id)

    if action == 'increase':
        if cart.get(pid, 0) < product.stock_qty:
            cart[pid] = cart.get(pid, 0) + 1
    elif action == 'decrease':
        if cart.get(pid, 0) > 1:
            cart[pid] -= 1
        else:
            cart.pop(pid, None)
    elif action == 'set':
        try:
            qty = int(request.form.get('quantity', 1))
        except ValueError:
            qty = 1
        if qty <= 0:
            cart.pop(pid, None)
        else:
            cart[pid] = min(qty, product.stock_qty)
    elif action == 'remove':
        cart.pop(pid, None)

    session['cart'] = cart
    session.modified = True
    return redirect(url_for('main.cart'))


# --- 5. შეკვეთის გაფორმება ---
@main.route('/checkout', methods=['GET', 'POST'])
def checkout():
    items, subtotal, box_discount, shipping_fee, total_price, _ = get_cart_details()
    if not items:
        flash('თქვენი კალათა ცარიელია!', 'warning')
        return redirect(url_for('main.home'))

    available_bonus = round(current_user.bonus_balance, 2) if (current_user.is_authenticated and current_user.bonus_balance > 0) else 0.0

    is_first_order = True
    if current_user.is_authenticated:
        is_first_order = Order.query.filter(Order.buyer_id == current_user.id, Order.status != 'cancelled').count() == 0

    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        delivery_slot = request.form.get('delivery_slot', DELIVERY_SLOTS[0]).strip()
        notes = request.form.get('notes', '').strip()
        payment_method = request.form.get('payment_method', 'cash')
        use_bonus = True if request.form.get('use_bonus') else False
        ref_input = request.form.get('referral_code', '').strip().upper()
        receipt_file = request.files.get('receipt')

        if not customer_name or not phone or not address:
            flash('გთხოვთ შეავსოთ სახელი, ტელეფონი და მისამართი!', 'danger')
            return redirect(url_for('main.checkout'))

        receipt_filename = None
        if payment_method == 'transfer':
            if receipt_file and receipt_file.filename != '':
                receipt_filename = save_uploaded_file(receipt_file, prefix="receipt")
            else:
                flash('საბანკო გადარიცხვის არჩევისას გთხოვთ ატვირთოთ ქვითარი!', 'danger')
                return redirect(url_for('main.checkout'))

        ref_discount = 0.0
        applied_ref_code = None
        if ref_input:
            if subtotal < 20.0:
                flash('რეფერალური კოდი მოქმედებს მინიმუმ 20.00 ₾-იან შეკვეთაზე.', 'warning')
                return redirect(url_for('main.checkout'))

            referrer = User.query.filter_by(referral_code=ref_input).first()
            already_used_phone = Order.query.filter(Order.phone == phone, Order.status != 'cancelled').first() is not None
            is_self = current_user.is_authenticated and referrer and referrer.id == current_user.id

            if referrer and not is_self and is_first_order and not already_used_phone:
                ref_discount = 5.0
                applied_ref_code = ref_input
                total_price = max(0.0, round(total_price - ref_discount, 2))
            else:
                flash('რეფერალური კოდი არასწორია ან უკვე გამოყენებულია (მოქმედებს მხოლოდ პირველ შეკვეთაზე).', 'warning')
                return redirect(url_for('main.checkout'))

        bonus_deducted = 0.0
        if use_bonus and available_bonus > 0:
            bonus_deducted = round(min(available_bonus, total_price), 2)
            total_price = round(total_price - bonus_deducted, 2)
            current_user.bonus_balance = round(current_user.bonus_balance - bonus_deducted, 2)

        summary_lines = [
            f"{item['product'].title} — {item['quantity']} x {item['product'].price:.2f} ₾ = {item['line_total']:.2f} ₾"
            for item in items
        ]
        items_summary = "\n".join(summary_lines)
        items_map = {str(item['product'].id): item['quantity'] for item in items}

        sold_out_alerts = []
        for item in items:
            prod = item['product']
            ordered_qty = item['quantity']
            if prod.stock_qty is not None:
                prod.stock_qty = max(0, prod.stock_qty - ordered_qty)
                if prod.stock_qty == 0:
                    prod.in_stock = False
                    sold_out_alerts.append(f"⚠️ <b>მარაგი ამოიწურა:</b> „{prod.title}“ (დარჩა 0)")

        new_order = Order(
            buyer_id=current_user.id if current_user.is_authenticated else None,
            customer_name=customer_name,
            phone=phone,
            address=address,
            delivery_slot=delivery_slot,
            notes=notes,
            items_summary=items_summary,
            items_json=json.dumps(items_map),
            subtotal=subtotal,
            discount_amount=round(box_discount + ref_discount, 2),
            referral_code_used=applied_ref_code,
            bonus_used=bonus_deducted,
            shipping_fee=shipping_fee,
            total_price=total_price,
            payment_method=payment_method,
            receipt_image=receipt_filename,
            status='pending'
        )
        db.session.add(new_order)

        if current_user.is_authenticated:
            if not current_user.phone:
                current_user.phone = phone
            if not current_user.address:
                current_user.address = address

        db.session.commit()
        session.pop('cart', None)
        session.pop('is_box_combo', None)
        session.pop('pending_ref_code', None)

        pay_label = "საბანკო გადარიცხვა (ქვითრით)" if payment_method == 'transfer' else "ადგილზე გადახდა"
        sold_out_block = ("\n\n" + "\n".join(sold_out_alerts)) if sold_out_alerts else ""
        tg_msg = (
            f"<b>ახალი შეკვეთა #{new_order.id} — სახლური გემო</b>\n\n"
            f"<b>კლიენტი:</b> {customer_name}\n"
            f"<b>ტელეფონი:</b> {phone}\n"
            f"<b>მისამართი:</b> {address}\n"
            f"<b>დრო:</b> {delivery_slot}\n"
            f"<b>გადახდა:</b> {pay_label}\n"
            f"{f'<b>რეფერალური კოდი:</b> {applied_ref_code} (-5 ₾)' + chr(10) if applied_ref_code else ''}"
            f"{f'<b>კომენტარი:</b> {notes}' + chr(10) if notes else ''}\n"
            f"<b>პროდუქტები:</b>\n{items_summary}\n\n"
            f"<b>ჯამი: {total_price:.2f} ₾</b>"
            f"{sold_out_block}"
        )
        send_telegram_alert(tg_msg)

        flash(f'შეკვეთა #{new_order.id} მიღებულია! მალე დაგიკავშირდებით.', 'success')
        return redirect(url_for('main.order_success', order_id=new_order.id))

    saved_ref_code = session.get('pending_ref_code', '')
    return render_template(
        'checkout.html',
        items=items,
        subtotal=subtotal,
        box_discount=box_discount,
        shipping_fee=shipping_fee,
        total_price=total_price,
        available_bonus=available_bonus,
        is_first_order=is_first_order,
        delivery_slots=DELIVERY_SLOTS,
        saved_ref_code=saved_ref_code
    )

@main.route('/order-success/<int:order_id>')
def order_success(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('order_success.html', order=order)


# --- შეკვეთის გამეორება ---
@main.route('/order/<int:order_id>/reorder', methods=['POST'])
@login_required
def reorder(order_id):
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != current_user.id:
        flash('ამ შეკვეთაზე წვდომა არ გაქვთ.', 'danger')
        return redirect(url_for('main.profile'))

    if not order.items_json:
        flash('ამ შეკვეთის ავტომატური გამეორება ვერ ხერხდება.', 'warning')
        return redirect(url_for('main.profile'))

    saved_items = json.loads(order.items_json)
    cart_dict = session.get('cart', {})
    if not isinstance(cart_dict, dict):
        cart_dict = {}

    added_any = False
    for pid_str, qty in saved_items.items():
        product = Product.query.get(int(pid_str))
        if product and product.in_stock and (product.stock_qty or 0) > 0:
            cart_dict[pid_str] = min(cart_dict.get(pid_str, 0) + int(qty), product.stock_qty)
            added_any = True

    session['cart'] = cart_dict
    session.modified = True

    if added_any:
        flash(f'შეკვეთა #{order.id}-ის პროდუქტები დაემატა კალათაში!', 'success')
        return redirect(url_for('main.cart'))

    flash('შეკვეთის პროდუქტები ამჟამად მარაგში აღარ არის.', 'warning')
    return redirect(url_for('main.profile'))

@main.route('/api/check-referral')
def check_referral_api():
    code = request.args.get('code', '').strip().upper()
    if not code:
        return jsonify({'valid': False, 'message': ''})

    referrer = User.query.filter_by(referral_code=code).first()
    if not referrer:
        return jsonify({'valid': False, 'message': '✕ ასეთი რეფერალური კოდი ვერ მოიძებნა'})

    if current_user.is_authenticated and referrer.id == current_user.id:
        return jsonify({'valid': False, 'message': '✕ საკუთარი კოდის გამოყენება არ შეიძლება'})

    return jsonify({
        'valid': True,
        'message': f'✓ კოდი ვალიდურია (მოგიწვიათ: {referrer.username}) — პირველ შეკვეთაზე (20 ₾+) მიიღებთ -5.00 ₾ ფასდაკლებას!'
    })

# --- 6. ავტორიზაცია / რეგისტრაცია / პროფილი ---
@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    # თუ ბმულით შემოვიდა (?ref=CODE)
    prefill_ref = request.args.get('ref', '').strip().upper()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        ref_code_input = request.form.get('referral_code', '').strip().upper()

        if password != confirm_password:
            flash('პაროლები ერთმანეთს არ ემთხვევა!', 'danger')
            return redirect(url_for('main.register'))

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('მომხმარებელი ამ სახელით ან ელ-ფოსტით უკვე არსებობს!', 'danger')
            return redirect(url_for('main.register'))

        valid_referrer = None
        if ref_code_input:
            valid_referrer = User.query.filter_by(referral_code=ref_code_input).first()
            if not valid_referrer:
                flash('მითითებული რეფერალური კოდი არ არსებობს! შეამოწმეთ კოდი ან დატოვეთ ველი ცარიელი.', 'danger')
                return redirect(url_for('main.register'))

        new_user = User(
            username=username,
            email=email,
            phone=phone,
            password=generate_password_hash(password, method='scrypt'),
            is_admin=False
        )
        db.session.add(new_user)
        db.session.flush()
        new_user.referral_code = generate_referral_code(username, new_user.id)
        db.session.commit()

        login_user(new_user)

        if valid_referrer:
            session['pending_ref_code'] = valid_referrer.referral_code
            flash(f'რეგისტრაცია დასრულდა! თქვენი კოდია {new_user.referral_code}. მეგობრის კოდი ({valid_referrer.referral_code}) გააქტიურდა — პირველ შეკვეთაზე (20 ₾-დან) დაგაკლდებათ 5.00 ₾!', 'success')
        else:
            flash(f'რეგისტრაცია წარმატებით დასრულდა! თქვენი პირადი რეფერალური კოდია: {new_user.referral_code}', 'success')

        return redirect(url_for('main.home'))

    return render_template('register.html', prefill_ref=prefill_ref)


@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            if not user.referral_code:
                user.referral_code = generate_referral_code(user.username, user.id)
                db.session.commit()
            login_user(user)
            flash(f'კეთილი იყოს თქვენი მობრძანება, {user.username}!', 'success')
            return redirect(url_for('main.home'))
        flash('ელ-ფოსტა ან პაროლი არასწორია!', 'danger')

    return render_template('login.html')


@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('თქვენ გამოხვედით სისტემიდან.', 'info')
    return redirect(url_for('main.home'))


@main.route('/profile')
@login_required
def profile():
    if not current_user.referral_code:
        current_user.referral_code = generate_referral_code(current_user.username, current_user.id)
        db.session.commit()

    my_orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).all()
    orders_count = sum(1 for o in my_orders if o.status != 'cancelled')
    liked_products = [like.product for like in ProductLike.query.filter_by(user_id=current_user.id).all()]
    invited_count = Order.query.filter_by(referral_code_used=current_user.referral_code, referral_rewarded=True).count()

    return render_template(
        'profile.html',
        orders=my_orders,
        orders_count=orders_count,
        liked_products=liked_products,
        invited_count=invited_count
    )


# --- 7. ადმინ პანელი ---
def filter_orders_by_period(period, date_from_str='', date_to_str=''):
    now = datetime.now()
    query = Order.query.filter(Order.status != 'cancelled')

    if period == 'today':
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(Order.created_at >= start_dt)
        label = f"დღევანდელი ({now.strftime('%d.%m.%Y')})"
    elif period == 'week':
        start_dt = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(Order.created_at >= start_dt)
        label = f"ბოლო 7 დღე ({start_dt.strftime('%d.%m')} - {now.strftime('%d.%m.%Y')})"
    elif period == 'month':
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(Order.created_at >= start_dt)
        label = f"მიმდინარე თვე ({now.strftime('%m.%Y')})"
    elif period == 'custom' and date_from_str and date_to_str:
        try:
            d_from = datetime.strptime(date_from_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
            d_to = datetime.strptime(date_to_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Order.created_at >= d_from, Order.created_at <= d_to)
            label = f"{d_from.strftime('%d.%m.%Y')} - {d_to.strftime('%d.%m.%Y')}"
        except ValueError:
            period = 'all'
            label = "ყველა პერიოდი"
    else:
        period = 'all'
        label = "ყველა პერიოდი"

    filtered_orders = query.order_by(Order.created_at.desc()).all()

    products_map = {p.id: p for p in Product.query.all()}
    product_sales = {}
    total_revenue = 0.0
    total_subtotal = 0.0
    total_discounts = 0.0
    total_shipping = 0.0

    for o in filtered_orders:
        total_revenue += float(o.total_price or 0)
        total_subtotal += float(o.subtotal or 0)
        total_discounts += float(o.discount_amount or 0) + float(o.bonus_used or 0)
        total_shipping += float(o.shipping_fee or 0)

        if o.items_json:
            try:
                items_dict = json.loads(o.items_json)
                for pid_str, qty in items_dict.items():
                    pid = int(pid_str)
                    qty = int(qty)
                    prod = products_map.get(pid)
                    title = prod.title if prod else f"პროდუქტი #{pid}"
                    unit_price = float(prod.price) if prod else 0.0

                    if title not in product_sales:
                        product_sales[title] = {
                            'title': title,
                            'qty': 0,
                            'unit_price': unit_price,
                            'total_amount': 0.0
                        }
                    product_sales[title]['qty'] += qty
                    product_sales[title]['total_amount'] = round(product_sales[title]['qty'] * unit_price, 2)
            except Exception:
                pass

    sales_list = sorted(product_sales.values(), key=lambda x: x['qty'], reverse=True)

    return {
        'period': period,
        'label': label,
        'orders_count': len(filtered_orders),
        'total_units': sum(item['qty'] for item in sales_list),
        'total_subtotal': round(total_subtotal, 2),
        'total_discounts': round(total_discounts, 2),
        'total_shipping': round(total_shipping, 2),
        'total_revenue': round(total_revenue, 2),
        'sales_list': sales_list
    }


@main.route('/admin')
@login_required
@admin_required
def admin_panel():
    period = request.args.get('period', 'month')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    fin_summary = filter_orders_by_period(period, date_from, date_to)

    products = Product.query.order_by(Product.category.asc(), Product.id.asc()).all()
    orders = Order.query.order_by(Order.created_at.desc()).all()
    users_count = User.query.count()
    total_revenue = sum(o.total_price for o in orders if o.status != 'cancelled')

    active_orders = [o for o in orders if o.status in ['pending', 'preparing'] and o.items_json]
    prep_totals = {}
    for o in active_orders:
        try:
            items_map = json.loads(o.items_json)
            for pid_str, qty in items_map.items():
                prod = Product.query.get(int(pid_str))
                if prod:
                    if prod.id not in prep_totals:
                        prep_totals[prod.id] = {
                            'title': prod.title,
                            'unit': prod.unit,
                            'qty': 0
                        }
                    prep_totals[prod.id]['qty'] += int(qty)
        except Exception:
            continue

    kitchen_summary = list(prep_totals.values())

    return render_template(
        'admin.html',
        products=products,
        orders=orders,
        users_count=users_count,
        total_revenue=round(total_revenue, 2),
        kitchen_summary=kitchen_summary,
        active_orders_count=len(active_orders),
        fin_summary=fin_summary,
        date_from=date_from,
        date_to=date_to
    )


@main.route('/admin/export-finance-excel')
@login_required
@admin_required
def export_finance_excel():
    period = request.args.get('period', 'month')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    fin = filter_orders_by_period(period, date_from, date_to)

    wb = openpyxl.Workbook()

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="9B2C2C", end_color="9B2C2C", fill_type="solid")
    total_font = Font(bold=True, size=11)
    total_fill = PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin', color='D1D5DB'),
        right=Side(style='thin', color='D1D5DB'),
        top=Side(style='thin', color='D1D5DB'),
        bottom=Side(style='thin', color='D1D5DB')
    )

    ws1 = wb.active
    ws1.title = "გაყიდული პროდუქტები"

    ws1.append([f"ფინანსური რეპორტი — {fin['label']}"])
    ws1['A1'].font = Font(bold=True, size=13)
    ws1.append([])

    headers1 = ["№", "პროდუქტის დასახელება", "გაყიდული რაოდენობა", "ერთეულის ფასი (₾)", "ჯამური ღირებულება (₾)"]
    ws1.append(headers1)

    for col_idx in range(1, len(headers1) + 1):
        cell = ws1.cell(row=3, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center" if col_idx != 2 else "left", vertical="center")
        cell.border = thin_border

    for idx, item in enumerate(fin['sales_list'], start=1):
        row_num = 3 + idx
        ws1.append([idx, item['title'], item['qty'], item['unit_price'], item['total_amount']])
        for col_idx in range(1, 6):
            c = ws1.cell(row=row_num, column=col_idx)
            c.border = thin_border
            if col_idx in (4, 5):
                c.number_format = '#,##0.00'

    last_data_row = 3 + len(fin['sales_list'])
    total_row = last_data_row + 1
    ws1.append([
        "",
        "სულ გაყიდული პროდუქცია:",
        f"=SUM(C4:C{last_data_row})" if len(fin['sales_list']) > 0 else 0,
        "",
        f"=SUM(E4:E{last_data_row})" if len(fin['sales_list']) > 0 else 0
    ])
    for col_idx in range(1, 6):
        c = ws1.cell(row=total_row, column=col_idx)
        c.font = total_font
        c.fill = total_fill
        c.border = thin_border
        if col_idx == 5:
            c.number_format = '#,##0.00'

    ws2 = wb.create_sheet(title="ფინანსური შეჯამება")
    ws2.append(["მაჩვენებელი", "მნიშვნელობა"])
    for col_idx in range(1, 3):
        c = ws2.cell(row=1, column=col_idx)
        c.font = header_font
        c.fill = header_fill
        c.border = thin_border

    summary_rows = [
        ("პერიოდი", fin['label']),
        ("შეკვეთების რაოდენობა", fin['orders_count']),
        ("გაყიდული შეკვრების ჯამი", fin['total_units']),
        ("პროდუქციის საბაზისო ღირებულება (₾)", fin['total_subtotal']),
        ("გამოყენებული ფასდაკლებები და ბონუსები (₾)", fin['total_discounts']),
        ("მიტანის საფასური (₾)", fin['total_shipping']),
        ("საბოლოო შემოსავალი (₾)", fin['total_revenue']),
    ]
    for r_idx, (k, v) in enumerate(summary_rows, start=2):
        ws2.append([k, v])
        ws2.cell(row=r_idx, column=1).border = thin_border
        val_cell = ws2.cell(row=r_idx, column=2)
        val_cell.border = thin_border
        if isinstance(v, float):
            val_cell.number_format = '#,##0.00'
        if r_idx == len(summary_rows) + 1:
            ws2.cell(row=r_idx, column=1).font = total_font
            val_cell.font = total_font
            ws2.cell(row=r_idx, column=1).fill = total_fill
            val_cell.fill = total_fill

    for ws in (ws1, ws2):
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = max_len + 5

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"saxluri_gemo_finansebi_{period}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@main.route('/admin/product/quick-update/<int:product_id>', methods=['POST'])
@login_required
@admin_required
def admin_quick_update_product(product_id):
    product = Product.query.get_or_404(product_id)
    new_price = request.form.get('price', '').strip()
    new_stock = request.form.get('stock_qty', '').strip()

    if new_price:
        product.price = round(float(new_price), 2)
    if new_stock.isdigit():
        product.stock_qty = int(new_stock)
        product.in_stock = product.stock_qty > 0

    db.session.commit()
    flash(f'„{product.title}“ განახლდა (ფასი: {product.price:.2f} ₾, მარაგი: {product.stock_qty}).', 'success')
    return redirect(url_for('main.admin_panel'))

@main.route('/admin/order/<int:order_id>/print')
@login_required
@admin_required
def admin_print_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('print_receipt.html', order=order)

@main.route('/admin/product/<int:product_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    ProductLike.query.filter_by(product_id=product.id).delete()
    Review.query.filter_by(product_id=product.id).delete()
    db.session.delete(product)
    db.session.commit()
    flash(f'პროდუქტი „{product.title}“ წაიშალა.', 'info')
    return redirect(url_for('main.admin_panel'))

@main.route('/admin/export-orders')
@login_required
@admin_required
def admin_export_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow([
        'შეკვეთის #', 'თარიღი', 'კლიენტი', 'ტელეფონი', 'მისამართი',
        'დროის სლოტი', 'პროდუქტები', 'პროდუქტების ჯამი (₾)',
        'ფასდაკლება (₾)', 'ბონუსი (₾)', 'მიტანა (₾)', 'სულ გადასახდელი (₾)',
        'გადახდის მეთოდი', 'სტატუსი'
    ])

    for o in orders:
        writer.writerow([
            o.id,
            o.created_at.strftime('%Y-%m-%d %H:%M'),
            o.customer_name,
            o.phone,
            o.address,
            o.delivery_slot or '',
            o.items_summary.replace('\n', ' | '),
            f"{o.subtotal:.2f}",
            f"{(o.discount_amount or 0):.2f}",
            f"{(o.bonus_used or 0):.2f}",
            f"{o.shipping_fee:.2f}",
            f"{o.total_price:.2f}",
            o.payment_method,
            o.status
        ])

    filename = f"saxluri_gemo_orders_{datetime.now().strftime('%Y_%m_%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@main.route('/admin/product/set-stock/<int:product_id>', methods=['POST'])
@login_required
@admin_required
def admin_set_stock(product_id):
    product = Product.query.get_or_404(product_id)
    qty_raw = request.form.get('stock_qty', '').strip()
    quick_add = request.form.get('quick_add', '').strip()

    if quick_add.isdigit():
        product.stock_qty = (product.stock_qty or 0) + int(quick_add)
    elif qty_raw.isdigit():
        product.stock_qty = int(qty_raw)

    product.in_stock = product.stock_qty > 0
    db.session.commit()

    if product.in_stock:
        flash(f'„{product.title}“ მარაგშია ({product.stock_qty} {product.unit}).', 'success')
    else:
        flash(f'„{product.title}“ მოინიშნა როგორც ამოწურული (0).', 'info')

    return redirect(url_for('main.admin_panel'))


@main.route('/admin/product/<int:product_id>/price', methods=['POST'])
@login_required
def admin_set_price(product_id):
    if not current_user.is_admin:
        abort(403)
    product = Product.query.get_or_404(product_id)
    try:
        new_price = float(request.form.get('price', 0))
        if new_price >= 0:
            product.price = round(new_price, 2)
            db.session.commit()
            flash(f'„{product.title}“-ის ფასი განახლდა: {product.price:.2f} ₾', 'success')
    except ValueError:
        flash('არასწორი ფასის ფორმატი.', 'danger')
    return redirect(url_for('main.admin_panel'))


@main.route('/admin/product/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_product():
    if request.method == 'POST':
        title = request.form.get('title')
        category = request.form.get('category')
        dietary_tag = request.form.get('dietary_tag', 'standard')
        allergens = request.form.get('allergens', '').strip()
        unit = request.form.get('unit')
        weight_info = request.form.get('weight_info')
        price = float(request.form.get('price'))
        wholesale_val = request.form.get('wholesale_price')
        wholesale_price = float(wholesale_val) if wholesale_val else None
        stock_qty = int(request.form.get('stock_qty', 0) or 0)
        cooking_time = request.form.get('cooking_time', '7-8 წუთი')
        ingredients = request.form.get('ingredients')
        description = request.form.get('description')
        is_featured = True if request.form.get('is_featured') else False

        image_file = save_uploaded_file(request.files.get('image'), prefix="prod") or 'default_food.png'

        prod = Product(
            title=title,
            category=category,
            dietary_tag=dietary_tag,
            allergens=allergens,
            unit=unit,
            weight_info=weight_info,
            price=price,
            wholesale_price=wholesale_price,
            stock_qty=stock_qty,
            in_stock=stock_qty > 0,
            cooking_time=cooking_time,
            ingredients=ingredients,
            description=description,
            is_featured=is_featured,
            image_file=image_file
        )
        db.session.add(prod)
        db.session.commit()
        flash('ახალი პროდუქტი წარმატებით დაემატა!', 'success')
        return redirect(url_for('main.admin_panel'))

    return render_template('admin_product_form.html', product=None)


@main.route('/admin/product/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.title = request.form.get('title')
        product.category = request.form.get('category')
        product.dietary_tag = request.form.get('dietary_tag', 'standard')
        product.allergens = request.form.get('allergens', '').strip()
        product.unit = request.form.get('unit')
        product.weight_info = request.form.get('weight_info')
        product.price = float(request.form.get('price'))
        wholesale_val = request.form.get('wholesale_price')
        product.wholesale_price = float(wholesale_val) if wholesale_val else None
        product.stock_qty = int(request.form.get('stock_qty', 0) or 0)
        product.in_stock = product.stock_qty > 0
        product.cooking_time = request.form.get('cooking_time')
        product.ingredients = request.form.get('ingredients')
        product.description = request.form.get('description')
        product.is_featured = True if request.form.get('is_featured') else False

        new_img = save_uploaded_file(request.files.get('image'), prefix="prod")
        if new_img:
            product.image_file = new_img

        db.session.commit()
        flash('პროდუქტი განახლდა!', 'success')
        return redirect(url_for('main.admin_panel'))

    return render_template('admin_product_form.html', product=product)




@main.route('/admin/order/<int:order_id>/status', methods=['POST'])
@login_required
@admin_required
def admin_update_order(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    if new_status in ['pending', 'preparing', 'delivered', 'cancelled']:
        order.status = new_status

        if new_status == 'delivered':
            msg_parts = []
            if order.buyer_id and not order.bonus_rewarded and order.total_price > 0:
                buyer = User.query.get(order.buyer_id)
                if buyer:
                    cashback = round(order.total_price * 0.05, 2)
                    buyer.bonus_balance = round((buyer.bonus_balance or 0.0) + cashback, 2)
                    order.bonus_rewarded = True
                    msg_parts.append(f"მყიდველს დაერიცხა {cashback:.2f} ₾ ბონუსი")

            if order.referral_code_used and not order.referral_rewarded:
                referrer = User.query.filter_by(referral_code=order.referral_code_used).first()
                if referrer:
                    referrer.bonus_balance = round((referrer.bonus_balance or 0.0) + 5.0, 2)
                    order.referral_rewarded = True
                    msg_parts.append(f"{referrer.username}-ს დაერიცხა 5.00 ₾ რეფერალური ბონუსი")

            db.session.commit()
            if msg_parts:
                flash(f"შეკვეთა #{order.id} მიტანილია — {', '.join(msg_parts)}!", 'success')
            else:
                flash(f'შეკვეთა #{order.id}-ის სტატუსი განახლდა!', 'success')
            return redirect(url_for('main.admin_panel'))

        db.session.commit()
        flash(f'შეკვეთა #{order.id}-ის სტატუსი განახლდა!', 'success')
    return redirect(url_for('main.admin_panel'))


# --- 8. შეკვეთის სტატუსის შემოწმება ---
@main.route('/track-order', methods=['GET', 'POST'])
def track_order():
    orders = []
    searched = False
    if request.method == 'POST':
        order_id_raw = request.form.get('order_id', '').strip().lstrip('#').strip()
        phone_raw = request.form.get('phone', '').strip()
        searched = True

        # ვტოვებთ მხოლოდ ბოლო 9 ციფრს (რომ +995, გამოტოვებები ან ტირეები არ უშლიდეს ხელს)
        clean_digits = ''.join(ch for ch in phone_raw if ch.isdigit())[-9:]

        if clean_digits:
            all_orders = Order.query.order_by(Order.created_at.desc()).all()
            for o in all_orders:
                db_digits = ''.join(ch for ch in (o.phone or '') if ch.isdigit())[-9:]
                if db_digits == clean_digits:
                    if not order_id_raw or (order_id_raw.isdigit() and o.id == int(order_id_raw)):
                        orders.append(o)

    return render_template('track_order.html', orders=orders, searched=searched)

# --- 9. საბითუმო / B2B შეთავაზება ---
@main.route('/wholesale', methods=['GET', 'POST'])
def wholesale():
    wholesale_products = Product.query.filter(
        Product.in_stock == True,
        Product.stock_qty > 0,
        Product.wholesale_price != None
    ).all()

    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip()
        contact_person = request.form.get('contact_person', '').strip()
        phone = request.form.get('phone', '').strip()
        details = request.form.get('details', '').strip()

        if company_name and phone:
            b2b_request = Order(
                customer_name=f"[B2B საბითუმო] {company_name} ({contact_person})",
                phone=phone,
                address="საბითუმო პარტნიორობის მოთხოვნა",
                delivery_slot="შეთანხმებით",
                notes=details,
                items_summary=f"საბითუმო თანამშრომლობის მოთხოვნა: {details or 'პრაისის მოთხოვნა'}",
                subtotal=0.0,
                shipping_fee=0.0,
                total_price=0.0,
                payment_method='b2b_inquiry',
                status='pending'
            )
            db.session.add(b2b_request)
            db.session.commit()

            tg_b2b = (
                f"<b>ახალი B2B საბითუმო მოთხოვნა #{b2b_request.id}</b>\n\n"
                f"<b>ობიექტი:</b> {company_name}\n"
                f"<b>საკონტაქტო პირი:</b> {contact_person or '-'}\n"
                f"<b>ტელეფონი:</b> {phone}\n"
                f"<b>დეტალები:</b> {details or 'პრაისის მოთხოვნა'}"
            )
            send_telegram_alert(tg_b2b)

            flash('თქვენი საბითუმო მოთხოვნა მიღებულია! ჩვენი მენეჯერი მალე დაგიკავშირდებათ.', 'success')
            return redirect(url_for('main.wholesale'))

    return render_template('wholesale.html', products=wholesale_products)


# --- 10. წესები და პირობები / კონფიდენციალურობა ---
@main.route('/terms')
def terms():
    return render_template('legal.html', page_type='terms')


@main.route('/privacy')
def privacy():
    return render_template('legal.html', page_type='privacy')

@main.route('/robots.txt')
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /cart",
        f"Sitemap: {request.url_root.rstrip('/')}/sitemap.xml"
    ]
    return Response("\n".join(lines), mimetype="text/plain")

@main.route('/sitemap.xml')
def sitemap_xml():
    base = request.url_root.rstrip('/')
    urls = [
        f"{base}/",
        f"{base}/wholesale",
        f"{base}/terms",
        f"{base}/privacy"
    ]
    for p in Product.query.all():
        urls.append(f"{base}/product/{p.id}")

    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"  <url><loc>{u}</loc><changefreq>weekly</changefreq></url>")
    xml.append('</urlset>')
    return Response("\n".join(xml), mimetype="application/xml")