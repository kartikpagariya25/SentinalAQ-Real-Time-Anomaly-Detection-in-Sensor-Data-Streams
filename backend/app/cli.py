import warnings

warnings.filterwarnings("ignore")
import argparse

from . import ui


def main():
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("profile")
    g = sub.add_parser("generate")
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--fault-scale", type=float, default=1.0)
    cp = sub.add_parser("compare")
    cp.add_argument("--resume", action="store_true")
    sub.add_parser("learning-curve")
    p = sub.add_parser("peek")
    for k in ("city", "device", "start", "end", "fault", "export"):
        p.add_argument(f"--{k}", default=None)
    p.add_argument("--rows", type=int, default=25)
    p.add_argument("--faults-only", action="store_true")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8000)
    im = sub.add_parser("ingest-sim")
    im.add_argument("--start", default="2026-11-07")
    im.add_argument("--days", type=int, default=2)
    im.add_argument("--cities", default="Delhi,Pune")
    im.add_argument("--db", default=None)
    sub.add_parser("train")
    e = sub.add_parser("evaluate")
    e.add_argument("--skip-unseen-cities", action="store_true")
    s = sub.add_parser("stream")
    s.add_argument("--start", default="2026-11-07")
    s.add_argument("--days", type=int, default=3)
    s.add_argument("--cities", default="Delhi,Pune")
    s.add_argument("--delay", type=float, default=0.4)
    s.add_argument("--seed", type=int, default=2026)
    s.add_argument("--only-flagged", action="store_true")
    s.add_argument("--out", default=None)
    sub.add_parser("all")
    a = ap.parse_args()

    from . import pipeline
    if a.cmd == "profile":
        pipeline.cmd_profile()
    elif a.cmd == "generate":
        pipeline.cmd_generate(a.seed, a.fault_scale)
    elif a.cmd == "compare":
        pipeline.cmd_compare(resume=a.resume)
    elif a.cmd == "learning-curve":
        from .compare import learning_curve
        learning_curve()
    elif a.cmd == "peek":
        from .explore import peek
        peek(a)
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("app.api:app", host="127.0.0.1", port=a.port)
    elif a.cmd == "ingest-sim":
        from .stream import run_ingest_sim
        run_ingest_sim(a)
    elif a.cmd == "train":
        pipeline.cmd_train()
    elif a.cmd == "evaluate":
        from .evaluate import evaluate
        evaluate(a.skip_unseen_cities)
    elif a.cmd == "stream":
        from .stream import run_cli
        run_cli(a)
    elif a.cmd == "all":
        from .evaluate import evaluate
        pipeline.cmd_profile()
        pipeline.cmd_generate()
        pipeline.cmd_train()
        evaluate()


if __name__ == "__main__":
    main()
