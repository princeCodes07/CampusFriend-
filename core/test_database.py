from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.database import database_config


class DatabaseConfigurationTests(SimpleTestCase):
    def test_local_fallback(self):
        self.assertEqual(database_config(Path('/local'), {}), {
            'ENGINE': 'django.db.backends.sqlite3', 'NAME': Path('/local/db.sqlite3'),
        })

    def test_render_requires_database_url(self):
        with self.assertRaises(ImproperlyConfigured):
            database_config(Path('/local'), {'RENDER': 'true', 'DATABASE_URL': ' '})

    def test_postgres_url_decoding_tls_and_connections(self):
        config = database_config(Path('/local'), {
            'DATABASE_URL': 'postgresql://test:p%40ss%2Fword@db.example.test:5432/campus?sslmode=verify-full',
            'DB_CONN_MAX_AGE': '0',
        })
        self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(config['PASSWORD'], 'p@ss/word')
        self.assertEqual(config['OPTIONS'], {'sslmode': 'verify-full', 'connect_timeout': 10})
        self.assertEqual(config['CONN_MAX_AGE'], 0)
        self.assertTrue(config['CONN_HEALTH_CHECKS'])

    def test_default_tls_and_no_credentials_in_errors(self):
        config = database_config(Path('/local'), {'DATABASE_URL': 'postgres://test:example@db.test/campus'})
        self.assertEqual(config['OPTIONS']['sslmode'], 'require')
        for url in [
            'mysql://test:private-value@db.test/campus',
            'sqlite:///file', 'postgres://test:private-value@db.test',
            'postgres://test:private-value@db.test:bad/campus',
            'postgres://test:private-value@db.test/campus?sslmode=disable',
            'postgres://test:private-value@db.test/campus?host=elsewhere',
            'postgres://test:private-value@db.test/campus?sslmode=require&sslmode=disable',
            'postgres://test:private-value@db.test/campus?connect_timeout=0',
            'postgres://test:private-value@db.test/campus#fragment',
        ]:
            with self.subTest(url_type=url.split(':')[0]):
                with self.assertRaises(ImproperlyConfigured) as caught:
                    database_config(Path('/local'), {'DATABASE_URL': url})
                self.assertNotIn('private-value', str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_invalid_connection_age(self):
        for age in ['-1', 'bad', '601']:
            with self.assertRaises(ImproperlyConfigured):
                database_config(Path('/local'), {'DATABASE_URL': 'postgres://test:example@db.test/campus', 'DB_CONN_MAX_AGE': age})
