"""Azure Functions Python v2 HTTP endpoint with process-first-call telemetry."""
import hashlib
import json
import os
import threading
import azure.functions as func
from workload import compute

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
_lock = threading.Lock()
_first = True
_instance = hashlib.sha256((os.environ.get('WEBSITE_INSTANCE_ID', 'local') + str(os.getpid())).encode()).hexdigest()[:12]

@app.route(route='compute', methods=['POST'])
def compute_task(req: func.HttpRequest) -> func.HttpResponse:
    global _first
    try:
        result = compute(req.get_json())
        with _lock:
            first = _first
            _first = False
        result.update(worker_instance=_instance, first_on_process=first)
        return func.HttpResponse(json.dumps(result), mimetype='application/json', status_code=200)
    except (ValueError, TypeError) as exc:
        return func.HttpResponse(json.dumps({'error': str(exc)}), mimetype='application/json', status_code=400)
