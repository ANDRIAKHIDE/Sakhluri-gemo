import os
from dotenv import load_dotenv
from flask import Flask
from werkzeug.security import generate_password_hash
from ext import db, login_manager

load_dotenv()


def create_app():
    app = Flask(__name__)

    base_dir = os.path.abspath(os.path.dirname(__file__))
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'saxluri_gemo_default_secret_key')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_dir, 'saxluri_food.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    upload_folder = os.path.join(base_dir, 'static', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = upload_folder

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    login_manager.login_message = 'გთხოვთ გაიაროთ ავტორიზაცია.'
    login_manager.login_message_category = 'info'

    from models import User, Product
    from routes import main

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(main)

    with app.app_context():
        db.create_all()
        ensure_admin_account(User)
        seed_admin_catalog(Product)

    return app


def ensure_admin_account(User):
    admin_email = "khidesheliandria@gmail.com"
    admin_user = User.query.filter_by(email=admin_email).first()

    if not admin_user:
        admin_user = User(
            username="Andria",
            email=admin_email,
            password=generate_password_hash("Andria2007$", method='scrypt'),
            is_admin=True,
            referral_code="ANDRIA5"
        )
        db.session.add(admin_user)
    else:
        admin_user.is_admin = True
        admin_user.password = generate_password_hash("Andria2007$", method='scrypt')
        if not admin_user.referral_code:
            admin_user.referral_code = "ANDRIA5"

    db.session.commit()


def seed_admin_catalog(Product):
    if Product.query.count() > 0:
        return

    # გამზადებული მენიუ ადმინ-პანელში (საწყისი რაოდენობა 0 — მთავარ გვერდზე გამოჩნდება მას შემდეგ, რაც მარაგს ჩაწერ)
    catalog_templates = [
        Product(
            title="ქალაქური ხინკალი (საქონელი და ღორი)",
            category="ხინკალი",
            dietary_tag="standard",
            allergens="გლუტენი (ხორბლის ფქვილი)",
            unit="10 ცალი",
            weight_info="დაახლ. 900 გრ",
            price=14.00,
            wholesale_price=11.50,
            cooking_time="8-9 წუთი",
            ingredients="საქონლის ხორცი, ღორის ხორცი, ხახვი, ქინძი, წიწაკა, უმაღლესი ხარისხის ფქვილი",
            description="წვნიანი, არომატული ქალაქური ხინკალი ახალი მწვანილითა და ნატურალური ხორცით.",
            image_file="https://images.unsplash.com/photo-1625220194771-7ebdea0b70b9?auto=format&fit=crop&w=900&q=80",
            is_featured=True,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="მთიულური ხინკალი (მწვანილის გარეშე)",
            category="ხინკალი",
            dietary_tag="standard",
            allergens="გლუტენი (ხორბლის ფქვილი)",
            unit="10 ცალი",
            weight_info="დაახლ. 900 გრ",
            price=14.50,
            wholesale_price=12.00,
            cooking_time="8-9 წუთი",
            ingredients="საქონლის ხორცი, ღორის ხორცი, ხახვი, ძირა, წიწაკა, ფქვილი",
            description="ტრადიციული მთიულური რეცეპტით, ძირასა და ნატურალური ხორცის მდიდარი გემოთი.",
            image_file="https://images.unsplash.com/photo-1625220194771-7ebdea0b70b9?auto=format&fit=crop&w=900&q=80",
            is_featured=False,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="სოკოს ხინკალი (სამარხვო)",
            category="ხინკალი",
            dietary_tag="fasting",
            allergens="გლუტენი (ხორბლის ფქვილი)",
            unit="10 ცალი",
            weight_info="დაახლ. 850 გრ",
            price=12.00,
            wholesale_price=9.50,
            cooking_time="7-8 წუთი",
            ingredients="ქამა სოკო, ხახვი, ქინძი, ტარხუნა, შავი პილპილი, ფქვილი",
            description="არომატული, სამარხვო სოკოს ხინკალი ახალი მწვანილით.",
            image_file="https://images.unsplash.com/photo-1625220194771-7ebdea0b70b9?auto=format&fit=crop&w=900&q=80",
            is_featured=False,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="სახლური პელმენი საქონლის ხორცით",
            category="პელმენი და ვარენიკი",
            dietary_tag="standard",
            allergens="გლუტენი, კვერცხი",
            unit="1 კგ",
            weight_info="დაახლ. 65-70 ცალი",
            price=18.50,
            wholesale_price=15.00,
            cooking_time="6-7 წუთი",
            ingredients="საქონლის რბილი ხორცი, ხახვი, კვერცხი, ფქვილი, მარილი",
            description="თხელ ცომში მოხვეული ნაზი პელმენი ნატურალური საქონლის ხორცით.",
            image_file="https://images.unsplash.com/photo-1541696432-82c6da8ce7bf?auto=format&fit=crop&w=900&q=80",
            is_featured=True,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="ვარენიკი სოკოთი და კარტოფილით (სამარხვო)",
            category="პელმენი და ვარენიკი",
            dietary_tag="fasting",
            allergens="გლუტენი",
            unit="1 კგ",
            weight_info="დაახლ. 45 ცალი",
            price=13.00,
            wholesale_price=10.50,
            cooking_time="5-6 წუთი",
            ingredients="კარტოფილი, ქამა სოკო, მოშუშული ხახვი, შავი პილპილი, ფქვილი",
            description="სამარხვო, ნოყიერი ვარენიკები ოქროსფრად მოშუშული სოკოთი და ხახვით.",
            image_file="https://images.unsplash.com/photo-1583032015879-e5022cb87c3b?auto=format&fit=crop&w=900&q=80",
            is_featured=False,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="ვარენიკი სულგუნითა და ნადუღით",
            category="პელმენი და ვარენიკი",
            dietary_tag="standard",
            allergens="გლუტენი, რძის პროდუქტი, კვერცხი",
            unit="1 კგ",
            weight_info="დაახლ. 45 ცალი",
            price=17.00,
            wholesale_price=14.00,
            cooking_time="5-6 წუთი",
            ingredients="სოფლის სულგუნი, ნადუღი, პიტნა, კვერცხი, ფქვილი",
            description="ნაზ ცომში მოხვეული სულგუნისა და პიტნის ვარენიკი.",
            image_file="https://images.unsplash.com/photo-1583032015879-e5022cb87c3b?auto=format&fit=crop&w=900&q=80",
            is_featured=False,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="ხორცის ბლინები (შემწვარი ნახევარფაბრიკატი)",
            category="ბლინები",
            dietary_tag="standard",
            allergens="გლუტენი, რძე, კვერცხი",
            unit="10 ცალი",
            weight_info="დაახლ. 850 გრ",
            price=15.00,
            wholesale_price=12.50,
            cooking_time="4-5 წუთი ტაფაზე",
            ingredients="საქონლის მოხარშული ხორცი, ბრინჯი, რძე, კვერცხი, ფქვილი, სუნელები",
            description="ოქროსფერი, თხელი ბლინები მდიდარი ხორცის შიგთავსით.",
            image_file="https://images.unsplash.com/photo-1519676867240-f03562e64548?auto=format&fit=crop&w=900&q=80",
            is_featured=True,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="ხაჭოს ბლინები ქიშმიშით და ვანილით",
            category="ბლინები",
            dietary_tag="standard",
            allergens="გლუტენი, რძის პროდუქტი, კვერცხი",
            unit="10 ცალი",
            weight_info="დაახლ. 800 გრ",
            price=13.50,
            wholesale_price=11.00,
            cooking_time="4-5 წუთი ტაფაზე",
            ingredients="სოფლის ხაჭო, ქიშმიში, ვანილი, კვერცხი, რძე, ფქვილი",
            description="ნაზი, ტკბილი ბლინები სოფლის ხაჭოთი — მზადდება კარაქში 4 წუთში.",
            image_file="https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?auto=format&fit=crop&w=900&q=80",
            is_featured=False,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="სახლური კატლეტი (საქონელი და ღორი)",
            category="ხორცეული",
            dietary_tag="standard",
            allergens="გლუტენი, კვერცხი",
            unit="1 კგ",
            weight_info="10-12 ცალი",
            price=21.00,
            wholesale_price=17.50,
            cooking_time="10-12 წუთი ტაფაზე",
            ingredients="საქონლისა და ღორის რბილი ხორცი, ხახვი, ნიორი, კვერცხი, ორცხობილა",
            description="წვნიანი, ოჯახური კატლეტები ოქროსფერ საფანელში.",
            image_file="https://images.unsplash.com/photo-1529042410759-befb1204b468?auto=format&fit=crop&w=900&q=80",
            is_featured=False,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="ქაბაბი შამფურისთვის / ტაფისთვის",
            category="ხორცეული",
            dietary_tag="standard",
            allergens="არ შეიცავს",
            unit="1 კგ",
            weight_info="6-7 ცალი",
            price=22.00,
            wholesale_price=18.50,
            cooking_time="12-15 წუთი",
            ingredients="საქონლისა და ღორის ხორცი, კოწახური, ხახვი, სუნელები",
            description="ნამდვილი ქართული ქაბაბი კოწახურითა და არომატული სუნელებით.",
            image_file="https://images.unsplash.com/photo-1555939594-58d7cb561ad1?auto=format&fit=crop&w=900&q=80",
            is_featured=False,
            in_stock=False,
            stock_qty=0
        ),
        Product(
            title="საოჯახო სეტი „დიდი სუფრა“",
            category="საოჯახო სეტები",
            dietary_tag="standard",
            allergens="გლუტენი, რძე, კვერცხი",
            unit="1 სეტი",
            weight_info="20 ხინკალი + 1 კგ პელმენი + 10 ბლინი",
            price=55.00,
            wholesale_price=48.00,
            cooking_time="7-9 წუთი",
            ingredients="ქალაქური ხინკალი 20ც, საქონლის პელმენი 1კგ, ხორცის ბლინები 10ც",
            description="სრული საოჯახო მარაგი მთელი კვირისთვის — უფასო მიტანით თბილისში.",
            image_file="https://images.unsplash.com/photo-1625220194771-7ebdea0b70b9?auto=format&fit=crop&w=900&q=80",
            is_featured=True,
            in_stock=False,
            stock_qty=0
        )
    ]

    db.session.add_all(catalog_templates)
    db.session.commit()


if __name__ == '__main__':
    app = create_app()
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    app.run(debug=debug_mode)