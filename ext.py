from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message = 'ამ გვერდზე შესასვლელად გთხოვთ გაიაროთ ავტორიზაცია.'
login_manager.login_message_category = 'warning'