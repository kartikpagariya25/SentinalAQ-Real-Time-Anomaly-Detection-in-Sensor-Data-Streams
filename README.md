# SentinelAQ — Real-Time Anomaly Detection in Sensor Data Streams
Sponsored project with Respirer Living Sciences.

## Structure
- `backend/` — all data generation, detection models, benchmarking code
- `frontend/` — dashboard/UI
- `Final_plan.md`, `Real-Time-Anomaly-Detection-Implementation-Plan.md` — project planning docs

## Backend quick start
```
cd backend
pip install -r requirements.txt
python generate_sensor_dataset.py --output sensor_data.csv --n_records 1000000 --n_stations 50
python models/benchmark.py --input sensor_data.csv --sample-size 0 --output benchmark_results_v3.csv
uvicorn api.main:create_app --factory --reload --app-dir backend
```

## Frontend quick start
```
cd frontend
npm install
npm run dev
```
Open http://localhost:5173 (requires the backend running — see above).
