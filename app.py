import os
import io
from datetime import datetime
from dotenv import load_dotenv

import pandas as pd
from fpdf import FPDF
from flask import (Flask, render_template, request, redirect, url_for, flash, 
                   send_file)
from flask_login import (LoginManager, UserMixin, login_user, login_required, 
                         logout_user, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, Transaction

# Load environment variables from .env file
load_dotenv()

# --- FLASK APP INITIALIZATION ---
app = Flask(__name__)

# --- CONFIGURATION ---
# Use the SECRET_KEY from environment variables for security, with a fallback for local dev
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-for-development')
# Use the DATABASE_URL from Render, with a fallback to a local SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///finance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- EXTENSION INITIALIZATIONS ---
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Redirect to login page if user is not authenticated

# --- USER LOADER FOR FLASK-LOGIN ---
@login_manager.user_loader
def load_user(user_id):
    """Flask-Login function to retrieve a user from the database."""
    return User.query.get(int(user_id))

# --- APPLICATION ROUTES ---

@app.route('/')
@login_required
def dashboard():
    """Displays the main dashboard with financial summaries and recent transactions."""
    total_income = db.session.query(db.func.sum(Transaction.amount)).filter_by(type='Income').scalar() or 0.0
    total_expense = db.session.query(db.func.sum(Transaction.amount)).filter_by(type='Expense').scalar() or 0.0
    balance = total_income - total_expense
    
    # Fetch only the 10 most recent transactions for the dashboard overview
    recent_transactions = Transaction.query.order_by(Transaction.date.desc()).limit(10).all()
    
    return render_template('dashboard.html', 
                           income=total_income, 
                           expense=total_expense, 
                           balance=balance, 
                           transactions=recent_transactions)

@app.route('/transactions')
@login_required
def list_transactions():
    """Displays a full, paginated list of all transactions."""
    # In a real app with lots of data, you would use pagination here like:
    # page = request.args.get('page', 1, type=int)
    # all_tx = Transaction.query.order_by(Transaction.date.desc()).paginate(page=page, per_page=25)
    
    # For now, we'll fetch all transactions, sorted by most recent
    all_tx = Transaction.query.order_by(Transaction.date.desc()).all()
    
    return render_template('transactions.html', transactions=all_tx)


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_transaction():
    """Handles the form for adding a new transaction."""
    if request.method == 'POST':
        try:
            date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
            trans_type = request.form.get('type')
            category = request.form.get('category')
            description = request.form.get('description')
            amount = float(request.form.get('amount'))

            if amount <= 0:
                flash('Amount must be a positive number.', 'warning')
                return render_template('add_transaction.html')

            new_trans = Transaction(date=date, 
                                    type=trans_type, 
                                    category=category, 
                                    description=description, 
                                    amount=amount, 
                                    user_id=current_user.id)
            db.session.add(new_trans)
            db.session.commit()
            flash('Transaction added successfully!', 'success')
            return redirect(url_for('dashboard'))
        except ValueError:
            flash('Invalid data provided. Please check your inputs.', 'danger')
            return render_template('add_transaction.html')
        
    return render_template('add_transaction.html')

# --- AUTHENTICATION ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password. Please try again.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Handles user logout."""
    logout_user()
    return redirect(url_for('login'))

# --- REPORTING ROUTES ---

@app.route('/download/csv')
@login_required
def download_csv():
    """Generates a CSV report of all transactions and serves it for download."""
    query = Transaction.query.all()
    df = pd.DataFrame([(d.date, d.type, d.category, d.description, d.amount) for d in query],
                      columns=['Date', 'Type', 'Category', 'Description', 'Amount'])
    
    # Create an in-memory text buffer to hold the CSV data
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, encoding='utf-8')
    buffer.seek(0)

    # Use send_file to send the buffer's content as a downloadable file
    return send_file(
        io.BytesIO(buffer.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"piwc_giessen_transactions_{datetime.now().strftime('%Y-%m-%d')}.csv"
    )

# --- COMMAND LINE INTERFACE (CLI) COMMANDS ---

@app.cli.command("init-db")
def init_db_command():
    """Creates the database tables and a default admin user."""
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin')
            # IMPORTANT: Change this password in a secure way or after the first login!
            # You can prompt for it or use an environment variable.
            admin_password = os.environ.get('ADMIN_PASSWORD', 'your-strong-initial-password')
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"Database initialized and user 'admin' created.")
        else:
            print("Database already initialized and 'admin' user exists.")

# --- MAIN EXECUTION BLOCK ---

if __name__ == '__main__':
    # This block is for local development only.
    # Gunicorn (the production server) will not run this.
    with app.app_context():
        db.create_all() # Ensures DB exists for local runs
    app.run(debug=True)