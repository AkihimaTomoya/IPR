from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g
from werkzeug.utils import secure_filename
import os
from google import genai
import sqlite3
from model import Model

app = Flask(__name__)
app.secret_key = os.urandom(24)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

app.config['UPLOAD_FOLDER'] = 'static/uploads'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Set API key and model
os.environ["SERPAPI_API_KEY"] = "483f476db0c98ac0476e45e3fa253b7023e02b336141a712361f84f13cf6fc7e"
api_key = os.environ.get("SERPAPI_API_KEY")
os.environ["GEMINI_API_KEY"] = "AIzaSyB9v8czj3wz5T6lmgxRIJEFfAMsr3eHvFE"
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
outfit_model = Model(client, api_key)

# Ensure directories exist
os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
os.makedirs(os.path.join('static', 'generated'), exist_ok=True)
os.makedirs(os.path.join('static', 'tryon'), exist_ok=True)

DATABASE = 'history.db'

# Database setup
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        g._database = db
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                query TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()

@app.route('/')
def home():
    db = get_db()
    history = db.execute('SELECT * FROM history ORDER BY created_at DESC').fetchall()
    return render_template('home.html', history=history)

@app.route('/generate-outfit', methods=['GET', 'POST'])
def generate_outfit():
    styles = ['Casual', 'Streetwear', 'Business/Formal', 'Bohemian', 'Minimalist',
              'Preppy', 'Grunge', 'Vintage/Retro', 'Gothic', 'Athleisure']
    colors = ['Red', 'Blue', 'Green', 'Black', 'White', 'Yellow', 'Pink', 'Purple', 'Orange', 'Gray', 'Brown']
    genders = ['Male', 'Female']
    gender_map = {'Male': 'him', 'Female': 'her'}
    gender_map_2 = {'Male': 'man', "Female": 'women'}

    if request.method == 'POST':
        prompt = request.form.get('prompt')
        style = request.form.get('style')
        color = request.form.get('color')
        gender = request.form.get('gender') or 'Male'
        file = request.files.get('image')

        if prompt:
            base_prompt = prompt
        elif style and color:
            base_prompt = f"{color} {style}"
        else:
            flash("Please fill the prompt or choose color and style,")
            return redirect(url_for('generate_outfit'))

        pronoun = gender_map.get(gender, 'that person')
        prompt_text = f"Make {pronoun} wear {base_prompt}" if file else f"Generate a photorealistic image of {gender_map_2.get(gender, 'person')} wearing {base_prompt}"

        try:
            contents = outfit_model.prepare_generation_contents(prompt_text, file)
        except Exception as e:
            print(f"Error processing image: {e}")
            flash("Failed to process image. Please try again.")
            return redirect(url_for('generate_outfit'))

        try:
            response = outfit_model.generate_image_from_contents(contents)
        except Exception as e:
            print(f"Error calling API: {e}")
            flash("Failed to generate image. Please try again.")
            return redirect(url_for('generate_outfit'))

        try:
            last_fname = outfit_model.extract_image_from_response(response)
        except Exception:
            flash("Image generation failed. Please try again.")
            return redirect(url_for('generate_outfit'))

        if last_fname:
            gen_path = os.path.join(app.root_path, 'static', 'generated', last_fname)
            query = outfit_model.extract_query_from_image(gen_path)
            query = query.replace("*", "").strip().rstrip(",")
            db = get_db()
            db.execute('INSERT INTO history (filename, query) VALUES (?, ?)', (last_fname, query))
            db.commit()

        return redirect(url_for('search_outfit', filename=last_fname))

    return render_template('generate_outfit.html', styles=styles, colors=colors, genders=genders)

@app.route('/search/<filename>')
def search_outfit(filename):
    db = get_db()
    result = db.execute('SELECT query FROM history WHERE filename = ? LIMIT 1', (filename,)).fetchone()

    if not result:
        flash("No data found for the given image.")
        return redirect(url_for('generate_outfit'))

    query = result['query']
    img_url = url_for('static', filename=f'generated/{filename}')

    return render_template('search_outfit.html', images=[img_url], query=query)

@app.route('/search_data', methods=['GET'])
def search_data():
    query = request.args.get("query", "")
    query = extract_keywords(query)
    if not query:
        return jsonify([])

    try:
        detailed_items = outfit_model.search_data(query)
    except Exception as e:
        return jsonify({"error": f"Error fetching data: {e}"})

    return jsonify(detailed_items)

def extract_keywords(text):
    lines = text.splitlines()
    keywords = []

    for line in lines:
        if ':' in line:
            item, desc = line.split(':', 1)
            desc = desc.split(',')[0]
            keywords.append(f"{item.strip()} {desc.strip()}")
        elif line.strip():
            keywords.append(line.strip())

    return ', '.join(keywords)



@app.route('/outfit-recommend', methods=['GET', 'POST'])
def outfit_recommend():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('No file part')
            return redirect(request.url)

        file = request.files['image']

        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            # Save the image to the folder
            filename = secure_filename(file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(image_path)

            # Generate outfit suggestion
            outfit_suggestion = outfit_model.outfit_recommend(image_path)

            if outfit_suggestion:
                print(outfit_suggestion)
                return render_template('outfit_recommend.html',
                                       image_path=image_path,
                                       filename=filename,
                                       query=outfit_suggestion)
            flash("Cannot generate outfit suggestion from the image.")
            return redirect(url_for('outfit_recommend'))

        else:
            flash('Invalid file format')
            return redirect(request.url)

    return render_template('outfit_recommend.html', image_path=None, filename=None, query=None)


# Upload user image for try-on
@app.route('/tryon-outfit', methods=['GET', 'POST'])
def tryon_outfit():
    tryon_result = None
    sample_outfits = [
        "static/samples/outfit1.jpg",
        "static/samples/outfit2.jpg",
        "static/samples/outfit3.jpg"
    ]
    sample_people = [
        "static/samples/person1.jpg",
        "static/samples/person2.jpg",
        "static/samples/person3.jpg"
    ]
    if request.method == 'POST':
        person_image_path = None
        outfit_image_path = None
        # --- Ảnh người ---
        person_file = request.files.get('person_image')
        selected_person = request.form.get('sample_person')

        if person_file and person_file.filename != '' and allowed_file(person_file.filename):
            filename = secure_filename(person_file.filename)
            person_image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            person_file.save(person_image_path)
        elif selected_person in sample_people:
            person_image_path = selected_person

        # --- Ảnh outfit ---
        outfit_file = request.files.get('outfit_image')
        selected_outfit = request.form.get('sample_outfit')

        if outfit_file and outfit_file.filename != '' and allowed_file(outfit_file.filename):
            filename = secure_filename(outfit_file.filename)
            outfit_image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            outfit_file.save(outfit_image_path)
        elif selected_outfit in sample_outfits:
            outfit_image_path = selected_outfit

        # Kiểm tra đủ 2 ảnh
        if not person_image_path or not outfit_image_path:
            flash("Cần cung cấp ảnh người và outfit (upload hoặc chọn mẫu).")
            return redirect(request.url)

        # Thực hiện try-on
        tryon_output = outfit_model.try_on(person_image_path, outfit_image_path)
        if tryon_output:
            tryon_result = tryon_output
        else:
            flash("Xử lý thử đồ thất bại, vui lòng thử lại sau.")
            return redirect(request.url)

    return render_template('tryon_outfit.html',
                               sample_people=sample_people,
                               sample_outfits=sample_outfits,
                               tryon_result=tryon_result)



if __name__ == '__main__':
    init_db()
    app.run(debug=True)

