# test_suite.py
"""Comprehensive test suite for the FreeNumber backend API (Numbers Management & Push Notifications)"""
import unittest
import json
import time
from main import app, ADMIN_PASSWORD
from shared_storage import shared_storage

class FreeNumberApiTests(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_root_and_health(self):
        res = self.app.get('/')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('service'), 'FreeNumber API')

        res_h = self.app.get('/health')
        self.assertEqual(res_h.status_code, 200)
        data_h = res_h.get_json()
        self.assertEqual(data_h.get('status'), 'ok')
        self.assertIn('numbers', data_h)
        self.assertIn('push_subscribers', data_h)

    def test_admin_ui_route(self):
        res = self.app.get('/admin')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'FreeNumber Admin', res.data)
        self.assertIn(b'Admin Security Access', res.data)

    def test_admin_security_verify(self):
        # Invalid password
        res = self.app.post('/api/admin/verify', json={'password': 'wrong_passcode'})
        self.assertEqual(res.status_code, 401)

        # Valid password in body
        res = self.app.post('/api/admin/verify', json={'password': ADMIN_PASSWORD})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get('success'))

        # Valid password in X-Admin-Key header
        res = self.app.post('/api/admin/verify', headers={'X-Admin-Key': ADMIN_PASSWORD})
        self.assertEqual(res.status_code, 200)

    def test_numbers_endpoint_schema(self):
        res = self.app.get('/api/numbers')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        numbers = data.get('numbers', [])
        self.assertGreater(len(numbers), 0)

        first = numbers[0]
        required_keys = ['id', 'number', 'countryCode', 'country', 'flag', 'status', 'supported_apps', 'blocked_apps']
        for k in required_keys:
            self.assertIn(k, first, f"Missing key in /api/numbers: {k}")

        self.assertIsInstance(first['supported_apps'], list)
        self.assertIsInstance(first['blocked_apps'], list)

    def test_apps_endpoint(self):
        res = self.app.get('/api/apps')
        self.assertEqual(res.status_code, 200)
        apps = res.get_json()
        self.assertIsInstance(apps, list)
        self.assertGreater(len(apps), 0)

        wa = next((a for a in apps if a['id'] == 'whatsapp'), None)
        self.assertIsNotNone(wa)
        self.assertIn('name', wa)
        self.assertIn('icon_slug', wa)
        self.assertIn('available_countries_count', wa)
        self.assertIn('status', wa)

    def test_compatibility_stubs(self):
        # /api/numbers/{number}/messages should return safe empty list without error
        res_msg = self.app.get('/api/numbers/79775594420/messages')
        self.assertEqual(res_msg.status_code, 200)
        msg_data = res_msg.get_json()
        self.assertEqual(msg_data.get('total_messages'), 0)
        self.assertEqual(msg_data.get('messages'), [])

        # /api/otps stub
        res_otps = self.app.get('/api/otps')
        self.assertEqual(res_otps.status_code, 200)
        self.assertEqual(res_otps.get_json().get('total'), 0)

    def test_admin_add_and_edit_number(self):
        headers = {'X-Admin-Key': ADMIN_PASSWORD}
        # Add new number
        payload = {
            'country': 'Germany',
            'countryCode': '+49',
            'flag': '🇩🇪',
            'numbers': ['4915123456789'],
            'status': 'active',
            'supported_apps': ['whatsapp', 'uber', 'telegram'],
            'blocked_apps': ['paypal']
        }
        res = self.app.post('/api/admin/numbers', headers=headers, json=payload)
        self.assertEqual(res.status_code, 200)
        
        # Verify it appears in /api/numbers
        res_list = self.app.get('/api/numbers?country=%2B49')
        data = res_list.get_json()
        self.assertGreaterEqual(data.get('total'), 1)
        added_num = next((n for n in data['numbers'] if n['number'] == '4915123456789'), None)
        self.assertIsNotNone(added_num)
        self.assertIn('uber', added_num['supported_apps'])

        # Update number status to inactive
        res_put = self.app.put(f'/api/admin/numbers/{added_num["id"]}', headers=headers, json={
            'status': 'inactive',
            'supported_apps': ['telegram']
        })
        self.assertEqual(res_put.status_code, 200)

        # Delete number
        res_del = self.app.delete(f'/api/admin/numbers/{added_num["id"]}', headers=headers)
        self.assertEqual(res_del.status_code, 200)

    def test_notifications_subscribe_and_send(self):
        # Subscribe
        sub_payload = {
            'fcm_token': 'sample_device_fcm_token_123',
            'number': '79775594420'
        }
        res_sub = self.app.post('/api/notifications/subscribe', json=sub_payload)
        self.assertEqual(res_sub.status_code, 200)
        self.assertTrue(res_sub.get_json().get('success'))

        # Admin broadcast
        headers = {'X-Admin-Key': ADMIN_PASSWORD}
        notify_payload = {
            'title': 'Test Push Notification',
            'body': 'New numbers added!',
            'number': '79775594420',
            'app_id': 'whatsapp'
        }
        res_send = self.app.post('/api/admin/notifications/send', headers=headers, json=notify_payload)
        self.assertEqual(res_send.status_code, 200)
        self.assertTrue(res_send.get_json().get('success'))

    def test_banners_system(self):
        headers = {'X-Admin-Key': ADMIN_PASSWORD}

        # 1. Add single banner
        res_add = self.app.post('/api/admin/banners', headers=headers, json={
            'text': 'Venezuela working for WhatsApp 🚀',
            'active': True
        })
        self.assertEqual(res_add.status_code, 200)
        add_data = res_add.get_json()
        self.assertTrue(add_data.get('success'))

        # 2. Public GET /api/banners
        res_pub = self.app.get('/api/banners')
        self.assertEqual(res_pub.status_code, 200)
        pub_data = res_pub.get_json()
        self.assertTrue(pub_data.get('success'))
        self.assertIn('Venezuela working for WhatsApp 🚀', pub_data.get('banners', []))
        self.assertIsInstance(pub_data.get('items'), list)

        # 3. Save multi-line banners
        res_bulk = self.app.post('/api/admin/banners/save-all', headers=headers, json={
            'lines': [
                'Venezuela working for WhatsApp 🚀',
                'USA & Russia numbers refreshed',
                'Telegram OTPs 100% active'
            ]
        })
        self.assertEqual(res_bulk.status_code, 200)
        bulk_data = res_bulk.get_json()
        self.assertEqual(len(bulk_data.get('banners', [])), 3)

        # Verify public endpoint returns all 3 lines
        res_pub2 = self.app.get('/api/banners')
        pub_data2 = res_pub2.get_json()
        self.assertEqual(len(pub_data2.get('banners', [])), 3)
        self.assertEqual(pub_data2['banners'][0], 'Venezuela working for WhatsApp 🚀')

        # 4. Update banner
        ban_id = bulk_data['banners'][0]['id']
        res_upd = self.app.put(f'/api/admin/banners/{ban_id}', headers=headers, json={
            'active': False
        })
        self.assertEqual(res_upd.status_code, 200)

        # Inactive banner should not appear in public /api/banners
        res_pub3 = self.app.get('/api/banners')
        self.assertEqual(len(res_pub3.get_json().get('banners', [])), 2)

        # 5. Delete banner
        res_del = self.app.delete(f'/api/admin/banners/{ban_id}', headers=headers)
        self.assertEqual(res_del.status_code, 200)

    def test_upload_numbers_txt(self):
        import io
        headers = {'X-Admin-Key': ADMIN_PASSWORD}
        txt_content = "584120000001\n584120000002\n584120000003"
        data = {
            'country': 'Venezuela',
            'countryCode': '+58',
            'flag': '🇻🇪',
            'file': (io.BytesIO(txt_content.encode('utf-8')), 'numbers.txt')
        }
        res = self.app.post('/api/admin/numbers/upload', headers=headers, data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get('success'))

        # Verify added
        res_check = self.app.get('/api/numbers?country=Venezuela')
        self.assertGreaterEqual(res_check.get_json().get('total', 0), 3)

if __name__ == '__main__':
    unittest.main()
