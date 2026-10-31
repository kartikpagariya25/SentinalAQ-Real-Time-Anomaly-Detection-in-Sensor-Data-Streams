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
    sv.add_argument("--email-period", default=None, help="daily/weekly: start scheduled email reports")
    sv.add_argument("--email-hour", type=int, default=6)
    lf = sub.add_parser("live-feed")
    lf.add_argument("--url", default="http://127.0.0.1:8000")
    lf.add_argument("--api-key", default=None)
    lf.add_argument("--replay-days", type=int, default=1100, help="days of dataset history to stream continuously (0 = off)")
    lf.add_argument("--cities", default="Delhi,Pune")
    lf.add_argument("--delay", type=float, default=1.0)
    lf.add_argument("--seed", type=int, default=2026)
    lf.add_argument("--loop", action="store_true", help="keep feeding forever (continuous demo)")
    er = sub.add_parser("email-report")
    er.add_argument("--period", default="daily")
    er.add_argument("--date", default=None)
    er.add_argument("--to", default=None)
    im = sub.add_parser("ingest-sim")
    im.add_argument("--start", default="2026-09-28")
    im.add_argument("--days", type=int, default=2)
    im.add_argument("--cities", default="Delhi,Pune")
    im.add_argument("--db", default=None)
    sub.add_parser("train")
    md = sub.add_parser("models")
    md.add_argument("--info", action="store_true", help="also show a short description of each model")
    e = sub.add_parser("evaluate")
    e.add_argument("--skip-unseen-cities", action="store_true")
    s = sub.add_parser("stream")
    s.add_argument("--start", default="2026-09-28")
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
        if a.email_period:
            from .mailer import start_scheduler
            start_scheduler(a.email_period, a.email_hour)
        uvicorn.run("app.api:app", host="127.0.0.1", port=a.port)
    elif a.cmd == "live-feed":
        from .live import run_live_feed
        run_live_feed(a)
    elif a.cmd == "email-report":
        from .mailer import send_report
        to = [x.strip() for x in a.to.split(",")] if a.to else None
        try:
            ui.ok(str(send_report(a.period, a.date, to)))
        except Exception as e:
            ui.warn(str(e))
    elif a.cmd == "ingest-sim":
        from .stream import run_ingest_sim
        run_ingest_sim(a)
    elif a.cmd == "train":
        pipeline.cmd_train()
    elif a.cmd == "models":
        pipeline.cmd_models(a.info)
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
