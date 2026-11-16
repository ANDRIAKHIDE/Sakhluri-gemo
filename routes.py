import os
import uuid
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from ext import db
from models import User, Product, Order, ProductLike, Review

main = Blueprint('main', __name__)

CATEGORIES = ['ხინკალი', 'პელმენი და ვარენიკი', 'ხორცეული', 'ბლინები', 'საოჯახო სეტები']


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


# --- კალათის დამხმარე ფუნქცია ---
def get_cart_details():
    raw_cart = session.get('cart', {})
    # მიგრაცია თუ ძველი სია იყო სესიაში
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
        if product and qty > 0:
            line_total = round(product.price * qty, 2)
            subtotal += line_total
            total_count += qty
            items.append({
                'product': product,
                'quantity': qty,
                'line_total': line_total
            })

    subtotal = round(subtotal, 2)
    # 50 ლარიდან უფასო მიტანა!
    shipping_fee = 0.0 if (subtotal >= 50.0 or subtotal == 0) else 5.0
    total_price = round(subtotal + shipping_fee, 2)

    return items, subtotal, shipping_fee, total_price, total_count


@main.app_context_processor
def inject_globals():
    _, _, _, _, cart_count = get_cart_details()
    return dict(cart_count=cart_count, categories=CATEGORIES)


# --- 1. მთავარი გვერდი ---
@main.route('/')
def home():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    products_query = Product.query.filter_by(in_stock=True)

    if query:
        products_query = products_query.filter(
            Product.title.ilike(f'%{query}%') | Product.description.ilike(f'%{query}%')
        )
    if category:
        products_query = products_query.filter_by(category=category)

    products = products_query.order_by(Product.is_featured.desc(), Product.id.asc()).all()

    user_liked_ids = []
    if current_user.is_authenticated:
        user_liked_ids = [like.product_id for like in ProductLike.query.filter_by(user_id=current_user.id).all()]

    return render_template(
        'home.html',
        products=products,
        user_liked_ids=user_liked_ids,
        selected_category=category,
        search_query=query
    )


# --- 2. პროდუქტის დეტალური გვერდი და შეფასებები ---
@main.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    reviews = Review.query.filter_by(product_id=product.id).order_by(Review.date_posted.desc()).all()
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 5.0

    is_liked = False
    if current_user.is_authenticated:
        is_liked = ProductLike.query.filter_by(user_id=current_user.id, product_id=product.id).first() is not None

    related = Product.query.filter(Product.category == product.category, Product.id != product.id).limit(3).all()
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


# --- 3. მოწონება (AJAX LIKE / UNLIKE) ---
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


# --- 4. კალათა (CART) ---
@main.route('/cart')
def cart():
    items, subtotal, shipping_fee, total_price, _ = get_cart_details()
    return render_template(
        'cart.html',
        items=items,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total_price=total_price
    )


@main.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    qty = int(request.form.get('quantity', 1))
    # ხინკალზე/ბლინზე მინიმუმ 10 ცალის ან 1-ის დამატება მომხმარებლის არჩევანით
    qty = max(1, qty)

    cart_dict = session.get('cart', {})
    if not isinstance(cart_dict, dict):
        cart_dict = {}

    pid_str = str(product.id)
    cart_dict[pid_str] = cart_dict.get(pid_str, 0) + qty
    session['cart'] = cart_dict
    session.modified = True

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        _, _, _, _, total_count = get_cart_details()
        return jsonify({'success': True, 'cart_count': total_count, 'message': f'„{product.title}“ დაემატა კალათაში!'})

    flash(f'„{product.title}“ ({qty} {product.unit}) დაემატა კალათაში!', 'success')
    return redirect(request.referrer or url_for('main.home'))


@main.route('/cart/update/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    action = request.form.get('action')
    cart_dict = session.get('cart', {})
    pid_str = str(product_id)

    if pid_str in cart_dict:
        if action == 'increase':
            cart_dict[pid_str] += 1
        elif action == 'decrease':
            cart_dict[pid_str] -= 1
            if cart_dict[pid_str] <= 0:
                del cart_dict[pid_str]
        elif action == 'remove':
            del cart_dict[pid_str]

    session['cart'] = cart_dict
    session.modified = True
    return redirect(url_for('main.cart'))


# --- 5. შეკვეთის გაფორმება (CHECKOUT) ---
@main.route('/checkout', methods=['GET', 'POST'])
def checkout():
    items, subtotal, shipping_fee, total_price, _ = get_cart_details()
    if not items:
        flash('თქვენი კალათა ცარიელია!', 'warning')
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        notes = request.form.get('notes', '').strip()
        payment_method = request.form.get('payment_method', 'cash')
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

        summary_lines = [
            f"{item['product'].title} — {item['quantity']} x {item['product'].price:.2f} ₾ = {item['line_total']:.2f} ₾"
            for item in items
        ]
        items_summary = "\n".join(summary_lines)

        new_order = Order(
            buyer_id=current_user.id if current_user.is_authenticated else None,
            customer_name=customer_name,
            phone=phone,
            address=address,
            notes=notes,
            items_summary=items_summary,
            subtotal=subtotal,
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

        flash(f'შეკვეთა #{new_order.id} მიღებულია! მალე დაგიკავშირდებით.', 'success')
        return redirect(url_for('main.order_success', order_id=new_order.id))

    return render_template(
        'checkout.html',
        items=items,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total_price=total_price
    )


@main.route('/order-success/<int:order_id>')
def order_success(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('order_success.html', order=order)


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

        is_first = User.query.count() == 0
        new_user = User(
            username=username,
            email=email,
            phone=phone,
            password=generate_password_hash(password, method='scrypt'),
            is_admin=is_first
        )
        db.session.add(new_user)
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
    my_orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).all()
    liked_products = [like.product for like in ProductLike.query.filter_by(user_id=current_user.id).all()]
    return render_template('profile.html', orders=my_orders, liked_products=liked_products)


# --- 7. ადმინ პანელი (პროდუქტებისა და შეკვეთების მართვა) ---
@main.route('/admin')
@login_required
@admin_required
def admin_panel():
    products = Product.query.order_by(Product.id.desc()).all()
    orders = Order.query.order_by(Order.created_at.desc()).all()
    users_count = User.query.count()
    total_revenue = sum(o.total_price for o in orders if o.status != 'cancelled')
    return render_template(
        'admin.html',
        products=products,
        orders=orders,
        users_count=users_count,
        total_revenue=round(total_revenue, 2)
    )


@main.route('/admin/product/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_product():
    if request.method == 'POST':
        title = request.form.get('title')
        category = request.form.get('category')
        unit = request.form.get('unit')
        weight_info = request.form.get('weight_info')
        price = float(request.form.get('price'))
        wholesale_val = request.form.get('wholesale_price')
        wholesale_price = float(wholesale_val) if wholesale_val else None
        cooking_time = request.form.get('cooking_time', '7-8 წუთი')
        ingredients = request.form.get('ingredients')
        description = request.form.get('description')
        is_featured = True if request.form.get('is_featured') else False

        image_file = save_uploaded_file(request.files.get('image'), prefix="prod") or 'default_food.png'

        prod = Product(
            title=title,
            category=category,
            unit=unit,
            weight_info=weight_info,
            price=price,
            wholesale_price=wholesale_price,
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
        product.unit = request.form.get('unit')
        product.weight_info = request.form.get('weight_info')
        product.price = float(request.form.get('price'))
        wholesale_val = request.form.get('wholesale_price')
        product.wholesale_price = float(wholesale_val) if wholesale_val else None
        product.cooking_time = request.form.get('cooking_time')
        product.ingredients = request.form.get('ingredients')
        product.description = request.form.get('description')
        product.is_featured = True if request.form.get('is_featured') else False
        product.in_stock = True if request.form.get('in_stock') else False

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
        db.session.commit()
        flash(f'შეკვეთა #{order.id}-ის სტატუსი განახლდა!', 'success')
    return redirect(url_for('main.admin_panel'))
