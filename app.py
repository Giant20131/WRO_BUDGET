import os
import uuid
import csv
import io
import requests
from datetime import datetime, date, time
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, session, flash, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environmental variables from .env file
load_dotenv()

# Initialize Flask application
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'wro-budget-manager-super-secret-key-12345')

# Database configuration (dynamic Supabase PostgreSQL or fallback SQLite)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_url = os.environ.get('DATABASE_URL')
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'wro_budget.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# File uploads configuration
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'proofs')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload size
ALLOWED_EXTENSIONS = {'pdf'}

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
csrf = CSRFProtect(app)

# ---------------------------------------------------------
# Database Models
# ---------------------------------------------------------

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin' or 'teammate'
    allocated_budget = db.Column(db.Float, default=0.0)

    buys = db.relationship('Buy', backref='user', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"

class Buy(db.Model):
    __tablename__ = 'buys'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    pdf_proof_path = db.Column(db.String(255), nullable=True)

    components = db.relationship('Component', backref='buy', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Buy ID: {self.id}, Total: {self.total_amount}>"

class Component(db.Model):
    __tablename__ = 'components'
    id = db.Column(db.Integer, primary_key=True)
    buy_id = db.Column(db.Integer, db.ForeignKey('buys.id', ondelete='CASCADE'), nullable=False)
    component_name = db.Column(db.String(150), nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f"<Component {self.component_name} (Qty: {self.quantity})>"

# ---------------------------------------------------------
# Authentication Guards
# ---------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------------------------
# Forms
# ---------------------------------------------------------

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign In')

# Helper function to check file extension
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Supabase storage helper functions
def upload_to_supabase_storage(file_data, filename, content_type='application/pdf'):
    """
    Uploads a file to Supabase Storage bucket 'proofs'.
    Returns the public URL if successful, or None if failed.
    """
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_KEY')
    if not supabase_url or not supabase_key:
        return None
    
    supabase_url = supabase_url.rstrip('/')
    bucket = 'proofs'
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{filename}"
    
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey": supabase_key,
        "Content-Type": content_type
    }
    
    try:
        response = requests.post(upload_url, headers=headers, data=file_data)
        if response.status_code == 200:
            return f"{supabase_url}/storage/v1/object/public/{bucket}/{filename}"
        else:
            print(f"Supabase upload error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Exception during Supabase upload: {e}")
        return None

def delete_from_supabase_storage(file_url_or_path):
    """
    Deletes a file from Supabase Storage bucket 'proofs'.
    """
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_KEY')
    if not supabase_url or not supabase_key or not file_url_or_path:
        return False
    
    filename = file_url_or_path
    if '/' in file_url_or_path:
        filename = file_url_or_path.split('/')[-1]
        
    supabase_url = supabase_url.rstrip('/')
    bucket = 'proofs'
    delete_url = f"{supabase_url}/storage/v1/object/{bucket}"
    
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey": supabase_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "prefixes": [filename]
    }
    
    try:
        response = requests.delete(delete_url, headers=headers, json=payload)
        return response.status_code == 200
    except Exception as e:
        print(f"Exception during Supabase delete: {e}")
        return False

# ---------------------------------------------------------
# Database Seed Script
# ---------------------------------------------------------

def seed_db():
    """Pre-seeds the database with default users configured from environmental variables."""
    admin_uname = os.environ.get("ADMIN_USERNAME", "admin")
    manthan_uname = os.environ.get("MANTHAN_USERNAME", "manthan")
    dinesh_uname = os.environ.get("DINESH_USERNAME", "dinesh")

    users_to_seed = [
        {
            "username": admin_uname,
            "role": "admin",
            "password": os.environ.get("ADMIN_PASSWORD", "adminpassword123"),
            "budget": 0.0
        },
        {
            "username": manthan_uname,
            "role": "teammate",
            "password": os.environ.get("MANTHAN_PASSWORD", "manthanpassword123"),
            "budget": 5000.0
        },
        {
            "username": dinesh_uname,
            "role": "teammate",
            "password": os.environ.get("DINESH_PASSWORD", "dineshpassword123"),
            "budget": 5000.0
        }
    ]
    
    for u_data in users_to_seed:
        user = User.query.filter_by(username=u_data["username"]).first()
        if not user:
            new_user = User(
                username=u_data["username"],
                password_hash=generate_password_hash(u_data["password"]),
                role=u_data["role"],
                allocated_budget=u_data["budget"]
            )
            db.session.add(new_user)
    
    db.session.commit()
    print("Database seeding completed successfully.")

# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password.", "danger")
            
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    current_user = db.session.get(User, session['user_id'])
    
    # Retrieve all users for admin or stats
    teammates = User.query.filter_by(role='teammate').all()
    all_users = User.query.all()
    
    # Retrieve all transaction list
    # Sort buys by date and time descending
    buys = Buy.query.order_by(Buy.date.desc(), Buy.time.desc()).all()
    
    # Calculations for stats
    # 1. Total Team budget & expenditures (Admin)
    total_team_budget = sum([u.allocated_budget for u in teammates])
    
    # Total spent by users
    spent_by_user = {}
    for u in all_users:
        spent = db.session.query(db.func.sum(Buy.total_amount)).filter(Buy.user_id == u.id).scalar() or 0.0
        spent_by_user[u.username] = spent
        
    total_team_spent = sum([spent_by_user.get(u.username, 0.0) for u in teammates])
    total_team_remaining = total_team_budget - total_team_spent

    # 2. Specific teammate budget (Manthan / Dinesh)
    my_budget = current_user.allocated_budget
    my_spent = spent_by_user.get(current_user.username, 0.0)
    my_remaining = my_budget - my_spent

    # Find the "other" teammate for teammate view
    other_teammate = None
    other_budget = 0.0
    other_spent = 0.0
    if current_user.role == 'teammate':
        other = User.query.filter(User.role == 'teammate', User.id != current_user.id).first()
        if other:
            other_teammate = other.username
            other_budget = other.allocated_budget
            other_spent = spent_by_user.get(other.username, 0.0)

    # Prepare data for Chart.js
    # Bar Chart: Allocated Budget vs Expenditures (for manthan and dinesh configured usernames)
    manthan_uname = os.environ.get("MANTHAN_USERNAME", "manthan")
    dinesh_uname = os.environ.get("DINESH_USERNAME", "dinesh")
    
    manthan_user = User.query.filter_by(username=manthan_uname).first()
    dinesh_user = User.query.filter_by(username=dinesh_uname).first()
    
    chart_data = {
        'manthan': {
            'username': manthan_uname,
            'budget': manthan_user.allocated_budget if manthan_user else 0.0,
            'spent': spent_by_user.get(manthan_uname, 0.0)
        },
        'dinesh': {
            'username': dinesh_uname,
            'budget': dinesh_user.allocated_budget if dinesh_user else 0.0,
            'spent': spent_by_user.get(dinesh_uname, 0.0)
        }
    }

    # Cumulative spending line chart data
    # We query all buys sorted by date ascending
    chronological_buys = Buy.query.order_by(Buy.date.asc(), Buy.time.asc()).all()
    cumulative_dates = []
    cumulative_spent = []
    running_total = 0.0
    
    for b in chronological_buys:
        running_total += b.total_amount
        # Group by date for line chart labels
        date_str = b.date.strftime('%Y-%m-%d')
        cumulative_dates.append(date_str)
        cumulative_spent.append(running_total)

    # Context to pass to templates
    context = {
        'current_user': current_user,
        'teammates': teammates,
        'all_users': all_users,
        'buys': buys,
        'date_today': date.today().strftime('%Y-%m-%d'),
        'time_now': datetime.now().strftime('%H:%M'),
        'admin_stats': {
            'budget': total_team_budget,
            'spent': total_team_spent,
            'remaining': total_team_remaining
        },
        'teammate_stats': {
            'my_budget': my_budget,
            'my_spent': my_spent,
            'my_remaining': my_remaining,
            'other_name': other_teammate,
            'other_budget': other_budget,
            'other_spent': other_spent
        },
        'chart_data': chart_data,
        'line_chart_data': {
            'dates': cumulative_dates,
            'spent': cumulative_spent
        }
    }
    
    return render_template('dashboard.html', **context)

@app.route('/admin/budget', methods=['POST'])
@admin_required
def admin_budget():
    manthan_uname = os.environ.get("MANTHAN_USERNAME", "manthan")
    dinesh_uname = os.environ.get("DINESH_USERNAME", "dinesh")
    
    manthan_budget = request.form.get('manthan_budget', type=float)
    dinesh_budget = request.form.get('dinesh_budget', type=float)
    
    manthan = User.query.filter_by(username=manthan_uname).first()
    dinesh = User.query.filter_by(username=dinesh_uname).first()
    
    if manthan and manthan_budget is not None:
        manthan.allocated_budget = max(0.0, manthan_budget)
    if dinesh and dinesh_budget is not None:
        dinesh.allocated_budget = max(0.0, dinesh_budget)
        
    db.session.commit()
    flash("Budgets updated successfully.", "success")
    return redirect(url_for('dashboard'))

@app.route('/buy/add', methods=['POST'])
@login_required
def buy_add():
    # Handle files
    pdf_proof = request.files.get('pdf_proof')
    pdf_path = None
    
    if pdf_proof and pdf_proof.filename != '':
        if allowed_file(pdf_proof.filename):
            filename = secure_filename(pdf_proof.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            
            # Read file data for Supabase upload
            file_data = pdf_proof.read()
            pdf_proof.seek(0)
            
            # Try uploading to Supabase
            supabase_url = os.environ.get('SUPABASE_URL')
            supabase_key = os.environ.get('SUPABASE_KEY')
            uploaded_url = None
            
            if supabase_url and supabase_key:
                uploaded_url = upload_to_supabase_storage(file_data, unique_filename, content_type='application/pdf')
                
            if uploaded_url:
                pdf_path = uploaded_url
            else:
                # Local fallback
                pdf_proof.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                pdf_path = unique_filename
        else:
            flash("Invalid file format. Only PDF files are allowed.", "danger")
            return redirect(url_for('dashboard'))
    else:
        flash("Proof of purchase (PDF) is required.", "danger")
        return redirect(url_for('dashboard'))

    # Parse date and time
    form_date = request.form.get('date')
    form_time = request.form.get('time')
    
    buy_date = datetime.strptime(form_date, '%Y-%m-%d').date() if form_date else date.today()
    buy_time = datetime.strptime(form_time, '%H:%M').time() if form_time else datetime.now().time()

    # Determine user_id (Admin can choose who bought it, teammates are locked to themselves)
    if session.get('role') == 'admin':
        buyer_id = request.form.get('buyer_id', type=int)
        if not buyer_id:
            buyer_id = session['user_id']
    else:
        buyer_id = session['user_id']

    # Retrieve component lists
    component_names = request.form.getlist('component_name[]')
    unit_prices = request.form.getlist('unit_price[]')
    quantities = request.form.getlist('quantity[]')

    if not component_names or len(component_names) == 0:
        flash("You must include at least one component in the purchase.", "danger")
        return redirect(url_for('dashboard'))

    # Calculate total and create list of Component objects
    total_amount = 0.0
    new_components = []
    
    for name, price, qty in zip(component_names, unit_prices, quantities):
        if not name.strip():
            continue
        try:
            p = float(price)
            q = int(qty)
            if p <= 0 or q <= 0:
                raise ValueError
            
            total_amount += p * q
            new_components.append(Component(
                component_name=name.strip(),
                unit_price=p,
                quantity=q
            ))
        except ValueError:
            flash("Component unit price and quantity must be positive numbers.", "danger")
            return redirect(url_for('dashboard'))

    if not new_components:
        flash("No valid components were added.", "danger")
        return redirect(url_for('dashboard'))

    # Create Buy record
    new_buy = Buy(
        user_id=buyer_id,
        date=buy_date,
        time=buy_time,
        total_amount=total_amount,
        pdf_proof_path=pdf_path
    )
    
    # Save Buy & Components to Database
    db.session.add(new_buy)
    db.session.flush() # gets new_buy.id
    
    for comp in new_components:
        comp.buy_id = new_buy.id
        db.session.add(comp)
        
    db.session.commit()
    flash(f"Purchase logged successfully! Total: ₹{total_amount:,.2f}", "success")
    return redirect(url_for('dashboard'))

@app.route('/buy/edit/<int:buy_id>', methods=['GET', 'POST'])
@admin_required
def buy_edit(buy_id):
    buy_record = db.session.get(Buy, buy_id)
    if not buy_record:
        flash("Transaction not found.", "danger")
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        # Parse date and time
        form_date = request.form.get('date')
        form_time = request.form.get('time')
        buyer_id = request.form.get('buyer_id', type=int)
        
        buy_record.date = datetime.strptime(form_date, '%Y-%m-%d').date() if form_date else buy_record.date
        buy_record.time = datetime.strptime(form_time, '%H:%M').time() if form_time else buy_record.time
        
        if buyer_id:
            buy_record.user_id = buyer_id

        # Handle optional new PDF proof
        pdf_proof = request.files.get('pdf_proof')
        if pdf_proof and pdf_proof.filename != '':
            if allowed_file(pdf_proof.filename):
                filename = secure_filename(pdf_proof.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                
                # Read file data
                file_data = pdf_proof.read()
                pdf_proof.seek(0)
                
                # Check for Supabase config
                supabase_url = os.environ.get('SUPABASE_URL')
                supabase_key = os.environ.get('SUPABASE_KEY')
                uploaded_url = None
                
                if supabase_url and supabase_key:
                    uploaded_url = upload_to_supabase_storage(file_data, unique_filename, content_type='application/pdf')
                
                # Delete old PDF file if exists
                if buy_record.pdf_proof_path:
                    if buy_record.pdf_proof_path.startswith('http'):
                        delete_from_supabase_storage(buy_record.pdf_proof_path)
                    else:
                        old_path = os.path.join(app.config['UPLOAD_FOLDER'], buy_record.pdf_proof_path)
                        if os.path.exists(old_path):
                            try:
                                os.remove(old_path)
                            except Exception as e:
                                print(f"Error removing local file: {e}")
                
                if uploaded_url:
                    buy_record.pdf_proof_path = uploaded_url
                else:
                    # Fallback to local
                    pdf_proof.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    buy_record.pdf_proof_path = unique_filename
            else:
                flash("Invalid file format. Only PDF files are allowed.", "danger")
                return redirect(url_for('buy_edit', buy_id=buy_id))

        # Re-populate components
        component_names = request.form.getlist('component_name[]')
        unit_prices = request.form.getlist('unit_price[]')
        quantities = request.form.getlist('quantity[]')
        
        if not component_names or len(component_names) == 0:
            flash("You must include at least one component in the purchase.", "danger")
            return redirect(url_for('buy_edit', buy_id=buy_id))
            
        # Delete old components
        Component.query.filter_by(buy_id=buy_record.id).delete()
        
        # Calculate new total amount and add updated components
        total_amount = 0.0
        for name, price, qty in zip(component_names, unit_prices, quantities):
            if not name.strip():
                continue
            try:
                p = float(price)
                q = int(qty)
                if p <= 0 or q <= 0:
                    raise ValueError
                
                total_amount += p * q
                new_comp = Component(
                    buy_id=buy_record.id,
                    component_name=name.strip(),
                    unit_price=p,
                    quantity=q
                )
                db.session.add(new_comp)
            except ValueError:
                db.session.rollback()
                flash("Component unit price and quantity must be positive numbers.", "danger")
                return redirect(url_for('buy_edit', buy_id=buy_id))
                
        buy_record.total_amount = total_amount
        db.session.commit()
        
        flash("Transaction updated successfully.", "success")
        return redirect(url_for('dashboard'))
        
    users = User.query.all()
    return render_template('edit_buy.html', buy=buy_record, users=users)

@app.route('/export/expenses')
@login_required
def export_expenses():
    # Gather transactions ordered chronologically
    buys = Buy.query.order_by(Buy.date.asc(), Buy.time.asc()).all()
    
    # Generate CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # CSV Header
    writer.writerow([
        'Transaction ID', 
        'Date', 
        'Time', 
        'Buyer Username', 
        'Total Buy Amount', 
        'Component Name', 
        'Unit Price', 
        'Quantity', 
        'Line Item Total',
        'PDF Proof Link'
    ])
    
    for b in buys:
        buyer = b.user.username if b.user else 'Unknown'
        if b.pdf_proof_path:
            pdf_url = b.pdf_proof_path if b.pdf_proof_path.startswith('http') else url_for('static', filename=f'uploads/proofs/{b.pdf_proof_path}', _external=True)
        else:
            pdf_url = 'None'
        
        # If no components exist for some reason, write a row for the buy
        if not b.components:
            writer.writerow([b.id, b.date.strftime('%Y-%m-%d'), b.time.strftime('%H:%M:%S'), buyer, b.total_amount, 'No Components', 0.0, 0, 0.0, pdf_url])
            continue
            
        for c in b.components:
            line_total = c.unit_price * c.quantity
            writer.writerow([
                b.id, 
                b.date.strftime('%Y-%m-%d'), 
                b.time.strftime('%H:%M:%S'), 
                buyer, 
                b.total_amount, 
                c.component_name, 
                c.unit_price, 
                c.quantity, 
                line_total,
                pdf_url
            ])
            
    # Return as downloadable CSV attachment
    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=wro_expenses_summary.csv"}
    )

# ---------------------------------------------------------
# Application Startup Initialization
# ---------------------------------------------------------

with app.app_context():
    db.create_all()
    seed_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
