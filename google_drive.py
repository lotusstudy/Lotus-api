"""
Google Drive Integration for Lotus Academy
Fetches attendance Excel files from Google Drive
"""
import os
import io
import re
import json
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# Get credentials from environment (Render) or file (local)
def get_credentials():
    """Get Google credentials from environment or file"""
    
    # For Render deployment - use environment variable
    if os.environ.get('GOOGLE_CREDENTIALS'):
        try:
            creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
            return service_account.Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
        except Exception as e:
            print(f"Error parsing GOOGLE_CREDENTIALS: {e}")
            raise
    
    # For local development - use JSON file
    service_account_file = os.path.join(os.path.dirname(__file__), 'service_account.json')
    if os.path.exists(service_account_file):
        return service_account.Credentials.from_service_account_file(
            service_account_file, scopes=SCOPES
        )
    
    raise Exception(
        "No Google credentials found. Either:\n"
        "1. Set GOOGLE_CREDENTIALS environment variable (Render)\n"
        "2. Add service_account.json file (local development)"
    )

def get_folder_id():
    """Get Google Drive folder ID from environment or config"""
    folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '')
    if not folder_id:
        # Try to read from config file (local dev)
        config_file = os.path.join(os.path.dirname(__file__), 'drive_config.json')
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
                folder_id = config.get('folder_id', '')
    
    if not folder_id:
        raise Exception(
            "No folder ID configured. Either:\n"
            "1. Set GOOGLE_DRIVE_FOLDER_ID environment variable\n"
            "2. Create drive_config.json with 'folder_id' key"
        )
    
    return folder_id

def get_drive_service():
    """Authenticate and return Google Drive service"""
    try:
        credentials = get_credentials()
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        print(f"❌ Error creating Drive service: {e}")
        raise

def list_files_in_folder(folder_id=None, file_type='excel'):
    """
    List all files from Google Drive folder
    
    Args:
        folder_id: Google Drive folder ID (optional)
        file_type: 'excel' or 'all'
    
    Returns:
        List of file objects with id, name, createdTime, modifiedTime
    """
    try:
        service = get_drive_service()
        
        if folder_id is None:
            folder_id = get_folder_id()
        
        # Build query
        if file_type == 'excel':
            query = "mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'"
        else:
            query = None
        
        if folder_id:
            if query:
                query += f" and '{folder_id}' in parents"
            else:
                query = f"'{folder_id}' in parents"
        
        # Fetch files
        all_files = []
        page_token = None
        
        while True:
            results = service.files().list(
                q=query,
                pageSize=100,
                fields="nextPageToken, files(id, name, createdTime, modifiedTime, size)",
                orderBy="modifiedTime desc",
                pageToken=page_token
            ).execute()
            
            files = results.get('files', [])
            all_files.extend(files)
            
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        
        print(f"📁 Found {len(all_files)} files in Drive folder")
        return all_files
        
    except Exception as e:
        print(f"❌ Error listing files: {e}")
        return []

def download_excel(file_id):
    """
    Download an Excel file from Google Drive
    
    Args:
        file_id: Google Drive file ID
    
    Returns:
        BytesIO buffer containing the Excel file
    """
    try:
        service = get_drive_service()
        request = service.files().get_media(fileId=file_id)
        
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        file_buffer.seek(0)
        return file_buffer
        
    except Exception as e:
        print(f"❌ Error downloading file {file_id}: {e}")
        raise

def extract_date_from_filename(filename):
    """
    Extract date from filename
    
    Examples:
        'Class_Class 12_2026-04-30.xlsx' → '2026-04-30'
        'Teachers_2026-04-30.xlsx' → '2026-04-30'
    """
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    return None

def extract_class_from_filename(filename):
    """
    Extract class number from student filename
    
    Example:
        'Class_Class 12_2026-04-30.xlsx' → '12'
    """
    match = re.search(r'Class_Class[_\s]+(\d+)', filename)
    if match:
        return match.group(1)
    return None

def is_student_file(filename):
    """Check if file is a student attendance file"""
    return filename.lower().startswith('class_')

def is_teacher_file(filename):
    """Check if file is a teacher attendance file"""
    return filename.lower().startswith('teachers_')

def process_student_excel(file_buffer, date):
    """
    Process student attendance Excel file
    
    Returns:
        List of dictionaries with student attendance data
    """
    try:
        # Read raw Excel data
        df = pd.read_excel(file_buffer, engine='openpyxl', header=None)
        
        # Find the data start row
        data_start = 0
        for i, row in df.iterrows():
            first_cell = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            if first_cell and not first_cell.startswith('🏫') and not first_cell.startswith('Attendance'):
                data_start = i
                break
        
        # Read again from data start
        file_buffer.seek(0)
        df = pd.read_excel(file_buffer, engine='openpyxl', skiprows=data_start)
        
        results = []
        
        for _, row in df.iterrows():
            try:
                # Skip empty rows
                if pd.isna(row.iloc[0]):
                    continue
                
                name = str(row.iloc[0]).strip()
                
                # Skip header/invalid rows
                if not name or name in ['0', '1', '2', '3'] or name.startswith('0') and len(name) <= 2:
                    continue
                
                # Extract data based on column count
                if len(row) >= 7:
                    student_class = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else 'Unknown'
                    board = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else 'Unknown'
                    stream = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) and str(row.iloc[3]).strip().lower() != 'nan' else None
                    time_val = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else '00:00:00'
                    status = str(row.iloc[6]).strip() if pd.notna(row.iloc[6]) else 'ABSENT'
                elif len(row) >= 5:
                    student_class = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else 'Unknown'
                    board = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else 'Unknown'
                    stream = None
                    time_val = '00:00:00'
                    status = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else 'ABSENT'
                else:
                    continue
                
                # Normalize status
                status_upper = status.upper()
                if 'PRESENT' in status_upper:
                    status = 'PRESENT'
                elif 'ABSENT' in status_upper:
                    status = 'ABSENT'
                else:
                    status = 'ABSENT'
                
                # Normalize time
                if time_val in ['00:00:00', '0', 'nan', '', 'None']:
                    time_val = None
                
                results.append({
                    'name': name,
                    'class': student_class,
                    'board': board,
                    'stream': stream,
                    'date': date,
                    'time': time_val,
                    'status': status
                })
                
            except Exception as e:
                print(f"  ⚠️ Error processing student row: {e}")
                continue
        
        return results
        
    except Exception as e:
        print(f"❌ Error processing student Excel: {e}")
        return []

def process_teacher_excel(file_buffer, date):
    """
    Process teacher attendance Excel file
    
    Returns:
        List of dictionaries with teacher attendance data
    """
    try:
        df = pd.read_excel(file_buffer, engine='openpyxl', header=None)
        
        # Find data start
        data_start = 0
        for i, row in df.iterrows():
            first_cell = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            if first_cell and not first_cell.startswith('🏫') and not first_cell.startswith('Attendance'):
                data_start = i
                break
        
        file_buffer.seek(0)
        df = pd.read_excel(file_buffer, engine='openpyxl', skiprows=data_start)
        
        results = []
        
        for _, row in df.iterrows():
            try:
                if pd.isna(row.iloc[0]):
                    continue
                
                name = str(row.iloc[0]).strip()
                
                if not name or name in ['0', '1', '2']:
                    continue
                
                # Extract data
                if len(row) >= 4:
                    subject = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else 'Unknown'
                    time_val = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else '00:00:00'
                    status = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else 'ABSENT'
                elif len(row) >= 3:
                    subject = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else 'Unknown'
                    time_val = '00:00:00'
                    status = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else 'ABSENT'
                else:
                    continue
                
                # Normalize status
                status_upper = status.upper()
                if 'PRESENT' in status_upper:
                    status = 'PRESENT'
                elif 'ABSENT' in status_upper:
                    status = 'ABSENT'
                else:
                    status = 'ABSENT'
                
                if time_val in ['00:00:00', '0', 'nan', '', 'None']:
                    time_val = None
                
                results.append({
                    'name': name,
                    'subject': subject,
                    'date': date,
                    'time': time_val,
                    'status': status
                })
                
            except Exception as e:
                print(f"  ⚠️ Error processing teacher row: {e}")
                continue
        
        return results
        
    except Exception as e:
        print(f"❌ Error processing teacher Excel: {e}")
        return []

def test_connection():
    """Test Google Drive connection"""
    try:
        service = get_drive_service()
        folder_id = get_folder_id()
        files = list_files_in_folder(folder_id)
        
        print(f"✅ Google Drive connected successfully!")
        print(f"📁 Folder ID: {folder_id}")
        print(f"📄 Files found: {len(files)}")
        
        for f in files[:5]:
            size_mb = int(f.get('size', 0)) / (1024 * 1024)
            print(f"   - {f['name']} ({size_mb:.2f} MB)")
        
        if len(files) > 5:
            print(f"   ... and {len(files) - 5} more files")
        
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

if __name__ == '__main__':
    test_connection()