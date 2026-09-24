"""Tests for the study groups list page.

`study_groups_page` used to annotate `member_count=Count('members')` on a
queryset built from `filter(members=user) | filter(creator=user)).distinct()`.
Combining an OR'd filter on an M2M relation with a Count() aggregate on that
same relation produces wrong (undercounted) results for some groups - verified
empirically before this fix. member_count is now set via a plain per-group
`.members.count()` instead.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import GroupComment, Notebook, Question, StudyGroup


class StudyGroupsPageMemberCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='viewer', password='pw')
        self.client.force_login(self.user)

    def test_member_count_correct_when_user_is_plain_member_not_creator(self):
        creator = User.objects.create_user(username='creator', password='pw')
        group = StudyGroup.objects.create(name='Study Buddies', creator=creator)
        group.members.add(creator, self.user)  # 2 total members; viewer isn't the creator

        response = self.client.get(reverse('notebooks:study_groups_page'))
        my_group = next(g for g in response.context['my_groups'] if g.pk == group.pk)
        self.assertEqual(my_group.member_count, 2)

    def test_member_count_correct_when_user_is_creator_and_member(self):
        other = User.objects.create_user(username='other', password='pw')
        group = StudyGroup.objects.create(name='My Group', creator=self.user)
        group.members.add(self.user, other)

        response = self.client.get(reverse('notebooks:study_groups_page'))
        my_group = next(g for g in response.context['my_groups'] if g.pk == group.pk)
        self.assertEqual(my_group.member_count, 2)

    def test_group_appears_once_even_if_creator_is_also_in_members(self):
        group = StudyGroup.objects.create(name='Solo', creator=self.user)
        group.members.add(self.user)

        response = self.client.get(reverse('notebooks:study_groups_page'))
        matches = [g for g in response.context['my_groups'] if g.pk == group.pk]
        self.assertEqual(len(matches), 1)

    def test_public_groups_member_count_is_correct(self):
        creator = User.objects.create_user(username='pubcreator', password='pw')
        member = User.objects.create_user(username='pubmember', password='pw')
        group = StudyGroup.objects.create(name='Public Group', creator=creator, is_public=True)
        group.members.add(creator, member)

        response = self.client.get(reverse('notebooks:study_groups_page'))
        public_group = next(g for g in response.context['public_groups'] if g.pk == group.pk)
        self.assertEqual(public_group.member_count, 2)

    def test_public_groups_the_user_already_belongs_to_are_excluded(self):
        creator = User.objects.create_user(username='pubcreator2', password='pw')
        group = StudyGroup.objects.create(name='Already Joined', creator=creator, is_public=True)
        group.members.add(creator, self.user)

        response = self.client.get(reverse('notebooks:study_groups_page'))
        public_ids = [g.pk for g in response.context['public_groups']]
        self.assertNotIn(group.pk, public_ids)


class AddGroupCommentOwnershipTests(TestCase):
    """`add_group_comment` used to fetch the question by id with no ownership
    check at all, and the group-detail template renders
    `comment.question.question_text` for any comment - so a member could
    attach (and leak the text of) an arbitrary question from someone else's
    private notebook by crafting the POST with its id. The commenting UI only
    ever offers the commenter's own questions, so the server must enforce
    that too."""

    def setUp(self):
        self.member = User.objects.create_user(username='member', password='pw')
        self.client.force_login(self.member)
        self.group = StudyGroup.objects.create(name='Group', creator=self.member)
        self.group.members.add(self.member)

        self.victim = User.objects.create_user(username='victim', password='pw')
        victim_notebook = Notebook.objects.create(user=self.victim, title='Private Notes', pdf_file='fake.txt')
        self.victim_question = Question.objects.create(
            notebook=victim_notebook, question_text='Super secret private question',
        )

    def test_cannot_attach_a_comment_to_another_users_question(self):
        response = self.client.post(
            reverse('notebooks:add_comment', args=[self.group.pk]),
            {'question_id': self.victim_question.pk, 'text': 'nice question'},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(GroupComment.objects.filter(question=self.victim_question).exists())

    def test_can_attach_a_comment_to_own_question(self):
        own_notebook = Notebook.objects.create(user=self.member, title='My Notes', pdf_file='fake.txt')
        own_question = Question.objects.create(notebook=own_notebook, question_text='My own question')

        response = self.client.post(
            reverse('notebooks:add_comment', args=[self.group.pk]),
            {'question_id': own_question.pk, 'text': 'my comment'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GroupComment.objects.filter(question=own_question, author=self.member).exists())
