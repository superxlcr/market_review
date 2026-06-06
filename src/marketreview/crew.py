import os
from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from marketreview.tools.market_tools import (
    GetIndexTechnicalsTool,
    GetMarketBreadthTool,
    GetIndexContributionTool,
)


def _build_llm() -> LLM:
    """Build LLM from environment variables. Supports any OpenAI-compatible API."""
    model = os.environ.get("MODEL", "deepseek-chat")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    # OpenAI SDK expects base_url to end with /v1
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return LLM(
        model=f"openai/{model}",
        api_key=api_key,
        base_url=base_url,
        temperature=0.7,
        max_tokens=8000,
    )


@CrewBase
class Marketreview:
    """Marketreview crew — Agent 1: 大盘分析"""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def market_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["market_analyst"],  # type: ignore[index]
            llm=_build_llm(),
            tools=[
                GetIndexTechnicalsTool(),
                GetMarketBreadthTool(),
                GetIndexContributionTool(),
            ],
            verbose=True,
        )

    @task
    def market_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config["market_analysis_task"],  # type: ignore[index]
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
