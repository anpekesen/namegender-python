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
