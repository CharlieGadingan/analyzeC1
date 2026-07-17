import os
import re
import subprocess
import sys
from html.parser import HTMLParser


SUPPORTED_LANGUAGES = {
    'c': {
        'name': 'C',
        'extensions': ['.c'],
    },
    'cpp': {
        'name': 'C++',
        'extensions': ['.cpp', '.cc', '.cxx', '.c++', '.hpp', '.h'],
    },
    'java': {
        'name': 'Java',
        'extensions': ['.java'],
    },
    'python': {
        'name': 'Python',
        'extensions': ['.py'],
    },
    'javascript': {
        'name': 'JavaScript',
        'extensions': ['.js', '.mjs', '.cjs'],
    },
    'html': {
        'name': 'HTML',
        'extensions': ['.html', '.htm'],
    },
    'css': {
        'name': 'CSS',
        'extensions': ['.css'],
    },
}


VOID_HTML_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr'
}

LANGUAGE_HINTS = {
    'html': [
        r'<!doctype\s+html',
        r'<html\b',
        r'<head\b',
        r'<body\b',
    ],
    'css': [
        r'^\s*@import\b',
        r'^\s*@media\b',
        r'^\s*[.#][\w-]+\s*\{',
        r'^\s*[a-zA-Z][\w-]*\s*\{\s*$',
    ],
    'python': [
        r'^\s*#!.*\bpython[0-9.]*\b',
        r'^\s*def\s+\w+\s*\(',
        r'^\s*class\s+\w+\s*:',
        r'^\s*import\s+\w+',
        r'^\s*from\s+\w+\s+import\s+',
    ],
    'java': [
        r'^\s*package\s+[\w.]+\s*;',
        r'^\s*import\s+java\.',
        r'\bpublic\s+class\b',
        r'\bSystem\.out\.println\b',
    ],
    'javascript': [
        r'^\s*#!.*\bnode\b',
        r'\b(const|let|var)\s+\w+\s*=',
        r'\bfunction\s+\w+\s*\(',
        r'=>',
        r'\bimport\s+.*\s+from\s+[\'"]',
    ],
    'cpp': [
        r'^\s*#include\s*<iostream>',
        r'\bstd::',
        r'\bcout\b',
        r'\bcin\b',
        r'\busing\s+namespace\s+std\b',
        r'\btemplate\s*<',
        r'\bclass\s+\w+\s*\{',
    ],
    'c': [
        r'^\s*#include\s*<stdio\.h>',
        r'\bprintf\s*\(',
        r'\bscanf\s*\(',
        r'\bint\s+main\s*\(',
    ],
}


def get_supported_language_labels():
    return [details['name'] for details in SUPPORTED_LANGUAGES.values()]


def get_supported_extensions():
    extensions = []
    for details in SUPPORTED_LANGUAGES.values():
        extensions.extend(details['extensions'])
    return extensions


def detect_language_from_extension(file_name):
    extension = os.path.splitext(file_name)[1].lower()
    for language_key, details in SUPPORTED_LANGUAGES.items():
        if extension in details['extensions']:
            return language_key
    return None


def detect_language_from_content(content, file_name=None):
    normalized_content = content or ''
    sample = normalized_content[:4000]
    if normalized_content.lstrip().startswith('\ufeff'):
        sample = normalized_content.lstrip('\ufeff')[:4000]

    for language_key, patterns in LANGUAGE_HINTS.items():
        for pattern in patterns:
            if re.search(pattern, sample, re.IGNORECASE | re.MULTILINE):
                return language_key

    if file_name:
        return detect_language_from_extension(file_name)

    return None


def detect_language_for_file(file_path, file_name=None):
    try:
        content = read_text_file(file_path)
    except Exception:
        content = ''

    detected_language = detect_language_from_content(content, file_name=file_name)
    if detected_language:
        return detected_language

    if file_name:
        return detect_language_from_extension(file_name)

    return None


def read_text_file(file_path):
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'ascii']
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as file_handle:
                return file_handle.read()
        except (UnicodeDecodeError, LookupError):
            continue

    with open(file_path, 'rb') as file_handle:
        return file_handle.read().decode('utf-8', errors='ignore')


def _append_issue(items, line, message, issue_type):
    items.append({
        'line': line,
        'message': message,
        'type': issue_type
    })


def _parse_process_output(stderr_text):
    errors = []
    warnings = []
    seen_messages = set()

    for line in stderr_text.split('\n'):
        if not line.strip():
            continue

        cleaned_line = line.strip()
        normalized_type = None
        line_number = 0
        message = cleaned_line

        gcc_like = re.search(r':(\d+):(\d+):\s+(error|warning):\s+(.*)$', cleaned_line, re.IGNORECASE)
        if gcc_like:
            line_number = int(gcc_like.group(1))
            normalized_type = gcc_like.group(3).lower()
            message = gcc_like.group(4).strip()
        else:
            simple_gcc_like = re.search(r':(\d+):\s+(error|warning):\s+(.*)$', cleaned_line, re.IGNORECASE)
            if simple_gcc_like:
                line_number = int(simple_gcc_like.group(1))
                normalized_type = simple_gcc_like.group(2).lower()
                message = simple_gcc_like.group(3).strip()
            else:
                python_like = re.search(r'File ".*?", line (\d+)', cleaned_line)
                if python_like:
                    line_number = int(python_like.group(1))
                    normalized_type = 'error' if 'error' in cleaned_line.lower() else 'warning'
                    message = cleaned_line
                elif 'error:' in cleaned_line.lower():
                    normalized_type = 'error'
                    message = cleaned_line.split('error:', 1)[1].strip()
                elif 'warning:' in cleaned_line.lower():
                    normalized_type = 'warning'
                    message = cleaned_line.split('warning:', 1)[1].strip()

        if normalized_type is None:
            continue

        message = re.sub(r'\s*\[.*?\]$', '', message).strip()
        message_key = f'{line_number}:{normalized_type}:{message}'
        if message_key in seen_messages:
            continue
        seen_messages.add(message_key)

        target = errors if normalized_type == 'error' else warnings
        _append_issue(target, line_number, message, normalized_type)

    errors.sort(key=lambda item: item['line'])
    warnings.sort(key=lambda item: item['line'])
    return errors, warnings


def _parse_python_output(stderr_text):
    errors = []
    warnings = []

    if not stderr_text.strip():
        return errors, warnings

    line_number = 0
    message = stderr_text.strip().splitlines()[-1].strip()

    match = re.search(r'File ".*?", line (\d+)', stderr_text)
    if match:
        line_number = int(match.group(1))

    for line in reversed([line.strip() for line in stderr_text.splitlines() if line.strip()]):
        if 'SyntaxError:' in line or 'IndentationError:' in line or 'TabError:' in line:
            message = line.split(':', 1)[1].strip() if ':' in line else line
            break

    _append_issue(errors, line_number, message, 'error')
    return errors, warnings


def _parse_javascript_output(stderr_text):
    errors = []
    warnings = []

    if not stderr_text.strip():
        return errors, warnings

    line_number = 0
    message = stderr_text.strip().splitlines()[-1].strip()

    first_line = next((line.strip() for line in stderr_text.splitlines() if line.strip()), '')
    match = re.search(r':(\d+):(?:\d+)?:', first_line)
    if match:
        line_number = int(match.group(1))

    for line in reversed([line.strip() for line in stderr_text.splitlines() if line.strip()]):
        if 'SyntaxError:' in line or 'ReferenceError:' in line or 'TypeError:' in line:
            message = line.split(':', 1)[1].strip() if ':' in line else line
            break

    _append_issue(errors, line_number, message, 'error')
    return errors, warnings


class _HtmlSyntaxChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_HTML_TAGS:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        return

    def handle_endtag(self, tag):
        if tag in VOID_HTML_TAGS:
            return

        for index in range(len(self.stack) - 1, -1, -1):
            open_tag, line_number = self.stack[index]
            if open_tag == tag:
                del self.stack[index:]
                return

        _append_issue(self.errors, self.getpos()[0], f'Unexpected closing tag </{tag}>', 'error')

    def close(self):
        super().close()
        for tag, line_number in reversed(self.stack):
            _append_issue(self.errors, line_number, f'Unclosed tag <{tag}>', 'error')


def analyze_html_content(content):
    checker = _HtmlSyntaxChecker()
    try:
        checker.feed(content)
        checker.close()
    except Exception as exc:
        _append_issue(checker.errors, 0, f'HTML parse error: {exc}', 'error')

    return checker.errors, []


def _strip_css_comments(content):
    return re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)


def analyze_css_content(content):
    errors = []
    warnings = []
    cleaned = _strip_css_comments(content)
    brace_stack = []

    for line_number, line in enumerate(cleaned.splitlines(), start=1):
        in_string = None
        escaped = False
        for character in line:
            if in_string:
                if escaped:
                    escaped = False
                elif character == '\\':
                    escaped = True
                elif character == in_string:
                    in_string = None
                continue

            if character in {'"', "'"}:
                in_string = character
            elif character == '{':
                brace_stack.append(line_number)
            elif character == '}':
                if brace_stack:
                    brace_stack.pop()
                else:
                    _append_issue(errors, line_number, 'Unexpected closing brace }', 'error')

    for line_number in brace_stack:
        _append_issue(errors, line_number, 'Unclosed block {', 'error')

    return errors, warnings


def analyze_source_file(file_path, language):
    result = {
        'errors': [],
        'warnings': [],
        'compile_output': '',
        'analysis_signal': None,
        'passed': True
    }

    try:
        analysis_signal = {
            'c': 'gcc',
            'cpp': 'g++',
            'java': 'javac',
            'python': 'python',
            'javascript': 'node',
            'html': 'html-parser',
            'css': 'css-parser',
        }.get(language)
        result['analysis_signal'] = analysis_signal

        if language == 'c':
            command = ['gcc', '-fsyntax-only', '-Wall', '-Wextra', '-std=c11', file_path]
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            result['compile_output'] = process.stderr
            result['errors'], result['warnings'] = _parse_process_output(process.stderr)
        elif language == 'cpp':
            command = ['g++', '-fsyntax-only', '-Wall', '-Wextra', '-std=c++14', file_path]
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            result['compile_output'] = process.stderr
            result['errors'], result['warnings'] = _parse_process_output(process.stderr)
        elif language == 'java':
            command = ['javac', '-Xlint', file_path]
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            result['compile_output'] = process.stderr
            result['errors'], result['warnings'] = _parse_process_output(process.stderr)
        elif language == 'python':
            command = [sys.executable, '-m', 'py_compile', file_path]
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            result['compile_output'] = process.stderr
            result['errors'], result['warnings'] = _parse_python_output(process.stderr)
        elif language == 'javascript':
            command = ['node', '--check', file_path]
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            result['compile_output'] = process.stderr
            result['errors'], result['warnings'] = _parse_javascript_output(process.stderr)
        elif language == 'html':
            content = read_text_file(file_path)
            result['errors'], result['warnings'] = analyze_html_content(content)
            result['compile_output'] = ''
        elif language == 'css':
            content = read_text_file(file_path)
            result['errors'], result['warnings'] = analyze_css_content(content)
            result['compile_output'] = ''
        else:
            result['errors'].append({
                'line': 0,
                'message': f'Unsupported language: {language}',
                'type': 'error'
            })

        result['passed'] = len(result['errors']) == 0

    except subprocess.TimeoutExpired:
        result['errors'].append({
            'line': 0,
            'message': 'Compilation timeout - file may be too complex',
            'type': 'error'
        })
        result['passed'] = False
    except FileNotFoundError:
        tool_names = {
            'c': 'gcc',
            'cpp': 'g++',
            'java': 'javac',
            'python': 'python',
            'javascript': 'node'
        }
        result['errors'].append({
            'line': 0,
            'message': f'Analyzer tool not found. Please install {tool_names.get(language, language)}.',
            'type': 'error'
        })
        result['passed'] = False
    except Exception as exc:
        result['errors'].append({
            'line': 0,
            'message': f'Analysis error: {str(exc)}',
            'type': 'error'
        })
        result['passed'] = False

    return result
