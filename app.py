from flask import Flask, render_template, request, redirect, url_for, session
import os
import subprocess
import requests
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_STEP'] = 'uploads/step'
app.config['UPLOAD_QIF'] = 'uploads/qif'
app.config['OUTPUT_DIR'] = 'output'

# Разрешенные расширения
ALLOWED_DATA = {'xml'}
ALLOWED_RML = {'rml'}

def allowed_file(filename, file_type):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in (ALLOWED_DATA if file_type == 'data' else ALLOWED_RML)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Очистка сессии и папок
        session.clear()
        os.makedirs(app.config['UPLOAD_STEP'], exist_ok=True)
        os.makedirs(app.config['UPLOAD_QIF'], exist_ok=True)

        # Сохранение файлов
        files = {
            'step_file': ('step', app.config['UPLOAD_STEP']),
            'qif_file': ('qif', app.config['UPLOAD_QIF']),
            'step_rml': ('step', app.config['UPLOAD_STEP']),
            'qif_rml': ('qif', app.config['UPLOAD_QIF'])
        }

        for field, (file_type, folder) in files.items():
            file = request.files.get(field)
            if not file or file.filename == '':
                return f"Ошибка: файл {field} не загружен"
            
            file_type_check = 'data' if 'file' in field else 'rml'
            if not allowed_file(file.filename, file_type_check):
                return f"Недопустимый формат для {field}"
            
            # Генерируем безопасное имя файла
            filename = secure_filename(file.filename)
            filepath = os.path.join(folder, filename)
            file.save(filepath)
            session[field] = filepath  # Сохраняем полный путь в сессии
            print(f"Файл сохранен: {filepath}")  # Логирование

        return redirect(url_for('processing'))
    
    return render_template('index.html')

@app.route('/processing')
def processing():
    # Шаг 1: Конвертация STEP
    step_ttl = convert_to_ttl(
        data_file=session['step_file'],  # Полный путь к STEP-файлу
        rml_file=session['step_rml'],    # Полный путь к RML-маппингу
        output=os.path.join(app.config['OUTPUT_DIR'], 'step_data.ttl')
    )
    
    # Шаг 2: Конвертация QIF
    qif_ttl = convert_to_ttl(
        data_file=session['qif_file'],   # Полный путь к QIF-файлу
        rml_file=session['qif_rml'],     # Полный путь к RML-маппингу
        output=os.path.join(app.config['OUTPUT_DIR'], 'qif_data.ttl')
    )
    
    # Шаг 3: Загрузка в Fuseki
    fuseki_status = upload_to_fuseki([
        os.path.join(app.config['OUTPUT_DIR'], 'step_data.ttl'),
        os.path.join(app.config['OUTPUT_DIR'], 'qif_data.ttl')
    ])
    
    return render_template('processing.html', 
        step_ttl=step_ttl,
        qif_ttl=qif_ttl,
        fuseki_status=fuseki_status
    )

def convert_to_ttl(data_file, rml_file, output):
    try:
        # Экранируем пробелы в путях
        data_file_escaped = f'"{os.path.abspath(data_file)}"'
        rml_file_escaped = f'"{os.path.abspath(rml_file)}"'
        output_escaped = f'"{os.path.abspath(output)}"'
        
        cmd = f'java -jar rmlmapper-7.3.3-r374-all.jar -m {rml_file_escaped} -s {data_file_escaped} -o {output_escaped}'
        print(f"Выполняется команда: {cmd}")  # Логирование

        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True
        )
        print("Вывод RMLMapper:", result.stdout)
        return "✅ Успешно сгенерирован"
    except subprocess.CalledProcessError as e:
        print("Ошибка RMLMapper:", e.stderr)
        return f"❌ Ошибка: {e.stderr}"

def upload_to_fuseki(ttl_files):
    try:
        for file in ttl_files:
            with open(file, 'rb') as f:
                response = requests.post(
                    'http://localhost:3030/dataset/data',
                    headers={'Content-Type': 'text/turtle'},
                    data=f.read()
                )
                if response.status_code != 200:
                    return "❌ Ошибка загрузки"
        return "✅ Данные в Fuseki"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

@app.route('/query', methods=['GET', 'POST'])
def query():
    if request.method == 'POST':
        sparql = request.form['query']
        response = requests.get(
            'http://localhost:3030/dataset/query',
            params={'query': sparql},
            headers={'Accept': 'application/json'}
        )
        return render_template('query.html', results=response.json())
    return render_template('query.html')

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_STEP'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_QIF'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_DIR'], exist_ok=True)
    app.run(debug=True)