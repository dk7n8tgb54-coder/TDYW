"""Attachment counts on the two operation-record list endpoints."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.evidence.models import EvidenceAttachment
from apps.equipment_lifecycle.tests.base import (
    ALL_OPERATION_PERMS, RECORDS_URL, SYSTEM_RECORDS_URL,
    make_client, make_record, make_system, make_user,
)


class OperationAttachmentCountTest(TestCase):
    def setUp(self):
        self.user = make_user('count_owner', perms=ALL_OPERATION_PERMS)
        self.client = make_client(self.user)
        self.system = make_system(self.user)

    def attachment(self, record, **overrides):
        values = dict(
            tenant_id=record.tenant_id, module='equipment_lifecycle',
            object_type='el_operation_record', object_id=str(record.id),
            file_name='proof.txt', file_path='test/proof.txt', file_size=1,
        )
        values.update(overrides)
        return EvidenceAttachment.objects.create(**values)

    def rows(self, url, params=None):
        result = self.client.get(url, params or {})
        self.assertEqual(result.status_code, 200)
        payload = result.json()
        self.assertFalse(payload.get('error'), payload)
        return {row['id']: row for row in payload['data']['data']}

    def test_both_lists_count_only_active_attachments_owned_by_record(self):
        empty = make_record(self.user, self.system, title='empty')
        target = make_record(self.user, self.system, title='target')
        other = make_record(self.user, self.system, title='other')
        self.attachment(target)
        self.attachment(target)
        self.attachment(target, is_deleted=True)
        self.attachment(target, module='contract_agreement')
        self.attachment(target, object_type='other_type')
        self.attachment(target, tenant_id='another_tenant')
        self.attachment(other)
        for url in (RECORDS_URL + '/', SYSTEM_RECORDS_URL % self.system.id):
            rows = self.rows(url)
            self.assertEqual(rows[empty.id]['attachment_count'], 0)
            self.assertEqual(rows[target.id]['attachment_count'], 2)
            self.assertEqual(rows[other.id]['attachment_count'], 1)
        self.assertEqual(EvidenceAttachment.objects.filter(
            object_id=str(target.id), is_deleted=False).count(), 5)

    def test_tenant_and_record_access_boundaries(self):
        own = make_record(self.user, self.system)
        self.attachment(own)
        foreign_user = make_user('count_foreign', perms=ALL_OPERATION_PERMS,
                                 tenant_id='other')
        foreign_system = make_system(foreign_user, tenant_id='other',
                                     system_code='SYS-OTHER')
        foreign = make_record(foreign_user, foreign_system, tenant_id='other')
        self.attachment(foreign)
        self.assertEqual(set(self.rows(RECORDS_URL + '/')), {own.id})
        self.assertIn('error', self.client.get(
            SYSTEM_RECORDS_URL % foreign_system.id).json())
        foreign_rows = {row['id']: row for row in make_client(foreign_user).get(
            RECORDS_URL + '/').json()['data']['data']}
        self.assertEqual(foreign_rows[foreign.id]['attachment_count'], 1)
        self.assertNotIn(own.id, foreign_rows)

    def test_page_aggregation_uses_one_attachment_query(self):
        records = [make_record(self.user, self.system, title=str(i))
                   for i in range(12)]
        for record in records:
            self.attachment(record)
        for url in (RECORDS_URL + '/', SYSTEM_RECORDS_URL % self.system.id):
            query_counts = []
            for page_size in (1, 10):
                with CaptureQueriesContext(connection) as queries:
                    rows = self.rows(url, {'page_size': page_size})
                attachment_queries = [q for q in queries if
                                      'tdyw_evidence_attachments' in q['sql'].lower()]
                aggregate_queries = [q for q in attachment_queries if
                                     'GROUP BY' in q['sql'].upper()]
                self.assertEqual(len(aggregate_queries), 1)
                query_counts.append(len(attachment_queries))
                self.assertEqual(len(rows), page_size)
                self.assertTrue(all(row['attachment_count'] == 1
                                    for row in rows.values()))
            self.assertEqual(query_counts[0], query_counts[1])
