from datetime import datetime

from django.test import TestCase

from apps.interference.models import (
    AirInterferenceDetail,
    GroundInterferenceDetail,
    InvestigationEvent,
    InterferenceEvent,
    InterferenceInvestigation,
    SpectrumMeasurement,
)
from apps.utils.test_helpers import make_user


class InterferenceFinalModelTest(TestCase):
    def setUp(self):
        self.user = make_user('interference_final', [
            'interference.interference.view',
            'interference.interference.add',
            'interference.interference.edit',
            'interference.interference.del',
            'interference.investigation.view',
            'interference.investigation.add',
            'interference.investigation.edit',
            'interference.investigation.del',
            'interference.measurement.view',
            'interference.measurement.add',
        ])

    def test_shared_primary_key_details_and_public_aircraft_fields(self):
        event = InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id,
            datetime=datetime(2026, 8, 1, 10, 0),
            scene_code='cross',
            classification_status='confirmed',
            interference_kind_code='intermittent',
            affected_system_code='communication',
            source_type_code='vehicle_power',
            flight_number='CA1234', aircraft_no='B-2026', aircraft_type='A320',
            phenomenon='杂音', created_by=self.user,
        )
        ground = GroundInterferenceDetail.objects.create(
            event=event, tenant_id=self.user.tenant_id,
            location='3号机位', frequency='118.6', ground_equipment='电源车',
        )
        air = AirInterferenceDetail.objects.create(
            event=event, tenant_id=self.user.tenant_id,
            route='HFE-VVO', alert_frequency='118.6', alert_altitude=1200,
            duration=45,
        )
        self.assertEqual(ground.pk, event.pk)
        self.assertEqual(air.pk, event.pk)
        self.assertEqual(event.to_view()['aircraft_no'], 'B-2026')

    def test_investigation_duplicate_link_is_rejected(self):
        event = InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id, datetime=datetime.now(),
            scene_code='unknown', created_by=self.user,
        )
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=self.user.tenant_id, name='专题', created_by=self.user,
        )
        InvestigationEvent.objects.create(
            tenant_id=self.user.tenant_id, investigation=investigation,
            event=event, created_by=self.user,
        )
        with self.assertRaises(Exception):
            InvestigationEvent.objects.create(
                tenant_id=self.user.tenant_id, investigation=investigation,
                event=event, created_by=self.user,
            )

    def test_measurement_belongs_to_investigation(self):
        investigation = InterferenceInvestigation.objects.create(
            tenant_id=self.user.tenant_id, name='测量专题', created_by=self.user,
        )
        measurement = SpectrumMeasurement.objects.create(
            tenant_id=self.user.tenant_id, investigation=investigation,
            measured_at=datetime.now(), location='机坪', created_by=self.user,
        )
        self.assertEqual(measurement.investigation_id, investigation.id)
