import os
from flask import Flask
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from ext import db, migrate, login_manager
from models import User, Product

# .env ფაილიდან გარემო ცვლადების ჩატვირთვა
load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# უსაფრთხოების გასაღები
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gemrieli_saxluri_secret_key_2026')

# მონაცემთა ბაზის კონფიგურაცია (ნაგულისხმევად SQLite, რომ PyCharm-ში პირდაპირ გაეშვას)
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_url = 'sqlite:///' + os.path.join(basedir, 'saxluri_food.db')

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ფაილების ატვირთვის საქაღალდე
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# გაფართოებების ინიციალიზაცია ext.py-დან
db.init_app(app)
migrate.init_app(app, db)
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def seed_initial_data():
    """საწყისი ადმინისა და ქართული ნახევარფაბრიკატების ჩატვირთვა ცარიელ ბაზაში"""
    if User.query.count() == 0:
        admin = User(
            username='admin',
            email='admin@saxluri.ge',
            phone='555 00 00 00',
            password=generate_password_hash('admin123', method='scrypt'),
            is_admin=True
        )
        db.session.add(admin)

    if Product.query.count() == 0:
        initial_products = [
            Product(
                title="ქალაქური ხინკალი (მწვანილით)",
                description="წვნიანი სახლური ხინკალი ახალი საქონლისა და ღორის ხორცის მიქსით, ქინძით, ოხრახუშითა და წიწაკით.",
                ingredients="საქონლის და ღორის ხორცი (70/30), ქინძი, ოხრახუში, ხახვი, წიწაკა, უმაღლესი ხარისხის ფქვილი",
                cooking_time="7-8 წუთი",
                unit="1 ცალი",
                weight_info="~95 გრ",
                price=1.40,
                wholesale_price=1.20,
                category="ხინკალი",
                is_featured=True
            ),
            Product(
                title="მთიულური ხინკალი (უმწვანილო)",
                description="ტრადიციული მთიულური რეცეპტით მომზადებული ხინკალი, მწვანილის გარეშე, ძირითა და შავი პილპილით.",
                ingredients="საქონლის და ღორის ხორცი, ხახვი, ძირა, შავი პილპილი, ფქვილი, მარილი",
                cooking_time="7-8 წუთი",
                unit="1 ცალი",
                weight_info="~95 გრ",
                price=1.50,
                wholesale_price=1.25,
                category="ხინკალი",
                is_featured=True
            ),
            Product(
                title="ხინკალი სოკოთი (სამარხვო)",
                description="არომატული ქამა სოკოს შიგთავსით, მოშუშული ხახვითა და ქორფა მწვანილებით.",
                ingredients="ქამა სოკო, ხახვი, ქინძი, ტარხუნა, სანელებლები, ფქვილი",
                cooking_time="6-7 წუთი",
                unit="1 ცალი",
                weight_info="~90 გრ",
                price=1.00,
                wholesale_price=0.80,
                category="ხინკალი",
                is_featured=False
            ),
            Product(
                title="სახლური პელმენი ხორცით",
                description="თხელ ცომში გახვეული ნაზი ხორცის პელმენი — იდეალურია როგორც მოსახარშად, ისე ქოთანში გამოსაცხობად.",
                ingredients="საქონლის და ღორის ფარში, ხახვი, კვერცხი, ფქვილი, შავი პილპილი",
                cooking_time="5-6 წუთი",
                unit="1 კგ",
                weight_info="1000 გრ",
                price=20.00,
                wholesale_price=17.00,
                category="პელმენი და ვარენიკი",
                is_featured=True
            ),
            Product(
                title="ვარენიკი კარტოფილით (სამარხვო)",
                description="ნაზი კარტოფილის პიურეთი და ოქროსფრად მოშუშული ხახვით შეზავებული ვარენიკი.",
                ingredients="კარტოფილი, მოშუშული ხახვი, მცენარეული ზეთი, ფქვილი, მარილი",
                cooking_time="5 წუთი",
                unit="1 კგ",
                weight_info="1000 გრ",
                price=12.50,
                wholesale_price=10.00,
                category="პელმენი და ვარენიკი",
                is_featured=False
            ),
            Product(
                title="ვარენიკი იმერული ხაჭოთი",
                description="ნატურალური სოფლის ხაჭოთი მომზადებული ტკბილი ან ოდნავ მარილიანი ვარენიკი.",
                ingredients="სოფლის ხაჭო, კვერცხი, ფქვილი, ვანილი/მარილი",
                cooking_time="5 წუთი",
                unit="1 კგ",
                weight_info="1000 გრ",
                price=14.50,
                wholesale_price=11.50,
                category="პელმენი და ვარენიკი",
                is_featured=False
            ),
            Product(
                title="ქაბაბი (საქონლის და ღორის)",
                description="წვნიანი ქაბაბი კოწახურითა და ქართული სანელებლებით — მზადაა ტაფაზე ან მაყალზე შესაწვავად.",
                ingredients="საქონლის და ღორის ხორცი, დუმა, ხახვი, კოწახური, ძირა",
                cooking_time="10-12 წუთი",
                unit="1 ცალი",
                weight_info="~150 გრ",
                price=4.00,
                wholesale_price=3.40,
                category="ხორცეული",
                is_featured=True
            ),
            Product(
                title="სახლური კატლეტი",
                description="ოჯახური რეცეპტით შეზავებული რბილი და წვნიანი კატლეტი.",
                ingredients="საქონლის და ღორის ხორცი, ხახვი, ნიორი, ქინძი, პურის გული, კვერცხი",
                cooking_time="12-15 წუთი",
                unit="1 კგ",
                weight_info="1000 გრ (~10-11 ცალი)",
                price=21.50,
                wholesale_price=18.00,
                category="ხორცეული",
                is_featured=False
            ),
            Product(
                title="ტოლმა ვაზის ფოთოლში",
                description="ნორჩ ვაზის ფოთოლში გახვეული არომატული ფარში ბრინჯითა და მწვანილებით.",
                ingredients="ვაზის ფოთოლი, საქონლის და ღორის ფარში, ბრინჯი, ქინძი, რეჰანი, პიტნა",
                cooking_time="25-30 წუთი",
                unit="1 კგ",
                weight_info="1000 გრ",
                price=22.50,
                wholesale_price=19.00,
                category="ხორცეული",
                is_featured=False
            ),
            Product(
                title="ბლინები ხორცით",
                description="თხელ, ოქროსფერ ბლინებში გახვეული შეზავებული მოხარშული ხორცის ფარში.",
                ingredients="რძე, კვერცხი, ფქვილი, საქონლის ფარში, ხახვი, შავი პილპილი",
                cooking_time="4-5 წუთი (შებრაწვა)",
                unit="1 ცალი",
                weight_info="~85 გრ",
                price=1.40,
                wholesale_price=1.15,
                category="ბლინები",
                is_featured=False
            ),
            Product(
                title="ბლინები ყველით / ხაჭოთი",
                description="სულგუნისა და იმერული ყველის მიქსით სავსე ნაზი ბლინები.",
                ingredients="რძე, კვერცხი, ფქვილი, იმერული ყველი, სულგუნი",
                cooking_time="4-5 წუთი (შებრაწვა)",
                unit="1 ცალი",
                weight_info="~85 გრ",
                price=1.25,
                wholesale_price=1.00,
                category="ბლინები",
                is_featured=False
            ),
            Product(
                title="სეტი „საოჯახო კლასიკა“ (7% ფასდაკლებით)",
                description="20 ქალაქური ხინკალი + 1 კგ პელმენი + 10 ბლინი ხორცით. იდეალური მარაგი მთელი ოჯახისთვის!",
                ingredients="20ც ხინკალი, 1კგ პელმენი, 10ც ხორცის ბლინი",
                cooking_time="5-8 წუთი",
                unit="1 სეტი",
                weight_info="~3.8 კგ ჯამში",
                price=57.60,
                wholesale_price=52.00,
                category="საოჯახო სეტები",
                is_featured=True
            ),
        ]
        db.session.bulk_save_objects(initial_products)
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_initial_data()

# Blueprint-ის რეგისტრაცია
from routes import main
app.register_blueprint(main)

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 't']
    app.run(debug=debug_mode, port=5000)