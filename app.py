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

# --- NEU: Finaler Planner ---
PLANNER_MODEL = "llama-3.1-8b-instant"
AVAILABLE_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
AVAILABLE_TOOLS = ["retrieval", "code_interpreter"]

PLANNER_SYSTEM_PROMPT = f"""
Du bist ein hochintelligenter Planungs-Agent. Deine Aufgabe ist es, die Anfrage eines Benutzers zu analysieren und den optimalen Ausführungsplan als JSON-Objekt zu erstellen.

**Verfügbare Ressourcen:**
- Modelle: {AVAILABLE_MODELS}
- Werkzeuge: {AVAILABLE_TOOLS}

**Dein Ziel:**
Erstelle ein JSON-Objekt basierend auf dem User-Prompt, dem `mode` und den `user_overrides`.

**JSON-Schema:**
{{
  "final_model": "string",
  "final_tools": ["string"],
  "final_url": "string | null",
  "optimierter_prompt": "string"
}}

**REGELN JE NACH MODUS:**

**1. Wenn `mode` == "manual":**
   - **Respektiere Benutzervorgaben:** Die `user_overrides` sind Befehle. Verwende das vom Benutzer gewählte Modell, die Werkzeuge und die URL für `final_model`, `final_tools` und `final_url`.
   - **Optimiere den Prompt:** Formuliere den `optimierter_prompt`, um die manuell gewählten Werkzeuge bestmöglich zu nutzen.

**2. Wenn `mode` == "automatic":**
   - **Ignoriere `user_overrides`:** Du hast die volle Kontrolle.
   - **Modellwahl:** Wähle 'llama3.1-70b-versatile' für komplexe Aufgaben/Code, sonst 'mixtral-8x7b-32768'.
   - **Werkzeugwahl:** Aktiviere 'retrieval' für aktuelle Infos. Aktiviere 'code_interpreter' für Berechnungen.
   - **URL-Recherche:** Wenn 'retrieval' nötig ist, weise den Executor im `optimierter_prompt` an, zuerst eine Websuche durchzuführen, um die besten URLs zum Thema zu finden, und DANN diese URLs zur Beantwortung der Frage zu nutzen. Setze `final_url` auf `null`.
   - **Optimiere den Prompt:** Erstelle eine sehr detaillierte Anweisung für den Executor.

**PROMPT-OPTIMIERUNG FÜR AUSGABEFORMATE:**
- **`powerpoint`:** Der `optimierter_prompt` MUSS die Anweisung enthalten, ein JSON nach dem Schema `{{ "slides": [ ... ] }}` zu erstellen.
- **`code`:** Der `optimierter_prompt` MUSS die Anweisung enthalten, einen vollständigen, kommentierten Code-Block in der passenden Programmiersprache zu liefern, formatiert mit Markdown (z.B. ```python ... ```).
- **`text`:** Formuliere eine klare, offene Frage.
"""

# ... (handle_powerpoint_creation Funktion bleibt unverändert) ...

# --- Der zentrale API-Endpunkt ---
@app.route('/generate', methods=['POST'])
def generate_agent_response():
    # 1. Sicherheit & Daten-Extraktion
    auth_header = request.headers.get('Authorization')
    # ... (Sicherheitscheck bleibt gleich) ...

    data = request.get_json()
    user_prompt = data.get('prompt')
    mode = data.get('mode', 'automatic')
    user_overrides = data.get('user_overrides', {})
    output_format = data.get('output_format', 'text')
    
    # ... (Prompt-Check bleibt gleich) ...

    try:
        # --- SCHRITT 1: PLANNER ---
        planner_context = f"""
        Mode: "{mode}"
        User-Prompt: "{user_prompt}"
        Output-Format: "{output_format}"
        User-Overrides: {json.dumps(user_overrides)}
        """
        
        planner_messages = [{"role": "system", "content": PLANNER_SYSTEM_PROMPT}, {"role": "user", "content": planner_context}]
        planner_completion = client.chat.completions.create(model=PLANNER_MODEL, messages=planner_messages, response_format={"type": "json_object"})
        plan = json.loads(planner_completion.choices[0].message.content)

        # --- SCHRITT 2: EXECUTOR ---
        final_model = plan.get("final_model")
        final_tools_names = plan.get("final_tools", [])
        executor_prompt = plan.get("optimierter_prompt")

        # System-Prompt für den Executor je nach Aufgabe anpassen
        system_prompt_executor = "Du bist ein Weltklasse-Experte. Führe die Anweisung präzise aus."
        if output_format == 'code':
            system_prompt_executor = "Du bist ein erfahrener Software-Entwickler. Schreibe sauberen, effizienten und gut dokumentierten Code."
        elif output_format == 'powerpoint':
            system_prompt_executor = "Du bist ein Experte für die Erstellung überzeugender Präsentationen."

        executor_messages = [{"role": "system", "content": system_prompt_executor}, {"role": "user", "content": executor_prompt}]
        
        completion_params = {"model": final_model, "messages": executor_messages}
        if final_tools_names:
            completion_params["tools"] = [{"type": name} for name in final_tools_names]
        if output_format == 'powerpoint':
            completion_params["response_format"] = {"type": "json_object"}

        executor_completion = client.chat.completions.create(**completion_params)
        ai_response_content = executor_completion.choices[0].message.content

        # 3. Ausgabe verarbeiten
        if output_format == 'powerpoint':
            ai_json = json.loads(ai_response_content)
            ppt_file = handle_powerpoint_creation(ai_json)
            return send_file(ppt_file, as_attachment=True, download_name='praesentation.pptx', mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation')
        else: # Gilt für 'text' und 'code'
            return jsonify({"responseText": ai_response_content})

    except Exception as e:
        print(f"Ein Fehler ist aufgetreten: {e}")
        return jsonify({"error": "Ein interner Fehler ist auf dem Server aufgetreten.", "details": str(e)}), 500

# --- Server-Start ---
if __name__ == '__main__':
    app.run(debug=True, port=5001)
