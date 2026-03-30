# app.py - Complete Version with Classroom Support
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from datetime import datetime
import os
import tempfile
import shutil
import subprocess
import threading
import re
from git import Repo
import firebase_admin
from firebase_admin import credentials, firestore
import json
import socket
import sys

# Initialize Firebase Admin SDK
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase initialized successfully")
except Exception as e:
    print(f"❌ Firebase initialization failed: {e}")
    print("Make sure serviceAccountKey.json exists in the current directory")
    sys.exit(1)

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-please-change-in-production'

# Enable CORS for all routes
CORS(app, origins='*')

# Collections
classrooms_ref = db.collection('Classrooms')
professors_ref = db.collection('professors')
students_ref = db.collection('Students')
activitys_ref = db.collection('Activitys')
prof_submit_ref = db.collection('profSubmit')
reviews_ref = db.collection('reviews')
analysis_results_ref = db.collection('Analysis_results')

def clean_error_message(error_line):
    """Extract error message"""
    import re
    
    # Try to extract the main error with line number
    main_error = re.search(r':(\d+):(\d+):\s+(error|warning):\s+(.*)$', error_line, re.IGNORECASE)
    if main_error:
        line_num = int(main_error.group(1))
        msg_type = main_error.group(3).lower()
        message = main_error.group(4).strip()
        message = re.sub(r'\s*\[.*?\]$', '', message).strip()
        
        return {
            'line': line_num,
            'type': msg_type,
            'message': message
        }
    
    # Try without column number
    simple_error = re.search(r':(\d+):\s+(error|warning):\s+(.*)$', error_line, re.IGNORECASE)
    if simple_error:
        line_num = int(simple_error.group(1))
        msg_type = simple_error.group(2).lower()
        message = simple_error.group(3).strip()
        message = re.sub(r'\s*\[.*?\]$', '', message).strip()
        
        return {
            'line': line_num,
            'type': msg_type,
            'message': message
        }
    
    # Last resort - extract error without line number
    if 'error:' in error_line.lower():
        parts = error_line.lower().split('error:')
        return {
            'line': 0,
            'type': 'error',
            'message': parts[-1].strip()
        }
    elif 'warning:' in error_line.lower():
        parts = error_line.lower().split('warning:')
        return {
            'line': 0,
            'type': 'warning',
            'message': parts[-1].strip()
        }
    
    return None

def analyze_file(file_path, language, file_content):
    """Analyze a single file"""
    errors = []
    warnings = []
    
    try:
        if language == 'c':
            cmd = ['gcc', '-fsyntax-only', '-Wall', '-Wextra', '-std=c11', file_path]
        elif language == 'cpp':
            cmd = ['g++', '-fsyntax-only', '-Wall', '-Wextra', '-std=c++14', file_path]
        else:
            return errors, warnings
        
        # Run compilation
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        # Parse ALL errors and warnings from stderr
        seen_messages = set()
        
        for line in process.stderr.split('\n'):
            if not line.strip():
                continue
            
            cleaned = clean_error_message(line)
            if cleaned is None:
                continue
            
            # Create unique key for this message
            msg_key = f"{cleaned['line']}:{cleaned['type']}:{cleaned['message']}"
            if msg_key in seen_messages:
                continue
            
            seen_messages.add(msg_key)
            
            if cleaned['type'] == 'error':
                errors.append({
                    'line': cleaned['line'],
                    'message': cleaned['message'],
                    'type': 'error'
                })
            elif cleaned['type'] == 'warning':
                warnings.append({
                    'line': cleaned['line'],
                    'message': cleaned['message'],
                    'type': 'warning'
                })
        
        # Sort by line number
        errors.sort(key=lambda x: x['line'])
        warnings.sort(key=lambda x: x['line'])
        
    except subprocess.TimeoutExpired:
        errors.append({'line': 0, 'message': 'Compilation timeout - file may be too complex', 'type': 'error'})
    except FileNotFoundError:
        errors.append({'line': 0, 'message': f'Compiler not found. Please install {"gcc" if language=="c" else "g++"}.', 'type': 'error'})
    except Exception as e:
        errors.append({'line': 0, 'message': f'Analysis error: {str(e)}', 'type': 'error'})
    
    return errors, warnings

@app.route('/api/classroom/<classroom_id>', methods=['GET'])
def get_classroom_info(classroom_id):
    """Get classroom information"""
    try:
        classroom_doc = classrooms_ref.document(classroom_id).get()
        if not classroom_doc.exists:
            return jsonify({'success': False, 'error': 'Classroom not found'}), 404
        
        classroom = classroom_doc.to_dict()
        classroom['classroomID'] = classroom_id
        
        return jsonify({'success': True, 'classroom': classroom})
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/students/<professor_id>', methods=['GET'])
def get_students_by_professor(professor_id):
    """Get all students for a professor"""
    try:
        print(f"📡 Fetching students for professor: {professor_id}")
        
        # Check if professor exists
        professor_doc = professors_ref.document(professor_id).get()
        if not professor_doc.exists:
            print(f"❌ Professor not found: {professor_id}")
            return jsonify({
                'success': False, 
                'error': f'Professor with ID {professor_id} not found'
            }), 404
        
        # Get all students with this professor ID
        students = []
        students_snapshot = students_ref.where('professorID', '==', professor_id).stream()
        
        for doc in students_snapshot:
            student = doc.to_dict()
            student['StudentID'] = doc.id
            students.append(student)
        
        print(f"✅ Found {len(students)} students for professor {professor_id}")
        
        return jsonify({
            'success': True,
            'students': students
        })
        
    except Exception as e:
        print(f"❌ Error in get_students_by_professor: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/activities/<student_id>', methods=['GET'])
def get_student_activities(student_id):
    """Get all activities for a student with classroom info"""
    try:
        print(f"📡 Fetching activities for student: {student_id}")
        
        # Check if student exists
        student_doc = students_ref.document(student_id).get()
        if not student_doc.exists:
            print(f"❌ Student not found: {student_id}")
            return jsonify({
                'success': False, 
                'error': f'Student with ID {student_id} not found'
            }), 404
        
        student_data = student_doc.to_dict()
        classroom_id = student_data.get('classroomID', 'CLASS101')
        
        # Get classroom info
        classroom_doc = classrooms_ref.document(classroom_id).get()
        classroom_info = classroom_doc.to_dict() if classroom_doc.exists else {}
        
        print(f"✅ Found student: {student_data.get('name')} - Classroom: {classroom_id}")
        
        # Get all activities for this student
        activities = []
        activities_snapshot = activitys_ref.where('StudentID', '==', student_id).stream()
        
        activities_list = list(activities_snapshot)
        print(f"📚 Found {len(activities_list)} activities for student {student_id}")
        
        for doc in activities_list:
            activity = doc.to_dict()
            activity['ActivityID'] = activity.get('ActivityID', doc.id)
            
            # Get submission for this activity
            submit_id = f"{student_id}_{activity['ActivityID']}"
            submit_doc = prof_submit_ref.document(submit_id).get()
            
            activity_data = {
                "activity_id": activity["ActivityID"],
                "title": activity["ActivityTitle"],
                "description": activity.get("description", ""),
                "due_date": activity["due_date"],
                "difficulty": activity["difficulty"],
                "language": activity["language"],
                "repo_url": activity["repo_url"],
                "branch": activity.get("branch", "main"),
                "classroomID": activity.get("classroomID", classroom_id),
                "classroomName": classroom_info.get('name', 'Programming Fundamentals'),
                "status": "pending",
                "grade": None,
                "feedback": None,
                "submit_id": None,
                "errors_count": 0,
                "warnings_count": 0,
                "total_files": 0
            }
            
            if submit_doc.exists:
                submission = submit_doc.to_dict()
                activity_data["submit_id"] = submit_id
                activity_data["status"] = submission.get("status", "pending")
                
                # Get review
                review_doc = reviews_ref.document(submit_id).get()
                if review_doc.exists:
                    review = review_doc.to_dict()
                    activity_data["grade"] = review.get("grade")
                    activity_data["feedback"] = review.get("feedback")
                    if review.get("status") == "completed":
                        activity_data["status"] = "reviewed"
                
                # Get analysis results
                analysis_snapshot = analysis_results_ref.where("submit_id", "==", submit_id).stream()
                
                total_errors = 0
                total_warnings = 0
                file_count = 0
                for analysis_doc in analysis_snapshot:
                    file_count += 1
                    result = analysis_doc.to_dict()
                    total_errors += len([e for e in result.get("errors", []) if e.get('type') == 'error'])
                    total_warnings += len(result.get("warnings", []))
                
                activity_data["errors_count"] = total_errors
                activity_data["warnings_count"] = total_warnings
                activity_data["total_files"] = file_count
            
            activities.append(activity_data)
            print(f"   • {activity_data['title']} - Status: {activity_data['status']}")
        
        return jsonify({
            "success": True, 
            "activities": activities, 
            "student": student_data,
            "classroom": classroom_info
        })
        
    except Exception as e:
        print(f"❌ Error in get_student_activities: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        professors_ref.limit(1).get()
        
        return jsonify({
            'status': 'healthy',
            'database': 'firebase',
            'collections_initialized': True,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy', 
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@app.route('/api/submit-repo', methods=['POST'])
def submit_repository():
    """Submit a repository for analysis (professor submits for student)"""
    try:
        data = request.json
        
        student_id = data.get('student_id')
        activity_id = data.get('activity_id')
        repo_url = data.get('repo_url')
        branch = data.get('branch', 'main')
        professor_id = data.get('professor_id', 'prof_icabasug')
        
        if not all([student_id, activity_id, repo_url]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Verify student exists
        student_doc = students_ref.document(student_id).get()
        if not student_doc.exists:
            return jsonify({'success': False, 'error': 'Student not found'}), 404
        
        student_data = student_doc.to_dict()
        
        # Get activity details
        activity_doc = activitys_ref.document(f"{student_id}_{activity_id}").get()
        if not activity_doc.exists:
            return jsonify({'success': False, 'error': 'Activity not found'}), 404
        
        activity = activity_doc.to_dict()
        
        submit_id = f"{student_id}_{activity_id}"
        
        # Check if submission exists in profSubmit
        submit_doc = prof_submit_ref.document(submit_id).get()
        
        if submit_doc.exists:
            print(f"📝 Using existing submission: {submit_id}")
            # Delete old analysis results
            analysis_snapshot = analysis_results_ref.where("submit_id", "==", submit_id).stream()
            for doc in analysis_snapshot:
                doc.reference.delete()
            
            # Reset submission
            prof_submit_ref.document(submit_id).set({
                'StudentID': student_id,
                'ActivityID': activity_id,
                'ActivityTitle': activity['ActivityTitle'],
                'classroomID': activity.get('classroomID', student_data.get('classroomID', 'CLASS101')),
                'professorID': professor_id,
                'repo_url': repo_url,
                'branch': branch,
                'status': 'pending',
                'completed_at': None,
                'total_files': 0,
                'analyzed_files': 0,
                'errors_count': 0,
                'warnings_count': 0,
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=True)
        else:
            # Create new submission in profSubmit
            submission_data = {
                'StudentID': student_id,
                'ActivityID': activity_id,
                'ActivityTitle': activity['ActivityTitle'],
                'classroomID': activity.get('classroomID', student_data.get('classroomID', 'CLASS101')),
                'professorID': professor_id,
                'repo_url': repo_url,
                'branch': branch,
                'status': 'pending',
                'created_at': firestore.SERVER_TIMESTAMP,
                'completed_at': None,
                'total_files': 0,
                'analyzed_files': 0,
                'errors_count': 0,
                'warnings_count': 0
            }
            prof_submit_ref.document(submit_id).set(submission_data)
            print(f"📝 Created new submission: {submit_id}")
        
        # Start analysis in background
        thread = threading.Thread(
            target=analyze_repository_background,
            args=(submit_id, repo_url, branch, student_id, professor_id)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'submit_id': submit_id,
            'status': 'pending'
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save-grade', methods=['POST'])
def save_grade():
    """Save grade for a submission"""
    try:
        data = request.json
        submit_id = data.get('submit_id')
        grade = data.get('grade')
        professor_id = data.get('professor_id', 'prof_icabasug')
        
        if not submit_id:
            return jsonify({'success': False, 'error': 'Submit ID required'}), 400
        
        if grade is None or not isinstance(grade, (int, float)) or grade < 0 or grade > 100:
            return jsonify({'success': False, 'error': 'Grade must be a number between 0 and 100'}), 400
        
        # Check if submission exists
        submit_doc = prof_submit_ref.document(submit_id).get()
        if not submit_doc.exists:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        submission = submit_doc.to_dict()
        
        # Save grade in review
        review_data = {
            'StudentID': submission['StudentID'],
            'ActivityID': submission['ActivityID'],
            'classroomID': submission.get('classroomID', 'CLASS101'),
            'professorID': professor_id,
            'grade': grade,
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        
        reviews_ref.document(submit_id).set(review_data, merge=True)
        print(f"✅ Saved grade for submission {submit_id}: {grade}")
        
        return jsonify({
            'success': True,
            'message': f'Grade {grade} saved successfully'
        })
        
    except Exception as e:
        print(f"❌ Error saving grade: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/analysis/<submit_id>', methods=['GET'])
def get_analysis(submit_id):
    """Get analysis results for a submission"""
    try:
        submit_doc = prof_submit_ref.document(submit_id).get()
        if not submit_doc.exists:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        submission = submit_doc.to_dict()
        submission['_id'] = submit_id
        
        # Get all analysis results
        results = []
        analysis_snapshot = analysis_results_ref.where("submit_id", "==", submit_id).stream()
        for doc in analysis_snapshot:
            result = doc.to_dict()
            result['_id'] = doc.id
            results.append(result)
        
        # Get review if exists
        review_doc = reviews_ref.document(submit_id).get()
        review = review_doc.to_dict() if review_doc.exists else None
        
        return jsonify({
            'success': True,
            'submission': submission,
            'files': results,
            'review': review
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/<submit_id>', methods=['GET'])
def get_files(submit_id):
    """Get list of ALL analyzed files with content"""
    try:
        files = []
        analysis_snapshot = analysis_results_ref.where("submit_id", "==", submit_id).stream()
        
        for doc in analysis_snapshot:
            file_data = doc.to_dict()
            file_data['_id'] = doc.id
            files.append(file_data)
        
        files.sort(key=lambda x: x.get('file_path', ''))
        
        print(f"📤 Returning {len(files)} files for submission {submit_id}")
        
        return jsonify({
            'success': True,
            'files': files
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save-feedback', methods=['POST'])
def save_feedback():
    """Save feedback for a submission"""
    try:
        data = request.json
        
        submit_id = data.get('submit_id')
        reviewer_id = data.get('reviewer_id', 'prof_icabasug')
        feedback = data.get('feedback', '')
        
        if not submit_id:
            return jsonify({'success': False, 'error': 'Submit ID required'}), 400
        
        # Check if submission exists
        submit_doc = prof_submit_ref.document(submit_id).get()
        if not submit_doc.exists:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        submission = submit_doc.to_dict()
        
        # Save feedback in review
        review_data = {
            'StudentID': submission['StudentID'],
            'ActivityID': submission['ActivityID'],
            'classroomID': submission.get('classroomID', 'CLASS101'),
            'professorID': reviewer_id,
            'feedback': feedback,
            'status': 'completed',
            'completed_at': firestore.SERVER_TIMESTAMP
        }
        
        reviews_ref.document(submit_id).set(review_data, merge=True)
        print(f"✅ Saved feedback for submission {submit_id}")
        
        # Update submission status
        prof_submit_ref.document(submit_id).update({
            'status': 'reviewed',
            'reviewed_at': firestore.SERVER_TIMESTAMP
        })
        
        return jsonify({
            'success': True,
            'message': 'Feedback saved successfully'
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def analyze_repository_background(submit_id, repo_url, branch, student_id, professor_id):
    """Background task for repository analysis"""
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        print(f"📦 Cloning from {repo_url} to {temp_dir}")
        
        repo = Repo.clone_from(repo_url, temp_dir, branch=branch, depth=1)
        
        latest_commit = repo.head.commit
        print(f"   📍 Latest commit: {latest_commit.hexsha[:8]} - {latest_commit.message.strip()}")
        
        # Find ALL files
        all_files = []
        
        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '.git' and d != '__pycache__']
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, temp_dir)
                
                file_stat = os.stat(file_path)
                mod_time = datetime.fromtimestamp(file_stat.st_mtime)
                
                language = 'unknown'
                ext = os.path.splitext(file)[1].lower()
                
                if ext in ['.c']:
                    language = 'c'
                elif ext in ['.cpp', '.cc', '.cxx']:
                    language = 'cpp'
                elif ext in ['.h', '.hpp']:
                    language = 'header'
                elif ext in ['.py']:
                    language = 'python'
                elif ext in ['.js']:
                    language = 'javascript'
                elif ext in ['.html', '.htm']:
                    language = 'html'
                elif ext in ['.css']:
                    language = 'css'
                elif ext in ['.md']:
                    language = 'markdown'
                elif ext in ['.txt']:
                    language = 'text'
                elif ext in ['.json']:
                    language = 'json'
                
                all_files.append((file_path, rel_path, language, file, mod_time))
        
        print(f"🔍 Found {len(all_files)} total files")
        
        # Update submission
        prof_submit_ref.document(submit_id).update({
            'total_files': len(all_files),
            'status': 'analyzing',
            'last_commit': latest_commit.hexsha,
            'last_commit_message': latest_commit.message.strip(),
            'last_commit_date': datetime.fromtimestamp(latest_commit.committed_date)
        })
        
        total_errors = 0
        total_warnings = 0
        processed_count = 0
        
        for file_path, rel_path, language, file_name, mod_time in all_files:
            try:
                # Read file content
                content = ""
                file_size = os.path.getsize(file_path)
                
                try:
                    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'ascii']
                    for encoding in encodings:
                        try:
                            with open(file_path, 'r', encoding=encoding) as f:
                                content = f.read()
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue
                    else:
                        with open(file_path, 'rb') as f:
                            content = f.read().decode('utf-8', errors='ignore')
                except Exception as e:
                    content = f"// Error reading file: {str(e)}"
                
                # Analyze file
                errors, warnings = analyze_file(file_path, language, content)
                
                # Store in Analysis_results collection
                doc_id = f"{submit_id}_{rel_path.replace('/', '_')}"
                result_data = {
                    'submit_id': submit_id,
                    'StudentID': student_id,
                    'professorID': professor_id,
                    'file_path': rel_path.replace('\\', '/'),
                    'file_name': file_name,
                    'language': language,
                    'status': 'analyzed',
                    'errors': errors,
                    'warnings': warnings,
                    'content': content,
                    'analyzed_at': firestore.SERVER_TIMESTAMP,
                    'passed': len(errors) == 0,
                    'file_size': file_size,
                    'file_modified': mod_time
                }
                
                analysis_results_ref.document(doc_id).set(result_data)
                
                total_errors += len([e for e in errors if e.get('type') == 'error'])
                total_warnings += len(warnings)
                processed_count += 1
                
                if processed_count % 5 == 0:
                    prof_submit_ref.document(submit_id).update({
                        'analyzed_files': processed_count,
                        'errors_count': total_errors,
                        'warnings_count': total_warnings
                    })
                    print(f"📊 Progress: {processed_count}/{len(all_files)} files")
                
                if errors:
                    status_icon = "❌"
                elif warnings:
                    status_icon = "⚠️"
                else:
                    status_icon = "✅"
                    
                print(f"{status_icon} {rel_path}")
                
            except Exception as e:
                print(f"❌ Error processing {rel_path}: {e}")
                doc_id = f"{submit_id}_{rel_path.replace('/', '_')}"
                result_data = {
                    'submit_id': submit_id,
                    'StudentID': student_id,
                    'professorID': professor_id,
                    'file_path': rel_path.replace('\\', '/'),
                    'file_name': file_name,
                    'language': language,
                    'status': 'failed',
                    'errors': [{'line': 0, 'message': f'Processing error: {str(e)}', 'type': 'error'}],
                    'warnings': [],
                    'content': f"// Error processing file: {str(e)}",
                    'analyzed_at': firestore.SERVER_TIMESTAMP,
                    'passed': False,
                    'file_size': 0
                }
                analysis_results_ref.document(doc_id).set(result_data)
                total_errors += 1
                processed_count += 1
        
        # Final update
        prof_submit_ref.document(submit_id).update({
            'status': 'completed',
            'completed_at': firestore.SERVER_TIMESTAMP,
            'analyzed_files': processed_count,
            'errors_count': total_errors,
            'warnings_count': total_warnings
        })
        
        print(f"\n✅ Analysis complete for {submit_id}")
        print(f"   Total files: {len(all_files)}")
        print(f"   Total errors: {total_errors}")
        print(f"   Total warnings: {total_warnings}")
        
    except Exception as e:
        print(f"❌ Background analysis failed: {e}")
        prof_submit_ref.document(submit_id).update({
            'status': 'failed',
            'error': str(e)
        })
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"🧹 Cleaned up temporary directory")

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'name': 'CodeTracker API',
        'version': '2.0.0',
        'status': 'running',
        'database': 'firebase',
        'collections': [
            'Classrooms',
            'professors',
            'Students',
            'Activitys',
            'profSubmit',
            'reviews',
            'Analysis_results'
        ],
        'current_setup': {
            'classrooms': 1,
            'students': 2,
            'activities': 4
        },
        'endpoints': [
            '/api/health',
            '/api/classroom/<classroom_id>',
            '/api/students/<professor_id>',
            '/api/activities/<student_id>',
            '/api/submit-repo',
            '/api/analysis/<submit_id>',
            '/api/files/<submit_id>',
            '/api/save-grade',
            '/api/save-feedback'
        ]
    })

def find_free_port():
    """Find a free port on the system"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

if __name__ == '__main__':
    # Try common ports first
    ports_to_try = [5000, 5001, 8080, 3000, 8000, 8888]
    selected_port = None
    
    print("🔍 Checking available ports...")
    for port in ports_to_try:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                selected_port = port
                print(f"   ✓ Port {port} is available")
                break
        except OSError:
            print(f"   ✗ Port {port} is in use")
            continue
    
    if selected_port is None:
        selected_port = find_free_port()
        print(f"   ℹ️ Using automatically assigned port: {selected_port}")
    
    print("=" * 60)
    print("🚀 CodeTracker Backend Server (Firebase)")
    print("=" * 60)
    print(f"📡 Database: Firebase Firestore")
    print(f"🌐 Server running on: http://127.0.0.1:{selected_port}")
    print("=" * 60)
    print(f"📋 Test endpoints:")
    print(f"   Health: http://127.0.0.1:{selected_port}/api/health")
    print(f"   Classroom: http://127.0.0.1:{selected_port}/api/classroom/CLASS101")
    print(f"   Students: http://127.0.0.1:{selected_port}/api/students/prof_icabasug")
    print(f"   Activities for STU001: http://127.0.0.1:{selected_port}/api/activities/STU001")
    print("=" * 60)
    print(f"⚠️  IMPORTANT: Update Syntax.html with this port:")
    print(f"   const API_BASE_URL = 'http://127.0.0.1:{selected_port}';")
    print("=" * 60)
    
    app.run(debug=True, port=selected_port, host='127.0.0.1')