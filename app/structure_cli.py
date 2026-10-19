"""Structure a book page by page: render a page to read, compile page plans, import and export page trees.

Evidence comes from a run in the database (--run) or, for work outside it, from
an exported lines file and the source PDF (--lines and --pdf).

  python -m app.structure_cli prep --run R --page 12 --out work/
  python -m app.structure_cli compile --run R --page 12 plans/p012.plan --by claude
  python -m app.structure_cli compile --lines lines.json --pdf book.pdf --page 12 plans/p012.plan --out pages/
  python -m app.structure_cli import --run R pages/
  python -m app.structure_cli export --run R pages/
  python -m app.structure_cli status --run R
  python -m app.structure_cli export-grammar --run R --profile profile.json site-data/
  python -m app.structure_cli export-grammar --pages pages/ --pdf book.pdf --profile profile.json site-data/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.structure.evidence import load_lines, run_lines, text_layer_words
from app.structure.plan import compile_plan


def _dump(tree: dict) -> str:
    return json.dumps(tree, ensure_ascii=False, indent=1)


def _evidence(args, db):
    if args.run:
        from app.structure.store import source_pdf

        return run_lines(db, args.run), source_pdf(db, args.run)
    if not (args.lines and args.pdf):
        raise SystemExit("give --run, or both --lines and --pdf")
    return load_lines(args.lines), args.pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prep", "compile", "import", "export", "status"):
        command = sub.add_parser(name)
        command.add_argument("--run")
        if name in ("prep", "compile"):
            command.add_argument("--lines")
            command.add_argument("--pdf")
            command.add_argument("--page", type=int, required=True)
    sub.choices["prep"].add_argument("--out", required=True, help="directory for the page image")
    sub.choices["compile"].add_argument("plan")
    sub.choices["compile"].add_argument("--by", default="claude", help="who wrote the plan")
    sub.choices["compile"].add_argument("--out", help="without --run: directory for pNNN.json")
    sub.choices["import"].add_argument("pages")
    sub.choices["import"].add_argument("--producer", default="import")
    sub.choices["export"].add_argument("pages")
    grammar = sub.add_parser("export-grammar", help="grammar.json and pictures for the reading site")
    grammar.add_argument("--run")
    grammar.add_argument("--pages", help="without --run: directory of pNNN.json")
    grammar.add_argument("--pdf", help="without --run: the source PDF")
    grammar.add_argument("--profile", required=True, help="the book profile (JSON)")
    grammar.add_argument("out")
    args = parser.parse_args(argv)

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.command == "prep":
            lines, pdf = _evidence(args, db)
            import fitz

            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            target = out / f"p{args.page:03d}.png"
            with fitz.open(pdf) as document:
                document[args.page - 1].get_pixmap(matrix=fitz.Matrix(1.15, 1.15), alpha=False).save(str(target))
            print(target)
            for i, line in enumerate(lines.get(args.page, []), 1):
                flag = "" if line.get("check") in (None, "ACCEPTED") else " ?"
                print(f"{i}|{line['box'][0]:.2f},{line['box'][1]:.2f}|{line['text']}{flag}")
        elif args.command == "compile":
            plan = Path(args.plan).read_text(encoding="utf-8")
            if args.run:
                from app.structure.store import compile_and_save

                record = compile_and_save(db, args.run, args.page, plan, author=args.by)
                print(json.dumps({**record.checks, "version": record.version, "status": record.status}, ensure_ascii=False))
            else:
                lines, pdf = _evidence(args, db)
                tree = compile_plan(args.page, plan, lines.get(args.page, []), text_layer_words(pdf, args.page), by=args.by)
                if args.out:
                    Path(args.out).mkdir(parents=True, exist_ok=True)
                    (Path(args.out) / f"p{args.page:03d}.json").write_text(_dump(tree), encoding="utf-8")
                print(json.dumps(tree["checked"], ensure_ascii=False))
        elif args.command == "import":
            from app.structure.store import save_page

            if not args.run:
                raise SystemExit("import needs --run")
            count = 0
            for path in sorted(Path(args.pages).glob("p*.json")):
                save_page(db, args.run, json.loads(path.read_text(encoding="utf-8")), producer=args.producer)
                count += 1
            print(f"{count} pages imported")
        elif args.command == "export":
            from app.structure.store import as_tree, current_pages

            if not args.run:
                raise SystemExit("export needs --run")
            out = Path(args.pages)
            out.mkdir(parents=True, exist_ok=True)
            pages = current_pages(db, args.run)
            for number, record in pages.items():
                (out / f"p{number:03d}.json").write_text(_dump(as_tree(record)), encoding="utf-8")
            print(f"{len(pages)} pages exported")
        elif args.command == "export-grammar":
            from app.structure.grammar_export import export_grammar

            if args.run:
                from app.structure.store import as_tree, current_pages, source_pdf

                trees = {n: as_tree(r) for n, r in current_pages(db, args.run).items()}
                pdf = source_pdf(db, args.run)
            elif args.pages and args.pdf:
                trees = {int(p.stem[1:]): json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.pages).glob("p*.json"))}
                pdf = args.pdf
            else:
                raise SystemExit("give --run, or both --pages and --pdf")
            profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
            print(json.dumps(export_grammar(trees, pdf, profile, args.out), ensure_ascii=False))
        elif args.command == "status":
            from app.structure.store import ACCEPTED, current_pages

            if not args.run:
                raise SystemExit("status needs --run")
            pages = current_pages(db, args.run)
            waiting = {n: r.checks for n, r in pages.items() if r.status != ACCEPTED}
            print(json.dumps({"structured_pages": len(pages), "accepted": len(pages) - len(waiting), "waiting": waiting}, ensure_ascii=False))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
