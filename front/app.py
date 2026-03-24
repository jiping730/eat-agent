import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
from core.workflow import create_workflow
from core.memory import MemoryManager
import uuid
# 在文件顶部添加
from collections import defaultdict
user_histories = defaultdict(list)   # 存储每个用户的消息历史

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
def ask():
    try:
        data = request.get_json()
        question = data.get('question', '')
        user_id = data.get('user_id', str(uuid.uuid4()))
        config = {"configurable": {"thread_id": user_id}}

        # 获取该用户的历史消息（如果有）
        history = user_histories.get(user_id, [])
        # 将当前用户问题加入历史
        history.append({"role": "user", "content": question})

        # 构建初始状态（包含完整历史）
        initial_state = {
            "messages": history,
            "user_id": user_id,
            "memory_context": [],
            "current_goal": "",
            "plan": [],
            "tool_outputs": {},
            "reflection": "",
            "iteration": 0,
            "followup": False
        }

        start = time.time()
        final_state = workflow.invoke(initial_state, config=config)
        elapsed = time.time() - start

        # 获取助手回复
        answer = final_state["messages"][-1]["content"]
        # 将助手回复也加入历史
        history.append({"role": "assistant", "content": answer})
        user_histories[user_id] = history

        memory_mgr.add_interaction(question, answer, user_id)

        return jsonify({
            "answer": answer,
            "response_time": round(elapsed, 2),
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