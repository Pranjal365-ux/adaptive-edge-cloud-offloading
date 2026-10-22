# Adaptive Task Offloading in Edge–Cloud Computing

A reproducible fifth semester project prototype based on the supplied synopsis. It compares edge-only, cloud-only, fixed-threshold and adaptive policies on identical simulated task streams.

## Requirements

- Python 3.10 or newer on Windows, macOS or Linux.
- No cloud account, API key, physical edge device, Java toolkit or paid service is needed for the core simulation.
- Optional charts: `python -m pip install matplotlib`.
- Optional interactive dashboard: `python -m pip install streamlit pandas`, then `streamlit run dashboard.py`.
- About 100 MB of free disk space is ample for ordinary runs. The default experiment has 100 runs and 30,000 task records.

## Run

From this folder:

```bash
python offloading.py --tasks 300 --seeds 5 --output results
python -m unittest -v
python plot_results.py results
```

The last command requires matplotlib. `dashboard.py` can run and inspect the same experiment interactively. A run writes `summary.csv` (one row per scenario/policy/seed), `tasks.csv` (individual decisions and outcomes), and `experiment.json` (all settings and threshold selection). Keep these files when preparing the paper.

## Experimental design

The model has two edge CPU workers, four cloud CPU workers, one FIFO uplink, and one FIFO downlink. Arrivals are exponentially spaced. Tasks have distinct computational work (million instructions) and input/output size (decimal MB). Execution time is work divided by processing rate. Transmission time is `8 × size_MB / bandwidth_Mbps`. One-way latency is added after upload and after download. For each final seed and scenario, all four policies receive precisely the same generated task trace.

Five scenarios test light/heavy traffic, good/poor network, and a network alternating every 30 simulated seconds. Bandwidth is sampled when a transfer starts and remains fixed during that transfer. All numerical values are **synthetic assumptions**, not measurements from a physical deployment. Edit the `SCENARIOS` list and task generator in `offloading.py` to reflect justified parameters from your literature or measured data.

The threshold policy offloads when `work_mi > K`. Candidate K values are the 25th, 50th and 75th percentiles of work in a separate development trace. It selects the candidate with the lowest mean completion time across development seeds 1001–1005. The selected K is frozen for final seeds 2001 onward and all five final scenarios. This is a *globally fixed* baseline, so it cannot react to momentary network conditions.

The adaptive policy estimates edge and cloud completion time using current resource backlog, task work, transfer size and current network conditions. It sends a task to cloud if predicted cloud time plus `100 seconds/USD × estimated cloud cost` is less than predicted edge time. This coefficient is an explicit modelling choice; a sensitivity experiment should vary it if cost is central to the final claim. The cloud price is a synthetic $0.0001 per compute second and charges only CPU service, not actual provider billing, storage or data egress.

Reported per-run metrics are mean and p95 task completion time, throughput, edge CPU utilization, transferred MB, estimated cloud charge and cloud-task fraction. The bar charts average **per-run metrics** across seeds; for the formal paper, report variability as well (for example, standard deviation or a confidence interval) and include units on every table/axis.

## Scope and limitations

The core model is a simulation. The separate live benchmark below runs identical SHA-256 tasks locally and on Azure; it does not validate the synthetic network and cost parameters. The simulator does not implement RAM limits, energy consumption, failures, security, node mobility, actual cloud invoices, or retransmission. Separate upload and download queues are a simplified network. The adaptive policy's backlog prediction is approximate; its predicted times are not the same as actual completion times. Task size and CPU work are generated independently within two classes. Describe these choices in the report, and confine claims to tested scenarios.

## Suggested next research steps

1. Have the guide approve the experimental question, units, task generator and synthetic parameter ranges.
2. Add a real trace or measured network conditions if available; retain the synthetic baseline for repeatability.
3. Run more seeds, plot variability and compare per-task outcomes under changing conditions.
4. Add an ablation: remove network awareness or cost from the adaptive decision to learn which factor matters.
5. Explain failures as carefully as successes. Use actual generated CSV values in the Results section, never placeholder numbers.

## Real cloud stage using Azure Functions and Terraform

The `azure_function/` code and `terraform/main.tf` are a deployment starter. The same SHA-256 task runs on the laptop and in an Azure Function. `live_probe.py` sends an HTTPS POST with a function key, verifies identical output, and records edge compute time, cloud compute time, and total cloud round trip. The difference between cloud round trip and cloud compute time includes network transfer, service overhead and possibly a cold start; it is not a pure network latency measure.

Requirements: an Azure subscription that permits Resource Group, Storage Account and Linux Consumption Function App creation; Terraform CLI; Azure CLI for sign-in; and Python 3.10+ locally. The function package uses a Python 3.12 runtime and Azure Functions Python v2. Central India is the default region; if your subscription does not offer this plan there, pass another supported region. Storage and function usage can incur charges. Review your subscription's available credit and pricing before applying. Terraform state contains resource details and storage credentials; keep it private and do not upload it to a public repository.

In PowerShell on Windows, from the extracted project folder:

```powershell
az login
az account list --output table
az account set --subscription YOUR_SUBSCRIPTION_ID
cd terraform
terraform init
terraform plan -var="subscription_id=YOUR_SUBSCRIPTION_ID"
terraform apply -var="subscription_id=YOUR_SUBSCRIPTION_ID"
terraform output -raw function_url
terraform output -raw function_app_name
terraform output -raw resource_group_name
cd ..
$env:AZURE_FUNCTION_KEY = Read-Host "Paste the compute_task function key"
python live_probe.py --url "YOUR_OUTPUT_FUNCTION_URL"
python live_experiment.py --url "YOUR_OUTPUT_FUNCTION_URL" --tasks 20 --seeds 3 --output live_results
Remove-Item Env:AZURE_FUNCTION_KEY
```

Review the plan before applying. In the Azure portal, open the Function App shown in the output, then **Functions → compute_task → Function Keys** and copy its default key. Paste it into the PowerShell prompt; do not share it or save it in source code. It may take a short time after the first deployment for the function to be indexed. When finished, from the `terraform` folder run `terraform destroy -var="subscription_id=YOUR_SUBSCRIPTION_ID"` and review the destruction plan. Keep the same state file until cleanup is complete.

On macOS/Linux, use `export AZURE_FUNCTION_KEY=...` and `unset AZURE_FUNCTION_KEY`. The deployment has not been run against a live subscription in this package. If the zip deployment fails because of a regional or platform restriction, keep the Terraform error and inspect the Function App deployment logs before rerunning; do not interpret an infrastructure apply alone as a successful code deployment.

`live_experiment.py` runs all four policies with the same task trace for each final seed. Eight separate calibration calls measure local and remote CPU rates and Azure round trip overhead. The fixed threshold is selected by predicted mean latency on the four development work classes, then frozen; final task outcomes do not train it. The adaptive policy predicts edge and cloud completion using calibration and the current number of unfinished tasks per worker pool. Arrivals follow a seeded exponential schedule, and policy order is shuffled per seed. Each run records per-task response time and a policy summary. The default 20 tasks × 3 seeds makes **up to 180** remote final calls plus 8 calibration calls and 9 optional pilot calls; actual number depends on offloading decisions. Increase seeds and test network conditions deliberately for a serious report.

The live benchmark records actual client-observed latency and throughput. `transferred_input_bytes` counts payload input sent to Azure, not total network traffic. It does not record Azure billing, energy, true server queue lengths, or a pure network latency measure. Local and cloud worker counts are explicit experiment settings, not an assertion of equal hardware. CPU, service load, cold starts and internet conditions can change between policy runs; report these as limitations and do not claim statistical significance from three seeds. `live_results/protocol.json`, `summary.csv` and `tasks.csv` contain no function key. Keep the simulator results and the live results in separate paper tables.
