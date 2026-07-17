# app.py - Standalone Code Analyzer Backend (No Firebase)
from datetime import datetime
import os
import shutil
import socket
import tempfile
import threading
import uuid

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from git import Repo

from language_checks import (
    analyze_source_file,
    detect_language_from_content,
    get_supported_extensions,
    get_supported_language_labels,
    read_text_file,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'code-analyzer-secret-key')

CORS(app, origins=[
    'http://localhost:5500',
    'http://127.0.0.1:5500',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://analyzec1-production.up.railway.app',
    'https://cd-tracker-nine.vercel.app',
    'http://localhost:8080/api'
], supports_credentials=True, allow_headers=['Content-Type', 'Authorization'])

analysis_storage = {}


def analyze_file(file_path, language):
    """Analyze a single supported file."""
    return analyze_source_file(file_path, language)


def detect_branch(repo_url):
    """Detect the default branch of a GitHub repository."""
    try:
        parts = repo_url.rstrip('/').split('/')
        if len(parts) >= 5:
            user = parts[-2]
            repo_name = parts[-1].replace('.git', '')

            api_url = f"https://api.github.com/repos/{user}/{repo_name}"
            headers = {}
            if os.getenv('GITHUB_TOKEN'):
                headers['Authorization'] = f"token {os.getenv('GITHUB_TOKEN')}"

            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                repo_info = response.json()
                return repo_info.get('default_branch', 'main')
    except Exception as exc:
        print(f"Could not detect default branch: {exc}")

    return 'main'


def analyze_repository_background(analysis_id, repo_url, branch):
    """Background task for repository analysis."""
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        print(f"Cloning {repo_url} to {temp_dir}")

        analysis_storage[analysis_id]['status'] = 'cloning'

        branches_to_try = [branch, 'main', 'master']
        cloned_successfully = False
        used_branch = None

        for try_branch in branches_to_try:
            try:
                print(f"Trying branch: {try_branch}")
                Repo.clone_from(repo_url, temp_dir, branch=try_branch, depth=1)
                used_branch = try_branch
                cloned_successfully = True
                print(f"Cloned using branch: {try_branch}")
                break
            except Exception as clone_error:
                print(f"Failed with branch {try_branch}: {clone_error}")
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    temp_dir = tempfile.mkdtemp()

        if not cloned_successfully:
            raise Exception(f"Failed to clone repository. Tried branches: {branches_to_try}")

        analysis_storage[analysis_id]['status'] = 'analyzing'
        analysis_storage[analysis_id]['branch_used'] = used_branch

        source_files = []
        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '.git' and d != '__pycache__']

            for file_name in files:
                file_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(file_path, temp_dir)

                try:
                    content = read_text_file(file_path)
                except Exception:
                    content = ''

                language = detect_language_from_content(content, file_name=file_name)
                if language:
                    source_files.append((file_path, rel_path, language, file_name, content))

        print(f"Found {len(source_files)} supported source files")

        if not source_files:
            analysis_storage[analysis_id]['status'] = 'completed'
            analysis_storage[analysis_id]['summary'] = {
                'total_files': 0,
                'errors_count': 0,
                'warnings_count': 0,
                'branch_used': used_branch,
            }
            analysis_storage[analysis_id]['files'] = []
            return

        total_errors = 0
        total_warnings = 0
        analyzed_files = []

        for file_path, rel_path, language, file_name, content in source_files:
            try:
                analysis_result = analyze_file(file_path, language)

                file_result = {
                    'file_path': rel_path.replace('\\', '/'),
                    'file_name': file_name,
                    'language': language,
                    'code': content,
                    'analysis_signal': analysis_result['analysis_signal'],
                    'errors': analysis_result['errors'],
                    'warnings': analysis_result['warnings'],
                    'errors_count': len(analysis_result['errors']),
                    'warnings_count': len(analysis_result['warnings']),
                }

                analyzed_files.append(file_result)
                total_errors += len(analysis_result['errors'])
                total_warnings += len(analysis_result['warnings'])

                status_label = 'ERROR' if analysis_result['errors'] else 'WARN' if analysis_result['warnings'] else 'OK'
                print(f"{status_label} {rel_path} (Errors: {len(analysis_result['errors'])}, Warnings: {len(analysis_result['warnings'])})")

            except Exception as exc:
                print(f"Error processing {rel_path}: {exc}")
                file_result = {
                    'file_path': rel_path.replace('\\', '/'),
                    'file_name': file_name,
                    'language': language,
                    'code': content or f"// Error processing file: {exc}",
                    'analysis_signal': None,
                    'errors': [{'line': 0, 'message': f'Processing error: {exc}', 'type': 'error'}],
                    'warnings': [],
                    'errors_count': 1,
                    'warnings_count': 0,
                }
                analyzed_files.append(file_result)
                total_errors += 1

        analysis_storage[analysis_id]['status'] = 'completed'
        analysis_storage[analysis_id]['summary'] = {
            'total_files': len(source_files),
            'errors_count': total_errors,
            'warnings_count': total_warnings,
            'branch_used': used_branch,
        }
        analysis_storage[analysis_id]['files'] = analyzed_files

        print(f"Analysis complete for {analysis_id}")
        print(f"Total files: {len(source_files)}")
        print(f"Total errors: {total_errors}")
        print(f"Total warnings: {total_warnings}")

    except Exception as exc:
        print(f"Background analysis failed: {exc}")
        analysis_storage[analysis_id]['status'] = 'error'
        analysis_storage[analysis_id]['error'] = str(exc)
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("Cleaned up temporary directory")


@app.route('/api/analyze', methods=['POST'])
def analyze_repository():
    """Analyze a GitHub repository."""
    try:
        data = request.json or {}
        repo_url = data.get('repo_url')

        if not repo_url:
            return jsonify({'success': False, 'error': 'Repository URL required'}), 400

        analysis_id = str(uuid.uuid4())
        branch = detect_branch(repo_url)

        analysis_storage[analysis_id] = {
            'id': analysis_id,
            'repo_url': repo_url,
            'branch': branch,
            'status': 'pending',
            'created_at': datetime.utcnow().isoformat(),
            'summary': None,
            'files': [],
        }

        thread = threading.Thread(
            target=analyze_repository_background,
            args=(analysis_id, repo_url, branch),
            daemon=True,
        )
        thread.start()

        return jsonify({
            'success': True,
            'analysis_id': analysis_id,
            'branch_used': branch,
            'message': 'Analysis started',
        })

    except Exception as exc:
        print(f"Error: {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/analysis/<analysis_id>', methods=['GET'])
def get_analysis(analysis_id):
    """Get analysis results."""
    try:
        if analysis_id not in analysis_storage:
            return jsonify({'success': False, 'error': 'Analysis not found'}), 404

        analysis = analysis_storage[analysis_id]
        response = {
            'success': True,
            'analysis_id': analysis_id,
            'status': analysis['status'],
            'repo_url': analysis['repo_url'],
        }

        if analysis['status'] == 'completed':
            response['summary'] = analysis['summary']
            response['files'] = analysis['files']
        elif analysis['status'] == 'error':
            response['error'] = analysis.get('error', 'Unknown error')

        return jsonify(response)

    except Exception as exc:
        print(f"Error: {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'Code Analyzer API',
    })


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'name': 'Code Analyzer API',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': [
            'POST /api/analyze - Analyze a GitHub repository',
            'GET /api/analysis/<analysis_id> - Get analysis results',
            'GET /api/health - Health check',
        ],
        'supported_languages': get_supported_language_labels(),
        'supported_extensions': get_supported_extensions(),
    })


def find_free_port():
    """Find a free port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def cleanup_old_analyses():
    """Remove analyses older than 1 hour."""
    now = datetime.utcnow()
    to_delete = []
    for analysis_id, analysis in analysis_storage.items():
        created_at = datetime.fromisoformat(analysis['created_at'])
        if (now - created_at).total_seconds() > 3600:
            to_delete.append(analysis_id)

    for analysis_id in to_delete:
        del analysis_storage[analysis_id]

    if to_delete:
        print(f"Cleaned up {len(to_delete)} old analyses")


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))

    if not os.getenv('RAILWAY_ENVIRONMENT'):
        ports_to_try = [5000, 5001, 8080, 3000, 8000, 8888]
        selected_port = None

        print("Checking available ports...")
        for test_port in ports_to_try:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(('127.0.0.1', test_port))
                    selected_port = test_port
                    print(f"Port {test_port} is available")
                    break
            except OSError:
                print(f"Port {test_port} is in use")

        if selected_port is None:
            selected_port = find_free_port()
            print(f"Using automatically assigned port: {selected_port}")

        print("=" * 60)
        print("Code Analyzer Backend Server")
        print("=" * 60)
        print(f"Server running on: http://127.0.0.1:{selected_port}")
        print("API Endpoints:")
        print("  POST /api/analyze - Analyze repository")
        print("  GET /api/analysis/<id> - Get results")
        print("  GET /api/health - Health check")
        print("=" * 60)

        app.run(debug=True, port=selected_port, host='127.0.0.1')
    else:
        print("=" * 60)
        print("Code Analyzer Backend Server (Production)")
        print("=" * 60)
        print(f"Server running on port: {port}")
        print("API Endpoints:")
        print("  POST /api/analyze - Analyze repository")
        print("  GET /api/analysis/<id> - Get results")
        print("  GET /api/health - Health check")
        print("=" * 60)

        app.run(debug=False, port=port, host='0.0.0.0')
