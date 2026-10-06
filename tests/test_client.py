import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from namegender import NameGender, NameGenderError


ENVELOPE = {"credits_charged", "credits_remaining", "data_version", "request_id", "country_source"}

SALUTATION_DE = {
    "credits_charged": 1, "credits_remaining": 99, "data_version": "2026.10", "request_id": "req_1",
    "country_source": None, "query": "Dr. Anna Müller", "language": "de", "form": "gendered", "reason": None,
    "salutation": {"formal": "Sehr geehrte Frau Dr. Müller,", "informal": "Liebe Anna,", "neutral": "Guten Tag Dr. Anna Müller,"},
    "parts": {"opening": "Sehr geehrte", "courtesy": "Frau", "academic": "Dr.", "name": "Müller"},
    "gender": "female", "gender_source": "lookup", "probability": 99, "confidence": "high",
    "first_name": "Anna", "last_name": "Müller", "name_type": "personal", "country": "DE",
}

SALUTATION_NEUTRAL = {
    **SALUTATION_DE, "query": "Andrea Rossi", "form": "neutral", "reason": "below_min_probability",
    "salutation": {"formal": "Guten Tag Andrea Rossi,", "informal": "Hallo Andrea,", "neutral": "Guten Tag Andrea Rossi,"},
    "parts": {"opening": "Guten Tag", "courtesy": None, "academic": None, "name": "Andrea Rossi"},
    "gender": "male", "probability": 62, "confidence": "low", "first_name": "Andrea", "last_name": "Rossi", "country": None,
}


class ClientTest(unittest.TestCase):
    @patch("namegender.client.urlopen")
    def test_name(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"gender":"female"}'
        result = NameGender("secret").name("Ayse", country="TR")
        self.assertEqual(result["gender"], "female")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer secret")

    @patch("namegender.client.urlopen")
    def test_bulk_treats_a_string_as_one_name(self, urlopen):
        # list("Ayşe") splits a string into characters; that sent four names
        # and cost four credits.
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"results":[],"summary":{}}'
        client = NameGender("secret")

        client.bulk("Ayşe")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["names"], ["Ayşe"])

        client.bulk(("Ayşe", "Mehmet"))
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["names"], ["Ayşe", "Mehmet"])

    @patch("namegender.client.urlopen")
    def test_countries(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"name":"Mehmet","registrations":[{"country":"FR","share":58.97}],"attested_in":["FR","TR"]}'
        result = NameGender("secret").countries("Mehmet", limit=10)
        self.assertEqual(result["attested_in"], ["FR", "TR"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://namegender.com/api/v1/gender/countries")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        self.assertEqual(json.loads(request.data), {"name": "Mehmet", "limit": 10})

    @patch("namegender.client.urlopen")
    def test_options_use_namegender_names(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"query":"Andrea","gender":"male","sample_size":120,"took_ms":3}'
        result = NameGender("secret").name("Andrea", country="IT", ai_fallback=True, best_guess=True)
        self.assertEqual(result["sample_size"], 120)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://namegender.com/api/v1/gender")
        self.assertEqual(json.loads(request.data), {"name": "Andrea", "country": "IT", "ai_fallback": True, "best_guess": True})

    @patch("namegender.client.urlopen")
    def test_locale_and_ip_are_sent_only_when_given(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"gender":"male","country":"IT","country_source":"locale"}'
        client = NameGender("secret")

        result = client.name("Andrea", locale="it-IT", ip="203.0.113.7")
        self.assertEqual(result["country_source"], "locale")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data),
                         {"name": "Andrea", "locale": "it-IT", "ip": "203.0.113.7"})

        client.email("andrea@example.com", ip="203.0.113.7")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"email": "andrea@example.com", "ip": "203.0.113.7"})

        client.username("andrea92", locale="pt_BR")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"username": "andrea92", "locale": "pt_BR"})

        client.name("Andrea", country="IT")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"name": "Andrea", "country": "IT"})

    @patch("namegender.client.urlopen")
    def test_bulk_sends_locale_and_ip(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"results":[{"name":"Andrea"}],"summary":{},"took_ms":4,"country_source":"ip"}'
        client = NameGender("secret")

        result = client.bulk(["Andrea"], locale="en", ip="203.0.113.7")
        self.assertEqual(result["country_source"], "ip")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data),
                         {"names": ["Andrea"], "type": "name", "locale": "en", "ip": "203.0.113.7"})

        client.bulk(["Andrea"], "IT", "name")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"names": ["Andrea"], "country": "IT", "type": "name"})

    @patch("namegender.client.urlopen")
    def test_error_status_raises(self, urlopen):
        body = b'{"error":"no_credits","message":"Out of credits.","request_id":"req_1","docs":"https://namegender.com/docs"}'
        urlopen.side_effect = HTTPError("https://namegender.com/api/v1/me", 402, "Payment Required", {}, io.BytesIO(body))
        with self.assertRaises(NameGenderError) as caught:
            NameGender("secret").account()
        self.assertEqual(caught.exception.status, 402)
        self.assertEqual(caught.exception.body["error"], "no_credits")

    @patch("namegender.client.urlopen")
    def test_salutation_sends_only_the_options_that_are_set(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps(SALUTATION_DE).encode()
        client = NameGender("secret")

        result = client.salutation("Dr. Anna Müller", language="de", min_probability=80)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://namegender.com/api/v1/salutation")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"name": "Dr. Anna Müller", "language": "de", "min_probability": 80})
        self.assertEqual(result["form"], "gendered")
        self.assertIsNone(result["reason"])
        self.assertEqual(result["salutation"], {
            "formal": "Sehr geehrte Frau Dr. Müller,", "informal": "Liebe Anna,", "neutral": "Guten Tag Dr. Anna Müller,"})
        self.assertEqual(result["parts"]["academic"], "Dr.")
        self.assertEqual(result["credits_charged"], 1)

        client.salutation(first_name="Andrea", last_name="Rossi", language="de", country="IT", locale="de-DE",
                          ip="203.0.113.7", gender="neutral", min_probability=95, title="Dr.")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {
            "first_name": "Andrea", "last_name": "Rossi", "language": "de", "country": "IT", "locale": "de-DE",
            "ip": "203.0.113.7", "gender": "neutral", "min_probability": 95, "title": "Dr."})

    @patch("namegender.client.urlopen")
    def test_salutation_neutral_form_with_reason_and_null_parts(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps(SALUTATION_NEUTRAL).encode()
        result = NameGender("secret").salutation("Andrea Rossi", language="de")
        self.assertEqual(result["form"], "neutral")
        self.assertEqual(result["reason"], "below_min_probability")
        self.assertEqual(result["salutation"]["formal"], "Guten Tag Andrea Rossi,")
        self.assertIsNone(result["parts"]["courtesy"])
        self.assertIsNone(result["parts"]["academic"])

    @patch("namegender.client.urlopen")
    def test_salutation_bulk_keeps_order_and_summary(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        organization = {**SALUTATION_NEUTRAL, "query": "ACME GmbH", "form": "organization", "reason": None,
                        "gender": None, "name_type": "organization",
                        "parts": {"opening": "Sehr geehrte Damen und Herren", "courtesy": None, "academic": None, "name": None}}
        results = [{k: v for k, v in r.items() if k not in ENVELOPE} for r in (SALUTATION_DE, SALUTATION_NEUTRAL, organization)]
        response.read.return_value = json.dumps({
            "credits_charged": 3, "credits_remaining": 96, "data_version": "2026.10", "request_id": "req_2",
            "took_ms": 4, "country_source": None, "language": "de",
            "summary": {"total": 3, "gendered": 1, "neutral": 1, "organization": 1}, "results": results,
        }).encode()
        client = NameGender("secret")

        result = client.salutation_bulk(("Dr. Anna Müller", "Andrea Rossi", "ACME GmbH"), language="de")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://namegender.com/api/v1/salutation/bulk")
        self.assertEqual(json.loads(request.data), {"names": ["Dr. Anna Müller", "Andrea Rossi", "ACME GmbH"], "language": "de"})
        self.assertEqual(result["summary"], {"total": 3, "gendered": 1, "neutral": 1, "organization": 1})
        self.assertEqual([r["query"] for r in result["results"]], ["Dr. Anna Müller", "Andrea Rossi", "ACME GmbH"])
        self.assertEqual([r["form"] for r in result["results"]], ["gendered", "neutral", "organization"])
        self.assertIsNone(result["results"][2]["parts"]["name"])

        client.salutation_bulk("Dr. Anna Müller")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"names": ["Dr. Anna Müller"]})

    @patch("namegender.client.urlopen")
    def test_salutation_unsupported_language_raises(self, urlopen):
        body = json.dumps({"error": "invalid_input", "message": "Unsupported language.", "request_id": "req_7",
                           "field": "language", "supported": ["en", "de", "tr"]}).encode()
        urlopen.side_effect = HTTPError("https://namegender.com/api/v1/salutation", 422, "Unprocessable", {}, io.BytesIO(body))
        with self.assertRaises(NameGenderError) as caught:
            NameGender("secret").salutation("Dr. Anna Müller", language="xx")
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(str(caught.exception), "Unsupported language.")
        self.assertEqual(caught.exception.body["field"], "language")
        self.assertEqual(caught.exception.body["supported"], ["en", "de", "tr"])


class BatchesTest(unittest.TestCase):
    @patch("namegender.client.urlopen")
    def test_create_uploads_multipart_with_idempotency_key(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"id":"B-1","status":"queued"}'
        job = NameGender("secret").batches.create(b"ad\nAy\xc5\x9fe\n", filename="customers.csv",
                                                   name_column="ad", best_guess=True, country=None)
        self.assertEqual(job["id"], "B-1")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://namegender.com/api/v1/batches")
        self.assertTrue(request.headers["Content-type"].startswith("multipart/form-data; boundary="))
        self.assertTrue(request.headers["Idempotency-key"])
        body = request.data.decode()
        self.assertIn('name="name_column"\r\n\r\nad\r\n', body)
        self.assertIn('name="best_guess"\r\n\r\ntrue\r\n', body)
        self.assertIn('name="start"\r\n\r\ntrue\r\n', body)
        self.assertNotIn('name="country"', body)
        self.assertIn('filename="customers.csv"', body)
        self.assertIn("ad\nAyşe\n", body)

    @patch("namegender.client.time.sleep")
    @patch("namegender.client.urlopen")
    def test_create_retries_with_the_same_key_but_not_a_refusal(self, urlopen, sleep):
        ok = urlopen.return_value.__enter__.return_value
        ok.read.return_value = b'{"id":"B-1"}'
        urlopen.side_effect = [HTTPError("u", 503, "x", {}, io.BytesIO(b"{}")), urlopen.return_value]
        NameGender("secret").batches.create(b"x", filename="a.csv", name_column="ad")
        keys = [call.args[0].headers["Idempotency-key"] for call in urlopen.call_args_list]
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])

        urlopen.reset_mock()
        urlopen.side_effect = HTTPError("u", 402, "x", {}, io.BytesIO(b'{"error":"no_credits"}'))
        with self.assertRaises(NameGenderError):
            NameGender("secret").batches.create(b"x", filename="a.csv", name_column="ad")
        self.assertEqual(urlopen.call_count, 1)

    def test_bytes_need_a_filename(self):
        with self.assertRaises(ValueError):
            NameGender("secret").batches.create(b"x")

    @patch("namegender.client.time.sleep")
    @patch("namegender.client.urlopen")
    def test_wait_polls_until_finished(self, urlopen, sleep):
        response = urlopen.return_value.__enter__.return_value
        response.read.side_effect = [
            b'{"id":"B-1","status":"queued","poll_after_seconds":2}',
            b'{"id":"B-1","status":"completed","poll_after_seconds":null}',
        ]
        seen = []
        job = NameGender("secret").batches.wait("B-1", on_progress=lambda j: seen.append(j["status"]))
        self.assertEqual(job["status"], "completed")
        self.assertEqual(seen, ["queued", "completed"])
        sleep.assert_called_once_with(2)

    @patch("namegender.client.urlopen")
    def test_cancel_list_and_download(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.side_effect = [b"", b'{"data":[],"total":0}', b"ad,gender\n"]
        client = NameGender("secret")
        self.assertIsNone(client.batches.cancel("B-1"))
        client.batches.list(limit=5)
        self.assertEqual(client.batches.download("B-1"), b"ad,gender\n")
        calls = [(c.args[0].get_method(), c.args[0].full_url) for c in urlopen.call_args_list]
        self.assertEqual(calls, [
            ("DELETE", "https://namegender.com/api/v1/batches/B-1"),
            ("GET", "https://namegender.com/api/v1/batches?limit=5"),
            ("GET", "https://namegender.com/api/v1/batches/B-1/result"),
        ])


class WebhookTest(unittest.TestCase):
    # Same vector as the server's WebhookDeliveryTest, computed independently.
    SECRET = "whsec_test_vector"
    BODY = b'{"id":"evt_1","type":"webhook.test"}'
    HEADER = "t=1700000000,v1=857fcddfea47617c448b7a8e6537bbd59c9922a37c5273b2709812fbadb29e50"
    NOW = 1700000000

    def test_verifies_the_shared_vector(self):
        from namegender import webhooks
        self.assertEqual(webhooks.verify(self.BODY, self.HEADER, self.SECRET, now=self.NOW + 60)["id"], "evt_1")
        self.assertEqual(webhooks.verify(self.BODY.decode(), self.HEADER, self.SECRET, now=self.NOW)["type"], "webhook.test")
        rotated = "t=1700000000,v1=" + "0" * 64 + ",v1=857fcddfea47617c448b7a8e6537bbd59c9922a37c5273b2709812fbadb29e50"
        webhooks.verify(self.BODY, rotated, self.SECRET, now=self.NOW)

    def test_rejects_tampering_wrong_secret_old_timestamp_and_bad_header(self):
        from namegender import WebhookVerificationError, webhooks
        cases = [
            (self.BODY.replace(b"evt_1", b"evt_2"), self.HEADER, self.SECRET, self.NOW),
            (self.BODY, self.HEADER, "whsec_other", self.NOW),
            (self.BODY, self.HEADER, self.SECRET, self.NOW + 301),
            (self.BODY, None, self.SECRET, self.NOW),
            (self.BODY, "t=abc,v1=", self.SECRET, self.NOW),
        ]
        for payload, header, secret, now in cases:
            with self.assertRaises(WebhookVerificationError):
                webhooks.verify(payload, header, secret, now=now)
        with self.assertRaises(TypeError):
            webhooks.verify({"id": "evt_1"}, self.HEADER, self.SECRET, now=self.NOW)
