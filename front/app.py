import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
from core.workflow import create_workflow
from core.memory import MemoryManager
import uuid

workflow = None
memory_mgr = None

try:
    workflow = create_workflow()
    memory_mgr = MemoryManager()
    print("工作流和记忆管理器初始化成功")
except Exception as e:
    print("初始化工作流或记忆管理器失败:", e)
    import traceback
    traceback.print_exc()
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
@app.route('/ask', methods=['POST'])
def ask():
    try:
        data = request.get_json()
        question = data.get('question', '')
        user_id = data.get('user_id', str(uuid.uuid4()))

        # 如果工作流未初始化，返回错误
        if workflow is None or memory_mgr is None:
            return jsonify({'error': '工作流未初始化'}), 500

        initial_state = {
            "messages": [{"role": "user", "content": question}],
            "user_id": user_id,
            "memory_context": [],
            "current_goal": "",
            "plan": [],
            "tool_outputs": {},
            "reflection": "",
            "iteration": 0
        }

        config = {"configurable": {"thread_id": user_id}}
        print("开始调用 workflow.invoke")
        final_state = workflow.invoke(initial_state, config=config)
        print("workflow.invoke 调用完成")

        memory_mgr.add_interaction(question, final_state["messages"][-1]["content"], user_id)

        return jsonify({
            "answer": final_state["messages"][-1]["content"],
            "response_time": final_state.get("response_time", 0),
            "retrieval_count": len(final_state["tool_outputs"])
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    try:
        app.run(debug=False, port=5000)
    except Exception as e:
        print("Flask run error:", e)
        import traceback
        traceback.print_exc()