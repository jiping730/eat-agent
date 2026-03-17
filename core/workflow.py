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
            print(f"用户输入: {last_msg}")
            if "热量" in last_msg:
                state["current_goal"] = "calorie_query"
            elif "餐" in last_msg or "搭配" in last_msg:
                state["current_goal"] = "meal_planner"
            else:
                state["current_goal"] = "general"
            print(f"当前目标: {state['current_goal']}")
        except Exception as e:
            print(f"❌ understand_intent 异常: {e}")
            traceback.print_exc()
        print("<<< 离开 understand_intent")
        return state

    def retrieve_memory(state: AgentState) -> AgentState:
        print(">>> 进入 retrieve_memory")
        try:
            query = state["messages"][-1]["content"]
            print(f"检索记忆，查询: {query}")
            # 调用记忆管理器检索
            memories = memory_mgr.retrieve_relevant_memories(query, user_id=state["user_id"])
            print(f"检索到 {len(memories)} 条记忆")
            state["memory_context"] = memories
        except Exception as e:
            print(f"❌ retrieve_memory 异常: {e}")
            traceback.print_exc()
            # 异常时设为空列表，避免后续节点出错
            state["memory_context"] = []
        print("<<< 离开 retrieve_memory")
        return state

    def plan_actions(state: AgentState) -> AgentState:
        print(">>> 进入 plan_actions")
        try:
            goal = state["current_goal"]
            if goal in ["calorie_query", "meal_planner"]:
                state["plan"] = [goal]
            else:
                state["plan"] = []
            print(f"执行计划: {state['plan']}")
        except Exception as e:
            print(f"❌ plan_actions 异常: {e}")
            traceback.print_exc()
            state["plan"] = []
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
        print(">>> 进入 generate_answer")
        try:
            # 整合上下文
            context = {
                "memory": state["memory_context"],
                "tool_outputs": state["tool_outputs"],
                "graph_rag": graph_rag.search(state["messages"][-1]["content"]) if graph_rag else None
            }
            print(f"上下文: {context}")

            llm = get_llm()
            prompt = f"用户问题：{state['messages'][-1]['content']}\n上下文：{context}\n请回答。"
            print(f"调用 LLM，prompt: {prompt[:100]}...")  # 只打印前100字符

            answer = llm.invoke(prompt)
            print(f"LLM 回答: {answer}")

            state["messages"].append({"role": "assistant", "content": answer})
        except Exception as e:
            print(f"❌ generate_answer 异常: {e}")
            traceback.print_exc()
            # 异常时返回简单回答
            state["messages"].append({"role": "assistant", "content": "抱歉，我暂时无法回答。"})
        print("<<< 离开 generate_answer")
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
    workflow.add_node("plan", plan_actions)
    workflow.add_node("execute_tool", execute_tool)
    workflow.add_node("generate_answer", generate_answer)
    workflow.add_node("reflect", reflect)

    workflow.set_entry_point("understand")
    workflow.add_edge("understand", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "plan")
    workflow.add_conditional_edges("plan", should_continue)
    workflow.add_conditional_edges("execute_tool", should_continue)  # 关键修改
    workflow.add_edge("generate_answer", "reflect")
    workflow.add_edge("reflect", END)

    # 使用内存检查点
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app