import os
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import or_
from extensions import db
from my_models import User, Book, BookTransaction
from datetime import datetime, timedelta


BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'library.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)
with app.app_context():
    db.create_all()



DUE_DAYS = 14
FINE_PER_DAY = 5.0  

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except (ValueError, TypeError):
        return None


@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_dashboard'))
    return render_template('login.html')

# ------------------------- Authentication -------------------------
@app.route('/', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()
        remember_me = bool(request.form.get('remember'))
        
        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template('login.html')
        
        # Find user by username; if not found, try by email (allow login via either)
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User.query.filter_by(email=username.lower()).first()
        
        
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid credentials. Please check your username and password.", "danger")
            return render_template('login.html')
        
        # Check if account is active
        if not user.active:
            flash("Account inactive. Contact admin.", "warning")
            return redirect(url_for('login'))
        
        # All checks passed, login the user
        login_user(user, remember=remember_me)
        flash("Logged in successfully.", "success")
        next_page = request.args.get('next')
        resp = redirect(next_page or url_for('index'))
        # store for next-time prefill
        try:
            resp.set_cookie('last_username', user.username, max_age=30*24*60*60, samesite='Lax')
            if user.email:
                resp.set_cookie('last_email', user.email, max_age=30*24*60*60, samesite='Lax')
        except Exception:
            pass
        return resp
    
    return render_template('login.html', last_username=request.cookies.get('last_username'), last_email=request.cookies.get('last_email'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
   
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        
        if not username or not password or not email:
            flash("Username, password, and email are required.", "danger")
            return redirect(url_for('register'))
        
        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash(f"Username '{username}' is already taken. Please choose a different username.", "danger")
            return redirect(url_for('register'))
        
        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash(f"Email '{email}' is already registered. Please use a different email or login instead.", "danger")
            return redirect(url_for('register'))
        
        # Create new user with username and email stored in database
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            name=name,
            email=email,
            role='user',
            active=True
        )
        
        try:
            db.session.add(user)
            db.session.commit()
            flash(f"Registration successful! Username '{username}' and email '{email}' have been stored. You can login now.", "success")
            resp = redirect(url_for('login'))
            # store for next-time prefill
            try:
                resp.set_cookie('last_username', username, max_age=30*24*60*60, samesite='Lax')
                if email:
                    resp.set_cookie('last_email', email, max_age=30*24*60*60, samesite='Lax')
            except Exception:
                pass
            return resp
        except Exception as e:
            db.session.rollback()
            # Handle database unique constraint violations as backup
            if 'UNIQUE constraint failed' in str(e) or 'unique constraint' in str(e).lower():
                if 'username' in str(e).lower():
                    flash(f"Username '{username}' is already taken. Please choose a different username.", "danger")
                elif 'email' in str(e).lower():
                    flash(f"Email '{email}' is already registered. Please use a different email.", "danger")
                else:
                    flash("Username or email already exists. Please choose different credentials.", "danger")
            else:
                flash("An error occurred during registration. Please try again.", "danger")
            return redirect(url_for('register'))
    
    return render_template('register.html')

# ------------------------- Admin Dashboard -------------------------
def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return func(*args, **kwargs)
    return wrapper

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_books = Book.query.count()
    total_users = User.query.filter_by(role='user').count()
    issued = BookTransaction.query.filter_by(status='issued').count()
    overdue = 0
    now = datetime.utcnow()
    for t in BookTransaction.query.filter_by(status='issued').all():
        if t.due_date and t.due_date < now:
            overdue += 1
    recent_transactions = BookTransaction.query.order_by(BookTransaction.issue_date.desc()).limit(8).all()
    return render_template('admin_dashboard.html', total_books=total_books, total_users=total_users, issued=issued, overdue=overdue, recent_transactions=recent_transactions)

# ------------------------- User Dashboard -------------------------
@app.route('/user')
@login_required
def user_dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    my_BookTransactions = BookTransaction.query.filter_by(user_id=current_user.id).order_by(BookTransaction.issue_date.desc()).all()
    today = datetime.utcnow().date()
    
    # Calculate statistics
    issued_books = [t for t in my_BookTransactions if t.status == 'issued']
    overdue_books = [t for t in issued_books if t.due_date and t.due_date.date() < today]
    returned_books = [t for t in my_BookTransactions if t.status == 'returned']
    total_fine = sum(t.fine for t in my_BookTransactions if t.fine > 0)
    
    # Library statistics
    total_books_in_library = Book.query.count()
    available_books = Book.query.filter(Book.available_copies > 0).count()
    
    has_issued = len(issued_books) > 0
    
    return render_template('user_dashboard.html', 
                         my_BookTransactions=my_BookTransactions, 
                         fine_per_day=FINE_PER_DAY, 
                         today=today, 
                         has_issued=has_issued,
                         issued_count=len(issued_books),
                         overdue_count=len(overdue_books),
                         returned_count=len(returned_books),
                         total_fine=total_fine,
                         total_books_in_library=total_books_in_library,
                         available_books=available_books,
                         DUE_DAYS=DUE_DAYS)

# ------------------------- Books -------------------------
@app.route('/books')
@login_required
def books():
    q = request.args.get('q', '').strip()
    if q:
        books = Book.query.filter(
            or_(
                Book.title.ilike(f'%{q}%'),
                Book.author.ilike(f'%{q}%'),
                (Book.isbn.isnot(None)) & (Book.isbn.ilike(f'%{q}%'))
            )
        ).all()
    else:
        books = Book.query.order_by(Book.title).all()
    return render_template('books.html', books=books, q=q, due_days=DUE_DAYS, fine_per_day=FINE_PER_DAY)

@app.route('/admin/book/add', methods=['GET','POST'])
@login_required
@admin_required
def add_book():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        author = (request.form.get('author') or '').strip()
        isbn = (request.form.get('isbn') or '').strip() or None
        publisher = (request.form.get('publisher') or '').strip()
        category = (request.form.get('category') or '').strip()
        
        if not title or not author:
            flash("Title and author are required.", "danger")
            return render_template('add_book.html')
        
        try:
            copies = int(request.form.get('copies') or 1)
            if copies < 1:
                copies = 1
        except ValueError:
            copies = 1
        
        book = Book(title=title, author=author, isbn=isbn, publisher=publisher, category=category, total_copies=copies, available_copies=copies)
        db.session.add(book)
        db.session.commit()
        flash("Book added successfully.", "success")
        return redirect(url_for('books'))
    return render_template('add_book.html')

@app.route('/admin/book/edit/<int:book_id>', methods=['GET','POST'])
@login_required
@admin_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        author = (request.form.get('author') or '').strip()
        isbn = (request.form.get('isbn') or '').strip() or None
        publisher = (request.form.get('publisher') or '').strip()
        category = (request.form.get('category') or '').strip()
        
        if not title or not author:
            flash("Title and author are required.", "danger")
            return render_template('edit_book.html', book=book)
        
        try:
            new_total = int(request.form.get('copies') or book.total_copies)
            if new_total < 1:
                new_total = 1
        except ValueError:
            new_total = book.total_copies
        
        book.title = title
        book.author = author
        book.isbn = isbn
        book.publisher = publisher
        book.category = category
        
        diff = new_total - book.total_copies
        book.total_copies = new_total
        book.available_copies = max(0, book.available_copies + diff)
        db.session.commit()
        flash("Book updated.", "success")
        return redirect(url_for('books'))
    return render_template('edit_book.html', book=book)

@app.route('/admin/book/delete/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
   
    active = BookTransaction.query.filter_by(book_id=book.id, status='issued').count()
    if active:
        flash("Cannot delete book: active issued copies exist.", "warning")
        return redirect(url_for('books'))
    db.session.delete(book)
    db.session.commit()
    flash("Book deleted.", "info")
    return redirect(url_for('books'))

# ------------------------- Issue & Return -------------------------
@app.route('/books/issue/<int:book_id>', methods=['GET','POST'])
@login_required
def issue_book_to_user(book_id):
    # Allow regular users to issue books to themselves
    book = Book.query.get_or_404(book_id)
    
    if request.method == 'POST':
        if book.available_copies <= 0:
            flash("No copies available.", "warning")
            return redirect(url_for('books'))
        
        # Check if user already has this book issued
        existing = BookTransaction.query.filter_by(
            user_id=current_user.id, 
            book_id=book.id, 
            status='issued'
        ).first()
        if existing:
            flash("You already have this book issued.", "warning")
            return redirect(url_for('books'))
        
        due_date = datetime.utcnow() + timedelta(days=DUE_DAYS)
        tr = BookTransaction(user_id=current_user.id, book_id=book.id, due_date=due_date, status='issued')
        book.available_copies -= 1
        db.session.add(tr)
        db.session.commit()
        
        # Redirect to confirmation page
        return redirect(url_for('issue_confirmation', trans_id=tr.id))
    
    # GET request - show confirmation page
    if book.available_copies <= 0:
        flash("This book is not available.", "warning")
        return redirect(url_for('books'))
    
    # Calculate return date
    return_date = datetime.utcnow() + timedelta(days=DUE_DAYS)
    
    return render_template('issue_confirmation.html', book=book, due_days=DUE_DAYS, fine_per_day=FINE_PER_DAY, return_date=return_date)

@app.route('/books/issue/confirm/<int:trans_id>')
@login_required
def issue_confirmation(trans_id):
    tr = BookTransaction.query.get_or_404(trans_id)
    # Only the user who issued the book can see this confirmation
    if tr.user_id != current_user.id:
        abort(403)
    return render_template('issue_success.html', transaction=tr, fine_per_day=FINE_PER_DAY)

@app.route('/admin/issue', methods=['GET','POST'])
@login_required
@admin_required
def issue_book():
    if request.method == 'POST':
        try:
            user_id = int(request.form.get('user_id') or 0)
            book_id = int(request.form.get('book_id') or 0)
        except (ValueError, TypeError):
            flash("Invalid user or book ID.", "danger")
            return redirect(url_for('issue_book'))
        
        user = User.query.get(user_id)
        book = Book.query.get(book_id)
        if not user or not book:
            flash("Invalid user or book.", "danger")
            return redirect(url_for('issue_book'))
        if book.available_copies <= 0:
            flash("No copies available.", "warning")
            return redirect(url_for('issue_book'))
        due_date = datetime.utcnow() + timedelta(days=DUE_DAYS)
        tr = BookTransaction(user_id=user.id, book_id=book.id, due_date=due_date, status='issued')
        book.available_copies -= 1
        db.session.add(tr)
        db.session.commit()
        flash(f"Book issued to {user.username}. Due on {due_date.date()}", "success")
        return redirect(url_for('admin_dashboard'))
    users = User.query.filter_by(role='user').all()
    books = Book.query.filter(Book.available_copies > 0).all()
    return render_template('issue_book.html', users=users, books=books, due_days=DUE_DAYS)

@app.route('/return/<int:trans_id>', methods=['GET','POST'])
@login_required
def return_book(trans_id):
    tr = BookTransaction.query.get_or_404(trans_id)
    # Admin or owner can return
    if current_user.role != 'admin' and tr.user_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        tr.return_date = datetime.utcnow()
        # calculate fine if returned after due_date
        if tr.due_date and tr.return_date.date() > tr.due_date.date():
            days_late = (tr.return_date.date() - tr.due_date.date()).days
            tr.fine = days_late * FINE_PER_DAY
        else:
            tr.fine = 0.0
        tr.status = 'returned'
        # increment available copies
        tr.book.available_copies = min(tr.book.total_copies, tr.book.available_copies + 1)
        db.session.commit()
        flash("Book returned successfully.", "success")
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_dashboard'))
    return render_template('return_book.html', BookTransaction=tr)

# ------------------------- Reports -------------------------
@app.route('/admin/report')
@login_required
@admin_required
def report():
    # Simple report: all BookTransactions
    BookTransactions = BookTransaction.query.order_by(BookTransaction.issue_date.desc()).all()
    return render_template('report.html', BookTransactions=BookTransactions)

# ------------------------- Admin user management -------------------------
@app.route('/admin/users')
@login_required
@admin_required
def manage_users():
    users = User.query.order_by(User.username).all()
    return render_template('manage_users.html', users=users)

@app.route('/admin/user/toggle/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash("Cannot deactivate admin.", "warning")
        return redirect(url_for('manage_users'))
    user.active = not user.active
    db.session.commit()
    flash("User status updated.", "info")
    return redirect(url_for('manage_users'))

# ------------------------- Simple error pages -------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

# if __name__ == "__main__":
#     app.run(debug=True)

if __name__ == "__main__":
    # Use PORT env var when deployed (platforms like Render/Heroku set this).
    port = int(os.environ.get("PORT", 5000))
    # Use host 0.0.0.0 so the container accepts external connections.
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)

