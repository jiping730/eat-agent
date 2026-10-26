import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
from core.conversation_runtime import ConversationRuntime

runtime = ConversationRuntime()
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    try:
        data = request.get_json(silent=True) or {}
        question = data.get('question', '')
        if not isinstance(question, str) or not question.strip():
            return jsonify({'error': 'question 不能为空'}), 400
        user_id = data.get('user_id')
        response = runtime.ask(question, user_id=user_id)
        return jsonify(response.to_dict())
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    try:
        app.run(debug=False, host="0.0.0.0", port=5000)
    except Exception as e:
        print("Flask run error:", e)
        import traceback
        traceback.print_exc()
