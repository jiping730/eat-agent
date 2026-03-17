import sys
import os
# 将项目根目录（front 的上一级）加入 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from agent.agent_executor import create_agent_executor
from utils.callbacks import PerformanceCallbackHandler

app = Flask(__name__,
            template_folder='templates',      # 指定模板文件夹路径
            static_folder='static')           # 指定静态文件夹路径
CORS(app)

# 全局 Agent 执行器
agent_executor = None
perf_callback = PerformanceCallbackHandler()

def get_agent():
    global agent_executor
    if agent_executor is None:
        agent_executor = create_agent_executor(callbacks=[perf_callback])
    return agent_executor

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    data = request.get_json()
    question = data.get('question', '')
    if not question:
        return jsonify({'error': '问题不能为空'}), 400

    # 重置性能统计
    perf_callback.total_retrievals = 0
    perf_callback.start_time = None
    perf_callback.end_time = None

    try:
        agent = get_agent()
        start = time.time()
        response = agent.invoke({"input": question})
        end = time.time()
        answer = response.get('output', '')
        stats = perf_callback.get_stats()
        response_time = stats['response_time'] if stats['response_time'] else (end - start)
        return jsonify({
            'answer': answer,
            'response_time': round(response_time, 2),
            'retrieval_count': stats['retrieval_count']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)