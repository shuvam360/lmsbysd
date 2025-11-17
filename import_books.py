import csv
from app import app, db
from my_models import Book


CSV_FILE = 'book.py.csv'

with app.app_context():
    with open(CSV_FILE, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)

        count = 0
        skipped = 0
        
        for row in reader:
            # Read CSV columns: bid, title, author, category, status
            title = row.get('title', '').strip()
            author = row.get('author', '').strip()
            category = row.get('category', '').strip()
            status = row.get('status', '').strip().lower()

            # Skip if required fields are missing
            if not title or not author:
                skipped += 1
                continue
            
            # Check if book already exists (by title and author)
            existing = Book.query.filter_by(title=title, author=author).first()
            if existing:
                skipped += 1
                continue
            
            # Set copies based on status
            # If status is 'issued', set available_copies to 0 (book is out)
            # If status is 'available', set available_copies to 1 (book is available)
            if status == 'issued':
                total_copies = 1
                available_copies = 0
            elif status == 'available':
                total_copies = 1
                available_copies = 1
            else:
                # Default to available if status is unclear
                total_copies = 1
                available_copies = 1
            
            # Map status to model format
            book_status = 'Available' if status == 'available' else 'Issued'
            
            book = Book(
                title=title,
                author=author,
                category=category if category else None,
                total_copies=total_copies,
                available_copies=available_copies,
                status=book_status
            )
            
            db.session.add(book)
            count += 1

        db.session.commit()
        print(f"✅ Successfully imported {count} books into the database.")
        if skipped > 0:
            print(f"⚠️  Skipped {skipped} books (missing data or duplicates).")
