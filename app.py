import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename
from models import db, User, Book, Category, IssuedBook
from datetime import datetime
from sqlalchemy import or_

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['ALLOWED_PDF_EXTENSIONS'] = {'pdf'}

# Ensure upload directories exist
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'books'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs'), exist_ok=True)

db.init_app(app)

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            flash('Access denied. Admin privileges required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))
        
        user = User(name=name, email=email, role='student')
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['user_role'] = user.role
            
            flash(f'Welcome back, {user.name}!', 'success')
            
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_books = Book.query.count()
    total_students = User.query.filter_by(role='student').count()
    total_issued = IssuedBook.query.filter_by(status='issued').count()
    recent_books = Book.query.order_by(Book.added_date.desc()).limit(5).all()
    
    return render_template('admin_dashboard.html',
                         total_books=total_books,
                         total_students=total_students,
                         total_issued=total_issued,
                         recent_books=recent_books)

@app.route('/admin/books')
@admin_required
def admin_books():
    search = request.args.get('search', '')
    category_id = request.args.get('category', '')
    
    query = Book.query
    
    if search:
        query = query.filter(or_(
            Book.title.ilike(f'%{search}%'),
            Book.author.ilike(f'%{search}%'),
            Book.isbn.ilike(f'%{search}%')
        ))
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    books = query.order_by(Book.added_date.desc()).all()
    categories = Category.query.all()
    
    return render_template('admin_books.html', books=books, categories=categories)

@app.route('/admin/books/add', methods=['GET', 'POST'])
@admin_required
def add_book():
    if request.method == 'POST':
        title = request.form.get('title')
        author = request.form.get('author')
        isbn = request.form.get('isbn')
        category_id = request.form.get('category_id')
        description = request.form.get('description')
        
        if Book.query.filter_by(isbn=isbn).first():
            flash('A book with this ISBN already exists', 'danger')
            return redirect(url_for('add_book'))
        
        image_path = None
        pdf_path = None
        
        # Handle image upload
        if 'image' in request.files:
            image = request.files['image']
            if image and image.filename and allowed_file(image.filename, app.config['ALLOWED_IMAGE_EXTENSIONS']):
                filename = secure_filename(image.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                image_path = f"uploads/books/{unique_filename}"
                full_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'books', unique_filename)
                image.save(full_image_path)
        
        # Handle PDF upload
        if 'pdf' in request.files:
            pdf = request.files['pdf']
            if pdf and pdf.filename and allowed_file(pdf.filename, app.config['ALLOWED_PDF_EXTENSIONS']):
                filename = secure_filename(pdf.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                pdf_path = f"uploads/pdfs/{unique_filename}"
                full_pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', unique_filename)
                pdf.save(full_pdf_path)
        
        book = Book(
            title=title,
            author=author,
            isbn=isbn,
            category_id=category_id,
            description=description,
            image_path=image_path,
            pdf_path=pdf_path
        )
        
        db.session.add(book)
        db.session.commit()
        
        flash('Book added successfully!', 'success')
        return redirect(url_for('admin_books'))
    
    categories = Category.query.all()
    return render_template('add_book.html', categories=categories)

@app.route('/admin/books/edit/<int:book_id>', methods=['GET', 'POST'])
@admin_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.isbn = request.form.get('isbn')
        book.category_id = request.form.get('category_id')
        book.description = request.form.get('description')
        
        # Handle image upload
        if 'image' in request.files:
            image = request.files['image']
            if image and image.filename and allowed_file(image.filename, app.config['ALLOWED_IMAGE_EXTENSIONS']):
                # Remove old image if exists
                if book.image_path:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], book.image_path.replace('uploads/', ''))
                    if os.path.exists(old_path):
                        os.remove(old_path)
                
                filename = secure_filename(image.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                book.image_path = f"uploads/books/{unique_filename}"
                full_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'books', unique_filename)
                image.save(full_image_path)
        
        # Handle PDF upload
        if 'pdf' in request.files:
            pdf = request.files['pdf']
            if pdf and pdf.filename and allowed_file(pdf.filename, app.config['ALLOWED_PDF_EXTENSIONS']):
                # Remove old PDF if exists
                if book.pdf_path:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], book.pdf_path.replace('uploads/', ''))
                    if os.path.exists(old_path):
                        os.remove(old_path)
                
                filename = secure_filename(pdf.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                book.pdf_path = f"uploads/pdfs/{unique_filename}"
                full_pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', unique_filename)
                pdf.save(full_pdf_path)
        
        db.session.commit()
        
        flash('Book updated successfully!', 'success')
        return redirect(url_for('admin_books'))
    
    categories = Category.query.all()
    return render_template('edit_book.html', book=book, categories=categories)

@app.route('/admin/books/delete/<int:book_id>', methods=['POST'])
@admin_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    
    # Remove associated files
    if book.image_path:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], book.image_path.replace('uploads/', ''))
        if os.path.exists(image_path):
            os.remove(image_path)
    
    if book.pdf_path:
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], book.pdf_path.replace('uploads/', ''))
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    
    # Delete issued book records
    IssuedBook.query.filter_by(book_id=book_id).delete()
    
    db.session.delete(book)
    db.session.commit()
    
    flash('Book deleted successfully!', 'success')
    return redirect(url_for('admin_books'))

@app.route('/admin/categories')
@admin_required
def manage_categories():
    categories = Category.query.all()
    return render_template('manage_categories.html', categories=categories)

@app.route('/admin/categories/add', methods=['POST'])
@admin_required
def add_category():
    name = request.form.get('name')
    
    if Category.query.filter_by(name=name).first():
        flash('Category already exists', 'danger')
    else:
        category = Category(name=name)
        db.session.add(category)
        db.session.commit()
        flash('Category added successfully!', 'success')
    
    return redirect(url_for('manage_categories'))

@app.route('/admin/categories/delete/<int:category_id>', methods=['POST'])
@admin_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    
    if Book.query.filter_by(category_id=category_id).first():
        flash('Cannot delete category that has books assigned to it', 'danger')
    else:
        db.session.delete(category)
        db.session.commit()
        flash('Category deleted successfully!', 'success')
    
    return redirect(url_for('manage_categories'))

@app.route('/admin/students')
@admin_required
def view_students():
    students = User.query.filter_by(role='student').all()
    return render_template('view_students.html', students=students)

@app.route('/admin/issue', methods=['GET', 'POST'])
@admin_required
def issue_book():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        book_id = request.form.get('book_id')
        return_date_str = request.form.get('return_date')
        
        existing = IssuedBook.query.filter_by(book_id=book_id, status='issued').first()
        if existing:
            flash('This book is already issued to someone', 'danger')
            return redirect(url_for('issue_book'))
        
        return_date = datetime.strptime(return_date_str, '%Y-%m-%d') if return_date_str else None
        
        issued_book = IssuedBook(
            user_id=user_id,
            book_id=book_id,
            return_date=return_date
        )
        
        db.session.add(issued_book)
        db.session.commit()
        
        flash('Book issued successfully!', 'success')
        return redirect(url_for('issued_books_admin'))
    
    students = User.query.filter_by(role='student').all()
    books = Book.query.all()
    
    return render_template('issue_book.html', students=students, books=books)

@app.route('/admin/issued')
@admin_required
def issued_books_admin():
    issued_books = IssuedBook.query.order_by(IssuedBook.issue_date.desc()).all()
    return render_template('issued_books_admin.html', issued_books=issued_books)

@app.route('/admin/return/<int:issued_id>', methods=['POST'])
@admin_required
def return_book(issued_id):
    issued_book = IssuedBook.query.get_or_404(issued_id)
    issued_book.status = 'returned'
    
    db.session.commit()
    
    flash('Book returned successfully!', 'success')
    return redirect(url_for('issued_books_admin'))

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    user_id = session.get('user_id')
    issued_books = IssuedBook.query.filter_by(user_id=user_id, status='issued').all()
    
    search = request.args.get('search', '')
    category_id = request.args.get('category', '')
    
    query = Book.query
    
    if search:
        query = query.filter(or_(
            Book.title.ilike(f'%{search}%'),
            Book.author.ilike(f'%{search}%')
        ))
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    books = query.order_by(Book.added_date.desc()).all()
    categories = Category.query.all()
    
    return render_template('student_dashboard.html',
                         books=books,
                         categories=categories,
                         issued_books=issued_books)

@app.route('/student/issued')
@login_required
def student_issued_books():
    user_id = session.get('user_id')
    issued_books = IssuedBook.query.filter_by(user_id=user_id).order_by(IssuedBook.issue_date.desc()).all()
    
    return render_template('student_issued_books.html', issued_books=issued_books)

@app.route('/book/<int:book_id>')
@login_required
def view_book(book_id):
    book = Book.query.get_or_404(book_id)
    return render_template('view_book.html', book=book)

@app.route('/download/<int:book_id>')
@login_required
def download_book(book_id):
    book = Book.query.get_or_404(book_id)
    
    if not book.pdf_path:
        flash('PDF not available for this book', 'warning')
        return redirect(url_for('view_book', book_id=book_id))
    
    pdf_filename = os.path.basename(book.pdf_path)
    pdf_directory = os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs')
    
    return send_from_directory(pdf_directory, pdf_filename, as_attachment=True)

def init_db():
    with app.app_context():
        db.create_all()
        
        if not User.query.filter_by(email='admin@library.com').first():
            admin = User(name='Admin', email='admin@library.com', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('Default admin created: admin@library.com / admin123')
        
        if Category.query.count() == 0:
            default_categories = ['Fiction', 'Non-Fiction', 'Science', 'Technology', 'History', 'Biography']
            for cat_name in default_categories:
                category = Category(name=cat_name)
                db.session.add(category)
            db.session.commit()
            print('Default categories created')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)