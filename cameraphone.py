import cv2
import numpy as np
import pytesseract
import subprocess
import pyttsx3
import pygame
import os
import re
import time
from spellchecker import SpellChecker 
from thefuzz import process 


pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class VivaExEngine:
    def __init__(self):
        pygame.mixer.init()
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', 150)
        self.spell = SpellChecker() 
        self.science_terms = [
            "Probability", "Mathematics", "Statistics", "Population", 
            "Experiment", "Variable", "Example", "Jarash", "GPA", "Department"
        ]
        
    def speak_piper(self, text, lang="en", speed=1.5):
        print(f"🎙️ Piper is speaking at speed {speed}...")
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        piper_exe = os.path.join(base_dir, "piper", "piper.exe")
        
        model_name = "ar_JO-hamza-medium.onnx" if lang == "ar" else "en_US-lessac-medium.onnx"
        model_path = os.path.join(base_dir, "model", model_name)
        output_wav = os.path.join(base_dir, "speech_output.wav")

        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.unload()

            process = subprocess.run(
                [piper_exe, "--model", model_path, "--output_file", output_wav, "--length_scale", str(speed)],
                input=text.encode('utf-8'),
                capture_output=True,
                check=True
            )
            
            if os.path.exists(output_wav):
                pygame.mixer.music.load(output_wav)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
        except Exception as e:
            print(f"❌ خطأ في السرد: {e}")
            
    def local_logic_correction(self, raw_text):
        lines = raw_text.split('\n')
        final_lines = []

        for line in lines:
            if not line.strip(): continue
            words = line.split()
            corrected_words = []
            for word in words:
                clean_word = re.sub(r'[^\w]', '', word)
                
                if not clean_word or len(clean_word) < 3 or clean_word.isdigit():
                    corrected_words.append(word)
                    continue

                best_match, score = process.extractOne(clean_word, self.science_terms)
                if score > 90: 
                    corrected_words.append(best_match)
                else:
                    corr = self.spell.correction(word)
                    corrected_words.append(corr if corr else word)
            
            final_lines.append(" ".join(corrected_words))
        return " . \n ".join(final_lines)

    def extract_text(self, image):
        print("🛠️ جاري المعالجة الرقمية...")
        # إذا كانت الكاميرا مقلوبة، يمكنك تعديل أو حذف السطر التالي
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        contrast = clahe.apply(gray)

        processed = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        processed = cv2.copyMakeBorder(processed, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=[255, 255, 255])
        cv2.imwrite("debug_ocr_view.jpg", processed)
        
        print("📖 استخراج النصوص أوفلاين...")
        custom_config = r'--oem 3 --psm 3'
        raw_text = pytesseract.image_to_string(processed, lang='eng+ara', config=custom_config)

        return self.local_logic_correction(raw_text)

    def calculate_sharpness(self, image):
        return cv2.Laplacian(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()

    def capture_best_frame(self):
        # فتح الكاميرا بإعداداتها الطبيعية تماماً بدون إجبار على أي دقة
        cap = cv2.VideoCapture(1)

        if not cap.isOpened():
            print("❌ لم يتم العثور على الكاميرا! تأكدي من توصيل الـ USB.")
            return None

        print("📷 يتم الآن عرض الكاميرا. اضبطي الزاوية ثم اضغطي على 'Space' (المسطرة) للالتقاط.")
        
        frames_buffer = [] 
        
        # تفريغ الذاكرة المؤقتة للـ USB (تسخين الكاميرا لتجنب التعليق)
        for _ in range(5):
            cap.read()
            
        while True:
            ret, frame = cap.read()
            if not ret:
                print("⚠️ الكاميرا فصلت... جاري معالجة ما تم التقاطه.")
                break
                
            frames_buffer.append(frame.copy())
            if len(frames_buffer) > 5:
                frames_buffer.pop(0)
                
            display_frame = frame.copy()
            cv2.putText(display_frame, "Adjust Camera. Press SPACE to capture, or 'q' to quit.", 
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            cv2.imshow("Camera Preview - Viva", display_frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord(' '):  
                print("📸 تم الالتقاط!")
                break
            elif key == ord('q'): 
                cap.release()
                cv2.destroyAllWindows()
                return None
                
        cap.release()
        cv2.destroyAllWindows()
        
        if not frames_buffer: 
            return None
            
        scores = [self.calculate_sharpness(f) for f in frames_buffer]
        return frames_buffer[np.argmax(scores)]

    def speak_offline(self, text):
        print(f"🤖 نطق: {text[:50]}...")
        self.engine.say(text)
        self.engine.runAndWait()

if __name__ == "__main__":
    viva = VivaExEngine()
    
    img = viva.capture_best_frame()
    
    if img is not None:
        text_output = viva.extract_text(img)
        print("-" * 30)
        print(f"📝 النتيجة النهائية:\n{text_output}")
        print("-" * 30)
        
        viva.speak_piper(text_output, lang="en") 
    else:
        print("❌ تم الإلغاء أو فشل التقاط الصورة!")
      
