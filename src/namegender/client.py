import json
import os
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

_FINISHED = {"completed", "failed", "cancelled"}

# Statuses worth retrying an upload for: the request may never have reached
# the application. Everything else (402, 422, 429 too_many_batches) would
# fail the same way again.
_RETRYABLE = {502, 503, 504}


class NameGenderError(RuntimeError):
    def __init__(self, message, status=0, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class NameGender:
    def __init__(self, api_key, base_url="https://namegender.com/api/v1", timeout=30):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ``options`` are sent as-is: ``ai_fallback=True`` falls back to a language
    # model for names not in the database (needs AI consent on the account),
    # ``best_guess=True`` returns the most likely gender even below the
    # probability threshold. A successful response is any 2xx status; anything
    # else raises NameGenderError.
    #
    # Where the country comes from, in order: ``country`` (ISO code), then the
    # region of ``locale`` (a language tag such as ``"it-IT"`` or ``"pt_BR"``;
    # ``"en"`` alone sets no country), then the country of ``ip`` (the end
    # user's IP address, not stored by the API). Each is sent only when given.
    # The response's ``country_source`` says which one was used: ``"country"``,
    # ``"locale"``, ``"ip"`` or ``None`` (for ``bulk``, on the top level, not per item).

    def name(self, name, country=None, *, locale=None, ip=None, **options):
        return self._post("/gender", self._payload(name=name, country=country, locale=locale, ip=ip, **options))

    def email(self, email, country=None, *, locale=None, ip=None, **options):
        return self._post("/gender/email", self._payload(email=email, country=country, locale=locale, ip=ip, **options))

    def username(self, username, country=None, *, locale=None, ip=None, **options):
        return self._post("/gender/username", self._payload(
            username=username, country=country, locale=locale, ip=ip, **options))

    def bulk(self, names, country=None, type="name", *, locale=None, ip=None, **options):
        # A single string is one name. list("Ayşe") would split it into
        # ["A", "y", "ş", "e"]: four lookups, four credits, no useful answer.
        if isinstance(names, str):
            names = [names]
        return self._post("/gender/bulk", self._payload(
            names=list(names), country=country, type=type, locale=locale, ip=ip, **options))

    def salutation(self, name=None, *, first_name=None, last_name=None, language=None, country=None,
                   locale=None, ip=None, gender=None, min_probability=None, title=None):
        """A ready-to-use letter salutation, e.g. ``"Sehr geehrte Frau Dr. Müller,"``.

        Pass the full name (titles included), or ``first_name`` and
        ``last_name`` when they are stored separately. ``language`` is one of
        en, en-US, en-GB, de, de-AT, de-CH, fr, es, it, pt, pt-PT, pt-BR, nl,
        tr, pl, ja (anything else raises NameGenderError with status 422).
        ``gender`` ("male", "female" or "neutral") overrides the lookup,
        ``min_probability`` (50-100, default 90) is the certainty needed for a
        gendered form and ``title`` is an academic title such as ``"Dr."``.
        When the gender is not certain the neutral form comes back; ``form``
        and ``reason`` say why. ``best_guess`` does not apply. One credit.
        """
        return self._post("/salutation", self._payload(
            name=name, first_name=first_name, last_name=last_name, language=language, country=country,
            locale=locale, ip=ip, gender=gender, min_probability=min_probability, title=title))

    def salutation_bulk(self, names, *, language=None, country=None, locale=None, ip=None, gender=None,
                        min_probability=None, title=None):
        """Salutations for up to 100 names, returned in input order. One credit per name.

        The options, as for :meth:`salutation`, apply to every name.
        """
        if isinstance(names, str):
            names = [names]
        return self._post("/salutation/bulk", self._payload(
            names=list(names), language=language, country=country, locale=locale, ip=ip, gender=gender,
            min_probability=min_probability, title=title))

    def countries(self, name, limit=None):
        """Country distribution of a name. Not a country-of-origin or ethnicity inference.

        ``registrations`` is counted volume, comparable only among countries that publish
        counted birth statistics; ``attested_in`` is presence with no weight attached.
        """
        return self._post("/gender/countries", self._payload(name=name, limit=limit))

    def account(self):
        return self._request("GET", "/me")

    @property
    def batches(self):
        """File jobs: upload a CSV or XLSX file, get it back with gender columns added."""
        return Batches(self)

    @staticmethod
    def _payload(**values):
        return {key: value for key, value in values.items() if value is not None}

    def _post(self, path, body):
        return self._request("POST", path, body)

    def _request(self, method, path, body=None, raw=None, headers=None):
        content = self._send(method, path, body, raw, headers)
        # 204 (a cancelled job) has no body.
        return json.loads(content) if content else None

    def _send(self, method, path, body=None, raw=None, headers=None):
        if raw is not None:
            data, content_type = raw
        else:
            data = json.dumps(body).encode() if body is not None else None
            content_type = "application/json"
        request = Request(self.base_url + path, data=data, method=method, headers={
            "Accept": "application/json", "Content-Type": content_type,
            "Authorization": f"Bearer {self.api_key}",
            **(headers or {}),
        })
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as error:
            try:
                payload = json.loads(error.read())
            except Exception:
                payload = None
            raise NameGenderError((payload or {}).get("message", str(error)), error.code, payload) from error


class Batches:
    """File jobs. Reached as ``client.batches``."""

    def __init__(self, client):
        self._client = client

    def create(self, file, filename=None, start=True, idempotency_key=None, retries=2, **settings):
        """Upload a file and, unless ``start=False``, start it.

        ``file`` is a path, bytes, or a binary file object. The extension of
        the file name (``.csv``, ``.xlsx``) tells the API the format; pass
        ``filename`` when ``file`` is bytes. ``name_column`` is required to
        start: a guessed column that is wrong would spend credits on the
        wrong data. With ``start=False`` the job carries ``inspection``
        (columns, preview, cost) and is started with :meth:`start`.

        One Idempotency-Key is used for every attempt, so a retry after a
        dropped connection returns the first job instead of opening a
        second one and reserving credit twice.
        """
        content, name = _read_file(file, filename)
        fields = {"start": "true" if start else "false"}
        for key, value in settings.items():
            if value is not None:
                fields[key] = ("true" if value else "false") if isinstance(value, bool) else str(value)

        body, content_type = _multipart(fields, "file", name, content)
        headers = {"Idempotency-Key": idempotency_key or str(uuid.uuid4())}

        for attempt in range(retries + 1):
            try:
                return self._client._request("POST", "/batches", raw=(body, content_type), headers=headers)
            except NameGenderError as error:
                if error.status not in _RETRYABLE or attempt >= retries:
                    raise
            except URLError:
                if attempt >= retries:
                    raise
            time.sleep(2 ** attempt)

    def start(self, id, name_column, **settings):
        """Start a job uploaded with ``start=False``."""
        body = self._client._payload(name_column=name_column, **settings)
        return self._client._request("POST", f"/batches/{quote(id, safe='')}/start", body)

    def get(self, id):
        return self._client._request("GET", f"/batches/{quote(id, safe='')}")

    def list(self, limit=None, page=None):
        """Newest first. Includes jobs started from the dashboard."""
        query = urlencode(self._client._payload(limit=limit, page=page))
        return self._client._request("GET", "/batches" + (f"?{query}" if query else ""))

    def cancel(self, id):
        """Cancel a job that has not started (credit is returned), or delete a finished one."""
        self._client._request("DELETE", f"/batches/{quote(id, safe='')}")

    def wait(self, id, timeout=3600, on_progress=None):
        """Poll until the job is completed, failed or cancelled, and return it.

        A failed job is returned, not raised: check ``status`` and ``error["code"]``.
        """
        deadline = time.monotonic() + timeout
        while True:
            job = self.get(id)
            if on_progress:
                on_progress(job)
            if job["status"] in _FINISHED or job["status"] == "uploaded":
                return job
            pause = job.get("poll_after_seconds") or 5
            if time.monotonic() + pause > deadline:
                raise NameGenderError(f"Timed out waiting for {id}", 0, job)
            time.sleep(pause)

    def download(self, id, path=None):
        """The result file as bytes, or written to ``path`` (which is then returned)."""
        content = self._client._send("GET", f"/batches/{quote(id, safe='')}/result")
        if path is None:
            return content
        with open(path, "wb") as handle:
            handle.write(content)
        return path


def _read_file(file, filename):
    if isinstance(file, (bytes, bytearray)):
        if not filename:
            raise ValueError("filename is required when file is bytes")
        return bytes(file), filename
    if isinstance(file, (str, os.PathLike)):
        with open(file, "rb") as handle:
            return handle.read(), filename or os.path.basename(os.fspath(file))
    name = filename or os.path.basename(getattr(file, "name", "") or "")
    if not name:
        raise ValueError("filename is required when the file object has no name")
    return file.read(), name


def _multipart(fields, file_field, filename, content):
    boundary = uuid.uuid4().hex
    lines = []
    for key, value in fields.items():
        lines += [f"--{boundary}", f'Content-Disposition: form-data; name="{key}"', "", value]
    head = "\r\n".join(lines + [
        f"--{boundary}",
        f'Content-Disposition: form-data; name="{file_field}"; filename="{_quote_header(filename)}"',
        "Content-Type: application/octet-stream",
        "", "",
    ]).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + content + tail, f"multipart/form-data; boundary={boundary}"


def _quote_header(value):
    # A quote or line break in a file name would end the header early.
    return value.replace("\\", "\\\\").replace('"', "%22").replace("\r", "").replace("\n", "")
