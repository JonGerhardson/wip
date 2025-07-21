import os
import requests
import json
import re
import fitz  # PyMuPDF library
import docx  # python-docx library
import hashlib
import sqlite3
import subprocess
import sys
import math
import shutil
from flask import Flask, request, jsonify
from flask_cors import CORS
from tqdm import tqdm

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# --- Configuration ---
LLM_URL = "http://localhost:1234/v1/chat/completions"
DATABASE_FILE = "file_organizer.db"
SUPPORTED_EXTENSIONS = ['.pdf', '.txt', '.docx', '.jpg', '.jpeg', '.png', '.gif', '.mp3', '.wav', '.m4a']

# --- Helper Functions ---
def is_exiftool_installed():
    """Check if exiftool is installed and available in the system's PATH."""
    return shutil.which("exiftool") is not None

# --- Database Setup ---
def init_db():
    """Initializes the SQLite database and creates/updates the 'files' table."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT UNIQUE NOT NULL,
            original_name TEXT NOT NULL,
            original_path TEXT NOT NULL,
            new_name TEXT,
            file_path TEXT,
            topic TEXT,
            summary TEXT,
            speakers TEXT,
            file_type TEXT,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Add metadata column if it doesn't exist for backward compatibility
    try:
        cursor.execute("ALTER TABLE files ADD COLUMN metadata TEXT")
    except sqlite3.OperationalError:
        pass # Column already exists
    # Add original_path column
    try:
        cursor.execute("ALTER TABLE files ADD COLUMN original_path TEXT")
    except sqlite3.OperationalError:
        pass # Column already exists
    conn.commit()
    conn.close()

# --- File Processing Utilities ---

def calculate_file_hash(file_path, block_size=65536):
    hasher = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            buf = f.read(block_size)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(block_size)
        return hasher.hexdigest()
    except Exception as e:
        print(f"Error calculating hash for {file_path}: {e}")
        return None

def get_text_from_pdf(file_path):
    try:
        with fitz.open(file_path) as doc:
            return "".join(page.get_text() for page in doc).strip()
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
        return None

def get_text_from_txt(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error reading TXT {file_path}: {e}")
        return None

def get_text_from_docx(file_path):
    try:
        doc = docx.Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs]).strip()
    except Exception as e:
        print(f"Error reading DOCX {file_path}: {e}")
        return None

def get_file_content(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf': return get_text_from_pdf(file_path)
    elif ext == '.txt': return get_text_from_txt(file_path)
    elif ext == '.docx': return get_text_from_docx(file_path)
    return "" # Return empty string for non-text files, metadata will be used

def get_external_metadata(file_path):
    """Extracts metadata using ExifTool."""
    if not is_exiftool_installed():
        return {"Error": "ExifTool not found. Please install it to extract rich metadata."}
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-G", file_path],
            capture_output=True, text=True, check=True
        )
        # ExifTool returns a list of dictionaries, we only need the first one
        metadata = json.loads(result.stdout)[0]
        return metadata
    except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError) as e:
        print(f"Error getting metadata for {file_path}: {e}")
        return {"Error": f"Could not extract metadata. {e}"}

def get_llm_analysis(text_content, metadata, directory_path):
    """Sends a request to the local LLM for analysis."""
    known_names = []
    names_file_path = os.path.join(directory_path, 'names.txt')
    if os.path.exists(names_file_path):
        with open(names_file_path, 'r', encoding='utf-8') as f:
            known_names = [line.strip() for line in f if line.strip()]

    system_prompt = """You are an expert assistant for analyzing document content and metadata. Your task is to carefully read the provided text and file metadata to extract information. Use the metadata to enrich your understanding.
You have a 'Known Correct Names' list. If you see garbled or phonetically similar names, you MUST use the correct spelling from the list.
For transcripts, prioritize extracting the date, setting, and a clear subject.
Format your response as a single, valid JSON object with the following keys:
- "topic": A concise, descriptive topic (5 words maximum).
- "synopsis": A brief summary (max 2-3 sentences).
- "speakers": A JSON array of strings listing speakers or key people. Use corrected names.
- "date": The date of the document/event in YYYY-MM-DD format (from text or metadata). Default to "N/A".
- "setting": The setting or event type (e.g., "City Council Meeting"). Default to "N/A".
- "subject": A clear, one-line subject of the meeting/document. Default to "N/A".
Ensure the output is only the JSON object itself, with no extra text or markdown."""

    metadata_str = json.dumps(metadata, indent=2, sort_keys=True)
    user_prompt_content = f"File Metadata:\n```json\n{metadata_str}\n```\n\n"
    if text_content:
        user_prompt_content += f"Document Text:\n```\n{text_content}\n```\n"
    else:
        user_prompt_content += "Document contains no text. Analyze based on metadata only.\n"

    if known_names:
        names_list_str = "\n".join([f"- {name}" for name in known_names])
        user_prompt_content = f"Reference List of Known Correct Names:\n{names_list_str}\n\n---\n\n{user_prompt_content}"

    headers = {"Content-Type": "application/json"}
    data = {
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt_content}],
        "temperature": 0.1, "max_tokens": 800, "stream": False
    }

    try:
        response = requests.post(LLM_URL, headers=headers, json=data, timeout=120)
        response.raise_for_status()
        llm_output = response.json()['choices'][0]['message']['content']
        llm_output = llm_output.strip().strip('```json').strip('```').strip()
        return json.loads(llm_output)
    except Exception as e:
        print(f"LLM analysis failed: {e}")
        return None

def sanitize_filename(name):
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
    return re.sub(r'\s+', '-', sanitized).strip().lower()[:100]

# --- API Endpoints ---

@app.route('/process_files', methods=['POST'])
def process_files_endpoint():
    data = request.get_json()
    directory_path = data.get('directory_path')

    if not directory_path or not os.path.isdir(directory_path):
        return jsonify({"error": f"Directory '{directory_path}' not found."}), 404

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    files_to_scan = []
    for root, _, files in os.walk(directory_path):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS:
                files_to_scan.append(os.path.join(root, filename))

    if not files_to_scan:
        return jsonify([]), 200

    processed_files_for_review = []
    print(f"\nFound {len(files_to_scan)} supported files. Checking against database...")
    for file_path in tqdm(files_to_scan, desc="Processing Files", unit="file"):
        file_ext = os.path.splitext(file_path)[1]
        filename = os.path.basename(file_path)
        
        if not os.path.isfile(file_path): continue

        file_hash = calculate_file_hash(file_path)
        if not file_hash: continue

        cursor.execute("SELECT id FROM files WHERE file_hash = ?", (file_hash,))
        if cursor.fetchone(): continue

        text_content = get_file_content(file_path)
        metadata = get_external_metadata(file_path)
        
        llm_analysis = get_llm_analysis(text_content, metadata, directory_path)
        if not llm_analysis:
            print(f"Skipping {filename}: LLM analysis failed.")
            continue

        topic = llm_analysis.get('topic', 'unknown-topic')
        synopsis = llm_analysis.get('synopsis', 'No synopsis available.')
        speakers = json.dumps(llm_analysis.get('speakers', []))
        metadata_json = json.dumps(metadata)

        cursor.execute(
            "INSERT INTO files (file_hash, original_name, original_path, topic, summary, speakers, file_type, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (file_hash, filename, file_path, topic, synopsis, speakers, file_ext, metadata_json)
        )
        conn.commit()

        proposed_name = f"{sanitize_filename(topic)}{file_ext}"
        if file_ext == '.txt':
            date, setting, subject = llm_analysis.get('date'), llm_analysis.get('setting'), llm_analysis.get('subject')
            name_parts = [p for p in [date, setting, subject] if p and p != "N/A"]
            if len(name_parts) > 1:
                proposed_name = f"{'-'.join(sanitize_filename(p) for p in name_parts)}{file_ext}"

        processed_files_for_review.append({
            "originalName": filename,
            "originalPath": file_path,
            "llmTopic": topic,
            "synopsis": synopsis,
            "speakers": llm_analysis.get('speakers', []),
            "proposedName": proposed_name,
            "fileType": file_ext
        })

    conn.close()
    print(f"Processing complete. Found {len(processed_files_for_review)} new files to review.")
    return jsonify(processed_files_for_review), 200

@app.route('/save_all_changes', methods=['POST'])
def save_all_changes_endpoint():
    data = request.get_json()
    renames = data.get('renames', [])

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    successful_renames = 0
    failed_renames = []

    for item in tqdm(renames, desc="Applying Renames", unit="file"):
        original_path = item.get('original_path')
        new_name = item.get('proposed_new_name')

        if not original_path or not new_name: continue

        if not os.path.exists(original_path):
            failed_renames.append({"original": os.path.basename(original_path), "reason": "Original file not found."})
            continue
        
        # Handle deletion marking
        if item.get('status') == 'marked_for_deletion':
            new_name = f"DELETE_{os.path.basename(original_path)}"

        new_path = os.path.join(os.path.dirname(original_path), new_name)

        try:
            os.rename(original_path, new_path)

            file_hash = calculate_file_hash(new_path)
            if file_hash:
                cursor.execute(
                    "UPDATE files SET new_name = ?, file_path = ? WHERE file_hash = ?",
                    (new_name, new_path, file_hash)
                )
                conn.commit()
            successful_renames += 1
        except Exception as e:
            failed_renames.append({"original": os.path.basename(original_path), "reason": str(e)})
    
    conn.close()
    return jsonify({"successful_renames": successful_renames, "failed_renames": failed_renames}), 200

@app.route('/search', methods=['GET'])
def search_files_endpoint():
    query = request.args.get('q', '')
    if not query: return jsonify([])
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    search_term = f"%{query}%"
    cursor.execute("SELECT * FROM files WHERE topic LIKE ? OR summary LIKE ? OR original_name LIKE ? OR new_name LIKE ? OR speakers LIKE ? OR metadata LIKE ? ORDER BY created_at DESC",
                   (search_term, search_term, search_term, search_term, search_term, search_term))
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(results)

@app.route('/browse_files', methods=['GET'])
def browse_files_endpoint():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(id) FROM files")
    total_files = cursor.fetchone()[0]
    total_pages = math.ceil(total_files / per_page)
    offset = (page - 1) * per_page
    cursor.execute("SELECT * FROM files ORDER BY created_at DESC LIMIT ? OFFSET ?", (per_page, offset))
    files = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"files": files, "total_pages": total_pages, "current_page": page, "total_files": total_files})

@app.route('/open_file', methods=['POST'])
def open_file_endpoint():
    data = request.get_json()
    file_path = data.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found or path is invalid."}), 404
    try:
        real_path = os.path.realpath(file_path)
        if sys.platform == "win32": os.startfile(real_path)
        elif sys.platform == "darwin": subprocess.call(["open", real_path])
        else: subprocess.call(["xdg-open", real_path])
        return jsonify({"message": "File opening command sent."}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to open file: {e}"}), 500

@app.route('/get_names', methods=['POST'])
def get_names_endpoint():
    data = request.get_json()
    directory_path = data.get('directory_path')
    if not directory_path or not os.path.isdir(directory_path):
        return jsonify({"error": "Directory path is required."}), 400
    names_file_path = os.path.join(directory_path, 'names.txt')
    if os.path.exists(names_file_path):
        with open(names_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"names_content": content}), 200
    else:
        return jsonify({"names_content": ""}), 200

@app.route('/save_names', methods=['POST'])
def save_names_endpoint():
    data = request.get_json()
    directory_path = data.get('directory_path')
    names_content = data.get('names_content', '')
    if not directory_path or not os.path.isdir(directory_path):
        return jsonify({"error": "Directory path is required."}), 400
    names_file_path = os.path.join(directory_path, 'names.txt')
    try:
        with open(names_file_path, 'w', encoding='utf-8') as f:
            f.write(names_content)
        return jsonify({"message": "Names file saved successfully."}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to save names file: {e}"}), 500

@app.route('/clear_directory_cache', methods=['POST'])
def clear_directory_cache_endpoint():
    data = request.get_json()
    directory_path = data.get('directory_path')
    if not directory_path or not os.path.isdir(directory_path):
        return jsonify({"error": "Invalid or missing directory path."}), 400
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        path_pattern = os.path.join(directory_path, '') + '%'
        cursor.execute("DELETE FROM files WHERE original_path LIKE ?", (path_pattern,))
        conn.commit()
        deleted_rows = cursor.rowcount
        conn.close()
        return jsonify({"message": f"Cleared {deleted_rows} records for directory."}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to clear directory cache: {e}"}), 500

@app.route('/clear_database', methods=['POST'])
def clear_database_endpoint():
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM files")
        conn.commit()
        conn.close()
        return jsonify({"message": "Database cleared successfully."}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to clear database: {e}"}), 500

if __name__ == '__main__':
    if not is_exiftool_installed():
        print("\n--- WARNING ---")
        print("ExifTool is not found on your system's PATH.")
        print("Please install it from https://exiftool.org/ to enable rich metadata extraction.")
        print("The application will run without it, but metadata features will be disabled.")
        print("---------------\n")
    init_db()
    app.run(debug=True, port=5000)
