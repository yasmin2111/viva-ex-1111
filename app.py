from flask import Flask, request, jsonify, render_template
import re
import uuid
import time

app = Flask(__name__)
sessions = {}

# ==============================================================================
# 🧠 CORE AI FUNCTIONS & TEXT HEALERS
# ==============================================================================

def detect_language(text):
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    if len(text) < 10: return 'en'
    if arabic_chars > len(text) * 0.05:
        return 'ar'
    return 'en'

def normalize_arabic_numerals(text):
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return text.translate(trans)

def repair_arabic_text(text):
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\(\s+(\d+)\s+\)', r'(\1)', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text

def extract_questions_smart(text):
    clean_text = repair_arabic_text(text)
    clean_text = re.sub(r'\r\n', '\n', clean_text)
    language = detect_language(clean_text)

    metadata = {'duration': None, 'student_name': None, 'instructions': None}
    dur_match = re.search(r'(?:المدة|مدة|Time)\s*[:\-]?\s*([^\n|]+)', clean_text, re.IGNORECASE)
    if dur_match: metadata['duration'] = dur_match.group(1).strip()
    
    name_match = re.search(r'(?:اسم الطالب|Student Name)\s*[:\-]?\s*([^\n|]+)', clean_text, re.IGNORECASE)
    if name_match: metadata['student_name'] = name_match.group(1).strip()
    
    instr_match = re.search(r'(?:تعليمات|ملحوظة|ملاحظة|Instructions)\s*[:\-]?\s*([^\n|]+)', clean_text, re.IGNORECASE)
    if instr_match: metadata['instructions'] = instr_match.group(1).strip()

    section_patterns = [
        r'[Qq]uestion\s+[Nn]umber\s+(\w+|\d+)',
        r'السؤال\s+(الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|\d+)',
        r'سؤال\s*إضافي',
        r'Part\s+[A-Z\d]+',
        r'القسم\s+(الأول|الثاني|الثالث|الرابع)'
    ]
    combined_pattern = '|'.join(section_patterns)
    splits = list(re.finditer(combined_pattern, clean_text, re.IGNORECASE))
    
    sections_raw = []
    if not splits:
        sections_raw = [{'num': 1, 'label': 'Main Exam', 'text': clean_text}]
    else:
        for i, m in enumerate(splits):
            start = m.start()
            end = splits[i+1].start() if i+1 < len(splits) else len(clean_text)
            sections_raw.append({
                'num': i + 1,
                'label': m.group(0).strip(),
                'text': clean_text[start:end]
            })

    questions = []
    global_id = 0
    ar_to_en_map = {'أ': 'a', 'ب': 'b', 'ج': 'c', 'د': 'd', 'هـ': 'e', 'و': 'f', 'أ)': 'a', 'ب)': 'b'}

    q_pattern = r'(?:^|\n|\t|\s{2,})(?:Question\s+|السؤال\s*)?[\(\[\-]?\s*(\d+|[٠-٩]+)\s*[\.\-\)\]:]+(?=\s|\b)'
    q_pattern_fallback = r'(?:^|\n)\s*[\(\[]?\s*(\d+|[٠-٩]+)\s*(?:[\.\-\)\]:]+|\s{2,})(?=\S)'
    opt_pattern = r'(?:^|\s+)[\(\[\-]?([a-dA-Dأبجدهـو])(?:[\.\-\)\]:]+(?=\s)|\s{3,}(?=\S))'

    for sec in sections_raw:
        sec_text = sec['text']
        q_matches = list(re.finditer(q_pattern, sec_text, re.IGNORECASE))
        if not q_matches:
            q_matches = list(re.finditer(q_pattern_fallback, sec_text))
            
        if not q_matches and len(sec_text.strip()) > 20:
             global_id += 1
             questions.append({
                'id': global_id, 'number': 1, 'section': sec['num'],
                'section_label': sec['label'], 'text': sec_text.strip(),
                'options': [], 'type': 'essay', 'answer': None, 'answer_time': None
             })
             continue
            
        for i, match in enumerate(q_matches):
            q_num_raw = match.group(1)
            q_num = normalize_arabic_numerals(q_num_raw)
            start_idx = match.end()
            end_idx = q_matches[i+1].start() if i+1 < len(q_matches) else len(sec_text)
            q_raw_text = sec_text[start_idx:end_idx].strip()
            
            opt_matches = list(re.finditer(opt_pattern, q_raw_text))
            options = []
            if opt_matches:
                q_text_only = q_raw_text[:opt_matches[0].start()].strip()
                for j, o_match in enumerate(opt_matches):
                    letter = o_match.group(1).lower()
                    letter = ar_to_en_map.get(letter, letter)
                    o_start = o_match.end()
                    o_end = opt_matches[j+1].start() if j+1 < len(opt_matches) else len(q_raw_text)
                    opt_text = q_raw_text[o_start:o_end].strip()
                    if opt_text: options.append({'letter': letter, 'text': opt_text})
            else:
                q_text_only = q_raw_text

            q_text_only = re.sub(r'\s+', ' ', q_text_only).strip()
            if len(q_text_only) < 3: continue
            if re.search(r'\.{3,}|_{3,}|-{3,}', q_text_only):
                q_text_only = re.sub(r'\.{3,}|_{3,}|-{3,}', ' [BLANK] ', q_text_only)

            if options and len(options) >= 2: q_type = 'mcq'
            elif any(kw in q_text_only.lower() for kw in ['true', 'false', 'صح', 'خطأ', 'صواب']): q_type = 'tf'
            else: q_type = 'essay'

            global_id += 1
            questions.append({
                'id': global_id, 'number': int(q_num) if q_num.isdigit() else q_num,
                'section': sec['num'], 'section_label': sec['label'],
                'text': q_text_only, 'options': options, 'type': q_type,
                'answer': None, 'answer_time': None
            })

    return {
        'questions': questions, 'metadata': metadata,
        'sections': [{'num': s['num'], 'label': s['label']} for s in sections_raw],
        'language': language
    }

# ==============================================================================
# 🌐 ROUTES
# ==============================================================================

@app.route('/')
def index():
    # سيقوم فلاسك بالبحث عن index.html داخل مجلد templates تلقائياً
    return render_template('index.html')

@app.route('/api/extract_questions', methods=['POST'])
def api_extract_questions():
    try:
        data = request.get_json()
        if not data or not data.get('text'): return jsonify({'error': 'No text'}), 400
        result = extract_questions_smart(data['text'])
        if not result['questions']: return jsonify({'error': 'No questions found'}), 400
        session_id = str(uuid.uuid4())
        sessions[session_id] = {'questions': result['questions'], 'answers': [], 'created_at': time.time()}
        return jsonify({
            'success': True, 'session_id': session_id, 'questions': result['questions'],
            'metadata': result['metadata'], 'language': result['language'],
            'sections': result['sections']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/save_answer', methods=['POST'])
def api_save_answer():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        if session_id not in sessions: return jsonify({'error': 'Session not found'}), 404
        sessions[session_id]['answers'].append({'q_id': data.get('q_id'), 'answer': data.get('answer'), 'time': time.time()})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
