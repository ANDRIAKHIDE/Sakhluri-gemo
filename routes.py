import os
import io
import csv
import json
import uuid
import urllib.request
import urllib.parse
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session, jsonify, Response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from ext import db
from models import User, Product, Order, ProductLike, Review

main = Blueprint('main', __name__)

CATEGORIES = ['ხინკალი', 'პელმენი და ვარენიკი', 'ხორცეული', 'ბლინები', 'საოჯახო სეტები']

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
    _, _, _, _, _, cart_count = get_cart_details()
    return dict(cart_count=cart_count, categories=CATEGORIES, dietary_labels=DIETARY_LABELS)


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
    if current_user.is_authenticated:
        is_liked = ProductLike.query.filter_by(user_id=current_user.id, product_id=product.id).first() is not None

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
        related=related
    )


@main.route('/product/<int:product_id>/review', methods=['POST'])
@login_required
def add_review(product_id):
    product = Product.query.get_or_404(product_id)
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
        _, _, _, _, _, total_count = get_cart_details()
        return jsonify({
            'success': True,
            'cart_count': total_count,
            'message': f'„{product.title}“ დაემატა კალათაში (მარაგშია {avail} {product.unit})'
        })

    flash(f'„{product.title}“ ({qty} {product.unit}) დაემატა კალათაში!', 'success')
    return redirect(request.referrer or url_for('main.home'))


@main.route('/cart/update/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    action = request.form.get('action')
    cart_dict = session.get('cart', {})
    pid_str = str(product_id)
    product = Product.query.get(product_id)

    if pid_str in cart_dict:
        if action == 'increase':
            max_allowed = (product.stock_qty or 0) if product else 0
            if cart_dict[pid_str] < max_allowed:
                cart_dict[pid_str] += 1
        elif action == 'decrease':
            cart_dict[pid_str] -= 1
            if cart_dict[pid_str] <= 0:
                del cart_dict[pid_str]
        elif action == 'remove':
            del cart_dict[pid_str]

    if len(cart_dict) < 3:
        session['is_box_combo'] = False

    session['cart'] = cart_dict
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
        if ref_input and subtotal >= 20.0:
            referrer = User.query.filter_by(referral_code=ref_input).first()
            already_used_phone = Order.query.filter(Order.phone == phone, Order.status != 'cancelled').first() is not None
            is_self = current_user.is_authenticated and referrer and referrer.id == current_user.id

            if referrer and not is_self and is_first_order and not already_used_phone:
                ref_discount = 5.0
                applied_ref_code = ref_input
                total_price = max(0.0, round(total_price - ref_discount, 2))
            else:
                flash('რეფერალური კოდი არასწორია ან უკვე გამოყენებულია (მოქმედებს მხოლოდ პირველ შეკვეთაზე 20 ₾-დან).', 'warning')
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

    return render_template(
        'checkout.html',
        items=items,
        subtotal=subtotal,
        box_discount=box_discount,
        shipping_fee=shipping_fee,
        total_price=total_price,
        available_bonus=available_bonus,
        is_first_order=is_first_order,
        delivery_slots=DELIVERY_SLOTS
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


# --- 6. ავტორიზაცია / რეგისტრაცია / პროფილი ---
@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('პაროლები ერთმანეთს არ ემთხვევა!', 'danger')
            return redirect(url_for('main.register'))

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('მომხმარებელი ამ სახელით ან ელ-ფოსტით უკვე არსებობს!', 'danger')
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
        flash('რეგისტრაცია წარმატებით დასრულდა!', 'success')
        return redirect(url_for('main.home'))

    return render_template('register.html')


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
    liked_products = [like.product for like in ProductLike.query.filter_by(user_id=current_user.id).all()]
    invited_count = Order.query.filter_by(referral_code_used=current_user.referral_code, referral_rewarded=True).count()
    return render_template(
        'profile.html',
        orders=my_orders,
        liked_products=liked_products,
        invited_count=invited_count
    )


# --- 7. ადმინ პანელი ---
@main.route('/admin')
@login_required
@admin_required
def admin_panel():
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
        active_orders_count=len(active_orders)
    )


@main.route('/admin/order/<int:order_id>/print')
@login_required
@admin_required
def admin_print_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('print_receipt.html', order=order)


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


@main.route('/admin/product/delete/<int:product_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('პროდუქტი წაიშალა.', 'info')
    return redirect(url_for('main.admin_panel'))


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
    order = None
    searched = False
    if request.method == 'POST':
        searched = True
        order_id_raw = request.form.get('order_id', '').strip().replace('#', '')
        phone = request.form.get('phone', '').strip()

        if order_id_raw.isdigit() and phone:
            found = Order.query.get(int(order_id_raw))
            clean_input = phone.replace(' ', '')
            if found and (clean_input in found.phone.replace(' ', '') or found.phone.replace(' ', '') == clean_input):
                order = found

        if not order:
            flash('მითითებული ნომრითა და ტელეფონით შეკვეთა ვერ მოიძებნა.', 'warning')

    return render_template('track_order.html', order=order, searched=searched)


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