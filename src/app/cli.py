from __future__ import annotations

import argparse
from pathlib import Path

from app.graph import ShoppingAssistant


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shopping Assistant CLI.")
    parser.add_argument("--question", help="Run one question through the graph.")
    parser.add_argument("--test-file", default="data/test.json")
    parser.add_argument("--trace-file", default=None)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true", help="Force rebuild Chroma index.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    assistant = ShoppingAssistant()

    if args.batch:
        test_file = Path(args.test_file)
        output_dir = assistant.settings.traces_dir
        print(f"Running batch test from {test_file} ...")
        summary = assistant.run_batch(
            test_file=test_file,
            output_dir=output_dir,
            rebuild_index=args.rebuild_index,
        )
        print(f"\nBatch complete: {summary['ok']}/{summary['total']} OK")
        print(f"Summary saved to: {output_dir / 'summary.json'}")
        for r in summary["results"]:
            status_icon = "✓" if r["status"] == "ok" else "✗"
            print(f"  [{status_icon}] {r['id']}: {r.get('final_answer', r.get('error', ''))[:120]}")

    elif args.question:
        trace_file = Path(args.trace_file) if args.trace_file else None
        result = assistant.ask(
            question=args.question,
            trace_file=trace_file,
            rebuild_index=args.rebuild_index,
        )
        print("\n" + "=" * 60)
        print(f"Question: {args.question}")
        print("=" * 60)
        print(result["final_answer"])
        if trace_file:
            print(f"\nTrace saved to: {trace_file}")

    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
