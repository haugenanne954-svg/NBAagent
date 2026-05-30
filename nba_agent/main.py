"""CLI 入口：

用法：
    # 一次性问答
    python -m nba_agent.main "湖人最近怎么样？"

    # 进入交互式多轮（同一 thread_id 上下文保留）
    python -m nba_agent.main --interactive --thread my-session

    # 启动 Web 服务（浏览器交互）
    python -m nba_agent.main --serve
    python -m nba_agent.main --serve --port 8080
"""
from __future__ import annotations

import argparse
import sys
import uuid

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

from langchain_core.messages import HumanMessage
from loguru import logger

from .flow import emit_flow_event, run_graph_with_flow_sync
from .graph import build_graph


def _setup_logger(verbose: bool) -> None:
    """配置 loguru 日志级别：verbose=True 时输出 DEBUG，否则 INFO。"""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="<level>[{level}]</level> {message}")


def run_oneshot(query: str, thread_id: str, stream: bool = False) -> str:
    """单次问答：构建图、执行一次 invoke、返回最终回答。"""
    graph = build_graph()
    if stream:
        return run_graph_with_flow_sync(graph, query, thread_id=thread_id, emit=emit_flow_event)

    # thread_id 用于 SQLite checkpointer 区分不同对话上下文
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=query)],
            "user_query": query,
            "visited": [],  # 新一轮清空已访问列表
        },
        config=config,
    )
    # 最终回答由 finalize 节点写入 messages 末尾
    return result["messages"][-1].content


def run_interactive(thread_id: str, stream: bool = False) -> None:
    """交互式多轮对话：同一 thread_id 保持上下文，输入 exit/quit 退出。"""
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    print(f"=== NBA 助手（thread_id={thread_id}）输入 'exit' 退出 ===")
    while True:
        try:
            query = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in {"exit", "quit", ":q"}:
            break

        if stream:
            print("\n助手> ", end="", flush=True)
            run_graph_with_flow_sync(graph, query, thread_id=thread_id, emit=emit_flow_event)
            print()
        else:
            result = graph.invoke(
                {
                    "messages": [HumanMessage(content=query)],
                    "user_query": query,
                    "visited": [],
                },
                config=config,
            )
            print(f"\n助手> {result['messages'][-1].content}")


def run_server(port: int = 8000) -> None:
    """启动 FastAPI Web 服务，提供浏览器交互界面。"""
    import uvicorn
    from .server import app
    logger.info("NBA Agent Web 服务启动: http://localhost:{}", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def main() -> None:
    """CLI 入口：解析命令行参数，选择一次性或交互式模式运行。"""
    parser = argparse.ArgumentParser(description="NBA 助手 Agent CLI")
    parser.add_argument("query", nargs="?", help="一次性提问")
    parser.add_argument("--interactive", "-i", action="store_true", help="进入交互式多轮")
    parser.add_argument("--serve", "-s", action="store_true", help="启动 Web 服务（浏览器交互）")
    parser.add_argument("--port", type=int, default=8000, help="Web 服务端口（默认 8000）")
    parser.add_argument("--stream", action="store_true", help="在 CLI 中显示 LangGraph 执行进度并流式输出最终回答")
    parser.add_argument("--thread", default=None, help="对话 thread_id（多轮上下文 key）")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印 DEBUG 日志")
    args = parser.parse_args()

    _setup_logger(args.verbose)

    if args.serve:
        run_server(port=args.port)
        return

    thread_id = args.thread or f"oneshot-{uuid.uuid4().hex[:8]}"

    if args.interactive:
        run_interactive(thread_id, stream=args.stream)
        return

    if not args.query:
        parser.print_help()
        sys.exit(1)

    answer = run_oneshot(args.query, thread_id, stream=args.stream)
    if not args.stream:
        print(answer)


if __name__ == "__main__":
    main()
