import os
import io
import json
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from groq import Groq
from pptx import Presentation

# --- Initialisierung ---
app = Flask(__name__)

# CORS für die Verbindung mit GitHub Pages einrichten
# Erlaubt Anfragen von Ihrer zukünftigen GitHub Pages Webseite
CORS(app, resources={r"/generate": {"origins": "https://mrowinski-thorge.github.io"}})

# --- Sichere Konfiguration aus Umgebungsvariablen ---
# Auf Render.com müssen diese als Environment Variables gesetzt werden.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
WEBSITE_PASSWORD = os.environ.get("WEBSITE_PASSWORD") # Das Passwort für unsere Webseite

if not GROQ_API_KEY or not WEBSITE_PASSWORD:
    raise ValueError("GROQ_API_KEY und WEBSITE_PASSWORD müssen als Umgebungsvariablen gesetzt sein.")

client = Groq(api_key=GROQ_API_KEY)


# --- Hilfsfunktionen (für Erweiterbarkeit) ---

def handle_powerpoint_creation(ai_json_response):
    """Erstellt eine PowerPoint-Datei aus der JSON-Antwort der KI."""
    slides_data = ai_json_response.get('slides', [])
    prs = Presentation()
    for slide_info in slides_data:
        slide_layout = prs.slide_layouts[1]
        slide = prs.slides.add_slide(slide_layout)
        slide.shapes.title.text = slide_info.get('title', 'Kein Titel')
        body_shape = slide.placeholders[1]
        tf = body_shape.text_frame
        tf.clear()
        for point in slide_info.get('content', []):
            p = tf.add_paragraph()
            p.text = str(point)
            p.level = 0
    
    ppt_io = io.BytesIO()
    prs.save(ppt_io)
    ppt_io.seek(0)
    return ppt_io


# --- Der zentrale API-Endpunkt ---
@app.route('/generate', methods=['POST'])
def generate_agent_response():
    # 1. Sicherheits-Check: Passwort verifizieren
    auth_header = request.headers.get('Authorization')
    if not auth_header or f"Bearer {WEBSITE_PASSWORD}" != auth_header:
        return jsonify({"error": "Ungültige oder fehlende Authentifizierung"}), 401

    # 2. Anfrage-Daten vom Frontend auslesen
    data = request.get_json()
    prompt = data.get('prompt')
    model = data.get('model', 'groq/compound')
    output_format = data.get('output_format', 'text')
    enabled_tools = data.get('tools', {})

    if not prompt:
        return jsonify({"error": "Kein Prompt angegeben"}), 400

    # 3. Dynamisch die Werkzeuge für Groq zusammenbauen
    tools_for_groq = []
    if enabled_tools.get('websuche'):
        tools_for_groq.append({"type": "browser_search"})
    if enabled_tools.get('code_interpreter'):
        tools_for_groq.append({"type": "code_interpreter"})

    # 4. System-Prompt basierend auf dem Ausgabeformat anpassen
    system_prompt = "Du bist ein hilfreicher KI-Assistent."
    response_format = None # Standardmäßig kein festes Format
    
    if output_format == 'powerpoint':
        system_prompt = "Du bist ein Experte für die Erstellung von Präsentationen. Gib deine Antwort IMMER als JSON-Objekt zurück, das dem Schema folgt: { \"slides\": [ { \"title\": \"string\", \"content\": [\"string\"] } ] }"
        response_format = {"type": "json_object"}

    try:
        # 5. Groq API aufrufen
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        
        completion_params = {
            "model": model,
            "messages": messages,
        }
        # Nur wenn Tools aktiviert sind, diese auch an die API senden
        if tools_for_groq:
            completion_params["tools"] = tools_for_groq
        # Nur wenn ein JSON-Format benötigt wird, dieses auch anfordern
        if response_format:
            completion_params["response_format"] = response_format

        chat_completion = client.chat.completions.create(**completion_params)
        ai_response_content = chat_completion.choices[0].message.content

        # 6. Ausgabe basierend auf dem Format verarbeiten
        if output_format == 'powerpoint':
            ai_json = json.loads(ai_response_content)
            ppt_file = handle_powerpoint_creation(ai_json)
            return send_file(
                ppt_file,
                as_attachment=True,
                download_name=f'praesentation.pptx',
                mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation'
            )
        else: # Standard ist 'text'
            return jsonify({"responseText": ai_response_content})

    except Exception as e:
        print(f"Ein Fehler ist aufgetreten: {e}")
        return jsonify({"error": "Ein interner Fehler ist aufgetreten.", "details": str(e)}), 500

# --- Server-Start ---
if __name__ == '__main__':
    # Dieser Modus ist nur für lokales Testen. Render.com nutzt gunicorn.
    app.run(debug=True, port=5001)
