"""Tests for the notification bell's API + dropdown markup.

Before this, the bell showed an unread-count badge but clicking it did
nothing - there was no UI to actually read a notification, even though the
underlying API (user_notifications / mark_notification_read) already worked.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import Notification


class NotificationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='notifme', password='pw')
        self.client.force_login(self.user)

    def test_lists_notifications_newest_first_with_unread_count(self):
        Notification.objects.create(user=self.user, notification_type='system', title='First', message='m1')
        Notification.objects.create(user=self.user, notification_type='system', title='Second', message='m2', is_read=True)

        response = self.client.get(reverse('notebooks:notifications'))
        data = response.json()
        self.assertEqual(data['unread_count'], 1)
        self.assertEqual(data['notifications'][0]['title'], 'Second')  # newest first
        self.assertEqual(data['notifications'][1]['title'], 'First')

    def test_does_not_include_another_users_notifications(self):
        other = User.objects.create_user(username='someone_else', password='pw')
        Notification.objects.create(user=other, notification_type='system', title='Not yours', message='m')

        response = self.client.get(reverse('notebooks:notifications'))
        data = response.json()
        self.assertEqual(data['unread_count'], 0)
        self.assertEqual(data['notifications'], [])

    def test_mark_read_updates_the_notification(self):
        notif = Notification.objects.create(user=self.user, notification_type='system', title='X', message='m')
        response = self.client.post(reverse('notebooks:read_notification', args=[notif.pk]))
        self.assertEqual(response.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_cannot_mark_another_users_notification_read(self):
        other = User.objects.create_user(username='not_mine', password='pw')
        notif = Notification.objects.create(user=other, notification_type='system', title='X', message='m')
        response = self.client.post(reverse('notebooks:read_notification', args=[notif.pk]))
        self.assertEqual(response.status_code, 404)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)


class NotificationDropdownMarkupTests(TestCase):
    def test_dropdown_markup_present_for_authenticated_user(self):
        user = User.objects.create_user(username='dropdown_user', password='pw')
        self.client.force_login(user)
        response = self.client.get(reverse('notebooks:dashboard'))
        self.assertContains(response, 'id="notif-dropdown"')
        self.assertContains(response, 'id="notif-list"')
        self.assertContains(response, 'id="notif-mark-all-read"')

    def test_no_notif_bell_markup_for_anonymous_visitor(self):
        response = self.client.get(reverse('notebooks:dashboard'), follow=True)
        self.assertNotContains(response, 'id="notif-dropdown"')
