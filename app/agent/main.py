import sys

from app.agent.llm import get_llm


async def run_agent(
    query: str, thread_id: str, user_id: str | None = None
) -> dict[str, object]:
    """Lazy import keeps the CLI usable before service dependencies initialize."""
    from app.agent.main_agent import run_agent as run_main_agent

    return await run_main_agent(query, thread_id, user_id)


def main() -> None:
    prompt = " ".join(sys.argv[1:]).strip() or "用一句话介绍 agent"
    response = get_llm().invoke(prompt)
    print(response.content)


if __name__ == "__main__":
    main()
