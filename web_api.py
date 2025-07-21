# web_api.py
from flask import Flask, request, jsonify, send_from_directory
from assistant_core import handle_question

app = Flask(__name__, static_folder="static", template_folder="static")

@app.route("/api/ask", methods=["POST"])
def ask():
    payload = request.json or {}
    question = payload.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400

    # call your refactored logic
    answer = handle_question(
        question=question,
        speaker=payload.get("speaker", "arnold"),
        language=payload.get("language"),
        speed=payload.get("speed", 1.0),
        save_json=payload.get("save_json", False)
    )
    return jsonify({ "answer": answer })

# serve the static HTML/JS
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and (app.static_folder / path).exists():
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    # bind to 0.0.0.0 if you want LAN access
    app.run(host="127.0.0.1", port=8000, debug=True)
