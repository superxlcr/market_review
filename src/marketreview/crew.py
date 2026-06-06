from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from marketreview.tools.market_tools import (
    GetIndexTechnicalsTool,
    GetMarketBreadthTool,
    GetIndexContributionTool,
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
