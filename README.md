# NameGender Python

```sh
pip install namegender-client
```

```python
from namegender import NameGender
client = NameGender("YOUR_API_KEY")
result = client.name("Ayşe", country="TR")
print(result["gender"], result["probability"], result["sample_size"], result["confidence"])
```

## Options and response

`name`, `email`, `username` and `bulk` accept `country`, `ai_fallback` and
`best_guess` as keyword arguments:

```python
result = client.name("Andrea", country="IT", best_guess=True)
```

A result carries `query`, `name`, `first_name`, `middle_name`, `last_name`, `name_type`, `gender`, `country`, `probability`,
`sample_size`, `took_ms`, `source`, `confidence` and `matched_as`, alongside
`credits_charged`, `credits_remaining`, `data_version` and `request_id`.
Success is the HTTP status: any non-2xx response raises `NameGenderError`
with `status` and `body` (`{"error", "message", "request_id", "docs"}`).
Branch on `body["error"]`, not on the message.

## Country distribution

Returns the countries a name is recorded in. This is not a country-of-origin or
ethnicity inference, and must not be used as one.

```python
result = client.countries("Mehmet", limit=10)
print(result["registrations"])  # [{"country": "FR", "count": 3775, "share": 58.97, "gender": "male", "probability": 99, "source": "insee"}, ...]
print(result["attested_in"])    # ["AL", "AU", "BE", ..., "TR", "US"]
print(result["basis"]["note"])
```

The two lists are deliberately kept apart. `registrations` is measured volume and
is comparable only among the seven countries that publish counted birth
statistics (US, UK, France, Canada, Spain, Ireland, Norway); `share` is a
percentage across those counts alone. `attested_in` is presence with no weight
attached, which is where countries that publish no counts, such as Turkey, Japan
and India, appear. Show `basis["note"]` next to any percentage you display.

`limit` (1–100, default 25) caps how many counted countries come back in
`registrations`. One credit per request.

## File jobs

Upload a CSV or XLSX file (up to 100 MB and 1,000,000 rows) and get it back
with gender columns added. One credit per row, charged only if the job
completes.

```python
job = client.batches.create(
    "customers.csv",             # a path, bytes (with filename=) or a binary file object
    name_column="first_name",    # required to start
    country_column="country",    # optional: a country code per row
)

done = client.batches.wait(job["id"], on_progress=lambda j: print(j["progress"]))
if done["status"] == "failed":
    raise RuntimeError(done["error"]["code"])

client.batches.download(done["id"], "customers-gender.csv")
```

`name_column` is required to start: a guessed column that turns out to be
wrong would spend credits on the wrong data. To see the columns and the cost
first, upload with `start=False`, read `job["inspection"]`, then call
`client.batches.start(job["id"], name_column=...)`.

`create` sends an `Idempotency-Key` and retries network errors and 502/503/504
with the same key, so a retry never opens a second job. Pass your own
`idempotency_key` to keep that guarantee across your own retries.

`wait` returns a failed job rather than raising; branch on
`job["error"]["code"]`. `cancel` returns the credit of a job that has not
started, and deletes a finished one. `list(limit=, page=)` includes jobs
started from the dashboard. Up to three jobs can be queued or running at once;
a fourth is refused with `429 too_many_batches`.

The result appends `gender`, `probability`, `sample_size`, `country`, `source`,
`matched_as`, `first_name`, `middle_name`, `last_name` and `name_type` to every
row. A CSV result starts with a UTF-8 byte order mark; read it with
`encoding="utf-8-sig"`.

## Webhooks

Add an endpoint under Webhooks in the dashboard, and NameGender sends a signed
`POST` to it when a file job completes or fails. `webhooks.verify` checks the
signature and the timestamp, and returns the event.

```python
import os
from flask import Flask, request
from namegender import webhooks, WebhookVerificationError

app = Flask(__name__)

@app.post("/namegender")
def namegender_webhook():
    try:
        event = webhooks.verify(
            request.get_data(),   # the raw bytes, not request.json
            request.headers.get("NameGender-Signature"),
            os.environ["NAMEGENDER_WEBHOOK_SECRET"],
        )
    except WebhookVerificationError:
        return "", 400

    if event["type"] == "batch.completed":
        job = event["data"]["object"]   # the job, as batches.get() returns it
        ...
    return "", 204
```

Answer quickly and do slow work afterwards. Anything other than a 2xx within 10
seconds is retried, up to 8 attempts over about 45 hours. Use `event["id"]`
(also the `NameGender-Event-Id` header) to ignore a delivery you have already
handled: a retry carries the same id, and order is not guaranteed.
