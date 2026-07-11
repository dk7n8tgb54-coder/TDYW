# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from celery.schedules import crontab


CONTRACT_AGREEMENT_BEAT_SCHEDULE = {
    'contract-agreement-scan-expiration': {
        'task': 'apps.contract_agreement.tasks.scan_contract_agreement_expiration',
        'schedule': crontab(hour=8, minute=10),
        'options': {
            'queue': 'contract_agreement',
            'time_limit': 600,
        },
    },
}

