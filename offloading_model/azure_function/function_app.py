"""Azure Functions Python v2 HTTP endpoint."""

import json

import azure.functions as func
from workload import compute

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="compute", methods=["POST"])
def compute_task(req: func.HttpRequest) -> func.HttpResponse:
    try:
        result = compute(req.get_json())
        return func.HttpResponse(json.dumps(result), mimetype="application/json", status_code=200)
    except (ValueError, TypeError) as exc:
        return func.HttpResponse(
            json.dumps({"error": str(exc)}), mimetype="application/json", status_code=400
        )
