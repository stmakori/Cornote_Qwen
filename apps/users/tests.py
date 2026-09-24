"""Tests for the password reset flow (previously missing entirely - a user who
forgot their password had no recovery path)."""
import re

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='forgetful', email='forgetful@example.com', password='OldPass1234!',
        )

    def test_requesting_reset_sends_an_email(self):
        response = self.client.post(reverse('users:password_reset'), {'email': 'forgetful@example.com'})
        self.assertRedirects(response, reverse('users:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Reset your Cornote password', mail.outbox[0].subject)
        self.assertIn('forgetful@example.com', mail.outbox[0].to)

    def test_email_contains_a_working_reset_link(self):
        self.client.post(reverse('users:password_reset'), {'email': 'forgetful@example.com'})
        body = mail.outbox[0].body
        match = re.search(r'/users/reset/(?P<uidb64>[^/]+)/(?P<token>[^/\s]+)/', body)
        self.assertIsNotNone(match, 'reset link not found in email body')

        # First GET redirects to a session-tokened URL (Django's set-password
        # flow), following it should render a valid confirm form.
        response = self.client.get(
            reverse('users:password_reset_confirm', kwargs=match.groupdict()), follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Set a new password')

    def test_unknown_email_does_not_reveal_whether_account_exists(self):
        # Django's PasswordResetView always redirects the same way regardless
        # of whether the email matches an account, to avoid leaking who has one.
        response = self.client.post(reverse('users:password_reset'), {'email': 'nobody@example.com'})
        self.assertRedirects(response, reverse('users:password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_can_actually_set_a_new_password_and_log_in_with_it(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        # Follow the same session-token dance the real flow uses: GET the
        # uidb64/token URL once (Django swaps it for a session-stored token
        # and redirects to .../set-password/), then POST the new password there.
        session = self.client.session
        get_response = self.client.get(
            reverse('users:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token}), follow=True,
        )
        self.assertEqual(get_response.status_code, 200)

        post_response = self.client.post(get_response.wsgi_request.path, {
            'new_password1': 'BrandNewPass1234!',
            'new_password2': 'BrandNewPass1234!',
        })
        self.assertRedirects(post_response, reverse('users:password_reset_complete'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNewPass1234!'))
        self.assertFalse(self.user.check_password('OldPass1234!'))

    def test_expired_or_reused_token_shows_invalid_link_message(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(
            reverse('users:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': 'bogus-token'}),
            follow=True,
        )
        self.assertContains(response, 'Link expired')

    def test_reset_form_inputs_are_styled_like_the_rest_of_the_app(self):
        # Django's stock PasswordResetForm/SetPasswordForm render bare inputs
        # with no CSS class, which looked like unstyled browser widgets on the
        # dark theme. Both steps should now carry the app's form-control class.
        response = self.client.get(reverse('users:password_reset'))
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'class="form-control"')
        self.assertContains(response, 'for="id_email"')

        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.get(
            reverse('users:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token}), follow=True,
        )
        self.assertContains(response, 'name="new_password1"')
        self.assertContains(response, 'for="id_new_password1"')
        self.assertEqual(response.content.decode().count('class="form-control"'), 2)


class LoginViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sam', password='CorrectHorse1!')
        self.url = reverse('users:login')

    def test_successful_login_redirects_to_dashboard(self):
        response = self.client.post(self.url, {'username': 'sam', 'password': 'CorrectHorse1!'})
        self.assertRedirects(response, reverse('notebooks:dashboard'), fetch_redirect_response=False)

    def test_wrong_password_shows_inline_error_and_stays_on_page(self):
        response = self.client.post(self.url, {'username': 'sam', 'password': 'nope'})
        self.assertEqual(response.status_code, 200)
        # The error is rendered inside the card (non_field_errors), not only as a flash.
        self.assertContains(response, 'alert-danger')
        self.assertContains(response, 'Please enter a correct username and password')

    def test_safe_next_url_is_honoured(self):
        response = self.client.post(
            self.url + '?next=/notebooks/upload/', {'username': 'sam', 'password': 'CorrectHorse1!'},
        )
        self.assertRedirects(response, '/notebooks/upload/', fetch_redirect_response=False)

    def test_next_is_carried_in_a_hidden_field_so_it_survives_a_failed_attempt(self):
        response = self.client.get(self.url + '?next=/notebooks/upload/')
        self.assertContains(response, 'name="next" value="/notebooks/upload/"')
        # Hidden field alone (no query string) must still work on the POST.
        response = self.client.post(
            self.url, {'username': 'sam', 'password': 'CorrectHorse1!', 'next': '/notebooks/upload/'},
        )
        self.assertRedirects(response, '/notebooks/upload/', fetch_redirect_response=False)

    def test_external_next_url_is_ignored_not_an_open_redirect(self):
        for evil in ('https://evil.example/phish', '//evil.example', 'http://evil.example'):
            response = self.client.post(
                self.url + '?next=' + evil, {'username': 'sam', 'password': 'CorrectHorse1!'},
            )
            self.assertRedirects(response, reverse('notebooks:dashboard'), fetch_redirect_response=False)
            self.client.logout()

    def test_labels_are_associated_with_their_inputs(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'for="id_username"')
        self.assertContains(response, 'for="id_password"')

    def test_already_authenticated_user_is_sent_to_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('notebooks:dashboard'), fetch_redirect_response=False)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('users:logout')).status_code, 405)
        response = self.client.post(reverse('users:logout'))
        self.assertRedirects(response, reverse('users:login'), fetch_redirect_response=False)


class RegisterViewTests(TestCase):
    def test_register_creates_user_and_profile_and_logs_in(self):
        response = self.client.post(reverse('users:register'), {
            'username': 'newbie', 'email': 'newbie@example.com',
            'password1': 'Sturdy-Pass-9876', 'password2': 'Sturdy-Pass-9876',
        })
        self.assertRedirects(response, reverse('notebooks:dashboard'), fetch_redirect_response=False)
        user = User.objects.get(username='newbie')
        self.assertEqual(user.email, 'newbie@example.com')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_mismatched_passwords_rerender_with_field_error(self):
        response = self.client.post(reverse('users:register'), {
            'username': 'newbie', 'email': 'newbie@example.com',
            'password1': 'Sturdy-Pass-9876', 'password2': 'different',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalid-feedback')
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_email_is_required(self):
        response = self.client.post(reverse('users:register'), {
            'username': 'newbie', 'email': '',
            'password1': 'Sturdy-Pass-9876', 'password2': 'Sturdy-Pass-9876',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newbie').exists())


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='timer', password='Tick-Tock-4321')
        self.url = reverse('users:profile')

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_saves_valid_durations(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'focus_duration': 50, 'break_duration': 10})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        profile = self.user.profile
        self.assertEqual((profile.focus_duration, profile.break_duration), (50, 10))

    def test_rejects_out_of_range_durations_without_saving(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {'focus_duration': 500, 'break_duration': 0})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalid-feedback')
        profile = self.user.profile
        self.assertEqual((profile.focus_duration, profile.break_duration), (25, 5))


class LandingPageTests(TestCase):
    def test_renders_for_anonymous_visitor_with_working_links(self):
        response = self.client.get(reverse('landing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('users:register'))
        self.assertContains(response, reverse('users:demo_login'))
        self.assertContains(response, reverse('users:password_reset'))
        # No dead placeholder links left in the footer.
        self.assertNotContains(response, 'href="#"')

    def test_renders_for_authenticated_visitor(self):
        user = User.objects.create_user(username='back', password='Again-1234-Pls')
        self.client.force_login(user)
        response = self.client.get(reverse('landing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('notebooks:dashboard'))
