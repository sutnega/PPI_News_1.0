from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .errors import AdapterError
from .registry import create_adapter, list_sources


def _write_jsonl(items: list[object], destination: str) -> None:
    lines = [json.dumps(item.to_dict(), ensure_ascii=False) for item in items]  # type: ignore[attr-defined]
    payload = "\n".join(lines) + ("\n" if lines else "")
    if destination == "-":
        sys.stdout.write(payload)
    else:
        Path(destination).write_text(payload, encoding="utf-8")


def command_list(as_json: bool) -> int:
    configs = list_sources()
    if as_json:
        sys.stdout.write(json.dumps([
            {"slug": c.slug, "source_id": c.source_id, "source_name": c.source_name, "endpoint": c.endpoint}
            for c in configs
        ], ensure_ascii=False, indent=2) + "\n")
    else:
        print("slug\tsource_id\tsource_name\tendpoint")
        for c in configs:
            print(f"{c.slug}\t{c.source_id}\t{c.source_name}\t{c.endpoint}")
    return 0


def command_collect(args: argparse.Namespace) -> int:
    try:
        with create_adapter(args.source, respect_robots=not args.ignore_robots, retries=args.retries) as adapter:
            items, report = adapter.collect(limit=args.limit)
        _write_jsonl(items, args.output)
        print(json.dumps(report.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 0
    except (AdapterError, OSError) as exc:
        print(json.dumps({"source": args.source, "status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


def command_extract_file(args: argparse.Namespace) -> int:
    html = Path(args.html_file).read_text(encoding=args.encoding)
    with create_adapter(args.source, respect_robots=False, retries=1) as adapter:
        items = adapter.extract_html(html, base_url=args.base_url, limit=args.limit)
    _write_jsonl(items, args.output)
    return 0 if items else 3


def command_probe_all(args: argparse.Namespace) -> int:
    failures = 0
    reports: list[dict[str, object]] = []
    for config in list_sources():
        try:
            with create_adapter(config.slug, respect_robots=not args.ignore_robots, retries=args.retries) as adapter:
                items, report = adapter.collect(limit=args.limit)
            reports.append(report.to_dict())
            if args.output_dir:
                target = Path(args.output_dir) / f"{config.slug}.jsonl"
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_jsonl(items, str(target))
        except (AdapterError, OSError) as exc:
            failures += 1
            reports.append({"source_id": config.source_id, "source_name": config.source_name, "status": "ERROR", "error": str(exc)})
            if args.stop_on_error:
                break
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 2 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ppi-html", description="PPI Radar standalone HTML adapters")
    parser.add_argument("--verbose", action="store_true", help="Enable diagnostic logs")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="List the 21 configured sources")
    list_cmd.add_argument("--json", action="store_true")

    collect = sub.add_parser("collect", help="Fetch one source and emit JSONL")
    collect.add_argument("source", help="Source slug from `ppi-html list`")
    collect.add_argument("--limit", type=int, default=50)
    collect.add_argument("--retries", type=int, default=3)
    collect.add_argument("--output", default="-", help="JSONL file or - for stdout")
    collect.add_argument("--ignore-robots", action="store_true", help="Explicitly disable robots.txt enforcement")

    extract = sub.add_parser("extract-file", help="Run an adapter against a saved HTML fixture")
    extract.add_argument("source")
    extract.add_argument("html_file")
    extract.add_argument("--base-url")
    extract.add_argument("--encoding", default="utf-8")
    extract.add_argument("--limit", type=int, default=50)
    extract.add_argument("--output", default="-")

    probe = sub.add_parser("probe-all", help="Sequentially smoke-test all sources")
    probe.add_argument("--limit", type=int, default=5)
    probe.add_argument("--retries", type=int, default=2)
    probe.add_argument("--output-dir")
    probe.add_argument("--stop-on-error", action="store_true")
    probe.add_argument("--ignore-robots", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "list":
        return command_list(args.json)
    if args.command == "collect":
        return command_collect(args)
    if args.command == "extract-file":
        return command_extract_file(args)
    if args.command == "probe-all":
        return command_probe_all(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

