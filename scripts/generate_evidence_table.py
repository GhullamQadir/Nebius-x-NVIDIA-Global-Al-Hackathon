"""Generate evidence table for model routing and adapter performance."""
import time
from typing import List, Dict, Any

from packages.contracts.schemas import ModelRequest
from packages.nebius_adapter.mock import MockModelProvider


def collect_metrics() -> List[Dict[str, Any]]:
    """Run mock calls and collect metrics for evidence table."""
    provider = MockModelProvider()
    results = []

    # Test cases across different scenarios
    test_cases = [
        {
            "name": "mock/nemotron-nano (low complexity)",
            "request": ModelRequest(prompt="Simple question", task_complexity="low"),
            "with_tools": False,
        },
        {
            "name": "mock/nemotron-super (moderate complexity)",
            "request": ModelRequest(prompt="Moderate complexity task with more details", task_complexity="moderate"),
            "with_tools": False,
        },
        {
            "name": "mock/nemotron-ultra (high complexity)",
            "request": ModelRequest(prompt="Complex reasoning task requiring deep analysis", task_complexity="high"),
            "with_tools": False,
        },
        {
            "name": "mock/nemotron-super (with tools)",
            "request": ModelRequest(
                prompt="Use tools to solve",
                task_complexity="moderate",
                tools=[{"type": "function", "function": {"name": "test_tool", "arguments": "{}"}}],
            ),
            "with_tools": True,
        },
    ]

    for case in test_cases:
        try:
            start = time.perf_counter()
            response = provider.complete(case["request"], model_id=case["name"])
            latency = (time.perf_counter() - start) * 1000.0

            results.append(
                {
                    "Scenario": case["name"],
                    "Latency (ms)": f"{latency:.2f}",
                    "Prompt Tokens": str(response.input_tokens),
                    "Completion Tokens": str(response.output_tokens),
                    "Total Tokens": str(response.total_tokens),
                    "Tool Calls Present (Yes/No)": "Yes" if response.tool_calls else "No",
                    "Status": "Success",
                }
            )
        except Exception as e:
            results.append(
                {
                    "Scenario": case["name"],
                    "Latency (ms)": "N/A",
                    "Prompt Tokens": "0",
                    "Completion Tokens": "0",
                    "Total Tokens": "0",
                    "Tool Calls Present (Yes/No)": "No",
                    "Status": f"Fail: {type(e).__name__}",
                }
            )

    return results


def print_markdown_table(results: List[Dict[str, Any]]) -> None:
    """Print formatted Markdown table."""
    if not results:
        return

    headers = [
        "Scenario",
        "Latency (ms)",
        "Prompt Tokens",
        "Completion Tokens",
        "Total Tokens",
        "Tool Calls Present (Yes/No)",
        "Status",
    ]

    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in results:
        values = [row.get(h, "") for h in headers]
        print("| " + " | ".join(str(v) for v in values) + " |")


def main() -> None:
    """Main function to generate evidence table."""
    print("# Evidence E01/E08 - Model Router and Adapter Metrics\n")
    results = collect_metrics()
    print_markdown_table(results)


if __name__ == "__main__":
    main()
