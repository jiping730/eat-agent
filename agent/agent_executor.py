from langchain.agents import create_react_agent, AgentExecutor
from langchain_community.chat_models import ChatZhipuAI
from agent.tools import create_retrieval_tool
from agent.prompt import react_prompt
from config import settings

def create_agent_executor(callbacks=None):
    llm = ChatZhipuAI(
        model=settings.llm_model,
        api_key=settings.zhipuai_api_key,
        temperature=0.7
    )
    tools = [create_retrieval_tool()]
    agent = create_react_agent(llm=llm, tools=tools, prompt=react_prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,                # 打印中间步骤（调试用）
        handle_parsing_errors=True,
        callbacks=callbacks
    )
    return agent_executor