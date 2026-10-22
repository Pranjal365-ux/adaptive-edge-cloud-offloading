# Application Insights and Log Analytics queries

The queries below use standard Application Insights tables. Set the time range in the Azure portal before running them. The application does not attach task payloads or API keys to telemetry.

## Request volume, failures, and p95

```kusto
requests
| summarize Requests=count(), Failed=countif(success == false),
            P95DurationMs=percentile(duration, 95)
  by bin(timestamp, 5m), cloud_RoleName
| order by timestamp asc
```

## Slowest gateway and worker operations

```kusto
requests
| where success == true
| summarize P50Ms=percentile(duration, 50), P95Ms=percentile(duration, 95),
            Count=count()
  by operation_Name, cloud_RoleName
| order by P95Ms desc
```

## Exceptions by service

```kusto
exceptions
| summarize Count=count() by type, outerMessage, cloud_RoleName
| order by Count desc
```

## Correlated trace events

```kusto
traces
| where isnotempty(operation_Id)
| project timestamp, severityLevel, cloud_RoleName, operation_Id, message
| order by timestamp desc
```

Use `docs/AUDIT.md` for the difference between app-level latency, simulator completion time, and billed Azure cost. Application Insights sampling can affect trace counts; Prometheus histograms remain the demo's main local metric source.
