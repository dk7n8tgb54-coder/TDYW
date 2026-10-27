import json
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
from apps.utils.test_helpers import make_client, make_user, setup_test_env


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
            interference_kind_code='intermittent',
            affected_system_code='communication',
            source_type_code='ground_equipment',
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


class InterferenceAirUnitRetiredTest(TestCase):
    """高度/时间单位字段下线契约：旧参数拒绝，视图不再返回单位。"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('interference_air_unit', [
            'interference.interference.view',
            'interference.interference.add',
        ])
        self.client_auth = make_client(self.user)

    def _payload(self, **extra_air):
        air = {
            'route': 'HFE-VVO',
            'alert_frequency': '118.6',
            'alert_altitude': 1200,
            'alert_segment': '',
            'duration': 45,
        }
        air.update(extra_air)
        return {
            'datetime': '2026-10-02 10:00:00',
            'scene_code': 'air',
            'air_detail': air,
        }

    def test_stale_unit_params_are_rejected(self):
        for stale_key in ('alert_altitude_unit', 'duration_unit'):
            response = self.client_auth.post(
                '/interference/events/', self._payload(**{stale_key: 'ft'}),
                content_type='application/json')
            data = json.loads(response.content)
            self.assertIn(stale_key, data.get('error', ''),
                          '旧参数 %s 应被显式拒绝' % stale_key)

    def test_legacy_flat_unit_params_are_rejected(self):
        payload = self._payload()
        payload.pop('air_detail')
        payload['alert_altitude_unit'] = 'ft'
        response = self.client_auth.post(
            '/interference/events/', payload,
            content_type='application/json')
        data = json.loads(response.content)
        self.assertIn('alert_altitude_unit', data.get('error', ''))

    def test_air_detail_view_has_no_unit_fields(self):
        event = InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id,
            datetime=datetime(2026, 10, 2, 10, 0),
            scene_code='air', created_by=self.user,
        )
        air = AirInterferenceDetail.objects.create(
            event=event, tenant_id=self.user.tenant_id,
            alert_altitude=1200, duration=45,
        )
        view = air.to_view()
        self.assertEqual(view['alert_altitude'], 1200)
        self.assertEqual(view['duration'], 45)
        self.assertNotIn('alert_altitude_unit', view)
        self.assertNotIn('alert_altitude_text', view)
        self.assertNotIn('duration_unit', view)
        self.assertNotIn('duration_text', view)
