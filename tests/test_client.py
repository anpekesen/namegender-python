import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from namegender import NameGender, NameGenderError


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
    def test_error_status_raises(self, urlopen):
        body = b'{"error":"no_credits","message":"Out of credits.","request_id":"req_1","docs":"https://namegender.com/docs"}'
        urlopen.side_effect = HTTPError("https://namegender.com/api/v1/me", 402, "Payment Required", {}, io.BytesIO(body))
        with self.assertRaises(NameGenderError) as caught:
            NameGender("secret").account()
        self.assertEqual(caught.exception.status, 402)
        self.assertEqual(caught.exception.body["error"], "no_credits")


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
