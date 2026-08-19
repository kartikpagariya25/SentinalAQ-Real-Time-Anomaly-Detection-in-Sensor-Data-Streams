import pandas as pd
from fastapi import APIRouter, Request

router = APIRouter()

WINNER = "lof"
WHY = (
    "Isolation Forest has the best raw F1 (0.43) but flags 86-94% of real "
    "environmental events as sensor faults. STL residual is better but still "
    "fails that bar (43-49%). LOF is the only one of the three that clears it "
    "(6-7% env-event false-positive rate) - the deliberate trade is accepting "
    "LOF's lower raw recall in exchange for not crying \"fault\" on genuine "
    "air-quality events. See Final_plan.md Section 8."
)


@router.get("/api/benchmark")
def get_benchmark(request: Request):
    path = request.app.state.benchmark_csv_path
    df = pd.read_csv(path)
    df = df.rename(columns={df.columns[0]: "method"})
    # NaN is not valid JSON; convert to None -> null. astype(object) first, otherwise
    # pandas coerces None back to NaN on numeric (float64) columns.
    df = df.astype(object).where(pd.notna(df), None)
    table = df.to_dict(orient="records")
    return {"table": table, "winner": WINNER, "why": WHY}
