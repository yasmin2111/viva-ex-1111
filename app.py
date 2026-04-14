from flask import Flask, request, jsonify, render_template_string
import re
import uuid
import time

app = Flask(__name__)
sessions = {}

def detect_language(text):
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    if len(text) < 10: return 'en'
    if arabic_chars > len(text) * 0.05:
        return 'ar'
    return 'en'

def normalize_arabic_numerals(text):
    # تحويل الأرقام المشرقية إلى أرقام إنجليزية لسهولة المعالجة
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return text.translate(trans)

def extract_questions_smart(text):
    print("=== بدء خوارزمية الذكاء الهيكلي الشاملة (Ultimate Split) ===")
    
    # 1. تنظيف النص المبدئي
    clean_text = re.sub(r'\r\n', '\n', text)
    language = detect_language(clean_text)

    # 2. استخراج البيانات الوصفية
    metadata = {'duration': None, 'student_name': None, 'instructions': None}
    dur_match = re.search(r'(?:المدة|مدة|Time)\s*[:\-]?\s*([^\n|]+)', clean_text, re.IGNORECASE)
    if dur_match: metadata['duration'] = dur_match.group(1).strip()
    
    name_match = re.search(r'(?:اسم الطالب|Student Name)\s*[:\-]?\s*([^\n|]+)', clean_text, re.IGNORECASE)
    if name_match: metadata['student_name'] = name_match.group(1).strip()
    
    instr_match = re.search(r'(?:تعليمات|ملحوظة|ملاحظة|Instructions)\s*[:\-]?\s*([^\n|]+)', clean_text, re.IGNORECASE)
    if instr_match: metadata['instructions'] = instr_match.group(1).strip()

    # 3. تحديد الأقسام (Sections)
    section_patterns = [
        r'[Qq]uestion\s+[Nn]umber\s+(\w+|\d+)',
        r'السؤال\s+(الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|\d+)',
        r'سؤال\s*إضافي',
        r'Part\s+[A-Z\d]+'
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
    ar_to_en_map = {'أ': 'a', 'ب': 'b', 'ج': 'c', 'د': 'd', 'هـ': 'e', 'و': 'f'}

    # 4. النمط الخارق لاستخراج الأسئلة: يدعم (1), 1-, 1., السؤال 1
    q_pattern = r'(?:^|\n|\t|\s+)(?:(?:السؤال\s*(\d+|[٠-٩]+))|(?:[\(\[\-]\s*(\d+|[٠-٩]+)\s*[\.\-\)\]:]+)|(?:(\d+|[٠-٩]+)\s*[\.\-\)\]:]+))\s+'
    
    # 5. النمط الخارق لفصل الخيارات: يدعم a) أو أ) أو حتى أ بدون أقواس بداية السطر
    opt_pattern = r'(?:^|\n|\t|\s{3,})\s*[\(\[]?\s*([a-dA-Dأبجدهـو])\s*(?:[\.\-\)\]:]+|\s+(?=\S))'

    for sec in sections_raw:
        sec_text = sec['text']
        
        # البحث عن الأسئلة
        q_matches = list(re.finditer(q_pattern, sec_text))
        
        # Fallback إذا كان النص بدون ترقيم واضح
        if not q_matches and len(sec_text.strip()) > 15:
            loose_pattern = r'(?:^|\n)\s*[\(\[]?\s*(\d+|[٠-٩]+)\s*(?:[\.\-\)\]:]+|\s+(?=\S))'
            q_matches = list(re.finditer(loose_pattern, sec_text))
            
        for i, match in enumerate(q_matches):
            q_num_raw = match.group(1) or match.group(2) or match.group(3)
            q_num = normalize_arabic_numerals(q_num_raw)
            
            start_idx = match.end()
            end_idx = q_matches[i+1].start() if i+1 < len(q_matches) else len(sec_text)
            q_raw_text = sec_text[start_idx:end_idx].strip()
            
            # استخراج الخيارات
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
                    opt_text = re.sub(r'\s+', ' ', opt_text)
                    if opt_text:
                        options.append({'letter': letter, 'text': opt_text})
            else:
                q_text_only = q_raw_text

            q_text_only = re.sub(r'\s+', ' ', q_text_only).strip()

            if len(q_text_only) < 3:
                continue

            # معالجة الفراغات
            if re.search(r'\.{3,}|_{3,}|-{3,}', q_text_only):
                q_text_only = re.sub(r'\.{3,}|_{3,}|-{3,}', ' [BLANK] ', q_text_only)

            # تحديد نوع السؤال
            if options and len(options) >= 2:
                q_type = 'mcq'
            elif any(kw in q_text_only.lower() for kw in ['true', 'false', 'صح', 'خطأ', 'صواب']):
                q_type = 'tf'
            else:
                q_type = 'essay'

            global_id += 1
            questions.append({
                'id': global_id,
                'number': int(q_num) if q_num.isdigit() else q_num,
                'section': sec['num'],
                'section_label': sec['label'],
                'text': q_text_only,
                'options': options,
                'type': q_type,
                'answer': None,
                'answer_time': None
            })

    print(f"Total valid questions extracted: {len(questions)}")

    return {
        'questions': questions,
        'metadata': metadata,
        'sections': [{'num': s['num'], 'label': s['label']} for s in sections_raw],
        'language': language
    }

# ==============================================================================
# 🌐 Flask Application Routes & HTML
# ==============================================================================

HTML_FULL = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Viva EX - Advanced Blind & Special Needs Exam System</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .main-card {
            background: white;
            border-radius: 30px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 { color: #1a73e8; font-size: 2rem; margin-bottom: 10px; text-align: center; }
        .subtitle { text-align: center; color: #5f6368; margin-bottom: 30px; }
        .upload-area {
            border: 4px dashed #1a73e8;
            border-radius: 20px;
            padding: 50px;
            text-align: center;
            cursor: pointer;
            background: #f8f9fa;
            font-size: 1.2rem;
            transition: all 0.3s;
        }
        .upload-area:hover { background: #e8f0fe; transform: scale(1.02); }
        .quiz-area { display: none; }
        .quiz-area.active { display: block; animation: fadeIn 0.5s ease-in-out; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        
        .metadata-bar {
            background: #e8f0fe;
            padding: 15px;
            border-radius: 15px;
            margin-bottom: 15px;
            font-size: 1rem;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            justify-content: center;
        }
        .metadata-item { background: white; padding: 5px 15px; border-radius: 20px; font-weight: 600; color: #1a73e8; }

        /* Section Tabs */
        .section-tabs {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 15px;
            justify-content: center;
        }
        .sec-tab {
            padding: 7px 18px;
            border: 2px solid #ddd;
            border-radius: 50px;
            font-size: .85rem;
            cursor: pointer;
            background: #f8f9fa;
            transition: .2s;
            font-weight: 600;
        }
        .sec-tab.active { background: #1a73e8; color: #fff; border-color: #1a73e8; }

        /* Progress bar */
        .progress-row {
            display: flex;
            align-items: center;
            gap: 12px;
            margin: 10px 0;
            background: #f8f9fa;
            padding: 10px 20px;
            border-radius: 15px;
        }
        .progress-bar-wrap {
            flex: 1;
            height: 12px;
            background: #e8eaed;
            border-radius: 10px;
            overflow: hidden;
        }
        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, #34a853, #1a73e8);
            border-radius: 10px;
            transition: width .4s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .question-counter {
            font-size: 1.2rem;
            font-weight: bold;
            color: #1a73e8;
            white-space: nowrap;
        }
        .sec-chip {
            display: inline-block;
            background: #e8f0fe;
            color: #0d47a1;
            padding: 6px 16px;
            border-radius: 50px;
            font-size: .85rem;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .question-type-badge {
            display: block;
            text-align: center;
            padding: 8px 20px;
            border-radius: 25px;
            font-size: 1rem;
            font-weight: bold;
            margin: 10px auto;
            width: fit-content;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .type-essay { background: #1a73e8; color: white; }
        .type-tf { background: #fbbc04; color: black; }
        .type-mcq { background: #34a853; color: white; }
        
        .question-box {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 20px;
            margin: 20px 0;
            font-size: 1.3rem;
            line-height: 1.6;
            direction: auto;
            box-shadow: 0 10px 20px rgba(118, 75, 162, 0.2);
        }
        .blank-highlight {
            background: #fbbc04;
            color: black;
            padding: 2px 20px;
            border-radius: 20px;
            display: inline-block;
            margin: 0 5px;
        }
        .options-box {
            background: #f1f3f4;
            padding: 25px;
            border-radius: 15px;
            margin: 15px 0;
            direction: auto;
        }
        .option-item {
            background: white;
            padding: 15px;
            margin: 10px 0;
            border-radius: 12px;
            border-left: 5px solid #1a73e8;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 15px;
            transition: all .2s;
            font-size: 1.1rem;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        .option-item:hover { background: #e8f0fe; transform: translateX(5px); }
        .option-item.selected { background: #e8f0fe; border-left-color: #34a853; font-weight: bold; box-shadow: 0 4px 10px rgba(52, 168, 83, 0.2); }
        .opt-letter {
            background: #1a73e8; color: white;
            border-radius: 50%; width: 32px; height: 32px;
            display: flex; align-items: center; justify-content: center;
            font-weight: bold; flex-shrink: 0;
            font-size: 1.1rem;
        }
        
        .status-badge {
            display: inline-block;
            padding: 10px 20px;
            border-radius: 50px;
            font-size: 1rem;
            font-weight: bold;
            margin: 10px 0;
            transition: all 0.3s;
        }
        .status-listening { background: #e8f0fe; color: #1a73e8; }
        .status-speaking  { background: #fef7e0; color: #fbbc04; }
        .status-recording { background: #34a853; color: white; }
        .status-waiting   { background: #fff3e0; color: #e65100; }
        
        .silence-bar-container {
            background: #f1f3f4;
            border-radius: 10px;
            height: 12px;
            margin: 10px 0;
            overflow: hidden;
            display: none;
        }
        .silence-bar {
            height: 100%;
            background: linear-gradient(90deg, #34a853, #fbbc04, #ea4335);
            border-radius: 10px;
            width: 0%;
            transition: width 0.1s linear;
        }
        
        .recognized-area {
            background: #2d2d5e;
            color: #fbbc04;
            padding: 20px;
            border-radius: 15px;
            margin: 20px 0;
            text-align: center;
            font-size: 1.2rem;
            font-weight: bold;
            border: 3px solid #fbbc04;
            min-height: 90px;
            box-shadow: inset 0 0 10px rgba(0,0,0,0.5);
        }
        .recognized-label { color: #fbbc04; font-size: 0.95rem; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }
        .recognized-text {
            color: white;
            font-size: 1.4rem;
            margin-top: 5px;
            word-break: break-word;
            min-height: 40px;
        }
        .interim-text { color: #aaa; font-style: italic; }
        
        .button-group {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin: 25px 0;
            justify-content: center;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 25px;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .btn:hover { opacity: 0.85; transform: translateY(-2px); box-shadow: 0 6px 12px rgba(0,0,0,0.15); }
        .btn:active { transform: translateY(0); }
        .btn-primary  { background: #1a73e8; color: white; }
        .btn-success  { background: #34a853; color: white; }
        .btn-danger   { background: #ea4335; color: white; }
        .btn-warning  { background: #fbbc04; color: black; }
        .btn-purple   { background: #764ba2; color: white; }
        
        .log-area {
            background: #f8f9fa;
            border-radius: 20px;
            padding: 25px;
            margin-top: 40px;
            max-height: 350px;
            overflow-y: auto;
            border: 1px solid #ddd;
        }
        .log-item {
            background: white;
            padding: 15px;
            border-radius: 12px;
            margin-bottom: 12px;
            border-left: 5px solid #34a853;
            position: relative;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .log-item.edited { border-left-color: #fbbc04; }
        .log-edit-btn {
            position: absolute; right: 15px; top: 15px;
            background: #1a73e8; color: white; border: none;
            border-radius: 8px; padding: 5px 12px;
            font-size: .85rem; cursor: pointer;
            transition: 0.2s;
        }
        .log-edit-btn:hover { background: #0d47a1; }
        
        .voice-hint {
            background: white;
            padding: 20px;
            border-radius: 15px;
            margin: 20px 0;
            text-align: center;
            font-size: 0.95rem;
            border: 2px dashed #1a73e8;
            color: #333;
        }

        /* Edit Modal */
        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,.65);
            align-items: center;
            justify-content: center;
            z-index: 999;
            backdrop-filter: blur(5px);
        }
        .modal-overlay.open { display: flex; }
        .modal-box {
            background: white;
            border-radius: 25px;
            padding: 35px;
            max-width: 600px;
            width: 95%;
            max-height: 88vh;
            overflow-y: auto;
            box-shadow: 0 15px 50px rgba(0,0,0,.4);
        }
        .modal-box h3 { margin-bottom: 20px; color: #0d47a1; font-size: 1.5rem; }
        .modal-qtext {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 15px;
            font-size: 1.05rem;
            direction: auto;
            border-left: 4px solid #764ba2;
        }
        .modal-box select, .modal-box textarea {
            width: 100%; padding: 12px; border-radius: 12px;
            border: 2px solid #ddd; font-size: 1rem;
            margin-bottom: 15px; font-family: inherit;
        }
        .modal-box select:focus, .modal-box textarea:focus {
            outline: none; border-color: #1a73e8; box-shadow: 0 0 0 3px rgba(26,115,232,0.2);
        }
        .modal-btns { display: flex; gap: 10px; justify-content: flex-end; margin-top: 10px; }

        @keyframes pulse { 0%,100%{opacity:1; transform: scale(1);} 50%{opacity:.8; transform: scale(1.05);} }
        .pulsing { animation: pulse 1.5s infinite; }
    </style>
</head>
<body>
    <div class="container">
        <div class="main-card">
            <h1>🎓 Viva EX AI System</h1>
            <p class="subtitle">Powered by Smart Split Parsing & AI Voice | For Blind & Special Needs Students</p>

            <div id="upload-area" class="upload-area" onclick="document.getElementById('pdf-input').click()">
                <input type="file" id="pdf-input" accept=".pdf" style="display:none">
                <div style="font-size: 3rem; margin-bottom: 10px;">📄</div>
                <div><strong>Click to Upload Exam PDF File</strong></div>
                <small style="color: #666; display: block; margin-top: 10px;">Master Engine: Solves Column Issues, Arabic Formats & Smart Audio</small>
            </div>

            <div id="quiz-area" class="quiz-area">
                <div id="metadata-bar" class="metadata-bar"></div>

                <div id="section-tabs" class="section-tabs"></div>

                <div class="progress-row">
                    <span class="question-counter">Q <span id="q-current">1</span>/<span id="q-total">0</span></span>
                    <div class="progress-bar-wrap">
                        <div id="progress-fill" class="progress-bar-fill" style="width:0%"></div>
                    </div>
                    <span id="q-answered" style="font-size:.9rem;color:#5f6368; font-weight: bold;">0 answered</span>
                </div>

                <div id="sec-chip" class="sec-chip"></div>
                <div id="type-badge" class="question-type-badge"></div>
                <div id="question-box" class="question-box"></div>
                <div id="options-box" class="options-box" style="display:none;"></div>

                <div class="recognized-area">
                    <div class="recognized-label">🎤 System is hearing:</div>
                    <div id="recognized-text" class="recognized-text">...</div>
                </div>
                <div id="silence-bar-container" class="silence-bar-container">
                    <div id="silence-bar" class="silence-bar"></div>
                </div>

                <div style="text-align: center;">
                    <span id="status" class="status-badge status-listening">🎤 Ready for voice commands...</span>
                </div>

                <div class="voice-hint">
                    🎙️ <strong>Voice Commands Dictionary:</strong><br><br>
                    <strong>Navigation:</strong> "Read" / "Repeat" (إقرأ) &nbsp;|&nbsp; "Next" / "Skip" (التالي/تخطي) &nbsp;|&nbsp; "Back" (السابق)<br>
                    <strong>Answers:</strong> "True" (صح) / "False" (خطأ) &nbsp;|&nbsp; "A" "B" "C" "D" (أ ب ج د)<br>
                    <strong>System:</strong> "Edit 3" (تعديل رقم) &nbsp;|&nbsp; "Save" (حفظ / تقرير)<br>
                    <hr style="margin: 10px 0; border: 1px dashed #ddd;">
                    <em>Essay Questions: Speak your answer normally, then stay silent for 2 seconds to confirm.</em>
                </div>

                <div class="button-group">
                    <button class="btn btn-success" onclick="answerTrue()">✅ True (صح)</button>
                    <button class="btn btn-danger"  onclick="answerFalse()">❌ False (خطأ)</button>
                    <button class="btn btn-primary" onclick="repeatQuestion()">🔄 Repeat (إعادة)</button>
                    <button class="btn btn-primary" onclick="previousQuestion()">⏮️ Prev (السابق)</button>
                    <button class="btn btn-primary" onclick="nextQuestion()">Next/Skip (تخطي) ⏭️</button>
                    <button class="btn btn-primary" onclick="readInstructionsAgain()">📖 Help (مساعدة)</button>
                    <button class="btn btn-purple"  onclick="openEditModal(null)">✏️ Edit (تعديل)</button>
                    <button class="btn btn-warning" onclick="downloadReport()">💾 Save (حفظ)</button>
                </div>

                <div class="log-area">
                    <h3 style="color: #1a73e8; margin-bottom: 15px;">📝 Answers Log & Timeline</h3>
                    <div id="log-container"></div>
                </div>
            </div>
        </div>
    </div>

    <div id="modal-overlay" class="modal-overlay" onclick="closeModalOutside(event)">
        <div class="modal-box">
            <h3>✏️ Edit Recorded Answer</h3>
            <select id="modal-q-select" onchange="modalQuestionChanged()"></select>
            <div id="modal-q-text" class="modal-qtext"></div>
            <div id="modal-opts-wrap" style="display:none">
                <div id="modal-opts"></div>
            </div>
            <div id="modal-text-wrap">
                <textarea id="modal-answer" rows="4" placeholder="Type your new answer here…"></textarea>
            </div>
            <div class="modal-btns">
                <button class="btn btn-primary" onclick="saveModalAnswer()">💾 Update Answer</button>
                <button class="btn btn-danger"  onclick="closeModal()">Cancel</button>
            </div>
        </div>
    </div>

    <script>
        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';

        let sessionId = null;
        let questions = [];
        let currentIndex = 0;
        let metadata = {};
        let examLanguage = 'en';
        let isSpeaking = false;
        let recognition = null;
        let recognitionActive = false;
        let silenceTimer = null;
        let silenceBarTimer = null;
        let pendingEssayText = "";
        let sectionFilter = null;
        const SILENCE_MS = 2000;

        // ── Helpers ────────────────────────────────────────────────────
        function updateRecognizedText(text, isFinal) {
            const el = document.getElementById('recognized-text');
            el.textContent = text;
            el.className = 'recognized-text' + (isFinal ? '' : ' interim-text');
            if (isFinal) {
                el.style.color = '#34a853';
                setTimeout(() => el.style.color = 'white', 1500);
            } else {
                el.style.color = '#fbbc04';
            }
        }

        function updateStatus(message, className) {
            const el = document.getElementById('status');
            el.innerHTML = message;
            el.className = `status-badge ${className}`;
        }

        function visibleQuestions() {
            if (sectionFilter === null) return questions;
            return questions.filter(q => q.section === sectionFilter);
        }
        function currentQ() {
            return visibleQuestions()[currentIndex] || null;
        }

        function updateProgress() {
            const vq = visibleQuestions();
            const tot = vq.length;
            const cur = currentIndex + 1;
            document.getElementById('q-current').textContent = cur;
            document.getElementById('q-total').textContent   = tot;
            document.getElementById('progress-fill').style.width = (tot ? (cur / tot * 100) : 0) + '%';
            const answered = vq.filter(q => q.answer !== null).length;
            document.getElementById('q-answered').textContent = answered + (examLanguage === 'ar' ? ' تمت الإجابة' : ' answered');
        }

        function buildSectionTabs(sections) {
            const container = document.getElementById('section-tabs');
            container.innerHTML = '';

            const allBtn = document.createElement('button');
            allBtn.className = 'sec-tab active';
            allBtn.textContent = examLanguage === 'ar' ? 'جميع الأقسام' : 'All Sections';
            allBtn.onclick = () => switchSection(null, allBtn);
            container.appendChild(allBtn);

            const unique = [...new Map(sections.map(s => [s.num, s])).values()];
            unique.forEach(s => {
                const btn = document.createElement('button');
                btn.className = 'sec-tab';
                let sName = s.label.length > 20 ? s.label.substring(0,20)+'...' : s.label;
                btn.textContent = sName;
                btn.title = s.label;
                btn.onclick = () => switchSection(s.num, btn);
                container.appendChild(btn);
            });
        }

        function switchSection(num, btnEl) {
            document.querySelectorAll('.sec-tab').forEach(b => b.classList.remove('active'));
            btnEl.classList.add('active');
            sectionFilter = num;
            currentIndex = 0;
            displayQuestion();
            setTimeout(readFullQuestion, 300);
        }

        function displayQuestion() {
            const q = currentQ();
            if (!q) return;

            document.getElementById('sec-chip').textContent = q.section_label + ' · ' + (examLanguage === 'ar' ? 'سؤال ' : 'Question ') + q.number;

            let displayText = q.text.replace(/\[BLANK\]/g, '<span class="blank-highlight">______</span>');
            document.getElementById('question-box').innerHTML = displayText;

            const badge = document.getElementById('type-badge');
            if (q.type === 'mcq') {
                badge.textContent = examLanguage === 'ar' ? '🎯 اختيار من متعدد – قُل أ، ب، ج، د' : '🎯 Multiple Choice – Say A, B, C, or D';
                badge.className = 'question-type-badge type-mcq';
            } else if (q.type === 'tf') {
                badge.textContent = examLanguage === 'ar' ? '⚖️ صح أو خطأ – قُل صح أو خطأ' : '⚖️ True / False – Say True or False';
                badge.className = 'question-type-badge type-tf';
            } else {
                badge.textContent = examLanguage === 'ar' ? '✍️ سؤال مقالي – تحدث ثم اصمت ثانيتين' : '✍️ Essay – Speak then pause 2s';
                badge.className = 'question-type-badge type-essay';
            }

            const optionsBox = document.getElementById('options-box');
            if (q.options && q.options.length > 0) {
                optionsBox.style.display = 'block';
                optionsBox.innerHTML = `<strong>${examLanguage === 'ar' ? 'الخيارات المتاحة:' : 'Available Options:'}</strong><br><br>`;
                q.options.forEach((o, i) => {
                    const div = document.createElement('div');
                    div.className = 'option-item' + (q.answer === o.letter ? ' selected' : '');
                    div.innerHTML = `<span class="opt-letter">${o.letter.toUpperCase()}</span> <span>${o.text}</span>`;
                    div.onclick = () => saveAnswer(o.letter);
                    optionsBox.appendChild(div);
                });
            } else {
                optionsBox.style.display = 'none';
            }

            updateProgress();
        }

        function resolveAnswerLabel(q) {
            if (!q.answer) return 'none';
            if (q.type === 'mcq') {
                const o = q.options.find(x => x.letter === q.answer);
                return o ? o.letter.toUpperCase() + ') ' + o.text : q.answer;
            }
            return q.answer;
        }

        function readFullQuestion() {
            const q = currentQ();
            if (!q || isSpeaking) return;

            let textToRead = examLanguage === 'ar' ? `السؤال ${currentIndex + 1}. ` : `Question ${currentIndex + 1}. `;

            let questionText = q.text.replace(/\[BLANK\]/g, examLanguage === 'ar' ? ' فراغ ' : ' blank ');
            textToRead += questionText + ' ';

            if (q.options && q.options.length > 0) {
                textToRead += examLanguage === 'ar' ? 'الخيارات هي: ' : 'Options are: ';
                q.options.forEach(o => {
                    textToRead += o.letter.toUpperCase() + ') ' + o.text + '. ';
                });
                textToRead += examLanguage === 'ar' ? 'قُل أ، أو ب، أو ج، أو د للتأكيد. ' : 'Say A, B, C, or D to confirm. ';
            } else if (q.type === 'tf') {
                textToRead += examLanguage === 'ar' ? 'قُل كلمة صح أو كلمة خطأ. ' : 'Say True or False. ';
            } else {
                textToRead += examLanguage === 'ar' ? 'قل إجابتك بوضوح، ثم اصمت لمدة ثانيتين لتأكيد وحفظ الإجابة. ' : 'Speak your answer clearly, then pause for two seconds to save it. ';
            }

            if (q.answer !== null) {
                textToRead += (examLanguage === 'ar' ? 'إجابتك المسجلة حالياً هي: ' : 'Your currently recorded answer is: ') + resolveAnswerLabel(q) + '. ';
            }

            speak(textToRead);
        }

        function speak(text, onDone) {
            if (!text) { if (onDone) onDone(); return; }
            window.speechSynthesis.cancel();
            isSpeaking = true;
            if (recognitionActive && recognition) recognition.stop();
            updateStatus('🔊 Speaking…', 'status-speaking pulsing');

            const u = new SpeechSynthesisUtterance(text);
            u.lang = examLanguage === 'ar' ? 'ar-SA' : 'en-US';
            u.rate = 0.85; 
            u.pitch = 1;
            u.onend = () => {
                isSpeaking = false;
                updateStatus('🎤 Listening… Speak Now', 'status-listening pulsing');
                restartRecognition();
                if (onDone) onDone();
            };
            window.speechSynthesis.speak(u);
        }

        function buildRecognition() {
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SR) {
                updateRecognizedText('Speech recognition is not supported in this browser.', true);
                return null;
            }
            const r = new SR();
            r.lang = examLanguage === 'ar' ? 'ar-SA' : 'en-US';
            r.continuous = true;
            r.interimResults = true;
            r.maxAlternatives = 3;

            r.onstart = () => {
                recognitionActive = true;
                updateStatus('🎤 Recording… I am listening', 'status-recording pulsing');
                updateRecognizedText('Waiting for voice...', false);
            };

            r.onresult = (event) => {
                if (isSpeaking) return;
                let interim = '', final_ = '';
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    const t = event.results[i][0].transcript;
                    if (event.results[i].isFinal) final_ += t + ' ';
                    else interim += t;
                }
                const display = (final_ + interim).trim();
                updateRecognizedText(display, !!final_);

                if (final_.trim()) {
                    processCommand(final_.trim().toLowerCase());
                } else if (interim.trim()) {
                    clearSilenceCountdown();
                    const q = currentQ();
                    if (q && q.type === 'essay') pendingEssayText = display;
                }
            };

            r.onerror = (event) => {
                recognitionActive = false;
                if (event.error !== 'no-speech') console.warn('Speech-To-Text Error:', event.error);
            };

            r.onend = () => {
                recognitionActive = false;
                if (!isSpeaking) setTimeout(restartRecognition, 200);
            };
            return r;
        }

        function restartRecognition() {
            if (isSpeaking || recognitionActive) return;
            if (!recognition) recognition = buildRecognition();
            if (!recognition) return;
            try { recognition.start(); } catch (e) {}
        }

        function startSilenceCountdown() {
            clearSilenceCountdown();
            const container = document.getElementById('silence-bar-container');
            const bar = document.getElementById('silence-bar');
            container.style.display = 'block';
            bar.style.width = '0%';

            const stepMs = 50, steps = SILENCE_MS / stepMs;
            let elapsed = 0;
            silenceBarTimer = setInterval(() => {
                elapsed++;
                bar.style.width = ((elapsed / steps) * 100) + '%';
                if (elapsed >= steps) clearInterval(silenceBarTimer);
            }, stepMs);

            silenceTimer = setTimeout(() => {
                container.style.display = 'none';
                bar.style.width = '0%';
                if (pendingEssayText.trim().length > 1) saveAnswer(pendingEssayText.trim());
            }, SILENCE_MS);
        }

        function clearSilenceCountdown() {
            clearTimeout(silenceTimer);
            clearInterval(silenceBarTimer);
            silenceTimer = silenceBarTimer = null;
            document.getElementById('silence-bar-container').style.display = 'none';
            document.getElementById('silence-bar').style.width = '0%';
        }

        function processCommand(cmd) {
            const q = currentQ();
            if (!q) return;

            // 1. تنظيف النص: إزالة علامات الترقيم التي يضيفها المتصفح للصوت
            let cleanCmd = cmd.toLowerCase().replace(/[.,!؟?;:]/g, '').trim();

            // 2. أولاً: فحص أوامر التنقل (حتى لا يتم الخلط بين كلمة Pass و حرف a)
            if (/(read|repeat|اقرأ|قراءة|أعد|إعادة)/.test(cleanCmd)) { clearSilenceCountdown(); readFullQuestion(); return; }
            if (/(next|skip|pass|التالي|تخطي|تجاوز|سكيب|تخطى|بعده)/.test(cleanCmd)) { clearSilenceCountdown(); nextQuestion(); return; }
            if (/(back|previous|السابق|رجوع|ارجع|قبله)/.test(cleanCmd)) { clearSilenceCountdown(); previousQuestion(); return; }
            if (/(help|instruction|مساعدة|تعليمات)/.test(cleanCmd)) { clearSilenceCountdown(); readInstructionsAgain(); return; }
            if (/(save|report|حفظ|تقرير|انهاء)/.test(cleanCmd)) { clearSilenceCountdown(); downloadReport(); return; }

            // 3. فحص أوامر التعديل
            const editMatch = cleanCmd.match(/(?:edit|تعديل)(?:\s+(?:question|رقم|السؤال))?\s+(\d+)/);
            if (editMatch) { clearSilenceCountdown(); openEditModal(parseInt(editMatch[1])); return; }
            if (/(?:edit|تعديل)/.test(cleanCmd) && !editMatch) { clearSilenceCountdown(); openEditModal(null); return; }

            // 4. خيارات الصح والخطأ
            if (q.type === 'tf') {
                if (/\b(?:true|correct|yes)\b|صح|صواب|نعم/.test(cleanCmd)) { clearSilenceCountdown(); saveAnswer('True'); return; }
                if (/\b(?:false|wrong|no)\b|خطأ|غلط|لا/.test(cleanCmd)) { clearSilenceCountdown(); saveAnswer('False'); return; }
            }

            // 5. الذكاء الصوتي لخيارات الـ MCQ
            if (q.type === 'mcq' && q.options.length > 0) {
                
                // أ- المطابقة الحرفية (إذا قال A، بي، جيم، إيه...)
                const letterMatch = cleanCmd.match(/^(a|b|c|d|أ|ب|ج|د|إيه|ايه|بي|سي|دي|ألف|باء|جيم|دال|اليف)$/i);
                if (letterMatch) {
                    let mapped = letterMatch[1].toLowerCase()
                        .replace(/أ|إيه|ايه|ألف|اليف/g, 'a')
                        .replace(/ب|بي|باء/g, 'b')
                        .replace(/ج|سي|جيم/g, 'c')
                        .replace(/د|دي|دال/g, 'd');
                    const opt = q.options.find(o => o.letter.toLowerCase() === mapped);
                    if (opt) { clearSilenceCountdown(); saveAnswer(opt.letter); return; }
                }
                
                // ب- المطابقة الجملية (إذا قال: الخيار ألف، إجابة B، choose c)
                const phraseMatch = cleanCmd.match(/(?:choose|option|letter|answer|الخيار|حرف|إجابة)\s+(a|b|c|d|أ|ب|ج|د|إيه|بي|سي|دي)/i);
                if (phraseMatch) {
                    let mapped = phraseMatch[1].toLowerCase()
                        .replace(/أ|إيه/g, 'a').replace(/ب|بي/g, 'b').replace(/ج|سي/g, 'c').replace(/د|دي/g, 'd');
                    const opt = q.options.find(o => o.letter.toLowerCase() === mapped);
                    if (opt) { clearSilenceCountdown(); saveAnswer(opt.letter); return; }
                }

                // ج- المطابقة بالنص (إذا قرأ الخيار نفسه، مثل: "real bond")
                const spokenTextMatch = q.options.find(o => o.text && cleanCmd.includes(o.text.toLowerCase().trim()));
                if (spokenTextMatch) {
                    clearSilenceCountdown(); saveAnswer(spokenTextMatch.letter); return;
                }
            }

            // 6. الإجابات المقالية
            if (q.type === 'essay') {
                pendingEssayText = cmd;
                updateStatus(examLanguage === 'ar' ? '⏳ جاري التأكيد بعد ثانيتين...' : '⏳ Confirming in 2 s…', 'status-waiting pulsing');
                startSilenceCountdown();
                return;
            }

            updateRecognizedText((examLanguage === 'ar' ? 'أمر غير معروف: "' : 'Unknown command: "') + cleanCmd + '"', true);
        }

        function saveAnswer(answer) {
            clearSilenceCountdown();
            pendingEssayText = '';
            const q = currentQ();
            if (!q) return;

            const wasAnswered = q.answer !== null;
            q.answer = answer;
            q.answer_time = new Date().toLocaleTimeString();

            refreshLog();
            displayQuestion();
            updateRecognizedText('✅ Saved: ' + answer, true);

            const feedback = examLanguage === 'ar' ? 'تم حفظ الإجابة بنجاح.' : 'Answer recorded successfully.';
            speak(feedback, () => {
                const vq = visibleQuestions();
                if (!wasAnswered && currentIndex + 1 < vq.length) {
                    currentIndex++;
                    displayQuestion();
                    setTimeout(readFullQuestion, 500);
                } else if (vq.every(x => x.answer !== null)) {
                    speak(examLanguage === 'ar' ? 'لقد أتممت الإجابة على جميع الأسئلة في هذا القسم! قل حفظ لتحميل التقرير النهائي.' : 'All questions in this section are answered! Say Save to download your final report.');
                }
            });

            fetch('/api/save_answer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, q_id: q.id, answer: answer })
            }).catch(() => {});
        }

        function nextQuestion() {
            const vq = visibleQuestions();
            if (currentIndex + 1 < vq.length) { currentIndex++; displayQuestion(); setTimeout(readFullQuestion, 400); }
            else speak(examLanguage === 'ar' ? 'لقد وصلت إلى السؤال الأخير.' : 'You have reached the last question.');
        }
        function previousQuestion() {
            if (currentIndex > 0) { currentIndex--; displayQuestion(); setTimeout(readFullQuestion, 400); }
            else speak(examLanguage === 'ar' ? 'أنت الآن في السؤال الأول.' : 'This is the very first question.');
        }
        function repeatQuestion() { readFullQuestion(); }
        function answerTrue()  { const q = currentQ(); if (q && q.type !== 'essay') saveAnswer('True'); }
        function answerFalse() { const q = currentQ(); if (q && q.type !== 'essay') saveAnswer('False'); }
        function readInstructionsAgain() {
            speak(examLanguage === 'ar' ? 'للتنقل قل: اقرأ، التالي، تخطي، أو السابق. للإجابة قل الخيار مثل: ألف، باء، جيم، دال. للتعديل قل: تعديل متبوعاً برقم السؤال. ولإنهاء الامتحان قل: حفظ.' : 'For navigation say: Read, Next, Skip, or Back. To answer say the option like: A, B, C, D. To edit say: Edit followed by the question number. To finish say: Save.');
        }

        function refreshLog() {
            const con = document.getElementById('log-container');
            con.innerHTML = '';
            questions.filter(q => q.answer !== null).reverse().forEach(q => {
                const div = document.createElement('div');
                div.className = 'log-item' + (q._edited ? ' edited' : '');
                const shortQ = q.text.length > 100 ? q.text.substring(0, 100) + '…' : q.text;
                div.innerHTML =
                    `<strong style="color: #0d47a1;">${q.section_label} · Q${q.number}:</strong> ${shortQ}<br>` +
                    `<strong style="color: #34a853; margin-top: 5px; display: inline-block;">Answer:</strong> <span style="font-size: 1.1rem; font-weight: bold;">${resolveAnswerLabel(q)}</span>` +
                    ` <small style="color: #888; margin-left: 10px;">(${q.answer_time || ''})</small>` +
                    `<button class="log-edit-btn" onclick="openEditModal(${q.id})">✏️ Edit</button>`;
                con.appendChild(div);
            });
        }

        function openEditModal(qId) {
            const sel = document.getElementById('modal-q-select');
            sel.innerHTML = '';
            questions.forEach(q => {
                const opt = document.createElement('option');
                opt.value = q.id;
                const label = `${q.section_label} · Q${q.number}: ` + (q.text.length > 50 ? q.text.substring(0, 50) + '…' : q.text);
                opt.textContent = label;
                sel.appendChild(opt);
            });
            const target = qId || currentQ()?.id || questions[0]?.id;
            if (target) sel.value = target;
            modalQuestionChanged();
            document.getElementById('modal-overlay').classList.add('open');
        }

        function modalQuestionChanged() {
            const q = questions.find(x => x.id === parseInt(document.getElementById('modal-q-select').value));
            if (!q) return;
            document.getElementById('modal-q-text').innerHTML = q.text.replace(/\[BLANK\]/g, '<span class="blank-highlight">______</span>');

            if (q.type === 'mcq' && q.options.length >= 2) {
                document.getElementById('modal-opts-wrap').style.display = 'block';
                document.getElementById('modal-text-wrap').style.display = 'none';
                const mo = document.getElementById('modal-opts');
                mo.innerHTML = '';
                mo.dataset.chosen = q.answer || '';
                q.options.forEach(o => {
                    const div = document.createElement('div');
                    div.className = 'option-item' + (q.answer === o.letter ? ' selected' : '');
                    div.innerHTML = `<span class="opt-letter">${o.letter.toUpperCase()}</span> <span>${o.text}</span>`;
                    div.onclick = () => {
                        document.querySelectorAll('#modal-opts .option-item').forEach(d => d.classList.remove('selected'));
                        div.classList.add('selected');
                        mo.dataset.chosen = o.letter;
                    };
                    mo.appendChild(div);
                });
            } else {
                document.getElementById('modal-opts-wrap').style.display = 'none';
                document.getElementById('modal-text-wrap').style.display = 'block';
                document.getElementById('modal-answer').value = q.answer || '';
            }
        }

        function saveModalAnswer() {
            const q = questions.find(x => x.id === parseInt(document.getElementById('modal-q-select').value));
            if (!q) return;
            let ans;
            if (q.type === 'mcq') {
                ans = document.getElementById('modal-opts').dataset.chosen;
                if (!ans) { alert(examLanguage === 'ar' ? 'الرجاء اختيار إجابة.' : 'Please select an option.'); return; }
            } else {
                ans = document.getElementById('modal-answer').value.trim();
                if (!ans) { alert(examLanguage === 'ar' ? 'الرجاء كتابة إجابة.' : 'Please enter an answer.'); return; }
            }
            q.answer = ans;
            q.answer_time = new Date().toLocaleTimeString();
            q._edited = true;
            closeModal();
            refreshLog();
            displayQuestion();
            speak(examLanguage === 'ar' ? 'تم تحديث الإجابة بنجاح.' : 'Answer updated successfully.');
        }

        function closeModal() { document.getElementById('modal-overlay').classList.remove('open'); }
        function closeModalOutside(e) { if (e.target === document.getElementById('modal-overlay')) closeModal(); }

        function readExamInstructions() {
            let msg = examLanguage === 'ar' ? 'مرحباً بك في نظام الذكاء الاصطناعي لفيفا إكس. ' : 'Welcome to the Viva EX AI System. ';
            if (metadata.duration) msg += (examLanguage === 'ar' ? 'مدة الامتحان هي: ' : 'Exam duration is: ') + metadata.duration + '. ';
            if (metadata.student_name) msg += (examLanguage === 'ar' ? 'الطالب: ' : 'Student: ') + metadata.student_name + '. ';
            if (metadata.instructions) msg += (examLanguage === 'ar' ? 'تعليمات الامتحان: ' : 'Exam Instructions: ') + metadata.instructions + '. ';
            msg += (examLanguage === 'ar' ? 'تم استخراج ' : 'Successfully extracted ') + questions.length + (examLanguage === 'ar' ? ' سؤال. ' : ' questions. ');
            msg += (examLanguage === 'ar' ? 'سأقوم الآن بقراءة السؤال الأول.' : 'I will now begin reading the first question.');
            speak(msg, () => setTimeout(readFullQuestion, 500));
        }

        function displayMetadata() {
            const bar = document.getElementById('metadata-bar');
            let html = '';
            if (metadata.duration) html += `<div class="metadata-item">⏱️ ${metadata.duration}</div>`;
            if (metadata.student_name) html += `<div class="metadata-item">👤 ${metadata.student_name}</div>`;
            if (metadata.instructions) html += `<div class="metadata-item" style="width: 100%; text-align: center; margin-top: 10px;">📌 ${metadata.instructions}</div>`;
            bar.innerHTML = html || '<div class="metadata-item">✅ Exam successfully parsed and ready</div>';
        }

        // الجافاسكريبت الآن ذكي: يفصل العواميد بـ Tab ويترك الكلمات المتصلة بدون فصل
        async function processPDF(file) {
            document.getElementById('upload-area').style.display = 'none';
            document.getElementById('quiz-area').classList.add('active');
            updateStatus('⏳ Analyzing PDF structure...', 'status-listening pulsing');

            try {
                const ab  = await file.arrayBuffer();
                const pdf = await pdfjsLib.getDocument({ data: ab }).promise;
                let fullText = '';
                
                for (let i = 1; i <= pdf.numPages; i++) {
                    const page    = await pdf.getPage(i);
                    const content = await page.getTextContent();
                    
                    let lastY;
                    let lastX;
                    let pageText = "";
                    for (let item of content.items) {
                        let y = item.transform[5];
                        let x = item.transform[4];

                        if (lastY !== undefined && Math.abs(lastY - y) > 5) {
                            pageText += "\\n";
                        } else if (lastY !== undefined) {
                            let distance = Math.abs(x - lastX);
                            if (distance > 25) { 
                                pageText += " \\t "; // عمود جديد
                            } else if (distance > 2) {
                                pageText += " "; // مسافة عادية بين الكلمات
                            }
                            // إذا كانت الـ distance قريبة جداً (<2)، تندمج الكلمتين معاً بدون مسافة (يحل مشكلة الحروف المقطوعة)
                        }
                        pageText += item.str;
                        lastY = y;
                        lastX = x;
                    }
                    fullText += pageText + "\\n\\n";
                }

                const res  = await fetch('/api/extract_questions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: fullText })
                });
                const data = await res.json();

                if (data.error) { alert(data.error); location.reload(); return; }

                sessionId    = data.session_id;
                questions    = data.questions;
                metadata     = data.metadata;
                examLanguage = data.language || 'en';
                currentIndex = 0;
                sectionFilter = null;

                displayMetadata();
                buildSectionTabs(data.sections || []);
                displayQuestion();

                recognition = buildRecognition();
                if (recognition) recognition.start();
                setTimeout(readExamInstructions, 800);

            } catch (err) {
                alert('Fatal Error: ' + err.message);
                location.reload();
            }
        }

        function downloadReport() {
            let c = '='.repeat(60) + '\\n';
            c += '      VIVA EX AI – OFFICIAL EXAM REPORT\\n' + '='.repeat(60) + '\\n\\n';
            c += `Generation Date: ${new Date().toLocaleString()}\\n`;
            c += `Exam Language: ${examLanguage === 'ar' ? 'Arabic' : 'English'}\\n`;
            c += `Completion Status: ${questions.filter(q => q.answer !== null).length} / ${questions.length} answered\\n`;
            if (metadata.duration) c += `Exam Duration: ${metadata.duration}\\n`;
            if (metadata.student_name) c += `Student Name: ${metadata.student_name}\\n`;
            c += '\\n' + '='.repeat(60) + '\\n\\n';

            const secs = [...new Set(questions.map(q => q.section))].sort();
            secs.forEach(s => {
                const secLabel = questions.find(q => q.section === s).section_label;
                c += `[  ${secLabel.toUpperCase()}  ]\\n`;
                c += '-'.repeat(secLabel.length + 6) + '\\n\\n';
                
                questions.filter(q => q.section === s).forEach(q => {
                    c += `Question ${q.number}: ${q.text.replace(/\\[BLANK\\]/g, '_____')}\\n`;
                    if (q.options.length > 0) {
                        c += `Options: `;
                        q.options.forEach(o => c += `[${o.letter.toUpperCase()}] ${o.text}   `);
                        c += '\\n';
                    }
                    c += `=> Recorded Answer: ${resolveAnswerLabel(q)}\\n`;
                    if (q.answer_time) c += `=> Timestamp: ${q.answer_time}\\n`;
                    if (q._edited) c += `=> Note: This answer was manually edited.\\n`;
                    c += '\\n';
                });
                c += '\\n';
            });

            const blob = new Blob([c], { type: 'text/plain;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `VivaEX_Report_${Date.now()}.txt`;
            a.click();
            speak(examLanguage === 'ar' ? 'تم تنزيل التقرير النهائي بنجاح.' : 'Final report has been downloaded successfully.');
        }

        document.getElementById('pdf-input').onchange = e => {
            if (e.target.files[0]) processPDF(e.target.files[0]);
        };
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_FULL)

@app.route('/api/extract_questions', methods=['POST'])
def api_extract_questions():
    try:
        data = request.get_json()
        if not data or not data.get('text'):
            return jsonify({'error': 'No text provided'}), 400

        result = extract_questions_smart(data['text'])

        if not result['questions']:
            return jsonify({'error': 'AI Parser could not identify questions. Please ensure the PDF has selectable text.'}), 400

        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            'questions':  result['questions'],
            'answers':    [],
            'created_at': time.time()
        }

        return jsonify({
            'success':    True,
            'session_id': session_id,
            'questions':  result['questions'],
            'metadata':   result['metadata'],
            'language':   result['language'],
            'total':      len(result['questions']),
            'sections':   result['sections'],
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/save_answer', methods=['POST'])
def api_save_answer():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'}), 400
        session_id = data.get('session_id')
        if session_id not in sessions:
            return jsonify({'error': 'Session not found'}), 404
        sessions[session_id]['answers'].append({
            'q_id':   data.get('q_id'),
            'answer': data.get('answer'),
            'time':   time.time()
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print('=' * 70)
    print('🚀  Viva EX AI Engine  –  Blind & Special-Needs Exam System')
    print('🧠  Powered by Advanced Ultimate Split Parsing & Full Audio Intent')
    print('📍  Server running at: http://localhost:5000')
    print('=' * 70)
    app.run(debug=True, port=5000)