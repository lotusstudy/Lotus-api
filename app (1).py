"""
Lotus Academy Management System - Main Flask Application
Complete attendance management with Google Drive integration
"""
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from functools import wraps
from datetime import datetime, timedelta
import os
import json

# Import local modules
from database import (
    init_db, get_db, get_total_days, 
    get_student_attendance_percentage, get_teacher_attendance_percentage,
    get_last_updated_date, update_last_updated_date, log_sync, get_sync_history
)
from models import (
    get_or_create_student, get_or_create_teacher,
    insert_student_attendance, insert_teacher_attendance,
    date_exists_in_attendance, get_all_students, get_all_teachers,
    get_student_by_id, get_teacher_by_id, get_class_averages, search_all
)
from google_drive import (
    list_files_in_folder, download_excel, extract_date_from_filename,
    is_student_file, is_teacher_file, process_student_excel, process_teacher_excel
)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'lotus-academy-secret-key-' + str(os.urandom(24)))
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# Configure CORS
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": [
            'http://localhost:3000',
            'http://localhost:5500',
            'http://127.0.0.1:5500',
            'http://localhost:8080',
            'https://*.vercel.app',
            'https://*.netlify.app',
            '*'  # Allow all origins for testing
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"]
    }
})

# ==================== AUTHENTICATION ====================

# Valid credentials
VALID_USERS = {
    'shristi': 'lotusaccountmanager',
    'anmol': 'adminlotus.ea',
    'anubhav': 'anulotus.ea'
}

def login_required(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for session first
        if 'user' in session:
            return f(*args, **kwargs)
        
        # Check for Authorization header
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Basic '):
            import base64
            try:
                decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
                username, password = decoded.split(':', 1)
                if username in VALID_USERS and VALID_USERS[username] == password:
                    session['user'] = username
                    return f(*args, **kwargs)
            except:
                pass
        
        return jsonify({
            'error': 'Unauthorized',
            'message': 'Please login to access this resource',
            'redirect': '/login'
        }), 401
    
    return decorated_function

# ==================== CORE ROUTES ====================

@app.route('/')
def home():
    """Root endpoint - API status"""
    return jsonify({
        'message': 'Lotus Academy Management API',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': {
            'login': '/login',
            'sync': '/sync',
            'stats': '/stats',
            'teachers': '/teachers',
            'students': '/students',
            'classes': '/classes',
            'search': '/search',
            'health': '/health'
        }
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check for monitoring"""
    try:
        # Test database connection
        conn = get_db()
        conn.execute('SELECT 1')
        conn.close()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/login', methods=['POST', 'OPTIONS'])
def login():
    """User login endpoint"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'Please provide username and password'
            }), 400
        
        username = data.get('username', '').strip().lower()
        password = data.get('password', '')
        remember = data.get('remember', False)
        
        # Validate credentials
        if username in VALID_USERS and VALID_USERS[username] == password:
            session['user'] = username
            session['login_time'] = datetime.now().isoformat()
            
            if remember:
                session.permanent = True
            
            return jsonify({
                'success': True,
                'message': 'Login successful',
                'user': username,
                'redirect': '/dashboard'
            })
        
        return jsonify({
            'success': False,
            'message': 'Invalid username or password'
        }), 401
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Login error: {str(e)}'
        }), 500

@app.route('/logout', methods=['POST'])
def logout():
    """User logout endpoint"""
    session.clear()
    return jsonify({
        'success': True,
        'message': 'Logged out successfully'
    })

@app.route('/check-auth', methods=['GET'])
def check_auth():
    """Check if user is authenticated"""
    if 'user' in session:
        return jsonify({
            'authenticated': True,
            'user': session['user']
        })
    return jsonify({'authenticated': False})

# ==================== SYNC ROUTE ====================

@app.route('/sync', methods=['POST', 'GET'])
@login_required
def sync_data():
    """
    Sync attendance data from Google Drive
    Processes all Excel files and inserts into database
    """
    try:
        print(f"\n{'='*50}")
        print(f"🔄 Starting sync at {datetime.now()}")
        print(f"{'='*50}")
        
        # Get all files from Google Drive
        try:
            files = list_files_in_folder()
        except Exception as e:
            # If Drive fails, try local test data
            print(f"⚠️ Google Drive access failed: {e}")
            print("📂 Checking for local test data...")
            files = _get_local_test_files()
        
        if not files:
            return jsonify({
                'success': False,
                'message': 'No Excel files found. Please check Google Drive connection.',
                'synced': 0,
                'skipped': 0
            }), 404
        
        synced_files = 0
        skipped_files = 0
        total_records = 0
        errors = []
        
        for file in files:
            try:
                filename = file.get('name', 'unknown.xlsx')
                file_id = file.get('id', '')
                
                print(f"\n📄 Processing: {filename}")
                
                # Extract date from filename
                date = extract_date_from_filename(filename)
                if not date:
                    print(f"  ⏭️ Skipped: No date in filename")
                    skipped_files += 1
                    continue
                
                # Check if date already processed
                if date_exists_in_attendance(date):
                    print(f"  ⏭️ Skipped: Date {date} already synced")
                    skipped_files += 1
                    continue
                
                # Download and process file
                if file.get('_local_path'):
                    # Local file
                    file_buffer = open(file['_local_path'], 'rb')
                else:
                    # Google Drive file
                    file_buffer = download_excel(file_id)
                
                records = []
                
                if is_student_file(filename):
                    records = process_student_excel(file_buffer, date)
                    file_type = 'student'
                elif is_teacher_file(filename):
                    records = process_teacher_excel(file_buffer, date)
                    file_type = 'teacher'
                else:
                    print(f"  ⏭️ Skipped: Unknown file type")
                    skipped_files += 1
                    file_buffer.close()
                    continue
                
                if not records:
                    print(f"  ⚠️ No records found in file")
                    skipped_files += 1
                    file_buffer.close()
                    continue
                
                # Insert records into database
                inserted_count = 0
                for record in records:
                    try:
                        if file_type == 'student':
                            student_id = get_or_create_student(
                                record['name'],
                                record['class'],
                                record['board'],
                                record.get('stream')
                            )
                            if student_id:
                                success = insert_student_attendance(
                                    student_id,
                                    date,
                                    record['status'],
                                    record.get('time')
                                )
                                if success:
                                    inserted_count += 1
                        
                        elif file_type == 'teacher':
                            teacher_id = get_or_create_teacher(
                                record['name'],
                                record['subject']
                            )
                            if teacher_id:
                                success = insert_teacher_attendance(
                                    teacher_id,
                                    date,
                                    record['status'],
                                    record.get('time')
                                )
                                if success:
                                    inserted_count += 1
                    
                    except Exception as e:
                        print(f"  ❌ Error inserting record: {e}")
                
                file_buffer.close()
                synced_files += 1
                total_records += inserted_count
                
                print(f"  ✅ Processed: {inserted_count} records for date {date}")
                
            except Exception as e:
                error_msg = f"Error processing {file.get('name', 'unknown')}: {str(e)}"
                print(f"  ❌ {error_msg}")
                errors.append(error_msg)
                skipped_files += 1
                continue
        
        # Update last sync date
        today = datetime.now().strftime('%Y-%m-%d')
        update_last_updated_date(today)
        
        # Log sync
        status = 'SUCCESS' if synced_files > 0 else 'NO_NEW_DATA'
        log_sync(synced_files, total_records, status)
        
        print(f"\n{'='*50}")
        print(f"✅ Sync completed: {synced_files} files, {total_records} records")
        print(f"⏭️ Skipped: {skipped_files} files")
        if errors:
            print(f"❌ Errors: {len(errors)}")
        print(f"{'='*50}\n")
        
        return jsonify({
            'success': True,
            'message': f'Synced {synced_files} files ({total_records} records)',
            'synced': synced_files,
            'skipped': skipped_files,
            'total_records': total_records,
            'errors': errors if errors else None,
            'timestamp': today
        })
        
    except Exception as e:
        print(f"❌ Sync failed: {e}")
        log_sync(0, 0, 'FAILED', str(e))
        
        return jsonify({
            'success': False,
            'message': f'Sync failed: {str(e)}'
        }), 500

def _get_local_test_files():
    """Get local Excel files for testing (fallback when Drive unavailable)"""
    test_folder = os.path.join(os.path.dirname(__file__), 'test_data')
    
    if not os.path.exists(test_folder):
        return []
    
    files = []
    for filename in os.listdir(test_folder):
        if filename.endswith('.xlsx'):
            files.append({
                'name': filename,
                'id': f'local_{filename}',
                '_local_path': os.path.join(test_folder, filename)
            })
    
    return files

# ==================== STATS ROUTE ====================

@app.route('/stats', methods=['GET'])
@login_required
def get_stats():
    """Get dashboard statistics"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        total_days = get_total_days()
        
        cursor.execute('SELECT COUNT(*) as total FROM students')
        total_students = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM teachers')
        total_teachers = cursor.fetchone()['total']
        
        # Get today's attendance
        today = datetime.now().strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT COUNT(*) as present FROM student_attendance 
            WHERE date = ? AND status = 'PRESENT'
        ''', (today,))
        today_present = cursor.fetchone()['present'] if total_students > 0 else 0
        
        cursor.execute('''
            SELECT COUNT(*) as present FROM teacher_attendance 
            WHERE date = ? AND status = 'PRESENT'
        ''', (today,))
        today_teacher_present = cursor.fetchone()['present'] if total_teachers > 0 else 0
        
        last_updated = get_last_updated_date()
        
        # Overall attendance percentage
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN status = 'PRESENT' THEN 1 ELSE 0 END), 0) as present,
                COUNT(*) as total
            FROM student_attendance
        ''')
        student_att = cursor.fetchone()
        overall_student_pct = round((student_att['present'] / student_att['total']) * 100, 2) if student_att['total'] > 0 else 0
        
        cursor.execute('''
            SELECT 
                COALESCE(SUM(CASE WHEN status = 'PRESENT' THEN 1 ELSE 0 END), 0) as present,
                COUNT(*) as total
            FROM teacher_attendance
        ''')
        teacher_att = cursor.fetchone()
        overall_teacher_pct = round((teacher_att['present'] / teacher_att['total']) * 100, 2) if teacher_att['total'] > 0 else 0
        
        conn.close()
        
        return jsonify({
            'total_days': total_days,
            'total_students': total_students,
            'total_teachers': total_teachers,
            'today_student_present': today_present,
            'today_teacher_present': today_teacher_present,
            'overall_student_attendance': overall_student_pct,
            'overall_teacher_attendance': overall_teacher_pct,
            'last_updated': last_updated,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== TEACHER ROUTES ====================

@app.route('/teachers', methods=['GET'])
@login_required
def get_teachers():
    """Get all teachers with attendance percentage"""
    try:
        teachers = get_all_teachers()
        total_days = get_total_days()
        
        result = []
        for teacher in teachers:
            percentage = get_teacher_attendance_percentage(teacher['id'])
            result.append({
                'id': teacher['id'],
                'name': teacher['name'],
                'subject': teacher['subject'],
                'attendance_percentage': percentage,
                'total_days': total_days
            })
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/teacher/<int:teacher_id>', methods=['GET'])
@login_required
def get_teacher_detail(teacher_id):
    """Get teacher details with full attendance history"""
    try:
        teacher = get_teacher_by_id(teacher_id)
        
        if not teacher:
            return jsonify({'error': 'Teacher not found'}), 404
        
        attendance_history = teacher.pop('attendance_history', [])
        
        # Separate present and absent dates
        present_dates = [a['date'] for a in attendance_history if a['status'] == 'PRESENT']
        absent_dates = [a['date'] for a in attendance_history if a['status'] == 'ABSENT']
        
        percentage = get_teacher_attendance_percentage(teacher_id)
        total_days = get_total_days()
        
        return jsonify({
            **teacher,
            'attendance_percentage': percentage,
            'total_days': total_days,
            'present_count': len(present_dates),
            'absent_count': len(absent_dates),
            'present_dates': sorted(present_dates, reverse=True),
            'absent_dates': sorted(absent_dates, reverse=True),
            'attendance_history': attendance_history
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== STUDENT ROUTES ====================

@app.route('/students', methods=['GET'])
@login_required
def get_students():
    """Get all students with filters"""
    try:
        class_filter = request.args.get('class', '').strip()
        search = request.args.get('search', '').strip()
        
        students = get_all_students(
            class_filter=class_filter if class_filter else None,
            search=search if search else None
        )
        
        total_days = get_total_days()
        
        result = []
        for student in students:
            percentage = get_student_attendance_percentage(student['id'])
            result.append({
                'id': student['id'],
                'name': student['name'],
                'class': student['class'],
                'board': student['board'],
                'stream': student.get('stream'),
                'attendance_percentage': percentage
            })
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/student/<int:student_id>', methods=['GET'])
@login_required
def get_student_detail(student_id):
    """Get student details with full attendance history"""
    try:
        student = get_student_by_id(student_id)
        
        if not student:
            return jsonify({'error': 'Student not found'}), 404
        
        attendance_history = student.pop('attendance_history', [])
        
        present_dates = [a['date'] for a in attendance_history if a['status'] == 'PRESENT']
        absent_dates = [a['date'] for a in attendance_history if a['status'] == 'ABSENT']
        
        percentage = get_student_attendance_percentage(student_id)
        total_days = get_total_days()
        
        return jsonify({
            **student,
            'attendance_percentage': percentage,
            'total_days': total_days,
            'present_count': len(present_dates),
            'absent_count': len(absent_dates),
            'present_dates': sorted(present_dates, reverse=True),
            'absent_dates': sorted(absent_dates, reverse=True),
            'attendance_history': attendance_history
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== CLASS ROUTES ====================

@app.route('/classes', methods=['GET'])
@login_required
def get_classes():
    """Get class-wise attendance averages"""
    try:
        class_averages = get_class_averages()
        return jsonify(class_averages)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== SEARCH ROUTE ====================

@app.route('/search', methods=['GET'])
@login_required
def search():
    """Search students and teachers"""
    try:
        query = request.args.get('q', '').strip()
        
        if not query:
            return jsonify({'students': [], 'teachers': []})
        
        results = search_all(query)
        total_days = get_total_days()
        
        # Add percentages
        for student in results['students']:
            student['attendance_percentage'] = get_student_attendance_percentage(student['id'])
        
        for teacher in results['teachers']:
            teacher['attendance_percentage'] = get_teacher_attendance_percentage(teacher['id'])
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== SYNC HISTORY ====================

@app.route('/sync-history', methods=['GET'])
@login_required
def get_sync_history_route():
    """Get recent sync history"""
    try:
        limit = request.args.get('limit', 10, type=int)
        history = get_sync_history(limit)
        return jsonify(history)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Not found',
        'message': 'The requested resource was not found'
    }), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({
        'error': 'Internal server error',
        'message': 'Something went wrong on the server'
    }), 500

# ==================== INITIALIZATION ====================

# Initialize database on startup
with app.app_context():
    init_db()
    print("🚀 Lotus Academy Management System initialized")
    print("📋 Available endpoints:")
    print("   POST /login - User authentication")
    print("   POST /sync - Sync attendance from Drive")
    print("   GET  /stats - Dashboard statistics")
    print("   GET  /teachers - List teachers")
    print("   GET  /students - List students")
    print("   GET  /classes - Class averages")
    print("   GET  /search?q= - Search")
    print("   GET  /health - Health check")

# ==================== MAIN ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'production') != 'production'
    
    print(f"\n🌐 Starting server on port {port}")
    print(f"🔧 Debug mode: {debug}")
    print(f"📍 Local: http://localhost:{port}")
    print(f"📍 Health: http://localhost:{port}/health")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )