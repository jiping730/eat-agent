import operator
from typing import TypedDict, Annotated, List, Dict, Any
import traceback
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from core.memory import MemoryManager
from core.graph_rag import GraphRAGEngine
from utils.llm import get_llm
from config import settings

# 定义状态
class AgentState(TypedDict):
    messages: Annotated[List[Dict[str, str]], operator.add]   # 对话历史
    user_id: str                                               # 用户标识
    memory_context: List[str]                                  # 记忆检索结果
    current_goal: str                                          # 当前目标
    plan: List[str]                                            # 执行计划
    tool_outputs: Dict[str, Any]                               # 工具输出缓存
    reflection: str                                             # 反思结果
    iteration: int                                              # 当前迭代次数
    followup: bool

def create_workflow():
    # 初始化组件
    print("正在初始化 MemoryManager...")
    memory_mgr = MemoryManager()
    print("MemoryManager 初始化完成")

    # 尝试初始化 GraphRAG，如果失败则禁用
    graph_rag = None
    if settings.use_graphrag:
        try:
            print("正在初始化 GraphRAGEngine...")
            graph_rag = GraphRAGEngine()
            print("GraphRAGEngine 初始化成功")
        except Exception as e:
            print(f"警告: GraphRAG 初始化失败，已禁用图检索功能: {e}")
            graph_rag = None

    # 定义节点函数（包含详细日志和异常捕获）
    def understand_intent(state: AgentState) -> AgentState:
        print(">>> 进入 understand_intent")
        try:
            last_msg = state["messages"][-1]["content"]
            # 获取最近几轮对话作为上下文
            context_messages = state["messages"][-3:]  # 最近3条消息
            context_str = "\n".join(
                [f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}" for m in context_messages])

            # 调用 LLM 进行分类
            llm = get_llm()
            prompt = f"""请根据对话历史判断当前用户输入属于以下哪一类：
    - calorie_query: 用户询问食物的热量、卡路里等
    - meal_planner: 用户要求推荐餐食、搭配、组合等
    - followup: 用户使用代词（如“这个”、“它”、“那个”）或进行追问（如“有没有低卡的”、“晚上吃”），通常需要结合上一轮回答
    - general: 其他情况

    对话历史：
    {context_str}

    当前用户输入：{last_msg}

    只返回类别名称（如 calorie_query），不要输出其他内容。"""

            intent = llm.invoke(prompt).strip().lower()
            # 如果返回包含多个可能，取第一个
            if " " in intent:
                intent = intent.split()[0]
            if intent in ["calorie_query", "meal_planner", "followup"]:
                state["current_goal"] = intent
            else:
                state["current_goal"] = "general"

            print(f"用户输入: {last_msg}")
            print(f"当前目标: {state['current_goal']}")
        except Exception as e:
            print(f"❌ understand_intent 异常: {e}")
            traceback.print_exc()
            # 异常时回退到关键词匹配
            if "热量" in last_msg:
                state["current_goal"] = "calorie_query"
            elif "餐" in last_msg or "搭配" in last_msg:
                state["current_goal"] = "meal_planner"
            else:
                state["current_goal"] = "general"
        print("<<< 离开 understand_intent")
        return state

    def retrieve_memory(state: AgentState) -> AgentState:
        print(">>> 进入 retrieve_memory")
        try:
            if state.get("followup", False):
                print("追问模式，跳过长期记忆检索")
                state["memory_context"] = []
            else:
                query = state["messages"][-1]["content"]
                print(f"检索记忆，查询: {query}")
                memories = memory_mgr.retrieve_relevant_memories(query, user_id=state["user_id"])
                print(f"检索到 {len(memories)} 条记忆")
                state["memory_context"] = memories
        except Exception as e:
            print(f"❌ retrieve_memory 异常: {e}")
            traceback.print_exc()
            state["memory_context"] = []
        print("<<< 离开 retrieve_memory")
        return state

    def plan_actions(state: AgentState) -> AgentState:
        print(">>> 进入 plan_actions")
        try:
            goal = state["current_goal"]
            current_user_msg = state["messages"][-1]["content"]
            # 获取上一轮助手消息
            last_assistant_msg = ""
            if len(state["messages"]) >= 2 and state["messages"][-2]["role"] == "assistant":
                last_assistant_msg = state["messages"][-2]["content"]

            # 判断是否为追问：包含代词或模糊指示词，且上一轮有内容
            # 在 plan_actions 函数内，followup_keywords 扩展为：
            followup_keywords = [
                # 指示代词
                "这个", "那个", "这些", "那些", "它", "它们", "这", "那",
                # 时间相关
                "中午", "晚上", "早餐", "午餐", "晚餐", "明天", "后天", "今天", "昨天", "一会", "等会",
                # 动作/指令
                "搭配", "推荐", "帮我", "给我", "要", "想", "来", "换", "改", "做", "弄",
                # 延续/补充
                "再", "还", "也", "又", "继续", "另外", "还有", "除此之外",
                # 语气/反问
                "呢", "吗", "吧", "嘛", "呀", "啊", "怎么样", "如何", "什么", "啥", "怎么",
                # 比较/选择
                "别的", "其他", "另", "类似", "同样", "一样",
                # 数量/程度
                "一点", "一些", "稍微", "多", "少", "更", "最",
                # 否定/转折
                "不", "没", "不是", "不要", "别",
                # 多轮组合
                "两种", "两个", "都", "一起", "同时", "各", "分别", "混合"
            ]
            is_followup = any(word in current_user_msg for word in followup_keywords) and last_assistant_msg

            if is_followup:
                state["plan"] = []
                state["followup"] = True
                print("检测到追问，跳过工具调用")
            elif goal in ["calorie_query", "meal_planner"]:
                state["plan"] = [goal]
                state["followup"] = False
            else:
                state["plan"] = []
                state["followup"] = False
            print(f"执行计划: {state['plan']}, followup: {state.get('followup', False)}")
        except Exception as e:
            print(f"❌ plan_actions 异常: {e}")
            traceback.print_exc()
            state["plan"] = []
            state["followup"] = False
        print("<<< 离开 plan_actions")
        return state

    def execute_tool(state: AgentState) -> AgentState:
        print(">>> 进入 execute_tool")
        try:
            if not state["plan"]:
                print("计划为空，跳过工具执行")
                return state
            tool_name = state["plan"].pop(0)
            print(f"执行工具: {tool_name}")
            # 简化：返回模拟结果，实际应调用 MCP 客户端
            result = f"执行工具 {tool_name}，输入：{state['messages'][-1]['content']}"
            state["tool_outputs"][tool_name] = result
            print(f"工具结果: {result}")
        except Exception as e:
            print(f"❌ execute_tool 异常: {e}")
            traceback.print_exc()
        print("<<< 离开 execute_tool")
        return state

    def generate_answer(state: AgentState) -> AgentState:
        messages = state["messages"]
        # 构建最近5条对话历史
        history_lines = []
        for msg in messages[-5:]:
            role = "用户" if msg["role"] == "user" else "助手"
            history_lines.append(f"{role}：{msg['content']}")
        history_text = "\n".join(history_lines)

        current_question = state["messages"][-1]["content"]

        # 如果是追问模式
        if state.get("followup", False):
            # 提取最近3轮助手的回答（可能包含多个菜系）
            assistant_responses = []
            for i in range(len(messages) - 2, -1, -1):
                if messages[i]["role"] == "assistant":
                    assistant_responses.append(messages[i]["content"])
                    if len(assistant_responses) >= 3:
                        break
            assistant_responses.reverse()  # 保持时间顺序
            assistant_history = "\n\n".join(assistant_responses) if assistant_responses else "无历史记录"

            # 判断是否为多菜系组合请求
            multi_keywords = ["两种", "两个", "都", "一起", "同时", "各", "分别", "混合"]
            is_multi = any(kw in current_question for kw in multi_keywords)

            if is_multi:
                prompt = f"""请根据以下对话历史回答用户当前问题。用户想同时品尝之前提到的多种菜系，请结合历史中出现的所有菜系推荐。

    对话历史：
    {history_text}

    助手历史回答（可能包含多个菜系）：
    {assistant_history}

    当前用户问题：{current_question}

    请为用户推荐一个包含多种菜系的餐食组合。例如，如果之前提到了印度菜和湖南菜，请从这两种菜系中各选1-2道菜，组合成一份午餐或晚餐。回答要具体，包括菜品名称和简单说明。"""
            else:
                # 单一追问，使用上一轮助手内容
                prev_assistant = assistant_responses[-1] if assistant_responses else ""
                prompt = f"""请根据以下对话历史回答用户当前问题。这是一个追问，请务必结合上一轮助手的内容。

    对话历史：
    {history_text}

    上一轮助手回答（关键内容）：
    {prev_assistant}

    当前用户问题：{current_question}

    请基于上一轮助手的内容，为用户推荐符合要求的餐食组合。如果上一轮助手推荐了某个菜系（如印度菜、湖南菜）或具体菜品，请从该菜系或菜品中筛选出适合的菜品，并组合成适合用户要求的餐食（如午餐、晚餐）。回答要具体，包括菜品名称和简单的说明。"""
        else:
            context = {
                "memory": state["memory_context"],
                "tool_outputs": state["tool_outputs"],
                "graph_rag": graph_rag.search(current_question) if graph_rag else None
            }
            prompt = f"""请根据以下对话历史和相关上下文回答用户当前问题。

    对话历史：
    {history_text}

    当前用户问题：{current_question}

    上下文信息：{context}"""

        llm = get_llm()
        answer = llm.invoke(prompt)
        state["messages"].append({"role": "assistant", "content": answer})
        return state

    def reflect(state: AgentState) -> AgentState:
        print(">>> 进入 reflect")
        try:
            # 保存元记忆
            last_user_msg = state["messages"][-2]["content"]
            last_assistant_msg = state["messages"][-1]["content"]
            memory_mgr.save_meta(last_user_msg, last_assistant_msg, 1.0)
            print("元记忆已保存")
        except Exception as e:
            print(f"❌ reflect 异常: {e}")
            traceback.print_exc()
        print("<<< 离开 reflect")
        return state

    def should_continue(state: AgentState) -> str:
        print(">>> 进入 should_continue")
        try:
            if state["plan"]:
                print("计划非空，继续执行工具")
                return "execute_tool"
            else:
                print("计划为空，转向生成答案")
                return "generate_answer"
        except Exception as e:
            print(f"❌ should_continue 异常: {e}")
            traceback.print_exc()
            return "generate_answer"  # 默认转向生成答案
        finally:
            print("<<< 离开 should_continue")

    # 构建图
    print("开始构建 StateGraph...")
    # 构建图
    workflow = StateGraph(AgentState)

    workflow.add_node("understand", understand_intent)
    workflow.add_node("retrieve_memory", retrieve_memory)
    workflow.add_node("plan_actions", plan_actions)
    workflow.add_node("execute_tool", execute_tool)
    workflow.add_node("generate_answer", generate_answer)
    workflow.add_node("reflect", reflect)

    workflow.set_entry_point("understand")
    workflow.add_edge("understand", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "plan_actions")
    workflow.add_conditional_edges("plan_actions", should_continue)
    workflow.add_conditional_edges("execute_tool", should_continue)  # 关键修改
    workflow.add_edge("generate_answer", "reflect")
    workflow.add_edge("reflect", END)

    # 使用内存检查点
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app