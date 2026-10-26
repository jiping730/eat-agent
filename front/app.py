import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

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
        if not isinstance(question, str) or not question.strip():
            return jsonify({'error': 'question 不能为空'}), 400
        user_id = data.get('user_id', str(uuid.uuid4()))
        config = {"configurable": {"thread_id": user_id}}

        # MemorySaver 会按 thread_id 保存上一轮 Grill 上下文。第二轮只
        # 追加一条 user 消息，避免把完整历史再次喂给 operator.add reducer。
        history = list(user_histories.get(user_id, []))
        user_message = {"role": "user", "content": question.strip()}
        if history:
            initial_state = {"messages": [user_message], "user_id": user_id}
        else:
            initial_state = {
                "messages": [user_message],
                "user_id": user_id,
                "memory_context": [],
                "current_goal": "",
                "plan": [],
                "tool_outputs": {},
                "reflection": "",
                "iteration": 0,
                "followup": False,
                "grill_context": {},
                "grill_result": {},
            }

        start = time.time()
        final_state = workflow.invoke(initial_state, config=config)
        elapsed = time.time() - start

        assistant_messages = [m for m in final_state.get("messages", []) if m.get("role") == "assistant"]
        answer = assistant_messages[-1]["content"] if assistant_messages else "暂时无法生成回答。"
        history.extend([user_message, {"role": "assistant", "content": answer}])
        user_histories[user_id] = history

        grill_result = final_state.get("grill_result", {}) or {}
        grill_action = grill_result.get("action")

        # 追问本身不是最终知识回答，不写入长期记忆；最终回答才写入。
        if grill_action not in {"clarify", "fallback", "pending_confirmation"}:
            memory_mgr.add_interaction(question, answer, user_id)

        response_type = {
            "clarify": "clarification",
            "fallback": "clarification",
            "pending_confirmation": "confirmation",
        }.get(grill_action, "answer")

        return jsonify({
            "answer": answer,
            "type": response_type,
            "target_field": grill_result.get("target_field"),
            "options": grill_result.get("candidates", []),
            "assumptions": grill_result.get("assumptions", []),
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
