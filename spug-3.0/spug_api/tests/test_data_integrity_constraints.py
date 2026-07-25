# -*- coding: utf-8 -*-
"""Database-level regression tests for core business invariants."""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.contract_agreement.models import ContractAgreement
from apps.document.models import DocumentTransfer
from apps.utils.test_helpers import make_user


class DataIntegrityConstraintTest(TestCase):
    def setUp(self):
        self.actor = make_user('constraint_actor', is_supper=True)

    def assert_integrity_error(self, callback):
        # The savepoint keeps the surrounding TestCase transaction usable.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                callback()

    def test_active_username_is_case_insensitively_unique(self):
        make_user('ActiveAdmin', is_supper=True)
        self.assert_integrity_error(lambda: make_user('activeadmin', is_supper=True))

    def test_soft_deleted_username_can_be_reused(self):
        deleted = make_user('ReusableName', is_supper=True)
        deleted.deleted_at = timezone.now()
        deleted.deleted_by = self.actor
        deleted.save(update_fields=['deleted_at', 'deleted_by'])

        replacement = make_user('reusablename', is_supper=True)
        self.assertEqual(replacement.username, 'reusablename')

    def test_contract_date_and_conditional_fee_are_enforced(self):
        common = {
            'tenant_id': 'tenant-a',
            'contract_name': '测试合同',
            'contract_type': ContractAgreement.TYPE_SERVICE_GUARANTEE,
            'valid_start_date': date(2026, 7, 2),
            'valid_end_date': date(2026, 7, 1),
            'has_fee': True,
            'fee_amount': Decimal('-1.00'),
            'signing_party': '甲方',
            'responsible_user_id': self.actor.id,
            'responsible_user_name': self.actor.nickname,
            'created_by': self.actor,
        }
        self.assert_integrity_error(lambda: ContractAgreement.objects.create(**common))

    def test_document_transfer_numeric_ranges_are_enforced(self):
        self.assert_integrity_error(lambda: DocumentTransfer.objects.create(
            tenant_id='tenant-a',
            user=self.actor,
            transfer_type='UPLOAD',
            status='UPLOADING',
            file_name='test.bin',
            file_size=10,
            file_path='/tmp/test.bin',
            total_chunks=1,
            uploaded_chunks=2,
            progress=101,
        ))
