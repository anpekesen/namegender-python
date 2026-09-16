import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


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

    def name(self, name, country=None, **options):
        return self._post("/gender", self._payload(name=name, country=country, **options))

    def email(self, email, country=None, **options):
        return self._post("/gender/email", self._payload(email=email, country=country, **options))

    def username(self, username, country=None, **options):
        return self._post("/gender/username", self._payload(username=username, country=country, **options))

    def bulk(self, names, country=None, type="name", **options):
        # A single string is one name. list("Ayşe") would split it into
        # ["A", "y", "ş", "e"]: four lookups, four credits, no useful answer.
        if isinstance(names, str):
            names = [names]
        return self._post("/gender/bulk", self._payload(names=list(names), country=country, type=type, **options))

    def countries(self, name, limit=None):
        """Country distribution of a name. Not a country-of-origin or ethnicity inference.

        ``registrations`` is counted volume, comparable only among countries that publish
        counted birth statistics; ``attested_in`` is presence with no weight attached.
        """
        return self._post("/gender/countries", self._payload(name=name, limit=limit))

    def account(self):
        return self._request("GET", "/me")

    @staticmethod
    def _payload(**values):
        return {key: value for key, value in values.items() if value is not None}

    def _post(self, path, body):
        return self._request("POST", path, body)

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base_url + path, data=data, method=method, headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        })
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except HTTPError as error:
            try:
                payload = json.loads(error.read())
            except Exception:
                payload = None
            raise NameGenderError((payload or {}).get("message", str(error)), error.code, payload) from error
