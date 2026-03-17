from agent.agent_executor import create_agent_executor
from utils.callbacks import PerformanceCallbackHandler

def main():
    perf_callback = PerformanceCallbackHandler()
    agent_executor = create_agent_executor(callbacks=[perf_callback])

    print("Agentic RAG 智能问答系统已启动。输入 'exit' 退出。")
    while True:
        user_input = input("\n用户: ")
        if user_input.lower() in ['exit', 'quit']:
            break

        # 重置回调状态（为每次对话独立统计）
        perf_callback.total_retrievals = 0
        perf_callback.start_time = None
        perf_callback.end_time = None

        try:
            response = agent_executor.invoke({"input": user_input})
            answer = response['output']
            print(f"助手: {answer}")

            stats = perf_callback.get_stats()
            print(f"[性能] 响应时间: {stats['response_time']:.2f}秒, 检索次数: {stats['retrieval_count']}")
        except Exception as e:
            print(f"发生错误: {e}")

if __name__ == "__main__":
    main()