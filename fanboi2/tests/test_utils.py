import unittest
import unittest.mock
from fanboi2.models import redis_conn
from fanboi2.tests import DummyRedis, RegistryMixin
from pyramid import testing


class TestRequestSerializer(unittest.TestCase):

    def _getTargetFunction(self):
        from fanboi2.utils import serialize_request
        return serialize_request

    def test_serialize(self):
        request = testing.DummyRequest()
        request.application_url = 'http://www.example.com/'
        request.referrer = 'http://www.example.com/'
        request.remote_addr = '127.0.0.1'
        request.url = 'http://www.example.com/foobar'
        request.user_agent = 'Mock/1.0'
        self.assertEqual(
            self._getTargetFunction()(request),
            {
                'application_url': 'http://www.example.com/',
                'referrer': 'http://www.example.com/',
                'remote_addr': '127.0.0.1',
                'url': 'http://www.example.com/foobar',
                'user_agent': 'Mock/1.0',
            }
        )

    def test_serialize_dict(self):
        request = {'foo': 1}
        self.assertEqual(self._getTargetFunction()(request), request)


class TestDnsBl(unittest.TestCase):

    def _makeOne(self, providers=None):
        from fanboi2.utils import dnsbl
        if providers is None:
            providers = ['xbl.spamhaus.org']
        dnsbl.configure_providers(providers)
        return dnsbl

    def test_init(self):
        dnsbl = self._makeOne()
        self.assertEqual(dnsbl.providers, ['xbl.spamhaus.org'])

    def test_init_no_providers(self):
        dnsbl = self._makeOne(providers=[])
        self.assertEqual(dnsbl.providers, [])

    def test_init_string_providers(self):
        dnsbl = self._makeOne(providers='xbl.spamhaus.org tor.ahbl.org')
        self.assertEqual(dnsbl.providers, ['xbl.spamhaus.org', 'tor.ahbl.org'])

    @unittest.mock.patch('socket.gethostbyname')
    def test_listed(self, lookup_call):
        lookup_call.return_value = '127.0.0.2'
        dnsbl = self._makeOne()
        self.assertEqual(dnsbl.listed('10.0.100.254'), True)
        lookup_call.assert_called_with('254.100.0.10.xbl.spamhaus.org.')

    @unittest.mock.patch('socket.gethostbyname')
    def test_listed_unlisted(self, lookup_call):
        import socket
        lookup_call.side_effect = socket.gaierror('foobar')
        dnsbl = self._makeOne()
        self.assertEqual(dnsbl.listed('10.0.100.1'), False)
        lookup_call.assert_called_with('1.100.0.10.xbl.spamhaus.org.')

    @unittest.mock.patch('socket.gethostbyname')
    def test_listed_invalid(self, lookup_call):
        lookup_call.return_value = '192.168.1.1'
        dnsbl = self._makeOne()
        self.assertEqual(dnsbl.listed('10.0.100.2'), False)

    @unittest.mock.patch('socket.gethostbyname')
    def test_listed_malformed(self, lookup_call):
        lookup_call.return_value = 'foobarbaz'
        dnsbl = self._makeOne()
        self.assertEqual(dnsbl.listed('10.0.100.2'), False)


class TestAkismet(RegistryMixin, unittest.TestCase):

    def _makeOne(self, key='hogehoge'):
        from fanboi2.utils import akismet
        akismet.configure_key(key)
        return akismet

    def _makeResponse(self, content):
        class MockResponse(object):

            def __init__(self, content):
                self.content = content

        return MockResponse(content)

    def test_init(self):
        akismet = self._makeOne()
        self.assertEqual(akismet.key, 'hogehoge')

    # noinspection PyTypeChecker
    def test_init_no_key(self):
        akismet = self._makeOne(key=None)
        self.assertEqual(akismet.key, None)

    @unittest.mock.patch('requests.post')
    def test_spam(self, api_call):
        api_call.return_value = self._makeResponse(b'true')
        request = self._makeRequest()
        akismet = self._makeOne()
        self.assertEqual(akismet.spam(request, 'buy viagra'), True)
        api_call.assert_called_with(
            'https://hogehoge.rest.akismet.com/1.1/comment-check',
            headers=unittest.mock.ANY,
            data=unittest.mock.ANY,
            timeout=unittest.mock.ANY,
        )

    @unittest.mock.patch('requests.post')
    def test_spam_ham(self, api_call):
        api_call.return_value = self._makeResponse(b'false')
        request = self._makeRequest()
        akismet = self._makeOne()
        self.assertEqual(akismet.spam(request, 'Hogehogehogehoge!'), False)
        api_call.assert_called_with(
            'https://hogehoge.rest.akismet.com/1.1/comment-check',
            headers=unittest.mock.ANY,
            data=unittest.mock.ANY,
            timeout=unittest.mock.ANY,
        )

    @unittest.mock.patch('requests.post')
    def test_spam_timeout(self, api_call):
        import requests
        request = self._makeRequest()
        akismet = self._makeOne()
        api_call.side_effect = requests.Timeout('connection timed out')
        self.assertEqual(akismet.spam(request, 'buy viagra'), False)

    # noinspection PyTypeChecker
    @unittest.mock.patch('requests.post')
    def test_spam_no_key(self, api_call):
        request = self._makeRequest()
        akismet = self._makeOne(key=None)
        self.assertEqual(akismet.spam(request, 'buy viagra'), False)
        assert not api_call.called


class TestRateLimiter(unittest.TestCase):

    def setUp(self):
        redis_conn._redis = DummyRedis()

    def tearDown(self):
        redis_conn._redis = None

    def _getTargetClass(self):
        from fanboi2.utils import RateLimiter
        return RateLimiter

    def _getHash(self, text):
        import hashlib
        return hashlib.md5(text.encode('utf8')).hexdigest()

    def _makeRequest(self):
        request = testing.DummyRequest()
        request.remote_addr = '127.0.0.1'
        request.user_agent = 'TestBrowser/1.0'
        request.referrer = 'http://www.example.com/foo'
        testing.setUp(request=request)
        return request

    def test_init(self):
        request = self._makeRequest()
        ratelimit = self._getTargetClass()(request, namespace='foobar')
        self.assertEqual(ratelimit.key,
                         "rate:foobar:%s" % self._getHash('127.0.0.1'))

    def test_init_no_namespace(self):
        request = self._makeRequest()
        ratelimit = self._getTargetClass()(request)
        self.assertEqual(ratelimit.key,
                         "rate:None:%s" % self._getHash('127.0.0.1'))

    def test_limit(self):
        request = self._makeRequest()
        ratelimit = self._getTargetClass()(request, namespace='foobar')
        self.assertFalse(ratelimit.limited())
        self.assertEqual(ratelimit.timeleft(), 0)
        ratelimit.limit(seconds=30)
        self.assertTrue(ratelimit.limited())
        self.assertEqual(ratelimit.timeleft(), 30)

    def test_limit_no_seconds(self):
        request = self._makeRequest()
        ratelimit = self._getTargetClass()(request, namespace='foobar')
        ratelimit.limit()
        self.assertTrue(ratelimit.limited())
        self.assertEqual(ratelimit.timeleft(), 10)
