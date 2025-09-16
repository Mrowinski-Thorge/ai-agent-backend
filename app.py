import os
import io
import json
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from groq import Groq
from pptx import Presentation
from pptx.util import Inches

# --- Initialisierung & Konfiguration ---
app = Flask(__name__)
CORS(app, resources={r"/generate": {"origins": "https://mrowinski-thorge.github.io"}})

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
WEBSITE_PASSWORD = os.environ.get("WEBSITE_PASSWORD")
if not GROQ_API_KEY or not WEBSITE_PASSWORD:
    raise ValueError("GROQ_API_KEY und WEBSITE_PASSWORD müssen als Umgebungsvariablen gesetzt sein.")

client = Groq(api_key=GROQ_API_KEY)

# --- Planner Konfiguration ---
PLANNER_MODEL = "llama-3.1-8b-instant"
AVAILABLE_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"
AVAILABLE_TOOLS = ["retrieval", "code_interpreter"]

PLANNER_SYSTEM_PROMPT = f"""
Du bist ein Planungs-Agent. Analysiere die Anfrage und erstelle den besten Plan als JSON.

**Verfügbare Ressourcen:**
- Modelle: {AVAILABLE_MODELS}
- Werkzeuge: {AVAILABLE_TOOLS}

**JSON-Schema:** {{ "final_model": "string", "final_tools": ["string"], "optimierter_prompt": "string" }}

**Deine Aufgabe (Modus 'automatic'):**
- Wähle das beste Modell: 'llama-3.3-70b-versatile' für komplexe Aufgaben, sonst 'llama-3.1-8b-instant'.
- Wähle Werkzeuge: Aktiviere 'retrieval' oder 'code_interpreter' nur, wenn sie absolut notwendig sind. Sonst gib eine LEERE Liste `[]` zurück.
- Optimiere den Prompt für das Ausgabeformat ('text', 'powerpoint', 'code').
"""

def handle_powerpoint_creation(ai_json_response):
    # Diese Funktion bleibt unverändert
    slides_data = ai_json_response.get('slides', [])
    prs = Presentation()
    for slide_info in slides_data:
        slide_layout = prs.slide_layouts[5]
        slide = prs.slides.add_slide(slide_layout)
        slide.shapes.title.text = slide_info.get('title', 'Kein Titel')
        left, top, width, height = Inches(0.5), Inches(1.5), Inches(9.0), Inches(5.5)
        txBox = slide.shapes.add_textbox(left, top, width, height)
        tf = txBox.text_frame
        content = slide_info.get('content', [])
        for point in content:
            p = tf.add_paragraph(); p.text = str(point); p.level = 0
        notes_slide = slide.notes_slide
        notes_slide.notes_text_frame.text = slide_info.get('notes', '')
    ppt_io = io.BytesIO()
    prs.save(ppt_io)
    ppt_io.seek(0)
    return ppt_io

@app.route('/generate', methods=['POST'])
def generate_agent_response():
    auth_header = request.headers.get('Authorization')
    if not auth_header or f"Bearer {WEBSITE_PASSWORD}" != auth_header:
        return jsonify({"error": "Ungültige Authentifizierung"}), 401

    data = request.get_json()
    if not data: return jsonify({"error": "Keine Daten erhalten"}), 400

    user_prompt = data.get('prompt')
    mode = data.get('mode', 'automatic')
    user_overrides = data.get('user_overrides', {})
    output_format = data.get('output_format', 'text')

    if not user_prompt: return jsonify({"error": "Kein Prompt angegeben"}), 400

    try:
        final_model = ""
        final_tools_names = []
        optimierter_prompt = ""

        if mode == 'manual':
            # Im manuellen Modus werden die Werte direkt und sicher gesetzt.
            final_model = user_overrides.get('model', 'llama-3.1-8b-instant')
            
            # Sichere Verarbeitung der Werkzeug-Auswahl
            manual_tools = user_overrides.get('tools', {})
            if manual_tools.get('websuche'):
                final_tools_names.append('retrieval')
            if manual_tools.get('code_interpreter'):
                final_tools_names.append('code_interpreter')
            
            # Der Prompt wird direkt übernommen, da der Benutzer die Kontrolle hat.
            optimierter_prompt = user_prompt

        else: # mode == 'automatic'
            # Nur im automatischen Modus wird der Planner befragt.
            planner_context = f"""
            User-Prompt: "{user_prompt}", Output-Format: "{output_format}"
            """
            planner_messages = [{"role": "system", "content": PLANNER_SYSTEM_PROMPT}, {"role": "user", "content": planner_context}]
            planner_completion = client.chat.completions.create(model=PLANNER_MODEL, messages=planner_messages, response_format={"type": "json_object"})
            plan = json.loads(planner_completion.choices[0].message.content)
            
            final_model = plan.get("final_model", "llama-3.1-8b-instant")
            # Auch hier werden leere Einträge sicher gefiltert.
            final_tools_names = [tool for tool in plan.get("final_tools", []) if tool]
            optimierter_prompt = plan.get("optimierter_prompt", user_prompt)

        # --- Executor-Phase ---
        system_prompt_executor = "Du bist ein Weltklasse-Experte."
        if output_format == 'code': system_prompt_executor = "Du bist ein erfahrener Software-Entwickler."
        elif output_format == 'powerpoint': system_prompt_executor = "Du bist ein Experte für Präsentationen."

        executor_messages = [{"role": "system", "content": system_prompt_executor}, {"role": "user", "content": optimierter_prompt}]
        
        # **DIE ENTSCHEIDENDE KORREKTUR**
        completion_params = {
            "model": final_model,
            "messages": executor_messages
        }
        # Der 'tools'-Parameter wird NUR hinzugefügt, wenn die Liste NICHT leer ist.
        if final_tools_names:
            completion_params["tools"] = [{"type": name} for name in final_tools_names]
        
        if output_format == 'powerpoint':
            completion_params["response_format"] = {"type": "json_object"}

        executor_completion = client.chat.completions.create(**completion_params)
        ai_response_content = executor_completion.choices[0].message.content

        # --- Ausgabe-Verarbeitung ---
        if output_format == 'powerpoint':
            ai_json = json.loads(ai_response_content)
            ppt_file = handle_powerpoint_creation(ai_json)
            return send_file(ppt_file, as_attachment=True, download_name='praesentation.pptx', mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation')
        else:
            return jsonify({"responseText": ai_response_content})

    except Exception as e:
        print(f"Ein Fehler ist aufgetreten: {e}")
        return jsonify({"error": "Ein interner Fehler ist auf dem Server aufgetreten.", "details": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
