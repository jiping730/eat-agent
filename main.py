from core.conversation_runtime import ConversationRuntime

def main():
    runtime = ConversationRuntime()
    user_id = "cli-user"

    print("Agentic RAG 智能问答系统已启动。输入 'exit' 退出。")
    while True:
        user_input = input("\n用户: ")
        if user_input.lower() in ['exit', 'quit']:
            break

        try:
            response = runtime.ask(user_input, user_id=user_id)
            print(f"助手: {response.answer}")
            print(f"[性能] 响应时间: {response.response_time:.2f}秒, 检索次数: {response.retrieval_count}")
        except Exception as e:
            print(f"发生错误: {e}")

if __name__ == "__main__":
    main()
