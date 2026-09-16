import json
import unittest
from unittest.mock import patch
from namegender import NameGender


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
